"""The real CLAUDE.COM + GRIDGPIB.COM through the GPIB-Pico2 bridge model (pico_model.py) and the real
gridlink PicoProto: frames to the GRiD as big as its HELLO's rx= says, split into TX frames that fit the
firmware's input buffer, and the old 246-byte frames for a CLAUDE that doesn't say.

    python3 tests/test_emu_pico.py          (also prints emulated times for a sweep of frame sizes)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_anthropic import reply
from test_emu import start, check, results
from gridlink import glp

BIG = ''.join('line %05d: the quick brown fox jumps over the lazy dog\n' % i for i in range(400))


def big_turn(trace=None, **kw):
    h = start([reply(('tool', 'str_replace_based_edit_tool',
                      {'command': 'create', 'path': 'A:\\BIG.TXT', 'file_text': BIG})),
               reply(('tool', 'str_replace_based_edit_tool', {'command': 'view', 'path': 'A:\\BIG.TXT', 'view_range': [395, 400]})),
               reply(('text', 'Written and checked.'))], mode='edits', bridge='pico', **kw)
    if trace is not None: h.link.trace = h.link.t.proto.trace = trace
    t0 = h.m.us
    assert h.turn('write a big file', sim_s=120)
    assert bytes(h.m.fs['A:\\BIG.TXT']) == BIG.replace('\n', '\r\n').encode()
    assert 'line 00399' in results(h, 2)[0]['content']
    check(h)
    return h, (h.m.us - t0) / 1e6


def test_hello_announces_rx():
    h, _ = big_turn()
    assert h.link.grid_rx == 2048 and h.link.maxpay == 2048, (h.link.grid_rx, h.link.maxpay)
    assert h.nano.big_tx == 0 and not h.nano.violations, h.nano.violations
    assert h.link.stats['tx_bytes'] > 20000


def test_big_frames_are_split_for_the_pico():
    h, _ = big_turn()
    # a 2 KB GLP frame went as TX frames of at most 512 bytes, EOI only on the last
    assert h.nano.tx_frames > h.link.stats['tx_frames'], (h.nano.tx_frames, h.link.stats['tx_frames'])


def test_old_frame_size_still_works():
    h, _ = big_turn(frame_cap=glp.GRID_RX_DEFAULT)
    assert h.link.maxpay == 246


def test_trace():
    # gridlink.bench --trace: the link's frames and the bridge's GPIB events, in order
    import collections
    tr = collections.deque()
    big_turn(trace=tr)
    names = [e for _, e in tr]
    for want in ('pi REQUEST+ big', 'grid POLL', 'grid REPLY+ big', 'send'):
        assert want in names, (want, sorted(set(names)))
    assert all(a[0] <= b[0] for a, b in zip(tr, list(tr)[1:]))
    # (the model sends no GPIB events; the firmware's reach the trace through PicoProto)
    import struct
    from gridlink.pico import PicoProto, cobs_encode, F_EVENT
    p = PicoProto(lambda d: None, log=lambda *a: None)
    p.connected = True; p.trace = collections.deque()
    p.feed(cobs_encode(struct.pack('<BBHBI', F_EVENT, 0x1D, 0, 0, 0)))
    assert [e for _, e in p.trace] == ['TX_DONE'], p.trace


def test_ring_wakes_an_idle_grid():
    # GF_WAKE: with something to send while the GRiD is idle, gridlink rings (WAKE), the bridge raises SRQ and
    # CLAUDE POLLs at once instead of at its next once-a-second idle POLL
    h = start([], mode='edits', bridge='pico')
    assert h.link.grid_wake
    lat = []
    for i in range(4):
        assert h.connect()
        h.run_until(lambda: False, sim_s=0.3 + 0.17 * i)    # somewhere in the idle second
        n, t0 = h.link.stats['rx_frames'], h.m.us
        h.link.send(glp.P_TEXT, b'ring %d\r\n' % i)
        assert h.run_until(lambda: h.link.stats['rx_frames'] > n, sim_s=2.0)
        lat.append((h.m.us - t0) / 1e3)
    # GRIDGPIB 1.2 takes SRQ on IRQ 5, which wakes CLAUDE's HLT at once (without it: up to a 55 ms tick)
    assert h.nano.rings >= 4 and max(lat) < 20 and h.m.irqs5 > 0, (h.nano.rings, lat, h.m.irqs5)
    check(h)


def test_old_claude_gets_246():
    body = bytes([1, 3, 0, 4, 80, 20]) + b'os=DOS 3.30\ngrid=CLAUDE 1.2\napp=term\n'
    assert glp.hello_rx(body) == 246
    assert glp.hello_rx(bytes(6) + b'rx=100000\n') == glp.GRID_RX_MAX
    assert glp.hello_rx(bytes(6) + b'rx=12\n') == 246


def sweep():
    print('emulated (4 us per basic block, about a 10 MHz 286; +-30 %): one turn writing and reading 22.8 KB')
    for cap in (246, 512, 1024, 2048, 4096):
        h, t = big_turn(frame_cap=cap)
        print('  frames of %4d: %.2f s' % (cap, t))


if __name__ == '__main__':
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    ok = 0
    for n in names:
        try:
            globals()[n](); ok += 1; print('ok  ', n)
        except Exception:
            import traceback; print('FAIL', n); traceback.print_exc()
    print('%d of %d passed' % (ok, len(names)))
    if ok == len(names) and '--no-sweep' not in sys.argv: sweep()
    sys.exit(0 if ok == len(names) else 1)
