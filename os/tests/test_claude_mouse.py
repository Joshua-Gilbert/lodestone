"""CLAUDE /W and the mouse, on the Lodestone kernel: pcemu's serial mouse,
the kernel's own INT 33h, the real CLAUDE.COM, the real gridlink, and gridfox
on the stand-in Firefox (claude-link/tests/fake_firefox.py, Node + jsdom).

A left click goes to the Pi as EVENT 05h (its pixel).  On gridfox's links
gridlink hands it to gridfox as an xterm mouse report, and gridfox follows
the link; on a plot Claude Code showed (grid_plot), the point is typed into
Claude Code's prompt.

    python3 tests/test_claude_mouse.py
"""
import os, shutil, sys, tempfile, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import claude_kernel as CK                      # (claude-link's tests on the path)
import grid_emu as G
from fake_firefox import FakeFirefox, missing

CL = os.path.join(GOS, 'claude')
FAKE = '%s %s' % (sys.executable, os.path.join(CK.GL_TESTS, 'fake_claude.py'))
U = 'http://test.local/'


def claude_w():
    """CLAUDE.COM as `CLAUDE /W` leaves it: app_want = 'W' (the Executive
    runs a program without arguments).  With its MAP, for the harness."""
    d = tempfile.mkdtemp(prefix='claudew-')
    sym = G.symbols(os.path.join(CL, 'CLAUDE.MAP'))
    com = bytearray(open(os.path.join(CL, 'CLAUDE.COM'), 'rb').read())
    assert com[sym['app_want'] - 0x100] == 0
    com[sym['app_want'] - 0x100] = ord('W')
    open(os.path.join(d, 'CLAUDEW.COM'), 'wb').write(com)
    shutil.copy(os.path.join(CL, 'CLAUDE.MAP'), os.path.join(d, 'CLAUDEW.MAP'))
    return os.path.join(d, 'CLAUDEW.COM')


def harness(f, com, mouse=True):
    h = CK.KernelHarness(term=FAKE, claude_com=com)
    h.cfg.web_command = '%s -m gridfox --port %d %sindex' % (sys.executable, f.port, U)
    h.cfg.web_dir = os.path.join(h.tmp, 'web')
    h.m.mouse = mouse
    return h


def point(h, x, y):
    """Move the kernel's INT 33h pointer to pixel (x, y): 1 mickey a pixel
    across, 2 down (8 per 8 and 16 per 8, Microsoft's defaults)."""
    k = h.k
    for _ in range(60):
        dx, dy = x - k.u16('m33_x'), y - k.u16('m33_y')
        if not dx and not dy: return
        sx, sy = max(-100, min(100, dx)), max(-100, min(100, 2 * dy))
        h.m.mouse_move(sx & 0xFF, sy & 0xFF); h.m.run_for(0.03)
    raise AssertionError('pointer stuck at %d,%d' % (k.u16('m33_x'), k.u16('m33_y')))


def click(h, col, row):
    point(h, col * 8 + 3, row * 16 + 8)
    h.m.mouse_move(0, 0, 1); h.m.run_for(0.05)
    h.m.mouse_move(0, 0, 0); h.m.run_for(0.05)


def wait(h, text, sim_s=30):
    return h.run_until(lambda: text in h.screen(), sim_s)


results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''),
          flush=True)


def t_click_follows_a_link():
    f = FakeFirefox()
    h = harness(f, claude_w())
    try:
        h.boot()
        check('/W: Term, connected', h.run_until(lambda: h.var('term') and h.var('connected'), 15), h.log)
        check('/W: gridfox shows the page', wait(h, 'Tektronix 7854 notes'), h.screen())
        check('/W: the mouse found (INT 33h reset)', h.var('tmouse') == 0xFF, h.var('tmouse'))
        check('/W: the links row is drawn', wait(h, 'Long page | Search', 10), h.screen())   # (frames arrive in turn)
        rows = h.screen().split('\n')
        r = [i for i, l in enumerate(rows) if 'Long page' in l][0]
        c = rows[r].index('Long page') + 2
        click(h, c, r)
        check('a click on "Long page" follows it', wait(h, 'Paragraph 1 of the long page.'), h.screen())
        check('the address bar says so', h.run_until(lambda: h.screen().split('\n')[0].strip() == U + 'long', 10),
              h.screen().split('\n')[0])
        click(h, 10, 0)                                         # the address: Go
        check('a click on the address opens Go', wait(h, 'Go:', 10), h.screen().split('\n')[23])
        check('no link failures', h.var('n_fail', 2) == 0 and not h.m.crash, (h.var('n_fail', 2), h.m.crash))
    finally:
        h.close(); f.close()


def t_no_mouse():
    """No mouse on the 1520: /W still works, from the keys."""
    f = FakeFirefox()
    h = harness(f, claude_w(), mouse=False)
    try:
        h.boot()
        check('no mouse: gridfox shows the page', wait(h, 'Tektronix 7854 notes'), h.screen())
        check('no mouse: tmouse 0', h.var('tmouse') == 0, h.var('tmouse'))
    finally:
        h.close(); f.close()


def t_plot_click_types_into_the_prompt():
    """CLAUDE (Term, no /W): the pointer is on there too.  A plot from
    grid_plot; a click on a point types it into Claude Code's prompt, and
    Claude Code's screen comes back."""
    sys.path.insert(0, CK.GL_TESTS)
    from gridlink import plot as PL
    import test_picture as TP
    h = CK.KernelHarness(term=FAKE)
    h.m.mouse = True
    try:
        h.boot()
        check('Term: connected', h.run_until(lambda: h.var('term') and h.var('connected'), 15), h.log)
        check('Term: Claude Code', wait(h, 'Welcome to Claude Code', 20), h.screen())
        check('Term: the mouse found', h.var('tmouse') == 0xFF, h.var('tmouse'))
        t = h.router.term
        check('Term: pictures (HELLO flags)', t.can_picture(), t.gflags)
        xs, ys = TP.sweep(201)
        p = PL.Plot([{'name': 'S21', 'x': xs, 'y': ys}], title='Filter', x_label='Hz', y_label='dB')
        t.tools.tools.viewer.show(p)
        check('the plot is up', h.run_until(lambda: not t.ready() and t.pic is not None and
                                                    'Esc: back' in h.screen().split('\n')[24], 30),
              h.screen().split('\n')[24])
        x, y = int(p.ax.px(xs[100])), int(p.ay.px(ys[100]))
        point(h, x, y)
        h.m.mouse_move(0, 0, 1); h.m.run_for(0.05)
        h.m.mouse_move(0, 0, 0); h.m.run_for(0.05)
        check('the click is typed into the prompt', wait(h, '[clicked plot "Filter": Hz = ', 20), h.screen())
        check('the nearest point', wait(h, 'nearest point: S21', 5), h.screen())
        check('Claude Code is back', t.pic is None and 'Welcome to Claude Code' in h.screen(), h.screen())
        check('no link failures', h.var('n_fail', 2) == 0 and not h.m.crash, (h.var('n_fail', 2), h.m.crash))
    finally:
        h.close()


def t_chat_leaves_the_mouse():
    """Chat (no Term): no pointer (chat draws without hiding it), no INT 33h polls."""
    h = CK.KernelHarness()
    h.m.mouse = True
    try:
        h.boot()
        check('chat: connected', h.run_until(lambda: h.var('connected'), 15), h.log)
        check('chat: not Term', h.var('term') == 0, h.var('term'))
        check('chat: tmouse 0', h.var('tmouse') == 0, h.var('tmouse'))
    finally:
        h.close()


def t_term_to_chat_hides_the_pointer():
    """Term, then a HELLO after a lost link that the Pi answers with chat:
    Term's pointer goes (it stayed, drawn over chat, tracking the mouse)."""
    h = CK.KernelHarness(term=FAKE)
    h.m.mouse = True
    try:
        h.boot()
        check('Term: connected, the pointer on', h.run_until(lambda: h.var('term') and h.var('tmouse') == 0xFF, 20) and
              h.k.u16('m33_cnt') == 0, (h.var('term'), h.var('tmouse'), h.k.u16('m33_cnt'), h.log[-3:]))
        h.cfg.app = 'chat'                      # the Pi's choice at the next HELLO
        real = h.transport.answer
        h.transport.answer = lambda f: None     # the Pi goes quiet
        lost = h.run_until(lambda: not h.var('connected'), 15)
        h.transport.answer = real
        check('chat after the link came back', lost and h.run_until(lambda: h.var('connected') and not h.var('term'), 20),
              (lost, h.var('connected'), h.var('term'), h.log[-3:]))
        check('... Term\'s pointer off', h.run_until(lambda: h.var('tmouse') == 0, 5) and h.k.u16('m33_cnt') != 0,
              (h.var('tmouse'), h.k.u16('m33_cnt')))
        check('... no crash', not h.m.crash, h.m.crash)
    finally:
        h.close()


if __name__ == '__main__':
    why = missing()
    if why:
        print('skip: the stand-in Firefox needs Node and jsdom (%s)' % why); sys.exit(0)
    for t in (t_click_follows_a_link, t_no_mouse, t_plot_click_types_into_the_prompt, t_chat_leaves_the_mouse,
              t_term_to_chat_hides_the_pointer):
        t0 = time.time()
        try:
            t()
        except Exception:
            check(t.__name__, False, traceback.format_exc())
        print('   (%.1f s)' % (time.time() - t0))
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed' % (len(results), len(bad)))
    sys.exit(1 if bad else 0)
