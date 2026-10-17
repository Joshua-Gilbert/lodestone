#!/usr/bin/env python3
"""A stand-in Firefox for gridfox's tests: a Marionette server whose pages
are jsdom (fake_firefox_dom.js), so gridfox's real extract.js and act.js run
against a real DOM.  Pages come from a folder: http://test.local/NAME is
NAME.html there (the query string is left for the page's scripts).

    python3 tests/fake_firefox.py [--port 2828] [--pages tests/web]

Needs Node and `npm install` in tests/ (jsdom).
"""
import argparse, json, os, socket, subprocess, sys, threading, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
NOT_FOUND = '<html><head><title>Not found</title></head><body><h1>Not found</h1><p>%s</p></body></html>'


class FakeFirefox:
    def __init__(s, pages=os.path.join(HERE, 'web'), port=0, delay=0.0, slow=None):
        s.pages = pages; s.delay = delay
        s.slow = slow or {}                 # path -> seconds the old page stays up after a click to it
        s.caps = None; s.clicks = []
        s.node = subprocess.Popen(['node', os.path.join(HERE, 'fake_firefox_dom.js')], cwd=HERE,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        s.srv = socket.socket(); s.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.srv.bind(('127.0.0.1', port)); s.srv.listen(4)
        s.port = s.srv.getsockname()[1]
        s.hist = []; s.pos = -1; s.url = 'about:blank'; s.title = ''
        s.calls = []; s.session = False
        s.lock = threading.Lock()
        s._load('about:blank', push=True)
        threading.Thread(target=s._serve, daemon=True).start()

    # ---- the DOM ---------------------------------------------------------
    def _node(s, m):
        s.node.stdin.write(json.dumps(m) + '\n'); s.node.stdin.flush()
        return json.loads(s.node.stdout.readline())

    def _html(s, url):
        u = urllib.parse.urlsplit(url)
        if url == 'about:blank': return '<html><body></body></html>'
        if u.netloc != 'test.local': return NOT_FOUND % ('No network in the tests: ' + url)
        name = (u.path.strip('/') or 'index').replace('/', '_')
        p = os.path.join(s.pages, name if name.endswith('.html') else name + '.html')
        if not os.path.exists(p): return NOT_FOUND % url
        return open(p, encoding='utf-8').read()

    def _load(s, url, push=True):
        r = s._node({'op': 'load', 'url': url, 'html': s._html(url)})
        assert r['ok'], r
        s.url = url
        t = s._node({'op': 'exec', 'script': 'return document.title;', 'args': []})
        s.title = t.get('value') or ''
        if push:
            s.hist = s.hist[:s.pos + 1] + [url]; s.pos = len(s.hist) - 1

    def _go(s, url):
        """A page a click or a form led to: at once, or after the old page has
        stayed up a while (as a real browser does with a slow server)."""
        wait = s.slow.get(urllib.parse.urlsplit(url).path.strip('/'))
        if not wait: s._load(url); return
        s._node({'op': 'unload'})
        def later():
            __import__('time').sleep(wait)
            with s.lock: s._load(url)
        threading.Thread(target=later, daemon=True).start()

    # ---- Marionette ------------------------------------------------------
    def _serve(s):
        while True:
            try: c, _ = s.srv.accept()
            except OSError: return
            threading.Thread(target=s._conn, args=(c,), daemon=True).start()

    def _conn(s, c):
        hello = json.dumps({'applicationType': 'gecko', 'marionetteProtocol': 3}).encode()
        c.sendall(b'%d:' % len(hello) + hello)
        buf = b''
        try:
            while True:
                while b':' not in buf:
                    d = c.recv(65536)
                    if not d: return
                    buf += d
                n, rest = buf.split(b':', 1); n = int(n)
                while len(rest) < n:
                    d = c.recv(65536)
                    if not d: return
                    rest += d
                msg = json.loads(rest[:n]); buf = rest[n:]
                _, mid, name, params = msg
                with s.lock:
                    err, res = s.handle(name, params)
                out = json.dumps([1, mid, err, res]).encode()
                c.sendall(b'%d:' % len(out) + out)
        finally:
            c.close(); s.session = False

    def handle(s, name, p):
        s.calls.append(name)
        if s.delay: __import__('time').sleep(s.delay)
        if name == 'WebDriver:NewSession':
            if s.session: return {'error': 'session not created', 'message': 'Maximum number of active sessions'}, None
            # Marionette reads the parameters as the capabilities themselves: a
            # geckodriver-style {capabilities: {alwaysMatch}} would be ignored
            # without a word by the real one, so here it is an error
            if 'capabilities' in p or p.get('pageLoadStrategy') != 'eager':
                return {'error': 'invalid argument', 'message': 'capabilities not as Marionette reads them: %r' % p}, None
            s.caps = p
            s.session = True
            return None, {'sessionId': 'fake', 'capabilities': {'browserName': 'firefox'}}
        if name == 'WebDriver:DeleteSession': s.session = False; return None, {}
        if name == 'WebDriver:Navigate':
            if urllib.parse.urlsplit(p['url']).netloc == 'error.test':          # what Firefox says for a bad host
                s._load('about:blank')
                return {'error': 'unknown error', 'message': 'Reached error page: about:neterror?e=dnsNotFound'}, None
            s._load(p['url']); return None, {}
        if name == 'WebDriver:Back':
            if s.pos > 0: s.pos -= 1; s._load(s.hist[s.pos], push=False)
            return None, {}
        if name == 'WebDriver:Forward':
            if s.pos < len(s.hist) - 1: s.pos += 1; s._load(s.hist[s.pos], push=False)
            return None, {}
        if name == 'WebDriver:Refresh': s._load(s.url, push=False); return None, {}
        if name == 'WebDriver:GetCurrentURL': return None, {'value': s.url}
        if name == 'WebDriver:GetTitle': return None, {'value': s.title}
        if name == 'WebDriver:SetWindowRect': return None, {}
        if name == 'WebDriver:ExecuteScript':
            r = s._node({'op': 'exec', 'script': p['script'], 'args': p.get('args', [])})
            if not r['ok']: return {'error': 'javascript error', 'message': r['error']}, None
            if r.get('nav'): s._go(r['nav'])
            return None, {'value': r['value']}
        if name == 'WebDriver:ElementClick':
            r = s._node({'op': 'click', 'id': p['id']})
            if not r['ok']: return {'error': r['error'], 'message': r['error']}, None
            s.clicks.append(p['id'])
            if r.get('nav'): s._go(r['nav'])
            return None, {}
        return {'error': 'unknown command', 'message': name}, None

    def close(s):
        try: s.srv.close()
        except OSError: pass
        try: s.node.kill()
        except OSError: pass


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=2828)
    ap.add_argument('--pages', default=os.path.join(HERE, 'web'))
    a = ap.parse_args()
    f = FakeFirefox(a.pages, a.port)
    print('stand-in Firefox on port %d' % f.port, file=sys.stderr)
    threading.Event().wait()
