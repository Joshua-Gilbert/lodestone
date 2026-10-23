"""gridfox's screen and keys: an 80x24 terminal program.

It runs in Term's pty on the Pi (CLAUDE /W on the GRiD), or in any xterm.
Row 0 is the address, rows 1-22 the page, row 23 the status line.  Every
change is drawn as whole rows inside synchronised output (?2026), so Term
sends the GRiD one frame for it, and only the rows that changed.

V flips to the picture view: Firefox's own pixels, 640 x 384, through
Term's pictures (gridlink's OSC 5150: a PNG file in this folder, which
gridlink dithers and sends).  Clicks come back in pixels (?1016) and go to
the page as a person's; so do the keys, but for a few of gridfox's own.
"""
import hashlib, os, select, signal, struct, sys, termios, time, tty, urllib.parse
from . import page as P, video as V
from .marionette import MarionetteError
ERRS = (MarionetteError, RuntimeError, OSError, ValueError)

ROWS, COLS = 24, 80
URL_EVERY = 1.0                     # seconds between looks at the address when idle
TOP, BODY = 1, 22                   # page rows 1..22
PIC_W, PIC_H = 640, 384             # the picture view: the GRiD's rows 0-23
TEXT_W, TEXT_H = 1024, 768          # Firefox's window for the text view
SHOTS = (0.0, 0.5, 1.5, 4.0)        # after an action: pictures then (s), as the page settles
IDLE_SHOT = 2.0                     # and at most this often while idle, when it changed
FRAME_SHOT = 0.25                   # while the page keeps changing by itself (a video, an animation)
SHOWN_WAIT = 3.0                    # then the next look waits for the GRiD to have the last whole, or this
LINE_PX, PAGE_PX = 48, 352          # the picture view's scrolling (whole rows of 16 lines)
VIEW_FILE = 'view.png'
BAND = 48                           # columns of the GRiD's band the title gets (CLAUDE's keys take the rest)
SEARCH = 'https://html.duckduckgo.com/html/?q=%s'
HOME = 'about:gridfox'

HELP = [
    ('h1', 'gridfox: Firefox on the GRiD'),
    ('p', 'Firefox runs on the Raspberry Pi and does all the work; the GRiD shows each page as text.'),
    ('h2', 'Moving around'),
    ('li', 'Up/Down a line, PgUp/PgDn or Space a screen, Home/End top and bottom'),
    ('li', 'Tab and Shift-Tab: next and previous link, button or field'),
    ('li', 'Return: follow the link, press the button, fill in the field'),
    ('li', 'The mouse: click a link, button or field to use it; click the address to go somewhere else'),
    ('li', 'F then a number: follow link number n on the screen (hints)'),
    ('li', 'Left or Backspace: back.  Right: forward.  R: reload.  Period: read the page again'),
    ('li', 'Y on a YouTube video: play it without YouTube\'s player (no bot check, no ads; yt-dlp on the Pi)'),
    ('h2', 'Going somewhere'),
    ('li', 'G (or O, or F6): type an address, or words to search for'),
    ('li', 'S: search.  /: find on the page, N: find the next one'),
    ('li', 'H or ?: this help.  Esc cancels what you are typing.  Ctrl-Q: close gridfox'),
    ('h2', 'The picture view'),
    ('li', 'V: the page as Firefox draws it, dithered (slower than text: the GRiD gets pixels). Esc: back'),
    ('li', 'There, a click is a real click anywhere on the page, and typing goes to the page'),
    ('li', 'Up/Down and PgUp/PgDn scroll, Home/End top and bottom; Ctrl-B back, Ctrl-F forward, '
           'Ctrl-R reload, F6 or Ctrl-L an address, Ctrl-I light or dark, Ctrl-Y the video on its own'),
    ('li', 'In a video played with Y: a click or Space plays and pauses, Left and Right go 10 s; Ctrl-B: back to YouTube'),
    ('h2', 'Forms'),
    ('p', 'Return on a field asks for its text at the bottom; Return there fills it in and goes on to the '
          'form\'s next field, or sends the form after the last one.  Return on a check box ticks it; on a '
          'list, pick from the choices.'),
]


def help_model():
    return {'url': HOME, 'title': 'gridfox help', 'acts': [],
            'blocks': [{'k': k, 'd': 1, 'm': -1 if k == 'li' else 0, 'r': [[t, 0, -1]]} for k, t in HELP]}


def looks_like_url(t):
    t = t.strip()
    if not t or ' ' in t: return False
    if '://' in t or t.startswith(('about:', 'file:', 'data:')): return True
    host = t.split('/')[0]
    return '.' in host or host.startswith('localhost') or host.replace('.', '').replace(':', '').isdigit()


def to_url(text, search=SEARCH):
    t = text.strip()
    if looks_like_url(t):
        return t if ('://' in t or t.startswith(('about:', 'file:', 'data:'))) else 'https://' + t
    return search % urllib.parse.quote_plus(t)


class Keys:
    """Bytes from the pty -> key names ('up', 'pgdn', 'esc', 'meta-g', 'x', ...)."""
    SEQ = {'[A': 'up', '[B': 'down', '[C': 'right', '[D': 'left', '[H': 'home', '[F': 'end',
           'OA': 'up', 'OB': 'down', 'OC': 'right', 'OD': 'left', 'OH': 'home', 'OF': 'end',
           '[5~': 'pgup', '[6~': 'pgdn', '[2~': 'ins', '[3~': 'del', '[1~': 'home', '[4~': 'end',
           '[7~': 'home', '[8~': 'end', '[Z': 'btab', '[17~': 'f6', 'OP': 'f1', '[11~': 'f1'}

    def __init__(s): s.buf = b''; s.esc_t = None

    def feed(s, data, now=None):
        s.buf += data
        return s.take(now if now is not None else time.time())

    def take(s, now, lone_esc=0.015, stale=0.15):
        # Term writes a lone Esc on its own and waits 30 ms before the next
        # key, so 15 ms of nothing after an Esc means Esc; a sequence left
        # unfinished for longer than `stale` was never going to finish.
        out = []
        b = s.buf
        while b:
            c = b[0]
            if c == 0x1B:
                n = b[1] if len(b) > 1 else None
                done = None
                if n == 0x5D and (b[2:7] == b'5150;' or (len(b) < 7 and b'5150;'.startswith(b[2:]))):
                    # gridlink's OSC 5150 (`shown`: the GRiD has the last picture whole), not CODE-]
                    j = b.find(b'\x07', 2)
                    if j < 0:
                        if s.esc_t is None: s.esc_t = now
                        if now - s.esc_t < stale or len(b) < 64: break
                        b = b[2:]; s.esc_t = None; continue        # (never ends: drop it)
                    s.esc_t = None
                    out.append('osc:' + b[2:j].decode('latin1')); b = b[j + 1:]
                    continue
                if n in (0x5B, 0x4F):                       # CSI / SS3
                    j = 2
                    while j < len(b) and (0x30 <= b[j] <= 0x3F): j += 1
                    while j < len(b) and (0x20 <= b[j] <= 0x2F): j += 1
                    if j < len(b): done = j
                if n is None or (n in (0x5B, 0x4F) and done is None):
                    if s.esc_t is None: s.esc_t = now
                    if now - s.esc_t >= (lone_esc if n is None else stale):
                        out.append('esc'); b = b[1:]; s.esc_t = None
                        continue
                    break
                s.esc_t = None
                if n in (0x5B, 0x4F):
                    j = done
                    seq = b[1:j + 1].decode('latin1')
                    if seq.startswith('[<') and seq[-1] in 'Mm':    # an SGR mouse report (?1006)
                        b = b[j + 1:]
                        k = _click(seq)
                        if k: out.append(k)
                        continue
                    out.append(s.SEQ.get(seq, 'unknown')); b = b[j + 1:]
                elif n == 0x1B: out.append('esc'); b = b[1:]
                elif n == 0x0D: out.append('meta-enter'); b = b[2:]
                else: out.append('meta-' + chr(n).lower()); b = b[2:]
                continue
            if c >= 0x80:                                      # UTF-8: the whole character
                need = 2 if c < 0xE0 else 3 if c < 0xF0 else 4
                if len(b) < need: break
                try: out.append(b[:need].decode('utf-8'))
                except UnicodeDecodeError: pass
                b = b[need:]; continue
            b = b[1:]
            if c == 0x0D or c == 0x0A: out.append('enter')
            elif c == 0x09: out.append('tab')
            elif c in (0x7F, 0x08): out.append('bksp')
            elif c < 0x20: out.append('ctrl-' + chr(c + 0x60))
            else: out.append(chr(c))
        s.buf = b
        return out


class Line:
    """A one-line editor (address bar, find, a form field)."""
    def __init__(s, prompt, text='', secret=False):
        # what the page gave (a field's value, its label) can hold anything:
        # only what the GRiD can show goes on the screen, one cell a character
        s.prompt = P.clean(prompt).replace('\n', ' '); s.text = P.clean(text or '')
        s.pos = len(s.text); s.secret = secret

    def key(s, k):
        if k == 'left': s.pos = max(0, s.pos - 1)
        elif k == 'right': s.pos = min(len(s.text), s.pos + 1)
        elif k in ('home', 'ctrl-a'): s.pos = 0
        elif k in ('end', 'ctrl-e'): s.pos = len(s.text)
        elif k == 'bksp':
            if s.pos: s.text = s.text[:s.pos - 1] + s.text[s.pos:]; s.pos -= 1
        elif k == 'del': s.text = s.text[:s.pos] + s.text[s.pos + 1:]
        elif k == 'ctrl-u': s.text = s.text[s.pos:]; s.pos = 0
        elif k == 'ctrl-k': s.text = s.text[:s.pos]
        elif len(k) == 1 and k.isprintable(): s.text = s.text[:s.pos] + k + s.text[s.pos:]; s.pos += 1
        else: return False
        return True

    def view(s, width):
        """-> (text, cursor column) fitted to width."""
        shown = '*' * len(s.text) if s.secret else s.text.replace('\n', '\u23ce')   # (a textarea's lines: one row)
        room = width - len(s.prompt) - 1
        start = max(0, s.pos - room + 1) if s.pos >= room else 0
        part = shown[start:start + room]
        return s.prompt + part, len(s.prompt) + s.pos - start


class App:
    def __init__(s, browser, out=None, start=None, search=SEARCH, log=None, quit_keys=(), pictures=False,
                 profile=None):
        s.b = browser; s.out = out or sys.stdout.buffer
        s.search = search; s.log = log or (lambda m: None)
        s.model = help_model(); s.doc = P.layout(s.model)
        s.top = 0; s.sel = -1; s.url = HOME
        s.line = None; s.line_do = None          # the editor on row 23 and what Return does with it
        s.hints = None; s.hint_in = ''           # F: {number: act}
        s.menu = None                            # a <select>'s choices: (act, options, index)
        s.status = 'G: go to an address   H: help'; s.busy = ''
        s.find_text = ''; s.shown = [None] * ROWS
        s.rereads = []; s.places = {}            # url -> (top, sel), for Back
        s.title_sent = None; s.start = start
        s.quit = False; s.quit_keys = tuple(quit_keys) + ('ctrl-q',); s.found = -1
        s.lost = None                            # why Firefox can't be reached (gridfox then ends)
        s.before_help = None                     # the page help was opened over
        s.url_t = 0.0                            # when the address was last checked
        # the picture view
        s.pictures = pictures                    # the GRiD can show them (gridlink says so: GRIDLINK_PICTURES)
        s.picture = False                        # V: in it (the text goes on underneath)
        s.pic_up = False                         # the picture shown now (not while typing an address)
        s.pic_hash = None; s.pic_size = (PIC_W, PIC_H)
        s.shots = []; s.shot_t = 0.0             # pictures due, and when the last was taken
        s.moving = False                         # the page changed by itself at the last look: look again soon
        s.frame = False                          # the picture up is one of those (gridlink: whole frames, in turn)
        s.awaiting = False; s.sent_t = 0.0       # sent, and the GRiD not yet said to have it whole (OSC 5150 shown)
        s.pic_inv = None                         # None: light pages dark (gridlink decides); or True/False
        s.view_path = os.path.abspath(VIEW_FILE)
        s.profile = profile                      # Firefox's profile (Y: its cookies, if YouTube asks yt-dlp to sign in)

    # ---- pages ------------------------------------------------------------
    def go(s, url):
        if url == HOME:
            if s.url != HOME: s.before_help = (s.model, s.url, s.top, s.sel)
            s._remember(); s.model = help_model(); s.url = HOME; s._relayout(top=0, sel=-1); return
        s._remember(); s.before_help = None
        s.busy = 'Loading %s' % url; s.draw()
        err = None
        try:
            s.b.open(url)
        except ERRS as e:
            err = 'Could not open it: %s' % _short(e)
        s._loaded(top=0, err=err)

    def _loaded(s, top=None, sel=None, err=None):
        s.busy = 'Reading the page'; s.draw()
        try:
            s.model = s.b.read()
        except ERRS as e:
            s.busy = ''; s.status = err or 'Could not read the page: %s' % _short(e); s.draw(); return
        s.url = s.model.get('url', '') or s.url
        if top is None:                          # Back/Forward: where we were
            top, sel = s.places.get(s.url, (0, -1))
        s.busy = ''; s.status = err or ''
        s._relayout(top=top, sel=sel if sel is not None else -1)
        try: s.b.mark()                          # this document, for telling it from the next
        except ERRS: pass
        if top == 0 and urllib.parse.urldefrag(s.url)[1]: s._to_anchor()   # page.html#section
        # pages that fill in after they load: look again shortly
        now = time.time(); s.rereads = [now + 0.6, now + 2.0, now + 5.0]
        s._shots()

    def _relayout(s, top=None, sel=None):
        s.doc = P.layout(s.model)
        if top is not None: s.top = top
        if sel is not None: s.sel = sel
        s.top = max(0, min(s.top, max(0, len(s.doc) - BODY)))
        if s.sel >= len(s.model.get('acts', [])): s.sel = -1
        s.draw()

    def reread(s):
        """Read the page again; keep the place if anything changed."""
        if s.url == HOME: return
        try:
            m = s.b.read()
        except ERRS:
            return
        new = m.get('url') or s.url
        if new != s.url and not (_page(new) == _page(s.url) or s.b.same_document()):
            s.model = m; s.url = new; s._relayout(top=0, sel=-1); s.b.mark(); return
        moved = new != s.url                     # the same document at another address (#fragment, pushState)
        if moved or m.get('blocks') != s.model.get('blocks') or m.get('acts') != s.model.get('acts'):
            s.model = m; s.url = new; s._relayout()
        if moved and urllib.parse.urldefrag(new)[1]:
            s._to_anchor()

    def _to_anchor(s):
        """Scroll to the address's #fragment, if the page has it."""
        frag = urllib.parse.unquote(urllib.parse.urldefrag(s.url)[1])
        ln = s.doc.anchors.get(frag) if frag else None
        if frag == 'top' and ln is None: ln = 0
        if ln is not None:
            s.top = max(0, min(ln, max(0, len(s.doc) - BODY))); s.draw()

    def _remember(s):
        if s.url: s.places[s.url] = (s.top, s.sel)

    def back(s):
        if s.url == HOME:                        # help is not a page in Firefox's history
            if s.before_help:
                s.model, s.url, top, sel = s.before_help; s.before_help = None
                s._relayout(top=top, sel=sel); s.reread()
            return
        s._remember(); s.busy = 'Back'; s.draw()
        err = None
        try: s.b.back()
        except ERRS as e: err = 'Back: %s' % _short(e)
        s._loaded(err=err)

    def forward(s):
        if s.url == HOME: return
        s._remember(); s.busy = 'Forward'; s.draw()
        err = None
        try: s.b.forward()
        except ERRS as e: err = 'Forward: %s' % _short(e)
        s._loaded(err=err)

    def reload(s):
        if s.url == HOME: return
        s._remember(); s.busy = 'Reloading'; s.draw()
        err = None
        try: s.b.reload()
        except ERRS as e: err = 'Reload: %s' % _short(e)
        top, sel = s.places.get(s.url, (0, -1))
        s._loaded(top, sel, err=err)

    # ---- acts -------------------------------------------------------------
    def acts(s): return s.model.get('acts', [])

    def activate(s, i):
        acts = s.acts()
        if not 0 <= i < len(acts): return
        a = acts[i]; t = a.get('t')
        if s.url == HOME: return
        if t == 'field':
            label = (str(a.get('lb') or a.get('ph') or a.get('name') or 'Text'))[:24]
            s.line = Line(label + ': ', a.get('v', ''), secret=a.get('type') == 'password')
            s.line_do = lambda text, i=i: s.fill(i, text)
            s.draw(); return
        if t == 'select':
            opts = [_fit(str(o), 70) for o in (a.get('opts') or [])] or ['-']
            v = a.get('v', 0); v = v if isinstance(v, int) and 0 <= v < len(opts) else 0
            s.menu = [i, opts, v]; s.draw(); return
        s._do('click', i)

    def fill(s, i, text):
        a = s.acts()[i]
        try:
            s.b.act('set', i, text)
        except ERRS as e:
            s.status = 'Could not fill it in: %s' % _short(e); s.draw(); return
        s.reread()                               # (the page may have answered the typing)
        acts = s.acts()
        # The form is sent from its last field only when nothing else in it
        # is still to be set (check boxes, lists, more fields); otherwise on
        # to the next of them.  Its buttons don't count: Return sends with the
        # first, as a browser does.
        form = a.get('f', -1)
        rest = [j for j in range(i + 1, len(acts)) if form >= 0 and acts[j].get('f', -1) == form
                and acts[j].get('t') in ('field', 'check', 'select')]
        if a.get('type') == 'textarea' or rest:
            if rest: s.select(rest[0])
            s.status = 'Filled in.' + ('  On to the next part of the form (its button sends it).' if rest else '')
            s.draw(); return
        s._do('submit', i)

    def choose(s, i, n):
        try:
            nav = s.b.act('select', i, n)
        except ERRS as e:
            s.status = 'Could not choose it: %s' % _short(e); s.draw(); return
        if nav: s._loaded(top=0)
        else: s.reread()

    def _do(s, op, i):
        s._remember(); s.busy = 'Working'; s.draw()
        try:
            nav = s.b.act(op, i)
        except ERRS as e:
            s.busy = ''; s.status = 'That did not work: %s' % _short(e); s.draw(); return
        if nav:
            s._loaded(top=0)
        else:
            s.busy = ''
            s.reread()
            now = time.time(); s.rereads = [now + 0.5, now + 1.5]
            s._shots()
            s.draw()

    def select(s, i):
        """Make act i the selected one and scroll it into view."""
        s.sel = i
        w = s.doc.where.get(i)
        if w:
            ln = w[0]
            if ln < s.top: s.top = max(0, ln - 2)
            elif ln >= s.top + BODY: s.top = min(max(0, len(s.doc) - BODY), ln - BODY + 3)

    def tab(s, step):
        acts = [a for a in sorted(s.doc.where, key=lambda a: s.doc.where[a])]
        if not acts: s.status = 'No links on this page.'; return
        onscreen = s.doc.acts_in(s.top, BODY)
        if s.sel in acts and (s.sel in onscreen or not onscreen):
            k = acts.index(s.sel) + step
            if not 0 <= k < len(acts):
                s.status = 'The last link.' if step > 0 else 'The first link.'; return
            s.select(acts[k])
        elif onscreen:
            s.select(onscreen[0] if step > 0 else onscreen[-1])
        else:                                                  # the next one below (or above) the screen
            below = [a for a in acts if s.doc.where[a][0] >= s.top + BODY]
            above = [a for a in acts if s.doc.where[a][0] < s.top]
            if step > 0 and below: s.select(below[0])
            elif step < 0 and above: s.select(above[-1])

    # ---- keys -------------------------------------------------------------
    def key(s, k):
        s.status = '' if not s.busy else s.status
        if k.startswith('osc:'):                              # (gridlink's, never a key)
            if k == 'osc:5150;shown': s.awaiting = False
            return
        if k in s.quit_keys: s.quit = True; return           # (from anywhere, typing included)
        if s.picture and s.line is None and s.menu is None: return s._picture_key(k)
        if k.startswith('click:'): return s.click(*(int(v) for v in k[6:].split(':')))
        if s.menu is not None: return s._menu_key(k)
        if s.line is not None: return s._line_key(k)
        if s.hints is not None: return s._hint_key(k)
        low = k.lower() if len(k) == 1 else k
        if k == 'up': s.scroll(-1)
        elif k == 'down': s.scroll(1)
        elif k in ('pgup', 'meta-v'): s.scroll(-(BODY - 2))
        elif k in ('pgdn', ' ', 'ctrl-v'): s.scroll(BODY - 2)
        elif k == 'home': s.top = 0
        elif k == 'end': s.top = max(0, len(s.doc) - BODY)
        elif k == 'tab': s.tab(1)
        elif k == 'btab': s.tab(-1)
        elif k == 'enter':
            if s.sel >= 0: s.activate(s.sel)
            else: s.status = 'Tab to a link first, or F for numbers.'
        elif k in ('left', 'bksp'): s.back(); return
        elif k == 'right': s.forward(); return
        elif low in ('g', 'o') or k in ('f6', 'ctrl-l'): s._go_line()
        elif low == 's':
            s.line = Line('Search: ')
            s.line_do = lambda t: s.go(s.search % urllib.parse.quote_plus(t)) if t.strip() else None
        elif k == '/':
            s.line = Line('Find: ', s.find_text)
            s.line_do = s.find
        elif low == 'n':
            if s.find_text: s.find(s.find_text, again=True)
        elif low == 'f': s._hints()
        elif low == 'r' or k == 'ctrl-r': s.reload(); return
        elif k == '.':                           # read the page again (no reload, nothing sent again)
            s.reread(); s.status = 'Read again.'
        elif low == 'h' or k in ('?', 'f1'): s.go(HOME); return
        elif low == 'v': s.picture_view(True); return
        elif low == 'y': s.plain_video(); return
        s.draw()

    def click(s, col, row):
        """A left click on a cell: in a list's choices, that choice; on the
        address, Go; on a link, button or field, as Tab to it and Return.
        A click elsewhere closes what is open (choices, numbers, typing)."""
        if s.menu is not None:
            i = s.menu[0]
            box = s._menu_box()
            if box[0] < row <= box[0] + box[2] and box[1] <= col < box[1] + box[3]:
                s.menu = None; s.draw(); s.choose(i, box[4] + row - box[0] - 1); return
            s.menu = None
        if s.line is not None:
            if row == ROWS - 1: return                      # (on the line being typed: nothing)
            s.line = None; s.line_do = None
        s.hints = None
        if row == 0:
            s._go_line(); s.draw(); return
        if TOP <= row < TOP + BODY:
            ln = s.top + row - TOP
            if ln < len(s.doc):
                acts = s.doc.act[ln]
                a = acts[col] if col < len(acts) else -1
                if a >= 0:
                    s.sel = a; s.draw(); s.activate(a); return
        s.status = ''
        s.draw()

    def _go_line(s):
        """Go: an address, or words to search for, typed on the bottom row."""
        s.line = Line('Go: ', '' if s.url == HOME else s.url)
        s.line_do = lambda t: s.go(to_url(t, s.search)) if t.strip() else None

    def _menu_box(s):
        """Where the list's choices are drawn: (first row, column, rows, width, first choice)."""
        if s.menu is None: return None
        i, opts, n = s.menu
        h = min(len(opts), BODY - 2); w = min(COLS - 4, max([len(o) for o in opts] + [10]) + 6)
        first = max(0, min(n - h // 2, len(opts) - h))
        return (TOP + max(0, (BODY - h - 2) // 2), (COLS - w) // 2, h, w, first)

    def scroll(s, n):
        s.top = max(0, min(s.top + n, max(0, len(s.doc) - BODY)))

    def _line_key(s, k):
        if k == 'esc': s.line = None; s.line_do = None
        elif k == 'enter':
            text = s.line.text; do = s.line_do
            s.line = None; s.line_do = None; s.draw()
            if do: do(text)
            return
        elif k.startswith('click:'): return s.click(*(int(v) for v in k[6:].split(':')))
        else: s.line.key(k)
        s.draw()

    def plain_video(s):
        """Y: the YouTube video open now, without YouTube's player: yt-dlp
        on the Pi finds its file, and gridfox plays that in a page of its own
        (video.py), in the picture view when the GRiD can show it."""
        try: s.url = s.b.m.url() or s.url        # (YouTube moves between videos by itself)
        except ERRS: pass
        if not V.is_video(s.url):
            s.status = 'Y plays a YouTube video on its own: open the video\'s page first.'; s.draw(); return
        s.busy = 'Finding the video (yt-dlp)'; s.draw()
        try:
            src, title, headers = V.find(s.url, profile=s.profile)
        except V.NotFound as e:
            s.busy = ''
            if s.picture: s.picture_view(False)  # (the picture covers the status line: the text, to say why)
            s.status = 'Y: %s' % _short(e); s.draw(); return
        s.go(V.write_page(V.serve(src, headers), title, os.path.dirname(s.view_path)))
        if s.pictures and not s.picture: s.picture_view(True)
        try:
            s.b.click_at(8, 8)                   # (a person's click: Firefox lets it start the sound)
        except ERRS as e:
            s.log('video start: %r' % (e,))
        s._shots()
        s.status = 'Playing: %s  (Back: YouTube)' % title; s.draw()

    # ---- the picture view ----------------------------------------------------
    def picture_view(s, on):
        """V: Firefox's pixels on the GRiD (a 640 x 384 viewport); Esc: the text again."""
        if on == s.picture: return
        if on and not s.pictures:
            s.status = 'The picture view needs CLAUDE.COM 1.2 on the GRiD (CLAUDE /W).'; s.draw(); return
        if on and s.url == HOME:
            s.status = 'The picture view is of a page: G to go to one first.'; s.draw(); return
        s.picture = on; s.pic_hash = None; s.awaiting = False
        try:
            s.b.view_size(*((PIC_W, PIC_H) if on else (TEXT_W, TEXT_H)))
        except ERRS as e:
            s.log('view size: %r' % (e,))
        if on:
            s.busy = 'Drawing the page'; s.draw()
            s._shots(); s._shoot()
            s.busy = ''
        else:
            s._sync_view()
            s.reread()
        s.draw()

    def _shots(s):
        """Pictures as the page settles after an action (the picture view)."""
        if s.picture:
            now = time.time(); s.shots = [now + d for d in SHOTS]

    def _shoot(s, frame=False):
        """Firefox's picture now; to the GRiD if it changed.  frame: a look
        on our own, not the one at an action: if the page changed by itself,
        the next look comes soon (FRAME_SHOT), else at the idle pace."""
        if s.shots and time.time() >= s.shots[0] - 0.01: s.shots.pop(0)
        s.shot_t = time.time()
        png = s.b.screenshot()
        if len(png) >= 24 and png[:8] == b'\x89PNG\r\n\x1a\n': s.pic_size = struct.unpack('>II', png[16:24])
        h = hashlib.sha1(png).digest()
        changed = h != s.pic_hash
        if frame: s.moving = changed
        if not changed and s.pic_up: return
        s.pic_hash = h; s.frame = frame
        tmp = s.view_path + '.tmp'
        with open(tmp, 'wb') as f: f.write(png)
        os.replace(tmp, s.view_path)
        s.pic_up = False; s._sync_view()
        s.awaiting = s.pic_up; s.sent_t = time.time()

    def _sync_view(s):
        """The picture up when in the picture view and not typing an address; else the text."""
        want = s.picture and not s.modal() and s.pic_hash is not None
        if want == s.pic_up: return
        s.pic_up = want
        if want:
            flags = ([] if s.pic_inv is None else ['invert' if s.pic_inv else 'plain']) + (['frame'] if s.frame else [])
            flags = ','.join(flags)
            s.out.write(('\x1b[?1016h\x1b]5150;show;%s;%s\x07' % (flags, s.view_path)).encode('utf-8'))
        else:
            s.out.write(b'\x1b[?1016l\x1b]5150;hide\x07')
        s.out.flush()

    def _pic_xy(s, x, y):
        """A pixel of the GRiD's picture -> the viewport's (gridlink fits a
        screenshot that isn't 640 x 384, centred: the same sums)."""
        iw, ih = s.pic_size
        if (iw, ih) == (PIC_W, PIC_H): return x, y
        sc = min(PIC_W / iw, PIC_H / ih)
        nw, nh = max(1, round(iw * sc)), max(1, round(ih * sc))
        return (x - (PIC_W - nw) // 2) / sc, (y - (PIC_H - nh) // 2) / sc

    def _picture_key(s, k):
        if k.startswith('click:'):
            x, y = (int(v) for v in k[6:].split(':'))
            vx, vy = s._pic_xy(x, y)
            if not (0 <= vx < s.pic_size[0] and 0 <= vy < s.pic_size[1]): return
            s._remember(); nav = s.b.click_at(vx, vy)
            if nav: s._loaded(top=0)
            else: s._shots(); s._shoot()
            return
        if k == 'esc': s.picture_view(False); return
        if k in ('up', 'down', 'pgup', 'pgdn', 'home', 'end'):
            d = {'up': -LINE_PX, 'down': LINE_PX, 'pgup': -PAGE_PX, 'pgdn': PAGE_PX}.get(k, 0)
            s.b.scroll(d, 0 if k == 'home' else -1 if k == 'end' else None)
            s._shots(); s._shoot(); return
        if k in ('f6', 'ctrl-l'):
            s._go_line(); s._sync_view(); s.draw(); return
        if k == 'ctrl-b': s.back(); return
        if k == 'ctrl-f': s.forward(); return
        if k == 'ctrl-r': s.reload(); return
        if k == 'ctrl-y': s.plain_video(); return
        if k == 'ctrl-i':                                 # light or dark: the other way
            s.pic_inv = not s.pic_inv if s.pic_inv is not None else True
            s.pic_up = False; s._sync_view(); return
        if k in ('enter', 'tab', 'btab', 'bksp', 'del', 'left', 'right', 'ins') or (len(k) == 1 and k.isprintable()):
            s._remember()
            if s.b.press([k]): s._loaded(top=0)
            else:
                s.shots = [time.time() + d for d in (0.15, 0.6, 1.5)]
            return

    def _hints(s):
        on = s.doc.acts_in(s.top, BODY)
        if not on: s.status = 'No links on the screen.'; return
        s.hints = {str(n + 1): a for n, a in enumerate(on)}; s.hint_in = ''
        s.status = 'Link number, then Return (Esc: none)'

    def _hint_key(s, k):
        if k == 'esc': s.hints = None; s.status = ''
        elif k == 'bksp': s.hint_in = s.hint_in[:-1]
        elif len(k) == 1 and k.isdigit():
            s.hint_in += k
            # unique: no longer number starts with it
            if s.hint_in in s.hints and not any(h != s.hint_in and h.startswith(s.hint_in) for h in s.hints):
                a = s.hints[s.hint_in]; s.hints = None; s.sel = a; s.activate(a); return
        elif k == 'enter':
            a = s.hints.get(s.hint_in); s.hints = None
            if a is not None: s.sel = a; s.activate(a); return
            s.status = 'No link %s.' % s.hint_in if s.hint_in else ''
        s.draw()

    def _menu_key(s, k):
        i, opts, n = s.menu
        if k == 'esc': s.menu = None
        elif k == 'up': s.menu[2] = max(0, n - 1)
        elif k == 'down': s.menu[2] = min(len(opts) - 1, n + 1)
        elif k == 'pgup': s.menu[2] = max(0, n - (BODY - 3))
        elif k == 'pgdn': s.menu[2] = min(len(opts) - 1, n + BODY - 3)
        elif k == 'enter':
            s.menu = None; s.draw(); s.choose(i, n); return
        s.draw()

    def find(s, text, again=False):
        if not text.strip(): return
        s.find_text = text
        start = (s.found + 1) if again and s.found >= 0 else s.top
        ln = s.doc.find(text, start)
        if ln < 0: s.status = 'Not on this page: %s' % text
        else:
            s.found = ln
            s.top = max(0, min(ln - 2, max(0, len(s.doc) - BODY)))
            s.status = 'Found on line %d of %d (N: next)' % (ln + 1, len(s.doc))
        s.draw()

    # ---- the screen -------------------------------------------------------
    def rows(s):
        """-> 24 rows of (text, attrs) and the cursor ((row, col) or None)."""
        out = []
        url = s.url if s.url != HOME else 'gridfox'
        bar = (' ' + _fit(url, COLS - 2)).ljust(COLS)
        out.append((bar, [P.A_INV] * COLS))
        hint_at = {}
        if s.hints:
            hint_at = {a: h for h, a in s.hints.items()}
        for r in range(BODY):
            ln = s.top + r
            if ln < len(s.doc):
                text = s.doc.text[ln].ljust(COLS)[:COLS]
                attr = (list(s.doc.attr[ln]) + [0] * COLS)[:COLS]
                acts = (list(s.doc.act[ln]) + [-1] * COLS)[:COLS]
                if s.sel >= 0:
                    attr = [a | P.A_INV if x == s.sel else a for a, x in zip(attr, acts)]
                if hint_at:
                    tl = list(text)
                    for c in range(COLS):
                        a = acts[c]
                        if a in hint_at and (c == 0 or acts[c - 1] != a):
                            lab = hint_at[a]
                            for j, ch in enumerate(lab):
                                if c + j < COLS: tl[c + j] = ch; attr[c + j] = P.A_INV
                    text = ''.join(tl)
                out.append((text, attr))
            else:
                out.append((' ' * COLS, [0] * COLS))
        if s.menu is not None:
            out = s._menu_rows(out)
        cur = None
        if s.line is not None:
            t, c = s.line.view(COLS)
            out.append((t.ljust(COLS), [0] * COLS)); cur = (ROWS - 1, min(c, COLS - 1))
        else:
            out.append((s._status_text(), [P.A_DIM] * COLS))
        return out, cur

    def _menu_rows(s, out):
        i, opts, n = s.menu
        r0, c0, h, w, first = s._menu_box()
        box = ['┌' + '─' * (w - 2) + '┐']
        for k in range(first, first + h):
            mark = '▸' if k == n else ' '
            box.append('│' + (' %s %s' % (mark, _fit(opts[k], w - 6))).ljust(w - 2) + '│')
        box.append('└' + '─' * (w - 2) + '┘')
        for j, b in enumerate(box):
            r = r0 + j
            t, a = out[r]
            inv = (first + j - 1 == n) and 0 < j < len(box) - 1
            out[r] = (t[:c0] + b + t[c0 + w:], a[:c0] + [P.A_INV if inv else 0] * w + a[c0 + w:])
        return out

    def _status_text(s):
        if s.busy: left = s.busy + '…'
        elif s.status: left = s.status
        elif s.sel >= 0 and s.sel < len(s.acts()):
            a = s.acts()[s.sel]
            left = {'link': lambda: a.get('h', ''), 'button': lambda: 'Button: ' + a.get('v', ''),
                    'field': lambda: 'Field: Return to type in it', 'check': lambda: 'Return: tick or untick',
                    'select': lambda: 'Return: choose'}.get(a.get('t'), lambda: '')()
        else: left = 'G go  S search  F follow  / find  Tab links  H help'
        n = len(s.doc)
        pos = 'All' if n <= BODY else 'Top' if s.top == 0 else 'Bot' if s.top >= n - BODY else \
            '%d%%' % (100 * (s.top + BODY) // n)
        right = ' %s ' % pos
        return (' ' + _fit(left, COLS - len(right) - 2)).ljust(COLS - len(right)) + right

    def draw(s, full=False):
        rows, cur = s.rows()
        parts = ['\x1b[?2026h']
        if full:                                 # (clicks: CLAUDE /W; in pixels only in the picture view)
            parts.append('\x1b[?7l\x1b[2J\x1b[?1000h\x1b[?1006h' + ('' if s.pic_up else '\x1b[?1016l'))
            s.shown = [None] * ROWS
        for r, (text, attr) in enumerate(rows):
            if s.shown[r] == (text, attr): continue
            s.shown[r] = (text, attr)
            parts.append('\x1b[%d;1H' % (r + 1) + _sgr_line(text, attr))
        title = s.model.get('title') or s.url
        if s.picture:                            # (the band is all that shows over the picture)
            title = (_fit(s.busy, BAND - 1) + '…') if s.busy else '%s  (Esc: text)' % _fit(title, BAND - 13)
        if title != s.title_sent:
            s.title_sent = title
            parts.append('\x1b]0;%s\x07' % P.clean(title).replace('\x07', '')[:70])
        if cur: parts.append('\x1b[%d;%dH\x1b[?25h' % (cur[0] + 1, cur[1] + 1))
        else: parts.append('\x1b[?25l')
        parts.append('\x1b[?2026l')
        s.out.write(''.join(parts).encode('utf-8')); s.out.flush()

    # ---- the loop ---------------------------------------------------------
    def modal(s): return s.line is not None or s.menu is not None or s.hints is not None

    def run(s, fd_in=0):
        keys = Keys()
        s.draw(full=True)
        if s.start: s._guard(lambda: s.go(to_url(s.start, s.search)))
        while not s.quit:
            now = time.time()
            wait = 0.5
            if not s.modal():                    # (while typing, the timed looks wait)
                if s.rereads: wait = max(0.0, min(wait, s.rereads[0] - now))
                if s.url != HOME: wait = max(0.0, min(wait, s.url_t + URL_EVERY - now))
                if s.picture: wait = max(0.0, min(wait, s._next_shot() - now))
            if keys.buf: wait = min(wait, 0.02)
            r, _, _ = select.select([fd_in], [], [], wait)
            now = time.time()
            if r:
                try: data = os.read(fd_in, 4096)
                except OSError: data = b''
                if not data: break
                ks = keys.feed(data, now)
            else:
                ks = keys.take(now)
            for k in ks:
                s._guard(lambda: s.key(k))
                if s.quit: break
            s._sync_view()
            if s.quit or s.modal(): continue
            now = time.time()
            if s.picture and now >= s._next_shot():
                s._guard(lambda: s._shoot(True))     # (a look on our own: not the one at an action)
            elif s.rereads and now >= s.rereads[0]:
                s.rereads.pop(0); s._guard(s.reread)
            elif s.url != HOME and now >= s.url_t + URL_EVERY:
                s.url_t = now; s._guard(s._check_url)

    def _next_shot(s):
        """A moving page: the next look once the GRiD has the last picture
        whole (gridlink says so), at most every FRAME_SHOT: one look a frame
        the link can carry, none wasted.  (SHOWN_WAIT if it never says.)"""
        if s.moving:
            t = s.shot_t + FRAME_SHOT
            if s.awaiting: t = max(t, s.sent_t + SHOWN_WAIT)
        else:
            t = s.shot_t + IDLE_SHOT
        return min(t, s.shots[0]) if s.shots else t

    def _check_url(s):
        """A page that arrived on its own (a slow link or form answered at last,
        a redirect, a script): read it."""
        u = s.b.m.url()
        if not u or u == s.url: return
        if _page(u) == _page(s.url) or s.b.same_document():
            s.reread()                           # a #fragment or the page's own history.pushState
        else:
            s._remember(); s._loaded(top=0)

    def _guard(s, fn):
        """One step; a lost Firefox ends gridfox (Term offers to start it
        again), anything else is shown and logged rather than fatal."""
        try:
            fn()
        except ERRS as e:
            if not getattr(s.b.m, 'dead', False):
                s.busy = ''; s.status = _short(e); s.draw()
        except Exception as e:
            import traceback; s.log(traceback.format_exc())
            s.busy = ''; s.status = 'gridfox: %s' % _short(e); s.draw()
        if getattr(s.b.m, 'dead', False):
            s.lost = 'the connection to Firefox was lost'; s.quit = True


def _click(seq):
    """'[<0;12;5M' (left button down at column 12, row 5) -> 'click:11:4';
    releases, other buttons and motion -> None."""
    try:
        b, x, y = (int(v) for v in seq[2:-1].split(';'))
    except ValueError:
        return None
    return 'click:%d:%d' % (x - 1, y - 1) if seq[-1] == 'M' and b == 0 else None


def _page(url):
    """The address without its #fragment: the same document."""
    return urllib.parse.urldefrag(url or '')[0]


def _fit(t, w):
    t = P.clean(t).replace('\n', ' ')
    return t if len(t) <= w else t[:max(0, w - 1)] + P.ELL


def _sgr_line(text, attr):
    out = []; cur = None
    for ch, a in zip(text, attr):
        a = (a & (P.A_LINK | P.A_INV | P.A_FIELD))
        if a != cur:
            sgr = ['0']
            if a & P.A_INV: sgr.append('7')
            if a & (P.A_LINK | P.A_FIELD): sgr.append('4')
            out.append('\x1b[%sm' % ';'.join(sgr)); cur = a
        out.append(ch)
    out.append('\x1b[0m')
    return ''.join(out)


def _short(e):
    t = str(e).strip().split('\n')[0]
    return t[:120]


def run_tty(app):
    """Run in a real terminal (the pty): raw keys, restored at the end."""
    fd = 0
    old = termios.tcgetattr(fd) if os.isatty(fd) else None
    try:
        if old: tty.setraw(fd)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, lambda *_: setattr(app, 'quit', True))
        app.run(fd)
    finally:
        if old: termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write('\x1b]5150;hide\x07\x1b[?1016l\x1b[?1000l\x1b[?1006l\x1b[?7h\x1b[?25h\x1b[0m\x1b[2J\x1b[H')
        if app.lost: sys.stdout.write('\r\n  gridfox stopped: %s.\r\n' % app.lost)
        sys.stdout.write('\r\n'); sys.stdout.flush()
