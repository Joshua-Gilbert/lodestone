#!/usr/bin/env python3
"""Multitasking (KMT.INC): the switch and the skeleton (M1), tasks switched
when one waits for a key (M2a), the front one chosen with CODE-Tab, each with
its own screen (M2b), preempted at the timer's tick where it is safe (M3).

(pcemu's INT 16h AH=00h with no key blocks at the caller's own INT 16h, so a
program waiting there can be preempted; on the 1520 it waits inside the BIOS,
where it can't.)

MULTITASK=1 in LODE.INI (with EMS, enough for the disk cache to be in it)
puts multitasking's resident part in a block of its own at the top of
memory, with INT 08h, INT 21h F0h and the kernel's key wait going through
it.  Programs start others as tasks (MTLAUNCH), each in a region of its own,
and they take turns at the timer's tick, where it is safe.  Off (no such
line, any other value, or no EMS), nothing of it is in memory and everything
is as before.
python3 tests/test_mt.py [t_image t_off t_on t_file t_tasks t_ends t_front t_preempt t_rules t_fpu t_progs t_rom]"""
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
MTL, MTLN, MTCW, MTMD, FREEH, MTSP, MTHK = (os.path.join(HERE, n + '.COM') for n in ('MTLAUNCH', 'MTLINE', 'MTCWD', 'MTMODE', 'FREEH',
                                                                                    'MTSPIN', 'MTHOOK'))
SYS = os.path.join(GOS, 'src', 'LODE.SYS')
MTSYS = os.path.join(GOS, 'src', 'LODEMT.SYS')
MAP = os.path.join(GOS, 'src', 'LODE.MAP')
import mkmt
INT08 = (STUB, 0x1000)                  # pcemu's BIOS timer handler
MT_ENT, TE_NAME, TE_SH = 32, 10, 22      # KMT.INC: an entry in mt_tab, its name, its screen's EMS handle

# With the switch off these must not move (main with UI API 6 and PrtSc's printing): the kernel's
# image and BSS, the UI block kept while a DOS program runs
OFF_MAP = {'image_end': 0x44E0, 'bss_end': 0x7B30, 'ui_keep_end': 0x6CE4}

def ini(text):
    p = os.path.join(A.OUT, 'LODE.INI'); open(p, 'wb').write(text); return 'LODE.INI=' + p

def boot(name, text=None, ems=88, *more, mt=MTSYS, nofpu=False):
    """A floppy with LODE.SYS and (unless mt=None) LODEMT.SYS, LCMD, MEMSZ,
    MTPROBE, `more`, and LODE.INI holding `text`.  nofpu: INT 11h says no
    coprocessor, and the 286's EM bit is set, so any coprocessor instruction
    traps (INT 7, counted in pc.ints)."""
    files = ([] if mt is None else ['LODEMT.SYS=' + mt]) + [A.LCMD, A.MEMSZ, MTPROBE, MTL, MTLN, MTCW, MTMD, FREEH, MTSP, MTHK] + list(more) \
        + ([ini(text)] if text is not None else [])
    k = ktest.KPC(A.image(name, *files), ems_pages=ems)
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

def f0_bytes(k): return bytes(k.pc.rd(0x60, k.Y['f_F0'], 5))
def kw_bytes(k): return bytes(k.pc.rd(0x60, k.Y['kbd_get.k'], 6))
def dx_bytes(k): return bytes(k.pc.rd(0x60, k.Y['done.sw'], 5))
EXIT5 = bytes([0x8E, 0xD0, 0x89, 0xDC, 0x61])      # MOV SS,AX / MOV SP,BX / POPA

def probe(k):
    """MTPROBE's lines: {AL: (CF, AX, BX, CX)}."""
    out = k.run_file('MTPROBE.COM', 20)
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
        check('%s: no MT block, INT 08h the BIOS\'s, f_F0, kbd_get.k and done.sw as assembled' % tag,
              mt_seg(k) is None and vec(k, 8) == INT08 and f0_bytes(k) == sysb[k.Y['f_F0']:k.Y['f_F0'] + 5]
              and kw_bytes(k) == sysb[k.Y['kbd_get.k']:k.Y['kbd_get.k'] + 6] and dx_bytes(k) == EXIT5,
              (show(mcbs(k)), vec(k, 8), f0_bytes(k).hex()))
        if tag in ('no LODE.INI', 'MULTITASK=1 but no EMS'):
            got, out = probe(k)
            check('%s: F0h AL=00h answers (4F47h, 0201h); 11h-14h, 1Bh and FFh fail with AX = 1' % tag,
                  got.get(0) == (0, 0x4F47, 0x0201, 0x1234) and all(bad(got.get(a, (0, 0, 0, 0))) for a in (0x11, 0x12, 0x13, 0x14, 0x1B, 0xFF)),
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
          'with AX = 1; 13h with task 0 works', got.get(0) == (0, 0x4F47, 0x0201, 0x1234)
          and all(bad(got.get(a, (0, 0, 0, 0))) for a in (0x11, 0x14, 0x1B, 0xFF)) and got.get(0x13, (1,))[0] == 0, out[-400:])
    check('F0h AL=13h with BL = 8 (no such task) and BL = 7 (a free one): CF, AX = 1',
          bad(got.get(0x113, (0, 0))) and bad(got.get(0x213, (0, 0))), out[-400:])
    check('F0h AL=12h with no room: CF clear, CX = 1 task, AL = 0 in front, nothing written', got.get(0x12, (1,))[:2] == (0, 0xF000)
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
          'the Executive\'s task in front; both prompts on the screen',
          st == ([(0, 1, 'Executive'), (1, 2, 'MTLINE.COM'), (2, 2, 'MTLINE.COM')], 0, 0)
          and k.pc.text_screen().count('MTLINE>') >= 2, (st, k.pc.text_screen()))
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
    v = sh.run('ver')                   # (the screen is shared until M4: the prompt's line is a jumble)
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
    s1 = k.pc.text_screen()
    check('CODE-Tab while MTLAUNCH waits: task 1 to the front, the key taken out of the buffer; its screen, never shown '
          'yet, clear in mode 3', tstate(k)[1] == 1 and no_hot(k) and s1.strip() == '' and k.pc.mode() == 3,
          (tstate(k), k.pc.kbd_ring(), s1[-200:]))
    k.key('hel'); k.run_for(0.3)
    check('... what is typed goes to task 1, and shows on its screen', 'hel' in k.pc.text_screen(), k.pc.text_screen()[-200:])
    hot(k)
    check('CODE-Tab again: task 2, its screen clear', tstate(k)[1] == 2 and k.pc.text_screen().strip() == '', (tstate(k), k.pc.text_screen()[-200:]))
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
    check('CODE-Tab at the command prompt, a task waiting: nothing switches (LCMD asks with INT 21h AH=0Bh), and the key '
          'is gone (the BIOS drops it there)', st[0] == [(0, 1, 'Executive'), (1, 2, 'MTLINE.COM')] and st[1] == 0
          and no_hot(k), (st, k.pc.kbd_ring()))
    sh.run('mtlaunch')
    hot(k)
    st = tstate(k)
    line(k, 'late'); line(k, '')
    v = sh.run('ver')
    check('... with MTLAUNCH waiting, CODE-Tab brings it up; it gets its line ("late": L.TXT); the prompt goes on',
          st[1] == 1 and A.disk_file(k, 'L.TXT') == b'late' and tstate(k) == ([(0, 1, 'Executive')], 0, 0)
          and 'Lodestone version' in v and ems_used(k) == e0, (st, A.disk_file(k, 'L.TXT'), tstate(k), v))
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
    hot(k); line(k, 'b'); line(k, '')
    check('task 0\'s screen kept (task 1 in front with /F), then its handle freed (FREEH, task 2): back in front it '
          'can\'t be mapped, so task 0 comes back clear in mode 3 and keeps none; the rest goes on',
          st[1] == 1 and bytes(sf) == bytes([h0, 1]) and sc.strip() == '' and m == 3 and bytes(h1) == b'\0\0'
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
    there); the stack used below the caller's SP until MT is done there (every block, kernel calls included).
    Every call of mt_safe that fails one rule alone counts under that rule (only), so the tests can show each one
    was met.  force: a switch due on every INT 21h way out (mt_pend set at mt_exit), so every one is checked."""
    def __init__(s, k):
        s.k, s.ev, s.force, s.track = k, [], False, None
        s.depth, s.only = {'tick': 0, 'exit': 0}, collections.Counter()
        s.seg = seg = mt_seg(k)
        s.at, s.sa, s.swa, s.ex = (seg * 16 + k.Y[n] for n in ('mt_preempt', 'mt_safe', 'mt_switch', 'mt_exit'))
        s.fd, s.fdw, s.due = seg * 16 + k.Y['mt_fdrain'], seg * 16 + k.Y['mt_fdrain.w'], False
        s.inject, s.injected, s.open, s.nested = None, 0, {}, collections.Counter()
        # (IRQ 13 at mt_fdrain, when inject() says; open drains: SS -> the SP and where its call returns; switches
        #  started inside one, by path)
        s.ret = {k.Y['mt_tick.r']: 'tick', k.Y['mt_exit.n']: 'exit'}
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
            if pc.r('ss') != s.track[0] or pc.r('cs') not in (s.seg, 0x60): s.track = None
            else: s.depth[s.track[2]] = max(s.depth[s.track[2]], s.track[1] - pc.r('sp'))
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
        elif a == s.at:
            ss, sp = pc.r('ss'), pc.r('sp')
            path = s.ret.get(pc.u16(ss, sp), '?')
            if ss in s.open: s.nested[path] += 1            # (inside a drain of this task's, its IRQ 13 handler's)
            f = sp + 12 if path == 'tick' else sp + 4 + 20     # (mt_tick's 5 pushes, or BP and INT 21h's frame: IP, CS, FL)
            ip, cs, fl = pc.u16(ss, f), pc.u16(ss, f + 2), pc.u16(ss, f + 4)
            r, cur = s.rules(cs, ip, fl, ss)
            if path == 'tick': r['ivt'] = vec(k, 8) == (s.seg, k.Y['mt_tick'])   # (else a hook ahead was interrupted)
            s.ev.append(dict(path=path, cs=cs, ip=ip, fl=fl, task=cur, ss=ss, r=r, sw=False,
                             ok=path != '?' and all(r.values())))
            s.track = (ss, f + 6, path)                          # (the caller's SP: under the frame)
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
    dx = len(au.switches(n, 'exit'))
    check('the same with an INT 21h call on every count (AH=2Ch): about half each (alone %d; %d and %d), %d of the '
          'switches on INT 21h\'s way out' % (d0, d1, d2, dx), d0 > 0 and 0.3 * d0 < d1 < 0.7 * d0 and 0.3 * d0 < d2 < 0.7 * d0
          and dx >= 10, (d0, d1, d2, dx))
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
    scr = k.pc.text_screen()
    k.key('a'); k.run_for(2)
    k.pc.drives[0].bad = set()
    st = tstate(k) if not k.crashed else None
    line(k, '')
    v = sh.run('ver')
    # (EXEC's own entry for the program it reads, which no handle holds, stays taken: the kernel's EXEC doesn't
    # give it back when it is aborted, with multitasking or without)
    d = [b - a for a, b in zip(used0, sft_used(k))]
    check('a read error while the stub EXECs its program, answered Abort: the stub ends itself (its own parent) and its '
          'task with it; MTLAUNCH, then the prompt, go on; memory as before, the handles the stub inherited closed',
          'Abort' in scr and not k.crashed and st and st[0] == [(0, 1, 'Executive')] and 'Lodestone version' in v
          and merged(mcbs(k)) == a0 and sorted(d) == [0] * 23 + [1] and used0[d.index(1)] == 0 and ems_used(k) == e0,
          (scr[-300:], st, v, d, ems_used(k), e0))
    k = boot('mt_tsr.img', b'MULTITASK=1\r\n', 88, os.path.join(HERE, 'TSR.COM'))
    sh = Shell(k)
    sh.run('ver')
    e0 = ems_used(k)
    o = sh.run('mtlaunch tsr.com')
    line(k, '')
    a = mcbs(k)
    v = sh.run('ver')
    check('a program that stays resident in a task (TSR.COM, AH=31h): the task ends, its region stays (renamed TR, '
          'the system\'s); the prompt goes on', not k.crashed and tstate(k)[0] == [(0, 1, 'Executive')]
          and [(b[4], b[2]) for b in a[-2:]] == [(b'TR', 8), (b'MT', 8)] and 'Lodestone version' in v
          and ems_used(k) == e0, (show(a), v, ems_used(k), e0))
    o = sh.run('mtlaunch mtline.com t.txt')
    a1 = mcbs(k)
    front(k, 1); line(k, 'next')
    line(k, '')
    a = mcbs(k)
    check('... and the next task\'s region goes below it (T1), and ends', A.disk_file(k, 'T.TXT') == b'next'
          and [(b[4], b[2]) for b in a1[-3:]] == [(b'T1', 8), (b'TR', 8), (b'MT', 8)]
          and tstate(k)[0] == [(0, 1, 'Executive')] and [(b[4], b[2]) for b in a[-2:]] == [(b'TR', 8), (b'MT', 8)],
          (show(a1), show(a), A.disk_file(k, 'T.TXT')))

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

def t_progs():
    print('== MULTITASK=1: DOS programs as before')
    k0 = boot('mt_mem0.img', b'MULTITASK=0\r\n')
    k1 = boot('mt_mem1.img', b'MULTITASK=1\r\n')
    a0, a1 = mcbs(k0), mcbs(k1)
    paras = (k1.Y['mt_bend'] + 15) // 16
    check('free memory with it on: exactly MT\'s %d paragraphs and its MCB less (%d bytes)' % (paras, (paras + 1) * 16),
          a0[-1][2] == 0 and a1[-2][2] == 0 and a1[-2][3] == a0[-1][3] - (paras + 1) and a0[:-1] == a1[:-2], (show(a0), show(a1)))
    m0 = re.search(r'([\d.]+) KB for programs', k0.run_file('MEMSZ.COM', 30))
    m1 = re.search(r'([\d.]+) KB for programs', k1.run_file('MEMSZ.COM', 30))
    print('   MEMSZ: %s KB off, %s KB on' % (m0 and m0.group(1), m1 and m1.group(1)))
    check('MEMSZ (from the Executive), off: 577.6 KB, as with no switch (test_splash.py MEM_044)', m0 and m0.group(1) == '577.6', m0 and m0.group(1))
    k = boot('mt_progs.img', b'MULTITASK=1\r\n', 88, os.path.join(HERE, 'TESTDOS.COM'), os.path.join(HERE, 'EMSTEST.COM'),
             os.path.join(HERE, 'CACHETST.COM'))
    out = k.run_file('TESTDOS.COM', 120)
    check('TESTDOS: no failures', 'FAIL' not in out and ' 0 failed' in out, out[-300:])
    out = k.run_file('EMSTEST.COM', 300)
    check('EMSTEST: no failures', 'FAIL' not in out and ' 0 failed' in out, out[-300:])
    out = k.run_file('CACHETST.COM', 900)
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
    for n in ('MTPROBE', 'MTLAUNCH', 'MTLINE', 'MTCWD', 'MTMODE', 'FREEH', 'MTSPIN', 'MTHOOK'):
        subprocess.run(['nasm', '-f', 'bin', '-i', os.path.join(GOS, 'src') + '/', '-o', os.path.join(HERE, n + '.COM'),
                        os.path.join(HERE, n + '.ASM')], check=True)
    only = [a for a in sys.argv[1:] if a.startswith('t_')]
    for t in (t_image, t_off, t_on, t_file, t_tasks, t_ends, t_front, t_preempt, t_rules, t_fpu, t_progs, t_rom):
        if not only or t.__name__ in only: t()
    bad_ = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad_), (': ' + '; '.join(bad_)) if bad_ else '', time.time() - t0))
    sys.exit(1 if bad_ else 0)
