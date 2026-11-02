"""gpibctl: talk to the running gpib-bridged.

    gpibctl status                 connection, address, counters (Pi and Pico)
    gpibctl watch                  every message and bus event, live (Ctrl-C stops)
    gpibctl reply TEXT             queue TEXT + newline for the GRiD's next read
    gpibctl srq STATUS             request service (SRQ) with this status byte; the GRiD's serial poll clears it
    gpibctl address N              move the bridge to GPIB address N (until restart: set it in bridge.toml)
    gpibctl offline | online       take the bridge off the bus / put it back
    gpibctl flash FILE.uf2         reboot the Pico into its bootloader and copy new firmware (run with sudo)
"""
import argparse
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from .protocol import PICO_VID

DEFAULT_SOCK = "/run/gpib-bridge/ctl.sock"


def connect(path):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(path)
    except OSError as e:
        sys.exit(f"gpibctl: can't reach the daemon at {path} ({e}).  Is gpib-bridge running?  "
                 "systemctl status gpib-bridge")
    return s


def request(path, req):
    s = connect(path)
    s.sendall((json.dumps(req) + "\n").encode())
    f = s.makefile("r")
    line = f.readline()
    s.close()
    if not line:
        sys.exit("gpibctl: the daemon closed the connection")
    return json.loads(line)


def show_status(r):
    if not r.get("connected"):
        print(f"bridge: NOT connected (port {r.get('port')})")
    else:
        print(f"bridge: {r['firmware']} on {r['port']}")
    p = r.get("pico") or {}
    print(f"GPIB address {r['address']}, handler {r['handler']}, "
          f"{'online' if p.get('online') else 'offline'}"
          + (", listening" if p.get("listener") else "") + (", talking" if p.get("talker") else ""))
    print(f"REN {'on' if r['ren'] else 'off'}, LLO {'on' if r['llo'] else 'off'}, status byte 0x{r['status_byte']:02X}"
          + (" with SRQ" if r["rsv"] else ""))
    st = r.get("stats", {})
    print(f"Pi:   {st.get('messages', 0)} messages in, {st.get('bytes_in', 0)} bytes in, "
          f"{st.get('bytes_out', 0)} bytes out, {st.get('handler_errors', 0)} handler errors")
    if p:
        print(f"Pico: {p['commands']} commands, {p['bytes_in']} bytes in, {p['bytes_out']} bytes out, "
              f"{p['polls']} polls, {p['events_lost']} events lost, {p['rx_holds']} NRFD holds, "
              f"up {p['pico_uptime_ms'] / 1000:.0f} s")


def watch(path):
    s = connect(path)
    s.sendall(b'{"cmd": "events"}\n')
    f = s.makefile("r")
    f.readline()
    print("watching (Ctrl-C stops)")
    try:
        for line in f:
            ev = json.loads(line)
            t = time.strftime("%H:%M:%S", time.localtime(ev.pop("t", time.time())))
            name = ev.pop("event")
            if name == "MESSAGE":
                print(f"{t}  MESSAGE {ev['len']} bytes{'' if ev['eoi'] else ' (no EOI)'}: {ev['data']!r}")
            else:
                extra = " ".join(f"{k}={v}" for k, v in ev.items() if k != "gen")
                print(f"{t}  {name} {extra}".rstrip())
    except KeyboardInterrupt:
        pass


def find_bootsel_device(timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for d in glob.glob("/dev/disk/by-label/RP2350") + glob.glob("/dev/disk/by-label/RPI-RP2"):
            return os.path.realpath(d)
        time.sleep(0.3)
    return None


def touch_1200():
    try:
        import serial
        import serial.tools.list_ports
    except ImportError:
        return
    for p in serial.tools.list_ports.comports():
        if p.vid == PICO_VID:
            try:
                s = serial.Serial(p.device, 1200)
                s.dtr = False
                s.close()
                print(f"1200-baud touch on {p.device}")
            except (serial.SerialException, OSError):
                pass


def flash(path, uf2):
    if not os.path.exists(uf2):
        sys.exit(f"gpibctl: {uf2} not found")
    if os.geteuid() != 0:
        sys.exit("gpibctl flash needs root to mount the Pico's drive: sudo gpibctl flash " + uf2)
    dev = find_bootsel_device(0.1)
    if not dev:
        try:
            print(request(path, {"cmd": "bootsel", "hold": 30}).get("note", ""))
        except SystemExit:
            print("daemon not running: hold BOOTSEL on the Pico while plugging it in")
        dev = find_bootsel_device(4)
        if not dev:
            touch_1200()                       # the bench firmware (arduino-pico) reboots on a 1200-baud touch
            dev = find_bootsel_device()
    if not dev:
        sys.exit("gpibctl: no RP2350 bootloader drive appeared")
    mnt = tempfile.mkdtemp(prefix="rp2350-")
    subprocess.run(["mount", dev, mnt], check=True)
    try:
        shutil.copyfile(uf2, os.path.join(mnt, os.path.basename(uf2)))
        os.sync()
        print(f"copied {uf2} to the Pico; it reboots into the new firmware")
    finally:
        subprocess.run(["umount", mnt], check=False)
        os.rmdir(mnt)
    time.sleep(3)
    # restart whichever of the two services was using the bridge (try-restart: only if it was running)
    subprocess.run(["systemctl", "try-restart", "gpib-bridge", "gridlink"], check=False)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gpibctl", description="control the GPIB-Pico2 bridge daemon",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--ctl", default=os.environ.get("GPIB_CTL", DEFAULT_SOCK))
    ap.add_argument("--json", action="store_true", help="print the daemon's raw answer")
    ap.add_argument("cmd", choices=["status", "watch", "reply", "srq", "address", "offline", "online", "flash"])
    ap.add_argument("arg", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "watch":
        return watch(a.ctl)
    if a.cmd == "flash":
        if not a.arg:
            ap.error("flash FILE.uf2")
        return flash(a.ctl, a.arg[0])
    if a.cmd == "status":
        req = {"cmd": "status"}
    elif a.cmd == "reply":
        req = {"cmd": "reply", "text": " ".join(a.arg) + "\n"}
    elif a.cmd == "srq":
        req = {"cmd": "srq", "status": int(a.arg[0], 0) if a.arg else 1}
    elif a.cmd == "address":
        if not a.arg:
            ap.error("address N")
        req = {"cmd": "address", "address": int(a.arg[0])}
    else:
        req = {"cmd": a.cmd}
    r = request(a.ctl, req)
    if a.json or a.cmd != "status":
        print(json.dumps(r, indent=1))
    else:
        show_status(r)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
