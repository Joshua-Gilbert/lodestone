"""The browser as gridfox uses it: one Firefox tab, read as a page model."""
import base64, os, random, time
from .marionette import MarionetteError, ELEMENT

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACT = open(os.path.join(HERE, 'extract.js'), encoding='utf-8').read()
ACT = open(os.path.join(HERE, 'act.js'), encoding='utf-8').read()

GONE = ('no such window', 'javascript error', 'no such frame', 'unknown error', 'stale element reference')

# WebDriver's codes for keys that aren't characters
KEYS = {'enter': '\ue007', 'tab': '\ue004', 'bksp': '\ue003', 'del': '\ue017', 'left': '\ue012',
        'right': '\ue014', 'up': '\ue013', 'down': '\ue015', 'home': '\ue011', 'end': '\ue010',
        'pgup': '\ue00e', 'pgdn': '\ue00f', 'ins': '\ue016'}
SHIFT = '\ue008'
# the dropdown (<select>) at a viewport point (or with the focus, x < 0): kept as
# window.__gridfoxPick; -> its options, the one chosen and where it is, or null
PICK = ('var x = arguments[0], y = arguments[1], d = document, el;'
        'if (x < 0) { el = d.activeElement; while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement; }'
        'else { el = d.elementFromPoint(x, y);'
        '  while (el && el.shadowRoot && el.shadowRoot.elementFromPoint) { var e2 = el.shadowRoot.elementFromPoint(x, y); if (!e2 || e2 === el) break; el = e2; } }'
        'while (el && (el.tagName === "OPTION" || el.tagName === "OPTGROUP")) el = el.parentElement;'
        'if (!el || el.tagName !== "SELECT" || el.disabled || el.multiple || el.size > 1) { window.__gridfoxPick = null; return null; }'
        'window.__gridfoxPick = el; var o = [];'
        'for (var i = 0; i < el.options.length && i < 500; i++) o.push([el.options[i].text.replace(/\\s+/g, " ").trim(), el.options[i].disabled]);'
        'var r = el.getBoundingClientRect();'
        'return {opts: o, v: el.selectedIndex, r: [r.left, r.top, r.width, r.height], w: innerWidth, h: innerHeight};')
# the frame (<iframe>) at a viewport point, and the point in its own viewport,
# or null: a click there goes into it (an embedded video player's)
FRAME_AT = ('var x = arguments[0], y = arguments[1], el = document.elementFromPoint(x, y);'
            'while (el && el.shadowRoot && el.shadowRoot.elementFromPoint) { var e2 = el.shadowRoot.elementFromPoint(x, y); if (!e2 || e2 === el) break; el = e2; }'
            'if (!el || (el.tagName !== "IFRAME" && el.tagName !== "FRAME")) return null;'
            'var r = el.getBoundingClientRect();'
            'return {el: el, x: x - r.left - el.clientLeft, y: y - r.top - el.clientTop};')
FRAMES = 4                      # frames inside frames a click goes into at most
# select_at()'s dropdown: option n chosen, as a person's choice is (input, change)
CHOOSE = ('var el = window.__gridfoxPick, n = arguments[0];'
          'if (!el || !el.isConnected) return false;'
          'el.focus(); el.selectedIndex = n;'
          'el.dispatchEvent(new Event("input", {bubbles: true})); el.dispatchEvent(new Event("change", {bubbles: true}));'
          'return true;')
SCROLL = ('var d = arguments[0], to = arguments[1];'
          'if (to !== null) window.scrollTo({top: to < 0 ? document.documentElement.scrollHeight : to,'
          ' behavior: "instant"});'
          'else window.scrollBy({top: d, behavior: "instant"});'
          'return window.scrollY;')


class Browser:
    def __init__(s, m, log=None):
        s.m = m; s.log = log or (lambda msg: None)
        s.stamp = None

    # ---- reading ----------------------------------------------------------
    def read(s, tries=20):
        """-> the page model (extract.js), waiting out a page still unloading."""
        last = None
        for _ in range(tries):
            try:
                r = s.m.script(EXTRACT, [{}], timeout=20)
                if isinstance(r, dict) and 'blocks' in r: return r
                last = 'no page'
            except MarionetteError as e:
                last = e
                if not any(g in str(e).lower() for g in GONE): raise
            time.sleep(0.1)
        raise RuntimeError('could not read the page: %s' % last)

    # ---- moving -----------------------------------------------------------
    def open(s, url):
        s.m.navigate(url)

    def back(s): s.m.back()

    def forward(s): s.m.forward()

    def reload(s): s.m.refresh()

    def act(s, op, i, val=None):
        """Act on element i of the last read; -> True if a new page came of it."""
        s._stamp()
        if op == 'click' and s._real_click(i):
            return s.settle()
        r = s.m.script(ACT, [op, i, val], timeout=15)
        if isinstance(r, dict) and not r.get('ok', True):
            raise RuntimeError(r.get('why', 'that did not work'))
        return s.settle()

    def _real_click(s, i):
        """Click as a person would (WebDriver:ElementClick: trusted events, so
        pop-up blockers and the like let it through).  False: it couldn't be
        clicked that way (covered, not interactable), try a script click."""
        r = s.m.script(ACT, ['el', i, None], timeout=15)
        if isinstance(r, dict) and not r.get('ok', True):
            raise RuntimeError(r.get('why', 'that did not work'))
        el = r.get('el') if isinstance(r, dict) else None
        if not isinstance(el, dict) or ELEMENT not in el: return False
        try:
            s.m.click(el)
            return True
        except MarionetteError as e:
            s.log('real click refused (%s); a script click instead' % e.error)
            return False

    def _stamp(s):
        s.stamp = '%016x' % random.getrandbits(64)
        try: s.m.script(ACT, ['stamp', 0, s.stamp], timeout=5)
        except MarionetteError: pass

    def settle(s, start=0.35, load=20.0):
        """After an action: wait briefly to see whether a new page starts
        loading; if one does, until it has its document (eager)."""
        t0 = time.time(); new = False
        while time.time() - t0 < start:
            st = s._stamped()
            # a new document, or the old one already unloading (a slow page on its way)
            if st is None or not st.get('same') or st.get('leaving'): new = True; break
            time.sleep(0.03)
        if not new:
            return False
        while time.time() - t0 < load:
            st = s._stamped()
            if st is not None and not st.get('same') and st.get('ready') in ('interactive', 'complete'): break
            time.sleep(0.05)
        return True

    def mark(s):
        """Mark the document now open (so a later look can tell it is the same one)."""
        s._stamp()

    def same_document(s):
        """The document marked last is still the one open (an address changed
        by a #fragment or history.pushState, not a new page)."""
        if s.stamp is None: return False
        st = s._stamped()
        return bool(st and st.get('same') and not st.get('leaving'))

    def _stamped(s):
        try:
            return s.m.script(ACT, ['stamped', 0, s.stamp], timeout=5)
        except MarionetteError:
            return None                         # (the old page is unloading)

    # ---- the picture view: Firefox's own pixels ----------------------------
    def view_size(s, w, h):
        """The viewport w x h (the window less whatever Firefox draws around it)."""
        s.m.set_window(w, h)
        try:
            iw, ih = s.m.script('return [window.innerWidth, window.innerHeight];', timeout=5)
            if (iw, ih) != (w, h): s.m.set_window(w + (w - int(iw)), h + (h - int(ih)))
        except (MarionetteError, TypeError, ValueError):
            pass

    def screenshot(s):
        """-> PNG bytes of the viewport."""
        return base64.b64decode(s.m.screenshot())

    def click_at(s, x, y):
        """A click at viewport pixel (x, y): -> True if a new page came of it.
        On a frame (an embedded player: Vimeo's, YouTube's), the click goes
        into the frame's own page at that point, as a person's would: sent to
        the page around it, the frame's page never had it (its play button
        did nothing, and with autoplay off nothing starts without one)."""
        s._stamp()
        depth = 0
        try:
            while depth < FRAMES:
                try:
                    r = s.m.script(FRAME_AT, [x, y], timeout=5)
                    if not isinstance(r, dict) or not isinstance(r.get('el'), dict): break
                    s.m.frame(r['el'])
                except MarionetteError as e:
                    s.log('frame not entered (%s): clicked around it' % getattr(e, 'error', e))
                    break
                depth += 1
                x, y = r.get('x', x), r.get('y', y)
            s.m.actions([{'type': 'pointer', 'id': 'gridfox-mouse', 'parameters': {'pointerType': 'mouse'},
                          'actions': [{'type': 'pointerMove', 'x': int(x), 'y': int(y), 'origin': 'viewport',
                                       'duration': 0},
                                      {'type': 'pointerDown', 'button': 0}, {'type': 'pointerUp', 'button': 0}]}])
        finally:
            for _ in range(depth):
                try: s.m.parent_frame()
                except MarionetteError: pass
        return s.settle()

    def select_at(s, x, y):
        """The dropdown (<select>) at viewport pixel (x, y), or with the focus
        when x is None: {opts: [[text, disabled]], v: the one chosen, r: [x, y,
        w, h] where it is, w, h: the viewport}, or None.  Firefox draws a
        dropdown's list as a pop-up of its own, which a headless Firefox's
        screenshots never show, so the picture view draws gridfox's instead."""
        try:
            r = s.m.script(PICK, [-1 if x is None else x, -1 if y is None else y], timeout=5)
        except MarionetteError:
            return None
        return r if isinstance(r, dict) and r.get('opts') else None

    def choose_picked(s, n):
        """select_at()'s dropdown: option n chosen.  -> True if a new page came of it."""
        s._stamp()
        if not s.m.script(CHOOSE, [n], timeout=10): raise RuntimeError('that list is no longer on the page')
        return s.settle()

    def press(s, keys):
        """gridfox's key names and characters, typed into the page (whatever
        has the focus).  -> True if a new page came of them (Return in a form)."""
        acts = []
        for k in keys:
            if k == 'btab':
                acts += [{'type': 'keyDown', 'value': SHIFT}, {'type': 'keyDown', 'value': KEYS['tab']},
                         {'type': 'keyUp', 'value': KEYS['tab']}, {'type': 'keyUp', 'value': SHIFT}]
                continue
            v = KEYS.get(k, k if len(k) == 1 else None)
            if v is None: continue
            acts += [{'type': 'keyDown', 'value': v}, {'type': 'keyUp', 'value': v}]
        if not acts: return False
        s._stamp()
        s.m.actions([{'type': 'key', 'id': 'gridfox-keys', 'actions': acts}])
        return s.settle() if 'enter' in keys else False

    def scroll(s, dy=0, to=None):
        """Scroll by dy pixels, or to a place (-1: the end).  -> the scroll position."""
        return s.m.script(SCROLL, [dy, to], timeout=5)

    def ready_state(s):
        try: return s.m.script('return document.readyState;', timeout=5)
        except MarionetteError: return None
