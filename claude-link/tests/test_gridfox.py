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
from gridlink import glp

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

    def click(s, col, row):
        s.app.key('click:%d:%d' % (col, row)); s.pump()

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


def test_app_rows():
    """A GRiD window's rows (T5e: the pty resized): the page gets all but the
    address and the status line, which is the last row; PgDn, End, Tab and a
    list's choices go by the page's rows; the place is kept through a resize."""
    r = Run(U + 'index')
    try:
        r.app.go(U + 'long'); r.pump()
        def at(rows):
            r.app.resize(rows); r.scr.resize(rows, 80); r.scr.reset(); r.app.draw(full=True); r.pump()
        at(19)
        assert r.app.nrows == 19 and r.app.body == 17, (r.app.nrows, r.app.body)
        t = r.text()
        assert len(t) == 19 and t[0].strip() == U + 'long' and t[18].endswith('Top'), t
        assert r.has('Paragraph 1 of the long page.'), t
        assert (r.scr.cursor.y, r.scr.cursor.x) == (18, 0), (r.scr.cursor.y, r.scr.cursor.x)   # hidden, parked:
        r.keys('pgdn')                                          # (a window follows it; at column 79 it lost 2)
        assert (r.scr.cursor.y, r.scr.cursor.x) == (18, 0), (r.scr.cursor.y, r.scr.cursor.x)
        assert r.app.top == 15 and r.text()[18].endswith('%'), (r.app.top, r.text()[18])   # 17 rows less two
        r.keys('/')                                             # the typing line: the last row, its cursor there
        assert r.text()[18].startswith('Find:') and r.scr.cursor.y == 18 and r.scr.cursor.x == 6, \
            (r.text()[18], r.scr.cursor.y, r.scr.cursor.x)
        assert r.app.rows()[1] == (18, 6), r.app.rows()[1]      # (as asked: pyte would clamp a row 23 to 18)
        r.keys('esc')
        r.keys('end')
        n = len(r.app.doc)
        assert r.app.top == n - 17 and r.has('The end of the long page.') and r.text()[18].endswith('Bot'), r.text()
        at(24)                                                  # taller: the place kept, still at the end
        assert r.app.body == 22 and r.app.top == n - 22 and r.text()[23].endswith('Bot'), (r.app.top, r.text())
        at(19)
        r.keys('home', 'left')                                  # back to the index
        assert r.app.url == U + 'index', r.app.url
        sel = [i for i, a in enumerate(r.app.acts()) if a['t'] == 'select'][0]
        r.app.select(sel); r.app.draw(); r.pump()
        ln = r.app.doc.where[sel][0]
        assert r.app.top <= ln < r.app.top + 17, (ln, r.app.top)          # Tab's scroll: within 17 rows
        r.keys('enter')
        assert r.has('│ ▸ Volts') and r.has('Ohms'), r.text()
        box = r.app._menu_box()
        assert box[0] + box[2] + 1 < 18, box                    # (the choices inside the page's rows)
        r.keys('esc')
        at(4)                                                   # the smallest a window gives: 2 page rows
        assert r.app.body == 2 and len(r.text()) == 4 and r.text()[0].strip() == U + 'index', r.text()
        top = r.app.top
        r.keys('pgdn')
        assert r.app.top == top + 1, (top, r.app.top)           # (at least a row)
        r.app.select(sel); r.keys('enter')                      # the choices, cut to the page's rows
        assert r.app.menu is not None and len(r.text()) == 4, r.text()
        r.keys('esc')
        r.keys('end', 'btab')                                   # Shift-Tab from the end: the link above, in view
        w = r.app.doc.where[r.app.sel][0]
        assert r.app.top <= w < r.app.top + 2, (r.app.sel, w, r.app.top)
        r.keys('f')                                             # F's numbers, then a resize: the links shown now
        at(19)
        assert r.app.hints and set(r.app.hints.values()) == set(r.app.doc.acts_in(r.app.top, 17)), r.app.hints
        r.keys('esc')
        r.app.go(U + 'long'); r.pump()
        d = r.app.doc
        lk = min(d.where[a][0] for a in d.where)                # F with a link in view, then a shrink that
        r.app.top = max(0, lk - 15); r.app.draw(); r.pump()     #  leaves none on the screen: no numbers
        r.keys('f')
        assert r.app.hints, (lk, r.app.top)
        at(4)
        assert not d.acts_in(r.app.top, 2) and r.app.hints is None and not r.app.modal(), (r.app.top, r.app.hints)
        r.keys('1')
        assert r.app.url == U + 'long', r.app.url
        at(4)
        r.keys('end', '/', *'Paragraph 3 of', 'enter')          # Find upwards: the line found in view
        assert r.has('Paragraph 3 of the long page.'), r.text()
        r.app.resize(2)
        assert r.app.nrows == 3 and r.app.body == 1             # (never under MIN_ROWS)
        r.app.resize(None)
        assert r.app.nrows == 24 and r.app.body == 22           # (no size known: 24)
    finally:
        r.close()


def test_app_cols():
    """A GRiD window is 78 columns (gridlink's pty then too): gridfox lays the
    page out again for them, the status line's All/Top/Bot inside them, and
    80 again full screen.  At 80 in a window, their last two were cut off."""
    r = Run(U + 'long')
    try:
        def at(rows, cols):
            r.app.resize((rows, cols)); r.scr.resize(rows, cols); r.scr.reset(); r.app.draw(full=True); r.pump()
        r.app.model = {'blocks': [{'k': 'p', 'r': [['word ' * 40, 0, -1]]}], 'acts': []}
        r.app._relayout(top=0); r.pump()
        assert max(len(l) for l in r.app.doc.text) > 78, r.app.doc.text      # (80 wide: a line past 78)
        at(19, 78)
        assert r.app.ncols == 78 and r.app.nrows == 19, (r.app.ncols, r.app.nrows)
        assert max(len(l) for l in r.app.doc.text) <= 78, r.app.doc.text
        rows, _ = r.app.rows()
        assert all(len(t) == 78 for t, _ in rows) and rows[18][0].rstrip().endswith('All'), rows
        assert r.text()[18].rstrip().endswith('All'), r.text()
        at(24, 80)
        assert r.app.ncols == 80 and max(len(l) for l in r.app.doc.text) > 78, r.app.doc.text
        at(19, 20)                                              # (narrower than any window: 40 at least)
        assert r.app.ncols == 40, r.app.ncols
    finally:
        r.close()


def test_app_rows_paths():
    """At 19 rows, each place that counts the page's rows counts 17, not 22:
    a click on the status line, the typing line's row, F's numbers, Tab
    from a scrolled place (on the screen, else the next below), the
    percent and Bot, Find near the end, Back to a place at the end, the
    choices' place; at 4 rows, Tab down keeps the link in view."""
    r = Run(U + 'index')
    try:
        def at(rows):
            r.app.resize(rows); r.scr.resize(rows, 80); r.scr.reset(); r.app.draw(full=True); r.pump()
        at(19)
        d = r.app.doc
        lines = sorted(set(w[0] for w in d.where.values()))
        # a link on doc line top+17 (the status row at 19 rows; a page row at 22): a click there does nothing
        ln = [l for l in lines if l >= 17][0]
        r.app.top = ln - 17; r.app.sel = -1; r.app.draw(); r.pump()
        col = d.act[ln].index(next(a for a in d.act[ln] if a >= 0))
        r.click(col, 18)
        assert r.app.url == U + 'index' and r.app.sel == -1, (r.app.url, r.app.sel)
        r.app.top = [t for t in range(len(d)) if d.acts_in(t, 17) and set(d.acts_in(t, 17)) != set(d.acts_in(t, 22))][0]
        r.keys('f')                                             # F: only the links in the 17 rows
        assert r.app.hints and set(r.app.hints.values()) == set(d.acts_in(r.app.top, 17)), (r.app.top, r.app.hints)
        r.keys('esc')
        # Tab with the selected link just under the 17 rows (in view at 22): the first one on the screen
        off = [a for a in d.acts_in(r.app.top, 22) if a not in d.acts_in(r.app.top, 17)]
        r.app.sel = off[0]; top = r.app.top
        r.keys('tab')
        assert r.app.sel == d.acts_in(top, 17)[0], (r.app.sel, d.acts_in(top, 17))
        # Tab with nothing selected from a place whose 17 rows hold no link and the next 5 do:
        # the next link below, scrolled into view
        gaps = [l for l in lines if l >= 17 and not any(l - 17 <= m < l for m in lines)]
        assert gaps, lines
        r.app.top = gaps[0] - 17; r.app.sel = -1
        r.keys('tab')
        w = d.where[r.app.sel][0]
        assert r.app.top <= w < r.app.top + 17, (r.app.sel, w, r.app.top)
        # Tab from a place with links on its 17 rows: the first of them
        r.app.top = 0; r.app.sel = -1
        r.keys('tab')
        assert r.app.sel == d.acts_in(0, 17)[0], r.app.sel
        r.keys('/')                                             # the typing line's row: a click there keeps it
        r.click(3, 18)
        assert r.app.line is not None, 'the typing line closed'
        r.keys('esc')
        sel = [i for i, a in enumerate(r.app.acts()) if a['t'] == 'select'][0]
        r.app.select(sel); r.keys('enter')
        r0, c0, h, w, first = r.app._menu_box()
        assert h == min(len(r.app.menu[1]), 15) and r0 == 1 + max(0, (17 - h - 2) // 2), (r0, h)
        r.keys('esc')
        r.app.go(U + 'long'); r.pump()
        d = r.app.doc; n = len(d)
        r.app.top = n - 20; r.app.draw(); r.pump()             # 3 rows short of the end: a percent, not Bot
        assert r.text()[18].endswith(' %d%%' % (100 * (n - 20 + 17) // n)), (n, r.text()[18])
        r.keys('home', '/', *'The end of the long page', 'enter')   # Find near the end: the last 17 rows
        f = d.find('The end of the long page', 0)
        assert r.app.top == min(f - 2, n - 17), (r.app.top, f, n)
        r.keys('end')
        assert r.app.top == n - 17
        r.keys('left'); r.keys('right')                         # Back, Forward: the place at the end kept
        assert r.app.url == U + 'long' and r.app.top == n - 17, (r.app.url, r.app.top)
        r.app.go(U + 'anchors'); r.pump()                       # #end, the page's last lines: the last 17
        d = r.app.doc; n = len(d)
        end = [i for i, a in enumerate(r.app.acts()) if a.get('h', '').endswith('#end')][0]
        r.app.select(end); r.keys('enter')
        assert r.app.url.endswith('#end') and r.app.top == min(d.anchors['end'], n - 17), (r.app.top, d.anchors, n)
        at(4)
        r.app.go(U + 'index'); r.pump()
        r.app.top = 0; r.app.sel = -1; r.app.draw(); r.pump()
        acts = sorted(r.app.doc.where, key=lambda a: r.app.doc.where[a])
        for _ in range(len(acts) - 1):                          # Tab down at 2 page rows: always in view
            r.keys('tab')
            w = r.app.doc.where[r.app.sel][0]
            assert r.app.top <= w < r.app.top + 2, (r.app.sel, w, r.app.top)
        at(3)                                                   # (an xterm's 3 rows: a page row)
        sel = [i for i, a in enumerate(r.app.acts()) if a['t'] == 'select'][0]
        v = r.app.acts()[sel].get('v')
        r.app.select(sel); r.keys('enter', 'down')              # (another choice lit: one a click would take)
        r.click(40, 2)                                          # on the status line, under the cut box: no choice
        assert r.app.menu is None and r.app.acts()[sel].get('v') == v, (r.app.menu, r.app.acts()[sel].get('v'), v)
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


# ---- the mouse (CLAUDE /W clicks) ---------------------------------------------
def test_mouse_reports_and_clicks():
    from gridfox.app import Keys
    k = Keys()
    assert k.feed(b'\x1b[<0;12;5M\x1b[<0;12;5mx\x1b[<2;1;1M\x1b[<64;3;3M', 0) == ['click:11:4', 'x']
    # gridlink's word (OSC 5150) is one event, in pieces too; CODE-] is still Meta-]
    assert k.feed(b'a\x1b]5150;sho', 0) == ['a'] and k.feed(b'wn\x07b', 0.001) == ['osc:5150;shown', 'b']
    assert k.feed(b'\x1b]x', 0) == ['meta-]', 'x']
    r = Run(U + 'index')
    try:
        app = r.app
        out = io.BytesIO(); app.out = out; app.draw(full=True)
        assert b'\x1b[?1000h\x1b[?1006h' in out.getvalue()                  # reporting asked for
        app.out = r.out; app.shown = [None] * 24
        row, col = [(ln - app.top + 1, c) for ln, t in enumerate(app.doc.text) for c in [t.find('Long page')]
                    if c >= 0][0]
        r.click(col + 2, row)                                # on "Long page"
        assert app.url == U + 'long' and r.has('Paragraph 1 of the long page.'), (app.url, r.text())
        r.click(5, 0)                                                    # the address: Go
        assert r.text()[23].startswith('Go:'), r.text()[23]
        r.click(40, 10)                                                  # elsewhere: Go closed
        assert app.line is None and not r.text()[23].startswith('Go:')
        r.keys('left')
        sel = [i for i, a in enumerate(app.acts()) if a['t'] == 'select'][0]
        app.select(sel); r.keys('enter')                                       # the list's choices
        r0, c0, h, w, first = app._menu_box()
        r.click(c0 + 3, r0 + 1 + 2)                          # the third: Ohms
        assert app.menu is None and r.has('[Ohms \u25bc]'), r.text()
        r.click(0, 23)                                              # the status line: nothing
        assert app.url == U + 'index'
    finally:
        r.close()


# ---- the picture view (V) -------------------------------------------------------
def line_y(f, text):
    """The y of the stand-in's line holding text (its layout: 16 pixels a line)."""
    r = f._node({'op': 'lines'})
    i = [k for k, (t, _) in enumerate(r['lines']) if text in t][0]
    return i * 16 - r['y'] + 8


def test_picture_view():
    import tempfile
    r = Run(U + 'index')
    try:
        app, f = r.app, r.f
        d = tempfile.mkdtemp(prefix='gridfox-view-'); app.view_path = os.path.join(d, 'view.png')
        app.key('v')                                              # not without a GRiD that can show it
        assert not app.picture and 'CLAUDE.COM 1.2' in app.status, app.status
        app.pictures = True
        out = io.BytesIO(); app.out = out
        n0 = f.shots
        app.key('v')
        assert app.picture and app.pic_up and f.shots == n0 + 1
        o = out.getvalue()
        assert b'\x1b[?1016h' in o and (b'\x1b]5150;show;;%s\x07' % app.view_path.encode()) in o, o[-200:]
        assert open(app.view_path, 'rb').read()[:8] == b'\x89PNG\r\n\x1a\n'
        assert f.window == (650, 392) and app.pic_size == (640, 384), (f.window, app.pic_size)   # the viewport 640 x 384
        assert b'(Esc: text)' in o                                        # the band says how to leave
        # the same picture again: not sent again
        out.seek(0); out.truncate(); app._shoot()
        assert b'5150' not in out.getvalue()
        # a click at a pixel: a real click there (on "Long page")
        app.key('click:%d:%d' % (30, line_y(f, 'Long page')))
        assert f.points and f.points[-1][2] == 'a', f.points
        assert app.url == U + 'long', app.url
        # scrolling: whole rows of 16 lines
        app.key('pgdn'); assert app.b.scroll(0) == 352
        app.key('down'); assert app.b.scroll(0) == 400
        app.key('home'); assert app.b.scroll(0) == 0
        app.key('end'); assert app.b.scroll(0) > 400
        # typing goes to the page: the sign-in form's field
        app.key('ctrl-b'); app.go(U + 'login')
        app.key('click:%d:%d' % (30, line_y(f, '[User name]')))
        for c in 'abc': app.key(c)
        app.key('bksp')
        assert f.keys[-4:] == ['a', 'b', 'c', '\ue003'], f.keys
        assert f._node({'op': 'exec', 'script': 'return document.querySelector("[name=user]").value;',
                        'args': []})['value'] == 'ab'
        # the address: the text view's Go line over the picture, then the picture again
        out.seek(0); out.truncate()
        app.key('f6')
        assert app.line is not None and not app.pic_up and b'5150;hide' in out.getvalue()
        app.key('esc'); app._sync_view()
        assert app.line is None and app.pic_up
        # light or dark: the other way
        out.seek(0); out.truncate(); app.key('ctrl-i')
        assert b'5150;show;invert;' in out.getvalue(), out.getvalue()
        # Esc: the text view again, as it was
        out.seek(0); out.truncate()
        app.key('esc')
        o = out.getvalue()
        assert not app.picture and b'5150;hide' in o and b'\x1b[?1016l' in o
        assert f.window == (1034, 776), f.window
        app.out = r.out; app.shown = [None] * 24; app.draw(); r.pump()
        assert r.has('User') and r.text()[0].strip() == U + 'login', r.text()
        # no picture of the help page
        app.go('about:gridfox'); app.key('v')
        assert not app.picture and 'G to go' in app.status
        # the address bar clicked with the Go line open, in the picture view: no stray G typed into the page
        app.go(U + 'login'); app.key('v'); n = len(f.keys)
        app.key('f6'); app.key('click:5:0')
        assert app.line is not None and len(f.keys) == n, (app.line, f.keys[n:])
    finally:
        r.close()


def test_picture_view_keeps_up_with_a_moving_page():
    """A page that changes by itself (a video): looks every FRAME_SHOT, not
    every IDLE_SHOT, as frames gridlink shows whole; a still page: the idle pace."""
    import tempfile
    from gridfox.app import FRAME_SHOT, IDLE_SHOT
    r = Run(U + 'anim')
    try:
        app = r.app; app.pictures = True
        app.view_path = os.path.join(tempfile.mkdtemp(prefix='gridfox-view-'), 'view.png')
        out = io.BytesIO(); app.out = out
        app.key('v'); app.shots = []
        time.sleep(0.25); app._shoot(True)
        assert app.moving
        assert b'5150;show;frame;' in out.getvalue(), out.getvalue()[-120:]
        # the next look waits for gridlink's word that the GRiD has the last whole
        from gridfox.app import SHOWN_WAIT
        assert app.awaiting and abs(app._next_shot() - app.sent_t - SHOWN_WAIT) < 1e-6
        for k in Keys().feed(b'\x1b]5150;shown\x07', 0): app.key(k)
        assert not app.awaiting and abs(app._next_shot() - app.shot_t - FRAME_SHOT) < 1e-6
        app.go(U + 'index'); app.shots = []
        app._shoot(True); app._shoot(True)                       # (the second: nothing changed)
        assert not app.moving and abs(app._next_shot() - app.shot_t - IDLE_SHOT) < 1e-6
    finally:
        r.close()


def test_picture_view_end_to_end():
    from gridsim import TermHarness
    from gridlink import picture as PIC
    f = FakeFirefox()
    try:
        cmd = '%s -m gridfox --port %d %sindex' % (sys.executable, f.port, U)
        h = TermHarness(app='web', web_command=cmd)
        try:
            assert h.wait_text('Tektronix 7854 notes', wall=20), (h.log, h.grid.screen_text())
            assert h.settle()
            t = h.router.web
            b0 = h.grid.stats['rx_bytes']
            h.grid.press(0x76, 0x2F)                                            # V
            assert h.run_until(lambda: t.pic is not None and bytes(h.grid.pix) == t.pic['bits'], 20), h.log[-5:]
            assert not any(bytes(r).strip() for r in h.grid.cells)              # the text is gone
            bits = t.pic['bits']
            lit = sum(bin(b).count('1') for b in bits) / (PIC.SIZE * 8)
            assert lit < 0.2, lit                                               # a white page shown dark
            assert h.run_until(lambda: h.grid.title.endswith(b'(Esc: text)'), 5), h.grid.title
            print('     the page as a picture: %d bytes to the GRiD' % (h.grid.stats['rx_bytes'] - b0))
            # a click at a pixel: gridlink reports it in pixels (?1016), gridfox clicks there
            h.grid.click(30, line_y(f, 'Long page'))
            assert h.run_until(lambda: b'A long page' in h.grid.title, 15), h.grid.title
            assert h.run_until(lambda: t.pic is not None and bytes(h.grid.pix) == t.pic['bits'], 20)
            # PgDn: a scroll op and a strip, not the whole picture again
            assert h.settle()
            b1 = h.grid.stats['rx_bytes']; sc0 = h.grid.stats['cells_frames']
            h.grid.press(0, 0x51)
            assert h.run_until(lambda: f.calls.count('WebDriver:TakeScreenshot') and
                               bytes(h.grid.pix) == t.pic['bits'] and t.penc.shown == t.pic['bits'], 20)
            assert h.settle()
            b2 = h.grid.stats['rx_bytes']
            # Down: 3 rows; the GRiD moves what it has (a scroll op) and gets the new rows
            n = f.calls.count('WebDriver:TakeScreenshot')
            h.grid.press(0, 0x50)
            assert h.run_until(lambda: f.calls.count('WebDriver:TakeScreenshot') > n and
                               bytes(h.grid.pix) == t.pic['bits'] and t.penc.shown == t.pic['bits'], 20)
            assert h.settle()
            b3 = h.grid.stats['rx_bytes']
            print('     a screen down: %d bytes; 3 rows down: %d' % (b2 - b1, b3 - b2))
            assert b3 - b2 < (b2 - b1) / 2, (b2 - b1, b3 - b2)
            # a page that changes by itself: whole frames, one after another, at the link's pace
            h.grid.press(0x1B, 0x01)
            assert h.wait_text('Paragraph 1 of the long page.', wall=10)
            for ch in 'g': h.grid.press(ord(ch), 0x22)
            assert h.wait_text('Go:', wall=5)
            for _ in range(80): h.grid.press(0x08, 0x0E)
            for ch in U + 'anim': h.grid.press(ord(ch), 0)
            h.grid.press(0x0D, 0x1C)
            assert h.wait_text('Frame', wall=10), h.grid.screen_text()
            h.grid.press(0x76, 0x2F)
            assert h.run_until(lambda: t.pic is not None and bytes(h.grid.pix) == t.pic['bits'], 20)
            seen = set(); n0 = f.shots
            def whole():
                if t.pic is not None and bytes(h.grid.pix) == t.pic['bits']: seen.add(bytes(h.grid.pix))
            h.grid.on_cells = whole
            t0 = time.time()
            h.run_until(lambda: time.time() - t0 > 3.0, wall=4)
            h.grid.on_cells = None
            print('     a moving page: %d whole frames in 3 s (%d screenshots)' % (len(seen), f.shots - n0))
            assert len(seen) >= 6, len(seen)                        # (at the idle pace: one or two)
            assert f.shots - n0 <= len(seen) + 3, (f.shots - n0, len(seen))   # (a look a frame: none wasted)
            h.grid.press(0x1B, 0x01)
            assert h.wait_text('Frame', wall=10)
            for ch in 'g': h.grid.press(ord(ch), 0x22)
            assert h.wait_text('Go:', wall=5)
            for _ in range(80): h.grid.press(0x08, 0x0E)
            for ch in U + 'long': h.grid.press(ord(ch), 0)
            h.grid.press(0x0D, 0x1C)
            h.grid.press(0x76, 0x2F)
            assert h.run_until(lambda: t.pic is not None and bytes(h.grid.pix) == t.pic['bits'], 20)
            # Esc: the text again, the long page
            h.grid.press(0x1B, 0x01)
            assert h.wait_text('Paragraph 1 of the long page.', wall=10), h.grid.screen_text()
            assert t.pic is None
            assert h.grid.stats['fail'] == 0, h.grid.stats
            errs = [l for l in h.log if 'Traceback' in str(l) or 'picture from' in str(l)]
            assert not errs, errs
        finally:
            h.close()
    finally:
        f.close()


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
            # a GRiD window 19 rows tall (T5e's EVENT 08h): gridlink resizes the pty, gridfox
            # (SIGWINCH) lays out for it: the status line on row 18, rows 19-23 blank
            status = lambda r: 'test.local/long' in h.grid.screen_text()[r] and \
                h.grid.screen_text()[r].rstrip().endswith(('All', 'Top'))     # (the link selected: its address)
            assert status(23), h.grid.screen_text()
            # (pyte drops a shrunk screen's top rows, so the old status line is on the last row at
            # once: gridfox's own layout is the address back on row 0, the status under the page)
            # (and in a window, 78 columns: the window shows 78 of the GRiD's 80, so nothing past them)
            laid = lambda n: h.grid.screen_text()[0].strip() == U + 'index' and status(n - 1) and \
                all(not l.strip() for l in h.grid.screen_text()[n:24]) and \
                (n == 24 or all(len(l.rstrip()) <= 78 for l in h.grid.screen_text()))
            took = []
            for n in (19, 12, 19, 12, 19):
                t0 = time.time()
                h.router.web.set_rows(n)
                assert h.run_until(lambda: laid(n), wall=5), (n, h.grid.screen_text())
                took.append(time.time() - t0)
                assert h.settle() and laid(n), (n, h.grid.screen_text())
            print('     19 and 12 rows: laid out again in %s ms' % ', '.join('%.0f' % (t * 1000) for t in took))
            assert max(took) < 0.2, took                                        # (the wakeup fd: not select's 0.5 s)
            assert h.router.web.cols == 78, h.router.web.cols
            h.router.web.set_rows(24)
            assert h.run_until(lambda: status(23) and len(h.grid.screen_text()[23].rstrip()) == 79, wall=5), \
                h.grid.screen_text()
            assert h.router.web.cols == 80, h.router.web.cols
            assert h.settle()
            # a click from the GRiD (EVENT 05h): on "Sign in", a link on the first page row
            row = [i for i, l in enumerate(h.grid.screen_text()) if 'Sign in' in l][0]
            col = h.grid.screen_text()[row].index('Sign in') + 1
            h.grid.txq.append([glp.G_EVENT, bytes([glp.EV_CLICK, col, row]), 0])
            assert h.wait_text('Password', wall=10), h.grid.screen_text()          # the sign-in page
            assert h.grid.screen_text()[0].strip() == U + 'login', h.grid.screen_text()[0]
            assert h.settle()
            # gridfox started in a pty that is 19 rows already (Ctrl-Q in a window, then Return):
            # no SIGWINCH comes, so its first read of the rows lays it out
            h.router.web.set_rows(19)
            assert h.run_until(lambda: h.grid.screen_text()[0].strip() == U + 'login', wall=5)
            assert h.settle()
            h.grid.press(0x11, 0x10)                                            # Ctrl-Q: gridfox ends
            assert h.wait_text('Press Return', wall=15), h.grid.screen_text()
            assert h.settle()
            h.grid.press(0x0D, 0x1C)                                            # Return: started again
            assert h.run_until(lambda: h.grid.screen_text()[0].strip() == U + 'index'
                               and h.grid.screen_text()[18].rstrip().endswith(('All', 'Top'))
                               and not any(l.strip() for l in h.grid.screen_text()[19:24]), wall=20), \
                h.grid.screen_text()
            assert h.settle()
            # (a 24-row layout in the 19-row pty looks the same: its rows past 18 land on row 18 and
            # the status line last.  PgDn tells them apart: 15 rows, so row 16 comes up to row 1)
            row16 = h.grid.screen_text()[16]
            assert row16.strip(), h.grid.screen_text()
            h.grid.press(0, 0x51)                                               # PgDn
            assert h.run_until(lambda: h.grid.screen_text()[1] == row16, wall=10), (row16, h.grid.screen_text())
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


def test_video_find_and_page():
    """Y's half on the Pi: which addresses are videos, yt-dlp asked (and asked
    again with Firefox's cookies when YouTube wants a sign-in), the page made."""
    import json, subprocess, tempfile, types
    from gridfox import video as V
    for u in ('https://www.youtube.com/watch?v=Z2UWOeBcsJI', 'https://m.youtube.com/watch?v=Z2UWOeBcsJI&t=4',
              'https://youtu.be/Z2UWOeBcsJI', 'https://www.youtube.com/shorts/abcdefGHIJK'):
        assert V.is_video(u), u
    for u in ('https://www.youtube.com/', 'https://www.youtube.com/results?search_query=2001',
              'https://notyoutube.com/watch?v=Z2UWOeBcsJI', 'about:gridfox', None):
        assert not V.is_video(u), u
    calls = []
    def run(answers):
        def r(a, **kw):
            calls.append(a); code, out, err = answers.pop(0)
            return types.SimpleNamespace(returncode=code, stdout=out, stderr=err)
        return r
    good = json.dumps({'title': '2001: A Space Odyssey <trailer>', 'url': 'https://rr1.googlevideo.com/v?a=1&b=2',
                       'http_headers': {'User-Agent': 'com.google.android.youtube/1'}})
    assert V.find('U', run=run([(0, good + '\n', '')]), cmd=['yt-dlp']) == \
        ('https://rr1.googlevideo.com/v?a=1&b=2', '2001: A Space Odyssey <trailer>',
         {'User-Agent': 'com.google.android.youtube/1'})
    assert '--cookies-from-browser' not in calls[-1] and calls[-1][-1] == 'U'
    prof = tempfile.mkdtemp(prefix='gridfox-profile-')
    calls.clear()
    bot = (1, '', "ERROR: [youtube] Z2UWOeBcsJI: Sign in to confirm you're not a bot. Use --cookies")
    assert V.find('U', profile=prof, run=run([bot, (0, good, '')]), cmd=['yt-dlp'])[1].startswith('2001')
    assert len(calls) == 2 and calls[1][1:3] == ['--cookies-from-browser', 'firefox:' + prof], calls[1]
    calls.clear()
    try: V.find('U', profile=prof, run=run([(1, '', 'ERROR: [youtube] Z2UWOeBcsJI: Video unavailable')]), cmd=['yt-dlp'])
    except V.NotFound as e: assert str(e) == 'Video unavailable', e
    else: raise AssertionError('no NotFound')
    assert len(calls) == 1                                       # (cookies wouldn't help that)
    calls.clear()
    nojs = (1, '', 'WARNING: [youtube] No supported JavaScript runtime could be found. Only deno is enabled\n'
                   'ERROR: [youtube] e-QFj59PON4: Requested format is not available.')
    try: V.find('U', run=run([nojs]), cmd=['yt-dlp'])
    except V.NotFound as e: assert 'needs deno' in str(e), e
    else: raise AssertionError('no NotFound')
    def slow(a, **kw): raise subprocess.TimeoutExpired(a, 1)
    try: V.find('U', run=slow, cmd=['yt-dlp'])
    except V.NotFound as e: assert 'too long' in str(e)
    url = V.write_page('https://rr1.googlevideo.com/v?a=1&b="2"', 'A <b>title</b>', prof)
    assert url.startswith('file://') and url.endswith('/video.html')
    h = open(os.path.join(prof, 'video.html'), encoding='utf-8').read()
    assert 'src="https://rr1.googlevideo.com/v?a=1&amp;b=&quot;2&quot;"' in h and 'A &lt;b&gt;title' in h
    assert '<b>title' not in h


def test_video_relay():
    """The relay: YouTube's file fetched with yt-dlp's headers (a stand-in
    server that refuses any other User-Agent and any piece over CHUNK, as
    YouTube does), whole or from where Firefox seeks to."""
    import threading, urllib.error, urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from gridfox import video as V
    data = bytes(range(256)) * 20                                   # 5120 bytes
    asks = []
    class Up(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(h, *a): pass
        def do_GET(h):
            a, b = (int(x) for x in h.headers['Range'][6:].split('-'))
            asks.append((a, b))
            if h.headers.get('User-Agent') != 'yt-app' or b - a + 1 > 1000:
                h.send_response(403); h.send_header('Content-Length', '0'); h.end_headers(); return
            b = min(b, len(data) - 1); body = data[a:b + 1]
            h.send_response(206); h.send_header('Content-Type', 'video/mp4')
            h.send_header('Content-Range', 'bytes %d-%d/%d' % (a, b, len(data)))
            h.send_header('Content-Length', str(len(body))); h.end_headers(); h.wfile.write(body)
    up = ThreadingHTTPServer(('127.0.0.1', 0), Up); up.daemon_threads = True
    threading.Thread(target=up.serve_forever, daemon=True).start()
    chunk = V.CHUNK; V.CHUNK = 1000
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    relay = V.Relay(opener=direct.open)
    try:
        src = 'http://127.0.0.1:%d/v' % up.server_address[1]
        at = relay.add(src, {'User-Agent': 'yt-app'})
        assert at.startswith('http://127.0.0.1:%d/v/' % relay.port) and at.endswith('.mp4')
        get = lambda rng: direct.open(urllib.request.Request(at, headers={'Range': rng,
                                      'User-Agent': 'Mozilla/5.0 Firefox/140.0'}), timeout=10)
        r = get('bytes=0-')                                         # Firefox's first ask: all of it
        assert r.status == 206 and r.headers['Content-Range'] == 'bytes 0-5119/5120', dict(r.headers)
        assert r.read() == data
        assert all(b - a + 1 <= 1000 for a, b in asks) and len(asks) == 6, asks
        r = get('bytes=3000-3499')                                  # a seek
        assert r.headers['Content-Range'] == 'bytes 3000-3499/5120' and r.read() == data[3000:3500]
        refused = relay.add(src, {'User-Agent': 'Mozilla/5.0 Firefox/140.0'})   # (Firefox's own: 403)
        try: direct.open(urllib.request.Request(refused, headers={'Range': 'bytes=0-'}), timeout=10)
        except urllib.error.HTTPError as e: assert e.code == 403
        else: raise AssertionError('no 403')
        try: direct.open('http://127.0.0.1:%d/v/0123456789abcdef.mp4' % relay.port, timeout=10)
        except urllib.error.HTTPError as e: assert e.code == 404
        else: raise AssertionError('no 404')
    finally:
        V.CHUNK = chunk; relay.close(); up.shutdown(); up.server_close()


def test_app_plain_video():
    """Y in gridfox: off a video's page, a word why not; on one, the page of
    its own opened, the picture view up, and a person's click to start it."""
    import tempfile
    from gridfox import video as V
    r = Run(U + 'index')
    real = V.is_video, V.find
    try:
        app = r.app; app.pictures = True
        app.view_path = os.path.join(tempfile.mkdtemp(prefix='gridfox-view-'), 'view.png')
        r.keys('y')
        assert r.has('open the video') and not app.picture
        V.is_video = lambda u: True
        V.find = lambda u, profile=None: (_ for _ in ()).throw(V.NotFound('yt-dlp is not installed on the Pi'))
        r.keys('y')
        assert r.has('Y: yt-dlp is not installed') and not app.picture
        app.picture_view(True); assert app.picture
        seen = []
        def slow(u, profile=None):
            seen.append(app.title_sent)          # what the GRiD's band says while yt-dlp works
            raise V.NotFound('Video unavailable')
        V.find = slow
        app.key('ctrl-y'); r.pump()
        assert seen and seen[0].startswith('Finding the video'), seen
        assert not app.picture and r.has('Y: Video unavailable')  # (back to the text, to say why)
        V.find = lambda u, profile=None: ('https://rr1.googlevideo.com/v', '2001 trailer', {'User-Agent': 'app'})
        n = len(r.f.points)
        r.keys('y')
        assert app.url.startswith('file://') and app.url.endswith('/video.html'), app.url
        page = open(os.path.join(os.path.dirname(app.view_path), 'video.html'), encoding='utf-8').read()
        assert 'src="http://127.0.0.1:' in page and 'googlevideo' not in page     # (through the relay)
        assert app.picture and len(r.f.points) > n
        assert 'Playing: 2001 trailer' in app.status
        assert os.path.exists(os.path.join(os.path.dirname(app.view_path), 'video.html'))
    finally:
        V.is_video, V.find = real
        r.close()


NO_BROWSER = ('test_wrap_and_clean', 'test_layout_kinds', 'test_keys_and_line', 'test_keys_timing',
              'test_firefox_quits_cleanly', 'test_web_exit_banner',
              'test_video_find_and_page', 'test_video_relay')       # (these run without the stand-in)

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
