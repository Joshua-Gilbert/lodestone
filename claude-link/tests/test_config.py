"""gridlink's settings (gridlink/config.py, P14): a bad number named by its key, 0 taken from the command line, the
API key file's mode, and a key file that isn't there, or can't be read, said without an exit.

    python3 tests/test_config.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gridlink import config as C
from gridlink.config import Config


def load(toml):
    with tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False) as f: f.write(toml)
    try:
        return Config().load(f.name)
    finally:
        os.unlink(f.name)


def refused(toml):
    """-> the SystemExit's text, or None if it loaded."""
    try:
        load(toml)
    except SystemExit as e:
        return str(e)
    return None


def test_numbers_named():
    for toml, key in (('[bridge]\nbaud = "fast"\n', '[bridge] baud'), ('[bridge]\naddress = 31\n', '[bridge] address'),
                      ('[bridge]\naddress = 21\n', '[bridge] address'),
                      ('[claude]\nmax_tokens = "lots"\n', '[claude] max_tokens'),
                      ('[claude]\ncompact_at = 1.5\n', '[claude] compact_at'),
                      ('[grid]\nbash_timeout = true\n', '[grid] bash_timeout'),
                      ('[grid]\nbash_timeout = 0\n', '[grid] bash_timeout'),
                      ('[permissions]\nmeasure = [3, 40]\n', '[permissions] measure'),
                      ('[permissions]\nmeasure = 3\n', '[permissions] measure'),
                      ('[plotter]\naddress = 7\n', '[plotter] address')):
        why = refused(toml)
        assert why and why.startswith(key + ' must be'), (toml, why)
    c = load('[bridge]\nbaud = 9600\naddress = 0\n[claude]\nmax_tokens = 8000\n[grid]\nbash_timeout = 30\n'
             '[permissions]\nmeasure = [16, 3, 16]\n[plotter]\naddress = 2\n')
    assert (c.baud, c.address, c.max_tokens, c.bash_timeout, c.measure, c.plotter) == (9600, 0, 8000, 30, [3, 16], 2)


def test_command_line_zero():
    # --address 0 and --baud given are taken (0 was dropped as "not given"); a bad one is named
    import gridlink.__main__ as M
    seen = []
    class Seen(Config):
        def load(s, path=None):
            seen.append(s); return Config.load(s, path)
    old, M.Config = M.Config, Seen
    env = os.environ.pop('ANTHROPIC_API_KEY', None)
    try:
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'c.toml'); open(p, 'w').write('[bridge]\naddress = 7\n')
            for argv, want in ((['--address', '0', '--baud', '300'], (0, 300)), (['--address', '21'], '--address'),
                               (['--baud', '0'], '--baud')):
                del seen[:]
                try:
                    M.main(['--config', p, '--console'] + argv)
                except SystemExit as e:
                    why = str(e)
                if isinstance(want, tuple):
                    assert why.startswith('No API key') and (seen[0].address, seen[0].baud) == want, (argv, why)
                else:
                    assert why.startswith(want + ' must be'), (argv, why)
    finally:
        M.Config = old
        if env is not None: os.environ['ANTHROPIC_API_KEY'] = env


def test_key_file():
    with tempfile.TemporaryDirectory() as d:
        k = os.path.join(d, 'api_key')
        # not there: said, no exit (the shipped config names it; Term-only installs never make it), and not
        # "chat is off": ANTHROPIC_API_KEY may still give the key
        c = load('[claude]\napi_key_file = "%s"\n' % k)
        assert c.api_key is None and len(c.warnings) == 1 and 'not there' in c.warnings[0], c.warnings
        assert 'ANTHROPIC_API_KEY' in c.warnings[0] and 'chat is off' not in c.warnings[0], c.warnings
        open(k, 'w').write('sk-test\n'); os.chmod(k, 0o644)
        c = load('[claude]\napi_key_file = "%s"\n' % k)
        assert c.api_key == 'sk-test' and len(c.warnings) == 1 and 'chmod 600' in c.warnings[0], c.warnings
        os.chmod(k, 0o600)
        c = load('[claude]\napi_key_file = "%s"\n' % k)
        assert c.api_key == 'sk-test' and not c.warnings, c.warnings
        # one the service user can't read (or a directory): a line naming the setting, not a traceback
        bad = [os.path.join(d, 'adir')]
        os.mkdir(bad[0])
        if os.geteuid() != 0:                        # (root reads a mode 000 file)
            os.chmod(k, 0o000); bad.append(k)
        for p in bad:
            c = load('[claude]\napi_key_file = "%s"\n' % p)
            assert c.api_key is None and len(c.warnings) == 1, (p, c.warnings)
            assert c.warnings[0].startswith('[claude] api_key_file %s cannot be read' % p), c.warnings
        os.chmod(k, 0o600)


def test_chat_off_said_by_main():
    # a key file not there: main() says chat is off only when ANTHROPIC_API_KEY isn't set either
    import logging
    import gridlink.__main__ as M
    class Bridge:
        frame_limit = 3000; patched = True; version = 'test'
        def __init__(s, *a, **kw): pass
        def open(s): pass
        def configure(s): return s.version
        def answer(s, frame): pass
    lines = []
    class Keep(logging.Handler):
        def emit(s, r): lines.append(r.getMessage())
    h = Keep(); logging.getLogger('gridlink').addHandler(h)
    old = M.PicoBridge, M.serve
    M.PicoBridge, M.serve = Bridge, lambda t, link, stop: None
    env = os.environ.pop('ANTHROPIC_API_KEY', None)
    import types
    fake = 'anthropic' not in sys.modules            # (main() imports it in a thread when there is a key)
    if fake: sys.modules['anthropic'] = types.ModuleType('anthropic')
    try:
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'c.toml')
            open(p, 'w').write('[claude]\napi_key_file = "%s"\n' % os.path.join(d, 'none'))
            for env_key, off in ((None, True), ('sk-env', False)):
                if env_key: os.environ['ANTHROPIC_API_KEY'] = env_key
                del lines[:]
                M.main(['--config', p])
                assert any('api_key_file' in l and 'not there' in l for l in lines), lines
                assert any('chat is off' in l for l in lines) == off, (env_key, lines)
    finally:
        M.PicoBridge, M.serve = old
        logging.getLogger('gridlink').removeHandler(h)
        if fake: sys.modules.pop('anthropic', None)
        os.environ.pop('ANTHROPIC_API_KEY', None)
        if env is not None: os.environ['ANTHROPIC_API_KEY'] = env


def test_shipped_config():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    c = Config().load(os.path.join(here, 'config.example.toml'))
    assert c.bridge == 'pico' and c.port == 'auto' and not c.baud_set and c.address == 7, (c.bridge, c.port)


def test_int_in():
    assert C.int_in('x', 5, 0, 9) == 5
    for v in (True, '5', 5.0, -1, 10):
        try:
            C.int_in('[s] x', v, 0, 9); raise AssertionError(v)
        except SystemExit as e:
            assert str(e) == '[s] x must be a whole number from 0 to 9, not %r' % (v,), e


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
