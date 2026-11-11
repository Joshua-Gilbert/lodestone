"""CLAUDE.COM 1.13 in a terminal window (Lodestone's multitasking) in
emulation: grid_emu's FakeMT stands in for MT (MT_PUB, MT_WAKE, MT_LIST,
and MT's front for a graphics mode and back for a text one), against the
real gridlink with a stand-in Claude Code in a pty.  In its window CLAUDE
draws its shadow alone (25 rows, the status band its last) and publishes
it; the Executive's screen (B800h) is never written while it is behind.

    python3 tests/test_emu_window.py [outdir]
"""
import os, struct, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_emu import EmuHarness, FakeMT
from gridlink import glp, picture as PIC
import test_emu_term as TT

PBF_SHOWN, PBF_NOCUR = 1, 2


def start(window=True, front=False, args='/A:7', mouse=False, connect=True, term=TT.FAKE, **kw):
    h = EmuHarness(term=term, args=args, **kw)
    h.mt = FakeMT(window, front); h.mt.attach(h.m)
    if mouse: h.m.mouse = {'presses': []}
    h.boot()
    if connect:
        assert h.run_until(lambda: h.var('term') == 1 and h.var('connected') == 1, 10), (h.m.crash, h.log, h.mt.log)
    h.paint_claude_stack()                      # (check() reads how deep it went)
    return h


def desc(h):
    """The descriptor CLAUDE published (MTAPI.INC's PB_*)."""
    es, di = h.mt.desc
    b = h.m.rd(es, di, 22)
    return dict(ver=b[0], flags=b[1], cols=b[2], rows=b[3], cells=struct.unpack_from('<HH', b, 4),
                font=struct.unpack_from('<HH', b, 8), first=b[12], gend=b[13],
                cur=struct.unpack_from('<H', b, 14)[0], chg=struct.unpack_from('<H', b, 16)[0],
                xlat=struct.unpack_from('<HH', b, 18))


def shadow(h):
    """The shadow, 25 rows of (glyphs, attributes): what the window draws."""
    raw = h.m.rd(h.var('shadseg', 2), 0, 25 * 160)
    return [bytes(raw[r * 160:(r + 1) * 160:2]) for r in range(25)], [bytes(raw[r * 160 + 1:(r + 1) * 160:2]) for r in range(25)]


def wtext(h):
    cs, _ = shadow(h)
    return '\n'.join(''.join(chr(c) if 32 <= c < 127 else ' ' for c in r).rstrip() for r in cs)


def win_in_step(h, sim_s=20):
    """The shadow's rows 0-23 are pyte's, and the descriptor's cursor its."""
    def same():
        t = h.router.web if h.router.app == 'web' else h.router.term
        if h.m.crash or t.dirty: return False
        tc, ta, cur = TT.pi_cells(h)
        cs, ats = shadow(h)
        d = desc(h)
        want = (cur[0] << 8 | cur[1]) if cur else None
        got = None if d['flags'] & PBF_NOCUR else d['cur']
        return cs[:24] == tc and ats[:24] == ta and got == want
    return h.run_until(same, sim_s)


def wait_wtext(h, text, sim_s=20):
    return h.run_until(lambda: text in wtext(h), sim_s)


def pixels_on_screen(h):
    """Rows 0-383 of the mode 40h screen as a picture's bytes (80 a line)."""
    v = h.m.rd(0xB800, 0, 0x8000)
    return b''.join(v[(y & 3) * 0x2000 + (y >> 2) * 80:(y & 3) * 0x2000 + (y >> 2) * 80 + 80] for y in range(PIC.H))


def test_window_second():
    """Another task runs CLAUDE.COM already (MT_LIST: a second CODE-A): this
    one says so and ends, publishing nothing, the link not touched."""
    h = EmuHarness(term=TT.FAKE, args='/A:7')
    h.mt = FakeMT(); h.mt.others = [(2, 'CLAUDE.COM')]; h.mt.attach(h.m)
    try:
        h.boot()
        assert h.run_until(lambda: h.m.stopped, 10), (h.mt.log, ''.join(h.m.tty)[-200:])
        assert 'running already' in ''.join(h.m.tty), ''.join(h.m.tty)[-200:]
        assert h.mt.desc is None and 'pub' not in h.mt.log and not h.var('connected'), h.mt.log
    finally:
        h.close()


def test_window_term():
    """Published, never drawn on the screen: the descriptor, the shadow in
    step with Claude Code's screen, its cursor and the status band."""
    h = start()
    try:
        assert wait_wtext(h, 'Welcome to Claude Code'), wtext(h)
        assert win_in_step(h), wtext(h)
        assert h.mt.wake == 1, h.mt.log                                    # (MT_WAKE asked)
        d = desc(h)
        assert (d['ver'], d['cols'], d['rows'], d['first'], d['gend']) == (2, 80, 25, 0x20, 0xAF), d
        assert d['flags'] & PBF_SHOWN, d
        assert d['cells'] == (0, h.var('shadseg', 2)), d                  # (offset, segment)
        assert d['font'] == (h.sym['font'], h.claude_psp), d
        fs, fo = d['font'][1], d['font'][0]
        assert h.m.rd(fs, fo, (0xAF - 0x20) * 16) == h.font_img, 'the font published is not CLAUDE\'s'
        xs, xo = d['xlat'][1], d['xlat'][0]
        xl = h.m.rd(xs, xo, 128)
        assert xl[0] == ord('*') and xl[0x18] == 0xC0 and xl[0x0D] == 0xC4 and xl[0x2F:] == bytes(81), xl
        assert '[mode 40h]' not in h.m.log, h.m.log
        assert h.m.mode() == 3 and h.mt.vwrites == 0, (h.m.mode(), h.mt.vwrites)
        assert 'CODE-Q quits' in wtext(h).split('\n')[24], wtext(h)
        assert all(a & 1 for a in shadow(h)[1][24]), 'the band is not inverse'
        chg = desc(h)['chg']
        h.term_type('hello'); h.press(0x1C0D)
        assert wait_wtext(h, 'You said: hello'), wtext(h)
        assert win_in_step(h), wtext(h)
        assert desc(h)['chg'] > chg + 3, (chg, desc(h)['chg'])
        t = h.router.term                                       # (a cursor shown: BH its row, BL its column)
        with t.lock:
            t.stream.feed(b'\x1b[?25h\x1b[5;12H'); t._mark()
        t.link.wake()
        assert win_in_step(h), (wtext(h), hex(desc(h)['cur']))
        assert desc(h)['cur'] == 0x040B and not desc(h)['flags'] & PBF_NOCUR, (hex(desc(h)['cur']), desc(h)['flags'])
        with t.lock:
            t.stream.feed(b'\x1b[?25l'); t._mark()
        t.link.wake()
        assert win_in_step(h) and desc(h)['flags'] & PBF_NOCUR, desc(h)['flags']
        h.term_type('big'); h.press(0x1C0D)
        assert wait_wtext(h, 'line 59'), wtext(h)
        assert win_in_step(h), wtext(h)
        assert h.mt.vwrites == 0 and h.mt.desc and not h.mt.front, (h.mt.vwrites, h.mt.log)
        TT.check(h)
    finally:
        h.close()


def test_window_size():
    """T5e: Claude Code 2.1 lays out the whole terminal (the mascot at the top,
    the prompt box pinned to the bottom), so a window showing 19 of 24 rows
    lost the mascot.  The window's rows (PB_VIEW, which MT writes from
    TERM.RUN's MT_TROWS) go to the Pi (EVENT 08h): its pty is that tall, the
    program lays out for it, and the descriptor publishes those rows alone."""
    h = start(term=TT.FAKE + ' --full')
    try:
        t = h.router.term
        assert wait_wtext(h, 'Claude Code (fake, full)') and wait_wtext(h, 'rows: 24'), wtext(h)
        d = desc(h)
        assert d['ver'] == 2 and d['rows'] == 25 and t.rows == 24, (d, t.rows)
        assert h.mt.view(h.m, 19)
        assert h.run_until(lambda: t.rows == 19 and 'rows: 19' in wtext(h) and desc(h)['rows'] == 19, 20), \
            (t.rows, desc(h), wtext(h))
        assert win_in_step(h), wtext(h)
        cs, _ = shadow(h)
        crow = desc(h)['cur'] >> 8
        assert crow == 15 and any(0xA1 <= c <= 0xAE for c in cs[1]) and 'shortcuts' in wtext(h).split('\n')[17], (crow, wtext(h))
        assert all(r == b' ' * 80 for r in cs[19:24]), 'rows past the window\'s not blank'
        h.term_type('hi'); h.press(0x1C0D)
        assert wait_wtext(h, 'You said: hi') and win_in_step(h), wtext(h)
        for v, want in ((12, 12), (30, 24), (2, 4)):
            h.mt.view(h.m, v)
            assert h.run_until(lambda: t.rows == want and (want < 12 or 'rows: %d' % want in wtext(h)), 20), \
                (v, t.rows, wtext(h))                       # (at 4 rows the stand-in's own rows overlap)
            assert h.run_until(lambda: desc(h)['rows'] == (want if want < 24 else 25), 5), (v, desc(h))
            assert win_in_step(h), wtext(h)
        h.mt.view(h.m, 19)
        assert h.run_until(lambda: t.rows == 19, 20), t.rows
        h.mt.window = False; h.mt.front = True              # (its window gone, it in front: full screen for good)
        assert h.run_until(lambda: not h.var('wmode') and t.rows == 24 and 'rows: 24' in '\n'.join(t.screen.text()), 20), \
            (h.var('wmode'), t.rows, h.mt.log)
        TT.check(h)
    finally:
        h.close()


def test_window_size_older_pi():
    """A Pi that doesn't say HF_SIZE: no EVENT 08h, 24 rows and the
    descriptor's 25 (the status band) as before."""
    keep = glp.HF_SIZE
    glp.HF_SIZE = 0
    h = start(term=TT.FAKE + ' --full')
    try:
        t = h.router.term
        assert wait_wtext(h, 'rows: 24'), wtext(h)
        assert h.mt.view(h.m, 19)
        h.run_until(lambda: False, 0.8)
        assert t.rows == 24 and desc(h)['rows'] == 25 and h.var('pi_rows') == 24, (t.rows, desc(h))
        TT.check(h)
    finally:
        glp.HF_SIZE = keep
        h.close()


def test_window_web():
    """CLAUDE /W in a window: the window's 19 rows make gridfox's pty 19 rows
    (T5e), and gridfox lays out for them: the address in row 0, the page under
    it, its status line in row 18, in view; rows 19-23 blank.  Full screen
    for good: 24 rows, the status line in row 23 again."""
    from fake_firefox import FakeFirefox, missing
    if missing():
        print('     skipped: %s (the stand-in Firefox runs on Node and jsdom)' % missing())
        return
    f = FakeFirefox()
    url = 'http://test.local/index'
    h = start(args='/A:7 /W', web='%s -m gridfox --port %d %s' % (sys.executable, f.port, url))
    try:
        assert wait_wtext(h, 'Tektronix 7854 notes', 30), (h.log, wtext(h))
        w = h.router.web
        assert h.router.app == 'web' and h.router.term is None and w.rows == 24, (h.router.app, w.rows)
        rows = lambda: wtext(h).split('\n')
        status = lambda r: rows()[r].rstrip().endswith(('All', 'Top'))
        assert h.run_until(lambda: rows()[0].strip() == url and status(23), 20), wtext(h)
        assert h.mt.view(h.m, 19)
        assert h.run_until(lambda: w.rows == 19 and desc(h)['rows'] == 19 and rows()[0].strip() == url
                           and status(18) and not any(l.strip() for l in rows()[19:24]), 20), \
            (w.rows, desc(h), wtext(h))
        assert win_in_step(h), wtext(h)
        assert 'Tektronix 7854 notes' in wtext(h)
        h.press(0x0F09); h.press(0x0F09); h.press(0x1C0D)                  # Tab Tab Return: the long page
        assert wait_wtext(h, 'Paragraph 1 of the long page.'), wtext(h)
        h.press(0x5100)                                                     # PgDn: 17 rows less two
        assert h.run_until(lambda: 'Paragraph 1 of' not in wtext(h) and 'Paragraph 15 of' in wtext(h)
                           and rows()[18].rstrip().endswith('%'), 20), wtext(h)
        assert win_in_step(h), wtext(h)
        h.mt.window = False; h.mt.front = True              # (its window gone, it in front: full screen for good)
        assert h.run_until(lambda: not h.var('wmode') and w.rows == 24, 20), (h.var('wmode'), w.rows, h.mt.log)
        assert h.run_until(lambda: w.screen.display[23].rstrip().endswith('%')
                           and w.screen.display[0].strip() == 'http://test.local/long', 20), w.screen.display
        TT.check(h)
    finally:
        h.close(); f.close()


def picture_round_trip(h):
    t = h.router.term
    page = bytes((y * 7 + x) & 0xFF if (y // 16) % 3 == 0 else 0 for y in range(PIC.H) for x in range(80))
    t.show_picture(page, 'test', title='A picture')
    assert h.run_until(lambda: h.mt.front and h.m.mode() == 0x40 and pixels_on_screen(h) == page, 20), \
        (h.mt.log, h.m.mode())
    assert h.var('pic') and not h.var('win'), 'not full screen for the picture'
    assert not desc(h)['flags'] & PBF_SHOWN, desc(h)
    pubs = h.mt.pubs
    assert t.hide_picture('test')
    assert h.run_until(lambda: not h.mt.front and h.var('win') and not h.var('pic'), 20), h.mt.log
    assert h.m.mode() == 3 and desc(h)['flags'] & PBF_SHOWN and h.mt.pubs > pubs, (h.m.mode(), h.mt.log)
    assert win_in_step(h), wtext(h)
    w = h.mt.vwrites
    h.term_type('after'); h.press(0x1C0D)
    assert wait_wtext(h, 'You said: after'), wtext(h)
    assert win_in_step(h) and h.mt.vwrites == w, h.mt.vwrites - w
    assert h.mt.log.count('front') == 1 and h.mt.log.count('back') == 1, h.mt.log


def test_window_picture():
    """A picture: full screen (the mode 40h set brings the task to the front),
    drawn bit for bit; its end: back to the window (mode 3), in step."""
    h = start()
    try:
        assert wait_wtext(h, 'Welcome to Claude Code') and win_in_step(h), wtext(h)
        picture_round_trip(h)
        assert h.var('fpic_seen'), 'F_PIC never seen'
        TT.check(h)
    finally:
        h.close()


def test_window_picture_older_pi():
    """A Pi that doesn't mark pictures' frames (no F_PIC): a frame that clears
    and has no pixels ends the picture."""
    keep = PIC.F_PIC
    PIC.F_PIC = 0
    h = start()
    try:
        assert wait_wtext(h, 'Welcome to Claude Code') and win_in_step(h), wtext(h)
        picture_round_trip(h)
        assert not h.var('fpic_seen'), 'F_PIC seen from an older Pi'
        TT.check(h)
    finally:
        PIC.F_PIC = keep
        h.close()


def test_window_click():
    """A click in the window (TERM gives rows of 8, INT 33h's text units):
    the Pi gets pixels, rows of 16."""
    h = start(mouse=True)
    try:
        assert wait_wtext(h, 'Welcome to Claude Code') and win_in_step(h), wtext(h)
        got = []
        t = h.router.term
        real = t.click_at
        t.click_at = lambda x, y: got.append((x, y)) or real(x, y)
        h.m.mouse['presses'].append((12 * 8, 5 * 8))
        h.press(0x3900); h.run_until(lambda: got, 10)              # (a key wakes it to look)
        assert got and got[0] == (12 * 8, 5 * 16), got
        TT.check(h)
    finally:
        h.close()


SNAPME = bytes([0xBA, 0x0C, 0x01, 0xB4, 0x09, 0xCD, 0x21, 0xB8, 0x00, 0x4C, 0xCD, 0x21]) + b'WINDOW SNAP$'


def test_window_run_and_snapshot():
    """RUN in the window: the program's pages shown there (PBF_SHOWN off),
    no mode 40h; its snapshot read through INT 10h (B800h is the
    Executive's behind); then published again, in step."""
    h = start(files={'A:\\SNAPME.COM': SNAPME})
    try:
        assert wait_wtext(h, 'Welcome to Claude Code') and win_in_step(h), wtext(h)
        g = h.router.term.grid
        pubs, res, n = h.mt.pubs, {}, len(h.mt.log)
        th = threading.Thread(target=lambda: res.update(r=g.run('SNAPME', capture=False, snapshot=True)))
        th.start()
        assert h.run_until(lambda: not th.is_alive(), 30), 'RUN did not finish'
        assert res['r']['exit'] == 0 and res['r']['snapshot'], res
        assert 'mode 03' in h.mt.log[n:], h.mt.log[n:]                   # (the program's pages meanwhile:
        assert 'mode 03 shown' not in h.mt.log[n:], h.mt.log[n:]         #  its screen not shown)
        assert h.m.reads08 >= 2000, h.m.reads08                            # (2000 cells through INT 10h)
        assert '[mode 40h]' not in h.m.log and h.mt.vwrites == 0, h.mt.vwrites
        assert h.run_until(lambda: desc(h)['flags'] & PBF_SHOWN and h.mt.pubs > pubs, 5), h.mt.log
        snap = {}
        th = threading.Thread(target=lambda: snap.update(r=g.screen(0)))
        th.start()
        assert h.run_until(lambda: not th.is_alive(), 30), 'SCREEN did not finish'
        s = snap['r']
        mode, banks, bpp, width, height, bpl = s[0], s[1], s[2], *struct.unpack_from('<HHH', s, 3)
        assert (mode, banks, bpp, width, height, bpl) == (3, 1, 0, 80, 25, 160), s[:9]
        text = bytes(s[9::2]).decode('cp437')
        assert 'WINDOW SNAP' in text, text[:200]
        assert win_in_step(h), wtext(h)
        TT.check(h)
    finally:
        h.close()


def test_window_screen():
    """SCREEN in the window: our own screen from the shadow, as mode 40h's
    (B800h is the Executive's): its 25 rows with CLAUDE's font."""
    h = start()
    try:
        assert wait_wtext(h, 'Welcome to Claude Code') and win_in_step(h), wtext(h)
        g = h.router.term.grid
        snap = {}
        th = threading.Thread(target=lambda: snap.update(r=g.screen(1)))
        th.start()
        assert h.run_until(lambda: not th.is_alive(), 30), 'SCREEN did not finish'
        s = snap['r']
        assert (s[0], s[1], s[2]) == (0x40, 4, 1) and struct.unpack_from('<HHH', s, 3) == (640, 400, 80), s[:9]
        vram = s[9:9 + 0x8000]
        assert 'Welcome to Claude Code' in h.font.screen(vram), h.font.screen(vram)
        assert 'CODE-Q quits' in h.font.screen(vram).split('\n')[24]
        assert h.mt.vwrites == 0 and '[mode 40h]' not in h.m.log
        TT.check(h)
    finally:
        h.close()


def test_window_none_in_front():
    """A task in front with no window (FULL=, no TERM.RUN): full screen at
    once, the descriptor withdrawn; Term as ever."""
    h = start(window=False, front=True)
    try:
        assert h.m.mode() == 0x40 and h.mt.desc is None and not h.var('wmode'), (h.m.mode(), h.mt.log)
        assert h.run_until(lambda: 'Welcome to Claude Code' in h.screen(), 20), h.screen()
        assert TT.in_step(h), TT.mismatch(h)
        assert h.mt.wake == 1
        TT.check(h)
    finally:
        h.close()


def test_window_late_then_gone():
    """Behind with no window yet: drawn in the shadow, published again at
    its ticks.  A window then: still.  None, and in front: full screen."""
    h = start(window=False, front=False)
    try:
        assert h.var('wmode') and h.var('win') and h.m.mode() == 3, h.mt.log
        assert wait_wtext(h, 'Welcome to Claude Code'), wtext(h)
        pubs = h.mt.pubs
        h.run_until(lambda: False, 2)
        assert h.mt.pubs >= pubs + 3, (pubs, h.mt.pubs)                    # (every 9 ticks: 2 s, 4)
        h.mt.window = True
        h.run_until(lambda: False, 1)
        assert h.var('wmode') and h.mt.vwrites == 0
        h.mt.window = False; h.mt.front = True
        assert h.run_until(lambda: not h.var('wmode') and h.m.mode() == 0x40, 3), h.mt.log
        assert h.mt.desc is None, h.mt.log
        assert TT.in_step(h), TT.mismatch(h)
        TT.check(h)
    finally:
        h.close()


def test_window_chat():
    """The Pi chooses chat: full screen for good, as for a picture."""
    from test_emu import reply
    h = EmuHarness([reply(('text', 'Hello from chat.'))], args='/A:7')
    h.mt = FakeMT(); h.mt.attach(h.m)
    try:
        h.boot()
        assert h.connect(), (h.m.crash, h.mt.log)
        assert not h.var('term') and not h.var('wmode') and h.m.mode() == 0x40, h.mt.log
        assert h.mt.desc is None and 'front' in h.mt.log, h.mt.log
        assert h.turn('hi') and 'Hello from chat.' in h.screen(), h.screen()
    finally:
        h.close()


def test_window_slash_c():
    """CLAUDE /C: never published (chat is full screen); woken by SRQ still."""
    from test_emu import reply
    h = EmuHarness([reply(('text', 'Hi.'))], args='/A:7 /C')
    h.mt = FakeMT(); h.mt.attach(h.m)
    try:
        h.boot()
        assert h.connect(), (h.m.crash, h.mt.log)
        assert h.mt.pubs == 0 and h.mt.wake == 1 and not h.var('wmode'), h.mt.log
    finally:
        h.close()


def test_window_quit():
    """CODE-Q: withdrawn, then the program ends."""
    h = start()
    try:
        assert wait_wtext(h, 'Welcome to Claude Code'), wtext(h)
        h.press(0x1000)
        assert h.run_until(lambda: h.m.stopped or h.m.exit_code is not None or 'Claude for GRiD ended' in ''.join(h.m.tty), 10), h.mt.log
        assert h.mt.desc is None and h.mt.log[-2:] == ['withdrawn', 'mode 03'], h.mt.log   # (then leave's mode)
        TT.check(h)
    finally:
        h.close()


if __name__ == '__main__':
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    if len(sys.argv) > 1 and sys.argv[1].startswith('test_'): names = sys.argv[1:]
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
