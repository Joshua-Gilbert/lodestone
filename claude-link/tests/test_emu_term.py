"""Term on the real CLAUDE.COM (CLAUDE /T) in emulation: the GRiD side of
the link, the CELLS decoder, the keyboard, RUN in the middle of a session,
against the real gridlink with a stand-in Claude Code in a pty.

    python3 tests/test_emu_term.py [outdir]
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_emu import EmuHarness
from gridlink import glp

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = '%s %s' % (sys.executable, os.path.join(HERE, 'fake_claude.py'))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('EMU_OUT', '')


def shot(h, name):
    if OUT:
        os.makedirs(OUT, exist_ok=True)
        h.shot(os.path.join(OUT, name + '.png'))


def start(**kw):
    h = EmuHarness(term=FAKE, args=kw.pop('args', '/A:7 /T'), **kw)
    h.boot()
    assert h.run_until(lambda: h.var('term') and h.var('connected'), 10), \
        ('no Term', h.m.crash, h.log, h.screen())
    assert h.run_until(lambda: 'Welcome to Claude Code' in h.screen(), 20), h.screen()
    assert in_step(h), mismatch(h)
    return h


def pi_cells(h):
    t = h.router.web if h.router.app == 'web' else h.router.term
    with t.lock:
        tc, ta = t.screen.cells()
        c = t.screen.cursor
        cur = None if c.hidden else (c.y, c.x)
    return [bytes(r) for r in tc], [bytes(r) for r in ta], cur


def in_step(h, sim_s=20):
    """The GRiD's shadow and screen are what pyte has on the Pi."""
    def same():
        t = h.router.web if h.router.app == 'web' else h.router.term
        if h.m.crash or t.dirty: return False
        tc, ta, cur = pi_cells(h)
        gc, ga = h.term_cells()
        return gc == tc and ga == ta and not h.term_vram_ok(tc, ta, cur)
    return h.run_until(same, sim_s)


def mismatch(h):
    tc, ta, cur = pi_cells(h)
    gc, ga = h.term_cells()
    rows = [r for r in range(24) if tc[r] != gc[r] or ta[r] != ga[r]]
    return 'rows differ: %s; bad cells on screen: %s\n%s' % (rows, h.term_vram_ok(tc, ta, cur)[:10], h.screen())


def check(h):
    assert not h.m.crash, h.m.crash
    assert not h.nano.violations, h.nano.violations
    errs = [l for l in h.log if 'Traceback' in str(l) or 'error' in str(l).lower()]
    assert not errs, errs
    assert h.var('n_fail', 2) == 0, ('link failures', h.var('n_fail', 2))


def wait_screen(h, text, sim_s=20):
    return h.run_until(lambda: text in h.screen(), sim_s)


def test_term_connect_and_type():
    h = start()
    try:
        assert 'CODE-Q quits' in h.screen().split('\n')[24], h.screen()
        assert 'DA ok' in h.screen()
        h.term_type('hello'); h.press(0x1C0D)
        assert wait_screen(h, 'You said: hello'), h.screen()
        assert in_step(h), mismatch(h)
        shot(h, 'term_hello')
        h.term_type('big'); h.press(0x1C0D)
        assert wait_screen(h, 'line 59'), h.screen()
        assert in_step(h), mismatch(h)
        h.term_type('diff'); h.press(0x1C0D)
        assert wait_screen(h, 'int rate = 5'), h.screen()
        assert in_step(h), mismatch(h)
        shot(h, 'term_diff')
        check(h)
    finally:
        h.close()


def test_term_keys():
    h = start()
    try:
        h.term_type('run dir'); h.press(0x1C0D)
        assert wait_screen(h, 'Do you want to proceed?'), h.screen()
        h.press(0x5000)                                    # Down
        h.press(0x1C0D)
        assert wait_screen(h, 'ran dir'), h.screen()
        h.press(0x0F00)                                    # Shift-Tab
        assert wait_screen(h, 'accept edits on'), h.screen()
        h.term_type('one'); h.press(0x1C00); h.term_type('two')   # CODE-Return: a new line
        assert wait_screen(h, '  two'), h.screen()
        assert in_step(h), mismatch(h)
        h.press(0x2E03)                                    # Ctrl-C clears the prompt
        assert h.run_until(lambda: 'two' not in h.screen(), 20), h.screen()
        assert in_step(h), mismatch(h)
        check(h)
    finally:
        h.close()


def test_term_repaint_and_run():
    h = start()
    try:
        h.term_type('hello'); h.press(0x1C0D)
        assert wait_screen(h, 'You said: hello'), h.screen()
        assert in_step(h), mismatch(h)
        # CODE-R: redraw here, and the Pi starts again from a clear screen
        h.m.wr(0xB800, 0, b'\xff' * 2000)                  # spoil the screen
        frames = h.router.term.enc.stats['frames']
        h.press(0x1300)
        assert h.run_until(lambda: h.router.term.enc.stats['frames'] > frames, 20)
        assert in_step(h), mismatch(h)
        # a DOS program run in the middle (what the MCP bridge does): text mode,
        # then the Term screen again from the shadow
        res = {}
        import threading
        th = threading.Thread(target=lambda: res.update(r=h.router.term.grid.run('VER', capture=False)))
        th.start()
        assert h.run_until(lambda: not th.is_alive(), 30), 'RUN did not finish'
        assert res['r']['exit'] == 0, res
        assert h.m.mode() == 0x40
        assert in_step(h), mismatch(h)
        assert 'CODE-Q quits' in h.screen().split('\n')[24]
        check(h)
    finally:
        h.close()


def test_term_ignores_chat_messages():
    h = start()
    try:
        h.link.send(glp.P_TEXT, b'stray chat text from a turn still running')
        h.link.send(glp.P_ASK, bytes([9, 2]) + b'Run it?\0\0\0')
        h.link.send(glp.P_READY)
        assert h.run_until(lambda: not h.link.busy(), 20)
        assert 'stray' not in h.screen() and not h.var('ask_open'), h.screen()
        assert in_step(h), mismatch(h)
        check(h)
    finally:
        h.close()


def test_term_repaint_flood_then_request():
    h = start()
    try:
        for _ in range(12): h.press(0x1300)          # CODE-R held down
        res = {}
        import threading
        th = threading.Thread(target=lambda: res.update(r=h.router.term.grid.get_info()))
        th.start()
        assert h.run_until(lambda: not th.is_alive(), 30), 'the request was lost'
        assert 'os' in res['r'], res
        assert in_step(h), mismatch(h)
        check(h)
    finally:
        h.close()


def test_hello_not_answered():
    # gridlink fails on the first HELLO (answers NOP): CLAUDE starts the link again
    h = EmuHarness(term=FAKE, args='/A:7 /T')
    real = h.router.on_message; n = [0]
    def flaky(t, b):
        if t == glp.G_HELLO and n[0] == 0:
            n[0] += 1; raise RuntimeError('first HELLO fails')
        return real(t, b)
    h.link.on_message = flaky
    try:
        h.boot()
        assert h.run_until(lambda: 'Welcome to Claude Code' in h.screen(), 30), h.screen()
        assert h.var('n_fail', 2) >= 1 and n[0] == 1
    finally:
        h.close()


def test_term_quit():
    h = start()
    try:
        h.press(0x1000)                                    # CODE-Q
        assert h.run_until(lambda: h.m.exited if hasattr(h.m, 'exited') else h.m.mode() == 3, 10), h.screen()
        check(h)
    finally:
        h.close()


def test_web_gridfox():
    """CLAUDE /W: the same Term path, showing gridfox (Firefox as text)."""
    from fake_firefox import FakeFirefox
    f = FakeFirefox()
    h = EmuHarness(term=FAKE, web='%s -m gridfox --port %d http://test.local/index' % (sys.executable, f.port),
                   args='/A:7 /W')
    try:
        h.boot()
        assert h.run_until(lambda: h.var('term') and h.var('connected'), 10), (h.m.crash, h.log, h.screen())
        assert wait_screen(h, 'Tektronix 7854 notes', 30), (h.log, h.screen())
        assert h.router.app == 'web' and h.router.term is None             # HELLO said app=web
        assert in_step(h), mismatch(h)
        shot(h, 'web_index')
        h.press(0x0F09); h.press(0x0F09); h.press(0x1C0D)                  # Tab Tab Return: the long page
        assert wait_screen(h, 'Paragraph 1 of the long page.'), h.screen()
        assert in_step(h), mismatch(h)
        h.press(0x5100)                                                     # PgDn
        assert wait_screen(h, 'Paragraph 20 of'), h.screen()
        assert in_step(h), mismatch(h)
        shot(h, 'web_long')
        check(h)
    finally:
        h.close(); f.close()


def test_term_echo_time():
    """Simulated GRiD time from a key to its echo on the GRiD's screen
    (the Pi's side runs in real time; the clock does not count it)."""
    h = start()
    try:
        lat = []; typed = ''
        for ch in 'echo time':
            h.run_until(lambda: False, 0.3)
            t0 = h.m.us
            h.term_type(ch); typed += ch
            assert h.run_until(lambda: '> ' + typed in h.screen(), 10), typed
            lat.append((h.m.us - t0) / 1000.0)
        lat.sort()
        print('     GRiD time, key to echo on screen (ms): median %.0f, worst %.0f' % (lat[len(lat) // 2], lat[-1]))
        check(h)
    finally:
        h.close()


if __name__ == '__main__':
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    bad = 0
    for n in names:
        t0 = time.time()
        try:
            globals()[n]()
            print('ok   %-34s %.1fs' % (n, time.time() - t0))
        except Exception:
            bad += 1
            print('FAIL %s' % n); traceback.print_exc()
    print('%d of %d passed' % (len(names) - bad, len(names)))
    sys.exit(1 if bad else 0)
