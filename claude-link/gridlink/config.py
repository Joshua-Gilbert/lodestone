"""Settings for gridlink: a TOML file plus command-line overrides."""
import os, shlex, sys
try:
    import tomllib
except ImportError:                     # Python < 3.11
    tomllib = None

PATHS = ['~/.config/gridlink/config.toml', '/etc/gridlink/config.toml']

# Joshua's bus (see the GPIB driver notes); edit [bus] in the config file.
DEFAULT_BUS = {
    1: 'Tek 4662 pen plotter (HP-GL, through its Nano; grid_plotter)', 2: 'Tek 11403 digitizing scope',
    3: 'Tek 7854 oscilloscope', 5: 'Tek AFG5101 arbitrary function generator', 6: 'Tek FG5010 function generator',
    11: 'Tek SI5020 switch', 13: 'Tek PS5004 power supply', 16: 'Tek DM5120 DMM',
    17: 'HP 4275A multi-frequency LCR meter',
    18: 'HP 8753D network analyzer', 19: 'HP 8753D, its second address (reserved: not another instrument)',
    28: 'Tek DM5010 DMM', 29: 'Tek DC5009 counter',
    30: 'Tek PS5010 power supply',
}

MODELS = {'opus': 'claude-opus-5-5', 'sonnet': 'claude-sonnet-5-5', 'haiku': 'claude-haiku-4-5',
          'fable': 'claude-fable-5-1'}
# $ per million tokens: input, output (cache reads/writes are derived)
PRICES = {'claude-fable-5-1': (10, 50), 'claude-opus-5-5': (4, 20), 'claude-sonnet-5-5': (2, 10),
          'claude-haiku-4-5': (1, 5)}
CACHE_READ = {'claude-fable-5-1': 0.025, 'claude-opus-5-5': 0.05}


class Config:
    def __init__(s):
        s.bridge = 'pico'                   # pico (the GPIB-Pico2 bridge) or ar488 (the Nano)
        s.port = 'auto'; s.baud = 115200; s.address = 7
        s.model = 'claude-opus-5-5'; s.max_tokens = 32000; s.web = True
        s.compact_at = 300000
        s.set_clock = True; s.mode = 'ask'
        s.auto_mode = []                        # tools Claude Code's own mode decides on (no forced prompt)
        s.measure = []                          # GPIB addresses gpib_measure may query without asking
        s.plotter = 1                           # GPIB address of the 4662's HP-GL Nano (grid_plotter)
        s.workdir = os.path.expanduser('~/gridlink/work')
        s.memory_dir = os.path.expanduser('~/gridlink/memories')
        s.sessions_dir = os.path.expanduser('~/gridlink/sessions')
        s.bash_timeout = 180
        s.bus = dict(DEFAULT_BUS)
        s.api_key = None; s.user = 'Joshua'
        s.extra_prompt = ''
        s.app = 'auto'                          # chat, term, or auto (chat when there is a key)
        s.term_command = 'claude'               # Term: the program in the pty
        s.term_dir = os.path.expanduser('~/grid')
        s.term_socket = None                    # MCP bridge socket (default $XDG_RUNTIME_DIR/gridlink.sock)
        s.term_api_key = False                  # pass ANTHROPIC_API_KEY on to Claude Code (normally not)
        # CLAUDE /W: Firefox as text (gridfox) in the pty, on gridlink's own
        # Python (the venv: wcwidth is there, through pyte)
        s.web_command = '%s -m gridfox' % shlex.quote(sys.executable)
        s.web_dir = os.path.expanduser('~/.cache/gridfox')   # where it runs (not ~/grid)
        s.source = None

    def load(s, path=None):
        cands = [path] if path else PATHS
        for p in cands:
            p = os.path.expanduser(p)
            if p and os.path.exists(p):
                if tomllib is None: raise SystemExit('Python 3.11+ is needed to read %s' % p)
                with open(p, 'rb') as f: d = tomllib.load(f)
                s.apply(d); s.source = p
                break
        return s

    def apply(s, d):
        b = d.get('bridge', {}); c = d.get('claude', {}); g = d.get('grid', {}); pm = d.get('permissions', {})
        s.bridge = str(b.get('kind', s.bridge)).lower()
        s.port = b.get('port', s.port); s.baud = int(b.get('baud', s.baud)); s.address = int(b.get('address', s.address))
        s.model = MODELS.get(c.get('model', ''), c.get('model', s.model))
        s.max_tokens = int(c.get('max_tokens', s.max_tokens)); s.web = bool(c.get('web', s.web))
        s.compact_at = int(c.get('compact_at', s.compact_at))
        s.extra_prompt = c.get('extra_prompt', s.extra_prompt)
        key = c.get('api_key'); keyfile = c.get('api_key_file')
        if key: s.api_key = key
        elif keyfile and os.path.exists(os.path.expanduser(keyfile)):
            s.api_key = open(os.path.expanduser(keyfile)).read().strip()
        s.set_clock = bool(g.get('set_clock', s.set_clock)); s.user = g.get('user', s.user)
        s.app = str(g.get('app', s.app)).lower()
        t = d.get('term', {})
        s.term_command = t.get('command', s.term_command)
        if 'dir' in t: s.term_dir = os.path.expanduser(t['dir'])
        if 'socket' in t: s.term_socket = t['socket']
        s.term_api_key = bool(t.get('keep_api_key', s.term_api_key))
        w = d.get('web', {})
        s.web_command = w.get('command', s.web_command)
        if 'dir' in w: s.web_dir = os.path.expanduser(w['dir'])
        for k in ('workdir', 'memory_dir', 'sessions_dir'):
            if k in g: setattr(s, k, os.path.expanduser(g[k]))
        s.bash_timeout = int(g.get('bash_timeout', s.bash_timeout))
        s.mode = pm.get('mode', s.mode)
        if 'measure' in pm:
            m = pm['measure']
            if not isinstance(m, list) or not all(isinstance(a, int) and not isinstance(a, bool) and 0 <= a <= 30
                                                  for a in m):
                raise SystemExit('[permissions] measure must be a list of GPIB addresses (0-30)')
            s.measure = sorted(set(m))
        if 'auto_mode' in pm:
            m = pm['auto_mode']; ok = ('gpib_send', 'grid_command', 'grid_change_files', 'grid_type', 'grid_plotter')
            if not isinstance(m, list) or not all(x in ok for x in m):
                raise SystemExit('[permissions] auto_mode must list some of: %s' % ', '.join(ok))
            s.auto_mode = sorted(set(m))
        if 'bus' in d:
            s.bus = {int(k): str(v) for k, v in d['bus'].items()}
        if 'address' in d.get('plotter', {}):
            a = d['plotter']['address']
            if not isinstance(a, int) or isinstance(a, bool) or not 0 <= a <= 30 or a in (21, s.address):
                raise SystemExit('[plotter] address must be a GPIB address (0-30), not 21 (the GRiD) or '
                                 'the bridge\'s (%d)' % s.address)
            s.plotter = a

    def env_key(s):
        return bool(os.environ.get('ANTHROPIC_API_KEY'))

    def price(s, model=None):
        return PRICES.get(model or s.model, (4, 20))
