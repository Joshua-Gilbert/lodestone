"""Remote procedure calls to the GRiD (REQUEST/REPLY messages)."""
import struct, threading, time
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
    0xFF: 'unknown request',
}
GPIB_ERRORS = {1: 'timeout', 2: 'no listener at that address', 3: 'GRiD is not the controller',
               4: 'bad function', 5: 'no data (read timeout)', 6: 'GPIB driver busy'}

READ_CHUNK = 8192
WRITE_CHUNK = 4000


class GridError(Exception):
    def __init__(s, msg, code=None):
        super().__init__(msg); s.code = code


def errtext(code):
    return DOS_ERRORS.get(code, 'DOS error %d' % code)


class Grid:
    def __init__(s, link):
        s.link = link
        s.cv = threading.Condition()
        s.replies = {}; s.waiting = set(); s.next_id = 1
        s.generation = 0                       # bumps when the GRiD restarts
        s.ended = 0; s.why = ''                # bumps when the calls waiting end, and why
        s.info = {}
        s.after_run = None                     # called when a RUN ends (Term: a picture is gone)

    # ---- plumbing ------------------------------------------------------
    def on_reply(s, body):
        if len(body) < 2: return
        with s.cv:
            if body[0] in s.waiting:
                s.replies[body[0]] = (body[1], bytes(body[2:]))
                s.cv.notify_all()

    def on_restart(s):
        s.end_calls('the GRiD restarted the link', restart=True)

    def end_calls(s, why, restart=False):
        """The calls waiting now fail with this: the GRiD restarted the link,
        or the user went back from resident Claude's console to the program."""
        with s.cv:
            if restart: s.generation += 1
            s.ended += 1; s.why = why
            s.cv.notify_all()

    def call(s, op, args=b'', timeout=60.0):
        with s.cv:
            rid = s.next_id; s.next_id = s.next_id % 250 + 1
            s.waiting.add(rid); s.replies.pop(rid, None); gen = s.ended
        s.link.send(glp.P_REQUEST, bytes([rid, op]) + bytes(args))
        deadline = time.time() + timeout
        with s.cv:
            try:
                while rid not in s.replies:
                    left = deadline - time.time()
                    if s.ended != gen: raise GridError(s.why)
                    if left <= 0: raise GridError('the GRiD did not answer in %d s' % timeout)
                    s.cv.wait(min(left, 0.5))
                return s.replies.pop(rid)
            finally:
                s.waiting.discard(rid)

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

    def read_file(s, path, limit=256 * 1024, progress=None):
        data = bytearray()
        while len(data) < limit:
            chunk = s.read(path, len(data), min(READ_CHUNK, limit - len(data)))
            data += chunk
            if progress: progress(len(data))
            if len(chunk) < READ_CHUNK: break
        return bytes(data)

    def write(s, path, data, mode=0, offset=0):
        no_device(path)
        r = s.ok(glp.OP_WRITE, struct.pack('<BI', mode, offset) + glp.asciiz(path) + bytes(data),
                 timeout=60.0)
        n = struct.unpack('<H', r[:2])[0] if len(r) >= 2 else len(data)
        if n != len(data): raise GridError('disk full (wrote %d of %d bytes)' % (n, len(data)), 0xF4)

    def write_file(s, path, data, progress=None):
        data = bytes(data)
        s.write(path, data[:WRITE_CHUNK], mode=0)
        done = min(len(data), WRITE_CHUNK)
        while done < len(data):
            s.write(path, data[done:done + WRITE_CHUNK], mode=2)
            done += WRITE_CHUNK
            if progress: progress(min(done, len(data)))

    def write_file_safe(s, path, data, progress=None):
        """Write NAME.$$$ first, then swap it in, so a broken link can't leave
        a half-written file under the real name."""
        tmp = temp_name(path)
        s.write_file(tmp, data, progress)
        try:
            try: s.delete(path)
            except GridError as e:
                if e.code not in (2,): raise
            s.rename(tmp, path)
        except GridError:                   # (e.g. a name DOS won't take, 3:
            try: s.delete(tmp)              #  NAME.$$$ isn't left behind)
            except GridError: pass
            raise

    def delete(s, path): s.ok(glp.OP_DELETE, glp.asciiz(path))
    def rename(s, old, new): s.ok(glp.OP_RENAME, glp.asciiz(old) + glp.asciiz(new))
    def mkdir(s, path): s.ok(glp.OP_MKDIR, glp.asciiz(path))
    def rmdir(s, path): s.ok(glp.OP_RMDIR, glp.asciiz(path))

    def stat(s, path):
        r = s.ok(glp.OP_STAT, glp.asciiz(path))
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
        st, r = s.call(glp.OP_TYPE, bytes(keys), timeout=timeout)
        if st not in (0, 0xF5) or not r: raise GridError(errtext(st), st)
        return bool(r[0] & 1), (r[1:] if st == 0 else None)

    def gpib(s, op, addr, data=b'', flags=0, timeout_ms=2000, maxlen=4096):
        """op/addr/flags (1 byte each), per-byte timeout ms (2), largest
        reply (2), then data to send."""
        maxlen = max(1, min(int(maxlen), 15000))
        args = struct.pack('<BBBHH', op, addr, flags, min(timeout_ms, 65535), maxlen) + bytes(data)
        st, r = s.call(glp.OP_GPIB, args, timeout=timeout_ms / 1000.0 + 30)
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
    return base.split('.')[0].strip().rstrip(':').strip().upper() in DEVICES    # (AUX: and COM1.TXT too)


def no_device(path):
    if is_device(path): raise GridError('%s is a DOS device, not a file' % path, 5)


def is_grid_path(p):
    p = p.strip()
    return len(p) >= 2 and p[1] == ':' and p[0].isalpha()


def norm(p):
    """Normalise a GRiD path: forward slashes to backslashes, upper case."""
    return p.strip().replace('/', '\\').upper()
