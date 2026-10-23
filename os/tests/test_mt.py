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
python3 tests/test_mt.py [t_image t_off t_on t_file t_tasks t_ends t_front t_preempt t_rules t_fpu t_screens t_keys t_mouse t_progs t_rom]"""
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
MT_ENT, TE_NAME, TE_SH = 32, 10, 22      # KMT.INC: an entry in mt_tab, its name, its screen's EMS handle
TE_TX, TE_VF, TX_VID = 6, 24, 10         # (its TX's segment, VF_DIRECT and the SPF_ overrides; a TX's BIOS video data)
VF_DIRECT, SPF_BG, SPF_FREEZE, TS_WAITF, TS_FROZEN = 1, 2, 4, 3, 4
INT10 = (STUB, 0x10 * 8)                # pcemu's BIOS INT 10h
INT16 = (STUB, 0x16 * 8)                # and INT 16h
TS_WAITK = 2
MTK = os.path.join(HERE, 'MTKEY.COM')
MTM = os.path.join(HERE, 'MTM33.COM')
MTV = os.path.join(HERE, 'MTVEC.COM')
MTKL = os.path.join(HERE, 'MTKILL.COM')

# With the switch off these must not move (main with UI API 6, PrtSc's printing and the audit's kernel
# and UI batches, then its medium-risk kernel and UI batches): the kernel's image and BSS, the UI block
# kept while a DOS program runs
OFF_MAP = {'image_end': 0x4090, 'bss_end': 0x75C0, 'ui_keep_end': 0x620A}  # (6144h before right clicks, UI API 7; 6164h before X22;
                                        #  6154h before M7b: the Executive's Return as a task, CODE-T, the UI block moved once no task is left;
                                        #  3F80h/74B0h before GPIB's SRQ on IRQ 5)

def ini(text):
    p = os.path.join(A.OUT, 'LODE.INI'); open(p, 'wb').write(text); return 'LODE.INI=' + p

def boot(name, text=None, ems=88, *more, mt=MTSYS, nofpu=False, mouse=False):
    """A floppy with LODE.SYS and (unless mt=None) LODEMT.SYS, LCMD, MEMSZ,
    MTPROBE, `more`, and LODE.INI holding `text`.  nofpu: INT 11h says no
    coprocessor, and the 286's EM bit is set, so any coprocessor instruction
    traps (INT 7, counted in pc.ints).  mouse: a serial mouse on COM1."""
    files = ([] if mt is None else ['LODEMT.SYS=' + mt]) + [A.LCMD, A.MEMSZ, MTPROBE, MTL, MTLN, MTCW, MTMD, FREEH, MTSP, MTHK] + list(more) \
        + ([ini(text)] if text is not None else [])
    k = ktest.KPC(A.image(name, *files), ems_pages=ems)
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
    """An EQU's value, from LODE.MAP's list of them (ktest's symbols are the labels)."""
    for l in open(os.path.join(GOS, 'src', 'LODE.MAP')):
        m = re.match(r'([0-9A-F]{8})\s+(\S+)\s*$', l)
        if m and m.group(2) == name: return int(m.group(1), 16)
    raise KeyError(name)

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
        check('%s: no MT block, INT 08h, 10h and 16h the BIOS\'s, f_F0, kbd_get.k and done.sw as assembled' % tag,
              mt_seg(k) is None and vec(k, 8) == INT08 and vec(k, 0x10) == INT10 and vec(k, 0x16) == INT16
              and f0_bytes(k) == sysb[k.Y['f_F0']:k.Y['f_F0'] + 5]
              and kw_bytes(k) == sysb[k.Y['kbd_get.k']:k.Y['kbd_get.k'] + 6] and dx_bytes(k) == EXIT5,
              (show(mcbs(k)), vec(k, 8), f0_bytes(k).hex()))
        if tag in ('no LODE.INI', 'MULTITASK=1 but no EMS'):
            got, out = probe(k)
            check('%s: F0h AL=00h answers (4F47h, 0201h); 11h-14h, 1Bh, 1Ch and FFh fail with AX = 1' % tag,
                  got.get(0) == (0, 0x4F47, 0x0201, 0x1234) and all(bad(got.get(a, (0, 0, 0, 0))) for a in (0x11, 0x12, 0x13, 0x14, 0x1B, 0x1C, 0xFF)),
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
    check('task 0 is the Executive: its PSP the root process\'s',
          k.pc.u16(seg, Y['mt_tab'] + 2) == k.u16('root_psp'), (hex(k.pc.u16(seg, Y['mt_tab'] + 2)), hex(k.u16('root_psp'))))
    t0, b0 = k.pc.u16(seg, Y['mt_ticks']), k.pc.u16(0x40, 0x6C)
    k.run_for(2.0)
    t1, b1 = k.pc.u16(seg, Y['mt_ticks']), k.pc.u16(0x40, 0x6C)
    check('2 s: mt_tick ran %d times, the BIOS counted %d ticks (18.2 a second)' % (t1 - t0, b1 - b0),
          t1 - t0 == b1 - b0 and 34 <= b1 - b0 <= 38, (t1 - t0, b1 - b0))
    got, out = probe(k)
    check('F0h through mt_f0: AL=00h still answers (4F47h, 0201h: its OR AL,AL redone); 11h (not from a stub), 14h, 1Bh, FFh fail '
          'with AX = 1; 13h with task 0 works, and 1Ch (MT_SCREEN; alone, nothing to do)', got.get(0) == (0, 0x4F47, 0x0201, 0x1234)
          and all(bad(got.get(a, (0, 0, 0, 0))) for a in (0x11, 0x14, 0x1B, 0xFF)) and got.get(0x13, (1,))[0] == 0
          and got.get(0x1C, (1,))[0] == 0, out[-400:])
    check('F0h AL=13h with BL = 8 (no such task) and BL = 7 (a free one): CF, AX = 1',
          bad(got.get(0x113, (0, 0))) and bad(got.get(0x213, (0, 0))), out[-400:])
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
        su.append((k.u16('wseg'), k.rd('ems_su', 2)))
        k.key(ktest.ESC)
        su.append((k.u16('wseg'), k.rd('ems_su', 2)))
    check('the other F0h calls go on to the kernel: the help window\'s save-under is lent (AL=2) and given back (AL=3), twice',
          all(su[i][0] != 0 and su[i][1] != b'\0\0' for i in (0, 2)) and all(su[i] == (0, b'\0\0') for i in (1, 3)),
          [(hex(w), bytes(e).hex()) for w, e in su])
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
    """Shift-Return on a program in the Executive (ktest's run_file, Shift held at 40:17h till it runs): in the
    Executive's own task, which waits for it, as with multitasking off (Return starts it as a task, M7b)."""
    k.select(name)
    k.pc.tty.clear() if isinstance(k.pc.tty, list) else None
    k.pc.wr(0x40, 0x17, b'\x02')
    k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() != 0x40, 5)
    k.pc.wr(0x40, 0x17, b'\x00')
    ktest.run_answering(k.pc, lambda: k.pc.mode() == 0x40, sim_s)
    k.settle()
    return ''.join(k.pc.tty) if isinstance(k.pc.tty, list) else k.pc.tty

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
        s.wf = seg * 16 + k.Y['mt_wfront']   # (a background task waiting at INT 10h to be in front)
        s.wk = seg * 16 + k.Y['mt_wkey']     # (a task waiting at INT 16h for a key)
        s.pss = None
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
        reg = pc.u16(s.seg, Y['mt_tab'] + cur * MT_ENT + 4)
        ui, psp, root = pc.u16(0x60, Y['ui_seg']), pc.u16(0x60, Y['cur_psp']), pc.u16(0x60, Y['root_psp'])
        r = dict(cs=cs < 0xA000 and cs not in (0x60, s.seg) and (cs != ui or ip in (Y['..@ui_idle'], Y['..@ui_sidle'])),
                 iff=bool(fl & 0x200), isr=pc.isr == 0, indos=pc.rd(0x60, Y['indos'], 1)[0] == 0,
                 busy=pc.rd(ui, Y['m33_busy'], 1)[0] == 0, ss=s.mine(ss, cur, reg, psp, root, ui),
                 own=cs == ui or s.mine(cs, cur, reg, psp, root, ui))
        return r, cur
    def watch(s, a):
        if s.prev: s.prev(a)
        k, pc = s.k, s.k.pc
        if s.track:
            ss, sp, cs = pc.r('ss'), pc.r('sp'), pc.r('cs')
            new, s.pss = ss != s.pss, ss
            if new or ss != s.track[0] or pc.rd(s.seg, k.Y['mt_cur'], 1)[0] != s.track[3]: pass
            elif sp >= s.track[1]: s.track = None       # (just loaded, between MOV SS and MOV SP; another task's,
            elif cs < 0xA000 and cs not in s.track[4]:  #  or MT's own stack; the frame gone: back in the caller,
                s.track = None                          #  or in its code)
            else: s.depth[s.track[2]] = max(s.depth[s.track[2]], s.track[1] - sp)
        if s.open:                                          # (back from that very mt_fdrain call: its RET's
            ss = pc.r('ss')                                 #  target, its SP above the return address)
            if ss in s.open and s.open[ss][1] == a and pc.r('sp') == s.open[ss][0] + 2: del s.open[ss]
        if a == s.fd:
            ss = pc.r('ss')
            again = ss in s.open                            # (a drain inside this task's: no second IRQ)
            if not again: s.open[ss] = (pc.r('sp'), s.seg * 16 + pc.u16(ss, pc.r('sp')))
            s.due = s.inject and not again and s.inject()
        elif a == s.fdw and s.due:                          # (interrupts on: raised and taken here, pcemu
            s.due = False                                   #  delivering IRQs as its run loop starts again)
            pc.irq_pending.add(13); s.injected += 1; pc.mu.emu_stop()
        elif a == s.ex:
            if s.force and pc.rd(s.seg, k.Y['mt_pend'], 1)[0] == 0: pc.wr(s.seg, k.Y['mt_pend'], b'\1')
        elif a == s.sa:
            r, cur = s.rules(pc.r('ax'), pc.r('bx'), pc.r('dx'), pc.r('ss'))
            no = [n for n, ok in r.items() if not ok]
            if len(no) == 1: s.only[no[0]] += 1
        elif a in (s.at, s.wf, s.wk):
            ss, sp = pc.r('ss'), pc.r('sp')
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
            if path == 'tick': r['ivt'] = vec(k, 8) == (s.seg, k.Y['mt_tick'])   # (else a hook ahead was interrupted)
            s.ev.append(dict(path=path, cs=cs, ip=ip, fl=fl, task=cur, ss=ss, r=r, sw=False,
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
    # (EXEC's own entry for the program it reads, which no handle holds, stays taken: the kernel's EXEC doesn't
    # give it back when it is aborted, with multitasking or without)
    d = [b - a for a, b in zip(used0, sft_used(k))]
    check('a read error while the stub EXECs its program, answered Abort: the prompt on the screen in front, shadowed in '
          'MTLAUNCH\'s pages too; the stub ends itself (its own parent) and its '
          'task with it; MTLAUNCH, then the prompt, go on; memory as before, the handles the stub inherited closed',
          'Abort' in scr and sync and not k.crashed and st and st[0] == [(0, 1, 'Executive')] and 'Lodestone version' in v
          and merged(mcbs(k)) == a0 and sorted(d) == [0] * 23 + [1] and used0[d.index(1)] == 0 and ems_used(k) == e0,
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
        reg = k.pc.u16(seg, Y['mt_tab'] + cur * MT_ENT + 4)
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
    # Y's turn is made due once its hook is in: a tick that lands in MT's own code (mt_i16, where Y's loop spends
    # most of its time) leaves the slice as it is, so with the emulator's tick in step with that loop Y's turn
    # may never end by itself (X21)
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
    n0 = len(au.ev)
    typ(k, 'mtlaunch /f mtkey.com r r2.txt;mtspin.com 20 s2.txt', 1.0)
    st = tstate(k)
    k.run_for(1.5)
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
    k = boot('mt_kh.img', b'MULTITASK=1\r\n', 88, MTK)
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
        tx = k.pc.u16(seg, Y['mt_tab'] + task * MT_ENT + 6)
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
        return k.pc.u16(ent(task, 6), o + 2), k.pc.u16(ent(task, 6), o)
    def txfv(task, i):                  # its INT 09h (0) or 1Bh (1), in its TX
        o = equ('TX_FVEC') + i * 4
        return k.pc.u16(ent(task, 6), o + 2), k.pc.u16(ent(task, 6), o)
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
    reg1 = ent(1, 4)
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
    reg = ent(1, 4)
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
    st, a3, rg = tstate(k), vec(k, 9), ent(1, 4)
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
    reg = ent(1, 4)
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
    reg = ent(1, 4)
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
    ext = lambda task: k.pc.u16(seg, Y['mt_tab'] + task * MT_ENT + 8)      # (TE_EXIT)
    alone = lambda: tstate(k)[0] == [(0, 1, 'Executive')]
    m0, s0, e0 = merged(mcbs(k)), sft_used(k), ems_used(k)
    back = lambda: alone() and merged(mcbs(k)) == m0 and sft_used(k) == s0 and ems_used(k) == e0 and not k.crashed
    now = lambda: (tstate(k), show(mcbs(k)), sft_used(k), s0, ems_used(k), e0)
    kr = {}
    def killed(n, cmd, settle=0.6):     # cmd started (MTLAUNCH's), run a while, then MTLAUNCH /K:n
        sh.run('mtlaunch ' + cmd); line(k, ''); k.run_for(settle)
        st, e1 = tstate(k), ems_used(k)
        reg = k.pc.u16(seg, Y['mt_tab'] + n * MT_ENT + 4)                  # (TE_REG: its region, its MCB before it)
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
    top, hot, prev = seg * 16 + Y['mt_i16.top'] + 3, [], k.pc.watch
    def w(a):                                   # (just back from .top's CALL mt_hot: the key put in the buffer)
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
    m0, s0, e0 = merged(mcbs(k)), sft_used(k), ems_used(k)
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
    marked = lambda: k.pc.rd(seg, Y['mt_tab'] + MT_ENT + 25, 1)[0]     # (task 1's TE_KILL)
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
    m0, s0, e0 = merged(mcbs(k)), sft_used(k), ems_used(k)
    alone = lambda: tstate(k)[0] == [(0, 1, 'Executive')]
    back = lambda: alone() and merged(mcbs(k)) == m0 and sft_used(k) == s0 and ems_used(k) == e0 and not k.crashed
    now = lambda: (tstate(k), show(mcbs(k)), sft_used(k), s0, ems_used(k), e0)
    def region(task):                   # its region: segment, paragraphs (its MCB's), and its bytes
        r = ent(task, 4)
        n = k.pc.u16(r - 1, 3)
        return r, n, bytes(k.pc.rd(r, 0, n * 16))
    def mt(cmd):                        # MTLAUNCH's options, from the prompt
        o = sh.run('mtlaunch ' + cmd); line(k, ''); k.run_for(0.3)
        return o
    def owners(task):                   # the owners in its own arena (its PSPs)
        s, out = k.pc.u16(ent(task, 6), equ('V_MCB')), set()
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
    sp1 = ent(1, 4), ent(1, 28)        # (the parked one's region: TE_REG, TE_PSZ)
    eb = ems_used(k)                    # (the parked one's own EMS page among them: the programs in its place
                                        #  below have their PSPs at its program's segment)
    mt('mtvec.com i 0 x')               # (task 2: INT 62h its own, then a line)
    k.run_for(0.3)
    r2, n2 = ent(2, 4), k.pc.u16(ent(2, 4) - 1, 3)
    lap = r2 - 1 < sp1[0] + sp1[1] and sp1[0] - 1 < r2 + n2
    v62 = vec(k, 0x62)
    o1, o2 = mt('/u:1'), mt('/p:2')
    check('a task in the parked one\'s place (MTVEC I, %04X: %d paragraphs; the parked one at %04X), INT 62h its own: '
          'it can\'t be parked (error 5), and the parked one doesn\'t come back (error 8); both as they were'
          % (r2, n2, sp1[0]), lap and r2 <= v62[0] < r2 + n2 and 'MTLAUNCH: error 8' in o1 and 'MTLAUNCH: error 5' in o2 and st(1) == 5
          and st(2) == TS_WAITK and vec(k, 0x62) == v62 and not k.crashed, (r2, n2, sp1, v62, o1, o2, now()))
    front(k, 2); line(k, ''); k.run_for(0.5)                        # (I ends, INT 62h put back)
    mt('mtkill.com f 10 kc.txt')        # (task 2 again, in the same place: its PSPs at the same segments)
    r2, n2 = ent(2, 4), k.pc.u16(ent(2, 4) - 1, 3)
    lap = r2 - 1 < sp1[0] + sp1[1] and sp1[0] - 1 < r2 + n2
    pc = owners(2)
    o1 = mt('/u:1')
    sa, sb, ra = st(1), st(2), ent(1, 4)
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
    r1 = ent(1, 4)
    pk, prev = [], k.pc.watch
    def w(a):
        if prev: prev(a)
        if a == seg * 16 + Y['mt_pinned'] and cur() == 2 and not pk:
            k.pc.wr(ent(2, 6), equ('TX_FVEC'), struct.pack('<HH', 0x100, r1 + 0x40))
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
    r1, r2, va = ent(1, 4), ent(2, 4), vec(k, 0x62)
    gv = struct.unpack('<HH', bytes(k.pc.rd(ent(2, 6), equ('TX_GSN') + 0x62 * 4, 4)))
    o1 = mt('/p:1')
    s1 = st(1)
    front(k, 2); line(k, ''); k.run_for(0.5)                        # (each ends, INT 62h put back)
    front(k, 1); line(k, ''); k.run_for(0.5)
    check('a task (MTVEC I) whose INT 62h is only in another\'s copy of the table at its spawn (TX_GSN; the table\'s '
          'is the other\'s own): pinned (error 5); both end, INT 62h as before', r2 <= va[0] < r2 + k.pc.u16(r2 - 1, 3)
          and r1 <= gv[1] < r1 + k.pc.u16(r1 - 1, 3) and 'MTLAUNCH: error 5' in o1 and s1 == TS_WAITK
          and vec(k, 0x62) == v62 and back(), (r1, r2, va, gv, o1, s1, now()))

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
    cl = os.path.join(GOS, 'claude', 'CLAUDE.COM')
    k = boot('mt_lc.img', b'MULTITASK=1\r\n', 88, 'SB.BAT=' + sb, 'TW.BAT=' + tw, 'SG.BAT=' + sg, cl,
             os.path.join(HERE, 'UPPER.COM'))
    seg, Y = mt_seg(k), k.Y
    sh = Shell(k)
    sh.run('ver')
    m0, s0, e0 = merged(mcbs(k)), sft_used(k), ems_used(k)
    back = lambda: tstate(k)[0] == [(0, 1, 'Executive')] and merged(mcbs(k)) == m0 and sft_used(k) == s0 \
        and ems_used(k) == e0 and not k.crashed
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
    g = k.pc.rd(seg, Y['mt_tab'] + MT_ENT + 30, 1)[0]
    typ(k, 'wait 1', 0.5)
    k.pc.wr(seg, Y['mt_tab'] + MT_ENT + 30, bytes([g + 1, g + 1]))     # (as if ended, another started and ended)
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
    # a program that can't be started (LCMD.COM in 1 KB): the task ends at once, its code FF08h; WAIT says so
    sh.run('set task=1')                # (both environments copied alike: the next one in the same place)
    o1 = sh.run('start /w /m:1 lcmd.com')
    k.run_for(0.5)
    x1 = xc(1)
    o2 = sh.run('wait 1 || echo FAILED')
    o3 = sh.run('if errorlevel 8 echo LEVEL8')
    check('START /M:1 LCMD.COM: started, but its program can\'t be (EXEC: no memory): MT_EXIT\'s code FF08h; WAIT says it '
          'couldn\'t be started, fails, ERRORLEVEL 8', 'error' not in o1.lower() and x1 and x1.group(3) == 'FF08'
          and 'could not be started' in o2 and 'FAILED' in o2 and 'LEVEL8' in o3 and back(),
          (o1, x1 and x1.groups(), o2, o3))
    # one that can, in the same place (the same size): not taken for one that couldn't (its stub's ST_FAIL cleared)
    rf = k.pc.u16(seg, Y['mt_tab'] + MT_ENT + 4)
    sh.run('start /w /m:1 mtline.com sm.txt')
    rm, s1 = k.pc.u16(seg, Y['mt_tab'] + MT_ENT + 4), tstate(k)[0]
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
    vf = [k.pc.rd(seg, Y['mt_tab'] + t * MT_ENT + 24, 1)[0] for t in (1, 2)]
    r1, r2 = (k.pc.u16(seg, Y['mt_tab'] + t * MT_ENT + 4) for t in (1, 2))
    s1, s2 = k.pc.u16(r1 - 1, 3), k.pc.u16(r2 - 1, 3)
    sh.run('start /w /d mtspin.com 200 fz.txt')     # (a task computing, never run behind: frozen)
    o2 = sh.run('tasks')
    o = sh.run('kill 1 && kill 2 && kill 3 && echo KILLED')
    check('START /B: SPF_BG; START /D: SPF_FREEZE (TE_VF %s); /M:32: 2048 paragraphs for its programs, 32 KB less than '
          'the default 64 KB (regions of %d and %d paragraphs); TASK=2 after the second; START /D MTSPIN: TASKS says '
          '"(frozen)"' % (vf, s2, s1), vf == [2, 4] and s1 - s2 == 2048 and 'TASK=2' in o1
          and re.search(r'3\s+MTSPIN\.COM \(frozen\)', o2) and 'KILLED' in o and back(), (vf, s1, s2, o1, o2, o))
    # a pipe with multitasking on (its files named by LCMD's task: pipe_names asks MT_LIST), none left
    o = sh.run('echo hello there | upper | upper')
    left = [n for n in ('PIPEA1.$$0', 'PIPEA2.$$0', 'PIPEA1.$$$', 'PIPEA2.$$$') if A.disk_file(k, n) is not None]
    check('a pipe (ECHO | UPPER | UPPER) with multitasking on: HELLO THERE, its files gone', re.search(r'^HELLO THERE\s*$', o, re.M)
          and not left and back(), (o, left))
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
    """Return on a program in the Executive (with multitasking on: it starts as a task, in front)."""
    k.select(name); k.key(ktest.ENTER, settle=False); k.run_for(wait)

def t_exec():
    print('== the Executive: Return starts a program as a task (M7b)')
    # off: Return runs it and waits, as before; no entry
    k = boot('mt_ex0.img', None)
    k.select('MTLINE.COM'); k.key(ktest.ENTER, settle=False); k.pc.run_until(lambda: k.pc.mode() != 0x40, 5)
    k.run_for(0.5)
    line(k, '=4'); k.settle()
    b0 = k.band()
    check('off: no MT_UI entry (ui_mtx 0:0, ex_mtw 1 while the Executive waits, as it adds its own 1); Return on '
          'MTLINE.COM runs it and waits: "MTLINE.COM ended, exit code 4"', k.u16('ui_mtx') == 0 and k.u16('ui_mtx', 2) == 0
          and k.rd('ex_mtw', 1) == b'\x01' and b0[:1] == ['MTLINE.COM ended, exit code 4'], (k.rd('ex_mtw', 1), b0))
    mk = os.path.join(A.OUT, 'MKFILE.COM'); open(mk, 'wb').write(MKFILE)
    xs, xa, xb, xm, xl = (mz(os.path.join(A.OUT, n + '.EXE'), mi, ma) for n, mi, ma in
                          (('EXS', 0x20, 0x300), ('EXA', 0x20, 0xFFFF), ('EXB', 0xA000, 0xFFFF), ('EXM', 0x20, 0x20),
                           ('EXL', 0x40, 0x10)))
    k = boot('mt_ex.img', b'MULTITASK=1\r\n', 88, 'MKFILE.COM=' + mk, 'EXS.EXE=' + xs, 'EXA.EXE=' + xa, 'EXB.EXE=' + xb,
             'EXM.EXE=' + xm, 'EXL.EXE=' + xl, A.CALCRUN, A.TSR, os.path.join(GOS, 'apps', 'TASKS.RUN'))
    seg, Y = mt_seg(k), k.Y
    arena = lambda: k.pc.u16(seg, Y['mt_arena'])
    m0, s0, e0 = merged(mcbs(k)), sft_used(k), ems_used(k)
    back = lambda: tstate(k)[:2] == ([(0, 1, 'Executive')], 0) and merged(mcbs(k)) == m0 and sft_used(k) == s0 \
        and ems_used(k) == e0 and k.pc.mode() == 0x40 and not k.crashed
    lists = [k.pc.u16(seg, Y[n]) for n in ('mt_lbg', 'mt_lfz', 'mt_lmem')]
    check('on: the Executive has MT_UI\'s entry (mt_ui in MT\'s block), ex_mtw 2 while it waits; no lists in LODE.INI: '
          'each list empty (mt_lnone)', (k.u16('ui_mtx'), k.u16('ui_mtx', 2)) == (Y['mt_ui'], seg)
          and k.rd('ex_mtw', 1) == b'\x02' and lists == [Y['mt_lnone']] * 3, (k.u16('ui_mtx'), k.rd('ex_mtw', 1), lists))
    # Return: a task in front; its end: the Executive in front, its list again, "X ended, exit code n"
    ret(k, 'MTLINE.COM')
    st1, ar1, scr = tstate(k), arena(), k.pc.text_screen()
    line(k, '=5'); k.run_for(1.0); k.settle()
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
             b'MTMEM=MTLINE:100;LCMD.COM:1 BAD BIG:5000 MTCWD:0 ,\r\n', 88, os.path.join(HERE, 'UPPER.COM'))
    seg, Y = mt_seg(k), k.Y
    bg = b'MTSPIN\0\0\0UPPER\0\0\0X\0\0\0MTLIN\0\0\0\0'
    fz = b'MTLINE.EXE\0\0\0MTCWD.COM\0\0\0\0'
    mm = b'MTLINE\0' + struct.pack('<H', 100) + b'LCMD.COM\0' + struct.pack('<H', 1) + b'\0'
    got = bytes(k.pc.rd(seg, Y['mt_ini'], len(bg + fz + mm)))
    ptr = [k.pc.u16(seg, Y[n]) for n in ('mt_lbg', 'mt_lfz', 'mt_lmem')]
    i0 = Y['mt_ini']
    check('the lists read at start-up (any case, commas, semicolons, blanks; MTMEM= entries without a number, of 0, '
          'or of 1024 KB and more left out)', got == bg + fz + mm and ptr == [i0, i0 + len(bg), i0 + len(bg + fz)], (got, ptr))
    sh = Shell(k)
    sh.run('ver')
    m0, s0, e0 = merged(mcbs(k)), sft_used(k), ems_used(k)
    back = lambda: tstate(k)[0] == [(0, 1, 'Executive')] and merged(mcbs(k)) == m0 and sft_used(k) == s0 \
        and ems_used(k) == e0 and not k.crashed
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
    ret(k, 'LCMD.COM', 1.5); k.settle()
    b2 = k.band()
    check('Return: MTMEM= too (MTLINE.COM: 1900h paragraphs, not a .COM\'s 64 KB); LCMD.COM with 1 KB: "LCMD.COM could '
          'not be started: error 8"', a1 == 0x1900 and b1[:1] == ['MTLINE.COM ended'] and
          b2[:1] == ['LCMD.COM could not be started: error 8'] and tstate(k)[0] == [(0, 1, 'Executive')], (a1, b1, b2))

def t_tasksrun():
    print('== TASKS.RUN: the tasks, CODE-T (M7b)')
    TR = os.path.join(GOS, 'apps', 'TASKS.RUN')
    k = boot('mt_tr0.img', None, 88, TR)
    k.key(A.CODE['T']); k.run_for(0.3)
    t0 = k.text()
    k.key(ktest.ESC); k.run_for(0.3)
    check('off: CODE-T opens Tasks, which says multitasking is off; ESC closes it (exit code 0FFFFh)',
          'Multitasking is off.' in t0 and A.run_ret(k) == 0xFFFF, t0[-600:])
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
    check('MEMSZ (from the Executive), off: 581.7 KB, as with no switch (test_splash.py MEM_044)', m0 and m0.group(1) == '581.7', m0 and m0.group(1))
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

if __name__ == '__main__':
    t0 = time.time()
    A.build()
    for n in ('MTPROBE', 'MTLAUNCH', 'MTLINE', 'MTCWD', 'MTMODE', 'FREEH', 'MTSPIN', 'MTHOOK', 'MTSCR', 'VNEST', 'MTCRIT',
              'MTNEST', 'VHOOK', 'MTKEY', 'MTM33', 'MTVEC', 'MTKILL'):
        subprocess.run(['nasm', '-f', 'bin', '-i', os.path.join(GOS, 'src') + '/',
                        '-o', os.path.join(HERE, n + ('.BIN' if n == 'VNEST' else '.COM')),
                        os.path.join(HERE, n + '.ASM')], check=True)
    only = [a for a in sys.argv[1:] if a.startswith('t_')]
    for t in (t_image, t_off, t_on, t_file, t_tasks, t_ends, t_front, t_preempt, t_rules, t_fpu, t_screens, t_keys, t_mouse, t_vectors, t_kill, t_park, t_lcmd, t_exec, t_lists, t_tasksrun, t_system, t_progs, t_rom):
        if not only or t.__name__ in only: t()
    bad_ = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad_), (': ' + '; '.join(bad_)) if bad_ else '', time.time() - t0))
    sys.exit(1 if bad_ else 0)
