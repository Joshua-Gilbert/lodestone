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
