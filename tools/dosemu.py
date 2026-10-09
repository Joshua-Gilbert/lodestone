# Minimal multi-program DOS + GRiD 1520 GPIB emulator for Lodestone tests.
# Runs several .COM programs one after another in the same memory, so a
# TSR (GRIDGPIB) installed by the first stays resident for the next; real
# IVT vectoring for INT 60h-66h; uPD7210 + bus model from sim7210.py; PIT
# channel 0 + BIOS tick model.
import struct
from unicorn import *
from unicorn.x86_const import *
import sim7210 as S

class Machine:
    def __init__(s, devices, ticks_per=300):
        s.mu = Uc(UC_ARCH_X86, UC_MODE_16); s.mu.mem_map(0, 0x110000)
        s.chip = S.NEC7210(devices); s.out = []; s.files = {}; s.fh = {}
        s.nb = 0; s.tp = ticks_per; s.pit = {'latch': None, 'hi': False}
        s.pitmode = []; s.tsr = None; s.exitcode = None; s.freed = []
        mu = s.mu
        mu.hook_add(UC_HOOK_INTR, s.intr)
        mu.hook_add(UC_HOOK_INSN, s.hin, None, 1, 0, UC_X86_INS_IN)
        mu.hook_add(UC_HOOK_INSN, s.hout, None, 1, 0, UC_X86_INS_OUT)
        mu.hook_add(UC_HOOK_BLOCK, s.blk)
    R = lambda s, r: s.mu.reg_read(r)
    def W(s, r, v): s.mu.reg_write(r, v)
    def cf(s, c):
        f = s.R(UC_X86_REG_FLAGS); s.W(UC_X86_REG_FLAGS, (f | 1) if c else (f & ~1))
    def blk(s, uc, a, sz, ud):
        s.nb += 1
        if s.nb % s.tp == 0:
            t = struct.unpack('<H', bytes(uc.mem_read(0x46C, 2)))[0]
            uc.mem_write(0x46C, struct.pack('<H', (t + 1) & 0xFFFF))
    def hin(s, uc, port, size, ud):
        if port == 0x40:
            p = s.pit
            if p['latch'] is None:
                p['latch'] = (65536 - (s.nb % s.tp) * (65536 // s.tp)) & 0xFFFF; p['hi'] = False
            v = p['latch']
            if not p['hi']: p['hi'] = True; return v & 0xFF
            p['latch'] = None; return v >> 8
        if (port & 0x3FF) == S.BASE and port < 0x2000: return s.chip.read(port >> 10)
        return 0xFF
    def hout(s, uc, port, size, val, ud):
        if port == 0x43:
            if val & 0xF0: s.pitmode.append(val & 0xFF)
            else: s.pit['latch'] = None
            return
        if (port & 0x3FF) == S.BASE and port < 0x2000: s.chip.write(port >> 10, val & 0xFF)
    def ivt(s, n):
        o, g = struct.unpack('<HH', bytes(s.mu.mem_read(n * 4, 4))); return g, o
    def intr(s, uc, n, ud):
        R = s.R; W = s.W
        if 0x60 <= n <= 0x66:
            seg, off = s.ivt(n)
            if seg == 0 and off == 0: s.out.append('[INT %02X to null]' % n); uc.emu_stop(); return
            sp = R(UC_X86_REG_SP); ss = R(UC_X86_REG_SS)
            for v in (R(UC_X86_REG_FLAGS), R(UC_X86_REG_CS), R(UC_X86_REG_IP)):
                sp = (sp - 2) & 0xFFFF; uc.mem_write(ss * 16 + sp, struct.pack('<H', v))
            W(UC_X86_REG_SP, sp); W(UC_X86_REG_FLAGS, R(UC_X86_REG_FLAGS) & ~0x200)
            W(UC_X86_REG_CS, seg); W(UC_X86_REG_IP, off); return
        if n in (0x10, 0x16): return
        if n != 0x21: s.out.append('[int %02X]' % n); uc.emu_stop(); return
        ah = R(UC_X86_REG_AH); al = R(UC_X86_REG_AL); ds = R(UC_X86_REG_DS); dx = R(UC_X86_REG_DX)
        bx = R(UC_X86_REG_BX); cx = R(UC_X86_REG_CX)
        if ah == 9:
            p = ds * 16 + dx; b = b''
            while uc.mem_read(p, 1)[0] != 0x24: b += bytes(uc.mem_read(p, 1)); p += 1
            s.out.append(b.decode('latin1'))
        elif ah == 2: s.out.append(chr(R(UC_X86_REG_DL)))
        elif ah == 0x35:
            g, o = s.ivt(al); W(UC_X86_REG_ES, g); W(UC_X86_REG_BX, o)
        elif ah == 0x25: uc.mem_write(al * 4, struct.pack('<HH', dx, ds))
        elif ah == 0x31: s.tsr = (R(UC_X86_REG_CS), dx); uc.emu_stop()
        elif ah == 0x49: s.freed.append(R(UC_X86_REG_ES)); s.cf(0)
        elif ah == 0x3D:
            nm = bytes(uc.mem_read(ds * 16 + dx, 20)).split(b'\0')[0]
            W(UC_X86_REG_AX, 2); s.cf(1)
        elif ah == 0x3C:
            nm = bytes(uc.mem_read(ds * 16 + dx, 20)).split(b'\0')[0].decode()
            h = 5 + len(s.fh); s.fh[h] = nm; s.files[nm] = b''; W(UC_X86_REG_AX, h); s.cf(0)
        elif ah == 0x40:
            if bx in s.fh: s.files[s.fh[bx]] += bytes(uc.mem_read(ds * 16 + dx, cx))
            elif bx in (1, 2): s.out.append(bytes(uc.mem_read(ds * 16 + dx, cx)).decode('latin1'))
            W(UC_X86_REG_AX, cx); s.cf(0)
        elif ah in (0x3E, 0x68): s.cf(0)
        elif ah == 0x4C: s.exitcode = al; uc.emu_stop()
        elif ah == 0x4A: s.cf(0)
        elif ah == 0x30: W(UC_X86_REG_AX, 0x1E03); W(UC_X86_REG_BX, 0); s.cf(0)
        elif ah == 0x62: W(UC_X86_REG_BX, s.curseg)
        elif ah == 0x44:
            if al == 0: W(UC_X86_REG_DX, 0x80 | (0x03 if bx < 2 else 0)); s.cf(0)
            else: s.cf(0)
        elif ah == 0x48: W(UC_X86_REG_AX, 0x8000); s.cf(0)
        elif ah in (0x1A, 0x33, 0x0B, 0x29, 0x19, 0x63, 0x38, 0x37, 0x58): W(UC_X86_REG_AL, 0); s.cf(0)
        elif ah == 0x2C: W(UC_X86_REG_CX, 0); W(UC_X86_REG_DX, 0)
        elif ah == 0x2A: W(UC_X86_REG_CX, 2026); W(UC_X86_REG_DX, 0x091D)
        elif ah == 0x06:
            if R(UC_X86_REG_DL) != 0xFF: s.out.append(chr(R(UC_X86_REG_DL)))
            else: W(UC_X86_REG_FLAGS, R(UC_X86_REG_FLAGS) | 0x40)
        else: s.out.append('[21/%02X]' % ah); uc.emu_stop()
    def run(s, prog, args='', seg=0x1000, maxins=400_000_000):
        mu = s.mu; base = seg * 16; s.curseg = seg
        mu.mem_write(base, b'\xcd\x20' + struct.pack('<H', 0x9FFF) + b'\0' * 0xFC)
        mu.mem_write(base + 0x2C, struct.pack('<H', seg - 0x10))
        img = open(prog, 'rb').read()
        a = args.encode(); mu.mem_write(base + 0x80, bytes([len(a)]) + a + b'\r')
        if img[:2] == b'MZ':                       # EXE: load + relocate
            last, pages, nrel, hdr, minx, maxx, ss, sp, ck, ip, cs, rel = struct.unpack('<HHHHHHHHHHHH', img[2:26])
            size = pages * 512 - (512 - last if last else 0) - hdr * 16
            load = seg + 0x10
            mu.mem_write(load * 16, img[hdr * 16: hdr * 16 + size])
            for i in range(nrel):
                o, g = struct.unpack('<HH', img[rel + 4 * i: rel + 4 * i + 4])
                addr = (load + g) * 16 + o
                v = struct.unpack('<H', bytes(mu.mem_read(addr, 2)))[0]
                mu.mem_write(addr, struct.pack('<H', (v + load) & 0xFFFF))
            s.W(UC_X86_REG_DS, seg); s.W(UC_X86_REG_ES, seg)
            s.W(UC_X86_REG_SS, load + ss); s.W(UC_X86_REG_SP, sp)
            s.W(UC_X86_REG_CS, load + cs); s.W(UC_X86_REG_FLAGS, 0x202)
            s.out = []; s.tsr = None; s.exitcode = None
            try:
                mu.emu_start((load + cs) * 16 + ip, 0, count=maxins)
            except UcError as e:
                s.out.append('\n[CRASH %s at %04X:%04X]' % (e, s.R(UC_X86_REG_CS), s.R(UC_X86_REG_IP)))
            return ''.join(s.out)
        mu.mem_write(base + 0x100, img)
        a = args.encode(); mu.mem_write(base + 0x80, bytes([len(a)]) + a + b'\r')
        for r in (UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS): s.W(r, seg)
        s.W(UC_X86_REG_SP, 0xFFFE); mu.mem_write(base + 0xFFFE, b'\0\0')
        s.W(UC_X86_REG_FLAGS, 0x202)
        s.out = []; s.tsr = None; s.exitcode = None
        try:
            mu.emu_start(base + 0x100, 0, count=maxins)
        except UcError as e:
            s.out.append('\n[CRASH %s at %04X:%04X]' % (e, s.R(UC_X86_REG_CS), s.R(UC_X86_REG_IP)))
        return ''.join(s.out)
