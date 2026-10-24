"""Behavioural model of the GPIB-Pico2 bridge (bridge fw 2026-10-16d; 2026-10-23d and 2026-10-24 asked) for the emulator tests.

It speaks the bridge's USB protocol (COBS frames, PROTOCOL.md in GPIB Pico Board/firmware/bridge) to the real
gridlink PicoProto, and is a GPIB device to the 7210 model, as the firmware is:

* the GRiD's messages go to the Pi whole, in DATA frames of at most 240 bytes, a new generation at the first
  byte of every message;
* the Pi's TX frames are queued with their generation; one ending with EOI completes a reply, and in auto
  service request mode the bridge then raises SRQ with status 60h, keeps READY (20h) until the reply has been
  read, and drops a reply a newer message or an SDC has made stale;
* a TX frame bigger than the firmware's 600-byte input buffer is lost (counted in `violations`), so the Pi
  must split big replies into several TX frames;
* quiet (CONFIG bit 2, fw 2026-10-24, with `quiet=True`): the status byte as ever, the SRQ line never driven.

It subclasses AR488Model only so the 7210 model treats it as the bridge device; it shares none of its logic.
Time is in microseconds from the harness's clock.
"""
import collections, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from gridlink.pico import (cobs_encode, cobs_decode, F_HELLO_REQ, F_CONFIG, F_TX, F_STB, F_PING, F_WAKE, F_HELLO,
                           F_DATA, F_EVENT, F_PONG, F_CREDIT, CF_ONLINE, CF_AUTO_RSV, CF_QUIET, TXF_EOI, DF_EOI, F_HOLD,
                           TXF_HELD, DF_HELD, F_HOLD_GLP)
from gridlink.glp import fletcher16
from ar488_model import AR488Model

INBUF = 600           # host_link.c inbuf[600]: a longer COBS frame is dropped
DATA_CHUNK = 240
TX_RING = 16383


class PicoModel(AR488Model):
    def __init__(s, clock, addr=7, to_pi=None, usb_us=500, holds=False, quiet=False):
        super().__init__(clock, addr=addr, patched=True, to_pi=to_pi)
        # holds: the model says it is fw 2026-10-23c and takes F_HOLD (a reply held for the next message, sent
        # if that message is the one expected).  (gridlink then also sends EARLY frames: here only partial ones.)
        # quiet: it says fw 2026-10-24 (holds too) and takes CONFIG's quiet: no SRQ line, the byte as ever.
        s.holds = holds or quiet; s.can_quiet = quiet; s.quiet = False
        s.hold = None; s.cmp = None          # the hold out (gen, expected bytes); the one this message is compared to
        s.held = collections.deque()         # [gen, bytearray, complete] held replies
        s.n_held = 0
        s.usb_us = usb_us
        s.inq = collections.deque()          # (arrival_us, bytes) from the Pi
        s.inbuf = bytearray(); s.overrun = False
        s.online = False; s.auto = False
        s.gen = 0; s.partial = False
        s.ring = collections.deque()         # [gen, bytearray, complete] replies from the Pi
        s.consumed = 0; s.announced = 0; s.completed = 0
        s.rx_msg = bytearray()
        s.tx_frames = 0; s.big_tx = 0
        s.bell = None; s.rings = 0            # WAKE (fw 2026-10-22b): SRQ for an idle GRiD, until it sends again
        s.wake = None                         # the machine's schedule(t), so a HLT ends when SRQ can rise

    # ---- USB ---------------------------------------------------------
    def pi_write(s, data, latency_us=None):
        t = s.clock() + (s.usb_us if latency_us is None else latency_us)
        s.inq.append((t, bytes(data)))
        if s.wake: s.wake(t)                  # (a machine that sleeps: look at us then, SRQ may come)

    def _send(s, frame, t=None):
        s.to_pi(cobs_encode(frame), (s.clock() if t is None else t) + s.usb_us)

    def service(s):
        now = s.clock()
        while s.inq and s.inq[0][0] <= now:
            _, data = s.inq.popleft()
            for b in data:
                if b:
                    if len(s.inbuf) < INBUF: s.inbuf.append(b)
                    else: s.overrun = True
                    continue
                if s.overrun:
                    s.violations.append(('TX frame longer than the Pico input buffer', now)); s.big_tx += 1
                elif s.inbuf:
                    try: s._frame(cobs_decode(bytes(s.inbuf)))
                    except ValueError: s.violations.append(('bad COBS', now))
                s.inbuf = bytearray(); s.overrun = False

    def _frame(s, f):
        t = f[0]
        if t == F_HELLO_REQ:
            s.online = False
            s._send(struct.pack('<BBHHIH', F_HELLO, 1, TX_RING, DATA_CHUNK, s.consumed, 0)
                    + (b'bridge fw 2026-10-24 (model)' if s.can_quiet else
                       b'bridge fw 2026-10-23d (model)' if s.holds else b'bridge model'))
        elif t == F_CONFIG:
            was = s.online
            s.addr, fl = f[1], f[2]
            s.online = bool(fl & CF_ONLINE); s.auto = bool(fl & CF_AUTO_RSV)
            s.quiet = bool(fl & CF_QUIET) and s.can_quiet
            if s.online and not was: s.gen += 1; s.ring.clear()
        elif t == F_PING:
            s._send(bytes([F_PONG, 1 if s.online else 0]) + bytes(46))
        elif t in (F_HOLD, F_HOLD_GLP) and s.holds:
            s.hold = (struct.unpack_from('<H', f, 1)[0], bytes(f[3:]), t == F_HOLD_GLP)
        elif t == F_TX and s.holds and f[3] & TXF_HELD:
            gen, fl = struct.unpack_from('<HB', f, 1)
            data = f[4:]; s.tx_frames += 1
            if ((gen - s.gen) & 0xFFFF) != 1:      # its message has come (or gone) already: dropped
                s._consume(len(data)); return
            if s.held and s.held[-1][0] == gen and not s.held[-1][2]: s.held[-1][1] += data
            else: s.held.append([gen, bytearray(data), False])
            if fl & TXF_EOI: s.held[-1][2] = True
        elif t == F_TX:
            gen, fl = struct.unpack_from('<HB', f, 1)
            data = f[4:]; s.tx_frames += 1
            if gen != s.gen:
                s._consume(len(data)); return
            if s.ring and s.ring[-1][0] == gen and not s.ring[-1][2]:
                s.ring[-1][1] += data
            else:
                s.ring.append([gen, bytearray(data), False])
            if fl & TXF_EOI:
                s.ring[-1][2] = True; s.completed += 1
        elif t == F_STB:
            pass
        elif t == F_WAKE:
            s.rings += 1
            # (as the firmware: a WAKE replaces the bell; one for an older message is void, so it takes it back)
            s.bell = s.gen if struct.unpack_from('<H', f, 1)[0] == s.gen & 0xFFFF else None

    def _consume(s, n):
        s.consumed += n
        s._send(struct.pack('<BI', F_CREDIT, s.consumed))

    def _drop_stale(s):
        while s.ring and s.ring[0][0] != s.gen:
            g, d, c = s.ring.popleft(); s._consume(len(d))

    def _ready(s):
        s._drop_stale()
        return bool(s.ring and s.ring[0][2])

    def _bell(s):
        return s.bell is not None and s.bell == s.gen

    # ---- GPIB --------------------------------------------------------
    @property
    def srq(s):
        s.service()
        return (s.online and s.auto and not s.quiet
                and ((s._ready() and s.announced < s.completed) or s._bell()))

    @srq.setter
    def srq(s, v):
        pass                                   # (AR488Model.__init__ sets it)

    @property
    def status(s):
        s.service(); s.spolls += 1
        if not s.auto: return 0
        ready = s._ready()
        rqs = (ready and s.announced < s.completed) or s._bell()
        if rqs: s.announced = s.completed; s.bell = None
        return (0x20 if ready else 0) | (0x40 if rqs else 0)

    def on_listen(s, active):
        s.service(); s.listening = active
        if not active and s.partial: s._end_msg(False)

    def rx_byte(s, v, eoi):
        now = s.clock()
        if not s.partial:
            s.gen += 1; s.partial = True; s.rx_msg = bytearray()
            s.cmp, s.hold = (s.hold[1:] if s.hold and s.hold[0] == s.gen & 0xFFFF else None), None
        s.rx_msg.append(v)
        if eoi: s._end_msg(True)
        return now

    def _end_msg(s, eoi):
        m = bytes(s.rx_msg); s.partial = False; s.rx_msg = bytearray()
        t = s.clock()
        hit = eoi and s.cmp is not None and (_glp_ok(m, s.cmp[0]) if s.cmp[1] else m == s.cmp[0])
        s.cmp = None
        while s.held and s.held[0][0] != s.gen & 0xFFFF:   # (older ones: stale)
            s._consume(len(s.held.popleft()[1]))
        if s.held:
            g, d, c = s.held.popleft()
            if hit and c:                        # its reply is ready now: SRQ at once
                s.ring.append([g, d, True]); s.completed += 1; s.n_held += 1
                if s.wake: s.wake(t)
            else:
                s._consume(len(d)); hit = False
        for i in range(0, max(len(m), 1), DATA_CHUNK):
            last = i + DATA_CHUNK >= len(m)
            s._send(struct.pack('<BHB', F_DATA, s.gen & 0xFFFF,
                                ((DF_EOI | (DF_HELD if hit else 0)) if eoi else 2) if last else 0)
                    + m[i:i + DATA_CHUNK], t)

    def on_talk(s):
        s.service(); s.talks += 1
        s.out = b''
        if s._ready():
            g, d, c = s.ring.popleft()
            s.out = bytes(d); s._consume(len(d))

    def on_sent(s):
        """The reply's last byte went (the chip model calls it): TX_DONE, as the firmware's."""
        s._send(struct.pack('<BBHBI', F_EVENT, 0x1D, s.gen & 0xFFFF, 0, 0))

    def sdc(s, code=0x16):
        s.gen += 1; s.partial = False; s.cmp = None; s._drop_stale()
        s._send(struct.pack('<BBHBI', F_EVENT, code, s.gen & 0xFFFF, 0, 0))    # (the Pi is told, as the firmware's)

    def dcl(s):
        s.sdc(0x15)                         # (DCL: the same clear, reported as DCL)


def _glp_ok(m, head):
    """F_HOLD_GLP: one GLP frame starting with `head`, its length right, its Fletcher sum good."""
    if len(m) < 8 or m[:4] != head: return False
    n = m[4] | m[5] << 8
    return len(m) == 8 + n and fletcher16(m[1:6 + n]) == (m[6 + n] | m[7 + n] << 8)


class PicoModelTransport:
    """gridlink's PicoBridge, minus the serial port: the real PicoProto (pico.py), writing into the model.
    Bytes from the model go through feed(), which returns the GRiD's messages for Link.feed."""
    from gridlink.pico import FRAME_MAX as frame_limit
    patched = True

    def __init__(s, model):
        from gridlink.pico import PicoProto
        s.model = model
        s.proto = PicoProto(model.pi_write, addr=model.addr, log=lambda *a: None)
        s.version = 'GPIB-Pico2 model'
        s.proto.hello()

    def feed(s, data):
        return s.proto.feed(data)

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

    def set_quiet(s, on):
        return s.proto.set_quiet(on)

    @property
    def can_quiet(s):
        return s.proto.can_quiet

    @property
    def sdcs(s):
        return s.proto.sdcs

    @property
    def delivered_at(s):
        return s.proto.tx_done_at
