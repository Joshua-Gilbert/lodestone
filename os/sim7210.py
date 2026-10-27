# Higher-fidelity uPD7210 + GPIB bus model (v2) for unicorn tests.
# Models: ISR1 latches (cleared on read), DIR register, RFD holdoff (AUXRA bit0),
# handshake completion on DIR read / rhdf, serial-poll status re-sent every
# handshake, TCS waiting for a handshake (and TCA ignored while TCS pending),
# stale bytes left in DIR.  Devices = Joshua's bus: FG5010@6, HP8753D@14, DC5009@29.
import os, sys, struct
from unicorn import *
from unicorn.x86_const import *

BASE = 0x02E1
GHOSTDEV = [os.environ.get('GHOSTDEV') == '1']
KEYS = [0]
class Device:
    def __init__(s, addr, status, answers):
        s.addr, s.status, s.answers = addr, status, answers
        s.inbuf = b''; s.out = b''
    def message(s, msg):
        key = msg.strip().decode('latin1')
        s.out = (s.answers[key] + '\r\n').encode() if key in s.answers else b''

def bus():
    return {6: Device(6, 0x41, {'ID?': 'ID TEK/FG5010,V79.1,F1.0'}),
            14: Device(14, 0x00, {'*IDN?': 'HEWLETT-PACKARD,8753D,0,6.14'}),
            29: Device(29, 0x41, {'ID?': 'ID TEK/DC5009,V79.1,F2.1'})}

class NEC7210:
    def __init__(s, devices, stale=None):
        s.devices = devices; s.my = 0; s.log = []; s.ren = False
        s.full_reset(); s.stray = os.environ.get('STRAY') == '1'; s.spe_count = 0
        s.slow_start = 0; s.n_slow = 0                 # a slow listener: DO that many ISR1 reads after GTS
        if stale is not None: s.dir = stale            # left over from a previous run
    def full_reset(s):
        s.cic = False; s.atn = False; s.listeners = set(); s.talker = None
        s.spe = False; s.dir = 0; s.dir_full = False; s.isr1 = 0; s.seoi = False
        s.holdoff_all = False; s.holdoff_end = False; s.reos = False; s.held = False; s.tcs_pending = False; s.msgpos = 0
        s.errlatch = False; s.co = False; s.do = False; s.do_hold = 0
    def chip_talks(s): return s.talker == s.my
    def chip_listens(s): return s.my in s.listeners
    def source(s):
        return s.devices.get(s.talker) if (s.talker is not None and s.talker != s.my) else None
    def pump(s):
        # a device may send one byte if: chip listening, ATN off, handshake free
        if s.atn or not s.chip_listens() or s.dir_full or s.held: return
        d = s.source()
        if d is None:
            if GHOSTDEV[0] and s.spe and s.talker is not None and s.talker != s.my:
                s.ghostwait = getattr(s, 'ghostwait', 0) + 1
                if s.ghostwait >= 15:
                    s.ghostwait = 0; s.dir = 0; s.dir_full = True; s.isr1 |= 0x01
                    if s.holdoff_all: s.held = True
            return
        if s.spe: b, e = d.status, False
        elif d.out:
            b = d.out[0]; d.out = d.out[1:]; e = (len(d.out) == 0)
            if e and getattr(d, 'on_sent', None): d.on_sent()      # (its last byte: the Pico's TX_DONE)
        else: return
        end = e or (s.reos and b == 0x0A)
        s.dir = b; s.dir_full = True; s.isr1 |= 0x01 | (0x10 if end else 0)
        if s.holdoff_all or (s.holdoff_end and end): s.held = True
        s.bytes_sent = getattr(s, 'bytes_sent', 0) + 1
    def handshake_done(s):
        if s.tcs_pending: s.tcs_pending = False; s.atn = True; s.co = True
    def read(s, reg):
        s.pump()
        if reg == 0:
            v = s.dir
            if s.dir_full:
                s.dir_full = False
                if not s.held: s.handshake_done()
            s.pump(); return v
        if reg == 1:
            if s.do_hold:
                s.do_hold -= 1
                if not s.do_hold: s.do = True
            v = s.isr1
            if s.do: v |= 0x02; s.do = False
            if s.errlatch: v |= 0x04; s.errlatch = False
            s.isr1 = 0; return v
        if reg == 2:
            v = 0x08 if s.co else 0
            s.co = False; return v
        if reg == 4: return (0x80 if s.cic else 0) | (0 if s.atn else 0x40) | (0x04 if s.chip_listens() else 0) | (0x02 if s.chip_talks() else 0)
        if reg == 6: return s.my
        return 0
    def write(s, reg, v):
        if reg == 5: return s.aux(v)
        if reg == 6:
            if not v & 0x80: s.my = v & 0x1F
            return
        if reg == 0: return s.cdor(v)
    def aux(s, v):
        if v == 0x02: s.full_reset(); s.log.append('reset')
        elif 0x80 <= v <= 0x9F: s.holdoff_all = bool(v & 1); s.holdoff_end = bool(v & 2); s.reos = bool(v & 4)
        elif v == 0x03:
            if s.held: s.held = False; s.handshake_done()
        elif v == 0x16: s.cic = True; s.atn = True; s.co = True; s.listeners.clear(); s.talker = None; s.tcs_pending = False
        elif v == 0x1F: s.ren = True
        elif v == 0x17: s.ren = False
        elif v == 0x11:
            if s.tcs_pending: s.log.append('TCA ignored (TCS pending)')
            elif s.cic:
                if not s.atn: s.co = True
                s.atn = True
        elif v == 0x12:
            if s.dir_full or s.held: s.tcs_pending = True
            else: s.tcs_pending = True; s.log.append('TCS with no handshake -> waits')
        elif v == 0x06: s.seoi = True
        elif v == 0x10:
            if s.cic and not s.tcs_pending:
                s.atn = False; s.co = False
                if s.chip_talks() and s.slow_start: s.do_hold = s.slow_start; s.n_slow += 1
                elif s.chip_talks(): s.do = True
        s.pump()
    def cdor(s, v):
        if s.atn:
            if not s.cic: return
            s.co = True                      # command byte sent, ready for next
            if v == 0x3F: s.listeners.clear()
            elif v == 0x5F: s.talker = None
            elif v == 0x18:
                s.spe = True; s.spe_count += 1
                if s.stray and s.spe_count == 1: s.isr1 |= 0x01; s.log.append('stray DI injected')
                if os.environ.get('WEDGE') == '1' and s.spe_count == 12: s.tcs_pending = True; s.atn = False; s.log.append('chip wedged')
            elif v == 0x19: s.spe = False
            elif 0x20 <= v <= 0x3E: s.listeners.add(v - 0x20)
            elif 0x40 <= v <= 0x5E:
                s.talker = v - 0x40
                d = s.devices.get(s.talker)
                if d is not None and not d.out and getattr(d, 'reading', None):
                    d.out = (d.reading + '\r\n').encode()
            return
        if not s.chip_talks(): return
        targets = [s.devices[a] for a in s.listeners if a in s.devices]
        if not targets: s.errlatch = True; return
        eoi = s.seoi; s.seoi = False
        s.do = True                          # byte accepted, ready for next
        for d in targets:
            d.inbuf += bytes([v])
            if eoi or v == 0x0A: d.message(d.inbuf); d.inbuf = b''

def run(prog, args='', stale=None, maxins=300_000_000):
    chip = NEC7210(bus(), stale)
    mu = Uc(UC_ARCH_X86, UC_MODE_16); mu.mem_map(0, 0x110000)
    PSP = 0x1000; base = PSP * 16
    mu.mem_write(base, b'\xcd\x20' + struct.pack('<H', 0x9FC0))
    mu.mem_write(base + 0x100, open(prog, 'rb').read())
    a = args.encode(); mu.mem_write(base + 0x80, bytes([len(a)]) + a + b'\r')
    out = []
    R = mu.reg_read; W = mu.reg_write
    def cf(c):
        f = R(UC_X86_REG_FLAGS); W(UC_X86_REG_FLAGS, (f | 1) if c else (f & ~1))
    def hook(uc, n, ud):
        ah = R(UC_X86_REG_AH); ds = R(UC_X86_REG_DS); dx = R(UC_X86_REG_DX)
        if n == 0x10: return
        if n == 0x16:
            KEYS[0] += 1
            if KEYS[0] == 40: GHOSTDEV[0] = False          # 'user powers off the culprit'
            f = R(UC_X86_REG_FLAGS)
            if ah == 1: W(UC_X86_REG_FLAGS, (f & ~0x40) if KEYS[0] > 80 else (f | 0x40))
            return
        if ah == 9:
            p = ds * 16 + dx; b = b''
            while uc.mem_read(p, 1)[0] != 0x24: b += bytes(uc.mem_read(p, 1)); p += 1
            out.append(b.decode('latin1'))
        elif ah == 2: out.append(chr(R(UC_X86_REG_DL)))
        elif ah == 0x3D: W(UC_X86_REG_AX, 2); cf(1)
        elif ah == 0x3C: W(UC_X86_REG_AX, 5); cf(0)
        elif ah == 0x40: W(UC_X86_REG_AX, R(UC_X86_REG_CX)); cf(0)
        elif ah in (0x3E, 0x68): cf(0)
        elif ah == 0x4C: uc.emu_stop()
    pit = {'latch': None, 'hi': False}
    def hin(uc, port, size, ud):
        if port == 0x40:
            if pit['latch'] is None:
                v = (65536 - (nb[0] % 300) * 218) & 0xFFFF; pit['latch'] = v; pit['hi'] = False
            v = pit['latch']
            if not pit['hi']: pit['hi'] = True; return v & 0xFF
            pit['latch'] = None; return v >> 8
        if (port & 0x3FF) == BASE and port < 0x2000: return chip.read(port >> 10)
        return 0xFF
    def hout(uc, port, size, val, ud):
        if port == 0x43:
            chip.log.append('PIT %02X' % (val & 0xFF))
            if (val & 0xF0) == 0: pit['latch'] = None
            return
        if (port & 0x3FF) == BASE and port < 0x2000: chip.write(port >> 10, val & 0xFF)
    nb = [0]
    def hb(uc, addr, size, ud):
        nb[0] += 1
        if nb[0] % 300 == 0:
            t = struct.unpack('<H', bytes(uc.mem_read(0x46C, 2)))[0]; uc.mem_write(0x46C, struct.pack('<H', (t + 1) & 0xFFFF))
    mu.hook_add(UC_HOOK_INTR, hook)
    mu.hook_add(UC_HOOK_INSN, hin, None, 1, 0, UC_X86_INS_IN)
    mu.hook_add(UC_HOOK_INSN, hout, None, 1, 0, UC_X86_INS_OUT)
    mu.hook_add(UC_HOOK_BLOCK, hb)
    for r in (UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS): W(r, PSP)
    W(UC_X86_REG_SP, 0xFFFE)
    try:
        mu.emu_start(base + 0x100, 0, count=maxins)
    except UcError as e:
        out.append('\n[CRASH %s at %04X:%04X SP=%04X]' % (e, R(UC_X86_REG_CS), R(UC_X86_REG_IP), R(UC_X86_REG_SP)))
    return ''.join(out), chip

if __name__ == '__main__':
    stale = int(os.environ['STALE'], 16) if 'STALE' in os.environ else None
    o, c = run(os.environ.get('PROG', 'GPIBSCAN.COM'), sys.argv[1] if len(sys.argv) > 1 else '', stale)
    print(o); print('chip log:', c.log[:6])
