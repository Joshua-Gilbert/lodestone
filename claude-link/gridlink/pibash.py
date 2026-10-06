"""A persistent bash session on the Pi for Claude's `bash` tool."""
import os, queue, signal, subprocess, threading, time, uuid

LIMIT = 30000


class Bash:
    def __init__(s, cwd):
        s.cwd = cwd; s.p = None; s.q = None
        os.makedirs(cwd, exist_ok=True)

    def start(s):
        env = dict(os.environ, TERM='dumb', PAGER='cat', GIT_PAGER='cat', PYTHONUNBUFFERED='1')
        s.p = subprocess.Popen(['bash', '--noprofile', '--norc'], cwd=s.cwd, env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
        s.q = queue.Queue()
        def pump(stream, q):
            for line in iter(stream.readline, b''):
                q.put(line)
            q.put(None)
        threading.Thread(target=pump, args=(s.p.stdout, s.q), daemon=True).start()

    def stop(s):
        if s.p and s.p.poll() is None:
            try: os.killpg(s.p.pid, signal.SIGKILL)
            except OSError: pass
        s.p = None

    def restart(s):
        s.stop(); s.start()
        return 'bash restarted'

    def run(s, command, timeout=180):
        if s.p is None or s.p.poll() is not None: s.start()
        mark = '__gridlink_%s__' % uuid.uuid4().hex[:12]
        s.p.stdin.write((command + '\n' + 'echo; echo %s $?\n' % mark).encode())
        s.p.stdin.flush()
        out = []; size = 0; code = None; deadline = time.time() + timeout
        while True:
            left = deadline - time.time()
            if left <= 0:
                s.restart()
                return _clip(''.join(out)) + '\n[timed out after %d s; shell restarted]' % timeout, 124
            try: line = s.q.get(timeout=min(left, 1.0))
            except queue.Empty: continue
            if line is None:
                s.p = None
                return _clip(''.join(out)) + '\n[shell exited]', 1
            text = line.decode('utf-8', 'replace')
            if text.startswith(mark):
                try: code = int(text.split()[1])
                except (IndexError, ValueError): code = 0
                break
            size += len(text)
            if size < LIMIT * 4: out.append(text)
        text = ''.join(out)
        if text.endswith('\n\n'): text = text[:-1]
        if text.endswith('\n'): text = text[:-1]
        return _clip(text), code


def _clip(text):
    if len(text) <= LIMIT: return text
    half = LIMIT // 2
    return text[:half] + '\n[... %d characters cut ...]\n' % (len(text) - LIMIT) + text[-half:]
