#!/usr/bin/env python3
"""Multitasking (KMT.INC), step 1: the switch and the skeleton.

MULTITASK=1 in LODE.INI (with EMS, enough for the disk cache to be in it)
puts multitasking's resident part in a block of its own at the top of
memory, with INT 08h and INT 21h F0h going through it; one task, the
Executive, and nothing switches yet.  Off (no such line, any other value, or
no EMS), nothing of it is in memory and everything is as before.
python3 tests/test_mt.py [t_image t_off t_on t_file t_progs t_rom]"""
import os, re, subprocess, sys, time
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

MTPROBE = os.path.join(HERE, 'MTPROBE.COM')
SYS = os.path.join(GOS, 'src', 'LODE.SYS')
MTSYS = os.path.join(GOS, 'src', 'LODEMT.SYS')
MAP = os.path.join(GOS, 'src', 'LODE.MAP')
import mkmt
INT08 = (STUB, 0x1000)                  # pcemu's BIOS timer handler

# With the switch off these must not move (0.6 with UI API 6): the kernel's
# image and BSS, the UI block kept while a DOS program runs
OFF_MAP = {'image_end': 0x4450, 'bss_end': 0x7A90, 'ui_keep_end': 0x6CE4}

def ini(text):
    p = os.path.join(A.OUT, 'LODE.INI'); open(p, 'wb').write(text); return 'LODE.INI=' + p

def boot(name, text=None, ems=88, *more, mt=MTSYS):
    """A floppy with LODE.SYS and (unless mt=None) LODEMT.SYS, LCMD, MEMSZ,
    MTPROBE, `more`, and LODE.INI holding `text`."""
    files = ([] if mt is None else ['LODEMT.SYS=' + mt]) + [A.LCMD, A.MEMSZ, MTPROBE] + list(more) \
        + ([ini(text)] if text is not None else [])
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

def probe(k):
    """MTPROBE's lines: {AL: (CF, AX, BX, CX)}."""
    out = k.run_file('MTPROBE.COM', 20)
    got = {}
    for m in re.finditer(r'F0([0-9A-F]{2}) CF=(\d) AX=([0-9A-F]{4}) BX=([0-9A-F]{4}) CX=([0-9A-F]{4})', out):
        got[int(m.group(1), 16)] = (int(m.group(2)), int(m.group(3), 16), int(m.group(4), 16), int(m.group(5), 16))
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
        check('%s: no MT block, INT 08h the BIOS\'s, f_F0 as assembled' % tag,
              mt_seg(k) is None and vec(k, 8) == INT08 and f0_bytes(k) == sysb[k.Y['f_F0']:k.Y['f_F0'] + 5],
              (show(mcbs(k)), vec(k, 8), f0_bytes(k).hex()))
        if tag in ('no LODE.INI', 'MULTITASK=1 but no EMS'):
            got, out = probe(k)
            check('%s: F0h AL=00h answers (4F47h, 0201h); 10h-13h and FFh fail with AX = 1' % tag,
                  got.get(0) == (0, 0x4F47, 0x0201, 0x1234) and all(bad(got.get(a, (0, 0, 0, 0))) for a in (0x10, 0x11, 0x12, 0x13, 0xFF)),
                  out[-400:])
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
    check('a block of its own, owner 8, called MT, %d paragraphs: the last one, ending at A000h, one free block below it' % paras,
          at_top(k) and arena[-1][3] == paras and arena[-2][3] > 0x8000, show(arena))
    check('INT 08h goes through mt_tick', vec(k, 8) == (seg, Y['mt_tick']), (vec(k, 8), hex(seg or 0)))
    old = (k.pc.u16(seg, Y['mt_old08'] + 2), k.pc.u16(seg, Y['mt_old08']))
    check('... which goes on to the BIOS\'s', old == INT08, old)
    f0 = f0_bytes(k)
    check('INT 21h F0h goes through mt_f0 (JMP FAR over f_F0\'s first 5 bytes)',
          f0[0] == 0xEA and f0[1] | f0[2] << 8 == Y['mt_f0'] and f0[3] | f0[4] << 8 == seg, f0.hex())
    check('task 0 is the Executive: its PSP the root process\'s',
          k.pc.u16(seg, Y['mt_tab'] + 2) == k.u16('root_psp'), (hex(k.pc.u16(seg, Y['mt_tab'] + 2)), hex(k.u16('root_psp'))))
    t0, b0 = k.pc.u16(seg, Y['mt_ticks']), k.pc.u16(0x40, 0x6C)
    k.run_for(2.0)
    t1, b1 = k.pc.u16(seg, Y['mt_ticks']), k.pc.u16(0x40, 0x6C)
    check('2 s: mt_tick ran %d times, the BIOS counted %d ticks (18.2 a second)' % (t1 - t0, b1 - b0),
          t1 - t0 == b1 - b0 and 34 <= b1 - b0 <= 38, (t1 - t0, b1 - b0))
    got, out = probe(k)
    check('F0h through mt_f0: AL=00h still answers (4F47h, 0201h: its OR AL,AL redone); 10h, 11h, 13h, FFh fail with AX = 1',
          got.get(0) == (0, 0x4F47, 0x0201, 0x1234) and all(bad(got.get(a, (0, 0, 0, 0))) for a in (0x10, 0x11, 0x13, 0xFF)), out[-400:])
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

def t_progs():
    print('== MULTITASK=1: DOS programs as before')
    k0 = boot('mt_mem0.img', b'MULTITASK=0\r\n')
    k1 = boot('mt_mem1.img', b'MULTITASK=1\r\n')
    a0, a1 = mcbs(k0), mcbs(k1)
    paras = (k1.Y['mt_tend'] - k1.Y['mt_tstart'] + 15) // 16
    check('free memory with it on: exactly MT\'s %d paragraphs and its MCB less (%d bytes)' % (paras, (paras + 1) * 16),
          a0[-1][2] == 0 and a1[-2][2] == 0 and a1[-2][3] == a0[-1][3] - (paras + 1) and a0[:-1] == a1[:-2], (show(a0), show(a1)))
    m0 = re.search(r'([\d.]+) KB for programs', k0.run_file('MEMSZ.COM', 30))
    m1 = re.search(r'([\d.]+) KB for programs', k1.run_file('MEMSZ.COM', 30))
    print('   MEMSZ: %s KB off, %s KB on' % (m0 and m0.group(1), m1 and m1.group(1)))
    check('MEMSZ (from the Executive), off: 577.8 KB, as with no switch', m0 and m0.group(1) == '577.8', m0 and m0.group(1))
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
    """SFT entries in use (S_REF, the first byte of each of 24 x 44)."""
    base = k.Y['sft']
    return sum(1 for i in range(24) if k.pc.rd(0x60, base + i * 44, 1)[0] != 0)

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
              'INT 08h and f_F0 untouched' % tag,
              mt_seg(k) is None and merged(mcbs(k)) == merged(a0) and sft_used(k) == used0 and vec(k, 8) == INT08
              and f0_bytes(k)[0] == 0x8A and k.pc.mode() == 0x40, (show(mcbs(k)), show(a0), sft_used(k), used0))
    k = boot('mt_f1.img', b'MULTITASK=1\r\n', mt=MTSYS)
    check('... and the file as built: on (no file left open either)', at_top(k) and sft_used(k) == used0, (show(mcbs(k)), sft_used(k)))

if __name__ == '__main__':
    t0 = time.time()
    A.build()
    subprocess.run(['nasm', '-f', 'bin', '-o', MTPROBE, os.path.join(HERE, 'MTPROBE.ASM')], check=True)
    only = [a for a in sys.argv[1:] if a.startswith('t_')]
    for t in (t_image, t_off, t_on, t_file, t_progs, t_rom):
        if not only or t.__name__ in only: t()
    bad_ = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad_), (': ' + '; '.join(bad_)) if bad_ else '', time.time() - t0))
    sys.exit(1 if bad_ else 0)
