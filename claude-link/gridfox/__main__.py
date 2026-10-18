"""gridfox: Firefox on the Pi, shown as text on the GRiD (CLAUDE /W).

    python3 -m gridfox [URL] [--port 2828] [--firefox PATH] [--no-images]

gridlink starts it in Term's pty when the GRiD's HELLO says app=web; it also
runs in any 80x24 xterm for trying it out (Ctrl-C quits there; Ctrl-Q
anywhere, and Return on the GRiD starts it again).
"""
import argparse, os, sys, time
from .marionette import Firefox
from .browser import Browser
from .app import App, SEARCH, run_tty


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gridfox', description=__doc__.split('\n')[0])
    ap.add_argument('url', nargs='?', help='the page to open first')
    ap.add_argument('--port', type=int, default=2828, help='Marionette port (an already running Firefox is used)')
    ap.add_argument('--firefox', help='the Firefox to run (default: firefox-esr or firefox on PATH)')
    ap.add_argument('--profile', default='~/.cache/gridfox/profile', help='Firefox profile (sign-ins kept here)')
    ap.add_argument('--no-images', dest='images', action='store_false',
                    help='Firefox loads no pictures (the text view needs none; the picture view shows none)')
    ap.add_argument('--images', action='store_true', help=argparse.SUPPRESS)      # (the default now)
    ap.add_argument('--search', default=SEARCH, help='search address, %%s for the words')
    ap.add_argument('--log', default='~/.cache/gridfox/gridfox.log')
    ap.add_argument('--console', action='store_true', help='Ctrl-C quits (for trying it in a terminal)')
    a = ap.parse_args(argv)

    logp = os.path.expanduser(a.log)
    os.makedirs(os.path.dirname(logp), exist_ok=True)
    logf = open(logp, 'a', buffering=1)
    log = lambda m: logf.write('%s %s\n' % (time.strftime('%H:%M:%S'), m))

    sys.stdout.write('\x1b[2J\x1b[H\x1b[?25l  Starting Firefox on the Pi…\r\n'); sys.stdout.flush()
    fx = Firefox(binary=a.firefox, profile=a.profile, port=a.port, images=a.images, log=log)
    try:
        m = fx.start()
    except Exception as e:
        log('firefox: %r' % e)
        sys.stdout.write('\r\n  Firefox could not start: %s\r\n  (Install it with: sudo apt install firefox)\r\n' % e)
        sys.stdout.flush()
        return 1
    app = App(Browser(m, log=log), start=a.url, search=a.search, log=log,
              quit_keys=('ctrl-c',) if a.console or not os.environ.get('GRIDLINK') else ())
    try:
        run_tty(app)
    finally:
        fx.stop(m)                  # (a clean quit first: cookies and sign-ins kept)
        m.close()
    if app.lost: log('stopped: %s' % app.lost)
    return 3 if app.lost else 0


if __name__ == '__main__':
    sys.exit(main())
