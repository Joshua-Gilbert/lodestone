"""Firefox, driven through Marionette, its own remote-control protocol.

Marionette is built into every Firefox: started with --marionette it listens
on a local TCP port (2828).  A message is its length in decimal, a colon and
JSON:  [0, id, "WebDriver:Navigate", {...}]  ->  [1, id, error, result].
No geckodriver and no Python packages are needed.
"""
import json, os, shutil, socket, subprocess, threading, time

PREFS = {
    # quiet, fast start: no first-run pages, updates, telemetry or default-browser check
    'browser.shell.checkDefaultBrowser': False,
    'browser.startup.homepage_override.mstone': 'ignore',
    'startup.homepage_welcome_url': 'about:blank',
    'browser.startup.page': 0,
    'browser.aboutwelcome.enabled': False,
    'datareporting.policy.dataSubmissionEnabled': False,
    'datareporting.healthreport.uploadEnabled': False,
    'toolkit.telemetry.reportingpolicy.firstRun': False,
    'app.update.auto': False, 'app.update.enabled': False,
    'app.normandy.enabled': False,
    'browser.tabs.warnOnClose': False,
    'browser.sessionstore.resume_from_crash': False,
    'media.autoplay.default': 5,                       # nothing plays
    'dom.disable_open_during_load': True,              # no pop-ups
    'browser.link.open_newwindow': 1,                  # target=_blank opens here, in the one tab
    'browser.link.open_newwindow.restriction': 0,
}


class MarionetteError(Exception):
    def __init__(s, err):
        s.error = err.get('error', 'error') if isinstance(err, dict) else str(err)
        s.message = err.get('message', '') if isinstance(err, dict) else ''
        super().__init__('%s: %s' % (s.error, s.message))


class Marionette:
    def __init__(s, host='127.0.0.1', port=2828, timeout=30.0):
        s.sock = socket.create_connection((host, port), timeout=timeout)
        s.sock.settimeout(timeout)
        s.buf = b''; s.id = 0; s.lock = threading.Lock()
        s.hello = s._recv()
        s.session = None

    def _recv(s):
        while b':' not in s.buf:
            d = s.sock.recv(65536)
            if not d: raise ConnectionError('Firefox closed the Marionette connection')
            s.buf += d
        n, rest = s.buf.split(b':', 1)
        n = int(n)
        while len(rest) < n:
            d = s.sock.recv(max(65536, n - len(rest)))
            if not d: raise ConnectionError('Firefox closed the Marionette connection')
            rest += d
        s.buf = rest[n:]
        return json.loads(rest[:n].decode('utf-8'))

    def call(s, name, params=None, timeout=None):
        with s.lock:
            s.id += 1
            msg = json.dumps([0, s.id, name, params or {}], separators=(',', ':')).encode('utf-8')
            if timeout is not None: s.sock.settimeout(timeout)
            try:
                s.sock.sendall(b'%d:' % len(msg) + msg)
                while True:
                    r = s._recv()
                    if isinstance(r, list) and len(r) == 4 and r[0] == 1 and r[1] == s.id: break
            finally:
                if timeout is not None: s.sock.settimeout(30.0)
        if r[2]: raise MarionetteError(r[2])
        return r[3]

    def value(s, name, params=None, **kw):
        r = s.call(name, params, **kw)
        return r.get('value') if isinstance(r, dict) else r

    # ---- WebDriver -------------------------------------------------------
    def new_session(s, page_load='eager', load_ms=20000, script_ms=10000):
        caps = {'pageLoadStrategy': page_load,
                'timeouts': {'pageLoad': load_ms, 'script': script_ms, 'implicit': 0}}
        r = s.call('WebDriver:NewSession', {'capabilities': {'alwaysMatch': caps}})
        s.session = r.get('sessionId') if isinstance(r, dict) else None
        return r

    def navigate(s, url, timeout=25):
        s.call('WebDriver:Navigate', {'url': url}, timeout=timeout)

    def back(s): s.call('WebDriver:Back', timeout=25)

    def forward(s): s.call('WebDriver:Forward', timeout=25)

    def refresh(s): s.call('WebDriver:Refresh', timeout=25)

    def url(s): return s.value('WebDriver:GetCurrentURL')

    def title(s): return s.value('WebDriver:GetTitle')

    def script(s, body, args=(), timeout=15):
        return s.value('WebDriver:ExecuteScript', {'script': body, 'args': list(args)}, timeout=timeout)

    def screenshot(s):
        """The viewport as base64 PNG (for the picture view, later)."""
        return s.value('WebDriver:TakeScreenshot', {'full': False, 'hash': False})

    def set_window(s, w, h):
        s.call('WebDriver:SetWindowRect', {'width': w, 'height': h})

    def close(s):
        try:
            if s.session: s.call('WebDriver:DeleteSession', timeout=5)
        except Exception: pass
        try: s.sock.close()
        except OSError: pass


def find_firefox(path=None):
    for c in ([path] if path else []) + ['firefox-esr', 'firefox']:
        if c and (os.sep in c and os.access(c, os.X_OK)): return c
        p = c and shutil.which(c)
        if p: return p
    return None


def port_open(port, host='127.0.0.1'):
    try:
        socket.create_connection((host, port), timeout=0.3).close()
        return True
    except OSError:
        return False


class Firefox:
    """A headless Firefox with its own profile (cookies and sign-ins kept),
    or one already listening on the port."""
    def __init__(s, binary=None, profile='~/.cache/gridfox/profile', port=2828, images=False,
                 width=1024, height=768, log=None):
        s.binary = binary; s.profile = os.path.expanduser(profile); s.port = port
        s.images = images; s.size = (width, height); s.proc = None; s.log = log or (lambda m: None)

    def write_prefs(s):
        os.makedirs(s.profile, exist_ok=True)
        prefs = dict(PREFS)
        prefs['marionette.port'] = s.port
        # the text view needs no pictures: not fetching them is most of a page's weight
        prefs['permissions.default.image'] = 1 if s.images else 2
        with open(os.path.join(s.profile, 'user.js'), 'w') as f:
            for k, v in prefs.items(): f.write('user_pref(%s, %s);\n' % (json.dumps(k), json.dumps(v)))

    def start(s, wait=40.0):
        """-> a connected Marionette (with a session)."""
        if not port_open(s.port):
            exe = find_firefox(s.binary)
            if not exe: raise FileNotFoundError('Firefox is not installed (sudo apt install firefox)')
            s.write_prefs()
            env = dict(os.environ, MOZ_HEADLESS='1')
            env.pop('DISPLAY', None); env.pop('WAYLAND_DISPLAY', None)
            args = [exe, '--headless', '--marionette', '--no-remote', '--profile', s.profile,
                    '--width', str(s.size[0]), '--height', str(s.size[1]), 'about:blank']
            s.log('starting %s' % ' '.join(args))
            s.proc = subprocess.Popen(args, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, start_new_session=True)
            t0 = time.time()
            while not port_open(s.port):
                if s.proc.poll() is not None:
                    raise RuntimeError('Firefox exited at start (code %s)' % s.proc.returncode)
                if time.time() - t0 > wait: raise TimeoutError('Firefox did not open Marionette')
                time.sleep(0.1)
        m = None; t0 = time.time()
        while True:
            try:
                m = Marionette(port=s.port); m.new_session(); break
            except (OSError, ConnectionError, MarionetteError) as e:
                if m is not None: m.close()
                m = None
                if time.time() - t0 > 10: raise RuntimeError('Firefox would not start a session: %s' % e)
                time.sleep(0.3)
        return m

    def stop(s):
        if s.proc is not None and s.proc.poll() is None:
            s.proc.terminate()
            try: s.proc.wait(5)
            except subprocess.TimeoutExpired: s.proc.kill()
