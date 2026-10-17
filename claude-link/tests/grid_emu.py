"""The real CLAUDE.COM, end to end, on an emulated GRiD.

An x86 real-mode CPU (unicorn) with a small DOS 3.30 and BIOS, the uPD7210
GPIB chip and bus (sim7210), the real GRIDGPIB.COM driver resident, the AR488
bridge model, and the real gridlink Pi side with a scripted Claude.  Time is
simulated: 4 us per basic block, BIOS ticks at 18.2 Hz, PIT channel 0 and the
port 61h refresh toggle follow it, HLT sleeps to the next tick.

    python3 tests/grid_emu.py [outdir]     runs the scenarios, writes PNGs

CLAUDE_COM, GRIDGPIB_COM and TESTKEY_COM in the environment override where
the binaries are found.
"""
import collections, datetime, os, struct, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR, UC_HOOK_INSN, UC_HOOK_BLOCK
from unicorn import x86_const as X
import sim7210 as S
from ar488_model import AR488Model
from gridsim import ModelTransport
from fake_anthropic import FakeAnthropic
from gridlink.link import Link
from gridlink.agent import Session
from gridlink.config import Config
from gridlink.router import Router


def _find(env, *cands):
    if os.environ.get(env): return os.environ[env]
    for c in cands:
        if os.path.exists(c): return c
    return cands[-1]

ROOT = os.path.dirname(HERE)
CLAUDE_COM = _find('CLAUDE_COM', os.path.join(ROOT, '..', 'os', 'claude', 'CLAUDE.COM'),
                   '/home/claude/gos/claude/CLAUDE.COM')
TESTKEY_COM = _find('TESTKEY_COM', os.path.join(ROOT, '..', 'os', 'claude', 'TESTKEY.COM'),
                    '/home/claude/gos/claude/TESTKEY.COM')
GRIDGPIB_COM = _find('GRIDGPIB_COM', os.path.join(HERE, 'bin', 'GRIDGPIB.COM'),
                     '/home/claude/TM5000/driver/gridgpib/GRIDGPIB.COM')

TICK_US = 1e6 * 65536 / 1193182        # 54925.4 us
BLOCK_US = 4.0
STUB = 0xF000                           # BIOS stubs: F000:n*8 = INT n; RETF 2
R = {n: getattr(X, 'UC_X86_REG_' + n.upper()) for n in
     'ax bx cx dx si di bp sp cs ds es ss ip flags al ah bl bh cl ch dl dh'.split()}
GLYPH_NAMES = {0x80: '\u25cf', 0x81: '\u23bf', 0x82: '\u2026', 0x83: '\u2192', 0x84: '\u2713', 0x85: '\u2717',
               0x86: '\u00b7', 0x87: '\u00b7', 0x88: '+', 0x89: '*', 0x8A: '\u2736', 0x8B: '\u273b', 0x8C: '\u273d',
               0x8D: '\u2500', 0x8E: '\u2502', 0x8F: '\u25b8', 0x90: '\u00b0', 0x91: '\u00b5', 0x92: '\u03a9',
               0x93: '\u00b1', 0x94: '\u00d7', 0x95: '\u2248', 0x96: '\u2264', 0x97: '\u2265', 0x7F: '\u2588',
               0x98: '\u2514', 0x99: '\u2518', 0x9A: '\u250c', 0x9B: '\u2510', 0x9C: '\u251c', 0x9D: '\u2524',
               0x9E: '\u252c', 0x9F: '\u2534', 0xA0: '\u253c'}


class Chip(S.NEC7210):
    """The 7210 bus model, extended for a device-mode AR488 on the bus:
    talk is decided when ATN drops (TAD comes before SPE in a serial poll),
    data bytes go to the AR488 one by one with EOI, SDC/DCL reach it, and
    its SRQ line shows in ISR2."""
    def __init__(s, devices):
        super().__init__(devices)
        s.pending_talk = None
        s.clock = lambda: 0.0; s.do_at = 0.0

    def ar(s, a):
        d = s.devices.get(a)
        return d if isinstance(d, AR488Model) else None

    def read(s, reg):
        if reg == 2:
            v = super().read(2)
            for d in s.devices.values():
                if isinstance(d, AR488Model):
                    d.service()
                    if d.srq: v |= 0x40
            return v
        if reg == 1 and s.do and s.clock() < s.do_at:      # AR488 still busy with the byte
            s.do = False; v = super().read(1); s.do = True
            return v
        return super().read(reg)

    def aux(s, v):
        if v == 0x10 and s.cic and not s.tcs_pending and s.pending_talk is not None:
            d = s.ar(s.pending_talk)
            if d is not None and not s.spe: d.on_talk()
            s.pending_talk = None
        super().aux(v)

    def cdor(s, v):
        if s.atn:
            if s.cic:
                if 0x40 <= v <= 0x5E: s.pending_talk = v - 0x40
                elif v == 0x5F: s.pending_talk = None
                elif v == 0x3F:
                    for a in list(s.listeners):
                        d = s.ar(a)
                        if d is not None: d.on_listen(False)
                elif 0x20 <= v <= 0x3E:
                    d = s.ar(v - 0x20)
                    if d is not None: d.on_listen(True)
                elif v == 0x04:
                    for a in s.listeners:
                        d = s.ar(a)
                        if d is not None: d.sdc()
                elif v == 0x14:
                    for d in s.devices.values():
                        if isinstance(d, AR488Model): d.sdc()
            return super().cdor(v)
        if not s.chip_talks(): return
        ars = [s.ar(a) for a in s.listeners if s.ar(a) is not None]
        if not ars: return super().cdor(v)
        eoi = s.seoi
        others = [s.devices[a] for a in s.listeners if a in s.devices and s.ar(a) is None]
        s.seoi = False; s.do = True
        for d in ars: s.do_at = max(s.do_at, d.rx_byte(v, eoi) or 0.0)
        for d in others:
            d.inbuf += bytes([v])
            if eoi or v == 0x0A: d.message(d.inbuf); d.inbuf = b''


class Machine:
    MEMBASE = 0x0600
    MEMTOP = 0x9FC0

    def __init__(s, devices=None, files=None, start=datetime.datetime(2026, 10, 4, 20, 30, 0)):
        s.mu = mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x110000)
        s.us = 0.0; s.next_tick = TICK_US; s.next_event = TICK_US
        s.on_due = None; s.due_at = float('inf')
        s.chip = Chip(devices if devices is not None else S.bus())
        s.chip.clock = s.clock
        s.fs = {}; s.dirs = {'A:\\', 'B:\\', 'C:\\'}; s.cwd = 'A:\\'
        for k, v in (files or {}).items(): s.fs[s.norm(k)] = bytearray(v)
        s.handles = {}; s.finds = {}; s.dta = (0, 0x80)
        s.keys = collections.deque(); s.tty = []; s.log = []
        s.blocks = []; s.psp = 0; s.ctx = []; s.last_exit = 0
        s.stopped = False; s.exit_code = None; s.crash = None
        s.clock0 = start; s.clock_set = None; s.rtc_set = []
        s.pit_latch = None; s.pit_hi = False
        s.last_blk = (0, 0); s.halted = False; s.blocked = False
        s.ints = collections.Counter()
        for n in range(256):
            mu.mem_write(n * 4, struct.pack('<HH', n * 8, STUB))
            mu.mem_write(STUB * 16 + n * 8, bytes([0xCD, n, 0xCA, 0x02, 0x00]))
        for n in range(0x60, 0x68):
            mu.mem_write(n * 4, b'\0\0\0\0')
        mu.mem_write(0x410, struct.pack('<H', 0x4423)); mu.mem_write(0x413, struct.pack('<H', 640))
        mu.mem_write(0x449, bytes([3])); mu.mem_write(0x44A, struct.pack('<H', 80))
        mu.mem_write(0x44E, b'\0\0'); mu.mem_write(0x450, b'\0\0')
        mu.mem_write(0xFFFFE, b'\xFC')
        mu.hook_add(UC_HOOK_INTR, s.intr)
        mu.hook_add(UC_HOOK_INSN, s.hin, None, 1, 0, X.UC_X86_INS_IN)
        mu.hook_add(UC_HOOK_INSN, s.hout, None, 1, 0, X.UC_X86_INS_OUT)
        mu.hook_add(UC_HOOK_BLOCK, s.blk)

    # ---- registers and memory ---------------------------------------------
    def r(s, n): return s.mu.reg_read(R[n])
    def w(s, n, v): s.mu.reg_write(R[n], v & 0xFFFF)
    def cf(s, c):
        f = s.r('flags'); s.w('flags', (f | 1) if c else (f & ~1))
    def zf(s, z):
        f = s.r('flags'); s.w('flags', (f | 0x40) if z else (f & ~0x40))
    def err(s, code):
        s.w('ax', code); s.cf(1); s.last_err = code
    def rd(s, seg, off, n): return bytes(s.mu.mem_read((seg * 16 + off) & 0xFFFFF, n))
    def wr(s, seg, off, data): s.mu.mem_write((seg * 16 + off) & 0xFFFFF, bytes(data))
    def u16(s, seg, off): return struct.unpack('<H', s.rd(seg, off, 2))[0]
    def asciiz(s, seg, off, limit=256):
        b = s.rd(seg, off, limit); return b.split(b'\0')[0]
    def push(s, v):
        sp = (s.r('sp') - 2) & 0xFFFF; s.w('sp', sp); s.wr(s.r('ss'), sp, struct.pack('<H', v & 0xFFFF))

    # ---- time ---------------------------------------------------------------
    def clock(s): return s.us

    def schedule(s, t):
        if t < s.due_at: s.due_at = t
        if t < s.next_event: s.next_event = t

    def blk(s, uc, addr, size, ud):
        s.last_blk = (addr, size)
        s.us += BLOCK_US
        if s.us >= s.next_event: s.on_time()

    def on_time(s):
        while s.us >= s.next_tick:
            t = struct.unpack('<I', s.rd(0, 0x46C, 4))[0] + 1
            s.wr(0, 0x46C, struct.pack('<I', t))
            s.next_tick += TICK_US
        if s.us >= s.due_at:
            s.due_at = float('inf')
            if s.on_due: s.on_due()          # may schedule() again
        s.next_event = min(s.next_tick, s.due_at)

    def sleep_to_tick(s):
        s.us = max(s.us, s.next_tick); s.on_time()

    def now(s):
        return s.clock0 + datetime.timedelta(microseconds=s.us)

    # ---- ports --------------------------------------------------------------
    def hin(s, uc, port, size, ud):
        if port == 0x40:
            if s.pit_latch is None:
                n = int(s.us * 1.193182) % 32768
                s.pit_latch = (65536 - 2 * n) & 0xFFFF; s.pit_hi = False
            v = s.pit_latch
            if not s.pit_hi: s.pit_hi = True; return v & 0xFF
            s.pit_latch = None; return v >> 8
        if port == 0x61:
            return 0x00 | ((int(s.us / 15.085) & 1) << 4)
        if (port & 0x3FF) == S.BASE and port < 0x2000:
            return s.chip.read(port >> 10)
        return 0xFF

    def hout(s, uc, port, size, val, ud):
        if port == 0x43:
            if (val & 0xC0) == 0 and (val & 0x30) == 0:
                n = int(s.us * 1.193182) % 32768
                s.pit_latch = (65536 - 2 * n) & 0xFFFF; s.pit_hi = False
            return
        if (port & 0x3FF) == S.BASE and port < 0x2000:
            s.chip.write(port >> 10, val & 0xFF)

    # ---- interrupts ---------------------------------------------------------
    def intr(s, uc, n, ud):
        cs, ip = s.r('cs'), s.r('ip')
        if cs != STUB:
            off, seg = struct.unpack('<HH', s.rd(0, n * 4, 4))
            if not (seg == STUB and off == n * 8):
                if seg == 0 and off == 0:
                    s.crash = 'INT %02Xh through a null vector at %04X:%04X' % (n, cs, ip)
                    uc.emu_stop(); return
                s.push(s.r('flags')); s.push(cs); s.push(ip)
                s.w('flags', s.r('flags') & ~0x300)
                s.w('cs', seg); s.w('ip', off)
                return
        s.ints[n] += 1
        h = getattr(s, 'int%02x' % n, None)
        if h: h()
        else: s.log.append('[int %02Xh AX=%04X ignored]' % (n, s.r('ax')))

    def int10(s):
        ah, al = s.r('ah'), s.r('al')
        if ah == 0x00:
            mode = al & 0x7F
            s.wr(0, 0x449, [mode]); s.wr(0, 0x450, b'\0\0')
            if mode == 0x40:
                s.wr(0xB800, 0, bytes(0x8000))
            else:
                s.wr(0xB800, 0, b'\x20\x07' * 2000)
            s.log.append('[mode %02Xh]' % mode)
        elif ah == 0x0F:
            s.w('ax', 0x5000 | s.rd(0, 0x449, 1)[0]); s.w('bx', s.r('bx') & 0xFF)
        elif ah == 0x02:
            s.wr(0, 0x450, [s.r('dl'), s.r('dh')])
        elif ah == 0x03:
            c, r_ = s.rd(0, 0x450, 2); s.w('dx', (r_ << 8) | c); s.w('cx', 0x0607)
        elif ah == 0x0E:
            s.tty_put(al)
        elif ah in (0x09, 0x0A):
            c, r_ = s.rd(0, 0x450, 2)
            for i in range(s.r('cx')):
                p = r_ * 80 + c + i
                if p < 2000: s.wr(0xB800, p * 2, [al] + ([s.r('bl')] if ah == 9 else []))
        elif ah == 0x06 or ah == 0x07:
            if s.rd(0, 0x449, 1)[0] < 4: s.wr(0xB800, 0, b'\x20\x07' * 2000)

    def tty_put(s, ch):
        s.tty.append(chr(ch))
        if s.rd(0, 0x449, 1)[0] >= 4: return
        c, r_ = s.rd(0, 0x450, 2)
        if ch == 13: c = 0
        elif ch == 10: r_ += 1
        elif ch == 8: c = max(0, c - 1)
        elif ch == 7: pass
        else:
            s.wr(0xB800, (r_ * 80 + c) * 2, [ch, 7]); c += 1
            if c >= 80: c = 0; r_ += 1
        if r_ >= 25:
            v = s.rd(0xB800, 160, 3840); s.wr(0xB800, 0, v + b'\x20\x07' * 80); r_ = 24
        s.wr(0, 0x450, [c, r_])

    def int16(s):
        ah = s.r('ah')
        if ah in (0x00, 0x10):
            if s.keys:
                s.w('ax', s.keys.popleft())
            else:                               # wait: run time on, try again
                s.w('ip', s.r('ip') - 2); s.blocked = True; s.mu.emu_stop()
        elif ah in (0x01, 0x11):
            if s.keys: s.w('ax', s.keys[0]); s.zf(0)
            else: s.zf(1)
        elif ah in (0x02, 0x12):
            s.w('ax', s.r('ax') & 0xFF00)

    def int1a(s):
        ah = s.r('ah')
        if ah == 0x00:
            t = struct.unpack('<I', s.rd(0, 0x46C, 4))[0]
            s.w('cx', t >> 16); s.w('dx', t); s.w('ax', 0)
        elif ah == 0x02:
            n = s.now(); bcd = lambda v: ((v // 10) << 4) | (v % 10)
            s.w('cx', (bcd(n.hour) << 8) | bcd(n.minute)); s.w('dx', bcd(n.second) << 8); s.cf(0)
        elif ah == 0x04:
            n = s.now(); bcd = lambda v: ((v // 10) << 4) | (v % 10)
            s.w('cx', (bcd(n.year // 100) << 8) | bcd(n.year % 100)); s.w('dx', (bcd(n.month) << 8) | bcd(n.day)); s.cf(0)
        elif ah in (0x03, 0x05):
            s.rtc_set.append((ah, s.r('cx'), s.r('dx'))); s.cf(0)

    def int11(s): s.w('ax', 0x4423)
    def int12(s): s.w('ax', 640)
    def int15(s): s.w('ax', (s.r('ax') & 0xFF) | 0x8600); s.cf(1)
    def int28(s): pass

    def int20(s):
        s.w('ax', 0x4C00); s.terminate(0, tsr=False)

    # ---- files ----------------------------------------------------------------
    def norm(s, p):
        if isinstance(p, bytes): p = p.decode('cp437')
        p = p.strip().upper().replace('/', '\\')
        if len(p) >= 2 and p[1] == ':': drv, rest = p[:2], p[2:]
        else: drv, rest = s.cwd[:2], p
        if not rest.startswith('\\'):
            base = s.cwd if s.cwd[:2] == drv else drv + '\\'
            rest = base[2:] + rest
        parts = []
        for x in rest.split('\\'):
            if x in ('', '.'): continue
            if x == '..':
                if parts: parts.pop()
                continue
            parts.append(x)
        return drv + '\\' + '\\'.join(parts)

    def parent(s, p): return p.rpartition('\\')[0] + '\\'

    def isdir(s, p): return (p.rstrip('\\') + '\\') in s.dirs

    @staticmethod
    def fcb_name(name):
        n, _, e = name.partition('.')
        return (n[:8].ljust(8), e[:3].ljust(3))

    @staticmethod
    def fcb_pat(pat):
        n, _, e = pat.partition('.')
        def f(x, w):
            out = ''
            for ch in x:
                if ch == '*': out += '?' * (w - len(out)); break
                out += ch
            return out[:w].ljust(w)
        return f(n, 8), f(e, 3)

    def matches(s, pat, name):
        pn, pe = s.fcb_pat(pat); nn, ne = s.fcb_name(name)
        ok = lambda p, x: all(a == '?' or a == b for a, b in zip(p, x))
        return ok(pn, nn) and ok(pe, ne)

    def dos_dt(s):
        n = s.now()
        return ((n.hour << 11) | (n.minute << 5) | (n.second // 2),
                ((n.year - 1980) << 9) | (n.month << 5) | n.day)

    def entries(s, d):
        out = []
        for p, v in s.fs.items():
            if s.parent(p) == d: out.append((p.rpartition('\\')[2], 0x20, len(v)))
        for p in s.dirs:
            q = p.rstrip('\\')
            if q.count('\\') and s.parent(q) == d and p != d:
                out.append((q.rpartition('\\')[2], 0x10, 0))
        return sorted(out)

    def put_find(s, st):
        name, attr, size = st['list'][st['i']]; st['i'] += 1
        t, d = s.dos_dt()
        seg, off = s.dta
        s.wr(seg, off, bytes(21) + struct.pack('<BHHI', attr, t, d, size) + name.encode().ljust(13, b'\0')[:13])

    # ---- DOS ------------------------------------------------------------------
    def int21(s):
        ah, al = s.r('ah'), s.r('al')
        ds, dx, bx, cx = s.r('ds'), s.r('dx'), s.r('bx'), s.r('cx')
        f = getattr(s, 'd%02x' % ah, None)
        if f:
            f(ah, al, ds, dx, bx, cx)
        else:
            s.log.append('[21h/%02Xh not emulated]' % ah); s.err(1)

    def d02(s, *a): s.tty_put(s.r('dl'))
    def d06(s, ah, al, ds, dx, *a):
        if dx & 0xFF == 0xFF:
            if s.keys: s.w('al', s.keys.popleft() & 0xFF); s.zf(0)
            else: s.w('al', 0); s.zf(1)
        else: s.tty_put(dx & 0xFF)
    def d09(s, ah, al, ds, dx, *a):
        p = dx
        while True:
            c = s.rd(ds, p, 1)[0]
            if c == 0x24: break
            s.tty_put(c); p += 1
    def d0b(s, *a): s.w('al', 0xFF if s.keys else 0)
    def d0e(s, *a): s.w('al', 3)
    def d19(s, *a): s.w('al', ord(s.cwd[0]) - 65)
    def d1a(s, ah, al, ds, dx, *a): s.dta = (ds, dx)
    def d2f(s, *a): s.w('es', s.dta[0]); s.w('bx', s.dta[1])
    def d25(s, ah, al, ds, dx, *a): s.wr(0, al * 4, struct.pack('<HH', dx, ds))
    def d35(s, ah, al, *a):
        o, g = struct.unpack('<HH', s.rd(0, al * 4, 4)); s.w('es', g); s.w('bx', o)
    def d2a(s, *a):
        n = s.now(); s.w('cx', n.year); s.w('dx', (n.month << 8) | n.day); s.w('al', (n.weekday() + 1) % 7)
    def d2c(s, *a):
        n = s.now(); s.w('cx', (n.hour << 8) | n.minute); s.w('dx', (n.second << 8) | (n.microsecond // 10000))
    def d2b(s, ah, al, ds, dx, bx, cx):
        n = s.now()
        try:
            s.clock0 = n.replace(year=cx, month=dx >> 8, day=dx & 0xFF) - datetime.timedelta(microseconds=s.us)
            s.w('al', 0); s.clock_set = s.now()
        except ValueError: s.w('al', 0xFF)
    def d2d(s, ah, al, ds, dx, bx, cx):
        n = s.now()
        try:
            s.clock0 = n.replace(hour=cx >> 8, minute=cx & 0xFF, second=dx >> 8, microsecond=0) \
                - datetime.timedelta(microseconds=s.us)
            s.w('al', 0); s.clock_set = s.now()
        except ValueError: s.w('al', 0xFF)
    def d30(s, *a): s.w('ax', 0x1E03); s.w('bx', 0); s.w('cx', 0)
    def d33(s, *a): s.w('dx', s.r('dx') & 0xFF00)
    def d36(s, ah, al, ds, dx, *a):
        d = dx & 0xFF
        if d > 3: s.w('ax', 0xFFFF); return
        s.w('ax', 2); s.w('bx', 600); s.w('cx', 512); s.w('dx', 713)
    def d44(s, ah, al, ds, dx, bx, cx):
        if al == 0x00:
            s.w('dx', 0x80 | (0x03 if bx < 2 else 0)) if bx < 5 else s.w('dx', 0x0000); s.cf(0)
        elif al == 0x08:
            d = bx & 0xFF
            if d == 0: d = ord(s.cwd[0]) - 64
            if d in (1, 2): s.w('ax', 0); s.cf(0)
            elif d == 3: s.w('ax', 1); s.cf(0)
            else: s.err(0x0F)
        else: s.cf(0)
    def d47(s, ah, al, ds, dx, *a):
        si = s.r('si'); d = dx & 0xFF
        s.wr(ds, si, s.cwd[3:].rstrip('\\').encode() + b'\0'); s.cf(0)
    def d3b(s, ah, al, ds, dx, *a):
        p = s.norm(s.asciiz(ds, dx))
        if not s.isdir(p): return s.err(3)
        s.cwd = p.rstrip('\\') + '\\'; s.cf(0)
    def d39(s, ah, al, ds, dx, *a):
        p = s.norm(s.asciiz(ds, dx))
        if s.isdir(p) or p in s.fs: return s.err(5)
        if not s.isdir(s.parent(p)): return s.err(3)
        s.dirs.add(p + '\\'); s.cf(0)
    def d3a(s, ah, al, ds, dx, *a):
        p = s.norm(s.asciiz(ds, dx))
        if not s.isdir(p): return s.err(3)
        if s.entries(p + '\\'): return s.err(5)
        s.dirs.discard(p + '\\'); s.cf(0)
    def d3c(s, ah, al, ds, dx, *a):
        p = s.norm(s.asciiz(ds, dx))
        if s.isdir(p): return s.err(5)
        if not s.isdir(s.parent(p)): return s.err(3)
        s.fs[p] = bytearray(); s.open_handle(p)
    def open_handle(s, p):
        h = 5
        while h in s.handles: h += 1
        s.handles[h] = {'p': p, 'pos': 0}; s.w('ax', h); s.cf(0)
    def d3d(s, ah, al, ds, dx, *a):
        p = s.norm(s.asciiz(ds, dx))
        if p not in s.fs: return s.err(5 if s.isdir(p) else (2 if s.isdir(s.parent(p)) else 3))
        s.open_handle(p)
    def d3e(s, ah, al, ds, dx, bx, cx):
        if bx in s.handles: del s.handles[bx]; s.cf(0)
        elif bx < 5: s.cf(0)
        else: s.err(6)
    def d3f(s, ah, al, ds, dx, bx, cx):
        if bx < 5 and bx not in s.handles: s.w('ax', 0); s.cf(0); return
        h = s.handles.get(bx)
        if not h: return s.err(6)
        d = s.fs[h['p']][h['pos']:h['pos'] + cx]
        s.wr(ds, dx, d); h['pos'] += len(d); s.w('ax', len(d)); s.cf(0)
    def d40(s, ah, al, ds, dx, bx, cx):
        data = s.rd(ds, dx, cx)
        if bx in (1, 2) and bx not in s.handles:
            for c in data: s.tty_put(c)
            s.w('ax', cx); s.cf(0); return
        h = s.handles.get(bx)
        if not h: return s.err(6)
        f = s.fs[h['p']]
        if cx == 0: del f[h['pos']:]
        else:
            if len(f) < h['pos']: f.extend(bytes(h['pos'] - len(f)))
            f[h['pos']:h['pos'] + cx] = data
        h['pos'] += cx; s.w('ax', cx); s.cf(0)
    def d41(s, ah, al, ds, dx, *a):
        p = s.norm(s.asciiz(ds, dx))
        if p not in s.fs: return s.err(2)
        del s.fs[p]; s.cf(0)
    def d42(s, ah, al, ds, dx, bx, cx):
        h = s.handles.get(bx)
        if not h: return s.err(6)
        off = (cx << 16) | dx
        if off & 0x80000000: off -= 1 << 32
        base = {0: 0, 1: h['pos'], 2: len(s.fs[h['p']])}.get(al)
        if base is None: return s.err(1)
        h['pos'] = max(0, base + off)
        s.w('ax', h['pos'] & 0xFFFF); s.w('dx', h['pos'] >> 16); s.cf(0)
    def d43(s, ah, al, ds, dx, *a):
        p = s.norm(s.asciiz(ds, dx))
        if p in s.fs: s.w('cx', 0x20); s.cf(0)
        elif s.isdir(p): s.w('cx', 0x10); s.cf(0)
        else: s.err(2)
    def d56(s, ah, al, ds, dx, *a):
        old = s.norm(s.asciiz(ds, dx)); new = s.norm(s.asciiz(s.r('es'), s.r('di')))
        if old not in s.fs: return s.err(2)
        if new in s.fs or s.isdir(new): return s.err(5)
        s.fs[new] = s.fs.pop(old); s.cf(0)
    def d57(s, ah, al, ds, dx, bx, cx):
        t, d = s.dos_dt()
        if al == 0: s.w('cx', t); s.w('dx', d)
        s.cf(0)
    def d4e(s, ah, al, ds, dx, bx, cx):
        p = s.norm(s.asciiz(ds, dx))
        d, _, pat = p.rpartition('\\'); d += '\\'
        if not s.isdir(d): return s.err(3)
        lst = [e for e in s.entries(d) if s.matches(pat, e[0]) and (e[1] != 0x10 or cx & 0x10)]
        if not lst: return s.err(2)
        st = {'list': lst, 'i': 0}; s.finds[s.dta] = st
        s.put_find(st); s.cf(0)
    def d4f(s, *a):
        st = s.finds.get(s.dta)
        if not st or st['i'] >= len(st['list']): return s.err(18)
        s.put_find(st); s.cf(0)
    def d50(s, ah, al, ds, dx, bx, cx): s.psp = bx
    def d51(s, *a): s.w('bx', s.psp)
    d62 = d51
    def d52(s, *a):
        """The "list of lists", for its first MCB (at BX-2): the chain is
        written from the blocks (each has a paragraph before it kept for its
        MCB) and the free gaps between them; the pointer just below them."""
        chain, pos = [], s.MEMBASE
        for seg, n, owner in sorted(s.blocks):
            if seg - 1 > pos: chain.append((pos, 0, seg - 2 - pos))
            chain.append((seg - 1, owner, n))
            pos = max(pos, seg + n)
        if s.MEMTOP > pos: chain.append((pos, 0, s.MEMTOP - pos - 1))
        for i, (m, owner, n) in enumerate(chain):
            s.wr(m, 0, (b'Z' if i == len(chain) - 1 else b'M') + struct.pack('<HH', owner, n))
        s.wr(s.MEMBASE - 1, 0, struct.pack('<H', s.MEMBASE))
        s.w('es', s.MEMBASE - 1); s.w('bx', 2)
    def d59(s, *a): s.w('ax', getattr(s, 'last_err', 0)); s.w('bx', 0x0101)
    def d29(s, *a): s.w('al', 0)

    # ---- memory -----------------------------------------------------------
    def gaps(s):
        pos = s.MEMBASE
        for seg, n, _ in sorted(s.blocks):
            if seg - 1 > pos: yield pos, seg - 1 - pos
            pos = max(pos, seg + n)
        if s.MEMTOP > pos: yield pos, s.MEMTOP - pos

    def alloc(s, paras, owner):
        best = 0
        for g, n in s.gaps():
            if n - 1 >= paras:
                seg = g + 1; s.blocks.append([seg, paras, owner]); return seg, 0
            best = max(best, n - 1)
        return None, best

    def block(s, seg):
        for b in s.blocks:
            if b[0] == seg: return b
        return None

    def room(s, seg):
        nxt = min([b[0] - 1 for b in s.blocks if b[0] > seg] + [s.MEMTOP])
        return nxt - seg

    def d48(s, ah, al, ds, dx, bx, cx):
        seg, best = s.alloc(bx, s.psp)
        if seg is None: s.w('bx', best); return s.err(8)
        s.w('ax', seg); s.cf(0)
    def d49(s, *a):
        b = s.block(s.r('es'))
        if not b: return s.err(9)
        s.blocks.remove(b); s.cf(0)
    def d4a(s, ah, al, ds, dx, bx, cx):
        b = s.block(s.r('es'))
        if not b: return s.err(9)
        m = s.room(b[0])
        if bx > m: s.w('bx', m); return s.err(8)
        b[1] = bx; s.cf(0)

    # ---- programs --------------------------------------------------------------
    def make_env(s, parent_env, prog):
        if parent_env:
            raw = s.rd(parent_env, 0, 1024); end = raw.find(b'\0\0')
            vars_ = raw[:end + 1]
        else:
            vars_ = b'COMSPEC=A:\\COMMAND.COM\0PATH=A:\\\0TEMP=A:\\\0'
        blob = vars_ + b'\0\x01\0' + prog.encode() + b'\0'
        seg, _ = s.alloc((len(blob) + 15) // 16, 0)
        s.wr(seg, 0, blob)
        return seg

    def load(s, path, tail, env):
        """Load a .COM or .EXE for execution; returns (psp, cs, ip, ss, sp)."""
        img = bytes(s.fs[path])
        _, best = s.alloc(0xFFFF, 0)
        psp, _ = s.alloc(best, 0)
        s.block(psp)[2] = psp
        for b in s.blocks:
            if b[0] == env: b[2] = psp
        top = psp + best
        s.wr(psp, 0, b'\xcd\x20' + struct.pack('<H', top) + bytes(0xFC))
        s.wr(psp, 0x2C, struct.pack('<H', env))
        s.wr(psp, 0x80, bytes([len(tail)]) + tail + b'\r')
        if img[:2] == b'MZ':
            last, pages, nrel, hdr, minx, maxx, ss, sp, ck, ip, cs, rel = struct.unpack('<12H', img[2:26])
            size = pages * 512 - (512 - last if last else 0) - hdr * 16
            load = psp + 0x10
            s.wr(load, 0, img[hdr * 16:hdr * 16 + size])
            for i in range(nrel):
                o, g = struct.unpack('<HH', img[rel + 4 * i:rel + 4 * i + 4])
                v = s.u16(load + g, o); s.wr(load + g, o, struct.pack('<H', (v + load) & 0xFFFF))
            return psp, load + cs, ip, load + ss, sp
        s.wr(psp, 0x100, img)
        s.wr(psp, 0xFFFE, b'\0\0')
        return psp, psp, 0x100, psp, 0xFFFE

    def start(s, path, args=''):
        """Run a top-level program (as if typed at the DOS prompt)."""
        path = s.norm(path)
        env = s.make_env(0, path)
        tail = (' ' + args if args else '').encode()
        psp, cs, ip, ss, sp = s.load(path, tail, env)
        s.psp = psp; s.dta = (psp, 0x80); s.ctx = [None]
        s.stopped = False; s.exit_code = None
        for n in ('ds', 'es'): s.w(n, psp)
        s.w('cs', cs); s.w('ip', ip); s.w('ss', ss); s.w('sp', sp)
        s.w('ax', 0); s.w('bx', 0); s.w('cx', 0xFF); s.w('dx', psp); s.w('flags', 0x202)
        return psp

    def d4b(s, ah, al, ds, dx, bx, cx):
        if al != 0: return s.err(1)
        path = s.norm(s.asciiz(ds, dx))
        es = s.r('es')
        envseg, toff, tseg = struct.unpack('<HHH', s.rd(es, bx, 6))
        if path not in s.fs: return s.err(2)
        n = s.rd(tseg, toff, 1)[0]; tail = s.rd(tseg, toff + 1, n)
        s.log.append('[EXEC %s%s]' % (path, tail.decode('cp437')))
        if path.endswith('\\COMMAND.COM'):
            s.last_exit = s.shell(tail.decode('cp437')); s.cf(0); return
        env = s.make_env(envseg or s.u16(s.psp, 0x2C), path)
        saved = {n: s.r(n) for n in ('cs', 'ip', 'ss', 'sp', 'flags', 'bp')}
        saved['psp'] = s.psp; saved['dta'] = s.dta
        psp, cs, ip, ss, sp = s.load(path, tail, env)
        s.ctx.append(saved)
        s.psp = psp; s.dta = (psp, 0x80)
        for n in ('ds', 'es'): s.w(n, psp)
        s.w('cs', cs); s.w('ip', ip); s.w('ss', ss); s.w('sp', sp)
        s.w('ax', 0); s.w('bx', 0); s.w('flags', 0x202)

    def d4c(s, ah, al, *a): s.terminate(al, tsr=False)
    def d31(s, ah, al, ds, dx, *a): s.terminate(al, tsr=True, keep=dx)
    def d4d(s, *a): s.w('ax', s.last_exit); s.cf(0)

    def terminate(s, code, tsr, keep=0):
        child = s.psp
        if tsr:
            b = s.block(child)
            if b: b[1] = keep
        else:
            s.blocks = [b for b in s.blocks if b[2] != child]
            for h in [h for h in s.handles]: pass
        s.last_exit = code | (0x300 if tsr else 0)
        ctx = s.ctx.pop() if s.ctx else None
        if ctx is None:
            s.stopped = True; s.exit_code = code; s.tsr = tsr; s.mu.emu_stop(); return
        s.psp = ctx['psp']; s.dta = ctx['dta']
        for n in ('cs', 'ip', 'ss', 'sp', 'bp'): s.w(n, ctx[n])
        s.w('flags', ctx['flags'] & ~1)
        for n in ('ax', 'bx', 'cx', 'dx', 'si', 'di'): s.w(n, 0x5A5A)   # DOS 3 keeps only CS:IP (+SS:SP)
        s.w('ds', 0x1234); s.w('es', 0x4321)

    def shell(s, line):
        """COMMAND.COM /C: the built-in commands Claude is likely to use."""
        t = line.strip()
        if t[:2].upper() == '/C': t = t[2:].strip()
        out = None; append = False
        if '>' in t:
            t, _, o = t.partition('>')
            if o.startswith('>'): append = True; o = o[1:]
            out = s.norm(o.strip())
        words = t.split(); cmd = words[0].upper() if words else ''
        arg = t[len(cmd):].strip()
        text = ''
        if cmd == 'DIR':
            p = s.norm(arg or '*.*')
            if s.isdir(p): p = p.rstrip('\\') + '\\*.*'
            d, _, pat = p.rpartition('\\'); d += '\\'
            ents = [e for e in s.entries(d) if s.matches(pat, e[0])]
            text = '\n Volume in drive %s has no label\n Directory of  %s\n\n' % (d[0], d.rstrip('\\') if len(d) > 3 else d)
            for nm, attr, size in ents:
                n, _, e = nm.partition('.')
                text += '%-8s %-3s %s  10-04-26   8:31p\n' % (n, e, '<DIR>    ' if attr == 0x10 else '%9d' % size)
            text += '%9d File(s)    307200 bytes free\n' % len(ents)
        elif cmd == 'VER': text = '\nMS-DOS Version 3.30\n\n'
        elif cmd == 'ECHO': text = arg + '\n'
        elif cmd == 'TYPE':
            p = s.norm(arg)
            text = s.fs[p].decode('cp437').replace('\r\n', '\n') if p in s.fs else 'File not found\n'
        else: text = 'Bad command or file name\n'
        data = text.replace('\n', '\r\n').encode('cp437')
        if out:
            if append: s.fs.setdefault(out, bytearray()).extend(data)
            else: s.fs[out] = bytearray(data)
        else:
            for c in data: s.tty_put(c)
        return 0

    # ---- running ----------------------------------------------------------------
    def lin(s): return (s.r('cs') * 16 + s.r('ip')) & 0xFFFFF

    def run(s, n=40000):
        if s.stopped or s.crash: return False
        s.blocked = False
        try:
            s.mu.emu_start(s.lin(), 0xFFFFFFFF, count=n)
        except UcError as e:
            s.crash = 'CPU %s at %04X:%04X' % (e, s.r('cs'), s.r('ip')); return False
        a, z = s.last_blk
        here = s.lin()
        s.halted = a + z == here and s.rd(0, here - 1, 1)[0] == 0xF4
        if s.blocked or s.halted:
            s.sleep_to_tick()                    # HLT, or waiting for a key
        return not (s.stopped or s.crash)

    def run_program(s, path, args='', limit_us=30e6):
        s.start(path, args)
        end = s.us + limit_us
        while s.run() and s.us < end: pass
        return ''.join(s.tty)

    # ---- the screen ----------------------------------------------------------------
    def mode(s): return s.rd(0, 0x449, 1)[0]

    def png(s, path, scale=2):
        from PIL import Image
        if s.mode() == 0x40:
            vram = s.rd(0xB800, 0, 0x8000)
            im = Image.new('RGB', (640, 400))
            px = im.load()
            for y in range(400):
                base = (y & 3) * 0x2000 + (y >> 2) * 80
                for xb in range(80):
                    v = vram[base + xb]
                    for b in range(8):
                        px[xb * 8 + b, y] = (255, 170, 50) if v & (0x80 >> b) else (28, 12, 0)
            im = im.resize((640 * scale // 2 * 2, 400 * scale // 2 * 2), Image.NEAREST)
        else:
            from PIL import ImageDraw
            im = Image.new('RGB', (640, 400), (28, 12, 0)); d = ImageDraw.Draw(im)
            for i, line in enumerate(s.text_screen().split('\n')):
                d.text((0, i * 16), line, fill=(255, 170, 50))
        im.save(path)

    def text_screen(s):
        v = s.rd(0xB800, 0, 4000)
        return '\n'.join(''.join(chr(v[(r * 80 + c) * 2]) if 32 <= v[(r * 80 + c) * 2] < 127 else ' '
                                 for c in range(80)).rstrip() for r in range(25))


class Font:
    """Reads CLAUDE's own font out of its image, to turn the mode 40h screen
    back into text (cells are 8x16; inverse = all bits flipped)."""
    def __init__(s, image, font_off):
        s.map = {}; s.ul = {}
        for i in range(0x81):
            g = image[font_off + i * 16:font_off + i * 16 + 16]
            ch = chr(0x20 + i) if 0x20 + i < 0x7F else GLYPH_NAMES.get(0x20 + i, '?')
            inv = bytes(b ^ 0xFF for b in g)
            s.map.setdefault(g, (ch, False))
            if g != b'\xff' * 16: s.map.setdefault(inv, (ch, True))
            s.ul.setdefault(g[:14] + b'\xff' + g[15:], (ch, False))     # underlined
            s.ul.setdefault(inv[:14] + b'\x00' + inv[15:], (ch, True))
        s.map[b'\xff' * 16] = (' ', True)          # an inverse space, not a block

    def read(s, vram, row, col):
        g = bytes(vram[(r & 3) * 0x2000 + (row * 4 + (r >> 2)) * 80 + col] for r in range(16))
        return s.map.get(g) or s.ul.get(g) or ('\u00bf', False)

    def screen(s, vram, marks=False):
        lines = []
        for row in range(25):
            line = ''
            for col in range(80):
                ch, inv = s.read(vram, row, col)
                line += ch
            lines.append(line.rstrip())
        return '\n'.join(lines)


def symbols(mapfile):
    """A NASM map's symbols: Real, Virtual, Name lines -> {name: virtual}
    (the same but for a section with vstart, like CLAUDE.COM's resident
    stub, whose labels count from 100h in its own block)."""
    syms = {}
    for line in open(mapfile):
        p = line.split()
        if len(p) == 3:
            try: syms[p[2]] = int(p[1], 16)
            except ValueError: pass
    return syms


class EmuHarness:
    """Real CLAUDE.COM <-> real GRIDGPIB <-> 7210 + bus <-> AR488 model <->
    real gridlink (Link + Session) <-> scripted Claude."""
    def __init__(s, script=None, patched=True, files=None, mode='ask', answer='y', args='/A:7',
                 claude_com=CLAUDE_COM, mapfile=None, baud=115200, term=None, web=None):
        s.m = m = Machine()
        s.pending = []
        s.nano = AR488Model(m.clock, addr=7, patched=patched, to_pi=s._to_pi, baud=baud)
        m.chip.devices[7] = s.nano
        m.on_due = s.pump_pi
        s.transport = ModelTransport(s.nano, patched, baud=baud)
        s.tmp = tempfile.mkdtemp(prefix='gridemu-')
        cfg = Config()
        cfg.workdir = os.path.join(s.tmp, 'work'); cfg.memory_dir = os.path.join(s.tmp, 'mem')
        cfg.sessions_dir = os.path.join(s.tmp, 'sessions'); cfg.mode = mode; cfg.web = False
        s.cfg = cfg
        s.client = FakeAnthropic(script or [])
        s.log = []
        if term:
            # Term: gridlink's router and a program in a pty (no API key)
            cfg.term_dir = os.path.join(s.tmp, 'grid'); cfg.term_command = term
            if web: cfg.web_command = web; cfg.web_dir = os.path.join(s.tmp, 'web')
            cfg.term_socket = os.path.join(s.tmp, 'gridlink.sock')
            cfg.api_key = None; cfg.env_key = lambda: False; cfg.app = 'auto'
            s.router = Router(cfg, log=s.log.append)
            s.link = Link(s.transport, s.router.on_message, log=s.log.append, hold=0.0)
            s.router.attach(s.link)
            s.session = None
        else:
            s.router = None
            s.session = Session(cfg, s.client, log=s.log.append)
            s.link = Link(s.transport, s.session.on_message, log=s.log.append, hold=0.0)
            s.session.attach(s.link)
            threading.Thread(target=s.session.run, daemon=True).start()
        img = open(claude_com, 'rb').read()
        m.fs['A:\\CLAUDE.COM'] = bytearray(img)
        m.fs['A:\\GRIDGPIB.COM'] = bytearray(open(GRIDGPIB_COM, 'rb').read())
        if os.path.exists(TESTKEY_COM): m.fs['A:\\TESTKEY.COM'] = bytearray(open(TESTKEY_COM, 'rb').read())
        m.fs['A:\\COMMAND.COM'] = bytearray(b'\xcd\x20' + bytes(100))
        for k, v in (files or {}).items(): m.fs[m.norm(k)] = bytearray(v)
        s.sym = symbols(mapfile or os.path.splitext(claude_com)[0] + '.MAP')
        s.font = Font(img, s.sym['font'] - 0x100)
        s.font_img = img[s.sym['font'] - 0x100:s.sym['font'] - 0x100 + 0x81 * 16]
        s.answer = answer
        s.args = args
        s.shots = []

    # Pi side plumbing
    def _to_pi(s, data, t):
        s.pending.append((t, data)); s.m.schedule(t)

    def pump_pi(s):
        now = s.m.us
        ready = sorted([p for p in s.pending if p[0] <= now], key=lambda p: p[0])
        s.pending = [p for p in s.pending if p[0] > now]
        for t, data in ready: s.link.feed(data)
        if s.pending: s.m.schedule(min(p[0] for p in s.pending))

    # CLAUDE's variables
    def var(s, name, size=1):
        a = s.claude_psp * 16 + s.sym[name]
        return int.from_bytes(s.m.mu.mem_read(a, size), 'little')

    def boot(s):
        out = s.m.run_program('A:\\GRIDGPIB.COM', limit_us=5e6)
        assert s.m.tsr and s.m.exit_code == 0, (out, s.m.log, s.m.crash)
        s.gridgpib_out = out
        s.m.tty = []
        s.claude_psp = s.m.start('A:\\CLAUDE.COM', s.args)
        return out

    def run_until(s, cond, sim_s=10.0, wall=60.0):
        end = s.m.us + sim_s * 1e6; wend = time.time() + wall
        while s.m.us < end and time.time() < wend:
            if cond(): return True
            if not s.m.run(): break
        return cond()

    def idle(s):
        """Connected, nothing in flight, and CLAUDE asleep in its idle loop
        (so it is not in the middle of something)."""
        return (s.m.halted and s.var('connected') and not s.var('busy') and not s.link.busy()
                and s.var('lstate') == 1 and not s.var('txq_n') and not s.var('req_ready'))

    def connect(s, sim_s=10.0):
        return s.run_until(s.idle, sim_s)

    def type(s, text, enter=True):
        for ch in text:
            s.m.keys.append(SCAN.get(ch, 0) << 8 | ord(ch))
        if enter: s.m.keys.append(0x1C0D)
        s.m.halted = False

    def key(s, ax):
        s.m.keys.append(ax); s.m.halted = False

    def turn(s, text, sim_s=60.0, on_ask=None):
        s.type(text)
        s.run_until(lambda: s.var('busy') or s.m.crash, 5.0)
        def done():
            if s.var('ask_open') and not s.m.keys:
                s.settle()
                if on_ask: on_ask(s)
                else: s.m.keys.append(ord(s.answer))
            return s.idle()
        return s.run_until(done, sim_s)

    def screen(s):
        if s.m.mode() != 0x40: return s.m.text_screen()
        return s.font.screen(s.m.rd(0xB800, 0, 0x8000))

    def settle(s, busy_ms=80):
        """Let CLAUDE finish what it is doing: run on until it halts in its
        idle loop (it never does while Claude is working: then just a while)."""
        t = s.m.us
        s.m.halted = False
        if s.var('busy') or s.var('ask_open'):
            s.run_until(lambda: s.m.us > t + busy_ms * 1000, 1.0)
        else:
            s.run_until(lambda: s.m.halted, 5.0)

    # ---- Term -----------------------------------------------------------
    def term_cells(s):
        """The GRiD's shadow of the Term screen: 24 rows of (glyphs, attributes)."""
        seg = s.var('shadseg', 2)
        raw = s.m.mu.mem_read(seg * 16, 24 * 160)
        return ([bytes(raw[r * 160:(r + 1) * 160:2]) for r in range(24)],
                [bytes(raw[r * 160 + 1:(r + 1) * 160:2]) for r in range(24)])

    def term_vram_ok(s, chs, ats, cursor=None):
        """Video memory rows 0-23 are exactly these cells drawn with CLAUDE's
        font (and the cursor, if shown).  Returns a list of bad cells."""
        v = s.m.rd(0xB800, 0, 0x8000)
        bad = []
        for r in range(24):
            for c in range(80):
                g = chs[r][c]; a = ats[r][c]
                g = 0x20 if g < 0x20 else ('?' if g > 0xA0 else g)
                g = ord(g) if isinstance(g, str) else g
                want = bytearray(s.font_img[(g - 0x20) * 16:(g - 0x1F) * 16])
                if a & 1: want = bytearray(b ^ 0xFF for b in want)
                if a & 2: want[14] = 0x00 if a & 1 else 0xFF
                if cursor and cursor == (r, c):
                    want[14] ^= 0xFF; want[15] ^= 0xFF
                got = bytes(v[(i & 3) * 0x2000 + (r * 4 + (i >> 2)) * 80 + c] for i in range(16))
                if got != bytes(want): bad.append((r, c))
        return bad

    def press(s, ax):
        s.m.keys.append(ax); s.m.halted = False

    def term_type(s, text):
        for ch in text: s.press(SCAN.get(ch, 0) << 8 | ord(ch))

    def close(s):
        if s.router is not None and s.router.term is not None: s.router.term.stop()
        if s.router is not None and getattr(s.router, 'web', None) is not None: s.router.web.stop()

    def shot(s, path):
        s.settle()
        s.m.png(path); s.shots.append(path)
        with open(os.path.splitext(path)[0] + '.txt', 'w', encoding='utf-8') as f: f.write(s.screen() + '\n')


SCAN = {}
for row, sc in (('1234567890-=', 2), ('qwertyuiop[]', 0x10), ("asdfghjkl;'`", 0x1E), ('\\zxcvbnm,./', 0x2B)):
    for i, ch in enumerate(row): SCAN[ch] = sc + i
for k, v in list(SCAN.items()):
    if k.isalpha(): SCAN[k.upper()] = v
SCAN[' '] = 0x39
for a, b in zip('!@#$%^&*()_+', '1234567890-='): SCAN[a] = SCAN[b]
for a, b in zip('{}:"~|<>?', "[];'`\\,./"): SCAN[a] = SCAN[b]
