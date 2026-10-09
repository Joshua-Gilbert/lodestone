"""Term: the real Claude Code, in a pty on the Pi, with the GRiD as its screen
and keyboard.  Your Claude subscription works here because nothing sits
between you and the `claude` program but a terminal.

The GRiD sends KEYS (BIOS key words); they go into the pty as an xterm's
keys.  What `claude` draws goes into pyte; the Link pulls CELLS frames from
here, always for the latest screen.  The GRiD's own abilities (files, RUN,
SCREEN, GPIB) reach Claude Code through the MCP bridge (mcp.py), which
talks to this process over a Unix socket.
"""
import fcntl, os, select, shlex, shutil, struct, subprocess, termios, threading, time
import pyte
from . import glp
from .grid import Grid
from .keys import term_keys
from .termscreen import TermScreen, PreFilter, Encoder, fold_title
from . import mcp

SETTLE = 0.012       # no pty output for this long: the screen is drawn
MAX_WAIT = 0.08      # but never hold changes back longer than this
SYNC_MAX = 0.5       # an unfinished ?2026 frame counts as done after this
TERM_HOLD = 0.06     # the Pi's hold on a POLL in Term (250 ms in chat)
TITLE_EVERY = 1.0
ESC_GAP = 0.03       # after a lone Esc, before the next key


def _ctty():
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def resolve(cmd):
    """The program to run: as given, on PATH, or where Claude Code's
    installers put it (a systemd service's PATH has no ~/.local/bin)."""
    c = cmd[0]
    if os.sep in c or shutil.which(c): return cmd
    for d in ('~/.local/bin', '~/.claude/local', '~/.npm-global/bin', '/usr/local/bin'):
        p = os.path.join(os.path.expanduser(d), c)
        if os.access(p, os.X_OK): return [p] + cmd[1:]
    return cmd


class TermSession:
    def __init__(s, cfg, log=print, command=None, cwd=None):
        s.cfg, s.log = cfg, log
        s.command = command or shlex.split(getattr(cfg, 'term_command', 'claude'))
        s.cwd = os.path.expanduser(cwd or getattr(cfg, 'term_dir', '~/grid'))
        s.lock = threading.RLock()
        s.screen = TermScreen(); s.stream = pyte.ByteStream(s.screen)
        s.screen.write_process_input = s._answer_query
        s.pre = PreFilter(lambda: s.screen.mode)
        s.enc = Encoder()
        s.link = None; s.grid = None
        s.child = None; s.fd = None; s.reader = None
        s.dirty = True; s.last_byte = 0.0; s.first_dirty = 0.0
        s.title = ''; s.title_sent = None; s.title_t = 0.0
        s.hello = {}; s.exited = None
        s.stats = dict(keys=0, pty_in=0, pty_out=0)
        s.tools = None; s.sock = mcp.socket_path(cfg)

    # ---- the link ------------------------------------------------------
    def attach(s, link):
        if s.link is not link:
            s.link = link; s.grid = Grid(link)
        link.source = s; link.hold = TERM_HOLD
        if s.tools is None:
            # the GRiD's abilities for Claude Code (mcp.py), one request at a time
            try:
                s.tools = mcp.ToolServer(s.sock, mcp.GridTools(s.grid, s.cfg, getattr(s.cfg, 'address', 7), root=s.cwd),
                                         available=s.why_not, log=s.log).start()
            except OSError as e:
                s.log('term: no MCP socket at %s: %s' % (s.sock, e))

    def why_not(s):
        """Why a GRiD tool can't run now (None: it can)."""
        if s.link is None or s.link.source is not s:
            return 'The GRiD is not in Term mode (CLAUDE /T on the GRiD).'
        if not s.hello or time.time() - s.link.last_rx > 10:
            return 'The GRiD is not connected (start CLAUDE /T on it).'
        return None

    def detach(s):
        if s.link is not None and s.link.source is s: s.link.source = None

    def on_message(s, t, body):
        if t == glp.G_HELLO:
            info = {}
            if len(body) >= 6: info.update(glp.kv_lines(body[6:]))
            s.hello = info
            s.grid.on_restart()
            with s.lock:
                s.enc.reset(); s._mark()
            s.link.send_first(glp.P_HELLO, bytes([glp.VERSION, glp.HF_TERM]) + b'Claude Code')
            s.title_sent = None
            if s.child is None and s.exited is None: s.start()
            s._send_title(force=True)
            if getattr(s.cfg, 'set_clock', False):
                threading.Thread(target=s._settime, daemon=True).start()
        elif t == glp.G_KEYS:
            s.keys(body)
        elif t == glp.G_EVENT and body:
            if body[0] == glp.EV_REPAINT:
                with s.lock:
                    s.enc.reset(); s._mark()
        elif t == glp.G_REPLY:
            s.grid.on_reply(body)

    # Link source: called with the link's lock held
    def ready(s):
        with s.lock:
            if not s.dirty: return False
            now = time.time()
            if s.screen.sync and now - s.screen.sync_t < SYNC_MAX: return False
            return now - s.last_byte >= SETTLE or now - s.first_dirty >= MAX_WAIT

    def take(s, maxpay):
        with s.lock:
            tc, ta = s.screen.cells()
            c = s.screen.cursor
            cur = (min(c.y, 23), min(c.x, 79), bool(c.hidden))
            p, more = s.enc.make(tc, ta, cur, maxpay)
            s.dirty = more
            if more: s.first_dirty = 0.0          # the rest goes at once
            return p

    def delivered(s):
        with s.lock: s.enc.delivered()

    def _mark(s):
        if not s.dirty: s.first_dirty = time.time()
        s.dirty = True

    def _settime(s):
        lock = s.tools.lock if s.tools is not None else threading.Lock()
        try:
            with lock: s.grid.settime()               # one GRiD request at a time
        except Exception as e: s.log('term: settime: %s' % e)

    # ---- the program ---------------------------------------------------
    def start(s):
        try:
            return s._start()
        except Exception as e:
            s.child = None; s.exited = -1
            s.log('term: can\'t start: %r' % e)
            s._message('Can\'t start %s: %s. Press Return to try again.' % (s.command[0], e))
            return False

    def _start(s):
        os.makedirs(s.cwd, exist_ok=True)
        try:
            if mcp.write_mcp_json(s.cwd, s.sock): s.log('term: registered the GRiD tools in %s/.mcp.json' % s.cwd)
        except (OSError, ValueError) as e:
            s.log('term: .mcp.json left alone: %s' % e)
        m, sl = os.openpty()
        fcntl.ioctl(sl, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        env = dict(os.environ, TERM='xterm-256color', LANG='C.UTF-8', COLUMNS='80', LINES='24')
        env.pop('COLORTERM', None)
        if not getattr(s.cfg, 'term_api_key', False):
            # Term is for the subscription: a key in gridlink's environment
            # (for the chat) must not make Claude Code bill the API instead
            for k in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'): env.pop(k, None)
        try:
            s.child = subprocess.Popen(resolve(s.command), stdin=sl, stdout=sl, stderr=sl, cwd=s.cwd, env=env,
                                       start_new_session=True, preexec_fn=_ctty, close_fds=True)
        except OSError as e:
            os.close(sl); os.close(m)
            s.child = None; s.exited = -1
            s._message('Can\'t start %s: %s.\r\nInstall Claude Code on the Pi (see the README), '
                       'then press Return.' % (s.command[0], e.strerror or e))
            return False
        os.close(sl)
        s.fd = m; s.exited = None
        with s.lock:
            s.screen.reset(); s._mark()
            s.stream = pyte.ByteStream(s.screen)          # nothing half-parsed from before
            s.pre = PreFilter(lambda: s.screen.mode)
        s.reader = threading.Thread(target=s._read, args=(m, s.child), daemon=True, name='term-pty')
        s.reader.start()
        s.log('term: started %s in %s (pid %d)' % (' '.join(s.command), s.cwd, s.child.pid))
        return True

    def stop(s):
        if s.tools is not None: s.tools.stop()
        if s.child is not None:
            try: s.child.terminate(); s.child.wait(3)
            except Exception:
                try: s.child.kill()
                except Exception: pass

    def _read(s, fd, child):
        while True:
            try:
                r, _, _ = select.select([fd], [], [], 0.5)
            except (OSError, ValueError):
                break
            if r:
                try: data = os.read(fd, 65536)
                except OSError: data = b''
                if not data: break
                s.feed(data)
            s._send_title()
        code = child.wait()
        mine = s.child is child                   # (not one started again since)
        if mine:
            s.child = None; s.fd = None; s.exited = code
        try: os.close(fd)
        except OSError: pass
        if mine:
            s.log('term: %s exited (%s)' % (s.command[0], code))
            s._message('%s exited (code %s). Press Return to start it again, CODE-Q to leave.'
                       % (s.command[0], code))

    def feed(s, data):
        s.stats['pty_in'] += len(data)
        with s.lock:
            for kind, b in s.pre.parts(data):     # pyte answers DA as it goes: keep the order
                if kind == 'data': s.stream.feed(b)
                else: s._write(b)
            s.last_byte = time.time(); s._mark()
            s.title = s.screen.title
        if s.link is not None: s.link.wake()

    def _answer_query(s, text):
        s._write(text.encode('latin1') if isinstance(text, str) else text)

    def _write(s, data):
        if s.fd is None or not data: return
        try:
            os.write(s.fd, data); s.stats['pty_out'] += len(data)
        except OSError:
            pass

    def _message(s, text):
        with s.lock:
            s.stream.feed(('\r\n\x1b[7m %s \x1b[27m\r\n' % text).encode('utf-8'))
            s._mark()
        if s.link is not None: s.link.wake()

    def keys(s, body):
        s.stats['keys'] += len(body) // 2
        if s.child is None:
            if any(body[i] == 0x0D for i in range(0, len(body) - 1, 2)): s.start()
            return
        # A lone Esc followed by more keys in one write reads as Meta-key (or
        # Esc Esc as Meta-Esc): give each Esc its own write and a moment.
        start = 0
        for i in range(0, len(body) - 1, 2):
            if body[i] == 0x1B and body[i + 1] == 0x01 and i + 2 < len(body):
                s._write(term_keys(body[start:i + 2], s.screen.app_cursor))
                time.sleep(ESC_GAP); start = i + 2
        s._write(term_keys(body[start:], s.screen.app_cursor))

    def _send_title(s, force=False):
        if s.link is None or s.link.source is not s: return
        t = fold_title(s.title) or 'Claude Code'
        now = time.time()
        if t != s.title_sent and (force or now - s.title_t >= TITLE_EVERY):
            s.title_sent = t; s.title_t = now
            s.link.send(glp.P_TITLE, t.encode('latin1', 'replace'))

    def text(s):
        with s.lock: return s.screen.text()
