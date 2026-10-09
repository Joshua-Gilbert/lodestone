"""Pi side of the GLP link: strict alternation over an AR488 in device mode.

The GRiD (controller) writes one frame; we answer with exactly one frame.
Everything we want to say waits in an outbound queue until the GRiD asks.
"""
import math, re, threading, time, collections
from . import glp


def stock_wait_ms(nbytes, baud):
    """How long the GRiD should wait after seeing RQS before it reads, with
    stock AR488: the frame is still arriving over serial when SRQ goes up."""
    return max(2, min(glp.ST_WAITMASK, int(math.ceil(glp.line_time_ms(nbytes + 1, baud) * 1.15 + 2))))


def answer_bytes(frame, patched, baud):
    """What the Pi writes to the Nano to put one frame in front of the GRiD."""
    data = glp.escape(frame) + b'\n'
    if not patched:
        # status first: anything sent after a complete line would be glued
        # onto it.  Bits 0-4 tell the GRiD how long the line still needs.
        data = b'++status %d\n' % (glp.ST_RQS | stock_wait_ms(len(data), baud)) + data
    return data


class AR488Serial:
    """The Nano on a USB serial port, running AR488 (stock or +GRiD patch)."""
    def __init__(s, port, baud=115200, addr=7, log=print):
        s.port, s.baud, s.addr, s.log = port, baud, addr, log
        s.ser = None; s.patched = False; s.version = ''

    @property
    def frame_limit(s):
        return glp.PATCHED_FRAME_MAX if s.patched else glp.STOCK_FRAME_MAX

    def open(s):
        import serial
        s.ser = serial.Serial(s.port, s.baud, timeout=0.02)
        time.sleep(2.0)                  # opening the port resets the Nano
        s.ser.reset_input_buffer()

    def _quiet(s, ms=300, limit=10.0):
        """Wait until the GRiD has been silent for ms, so a command we send
        cannot collide with a frame it is writing (the Nano would drop it)."""
        t_end = time.time() + limit; last = time.time(); junk = b''
        while time.time() < t_end:
            d = s.ser.read(256)
            if d: last = time.time(); junk += d
            elif time.time() - last >= ms / 1000.0: return junk
        return junk

    def _cmd(s, text, reply=False):
        s._quiet()
        s.ser.write(text.encode() + b'\n')
        if not reply: time.sleep(0.05); return ''
        t_end = time.time() + 1.0; buf = b''
        while time.time() < t_end:
            buf += s.ser.read(256)
            if b'\n' in buf: break
        return buf.decode('latin1', 'replace')

    def configure(s):
        for c in ('++mode 0', '++addr %d' % s.addr, '++eos 3', '++eoi 1', '++eot_enable 0', '++idn 0'):
            s._cmd(c)
        v = s._cmd('++ver real', reply=True)
        m = re.search(r'AR488[^\r\n]*', v)
        s.version = m.group(0) if m else v.strip()
        s.patched = '+GRiD' in s.version
        a = s._cmd('++addr', reply=True)
        s.log('bridge: %s, %s firmware, address %s, frames up to %d bytes'
              % (s.version or '(no answer)', 'patched' if s.patched else 'stock', a.strip(), s.frame_limit))
        return s.version

    def save(s):
        s._cmd('++savecfg')

    def answer(s, frame):
        s.ser.write(answer_bytes(frame, s.patched, s.baud))

    def read(s):
        # One byte with the timeout, then whatever has arrived: read(4096)
        # would wait out the whole timeout for every frame.
        d = s.ser.read(1)
        if d:
            n = s.ser.in_waiting
            if n: d += s.ser.read(n)
        return d


class Link:
    """Frame-level state machine.  `on_message(type, body)` is called for every
    complete inbound message (from the reader thread; keep it quick).

    `source` (Term) is pulled for one frame whenever the queue gives way:
    source.ready() says it has something to send now, source.take(maxpay)
    gives a CELLS payload (or None), source.delivered() says the GRiD has the
    last one (its next frame is a new one)."""
    HOLD = 0.25
    KEYS_HOLD = 0.03

    def __init__(s, transport, on_message, log=print, hold=HOLD):
        s.t, s.on_message, s.log, s.hold = transport, on_message, log, hold
        s.source = None; s.keys_hold = s.KEYS_HOLD; s.last_q = False
        s.parser = glp.StreamParser(max_len=4096)
        s.lock = threading.Condition()
        s.outq = collections.deque()          # (type, body) messages
        s.cur = None                          # (type, body, offset) being sent
        s.reasm = glp.Reassembler()
        s.pi_seq = 0; s.last_g = None; s.last_answer = None
        s.stats = collections.Counter(); s.connected = False
        s.last_rx = time.time()
        s.grid_maxpay = 1024

    # ---- outbound -----------------------------------------------------
    def send(s, mtype, body=b''):
        with s.lock:
            s.outq.append((mtype, bytes(body)))
            s.lock.notify_all()

    def send_first(s, mtype, body=b''):
        """Jump the queue (the answer to HELLO must be HELLO)."""
        with s.lock:
            s.outq.appendleft((mtype, bytes(body)))
            s.lock.notify_all()

    def busy(s):
        with s.lock: return bool(s.outq or s.cur)

    def wake(s):
        """The source has something new."""
        with s.lock: s.lock.notify_all()

    def _has_output(s):
        return bool(s.outq or s.cur) or (s.source is not None and s.source.ready())

    def _next_payload(s):
        maxpay = s.t.frame_limit - glp.OVERHEAD
        src = s.source
        # The queue and the source take turns when both have something;
        # the answer to HELLO is always first.
        queued = bool(s.outq or s.cur)
        hello = s.cur is None and s.outq and s.outq[0][0] == glp.P_HELLO
        if src is not None and (not queued or (s.last_q and not hello)) and src.ready():
            p = src.take(maxpay)
            if p is not None:
                s.last_q = False
                return glp.P_CELLS, p
        s.last_q = queued
        if s.cur is None:
            if not s.outq: return glp.P_NOP, b''
            t, body = s.outq.popleft()
            if t == glp.P_TEXT:                 # coalesce queued text
                while s.outq and s.outq[0][0] == glp.P_TEXT and len(body) < 4096:
                    body += s.outq.popleft()[1]
            s.cur = [t, body, 0]
        t, body, off = s.cur
        chunk = body[off:off + maxpay]
        off += len(chunk)
        if off >= len(body):
            s.cur = None; return t, chunk
        s.cur[2] = off
        return t | glp.MORE, chunk

    def _answer(s, kind, payload):
        s.pi_seq = (s.pi_seq + 1) & 0xFF
        frame = glp.encode(kind, s.pi_seq, s.last_g if s.last_g is not None else 0, payload)
        s.last_answer = frame
        s.t.answer(frame)
        s.stats['tx_frames'] += 1; s.stats['tx_bytes'] += len(frame)

    # ---- inbound ------------------------------------------------------
    def feed(s, data):
        """Bytes from the Nano.  Returns the number of frames handled."""
        if data: s.last_rx = time.time()
        n = 0
        for f in s.parser.feed(data):
            s.handle(f); n += 1
        return n

    def idle_check(s, quiet=0.15):
        """Bytes that sat for `quiet` seconds without making a frame were
        damaged in transit: ask the GRiD to resend."""
        if s.parser.pending() and time.time() - s.last_rx > quiet:
            s.parser.idle()
            s.stats['rx_damaged'] += 1
            s._answer_nak()

    def _answer_nak(s):
        frame = glp.encode(glp.P_NAK, s.pi_seq, s.last_g if s.last_g is not None else 0)
        s.t.answer(frame)          # NAK does not replace last_answer
        s.stats['tx_nak'] += 1

    def handle(s, f):
        s.stats['rx_frames'] += 1; s.stats['rx_bytes'] += len(f.payload) + glp.OVERHEAD
        t = f.type
        if t == glp.G_NAK:
            s.stats['rx_nak'] += 1
            if s.last_answer: s.t.answer(s.last_answer)
            else: s._answer(glp.P_NOP, b'')
            return
        if t == glp.G_HELLO:
            with s.lock:
                s.outq.clear(); s.cur = None
            s.reasm = glp.Reassembler(); s.pi_seq = 0; s.last_g = None; s.connected = True
        elif s.last_g is not None and f.seq == s.last_g:
            s.stats['rx_dup'] += 1
            if s.last_answer: s.t.answer(s.last_answer)
            return
        elif s.source is not None:
            s.source.delivered()            # a new frame: our last answer arrived
        s.last_g = f.seq
        msg = s.reasm.add(f)
        if msg:
            mt, body = msg
            if mt == glp.G_HELLO and len(body) >= 4:
                s.grid_maxpay = body[2] | (body[3] << 8)
            if mt != glp.G_POLL:
                try: s.on_message(mt, body)
                except Exception as e: s.log('link: handler error: %r' % e)
        # Answer.  A POLL may wait for output, and in Term so may KEYS (for
        # the echo); anything else is answered now.
        with s.lock:
            hold = s.hold if t == glp.G_POLL and not f.more else 0
            if t == glp.G_KEYS and s.source is not None: hold = s.keys_hold
            if hold and not s._has_output():
                end = time.time() + hold
                while not s._has_output():
                    left = end - time.time()
                    if left <= 0: break
                    # the source may become ready by time alone (output settling)
                    s.lock.wait(min(left, 0.005) if s.source is not None else left)
            kind, payload = s._next_payload()
        s._answer(kind, payload)


def serve(transport, link, stop):
    """Reader loop for a real serial transport."""
    while not stop.is_set():
        data = transport.read()
        if data: link.feed(data)
        else: link.idle_check()
