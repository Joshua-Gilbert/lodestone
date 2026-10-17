"""The browser as gridfox uses it: one Firefox tab, read as a page model."""
import os, random, time
from .marionette import MarionetteError, ELEMENT

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACT = open(os.path.join(HERE, 'extract.js'), encoding='utf-8').read()
ACT = open(os.path.join(HERE, 'act.js'), encoding='utf-8').read()

GONE = ('no such window', 'javascript error', 'no such frame', 'unknown error', 'stale element reference')


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

    def _stamped(s):
        try:
            return s.m.script(ACT, ['stamped', 0, s.stamp], timeout=5)
        except MarionetteError:
            return None                         # (the old page is unloading)

    def ready_state(s):
        try: return s.m.script('return document.readyState;', timeout=5)
        except MarionetteError: return None
