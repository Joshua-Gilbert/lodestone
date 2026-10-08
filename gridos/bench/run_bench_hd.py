"""BENCH.COM on drive C: under Grid-OS, in pcemu with the hard disk timed
(seeks and rotation; see pcemu.Ata's `timed`), on the layout of Joshua's
CP30104H (its own partition table and boot sector: 762 x 8 x 39, one
121 MB FAT16 partition, 2 KB clusters) with about 800 KB of files at the
start, as on the real disk.  Prints BENCH's report and a table from the
emulator's exact timing points, with and without EMS.

    python3 bench/run_bench_hd.py

GRiD MS-DOS 3.30 can't be compared here: its BIOS doesn't know the drive,
and DOS 3.30 can't use a partition over 32 MB anyway.
"""
import os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(GOS, 'tests'))
import pcemu, mkimg, ktest, run_bench, fat16img as F

ROM = os.path.join(GOS, '..', 'rom', 'hd_cp30104h')
BENCH = os.path.join(HERE, 'BENCH.COM')


def drive(lookahead=False):
    sect0 = open(os.path.join(ROM, 'HDSECT0.BIN'), 'rb').read()
    plba, n = struct.unpack_from('<II', sect0, 446 + 8)
    f = F.Fat(n, 4, plba, True)
    files = [('IO.SYS', 0x07, b'I' * 33430), ('MSDOS.SYS', 0x07, b'M' * 37394), ('COMMAND.COM', 0x20, b'C' * 47845),
             ('DOS', 0, [('F%02d.EXE' % i, 0x20, bytes([65 + i % 26]) * (14000 + 900 * i)) for i in range(36)])]
    f.finish(f.tree(files))
    f.img[0:512] = open(os.path.join(ROM, 'HDBOOT.BIN'), 'rb').read()
    d = bytearray(762 * 8 * 39 * 512); d[0:512] = sect0; d[plba * 512:(plba + n) * 512] = f.img
    return pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=762, heads=8, spt=39, disk=d,
                     timed=True, rpm=3360, lookahead=lookahead)


def run(ems, lookahead=False):
    img = mkimg.build(os.path.join(run_bench.TMP, 'hd.img'), [os.path.join(GOS, 'src', 'GRIDOS.SYS'),
                                                             os.path.join(GOS, 'src', 'GRIDCMD.COM'), BENCH])
    k = ktest.KPC(img, ata=drive(lookahead), disk_model='real', ems_pages=88 if ems else 0)
    k.start(20)
    k.key(ktest.CODE_P)                                 # the prompt, C: current, BENCH from A:
    k.key('c:'); k.key(ktest.ENTER)
    k.pc.tty.clear()
    k.key('a:bench'); k.key(ktest.ENTER, settle=False)
    tty = lambda: ''.join(k.pc.tty)
    ktest.run_answering(k.pc, lambda: 'Results added' in tty() and k.pc.text_screen().rstrip().endswith('>'), 900)
    return k.pc, tty()


if __name__ == '__main__':
    t = time.time()
    res = []
    for la in (False, True):
        pc, out = run(True, la)
        print('==== Grid-OS on C: with EMS, the drive %s look-ahead ====\n%s\n' % ('with' if la else 'without', out.strip()))
        res.append(run_bench.results(pc))
    print('%-32s %10s %10s' % ('emulator timing (s)', 'no look-ahead', 'look-ahead'))
    for n, a, b in zip(run_bench.NAMES, *res):
        print('%-32s %10s %10s' % (n, a and '%.3f' % a[0], b and '%.3f' % b[0]))
    print('%-32s %10.2f %10.2f' % ('Total', *(sum(x[0] for x in r if x) for r in res)))
    print('(wall %.0f s)' % (time.time() - t))
