"""The GRiD's abilities for Claude Code (Term): an MCP server.

Claude Code starts this as a stdio MCP server (gridlink writes it into
~/grid/.mcp.json).  Each tool call goes over a Unix socket to gridlink,
which owns the link and sends it to the GRiD as a GLP REQUEST, one at a
time.  Approvals are Claude Code's own: the read-only tools ask until you
allow them; the ones that change something ask every time.  Pi files are
only ever ones inside ~/grid.

    python3 -I -c '...from gridlink.mcp import main; main()'   (what .mcp.json runs)
"""
import json, os, socket, stat, sys, tempfile, threading, time
from . import glp, keys as K, screen
from .grid import READ_CHUNK, GridError, is_device, is_grid_path, norm

PROTOCOL = '2025-06-18'
PROTOCOLS = ('2025-06-18', '2025-03-26', '2024-11-05')    # what the tools here fit; the newest otherwise
NAME = 'grid'


def socket_path(cfg=None):
    p = os.environ.get('GRIDLINK_SOCKET') or getattr(cfg, 'term_socket', None)
    if p: return os.path.expanduser(p)
    run = os.environ.get('XDG_RUNTIME_DIR')
    return os.path.join(run, 'gridlink.sock') if run else os.path.expanduser('~/.cache/gridlink/gridlink.sock')


# Two kinds of tool.  Read-only ones (readOnlyHint) only look: you can let
# Claude Code run them without asking ("don't ask again", or an allow rule).
# The others change files, run programs or talk to instruments, and carry
# anthropic/requiresUserInteraction, so Claude Code asks every time: it
# offers no "don't ask again" for them and no allow rule skips the question.
LOOK = {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True}
ASK = {'anthropic/requiresUserInteraction': True}

MAX_COPY = 1024 * 1024          # bytes in one copy or write (5 minutes at stock link speed)
MAX_READ = 48 * 1024            # bytes of a file or program output into the conversation
MAX_LINE = 8 * 1024 * 1024      # one request on the socket (1 MB of text, JSON-escaped)
MAX_PATH = 79                   # characters in a GRiD path
MAX_CMD = 100                   # a DOS command line: 125 with ' /C ' and ' >A:\\CLAUDE.OUT' in it
MAX_RUN = 3600                  # seconds the Pi waits for a program (the GRiD itself never stops it)
MAX_GPIB = 4000                 # bytes sent to an instrument (CLAUDE.COM takes 4,700 per request)
MAX_TYPE = 2048                 # a key script for the paused program (resident Claude's console takes 2 KB)
MAX_TYPE_WAIT = 600             # seconds the Pi waits for those keys to play
MAX_PLOT_FILE = 8 * 1024 * 1024 # a data file for grid_plot
MAX_IMAGE_FILE = 20 * 1024 * 1024
MAX_PICK_WAIT = 600             # seconds grid_pick waits for clicks
PICTURE_TOOLS = ('grid_plot', 'grid_image', 'grid_pick')     # no GRiD request: not one at a time

GPIB_PROPS = {
    'address': {'type': 'integer', 'minimum': 0, 'maximum': 30},
    'timeout_ms': {'type': 'integer', 'minimum': 1, 'maximum': 65535,
                   'description': 'Per-byte read timeout (default 2000).'},
    'max_bytes': {'type': 'integer', 'minimum': 1, 'maximum': 15000,
                  'description': 'Largest reply to accept (default 4096).'},
    'save_to': {'type': 'string', 'description': (
        'A new Pi file (in this directory) to put the reply in instead of returning it: for a trace or '
        'a long reading to show with grid_plot. You get its size and first lines.')},
}
RANGE = {'type': 'array', 'items': {'type': 'number'}, 'minItems': 2, 'maxItems': 2}
AXES = {
    'title': {'type': 'string'},
    'x_log': {'type': 'boolean'}, 'y_log': {'type': 'boolean'},
    'x_range': dict(RANGE, description='[low, high] (default: the data\'s).'),
    'y_range': dict(RANGE, description='[low, high] (default: the data\'s).'),
}

TOOLS = [
    {'name': 'grid_info', 'title': 'GRiD: system information',
     'description': "The GRiD's DOS version, drives, free memory, EMS, GPIB driver, current directory and clock.",
     'inputSchema': {'type': 'object', 'properties': {}},
     'annotations': dict(LOOK, title='GRiD: system information')},
    {'name': 'grid_files', 'title': 'GRiD: look at files',
     'description': (
         "Look at files on the GRiD (DOS paths with a drive letter, 8.3 names: A:\\\\TM5000\\\\DATA.TXT). "
         "Read-only. Actions: list (a directory or a wildcard pattern, with sizes and dates), info, read "
         "(a text file of up to 48 KB, CP437 and CR LF turned into Unicode and LF; for a bigger file use "
         "grid_change_files copy_from_grid and your own tools), free (space on the drive). To change "
         "files use grid_change_files."),
     'inputSchema': {'type': 'object', 'properties': {
         'action': {'type': 'string', 'enum': ['list', 'info', 'read', 'free']},
         'path': {'type': 'string'},
     }, 'required': ['action', 'path']},
     'annotations': dict(LOOK, title='GRiD: look at files')},
    {'name': 'grid_screen', 'title': 'GRiD: last screenshot',
     'description': ("The screen of the last DOS program run with screenshot=true or a {SNAP} key: text "
                     "for text modes, an image for graphics."),
     'inputSchema': {'type': 'object', 'properties': {}},
     'annotations': dict(LOOK, title='GRiD: last screenshot')},
    {'name': 'gpib_read', 'title': 'GPIB: read',
     'description': (
         "Read from instruments on the GRiD's GPIB bus without sending them commands (the GRiD is "
         "controller at address 21; the Pi's bridge is on the bus too). Nothing is sent, but a serial "
         "poll clears the instrument's service request (and, on some, latched status bits). Actions: "
         "scan (serial-polls every address, lists the ones that answer), poll (one status byte), read "
         "(the instrument's pending output). To send anything, queries included, use gpib_send."),
     'inputSchema': {'type': 'object', 'properties': dict(
         {'action': {'type': 'string', 'enum': ['scan', 'poll', 'read']}}, **GPIB_PROPS),
         'required': ['action']},
     'annotations': dict(LOOK, idempotentHint=False, title='GPIB: read')},   # (a read empties the instrument's
                                                                              #  output, a poll clears its status)
    {'name': 'grid_command', 'title': 'GRiD: run a DOS program',
     'description': (
         "Run a DOS command line or program on the GRiD 1520 (through COMMAND.COM /C, in the GRiD's "
         "current directory). The user approves every run. With capture=true (default) the program's "
         "text output is redirected to a file and returned (up to 48 KB, then its start and end); use "
         "that for DIR, TYPE, CHKDSK, batch files. Programs that draw their own screen (TM5000G, "
         "editors) need capture=false: drive them with `keys` and look at them with `screenshot`. While "
         "it runs the GRiD shows the program, not this terminal; the user can type into it too. Runs "
         "until the program exits."),
     'inputSchema': {'type': 'object', 'properties': {
         'command': {'type': 'string', 'maxLength': MAX_CMD,
                     'description': 'DOS command line, e.g. "DIR A:\\\\TM5000" or "TM5000G"'},
         'keys': {'type': 'string', 'description': (
             'Keystrokes to type into the program. Plain characters type themselves; named keys in braces: '
             '{ENTER} {ESC} {TAB} {BKSP} {UP} {DOWN} {LEFT} {RIGHT} {HOME} {END} {PGUP} {PGDN} {INS} {DEL} '
             '{F1}..{F10} {ALT+X} {CTRL+X} {SHIFT+F1}; {WAIT 2.5} pauses (seconds, at most 600, all of '
             'them together less than timeout); {SNAP} takes a screenshot then. At most about 2,000 keys. When the script ends the real keyboard '
             'takes over, so end with the keys that quit the program unless the user will.')},
         'capture': {'type': 'boolean', 'description': 'Return the text output (default true).'},
         'screenshot': {'type': 'boolean', 'description': 'Also capture the screen when the program exits.'},
         'timeout': {'type': 'integer', 'minimum': 1, 'maximum': MAX_RUN,
                     'description': ('Seconds to wait for the program (default 900, at most 3600). The '
                                     'program itself goes on until it exits.')},
     }, 'required': ['command']},
     'annotations': {'readOnlyHint': False, 'destructiveHint': True, 'title': 'GRiD: run a DOS program'},
     '_meta': ASK},
    {'name': 'grid_change_files', 'title': 'GRiD: change files',
     'description': (
         "Change files on the GRiD, or copy them between the GRiD and this Pi. The user approves every "
         "call. Actions: write (content as text; written as CP437 with CR LF, through NAME.$$$ so a broken "
         "link can't leave half a file), delete, rename (to = new name), mkdir, rmdir, copy_from_grid "
         "(path = the GRiD file, to = a file in the Pi's ~/grid directory, default its own name there), "
         "copy_to_grid (path = a file in ~/grid on the Pi, to = the GRiD file). Pi files must be inside "
         "~/grid. Copies and writes are at most 1 MB; the link moves roughly 3-7 KB/s. To edit a GRiD "
         "file with your own editing tools: copy_from_grid, edit the copy, copy_to_grid."),
     'inputSchema': {'type': 'object', 'properties': {
         'action': {'type': 'string', 'enum': ['write', 'delete', 'rename', 'mkdir', 'rmdir',
                                               'copy_from_grid', 'copy_to_grid']},
         'path': {'type': 'string'}, 'to': {'type': 'string'}, 'content': {'type': 'string'},
     }, 'required': ['action', 'path']},
     'annotations': {'readOnlyHint': False, 'destructiveHint': True, 'title': 'GRiD: change files'},
     '_meta': ASK},
    {'name': 'gpib_send', 'title': 'GPIB: send to an instrument',
     'description': (
         "Send to an instrument on the GRiD's GPIB bus. The user approves every call: power supplies "
         "and sources drive real circuits, so never change their outputs unless asked. Actions: query "
         "(send a command, read the reply), write, clear (device clear), trigger (GET), local, remote. "
         "Commands get CR LF and EOI unless terminator says otherwise."),
     'inputSchema': {'type': 'object', 'properties': dict(
         {'action': {'type': 'string', 'enum': ['query', 'write', 'clear', 'trigger', 'local', 'remote']},
          'command': {'type': 'string', 'maxLength': MAX_GPIB},
          'terminator': {'type': 'string', 'enum': ['crlf', 'lf', 'none']}}, **GPIB_PROPS),
         'required': ['action', 'address']},
     'annotations': {'readOnlyHint': False, 'destructiveHint': True, 'title': 'GPIB: send to an instrument'},
     '_meta': ASK},
    # pictures on the GRiD's screen (CLAUDE.COM 1.2, Term): plotview.py
    {'name': 'grid_plot', 'title': 'GRiD: show a plot',
     'description': (
         "Show a line or scatter plot on the GRiD's screen (640x384, one bit, in its own font), over this "
         "terminal until the user presses Esc; Claude Code goes on underneath. Data inline (series) or from "
         "a Pi file in this directory: CSV or numbers separated by spaces (e.g. a trace saved with gpib_read's "
         "save_to), or JSON (a list of series). The user can click the plot: a click types the point (data "
         "coordinates and the nearest point) into your prompt for them to add to. To have them point at "
         "something for you, show the plot, then call grid_pick. You get the picture the GRiD shows."),
     'inputSchema': {'type': 'object', 'properties': dict({
         'series': {'type': 'array', 'maxItems': 8, 'items': {'type': 'object', 'properties': {
             'name': {'type': 'string'},
             'x': {'type': 'array', 'items': {'type': 'number'}, 'description': 'Default: 0, 1, 2, ...'},
             'y': {'type': 'array', 'items': {'type': 'number'}},
             'style': {'type': 'string', 'enum': ['line', 'points', 'both']}}, 'required': ['y']}},
         'file': {'type': 'string', 'description': 'A data file instead of series.'},
         'x_column': {'type': 'integer', 'minimum': 0, 'description': (
             "The file's x column (1 = the first, the default for two or more columns); 0: none, the points "
             "are evenly spaced (over x_span).")},
         'columns': {'type': 'array', 'items': {'type': 'integer', 'minimum': 1},
                     'description': "The file's y columns (default: all but x)."},
         'x_span': dict(RANGE, description=(
             'Data without x (no x in a series, or x_column 0): the first and last points\' x, e.g. an '
             'instrument\'s start and stop frequency.')),
         'style': {'type': 'string', 'enum': ['line', 'points', 'both'], 'description': "The file's series."},
         'x_label': {'type': 'string'}, 'y_label': {'type': 'string'}}, **AXES)},
     'annotations': dict(LOOK, title='GRiD: show a plot')},
    {'name': 'grid_image', 'title': 'GRiD: show a picture',
     'description': (
         "Show a picture file from this directory (PNG, JPEG, GIF, BMP: a matplotlib plot you saved, a "
         "screenshot) on the GRiD's screen, scaled to fit 640x384 and dithered to one bit, until the user "
         "presses Esc. A mostly white picture is inverted (lit lines on dark, as the GRiD draws) unless "
         "invert says otherwise. With plot_area and the axis ranges, clicks map to data coordinates. Clicks "
         "type into your prompt, or use grid_pick. You get the picture the GRiD shows."),
     'inputSchema': {'type': 'object', 'properties': dict({
         'path': {'type': 'string'},
         'invert': {'type': 'boolean'},
         'plot_area': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4,
                       'description': ("The plot's axes box in the picture's own pixels: [left, top, right, "
                                       "bottom], where x_range and y_range's ends are.")}}, **AXES),
         'required': ['path']},
     'annotations': dict(LOOK, title='GRiD: show a picture')},
    {'name': 'grid_pick', 'title': 'GRiD: the user clicks points',
     'description': (
         "Ask the user to click points on the plot or picture you showed last (grid_plot, grid_image; it is "
         "shown again if they went back), and wait for the clicks: their data coordinates and, on a plot, "
         "the nearest data point. The prompt is shown in the GRiD's band (keep it short: 'click the "
         "notch'). Esc on the GRiD cancels."),
     'inputSchema': {'type': 'object', 'properties': {
         'prompt': {'type': 'string', 'maxLength': 44},
         'count': {'type': 'integer', 'minimum': 1, 'maximum': 10, 'description': 'Clicks to wait for (default 1).'},
         'timeout': {'type': 'integer', 'minimum': 5, 'maximum': MAX_PICK_WAIT,
                     'description': 'Seconds to wait (default 120).'}}},
     'annotations': dict(LOOK, idempotentHint=False, title='GRiD: the user clicks points')},
    # resident Claude (CLAUDE /R): Claude Code popped up over a DOS program
    {'name': 'grid_program', 'title': 'GRiD: the paused program',
     'description': (
         "The DOS program that resident Claude's console (CLAUDE /R, CODE-\\) is popped up over, e.g. "
         "TM5000G: its name and its screen as the user left it (text for text modes, an image for "
         "graphics). Only while Claude Code is in that console; the other GRiD tools wait until the "
         "user leaves the program."),
     'inputSchema': {'type': 'object', 'properties': {}},
     'annotations': dict(LOOK, title='GRiD: the paused program')},
    {'name': 'grid_type', 'title': 'GRiD: type into the paused program',
     'description': (
         "Type keys into the DOS program that resident Claude's console is popped up over. The user "
         "approves every call. The console goes away while the keys play, so the user sees the program "
         "take them; then it comes back, and you get the program's screen. The user can stop the keys "
         "with CODE-\\. End with a {WAIT} long enough for the program to finish what the keys started "
         "(drawing a menu, a measurement). If the keys quit the program, the rest go to whatever runs "
         "next (the DOS prompt or the Executive)."),
     'inputSchema': {'type': 'object', 'properties': {
         'keys': {'type': 'string', 'description': (
             'Plain characters type themselves; named keys in braces: {ENTER} {ESC} {TAB} {BKSP} {UP} {DOWN} '
             '{LEFT} {RIGHT} {HOME} {END} {PGUP} {PGDN} {INS} {DEL} {F1}..{F10} {ALT+X} {CTRL+X} {SHIFT+F1}; '
             '{WAIT 1.5} pauses (seconds). At most about 1,000 keys.')},
         'timeout': {'type': 'integer', 'minimum': 1, 'maximum': MAX_TYPE_WAIT,
                     'description': ('Seconds to wait for the keys to play and the program to wait for a '
                                     'key again (default 60).')},
     }, 'required': ['keys']},
     'annotations': {'readOnlyHint': False, 'destructiveHint': True,
                     'title': 'GRiD: type into the paused program'},
     '_meta': ASK},
]


def text(t): return {'type': 'text', 'text': t}


def snap_marks(kb):
    """Where a compiled key script has {SNAP} marks (FF FE xx), walking its
    items: keys (2 bytes), waits (FF FF n) and marks (3 bytes)."""
    i, out = 0, []
    while i < len(kb):
        if kb[i] == 0xFF and i + 1 < len(kb) and kb[i + 1] in (0xFF, 0xFE):
            if kb[i + 1] == 0xFE: out.append(i)
            i += 3
        else:
            i += 2
    return out


# ---- Pi files: only in the Term directory (~/grid) ----------------------
PROTECTED = ('claude.md', 'claude.local.md')       # Claude Code's memory files


def pi_path(root, p):
    """A Pi path for the copies, resolved (symlinks too) and checked: inside
    root, no dot-names on the way (Claude Code's .claude settings,
    .mcp.json) and not CLAUDE.md.  ValueError otherwise."""
    if not isinstance(p, str) or not p.strip() or '\0' in p:
        raise ValueError('a Pi path is required')
    root = os.path.realpath(os.path.expanduser(root))
    full = os.path.realpath(os.path.join(root, os.path.expanduser(p.strip())))
    if full == root or os.path.commonpath([root, full]) != root:
        raise ValueError('Pi files must be inside %s, not %s' % (root, full))
    parts = os.path.relpath(full, root).split(os.sep)
    if any(x.startswith('.') for x in parts) or parts[-1].lower() in PROTECTED:
        raise ValueError('%s is a settings file: not with this tool' % full)
    return full


def read_pi(path, cap):
    """A regular file's bytes, at most cap.  O_NONBLOCK so a FIFO can't
    hang us; one link only, so a hard link into ~/grid can't carry a file
    from elsewhere out."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode): raise ValueError('%s is not a regular file' % path)
        if st.st_nlink > 1: raise ValueError('%s has other hard links; copy it to a new file first' % path)
        if st.st_size > cap: raise ValueError('%s is %d bytes; the most is %d' % (path, st.st_size, cap))
        data = bytearray()
        while len(data) <= cap:
            b = os.read(fd, min(65536, cap + 1 - len(data)))
            if not b: break
            data += b
        if len(data) > cap: raise ValueError('%s grew past %d bytes' % (path, cap))
        return bytes(data)
    finally:
        os.close(fd)


def write_pi(path, data):
    """Through a temporary file and a rename, so a symlink or hard link
    already at that name is replaced, never written through."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.grid-')
    try:
        with os.fdopen(fd, 'wb') as f: f.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def to_dos(t):
    from .tools import to_cp437
    return to_cp437(t.replace('\r\n', '\n').replace('\n', '\r\n'))


def from_dos(raw):
    return raw.decode('cp437').replace('\r\n', '\n').replace('\x1a', '')


# ---- arguments: checked here, whatever the schema said -------------------
def arg_str(a, k, need=False, most=None):
    v = a.get(k)
    if v is None or v == '':
        if need: raise ValueError('%s is required' % k)
        return ''
    if not isinstance(v, str): raise ValueError('%s must be a string' % k)
    if most is not None and len(v) > most: raise ValueError('%s is longer than %d characters' % (k, most))
    return v


def arg_int(a, k, default, lo, hi):
    v = a.get(k)
    if v is None: return default
    if isinstance(v, float) and v.is_integer(): v = int(v)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValueError('%s must be a whole number from %d to %d' % (k, lo, hi))
    return v


def arg_bool(a, k, default):
    v = a.get(k)
    if v is None: return default
    if not isinstance(v, bool): raise ValueError('%s must be true or false' % k)
    return v


def dos_text(s, what):
    """Text the GRiD gets as an ASCIIZ string: CP437, no control characters
    (CLAUDE.COM would cut it at a NUL; a CR ends a DOS command line)."""
    if any(ord(c) < 32 for c in s): raise ValueError('%s has control characters' % what)
    try: s.encode('cp437')
    except UnicodeEncodeError: raise ValueError('%s has characters DOS cannot hold' % what)
    return s


def grid_path(a, k='path', wild=False):
    p = arg_str(a, k, need=True).strip()
    if not is_grid_path(p) or not 'A' <= p[0].upper() <= 'Z':
        raise ValueError('%s must be a GRiD path like A:\\NAME.EXT' % k)
    p = dos_text(norm(p), k)
    if len(p) > MAX_PATH: raise ValueError('%s is longer than %d characters' % (k, MAX_PATH))
    if not wild and any(c in p for c in '*?'): raise ValueError('%s: wildcards only for list' % k)
    if is_device(p): raise ValueError('%s is a DOS device (CON, AUX, COM1...), not a file' % p)
    return p


class GridTools:
    """The tools, on gridlink's side of the socket (a Grid to call).  Pi
    paths are kept inside root, the Term directory."""
    def __init__(s, grid, cfg=None, bridge=7, root=None, hello=lambda: {}, viewer=None):
        s.G = grid; s.cfg = cfg; s.bridge = bridge
        s.root = root or getattr(cfg, 'term_dir', None) or '~/grid'
        s.hello = hello                     # the GRiD's last HELLO (the paused program's name)
        s.viewer = viewer                   # plotview.Viewer: pictures on the GRiD's screen

    def call(s, name, a):
        try:
            fn = getattr(s, 't_' + name, None) if name in NAMES else None
            if fn is None: return [text('Unknown tool %s' % name)], True
            return fn(a)
        except GridError as e:
            return [text('GRiD: %s' % e)], True
        except (K.KeyError_, ValueError, OSError) as e:
            return [text('Error: %s' % e)], True

    # ---- read-only -----------------------------------------------------
    def t_grid_info(s, a):
        info = s.G.get_info()
        return [text('\n'.join('%s: %s' % kv for kv in info.items()))], False

    def snapshot(s, raw=None):
        snap = screen.parse(s.G.screen(0) if raw is None else raw)
        if screen.is_text(snap):
            return [text('Screen (%s):\n%s' % (screen.describe(snap), screen.text(snap)))]
        png = screen.png_block(snap)['source']['data']
        return [text('Screenshot: %s' % screen.describe(snap)),
                {'type': 'image', 'data': png, 'mimeType': 'image/png'}]

    def t_grid_screen(s, a):
        return s.snapshot(), False

    # ---- resident Claude: the program its console is popped up over --------
    def program(s):
        return (s.hello() or {}).get('prog') or 'the program'

    def t_grid_program(s, a):
        name = (s.hello() or {}).get('prog')
        head = ('%s is paused under resident Claude\'s console.' % name if name else
                'A DOS program is paused under resident Claude\'s console (its name isn\'t known).')
        return [text(head)] + s.snapshot(), False

    def t_grid_type(s, a):
        timeout = arg_int(a, 'timeout', 60, 1, MAX_TYPE_WAIT)
        kbytes = K.compile_script(arg_str(a, 'keys', need=True))
        marks = snap_marks(kbytes)
        if marks and marks[-1] == len(kbytes) - 3:          # (the screen comes at the end anyway)
            kbytes = kbytes[:-3]; marks.pop()
        if marks: raise ValueError('{SNAP} can only end the keys: grid_type takes the screen when they are done')
        if not kbytes: raise ValueError('no keys')
        if len(kbytes) > MAX_TYPE:
            raise ValueError('the keys come to %d bytes; the console takes %d (about %d keys)'
                             % (len(kbytes), MAX_TYPE, MAX_TYPE // 2))
        if K.script_seconds(kbytes) >= timeout:
            raise ValueError('the keys wait %.0f s in all, not less than timeout (%d s)'
                             % (K.script_seconds(kbytes), timeout))
        played, raw = s.G.type_keys(kbytes, timeout=timeout + 10)
        name = s.program()
        head = ('Typed into %s.' % name if played else
                'The user stopped the keys (CODE-\\) before all of them were typed into %s.' % name)
        if raw is None:
            return [text(head + ' No screenshot: its video mode isn\'t one the console keeps.')], False
        return [text(head)] + s.snapshot(raw), False

    def t_grid_files(s, a):
        G = s.G; act = a.get('action')
        if act not in ('list', 'info', 'read', 'free'):
            return [text('Error: grid_files only looks (list, info, read, free); '
                         'grid_change_files changes files')], True
        path = grid_path(a, wild=act == 'list')
        if act == 'list':
            pat = path if any(c in path for c in '*?') else path.rstrip('\\') + '\\*.*'
            ents = G.dir(pat)
            lines = ['%-12s %10s  %s %s' % (e['name'], '<DIR>' if e['dir'] else e['size'], e['date'], e['time'])
                     for e in ents]
            return [text('%s\n%s' % (pat, '\n'.join(lines) or '(empty)'))], False
        if act == 'info':
            st = G.stat(path)
            return [text('%s: %s, modified %s %s, attributes %02Xh' % (
                path, 'directory' if st['dir'] else '%d bytes' % st['size'], st['date'], st['time'], st['attr']))], False
        if act == 'read':
            return [text(from_dos(s.whole(path, MAX_READ, 'read returns',
                                          'copy it to the Pi with grid_change_files copy_from_grid')))], False
        fb, tb = G.free(ord(path[0]) - 64)
        return [text('%s %d bytes free of %d' % (path[:2], fb, tb))], False

    def whole(s, path, cap, says, instead):
        """A whole GRiD file, never part of one: too big is an error."""
        st = s.G.stat(path)
        if st['dir']: raise ValueError('%s is a directory' % path)
        if st['size'] > cap:
            raise ValueError('%s is %d bytes; %s at most %d: %s' % (path, st['size'], says, cap, instead))
        data = s.G.read_file(path, limit=cap + 1)
        if len(data) > cap: raise ValueError('%s grew past %d bytes while it was read' % (path, cap))
        return data

    def t_gpib_read(s, a):
        act = a.get('action')
        if act not in ('scan', 'poll', 'read'):
            return [text('Error: gpib_read only reads (scan, poll, read); gpib_send sends')], True
        addr, tmo, maxb = s.gpib_args(a, need_addr=act != 'scan')
        G = s.G
        if act == 'scan':
            found = list(G.gpib(glp.GP_SCAN, 0, timeout_ms=tmo))
            return [text('Responding addresses: %s' % (', '.join(map(str, found)) or 'none'))], False
        if act == 'poll':
            r = G.gpib(glp.GP_SPOLL, addr, timeout_ms=tmo); v = r[0] if r else 0
            return [text('Status byte %02Xh (%s)' % (v, format(v, '08b')))], False
        r = G.gpib(glp.GP_READ, addr, timeout_ms=tmo, maxlen=maxb)
        return s.reply(a, r)

    def reply(s, a, r):
        """An instrument's reply: returned, or into a Pi file (save_to)."""
        to = arg_str(a, 'save_to')
        if not to: return [text(r.decode('latin1').rstrip('\r\n') or '(empty reply)')], False
        path = pi_path(s.root, to)
        if os.path.lexists(path): raise ValueError('%s is there already: save_to makes a new file' % path)
        write_pi(path, bytes(r))
        lines = r.decode('latin1').splitlines()
        head = '\n'.join(l[:200] for l in lines[:3])
        return [text('%d bytes (%d lines) saved to %s. It begins:\n%s' % (len(r), len(lines), path, head))], False

    def gpib_args(s, a, need_addr=True):
        addr = arg_int(a, 'address', None, 0, 30)
        if addr is None and need_addr: raise ValueError('address is required')
        if addr in (21, s.bridge): raise ValueError('%d is the GRiD or the bridge, not an instrument' % addr)
        return addr, arg_int(a, 'timeout_ms', 2000, 1, 65535), arg_int(a, 'max_bytes', 4096, 1, 15000)

    # ---- the user approves every call ------------------------------------
    def t_grid_command(s, a):
        command = dos_text(arg_str(a, 'command', need=True, most=MAX_CMD).strip(), 'command')
        if not command: raise ValueError('command is required')
        capture = arg_bool(a, 'capture', True); shot = arg_bool(a, 'screenshot', False)
        timeout = arg_int(a, 'timeout', 900, 1, MAX_RUN)
        script = arg_str(a, 'keys')
        kbytes = K.compile_script(script) if script else b''
        if K.script_seconds(kbytes) >= timeout:
            raise ValueError('the key script waits %.0f s in all, not less than timeout (%d s)'
                             % (K.script_seconds(kbytes), timeout))
        r = s.G.run(command, capture=capture, snapshot=shot or b'\xff\xfe' in kbytes, keys=kbytes, timeout=timeout)
        msg = 'Exit code: %d' % r['exit']
        if capture:
            t = ''
            if r['output'] and r['outfile']:
                try: t = s.output(r['outfile'])
                finally:
                    try: s.G.delete(r['outfile'])
                    except GridError: pass
            msg += '\nOutput:\n' + (t or '(no output)')
        out = [text(msg)]
        if r['snapshot']: out += s.snapshot()
        elif shot: out.append(text('No screenshot was taken.'))
        return out, False

    def output(s, name):
        """A program's output: all of it up to MAX_READ, else its start and
        its end with how much is left out between them."""
        G = s.G
        raw = G.read_file(name, limit=MAX_READ + 1)
        if len(raw) <= MAX_READ: return from_dos(raw).strip('\n')
        size = G.stat(name)['size']
        tail = G.read(name, max(0, size - READ_CHUNK), READ_CHUNK)
        head = raw[:MAX_READ - READ_CHUNK]
        return '%s\n[... %d bytes of output not shown ...]\n%s' % (
            from_dos(head), size - len(head) - len(tail), from_dos(tail).strip('\n'))

    def t_grid_change_files(s, a):
        G = s.G; act = a.get('action')
        if act == 'copy_to_grid':
            src = pi_path(s.root, a.get('path'))
            to = grid_path(a, 'to')
            data = read_pi(src, MAX_COPY)
            G.write_file_safe(to, data)
            return [text('Copied %s (%d bytes) to %s' % (src, len(data), to))], False
        path = grid_path(a)
        if act == 'copy_from_grid':
            name = path.rpartition('\\')[2]
            dest = pi_path(s.root, arg_str(a, 'to') or name)
            if os.path.isdir(dest): dest = pi_path(s.root, os.path.join(dest, name))
            data = s.whole(path, MAX_COPY, 'a copy is', 'too big for the link')
            write_pi(dest, data)
            return [text('Copied %s (%d bytes) to %s' % (path, len(data), dest))], False
        if act == 'write':
            data = to_dos(arg_str(a, 'content'))
            if len(data) > MAX_COPY: raise ValueError('content is %d bytes; the most is %d' % (len(data), MAX_COPY))
            G.write_file_safe(path, data)
            return [text('Wrote %s (%d bytes)' % (path, len(data)))], False
        if act == 'delete':
            G.delete(path); return [text('Deleted %s' % path)], False
        if act == 'rename':
            to = arg_str(a, 'to', need=True).strip()
            if not is_grid_path(to) and '\\' not in to: to = path.rpartition('\\')[0] + '\\' + to
            to = grid_path({'to': to}, 'to')
            G.rename(path, to); return [text('Renamed %s to %s' % (path, to))], False
        if act == 'mkdir':
            G.mkdir(path); return [text('Created directory %s' % path)], False
        if act == 'rmdir':
            G.rmdir(path); return [text('Removed directory %s' % path)], False
        return [text('Error: unknown action %s' % act)], True

    def t_gpib_send(s, a):
        act = a.get('action')
        ops = {'clear': glp.GP_CLEAR, 'trigger': glp.GP_TRIGGER, 'local': glp.GP_LOCAL, 'remote': glp.GP_REMOTE}
        if act not in ('query', 'write') and act not in ops:
            return [text('Error: unknown action %s' % act)], True
        addr, tmo, maxb = s.gpib_args(a)
        G = s.G
        if act in ops:
            G.gpib(ops[act], addr, timeout_ms=tmo)
            return [text('%s sent to %d' % (act, addr))], False
        t = a.get('terminator', 'crlf')
        term = {'crlf': b'\r\n', 'lf': b'\n', 'none': b''}.get(t) if isinstance(t, str) or t is None else None
        if t is None: term = b'\r\n'
        if term is None: raise ValueError('terminator must be crlf, lf or none')
        cmd = arg_str(a, 'command', need=True, most=MAX_GPIB)
        try: data = cmd.encode('latin1') + term
        except UnicodeEncodeError: raise ValueError('command must be Latin-1 text')
        if act == 'query':
            r = G.gpib(glp.GP_QUERY, addr, data, timeout_ms=tmo, maxlen=maxb)
            return s.reply(a, r)
        G.gpib(glp.GP_WRITE, addr, data, flags=1, timeout_ms=tmo)
        return [text('Sent to %d' % addr)], False


    # ---- pictures on the GRiD's screen: no GRiD request, not one at a time --
    def picture_args(s, a):
        return dict(title=arg_str(a, 'title', most=200), x_log=arg_bool(a, 'x_log', False),
                    y_log=arg_bool(a, 'y_log', False), x_range=a.get('x_range'), y_range=a.get('y_range'))

    def shown(s, view, what):
        """view up on the GRiD -> the tool's answer, with the picture as the GRiD shows it."""
        if s.viewer is None: return [text('Pictures need Term (CLAUDE /T) with CLAUDE.COM 1.2 or later.')], True
        try: s.viewer.show(view)
        except RuntimeError as e: return [text(str(e))], True
        return [text(what + ' Clicks on it go into your prompt; Esc on the GRiD goes back to this terminal.'),
                picture_block(view.bits)], False

    def t_grid_plot(s, a):
        from . import plot as PL
        kw = s.picture_args(a)
        series = a.get('series'); f = arg_str(a, 'file')
        if (series is None) == (not f): raise ValueError('give series or file (one of them)')
        span = PL._range(a.get('x_span'), 'x_span', False) if a.get('x_span') is not None else None
        if f:
            data = read_pi(pi_path(s.root, f), MAX_PLOT_FILE).decode('utf-8', 'replace')
            series = PL.series_from_file(data, arg_int(a, 'x_column', None, 0, 999), a.get('columns'),
                                         a.get('style'))
        if span is not None:
            for sr in series if isinstance(series, list) else []:
                if isinstance(sr, dict) and sr.get('x') is None and isinstance(sr.get('y'), list):
                    n = len(sr['y'])
                    sr['x'] = [span[0] + (span[1] - span[0]) * k / max(1, n - 1) for k in range(n)]
        p = PL.Plot(series, x_label=arg_str(a, 'x_label', most=200), y_label=arg_str(a, 'y_label', most=200), **kw)
        n = sum(len(sr['y']) for sr in p.series)
        return s.shown(p, 'Shown on the GRiD: %d series, %d points; x %s to %s, y %s to %s.' % (
            len(p.series), n, PL.num(p.xr[0]), PL.num(p.xr[1]), PL.num(p.yr[0]), PL.num(p.yr[1])))

    def t_grid_image(s, a):
        from PIL import Image
        import io
        from . import plot as PL
        path = pi_path(s.root, arg_str(a, 'path', need=True))
        im = Image.open(io.BytesIO(read_pi(path, MAX_IMAGE_FILE)))
        if im.size[0] * im.size[1] > 40_000_000: raise ValueError('%s is too big (%dx%d)' % ((path,) + im.size))
        inv = a.get('invert')
        if inv is not None and not isinstance(inv, bool): raise ValueError('invert must be true or false')
        kw = s.picture_args(a)
        v = PL.ImageView(im, invert=inv, plot_area=a.get('plot_area'), **kw)
        return s.shown(v, 'Shown on the GRiD: %s (%dx%d%s%s).' % (
            os.path.basename(path), im.size[0], im.size[1], ', inverted' if v.inverted else '',
            ', clicks map to data' if v.ax is not None else ''))

    def t_grid_pick(s, a):
        from . import plot as PL
        if s.viewer is None: return [text('Pictures need Term (CLAUDE /T) with CLAUDE.COM 1.2 or later.')], True
        prompt = arg_str(a, 'prompt', most=44)
        count = arg_int(a, 'count', 1, 1, 10)
        tmo = arg_int(a, 'timeout', 120, 5, MAX_PICK_WAIT)
        try: got, why = s.viewer.pick(prompt, count, tmo)
        except RuntimeError as e: return [text(str(e))], True
        lines = []
        for i, c in enumerate(got):
            l = '%d: ' % (i + 1)
            if c['x'] is not None: l += 'x = %s, y = %s' % (PL.num(c['x']), PL.num(c['y']))
            elif c.get('image_pixel'): l += 'pixel (%d, %d) of the picture' % tuple(c['image_pixel'])
            else: l += 'outside the plot'
            n = c['nearest']
            if n is not None:
                l += '; nearest point: %s #%d (x = %s, y = %s)' % (n['series'], n['index'], PL.num(n['x']), PL.num(n['y']))
            lines.append(l)
        head = ('%d click%s' % (len(got), '' if len(got) == 1 else 's')) if got else 'No clicks'
        if why: head += ' (%s)' % why
        return [text(head + ('.\n' + '\n'.join(lines) if lines else '.'))], not got


def picture_block(bits):
    """A picture as the GRiD shows it (lit amber on dark), for Claude."""
    import base64, io
    from PIL import Image
    im = Image.frombytes('1', (640, 384), bytes(bits)).convert('L').point(lambda v: 0xD8 if v else 0x10)
    out = io.BytesIO(); im.save(out, 'PNG', optimize=True)
    return {'type': 'image', 'data': base64.b64encode(out.getvalue()).decode(), 'mimeType': 'image/png'}


NAMES = {t['name'] for t in TOOLS}


class ToolServer:
    """gridlink's end: a Unix socket; one JSON request per connection
    ({"tool", "arguments"} -> {"content", "isError"}), one GRiD request at a
    time (CLAUDE.COM runs one REQUEST at a time)."""
    def __init__(s, path, tools, available=lambda tool: None, log=print):
        s.path, s.tools, s.available, s.log = path, tools, available, log
        s.lock = threading.Lock(); s.sock = None

    def start(s):
        os.makedirs(os.path.dirname(s.path), mode=0o700, exist_ok=True)
        try: os.unlink(s.path)
        except FileNotFoundError: pass
        s.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o077)                     # only this user, from the start
        try: s.sock.bind(s.path)
        finally: os.umask(old)
        s.sock.listen(8)
        threading.Thread(target=s._accept, daemon=True, name='mcp-socket').start()
        return s

    def _accept(s):
        while True:
            try: c, _ = s.sock.accept()
            except OSError: return
            threading.Thread(target=s._serve, args=(c,), daemon=True).start()

    def _serve(s, c):
        with c:
            try:
                c.settimeout(30)                  # the request comes at once
                f = c.makefile('rwb')
                line = f.readline(MAX_LINE + 1)
                c.settimeout(None)                # the answer takes what the GRiD takes
                res = s.request(line)
                f.write(json.dumps({'content': res[0], 'isError': bool(res[1])}).encode() + b'\n'); f.flush()
            except Exception as e:                # the client went away
                s.log('mcp: %r' % e)

    def request(s, line):
        try:
            if len(line) > MAX_LINE or not line.endswith(b'\n'):
                return [text('gridlink: request too large or cut short')], True
            req = json.loads(line.decode('utf-8', 'replace'))
            if not isinstance(req, dict): raise ValueError('not an object')
            tool = req.get('tool'); args = req.get('arguments')
            if args is None: args = {}
            if not isinstance(tool, str) or not isinstance(args, dict):
                return [text('gridlink: a request needs a tool name and an arguments object')], True
            with s.lock:                          # (a RUN going on keeps the GRiD from polling:
                why = s.available(tool)           # wait for it, don't call that "not connected")
                if why: return [text(why)], True
                if tool not in PICTURE_TOOLS: return s.tools.call(tool, args)
            return s.tools.call(tool, args)       # (grid_pick waits for the user, not the GRiD)
        except Exception as e:
            s.log('mcp: %r' % e); return [text('gridlink: %s' % e)], True

    def stop(s):
        if s.sock: s.sock.close()
        try: os.unlink(s.path)
        except OSError: pass


# Isolated (-I): not `python -m`, which puts Claude Code's directory (~/grid,
# where it may write files) first on sys.path, so a json.py there would run.
LAUNCH = 'import sys; sys.path.insert(0, %r); from gridlink.mcp import main; main()'


def write_mcp_json(directory, sock):
    """Register this server in Claude Code's project file, keeping any others.
    A file that doesn't read as JSON is left alone (ValueError)."""
    p = os.path.join(directory, '.mcp.json')
    try:
        with open(p) as f: d = json.load(f)
    except FileNotFoundError:
        d = {}
    except ValueError as e:
        raise ValueError('%s is not valid JSON (%s); add the grid server by hand' % (p, e))
    if not isinstance(d, dict): raise ValueError('%s is not a JSON object' % p)
    servers = d.get('mcpServers')
    if not isinstance(servers, dict): servers = d['mcpServers'] = {}
    pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entry = {'type': 'stdio', 'command': sys.executable, 'args': ['-I', '-c', LAUNCH % pkg],
             'env': {'GRIDLINK_SOCKET': sock}}
    if servers.get(NAME) == entry: return False
    servers[NAME] = entry
    os.makedirs(directory, exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w') as f: json.dump(d, f, indent=2); f.write('\n')
    os.replace(tmp, p)
    return True


# ---- the stdio MCP server (Claude Code's end) ---------------------------
def local_paths(tool, args):
    """Pi paths are Claude Code's: relative ones are made absolute here, in
    its directory, before gridlink (elsewhere) sees them.  gridlink checks
    them against ~/grid."""
    if tool in ('grid_plot', 'grid_image') and isinstance(args, dict):
        k = 'file' if tool == 'grid_plot' else 'path'
        if isinstance(args.get(k), str) and args[k]:
            return dict(args, **{k: os.path.abspath(os.path.expanduser(args[k]))})
    if tool in ('gpib_read', 'gpib_send') and isinstance(args, dict) and isinstance(args.get('save_to'), str) \
            and args['save_to']:
        return dict(args, save_to=os.path.abspath(os.path.expanduser(args['save_to'])))
    if tool != 'grid_change_files' or not isinstance(args, dict): return args
    a = dict(args); act = a.get('action')
    if act == 'copy_to_grid' and isinstance(a.get('path'), str) and a['path']:
        a['path'] = os.path.abspath(os.path.expanduser(a['path']))
    if act == 'copy_from_grid' and isinstance(a.get('path'), str):
        to = a.get('to') or a['path'].replace('/', '\\').rpartition('\\')[2]
        if isinstance(to, str) and to: a['to'] = os.path.abspath(os.path.expanduser(to))
    return a


def call_gridlink(sock, tool, args):
    """No timeout here: gridlink bounds every GRiD call itself."""
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.connect(sock)
    except OSError:
        return {'content': [text('gridlink is not running on this Pi (or not in Term mode yet).')], 'isError': True}
    try:
        with c:
            c.sendall(json.dumps({'tool': tool, 'arguments': local_paths(tool, args)}).encode() + b'\n')
            line = c.makefile('rb').readline()
        return json.loads(line)
    except (OSError, ValueError):
        return {'content': [text('gridlink closed the connection.')], 'isError': True}


def rpc_error(mid, code, message):
    return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': code, 'message': message}}


def handle(msg, sock):
    """One JSON-RPC message -> the response (or None for a notification)."""
    mid = msg.get('id'); method = msg.get('method')
    if mid is None: return None
    p = msg.get('params')
    if p is None: p = {}
    if not isinstance(p, dict): return rpc_error(mid, -32602, 'params must be an object')
    if method == 'initialize':
        v = p.get('protocolVersion')
        if v not in PROTOCOLS: v = PROTOCOL                      # (the client decides whether it can go on)
        res = {'protocolVersion': v, 'capabilities': {'tools': {}},
               'serverInfo': {'name': 'gridlink', 'version': '1.1'},
               'instructions': ('Tools for the GRiD 1520 this terminal runs on: its files, DOS programs '
                                '(with keystrokes and screenshots) and the GPIB bus it controls.')}
    elif method == 'ping':
        res = {}
    elif method == 'tools/list':
        res = {'tools': TOOLS}
    elif method == 'tools/call':
        name = p.get('name'); args = p.get('arguments')
        if args is None: args = {}
        if not isinstance(name, str) or not isinstance(args, dict):
            return rpc_error(mid, -32602, 'tools/call needs a tool name and an arguments object')
        res = call_gridlink(sock, name, args)
    else:
        return rpc_error(mid, -32601, 'no method %s' % method)
    return {'jsonrpc': '2.0', 'id': mid, 'result': res}


def respond(line, sock):
    """One line from Claude Code -> the responses.  Nothing in it may stop
    the server: a bad message gets a JSON-RPC error and the next one is read."""
    try: msg = json.loads(line.decode('utf-8', 'replace'))
    except (ValueError, RecursionError):
        return [rpc_error(None, -32700, 'parse error')]
    out = []
    for m in (msg if isinstance(msg, list) else [msg]):
        if not isinstance(m, dict):
            out.append(rpc_error(None, -32600, 'invalid request')); continue
        try: r = handle(m, sock)
        except Exception as e:
            mid = m.get('id')
            r = None if mid is None else rpc_error(mid, -32603, 'internal error: %s' % e)
        if r is not None: out.append(r)
    return out


def main():
    sock = socket_path()
    out = sys.stdout
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line: continue
        for r in respond(line, sock):
            out.write(json.dumps(r) + '\n'); out.flush()


if __name__ == '__main__':
    main()
