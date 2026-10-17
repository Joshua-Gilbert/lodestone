"""Firefox, driven through Marionette, its own remote-control protocol.

Marionette is built into every Firefox: started with --marionette it listens
on a local TCP port (2828).  A message is its length in decimal, a colon and
JSON:  [0, id, "WebDriver:Navigate", {...}]  ->  [1, id, error, result].
No geckodriver and no Python packages are needed.
"""
import ctypes, json, os, shutil, signal, socket, subprocess, tempfile, threading, time

SANDBOX = 'gridfox'
ELEMENT = 'element-6066-11e4-a52e-4f735466cecf'      # WebDriver's web element key

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
    # downloads go to a temporary folder, without asking (not the SD card's ~/Downloads)
    'browser.download.folderList': 2,
    'browser.download.useDownloadDir': True,
    'browser.download.always_ask_before_handling_new_types': False,
    'browser.download.manager.showWhenStarting': False,
}


def _die_with_parent():
    """Firefox goes when gridfox does, even if gridfox is killed outright."""
    try:
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGTERM)    # PR_SET_PDEATHSIG
    except Exception:
        pass


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
        s.dead = False                  # the connection is gone or out of step: start again
        s.session = None
        try:
            s.hello = s._recv()
        except Exception:
            s.sock.close(); raise

    def _recv(s):
        # everything read stays in s.buf until a whole message is there, so a
        # message is never half-consumed
        while True:
            i = s.buf.find(b':')
            if i >= 0:
                n = int(s.buf[:i])
                if len(s.buf) >= i + 1 + n:
                    body = s.buf[i + 1:i + 1 + n]; s.buf = s.buf[i + 1 + n:]
                    return json.loads(body.decode('utf-8'))
            elif len(s.buf) > 20:
                raise ValueError('not Marionette')
            d = s.sock.recv(65536)
            if not d: raise ConnectionError('Firefox closed the Marionette connection')
            s.buf += d

    def call(s, name, params=None, timeout=None):
        with s.lock:
            if s.dead: raise ConnectionError('the connection to Firefox was lost')
            s.id += 1
            msg = json.dumps([0, s.id, name, params or {}], separators=(',', ':')).encode('utf-8')
            try:
                s.sock.settimeout(timeout if timeout is not None else 30.0)
                s.sock.sendall(b'%d:' % len(msg) + msg)
                while True:
                    r = s._recv()
                    if isinstance(r, list) and len(r) == 4 and r[0] == 1 and r[1] == s.id: break
            except (OSError, ValueError) as e:
                # a timeout or a broken stream: the next answer could be this
                # one's, so this connection can't be trusted again
                s.dead = True
                try: s.sock.close()
                except OSError: pass
                raise ConnectionError('Firefox did not answer (%s): %s' % (name, e or type(e).__name__))
        if r[2]: raise MarionetteError(r[2])
        return r[3]

    def value(s, name, params=None, **kw):
        r = s.call(name, params, **kw)
        return r.get('value') if isinstance(r, dict) else r

    # ---- WebDriver -------------------------------------------------------
    def new_session(s, page_load='eager', load_ms=20000, script_ms=10000):
        # Marionette takes the capabilities as the parameters themselves (not
        # geckodriver's {capabilities: {alwaysMatch}}, whose keys it would ignore)
        caps = {'pageLoadStrategy': page_load, 'unhandledPromptBehavior': 'dismiss',
                'timeouts': {'pageLoad': load_ms, 'script': script_ms, 'implicit': 0}}
        r = s.call('WebDriver:NewSession', caps)
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
        # a named sandbox: gridfox's globals and the DOM built-ins it calls are
        # out of the page's reach (the page sees its own window, not ours)
        # newSandbox false: the same sandbox each time (extract.js leaves the
        # elements there for act.js); the default, but said outright, as
        # Marionette's own comments say otherwise
        return s.value('WebDriver:ExecuteScript', {'script': body, 'args': list(args), 'sandbox': SANDBOX,
                                                   'newSandbox': False}, timeout=timeout)

    def click(s, el, timeout=25):
        """A real click (trusted events, user activation) on a web element
        reference from script()."""
        eid = el.get(ELEMENT) if isinstance(el, dict) else None
        if not eid: raise MarionetteError({'error': 'no such element', 'message': 'not an element'})
        s.call('WebDriver:ElementClick', {'id': eid}, timeout=timeout)

    def screenshot(s):
        """The viewport as base64 PNG (for the picture view, later)."""
        return s.value('WebDriver:TakeScreenshot', {'full': False, 'hash': False})

    def set_window(s, w, h):
        s.call('WebDriver:SetWindowRect', {'width': w, 'height': h})

    def quit(s, timeout=10):
        """Ask Firefox to shut down as it would from its menu (cookies, sign-ins
        and the session store written out).  -> True if it agreed."""
        try:
            s.call('Marionette:Quit', {'flags': ['eAttemptQuit']}, timeout=timeout)
            s.session = None
            return True
        except Exception:
            return False

    def close(s):
        try:
            if s.session and not s.dead: s.call('WebDriver:DeleteSession', timeout=1)
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
        prefs['browser.download.dir'] = os.path.join(tempfile.gettempdir(), 'gridfox-downloads')
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
                                      stderr=subprocess.DEVNULL, start_new_session=True,
                                      preexec_fn=_die_with_parent)
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

    def stop(s, m=None, wait=8.0):
        """The Firefox gridfox started: quit cleanly through Marionette, then
        SIGTERM, and a kill only as the last resort.  One that was already
        running when gridfox came is left running."""
        if s.proc is None or s.proc.poll() is not None: return
        if m is not None and not m.dead and m.quit():
            try: s.proc.wait(wait); return
            except subprocess.TimeoutExpired: pass
        s.proc.terminate()
        try: s.proc.wait(wait if m is None else 2.0)
        except subprocess.TimeoutExpired: s.proc.kill()
