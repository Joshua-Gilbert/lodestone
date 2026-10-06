# Instrumented DOS/BIOS emulator: runs GRIDGPIB.COM then TM5000G.EXE and logs
# every software interrupt (INT n / AH / AL) the program makes.
import struct, sys, collections
from unicorn import *
from unicorn.x86_const import *
import sim7210 as S, dosemu as D

class Tracer(D.Machine):
    def setup(s, keys):
        s.keys = list(keys); s.log = collections.Counter(); s.order = []
        s.cur = [0, 0]; s.mode = 3; s.files = {}; s.fh = {}; s.nexth = 5
        s.memtop = 0xA000; s.blocks = {}; s.screens = []; s.last_hook = None
        s.mouse = [320, 100, 0]; s.dta = 0; s.hooked = set(); s.tracking = False
        mu = s.mu
        mu.mem_write(0x410, struct.pack('<H', 0x4423))   # equipment word (as the 1520)
        mu.mem_write(0x413, struct.pack('<H', 640))
        mu.mem_write(0x449, bytes([3])); mu.mem_write(0x44A, struct.pack('<H', 80))
        mu.mem_write(0x463, struct.pack('<H', 0x3D4)); mu.mem_write(0x408, struct.pack('<H', 0x378))
        mu.mem_write(0x400, struct.pack('<HH', 0x3F8, 0x2F8))
        # IRET stubs for unhooked vectors live at F000:FF53 like the real BIOS
        mu.mem_write(0xFFF53, b'\xcf')
    def note(s, key):
        if key not in s.log: s.order.append(key)
        s.log[key] += 1
    def tty(s, ch):
        r, c = s.cur
        if ch == '\r': c = 0
        elif ch == '\n': r += 1
        elif ch == '\b': c = max(0, c - 1)
        elif ch == '\x07': pass
        else:
            if s.mode <= 3: s.mu.mem_write(0xB8000 + (r * 80 + c) * 2, bytes([ord(ch) & 0xFF, 7]))
            c += 1
            if c >= 80: c = 0; r += 1
        if r >= 25:
            if s.mode <= 3:
                buf = bytes(s.mu.mem_read(0xB8000 + 160, 160 * 24)); s.mu.mem_write(0xB8000, buf + b' \x07' * 80)
            r = 24
        s.cur = [r, c]
    def screen(s):
        t = bytes(s.mu.mem_read(0xB8000, 4000))
        return '\n'.join(''.join(chr(t[(r * 80 + c) * 2]) if 32 <= t[(r * 80 + c) * 2] < 127 else ' ' for c in range(80)).rstrip() for r in range(25))
    def intr(s, uc, n, ud):
        R = s.R; W = s.W
        ah = R(UC_X86_REG_AH); al = R(UC_X86_REG_AL)
        if 0x60 <= n <= 0x66 or n in s.hooked:
            s.note(('INT %02Xh' % n, 'AH=%02X' % ah if n < 0x34 or n > 0x3E else '(FP emu)', ''))
            seg, off = s.ivt(n)
            if seg == 0 and off == 0: s.out.append('[INT %02X to null]' % n); uc.emu_stop(); return
            sp = R(UC_X86_REG_SP); ss = R(UC_X86_REG_SS)
            for v in (R(UC_X86_REG_FLAGS), R(UC_X86_REG_CS), R(UC_X86_REG_IP)):
                sp = (sp - 2) & 0xFFFF; uc.mem_write(ss * 16 + sp, struct.pack('<H', v))
            W(UC_X86_REG_SP, sp); W(UC_X86_REG_FLAGS, R(UC_X86_REG_FLAGS) & ~0x200)
            W(UC_X86_REG_CS, seg); W(UC_X86_REG_IP, off); return
        key = ('INT %02Xh' % n, 'AH=%02X' % ah, 'AL=%02X' % al if n in (0x21, 0x10, 0x15, 0x2F, 0x16) and ah in (0x44, 0x42, 0x43, 0x57, 0x0B, 0x00, 0x12, 0x10, 0x4B, 0x1A) else '')
        if n == 0x33: key = ('INT 33h', 'AX=%04X' % R(UC_X86_REG_AX), '')
        s.note(key)
        cf = s.cf
        if n == 0x10:
            if ah == 0x00:
                s.mode = al & 0x7F; uc.mem_write(0x449, bytes([s.mode]))
                if s.mode <= 3: uc.mem_write(0xB8000, b' \x07' * 2000)
            elif ah == 0x0F: W(UC_X86_REG_AX, (80 << 8) | s.mode); W(UC_X86_REG_BX, 0)
            elif ah == 0x02: s.cur = [R(UC_X86_REG_DH), R(UC_X86_REG_DL)]
            elif ah == 0x03: W(UC_X86_REG_DX, (s.cur[0] << 8) | s.cur[1]); W(UC_X86_REG_CX, 0x0607)
            elif ah in (0x09, 0x0A):
                r, c = s.cur
                for i in range(R(UC_X86_REG_CX)):
                    if s.mode <= 3 and r * 80 + c + i < 2000: uc.mem_write(0xB8000 + (r * 80 + c + i) * 2, bytes([al, 7]))
            elif ah == 0x0E: s.tty(chr(al))
            elif ah in (0x06, 0x07) and al == 0 and s.mode <= 3:
                r0, c0, r1, c1 = R(UC_X86_REG_CH), R(UC_X86_REG_CL), R(UC_X86_REG_DH), R(UC_X86_REG_DL)
                for r in range(r0, min(r1, 24) + 1):
                    for c in range(c0, min(c1, 79) + 1): uc.mem_write(0xB8000 + (r * 80 + c) * 2, b' \x07')
            elif ah == 0x08: W(UC_X86_REG_AX, 0x0720)
            return
        if n == 0x16:
            if ah in (0x00, 0x10):
                if not s.keys: s.screens.append(s.screen()); uc.emu_stop(); return
                k = s.keys.pop(0); s.screens.append(s.screen()); W(UC_X86_REG_AX, k)
            elif ah in (0x01, 0x11):
                f = R(UC_X86_REG_FLAGS)
                if s.keys: W(UC_X86_REG_FLAGS, f & ~0x40); W(UC_X86_REG_AX, s.keys[0])
                else:
                    s.idle = getattr(s, 'idle', 0) + 1
                    if s.idle > 20000: s.screens.append(s.screen()); uc.emu_stop()
                    W(UC_X86_REG_FLAGS, f | 0x40)
            elif ah in (0x02, 0x12): W(UC_X86_REG_AX, 0)
            return
        if n == 0x33:
            ax = R(UC_X86_REG_AX)
            if ax == 0: W(UC_X86_REG_AX, 0xFFFF); W(UC_X86_REG_BX, 2)
            elif ax == 3: W(UC_X86_REG_BX, 0); W(UC_X86_REG_CX, s.mouse[0]); W(UC_X86_REG_DX, s.mouse[1])
            return
        if n == 0x1A:
            if ah == 0:
                t = struct.unpack('<H', bytes(uc.mem_read(0x46C, 2)))[0]; W(UC_X86_REG_CX, 0); W(UC_X86_REG_DX, t); W(UC_X86_REG_AL, 0)
            return
        if n == 0x17: W(UC_X86_REG_AH, 0x90); return
        if n == 0x11: W(UC_X86_REG_AX, 0x4423); return
        if n == 0x12: W(UC_X86_REG_AX, 640); return
        if n == 0x15: cf(1); W(UC_X86_REG_AH, 0x86); return
        if n == 0x2F: W(UC_X86_REG_AL, 0); return
        if n == 0x28: return
        if n == 0x21: return s.dos(uc, ah, al)
        s.out.append('[unhandled INT %02X AH=%02X]' % (n, ah)); uc.emu_stop()
    def dos(s, uc, ah, al):
        R = s.R; W = s.W; cf = s.cf
        ds, dx, bx, cx = R(UC_X86_REG_DS), R(UC_X86_REG_DX), R(UC_X86_REG_BX), R(UC_X86_REG_CX)
        sz = lambda p: bytes(uc.mem_read(p, 80)).split(b'\0')[0].decode('latin1')
        if ah == 0x40:
            data = bytes(uc.mem_read(ds * 16 + dx, cx))
            if bx in (1, 2):
                for ch in data.decode('latin1'): s.tty(ch)
            elif bx in s.fh: s.files[s.fh[bx][0]] += data
            W(UC_X86_REG_AX, cx); cf(0)
        elif ah == 0x3F:
            if bx == 0:
                if not getattr(s, 'linebuf', b''):
                    if not s.keys: s.screens.append(s.screen()); uc.emu_stop(); return
                    s.screens.append(s.screen()); line = b''
                    while s.keys:
                        k = s.keys.pop(0) & 0xFF
                        if k == 0x0D: break
                        line += bytes([k])
                    for ch in line.decode('latin1') + '\r\n': s.tty(ch)
                    s.linebuf = line + b'\r\n'
                d = s.linebuf[:cx]; s.linebuf = s.linebuf[cx:]
                uc.mem_write(ds * 16 + dx, d); W(UC_X86_REG_AX, len(d))
            elif bx in s.fh:
                nm, pos = s.fh[bx]; d = s.files[nm][pos:pos + cx]; uc.mem_write(ds * 16 + dx, d); s.fh[bx][1] += len(d); W(UC_X86_REG_AX, len(d))
            else: W(UC_X86_REG_AX, 0)
            cf(0)
        elif ah in (0x3C, 0x5B):
            nm = sz(ds * 16 + dx).upper(); s.files[nm] = b''; h = s.nexth; s.nexth += 1; s.fh[h] = [nm, 0]; W(UC_X86_REG_AX, h); cf(0)
        elif ah == 0x3D:
            nm = sz(ds * 16 + dx).upper()
            if nm in s.files: h = s.nexth; s.nexth += 1; s.fh[h] = [nm, 0]; W(UC_X86_REG_AX, h); cf(0)
            else: W(UC_X86_REG_AX, 2); cf(1)
        elif ah == 0x3E: s.fh.pop(bx, None); cf(0)
        elif ah == 0x42:
            off = (cx << 16) | dx
            if bx in s.fh:
                nm, pos = s.fh[bx]; base = [0, pos, len(s.files[nm])][al]; s.fh[bx][1] = base + off; p = s.fh[bx][1]
            else: p = 0
            W(UC_X86_REG_AX, p & 0xFFFF); W(UC_X86_REG_DX, p >> 16); cf(0)
        elif ah == 0x44:
            if al == 0: W(UC_X86_REG_DX, 0x80 | 0x03 if bx < 3 else 0x0); cf(0)
            else: W(UC_X86_REG_AX, 0); cf(0)
        elif ah == 0x30: W(UC_X86_REG_AX, 0x1E03); W(UC_X86_REG_BX, 0); W(UC_X86_REG_CX, 0); cf(0)
        elif ah == 0x4A:
            seg = R(UC_X86_REG_ES); s.blocks[seg] = bx; cf(0)
        elif ah == 0x48:
            top = max([g + n for g, n in s.blocks.items()] or [0x2000])
            avail = s.memtop - top - 1
            if bx > avail: W(UC_X86_REG_AX, 8); W(UC_X86_REG_BX, max(avail, 0)); cf(1)
            else: s.blocks[top + 1] = bx; W(UC_X86_REG_AX, top + 1); cf(0)
        elif ah == 0x49: s.blocks.pop(R(UC_X86_REG_ES), None); cf(0)
        elif ah == 0x35:
            g, o = s.ivt(al); W(UC_X86_REG_ES, g); W(UC_X86_REG_BX, o)
        elif ah == 0x25:
            uc.mem_write(al * 4, struct.pack('<HH', dx, ds))
            if s.tracking and al not in (0x21, 0x10, 0x16, 0x33): s.hooked.add(al)
        elif ah == 0x31: s.tsr = (R(UC_X86_REG_CS), dx); uc.emu_stop()
        elif ah == 0x4C: s.exitcode = al; uc.emu_stop()
        elif ah == 0x62 or ah == 0x51: W(UC_X86_REG_BX, s.curseg)
        elif ah == 0x2A: W(UC_X86_REG_CX, 2026); W(UC_X86_REG_DX, 0x0A04); W(UC_X86_REG_AL, 0)
        elif ah == 0x2C:
            t = struct.unpack('<H', bytes(uc.mem_read(0x46C, 2)))[0]; W(UC_X86_REG_CX, 0x1000 + (t // 1092)); W(UC_X86_REG_DX, (t % 18) << 8)
        elif ah == 0x1A: s.dta = ds * 16 + dx
        elif ah == 0x2F: W(UC_X86_REG_ES, s.curseg); W(UC_X86_REG_BX, 0x80)
        elif ah == 0x19: W(UC_X86_REG_AL, 0)
        elif ah == 0x0E: W(UC_X86_REG_AL, 2)
        elif ah == 0x47: uc.mem_write(R(UC_X86_REG_DS) * 16 + R(UC_X86_REG_SI), b'\0'); cf(0)
        elif ah == 0x3B: cf(0)
        elif ah == 0x36: W(UC_X86_REG_AX, 1); W(UC_X86_REG_BX, 1000); W(UC_X86_REG_CX, 512); W(UC_X86_REG_DX, 2847)
        elif ah in (0x4E, 0x4F): W(UC_X86_REG_AX, 18); cf(1)
        elif ah == 0x43: W(UC_X86_REG_AX, 2); cf(1)
        elif ah == 0x41: cf(0)
        elif ah == 0x56: cf(0)
        elif ah == 0x33: W(UC_X86_REG_DL, 0)
        elif ah == 0x06:
            if R(UC_X86_REG_DL) != 0xFF: s.tty(chr(R(UC_X86_REG_DL)))
            elif s.keys: W(UC_X86_REG_AL, s.keys.pop(0) & 0xFF); W(UC_X86_REG_FLAGS, R(UC_X86_REG_FLAGS) & ~0x40)
            else: W(UC_X86_REG_AL, 0); W(UC_X86_REG_FLAGS, R(UC_X86_REG_FLAGS) | 0x40)
        elif ah in (0x02,): s.tty(chr(R(UC_X86_REG_DL)))
        elif ah in (0x07, 0x08, 0x01):
            if not s.keys: s.screens.append(s.screen()); uc.emu_stop(); return
            s.screens.append(s.screen()); W(UC_X86_REG_AL, s.keys.pop(0) & 0xFF)
        elif ah == 0x0B:
            W(UC_X86_REG_AL, 0xFF if s.keys else 0)
            if not s.keys:
                s.idle = getattr(s, 'idle', 0) + 1
                if s.idle > 3000: s.screens.append(s.screen()); uc.emu_stop()
        elif ah == 0x09:
            p = ds * 16 + dx
            while uc.mem_read(p, 1)[0] != 0x24: s.tty(chr(uc.mem_read(p, 1)[0])); p += 1
        elif ah in (0x57, 0x45, 0x46, 0x68, 0x0D, 0x29, 0x63, 0x58, 0x38, 0x37): cf(0); W(UC_X86_REG_AX, 0) if ah != 0x45 else W(UC_X86_REG_AX, 9)
        else: s.out.append('[unhandled 21/%02X]' % ah); uc.emu_stop()

    def load_exe(s, prog, seg):
        mu = s.mu; base = seg * 16; s.curseg = seg
        envseg = seg - 0x20
        env = b'COMSPEC=A:\\COMMAND.COM\0PATH=A:\\\0\0\x01\0A:\\TM5000G.EXE\0'
        mu.mem_write(envseg * 16, env)
        mu.mem_write(base, b'\xcd\x20' + struct.pack('<H', s.memtop) + b'\0' * 0xFC)
        mu.mem_write(base + 0x2C, struct.pack('<H', envseg)); mu.mem_write(base + 0x80, b'\x00\r')
        img = open(prog, 'rb').read()
        last, pages, nrel, hdr, minx, maxx, ss, sp, ck, ip, cs, rel = struct.unpack('<HHHHHHHHHHHH', img[2:26])
        size = pages * 512 - (512 - last if last else 0) - hdr * 16
        load = seg + 0x10
        mu.mem_write(load * 16, img[hdr * 16: hdr * 16 + size])
        for i in range(nrel):
            o, g = struct.unpack('<HH', img[rel + 4 * i: rel + 4 * i + 4]); a = (load + g) * 16 + o
            v = struct.unpack('<H', bytes(mu.mem_read(a, 2)))[0]; mu.mem_write(a, struct.pack('<H', (v + load) & 0xFFFF))
        s.blocks[seg] = s.memtop - seg
        s.W(UC_X86_REG_DS, seg); s.W(UC_X86_REG_ES, seg); s.W(UC_X86_REG_SS, load + ss); s.W(UC_X86_REG_SP, sp)
        s.W(UC_X86_REG_CS, load + cs); s.W(UC_X86_REG_IP, ip); s.W(UC_X86_REG_FLAGS, 0x202)
        s.out = []
        print('EXE image', size, 'bytes; min/max extra paras', minx, maxx, 'relocs', nrel)
    def go(s, maxins=300_000_000):
        cs = s.R(UC_X86_REG_CS); ip = s.R(UC_X86_REG_IP)
        try: s.mu.emu_start(cs * 16 + ip, 0, count=maxins)
        except UcError as e: s.out.append('\n[CRASH %s at %04X:%04X]' % (e, s.R(UC_X86_REG_CS), s.R(UC_X86_REG_IP)))

def K(ch):
    named = {'ESC': 0x011B, 'ENTER': 0x1C0D, 'F1': 0x3B00, 'UP': 0x4800, 'DN': 0x5000}
    return named[ch] if ch in named else (int(ch[2:], 16) if ch.startswith('0x') else ord(ch))

if __name__ == '__main__':
    keys = []
    for k in (sys.argv[1].split(',') if len(sys.argv) > 1 and sys.argv[1] else []):
        if k.startswith('s:'): keys += [ord(c) for c in k[2:]] + [0x1C0D]
        else: keys.append(K(k))
    m = Tracer(S.bus()); m.setup(keys)
    print('GRIDGPIB:', D.Machine.run(m, 'GRIDGPIB.COM', seg=0x0800)[:200].replace('\n', ' | '))
    m.log.clear(); m.order.clear(); m.tracking = True
    m.load_exe('TM5000G.EXE', 0x1000); m.go()
    print('hooked vectors:', sorted('%02Xh' % v for v in m.hooked))
    print(''.join(m.out)[-300:])
    for i, sc in enumerate(m.screens[-int(sys.argv[2]) if len(sys.argv) > 2 else -2:]): print('--- screen ---\n' + sc)
    print('\n=== interrupt calls in first-use order ===')
    for k in m.order: print('%-8s %-8s %-6s x%d' % (k[0], k[1], k[2], m.log[k]))
    print('files:', {k: len(v) for k, v in m.files.items()})
