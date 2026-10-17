"""gridfox (CLAUDE /W): Firefox on the Pi as text on the GRiD.

The layout and keys on their own; the real extract.js and act.js against a
stand-in Firefox (fake_firefox.py: Marionette + jsdom); the app driven key by
key; and end to end through gridlink and the GRiD's link (GridSim).

    python3 tests/test_gridfox.py        (needs Node and `npm ci` in tests/; skips without)
"""
import io, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import pyte
from fake_firefox import FakeFirefox, missing
from gridfox import page as P
from gridfox.app import App, Keys, Line, to_url, looks_like_url, BODY
from gridfox.browser import Browser
from gridfox.marionette import Marionette

U = 'http://test.local/'


# ---- layout -----------------------------------------------------------------
def test_wrap_and_clean():
    cs = P.cells([['one two three four five six seven', 0, -1]])
    lines = [''.join(c for c, _, _ in l) for l in P.wrap(cs, 10)]
    assert lines == ['one two', 'three four', 'five six', 'seven'], lines
    long = P.cells([['x' * 25, 0, -1]])
    assert [len(l) for l in P.wrap(long, 10)] == [10, 10, 5]
    assert P.clean('café “hi” ​x \U0001F600y 中') == 'café "hi" x y ?'
    assert all(len(t) <= 80 for t in P.layout({'blocks': [{'k': 'p', 'r': [['w ' * 300, 0, -1]]}]}).text)


def test_layout_kinds():
    m = {'blocks': [
        {'k': 'h1', 'r': [['Title', 0, -1]]},
        {'k': 'p', 'r': [['See ', 0, -1], ['this link', 0, 0], ['.', 0, -1]]},
        {'k': 'li', 'd': 1, 'm': -1, 'r': [['a', 0, -1]]},
        {'k': 'li', 'd': 2, 'm': 2, 'r': [['b', 0, 1]]},
        {'k': 'pre', 'r': [['x = 1\n  y = 2', 4, -1]]},
        {'k': 'hr', 'r': []},
        {'k': 'h3', 'r': [['Sub', 0, -1]]}]}
    d = P.layout(m)
    t = d.text
    assert t[0] == 'Title'.ljust(80) and all(a & P.A_INV for a in d.attr[0])
    assert t[2] == 'See this link.' and d.attr[2][4] == P.A_LINK and d.act[2][4] == 0 and d.act[2][3] == -1
    assert t[4] == '• a' and t[5] == '  2. b', t
    assert t[7:9] == ['  x = 1', '    y = 2'], t
    assert t[10] == '─' * 80 and t[12] == '▸ Sub', t
    assert d.where == {0: (2, 4), 1: (5, 5)}, d.where
    assert d.acts_in(0, 3) == [0] and d.find('y = 2') == 8


def test_keys_and_line():
    k = Keys()
    assert k.feed(b'a\x1b[A\x1b[6~\t\x1b[Z\r\x7f\x1bg\xc3\xa9') == ['a', 'up', 'pgdn', 'tab', 'btab', 'enter',
                                                                      'bksp', 'meta-g', 'é']
    assert k.feed(b'\x1b[', 0) == [] and k.feed(b'B', 0) == ['down']         # split across reads
    assert k.feed(b'\x1b', 10.0) == [] and k.take(10.1) == ['esc']           # a lone Esc, after a moment
    ln = Line('Go: ', 'abc')
    for x in ['left', 'X', 'home', 'Y', 'end', 'bksp']: ln.key(x)
    assert ln.text == 'YabX', ln.text
    assert looks_like_url('example.com') and looks_like_url('http://x') and not looks_like_url('two words')
    assert to_url('example.com/a') == 'https://example.com/a'
    assert to_url('7854 manual').endswith('q=7854+manual')


# ---- the real scripts on a stand-in Firefox ---------------------------------
_FAKE = None


def fake(slow=None):
    """The module's one stand-in Firefox (node and jsdom start once), reset."""
    global _FAKE
    if _FAKE is None: _FAKE = FakeFirefox()
    return _FAKE.reset(slow)


def browser(slow=None):
    f = fake(slow)
    m = Marionette(port=f.port); m.new_session()
    return f, m, Browser(m)


def test_extract():
    f, m, b = browser()
    try:
        b.open(U + 'index')
        mod = b.read()
        d = P.layout(mod)
        text = '\n'.join(d.text)
        assert mod['title'] == 'Test Bench Home' and mod['url'] == U + 'index'
        assert 'hidden' not in text and 'Nor this' not in text
        assert 'programs are stored in RAM' in text                       # whitespace folded
        assert '• 7A26 dual-trace amplifier' in d.text and '  • delayed sweep' in d.text
        assert '3. Third' in d.text and '4. Fourth' in d.text
        assert 'Item │ Value' in d.text and 'Points │ 512' in d.text
        assert '  20   GOTO 10' in d.text                                 # pre keeps its spaces
        assert '│ Measure twice, cut once.' in d.text
        assert 'Grüße, café' in text and '[scope photo]' in text
        kinds = [a['t'] for a in mod['acts']]
        assert kinds == ['link'] * 5 + ['button', 'select', 'check'], kinds
        assert mod['acts'][6]['opts'] == ['Volts', 'Amps', 'Ohms']
        assert mod['acts'][1]['h'] == U + 'long'
    finally:
        m.close()


# ---- the app, key by key ----------------------------------------------------
class Run:
    def __init__(s, start=None):
        s.f, s.m, s.b = browser()
        s.out = io.BytesIO()
        s.app = App(s.b, out=s.out)
        s.scr = pyte.Screen(80, 24); s.st = pyte.ByteStream(s.scr)
        s.app.draw(full=True)
        if start: s.app.go(start)
        s.pump()

    def pump(s):
        s.st.feed(s.out.getvalue()); s.out.seek(0); s.out.truncate()

    def keys(s, *ks):
        for k in ks:
            if len(k) > 1 and k not in ('up', 'down', 'pgdn', 'pgup', 'home', 'end', 'tab', 'btab', 'enter',
                                         'bksp', 'esc', 'left', 'right', 'f6'):
                for c in k: s.app.key(c)
            else: s.app.key(k)
        s.pump()

    def text(s): return [l.rstrip() for l in s.scr.display]

    def has(s, t): return any(t in l for l in s.text())

    def rereads(s):
        """The app's timed looks at the page, done now."""
        time.sleep(0.4)
        while s.app.rereads: s.app.rereads.pop(0); s.app.reread()
        s.pump()

    def close(s): s.m.close()


def test_app_open_follow_back():
    r = Run(U + 'index')
    try:
        t = r.text()
        assert t[0].strip() == U + 'index' and r.scr.buffer[0][1].reverse     # the address bar
        assert r.has('Tektronix 7854 notes') and r.has('Plug-ins')
        assert r.scr.buffer[1][0].data == 'H' and r.scr.buffer[1][0].underscore  # links underlined
        r.keys('tab')
        assert r.app.sel == 0 and r.scr.buffer[1][0].reverse and r.text()[23].strip().startswith(U + 'index')
        r.keys('tab', 'enter')                                 # the second link: Long page
        assert r.app.url == U + 'long' and r.has('Paragraph 1 of the long page.'), r.text()
        r.keys('pgdn', 'pgdn')
        top = r.app.top
        assert top == 2 * (BODY - 2) and r.has('Paragraph %d of' % (top // 2)), (top, r.text())
        r.keys('end')
        assert r.has('The end of the long page.') and r.text()[23].endswith('Bot')
        r.keys('home', 'left')                                  # back
        assert r.app.url == U + 'index' and r.app.top == 0 and r.app.sel == 1
        r.keys('right')                                         # forward: the long page, where we were
        assert r.app.url == U + 'long' and r.app.top == 0, r.app.top
    finally:
        r.close()


def test_app_hints_and_find():
    r = Run(U + 'index')
    try:
        r.keys('f')
        assert r.scr.buffer[1][0].data == '1' and r.scr.buffer[1][0].reverse     # numbers over the links
        assert r.has('Link number')
        r.keys('4', 'enter')                                    # Sign in (1..9 would be ambiguous with 2 digits)
        assert r.app.url == U + 'login', (r.app.url, r.text())
        r.keys('left', '/')
        assert r.text()[23].startswith('Find:')
        r.keys('GOTO', 'enter')
        assert 'Found on line' in r.text()[23] and r.has('20   GOTO 10'), r.text()
    finally:
        r.close()


def test_app_search_form():
    r = Run(U + 'search')
    try:
        r.keys('tab')
        assert r.app.acts()[r.app.sel]['t'] == 'field'
        r.keys('enter')
        assert r.text()[23].startswith('Search words:')
        r.keys('7854 manual', 'enter')                          # the form's only field: sent
        assert r.app.url.startswith(U + 'search?q=7854+manual'), r.app.url
        assert r.has('Results for 7854 manual:') and r.has('The long page about 7854 manual'), r.text()
        assert r.app.model['title'] == 'Search: 7854 manual'
    finally:
        r.close()


def test_app_login_two_fields():
    r = Run(U + 'login')
    try:
        r.keys('tab', 'enter', 'joshua', 'enter')               # user: on to the password
        assert r.app.url == U + 'login' and r.app.acts()[r.app.sel]['type'] == 'password', r.app.sel
        assert r.has('[joshua')
        r.keys('enter', 'hunter2')
        assert r.text()[23].endswith('*******'), r.text()[23]    # the password isn't shown
        r.keys('enter')
        assert r.has('Welcome, joshua (7 letter password)'), r.text()
    finally:
        r.close()


def test_app_button_select_check():
    r = Run(U + 'index')
    try:
        btn = [i for i, a in enumerate(r.app.acts()) if a['t'] == 'button'][0]
        r.app.select(btn); r.keys('enter')
        assert r.has('Clicked 1 times.'), r.text()             # same page, read again
        r.app.select(btn); r.keys('enter')
        assert r.has('Clicked 2 times.')
        sel = [i for i, a in enumerate(r.app.acts()) if a['t'] == 'select'][0]
        r.app.select(sel); r.keys('enter')
        assert r.has('│ ▸ Volts') and r.has('Ohms'), r.text()    # the choices
        r.keys('down', 'down', 'enter')
        assert r.has('[Ohms ▼]'), r.text()
        cb = [i for i, a in enumerate(r.app.acts()) if a['t'] == 'check'][0]
        r.app.select(cb); r.keys('enter')
        assert r.has('[x] Averaging'), r.text()
    finally:
        r.close()


def test_app_late_content_and_help():
    r = Run(U + 'late')
    try:
        assert r.has('Loading...')
        r.rereads()
        assert r.has('Filled in by script later.'), r.text()
        r.keys('h')
        assert r.has('gridfox: Firefox on the GRiD') and r.text()[0].strip() == 'gridfox'
        r.keys('g')
        assert r.text()[23].startswith('Go:')
        r.keys('test.local/long', 'enter')
        # "test.local/long" has a dot: an address (https:// is added; the stand-in has no TLS, so 404 there)
        assert r.app.url.startswith('https://test.local/long'), r.app.url
    finally:
        r.close()


# ---- what the review found (2026-10-17) ------------------------------------
def test_session_shape_and_real_clicks():
    r = Run(U + 'index')
    try:
        assert r.f.caps['pageLoadStrategy'] == 'eager' and r.f.caps['unhandledPromptBehavior'] == 'dismiss'
        r.keys('tab', 'tab', 'enter')
        assert r.app.url == U + 'long' and r.f.clicks, (r.app.url, r.f.clicks)     # WebDriver:ElementClick
        assert 'WebDriver:ElementClick' in r.f.calls
    finally:
        r.close()


def test_hostile_page():
    r = Run(U + 'hostile')
    try:
        t = '\n'.join(r.text())
        d = r.app.doc.text
        # a list starting at 1e80 or Infinity: laid out, numbers in bounds
        assert '99999. huge start' in d and '1. exponent start' in d, d
        assert '1. infinite start' in d and '1. negative start' in d, d
        assert 'zero widthhere and a tab in it' in d, d                             # (U+2028 is space to JS)
        assert 'in 1 \u2502 in 2' in d and '\u2502 outer C' in d, d                  # the outer row goes on
        assert any('Shadow before Slotted title shadow after' in l for l in d), d     # the slot, in place
        assert not any('unslotted' in l for l in d)
        assert all(len(l) <= 80 for l in d)
        # nothing from the page reaches the terminal as a control sequence
        r.out.seek(0); r.out.truncate()
        evil = [i for i, a in enumerate(r.app.acts()) if a.get('name') == 'user'][0]
        r.app.select(evil); r.app.key('enter')
        raw = r.out.getvalue(); r.pump()
        for bad in (b'\x1bc', b'\x1b[2J', b'\x07', b'\x1b]0;pwned'):
            assert bad not in raw, (bad, raw)
        assert r.text()[23].startswith('Name[2J: x[2Jcboom'), r.text()[23]
        assert r.text()[0].strip() == U + 'hostile' and r.scr.buffer[0][1].reverse     # the screen intact
        r.keys('esc')
        ta = [i for i, a in enumerate(r.app.acts()) if a.get('type') == 'textarea'][0]
        r.app.select(ta); r.keys('enter')
        assert 'line one\u23celine two' in r.text()[23] and r.text()[0].strip() == U + 'hostile', r.text()
        r.keys('esc')
    finally:
        r.close()


def test_form_not_sent_early():
    r = Run(U + 'form2')
    try:
        r.keys('tab', 'enter', 'joshua', 'enter')               # a check box follows: not sent yet
        assert r.app.url == U + 'form2' and r.app.acts()[r.app.sel]['t'] == 'check', r.app.url
        r.keys('enter')                                         # tick it
        assert r.has('[x] Terms')
        r.keys('tab', 'enter')                                  # the Order button
        assert r.has('Welcome, joshua (5 letter password)'), r.text()     # (pw=terms)
    finally:
        r.close()


def test_slow_page_after_click():
    f, m, b = browser(slow={'long': 1.0})
    out = io.BytesIO(); app = App(b, out=out)
    try:
        app.go(U + 'index')
        app.select(1); t0 = time.time(); app.key('enter')         # Long page, which takes a second
        assert app.url == U + 'long' and time.time() - t0 >= 0.9, app.url
        assert any('Paragraph 1 of the long page.' in l for l in app.doc.text)
    finally:
        m.close()


def test_covered_link_falls_back():
    r = Run(U + 'hostile')
    try:
        cov = [i for i, a in enumerate(r.app.acts()) if a['t'] == 'link'][0]
        r.app.select(cov); r.keys('enter')
        assert r.app.url == U + 'long' and not r.f.clicks, r.app.url          # refused, then a script click
    finally:
        r.close()


def test_help_back_and_errors():
    r = Run(U + 'index')
    try:
        r.keys('pgdn'); top = r.app.top
        hist = (list(r.f.hist), r.f.pos)
        r.keys('h', 'left')
        assert r.app.url == U + 'index' and r.app.top == top and (list(r.f.hist), r.f.pos) == hist
        r.keys('g'); r.app.key('ctrl-u'); r.keys('error.test', 'enter')    # (Go starts with the address)
        assert 'Could not open it' in r.text()[23] and 'error page' in r.text()[23], r.text()[23]
    finally:
        r.close()


def test_keys_timing():
    k = Keys()
    assert k.feed(b'\x1b', 0.0) == [] and k.take(0.02) == ['esc']           # Term's lone Esc
    assert k.feed(b'g', 0.05) == ['g']
    assert k.feed(b'\x1bO', 1.0) == [] and k.take(1.05) == [] and k.take(1.2) == ['esc', 'O']
    assert P.clean('a\u2028b\u1161c') == 'abc'


def _loop(r, fd):
    import threading
    th = threading.Thread(target=r.app.run, args=(fd,), daemon=True); th.start()
    return th


def test_no_spin_while_typing():
    import gridfox.app as A
    r = Run(U + 'late'); rd, wr = os.pipe()
    calls = [0]; real = A.select.select

    def counting(*a):
        calls[0] += 1; return real(*a)
    A.select.select = counting
    try:
        th = _loop(r, rd)
        time.sleep(0.2); os.write(wr, b'g'); time.sleep(0.2)
        r.app.rereads = [time.time() - 1]                        # a look due while the editor is open
        calls[0] = 0; time.sleep(1.0)
        assert calls[0] < 20, calls[0]
        os.write(wr, b'\x11'); th.join(3)                         # Ctrl-Q
        assert not th.is_alive()
    finally:
        A.select.select = real; os.close(wr); os.close(rd); r.close()


def test_lost_firefox_ends_gridfox():
    r = Run(U + 'index'); rd, wr = os.pipe()
    try:
        th = _loop(r, rd)
        time.sleep(0.2)
        r.m.sock.close()                                         # Firefox gone
        os.write(wr, b'.')                                       # read again: the call fails
        th.join(5)
        assert not th.is_alive() and r.app.lost, r.app.lost
    finally:
        os.close(wr); os.close(rd)
        time.sleep(0.2)                                          # (the stand-in sees the session go)


# ---- Joshua's review (2026-10-17) -------------------------------------------
def test_anchor_links_keep_the_page():
    r = Run(U + 'anchors')
    try:
        assert '#' not in r.app.url
        r.keys('tab', 'enter')                                   # GPIB commands: #gpib, the same document
        assert r.app.url == U + 'anchors#gpib', r.app.url
        top = r.app.top
        assert top > 0 and r.app.doc.text[top].strip() == 'GPIB commands', (top, r.text())
        assert r.has('ID? asks for the identity.')
        r.app.url_t = 0; r.app._check_url(); r.pump()           # the idle look at the address: no jump
        assert r.app.top == top, r.app.top
        r.keys('home')
        end = [i for i, a in enumerate(r.app.acts()) if a.get('h', '').endswith('#end')][0]
        r.app.select(end); r.keys('enter')                       # #end: an <a name> in an empty spot
        assert r.app.url == U + 'anchors#end' and r.has('The very end.'), r.text()
        r.keys('home')
        idx = [i for i, a in enumerate(r.app.acts()) if a.get('h', '').endswith('/long')][0]
        r.app.select(idx); r.keys('enter')                       # a real new page still starts at the top
        assert r.app.url == U + 'long' and r.app.top == 0
        r.f.reset(); r.app.go(U + 'anchors#gpib'); r.pump()      # an address with a #fragment, opened
        assert r.app.doc.text[r.app.top].strip() == 'GPIB commands', r.app.top
    finally:
        r.close()


def test_pushstate_keeps_the_place():
    r = Run(U + 'anchors')
    try:
        btn = [i for i, a in enumerate(r.app.acts()) if a.get('v') == 'Next view'][0]
        r.app.select(btn); top = r.app.top
        r.keys('enter')                                          # the page changes its own address
        assert r.app.url == U + 'anchors?view=2', r.app.url
        assert r.app.top == top and r.has('View two'), (r.app.top, top, r.text())
        r.app._check_url(); r.pump()
        assert r.app.top == top
    finally:
        r.close()


def test_labels_and_details():
    r = Run(U + 'anchors')
    try:
        d = r.app.doc.text
        assert '[+] More settings' in d and 'Hidden until opened.' not in d, d[-12:]
        assert '[-] Open already' in d and 'Shown from the start.' in d
        cs = [i for i, a in enumerate(r.app.acts()) if a.get('name') == 'cs'][0]
        r.app.select(cs); r.keys('enter')
        assert r.text()[23].startswith('Call sign:'), r.text()[23]            # <label for>
        r.keys('esc')
        sq = [i for i, a in enumerate(r.app.acts()) if a.get('name') == 'sq'][0]
        r.app.select(sq); r.keys('enter')
        assert r.text()[23].startswith('Grid square:'), r.text()[23]          # a wrapping <label>
        r.keys('esc')
        det = [i for i, a in enumerate(r.app.acts()) if a.get('v') == 'More settings'][0]
        r.app.select(det); r.keys('enter')                                    # Return opens it
        assert '[-] More settings' in r.app.doc.text and 'Hidden until opened.' in r.app.doc.text
    finally:
        r.close()


def test_firefox_quits_cleanly():
    import subprocess
    from gridfox.marionette import Firefox

    class M:                        # what stop() needs of Marionette
        dead = False
        def __init__(s, ok): s.ok = ok; s.asked = 0
        def quit(s): s.asked += 1; return s.ok
    fx = Firefox()
    fx.proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.3)'])
    m = M(True); t0 = time.time(); fx.stop(m, wait=5)
    assert m.asked == 1 and fx.proc.returncode == 0 and time.time() - t0 < 2      # asked, then waited for it
    fx.proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    m = M(False); fx.stop(m, wait=0.5)
    assert m.asked == 1 and fx.proc.returncode is not None                       # refused: SIGTERM after all
    fx.proc = None; fx.stop(M(True))                                             # not ours: left alone


def test_web_exit_banner():
    from gridlink.term import TermSession
    from gridlink.config import Config
    import tempfile
    cfg = Config(); cfg.web_dir = tempfile.mkdtemp()
    t = TermSession(cfg, web=True, command=[sys.executable, '-c', 'import sys; sys.exit(3)'], log=lambda m: None)
    try:
        t.start(); end = time.time() + 5
        while time.time() < end and t.exited is None: time.sleep(0.05)
        time.sleep(0.1)
        text = '\n'.join(t.text())
        assert 'gridfox exited (it lost Firefox) (code 3)' in text and 'python' not in text, text
    finally:
        t.stop()


# ---- end to end: gridlink + the GRiD's link (GridSim) -----------------------
def test_end_to_end_gridsim():
    from gridsim import TermHarness
    f = FakeFirefox()
    try:
        cmd = '%s -m gridfox --port %d %sindex' % (sys.executable, f.port, U)
        os.environ['ANTHROPIC_API_KEY'] = 'sk-must-not-reach-gridfox'
        h = TermHarness(app='web', web_command=cmd)
        h.cfg.term_api_key = True                                              # even so
        try:
            assert h.wait_text('Tektronix 7854 notes', wall=20), (h.log, h.grid.screen_text())
            assert h.router.app == 'web' and h.router.term is None             # no Claude Code started
            assert h.router.web.cwd == h.cfg.web_dir != h.cfg.term_dir         # not in ~/grid
            env = open('/proc/%d/environ' % h.router.web.child.pid, 'rb').read().split(b'\0')
            assert not any(e.startswith(b'ANTHROPIC_API_KEY=') for e in env)
            os.environ.pop('ANTHROPIC_API_KEY', None)
            assert h.run_until(lambda: h.grid.title == b'Test Bench Home', 5), h.grid.title   # (at most once a second)
            assert h.settle()
            h.grid.press(0x09, 0x0F); h.grid.press(0x09, 0x0F)
            assert h.settle()
            b0 = h.grid.stats['rx_bytes']
            h.grid.press(0x0D, 0x1C)
            assert h.wait_text('Paragraph 1 of the long page.', wall=10), h.grid.screen_text()
            assert h.settle()
            b1 = h.grid.stats['rx_bytes']
            h.grid.press(0, 0x51)                                               # PgDn
            assert h.wait_text('Paragraph 20 of', wall=10), h.grid.screen_text()
            assert h.settle()
            b2 = h.grid.stats['rx_bytes']
            print('     a new page: %d bytes to the GRiD; a screen down: %d' % (b1 - b0, b2 - b1))
            assert b1 - b0 < 3000 and b2 - b1 < 2000, (b1 - b0, b2 - b1)
            h.grid.press(0x08, 0x0E)                                            # Backspace: back
            assert h.wait_text('Plug-ins', wall=10), h.grid.screen_text()
            assert h.settle()
            assert not h.nano.violations, h.nano.violations
            assert h.grid.stats['fail'] == 0, h.grid.stats
            errs = [l for l in h.log if 'Traceback' in str(l)]
            assert not errs, errs
        finally:
            h.close()
    finally:
        os.environ.pop('ANTHROPIC_API_KEY', None)
        f.close()


NO_BROWSER = ('test_wrap_and_clean', 'test_layout_kinds', 'test_keys_and_line', 'test_keys_timing',
              'test_firefox_quits_cleanly', 'test_web_exit_banner')       # (these run without the stand-in)

if __name__ == '__main__':
    tests = [(n, v) for n, v in sorted(globals().items()) if n.startswith('test_') and callable(v)]
    only = sys.argv[1:]
    bad = 0
    why = missing()
    if why: print('skip: the stand-in Firefox needs Node and jsdom (%s); only the tests without it run' % why)
    for n, t in tests:
        if only and not any(o in n for o in only): continue
        if why and n not in NO_BROWSER: print('skip %s' % n); continue
        t0 = time.time()
        try:
            t(); print('ok   %-34s %.1fs' % (n, time.time() - t0))
        except Exception:
            bad += 1
            import traceback; print('FAIL %s' % n); traceback.print_exc()
    print('%d failed' % bad if bad else 'all passed')
    sys.exit(1 if bad else 0)
