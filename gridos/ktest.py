"""Test harness for the Grid-OS 0.2 kernel: boot an image in pcemu, drive
the Executive with keys, read its screen back (OCR of the 640x400 mode)
and trace INT 21h calls.

    k = KPC('k02.img'); k.start()
    k.key(DOWN, ENTER); k.settle()
    print(k.ocr())
"""
import os, re, bisect, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pcemu

ENTER, ESC, UP, DOWN, LEFT, RIGHT = 0x1C0D, 0x011B, 0x4800, 0x5000, 0x4B00, 0x4D00
TAB, BKSP, F1, CODE_C = 0x0F09, 0x0E08, 0x3B00, 0x2E00


class Syms:
    def __init__(s, path=os.path.join(HERE, 'src', 'GRIDOS.MAP')):
        s.by_name, s.by_addr, sec = {}, {}, None
        for line in open(path):
            if line.startswith('---- Section'): sec = line
            m = re.match(r"\s*([0-9A-F]+)\s+([0-9A-F]+)\s+(\S+)\s*$", line)
            if m and sec:
                a = int(m.group(2), 16); s.by_name[m.group(3)] = a
                if '.' not in m.group(3) or a not in s.by_addr: s.by_addr.setdefault(a, m.group(3))
        s.addrs = sorted(s.by_addr)
    def __getitem__(s, n): return s.by_name[n]
    def name(s, off):
        i = bisect.bisect_right(s.addrs, off) - 1
        return hex(off) if i < 0 else '%s+%x' % (s.by_addr[s.addrs[i]], off - s.addrs[i])


_font = None
def font():
    global _font
    if _font is None:
        f = pcemu.load_font(os.path.join(HERE, 'src', 'FONT.INC'))
        _font = {}
        for c, g in f.items():
            if not 33 <= c <= 126 or not any(g): continue
            _font.setdefault(bytes(g), chr(c))
            _font.setdefault(bytes(b ^ 0xFF for b in g), chr(c))
    return _font


class KPC:
    def __init__(s, img, b=None, chip=None, trace=False, **kw):
        s.pc = pcemu.PC(img, b, chip, **kw)
        s.Y = Syms()
        s.dos = []          # (function, args, result) of traced INT 21h calls
        s.pending = {}
        s.trace = trace
        s.hooks = []
        s.pc.watch = s._watch

    # ---- INT 21h trace ----------------------------------------------------
    def _watch(s, addr):
        pc = s.pc
        for h in s.hooks: h(pc)
        if not s.trace: return
        cs, ip = pc.r('cs'), pc.r('ip')
        if cs == 0x60 and ip == s.Y['int21']:
            ss, sp = pc.r('ss'), pc.r('sp')
            ret = (pc.u16(ss, sp + 2) * 16 + pc.u16(ss, sp)) & 0xFFFFF
            ax = pc.r('ax')
            if (ax >> 8) in (0x0B, 0x2C, 0x06, 0x0E, 0x19): return
            arg = ''
            if (ax >> 8) in (0x39, 0x3A, 0x3B, 0x3C, 0x3D, 0x41, 0x43, 0x4B, 0x4E, 0x5B, 0x56):
                arg = pc.asciiz(pc.r('ds'), pc.r('dx')).decode('latin-1')
            s.pending[ret] = (ax, pc.r('bx'), pc.r('cx'), pc.r('dx'), arg)
            return
        lin = (cs * 16 + ip) & 0xFFFFF
        if lin in s.pending:
            ax, bx, cx, dx, arg = s.pending.pop(lin)
            fl = pc.r('flags')
            s.dos.append((ax >> 8, ax, bx, cx, dx, arg, pc.r('ax'), fl & 1))

    def dos_log(s):
        return ['AH=%02X ax %04X bx %04X cx %04X dx %04X %s -> ax %04X%s' % (
            f, ax, bx, cx, dx, arg, rax, ' CF' if cf else '') for f, ax, bx, cx, dx, arg, rax, cf in s.dos]

    # ---- running ----------------------------------------------------------
    def start(s, sim_s=6.0):
        s.pc.boot(0)
        return s.settle(sim_s)

    def waiting(s):
        """Waiting for a key (INT 16h blocked) or halted in an idle loop."""
        return s.pc.blocked or s.pc.halted

    def settle(s, sim_s=6.0):
        """Run until the machine waits for input and the key queue is empty."""
        pc = s.pc
        end = pc.us + sim_s * 1e6
        quiet = 0
        while pc.us < end:
            if not pc.run(): break
            if s.waiting() and not pc.keys:
                quiet += 1
                if quiet >= 3: return True
            else:
                quiet = 0
        return False

    def key(s, *keys, settle=True):
        for k in keys:
            if isinstance(k, str):
                for ch in k: s.pc.keys.append(ord(ch))
            else:
                s.pc.keys.append(k)
            if settle: s.settle()

    def run_for(s, sim_s): s.pc.run_for(sim_s)

    @property
    def crashed(s): return s.pc.crash or s.pc.stopped

    def where(s):
        cs, ip = s.pc.r('cs'), s.pc.r('ip')
        return '%04X:%04X %s' % (cs, ip, s.Y.name(ip) if cs == 0x60 else '')

    # ---- screen -----------------------------------------------------------
    def ocr(s):
        """Text of the 640x400 screen: list of (y, line) for every pixel row
        where a glyph starts (columns on 8-pixel boundaries)."""
        pc = s.pc
        if pc.mode() not in (0x40, 0x48):
            return [(r * 16, l) for r, l in enumerate(pc.text_screen().split('\n'))]
        v = pc.rd(0xB800, 0, 0x8000)
        rows = [bytes(v[(y & 3) * 0x2000 + (y >> 2) * 80:(y & 3) * 0x2000 + (y >> 2) * 80 + 80]) for y in range(400)]
        F = font()
        hits = {}
        for y in range(0, 400 - 15):
            for x in range(80):
                k = bytes(rows[y + i][x] for i in range(16))
                c = F.get(k)
                if c: hits.setdefault(y, {})[x] = c
        out = []
        for y in sorted(hits):
            line = hits[y]
            if len(line) < 1: continue
            out.append((y, ''.join(line.get(x, ' ') for x in range(80)).rstrip()))
        return out

    def text(s):
        return '\n'.join(l for y, l in s.ocr())

    def shot(s, path):
        s.pc.png(path, pcemu.load_font(os.path.join(HERE, 'src', 'FONT.INC')))
        return path

    # ---- block trace ------------------------------------------------------
    def btrace(s, start, n=200, skip=()):
        """Record kernel blocks from the next time `start` is reached."""
        rec = {'on': False, 'out': []}
        a = s.Y[start]
        def h(pc):
            cs, ip = pc.r('cs'), pc.r('ip')
            if cs == 0x60 and ip == a: rec['on'] = True
            if rec['on'] and len(rec['out']) < n:
                nm = s.Y.name(ip) if cs == 0x60 else ''
                if any(nm.startswith(k) for k in skip): return
                rec['out'].append('%04X:%04X %-26s ax %04X bx %04X cx %04X dx %04X si %04X di %04X ds %04X es %04X ss %04X sp %04X' % (
                    cs, ip, nm, *(pc.r(r) for r in ('ax', 'bx', 'cx', 'dx', 'si', 'di', 'ds', 'es', 'ss', 'sp'))))
        s.hooks.append(h)
        return rec['out']

    # ---- the Executive ----------------------------------------------------
    def exec_list(s):
        """Names in the Executive's list, in display order."""
        pc, Y = s.pc, s.Y
        n = pc.u16(0x60, Y['nent'])
        out = []
        for i in range(n):
            p = pc.u16(0x60, Y['entlist'] + 2 * i)
            e = pc.rd(0x60, p, 11).decode('latin-1')
            nm, ext = e[:8].rstrip(), e[8:].rstrip()
            out.append(nm + ('.' + ext if ext else ''))
        return out

    def select(s, name):
        lst = s.exec_list()
        i = lst.index(name.upper())
        sel = s.pc.u16(0x60, s.Y['sel'])
        while sel < i: s.key(DOWN, settle=False); sel += 1
        while sel > i: s.key(UP, settle=False); sel -= 1
        s.settle()

    def run_file(s, name, sim_s=60.0):
        """Select a program, confirm, and run until the Executive is back."""
        s.select(name)
        s.pc.tty.clear() if isinstance(s.pc.tty, list) else None
        s.key(ENTER, settle=False)
        s.pc.run_until(lambda: s.pc.mode() != 0x40, 5)
        run_answering(s.pc, lambda: s.pc.mode() == 0x40, sim_s)
        s.settle()
        return ''.join(s.pc.tty) if isinstance(s.pc.tty, list) else s.pc.tty

    def band(s):
        """The prompt band's text (messages after a program ends)."""
        return [l.strip() for y, l in s.ocr() if y >= 360]


def run_answering(pc, done, sim_s):
    """Run until done(), pressing Enter whenever a program says "Press any
    key" (BENCH and CACHETST wait so their results can be read)."""
    tty = lambda: ''.join(pc.tty) if isinstance(pc.tty, list) else pc.tty
    seen = tty().count('Press any key')
    t_end = pc.us + sim_s * 1e6
    while True:
        us0 = pc.us
        pc.run_until(lambda: done() or pc.crash or tty().count('Press any key') > seen,
                     max(0.0, (t_end - pc.us) / 1e6))
        if done() or pc.crash or pc.us >= t_end: return
        if tty().count('Press any key') <= seen and pc.us == us0: return   # (stopped)
        seen = tty().count('Press any key')
        pc.keys.append(0x1C0D)
