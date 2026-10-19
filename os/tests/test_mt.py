#!/usr/bin/env python3
"""Multitasking (KMT.INC), step 1: the switch and the skeleton.

MULTITASK=1 in LODE.INI (with EMS) puts multitasking's resident part in a
block of its own at the top of memory, with INT 08h and INT 21h F0h going
through it; one task, the Executive, and nothing switches yet.  Off (no such
line, MULTITASK=0, or no EMS), nothing of it is in memory and everything is
as before.  python3 tests/test_mt.py [t_off t_on t_progs]"""
import os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest
import test_apps as A
from test_kernel import Shell
from pcemu import STUB

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:600]) if detail and not cond else ''))

def ini(text):
    p = os.path.join(A.OUT, 'LODE.INI'); open(p, 'wb').write(text); return 'LODE.INI=' + p

def boot(name, text=None, ems=88, *more):
    files = [A.LCMD, A.MEMSZ] + list(more) + ([ini(text)] if text is not None else [])
    k = ktest.KPC(A.image(name, *files), ems_pages=ems); k.start(10)
    return k

def mcbs(k):
    """The memory arena: (segment of the MCB, type, owner, paragraphs, name)."""
    pc, seg, out = k.pc, k.u16('first_mcb'), []
    while True:
        t, own, sz, nm = chr(pc.rd(seg, 0, 1)[0]), pc.u16(seg, 1), pc.u16(seg, 3), pc.rd(seg, 8, 2)
        out.append((seg, t, own, sz, nm))
        if t != 'M' or len(out) > 200: return out
        seg += sz + 1

def mt_seg(k):
    """MT's block (its segment), or None."""
    for seg, t, own, sz, nm in mcbs(k):
        if nm == b'MT' and own == 8: return seg + 1
    return None

def vec(k, n): return k.pc.u16(0, n * 4 + 2), k.pc.u16(0, n * 4)

def memsz(k):
    m = re.search(r'([\d.]+) KB for programs', k.run_file('MEMSZ.COM', 30))
    return float(m.group(1)) if m else None

OFF_MSG = 'Multitasking is off (MULTITASK=1 in LODE.INI)'

def t_off():
    print('== off: nothing of it in memory, everything as before')
    for tag, text, ems in (('no MULTITASK= line', b'SPLASH=0\r\n', 88), ('MULTITASK=0', b'MULTITASK=0\r\n', 88),
                           ('MULTITASK=Off', b'MULTITASK=Off\r\n', 88), ('MULTITASK=1 but no EMS', b'MULTITASK=1\r\n', 0)):
        k = boot('mt_off.img', text, ems)
        Y = k.Y
        check('%s: no MT block, INT 08h the BIOS\'s, INT 21h F0h as it was' % tag,
              mt_seg(k) is None and vec(k, 8)[0] == STUB and k.pc.rd(0x60, Y['f_F0'], 1)[0] == 0x8A,
              (mcbs(k)[-3:], vec(k, 8), k.pc.rd(0x60, Y['f_F0'], 5).hex()))
        sh = Shell(k)
        o = sh.run('tasks || echo FAILED')
        check('%s: TASKS says it is off, and fails (ERRORLEVEL 1)' % tag, OFF_MSG in o and 'FAILED' in o, o)

def t_on():
    print('== MULTITASK=1: the switch and the skeleton')
    k = boot('mt_on.img', b'MULTITASK=1\r\n')
    Y = k.Y
    seg = mt_seg(k)
    arena = mcbs(k)
    paras = (Y['mt_tend'] - Y['mt_tstart'] + 15) // 16
    check('a block of its own, owner 8, called MT, %d paragraphs: the last one, at the top of memory' % paras,
          seg is not None and arena[-1][0] == seg - 1 and arena[-1][1] == 'Z' and arena[-1][3] == paras
          and seg + paras == 0xA000, [(hex(s), t, hex(o), sz, n) for s, t, o, sz, n in arena[-4:]])
    check('DOS programs still get one block below it (the free space before it is one block)',
          arena[-2][2] == 0 and arena[-2][3] > 0x8000, [(hex(s), t, hex(o), sz, n) for s, t, o, sz, n in arena[-4:]])
    check('INT 08h goes through mt_tick', vec(k, 8) == (seg, Y['mt_tick']), (vec(k, 8), hex(seg or 0)))
    old = (k.pc.u16(seg, Y['mt_old08'] + 2), k.pc.u16(seg, Y['mt_old08']))
    check('... which goes on to the BIOS\'s', old[0] == STUB, old)
    f0 = k.pc.rd(0x60, Y['f_F0'], 5)
    check('INT 21h F0h goes through mt_f0 (a far jump over f_F0\'s first 5 bytes)',
          f0[0] == 0xEA and f0[1] | f0[2] << 8 == Y['mt_f0'] and f0[3] | f0[4] << 8 == seg, f0.hex())
    check('task 0 is the Executive: its PSP the root process\'s',
          k.pc.u16(seg, Y['mt_tab'] + 2) == k.u16('cur_psp'), (hex(k.pc.u16(seg, Y['mt_tab'] + 2)), hex(k.u16('cur_psp'))))
    t0, b0 = k.pc.u16(seg, Y['mt_ticks']), k.pc.u16(0x40, 0x6C)
    k.run_for(2.0)
    t1, b1 = k.pc.u16(seg, Y['mt_ticks']), k.pc.u16(0x40, 0x6C)
    check('2 s: mt_tick ran %d times, the BIOS counted %d ticks (18.2 a second)' % (t1 - t0, b1 - b0),
          t1 - t0 == b1 - b0 and 34 <= b1 - b0 <= 38, (t1 - t0, b1 - b0))
    sh = Shell(k)
    o = sh.run('tasks && echo WORKED')
    check('TASKS lists one task, the Executive, in front (ERRORLEVEL 0)',
          re.search(r'^\s*0\s+Executive \(in front\)\s*$', o, re.M) and 'WORKED' in o and OFF_MSG not in o
          and len([l for l in o.split('\n') if 'Executive' in l]) == 1, o)
    k = boot('mt_on.img', b'MULTITASK=1\r\n')
    k.key(ktest.F1)
    lent = k.u16('wseg')
    k.key(ktest.ESC)
    back = k.u16('wseg')
    check('the other F0h calls go on to the kernel: the help window\'s save-under borrows the disk cache\'s memory (AL=2) and gives it back (AL=3)',
          lent != 0 and back == 0, (hex(lent), hex(back)))
    for text in (b'MULTITASK=Yes\r\n', b'multitask=on\r\n', b'NOTE=MULTITASK=0\r\nMULTITASK=1\r\n'):
        k = boot('mt_on2.img', text)
        check('%r: on' % text, mt_seg(k) is not None, mcbs(k)[-2:])
    k = boot('mt_md.img', b'MULTITASK=1\r\nMDISK=512\r\n')
    check('MULTITASK=1 and MDISK=512: both (M: is 512 KB)', mt_seg(k) is not None and A.md_pages(k) == 32, (A.md_pages(k), mcbs(k)[-2:]))
    k = boot('mt_md.img', b'MDISK=0\r\nMULTITASK=1\r\n')
    check('MDISK=0 and MULTITASK=1: M: off, multitasking on', mt_seg(k) is not None and A.md_pages(k) == 0, (A.md_pages(k), mcbs(k)[-2:]))

def t_progs():
    print('== MULTITASK=1: DOS programs as before')
    k0 = boot('mt_mem0.img', b'SPLASH=0\r\n')
    k1 = boot('mt_mem1.img', b'MULTITASK=1\r\n')
    kb0, kb1 = memsz(k0), memsz(k1)
    paras = (k1.Y['mt_tend'] - k1.Y['mt_tstart'] + 15) // 16 + 1
    check('a DOS program gets %.1f KB with it on, %.1f KB off: MT\'s block, %d bytes, less' % (kb1, kb0, paras * 16),
          kb0 is not None and kb1 is not None and abs((kb0 - kb1) - paras * 16 / 1024) < 0.1, (kb0, kb1))
    k = boot('mt_progs.img', b'MULTITASK=1\r\n', 88, os.path.join(HERE, 'TESTDOS.COM'), os.path.join(HERE, 'EMSTEST.COM'),
             os.path.join(HERE, 'CACHETST.COM'))
    out = k.run_file('TESTDOS.COM', 120)
    check('TESTDOS: no failures', 'FAIL' not in out and ' 0 failed' in out, out[-300:])
    out = k.run_file('EMSTEST.COM', 300)
    check('EMSTEST: no failures', 'FAIL' not in out and ' 0 failed' in out, out[-300:])
    out = k.run_file('CACHETST.COM', 900)
    check('CACHETST: every byte reads back as written', ' 0 errors' in out, out[-300:])
    check('back in the Executive, MT still there and still ticking',
          k.pc.mode() == 0x40 and not k.crashed and mt_seg(k) is not None and vec(k, 8)[0] == mt_seg(k), k.where())

if __name__ == '__main__':
    t0 = time.time()
    A.build()
    only = [a for a in sys.argv[1:] if a.startswith('t_')]
    for t in (t_off, t_on, t_progs):
        if not only or t.__name__ in only: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
