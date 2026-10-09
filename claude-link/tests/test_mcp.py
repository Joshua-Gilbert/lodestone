"""The MCP bridge (Term): Claude Code's stdio MCP server -> Unix socket ->
gridlink -> GLP REQUEST -> the GRiD (GridSim), and back.

    python3 tests/test_mcp.py
"""
import json, os, subprocess, sys, threading, time
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
    names = [t['name'] for t in r['result']['tools']]
    assert names == ['grid_command', 'grid_files', 'grid_screen', 'grid_info', 'gpib'], names
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
    a = mcp.local_paths('grid_files', {'action': 'copy_to_grid', 'path': 'foo.txt', 'to': 'A:\\FOO.TXT'})
    assert a['path'] == os.path.join(here, 'foo.txt'), a
    a = mcp.local_paths('grid_files', {'action': 'copy_from_grid', 'path': 'A:\\TM5000\\CFG.C'})
    assert a['to'] == os.path.join(here, 'CFG.C'), a
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
        assert len(c.rpc('tools/list')['result']['tools']) == 5
        r = c.call('grid_files', action='list', path='A:\\')
        assert 'CFG.C' in body(r) and not r['isError'], r
        r = c.call('grid_files', action='read', path='a:\\cfg.c')
        assert body(r) == CFG_C.decode().replace('\r\n', '\n'), r
        r = c.call('grid_files', action='write', path='A:\\NEW.TXT', content='caf\u00e9\nline 2\n')
        assert not r['isError'] and h.grid.fs['A:\\NEW.TXT'] == b'caf\x82\r\nline 2\r\n', h.grid.fs
        assert 'A:\\NEW.$$$' not in h.grid.fs
        pi = os.path.join(h.tmp, 'cfg.c')
        r = c.call('grid_files', action='copy_from_grid', path='A:\\CFG.C', to=pi)
        assert open(pi, 'rb').read() == CFG_C, r
        open(pi, 'wb').write(CFG_C.replace(b'rate = 1', b'rate = 5'))
        r = c.call('grid_files', action='copy_to_grid', path=pi, to='A:\\CFG.C')
        assert h.grid.fs['A:\\CFG.C'] == CFG_C.replace(b'rate = 1', b'rate = 5'), r
        r = c.call('grid_files', action='delete', path='A:\\NOPE.TXT')
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
        r = c.call('gpib', action='query', address=29, command='ID?')
        assert body(r) == 'ID TEK/DC5009,V79.1,F1.2', r
        r = c.call('gpib', action='scan')
        assert '6, 16, 29' in body(r), r
        r = c.call('gpib', action='write', address=7, command='X')
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
        h.link.last_rx = time.time() - 60
        r = c.rpc('tools/call', {'name': 'grid_info', 'arguments': {}})['result']
        assert r['isError'] and 'not connected' in body(r), r
    finally:
        c.close(); h.close()


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
