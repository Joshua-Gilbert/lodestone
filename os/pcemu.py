"""A GRiDCase 1520 as seen by an operating system: x86 real mode (unicorn)
with only a BIOS - no DOS.  Used to test the Lodestone kernel, which provides
DOS itself.

  * BIOS services in Python (INT 10h, 11h, 12h, 13h, 14h, 15h, 16h, 17h,
    18h, 19h, 1Ah) behind F000 stubs; every other vector is whatever the
    guest installs (the BIOS leaves 60h-67h null, like a real AT BIOS).
  * Timer IRQ 0 through the IVT at 18.2 Hz into a real-code BIOS INT 08h
    handler that counts 40:6C and calls INT 1Ch; HLT sleeps to the next IRQ.
  * Floppies A: and B: as image files behind INT 13h with the real
    controller's limits: no track crossing, no 64 KB DMA crossing, ROM
    can't be a DMA buffer (the EMS frame can).  Change line per drive.
  * Video: text modes (B800 cells), GRiD mode 40h (640x400 1 bpp),
    CGA modes 4/6 memory; PNG rendering.
  * uPD7210 at 02E1h + n*400h (any object with read/write), COM2 serial
    mouse with IRQ3, PIT channel 0, port 61h refresh toggle, panel 7F8h.
  * EMS (ems_pages > 0): the 1520's expanded memory as GRiD's EMM.SYS
    drives it - a 64 KB frame at E000h in 4 windows of 16 KB, window w's
    page register at port 0258h + w*4000h (readable; 80h + raw page maps
    it, 0 unmaps and the window reads FFh), INT 15h E442h says "EMS mode".
    Raw pages past the board's are absent, or with ems_alias the same
    memory again (a partly decoded board), as the kernel's scan must see.

Time: 4 us per executed basic block (about a 10 MHz 286).
"""
import collections, ctypes, datetime, os, struct
from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR, UC_HOOK_INSN, UC_HOOK_BLOCK, UC_PROT_ALL
from unicorn import x86_const as X

TICK_US = 1e6 * 65536 / 1193182
BLOCK_US = 4.0
KB_START, KB_END = 0x1E, 0x3E   # the BIOS's keyboard buffer in 40:0 (40:80h, 40:82h)
# per-iteration cost of REP string ops, from RAMSPEED on the 1520 (~10 MHz):
# rep stosw 6133 KB/s, rep lodsw 3738 KB/s, rep movsw 3074 KB/s
REP_US = {0xA4: 0.45, 0xA5: 0.65, 0xAA: 0.25, 0xAB: 0.33, 0xAC: 0.4, 0xAD: 0.53,
          0xA6: 1.0, 0xA7: 1.1, 0xAE: 0.9, 0xAF: 1.0, 0x6C: 0.6, 0x6D: 0.7, 0x6E: 0.6, 0x6F: 0.7}
# an EMS page register read or written (IN/OUT DX on the 1520's I/O bus):
# a 286's IN/OUT (5 / 3 clocks at ~10 MHz) plus an 8-bit bus cycle with its
# wait states, about 1 us; the rest of the block is counted as usual.  (Not
# measured on the 1520 yet: BENCH on M: there checks it; RAMSPEED's 0.15 ms
# for a page switch is GRiD's EMM.SYS through INT 67h, mostly software.)
EMS_IO_US = 1.0
STUB = 0xF000
EMS_FRAME = 0xE0000
EMS_PAGE = 0x4000
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
        s.empty = False                 # no disk in the drive: time-out
    def save(s, path=None):
        open(path or s.path, 'wb').write(s.img)


class Ata:
    """The 1520's internal hard disk: an AT-bus drive at 1F0h-1F7h, as a
    1989 Conner answers (for HDPROBE).  (Not 3F6h: on the 1520 that port
    doesn't reach the drive.)  Commands finish at once unless they fail
    mechanically.
      model, cyls, heads, spt: what IDENTIFY says (identify=False: ABRT)
      rpm: the index pulse in the status (0: not turning)
      formatted: True, False, or the set of cylinders that have sector IDs
      stuck: busy for ever (status 80h, writes ignored)
      tk0: recalibrate fails with track 0 not found
      diag: the code after 90h (01h: passed)
      data: {LBA: 512 bytes}; the rest reads as zeros
      irq: the drive raises IRQ 14 when a command ends (False: a dead line)
      mech_fail: it can't find its way on the disk (as Joshua's CP30104H,
        2026-10-07): recalibrate aborts, a seek never completes (BSY drops,
        DSC doesn't come), reads end IDNF; each failure after fail_ms
      frees: mech_fail ends after this many recalibrates (exercise worked)
      unready: busy for this many seconds from the first look (spin-up)
      disk: the whole disk, LBA order (data overrides it); written by
        WRITE SECTORS (30h) as a bytearray (s.disk)
      bad: LBAs that don't read (UNC); a read of several sectors stops
        there, with the ones before it transferred
      stick_at: busy for good from this read command on (stuck again)
      badw: LBAs that don't take a write (IDNF once the data is in; the
        command ends there); s.wfails counts them.  A test may change it
      cut: the power goes during this WRITE SECTORS command (1 = the
        first): half its sectors land (none of one), then the PC stops
    While busy, every register reads the status and writes go nowhere."""
    BSY, DRDY, DSC, DRQ, ERR, IDX = 0x80, 0x40, 0x10, 0x08, 0x01, 0x02

    def __init__(s, model='Conner Peripherals 40MB - CP3044', cyls=977, heads=5, spt=17, rpm=3486,
                 formatted=True, stuck=False, tk0=False, diag=0x01, identify=True, data=None,
                 serial='CP3044-123456', firmware='1.03', irq=True, mech_fail=False, unready=0,
                 fail_ms=0, frees=0, disk=None, bad=(), stick_at=None, badw=(), cut=None, timed=False,
                 seek_ms=(4.0, 0.02), cmd_ms=0.5, pio_us=1.0, lookahead=False):
        s.model, s.cyls, s.heads, s.spt, s.rpm = model, cyls, heads, spt, rpm
        s.formatted, s.stuck, s.tk0, s.diag, s.identify = formatted, stuck, tk0, diag, identify
        s.serial, s.firmware = serial, firmware
        s.data = dict(data or {})
        s.reg = {1: diag, 2: 1, 3: 1, 4: 0, 5: 0, 6: 0xA0}
        s.st = s.DRDY | s.DSC
        s.buf = b''; s.pos = 0
        s.cmds = []                                     # (command, C, H, S) as sent
        s.irq = irq; s.pc = None
        s.mech_fail, s.unready, s.fail_ms, s.frees = mech_fail, unready, fail_ms, frees
        s.first = None; s.busy_until = 0; s.recals = 0
        s.disk = bytearray(disk) if disk is not None else None
        s.bad, s.stick_at, s.pend, s.reads = set(bad), stick_at, None, 0
        s.wq = []                                       # sectors still to come in (LBA)
        s.wbuf = bytearray(); s.writes = []             # (LBA, sectors) per command
        s.badw, s.wfails = set(badw), 0
        s.cut, s.wcmds, s.cutting = cut, 0, False
        # timed: seeks and rotation cost time (for benchmarks; off in the
        # functional tests).  A seek of d cylinders takes seek_ms[0] +
        # seek_ms[1] * d ms; a command cmd_ms; sector n of a track passes
        # under the head at (n - 1) / spt of a turn.  Reads stream into the
        # drive's buffer at the disk's pace (each sector ready as it has
        # passed); writes are taken into the buffer at once and the command
        # ends when the last sector has been written.  pio_us: each data word
        # moved by the CPU.  lookahead: the drive keeps the sectors it read
        # and goes on reading to the end of that track into its buffer; a
        # read of those is answered from there, a new command ends the
        # look-ahead, and a write empties the buffer.
        s.timed, s.seek_ms, s.cmd_ms, s.pio_us = timed, seek_ms, cmd_ms, pio_us
        s.lookahead, s.la = lookahead, {}
        s.cyl = 0; s.ready = []; s.wsec = []; s.wt = 0

    def power_cut(s):
        s.stuck = True
        if s.pc: s.pc.stopped = 'power cut'; s.pc.mu.emu_stop()

    def intr(s):
        if s.irq and s.pc: s.pc.irq_pending.add(14)

    @staticmethod
    def text(t, n):                                     # an ATA string: n words, bytes swapped
        b = t.encode().ljust(2 * n)[:2 * n]
        return bytes(b[i ^ 1] for i in range(2 * n))

    def ident_block(s):
        w = [0] * 256
        w[0] = 0x0A5A; w[1] = s.cyls; w[3] = s.heads; w[4] = 20160; w[5] = 594; w[6] = s.spt
        w[20] = 1; w[21] = 0x20; w[22] = 4
        b = bytearray(struct.pack('<256H', *w))
        b[20:40] = s.text(s.serial, 10); b[46:54] = s.text(s.firmware, 4); b[54:94] = s.text(s.model, 20)
        return bytes(b)

    def _seek(s, us, c):
        d = abs(c - s.cyl); s.cyl = c
        return us + (s.seek_ms[0] + s.seek_ms[1] * d) * 1000 if d else us

    def _slot(s, t, n):                                 # when sector n next starts under the head
        rev = 60e6 / s.rpm; st = rev / s.spt
        ph = (n - 1) * st
        k = -(-(t - ph - 0.01) // rev)                 # (0.01 us: rounding, not a lost turn)
        return ph + k * rev, st

    def _chs(s, lba):
        return lba // (s.heads * s.spt), lba // s.spt % s.heads, lba % s.spt + 1

    def busy(s, us):
        if s.stuck: return True
        if s.timed and s.st & s.DRQ and s.ready and not s.wq:
            i = s.pos // 512
            if i < len(s.ready) and us < s.ready[i]: return True
        if s.first is None: s.first = us
        return us - s.first < s.unready * 1e6 or us < s.busy_until

    def status(s, us):
        if s.busy(us): return s.BSY
        st = s.st
        if s.rpm:
            per = 60e6 / s.rpm
            if us % per < per * 0.03: st |= s.IDX
        return st

    def sector(s, lba):
        if lba in s.data: return s.data[lba]
        if s.disk is not None and (lba + 1) * 512 <= len(s.disk): return bytes(s.disk[lba * 512:(lba + 1) * 512])
        return bytes(512)

    def has_sector(s, c, h, n):
        if not (c < s.cyls and h < s.heads and 1 <= n <= s.spt): return False
        return s.formatted if isinstance(s.formatted, bool) else c in s.formatted

    def read(s, port, size, us):
        if port == 0x1F0:
            if not s.st & s.DRQ or s.busy(us): return 0xFFFF if size == 2 else 0xFF
            v = s.buf[s.pos] | (s.buf[s.pos + 1] << 8 if size == 2 else 0)
            s.pos += size
            if s.pos >= len(s.buf):
                s.st &= ~s.DRQ
                if s.pend: s.reg[1] = s.pend; s.st |= s.ERR; s.pend = None
            return v
        if port == 0x1F7 and s.pc: s.pc.irq_pending.discard(14)     # (reading it ends INTRQ)
        if port == 0x1F7 or s.busy(us): return s.status(us)
        return s.reg.get(port - 0x1F0, 0)

    def write(s, port, val, us, size=1):
        if s.busy(us): return
        if port == 0x1F0 and s.wq and s.st & s.DRQ:      # a sector's data coming in
            s.wbuf += bytes([val & 0xFF, val >> 8]) if size == 2 else bytes([val & 0xFF])
            if len(s.wbuf) >= 512:
                lba = s.wq.pop(0); sec = bytes(s.wbuf[:512])
                s.wbuf = bytearray()
                if lba in s.badw:
                    s.wq = []; s.wfails += 1; s.reg[1] = 0x10; s.st = s.DRDY | s.DSC | s.ERR
                    s.intr(); return
                if s.disk is not None and (lba + 1) * 512 <= len(s.disk): s.disk[lba * 512:(lba + 1) * 512] = sec
                s.data.pop(lba, None)
                if s.timed:                             # on the disk when it next passes the head
                    c, h, n = s._chs(lba)
                    t = s._seek(max(s.wt, us), c)
                    t0, st = s._slot(t, n); s.wt = t0 + st
                    if not s.wq: s.busy_until = s.wt
                if not s.wq and s.cutting: return s.power_cut()
                if not s.wq: s.st = s.DRDY | s.DSC
                s.intr()
            return
        if port != 0x1F7:
            if port != 0x1F0: s.reg[port - 0x1F0] = val
            return
        c = s.reg[4] | s.reg[5] << 8; h = s.reg[6] & 15; n = s.reg[3]
        s.cmds.append((val, c, h, n))
        s.ready = []
        ok = s.DRDY | s.DSC
        s.intr()
        def fail(err, slow=False):
            s.reg[1] = err; s.st = ok | s.ERR
            if slow: s.busy_until = us + s.fail_ms * 1000
        if val == 0xEC:
            if not s.identify: return fail(0x04)
            s.buf = s.ident_block(); s.pos = 0; s.st = ok | s.DRQ
        elif val == 0x90:
            s.reg[1] = s.diag; s.st = ok
        elif val == 0x91:
            s.st = ok
        elif (val & 0xF0) == 0x70:
            s.st = s.DRDY if s.mech_fail else ok        # (DSC never comes)
        elif (val & 0xF0) == 0x10:
            s.recals += 1
            if s.tk0: return fail(0x02)
            if s.mech_fail:
                if s.recals == s.frees: s.mech_fail = False
                return fail(0x04, True)
            s.st = ok
        elif val in (0x30, 0x31):
            s.wq = []; s.wbuf = bytearray()
            for i in range(s.reg[2] or 256):
                if not s.has_sector(c, h, n): break
                s.wq.append((c * s.heads + h) * s.spt + n - 1)
                n += 1
                if n > s.spt: n = 1; h += 1
                if h >= s.heads: h = 0; c += 1
            if not s.wq: return fail(0x10)
            s.writes.append((s.wq[0], len(s.wq)))
            if s.timed: s.wt = s._seek(us + s.cmd_ms * 1000, c); s.la = {}
            s.wcmds += 1
            if s.cut == s.wcmds:
                s.wq = s.wq[:len(s.wq) // 2]; s.cutting = True
                if not s.wq: return s.power_cut()
            s.st = ok | s.DRQ
        elif val in (0x20, 0x21):
            s.reads += 1
            if s.stick_at and s.reads >= s.stick_at: s.stuck = True; return
            if s.mech_fail: return fail(0x10, True)
            buf = []; s.pend = None
            for i in range(s.reg[2] or 256):           # (on through heads and cylinders)
                if not s.has_sector(c, h, n): s.pend = 0x10; break
                lba = (c * s.heads + h) * s.spt + n - 1
                if lba in s.bad: s.pend = 0x40; break
                buf.append(s.sector(lba))
                n += 1
                if n > s.spt: n = 1; h += 1
                if h >= s.heads: h = 0; c += 1
            if not buf: e = s.pend; s.pend = None; return fail(e)
            s.buf = b''.join(buf); s.pos = 0; s.st = ok | s.DRQ
            s.ready = []
            if s.timed:
                t = us + s.cmd_ms * 1000
                lba = (c * s.heads + h) * s.spt + n - 1 - len(buf)
                la, s.la = s.la, {}
                for i in range(len(buf)):
                    if lba + i in la:                   # in the buffer already
                        t = max(t, la[lba + i]); s.ready.append(t); continue
                    la = {}                             # (a new command ends the look-ahead)
                    cc, hh, nn = s._chs(lba + i)
                    t = s._seek(t, cc)
                    t0, st = s._slot(t, nn); t = t0 + st
                    s.ready.append(t)
                if s.lookahead:
                    s.la = {lba + i: r for i, r in enumerate(s.ready)}     # (kept in the buffer)
                    cc, hh, nn = s._chs(lba + len(buf) - 1)
                    st = 60e6 / s.rpm / s.spt
                    for k in range(1, s.spt - nn + 1):
                        s.la[lba + len(buf) - 1 + k] = t + k * st
        else:
            fail(0x04)


class PC:
    def __init__(s, a=None, b=None, chip=None, start=datetime.datetime(2026, 10, 4, 21, 30, 0), mem_kb=640,
                 disk_model='flat', ems_pages=0, ems_alias=False, ata=None, float_bus=False, roms=None):
        s.mu = mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x110000)
        s.ems_pages = ems_pages; s.ems_alias = ems_alias
        s.ata = ata                     # the internal hard disk (Ata), or none: FFh
        s.float_bus = float_bus         # no drive, and its ports read what's left on the bus
        if ata: ata.pc = s
        if ems_pages:
            # the board's memory, and what each window shows: a page of it
            # (mem_map_ptr, so two windows on one page are the same bytes) or,
            # when it is off, nothing (MMIO: reads FFh, writes go nowhere)
            s.ems_store = ctypes.create_string_buffer(ems_pages * EMS_PAGE)
            s.ems_reg = [0, 0, 0, 0]
            mu.mem_unmap(EMS_FRAME, 4 * EMS_PAGE)
            for w in range(4): s.ems_map(w, first=True)
        s.drives = [Floppy(a) if a is not None else None, Floppy(b) if b is not None else None]
        s.disk_model = disk_model       # 'flat' = 2 ms a sector; 'real' = seeks, rotation, motor
        s.marks = []                    # (BX, us) for INT 1Ah AH=0 calls with BX = BExxh
        s.chip = chip
        s.us = 0.0; s.next_tick = TICK_US; s.next_event = TICK_US
        s.due_at = float('inf'); s.on_due = None
        s.irq_pending = set(); s.pic_mask = 0xB8
        s.isr = 0; s.pic_rr = 2         # in service (EOI ends it); OCW3: what port 20h reads
        s.pic2_mask = 0xFF              # the slave PIC (IRQ 8-15, through IRQ 2)
        s.soft = []                     # INTs the BIOS's IRQ handlers would raise (5: Shift-PrtSc)
        s.keys = collections.deque(); s.tty = []; s.log = []; s.lpt = []
        s.calls13 = []; s.ints = collections.Counter(); s.t13 = []
        s.stopped = None; s.crash = None; s.halted = False; s.blocked = False
        s.last_blk = (0, 0); s.pit_latch = None; s.pit_hi = False; s.pit_mode = 3
        s.clock0 = start
        s.uart = {'lcr': 0, 'mcr': 0, 'ier': 0, 'rx': [], 'scr': 0, 'dll': 0}
        s.moves = []
        s.watch = None
        s.ccr = 0x30; s.on_ccr = None   # CGA colour select (3D9h), as written; on_ccr(value) at each write
        # CMOS: Joshua's 1520 (CMOS128.BIN) if it's here, else a 1.44 MB A:
        cm = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'CMOS128.BIN')
        s.cmos = bytearray(open(cm, 'rb').read()) if os.path.exists(cm) else bytearray(128)
        if not os.path.exists(cm): s.cmos[0x10] = 0x40; s.cmos[0x15:0x17] = b'\x80\x02'
        s.cidx = 0
        s.mem_kb = mem_kb
        # the application-ROM sockets: socket -> 128 KB image.  INT 15h E400-E404
        # answer as the 1520's BIOS does (tools/simgrid.py runs the real one:
        # tests/test_rom.py checks the two agree); while an image is mapped,
        # A000-BFFF is the ROM and video memory is hidden
        s.roms = dict(roms or {})
        s.rom_mapped = None; s.rom_saved = None; s.rom_maps = 0
        s.bios_init()
        mu.hook_add(UC_HOOK_INTR, s.intr)
        mu.hook_add(UC_HOOK_INSN, s.hin, None, 1, 0, X.UC_X86_INS_IN)
        mu.hook_add(UC_HOOK_INSN, s.hout, None, 1, 0, X.UC_X86_INS_OUT)
        mu.hook_add(UC_HOOK_BLOCK, s.blk)

    def bios_init(s):
        """What the BIOS's POST leaves: the IVT, the BIOS data area, the
        screen, the reset jump (also after Ctrl-Alt-Del, see warm_boot)."""
        # IVT: BIOS services via stubs, IRQs via real code, 60h-67h null
        for n in range(256):
            s.mu.mem_write(n * 4, struct.pack('<HH', n * 8, STUB))
            s.mu.mem_write(STUB * 16 + n * 8, bytes([0xCD, n, 0xCA, 0x02, 0x00]))
        s.mu.mem_write(STUB * 16 + 0x1000, INT08)
        s.mu.mem_write(STUB * 16 + 0x1100, IRQEOI)
        s.mu.mem_write(STUB * 16 + 0x1200, IRET)
        s.mu.mem_write(8 * 4, struct.pack('<HH', 0x1000, STUB))
        for n in list(range(9, 0x10)) + list(range(0x70, 0x78)):
            s.mu.mem_write(n * 4, struct.pack('<HH', 0x1100, STUB))
        for n in (0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x0, 0x1, 0x3, 0x4, 0x5):
            s.mu.mem_write(n * 4, struct.pack('<HH', 0x1200, STUB))
        for n in range(0x20, 0x100):
            if n not in (0x40, 0x41, 0x46, 0x4A):
                s.mu.mem_write(n * 4, struct.pack('<HH', 0x1200, STUB))
        for n in range(0x60, 0x68):
            s.mu.mem_write(n * 4, b'\0\0\0\0')
        # BDA
        equip = 0x4423 | (0x40 if s.drives[1] else 0)
        s.mu.mem_write(0x410, struct.pack('<H', equip))
        s.mu.mem_write(0x413, struct.pack('<H', s.mem_kb))
        s.mu.mem_write(0x41A, struct.pack('<HH', 0x1E, 0x1E)); s.kbd_mirror = []
        s.mu.mem_write(0x480, struct.pack('<HH', KB_START, KB_END))
        s.mu.mem_write(0x449, bytes([3])); s.mu.mem_write(0x44A, struct.pack('<HH', 80, 4096))
        s.mu.mem_write(0x44E, b'\0\0'); s.mu.mem_write(0x450, bytes(16)); s.mu.mem_write(0x460, b'\x07\x06\x00')
        s.mu.mem_write(0x463, struct.pack('<H', 0x3D4)); s.mu.mem_write(0x484, bytes([24]))
        secs = s.clock0.hour * 3600 + s.clock0.minute * 60 + s.clock0.second
        s.mu.mem_write(0x46C, struct.pack('<I', int(secs * 1193182 / 65536)))
        s.mu.mem_write(0xFFFF0, b'\xEA\x5B\xE0\x00\xF0')        # the reset jump, as in the ROM (FFFF:1 isn't 0)
        s.mu.mem_write(0xFFFF5, b'10/25/89'); s.mu.mem_write(0xFFFFE, b'\xFC')
        s.mu.mem_write(0xF0000 + 0xE05B, b'\xCD\x19')         # the POST: warm_boot
        s.wr(0xB800, 0, b'\x20\x07' * 2000)

    def warm_boot(s, ems='keep'):
        """Ctrl-Alt-Del (or a jump to FFFF:0 with 0:472 = 1234h): the warm
        POST - the BIOS's vectors and data area again, the PICs, the screen,
        EMS's page registers off - then INT 19h.  Memory is not tested, so it
        keeps what it held.  EMS: 'keep' (what EMSKEEP checks on the 1520),
        'lose' (every page different afterwards), or a set of board pages
        that lose their contents."""
        if s.ems_pages:
            import random
            r = random.Random(1234)
            lose = range(s.ems_pages) if ems == 'lose' else (() if ems == 'keep' else ems)
            for p in lose:
                s.ems_store[p * EMS_PAGE:(p + 1) * EMS_PAGE] = bytes(r.getrandbits(8) for _ in range(EMS_PAGE))
            s.ems_reg = [0, 0, 0, 0]
            for w in range(4): s.ems_map(w)
        s.bios_init()
        s.irq_pending = set(); s.soft = []; s.isr = 0; s.pic_rr = 2
        s.pic_mask = 0xB8; s.pic2_mask = 0xFF
        s.keys.clear(); s.blocked = False; s.halted = False
        s.uart = {'lcr': 0, 'mcr': 0, 'ier': 0, 'rx': [], 'scr': 0, 'dll': 0}
        s.warm_boots = getattr(s, 'warm_boots', 0) + 1
        s.boot(0)

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

    def pit_read(s):
        """Latch channel 0.  Mode 3 (the BIOS's) counts down by 2, twice a
        tick; mode 2 (pit_init in tools/timing.inc) once, by 1, from the
        tick."""
        if s.pit_mode == 2:
            n = int((s.us - (s.next_tick - TICK_US)) * 1.193182) % 65536
            s.pit_latch = (65536 - n) & 0xFFFF
        else:
            n = int(s.us * 1.193182) % 32768
            s.pit_latch = (65536 - 2 * n) & 0xFFFF
        s.pit_hi = False

    def sleep_to_tick(s):
        s.us = max(s.us, s.next_tick); s.on_time()

    def deliver_irqs(s):
        """Every unmasked pending IRQ, highest priority first, as a PIC would:
        the next one is serviced as soon as the one before IRETs.  The frames
        are stacked lowest priority first, so the IRQ 0 handler's IRET goes
        straight into the next handler (with IF clear, as its INT would
        leave it), and the last one returns to the program.  Delivering only
        IRQ 0 per run() starved the mouse while long INT 13h calls (which
        the emulator does in one step) kept a timer tick pending."""
        if s.soft and s.r('flags') & 0x200:     # as INT 9 does after its EOI
            n = s.soft.pop(0)
            off, seg = struct.unpack('<HH', s.rd(0, n * 4, 4))
            s.push(s.r('flags')); s.push(s.r('cs')); s.push(s.r('ip'))
            s.w('flags', s.r('flags') & ~0x300)
            s.w('cs', seg); s.w('ip', off)
            return
        if not (s.r('flags') & 0x200) or not s.irq_pending: return
        due = [i for i in sorted(s.irq_pending) if s.unmasked(i)]
        if not due: return
        first = True
        for irq in reversed(due):
            s.irq_pending.discard(irq)
            s.isr |= 1 << (irq if irq < 8 else 2)
            off, seg = struct.unpack('<HH', s.rd(0, (8 + irq if irq < 8 else 0x68 + irq) * 4, 4))
            fl = s.r('flags')
            s.push(fl if first else fl & ~0x300); s.push(s.r('cs')); s.push(s.r('ip'))
            s.w('flags', fl & ~0x300)
            s.w('cs', seg); s.w('ip', off)
            first = False
        return                                  # IF is now clear

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
            if s.pit_latch is None: s.pit_read()
            v = s.pit_latch
            if not s.pit_hi: s.pit_hi = True; return v & 0xFF
            s.pit_latch = None; return v >> 8
        if port == 0x61: return (int(s.us / 15.085) & 1) << 4
        if port == 0x71: return s.cmos_read(s.cidx)
        if port == 0x21: return s.pic_mask
        if port == 0xA1: return s.pic2_mask
        if port == 0x20: return s.isr if s.pic_rr == 3 else 0
        if port == 0x7F8: return 0xFD
        if port == 0x6F8: return 0x90                   # drive backplane 9 (the 1520's, GRIDPROBE)
        if s.ata and 0x1F0 <= port <= 0x1F7:
            if port == 0x1F0 and s.ata.timed: s.us += s.ata.pio_us         # (REP INSW: one hook a word)
            return s.ata.read(port, size, s.us)
        if s.float_bus and (0x1F0 <= port <= 0x1F7 or port == 0x3F6):   # as Joshua's 1520 reads
            b = s.rd(s.r('cs'), s.r('ip') + 2, 2)                       #  (2026-10-07): code bytes
            return b[0] | b[1] << 8 if size == 2 else b[0]              #  just prefetched
        if port == 0x3DA:
            return 0x08 if int(s.us / 1000) % 16 == 0 else 0x00
        if 0x2F8 <= port <= 0x2FF: return s.uart_in(port - 0x2F8)
        if s.ems_pages and (port & 0x3FFF) == 0x258: s.us += EMS_IO_US; return s.ems_reg[port >> 14]
        if s.chip is not None and (port & 0x3FF) == 0x2E1 and port < 0x2000:
            return s.chip.read(port >> 10)
        return 0xFF

    # ---- EMS board ------------------------------------------------------------
    def ems_page(s, v):
        """The board page a page-register value shows, or None (window off,
        or a raw page this board doesn't have)."""
        if not v & 0x80: return None
        r = v & 0x7F
        if r < s.ems_pages: return r
        return r % s.ems_pages if s.ems_alias else None

    def ems_map(s, w, first=False):
        base = EMS_FRAME + w * EMS_PAGE
        p = s.ems_page(s.ems_reg[w])
        if not first: s.mu.mem_unmap(base, EMS_PAGE)
        if p is None:
            s.mu.mmio_map(base, EMS_PAGE, lambda uc, off, size, ud: (1 << 8 * size) - 1, None,
                          lambda uc, off, size, val, ud: None, None)
        else:
            s.mu.mem_map_ptr(base, EMS_PAGE, UC_PROT_ALL, ctypes.addressof(s.ems_store) + p * EMS_PAGE)

    def ems_read(s, page, off, n):
        """Bytes of a board page, mapped or not."""
        a = page * EMS_PAGE + off
        return bytes(s.ems_store[a:a + n])

    # Floppy DMA reaches the frame as the CPU does, through each window's
    # page (the 1520 does this: EMSTEST "floppy DMA into the frame: works").
    # A window that is off reads FFh and keeps nothing.
    def in_frame(s, lin, n):
        return bool(s.ems_pages) and EMS_FRAME <= lin and lin + n <= EMS_FRAME + 4 * EMS_PAGE

    def frame_runs(s, lin, n):
        """(offset in the run, board page or None, offset in the page, bytes)
        for each window [lin, lin + n) passes through."""
        o = 0
        while o < n:
            f = lin + o - EMS_FRAME
            k = min(EMS_PAGE - f % EMS_PAGE, n - o)
            yield o, s.ems_page(s.ems_reg[f // EMS_PAGE]), f % EMS_PAGE, k
            o += k

    def dma_write(s, lin, data):
        if not s.in_frame(lin, len(data)):
            s.mu.mem_write(lin, data)
            # Unicorn keeps code it has translated from these bytes: a
            # program loaded where another one ran would run the old one's
            # code (a real DMA transfer has nothing to keep).  The frame
            # below is EMS: its bytes reach memory through mapping.
            s.mu.ctl_remove_cache(lin, lin + len(data))
            return
        for o, p, f, k in s.frame_runs(lin, len(data)):
            if p is not None: s.ems_store[p * EMS_PAGE + f:p * EMS_PAGE + f + k] = data[o:o + k]

    def dma_read(s, lin, n):
        if not s.in_frame(lin, n): return s.mu.mem_read(lin, n)
        out = bytearray()
        for o, p, f, k in s.frame_runs(lin, n):
            out += b'\xFF' * k if p is None else s.ems_store[p * EMS_PAGE + f:p * EMS_PAGE + f + k]
        return out

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
        if s.ata and port == 0x1F0:
            if s.ata.timed: s.us += s.ata.pio_us
            return s.ata.write(port, val & 0xFFFF, s.us, size)   # (a word: OUTSW)
        val &= 0xFF
        if port == 0x70: s.cidx = val & 0x7F; return
        if port == 0x71:
            if s.cidx >= 0x0E: s.cmos[s.cidx] = val
            return
        if port == 0x43:
            if (val & 0xF0) == 0: s.pit_read()
            elif (val & 0xF0) == 0x30: s.pit_mode = (val >> 1) & 3     # (channel 0: 2 or 3)
            return
        if port == 0x21: s.pic_mask = val; return
        if port == 0xA1: s.pic2_mask = val; return
        if s.ata and 0x1F0 <= port <= 0x1F7: return s.ata.write(port, val, s.us, size)
        if port == 0x20:
            if val == 0x20: s.isr &= s.isr - 1          # the highest priority's EOI
            elif val & 0xF8 == 0x60: s.isr &= ~(1 << (val & 7))
            elif val & 0x9A == 0x0A: s.pic_rr = val & 3  # OCW3: read IRR / ISR
            return
        if 0x2F8 <= port <= 0x2FF: return s.uart_out(port - 0x2F8, val)
        if s.ems_pages and (port & 0x3FFF) == 0x258:
            s.us += EMS_IO_US; s.ems_reg[port >> 14] = val; s.ems_map(port >> 14); return
        if s.chip is not None and (port & 0x3FF) == 0x2E1 and port < 0x2000:
            s.chip.write(port >> 10, val)
        if port == 0x3D9: s.set_ccr(val)

    def set_ccr(s, v):
        s.ccr = v
        if s.on_ccr: s.on_ccr(v)

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
            # the colour select, as the 1520's BIOS sets it (int10.asm): 30h,
            # 3Fh in mode 6 (white on black); kept in 40:66h, and not written
            # to the port above the CGA modes
            v = 0x3F if m == 6 else 0x30
            s.wr(0, 0x466, [v])
            if m <= 6: s.set_ccr(v)
            s.log.append('[mode %02Xh]' % m)
        elif ah == 0x01: s.wr(0, 0x460, [s.r('cl'), s.r('ch')])
        elif ah == 0x02: s.set_cursor(s.r('dh'), s.r('dl'))
        elif ah == 0x03:
            r, c = s.cursor(); s.w('dx', (r << 8) | c); s.w('cx', 0x0607)
        elif ah == 0x05 and text:       # the page shown: the BIOS keeps it and its
            s.wr(0, 0x462, [al & 7])    #  start (40:62h, 40:4Eh); the text model
            s.wr(0, 0x44E, struct.pack('<H', (al & 7) * (0x800 if cols == 40 else 0x1000)))   # stays page 0's
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
        elif ah == 0x0B:                # (the 1520's VidSetPalette): BH=0 the
            v = s.rd(0, 0x466, 1)[0]    #  border, background or 640x200 colour,
            bl = s.r('bl')              #  BH=1 the 320x200 palette
            v = (v & 0xE0) | (bl & 0x1F) if s.r('bh') == 0 else (v & 0xDF) | (0x20 if bl & 1 else 0)
            s.wr(0, 0x466, [v]); s.set_ccr(v)
        elif ah in (0x10, 0x11, 0x12, 0x1A, 0x1B, 0x1C, 0x13): pass

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
        if ah in (2, 3, 4) and d.empty:
            s.w('ax', 0x8000); s.cf(1); return          # time-out: no disk
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
            if ah != 4 and lin >= 0xA0000 and not s.in_frame(lin, al * 512):
                s.w('ax', 0x0900); s.cf(1); return        # DMA can't reach video/ROM (the EMS frame it can)
            lba = (c * d.heads + h) * d.spt + sct - 1
            if ah == 2 and d.bad.intersection(range(lba, lba + al)):
                good = min(d.bad.intersection(range(lba, lba + al))) - lba
                s.dma_write(lin, bytes(d.img[lba * 512:(lba + good) * 512]) + b'\xEE' * 512)   # (bad data DMA'd anyway)
                s.calls_bad = getattr(s, 'calls_bad', 0) + 1
                s.w('ax', 0x1000 | good); s.cf(1); return
            if ah == 2: s.dma_write(lin, bytes(d.img[lba * 512:(lba + al) * 512]))
            elif ah == 3: d.img[lba * 512:(lba + al) * 512] = s.dma_read(lin, al * 512)
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

    def rom_list(s):
        """The logical images, as E401 counts them: socket 0's, then socket 1's
        (an empty socket, or one without the BB66h trailer, has none)."""
        out = []
        for sock in (0, 1):
            img = s.roms.get(sock)
            if img and img[-256:-254] == b'\x66\xBB': out.append(sock)
        return out

    def rom_map(s, sock):
        if s.rom_mapped is None: s.rom_saved = s.rd(0xA000, 0, 0x20000)
        s.mu.mem_write(0xA0000, bytes(s.roms[sock])); s.rom_mapped = sock; s.rom_maps += 1

    def rom_unmap(s):
        if s.rom_mapped is not None:
            s.mu.mem_write(0xA0000, s.rom_saved); s.rom_mapped = None; s.rom_saved = None

    def boot_rom(s, sock=0):
        """The BIOS's GridBootRom: the image (system type 1, bootable) copied to
        8000:0000, entered at (bootSeg + 8000h):0000 with DL = 'r', IF on."""
        img = s.roms[sock]; t = img[-256:]
        assert t[0:2] == b'\x66\xBB' and t[2] == 1 and t[3] == 0x80, 'not a bootable image'
        s.mu.mem_write(0x80000, bytes(img))
        bseg = struct.unpack_from('<H', t, 4)[0]
        s.w('cs', bseg if bseg >= 0x8000 else bseg + 0x8000); s.w('ip', 0)
        s.w('dx', 0x72); s.w('ss', 0x0030); s.w('sp', 0x0100); s.w('flags', 0x202)

    def int15(s):
        ax, ah = s.r('ax'), s.r('ah')
        if ah == 0xE4 and ax <= 0xE404:
            al = ax & 0xFF; imgs = s.rom_list()
            if al == 0: s.w('ax', 0x0008); s.w('bx', 5); s.w('cx', 2); s.cf(0); return
            if al == 1:
                if not imgs: s.w('ax', 0x0300); s.cf(1); return
                s.rom_ds = s.r('ds')
                s.w('ax', len(imgs)); s.cf(0); return
            if s.r('ds') != getattr(s, 'rom_ds', None):     # (the BIOS checks DS is
                s.w('ax', 0x0200); s.cf(1); return          #  the one E401 set up)
            if al == 4: s.rom_unmap(); s.w('ax', 0); s.cf(0); return
            dl = s.r('dl')
            if dl >= len(imgs): s.w('ax', 0x0400); s.cf(1); return
            sock = imgs[dl]; t = s.roms[sock][-256:]
            if al == 2:
                s.w('ax', 0x0080); s.w('bx', struct.unpack_from('<H', t, 19)[0])
                s.w('cx', 0x0404 * sock); s.w('dx', t[2] << 8 | dl); s.w('es', 0xA000); s.cf(0); return
            s.rom_map(sock); s.w('ax', 4 * sock); s.cf(0); return
        if ax == 0xE440: s.w('cx', s.ems_pages * 16 if s.ems_pages else 1408); s.w('ax', 0); s.cf(0); return
        if ax == 0xE441: s.w('cx', 0); s.w('ax', 0); s.cf(0); return
        if ax == 0xE442 and s.ems_pages and s.r('dl') == 0xFF:     # memory mode: EMS
            s.w('dx', (s.r('dx') & 0xFF00) | 1); s.w('ax', 0); s.cf(0); return
        if ah == 0x4F: s.cf(1); return
        if ah == 0x88: s.w('ax', 0); s.cf(0); return
        if ah == 0x86:
            s.us += (s.r('cx') << 16 | s.r('dx')); s.cf(0); return
        if ah in (0x90, 0x91): s.w('ax', ax & 0xFF); s.cf(0); return
        s.w('ax', (ax & 0xFF) | 0x8600); s.cf(1)

    # The 1520's BIOS (GRiD's Phoenix 286 BIOS, 10/25/89; its INT 9 and
    # INT 16h as in github.com/philip-searle/gridcase-bios) stores Alt with
    # these keys as scan code + F0h: "enhanced keyboard only".  INT 16h
    # AH=00h/01h skip them (AH=01h drops them from the buffer); AH=10h/11h
    # return them with AL = 0.  Tests queue keys as AH=10h returns them
    # (CODE-? = 3500h), so they are stored here the way the BIOS would.
    ALT_F0 = {0x01, 0x0E, 0x1A, 0x1B, 0x1C, 0x27, 0x28, 0x29, 0x2B, 0x33, 0x34, 0x35, 0x37, 0x4A, 0x4E}

    @staticmethod
    def bios_word(k):
        return k | 0xF0 if k & 0xFF == 0 and k >> 8 in PC.ALT_F0 else k

    @staticmethod
    def old_read(w):
        """What INT 16h AH=00h/01h make of a buffer word (None: skipped)."""
        ah, al = w >> 8, w & 0xFF
        if ah == 0xE0:
            return {0xE02F: 0x352F, 0xE00D: 0x1C0D, 0xE00A: 0x1C0A}.get(w, w)
        if ah >= 0x85: return None
        if al == 0xE0 and ah: al = 0
        if al == 0xF0 and ah: return None
        return ah << 8 | al

    @staticmethod
    def ext_read(w):
        return w & 0xFF00 if w & 0xFF == 0xF0 and w >> 8 else w

    # The BIOS's keyboard buffer (40:1Eh-3Dh, head 40:1Ah, tail 40:1Ch) holds
    # the first 15 of s.keys as the BIOS would, so code that reads it directly
    # (resident Claude's hot key) sees what it would on the 1520.  Keys go in
    # at the tail as the keyboard's IRQ would put them, and the head moves on
    # as INT 16h takes them, so nothing in it moves under code reading it.
    # What guest code changes there (a word taken out, head moved, keys put
    # back) is taken into s.keys at the next sync: each run slice and INT 16h.
    def kbd_ring(s):
        head, tail = struct.unpack('<HH', s.rd(0x40, 0x1A, 4))
        out = []
        while head != tail and KB_START <= head < KB_END and len(out) < 16:
            out.append(struct.unpack('<H', s.rd(0x40, head, 2))[0])
            head = head + 2 if head + 2 < KB_END else KB_START
        return out

    def kbd_sync(s):
        ring = s.kbd_ring()
        if ring != s.kbd_mirror:
            rest = list(s.keys)[len(s.kbd_mirror):]
            s.keys.clear(); s.keys.extend(ring + rest)
            s.kbd_mirror = ring
        n = len(s.kbd_mirror)
        if n < 15 and len(s.keys) > n:
            head, tail = struct.unpack('<HH', s.rd(0x40, 0x1A, 4))
            if not (KB_START <= head < KB_END and KB_START <= tail < KB_END) or not n:
                head = tail = KB_START
            for k in list(s.keys)[n:15]:
                w = PC.bios_word(k)
                s.mu.mem_write(0x400 + tail, struct.pack('<H', w)); s.kbd_mirror.append(w)
                tail = tail + 2 if tail + 2 < KB_END else KB_START
            s.mu.mem_write(0x41A, struct.pack('<HH', head, tail))

    def int16(s):
        s.kbd_sync()
        n0, ah = len(s.keys), s.r('ah')
        s.int16_hle()
        n = min(n0 - len(s.keys), len(s.kbd_mirror)) if ah != 5 else 0
        if n > 0:                               # taken from the front: the head moves on
            head = struct.unpack('<H', s.rd(0x40, 0x1A, 2))[0]
            for _ in range(n): head = head + 2 if head + 2 < KB_END else KB_START
            s.mu.mem_write(0x41A, struct.pack('<H', head)); s.kbd_mirror = s.kbd_mirror[n:]
        s.kbd_sync()

    def int16_hle(s):
        ah = s.r('ah')
        if ah in (0x00, 0x01):
            while s.keys and PC.old_read(PC.bios_word(s.keys[0])) is None:
                s.keys.popleft()                # the BIOS skips (and drops) these
        if ah in (0x00, 0x10):
            if s.keys:
                w = PC.bios_word(s.keys.popleft())
                s.w('ax', PC.old_read(w) if ah == 0 else PC.ext_read(w))
            else:
                s.w('ip', s.r('ip') - 2); s.blocked = True; s.mu.emu_stop()
        elif ah in (0x01, 0x11):
            if s.keys:
                w = PC.bios_word(s.keys[0])
                s.w('ax', PC.old_read(w) if ah == 1 else PC.ext_read(w)); s.zf(0)
            else: s.zf(1)
        elif ah in (0x02, 0x12): s.w('ax', s.r('ax') & 0xFF00)
        elif ah == 0x05:                        # (full at 15, as the BIOS's buffer)
            if len(s.keys) >= 15: s.w('ax', (s.r('ax') & 0xFF00) | 1)
            else: s.keys.append(s.r('cx')); s.w('ax', 0)

    def prtsc(s):
        """Shift-PrtSc: the BIOS's INT 9 calls INT 5."""
        s.soft.append(5)

    def int18(s): s.stopped = 'INT 18h (ROM BASIC)'; s.mu.emu_stop()
    def int19(s):
        if s.r('cs') == 0xF000 and s.r('ip') == 0xE05D:      # the reset jump's POST
            s.warm_boot(getattr(s, 'ems_on_reset', 'keep')); s.mu.emu_stop(); return
        s.stopped = 'INT 19h (reboot)'; s.mu.emu_stop()

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
            unb = lambda v: (v >> 4) * 10 + (v & 15)
            cx, dx, n = s.r('cx'), s.r('dx'), s.now()
            try:
                if ah == 0x03:
                    new = n.replace(hour=unb(cx >> 8), minute=unb(cx & 255), second=unb(dx >> 8), microsecond=0)
                else:
                    new = n.replace(year=unb(cx >> 8) * 100 + unb(cx & 255), month=unb(dx >> 8), day=unb(dx & 255))
                s.clock0 += new - n             # the RTC runs on from there
            except ValueError:
                pass

    # ---- running --------------------------------------------------------------
    def lin(s): return (s.r('cs') * 16 + s.r('ip')) & 0xFFFFF

    def boot(s, drive=0):
        """INT 19h: sector 0 of the drive to 0:7C00, jump with DL = drive."""
        s.mu.mem_write(0x7C00, bytes(s.drives[drive].img[:512]))
        s.w('cs', 0); s.w('ip', 0x7C00); s.w('dx', drive); s.w('ss', 0); s.w('sp', 0x7C00)
        s.w('flags', 0x202)

    def run(s, n=20000):
        if s.stopped or s.crash: return False
        s.kbd_sync()
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

    def unmasked(s, i):
        if i < 8: return not s.pic_mask & (1 << i)
        return not s.pic_mask & 4 and not s.pic2_mask & (1 << (i - 8))

    def deliverable(s):
        return bool(s.r('flags') & 0x200) and (bool(s.soft) or any(s.unmasked(i) for i in s.irq_pending))

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
