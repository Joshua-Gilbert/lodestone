"""The MCP bridge (Term): Claude Code's stdio MCP server -> Unix socket ->
gridlink -> GLP REQUEST -> the GRiD (GridSim), and back.

    python3 tests/test_mcp.py
"""
import json, os, struct, subprocess, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gridsim import TermHarness
from gridlink import mcp

CFG_C = b'#include <stdio.h>\r\nint rate = 1;\r\nint main(void) { return rate; }\r\n'


class Client:
    """Claude Code's side: `python -m gridlink.mcp` as .mcp.json says."""
    def __init__(s, h):
        entry = json.load(open(os.path.join(h.cfg.term_dir, '.mcp.json')))['mcpServers']['grid']
        env = dict(os.environ, **entry['env'])
        s.p = subprocess.Popen([entry['command']] + entry['args'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               env=env, cwd=h.cfg.term_dir)
        s.h = h; s.n = 0; s.lock = threading.Lock()

    def rpc(s, method, params=None, notify=False):
        with s.lock:
            s.n += 1
            m = {'jsonrpc': '2.0', 'method': method, 'params': params or {}}
            if not notify: m['id'] = s.n
            s.p.stdin.write((json.dumps(m) + '\n').encode()); s.p.stdin.flush()
            if notify: return None
            return json.loads(s.p.stdout.readline())

    def call(s, tool, **args):
        """A tool call, with the GRiD (GridSim) running while it waits."""
        out = {}
        th = threading.Thread(target=lambda: out.update(r=s.rpc('tools/call', {'name': tool, 'arguments': args})))
        th.start()
        assert s.h.run_until(lambda: not th.is_alive(), wall=20), 'no answer to %s' % tool
        return out['r']['result']

    def close(s):
        s.p.stdin.close(); s.p.wait(5)


def start(files=None):
    h = TermHarness(files=files)
    assert h.wait_text('Welcome to Claude Code', wall=10)
    assert h.run_until(lambda: h.grid.time_set is not None, wall=5), 'no SETTIME'
    return h, Client(h)


def body(res):
    return '\n'.join(c.get('text', '') for c in res['content'])


def test_protocol():
    r = mcp.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                    'params': {'protocolVersion': '2025-06-18', 'capabilities': {}}}, '/nonexistent')
    assert r['result']['protocolVersion'] == '2025-06-18' and 'tools' in r['result']['capabilities']
    assert mcp.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, '') is None
    r = mcp.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, '')
    tools = {t['name']: t for t in r['result']['tools']}
    look = ['grid_info', 'grid_files', 'grid_screen', 'gpib_read', 'gpib_measure', 'grid_program', 'grid_plot',
            'grid_image', 'grid_pick']
    ask = ['grid_command', 'grid_change_files', 'gpib_send', 'grid_type', 'grid_plotter']
    assert sorted(tools) == sorted(look + ask), list(tools)
    for n in look:                       # can be allowed for good: they only look
        assert tools[n]['annotations']['readOnlyHint'] is True and '_meta' not in tools[n], n
    for n in ask:                        # Claude Code asks every time
        assert tools[n]['annotations']['destructiveHint'] is True, n
        assert tools[n]['_meta'] == {'anthropic/requiresUserInteraction': True}, n
    acts = lambda n: set(tools[n]['inputSchema']['properties']['action']['enum'])
    assert acts('grid_files') == {'list', 'info', 'read', 'free'}
    assert acts('gpib_read') == {'scan', 'poll', 'read'}
    r = mcp.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                    'params': {'name': 'grid_info', 'arguments': {}}}, '/nonexistent/sock')
    assert r['result']['isError'] and 'not running' in body(r['result'])
    r = mcp.handle({'jsonrpc': '2.0', 'id': 4, 'method': 'bogus'}, '')
    assert r['error']['code'] == -32601


def test_mcp_json_merge():
    import tempfile
    d = tempfile.mkdtemp()
    json.dump({'mcpServers': {'other': {'command': 'x'}}}, open(os.path.join(d, '.mcp.json'), 'w'))
    assert mcp.write_mcp_json(d, '/run/x.sock')
    j = json.load(open(os.path.join(d, '.mcp.json')))
    assert set(j['mcpServers']) == {'other', 'grid'} and j['mcpServers']['grid']['env']['GRIDLINK_SOCKET'] == '/run/x.sock'
    assert not mcp.write_mcp_json(d, '/run/x.sock')            # unchanged: not rewritten


def test_paths_and_robustness():
    import tempfile
    here = os.getcwd()
    a = mcp.local_paths('grid_change_files', {'action': 'copy_to_grid', 'path': 'foo.txt', 'to': 'A:\\FOO.TXT'})
    assert a['path'] == os.path.join(here, 'foo.txt'), a
    a = mcp.local_paths('grid_change_files', {'action': 'copy_from_grid', 'path': 'A:\\TM5000\\CFG.C'})
    assert a['to'] == os.path.join(here, 'CFG.C'), a
    assert mcp.local_paths('grid_change_files', {'action': 'copy_from_grid', 'path': 5}) == {'action': 'copy_from_grid', 'path': 5}
    assert mcp.local_paths('gpib', {'action': 'scan'}) == {'action': 'scan'}
    d = tempfile.mkdtemp(); p = os.path.join(d, '.mcp.json')
    open(p, 'w').write('{"mcpServers": {"mine": {"command": "x"},}}')     # a trailing comma
    try: mcp.write_mcp_json(d, '/s'); assert False, 'overwrote a file it could not read'
    except ValueError: pass
    assert 'mine' in open(p).read()
    open(p, 'w').write('{"mcpServers": null}')
    assert mcp.write_mcp_json(d, '/s') and 'grid' in json.load(open(p))['mcpServers']


def test_files():
    h, c = start(files={'A:\\CFG.C': CFG_C})
    try:
        r = c.rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't'}})
        assert r['result']['serverInfo']['name'] == 'gridlink'
        c.rpc('notifications/initialized', notify=True)
        assert len(c.rpc('tools/list')['result']['tools']) == 14
        r = c.call('grid_files', action='list', path='A:\\')
        assert 'CFG.C' in body(r) and not r['isError'], r
        r = c.call('grid_files', action='info', path='A:\\NOPE.TXT')     # (STAT's 18: not there)
        assert r['isError'] and 'file not found' in body(r), r
        r = c.call('grid_files', action='read', path='a:\\cfg.c')
        assert body(r) == CFG_C.decode().replace('\r\n', '\n'), r
        r = c.call('grid_files', action='write', path='A:\\NEW.TXT', content='x')
        assert r['isError'] and 'grid_change_files' in body(r), r      # grid_files only looks
        r = c.call('grid_change_files', action='write', path='A:\\NEW.TXT', content='caf\u00e9\nline 2\n')
        assert not r['isError'] and h.grid.fs['A:\\NEW.TXT'] == b'caf\x82\r\nline 2\r\n', h.grid.fs
        assert 'A:\\NEW.$$$' not in h.grid.fs
        pi = os.path.join(h.cfg.term_dir, 'cfg.c')
        r = c.call('grid_change_files', action='copy_from_grid', path='A:\\CFG.C', to=pi)
        assert open(pi, 'rb').read() == CFG_C, r
        open(pi, 'wb').write(CFG_C.replace(b'rate = 1', b'rate = 5'))
        r = c.call('grid_change_files', action='copy_to_grid', path=pi, to='A:\\CFG.C')
        assert h.grid.fs['A:\\CFG.C'] == CFG_C.replace(b'rate = 1', b'rate = 5'), r
        r = c.call('grid_change_files', action='copy_from_grid', path='A:\\CFG.C')   # default: ~/grid/CFG.C
        assert open(os.path.join(h.cfg.term_dir, 'CFG.C'), 'rb').read() == h.grid.fs['A:\\CFG.C'], r
        r = c.call('grid_change_files', action='delete', path='A:\\NOPE.TXT')
        assert r['isError'] and 'file not found' in body(r), r
        r = c.call('grid_info')
        assert 'os: MS-DOS 3.30' in body(r), r
    finally:
        c.close(); h.close()


def test_command_screen_gpib():
    h, c = start(files={'A:\\CFG.C': CFG_C})
    try:
        r = c.call('grid_command', command='DIR')
        assert 'Exit code: 0' in body(r) and 'A:\\CFG.C' in body(r), r
        assert 'A:\\CLAUDE.OUT' not in h.grid.fs                 # read, then deleted
        r = c.call('grid_command', command='TM5000G', capture=False, keys='1{ENTER}{SNAP}{ESC}')
        assert 'TM5000G v3.7' in body(r), r
        cmd, keys = h.grid.last_run
        assert keys.startswith(b'1\x02\r\x1c') and b'\xff\xfe\x00' in keys, keys
        r = c.call('grid_screen')
        assert 'TM5000G v3.7' in body(r), r
        r = c.call('gpib_send', action='query', address=29, command='ID?')
        assert body(r) == 'ID TEK/DC5009,V79.1,F1.2', r
        r = c.call('gpib_read', action='scan')
        assert '6, 16, 29' in body(r), r
        r = c.call('gpib_send', action='write', address=7, command='X')
        assert r['isError'], r
        # two calls at once (Claude Code may run tools in parallel): one at a time to the GRiD
        out = []
        ths = [threading.Thread(target=lambda: out.append(c2.rpc('tools/call', {'name': 'grid_files',
                                'arguments': {'action': 'read', 'path': 'A:\\CFG.C'}})))
               for c2 in (Client(h), Client(h))]
        for t in ths: t.start()
        assert h.run_until(lambda: not any(t.is_alive() for t in ths), wall=20)
        assert len(out) == 2 and all(not o['result']['isError'] for o in out), out
    finally:
        c.close(); h.close()


def test_not_connected():
    h, c = start()
    try:
        h.grid.state = 'reset'; h.grid.connected = False          # the GRiD went away
        h.link.last_rx = time.monotonic() - 60
        r = c.rpc('tools/call', {'name': 'grid_info', 'arguments': {}})['result']
        assert r['isError'] and 'not connected' in body(r), r
    finally:
        c.close(); h.close()


class NoGrid:
    """A GRiD that must not be reached: every check fails before it."""
    def __getattr__(s, name):
        raise AssertionError('reached the GRiD (%s) with bad arguments' % name)


def test_pi_files_only_in_grid_dir():
    import tempfile
    home = tempfile.mkdtemp(); root = os.path.join(home, 'grid'); os.makedirs(root)
    os.makedirs(os.path.join(home, '.claude')); secret = os.path.join(home, '.claude', '.credentials.json')
    open(secret, 'w').write('{"token": "s3cret"}')
    ok = lambda p: mcp.pi_path(root, p)
    assert ok('X.TXT') == os.path.join(os.path.realpath(root), 'X.TXT')
    assert ok(os.path.join(root, 'sub', 'Y.C')).endswith(os.path.join('grid', 'sub', 'Y.C'))
    os.symlink(secret, os.path.join(root, 'creds'))                      # a link out of ~/grid
    os.symlink(os.path.join(home, '.claude'), os.path.join(root, 'cc'))
    for bad in ('../.bashrc', secret, '/etc/passwd', '~/.bashrc', 'creds', 'cc/settings.json', root, '',
                '.claude/settings.json', '.claude/settings.local.json', '.mcp.json', 'sub/.hidden',
                'CLAUDE.md', 'claude.local.md', 'x\0y', 5, None):
        try: ok(bad); assert False, 'accepted %r' % (bad,)
        except ValueError: pass
    # reading: regular files with one link, at most the cap; a FIFO doesn't hang
    f = os.path.join(root, 'A.TXT'); open(f, 'wb').write(b'abc')
    assert mcp.read_pi(f, 10) == b'abc'
    try: mcp.read_pi(f, 2); assert False
    except ValueError as e: assert '3 bytes' in str(e)
    os.mkfifo(os.path.join(root, 'PIPE'))
    t0 = time.time()
    try: mcp.read_pi(os.path.join(root, 'PIPE'), 10); assert False
    except ValueError as e: assert 'regular' in str(e)
    assert time.time() - t0 < 2
    os.link(secret, os.path.join(root, 'HARD'))                           # a hard link into ~/grid
    try: mcp.read_pi(mcp.pi_path(root, 'HARD'), 1000); assert False
    except ValueError as e: assert 'hard links' in str(e)
    # writing: a link already at that name is replaced, never written through
    os.symlink(secret, os.path.join(root, 'OUT.TXT'))
    mcp.write_pi(os.path.join(root, 'OUT.TXT'), b'new')
    assert open(secret).read() == '{"token": "s3cret"}' and not os.path.islink(os.path.join(root, 'OUT.TXT'))
    assert open(os.path.join(root, 'OUT.TXT'), 'rb').read() == b'new'
    mcp.write_pi(os.path.join(root, 'HARD'), b'new')
    assert open(secret).read() == '{"token": "s3cret"}'
    assert not [n for n in os.listdir(root) if n.startswith('.grid-')]   # no temporary files left
    # and through the tool: nothing outside ~/grid, before the GRiD is asked
    gt = mcp.GridTools(NoGrid(), root=root)
    for a in ({'action': 'copy_to_grid', 'path': secret, 'to': 'A:\\X'},
              {'action': 'copy_to_grid', 'path': os.path.join(root, 'creds'), 'to': 'A:\\X'},
              {'action': 'copy_from_grid', 'path': 'A:\\X.TXT', 'to': os.path.join(home, '.bashrc')},
              {'action': 'copy_from_grid', 'path': 'A:\\X.TXT', 'to': os.path.join(root, '.claude', 'settings.json')},
              {'action': 'copy_from_grid', 'path': 'A:\\X.TXT', 'to': os.path.join(root, 'CLAUDE.md')}):
        res, err = gt.call('grid_change_files', a)
        assert err and 'Error' in res[0]['text'], (a, res)


def test_bad_arguments_never_reach_the_grid():
    gt = mcp.GridTools(NoGrid(), bridge=7, root='/nonexistent/grid')
    q = dict(action='query', address=9, command='ID?')
    cases = [
        ('gpib_send', dict(q, address=31)), ('gpib_send', dict(q, address=-1)), ('gpib_send', dict(q, address='9')),
        ('gpib_send', dict(q, address=True)), ('gpib_send', dict(q, address=21)), ('gpib_send', dict(q, address=7)),
        ('gpib_send', dict(q, address=None)), ('gpib_send', dict(q, timeout_ms=-5)), ('gpib_send', dict(q, timeout_ms=70000)),
        ('gpib_send', dict(q, max_bytes=0)), ('gpib_send', dict(q, command='')), ('gpib_send', dict(q, command='x' * 5000)),
        ('gpib_send', dict(q, command='\u2603?')), ('gpib_send', dict(q, terminator='cr')),
        ('gpib_send', dict(q, terminator=[])), ('gpib_send', dict(q, terminator='')), ('gpib_send', dict(q, terminator=['crlf'])),
        ('gpib_send', dict(q, action='scan')), ('gpib_read', dict(q)), ('gpib_read', dict(action='write', address=9)),
        ('gpib_read', dict(action='poll')), ('gpib_read', dict(action='read', address=40)),
        ('grid_command', {}), ('grid_command', dict(command='   ')), ('grid_command', dict(command=5)),
        ('grid_command', dict(command='X' * 101)), ('grid_command', dict(command='DIR\rDEL *.*')),
        ('grid_command', dict(command='TM5000G', keys='{WAIT 600}{WAIT 600}')),     # waits past the 900 s timeout
        ('grid_command', dict(command='TM5000G', keys='{WAIT 31}', timeout=30)), ('grid_command', dict(command='X', timeout=3601)),
        ('grid_command', dict(command='DIR', keys='{WAIT 1e9}')), ('grid_command', dict(command='DIR', keys='{WAIT nan}')),
        ('grid_command', dict(command='DIR', keys='{WAIT inf}')), ('grid_command', dict(command='DIR', keys='{WAIT -1}')),
        ('grid_command', dict(command='DIR', keys='{WAIT soon}')), ('grid_command', dict(command='DIR', keys='x' * 2100)),
        ('grid_command', dict(command='DIR', timeout=0)), ('grid_command', dict(command='DIR', timeout=10 ** 9)),
        ('grid_command', dict(command='DIR', capture='yes')), ('grid_command', dict(command='DIR', keys=['x'])),
        ('grid_files', dict(action='delete', path='A:\\X')), ('grid_files', dict(action='rmdir', path='A:\\D')),
        ('grid_files', dict(action='read', path='X.TXT')), ('grid_files', dict(action='read', path='A:\\X\0.TXT')),
        ('grid_files', dict(action='read', path='A:\\' + 'D\\' * 50)), ('grid_files', dict(action='read', path='A:\\*.*')),
        ('grid_files', dict(action='read', path='A:\\\u2192.TXT')), ('grid_files', dict(action='read', path=['A:\\X'])),
        ('grid_change_files', dict(action='delete', path='A:\\*.*')), ('grid_change_files', dict(action='rename', path='A:\\X')),
        ('grid_change_files', dict(action='rename', path='A:\\X', to='Y?')), ('grid_change_files', dict(action='write', path='A:\\X', content=5)),
        ('grid_change_files', dict(action='write', path='A:\\X', content='x' * (mcp.MAX_COPY + 1))),
        ('grid_change_files', dict(action='format', path='A:\\')),
        ('grid_files', dict(action='free', path='\u00e9:')), ('grid_files', dict(action='read', path='A:\\AUX')), ('grid_files', dict(action='read', path='A:\\TM\\COM1.TXT')),
        ('grid_files', dict(action='read', path='a:con')), ('grid_files', dict(action='info', path='A:\\CLOCK$')),
        ('grid_change_files', dict(action='write', path='A:\\PRN.TXT', content='x')),
        ('grid_change_files', dict(action='copy_from_grid', path='A:\\LPT1', to='/nonexistent/grid/X')), ('grid', {}), ('t_grid_info', {}), ('__init__', {}),
        ('grid_type', {}), ('grid_type', dict(keys='')), ('grid_type', dict(keys=5)), ('grid_type', dict(keys='a{SNAP}b')),
        ('grid_type', dict(keys='x' * 1025)), ('grid_type', dict(keys='{WAIT 61}')), ('grid_type', dict(keys='x', timeout=601)),
        ('grid_type', dict(keys='x', timeout=0)), ('grid_type', dict(keys='{WAIT 3}', timeout=2)), ('grid_type', dict(keys='{NOPE}')),
    ]
    for name, a in cases:
        res, err = gt.call(name, a)
        assert err, (name, a, res)
    # DOS devices are refused below the tools too (chat mode reads through Grid as well)
    from gridlink.grid import Grid, GridError
    for dev in ('A:\\AUX', 'C:\\TM\\com2.dat', 'A:NUL', 'A:\\AUX:', 'A:\\X\\COM1:', 'A:\\EMMXXXX0', 'A:\\PRN :'):
        try: Grid(NoGrid()).read(dev); assert False, dev
        except GridError: pass
        try: Grid(NoGrid()).write(dev, b'x'); assert False, dev
        except GridError: pass
    # the key script compiler (chat mode uses it too)
    from gridlink import keys as K
    k = K.compile_script('1{WAIT 600}{ENTER}{SNAP}{WAIT 2.5}')
    assert len(k) == 2 + 3 * -(-round(600 / K.TICK) // 255) + 2 + 3 + 3          # 43 waits of 255 ticks or less
    assert abs(K.script_seconds(k) - 602.5) < 0.1, K.script_seconds(k)
    for bad in ('{WAIT 601}', '{WAIT -0.1}', '{WAIT nan}', '{WAIT 1e400}', 'a' * 2049):
        try: K.compile_script(bad); assert False, bad
        except K.KeyError_: pass


class Paused:
    """Resident Claude's console over a program: its screen, and TYPE's
    answers (the keys it got kept)."""
    def __init__(s, played=True, mode=3):
        s.played, s.mode, s.typed = played, mode, []
    def raw(s):
        if s.mode == 3:
            cells = b''.join(bytes([c, 7]) for c in b'TM5000 CONTROL SYSTEM'.ljust(80 * 25))
            return struct.pack('<BBBHHH', 3, 1, 0, 80, 25, 160) + cells
        return struct.pack('<BBBHHH', 6, 2, 1, 640, 200, 80) + bytes(16384)
    def screen(s, which=0): return s.raw()
    def type_keys(s, keys, timeout=60):
        s.typed.append((bytes(keys), timeout))
        return s.played, (s.raw() if s.mode != 7 else None)


def test_grid_program_and_type():
    from gridlink import keys as K
    hello = {'app': 'resident', 'prog': 'TM5000G.EXE'}
    p = Paused(); gt = mcp.GridTools(p, root='/nonexistent', hello=lambda: hello)
    res, err = gt.call('grid_program', {})
    assert not err and 'TM5000G.EXE is paused' in res[0]['text'] and 'TM5000 CONTROL SYSTEM' in res[1]['text'], res
    # the screen comes at the end: a {SNAP} there is dropped, the Pi waits the keys' time and more
    res, err = gt.call('grid_type', {'keys': '1{ENTER}{WAIT 0.5}{SNAP}', 'timeout': 30})
    assert not err and res[0]['text'] == 'Typed into TM5000G.EXE.' and 'TM5000 CONTROL SYSTEM' in res[1]['text'], res
    assert p.typed == [(K.compile_script('1{ENTER}{WAIT 0.5}'), 40)], p.typed
    assert mcp.snap_marks(K.compile_script('{WAIT 13.95}a{SNAP}')) == [5]      # (a wait of FE ticks is no mark)
    p.played = False
    res, err = gt.call('grid_type', {'keys': '{ESC}'})
    assert not err and 'stopped the keys (CODE-\\)' in res[0]['text'], res
    p.played, p.mode = True, 6
    res, err = gt.call('grid_type', {'keys': 'x'})
    assert not err and res[-1]['type'] == 'image', res
    p.mode = 7
    res, err = gt.call('grid_type', {'keys': 'x'})
    assert not err and 'No screenshot' in res[0]['text'], res
    hello.pop('prog')                                   # (DOS two deep, or its environment freed: no name)
    res, err = gt.call('grid_program', {})
    assert not err and 'name isn\'t known' in res[0]['text'], res


class Outfile:
    """A GRiD with one big output file (the Grid calls output() uses)."""
    def __init__(s, data): s.data = data
    def read_file(s, path, limit): return s.data[:limit]
    def stat(s, path): return {'size': len(s.data), 'dir': False}
    def read(s, path, off, n): return s.data[off:off + n]


def test_sizes_are_errors_not_cuts():
    # a program's output: all of it, or its start and end and what's between them
    gt = mcp.GridTools(Outfile(b'x' * 100 + b'\r\n'), root='/nonexistent')
    assert gt.output('A:\\O') == 'x' * 100
    big = b''.join(b'line %06d\r\n' % i for i in range(20000))          # 260,000 bytes
    out = mcp.GridTools(Outfile(big), root='/nonexistent').output('A:\\O')
    assert out.startswith('line 000000\n') and out.endswith('line 019999')
    n = int(out.split('[... ')[1].split()[0])
    assert 'bytes of output not shown' in out and n == len(big) - mcp.MAX_READ, n   # 40 KB head, 8 KB tail
    h, c = start(files={'A:\\BIG.TXT': b'a' * (mcp.MAX_READ + 1), 'A:\\OK.TXT': b'b' * mcp.MAX_READ,
                        'A:\\HUGE.DAT': b'\0' * (mcp.MAX_COPY + 1)})
    try:
        r = c.call('grid_files', action='read', path='A:\\BIG.TXT')
        assert r['isError'] and '%d bytes' % (mcp.MAX_READ + 1) in body(r) and 'aaaa' not in body(r), r
        r = c.call('grid_files', action='read', path='A:\\OK.TXT')
        assert not r['isError'] and len(body(r)) == mcp.MAX_READ, len(body(r))
        r = c.call('grid_change_files', action='copy_from_grid', path='A:\\HUGE.DAT')
        assert r['isError'] and 'too big' in body(r), r
        assert not os.path.exists(os.path.join(h.cfg.term_dir, 'HUGE.DAT'))
        f = os.path.join(h.cfg.term_dir, 'BIG.BIN'); open(f, 'wb').write(b'\0' * (mcp.MAX_COPY + 1))
        r = c.call('grid_change_files', action='copy_to_grid', path=f, to='A:\\BIG.BIN')
        assert r['isError'] and 'the most is' in body(r) and 'A:\\BIG.BIN' not in h.grid.fs, r
        os.mkfifo(os.path.join(h.cfg.term_dir, 'FIFO'))
        r = c.call('grid_change_files', action='copy_to_grid', path='FIFO', to='A:\\F')
        assert r['isError'] and 'regular' in body(r), r
        r = c.call('grid_change_files', action='copy_from_grid', path='A:\\OK.TXT', to='/tmp/OK.TXT')
        assert r['isError'] and 'inside' in body(r) and not os.path.exists('/tmp/OK.TXT'), r
    finally:
        c.close(); h.close()


def test_stdio_server_survives_anything():
    env = dict(os.environ, GRIDLINK_SOCKET='/nonexistent/gridlink.sock',
               PYTHONPATH=os.path.dirname(HERE))
    p = subprocess.Popen([sys.executable, '-m', 'gridlink.mcp'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
    lines = [b'\xff\xfe not utf-8\n', b'[' * 100000 + b'\n', b'{not json\n', b'5\n', b'[1, "x"]\n',
             b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":[1]}\n',
             b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":5}}\n',
             b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"grid_info","arguments":"x"}}\n',
             b'{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"grid_change_files",'
             b'"arguments":{"action":"copy_from_grid","path":["A:\\\\X"],"to":7}}}\n',
             b'{"jsonrpc":"2.0","id":5,"method":"initialize","params":{"protocolVersion":7}}\n',
             b'{"jsonrpc":"2.0","method":"notifications/initialized","params":"x"}\n',
             b'{"jsonrpc":"2.0","id":6,"method":"ping"}\n']
    out, _ = p.communicate(b''.join(lines), timeout=30)
    rs = [json.loads(l) for l in out.splitlines()]
    by = {r.get('id'): r for r in rs}               # (tool calls answer on their own threads: in any order)
    assert p.returncode == 0 and by[6] == {'jsonrpc': '2.0', 'id': 6, 'result': {}}, rs
    assert by[1]['error']['code'] == -32602 and by[2]['error']['code'] == -32602 and by[3]['error']['code'] == -32602
    assert by[4]['result']['isError'] and by[5]['result']['protocolVersion'] == mcp.PROTOCOL
    # a version it doesn't know: it answers with its own; one it knows: that one
    for asked, want in (('1900-01-01', mcp.PROTOCOL), ('2024-11-05', '2024-11-05'), (None, mcp.PROTOCOL)):
        r = mcp.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': asked}}, '/nonexistent')
        assert r['result']['protocolVersion'] == want, (asked, r)
    # gpib_read is read-only but not idempotent (a read empties the instrument's output)
    gr = next(t for t in mcp.TOOLS if t['name'] == 'gpib_read')['annotations']
    assert gr['readOnlyHint'] and not gr['destructiveHint'] and gr['idempotentHint'] is False, gr
    assert sum(1 for r in rs if r.get('error', {}).get('code') == -32700) == 3, rs


def test_second_call_waits_its_turn():
    """While a RUN keeps the GRiD from polling, a second call waits for it
    instead of hearing "not connected"."""
    busy = threading.Event(); go = threading.Event()
    class Slow:
        def call(s, name, a):
            busy.set(); go.wait(5); busy.clear()
            return [mcp.text('done %s' % name)], False
    srv = mcp.ToolServer('/nonexistent', Slow(), available=lambda tool: 'not connected' if busy.is_set() else None,
                         log=lambda m: None)
    out = {}
    t1 = threading.Thread(target=lambda: out.update(a=srv.request(b'{"tool": "grid_command", "arguments": {}}\n')))
    t1.start(); assert busy.wait(5)
    t2 = threading.Thread(target=lambda: out.update(b=srv.request(b'{"tool": "grid_info", "arguments": {}}\n')))
    t2.start(); time.sleep(0.2); go.set(); t1.join(5); t2.join(5)
    assert out['a'] == ([mcp.text('done grid_command')], False) and out['b'] == ([mcp.text('done grid_info')], False), out


def test_launch_ignores_the_working_directory():
    """.mcp.json's command imports nothing from ~/grid (Claude Code may write
    files there): a json.py there must not run."""
    import tempfile
    d = tempfile.mkdtemp()
    open(os.path.join(d, 'json.py'), 'w').write('raise SystemExit("imported from ~/grid")\n')
    os.makedirs(os.path.join(d, 'gridlink')); open(os.path.join(d, 'gridlink', '__init__.py'), 'w').write('raise SystemExit(9)\n')
    mcp.write_mcp_json(d, '/nonexistent/gridlink.sock')
    entry = json.load(open(os.path.join(d, '.mcp.json')))['mcpServers']['grid']
    p = subprocess.Popen([entry['command']] + entry['args'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, cwd=d, env=dict(os.environ, **entry['env']))
    out, err = p.communicate(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n', timeout=20)
    assert p.returncode == 0 and json.loads(out) == {'jsonrpc': '2.0', 'id': 1, 'result': {}}, (out, err)


def plot_to_end(h, c, wall=30):
    """Run the GRiD while the background plot goes; its last status."""
    end = time.time() + wall
    while time.time() < end:
        h.run_for(0.2)
        r = body(c.call('grid_plotter', action='status'))
        if any(w in r for w in (': done', ': stopped', ': cancelled')): return r
    raise AssertionError('the plot did not finish: %s' % r)


def assert_pairs(data, parts):
    """Each part that ends inside data's one PA/PD list ends just after a
    y: an even count of numbers in the list so far."""
    import re
    data = data.encode(); i = data.index(b'PA') if b'PA' in data else data.index(b'PD')
    e = data.index(b';', i); at = 0
    for p in parts[:-1]:
        at += len(p)
        if i < at < e:
            n = len(re.findall(rb'[^,\s;]+', data[i + 2:at]))
            assert n % 2 == 0 and data[at - 1:at] in b', ', (at, n, data[at - 20:at + 5])


def test_plotter():
    h, c = start()
    try:
        square = 'IN;SP1;PU1000,1000;PD3000,1000,3000,3000,1000,3000,1000,1000;LBTEST;1\x03;PU;'
        r = c.call('grid_plotter', hpgl=square)
        assert not r['isError'] and 'background' in body(r) and 'GPIB 1' in body(r), r
        r = plot_to_end(h, c)
        assert ': done' in r and '%d of %d bytes' % (len(square), len(square)) in r, r
        assert h.grid.plot_parts == [square.encode()], h.grid.plot_parts
        assert getattr(h.grid, 'plot_clears', []) == [], h.grid.plot_clears   # the Nano idle at the start: no SDC
        assert not getattr(h.grid, 'plot_overrun', False)
        # no ';' at the end: one is added, so the Nano ends the last command
        h.grid.plot_parts = []
        r = c.call('grid_plotter', hpgl='IN;PU1,2PD3,4')
        assert not r['isError'], r
        r = plot_to_end(h, c)
        assert ': done' in r and h.grid.plot_parts == [b'IN;PU1,2PD3,4;'], (r, h.grid.plot_parts)
        # a long plot: sent in parts that fit, polled in between, whole commands
        big = ''.join('PD%d,%d;' % (i, i) for i in range(600)) + 'LBA;B;C\x03;PU;'
        open(os.path.join(h.cfg.term_dir, 'big.plt'), 'w').write(big)
        # short commands before one longer than any room: the long one in parts, not a wait for ever
        long = 'IN;PU0,0;PD' + ','.join('%d,%d' % (i, i * 3 % 1000) for i in range(200)) + ';PU;'
        h.grid.plot_parts = []; h.grid.plot_held = 0
        r = c.call('grid_plotter', hpgl=long)
        assert not r['isError'], r
        r = plot_to_end(h, c)
        assert ': done' in r and b''.join(h.grid.plot_parts) == long.encode(), (r, h.grid.plot_parts)
        assert not getattr(h.grid, 'plot_overrun', False), 'sent more than the Nano had room for'
        # (cut in its list only just after the ',' after a y: never inside a number or an x,y pair)
        assert h.grid.plot_parts[0].endswith(b',') and len(h.grid.plot_parts[0]) > 200, h.grid.plot_parts
        assert all(p.endswith((b';', b',')) for p in h.grid.plot_parts), h.grid.plot_parts
        assert_pairs(long, h.grid.plot_parts)
        # the same with ", " and " " between the numbers
        for sep in (', ', ' '):
            lst = 'IN;PA' + sep.join('%d%s%d' % (i * 37 % 10000, sep, i * 53 % 7000) for i in range(150)) + ';PU;'
            h.grid.plot_parts = []; h.grid.plot_held = 0
            c.call('grid_plotter', hpgl=lst)
            r = plot_to_end(h, c)
            assert ': done' in r and b''.join(h.grid.plot_parts) == lst.encode(), (r, h.grid.plot_parts)
            assert len(h.grid.plot_parts) > 2, h.grid.plot_parts
            assert_pairs(lst, h.grid.plot_parts)
        # a second mnemonic with no ';' before it: its list counted from its own start ("0PD0," is no number)
        two = 'IN;PU0,0PD' + ','.join('%d,%d' % (i, 1000 + i) for i in range(200)) + ';PU;'
        h.grid.plot_parts = []; h.grid.plot_held = 0
        c.call('grid_plotter', hpgl=two)
        r = plot_to_end(h, c)
        assert ': done' in r and b''.join(h.grid.plot_parts) == two.encode(), (r, h.grid.plot_parts)
        assert len(h.grid.plot_parts) > 2, h.grid.plot_parts
        assert_pairs(two, h.grid.plot_parts)
        # ... and one that isn't PA PD PR PU ends the pairing: cut where the room ends
        oth = 'IN;PA0,0XX' + '12,' * 100 + ';PU;'
        h.grid.plot_parts = []; h.grid.plot_held = 0
        c.call('grid_plotter', hpgl=oth)
        r = plot_to_end(h, c)
        assert ': done' in r and h.grid.plot_parts[0] == oth.encode()[:240], (r, h.grid.plot_parts)
        # any other command bigger than the room is cut where the room ends (only PA PD PR PU lists are numbers)
        lab = 'IN;LB' + 'a,b ' * 100 + '\x03;'
        h.grid.plot_parts = []; h.grid.plot_held = 0
        c.call('grid_plotter', hpgl=lab)
        r = plot_to_end(h, c)
        assert ': done' in r and b''.join(h.grid.plot_parts) == lab.encode(), (r, h.grid.plot_parts)
        assert h.grid.plot_parts[0] == lab.encode()[:240], h.grid.plot_parts
        other = 'IN;XX' + '12,' * 100 + ';PU;'                         # (numbers, but not a PA PD PR PU list)
        h.grid.plot_parts = []; h.grid.plot_held = 0
        c.call('grid_plotter', hpgl=other)
        r = plot_to_end(h, c)
        assert ': done' in r and h.grid.plot_parts[0] == other.encode()[:240], (r, h.grid.plot_parts)
        h.grid.plot_parts = []; h.grid.plot_held = 0
        r = c.call('grid_plotter', file='big.plt')
        assert not r['isError'], r
        r2 = c.call('grid_plotter', file='big.plt')                    # one at a time
        assert r2['isError'] and 'A plot is running' in body(r2), r2
        r3 = c.call('grid_info')                                        # the GRiD stays usable meanwhile
        assert not r3['isError'], r3
        r = plot_to_end(h, c)
        assert ': done' in r, r
        assert b''.join(h.grid.plot_parts) == big.encode()
        assert len(h.grid.plot_parts) > 4 and all(len(p) <= 240 for p in h.grid.plot_parts)
        assert all(p.endswith((b';', b'\x03')) for p in h.grid.plot_parts), h.grid.plot_parts
        assert not getattr(h.grid, 'plot_overrun', False), 'sent more than the Nano had room for'
        assert sum(1 for op, a, d in h.grid.gpib_log if a == 1 and op == mcp.glp.GP_SPOLL) > len(h.grid.plot_parts)
        # the Nano stops taking bytes part way
        h.grid.plot_parts = []; h.grid.plot_clears = []; h.grid.plot_held = 0; h.grid.plot_fail_after = 2
        c.call('grid_plotter', file='big.plt')
        r = plot_to_end(h, c)
        assert ': stopped' in r and 'part of the drawing may be on the paper' in r, r
        assert h.grid.plot_clears == [2], h.grid.plot_clears         # (cleared as it failed)
        h.grid.plot_fail_after = None
        # cancel: SDC, then the pen up after the whole commands sent
        h.grid.plot_parts = []; h.grid.plot_clears = []; h.grid.plot_held = 0; h.grid.plot_drain = 1  # a slow pen
        c.call('grid_plotter', file='big.plt')
        h.run_for(0.5)
        r = body(c.call('grid_plotter', action='cancel'))
        assert 'cancelled' in r and 'not have stopped' not in r, r
        parts = h.grid.plot_parts
        assert len(parts) >= 2 and parts[-1] == b'PU;' and h.grid.plot_clears == [len(parts) - 1],             (parts, h.grid.plot_clears)
        # cancelled inside one command sent in parts: SDC, no "PU;" (it would end the list early)
        one = 'PD' + ','.join('%d,%d' % (i, i) for i in range(300)) + ';'
        h.grid.plot_parts = []; h.grid.plot_clears = []; h.grid.plot_held = 0
        c.call('grid_plotter', hpgl=one)
        end = time.time() + 20
        while not h.grid.plot_parts:
            assert time.time() < end; h.run_for(0.2)
        r = body(c.call('grid_plotter', action='cancel'))
        assert 'cancelled' in r, r
        parts = h.grid.plot_parts
        assert len(parts) == 1 and parts[0].endswith(b',') and h.grid.plot_clears == [1], (parts, h.grid.plot_clears)
        h.grid.plot_drain = 60
        # a clear the GRiD fails is not fatal, but said (a Nano stuck at the start: a label left open)
        h.grid.plot_parts = []; h.grid.plot_held = 0; h.grid.plot_clear_fail = True; h.grid.plot_open = True
        stuck = mcp.PLOT_STUCK; mcp.PLOT_STUCK = 1
        try:
            c.call('grid_plotter', hpgl='IN;PU1,2;')
            end = time.time() + 20
            while not h.grid.plot_parts:
                assert time.time() < end; h.run_for(0.2)
        finally:
            mcp.PLOT_STUCK = stuck
        h.grid.plot_open = False                        # (its label ended after all: the plot can finish)
        r = plot_to_end(h, c)
        assert ': done' in r and h.grid.plot_parts == [b'IN;PU1,2;'], (r, h.grid.plot_parts)
        assert 'The Nano was not cleared' in r and 'a label left open may eat the start' in r, r
        assert any('plot: the Nano was not cleared' in str(l) for l in h.log), h.log
        h.grid.plot_clear_fail = False
        # a clear that fails on cancel: said
        h.grid.plot_parts = []; h.grid.plot_clears = []; h.grid.plot_held = 0; h.grid.plot_drain = 1
        c.call('grid_plotter', file='big.plt')
        end = time.time() + 20
        while not h.grid.plot_parts:
            assert time.time() < end; h.run_for(0.2)
        h.grid.plot_clear_fail = True
        r = body(c.call('grid_plotter', action='cancel'))
        assert ': cancelled' in r and 'The plotter may not have stopped cleanly' in r, r
        assert h.grid.plot_clears == [], h.grid.plot_clears
        h.grid.plot_clear_fail = False; h.grid.plot_drain = 60
        # cancelled while the pen finishes is "cancelled", not "done"
        h.grid.plot_parts = []; h.grid.plot_clears = []; h.grid.plot_held = 0; h.grid.plot_drain = 0  # never finishes
        c.call('grid_plotter', hpgl='IN;PU1,2;')
        end = time.time() + 20
        while 'the pen is finishing' not in body(c.call('grid_plotter', action='status')):
            assert time.time() < end; h.run_for(0.2)
        r = body(c.call('grid_plotter', action='cancel'))
        assert ': cancelled' in r, r
        # (no clear: what the Nano holds is drawn)
        assert h.grid.plot_clears == [] and h.grid.plot_parts == [b'IN;PU1,2;'], (h.grid.plot_clears, h.grid.plot_parts)
        h.grid.plot_drain = 60
        # a GRiD that doesn't answer the plot's polls holds the other tools for one short wait, not 31 s
        h.grid.plot_parts = []; h.grid.plot_held = 0; h.grid.plot_drain = 0
        c.call('grid_plotter', hpgl='IN;PU1,2;')
        h.grid.plot_mute = True
        h.run_for(1.5)                                  # (a poll is out by now, unanswered)
        t0 = time.time()
        r = c.call('grid_info')
        assert not r['isError'] and time.time() - t0 < mcp.PLOT_POLL_WAIT + 3, (r, time.time() - t0)
        r = body(c.call('grid_plotter', action='cancel'))
        assert ': cancelled' in r or 'cancelling' in r, r
        h.grid.plot_mute = False; h.grid.plot_drain = 60
        plot_to_end(h, c)
        # a Nano without serial poll (before v4): an error, nothing sent
        h.grid.plot_parts = []; h.grid.plot_nopoll = True
        r = c.call('grid_plotter', hpgl='IN;')
        assert r['isError'] and 'does not answer a serial poll' in body(r) and 'Nothing was sent' in body(r), r
        assert h.grid.plot_parts == []
        h.grid.plot_nopoll = False
        r = c.call('gpib_read', action='scan')                 # v4 answers a poll: on the scan
        assert '1, 6, 16, 29' in body(r), r
    finally:
        c.close(); h.close()


def test_plotter_labels_as_plot_com():
    """As PLOT.COM: a cut never falls between a label mnemonic's letters
    (with or without what the Nano drops between them); a cancel clears
    first, then sends ETX and "PU;" inside a label's text, "PU;" after a
    whole command, nothing inside a list; a start whose poll asks for
    service is refused (X78)."""
    h, c = start()
    try:
        def plot(hpgl):
            h.grid.plot_parts = []; h.grid.plot_clears = []; h.grid.plot_held = 0
            r = c.call('grid_plotter', hpgl=hpgl)
            assert not r['isError'], r
            r = plot_to_end(h, c)
            assert ': done' in r and b''.join(h.grid.plot_parts) == hpgl.encode(), (r, h.grid.plot_parts)
            return h.grid.plot_parts
        # the room is 240: the mnemonic's letters at 238/241 (CR LF between), 239/240, 237/240 (SO SI
        # between), 239/242 (SUB BS between)
        for at, mn in ((238, 'L\r\nB'), (239, 'LB'), (237, 'B\x0e\x0fL'), (239, 'w\x1a\x08d')):
            head = 'IN;PA' + '1,2,' * 58
            data = head + ' ' * (at - len(head)) + mn + 'x' * 300 + '\x03;PU;'
            assert data.find(mn) == at
            parts = plot(data)
            assert parts[0] == data[:at].encode(), (mn, parts[0][-12:])
        # no cut at all inside a mnemonic that the room's end doesn't split
        parts = plot('IN;SP1;LB' + 'y' * 500 + '\x03;PU;')
        assert len(parts[0]) == 240, parts
        # cancels, the pen slow: inside a label's text
        h.grid.plot_drain = 1
        def cancel(hpgl):
            h.grid.plot_parts = []; h.grid.plot_clears = []; h.grid.plot_held = 0
            c.call('grid_plotter', hpgl=hpgl)
            end = time.time() + 20
            while not h.grid.plot_parts:
                assert time.time() < end; h.run_for(0.2)
            r = body(c.call('grid_plotter', action='cancel'))
            assert ': cancelled' in r and 'not have stopped' not in r, r
            return h.grid.plot_parts, h.grid.plot_clears
        for lab in ('LB', 'BL', 'WD', 'L\nB'):
            parts, clears = cancel('IN;SP1;PA10,20' + lab + 'ab;c' * 200 + '\x03;PU;')
            assert len(parts) == 2 and parts[1] == b'\x03PU;' and clears == [1], (lab, parts, clears)
        # after whole commands
        parts, clears = cancel(''.join('PD%d,%d;' % (i, i) for i in range(200)))
        assert parts[-1] == b'PU;' and clears == [len(parts) - 1], (parts, clears)
        # inside a list: the clear alone
        parts, clears = cancel('PD' + ','.join('%d,%d' % (i, i) for i in range(300)) + ';')
        assert len(parts) == 1 and clears == [1], (parts, clears)
        h.grid.plot_drain = 60
        # a poll at the start that asks for service (RQS): not the Nano: refused at once, an error, no plot
        # started, nothing sent, no clear
        h.grid.plot_rqs = True
        h.grid.plot_parts = []; h.grid.plot_clears = []; h.grid.plot_held = 0
        r = c.call('grid_plotter', hpgl='IN;PU1,2;')
        h.run_for(0.5)
        h.grid.plot_rqs = False
        assert r['isError'] and body(r) == 'GPIB 1 asks for service: it is not the Nano. Nothing was sent.', r
        st = body(c.call('grid_plotter', action='status'))
        assert 'asks for service' not in st and ': cancelled' in st, st     # (status: still the last plot's)
        assert h.grid.plot_clears == [] and h.grid.plot_parts == [], (r, h.grid.plot_clears)
    finally:
        c.close(); h.close()


def test_plotter_start_and_failures():
    """The start (X78): a Nano still drawing what an earlier plot left it is waited for, not
    cleared (a clear would drop what it holds); one that gets nowhere for PLOT_STUCK s (a label left open:
    not idle, its buffer empty) is cleared; a cancel meanwhile clears nothing.  A plot that fails (a write,
    a Nano with no room for PLOT_STALL s) clears the Nano, so its parser is clean for the next.  And the
    other session's fuzzed cases: a cancel inside a label that holds a ';', and a label straight after a
    list that fills the room."""
    h, c = start()
    stuck, stall = mcp.PLOT_STUCK, mcp.PLOT_STALL
    mcp.PLOT_STUCK = 1.5
    def until_parts(k):
        end = time.time() + 20
        while len(h.grid.plot_parts) < k:
            assert time.time() < end, h.grid.plot_parts
            h.run_for(0.2)
    def fresh(**kw):
        h.grid.plot_parts = []; h.grid.plot_clears = []; h.grid.plot_held = 0; h.grid.plot_drain = 60
        h.grid.plot_open = False; h.grid.plot_frozen_until = 0; h.grid.plot_empty = False; h.grid.plot_poll_fail = 0
        for k, v in kw.items(): setattr(h.grid, k, v)
    try:
        # draining: 75 bytes held, 25 drawn a poll (its status changes each time): waited for, then
        # plotted, no clear
        fresh(plot_held=100, plot_drain=25)
        r = c.call('grid_plotter', hpgl='IN;PU1,2;')
        assert not r['isError'] and 'The Nano is still busy (status ' in body(r) and \
            'the plot first waits for it to finish the last drawing.' in body(r), r
        end = time.time() + 5
        while 'waiting for the Nano to finish the last drawing' not in body(c.call('grid_plotter', action='status')):
            assert time.time() < end, 'not waiting'; time.sleep(0.05)
        r = plot_to_end(h, c)
        assert ': done' in r and 'Waited for the Nano to finish the last drawing' in r, r
        assert h.grid.plot_clears == [] and h.grid.plot_parts == [b'IN;PU1,2;'], (h.grid.plot_clears, r)
        # stuck (a label left open): its status unchanged for PLOT_STUCK s, then cleared and plotted
        fresh(plot_open=True)
        c.call('grid_plotter', hpgl='IN;PU1,2;')
        r = plot_to_end(h, c)
        assert ': done' in r and 'The Nano was stuck (its status 3Ch, its buffer empty but not idle, unchanged ' \
            'for 1 s' in r, r
        assert 'a label left open?): cleared.' in r, r
        assert h.grid.plot_clears == [0] and h.grid.plot_parts == [b'IN;PU1,2;'], (h.grid.plot_clears, r)
        assert any('status stayed 3Ch' in str(l) for l in h.log), h.log
        # cancelled while it waits: nothing sent, nothing cleared (what the Nano holds is the last drawing's)
        mcp.PLOT_STUCK = 60
        fresh(plot_held=200, plot_drain=0)
        c.call('grid_plotter', hpgl='IN;PU1,2;')
        h.run_for(0.5)
        r = body(c.call('grid_plotter', action='cancel'))
        assert ': cancelled' in r and h.grid.plot_clears == [] and h.grid.plot_parts == [], (r, h.grid.plot_clears)
        # busy, its buffer frozen (not 3Ch) past PLOT_STUCK, then drawing again: waited for, never cleared
        mcp.PLOT_STUCK, mcp.PLOT_STALL = 1.5, 6
        fresh(plot_held=100, plot_drain=25, plot_frozen_until=time.time() + 3.5)
        c.call('grid_plotter', hpgl='IN;PU1,2;')
        r = plot_to_end(h, c)
        assert ': done' in r and 'Waited for the Nano' in r and h.grid.plot_clears == [], (r, h.grid.plot_clears)
        h.grid.plot_frozen_until = 0
        mcp.PLOT_STALL = 1.5
        # ... frozen for good: failed after PLOT_STALL, nothing sent, not cleared
        fresh(plot_held=100, plot_drain=0)
        c.call('grid_plotter', hpgl='IN;PU1,2;')
        r = plot_to_end(h, c)
        assert ': stopped' in r and 'its status 23h unchanged' in r and 'Nothing was sent; it was not cleared' in r, r
        assert h.grid.plot_clears == [] and h.grid.plot_parts == [], (r, h.grid.plot_clears)
        assert any('plot: stopped after 0 of 9 bytes: The Nano stayed busy' in str(l) for l in h.log), h.log
        # 00h all along (full, or not the Nano): the address asked about, not cleared
        fresh(plot_held=240, plot_drain=0)
        c.call('grid_plotter', hpgl='IN;PU1,2;')
        r = plot_to_end(h, c)
        assert ': stopped' in r and 'GPIB 1 polled 00h, unchanged' in r and '[plotter] address' in r, r
        assert h.grid.plot_clears == [] and h.grid.plot_parts == [], (r, h.grid.plot_clears)
        # RQS while it waits: refused, nothing sent, not cleared
        mcp.PLOT_STALL = 60
        fresh(plot_held=200, plot_drain=0)
        c.call('grid_plotter', hpgl='IN;PU1,2;')
        h.run_for(0.5); h.grid.plot_rqs = True
        r = plot_to_end(h, c)
        h.grid.plot_rqs = False
        assert ': stopped' in r and 'asks for service: it is not the Nano' in r, r
        assert h.grid.plot_clears == [] and h.grid.plot_parts == [], (r, h.grid.plot_clears)
        # empty polls while it waits count as no answer: failed after PLOT_STALL, not cleared
        mcp.PLOT_STALL = 1.5
        fresh(plot_held=200, plot_drain=0)
        c.call('grid_plotter', hpgl='IN;PU1,2;')
        h.run_for(0.3); h.grid.plot_empty = True
        r = plot_to_end(h, c)
        h.grid.plot_empty = False
        assert ': stopped' in r and 'serial polls came back empty' in r and h.grid.plot_clears == [], r
        # a label left open, every other poll failing: still cleared after PLOT_STUCK, then plotted
        mcp.PLOT_STALL = 60
        fresh(plot_open=True, plot_poll_fail=2)
        c.call('grid_plotter', hpgl='IN;PU1,2;')
        r = plot_to_end(h, c)
        h.grid.plot_poll_fail = 0
        assert ': done' in r and 'The Nano was stuck' in r and h.grid.plot_clears == [0], (r, h.grid.plot_clears)
        # the GRiD stops answering while it waits: no clear; failed after PLOT_STALL s
        mcp.PLOT_STALL = 1.5
        fresh(plot_held=200, plot_drain=0)
        c.call('grid_plotter', hpgl='IN;PU1,2;')
        h.grid.plot_mute = True
        r = plot_to_end(h, c)
        h.grid.plot_mute = False
        assert ': stopped' in r and 'The GRiD stopped answering' in r and h.grid.plot_clears == [], (r, h.grid.plot_clears)
        mcp.PLOT_STUCK = 1.5
        # ... and while it sends: no clear either
        fresh(plot_drain=0)
        c.call('grid_plotter', hpgl=''.join('PD%d,%d;' % (i, i) for i in range(100)))
        until_parts(1)
        h.grid.plot_mute = True
        r = plot_to_end(h, c)
        h.grid.plot_mute = False
        assert ': stopped' in r and 'The GRiD stopped answering' in r and h.grid.plot_clears == [], (r, h.grid.plot_clears)
        mcp.PLOT_STALL = stall
        # a stall (no room for PLOT_STALL s): cleared as it fails
        mcp.PLOT_STALL = 1.5
        fresh(plot_drain=0)
        c.call('grid_plotter', hpgl=''.join('PD%d,%d;' % (i, i) for i in range(100)))
        r = plot_to_end(h, c)
        assert ': stopped' in r and 'no room' in r, r
        assert h.grid.plot_clears == [len(h.grid.plot_parts)] and h.grid.plot_parts, (h.grid.plot_clears, r)
        mcp.PLOT_STALL = stall
        # a cancel inside a label that holds a ';', after the first write and after the second: the clear,
        # then ETX and "PU;"; then a plot with no label goes as ever
        lab = 'IN;PU0,0;LB' + 'a' * 300 + ';' + 'b' * 300 + '\x03;PU;PA10,10;'
        for k in (1, 2):
            fresh(plot_drain=0)                         # (the pen still: no room after each part)
            c.call('grid_plotter', hpgl=lab)
            until_parts(1)
            if k == 2:
                h.grid.plot_held = 0; until_parts(2)    # (room for one more part)
            r = body(c.call('grid_plotter', action='cancel'))
            parts = h.grid.plot_parts
            assert ': cancelled' in r and 'not have stopped' not in r, r
            assert len(parts) == k + 1 and parts[-1] == b'\x03PU;' and h.grid.plot_clears == [k], (k, parts)
            assert b''.join(parts[:k]) == lab.encode()[:240 * k], (k, parts)
            fresh()
            c.call('grid_plotter', hpgl='IN;PU1,2;PD3,4;PU;')
            r = plot_to_end(h, c)
            assert ': done' in r and h.grid.plot_parts == [b'IN;PU1,2;PD3,4;PU;'] and h.grid.plot_clears == [], r
        # the pen-up can't be sent after a cut inside a label: said, with what an older Nano does next
        fresh(plot_drain=0)
        c.call('grid_plotter', hpgl=lab)
        until_parts(1)
        h.grid.plot_fail_after = 1
        r = body(c.call('grid_plotter', action='cancel'))
        h.grid.plot_fail_after = None
        assert ': cancelled' in r and 'may not have stopped cleanly' in r and h.grid.plot_clears == [1], r
        assert 'still inside the label and will take the next drawing as its text: switch it off and on' in r, r
        # a 239-byte PA list, then a label at once: no part ends between its L and B
        lst = 'PA' + '1,2,' * 59 + '1'
        assert len(lst) == 239
        data = lst + 'LBab;cd\x03;PU;'
        fresh()
        c.call('grid_plotter', hpgl=data)
        r = plot_to_end(h, c)
        parts = h.grid.plot_parts
        assert ': done' in r and b''.join(parts) == data.encode() and parts[0] == lst.encode(), (r, parts)
        at = 0
        for p in parts[:-1]:
            at += len(p); assert at != 240, parts
    finally:
        mcp.PLOT_STUCK, mcp.PLOT_STALL = stuck, stall
        c.close(); h.close()


def test_plotter_start_on_a_clock():
    """settle()'s limits as they ship (PLOT_STUCK 60 s, PLOT_STALL 200 s), on a clock of the test's own: a
    poll script by the time, a GridError for a failed poll, the clears recorded."""
    class Tools:
        def __init__(t): t.lines = []
        def log(t, m): t.lines.append(m)
    def job(first, at, data=b'IN;PU1,2;', clear_fails=None):
        """at(t, j) -> a status byte, None (an empty poll), or an exception to raise"""
        j = mcp.PlotJob(Tools(), 1, data, 1000, first=first)
        now = [0.0]; j.clears = []; j.writes_ = []
        def sleep(d):
            now[0] += d
            assert now[0] < 10000, 'never ends'
        def poll():
            j.polls += 1; got = at(now[0], j)
            if isinstance(got, Exception): raise got
            return got
        def clear(cancellable=False):
            j.clears.append(now[0]); return clear_fails
        def gpib(op, data=b'', flags=0, cancellable=False):
            j.writes_.append(bytes(data)); return b''
        j.clock, j.sleep, j.poll, j.clear, j.gpib = (lambda: now[0]), sleep, poll, clear, gpib
        j.now = now
        return j
    assert mcp.PLOT_STUCK == 60 and mcp.PLOT_STALL == 200
    E = mcp.GridError('busy')
    # a frozen buffer (not 3Ch): no clear before PLOT_STALL, then failed, nothing sent, not cleared
    j = job(0x23, lambda t, j: 0x23)
    assert not j.settle() and j.state == 'failed' and j.clears == [], (j.state, j.clears)
    assert 200 <= j.now[0] <= 202 and 'stayed busy for 200 s, its status 23h unchanged' in j.error, (j.now, j.error)
    assert any('plot: stopped after 0 of 9 bytes' in l for l in j.tools.lines), j.tools.lines
    # ... frozen for 190 s, then drawing again and idle: waited for, not cleared
    j = job(0x23, lambda t, j: 0x23 if t < 190 else 0x30 if t < 195 else 0x80 | 0x3C)
    assert j.settle() and j.state == 'sending' and j.clears == [] and 'Waited' in j.note, (j.state, j.clears)
    # 3Ch unchanged: cleared at PLOT_STUCK, not before
    j = job(0x3C, lambda t, j: 0x3C)
    assert j.settle() and len(j.clears) == 1 and 60 <= j.clears[0] <= 62, j.clears
    assert 'its status 3Ch, its buffer empty but not idle, unchanged for 60 s' in j.note, j.note
    # ... reached after a change: counted from the change
    j = job(0x10, lambda t, j: 0x10 if t < 30 else 0x3C)
    assert j.settle() and len(j.clears) == 1 and 90 <= j.clears[0] <= 92, j.clears
    # 00h all along: the address asked about, not cleared
    j = job(0x00, lambda t, j: 0x00)
    assert not j.settle() and j.clears == [] and 'GPIB 1 polled 00h, unchanged, for 200 s' in j.error, j.error
    # ... 00h after a change: the busy Nano's message
    j = job(0x08, lambda t, j: 0x08 if t < 10 else 0x00)
    assert not j.settle() and j.clears == [] and 'its status 00h unchanged' in j.error, j.error
    # RQS at the start: refused, no poll, no clear; and during the wait
    j = job(0x40 | 0x3C, lambda t, j: 0x3C)
    assert not j.settle() and j.state == 'failed' and j.polls == 0 and j.clears == [], (j.state, j.polls)
    assert j.error == 'GPIB 1 asks for service: it is not the Nano. Nothing was sent.', j.error
    j = job(0x23, lambda t, j: 0x23 if t < 5 else 0x40 | 0x23)
    assert not j.settle() and j.clears == [] and 'asks for service' in j.error and j.now[0] < 7, (j.now, j.error)
    # poll errors mixed with unchanged answers: the busy stall (not "stopped answering"), not cleared
    j = job(0x23, lambda t, j: E if j.polls % 2 else 0x23)
    assert not j.settle() and j.clears == [] and 'stayed busy' in j.error and j.now[0] <= 202, (j.now, j.error)
    # ... with 3Ch: cleared at PLOT_STUCK as ever
    j = job(0x3C, lambda t, j: E if j.polls % 2 else 0x3C)
    assert j.settle() and len(j.clears) == 1 and j.clears[0] <= 62, j.clears
    # errors only: the GRiD stopped answering, after PLOT_STALL
    j = job(0x23, lambda t, j: E)
    assert not j.settle() and j.clears == [] and 'The GRiD stopped answering: busy.' in j.error, j.error
    assert 200 <= j.now[0] <= 202, j.now
    # empty polls count as no answer, alone and mixed with errors
    j = job(0x23, lambda t, j: None)
    assert not j.settle() and j.clears == [] and 'came back empty for 200 s' in j.error and j.now[0] <= 202, j.now
    j = job(0x23, lambda t, j: E if j.polls % 2 else None)
    assert not j.settle() and j.clears == [] and j.now[0] <= 202, (j.now, j.error)
    # a cancel during the poll that would have cleared (3Ch at PLOT_STUCK): nothing cleared, nothing sent;
    # run() sends nothing after it either (no halt: no clear, no "PU;")
    def cancel_at_60(t, j):
        if t >= 60: j.cancel = True
        return 0x3C
    j = job(0x3C, cancel_at_60)
    j.run()
    assert j.state == 'cancelled' and j.clears == [] and j.writes_ == [] and j.sent == 0, (j.state, j.clears)
    # a cancel that comes while the stuck clear waits for the tools' lock (another tool call holds it): the
    # clear is not sent, and run() sends nothing after it
    class CancelOnLock:
        def __init__(t, j): t.j = j; t.lk = threading.Lock()
        def __enter__(t): t.j.cancel = True; t.lk.acquire()
        def __exit__(t, *e): t.lk.release()
    class G:
        def __init__(t): t.ops = []
        def gpib(t, op, *a, **k): t.ops.append(op); return b''
    j = job(0x3C, lambda t, j: 0x3C)
    del j.clear, j.gpib                     # (the job's own: the lock, then the GRiD)
    j.tools.lock = CancelOnLock(j); j.tools.G = G()
    j.tools.available = lambda tool: None; j.tools.away = lambda: False
    j.run()
    assert j.state == 'cancelled' and j.tools.G.ops == [] and j.sent == 0, (j.state, j.tools.G.ops, j.error)
    # ... and a cancel already set when settle() hands over (an idle Nano: no poll, no look): no halt, so
    # no clear and no "PU;"; said as nothing sent
    j = job(0x80 | 0x3C, lambda t, j: 0x3C)
    j.cancel = True
    j.run()
    assert j.state == 'cancelled' and j.clears == [] and j.writes_ == [] and j.sent == 0, (j.state, j.clears)
    assert j.error == 'Nothing was sent.' and ': cancelled. 0 of 9 bytes sent' in j.report(), j.report()
    # failed() keeps the start's note: the stuck clear failed, then a write fails
    def write_fails(op, data=b'', flags=0): raise mcp.GridError('no listener')
    j = job(0x3C, lambda t, j: 0x3C, clear_fails='timeout')
    j.gpib = write_fails
    j.run()
    assert j.state == 'failed' and j.error.startswith('The Nano was not cleared: timeout;'), j.error
    assert 'A write failed (no listener)' in j.error, j.error
    assert any('stopped after 0 of 9 bytes: A write failed' in l and '(the clear failed: timeout)' in l
               for l in j.tools.lines), j.tools.lines
    # a bug inside run(): failed and logged, never left 'sending'
    j = job(0x80 | 0x3C, lambda t, j: ValueError('a bug'))
    j.run()
    assert j.state == 'failed' and "gridlink's plot failed (ValueError: a bug); nothing was sent." in j.error, j.error
    assert any('Traceback' in l for l in j.tools.lines), j.tools.lines
    # a cancel's outcome is logged
    j = job(0x80 | 0x3C, lambda t, j: 0x3C)
    j.sent = 3; j.ends = [3, 9]
    j.halt()
    assert any("plot: cancelled after 3 of 9 bytes: cleared; b'PU;' sent" in l for l in j.tools.lines), j.tools.lines


def test_hpgl_ends():
    d = b'IN;SP1;LBA;B\x03;PU1,2;LBno end'
    assert mcp.hpgl_ends(d) == [3, 7, 14, 20, len(d)], mcp.hpgl_ends(d)
    assert mcp.hpgl_ends(b'PA1,2') == [5]                    # no final ';'
    assert mcp.hpgl_ends(b'IN;SP1;PU0,0;PD100,0;') == [3, 7, 13, 21]
    lb = b'PU10,10;LBVOLTS; AMPS;\x03;PD20,20;'           # a label's ';' is not a command's end
    assert mcp.hpgl_ends(lb) == [8, 24, 32], mcp.hpgl_ends(lb)
    assert mcp.hpgl_ends(b'LBno end') == [8]                 # an unterminated label: all of it
    big = b';'.join(b'PD%d,%d' % (i, i) for i in range(3000)) + b';'
    e = mcp.hpgl_ends(big)
    assert len(e) == 3000 and e[-1] == len(big) and all(big[i - 1:i] == b';' for i in e)
    # (hpgl_parts went: its hpgl_check cases are here)
    for bad in (b'', b' ;\r\n', b'IN;\x07', b'IN;\x00', b'LB\xe9\x03',
                b'IN;LBHI', b'LBA\x03;PU;BLabc', b'wdNO END'):        # a label left open
        try: mcp.hpgl_check(bad); assert False, bad
        except ValueError: pass
    assert mcp.hpgl_check(b'IN;\r\nLBHI\x03;\tPU;') == b'IN;\r\nLBHI\x03;\tPU;'
    assert mcp.hpgl_check(b'PU;\r\n') == b'PU;\r\n'
    assert mcp.hpgl_check(b'IN;PA1,2') == b'IN;PA1,2;'      # the Nano would hold the last point
    assert mcp.hpgl_check(b'LBHI\x03') == b'LBHI\x03;'
    assert mcp.hpgl_check(b'IN;\x1bAJ30;LBa\x0eb\x0fc\x03;') == b'IN;\x1bAJ30;LBa\x0eb\x0fc\x03;'  # 4662 commands, SO/SI


def test_plotter_bad_arguments_never_reach_the_grid():
    t = mcp.GridTools(NoGrid(), root='/nonexistent')
    for a in ({}, {'hpgl': ''}, {'hpgl': 'IN;', 'file': 'x.plt'}, {'hpgl': 'IN;\x07'}, {'hpgl': 'PA☃;'},
              {'hpgl': 'x' * (mcp.MAX_HPGL + 1)}, {'hpgl': 'IN;', 'timeout_ms': 10}, {'file': '../etc/passwd'},
              {'file': '.mcp.json'}, {'hpgl': 5}, {'action': 'bogus', 'hpgl': 'IN;'}):
        res, err = t.call('grid_plotter', a)
        assert err, a
    class Cfg: plotter = 7
    res, err = mcp.GridTools(NoGrid(), cfg=Cfg(), root='/nonexistent').call('grid_plotter', {'hpgl': 'IN;'})
    assert err and 'bridge' in body({'content': res}), res


def test_plotter_config():
    import tempfile
    from gridlink.config import Config
    assert Config().plotter == 1 and 'plotter' in Config().bus[1] and '7854' in Config().bus[3]
    for toml, ok in (('[plotter]\naddress = 5\n', 5), ('[plotter]\naddress = 21\n', None),
                     ('[plotter]\naddress = 7\n', None), ('[plotter]\naddress = "3"\n', None),
                     ('[plotter]\naddress = 31\n', None)):
        with tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False) as f: f.write(toml)
        try:
            cfg = Config().load(f.name)
            assert ok == cfg.plotter, toml
        except SystemExit:
            assert ok is None, toml
        finally:
            os.unlink(f.name)


def test_socket_requests_checked():
    srv = mcp.ToolServer('/nonexistent', mcp.GridTools(NoGrid(), root='/nonexistent'), log=lambda m: None)
    for line in (b'{"tool": "grid_info"', b'[]\n', b'{"tool": 5}\n', b'{"tool": "grid_info", "arguments": []}\n',
                 b'x' * (mcp.MAX_LINE + 1), b'\xff\n'):
        res, err = srv.request(line)
        assert err, line[:40]


def test_bench_edges():
    """gridlink.bench's bounds, --prof under --sweep, no file left on the GRiD, the first error kept."""
    import contextlib, io, tempfile
    from gridlink import bench
    calls = []
    fail = {}

    def fake(sock, name, args):
        calls.append((name, dict(args)))
        if name in fail and fail[name](args):
            return {'isError': True, 'content': [{'type': 'text', 'text': 'boom %s' % name}]}
        if name == '_link':
            return {'content': [{'type': 'text', 'text': json.dumps(
                {'bridge': 'pico', 'maxpay': 2048, 'grid_rx': 2048, 'grid_maxpay': 2048, 'holds': 1,
                 'stats': {}})}]}
        if name == 'grid_change_files' and args['action'] == 'copy_from_grid':
            with open(args['to'], 'wb') as f: f.write(open(os.path.join(d, 'bench.bin'), 'rb').read())
        return {'content': [{'type': 'text', 'text': 'ok'}]}

    def run(*argv):
        del calls[:]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                r = bench.main(['--dir', d, '--size', '1', '--idle', '0'] + list(argv))
            except SystemExit as e:
                r = e
        return r, out.getvalue(), err.getvalue()

    old = bench.call_gridlink, bench.socket_path
    with tempfile.TemporaryDirectory() as d:
        sock = os.path.join(d, 'sock'); open(sock, 'w').close()
        bench.call_gridlink, bench.socket_path = fake, lambda: sock
        try:
            for bad in (['--trips', '0'], ['--idle', '-1'], ['--size', '0']):
                r, _, err = run(*bad)
                assert isinstance(r, SystemExit) and r.code == 2 and 'below' in err, bad
            r, out, _ = run('--trips', '1')
            assert r == 0 and 'every byte right' in out, out
            r, out, _ = run('--trips', '1', '--sweep', '512,1024', '--prof')
            profs = [a['prof'] for n, a in calls if n == '_link' and 'prof' in a]
            assert r == 0 and profs == ['start', 'stop'], profs
            assert [a['frame_cap'] for n, a in calls if 'frame_cap' in a] == [512, 1024, 0]
            # the copy back fails: the GRiD's file is still deleted, and that failure is the one reported
            fail['grid_change_files'] = lambda a: a['action'] == 'copy_from_grid'
            r, _, _ = run('--trips', '1')
            assert isinstance(r, SystemExit) and r.code == 'grid_change_files failed: boom grid_change_files'
            assert any(a.get('action') == 'delete' for n, a in calls), calls
            # ...and with --nohold the restore failing too does not hide it
            fail['_link'] = lambda a: a.get('hold') == 1
            r, _, err = run('--trips', '1', '--nohold')
            assert isinstance(r, SystemExit) and r.code == 'grid_change_files failed: boom grid_change_files', r.code
            assert 'clean-up failed too' in err and any(a.get('action') == 'delete' for n, a in calls)
        finally:
            bench.call_gridlink, bench.socket_path = old


if __name__ == '__main__':
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    bad = 0
    for n in names:
        t0 = time.time()
        try:
            globals()[n]()
            print('ok   %-34s %.1fs' % (n, time.time() - t0))
        except Exception:
            bad += 1
            print('FAIL %s' % n); traceback.print_exc()
    print('%d of %d passed' % (len(names) - bad, len(names)))
    sys.exit(1 if bad else 0)
