# GRiDCase 1520 model: real BIOS INT 15h (ROM_F000.BIN), CMOS, AppROM window,
# V6366/panel ports, one UART with a Microsoft mouse on COM1, DOS from tm5trace.
import struct, sys
from unicorn import *
from unicorn.x86_const import *
import os
import tm5trace as T, sim7210 as S, dosemu as D, mkrom
HERE = os.path.dirname(os.path.abspath(__file__))
def romfile(n):
    for d in (HERE, os.path.join(HERE, '..', 'rom')):
        if os.path.exists(os.path.join(d, n)): return os.path.join(d, n)
    raise FileNotFoundError(n)

class Grid(T.Tracer):
    def setup2(s, rom_images, keys):
        s.setup(keys)
        mu = s.mu
        mu.mem_write(0xF0000, open(romfile('ROM_F000.BIN'), 'rb').read())
        mu.mem_write(0x15 * 4, struct.pack('<HH', 0xF859, 0xF000))
        s.cmos = bytearray(open(romfile('CMOS128.BIN'), 'rb').read()); s.cmos[0x3F] = 0x02; s.cidx = 0
        s.roms = rom_images                 # socket -> 128 KB image
        s.p6f8 = 0; s.sel = 0; s.saved = None; s.ports = []
        s.uart = {'scr': 0, 'lcr': 0, 'mcr': 0, 'ier': 0, 'rx': [], 'dll': 12, 'dlm': 0}
        s.mode40 = False
    def remap(s):
        mu = s.mu
        if s.p6f8 & 1:
            if s.saved is None: s.saved = bytes(mu.mem_read(0xA0000, 0x20000))
            sock = (s.sel >> 2) & 1
            img = s.roms.get(sock) if (s.sel & 3) == 0 else None
            mu.mem_write(0xA0000, img if img else b'\xFF' * 0x20000)
        elif s.saved is not None:
            mu.mem_write(0xA0000, s.saved); s.saved = None
    def hin(s, uc, port, size, ud):
        if port == 0x71: return s.cmos[s.cidx & 0x7F]
        if port == 0x6F8: return 0x10 | s.p6f8
        if port == 0x7F8: return 0x0D
        if port == 0x3DF: return 0xC1
        if 0x3F8 <= port <= 0x3FF:
            u = s.uart; o = port - 0x3F8
            if o == 0: return (u['dll'] if u['lcr'] & 0x80 else (u['rx'].pop(0) if u['rx'] else 0))
            if o == 1: return u['dlm'] if u['lcr'] & 0x80 else u['ier']
            if o == 3: return u['lcr']
            if o == 4: return u['mcr']
            if o == 5: return 0x60 | (1 if u['rx'] else 0)
            if o == 6: return 0xB0
            if o == 7: return u['scr']
        return D.Machine.hin(s, uc, port, size, ud)
    def hout(s, uc, port, size, val, ud):
        val &= 0xFF
        if port == 0x70: s.cidx = val; return
        if port == 0x71: s.cmos[s.cidx & 0x7F] = val; return
        if port in (0x6F8, 0x7F8, 0x7F9, 0x7FA, 0xBD0, 0xBD1): s.ports.append((port, val))
        if port == 0x6F8: s.p6f8 = val; s.remap(); return
        if port == 0xBD0: s.sel = val; s.remap(); return
        if 0x3F8 <= port <= 0x3FF:
            u = s.uart; o = port - 0x3F8
            if o == 0:
                if u['lcr'] & 0x80: u['dll'] = val
            elif o == 1:
                if u['lcr'] & 0x80: u['dlm'] = val
                else: u['ier'] = val
            elif o == 3: u['lcr'] = val
            elif o == 4:
                if val & 3 == 3 and u['mcr'] & 3 == 0: u['rx'] += [ord('M')]
                u['mcr'] = val
            elif o == 7: u['scr'] = val
            return
        return D.Machine.hout(s, uc, port, size, val, ud)
    def intr(s, uc, n, ud):
        R = s.R; W = s.W
        if n == 0x15:                      # vector into the real BIOS
            s.note(('INT 15h', 'AX=%04X' % R(UC_X86_REG_AX), ''))
            seg, off = s.ivt(n); sp = R(UC_X86_REG_SP); ss = R(UC_X86_REG_SS)
            for v in (R(UC_X86_REG_FLAGS), R(UC_X86_REG_CS), R(UC_X86_REG_IP)):
                sp = (sp - 2) & 0xFFFF; uc.mem_write(ss * 16 + sp, struct.pack('<H', v))
            W(UC_X86_REG_SP, sp); W(UC_X86_REG_CS, seg); W(UC_X86_REG_IP, off); return
        if n == 0x10 and R(UC_X86_REG_AX) == 0x0040:
            s.mode = 0x40; uc.mem_write(0x449, b'\x40'); s.mode40 = True; return
        return T.Tracer.intr(s, uc, n, ud)

if __name__ == '__main__':
    roms = {0: mkrom.image(b'\xEB\xFE')}
    keys = [0x3920, 0x1E61, 0x3B00, 0x011B]
    m = Grid(S.bus()); m.setup2(roms, keys)
    out = D.Machine.run(m, sys.argv[1] if len(sys.argv) > 1 else 'GRIDPROBE.COM', seg=0x1000,
                        maxins=200_000_000)
    print(out[-200:])
    rep = m.files.get('A:\\GPROBE.TXT', b'').decode('latin1')
    print(rep)
    print('ROM files:', {k: len(v) for k, v in m.files.items()})
    if 'A:\\ROM0.BIN' in m.files: print('ROM0 == source image:', m.files['A:\\ROM0.BIN'] == roms[0])
    print('port writes:', m.ports[:40])
    print('video RAM restored after unmap:', m.saved is None)
