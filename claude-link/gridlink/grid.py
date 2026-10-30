"""Remote procedure calls to the GRiD (REQUEST/REPLY messages)."""
import re, struct, threading, time
from . import glp

DOS_ERRORS = {
    1: 'invalid function', 2: 'file not found', 3: 'path not found', 4: 'too many open files',
    5: 'access denied', 6: 'invalid handle', 8: 'not enough memory', 11: 'invalid format',
    15: 'invalid drive', 16: 'cannot remove the current directory', 17: 'not the same drive',
    18: 'no more files', 19: 'disk is write-protected', 20: 'unknown unit', 21: 'drive not ready',
    23: 'data error (CRC)', 25: 'seek error', 26: 'unknown media type', 27: 'sector not found',
    29: 'write fault', 30: 'read fault', 31: 'general failure', 32: 'sharing violation',
    80: 'file exists', 82: 'cannot make directory entry',
    83: 'disk error (drive not ready, write-protected or bad disk)',
    0xF0: 'request too large for the GRiD', 0xF1: 'not enough memory on the GRiD',
    0xF2: 'GPIB driver not found', 0xF3: 'command line too long for DOS', 0xF4: 'disk full',
    0xF5: 'no snapshot taken', 0xF6: 'a DOS program is paused on the GRiD (resident Claude)',
    0xF7: ('DOS is busy under the program resident Claude\'s console is popped up over (it is inside a DOS '
           'call other than the kernel\'s key wait, e.g. its own disk-error handler, or in the key wait of '
           'Lodestone\'s tasks, MULTITASK=1, or it is DEFRAG, which writes the disk itself): the '
           'GRiD\'s files can\'t be used from this pop-up. They can once the user goes back to the program '
           '(CODE-\\) and brings the console up again at another of its key waits'),
    0xFF: 'unknown request',
}
# what resident Claude's console serves in the background (M4): files and GPIB (SCREEN too where its HELLO
# says bgscreen, CLAUDE 1.11: Term adds it); never TYPE
OPS_BG = frozenset(range(glp.OP_DIR, glp.OP_FREE + 1)) | {glp.OP_GPIB}

GPIB_ERRORS = {1: 'timeout', 2: 'no listener at that address', 3: 'GRiD is not the controller',
               4: 'bad function', 5: 'no data (read timeout)', 6: 'GPIB driver busy'}

READ_CHUNK = 8192
HUGE_READ_CHUNK = 16384     # CLAUDE 1.7 says rd=16384 (and frames of 3300 out of it: five a read)
WRITE_CHUNK = 4000      # a CLAUDE before 1.5 takes 4,700-byte requests: 4,000 bytes and a path
BIG_WRITE_CHUNK = 8192  # CLAUDE 1.5 says req=8700: each write request's DOS open, seek and close goes for twice as much
HUGE_WRITE_CHUNK = 16384   # CLAUDE 1.6 says req=16700 (and rx=3340: five frames a request, no short last one)


class GridError(Exception):
    def __init__(s, msg, code=None):
        super().__init__(msg); s.code = code


def errtext(code):
    return DOS_ERRORS.get(code, 'DOS error %d' % code)


class Grid:
    def __init__(s, link):
        s.link = link
        s.cv = threading.Condition()
        s.replies = {}; s.waiting = {}; s.next_id = 1    # waiting: id -> op
        s.dead = {}                            # id -> why: a call ended (end_calls)
        s.generation = 0                       # bumps when the GRiD restarts
        s.ended = 0; s.why = ''                # bumps when the calls waiting end, and why
        s.info = {}
        s.after_run = None                     # called when a RUN ends (Term: a picture is gone)
        s.typing = 0                           # TYPEs waiting: resident Claude's console is down meanwhile
        s.n_replies = 0                        # REPLYs from the GRiD, counted
        s.type_out = False                     # one given up on (timed out): the console may be down still,
                                               #  until we hear from it (a REPLY: TYPE's own comes first)

    # ---- plumbing ------------------------------------------------------
    def on_reply(s, body):
        if len(body) < 2: return
        with s.cv:
            s.type_out = False; s.n_replies += 1
            if body[0] in s.waiting and body[0] not in s.dead:
                s.replies[body[0]] = (body[1], bytes(body[2:]))
                s.cv.notify_all()

    def on_restart(s):
        s.end_calls('the GRiD restarted the link', restart=True)

    def end_calls(s, why, restart=False, keep=()):
        """The calls waiting now fail with this: the GRiD restarted the link,
        or the user went back from resident Claude's console to the program
        (keep: the ops the console goes on with in the background, M4)."""
        with s.cv:
            if restart: s.generation += 1; s.type_out = False
            s.ended += 1; s.why = why
            for rid, op in s.waiting.items():
                if op not in keep: s.dead[rid] = why
            s.cv.notify_all()

    def call(s, op, args=b'', timeout=60.0):
        with s.cv:
            rid = s.next_id; s.next_id = s.next_id % 250 + 1
            s.waiting[rid] = op; s.replies.pop(rid, None); s.dead.pop(rid, None)
        msg = bytes([rid, op]) + bytes(args)
        s.link.send(glp.P_REQUEST, msg)
        deadline = time.monotonic() + timeout
        with s.cv:
            try:
                while rid not in s.replies:
                    left = deadline - time.monotonic()
                    if rid in s.dead:
                        s.link.withdraw(glp.P_REQUEST, msg)    # (queued after the HELLO that ended it: not to run)
                        raise GridError(s.dead[rid])
                    if left <= 0:
                        # (not yet on its way: taken back, so it can't run later, after we have said it failed;
                        # resident Claude's background waits for its program's key calls, M4)
                        if s.link.withdraw(glp.P_REQUEST, msg):
                            raise GridError('the GRiD did not take the request in %d s (it was withdrawn: '
                                            'nothing was done)' % timeout)
                        raise GridError('the GRiD did not answer in %d s' % timeout)
                    s.cv.wait(min(left, 0.5))
                return s.replies.pop(rid)
            finally:
                s.waiting.pop(rid, None); s.dead.pop(rid, None)

    def ok(s, op, args=b'', timeout=60.0):
        st, data = s.call(op, args, timeout)
        if st: raise GridError(errtext(st), st)
        return data

    # ---- operations ----------------------------------------------------
    def get_info(s):
        s.info = glp.kv_lines(s.ok(glp.OP_INFO))
        return s.info

    def dir(s, pattern):
        data = s.ok(glp.OP_DIR, glp.asciiz(pattern))
        out = []
        for i in range(0, len(data) - 21, 22):
            attr, tm, dt, size = struct.unpack_from('<BHHI', data, i)
            name = data[i + 9:i + 22].split(b'\0')[0].decode('cp437', 'replace')
            out.append(dict(name=name, attr=attr, size=size, dir=bool(attr & 0x10),
                            date='%04d-%02d-%02d' % (1980 + (dt >> 9), (dt >> 5) & 15, dt & 31),
                            time='%02d:%02d' % (tm >> 11, (tm >> 5) & 63)))
        return out

    def read(s, path, offset=0, length=READ_CHUNK):
        no_device(path)
        return s.ok(glp.OP_READ, struct.pack('<IH', offset, length) + glp.asciiz(path))

    def read_chunk(s):
        return HUGE_READ_CHUNK if getattr(s.link, 'grid_rd', 0) >= HUGE_READ_CHUNK else READ_CHUNK

    def read_file(s, path, limit=256 * 1024, progress=None):
        data = bytearray()
        size = s.read_chunk()
        while len(data) < limit:
            want = min(size, limit - len(data))
            chunk = s.read(path, len(data), want)
            data += chunk
            if progress: progress(len(data))
            if len(chunk) < want: break
        return bytes(data)

    def write(s, path, data, mode=0, offset=0):
        no_device(path)
        r = s.ok(glp.OP_WRITE, struct.pack('<BI', mode, offset) + glp.asciiz(path) + bytes(data),
                 timeout=60.0)
        n = struct.unpack('<H', r[:2])[0] if len(r) >= 2 else len(data)
        if n != len(data): raise GridError('disk full (wrote %d of %d bytes)' % (n, len(data)), 0xF4)

    def write_chunk(s):
        req = getattr(s.link, 'grid_req', glp.GRID_REQ_DEFAULT)
        for c in (HUGE_WRITE_CHUNK, BIG_WRITE_CHUNK):
            if req >= c + 300: return c
        return WRITE_CHUNK

    def write_file(s, path, data, progress=None):
        data = bytes(data)
        chunk = s.write_chunk()
        s.write(path, data[:chunk], mode=0)
        done = min(len(data), chunk)
        while done < len(data):
            s.write(path, data[done:done + chunk], mode=2)
            done += chunk
            if progress: progress(min(done, len(data)))

    def write_file_safe(s, path, data, progress=None):
        """Write NAME.$$$ first, then swap it in, so a broken link can't leave
        a half-written file under the real name."""
        tmp = temp_name(path)
        s.write_file(tmp, data, progress)
        try: s.delete(path)
        except GridError as e:
            if e.code not in (2,):          # the old file stays (a name DOS won't
                try: s.delete(tmp)          #  take, 3; or 5): NAME.$$$ goes.  Once
                except GridError: pass      #  it's deleted, NAME.$$$ is the only
                raise                       #  copy: kept if the rename fails
        s.rename(tmp, path)

    def delete(s, path): s.ok(glp.OP_DELETE, glp.asciiz(path))
    def rename(s, old, new): s.ok(glp.OP_RENAME, glp.asciiz(old) + glp.asciiz(new))
    def mkdir(s, path): s.ok(glp.OP_MKDIR, glp.asciiz(path))
    def rmdir(s, path): s.ok(glp.OP_RMDIR, glp.asciiz(path))

    def stat(s, path):
        if len(path) > 3: path = path.rstrip('\\')     # (SUB\: DOS says 3 for a \ last, as MS-DOS; not the root's)
        try: r = s.ok(glp.OP_STAT, glp.asciiz(path))
        except GridError as e:                  # (FIND FIRST's "no more files", as in
            if e.code == 18: raise GridError(errtext(2), 2) from None    #  MS-DOS: not there)
            raise
        attr, tm, dt, size = struct.unpack_from('<BHHI', r)
        return dict(attr=attr, size=size, dir=bool(attr & 0x10),
                    date='%04d-%02d-%02d' % (1980 + (dt >> 9), (dt >> 5) & 15, dt & 31),
                    time='%02d:%02d' % (tm >> 11, (tm >> 5) & 63))

    def exists(s, path):
        try: s.stat(path); return True
        except GridError as e:
            if e.code in (2, 3, 18): return False
            raise

    def free(s, drive=0):
        r = s.ok(glp.OP_FREE, bytes([drive]))
        return struct.unpack('<II', r[:8])

    def run(s, command, capture=True, snapshot=False, keys=b'', timeout=3600):
        flags = (1 if capture else 0) | (2 if snapshot else 0)
        args = struct.pack('<BHH', flags, min(timeout, 65535), len(keys)) + bytes(keys) + glp.asciiz(command)
        try:
            st, r = s.call(glp.OP_RUN, args, timeout=timeout + 30)
        finally:
            if s.after_run is not None: s.after_run()      # (the program drew over the screen)
        if st: raise GridError(errtext(st), st)
        code, rflags = struct.unpack_from('<HB', r)
        outname = r[3:].split(b'\0')[0].decode('cp437', 'replace')
        return dict(exit=code, output=bool(rflags & 1), snapshot=bool(rflags & 2), outfile=outname)

    def screen(s, which=0):
        return s.ok(glp.OP_SCREEN, bytes([which]), timeout=120)

    def type_keys(s, keys, timeout=60):
        """Keys (a compiled key script) into the DOS program paused under
        resident Claude's console.  The answer comes once they have played,
        or CODE-\\ stopped them: (all played?, the screen then as SCREEN
        gives it, or None if its mode isn't one the console keeps)."""
        with s.cv: s.typing += 1; ended, seen = s.ended, s.n_replies
        done = False
        try:
            st, r = s.call(glp.OP_TYPE, bytes(keys), timeout=timeout); done = True
        finally:
            with s.cv:
                s.typing -= 1
                if not done and s.ended == ended and s.n_replies == seen:    # (not ended by a HELLO or
                    s.type_out = True                                      #  EVENT away; no REPLY since)
        if st not in (0, 0xF5) or not r: raise GridError(errtext(st), st)
        return bool(r[0] & 1), (r[1:] if st == 0 else None)

    def gpib(s, op, addr, data=b'', flags=0, timeout_ms=2000, maxlen=4096, wait=None):
        """op/addr/flags (1 byte each), per-byte timeout ms (2), largest
        reply (2), then data to send.  `wait`: seconds the Pi waits for the
        answer (default the GPIB time-out and 30 s for the GRiD)."""
        maxlen = max(1, min(int(maxlen), 15000))
        args = struct.pack('<BBBHH', op, addr, flags, min(timeout_ms, 65535), maxlen) + bytes(data)
        st, r = s.call(glp.OP_GPIB, args, timeout=wait or timeout_ms / 1000.0 + 30)
        if st == 0xF2: raise GridError(errtext(st), st)
        if st: raise GridError('GPIB: ' + GPIB_ERRORS.get(st, 'error %d' % st), st)
        return r

    def settime(s, t=None):
        t = time.localtime(t)
        s.ok(glp.OP_SETTIME, struct.pack('<HBBBBB', t.tm_year, t.tm_mon, t.tm_mday,
                                         t.tm_hour, t.tm_min, t.tm_sec))


def temp_name(path):
    """A:\\DIR\\NAME.EXT -> A:\\DIR\\NAME.$$$"""
    head, sep, tail = path.rpartition('\\')
    base = tail.split('.')[0] or 'CLAUDE'
    return head + sep + base[:8] + '.$$$'


DEVICES = {'CON', 'AUX', 'PRN', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'LPT1', 'LPT2', 'LPT3', 'CLOCK$',
           'EMMXXXX0'}                             # (Lodestone's EMS manager's device)


def is_device(path):
    """DOS opens a device for these names in any directory, with any
    extension: A:\\X\\AUX.TXT is the serial port, and reading it waits
    forever."""
    base = path.replace('/', '\\').rpartition('\\')[2]
    if len(base) >= 2 and base[1] == ':': base = base[2:]          # (A:NUL)
    name = base.split('.')[0].strip().rstrip(':').strip().upper()
    return name in DEVICES or re.fullmatch(r'GPIB\d{1,2}', name) is not None    # (AUX: and COM1.TXT; Lodestone's GPIBnn)


def no_device(path):
    if is_device(path): raise GridError('%s is a DOS device, not a file' % path, 5)


def is_grid_path(p):
    p = p.strip()
    return len(p) >= 2 and p[1] == ':' and p[0].isalpha()


def norm(p):
    """Normalise a GRiD path: forward slashes to backslashes, upper case."""
    return p.strip().replace('/', '\\').upper()
