#!/usr/bin/env python3
"""Multitasking (KMT.INC): the switch and the skeleton (M1), tasks switched
when one waits for a key (M2a), the front one chosen with CODE-Tab, each with
its own screen (M2b), preempted at the timer's tick where it is safe (M3), each
with its own coprocessor (M3b), a background task's output in its own screen and a
task that writes the screen itself frozen there (M4a), keys for the front task
only and CODE-Tab wherever it is typed (M4b), each task's own mouse (M4c).

(pcemu's INT 16h AH=00h with no key blocks at the caller's own INT 16h, so a
program waiting there could be preempted even before M4b; on the 1520 it waited
inside the BIOS, where it can't be.  Since M4b a program's read with nothing
typed waits in MT, not the BIOS.)

MULTITASK=1 in LODE.INI (with EMS, enough for the disk cache to be in it)
puts multitasking's resident part in a block of its own at the top of
memory, with INT 08h, INT 21h F0h and the kernel's key wait going through
it.  Programs start others as tasks (MTLAUNCH), each in a region of its own,
and they take turns at the timer's tick, where it is safe.  Off (no such
line, any other value, or no EMS), nothing of it is in memory and everything
is as before.
python3 tests/test_mt.py [t_name ...]     (any of the t_ functions at the end, in their order; default all)"""
import collections, os, re, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest
import test_apps as A
from test_kernel import Shell
from pcemu import STUB
from unicorn import x86_const as UX

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:600]) if detail and not cond else ''))

MTPROBE = os.path.join(HERE, 'MTPROBE.COM')
MTSC = os.path.join(HERE, 'MTSCR.COM')
VNEST = os.path.join(HERE, 'VNEST.BIN')
MTCR, MTNS, VHK = (os.path.join(HERE, n + '.COM') for n in ('MTCRIT', 'MTNEST', 'VHOOK'))
MTL, MTLN, MTCW, MTMD, FREEH, MTSP, MTHK = (os.path.join(HERE, n + '.COM') for n in ('MTLAUNCH', 'MTLINE', 'MTCWD', 'MTMODE', 'FREEH',
                                                                                    'MTSPIN', 'MTHOOK'))
SYS = os.path.join(GOS, 'src', 'LODE.SYS')
MTSYS = os.path.join(GOS, 'src', 'LODEMT.SYS')
MAP = os.path.join(GOS, 'src', 'LODE.MAP')
import mkmt
INT08 = (STUB, 0x1000)                  # pcemu's BIOS timer handler
# KMT.INC's layout, from LODE.MAP's EQUs (H6): an entry in mt_tab and its fields (its stub's PSP, its region, its
# TX's segment, its last exit code, its name, its screen's EMS handle, VF_DIRECT and the SPF_ overrides, MT_KILL's
# mark, parked: the EMS handle its region is in and the region's paragraphs, its count); a TX's BIOS video data
(MT_ENT, TE_PSP, TE_REG, TE_TX, TE_EXIT, TE_NAME, TE_SH, TE_VF, TE_KILL, TE_PH, TE_PSZ, TE_GEN, TX_VID, VF_DIRECT,
 SPF_BG, SPF_FREEZE, TS_WAITF, TS_FROZEN) = map(ktest.equ, (
    'MT_ENT', 'TE_PSP', 'TE_REG', 'TE_TX', 'TE_EXIT', 'TE_NAME', 'TE_SH', 'TE_VF', 'TE_KILL', 'TE_PH', 'TE_PSZ',
    'TE_GEN', 'TX_VID', 'VF_DIRECT', 'SPF_BG', 'SPF_FREEZE', 'TS_WAITF', 'TS_FROZEN'))
INT10 = (STUB, 0x10 * 8)                # pcemu's BIOS INT 10h
INT16 = (STUB, 0x16 * 8)                # and INT 16h
TS_WAITK = ktest.equ('TS_WAITK')
MTK = os.path.join(HERE, 'MTKEY.COM')
MTM = os.path.join(HERE, 'MTM33.COM')
MTV = os.path.join(HERE, 'MTVEC.COM')
MTKL = os.path.join(HERE, 'MTKILL.COM')

# With the switch off these must not move (main with UI API 6, PrtSc's printing and the audit's kernel
# and UI batches, then its medium-risk kernel and UI batches): the kernel's image and BSS, the UI block
# kept while a DOS program runs.  (LODE.ASM's parity pads move the kernel in steps of 0 or 2 bytes for a change
# before gp_isr; no code slack at lastdrv 40CFh: any change netting +1 moves image_end and bss_end.  The UI's
# pads, UICORE.INC's, likewise: ui_image_end 5220h, no slack before uibss's paragraph)
OFF_MAP ={'image_end': 0x3F60, 'bss_end': 0x7360, 'ui_keep_end': 0x64D0}  # (6422h before free memory on the info line, 160 bytes; 3F50h/7350h before the 2026-10-20 audit's S4 and S14, INT 21h 09h in one write and the EMS module's word-wise 57h; 40C0h/74C0h before the 2026-10-20 audit's KC-2, the screen capture's file writer as SCREEN.PRN; 75E0h before the 2026-10-20 audit's K2, EXEC's and rename's buffers in the INT 21h stack's low area; 64C2h before the 2026-10-20 audit's AP-1, HT in help lines; 40D0h/7600h before the 2026-10-20 audit's XI-13 and G1-5; 64E2h before its UI-7; 64C2h before Paint: the Executive opening .BMP files, 32 bytes; 40E0h/7610h before dev_where read dev_look_ax's BX, audit R38; 40F0h/7620h before ex_busy went, audit O7; 64F6h before R42, the Executive's MULTITASK-only code in KMW; 64E6h before help lines cut at the window's inner edge, re-padded; 6516h before the audit's UI batch, R39-R41; 4190h/76C0h before the audit's kernel batch; 6526h before the clipboard's file named at start-up, audit X47; 4170h/76A0h before an Abort while EXEC loads failed the EXEC; 63D0h before the clipboard, UI_CLIP; 621Ah before pop-up menus and drags, UI API 8; 6144h before right clicks, UI API 7; 6164h before X22;
                                        #  6154h before M7b: the Executive's Return as a task, CODE-T, the UI block moved once no task is left;
                                        #  3F80h/74B0h before GPIB's SRQ on IRQ 5; 4090h/75C0h/620Ah before INT 24h for no disk;
                                        #  40B0h/75E0h before GPIBLOOP's fast loops; 40E0h/7610h before the driver's frame check)

def ini(text):
    p = os.path.join(A.OUT, 'LODE.INI'); open(p, 'wb').write(text); return 'LODE.INI=' + p

def boot(name, text=None, ems=88, *more, mt=MTSYS, nofpu=False, mouse=False, chip=None, irq_exact=True, **kw):
    """A floppy with LODE.SYS and (unless mt=None) LODEMT.SYS, LCMD, MEMSZ,
    MTPROBE, `more`, and LODE.INI holding `text`.  nofpu: INT 11h says no
    coprocessor, and the 286's EM bit is set, so any coprocessor instruction
    traps (INT 7, counted in pc.ints).  mouse: a serial mouse on COM1.  irq_exact: pcemu's (an IRQ held
    under CLI taken when IF is set again, as the 1520's PIC gives it; on by default, H10).  kw: pcemu's
    (fd_wait: a floppy's transfer waits for its IRQ 6, M10; disk_model)."""
    files = ([] if mt is None else ['LODEMT.SYS=' + mt]) + [A.LCMD, A.MEMSZ, MTPROBE, MTL, MTLN, MTCW, MTMD, FREEH, MTSP, MTHK] + list(more) \
        + ([ini(text)] if text is not None else [])
    k = ktest.KPC(A.image(name, *files), ems_pages=ems, chip=chip, irq_exact=irq_exact, **kw)
    k.pc.mouse = mouse
    if nofpu:
        k.pc.wr(0, 0x410, struct.pack('<H', k.pc.u16(0, 0x410) & ~2))
        k.pc.mu.reg_write(UX.UC_X86_REG_CR0, k.pc.mu.reg_read(UX.UC_X86_REG_CR0) | 4)
    k.start(10)
    k.mcb0 = k.u16('first_mcb')         # (the whole arena's start: first_mcb is per task)
    return k

def mcbs(k):
    """The memory arena: (segment of the MCB, type, owner, paragraphs, name)."""
    pc, seg, out = k.pc, getattr(k, 'mcb0', None) or k.u16('first_mcb'), []
    while True:
        t, own, sz, nm = chr(pc.rd(seg, 0, 1)[0]), pc.u16(seg, 1), pc.u16(seg, 3), pc.rd(seg, 8, 2)
        out.append((seg, t, own, sz, nm))
        if t != 'M' or len(out) > 200: return out
        seg += sz + 1

def show(arena): return [(hex(s), t, hex(o), sz, n) for s, t, o, sz, n in arena[-4:]]

def mt_seg(k):
    """MT's block (its segment), or None."""
    for seg, t, own, sz, nm in mcbs(k):
        if nm == b'MT' and own == 8: return seg + 1
    return None

def at_top(k):
    """MT's block is the last one, ending at A000h, after one free block."""
    a, seg = mcbs(k), mt_seg(k)
    return (seg is not None and a[-1][0] == seg - 1 and a[-1][1] == 'Z' and seg + a[-1][3] == 0xA000
            and a[-2][2] == 0)

def vec(k, n): return k.pc.u16(0, n * 4 + 2), k.pc.u16(0, n * 4)

def equ(name):
    """An EQU's value, from LODE.MAP's list of them (ktest.equ)."""
    return ktest.equ(name)

def f0_bytes(k): return bytes(k.pc.rd(0x60, k.Y['f_F0'], 5))
def kw_bytes(k): return bytes(k.pc.rd(0x60, k.Y['kbd_get.k'], 6))
def dx_bytes(k): return bytes(k.pc.rd(0x60, k.Y['done.sw'], 5))
EXIT5 = bytes([0x8E, 0xD0, 0x89, 0xDC, 0x61])      # MOV SS,AX / MOV SP,BX / POPA

def probe(k):
    """MTPROBE's lines: {AL: (CF, AX, BX, CX)}."""
    out = run_wait(k, 'MTPROBE.COM', 20)
    got = {}                            # (a call made again: + 100h each time)
    for m in re.finditer(r'F0([0-9A-F]{2}) CF=(\d) AX=([0-9A-F]{4}) BX=([0-9A-F]{4}) CX=([0-9A-F]{4})', out):
        a = int(m.group(1), 16)
        while a in got: a += 0x100
        got[a] = (int(m.group(2)), int(m.group(3), 16), int(m.group(4), 16), int(m.group(5), 16))
    return got, out

def bad(r): return r[0] == 1 and r[1] == 1      # CF, AX = 1: MS-DOS has no such call

OFF_MSG = 'Multitasking is off (MULTITASK=1 in LODE.INI)'

def t_off():
    print('== off: nothing of it in memory, everything as before')
    Y = ktest.Syms()
    check('the map with the switch off: %s' % ', '.join('%s %04Xh' % kv for kv in OFF_MAP.items()),
          all(Y[n] == v for n, v in OFF_MAP.items()), {n: hex(Y[n]) for n in OFF_MAP})
    sysb = open(SYS, 'rb').read()
    for tag, text, ems in (('no LODE.INI', None, 88), ('no MULTITASK= line', b'SPLASH=0\r\n', 88),
                           ('MULTITASK=0', b'MULTITASK=0\r\n', 88), ('MULTITASK=Off', b'MULTITASK=Off\r\n', 88),
                           ('MULTITASK=No', b'MULTITASK=No\r\n', 88), ('MULTITASK=2', b'MULTITASK=2\r\n', 88),
                           ('MULTITASK=10', b'MULTITASK=10\r\n', 88), ('MULTITASK=Yikes', b'MULTITASK=Yikes\r\n', 88),
                           ('MULTITASK=One', b'MULTITASK=One\r\n', 88), ('MULTITASK= (empty)', b'MULTITASK=\r\n', 88),
                           ('MULTITASK=1 but no EMS', b'MULTITASK=1\r\n', 0)):
        k = boot('mt_off.img', text, ems)
        check('%s: no MT block, INT 08h, 10h and 16h the BIOS\'s, f_F0, kbd_get.k, done.sw, f_48, mem_largest, f_4B.xe and gp_isr.e '
              'as assembled' % tag, mt_seg(k) is None and vec(k, 8) == INT08 and vec(k, 0x10) == INT10 and vec(k, 0x16) == INT16
              and f0_bytes(k) == sysb[k.Y['f_F0']:k.Y['f_F0'] + 5]
              and kw_bytes(k) == sysb[k.Y['kbd_get.k']:k.Y['kbd_get.k'] + 6] and dx_bytes(k) == EXIT5
              and all(bytes(k.pc.rd(0x60, k.Y[s], 5)) == sysb[k.Y[s]:k.Y[s] + 5] for s in ('f_48', 'mem_largest', 'f_4B.xe', 'gp_isr.e')),
              (show(mcbs(k)), vec(k, 8), f0_bytes(k).hex()))
        if tag in ('no LODE.INI', 'MULTITASK=1 but no EMS'):
            got, out = probe(k)
            check('%s: F0h AL=00h answers (4F47h, 0201h); 11h-14h, 18h, 1Bh, 1Ch, FFh and 1Eh-23h fail with AX = 1' % tag,
                  got.get(0) == (0, 0x4F47, 0x0201, 0x1234) and all(bad(got.get(a, (0, 0, 0, 0))) for a in (0x11, 0x12, 0x13, 0x14, 0x1B, 0x1C, 0xFF, 0x1E, 0x11E, 0x21E, 0x31E, 0x1F, 0x11F, 0x21F, 0x20, 0x120, 0x220, 0x21, 0x121, 0x221, 0x321, 0x22, 0x122, 0x222, 0x322, 0x23, 0x123, 0x18, 0x118)),
                  out[-400:])
            sh = Shell(k)
            o = sh.run('mtlaunch mtline.com x.txt')
            line(k, '')
            check('%s: MTLAUNCH can\'t start a task: MTLAUNCH: error 1, and no list' % tag,
                  'MTLAUNCH: error 1' in o and 'list: 0' not in o, o)
            o = sh.run('tasks || echo FAILED')
            check('%s: TASKS says it is off, and fails (ERRORLEVEL 1)' % tag, OFF_MSG in o and 'FAILED' in o, o)

def t_on():
    print('== MULTITASK=1: the switch and the skeleton')
    k = boot('mt_on.img', b'MULTITASK=1\r\n')
    Y = k.Y
    seg = mt_seg(k)
    arena = mcbs(k)
    paras = (Y['mt_bend'] + 15) // 16           # (the image and its BSS)
    check('a block of its own, owner 8, called MT, %d paragraphs: the last one, ending at A000h, one free block below it' % paras,
          at_top(k) and arena[-1][3] == paras and arena[-2][3] > 0x8000, show(arena))
    check('INT 08h goes through mt_tick', vec(k, 8) == (seg, Y['mt_tick']), (vec(k, 8), hex(seg or 0)))
    old = (k.pc.u16(seg, Y['mt_old08'] + 2), k.pc.u16(seg, Y['mt_old08']))
    check('... which goes on to the BIOS\'s', old == INT08, old)
    old = (k.pc.u16(seg, Y['mt_old10'] + 2), k.pc.u16(seg, Y['mt_old10']))
    check('INT 10h goes through mt_v10, and on to the BIOS\'s', vec(k, 0x10) == (seg, Y['mt_v10']) and old == INT10,
          (vec(k, 0x10), old))
    old = (k.pc.u16(seg, Y['mt_old16'] + 2), k.pc.u16(seg, Y['mt_old16']))
    check('INT 16h goes through mt_i16, and on to the BIOS\'s', vec(k, 0x16) == (seg, Y['mt_i16']) and old == INT16,
          (vec(k, 0x16), old))
    f0 = f0_bytes(k)
    check('INT 21h F0h goes through mt_f0 (JMP FAR over f_F0\'s first 5 bytes)',
          f0[0] == 0xEA and f0[1] | f0[2] << 8 == Y['mt_f0'] and f0[3] | f0[4] << 8 == seg, f0.hex())
    kw = kw_bytes(k)
    check('the key wait goes through mt_kwait (JMP FAR over kbd_get.k\'s MOV AH,1 / INT 16h / JNZ)',
          kw[0] == 0xEA and kw[1] | kw[2] << 8 == Y['mt_kwait'] and kw[3] | kw[4] << 8 == seg, kw.hex())
    dx = dx_bytes(k)
    check('INT 21h\'s way out goes through mt_exit (JMP FAR over done.sw\'s MOV SS,AX / MOV SP,BX / POPA)',
          dx[0] == 0xEA and dx[1] | dx[2] << 8 == Y['mt_exit'] and dx[3] | dx[4] << 8 == seg, dx.hex())
    check('... ctrlc\'s copy of those bytes untouched', bytes(k.pc.rd(0x60, Y['ctrlc.sw'], 5)) == EXIT5,
          bytes(k.pc.rd(0x60, Y['ctrlc.sw'], 5)).hex())
    gb = [bytes(k.pc.rd(0x60, Y[s], 5)) for s in ('f_48', 'mem_largest', 'f_4B.xe')]
    check('48h, EXEC\'s largest block and its environment\'s go through mt_48, mt_largest and mt_xenv (JMP FAR over '
          'f_48\'s, mem_largest\'s and f_4B.xe\'s first 5 bytes: a task\'s region grows, T5a)',
          [(b[0], b[1] | b[2] << 8, b[3] | b[4] << 8) for b in gb]
          == [(0xEA, Y['mt_48'], seg), (0xEA, Y['mt_largest'], seg), (0xEA, Y['mt_xenv'], seg)], [b.hex() for b in gb])
    gb = bytes(k.pc.rd(0x60, Y['gp_isr.e'], 5))
    check('the GPIB driver\'s SRQ interrupt goes through mt_srqi at its EOI (JMP FAR over gp_isr.e\'s MOV AL,20h / OUT 20h,AL / '
          'POP DS: T5c)', (gb[0], gb[1] | gb[2] << 8, gb[3] | gb[4] << 8) == (0xEA, Y['mt_srqi'], seg), gb.hex())
    check('task 0 is the Executive: its PSP the root process\'s',
          k.pc.u16(seg, Y['mt_tab'] + 2) == k.u16('root_psp'), (hex(k.pc.u16(seg, Y['mt_tab'] + 2)), hex(k.u16('root_psp'))))
    t0, b0 = k.pc.u16(seg, Y['mt_ticks']), k.pc.u16(0x40, 0x6C)
    k.run_for(2.0)
    t1, b1 = k.pc.u16(seg, Y['mt_ticks']), k.pc.u16(0x40, 0x6C)
    check('2 s: mt_tick ran %d times, the BIOS counted %d ticks (18.2 a second)' % (t1 - t0, b1 - b0),
          t1 - t0 == b1 - b0 and 34 <= b1 - b0 <= 38, (t1 - t0, b1 - b0))
    guards, prev = [], k.pc.watch       # (MTPROBE's MT_END: MT's guards set as it comes in, read as it is refused)
    gv = ('mt_crit', 'mt_in13', 'mt_inb')
    def w(a):
        if prev: prev(a)
        if a == seg * 16 + Y['mt_end'] and not guards:
            for v in gv: k.pc.wr(seg, Y[v], b'\1')
            guards.append(None)
        elif a == seg * 16 + Y['mt_bad'] and len(guards) == 1:
            guards.append(tuple(k.pc.rd(seg, Y[v], 1)[0] for v in gv))
            for v in gv: k.pc.wr(seg, Y[v], b'\0')
    k.pc.watch = w
    got, out = probe(k)
    k.pc.watch = prev
    check('MT_END not from a stub (MTPROBE\'s, task 0\'s), MT\'s guards set as it comes in (mt_crit, mt_in13, mt_inb): '
          'refused before it touches them (%s; audit3 X39)' % (guards[1:],), guards[1:] == [(1, 1, 1)], guards)
    check('F0h through mt_f0: AL=00h still answers (4F47h, 0201h: its OR AL,AL redone); 11h (not from a stub), 14h, 1Bh, FFh fail '
          'with AX = 1; 13h with task 0 works, and 1Ch (MT_SCREEN; alone, nothing to do)', got.get(0) == (0, 0x4F47, 0x0201, 0x1234)
          and all(bad(got.get(a, (0, 0, 0, 0))) for a in (0x11, 0x14, 0x1B, 0xFF)) and got.get(0x13, (1,))[0] == 0
          and got.get(0x1C, (1,))[0] == 0, out[-400:])
    check('F0h AL=13h with BL = 8 (no such task) and BL = 7 (a free one): CF, AX = 1',
          bad(got.get(0x113, (0, 0))) and bad(got.get(0x213, (0, 0))), out[-400:])
    check('F0h AL=1Eh (MT_TOPEN, T2), 1Fh (MT_TROWS), 20h (MT_TKEY), T1, and 21h (MT_TMOUSE, T4): task 0 refused (AX = 5); '
          '7 (a free one) and 8 (none such): AX = 1', all(got.get(a, (0, 0))[:2] == (1, 5) for a in (0x1E, 0x1F, 0x20, 0x21))
          and all(bad(got.get(a, (0, 0))) for a in (0x11E, 0x21E, 0x31E, 0x11F, 0x21F, 0x120, 0x220, 0x121, 0x221, 0x321)),
          out[-500:])
    check('F0h AL=22h (MT_PUB, T5b): CL = 0 from task 0 and CL = 1 for task 0 refused (AX = 5); CL = 1 for 7 (a free one) '
          'and CL = 2: AX = 1', all(got.get(a, (0, 0))[:2] == (1, 5) for a in (0x22, 0x122))
          and all(bad(got.get(a, (0, 0))) for a in (0x222, 0x322)), out[-500:])
    gi = k.pc.rd(0x60, Y['gp_irq'], 1)[0]
    check('F0h AL=23h (MT_WAKE, T5c) from task 0: BL = 1, then 0, both CF clear, AX = the driver\'s IRQ (%d); none '
          'left afterwards (mt_wkt FFh)' % gi, got.get(0x23, (1,))[:2] == (0, gi) and got.get(0x123, (1,))[:2] == (0, gi)
          and k.pc.rd(seg, Y['mt_wkt'], 1)[0] == 0xFF, out[-300:])
    check('F0h AL=18h (MT_FLAGS): BL = 0 (the Executive) refused, AX = 5; BL = 8 (none such: mt_targ\'s own failure) '
          'AX = 1', got.get(0x18, (0, 0))[:2] == (1, 5) and bad(got.get(0x118, (0, 0))), out[-300:])
    check('F0h AL=12h with no room: CF clear, CX = 1 task, AL = 0 in front, AH = 0 the caller, nothing written',
          got.get(0x12, (1,))[:2] == (0, 0x0000)
          and got[0x12][3] == 1, out[-400:])
    sh = Shell(k)
    o = sh.run('tasks && echo WORKED')
    check('TASKS lists one task, the Executive, in front (ERRORLEVEL 0)',
          re.search(r'^\s*0\s+Executive \(in front\)\s*$', o, re.M) and 'WORKED' in o and OFF_MSG not in o
          and len([l for l in o.split('\n') if 'Executive' in l]) == 1, o)
    k = boot('mt_on.img', b'MULTITASK=1\r\n')
    su = []
    for i in range(2):
        k.key(ktest.F1)
        su.append((k.u16('wseg'), k.rd('ems_su', 2), A.has(k, 'Help')))
        k.key(ktest.ESC)
        su.append((k.u16('wseg'), k.rd('ems_su', 2), A.has(k, 'Help')))
    check('the other F0h calls go on to the kernel: the help window\'s save-under is lent (AL=2) and given back (AL=3), '
          'twice (M8a: as before while no window .RUN runs)', [s[2] for s in su] == [True, False] * 2
          and all(su[i][0] != 0 and su[i][1] != b'\0\0' for i in (0, 2)) and all(su[i][:2] == (0, b'\0\0') for i in (1, 3)),
          [(hex(w), bytes(e).hex(), h) for w, e, h in su])
    for text in (b'MULTITASK=Yes\r\n', b'multitask=on\r\n', b'MULTITASK=1', b'MULTITASK=yes \r\n',
                 b'NOTE=MULTITASK=0\r\nMULTITASK=1\r\n'):
        k = boot('mt_on2.img', text)
        check('%r: on, at the top' % text, at_top(k), show(mcbs(k)))
    k = boot('mt_md.img', b'MULTITASK=1\r\nMDISK=512\r\n')
    check('MULTITASK=1 and MDISK=512: both (M: is 512 KB; MT at the top)', at_top(k) and A.md_pages(k) == 32, (A.md_pages(k), show(mcbs(k))))
    k = boot('mt_md.img', b'MDISK=0\r\nMULTITASK=1\r\n')
    check('MDISK=0 and MULTITASK=1: M: off, multitasking on, at the top', at_top(k) and A.md_pages(k) == 0, (A.md_pages(k), show(mcbs(k))))

def tstate(k):
    """MT's own table: ([(task, TS_* state, name)], front, running)."""
    seg, Y = mt_seg(k), k.Y
    out = []
    for i in range(8):
        b = Y['mt_tab'] + i * MT_ENT
        st = k.pc.rd(seg, b, 1)[0]
        if st: out.append((i, st, bytes(k.pc.rd(seg, b + TE_NAME, 12)).rstrip(b'\0').decode()))
    return out, k.pc.rd(seg, Y['mt_front'], 1)[0], k.pc.rd(seg, Y['mt_cur'], 1)[0]

def front(k, n):
    """Bring task n to the front, as F0h AL=13h does (mt_swreq), then let it run."""
    k.pc.wr(mt_seg(k), k.Y['mt_swreq'], bytes([n])); k.run_for(0.3)

def line(k, text):
    k.key(text); k.key(ktest.ENTER); k.run_for(0.5)

def run_wait(k, name, sim_s=60.0):
    """Shift-Return on a program in the Executive: in the Executive's own task, which waits for it, as with
    multitasking off (Return starts it as a task, M7b)."""
    return k.run_file(name, sim_s, shift=True)

def t_tasks():
    print('== tasks: programs started as tasks, switched when one waits for a key')
    k = boot('mt_t.img', b'MULTITASK=1\r\n', 88, 'SUB1\\', 'SUB2\\')
    sh = Shell(k)
    sh.run('ver')                       # (LCMD's first command takes a block)
    a0, used0 = merged(mcbs(k)), sft_used(k)
    o = sh.run('mtlaunch mtline.com a.txt;mtline.com b.txt')
    check('MTLAUNCH starts task 1 and task 2, and MT_LIST lists them after the Executive',
          'task 1' in o and 'task 2' in o and 'list: 0 1 Executive; 1 1 MTLINE.COM; 2 1 MTLINE.COM;' in o, o)
    st = tstate(k)
    check('when MTLAUNCH waits for its line, both run to theirs and wait there (TS_WAITK) in the background; '
          'the Executive\'s task in front; each prompt in its own task\'s screen, none on the one in front',
          st == ([(0, 1, 'Executive'), (1, 2, 'MTLINE.COM'), (2, 2, 'MTLINE.COM')], 0, 0)
          and 'MTLINE>' not in k.pc.text_screen() and all('MTLINE>' in slot_text(k, i) for i in (1, 2)),
          (st, k.pc.text_screen(), [slot_text(k, i)[:80] for i in (1, 2)]))
    a = mcbs(k)
    check('their regions: T1 right under MT\'s block, T2 under T1, the system\'s (owner 8)',
          [(b[4], b[2]) for b in a[-3:]] == [(b'T2', 8), (b'T1', 8), (b'MT', 8)]
          and a[-3][0] + a[-3][3] + 1 == a[-2][0] and a[-2][0] + a[-2][3] + 1 == a[-1][0], show(a))
    front(k, 1)
    k.key('hel'); k.run_for(0.3)
    front(k, 2)
    check('task 1 to the front, "hel" typed; then task 2: task 1 waits again, its line half-typed',
          tstate(k)[0][1:] == [(1, 2, 'MTLINE.COM'), (2, 1, 'MTLINE.COM')] and tstate(k)[1] == 2, tstate(k))
    line(k, 'world')
    check('task 2 gets "world" (B.TXT); it ends, its region goes; the Executive\'s task in front again',
          A.disk_file(k, 'B.TXT') == b'world' and tstate(k) == ([(0, 1, 'Executive'), (1, 2, 'MTLINE.COM')], 0, 0)
          and b'T2' not in [b[4] for b in mcbs(k) if b[2]], (A.disk_file(k, 'B.TXT'), tstate(k)))
    front(k, 1)
    line(k, 'lo')
    check('task 1 again: its half-typed line kept while task 2 ran ("hel" + "lo": A.TXT "hello")',
          A.disk_file(k, 'A.TXT') == b'hello', A.disk_file(k, 'A.TXT'))
    line(k, '')
    a1, used1 = merged(mcbs(k)), sft_used(k)
    v = sh.run('ver')
    check('MTLAUNCH gets its line and ends; the command prompt back (VER answers); memory as before (free neighbours '
          'merged), no file left open (the stubs\' inherited handles closed)',
          tstate(k) == ([(0, 1, 'Executive')], 0, 0) and a1 == a0 and used1 == used0 and 'Lodestone version' in v,
          (tstate(k), show(a1), used1, used0, v))
    # /F: the second to the front
    o = sh.run('mtlaunch mtline.com c.txt;/f mtline.com d.txt')
    k.run_for(0.3)
    sf = k.pc.text_screen()
    check('/F (SPF_FRONT): task 2 comes to the front at the first key wait, with a screen of its own (mode 3: the '
          'tasks\' prompts, not MTLAUNCH\'s lines)', tstate(k)[1] == 2 and k.pc.mode() == 3 and 'MTLINE>' in sf
          and 'MTLAUNCH' not in sf, (tstate(k), o, sf[-200:]))
    line(k, 'two')
    front(k, 1)
    line(k, 'one')
    check('... and when the front task ends, task 0\'s screen is back (MTLAUNCH\'s)', 'MTLAUNCH waits>' in k.pc.text_screen(),
          k.pc.text_screen()[-300:])
    line(k, '')
    check('... it got the first line ("two": D.TXT), task 1 the next ("one": C.TXT)',
          A.disk_file(k, 'D.TXT') == b'two' and A.disk_file(k, 'C.TXT') == b'one' and tstate(k)[0] == [(0, 1, 'Executive')],
          (A.disk_file(k, 'C.TXT'), A.disk_file(k, 'D.TXT'), tstate(k)))
    # each task its own current directory
    o = sh.run('mtlaunch mtcwd.com \\sub1 c1.txt;mtcwd.com \\sub2 c2.txt')
    front(k, 1); k.key('x'); k.run_for(0.5)
    front(k, 2); k.key('x'); k.run_for(0.5)
    line(k, '')
    o = sh.run('cd')
    c1, c2 = A.disk_file(k, 'SUB1\\C1.TXT'), A.disk_file(k, 'SUB2\\C2.TXT')
    check('each task its own current directory: task 1 in \\SUB1, task 2 in \\SUB2 (each writes its file there: '
          '\\SUB1\\C1.TXT, \\SUB2\\C2.TXT); the command prompt\'s still A:\\', c1 == b'\\SUB1' and c2 == b'\\SUB2'
          and o.split('\n')[0].strip() == 'A:\\', (c1, c2, o))
    # no room, no slot
    o = sh.run('mtlaunch /m:60000 mtline.com x.txt')
    line(k, '')
    check('no room for its region: MTLAUNCH: error 8 (and no task)', 'MTLAUNCH: error 8' in o and tstate(k)[0] == [(0, 1, 'Executive')], o)
    o = sh.run('mtlaunch /m:65535 mtline.com x.txt')
    line(k, '')
    check('... and a region past 1 MB (its size overflows): error 8 too', 'MTLAUNCH: error 8' in o and tstate(k)[0] == [(0, 1, 'Executive')], o)
    o = sh.run('mtlaunch /r:8 /m:64 mtline.com e.txt')
    check('8 at once: tasks 1 to 7, then MTLAUNCH: error 4 (the table is full)',
          all('task %d' % i in o for i in range(1, 8)) and 'MTLAUNCH: error 4' in o and len(tstate(k)[0]) == 8, (o, tstate(k)))
    got = []
    for i in range(1, 8):
        front(k, i); line(k, 'e%d' % i); got.append(A.disk_file(k, 'E.TXT'))
    line(k, '')
    check('... each of the 7 in turn gets its own line (and writes E.TXT), ends, and memory and files are as before',
          got == [b'e%d' % i for i in range(1, 8)] and tstate(k)[0] == [(0, 1, 'Executive')]
          and merged(mcbs(k)) == a0 and sft_used(k) == used0, (tstate(k), got))
    # to the front through the API (AL=13h)
    o = sh.run('mtlaunch mtline.com g1.txt;mtline.com g2.txt;/g:2')
    k.run_for(0.3)
    check('MT_FRONT (AL=13h, MTLAUNCH /G:2): task 2 to the front at the next key wait', tstate(k)[1] == 2 and 'error' not in o, (tstate(k), o))
    line(k, 'gg')
    front(k, 1); line(k, 'g')
    line(k, '')
    check('... it got the line ("gg": G2.TXT)', A.disk_file(k, 'G2.TXT') == b'gg' and A.disk_file(k, 'G1.TXT') == b'g'
          and tstate(k)[0] == [(0, 1, 'Executive')], (A.disk_file(k, 'G1.TXT'), A.disk_file(k, 'G2.TXT'), tstate(k)))
    # a program that isn't there
    o = sh.run('mtlaunch nosuch.com')
    line(k, '')
    check('a task whose program isn\'t there: it starts (task 1), its EXEC fails, it ends; memory and files as before',
          'task 1' in o and tstate(k)[0] == [(0, 1, 'Executive')] and merged(mcbs(k)) == a0 and sft_used(k) == used0
          and 'Lodestone version' in sh.run('ver'), (o, tstate(k)))
    # the spawner ends first
    sh.run('mtlaunch mtline.com s.txt')
    line(k, '')
    st = tstate(k)
    o = sh.run('mtlaunch')
    front(k, 1); line(k, 'late')
    line(k, '')
    check('the spawner ends first (its task waits on); later, at another key wait, the task gets its line ("late": S.TXT) '
          'and ends; memory and files as before', st[0] == [(0, 1, 'Executive'), (1, 2, 'MTLINE.COM')]
          and A.disk_file(k, 'S.TXT') == b'late' and tstate(k)[0] == [(0, 1, 'Executive')] and merged(mcbs(k)) == a0
          and sft_used(k) == used0, (st, tstate(k), A.disk_file(k, 'S.TXT')))

def file_lbas(path, name):
    """A file's sectors (LBAs) on a 1.44 MB FAT12 image."""
    d = open(path, 'rb').read()
    fat, out = d[512:512 + 9 * 512], []
    for i in range(224):
        e = d[19 * 512 + i * 32:19 * 512 + i * 32 + 32]
        if e[:11] == name:
            cl = e[26] | e[27] << 8
            while 2 <= cl < 0xFF8:
                out.append(33 + cl - 2)
                v = fat[cl * 3 // 2] | fat[cl * 3 // 2 + 1] << 8
                cl = v >> 4 if cl & 1 else v & 0xFFF
    return out

HOT = 0xA500                            # CODE-Tab (as AH=10h gives it on the 1520)

def hot(k):
    k.key(HOT); k.run_for(0.4)

def ems_used(k): return k.pc.rd(0x60, k.Y['ems_used'], 1)[0]

def no_hot(k): return not any(w in (0xA500, 0xA5F0) for w in k.pc.kbd_ring())

def t_front():
    print('== the front: CODE-Tab to the next task, each task its own screen')
    k = boot('mt_h.img', b'MULTITASK=1\r\n', 88)
    sh = Shell(k)
    sh.run('ver')
    a0, used0, e0 = merged(mcbs(k)), sft_used(k), ems_used(k)
    sh.run('mtlaunch mtline.com a.txt;mtline.com b.txt')
    e1 = ems_used(k)
    check('each task\'s screen: 2 EMS pages of its own (task 1, task 2: 4 more pages in use)', e1 == e0 + 4, (e0, e1))
    scr0, cur0, bd0 = k.pc.text_screen(), k.pc.cursor(), bytes(k.pc.rd(0x40, 0x49, 30))
    hot(k)
    s1, s_1 = k.pc.text_screen(), shd(k)
    check('CODE-Tab while MTLAUNCH waits: task 1 to the front, the key taken out of the buffer; its screen, never shown '
          'yet: mode 3, its prompt (printed in the background) and nothing else; shadowed from there (mt_shd 1)',
          tstate(k)[1] == 1 and no_hot(k) and s1.strip() == 'MTLINE>' and k.pc.mode() == 3 and s_1 == 1,
          (tstate(k), k.pc.kbd_ring(), s_1, s1[-200:]))
    k.key('hel'); k.run_for(0.3)
    check('... what is typed goes to task 1, and shows on its screen', 'hel' in k.pc.text_screen(), k.pc.text_screen()[-200:])
    hot(k)
    check('CODE-Tab again: task 2, its own prompt only; task 1, its prompt printed behind and "hel" in front (shadowed), '
          'found not to write the screen itself', tstate(k)[1] == 2 and k.pc.text_screen().strip() == 'MTLINE>'
          and vflags(k, 1) & VF_DIRECT == 0, (tstate(k), vflags(k, 1), k.pc.text_screen()[-200:]))
    hot(k)
    check('and again: round to task 0, MTLAUNCH\'s screen back as it was, its cursor and BIOS video data too',
          tstate(k)[1] == 0 and k.pc.text_screen() == scr0 and k.pc.cursor() == cur0 and bytes(k.pc.rd(0x40, 0x49, 30)) == bd0,
          (tstate(k), k.pc.cursor(), cur0, k.pc.text_screen()[-300:]))
    hot(k)
    check('and again: task 1, its screen back ("hel")', tstate(k)[1] == 1 and 'hel' in k.pc.text_screen()
          and 'MTLAUNCH' not in k.pc.text_screen(), (tstate(k), k.pc.text_screen()[-200:]))
    line(k, 'lo')
    check('task 1 gets "lo" ("hello": its line kept) and ends: task 0 in front, MTLAUNCH\'s screen back',
          A.disk_file(k, 'A.TXT') == b'hello' and tstate(k)[1] == 0 and k.pc.text_screen() == scr0,
          (A.disk_file(k, 'A.TXT'), tstate(k), k.pc.text_screen()[-300:]))
    hot(k)
    line(k, 'world')
    line(k, '')
    check('CODE-Tab with tasks 0 and 2 left: task 2 (B.TXT "world"); all ended, memory, files and EMS pages as before',
          A.disk_file(k, 'B.TXT') == b'world' and tstate(k) == ([(0, 1, 'Executive')], 0, 0) and merged(mcbs(k)) == a0
          and sft_used(k) == used0 and ems_used(k) == e0, (A.disk_file(k, 'B.TXT'), tstate(k), ems_used(k), e0))
    # a graphics screen kept
    o = sh.run('mtlaunch /f mtmode.com 40 m.txt')
    k.run_for(0.5)
    v1, m1 = bytes(k.pc.rd(0xB800, 0, 0x8000)), k.pc.mode()
    hot(k)
    s0, m0 = k.pc.text_screen(), k.pc.mode()
    hot(k)
    v2, m2 = bytes(k.pc.rd(0xB800, 0, 0x8000)), k.pc.mode()
    k.key('x'); k.run_for(0.5)
    line(k, '')
    check('MTMODE in mode 40h (640 x 400, 32 KB), in front; CODE-Tab to task 0 (text, mode 3: MTLAUNCH\'s screen), CODE-Tab '
          'back: mode 40h and its 32 KB as they were; MTMODE finds its pattern intact (M.TXT "ok")',
          m1 == 0x40 and m0 == 3 and 'MTLAUNCH waits>' in s0 and m2 == 0x40 and v2 == v1 and A.disk_file(k, 'M.TXT') == b'ok'
          and tstate(k)[0] == [(0, 1, 'Executive')], (hex(m1), hex(m0), hex(m2), v1 == v2, A.disk_file(k, 'M.TXT')))
    # a CGA mode: its palette (3D9h) back before the screen
    o = sh.run('mtlaunch /f mtmode.com 04 n.txt')
    k.run_for(0.5)
    k.pc.wr(0x40, 0x66, bytes([0x25])); k.pc.set_ccr(0x25)
    v1, m1 = bytes(k.pc.rd(0xB800, 0, 0x8000)), k.pc.mode()
    hot(k)
    ccr = []
    k.pc.on_ccr = lambda v: ccr.append((v, bytes(k.pc.rd(0xB800, 0, 0x4000)) == v1[:0x4000]))
    hot(k)
    k.pc.on_ccr = None
    v2, m2, c2, p2 = bytes(k.pc.rd(0xB800, 0, 0x8000)), k.pc.mode(), k.pc.ccr, k.pc.rd(0x40, 0x66, 1)[0]
    k.key('x'); k.run_for(0.5)
    line(k, '')
    check('MTMODE in mode 4 (CGA, palette 25h in 40:66h and 3D9h): CODE-Tab away and back: mode 4, 3D9h 25h (written '
          'after the mode set, before the screen), 40:66h 25h, the screen as it was (N.TXT "ok")',
          m1 == 4 and m2 == 4 and c2 == 0x25 and p2 == 0x25 and v2 == v1 and ccr and ccr[-1] == (0x25, False)
          and A.disk_file(k, 'N.TXT') == b'ok', (hex(m1), hex(m2), hex(c2), hex(p2), ccr, v2 == v1, A.disk_file(k, 'N.TXT')))
    o = sh.run('mtlaunch mtline.com c.txt')
    hot(k)
    st1 = tstate(k)
    hot(k)
    st2 = tstate(k)
    front(k, 1); line(k, 'c'); line(k, '')
    check('CODE-Tab twice with one task besides task 0: to it, and back to task 0; the task goes on as before',
          st1[1] == 1 and st2[1] == 0 and A.disk_file(k, 'C.TXT') == b'c', (st1, st2, A.disk_file(k, 'C.TXT')))
    # typed before CODE-Tab: still the front task's
    sh.run('mtlaunch mtline.com t1.txt')
    k.key('x', 'y', HOT, 'z', ktest.ENTER, settle=False); k.run_for(1.5)
    st = tstate(k)
    line(k, '')
    check('"xy", CODE-Tab, "z", Enter typed ahead: MTLAUNCH (in front) reads "xy" first, then task 1 comes to the front '
          'and gets "z" (T1.TXT)', A.disk_file(k, 'T1.TXT') == b'z', (A.disk_file(k, 'T1.TXT'), st))
    # at the command prompt, a task left waiting
    sh.run('mtlaunch mtline.com l.txt')
    line(k, '')
    k.key(HOT); k.run_for(0.4)
    st = tstate(k)
    check('CODE-Tab at the command prompt, a task waiting: it comes to the front (M4b: LCMD asks with INT 21h AH=0Bh, '
          'whose INT 16h call finds CODE-Tab first; the switch is made at the next safe point), the key not left behind',
          st[0] == [(0, 1, 'Executive'), (1, 2, 'MTLINE.COM')] and st[1] == 1 and no_hot(k), (st, k.pc.kbd_ring()))
    line(k, 'late'); line(k, '')
    v = sh.run('ver')
    check('... it gets its line ("late": L.TXT); ended, the prompt goes on', A.disk_file(k, 'L.TXT') == b'late'
          and tstate(k) == ([(0, 1, 'Executive')], 0, 0) and 'Lodestone version' in v and ems_used(k) == e0,
          (A.disk_file(k, 'L.TXT'), tstate(k), v))
    # a program frees task 0's screen handle
    h0 = k.pc.rd(mt_seg(k), k.Y['mt_tab'] + TE_SH, 1)[0]
    sh.run('mtlaunch freeh.com %d;mtline.com f.txt' % h0)
    hot(k)
    st, h1 = tstate(k), k.pc.rd(mt_seg(k), k.Y['mt_tab'] + TE_SH, 2)
    hot(k)
    sc, m = k.pc.text_screen(), k.pc.mode()
    hot(k); line(k, 'f'); line(k, '')
    v = sh.run('ver')
    check('FREEH frees task 0\'s screen handle (%d): at the next CODE-Tab its pages can\'t be mapped, so it keeps none '
          '(TE_SH 0, nothing copied), and comes back clear in mode 3; the task goes on; EMS 2 pages fewer in use '
          '(FREEH\'s doing), no more' % h0, st[1] == 2 and bytes(h1) == b'\0\0' and sc.strip() == '' and m == 3
          and A.disk_file(k, 'F.TXT') == b'f' and 'Lodestone version' in v and ems_used(k) == e0 - 2 and not k.crashed,
          (st, bytes(h1).hex(), sc[-200:], A.disk_file(k, 'F.TXT'), ems_used(k), e0))
    # keys AH=01h drops, ahead of CODE-Tab; and one it doesn't
    k = boot('mt_hk.img', b'MULTITASK=1\r\n', 88)
    sh = Shell(k)
    sh.run('ver')
    got = []
    for tag, ahead in (('CODE-? (35F0h)', 0x3500), ('Ctrl-Up (8D00h)', 0x8D00), ('a character F0h (00F0h)', 0x00F0)):
        sh.run('mtlaunch mtline.com k.txt')
        k.key(ahead, HOT, 'z', ktest.ENTER, settle=False); k.run_for(1.5)
        got.append((tag, A.disk_file(k, 'K.TXT'), tstate(k)[0]))
        line(k, '')
    check('ahead of CODE-Tab: keys the BIOS drops for AH=01h (CODE-?, Ctrl-Up) don\'t hold it back; a character (00F0h) '
          'is the front task\'s, read first; each time task 1 gets "z"',
          all(f == b'z' and len(st) == 1 for tag, f, st in got), got)
    # a handle freed by a program, given out again
    e0 = ems_used(k)
    h0 = k.pc.rd(mt_seg(k), k.Y['mt_tab'] + TE_SH, 1)[0]
    sh.run('mtlaunch freeh.com %d' % h0)
    line(k, '')
    sh.run('mtlaunch mtline.com r.txt')
    hs = [k.pc.rd(mt_seg(k), k.Y['mt_tab'] + i * MT_ENT + TE_SH, 1)[0] for i in (0, 1)]
    hot(k); k.key('abc'); k.run_for(0.3)
    hot(k)
    s0 = k.pc.text_screen()
    hot(k)
    s1 = k.pc.text_screen()
    line(k, ''); line(k, '')
    check('task 0\'s handle (%d) freed by FREEH, then given to task 1 by MT_SPAWN: task 0 keeps none (TE_SH 0), so '
          'task 1\'s screen isn\'t written over ("abc" still there after task 0 has been in front, clear); EMS: '
          'only FREEH\'s 2 pages fewer' % h0, hs == [0, h0] and s0.strip() == '' and 'abc' in s1
          and ems_used(k) == e0 - 2 and tstate(k)[0] == [(0, 1, 'Executive')], (hs, s0[-100:], s1[-100:], ems_used(k), e0))
    # freed while its task is in the background, its screen kept
    k = boot('mt_hb.img', b'MULTITASK=1\r\n', 88)
    sh = Shell(k)
    sh.run('ver')
    h0 = k.pc.rd(mt_seg(k), k.Y['mt_tab'] + TE_SH, 1)[0]
    sh.run('mtlaunch /f mtline.com b2.txt;freeh.com %d' % h0)
    k.run_for(0.5)
    st, sf = tstate(k), k.pc.rd(mt_seg(k), k.Y['mt_tab'] + TE_SH, 2)
    hot(k)
    sc, m, h1 = k.pc.text_screen(), k.pc.mode(), k.pc.rd(mt_seg(k), k.Y['mt_tab'] + TE_SH, 2)
    set_vflags(k, 0, VF_DIRECT)
    hot(k)
    v_g = vflags(k, 0)
    line(k, 'b'); line(k, '')
    check('task 0\'s screen kept (task 1 in front with /F), then its handle freed (FREEH, task 2): back in front it '
          'can\'t be mapped, so task 0 comes back clear in mode 3 and keeps none (switched from again, nothing compared: '
          'not marked as writing the screen itself); the rest goes on',
          st[1] == 1 and bytes(sf) == bytes([h0, 1]) and sc.strip() == '' and m == 3 and bytes(h1) == b'\0\0'
          and v_g & VF_DIRECT == 0
          and A.disk_file(k, 'B2.TXT') == b'b' and 'Lodestone version' in sh.run('ver'),
          (st, bytes(sf).hex(), sc[-100:], bytes(h1).hex(), A.disk_file(k, 'B2.TXT')))
    # no EMS for a task's screen
    k = boot('mt_hf.img', b'MULTITASK=1\r\nMDISK=1344\r\n', 88)
    sh = Shell(k)
    sh.run('ver')
    a0, used0, e0 = merged(mcbs(k)), sft_used(k), ems_used(k)
    o = sh.run('mtlaunch mtline.com x.txt')
    line(k, '')
    check('no EMS left for a task\'s screen (MDISK=1344): MTLAUNCH: error 8; its region given back, memory, files and '
          'EMS as before', 'MTLAUNCH: error 8' in o and tstate(k)[0] == [(0, 1, 'Executive')] and merged(mcbs(k)) == a0
          and sft_used(k) == used0 and ems_used(k) == e0, (o, ems_used(k), e0))
    # no EMS for a screen
    k = boot('mt_he.img', b'MULTITASK=1\r\nMDISK=9999\r\n', 88)
    o = Shell(k).run('tasks || echo FAILED')
    check('MDISK= all of EMS and MULTITASK=1: no pages left for task 0\'s screen, so multitasking stays off (TASKS says so)',
          mt_seg(k) is None and OFF_MSG in o and A.md_pages(k) > 0, (show(mcbs(k)), o, A.md_pages(k)))

def typ(k, s, t=0.5):
    """Type a command without waiting for the machine to go idle (a task may be computing)."""
    k.key(s, settle=False); k.key(ktest.ENTER, settle=False); k.run_for(t)

class Baseline:
    """The machine with the Executive alone (H5): the arena (merged), the SFT entries in use and the EMS pages
    as they are now.  back(): all three as they were, nothing crashed; now(): what to show when not.  A test
    that takes them again sets m0, s0, e0."""
    def __init__(s, k):
        s.k = k
        s.m0, s.s0, s.e0 = merged(mcbs(k)), sft_used(k), ems_used(k)
    def alone(s): return tstate(s.k)[0] == [(0, 1, 'Executive')]
    def back(s):
        k = s.k
        return s.alone() and merged(mcbs(k)) == s.m0 and sft_used(k) == s.s0 and ems_used(k) == s.e0 and not k.crashed
    def now(s): return (tstate(s.k), show(mcbs(s.k)), sft_used(s.k), s.s0, ems_used(s.k), s.e0)

class TermView:
    """A terminal window's test helpers (H5): MT's bytes, the first session's TERM.RUN (its variables, its window
    record), the screen, keys typed into the window, the clipboard's EMS page."""
    def __init__(s, k):
        s.k, s.seg, s.Y = k, mt_seg(k), k.Y
        s._ts = None
    @property
    def TS(s):
        if s._ts is None: s._ts = A.run_syms('apps/TERM.ASM')
        return s._ts
    def mb(s, n): return s.k.pc.rd(s.seg, s.Y[n], 1)[0]
    def base(s): return s.k.pc.u16(s.seg, s.Y['mw_ses'] + SE_SIZE + SE_BASE)      # (the first session's slot)
    def tv(s, n): return s.k.pc.u16(s.k.useg, s.base() + s.TS[n])
    def tb(s, n): return s.k.pc.rd(s.k.useg, s.base() + s.TS[n], 1)[0]
    def wv(s, o): return s.k.pc.u16(s.k.useg, s.base() + s.TS['win'] + o)          # (W_COL 0, W_Y 2, W_W 4, W_H 6)
    def scr(s): return '\n'.join(l for y, l in s.k.ocr())
    def tnum(s, name): return next((i for i, s_, n in tstate(s.k)[0] if n == name), 7)
    def tx(s, n): return s.k.pc.u16(s.seg, task_ent(s.k, n) + TE_TX)
    def typ2(s, text, t=1.0):
        k = s.k
        k.key(text, settle=False); k.key(ktest.ENTER, settle=False); k.run_for(t)
    def to0(s):
        for _ in range(8):
            if tstate(s.k)[1] == 0: break
            hot(s.k); s.k.run_for(1.0)
    def drawn(s, r, c):                 # the 16 bytes on the screen of the task's cell (r, c) in the window
        tv = s.tv
        d = (tv('y0') + (r - tv('top')) * 16) * 20 + tv('x0') + c - tv('left')
        return bytes(s.k.pc.rd(0xB800, d + (y & 3) * 0x2000 + (y >> 2) * 80, 1)[0] for y in range(16))
    def cxy(s, r, c):                   # the middle of the task's screen cell (r, c) in the window
        tv = s.tv
        return (tv('x0') + c - tv('left')) * 8 + 4, tv('y0') + (r - tv('top')) * 16 + 8
    def mv(s, x, y):                    # (A.point without its settle: a task may be busy)
        k = s.k
        dx, dy = x - k.u16('mx'), y - k.u16('my')
        while dx or dy:
            sx, sy = max(-100, min(100, dx)), max(-100, min(100, dy))
            k.pc.mouse_move(sx & 0xFF, sy & 0xFF); k.pc.run_for(0.05)
            dx -= sx; dy -= sy
    def btn(s, b, t=0.3):               # buttons b down a moment (the UI looks at them as it can), then up
        k = s.k
        k.pc.mouse_move(0, 0, b); k.pc.run_for(0.2); k.pc.mouse_move(0, 0, 0); k.pc.run_for(t)
    def page(s):                        # the clipboard's EMS page (KEMS's tables)
        k, Y = s.k, s.Y
        h = k.u16('clip_h')
        if not h: return None
        return k.pc.ems_page(k.pc.rd(0x60, Y['ems_ltab'] + k.pc.rd(0x60, Y['ems_h'] + h * 4, 1)[0], 1)[0])
    def clip(s):
        pg = s.page()
        return b'' if pg is None else s.k.pc.ems_read(pg, 0, s.k.u16('clip_len'))

def tclick(k, x, y, settle=True):
    """A.click with the button held 60 ms, over a tick: with tasks computing behind, the Executive idle gives its
    turn away (T5d) and the mouse brings it back at the next tick (mt_mwant); the UI reads the buttons' state, so a
    shorter click between two ticks is missed.  settle=False: no wait after the release (see bclick)."""
    dx, dy = x - k.u16('mx'), y - k.u16('my')
    while dx or dy:
        sx, sy = max(-100, min(100, dx)), max(-100, min(100, dy))
        k.pc.mouse_move(sx & 0xFF, sy & 0xFF); k.pc.run_for(0.05)
        dx -= sx; dy -= sy
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.06); k.pc.mouse_move(0, 0, 0)
    if settle: k.settle()

def took(k, what, mouse=False, within=1.0):
    """Run till the keys given (and with mouse, the mouse's packets) are taken: a failure if not within `within` s."""
    e = k.pc.us + within * 1e6
    left = lambda: k.pc.keys or (mouse and k.pc.uart['rx'])
    while left() and k.pc.us < e and k.pc.run(): pass
    if left():
        check('%s taken within %.1f s, a task computing behind' % (what, within), False,
              (list(k.pc.keys), k.pc.uart['rx'], k.crashed))

def bkey(k, *keys, t=0.5):
    """k.key with a task computing behind: the machine never waits then, so a default settle would run to its 6 s
    timeout.  Each key (a string: all of it) given alone and taken (took), then t s for what it does (audit3 H2)."""
    for x in keys:
        k.key(x, settle=False); took(k, 'the key %r' % (x,))
    k.run_for(t)

def bclick(k, x, y, t=0.3):
    """A click as bkey's keys: tclick's, held over a tick (A.click's 50 ms press, with no 6 s wait before it to set
    the phase, can fall between two ticks and be missed), taken (took), then t s."""
    tclick(k, x, y, settle=False); took(k, 'a click at (%d, %d)' % (x, y), True); k.run_for(t)

def spun(k, name):
    v = A.disk_file(k, name)
    return int(v, 16) if v else 0

class Audit:
    """Every arrival at mt_preempt (mt_safe said yes): the interrupted or calling code's CS:IP and flags, read
    from the frame on its own stack (mt_tick's or INT 21h's, told apart by mt_preempt's return address), checked
    against every rule, the task's own memory found from the arena; whether it switched (mt_switch reached from
    there); the stack used below the caller's SP until its frame is popped or its code runs (every block of that
    task's on that stack: MT's, the kernel's, the UI's, the BIOS's, interrupts' to them).
    Every call of mt_safe that fails one rule alone counts under that rule (only), so the tests can show each one
    was met.  force: a switch due on every INT 21h way out (mt_pend set at mt_exit), so every one is checked."""
    def __init__(s, k):
        s.k, s.ev, s.force, s.track = k, [], False, None
        s.depth, s.only = {'tick': 0, 'exit': 0, 'v10': 0, 'i16': 0, 'peek': 0}, collections.Counter()
        s.seg = seg = mt_seg(k)
        s.at, s.sa, s.swa, s.ex = (seg * 16 + k.Y[n] for n in ('mt_preempt', 'mt_safe', 'mt_switch', 'mt_exit'))
        s.srqi, s.tick, s.srq = seg * 16 + k.Y['mt_srqi'], seg * 16 + k.Y['mt_tick'], False
        s.i0e = seg * 16 + k.Y['mt_i0e']     # (M10: mt_tick's tail from IRQ 6, the floppy's)
        s.wf = seg * 16 + k.Y['mt_wfront']   # (a background task waiting at INT 10h to be in front)
        s.wk = seg * 16 + k.Y['mt_wkey']     # (a task waiting at INT 16h for a key)
        s.pss = None
        s.lo, s.go, s.cur = s.swa, seg * 16 + k.Y['mt_load.go'], None    # (mt_cur, when known: see watch)
        s.stale = False                                                   # (rules found s.cur wrong: said once)
        s.fd, s.fdw, s.due = seg * 16 + k.Y['mt_fdrain'], seg * 16 + k.Y['mt_fdrain.w'], False
        s.inject, s.injected, s.open, s.nested = None, 0, {}, collections.Counter()
        # (IRQ 13 at mt_fdrain, when inject() says; open drains: SS -> the SP and where its call returns; switches
        #  started inside one, by path)
        s.ret = {k.Y['mt_tick.r']: 'tick', k.Y['mt_exit.n']: 'exit', k.Y['mt_v10.wf']: 'v10', k.Y['mt_i16.wk']: 'i16',
                 k.Y['mt_wkey.sw']: 'i16', k.Y['mt_i16.pk']: 'peek'}
        s.prev, k.pc.watch = k.pc.watch, s.watch
    def stop(s): s.k.pc.watch = s.prev
    def mine(s, x, task, reg, psp, root, ui):
        """Segment x in the running task's own memory: its region; task 0's: the UI's block (the Executive
        running), else a block cur_psp owns."""
        pc = s.k.pc
        if task: return reg <= x < reg + pc.u16(reg - 1, 3)
        if psp == root: return ui <= x < ui + pc.u16(ui - 1, 3)
        return any(seg < x <= seg + sz and own == psp for seg, t, own, sz, nm in mcbs(s.k))
    def rules(s, cs, ip, fl, ss):
        pc, Y = s.k.pc, s.k.Y
        cur = pc.rd(s.seg, Y['mt_cur'], 1)[0]
        if s.cur is not None and s.cur != cur and not s.stale:     # (watch's mt_cur, kept from mt_load.go: wrong
            s.stale = True                                          #  if mt_cur had another writer, or mt_load
            check('Audit: mt_cur as kept since mt_load.go (%d), as read (%d)' % (s.cur, cur), False)  # another way out)
        reg = pc.u16(s.seg, Y['mt_tab'] + cur * MT_ENT + TE_REG)
        ui, psp, root = pc.u16(0x60, Y['ui_seg']), pc.u16(0x60, Y['cur_psp']), pc.u16(0x60, Y['root_psp'])
        ts = pc.u16(s.seg, Y['mt_tsrs'])                # (Resident Claude's stub, MT_TSR: only at its HLT, in a
        stub = ts != 0 and cs == ts                     #  read of the program's own: its frame's CS, at the
        caller = pc.u16(ss, pc.u16(s.seg, Y['mt_lsp']) + 2)   # interrupted SP, the task's and not the UI's)
        r = dict(cs=cs < 0xA000 and cs not in (0x60, s.seg) and (cs != ui or ip in (Y['..@ui_idle'], Y['..@ui_sidle'], Y['..@ui_midle']))
                 and (not stub or (ip == pc.u16(s.seg, Y['mt_tsro']) and pc.rd(cs, ip - 1, 1) == b'\xf4'
                                   and caller != ui and s.mine(caller, cur, reg, psp, root, ui))),
                 iff=bool(fl & 0x200), isr=pc.isr == 0, indos=pc.rd(0x60, Y['indos'], 1)[0] == 0,
                 busy=pc.rd(ui, Y['m33_busy'], 1)[0] == 0, ss=s.mine(ss, cur, reg, psp, root, ui),
                 own=cs == ui or stub or s.mine(cs, cur, reg, psp, root, ui))
        return r, cur
    def watch(s, a):
        if s.prev: s.prev(a)
        k, pc = s.k, s.k.pc
        if s.lo <= a <= s.go:                           # (mt_cur's one writer is in mt_load: unknown from
            s.cur = pc.rd(s.seg, k.Y['mt_cur'], 1)[0] if a == s.go else None    # mt_switch on, read again at
        had = s.track                                   #  mt_load.go, the one way back into a task)
        if had and (s.cur is None or s.cur == had[3]):  # (another task running: nothing to read)
            ss, sp, cs = pc.r('ss'), pc.r('sp'), pc.r('cs')
            new, s.pss = ss != s.pss, ss
            cur = s.cur if s.cur is not None else pc.rd(s.seg, k.Y['mt_cur'], 1)[0]
            if new or ss != s.track[0] or cur != s.track[3]: pass
            elif sp >= s.track[1]: s.track = None       # (just loaded, between MOV SS and MOV SP; another task's,
            elif cs < 0xA000 and cs not in s.track[4]:  #  or MT's own stack; the frame gone: back in the caller,
                s.track = None                          #  or in its code)
            else: s.depth[s.track[2]] = max(s.depth[s.track[2]], s.track[1] - sp)
        if s.open:                                          # (back from that very mt_fdrain call: its RET's
            ss = pc.r('ss')                                 #  target, its SP above the return address)
            if ss in s.open and s.open[ss][1] == a and pc.r('sp') == s.open[ss][0] + 2: del s.open[ss]
        if a == s.fd:
            if s.inject is None: s.due = False; return      # (the drains' bookkeeping: t_fpu's IRQ 13 only)
            ss = pc.r('ss')
            again = ss in s.open                            # (a drain inside this task's: no second IRQ)
            if not again: s.open[ss] = (pc.r('sp'), s.seg * 16 + pc.u16(ss, pc.r('sp')))
            s.due = s.inject and not again and s.inject()
        elif a == s.fdw and s.due:                          # (interrupts on: raised and taken here, pcemu
            s.due = False                                   #  delivering IRQs as its run loop starts again)
            pc.irq_pending.add(13); s.injected += 1; pc.mu.emu_stop()
        elif a == s.ex:
            if s.force and pc.rd(s.seg, k.Y['mt_pend'], 1)[0] == 0: pc.wr(s.seg, k.Y['mt_pend'], b'\1')
        elif a in (s.srqi, s.tick, s.i0e):
            s.srq = {s.srqi: 'srq', s.i0e: 'fd'}.get(a)       # (mt_tick's tail reached from the SRQ's interrupt, or
                                                            #  M10's IRQ 6)
        elif a == s.sa:
            r, cur = s.rules(pc.r('ax'), pc.r('bx'), pc.r('dx'), pc.r('ss'))
            no = [n for n, ok in r.items() if not ok]
            if len(no) == 1: s.only[no[0]] += 1
        elif a in (s.at, s.wf, s.wk):
            ss, sp = pc.r('ss'), pc.r('sp')
            if had: s.pss = ss                              # (as each block's read keeps it, the reads skipped or not)
            path = s.ret.get(pc.u16(ss, sp), '?')
            if a == s.wf and path != 'v10': path = '?'
            if a == s.wk and path != 'i16': path = '?'
            if a != s.wk and path == 'i16': path = '?'
            if a != s.at and path == 'peek': path = '?'
            if ss in s.open: s.nested[path] += 1            # (inside a drain of this task's, its IRQ 13 handler's)
            f = sp + 12 if path == 'tick' else sp + 4 + 20     # (mt_tick's 5 pushes, or BP and INT 21h's frame: IP, CS, FL)
            if path in ('v10', 'i16', 'peek'): f = pc.r('bp') + 2    # (mt_v10's or mt_i16's BP: the INT frame after it)
            ip, cs, fl = pc.u16(ss, f), pc.u16(ss, f + 2), pc.u16(ss, f + 4)
            r, cur = s.rules(cs, ip, fl, ss)
            if path == 'tick':          # (else a hook ahead was interrupted: INT 08h's, or from mt_srqi IRQ 5's)
                r['ivt'] = (vec(k, 0x0D) == (0x60, k.Y['gp_isr']) if s.srq == 'srq' else
                            vec(k, 0x0E) == (s.seg, k.Y['mt_i0e']) if s.srq == 'fd' else
                            vec(k, 8) == (s.seg, k.Y['mt_tick']))
            s.ev.append(dict(path=path, cs=cs, ip=ip, fl=fl, task=cur, ss=ss, csp=f + 6, r=r, sw=False,
                             ok=path != '?' and all(r.values())))
            s.track = (ss, f + 6, path, cur, (s.seg, 0x60, pc.u16(0x60, k.Y['ui_seg'])))   # (the caller's SP:
                                                                 #  under the frame; MT, the kernel, the UI)
        elif a == s.swa and s.ev and pc.u16(pc.r('ss'), pc.r('sp')) in s.ret:
            s.ev[-1]['sw'] = True
    def bad(s): return [e for e in s.ev if not e['ok']]
    def switches(s, n=0, path=None): return [e for e in s.ev[n:] if e['sw'] and path in (None, e['path'])]

def t_preempt():
    print('== preemption: tasks switched at the tick, where it is safe')
    pad = os.path.join(A.OUT, 'PAD3.BIN'); open(pad, 'wb').write(bytes(300000))
    k = boot('mt_p.img', b'MULTITASK=1\r\n', 88, 'PAD.BIN=' + pad)
    au = Audit(k)
    sh = Shell(k)
    sh.run('ver')
    typ(k, 'mtlaunch mtspin.com 20 c0.txt', 2.5); line(k, '')
    typ(k, 'mtlaunch mtspin.com 20 c1.txt;mtspin.com 20 c2.txt', 2.5); line(k, '')
    c0, c1, c2 = spun(k, 'C0.TXT'), spun(k, 'C1.TXT'), spun(k, 'C2.TXT')
    fat = k.pc.rd(0x60, k.Y['fatbuf'] + 0x17B, 1)[0]
    check('two MTSPINs (no INT 21h, nothing printed) take turns at the tick: each counts about half what one alone '
          'does in the same 20 ticks (alone %d; %d and %d), on a floppy 300 KB full (the FAT\'s byte 17Bh, which MT once '
          'read for the UI\'s m33_busy, %02Xh)' % (c0, c1, c2, fat),
          c0 > 0 and 0.3 * c0 < c1 < 0.7 * c0 and 0.3 * c0 < c2 < 0.7 * c0 and fat != 0, (c0, c1, c2, fat))
    typ(k, 'mtlaunch /f mtspin.com 20 c3.txt;mtspin.com 20 c4.txt', 2.5); line(k, '')
    c3, c4 = spun(k, 'C3.TXT'), spun(k, 'C4.TXT')
    check('the front one\'s turn is 2 ticks, the other\'s 1: about twice as many counts (%d and %d)' % (c3, c4),
          c4 > 0 and 1.4 < c3 / c4 < 2.8, (c3, c4))
    typ(k, 'mtlaunch mtspin.com 20 d0.txt d', 2.5); line(k, '')
    n = len(au.ev)
    typ(k, 'mtlaunch mtspin.com 20 d1.txt d;mtspin.com 20 d2.txt d', 2.5); line(k, '')
    d0, d1, d2 = spun(k, 'D0.TXT'), spun(k, 'D1.TXT'), spun(k, 'D2.TXT')
    sw, dx, dt = len(au.switches(n)), len(au.switches(n, 'exit')), len(au.switches(n, 'tick'))
    # (each turn ends with a switch, at the tick or on INT 21h's way out; which of the two depends on where the
    #  ticks land in the spinners' loop, and that moves with the code's layout and what ran before: on one build,
    #  e.g., the split reversed between this group and the step run alone, the total the same; on M7b's first build, its
    #  MT block 72 paragraphs lower, all 20 on the way out.  The tick's are the first group's, with no INT 21h)
    check('the same with an INT 21h call on every count (AH=2Ch): about half each (alone %d; %d and %d); a switch at '
          'each turn\'s end, %d in all: %d at the tick, %d on INT 21h\'s way out' % (d0, d1, d2, sw, dt, dx),
          d0 > 0 and 0.3 * d0 < d1 < 0.7 * d0 and 0.3 * d0 < d2 < 0.7 * d0 and 18 <= sw <= 30 and dx >= 1
          and dt + dx == sw, (d0, d1, d2, sw, dt, dx))
    typ(k, 'mtlaunch mtspin.com 15 w1.txt w w1.dat;mtspin.com 15 w2.txt w w2.dat', 2.5); line(k, '')
    w1, w2 = spun(k, 'W1.TXT'), spun(k, 'W2.TXT')
    rec = b'0123456789ABCDEF' * 3 + b'0123456789ABCDE\n'
    check('two tasks writing a file each, 64 bytes a count, at once: both files whole (%d and %d records), the disk '
          'readable' % (w1, w2), w1 > 0 and w2 > 0 and A.disk_file(k, 'W1.DAT') == rec * w1
          and A.disk_file(k, 'W2.DAT') == rec * w2, (w1, w2, len(A.disk_file(k, 'W1.DAT') or b'')))
    # a key for the front task, waiting in DOS while two others compute
    typ(k, 'mtlaunch mtspin.com 40 l1.txt;mtspin.com 40 l2.txt', 0.6)
    t0 = k.pc.u16(0x40, 0x6C)
    k.key(ktest.ENTER, settle=False)
    for i in range(1000):
        k.run_for(0.005)
        if not k.pc.keys and k.pc.u16(0x40, 0x1A) == k.pc.u16(0x40, 0x1C): break
    lat = (k.pc.u16(0x40, 0x6C) - t0) & 0xFFFF
    k.run_for(2.5)
    check('MTLAUNCH in front waiting for a key, two MTSPINs behind it: Enter is taken within %d ticks (3 at most: the '
          'front task\'s turn comes as soon as a key is there)' % lat, lat <= 3 and spun(k, 'L1.TXT') and spun(k, 'L2.TXT'),
          (lat, spun(k, 'L1.TXT'), spun(k, 'L2.TXT')))
    # at the command prompt, then in the Executive
    typ(k, 'mtlaunch mtspin.com 30 p.txt', 0.5); typ(k, '', 3)
    p = spun(k, 'P.TXT')
    check('MTLAUNCH ended, LCMD\'s prompt in front (it polls, then HLTs): MTSPIN goes on in the background, most of '
          'the time (%d in 30 ticks; %d in 20 alone)' % (p, c0), p > 0.8 * c0, (p, c0))
    v = sh.run('ver')
    typ(k, 'mtlaunch mtspin.com 60 i.txt', 0.5); typ(k, '', 0.3); typ(k, 'exit', 0.5)
    k.run_for(3.5)
    i = spun(k, 'I.TXT')
    check('... and with the Executive idle in front (LCMD ended, no keys): its HLT ends its turn at once, so MTSPIN '
          'gets most of the time (%d in 60 ticks; %d in 20 alone)' % (i, c0), i > 1.5 * c0 and k.pc.mode() == 0x40, (i, c0))
    sh = Shell(k)
    sh.run('ver')
    typ(k, 'mtlaunch mtspin.com 60 e.txt', 0.5); typ(k, '', 0.3); typ(k, 'exit', 1.0)
    k.key(*[ktest.DOWN, ktest.UP] * 60, settle=False)  # (the Executive busy drawing: ticks land mid-UI too)
    k.run_for(3.5)
    e = spun(k, 'E.TXT')
    ui = [x for x in au.ev if x['cs'] == k.pc.u16(0x60, k.Y['ui_seg'])]
    check('... and with the Executive busy in front (moving its selection 120 times): it is switched from only at its '
          'idle HLT, MTSPIN runs (%d in 60 ticks), and the Executive is still there (mode 40h)' % e,
          e > c0 and ui and k.pc.mode() == 0x40 and not k.crashed, (e, len(ui), hex(k.pc.mode())))
    bad = au.bad()
    check('every one of the %d times mt_safe said yes (%d of them switched: %d at the tick, %d on INT 21h\'s way out) '
          'was at a safe point, read from the frame on the caller\'s own stack: CS below A000h, not the kernel\'s or '
          'MT\'s, in the UI only at its idle HLTs; interrupts on, none in service, outside INT 21h, no INT 33h handler; '
          'SS and CS the task\'s own memory' % (len(au.ev), len(au.switches()), len(au.switches(0, 'tick')),
          len(au.switches(0, 'exit'))), len(au.ev) > 50 and not bad, (len(au.ev), bad[:3]))
    print('   the stack used below the caller\'s SP while MT switches from it: %d bytes from the tick (with the '
          'interrupt\'s 6), %d on INT 21h\'s way out (with its 26-byte frame)' % (au.depth['tick'], au.depth['exit']))
    check('MT\'s use of a task\'s stack, every step of a switch from outside INT 21h: %d bytes at the tick, %d on the way '
          'out, under 64' % (au.depth['tick'], au.depth['exit']), 0 < au.depth['tick'] < 64 and 0 < au.depth['exit'] < 64,
          au.depth)
    au.stop()

def t_rules():
    print('== the safe-point rules, each one met')
    k = boot('mt_r.img', b'MULTITASK=1\r\n', 88)
    Y, seg = k.Y, mt_seg(k)
    au = Audit(k)
    sh = Shell(k)
    sh.run('ver')
    typ(k, 'mtlaunch mtspin.com 20 r0.txt', 2.5); line(k, '')
    r0 = spun(k, 'R0.TXT')
    # files open, as DEFRAG and System ask
    typ(k, 'mtspin 0 o0.txt o', 1.0)
    typ(k, 'mtlaunch mtspin.com 0 o1.txt o', 1.0); line(k, '')
    typ(k, 'mtlaunch mtspin.com 40 x.txt', 0.5); typ(k, '', 0.3); typ(k, 'mtspin 0 o2.txt o', 0.5); k.run_for(2.5)
    o = [A.disk_file(k, n) for n in ('O0.TXT', 'O1.TXT', 'O2.TXT')]
    check('F0h AL=1 (files open on A:, which DEFRAG and System ask before writing a disk\'s FAT themselves): none with '
          'only the Executive; at least 1 in a task (the Executive is another), and at the prompt with a task there (%s)'
          % b' '.join(x or b'-' for x in o).decode(), o == [b'00000000', b'00000001', b'00000001'], o)
    # an INT 33h event handler running
    ui = k.pc.u16(0x60, Y['ui_seg'])
    n, b0 = len(au.ev), au.only['busy']
    k.pc.wr(ui, Y['m33_busy'], b'\1')
    typ(k, 'mtlaunch mtspin.com 20 b1.txt;mtspin.com 20 b2.txt', 3.0); line(k, '')
    k.pc.wr(ui, Y['m33_busy'], b'\0')
    b1, b2 = spun(k, 'B1.TXT'), spun(k, 'B2.TXT')
    check('the UI\'s m33_busy set (an INT 33h event handler running): no switch from a task at all (%d refused for '
          'that alone), so the two MTSPINs run one after the other, each about as much as alone (%d and %d; %d)'
          % (au.only['busy'] - b0, b1, b2, r0), len(au.ev) == n and au.only['busy'] > b0 and b1 > 0.8 * r0 and b2 > 0.8 * r0,
          (len(au.ev) - n, b1, b2, r0))
    # interrupted with the direction flag set (STD ... REP MOVS, as a memmove backwards)
    typ(k, 'mtlaunch mtspin.com 20 x1.txt b;mtspin.com 20 x2.txt b', 2.5); line(k, '')
    x1, x2 = spun(k, 'X1.TXT'), spun(k, 'X2.TXT')
    check('two tasks counting with the direction flag set (STD), switched at the tick: MT copies their contexts forward '
          'all the same (CLD), and they take turns (%d and %d)' % (x1, x2),
          0.3 * r0 < x1 < 0.7 * r0 and 0.3 * r0 < x2 < 0.7 * r0 and not k.crashed, (x1, x2, r0))
    # a stack outside the task's memory
    n, s0 = len(au.ev), au.only['ss']
    typ(k, 'mtlaunch mtspin.com 20 s1.txt s;mtspin.com 20 s2.txt', 3.0); line(k, '')
    s1, s2 = spun(k, 'S1.TXT'), spun(k, 'S2.TXT')
    check('a task counting with its stack outside its memory (at B800h): never switched from there (%d refused for that '
          'alone), so it counts about as much as alone (%d; %d), the other after it (%d)' % (au.only['ss'] - s0, s1, r0, s2),
          au.only['ss'] > s0 and s1 > 0.8 * r0 and s2 > 0 and not [e for e in au.ev[n:] if e['ss'] == 0xB800], (s1, s2, r0))
    # INT 21h with interrupts off; INT 21h from INT 1Ch, IRQ 0 in service (a switch due on every way out)
    au.force = True
    f0 = au.only['iff']
    typ(k, 'mtlaunch mtspin.com 20 i1.txt c;mtspin.com 20 i2.txt c', 3.0); line(k, '')
    i1, i2 = spun(k, 'I1.TXT'), spun(k, 'I2.TXT')
    check('INT 21h called with interrupts off (CLI), a switch due on every way out: refused there for that alone (%d '
          'times); the two still take turns (%d and %d)' % (au.only['iff'] - f0, i1, i2), au.only['iff'] > f0 and i1 and i2,
          (au.only['iff'] - f0, i1, i2))
    q0, v1c = au.only['isr'], vec(k, 0x1C)
    typ(k, 'mtlaunch mtspin.com 20 h1.txt h;mtspin.com 20 h2.txt', 3.0); line(k, '')
    au.force = False
    h1, h2 = spun(k, 'H1.TXT'), spun(k, 'H2.TXT')
    check('a task\'s own INT 1Ch handler (STI, then INT 21h): refused on that way out for IRQ 0 in service alone (%d '
          'times); the two still take turns (%d and %d), INT 1Ch given back' % (au.only['isr'] - q0, h1, h2),
          au.only['isr'] > q0 and 0.3 * r0 < h1 < 0.8 * r0 and 0.3 * r0 < h2 < 0.8 * r0
          and vec(k, 0x1C) == v1c, (au.only['isr'] - q0, h1, h2, vec(k, 0x1C), v1c))
    # task 0 running a program (from the prompt) with its stack outside its own blocks, a task behind it
    s0 = au.only['ss']
    typ(k, 'mtlaunch mtspin.com 60 y0.txt', 0.5); typ(k, '', 0.3)
    typ(k, 'mtspin 20 s3.txt s', 1.5); typ(k, 'mtspin 20 f3.txt f', 1.5); k.run_for(3.5)
    s3, f3, y0 = spun(k, 'S3.TXT'), spun(k, 'F3.TXT'), spun(k, 'Y0.TXT')
    check('task 0 running MTSPIN from the prompt, its stack at B800h, then in a block it gave back (nobody\'s): never '
          'switched from there (%d refused for that alone, the arena walked), so each counts about as much as alone '
          '(%d and %d; %d); the task behind them counted (%d)' % (au.only['ss'] - s0, s3, f3, r0, y0),
          au.only['ss'] > s0 and s3 > 0.8 * r0 and f3 > 0.8 * r0 and y0, (au.only['ss'] - s0, s3, f3, r0, y0))
    # code outside the caller's memory, on its stack: a TSR's INT 62h
    typ(k, 'mthook s', 1.0)
    sv = vec(k, 0x62)
    o0, n = au.only['own'], len(au.ev)
    typ(k, 'mtlaunch mtspin.com 20 q1.txt r;mtspin.com 20 q2.txt', 3.0); line(k, '')
    q1, q2 = spun(k, 'Q1.TXT'), spun(k, 'Q2.TXT')
    check('a task calling a TSR\'s service (MTHOOK S\'s INT 62h: STI, 2 ticks there): never switched from inside it, CS '
          'not the task\'s (%d refused for that alone); both counted (%d and %d)' % (au.only['own'] - o0, q1, q2),
          sv[0] != STUB and au.only['own'] > o0 and q1 and q2 and not [e for e in au.ev[n:] if e['cs'] == sv[0]],
          (sv, au.only['own'] - o0, q1, q2))
    # INT 08h written in the vector table directly, by a task: ahead of mt_tick
    n = len(au.ev)
    typ(k, 'mtlaunch mtspin.com 20 t1.txt t;mtspin.com 20 t2.txt', 3.0); line(k, '')
    t1, t2 = spun(k, 'T1.TXT'), spun(k, 'T2.TXT')
    check('a task hooking INT 08h in the vector table itself (ahead of mt_tick, which then sees the hook, not the task, '
          'interrupted): no switch at the tick meanwhile, so it counts about as much as alone (%d; %d), the other after it '
          '(%d); the vector given back' % (t1, r0, t2), t1 > 0.8 * r0 and t2 > 0 and vec(k, 8) == (seg, Y['mt_tick']),
          (t1, t2, r0, vec(k, 8)))
    # a TSR hooking INT 08h (AH=35h/25h): ahead of mt_tick, for good
    typ(k, 'mtlaunch mtspin.com 20 kd.txt d', 2.5); line(k, '')
    kd = spun(k, 'KD.TXT')
    typ(k, 'mthook', 1.0)
    hk = vec(k, 8)
    got = (k.pc.u16(hk[0], 0x104), k.pc.u16(hk[0], 0x102))
    n = len(au.ev)
    typ(k, 'mtlaunch mtspin.com 20 k1.txt d;mtspin.com 20 k2.txt d', 2.5); line(k, '')
    k1, k2 = spun(k, 'K1.TXT'), spun(k, 'K2.TXT')
    typ(k, 'mtlaunch mtspin.com 20 k3.txt;mtspin.com 20 k4.txt', 3.0); line(k, '')
    k3, k4 = spun(k, 'K3.TXT'), spun(k, 'K4.TXT')
    ev = au.ev[n:]
    t0, b0 = k.pc.u16(seg, Y['mt_ticks']), k.pc.u16(0x40, 0x6C)
    k.run_for(1.0)
    t1_, b1 = k.pc.u16(seg, Y['mt_ticks']), k.pc.u16(0x40, 0x6C)
    check('a TSR hooking INT 08h with AH=35h/25h (STI, PUSHF / CALL FAR): ahead of mt_tick, chaining to it (mt_tick runs '
          'every tick); the tick switches nothing while it is there, INT 21h\'s way out still does: two MTSPINs calling '
          'INT 21h take turns (%d and %d; %d alone), two that don\'t run one after the other (%d and %d; %d alone)'
          % (k1, k2, kd, k3, k4, r0), hk[0] not in (seg, STUB) and got == (seg, Y['mt_tick']) and (t1_ - t0) == (b1 - b0) > 10
          and not [e for e in ev if e['path'] == 'tick'] and [e for e in ev if e['sw']]
          and 0.3 * kd < k1 < 0.7 * kd and 0.3 * kd < k2 < 0.7 * kd and k3 > 0.8 * r0 and k4 > 0.8 * r0,
          (hk, got, (t1_ - t0, b1 - b0), k1, k2, kd, k3, k4, r0))
    bad = au.bad()
    check('every one of the %d times mt_safe said yes in these was at a safe point (as in t_preempt)' % len(au.ev),
          not bad and not k.crashed, bad[:3])
    au.stop()
    # LCMD's screen saver: the UI's code, called from LCMD (task 0 running LCMD, its stack)
    k = boot('mt_sv.img', b'MULTITASK=1\r\n', 88)
    au = Audit(k)
    ui = k.pc.u16(0x60, Y['ui_seg'])
    k.pc.wr(ui, Y['saver_t'], bytes([36, 0]))           # (2 s: LCMD reads it when it starts)
    sh = Shell(k)
    typ(k, 'mtlaunch mtspin.com 100 sv.txt', 0.5); typ(k, '', 0.3)
    k.run_for(4.0)
    mode = k.pc.mode()
    k.run_for(2.0)
    sv = spun(k, 'SV.TXT')
    sid = [e for e in au.ev if e['cs'] == ui and e['ip'] == Y['..@ui_sidle'] and e['sw']]
    k.key(' '); k.run_for(1.0)
    check('LCMD\'s screen saver on at its prompt (the UI\'s code, on LCMD\'s stack): switched from at its idle HLT (%d '
          'times), so MTSPIN goes on (%d in 100 ticks; %d in 20 alone); a key ends it, back to the prompt'
          % (len(sid), sv, r0), mode == 0x40 and sid and sv > 2 * r0 and k.pc.mode() == 3 and not au.bad(),
          (hex(mode), len(sid), sv, r0, hex(k.pc.mode()), au.bad()[:2]))
    au.stop()

def t_ends():
    print('== tasks that end otherwise: aborted, resident')
    pad = os.path.join(A.OUT, 'PAD.BIN'); open(pad, 'wb').write(bytes(70000))
    k = boot('mt_ab.img', b'MULTITASK=1\r\n', 88, 'PAD.BIN=' + pad, 'ZZ.COM=' + MTLN)
    sh = Shell(k)
    sh.run('ver')
    a0, used0, e0 = merged(mcbs(k)), sft_used(k), ems_used(k)
    k.pc.drives[0].bad = set(file_lbas(os.path.join(A.OUT, 'mt_ab.img'), b'ZZ      COM'))
    k.key('mtlaunch zz.com q.txt'); k.key(ktest.ENTER); k.run_for(3)
    scr, sync = k.pc.text_screen(), bytes(k.pc.rd(0xB800, 0, 0x4000)) == slot(k, 0)
    k.key('a'); k.run_for(2)
    k.pc.drives[0].bad = set()
    st = tstate(k) if not k.crashed else None
    line(k, '')
    v = sh.run('ver')
    # (an Abort while EXEC loads fails the EXEC: its own entry for the program it reads goes back too)
    d = [b - a for a, b in zip(used0, sft_used(k))]
    check('a read error while the stub EXECs its program, answered Abort: the prompt on the screen in front, shadowed in '
          'MTLAUNCH\'s pages too; the stub\'s EXEC fails and it ends its '
          'task; MTLAUNCH, then the prompt, go on; memory as before, the handles the stub inherited closed',
          'Abort' in scr and sync and not k.crashed and st and st[0] == [(0, 1, 'Executive')] and 'Lodestone version' in v
          and merged(mcbs(k)) == a0 and d == [0] * 24 and ems_used(k) == e0,
          (scr[-300:], st, v, d, ems_used(k), e0))
    k = boot('mt_tsr.img', b'MULTITASK=1\r\n', 88, os.path.join(HERE, 'TSR.COM'))
    sh = Shell(k)
    sh.run('ver')
    e0, m0 = ems_used(k), merged(mcbs(k))
    o = sh.run('mtlaunch tsr.com')
    line(k, '')
    a = mcbs(k)
    v = sh.run('ver')
    check('a program that stays resident in a task (TSR.COM, AH=31h): the task ends as if it had exited, its region '
          'freed (its hooks, in its own vectors, gone with them: M5a); the prompt goes on', not k.crashed
          and tstate(k)[0] == [(0, 1, 'Executive')] and merged(a) == m0 and 'Lodestone version' in v
          and ems_used(k) == e0, (show(a), v, ems_used(k), e0))
    o = sh.run('mtlaunch mtline.com t.txt')
    a1 = mcbs(k)
    front(k, 1); line(k, 'next')
    line(k, '')
    a = mcbs(k)
    check('... and the next task\'s region goes at the top again (T1, below MT), and ends', A.disk_file(k, 'T.TXT') == b'next'
          and [(b[4], b[2]) for b in a1[-2:]] == [(b'T1', 8), (b'MT', 8)]
          and tstate(k)[0] == [(0, 1, 'Executive')] and merged(a) == m0, (show(a1), show(a), A.disk_file(k, 'T.TXT')))

def t_fpu():
    print('== the coprocessor: each task\'s own')
    k = boot('mt_fp.img', b'MULTITASK=1\r\n', 88)
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    typ(k, 'mtlaunch mtspin.com 20 p0.txt p', 2.5); line(k, '')
    typ(k, 'mtlaunch mtspin.com 20 p1.txt p;mtspin.com 20 p2.txt p', 2.5); line(k, '')
    p0, p1, p2 = spun(k, 'P0.TXT'), spun(k, 'P1.TXT'), spun(k, 'P2.TXT')
    check('a coprocessor (INT 11h): kept per task.  Two MTSPINs each keeping its own values on it (n and 2n in ST0 and '
          'ST1, its own rounding in the control word), switched at the tick all along: neither saw them change, and each '
          'counted about half of one alone (%d and %d; %d)' % (p1, p2, p0), k.pc.rd(seg, Y['mt_fpu'], 1)[0] == 1
          and p0 > 0 and 0.3 * p0 < p1 < 0.7 * p0 and 0.3 * p0 < p2 < 0.7 * p0, (p0, p1, p2))
    typ(k, 'mtlaunch mtspin.com 40 p3.txt p', 0.5); typ(k, '', 0.3)
    typ(k, 'mtspin 20 p4.txt p', 1.5); k.run_for(3.0)
    p3, p4 = spun(k, 'P3.TXT'), spun(k, 'P4.TXT')
    check('... and task 0\'s (MTSPIN P from the prompt, another behind it): both kept (%d and %d)' % (p3, p4),
          p3 > 0 and 0.3 * p0 < p4 < 0.8 * p0, (p3, p4, p0))
    # a new task finds FNINIT's state, also when the one before it ended with its own, straight into it (no
    # switch between: the first writes its count to NUL, so it ends within its first turn)
    for i in range(3):
        typ(k, 'mtlaunch mtspin.com 0 nul p;mtspin.com 0 b%d.txt i' % i, 1.0); line(k, '')
    ib = [A.disk_file(k, 'B%d.TXT' % i) for i in range(3)]
    check('a new task finds the coprocessor as FNINIT leaves it (control word 037Fh), also run straight after one that '
          'set its own and ended (%s)' % b' '.join(x or b'-' for x in ib).decode(), ib == [b'00000001'] * 3, ib)
    # a coprocessor error (IRQ 13, raised by the test) pending at a switch: handled at mt_fdrain, before anything is
    # saved or chosen, by a handler that EOIs, STIs, calls INT 21h and waits for a tick, so it is preempted in there
    au = Audit(k)
    k.pc.pic2_mask &= ~0x20
    def inj():
        cur = k.pc.rd(seg, Y['mt_cur'], 1)[0]
        reg = k.pc.u16(seg, Y['mt_tab'] + cur * MT_ENT + TE_REG)
        return cur and reg <= vec(k, 0x75)[0] < reg + k.pc.u16(reg - 1, 3)      # (the E task's own error)
    au.inject = inj
    v75 = vec(k, 0x75)
    typ(k, 'mtlaunch mtspin.com 40 e1.txt e;mtspin.com 40 e2.txt p', 4.0); line(k, '')
    au.inject = None
    e1, e2 = spun(k, 'E1.TXT'), spun(k, 'E2.TXT')
    nt, nx = au.nested['tick'], au.nested['exit']
    check('a coprocessor error pending when a task is switched from (IRQ 13, %d times, never again inside its own '
          'handler): handled first, before anything is saved, by its handler, which was itself switched from (%d times at '
          'a tick in it, %d on its INT 21h\'s way out); both tasks counted (%d and %d, the second keeping its own '
          'coprocessor values), the machine intact, INT 75h given back' % (au.injected, nt, nx, e1, e2),
          au.injected >= 3 and nt > 0 and nx > 0 and e1 > 0 and e2 > 0 and not k.crashed
          and not au.bad() and vec(k, 0x75) == v75, (au.injected, dict(au.nested), e1, e2, au.bad()[:2], vec(k, 0x75), v75))
    au.stop()
    k = boot('mt_nf.img', b'MULTITASK=1\r\n', 88, nofpu=True)
    seg = mt_seg(k)
    Shell(k).run('ver')
    typ(k, 'mtlaunch mtspin.com 20 n1.txt;mtspin.com 20 n2.txt', 2.5); line(k, '')
    n1, n2 = spun(k, 'N1.TXT'), spun(k, 'N2.TXT')
    check('INT 11h says no coprocessor (and the 286\'s EM bit set, so any coprocessor instruction would trap): MT runs '
          'none (no INT 7), and tasks take turns as before (%d and %d)' % (n1, n2), seg
          and k.pc.rd(seg, Y['mt_fpu'], 1)[0] == 0 and k.pc.ints[7] == 0 and not k.crashed and n1 > 0 and n2 > 0
          and 0.5 < n1 / n2 < 2, (seg, k.pc.ints[7], n1, n2))

def task_ent(k, n): return k.Y['mt_tab'] + n * MT_ENT

def slot(k, n, size=0x4000):
    """Task n's screen as MT keeps it: its 2 EMS pages (KEMS's tables, as mt_smap reads them)."""
    pc, Y = k.pc, k.Y
    h = pc.rd(mt_seg(k), task_ent(k, n) + TE_SH, 1)[0]
    if not h: return None
    st = pc.rd(0x60, Y['ems_h'] + h * 4, 1)[0]
    return b''.join(pc.ems_read(pc.ems_page(pc.rd(0x60, Y['ems_ltab'] + st + i, 1)[0]), 0, 0x4000) for i in (0, 1))[:size]

def slot_text(k, n):
    v = slot(k, n, 4000) or bytes(4000)
    return '\n'.join(''.join(chr(v[(r * 80 + c) * 2]) if 32 <= v[(r * 80 + c) * 2] < 127 else ' '
                             for c in range(80)).rstrip() for r in range(25))

def tvid(k, n):
    """Task n's BIOS video data (40:49h-66h) in its TX."""
    return bytes(k.pc.rd(k.pc.u16(mt_seg(k), task_ent(k, n) + TE_TX), TX_VID, 30))

def vflags(k, n): return k.pc.rd(mt_seg(k), task_ent(k, n) + TE_VF, 1)[0]
def set_vflags(k, n, v): k.pc.wr(mt_seg(k), task_ent(k, n) + TE_VF, bytes([v]))
def shd(k): return k.pc.rd(mt_seg(k), k.Y['mt_shd'], 1)[0]

def waitfile(k, name, sim_s=20.0):
    """Run until the file is on the disk; the simulated microseconds it took (None: not in sim_s)."""
    u0 = k.pc.us
    while k.pc.us - u0 < sim_s * 1e6:
        k.run_for(0.05)
        if A.disk_file(k, name): return k.pc.us - u0
    return None

def t_fpbad():
    print('== a coprocessor that can\'t store (the 1520 with a 287XL): the start-up finds it and says there is none')
    # as it is: the store takes no time, the coprocessor kept (INT 11h's bit), nothing written to F0h/F1h
    k = boot('mt_fb0.img', b'MULTITASK=1\r\n', 88)
    check('a working coprocessor: the start-up\'s one FNSTENV returns at once; INT 11h still says there is one, nothing '
          'written to F0h/F1h, MT keeps each task\'s state (mt_fpu 1)', k.pc.rd(0x40, 0x10, 1)[0] & 2
          and k.pc.fpu_ports == [] and k.pc.rd(mt_seg(k), k.Y['mt_fpu'], 1)[0] == 1, (k.pc.fpu_ports,))
    # -dFPTEST: the store never ends by itself (a 287XL's in the 1520: BUSY held); the third tick ends it
    src = os.path.join(GOS, 'src')
    sysf, mapf, mtf = (os.path.join(A.OUT, n) for n in ('LODEFT.SYS', 'LODEFT.MAP', 'LODEMTFT.SYS'))
    m = os.path.join(A.OUT, '_ft.asm')
    open(m, 'w').write('[map symbols %s]\n%%include "LODE.ASM"\n' % mapf)
    subprocess.run(['nasm', '-f', 'bin', '-dFPTEST', '-i', src + '/', '-o', sysf, m], check=True)
    subprocess.run(['python3', os.path.join(GOS, 'mkmt.py'), sysf, mapf, mtf], check=True, stdout=subprocess.DEVNULL)
    import mkimg
    img = mkimg.build(os.path.join(A.OUT, 'mt_fb1.img'), ['LODE.SYS=' + sysf, 'LODEMT.SYS=' + mtf, A.LCMD, MTSP,
                                                          TERMRUN, TERMFNT, ini(b'MULTITASK=1\r\n')])
    k = ktest.KPC(img, ems_pages=88); k.start(10); k.mcb0 = k.u16('first_mcb')
    seg = mt_seg(k)
    eq, mf, ports = k.pc.rd(0x40, 0x10, 1)[0], k.pc.rd(seg, k.Y['mt_fpu'], 1)[0], list(k.pc.fpu_ports)
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    o = '\n'.join(l for y, l in k.ocr())
    check('a store that never ends: the third tick clears BUSY (F0h) and resets the coprocessor (F1h) (%s), the start-up '
          'goes on, INT 11h says there is none from then on (40:10h %02Xh), MT keeps no coprocessor state (mt_fpu %d), '
          'and CODE-P opens LCMD\'s window, its prompt drawn' % (ports, eq, mf), ports == [0xF0, 0xF1] and not eq & 2
          and mf == 0 and 'A:\\>' in o and not k.crashed, (ports, eq, mf, o[-300:]))

def t_screens():
    print('== screens: a background task\'s INT 10h in its own screen; one that writes the screen itself frozen there')
    k = boot('mt_sc.img', b'MULTITASK=1\r\n', 88, MTSC)
    seg, Y = mt_seg(k), k.Y
    au = Audit(k)
    sh = Shell(k)
    sh.run('ver')
    refs = {}
    for m, what in (('p', 'mode 3'), ('c', 'mode 1, 40 columns'), ('m', 'mode 83h, which the 1520 takes as 2')):
        # the reference: MTSCR alone, from the prompt (no other task: the BIOS's own output, nothing shadowed)
        typ(k, 'mtscr %s' % m, 3.0)
        ref, rbd, sh0 = bytes(k.pc.rd(0xB800, 0, 0x4000)), bytes(k.pc.rd(0x40, 0x49, 30)), shd(k)
        refs[m] = ref
        line(k, '')
        if m == 'p':
            rt, r1 = ('\n'.join(''.join(chr(ref[p + (r * 80 + c) * 2]) for c in range(80)) for r in range(25))
                      for p in (0, 0x1000))
            check('MTSCR P alone, from the prompt: the BIOS draws it (no other task, so nothing shadowed: mt_shd 0): page '
                  '0 its calls\' output, page 1 the 30 lines scrolled there in attribute 1Eh, and the AX 00h, 05h, 0Bh and '
                  '0Dh gave back (0029 0000 0B25 0355); 03h\'s CX for page 11 (the shape, page 8\'s cursor moved on: '
                  '0D0F), 0Ch\'s AX (0355), 08h past the 32 KB (FFFF), its page in window 2 untouched (S+); 09h '
                  'round to page 0 (16 "W")', sh0 == 0 and 'end' in rt and 'str1' in rt and 'BBBBB' in rt
                  and 'mvo' in rt and 's2' in rt and 'line A' in r1 and 'line Z' not in r1
                  and ref[0x1000 + (24 * 80) * 2 + 1] == 0x1E and '0029 0000 0B25 0355' in rt
                  and '0D0F 0355 FFFF S+' in rt and ref[:32] == b'W\x17' * 16, (sh0, rt, r1))
        # in the background, behind MTLAUNCH
        sh.run('cls')
        typ(k, 'mtlaunch mtscr.com %s' % m, 3.0)
        st, front_, s_bg = tstate(k), k.pc.text_screen(), shd(k)
        sl, tv = slot(k, 1), tvid(k, 1)
        diff = [i for i in range(0, 0x4000, 2) if sl[i:i + 2] != ref[i:i + 2]][:8]
        if m == 'p':
            check('MTSCR P in the background (MTLAUNCH in front): none of its output on the screen in front; in its own '
                  'screen (its 2 EMS pages) all of it, byte for byte as the BIOS drew it alone (16 KB: pages 0-3; mode 3, '
                  'the teletype and DOS, the cursor, 09h, 0Ah, 13h\'s four kinds, 06h, 07h, windows the wrong way round, '
                  'pages 1 and 8, what 03h, 08h, 0Fh answered and the AX 00h, 05h, 0Bh, 0Dh gave back, 30 lines '
                  'scrolled in the bottom line\'s attribute), its BIOS video data too (40:49h-66h: cursors, shape, page, '
                  'colour select)', st[0][1:] == [(1, 2, 'MTSCR.COM')] and 'MTLAUNCH waits>' in front_
                  and 'str1' not in front_ and 'line' not in front_ and sl == ref and tv == rbd,
                  (st, front_[-200:], diff, tv.hex(), rbd.hex()))
        else:
            check('MTSCR %s (%s) in the background: its own screen byte for byte as the BIOS drew it alone, its BIOS video '
                  'data too; the screen in front untouched' % (m.upper(), what), st[0][1:] == [(1, 2, 'MTSCR.COM')]
                  and 'line' not in front_ and sl == ref and tv == rbd, (st, front_[-200:], diff, tv.hex(), rbd.hex()))
        front(k, 1)
        ok = bytes(k.pc.rd(0xB800, 0, 0x4000)) == ref and bytes(k.pc.rd(0x40, 0x49, 30)) == rbd and tstate(k)[1] == 1
        if m == 'p':
            check('... brought to the front: that screen shown, and its BIOS data, and shadowed from there (mt_shd 1: '
                  'mt_scrld\'s, its mode set done in its own pages); MTLAUNCH\'s, shadowed from the moment '
                  'there was a task behind it (mt_shd 1: its pages given the screen then), found not to write the screen '
                  'itself', ok and s_bg == 1 and shd(k) == 1 and vflags(k, 0) & VF_DIRECT == 0,
                  (tstate(k), s_bg, shd(k), vflags(k, 0), k.pc.text_screen()[-200:]))
        else:
            check('... brought to the front: that screen shown, and its BIOS data', ok,
                  (tstate(k), k.pc.text_screen()[-200:]))
        line(k, ''); line(k, '')
        if m == 'p':
            check('... all ended, the prompt alone again: nothing shadowed (mt_shd 0)', shd(k) == 0 and len(tstate(k)[0]) == 1,
                  (shd(k), tstate(k)))
    # the page shown's start as the BIOS keeps it (40:4Eh), which KMT's scrolls and mt_vfast trust (O23, O25): MTSCR E,
    # the 1520's check, in the model
    typ(k, 'mtscr e e.txt', 3.0)
    e_, et = A.disk_file(k, 'E.TXT'), k.pc.text_screen()
    line(k, '')
    check('MTSCR E alone: 40:4Eh is 40:62h x 40:4Ch after every mode set (3, 1, 3, page 8 shown before each) and 05h '
          '(pages 1-8 and 0): 21 lines with "=", none with "!", 4E+', e_ == b'E+' and '4E+' in et
          and et.count(' =') == 21 and '!' not in et and '?' not in et,
          (e_, et[-400:]))
    # ... and where its calls never reach the BIOS (behind MTLAUNCH: they go into its pages, and it reads the front
    # task's 40:49h-4Eh, as in a terminal window): not a pass but 4E?
    typ(k, 'mtlaunch mtscr.com e e2.txt', 3.0)
    e2, est = A.disk_file(k, 'E2.TXT'), slot_text(k, 1)
    front(k, 1); line(k, ''); line(k, '')
    check('MTSCR E behind MTLAUNCH (its mode sets and 05h never reach the BIOS): lines marked "?" (40:49h, 62h not the '
          'mode and page asked for), 4E? and E?, not a false 4E+', e2 == b'E?' and '4E?' in est and ' ?' in est
          and '4E+' not in est, (e2, est[-500:]))
    ref = refs['p']
    # SPF_BG: its output on the real screen, shadowed as the front task's
    sh.run('cls')
    typ(k, 'mtlaunch /b mtscr.com p', 3.0)
    ft = k.pc.text_screen()
    front(k, 1)
    v0 = vflags(k, 0)
    line(k, ''); line(k, '')
    check('MTSCR P with SPF_BG (MTLAUNCH /B) in the background: its output on the screen in front, as it asked; done there '
          'in MTLAUNCH\'s pages too, so MTLAUNCH, switched from, isn\'t found to write the screen itself', 'str1' in ft
          and 'end' in ft and v0 & VF_DIRECT == 0, (ft[-300:], v0))
    # the detector: in front with another task there, shadowed; compared when switched from
    typ(k, 'mtlaunch mtline.com x.txt;/f mtscr.com p', 3.0)
    s_on, f1 = shd(k), tstate(k)[1]
    front(k, 0)
    c_p = vflags(k, 2)
    check('MTSCR P in front, another task there: its INT 10h calls shadowed in its pages (mt_shd 1); switched from, its '
          'screen matches them, so it is known not to write the screen itself (VF_DIRECT clear: it may run behind)',
          f1 == 2 and s_on == 1 and c_p & VF_DIRECT == 0 and slot(k, 2) == ref, (f1, s_on, c_p, tstate(k)))
    front(k, 2); line(k, '')
    front(k, 1); line(k, 'x'); line(k, '')
    # a page across the 32 KB's end (MTSCR B: page 7 from 7A80h), shadowed in front: whole-page scrolls that mt_vscr's
    # bound test sends the BIOS's way (O23: AL, BX, CX, DX kept to that test, no frame), one inside at once, the
    # teletype; its pages read before the switch (which copies the screen into them)
    typ(k, 'mtlaunch mtline.com x.txt;/f mtscr.com b b.txt', 3.0)
    f1, b_ = tstate(k)[1], A.disk_file(k, 'B.TXT')
    real, sl = bytes(k.pc.rd(0xB800, 0, 0x8000)), slot(k, 2, 0x8000) or bytes(0x8000)
    front(k, 0)
    c_b = vflags(k, 2)
    front(k, 2); line(k, '')
    front(k, 1); line(k, 'x'); line(k, '')
    w = real[0x7A80:]
    wt = ''.join(chr(c) for c in w[::2])
    diff = [hex(i) for i in range(0, 0x8000, 2) if sl[i:i + 2] != real[i:i + 2]][:8]
    check('MTSCR B in front, another task there, page 7 shown from 7A80h (40:4Ch 1180h): its pages as the BIOS drew the '
          'screen, page 0 and 7A80h-7FFFh byte for byte (the page scrolled up and down, a window partly past the 32 KB '
          'blanked, rows 3-5 moved at once, the teletype and its scroll); nothing written past the 32 KB (its own EMS '
          'page in window 2 signed still: B+); switched from, VF_DIRECT clear',
          f1 == 2 and b_ == b'B+' and sl[0x7A80:] == w and sl[:0x4000] == real[:0x4000] and c_b & VF_DIRECT == 0
          and 'bbbbbfastbb' in wt and 'd' * 80 in wt and {0x2E, 0x4E, 0x5B} <= set(w[1::2]), (f1, b_, c_b, diff, wt))
    # a program that sets 40:62h and 40:4Ch itself (no 05h, 40:4Eh left 0: MTSCR J), switched from, then writing
    # behind: mt_scrsv puts its saved 4Eh at 62h x 4Ch, where the BIOS writes, so its pages are as the BIOS drew it
    typ(k, 'mtscr j j0.txt', 4.0)
    j0, refj = A.disk_file(k, 'J0.TXT'), bytes(k.pc.rd(0xB800, 0, 0x4000))
    line(k, '')
    typ(k, 'mtlaunch mtline.com x.txt;/f mtscr.com j j.txt', 0.8)
    f1, jn = tstate(k)[1], A.disk_file(k, 'J.TXT')
    front(k, 0)
    j_ = waitfile(k, 'J.TXT', 5.0)
    slj, tvj, c_j = slot(k, 2) or bytes(0x4000), tvid(k, 2), vflags(k, 2)
    front(k, 2); line(k, '')
    front(k, 1); line(k, 'x'); line(k, '')
    r1 = ''.join(chr(refj[0xF00 + i * 2]) for i in range(2000))
    diff = [hex(i) for i in range(0, 0x4000, 2) if slj[i:i + 2] != refj[i:i + 2]][:8]
    check('MTSCR J (40:62h 1, 40:4Ch 0F00h set itself, no 05h) switched from in its wait, then 30 lines behind: its '
          'saved 40:4Eh made 62h x 4Ch at the switch (0F00h), so its characters and scrolls land on page 1 as the BIOS '
          'drew them alone (16 KB byte for byte)', j0 == b'J' and f1 == 2 and jn is None and j_ is not None
          and c_j & VF_DIRECT == 0 and slj == refj and 'line A' in r1 and tvj[0x4E - 0x49:0x50 - 0x49] == b'\x00\x0f',
          (j0, f1, jn, j_, c_j, diff, tvj.hex()))
    for mode, why in (('d', 'a word written into B800h itself'), ('g', 'in a graphics mode (6)')):
        typ(k, 'mtlaunch mtline.com x.txt;/f mtscr.com %s %s.txt' % (mode, mode), 3.0)
        f1 = tstate(k)[1]
        front(k, 0)
        c = vflags(k, 2)
        check('MTSCR %s in front, another task there: switched from, it is found to write the screen itself (%s): '
              'VF_DIRECT' % (mode.upper(), why), f1 == 2 and c & VF_DIRECT, (f1, c, tstate(k)))
        front(k, 2); line(k, '')
        front(k, 1); line(k, 'x'); line(k, '')
    # the 1520's own teletype calls INT 10h again for each step: those calls are the BIOS's (from above A000h), not shadowed again
    v = open(VNEST, 'rb').read()
    k.pc.wr(0xD000, 0, v)
    k.pc.wr(0xD000, len(v) - 4, struct.pack('<HH', INT10[1], INT10[0]))
    k.pc.wr(seg, Y['mt_old10'], struct.pack('<HH', 0, 0xD000))
    n10 = k.pc.ints[0x10]
    typ(k, 'mtlaunch mtline.com x.txt;/f mtscr.com p', 3.0)
    s_v = shd(k)
    front(k, 0)
    c_n = vflags(k, 2)
    nested = k.pc.ints[0x10] - n10
    check('with a teletype as the 1520\'s (VNEST at D000h, calling INT 10h again for its cursor, character, scroll: %d BIOS '
          'calls): MTSCR P in front is still shadowed (mt_shd 1) and found not to write the screen itself, its pages as '
          'the screen' % nested,
          s_v == 1 and c_n & VF_DIRECT == 0 and slot(k, 2) == ref and nested > 1000, (s_v, c_n, nested, tstate(k)))
    front(k, 2); line(k, '')
    front(k, 1); line(k, 'x'); line(k, '')
    k.pc.wr(seg, Y['mt_old10'], struct.pack('<HH', INT10[1], INT10[0]))
    # brought to the front with no mode set (as most programs are): shadowed from there all the same (mt_scrld), so one
    # that writes the screen itself is found
    typ(k, 'mtlaunch mtline.com x.txt;mtscr.com w w.txt', 2.0)
    front(k, 2)
    s_w = shd(k)
    k.key('a'); w_ = waitfile(k, 'W.TXT', 3.0)
    front(k, 0)
    c_w = vflags(k, 2)
    front(k, 2); line(k, '')
    front(k, 1); line(k, 'x'); line(k, '')
    check('MTSCR W, behind, brought to the front with no mode set: shadowed from there (mt_shd 1, mt_scrld\'s); a key, '
          'and it writes B800h itself: switched from, it is found to (VF_DIRECT)', s_w == 1 and w_ and c_w & VF_DIRECT,
          (s_w, w_, c_w))
    # MT_SCREEN from a task behind: not the front one's, so nothing
    typ(k, 'mtlaunch mtline.com x.txt;/f mtscr.com d;mtscr.com k k.txt', 3.0)
    k_ = A.disk_file(k, 'K.TXT')
    front(k, 0)
    c_k = vflags(k, 2)
    front(k, 2); line(k, '')
    front(k, 1); line(k, 'x'); line(k, '')
    check('MT_SCREEN from a task behind (MTSCR K) while MTSCR D is in front: not the front one\'s, so nothing done; D, '
          'switched from, is still found to write the screen itself', k_ == b'K' and c_k & VF_DIRECT, (k_, c_k, tstate(k)))
    # frozen in the background: never run there
    typ(k, 'mtlaunch mtspin.com 20 z1.txt', 0.05)
    for i in range(100):
        if len(tstate(k)[0]) == 2: break
        k.run_for(0.01)
    set_vflags(k, 1, VF_DIRECT)
    k.run_for(2.0)
    z1, st1 = A.disk_file(k, 'Z1.TXT'), tstate(k)
    set_vflags(k, 1, VF_DIRECT | SPF_BG)
    k.run_for(2.0)
    z1b, s_z = A.disk_file(k, 'Z1.TXT'), shd(k)
    line(k, '')
    check('a task marked VF_DIRECT is frozen in the background: never run there (MTSPIN 20 ticks: no count in 2 s, still '
          'TS_RUN); with SPF_BG too it runs (its count written); it ends behind MTLAUNCH, the last task: nothing shadowed '
          'from then (mt_shd 0)', z1 is None and st1[0][1:] == [(1, 1, 'MTSPIN.COM')] and z1b and s_z == 0,
          (z1, st1, z1b, s_z))
    # frozen while it runs, nothing else ready (the one in front waits for a key, TS_WAITK): it gives way to that one
    typ(k, 'mtlaunch mtline.com z4.txt;mtspin.com 40 z3.txt', 0.05)
    for i in range(100):
        if len(tstate(k)[0]) == 3: break
        k.run_for(0.01)
    front(k, 1)
    st3 = tstate(k)
    set_vflags(k, 2, VF_DIRECT)
    k.run_for(3.0)
    z3, st3b = A.disk_file(k, 'Z3.TXT'), tstate(k)
    set_vflags(k, 2, 0)
    z3b = waitfile(k, 'Z3.TXT', 3.0)
    line(k, 'x'); line(k, '')
    check('a task frozen while it runs, the others waiting for a key (MTLINE in front, MTLAUNCH behind it): it gives way at '
          'once, never runs again there (MTSPIN 40 ticks: no count in 3 s); thawed, it runs',
          st3[0][1:] == [(1, 2, 'MTLINE.COM'), (2, 1, 'MTSPIN.COM')] and st3[1:] == (1, 2) and z3 is None
          and st3b[0][2] == (2, 1, 'MTSPIN.COM') and z3b, (st3, z3, st3b, z3b))
    typ(k, 'mtlaunch /z mtspin.com 8 z2.txt', 2.0)
    z2, f2, lz = A.disk_file(k, 'Z2.TXT'), vflags(k, 1), k.pc.text_screen()
    front(k, 1)
    z2b = waitfile(k, 'Z2.TXT', 3.0)
    line(k, '')
    check('SPF_FREEZE (MTLAUNCH /Z): never run in the background (no count in 2 s), MT_LIST shows it frozen (TS_FROZEN, '
          '4), it runs once in front', z2 is None and f2 == SPF_FREEZE and '1 4 MTSPIN.COM;' in lz and z2b,
          (z2, f2, z2b, lz[-200:]))
    # graphics asked for in the background: it waits to be in front
    n = len(au.ev)
    typ(k, 'mtlaunch mtscr.com g g2.txt', 2.0)
    st, m0, g0, ft, gt = tstate(k), k.pc.mode(), A.disk_file(k, 'G2.TXT'), k.pc.text_screen(), slot_text(k, 1)
    sw = au.switches(n, 'v10')
    front(k, 1); k.run_for(0.5)
    m1, g1 = k.pc.mode(), A.disk_file(k, 'G2.TXT')
    line(k, ''); line(k, '')
    check('MTSCR G in the background asks for mode 6: it waits to be in front (TS_WAITF), switched from there at a safe '
          'point (%d times), its line in its own screen, the screen in front untouched (mode 3); brought to the front, mode 6 '
          'and on' % len(sw), st[0][1:] == [(1, TS_WAITF, 'MTSCR.COM')] and m0 == 3 and g0 is None
          and 'asks for graphics' in gt and 'graphics' not in ft and sw and m1 == 6 and g1 == b'G'
          and not au.bad(), (st, hex(m0), g0, len(sw), hex(m1), g1, au.bad()[:2]))
    typ(k, 'mtlaunch mtscr.com q q.txt', 2.0)
    q, vq, m0, fq = A.disk_file(k, 'Q.TXT'), vflags(k, 1), k.pc.mode(), k.pc.text_screen()
    front(k, 1)
    q1 = waitfile(k, 'Q.TXT', 2.0) and A.disk_file(k, 'Q.TXT')
    line(k, ''); line(k, '')
    check('... with interrupts off it can\'t wait (not a safe point): the mode set is dropped, and since it may go on to '
          'write the screen itself, it is frozen behind from its next safe point (VF_DIRECT); brought to the front it goes on in '
          'mode 3 (Q.TXT "Q03"), the screen in front untouched meanwhile', vq & VF_DIRECT and m0 == 3
          and 'graphics' not in fq and q1 == b'Q03' and len(tstate(k)[0]) == 1, (q, vq, hex(m0), q1, tstate(k), fq[-200:]))
    # a hardware interrupt's INT 10h: the real screen's, shadowed as the front task's
    typ(k, 'mtlaunch mtscr.com i i.txt', 2.0)
    i_, scr, isl, s_i = A.disk_file(k, 'I.TXT'), bytes(k.pc.rd(0xB800, 0, 160)), slot(k, 1, 160), shd(k)
    front(k, 1)
    v0 = vflags(k, 0)
    line(k, ''); line(k, '')
    check('MTSCR I in the background, its INT 1Ch handler drawing \'*\' through INT 10h (IRQ 0 in service): on the '
          'real screen, not in its own; done in MTLAUNCH\'s pages too (mt_shd still 1), so MTLAUNCH, switched from, '
          'isn\'t found to write the screen itself', i_ == b'I' and scr[158:160] == b'*\x70' and isl[158:160] != b'*\x70'
          and s_i == 1 and v0 & VF_DIRECT == 0 and len(tstate(k)[0]) == 1, (i_, scr[150:160], isl[150:160], s_i, v0,
                                                                           tstate(k)))
    # INT 13h through MT, which counts the calls running (inside one, an INT 10h call is taken as an interrupt's: below,
    # VHOOK T's and MTNEST I's, with the count set by the test, since pcemu's BIOS does its transfers at once)
    v13, n13 = vec(k, 0x13), k.pc.rd(seg, Y['mt_in13'], 1)[0]
    check('INT 13h through MT (mt_i13), its count back at 0 after all the reading so far', v13 == (seg, Y['mt_i13'])
          and n13 == 0, (v13, n13))
    # a ROM's own INT 10h (CS at A000h or above, not inside a call MT passed on to the BIOS): as it is, on the real
    # screen, not shadowed, so the front task's shadow is lost
    k.pc.wr(0xD800, 0, bytes([0xCD, 0x10, 0xCB]))
    typ(k, 'mtlaunch mtscr.com r r.txt', 2.0)
    r_, scr, rsl, s_r = A.disk_file(k, 'R.TXT'), bytes(k.pc.rd(0xB800, 0, 160)), slot(k, 1, 160), shd(k)
    front(k, 1)
    v_r = vflags(k, 0)
    line(k, ''); line(k, '')
    check('a ROM\'s INT 10h (MTSCR R behind MTLAUNCH, calling code at D800h that does INT 10h 13h): on the real screen as it '
          'is, not in its own; not shadowed, so MTLAUNCH\'s shadow is lost (mt_shd 0): switched from, not frozen',
          r_ == b'R' and scr[120:122] == b'R\x70' and rsl[120:122] != b'R\x70' and s_r == 0 and v_r & VF_DIRECT == 0,
          (r_, scr[118:124], rsl[118:124], s_r, v_r))
    # LCMD's screen saver doesn't start behind another task
    ui = k.pc.u16(0x60, Y['ui_seg'])
    k.pc.wr(ui, Y['saver_t'], bytes([36, 0]))           # (2 s: LCMD reads it when it starts)
    typ(k, 'mtlaunch lcmd.com', 1.0)
    s0, m0 = bytes(k.pc.rd(0xB800, 0, 0x4000)), k.pc.mode()
    k.run_for(4.0)
    s1, m1 = bytes(k.pc.rd(0xB800, 0, 0x4000)), k.pc.mode()
    front(k, 1)
    typ(k, 'exit', 1.0); line(k, '')
    check('LCMD as a task behind MTLAUNCH, past its saver\'s time (2 s): its saver doesn\'t start (MT_LIST: it isn\'t in '
          'front), the screen in front untouched', m0 == m1 == 3 and s1 == s0 and not k.crashed and len(tstate(k)[0]) == 1,
          (hex(m0), hex(m1), s0 == s1, tstate(k)))
    check('every switch in these was at a safe point (as in t_preempt), the ones from INT 10h too', not au.bad(), au.bad()[:3])
    au.stop()
    # LCMD's saver in front, a task behind: the screen it puts back itself, declared (MT_SCREEN)
    k = boot('mt_sc3.img', b'MULTITASK=1\r\n', 88, MTSC)
    ui = k.pc.u16(0x60, k.Y['ui_seg'])
    k.pc.wr(ui, k.Y['saver_t'], bytes([36, 0]))
    sh = Shell(k)
    sh.run('ver')
    typ(k, 'mtlaunch mtline.com x.txt', 1.0); line(k, '')
    k.run_for(4.0)
    m_sv = k.pc.mode()
    k.key(' '); k.run_for(1.0)
    m_bk = k.pc.mode()
    k.pc.wr(mt_seg(k), k.Y['mt_swreq'], b'\1')
    k.key('y'); k.run_for(0.5)
    st, v0 = tstate(k), vflags(k, 0)
    line(k, '')
    check('LCMD at its prompt with a task behind: its saver runs (mode 40h) and a key ends it; LCMD puts its screen back '
          'itself and says so (MT_SCREEN), so switched from, it isn\'t found to write the screen itself',
          m_sv == 0x40 and m_bk == 3 and st[1] == 1 and v0 & VF_DIRECT == 0, (hex(m_sv), hex(m_bk), st, v0))
    # an INT 24h handler of a background task prompting through DOS: on the real screen
    pad = os.path.join(A.OUT, 'ZZD.BIN'); open(pad, 'wb').write(bytes(range(256)) * 40)
    k = boot('mt_sc4.img', b'MULTITASK=1\r\n', 88, 'ZZ.DAT=' + pad, MTCR)
    sh = Shell(k)
    sh.run('ver')
    k.pc.drives[0].bad = set(file_lbas(os.path.join(A.OUT, 'mt_sc4.img'), b'ZZ      DAT'))
    typ(k, 'mtlaunch mtcrit.com c.txt', 4.0)
    ft, cs, sync = k.pc.text_screen(), slot_text(k, 1), bytes(k.pc.rd(0xB800, 0, 0x4000)) == slot(k, 0)
    k.key('q'); k.run_for(2.0)
    k.pc.drives[0].bad = set()
    c = A.disk_file(k, 'C.TXT')
    line(k, '')
    check('a background task\'s own INT 24h handler prompting through DOS (AH=09h, inside the nested INT 21h): its '
          'prompt on the real screen, since everything waits for its answer, not in its own, and shadowed in the front '
          'task\'s pages; the key typed answers it (C.TXT "Cq")', 'CRITPROMPT' in ft and 'CRITPROMPT' not in cs and sync
          and c == b'Cq', (ft[-300:], cs[-200:], sync, c))
    sh.run('cls')
    k.pc.drives[0].bad = set(file_lbas(os.path.join(A.OUT, 'mt_sc4.img'), b'ZZ      DAT'))
    typ(k, 'mtlaunch mtcrit.com c2.txt b', 4.0)
    ft, cs, sync = k.pc.text_screen(), slot_text(k, 1), bytes(k.pc.rd(0xB800, 0, 0x4000)) == slot(k, 0)
    k.key('q'); k.run_for(2.0)
    k.pc.drives[0].bad = set()
    c = A.disk_file(k, 'C2.TXT')
    line(k, '')
    check('... and through the BIOS\'s teletype (MTCRIT B: its own code, inside INT 21h, not the kernel\'s): the same',
          'CRITPROMPT' in ft and 'CRITPROMPT' not in cs and sync and c == b'Cq', (ft[-300:], cs[-200:], sync, c))
    # mt_v10 entered with interrupts on (a TSR's hook chaining with PUSHF / CALL FAR), a tick's INT 10h meanwhile
    k = boot('mt_sc5.img', b'MULTITASK=1\r\n', 88, MTNS)
    sh = Shell(k)
    sh.run('ver')
    typ(k, 'mtlaunch mtline.com x.txt', 1.0); line(k, '')
    s_n = shd(k)
    k.key('mtnest r.txt'); k.key(ktest.ENTER, settle=False)
    waitfile(k, 'R.TXT', 60)
    r = A.disk_file(k, 'R.TXT') or b''
    line(k, '')
    check('MTNEST in front, a task behind (shadowed): 3000 scrolls through INT 10h called with interrupts on (PUSHF / '
          'CALL FAR), its INT 1Ch handler calling INT 10h meanwhile: its own EMS page in window 0 intact after every one '
          '(%s)' % r.decode(errors='replace'), s_n == 1 and r.startswith(b'OK ') and int(r[3:] or b'0', 16) >= 3
          and not k.crashed,
          (s_n, r))
    front(k, 1); line(k, 'x')
    # brought to the front by MTLAUNCH /F, so shadowed from the start (mt_scrld): N as it is (a control: the shadow kept),
    # S with its stack in its own page in window 0, E printing a 13h string from there: those calls not shadowed, so lost
    for o, what, s_e in (('n', 'as above', 1), ('s', 'its stack in its own EMS page in window 0, where the pages would go', 0),
                    ('e', 'a 13h string from its own EMS page in window 0', 0),
                    ('i', 'running in front alone, inside an INT 13h call from the moment it runs (mt_in13, set by the '
                     'test): every call an interrupt\'s', 0)):
        typ(k, 'mtlaunch mtline.com x.txt;/f mtnest.com r%s.txt %s' % (o, o), 1.0)
        if o == 'i': k.pc.wr(mt_seg(k), k.Y['mt_in13'], b'\1')
        waitfile(k, 'R%s.TXT' % o.upper(), 60)
        k.pc.wr(mt_seg(k), k.Y['mt_in13'], b'\0')
        r, s_o, st = A.disk_file(k, 'R%s.TXT' % o.upper()) or b'', shd(k), tstate(k)
        front(k, 0)
        v_o = vflags(k, 2)
        front(k, 2); line(k, '')
        front(k, 1); line(k, 'x'); line(k, '')
        check('MTNEST %s brought to the front by MTLAUNCH /F, a task behind (%s): %s; its page intact (%s); switched from, '
              '%s' % (o.upper(), what, 'shadowed throughout (mt_shd 1)' if s_e else 'those calls go to the BIOS as they '
              'are, not shadowed, so the shadow is lost (mt_shd 0)', r.decode(errors='replace'),
              'found not to write the screen itself' if s_e else 'not known to write the screen itself, so not frozen'),
              st[1] == 2 and r.startswith(b'OK ') and s_o == s_e and v_o & VF_DIRECT == 0 and not k.crashed,
              (st, r, s_o, v_o))
    # audit3 X36: MTNEST E behind (its 13h string from its own page in window 0, where its screen's pages are mapped
    # for the call): not done, and nothing reached the real screen, so the front one's shadow is kept
    typ(k, 'mtlaunch mtline.com x.txt;mtnest.com rb.txt e', 1.0)
    s_b0 = shd(k)
    waitfile(k, 'RB.TXT', 60)
    r, s_b, lo, st = (A.disk_file(k, 'RB.TXT') or b'', shd(k), k.pc.rd(mt_seg(k), k.Y['mt_vlost'], 1)[0], tstate(k))
    front(k, 1); line(k, 'x'); line(k, '')
    check('MTNEST E behind (a 13h string from its own EMS page in window 0, in its own turns: not done there): the front '
          'one\'s shadow kept (mt_shd %d, then %d; mt_vlost %d); its page intact (%s)' % (s_b0, s_b, lo,
          r.decode(errors='replace')), s_b0 == s_b == 1 and lo == 0 and r.startswith(b'OK ') and st[1] == 0
          and not k.crashed, (s_b0, s_b, lo, r, st))
    # a driver's INT 10h hook loaded after MT (VHOOK: below A000h, chaining with PUSHF / CALL FAR): the BIOS's nested calls
    # come through it, still known as the BIOS's (MT's own calls marked, mt_inb)
    k = boot('mt_sc6.img', b'MULTITASK=1\r\n', 88, MTSC, VHK)
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    sh.run('vhook')
    v = open(VNEST, 'rb').read()
    k.pc.wr(0xD000, 0, v)
    k.pc.wr(0xD000, len(v) - 4, struct.pack('<HH', INT10[1], INT10[0]))
    k.pc.wr(seg, Y['mt_old10'], struct.pack('<HH', 0, 0xD000))
    n10 = k.pc.ints[0x10]
    typ(k, 'mtlaunch mtline.com x.txt;/f mtscr.com p', 3.0)
    s_h = shd(k)
    front(k, 0)
    c_h, sl_h, nested = vflags(k, 2), slot(k, 2), k.pc.ints[0x10] - n10
    front(k, 2); line(k, '')
    front(k, 1); line(k, 'x'); line(k, '')
    k.pc.wr(seg, Y['mt_old10'], struct.pack('<HH', INT10[1], INT10[0]))
    check('a driver\'s INT 10h hook loaded after MT (VHOOK, below A000h, PUSHF / CALL FAR), with a teletype as the '
          '1520\'s (VNEST: %d BIOS calls, its own through the hook): MTSCR P in front is shadowed (mt_shd 1), its screen '
          'as the BIOS drew it alone, and it is found not to write the screen itself' % nested,
          s_h == 1 and c_h & VF_DIRECT == 0 and sl_h == ref and nested > 1000, (s_h, c_h, nested, tstate(k)))
    # a TSR's clock (VHOOK T: INT 08h chained first, then INT 10h, a new digit each tick: no interrupt in service) inside
    # an INT 13h call (mt_in13), while MTSPIN runs behind MTLAUNCH: no window mapped for it, so on the real screen,
    # nothing more in MTSPIN's own
    sh.run('vhook t')
    typ(k, 'mtlaunch mtspin.com 100 z.txt', 1.0)
    seg, Y = mt_seg(k), k.Y
    k.pc.wr(seg, Y['mt_in13'], b'\1')
    t_f0, t_s0 = bytes(k.pc.rd(0xB800, 140, 2)), (slot(k, 1, 160) or bytes(160))[140:142]
    k.run_for(1.5)
    t_f, t_s, st = bytes(k.pc.rd(0xB800, 140, 2)), (slot(k, 1, 160) or bytes(160))[140:142], tstate(k)
    k.pc.wr(seg, Y['mt_in13'], b'\0')
    z = waitfile(k, 'Z.TXT', 6.0)
    line(k, '')
    check('a TSR\'s clock (VHOOK T: INT 08h, chained first, then INT 10h 13h, a new digit each tick; no interrupt in '
          'service) inside an INT 13h call, while MTSPIN runs behind MTLAUNCH: its digits go on on the real screen, none '
          'more in MTSPIN\'s own (it runs throughout: no switch inside an INT 13h call)', t_f != t_f0
          and t_f[1:] == b'\x70' and t_s == t_s0 and st[0][1:] == [(1, 1, 'MTSPIN.COM')] and st[2] == 1 and z,
          (t_f0, t_f, t_s0, t_s, st, z))
    # the shadow's cost: 120 lines through DOS in front, alone and with a task behind it (shadowed)
    k = boot('mt_sc2.img', b'MULTITASK=1\r\n', 88, MTSC)
    sh = Shell(k)
    sh.run('ver')
    for n in ('lw', 'l0'):              # (the first only to have MTSCR.COM in the disk cache for the timed ones)
        k.key('mtscr l %s.txt' % n); k.key(ktest.ENTER, settle=False)
        u0 = waitfile(k, n.upper() + '.TXT')
        line(k, '')
    typ(k, 'mtlaunch mtline.com x.txt', 1.0)
    line(k, '')
    k.key('mtscr l l1.txt'); k.key(ktest.ENTER, settle=False)
    s_, u1 = None, waitfile(k, 'L1.TXT')
    s_ = shd(k)
    line(k, '')
    print('   120 lines of 54 characters through DOS: %.0f ms alone, %.0f ms shadowed (another task there), in pcemu\'s '
          'time: %.1f us more a character' % (u0 / 1000, u1 / 1000, (u1 - u0) / (120 * 54)))
    check('the front task\'s output shadowed only while another task is there: 120 lines through DOS cost %.1f us more a '
          'character (in pcemu\'s time)' % ((u1 - u0) / (120 * 54)), u0 and u1 and s_ == 1 and u1 > u0, (u0, u1, s_))

def t_kslice():
    print('== audit3 S1: a task\'s slice of the kernel stack (switched from inside INT 21h) saved and put back in words')
    from unicorn import UC_HOOK_CODE
    k = boot('mt_ks.img', b'MULTITASK=1\r\n', 88)
    seg, Y, pc = mt_seg(k), k.Y, k.pc
    Shell(k).run('ver')
    top, KL, TKS, KS = Y['kstack_top'], equ('TX_KLEN'), equ('TX_KSTK'), equ('KSLICE')
    saved, lens, above, got = {}, collections.Counter(), {}, []
    def sv(uc, a, n, u):                # mt_switch.k: the running task's CX bytes at SS:SP, as it saves them
        cx = pc.r('cx')
        if cx:
            saved[pc.rd(seg, Y['mt_cur'], 1)[0]] = (pc.r('ss'), pc.r('sp'), bytes(pc.rd(pc.r('ss'), pc.r('sp'), cx)))
            lens[cx] += 1
    def ld(uc, a, n, u):                # mt_load: the TX of task BL marked past its slice; past kstack_top as it starts
        tx = pc.u16(seg, task_ent(k, pc.r('bl')) + TE_TX)
        n_ = pc.u16(tx, KL)
        pc.wr(tx, TKS + n_, bytes([0xA5]) * (KS - n_))
        above['b'] = bytes(pc.rd(0x60, top, 128))
    def go(uc, a, n, u):                # mt_load.go: the slice back, nothing past it written
        cur = pc.rd(seg, Y['mt_cur'], 1)[0]
        n_ = pc.u16(pc.u16(seg, task_ent(k, cur) + TE_TX), KL)
        if n_ and cur in saved:
            got.append((saved.pop(cur) == (pc.r('ss'), pc.r('sp'), bytes(pc.rd(pc.r('ss'), pc.r('sp'), n_))),
                        bytes(pc.rd(0x60, top, 128)) == above.get('b'), n_))
    hks = [pc.mu.hook_add(UC_HOOK_CODE, f, None, seg * 16 + Y[l], seg * 16 + Y[l])
           for f, l in ((sv, 'mt_switch.k'), (ld, 'mt_load'), (go, 'mt_load.go'))]
    for l in ('mt_switch.k', 'mt_load', 'mt_load.go'): pc.mu.ctl_remove_cache(seg * 16 + Y[l], seg * 16 + Y[l] + 1)
    typ(k, 'mtlaunch mtspin.com 60 ks1.txt d;/f mtline.com ks.txt', 0.5)
    for c in 'switched in DOS':         # (MTLINE in front, MTSPIN behind: MTLINE's line read waits for each key in
        k.key(c, settle=False); k.run_for(0.06)     #  kbd_get, giving MTSPIN its turn)
    k.key(ktest.ENTER, settle=False); k.run_for(0.3)
    for h in hks: pc.mu.hook_del(h)
    print('   slices (bytes: switches): %s' % sorted(lens.items()))
    check('a task switched from inside INT 21h (MTLINE, in front, waiting for each key of its line, MTSPIN D behind '
          'it): its slice of the kernel stack back byte for byte where it was (ending at kstack_top), nothing past '
          'kstack_top written (%d times, %d to %d bytes); its line read whole' % (len(got), min(lens) if lens else 0,
                                                                                 max(lens) if lens else 0),
          len(got) >= 12 and all(a and b for a, b, n in got) and A.disk_file(k, 'KS.TXT') == b'switched in DOS',
          ([g for g in got if not (g[0] and g[1])][:4], len(got), A.disk_file(k, 'KS.TXT')))

class IfOff:
    """The longest stretch with interrupts off in each INT 10h call through mt_v10 (keyed by its AH, BH and CX
    there), and the longest the timer's IRQ waited meanwhile (pcemu's us; irq_exact, so it lands as IF comes back)."""
    def __init__(s, k):
        s.k, s.v10 = k, mt_seg(k) * 16 + k.Y['mt_v10']
        s.t0 = s.key = s.tp = None
        s.off, s.lat = {}, {}
        s.prev, k.pc.watch = k.pc.watch, s.watch
    def stop(s): s.k.pc.watch = s.prev
    def watch(s, a):
        if s.prev: s.prev(a)
        pc = s.k.pc
        if a == s.v10: s.key = (pc.r('ah'), pc.r('bh'), pc.r('cx'))
        if pc.r('flags') & 0x200:
            if s.t0 is not None and s.key: s.off[s.key] = max(s.off.get(s.key, 0), pc.us - s.t0)
            s.t0 = s.key = None
        elif s.t0 is None: s.t0 = pc.us
        if 0 in pc.irq_pending:
            if s.tp is None: s.tp = (pc.us, s.key)
        elif s.tp is not None:
            t, key = s.tp
            if key: s.lat[key] = max(s.lat.get(key, 0), pc.us - t)
            s.tp = None

def t_vruns():
    print('== audit3 S2, S3: long runs in a background task\'s screen (09h at once inside the 32 KB; rows of a run-on '
          'scroll wholly past it skipped), as the BIOS does them, and the time they keep interrupts off')
    k = boot('mt_vr.img', b'MULTITASK=1\r\n', 88, MTSC, irq_exact=True)
    sh = Shell(k)
    sh.run('ver')
    off = {}
    for m, what in (('v', '09h of 8001h cells round 16 bits, then 09h of 1000h on page 4 and 2000 on page 0, 09h and 0Ah '
                     'round 16 bits, 09h across the 32 KB\'s end, 0Ah of 500'),
                    ('u', '09h of 8001h cells, then "clear below the cursor" on the last line run on from page 0 (a row '
                     'across the 32 KB\'s end, then past it) and from page 7 (round 16 bits)')):
        M = m.upper()
        typ(k, 'mtscr %s %s0.txt' % (m, m), 3.0)    # the reference: alone, from the prompt (the BIOS's own)
        ref, rbd, r0 = bytes(k.pc.rd(0xB800, 0, 0x8000)), bytes(k.pc.rd(0x40, 0x49, 30)), A.disk_file(k, M + '0.TXT')
        line(k, '')
        sh.run('cls')
        io = IfOff(k)
        typ(k, 'mtlaunch mtscr.com %s %s1.txt' % (m, m), 0.5)
        w = waitfile(k, M + '1.TXT', 30)
        io.stop()
        off.update(io.off)
        print('   %s: interrupts off (pcemu\'s us, the longest 6): %s' % (M, sorted(((v, '%02X %02X %04X' % kk)
                                                                                 for kk, v in io.off.items()), reverse=True)[:6]))
        st, front_, sl, tv, r1 = tstate(k), k.pc.text_screen(), slot(k, 1, 0x8000), tvid(k, 1), A.disk_file(k, M + '1.TXT')
        diff = [hex(i) for i in range(0, 0x8000, 2) if not sl or sl[i:i + 2] != ref[i:i + 2]][:8]
        check('MTSCR %s in the background (MTLAUNCH in front): its 32 KB byte for byte as the BIOS drew it alone (%s), its '
              'BIOS data too; its EMS page in window 2 untouched ("%s+"); the screen in front untouched' % (M, what, M),
              r0 == r1 == (M + '+').encode() and w and st[0][1:] == [(1, 2, 'MTSCR.COM')] and 'MTLAUNCH waits>' in front_
              and sl == ref and tv == rbd, (r0, w, r1, st, diff, tv.hex(), rbd.hex()))
        front(k, 1); line(k, ''); line(k, '')
        # shadowed in front, another task there: the same calls done in its pages (mt_vshad), found to match the BIOS's
        typ(k, 'mtlaunch mtline.com x.txt;/f mtscr.com %s %s2.txt' % (m, m), 0.5)
        w2 = waitfile(k, M + '2.TXT', 30)
        s_on, f1 = shd(k), tstate(k)[1]
        front(k, 0)
        c_v, sl2 = vflags(k, 2), slot(k, 2, 0x8000)
        front(k, 2); line(k, '')
        front(k, 1); line(k, 'x'); line(k, '')
        check('MTSCR %s in front, another task there: shadowed (mt_shd 1) in its pages, byte for byte as the BIOS drew it; '
              'switched from, found not to write the screen itself' % M, w2 and A.disk_file(k, M + '2.TXT') == (M + '+').encode()
              and f1 == 2 and s_on == 1 and c_v & VF_DIRECT == 0 and sl2 == ref, (w2, A.disk_file(k, M + '2.TXT'), f1, s_on,
                                                                                  c_v))
    o9, o6 = off.get((9, 0, 2000)), off.get((6, 0x1F, 0x1900))
    check('interrupts off for 09h\'s 2000 cells on page 0 (V) under 3 ms (%s us: one REP STOSW, not a cell at a time)'
          % o9, o9 is not None and o9 < 3000, o9)
    check('... and for page 0\'s "clear below" run on from row 25 (U) under 30 ms (%s us: the 151 rows wholly past the '
          '32 KB skipped, not walked a cell at a time)' % o6, o6 is not None and o6 < 30000, o6)

def two(v):
    """MTKEY's "nnnn kkkk" -> (n, k), or None."""
    return tuple(int(x, 16) for x in v.split()) if v and re.fullmatch(rb'[0-9A-F]{4} [0-9A-F]{4}', v) else None

def waittwo(k, name, sim_s=6.0):
    """Run until MTKEY's FILE holds its two numbers (on the disk, not just named); them, or None."""
    u0 = k.pc.us
    while k.pc.us - u0 < sim_s * 1e6:
        k.run_for(0.05)
        v = two(A.disk_file(k, name))
        if v: return v
    return None

def kclear(k):
    """Nothing typed left (keys the test put there for no one)."""
    k.pc.keys.clear(); k.pc.wr(0x40, 0x1A, bytes(k.pc.rd(0x40, 0x1C, 2))); k.pc.kbd_mirror = []; k.run_for(0.1)

MTIK = os.path.join(HERE, 'MTIRQK.COM')

def t_irqk():
    print('== M9b: a key read through DOS from an interrupt\'s handler, its IRQ still in service')
    k = boot('mt_ik.img', b'MULTITASK=1\r\n', 88, MTIK)
    Y, seg = k.Y, mt_seg(k)
    sh = Shell(k)
    sh.run('ver')
    cur = lambda: k.pc.rd(seg, Y['mt_cur'], 1)[0]
    swa, sw, prev = seg * 16 + Y['mt_switch'], [], k.pc.watch
    got = {}
    for case, when in (('front', lambda: cur() == 0), ('behind', lambda: cur() != 0)):
        typ(k, 'mtlaunch mtspin.com 300 s%s.txt' % case[0], 0.5); line(k, '')    # (counting behind, 16 s)
        f = 'K%s.TXT' % case[0].upper()
        v0 = vec(k, 0x0F)
        typ(k, 'mtirqk %s' % f, 0.1)
        t1 = k.pc.us + 3e6                              # (hooked and unmasked, then the task wanted running)
        while (vec(k, 0x0F) == v0 or k.pc.pic_mask & 0x80) and k.pc.us < t1: k.pc.run(300)
        h7 = vec(k, 0x0F)
        h7 = h7[0] * 16 + h7[1]
        while not when() and k.pc.us < t1: k.pc.run(300)
        n, at = len(sw), []
        def w(a):
            if prev: prev(a)
            if a == swa: sw.append(k.pc.isr)
            if a == h7 and not at: at.append(cur())     # (the task the handler runs in)
        k.pc.watch = w
        k.pc.irq_pending.add(7)
        k.run_for(0.5)
        held = k.pc.isr & 0x80
        k.key('x' if case == 'front' else 'y', settle=False)
        dt = waitfile(k, f, 3.0)
        k.pc.watch = prev
        got[case] = (A.disk_file(k, f), held, [i for i in sw[n:] if i & 0x80], dt is not None, at)
        line(k, '')
    check('a key read through DOS (AH=08h) from an IRQ 7 handler before its EOI, raised while the task in front runs: '
          'no task switched to while IRQ 7 is in service; it waits in front for the key, as in DOS, and gets it (%s)'
          % (got['front'],), got['front'][0] == b'x' and got['front'][1] and not got['front'][2]
          and got['front'][4] == [0], got['front'])
    check('... raised while a task behind runs (MTSPIN), so the handler\'s read is that task\'s: read as it is (no '
          'park, no switch while IRQ 7 is in service, M5b\'s forced front not taken), the key typed reaching it (%s)'
          % (got['behind'],), got['behind'][0] == b'y' and got['behind'][1] and not got['behind'][2]
          and got['behind'][4] and got['behind'][4][0] != 0, got['behind'])
    waitfile(k, 'SB.TXT', 30.0)
    check('MTSPIN behind ended as usual after each (its counts %d and %d)' % (spun(k, 'SF.TXT'), spun(k, 'SB.TXT')),
          spun(k, 'SF.TXT') > 0 and spun(k, 'SB.TXT') > 0 and not k.crashed)

MTFS = os.path.join(HERE, 'MTFAST.COM')
MTCL = os.path.join(HERE, 'MTCLI.COM')
def tick_rate(k, s=2.0):
    """The BIOS's ticks (40:6Ch) and MT's (mt_ticks: the turns' length) a simulated second, over s."""
    seg, Y = mt_seg(k), k.Y
    b0, m0, u0 = k.pc.u16(0x40, 0x6C), k.pc.u16(seg, Y['mt_ticks']), k.pc.us
    k.run_for(s)
    du = (k.pc.us - u0) / 1e6
    return (round(((k.pc.u16(0x40, 0x6C) - b0) & 0xFFFF) / du, 1),
            round(((k.pc.u16(seg, Y['mt_ticks']) - m0) & 0xFFFF) / du, 1))

def wait_pit(k, n, s=3.0):
    t1 = k.pc.us + s * 1e6
    while k.pc.pit_n != n and k.pc.us < t1: k.run_for(0.05)
    return k.pc.pit_n

def t_pitfast():
    print('== M9b: a program that runs the timer fast (counter 0 four times, its own INT 08h hook)')
    k = boot('mt_pf.img', b'MULTITASK=1\r\n', 88, MTFS)
    Y, seg = k.Y, mt_seg(k)
    sh = Shell(k)
    sh.run('ver')
    rate = lambda: tick_rate(k)
    ref = rate()
    near = lambda r, x=1: all(abs(v - x * ref[0]) < 0.06 * x * ref[0] for v in r)
    typ(k, 'mtlaunch mtfast.com 120 fb.txt;mtspin.com 120 sb.txt', 0.5); line(k, '')
    fast = wait_pit(k, 0x4000)
    beh = rate()
    waitfile(k, 'FB.TXT', 20.0); waitfile(k, 'SB.TXT', 20.0)
    fb = spun(k, 'FB.TXT')
    check('MTFAST behind (counter 0 at 4000h, its hook calling the BIOS\'s every 4th tick) with MTSPIN: the BIOS\'s '
          'clock and the turns at their rate meanwhile (%s a second, %s alone): MT divides in the others\' turns, '
          'its hook in its own (its calls %d)' % (beh, ref, fb), fast == 0x4000 and near(beh) and fb > 120, (fast, beh, ref, fb))
    typ(k, 'mtlaunch mtspin.com 120 sf.txt', 0.5); line(k, '')
    typ(k, 'mtfast 80 ff.txt k', 0.5)
    fast = wait_pit(k, 0x4000)
    fr = rate()
    waitfile(k, 'FF.TXT', 20.0)
    left = k.pc.pit_n
    after = rate()
    waitfile(k, 'SF.TXT', 20.0)
    check('... in front (task 0), MTSPIN behind: at their rate too (%s); and once it has ended leaving the counter '
          'fast (K: %04Xh), still (%s: MT divides for every task)' % (fr, left, after),
          fast == 0x4000 and near(fr) and left == 0x4000 and near(after) and spun(k, 'FF.TXT') > 80
          and not k.crashed, (fast, fr, left, after, spun(k, 'FF.TXT')))
    # its own INT 1Ch hook only (no INT 08h one), the clock let race: in its own turns as in DOS
    typ(k, 'mtfast 300 fc.txt c', 0.5)
    k.run_for(0.3)
    own = rate()
    waitfile(k, 'FC.TXT', 20.0)
    calls = spun(k, 'FC.TXT')
    check('... C (an INT 1Ch hook of its own, none on INT 08h), in front alone: MT doesn\'t divide in its turns, '
          'its INT 1Ch, the clock and the turns at the fast rate (%s a second), as in DOS; its calls %d'
          % (own, calls), near(own, 4) and 290 <= calls <= 310 and k.pc.pit_n == 65536 and not k.crashed,
          (own, calls, k.pc.pit_n))

def t_pitcli():
    print('== M9b: the timer\'s interrupt held late under CLI, by a different time each tick: not a fast counter')
    k = boot('mt_pc.img', b'MULTITASK=1\r\n', 88, MTCL)
    Y, seg = k.Y, mt_seg(k)
    sh = Shell(k)
    sh.run('ver')
    ref = tick_rate(k)
    reads, pr = [], k.pc.pit_read
    def latch():                        # (MT's reads of counter 0, at its ticks)
        pr()
        if k.pc.r('cs') == seg: reads.append(k.pc.pit_latch)
    k.pc.pit_read = latch
    b0, m0, u0 = k.pc.u16(0x40, 0x6C), k.pc.u16(seg, Y['mt_ticks']), k.pc.us
    typ(k, 'mtlaunch mtcli.com 100 cl.txt', 0.5); line(k, '')
    waitfile(k, 'CL.TXT', 60.0)
    du = (k.pc.us - u0) / 1e6
    got = (round(((k.pc.u16(0x40, 0x6C) - b0) & 0xFFFF) / du, 1),
           round(((k.pc.u16(seg, Y['mt_ticks']) - m0) & 0xFFFF) / du, 1))
    k.pc.pit_read = pr
    low = sum(r < 0x8000 for r in reads)
    check('MTCLI behind (interrupts off from each tick to 15-22 ms after it, a different time each): most ticks read '
          'low (%d of %d), yet the clock and the turns keep their rate over its run (%s a second, %s alone): two '
          'reads not the same, so not a fast counter' % (low, len(reads), got, ref),
          low > len(reads) // 2 and all(abs(v - ref[0]) < 0.06 * ref[0] for v in got)
          and A.disk_file(k, 'CL.TXT') == b'ok' and not k.crashed, (low, len(reads), got, ref))

def t_keys():
    print('== keys: the front task\'s only (INT 16h through MT), its waits switched from, CODE-Tab wherever it is typed')
    k = boot('mt_k.img', b'MULTITASK=1\r\n', 88, MTK)
    seg, Y = mt_seg(k), k.Y
    au = Audit(k)
    sh = Shell(k)
    sh.run('ver')
    # the references: in front, alone, the same programs see the keys typed
    ref = {}
    for m in 'pdqt':
        typ(k, 'mtkey %s %s0.txt' % (m, m), 0.2)
        k.key('ab', settle=False)
        ref[m] = waittwo(k, '%s0.TXT' % m.upper())
        kclear(k)
        line(k, '')
    check('the references, MTKEY in front with nothing else there, "ab" typed: its INT 16h peeks find them (P %s; Q, '
          'interrupts off, %s; T, from its INT 1Ch handler, %s), DOS\'s key status says so and AH=06h reads them (D %s)'
          % (ref['p'], ref['q'], ref['t'], ref['d']),
          ref['p'] and ref['p'][1] > 10 and ref['q'] and ref['q'][1] > 10 and ref['t'] and ref['t'][1] > 5
          and ref['d'] and ref['d'][0] > 0 and ref['d'][1] == 2, ref)
    sh.run('cls')
    # behind a task in front that computes and reads no keys: none for them; the keys left for the front one
    got, rings, own = {}, [], []
    i16, prev = seg * 16 + Y['mt_i16'], k.pc.watch
    def w(a):                                   # (T's handler's peeks in T's own task, task 3, behind: keys there)
        if prev: prev(a)
        if a == i16 and k.pc.isr and k.pc.rd(seg, Y['mt_cur'], 1)[0] == 3 and k.pc.rd(seg, Y['mt_front'], 1)[0] != 3 \
                and k.pc.kbd_ring(): own.append(1)
    # (Q polls with interrupts off nearly all the time: pcemu, taking a tick only where its run loop restarts
    # with them on, held most of T's 18 for Q's whole turn, and when one got through, so how many turns T had,
    # moved with the kernel's code; boot()'s irq_exact takes a held tick as soon as IF is set, as the PIC gives it)
    for ms in ('pd', 'qt'):
        if ms == 'qt': k.pc.watch = w
        typ(k, 'mtlaunch /f mtspin.com 60 s%s.txt;mtkey.com %s %s1.txt;mtkey.com %s %s1.txt'
            % (ms, ms[0], ms[0], ms[1], ms[1]), 0.3)
        k.key('abc', settle=False)
        for m in ms:
            got[m] = waittwo(k, '%s1.TXT' % m.upper())
        k.pc.watch = prev
        rings.append((tstate(k)[1], k.pc.kbd_ring()))
        kclear(k)
        waitfile(k, 'S%s.TXT' % ms.upper(), 6.0)
        line(k, '')
    check('behind MTSPIN (in front, reading no keys), "abc" typed: MTKEY\'s INT 16h peeks find none (P %s), and Q\'s '
          'with interrupts off none either (%s, counting those back with interrupts on, as the BIOS\'s are: whose code '
          'it is that counts); nor DOS\'s key status, AH=06h or the flush '
          '(D %s); the keys still there for the front task' % (got['p'], got['q'], got['d']),
          got['p'] and got['p'][0] > 10 and got['p'][1] == 0 and got['q'] and got['q'][0] > 10 and got['q'][1] == 0
          and got['d'] == (0, 0) and all(r == (1, [0x61, 0x62, 0x63]) for r in rings), (got, rings))
    check('... as it is from an INT 1Ch handler (T %s: the timer\'s interrupt in service, a TSR\'s peek, the machine\'s): '
          'every one finds them; INT 1Ch being each task\'s own (M5a), MTKEY T\'s handler is called in its own turns '
          'only, of 18 ticks (%d there)' % (got['t'], len(own)),
          got['t'] and 2 < got['t'][0] < 15 and got['t'][1] == got['t'][0] and len(own) == got['t'][0],
          (got['t'], len(own)))
    # a program that only polls in front: its peeks give the others their turns (mt_preempt from there, at a safe
    # point), which on the 1520 a tick, landing in MT or the BIOS, seldom can; here (MTKEY Y) the tick can't at all,
    # its own INT 08h hook being ahead of MT's
    # Y's turn is made due: pcemu takes ticks only where its run loop restarts with interrupts on, and Y's
    # loop is nearly all in mt_i16 with them off (not X21's case; that check is at MTKEY R's wait below)
    n0 = len(au.ev)
    typ(k, 'mtlaunch /f mtkey.com y pp.txt;mtspin.com 15 sp.txt', 0.3)
    k.pc.run_until(lambda: vec(k, 8) != (seg, Y['mt_tick']), 3)
    k.pc.wr(seg, Y['mt_pend'], b'\1')
    k.key('a', settle=False)
    pp = waittwo(k, 'PP.TXT')
    waitfile(k, 'SP.TXT', 4.0)
    kclear(k)
    line(k, '')
    sw = au.switches(n0, 'peek')
    check('MTKEY Y polling in front ("a" there, %s), the tick kept from switching by its INT 08h hook, its turn made '
          'due: MTSPIN behind still runs (%d), switched to from Y\'s peeks (%d times) at safe points'
          % (pp, spun(k, 'SP.TXT'), len(sw)), pp and pp[1] > 10 and spun(k, 'SP.TXT') > 0 and sw
          and not au.bad(), (pp, spun(k, 'SP.TXT'), len(sw), au.bad()[:2]))
    # inside an INT 13h call, or a call MT passed on to the BIOS (the test sets the count while P runs behind): an
    # interrupt's, as it is
    for var, f in (('mt_in13', '13'), ('mt_inb', 'ib')):
        hit = []
        def w(a):
            if prev: prev(a)
            if a == i16 and not hit and k.pc.rd(seg, Y['mt_cur'], 1)[0] == 2:
                hit.append(1); k.pc.wr(seg, Y[var], b'\1')
        k.pc.watch = w
        typ(k, 'mtlaunch /f mtspin.com 60 s%s.txt;mtkey.com p p%s.txt' % (f, f), 0.3)
        k.key('abc', settle=False)
        p13 = waittwo(k, 'P%s.TXT' % f.upper())
        k.pc.watch = prev
        kclear(k)
        waitfile(k, 'S%s.TXT' % f.upper(), 6.0)
        n13 = k.pc.rd(seg, Y[var], 1)[0]
        line(k, '')
        if var == 'mt_in13':
            check('MTKEY P behind, inside an INT 13h call (mt_in13 set by the test as it starts peeking): its peeks taken '
                  'as an interrupt\'s, as they are: they find "abc" (%s); the count cleared when it ends' % (p13,),
                  hit and p13 and p13[1] > 0 and n13 == 0, (hit, p13, n13))
        else:
            check('... inside a call MT passed on to the BIOS (mt_inb, set the same way): the same (%s)' % (p13,),
                  hit and p13 and p13[1] > 0 and n13 == 0, (hit, p13, n13))
    sh.run('cls')
    # a read in the background (INT 16h AH=00h): it waits until it is in front, the keys typed meanwhile not its
    n0 = len(au.ev)
    typ(k, 'mtlaunch mtkey.com r r1.txt', 1.0)
    st0 = tstate(k)
    line(k, 'hello')
    st1, r1 = tstate(k), A.disk_file(k, 'R1.TXT')
    front(k, 1)
    st2 = tstate(k)
    k.key('q', settle=False); k.run_for(0.5)
    r2 = A.disk_file(k, 'R1.TXT')
    sw = au.switches(n0, 'i16')
    check('MTKEY R in the background: its INT 16h read waits (TS_WAITK) while MTLAUNCH, in front, gets its line; brought '
          'to the front at the command prompt (M4b: at the next safe point, not only at a DOS key wait), it gets the '
          'next key ("q": 0071h, as pcemu gives a typed character); %d switches from INT 16h, each at a safe point' % len(sw),
          st0[0][1:] == [(1, TS_WAITK, 'MTKEY.COM')] and st0[1] == 0 and r1 is None
          and st2[1] == 1 and r2 == b'0071' and sw and not au.bad(), (st0, st1, r1, st2, r2, len(sw), au.bad()[:2]))
    line(k, '')
    # a read in front with nothing typed: it waits in MT, not the BIOS, the others running meanwhile
    # (X21: a tick in MT's own code, at mt_i16's HLT, counts against the turn)
    n0 = len(au.ev)
    tk, prev = [], k.pc.watch
    def w(a):
        if prev: prev(a)
        if a == seg * 16 + Y['mt_tick']:
            tk.append([k.pc.u16(k.pc.r('ss'), k.pc.r('sp') + 2) == seg, False])
        elif a == seg * 16 + Y['mt_tick.p'] and tk: tk[-1][1] = True
    k.pc.watch = w
    typ(k, 'mtlaunch /f mtkey.com r r2.txt;mtspin.com 20 s2.txt', 1.0)
    st = tstate(k)
    k.run_for(1.5)
    k.pc.watch = prev
    inmt = [p for c, p in tk if c]
    check('ticks landing in MT\'s own code (%d of %d: MTKEY R\'s wait in front at mt_i16\'s HLT) counted: its turn over '
          '(%d of them; audit3 X21)' % (len(inmt), len(tk), sum(inmt)), sum(inmt) >= 3, tk)
    s2, r2 = spun(k, 'S2.TXT'), A.disk_file(k, 'R2.TXT')
    k.key('q', settle=False); k.run_for(0.3)
    r3 = A.disk_file(k, 'R2.TXT')
    sw = au.switches(n0, 'i16')
    check('MTKEY R in front, nothing typed: it waits (TS_WAITK) while MTSPIN runs its 20 ticks (count %d); then "q" '
          'reaches it (0071h); %d switches from its INT 16h call, at safe points' % (s2, len(sw)),
          st[1] == 1 and (1, TS_WAITK, 'MTKEY.COM') in st[0] and s2 > 0 and r2 is None and r3 == b'0071' and sw
          and not au.bad(), (st, s2, r2, r3, len(sw)))
    line(k, '')
    # AH=10h: the wait looks with AH=11h, which keeps the CODE keys AH=01h drops
    typ(k, 'mtlaunch /f mtkey.com e e1.txt;mtspin.com 10 s3.txt', 1.0)
    k.key(0x35F0, settle=False); k.run_for(0.5)
    e1 = A.disk_file(k, 'E1.TXT')
    check('MTKEY E (AH=10h) in front, waiting: CODE-? (35F0h, a key AH=01h drops) reaches it (3500h, as AH=10h gives '
          'it)', e1 == b'3500', e1)
    line(k, '')
    # CODE-Tab while the front task waits in its INT 16h read, and while it computes asking for no keys
    typ(k, 'mtlaunch /f mtkey.com r r4.txt;mtline.com l4.txt', 1.0)
    k.key(HOT, settle=False); k.run_for(0.5)
    st = tstate(k)
    line(k, 'four')
    k.key(HOT, settle=False); k.run_for(0.5)
    stb = tstate(k)
    k.key('q', settle=False); k.run_for(0.5)
    check('CODE-Tab while MTKEY waits in its INT 16h read (in front): MTLINE comes to the front, gets its line; CODE-Tab '
          'back, and MTKEY gets "q"', st[1] == 2 and A.disk_file(k, 'L4.TXT') == b'four' and stb[1] == 1
          and A.disk_file(k, 'R4.TXT') == b'0071', (st, stb, A.disk_file(k, 'L4.TXT'), A.disk_file(k, 'R4.TXT')))
    # switched from in the middle of its run, its shadow lost (not known whether it writes the screen itself):
    # frozen behind, to be safe; switched from at its key wait, the same way: not
    line(k, '')
    typ(k, 'mtlaunch /f mtspin.com 60 s11.txt;mtline.com l11.txt', 0.8)
    k.pc.wr(seg, Y['mt_shd'], b'\0'); set_vflags(k, 1, 0)
    k.key(HOT, settle=False); k.run_for(0.4)
    st, v1 = tstate(k), vflags(k, 1)
    k.pc.wr(seg, Y['mt_shd'], b'\0')
    k.key(HOT, settle=False); k.run_for(0.4)
    st2, v2 = tstate(k), vflags(k, 2)
    front(k, 2)
    line(k, 'eleven')
    front(k, 1)
    waitfile(k, 'S11.TXT', 6.0)
    line(k, '')
    check('MTSPIN in front, computing, its shadow lost: switched from by CODE-Tab, it is taken as writing the screen '
          'itself (VF_DIRECT: frozen behind); MTLINE, its shadow lost at its key wait, switched from: not',
          st[1] == 2 and v1 & VF_DIRECT and st2[1] != 2 and not v2 & VF_DIRECT and A.disk_file(k, 'L11.TXT') == b'eleven',
          (st, v1, st2, v2, A.disk_file(k, 'L11.TXT')))
    # the one in front at its key wait, switched from while another runs (mt_swnow, from the tick in MTSPIN's turn):
    # not in its run, so not frozen, however its shadow stands
    line(k, '')
    typ(k, 'mtlaunch /f mtline.com l13.txt;mtspin.com 60 s13w.txt', 0.8)
    k.pc.wr(seg, Y['mt_shd'], b'\0'); set_vflags(k, 1, 0)
    k.key(HOT, settle=False); k.run_for(0.4)
    st, v1 = tstate(k), vflags(k, 1)
    front(k, 1)
    line(k, 'thirteen')
    waitfile(k, 'S13W.TXT', 6.0)
    line(k, '')
    check('MTLINE in front at its key wait, MTSPIN running behind, MTLINE\'s shadow lost: switched from by CODE-Tab '
          '(in MTSPIN\'s turn): not taken as writing the screen itself', st[1] == 2 and not v1 & VF_DIRECT
          and A.disk_file(k, 'L13.TXT') == b'thirteen', (st, v1, A.disk_file(k, 'L13.TXT')))
    # while mt_swnow changes the front (mt_swing, set by the test): CODE-Tab's change waits until it is done
    typ(k, 'mtlaunch /f mtspin.com 60 s12.txt;mtline.com l12.txt', 0.8)
    k.pc.wr(seg, Y['mt_swing'], b'\1')
    k.key(HOT, settle=False); k.run_for(0.4)
    st = tstate(k)
    k.pc.wr(seg, Y['mt_swing'], b'\0'); k.run_for(0.4)
    st2 = tstate(k)
    line(k, 'twelve')
    front(k, 1)
    waitfile(k, 'S12.TXT', 6.0)
    line(k, '')
    check('CODE-Tab while the front is being changed (mt_swing, set by the test): not changed meanwhile; then it is',
          st[1] == 1 and st2[1] == 2 and A.disk_file(k, 'L12.TXT') == b'twelve', (st, st2, A.disk_file(k, 'L12.TXT')))
    line(k, '')
    typ(k, 'mtlaunch /f mtspin.com 60 s5.txt;mtline.com l5.txt;mtline.com l5b.txt', 0.8)
    k.key(HOT, settle=False); k.run_for(0.4)
    st = tstate(k)
    front(k, 1)
    st1 = tstate(k)
    front(k, 2)
    line(k, 'five')
    front(k, 3)
    line(k, 'more')
    k.run_for(3.0)
    check('CODE-Tab while MTSPIN computes in front, asking for no keys: the tick finds it at a safe point, and MTLINE '
          'comes to the front for its line; a task asked for in front with no key at all (mt_swreq, as MT_FRONT sets '
          'it) is brought there by the tick too', st[1] == 2 and no_hot(k) and A.disk_file(k, 'L5.TXT') == b'five'
          and st1[1] == 1 and A.disk_file(k, 'L5B.TXT') == b'more' and spun(k, 'S5.TXT') > 0,
          (st, st1, A.disk_file(k, 'L5.TXT'), A.disk_file(k, 'L5B.TXT')))
    line(k, '')
    # INT 21h's way out: CODE-Tab found by DOS's key status (AH=0Bh's INT 16h call) in a task with a timer hook of
    # its own ahead of MT's (MTKEY X), so the tick doesn't switch: on the way out of that call
    typ(k, 'mtlaunch /f mtkey.com x x8.txt;mtline.com l8.txt', 0.2)
    for i in range(60):
        st = tstate(k)
        if vec(k, 8) != (seg, Y['mt_tick']) and st[1] == 1 and (2, TS_WAITK, 'MTLINE.COM') in st[0]: break
        k.run_for(0.05)
    v8 = vec(k, 8)
    seen, prev = [], k.pc.watch                 # (CODE-Tab taken, then ticks and INT 21h's way out, in order)
    marks = {seg * 16 + Y['mt_hot.m']: 'hot', seg * 16 + Y['mt_tick']: 'tick', seg * 16 + Y['mt_exit.c']: 'exit'}
    def w(a):
        if prev: prev(a)
        m = marks.get(a)
        if m and (seen or m == 'hot') and len(seen) < 40: seen.append(m)
    k.pc.watch = w
    k.key(HOT, settle=False); k.run_for(0.3)
    k.pc.watch = prev
    st, x8 = tstate(k), A.disk_file(k, 'X8.TXT')
    first = seen[:seen.index('exit') + 1] if 'exit' in seen else seen
    line(k, 'eight')
    waittwo(k, 'X8.TXT')
    check('CODE-Tab while MTKEY X asks DOS for keys in front, its own timer hook ahead of MT\'s (so the tick doesn\'t '
          'switch): switched on the way out of the very INT 21h call that found it (no tick between: %s), MTLINE in '
          'front for its line' % first, v8 != (seg, Y['mt_tick']) and st[1] == 2 and x8 is None
          and first[:1] == ['hot'] and first[-1:] == ['exit'] and 'tick' not in first
          and A.disk_file(k, 'L8.TXT') == b'eight' and two(A.disk_file(k, 'X8.TXT')) == (0, 0)
          and vec(k, 8) == (seg, Y['mt_tick']), (v8, st, x8, first, A.disk_file(k, 'L8.TXT'), A.disk_file(k, 'X8.TXT')))
    line(k, '')
    # a read with interrupts off: not where a task may be switched from, so as it is (to the BIOS)
    n0 = len(au.ev)
    typ(k, 'mtlaunch /f mtkey.com c c1.txt;mtspin.com 10 sc.txt', 0.8)
    st, blk, c0 = tstate(k), k.pc.blocked, A.disk_file(k, 'C1.TXT')
    k.key('q', settle=False); k.run_for(1.0)
    check('MTKEY C (its read with interrupts off) in front, waiting in the BIOS (the read before the key: running, '
          'blocked): not switched from there (no switch from INT 16h), as it is: the key reaches it',
          st[1] == 1 and st[2] == 1 and (1, 1, 'MTKEY.COM') in st[0] and blk and c0 is None
          and A.disk_file(k, 'C1.TXT') == b'0071' and not au.switches(n0, 'i16') and not au.bad(),
          (st, blk, c0, A.disk_file(k, 'C1.TXT'), len(au.switches(n0, 'i16')), au.bad()[:2]))
    k.run_for(1.0)
    line(k, '')
    # a background task at a DOS key wait it can't be switched from: a nested INT 21h (InDOS 2, set by the test for
    # that wait, as a TSR's read from the kernel's INT 28h would have it): it comes to the front for its keys, which
    # only the front task gets; inside an INT 13h call or a change of the front (set by the test): as it is, it reads
    # them there
    hit, prev = [], k.pc.watch
    bg, hv = seg * 16 + Y['mt_kwait.bg'], seg * 16 + Y['mt_kwait.have']
    for n, tag in enumerate(('indos', 'in13', 'swing')):
        def w(a):
            if prev: prev(a)
            if a == bg and len(hit) <= n:
                hit.append(tstate(k))
                if tag == 'indos': k.pc.wr(0x60, Y['indos'], b'\2')
                else: k.pc.wr(seg, Y['mt_' + tag], b'\1')
            elif a == hv and tag == 'indos' and k.pc.rd(0x60, Y['indos'], 1)[0] == 2:
                k.pc.wr(0x60, Y['indos'], b'\1')
        k.pc.watch = w
        typ(k, 'mtlaunch mtline.com l6%s.txt' % 'abc'[n], 1.0)
        st = tstate(k)
        line(k, 'six')
        k.pc.watch = prev
        k.pc.wr(seg, Y['mt_in13'], b'\0'); k.pc.wr(seg, Y['mt_swing'], b'\0')
        line(k, '')
        if tag == 'indos':
            check('MTLINE behind at its DOS key wait, nested (InDOS 2: it can\'t give way there): it comes to the front, '
                  'and gets its line', hit and hit[0][1] == 0 and hit[0][2] == 1 and st[1] == 1
                  and A.disk_file(k, 'L6A.TXT') == b'six', (hit, st, A.disk_file(k, 'L6A.TXT')))
        elif tag == 'in13':
            check('... inside an INT 13h call (mt_in13): not brought to the front (no screen mapped there); it reads the '
                  'keys as it is, from behind', len(hit) == 2 and hit[1][2] == 1 and st[1] == 0
                  and A.disk_file(k, 'L6B.TXT') == b'six', (hit, st, A.disk_file(k, 'L6B.TXT')))
        else:
            check('... while the front is being changed (mt_swing, set the same way): the same', len(hit) == 3
                  and hit[2][2] == 1 and st[1] == 0 and A.disk_file(k, 'L6C.TXT') == b'six',
                  (hit, st, A.disk_file(k, 'L6C.TXT')))
    v = sh.run('ver')
    check('... all ended, the prompt as before; nothing left in the key buffer', 'Lodestone version' in v
          and tstate(k)[0] == [(0, 1, 'Executive')] and k.pc.kbd_ring() == [] and not k.crashed, (v[-80:], tstate(k)))
    # CODE-Tab in the Executive itself (its own key loop: INT 16h AH=11h, then HLT; no DOS)
    typ(k, 'mtlaunch mtline.com l7.txt', 0.8); typ(k, '', 0.3); typ(k, 'exit', 1.0)
    st0, m0 = tstate(k), k.pc.mode()
    k.key(HOT, settle=False); k.run_for(0.5)
    st1, m1 = tstate(k), k.pc.mode()
    line(k, 'seven'); k.run_for(0.5)
    st2, m2 = tstate(k), k.pc.mode()
    check('CODE-Tab in the Executive, idle in front with MTLINE waiting behind: MTLINE comes to the front (mode 3) and '
          'gets its line; ended, the Executive is back in front (mode 40h)', st0[1] == 0 and m0 == 0x40 and st1[1] == 1
          and m1 == 3 and A.disk_file(k, 'L7.TXT') == b'seven' and st2 == ([(0, 1, 'Executive')], 0, 0) and m2 == 0x40
          and no_hot(k) and not k.crashed, (st0, hex(m0), st1, hex(m1), st2, hex(m2), A.disk_file(k, 'L7.TXT')))
    check('every switch made from INT 16h (%d) or elsewhere (%d) at a safe point' % (len(au.switches(0, 'i16')),
          len(au.switches())), au.switches(0, 'i16') and not au.bad(), au.bad()[:3])
    check('the stack MT used under the caller\'s SP there: %d bytes at the tick, %d at INT 16h, %d at a peek (under '
          '64; at the tick, the front changed on MT\'s own)' % (au.depth['tick'], au.depth['i16'], au.depth['peek']),
          all(0 < au.depth[p] < 64 for p in ('tick', 'i16', 'peek')), au.depth)
    au.stop()
    # a TSR's INT 16h hook loaded after MT, waiting in its own loop (as Resident Claude's does): its peeks are its
    # code's, not the task's, so they find the key; then it passes the read on, the program's own, which waits
    k = boot('mt_kh.img', b'MULTITASK=1\r\n', 88, MTK, os.path.join(HERE, 'KEYIN.COM'))
    sh = Shell(k)
    sh.run('mtkey h x')
    typ(k, 'mtlaunch /f mtspin.com 60 sh.txt;mtkey.com d dh.txt;mtkey.com p ph.txt', 0.3)
    k.key('abc', settle=False)
    dh, ph = waittwo(k, 'DH.TXT'), waittwo(k, 'PH.TXT')
    ring = k.pc.kbd_ring()
    kclear(k)
    waitfile(k, 'SH.TXT', 6.0)
    line(k, '')
    check('with MTKEY H\'s INT 16h hook loaded after MT (calling on with PUSHF / CALL FAR): DOS\'s key status behind '
          'still finds none (D %s: the kernel\'s call, on its stack), the keys left for the front task; a program\'s '
          'peek through it is the hook\'s code\'s, as it is (P %s finds them)' % (dh, ph),
          dh == (0, 0) and ph and ph[1] > 0 and ring == [0x61, 0x62, 0x63], (dh, ph, ring))
    typ(k, 'mtlaunch mtkey.com r rh.txt', 1.0)
    k.key('q', settle=False); k.run_for(1.0)
    st, rh = tstate(k), A.disk_file(k, 'RH.TXT')
    line(k, '')
    front(k, 1)
    k.key('z', settle=False); k.run_for(0.5)
    rh2 = A.disk_file(k, 'RH.TXT')
    v = sh.run('ver')
    check('a background read through a TSR\'s own INT 16h wait loop (MTKEY H, loaded after MT): the hook\'s peeks (its '
          'code, not the task\'s) see "q" typed for the front task, then the read it passes on waits (TS_WAITK), the '
          'key left to MTLAUNCH; brought to the front, it gets "z"; the machine goes on', st[0][1:] == [(1, TS_WAITK,
          'MTKEY.COM')] and rh is None and rh2 == b'007A' and 'Lodestone version' in v and not k.crashed,
          (st, rh, rh2, v[-60:]))
    # T5d: a program's own INT 16h hook (KEYIN with an argument hooks it, then reads a key through DOS) behind: MT's
    # wait there asks the hook at each of its turns, the task staying ready (TS_RUN, not TS_WAITK); the prompt in
    # front waiting for keys, nothing else ready, still gets them (switched to when one is typed for it)
    typ(k, 'mtlaunch keyin.com h', 1.0); line(k, '')
    k.run_for(1.0)
    st = tstate(k)
    nk = next((i for i, s_, n in st[0] if n == 'KEYIN.COM'), None)
    t0 = k.pc.us
    v = sh.run('ver')
    dt = (k.pc.us - t0) / 1e6
    if nk: front(k, nk)
    k.key('x', settle=False); k.run_for(1.0)
    st2 = tstate(k)
    check('KEYIN H behind (its own INT 16h hook, a read through DOS): ready, asked at its turns (TS_RUN); VER typed at '
          'the prompt in front answered (%.1f s; 3 at most: the front task switched to for its keys, where without that '
          'it waited 24 in the run recorded); brought to the front, "x" ends it' % dt,
          nk is not None and (nk, 1, 'KEYIN.COM') in st[0] and 'Lodestone version' in v and dt < 3
          and not any(n == 'KEYIN.COM' for i, s_, n in st2[0]) and not k.crashed, (st, v[-80:], st2))
    # X40: CODE-Tab with a tail the ring never reaches (40:1Ch odd, past 40:82h): mt_hot's compaction
    # stops after 16 words instead of looping with interrupts off
    k.run_for(0.5)
    st0 = tstate(k)
    k.pc.wr(0x40, 0x1E, struct.pack('<H', HOT) * 16)
    k.pc.wr(0x40, 0x1A, struct.pack('<HH', 0x1E, 0x41))
    t0 = k.pc.u16(seg, Y['mt_ticks'])
    k.pc.run_for(1.0)
    t1, tl = k.pc.u16(seg, Y['mt_ticks']), k.pc.u16(0x40, 0x1C)
    k.pc.run_for(1.0)
    ring = k.pc.kbd_ring()
    k.pc.wr(0x40, 0x1A, struct.pack('<HH', 0x1E, 0x1E))
    v = sh.run('ver')
    check('CODE-Tab ahead of a tail outside the ring (40:1Ch = 41h): taken out, the words after it moved 16 at most, the '
          'tail put in the ring (%02Xh); the machine goes on (%d ticks in 1 s), the rest taken a CODE-Tab at a time (%d '
          'left)' % (tl, t1 - t0, len(ring)), st0[0] == [(0, 1, 'Executive')] and t1 - t0 >= 15
          and 0x1E <= tl < 0x3E and not tl & 1 and ring == [] and 'Lodestone version' in v and not k.crashed,
          (st0, t1 - t0, hex(tl), ring, v[-60:]))

def three(v):
    """MTM33's FILE: (calls, x, y), or None."""
    try:
        a = v.decode().split()
        return tuple(int(x, 16) for x in a) if len(a) == 3 else None
    except Exception: return None

def waitthree(k, name, sim_s=6.0):
    u0 = k.pc.us
    while k.pc.us - u0 < sim_s * 1e6:
        k.run_for(0.05)
        v = three(A.disk_file(k, name) or b'')
        if v: return v
    return None

def t_mouse():
    print('== the mouse: each task its own INT 33h state; the front task\'s the one the mouse moves')
    k = boot('mt_m.img', b'MULTITASK=1\r\n', 88, MTM, mouse=True)
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    attr = lambda c, r: k.pc.rd(0xB800, (r * 80 + c) * 2 + 1, 1)[0]
    def m33(task, name):                # a field of task's own INT 33h state, in its TX
        tx = k.pc.u16(seg, Y['mt_tab'] + task * MT_ENT + TE_TX)
        return k.pc.u16(tx, equ('TX_M33') + Y[name] - Y['m33_st'])
    live = lambda name: k.u16(name)
    i33 = vec(k, 0x33)
    check('MT on, no task yet: INT 33h is the UI\'s driver, as with MT off', i33 == (k.useg, Y['int33_ui']), i33)
    # F in front (task 1), B behind (task 2): B's calls (reset, position, pointer on, handler) on its own state
    typ(k, 'mtlaunch /f mtm33.com f f1.txt;mtm33.com b b1.txt', 1.0)
    b1 = waitthree(k, 'B1.TXT')
    st, v = tstate(k), vec(k, 0x33)
    check('a task spawned: INT 33h through MT (mt_i33), on to the UI\'s', v == (seg, Y['mt_i33'])
          and k.pc.u16(seg, Y['mt_old33']) == Y['int33_ui'], (v, hex(seg)))
    check('MTM33 F in front, B behind: B\'s reset, position (200, 96), pointer on and handler are its own (03h: %s); '
          'F\'s pointer still on the real screen (40, 12), B\'s not drawn there (25, 12); the driver\'s state F\'s '
          '(320, 100, shown, its handler)' % (b1,), st[1] == 1 and b1 == (0, 200, 96) and attr(40, 12) == 0x70
          and attr(25, 12) == 0x07 and k.pc.mode() == 3 and (live('m33_x'), live('m33_y'), live('m33_cnt')) == (320, 100, 0)
          and live('m33_hpsp') != m33(2, 'm33_hpsp') and m33(2, 'm33_cnt') == 0 and m33(2, 'm33_x') == 200,
          (st, b1, attr(40, 12), attr(25, 12), live('m33_x'), live('m33_y'), live('m33_cnt'), m33(2, 'm33_x')))
    # the mouse moves F's pointer; CODE-Tab: B's, where B put it
    k.pc.mouse_move(80, 0); k.run_for(0.2)
    a1 = (attr(50, 12), attr(40, 12))
    k.key(HOT, settle=False); k.run_for(0.5)
    st2, a2 = tstate(k), (attr(25, 12), attr(50, 12))
    k.pc.mouse_move(16, 0); k.run_for(0.2)
    a3 = (attr(27, 12), attr(25, 12))
    k.key('q', settle=False); k.run_for(0.5)
    b2 = three(A.disk_file(k, 'B1.TXT') or b'')
    st4, a5, c5, x5 = tstate(k), attr(27, 12), live('m33_cnt'), live('m33_x')
    check('the mouse moved: F\'s pointer follows (50, 12); CODE-Tab: B in front, its pointer where it put it (25, 12), '
          'F\'s gone with F\'s screen; moved: B\'s follows (27, 12); B\'s handler called (%s), its position (216, 96)'
          % (b2,), a1 == (0x70, 0x07) and st2[1] == 2 and a2 == (0x70, 0x07) and a3 == (0x70, 0x07)
          and b2 == (1, 216, 96), (a1, st2, a2, a3, b2))
    check('B ended in front: the Executive\'s task in front, with its own INT 33h state (the pointer off, as MTLAUNCH '
          'never asked for it), not B\'s (x %d, not 216): none drawn on its screen' % x5, st4[1] == 0 and a5 == 0x07
          and c5 == 0xFFFF and x5 != 216, (st4, a5, c5, x5))
    front(k, 1)
    a4 = attr(50, 12)
    k.pc.mouse_move(8, 0); k.run_for(0.2)
    k.key('q', settle=False); k.run_for(0.5)
    f1 = three(A.disk_file(k, 'F1.TXT') or b'')
    line(k, '')
    check('F in front again: its pointer back where it was (50, 12); its handler called only while it was in front (2: '
          '%s), its position moved only then (408, 100)' % (f1,), a4 == 0x70 and f1 == (2, 408, 100), (a4, f1))
    # a program behind that sets a handler and ends (MTM33 H, a child of X behind): forgotten in X's own state
    pg, prev, psp, inj = [], k.pc.watch, [], []
    pga, pspa = seg * 16 + Y['mt_pgend'], k.useg * 16 + Y['m33_psp']
    def w(a):
        if prev: prev(a)
        if a == pga: pg.append((k.pc.r('bx'), m33(1, 'm33_hpsp'), m33(1, 'm33_hmask'), tstate(k)[2]))
        if a == pspa and k.pc.rd(seg, Y['mt_cur'], 1)[0] == 1: psp.append(1)
        if len(psp) == 2 and not inj and k.pc.r('flags') & 0x200:     # (H's 14h, interrupts on: a packet)
            inj.append((k.pc.r('cs'), k.pc.r('ip'))); k.pc.mouse_move(8, 0); k.pc.mu.emu_stop()
    k.pc.watch = w
    lx0 = live('m33_x')
    typ(k, 'mtlaunch mtm33.com x x1.txt', 1.0)
    k.pc.watch = prev
    hh, lx1 = three(A.disk_file(k, 'H.TXT') or b''), live('m33_x')
    st3 = tstate(k)
    pre = [e for e in pg if e[0] == e[1] != 0 and e[2] == 0x7F and e[3] == 1]
    h = (m33(1, 'm33_hseg'), m33(1, 'm33_hmask'), m33(1, 'm33_hpsp'))
    front(k, 1)
    k.key('q', settle=False); k.run_for(0.5)
    x1 = three(A.disk_file(k, 'X1.TXT') or b'')
    line(k, '')
    v = sh.run('ver')
    check('... a mouse packet while H\'s own call (14h) is in the driver with interrupts on (in its INT 21h AH=62h, '
          'at %s): held off (the mouse\'s IRQ masked meanwhile), then the front task\'s: H\'s handler not called, its '
          'position not moved (%s); the front\'s moved 8 (%d to %d)' % (inj, hh, lx0, lx1),
          inj and hh == (0, 320, 100) and lx1 == lx0 + 8, (inj, hh, lx0, lx1, len(psp)))
    check('MTM33 X behind runs H, which sets an event handler (on X\'s own state) and ends: forgotten there, as the '
          'driver forgets the front task\'s (%s; set when it ended: %s); X then gets its "q"' % (h, pre[:1]), st3[0][1:] == [(1, 2, 'MTM33.COM')]
          and pre and h == (0, 0, 0) and x1 == (0, 320, 100) and 'Lodestone version' in v and not k.crashed,
          (st3, pg, h, x1, v[-60:]))
    # a new task that never asks for the mouse: its state the driver's when it started, the pointer off and no
    # handler, so the mouse moving while it is in front is as before
    fb = [b for b in mcbs(k) if b[2] == 0][-1]          # (the free block below MT's: zeroed)
    for i in range(0, fb[3] * 16, 0x8000):
        n_ = min(0x8000, fb[3] * 16 - i); k.pc.wr(fb[0] + 1 + i // 16, 0, bytes(n_))
    typ(k, 'mtlaunch /f mtline.com lm.txt', 0.8)
    n, c0 = tstate(k), (m33(1, 'm33_cnt'), m33(1, 'm33_rx'), m33(1, 'm33_hseg'))
    k.pc.mouse_move(16, 8); k.run_for(0.2)
    c1 = (live('m33_cnt'), live('m33_hseg'))
    line(k, 'm')
    line(k, '')
    check('a new task (MTLINE, /F), its program never asking for the mouse: its state as the driver\'s, the pointer '
          'off, no handler (%s); the mouse moved while it is in front: nothing drawn, nothing called, it goes on' % (c0,),
          n[1] == 1 and c0 == (0xFFFF, 8, 0) and c1 == (0xFFFF, 0) and A.disk_file(k, 'LM.TXT') == b'm'
          and not k.crashed, (n, c0, c1, A.disk_file(k, 'LM.TXT')))
    # a call with an interrupt in service (T's INT 1Ch handler, behind): the machine's, on the driver's state
    seen, i33a = [], seg * 16 + Y['mt_i33']
    def w(a):
        if prev: prev(a)
        if a == i33a and k.pc.isr and k.pc.rd(seg, Y['mt_cur'], 1)[0] == 2: seen.append(1)
    k.pc.watch = w
    typ(k, 'mtlaunch /f mtm33.com f ft.txt;mtm33.com t tt.txt', 0.3)
    tt = waitthree(k, 'TT.TXT')
    k.pc.watch = prev
    k.key('q', settle=False); k.run_for(0.5)
    line(k, '')
    check('MTM33 T behind (its position (200, 96)), F in front: its INT 1Ch handler\'s calls, the timer\'s interrupt in '
          'service (%d of them in its own turn), are the machine\'s: given F\'s position, never its own (%s); its own '
          'code is given its own' % (len(seen), tt), seen and tt and tt[0] > 5 and tt[1] == 0 and tt[2] == 200,
          (len(seen), tt))
    # inside MT's call to the BIOS or an INT 13h call (the test sets it as B's first call comes): as they are, on
    # the driver's state (the front task's), as an interrupt's are
    i33a = seg * 16 + Y['mt_i33']
    for var, tag in (('mt_inb', 'i'), ('mt_in13', 'd')):
        hit = []
        def w(a):
            if prev: prev(a)
            if a == i33a and not hit and k.pc.rd(seg, Y['mt_cur'], 1)[0] == 2:
                hit.append(1); k.pc.wr(seg, Y[var], b'\1')
        k.pc.watch = w
        typ(k, 'mtlaunch /f mtm33.com f f%s.txt;mtm33.com b b%s.txt' % (tag, tag), 1.0)
        bq = waitthree(k, 'B%s.TXT' % tag.upper())
        a = (attr(25, 12), attr(40, 12), live('m33_x'))
        k.pc.watch = prev
        k.key('q', settle=False); k.run_for(0.5)        # (B, reading them as it is, then F)
        k.key('q', settle=False); k.run_for(0.5)
        line(k, '')
        check('MTM33 B behind, inside %s (%s set by the test as its first INT 33h call comes): its calls on the '
              'driver\'s state, as they are: its pointer on the real screen (25, 12), F\'s taken away by its reset'
              % ('MT\'s call to the BIOS' if tag == 'i' else 'an INT 13h call', var), hit and bq == (0, 200, 96)
              and a == (0x70, 0x07, 200) and not k.crashed, (hit, bq, a))
    # a reset behind in mode 40h (G, /B so it runs there): its ranges its own mode's, not the front one's text
    typ(k, 'mtlaunch /f /b mtm33.com g g1.txt', 0.1)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5)
    k.key(HOT, settle=False)
    k.run_for(0.1)
    st5b, g0 = tstate(k), A.disk_file(k, 'G1.TXT')
    g1 = waitthree(k, 'G1.TXT')
    st5, md5 = tstate(k), k.pc.mode()
    front(k, 1)
    k.key('q', settle=False); k.run_for(0.5)
    line(k, '')
    check('MTM33 G (mode 40h) sent behind before it resets: its reset there takes its ranges from its own mode (y in '
          'the middle of 400 rows: %s), the screen in front text (mode %Xh)' % (g1, md5), st5b[1] == 0 and g0 is None
          and st5[1] == 0 and md5 == 3 and g1 == (0, 320, 200), (st5b, g0, st5, hex(md5), g1))
    v = sh.run('ver')
    check('... all ended, the prompt as before', 'Lodestone version' in v and tstate(k)[0] == [(0, 1, 'Executive')]
          and not k.crashed, (v[-60:], tstate(k)))
    # a program's INT 33h hook that jumps on (MTM33 J, resident) in front of MT's: F in front, B behind, CODE-Tab:
    # B's pointer drawn, F's not left on B's screen (the UI's driver still answering, through the hook)
    typ(k, 'mtm33 j', 0.5)
    js_ = vec(k, 0x33)[0]
    typ(k, 'mtlaunch /f mtm33.com f fj.txt;mtm33.com b bj.txt', 1.0)
    bj = waitthree(k, 'BJ.TXT')
    aj0 = (attr(40, 12), attr(25, 12))
    k.key(HOT, settle=False); k.run_for(0.5)
    stj, aj1, vj = tstate(k), (attr(40, 12), attr(25, 12)), vec(k, 0x33)[0]
    k.key('q', settle=False); k.run_for(0.5)
    front(k, 1)
    k.key('q', settle=False); k.run_for(0.5)
    line(k, '')
    check('a program\'s INT 33h hook that jumps on (MTM33 J) in front of MT\'s: B\'s calls still its own (%s); CODE-Tab: '
          'B\'s pointer drawn on its screen (25, 12), F\'s not left there (40, 12)' % (bj,), js_ not in (seg, k.useg)
          and bj == (0, 200, 96) and aj0 == (0x70, 0x07) and stj[1] == 2 and aj1 == (0x07, 0x70) and vj == js_,
          (hex(js_), bj, aj0, stj, aj1))
    # another mouse driver (MTM33 D, resident, not chaining): MT's hook stays off it, and at each change of the
    # front its pointer goes (AX=2) and comes back (AX=1): its show count as it was
    # put in place while F (its pointer shown by the UI's driver) is behind: F back in front, the UI's pointer
    # not drawn by the change, D's being the one on INT 33h (D doesn't take the mouse's IRQ, as a real driver
    # would, so the mouse isn't moved here: the UI's own interrupt handler would draw it)
    typ(k, 'mtlaunch /f mtm33.com f fd.txt', 1.0)
    ad0 = attr(40, 12)
    k.key(HOT, settle=False); k.run_for(0.4)
    line(k, '')
    typ(k, 'mtm33 d', 0.5)
    ds_, do_ = vec(k, 0x33)
    k.key(HOT, settle=False); k.run_for(0.4)
    std, ad = tstate(k), attr(40, 12)
    k.key('q', settle=False); k.run_for(0.5)
    line(k, '')
    check('another INT 33h driver put in place while F (its pointer shown, the UI\'s) is behind: F back in front, the '
          'UI\'s pointer not drawn on its screen by the change (40, 12), D\'s the one on INT 33h', ad0 == 0x70
          and std[1] == 1 and ad == 0x07 and A.disk_file(k, 'FD.TXT') is not None and ds_ not in (seg, k.useg, js_),
          (hex(ad0), std, hex(ad), hex(ds_)))
    d2s = [k.pc.u16(ds_, do_ - 4)]
    typ(k, 'mtlaunch /f mtline.com ld.txt', 0.8)
    st6 = tstate(k)
    d2s.append(k.pc.u16(ds_, do_ - 4))
    k.key(HOT, settle=False); k.run_for(0.4)
    st6b = tstate(k)
    d2s.append(k.pc.u16(ds_, do_ - 4))
    k.key(HOT, settle=False); k.run_for(0.4)
    st7 = tstate(k)
    d2s.append(k.pc.u16(ds_, do_ - 4))
    line(k, 'd')
    line(k, '')
    d2s.append(k.pc.u16(ds_, do_ - 4))
    dc, d2 = k.pc.u16(ds_, do_ - 2), k.pc.u16(ds_, do_ - 4)
    check('another INT 33h driver, not the UI\'s: MT\'s hook not put over it; after three changes of the front and the '
          'front task\'s end, its pointer taken away at each (AX=2, counted after each: %s) and put back: its show count as it was (%d)'
          % (d2s, dc if dc < 0x8000 else dc - 0x10000), vec(k, 0x33) == (ds_, do_) and ds_ != seg and st6[1] == 1
          and st6b[1] == 0 and st7[1] == 1 and [d - d2s[0] for d in d2s] == [0, 2, 3, 4, 5] and dc == 0 and A.disk_file(k, 'LD.TXT') == b'd',
          (vec(k, 0x33), st6, st6b, st7, d2, dc, A.disk_file(k, 'LD.TXT')))
    # no mouse found: a background 0Ch masks nothing, and 40:49h is left as it is (MT's saved mode, made stale by
    # the test as the call comes, not written back)
    k = boot('mt_m0.img', b'MULTITASK=1\r\n', 88, MTM)
    seg, Y = mt_seg(k), k.Y
    Shell(k).run('ver')
    in_, prev, hit = seg * 16 + Y['mt_33in'], k.pc.watch, []
    def w(a):
        if prev: prev(a)
        if a == in_ and k.pc.r('ax') in (0x0C, 0x14):
            hit.append(1); k.pc.wr(seg, Y['mt_33md'], b'\7')
    k.pc.watch = w
    md0 = k.pc.mode()
    typ(k, 'mtlaunch mtm33.com h h.txt', 1.0)
    k.pc.watch = prev
    hz = three(A.disk_file(k, 'H.TXT') or b'')
    check('no mouse: MTM33 H behind (reset, 0Ch, 14h): for 0Ch and 14h the mode byte (40:49h) left as it was (%Xh, '
          'not MT\'s saved copy, made stale by the test as each call comes)' % k.pc.mode(), len(hit) == 2 and md0 != 7 and k.pc.mode() == md0
          and hz is not None and not k.crashed, (hit, hex(md0), hex(k.pc.mode()), hz))

def t_vectors():
    print('== vectors: each task its own (M5a)')
    k = boot('mt_v.img', b'MULTITASK=1\r\n', 88, MTV)
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    v1c, v2f, v62, v09, v1b, v23 = (vec(k, n) for n in (0x1C, 0x2F, 0x62, 9, 0x1B, 0x23))
    cur = lambda: k.pc.rd(seg, Y['mt_cur'], 1)[0]
    ent = lambda task, o: k.pc.u16(seg, Y['mt_tab'] + task * MT_ENT + o)
    def txvec(task, n):                 # task's own vector n (one of mt_vrun's), in its TX
        run = list(k.pc.rd(seg, Y['mt_vrun'], equ('MT_NVEC')))
        o = equ('TX_VEC') + run.index(n) * 4
        return k.pc.u16(ent(task, TE_TX), o + 2), k.pc.u16(ent(task, TE_TX), o)
    def txfv(task, i):                  # its INT 09h (0) or 1Bh (1), in its TX
        o = equ('TX_FVEC') + i * 4
        return k.pc.u16(ent(task, TE_TX), o + 2), k.pc.u16(ent(task, TE_TX), o)
    def runs(task, yes, s=2.0):         # run until task is (yes) or isn't the one running, and MT's switch is
        u0 = k.pc.us                    #  over (mt_cur is set before mt_load puts its vectors in; a halted
        while k.pc.us - u0 < s * 1e6:   #  machine's time jumps to the next tick, so no waiting for that)
            if (cur() == task) == yes:
                if k.pc.r('cs') != seg: return True
                k.run_for(0.00005)
            else: k.run_for(0.01)
        return False
    def vread(name):                    # MTVEC V's FILE: INT 1Ch, 2Fh, 23h, 24h
        r = (A.disk_file(k, name) or b'').split()
        return [(int(r[n], 16), int(r[n + 1], 16)) for n in range(0, 8, 2)] if len(r) == 8 else None
    inreg = lambda v, r: r <= v[0] < r + 0x1000
    m0, s0, e0 = merged(mcbs(k)), sft_used(k), ems_used(k)
    # two tasks hooking INT 1Ch (AH=35h/25h), the first to hook ending first: each its own, counting its own turns
    typ(k, 'mtlaunch mtvec.com h 40 h1.txt;mtvec.com h 60 h2.txt', 0.4)
    k.run_for(0.3)
    nr = runs(1, False)
    st = tstate(k)
    b = (txvec(1, 0x10), txvec(1, 0x16), txvec(1, 8), txvec(1, 0x1C))
    reg1 = ent(1, TE_REG)
    waitfile(k, 'H2.TXT', 8.0)
    line(k, '')
    h1, h2 = spun(k, 'H1.TXT'), spun(k, 'H2.TXT')
    check('a task\'s own vectors, in its TX while another runs: MT\'s at their base (INT 10h mt_v10, 16h mt_i16, 08h '
          'mt_tick), its INT 1Ch its own hook (in its region)', nr and (1, 1, 'MTVEC.COM') in st[0]
          and b[:3] == ((seg, Y['mt_v10']), (seg, Y['mt_i16']), (seg, Y['mt_tick'])) and inreg(b[3], reg1), (nr, st, b, hex(reg1)))
    check('two tasks hooking INT 1Ch, the first to hook ending first: each handler called in its own turns only (%d of '
          '40 ticks, %d of 60), and INT 1Ch as it was after both (not the first one\'s, freed)' % (h1, h2),
          0 < h1 < 34 and 0 < h2 < 54 and vec(k, 0x1C) == v1c and merged(mcbs(k)) == m0 and not k.crashed,
          (h1, h2, vec(k, 0x1C), v1c))
    # vectors left pointing into a task's region when it ends: the machine's put back; its own gone with it
    typ(k, 'mtlaunch mtvec.com g g.txt', 0.4)
    waitfile(k, 'G.TXT', 3.0); k.run_for(0.3)
    line(k, '')
    check('a task setting INT 62h (the machine\'s) and 2Fh (its own) and ending without putting them back: INT 62h put '
          'back as it was at its spawn, the Executive\'s INT 2Fh as before', A.disk_file(k, 'G.TXT') == b'g'
          and vec(k, 0x62) == v62 and vec(k, 0x2F) == v2f and not k.crashed, (vec(k, 0x62), v62, vec(k, 0x2F), v2f))
    typ(k, 'mtlaunch mtvec.com r r.txt', 0.4)
    waitfile(k, 'R.TXT', 3.0); k.run_for(0.3)
    line(k, '')
    check('... and staying resident (AH=31h), a file open and an EMS page taken: the same, its region freed, the file '
          'closed and the page given back', A.disk_file(k, 'R.TXT') == b'g' and vec(k, 0x62) == v62
          and vec(k, 0x2F) == v2f and merged(mcbs(k)) == m0 and sft_used(k) == s0 and ems_used(k) == e0
          and A.disk_file(k, 'RO.TXT') is not None and not k.crashed,
          (vec(k, 0x62), show(mcbs(k)), sft_used(k), s0, ems_used(k), e0))
    # INT 09h (the keyboard's) written by a task behind: its own; the front task's in the table meanwhile
    typ(k, 'mtlaunch mtvec.com k 90 k.txt;mtspin.com 40 ks.txt', 0.4)
    k.run_for(0.4)
    reg = ent(1, TE_REG)
    nr = runs(1, False)
    a1, f1 = vec(k, 9), txfv(1, 0)
    front(k, 1); k.run_for(0.3)
    st, a2 = tstate(k), vec(k, 9)
    waitfile(k, 'K.TXT', 9.0); waitfile(k, 'KS.TXT', 6.0); k.run_for(0.3)
    st3 = tstate(k)
    line(k, '')
    check('a task behind writing INT 09h in the table itself: taken off at the switch away, kept in its TX (%04X:%04X), '
          'the front task\'s in the table while another runs (%04X:%04X); in front, its own (%04X:%04X); as it was after it '
          'ends' % (f1 + a1 + a2), nr and inreg(f1, reg) and a1 == v09 and st[1] == 1 and a2 == f1
          and A.disk_file(k, 'K.TXT') == b'k' and st3[1] == 0 and vec(k, 9) == v09, (nr, f1, a1, a2, st, st3, vec(k, 9), v09))
    # a new task in front that never sets INT 09h (in K's region, its TX's 09h made something else first): the one
    # it started with, its spawner's; its INT 22h-24h MT's, not the shell's
    k.pc.wr(reg, equ('TX_FVEC'), bytes([0xEF, 0xBE, 0xAD, 0xDE]))
    typ(k, 'mtlaunch /f mtvec.com v 30 vf.txt', 0.6)
    st, a3, rg = tstate(k), vec(k, 9), ent(1, TE_REG)
    waitfile(k, 'VF.TXT', 4.0); k.run_for(0.3)
    line(k, '')
    vf = vread('VF.TXT')
    check('a new task in front that never sets INT 09h (MTVEC V, in K\'s region, the old TX\'s 09h overwritten first): '
          'the one it started with, its spawner\'s, is in the table (%04X:%04X)' % a3, st[1] == 1 and rg == reg
          and a3 == v09 and vf and not k.crashed, (st, hex(rg), hex(reg), a3, v09))
    check('... and its INT 23h and 24h are MT\'s (the kernel\'s ^C, mt_i24\'s prompt), not the shell\'s that started it '
          '(LCMD\'s %04X:%04X): its code would run in this task' % v23, vf and vf[2] == (0x60, Y['int23'])
          and vf[3] == (seg, Y['mt_i24']) and v23[0] not in (0x60, seg), (vf, v23))
    # MTVEC Q in front writes INT 09h, starts V in front and ends: V's (Q's, which it started with) put back
    typ(k, 'mtlaunch /f mtvec.com q 40 vq.txt', 0.4)
    k.run_for(1.4)
    st, a4 = tstate(k), vec(k, 9)
    waitfile(k, 'VQ.TXT', 5.0); k.run_for(0.3)
    line(k, '')
    check('a task in front writing INT 09h, starting another in front and ending (MTVEC Q): the one in front then has '
          'INT 09h as it was at Q\'s spawn (%04X:%04X), not Q\'s, freed' % a4, [e[2] for e in st[0]]
          == ['Executive', 'MTVEC.COM'] and st[1] != 0 and a4 == v09 and A.disk_file(k, 'VQ.TXT')
          and not k.crashed, (st, a4, v09))
    # a task started by a task (MTVEC P, its INT 2Fh hooked, starting MTVEC V): its vectors its spawner's, those
    # pointing into the spawner's region put back when that ends
    typ(k, 'mtlaunch mtvec.com p 30 p.txt', 0.4)
    waitfile(k, 'P.TXT', 6.0); k.run_for(0.3)
    line(k, '')
    pv = vread('P.TXT')
    check('a task started by a task that hooked INT 2Fh and then ended: its INT 2Fh (%s) put back as it was before that '
          'one\'s spawn, not left in its freed region' % (pv and '%04X:%04X' % pv[1]),
          pv and pv[1] == v2f and pv[0] == v1c and tstate(k)[0] == [(0, 1, 'Executive')] and not k.crashed, (pv, v2f, v1c))
    # a program in the Executive's task (MTVEC C, from the prompt) hooking INT 1Ch, starting V, putting it back and
    # ending: V's (C's, which it started with) as the Executive's is now
    typ(k, 'mtvec c 30 c.txt', 0.6)
    waitfile(k, 'C.TXT', 5.0); k.run_for(0.3)
    cv = vread('C.TXT')
    check('a program in the Executive\'s task hooking INT 1Ch, starting a task, putting it back and ending: the task\'s '
          'INT 1Ch (%s, C\'s when it started) as the Executive\'s is after it, not left in C\'s freed memory'
          % (cv and '%04X:%04X' % cv[0]), cv and cv[0] == v1c and tstate(k)[0] == [(0, 1, 'Executive')]
          and not k.crashed, (cv, v1c))
    # a program in the Executive's task writing INT 09h, starting a task in front, putting INT 09h back with AH=25h
    # (behind now) and ending (MTVEC W): the one in front, the table and the Executive's own as before, not W's
    typ(k, 'mtvec w 60 vw.txt', 0.6)
    k.run_for(1.5)
    st, a8 = tstate(k), vec(k, 9)
    fv8, t08 = (k.pc.u16(seg, Y['mt_fv'] + 2), k.pc.u16(seg, Y['mt_fv'])), txfv(0, 0)
    waitfile(k, 'VW.TXT', 6.0); k.run_for(0.3)
    check('a program in the Executive\'s task writing INT 09h, starting a task in front, putting INT 09h back with AH=25h '
          'behind and ending (MTVEC W): the table\'s (%04X:%04X), the front task\'s (mt_fv) and the Executive\'s own as '
          'before, not W\'s, freed' % a8, [e[2] for e in st[0]] == ['Executive', 'MTVEC.COM'] and st[1] != 0
          and a8 == fv8 == t08 == v09 and A.disk_file(k, 'VW.TXT') and not k.crashed, (st, a8, fv8, t08, v09))
    # INT 1Bh hooked and put back with AH=25h by a task behind (as Turbo Pascal's CRT does): its own, in its TX;
    # brought to the front after, the table has INT 1Bh as before, not its old hook
    typ(k, 'mtlaunch mtvec.com b 20 b.txt;mtspin.com 30 bs.txt', 0.4)
    k.run_for(0.3)
    reg = ent(1, TE_REG)
    nr = runs(1, False)
    f2, a5 = txfv(1, 1), vec(k, 0x1B)
    k.run_for(1.0)
    front(k, 1); k.run_for(0.3)
    st, a6 = tstate(k), vec(k, 0x1B)
    waitfile(k, 'B.TXT', 6.0); waitfile(k, 'BS.TXT', 4.0); k.run_for(0.3)
    line(k, '')
    bv = (A.disk_file(k, 'B.TXT') or b'').split()
    bv = (int(bv[1], 16), int(bv[2], 16)) if len(bv) == 3 and bv[0] == b'b' else None
    check('a task behind hooking INT 1Bh with AH=25h: its own, in its TX (%04X:%04X), AH=35h giving it (%s), the table\'s '
          'as it was (%04X:%04X); put back with AH=25h, then brought to the front: the table\'s INT 1Bh as before '
          '(%04X:%04X), not its old hook' % (f2 + (bv and '%04X:%04X' % bv,) + a5 + a6), nr and inreg(f2, reg)
          and bv == f2 and a5 == v1b and st[1] == 1 and a6 == v1b and not k.crashed, (nr, f2, bv, a5, st, a6, v1b))
    # INT 1Bh set with AH=25h and INT 09h written in the table by a task behind (MTVEC X): each its own, in its TX
    # (the one written, not both, taken off at the switch away); brought to the front while hooked, both in the table
    typ(k, 'mtlaunch mtvec.com x 60 x.txt;mtspin.com 80 xs.txt', 0.4)
    k.run_for(0.3)
    reg = ent(1, TE_REG)
    nr = runs(1, False)
    f3 = (txfv(1, 0), txfv(1, 1))
    front(k, 1); k.run_for(0.3)
    st, a7 = tstate(k), (vec(k, 9), vec(k, 0x1B))
    waitfile(k, 'X.TXT', 6.0); waitfile(k, 'XS.TXT', 6.0); k.run_for(0.3)
    line(k, '')
    check('a task behind setting INT 1Bh with AH=25h and writing INT 09h in the table itself (MTVEC X): both its own, '
          'in its TX (%04X:%04X, %04X:%04X); brought to the front while hooked, both in the table; as they were after '
          'it ends' % (f3[0] + f3[1]), nr and inreg(f3[0], reg) and inreg(f3[1], reg) and st[1] == 1 and a7 == f3
          and A.disk_file(k, 'X.TXT') == b'k' and vec(k, 9) == v09 and vec(k, 0x1B) == v1b and not k.crashed,
          (nr, f3, st, a7, hex(reg), vec(k, 9), vec(k, 0x1B)))
    # INT 09h written in the table by a task behind and put back at once with AH=25h (MTVEC Y): put back, the
    # write not taken for its own at the switch away
    typ(k, 'mtlaunch mtvec.com y 30 y.txt;mtspin.com 50 ys.txt', 0.4)
    k.run_for(0.3)
    nr = runs(1, False)
    f4 = txfv(1, 0)
    waitfile(k, 'Y.TXT', 5.0); waitfile(k, 'YS.TXT', 5.0); k.run_for(0.3)
    line(k, '')
    check('a task behind writing INT 09h in the table itself and putting it back at once with AH=25h (MTVEC Y): its '
          'own as before (%04X:%04X), not its handler, at the switch away' % f4, nr and f4 == v09
          and A.disk_file(k, 'Y.TXT') == b'k' and vec(k, 9) == v09 and not k.crashed, (nr, f4, v09))
    # a TSR hooking INT 1Ch in the Executive's task (MTVEC T): not in the tasks started before it, in those after
    typ(k, 'mtlaunch mtvec.com v 40 v1.txt', 0.4); line(k, '')
    typ(k, 'mtvec t', 0.6)
    early = A.disk_file(k, 'V1.TXT')
    r0 = runs(0, False, 1.0)            # (the Executive's own: in its TX while V1 runs, else live)
    t1c = txvec(0, 0x1C) if r0 else vec(k, 0x1C)
    typ(k, 'mtlaunch mtvec.com v 1 v2.txt', 0.4)
    waitfile(k, 'V1.TXT', 6.0); k.run_for(0.3)
    line(k, '')
    r1, r2 = vread('V1.TXT'), vread('V2.TXT')
    check('a TSR hooking INT 1Ch in the Executive\'s task (MTVEC T, %04X:%04X): a task started before it keeps its own '
          '(%s), one started after it has the TSR\'s (%s)' % (t1c + (r1 and '%04X:%04X' % r1[0], r2 and '%04X:%04X' % r2[0])),
          early is None and t1c != v1c and t1c[0] < seg and r1 and r2 and r1[0] == v1c and r2[0] == t1c and r2[1] == v2f
          and not k.crashed, (early, r0, t1c, r1, r2, v1c))

def t_kill():
    print('== tasks ended with MT_KILL, whatever runs in them (M5b)')
    k = boot('mt_kl.img', b'MULTITASK=1\r\n', 88, MTKL, MTK)
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    ext = lambda task: k.pc.u16(seg, Y['mt_tab'] + task * MT_ENT + TE_EXIT)
    B = Baseline(k)
    alone, back, now, m0, s0, e0 = B.alone, B.back, B.now, B.m0, B.s0, B.e0
    kr = {}
    def killed(n, cmd, settle=0.6):     # cmd started (MTLAUNCH's), run a while, then MTLAUNCH /K:n
        sh.run('mtlaunch ' + cmd); line(k, ''); k.run_for(settle)
        st, e1 = tstate(k), ems_used(k)
        reg = k.pc.u16(seg, Y['mt_tab'] + n * MT_ENT + TE_REG)             # (its region, its MCB before it)
        lo, hi = (reg * 16, (reg + k.pc.u16(reg - 1, 3)) * 16) if reg else (0, 0)
        ka, ea, ph, ran, prev = seg * 16 + Y['mt_kill'], seg * 16 + Y['mt_end'], [0], [], k.pc.watch
        def w(a):                       # (code run in its region from MT_KILL to its MT_END: none, if it ends
            if prev: prev(a)            #  where it would have gone on)
            if a == ka and ph[0] == 0: ph[0] = 1
            elif a == ea and ph[0] == 1: ph[0] = 2
            elif ph[0] == 1 and lo <= a < hi and len(ran) < 4: ran.append(hex(a))
        k.pc.watch = w
        o = sh.run('mtlaunch /k:%d' % n); line(k, ''); k.run_for(0.5)
        k.pc.watch = prev
        kr['ran'] = ran if ph[0] == 2 else ['no MT_END', ph[0]]
        return st, e1, o
    ks = lambda n: b'k' * n
    # behind, waiting for a line inside INT 21h (kbd_get), a file open and an EMS page taken
    st, e1, o = killed(1, 'mtkill.com f 1500 kf.txt')
    check('a task behind waiting for a line (MTKILL F: in kbd_get, inside INT 21h), its file open, an EMS page its own: '
          'ended, none of its code run after the call (a watch on its region), its file closed at its size (1,500 bytes: 3 '
          'clusters), the page given back, its region freed, the files and EMS as before; its exit code 0100h (as ^C)',
          (1, TS_WAITK, 'MTKILL.COM') in st[0] and e1 > e0 and 'error' not in o and not kr['ran']
          and A.disk_file(k, 'KF.TXT') == ks(1500) and ext(1) == 0x100 and back(), (st, e1, o, kr, now(), hex(ext(1))))
    # behind, computing (no INT 21h call): switched from at the tick, outside INT 21h
    st, e1, o = killed(1, 'mtkill.com s 200 ks.txt')
    check('... computing behind (MTKILL S, never calling INT 21h: on its own stack, outside the kernel): the same',
          (1, 1, 'MTKILL.COM') in st[0] and e1 > e0 and A.disk_file(k, 'KS.TXT') == ks(200) and ext(1) == 0x100
          and not kr['ran'] and back(), (st, e1, o, kr, now()))
    # a program with a child: both end with the task
    st, e1, o = killed(1, 'mtkill.com c 100 kc.txt')
    check('... running a child (MTKILL C, its child F waiting for a line): both ended with the task, the child\'s file '
          'closed at its size, memory, files and EMS as before', (1, TS_WAITK, 'MTKILL.COM') in st[0] and e1 > e0
          and A.disk_file(k, 'KC.TXT') == ks(100) and ext(1) == 0x100 and not kr['ran'] and back(), (st, e1, o, kr, now()))
    # computing behind with an INT 21h call on each count: switched from on INT 21h's way out (mt_exit)
    xs, prev = [], k.pc.watch
    def w(a):
        if prev: prev(a)
        if a == seg * 16 + Y['mt_exit.c'] and k.pc.rd(seg, Y['mt_cur'], 1)[0] == 1: xs.append(1)
    k.pc.watch = w
    st, e1, o = killed(1, 'mtspin.com 30000 kv.txt d')
    k.pc.watch = prev
    check('... computing behind with an INT 21h call on each count (MTSPIN D: nearly all its time inside INT 21h, so '
          'its turns end on the way out, mt_exit: reached %d times with one due): ended, as before' % len(xs),
          (1, 1, 'MTSPIN.COM') in st[0] and xs and A.disk_file(k, 'KV.TXT') is None and not kr['ran'] and back(),
          (st, len(xs), kr, now()))
    # its own task
    xp, prev = [], k.pc.watch
    def w(a):
        if prev: prev(a)
        if a in (seg * 16 + Y['mt_kill.df'], seg * 16 + Y['mt_kill.o']): xp.append(hex(a))
        if a == seg * 16 + Y['mt_kdie']: xp.append('kdie')
    k.pc.watch = w
    sh.run('mtlaunch mtkill.com x 30 kx.txt'); line(k, ''); k.run_for(1.0)
    k.pc.watch = prev
    check('a task ending itself (MTKILL X: AL=14h with its own number): at once, no return (no "!"; mt_kdie reached '
          'from mt_kill, neither its put-off path nor its path for another task taken), its file closed at its size, as '
          'before', xp == ['kdie'] and A.disk_file(k, 'KX.TXT') == ks(30) and ext(1) == 0x100 and back(), (xp, now()))
    # never run yet
    hits, prev = [], k.pc.watch
    def w(a):
        if prev: prev(a)
        if a == seg * 16 + Y['mt_first']: hits.append(1)
    k.pc.watch = w
    o = sh.run('mtlaunch mtspin.com 100 kn.txt;/k:1'); line(k, ''); k.run_for(0.8)
    k.pc.watch = prev
    check('a task ended before it ever ran (MTLAUNCH starting it, then /K:1): its stub never run (mt_first not reached), '
          'ended, as before', 'task 1' in o and 'error' not in o and not hits and A.disk_file(k, 'KN.TXT') is None
          and back(), (o, hits, now()))
    # frozen behind: it runs all the same, to end
    sh.run('mtlaunch /f /z mtkill.com f 40 kz.txt'); k.run_for(0.4)
    front(k, 0); line(k, ''); k.run_for(0.4)
    st, e1 = tstate(k), ems_used(k)
    o = sh.run('mtlaunch /k:1'); line(k, ''); k.run_for(0.6)
    check('a task frozen behind (MTLAUNCH /Z, in front first, then behind): ended all the same (mt_pick takes it), its '
          'file closed at its size', (1, TS_WAITK, 'MTKILL.COM') in st[0] and st[1] == 0
          and A.disk_file(k, 'KZ.TXT') == ks(40) and back(), (st, o, now()))
    # in front, ended by a task behind: the Executive's task in front again, its screen back
    sh.run('mtlaunch /f mtkill.com f 50 kq.txt;mtkill.com k 1 kk.txt')
    pre = tstate(k)
    k.run_for(1.5)
    st, scr = tstate(k), k.pc.text_screen()
    line(k, ''); k.run_for(0.6)
    kk = A.disk_file(k, 'KK.TXT')
    check('the task in front (MTKILL F, waiting for a line) ended by one behind (MTKILL K 1): the Executive\'s task in '
          'front again, its screen back (MTLAUNCH waits>), the killer told CF clear', pre[1] == 1
          and (1, TS_WAITK, 'MTKILL.COM') in pre[0] and st[1] == 0 and 'MTLAUNCH waits>' in scr
          and kk is not None and kk.startswith(b'0 ') and A.disk_file(k, 'KQ.TXT') == ks(50) and back(), (st, kk, now()))
    # waiting in the BIOS (its own INT 16h read: mt_wkey) and waiting to be in front (a graphics mode behind: mt_wfront)
    st, e1, o = killed(1, 'mtkey.com r kr.txt')
    r1 = kr['ran']
    st2, e2, o2 = killed(1, 'mtmode.com 04 km.txt')
    check('a task waiting in its own INT 16h read behind (MTKEY R), and one waiting to be in front (MTMODE 04, a graphics '
          'mode asked for behind): each ended, none of its code run after the call, as before',
          (1, TS_WAITK, 'MTKEY.COM') in st[0] and (1, 3, 'MTMODE.COM') in st2[0] and not r1 and not kr['ran']
          and A.disk_file(k, 'KR.TXT') is None and A.disk_file(k, 'KM.TXT') is None and back(),
          (st, st2, r1, kr, now()))
    # twice (the second too late); and what can't be ended
    sh.run('mtlaunch mtkill.com f 10 kd.txt'); line(k, ''); k.run_for(0.6)
    o = sh.run('mtlaunch /k:1 /k:1'); line(k, ''); k.run_for(0.6)
    o0 = sh.run('mtlaunch /k:0'); line(k, '')
    o3 = sh.run('mtlaunch /k:3'); line(k, '')
    o9 = sh.run('mtlaunch /k:9'); line(k, '')
    check('ended twice in one command (/K:1 /K:1): the first ends it on that call\'s way out (its turn comes at once), so '
          'the second finds none: error 1; the Executive\'s task: error 5; a task number with no task (3) or past 7 (9): '
          'error 1',
          o.count('MTLAUNCH: error 1') == 1 and A.disk_file(k, 'KD.TXT') == ks(10) and 'MTLAUNCH: error 5' in o0
          and 'MTLAUNCH: error 1' in o3 and 'MTLAUNCH: error 1' in o9 and back(), (o, o0, o3, o9, now()))
    # CODE-Tab coming in after mt_hot looked, inside the front task's DOS key status call, before the BIOS's AH=01h
    # would look (and drop it, as a key AH=01h can't give): MT drops what that would itself, CODE-Tab taken (M5b)
    typ(k, 'mtlaunch /f mtkey.com d d9.txt;mtline.com l9.txt', 0.2)
    for i in range(60):
        st = tstate(k)
        if st[1] == 1 and (2, TS_WAITK, 'MTLINE.COM') in st[0]: break
        k.run_for(0.05)
    top, hot, prev = seg * 16 + Y['mt_i16.nh'], [], k.pc.watch
    def w(a):                                   # (just back from .top's CALL mt_hot, at .nh: the key put in the buffer)
        if prev: prev(a)
        if a == top and not hot and k.pc.rd(seg, Y['mt_cur'], 1)[0] == 1 == k.pc.rd(seg, Y['mt_front'], 1)[0] \
                and k.pc.r('ss') == 0x60:
            hot.append(k.pc.us); k.pc.keys.append(HOT); k.pc.kbd_sync()
    k.pc.watch = w
    k.run_for(0.3)
    k.pc.watch = prev
    st = tstate(k)
    line(k, 'nine')
    d9 = waittwo(k, 'D9.TXT')
    line(k, '')
    check('CODE-Tab typed just after MT looked for it, inside the front task\'s DOS key status call (MTKEY D), before the '
          'BIOS\'s AH=01h: not lost (MT drops what that would, CODE-Tab taken): MTLINE, behind, comes to the front and '
          'gets its line; MTKEY D sees no key', hot and st[1] == 2 and A.disk_file(k, 'L9.TXT') == b'nine'
          and d9 == (0, 0) and back(), (hot, st, A.disk_file(k, 'L9.TXT'), d9, now()))
    # the kernel's INT 24h running outside INT 21h (as C:'s INT 25h/26h raise it: mt_crit set here by the test): the
    # task it runs in not switched from at the tick, though another is ready; switched again once it is over
    typ(k, 'mtlaunch mtspin.com 40 p1.txt;mtspin.com 40 p2.txt', 0.3)
    cur = lambda: k.pc.rd(seg, Y['mt_cur'], 1)[0]
    for i in range(400):
        if cur() == 1: break
        k.run_for(0.002)
    k.pc.wr(seg, Y['mt_crit'], b'\x01')
    seen = set()
    for i in range(30):
        k.run_for(0.01); seen.add(cur())
    k.pc.wr(seg, Y['mt_crit'], b'\x00')
    after = set()
    for i in range(30):
        k.run_for(0.01); after.add(cur())
    waitfile(k, 'P1.TXT', 6.0); waitfile(k, 'P2.TXT', 6.0); line(k, ''); k.run_for(0.3)
    check('the kernel\'s INT 24h running outside INT 21h (as C:\'s INT 25h/26h raise it; mt_crit set by the test) in a '
          'task computing behind: not switched from at the tick for 0.3 s, though another is ready (%s); once it is '
          'over, switched again (%s)' % (sorted(seen), sorted(after)), seen == {1} and 2 in after
          and spun(k, 'P1.TXT') > 0 and spun(k, 'P2.TXT') > 0 and back(), (seen, after, now()))
    # inside an interrupt's handler: the mouse's event handler (a serial mouse here), the timer's INT 1Ch
    k = boot('mt_kl2.img', b'MULTITASK=1\r\n', 88, MTKL, mouse=True)
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    B = Baseline(k)
    alone, back, now, m0, s0, e0 = B.alone, B.back, B.now, B.m0, B.s0, B.e0
    busy = lambda: k.pc.rd(k.useg, Y['m33_busy'], 1)[0]
    cur = lambda: k.pc.rd(seg, Y['mt_cur'], 1)[0]
    def both():                         # two tasks computing: both get turns (the tick still switches)
        typ(k, 'mtlaunch mtspin.com 30 q1.txt;mtspin.com 30 q2.txt', 0.3)
        seen = set()
        for i in range(60):
            k.run_for(0.01); seen.add(cur())
        waitfile(k, 'Q1.TXT', 6.0); waitfile(k, 'Q2.TXT', 6.0); line(k, ''); k.run_for(0.3)
        return seen
    def mouse(mode, more=''):
        typ(k, 'mtlaunch /f mtkill.com %s 0 x%s' % (mode, more), 0.3)
        b = []                          # (moved while task 1 runs: the front task's handler is called in whichever
        for i in range(40):             #  task the mouse's interrupt finds, and does its part only in its own)
            for j in range(200):
                if cur() == 1: break
                k.run_for(0.001)
            else:
                continue
            k.pc.mouse_move(8, 0); k.run_for(0.01); b.append(busy())
            if 1 in b: break
        k.run_for(1.2)
        st = tstate(k)
        line(k, ''); k.run_for(0.3)
        return b, st
    b, st = mouse('m', ';mtkill.com k 1 km.txt')
    seen = both()
    check('a task ended while its mouse event handler waits for a key (MTKILL M, by MTKILL K behind): the driver\'s '
          'm33_busy cleared as it ends (each program\'s end told to the UI: ui_progend), so the tick still switches: '
          'two tasks computing after it both get turns (%s)' % sorted(seen), 1 in b and A.disk_file(k, 'KM.TXT')
          and A.disk_file(k, 'KM.TXT').startswith(b'0 ') and busy() == 0 and {1, 2} <= seen
          and merged(mcbs(k)) == m0 and sft_used(k) == s0 and ems_used(k) == e0 and not k.crashed, (b, st, seen, busy()))
    zb, prev = [], k.pc.watch           # (m33_busy as the task ends: 1 if it ended inside its handler)
    def w(a):
        if prev: prev(a)
        if a == seg * 16 + Y['mt_end'] and len(zb) < 4: zb.append(busy())
    k.pc.watch = w
    b, st = mouse('z')
    k.pc.watch = prev
    seen = both()
    check('... and one whose handler ends its own task (MTKILL Z, computing for ever else): not there and then (the '
          'handler\'s call isn\'t over: m33_busy %s as it ends), but at its next safe point; m33_busy clear, both '
          'computing tasks after it get turns (%s)' % (zb, sorted(seen)),
          zb and not any(zb) and [e[0] for e in st[0]] == [0] and busy() == 0 and {1, 2} <= seen
          and merged(mcbs(k)) == m0 and ems_used(k) == e0 and not k.crashed, (b, st, seen, busy()))
    kd, prev = [], k.pc.watch           # (mt_kdie reached: the handler's kill, put off, then done)
    def w(a):
        if prev: prev(a)
        if a == seg * 16 + Y['mt_kdie']: kd.append(cur())
        if a == seg * 16 + Y['mt_kill.df']: kd.append('df')
    k.pc.watch = w
    marked = lambda: k.pc.rd(seg, Y['mt_tab'] + MT_ENT + TE_KILL, 1)[0]     # (task 1's)
    typ(k, 'mtlaunch /f mtkill.com r 0 x;mtspin.com 400 rq.txt', 0.3)
    for i in range(40):                 # (moves only until its handler's kill is put off: MTSPIN still computing
        for j in range(200):            #  after, so it isn't ended for want of another task to run)
            if cur() == 1: break
            k.run_for(0.001)
        else:
            continue
        k.pc.mouse_move(8, 0); k.run_for(0.01)
        if marked(): break
    mk = marked()
    k.run_for(1.0)
    k.pc.watch = prev
    st = tstate(k)
    sh.run('mtlaunch /k:2'); line(k, ''); k.run_for(0.5)
    check('... and one that, its handler\'s kill put off, goes on to read a key in front (MTKILL R, MTSPIN computing '
          'behind): ended when switched from, not left waiting for the key (mt_switch makes it ready); no key typed',
          mk and kd == ['df', 1] and [e[2] for e in st[0]] == ['Executive', 'MTSPIN.COM'] and busy() == 0
          and merged(mcbs(k)) == m0 and ems_used(k) == e0 and not k.crashed, (mk, kd, st, busy()))
    isr, prev = [], k.pc.watch
    def w(a):
        if prev: prev(a)
        if a == seg * 16 + Y['mt_end'] and len(isr) < 4: isr.append(k.pc.isr)
    k.pc.watch = w
    typ(k, 'mtlaunch mtkill.com t 0 x;mtspin.com 40 tq.txt', 0.3); k.run_for(1.0)
    st = tstate(k)
    waitfile(k, 'TQ.TXT', 6.0)
    k.pc.watch = prev
    line(k, ''); k.run_for(0.3)
    seen = both()
    check('a task whose INT 1Ch handler ends its own task (MTKILL T: the timer\'s interrupt in service), with another '
          'computing (MTSPIN, so it is switched from, its return changed by mt_switch): it ends when next run, with no '
          'interrupt in service (%s at mt_end), not inside the handler; the tick goes on (%s)' % (isr, sorted(seen)),
          isr and not any(isr) and 'MTKILL.COM' not in [e[2] for e in st[0]] and (2, 1, 'MTSPIN.COM') in st[0]
          and spun(k, 'TQ.TXT') > 0 and {1, 2} <= seen
          and merged(mcbs(k)) == m0 and ems_used(k) == e0 and not k.crashed, (isr, st, seen))

def t_park():
    print('== tasks parked in EMS and brought back (M6)')
    k = boot('mt_pk.img', b'MULTITASK=1\r\n', 128, MTKL, MTV)      # (2 MB of EMS: room for two parked)
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    ent = lambda task, o: k.pc.u16(seg, Y['mt_tab'] + task * MT_ENT + o)
    st = lambda task: k.pc.rd(seg, Y['mt_tab'] + task * MT_ENT, 1)[0]
    cur = lambda: k.pc.rd(seg, Y['mt_cur'], 1)[0]
    B = Baseline(k)
    alone, back, now, m0, s0, e0 = B.alone, B.back, B.now, B.m0, B.s0, B.e0
    def region(task):                   # its region: segment, paragraphs (its MCB's), and its bytes
        r = ent(task, TE_REG)
        n = k.pc.u16(r - 1, 3)
        return r, n, bytes(k.pc.rd(r, 0, n * 16))
    def mt(cmd):                        # MTLAUNCH's options, from the prompt
        o = sh.run('mtlaunch ' + cmd); line(k, ''); k.run_for(0.3)
        return o
    def owners(task):                   # the owners in its own arena (its PSPs)
        s, out = k.pc.u16(ent(task, TE_TX), equ('V_MCB')), set()
        for i in range(50):
            t, o, n = k.pc.rd(s, 0, 1)[0], k.pc.u16(s, 1), k.pc.u16(s, 3)
            if o: out.add(o)
            if t != ord('M'): break
            s += n + 1
        return out
    pages = lambda n: (n + 1023) // 1024
    ks = lambda n: b'k' * n
    # behind, waiting for a line inside INT 21h (its kernel stack's slice in its TX): parked, back, and on
    mt('mtkill.com f 1500 kp.txt')
    s1, (r1, n1, b1), e1 = st(1), region(1), ems_used(k)
    o = mt('/p:1')
    s2, own, e2 = st(1), k.pc.u16(r1 - 1, 1), ems_used(k)
    k.pc.wr(r1, 0, b'\xcc' * (n1 * 16))  # (the freed place scribbled on: only the copy back puts it right)
    o2 = mt('/u:1')
    s3, (r3, n3, b3), e3 = st(1), region(1), ems_used(k)
    if b3 == b1:                        # (not run if its bytes are wrong: ended, so the checks after go on)
        front(k, 1); line(k, 'go'); k.run_for(0.5)
    else:
        mt('/k:1')
    check('a task behind waiting for a line (MTKILL F, inside INT 21h) parked: its state 5, its region (%d paragraphs) '
          'freed, %d EMS pages taken; brought back (its place scribbled on meanwhile): at the same place, every byte as '
          'it was, its state again, the pages '
          'given back; then in front, the line: it goes on ("!" written), and ends' % (n1, pages(n1)),
          s1 == TS_WAITK and 'error' not in o + o2 and s2 == 5 and own == 0 and e2 == e1 + pages(n1)
          and s3 == TS_WAITK and (r3, n3) == (r1, n1) and b3 == b1 and e3 == e1
          and A.disk_file(k, 'KP.TXT') == ks(1500) + b'!' and back(), (s1, s2, own, e1, e2, s3, r1, r3, n1, n3, b1 == b3,
                                                                        o, o2, now()))
    # computing (switched from at the tick, outside INT 21h): parked, it doesn't run; back, it goes on
    typ(k, 'mtlaunch mtkill.com s 10 ps.txt', 0.3); line(k, ''); k.run_for(0.3)
    sr = st(1)
    typ(k, 'mtlaunch /p:1', 0.3); line(k, ''); k.run_for(0.2)       # (typed: the shell's run waits for an idle
    s1, ran = st(1), set()                                          #  machine)
    for i in range(300):
        k.run_for(0.01); ran.add(cur())
    s2 = st(1)
    typ(k, 'mtlaunch /u:1', 0.3); line(k, '')
    s3, ran2 = st(1), set()
    for i in range(100):
        k.run_for(0.01); ran2.add(cur())
    typ(k, 'mtlaunch /k:1', 0.3); line(k, ''); k.run_for(0.5)
    check('a task computing (MTKILL S, switched from at the tick) parked: not run for 3 s (tasks run %s); back, it '
          'runs again (%s); ended from there, its file closed at its size' % (sorted(ran), sorted(ran2)),
          sr == 1 and s1 == s2 == 5 and 1 not in ran and s3 == 1 and 1 in ran2
          and A.disk_file(k, 'PS.TXT') == ks(10) and back(), (sr, s1, s2, s3, ran, ran2, now()))
    # what can't be parked, or brought back
    mt('mtkill.com f 10 kq.txt')
    pq = owners(1)                      # (its PSPs: those of the task in its place later, the same)
    o0, o1, o3, o4 = mt('/p:0'), mt('/u:1'), mt('/p:3'), mt('/u:3')
    s1 = st(1)
    mt('/p:1')
    og = mt('/g:1')
    sw, prev = [], k.pc.watch           # (what mt_swnow is asked for: CODE-Tab's choice)
    def w(a):
        if prev: prev(a)
        if a == seg * 16 + Y['mt_swnow']: sw.append(k.pc.rd(seg, Y['mt_swreq'], 1)[0])
    k.pc.watch = w
    hot(k)
    k.pc.watch = prev
    f1 = k.pc.rd(seg, Y['mt_front'], 1)[0]
    front(k, 1); line(k, ''); k.run_for(0.3)    # (asked for anyway, as a request made before it was parked)
    f2, rq = k.pc.rd(seg, Y['mt_front'], 1)[0], k.pc.rd(seg, Y['mt_swreq'], 1)[0]
    o5 = mt('/p:1')
    check('refused: the Executive\'s task parked (error 5); one not parked brought back, no such task parked or brought '
          'back (error 1); a parked one: not to the front (MT_FRONT: error 5; CODE-Tab passes it by%s; asked for all the '
          'same, mt_swnow passes it by: the front %d, the request %02Xh), not parked again (error 5)'
          % (', no switch asked for' if set(sw) <= {255} else ', asking for %s' % sw, f2, rq), 'MTLAUNCH: error 5' in o0 and 'MTLAUNCH: error 1' in o1
          and 'MTLAUNCH: error 1' in o3 and 'MTLAUNCH: error 1' in o4 and s1 == TS_WAITK and st(1) == 5
          and 'MTLAUNCH: error 5' in og and 1 not in sw and f1 == 0 and f2 == 0 and rq == 0xFF and st(1) == 5
          and 'MTLAUNCH: error 5' in o5 and not k.crashed, (o0, o1, o3, o4, og, sw, f1, f2, rq, o5, now()))
    # in the way: a task whose region took the parked one's place; pinned (a vector into it), it can't be parked
    sp1 = ent(1, TE_REG), ent(1, TE_PSZ)        # (the parked one's region: TE_REG, TE_PSZ)
    eb = ems_used(k)                    # (the parked one's own EMS page among them: the programs in its place
                                        #  below have their PSPs at its program's segment)
    mt('mtvec.com i 0 x')               # (task 2: INT 62h its own, then a line)
    k.run_for(0.3)
    r2, n2 = ent(2, TE_REG), k.pc.u16(ent(2, TE_REG) - 1, 3)
    lap = r2 - 1 < sp1[0] + sp1[1] and sp1[0] - 1 < r2 + n2
    v62 = vec(k, 0x62)
    o1, o2 = mt('/u:1'), mt('/p:2')
    check('a task in the parked one\'s place (MTVEC I, %04X: %d paragraphs; the parked one at %04X), INT 62h its own: '
          'it can\'t be parked (error 5), and the parked one doesn\'t come back (error 8); both as they were'
          % (r2, n2, sp1[0]), lap and r2 <= v62[0] < r2 + n2 and 'MTLAUNCH: error 8' in o1 and 'MTLAUNCH: error 5' in o2 and st(1) == 5
          and st(2) == TS_WAITK and vec(k, 0x62) == v62 and not k.crashed, (r2, n2, sp1, v62, o1, o2, now()))
    front(k, 2); line(k, ''); k.run_for(0.5)                        # (I ends, INT 62h put back)
    mt('mtkill.com f 10 kc.txt')        # (task 2 again, in the same place: its PSPs at the same segments)
    r2, n2 = ent(2, TE_REG), k.pc.u16(ent(2, TE_REG) - 1, 3)
    lap = r2 - 1 < sp1[0] + sp1[1] and sp1[0] - 1 < r2 + n2
    pc = owners(2)
    o1 = mt('/u:1')
    sa, sb, ra = st(1), st(2), ent(1, TE_REG)
    o2 = mt('/u:2')
    sc, sd = st(1), st(2)
    front(k, 2); line(k, ''); k.run_for(0.5)                        # (it ends, as a program does, the other parked)
    se, ec = st(2), ems_used(k)
    o3 = mt('/u:1')
    front(k, 1); line(k, ''); k.run_for(0.5)                        # (and that one, through its own INT 22h)
    check('a task in the parked one\'s place, not pinned (MTKILL F; the parked one\'s own vectors, into that place, '
          'don\'t pin it): parked on the way, the parked one back (%s); then the other way round (%s); it ends meanwhile, '
          'the parked one\'s own vectors in its TX left as they were, and its EMS page its own (%d pages in use, as '
          'when it was parked: the programs run in its place, their PSPs at its program\'s segment, freed only their '
          'own); that one back, it ends too, '
          'through its own INT 22h; memory, files and EMS as before (the pages given back)' % ((sa, sb), (sc, sd), ec),
          lap and pq and pc == pq and 'error' not in o1 + o2 + o3 and (sa, sb) == (TS_WAITK, 5) and ra == sp1[0] and (sc, sd) == (5, TS_WAITK)
          and se == 0 and ec == eb and A.disk_file(k, 'KQ.TXT') == ks(10) + b'!'
          and A.disk_file(k, 'KC.TXT') == ks(10) + b'!' and back(), (lap, pq, pc, o1, o2, o3, sa, sb, sc, sd, se, eb, ec,
                                                                     now()))
    # asked from a task behind, whose own INT 09h (in its TX: the table's is the front one's) points into the one
    # to be parked (the test writes it there as MT_PARK looks): pinned all the same
    mt('mtkill.com f 10 kg.txt')
    r1 = ent(1, TE_REG)
    pk, prev = [], k.pc.watch
    def w(a):
        if prev: prev(a)
        if a == seg * 16 + Y['mt_pinned'] and cur() == 2 and not pk:
            k.pc.wr(ent(2, TE_TX), equ('TX_FVEC'), struct.pack('<HH', 0x100, r1 + 0x40))
            pk.append(1)
    k.pc.watch = w
    typ(k, 'mtlaunch mtlaunch.com /p:1', 0.4); line(k, ''); k.run_for(0.5)
    k.pc.watch = prev
    s1 = st(1)
    o1 = mt('/k:2 /k:1')
    check('asked from a task behind (MTLAUNCH /P:1, task 2) whose own INT 09h, in its TX, points into task 1: task 1 '
          'pinned all the same, not parked (state %d)' % s1, pk and s1 == TS_WAITK and 'error' not in o1
          and A.disk_file(k, 'KG.TXT') == ks(10) and back(), (pk, s1, o1, now()))
    # not enough EMS: a task taking every free page (MTKILL E)
    mt('mtkill.com f 10 ke.txt;mtkill.com e 0 x')
    k.run_for(0.5)
    s1, r1b, e1 = st(1), region(1), ems_used(k)
    o1 = mt('/p:1')
    s2, r2b, e2 = st(1), region(1), ems_used(k)
    front(k, 2); line(k, ''); k.run_for(0.5)                        # (E ends: its pages back)
    o2 = mt('/p:1')
    o3 = mt('/k:1')
    check('every EMS page taken (MTKILL E): parking fails (error 8), the task as it was (its state, its region, every '
          'byte); once they are back, it parks; ended from there', 'MTLAUNCH: error 8' in o1 and s2 == s1 == TS_WAITK
          and r2b == r1b and e2 == e1 and 'error' not in o2 + o3 and A.disk_file(k, 'KE.TXT') == ks(10) and back(),
          (o1, s1, s2, e1, e2, o2, o3, now()))
    # a parked task's own vectors put right while it is parked (its TX in EMS: mt_vrep through window 0): MTVEC L
    # hooks INT 2Fh and starts MTVEC V, which is parked; L ends, its hook in V's TX put back; V back, it reads it
    v2f, v1c = vec(k, 0x2F), vec(k, 0x1C)
    typ(k, 'mtlaunch mtvec.com l 90 pl.txt', 0.4); line(k, ''); k.run_for(0.3)
    s2a = st(2)
    oa = mt('/p:1')                     # (L pinned: V's own INT 2Fh is L's hook)
    o1 = mt('/p:2')
    ob = mt('/p:1')                     # (and with V parked: its TX in EMS)
    front(k, 1); line(k, ''); k.run_for(0.5)                        # (L ends, INT 2Fh not put back)
    s1, s2 = st(1), st(2)
    o2 = mt('/u:2')
    waitfile(k, 'PL.TXT', 8.0); k.run_for(0.3)
    r = (A.disk_file(k, 'PL.TXT') or b'').split()
    pv = [(int(r[n], 16), int(r[n + 1], 16)) for n in range(0, 8, 2)] if len(r) == 8 else None
    check('a task (MTVEC V) whose INT 2Fh is its spawner\'s hook (MTVEC L): the spawner can\'t be parked (error 5), V '
          'there or parked (its TX in EMS); V parked, the spawner ends, and V\'s own INT 2Fh, in its TX in EMS, is put '
          'back as it was before (%s), not left in the freed region' % (pv and '%04X:%04X' % pv[1]),
          s2a == 1 and 'MTLAUNCH: error 5' in oa and 'MTLAUNCH: error 5' in ob and 'error' not in o1 + o2 and s1 == 0
          and s2 == 5 and pv and pv[1] == v2f and pv[0] == v1c and back(),
          (s2a, s1, s2, oa, o1, ob, o2, pv, v2f, now()))
    # pinned by another task's copy of the table at its spawn (TX_GSN) alone: MTVEC I twice; the second, started
    # while INT 62h was the first's, takes INT 62h for itself
    v62 = vec(k, 0x62)
    mt('mtvec.com i 0 x')
    mt('mtvec.com i 0 x')
    r1, r2, va = ent(1, TE_REG), ent(2, TE_REG), vec(k, 0x62)
    gv = struct.unpack('<HH', bytes(k.pc.rd(ent(2, TE_TX), equ('TX_GSN') + 0x62 * 4, 4)))
    o1 = mt('/p:1')
    s1 = st(1)
    front(k, 2); line(k, ''); k.run_for(0.5)                        # (each ends, INT 62h put back)
    front(k, 1); line(k, ''); k.run_for(0.5)
    check('a task (MTVEC I) whose INT 62h is only in another\'s copy of the table at its spawn (TX_GSN; the table\'s '
          'is the other\'s own): pinned (error 5); both end, INT 62h as before', r2 <= va[0] < r2 + k.pc.u16(r2 - 1, 3)
          and r1 <= gv[1] < r1 + k.pc.u16(r1 - 1, 3) and 'MTLAUNCH: error 5' in o1 and s1 == TS_WAITK
          and vec(k, 0x62) == v62 and back(), (r1, r2, va, gv, o1, s1, now()))
    # X35: a parked task whose pages are gone (FREEH frees MT's handle; or its size changed) can't come
    # back (error 8), but MT_KILL ends it: its programs' EMS (incl. a 47h context), its wake, its screen's
    # and MT's handles if still MT's freed, the shadow off, MT_EXIT ^C's.  Shared: a screen handle given
    # to another program is left alone
    hrec = lambda h: (k.pc.rd(0x60, Y['ems_h'] + h * 4, 2), k.pc.u16(0x60, Y['ems_h'] + h * 4 + 2))
    for how in ('freed', 'resized', 'shared'):
        e0, mg0 = ems_used(k), merged(mcbs(k))
        B.e0 = e0                                   # (back() from here on: as e0)
        mt('mtkill.com f 10 k%s.txt' % how[0])
        o1 = mt('/p:1')
        ph, hs = (k.pc.rd(seg, Y['mt_tab'] + MT_ENT + o, 1)[0] for o in (TE_PH, TE_SH))
        sz = ent(1, TE_PSZ)
        hid = [h for h in range(1, 32) if hrec(h)[0][0] != 0xFF and hrec(h)[1] == 0xFFFF
               and k.pc.rd(seg, Y['mt_hold'] + h, 1)[0] == 1]
        if how == 'freed':
            sh.run('freeh %d' % ph); line(k, ''); k.run_for(0.3)
            sv0 = k.pc.rd(0x60, Y['ems_sv'], 1)[0]
            k.pc.wr(0x60, Y['ems_sv'], bytes([hid[0] if hid else 0xFF, 0, 0, 0, 0]))
            k.pc.wr(seg, Y['mt_wkt'], b'\1'); k.pc.wr(seg, Y['mt_wkp'], struct.pack('<H', 0x1234))
            k.pc.wr(seg, Y['mt_shd'], b'\1')
        else:
            k.pc.wr(seg, Y['mt_tab'] + MT_ENT + TE_PSZ, struct.pack('<H', sz + 1024))
        if how == 'shared':
            k.pc.wr(0x60, Y['ems_h'] + hs * 4 + 2, struct.pack('<H', 0x1234))
        o2 = mt('/u:1')
        sds, efc, prev = [], [], k.pc.watch             # (mt_shd as MT_KILL is done: the shell may draw after;
        def w(a):                                       #  and the records ems_free is given: (handle, open))
            if prev: prev(a)
            if a == seg * 16 + Y['mt_kill.ok']: sds.append(shd(k))
            if a == 0x600 + Y['ems_free']:
                efc.append(((k.pc.r('si') - Y['ems_h']) // 4, k.pc.rd(0x60, k.pc.r('si'), 1)[0] != 0xFF))
        k.pc.watch = w
        o3 = mt('/k:1')
        k.pc.watch = prev
        s1, e1, xr = st(1), ems_used(k), re.search(r'exit: (\w\w) (\w\w) (\w{4}) (\w\w)', mt('/x:1'))
        more, ok = '', True
        if how == 'freed':
            sv1, wk, sd = k.pc.rd(0x60, Y['ems_sv'], 1)[0], k.pc.rd(seg, Y['mt_wkt'], 1)[0], sds[:1] == [0]
            more = ('; its program\'s handle (%s) freed though a context was saved for it (the slot %02Xh, then %02Xh); '
                    'MT_WAKE\'s task none now (%02Xh); the shadow off, alone (mt_shd %s as MT_KILL is done); MT\'s '
                    'handle, closed by FREEH (its owner still MT\'s), not freed again (ems_free given %s)'
                    % (hid, sv0, sv1, wk, sds, efc))
            ok = sv0 == 0xFF and hid and hrec(hid[0])[0][0] == 0xFF and sv1 == 0xFF and wk == 0xFF and sd \
                and efc and all(o for h, o in efc) and ph not in [h for h, o in efc]
        if how == 'shared':
            r = hrec(hs)
            more = '; the screen\'s handle %d, another program\'s now, kept (%s, owner %04X)' % (hs, r[0].hex(), r[1])
            ok = r[0][0] != 0xFF and r[0][1] == 2 and r[1] == 0x1234
            e1 -= 2
            sh.run('freeh %d' % hs); line(k, ''); k.run_for(0.3)
        check('a parked task, MT\'s handle (%d) %s meanwhile: not back (error 8); MT_KILL ends it (state %d, MT_EXIT %s), '
              'every EMS page it had given back (%d in use, %d before it), its memory as before%s'
              % (ph, how, s1, xr and xr.groups(), e1, e0, more), 'error' not in o1 and ph and 'MTLAUNCH: error 8' in o2
              and 'error' not in o3 and s1 == 0 and e1 == e0 and alone() and merged(mcbs(k)) == mg0 and xr
              and xr.group(1) == '00' and xr.group(3) == '0100' and xr.group(2) == xr.group(4) and ok
              and ems_used(k) == e0 and not k.crashed, (how, ph, hs, hid, sz, o1, o2, o3, s1, e0, e1, xr and xr.groups(),
                                                         ems_used(k), more, now()))

MTGR = os.path.join(HERE, 'MTGROW.COM')

def t_grow():
    print('== a task\'s region grows on demand (T5a)')
    k = boot('mt_grow.img', b'MULTITASK=1\r\n', 88, MTGR)
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    k.pc.wr(0, 0x62 * 4, struct.pack('<HH', 0x5678, 0x1234))   # (INT 62h: a known vector, in each spawn's TX_GSN)
    m0, s0, e0, v62 = merged(mcbs(k)), sft_used(k), ems_used(k), vec(k, 0x62)
    au = Audit(k)
    TXP, STP, GRES = equ('TX_PARAS'), equ('ST_PARAS'), equ('MT_GRES')
    ent = lambda n, f: k.pc.u16(seg, task_ent(k, n) + f)
    rsz = lambda reg: k.pc.u16(reg - 1, 3)
    def below(reg):                     # the block just below a region: (its MCB, owner, paragraphs); none: zeros
        return next(((s, own, sz) for s, t, own, sz, nm in mcbs(k) if s + sz + 1 == reg - 1), (0, 0, 0))
    def chain(reg):                     # the task's own chain, from its region's start (grown: its first block)
        out, s = [], reg
        while len(out) < 40:
            t, own, sz, nm = chr(k.pc.rd(s, 0, 1)[0]), k.pc.u16(s, 1), k.pc.u16(s, 3), bytes(k.pc.rd(s, 8, 2))
            out.append((s, t, own, sz, nm))
            if t != 'M': break
            s += sz + 1
        return out
    def lines_of(f): return [x for x in (A.disk_file(k, f) or b'').decode('latin-1').split('\r\n') if x]
    def g(key, f='G.TXT', t=0.6):       # a key to MTGROW (in front): the line it wrote ('' if none came)
        n0 = len(lines_of(f))
        k.key(key, settle=False); k.run_for(t)
        l = lines_of(f)
        return l[-1] if len(l) > n0 else ''
    def gp(w, f='G.TXT'):               # "p" and w's 4 hex digits: 48h of w paragraphs
        n0 = len(lines_of(f))
        for c in 'p%04X' % w: k.key(c, settle=False); k.run_for(0.1)
        k.run_for(1.0)
        l = lines_of(f)
        return l[-1] if len(l) > n0 else ''
    def emsr(ph, para, n):              # n bytes from paragraph para of EMS handle ph's pages
        st, out, off = k.pc.rd(0x60, Y['ems_h'] + ph * 4, 1)[0], b'', para * 16
        while len(out) < n:
            o, c = off % 0x4000, min(n - len(out), 0x4000 - off % 0x4000)
            out += k.pc.ems_read(k.pc.ems_page(k.pc.rd(0x60, Y['ems_ltab'] + st + off // 0x4000, 1)[0]), o, c)
            off += c
        return out
    def ans(l):                         # "A aaaa c bbbb" -> (AX, CF, BX)
        p = l.split()
        return (int(p[1], 16), int(p[2]), int(p[3], 16)) if len(p) == 4 else (None, None, None)
    # in task 0 (LCMD's own prompt, full screen): nothing grows, a 48h that fails fails (CF), as with the switch off
    sh.run('mtgrow.com k 0 z.txt')
    a0 = merged(mcbs(k))
    lz, lzh = gp(0xE000, 'Z.TXT'), g('h', 'Z.TXT')
    a1 = merged(mcbs(k))
    lzq = g('q', 'Z.TXT')
    check('MTGROW K in task 0 (LCMD\'s own prompt): 48h E000h paragraphs fails, CF set and AX 8 (%s); 48h FFFFh too (%s); '
          'the arena as it was; "q" (%s)' % (lz, lzh, lzq), ans(lz)[:2] == (8, 1) and ans(lzh)[:2] == (8, 1) and a1 == a0
          and lzq == 'Q', (lz, lzh, show(a0), show(a1)))
    # MTSPIN first (T1: the top region; it computes beside), then MTGROW S with 16 KB (T2, below it)
    typ(k, 'start /w mtspin.com 60000 sp.txt', 0.5)
    sh.run('start /m:16 mtgrow.com s 600 g.txt')
    n = 2
    st = tstate(k)
    reg0, tx0, stp = ent(n, TE_REG), ent(n, TE_TX), ent(n, TE_PSP)
    rs0, b0, stub0 = rsz(reg0), below(reg0), bytes(k.pc.rd(stp, 0, STP * 16))
    l1 = g('2')                         # 32 KB: its 16 KB arena has no room
    a1, reg1 = ans(l1), ent(n, TE_REG)
    b1, c1, d1 = below(reg1), chain(reg1), reg0 - reg1
    check('MTGROW (16 KB, shrunk to its size) asks 48h for 32 KB: served (%s) at its region\'s new start; the region\'s '
          'MCB %Xh lower (802h: the block, its MCB and the TX\'s, in steps of 4 KB) and as much bigger, still "T2"; the '
          'block below %Xh smaller; TE_TX and the stub kept' % (l1, d1, b0[2] - b1[2]),
          st[0][-1][0] == n and a1[:2] == (reg1 + 1, 0) and d1 == 0x900 and rsz(reg1) == rs0 + d1
          and b1[2] == b0[2] - d1 and ent(n, TE_TX) == tx0 and bytes(k.pc.rd(stp, 0, STP * 16)) == stub0
          and k.pc.u16(reg1 - 1, 1) == 8 and bytes(k.pc.rd(reg1 - 1, 8, 2)) == b'T2', (st, l1, hex(reg0), hex(reg1), b0, b1))
    owner = c1[0][2]
    check('... the task\'s own chain: the block (800h, MTGROW\'s), the rest free (FDh), then the TX, stub and environment '
          'a block of the system\'s ("TX", owner 8) up to its old arena, the last block ending at the region\'s end',
          c1[0][1:4] == ('M', owner, 0x800) and owner not in (0, 8) and c1[1][1:4] == ('M', 0, 0xFD)
          and c1[2][0] == tx0 - 1 and c1[2][2] == 8 and c1[2][4] == b'TX' and c1[2][3] > TXP + STP
          and c1[-1][1] == 'Z' and c1[-1][0] + c1[-1][3] + 1 == reg1 + rsz(reg1), c1)
    l2 = g('2')                         # again: the chain's first block MTGROW's
    a2, reg2 = ans(l2), ent(n, TE_REG)
    c2 = chain(reg2)
    check('48h 32 KB again (the first block a program\'s): a free block in front of it, %Xh lower (801h, rounded), the '
          'block served from it (%s)' % (reg1 - reg2, l2), a2[:2] == (reg2 + 1, 0) and reg1 - reg2 == 0x900
          and c2[0][1:4] == ('M', owner, 0x800) and c2[1][1:4] == ('M', 0, 0xFE) and c2[2][0] == reg1, (l2, c2[:4]))
    l3 = g('f')
    l4 = g('3')                         # 48 KB: the first block free (8FFh, merged), too small
    a4, reg3 = ans(l4), ent(n, TE_REG)
    c3 = chain(reg3)
    check('49h of that block (%s), then 48h 48 KB: the free first block grown by what it lacks (C00h - 8FFh, in steps '
          'of 4 KB: %Xh lower) and served (%s)' % (l3, reg2 - reg3, l4), l3 == 'F 0' and a4[:2] == (reg3 + 1, 0)
          and reg2 - reg3 == 0x400 and c3[0][1:4] == ('M', owner, 0xC00), (l3, l4, c3[:3]))
    sw, prev, swa = [0], k.pc.watch, seg * 16 + Y['mt_switch']
    def w(a):
        if prev: prev(a)
        if a == swa and k.pc.rd(seg, Y['mt_cur'], 1)[0] == n: sw[0] += 1
    k.pc.watch = w
    lr = g('r', t=1.5)                  # code run in that block (grown), switched from meanwhile (MTSPIN beside)
    k.pc.watch = prev
    check('a routine copied into that block runs there 9 ticks (%s), the task switched from there and back meanwhile '
          '(%d times)' % (lr, sw[0]), lr.startswith('R ') and int(lr[2:], 16) > 0 and sw[0] >= 2, (lr, sw[0]))
    big = max((sz for s, t, own, sz, nm in chain(ent(n, TE_REG)) if own == 0), default=0)
    lh = g('h')
    check('48h FFFFh (a question, not a need): not grown, AX 8 and BX the arena\'s own largest (%s, %Xh)' % (lh, big),
          ans(lh) == (8, 1, big) and ent(n, TE_REG) == reg3, (lh, hex(big)))
    ms = []                             # the arena full (the largest block taken till none is left); then
    for _ in range(8):                  #  EXEC: the child grows it
        ms.append(g('m'))
        if ans(ms[-1])[1] or ans(ms[-1])[2] == 0: break
    regm = ent(n, TE_REG)
    lx = g('x', t=2.0)
    lines = [x for x in A.disk_file(k, 'G.TXT').decode('latin-1').split('\r\n') if x]
    cp = lines[-2].split() if len(lines) > 1 else []
    cp = (int(cp[1], 16), int(cp[2], 16)) if len(cp) == 3 and cp[0] == 'C' else (0, 0)
    check('every free block taken (%s), then EXEC of a child (MTGROW C): its region grown for it (%Xh lower), it ran '
          '(its line "%s": a .COM grown for its whole segment, 64 KB, under the TX at %04X: T5d) and ended (%s)'
          % (ms, regm - ent(n, TE_REG), lines[-2] if len(lines) > 1 else '', tx0, lx), ans(ms[-1])[:2] == (8, 1)
          and cp[1] >= 0x1000 and cp[0] + cp[1] < tx0 and lines[-1][:3] == 'X 0' and ent(n, TE_REG) < regm,
          (ms, lines[-3:], hex(regm), hex(ent(n, TE_REG))))
    ls = g('s')                         # a hole of 20h paragraphs: room for the environment, not the program
    for _ in range(8):
        if ans(g('m'))[1]: break
    le = g('e')
    rege = ent(n, TE_REG)
    lx2 = g('x', t=2.0)
    lines = [x for x in A.disk_file(k, 'G.TXT').decode('latin-1').split('\r\n') if x]
    check('a hole of 20h paragraphs left (%s, %s), the rest taken, then EXEC again: its environment there, its program '
          'not: the region grown for the program (%Xh lower; mt_largest), it ran (%s) and ended (%s)'
          % (ls, le, rege - ent(n, TE_REG), lines[-2] if len(lines) > 1 else '', lx2), ans(ls)[1] == 0 and le == 'E 0'
          and lines[-2][:2] == 'C ' and int(lines[-2].split()[2], 16) >= 0x1000
          and lines[-1][:3] == 'X 0' and ent(n, TE_REG) < rege, (ls, le, lines[-3:]))
    for _ in range(8):                  # (the arena full again: the children's room free)
        if ans(g('m'))[1]: break
    # boxed in: a task started now has its region just below this one
    front(k, 0)
    sh.run('start /w mtline.com bx.txt')
    front(k, n)
    regb = ent(n, TE_REG)
    lb = g('1')
    regb1 = ent(n, TE_REG)
    front(k, 3); line(k, ''); front(k, n)
    lb2 = g('1')
    check('a task started below it (MTLINE, task 3): 48h 16 KB refused, nothing changed (%s); it ends, its place free: '
          'served (%s)' % (lb, lb2), ans(lb)[:2] == (8, 1) and regb1 == regb and ans(lb2)[1] == 0
          and ent(n, TE_REG) < regb, (lb, lb2, hex(regb), hex(regb1)))
    # MT_GRES: the block below keeps room for a task of 64 KB and a .RUN
    refused = None
    for _ in range(8):
        regr = ent(n, TE_REG)
        l9 = g('9')                     # 144 KB at a time, till refused
        if ans(l9)[1]: refused = (l9, regr == ent(n, TE_REG), below(regr)[2]); break
    fb = below(ent(n, TE_REG))[2]
    ln = gp(max(fb - GRES, 1))          # (with the free block's MCB, one paragraph more than it can give)
    check('48h 144 KB, again and again, till refused (%s): the block below it (%Xh) can\'t give that and keep MT_GRES '
          '(%Xh); %Xh paragraphs, which leave MT_GRES but one paragraph: refused too, nothing changed (%s)'
          % (refused, fb, GRES, fb - GRES, ln), refused and refused[1] and GRES <= fb < 0x2401 + GRES and ans(ln)[:2] == (8, 1)
          and below(ent(n, TE_REG))[2] == fb, (refused, hex(fb), ln))
    # parked and back: its TX at its pages' start (mt_pmap), the region back byte for byte
    front(k, 0)
    regp, szp = ent(n, TE_REG), rsz(ent(n, TE_REG))
    img = bytes(k.pc.rd(regp, 0, szp * 16))
    txb = bytes(k.pc.rd(tx0, 0, TXP * 16))
    op = sh.run('park 2 && echo PARKED')
    ph, ga = k.pc.rd(seg, task_ent(k, n) + TE_PH, 1)[0], tx0 - regp
    inems = bool(ph) and emsr(ph, 0, TXP * 16) == txb and emsr(ph, 0, (szp - ga) * 16) == img[ga * 16:] \
        and emsr(ph, szp - ga, ga * 16) == img[:ga * 16]
    free = k.pc.u16(regp - 1, 1) == 0
    k.pc.wr(regp, 0, b'\x5A' * (szp * 16))       # (its place, free meanwhile, written over)
    ou = sh.run('unpark 2 && echo BACK')
    check('PARK 2 (grown by %Xh): its pages hold its TX first, then the rest to its end, then what is below its TX '
          '(%s); its place free (%s); UNPARK 2: in its place, every byte back' % (reg0 - regp, inems, free),
          'PARKED' in op and inems and free and 'BACK' in ou and ent(n, TE_REG) == regp
          and bytes(k.pc.rd(regp, 0, szp * 16)) == img, (op[-200:], inems, free, ou[-200:]))
    # a hook left in a grown block: KILL puts it back (mt_vfix: the TX's table)
    front(k, n)
    lv = g('v')
    hooked = vec(k, 0x62)
    front(k, 0)
    ok = sh.run('kill 2 && echo KILLED')
    check('INT 62h hooked into a grown block (%s, %04X:%04X), then KILL 2: put back as it was, its region freed'
          % (lv, hooked[0], hooked[1]), lv == 'V' and ent(n, TE_REG) <= hooked[0] < ent(n, TE_TX) and 'KILLED' in ok
          and vec(k, 0x62) == v62 and b'T2' not in [b[4] for b in mcbs(k) if b[2]], (lv, hooked, ok[-200:], vec(k, 0x62)))
    # K: a .COM that keeps all it was given, then a 48h of exactly what the block below can give but MT_GRES
    sh.run('start /m:16 mtgrow.com k 0 k.txt')
    n2 = tstate(k)[0][-1][0]
    r0 = ent(n2, TE_REG)
    fk = below(r0)[2]
    w = fk - GRES - 2                   # (the first growth: the block, its MCB and the TX's)
    lk = gp(w, 'K.TXT')
    r1 = ent(n2, TE_REG)
    lq = g('q', 'K.TXT')
    check('MTGROW K (keeps its whole arena) asks 48h for exactly what the block below it (%Xh) can give and keep MT_GRES '
          '(%Xh, %s): its region %Xh lower (not rounded: that wouldn\'t fit), MT_GRES left; "q": it ends, the grown region '
          'freed' % (fk, w, lk, r0 - r1), ans(lk)[:2] == (r1 + 1, 0) and r0 - r1 == w + 2 and below(r1)[2] == GRES
          and lq == 'Q' and b'T%d' % n2 not in [b[4] for b in mcbs(k) if b[2]], (lk, lq, hex(r0), hex(r1), hex(fk)))
    front(k, 0)
    sh.run('kill 1')
    k.run_for(1.0)
    check('... MTSPIN killed too: memory, files and EMS as before', tstate(k)[0] == [(0, 1, 'Executive')]
          and merged(mcbs(k)) == m0 and sft_used(k) == s0 and ems_used(k) == e0, (tstate(k), show(mcbs(k))))
    check('... every switch at a safe point (the audit)', not au.bad(), au.bad()[:3])

def t_lcmd():
    print('== LCMD\'s START, FG, KILL, PARK, UNPARK and WAIT (M7a)')
    cmds = ('start mtline.com x.txt', 'fg 1', 'kill 1', 'park 1', 'unpark 1', 'wait 1')
    k = boot('mt_lc0.img', None)
    sh = Shell(k)
    outs, lv = [], []
    for c in cmds:                      # (VER first: ERRORLEVEL 0 before each)
        sh.run('ver')
        outs.append(sh.run(c + ' || echo FAILED'))
        lv.append(sh.run('if errorlevel 1 echo LEVEL1'))
    check('off: each says multitasking is off and fails, ERRORLEVEL 1',
          all(OFF_MSG in x and 'FAILED' in x for x in outs) and all('LEVEL1' in x for x in lv), (outs, lv))
    sb = os.path.join(A.OUT, 'SB.BAT'); open(sb, 'wb').write(b'@echo off\r\nmtline.com %1\r\n')
    tw = os.path.join(A.OUT, 'TW.BAT')
    open(tw, 'wb').write(b'@echo off\r\nstart /w mtline.com tw.txt\r\nwait %TASK%\r\nif errorlevel 6 echo LEVEL6\r\n'
                         b'if errorlevel 7 echo LEVEL7\r\necho DONE\r\n')
    sg = os.path.join(A.OUT, 'SG.BAT'); open(sg, 'wb').write(b'@echo off\r\nstart /w mtline.com sg.txt\r\necho BATDONE\r\n')
    sp = os.path.join(A.OUT, 'SP.BAT'); open(sp, 'wb').write(b'@echo off\r\nmtline.com sp.txt | upper > spo.txt\r\n')
    cl = os.path.join(GOS, 'claude', 'CLAUDE.COM')
    huge = mz(os.path.join(A.OUT, 'HUGE.EXE'), 0xA000, 0xA000)     # (more than any free block: no region grows to it)
    k = boot('mt_lc.img', b'MULTITASK=1\r\n', 88, 'SB.BAT=' + sb, 'TW.BAT=' + tw, 'SG.BAT=' + sg, 'SP.BAT=' + sp, cl, huge,
             os.path.join(HERE, 'UPPER.COM'))
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    B = Baseline(k)
    m0, s0, e0, back = B.m0, B.s0, B.e0, B.back
    def xc(n):                          # MT_EXIT's answer (MTLAUNCH /X:n), then MTLAUNCH's line
        o = sh.run('mtlaunch /x:%d' % n); line(k, '')
        return re.search(r'exit: (\w\w) (\w\w) (\w{4}) (\w\w)', o)
    # START (in front): the task in front, MTLINE's prompt there; its line, it ends, LCMD's prompt again
    sh.run('start mtline.com sf.txt')
    st1 = tstate(k)
    line(k, 'front')
    st2 = tstate(k)
    o = sh.run('set')
    check('START: the program a task, in front (%s); its line typed to it, it ends; TASK=1 in the environment' % (st1,),
          st1[:2] == ([(0, 1, 'Executive'), (1, 2, 'MTLINE.COM')], 1) and st2[0] == [(0, 1, 'Executive')]
          and A.disk_file(k, 'SF.TXT') == b'front' and 'TASK=1' in o and back(), (st1, st2, o))
    # START /W, TASKS, FG by name, WAIT: ERRORLEVEL the exit code
    o1 = sh.run('start /w mtline.com sw.txt && echo STARTED')
    o2 = sh.run('tasks')
    x1 = xc(1)
    typ(k, 'wait mtline', 0.5)          # (typed: WAIT doesn't come back till the task ends)
    w1 = tstate(k)
    front(k, 1)
    line(k, '=7')
    k.run_for(0.5)
    o3 = sh.run('if errorlevel 7 echo LEVEL7')
    o4 = sh.run('if errorlevel 8 echo LEVEL8')
    x2 = xc(1)
    check('START /W: behind (TASKS: "1  MTLINE.COM"; MT_EXIT: state 2, the second started there, the first\'s code 0); '
          'WAIT MTLINE waits (the task waiting for a key); it ends with 7: ERRORLEVEL 7 (MT_EXIT: free, its exit code 7, '
          'the one started last)', 'STARTED' in o1 and re.search(r'^\s*1\s+MTLINE\.COM\s*$', o2, re.M)
          and x1 and x1.groups() == ('02', '02', '0000', '01') and w1[0][1] == (1, 2, 'MTLINE.COM')
          and 'LEVEL7' in o3 and 'LEVEL8' not in o4 and x2 and x2.groups() == ('00', '02', '0007', '02')
          and A.disk_file(k, 'SW.TXT') == b'=7' and back(), (o1, o2, x1 and x1.groups(), w1, o3, o4, x2 and x2.groups()))
    # the number used again: MT_EXIT keeps the last one's code till the new one ends; FG; WAIT of an ended one at once
    sh.run('start /w mtline.com sr.txt')
    x3 = xc(1)
    o4 = sh.run('fg 1 && echo FRONTED')
    f1 = tstate(k)[1]
    line(k, '=3'); k.run_for(0.3)
    s1 = tstate(k)[0]
    o5 = sh.run('wait 1 && echo W0')
    o6 = sh.run('if errorlevel 3 echo LEVEL3')
    check('the same number again: MT_EXIT says started three times, the last one\'s code (7) kept till it ends; FG 1: in '
          'front, its line typed to it; WAIT 1 after it ended (with 3): at once, ERRORLEVEL 3, failed',
          x3 and x3.groups() == ('02', '03', '0007', '02') and f1 == 1 and s1 == [(0, 1, 'Executive')]
          and A.disk_file(k, 'SR.TXT') == b'=3' and 'W0' not in o5 and 'LEVEL3' in o6 and back(),
          (x3 and x3.groups(), o4, f1, s1, o5, o6))
    # WAIT for a parked task ended by ^C (the task goes on); WAIT whose task's number was given to another, which
    # ended too: lost
    sh.run('start /w mtline.com sx.txt')
    sh.run('park 1')
    typ(k, 'wait 1', 0.5)
    sp = tstate(k)[0]
    k.key('x', settle=False); k.key(0x2E03); k.run_for(0.5)            # (a key ahead of the ^C)
    kb = '>x' not in k.pc.text_screen()                                 # (the keys up to it taken, not the prompt's)
    o1 = sh.run('echo BACKATPROMPT')
    sh.run('unpark 1')
    s1 = tstate(k)[0]
    g = k.pc.rd(seg, Y['mt_tab'] + MT_ENT + TE_GEN, 1)[0]
    typ(k, 'wait 1', 0.5)
    k.pc.wr(seg, Y['mt_tab'] + MT_ENT + TE_GEN, bytes([g + 1, g + 1]))     # (as if ended, another started and ended)
    k.run_for(0.5)
    o2 = k.pc.text_screen()
    o3 = sh.run('if errorlevel 1 echo LEVEL1')
    sh.run('kill 1')
    check('WAIT for a parked task (%s) ended by ^C, a key typed ahead of it: back at the prompt, the task still there, '
          'brought back (%s); WAIT '
          'whose task\'s number was used again and ended meanwhile: "Its exit code is lost", ERRORLEVEL 1' % (sp, s1),
          sp[1:] == [(1, 5, 'MTLINE.COM')] and kb and 'BACKATPROMPT' in o1 and s1[1:] == [(1, 2, 'MTLINE.COM')]
          and 'Its exit code is lost' in o2 and 'LEVEL1' in o3 and back(), (sp, kb, o1, s1, o2, o3))
    # keys typed while WAIT waits are left for the prompt (only a ^C is read)
    typ(k, 'cls', 0.2)
    typ(k, 'start /w mtspin.com 90 ta.txt', 0.3)    # (typed: the shell's run waits for an idle machine)
    typ(k, 'wait 1', 0.3)
    k.key('echo TYPED', settle=False)
    sa = tstate(k)[0]
    k.run_for(0.5)
    o0 = k.pc.text_screen()
    k.run_for(6.0)
    s1 = tstate(k)[0]
    k.key(ktest.ENTER); k.run_for(0.5)
    o = k.pc.text_screen()
    check('keys typed while WAIT waits (for MTSPIN, which ends by itself: %s, then %s) are left for the prompt: ECHO '
          'TYPED runs after it' % (sa, s1), sa[1:] == [(1, 1, 'MTSPIN.COM')] and 'TYPED' not in o0
          and s1 == [(0, 1, 'Executive')] and re.search(r'^TYPED\s*$', o, re.M) and back(), (sa, o0, s1, o))
    # PARK, UNPARK, KILL by number and name; WAIT of a killed one: AL 0, but failed
    sh.run('start /w mtline.com sp.txt')
    o1 = sh.run('park 1 && echo PARKED')
    o2 = sh.run('tasks')
    s1 = tstate(k)[0]
    o3 = sh.run('unpark mtline.com && echo BACK')
    s2 = tstate(k)[0]
    o4 = sh.run('kill MtLine && echo KILLED')
    o5 = sh.run('wait 1 || echo WFAILED')
    o6 = sh.run('if errorlevel 1 echo LEVEL1')
    check('PARK 1: parked (TASKS: "(parked)"); UNPARK MTLINE.COM: back; KILL MtLine: ended; WAIT 1: failed, '
          'ERRORLEVEL 0 (^C\'s or KILL\'s 0100h)', 'PARKED' in o1 and re.search(r'1\s+MTLINE\.COM \(parked\)', o2)
          and s1[1] == (1, 5, 'MTLINE.COM') and 'BACK' in o3 and s2[1] == (1, 2, 'MTLINE.COM') and 'KILLED' in o4
          and 'WFAILED' in o5 and 'LEVEL1' not in o6 and back(), (o1, o2, s1, o3, s2, o4, o5, o6))
    # what fails
    sh.run('start /w mtline.com se.txt')
    want = {'fg 7': 'No such task', 'fg nosuch': 'No such task', 'fg mtl': 'No such task', 'kill 257': 'No such task',
            'fg': 'Required parameter missing', 'kill 0': 'Not possible for that task',
            'wait 0': 'Not possible for that task', 'wait 5': 'No such task', 'park 0': 'Not possible for that task',
            'unpark 1': 'No such task', 'start nosuch.com': 'Bad command or file name', 'start': 'Required parameter missing',
            'start /q mtline.com': 'Syntax error', 'start /m:1024 mtline.com': 'Syntax error',
            'start /m:x mtline.com': 'Syntax error', 'start /w /m:1000 mtline.com': 'Not enough memory or EMS',
            'wait 2': 'No such task'}
    outs = {}
    for c in want:                      # (VER first: ERRORLEVEL 0 before each)
        sh.run('ver')
        outs[c] = sh.run(c + ' || echo FAILED') + sh.run('if errorlevel 1 echo LEVEL1')
    o = sh.run('set')
    sh.run('kill 1')
    check('refused, with its message, failing (ERRORLEVEL 1): %s; and TASK= gone after a START that failed'
          % '; '.join('%s: %s' % kv for kv in want.items()),
          all(want[c] in outs[c] and 'FAILED' in outs[c] and 'LEVEL1' in outs[c] for c in want)
          and 'TASK=' not in o and back(), (outs, o))
    # eight tasks at most: the eighth START says so
    for i in range(7):
        sh.run('start /w /m:1 mtline.com t%d.txt' % i)
    o1 = sh.run('start /w /m:1 mtline.com t7.txt || echo FAILED')
    n = len(tstate(k)[0])
    o2 = sh.run('kill 1 && kill 2 && kill 3 && kill 4 && kill 5 && kill 6 && kill 7 && echo KILLED')
    check('seven tasks and the Executive\'s: the next START says "Too many tasks" and fails',
          n == 8 and 'Too many tasks' in o1 and 'FAILED' in o1 and 'KILLED' in o2 and back(), (n, o1, o2))
    # a program that can't be started (HUGE.EXE in 1 KB, asking 640 KB: not even a region that grows, T5a, has room
    # for it): the task ends at once, its code FF08h; WAIT says so
    sh.run('set task=1')                # (both environments copied alike: the next one in the same place)
    o1 = sh.run('start /w /m:1 huge.exe')
    k.run_for(0.5)
    x1 = xc(1)
    o2 = sh.run('wait 1 || echo FAILED')
    o3 = sh.run('if errorlevel 8 echo LEVEL8')
    check('START /M:1 HUGE.EXE: started, but its program can\'t be (EXEC: no memory): MT_EXIT\'s code FF08h; WAIT says it '
          'couldn\'t be started, fails, ERRORLEVEL 8', 'error' not in o1.lower() and x1 and x1.group(3) == 'FF08'
          and 'could not be started' in o2 and 'FAILED' in o2 and 'LEVEL8' in o3 and back(),
          (o1, x1 and x1.groups(), o2, o3))
    # one that can, in the same place (the same size): not taken for one that couldn't (its stub's ST_FAIL cleared)
    rf = k.pc.u16(seg, Y['mt_tab'] + MT_ENT + TE_REG)
    sh.run('start /w /m:1 mtline.com sm.txt')
    rm, s1 = k.pc.u16(seg, Y['mt_tab'] + MT_ENT + TE_REG), tstate(k)[0]
    front(k, 1); line(k, '=2'); k.run_for(0.3)
    o2 = sh.run('wait 1 || echo FAILED')
    o3 = sh.run('if errorlevel 2 echo LEVEL2')
    check('START /M:1 MTLINE.COM, in the same place (%04X): it runs (%s), ends with 2; WAIT: ERRORLEVEL 2, not "could not '
          'be started"' % (rm, s1), rm == rf and s1[1:] == [(1, 2, 'MTLINE.COM')] and 'could not' not in o2
          and 'FAILED' in o2 and 'LEVEL2' in o3 and A.disk_file(k, 'SM.TXT') == b'=2' and back(), (rf, rm, s1, o2, o3))
    # a batch file: through COMSPEC (LCMD /C), its arguments too
    sh.run('start /w sb.bat sb.txt')
    s1 = tstate(k)[0]
    front(k, 1); line(k, '=4'); k.run_for(0.5)
    o = sh.run('wait 1 || echo WF')
    o2 = sh.run('if errorlevel 4 echo LEVEL4')
    check('START /W SB.BAT SB.TXT: LCMD.COM /C SB.BAT SB.TXT as the task (%s); its MTLINE (%%1: SB.TXT) gets its line '
          '(=4), the batch file ends, so '
          'does the task: WAIT\'s ERRORLEVEL LCMD /C\'s, its last command\'s (4)' % (s1,), s1[1:] == [(1, 2, 'LCMD.COM')]
          and A.disk_file(k, 'SB.TXT') == b'=4' and 'WF' in o and 'LEVEL4' in o2 and back(), (s1, o, o2))
    # a task started from a batch file doesn't keep it open (LCMD opens it not inherited)
    o1 = sh.run('sg.bat')
    s1 = tstate(k)[0]
    o2 = sh.run('del sg.bat && echo DELETED')
    o3 = sh.run('kill 1 && echo KILLED')
    check('a batch file that STARTs a task (%s): once it is done, it can be deleted while the task runs' % (s1,),
          'BATDONE' in o1 and s1[1:] == [(1, 2, 'MTLINE.COM')] and 'DELETED' in o2 and 'KILLED' in o3 and back(),
          (o1, s1, o2, o3))
    # in a batch file: START, then WAIT %TASK% and IF ERRORLEVEL
    typ(k, 'cls', 0.3)
    typ(k, 'tw.bat', 0.8)               # (typed: it waits)
    s1 = tstate(k)[0]
    front(k, 1); line(k, '=6'); k.run_for(0.8)
    o = k.pc.text_screen()
    check('a batch file: START /W MTLINE.COM, WAIT %%TASK%% (%s), IF ERRORLEVEL: its code (6)' % (s1,),
          s1[1:] == [(1, 2, 'MTLINE.COM')] and 'LEVEL6' in o and 'LEVEL7' not in o and 'DONE' in o and back(), (s1, o))
    # /B and /D: the task's flags (TE_VF), and how much memory /M gives
    sh.run('start /w /b mtline.com sb1.txt')
    sh.run('start /w /d /m:32 mtline.com sb2.txt')
    o1 = sh.run('set')
    vf = [k.pc.rd(seg, Y['mt_tab'] + t * MT_ENT + TE_VF, 1)[0] for t in (1, 2)]
    r1, r2 = (k.pc.u16(seg, Y['mt_tab'] + t * MT_ENT + TE_REG) for t in (1, 2))
    s1, s2 = k.pc.u16(r1 - 1, 3), k.pc.u16(r2 - 1, 3)
    sh.run('start /w /d mtspin.com 200 fz.txt')     # (a task computing, never run behind: frozen)
    o2 = sh.run('tasks')
    o = sh.run('kill 1 && kill 2 && kill 3 && echo KILLED')
    check('START /B: SPF_BG; START /D: SPF_FREEZE (TE_VF %s); /M:32: 2048 paragraphs for its programs, 32 KB less than '
          'the default 64 KB (regions of %d and %d paragraphs); TASK=2 after the second; START /D MTSPIN: TASKS says '
          '"(frozen)"' % (vf, s2, s1), vf == [2, 4] and s1 - s2 == 2048 and 'TASK=2' in o1
          and re.search(r'3\s+MTSPIN\.COM \(frozen\)', o2) and 'KILLED' in o and back(), (vf, s1, s2, o1, o2, o))
    # a pipe with multitasking on (its files named by LCMD's task: pipe_name asks MT_LIST; no TEMP here: the root), none left
    o = sh.run('echo hello there | upper | upper')
    left = [n for n in ('PIPEA1.$$0', 'PIPEA2.$$0', 'PIPEA1.$$$', 'PIPEA2.$$$') if A.disk_file(k, n) is not None]
    check('a pipe (ECHO | UPPER | UPPER) with multitasking on: HELLO THERE, its files gone', re.search(r'^HELLO THERE\s*$', o, re.M)
          and not left and back(), (o, left))
    # ... in a task behind (LCMD /C SP.BAT as task 1): its files named by that task, not the one in front
    sh.run('start /w sp.bat')
    n1 = [n for n in ('PIPEA1.$$1', 'PIPEA1.$$0', 'PIPEA1.$$$') if A.disk_file(k, n) is not None]
    front(k, 1); line(k, '=0'); k.run_for(0.5)
    sh.run('wait 1')
    left = [n for n in ('PIPEA1.$$1', 'PIPEA2.$$1') if A.disk_file(k, n) is not None]
    check('... a pipe in a task behind (START /W SP.BAT: MTLINE | UPPER > SPO.TXT), MTLINE waiting: its file \\PIPEA1.$$1 '
          '(task 1\'s; %s); then UPPER\'s output, the files gone' % (n1,), n1 == ['PIPEA1.$$1']
          and b'MTLINE>' in (A.disk_file(k, 'SPO.TXT') or b'') and not left and back(), (n1, A.disk_file(k, 'SPO.TXT'), left))
    # CLAUDE /U refuses while other tasks run
    o1 = sh.run('claude /r')
    sh.run('start /w mtline.com sc.txt')
    o2 = sh.run('claude /u')
    o3 = sh.run('if errorlevel 3 echo LEVEL3')
    sh.run('kill 1')
    o4 = sh.run('claude /u')
    o5 = sh.run('if errorlevel 1 echo LEVEL1')
    check('CLAUDE /U with another task: refused (exit code 3); with none, taken out',
          'can\'t be taken out while other tasks run' in o2 and 'LEVEL3' in o3 and 'no longer resident' in o4
          and 'LEVEL1' not in o5 and back(), (o1, o2, o3, o4, o5))

def mz(path, minal, maxal):
    """A small .EXE (t_exerel's header in test_kernel.py): it waits for a key (AH=08h), then ends with 0.  Its
    image is one paragraph; its header asks for at least minal paragraphs past it, at most maxal."""
    code = bytes([0xB4, 0x08, 0xCD, 0x21, 0xB8, 0x00, 0x4C, 0xCD, 0x21]).ljust(16, b'\x90')
    size = 32 + len(code)
    hdr = struct.pack('<2s13H', b'MZ', size % 512, (size + 511) // 512, 0, 2, minal, maxal, 1, 0x100, 0, 0, 0, 0x1C, 0)
    open(path, 'wb').write(hdr.ljust(32, b'\0') + code)
    return path

# MKFILE.COM: makes MADE.TXT, then waits for a key and ends (the Executive's list must show the file after)
MKFILE = bytes([0xB4, 0x3C, 0x31, 0xC9, 0xBA, 0x18, 0x01, 0xCD, 0x21, 0x89, 0xC3, 0xB4, 0x3E, 0xCD, 0x21,
                0xB4, 0x08, 0xCD, 0x21, 0xB8, 0x00, 0x4C, 0xCD, 0x21]) + b'MADE.TXT\0'

def ret(k, name, wait=1.0):
    """Return on a program in the Executive (with multitasking on: it starts as a task, in front: with no
    TERM.RUN on these floppies, by T2's fallback, mt_uwin's mt_swreq)."""
    k.select(name); k.key(ktest.ENTER, settle=False); k.run_for(wait)

def t_exec():
    print('== the Executive: Return starts a program as a task (M7b)')
    # off: Return runs it and waits, as before; no entry
    k = boot('mt_ex0.img', None)
    k.select('MTLINE.COM'); k.key(ktest.ENTER, settle=False); k.pc.run_until(lambda: k.pc.mode() != 0x40, 5)
    k.run_for(0.5)
    line(k, '=4'); k.settle()
    b0 = k.band()
    rp0 = bytes(k.rd('run_prog', 5))
    check('off: run_prog not patched (its CMP BYTE [ex_mtw],0), ex_mtw 1 while the Executive waits (as it adds its own '
          '1); Return on MTLINE.COM runs it and waits: "MTLINE.COM ended, exit code 4"',
          rp0 == b'\x80\x3e' + struct.pack('<H', k.Y['ex_mtw']) + b'\x00'
          and k.rd('ex_mtw', 1) == b'\x01' and b0[:1] == ['MTLINE.COM ended, exit code 4'], (rp0.hex(), k.rd('ex_mtw', 1), b0))
    mk = os.path.join(A.OUT, 'MKFILE.COM'); open(mk, 'wb').write(MKFILE)
    xs, xa, xb, xm, xl = (mz(os.path.join(A.OUT, n + '.EXE'), mi, ma) for n, mi, ma in
                          (('EXS', 0x20, 0x300), ('EXA', 0x20, 0xFFFF), ('EXB', 0xA000, 0xFFFF), ('EXM', 0x20, 0x20),
                           ('EXL', 0x40, 0x10)))
    k = boot('mt_ex.img', b'MULTITASK=1\r\n', 88, 'MKFILE.COM=' + mk, 'EXS.EXE=' + xs, 'EXA.EXE=' + xa, 'EXB.EXE=' + xb,
             'EXM.EXE=' + xm, 'EXL.EXE=' + xl, A.CALCRUN, A.TSR, os.path.join(GOS, 'apps', 'TASKS.RUN'))
    seg, Y = mt_seg(k), k.Y
    arena = lambda: k.pc.u16(seg, Y['mt_arena'])
    B = Baseline(k)
    m0, s0, e0 = B.m0, B.s0, B.e0
    back = lambda: B.back() and tstate(k)[1] == 0 and k.pc.mode() == 0x40
    lists = [k.pc.u16(seg, Y[n]) for n in ('mt_lbg', 'mt_lfz', 'mt_lmem')]
    rp = bytes(k.rd('run_prog', 5))
    check('on: run_prog patched (MT_UI: a JMP FAR to KMW\'s mw_prog in MT\'s block), ex_mtw 2 while it waits; no lists '
          'in LODE.INI: each list empty (mt_lnone)', rp == b'\xea' + struct.pack('<HH', Y['mw_prog'], seg)
          and k.rd('ex_mtw', 1) == b'\x02' and lists == [Y['mt_lnone']] * 3, (rp.hex(), k.rd('ex_mtw', 1), lists))
    # the look for a task's end (mt_ui AL = 1) rides poll_once's clock: every 9 ticks while idle, not at each wake
    from unicorn import UC_HOOK_CODE
    lin, nui = seg * 16 + Y['mt_ui'], [0]
    hk = k.pc.mu.hook_add(UC_HOOK_CODE, lambda *a: nui.__setitem__(0, nui[0] + 1), None, lin, lin)
    k.pc.mu.ctl_remove_cache(lin, lin + 1)
    u0 = k.pc.us; k.run_for(2.0); nt = (k.pc.us - u0) / 54925.4
    check('2 s idle (%.0f ticks): the look for a task\'s end made %d times (every 9 ticks, poll_once\'s clock; not at '
          'each tick\'s wake)' % (nt, nui[0]), 1 <= nui[0] <= nt / 9 + 1, (nt, nui[0]))
    # Return: a task in front; its end: the Executive in front, its list again, "X ended, exit code n"
    ret(k, 'MTLINE.COM')
    st1, ar1, scr = tstate(k), arena(), k.pc.text_screen()
    nend = lambda: k.pc.rd(seg, Y['mt_nend'], 1)[0]
    n0, te, tl = nend(), None, None
    k.key('=5', settle=False); k.key(ktest.ENTER, settle=False)
    e = k.pc.us + 3000000
    while k.pc.us < e and tl is None:
        k.pc.run(300)
        if te is None and nend() != n0: te = k.pc.us
        if te is not None and k.pc.rd(seg, Y['mt_send'], 1)[0] == nend(): tl = k.pc.us
    k.pc.mu.hook_del(hk)
    lt = (tl - te) / 54925.4 if tl else None
    check('... and a task\'s end noticed within 9 ticks of it (%s ticks; mt_ui called %d times in all)'
          % ('%.1f' % lt if lt is not None else None, nui[0]), lt is not None and lt <= 9.5, (te, tl, nui[0]))
    k.run_for(1.0); k.settle()
    st2, b2 = tstate(k), k.band()
    check('Return on MTLINE.COM: a task in front (%s), its prompt there; 64 KB, a .COM\'s (%04Xh paragraphs); its line '
          '"=5": it ends, the Executive in front, "MTLINE.COM ended, exit code 5"' % (st1[:2], ar1),
          [n for i, s, n in st1[0]] == ['Executive', 'MTLINE.COM'] and st1[1] == 1 and 'MTLINE>' in scr
          and ar1 == 0x1000 and b2[:1] == ['MTLINE.COM ended, exit code 5'] and back(), (st1, ar1, scr[:80], st2, b2))
    l0 = k.exec_list()
    ret(k, 'MKFILE.COM')
    k.key('x', settle=False); k.run_for(1.5); k.settle()
    l1, b1 = k.exec_list(), k.band()
    check('a task that made a file (MADE.TXT): once it ends, the Executive\'s list has it (read again); '
          '"MKFILE.COM ended" (exit code 0: no more)', 'MADE.TXT' not in l0 and 'MADE.TXT' in l1
          and b1[:1] == ['MKFILE.COM ended'] and back(), (l1, b1))
    # an .EXE: its header's memory
    ret(k, 'EXS.EXE')
    a1 = arena()
    k.key('x', settle=False); k.run_for(1.0); k.settle()
    big = max(sz for s, t, o, sz, n in merged(mcbs(k)) if o == 0)     # (as 48h finds it: free neighbours as one)
    ret(k, 'EXA.EXE')
    a2 = arena()
    hot(k)                              # (back to the Executive: another fits)
    ret(k, 'MTLINE.COM')
    st3 = tstate(k)
    front(k, 0)                         # (and the Tasks window, still: RUN_ROOM kept)
    k.key(A.CODE['T']); k.run_for(0.5)
    tw = k.rd('run_active', 1)
    k.key(ktest.ESC); k.run_for(0.3)
    front(k, 2)
    line(k, '=1'); k.run_for(1.0); k.settle()
    b3 = k.band()
    front(k, 1); k.key('x', settle=False); k.run_for(1.0); k.settle()
    b4 = k.band()
    cap = big - 2 * (equ('TX_PARAS') + equ('ST_PARAS') + equ('ENVMAX') // 16 + 2) - 0x1000 - 1024
    check('an .EXE: what its header asks for: EXS.EXE (one paragraph, PSP, most 300h past it, and 4Ah for EXEC\'s copy of '
          'the environment) %04Xh = 35Bh; EXA.EXE (most FFFFh) %04Xh: the largest block (%04Xh) less two regions\' own, '
          '64 KB and RUN_ROOM, so MTLINE.COM still starts (%s), and the Tasks window still opens; each one\'s end said'
          % (a1, a2, big, st3[0]), a1 == 0x35B and a2 == cap and tw == b'\x01'
          and [n for i, s, n in st3[0]] == ['Executive', 'EXA.EXE', 'MTLINE.COM'] and b3[:1] == ['MTLINE.COM ended, exit code 1']
          and b4[:1] == ['EXA.EXE ended'] and back(), (a1, a2, cap, big, tw, st3, b3, b4))
    # least = most, and most < least (as EXEC: the least): each starts, room for the environment's copy in it
    got = []
    for n in ('EXM.EXE', 'EXL.EXE'):
        ret(k, n)
        got.append((arena(), [t[2] for t in tstate(k)[0]]))
        k.key('x', settle=False); k.run_for(1.0); k.settle()
        got[-1] += (k.band()[:1],)
    check('an .EXE whose least is its most (20h): %04Xh = 7Bh, and one whose most (10h) is below its least (40h): %04Xh '
          '= 9Bh; both start and end ("X ended")' % (got[0][0], got[1][0]),
          got == [(0x7B, ['Executive', 'EXM.EXE'], ['EXM.EXE ended']), (0x9B, ['Executive', 'EXL.EXE'], ['EXL.EXE ended'])]
          and back(), got)
    ret(k, 'EXB.EXE')
    b5, st5 = k.band(), tstate(k)
    k.key(ktest.ENTER)
    check('an .EXE whose least is more than there is (A000h paragraphs): not started, "Can\'t run EXB.EXE: not enough '
          'memory or EMS; park or end a task"', b5[:1] == ["Can't run EXB.EXE: not enough memory or EMS; park or end a task"]
          and st5[:2] == ([(0, 1, 'Executive')], 0) and back(), (b5, st5))
    # Shift-Return: as with it off, in the Executive's own task, all its memory
    o = run_wait(k, 'MEMSZ.COM', 30)
    m = re.search(r'([\d.]+) KB for programs', o)
    check('Shift-Return: MEMSZ.COM runs in the Executive\'s own task, which waits: all the memory (%s KB), no task' % (m and m.group(1)),
          m and float(m.group(1)) > 500 and back(), o[-200:])
    # CODE-P: LCMD in the Executive's own task (as before: the tests' Shell); seven tasks from it: too many for Return
    sh = Shell(k)
    s6 = tstate(k)
    for i in range(7): sh.run('start /w /m:1 mtline.com')
    sh.run('exit'); k.settle()
    ret(k, 'MTLINE.COM')
    b6 = k.band()
    k.key(ktest.ENTER)
    sh = Shell(k)
    for i in range(1, 8): sh.run('kill %d' % i)
    sh.run('exit'); k.settle()
    check('CODE-P: the prompt in the Executive\'s own task (%s); with seven tasks, Return says "Can\'t run MTLINE.COM: '
          'too many tasks"' % (s6[:2],), s6[:2] == ([(0, 1, 'Executive')], 0) and b6[:1] == ["Can't run MTLINE.COM: too many tasks"]
          and back(), (s6, b6))
    # a task ending while a .RUN's window is open: not the .RUN's event; said once it has closed
    ret(k, 'EXS.EXE')
    hot(k)
    k.key(A.CODE['K']); k.run_for(0.3)
    front(k, 1); k.key('x', settle=False); k.run_for(1.0)
    up = k.rd('run_active', 1)
    k.key(ktest.ESC); k.run_for(1.0); k.settle()
    b7 = k.band()
    check('a task (EXS.EXE) ending while the calculator is open: the calculator goes on (no event for it); once it '
          'is closed, "EXS.EXE ended"', up == b'\x01' and k.rd('run_active', 1) == b'\x00' and b7[:1] == ['EXS.EXE ended'] and back(), (up, b7))
    # a TSR from the Executive's own task (Shift-Return), right after the UI block: with a task there, the block
    # stays (tasks' copies of the vectors point into it); once the task has gone, it moves past the TSR (last:
    # the TSR stays)
    ret(k, 'MTLINE.COM')
    front(k, 0)
    u0 = k.useg
    run_wait(k, 'TSR.COM', 10)
    k.key(ktest.ENTER); k.run_for(0.3)
    s1 = (k.useg == u0, k.u16('ent_max'), tstate(k)[0])
    front(k, 1); line(k, '=3'); k.run_for(1.0); k.settle()
    b8 = k.band()
    s2 = (k.useg != u0, k.u16('ent_max'), k.pc.u16(0x60, k.Y['ui_seg']) == k.useg, 'TSR.COM' in k.exec_list())
    k.key(A.CODE['T']); k.run_for(0.5)
    tw = k.rd('run_active', 1)
    k.key(ktest.ESC); k.run_for(0.3)
    check('a TSR right after the UI block, from Shift-Return, with a task (MTLINE.COM) there: the block stays (%s); '
          'the task ends ("%s"): the block moves past the TSR, its whole list again, and the Tasks window opens'
          % (s1[:2], b8[:1]), s1[:2] == (True, 0) and [t[2] for t in s1[2]] == ['Executive', 'MTLINE.COM']
          and b8[:1] == ['MTLINE.COM ended, exit code 3'] and s2 == (True, 240, True, True) and tw == b'\x01'
          and k.rd('run_active', 1) == b'\x00' and not k.crashed, (s1, b8, s2, tw))
    # ... and MT after the move: a task again (INT 33h hooked again, at the new block), the Executive in front and
    # back (task 0's state saved at its new place), the task's end
    u1 = k.useg
    ret(k, 'MTLINE.COM')
    v33 = struct.unpack('<HH', k.pc.rd(0, 0x33 * 4, 4))
    front(k, 0); k.settle()
    s3 = (k.useg == u1, k.u16('ent_max'), 'TSR.COM' in k.exec_list(), k.pc.mode(),
          struct.unpack('<HH', k.pc.rd(0, 0x24 * 4, 4)) == (k.Y['ui_int24'], k.useg))
    front(k, 1); line(k, '=2'); k.run_for(1.0); k.settle()
    b9 = k.band()
    check('... then Return on MTLINE.COM: a task again, INT 33h through MT (mt_i33) once more; the Executive in front '
          'and back, its list whole and INT 24h its own at the new place (%s); the task ends: "%s"' % (s3[:3], b9[:1]),
          v33 == (Y['mt_i33'], seg) and s3 == (True, 240, True, 0x40, True) and b9[:1] == ['MTLINE.COM ended, exit code 2']
          and tstate(k)[:2] == ([(0, 1, 'Executive')], 0) and k.pc.mode() == 0x40 and not k.crashed, (v33, s3, b9))

def t_lists():
    print('== LODE.INI\'s BG=, FREEZE= and MTMEM= (M7b)')
    k = boot('mt_li.img', b'MULTITASK=1\r\nbg=mtspin, upper;X MTLIN\r\nFREEZE=MTLINE.EXE MTCWD.COM\r\n'
             b'MTMEM=MTLINE:100;HUGE.EXE:1 BAD BIG:5000 MTCWD:0 ,\r\n', 88, os.path.join(HERE, 'UPPER.COM'),
             mz(os.path.join(A.OUT, 'HUGE.EXE'), 0xA000, 0xA000))
    seg, Y = mt_seg(k), k.Y
    bg = b'MTSPIN\0\0\0UPPER\0\0\0X\0\0\0MTLIN\0\0\0\0'
    fz = b'MTLINE.EXE\0\0\0MTCWD.COM\0\0\0\0'
    mm = b'MTLINE\0' + struct.pack('<H', 100) + b'HUGE.EXE\0' + struct.pack('<H', 1) + b'\0'
    got = bytes(k.pc.rd(seg, Y['mt_ini'], len(bg + fz + mm)))
    ptr = [k.pc.u16(seg, Y[n]) for n in ('mt_lbg', 'mt_lfz', 'mt_lmem')]
    i0 = Y['mt_ini']
    check('the lists read at start-up (any case, commas, semicolons, blanks; MTMEM= entries without a number, of 0, '
          'or of 1024 KB and more left out)', got == bg + fz + mm and ptr == [i0, i0 + len(bg), i0 + len(bg + fz)], (got, ptr))
    sh = Shell(k)
    sh.run('ver')
    B = Baseline(k)
    m0, s0, e0, back = B.m0, B.s0, B.e0, B.back
    got = []
    for c in ('start /w mtspin.com 1 c1.txt', 'start /w a:\\mtspin.com 1 c2.txt', 'start /w mtline.com l1.txt',
              'start /w /m:32 mtline.com l2.txt', 'start /w mtcwd.com', 'start /w upper.com'):
        sh.run(c)
        got.append((k.pc.rd(seg, Y['mt_sflags'], 1)[0] & 6, k.pc.u16(seg, Y['mt_arena'])))
    for t in range(1, 7): sh.run('kill %d' % t)
    k.run_for(0.5)
    check('START: BG= gives SPF_BG (MTSPIN, by its name, also with a path; not MTLINE.COM for MTLIN); FREEZE= '
          'SPF_FREEZE (MTCWD.COM; not MTLINE.COM, named MTLINE.EXE); MTMEM= its KB (MTLINE:100: 1900h paragraphs) unless '
          '/M: says (/M:32: 800h); none: 64 KB (%s)' % (got,),
          got == [(2, 0x1000), (2, 0x1000), (0, 0x1900), (0, 0x800), (4, 0x1000), (2, 0x1000)] and back(), (got, tstate(k)))
    sh.run('exit'); k.settle(); k.run_for(1.0)
    bx = k.band()
    check('back from the prompt (CODE-P) after tasks it started ended: "LCMD.COM ended" stays (the list read again, '
          'no message of the Executive\'s)', bx[:1] == ['LCMD.COM ended'], bx)
    k.key(ktest.ENTER)
    ret(k, 'MTLINE.COM')
    a1 = k.pc.u16(seg, Y['mt_arena'])
    line(k, '=0'); k.run_for(1.0); k.settle()
    b1 = k.band()
    ret(k, 'HUGE.EXE', 1.5); k.settle()
    b2 = k.band()
    check('Return: MTMEM= too (MTLINE.COM: 1900h paragraphs, not a .COM\'s 64 KB); HUGE.EXE with 1 KB (it asks 640 KB: no '
          'growth has room for it): "HUGE.EXE could not be started: error 8"', a1 == 0x1900 and b1[:1] == ['MTLINE.COM ended']
          and b2[:1] == ['HUGE.EXE could not be started: error 8'] and tstate(k)[0] == [(0, 1, 'Executive')], (a1, b1, b2))

def t_tasksrun():
    print('== TASKS.RUN: the tasks, CODE-T (M7b)')
    TR = os.path.join(GOS, 'apps', 'TASKS.RUN')
    k = boot('mt_tr0.img', None, 88, TR)
    k.key(A.CODE['T']); k.run_for(0.3)
    t0 = k.text()
    k.key(A.CODE['D']); k.run_for(0.2)
    bd = k.band()
    k.key(A.CODE['Z'], A.CODE['B'], ktest.ENTER); k.run_for(0.3)
    t1 = k.text()
    k.key(ktest.ESC); k.run_for(0.3)
    check('off: CODE-T opens Tasks, which says multitasking is off; CODE-D, CODE-Z, CODE-B, Return: nothing (no task '
          'selected: no question); ESC closes it (exit code 0FFFFh)', 'Multitasking is off.' in t0
          and not any(b.startswith('End') for b in bd) and 'Multitasking is off.' in t1 and A.run_ret(k) == 0xFFFF,
          (t0[-600:], bd))
    k = boot('mt_tr.img', b'MULTITASK=1\r\n', 88, TR)
    seg, Y = mt_seg(k), k.Y
    vf = lambda t: k.pc.rd(seg, Y['mt_tab'] + t * MT_ENT + TE_VF, 1)[0]
    for i in (1, 2):                    # two tasks, each waiting for a key behind
        ret(k, 'MTLINE.COM'); hot(k)
    k.key(A.CODE['T']); k.run_for(0.3)
    rows = lambda: [l[17:63].strip() for y, l in k.ocr() if re.match(r'\d  ', l[17:63].strip())]    # (inside the window)
    r0 = rows()
    k.key(ktest.DOWN)
    fl = []
    for i in range(3):
        k.key(A.CODE['B']); k.run_for(0.2); fl.append((vf(1), rows()[1].split()[-1]))
    check('CODE-T: a row each (%s); CODE-B on task 1: may run behind yes (SPF_BG), no (SPF_FREEZE), auto again (%s)'
          % (r0, fl), len(r0) == 3 and re.match(r'0  Executive\s+in front$', r0[0])
          and all(re.match(r'%d  MTLINE\.COM\s+waiting for a key\s+auto$' % t, r0[t]) for t in (1, 2))
          and fl == [(2, 'yes'), (4, 'no'), (0, 'auto')], (r0, fl))
    k.key(A.CODE['Z']); k.run_for(0.3)
    p1, r1 = tstate(k)[0], rows()
    k.key(A.CODE['Z']); k.run_for(0.3)
    p2 = tstate(k)[0]
    k.key(ktest.UP); k.key(A.CODE['Z']); k.run_for(0.2)
    b0 = k.band()
    k.key(ktest.ENTER)
    k.key(A.CODE['B']); k.run_for(0.2)
    b0 += k.band()
    k.key(ktest.ENTER)
    check('CODE-Z: task 1 parked (its row "parked"), CODE-Z again: back; on the Executive\'s row, CODE-Z and CODE-B: '
          '"Not possible for that task"', p1[1] == (1, 5, 'MTLINE.COM') and 'parked' in r1[1] and p2[1][1] != 5
          and [b for b in b0 if b.startswith('Not')] == ['Not possible for that task'] * 2, (p1, r1, p2, b0))
    k.key(ktest.DOWN); k.key(A.CODE['D']); k.run_for(0.2)
    be = k.band()
    k.key(ktest.ESC); k.run_for(0.3)
    re1, se = rows(), tstate(k)[0]
    k.key(ktest.UP)
    check('CODE-D on task 1: asked ("%s"); ESC: nothing ended, its row as it was, both tasks there (%s)' % (be[:1], se),
          be[:1] == ['End MTLINE.COM: Confirm to end the task'] and len(re1) == 3 and 'being ended' not in re1[1]
          and [n for i, s, n in se] == ['Executive', 'MTLINE.COM', 'MTLINE.COM'], (be, re1, se))
    k.key(ktest.DOWN); k.key(ktest.DOWN); k.key(A.CODE['D']); k.run_for(0.2)
    b1 = k.band()
    k.key(ktest.ENTER); k.run_for(0.2)
    r2 = rows()
    k.key(ktest.UP); k.key(A.CODE['Z']); k.run_for(0.3)
    pz = tstate(k)[0][1]
    k.key(ktest.ENTER); k.run_for(1.0)
    st = tstate(k)
    rr = A.run_ret(k)
    line(k, '=2'); k.run_for(1.5); k.settle()
    b2 = k.band()
    check('CODE-D on task 2: asked ("%s"), Return: its row "being ended"; task 1 parked, then Return: brought back, in '
          'front, the window closed (exit code 0FFFFh), task 2 gone (%s); task 1 ends: "MTLINE.COM ended, exit code 2"'
          % (b1[:1], st[:2]), b1[:1] == ['End MTLINE.COM: Confirm to end the task'] and 'being ended' in r2[2]
          and pz == (1, 5, 'MTLINE.COM') and [n for i, s, n in st[0]] == ['Executive', 'MTLINE.COM'] and st[1] == 1 and rr == 0xFFFF
          and b2[:1] == ['MTLINE.COM ended, exit code 2'] and tstate(k)[0] == [(0, 1, 'Executive')], (b1, r2, pz, st, rr, b2))

SE_SIZE, SE_BASE, SE_END, SE_SP, MW_STK = map(equ, ('SE_SIZE', 'SE_BASE', 'SE_END', 'SE_SP', 'MW_STK'))  # KMW.INC
SE_TASK = equ('SE_TASK')                                         # (a terminal window's task: T2)

def t_windows():
    print('== several window .RUNs at once: the calculator and the tasks (M8a)')
    TR = os.path.join(GOS, 'apps', 'TASKS.RUN')
    k = boot('mt_win.img', b'MULTITASK=1\r\n', 88, TR, A.CALCRUN, mouse=True)
    seg, Y = mt_seg(k), k.Y
    mb = lambda n: k.pc.rd(seg, Y[n], 1)[0]
    rec = lambda i, o: k.pc.u16(seg, Y['mw_ses'] + i * SE_SIZE + o)
    top = lambda: k.pc.u16(k.useg, Y['wstack'] + 4 * (k.u16('wdepth') - 1))
    def col(t):
        """The column where t is drawn (the pointer out of the way)."""
        A.point(k, 320, 399, settle=False); took(k, 'the pointer moved', True); k.run_for(0.3)
        return next((l.index(t) for y, l in k.ocr() if t in l), None)
    def uip():
        """As A.free_paras, from the whole arena's start (first_mcb is the task's
        running: MTSPIN's region while it counts)."""
        f = k.u16('first_mcb'); k.wr('first_mcb', struct.pack('<H', k.mcb0))
        try: return A.free_paras(k)
        finally: k.wr('first_mcb', struct.pack('<H', f))
    free0 = uip()
    # something computing behind meanwhile, and every switch checked
    k.key(A.CODE['P']); k.run_for(1.0)
    typ(k, 'start /w mtspin.com 5000 ws.txt', 0.3); typ(k, 'exit', 1.0); k.run_for(0.5)
    au = Audit(k)
    bkey(k, A.CODE['K'], t=0.5)
    n1, b1, x0 = mb('mw_n'), rec(1, SE_BASE), rec(0, SE_SP)
    bkey(k, A.CODE['T'], t=0.5)
    n2, c2, w2 = mb('mw_n'), mb('mw_cur'), k.u16('wdepth')
    check('CODE-K: the calculator, a session (%d) in the first slot (run_base, %04Xh), the Executive waiting on its own '
          'stack (%04Xh); CODE-T inside it: the tasks, in front (session %d), the calculator still there: %d windows'
          % (n1, b1, x0, c2, w2), n1 == 1 and b1 == k.u16('run_base') and Y['ui_stack_top'] - 2560 <= x0 < Y['ui_stack_top']
          and n2 == 2 and c2 == 2 and w2 == 2 and A.has(k, 'Calculator') and A.has(k, 'Tasks')
          and rec(2, SE_BASE) == rec(1, SE_END), (n1, hex(b1), hex(x0), n2, c2, w2, A.screen(k)))
    # the calculator's stack, painted where it isn't used, to see how deep it goes
    cb = rec(1, SE_END) - 8 - MW_STK
    k.pc.wr(k.useg, cb, b'\xa5' * (rec(1, SE_SP) - cb))
    def ans(): return [m.group(0) for l in A.lines(k) for m in [re.search(r'= -?[\d.]+', l)] if m]
    bkey(k, '9*9', t=0.3)                    # (the tasks: no such keys)
    a0 = A.has(k, '9*9')
    bkey(k, 0x6D00, t=0.5)
    c3, t3 = mb('mw_cur'), top()
    bkey(k, '2+2', ktest.ENTER, t=0.3)
    a1 = ans()
    check('keys go to the window in front only: "9*9" in the tasks, none for the calculator; CODE-F6: the calculator '
          'in front (session %d, its window on top), "2+2" Return: = 4 (%s)' % (c3, a1),
          not a0 and c3 == 1 and rec(1, SE_BASE) <= t3 < rec(1, SE_END) and a1 == ['= 4'] and mb('mw_n') == 2,
          (a0, c3, hex(t3), a1, mb('mw_n')))
    # moved: no save-under, so the screen drawn again under it
    c0 = col('Calculator')
    bkey(k, 0x6E00, ktest.LEFT, ktest.LEFT, ktest.LEFT, ktest.ENTER, t=0.3)
    cm = col('Calculator')
    mv = (A.has(k, 'Tasks'), A.has(k, 'LCMD'), A.has(k, '= 4'))
    bkey(k, 0x6E00, ktest.RIGHT, ktest.RIGHT, ktest.RIGHT, ktest.ENTER, t=0.3)
    check('CODE-F7, Left x3, Return in the calculator: 3 columns left (title at %s, from %s), the tasks\' window and the '
          'Executive\'s list drawn again under where it was, its line still there; moved back' % (cm, c0),
          c0 is not None and cm == c0 - 3 and mv == (True, True, True) and col('Calculator') == c0 and mb('mw_cur') == 1,
          (c0, cm, mv, A.screen(k)))
    bkey(k, ktest.F1, t=0.3)
    hp = A.has(k, 'Calculator Help')
    bkey(k, 0x6D00, t=0.3)
    c4, hp4 = mb('mw_cur'), A.has(k, 'Calculator Help')
    bclick(k, 20 * 8, 270)        # (the tasks' window only)
    c5, t5 = mb('mw_cur'), top()
    check('F1 in the calculator: its help; CODE-F6 meanwhile is its key, as any, which closes it: no change of front '
          '(session %d); a click on the tasks\' window: the tasks in front (session %d, on top)' % (c4, c5),
          hp and not hp4 and c4 == 1 and c5 == 2 and rec(2, SE_BASE) <= t5 < rec(2, SE_END), (hp, hp4, c4, c5, hex(t5)))
    # each one's band its own: the tasks' question waiting, the calculator's band meanwhile the Executive's
    q = 'End Executive: Confirm to end the task'
    bkey(k, A.CODE['D'], t=0.3)              # (on the Executive's row: asked, then "not possible")
    bt = k.band()
    bclick(k, 70 * 8, 100)
    bc, beh = k.band(), A.has(k, 'Behind')
    bclick(k, 20 * 8, 270)
    bt2, beh2 = k.band(), A.has(k, 'Behind')
    bkey(k, ktest.ESC, t=0.3)
    check('the tasks\' question waiting in the band (%s), a click on the calculator: in front, its own band (%s), the '
          'tasks\' columns under it; a click on the tasks: their question again, as it was (TASKS.RUN: its own buffer, '
          'not the rows\'), their window on top; ESC: no' % (bt[:1], bc[:1]), bt[:1] == [q]
          and bc[:1] == ['Select a file and confirm'] and not beh and bt2[:1] == [q] and beh2 and mb('mw_cur') == 2
          and mb('mw_n') == 2, (bt, bc, beh, bt2, beh2))
    bclick(k, 70 * 8, 100)        # (the calculator's only)
    c6 = mb('mw_cur')
    bclick(k, 20 * 8, 270)
    bkey(k, A.CODE['K'], t=0.5)
    c7, n7 = mb('mw_cur'), mb('mw_n')
    used = MW_STK - next((i for i, b in enumerate(k.pc.rd(k.useg, cb, MW_STK)) if b != 0xA5), MW_STK)
    print('   the calculator\'s stack: %d bytes of %d used' % (used, MW_STK))
    check('a click on the calculator: in front (%d); CODE-K with the tasks in front: the calculator brought there, not '
          'another (session %d, %d running); its stack: %d of %d bytes used' % (c6, c7, n7, used, MW_STK),
          c6 == 1 and c7 == 1 and n7 == 2 and used < MW_STK * 3 // 4, (c6, c7, n7, used))
    bkey(k, A.CODE['K'], t=0.5)
    n8, c8 = mb('mw_n'), mb('mw_cur')
    calc8, tasks8 = A.has(k, 'Calculator'), A.has(k, 'Tasks')
    k.pc.wr(seg, Y['mw_n'], bytes([4]))             # (as many as there may be: poked)
    bkey(k, A.CODE['K'], t=0.5)
    bf = k.band()
    bkey(k, ktest.ENTER, t=0.3)
    k.pc.wr(seg, Y['mw_n'], bytes([1]))
    check('... with as many window .RUNs as there may be, CODE-K: "CALC.RUN doesn\'t fit: close a window first" in the '
          'band (%s), the tasks in front still' % bf[:1], bf[:1] == ["CALC.RUN doesn't fit: close a window first"]
          and mb('mw_cur') == 2 and not A.has(k, 'Calculator'), (bf, mb('mw_cur')))
    bkey(k, A.CODE['K'], t=0.5)
    b9, n9 = rec(1, SE_BASE), mb('mw_n')            # (mw_free: the first record unused, 1 again)
    check('CODE-K in the calculator, in front: its own key, as without tasks: it closes (%d running, the tasks in front, '
          'session %d; its window gone, the tasks\' drawn again); CODE-K: it starts again, in the slot it left (%04Xh)'
          % (n8, c8, b9), n8 == 1 and c8 == 2 and not calc8 and tasks8 and n9 == 2 and k.pc.rd(seg, Y['mw_ses'] + SE_SIZE, 1)[0] == 1
          and b9 == k.u16('run_base'), (n8, c8, calc8, tasks8, hex(b9), n9))
    k.wr('saver_t', struct.pack('<H', 36))
    for _ in range(40):
        k.pc.run_for(0.25)
        if not A.has(k, 'Calculator'): break
    dark = not A.has(k, 'Calculator')
    k.wr('saver_t', struct.pack('<H', 5460))
    bkey(k, ktest.DOWN, t=0.5)
    spin = [n for i, s, n in tstate(k)[0]]
    check('the saver with both open, then a key: the Executive and both windows back; MTSPIN computing behind still (%s)'
          % spin, dark and A.has(k, 'Calculator') and A.has(k, 'Tasks') and A.has(k, 'LCMD') and 'MTSPIN.COM' in spin,
          (spin, A.screen(k)))
    ts = [i for i in (1, 2, 3, 4) if rec(i, 0) and rec(i, SE_BASE) > k.u16('run_base')]     # (the tasks' slot: above)
    hi0 = uip()[1]
    bkey(k, 0x6D00, t=0.5)                       # (the tasks in front)
    bkey(k, ktest.ESC, t=0.5)
    n10, c10, ub = mb('mw_n'), mb('mw_cur'), uip()[1]
    bkey(k, 0x6D00, t=0.5)
    c10b = mb('mw_cur')
    check('the tasks in front (CODE-F6), ESC: they close, the one in front before them next: the Executive (M8c: '
          'CODE-F6 put the calculator last), the calculator still open; CODE-F6: the calculator in front; the UI block the '
          'whole segment still while one runs (%s paragraphs, and %s with both: M8b)' % (ub, hi0), ts and n10 == 1
          and c10 == 0 and c10b == 1 and hi0 == 4096 and ub == 4096 and A.has(k, 'Calculator')
          and not A.has(k, 'Tasks'), (ts, n10, c10, c10b, hi0, ub, hex(rec(1, SE_END))))
    bkey(k, ktest.ESC, t=0.5); k.run_for(0.5)
    au.stop()
    sw = au.switches()
    ss = [e for e in sw if e['task'] == 0 and e['ss'] == k.useg and e['csp'] >= k.u16('run_base')]
    check('ESC, ESC: both closed (%d, then %d), the Executive back: its list, nothing loaded (run_active 0), the UI block '
          'as before; every switch meanwhile by the rules (%d, %d of them from a session\'s own stack, at the UI\'s idle HLTs: its loop\'s or the saver\'s'
          ', or a move\'s or resize\'s wait, mwait: audit3 X32; each of the three)' % (n10, mb('mw_n'), len(sw), len(ss)),
          n10 == 1 and mb('mw_n') == 0 and k.rd('run_active', 1) == b'\x00' and uip()[1] == free0[1]
          and A.has(k, 'Select a file and confirm') and not au.bad() and ss and not k.crashed
          and set(e['ip'] for e in ss) == {Y['..@ui_idle'], Y['..@ui_sidle'], Y['..@ui_midle']}, (n10, uip(), free0, au.bad()[:3], len(sw), len(ss), k.crashed, k.band(), sorted(set(hex(e['ip']) for e in ss if e['ip'] != Y['..@ui_idle']))))
    # started from a window while its question waits: the Executive's band, not a pointer into the starter's slot
    bkey(k, A.CODE['T'], t=0.5)
    bkey(k, A.CODE['D'], t=0.3)
    bkey(k, A.CODE['K'], t=0.5)
    bk, ck = k.band(), mb('mw_cur')
    k.wr('saver_t', struct.pack('<H', 36))
    for _ in range(40):
        k.pc.run_for(0.25)
        if not A.has(k, 'Calculator'): break
    k.wr('saver_t', struct.pack('<H', 5460))
    bkey(k, ktest.DOWN, t=0.5)
    bk2 = k.band()
    bkey(k, ktest.ESC, t=0.5)
    bt3 = k.band()
    bkey(k, ktest.ESC, t=0.3); bkey(k, ktest.ESC, t=0.5); k.run_for(0.5)
    check('CODE-D in the tasks, then CODE-K while it asks: the calculator\'s band the Executive\'s (%s), after the saver '
          'too (%s), not the tasks\' question; ESC: the tasks\' question again (%s); ESC, ESC: none left'
          % (bk[:1], bk2[:1], bt3[:1]), ck == 2 and bk[:1] == bk2[:1] == ['Select a file and confirm'] and bt3[:1] == [q]
          and mb('mw_n') == 0 and A.has(k, 'Select a file and confirm'), (ck, bk, bk2, bt3, mb('mw_n')))
    k = boot('mt_win2.img', b'MULTITASK=1\r\n', 88, TR)
    seg = mt_seg(k)
    k.key(A.CODE['T']); k.run_for(0.5)
    k.key(A.CODE['K']); k.run_for(0.5)
    bf, m1 = k.band(), k.pc.rd(seg, k.Y['mw_msg'], 1)[0]
    for _ in range(5): k.key(A.CODE['K']); k.run_for(0.2)     # (each one ends the message, or says it again)
    m2 = k.pc.rd(seg, k.Y['mw_msg'], 1)[0]
    k.run_for(0.3)
    up, m3 = A.has(k, 'Tasks'), k.pc.rd(seg, k.Y['mw_msg'], 1)[0]
    k.key(ktest.ESC); k.run_for(0.5)
    check('no CALC.RUN on the disk, CODE-K in the tasks: "CALC.RUN is not on this disk" (%s), waiting (%d); CODE-K '
          'meanwhile ends it, as any key, never nested (%d after five: ended, said, ended..., then %d); the tasks there still; '
          'ESC: the Executive' % (bf[:1], m1, m2, m3), bf[:1] == ['CALC.RUN is not on this disk'] and m1 == 1 and m2 == 0
          and m3 == 0 and up and k.pc.rd(seg, k.Y['mw_n'], 1)[0] == 0 and A.has(k, 'Select a file and confirm')
          and not k.crashed, (bf, m1, m2, m3, up, A.screen(k)))
    # a damaged CALC.RUN (cut short): from the Executive, run_app's message; from the tasks, the band's
    cr = open(A.CALCRUN, 'rb').read()
    bad = os.path.join(A.OUT, 'CALCBAD.RUN'); open(bad, 'wb').write(cr[:len(cr) // 2])
    k = boot('mt_win3.img', b'MULTITASK=1\r\n', 88, TR, 'CALC.RUN=' + bad)
    seg = mt_seg(k)
    f0 = A.free_paras(k)
    k.key(A.CODE['K']); k.run_for(0.5)
    be, re0, n0 = k.band(), k.rd('run_active', 1), k.pc.rd(seg, k.Y['mw_n'], 1)[0]
    k.key(ktest.ENTER); k.run_for(0.3)
    f1 = A.free_paras(k)
    k.key(A.CODE['T']); k.run_for(0.5)
    k.key(A.CODE['K']); k.run_for(0.5)
    bt = k.band()
    k.key(ktest.ENTER); k.run_for(0.3)
    n1, up = k.pc.rd(seg, k.Y['mw_n'], 1)[0], A.has(k, 'Tasks')
    k.key(ktest.ESC); k.run_for(0.5); k.settle()
    check('a CALC.RUN cut short: CODE-K in the Executive says "Can\'t run" (%s), nothing loaded, the UI block as it was; '
          'CODE-K in the tasks: "CALC.RUN can\'t start" (%s), the tasks still alone and in front' % (be[:1], bt[:1]),
          any(b.startswith("Can't run") for b in be) and re0 == b'\x00' and n0 == 0 and f1 == f0
          and bt[:1] == ["CALC.RUN can't start"] and n1 == 1 and up and A.free_paras(k) == f0 and not k.crashed,
          (be, re0, n0, f0, f1, bt, n1, up, A.free_paras(k)))

def t_base():
    print('== the Executive live under the windows (M8c): in front by a click or CODE-F6, its drawing clipped')
    p = os.path.join(A.OUT, 'NOTES.TXT'); open(p, 'wb').write(A.TEXT)
    q = os.path.join(A.OUT, 'OTHER.TXT'); open(q, 'wb').write(b'Other file\r\nsecond line')
    sq = os.path.join(A.OUT, 'SUBOTHER.TXT'); open(sq, 'wb').write(b'was in SUB\r\n')
    k = boot('mt_base.img', b'MULTITASK=1\r\n', 88, A.CALCRUN, A.WRITE, A.SYSTEM, p, q, 'SUB\\', 'SUB\\OTHER.TXT=' + sq,
             mouse=True)
    seg, Y = mt_seg(k), k.Y
    mb = lambda n: k.pc.rd(seg, Y[n], 1)[0]
    rec = lambda i, o: k.pc.u16(seg, Y['mw_ses'] + i * SE_SIZE + o)
    mru = lambda: list(k.pc.rd(seg, Y['mw_mru'], 5))
    WS = A.run_syms('apps/WRITE.ASM')
    def win(i):
        a = rec(i, SE_BASE) + WS['win']
        return tuple(k.pc.u16(k.useg, a + o) for o in (0, 2, 4, 6))
    def pix(c, y, w, h):
        """The screen's bytes in columns c.., rows y.. (the pointer out of the way)."""
        A.point(k, 639, 399)
        return b''.join(bytes(k.pc.rd(0xB800, (r & 3) * 0x2000 + (r >> 2) * 80 + c, w)) for r in range(y, y + h))
    def strip(t):
        """The title strip's line holding t, as read."""
        A.point(k, 639, 399)
        return next((l.rstrip() for y, l in k.ocr() if t in l), '')
    free0 = A.free_paras(k)
    fb0 = bytes(k.pc.rd(k.useg, Y['fill_band'], 5))
    k.select('NOTES.TXT'); k.key(ktest.ENTER); k.run_for(1.0)
    w1, fb1 = win(1), bytes(k.pc.rd(k.useg, Y['fill_band'], 5))
    A.click(k, 4, 72); k.run_for(0.3)               # (left of Write: the Executive's list)
    c1, b1, m1 = mb('mw_cur'), k.band(), mru()
    px = pix(*w1)
    check('Write in a window (%s), then a click on the Executive left of it: the Executive in front (%d), its own band '
          '(%s), Write still open (focus order %s); the core\'s drawing patched while windows run (fill_band: %s)'
          % (w1, c1, b1[:1], m1, fb1.hex()), mb('mw_n') == 1 and c1 == 0 and b1[:1] == ['Select a file and confirm']
          and m1 == [0, 1, 255, 255, 255] and fb1[0] == 0xEA and fb0[0] == 0x60 and A.has(k, 'Write: NOTES.TXT'),
          (w1, c1, b1, m1, fb0.hex(), fb1.hex()))
    s0 = k.u16('sel')
    k.key(ktest.DOWN, ktest.DOWN); k.run_for(0.3)
    s1, pd = k.u16('sel'), pix(*w1)
    k.key(ktest.TAB); k.run_for(0.3)
    pt, bt = pix(*w1), k.band()
    k.key(ktest.TAB, ktest.TAB); k.run_for(0.3)
    check('its keys its own: Down x2 moves its selection (%d to %d) under Write, Tab outlines Device (%s), Tab x2: '
          'Title again; Write\'s window not touched meanwhile (its bytes as they were)' % (s0, s1, bt[:1]), s1 == s0 + 2
          and pd == px and pt == px and bt[:1] == ['Device: Select item and confirm'] and pix(*w1) == px
          and mb('mw_cur') == 0, (s0, s1, pd == px, pt == px, bt, pix(*w1) == px))
    k.key(ktest.F1); k.run_for(0.5)
    hp = A.has(k, 'Lodestone 0.6 Help')
    k.key(ktest.ESC); k.run_for(0.5)
    st1 = strip('Write: NOTES.TXT')
    check('F1 in the Executive: its help, over Write; a key closes it: Write drawn again as it was (its bytes), its close '
          'box too (%r)' % st1, hp and not A.has(k, 'Lodestone 0.6 Help') and st1.endswith('x') and pix(*w1) == px
          and mb('mw_cur') == 0, (hp, st1, pix(*w1) == px, A.screen(k)))
    k.select('OTHER.TXT'); k.key(A.CODE['R']); k.run_for(0.5)
    k.key('QQ'); k.run_for(0.3)
    A.point(k, 639, 399)
    rf = [l.strip() for y, l in k.ocr() if 'New title' in l]
    k.key(ktest.ESC); k.run_for(0.5)
    check('CODE-R in the Executive: its form over Write, what is typed in it shown there (%s), not cut around Write: a '
          'window of its own' % rf, rf[:1] == ['New title  QQ'] and 'OTHER.TXT' in k.exec_list() and mb('mw_cur') == 0, rf)
    k.select('OTHER.TXT'); k.key(ktest.ENTER); k.run_for(1.0)
    c2, n2 = mb('mw_cur'), mb('mw_n')
    check('Return on OTHER.TXT in the Executive, Write open: a second Write with that file (session %d, %d running), in '
          'front; the first still open' % (c2, n2), c2 == 2 and n2 == 2 and A.has(k, 'Write: OTHER.TXT')
          and A.has(k, 'ther file') and A.has(k, 'Write: NOTES.TXT'), A.screen(k))
    cy = []
    for _ in range(3):
        k.key(0x6D00); k.run_for(0.5); cy.append(mb('mw_cur'))
    check('CODE-F6 x3 from the second Write: the Executive, the first Write, the second again (%s): the Executive is one '
          'of them' % cy, cy == [0, 1, 2], (cy, mru()))
    k.key(A.CODE['K']); k.run_for(0.5)
    ck = mb('mw_cur')
    k.key(ktest.ESC); k.run_for(0.5)
    ce = mb('mw_cur')
    A.click(k, 4, 340); k.run_for(0.3)              # (the Executive's information line)
    k.key(A.CODE['K']); k.run_for(0.5)
    ck2, x0, mk = mb('mw_cur'), rec(0, SE_SP), k.rd('ex_mtw', 1)[0]
    k.key(ktest.ESC); k.run_for(0.5)
    ce2, me = mb('mw_cur'), k.rd('ex_mtw', 1)[0]
    s2 = k.u16('sel')
    k.key(ktest.UP); k.run_for(0.3)
    check('CODE-K in the second Write: the calculator (session %d); ESC: the Write in front again (%d); a click on the '
          'Executive, CODE-K: the calculator again (%d), the Executive waiting in its UI_EVENT, the calculator\'s ex_mtw 1 '
          '(%d: a task\'s end not its event); ESC: the Executive in front (%d), its ex_mtw 2 again (%d), Up its key'
          % (ck, ce, ck2, mk, ce2, me), ck == 3 and ce == 2 and ck2 == 3 and ce2 == 0 and mk == 1 and me == 2
          and k.u16('sel') == s2 - 1 and mb('mw_n') == 2 and Y['ui_stack_top'] - 2560 <= x0 < Y['ui_stack_top'],
          (ck, ce, ck2, mk, ce2, me, s2, k.u16('sel'), hex(x0)))
    k.key(A.CODE['U']); k.run_for(0.5)
    bu = k.band()
    k.key(ktest.ENTER); k.run_for(0.3)
    check('CODE-U (System) with windows open: "%s" in the band; nothing started' % bu[:1],
          bu[:1] == ['SYSTEM.RUN needs the whole screen: close the windows first'] and mb('mw_n') == 2
          and mb('mw_cur') == 0 and k.rd('run_active', 1) == b'\x01', (bu, mb('mw_n')))
    # a window started while the Executive asks: its question and Copy/Move's destination (dstpath) left alone
    k.select('OTHER.TXT')
    k.key(A.CODE['C']); k.run_for(0.3)              # (Copy to SUB, which has an OTHER.TXT: Replace Ask's question)
    k.key(ktest.ENTER, ktest.ENTER, '\\sub', A.K_CODE_ENTER); k.run_for(0.5)
    bq0, dq0 = k.band(), bytes(k.rd('dstpath', 84)).split(b'\x00')[0]
    k.key(A.CODE['K']); k.run_for(0.5)
    cq, hq, bq1, dq = mb('mw_cur'), k.u16('held1'), k.band(), bytes(k.rd('dstpath', 84)).split(b'\x00')[0]
    k.key(ktest.ESC); k.run_for(0.5)
    bq2 = k.band()
    k.key(ktest.ESC); k.run_for(0.5)
    sub = A.fatcheck.read_files(k.pc.drives[0].img).get('A:\\SUB\\OTHER.TXT')
    check('Copy OTHER.TXT to SUB, Replace Ask: the Executive asks (%s; its destination %r); CODE-K meanwhile: the '
          'calculator, its band not the question (%s), the destination kept (%r); ESC: the question back; ESC: SUB\'s '
          'OTHER.TXT as it was' % (bq0[:1], dq0, bq1[:1], dq), bq0[:1] == ['OTHER.TXT is there already: Confirm to replace it']
          and dq0.upper().endswith(b'\\SUB\\OTHER.TXT') and cq == 3 and hq == 0 and not any('there already' in b for b in bq1)
          and dq == dq0 and bq2[:1] == bq0[:1] and sub == b'was in SUB\r\n' and mb('mw_cur') == 0,
          (bq0, dq0, cq, hq, bq1, dq, bq2, sub, mb('mw_cur')))
    # a task's end is the Executive's event, not a window's (ex_mtw is each one's own)
    k.key(A.CODE['P']); k.run_for(1.0)
    typ(k, 'start /w mtspin.com 400 tb.txt', 0.3); typ(k, 'exit', 1.0); k.run_for(0.5)    # (22 s: it ends later)
    bp = (A.has(k, 'Write: OTHER.TXT'), A.has(k, 'Write: NOTES.TXT'), mb('mw_cur'))
    ev, dk = [], rec(2, SE_BASE) + WS['do_key']
    def evh(pc):
        if pc.r('ip') == dk and pc.r('cs') == k.useg: ev.append(pc.r('ax'))
    k.hooks.append(evh)
    w2 = win(2)
    bclick(k, (w2[0] + 40) * 8, w2[1] + w2[3] - 12)     # (the second Write's status line)
    cw, tb0, lw0 = mb('mw_cur'), A.disk_file(k, 'TB.TXT'), 'TB.TXT' in k.exec_list()
    for _ in range(120):
        k.run_for(0.25)
        if A.disk_file(k, 'TB.TXT'): break
    k.run_for(0.5)
    k.hooks.remove(evh)
    tb, bw, lw = A.disk_file(k, 'TB.TXT'), k.band(), 'TB.TXT' in k.exec_list()
    tclick(k, 4, 340); k.run_for(0.5)
    lx = 'TB.TXT' in k.exec_list()
    A.click(k, 4, 340); k.run_for(0.3)             # ("LCMD.COM ended" still waits: a click reads it)
    check('CODE-P with windows open, START /W MTSPIN.COM, EXIT: both Writes back (%s); the second Write in front while '
          'MTSPIN ends: given no task\'s end (%s), its band its own (%s), the Executive\'s list as it was (no TB.TXT); a '
          'click on the Executive: its list again, TB.TXT in it' % (bp, [hex(e) for e in ev if e >= 0xFF10], bw[:1]),
          bp == (True, True, 0) and cw == 2 and tb0 is None and not lw0 and tb is not None
          and not any(e in (0xFF10, 0xFF11) for e in ev) and not lw and lx
          and bw[:1] == ['Type, or choose a command (CODE-? lists them)'] and mb('mw_cur') == 0,
          (bp, cw, tb0, lw0, tb, ev, bw, lw, lx))
    for i in (2, 1):                                # each Write: ESC, Return (unchanged)
        A.click(k, (win(i)[0] + 40) * 8, win(i)[1] + win(i)[3] - 12); k.run_for(0.3)
        k.key(ktest.ESC); k.run_for(0.3); k.key(ktest.ENTER); k.run_for(0.8)
    k.settle()
    fb2 = bytes(k.pc.rd(k.useg, Y['fill_band'], 5))
    check('both Writes closed: the Executive in front, nothing loaded (run_active 0), the UI block as before, the '
          'drawing unpatched (%s)' % fb2.hex(), mb('mw_n') == 0 and mb('mw_cur') == 0 and k.rd('run_active', 1) == b'\x00'
          and A.free_paras(k) == free0 and fb2 == fb0 and mb('mw_cp') == 0 and A.has(k, 'Select a file and confirm')
          and not k.crashed, (mb('mw_n'), mb('mw_cur'), k.rd('run_active', 1), mb('mw_cp'), k.band(), k.crashed, A.free_paras(k), free0, fb2.hex(), A.screen(k)))
    # the Executive's text cut by the calculator: right where it shows, the rows its top edge crosses too
    CS = A.run_syms('apps/CALC.ASM')
    k.key(A.CODE['K']); k.run_for(0.5)
    cwin = lambda: tuple(k.pc.u16(k.useg, rec(1, SE_BASE) + CS['win'] + o) for o in (0, 2, 4, 6))
    k.key(0x6E00, *([ktest.DOWN] * (1 if (cwin()[1] + 4 - 24) % 16 else 2)), ktest.ENTER); k.run_for(0.5)
    c0 = cwin()
    A.click(k, 8, 100); k.run_for(0.3)             # (the list: the Executive in front, the click taken)
    pc0, nt = pix(*c0), [0]
    for r in range(24, 24 + 13 * 16):               # (the list left of it blanked: F5 must draw it)
        k.pc.wr(0xB800, (r & 3) * 0x2000 + (r >> 2) * 80, bytes(c0[0]))
    def th(pc):
        if pc.r('cs') == seg and pc.r('ip') == Y['mw_span'] and pc.rd(seg, Y['mw_kind'], 1)[0] == 3: nt[0] += 1
    k.hooks.append(th)
    k.key(0x3F00); k.run_for(1.0)                   # (F5: the list again)
    k.hooks.remove(th)
    A.point(k, 639, 399)
    rows = {y: l[:c0[0]] for y, l in k.ocr() if 24 <= y < 24 + 13 * 16}
    want = [n.split('.')[0] for n in k.exec_list()[k.u16('top'):k.u16('top') + 13]]
    seen = [n for n in want if any(r[:40].split()[:1] == [n] for r in rows.values())]
    check('the calculator moved so its top edge (y %d) crosses a list row; the Executive in front, F5: its list drawn '
          'again around the calculator, every name left of it there (%d of %d), the row its edge crosses drawn a row at a '
          'time (%d rows of glyphs), the calculator not touched' % (c0[1], len(seen), len(want), nt[0]), (c0[1] - 24) % 16
          and seen == want and nt[0] > 0 and pix(*c0) == pc0 and mb('mw_cur') == 0, (c0, seen, want, nt[0], pix(*c0) == pc0))
    # the form's outline (a box of lines) cut by the calculator: drawn left of it, taken off exactly
    A.click(k, (c0[0] + 5) * 8, c0[1] + 8); k.run_for(0.3)    # (the calculator in front: moved over the form)
    k.key(0x6E00, *([ktest.LEFT] * 28), ktest.ENTER); k.run_for(0.5)
    c0 = cwin()
    A.click(k, 8, 100); k.run_for(0.3)
    fy, pc0 = 236, pix(*c0)                         # (FORM_Y - 8: Device's and Subject's outlines below)
    def rest():
        """The screen from row fy to the band, but for the calculator."""
        return pix(0, fy, c0[0], 360 - fy) + pix(c0[0], c0[1] + c0[3], 80 - c0[0], 360 - c0[1] - c0[3])
    l0, nx = rest(), [0]
    def xh(pc):
        if pc.r('cs') == seg and pc.r('ip') == Y['mw_rect'] and pc.rd(seg, Y['mw_kind'], 1)[0] == 2: nx[0] += 1
    k.hooks.append(xh)
    k.key(ktest.TAB); k.run_for(0.3)
    l1, pc1 = rest(), pix(*c0)
    k.key(ktest.TAB, ktest.TAB); k.run_for(0.3)
    k.hooks.remove(xh)
    check('the calculator moved over the form (column %d); Tab in the Executive: Device\'s outline (a box) drawn around it, cut '
          '(%d pieces of its sides by the clipping), the calculator not touched; Tab x2: Title again, the outlines gone, the '
          'screen there as it was' % (c0[0], nx[0]), l1 != l0 and nx[0] > 0 and pc1 == pc0 and rest() == l0
          and pix(*c0) == pc0 and mb('mw_cur') == 0, (c0, l1 != l0, nx[0], pc1 == pc0, rest() == l0, k.band()))
    k.select('LODE.SYS')                            # (Return on it: only "nothing opens it")
    k.key(0x6E00, ktest.LEFT, ktest.LEFT, ktest.LEFT, ktest.ENTER); k.run_for(0.5)
    c1 = cwin()
    sx, sy = (c0[0] + 5) * 8, c0[1] + 8             # (its title strip)
    A.drag(k, sx, sy, sx - 80, sy + 40); k.run_for(0.3)
    c2, cc = cwin(), mb('mw_cur')
    k.key(ktest.ESC); k.run_for(0.5); k.settle()
    check('the Executive in front: CODE-F7, Left x3, Return don\'t move the calculator (%s), a session\'s window; its '
          'title strip dragged: the calculator in front (%d), not moved (%s): the press only brought it there; ESC: '
          'closed' % (c1[:2], cc, c2[:2]), c1 == c0 and cc == 1 and c2 == c0 and mb('mw_n') == 0, (c0, c1, cc, c2, mb('mw_n')))

def t_menu():
    print('== pop-up menus (UI API 8) in a window .RUN: saved under, modal; a drag lets the tasks run')
    k = boot('mt_menu.img', b'MULTITASK=1\r\n', 88, A.MENUTEST, mouse=True)
    seg, Y = mt_seg(k), k.Y
    mb = lambda n: k.pc.rd(seg, Y[n], 1)[0]
    au = Audit(k)
    k.select('MENUTEST.RUN'); k.key(ktest.ENTER); k.run_for(1.0)
    sy, base = A.run_syms('tests/MENUTEST.ASM'), k.pc.u16(seg, Y['mw_ses'] + SE_SIZE + SE_BASE)
    v16 = lambda n: k.pc.u16(k.useg, base + sy[n])
    rd = [0]
    def rh(pc):
        if pc.r('ip') == Y['redraw_all'] and pc.r('cs') == k.useg: rd[0] += 1
    k.hooks.append(rh)
    A.point(k, 100, 100); v0 = A.body(k)
    A.press(k, 100, 100, 2)
    lent, shown = (k.u16('wseg') != 0, k.rd('mn_lent', 1)[0]), A.has(k, 'Paste')
    k.key(ktest.DOWN); k.key(ktest.ENTER); k.run_for(0.3)
    check('MENUTEST a window .RUN (session %d; its window drawn again on a close: no save-under), a right click in it: the '
          'menu, which borrows the cache itself (%s); Down, Return: item 1, the cache given back, the screen as it was '
          'with no redraw (%d)' % (mb('mw_cur'), lent, rd[0]), mb('mw_cur') == 1 and mb('mw_n') == 1 and shown and lent == (True, 1)
          and v16('mres') == 1 and k.u16('wseg') == 0 and rd[0] == 0 and A.body(k) == v0, (mb('mw_cur'), lent, shown, v16('mres'), rd[0]))
    A.press(k, 100, 100, 2)
    k.key(0x6D00); k.run_for(0.5)
    f6 = mb('mw_cur'), A.has(k, 'Paste')
    A.press(k, 8, 200, 1); k.run_for(0.3)           # (left of its window: the Executive's)
    check('the menu open: CODE-F6 does nothing (%s: no other window in front, still open); a click on the Executive: no '
          'choice (%04Xh), the focus still MENUTEST\'s (%d), the menu gone' % (f6, v16('mres'), mb('mw_cur')),
          f6 == (1, True) and v16('mres') == 0xFFFF and mb('mw_cur') == 1 and not A.has(k, 'Paste'), (f6, v16('mres'), mb('mw_cur')))
    # a drag: UI_MOUSE waits at ..@ui_midle, where MTSPIN behind gets its turns.  (While it computes the
    # machine is never idle, so nothing here waits for a settle; 2000 ticks, 110 s, outlast the section.)
    k.hooks.remove(rh)
    A.click(k, 4, 340); k.run_for(0.3)              # (the Executive in front: CODE-P is its key)
    k.key(A.CODE['P']); k.run_for(1.0)
    typ(k, 'start /w mtspin.com 2000 tb.txt', 0.3); typ(k, 'start /w mtspin.com 2000 tc.txt', 0.3)
    typ(k, 'exit', 1.0); k.run_for(0.5)
    bclick(k, 4, 340)               # ("LCMD.COM ended" waits in the Executive: a click reads it)
    bclick(k, 300, 300)             # (MENUTEST's window: it in front again)
    cm, n0, d0 = mb('mw_cur'), len(au.ev), v16('dn')
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.06)      # (held over a tick, and a packet a tick, as below: at any
    for i in range(10):                               #  phase; 50 ms, under a tick, passed by the phase only)
        k.pc.mouse_move((4 if i % 2 else -4) & 0xFF, 0, 1); k.pc.run_for(0.06)
    nh = len(au.ev)
    k.pc.run_for(1.5)                               # (held still: the mouse sends nothing)
    hold = sum(1 for e in au.ev[nh:] if e['sw'] and e['task'] == 0)
    k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.3)
    mid = [e for e in au.ev[n0:] if e['cs'] == k.useg and e['ip'] == Y['..@ui_midle'] and e['sw']]
    tb0 = A.disk_file(k, 'TB.TXT')
    check('two MTSPINs started behind (CODE-P, START /W, EXIT), MENUTEST in front again (%d); a drag in it, the button '
          'held still 1.5 s (UI_MOUSE %d times): the MTSPINs switched to %d times from UI_MOUSE\'s wait, the drag given '
          'only its turn in three (%d turns: the mouse still, nothing brings it back sooner), every switch at a safe '
          'point' % (cm, v16('dn'), len(mid), hold), cm == 1 and v16('dn') >= 15 and len(mid) >= 10 and tb0 is None
          and not au.bad() and hold <= 12, (cm, v16('dn'), len(mid), tb0, au.bad()[:2], len(au.switches(n0)), hold))
    # the mouse moving: each packet brings MENUTEST back at the next tick (mt_mwant), ahead of MTSPIN
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.06)
    seen, n1 = 0, len(au.ev)
    for i in range(20):
        k.pc.mouse_move(2, 0, 1); k.pc.run_for(0.06)  # (a tick: the drag's, ahead of the MTSPINs)
        seen += k.pc.u16(k.useg, base + sy['d1'] + 2) == k.u16('mx')
    k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.3)
    sw1 = len(au.switches(n1))
    turns = collections.Counter(e['task'] for e in au.switches(n1) if e['task'])     # (the turns each MTSPIN had)
    check('... the mouse moving (a packet every tick, two MTSPINs computing behind): the drag has each position within the tick '
          '(%d of 20; without it every third tick), and both MTSPINs take turns in between (%s: the round goes on after the '
          'one a boost took the turn from)' % (seen, dict(turns)), seen >= 19 and sw1 >= 10 and len(turns) == 2
          and min(turns.values()) >= 4 and not au.bad() and A.disk_file(k, 'TB.TXT') is None and A.disk_file(k, 'TC.TXT') is None,
          (seen, sw1, dict(turns), au.bad()[:2]))
    bkey(k, ktest.ESC, ktest.ESC, t=0.5)
    check('ESC, ESC: MENUTEST ended, the Executive in front (MTSPIN still behind)', mb('mw_n') == 0 and k.rd('run_active', 1) == b'\x00' and not k.crashed,
          (mb('mw_n'), k.band()))

def t_clip():
    print('== the clipboard (UI_CLIP) with tasks: a window .RUN\'s, kept while tasks are parked and killed')
    k = boot('mt_clip.img', b'MULTITASK=1\r\n', 88, A.CLIPTEST, MTKL)
    seg, Y = mt_seg(k), k.Y
    mb = lambda n: k.pc.rd(seg, Y[n], 1)[0]
    sy = A.run_syms('tests/CLIPTEST.ASM')
    def start():
        k.select('CLIPTEST.RUN'); k.key(ktest.ENTER); k.run_for(1.0)
        return k.pc.u16(seg, Y['mw_ses'] + SE_SIZE + SE_BASE)
    v = lambda b, n: k.pc.u16(k.useg, b + sy[n])
    def put(b, data):
        k.pc.wr(v(b, 'bseg'), 0, data); k.pc.wr(k.useg, b + sy['plen'], struct.pack('<H', len(data))); k.key('P')
        return v(b, 'rcf')
    def get(b, room):
        k.pc.wr(v(b, 'bseg'), 16400, bytes(room)); k.pc.wr(k.useg, b + sy['gmax'], struct.pack('<H', room)); k.key('G')
        return bytes(k.pc.rd(v(b, 'bseg'), 16400, v(b, 'gcx'))) if not v(b, 'rcf') else None
    b = start()
    cf, h, ses = put(b, A.CLIPPAT[:2000]), k.u16('clip_h'), mb('mw_cur')
    k.key(ktest.ESC); k.run_for(0.5)
    sh = Shell(k)
    e0 = ems_used(k)
    sh.run('start /w mtkill.com f 100 ck.txt')      # (an EMS page its own, then waits for a line)
    k.run_for(0.6); e1 = ems_used(k)
    op = sh.run('park 1 && echo PARKED')
    ou = sh.run('unpark 1 && echo BACK')
    ok_ = sh.run('kill 1 && echo KILLED')
    k.run_for(0.5); e2 = ems_used(k)
    typ(k, 'exit', 1.0); k.settle()
    seen = False
    for _ in range(10):                             # ("LCMD.COM ended": a key reads it, once it shows)
        k.run_for(0.3)
        if 'Press any key' in k.band(): k.key(ktest.ESC); seen = True; break
    b = start()
    g, rec = get(b, 4000), k.rd('ems_h', 4, 4 * h) if h else b''
    k.key(ktest.ESC); k.run_for(0.5)
    check('CLIPTEST a window .RUN (session %d): 2000 bytes put (handle %d); ended; a task with an EMS page of its own '
          '(MTKILL F) started, parked, back and killed from LCMD (its page freed: %d, %d, %d in use); CLIPTEST again: the same '
          '2000 bytes, its handle as it was (%r: one page, nobody\'s)' % (ses, h, e0, e1, e2, rec.hex()),
          cf == 0 and ses == 1 and 0 < h < 32 and g == A.CLIPPAT[:2000] and k.u16('clip_h') == h and e1 > e0 and e2 == e0
          and rec[1] == 1 and rec[2:] == b'\0\0' and mb('mw_n') == 0 and 'PARKED' in op and 'BACK' in ou and 'KILLED' in ok_
          and seen and not k.crashed, (cf, ses, h, g and len(g), rec, e0, e1, e2, seen, op[-80:], ou[-80:], ok_[-80:], k.band()))

def t_write():
    print('== Write as a window (M8b): beside the calculator and another Write, moved and resized')
    TR = os.path.join(GOS, 'apps', 'TASKS.RUN')
    p = os.path.join(A.OUT, 'NOTES.TXT'); open(p, 'wb').write(A.TEXT)
    k = boot('mt_wr.img', b'MULTITASK=1\r\n', 88, TR, A.CALCRUN, A.WRITE, p, mouse=True)
    seg, Y = mt_seg(k), k.Y
    mb = lambda n: k.pc.rd(seg, Y[n], 1)[0]
    rec = lambda i, o: k.pc.u16(seg, Y['mw_ses'] + i * SE_SIZE + o)
    WS = A.run_syms('apps/WRITE.ASM')
    def win(i):
        """Session i's Write window: (W_COL, W_Y, W_W, W_H)."""
        a = rec(i, SE_BASE) + WS['win']
        return tuple(k.pc.u16(k.useg, a + o) for o in (0, 2, 4, 6))
    def at(t):
        """(column, y) where t is drawn (the pointer out of the way)."""
        A.point(k, 639, 399)
        return next(((l.index(t), y) for y, l in k.ocr() if t in l), None)
    free0 = A.free_paras(k)
    hdr = open(A.WRITE, 'rb').read(16)
    k.select('NOTES.TXT'); k.key(ktest.ENTER); k.run_for(1.0)
    w1, t1, s1 = win(1), at('jumps over'), at('Line 1 of 5')
    check('Return on NOTES.TXT with MULTITASK=1: Write in a window (%s), a session, its text inside it (%s) and its status '
          'line (%s), not the whole screen\'s; WRITE.RUN asks for API 8 (its menu and drags), with RF_WIN in its header' % (w1, t1, s1),
          mb('mw_n') == 1 and w1 == (2, 32, 76, 296) and t1 == (3, 72) and s1 == (4, 308) and A.has(k, 'Write: NOTES.TXT')
          and struct.unpack('<H', hdr[4:6])[0] == 8 and struct.unpack('<H', hdr[14:16])[0] == 1, (w1, t1, s1, A.screen(k)))
    k.key('Hello. ')
    k.key(A.CODE['K']); k.run_for(0.5)
    n2 = mb('mw_n')
    k.key('2+2'); k.key(ktest.ENTER); k.run_for(0.3)
    calc = A.has(k, '= 4')
    k.key(0x6D00); k.run_for(0.5)
    k.key('Hi '); k.run_for(0.3)
    check('CODE-K in Write: the calculator beside it (%d running), "2+2" there: = 4; CODE-F6: Write in front, its keys '
          'its own again' % n2, n2 == 2 and calc and mb('mw_cur') == 1 and A.has(k, 'Hello. Hi') and A.has(k, 'he quick brown'), A.screen(k))
    ev, dk = [], rec(1, SE_BASE) + WS['do_key']        # (what Write's do_key is given)
    def evh(pc):
        if pc.r('ip') == dk and pc.r('cs') == k.useg: ev.append(pc.r('ax'))
    k.hooks.append(evh)
    k.key(0x6F00, ktest.LEFT, ktest.LEFT, ktest.LEFT, ktest.LEFT, ktest.UP, ktest.UP, ktest.ENTER); k.run_for(0.5)
    w2, s2, b2 = win(1), at('Line 1 of 5'), k.band()
    ev2 = list(ev)
    check('CODE-F8, Left x4, Up x2, Return: 4 columns narrower, 2 rows shorter (%s), its status line up with it (%s), its own '
          'band still (%s), the Executive drawn again around it' % (w2, s2, b2[:1]),
          w2 == (2, 32, 72, 264) and s2 == (4, 276) and b2[:1] == ['Type, or choose a command (CODE-? lists them)']
          and A.has(k, 'Hello. Hi') and A.has(k, 'Kind') and ev2 == [0xFF04], (w2, s2, b2, [hex(e) for e in ev2], A.screen(k)))
    cx, cy = (2 + 72 - 1) * 8 + 4, 32 + 264 - 4
    A.drag(k, cx, cy, cx + 16, cy + 16); k.run_for(0.3)
    w3, s3, ev3 = win(1), at('Line 1 of 5'), ev[len(ev2):]
    check('its bottom-right corner dragged 2 columns right, 16 pixels down: that much bigger (%s), the status line '
          'down a row (%s); Write given EV_SIZE each time, not the key or the click' % (w3, s3), w3 == (2, 32, 74, 280)
          and s3 == (4, 292) and mb('mw_cur') == 1 and ev3 == [0xFF04], (w3, s3, [hex(e) for e in ev3], A.screen(k)))
    A.click(k, 4, 72); k.run_for(0.3)              # (left of it, on the Executive: row 1's height)
    sc, ce, be = at('Line 1 of 5'), mb('mw_cur'), k.band()
    A.click(k, 40 * 8, 292 + 8); k.run_for(0.3)    # (its status line: Write in front again)
    cw = mb('mw_cur')
    k.key(0x6F00, ktest.LEFT, ktest.UP, ktest.ESC); k.run_for(0.5)
    we = win(1)
    k.key(0x6F00, *([ktest.LEFT] * 70), ktest.ENTER); k.run_for(0.5)
    wm = win(1)
    k.key(0x6F00, *([ktest.RIGHT] * 50), ktest.ENTER); k.run_for(0.5)
    check('a click left of it, on the Executive: the Executive in front (M8c), its band (%s), no cursor moved (%s); a '
          'click on Write\'s status line: Write in front; CODE-F8, Left, Up, ESC: as it was (%s); CODE-F8, Left x70: no '
          'narrower than 24 columns (%s); Right x50: back (%s)' % (be[:1], sc, we, wm, win(1)), sc == (4, 292) and ce == 0
          and be[:1] == ['Select a file and confirm'] and cw == 1 and we == (2, 32, 74, 280) and wm == (2, 32, 24, 280)
          and win(1) == (2, 32, 74, 280), (sc, ce, be, cw, we, wm, win(1), A.screen(k)))
    # one row: the view follows the cursor there; then as big as the screen allows
    k.key(0x7500); k.run_for(0.3)                   # (Ctrl-End: line 5)
    k.key(0x6F00, *([ktest.UP] * 30), ktest.ENTER); k.run_for(0.5)
    w1r, s1r, l1r = win(1), at('Line 5 of 5'), A.has(k, 'last line') and not A.has(k, 'Tabbed line')
    k.key(A.K_PGUP); k.run_for(0.3)
    s1u, l1u = at('Line 4 of 5'), A.has(k, 'bed line') and not A.has(k, 'last line')
    k.key(0x6F00, *([ktest.RIGHT] * 10), *([ktest.DOWN] * 20), ktest.ENTER); k.run_for(0.5)
    wbig = win(1)
    k.key(0x6F00, *([ktest.LEFT] * 4), *([ktest.UP] * 3), ktest.ENTER); k.run_for(0.5)
    k.key(0x7700, *([ktest.RIGHT] * 10)); k.run_for(0.3)    # (Ctrl-Home, Right x10: where it was)
    check('CODE-F8, Up x30: no shorter than 72 rows, one text row (%s): line 5 shown, its status line (%s); PgUp: a page '
          'is a line (%s); Right x10, Down x20: no further than the screen\'s right edge and the band (%s)'
          % (w1r, s1r, s1u, wbig), w1r == (2, 32, 74, 72) and s1r == (4, 84) and l1r and s1u == (4, 84) and l1u
          and wbig == (2, 32, 78, 328) and win(1) == (2, 32, 74, 280), (w1r, s1r, l1r, s1u, l1u, wbig, win(1), A.screen(k)))
    n0 = len(ev)
    k.key(0x6E00, ktest.RIGHT, ktest.RIGHT, ktest.DOWN, ktest.DOWN, ktest.ENTER); k.run_for(0.5)
    w4, t4, ev4 = win(1), at('Hello. Hi'), ev[n0:]
    k.hooks.remove(evh)
    check('CODE-F7, Right x2, Down x2, Return: moved (%s), the text with it (%s); Write given EV_MOVED' % (w4, t4),
          w4 == (4, 40, 74, 280) and t4 == (5, 64) and ev4 == [0xFF02], (w4, t4, [hex(e) for e in ev4], A.screen(k)))
    b1 = rec(1, SE_BASE)
    wv1 = lambda n: k.pc.u16(k.useg, b1 + WS[n])
    def wtx():
        seg, gs, ge, cap = wv1('bseg'), wv1('gap_s'), wv1('gap_e'), wv1('cap')
        return bytes(k.pc.rd(seg, 0, gs)) + bytes(k.pc.rd(seg, ge, cap - ge))
    A.drag(k, 5 * 8 + 2, 64 + 8, 11 * 8 + 2, 64 + 8); k.run_for(0.3)
    sel = (k.pc.rd(k.useg, b1 + WS['mode'], 1)[0], wv1('anchor'), wv1('gap_s'))
    A.point(k, 20 * 8, 64 + 16 + 8); k.pc.mouse_move(0, 0, 2); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.run_for(0.5)
    mn = A.has(k, 'Substitute...  CODE-S')
    k.key(ktest.ENTER); k.run_for(0.3)
    er = wtx()
    k.key('Hello.'); k.run_for(0.3)
    A.drag(k, 5 * 8 + 2, 64 + 8, 11 * 8 + 2, 64 + 8); k.key(A.CODE['C'], ktest.ESC); k.run_for(0.3)    # (Hello. to the clipboard)
    A.point(k, 13 * 8 + 2, 64 + 16 + 8); k.pc.mouse_move(0, 0, 2); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.run_for(0.5)
    k.key(ktest.ESC); k.run_for(0.3)
    rg = wv1('gap_s')
    check('in its window, moved: a drag over "Hello." selects it (%s: a selection of its own, from 0 to 6); a right click '
          'in its text: its menu; Return (Erase): erased; typed again; a right click on its second row\'s 9th column, ESC: '
          'the cursor there (%d), the window\'s text area, not the screen\'s' % (sel, rg), sel == (1, 0, 6) and mn
          and er.startswith(b' Hi The quick') and wtx().startswith(b'Hello. Hi The quick') and mb('mw_cur') == 1 and rg == 30 + 8,
          (sel, mn, er[:20], wtx()[:20], rg, A.screen(k)))
    k.key(0x7700, *([ktest.RIGHT] * 6)); k.run_for(0.3)    # (Ctrl-Home, Right x6: where it was)
    k.key(A.CODE['W']); k.run_for(1.0)
    n5, c5 = mb('mw_n'), mb('mw_cur')
    w5 = win(c5)
    check('CODE-W in Write: another Write, a new file (%d running, session %d), opening lower and to the right (%s), not '
          'over the first' % (n5, c5, w5), n5 == 3 and c5 == 3 and w5 == (6, 64, 72, 264) and A.has(k, 'Write: (new)')
          and win(1) == w4, (n5, c5, w5, A.screen(k)))
    k.key(A.CODE['X']); k.run_for(0.5)
    xf = A.has(k, 'Include a file') and k.band()[:1] == ['Transfer: Fill in form and confirm']
    k.key(ktest.ESC); k.run_for(0.3)
    k.key(A.CODE['T']); k.run_for(0.5)
    bt = k.band()
    k.key(ktest.ENTER); k.run_for(0.3)
    check('CODE-X: Write\'s Transfer (with MULTITASK=1); CODE-T: the tasks\', which don\'t fit beside two Writes and the '
          'calculator: "%s" (the segment\'s room, really out)' % bt[:1], xf and bt[:1] == ["TASKS.RUN doesn't fit: close a window first"]
          and mb('mw_n') == 3, (xf, bt, A.screen(k)))
    k.key(A.CODE['V'], 'abc'); k.key(A.CODE['Q']); k.run_for(0.3); k.key(ktest.ENTER); k.run_for(0.3)
    k.key('W2.TXT'); k.key(ktest.ENTER); k.run_for(1.0)
    n6, c6, d6 = mb('mw_n'), mb('mw_cur'), A.disk_file(k, 'W2.TXT')
    check('in the new Write, CODE-V (what the first Write copied, through the clipboard), "abc", CODE-Q, Return, a name, Return: saved (%r), its window gone, the first Write in '
          'front (%d running, session %d)' % (d6, n6, c6), d6 == b'Hello.abc' and n6 == 2 and c6 == 1
          and not A.has(k, 'Write: (new)') and A.has(k, 'Write: NOTES.TXT'), (d6, n6, c6, A.screen(k)))
    k.key(A.CODE['T']); k.run_for(0.5)
    nt, tk = mb('mw_n'), A.has(k, 'Tasks')
    k.key(ktest.ESC); k.run_for(0.5)
    k.key(A.CODE['W']); k.run_for(1.0)
    w9, n9 = win(mb('mw_cur')), mb('mw_n')
    A.click(k, (w9[0] + w9[2] - 2) * 8 + 4, w9[1] + 8); k.run_for(0.5)
    bq = k.band()
    k.key(ktest.ENTER); k.run_for(0.5)
    check('CODE-T now: the tasks fit, in the slot the second Write left (%d running); ESC.  CODE-W, then a click on the '
          'new Write\'s close box: as ESC, "%s", Return: gone (%d, then %d running), the first in front'
          % (nt, bq[:1], n9, mb('mw_n')), nt == 3 and tk and n9 == 3
          and bq[:1] == ['Cancel: Confirm to exit without saving (unchanged)'] and mb('mw_n') == 2 and mb('mw_cur') == 1,
          (nt, tk, n9, w9, bq, mb('mw_n'), mb('mw_cur'), A.screen(k)))
    k.wr('saver_t', struct.pack('<H', 36))
    for _ in range(40):
        k.pc.run_for(0.25)
        if not A.has(k, 'Hello. Hi'): break
    dark = not A.has(k, 'Hello. Hi')
    k.wr('saver_t', struct.pack('<H', 5460))
    k.key(ktest.DOWN); k.run_for(0.5)
    s8, b8 = at('Line 1 of 5'), k.band()
    check('the saver with Write and the calculator (behind it) open, then a key: the Executive and Write\'s text back, '
          'its status line where it was (%s), its own band (%s), not the Executive\'s' % (s8, b8[:1]), dark
          and A.has(k, 'Hello. Hi') and A.has(k, 'LCMD') and mb('mw_n') == 2 and s8 == (6, 300)
          and b8[:1] == ['Type, or choose a command (CODE-? lists them)'], (s8, b8, A.screen(k)))
    k.key(A.CODE['Q']); k.run_for(0.3); k.key(ktest.ENTER); k.run_for(1.0)
    d7, n7, c7 = A.disk_file(k, 'NOTES.TXT'), mb('mw_n'), mb('mw_cur')
    k.key(0x6D00); k.run_for(0.5)
    c7b = mb('mw_cur')
    k.key(ktest.ESC); k.run_for(0.5); k.settle()
    check('CODE-Q, Return in it: NOTES.TXT saved (%r...), the calculator still open (%d running), the Executive in front '
          '(%d: CODE-F6 put the calculator last, M8c); CODE-F6: the calculator (%d); ESC: the Executive, nothing loaded, '
          'the UI block as before' % (d7[:16], n7, c7, c7b), d7.startswith(b'Hello. Hi The quick brown fox\r\n')
          and n7 == 1 and c7 == 0 and c7b == 2 and mb('mw_n') == 0 and k.rd('run_active', 1) == b'\x00' and A.free_paras(k) == free0
          and A.has(k, 'Select a file and confirm') and not k.crashed, (d7, n7, A.free_paras(k), free0, A.screen(k)))
    k = boot('mt_wr0.img', b'MULTITASK=1\r\n', 88, A.WRITE, mt=None)
    k.key(A.CODE['W']); k.run_for(1.0)
    check('without LODEMT.SYS (the switch off), CODE-W: Write has the whole screen, as before (its title in the title '
          'bar, its status line at y 340)', any(y == 0 and 'Write: (new)' in l for y, l in k.ocr())
          and any(y == 340 and 'Line 1 of 1' in l for y, l in k.ocr()), A.screen(k))

def t_paintw():
    """Paint as a window (W1): with MULTITASK=1 a window .RUN (RF_WIN), its
    canvas a 1:1 view of the 640 x 400 picture (centred at first), moved by
    the arrows, PgUp/PgDn and Ctrl-Left/Right; strokes clamped to the canvas,
    fills following the picture's lines; C as the model has it, outside the
    view too; W_DRAW after another window, a move, a resize; CODE-X.  W2: a
    drag on the frame moves the view; CODE-F the whole screen, and back."""
    print('== Paint as a window (W1): a view of the picture')
    PAINT = os.path.join(GOS, 'apps', 'PAINT.RUN')
    TR = os.path.join(GOS, 'apps', 'TASKS.RUN')
    rows = [bytes(((x * 7 + y * 3) ^ (y >> 2)) & 0xFF for x in range(80)) for y in range(400)]
    pic = os.path.join(A.OUT, 'PIC.BMP'); open(pic, 'wb').write(A.mkbmp(640, 400, rows))
    k = boot('mt_pw.img', b'MULTITASK=1\r\n', 88, PAINT, TR, A.CALCRUN, pic, mouse=True)
    seg, Y = mt_seg(k), k.Y
    mb = lambda n: k.pc.rd(seg, Y[n], 1)[0]
    rec = lambda i, o: k.pc.u16(seg, Y['mw_ses'] + i * SE_SIZE + o)
    PS = A.run_syms('apps/PAINT.ASM')
    def pv(n, i=1): return k.pc.u16(k.useg, rec(i, SE_BASE) + PS[n])
    def pb(n, i=1): return k.pc.rd(k.useg, rec(i, SE_BASE) + PS[n], 1)[0]
    def win(i=1): return tuple(k.pc.u16(k.useg, rec(i, SE_BASE) + PS['win'] + o) for o in (0, 2, 4, 6))
    def C(i=1):
        c = k.pc.rd(pv('segc', i), 0, 32000)
        return [bytes(c[(399 - y) * 80:(400 - y) * 80]) for y in range(400)]
    def g(i=1): return {n: pv(n, i) for n in ('cx0', 'cw', 'cy0', 'chh', 'vx', 'vy', 'clx0', 'clx1', 'cly0', 'cly1', 'pph')}
    def view_bad(i=1):
        """Canvas lines that aren't C's view (the pointer moved out of the way first)."""
        A.point(k, 639, 0); k.run_for(0.2)                     # (the title bar's corner: off the canvas and the band)
        q, v, c = g(i), A.vram(k), C(i)
        return [y for y in range(q['chh']) if A.vrow(v, q['cy0'] + y)[q['cx0']:q['cx0'] + q['cw']]
                != c[q['vy'] + y][q['vx']:q['vx'] + q['cw']]][:4]
    def band():
        A.point(k, 639, 0); k.run_for(0.2)
        return ' | '.join(l for l in k.band() if l)
    m = A.PaintModel(rows)
    def stroke(tool, x0, y0, x1, y1, pat=0, keys=True):
        """A drag on the screen; the model's stroke at the clamped points, in picture pixels.  keys=False: the
        tool and pattern as they are (no key first, which would mend the band)."""
        q = g()
        if keys: k.key(tool); k.key(str(pat + 1))
        A.drag(k, x0, y0, x1, y1); k.run_for(0.2)
        cl = lambda x, lo, hi: max(lo, min(hi, x))
        ox, oy = q['vx'] * 8 - q['clx0'], q['vy'] - q['cly0']
        if pb('ses') == 0: ox = oy = 0                    # (zoomed: the screen is the picture)
        pts = [(cl(x, q['clx0'], q['clx1']) + ox, cl(y, q['cly0'], q['cly1']) + oy) for x, y in A.drag_pts(x0, y0, x1, y1)]
        m.clip = (q['clx0'] + ox, q['cly0'] + oy, q['clx1'] + ox, q['cly1'] + oy)
        m.stroke(tool, pts, pat)
    hdr = open(PAINT, 'rb').read(16)
    k.select('PIC.BMP'); k.key(ktest.ENTER); k.run_for(1.0)
    q = g()
    check('Return on PIC.BMP with MULTITASK=1: Paint in a window (%s), a session; PAINT.RUN API 6 with RF_WIN; strokes by '
          'UI_MOUSE; the view centred (vx %d, vy %d), the canvas inside the frame under the title (%d, %d, %d x %d)'
          % (win(), q['vx'], q['vy'], q['cx0'], q['cy0'], q['cw'], q['chh']),
          mb('mw_n') == 1 and win() == (2, 32, 76, 328) and struct.unpack('<H', hdr[4:6])[0] == 6
          and struct.unpack('<H', hdr[14:16])[0] == 1 and pb('ses') == 1 and pb('umouse') == 1
          and (q['cx0'], q['cw'], q['cy0'], q['chh'], q['vx'], q['vy']) == (3, 74, 52, 307, 3, 46)
          and (q['clx0'], q['clx1'], q['cly0'], q['cly1'], q['pph']) == (24, 615, 52, 358, 2), (win(), q))
    check('... its title "Paint: PIC.BMP", C the file, the canvas C\'s view of it; the band: the hint, and where the view is',
          A.has(k, 'Paint: PIC.BMP') and C() == rows and not view_bad()
          and band().startswith('Paint: draw with the mouse.  Tab: tools.  CODE-?: help |')
          and band().endswith('| View: from 24, 46 of 640 x 400'),
          (A.has(k, 'Paint: PIC.BMP'), C() == rows, view_bad(), band()))
    A.drag(k, 100, 100, 200, 150); k.run_for(0.2)
    check('... showing a file: a drag doesn\'t draw (until Return)', C() == rows and not view_bad(), view_bad())
    A.drag(k, 18, 200, 18, 184); k.run_for(0.2)
    p0 = (g()['vx'], g()['vy'], view_bad())
    A.drag(k, 18, 184, 18, 200); k.run_for(0.2)
    check('... a drag up on its frame moves the view (pans) there too: 16 lines down the picture (vy %d), drawn; down '
          'again: back (vy %d)' % (p0[1], g()['vy']), p0 == (3, 62, []) and (g()['vx'], g()['vy']) == (3, 46)
          and C() == rows and not view_bad(), (p0, g()))
    k.key(ktest.ENTER)
    # strokes: inside; past the canvas's right and bottom (clamped); a fill with the slant (phase 2);
    # the brush past its left edge (cut there)
    stroke('P', 100, 100, 300, 200)
    stroke('L', 200, 120, 639, 399)
    stroke('F', 40, 60, 200, 150, 7)
    stroke('B', 40, 200, 0, 300)
    check('strokes in the window: C exactly as the model, at the view\'s offset (outside the view: as it was); points '
          'past the canvas clamped to it, the brush cut at its edge, the slant fill on the picture\'s lines (pph 2)',
          C() == [bytes(l) for l in m.l] and not view_bad(), (A.diff([bytes(l) for l in m.l], C()), view_bad()))
    k.key('P')
    pans = []
    for d in ((18, 200, 18, 260), (620, 150, 620, 104), (300, 359, 312, 359), (312, 359, 308, 359), (300, 359, 340, 359),
              (340, 359, 316, 359), (300, 360, 340, 330)):
        A.drag(k, *d); k.run_for(0.2)
        pans.append((g()['vx'], g()['vy'], g()['pph'], view_bad()))
        if len(pans) == 1: b0 = band()
    check('drags on the window\'s frame pan, the picture following the hand: the left edge 60 down (vy 46 -> 0, kept '
          'inside), the right edge 46 up (46), the bottom rule 12 right (vx 3 -> 2, to the nearest byte), 4 left (3), '
          '40 right (0, kept inside), 24 left (3); a drag from the band\'s first line: no pan; drawn each '
          'time, the band saying where (%s); no stroke (clamped to the canvas, one would draw along its edge)' % pans,
          [p[:2] for p in pans] == [(3, 0), (3, 46), (2, 46), (3, 46), (0, 46), (3, 46), (3, 46)]
          and pans[0][2] == 4 and pans[1][2] == 2 and win() == (2, 32, 76, 328)
          and not any(p[3] for p in pans) and b0.endswith('View: from 24, 0 of 640 x 400')
          and C() == [bytes(l) for l in m.l], (pans, b0, A.diff([bytes(l) for l in m.l], C())))
    # the view moved: the arrows, PgDn, Ctrl-Left; kept inside the picture
    k.key(ktest.RIGHT); k.key(ktest.RIGHT); k.key(ktest.DOWN); k.run_for(0.3)
    a = (g()['vx'], g()['vy'], view_bad(), band())
    k.key(0x5100); k.key(0x7300); k.run_for(0.3)          # (PgDn, Ctrl-Left)
    b = (g()['vx'], g()['vy'], view_bad(), band())
    check('Right x2, Down: the view 16 pixels right (vx 3 -> 6 bytes, kept inside), 16 down (%s); PgDn, Ctrl-Left: to '
          'the bottom (vy 93) and the left (%s); the canvas C\'s view each time, the band saying where'
          % (a[:2], b[:2]), a[:3] == (6, 62, []) and a[3].endswith('View: from 48, 62 of 640 x 400')
          and b[:3] == (0, 93, []) and b[3].endswith('View: from 0, 93 of 640 x 400'), (a, b))
    stroke('F', 30, 300, 300, 358, 7)
    stroke('E', 300, 60, 400, 200)
    pre = [bytes(l) for l in m.l]
    check('a fill and the eraser after it (pph %d now): C as the model' % g()['pph'],
          C() == pre and not view_bad(), (A.diff(pre, C()), view_bad()))
    def timer(a, b):
        """Simulated µs from Paint's a's entry to b's entry, each time (session 1's slot)."""
        got, t = [], {}
        pa, pb_ = rec(1, SE_BASE) + PS[a], rec(1, SE_BASE) + PS[b]
        def h(pc):
            if pc.r('cs') != k.useg: return
            ip = pc.r('ip')
            if ip == pa: t['a'] = pc.us
            elif ip == pb_ and 'a' in t: got.append(pc.us - t.pop('a'))
        k.hooks.append(h)
        return got
    tc, tu, ts = timer('commit_view', 'main'), timer('k_undo', 'main'), timer('sync_u', 'tool_do')
    stroke('R', 100, 100, 250, 250)
    k.key('U'); k.run_for(0.3)
    check('U: undone, C the picture before the box, the canvas showing it', C() == pre and not view_bad(), (A.diff(pre, C()), view_bad()))
    print('     (µs: a stroke\'s start in a window %s, its end %s, undo and the view %s)' % (ts, tc, tu))
    check('speed in a window: a stroke\'s start (U = C where they may differ: the last view) and its end (the canvas '
          'into C) each in 16 ms or less, as the whole screen\'s end; undo and the view shown in 16 ms or less',
          ts and max(ts) <= 16000 and tc and tc[-1] <= 16000 and tu and tu[-1] <= 16000, (ts, tc, tu))
    k.key('U'); k.run_for(0.3)
    post = [bytes(l) for l in m.l]
    check('... U again: the box back', C() == post and not view_bad(), view_bad())
    # Invert (C and U may then differ anywhere), a stroke, undo: the inverted picture; again: the stroke
    k.key('I'); k.run_for(0.3)
    m.l = [bytearray(x ^ 0xFF for x in l) for l in m.l]
    inv = [bytes(l) for l in m.l]
    stroke('P', 100, 300, 300, 120)
    k.key('U'); k.run_for(0.3)
    a1 = (C() == inv, view_bad())
    k.key('U'); k.run_for(0.3)
    check('I (inverted), a stroke, U: the inverted picture (C and U kept apart everywhere after I); U again: the stroke',
          a1 == (True, []) and C() == [bytes(l) for l in m.l] and not view_bad(), (a1, A.diff([bytes(l) for l in m.l], C())))
    k.key(ktest.F1 if hasattr(ktest, 'F1') else 0x3B00); k.run_for(0.5)
    hs = A.screen(k)
    k.key(ktest.ESC); k.run_for(0.5)
    check('F1 in a window: the help has the view\'s keys (Arrows PgUp PgDn, Ctrl-Left Ctrl-Right), the frame\'s drag, '
          'the zoom (CODE-F) and Transfer as CODE-X; ESC: the view drawn again', 'move the view' in hs
          and 'Ctrl-Left  Ctrl-Right' in hs and 'A drag on the frame      move the view' in hs
          and 'CODE-F                   the whole screen, and back' in hs
          and 'CODE-X                   Transfer' in hs and 'CODE-T                   Transfer' not in hs and not view_bad(), hs)
    # another window over it and closed: W_DRAW draws the view again (no save-under with sessions)
    k.key(A.CODE['K']); k.run_for(0.5)
    n2 = mb('mw_n')
    k.key(ktest.ESC); k.run_for(0.5)
    check('CODE-K: the calculator over it (%d sessions); ESC: closed, Paint\'s view drawn again' % n2,
          n2 == 2 and mb('mw_n') == 1 and not view_bad(), view_bad())
    k.key(A.CODE['T']); k.run_for(0.5)
    t = A.has(k, 'Tasks')
    k.key(ktest.ESC); k.run_for(0.5)
    check('CODE-T: the tasks (not Transfer, which is CODE-X in a window); ESC: Paint again',
          t and mb('mw_n') == 1 and not view_bad(), (t, A.screen(k)))
    # resized and moved: the canvas follows, the view kept inside the picture
    k.key(0x6F00, ktest.LEFT, ktest.LEFT, ktest.LEFT, ktest.LEFT, ktest.UP, ktest.UP, ktest.ENTER); k.run_for(0.5)
    w2, q2 = win(), g()
    check('CODE-F8, Left x4, Up x2: the window 4 columns narrower, 2 rows shorter (%s); the canvas %d x %d, the view '
          'kept inside the picture (vx %d, vy %d) and drawn' % (w2, q2['cw'], q2['chh'], q2['vx'], q2['vy']),
          w2 == (2, 32, 72, 296) and (q2['cw'], q2['chh'], q2['vx'], q2['vy']) == (70, 275, 0, 93) and not view_bad(),
          (w2, q2, view_bad()))
    k.key(0x5100); k.key(0x7400); k.run_for(0.3)          # (PgDn, Ctrl-Right: the view at its limits)
    q4 = g()
    k.key(0x6F00, ktest.RIGHT, ktest.RIGHT, ktest.RIGHT, ktest.RIGHT, ktest.DOWN, ktest.DOWN, ktest.ENTER); k.run_for(0.5)
    q5 = g()
    check('the view at the smaller canvas\'s limits (vx %d, vy %d), the window made big again (%s): the view kept inside '
          'the picture (vx %d, vy %d), drawn, the band saying where' % (q4['vx'], q4['vy'], win(), q5['vx'], q5['vy']),
          (q4['vx'], q4['vy']) == (10, 125) and win() == (2, 32, 76, 328) and (q5['vx'], q5['vy']) == (6, 93)
          and not view_bad() and band().endswith('View: from 48, 93 of 640 x 400'), (q4, q5, band()))
    k.key(0x6F00, ktest.LEFT, ktest.LEFT, ktest.LEFT, ktest.LEFT, ktest.UP, ktest.UP, ktest.ENTER); k.run_for(0.5)
    # the screen saver over it, then a key: the view drawn again (W_DRAW, from redraw_all)
    entered, sa = [], Y['saver']
    hk = lambda pc: entered.append(1) if pc.r('cs') == k.useg and pc.r('ip') == sa else None
    k.hooks.append(hk)
    k.wr('saver_t', struct.pack('<H', 36))
    for _ in range(40):
        k.run_for(0.25)
        if entered: break
    k.run_for(1.0)
    q6, v6, c6 = g(), A.vram(k), C()                      # (no pointer moved: that would end it)
    over = any(A.vrow(v6, q6['cy0'] + y)[q6['cx0']:q6['cx0'] + q6['cw']] != c6[q6['vy'] + y][q6['vx']:q6['vx'] + q6['cw']]
               for y in range(q6['chh']))
    k.wr('saver_t', struct.pack('<H', 5460)); k.hooks.remove(hk)
    k.key(ktest.DOWN); k.run_for(0.5)                     # (the key wakes it, nothing more)
    check('the screen saver (over the canvas), then a key: Paint\'s view drawn again, its band too', bool(entered) and over
          and not view_bad() and band().endswith('View: from 48, 93 of 640 x 400'), (bool(entered), over, view_bad(), band()))
    # the tools' window over the canvas, a tool chosen: closed, the view drawn again
    k.key(ktest.TAB); k.run_for(0.3)
    tw = A.has(k, 'Tools')
    k.key('L'); k.run_for(0.3)
    check('Tab: the tools\' window over the canvas; L: the line chosen, the window closed, the view drawn again',
          tw and not A.has(k, 'Tools') and pv('tool') == 3 and not view_bad(), (tw, view_bad()))
    A.drag(k, 200, 36, 216, 40); k.run_for(0.5)
    w3, q3 = win(), g()
    prf = [bytes(l) for l in m.l]
    stroke('F', 100, 150, 300, 250, 7)
    check('its title dragged 2 columns right, 4 lines down (%s): the canvas there (%d, %d), pph %d; a slant fill: C as '
          'the model' % (w3, q3['cx0'], q3['cy0'], q3['pph']), w3 == (4, 36, 72, 296) and (q3['cx0'], q3['cy0'], q3['pph']) == (5, 56, 5)
          and C() == [bytes(l) for l in m.l] and not view_bad(), (w3, q3, A.diff([bytes(l) for l in m.l], C()), view_bad()))
    # Transfer is CODE-X in a window: saved, the title the new name
    k.key(A.CODE['X']); k.key('drawn'); k.key(ktest.ENTER); k.run_for(1.0)
    check('CODE-X, "drawn": DRAWN.BMP, the model\'s picture in Shift-PrtSc\'s format; the title "Paint: DRAWN.BMP"',
          A.disk_file(k, 'DRAWN.BMP') == m.bmp() and A.has(k, 'Paint: DRAWN.BMP') and not view_bad(),
          (len(A.disk_file(k, 'DRAWN.BMP') or b''), A.screen(k)))
    # W2: CODE-F, the whole screen (the window itself made so), and back
    def scr_bad():
        """The screen's lines, all 400, against C (but under the pointer)."""
        A.point(k, 639, 0); k.run_for(0.2)
        v = A.vram(k)
        return A.off_pointer(k, [A.vrow(v, y) for y in range(400)], C())
    tob = lambda: k.pc.rd(k.useg, Y['title_on'], 1)[0]   # (the session in front's)
    wf = lambda: (k.pc.u16(k.useg, rec(1, SE_BASE) + PS['win'] + 8), k.pc.u16(k.useg, rec(1, SE_BASE) + PS['win'] + 12))
    w0, t0, v0 = win(), tob(), (g()['vx'], g()['vy'])
    k.key(A.CODE['F']); k.run_for(0.5)
    q = g()
    check('CODE-F: the window the whole screen down to the band (%s), no title strip nor flags (%s), ses 0; the screen all '
          'of C (the band\'s lines too: Paint in front draws them, and the top lines), the canvas the whole screen (pph 0); its session\'s title off (title_on %d -> %d: no '
          'clock over the picture)' % (win(), wf(), t0, tob()), win() == (0, 0, 80, 360) and wf() == (0, 0)
          and pb('ses') == 0 and scr_bad() is None and (q['clx0'], q['clx1'], q['cly0'], q['cly1'], q['pph']) == (0, 639, 0, 399, 0)
          and (t0, tob()) == (1, 0), (win(), wf(), scr_bad(), q, t0, tob()))
    pre = [bytes(l) for l in m.l]
    k.key('U'); k.run_for(0.3)
    zu = (C() == prf, scr_bad())
    k.key('U'); k.run_for(0.3)
    check('zoomed, U first: the window\'s last stroke (the slant fill) undone, all of the picture shown; U again: back',
          zu == (True, None) and C() == pre and scr_bad() is None, (zu, scr_bad()))
    tz = timer('commit', 'main')
    stroke('L', 100, 20, 500, 390)
    mid = [bytes(l) for l in m.l]
    stroke('F', 600, 340, 630, 399, 7)
    check('zoomed: a line across the top and the band, a slant fill to the bottom: C as the model in screen co-ordinates, '
          'the screen C; its end the whole screen\'s (the commit: %s µs, 16 ms or less)' % tz,
          C() == [bytes(l) for l in m.l] and scr_bad() is None and tz and max(tz) <= 16000,
          (A.diff([bytes(l) for l in m.l], C()), scr_bad(), tz))
    zl = [bytes(l) for l in m.l]
    k.key('U'); k.run_for(0.3)
    u1 = (C() == mid, scr_bad())
    k.key('U'); k.run_for(0.3)
    check('zoomed, U: the fill undone, the screen C; U again: back', u1 == (True, None) and C() == zl and scr_bad() is None,
          (u1, scr_bad()))
    k.key(ktest.TAB); k.run_for(0.3)
    tw = A.has(k, 'Tools')
    k.key('P'); k.run_for(0.5)
    a = (tw, scr_bad(), tob())
    k.key(A.CODE['K']); k.run_for(0.5)
    n2 = mb('mw_n')
    k.key(ktest.F1 if hasattr(ktest, 'F1') else 0x3B00); k.run_for(0.5); k.key(ktest.ESC); k.run_for(0.5)
    tc_ = tob()                                           # (the calculator's, in front: its redraw drew Paint's)
    A.point(k, 639, 0); k.run_for(0.2)
    cb = (A.vrow(A.vram(k), 360) == b'\xff' * 80, C()[360] != b'\xff' * 80)   # (the band's first line, lit: not C's)
    k.key(ktest.ESC); k.run_for(0.5)
    b2, bt = scr_bad(), band()
    k.key('P'); k.run_for(0.3)
    check('zoomed: Tab\'s tools window over it, P: closed, the whole screen drawn again; CODE-K\'s calculator (%d '
          'sessions; F1 and ESC there: its own title left on, %d, and its band, as Paint\'s window is drawn from its '
          'redraw: the picture above the band only), ESC: the '
          'picture drawn again but for the band, Paint\'s (KMW\'s, for the one in front: first bad line %s), until a '
          'key; Paint\'s title still off each time (the Executive\'s base drew it: UI_CLS)' % (n2, tc_, b2),
          a == (True, None, 0) and n2 == 2 and tc_ == 1 and cb == (True, True) and mb('mw_n') == 1 and b2 and b2[0] >= 360
          and bt.endswith('The whole picture.  CODE-F: back to the window') and scr_bad() is None and tob() == 0,
          (a, n2, tc_, cb, b2, bt, scr_bad(), tob()))
    k.key(0x6D00); k.run_for(0.5)                         # (CODE-F6: the Executive in front)
    ex = (mb('mw_cur'), A.vrow(A.vram(k), 360) == b'\xff' * 80)
    k.key(0x6D00); k.run_for(0.5)                         # (and Paint again)
    bz = band()
    prp = [bytes(l) for l in m.l]
    for y in range(16): k.pc.wr(0xB800, (y & 3) * 0x2000 + (y >> 2) * 80, b'\x55' * 80)    # (as another's clock)
    stroke('P', 200, 300, 400, 380, keys=False)
    check('zoomed, CODE-F6: the Executive in front, its band shown (Paint\'s window stops above it); CODE-F6 again: '
          'Paint, its band over the picture ("%s"), and something over its top 16 lines (as another session\'s clock); '
          'a stroke over it (no key first): both mended first, C as the model, the screen C' % bz, ex == (0, True)
          and bz.endswith('The whole picture.  CODE-F: back to the window')
          and C() == [bytes(l) for l in m.l] and scr_bad() is None, (ex, bz, A.diff([bytes(l) for l in m.l], C()), scr_bad()))
    # zoomed, a question waiting (ESC with changes), the saver over it and woken: the question still in the band
    k.key(ktest.ESC); k.run_for(0.5)
    entered, sa = [], Y['saver']
    hk = lambda pc: entered.append(1) if pc.r('cs') == k.useg and pc.r('ip') == sa else None
    k.hooks.append(hk)
    k.wr('saver_t', struct.pack('<H', 36))
    for _ in range(40):
        k.run_for(0.25)
        if entered: break
    k.run_for(1.0)
    k.wr('saver_t', struct.pack('<H', 5460)); k.hooks.remove(hk)
    k.key(ktest.DOWN); k.run_for(0.5)                     # (the key wakes it, nothing more)
    sq = (bool(entered), band(), pb('tz'), pb('quit'))
    k.key(ktest.ESC); k.run_for(0.5)                      # (no: Paint goes on)
    check('zoomed, ESC (changes: the question), the screen saver over it, a key: the question still in the band (the '
          'window drawn above it only: "%s"); ESC: Paint goes on, all of the picture drawn, its title off again'
          % sq[1], sq[0] and 'Cancel: Confirm to quit without saving' in sq[1] and sq[2:] == (1, 0)
          and pb('quit') == 0 and pb('tz') == 0 and scr_bad() is None and tob() == 0, (sq, pb('tz'), scr_bad(), tob()))
    k.key(A.CODE['X']); k.key('zoomed'); k.key(ktest.ENTER); k.run_for(1.0)    # (typed first: replaces the name)
    check('zoomed, CODE-X "zoomed": ZOOMED.BMP, the model\'s picture; no title on the screen, the screen C',
          A.disk_file(k, 'ZOOMED.BMP') == m.bmp() and scr_bad() is None and pb('ses') == 0,
          (len(A.disk_file(k, 'ZOOMED.BMP') or b''), scr_bad()))
    k.key(A.CODE['F']); k.run_for(0.5)
    zb = (win(), pb('ses'), tob(), tuple(pv(n) for n in ('dy0', 'dy1', 'dx0', 'dx1')), (g()['vx'], g()['vy']))
    check('CODE-F again: the window as it was (%s), its title the new name, the view where it was (%s), drawn, the band '
          'saying where; the title back on (the clock); D the whole picture (strokes zoomed: %s)' % (zb[0], zb[4], zb[3]),
          zb[:3] == (w0, 1, 1) and zb[3] == (0, 400, 0, 80) and zb[4] == v0 and A.has(k, 'Paint: ZOOMED.BMP')
          and not view_bad() and band().endswith('View: from %d, %d of 640 x 400' % (v0[0] * 8, v0[1]))
          and wf()[0] != 0 and wf()[1] == 7, (zb, v0, A.has(k, 'Paint: ZOOMED.BMP'), view_bad(), band(), wf()))
    zp = [bytes(l) for l in m.l]
    k.key('U'); k.run_for(0.3)
    ou = (C() == prp, view_bad())
    k.key('U'); k.run_for(0.3)
    check('back in the window, U first: the last zoomed stroke undone, the view drawn; U again: back',
          ou == (True, []) and C() == zp and not view_bad(), (ou, view_bad()))
    stroke('R', 100, 100, 300, 250)
    k.key('U'); k.run_for(0.3)
    check('a stroke in the window after the zoom, U: the picture before it, all of it (U as C where the zoom changed '
          'them: D)', C() == zp and not view_bad(), (A.diff(zp, C()), view_bad()))
    k.key('U'); k.run_for(0.3)
    # CODE-Tab away to a full-screen task and back (paint.md §8's planned check, as it is since W1: Paint's strokes
    # come by UI_MOUSE, so the UI's own INT 33h state is task 0's, saved and put back by MT).  Task 0's hot spot,
    # masks made its own (after the first task's start, which saves it too); LCMD's (a copy, its pointer hidden) changed while it is in front: back
    # in task 0, task 0's again, not LCMD's.
    ST = ('m33_xmin', 'm33_xmax', 'm33_ymin', 'm33_ymax', 'm33_rx', 'm33_ry', 'm33_cnt', 'm33_hx', 'm33_hy', 'm33_ts', 'm33_tc')
    mst = lambda: (tuple(k.u16(n) for n in ST), bytes(k.rd('m33_gm', 64)))
    keep = mst()
    put = lambda hx, g: (k.wr('m33_hx', struct.pack('<HH', hx, hx + 2)), k.wr('m33_ts', struct.pack('<HH', g, g ^ 0xFFFF)),
                         k.wr('m33_gm', bytes((g + i) & 0xFF for i in range(64))))
    k.key(0x6D00); k.run_for(0.5)                         # (CODE-F6: the Executive)
    k.key(A.CODE['P']); k.run_for(1.0)                    # (no TERM.RUN here: LCMD a task in front, full screen)
    k.key(HOT); k.run_for(1.0)                            # (CODE-Tab: task 0; the first task's start saved its state)
    put(5, 0x1234)                                        # task 0's own now: only the next switch saves it
    m0 = mst()
    k.key(HOT); k.run_for(1.0)                            # CODE-Tab: LCMD
    t1 = tstate(k)[1:]
    put(9, 0x5678)                                        # (LCMD's own, in front)
    l1 = mst()
    k.key(HOT); k.run_for(1.0)                            # CODE-Tab: task 0 again
    t2 = tstate(k)[1:]
    k.key(0x6D00); k.run_for(0.5)                         # (CODE-F6: Paint)
    m1 = mst()
    k.wr('m33_hx', struct.pack('<HH', *keep[0][7:9])); k.wr('m33_ts', struct.pack('<HH', *keep[0][9:11]))
    k.wr('m33_gm', keep[1])                               # (Paint's pointer as it was)
    w2 = (mb('mw_cur'), pb('ses'), view_bad())
    stroke('L', 120, 120, 320, 220)
    check('CODE-F6, CODE-P (LCMD a task in front, full screen), CODE-Tab twice (front %s), again (task 0: %s), CODE-F6: Paint in '
          'front, its view drawn, the UI\'s INT 33h state task 0\'s as it was (limits, ratios, show count %d, hot spot, '
          'masks), not LCMD\'s; a stroke drawn where the mouse went' % (t1, t2, m1[0][6] - 65536 * (m1[0][6] > 32767)),
          t1[0] == 1 and t2[0] == 0 and w2 == (1, 1, []) and m1 == m0 and l1 != m0
          and C() == [bytes(l) for l in m.l] and not view_bad() and not k.crashed, (t1, t2, w2, m0, m1, l1, view_bad()))
    k.key('U'); k.run_for(0.3)
    k.key(A.CODE['X']); k.key(ktest.ENTER); k.run_for(1.0)    # (saved: no question at the close box)
    wx = win()
    tclick(k, (wx[0] + wx[2] - 2) * 8 + 4, wx[1] + 10); k.run_for(1.0)
    check('a click on its close box (saved: no question): Paint ends, its window closed, the session gone; nothing crashed',
          mb('mw_n') == 0 and not A.has(k, 'Paint:') and not k.crashed, A.screen(k))
    # a DOS task computing behind keeps going while a stroke is held (UI_MOUSE waits where tasks switch)
    k = boot('mt_pw2.img', b'MULTITASK=1\r\n', 88, PAINT, mouse=True)
    seg, Y = mt_seg(k), k.Y
    k.key(A.CODE['P']); k.run_for(1.0)
    typ(k, 'start /w mtspin.com 5000 hs.txt', 0.3); typ(k, 'exit', 1.0); k.run_for(1.0); k.settle()
    k.select('PAINT.RUN'); k.key(ktest.ENTER); k.run_for(1.0)  # (a window: the hint in the band, no wait)
    au = Audit(k)
    A.point(k, 200, 150); k.pc.mouse_move(0, 0, 1); k.run_for(0.1)
    n = len(au.ev)
    for _ in range(30): k.pc.mouse_move(1, 1, 1); k.run_for(0.1)
    held = (k.pc.rd(seg, Y['mw_n'], 1)[0], len(au.switches(n)), len(au.bad()))
    k.pc.mouse_move(0, 0, 0); k.run_for(0.3)
    au.stop()
    wt = lambda: bytes(k.pc.rd(k.useg, k.pc.u16(seg, Y['mw_ses'] + SE_SIZE + SE_BASE) + PS['wtitle'], 24))
    t0 = wt()[:6] == b'Paint\0'
    k.key(A.CODE['X']); k.key('verylongnamefor'); k.key(ktest.ENTER); k.run_for(1.0)
    t1 = wt()
    k.key(ktest.DOWN); k.run_for(0.3)
    check('an unnamed picture ("Paint"), CODE-X "verylongnamefor": saved as DOS cuts it, VERYLONG.BMP, and the title '
          'that name ("Paint: VERYLONG.BMP"), the band\'s view line its own after a key',
          t0 and t1[:20] == b'Paint: VERYLONG.BMP\0' and A.has(k, 'Paint: VERYLONG.BMP') and A.disk_file(k, 'VERYLONG.BMP')
          and not k.crashed
          and any(l.startswith('View: from') for l in k.band()), (t0, t1, k.band()))
    check('a stroke held 3 s in a Paint window: MTSPIN behind keeps its turns meanwhile (%d switches), every one by '
          'the rules' % held[1], held[0] == 1 and held[1] > 10 and held[2] == 0, held)
    # a second Paint: a session of its own, its window staggered, its own C
    k.key(0x6D00); k.run_for(0.5)                         # (CODE-F6: the Executive)
    k.select('PAINT.RUN'); k.key(ktest.ENTER); k.run_for(1.0)
    rec = lambda i, o: k.pc.u16(seg, Y['mw_ses'] + i * SE_SIZE + o)
    def pv2(n, i): return k.pc.u16(k.useg, rec(i, SE_BASE) + PS[n])
    w1_ = tuple(k.pc.u16(k.useg, rec(1, SE_BASE) + PS['win'] + o) for o in (0, 2, 4, 6))
    w2_ = tuple(k.pc.u16(k.useg, rec(2, SE_BASE) + PS['win'] + o) for o in (0, 2, 4, 6))
    c1 = k.pc.rd(pv2('segc', 1), 0, 32000)
    A.drag(k, 300, 200, 400, 250); k.run_for(0.3)
    c1b, c2 = k.pc.rd(pv2('segc', 1), 0, 32000), k.pc.rd(pv2('segc', 2), 0, 32000)
    check('a second Paint: two sessions (%d), the second\'s window lower and to the right (%s, the first %s), its own '
          'pictures (C %04Xh, the first\'s %04Xh); a stroke in it leaves the first\'s C as it was'
          % (k.pc.rd(seg, Y['mw_n'], 1)[0], w2_, w1_, pv2('segc', 2), pv2('segc', 1)),
          k.pc.rd(seg, Y['mw_n'], 1)[0] == 2 and w2_[0] > w1_[0] and w2_[1] > w1_[1]
          and len({pv2('segc', 1), pv2('segu', 1), pv2('segc', 2), pv2('segu', 2)}) == 4
          and c1b == c1 and c2 != bytes(32000) and not k.crashed, (w1_, w2_))
    k.key(ktest.ESC); k.key(ktest.ENTER); k.run_for(0.5)
    check('... ESC, Return (changed: quit without saving): the second ended, the first still there, nothing crashed',
          k.pc.rd(seg, Y['mw_n'], 1)[0] == 1 and k.pc.rd(k.useg, rec(1, SE_BASE) + PS['ses'], 1)[0] == 1
          and not k.crashed, A.screen(k))


def t_system():
    print('== System: the Multitasking topic (M7b)')
    k = boot('mt_sy.img', b'MULTITASK=1\r\nSAVER=10\r\n', 88, A.SYSTEM)
    k.key(A.CODE['U'])
    for _ in range(9): k.key(ktest.DOWN)
    t1 = k.text()
    k.key(' ')
    f1, t2 = A.disk_file(k, 'LODE.INI'), k.text()
    k.key(' ')
    f2 = A.disk_file(k, 'LODE.INI')
    check('System\'s tenth topic, Multitasking: on now, and from the next start-up; Space: off from the next start-up '
          '(its line gone, the others kept), Space again: MULTITASK=1 written', 'Multitasking now' in t1
          and re.search(r'Multitasking now\s+on', t1) and re.search(r'From the next start-up\s+on', t1)
          and re.search(r'From the next start-up\s+off', t2) and f1 == b'SAVER=10\r\n'
          and f2 == b'SAVER=10\r\nMULTITASK=1\r\n', (t1[-900:], f1, f2))
    k = boot('mt_sy2.img', b'multitask=On\r\n', 88, A.SYSTEM, mt=None)
    k.key(A.CODE['U'])
    for _ in range(9): k.key(ktest.DOWN)
    t3 = k.text()
    check('asked for (multitask=On, as the kernel reads it) but off (no LODEMT.SYS): said why',
          re.search(r'Multitasking now\s+off', t3) and re.search(r'From the next start-up\s+on', t3)
          and 'Asked for, but off this time' in t3, t3[-900:])
    k = boot('mt_sy3.img', b'MULTITASK=1X\r\n', 88, A.SYSTEM)
    k.key(A.CODE['U'])
    for _ in range(9): k.key(ktest.DOWN)
    t4 = k.text()
    check('MULTITASK=1X: off, for the kernel and for System alike (something after the 1)',
          re.search(r'Multitasking now\s+off', t4) and re.search(r'From the next start-up\s+off', t4)
          and 'Asked for' not in t4, t4[-900:])

def t_rclaude():
    print('== Resident Claude with tasks: MT_TSR, its key wait, its pop-up the front task\'s (M7c)')
    import test_resident as R
    cl = os.path.join(GOS, 'claude', 'CLAUDE.COM')
    k = boot('mt_rc.img', b'MULTITASK=1\r\n', 88, cl, MTK, 'ZZ.COM=' + MTLN)
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    tsr = lambda: (k.pc.u16(seg, Y['mt_tsrs']), k.pc.u16(seg, Y['mt_tsro']))
    # CLAUDE /R inside a task: refused (exit code 3), nothing resident
    sh.run('start /w claude.com /r'); k.run_for(1.0)
    o = sh.run('wait 1')
    o2 = sh.run('if errorlevel 3 echo LEVEL3')
    check('CLAUDE /R inside a task (START): refused, exit code 3 (WAIT\'s ERRORLEVEL), no stub, nothing for MT',
          'LEVEL3' in o2 and tsr() == (0, 0) and not any(n == 'CLAUDE' for s, ow, p, n in R.mcbs(k)), (o, o2, tsr()))
    # from the Executive's own task (CODE-P's prompt): resident, MT told
    o = sh.run('claude /r')
    stub = R.stub_seg(k)
    rmt = (k.pc.u16(stub, R.csym('r_mt')), k.pc.u16(stub, R.csym('r_mt') + 2))
    check('CLAUDE /R at CODE-P\'s prompt: resident (stub version 5, r_mt since 3); MT_TSR: MT has its key wait (%04X:%04X), the stub '
          'MT\'s three bytes (front, running, the pop-up waiting)' % tsr(), 'Claude is resident' in o and k.pc.rd(stub, 0x104, 1) == b'\x05'
          and tsr() == (stub, R.csym('..@r_idle')) and rmt == (Y['mt_front'], seg), (o, tsr(), rmt))
    # the front task waiting for a key in the stub's own loop: a task behind runs (switched from its HLT), as fast as
    # alone (the waiting task gets no turns: TS_WAITK, as in MT's own wait)
    typ(k, 'mtspin 36 r0.txt', 0.3)
    k.run_for(3.0); k.settle()
    r0 = spun(k, 'R0.TXT')
    au = Audit(k)
    typ(k, 'start /w mtspin.com 36 rs.txt', 0.3)
    typ(k, 'mtkey r rr.txt', 0.2)
    # meanwhile a timer interrupt, a switch due, raised elsewhere in the stub with interrupts on (r_hot, just after
    # its STI): not a place to switch from.  (All five come in MTKEY R's first turn, before it is switched from at the
    # HLT, once, and waits; MTSPIN's count, about 0.97 of its count alone, has room for the ticks they add.)
    at, raised, prev, waits = stub * 16 + R.csym('r_hot.no') + 1, [], k.pc.watch, set()
    def w(a):
        if prev: prev(a)
        cur = k.pc.rd(seg, Y['mt_cur'], 1)[0]
        if cur == 1: waits.add(tstate(k)[0][0][1])
        if a == at and len(raised) < 5 and cur == 0:
            raised.append(k.pc.us); k.pc.wr(seg, Y['mt_pend'], b'\1')
            k.pc.irq_pending.add(0); k.pc.mu.emu_stop()
    k.pc.watch = w
    k.run_for(4.0)
    k.pc.watch = prev
    rs = spun(k, 'RS.TXT')
    k.key('q', settle=False); k.run_for(1.0); k.settle()
    au.stop()
    at_hlt = [e for e in au.switches() if e['cs'] == stub]
    check('MTKEY R in front waiting in the stub\'s HLT loop: switched from at its HLT (%d times) and nowhere else in the '
          'stub (%d timer interrupts raised just after r_hot\'s STI), every switch by the rules; meanwhile it waits as in '
          'MT (TS_WAITK while MTSPIN runs: %s), so MTSPIN behind counts as fast as alone (%d, alone %d: %.2f); then "q" read'
          % (len(at_hlt), len(raised), sorted(waits), rs, r0, rs / max(r0, 1)),
          r0 > 0 and rs > 0.85 * r0 and A.disk_file(k, 'RR.TXT') == b'0071' and not k.crashed and at_hlt
          and len(raised) == 5 and all(e['ip'] == R.csym('..@r_idle') for e in at_hlt) and not au.bad()
          and TS_WAITK in waits, (rs, r0, sorted(waits), A.disk_file(k, 'RR.TXT'), len(at_hlt), len(raised),
                                    au.bad()[:3]))
    # CODE-\ in a background task's call (MTKEY P's peeks, through the stub), MTSPIN computing in front: the pop-up
    # waits for the front task's call
    typ(k, 'start /w mtline.com cl.txt', 0.3)           # (a task for CODE-Tab to switch to, below)
    typ(k, 'mtlaunch /f mtspin.com 36 fs.txt;mtkey.com p bp.txt', 0.3)
    k.pc.run_until(lambda: any(n == 'MTKEY.COM' for i, s, n in tstate(k)[0]), 1)     # (MTKEY P started: about then)
    kp = [i for i, s, n in tstate(k)[0] if n == 'MTKEY.COM']
    r16, put = stub * 16 + R.csym('r_int16'), []
    def w(a):
        if prev: prev(a)
        if a == r16 and not put and kp and k.pc.rd(seg, Y['mt_cur'], 1)[0] == kp[0]:
            put.append(1); k.pc.keys.append(R.HOT); k.pc.kbd_sync()
    k.pc.watch = w
    k.run_for(0.6)
    k.pc.watch = prev
    pend, inpop, mode, ring = (k.pc.rd(stub, R.csym('r_pend'), 1)[0], k.pc.rd(stub, R.csym('r_inpop'), 1)[0],
                               k.pc.mode(), k.pc.kbd_ring())
    k.run_for(3.0)
    up, st = R.console(k), tstate(k)
    check('CODE-\\ typed as MTKEY P, behind, calls INT 16h (through the stub), MTSPIN computing in front: taken there, '
          'the pop-up pending, not over the front screen (mode %02Xh); once the front task (LCMD\'s prompt) asks for a '
          'key, the console comes, in front' % mode, put and pend and inpop == 0 and mode == 3
          and not {0x2B00, 0x2BF0} & set(ring) and spun(k, 'FS.TXT') > 0 and up and st[1] == 0
          and A.disk_file(k, 'BP.TXT') is not None, (put, pend, inpop, hex(mode), ring, spun(k, 'FS.TXT'), up, st))
    # CODE-Tab in the console: the console's key, not MT's (no switch once it closes)
    k.key(HOT, settle=False); k.run_for(0.3)
    sw = k.pc.rd(seg, Y['mt_swreq'], 1)[0]
    k.key(R.HOT); k.run_for(0.5)
    st = tstate(k)
    check('CODE-Tab with the console up, MTLINE behind: left to the console (MT asks for no switch: mt_swreq %02Xh); '
          'the console closed, the front task as it was' % sw, sw == 0xFF and st[1] == 0 and not R.console(k)
          and k.pc.mode() == 3 and (1, TS_WAITK, 'MTLINE.COM') in st[0], (sw, st))
    front(k, 1); line(k, 'cl'); k.run_for(0.5); line(k, ''); k.run_for(0.3)    # (MTLINE, then MTLAUNCH's line)
    # a key only AH=10h gives (CODE-ESC: the BIOS's AH=01h drops it) while MTKEY R waits behind in the stub's loop:
    # the front task's AH=10h read gets it, every time; the read behind waits (TS_WAITK), and no look of its at the
    # buffer is an AH=01h
    got, peeks = [], []
    i16 = seg * 16 + Y['mt_i16']
    def w(a):
        if prev: prev(a)
        if a == i16 and k.pc.u16(k.pc.r('ss'), k.pc.r('sp') + 2) == stub \
                and k.pc.rd(seg, Y['mt_cur'], 1)[0] != k.pc.rd(seg, Y['mt_front'], 1)[0]:
            peeks.append(k.pc.r('ax') >> 8)
    k.pc.watch = w                                      # (from its start: its first looks, before its first HLT)
    typ(k, 'start /w mtkey.com r br.txt', 0.5)
    for i in range(3):
        typ(k, 'mtkey e e%d.txt' % i, 0.4)
        k.key(0x0100, settle=False); k.run_for(1.0); k.settle()
        got.append(A.disk_file(k, 'E%d.TXT' % i))
    k.pc.watch = prev
    st = tstate(k)
    check('CODE-ESC (only AH=10h gives it; the BIOS\'s AH=01h drops it) for MTKEY E (AH=10h) in front, MTKEY R waiting '
          'behind in the stub\'s loop: the front read gets it each time (%s); MTKEY R waits (TS_WAITK), its loop\'s looks '
          'from behind AH=11h only (%s)' % (got, sorted(set(peeks))), got == [b'0100'] * 3
          and peeks and set(peeks) == {0x11} and A.disk_file(k, 'BR.TXT') is None and (1, TS_WAITK, 'MTKEY.COM') in st[0],
          (got, peeks, st))
    # CODE-\ typed as MTKEY P, behind, calls through the stub, MTLINE in front waiting in MT for its line (DOS's key
    # wait: TS_WAITK): taken in MTKEY's call, the pop-up pending; MT brings the front task's turn as for a key
    # (mt_tsrk), and the console comes
    rid = [i for i, s, n in tstate(k)[0] if n == 'MTKEY.COM']       # (MTKEY R, waiting behind)
    typ(k, 'mtlaunch /f mtline.com ml.txt;mtkey.com p bq.txt', 0.3)
    kp = [i for i, s, n in tstate(k)[0] if n == 'MTKEY.COM' and i not in rid]
    put = []
    def w(a):
        if prev: prev(a)
        if a == r16 and not put and kp and k.pc.rd(seg, Y['mt_cur'], 1)[0] == kp[0]:
            put.append([e for e in tstate(k)[0] if e[2] == 'MTLINE.COM']); k.pc.keys.append(R.HOT); k.pc.kbd_sync()
    k.pc.watch = w
    k.run_for(1.0)
    k.pc.watch = prev
    up, tk = R.console(k), k.pc.rd(seg, Y['mt_tsrk'], 1)[0]
    k.key(R.HOT); k.run_for(0.5)
    line(k, 'ml'); k.run_for(1.0); line(k, ''); k.run_for(0.3)
    check('CODE-\\ typed as MTKEY P, behind, calls through the stub, MTLINE in front waiting in MT for its line (%s): '
          'the console comes (the front task\'s turn brought on, mt_tsrk, then cleared), and goes; MTLINE gets its line'
          % put, len(put) == 1 and [s for i, s, n in put[0]] == [TS_WAITK] and up and tk == 0 and A.disk_file(k, 'ML.TXT') == b'ml',
          (put, up, tk, tstate(k)))
    # a disk error in a task behind, its INT 24h prompt (MT's) reading the answer through the stub, where no switch
    # can come: the stub's loop finds the key (AH=11h) and passes the read on, as it is
    k.pc.drives[0].bad = set(file_lbas(os.path.join(A.OUT, 'mt_rc.img'), b'ZZ      COM'))
    typ(k, 'start /w zz.com zz.txt', 2.0)
    scr = k.pc.text_screen()
    k.key('a', settle=False); k.run_for(2.0)
    k.pc.drives[0].bad = set()
    v = sh.run('ver')
    st = tstate(k)
    check('a read error in a task behind (START /W of a file with bad sectors), Resident Claude loaded: its prompt '
          'answered (Abort) through the stub\'s loop, the task gone; the machine goes on',
          'Abort' in scr and 'Lodestone version' in v and not k.crashed
          and [e for e in st[0] if e[2] == 'ZZ.COM'] == [], (scr[-300:], v[-80:], st))
    front(k, 1)
    k.key('z', settle=False); k.run_for(1.0); k.settle()
    check('... MTKEY R brought to the front: its read gets "z" (007A)', A.disk_file(k, 'BR.TXT') == b'007A'
          and tstate(k)[0] == [(0, 1, 'Executive')], (A.disk_file(k, 'BR.TXT'), tstate(k)))
    # TYPE's keys (put in the console's page as type_start leaves them: its request, id and op, then a wait of 5 ticks
    # and "x", in ksbuf from 2) for MTKEY R in
    # front, waiting in the stub's loop, MTSPIN behind: switched from at the HLT in the wait (TS_WAITK), the front task
    # still gets its turns (mt_tsrk), the key comes, and at the end the console (to answer TYPE)
    typ(k, 'start /w mtspin.com 144 ts.txt', 0.3)        # (8 s: still computing when the keys are done)
    rp = k.pc.ems_page(k.pc.rd(stub, R.csym('r_hw'), 1)[0]) * 0x4000
    rsym = {m.group(2): int(m.group(1), 16) for m in (re.match(r'\s*[0-9A-F]+\s+([0-9A-F]+)\s+(\S+)\s*$', l)
                                                      for l in open(os.path.join(GOS, 'claude', 'RCON.MAP'))) if m}
    def ems(name, b): a = rp + rsym[name]; k.pc.ems_store[a:a + len(b)] = b
    ems('ksbuf', b'\0\0\xff\xff\x05\x78\x2d'); ems('ks_pos', b'\2\0'); ems('ks_len', b'\7\0'); ems('ks_wait', b'\0')
    typ(k, 'mtkey r tr.txt', 0.05)
    # the keys start in MTKEY R's read (AH=00h), as when the console goes, leaving them, in the program's call
    waits, fed = set(), []
    def w(a):
        if prev: prev(a)
        cur = k.pc.rd(seg, Y['mt_cur'], 1)[0]
        if a == r16 and not fed and cur == 0 and k.pc.r('ax') >> 8 == 0 and k.pc.r('ss') != 0x60:   # (not DOS's
            # read of LCMD's line, on the kernel's stack: MTKEY's own)
            fed.append(1); k.pc.wr(stub, R.csym('r_ks'), b'\1')
        if fed and cur != 0 and k.pc.ems_store[rp + rsym['ks_pos']] == b'\2':  # (in the wait: the key not yet)
            waits.add(tstate(k)[0][0][1])
    k.pc.watch = w
    k.run_for(2.5)
    k.pc.watch = prev
    tr, up, st = A.disk_file(k, 'TR.TXT'), R.console(k), tstate(k)
    k.key(R.HOT); k.run_for(0.5)
    k.run_for(7.0); k.settle()
    check('TYPE\'s keys (a 5-tick wait, then "x") for MTKEY R in front, MTSPIN behind: through the wait (MTKEY R '
          'waiting as in MT meanwhile: %s) the key comes (%s), then the console, to answer TYPE, MTSPIN still computing'
          % (sorted(waits), tr), fed and tr == b'2D78' and up and TS_WAITK in waits and any(n == 'MTSPIN.COM' for i, s, n in st[0])
          and spun(k, 'TS.TXT') > 0, (tr, up, sorted(waits), st))
    # CLAUDE /U: MT forgets the key wait
    o = sh.run('claude /u')
    check('CLAUDE /U: out, and MT has no key wait of its any more (0:0)', 'no longer resident' in o and tsr() == (0, 0),
          (o, tsr()))

def t_rpoll():
    print('== Resident Claude over a program that polls INT 16h AH=01h (KEYPK): MT sees its peeks; CODE-\\, CODE-Tab')
    import test_resident as R
    cl = os.path.join(GOS, 'claude', 'CLAUDE.COM')
    k = boot('mt_rp.img', b'MULTITASK=1\r\n', 88, cl, 'KEYPK.COM=' + R.asm('KEYPK', R.KEYPK))
    sh = Shell(k)
    sh.run('ver')
    o = sh.run('claude /r')
    typ(k, 'mtspin 36 r0.txt', 0.3)
    k.run_for(3.0); k.settle()
    r0 = spun(k, 'R0.TXT')
    typ(k, 'start /w mtspin.com 36 rs.txt', 0.3)
    typ(k, 'keypk', 0.2)
    k.run_for(3.5)
    k.key(ktest.ESC, settle=False); k.run_for(1.0)
    rs = spun(k, 'RS.TXT')
    check('MTSPIN behind KEYPK, which polls AH=01h through the stub: %d, alone %d (%.3f; 0.183 before the stub looked '
          'for CODE-\\ itself, 0.079 with that look under MT, whose peek MT took for the stub\'s, not the program\'s)'
          % (rs, r0, rs / max(r0, 1)), 'resident' in o and r0 > 0 and rs >= 0.15 * r0, (o[-120:], rs, r0))
    # CODE-\ under KEYPK at many moments of its loop: MT's mt_drop keeps it (2B00h) for the stub's next look
    def hot16(k):
        typ(k, 'keypk', 0.5)
        missed = []
        for i in range(16):
            k.pc.run_for(0.0013 * i + 0.0005)
            k.key(R.HOT, settle=False)
            if not k.pc.run_until(lambda: R.console(k), 3):
                missed.append(i)
                continue
            k.key(R.HOT, settle=False)
            k.pc.run_until(lambda: k.pc.mode() == 3, 3)
        return missed
    missed = hot16(k)
    check('CODE-\\ under KEYPK at 16 moments of its peek loop: the console came each time, and back', not missed, missed)
    # CODE-Tab under it, a task behind: the switch at its next peek, not at a tick in its own code
    k.key(ktest.ESC, settle=False); k.run_for(0.5)
    typ(k, 'start /w mtspin.com 200 rt.txt', 0.3)
    typ(k, 'keypk', 0.5)
    f0 = tstate(k)[1]
    k.key(HOT, settle=False)
    t0, us = k.pc.us, lambda: k.pc.us
    while us() < t0 + 500000 and tstate(k)[1] == f0: k.pc.run(300)
    dt = (us() - t0) / 1000.0
    check('CODE-Tab under KEYPK (task %d in front), MTSPIN behind: the front task changes %.1f ms later' % (f0, dt),
          tstate(k)[1] != f0 and dt < 100, (f0, tstate(k), dt))     # (44 ms with ticks on time, H10; 21 when a tick held
                                                                    #  under CLI waited for pcemu's next run; none in 500 when MT took
                                                                    #  the peeks for the stub's)
    # KEYPK's peeks through a TSR's INT 16h hook loaded after CLAUDE /R (MTKEY H, on with PUSHF / CALL FAR: the frame
    # MT sees is the hook's, not the program's): in front MT drops the keys AH=01h skips all the same, CODE-\ kept
    k = boot('mt_rp2.img', b'MULTITASK=1\r\n', 88, cl, MTK, 'KEYPK.COM=' + R.asm('KEYPK', R.KEYPK))
    sh = Shell(k)
    sh.run('ver')
    o = sh.run('claude /r') + sh.run('mtkey h x')
    m1 = hot16(k)
    k.key(ktest.ESC, settle=False); k.run_for(0.5)
    typ(k, 'start /w mtspin.com 200 rh.txt', 0.3)
    m2 = hot16(k)
    check('KEYPK through MTKEY H\'s hook (loaded after CLAUDE /R), CODE-\\ at 16 moments, alone and with MTSPIN behind: '
          'the console every time', 'resident' in o and not m1 and not m2, (o[-160:], m1, m2))

TERMRUN = os.path.join(GOS, 'apps', 'TERM.RUN')
TERMFNT = os.path.join(GOS, 'fonts', 'TERM.FNT')

def t_term():
    print('== terminal windows (T2): a text program started as a task behind, shown in TERM.RUN\'s window')
    box = os.path.join(A.OUT, 'BOX.TXT'); open(box, 'wb').write(b'\xc9\xcd\xbb\r\n')
    k = boot('mt_tw.img', b'MULTITASK=1\r\n', 88, TERMRUN, TERMFNT, box, A.CALCRUN)
    seg, Y = mt_seg(k), k.Y
    T = TermView(k)
    mb, base, tv, scr, tnum, typ2, TS = T.mb, T.base, T.tv, T.scr, T.tnum, T.typ2, T.TS
    au = Audit(k)
    # CODE-P: LCMD in a window, a task behind
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    st, n, o = tstate(k), tnum('LCMD.COM'), scr()
    tk = k.pc.rd(seg, Y['mw_ses'] + SE_SIZE + SE_TASK, 2)
    xy1 = (tv('x0'), tv('y0'))
    check('CODE-P with MULTITASK=1: LCMD.COM a task behind (task %d), task 0 still in front (mode 40h), in a terminal window '
          '(a session, TERM.RUN: MT_TOPEN gave it the task and its count), titled LCMD.COM, its prompt drawn inside' % n,
          (n, 1, 'LCMD.COM') in st[0] and st[1] == 0 and k.pc.mode() == 0x40 and mb('mw_n') == 1 and tk[0] == n
          and tk[1] == k.pc.rd(seg, task_ent(k, n) + TE_GEN, 1)[0] and 'LCMD.COM' in o and 'A:\\>' in o, (st, mb('mw_n'), tk, o[-400:]))
    # typed in the window: to it (MT_TKEY), its answer drawn; idle, the ticks aren't activity (the saver's lastact)
    typ2('ver')
    o = scr()
    la = k.pc.u16(k.useg, Y['lastact'])
    k.run_for(2.0)
    check('VER typed in the window: LCMD\'s answer drawn there ("Lodestone version"); 2 s idle with the window up: no '
          'activity counted (the saver\'s lastact as it was: EV_TICK is not a key)', 'Lodestone version' in o
          and k.pc.u16(k.useg, Y['lastact']) == la, (o[-300:], la, k.pc.u16(k.useg, Y['lastact'])))
    # MT_TOPEN from a task (MTPROBE in the window: task 1, its count 1, as the window's): refused, the record kept
    typ2('mtprobe > pr.txt', 4.0)
    l4 = [l for l in (A.disk_file(k, 'PR.TXT') or b'').decode('latin-1').split('\n') if l.startswith('F01E')]
    check('MT_TOPEN called by a task (MTPROBE run in the window, task %d count %d, its own): refused (AX = 1: the UI\'s '
          'call only), the window\'s record as it was' % (n, tk[1]), n == 1 and tk[1] == 1 and len(l4) == 4
          and 'CF=1 AX=0001' in l4[3] and k.pc.rd(seg, Y['mw_ses'] + SE_SIZE + SE_TASK, 2) == tk, (l4, tk))
    # a key's echo drawn at once: the task's change count (TX_CHG) gives the tick, not only the 9 ticks' heartbeat
    lat = []
    for ch in 'abcdef':
        c0 = tv('cur'); k.key(ch, settle=False)
        for t in range(1, 13):
            k.run_for(0.055)
            if tv('cur') != c0: break
        lat.append(t)
    k.key(ktest.ESC, settle=False); k.run_for(0.5)
    check('6 keys typed in the window, one at a time: each one\'s echo drawn within 3 ticks (%s: TX_CHG\'s tick, not the '
          'heartbeat\'s 9)' % lat, max(lat) <= 3, lat)
    # mw_say's message (CODE-T: no TASKS.RUN here) waits in the band: no tick is its key
    k.key(0x1400, settle=False); k.run_for(1.5)
    b1 = k.band()
    k.key(ktest.ESC, settle=False); k.run_for(0.5)
    check('CODE-T in the window (no TASKS.RUN): its message in the band, still there 1.5 s on (no EV_TICK ended it), '
          'gone after a key', any('TASKS.RUN' in l for l in b1) and not any('TASKS.RUN' in l for l in k.band()),
          (b1, k.band()))
    # DIR: past the window's 19 rows, the view follows the cursor
    typ2('dir', 2.0)
    o, top, rows, cur = scr(), tv('top'), tv('rows'), tv('cur') >> 8
    check('DIR in the window (more lines than its %d rows): the view follows the cursor (its screen\'s rows %d on; cursor row '
          '%d the last shown), the shell\'s banner scrolled out of it, the prompt at its foot' % (rows, top, cur),
          rows == 19 and top > 0 and cur == top + rows - 1 and 'command shell' not in o and 'A:\\>' in o.split('\n')[-4:][0] + ''.join(o.split('\n')[-4:]),
          (rows, top, cur, o[-500:]))
    # a program run from that prompt shows in the same window; its keys from the window
    typ2('mtline tl.txt')
    o = scr()
    typ2('hi')
    check('MTLINE run from the windowed prompt: in the same window ("MTLINE>"), "hi" typed there its line',
          'MTLINE>' in o and A.disk_file(k, 'TL.TXT') == b'hi', (o[-300:], A.disk_file(k, 'TL.TXT')))
    # code page 437: TYPE of 3 box bytes, drawn with TERM.FNT's glyphs
    typ2('type box.txt')
    sl, fnt = slot(k, n, 4000), open(TERMFNT, 'rb').read()
    at = next((i // 2 for i in range(0, 4000, 2) if sl[i:i + 6:2] == b'\xc9\xcd\xbb'), None)
    top, left, x0, y0 = tv('top'), tv('left'), tv('x0'), tv('y0')
    def drawn(r, c):
        d = (y0 + (r - top) * 16) * 20 + x0 + c - left
        return bytes(k.pc.rd(0xB800, d + (y & 3) * 0x2000 + (y >> 2) * 80, 1)[0] for y in range(16))
    got = [drawn(at // 80, at % 80 + j) == fnt[ch * 16:ch * 16 + 16] for j, ch in enumerate((0xC9, 0xCD, 0xBB))] if at is not None else None
    check('TYPE of C9h CDh BBh (code page 437\'s box corners and line) in the window: each drawn with TERM.FNT\'s glyph',
          got == [True, True, True], (at, got))
    # a resize (CODE-F8): fewer rows, the view still follows
    k.key(0x6F00, ktest.UP, ktest.UP, ktest.UP, ktest.ENTER, settle=False); k.run_for(1.0)
    typ2('ver')
    rows, top, cur = tv('rows'), tv('top'), tv('cur') >> 8
    check('CODE-F8, Up x3, Return: 3 rows fewer (%d); after VER the view still has the cursor (its row %d, rows %d-%d)'
          % (rows, cur, top, top + rows - 1), rows == 16 and top <= cur < top + rows, (rows, top, cur))
    # CODE-F7: moved down a step by the keys, the same view: all of it drawn again there (w_draw's unshade)
    yb = tv('y0')
    k.key(0x6E00, ktest.DOWN, ktest.ENTER, settle=False); k.run_for(1.0)
    o, ya = scr(), tv('y0')
    check('CODE-F7, Down, Return: the window moved down (its cells from line %d, %d before), its text drawn again there '
          '(the prompt, VER\'s answer), nothing typed meanwhile' % (ya, yb), ya > yb and 'A:\\>' in o
          and 'Lodestone version' in o, (ya, yb, o[-400:]))
    # CODE-F6: the Executive in front, then the window again, drawn as it was
    k.key(0x6D00, settle=False); k.run_for(1.0)
    c6 = mb('mw_cur')
    k.key(0x6D00, settle=False); k.run_for(1.5)
    o = scr()
    check('CODE-F6: the Executive in front (session %d), CODE-F6 again: the window in front, its text there (the prompt)' % c6,
          c6 == 0 and mb('mw_cur') == 1 and 'A:\\>' in o, (c6, mb('mw_cur'), o[-300:]))
    # keys typed while the task reads none (MTSPIN computing): the ring's 32, then TERM's 16 kept, all arriving
    typ2('mtspin 72 sp.txt', 0.3)
    k.key('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN', settle=False)            # (40)
    k.run_for(0.5)
    q = k.pc.rd(k.useg, base() + TS['qn'], 1)[0]
    w = waitfile(k, 'SP.TXT', 10.0); k.run_for(2.0)
    check('40 keys typed while MTSPIN computes in the window: 32 in its ring, the rest kept by TERM.RUN (%d), then all of '
          'them on LCMD\'s line, in order' % q, q == 8 and w is not None
          and 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMN' in slot_text(k, n), (q, w, slot_text(k, n)[-300:]))
    k.key(ktest.ESC, settle=False); k.run_for(0.5)
    # EXIT: the window closes, the Executive says so
    typ2('exit', 2.0)
    check('EXIT: the task ends, its window closes (no session), the Executive in front ("LCMD.COM ended")',
          mb('mw_n') == 0 and tnum('LCMD.COM') == 7 and any('LCMD.COM ended' in l for l in k.band()), (mb('mw_n'), tstate(k), k.band()))
    # Return on MTLINE.COM: its own window
    k.select('MTLINE.COM'); k.key(ktest.ENTER, settle=False); k.run_for(3.0)
    o, n2 = scr(), tnum('MTLINE.COM')
    typ2('ab', 2.0)
    check('Return on MTLINE.COM: a task behind (%d) in a window titled MTLINE.COM, its prompt there; "ab" and Return typed '
          'there: it ends, and the window with it' % n2, n2 != 7 and 'MTLINE.COM' in o and 'MTLINE>' in o
          and tnum('MTLINE.COM') == 7 and mb('mw_n') == 0, (o[-300:], mb('mw_n'), tstate(k)))
    # beside another session: the calculator open, the Executive in front again (CODE-F6), CODE-P: a second session;
    # CODE-Tab: the task full screen, then back (task 0 in front), its window drawn again
    k.key(0x2500, settle=False); k.run_for(1.5)                         # (CODE-K: the calculator)
    k.key(0x6D00, settle=False); k.run_for(1.0)
    c0 = mb('mw_cur')
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    n3, o = tnum('LCMD.COM'), scr()
    t1 = k.pc.rd(seg, Y['mw_ses'] + SE_SIZE + SE_TASK, 1)[0]
    b2 = k.pc.u16(seg, Y['mw_ses'] + 2 * SE_SIZE + SE_BASE)
    xy2 = (k.pc.u16(k.useg, b2 + TS['x0']), k.pc.u16(k.useg, b2 + TS['y0']))
    check('... that second terminal window opens lower and to the right (its slot higher: WINPOS.INC, as a second '
          'Write): its cells from %s, the first\'s from %s' % (xy2, xy1), xy2[0] > xy1[0] and xy2[1] > xy1[1], (xy1, xy2))
    check('CODE-K (the calculator: in the first session\'s record, the terminal window\'s before, its task cleared: %d), '
          'CODE-F6 (the Executive in front: %d), CODE-P: LCMD in a second session\'s window, beside the calculator\'s '
          '(2 sessions), its prompt drawn' % (t1, c0), t1 == 0 and c0 == 0 and mb('mw_n') == 2 and n3 != 7 and 'A:\\>' in o,
          (t1, c0, mb('mw_n'), tstate(k), o[-300:]))
    hot(k); k.run_for(1.5)
    fs = (tstate(k)[1], k.pc.mode(), 'A:\\>' in k.pc.text_screen())
    hot(k); k.run_for(1.5)
    for _ in range(8):                                                  # (CODE-Tab goes round the tasks)
        if tstate(k)[1] == 0: break
        hot(k); k.run_for(1.0)
    o0 = scr()
    typ2('ver')
    check('CODE-Tab: LCMD full screen (front %d, mode %02Xh, its prompt); CODE-Tab round to task 0: its window as it '
          'was (its prompt, before a key: task 0\'s screen put back by MT), VER\'s answer drawn there' % (fs[0], fs[1]), fs == (n3, 3, True)
          and k.pc.mode() == 0x40 and 'A:\\>' in o0 and 'Lodestone version' in scr(), (fs, tstate(k), k.pc.mode(), o0[-300:]))
    typ2('exit', 2.0)
    k.key(0x6D00, settle=False); k.run_for(1.0)
    k.key(ktest.ESC, settle=False); k.run_for(1.0)                     # (the calculator closed)
    # Shift-CODE-P: the Executive's own prompt, full screen, as before
    sh = Shell(k)
    o = sh.run('ver')
    check('Shift-CODE-P: the prompt as before, full screen in the Executive\'s task (mode 3, no task, no window)',
          k.pc.mode() == 3 and tstate(k)[0] == [(0, 1, 'Executive')] and mb('mw_n') == 0 and 'Lodestone version' in o,
          (k.pc.mode(), tstate(k), o[-200:]))
    line(k, 'exit')
    check('... every switch at a safe point (the audit; ui_event.l now mw_poll\'s)', not au.bad(), au.bad()[:3])
    # FULL=: in front, as before; and no TERM.RUN: the same
    for tag, text, files in (('FULL=MTLINE', b'MULTITASK=1\r\nFULL=MTLINE\r\n', (TERMRUN, TERMFNT)),
                             ('BG=MTLINE.COM', b'MULTITASK=1\r\nBG=MTLINE.COM\r\n', (TERMRUN, TERMFNT)),
                             ('FREEZE=MTLINE', b'MULTITASK=1\r\nFREEZE=MTLINE\r\n', (TERMRUN, TERMFNT)),
                             ('no TERM.RUN', b'MULTITASK=1\r\n', (TERMFNT,)), ('no TERM.FNT', b'MULTITASK=1\r\n', (TERMRUN,)),
                             ('a TERM.RUN not ours', b'MULTITASK=1\r\n', ('TERM.RUN=' + A.CALCRUN, TERMFNT))):
        k = boot('mt_tf.img', text, 88, *files)
        seg = mt_seg(k)
        k.select('MTLINE.COM'); k.key(ktest.ENTER, settle=False); k.run_for(3.0)
        if tag == 'a TERM.RUN not ours':                               # (the calculator's window: no MT_TOPEN; the
            c = k.pc.rd(seg, k.Y['mw_n'], 1)[0]                         #  Executive in front again, run_app returns)
            k.key(ktest.ESC, settle=False); k.run_for(3.0)
            st = tstate(k)
            check('%s (the calculator\'s, as TERM.RUN): Return on MTLINE.COM: a window, but no session has the task '
                  '(mw_owns); the window closed, the task in front, full screen' % tag, c == 1 and st[1] != 0
                  and k.pc.mode() == 3 and 'MTLINE>' in k.pc.text_screen(), (c, st, k.pc.mode()))
            continue
        st = tstate(k)
        check('%s: Return on MTLINE.COM: the task in front, full screen (mode 3, its prompt), no window' % tag,
              st[1] != 0 and k.pc.mode() == 3 and 'MTLINE>' in k.pc.text_screen()
              and k.pc.rd(seg, k.Y['mw_n'], 1)[0] == 0, (st, k.pc.mode(), k.pc.text_screen()[-200:]))
        if tag == 'no TERM.RUN':
            k.key('x', settle=False); k.key(ktest.ENTER, settle=False); k.run_for(2.0)
            k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
            st = tstate(k)
            check('... CODE-P with no TERM.RUN: LCMD a task, in front, full screen (not the Executive\'s own prompt: '
                  'Shift-CODE-P is)', st[1] != 0 and (st[1], 1, 'LCMD.COM') in st[0] and k.pc.mode() == 3
                  and k.pc.rd(seg, k.Y['mw_n'], 1)[0] == 0, (st, k.pc.mode()))

def t_wait_bg():
    print('== LCMD\'s WAIT behind, in a terminal window: a ^C typed into its window ends it, and one typed to the front '
          'task stays that task\'s (X34)')
    k = boot('mt_wb.img', b'MULTITASK=1\r\n', 88, TERMRUN, TERMFNT)
    T = TermView(k)
    scr, typ2 = T.scr, T.typ2
    ring = lambda: [k.pc.u16(0x40, a) for a in range(k.pc.u16(0x40, 0x1A), k.pc.u16(0x40, 0x1C), 2)]
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)                  # LCMD in a window: task 1, behind
    typ2('start /w mtspin.com 182 wa.txt')                              # task 2 computes, behind too (10 s)
    typ2('wait 2', 1.0)
    st0 = tstate(k)
    k.key(0x2E03, settle=False); k.run_for(1.5)                          # ^C typed into the window
    o1, st1 = scr(), tstate(k)
    check('WAIT 2 in LCMD\'s window, behind (%s): a ^C typed into the window ends it (^C, the prompt again), the task '
          'it waited for still there' % (st0[0],), [n for i, t, n in st0[0]] == ['Executive', 'LCMD.COM', 'MTSPIN.COM']
          and re.search(r'wait 2\s*\n\s*\^C\s*\n\s*A:\\>', o1) and st1[0] == st0[0], (st0, st1, o1[-300:]))
    typ2('wait 2', 1.0)
    k.key('x', settle=False); k.run_for(0.5)                            # a key in its ring (not a ^C)
    front(k, 2)                                                         # MTSPIN in front, full screen, computing
    k.key(0x2E03, settle=False); k.run_for(1.5)                          # ^C typed to it: in the BIOS's ring
    r, st2 = ring(), tstate(k)
    check('... WAIT 2 again, a key typed into the window, MTSPIN brought to the front: a ^C typed to MTSPIN stays in '
          'its ring (%s), WAIT behind doesn\'t take it, still waiting' % ['%04X' % w for w in r],
          0x2E03 in r and st2[1] == 2 and st2[0] == st0[0], (r, st2))
    k.run_for(10.0)                                                     # MTSPIN ends: WAIT does, at the window

def t_tgfx():
    print('== terminal windows (T3): a windowed program\'s graphics full screen, and back to its window with a text mode')
    k = boot('mt_tg.img', b'MULTITASK=1\r\n', 88, TERMRUN, TERMFNT, MTSC)
    seg, Y, WG = mt_seg(k), k.Y, equ('TX_WGFX')
    T = TermView(k)
    mb, scr, tnum, tx, typ2, to0 = T.mb, T.scr, T.tnum, T.tx, T.typ2, T.to0
    wg = lambda n: k.pc.rd(tx(n), WG, 1)[0]
    patok = lambda: bytes(k.pc.rd(0xB800, 0, 256)) == bytes((((i * 5) ^ (i >> 8)) & 0xFF) for i in range(256))
    def key(t=2.0):
        k.key('x', settle=False); k.run_for(t)
    au = Audit(k)
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    n = tnum('LCMD.COM')
    # a graphics mode asked for in the window: the task in front by itself, full screen
    typ2('mtmode 40 g.txt t', 3.0)
    st = tstate(k)
    check('MTMODE 40 run at the windowed prompt (task %d): in front by itself (front %d), mode 40h, its pattern on the '
          'screen, its TX_WGFX 1 (in front for graphics); its window still a session (behind)' % (n, st[1]),
          st[1] == n and k.pc.mode() == 0x40 and patok() and wg(n) == 1 and mb('mw_n') == 1, (st, k.pc.mode(), wg(n)))
    # CODE-Tab away: the window shows a note; a key in it: the task in front again
    to0()
    o = scr()
    key()
    st = tstate(k)
    check('CODE-Tab to task 0: the window\'s note ("In a graphics mode: a key here shows it"); a key typed in the window: '
          'the task in front again (front %d), its pattern as it was' % st[1], 'In a graphics mode' in o and st[1] == n
          and k.pc.mode() == 0x40 and patok(), (o[-400:], st))
    # a key: MTMODE sets mode 3 and prints: back to its window
    key(3.0)
    st, o = tstate(k), scr()
    check('a key: MTMODE sets mode 3, prints "MTMODE: text": back behind (front %d, the UI in 40h), its window showing it, '
          'TX_WGFX 0' % st[1], st[1] == 0 and k.pc.mode() == 0x40 and 'MTMODE: text' in o and wg(n) == 0, (st, o[-400:], wg(n)))
    key(2.0)
    check('a key typed in the window: MTMODE ends; its pattern was there throughout the switches (G.TXT "ok"); the '
          'prompt in the window (front 0, the UI in 40h)', A.disk_file(k, 'G.TXT') == b'ok' and tstate(k)[1] == 0
          and k.pc.mode() == 0x40 and 'A:\\>' in scr().split('MTMODE: text')[-1], (A.disk_file(k, 'G.TXT'), scr()[-300:]))
    # ending in graphics: a text mode set for it, the prompt back in its window
    typ2('mtmode 40 h.txt', 3.0)
    f1 = tstate(k)[1]
    key(3.0)
    st, o = tstate(k), scr()
    check('MTMODE 40 without T (front %d): a key, it ends still in graphics: mode 3 set for it (its screen\'s mode %d), '
          'back to its window, the prompt there (H.TXT "ok")' % (f1, k.pc.rd(tx(n), TX_VID, 1)[0]), f1 == n and st[1] == 0
          and k.pc.rd(tx(n), TX_VID, 1)[0] == 3 and A.disk_file(k, 'H.TXT') == b'ok' and 'A:\\>' in o
          and 'mtmode 40 h.txt' not in o and wg(n) == 0,
          (f1, st, o[-300:]))
    # mode 3 and at once graphics again (before the switch): still in front, not frozen behind
    typ2('mtmode 40 b.txt b', 3.0)
    f1 = tstate(k)[1]
    key(3.0)
    st, w1, vf = tstate(k), wg(n), k.pc.rd(seg, task_ent(k, n) + TE_VF, 1)[0]
    key(3.0)
    check('MTMODE 40 B (front %d): a key, mode 3 and at once 40h again: still in front (%d), TX_WGFX %d (in front for '
          'graphics), not frozen (TE_VF %d); a key, it ends in graphics: back to its window (B.TXT "ok")' % (f1, st[1], w1, vf),
          f1 == n and st[1] == n and k.pc.mode() == 0x40 and w1 == 1 and not vf & VF_DIRECT and tstate(k)[1] == 0
          and A.disk_file(k, 'B.TXT') == b'ok' and wg(n) == 0, (f1, st, w1, vf, tstate(k)))
    # CODE-Tab full screen in text: a mode 3 set there doesn't send it back (no TX_WGFX)
    hot(k); k.run_for(1.0)
    f1 = tstate(k)[1]
    typ2('mtmode 03 x.txt', 2.0)
    f2 = tstate(k)[1]
    key(2.0)
    check('CODE-Tab: LCMD full screen in text (front %d); MTMODE 03 there sets mode 3: still in front (%d, %d after its '
          'end), no TX_WGFX: a full screen asked for stays' % (f1, f2, tstate(k)[1]), f1 == n and f2 == n
          and tstate(k)[1] == n and A.disk_file(k, 'X.TXT') == b'ok' and wg(n) == 0, (f1, f2, tstate(k), wg(n)))
    # it writes the screen itself (MTSCR W, in front), back behind: frozen, a note; a key: in front
    typ2('mtscr w w.txt', 1.0)
    key(1.0)
    to0()
    o, st, vf = scr(), tstate(k), k.pc.rd(seg, task_ent(k, n) + TE_VF, 1)[0]
    key(2.0)
    f1 = tstate(k)[1]
    check('MTSCR W, the screen written itself in front, CODE-Tab to task 0: the task frozen behind (TE_VF %d), its '
          'window\'s note ("It writes the screen itself"); a key in the window: in front (%d)' % (vf, f1),
          'It writes the screen itself' in o and st[1] == 0 and vf & VF_DIRECT and f1 == n, (o[-400:], st, vf, f1))
    key(1.0)
    typ2('exit', 2.0)
    check('... EXIT in front: the task ends, its window closes, the Executive in front', tnum('LCMD.COM') == 7
          and mb('mw_n') == 0 and tstate(k)[1] == 0 and k.pc.mode() == 0x40, (tstate(k), mb('mw_n')))
    # Return on a graphics program: its window opens, it is full screen at once; at its end the Executive again
    k.select('MTMODE.COM'); k.key(ktest.ENTER, settle=False); k.run_for(3.0)
    st, n2, w1 = tstate(k), tnum('MTMODE.COM'), mb('mw_n')
    w2, pt = (wg(n2), patok()) if n2 != 7 else (0, False)
    key(3.0)
    check('Return on MTMODE.COM (no arguments: mode 40h): a terminal window opened (%d), the task full screen at once '
          '(front %d, TX_WGFX %d, its pattern); a key: it ends, its window closes, the Executive in front' % (w1, st[1], w2),
          w1 == 1 and st[1] == n2 and n2 != 7 and w2 == 1 and pt and tnum('MTMODE.COM') == 7 and mb('mw_n') == 0
          and tstate(k)[1] == 0 and k.pc.mode() == 0x40, (st, w1, w2, pt, tstate(k), mb('mw_n')))
    check('... every switch at a safe point (the audit)', not au.bad(), au.bad()[:3])
    # the end of a program other than the one that asked for graphics: no text mode for it (TX_WPSP)
    k = boot('mt_tg2.img', b'MULTITASK=1\r\n', 88, TERMRUN, TERMFNT)
    T = TermView(k)                     # (this machine's)
    mb, scr, tnum, tx, typ2, to0 = T.mb, T.scr, T.tnum, T.tx, T.typ2, T.to0
    seg = mt_seg(k)
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    n = tnum('LCMD.COM')
    typ2('mtmode 40 p.txt', 3.0)
    f1, wp = tstate(k)[1], k.pc.u16(tx(n), equ('TX_WPSP'))
    k.pc.wr(tx(n), equ('TX_WPSP'), struct.pack('<H', wp ^ 0xFFFF))              # (as if another program had asked)
    key(3.0)
    check('MTMODE 40 in front (front %d, TX_WPSP %04Xh: its PSP), TX_WPSP made another program\'s: its end in graphics '
          'leaves the task in front, in graphics (no mode 3 for it)' % (f1, wp), f1 == n and wp != 0 and tstate(k)[1] == n
          and k.pc.mode() == 0x40 and A.disk_file(k, 'P.TXT') == b'ok', (f1, wp, tstate(k), k.pc.mode()))
    # ... ended there (TX_WGFX still 1: MTLAUNCH /K, its own number); a new task in its place: its TX_WGFX 0
    t1, w1 = tx(n), wg(n)
    typ2('mtlaunch /k:%d' % n, 3.0)
    gone, w0 = tnum('LCMD.COM') == 7 and mb('mw_n') == 0, mb('mw_n')
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    n3 = tnum('LCMD.COM')
    t3, w3 = (tx(n3), wg(n3)) if n3 != 7 else (0, 9)
    hot(k); k.run_for(1.0)
    f1 = tstate(k)[1]
    typ2('mtmode 03 y.txt', 2.0)
    key(2.0)
    check('... ended in front there, its TX_WGFX %d (MTLAUNCH /K, its own number: its window closed, %d); a new LCMD in '
          'its place (task %d, the same TX: %04Xh, %04Xh): its TX_WGFX 0; CODE-Tab full screen (front %d), MTMODE 03 '
          'there: still in front' % (w1, w0, n3, t1, t3, f1), w1 == 1 and gone and n3 == n and t3 == t1 and w3 == 0
          and f1 == n3 and tstate(k)[1] == n3 and A.disk_file(k, 'Y.TXT') == b'ok', (w1, gone, n3, t1, t3, w3, f1, tstate(k)))

def t_tclip():
    print('== terminal windows (T4): select, copy and paste, the menu, and the mouse for the program in it')
    import ctypes
    sel = os.path.join(A.OUT, 'SEL.TXT'); open(sel, 'wb').write(b'alpha beta   \r\ngamma\r\ndelta epsilon\r\n')
    big = os.path.join(A.OUT, 'BIG.TXT')
    open(big, 'wb').write(b''.join(b'line %03d of a long file\r\n' % i for i in range(300)))
    # (boot()'s exact IRQ delivery: MTM33 P polls 03h nearly all its time under CLI, and without it gets
    #  almost no ticks there)
    k = boot('mt_t4.img', b'MULTITASK=1\r\n', 88, TERMRUN, TERMFNT, MTK, MTM, sel, big, mouse=True)
    seg, Y = mt_seg(k), k.Y
    T = TermView(k)
    mb, base, tv, tb, wv, scr, tnum, tx, TS = T.mb, T.base, T.tv, T.tb, T.wv, T.scr, T.tnum, T.tx, T.TS
    typ2, cxy, drawn, mv, btn, page, clip, to0 = T.typ2, T.cxy, T.drawn, T.mv, T.btn, T.page, T.clip, T.to0
    m33 = lambda n, f: k.pc.u16(tx(n), equ('TX_M33') + Y[f] - Y['m33_st'])  # (task n's own mouse state)
    fnt = open(TERMFNT, 'rb').read()
    g = lambda ch: fnt[ch * 16:ch * 16 + 16]
    inv = lambda b: bytes(255 - x for x in b)
    def setclip(data):                  # (written there, as UI_CLIP AL=0 would: a copy gave it its page)
        ctypes.memmove(ctypes.addressof(k.pc.ems_store) + page() * 0x4000, data, len(data))
        k.wr('clip_len', struct.pack('<H', len(data)))
    def row(text):
        return next((i for i, l in enumerate(slot_text(k, n).split('\n')) if l.startswith(text)), None)
    au = Audit(k)
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    n = tnum('LCMD.COM')
    typ2('type sel.txt', 2.0)
    r = row('alpha beta')
    # a drag from "beta" to "delta"'s last letter: lines selected, its cells drawn inverse
    A.drag(k, *(cxy(r, 6) + cxy(r + 2, 4))); k.run_for(0.5)
    mv(4, 4); k.run_for(0.3)                         # (the pointer off the cells)
    sa, sb = tv('sa'), tv('sb')
    hl = [drawn(r, 6) == inv(g(ord('b'))), drawn(r + 1, 0) == inv(g(ord('g'))), drawn(r + 2, 4) == inv(g(ord('a'))),
          drawn(r, 5) == g(32), drawn(r + 2, 5) == g(32), drawn(r, 4) == g(ord('a'))]
    check('LCMD in a window (task %d), TYPE of three lines; a drag from "beta" (row %s, column 6) to "delta"\'s last letter: '
          'selected by lines (%d to %d), its cells drawn inverse, those around it not (%s)' % (n, r, sa, sb, hl),
          r is not None and sa == r * 80 + 6 and sb == (r + 2) * 80 + 5 and all(hl), (r, sa, sb, hl))
    s0 = slot_text(k, n)
    k.key(A.CODE['C'], settle=False); k.run_for(0.5)
    check('CODE-C: the clipboard holds them (%r: each row\'s trailing blanks dropped, LF between rows); the program not given '
          'the key (its screen as it was), the selection still up' % clip(), clip() == b'beta\ngamma\ndelta'
          and slot_text(k, n) == s0 and tv('sb') > tv('sa'), (clip(), tv('sa'), tv('sb')))
    A.click(k, *cxy(r + 4, 10)); k.run_for(0.5)
    mv(4, 4); k.run_for(0.3)
    check('a click: the selection gone (%d, %d), its cells drawn as they are' % (tv('sa'), tv('sb')),
          tv('sa') == tv('sb') == 0 and drawn(r, 6) == g(ord('b')) and drawn(r + 2, 4) == g(ord('a')), (tv('sa'), tv('sb')))
    typ2('mtkey r k1.txt', 1.0)
    k.key(A.CODE['C'], settle=False); waitfile(k, 'K1.TXT', 3.0)
    check('... CODE-C with nothing selected: the program\'s (MTKEY R reads %r)' % A.disk_file(k, 'K1.TXT'),
          A.disk_file(k, 'K1.TXT') == b'2E00', A.disk_file(k, 'K1.TXT'))
    # the menu: Copy with a selection
    k.run_for(1.0)
    r = row('gamma')
    A.drag(k, *(cxy(r, 0) + cxy(r, 4))); k.run_for(0.3)
    mv(*cxy(r, 2)); btn(2, 0.5)
    o = scr()
    k.key(ktest.ENTER, settle=False); k.run_for(0.5)
    check('"gamma" selected, a right click: the menu (Copy, Paste, Full screen); Return on Copy, the first: the clipboard '
          '%r' % clip(), 'Copy           CODE-C' in o and 'Paste          CODE-V' in o and 'Full screen    CODE-Tab' in o
          and clip() == b'gamma', (o[-600:], clip()))
    # nothing selected: Paste, Full screen; while it is up, no tick for TERM (the help/form gate: UI_MENU's help_w)
    show_at, cnt, prev = k.useg * 16 + base() + TS['show'], [0], k.pc.watch
    def w(a):
        if prev: prev(a)
        if a == show_at: cnt[0] += 1
    k.key('type big.txt', settle=False); k.key(ktest.ENTER, settle=False); k.run_for(0.3)
    mv(*cxy(tv('top') + 2, 10)); btn(2, 0.2)
    for _ in range(30):                             # (the menu up: the task busy, the UI slower)
        if 'Full screen' in scr(): break
        k.run_for(0.1)
    k.pc.watch = w
    k.run_for(1.5)
    up, o = cnt[0], scr()
    k.key(ktest.ESC, settle=False); k.run_for(1.5)
    k.pc.watch = prev
    for _ in range(20):
        if 'line 299' in scr(): break
        k.run_for(1.0)
    check('TYPE of a long file, a right click with nothing selected: the menu (Paste, Full screen; no Copy); while it is up '
          '1.5 s, TERM not given a tick (its show entered %d times: the gate), %d times after ESC, the output all drawn' % (up, cnt[0]),
          'Paste          CODE-V' in o and 'Full screen    CODE-Tab' in o and 'Copy ' not in o and up == 0 and cnt[0] > 0
          and 'line 299' in scr(), (up, cnt[0], o[-500:]))
    # paste: 12 command lines (216 bytes: past the ring's 32 and TERM's 16), a line typed meanwhile after them
    typ2('cls', 1.0)
    setclip(b''.join(b'echo p%02d >> p.txt\n' % i for i in range(1, 13)))
    free = lambda: sum(sz for s_, t_, o_, sz, nm in mcbs(k) if o_ == 0)
    f0 = free()
    k.key(A.CODE['V'], settle=False); k.run_for(0.1)
    ps = tv('pseg')
    typ2('echo zz >>p.txt', 0.1)                   # (15 keys: TERM keeps 16)
    for _ in range(40):
        k.run_for(0.5)
        if tv('pseg') == 0 and b'zz' in (A.disk_file(k, 'P.TXT') or b''): break
    got = [l.strip() for l in (A.disk_file(k, 'P.TXT') or b'').split(b'\r\n') if l.strip()]
    check('CODE-V with them on the clipboard: typed to it in its own block (%04Xh, given back after: %04Xh, the free memory '
          'as before, %d paragraphs), all 12, in order, each answered (P.TXT %s), the line typed meanwhile after them'
          % (ps, tv('pseg'), f0, got[:3]), ps != 0 and tv('pseg') == 0 and free() == f0
          and got == [b'p%02d' % i for i in range(1, 13)] + [b'zz'], (ps, tv('pseg'), f0, free(), got))
    # the menu's Full screen; CODE-V with the clipboard empty: the program's
    mv(*cxy(tv('top') + 2, 10)); btn(2, 0.5)
    k.key(ktest.DOWN, settle=False); k.key(ktest.ENTER, settle=False); k.run_for(1.0)
    f1 = tstate(k)[1]
    to0()
    setclip(b'')
    typ2('mtkey r k2.txt', 1.0)
    k.key(A.CODE['V'], settle=False); waitfile(k, 'K2.TXT', 3.0)
    check('a right click, Down, Return: Full screen (front %d); CODE-V with the clipboard empty: the program\'s (MTKEY R: %r)'
          % (f1, A.disk_file(k, 'K2.TXT')), f1 == n and A.disk_file(k, 'K2.TXT') == b'2F00', (f1, A.disk_file(k, 'K2.TXT')))
    # resized by its corner, moved by its title, as a Write window (the core's): neither a selection nor the program's
    k.run_for(1.0)
    s0, w0, r0, c0 = slot_text(k, n), [wv(o) for o in (0, 2, 4, 6)], tv('rows'), tv('cols')
    cx, cy = (wv(0) + wv(4) - 1) * 8 + 4, wv(2) + wv(6) - 4
    A.drag(k, cx, cy, cx - 16, cy - 32); k.run_for(0.5)
    r1, c1 = tv('rows'), tv('cols')
    tx0, ty0 = (wv(0) + 20) * 8, wv(2) + 6
    A.drag(k, tx0, ty0, tx0 + 16, ty0 + 16); k.run_for(0.5)
    w1 = [wv(o) for o in (0, 2, 4, 6)]
    check('its corner dragged 2 columns left, 32 pixels up: 2 rows and columns fewer (%d, %d: %d, %d); its title strip dragged '
          '2 columns right and 16 down: moved (%s, %s); no selection made, nothing to the program (its screen as it was)'
          % (r0, c0, r1, c1, w0, w1), r1 == r0 - 2 and c1 == c0 - 2 and w1 == [w0[0] + 2, w0[1] + 16, w0[2] - 2, w0[3] - 32]
          and tv('sa') == tv('sb') == 0 and slot_text(k, n) == s0, (r0, c0, r1, c1, w0, w1, tv('sa'), tv('sb')))
    # 40 columns (MTMODE 01): a selection made in 80 gone; one made there not drawn past its 40 columns
    A.drag(k, *(cxy(tv('top') + 1, 2) + cxy(tv('top') + 2, 8))); k.run_for(0.3)
    s80 = tv('sb') > tv('sa')
    typ2('mtmode 01 c.txt', 2.0)
    s40 = (tv('sa'), tv('sb'), tv('ncols'))
    A.drag(k, *(cxy(2, 5) + cxy(5, 10))); k.run_for(0.3)
    mv(4, 4); k.run_for(0.5)
    sl = slot(k, n, 2000) or bytes(2000)
    hl = [drawn(3, 20) == inv(g(sl[(3 * 40 + 20) * 2])), drawn(3, 45) == g(32), drawn(4, 60) == g(32)]
    k.key('x', settle=False); k.run_for(2.0)
    typ2('mtmode 03 d.txt', 1.5); k.key('x', settle=False); k.run_for(2.0)
    check('a selection in 80 columns (%s), MTMODE 01: gone (%s: its columns 40 now); a drag there over rows 2-5: its cells '
          'inverse, the blanks past its 40 columns not (%s); MTMODE 03 back' % (s80, s40, hl), s80 and s40 == (0, 0, 40)
          and all(hl) and tv('ncols') == 80, (s80, s40, hl, tv('ncols')))
    # the mouse for the program in it: MTM33 P (it reset it, then polls 03h as TM5000G does), a short click given while it waits
    typ2('mtm33 p m.txt', 1.0)
    taken, rr, cc = tb('tdl') & 16, tv('top') + 3, 20
    mv(*cxy(rr, cc)); btn(1, 0.1)
    waitfile(k, 'M.TXT', 8.0); k.run_for(0.5)
    want, m = ' '.join('%04X' % v for v in (cc * 8, rr * 8, cc * 8, rr * 8, 1, 1)).encode(), A.disk_file(k, 'M.TXT')
    check('MTM33 P in the window (it reset the mouse: MT_TROWS\'s 16, %d), a short click on row %d, column %d while it waits: '
          'its 03h reads it down there, then up (the release held till it had read the press), one press and one release (%r)'
          % (taken, rr, cc, m), taken and m == want, (taken, m, want))
    k.run_for(1.0)
    mp = k.pc.u16(tx(n), equ('TX_MPSP'))
    A.drag(k, *(cxy(rr, 2) + cxy(rr, 6))); k.run_for(0.3)
    check('... it ended: the mouse no more its program\'s (TX_MPSP %04Xh, MT_TROWS\'s 16 %d), a drag selects again (%d, %d)'
          % (mp, tb('tdl') & 16, tv('sa'), tv('sb')), mp == 0 and not tb('tdl') & 16 and tv('sb') > tv('sa'), (mp, tv('sa'), tv('sb')))
    # MTM33 R: the same click, its release read by 06h alone (not 03h): given after its first 06h, not a click late
    typ2('mtm33 r r.txt', 1.0)
    mv(*cxy(rr, cc + 5)); btn(1, 0.1)
    waitfile(k, 'R.TXT', 8.0); k.run_for(0.5)
    want, m = ('0001 %04X %04X' % ((cc + 5) * 8, rr * 8)).encode(), A.disk_file(k, 'R.TXT')
    check('MTM33 R (06h only, till a release), a short click while it waits: its release there, one (%r): the release held '
          'given after its first 06h too' % m, m == want, (m, want))
    k.run_for(1.0)
    # MTM33 P again, the click while it polls 03h (past its 36 ticks, nearly all its time in the driver with interrupts off):
    # its ticks still come (pcemu: an IRQ held while IF is clear taken when it is set again), so it is switched from and
    # the UI sees the click
    typ2('mtm33 p m2.txt', 1.0); k.run_for(2.5)
    sw, prev, swa = [0], k.pc.watch, seg * 16 + Y['mt_switch']
    def w(a):
        if prev: prev(a)
        if a == swa: sw[0] += 1
    k.pc.watch = w; k.run_for(1.0); k.pc.watch = prev
    mv(*cxy(rr, cc)); btn(1, 0.1)
    waitfile(k, 'M2.TXT', 3.0); k.run_for(0.5)
    want, m = ' '.join('%04X' % v for v in (cc * 8, rr * 8, cc * 8, rr * 8, 1, 1)).encode(), A.disk_file(k, 'M2.TXT')
    check('MTM33 P, a short click while it polls 03h: switched from there (%d switches in 1 s), the click its own (%r)'
          % (sw[0], m), sw[0] >= 12 and m == want, (sw[0], m, want))
    k.run_for(1.0)
    # MTM33 F (reset, reading 03h only after "q"): a click's release held; Shift-drag selects over it; CODE-Tab: no button down
    typ2('mtm33 f f.txt', 1.5)
    mv(*cxy(rr, cc)); btn(1, 0.3)
    rel, np0 = k.pc.rd(tx(n), equ('TX_MREL'), 1)[0], m33(n, 'm33_np')
    k.pc.wr(0x40, 0x17, bytes([k.pc.rd(0x40, 0x17, 1)[0] | 2]))
    A.drag(k, *(cxy(rr, 2) + cxy(rr + 1, 6))); k.run_for(0.3)
    k.pc.wr(0x40, 0x17, bytes([k.pc.rd(0x40, 0x17, 1)[0] & 0xFC]))
    ss, np1 = (tv('sa'), tv('sb')), m33(n, 'm33_np')
    hot(k); k.run_for(1.0)
    fr, live, rel2 = tstate(k)[1], k.u16('m33_btn') & 3, k.pc.rd(tx(n), equ('TX_MREL'), 1)[0]
    check('MTM33 F (it reset the mouse, not reading 03h while it waits for keys): a click, its press given (%d), the release held (TX_MREL %02Xh); '
          'Shift held, a drag: a selection (%s), not the program\'s (its presses still %d); CODE-Tab (front %d): the release '
          'given first, no button down in the driver (%d, TX_MREL %02Xh)' % (np0, rel, ss, np1, fr, live, rel2),
          np0 == 1 and rel & 0xC0 == 0xC0 and ss[1] > ss[0] and np1 == 1 and fr == n and live == 0 and rel2 == 0,
          (np0, rel, ss, np1, fr, live, rel2))
    k.key('q', settle=False); k.run_for(1.0)
    fc = (A.disk_file(k, 'F.TXT') or b'')[:4]
    check('... its event handler (0Ch, every event) not called behind for the click nor the drag (F.TXT: %r)' % fc,
          fc == b'0000', fc)
    to0()
    # MT_TMOUSE from a task: refused
    typ2('mtprobe > pr.txt', 4.0)
    for _ in range(30):                 # (its lines once it has got that far: a window behind, its turns shared)
        if (A.disk_file(k, 'PR.TXT') or b'').count(b'\nF021') >= 4: break
        k.run_for(1.0)
    l5 = [l for l in (A.disk_file(k, 'PR.TXT') or b'').decode('latin-1').split('\n') if l.startswith('F021')]
    check('MT_TMOUSE (F0h 21h) called by a task (MTPROBE in the window), for task 0, 7, 8 and itself: refused (AX = 1: the '
          'UI\'s call only)', len(l5) == 4 and all('CF=1 AX=0001' in l for l in l5),
          (l5, tstate(k), (A.disk_file(k, 'PR.TXT') or b'')[-200:], slot_text(k, n)[-300:]))
    check('... every switch at a safe point (the audit)', not au.bad(), au.bad()[:3])
    # its close box (EV_CLOSE: TERM.RUN asks for API 9): asked; ESC keeps it all, nothing typed to the task; Return ends it
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    n4 = tnum('LCMD.COM')
    cx, cy = (wv(0) + wv(4) - 2) * 8 + 4, wv(2) + 8                    # (its title strip's last cell but one)
    kn = equ('TX_KN')
    put = lambda: (k.pc.rd(tx(n4), kn, 1)[0] + k.pc.rd(tx(n4), kn + 1, 1)[0]) % 32   # (keys ever put in its ring)
    p0 = put()
    A.click(k, cx, cy); k.run_for(0.5)
    b1 = k.band()
    k.key(ktest.ESC, settle=False); k.run_for(1.0)
    p1, alive = put(), (tnum('LCMD.COM'), mb('mw_n'))
    check('CODE-P: a terminal window with a close box (W_FLAGS %d): a click there asks in the band (%s); ESC: the window '
          'and its task (%d) as they were, the ESC not typed to it' % (wv(12), b1, n4), wv(12) & 2 and n4 != 7
          and any('Confirm to end LCMD.COM' in l for l in b1) and alive == (n4, 1) and p1 == p0, (wv(12), b1, alive, p0, p1))
    k.key(ktest.ESC, settle=False); k.run_for(0.5)
    p2 = put()
    A.click(k, cx, cy); k.run_for(0.5)
    k.key(ktest.ENTER, settle=False); k.run_for(2.0)
    check('... an ESC typed in the window still goes to the task (%d key); the close box again, Return: the task ended '
          '(MT_KILL), its window closed, the Executive in front (%s)' % ((p2 - p1) % 32, k.band()),
          (p2 - p1) % 32 == 1 and mb('mw_n') == 0 and tnum('LCMD.COM') == 7 and any('LCMD.COM ended' in l for l in k.band()),
          ((p2 - p1) % 32, mb('mw_n'), tstate(k), k.band()))
    # the menu's items are their keys: Paste on a note (a key there brings the task to the front) does that, as CODE-V would
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    n5 = tnum('LCMD.COM')
    setclip(b'echo q\n')
    typ2('mtmode 40 n.txt t', 3.0)
    f0 = tstate(k)[1]
    to0()
    mv(*cxy(tv('top') + 2, 10)); btn(2, 0.5)
    o, nt = scr(), tb('note')
    k.key(ktest.ENTER, settle=False); k.run_for(1.0)
    f1, ps = tstate(k)[1], tv('pseg')
    k.key('x', settle=False); k.run_for(2.0); k.key('x', settle=False); k.run_for(2.0)
    check('MTMODE 40 T in a window (task %d, in front: %d), CODE-Tab away: its note (%d); a right click: the menu (Paste, '
          'Full screen); Return on Paste: the task in front (%d), as a key typed there, nothing pasted' % (n5, f0, nt, f1),
          f0 == n5 and nt == 1 and 'Paste          CODE-V' in o and 'Full screen    CODE-Tab' in o and f1 == n5 and ps == 0
          and A.disk_file(k, 'N.TXT') == b'ok', (f0, nt, o[-400:], f1, ps, A.disk_file(k, 'N.TXT')))
    # TM5000G in a window: its mouse works there (Return on it: a text program)
    if not os.path.exists(A.TM5000G):
        print('(no TM5000G.EXE: skipped)'); return
    k = boot('mt_t4g.img', b'MULTITASK=1\r\n', 88, TERMRUN, TERMFNT, 'TM5000G.EXE=' + A.TM5000G, mouse=True,
             chip=A.sim7210.NEC7210(A.sim7210.bus()))
    T = TermView(k)                     # (this machine's)
    mb, base, tv, tb, wv, scr, tnum, tx, TS = T.mb, T.base, T.tv, T.tb, T.wv, T.scr, T.tnum, T.tx, T.TS
    typ2, cxy, drawn, mv, btn, page, clip, to0 = T.typ2, T.cxy, T.drawn, T.mv, T.btn, T.page, T.clip, T.to0
    seg = mt_seg(k)
    k.select('TM5000G.EXE'); k.key(ktest.ENTER, settle=False)
    n = 7
    for _ in range(60):
        k.run_for(1.0)
        n = tnum('TM5000G.EXE')
        if n != 7 and 'Mouse support enabled.' in slot_text(k, n): break
    t1 = slot_text(k, n) if n != 7 else ''
    k.key(ktest.ENTER, settle=False)
    for _ in range(20):
        k.run_for(0.5)
        if 'Mouse: ON' in slot_text(k, n): break
    t2 = slot_text(k, n)
    mv(*cxy(5, 10)); btn(1, 2.0)
    t3 = slot_text(k, n)
    k.key(ktest.ESC, settle=False); k.run_for(2.0)
    k.key('1', settle=False); k.run_for(2.0)
    t4 = slot_text(k, n)
    k.key(ktest.ESC, settle=False); k.run_for(2.0)
    t4b = slot_text(k, n)
    mv(*cxy(5, 10)); btn(1, 2.0)
    t5, fr = slot_text(k, n), tstate(k)[1]
    check('TM5000G.EXE: Return on it, in a terminal window (task %d, still behind: front %d): "Mouse support enabled.", '
          '"Mouse: ON"; a click on its row 5 in the window: "Module Configuration" (not there before); ESC, its key "1" and ESC '
          '(its pointer hidden twice): a click there again still its own' % (n, fr), n != 7 and fr == 0 and mb('mw_n') == 1
          and 'Mouse support enabled.' in t1 and 'Mouse: ON' in t2 and 'Module Configuration' not in t2
          and 'Module Configuration' in t3 and 'Module Configuration' in t4 and 'Module Configuration' not in t4b
          and 'Module Configuration' in t5, (n, fr, t2[:300], t3[:300], t4b[:300], t5[:300]))
    k.key(ktest.ESC, settle=False); k.run_for(1.0); k.key('0', settle=False)
    for _ in range(20):
        k.run_for(0.5)
        if tnum('TM5000G.EXE') == 7: break
    check('... "0": it ends, its window closes', tnum('TM5000G.EXE') == 7 and mb('mw_n') == 0, (tstate(k), mb('mw_n')))

MTTM = os.path.join(HERE, 'MTTERM.COM')

def t_wwait():
    print('== a window moved or resized with a task computing behind (audit3 X32); a window .RUN\'s message in the '
          'band through the saver (X38)')
    k = boot('mt_ww.img', b'MULTITASK=1\r\nTIDY=0\r\n', 88, TERMRUN, TERMFNT, mouse=True)
    seg, Y = mt_seg(k), k.Y
    cur = lambda: k.pc.rd(seg, Y['mt_cur'], 1)[0]
    T = TermView(k)
    TS, base, wv, tnum, mv = T.TS, T.base, T.wv, T.tnum, T.mv
    def turns(t=1.0):                   # in how many of t s's 10 ms looks task n is the one running
        c = 0
        for i in range(int(t * 100)):
            k.pc.run_for(0.01); c += cur() == n
        return c
    au = Audit(k)
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    n = tnum('LCMD.COM')
    k.key('mtspin 250 sw.txt', settle=False); k.key(ktest.ENTER, settle=False); k.run_for(1.0)
    r0, w0 = turns(), [wv(o) for o in (0, 2, 4, 6)]
    got = {}
    for what, start, end in (('CODE-F8', 0x6F00, ktest.ESC), ('CODE-F7', 0x6E00, ktest.ESC),
                             ('corner', (wv(0) + wv(4) - 1) * 8 + 4, wv(2) + wv(6) - 4),
                             ('title', (wv(0) + 20) * 8, wv(2) + 6)):
        if what.startswith('CODE'):     # (waiting for a key: mw_size's loop, and win_mv's)
            k.key(start, settle=False); k.run_for(0.3)
            got[what] = turns()
            k.key(end, settle=False); k.run_for(0.5)
        else:                           # (held down, the mouse still: mw_size's drag, and win_mv's)
            mv(start, end); k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.3)
            got[what] = turns()
            k.pc.mouse_move(0, 0, 0); k.run_for(0.5)
    w1 = [wv(o) for o in (0, 2, 4, 6)]
    check('MTSPIN computing in a terminal window (task %d: %d of 100 looks alone): while its window waits for a key to '
          'resize it (CODE-F8, mw_size) or move it (CODE-F7, win_mv), or its corner or title strip is held down with the '
          'mouse still, MTSPIN runs on (%s of 100), every switch at a safe point; ESC or the release: as it was'
          % (n, r0, got), n != 7 and r0 > 50 and all(v > 30 for v in got.values()) and w1 == w0 and not au.bad(),
          (n, r0, got, w0, w1, au.bad()[:3]))
    # X38: a window .RUN that can't start (CODE-K, no CALC.RUN): the band keeps its message through the saver
    k.key(A.CODE['K'], settle=False); k.run_for(1.0)
    b1 = k.band()
    st0 = k.u16('saver_t')
    k.wr('saver_t', struct.pack('<H', 18)); k.run_for(3.0)
    tm = bytes(k.rd('tmp', 8))
    k.key(ktest.DOWN, settle=False); k.run_for(1.0)
    b2 = k.band()
    k.wr('saver_t', struct.pack('<H', st0))
    k.key(ktest.ESC, settle=False); k.run_for(0.5)
    say = lambda b: any('CALC.RUN is not on this disk' in l for l in b)
    check('CODE-K with no CALC.RUN on the disk: "CALC.RUN is not on this disk" in the band (%s); the saver meanwhile '
          '(tmp then %r), and a key ends it: the band says it again (%s)' % (b1[:1], tm, b2[:1]), say(b1) and say(b2)
          and not k.crashed, (b1, tm, b2))

def t_wxor():
    print('== the Executive\'s XOR outlines cut around a window .RUN\'s window (M8c: mw_span\'s top, bottom and side rows)')
    k = boot('mt_wx.img', b'MULTITASK=1\r\n', 88, A.CALCRUN, mouse=True)
    seg, Y = mt_seg(k), k.Y
    CS = A.run_syms('apps/CALC.ASM')
    k.key(A.CODE['K']); k.run_for(0.5)
    c, y, w, h = (k.pc.u16(k.useg, k.pc.u16(seg, Y['mw_ses'] + SE_SIZE + SE_BASE) + CS['win'] + o) for o in (0, 2, 4, 6))
    A.click(k, 4, 72); k.run_for(0.3)               # (the Executive in front, the calculator on top)
    A.point(k, 639, 399); k.run_for(0.3)
    rects = (((c - 4) * 8 + 3, (c + 4) * 8 + 2, y + 10, 30),        # x0, x1 (pixels), y0, rows: its left side out,
             ((c - 2) * 8 + 1, (c + w - 3) * 8 + 4, y - 6, h + 12),  #  its right in; across its top and bottom;
             ((c - 9) * 8 + 2, 638, y + 30, 50),                      #  across all of it; its left side and bottom
             ((c + 2) * 8 + 5, 637, y + 5, h),                        #  in; its top above, its bottom in; wholly in
             ((c - 6) * 8 + 7, (c + 1) * 8 + 6, y - 20, 40),
             ((c + 3) * 8 + 1, (c + 5) * 8 + 4, y + 8, 12))
    REGS = ('ax', 'bx', 'cx', 'dx', 'si', 'di', 'bp', 'ds', 'es', 'flags')
    scr = lambda: bytes(k.pc.rd(0xB800, 0, 0x8000))
    st, got, rows = {'i': 0, 'go': False}, [], [0, 0]
    def xh(pc):                         # xor_rect called from the Executive's idle point, one rectangle a time
        if pc.r('cs') == seg and pc.r('ip') in (Y['mw_span.xl'], Y['mw_span.xs']):
            rows[pc.r('ip') == Y['mw_span.xs']] += 1
        if pc.r('cs') != k.useg or pc.r('ip') != Y['..@ui_idle'] or st['i'] >= len(rects): return
        if not st['go']:
            if pc.rd(seg, Y['mw_cur'], 1)[0]: return
            st['regs'], st['s0'] = {r: pc.r(r) for r in REGS}, scr()
            x0, x1, y0, n = rects[st['i']]
            pc.push(Y['..@ui_idle'])
            pc.w('ax', x0); pc.w('di', x1); pc.w('dx', y0); pc.w('cx', n); pc.w('ip', Y['xor_rect'])
            st['go'] = True; pc.mu.emu_stop()
        else:
            s0, s1 = st['s0'], scr()
            got.append({(xb * 8 + b, r) for r in range(400) for xb in range(80) for b in range(8)
                        if (s0[(r & 3) * 0x2000 + (r >> 2) * 80 + xb] ^ s1[(r & 3) * 0x2000 + (r >> 2) * 80 + xb]) & (0x80 >> b)})
            for r, v in st['regs'].items(): pc.w(r, v)
            st['go'] = False; st['i'] += 1
    k.hooks.append(xh)
    for _ in range(40):
        k.run_for(0.1)
        if st['i'] >= len(rects): break
    k.hooks.remove(xh)
    want = []
    for x0, x1, y0, n in rects:         # the outline unclipped, less the calculator's box
        p = {(x, r) for r in (y0, y0 + n - 1) for x in range(x0, x1 + 1)} | {(x, r) for r in range(y0, y0 + n) for x in (x0, x1)}
        want.append({(x, r) for x, r in p if not (c * 8 <= x < (c + w) * 8 and y <= r < y + h)})
    check('six outlines XORed by the Executive (xor_rect) with the calculator on top (column %d, row %d, %dx%d): each '
          'drawn exactly but where the calculator is (%s pixels), its rows cut a row at a time (%d top or bottom, %d '
          'side rows)' % (c, y, w, h, [len(g) for g in got], rows[0], rows[1]), len(got) == len(rects) and got == want
          and rows[0] > 0 and rows[1] > 0 and not want[-1] and all(want[:-1]) and not k.crashed,
          ([(len(g), len(v), len(g - v), len(v - g)) for g, v in zip(got, want)], rows, k.crashed))

def t_peek():
    print('== a window .RUN\'s file read from one open (R43): every way it can\'t start closes it')
    hdr = lambda api, img, bss, na, nr, fl: b'GRUN' + struct.pack('<6H', api, img, bss, na, nr, fl)
    fakes = (('NOWIN.RUN', hdr(5, 0x100, 0, 0, 0, 0)),          # not a window .RUN (cut short: run_app says so)
             ('WBAD.RUN', hdr(6, 0x10, 0, 0x2000, 0x2000, 1)),  # its fixups past 4000h words: mw_start's .bad
             ('WROOM.RUN', hdr(6, 0x10, 0xFF00, 0, 0, 1)),      # no slot that big: .room
             ('WCUT.RUN', hdr(6, 0x200, 0, 0, 0, 1)))           # its image cut short: mw_load's
    for n, b in fakes: open(os.path.join(A.OUT, n), 'wb').write(b)
    k = boot('mt_peek.img', b'MULTITASK=1\r\n', 88, A.CALCRUN, *(os.path.join(A.OUT, n) for n, b in fakes), mouse=True)
    seg, Y = mt_seg(k), k.Y
    mb = lambda n: k.pc.rd(seg, Y[n], 1)[0]
    fh = lambda: k.pc.u16(seg, Y['mw_fh'])
    s0, MW_MAX = sft_used(k), 4                     # (KMW.INC's)
    def tries(name, n):
        """Return on it n times: [the band's first line each time], every handle back each time."""
        out, ok = [], True
        for _ in range(n):
            k.select(name); k.key(ktest.ENTER, settle=False); k.run_for(0.4)
            out.append((k.band() or [''])[0])
            ok = ok and fh() == 0 and sft_used(k) == s0
            k.key(ktest.ENTER, settle=False); k.run_for(0.3)    # (the message gone)
        return sorted(set(out)), ok and fh() == 0 and sft_used(k) == s0
    # no window open: run_app's (mw_run's .orig) 22 times, past the root's 20 handles; mw_start's refusals
    r = [tries('NOWIN.RUN', 22)] + [tries(n, 3) for n in ('WBAD.RUN', 'WROOM.RUN', 'WCUT.RUN')]
    check('no window open: Return on NOWIN.RUN (not a window .RUN, cut short) 22 times, and 3 times each on WBAD.RUN, '
          'WROOM.RUN, WCUT.RUN (window .RUNs that can\'t start: their header, no room, cut short): each refused (%s), '
          'mw_peek\'s file closed each time (mw_fh 0, the SFT as it was), nothing running' % [x[0] for x in r],
          all(ok for x, ok in r) and all(x[0] and x[0][0] for x in r) and mb('mw_n') == 0 and k.rd('run_active', 1) == b'\x00',
          (r, mb('mw_n'), fh(), sft_used(k), s0))
    # a window open (the calculator), the Executive in front: mw_run's .ses, and mw_start's refusals from there
    k.key(A.CODE['K']); k.run_for(0.5)
    A.click(k, 4, 340); k.run_for(0.3)              # (the Executive's information line)
    c0 = mb('mw_cur')
    r = [tries(n, 3) for n in ('NOWIN.RUN', 'WBAD.RUN', 'WCUT.RUN')]
    check('the calculator open, the Executive in front (%d): Return on NOWIN.RUN ("%s"), WBAD.RUN and WCUT.RUN 3 times '
          'each: refused, the file closed each time; the calculator alone still' % (c0, r[0][0][0]),
          c0 == 0 and all(ok for x, ok in r) and r[0][0] == ['NOWIN.RUN needs the whole screen: close the windows first']
          and mb('mw_n') == 1, (r, c0, mb('mw_n'), fh(), sft_used(k), s0))
    # CALC.RUN till too many (MW_MAX): the last ones refused with their file closed; then each opened is a calculator
    nn = []
    for _ in range(MW_MAX + 1):
        A.click(k, 4, 340); k.run_for(0.3)
        k.select('CALC.RUN'); k.key(ktest.ENTER, settle=False); k.run_for(0.6)
        nn.append((mb('mw_n'), fh(), sft_used(k) == s0))
        k.key(ktest.ENTER, settle=False); k.run_for(0.3)
    check('Return on CALC.RUN %d times with the Executive in front: sessions %s (the last refused, too many), '
          'mw_peek\'s file closed each time, the SFT as it was' % (MW_MAX + 1, [n for n, f, s in nn]),
          [n for n, f, s in nn] == [2, 3, 4, 4, 4] and all(f == 0 and s for n, f, s in nn) and not k.crashed, (nn, A.screen(k)))

def t_tname():
    print('== a terminal window\'s title: its program\'s name in TERM.RUN\'s argument, from MT (R65)')
    k = boot('mt_tn.img', b'MULTITASK=1\r\n', 88, TERMRUN, TERMFNT, 'X.COM=' + MTLN, 'ABCDEFGH.EXE=' + MTLN, 'SUB\\',
             'SUB\\INSUB.COM=' + MTLN, mouse=True)
    seg, Y = mt_seg(k), k.Y
    T = TermView(k)
    TS, base, wv, scr, mb = T.TS, T.base, T.wv, T.scr, T.mb
    cstr = lambda off: bytes(k.pc.rd(k.useg, off, 40)).split(b'\0')[0].decode('latin-1')
    def opened(name, close=False):
        """Return on it: (its window's title, TERM's argument as MT gave it, as it should be, the title on the screen,
        the close box's question); then a line typed ends it, and the window with it."""
        if k.rd('msgshown', 1)[0]: k.key(ktest.ENTER)       # (the last one's "ended" cleared)
        k.select(name); k.key(ktest.ENTER, settle=False); k.run_for(3.0)
        n, c = k.pc.rd(seg, Y['mw_ses'] + SE_SIZE + SE_TASK, 2)
        nm = bytes(k.pc.rd(seg, task_ent(k, n) + TE_NAME, 12)).split(b'\0')[0].decode('latin-1')
        title, arg = cstr(wv(8)), cstr(base() + TS['arg'])
        got = (title, arg, '%d %d %s' % (n, c, nm), title in scr() if title else None, None)
        if close:
            A.click(k, (wv(0) + wv(4) - 2) * 8 + 4, wv(2) + 8); k.run_for(0.5)
            got = got[:4] + ((k.band() or [''])[0],)
            k.key(ktest.ESC, settle=False); k.run_for(0.5)
        k.key('q', settle=False); k.key(ktest.ENTER, settle=False); k.run_for(2.0)
        return got + (mb('mw_n'),)
    r1 = opened('X.COM')
    r12 = opened('ABCDEFGH.EXE', close=True)
    check('Return on X.COM and on ABCDEFGH.EXE (a whole 8.3 name: TE_NAME without its NUL): each in a window titled with '
          'its name (%r, %r), from TERM\'s argument "task count name" (%r, %r), drawn in its strip; the close box asks '
          'with it (%r); each window gone with its task' % (r1[0], r12[0], r1[1], r12[1], r12[4]),
          r1[:4] == ('X.COM', r1[2], r1[2], True) and r1[1].endswith(' X.COM') and r12[:4] == ('ABCDEFGH.EXE', r12[2], r12[2], True)
          and r12[4] == 'Close: Confirm to end ABCDEFGH.EXE' and r1[5] == r12[5] == 0, (r1, r12))
    # in a subject: the path's last part
    if k.rd('msgshown', 1)[0]: k.key(ktest.ENTER)
    A.pick_subject(k, 'SUB'); k.key(ktest.TAB); k.run_for(0.3)
    rs = opened('INSUB.COM')
    check('Return on INSUB.COM in subject SUB (its path A:\\SUB\\INSUB.COM): the title its name only (%r), argument %r'
          % (rs[0], rs[1]), rs[:4] == ('INSUB.COM', rs[2], rs[2], True) and rs[5] == 0, rs)
    # a task with no name (TE_NAME emptied as mt_uwin asks for it): no title, the strip still there
    from unicorn import UC_HOOK_CODE, x86_const as X
    lin = seg * 16 + Y['mt_uname']
    def blank(mu, a, sz, u):
        k.pc.wr(seg, mu.reg_read(X.UC_X86_REG_BX) + 10, b'\0' * 12)
    hk = k.pc.mu.hook_add(UC_HOOK_CODE, blank, None, lin, lin); k.pc.mu.ctl_remove_cache(lin, lin + 1)
    if k.rd('msgshown', 1)[0]: k.key(ktest.ENTER)
    A.pick_subject(k, 'Root'); k.key(ktest.TAB); k.run_for(0.3)
    rn = opened('X.COM', close=True)
    k.pc.mu.hook_del(hk)
    check('a task with no name: its window opens untitled (%r; the argument %r ends with the blank), the close box asks '
          '"%s"; it ends, the window with it' % (rn[0], rn[1], rn[4]), rn[0] == '' and rn[1] == rn[2] and rn[1].endswith(' ')
          and rn[4].rstrip() == 'Close: Confirm to end' and rn[5] == 0 and not k.crashed, rn)
    # TERM.RUN started by hand (X52): no task to show, so it says how it is opened, in the band till a key
    if k.rd('msgshown', 1)[0]: k.key(ktest.ENTER)
    k.select('TERM.RUN'); k.key(ktest.ENTER, settle=False); k.run_for(2.0)
    b = k.band() or ['']
    k.key(ktest.ESC, settle=False); k.run_for(0.5)
    check('TERM.RUN started by hand from the Executive: no window, and the band says how one opens (%r)' % b[0],
          b[0] == 'Opened by Return or CODE-P on a text program' and mb('mw_n') == 0 and not k.crashed, (b, mb('mw_n')))

QUITRUN = os.path.join(HERE, 'QUITRUN.RUN')

def t_wroot():
    print('== the root starting over with window .RUNs open (one\'s INT 21h 4Ch): every session forgotten, the blocks '
          'freed (mw_clean)')
    k = boot('mt_wr.img', b'MULTITASK=1\r\n', 88, QUITRUN, mouse=True)
    seg, Y = mt_seg(k), k.Y
    mb = lambda n: k.pc.rd(seg, Y[n], 1)[0]
    free0 = A.free_paras(k)
    for i in (1, 2):                    # (two of it, each with blocks of 64 and 32 paragraphs)
        if mb('mw_cur'): A.click(k, 8, 100); k.run_for(0.3)
        k.select('QUITRUN.RUN'); k.key(ktest.ENTER); k.run_for(1.0)
    n2, c2, f2 = mb('mw_n'), mb('mw_cur'), A.free_paras(k)
    nc = [0]
    def ch(pc):
        if pc.r('cs') == seg and pc.r('ip') == Y['mw_clean'] and pc.rd(seg, Y['mw_n'], 1)[0]: nc[0] += 1
    k.hooks.append(ch)
    k.key('Q'); k.run_for(2.0); k.settle()
    k.hooks.remove(ch)
    uses = [k.pc.rd(seg, Y['mw_ses'] + i * SE_SIZE, 1)[0] for i in range(1, 5)]
    check('two QUITRUN.RUNs open (%d, the second in front), Q in it: INT 21h 4Ch, the Executive starts over (mw_clean '
          'with sessions: %d); none left (%s), no clipping, its blocks and the first\'s freed: the memory as before (%s)'
          % (n2, nc[0], uses, A.free_paras(k)), n2 == 2 and c2 == 2 and f2 != free0 and nc[0] == 1 and mb('mw_n') == 0
          and mb('mw_cur') == 0 and mb('mw_cp') == 0 and uses == [0] * 4 and k.rd('run_active', 1) == b'\x00'
          and A.free_paras(k) == free0 and A.has(k, 'Select a file and confirm') and not k.crashed,
          (n2, c2, nc, uses, mb('mw_n'), mb('mw_cp'), A.free_paras(k), free0, f2, k.band(), k.crashed))
    k.select('QUITRUN.RUN'); k.key(ktest.ENTER); k.run_for(1.0)
    up = (mb('mw_n'), A.has(k, 'Quit test'))
    k.key(ktest.ESC); k.run_for(1.0)
    check('... then QUITRUN.RUN again: it opens (%s), ESC: it ends, the memory as before' % (up,), up == (1, True)
          and mb('mw_n') == 0 and A.free_paras(k) == free0 and not k.crashed, (up, mb('mw_n'), A.free_paras(k), free0))

MTPB = os.path.join(HERE, 'MTPUB.COM')

def t_tpub():
    print('== terminal windows (T5b): a screen a program publishes (MT_PUB), drawn in its window with its own font')
    import ctypes
    k = boot('mt_t5b.img', b'MULTITASK=1\r\n', 88, TERMRUN, TERMFNT, MTPB, MTTM, mouse=True)
    seg, Y = mt_seg(k), k.Y
    T = TermView(k)
    mb, TS, base, tv, tb, scr, tnum, tx = T.mb, T.TS, T.base, T.tv, T.tb, T.scr, T.tnum, T.tx
    drawn, cxy, mv, btn, page, clip, typ2, to0 = T.drawn, T.cxy, T.mv, T.btn, T.page, T.clip, T.typ2, T.to0
    TXP, TXPP, BUF = equ('TX_PUB'), equ('TX_PPSP'), TS['BUF']
    pubd = lambda n: (k.pc.u16(tx(n), TXP), k.pc.u16(tx(n), TXP + 2), k.pc.u16(tx(n), TXPP))
    def glyph(c, a, mark=False):        # MTPUB's glyph for code c, drawn with cell's attribute a, as TERM maps it
        c = 0x20 if c < 0x20 else 0x3F if c >= 0x48 else c
        b = [(c * 13 + r * 29) & 0xFF for r in range(16)]
        if a & 1: b = [x ^ 0xFF for x in b]
        if a & 2: b[14] = 0 if a & 1 else 0xFF
        if mark: b[14] ^= 0xFF; b[15] ^= 0xFF
        return bytes(b)
    def cellc(r, c):                    # MTPUB's cell (r, c): code, attribute
        if r == 24 and c < 6: return (0x05, 0xF0, 0x80, 0x81, 0x47, 0x20)[c], 0
        return 0x20 + (r * 7 + c) % 40, (c >> 3) & 3
    def rowok(r, skip=()):
        return all(drawn(r, c) == glyph(*cellc(r, c)) for c in range(tv('cols')) if c not in skip)
    def setclip(data):                  # (no page: no copy made, the clipboard empty already)
        if page() is None: return
        ctypes.memmove(ctypes.addressof(k.pc.ems_store) + page() * 0x4000, data, len(data))
        k.wr('clip_len', struct.pack('<H', len(data)))
    def lines(f='PB.TXT'):
        return [l for l in (A.disk_file(k, f) or b'').decode('latin-1').split('\r\n') if l]
    def key(ch, t=0.8):
        k.key(ch, settle=False); k.run_for(t)
    au = Audit(k)
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    n = tnum('LCMD.COM')
    typ2('mtpub pb.txt', 2.0)
    pd, ok1 = pubd(n), 'P 0 %02X01' % n
    check('MTPUB run in a windowed LCMD (task %d): MT_PUB taken (%s: AL 1, a window shows it; AH its task), TX_PUB %04X:%04Xh '
          'in its memory, TX_PPSP its PSP (%04Xh); TERM given its cells (MT_TROWS\'s DL 32: %02Xh), its 25 rows; the view as '
          'if the cursor (row 23) were a row lower: rows %d on' % (n, lines()[:1], pd[1], pd[0], pd[2], tb('tdl'), tv('top')),
          lines()[:1] == [ok1] and pd[1] == pd[2] != 0 and tb('tdl') & 32 and tb('nrows') == 25 and tv('top') == 25 - tv('rows')
          and tv('cur') == 0x1700 and tb('nocur') == 0, (lines(), pd, tb('tdl'), tb('nrows'), tv('top'), hex(tv('cur'))))
    sp = [drawn(24, c) == glyph(*cellc(24, c)) for c in range(6)]
    check('its cells drawn with its own font, byte for byte, by its attributes (inverse, underlined, both): rows 10 and 24, '
          'and 23 but the cursor\'s cell, which has its mark (rows 14-15 inverted); row 24\'s codes 05h (below its first: '
          '20h\'s glyph), F0h, 80h, 81h (past its end: \'?\'), 47h (its last), 20h (its first): %s' % sp,
          rowok(10) and rowok(23, (0,)) and rowok(24) and drawn(23, 0) == glyph(*cellc(23, 0), mark=True) and all(sp),
          (rowok(10), rowok(23, (0,)), sp, drawn(23, 0).hex()))
    pcg = lambda: k.pc.u16(pd[1], pd[0] + 16)                      # (its PB_CHG, TX_CHG)
    txc = lambda: k.pc.u16(tx(n), equ('TX_CHG'))
    lat, g, pc0 = [], 0x2B, pcg()
    for _ in range(6):
        g = 0x21 if g == 0x2F else g + 1
        k.key('c', settle=False)
        for t in range(1, 13):
            k.run_for(0.055)
            if drawn(23, 10) == glyph(g, 1): break
        lat.append(t)
    k.run_for(0.5)
    check('"c" x 6, its cell (23, 10) changed and PB_CHG counted each time (%d to %d): drawn within 3 ticks (%s)'
          % (pc0, pcg(), lat), max(lat) <= 3 and lines()[-1] == 'C %02X' % g and pcg() == pc0 + 6, (lat, lines()[-2:], pc0, pcg()))
    k.key('t', settle=False)
    seen, prev_ = [], None
    for _ in range(44):                 # (36 ticks of its, and some)
        k.run_for(0.055)
        d = drawn(22, 0)
        if d != prev_: seen.append(d); prev_ = d
    for _ in range(40):
        if lines()[-1:] == ['T']: break
        k.run_for(0.1)
    t22 = 0x42
    for _ in range(36): t22 = 0x21 if t22 >= 0x2F else t22 + 1
    check('"t": 36 ticks computing (never waiting: its state TS_RUN throughout), its cell (22, 0) the next glyph at each '
          'and PB_CHG counted: drawn again %d times in 44 ticks (mw_tick sees PB_CHG: not only the 9 ticks\' heartbeat), '
          'each its glyph' % (len(seen) - 1), len(seen) - 1 >= 10 and lines()[-1] == 'T'
          and all(x in [glyph(c_, 0) for c_ in range(0x21, 0x30)] for x in seen[1:]), (len(seen), lines()[-2:]))
    # the cursor: hidden (no mark, the view where it was), moved, shown again
    key('k')
    c1 = (drawn(23, 0) == glyph(*cellc(23, 0)), tb('nocur'), tv('top'))
    key('u')
    t1 = (tv('top'), drawn(5, 3) == glyph(*cellc(5, 3)))
    key('k')
    c2 = (drawn(5, 3) == glyph(*cellc(5, 3), mark=True), tv('top'))
    key('d')
    check('"k": PBF_NOCUR: no mark at (23, 0) (%s), the view as it was (%d); "u" (to row 5, column 3) while hidden: the view '
          'following it all the same, with no mark (T5d: MT_TROWS gives its row with bit 7; %d); "k": its mark at (5, 3), the view from its row (%d); "d": back to row 23, the view rows %d on'
          % (c1[0], c1[2], t1[0], c2[1], tv('top')), c1 == (True, 1, 6) and t1 == (5, True) and c2 == (True, 5) and tv('top') == 6
          and drawn(23, 0) == glyph(*cellc(23, 0), mark=True) and lines()[-4:] == ['K 03', 'U', 'K 01', 'D'],
          (c1, t1, c2, tv('top'), lines()[-4:]))
    key('r')
    fs = tv('fseg')
    r20 = (tb('nrows'), bytes(k.pc.rd(fs, BUF + 20 * 160, 5 * 160)) == b'\x20\x00' * 400, tv('top'))
    key('r')
    check('"r": PB_ROWS 20: TERM\'s rows %d, MT_TROWS\'s rows 20-24 blank (0020h: %s), the view in its 20 (rows %d on); "r": '
          '25 again, rows %d on' % (r20 + (tv('top'),)), r20 == (20, True, 1) and tb('nrows') == 25 and tv('top') == 6,
          (r20, tv('top'), lines()[-2:]))
    key('v')
    v40 = (tv('ncols'), all(drawn(10, c) == glyph(*cellc((400 + c) // 80, (400 + c) % 80)) for c in range(40)),
           all(drawn(10, c) == glyph(0x20, 0) for c in range(40, tv('cols'))))
    key('v')
    check('"v": PB_COLS 40, published again: TERM\'s columns %d; row 10 drawn from its cells read 40 a row (%s), blank past '
          'them (%s); "v": 80 again, row 10 as before' % v40, v40 == (40, True, True) and tv('ncols') == 80 and rowok(10)
          and lines()[-2:] == ['V 28', 'V 50'], (v40, tv('ncols'), lines()[-2:]))
    # Copy through its table; the menu: no Full screen, no menu with nothing that applies
    A.drag(k, *(cxy(24, 0) + cxy(24, 5))); k.run_for(0.3)
    mv(4, 4); k.run_for(0.3)
    k.key(A.CODE['C'], settle=False); k.run_for(0.5)
    cl = clip()
    A.click(k, *cxy(15, 40)); k.run_for(0.5)
    mv(*cxy(15, 40)); btn(2, 0.8)
    o1 = scr()
    k.key(ktest.ESC, settle=False); k.run_for(0.5)
    setclip(b'')
    beeps, prev, bp = [0], k.pc.watch, k.useg * 16 + k.Y['ui_beep']
    def w(a):
        if prev: prev(a)
        if a == bp: beeps[0] += 1
    k.pc.watch = w
    mv(*cxy(15, 40)); btn(2, 0.8)
    k.pc.watch = prev
    o2 = scr()
    k.key(ktest.ESC, settle=False); k.run_for(0.5)
    check('row 24\'s six cells selected, CODE-C: the clipboard %r (05h a blank, F0h and 81h \'?\' (0 in its table), 80h its '
          'table\'s \'A\', 47h \'G\', 20h a blank, dropped); a right click: only Paste (no Full screen); with the clipboard '
          'empty: no menu at all, and no beep (%d)' % (cl, beeps[0]), cl == b' ?A?G' and 'Paste          CODE-V' in o1
          and 'Full screen' not in o1 and 'Copy ' not in o1 and 'Paste' not in o2 and 'Full screen' not in o2 and beeps[0] == 0,
          (cl, o1[-400:], o2[-400:], beeps[0]))
    # CODE-Tab passes over it, MT_FRONT refuses it; another task's window beside it
    hot(k); k.run_for(1.0)
    f0 = tstate(k)[1]
    k.key(0x6D00, settle=False); k.run_for(1.0)
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    m = next((i for i, s_, nm in tstate(k)[0] if nm == 'LCMD.COM' and i != n), 7)
    typ2('mtlaunch /g:%d' % n, 2.0)
    o = scr()
    typ2('', 1.0)
    def trows(f, *a):                   # MTTERM R from this window: (CF, AX, BX, CX, DX, the 4000 bytes)
        typ2('mtterm r %d %s %s' % (n, f, ' '.join(map(str, a))), 2.0)
        b = A.disk_file(k, f.upper()) or bytes(4009)
        return (b[0],) + struct.unpack_from('<4H', b, 1) + (b[9:],)
    r0, r1, r2 = trows('t0.txt'), trows('t1.txt', 32768, 25), trows('t2.txt', 32768 + 5, 3)
    c1 = b''.join(struct.pack('<BB', *((g, 1) if (r, c) == (23, 10) else (t22, 0) if (r, c) == (22, 0) else cellc(r, c)))
                  for r in range(25) for c in range(80))
    check('MTTERM R (MT_TROWS from that window) for its task, as before T5b (DX 0): its pages (DL %02Xh, CX %04Xh, LCMD\'s '
          '"mtpub pb.txt" there); with DH 80h: its cells, all 2,000 as MTPUB has them (DL %02Xh, CL 80, CH its 25 rows: '
          '%04Xh, BX its cursor %04Xh); DX 8005h, 3 rows: its rows 5-7' % (r0[4] & 0xFF, r0[3], r1[4] & 0xFF, r1[3], r1[2]),
          r0[0] == 0 and r0[4] & 32 == 0 and r0[3] == 0x0350 and b'mtpub pb.txt' in r0[5][::2] and r1[0] == 0
          and r1[4] & 0xFF == 32 and r1[3] == 0x1950 and r1[2] == 0x1700 and r1[5] == c1 and r2[0] == 0
          and r2[5][:480] == c1[800:1280], (r0[:5], r1[:5], r2[:5], r0[5][:200:2], r1[5][:40].hex(), r2[5][:40].hex()))
    fr = []
    for _ in range(3):
        hot(k); k.run_for(1.0); fr.append(tstate(k)[1])
    to0()
    check('CODE-Tab with it the only other task: nothing (front %d); a second LCMD window (task %d): MTLAUNCH /G:%d there: '
          'MT_FRONT refused (error 5); CODE-Tab x 3: fronts %s (it passed over)' % (f0, m, n, fr), f0 == 0 and m != 7
          and 'MTLAUNCH: error 5' in o and fr == [m, 0, m], (f0, m, o[-300:], fr))
    typ2('exit', 2.0)
    for _ in range(3):
        if mb('mw_cur') == 1: break
        k.key(0x6D00, settle=False); k.run_for(1.0)
    # its pages while PBF_SHOWN is off; an old TERM (DX 0) given the pages always
    key('n')
    pg = (tb('tdl') & 32, 'MTPUB: pages' in scr(), tv('top'))
    key('s')
    sh = (tb('tdl') & 32, rowok(10))
    check('"n" (PBF_SHOWN off): its pages in the window ("MTPUB: pages", DL %02Xh; the view afresh: rows %d on); "s": its '
          'cells again (DL %02Xh)' % (pg[0], pg[2], sh[0]), pg == (0, True, 0) and sh == (32, True), (pg, sh))
    key('n')
    hot(k); k.run_for(1.0)
    fn = tstate(k)[1]
    k.key('s', settle=False); k.run_for(1.0)          # (in front: typed to it)
    fs_ = tstate(k)[1]
    k.key('p', settle=False); k.run_for(1.5)
    check('"n" again, CODE-Tab: in front (front %d: its pages shown, not passed over); "s" there: still in front (%d); "p" '
          '(published again, shown, in a text mode): back to its window (front %d), its cells drawn there'
          % (fn, fs_, tstate(k)[1]), fn == n and fs_ == n and tstate(k)[1] == 0 and tb('tdl') & 32 and rowok(10)
          and lines()[-1] == ok1, (fn, fs_, tstate(k), tb('tdl'), lines()[-3:]))
    # a picture: full screen (T3), CODE-Tab away from it and back, then back to its window
    key('g', 2.0)
    gf = (tstate(k)[1], k.pc.mode(), bytes(k.pc.rd(0xB800, 0, 256)) == bytes((((i_ * 5) ^ (i_ >> 8)) & 0xFF) for i_ in range(256)),
          k.pc.rd(tx(n), equ('TX_WGFX'), 1)[0])
    to0()
    hot(k); k.run_for(1.0)
    fg = tstate(k)[1]
    to0()
    o = scr()
    key('j', 2.0)
    f1 = tstate(k)[1]
    key('j', 2.0)
    check('"g": PBF_SHOWN off, mode 40h: in front by itself (front %d, mode %02Xh, its pattern %s, TX_WGFX %d); CODE-Tab to '
          'task 0, and from there onto it (front %d: in a graphics mode, not passed over); to task 0 again, its window\'s '
          'note; a key there: in front again (%d); a key: mode 3, back to its window, its cells there'
          % (gf[0], gf[1], gf[2], gf[3], fg, f1), gf == (n, 0x40, True, 1) and fg == n
          and 'In a graphics mode' in o and f1 == n and tstate(k)[1] == 0 and k.pc.mode() == 0x40 and tb('tdl') & 32
          and rowok(10) and lines()[-1] == 'G', (gf, fg, o[-300:], f1, tstate(k), lines()[-2:]))
    key('h', 2.0)
    h1 = tstate(k)[1]
    to0()
    o, hd = scr(), tb('tdl')
    hot(k); k.run_for(1.0)
    h2 = tstate(k)[1]
    key('j', 2.0)
    check('"h": mode 40h with PBF_SHOWN left on: in front by itself (front %d); CODE-Tab to task 0: the window\'s note, not '
          'its cells (DL %02Xh: in a graphics mode); CODE-Tab onto it (front %d: not passed over); a key: mode 3, back to its '
          'window' % (h1, hd, h2), h1 == n and 'In a graphics mode' in o and not hd & 32 and h2 == n
          and tstate(k)[1] == 0 and tb('tdl') & 32 and lines()[-2:] == ['G', 'G'], (h1, hd, h2, o[-300:], tstate(k), lines()[-2:]))
    # refused descriptors; a call it may not make
    key('b', 1.5)
    reg = k.pc.u16(seg, task_ent(k, n) + equ('TE_REG'))
    rsz = k.pc.u16(reg - 1, 3)                  # (its region: 1000h paragraphs at least, so the table at E-1000h:FFC0h
                                                #  starts in it and only the wrap past FFFFh refuses it)
    want = 'B' + ' 1 000D' * 14 + ' 1 0001' * 2 + (' 0 %02X01' % n) * 2
    check('"b": MT_PUB refused (0Dh) for ES:DI 0:400h, PB_VER 0, PB_COLS 0 and 81, PB_ROWS 0 and 26, PB_FIRST 21h, PB_GEND '
          '3Fh, PB_CELLS and PB_FONT 0:0, PB_FONT and PB_CELLS ending in the paragraph past its memory (by their sizes, 640 '
          'and 4,000 bytes), PB_XLAT past its segment\'s end (its start in its memory) and across its memory\'s end; CL 1 '
          'and 2 from a task (1); PB_XLAT its memory\'s last 128 bytes, and its own again: taken (its region %Xh '
          'paragraphs)' % rsz, lines()[-1] == want and rsz >= 0x1000, (lines()[-1], want, hex(rsz)))
    fb = next((s_ for s_, t_, o_, sz, nm in mcbs(k) if o_ == 0 and sz >= 4), None)
    if fb:                                      # (22 bytes in a free block: nothing's yet)
        k.pc.wr(fb + 1, 0, bytes(k.pc.rd(pd[1], pd[0], 22)))
        k.pc.wr(pd[1], pd[0] - 4, struct.pack('<HH', 0, fb + 1))
    else:
        k.pc.wr(pd[1], pd[0] - 4, struct.pack('<HH', 0x400, 0))    # (none: 0:400h, refused too, not 0:0)
    key('o')
    lo_ = lines()[-1:]
    k.pc.wr(pd[1], pd[0] - 4, struct.pack('<HH', 0x70, reg - 8))
    key('e')
    check('"o": a copy of its descriptor, valid but in a free block outside its memory (%s): refused (%s); "e": its table '
          'starting in the paragraph below its memory and ending in it (%04X:0070h): refused (%s); its own still published'
          % (fb and '%04X:0000' % (fb + 1), lo_, reg - 8, lines()[-1:]), fb and lo_ == ['O 1 000D']
          and lines()[-1] == 'E 1 000D' and pubd(n) == pd, (fb, lo_, lines()[-1:], pubd(n)))
    # a child: its end doesn't withdraw it; a child that publishes: its end withdraws that
    key('x', 2.0)
    px = pubd(n)
    key('y', 2.0)
    py, dy = pubd(n), tb('tdl') & 32
    key('p', 1.0)
    check('"x": a child MTPUB that publishes nothing ends (%s): MTPUB\'s still published (%s); "y": a child that publishes '
          'its own (%s) ends: withdrawn (TX_PUB, TX_PPSP %s), the window its pages (DL %02Xh); "p": published again'
          % (lines()[-5:-3], px == pd, lines()[-3:-2], py, dy), lines()[-5] == 'Y' and lines()[-4].startswith('X 0')
          and px == pd and lines()[-3] == 'Z 0 %02X01' % n and lines()[-2].startswith('X 0') and py == (0, 0, 0)
          and dy == 0 and lines()[-1] == ok1 and tb('tdl') & 32, (lines()[-7:], px, pd, py, dy))
    # T5d: its rows scrolled, its status row (24) staying: TERM moves what is drawn (scrl), the rest as cells finds it
    def allok():                        # the cells in view not drawn as its cells say (but the cursor's)
        co, cs_ = k.pc.u16(pd[1], pd[0] + 4), k.pc.u16(pd[1], pd[0] + 6)
        bad = []
        for r in range(tv('top'), tv('top') + tv('rows')):
            for c in range(tv('left'), tv('left') + tv('cols')):
                w = k.pc.u16(cs_, co + (r * 80 + c) * 2)
                if (r, c) != (23, 0) and drawn(r, c) != glyph(w & 0xFF, (w >> 8) & 3): bad.append((r, c))
        return bad
    sb, hits, prev = k.useg * 16 + base() + TS['scrl.m'], [0], k.pc.watch
    def ws(a):
        if prev: prev(a)
        if a == sb: hits[0] += 1
    k.pc.watch = ws
    b0 = allok()                        # (the pointer's cells: the UI's, over them)
    key('l')
    h1, b1 = hits[0], allok()
    k.key('lll', settle=False); k.run_for(1.0)
    k.pc.watch = prev
    b3 = allok()
    co, cs_ = k.pc.u16(pd[1], pd[0] + 4), k.pc.u16(pd[1], pd[0] + 6)
    sbad = [(r, c) for r in range(tv('rows')) for c in range(tv('cols')) if (tv('top') + r, tv('left') + c) != (23, 0)
            and k.pc.u16(tv('fseg'), TS['SHD'] + r * 160 + c * 2)
            != k.pc.u16(cs_, co + ((tv('top') + r) * 80 + tv('left') + c) * 2)]
    check('"l": its rows 1-23 moved up one, row 24 (its status) staying: TERM moves what is drawn (scrl: %d moves), every '
          'cell in view then as its cells say, byte for byte (%d not); "l" x 3 at once: so again (scrl: %d moves; %d not), '
          'TERM\'s shadow its cells (%d not; the mouse pointer\'s %d cells, the UI\'s, left out)'
          % (h1, len(b1), hits[0] - h1, len(b3), len(sbad), len(b0)), h1 >= 1 and hits[0] - h1 >= 1 and len(b0) <= 4
          and set(b1) <= set(b0) and set(b3) <= set(b0) and not sbad and lines()[-4:] == ['L'] * 4,
          (h1, hits[0], b0, b1[:5], b3[:5], sbad[:5], lines()[-4:]))
    s0 = (txc() + pcg()) & 0xFFFF
    key('w')
    pw, s1 = (pubd(n), tb('tdl') & 32), txc()
    key('p')
    s2 = (txc() + pcg()) & 0xFFFF
    check('"w", "p": the count a window sees (TX_CHG with PB_CHG while published) one up at each (%04Xh, %04Xh, %04Xh): PB_CHG '
          'kept in TX_CHG as it went' % (s0, s1, s2), s1 == (s0 + 1) & 0xFFFF and s2 == (s1 + 1) & 0xFFFF, (s0, s1, s2))
    key('q', 1.5)
    check('"w": withdrawn (%s: TX_PUB 0:0, DL %02Xh: its pages); "p": again; "q": it ends published: its end withdraws it '
          '(%s), the window LCMD\'s prompt again' % (lines()[-3], pw[1], pubd(n)), lines()[-3:] == ['W 0 %02X01' % n, ok1, 'Q']
          and pw == ((0, 0, 0), 0) and pubd(n) == (0, 0, 0) and not tb('tdl') & 32 and 'A:\\>' in scr(),
          (lines()[-3:], pw, pubd(n), scr()[-300:]))
    check('... every switch at a safe point (the audit)', not au.bad(), au.bad()[:3])
    typ2('exit', 2.0)
    # task 0 (the Executive's own prompt); no window (no TERM.RUN: in front); multitasking off
    sh_ = Shell(k)
    k.key('mtpub p0.txt', settle=False); k.key(ktest.ENTER, settle=False); k.run_for(2.0)
    k.key('q', settle=False); k.run_for(1.0)
    l0 = lines('P0.TXT')
    line(k, 'exit')
    k = boot('mt_t5b2.img', b'MULTITASK=1\r\n', 88, TERMFNT, MTPB)
    T = TermView(k)                     # (this machine's)
    mb, TS, base, tv, tb, scr, tnum, tx = T.mb, T.TS, T.base, T.tv, T.tb, T.scr, T.tnum, T.tx
    drawn, cxy, mv, btn, page, clip, typ2, to0 = T.drawn, T.cxy, T.mv, T.btn, T.page, T.clip, T.typ2, T.to0
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    n2 = tstate(k)[1]
    typ2('mtpub pf.txt', 2.0)
    hot(k); k.run_for(1.0)
    f2 = tstate(k)[1]
    hot(k); k.run_for(1.0)
    f3 = tstate(k)[1]
    key('q', 1.0)
    lf = lines('PF.TXT')
    k = boot('mt_t5b3.img', None, 88, MTPB)
    T = TermView(k)                     # (this machine's)
    mb, TS, base, tv, tb, scr, tnum, tx = T.mb, T.TS, T.base, T.tv, T.tb, T.scr, T.tnum, T.tx
    drawn, cxy, mv, btn, page, clip, typ2, to0 = T.drawn, T.cxy, T.mv, T.btn, T.page, T.clip, T.typ2, T.to0
    sh_ = Shell(k)
    k.key('mtpub po.txt', settle=False); k.key(ktest.ENTER, settle=False); k.run_for(2.0)
    k.key('q', settle=False); k.run_for(1.0)
    lo = lines('PO.TXT')
    check('MT_PUB refused from task 0 (the Executive\'s own prompt: %s, AX 5); from a task in front with no window (no '
          'TERM.RUN: task %d) taken, AL 0 (%s), and CODE-Tab from it to task 0 (%d) and back to it (%d: no window shows '
          'it, so not passed over); with multitasking off: refused, AX 1 (%s)' % (l0[:1], n2, lf[:1], f2, f3, lo[:1]),
          l0[:1] == ['P 1 0005'] and n2 != 0 and lf[:2] == ['P 0 %02X00' % n2, 'Q'] and f2 == 0 and f3 == n2
          and lo[:1] == ['P 1 0001'], (l0, n2, lf, f2, f3, lo))

def t_tcore():
    print('== a terminal window\'s calls (T1): MT_TROWS, a task\'s screen as MT keeps it; MT_TKEY, keys typed to it')
    k = boot('mt_tc.img', b'MULTITASK=1\r\n', 88, MTK, MTTM, MTSC)
    sh = Shell(k)
    sh.run('ver')
    tnum = TermView(k).tnum                                                        # (7: none such, a free one)
    def rows(n, f, *a):                     # MTTERM R: (CF, AX, BX, CX, DX, the 4000 bytes)
        sh.run('mtterm r %d %s %s' % (n, f, ' '.join(map(str, a))))
        b = A.disk_file(k, f.upper()) or bytes(4009)
        return (b[0],) + struct.unpack_from('<4H', b, 1) + (b[9:],)
    def keys(n, f, *kk):                    # MTTERM K: "cccc eeee"
        sh.run('mtterm k %d %s %s' % (n, f, ' '.join('%04X' % x for x in kk)))
        return A.disk_file(k, f.upper())
    # MTKEY R behind, its INT 16h read waiting (TS_WAITK); the front task's own keys still its (LCMD's prompt)
    typ(k, 'start /w mtkey.com r tk.txt', 1.0)
    n = tnum('MTKEY.COM')
    st0 = tstate(k)
    o = sh.run('ver')
    r0 = A.disk_file(k, 'TK.TXT')
    got = keys(n, 'k1.txt', 0x8500, 0x2D78)
    w = waitfile(k, 'TK.TXT', 3.0)
    k.run_for(0.5)
    o2 = sh.run('ver')                      # (a key left in the BIOS's buffer would come first: "xver")
    check('MTKEY R behind (task %s) waiting in its INT 16h read; VER typed in front still the front task\'s; MT_TKEY '
          'F11 (8500h: AH=00h doesn\'t give it) and "x" (2D78h): both taken (0002 0000), its read gets "x", as typed '
          '(2D78; F11 dropped, as the BIOS would), the BIOS\'s buffer never had them, and it ends' % n,
          n and (n, TS_WAITK, 'MTKEY.COM') in st0[0] and 'Lodestone version' in o and r0 is None
          and got == b'0002 0000' and w is not None and A.disk_file(k, 'TK.TXT') == b'2D78' and tnum('MTKEY.COM') == 7
          and 'Lodestone version' in o2 and 'Bad command' not in o2,
          (st0, o[-80:], r0, got, A.disk_file(k, 'TK.TXT'), tstate(k), o2[-80:]))
    # MTLINE behind, its DOS line read waiting in kbd_get (MT's key wait): the keys echoed in its own screen, its
    # changes counted; then Return, its line
    typ(k, 'start /w mtline.com tl.txt', 1.0)
    n = tnum('MTLINE.COM')
    a = rows(n, 'r1.txt')
    got = keys(n, 'k2.txt', 0x2368, 0x1769)
    k.run_for(1.0)
    b = rows(n, 'r2.txt')
    k.run_for(1.0)
    c = rows(n, 'r3.txt')
    sl = slot(k, n, 4000)
    txt = '\n'.join(''.join(chr(c[5][(r * 80 + i) * 2]) for i in range(80)).rstrip() for r in range(25))
    check('MTLINE behind (task %s) waiting for its line (DOS, in kbd_get: MT\'s key wait): "h", "i" with MT_TKEY taken '
          '(%s); echoed in its own screen (MT_TROWS: "MTLINE> hi", byte for byte its pages\' first 4000 bytes); its '
          'changes counted (%d, %d, then idle %d)' % (n, got, a[1], b[1], c[1]), n and a[0] == 0 and got == b'0002 0000'
          and 'MTLINE> hi' in txt and c[5] == sl and b[1] > a[1] and c[1] == b[1], (a[:5], b[:5], c[:5], txt[-200:]))
    tv = tvid(k, n)
    check('... and the rest: BX its cursor (%04X), CL 80 columns, CH mode 3, DL 0 (a text mode, not found writing the '
          'screen itself), DH TS_WAITK' % c[2], c[2] == struct.unpack_from('<H', tv, 0x50 - 0x49 + 2 * tv[0x62 - 0x49])[0]
          and c[3] == 0x0350 and c[4] == TS_WAITK << 8, (c[:5], tv.hex()))
    p = rows(n, 'r4.txt', 1, 1)
    check('MT_TROWS of one row (row 1, the prompt\'s, not blank): its 160 bytes only, the room past them as it was',
          p[0] == 0 and p[5][:160] == sl[160:320] and sl[160:320] != b' \7' * 80 and p[5][160:] == bytes(3840), p[:5])
    bads = [rows(n, 'rb%d.txt' % i, *a_) for i, a_ in enumerate(((20, 6), (0, 0), (25, 1)))]
    check('MT_TROWS of rows past 24, or none: CF, AX = 1', all(r[:2] == (1, 1) for r in bads), [r[:5] for r in bads])
    fr = rows(n, 'rf.txt')
    sh.run('mtterm f %d rg.txt' % n)
    g = A.disk_file(k, 'RG.TXT') or bytes(9)
    check('MT_TROWS with its room in the EMS frame\'s window 0, where the pages go: CF, AX = 1', g[:3] == b'\1\1\0', g[:9])
    sh.run('mtterm w %d rw.txt' % n)
    g = A.disk_file(k, 'RW.TXT') or bytes(9)
    txs = k.pc.u16(mt_seg(k), task_ent(k, n) + TE_TX)
    k.pc.wr(txs, TX_VID + 1, b'\x84')                     # (132 columns: its BIOS data, 40:4Ah, as a program left it)
    wide = rows(n, 'rx.txt')
    k.pc.wr(txs, TX_VID + 1, b'\x50')
    check('MT_TROWS with its room at F100h (4000 bytes round its segment\'s end): CF, AX = 1; a task of 132 columns: '
          'nothing copied (DL 2), the room untouched', g[:3] == b'\1\1\0' and wide[0] == 0 and wide[4] & 0xFF == 2
          and wide[3] & 0xFF == 0x84 and wide[5] == bytes(4000), (g[:9], wide[:5]))
    front(k, n); front(k, 0)
    d = rows(n, 'r5.txt')
    check('... brought to the front and back (nothing written meanwhile): its count up (%d, %d before: mt_scrsv)'
          % (d[1], fr[1]), tstate(k)[1] == 0 and d[1] > fr[1], (d[:5], fr[:5], tstate(k)))
    got = [keys(n, 'k%d.txt' % (6 + j), *([0x1E61 + j * 0x1201] * 20)) for j in (0, 1)]    # (20 "a", then 20 "b")
    k.run_for(1.0)
    got.append(keys(n, 'k3.txt', 0x1C0D))
    w = waitfile(k, 'TL.TXT', 3.0)
    k.run_for(0.5)
    check('... 20 "a", 20 "b" (the ring round its end: 2 before), then Return (1C0Dh) typed to it: its line "hi" and '
          'them; it ends', got == [b'0014 0000', b'0014 0000', b'0001 0000'] and w is not None
          and A.disk_file(k, 'TL.TXT') == b'hi' + b'a' * 20 + b'b' * 20 and tnum('MTLINE.COM') == 7, (got, A.disk_file(k, 'TL.TXT'), tstate(k)))
    # a task reading no keys (MTSPIN, frozen behind: START /D): 32 taken, the 33rd refused; MT_TROWS says frozen
    typ(k, 'start /w /d mtspin.com 30000 sp.txt', 0.5)   # (till killed)
    n = tnum('MTSPIN.COM')
    txs, kn = k.pc.u16(mt_seg(k), task_ent(k, n) + TE_TX), equ('TX_KN')
    k.pc.wr(txs, kn, b'\0\x14')                        # (none waiting, the first's place 20: as after 20 taken)
    past = bytes(k.pc.rd(txs, kn + 2 + 64, 32))
    got = (keys(n, 'k4.txt', *([0x1E61] * 20)), keys(n, 'k5.txt', *([0x1E61] * 13)))   # (a command line: 127 at most)
    ring = bytes(k.pc.rd(txs, kn, 2 + 64 + 32))
    fz = rows(n, 'rz.txt')
    check('MT_TKEY to MTSPIN (task %s, frozen behind: START /D), reading none: 20, then 12 of 13 taken, the 33rd refused '
          '(AX = 8: %s), the ring filled round its end (its first at 20), nothing past it written; MT_TROWS\'s DH TS_FROZEN, '
          'as MT_LIST says (ready, TS_RUN in MT\'s table)' % (n, got),
          got == (b'0014 0000', b'000C 0008') and fz[0] == 0 and fz[4] >> 8 == TS_FROZEN
          and ring[:2] == b'\x20\x14' and ring[2:66] == b'\x61\x1E' * 32 and ring[66:] == past
          and [s_ for i, s_, nm in tstate(k)[0] if i == n] == [1], (got, fz[:5], tstate(k), ring.hex()))
    sh.run('kill %d' % n)
    # parked: both refused (AX = 5)
    typ(k, 'start /w mtscr.com p', 3.0)
    n = tnum('MTSCR.COM')
    sh.run('park %d' % n)
    st = [s for i, s, nm in tstate(k)[0] if i == n]
    pr, got = rows(n, 'rp.txt'), keys(n, 'kp.txt', 0x1E61)
    check('a parked task (MTSCR, task %s, %s): MT_TROWS and MT_TKEY refused, AX = 5' % (n, st), st == [5]
          and pr[:2] == (1, 5) and got == b'0000 0005', (st, pr[:5], got))

MTSQ = os.path.join(HERE, 'MTSRQ.COM')

def srq_progs(k):
    """MTSRQ's PSPs: its signature at PSP:107h, an INT 20h at PSP:0, its MCB its own."""
    mem = bytes(k.pc.rd(0, 0, 0xA0000))
    out, i = [], mem.find(b'MTSRQ*')
    while i >= 0:
        p = (i - 0x107) // 16                           # (and its block still its own: not ended)
        if (i - 0x107) % 16 == 0 and mem[i - 0x107:i - 0x105] == b'\xcd\x20' and k.pc.u16(p - 1, 1) == p: out.append(p)
        i = mem.find(b'MTSRQ*', i + 1)
    return out

def t_srq():
    print('== T5c: a program woken by SRQ (MT_WAKE)')
    k = boot('mt_srq.img', b'MULTITASK=1\r\n', 88, MTSQ, chip=A.sim7210.NEC7210(A.sim7210.bus()))
    Y, seg = k.Y, mt_seg(k)
    au = Audit(k)
    sh = Shell(k)
    sh.run('ver')
    wkt = lambda: k.pc.rd(seg, Y['mt_wkt'], 1)[0]
    wkp = lambda: k.pc.u16(seg, Y['mt_wkp'])
    cur = lambda: k.pc.rd(seg, Y['mt_cur'], 1)[0]
    tnum = TermView(k).tnum
    def tnum_(psp):                                     # (the task whose region holds a PSP)
        for n in range(8):
            reg = k.pc.u16(seg, task_ent(k, n) + TE_REG)
            if n and k.pc.rd(seg, task_ent(k, n), 1)[0] and reg <= psp < reg + k.pc.u16(reg - 1, 3): return n
        return 0
    ways = {seg * 16 + Y['mt_srqi']: 'srqi', seg * 16 + Y['mt_srqi.r']: 'out', seg * 16 + Y['mt_tick.v']: 'v',
            seg * 16 + Y['mt_pick.wk']: 'pick', seg * 16 + Y['mt_exit']: 'exit', seg * 16 + Y['mw_poll.y']: 'y'}
    picks = []
    def lat(psp, when, max_s=0.4, at=None):
        """IRQ 5 raised once when() holds (at the block `at`, if given: from the watch) -> (ms until MTSRQ at
        psp sees it, or None; the way MT went meanwhile: mt_srqi, out of it, mt_tick.v, INT 21h's way out,
        mt_pick taking mt_want; T5d: the Executive giving way at its idle, mw_poll.y)."""
        if psp is None: return 'no MTSRQ', []
        t1 = k.pc.us + 2e6                              # (short runs: run_for's are 20000 blocks at least)
        hit, prev, base, t0, ev = [], k.pc.watch, psp * 16 + 0x10D, [], []
        def w(a):
            if prev: prev(a)
            if t0 and not hit and a in ways and len(ev) < 8: ev.append(ways[a])
            if at is not None and not t0 and a == at and when():     # (pcemu's irq_exact armed by hand: taken
                t0.append(k.pc.us); k.pc.irq_pending.add(5); k.pc.irq_wait = True   #  as IF is set again)
            if a == base and t0 and not hit: hit.append(k.pc.us)
        k.pc.watch = w
        while not t0:
            if k.pc.us > t1: k.pc.watch = prev; return 'never ready', []
            if at is None and when(): t0.append(k.pc.us); k.pc.irq_pending.add(5)
            else: k.pc.run(300)
        while not hit and k.pc.us - t0[0] < max_s * 1e6: k.pc.run(300)
        k.pc.watch = prev
        if 'pick' in ev: picks.append(ev)
        return (round((hit[0] - t0[0]) / 1000, 2) if hit else None), ev
    fast = lambda r: isinstance(r[0], float) and r[0] <= 3.0 and 'pick' in r[1]     # (woken: mt_pick took it)
    still = lambda r: r[0] is None and r[1][:2] == ['srqi', 'out']                   # (nothing woken)
    own = lambda n: lambda: cur() == n and k.pc.r('cs') not in (seg, 0x60) and k.pc.r('flags') & 0x200
    def one():
        ps = srq_progs(k)
        return ps[0] if len(ps) == 1 else None
    irq = k.pc.rd(0x60, Y['gp_irq'], 1)[0]
    gb = bytes(k.pc.rd(0x60, Y['gp_isr.e'], 5))
    check('the driver\'s SRQ interrupt on (IRQ 5, unmasked), its EOI a JMP FAR to mt_srqi',
          irq == 5 and not k.pc.pic_mask & 0x20 and (gb[0], gb[1] | gb[2] << 8, gb[3] | gb[4] << 8) == (0xEA, Y['mt_srqi'], seg),
          (irq, hex(k.pc.pic_mask), gb.hex()))
    # a program behind asking, a task computing: its turn at once
    typ(k, 'mtlaunch mtsrq.com 4', 1.0); line(k, '')        # (task 1, MTSPIN 2: MTSPIN's next in turn is the
    typ(k, 'mtlaunch mtspin.com 9000 s1.txt', 1.0); line(k, '')     #  Executive, not MTSRQ)
    q = one()
    nq, nspin = (tnum_(q) if q else None), tnum('MTSPIN.COM')
    wres = k.pc.u16(q, 0x105) if q else None
    check('MTSRQ behind asks MT_WAKE: AL = 5 (the driver\'s IRQ); MT holds its task and PSP',
          q and wres == 5 and wkt() == nq == 1 and nspin == 2 and wkp() == q, (q, wres, wkt(), nq, nspin))
    typ(k, 'mtsrq 0 g', 0.8)
    check('... another program giving it up (MTSRQ G, BL = 0, in task 0): nothing changes (its own only)',
          q and wkt() == nq and wkp() == q, (wkt(), hex(wkp())))
    r = lat(q, own(nspin))
    check('IRQ 5 while MTSPIN computes: MTSRQ runs at once (%s ms; 3 at most): mt_srqi, mt_tick.v, mt_pick taking '
          'it (%s), not after MTSPIN\'s turn and the Executive\'s' % r, fast(r) and r[1][:2] == ['srqi', 'v'],
          (r, nspin, tstate(k)))
    fr = task_ent(k, nq or 1) + TE_VF                   # (SPF_FREEZE, as MT_FLAGS sets it)
    k.pc.wr(seg, fr, bytes([k.pc.rd(seg, fr, 1)[0] | 4]))
    r = lat(q, own(nspin), 0.1)
    k.pc.wr(seg, fr, bytes([k.pc.rd(seg, fr, 1)[0] & ~4]))
    check('... frozen behind (SPF_FREEZE): IRQ 5 wakes nothing (mt_srqi straight out: %s), not seen meanwhile' % r[1],
          still(r), r)
    k.run_for(0.3)                                      # (thawed: it sees that one at its turn)
    r = lat(q, lambda: cur() == nspin, at=seg * 16 + Y['mt_load.go'])     # (raised under CLI: taken at its STI)
    check('... IRQ 5 in MT\'s own code as a switch to MTSPIN ends (mt_load\'s STI / RET: not a point to switch from): '
          'MTSRQ runs at the next tick (%s ms; %s), the wake kept, not lost' % r,
          isinstance(r[0], float) and 3 < r[0] <= 70 and 'pick' in r[1], r)
    r = lat(q, lambda: cur() == nq)
    check('... while MTSRQ itself runs (in its HLT): seen at once (%s ms)' % r[0], isinstance(r[0], float) and r[0] <= 3.0, r)
    k.run_for(0.3)
    check('... its fourth SRQ: it ends; its wake with it (mt_wkt FFh)', srq_progs(k) == [] and wkt() == 0xFF,
          (srq_progs(k), wkt()))
    # in INT 21h when it comes: at its way out
    typ(k, 'mtlaunch mtspin.com 9000 s2.txt d', 1.0); line(k, '')
    typ(k, 'mtlaunch mtsrq.com 1', 1.0); line(k, '')
    q = one()
    nd = next((i for i, s_, n in tstate(k)[0] if n == 'MTSPIN.COM' and i != nspin), None)
    r = lat(q, lambda: cur() == nd and k.pc.r('cs') == 0x60 and k.pc.r('flags') & 0x200
            and k.pc.rd(0x60, Y['indos'], 1)[0] == 1)
    check('IRQ 5 while MTSPIN D (an INT 21h on each count) is inside INT 21h: MTSRQ at its way out (%s ms; %s)' % r,
          fast(r) and r[1][:4] == ['srqi', 'v', 'exit', 'pick'], (r, nd, tstate(k)))
    o = sh.run('mtlaunch /k:%d' % nd) if nd else ''
    line(k, ''); k.run_for(0.5)
    check('... (MTSRQ ended, MTSPIN D killed)', srq_progs(k) == [] and wkt() == 0xFF and nd
          and nd not in [i for i, s_, n in tstate(k)[0]], (o, srq_progs(k), wkt(), tstate(k)))
    # X33: the task computing hooks INT 08h itself; the SRQ (IRQ 5, still the driver's) wakes at once
    typ(k, 'mtlaunch mtsrq.com 1', 1.0); line(k, '')
    q = one()
    typ(k, 'mtlaunch mtspin.com 50 s4.txt t', 0.2)
    nt = lambda: next((i for i, s_, n in tstate(k)[0] if n == 'MTSPIN.COM' and i != nspin), None)
    r = lat(q, lambda: nt() is not None and own(nt())() and vec(k, 8) != (seg, Y['mt_tick']))
    waitfile(k, 'S4.TXT', 8.0); line(k, ''); k.run_for(0.5)
    check('IRQ 5 while MTSPIN T computes, its own INT 08h hook ahead of mt_tick: MTSRQ runs at once all the same (%s '
          'ms; %s), IRQ 5\'s vector the driver\'s; MTSPIN T counts on, then ends' % r, fast(r) and r[1][:2] == ['srqi', 'v']
          and spun(k, 'S4.TXT') > 0 and srq_progs(k) == [] and wkt() == 0xFF, (r, spun(k, 'S4.TXT'), srq_progs(k), tstate(k)))
    # two programs asking: the last; the first's end leaves the second's
    typ(k, 'mtlaunch mtsrq.com 1', 1.0); line(k, '')
    qx = one()
    typ(k, 'mtlaunch mtsrq.com 2', 1.0); line(k, '')
    qy = next((x for x in srq_progs(k) if x != qx), None)
    ny = tnum_(qy) if qy else None
    check('two programs asking (two MTSRQs): the last one holds it', qx and qy and wkt() == ny and wkp() == qy,
          (qx, qy, ny, wkt(), hex(wkp())))
    r = lat(qy, own(nspin))
    k.run_for(0.5)
    check('... IRQ 5: the second woken at once (%s ms; %s); the first sees it at its turn and ends, the second\'s wake '
          'kept' % r, fast(r) and srq_progs(k) == [qy] and wkt() == ny and wkp() == qy, (r, srq_progs(k), wkt()))
    r = lat(qy, own(nspin))
    k.run_for(0.5)
    check('... again: woken at once (%s ms), it ends, its wake with it' % r[0], fast(r) and srq_progs(k) == []
          and wkt() == 0xFF, (r, srq_progs(k), wkt()))
    # the control: not asked
    typ(k, 'mtlaunch mtsrq.com 3 o', 1.0); line(k, '')
    q = one()
    lo = [lat(q, own(nspin)) for _ in range(3)]
    check('without MT_WAKE (MTSRQ O): it sees the SRQ only at its turn (%s ms; more than 5), mt_srqi straight out'
          % [x[0] for x in lo], q and wkt() == 0xFF and all(isinstance(x[0], float) and x[0] > 5
          and x[1][:2] == ['srqi', 'out'] for x in lo), (q, wkt(), lo))
    k.run_for(0.5)
    # asked and given up
    typ(k, 'mtlaunch mtsrq.com 2 f', 1.0); line(k, '')
    k.run_for(0.3)
    q = one()
    check('... MTSRQ F (asked, then BL = 0): given up (mt_wkt FFh), AL = 5', q and wkt() == 0xFF
          and k.pc.u16(q, 0x105) == 5, (srq_progs(k), wkt(), q and hex(k.pc.u16(q, 0x105))))
    for _ in range(2): k.pc.irq_pending.add(5); k.run_for(0.5)
    check('... (it ends after its two SRQs)', srq_progs(k) == [], srq_progs(k))
    # waiting for a key: not ready, nothing woken; killed: its wake ends with its task
    typ(k, 'mtlaunch mtsrq.com 1 k', 1.0); line(k, '')
    q = one()
    nq = tnum_(q) if q else None
    st = dict((i, s_) for i, s_, n in tstate(k)[0])
    r = lat(q, own(nspin), 0.2)
    check('MTSRQ K, waiting for a key (TS_WAITK): IRQ 5 wakes nothing (mt_srqi straight out; not seen, mt_want FFh)',
          q and st.get(nq) == 2 and wkt() == nq and still(r) and k.pc.rd(seg, Y['mt_want'], 1)[0] == 0xFF,
          (q, st, wkt(), nq, r))
    o = sh.run('mtlaunch /k:%d' % nq) if nq else ''
    line(k, ''); k.run_for(0.5)
    check('... MT_KILL ends its task: its wake too (mt_wkt FFh)', nq and srq_progs(k) == [] and wkt() == 0xFF,
          (o, srq_progs(k), wkt(), tstate(k)))
    typ(k, 'mtlaunch mtsrq.com 1 t', 1.0); line(k, '')
    k.run_for(0.5)
    check('... MTSRQ T, resident (31h) once asked: its task\'s end ends the wake (mt_wkt FFh)',
          wkt() == 0xFF and 'MTSRQ.COM' not in [n for i, s_, n in tstate(k)[0]], (wkt(), tstate(k)))
    # task 0: MTSRQ in front, full screen, MTSPIN behind
    typ(k, 'mtsrq 3', 0.8)
    q = one()
    l0 = [lat(q, own(nspin)) for _ in range(2)]
    check('task 0 asking (MTSRQ in front): woken from MTSPIN\'s turn at once (%s ms)' % [x[0] for x in l0],
          q and tnum_(q) == 0 and wkt() == 0 and all(fast(x) for x in l0), (q, wkt(), l0))
    k.pc.irq_pending.add(5); k.run_for(0.5)
    check('... it ends at its third: the wake ends with it (task 0\'s too)', srq_progs(k) == [] and wkt() == 0xFF,
          (srq_progs(k), wkt()))
    # the Executive in front (a terminal window's case, T5d): idle, and busy drawing.  Another MTSPIN first: a task
    # ready ahead of MTSRQ in the round (so the woken one is taken because it was woken, not as the next in turn)
    typ(k, 'mtlaunch mtspin.com 600 s3.txt', 1.0); line(k, '')
    typ(k, 'mtlaunch mtsrq.com 2', 1.0); line(k, '')
    typ(k, 'exit', 1.5)
    nsp3 = next((i for i, s_, n in tstate(k)[0] if n == 'MTSPIN.COM' and i != nspin), None)
    q = one()
    nq3 = tnum_(q) if q else None
    ui = k.pc.u16(0x60, Y['ui_seg'])
    ys, y0, s0 = [], seg * 16 + Y['mw_poll.y'], seg * 16 + Y['mt_switch']
    prev = k.pc.watch
    def wy(a):                                          # (mw_poll.y, then a switch before the next tick)
        if prev: prev(a)
        if a == y0: ys.append([k.pc.u16(seg, Y['mt_ticks']), 0])
        if a == s0 and ys and ys[-1][0] == k.pc.u16(seg, Y['mt_ticks']) and cur() == 0: ys[-1][1] = 1
    k.pc.watch = wy
    k.pc.run_for(0.5)
    k.pc.watch = prev
    check('the Executive in front and idle (MTSPIN and MTSRQ behind): it gives the rest of its turn away at its idle '
          '(mw_poll.y %d times, a switch from task 0 before the next tick %d times: not its HLT till then)'
          % (len(ys), sum(y[1] for y in ys)), q and k.pc.mode() == 0x40 and len(ys) >= 3 and sum(y[1] for y in ys) >= 3,
          (q, hex(k.pc.mode()), ys))
    kl = []
    for kk in (ktest.DOWN, ktest.UP, ktest.DOWN, ktest.UP):     # (keys meanwhile: back at the next tick, mt_mwant)
        k.pc.run_for(0.07)
        t0 = k.pc.us; k.pc.keys.append(kk)
        while k.pc.keys and k.pc.us - t0 < 0.5e6: k.pc.run(300)
        kl.append(round((k.pc.us - t0) / 1000, 1))
        k.pc.run_for(0.3)
    check('... a key for it meanwhile: taken at the next tick (%s ms; each typed just before one: 30 at most; it comes '
          'back for it, as for the mouse, mt_mwant; without that, at its turn in the round: 81 in the run recorded)' % kl,
          max(kl) <= 30, kl)
    seen = collections.Counter()
    for i in range(30):                                 # (keys all the while: the boost at every tick)
        k.pc.keys.append(ktest.DOWN if i % 2 == 0 else ktest.UP)
        for _ in range(25):
            e_ = k.pc.us + 1200
            while k.pc.us < e_ and k.pc.run(300): pass
            seen[cur()] += 1
    k.run_for(0.3)
    check('... a key every 30 ms or so for a second: the tasks behind still take turns, each MTSPIN (%d and %d samples '
          'of %d; the turn the boost took from one given back where it was, mt_mrot, the yield\'s look leaving it)'
          % (seen[nsp3], seen[nspin], sum(seen.values())), nsp3 is not None and seen[nsp3] > 20 and seen[nspin] > 20,
          dict(seen))
    idle = (Y['..@ui_idle'], Y['..@ui_midle'], Y['..@ui_sidle'])
    r = lat(q, lambda: cur() == 0, at=seg * 16 + Y['mw_poll'])     # (its poll: the little it runs, idle)
    check('... IRQ 5 while it runs, idle (in its poll): woken at once (%s ms; %s)' % r, fast(r), r)
    k.key(ktest.DOWN, ktest.UP, settle=False)
    r = lat(q, lambda: cur() == 0 and k.pc.r('cs') == ui and k.pc.r('ip') not in idle and k.pc.r('flags') & 0x200, 1.0)
    print('   the Executive busy drawing (its selection moved): the SRQ\'s task at its next idle, %s ms' % r[0])
    k.run_for(0.5)
    check('... the Executive busy drawing: the wake kept till its idle, where it gives way to it (mw_poll.y; not the '
          'tick, nor the other MTSPIN, task %s, ahead of it, task %s, in the round: %s ms; 40 at most; %s), and then MTSRQ '
          'ends, its wake with it' % ((nsp3, nq3) + r), isinstance(r[0], float) and r[0] <= 40
          and nsp3 is not None and nq3 and nsp3 < nq3 and 'pick' in r[1] and 'y' in r[1] and srq_progs(k) == []
          and wkt() == 0xFF, (r, nsp3, srq_progs(k), wkt()))
    check('... every switch at a safe point (the audit; %d at the tick\'s end, %d of them by SRQ, mt_pick taking '
          'mt_want)' % (len(au.switches(0, 'tick')), len(picks)), not au.bad() and len(picks) == 10, (au.bad()[:3], len(picks)))
    au.stop()
    # a program staying resident in task 0 keeps its wake (task 0 never ends)
    sh = Shell(k)
    sh.run('ver')
    typ(k, 'mtsrq 1 t', 1.0)
    ps = [x for x in srq_progs(k) if tnum_(x) == 0]
    check('MTSRQ T in task 0 (LCMD\'s prompt): resident, its wake kept (mt_wkt 0, mt_wkp its PSP): a limit',
          len(ps) == 1 and wkt() == 0 and wkp() == ps[0], (ps, wkt(), hex(wkp())))
    typ(k, 'mtsrq 0 g', 0.8)
    check('... another program in task 0 giving it up (MTSRQ G, BL = 0) and ending: kept (the task the same, the '
          'program not)', len(ps) == 1 and wkt() == 0 and wkp() == ps[0], (wkt(), hex(wkp())))
    # no SRQ interrupt (GPIBIRQ=0): AL 0
    k = boot('mt_srq0.img', b'MULTITASK=1\r\nGPIBIRQ=0\r\n', 88, chip=A.sim7210.NEC7210(A.sim7210.bus()))
    tnum = TermView(k).tnum             # (this machine's)
    got, out = probe(k)
    check('GPIBIRQ=0: MT_WAKE answers AL 0 (no wake comes), CF clear', got.get(0x23, (1,))[:2] == (0, 0)
          and got.get(0x123, (1,))[:2] == (0, 0), out[-300:])


def t_progs():
    print('== MULTITASK=1: DOS programs as before')
    k0 = boot('mt_mem0.img', b'MULTITASK=0\r\n')
    k1 = boot('mt_mem1.img', b'MULTITASK=1\r\n')
    a0, a1 = mcbs(k0), mcbs(k1)
    paras = (k1.Y['mt_bend'] + 15) // 16
    check('free memory with it on: exactly MT\'s %d paragraphs and its MCB less (%d bytes)' % (paras, (paras + 1) * 16),
          a0[-1][2] == 0 and a1[-2][2] == 0 and a1[-2][3] == a0[-1][3] - (paras + 1) and a0[:-1] == a1[:-2], (show(a0), show(a1)))
    m0 = re.search(r'([\d.]+) KB for programs', k0.run_file('MEMSZ.COM', 30))
    m1 = re.search(r'([\d.]+) KB for programs', run_wait(k1, 'MEMSZ.COM', 30))
    print('   MEMSZ: %s KB off, %s KB on' % (m0 and m0.group(1), m1 and m1.group(1)))
    check('MEMSZ (from the Executive), off: 581.6 KB, as with no switch (test_splash.py MEM_044)', m0 and m0.group(1) == '581.6', m0 and m0.group(1))
    k = boot('mt_progs.img', b'MULTITASK=1\r\n', 88, os.path.join(HERE, 'TESTDOS.COM'), os.path.join(HERE, 'EMSTEST.COM'),
             os.path.join(HERE, 'CACHETST.COM'))
    out = run_wait(k, 'TESTDOS.COM', 120)
    check('TESTDOS: no failures', 'FAIL' not in out and ' 0 failed' in out, out[-300:])
    out = run_wait(k, 'EMSTEST.COM', 300)
    check('EMSTEST: no failures', 'FAIL' not in out and ' 0 failed' in out, out[-300:])
    out = run_wait(k, 'CACHETST.COM', 900)
    check('CACHETST: every byte reads back as written', ' 0 errors' in out, out[-300:])
    seg = mt_seg(k)
    t0 = k.pc.u16(seg, k.Y['mt_ticks']) if seg else 0
    k.run_for(1.0)
    t1 = k.pc.u16(seg, k.Y['mt_ticks']) if seg else 0
    check('after them: back in the Executive, MT still at the top, ticking (%d in 1 s), F0h still through it' % (t1 - t0),
          k.pc.mode() == 0x40 and not k.crashed and at_top(k) and vec(k, 8) == (seg, k.Y['mt_tick'])
          and 17 <= t1 - t0 <= 20 and f0_bytes(k)[0] == 0xEA, k.where())

def t_rom():
    print('== from the ROM (the 1520\'s own start-up): C:\\LODE.INI turns it on')
    import test_rom as R
    k = R.boot(ata=R.sysinfo_hd(('LODE.INI', b'MULTITASK=1\r\n')), ems_pages=88)
    check('started from the ROM with C:\\LODE.INI MULTITASK=1: MT at the top, INT 08h through it',
          at_top(k) and vec(k, 8)[0] == mt_seg(k), show(mcbs(k)))
    R.to_prompt(k)
    o = R.prompt(k, 'tasks')
    check('... TASKS lists the Executive', re.search(r'0\s+Executive \(in front\)', o), o)
    r1, memsz, kb = R.rom(), open(A.MEMSZ, 'rb').read(), {}
    r96 = r1.replace(b'MTMEM=LCMD.COM:64', b'MTMEM=LCMD.COM:96')       # (the ROM's line, another size: seen)
    for tag, roms, more in (('ROM 1 alone (no TERM.FNT)', None, b''),
                            ('with ROM 2 (TERM.FNT on it)', {0: R.rom2(), 1: r1}, b''),
                            ('with ROM 2, the ROM\'s line made MTMEM=LCMD.COM:96', {0: R.rom2(), 1: r96}, b''),
                            ('... and C:\\LODE.INI MTMEM=FOO.COM:200', {0: R.rom2(), 1: r96}, b'MTMEM=FOO.COM:200\r\n')):
        k = R.boot(roms=roms, ata=R.sysinfo_hd(('LODE.INI', b'MULTITASK=1\r\n' + more), ('MEMSZ.COM', memsz)), ems_pages=88)
        k.mcb0 = k.u16('first_mcb')     # (the whole arena's start: first_mcb is per task)
        k.key(ktest.CODE_P, settle=False); k.run_for(4.0)
        st, n = tstate(k), k.pc.rd(mt_seg(k), k.Y['mw_n'], 1)[0]
        if roms is None:
            check('... %s: CODE-P: LCMD a task in front, full screen (as without windows)' % tag,
                  st[1] != 0 and k.pc.mode() == 3 and n == 0, (st, k.pc.mode(), n))
            continue
        o = '\n'.join(l for y, l in k.ocr())
        check('... %s: CODE-P: LCMD in a terminal window (TERM.RUN from ROM 1, TERM.FNT from ROM 2, by PATH), task 0 '
              'in front' % tag, st[1] == 0 and k.pc.mode() == 0x40 and n == 1 and 'LCMD.COM' in o and 'C:\\>' in o,
              (st, k.pc.mode(), n, o[-300:]))
        k.key('memsz', settle=False); k.key(ktest.ENTER, settle=False); k.run_for(3.0)
        m = re.search(r'([\d.]+) KB for programs', '\n'.join(l for y, l in k.ocr()))
        kb[(roms[1] is r96, more)] = m and float(m.group(1))
    k64, k96, kfoo = kb.get((False, b'')), kb.get((True, b'')), kb.get((True, b'MTMEM=FOO.COM:200\r\n'))
    check('... MEMSZ at that prompt: %s KB with the ROM as built (MTMEM=LCMD.COM:64: the task\'s 64 KB less LCMD); %s KB '
          'with the ROM\'s line made :96 (32 KB more: it is read); %s KB with that and C:\\LODE.INI\'s MTMEM=FOO.COM:200 '
          '(64 again: C:\'s line replaces the ROM\'s whole)' % (k64, k96, kfoo), r96 != r1 and k64 and k96 and kfoo
          and k64 < 64 and 28 <= k96 - k64 <= 36 and abs(kfoo - k64) < 1, kb)
    k = R.boot(ata=R.sysinfo_hd(), ems_pages=88)
    check('started from the ROM, no C:\\LODE.INI (the ROM\'s settings): off', mt_seg(k) is None and vec(k, 8) == INT08, show(mcbs(k)))

def sections(path):
    """LODE.MAP: {section: [(real, virtual, name)]}"""
    out, sec = {}, None
    for line in open(path):
        if line.startswith('---- Section'): sec = line.split()[2]
        m = re.match(r'\s*([0-9A-F]+)\s+([0-9A-F]+)\s+(\S+)\s*$', line)
        if m and sec: out.setdefault(sec, []).append((int(m.group(1), 16), int(m.group(2), 16), m.group(3)))
    return out

def t_image():
    print('== LODE.SYS and LODEMT.SYS')
    secs, Y = sections(MAP), ktest.Syms()
    sysb, mtb = open(SYS, 'rb').read(), open(MTSYS, 'rb').read()
    start = [r for r, v, n in secs['mtt'] if n == 'mt_tstart'][0]
    sumat = [r for r, v, n in secs['boot'] if n == 'mt_sum'][0]
    check('LODEMT.SYS is the resident part, %d bytes (mt_tend - mt_tstart), cut off the end of LODE.SYS (%d bytes)'
          % (len(mtb), len(sysb)), len(mtb) == Y['mt_tend'] - Y['mt_tstart'] and len(sysb) == start, (len(mtb), len(sysb), start))
    got = sysb[sumat] | sysb[sumat + 1] << 8
    check('LODE.SYS\'s mt_sum is LODEMT.SYS\'s checksum (%04Xh)' % mkmt.checksum(mtb), got == mkmt.checksum(mtb) != 0, hex(got))
    kw = sysb[Y['kbd_get.k']:Y['kbd_get.k'] + 6]
    check('kbd_get.k in LODE.SYS is MOV AH,1 / INT 16h / JNZ .have (B4 01 CD 16 75 xx: what mt_boot patches)',
          kw[:5] == bytes([0xB4, 1, 0xCD, 0x16, 0x75]) and Y['kbd_get.k'] + 6 + kw[5] == Y['kbd_get.have'], kw.hex())
    check('task 0\'s TX in MT\'s BSS: on the paragraph after the image', Y['mt_tx0'] == (len(mtb) + 15) // 16 * 16, hex(Y['mt_tx0']))
    ex = sysb[Y['done.sw']:Y['done.sw'] + 5]
    check('done.sw in LODE.SYS is MOV SS,AX / MOV SP,BX / POPA (8E D0 89 DC 61: what mt_boot patches), the bytes after it '
          'POP DS / POP ES / IRET, and ctrlc\'s copy of them is somewhere else (untouched)',
          ex == EXIT5 and sysb[Y['done.sw'] + 5:Y['done.sw'] + 8] == bytes([0x1F, 0x07, 0xCF])
          and sysb[Y['ctrlc.sw']:Y['ctrlc.sw'] + 5] == EXIT5 and Y['ctrlc.sw'] != Y['done.sw'], ex.hex())
    fs = [sysb[Y[f]:Y[f] + 7] for f in ('f_25', 'f_35')]
    check('f_25 and f_35 in LODE.SYS start XOR BX,BX / MOV ES,BX / MOV BL,[BP+F_AX] (31 DB 8E C3 8A 5E 0E: what mt_boot '
          'patches, mt_25 and mt_35 redo)', fs[0] == fs[1] == bytes([0x31, 0xDB, 0x8E, 0xC3, 0x8A, 0x5E, 0x0E]), [f.hex() for f in fs])
    gi = sysb[Y['gp_isr.e']:Y['gp_isr.e'] + 8]
    check('gp_isr.e in LODE.SYS is MOV AL,20h / OUT 20h,AL / POP DS, then POP DX / POP AX / IRET (B0 20 E6 20 1F 5A 58 CF: '
          'what mt_boot patches, mt_srqi redoes)', gi == bytes([0xB0, 0x20, 0xE6, 0x20, 0x1F, 0x5A, 0x58, 0xCF]), gi.hex())
    boot_end = min(r for r, v, n in secs['mdt'])      # (section boot ends where mdt starts)
    check('the start-ups (section boot) end at %04Xh, below 1000:F000, where LODE.INI is read (INI_BUF); LODE.SYS %d bytes, '
          'under the ROM loader\'s 64 KB' % (boot_end, len(sysb)), boot_end < 0xF000 and len(sysb) < 0x10000, (hex(boot_end), len(sysb)))

def merged(arena):
    """The arena with free neighbours as one block, as KMEM's mem_alloc
    merges them (lazily, on its next scan): what the next program gets."""
    out = []
    for seg, t, own, sz, nm in arena:
        if out and own == 0 and out[-1][2] == 0:
            s0, t0, o0, z0, n0 = out[-1]
            out[-1] = (s0, t, 0, z0 + sz + 1, n0)
        else:
            out.append((seg, t, own, sz, nm if own else b''))
    return out

def sft_used(k):
    """The SFT's reference counts (S_REF, the first byte of each of 24 x 44):
    a handle left open shows as a count one higher."""
    base = k.Y['sft']
    return [k.pc.rd(0x60, base + i * 44, 1)[0] for i in range(24)]

def t_file():
    print('== LODEMT.SYS: none, or not this LODE.SYS\'s: it stays off')
    mtb = open(MTSYS, 'rb').read()
    k0 = boot('mt_f0.img', b'MULTITASK=0\r\n')
    a0, used0 = mcbs(k0), sft_used(k0)
    flip = bytearray(mtb); flip[len(flip) // 2] ^= 0x40
    for tag, body in (('none', None), ('one byte changed (another build)', bytes(flip)), ('a byte short', mtb[:-1]),
                      ('empty', b'')):
        if body is None:
            k = boot('mt_f1.img', b'MULTITASK=1\r\n', mt=None)
        else:
            p = os.path.join(A.OUT, 'LODEMT.SYS'); open(p, 'wb').write(body)
            k = boot('mt_f1.img', b'MULTITASK=1\r\n', mt=p)
        check('MULTITASK=1, LODEMT.SYS %s: off; memory as with MULTITASK=0 (MT\'s block freed; free neighbours counted as one, as the next allocation merges them), no file left open, '
              'INT 08h, f_F0 and kbd_get.k untouched' % tag,
              mt_seg(k) is None and merged(mcbs(k)) == merged(a0) and sft_used(k) == used0 and vec(k, 8) == INT08
              and f0_bytes(k)[0] == 0x8A and kw_bytes(k)[0] == 0xB4 and k.pc.mode() == 0x40, (show(mcbs(k)), show(a0), sft_used(k), used0))
    k = boot('mt_f1.img', b'MULTITASK=1\r\n', mt=MTSYS)
    check('... and the file as built: on (no file left open either)', at_top(k) and sft_used(k) == used0, (show(mcbs(k)), sft_used(k)))

def t_k2cap():
    print('== K2: Shift-PrtSc at the prompt of an error inside EXEC, with MULTITASK=1 (a task behind keeps running)')
    big = os.path.join(A.OUT, 'BIG.COM')
    open(big, 'wb').write(bytes([0xB4, 0x09, 0xBA, 0x08, 0x01, 0xCD, 0x21, 0xC3]) + b'HELLO$' + b'Q' * 4082)
    k = boot('mt_k2.img', b'MULTITASK=1\r\n', 88, big, os.path.join(A.GOS, 'drivers', 'SCREEN.PRN'))
    d = k.pc.drives[0]
    img = bytes(d.img); sec = []
    for i in range(224):                                # BIG.COM's sectors (1.44 MB FAT12)
        e = img[19 * 512 + i * 32:19 * 512 + i * 32 + 32]
        if e[:11] == b'BIG     COM':
            cl = e[26] | e[27] << 8
            while 2 <= cl < 0xFF8:
                sec.append(33 + cl - 2)
                v = img[512 + cl * 3 // 2] | img[512 + cl * 3 // 2 + 1] << 8
                cl = v >> 4 if cl & 1 else v & 0xFFF
    ret(k, 'MTSPIN.COM', 0.5)                           # a task behind (no DOS calls: preempted at the tick)
    front(k, 0)
    ret(k, 'LCMD.COM', 1.0)
    d.bad = {sec[1]}
    k.key('big', settle=False); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: 'Fail?' in k.pc.text_screen() or k.pc.crash, 10)
    o1 = k.pc.text_screen()
    k.pc.prtsc(); k.run_for(1.0)
    d.bad = set()
    k.pc.keys.append(ord('r')); k.run_for(3.0)
    o = k.pc.text_screen()
    shots = [n for n in A.fatcheck.read_files(d.img) if 'SCREEN0' in n]
    check('an error inside EXEC (BIG.COM\'s image) from LCMD as a task, Shift-PrtSc at its prompt, then Retry: BIG.COM '
          'loads and runs whole (its buffers in the INT 21h stack\'s low area), the screen saved once, nothing crashed',
          'Fail?' in o1 and 'HELLO' in o and len(shots) == 1 and not k.crashed, (o1[-200:], o[-300:], shots))

class DWait:
    """M10's points in MT, counted as they are passed (a hook at each label), and the kernel's stack at each
    9001h from inside INT 21h (its depth: kstack_top less SP, SS the kernel's)."""
    LABELS = ('mt_dwait', 'mt_dcan.y', 'mt_dcan.no', 'mt_dready', 'mt_dtick', 'mt_i0e', 'mt_gate', 'mt_gate.no',
              'mt_gate.h', 'mt_dwait.u')
    def __init__(s, k):
        s.k, seg = k, mt_seg(k)
        s.at = {seg * 16 + k.Y[n]: n for n in s.LABELS}
        s.n = collections.Counter(); s.depth = []
        s.top = k.Y['kstack_top']
        k.hooks.append(s.hook)
    def hook(s, pc):
        n = s.at.get(s.k.addr)
        if n is None: return
        s.n[n] += 1
        if n == 'mt_dwait' and pc.r('ss') == 0x60:
            s.depth.append(s.top - pc.r('sp'))
    def m10(s, on):
        """M10 on, or off: INT 15h straight to the BIOS (MT's gates then never hold anything)."""
        k = s.k; seg = mt_seg(k)
        k.pc.wr(0, 0x15 * 4, struct.pack('<HH', k.Y['mt_i15'], seg) if on else k.pc.rd(seg, k.Y['mt_old15'], 4))

def dw_pad(n=300000):
    pad = os.path.join(A.OUT, 'PADM.BIN')
    open(pad, 'wb').write(bytes((i * 7 + i // 512) & 0xFF for i in range(n)))
    return pad

def dw_run(k, spin, cmd, done, sim=60):
    """MTSPIN started behind (MTLAUNCH, then its prompt line: the task runs on), then CMD at the prompt
    (task 0's LCMD): (seconds till DONE is on the screen, MTSPIN's count when it is through)."""
    typ(k, 'cls', 0.3)
    typ(k, 'mtlaunch mtspin.com ' + spin, 1.0); typ(k, '', 0.2)     # (MTLAUNCH's line: no settling, MTSPIN runs)
    t0 = k.pc.us
    typ(k, cmd, 0.1)
    k.pc.run_until(lambda: done in k.pc.text_screen() or k.pc.crash, sim)
    tc = (k.pc.us - t0) / 1e6
    f = spin.split()[1].upper()
    k.pc.run_until(lambda: bool(A.disk_file(k, f)) or k.pc.crash, sim)
    k.run_for(0.5)
    return tc, spun(k, f)

def t_dfrz():
    print('== M10: a task frozen behind while it waits on the floppy still runs when the floppy is done (no hang)')
    # A MTSPIN counts behind; then MTSPIN K (its own INT 13h read on each count, 1520 drive timing) in front, /Z:
    # frozen whenever behind.  CODE-Tab while K is out on the floppy: the other comes to the front, and K
    # is frozen behind.  Before the fix mt_pick skipped it (frozen) once its read was done, and the other's
    # first INT 21h waited at the gate for it for ever: the machine hung
    k = boot('mt_dfz.img', b'MULTITASK=1\r\n', 88, fd_wait=True, disk_model='real')
    Shell(k).run('ver')
    dw = DWait(k)
    seg, Y = mt_seg(k), k.Y
    st = lambda n: k.pc.rd(seg, Y['mt_tab'] + n * MT_ENT, 1)[0]
    typ(k, 'mtlaunch mtspin.com 120 c2.txt', 1.0); typ(k, '', 0.5)     # (counting, before K's reads start)
    typ(k, 'mtlaunch /f /z mtspin.com 60 k.txt k', 0.2)
    k.pc.run_until(lambda: tstate(k)[1] == 2 and st(2) == 6 or k.pc.crash, 10)
    out1 = st(2)
    k.key(HOT, settle=False)
    k.pc.run_until(lambda: tstate(k)[1] != 2 or k.pc.crash, 5)
    f2, s1 = tstate(k)[1], st(2)
    k.pc.run_until(lambda: bool(A.disk_file(k, 'C2.TXT')) or k.pc.crash, 30)
    c2 = A.disk_file(k, 'C2.TXT')
    check('MTSPIN K out on the floppy (state %d) in front; CODE-Tab: task %d in front, K behind (state %d, frozen '
          'there); the other counts on and writes its count (C2.TXT %r): nothing hung'
          % (out1, f2, s1, c2), out1 == 6 and f2 != 2 and c2 and int(c2, 16) > 0 and not k.crashed,
          (out1, f2, s1, c2, tstate(k), dict(dw.n)))
    front(k, 2)
    k.pc.run_until(lambda: bool(A.disk_file(k, 'K.TXT')) or k.pc.crash, 30)
    typ(k, '', 1.0)
    kc = A.disk_file(k, 'K.TXT')
    check('K back in front: it goes on reading, ends and writes its count (K.TXT %r); all ended, no INT 13h while '
          'one waited' % kc, kc and int(kc, 16) > 0 and tstate(k)[0] == [(0, 1, 'Executive')]
          and k.pc.fd_reentry == 0 and not k.crashed, (kc, tstate(k), k.pc.fd_reentry))

def t_hdtools():
    print('== HDSCAN and HDPROBE (they drive the hard disk themselves): not beside other tasks')
    tools = os.path.join(os.path.dirname(GOS), 'tools')
    k = boot('mt_hdt.img', b'MULTITASK=1\r\n', 88, os.path.join(tools, 'HDSCAN.COM'), os.path.join(tools, 'HDPROBE.COM'))
    sh = Shell(k)
    sh.run('ver')
    typ(k, 'mtlaunch mtline.com x.txt', 1.0); typ(k, '', 0.5)
    o1, o2 = sh.run('hdscan'), sh.run('hdprobe')
    check('a task there (MTLINE, waiting behind): HDSCAN and HDPROBE each say so and stop, nothing else done',
          all('other tasks are running' in o and 'End them first' in o and 'GRiDCase' not in o for o in (o1, o2))
          and len(tstate(k)[0]) == 2, (o1, o2, tstate(k)))
    front(k, 1); line(k, 'x')
    typ(k, 'cls', 0.3); typ(k, 'hdscan', 0.1)
    k.pc.run_until(lambda: 'Press any key' in k.pc.text_screen() or k.pc.crash, 120)
    o3 = k.pc.text_screen()
    k.key(ktest.ENTER); k.run_for(0.5)
    check('the task ended (the Executive alone): HDSCAN runs (its title, then its look for the drive: none here)',
          tstate(k)[0] == [(0, 1, 'Executive')] and 'HDSCAN 1.1' in o3 and 'other tasks' not in o3 and not k.crashed,
          (tstate(k), o3[-400:]))

def t_sysreq():
    print('== M11: SysReq to the next task, as CODE-Tab; Confm (CODE-SysReq) left alone; -dNOSYSREQ has none of it')
    k = boot('mt_sr.img', b'MULTITASK=1\r\n', 88)
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    srq = lambda code=False: (k.pc.sysreq(code), k.run_for(0.4))
    flag = lambda: k.pc.rd(seg, Y['mt_sysrq'], 1)[0]
    k.pc.srq_seen.clear()
    srq()
    check('SysReq with the Executive the only task: nothing to switch to, task 0 in front; MT passed 8500h and 8501h '
          'on to the BIOS (%s), its flag taken (mt_sysrq 0)' % [hex(a) for a in k.pc.srq_seen],
          tstate(k)[1] == 0 and k.pc.srq_seen == [0x8500, 0x8501] and flag() == 0, (tstate(k), k.pc.srq_seen, flag()))
    sh.run('mtlaunch mtline.com a.txt;mtline.com b.txt')
    scr0 = k.pc.text_screen()
    ring0 = k.pc.kbd_ring()
    srq()
    check('SysReq while MTLAUNCH waits: task 1 to the front, its own prompt; nothing put in the key buffer or taken from '
          'it', tstate(k)[1] == 1 and k.pc.text_screen().strip() == 'MTLINE>' and k.pc.kbd_ring() == ring0 == [],
          (tstate(k), k.pc.kbd_ring(), k.pc.text_screen()[-200:]))
    k.key('hel'); k.run_for(0.3)
    srq()
    check('typed to task 1 ("hel"), then SysReq: task 2', tstate(k)[1] == 2 and k.pc.text_screen().strip() == 'MTLINE>'
          and flag() == 0, (tstate(k), k.pc.text_screen()[-200:]))
    srq()
    check('SysReq again: round to task 0, MTLAUNCH\'s screen as it was', tstate(k)[1] == 0
          and k.pc.text_screen() == scr0, (tstate(k), k.pc.text_screen()[-300:]))
    k.pc.srq_seen.clear()
    srq(code=True)
    check('Confm (CODE-SysReq: CODE, the BIOS\'s Alt, held in 40:17h): no switch, task 0 still in front, no SysReq '
          'left waiting (mt_sysrq 0); 8500h and 8501h passed on to the BIOS for the program',
          tstate(k)[1] == 0 and flag() == 0 and k.pc.srq_seen == [0x8500, 0x8501] and k.pc.text_screen() == scr0,
          (tstate(k), flag(), k.pc.srq_seen))
    hot(k)
    srq()
    check('CODE-Tab, then SysReq: CODE-Tab to task 1, SysReq on to task 2', tstate(k)[1] == 2, tstate(k))
    srq()
    srq()
    check('SysReq twice more: task 0, then task 1 ("hel" kept on its screen)', tstate(k)[1] == 1
          and 'hel' in k.pc.text_screen(), (tstate(k), k.pc.text_screen()[-200:]))
    line(k, 'lo')
    srq()
    line(k, 'world')
    line(k, '')
    check('task 1 ends ("hello"); SysReq to task 2 (task 0 in front after task 1\'s end), which gets "world"; all ended',
          A.disk_file(k, 'A.TXT') == b'hello' and A.disk_file(k, 'B.TXT') == b'world'
          and tstate(k) == ([(0, 1, 'Executive')], 0, 0), (A.disk_file(k, 'A.TXT'), A.disk_file(k, 'B.TXT'), tstate(k)))
    # a task in front that reads no keys: the switch at a tick, where it is safe
    typ(k, 'mtlaunch /f mtspin.com 40 s.txt', 0.6)
    st1 = tstate(k)
    srq()
    st2 = tstate(k)
    k.run_for(3.0); line(k, '')
    c = A.disk_file(k, 'S.TXT')
    check('MTSPIN in front, counting, reading no keys: SysReq brings task 0 to the front at a tick; MTSPIN counts on '
          'behind and ends (S.TXT %r)' % c, st1[1] == 1 and st2[1] == 0 and c and int(c, 16) > 0
          and tstate(k)[0] == [(0, 1, 'Executive')], (st1, st2, c, tstate(k)))
    check('nothing went wrong', not k.crashed, k.crashed)
    # -dNOSYSREQ: the build for a machine without the key
    src = os.path.join(GOS, 'src')
    sysf, mapf, mtf = (os.path.join(A.OUT, n) for n in ('LODENS.SYS', 'LODENS.MAP', 'LODEMTNS.SYS'))
    m = os.path.join(A.OUT, '_ns.asm')
    open(m, 'w').write('[map symbols %s]\n%%include "LODE.ASM"\n' % mapf)
    subprocess.run(['nasm', '-f', 'bin', '-dNOSYSREQ', '-i', src + '/', '-o', sysf, m], check=True)
    subprocess.run(['python3', os.path.join(GOS, 'mkmt.py'), sysf, mapf, mtf], check=True, stdout=subprocess.DEVNULL)
    n0, n1 = os.path.getsize(MTSYS), os.path.getsize(mtf)
    check('-dNOSYSREQ: no mt_sysrq in its map; LODEMT.SYS %d bytes, %d fewer than with SysReq (LODE.SYS %d, the same '
          'size)' % (n1, n0 - n1, os.path.getsize(sysf)), 'mt_sysrq' not in open(mapf).read() and 0 < n0 - n1 <= 64
          and os.path.getsize(sysf) == os.path.getsize(os.path.join(src, 'LODE.SYS')), (n0, n1))
    import mkimg
    img = mkimg.build(os.path.join(A.OUT, 'mt_ns.img'), ['LODE.SYS=' + sysf, 'LODEMT.SYS=' + mtf, A.LCMD, MTL, MTLN,
                                                         ini(b'MULTITASK=1\r\n')])
    k = ktest.KPC(img, ems_pages=88); k.start(10); k.mcb0 = k.u16('first_mcb')
    sh = Shell(k)
    sh.run('ver')
    sh.run('mtlaunch mtline.com n.txt')
    k.pc.srq_seen.clear()
    srq = lambda: (k.pc.sysreq(), k.run_for(0.4))
    srq()
    st1 = tstate(k)
    hot(k)
    st2 = tstate(k)
    line(k, 'n'); line(k, '')
    check('-dNOSYSREQ: SysReq switches nothing (task 0 still in front), passed on to the BIOS (%s); CODE-Tab still '
          'does (task 1, N.TXT "n")' % [hex(a) for a in k.pc.srq_seen], st1[1] == 0 and st2[1] == 1
          and k.pc.srq_seen == [0x8500, 0x8501] and A.disk_file(k, 'N.TXT') == b'n' and not k.crashed,
          (st1, st2, k.pc.srq_seen, A.disk_file(k, 'N.TXT')))

def t_dwait():
    """M10: tasks run while one waits on the floppy (pcemu's fd_wait: INT 15h 9001h, IRQ 6, 9101h, the DMA at
    its end through the EMS windows as they are then).  The copy at the prompt, MTSPIN behind."""
    print('== M10: tasks run while one waits on the floppy')
    pad = dw_pad(); want = open(pad, 'rb').read()
    scr = os.path.join(A.GOS, 'drivers', 'SCREEN.PRN')
    def fresh(name, disk='flat', b=None):
        k = boot(name, b'MULTITASK=1\r\n', 88, 'PAD.BIN=' + pad, scr, fd_wait=True, disk_model=disk)
        Shell(k).run('ver')
        return k, DWait(k)
    # 1. the 1520's drive timing: the copy alone, M10 off and on (nobody else to run: the same); then with
    #    MTSPIN behind, off and on
    alone = []
    for on in (False, True):
        k, dw = fresh('mt_dw0.img', 'real')
        dw.m10(on)
        typ(k, 'cls', 0.3); t0 = k.pc.us; typ(k, 'copy pad.bin p.bin', 0.1)
        k.pc.run_until(lambda: 'copied' in k.pc.text_screen() or k.pc.crash, 60)
        alone.append(((k.pc.us - t0) / 1e6, dw.n['mt_dcan.y'], A.disk_file(k, 'P.BIN') == want))
    (a0, s0, o0), (a1, s1, o1) = alone
    check('the copy alone (the 1520\'s drive timing): %.2f s with M10 off, %.2f s on (%d of its waits could have been '
          'given away, nobody to take them: no switch), both exact' % (a0, a1, s1),
          o0 and o1 and s0 == 0 and s1 > 0 and abs(a1 - a0) < 0.01 * a0, alone)
    k, dw = fresh('mt_dw1.img', 'real')
    dw.m10(False)
    t_off, c_off = dw_run(k, '200 c0.txt', 'copy pad.bin p0.bin', 'copied')
    ok0 = A.disk_file(k, 'P0.BIN') == want
    sw0 = dw.n['mt_dcan.y']
    dw.m10(True)
    t_on, c_on = dw_run(k, '200 c1.txt', 'copy pad.bin p1.bin', 'copied')
    ok1 = A.disk_file(k, 'P1.BIN') == want
    pc = k.pc
    check('a 300 KB copy at the prompt, MTSPIN counting behind (the 1520\'s drive timing: seeks, rotation): with M10 '
          'off %.2f s, MTSPIN %d; on %.2f s, MTSPIN %d (%d switches at 9001h, back in %d 9101h, %d IRQ 6s through '
          'MT\'s hook): the waits given to MTSPIN, the copy within 10%% (a switch back is ~1.5 ms); both copies '
          'exact; no INT 13h while one waited, no transfer whose EMS window '
          'changed under it, no time-out' % (t_off, c_off, t_on, c_on, dw.n['mt_dcan.y'], dw.n['mt_dready'],
                                                dw.n['mt_i0e']),
          ok0 and ok1 and sw0 == 0 and dw.n['mt_dcan.y'] >= 20 and c_on > 5 * c_off and t_on < 1.10 * t_off
          and pc.fd_reentry == 0 and pc.fd_frame_bad == 0 and pc.fd_timeouts == 0 and not k.crashed,
          (ok0, ok1, sw0, dict(dw.n), c_off, c_on, t_off, t_on, pc.fd_reentry, pc.fd_frame_bad, pc.fd_timeouts))
    d = dw.depth
    check('the kernel\'s stack at each 9001h from inside INT 21h (the copy\'s reads and writes, MTLAUNCH\'s EXEC of '
          'MTSPIN): %d of them, %d bytes at most, under the TX\'s slice less mt_switch\'s room (%d)'
          % (len(d), max(d or [0]), equ('KSLICE') - 48), d and max(d) < equ('KSLICE') - 48, (len(d), max(d or [0])))
    # 2. behind: INT 21h on each count (D), its own INT 13h on each count (K)
    for mode, what in (('d', 'an INT 21h call (AH=2Ch) on each count: each one while the copy\'s read is out waits '
                              'for it'),
                       ('k', 'its own INT 13h read of A:\'s first sector on each count: each one while the copy\'s '
                              'read is out waits for it, none failed')):
        k, dw = fresh('mt_dw2%s.img' % mode)
        tc, c = dw_run(k, '120 c.txt ' + mode, 'copy pad.bin p.bin', 'copied')
        ok = A.disk_file(k, 'P.BIN') == want
        check('MTSPIN %s behind, %s (%d times held, %d switches at 9001h): the copy exact (%.2f s), MTSPIN counted %d; '
              'no INT 13h while one waited' % (mode.upper(), what, dw.n['mt_gate'], dw.n['mt_dcan.y'], tc, c),
              ok and c > 0 and dw.n['mt_gate'] > 0 and dw.n['mt_gate.no'] == 0 and k.pc.fd_reentry == 0
              and k.pc.fd_frame_bad == 0 and not k.crashed,
              (ok, c, dict(dw.n), k.pc.fd_reentry, k.pc.fd_frame_bad))
    # 3. behind: an EMS page of its own in window 2, the cache's
    k, dw = fresh('mt_dw3.img')
    tc, c = dw_run(k, '120 c.txt m', 'copy pad.bin p.bin', 'copied')
    ok = A.disk_file(k, 'P.BIN') == want
    check('MTSPIN M behind, its own EMS page mapped in window 2 (the cache\'s) and checked on each count: it doesn\'t '
          'run while a cache fill holds the window (%d switches at 9001h), so its page and the copy are exact (%.2f s; '
          'MTSPIN counted %d, its pattern intact); no transfer whose window changed under it'
          % (dw.n['mt_dcan.y'], tc, c), ok and c > 0 and dw.n['mt_dcan.y'] > 0 and k.pc.fd_frame_bad == 0
          and not k.crashed, (ok, c, dict(dw.n), k.pc.fd_frame_bad))
    # 4. behind: its INT 1Ch hook calls INT 21h (InDOS 0: its own task's) at interrupt time
    k, dw = fresh('mt_dw4.img')
    tc, c = dw_run(k, '120 c.txt h', 'copy pad.bin p.bin', 'copied')
    ok = A.disk_file(k, 'P.BIN') == want
    check('MTSPIN H behind, its INT 1Ch hook calling INT 21h (AH=2Ch) at interrupt time: refused while the copy\'s read '
          'is out (%d times: a call that can\'t wait there), the copy exact (%.2f s), MTSPIN counted %d, nothing '
          'crashed' % (dw.n['mt_gate.no'], tc, c), ok and c > 0 and dw.n['mt_gate.no'] > 0 and not k.crashed,
          (ok, c, dict(dw.n)))
    # 5. Shift-PrtSc in the middle of the copy
    k, dw = fresh('mt_dw5.img')
    typ(k, 'mtlaunch mtspin.com 120 c.txt', 1.0); typ(k, '', 0.2)
    typ(k, 'copy pad.bin p.bin', 0.1)
    k.pc.run_until(lambda: dw.n['mt_dcan.y'] >= 10, 20)
    sw = dw.n['mt_dcan.y']
    k.pc.prtsc()
    k.pc.run_until(lambda: 'copied' in k.pc.text_screen() or k.pc.crash, 60); k.run_for(2.0)
    shots = [n for n in A.fatcheck.read_files(k.pc.drives[0].img) if 'SCREEN0' in n]
    check('Shift-PrtSc in the middle of the copy (after %d switches at 9001h): the screen saved once, when the kernel '
          'could take it, and the copy exact' % sw, sw >= 10 and len(shots) == 1
          and A.disk_file(k, 'P.BIN') == want and not k.crashed, (sw, shots))
    # 6. MT_KILL of a task copying, in the middle of its copy
    k, dw = fresh('mt_dw6.img')
    typ(k, 'mtlaunch lcmd.com /c copy pad.bin p.bin', 0.5); typ(k, '', 0.2)
    k.pc.run_until(lambda: dw.n['mt_dcan.y'] >= 10, 20)
    sw = dw.n['mt_dcan.y']
    typ(k, 'mtlaunch /K:1', 3.0); line(k, ''); k.run_for(2.0)
    probs, files = A.fatcheck.check(bytes(k.pc.drives[0].img))
    got = A.disk_file(k, 'P.BIN')
    check('MT_KILL of a task copying, after %d switches at 9001h: the kill waits for the kernel to be free (its call '
          'held, %d times), then the task ends; the disk consistent, and P.BIN whole or not there (%s bytes)'
          % (sw, dw.n['mt_gate'], None if got is None else len(got)), sw >= 10 and dw.n['mt_gate'] > 0
          and not probs and (got is None or got == want or len(got) % 512 == 0) and not k.crashed,
          (sw, dict(dw.n), probs, None if got is None else len(got)))
    # 8. a bad sector in the file: the kernel's tries (each a wait given away), then its INT 24h prompt
    k, dw = fresh('mt_dw8.img')
    d = k.pc.drives[0]; img = bytes(d.img)
    e = next(img[19 * 512 + i * 32:19 * 512 + i * 32 + 32] for i in range(224)
             if img[19 * 512 + i * 32:19 * 512 + i * 32 + 11] == b'PAD     BIN')
    cl = e[26] | e[27] << 8
    for _ in range(40):                                 # (its 41st cluster: well into the copy)
        v = img[512 + cl * 3 // 2] | img[512 + cl * 3 // 2 + 1] << 8
        cl = v >> 4 if cl & 1 else v & 0xFFF
    d.bad = {33 + cl - 2}
    typ(k, 'cls', 0.3)
    typ(k, 'mtlaunch mtspin.com 200 c.txt', 1.0); typ(k, '', 0.2)
    typ(k, 'copy pad.bin p.bin', 0.1)
    k.pc.run_until(lambda: 'Fail?' in k.pc.text_screen() or k.pc.crash, 60)
    o1, sw = k.pc.text_screen(), dw.n['mt_dcan.y']
    k.pc.keys.append(ord('f'))
    k.pc.run_until(lambda: bool(A.disk_file(k, 'C.TXT')) or k.pc.crash, 60); k.run_for(1.0)
    probs, _ = A.fatcheck.check(bytes(d.img))
    check('a bad sector 40 clusters into PAD.BIN, MTSPIN behind: the kernel\'s tries, each wait given away (%d '
          'switches at 9001h), then its INT 24h prompt; F: the copy fails, back at the prompt, MTSPIN counted %d, '
          'the disk consistent, nothing hung' % (sw, spun(k, 'C.TXT')),
          'Fail?' in o1 and sw > 0 and spun(k, 'C.TXT') > 0 and not probs and not k.crashed and k.pc.fd_reentry == 0,
          (sw, spun(k, 'C.TXT'), probs, o1[-200:]))
    # 7. B: with no disk: the floppy's interrupt never comes (MT's time-out, then the BIOS's)
    k = ktest.KPC(A.image('mt_dw7.img', 'LODEMT.SYS=' + MTSYS, A.LCMD, MTL, MTSP, ini(b'MULTITASK=1\r\n')),
                  bytes(1474560), ems_pages=88, fd_wait=True)
    k.pc.drives[1].empty = True
    k.start(10); k.mcb0 = k.u16('first_mcb')
    dw = DWait(k)
    Shell(k).run('ver')
    typ(k, 'mtlaunch mtspin.com 300 c.txt', 1.0); typ(k, '', 0.2)
    typ(k, 'dir b:', 0.1)
    k.pc.run_until(lambda: 'Fail?' in k.pc.text_screen() or k.pc.crash, 60)
    sw, to = dw.n['mt_dcan.y'], dw.n['mt_dtick']
    k.pc.keys.append(ord('f')); k.run_for(2.0)
    k.pc.run_until(lambda: bool(A.disk_file(k, 'C.TXT')) or k.pc.crash, 60)
    check('B: with no disk, MTSPIN behind: each try switched away at 9001h (%d), back by MT\'s time-out (%d INT 13h '
          'time-outs), then the kernel\'s INT 24h prompt; F: back at the prompt, MTSPIN counted %d, nothing hung'
          % (sw, k.pc.fd_timeouts, spun(k, 'C.TXT')), sw >= 1 and k.pc.fd_timeouts >= 1 and spun(k, 'C.TXT') > 0
          and not k.crashed, (sw, to, k.pc.fd_timeouts, spun(k, 'C.TXT'), k.pc.text_screen()[-200:]))

def t_nodisk():
    print('== a task behind with no INT 24h of its own, B: with no disk: Fail at once, not a prompt nobody sees')
    nd = os.path.join(HERE, 'NODISKMT.COM')
    files = ['LODEMT.SYS=' + MTSYS, A.LCMD, MTL, nd, ini(b'MULTITASK=1\r\n')]
    k = ktest.KPC(A.image('mt_nd.img', *files), bytes(1474560), ems_pages=88)
    k.pc.drives[1].empty = True
    k.start(10)
    k.mcb0 = k.u16('first_mcb')
    ret(k, 'NODISKMT.COM', 0.3)                # (it waits 2 s, then opens B:X.TXT)
    front(k, 0)
    k.run_for(3.0)
    crit = k.pc.rd(mt_seg(k), k.Y['mt_crit'], 1)[0]
    sel0 = k.u16('sel')
    k.pc.keys.append(ktest.DOWN); k.run_for(1.0)
    check('NODISKMT behind the Executive opens B:X.TXT with no disk: 3 at once (RES.TXT "03"), no prompt waiting '
          '(mt_crit 0), and the Executive still takes keys', A.disk_file(k, 'RES.TXT') == b'03' and crit == 0
          and k.u16('sel') != sel0, (A.disk_file(k, 'RES.TXT'), crit, sel0, k.u16('sel')))
    # with a handler of its own that prompts (LCMD's, which NODISKMT run from LCMD as a task inherits): the same
    k = ktest.KPC(A.image('mt_nd2.img', *files), bytes(1474560), ems_pages=88)
    k.pc.drives[1].empty = True
    k.start(10)
    k.mcb0 = k.u16('first_mcb')
    ret(k, 'LCMD.COM', 1.0)
    k.key('nodiskmt'); k.key(ktest.ENTER, settle=False); k.run_for(0.3)
    front(k, 0)
    k.run_for(3.0)
    crit = k.pc.rd(mt_seg(k), k.Y['mt_crit'], 1)[0]
    sel0 = k.u16('sel')
    k.pc.keys.append(ktest.DOWN); k.run_for(1.0)
    check('... run from LCMD as a task (LCMD\'s INT 24h, which prompts), the Executive in front: the same, 3 at once, '
          'nothing waiting for an answer nobody can read', A.disk_file(k, 'RES.TXT') == b'03' and crit == 0
          and k.u16('sel') != sel0, (A.disk_file(k, 'RES.TXT'), crit, sel0, k.u16('sel')))
    # in a terminal window (CODE-P's LCMD, T2): the same, and the window still takes keys
    big = os.path.join(A.OUT, 'BIG.COM')
    open(big, 'wb').write(bytes([0xB4, 0x09, 0xBA, 0x08, 0x01, 0xCD, 0x21, 0xC3]) + b'HELLO$' + b'Q' * 4082)
    k = ktest.KPC(A.image('mt_nd3.img', *(files + [TERMRUN, TERMFNT, big])), bytes(1474560), ems_pages=88)
    k.pc.drives[1].empty = True
    k.start(10)
    k.mcb0 = k.u16('first_mcb')
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    k.key('nodiskmt', settle=False); k.key(ktest.ENTER, settle=False); k.run_for(4.0)
    crit = k.pc.rd(mt_seg(k), k.Y['mt_crit'], 1)[0]
    k.key('ver', settle=False); k.key(ktest.ENTER, settle=False); k.run_for(1.5)
    o, n = '\n'.join(l for y, l in k.ocr()), k.pc.rd(mt_seg(k), k.Y['mw_n'], 1)[0]
    check('... run from LCMD in a terminal window: the same, 3 at once, nothing waiting; the window still takes keys '
          '(VER answered there)', A.disk_file(k, 'RES.TXT') == b'03' and crit == 0 and n == 1 and 'Lodestone version' in o,
          (A.disk_file(k, 'RES.TXT'), crit, n, o[-300:]))
    # a program there that can't be read: EXEC fails at once (no prompt) and LCMD says why, since nothing else did
    k.key('cls', settle=False); k.key(ktest.ENTER, settle=False); k.run_for(1.0)
    k.pc.drives[0].bad = {file_lbas(os.path.join(A.OUT, 'mt_nd3.img'), b'BIG     COM')[1]}
    k.key('big', settle=False); k.key(ktest.ENTER, settle=False); k.run_for(4.0)
    crit = k.pc.rd(mt_seg(k), k.Y['mt_crit'], 1)[0]
    k.pc.drives[0].bad = set()
    o = '\n'.join(l for y, l in k.ocr())
    check('... a program there with a bad sector: EXEC fails, no prompt waiting; LCMD says "Data error" (none was '
          'asked), not "Bad command or file name"', crit == 0 and 'Data error' in o and 'Bad command' not in o
          and 'HELLO' not in o, (crit, o[-300:]))

if __name__ == '__main__':
    t0 = time.time()
    A.build()
    for n in ('MTPROBE', 'MTLAUNCH', 'MTLINE', 'MTCWD', 'MTMODE', 'FREEH', 'MTSPIN', 'MTHOOK', 'MTSCR', 'VNEST', 'MTCRIT',
              'MTNEST', 'VHOOK', 'MTKEY', 'MTM33', 'MTVEC', 'MTKILL', 'NODISKMT', 'MTTERM', 'MTGROW', 'MTPUB', 'MTSRQ', 'MTIRQK', 'MTFAST', 'MTCLI'):
        subprocess.run(['nasm', '-f', 'bin', '-i', os.path.join(GOS, 'src') + '/', '-i', HERE + '/',     # (MTLIB.INC)
                        '-o', os.path.join(HERE, n + ('.BIN' if n == 'VNEST' else '.COM')),
                        os.path.join(HERE, n + '.ASM')], check=True)
    A.mkrun.build(os.path.join(HERE, 'QUITRUN.ASM'), QUITRUN)
    only = [a for a in sys.argv[1:] if a.startswith('t_')]
    for t in (t_image, t_off, t_on, t_file, t_tasks, t_ends, t_front, t_preempt, t_rules, t_fpu, t_fpbad, t_screens, t_kslice, t_vruns, t_keys, t_irqk, t_pitfast, t_pitcli, t_mouse, t_vectors, t_kill, t_park, t_grow, t_lcmd, t_exec, t_lists, t_tasksrun, t_windows, t_peek, t_tname, t_write, t_paintw, t_base, t_menu, t_clip, t_system, t_rclaude, t_rpoll, t_tcore, t_term, t_wait_bg, t_tgfx, t_tclip, t_wwait, t_wxor, t_wroot, t_tpub, t_srq, t_progs, t_nodisk, t_k2cap, t_dwait, t_dfrz, t_sysreq, t_hdtools, t_rom):
        if not only or t.__name__ in only: t()
    bad_ = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad_), (': ' + '; '.join(bad_)) if bad_ else '', time.time() - t0))
    sys.exit(1 if bad_ else 0)
