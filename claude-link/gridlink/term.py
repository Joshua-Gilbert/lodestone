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
from . import picture as PIC
from . import plotview

SETTLE = 0.012       # no pty output for this long: the screen is drawn
MAX_WAIT = 0.08      # but never hold changes back longer than this
SYNC_MAX = 0.5       # an unfinished ?2026 frame counts as done after this
TERM_HOLD = 0.06     # the Pi's hold on a POLL in Term (250 ms in chat)
TITLE_EVERY = 1.0
ESC_GAP = 0.03       # after a lone Esc, before the next key
STOP_WEB = 15.0      # gridfox's own wait for Firefox to quit is 10 s


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
    def __init__(s, cfg, log=print, command=None, cwd=None, web=False):
        s.cfg, s.log = cfg, log
        s.web = web                     # gridfox (CLAUDE /W) instead of Claude Code: no GRiD tools
        default = getattr(cfg, 'web_command', 'python3 -m gridfox') if web else getattr(cfg, 'term_command', 'claude')
        s.command = command or shlex.split(default)
        # gridfox runs in a folder of its own: `python3 -m` puts the folder
        # first on sys.path, and Claude Code writes files in ~/grid
        default_dir = getattr(cfg, 'web_dir', '~/.cache/gridfox') if web else getattr(cfg, 'term_dir', '~/grid')
        s.cwd = os.path.expanduser(cwd or default_dir)
        s.name = 'gridfox' if web else 'Claude Code'
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
        s.away = False                  # resident Claude: the user went back to the program
        s.stats = dict(keys=0, pty_in=0, pty_out=0)
        s.tools = None; s.sock = mcp.socket_path(cfg)
        # A picture over the text (picture.py): while one is up it is the
        # link's frame source, and pyte goes on keeping the text underneath.
        s.pic = None                    # {'bits', 'owner', 'on_click', 'on_key', 'title'}
        s.pic_next = None               # a frame waiting for the one on its way to be whole (a video)
        s.penc = PIC.Encoder(); s.from_pic = False
        s.gflags = 0                    # the GRiD's HELLO flags (bit 1: it takes pictures)

    # ---- the link ------------------------------------------------------
    def attach(s, link):
        if s.link is not link:
            s.link = link; s.grid = Grid(link)
            s.grid.after_run = s.picture_lost         # (the program drew over a picture)
        link.source = s; link.hold = TERM_HOLD
        if s.tools is None and not s.web:
            # the GRiD's abilities for Claude Code (mcp.py), one request at a time
            try:
                s.tools = mcp.ToolServer(s.sock, mcp.GridTools(s.grid, s.cfg, getattr(s.cfg, 'address', 7), root=s.cwd,
                                                               hello=lambda: s.hello, viewer=plotview.Viewer(s)),
                                         available=s.why_not, log=s.log).start()
            except OSError as e:
                s.log('term: no MCP socket at %s: %s' % (s.sock, e))

    RESIDENT = ('Claude Code is popped up over a DOS program on the GRiD (%s; resident Claude, CLAUDE /R): '
                '%s work, but not this one while it is paused. Leave that program and start CLAUDE /T on '
                'the GRiD for it.')
    NOT_PAUSED = ('No DOS program is paused under resident Claude: grid_program and grid_type work in its '
                  'console (CLAUDE /R on the GRiD, then CODE-\\ over a program).')
    PAUSED_TOOLS = ('grid_program', 'grid_type')    # the ones the console answers
    OPS_TOOLS = {'files': ('grid_files', 'grid_change_files'),          # and as its HELLO's ops= says
                 'gpib': ('gpib_read', 'gpib_measure', 'gpib_send')}
    AWAY = ('The user has gone back from resident Claude\'s console to the DOS program on the GRiD (%s), which '
            'is running again: no GRiD tool works until they bring the console up over it again (CODE-\\).')
    AWAY_CALL = 'the user went back to the program (CODE-\\) before it answered'

    def resident(s):
        """The GRiD is CLAUDE /R's console, over a DOS program it paused."""
        return s.hello.get('app', '').lower() == 'resident'

    def why_not(s, tool=None):
        """Why a GRiD tool can't run now (None: it can)."""
        if s.link is None or s.link.source is not s:
            return 'The GRiD is not in Term mode (CLAUDE /T on the GRiD).'
        prog = s.hello.get('prog') or 'its name unknown'
        if s.away and s.resident(): return s.AWAY % prog
        if not s.hello or time.monotonic() - s.link.last_rx > 10:
            return 'The GRiD is not connected (start CLAUDE /T on it).'
        if s.resident():
            tools = s.paused_tools()
            if tool in tools: return None
            return s.RESIDENT % (prog, ', '.join(tools))
        return s.NOT_PAUSED if tool in s.PAUSED_TOOLS else None

    def paused_tools(s):
        """The GRiD tools resident Claude's console answers: grid_program and
        grid_type, then files and GPIB as its HELLO's ops= says (CLAUDE 1.9)."""
        ops = s.hello.get('ops', '').lower().split(',')
        return s.PAUSED_TOOLS + tuple(t for o in ops for t in s.OPS_TOOLS.get(o.strip(), ()))

    def may_ring(s):
        """The Link may ring the GRiD (an SRQ for a POLL): not while resident
        Claude's console is down, its program running (the user went back,
        TYPE's keys play, or a TYPE was given up on and the console hasn't
        been heard from since): that SRQ would be the program's."""
        return not (s.resident() and (s.away or s.grid.typing or s.grid.type_out))

    def detach(s):
        if s.link is not None and s.link.source is s: s.link.source = None

    def on_message(s, t, body):
        if t == glp.G_HELLO:
            info = {}
            if len(body) >= 6: info.update(glp.kv_lines(body[6:]))
            s.hello = info; s.away = False
            s.gflags = body[1] if len(body) >= 2 else 0
            s.screen.quads = bool(s.gflags & glp.GF_QUAD) and not s.resident()   # (CLAUDE 1.8's block elements)
            s.grid.on_restart()
            with s.lock:
                # CLAUDE /R's console kept its screen: go on from it if we sent it
                if not s.enc.resume(info.get('screen')): s.enc.reset()
                s.penc.reset()                    # (a picture: the GRiD's screen is unknown)
                if s.pic is not None and not s.can_picture(): s._drop_picture()
                s._mark()
            s.link.send_first(glp.P_HELLO, bytes([glp.VERSION, glp.HF_TERM]) + s.name.encode())
            s.title_sent = None
            if s.child is None and s.exited is None: s.start()
            s._send_title(force=True)
            if getattr(s.cfg, 'set_clock', False) and not s.resident():    # (no DOS calls there)
                threading.Thread(target=s._settime, daemon=True).start()
        elif t == glp.G_KEYS:
            s.keys(body)
        elif t == glp.G_EVENT and body:
            if body[0] == glp.EV_REPAINT:         # (the GRiD redrew the text: a picture is gone too)
                with s.lock:
                    s.enc.reset(); s.penc.reset(); s._mark()
            elif body[0] == glp.EV_PIXCLICK and len(body) >= 5:    # x, y in pixels (CLAUDE 1.2)
                s.click_at(body[1] | body[2] << 8, body[3] | body[4] << 8)
            elif body[0] == glp.EV_CLICK and len(body) >= 3:       # a cell (#32's CLAUDE)
                s.click_at(body[1] * 8 + 4, body[2] * 16 + 8)
            elif body[0] == glp.EV_AWAY:        # (resident Claude's console, going: never for TYPE's keys)
                s.away = True
                s.grid.end_calls(s.AWAY_CALL)
        elif t == glp.G_REPLY:
            s.grid.on_reply(body)

    # Link source: called with the link's lock held
    def ready(s):
        with s.lock:
            if s.pic is not None: return s.penc.dirty(s.pic['bits'])
            if not s.dirty: return False
            now = time.monotonic()
            if s.screen.sync and now - s.screen.sync_t < SYNC_MAX: return False
            return now - s.last_byte >= SETTLE or now - s.first_dirty >= MAX_WAIT

    def take(s, maxpay):
        with s.lock:
            if s.pic is not None:
                p, more = s.penc.make(s.pic['bits'], maxpay)
                s.from_pic = p is not None
                return p
            s.from_pic = False
            tc, ta = s.screen.cells()
            c = s.screen.cursor
            cur = (min(c.y, 23), min(c.x, 79), bool(c.hidden))
            p, more = s.enc.make(tc, ta, cur, maxpay)
            s.dirty = more
            if more: s.first_dirty = 0.0          # the rest goes at once
            return p

    def delivered(s):
        with s.lock:
            if s.from_pic: s.penc.delivered()
            else: s.enc.delivered()
            pic = s.pic; tell = False
            if pic is not None and pic['owner'] == 'pty' and not pic.get('told') and s.penc.shown == pic['bits']:
                pic['told'] = tell = True               # (gridfox paces a moving page's looks by it)
            nxt = s.pic_next
            if nxt is not None and pic is not None and s.penc.shown == pic['bits']:
                s.pic = nxt; s.pic_next = None          # the last frame is whole on the GRiD: the next
        if tell: s._write(b'\x1b]5150;shown\x07')

    # ---- pictures (picture.py) -------------------------------------------
    def can_picture(s):
        """The GRiD takes pictures: a CLAUDE.COM that says so, not resident
        Claude's console (its CELLS have no pixels)."""
        return bool(s.gflags & glp.GF_PIX) and not s.resident()

    def show_picture(s, bits, owner, on_click=None, on_key=None, title=None, frame=False):
        """bits (picture.SIZE bytes) over the text, until hide_picture.
        on_click(x, y) for a click on it; on_key(body) -> the keys left for
        the program (b'' when it took them all).  frame: one of a stream (a
        video): it waits until the GRiD has the one on its way whole, as the
        newest of those waiting.  (Else a fast stream would keep restarting the
        top of the picture and the bottom would never come.)"""
        if len(bits) != PIC.SIZE: raise ValueError('a picture is %d bytes' % PIC.SIZE)
        if not s.can_picture():
            raise RuntimeError('The GRiD can\'t show pictures here (it needs CLAUDE.COM 1.2 under CLAUDE /T or /W, '
                               'not resident Claude\'s console).')
        pic = {'bits': bytes(bits), 'owner': owner, 'on_click': on_click, 'on_key': on_key,
               'title': fold_title(''.join(c for c in title if c.isprintable())) if title else None}
        with s.lock:
            if (frame and s.pic is not None and s.pic['owner'] == owner and s.pic['title'] == pic['title']
                    and s.penc.shown != s.pic['bits']):
                s.pic_next = pic; return               # (no wake: the frame on its way goes on)
            if s.pic is None: s.penc.reset()   # (the first frame clears the text away)
            s.pic = pic; s.pic_next = None
            tell = owner == 'pty' and s.penc.shown == pic['bits']   # (the same pixels: whole already)
            if tell: pic['told'] = True
        if tell: s._write(b'\x1b]5150;shown\x07')
        s.title_sent = None; s._send_title(force=True)
        if s.link is not None: s.link.wake()

    def hide_picture(s, owner=None):
        """Back to the text (only owner's picture, if given).  -> whether one went."""
        with s.lock:
            if s.pic is None or (owner is not None and s.pic['owner'] != owner): return False
            s._drop_picture()
        s.title_sent = None; s._send_title(force=True)
        if s.link is not None: s.link.wake()
        return True

    def _drop_picture(s):
        s.pic = None; s.pic_next = None
        s.enc.reset(); s._mark()                # a clear and the whole text again
        s.dirty = True; s.first_dirty = 0.0

    def paste(s, text):
        """Words into the program's input as a paste (bracketed if it asked,
        ?2004), not sent: the user goes on typing."""
        text = ''.join(ch for ch in text if ch.isprintable())   # (no Esc, no Return: never sent, never a key)
        data = text.encode('utf-8')
        if (2004 << 5) in s.screen.mode: data = b'\x1b[200~' + data + b'\x1b[201~'
        s._write(data)

    def picture_lost(s):
        """The GRiD drew its text again (after a DOS program): send the picture again."""
        with s.lock: s.penc.reset()
        if s.link is not None: s.link.wake()

    def click_at(s, x, y):
        """A left click at pixel (x, y) of the GRiD's screen."""
        pic = s.pic
        if pic is not None:
            if y >= PIC.H: return                 # (CLAUDE's band)
            if pic['on_click'] is not None:
                try: pic['on_click'](x, y)
                except Exception as e: s.log('term: picture click: %r' % e)
                return
        s.click(x // 8, y // 16, x, y)

    PTY_PICTURE = 16 * 1024 * 1024              # bytes in a picture file from the pty

    def _osc_picture(s, arg):
        """OSC 5150 from the program in the pty (gridfox only): `show;FLAGS;PATH`
        (an image file in its own folder; FLAGS `invert`, `plain` or empty:
        a light picture is shown dark, as the GRiD draws) or `hide`."""
        if not s.web: return
        try:
            cmd, _, rest = arg.decode('utf-8', 'replace').partition(';')
            if cmd == 'hide':
                s.pty_inv = None; s.hide_picture('pty'); return
            if cmd != 'show': return
            flags, _, path = rest.partition(';')
            path = os.path.realpath(path)
            root = os.path.realpath(s.cwd)
            if os.path.commonpath([path, root]) != root: raise ValueError('not in %s' % root)
            if os.path.getsize(path) > s.PTY_PICTURE: raise ValueError('too big')
            from PIL import Image, ImageStat
            with Image.open(path) as im:
                if im.size[0] * im.size[1] > 16_000_000: raise ValueError('%dx%d is too big' % im.size)
                g = im.convert('L')
            flags = flags.split(',')
            if 'invert' in flags: inv = True
            elif 'plain' in flags: inv = False
            else:                               # (kept while the page's look stays near it: no flicker)
                m = ImageStat.Stat(g).mean[0]
                prev = getattr(s, 'pty_inv', None)
                inv = prev if prev is not None and 90 <= m <= 166 else m > 128
            s.pty_inv = inv
            s.show_picture(PIC.dither(g, invert=inv), 'pty', frame='frame' in flags)
        except Exception as e:
            s.log('term: picture from %s: %s' % (s.name, e))

    def _mark(s):
        if not s.dirty: s.first_dirty = time.monotonic()
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
        if not s.web:
            try:
                if mcp.write_mcp_json(s.cwd, s.sock, getattr(s.cfg, 'auto_mode', ())):
                    s.log('term: registered the GRiD tools in %s/.mcp.json' % s.cwd)
            except (OSError, ValueError) as e:
                s.log('term: .mcp.json left alone: %s' % e)
        m, sl = os.openpty()
        fcntl.ioctl(sl, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        env = dict(os.environ, TERM='xterm-256color', LANG='C.UTF-8', COLUMNS='80', LINES='24')
        env.pop('COLORTERM', None)
        if s.web or not getattr(s.cfg, 'term_api_key', False):
            # Term is for the subscription: a key in gridlink's environment
            # (for the chat) must not make Claude Code bill the API instead
            for k in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'): env.pop(k, None)
        if s.web:
            # gridfox sits beside gridlink (claude-link/gridfox): find it from anywhere
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env['PYTHONPATH'] = os.pathsep.join([here] + [p for p in [env.get('PYTHONPATH')] if p])
            env['GRIDLINK'] = 'web'
            if s.can_picture(): env['GRIDLINK_PICTURES'] = '1'   # (gridfox's picture view: this GRiD can)
            env['PYTHONSAFEPATH'] = '1'       # (3.11+) its folder is not on sys.path at all
        try:
            s.child = subprocess.Popen(resolve(s.command), stdin=sl, stdout=sl, stderr=sl, cwd=s.cwd, env=env,
                                       start_new_session=True, preexec_fn=_ctty, close_fds=True)
        except OSError as e:
            os.close(sl); os.close(m)
            s.child = None; s.exited = -1
            s._message('Can\'t start %s: %s.\r\nInstall %s on the Pi (see the README), '
                       'then press Return.' % (s.command[0], e.strerror or e,
                                               'Firefox and gridfox' if s.web else 'Claude Code'))
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
            # gridfox asks Firefox to quit cleanly (cookies, sign-ins, session
            # store written): give it the time, or Firefox is killed half-way
            try: s.child.terminate(); s.child.wait(STOP_WEB if s.web else 3)
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
            s.hide_picture('pty')                # (gridfox's picture: it can't take it away now)
        try: os.close(fd)
        except OSError: pass
        if mine:
            s.log('term: %s exited (%s)' % (s.name, code))
            why = ' (it lost Firefox)' if s.web and code == 3 else ''
            s._message('%s exited%s (code %s). Press Return to start it again, CODE-Q to leave.'
                       % (s.name, why, code))

    def feed(s, data):
        s.stats['pty_in'] += len(data)
        with s.lock:
            pics = []
            for kind, b in s.pre.parts(data):     # pyte answers DA as it goes: keep the order
                if kind == 'data': s.stream.feed(b)
                elif kind == 'pic': pics.append(b)
                else: s._write(b)
            s.last_byte = time.monotonic(); s._mark()
            s.title = s.screen.title
        for b in pics: s._osc_picture(b)
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
        pic = s.pic
        if pic is not None and any(body[i:i + 2] == b'\x0c\x26' for i in range(0, len(body) - 1, 2)):
            s.picture_lost()                    # (Ctrl-L: the GRiD drew its text again)
        if pic is not None and pic['on_key'] is not None:
            try: body = pic['on_key'](bytes(body))
            except Exception as e: s.log('term: picture key: %r' % e)
            if not body: return
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

    MOUSE_ON = tuple(m << 5 for m in (1000, 1002, 1003))      # (pyte keeps private modes << 5)
    SGR = 1006 << 5
    SGR_PIXELS = 1016 << 5                                     # (xterm: the same reports, in pixels)

    def click(s, col, row, px=None, py=None):
        """A left click on the GRiD's cell (col, row), or pixel (px, py): to
        the program as an xterm's press and release, only if it asked for
        mouse reports (in pixels if it asked for those, ?1016)."""
        if s.fd is None or not (0 <= row < 24 and 0 <= col < 80): return
        mode = s.screen.mode
        if not any(m in mode for m in s.MOUSE_ON): return
        x, y = col + 1, row + 1
        if s.SGR_PIXELS in mode and px is not None:
            s._write(b'\x1b[<0;%d;%dM\x1b[<0;%d;%dm' % (px + 1, py + 1, px + 1, py + 1))
        elif s.SGR in mode:
            s._write(b'\x1b[<0;%d;%dM\x1b[<0;%d;%dm' % (x, y, x, y))
        else:                                   # (the old X10 form: 32 + button, 32 + column, 32 + row)
            s._write(b'\x1b[M' + bytes([32, 32 + x, 32 + y]) + b'\x1b[M' + bytes([35, 32 + x, 32 + y]))

    def _send_title(s, force=False):
        if s.link is None or s.link.source is not s: return
        t = (s.pic or {}).get('title') or fold_title(s.title) or s.name
        now = time.monotonic()
        if t != s.title_sent and (force or now - s.title_t >= TITLE_EVERY):
            s.title_sent = t; s.title_t = now
            s.link.send(glp.P_TITLE, t.encode('latin1', 'replace'))

    def text(s):
        with s.lock: return s.screen.text()
