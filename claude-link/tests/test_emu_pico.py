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


def big_turn(trace=None, setup=None, **kw):
    h = start([reply(('tool', 'str_replace_based_edit_tool',
                      {'command': 'create', 'path': 'A:\\BIG.TXT', 'file_text': BIG})),
               reply(('tool', 'str_replace_based_edit_tool', {'command': 'view', 'path': 'A:\\BIG.TXT', 'view_range': [395, 400]})),
               reply(('text', 'Written and checked.'))], mode='edits', **dict(dict(bridge='pico'), **kw))
    if trace is not None: h.link.trace = h.link.t.proto.trace = trace
    if setup: setup(h)
    t0 = h.m.us
    assert h.turn('write a big file', sim_s=120)
    assert bytes(h.m.fs['A:\\BIG.TXT']) == BIG.replace('\n', '\r\n').encode()
    assert 'line 00399' in results(h, 2)[0]['content']
    check(h)
    return h, (h.m.us - t0) / 1e6


def test_hello_announces_rx():
    h, _ = big_turn()
    assert h.link.grid_rx == 3340 and h.link.maxpay == 3340, (h.link.grid_rx, h.link.maxpay)
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


def test_ring_gives_up_and_takes_the_srq_back():
    # a GRiD that doesn't answer (CLAUDE ended: the Executive, a DOS program, TM5000): RING_TRIES rings, then
    # the SRQ is taken back, so it isn't left held on the bus; nothing more until the GRiD sends again
    h = start([], mode='edits', bridge='pico')
    assert h.connect()
    r0, u0 = h.link.stats['rang'], h.link.stats['unrung']
    h.link.send(glp.P_TEXT, b'nobody there\r\n')
    srq = []
    for i in range(20):                       # (the GRiD stopped: only time goes on, 0.12 s a step)
        h.m.us += 120000
        h.link.ring_check()
        h.nano.service()
        srq.append(h.nano.srq)
    assert h.link.stats['rang'] - r0 == h.link.RING_TRIES and h.link.stats['unrung'] - u0 == 1, h.link.stats
    assert any(srq) and not any(srq[-10:]), srq
    # and a GRiD that comes back: its next frame lets us ring again
    h.link.stats['rang'] = 0
    assert h.run_until(lambda: h.link.stats['rx_frames'] > 0 and 'nobody there' in h.screen(), sim_s=3.0)
    check(h)


def test_no_rings_while_busy():
    # a copy keeps the GRiD busy (its next frame comes within RING_IDLE): no rings in between
    h, _ = big_turn()
    assert h.link.stats['rang'] <= 3, h.link.stats['rang']


def test_held_replies():
    # bridge fw 2026-10-23c: while a message goes to the GRiD in fragments, gridlink gives the bridge the
    # GRiD's next POLL and the answer to it; the bridge answers that POLL itself, no round trip to the Pi
    h0, t0 = big_turn()
    h, t = big_turn(bridge='pico-hold')
    st = h.link.stats
    # (CLAUDE 1.6: the 22 KB file goes as a 16 KB request of five 3340-byte frames and a 6 KB one of two: 4 + 1)
    assert h.transport.proto.holds and st['tx_held'] >= 5, (h.transport.proto.firmware, st)
    assert h.nano.n_held == st['tx_held'] == h.transport.proto.stats['held'], (h.nano.n_held, st)
    assert not h.nano.violations, h.nano.violations
    assert abs(t - t0) < 0.5, (t, t0)          # (the emulation doesn't time the Pi: no gain shows here)
    # and switched off (gridlink.bench --nohold): none
    h2, _ = big_turn(bridge='pico-hold', setup=lambda h: setattr(h.link, 'holding', False))
    assert h2.link.stats['tx_held'] == 0 and h2.nano.n_held == 0


def test_held_reply_bookkeeping():
    # Link alone, on a transport that holds: a used hold answers nothing and moves on as an answer would; a
    # missed one (the GRiD sent something else) is answered as usual, with the same fragment
    class T:
        frame_limit = 4104
        def __init__(t): t.sent, t.holds, t.used = [], [], False
        def answer(t, f): t.sent.append(f)
        def hold(t, expect, frame): t.holds.append((expect, frame)); return True
        def hold_used(t): u, t.used = t.used, False; return u
    t = T()
    from gridlink.link import Link
    k = Link(t, lambda *a: None, log=lambda *a: None, hold=0.0)
    k.grid_rx = 2048; k.last_g = 4; k.connected = True; k.rx_fl = True
    body = bytes(range(256)) * 24                     # 6 KB: three fragments
    k.send(glp.P_REQUEST, body)
    poll = lambda seq, ack: glp.Frame(glp.G_POLL, seq, ack, b'', fl=True)
    k.handle(poll(5, 0))                              # -> fragment 1 sent, fragment 2 held for POLL 6
    f1 = glp.decode(t.sent[-1], 8192)[0]
    assert f1.more and f1.payload == body[:2048] and f1.seq == 1, f1
    exp, held = t.holds[-1]
    assert exp == glp.encode(glp.G_POLL, 6, 1, b'', fl=True), exp
    h2 = glp.decode(held, 8192)[0]
    assert h2.seq == 2 and h2.ack == 6 and h2.more and h2.payload == body[2048:4096], h2
    n = len(t.sent)
    t.used = True
    k.handle(poll(6, 1))                              # the bridge answered it: nothing from us
    assert len(t.sent) == n and k.pi_seq == 2 and k.last_answer == held and k.stats['tx_held'] == 1
    exp, held3 = t.holds[-1]
    assert exp == glp.encode(glp.G_POLL, 7, 2, b'', fl=True)
    h3 = glp.decode(held3, 8192)[0]
    assert h3.seq == 3 and not h3.more and h3.payload == body[4096:], h3
    k.handle(glp.Frame(glp.G_KEYS, 7, 2, b'x', fl=True))   # not the POLL: answered as usual, the same fragment
    f3 = glp.decode(t.sent[-1], 8192)[0]
    assert len(t.sent) == n + 1 and f3.seq == 3 and f3.payload == body[4096:] and k.cur is None, f3
    assert len(t.holds) == 2                          # (the message's last fragment: nothing more to hold)


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
