"""The GRiD's abilities for Claude Code (Term): an MCP server.

Claude Code starts this as a stdio MCP server (gridlink writes it into
~/grid/.mcp.json).  Each tool call goes over a Unix socket to gridlink,
which owns the link and sends it to the GRiD as a GLP REQUEST, one at a
time.  Approvals are Claude Code's own: it asks before an MCP tool runs
unless you have allowed it.

    python3 -m gridlink.mcp            (what .mcp.json runs)
"""
import base64, json, os, socket, struct, sys, threading, time
from . import glp, keys as K, screen
from .grid import GridError, is_grid_path, norm

PROTOCOL = '2025-06-18'
NAME = 'grid'


def socket_path(cfg=None):
    p = os.environ.get('GRIDLINK_SOCKET') or getattr(cfg, 'term_socket', None)
    if p: return os.path.expanduser(p)
    run = os.environ.get('XDG_RUNTIME_DIR')
    return os.path.join(run, 'gridlink.sock') if run else os.path.expanduser('~/.cache/gridlink/gridlink.sock')


TOOLS = [
    {'name': 'grid_command',
     'description': (
         "Run a DOS command line or program on the GRiD 1520 (through COMMAND.COM /C, in the GRiD's "
         "current directory). With capture=true (default) the program's text output is redirected to a "
         "file and returned; use that for DIR, TYPE, CHKDSK, batch files. Programs that draw their own "
         "screen (TM5000G, editors) need capture=false: drive them with `keys` and look at them with "
         "`screenshot`. While it runs the GRiD shows the program, not this terminal; the user can type "
         "into it too. Runs until the program exits."),
     'inputSchema': {'type': 'object', 'properties': {
         'command': {'type': 'string', 'description': 'DOS command line, e.g. "DIR A:\\\\TM5000" or "TM5000G"'},
         'keys': {'type': 'string', 'description': (
             'Keystrokes to type into the program. Plain characters type themselves; named keys in braces: '
             '{ENTER} {ESC} {TAB} {BKSP} {UP} {DOWN} {LEFT} {RIGHT} {HOME} {END} {PGUP} {PGDN} {INS} {DEL} '
             '{F1}..{F10} {ALT+X} {CTRL+X} {SHIFT+F1}; {WAIT 2.5} pauses (seconds); {SNAP} takes a screenshot '
             'then. When the script ends the real keyboard takes over, so end with the keys that quit the '
             'program unless the user will.')},
         'capture': {'type': 'boolean', 'description': 'Return the text output (default true).'},
         'screenshot': {'type': 'boolean', 'description': 'Also capture the screen when the program exits.'},
         'timeout': {'type': 'integer', 'description': 'Seconds to wait for the program (default 900).'},
     }, 'required': ['command']}},
    {'name': 'grid_files',
     'description': (
         "Files on the GRiD (DOS paths with a drive letter, 8.3 names: A:\\\\TM5000\\\\DATA.TXT). Actions: "
         "list (a directory, with sizes and dates), info, read (a text file, CP437 and CR LF turned into "
         "Unicode and LF), write (content as text; written as CP437 with CR LF, through NAME.$$$ so a broken "
         "link can't leave half a file), delete, rename (to = new name), mkdir, rmdir, free (space on the "
         "drive), copy_from_grid (to = a path on the Pi), copy_to_grid (path = a file on the Pi, to = the "
         "GRiD file). To edit a GRiD file with your own editing tools: copy_from_grid, edit the copy, "
         "copy_to_grid. The link moves roughly 3-7 KB/s."),
     'inputSchema': {'type': 'object', 'properties': {
         'action': {'type': 'string', 'enum': ['list', 'info', 'read', 'write', 'delete', 'rename', 'mkdir',
                                               'rmdir', 'free', 'copy_from_grid', 'copy_to_grid']},
         'path': {'type': 'string'}, 'to': {'type': 'string'}, 'content': {'type': 'string'},
     }, 'required': ['action', 'path']}},
    {'name': 'grid_screen',
     'description': ("The screen of the last DOS program run with screenshot=true or a {SNAP} key: text "
                     "for text modes, an image for graphics."),
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'grid_info',
     'description': "The GRiD's DOS version, drives, free memory, EMS, GPIB driver, current directory and clock.",
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'gpib',
     'description': (
         "Instruments on the GRiD's GPIB bus (the GRiD is controller at address 21; the Pi's bridge is on "
         "the bus too). Actions: query (send a command, read the reply), write, read, poll (serial poll "
         "status byte), clear (device clear), trigger (GET), local, remote, scan (responding addresses). "
         "Commands get CR LF and EOI unless terminator says otherwise. Power supplies drive real circuits: "
         "never change their outputs unless asked."),
     'inputSchema': {'type': 'object', 'properties': {
         'action': {'type': 'string', 'enum': ['query', 'write', 'read', 'poll', 'clear', 'trigger',
                                               'local', 'remote', 'scan']},
         'address': {'type': 'integer', 'minimum': 0, 'maximum': 30},
         'command': {'type': 'string'},
         'terminator': {'type': 'string', 'enum': ['crlf', 'lf', 'none']},
         'timeout_ms': {'type': 'integer', 'description': 'Per-byte read timeout (default 2000).'},
         'max_bytes': {'type': 'integer', 'description': 'Largest reply to accept (default 4096).'},
     }, 'required': ['action']}},
]


def text(t): return {'type': 'text', 'text': t}


def to_dos(t):
    from .tools import to_cp437
    return to_cp437(t.replace('\r\n', '\n').replace('\n', '\r\n'))


class GridTools:
    """The tools, on gridlink's side of the socket (a Grid to call)."""
    def __init__(s, grid, cfg=None, bridge=7):
        s.G = grid; s.cfg = cfg; s.bridge = bridge

    def call(s, name, a):
        try:
            fn = getattr(s, 't_' + name, None)
            if fn is None: return [text('Unknown tool %s' % name)], True
            return fn(a)
        except GridError as e:
            return [text('GRiD: %s' % e)], True
        except (K.KeyError_, ValueError, OSError) as e:
            return [text('Error: %s' % e)], True

    def t_grid_info(s, a):
        info = s.G.get_info()
        return [text('\n'.join('%s: %s' % kv for kv in info.items()))], False

    def t_grid_command(s, a):
        command = (a.get('command') or '').strip()
        if not command: return [text('Error: empty command')], True
        capture = a.get('capture', True); script = a.get('keys') or ''
        shot = bool(a.get('screenshot', False)); timeout = int(a.get('timeout') or 900)
        kbytes = K.compile_script(script) if script else b''
        r = s.G.run(command, capture=capture, snapshot=shot or b'\xff\xfe' in kbytes, keys=kbytes, timeout=timeout)
        out = []
        msg = 'Exit code: %d' % r['exit']
        if capture:
            t = ''
            if r['output'] and r['outfile']:
                raw = s.G.read_file(r['outfile'], limit=64 * 1024)
                try: s.G.delete(r['outfile'])
                except GridError: pass
                t = raw.decode('cp437').replace('\r\n', '\n').replace('\x1a', '').strip('\n')
            if len(t) > 30000: t = t[:15000] + '\n[...]\n' + t[-15000:]
            msg += '\nOutput:\n' + (t or '(no output)')
        out.append(text(msg))
        if r['snapshot']: out += s.snapshot()
        elif shot: out.append(text('No screenshot was taken.'))
        return out, False

    def snapshot(s):
        snap = screen.parse(s.G.screen(0))
        if screen.is_text(snap):
            return [text('Screen (%s):\n%s' % (screen.describe(snap), screen.text(snap)))]
        png = screen.png_block(snap)['source']['data']
        return [text('Screenshot: %s' % screen.describe(snap)),
                {'type': 'image', 'data': png, 'mimeType': 'image/png'}]

    def t_grid_screen(s, a):
        return s.snapshot(), False

    def t_grid_files(s, a):
        G = s.G
        act = a.get('action'); path = (a.get('path') or '').strip(); to = (a.get('to') or '').strip()
        if act != 'copy_to_grid':
            if not is_grid_path(path): return [text('Error: path must be a GRiD path like A:\\NAME.EXT')], True
            path = norm(path)
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
            data = G.read_file(path, limit=256 * 1024)
            return [text(data.decode('cp437').replace('\r\n', '\n').replace('\x1a', ''))], False
        if act == 'write':
            data = to_dos(a.get('content') or '')
            G.write_file_safe(path, data)
            return [text('Wrote %s (%d bytes)' % (path, len(data)))], False
        if act == 'delete':
            G.delete(path); return [text('Deleted %s' % path)], False
        if act == 'rename':
            if not is_grid_path(to) and '\\' not in to: to = path.rpartition('\\')[0] + '\\' + to
            to = norm(to); G.rename(path, to); return [text('Renamed %s to %s' % (path, to))], False
        if act == 'mkdir':
            G.mkdir(path); return [text('Created directory %s' % path)], False
        if act == 'rmdir':
            G.rmdir(path); return [text('Removed directory %s' % path)], False
        if act == 'free':
            fb, tb = G.free(ord(path[0].upper()) - 64)
            return [text('%s %d bytes free of %d' % (path[:2], fb, tb))], False
        if act == 'copy_from_grid':
            dest = os.path.expanduser(to or path.rpartition('\\')[2])
            data = G.read_file(path, limit=4 * 1024 * 1024)
            os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
            with open(dest, 'wb') as f: f.write(data)
            return [text('Copied %s (%d bytes) to %s' % (path, len(data), os.path.abspath(dest)))], False
        if act == 'copy_to_grid':
            if not is_grid_path(to): return [text('Error: `to` must be a GRiD path')], True
            to = norm(to)
            with open(os.path.expanduser(path), 'rb') as f: data = f.read()
            G.write_file_safe(to, data)
            return [text('Copied %s (%d bytes) to %s' % (path, len(data), to))], False
        return [text('Error: unknown action %s' % act)], True

    def t_gpib(s, a):
        G = s.G
        act = a.get('action'); addr = a.get('address'); cmd = a.get('command') or ''
        term = {'crlf': b'\r\n', 'lf': b'\n', 'none': b''}[a.get('terminator') or 'crlf']
        tmo = int(a.get('timeout_ms') or 2000); maxb = int(a.get('max_bytes') or 4096)
        if act == 'scan':
            found = list(G.gpib(glp.GP_SCAN, 0, timeout_ms=tmo))
            return [text('Responding addresses: %s' % (', '.join(map(str, found)) or 'none'))], False
        if addr is None: return [text('Error: address is required')], True
        if addr in (21, s.bridge): return [text('Error: %d is the GRiD or the bridge, not an instrument' % addr)], True
        if act in ('query', 'write') and not cmd: return [text('Error: command is required')], True
        if act == 'query':
            r = G.gpib(glp.GP_QUERY, addr, cmd.encode('latin1') + term, timeout_ms=tmo, maxlen=maxb)
            return [text(r.decode('latin1').rstrip('\r\n') or '(empty reply)')], False
        if act == 'write':
            G.gpib(glp.GP_WRITE, addr, cmd.encode('latin1') + term, flags=1, timeout_ms=tmo)
            return [text('Sent to %d' % addr)], False
        if act == 'read':
            r = G.gpib(glp.GP_READ, addr, timeout_ms=tmo, maxlen=maxb)
            return [text(r.decode('latin1').rstrip('\r\n') or '(empty reply)')], False
        if act == 'poll':
            r = G.gpib(glp.GP_SPOLL, addr, timeout_ms=tmo); v = r[0] if r else 0
            return [text('Status byte %02Xh (%s)' % (v, format(v, '08b')))], False
        ops = {'clear': glp.GP_CLEAR, 'trigger': glp.GP_TRIGGER, 'local': glp.GP_LOCAL, 'remote': glp.GP_REMOTE}
        if act in ops:
            G.gpib(ops[act], addr, timeout_ms=tmo)
            return [text('%s sent to %d' % (act, addr))], False
        return [text('Error: unknown action %s' % act)], True


class ToolServer:
    """gridlink's end: a Unix socket; one JSON request per connection
    ({"tool", "arguments"} -> {"content", "isError"}), one GRiD request at a
    time (CLAUDE.COM runs one REQUEST at a time)."""
    def __init__(s, path, tools, available=lambda: None, log=print):
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
            f = c.makefile('rwb')
            line = f.readline()
            try:
                req = json.loads(line)
                why = s.available()
                if why: res = ([text(why)], True)
                else:
                    with s.lock:
                        res = s.tools.call(req.get('tool', ''), req.get('arguments') or {})
            except Exception as e:
                s.log('mcp: %r' % e); res = ([text('gridlink: %s' % e)], True)
            f.write(json.dumps({'content': res[0], 'isError': bool(res[1])}).encode() + b'\n'); f.flush()

    def stop(s):
        if s.sock: s.sock.close()
        try: os.unlink(s.path)
        except OSError: pass


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
    entry = {'type': 'stdio', 'command': sys.executable, 'args': ['-m', 'gridlink.mcp'],
             'env': {'GRIDLINK_SOCKET': sock, 'PYTHONPATH': pkg}}
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
    its directory, before gridlink (elsewhere) sees them."""
    if tool != 'grid_files' or not isinstance(args, dict): return args
    a = dict(args); act = a.get('action')
    if act == 'copy_to_grid' and a.get('path'):
        a['path'] = os.path.abspath(os.path.expanduser(a['path']))
    if act == 'copy_from_grid':
        to = a.get('to') or str(a.get('path', '')).replace('/', '\\').rpartition('\\')[2]
        a['to'] = os.path.abspath(os.path.expanduser(to))
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


def handle(msg, sock):
    """One JSON-RPC message -> the response (or None for a notification)."""
    mid = msg.get('id'); method = msg.get('method')
    if mid is None: return None
    if method == 'initialize':
        v = (msg.get('params') or {}).get('protocolVersion') or PROTOCOL
        res = {'protocolVersion': v, 'capabilities': {'tools': {}},
               'serverInfo': {'name': 'gridlink', 'version': '1.1'},
               'instructions': ('Tools for the GRiD 1520 this terminal runs on: its files, DOS programs '
                                '(with keystrokes and screenshots) and the GPIB bus it controls.')}
    elif method == 'ping':
        res = {}
    elif method == 'tools/list':
        res = {'tools': TOOLS}
    elif method == 'tools/call':
        p = msg.get('params') or {}
        res = call_gridlink(sock, p.get('name', ''), p.get('arguments') or {})
    else:
        return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': 'no method %s' % method}}
    return {'jsonrpc': '2.0', 'id': mid, 'result': res}


def main():
    sock = socket_path()
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try: msg = json.loads(line)
        except ValueError:
            out.write(json.dumps({'jsonrpc': '2.0', 'id': None,
                                  'error': {'code': -32700, 'message': 'parse error'}}) + '\n'); out.flush()
            continue
        msgs = msg if isinstance(msg, list) else [msg]
        for m in msgs:
            if not isinstance(m, dict): continue
            r = handle(m, sock)
            if r is not None:
                out.write(json.dumps(r) + '\n'); out.flush()


if __name__ == '__main__':
    main()
