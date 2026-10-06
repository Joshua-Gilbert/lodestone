"""gridlink: Claude for GRiD, Pi side.

    python3 -m gridlink                      serve the GRiD through the AR488 bridge
    python3 -m gridlink --console            talk to Claude in this terminal (no GRiD)
    python3 -m gridlink --save-bridge        also store the bridge settings in its EEPROM
"""
import argparse, collections, logging, os, signal, sys, threading, time
from . import glp
from .config import Config, MODELS
from .agent import Session
from .link import AR488Serial, Link, serve

GLYPHS = {0x80: '\u25cf', 0x81: '\u23bf', 0x82: '\u2026', 0x83: '\u2192', 0x84: '\u2713', 0x85: '\u2717',
          0x86: '\u00b7', 0x87: '\u00b7', 0x88: '\u2722', 0x89: '\u2733', 0x8A: '\u2736', 0x8B: '\u273b',
          0x8C: '\u273d', 0x8D: '\u2500', 0x8E: '\u2502', 0x8F: '\u25b8', 0x90: '\u00b0', 0x91: '\u00b5',
          0x92: '\u2126', 0x93: '\u00b1', 0x94: '\u00d7', 0x95: '\u2248', 0x96: '\u2264', 0x97: '\u2265'}


def grid_text_to_ansi(data):
    out = []
    for b in data:
        if b == glp.T_NL: out.append('\n')
        elif b == glp.T_INV_ON: out.append('\x1b[7m')
        elif b == glp.T_INV_OFF: out.append('\x1b[27m')
        elif b == glp.T_UL_ON: out.append('\x1b[4m')
        elif b == glp.T_UL_OFF: out.append('\x1b[24m')
        elif b in GLYPHS: out.append(GLYPHS[b])
        elif 32 <= b < 127: out.append(chr(b))
    return ''.join(out)


class ConsoleTransport:
    frame_limit = glp.PATCHED_FRAME_MAX; version = 'console (no GRiD)'; patched = False


class ConsoleLink:
    """Stands in for the GRiD: prints what the GRiD would show, reads prompts
    from the keyboard.  GRiD tools answer "no GRiD connected"."""
    def __init__(s):
        s.S = None; s.t = ConsoleTransport(); s.stats = collections.Counter()
        s.ready = threading.Event(); s.lock = threading.Lock()

    def send(s, t, body=b''):
        with s.lock:
            if t == glp.P_TEXT:
                sys.stdout.write(grid_text_to_ansi(body)); sys.stdout.flush()
            elif t == glp.P_STATUS:
                if body: sys.stdout.write('\x1b[2m[%s]\x1b[0m\n' % body.decode('latin1')); sys.stdout.flush()
            elif t == glp.P_TITLE:
                sys.stdout.write('\x1b]0;%s\x07' % grid_text_to_ansi(body))
            elif t == glp.P_REQUEST:
                s.S.grid.on_reply(bytes([body[0], 0xF6]))
            elif t == glp.P_ASK:
                aid, kind = body[0], body[1]
                q, d, a = (body[2:].split(b'\0') + [b'', b'', b''])[:3]
                print('\n\x1b[7m %s \x1b[0m' % grid_text_to_ansi(q))
                if d: print('   ' + grid_text_to_ansi(d).replace('\n', '\n   '))
                opts = '[y]es  [a] %s  [n]o: ' % grid_text_to_ansi(a) if kind == 1 else '[y]es  [n]o: '
                ans = (input(opts).strip().lower() or 'n')[:1]
                s.S.on_message(glp.G_EVENT, bytes([glp.EV_ANSWER, aid, ord(ans)]))
            elif t == glp.P_READY:
                s.ready.set()
            elif t == glp.P_CLEAR:
                sys.stdout.write('\x1b[2J\x1b[H')
    send_first = send


def console(cfg, client, log):
    link = ConsoleLink()
    S = Session(cfg, client, log=log); S.attach(link); link.S = S
    from .grid import DOS_ERRORS
    DOS_ERRORS[0xF6] = 'no GRiD connected (console mode)'
    threading.Thread(target=S.run, daemon=True).start()
    hello = bytes([1, 0, 0, 4, 80, 20]) + b'os=console on the Pi\ncwd=A:\\\n'
    S.on_message(glp.G_HELLO, hello)
    while True:
        link.ready.wait(); link.ready.clear()
        try:
            line = input('\n\x1b[1m>\x1b[0m ')
        except (EOFError, KeyboardInterrupt):
            print(); return
        if line.strip() in ('/exit', '/quit'): return
        S.on_message(glp.G_PROMPT, line.encode('cp437', 'replace'))
        # Ctrl-C while Claude works = Esc on the GRiD
        try:
            while not link.ready.wait(0.2): pass
            link.ready.set()
        except KeyboardInterrupt:
            S.on_message(glp.G_EVENT, bytes([glp.EV_INTERRUPT]))


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gridlink', description='Claude for GRiD - Pi side')
    ap.add_argument('--config', help='TOML settings file')
    ap.add_argument('--port'); ap.add_argument('--baud', type=int); ap.add_argument('--address', type=int)
    ap.add_argument('--model', help='opus, sonnet, haiku, fable or a model id')
    ap.add_argument('--mode', choices=['ask', 'edits', 'auto'])
    ap.add_argument('--console', action='store_true', help='chat in this terminal, no GRiD')
    ap.add_argument('--save-bridge', action='store_true', help='store bridge settings in its EEPROM')
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args(argv)

    cfg = Config().load(a.config)
    if a.port: cfg.port = a.port
    if a.baud: cfg.baud = a.baud
    if a.address: cfg.address = a.address
    if a.model: cfg.model = MODELS.get(a.model, a.model)
    if a.mode: cfg.mode = a.mode

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    log = logging.getLogger('gridlink').info

    import anthropic
    key = cfg.api_key or os.environ.get('ANTHROPIC_API_KEY')
    if not key:
        sys.exit('No API key: set ANTHROPIC_API_KEY or api_key_file in the config (%s).'
                 % (cfg.source or '~/.config/gridlink/config.toml'))
    client = anthropic.Anthropic(api_key=key, max_retries=3)

    if a.console:
        return console(cfg, client, log)

    t = AR488Serial(cfg.port, cfg.baud, cfg.address, log=log)
    log('opening %s at %d baud' % (cfg.port, cfg.baud))
    t.open()
    t.configure()
    if a.save_bridge:
        t.save(); log('bridge settings saved in its EEPROM')
    S = Session(cfg, client, log=log)
    link = Link(t, S.on_message, log=log)
    S.attach(link)
    threading.Thread(target=S.run, daemon=True, name='agent').start()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *x: stop.set())
    log('waiting for the GRiD (run CLAUDE on it)')
    try:
        serve(t, link, stop)
    except KeyboardInterrupt:
        pass
    log('stopped')


if __name__ == '__main__':
    main()
