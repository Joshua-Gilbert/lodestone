"""Behavioural model of the GPIB-Pico2 bridge (bridge fw 2026-10-16d) for the emulator tests.

It speaks the bridge's USB protocol (COBS frames, PROTOCOL.md in GPIB Pico Board/firmware/bridge) to the real
gridlink PicoProto, and is a GPIB device to the 7210 model, as the firmware is:

* the GRiD's messages go to the Pi whole, in DATA frames of at most 240 bytes, a new generation at the first
  byte of every message;
* the Pi's TX frames are queued with their generation; one ending with EOI completes a reply, and in auto
  service request mode the bridge then raises SRQ with status 60h, keeps READY (20h) until the reply has been
  read, and drops a reply a newer message or an SDC has made stale;
* a TX frame bigger than the firmware's 600-byte input buffer is lost (counted in `violations`), so the Pi
  must split big replies into several TX frames.

It subclasses AR488Model only so the 7210 model treats it as the bridge device; it shares none of its logic.
Time is in microseconds from the harness's clock.
"""
import collections, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from gridlink.pico import (cobs_encode, cobs_decode, F_HELLO_REQ, F_CONFIG, F_TX, F_STB, F_PING, F_HELLO,
                           F_DATA, F_EVENT, F_PONG, F_CREDIT, CF_ONLINE, CF_AUTO_RSV, TXF_EOI, DF_EOI)
from ar488_model import AR488Model

INBUF = 600           # host_link.c inbuf[600]: a longer COBS frame is dropped
DATA_CHUNK = 240
TX_RING = 16383


class PicoModel(AR488Model):
    def __init__(s, clock, addr=7, to_pi=None, usb_us=500):
        super().__init__(clock, addr=addr, patched=True, to_pi=to_pi)
        s.usb_us = usb_us
        s.inq = collections.deque()          # (arrival_us, bytes) from the Pi
        s.inbuf = bytearray(); s.overrun = False
        s.online = False; s.auto = False
        s.gen = 0; s.partial = False
        s.ring = collections.deque()         # [gen, bytearray, complete] replies from the Pi
        s.consumed = 0; s.announced = 0; s.completed = 0
        s.rx_msg = bytearray()
        s.tx_frames = 0; s.big_tx = 0

    # ---- USB ---------------------------------------------------------
    def pi_write(s, data, latency_us=None):
        s.inq.append((s.clock() + (s.usb_us if latency_us is None else latency_us), bytes(data)))

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
            s._send(struct.pack('<BBHHIH', F_HELLO, 1, TX_RING, DATA_CHUNK, s.consumed, 0) + b'bridge model')
        elif t == F_CONFIG:
            was = s.online
            s.addr, fl = f[1], f[2]
            s.online = bool(fl & CF_ONLINE); s.auto = bool(fl & CF_AUTO_RSV)
            if s.online and not was: s.gen += 1; s.ring.clear()
        elif t == F_PING:
            s._send(bytes([F_PONG, 1 if s.online else 0]) + bytes(46))
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

    def _consume(s, n):
        s.consumed += n
        s._send(struct.pack('<BI', F_CREDIT, s.consumed))

    def _drop_stale(s):
        while s.ring and s.ring[0][0] != s.gen:
            g, d, c = s.ring.popleft(); s._consume(len(d))

    def _ready(s):
        s._drop_stale()
        return bool(s.ring and s.ring[0][2])

    # ---- GPIB --------------------------------------------------------
    @property
    def srq(s):
        s.service()
        return s.online and s.auto and s._ready() and s.announced < s.completed

    @srq.setter
    def srq(s, v):
        pass                                   # (AR488Model.__init__ sets it)

    @property
    def status(s):
        s.service(); s.spolls += 1
        if not s.auto: return 0
        ready = s._ready()
        rqs = ready and s.announced < s.completed
        if rqs: s.announced = s.completed
        return (0x20 if ready else 0) | (0x40 if rqs else 0)

    def on_listen(s, active):
        s.service(); s.listening = active
        if not active and s.partial: s._end_msg(False)

    def rx_byte(s, v, eoi):
        now = s.clock()
        if not s.partial:
            s.gen += 1; s.partial = True; s.rx_msg = bytearray()
        s.rx_msg.append(v)
        if eoi: s._end_msg(True)
        return now

    def _end_msg(s, eoi):
        m = bytes(s.rx_msg); s.partial = False; s.rx_msg = bytearray()
        t = s.clock()
        for i in range(0, max(len(m), 1), DATA_CHUNK):
            last = i + DATA_CHUNK >= len(m)
            s._send(struct.pack('<BHB', F_DATA, s.gen & 0xFFFF, (DF_EOI if eoi else 2) if last else 0)
                    + m[i:i + DATA_CHUNK], t)

    def on_talk(s):
        s.service(); s.talks += 1
        s.out = b''
        if s._ready():
            g, d, c = s.ring.popleft()
            s.out = bytes(d); s._consume(len(d))

    def sdc(s):
        s.gen += 1; s.partial = False; s._drop_stale()


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
