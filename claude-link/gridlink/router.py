"""One gridlink, two ways to use Claude from the GRiD.

    chat  CLAUDE.COM's own conversation, run by gridlink's agent (API key)
    term  the real Claude Code on the Pi, the GRiD as its terminal
          (your Claude subscription; no API key)

The GRiD's HELLO picks: `app=term` (CLAUDE /T) or `app=chat` (CLAUDE /C);
without either, the config's [grid] app decides ("auto": chat when the Pi
has an API key, Term when it hasn't).  Term only goes to a CLAUDE that says
it can show it (HELLO flags bit 0).  The Pi's HELLO answer says which it
chose (flag HF_TERM).
"""
from . import glp
from .link import Link
from .term import TermSession


class Gate:
    """The link as an app sees it: its sends are dropped while another app
    has the GRiD (a chat turn still running after the GRiD went to Term)."""
    def __init__(s, link, active): s._link, s._active = link, active

    def send(s, t, body=b''):
        if s._active(): s._link.send(t, body)

    def send_first(s, t, body=b''):
        if s._active(): s._link.send_first(t, body)

    def __getattr__(s, name): return getattr(s._link, name)


class NoAgent:
    """Chat asked for, but it can't run here (no API key, or no anthropic)."""
    MSG = ('This Pi has no API key, so Claude for GRiD\'s own chat can\'t run here. '
           'For Claude Code with your Claude subscription, start CLAUDE /T.')
    OLD = ('This Pi has no API key, so Claude for GRiD\'s own chat can\'t run here. '
           'CLAUDE 1.1 (Grid-OS 0.4) can use Claude Code on your Claude plan instead: CLAUDE /T.')

    def __init__(s, log=print, why=None): s.log = log; s.link = None; s.why = why; s.can_term = True

    def attach(s, link): s.link = link

    def on_message(s, t, body):
        if t == glp.G_HELLO:
            s.can_term = len(body) >= 2 and bool(body[1] & glp.GF_TERM)
            s.link.send_first(glp.P_HELLO, bytes([glp.VERSION, 0]) + b'no API key')
            s.link.send(glp.P_TEXT, s.text() + b'\n')
            s.link.send(glp.P_READY)
        elif t == glp.G_PROMPT:
            s.link.send(glp.P_TEXT, b'\n' + s.text() + b'\n')
            s.link.send(glp.P_READY)
        elif t == glp.G_REPLY:
            pass

    def text(s):
        m = s.why or (s.MSG if s.can_term else s.OLD)
        return m.encode('latin1', 'replace')


class Router:
    def __init__(s, cfg, log=print, make_agent=None, term=None):
        s.cfg, s.log = cfg, log
        s.make_agent = make_agent          # (link) -> attached agent Session, or None (no key)
        s.link = None
        s.term = term; s.agent = None; s.active = None; s.app = None

    def attach(s, link):
        s.link = link

    def choose(s, body):
        info = glp.kv_lines(body[6:]) if len(body) >= 6 else {}
        can_term = len(body) >= 2 and bool(body[1] & glp.GF_TERM)   # an older CLAUDE can't
        app = info.get('app', '').lower()
        if app in ('term', 'chat'): want = app
        else:
            want = getattr(s.cfg, 'app', 'auto')
            if want not in ('term', 'chat'): want = 'chat' if s.has_key() else 'term'
        return want if want == 'chat' or can_term else 'chat'

    def has_key(s):
        return bool(getattr(s.cfg, 'api_key', None)) or s.cfg.env_key()

    def on_message(s, t, body):
        if t == glp.G_HELLO:
            s.switch(s.choose(body))
        if s.active is not None:
            s.active.on_message(t, body)

    def switch(s, app):
        if app == s.app: return
        s.log('gridlink: %s' % ('Term (Claude Code on the Pi)' if app == 'term' else 'chat'))
        s.quiesce(s.active)
        if s.term is not None: s.term.detach()
        if app == 'term':
            if s.term is None: s.term = TermSession(s.cfg, log=s.log)
            s.term.attach(s.link)
            s.active = s.term
        else:
            s.link.hold = Link.HOLD
            if s.agent is None:
                gate = Gate(s.link, lambda: s.active is s.agent)
                why = None
                if s.make_agent is not None:
                    try:
                        s.agent = s.make_agent(gate)
                    except Exception as e:           # (no anthropic, a bad config...)
                        s.log('gridlink: chat can\'t start: %r' % e)
                        why = 'Claude for GRiD\'s chat can\'t start on the Pi: %s' % e
                if s.agent is None:
                    s.agent = NoAgent(s.log, why); s.agent.attach(gate)
            s.active = s.agent
        s.app = app

    def quiesce(s, app):
        """The app the GRiD is leaving: stop its turn, fail its GRiD calls."""
        if app is None: return
        if getattr(app, 'busy', False) and hasattr(app, 'interrupt'):
            app.interrupt.set()
            with app.ask_cv: app.ask_cv.notify_all()
        g = getattr(app, 'grid', None)
        if g is not None: g.on_restart()
