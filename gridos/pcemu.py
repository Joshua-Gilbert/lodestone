"""A GRiDCase 1520 as seen by an operating system: x86 real mode (unicorn)
with only a BIOS - no DOS.  Used to test the Grid-OS kernel, which provides
DOS itself.

  * BIOS services in Python (INT 10h, 11h, 12h, 13h, 14h, 15h, 16h, 17h,
    18h, 19h, 1Ah) behind F000 stubs; every other vector is whatever the
    guest installs (the BIOS leaves 60h-67h null, like a real AT BIOS).
  * Timer IRQ 0 through the IVT at 18.2 Hz into a real-code BIOS INT 08h
    handler that counts 40:6C and calls INT 1Ch; HLT sleeps to the next IRQ.
  * Floppies A: and B: as image files behind INT 13h with the real
    controller's limits: no track crossing, no 64 KB DMA crossing, ROM
    can't be a DMA buffer.  Change line per drive.
  * Video: text modes (B800 cells), GRiD mode 40h (640x400 1 bpp),
    CGA modes 4/6 memory; PNG rendering.
  * uPD7210 at 02E1h + n*400h (any object with read/write), COM2 serial
    mouse with IRQ3, PIT channel 0, port 61h refresh toggle, panel 7F8h.

Time: 4 us per executed basic block (about a 10 MHz 286).
"""
import collections, datetime, os, struct
from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR, UC_HOOK_INSN, UC_HOOK_BLOCK
from unicorn import x86_const as X

TICK_US = 1e6 * 65536 / 1193182
BLOCK_US = 4.0
# per-iteration cost of REP string ops, from RAMSPEED on the 1520 (~10 MHz):
# rep stosw 6133 KB/s, rep lodsw 3738 KB/s, rep movsw 3074 KB/s
REP_US = {0xA4: 0.45, 0xA5: 0.65, 0xAA: 0.25, 0xAB: 0.33, 0xAC: 0.4, 0xAD: 0.53,
          0xA6: 1.0, 0xA7: 1.1, 0xAE: 0.9, 0xAF: 1.0, 0x6C: 0.6, 0x6D: 0.7, 0x6E: 0.6, 0x6F: 0.7}
STUB = 0xF000
R = {n: getattr(X, 'UC_X86_REG_' + n.upper()) for n in
     'ax bx cx dx si di bp sp cs ds es ss ip flags al ah bl bh cl ch dl dh'.split()}

# real-code BIOS pieces at F000:1000 and up
INT08 = bytes([0x50, 0x1E, 0x31, 0xC0, 0x8E, 0xD8, 0xFF, 0x06, 0x6C, 0x04, 0x75, 0x04,
               0xFF, 0x06, 0x6E, 0x04, 0xCD, 0x1C, 0xB0, 0x20, 0xE6, 0x20, 0x1F, 0x58, 0xCF])
IRQEOI = bytes([0x50, 0xB0, 0x20, 0xE6, 0x20, 0x58, 0xCF])
IRET = bytes([0xCF])


# A real floppy drive's timing (disk_model='real'): GRiD 1520 BIOS values
# (step 3 ms from SPECIFY DFh, head settle 15 ms, motor run-on 2 s; its
# motor-start wait is dead code, so a cold read just waits for the spindle),
# 300 rpm, and the standard 1.44 MB / 720 KB track layout: a sector's ID
# comes LEAD + n*SLOT bytes after the index, its data ends DATA_END later.
FD_REV = 200000.0
FD_STEP = 3000.0
FD_SETTLE = 15000.0
FD_SPINUP = 400000.0
FD_MOTOR_RUN = 2.0e6
FD_BIOS_IN = 250.0          # BIOS + FDC command phase
FD_BIOS_OUT = 100.0         # result phase + BIOS return


class Floppy:
    GEOM = {1474560: (80, 2, 18), 737280: (80, 2, 9), 1228800: (80, 2, 15), 368640: (40, 2, 9)}
    def timing(s):
        hd = s.spt >= 15
        byte = FD_REV / (12500.0 if hd else 6250.0)
        return byte * 146, byte * (682 if hd else 654), byte * 574
    def __init__(s, path_or_bytes):
        s.path = path_or_bytes if isinstance(path_or_bytes, str) else None
        s.img = bytearray(open(path_or_bytes, 'rb').read() if s.path else path_or_bytes)
        s.cyls, s.heads, s.spt = s.GEOM.get(len(s.img), (80, 2, 18))
        s.changed = False
        s.cyl = 0; s.recal = False; s.motor_off_at = -1.0; s.ready_at = 0.0
        s.ops = 0; s.busy_us = 0.0      # transfers and time spent in them
        s.wp = False                    # write-protect tab
        s.no_changeline = False         # a drive that always says "changed"
        s.bad = set()                   # LBAs that fail to read (CRC error)
    def save(s, path=None):
        open(path or s.path, 'wb').write(s.img)


class PC:
    def __init__(s, a=None, b=None, chip=None, start=datetime.datetime(2026, 10, 4, 21, 30, 0), mem_kb=640,
                 disk_model='flat'):
        s.mu = mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x110000)
        s.drives = [Floppy(a) if a is not None else None, Floppy(b) if b is not None else None]
        s.disk_model = disk_model       # 'flat' = 2 ms a sector; 'real' = seeks, rotation, motor
        s.marks = []                    # (BX, us) for INT 1Ah AH=0 calls with BX = BExxh
        s.chip = chip
        s.us = 0.0; s.next_tick = TICK_US; s.next_event = TICK_US
        s.due_at = float('inf'); s.on_due = None
        s.irq_pending = set(); s.pic_mask = 0xB8
        s.keys = collections.deque(); s.tty = []; s.log = []; s.lpt = []
        s.calls13 = []; s.ints = collections.Counter(); s.t13 = []
        s.stopped = None; s.crash = None; s.halted = False; s.blocked = False
        s.last_blk = (0, 0); s.pit_latch = None; s.pit_hi = False
        s.clock0 = start
        s.uart = {'lcr': 0, 'mcr': 0, 'ier': 0, 'rx': [], 'scr': 0, 'dll': 0}
        s.moves = []
        s.watch = None
        # CMOS: Joshua's 1520 (CMOS128.BIN) if it's here, else a 1.44 MB A:
        cm = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'CMOS128.BIN')
        s.cmos = bytearray(open(cm, 'rb').read()) if os.path.exists(cm) else bytearray(128)
        if not os.path.exists(cm): s.cmos[0x10] = 0x40; s.cmos[0x15:0x17] = b'\x80\x02'
        s.cidx = 0
        # IVT: BIOS services via stubs, IRQs via real code, 60h-67h null
        for n in range(256):
            mu.mem_write(n * 4, struct.pack('<HH', n * 8, STUB))
            mu.mem_write(STUB * 16 + n * 8, bytes([0xCD, n, 0xCA, 0x02, 0x00]))
        mu.mem_write(STUB * 16 + 0x1000, INT08)
        mu.mem_write(STUB * 16 + 0x1100, IRQEOI)
        mu.mem_write(STUB * 16 + 0x1200, IRET)
        mu.mem_write(8 * 4, struct.pack('<HH', 0x1000, STUB))
        for n in list(range(9, 0x10)) + list(range(0x70, 0x78)):
            mu.mem_write(n * 4, struct.pack('<HH', 0x1100, STUB))
        for n in (0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x0, 0x1, 0x3, 0x4, 0x5):
            mu.mem_write(n * 4, struct.pack('<HH', 0x1200, STUB))
        for n in range(0x20, 0x100):
            if n not in (0x40, 0x41, 0x46, 0x4A):
                mu.mem_write(n * 4, struct.pack('<HH', 0x1200, STUB))
        for n in range(0x60, 0x68):
            mu.mem_write(n * 4, b'\0\0\0\0')
        # BDA
        equip = 0x4423 | (0x40 if s.drives[1] else 0)
        mu.mem_write(0x410, struct.pack('<H', equip))
        mu.mem_write(0x413, struct.pack('<H', mem_kb))
        mu.mem_write(0x41A, struct.pack('<HH', 0x1E, 0x1E))
        mu.mem_write(0x449, bytes([3])); mu.mem_write(0x44A, struct.pack('<HH', 80, 4096))
        mu.mem_write(0x44E, b'\0\0'); mu.mem_write(0x450, bytes(16)); mu.mem_write(0x460, b'\x07\x06\x00')
        mu.mem_write(0x463, struct.pack('<H', 0x3D4)); mu.mem_write(0x484, bytes([24]))
        secs = start.hour * 3600 + start.minute * 60 + start.second
        mu.mem_write(0x46C, struct.pack('<I', int(secs * 1193182 / 65536)))
        mu.mem_write(0xFFFF5, b'10/25/89'); mu.mem_write(0xFFFFE, b'\xFC')
        s.wr(0xB800, 0, b'\x20\x07' * 2000)
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
    def rd(s, seg, off, n): return bytes(s.mu.mem_read((seg * 16 + off) & 0xFFFFF, n))
    def wr(s, seg, off, data): s.mu.mem_write((seg * 16 + off) & 0xFFFFF, bytes(data))
    def u16(s, seg, off): return struct.unpack('<H', s.rd(seg, off, 2))[0]
    def push(s, v):
        sp = (s.r('sp') - 2) & 0xFFFF; s.w('sp', sp); s.wr(s.r('ss'), sp, struct.pack('<H', v & 0xFFFF))
    def asciiz(s, seg, off, n=128): return s.rd(seg, off, n).split(b'\0')[0]

    # ---- time and interrupts -------------------------------------------------
    def clock(s): return s.us
    def now(s): return s.clock0 + datetime.timedelta(microseconds=s.us)
    def schedule(s, t):
        if t < s.due_at: s.due_at = t
        if t < s.next_event: s.next_event = t

    def blk(s, uc, addr, size, ud):
        # A REP string instruction runs one iteration per block (the block
        # restarts at the same address), so charge those at the measured
        # 1520 rate instead of a whole block each.
        if addr == s.last_blk[0] and size <= 4: s.us += s.rep_us(addr, size)
        else: s.us += BLOCK_US
        s.last_blk = (addr, size)
        if s.watch: s.watch(addr)
        if s.us >= s.next_event: s.on_time()

    def rep_us(s, addr, size):
        b = bytes(s.mu.mem_read(addr, size)); rep = False; i = 0
        while i < size - 1 and b[i] in (0x26, 0x2E, 0x36, 0x3E, 0xF2, 0xF3):
            rep |= b[i] in (0xF2, 0xF3); i += 1
        if rep and i == size - 1 and b[i] in REP_US: return REP_US[b[i]]
        return BLOCK_US

    def on_time(s):
        late = 0
        while s.us >= s.next_tick:
            if 0 in s.irq_pending: late += 1    # (a long BIOS wait: the BIOS
            s.irq_pending.add(0)                #  clock counts every tick)
            s.next_tick += TICK_US
            s.mu.emu_stop()
        if late:
            t = struct.unpack('<I', s.rd(0, 0x46C, 4))[0] + late
            s.wr(0, 0x46C, struct.pack('<I', t))
        if s.us >= s.due_at:
            s.due_at = float('inf')
            if s.on_due: s.on_due()
        s.next_event = min(s.next_tick, s.due_at)

    def sleep_to_tick(s):
        s.us = max(s.us, s.next_tick); s.on_time()

    def deliver_irqs(s):
        if not (s.r('flags') & 0x200) or not s.irq_pending: return
        for irq in sorted(s.irq_pending):
            if s.pic_mask & (1 << irq): continue
            s.irq_pending.discard(irq)
            vec = 8 + irq
            off, seg = struct.unpack('<HH', s.rd(0, vec * 4, 4))
            s.push(s.r('flags')); s.push(s.r('cs')); s.push(s.r('ip'))
            s.w('flags', s.r('flags') & ~0x300)
            s.w('cs', seg); s.w('ip', off)
            return                              # one at a time; IF is now clear

    def intr(s, uc, n, ud):
        cs, ip = s.r('cs'), s.r('ip')
        if not (cs == STUB and ip - 2 == n * 8):          # not the BIOS stub itself
            off, seg = struct.unpack('<HH', s.rd(0, n * 4, 4))
            if not (seg == STUB and off == n * 8):
                if seg == 0 and off == 0:
                    s.crash = 'INT %02Xh through a null vector at %04X:%04X (AX=%04X)' % (n, cs, ip, s.r('ax'))
                    uc.emu_stop(); return
                s.push(s.r('flags')); s.push(cs); s.push(ip)
                s.w('flags', s.r('flags') & ~0x300)
                s.w('cs', seg); s.w('ip', off)
                return
        s.ints[n] += 1
        h = getattr(s, 'int%02x' % n, None)
        if h: h()
        else: s.log.append('[BIOS int %02Xh AX=%04X not emulated]' % (n, s.r('ax')))

    # ---- ports --------------------------------------------------------------
    def hin(s, uc, port, size, ud):
        if port == 0x40:
            if s.pit_latch is None:
                n = int(s.us * 1.193182) % 32768
                s.pit_latch = (65536 - 2 * n) & 0xFFFF; s.pit_hi = False
            v = s.pit_latch
            if not s.pit_hi: s.pit_hi = True; return v & 0xFF
            s.pit_latch = None; return v >> 8
        if port == 0x61: return (int(s.us / 15.085) & 1) << 4
        if port == 0x71: return s.cmos_read(s.cidx)
        if port == 0x21: return s.pic_mask
        if port == 0x20: return 0
        if port == 0x7F8: return 0xFD
        if port == 0x3DA:
            return 0x08 if int(s.us / 1000) % 16 == 0 else 0x00
        if 0x2F8 <= port <= 0x2FF: return s.uart_in(port - 0x2F8)
        if s.chip is not None and (port & 0x3FF) == 0x2E1 and port < 0x2000:
            return s.chip.read(port >> 10)
        return 0xFF

    def cmos_read(s, i):
        bcd = lambda v: ((v // 10) << 4) | (v % 10)
        n = s.now()
        rtc = {0: n.second, 2: n.minute, 4: n.hour, 6: (n.weekday() + 1) % 7 + 1, 7: n.day, 8: n.month,
               9: n.year % 100, 0x32: n.year // 100}
        if i in rtc: return bcd(rtc[i])
        if i == 0x0A: return 0x26                       # no update in progress
        if i == 0x0B: return 0x02                       # BCD, 24 hour
        if i == 0x0D: return 0x80                       # battery good
        return s.cmos[i & 0x7F]

    def hout(s, uc, port, size, val, ud):
        val &= 0xFF
        if port == 0x70: s.cidx = val & 0x7F; return
        if port == 0x71:
            if s.cidx >= 0x0E: s.cmos[s.cidx] = val
            return
        if port == 0x43:
            if (val & 0xF0) == 0:
                n = int(s.us * 1.193182) % 32768
                s.pit_latch = (65536 - 2 * n) & 0xFFFF; s.pit_hi = False
            return
        if port == 0x21: s.pic_mask = val; return
        if 0x2F8 <= port <= 0x2FF: return s.uart_out(port - 0x2F8, val)
        if s.chip is not None and (port & 0x3FF) == 0x2E1 and port < 0x2000:
            s.chip.write(port >> 10, val)

    def uart_in(s, o):
        u = s.uart
        if o == 0:
            if u['lcr'] & 0x80: return u['dll']
            return u['rx'].pop(0) if u['rx'] else 0
        if o == 1: return u['ier']
        if o == 2: return 0x04 if u['rx'] else 0x01
        if o == 3: return u['lcr']
        if o == 4: return u['mcr']
        if o == 5: return 0x60 | (1 if u['rx'] else 0)
        if o == 6: return 0xB0
        if o == 7: return u['scr']
        return 0

    def uart_out(s, o, v):
        u = s.uart
        if o == 0 and u['lcr'] & 0x80: u['dll'] = v
        elif o == 1 and not (u['lcr'] & 0x80): u['ier'] = v
        elif o == 3: u['lcr'] = v
        elif o == 4:
            if s.mouse and v & 3 == 3 and u['mcr'] & 3 == 0:
                u['rx'].append(ord('M'))
            u['mcr'] = v
        elif o == 7: u['scr'] = v
    mouse = False

    def mouse_move(s, dx, dy, buttons=0):
        """Queue a Microsoft-protocol packet and raise IRQ3."""
        dx &= 0xFF; dy &= 0xFF
        s.uart['rx'] += [0x40 | (0x20 if buttons & 1 else 0) | (0x10 if buttons & 2 else 0) |
                         ((dy >> 6) << 2) | (dx >> 6), dx & 0x3F, dy & 0x3F]
        if s.uart['ier'] & 1: s.irq_pending.add(3)

    # ---- BIOS ---------------------------------------------------------------
    def mode(s): return s.rd(0, 0x449, 1)[0]
    def cursor(s):
        c, r = s.rd(0, 0x450, 2); return r, c
    def set_cursor(s, r, c): s.wr(0, 0x450, [c, r])

    def int10(s):
        ah, al = s.r('ah'), s.r('al')
        mode = s.mode()
        text = mode in (0, 1, 2, 3, 7)
        cols = 40 if mode in (0, 1) else 80
        if ah == 0x00:
            m = al & 0x7F
            s.wr(0, 0x449, [m]); s.wr(0, 0x450, bytes(16))
            c = 40 if m in (0, 1, 4, 5) else 80
            s.wr(0, 0x44A, struct.pack('<H', c))
            if not al & 0x80:
                if m in (0, 1, 2, 3, 7): s.wr(0xB800, 0, b'\x20\x07' * 2000)
                else: s.wr(0xB800, 0, bytes(0x8000))
            s.log.append('[mode %02Xh]' % m)
        elif ah == 0x01: s.wr(0, 0x460, [s.r('cl'), s.r('ch')])
        elif ah == 0x02: s.set_cursor(s.r('dh'), s.r('dl'))
        elif ah == 0x03:
            r, c = s.cursor(); s.w('dx', (r << 8) | c); s.w('cx', 0x0607)
        elif ah == 0x05: pass
        elif ah in (0x06, 0x07) and text:
            n = al; attr = s.r('bh')
            r0, c0, r1, c1 = s.r('ch'), s.r('cl'), s.r('dh'), s.r('dl')
            r1 = min(r1, 24); c1 = min(c1, cols - 1)
            rows = [bytearray(s.rd(0xB800, (r * cols + c0) * 2, (c1 - c0 + 1) * 2)) for r in range(r0, r1 + 1)]
            blank = bytearray([0x20, attr] * (c1 - c0 + 1))
            h = len(rows)
            if n == 0 or n >= h: rows = [blank[:] for _ in rows]
            elif ah == 6: rows = rows[n:] + [blank[:] for _ in range(n)]
            else: rows = [blank[:] for _ in range(n)] + rows[:h - n]
            for i, r in enumerate(range(r0, r1 + 1)):
                s.wr(0xB800, (r * cols + c0) * 2, rows[i])
        elif ah == 0x08 and text:
            r, c = s.cursor(); v = s.rd(0xB800, (r * cols + c) * 2, 2)
            s.w('ax', v[0] | (v[1] << 8))
        elif ah in (0x09, 0x0A):
            if text:
                r, c = s.cursor()
                for i in range(s.r('cx')):
                    p = r * cols + c + i
                    if p < 2000:
                        s.wr(0xB800, p * 2, [al] + ([s.r('bl')] if ah == 9 else []))
        elif ah == 0x0E: s.tty_put(al)
        elif ah == 0x0F:
            s.w('ax', (cols << 8) | mode); s.w('bx', s.r('bx') & 0xFF)
        elif ah == 0x0C and mode in (4, 5, 6):
            x, y = s.r('cx'), s.r('dx')
            base = (y & 1) * 0x2000 + (y >> 1) * 80
            if mode == 6:
                o = base + (x >> 3); b = 0x80 >> (x & 7)
                v = s.rd(0xB800, o, 1)[0]; v = (v | b) if al & 1 else (v & ~b)
                s.wr(0xB800, o, [v & 0xFF])
            else:
                o = base + (x >> 2); sh = (3 - (x & 3)) * 2
                v = s.rd(0xB800, o, 1)[0]; v = (v & ~(3 << sh)) | ((al & 3) << sh)
                s.wr(0xB800, o, [v & 0xFF])
        elif ah in (0x0B, 0x10, 0x11, 0x12, 0x1A, 0x1B, 0x1C, 0x13): pass

    def tty_put(s, ch):
        s.tty.append(chr(ch))
        if s.mode() not in (0, 1, 2, 3, 7): return
        cols = 40 if s.mode() in (0, 1) else 80
        r, c = s.cursor()
        if ch == 13: c = 0
        elif ch == 10: r += 1
        elif ch == 8: c = max(0, c - 1)
        elif ch == 7: pass
        else:
            s.wr(0xB800, (r * cols + c) * 2, [ch]); c += 1
            if c >= cols: c = 0; r += 1
        if r >= 25:
            v = s.rd(0xB800, cols * 2, cols * 2 * 24); s.wr(0xB800, 0, v + b'\x20\x07' * cols); r = 24
        s.set_cursor(r, c)

    def int11(s): s.w('ax', s.u16(0, 0x410))
    def int12(s): s.w('ax', s.u16(0, 0x413))

    def int13(s):
        ah, al, dl = s.r('ah'), s.r('al'), s.r('dl')
        d = s.drives[dl] if dl < 2 else None
        if ah == 0x00:
            for d in s.drives:
                if d: d.recal = True
            s.w('ax', 0); s.cf(0); return
        if d is None:
            s.w('ax', (s.r('ax') & 0xFF) | 0x8000); s.cf(1); return
        if ah == 0x08:
            s.w('bx', 4); s.w('cx', ((d.cyls - 1) << 8) | d.spt); s.w('dx', 0x0100 | (2 if s.drives[1] else 1))
            s.w('ax', 0); s.cf(0); return
        if ah == 0x15: s.w('ax', 0x0200); s.cf(0); return
        if ah == 0x16:
            if d.changed or d.no_changeline: d.changed = False; s.w('ax', 0x0600); s.cf(1)
            else: s.w('ax', 0); s.cf(0)
            return
        if ah in (0x17, 0x18): s.w('ax', 0); s.cf(0); return
        if ah in (2, 3, 4):
            cx, dx = s.r('cx'), s.r('dx')
            c, sct, h = (cx >> 8) | ((cx & 0xC0) << 2), cx & 63, dx >> 8
            es, bx = s.r('es'), s.r('bx'); lin = es * 16 + bx
            s.calls13.append((ah, dl, c, h, sct, al, '%05X' % lin))
            if al == 0 or sct == 0 or sct + al - 1 > d.spt or h >= d.heads or c >= d.cyls:
                s.w('ax', 0x0400); s.cf(1); return
            if ah == 3 and d.wp:
                s.w('ax', 0x0300); s.cf(1); return
            if ah != 4 and (lin & 0xFFFF) + al * 512 > 0x10000:
                s.w('ax', 0x0900); s.cf(1); return
            if ah != 4 and lin >= 0xA0000:
                s.w('ax', 0x0900); s.cf(1); return        # DMA can't reach video/ROM
            lba = (c * d.heads + h) * d.spt + sct - 1
            if ah == 2 and d.bad.intersection(range(lba, lba + al)):
                good = min(d.bad.intersection(range(lba, lba + al))) - lba
                s.mu.mem_write(lin, bytes(d.img[lba * 512:(lba + good) * 512]) + b'\xEE' * 512)   # (bad data DMA'd anyway)
                s.calls_bad = getattr(s, 'calls_bad', 0) + 1
                s.w('ax', 0x1000 | good); s.cf(1); return
            if ah == 2: s.mu.mem_write(lin, bytes(d.img[lba * 512:(lba + al) * 512]))
            elif ah == 3: d.img[lba * 512:(lba + al) * 512] = s.mu.mem_read(lin, al * 512)
            if s.disk_model == 'real':
                t0 = s.us; s.disk_time(d, c, sct, al); s.t13.append((t0, s.us, ah, c, h, sct, al))
            else: s.us += 2000 * al
            s.w('ax', al); s.cf(0); return
        s.w('ax', 0x0100); s.cf(1)

    def disk_time(s, d, c, sct, n):
        """Advance the clock as a real drive would for n sectors from (c, sct)."""
        lead, slot, data_end = d.timing()
        t0 = t = s.us + FD_BIOS_IN
        if t > d.motor_off_at:                  # motor was off: spin up
            d.ready_at = t + FD_SPINUP
        if d.recal:                             # after a reset: back to track 0
            t += d.cyl * FD_STEP + FD_SETTLE; d.cyl = 0; d.recal = False
        if c != d.cyl:
            t += abs(c - d.cyl) * FD_STEP + FD_SETTLE; d.cyl = c
        t = max(t, d.ready_at)
        start = lead + (sct - 1) * slot         # wait for the first sector's ID
        t += (start - t % FD_REV) % FD_REV
        t += (n - 1) * slot + data_end + FD_BIOS_OUT
        d.motor_off_at = t + FD_MOTOR_RUN
        d.ops += 1; d.busy_us += t - t0
        s.us = t

    def int14(s): s.w('ax', 0x8000 | (s.r('ax') & 0xFF))
    def int17(s):
        if s.r('ah') == 0: s.lpt.append(s.r('al'))
        s.w('ax', (s.r('ax') & 0xFF) | 0x9000)

    def int15(s):
        ax, ah = s.r('ax'), s.r('ah')
        if ax == 0xE440: s.w('cx', 1408); s.w('ax', 0); s.cf(0); return
        if ax == 0xE441: s.w('cx', 0); s.w('ax', 0); s.cf(0); return
        if ah == 0x4F: s.cf(1); return
        if ah == 0x88: s.w('ax', 0); s.cf(0); return
        if ah == 0x86:
            s.us += (s.r('cx') << 16 | s.r('dx')); s.cf(0); return
        if ah in (0x90, 0x91): s.w('ax', ax & 0xFF); s.cf(0); return
        s.w('ax', (ax & 0xFF) | 0x8600); s.cf(1)

    def int16(s):
        ah = s.r('ah')
        if ah in (0x00, 0x10):
            if s.keys: s.w('ax', s.keys.popleft())
            else:
                s.w('ip', s.r('ip') - 2); s.blocked = True; s.mu.emu_stop()
        elif ah in (0x01, 0x11):
            if s.keys: s.w('ax', s.keys[0]); s.zf(0)
            else: s.zf(1)
        elif ah in (0x02, 0x12): s.w('ax', s.r('ax') & 0xFF00)
        elif ah == 0x05: s.keys.append(s.r('cx')); s.w('ax', 0)

    def int18(s): s.stopped = 'INT 18h (ROM BASIC)'; s.mu.emu_stop()
    def int19(s): s.stopped = 'INT 19h (reboot)'; s.mu.emu_stop()

    def int1a(s):
        ah = s.r('ah'); bcd = lambda v: ((v // 10) << 4) | (v % 10)
        if ah == 0x00:
            if s.r('bx') & 0xFF00 == 0xBE00:            # BENCH's timing points
                s.marks.append((s.r('bx') & 0xFF, s.us, len(s.calls13), sum(c[5] for c in s.calls13)))
            t = struct.unpack('<I', s.rd(0, 0x46C, 4))[0]
            s.w('cx', t >> 16); s.w('dx', t); s.w('ax', 0)
        elif ah == 0x01:
            s.wr(0, 0x46C, struct.pack('<HH', s.r('dx'), s.r('cx')))
        elif ah == 0x02:
            n = s.now(); s.w('cx', (bcd(n.hour) << 8) | bcd(n.minute)); s.w('dx', bcd(n.second) << 8); s.cf(0)
        elif ah == 0x04:
            n = s.now()
            s.w('cx', (bcd(n.year // 100) << 8) | bcd(n.year % 100)); s.w('dx', (bcd(n.month) << 8) | bcd(n.day)); s.cf(0)
        elif ah in (0x03, 0x05):
            s.log.append('[RTC set %02X %04X %04X]' % (ah, s.r('cx'), s.r('dx'))); s.cf(0)

    # ---- running --------------------------------------------------------------
    def lin(s): return (s.r('cs') * 16 + s.r('ip')) & 0xFFFFF

    def boot(s, drive=0):
        """INT 19h: sector 0 of the drive to 0:7C00, jump with DL = drive."""
        s.mu.mem_write(0x7C00, bytes(s.drives[drive].img[:512]))
        s.w('cs', 0); s.w('ip', 0x7C00); s.w('dx', drive); s.w('ss', 0); s.w('sp', 0x7C00)
        s.w('flags', 0x202)

    def run(s, n=20000):
        if s.stopped or s.crash: return False
        s.deliver_irqs()
        s.blocked = False
        try:
            s.mu.emu_start(s.lin(), 0xFFFFFFFF, count=n)
        except UcError as e:
            s.crash = 'CPU %s at %04X:%04X' % (e, s.r('cs'), s.r('ip')); return False
        a, z = s.last_blk
        here = s.lin()
        s.halted = a + z == here and s.rd(0, here - 1, 1)[0] == 0xF4
        if (s.blocked or s.halted) and not s.deliverable():
            s.sleep_to_tick()                   # (an IRQ still waiting goes first,
        return not (s.stopped or s.crash)       #  as a real PIC would after IRET)

    def deliverable(s):
        return bool(s.r('flags') & 0x200) and any(not (s.pic_mask & (1 << i)) for i in s.irq_pending)

    def run_until(s, cond, sim_s=10.0):
        end = s.us + sim_s * 1e6
        while s.us < end:
            if cond(): return True
            if not s.run(): break
        return cond()

    def run_for(s, sim_s):
        end = s.us + sim_s * 1e6
        while s.us < end and s.run(): pass

    # ---- screens ----------------------------------------------------------------
    def text_screen(s):
        v = s.rd(0xB800, 0, 4000)
        return '\n'.join(''.join(chr(v[(r * 80 + c) * 2]) if 32 <= v[(r * 80 + c) * 2] < 127 else ' '
                                 for c in range(80)).rstrip() for r in range(25))

    def png(s, path, font=None, scale=2):
        from PIL import Image
        AMB, BG = (255, 170, 50), (28, 12, 0)
        m = s.mode()
        if m in (0x40, 0x48, 0x74):
            vram = s.rd(0xB800, 0, 0x8000)
            im = Image.new('RGB', (640, 400)); px = im.load()
            for y in range(400):
                base = (y & 3) * 0x2000 + (y >> 2) * 80
                for xb in range(80):
                    v = vram[base + xb]
                    for b in range(8): px[xb * 8 + b, y] = AMB if v & (0x80 >> b) else BG
        elif m in (4, 5, 6):
            vram = s.rd(0xB800, 0, 0x4000)
            im = Image.new('RGB', (640, 400)); px = im.load()
            for y in range(200):
                base = (y & 1) * 0x2000 + (y >> 1) * 80
                for xb in range(80):
                    v = vram[base + xb]
                    for b in range(8):
                        if m == 6: on = v & (0x80 >> b)
                        else: on = (v >> (6 - (b // 2) * 2)) & 3
                        c = AMB if on else BG
                        px[xb * 8 + b, 2 * y] = c; px[xb * 8 + b, 2 * y + 1] = c
        else:
            im = Image.new('RGB', (640, 400), BG); px = im.load()
            v = s.rd(0xB800, 0, 4000)
            for r in range(25):
                for c in range(80):
                    ch, at = v[(r * 80 + c) * 2], v[(r * 80 + c) * 2 + 1]
                    g = font.get(ch) if font else None
                    if g is None: g = font.get(0x3F) if font and ch >= 0x20 else bytes(16)
                    inv = (at & 0x70) and not (at & 0x07)
                    for y in range(16):
                        bits = g[y] ^ (0xFF if inv else 0)
                        for b in range(8):
                            px[c * 8 + b, r * 16 + y] = AMB if bits & (0x80 >> b) else BG
        im.resize((640 * scale // 2 * 2, 400 * scale // 2 * 2), Image.NEAREST).save(path)


def load_font(path):
    """FONT.INC (NASM db lines, ASCII 32-127) -> {code: 16 bytes}."""
    import re
    rows = [l for l in open(path) if l.strip().startswith('db ')]
    out = {}
    for i, l in enumerate(rows):
        vals = re.findall(r'([0-9A-Fa-f]+)h', l.split(';')[0])
        if len(vals) == 16: out[0x20 + i] = bytes(int(v, 16) for v in vals)
    return out
