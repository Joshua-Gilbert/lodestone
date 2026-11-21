"""What gridlink's log says when something stops (P13): a handler's traceback, a late REPLY, calls left waiting,
and -v's debug lines from the link's trace.

    python3 tests/test_logs.py
"""
import collections, json, os, re, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gridlink import glp
from gridlink.grid import Grid, GridError
from gridlink.link import Link, DebugTrace


class Sink:
    frame_limit = glp.PATCHED_FRAME_MAX
    def __init__(s): s.out = []
    def answer(s, frame): s.out.append(frame)


class FakeLink:
    def __init__(s): s.log_lines = []; s.sent = []
    def log(s, m): s.log_lines.append(m)
    def send(s, t, body=b''): s.sent.append((t, body))
    def withdraw(s, t, body): return False


def frame(kind, seq, payload=b''):
    return glp.encode(kind, seq, 0, payload, fl=True)


def test_handler_traceback():
    log = []
    def boom(mt, body): raise KeyError('nope')
    L = Link(Sink(), boom, log=log.append, hold=0)
    L.feed(frame(glp.G_HELLO, 1, bytes([1, glp.GF_FCS, 0, 4, 80, 24])))
    err = [l for l in log if 'handler error' in l]
    assert len(err) == 1 and 'Traceback' in err[0] and "KeyError: 'nope'" in err[0] and 'boom' in err[0], log


def test_late_reply():
    fl = FakeLink(); g = Grid(fl)
    g.on_reply(bytes([9, 0]) + b'out')               # (no call 9 waiting: a RUN's answer after its time-out)
    assert g.late == 1 and len(fl.log_lines) == 1 and 'late REPLY (id 9' in fl.log_lines[0], fl.log_lines
    g.waiting[3] = glp.OP_RUN; g.dead[3] = 'ended'
    g.on_reply(bytes([3, 0]))                        # (its call ended by a HELLO)
    assert g.late == 2 and '2 so far' in fl.log_lines[-1], fl.log_lines
    g.waiting[4] = glp.OP_DIR
    g.on_reply(bytes([4, 0]) + b'x')                 # (one that is waited for: not late)
    assert g.late == 2 and len(fl.log_lines) == 2 and g.replies[4] == (0, b'x')


def test_calls_waiting_backs_off():
    fl = FakeLink(); g = Grid(fl)
    g.waiting = {1: glp.OP_RUN, 2: glp.OP_DIR}; g.since = {1: 1000.0, 2: 1030.0}
    g._note_waiting(1050.0)                          # (the oldest 50 s: nothing yet)
    assert not fl.log_lines
    g._note_waiting(1061.0)
    assert len(fl.log_lines) == 1 and '2 calls waiting' in fl.log_lines[0] and '61 s' in fl.log_lines[0], fl.log_lines
    for now, n in ((1110.0, 1), (1121.0, 2), (1230.0, 2), (1241.0, 3), (1470.0, 3), (1481.0, 4)):
        g._note_waiting(now)                         # (at 1, 2, 4, 8 minutes)
        assert len(fl.log_lines) == n, (now, fl.log_lines)
    del g.waiting[1], g.since[1]                     # (the oldest done: the next one from a minute again)
    g._note_waiting(1490.0)
    assert len(fl.log_lines) == 5 and '1 call waiting' in fl.log_lines[-1] and '460 s' in fl.log_lines[-1]


def test_calls_waiting_from_call():
    # Grid.call's own loop, a RUN the GRiD never answers, on a clock 10 s a read: said at 1, 2, 4, 8 and 16
    # minutes, not every minute
    import gridlink.grid as grid_mod
    class Clock:
        t = 1000.0
        def monotonic(s): s.t += 10.0; return s.t
    fl = FakeLink(); g = Grid(fl)
    g.cv.wait = lambda timeout=None: True
    old = grid_mod.time; grid_mod.time = Clock()
    try:
        g.call(glp.OP_RUN, b'X', timeout=1000.0)
    except GridError:
        pass
    else:
        raise AssertionError('no time-out')
    finally:
        grid_mod.time = old
    ages = [int(re.search(r'oldest for (\d+) s', l).group(1)) for l in fl.log_lines if 'waiting' in l]
    assert len(ages) == 5 and all(60 * 2 ** k <= a < 60 * 2 ** k + 30 for k, a in enumerate(ages)), fl.log_lines
    assert not g.since and fl.sent and fl.sent[0][0] == glp.P_REQUEST


def test_router_dropped_before_app():
    # a message before the GRiD's HELLO chose an app (a fresh gridlink under a running CLAUDE): said once,
    # a POLL not at all
    from gridlink.router import Router
    class Cfg:
        app = 'auto'; api_key = None
        def env_key(s): return False
    log = []
    R = Router(Cfg(), log=log.append)
    R.on_message(glp.G_POLL, b'')
    assert not log, log
    R.on_message(glp.G_PROMPT, b'hello')
    R.on_message(glp.G_PROMPT, b'again')
    assert len(log) == 1 and 'before any app was chosen: dropped' in log[0], log


def test_verbose_wiring():
    # main()'s -v: the Link's trace and the Pico's PicoProto.trace are one DebugTrace, kept as trace_sink
    # (what the MCP bridge's trace 'stop' puts back); without -v, no trace
    import gridlink.__main__ as M
    from gridlink.pico import PicoProto
    got = {}
    class Bridge:
        frame_limit = glp.PATCHED_FRAME_MAX; patched = True; version = 'test'
        def __init__(s, *a, **kw):
            s.proto = PicoProto(lambda d: None, log=lambda *a: None); got['t'] = s
        def open(s): pass
        def configure(s): return s.version
        def answer(s, frame): pass
    def serve(t, link, stop): got['link'] = link
    old = M.PicoBridge, M.serve
    M.PicoBridge, M.serve = Bridge, serve
    env = os.environ.pop('ANTHROPIC_API_KEY', None)
    try:
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'c.toml'); open(p, 'w').write('[bridge]\nkind = "pico"\n')
            M.main(['--config', p])
            L = got['link']
            assert L.trace is None and L.trace_sink is None and got['t'].proto.trace is None
            M.main(['--config', p, '-v'])
            L = got['link']
            assert isinstance(L.trace, DebugTrace) and L.trace is L.trace_sink, (L.trace, L.trace_sink)
            assert got['t'].proto.trace is L.trace
    finally:
        M.PicoBridge, M.serve = old
        if env is not None: os.environ['ANTHROPIC_API_KEY'] = env


def test_trace_stop_restores_sink():
    # the MCP bridge's _link trace (gridlink.bench --trace) under -v: 'stop' with no 'start' is an empty trace
    # (the DebugTrace is no list), and 'stop' puts the DebugTrace back
    from gridlink.mcp import ToolServer
    lines = []
    L = Link(Sink(), lambda mt, body: None, log=lambda *a: None, hold=0)
    L.trace = L.trace_sink = DebugTrace(lines.append)
    class NS: pass
    tools = NS(); tools.G = NS(); tools.G.link = L
    srv = ToolServer('/nonexistent/gridlink.sock', tools, log=lambda *a: None)
    def trace(what):
        out, err = srv.link_request({'trace': what})
        assert not err, out
        return json.loads(out[0]['text'])
    assert trace('stop')['trace'] == [] and L.trace is L.trace_sink
    trace('start')
    assert isinstance(L.trace, collections.deque)
    L.feed(frame(glp.G_HELLO, 1, bytes([1, glp.GF_FCS, 0, 4, 80, 24])))
    assert not lines
    tr = trace('stop')['trace']
    assert [e for _, e in tr][:2] == ['grid HELLO', 'pi NOP'] and L.trace is L.trace_sink, tr
    L.feed(frame(glp.G_POLL, 2))
    assert lines == ['trace: grid POLL', 'trace: pi NOP'], lines


def test_verbose_trace():
    lines = []
    L = Link(Sink(), lambda mt, body: None, log=lambda *a: None, hold=0)
    L.trace = DebugTrace(lines.append)
    L.feed(frame(glp.G_HELLO, 1, bytes([1, glp.GF_FCS, 0, 4, 80, 24])))
    L.feed(frame(glp.G_POLL, 2))
    assert lines == ['trace: grid HELLO', 'trace: pi NOP', 'trace: grid POLL', 'trace: pi NOP'], lines


if __name__ == '__main__':
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    if len(sys.argv) > 1: names = [n for n in names if any(a in n for a in sys.argv[1:])]
    ok = 0
    for n in names:
        try:
            globals()[n](); ok += 1; print('ok  ', n)
        except Exception:
            import traceback; print('FAIL', n); traceback.print_exc()
    print('%d of %d passed' % (ok, len(names)))
    sys.exit(0 if ok == len(names) else 1)
