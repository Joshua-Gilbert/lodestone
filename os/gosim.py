# Lodestone PC model for testing: real-mode CPU (unicorn), floppy image behind
# INT 13h (with the real controller's limits: no track crossing, no 64 KB DMA
# crossing), INT 10h mode 40h, RTC, keyboard script, COM2 serial mouse with
# IRQ3 delivery, BIOS tick.  Renders the 640x400 mode-40h screen to PNG.
import struct, sys
from unicorn import *
from unicorn.x86_const import *

class PC:
    def __init__(s, image, keys=(), mouse_moves=()):
        s.img = bytearray(open(image, 'rb').read()); s.spt, s.heads = 18, 2
        s.mu = Uc(UC_ARCH_X86, UC_MODE_16); s.mu.mem_map(0, 0x110000)
        s.keys = list(keys); s.moves = list(mouse_moves); s.log = []; s.tty = ''
        s.mode = 3; s.ticks = 0; s.calls13 = []; s.uart = {'lcr': 0, 'mcr': 0, 'ier': 0, 'rx': [], 'scr': 0}
        s.pic = 0xFF; s.halts = 0; s.stopped = False
        mu = s.mu
        mu.mem_write(0x410, struct.pack('<H', 0x4423)); mu.mem_write(0x413, struct.pack('<H', 640))
        mu.mem_write(0xFFFF5, b'10/25/89'); mu.mem_write(0xFFFFE, b'\xFC')
        for v in range(256): mu.mem_write(v * 4, struct.pack('<HH', 0xFF53, 0xF000))
        mu.mem_write(0xFFF53, b'\xCF')
        mu.hook_add(UC_HOOK_INTR, s.intr)
        mu.hook_add(UC_HOOK_INSN, s.hin, None, 1, 0, UC_X86_INS_IN)
        mu.hook_add(UC_HOOK_INSN, s.hout, None, 1, 0, UC_X86_INS_OUT)
    R = lambda s, r: s.mu.reg_read(r)
    def W(s, r, v): s.mu.reg_write(r, v)
    def cf(s, c):
        f = s.R(UC_X86_REG_FLAGS); s.W(UC_X86_REG_FLAGS, (f | 1) if c else (f & ~1))
    def hin(s, uc, port, size, ud):
        u = s.uart
        if port == 0x7F8: return 0xFD
        if port == 0x3DA:                     # 1-in-10 vertical retrace pulses
            s.vs = getattr(s, 'vs', 0) + 1
            return 0x08 if (s.vs // 50) % 10 == 0 else 0x00
        if port == 0x21: return s.pic
        if 0x2F8 <= port <= 0x2FF:
            o = port - 0x2F8
            if o == 0: return u['rx'].pop(0) if u['rx'] else 0
            if o == 1: return u['ier']
            if o == 3: return u['lcr']
            if o == 4: return u['mcr']
            if o == 5: return 0x60 | (1 if u['rx'] else 0)
            if o == 7: return u['scr']
            return 0
        return 0xFF
    def hout(s, uc, port, size, val, ud):
        u = s.uart; val &= 0xFF
        if port == 0x21: s.pic = val
        if 0x2F8 <= port <= 0x2FF:
            o = port - 0x2F8
            if o == 1 and not (u['lcr'] & 0x80): u['ier'] = val
            elif o == 3: u['lcr'] = val
            elif o == 4:
                if val & 3 == 3 and u['mcr'] & 3 == 0: u['rx'].append(ord('M'))
                u['mcr'] = val
            elif o == 7: u['scr'] = val
    def chs(s, c, h, sct): return (c * s.heads + h) * s.spt + sct - 1
    def intr(s, uc, n, ud):
        R = s.R; W = s.W
        ah, al = R(UC_X86_REG_AH), R(UC_X86_REG_AL)
        s.log.append((n, R(UC_X86_REG_AX)))
        if n == 0x13:
            if ah == 0: W(UC_X86_REG_AH, 0); s.cf(0); return
            if ah in (2, 3):
                cx, dx = R(UC_X86_REG_CX), R(UC_X86_REG_DX)
                c, sct, h = cx >> 8, cx & 63, dx >> 8
                es, bx = R(UC_X86_REG_ES), R(UC_X86_REG_BX); lin = es * 16 + bx
                s.calls13.append((ah, c, h, sct, al, '%05X' % lin))
                if sct + al - 1 > s.spt: W(UC_X86_REG_AH, 4); s.cf(1); return     # past end of track
                if (lin & 0xFFFF) + al * 512 > 0x10000: W(UC_X86_REG_AH, 9); s.cf(1); return  # DMA boundary
                lba = s.chs(c, h, sct)
                if ah == 2: uc.mem_write(lin, bytes(s.img[lba * 512:(lba + al) * 512]))
                else: s.img[lba * 512:(lba + al) * 512] = uc.mem_read(lin, al * 512)
                W(UC_X86_REG_AH, 0); s.cf(0); return
            W(UC_X86_REG_AH, 1); s.cf(1); return
        if n == 0x10:
            ax = R(UC_X86_REG_AX)
            if ah == 0:
                s.mode = al; uc.mem_write(0x449, bytes([al]))
                uc.mem_write(0xB8000, b'\0' * 0x8000)
            elif ah == 0x0E: s.tty += chr(al)
            return
        if n == 0x16:
            if ah in (0, 0x10):
                if not s.keys: s.stopped = True; uc.emu_stop(); return
                W(UC_X86_REG_AX, s.keys.pop(0)); return
            if ah in (1, 0x11):
                f = R(UC_X86_REG_FLAGS)
                if s.keys and s.ticks >= s.keys_after: W(UC_X86_REG_AX, s.keys[0]); W(UC_X86_REG_FLAGS, f & ~0x40)
                else: W(UC_X86_REG_FLAGS, f | 0x40)
                return
            return
        if n == 0x1A:
            if ah == 2: W(UC_X86_REG_CX, 0x1731); W(UC_X86_REG_DX, 0x2500); s.cf(0)
            if ah == 4: W(UC_X86_REG_CX, 0x2026); W(UC_X86_REG_DX, 0x1004); s.cf(0)
            return
        if n == 0x12: W(UC_X86_REG_AX, 640); return
        if n == 0x11: W(UC_X86_REG_AX, 0x4463); return
        if n == 0x15:
            ax = R(UC_X86_REG_AX)
            if ax == 0xE440: W(UC_X86_REG_CX, 1408); W(UC_X86_REG_AH, 0); s.cf(0); return
            if ax == 0xE441: W(UC_X86_REG_CX, 0); W(UC_X86_REG_AH, 0); s.cf(0); return
            W(UC_X86_REG_AH, 0x86); s.cf(1); return
        if n == 0x19: s.stopped = True; s.tty += '[INT19]'; uc.emu_stop(); return
        if n == 0x21:
            if ah == 9:
                p = R(UC_X86_REG_DS) * 16 + R(UC_X86_REG_DX); t = b''
                while uc.mem_read(p, 1)[0] != 0x24: t += bytes(uc.mem_read(p, 1)); p += 1
                s.tty += t.decode('latin1')
            elif ah == 2: s.tty += chr(R(UC_X86_REG_DL))
            elif ah == 0x4C: s.stopped = True; uc.emu_stop()
            return
        # vectored (e.g. IRQ handlers installed by the guest)
        seg, off = struct.unpack('<HH', bytes(uc.mem_read(n * 4, 4)))[::-1]
        if (seg, off) != (0xF000, 0xFF53):
            s.push_int(seg, off)
    def push(s, v):
        sp = (s.R(UC_X86_REG_SP) - 2) & 0xFFFF; s.W(UC_X86_REG_SP, sp)
        s.mu.mem_write(s.R(UC_X86_REG_SS) * 16 + sp, struct.pack('<H', v))
    def push_int(s, seg, off):
        s.push(s.R(UC_X86_REG_FLAGS)); s.push(s.R(UC_X86_REG_CS)); s.push(s.R(UC_X86_REG_IP))
        s.W(UC_X86_REG_FLAGS, s.R(UC_X86_REG_FLAGS) & ~0x200); s.W(UC_X86_REG_CS, seg); s.W(UC_X86_REG_IP, off)
    def irq3(s):
        seg, off = struct.unpack('<HH', bytes(s.mu.mem_read(0x0B * 4, 4)))[::-1]
        s.push_int(seg, off)
    def run(s, cs, ip, slices=4000, keys_after=0):
        s.keys_after = keys_after
        s.W(UC_X86_REG_CS, cs); s.W(UC_X86_REG_IP, ip)
        for i in range(slices):
            if s.stopped: break
            try:
                s.mu.emu_start(s.R(UC_X86_REG_CS) * 16 + s.R(UC_X86_REG_IP), 0, count=200000)
            except UcError as e:
                cs_, ip_ = s.R(UC_X86_REG_CS), s.R(UC_X86_REG_IP)
                op = s.mu.mem_read(cs_ * 16 + ip_ - 1, 1)[0]
                if e.errno == UC_ERR_INSN_INVALID or op != 0xF4:
                    s.tty += '\n[CPU %s at %04X:%04X]' % (e, cs_, ip_); break
            # one timer tick per slice (also wakes HLT)
            s.ticks += 1
            t = struct.unpack('<I', bytes(s.mu.mem_read(0x46C, 4)))[0] + 1
            s.mu.mem_write(0x46C, struct.pack('<I', t))
            if s.R(UC_X86_REG_FLAGS) & 0x200:
                if s.moves and s.ticks >= s.moves[0][0] and s.uart['ier'] & 1 and not (s.pic & 8):
                    _, dx, dy, b = s.moves.pop(0)
                    dx &= 0xFF; dy &= 0xFF
                    s.uart['rx'] += [0x40 | (0x20 if b & 1 else 0) | (0x10 if b & 2 else 0) | ((dy >> 6) << 2) | (dx >> 6), dx & 0x3F, dy & 0x3F]
                    s.irq3()
        return s
    def screen_png(s, path, scale=2):
        from PIL import Image
        vram = bytes(s.mu.mem_read(0xB8000, 0x8000))
        im = Image.new('RGB', (640, 400))
        px = im.load()
        for y in range(400):
            base = (y & 3) * 0x2000 + (y >> 2) * 80
            for xb in range(80):
                v = vram[base + xb]
                for b in range(8):
                    px[xb * 8 + b, y] = (255, 160, 40) if v & (0x80 >> b) else (24, 10, 0)
        im.resize((640 * scale // 2 * 2, 400 * scale // 2 * 2), Image.NEAREST).save(path)
