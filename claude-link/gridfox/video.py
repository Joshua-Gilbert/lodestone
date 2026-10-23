"""Y: a YouTube video without YouTube's player.

YouTube's player shows Firefox a bot check (gridfox's Firefox is remote
controlled, and Firefox won't hide that) and a run of ads that floods the
picture view.  yt-dlp on the Pi finds the video's own file instead, one
with picture and sound together, and gridfox plays it in a plain page of
its own: a <video> filling the window, nothing else on it.

The file's address is good for some hours and for this Pi's address only,
which is all gridfox needs.  If YouTube asks yt-dlp to sign in, it tries
again with the cookies in gridfox's own Firefox profile.

On the Pi:  ~/gridlink/venv/bin/pip install -U "yt-dlp[default]"
(yt-dlp also wants a JavaScript runtime for YouTube: deno, or node.)
"""
import html, importlib.util, json, os, re, shutil, subprocess, sys, urllib.parse

# One file with picture and sound (no merging: Firefox plays it as it comes),
# H.264 first (Firefox on the Pi decodes it), small: the GRiD shows 640 x 384.
FORMAT = ('b[vcodec^=avc1][acodec!=none][height<=480]/b[acodec!=none][vcodec!=none][height<=480]'
          '/18/b[acodec!=none][vcodec!=none]')
WAIT = 90                       # seconds yt-dlp may take
PAGE = 'video.html'
HOSTS = ('youtube.com', 'youtu.be', 'youtube-nocookie.com')
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
    """-> (the video file's address, its title); NotFound with why not."""
    base = cmd or command()
    if not base:
        raise NotFound('yt-dlp is not installed on the Pi (pip install "yt-dlp[default]")')
    args = base + ['--no-playlist', '--no-warnings', '--js-runtimes', 'node', '-f', FORMAT,
                   '-O', '%(.{title,url,duration})j', url]
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
            return d['url'], str(d.get('title') or 'Video')
    return None


def _why(err):
    lines = [l.strip() for l in (err or '').splitlines() if l.strip()]
    errs = [l for l in lines if l.startswith('ERROR')] or lines
    if not errs: return ''
    t = re.sub(r'^ERROR:\s*(\[[^\]]*\]\s*)?([\w-]{6,}:\s*)?', '', errs[-1])
    if 'js' in t.lower() and 'runtime' in t.lower(): t += ' (install deno or node on the Pi)'
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
