"""Y: a YouTube video without YouTube's player.

YouTube's player shows Firefox a bot check (gridfox's Firefox is remote
controlled, and Firefox won't hide that) and a run of ads that floods the
picture view.  yt-dlp on the Pi finds the video's own file instead, one
with picture and sound together, and gridfox plays it in a plain page of
its own: a <video> filling the window, nothing else on it.

The file's address is good for some hours, for this Pi's address, and
often only for the YouTube app yt-dlp said it was: its server checks the
request's headers, and refuses Firefox's (403).  So Firefox doesn't fetch
it: a relay in gridfox (Relay, on 127.0.0.1) does, with yt-dlp's headers,
in pieces of at most CHUNK as yt-dlp does (larger asks are slowed or
refused), and Firefox's player plays the relay's address.  Seeking works:
Firefox's Range goes on to YouTube.  If YouTube asks yt-dlp to sign in, it
tries again with the cookies in gridfox's own Firefox profile.

On the Pi:  ~/gridlink/venv/bin/pip install -U "yt-dlp[default]"
(yt-dlp also wants a JavaScript runtime for YouTube: deno, or node.)
"""
import html, importlib.util, json, os, re, secrets, shutil, subprocess, sys, threading, urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# One file with picture and sound (no merging: Firefox plays it as it comes),
# H.264 first (Firefox on the Pi decodes it), small: the GRiD shows 640 x 384.
FORMAT = ('b[vcodec^=avc1][acodec!=none][height<=480]/b[acodec!=none][vcodec!=none][height<=480]'
          '/18/b[acodec!=none][vcodec!=none]')
WAIT = 90                       # seconds yt-dlp may take
PAGE = 'video.html'
HOSTS = ('youtube.com', 'youtu.be', 'youtube-nocookie.com')
CHUNK = 10 << 20                # bytes the relay asks YouTube for at a time (yt-dlp's own)
SIGN_IN = ('sign in to confirm', 'login_required', 'use --cookies', 'not a bot')


def is_video(url):
    """A YouTube address yt-dlp can play: a watch page, youtu.be, shorts, an embed, a live."""
    u = urllib.parse.urlsplit(url or '')
    host = (u.hostname or '').lower()
    if not any(host == h or host.endswith('.' + h) for h in HOSTS): return False
    if host.endswith('youtu.be'): return len(u.path.strip('/')) >= 6
    q = urllib.parse.parse_qs(u.query)
    return bool(q.get('v')) or bool(re.match(r'/(shorts|embed|live|v)/[\w-]{6,}', u.path))


def command():
    """How to run yt-dlp here: the module beside gridfox (the venv's), else on PATH."""
    if importlib.util.find_spec('yt_dlp') is not None: return [sys.executable, '-m', 'yt_dlp']
    exe = shutil.which('yt-dlp')
    return [exe] if exe else None


class NotFound(Exception):
    pass


def find(url, profile=None, run=subprocess.run, cmd=None):
    """-> (the video file's address, its title, the headers to fetch it with); NotFound with why not."""
    base = cmd or command()
    if not base:
        raise NotFound('yt-dlp is not installed on the Pi (pip install "yt-dlp[default]")')
    args = base + ['--no-playlist', '--js-runtimes', 'node', '-f', FORMAT,
                   '-O', '%(.{title,url,duration,http_headers})j', url]
    tries = [args]
    if profile and os.path.isdir(profile):
        tries.append(args[:len(base)] + ['--cookies-from-browser', 'firefox:' + profile] + args[len(base):])
    why = ''
    for n, a in enumerate(tries):
        try:
            r = run(a, capture_output=True, text=True, timeout=WAIT, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise NotFound('yt-dlp took too long')
        except OSError as e:
            raise NotFound('yt-dlp could not run: %s' % e)
        info = _parse(r.stdout)
        if r.returncode == 0 and info: return info
        why = _why(r.stderr) or 'yt-dlp found no video it could hand on'
        if not any(k in why.lower() for k in SIGN_IN): break        # (cookies won't help)
    raise NotFound(why)


def _parse(out):
    for line in reversed((out or '').strip().splitlines()):
        try: d = json.loads(line)
        except ValueError: continue
        if isinstance(d, dict) and str(d.get('url', '')).startswith('http'):
            hd = d.get('http_headers') if isinstance(d.get('http_headers'), dict) else {}
            return d['url'], str(d.get('title') or 'Video'), {str(k): str(v) for k, v in hd.items()}
    return None


def _why(err):
    lines = [l.strip() for l in (err or '').splitlines() if l.strip()]
    errs = [l for l in lines if l.startswith('ERROR')] or [l for l in lines if not l.startswith('WARNING')]
    # without a JavaScript runtime YouTube's formats are locked: yt-dlp only warns, then finds none
    if 'javascript runtime' in (err or '').lower():
        return 'yt-dlp needs deno on the Pi for YouTube (see docs/gridfox.md)'
    if not errs: return ''
    t = re.sub(r'^ERROR:\s*(\[[^\]]*\]\s*)?([\w-]{6,}:\s*)?', '', errs[-1])
    return t[:160]


def page(src, title):
    """The plain player: the video filling the window, black around it.
    A click or Space plays and pauses; Left and Right go back and on 10 s;
    the title shows in the corner while paused."""
    t = html.escape(title)
    return '''<!doctype html><html><head><meta charset="utf-8"><title>%s</title><style>
html,body{margin:0;height:100%%;background:#000;overflow:hidden;color:#fff;font:16px sans-serif}
video{width:100vw;height:100vh;object-fit:contain;display:block}
#t{position:fixed;left:8px;top:6px;right:8px;text-shadow:0 0 3px #000}
body.on #t{display:none}
</style></head><body>
<video id="v" src="%s" preload="auto" playsinline></video>
<div id="t">%s<br>Click or Space: play and pause.  Left, Right: 10 s.</div>
<script>
var v=document.getElementById('v'),t=document.getElementById('t');
function go(){if(v.paused)v.play().catch(function(e){t.textContent='Could not play: '+e.message;});else v.pause();}
document.addEventListener('click',go);
document.addEventListener('keydown',function(e){
 if(e.key===' '){go();e.preventDefault();}
 else if(e.key==='ArrowLeft'){v.currentTime=Math.max(0,v.currentTime-10);}
 else if(e.key==='ArrowRight'){v.currentTime+=10;}});
v.addEventListener('play',function(){document.body.className='on';});
v.addEventListener('pause',function(){document.body.className='';});
v.addEventListener('ended',function(){document.body.className='';t.textContent='The end.';});
v.addEventListener('error',function(){t.textContent='Firefox could not play this video.';});
</script></body></html>''' % (t, html.escape(src, quote=True), t)


def write_page(src, title, folder='.'):
    """The page into gridfox's folder; -> its file:// address."""
    p = os.path.abspath(os.path.join(folder, PAGE))
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: f.write(page(src, title))
    os.replace(tmp, p)
    return 'file://' + urllib.parse.quote(p)


class Relay:
    """Firefox -> 127.0.0.1 -> YouTube: the video fetched with yt-dlp's
    headers.  One server for gridfox's life (a thread), each video at a
    secret path of its own; the last few are kept, for Back and Forward."""
    KEEP = 4

    def __init__(s, opener=None):
        s.videos = {}; s.order = []; s.lock = threading.Lock()
        s.open = opener or urllib.request.build_opener().open
        relay = s

        class H(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(h, *a): pass
            def do_HEAD(h): relay._serve(h, body=False)
            def do_GET(h): relay._serve(h, body=True)

        s.srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
        s.srv.daemon_threads = True
        s.port = s.srv.server_address[1]
        threading.Thread(target=s.srv.serve_forever, daemon=True).start()

    def add(s, url, headers):
        """-> the address Firefox plays this video at."""
        key = secrets.token_hex(8)
        with s.lock:
            s.videos[key] = (url, dict(headers or {}))
            s.order.append(key)
            while len(s.order) > s.KEEP: s.videos.pop(s.order.pop(0), None)
        return 'http://127.0.0.1:%d/v/%s.mp4' % (s.port, key)

    def close(s):
        s.srv.shutdown(); s.srv.server_close()

    def _up(s, url, headers, a, b):
        """YouTube's answer for bytes a..b: (response, a, b, total)."""
        rq = urllib.request.Request(url, headers=dict(headers, Range='bytes=%d-%d' % (a, b)))
        r = s.open(rq, timeout=30)
        m = re.match(r'bytes (\d+)-(\d+)/(\d+|\*)', r.headers.get('Content-Range', '') or '')
        if m:
            total = int(m.group(3)) if m.group(3) != '*' else None
            return r, int(m.group(1)), int(m.group(2)), total
        n = int(r.headers.get('Content-Length') or 0)            # (a server that ignored the Range)
        return r, 0, n - 1, n

    def _serve(s, h, body):
        m = re.match(r'/v/([0-9a-f]+)\.mp4$', h.path)
        v = s.videos.get(m.group(1)) if m else None
        if not v:
            h.send_error(404); return
        url, headers = v
        rng = re.match(r'bytes=(\d*)-(\d*)', h.headers.get('Range', '') or '')
        start = int(rng.group(1)) if rng and rng.group(1) else 0
        want = int(rng.group(2)) if rng and rng.group(2) else None
        try:
            r, a, b, total = s._up(url, headers, start, start + CHUNK - 1 if want is None else min(want, start + CHUNK - 1))
        except urllib.error.HTTPError as e:
            h.send_error(e.code if e.code in (403, 404, 410, 416) else 502); return
        except Exception:
            h.send_error(502); return
        last = (total - 1) if total else b
        end = last if want is None else min(want, last)
        try:
            h.send_response(206 if rng else 200)
            h.send_header('Content-Type', r.headers.get('Content-Type') or 'video/mp4')
            h.send_header('Accept-Ranges', 'bytes')
            h.send_header('Content-Length', str(end - a + 1))
            if rng: h.send_header('Content-Range', 'bytes %d-%d/%s' % (a, end, total if total else '*'))
            h.end_headers()
            if not body: r.close(); return
            pos = a
            while True:
                while True:
                    d = r.read(64 << 10)
                    if not d: break
                    if pos + len(d) > end + 1: d = d[:end + 1 - pos]
                    h.wfile.write(d); pos += len(d)
                    if pos > end: break
                r.close()
                if pos > end: break
                r, _, _, _ = s._up(url, headers, pos, min(end, pos + CHUNK - 1))   # the next piece
        except (BrokenPipeError, ConnectionResetError):
            pass                                  # (Firefox seeked, or left the page: it asks again)
        except Exception:
            h.close_connection = True             # (YouTube broke off: Firefox asks again from here)


_RELAY = None


def serve(url, headers):
    """The relay's address for this video (the relay started the first time)."""
    global _RELAY
    if _RELAY is None: _RELAY = Relay()
    return _RELAY.add(url, headers)
