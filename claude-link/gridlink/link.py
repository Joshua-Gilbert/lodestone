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
        t_end = time.monotonic() + limit; last = time.monotonic(); junk = b''
        while time.monotonic() < t_end:
            d = s.ser.read(256)
            if d: last = time.monotonic(); junk += d
            elif time.monotonic() - last >= ms / 1000.0: return junk
        return junk

    def _cmd(s, text, reply=False):
        s._quiet()
        s.ser.write(text.encode() + b'\n')
        if not reply: time.sleep(0.05); return ''
        t_end = time.monotonic() + 1.0; buf = b''
        while time.monotonic() < t_end:
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
    RING_AGAIN = 0.1                          # ring again this long after a ring the GRiD didn't answer
    RING_IDLE = 0.05                          # the GRiD is idle once our last answer is this old
    RING_TRIES = 5                            # then give up (CLAUDE gone: Executive, a DOS program, TM5000)
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
        s.last_rx = time.monotonic()
        s.grid_maxpay = 1024
        s.grid_rx = glp.GRID_RX_DEFAULT       # payload the GRiD reads (its HELLO's rx=)
        s.grid_req = glp.GRID_REQ_DEFAULT     # the biggest REQUEST it takes (its HELLO's req=)
        s.grid_rd = 0                         # the biggest read it answers whole (its HELLO's rd=; 0: 8 KB reads)
        s.grid_fcs = False                    # the GRiD's HELLO offered the Fletcher sum
        s.rx_fl = False                       # the GRiD's last good frame had it: answer in kind
        s.grid_wake = False                   # the GRiD's HELLO said it POLLs when the bridge rings (GF_WAKE)
        s.rang = None                         # when we last rang, since the GRiD's last frame
        s.rings_left = s.RING_TRIES; s.unrung = True
        s.t_answered = 0.0                    # when our last answer went to the bridge
        s.clock = time.monotonic              # (the emulator tests give theirs: the rings' timing is the GRiD's)
        s.frame_cap = None                    # a smaller limit for tests and gridlink.bench
        s.trace = None                        # a deque while gridlink.bench --trace runs: (time, event)
        s.spec = None                         # the reply held in the bridge for the GRiD's next frame (_speculate)
        s.last_kind = None                    # the kind of our last answer
        s.drop_types = set()                  # a held answer went for a frame we never read: drop that message
        s.holding = True                      # (tests and gridlink.bench --nohold switch it off)

    @property
    def maxpay(s):
        """Payload of the Pi's frames: what the bridge, the GRiD and any cap allow."""
        m = min(s.t.frame_limit - glp.OVERHEAD, s.grid_rx)
        return min(m, s.frame_cap) if s.frame_cap else m

    # ---- outbound -----------------------------------------------------
    def send(s, mtype, body=b''):
        if s.trace is not None: s.trace.append((time.monotonic(), 'send'))
        with s.lock:
            s.outq.append((mtype, bytes(body)))
            s.lock.notify_all()
        s._poke()

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
        s._poke()

    def _poke(s):
        poke = getattr(s.t, 'poke', None)     # the serve loop's read returns now: ring_check sooner
        if poke: poke()

    def _to_grid(s, frame):
        s.t_answered = s.clock()
        s.t.answer(frame)

    def ring_check(s):
        """From the serve loop, between frames (never while an answer is held): when we have something for an
        idle GRiD, ask the bridge for an SRQ so it POLLs now instead of at its next idle POLL (up to 1 s).
        Idle: the GRiD read our last answer (the bridge's TX_DONE, where it tells us) RING_IDLE ago, and
        hasn't sent since (a busy GRiD sends its next frame sooner); never while an answer waits unread.  Again every
        RING_AGAIN until the GRiD sends (a ring can be lost: the GRiD may take its SRQ for the answer it is
        reading), RING_TRIES times; then the SRQ is taken back (unring), so an Executive or a DOS program
        doesn't find it held on the bus, and we wait for the GRiD's next frame."""
        if not (s.grid_wake and s.connected): return
        ring = getattr(s.t, 'ring', None)
        if ring is None: return
        now = s.clock()
        if s.rang is not None and now - s.rang < s.RING_AGAIN: return
        if s.rings_left <= 0:
            if not s.unrung:
                s.unrung = True
                unring = getattr(s.t, 'unring', None)
                if unring: unring()
                s.stats['unrung'] += 1
                if s.trace is not None: s.trace.append((time.monotonic(), 'unring'))
            return
        base = s.t_answered
        done = getattr(s.t, 'delivered_at', None)     # (the Pico's TX_DONE: the GRiD has read it)
        if done is not None:
            if done < s.t_answered: return            # our answer isn't read yet: the GRiD is busy with it
            base = done
        if now - base < s.RING_IDLE: return
        with s.lock:
            if not s._has_output(): return
        s.rang = now; s.rings_left -= 1; s.unrung = False
        s.stats['rang'] += 1
        if s.trace is not None: s.trace.append((time.monotonic(), 'ring'))
        ring()

    def _has_output(s):
        return bool(s.outq or s.cur) or (s.source is not None and s.source.ready())

    def _next_payload(s):
        maxpay = s.maxpay
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
        if kind == glp.P_HELLO and s.grid_fcs and len(payload) >= 2:   # the GRiD switches on reading it
            payload = bytes(payload[:1]) + bytes([payload[1] | glp.HF_FCS]) + bytes(payload[2:])
        # Each answer is checked as the frame it answers was: the HELLO (sent
        # with the CRC, as link_reset leaves the GRiD) gets the CRC, the
        # frames after it the Fletcher sum once the GRiD has switched.
        frame = glp.encode(kind, s.pi_seq, s.last_g if s.last_g is not None else 0, payload, fl=s.rx_fl)
        s.last_answer = frame; s.last_kind = kind
        if s.trace is not None: s.trace.append((time.monotonic(), 'pi ' + _name(kind, len(payload))))
        s._to_grid(frame)
        s.stats['tx_frames'] += 1; s.stats['tx_bytes'] += len(frame)

    # ---- inbound ------------------------------------------------------
    def feed(s, data):
        """Bytes from the Nano.  Returns the number of frames handled."""
        if data: s.last_rx = time.monotonic()
        n = 0
        for f in s.parser.feed(data):
            s.handle(f); n += 1
        return n

    def idle_check(s, quiet=0.15):
        """Bytes that sat for `quiet` seconds without making a frame were
        damaged in transit: ask the GRiD to resend."""
        if s.parser.pending() and time.monotonic() - s.last_rx > quiet:
            s.parser.idle()
            s.stats['rx_damaged'] += 1
            spec = s.spec
            if spec is not None and spec[0] is None and s.t.hold_used():
                # The bridge passed a fragment we can't read, and has acknowledged it: the rest of that message
                # would come without it.  Never expected (the bridge checks the same sum on the same bytes), but
                # a message with a hole must not be taken for whole: it is dropped, and its caller times out.
                s.spec = None
                s.reasm.parts.pop(spec[1], None); s.drop_types.add(spec[1])
                s.stats['held_unread'] += 1
                s.log('link: the bridge acknowledged a frame gridlink could not read: dropping that message')
                return
            s._answer_nak()

    def _answer_nak(s):
        frame = glp.encode(glp.P_NAK, s.pi_seq, s.last_g if s.last_g is not None else 0, fl=s.rx_fl)
        s._to_grid(frame)          # NAK does not replace last_answer
        s.stats['tx_nak'] += 1

    def handle(s, f):
        spec, s.spec = s.spec, None
        s.rang = None; s.rings_left = s.RING_TRIES; s.unrung = True    # (its frame ended any ring)
        if s.trace is not None:
            s.trace.append((time.monotonic(), 'grid ' + _name(f.type | (glp.MORE if f.more else 0), len(f.payload))))
        s.stats['rx_frames'] += 1; s.stats['rx_bytes'] += len(f.payload) + glp.OVERHEAD
        s.rx_fl = f.fl
        if f.fl: s.stats['rx_fletcher'] += 1
        t = f.type
        if t == glp.G_NAK:
            s.stats['rx_nak'] += 1
            if s.last_answer: s._to_grid(s.last_answer)
            else: s._answer(glp.P_NOP, b'')
            return
        if t == glp.G_HELLO:
            with s.lock:
                s.outq.clear(); s.cur = None
            s.reasm = glp.Reassembler(); s.pi_seq = 0; s.last_g = None; s.connected = True
            s.drop_types.clear()
        elif s.last_g is not None and f.seq == s.last_g:
            s.stats['rx_dup'] += 1
            if s.last_answer: s._to_grid(s.last_answer)
            return
        elif s.source is not None:
            s.source.delivered()            # a new frame: our last answer arrived
        s.last_g = f.seq
        msg = s.reasm.add(f)
        if msg and msg[0] in s.drop_types:
            s.drop_types.discard(msg[0]); msg = None
        if msg:
            mt, body = msg
            if mt == glp.G_HELLO and len(body) >= 4:
                s.grid_maxpay = body[2] | (body[3] << 8)
                s.grid_rx = glp.hello_rx(body)
                s.grid_req = glp.hello_req(body)
                s.grid_rd = glp.hello_rd(body)
                s.grid_fcs = bool(body[1] & glp.GF_FCS)
                s.grid_wake = bool(body[1] & glp.GF_WAKE)
            if mt != glp.G_POLL:
                try: s.on_message(mt, body)
                except Exception as e: s.log('link: handler error: %r' % e)
        if spec is not None and (t == glp.G_POLL if spec[0] is not None else f.more and f.fl) \
                and s.t.hold_used():
            s._commit(spec)                     # the bridge has answered it with the held reply
            s._speculate(f)
            return
        # Answer.  A POLL may wait for output, and in Term so may KEYS (for
        # the echo); anything else is answered now.  A REPLY's last frame waits
        # too: whoever made the call usually sends the next REQUEST within a few
        # ms (the next chunk of a copy), and answering NOP at once sent the GRiD
        # back to its once-a-second idle POLL, so every request cost ~1 s.
        with s.lock:
            hold = s.hold if t in (glp.G_POLL, glp.G_REPLY) and not f.more else 0
            if t == glp.G_KEYS and s.source is not None: hold = s.keys_hold
            if hold and not s._has_output():
                end = time.monotonic() + hold
                while not s._has_output():
                    left = end - time.monotonic()
                    if left <= 0: break
                    # the source may become ready by time alone (output settling)
                    s.lock.wait(min(left, 0.005) if s.source is not None else left)
            kind, payload = s._next_payload()
        s._answer(kind, payload)
        s._speculate(f)

    # ---- held replies (bridge fw 2026-10-23c) ---------------------------
    # While a message goes to the GRiD in fragments, its next frame is all but certain: having read a MORE
    # fragment, CLAUDE POLLs for the next (TERMLINK frame_poll: its sequence number + 1, acknowledging ours,
    # no payload, checked as before).  So with the answer we give the bridge that POLL, byte for byte, and our
    # answer to it, the next fragment.  If the GRiD's next message is that POLL, the bridge raises SRQ at its
    # last byte and the GRiD reads the fragment at once: the trip over USB to us and back (~1.5 ms of each
    # ~17 ms frame) is gone.  Anything else (KEYS, a NAK, a REPLY) and the bridge drops the fragment, and we
    # answer as usual: nothing has changed here until DATA says the hold was used (hold_used).
    # Out of the GRiD it is the same the other way round (bridge fw 2026-10-23d): having sent a MORE fragment and
    # read our NOP, CLAUDE sends the next fragment of the same message (seq + 1, acknowledging the NOP).  What
    # it carries we can't know, but our answer doesn't depend on it while we have nothing to send: a NOP.  So
    # the bridge gets that frame's first 4 bytes and the NOP, and checks the rest itself: the length, and the
    # Fletcher sum the GRiD put on it (the very check we make here), before it lets the NOP go.
    def _speculate(s, f):
        hold = getattr(s.t, 'hold', None)
        if hold is None or not s.holding or f.type == glp.G_HELLO or s.parser.pending(): return
        with s.lock:
            cur = s.cur
            if cur is None:
                if not (f.more and f.fl and s.last_kind == glp.P_NOP) or s.outq: return
                if s.source is not None and s.source.ready(): return
                seq = (f.seq + 1) & 0xFF
                frame = glp.encode(glp.P_NOP, (s.pi_seq + 1) & 0xFF, seq, b'', fl=True)
                if hold(bytes([glp.SYNC, f.kind, seq, s.pi_seq]), frame, glp=True):
                    s.spec = (None, f.type, 0, glp.P_NOP, frame)
                return
            if f.more: return                   # (the GRiD's message isn't finished: it doesn't POLL)
            if s.source is not None and s.last_q and s.source.ready(): return   # (the source's turn next)
            t, body, off = cur
            chunk = body[off:off + s.maxpay]
            kind = t if off + len(chunk) >= len(body) else t | glp.MORE
            seq = (f.seq + 1) & 0xFF
            expect = glp.encode(glp.G_POLL, seq, s.pi_seq, b'', fl=s.rx_fl)
            frame = glp.encode(kind, (s.pi_seq + 1) & 0xFF, seq, chunk, fl=s.rx_fl)
            if hold(expect, frame):
                s.spec = (cur, off, len(chunk), kind, frame)

    def _commit(s, spec):
        """The held reply answered the GRiD's POLL: what _answer would have done."""
        cur, off, n, kind, frame = spec
        with s.lock:
            if cur is not None and s.cur is cur and cur[2] == off:
                if off + n >= len(cur[1]): s.cur = None
                else: cur[2] = off + n
            s.last_q = cur is not None
        s.pi_seq = (s.pi_seq + 1) & 0xFF
        s.last_answer = frame; s.last_kind = kind
        s.t_answered = s.clock()
        if s.trace is not None: s.trace.append((time.monotonic(), 'pi ' + _name(kind, n) + ' held'))
        s.stats['tx_frames'] += 1; s.stats['tx_bytes'] += len(frame); s.stats['tx_held'] += 1


def _name(kind, n):
    """A frame for gridlink.bench --trace: REQUEST+ (MORE), CELLS ...; 'big' when it carries 512 bytes or more."""
    return glp.NAMES.get(kind & 0x7F, '%02X' % (kind & 0x7F)) + ('+' if kind & glp.MORE else '') + (' big' if n >= 512 else '')


def serve(transport, link, stop):
    """Reader loop for a real serial transport."""
    while not stop.is_set():
        data = transport.read()
        if data: link.feed(data)
        else: link.idle_check(); link.ring_check()
