"""The Executive's screen saver inside CLAUDE.COM (1.14) in emulation: idle
full screen for the saver's delay (INT 21h F0h AL=5: grid_emu's FakeSaver,
a stub that blanks the screen and waits for a key as the real one does),
CLAUDE tells the Pi (EVENT 07h) and calls it; the Pi's ring (Claude Code's
screen changed, a GRiD tool) ends it as a key would, and so do a key and the
mouse; the GRiD's tools stay on meanwhile.  Against the real gridlink with
a stand-in Claude Code in a pty, and in chat.

    python3 tests/test_emu_saver.py
"""
import os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_emu import EmuHarness, FakeSaver
from gridlink import glp
from unicorn.x86_const import UC_X86_REG_SP as SP
import test_emu_term as T

DELAY = 36                                  # (ticks: 2 s)


def start(mouse=False, delay=DELAY, **kw):
    kw.setdefault('bridge', 'pico')             # (the ring: the Pico bridge's; an AR488 has none)
    h = EmuHarness(term=T.FAKE, args=kw.pop('args', '/A:7 /T'), **kw)
    sv = FakeSaver(delay); sv.attach(h.m)
    if mouse: h.m.mouse = {'presses': [], 'pos': (100, 50), 'btn': 0}
    h.boot()
    assert h.run_until(lambda: h.var('term') and h.var('connected'), 10), ('no Term', h.m.crash, h.log)
    assert h.run_until(lambda: 'Welcome to Claude Code' in h.screen(), 20), h.screen()
    lo, top = h.sym['stack_bottom'], h.sym['stack_top']
    h.m.mu.mem_write(h.claude_psp * 16 + lo, b'\xa5' * (h.m.mu.reg_read(SP) - 16 - lo))
    h.stk = (lo, top)
    return h, sv


def feed(h, text):
    """Claude Code writes on its screen (the Pi's pyte), as a pty would."""
    t = h.router.term
    with t.lock:
        t.stream.feed(text.encode()); t._mark()
    t.link.wake()


def test_saver_on_and_ended_by_the_pi():
    h, sv = start()
    try:
        t = h.router.term
        t0 = h.m.us
        assert h.run_until(sv.up, 10), ('no saver', sv.entries(), h.var('sv_st'), h.log[-5:])
        dt = (h.m.us - t0) / 1e6
        assert t.saver_on(), 'the Pi was not told (EVENT 07h)'
        assert not any(h.m.rd(0xB800, 0, 0x8000)), 'the stub blanked the screen'
        h.run_until(lambda: False, 12)
        t.link.last_rx -= 11; t.saver_at = t.link.last_rx   # (past the Pi's 10 s: its clock, which the emulator
                                                            #  outruns; nothing half-read for idle_check meanwhile)
        assert sv.up() and t.saver_on() and t.why_not() is None, (sv.up(), t.saver_on(), t.why_not())
        feed(h, '\x1b[5;3HNews from Claude Code')
        t1 = h.m.us
        assert h.run_until(lambda: not sv.up(), 5), 'the ring did not end it'
        lat = (h.m.us - t1) / 1000
        assert h.run_until(lambda: 'News from Claude Code' in h.screen(), 10), h.screen()
        assert T.in_step(h), T.mismatch(h)
        assert not t.saver_on() and sv.entries() == 1, (t.saver_on(), sv.entries())
        print('     on after %.1f s idle; the Pi\'s change ended it in %.0f ms' % (dt, lat))
        T.check(h)
    finally:
        h.close()


def test_saver_and_a_tool_call():
    h, sv = start()
    try:
        assert h.run_until(sv.up, 10), 'no saver'
        h.run_until(lambda: False, 12)
        res = {}
        th = threading.Thread(target=lambda: res.update(r=h.router.term.grid.get_info()))
        th.start()
        assert h.run_until(lambda: not th.is_alive(), 20), 'the call never came back'
        assert 'CLAUDE 1.14' in res.get('r', {}).get('grid', ''), res
        assert not sv.up(), 'still up'
        assert T.in_step(h), T.mismatch(h)
        T.check(h)
    finally:
        h.close()


def test_saver_key_and_mouse():
    h, sv = start(mouse=True)
    try:
        got = []
        keys = h.router.term.keys
        h.router.term.keys = lambda body: (got.append(bytes(body)), keys(body))
        for i in range(6):                          # the mouse moving, under the delay each time: no saver
            h.m.mouse['pos'] = (100 + 8 * i, 50)
            h.run_until(lambda: sv.entries() > 0, 1)
        assert sv.entries() == 0, 'on while the mouse moved'
        assert h.run_until(sv.up, 10), 'no saver'
        h.key(0x1E61)                               # "a": it ends the saver, and goes no further
        assert h.run_until(lambda: not sv.up(), 5), 'a key did not end it'
        h.run_until(lambda: False, 1)
        assert not got, ('the waking key reached the Pi', got)
        assert T.in_step(h), T.mismatch(h)
        assert h.run_until(lambda: sv.entries() == 2 and sv.up(), 10), ('not on again', sv.entries())
        h.m.mouse['pos'] = (300, 120)               # the mouse moved
        assert h.run_until(lambda: not sv.up(), 5), 'the mouse did not end it'
        assert T.in_step(h), T.mismatch(h)
        h.run_until(lambda: False, 1)
        assert sv.entries() == 2 and not sv.up(), 'it came on again at once'
        T.check(h)
    finally:
        h.close()


def test_no_saver_while_claude_code_writes():
    h, sv = start(delay=91)                         # (5 s: past Term's own 2 s after a change, in maybe_idle)
    try:
        for i in range(8):                          # (a change every 3 s of the GRiD's time: under the delay)
            feed(h, '\x1b[%d;3Hline %d' % (3 + i, i))
            h.run_until(lambda: sv.entries() > 0, 3)
        assert sv.entries() == 0, 'on while Claude Code wrote'
        assert h.run_until(sv.up, 15), 'never on after it'
        T.check(h)
    finally:
        h.close()


def test_no_saver_with_an_ar488():
    h, sv = start(bridge='ar488')                   # (no ring: nothing could end it for the Pi)
    try:
        h.run_until(lambda: False, 6)
        assert sv.entries() == 0 and not h.router.term.saver_on(), sv.entries()
    finally:
        h.close()


def test_no_saver_with_an_older_pi():
    old = glp.HF_SAVER
    glp.HF_SAVER = 0                            # (a gridlink before CLAUDE 1.14's: its HELLO without bit 4)
    try:
        h, sv = start()
        try:
            h.run_until(lambda: False, 6)
            assert sv.entries() == 0 and not h.router.term.saver_on(), sv.entries()
        finally:
            h.close()
    finally:
        glp.HF_SAVER = old


def test_saver_in_chat():
    h = EmuHarness(script=[], bridge='pico')
    sv = FakeSaver(DELAY); sv.attach(h.m)
    try:
        h.boot()
        assert h.connect(10), (h.m.crash, h.log[-5:])
        for i in range(6):                          # typing a prompt (nothing to the Pi yet): no saver
            h.key(0x1E61)
            h.run_until(lambda: sv.entries() > 0, 1)
        assert sv.entries() == 0, 'on while a prompt was typed'
        assert h.run_until(sv.up, 10), 'no saver in chat'
        h.key(0x1E61)
        assert h.run_until(lambda: not sv.up(), 5), 'a key did not end it'
        h.run_until(lambda: False, 0.5)
        assert any(h.m.rd(0xB800, 0, 0x8000)), 'not drawn again'
    finally:
        h.close()


if __name__ == '__main__':
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    if len(sys.argv) > 1: names = [n for n in names if any(a in n for a in sys.argv[1:])]
    bad = 0
    for n in names:
        t0 = time.time()
        try:
            globals()[n]()
            print('ok   %-38s %.1fs' % (n, time.time() - t0))
        except Exception:
            bad += 1
            print('FAIL %s' % n); traceback.print_exc()
    print('%d of %d passed' % (len(names) - bad, len(names)))
    sys.exit(1 if bad else 0)
