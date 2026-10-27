#!/usr/bin/env python3
"""End-to-end test of the bridge firmware + Pi daemon, with no hardware.

Builds sim/host/bus_sim (the real gpib_engine.c and host_link.c on a modelled board and bus, a controller playing
the 1520, and a second instrument at address 5), starts the real Pi daemon (pi/gpibbridge) on the simulation's
pseudo-terminal, and runs:

  A  THRUTEST's nine steps, against the thrutest handler (the same checks the 1520 makes)
  B  traffic to the other instrument while the bridge is online: it must not take part or disturb it
  C  SRQ and serial poll
  D  big messages both ways (beyond the 240-byte frames and the reply credit)
  E  the Pi daemon stops: the bridge must go offline and leave the bus alone; then it comes back
  F  the scpi handler: queries, errors, status byte
  G  address change from the Pi
  H  a message ended without EOI; NRFD flow control while the Pi stalls and while the Pico's USB output stalls
  I  the daemon stalls past the Pico's 5 s PING timeout and must recover on its own
  J  gridlink's own Pico transport in auto service request mode, the way CLAUDE.COM reads (when the
     lodestone repo's claude-link is at $LODESTONE_LINK)
  K  a reply read twice at once, after replies dropped as stale on arrival (TALK_WAIT on CREDIT's scale)
  L  the daemon on a fake port whose write fails in the ping thread while the main loop reads it

usage: run_sim_tests.py          (writes sim/host/sim_results.txt)
"""
import collections
import struct
import json
import os
import random
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
LODESTONE_LINK = os.environ.get("LODESTONE_LINK", os.path.join(ROOT, "..", "claude-link"))   # gridlink, next door
FW = os.path.join(ROOT, "firmware", "bridge")
PI = os.path.join(ROOT, "pi")
SIM = os.path.join(HERE, "bus_sim")
CTL = "/tmp/gpib_sim_ctl.sock"
BENCH_ID = b"GPIB-Pico2,bench test,rev 1.2,addr 10\n"

results = []
out = []


def say(s=""):
    print(s, flush=True)
    out.append(s)


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    say(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))


class Sim:
    def __init__(self):
        subprocess.run(["gcc", "-O2", "-Wall", "-DGPIB_SIM", f"-I{FW}", "-o", SIM, os.path.join(HERE, "bus_sim.c"),
                        os.path.join(FW, "gpib_engine.c"), os.path.join(FW, "host_link.c"), "-lpthread"],
                       check=True)
        self.p = subprocess.Popen([SIM], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.pty = self.p.stdout.readline().split()[1]

    def cmd(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        r = self.p.stdout.readline().split()
        assert r and r[0] == "ok", (line, r)
        return r[1:]

    def write(self, addr, data, eoi=True):
        r = self.cmd(f"write {addr} {data.hex() or '-'} {1 if eoi else 0}")
        return int(r[0]), int(r[1])

    def read(self, addr, n=80):
        r = self.cmd(f"read {addr} {n}")
        return int(r[0]), (b"" if r[1] == "-" else bytes.fromhex(r[1])), int(r[2])

    def stats(self):
        return dict(kv.split("=") for kv in self.cmd("stats"))


class Daemon:
    def __init__(self, pty, handler="thrutest", address=10):
        if os.path.exists(CTL):
            os.unlink(CTL)
        env = dict(os.environ, PYTHONPATH=PI)
        self.log = open(os.path.join(HERE, f"daemon_{handler}.log"), "a")
        self.p = subprocess.Popen([sys.executable, "-m", "gpibbridge.daemon", "-c", "/nonexistent", "--port", pty,
                                   "--ctl", CTL, "--handler", handler, "--address", str(address), "-v"],
                                  env=env, stderr=self.log, stdout=self.log)
        t0 = time.time()
        while time.time() - t0 < 10:
            try:
                if ctl({"cmd": "status"}).get("pico", {}).get("online"):
                    return
            except OSError:
                pass
            time.sleep(0.2)
        raise RuntimeError("daemon did not bring the bridge online")

    def stop(self):
        self.p.terminate()
        self.p.wait(5)


def ctl(req):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(CTL)
    s.sendall((json.dumps(req) + "\n").encode())
    r = s.makefile("r").readline()
    s.close()
    return json.loads(r)


def thrutest(sim):
    say("A  THRUTEST's steps, thrutest handler, address 10")
    sim.cmd("ifc")
    check("1 bus init (IFC, REN)", True)
    r, n = sim.write(30, b"ABCD")
    check("2 empty address 30: nobody listens", r == 2, f"r={r} n={n}")
    r, s = sim.cmd("spoll 10")
    check("3 serial poll answers (status 0)", r == "0" and s == "0", f"r={r} s={s}")
    sim.write(10, b"*IDN?\n")
    r, got, end = sim.read(10)
    check("4 *IDN? query returns the bench ID with EOI", got == BENCH_ID and end == 1, f"{got!r} end={end}")
    sim.cmd("dcl")
    r, got, end = sim.read(10)
    check("5 DCL, then a read returns the ID", got == BENCH_ID and end == 1, f"{got!r}")
    pats = [bytes([1 << i for i in range(8)]), bytes([0xFF ^ (1 << i) for i in range(8)]),
            bytes([0, 0xFF, 0x55, 0xAA, 0x33, 0xCC, 0x0F, 0xF0])]
    pats += [bytes(range(s, s + 32)) for s in range(0, 256, 32)]
    random.seed(1)
    pats += [bytes(random.randrange(256) for _ in range(random.randrange(1, 120))) for _ in range(20)]
    bad = 0
    for p in pats:
        sim.write(10, p)
        r, got, end = sim.read(10, 200)
        if got != p or end != 1:
            bad += 1
            say(f"     echo mismatch: sent {p.hex()} got {got.hex()} end {end}")
    check(f"6 echo, {len(pats)} messages, every byte value both ways", bad == 0, f"{bad} wrong")
    sim.write(10, b"old message\n")
    sim.cmd("sdc 10")
    r, got, end = sim.read(10)
    check("7 SDC clears it (ID, not the old message)", got == BENCH_ID, f"{got!r}")
    sim.write(10, b"older message\n")
    sim.cmd("dcl")
    r, got, end = sim.read(10)
    check("8 DCL clears it", got == BENCH_ID, f"{got!r}")
    sim.cmd("ren 0")
    sim.cmd("ren 1")
    sim.cmd("gtl 10")
    sim.cmd("get 10")
    sim.cmd("ifc")
    time.sleep(0.5)
    st = ctl({"cmd": "status"})["stats"]
    check("9 REN off/on, GTL, GET, IFC reach the Pi",
          st.get("REN", 0) >= 2 and st.get("GTL", 0) >= 1 and st.get("GET", 0) >= 1 and st.get("IFC", 0) >= 1,
          str(st))


def reread(sim, d):
    say("K  a reply read twice at once, after replies dropped as stale on arrival")
    import signal
    drop0 = int(sim.stats()["dropped0"])
    for i in range(3):                           # the Pi answers a message only after the SDC that made it stale:
        d.p.send_signal(signal.SIGSTOP)          #  the Pico drops the reply as it arrives (tx_dropped0)
        sim.write(10, b"stale %d\n" % i)
        sim.cmd("sdc 10")
        d.p.send_signal(signal.SIGCONT)
        time.sleep(0.3)
    drops = int(sim.stats()["dropped0"]) - drop0
    check("replies made stale by an SDC are dropped on arrival", drops > 0, f"dropped0 +{drops}")
    sim.cmd("tmo 500")
    bad = 0
    for i in range(20):                          # (a race with the CREDIT: before the fix, about half of these
        msg = b"again %d\n" % i                  #  second reads timed out in the simulation)
        sim.write(10, msg)
        r, got, end = sim.read(10)
        r, got2, end2 = sim.read(10)             # at once, within the CREDIT's 5 ms: TALK_WAIT's arg must count the
        if got != msg or got2 != msg:            #  drops as CREDIT does, or the reply looks still on its way
            bad += 1
            say(f"     {msg!r}: read {got!r}, read again {got2!r}")
    sim.cmd("tmo 2000")
    check("20 replies read twice at once: the second read answered too (on_talk)", bad == 0, f"{bad} wrong")


def other_device(sim):
    say("B  the other instrument (address 5) with the bridge online")
    before = ctl({"cmd": "status"})["stats"].get("messages", 0)
    ok = True
    for i in range(10):
        msg = f"VDC;RANGE {i}\n".encode()
        r, n = sim.write(5, msg)
        dev = sim.cmd("dev")[0]
        if r != 0 or bytes.fromhex(dev) != msg:
            ok = False
            say(f"     write to 5: r={r} dev got {dev}")
        r, got, end = sim.read(5)
        if got != b"+1.234567E+00\n":
            ok = False
            say(f"     read from 5: {got!r}")
    check("20 writes/reads to address 5 all correct", ok)
    after = ctl({"cmd": "status"})["stats"].get("messages", 0)
    check("the bridge passed none of that traffic to the Pi", after == before, f"{before} -> {after}")
    sim.write(10, b"*IDN?\n")
    r, got, end = sim.read(10)
    check("the bridge still answers afterwards", got == BENCH_ID)


def srq(sim):
    say("C  SRQ and serial poll")
    check("SRQ released at first", sim.cmd("srq")[0] == "0")
    ctl({"cmd": "srq", "status": 0x05})
    time.sleep(0.2)
    check("SRQ asserted after the Pi requests service", sim.cmd("srq")[0] == "1")
    r, s = sim.cmd("spoll 10")
    check("serial poll returns 0x45 (RQS + 0x05)", r == "0" and int(s) == 0x45, f"r={r} s={s}")
    check("SRQ released after the poll", sim.cmd("srq")[0] == "0")
    r, s = sim.cmd("spoll 10")
    check("a second poll returns 0x05 (no RQS)", int(s) == 0x05, f"s={s}")
    sim.write(10, b"hello\n")                    # a reply (a TX frame) after the poll must not revive the SRQ
    sim.read(10)
    check("SRQ stays released after the next message and reply", sim.cmd("srq")[0] == "0")
    r, s = sim.cmd("spoll 10")
    check("and the poll after that has no RQS", int(s) == 0x05, f"s={s}")
    ctl({"cmd": "srq", "status": 0x05})
    time.sleep(0.2)
    check("a second, new request asserts SRQ again", sim.cmd("srq")[0] == "1")
    r, s = sim.cmd("spoll 10")
    check("served by its poll (0x45)", int(s) == 0x45 and sim.cmd("srq")[0] == "0", f"s={s}")
    ctl({"cmd": "status_byte", "status": 0})
    time.sleep(0.1)


def big(sim):
    say("D  big messages")
    for n in (241, 1000, 5000, 20000):
        data = bytes((i * 7 + 3) & 0xFF for i in range(n))
        r, sent = sim.write(10, data)
        r2, got, end = sim.read(10, n + 10)
        check(f"{n} bytes in and echoed back", sent == n and got == data and end == 1,
              f"sent={sent} got={len(got)} end={end}")
    st = sim.stats()
    say(f"     Pico NRFD holds (Pi slower than the bus) so far: {st['holds']}")


def stall_recovery(sim, d):
    say("I  the daemon stalls 5.8 s (Pico times out and goes offline), then must bring it back by itself")
    import signal
    d.p.send_signal(signal.SIGSTOP)
    time.sleep(5.8)
    d.p.send_signal(signal.SIGCONT)
    time.sleep(3.0)
    sim.write(10, b"*IDN?\n")
    r, got, end = sim.read(10)
    check("back online without a restart", got == BENCH_ID, repr(got))


def offline(sim, d):
    say("E  the Pi daemon stops")
    d.stop()
    time.sleep(1.0)
    st = sim.stats()
    check("bridge offline once the port closes", st["online"] == "0", str(st))
    check("bridge drives no bus line", sim.cmd("drives")[0] == "0")
    r, n = sim.write(10, b"*IDN?\n")
    check("a write to 10 finds nobody (like a powered-off instrument)", r == 2, f"r={r}")
    r, n = sim.write(5, b"VDC\n")
    r2, got, end = sim.read(5)
    check("address 5 still works", r == 0 and got == b"+1.234567E+00\n")
    d2 = Daemon(sim.pty)
    sim.write(10, b"*IDN?\n")
    r, got, end = sim.read(10)
    check("daemon restarted: answers again", got == BENCH_ID, f"{got!r}")
    return d2


def scpi(sim):
    say("F  scpi handler")
    d = Daemon(sim.pty, handler="scpi")

    def q(s):
        sim.write(10, s.encode())
        r, got, end = sim.read(10)
        return got
    idn = q("*IDN?\n")
    check("*IDN?", idn.startswith(b"PounceLab,GPIB-Pico2 Bridge,") and idn.endswith(b"\n"), repr(idn))
    check("two queries in one message", q("*OPC?;ECHO hello\n") == b"1;hello\n")
    sim.write(10, b"BOGUS 1\n")
    e1 = q("SYST:ERR?\n")
    check("an unknown command queues -113", e1 == b'-113,"Undefined header"\n', repr(e1))
    e2 = q("syst:err?\n")
    check("error queue empty again", e2 == b'0,"No error"\n', repr(e2))
    sim.write(10, b"*ESE 32;*SRE 32\n")
    sim.write(10, b"NOPE\n")
    time.sleep(0.2)
    check("command error with ESE/SRE set raises SRQ", sim.cmd("srq")[0] == "1")
    r, s = sim.cmd("spoll 10")
    check("poll shows RQS + ESB (0x60) + EAV (0x04)", int(s) == 0x64, f"s={s}")
    q("*CLS;*OPC?\n")
    r, got, end = sim.read(10)
    check("read with no query: times out (488.2), nothing sent", got == b"", repr(got))
    d.stop()


def address_change(sim):
    say("G  address change from the Pi")
    d = Daemon(sim.pty, address=10)
    ctl({"cmd": "address", "address": 7})
    time.sleep(0.3)
    r, n = sim.write(10, b"*IDN?\n")
    check("nobody at 10 after moving to 7", r == 2)
    sim.write(7, b"*IDN?\n")
    r, got, end = sim.read(7)
    check("answers at 7", got == BENCH_ID, repr(got))
    d.stop()
    d = Daemon(sim.pty, address=30)
    sim.write(30, b"*IDN?\n")
    r, got, end = sim.read(30)
    check("started with address 30 from the command line/config", got == BENCH_ID)
    d.stop()


def no_eoi_and_flow(sim, d):
    say("H  a message without EOI (ended by UNL), and NRFD flow control when the Pi stalls")
    r, n = sim.write(10, b"no eoi here", eoi=False)
    r2, got, end = sim.read(10)
    check("message ended by UNL reaches the Pi and is echoed", got == b"no eoi here" and end == 1, repr(got))
    import signal
    sim.cmd("tmo 10000")
    data = bytes((i * 13 + 1) & 0xFF for i in range(30000))
    holds0 = int(sim.stats()["holds"])
    d.p.send_signal(signal.SIGSTOP)              # the Pi stops reading for 2.5 s mid-message
    import threading
    threading.Timer(2.5, lambda: d.p.send_signal(signal.SIGCONT)).start()
    r, sent = sim.write(10, data)
    r2, got, end = sim.read(10, 40000)
    holds = int(sim.stats()["holds"]) - holds0
    check("30000 bytes with the Pi stalled 2.5 s: all accepted, echoed intact", sent == len(data) and got == data,
          f"sent={sent} got={len(got)}")
    say(f"     (NRFD holds meanwhile: {holds} -- the pty's kernel buffer may absorb it all)")
    holds0 = int(sim.stats()["holds"])
    sim.cmd("usbstall 2500")                     # the Pico's USB IN path stops for 2.5 s (host not taking data)
    r, sent = sim.write(10, data)
    r2, got, end = sim.read(10, 40000)
    holds = int(sim.stats()["holds"]) - holds0
    check("30000 bytes with the Pico's USB output stalled 2.5 s: echoed intact", sent == len(data) and got == data,
          f"sent={sent} got={len(got)}")
    check("...and NRFD was held meanwhile (frames wait, nothing dropped)", holds > 0, f"holds={holds}")
    sim.cmd("tmo 2000")


def gridlink_auto_srq(sim):
    """The real gridlink.pico.PicoBridge (the transport gridlink uses) on the simulated bridge, auto service
    request mode, with the 1520's GLP pattern: write a frame, wait for SRQ, serial poll (60h), read."""
    say("J  gridlink's Pico transport, auto service request (CLAUDE.COM's way of reading)")
    sys.path.insert(0, LODESTONE_LINK)
    import importlib
    pico = importlib.import_module("gridlink.pico")
    logs = []
    br = pico.PicoBridge(sim.pty, addr=7, log=logs.append)
    br.open()
    t0 = time.time()
    while not br.proto.online and time.time() - t0 < 5:
        time.sleep(0.05)
    check("PicoBridge connects and brings the bridge online at 7", br.proto.online, str(logs))

    def pi_answers(prefix):
        got = b""
        t0 = time.time()
        while time.time() - t0 < 3:
            got += br.read()
            if got.endswith(b"\n"):
                break
        if got:
            br.answer(prefix + got)
        return got

    r, n = sim.write(7, b"GLP frame 1\n")
    got = pi_answers(b"answer to ")
    check("the GRiD's frame reaches the Pi whole", got == b"GLP frame 1\n", repr(got))
    time.sleep(0.2)
    check("SRQ asserted once the whole answer is in the bridge", sim.cmd("srq")[0] == "1")
    r, s_ = sim.cmd("spoll 7")
    check("serial poll: 60h (RQS + READY)", int(s_) == 0x60, f"s={s_}")
    check("SRQ released by the poll", sim.cmd("srq")[0] == "0")
    r, s2 = sim.cmd("spoll 7")
    check("polled again before reading: 20h (READY, no RQS)", int(s2) == 0x20, f"s={s2}")
    r, data, end = sim.read(7, 255)
    check("the read gets the answer with EOI", data == b"answer to GLP frame 1\n" and end == 1, repr(data))
    r, s3 = sim.cmd("spoll 7")
    check("after the read: 00h", int(s3) == 0, f"s={s3}")
    check("and no SRQ", sim.cmd("srq")[0] == "0")
    # a stale answer: the GRiD gives up and sends SDC before reading
    sim.write(7, b"GLP frame 2\n")
    pi_answers(b"answer to ")
    time.sleep(0.2)
    sim.cmd("sdc 7")
    time.sleep(0.1)
    r, s4 = sim.cmd("spoll 7")
    check("SDC makes the waiting answer stale: SRQ gone, status 00h", sim.cmd("srq")[0] == "0" and int(s4) == 0,
          f"s={s4}")
    sim.write(7, b"GLP frame 3\n")
    pi_answers(b"answer to ")
    time.sleep(0.2)
    r, s5 = sim.cmd("spoll 7")
    r, data, end = sim.read(7, 255)
    check("the next exchange works (60h, then its own answer, not the stale one)",
          int(s5) == 0x60 and data == b"answer to GLP frame 3\n", f"s={s5} {data!r}")
    # 50 exchanges of full-size frames (254 bytes, every byte value)
    bad = 0
    for i in range(50):
        body = bytes((i * 31 + k) & 0xFF for k in range(240)) + b"\n"
        sim.write(7, body)
        got = b""
        t0 = time.time()
        while time.time() - t0 < 3 and len(got) < len(body):
            got += br.read()
        br.answer(got[:253] + b"\x00")
        t0 = time.time()
        while sim.cmd("srq")[0] != "1" and time.time() - t0 < 3:
            pass
        r, st = sim.cmd("spoll 7")
        r, data, end = sim.read(7, 255)
        if int(st) != 0x60 or data != got[:253] + b"\x00" or end != 1:
            bad += 1
    check("50 full-size exchanges (254-byte answers), every one right", bad == 0, f"{bad} bad")
    # big answers (CLAUDE 1.3 reads 2 KB frames): gridlink splits each into TX frames of 512 that fit the
    # firmware's 600-byte input buffer, EOI only on the last (and since fw 2026-10-23a, EARLY on the first)
    bad = 0
    for i in range(20):
        sim.write(7, b"GLP big %d\n" % i)
        got = b""
        t0 = time.time()
        while time.time() - t0 < 3 and not got.endswith(b"\n"):
            got += br.read()
        ans = bytes((i * 7 + k * 13) & 0xFF for k in range(2056))
        br.answer(ans)
        t0 = time.time()
        while sim.cmd("srq")[0] != "1" and time.time() - t0 < 3:
            pass
        r, st = sim.cmd("spoll 7")
        r, data, end = sim.read(7, 2057)
        if int(st) != 0x60 or data != ans or end != 1:
            bad += 1
    check("20 exchanges of 2056-byte answers (split in 512s), every one right", bad == 0, f"{bad} bad")
    # EARLY (fw 2026-10-23a): the first TX frame of a big answer says the answer is ready, so the GRiD reads
    # while the rest is still on its way over USB; an announced answer that goes stale doesn't leave READY on
    check("the bridge takes EARLY answers (fw 2026-10-23a), and gridlink uses them", br.proto.early,
          br.proto.firmware)
    import threading

    def tx(g, fl, data):                      # one TX frame by hand (gridlink's credit count kept right)
        br.proto.write(pico.cobs_encode(struct.pack("<BHB", pico.F_TX, g, fl) + data))
        br.proto.sent = (br.proto.sent + len(data)) & 0xFFFFFFFF

    def ask(text):
        sim.write(7, text)
        got = b""
        t0 = time.time()
        while time.time() - t0 < 3 and not got.endswith(b"\n"):
            got += br.read()
        return br.proto.gen

    ans = bytes((k * 29 + 3) & 0xFF for k in range(2056))
    g = ask(b"GLP early\n")
    tx(g, pico.TXF_EARLY, ans[:128])
    time.sleep(0.1)
    check("EARLY: SRQ with the first 128 bytes in, before the rest", sim.cmd("srq")[0] == "1")
    r, st = sim.cmd("spoll 7")
    rest = threading.Timer(0.3, lambda: (tx(g, 0, ans[128:640]), tx(g, 0, ans[640:1152]), tx(g, 0, ans[1152:1664]),
                                         tx(g, pico.TXF_EOI | pico.TXF_ANN, ans[1664:])))
    rest.start()
    r, data, end = sim.read(7, 2057)
    rest.join()
    check("... 60h, and the read waits for the rest and gets all 2056 bytes, EOI on the last",
          int(st) == 0x60 and data == ans and end == 1, f"s={st} {len(data)} {end}")
    r, st = sim.cmd("spoll 7")
    check("... then 00h", int(st) == 0, f"s={st}")
    g = ask(b"GLP early, then SDC\n")
    tx(g, pico.TXF_EARLY, ans[:128])
    time.sleep(0.1)
    sim.cmd("sdc 7")
    time.sleep(0.1)
    r, st = sim.cmd("spoll 7")
    check("an EARLY answer the SDC made stale: SRQ gone, 00h at once", sim.cmd("srq")[0] == "0" and int(st) == 0,
          f"s={st}")
    tx(g, 0, ans[128:640]); tx(g, pico.TXF_EOI | pico.TXF_ANN, ans[640:])
    time.sleep(0.1)
    r, st = sim.cmd("spoll 7")
    check("... and still 00h when its stale rest comes", int(st) == 0, f"s={st}")
    g = ask(b"GLP early, never finished\n")
    tx(g, pico.TXF_EARLY, ans[:128])
    time.sleep(0.1)
    sim.cmd("spoll 7")
    got = ask(b"GLP the next message\n")   # (the GRiD gave up on it: a new message, no read)
    br.answer(b"the next answer\n")
    time.sleep(0.2)
    r, st = sim.cmd("spoll 7")
    r, data, end = sim.read(7, 255)
    check("an EARLY answer never finished, then a new message: its answer as usual (60h)",
          int(st) == 0x60 and data == b"the next answer\n" and end == 1, f"s={st} {data!r}")
    bad = 0
    for i in range(10):
        ask(b"GLP big after %d\n" % i)
        br.answer(ans)
        t0 = time.time()
        while sim.cmd("srq")[0] != "1" and time.time() - t0 < 3:
            pass
        r, st = sim.cmd("spoll 7")
        r, data, end = sim.read(7, 2057)
        r, st2 = sim.cmd("spoll 7")
        if int(st) != 0x60 or data != ans or end != 1 or int(st2) != 0:
            bad += 1
    check("10 more 2056-byte EARLY answers after those, every one right, 00h after each", bad == 0, f"{bad} bad")
    # event times (fw 2026-10-23b): every EVENT says when it happened on the Pico's clock; RX_END, TX_IN, SRQ
    br.proto.trace = collections.deque()
    ask(b"GLP timed\n")
    br.answer(ans)
    t0 = time.time()
    while sim.cmd("srq")[0] != "1" and time.time() - t0 < 3:
        pass
    sim.cmd("spoll 7")
    sim.read(7, 2057)
    time.sleep(0.2)
    tr = list(br.proto.trace)
    br.proto.trace = None
    by_t = [e[1] for e in sorted(tr, key=lambda e: e[2])]          # (core 0's own events come out ahead of
    want, k = ["RX_END", "TX_IN", "SRQ", "SPOLL", "TALK", "TX_DONE"], 0   #  core 1's ring: arrival isn't order)
    for n in by_t:
        if k < len(want) and n == want[k]: k += 1
    check("bridge events carry their time; by it: RX_END, TX_IN, SRQ, SPOLL, TALK, TX_DONE",
          all(len(e) == 3 for e in tr) and k == len(want), f"{by_t}")
    rt = pico.retime(tr)
    arr = sorted(e[0] for e in tr)
    check("retime puts them on the Pi's clock, in their order, none after it arrived",
          len(rt) == len(tr) and [n for _, n in rt] == by_t
          and all(r <= a + 1e-6 for (r, _), a in zip(rt, [e[0] for e in sorted(tr, key=lambda e: e[2])])),
          f"{rt[:4]}")
    held_replies(sim, br, pico, ask, tx, ans)
    # WAKE (fw 2026-10-22b): gridlink rings when it has news for an idle GRiD; SRQ (40h, no READY) until the
    # GRiD polls or sends, and a ring for an older message than the GRiD's last is void
    check("idle after the reads: no SRQ", sim.cmd("srq")[0] == "0")
    br.ring()
    time.sleep(0.1)
    check("a ring asserts SRQ", sim.cmd("srq")[0] == "1")
    r, st = sim.cmd("spoll 7")
    check("its poll: 40h (RQS, no READY), and SRQ released", int(st) == 0x40 and sim.cmd("srq")[0] == "0",
          f"s={st}")
    br.ring()
    time.sleep(0.1)
    sim.write(7, b"GLP after a ring\n")
    time.sleep(0.1)
    check("a ring ends when the GRiD sends instead of polling", sim.cmd("srq")[0] == "0")
    got = pi_answers(b"answer to ")
    time.sleep(0.2)
    r, st = sim.cmd("spoll 7")
    r, data, end = sim.read(7, 255)
    check("and that exchange is as usual (60h, its answer)", int(st) == 0x60 and data == b"answer to " + got,
          f"s={st} {data!r}")
    old_gen = (br.proto.gen - 1) & 0xFFFF
    br.proto.write(pico.cobs_encode(struct.pack("<BH", pico.F_WAKE, old_gen)))
    time.sleep(0.1)
    check("a ring for an older message is void", sim.cmd("srq")[0] == "0")
    # quiet (fw 2026-10-24): the status byte as ever, the SRQ line never driven (resident Claude's background)
    check("the firmware can be quiet", br.set_quiet(True) and br.proto.quiet)
    time.sleep(0.1)
    sim.write(7, b"GLP quiet 1\n")
    pi_answers(b"answer to ")
    time.sleep(0.2)
    srq_q = sim.cmd("srq")[0]
    r, st = sim.cmd("spoll 7")
    r, data, end = sim.read(7, 255)
    check("quiet: an answer in raises no SRQ, and the poll says 60h as ever",
          srq_q == "0" and int(st) == 0x60 and data == b"answer to GLP quiet 1\n", f"srq={srq_q} s={st} {data!r}")
    br.ring()
    time.sleep(0.1)
    srq_q = sim.cmd("srq")[0]
    r, st = sim.cmd("spoll 7")
    check("quiet: a ring raises no SRQ, its poll says 40h", srq_q == "0" and int(st) == 0x40, f"srq={srq_q} s={st}")
    sim.write(7, b"GLP quiet 2\n")
    pi_answers(b"answer to ")
    time.sleep(0.2)
    srq_q = sim.cmd("srq")[0]
    br.set_quiet(False)
    time.sleep(0.1)
    srq_n = sim.cmd("srq")[0]
    r, st = sim.cmd("spoll 7")
    r, data, end = sim.read(7, 255)
    check("quiet off with an answer's RQS waiting: SRQ then, served by the poll (60h)",
          srq_q == "0" and srq_n == "1" and int(st) == 0x60 and sim.cmd("srq")[0] == "0"
          and data == b"answer to GLP quiet 2\n", f"srq {srq_q}->{srq_n} s={st} {data!r}")
    br.stop.set()
    br._drop()
    time.sleep(6.5)                        # the bridge sees the PINGs stop and goes offline


def held_replies(sim, br, pico, ask, tx, ans):
    """F_HOLD (fw 2026-10-23c): the Pi gives the bridge the GRiD's next message, expected, and the answer to it;
    if the message is that, the bridge raises SRQ at its last byte and sends the answer, with no word from the
    Pi; if not, the held answer is dropped and the Pi answers as usual."""
    check("the bridge takes holds (fw 2026-10-23c), and gridlink uses them", br.proto.holds, br.proto.firmware)

    def drain(want):                          # the Pi side: the GRiD's message, and whether the hold answered it
        got = b""
        t0 = time.time()
        while time.time() - t0 < 3 and not got.endswith(want[-1:]):
            got += br.read()
        return got, br.proto.hold_used()

    def wait_srq(t=1.0):
        t0 = time.time()
        while sim.cmd("srq")[0] != "1" and time.time() - t0 < t:
            pass
        return sim.cmd("srq")[0] == "1"

    h1 = bytes((k * 11 + 5) & 0xFF for k in range(2056))
    ask(b"GLP hold base\n")
    br.answer(b"first answer\n")
    br.proto.hold(b"GLP poll 1\n", h1)          # (held behind the first answer, for the message after it)
    wait_srq()
    r, st = sim.cmd("spoll 7")
    r, data, end = sim.read(7, 255)
    check("hold: the answer before it goes first, as usual", int(st) == 0x60 and data == b"first answer\n",
          f"s={st} {data!r}")
    time.sleep(0.1)
    sim.write(7, b"GLP poll 1\n")
    srq = wait_srq(0.2)
    r, st = sim.cmd("spoll 7")
    r, data, end = sim.read(7, 2057)
    got, used = drain(b"\n")
    check("hold: the expected message gets SRQ, 60h and the held answer, the Pi saying nothing",
          srq and int(st) == 0x60 and data == h1 and end == 1, f"srq={srq} s={st} {len(data)}")
    check("... and the Pi gets the message, marked answered (DF_HELD)", got == b"GLP poll 1\n" and used,
          f"{got!r} {used}")
    r, st = sim.cmd("spoll 7")
    check("... then 00h", int(st) == 0, f"s={st}")
    # not the message expected: dropped, the Pi answers
    br.proto.hold(b"GLP poll 2\n", h1)
    time.sleep(0.1)
    sim.write(7, b"GLP keys\n")
    time.sleep(0.2)
    srq = sim.cmd("srq")[0]
    got, used = drain(b"\n")
    check("hold: another message gets no SRQ, and the Pi hears it wasn't answered", srq == "0" and not used
          and got == b"GLP keys\n", f"srq={srq} {got!r} {used}")
    br.answer(b"keys answered\n")
    wait_srq()
    r, st = sim.cmd("spoll 7")
    r, data, end = sim.read(7, 255)
    check("... then the Pi's own answer (60h), not the held one", int(st) == 0x60 and data == b"keys answered\n",
          f"s={st} {data!r}")
    # a message that is only the start of the one expected (EOI early), and one that is longer
    for msg, what in ((b"GLP poll", "shorter"), (b"GLP poll 3\nX", "longer")):
        br.proto.hold(b"GLP poll 3\n", h1)
        time.sleep(0.1)
        sim.write(7, msg)
        time.sleep(0.2)
        srq = sim.cmd("srq")[0]
        got, used = drain(msg)
        br.answer(b"answered " + msg + b"\n")
        wait_srq()
        r, st = sim.cmd("spoll 7")
        r, data, end = sim.read(7, 255)
        check(f"hold: a {what} message isn't it: no SRQ till the Pi answers, then that answer",
              srq == "0" and not used and data == b"answered " + msg + b"\n", f"srq={srq} {used} {data!r}")
    # too late: the hold comes after its message (by hand: gridlink's hold() is always for the next one)
    g = ask(b"GLP late\n")
    br.proto.write(pico.cobs_encode(struct.pack("<BH", pico.F_HOLD, g) + b"GLP late\n"))
    tx(g, pico.TXF_HELD | pico.TXF_EOI, b"held, too late\n")
    time.sleep(0.2)
    check("hold: one that comes after its message is void: no SRQ", sim.cmd("srq")[0] == "0")
    br.answer(b"on time\n")
    wait_srq()
    r, st = sim.cmd("spoll 7")
    r, data, end = sim.read(7, 255)
    check("... and the Pi's answer goes, not the held one", int(st) == 0x60 and data == b"on time\n",
          f"s={st} {data!r}")
    # matched, then SDC before the read: stale like any answer
    br.proto.hold(b"GLP poll 4\n", h1)
    time.sleep(0.1)
    sim.write(7, b"GLP poll 4\n")
    wait_srq(0.2)
    drain(b"\n")
    sim.cmd("sdc 7")
    time.sleep(0.1)
    r, st = sim.cmd("spoll 7")
    check("hold: a held answer the SDC made stale: SRQ gone, 00h", sim.cmd("srq")[0] == "0" and int(st) == 0,
          f"s={st}")
    ask(b"GLP after SDC\n")
    br.answer(b"after SDC\n")
    wait_srq()
    r, st = sim.cmd("spoll 7")
    r, data, end = sim.read(7, 255)
    check("... and the next exchange is as usual", int(st) == 0x60 and data == b"after SDC\n", f"s={st} {data!r}")
    # a chain, as gridlink runs it: each held answer read, the expected POLL, the next hold
    frags = [bytes((i * 37 + k * 5) & 0xFF for k in range(2056)) for i in range(12)]
    ask(b"GLP chain\n")
    br.answer(frags[0])
    bad = 0
    t_srq = []
    for i in range(1, 12):
        br.proto.hold(b"GLP poll %d\n" % i, frags[i])
        wait_srq()
        r, st = sim.cmd("spoll 7")
        r, data, end = sim.read(7, 2057)
        if int(st) != 0x60 or data != frags[i - 1] or end != 1:
            bad += 1
        time.sleep(0.02)
        t0 = time.time()
        sim.write(7, b"GLP poll %d\n" % i)
        if not wait_srq(0.5): bad += 1
        t_srq.append(time.time() - t0)
        got, used = drain(b"\n")
        if not used: bad += 1
    r, st = sim.cmd("spoll 7")
    r, data, end = sim.read(7, 2057)
    if int(st) != 0x60 or data != frags[11]:
        bad += 1
    r, st = sim.cmd("spoll 7")
    check("hold: 11 held 2 KB answers in a row, every one right, 00h after", bad == 0 and int(st) == 0,
          f"{bad} bad, s={st}")
    st = sim.stats()
    check("the Pico counted the holds", int(st.get("held", 0)) >= 13, f"{st}")
    held_glp(sim, br, pico, wait_srq, drain)


def held_glp(sim, br, pico, wait_srq, drain):
    """F_HOLD_GLP (fw 2026-10-23d): held for a GLP frame by its first 4 bytes, its length and its Fletcher sum
    (the GRiD's next fragment, whatever it carries); anything else, the Pi answers."""
    from gridlink import glp
    check("the bridge takes GLP holds (fw 2026-10-23d)", br.proto.holds_glp, br.proto.firmware)
    nop = b"held NOP\n"
    payload = bytes((k * 7 + 1) & 0xFF for k in range(3300))
    good = glp.encode(glp.G_REPLY | glp.MORE, 21, 9, payload, fl=True)
    head = good[:4]
    cases = [("a good frame", good, True),
             ("another sequence number", glp.encode(glp.G_REPLY | glp.MORE, 22, 9, payload, fl=True), False),
             ("a bad sum", good[:-1] + bytes([good[-1] ^ 1]), False),
             ("a byte changed", good[:100] + bytes([good[100] ^ 0x40]) + good[101:], False),
             ("too short (EOI early)", good[:-1], False),
             ("a byte more", good + b"\x00", False),
             ("the CRC, not the sum", glp.encode(glp.G_REPLY | glp.MORE, 21, 9, payload, fl=False), False),
             ("an empty frame", glp.encode(glp.G_REPLY | glp.MORE, 21, 9, b"", fl=True), True)]
    for what, msg, want in cases:
        br.proto.hold(msg[:4] if want and msg is not good else head, nop, glp=True)
        time.sleep(0.1)
        sim.write(7, msg)
        srq = wait_srq(0.2)
        got = b""
        t0 = time.time()
        while time.time() - t0 < 3 and len(got) < len(msg):
            got += br.read()
        used = br.proto.hold_used()
        if not used:
            br.answer(b"Pi: " + what.encode() + b"\n")
            wait_srq()
        r, st = sim.cmd("spoll 7")
        r, data, end = sim.read(7, 255)
        ok = (used == want and srq == want and got == msg and int(st) == 0x60
              and data == (nop if want else b"Pi: " + what.encode() + b"\n"))
        check(f"GLP hold, {what}: {'the held NOP' if want else 'the Pi answers'}", ok,
              f"used={used} srq={srq} s={st} {data[:20]!r} {len(got)}/{len(msg)}")


def port_gone_under_read():
    """The daemon in this process on a fake port (no simulation): its ping thread's write fails while the main
    loop is reading the port.  pyserial 3.5's in_waiting on a closed port raises TypeError, which nothing in the
    main loop catches, so the port must be closed only by the main loop.  (The thread is left running.)"""
    say("L  the port fails the ping thread's write while the main loop reads it (a fake port)")
    import logging
    import threading
    import types
    import serial
    sys.path.insert(0, PI)
    from gpibbridge import daemon, protocol as P
    logging.getLogger("gpib-bridge").setLevel(logging.CRITICAL)
    ports, bridges, closers, talkers, errors = [], [], [], [], []
    ping_failed, closed = threading.Event(), threading.Event()

    class FakePort:
        """What the daemon uses of serial.Serial; the far end of a socket pair is the bridge."""

        def __init__(self, port, *a, **kw):
            self.mine, self.far = socket.socketpair()
            self.mine.setblocking(False)
            self.dtr, self.is_open, self.trap = False, True, False
            ports.append(self)

        def fileno(self):
            return self.mine.fileno()

        def write(self, frame):
            if not self.is_open:
                raise serial.PortNotOpenError()
            if self.trap and frame == P.ping():  # the bridge is gone (unplugged, reset)
                ping_failed.set()
                raise serial.SerialException("write failed: [Errno 5] Input/output error")
            if frame == P.hello_req():
                self.far.send(P.cobs_encode(struct.pack("<BBHHIH", P.F_HELLO, P.PROTO_VERSION, 1023, P.DATA_CHUNK,
                                                        0, 0) + b"bridge fw fake"))
            return len(frame)

        @property
        def in_waiting(self):
            if self.trap:                        # the race, made certain: the main loop reads while the ping
                ping_failed.wait(3)              #  thread's write fails, and (unfixed) closes the port
                closed.wait(0.5)
            if not self.is_open:
                raise TypeError("argument must be an int, or have a fileno() method.")   # pyserial 3.5's
            try:
                return len(self.mine.recv(4096, socket.MSG_PEEK))
            except BlockingIOError:
                return 0

        def read(self, n=1):
            if not self.is_open:
                raise serial.PortNotOpenError()
            try:
                return self.mine.recv(n)
            except BlockingIOError:
                return b""

        def close(self):
            if self.is_open:
                self.is_open = False
                closers.append(threading.current_thread().name)
                self.mine.close()
                closed.set()

    class Bridge(daemon.Bridge):
        def __init__(self, cfg):
            super().__init__(cfg)
            bridges.append(self)

        def broadcast(self, ev):
            talkers.append(threading.current_thread().name)
            super().broadcast(ev)

    daemon.serial = types.SimpleNamespace(Serial=FakePort, SerialException=serial.SerialException,
                                          tools=serial.tools)
    daemon.Bridge = Bridge

    def run():
        try:
            daemon.main(["-c", "/nonexistent", "--port", "fake", "--ctl", "/tmp/gpib_sim_fake_ctl.sock"])
        except BaseException as e:               # (main() never returns)
            errors.append(e)

    threading.Thread(target=run, name="main loop", daemon=True).start()

    def wait(cond, t):
        t0 = time.time()
        while not cond() and not errors and time.time() - t0 < t:
            time.sleep(0.02)
        return cond()
    up = wait(lambda: bridges and bridges[0].connected, 3)
    check("the daemon connects to the fake port", up, repr(errors))
    if not up:
        return
    b = bridges[0]
    ports[0].trap = True
    ports[0].far.send(b"\x00")                   # something to read: the main loop goes to read it
    ok = wait(lambda: len(ports) > 1 and b.connected and b.ser is ports[-1], 5)
    check("the daemon lives through it (nothing raised out of its main loop)", not errors, repr(errors))
    check("... closes the port, reopens and is connected again", ok, f"{len(ports)} ports")
    check("only the main loop closed the port and told the control clients",
          closers == ["main loop"] and set(talkers) == {"main loop"}, f"closed by {closers}, events from {set(talkers)}")


def main():
    sim = Sim()
    say(f"bus_sim on {sim.pty}")
    d = Daemon(sim.pty)
    try:
        thrutest(sim)
        reread(sim, d)
        other_device(sim)
        srq(sim)
        big(sim)
        no_eoi_and_flow(sim, d)
        stall_recovery(sim, d)
        d = offline(sim, d)
        d.stop()
        scpi(sim)
        address_change(sim)
        if os.path.isdir(LODESTONE_LINK):
            gridlink_auto_srq(sim)
        port_gone_under_read()
    finally:
        try:
            d.stop()
        except Exception:
            pass
        st = sim.stats()
        say(f"final Pico counters: {st}")
        check("no events lost in the Pico", st["lost"] == "0")
        sim.p.stdin.write("quit\n")
        sim.p.stdin.flush()
        sim.p.wait(5)
    n_ok = sum(ok for _, ok in results)
    say(f"\n{n_ok} of {len(results)} checks passed")
    with open(os.path.join(HERE, "sim_results.txt"), "w") as f:
        f.write("\n".join(out) + "\n")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
