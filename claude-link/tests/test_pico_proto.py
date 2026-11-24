"""gridlink's PicoProto (gridlink/pico.py) on its own: the frames from the bridge, without a GRiD or a port.

    python3 tests/test_pico_proto.py
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gridlink import pico
from gridlink.pico import cobs_encode, PicoProto, PicoBridge

def deframer():
    """A PicoProto whose frames, once deframed, are kept rather than parsed."""
    p = PicoProto(lambda b: None, log=lambda *a: None)
    got = []
    p._frame = lambda f: got.append(f) or b''
    return p, got


def test_overlong_valid_cobs():
    # a run that decodes as good COBS but is longer than 4096 bytes: only the length check refuses it.  4079
    # bytes without a zero encode to a 4096-byte run (taken), 4080 to 4097 (dropped, and the next frame read)
    for n, taken in ((4079, True), (4080, False)):
        p, got = deframer()
        f = bytes([pico.F_DATA]) + bytes(range(1, 256)) * 16
        f = f[:n]
        enc = cobs_encode(f)
        assert len(enc) - 1 == (4096 if taken else 4097) and pico.cobs_decode(enc[:-1]) == f
        p.feed(enc + cobs_encode(b'\x82next'))
        assert got == ([f] if taken else []) + [b'\x82next'], (n, len(got))
        assert p.stats['bad_frames'] == (0 if taken else 1), (n, p.stats)


def test_resync_mid_frame():
    # a reopen (resync) with a frame half in from the old port: the new port's first frame doesn't join it (or
    # get skipped with it); a new port that starts in the middle of a frame resynchronises at its next 0x00
    for left in (cobs_encode(b'\x82old frame')[:6],             # (part of a frame, in buf)
                 bytes(range(1, 256)) * 20):                     # (part of an overlong one: skipping)
        p, got = deframer()
        p.feed(left)
        assert not got
        p.resync()
        bad = p.stats['bad_frames']                    # (the overlong one: counted already)
        p.feed(cobs_encode(b'\x82new') + cobs_encode(b'\x82two'))
        assert got == [b'\x82new', b'\x82two'] and p.stats['bad_frames'] == bad, (got, p.stats)
    p, got = deframer()
    p.feed(b'\x09\x01\x02\0' + cobs_encode(b'\x82new') + cobs_encode(b'\x82two'))    # (a frame's tail first)
    assert got == [b'\x82new', b'\x82two'] and p.stats['bad_frames'] == 1, (got, p.stats)


MINIMUM = {pico.F_HELLO: 12, pico.F_DATA: 4, pico.F_EVENT: 9, pico.F_CREDIT: 5}


def connected(log=None):
    """A PicoProto past its HELLO, its writes kept."""
    out = []
    p = PicoProto(out.append, log=(log.append if log is not None else lambda *a: None))
    p.feed(cobs_encode(struct.pack('<BBHHIH', pico.F_HELLO, 1, 16383, 240, 0, 0) + b'bridge fw 2026-10-24 (test)'))
    assert p.connected
    return p, out


def state(p):
    return (p.connected, p.firmware, p.tx_ring, p.consumed, p.sent, p.gen, p.online, p.sdcs, p.tx_done_at)


def test_short_frames_ignored():
    # A frame too short for its type's fields, of every type gridlink parses: ignored, counted, nothing changed,
    # and the frames after it still read (it used to raise struct.error out of the reader thread)
    for t, n in sorted(MINIMUM.items()):
        for k in range(1, n):
            p, _ = connected()
            before = state(p)
            got = p.feed(cobs_encode(bytes([t]) + bytes(range(1, k))))
            assert got == b'' and p.stats['bad_frames'] == 1, (hex(t), k, got, p.stats)
            assert state(p) == before, (hex(t), k, state(p), before)
            assert p.feed(cobs_encode(struct.pack('<BHB', pico.F_DATA, 0, pico.DF_EOI) + b'next')) == b'next'
    # whole frames of each minimum length are not bad
    p, _ = connected()
    p.feed(cobs_encode(struct.pack('<BHB', pico.F_DATA, 1, 0)))
    p.feed(cobs_encode(struct.pack('<BBHBI', pico.F_EVENT, 0x1D, 1, 0, 0)))
    p.feed(cobs_encode(struct.pack('<BI', pico.F_CREDIT, 0)))
    assert p.stats['bad_frames'] == 0, p.stats


def test_short_hello_before_connect():
    # a short HELLO while PicoBridge waits for the bridge: ignored, not an exception out of open()
    p = PicoProto(lambda d: None, log=lambda *a: None)
    p.feed(cobs_encode(bytes([pico.F_HELLO, 1, 0xFF])))
    assert not p.connected and p.stats['bad_frames'] == 1


def test_short_pong_still_counts():
    # any PONG says the bridge is there: last_pong first, so a short one doesn't make the pinger drop the port
    p, _ = connected()
    p.last_pong = 0.0
    p.feed(cobs_encode(bytes([pico.F_PONG])))
    assert p.last_pong > 0 and p.pongs == 1, (p.last_pong, p.pongs)


def test_short_frames_logged_once():
    # three short frames, one line (PicoBridge's _once): every frame logging would flood the journal
    log = []
    b = PicoBridge(log=log.append)
    b.proto.connected = True
    for t in (pico.F_DATA, pico.F_EVENT, pico.F_CREDIT):
        b.proto.feed(cobs_encode(bytes([t, 1])))
    short = [l for l in log if 'shorter than its fields' in l]
    assert len(short) == 1 and b.proto.stats['bad_frames'] == 3, (log, b.proto.stats)


def pong(consumed, gen=0, online=1):
    return cobs_encode(bytes([pico.F_PONG, online, 7]) + bytes(6) + struct.pack('<HI', gen, consumed) + bytes(32))


def full(p, out, consumed=1000):
    """The bridge's ring full by our count (a CREDIT lost), and a reply waiting for room."""
    p.tx_ring = 100; p.consumed = consumed; p.sent = (consumed + 100) & 0xFFFFFFFF
    del out[:]
    p.answer(b'R' * 50)
    assert not out and p.pending


def test_pong_consumed_count():
    # PONG's u32 at offset 11 (host_link.c's send_pong) makes good a lost CREDIT: the reply goes
    p, out = connected()
    full(p, out)
    p.feed(pong(1060))
    assert p.consumed == 1060 and not p.pending and out, (p.consumed, p.pending)


def credit(c):
    return cobs_encode(struct.pack('<BI', pico.F_CREDIT, c))


def talk_wait(c):
    return cobs_encode(struct.pack('<BBHBII', pico.F_EVENT, 0x14, 0, 0, c, 0))


def test_live_count_one_lower_taken():
    # host_link.c's ann_flush: a stand-in EOI in the ring takes consumed_total() down by one (tx_dropped0--)
    # until core 1 pops it, and the credit sender and PONG send the lower count at once.  That slot is not
    # free: a CREDIT or PONG one below the held count is taken, or _pump would send a byte past the room
    for frame in (credit, pong):
        p, out = connected()
        p.tx_ring = 100; p.consumed = 1000; p.sent = 1000 + 99    # one byte of room by the old count
        p.feed(frame(999))
        assert p.consumed == 999, (frame.__name__, p.consumed)
        del out[:]
        p.answer(b'R')                             # (one byte: no room now)
        assert not out and p.pending, (frame.__name__, out)


def test_talk_wait_consumed_count():
    p, out = connected()
    full(p, out)
    p.feed(talk_wait(1050))
    assert p.consumed == 1050 and not p.pending and out, (p.consumed, p.pending)
    # TALK_WAIT's count is core 1's from when it happened: behind a CREDIT already here, it is not taken
    p.feed(credit(1080)); p.feed(talk_wait(1060))
    assert p.consumed == 1080, p.consumed


def test_consumed_count_wraps():
    p, out = connected()
    full(p, out, consumed=0xFFFFFFF0)
    p.feed(talk_wait(0x30))                       # (past the 32-bit wrap: ahead, so taken)
    assert p.consumed == 0x30 and not p.pending, (p.consumed, p.pending)
    p.feed(talk_wait(0xFFFFFFF8))                 # (before it: behind)
    assert p.consumed == 0x30, p.consumed


def test_pico_model_pong():
    # the emulator's bridge answers PING as the firmware does: 47 bytes, gen at 9, the consumed count at 11
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pico_model import PicoModel
    got = []
    m = PicoModel(lambda: 0, to_pi=lambda d, t: got.append(d))
    m.gen, m.consumed = 0x1234, 0x89ABCDEF
    m._frame(bytes([pico.F_PING]))
    f = pico.cobs_decode(got[-1][:-1])
    assert len(f) == 47 and f[0] == pico.F_PONG, f
    assert struct.unpack_from('<HI', f, 9) == (0x1234, 0x89ABCDEF), f


# ---- the two copies of the protocol: gridlink's pico.py and pico-bridge's protocol.py ---------------------------
# pico-bridge/pi installs on its own (gpibctl), so each keeps its copy; these keep them in step.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, 'pico-bridge', 'pi'))
from gpibbridge import protocol as P


def test_same_constants():
    names = [n for n in dir(P) if n.split('_')[0] in ('F', 'CF', 'DF', 'TXF')] + ['EVENTS', 'TX_CHUNK',
                                                                                  'PROTO_VERSION', 'PICO_VID']
    assert len(names) >= 20, names
    diff = [(n, getattr(P, n), getattr(pico, n, None)) for n in names if getattr(P, n) != getattr(pico, n, None)]
    assert not diff, diff
    # gridlink reads PONG's consumed count at offset 11 (X122): the daemon's PONG_FMT puts it there too
    i = P.PONG_FIELDS.index('tx_consumed')
    assert P.PONG_FMT.startswith('<8BH9I') and 1 + struct.calcsize('<8BH') == 11 and i == 9, (P.PONG_FMT, i)
    assert 1 + struct.calcsize(P.PONG_FMT) == 47


def frames_mix():
    """Frames as the bridge sends them, zeros inside, and the damage a tty can do: an overlong run, bad COBS."""
    import random
    r = random.Random(1520)
    good = [bytes([pico.F_DATA]) + bytes(r.choice((0, 0, r.randrange(256))) for _ in range(r.randrange(1, 300)))
            for _ in range(40)]
    s = b''.join(cobs_encode(f) for f in good[:10])
    s += bytes(r.randrange(1, 256) for _ in range(5000)) + b'\0'          # overlong, ended
    s += b''.join(cobs_encode(f) for f in good[10:20])
    s += b'\x05\x01\0'                                                     # bad COBS
    s += b'\0\0' + b''.join(cobs_encode(f) for f in good[20:30])          # empty runs
    s += bytes(r.randrange(1, 256) for _ in range(4500))                   # overlong, its 0x00 in the next part
    s += bytes(r.randrange(1, 256) for _ in range(300)) + b'\0'
    s += b''.join(cobs_encode(f) for f in good[30:])
    return s


def deframe_both(stream, cuts):
    d = P.Deframer()
    p = PicoProto(lambda b: None, log=lambda *a: None)
    got = []
    p._frame = lambda f: got.append(f) or b''
    want = []
    for a, b in zip(cuts, cuts[1:]):
        want += d.feed(stream[a:b]); p.feed(stream[a:b])
    return want, got, d.bad, p.stats['bad_frames']


def test_same_deframing():
    import random
    s = frames_mix()
    r = random.Random(7)
    for name, cuts in (('whole', [0, len(s)]), ('byte by byte', list(range(len(s) + 1))),
                       ('in pieces', sorted({0, len(s)} | {r.randrange(len(s)) for _ in range(200)}))):
        want, got, bad_d, bad_p = deframe_both(s, cuts)
        assert len(want) == 40 and want == got, (name, len(want), len(got))
        assert bad_d == bad_p == 3, (name, bad_d, bad_p)          # (the two overlong runs and the bad COBS)


def test_same_cobs():
    import random
    r = random.Random(3)
    for n in (0, 1, 253, 254, 255, 508, 1000, 3300):
        for zeros in (0, 1, 3):
            data = bytes(r.choice((0,) * zeros + (r.randrange(1, 256),)) for _ in range(n))
            a, b = cobs_encode(data), P.cobs_encode(data)
            assert a == b, (n, zeros)
            assert pico.cobs_decode(a[:-1]) == P.cobs_decode(b[:-1]) == data, (n, zeros)


if __name__ == '__main__':
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    if len(sys.argv) > 1: names = [n for n in names if any(a in n for a in sys.argv[1:])]
    ok = 0
    for n in names:
        try:
            globals()[n](); ok += 1; print('ok  ', n)
        except Exception:
            import traceback; print('FAIL', n); traceback.print_exc()
    print('%d of %d passed' % (ok, len(names)))
    sys.exit(0 if ok == len(names) else 1)
