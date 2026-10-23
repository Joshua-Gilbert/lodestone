"""The GPIB-Pico2 bridge as gridlink's transport (in place of the AR488 Nano).

The bridge is a Raspberry Pi Pico 2 with SN75160B/SN75161B transceivers, a GPIB device at the bridge address
(7). Its firmware (`bridge fw 2026-10-16d` or later, GPIB Pico Board/firmware/bridge) speaks a COBS-framed
protocol over USB CDC, documented in that folder's PROTOCOL.md; the frame codes below mirror its host_link.h.

What it gives GLP, compared with the AR488:

* GRiD -> Pi: every message the GRiD writes arrives whole and binary-clean (DATA frames, EOI marks the end).
  No serial buffer to overrun, so GLP's alternation is still kept but no longer load-bearing.
* Pi -> GRiD: a frame is sent as one TX (binary, no escaping, EOI on the last byte). In auto service request
  mode (CONFIG flags bit 1) the bridge itself raises SRQ with status 60h (RQS + READY) once the whole frame is
  in its buffer, keeps READY until the GRiD has read it, and drops a reply that a newer GRiD message or an SDC
  has made stale -- the AR488 +GRiD1 patch's behaviour, so CLAUDE.COM needs no change.
* Frames as big as the GRiD says it takes (HELLO's rx=; 246-byte payloads for a CLAUDE that doesn't say),
  split into TX frames of TX_CHUNK so they fit the firmware's input buffer.

The bridge takes no part in the bus until we put it online, and drops off again if our PINGs stop for 5 s.
"""
import collections, glob, os, struct, threading, time

from . import glp

PICO_VID = 0x2E8A
PROTO_VERSION = 1

F_HELLO_REQ, F_CONFIG, F_TX, F_STB, F_PING, F_BOOTSEL, F_WAKE, F_HOLD = 0x01, 0x02, 0x03, 0x04, 0x05, 0x07, 0x08, 0x09
F_HOLD_GLP = 0x0A
F_HELLO, F_DATA, F_EVENT, F_LOG, F_PONG, F_CREDIT = 0x81, 0x82, 0x83, 0x84, 0x85, 0x87
CF_ONLINE, CF_AUTO_RSV = 0x01, 0x02
DF_EOI, DF_END, DF_HELD = 0x01, 0x02, 0x04
TXF_EOI, TXF_EARLY, TXF_ANN, TXF_HELD = 0x01, 0x02, 0x04, 0x08
TX_CHUNK = 512          # data bytes per TX frame: 4 + 512 + COBS's 3 fit the firmware's 600-byte input buffer
TX_FIRST = 128          # an EARLY reply's first TX frame: small, so the bridge says READY as soon as it can
EARLY_FW = 'bridge fw 2026-10-23'   # firmware from this date on takes TXF_EARLY (PROTOCOL.md)
HOLD_FW = 'bridge fw 2026-10-23c'   # and from this one F_HOLD: a reply held for the GRiD's next message
HOLD_GLP_FW = 'bridge fw 2026-10-23d'   # and F_HOLD_GLP: held for its next frame, checked by the bridge
FRAME_MAX = 4104        # GLP frames to the GRiD: 4096 payload + 8 (what the GRiD takes is its HELLO's rx=)
EVENTS = {0x10: 'LISTEN', 0x11: 'UNLISTEN', 0x12: 'TALK', 0x13: 'UNTALK', 0x14: 'TALK_WAIT', 0x15: 'DCL',
          0x16: 'SDC', 0x17: 'GET', 0x18: 'GTL', 0x19: 'LLO', 0x1A: 'IFC', 0x1B: 'REN', 0x1C: 'SPOLL',
          0x1D: 'TX_DONE', 0x1E: 'ONLINE', 0x1F: 'OFFLINE',
          0x20: 'RX_END', 0x21: 'TX_IN', 0x22: 'SRQ'}   # (fw 2026-10-23b: for the trace)


def cobs_encode(data):
    """COBS, and the 0x00 that ends the frame: each run between zeros as its length + 1 and the run (254 bytes
    at most: then FFh, and the run goes on).  By runs, not bytes: ~25 times faster in Python."""
    out = bytearray()
    for run in bytes(data).split(b'\0'):
        while len(run) >= 254:
            out.append(255); out += run[:254]; run = run[254:]
        out.append(len(run) + 1); out += run
    out.append(0)
    return bytes(out)


def cobs_decode(data):
    out = bytearray(); i, n = 0, len(data)
    while i < n:
        code = data[i]; i += 1
        if code == 0 or i + code - 1 > n: raise ValueError('bad COBS frame')
        out += data[i:i + code - 1]; i += code - 1
        if code != 0xFF and i < n: out.append(0)
    return bytes(out)


class PicoProto:
    """The protocol state, without I/O: feed() it the bytes from the Pico, it returns the bytes of the GRiD's
    messages (for Link.feed); the frames to send come out through `write`.  The emulator tests drive this
    directly; PicoBridge runs it on a real serial port."""

    def __init__(s, write, addr=7, log=print):
        s.write, s.addr, s.log = write, addr, log
        s.buf = bytearray(); s.firmware = ''; s.early = False; s.holds = s.holds_glp = False
        s.connected = False; s.online = False
        s.gen = 0; s.tx_ring = 16383; s.sent = 0; s.consumed = 0
        s.pending = collections.deque()     # (gen, frame, expect): expect is a held reply's hold, else None
        s.hold_gen = None; s.hold_hit = None  # the hold out, and whether the bridge used it (DF_HELD)
        s.pong = {}; s.last_pong = 0.0; s.hello_at = 0.0; s.pongs = 0
        s.stats = collections.Counter()
        s.trace = None                      # a deque while gridlink.bench --trace runs: (time, event)
        s.clock = time.monotonic            # (the emulator tests give theirs)
        s.tx_done_at = None                 # when the GRiD last read a whole answer (the bridge's TX_DONE)
        s.lock = threading.RLock()          # feed() runs in the reader thread, answer() in the link's

    # Pico -> Pi
    def feed(s, data):
        """Returns bytes the GRiD wrote (whole GLP frames, in order)."""
        with s.lock: return s._feed(data)

    def _feed(s, data):
        out = bytearray()
        for b in data:
            if b:
                s.buf.append(b)
                if len(s.buf) > 4096: s.buf.clear(); s.stats['bad_frames'] += 1
                continue
            if not s.buf: continue
            try:
                f = cobs_decode(bytes(s.buf))
            except ValueError:
                s.stats['bad_frames'] += 1; s.buf.clear(); continue
            s.buf.clear()
            if f: out += s._frame(f)
        return bytes(out)

    def _frame(s, f):
        t = f[0]
        if t == F_HELLO:
            proto, ring, chunk, consumed, queued = struct.unpack_from('<BHHIH', f, 1)
            s.firmware = f[12:].decode('ascii', 'replace')
            s.early = s.firmware[:len(EARLY_FW)] >= EARLY_FW and s.firmware.startswith('bridge fw ')
            s.holds = s.firmware[:len(HOLD_FW)] >= HOLD_FW and s.firmware.startswith('bridge fw ')
            s.holds_glp = s.firmware[:len(HOLD_GLP_FW)] >= HOLD_GLP_FW and s.firmware.startswith('bridge fw ')
            s.hold_gen = None
            if proto != PROTO_VERSION:
                s.log('bridge: firmware protocol %d, gridlink speaks %d: update one of them' % (proto, PROTO_VERSION))
                return b''
            s.tx_ring = ring; s.consumed = consumed; s.sent = (consumed + queued) & 0xFFFFFFFF
            s.pending.clear(); s.connected = True; s.last_pong = time.monotonic()
            s.write(cobs_encode(bytes([F_STB, 0, 0])))
            s.write(cobs_encode(bytes([F_CONFIG, s.addr, CF_ONLINE | CF_AUTO_RSV])))
            s.log('bridge: %s, GPIB address %d, auto service request' % (s.firmware, s.addr))
            return b''
        if not s.connected: return b''
        if t == F_DATA:
            gen, flags = struct.unpack_from('<HB', f, 1)
            s._gen(gen)
            s.stats['rx_bytes'] += len(f) - 4
            if flags & (DF_EOI | DF_END) and gen == s.hold_gen:   # the message the hold was for: used or not
                s.hold_hit = bool(flags & DF_HELD); s.hold_gen = None
                s.stats['held' if s.hold_hit else 'hold_missed'] += 1
            return f[4:]
        if t == F_EVENT:
            code, gen, b, arg = struct.unpack_from('<BHBI', f, 1)
            s._gen(gen)
            name = EVENTS.get(code, hex(code))
            s.stats[name] += 1
            if s.trace is not None:          # (fw 2026-10-23b: when it happened, on the Pico's us timer)
                s.trace.append((time.monotonic(), name) if len(f) < 13 else
                               (time.monotonic(), name, struct.unpack_from('<I', f, 9)[0]))
            if name == 'TX_DONE': s.tx_done_at = s.clock()
            if name == 'ONLINE': s.online = True
            elif name == 'OFFLINE':
                s.online = False
                s.write(cobs_encode(bytes([F_CONFIG, s.addr, CF_ONLINE | CF_AUTO_RSV])))   # we still want it
            return b''
        if t == F_CREDIT:
            s.consumed = struct.unpack_from('<I', f, 1)[0]; s._pump(); return b''
        if t == F_PONG:
            s.last_pong = time.monotonic(); s.pongs += 1
            s.pong = dict(zip(('online', 'address', 'listener', 'talker', 'ren', 'llo', 'spms', 'rsv'), f[1:9]))
            if not f[1]:
                s.write(cobs_encode(bytes([F_CONFIG, s.addr, CF_ONLINE | CF_AUTO_RSV])))
            return b''
        if t == F_LOG:
            s.log('bridge: ' + f[1:].decode('ascii', 'replace'))
        return b''

    def _gen(s, g):
        if g != s.gen:
            s.gen = g
            # replies for older messages go, and a held reply not yet sent once its message has come
            nxt = (g + 1) & 0xFFFF
            s.pending = collections.deque(p for p in s.pending if p[0] == (g if p[2] is None else nxt))

    # Pi -> Pico
    def answer(s, frame):
        """One GLP frame for the GRiD's next read: the reply to its last message."""
        with s.lock:
            s.pending.append((s.gen, bytes(frame), None))
            s.stats['tx_frames'] += 1
            s._pump()

    def hold(s, expect, frame, glp=False):
        """A reply held for the GRiD's next message (bridge fw 2026-10-23c): if that message is exactly `expect`
        (its next POLL, Link works it out), the bridge sends `frame` as its answer by itself, SRQ at its last
        byte, with no round trip to us; DATA's DF_HELD then says so (hold_used).  If it is anything else the
        bridge drops `frame` and we answer it as usual.  False if the firmware can't."""
        with s.lock:
            # glp (fw 2026-10-23d): `expect` is the first 4 bytes of a GLP frame (sync, type, seq, ack), and the
            # bridge sends `frame` if the message is such a frame, its length right and its Fletcher sum good
            if not ((s.holds_glp if glp else s.holds) and s.connected): return False
            if not (len(expect) == 4 if glp else 0 < len(expect) <= 16): return False
            g = (s.gen + 1) & 0xFFFF
            s.hold_gen, s.hold_hit = g, None
            s.pending.append((g, bytes(frame), (F_HOLD_GLP if glp else F_HOLD, bytes(expect))))
            s.stats['holds'] += 1
            s._pump()
            return True

    def hold_used(s):
        """Whether the bridge answered the GRiD's last message with the held reply (True), or not."""
        with s.lock:
            hit, s.hold_hit = s.hold_hit, None
            return bool(hit)

    def _pump(s):
        while s.pending and s.connected:
            g, data, expect = s.pending[0]
            room = s.tx_ring - ((s.sent - s.consumed) & 0xFFFFFFFF)
            if room < len(data): return             # the whole frame must fit before any of it goes
            if expect is not None:                  # a held reply: the hold, then the reply in 512s
                out = [cobs_encode(struct.pack('<BH', expect[0], g) + expect[1])]
                for i in range(0, len(data), TX_CHUNK):
                    fl = TXF_HELD | (TXF_EOI if i + TX_CHUNK >= len(data) else 0)
                    out.append(cobs_encode(struct.pack('<BHB', F_TX, g, fl) + data[i:i + TX_CHUNK]))
                s.write(b''.join(out))
                s.sent = (s.sent + len(data)) & 0xFFFFFFFF
                s.pending.popleft()
                continue
            # The firmware's input buffer holds a COBS frame of 600 bytes (host_link.c), so a GLP frame
            # bigger than TX_CHUNK goes as several TX frames, EOI only on the last.  Older firmware raises SRQ
            # when that one is in; from fw 2026-10-23 the first (a small one) says EARLY, and the bridge raises
            # it then: the GRiD reads while the rest crosses USB, ~3.5 times faster than it reads.  All of them
            # in one write.
            early = s.early and len(data) > TX_CHUNK
            cuts = [0, TX_FIRST] if early else [0]
            while cuts[-1] + TX_CHUNK < len(data): cuts.append(cuts[-1] + TX_CHUNK)
            cuts.append(len(data))
            out = []
            for k in range(len(cuts) - 1):
                last = k == len(cuts) - 2
                fl = (TXF_EOI | (TXF_ANN if early else 0)) if last else (TXF_EARLY if early and k == 0 else 0)
                out.append(cobs_encode(struct.pack('<BHB', F_TX, g, fl) + data[cuts[k]:cuts[k + 1]]))
            s.write(b''.join(out))
            s.sent = (s.sent + len(data)) & 0xFFFFFFFF
            s.pending.popleft()

    def hello(s):
        s.connected = False; s.hello_at = time.monotonic()
        s.write(cobs_encode(bytes([F_HELLO_REQ])))

    def ping(s):
        s.write(cobs_encode(bytes([F_PING])))

    def ring(s):
        """Ask for an SRQ while the GRiD is idle (bridge fw 2026-10-22b; older firmware ignores it).  It carries
        the generation of the GRiD's last message, so the bridge drops it if the GRiD has sent a newer one."""
        with s.lock:
            s.stats['rings'] += 1
            s.write(cobs_encode(struct.pack('<BH', F_WAKE, s.gen & 0xFFFF)))

    def unring(s):
        """Take a ring back: a WAKE for an older generation than the GRiD's last replaces the bell and is void
        at once (bridge fw 2026-10-22b), so SRQ is released."""
        with s.lock:
            s.write(cobs_encode(struct.pack('<BH', F_WAKE, (s.gen - 1) & 0xFFFF)))

    def usb_test(s, count, size, timeout=5.0):
        """gridlink.bench --usb: `count` PINGs of `size` bytes (the firmware ignores what follows the type) sent
        at once; returns the seconds until the bridge has answered them all, or None."""
        size = max(1, min(size, TX_CHUNK + 4))
        ping = cobs_encode(bytes([F_PING]) + bytes(i % 255 + 1 for i in range(size - 1)))
        want = s.pongs + count
        t0 = time.monotonic()
        s.write(ping * count)
        while s.pongs < want:
            if time.monotonic() - t0 > timeout: return None
            time.sleep(0.0002)
        return time.monotonic() - t0


def retime(trace):
    """A trace's bridge events on the bridge's own clock (fw 2026-10-23b stamps them): each moved to when it
    happened, not when it reached the Pi -- the Pico sends its events between its USB reads, so a TALK can
    arrive ms late.  The Pico's timer is put on the Pi's clock by the smallest gap seen between an event's
    stamp and its arrival (so bridge times are late by about the quickest USB delivery, ~0.1 ms).  Returns
    [(time, event)] in time order."""
    stamped = [e for e in trace if len(e) == 3]
    if not stamped: return [(e[0], e[1]) for e in trace]
    base, last, wraps = stamped[0][2], stamped[0][2], 0
    us = {}
    for e in stamped:                                  # (the 32-bit us count wraps every 71 minutes)
        if e[2] < last and last - e[2] > 0x80000000: wraps += 1
        last = e[2]; us[id(e)] = (e[2] + (wraps << 32) - base) * 1e-6
    off = min(e[0] - us[id(e)] for e in stamped)
    out = [(us[id(e)] + off, e[1]) if len(e) == 3 else (e[0], e[1]) for e in trace]
    out.sort(key=lambda x: x[0])
    return out


def find_port(spec):
    if spec and spec not in ('auto', 'pico'):
        return [spec]
    ports = []
    if os.path.exists('/dev/gpib-bridge'): ports.append('/dev/gpib-bridge')
    ports += sorted(glob.glob('/dev/serial/by-id/*GPIB-Pico2*')) + sorted(glob.glob('/dev/serial/by-id/*Pico*'))
    try:
        import serial.tools.list_ports
        ports += [p.device for p in serial.tools.list_ports.comports() if p.vid == PICO_VID]
    except ImportError:
        pass
    seen, out = set(), []
    for p in ports:
        r = os.path.realpath(p)
        if r not in seen: seen.add(r); out.append(p)
    return out


class PicoBridge:
    """gridlink transport: frame_limit, open(), configure(), answer(frame), read()."""
    frame_limit = FRAME_MAX
    patched = True

    def __init__(s, port='auto', addr=7, log=print):
        s.spec, s.addr, s.log = port, addr, log
        s.ser = None; s.port = None; s.wlock = threading.Lock()
        s.proto = PicoProto(s._write, addr=addr, log=log)
        s.inq = collections.deque(); s.cv = threading.Condition()
        s.stop = threading.Event()

    @property
    def version(s):
        return s.proto.firmware or '(no answer)'

    def _write(s, data):
        ser = s.ser
        if ser is None: return
        try:
            with s.wlock: ser.write(data)
        except Exception as e:
            s.log('bridge: write failed (%r): reopening' % e); s._drop()

    def _drop(s):
        try:
            if s.ser: s.ser.close()
        except Exception:
            pass
        s.ser = None; s.proto.connected = False

    def _open_once(s):
        import serial
        for p in find_port(s.spec):
            try:
                ser = serial.Serial(p, 115200, timeout=0.02, write_timeout=2)
                try: ser.dtr = True
                except Exception: pass
            except Exception as e:
                s.log('bridge: cannot open %s (%s)' % (p, e)); continue
            s.ser, s.port = ser, p
            s.proto.buf.clear()
            s.proto.hello()
            t_end = time.monotonic() + 3
            while time.monotonic() < t_end and not s.proto.connected:
                d = ser.read(256)
                if d: s._push(s.proto.feed(d))
            if s.proto.connected:
                s.log('bridge on %s' % p)
                return True
            s.log('bridge: %s did not answer (not the bridge firmware? bench firmware?)' % p)
            s._drop()
        return False

    def open(s):
        while not s._open_once():
            time.sleep(2)
        threading.Thread(target=s._reader, daemon=True, name='pico-reader').start()
        threading.Thread(target=s._pinger, daemon=True, name='pico-ping').start()

    def configure(s):
        return s.version

    def save(s):
        s.log('bridge: nothing to save (the Pi sets the address at every start)')

    def _push(s, data):
        if data:
            with s.cv:
                s.inq.append(data); s.cv.notify_all()

    def _reader(s):
        while not s.stop.is_set():
            if s.ser is None:
                if not s._open_once(): time.sleep(2)
                continue
            ser = s.ser
            try:
                # One byte with the timeout, then whatever has arrived.  read(4096) waited out the whole
                # 20 ms timeout for every message the GRiD sent (a GLP frame is far short of 4096 bytes),
                # which put ~20 ms into every round trip of the link.
                d = ser.read(1)
                if d:
                    n = ser.in_waiting
                    if n: d += ser.read(n)
            except Exception as e:
                if s.ser is ser:              # else the pinger already dropped it: just reopen, quietly
                    s.log('bridge: read failed (%r): reopening' % e); s._drop()
                continue
            if d: s._push(s.proto.feed(d))

    def _pinger(s):
        while not s.stop.is_set():
            time.sleep(1.0)
            if s.ser is not None and s.proto.connected:
                s.proto.ping()
                if time.monotonic() - s.proto.last_pong > 6:
                    s.log('bridge: no PONG for 6 s: reopening'); s._drop()

    def answer(s, frame):
        s.proto.answer(frame)

    def hold(s, expect, frame, glp=False):
        return s.proto.hold(expect, frame, glp)

    def hold_used(s):
        return s.proto.hold_used()

    def ring(s):
        s.proto.ring()

    def unring(s):
        s.proto.unring()

    @property
    def delivered_at(s):
        return s.proto.tx_done_at

    def poke(s):
        with s.cv: s.cv.notify_all()

    def read(s):
        """GRiD bytes (whole messages), or b'' after a short wait."""
        with s.cv:
            if not s.inq: s.cv.wait(0.02)
            if not s.inq: return b''
            out = b''.join(s.inq); s.inq.clear()
            return out
