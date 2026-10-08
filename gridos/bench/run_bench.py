"""BENCH.COM on Grid-OS 0.2 and on GRiD MS-DOS 3.30, both in pcemu with the
real-drive timing model (seek, rotation, motor), from the same kind of
1.44 MB floppy.  Prints both reports and a side-by-side table from the
emulator's exact timing points.

    python3 bench/run_bench.py [path-to-GRiD-MS-DOS-EPROM-image]
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import pcemu, mkimg, ktest, dosimg

ROM = next((p for p in (sys.argv[1] if len(sys.argv) > 1 else '', os.environ.get('GRID_ROM', ''),
                        os.path.join(GOS, '..', 'rom', 'GRID_MSDOS330_ROM_300909-00.BIN'))
            if p and os.path.exists(p)), None)
BENCH = os.path.join(HERE, 'BENCH.COM')
TMP = os.path.join(__import__('tempfile').gettempdir(), 'gridos-bench')
os.makedirs(TMP, exist_ok=True)
NAMES = ['Write 256 KB (16 KB writes)', 'Read 256 KB (16 KB reads)', 'Read 256 KB (512-byte reads)',
         'Read 256 KB (128-byte reads)', '64 random 512-byte reads', 'Directory listing x 10',
         'Open + close x 100', '20 small files: create, delete', 'Load + run 120 KB .EXE x 3',
         'INT 21h calls x 1000']


def results(pc):
    m = {b: (us, n13, secs) for b, us, n13, secs in pc.marks}
    out = []
    for i in range(1, len(NAMES) + 1):
        if 2 * i in m and 2 * i + 1 in m:
            a, b = m[2 * i], m[2 * i + 1]
            out.append(((b[0] - a[0]) / 1e6, b[1] - a[1], b[2] - a[2]))
        else:
            out.append(None)
    return out


def run_gridos(prog=BENCH, kernel=None, limit=600):
    img = mkimg.build(os.path.join(TMP, 'gridos.img'), [kernel or os.path.join(GOS, 'src', 'GRIDOS.SYS'),
                                                        os.path.join(GOS, 'src', 'GRIDCMD.COM'), prog])
    k = ktest.KPC(img, disk_model='real')
    if kernel and os.path.exists(os.path.splitext(kernel)[0] + '.MAP'):
        k.Y = ktest.Syms(os.path.splitext(kernel)[0] + '.MAP')   # that kernel's symbols
    k.start(20)
    k.pc.tty.clear()
    k.select(os.path.basename(prog).upper()); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() != 0x40, 10)
    ktest.run_answering(k.pc, lambda: k.pc.mode() == 0x40, limit)
    return k.pc, ''.join(k.pc.tty)


def run_msdos(prog=BENCH, done='Total', limit=600):
    img = dosimg.build(os.path.join(TMP, 'msdos.img'), ROM, [prog])
    pc = pcemu.PC(img, disk_model='real')
    raw = open(img, 'rb').read()
    pc.mu.mem_write(0x7C00, raw[:512])                 # the boot sector's BPB at 0:7C00
    data = 1 + 2 * 9 + 14                               # IO.SYS's first sectors (its own loader)
    pc.mu.mem_write(0x700, raw[data * 512:(data + 3) * 512])
    for r, v in (('cs', 0x70), ('ip', 0), ('ax', 0), ('dx', 0), ('ss', 0), ('sp', 0x7C00), ('ds', 0), ('es', 0)):
        pc.w(r, v)
    pc.w('flags', 0x202)
    tty = lambda: ''.join(pc.tty)
    pc.run_until(lambda: 'new date' in tty(), 60); pc.keys.append(0x1C0D)
    pc.run_until(lambda: 'new time' in tty(), 30); pc.keys.append(0x1C0D)
    pc.run_until(lambda: tty().rstrip().endswith('>'), 30)
    n0 = len(pc.tty)
    for ch in os.path.splitext(os.path.basename(prog))[0].upper(): pc.keys.append(ord(ch))
    pc.keys.append(0x1C0D)
    ktest.run_answering(pc, lambda: done in tty()[n0:] and tty().rstrip().endswith('>'), limit)
    return pc, tty()[n0:]


if __name__ == '__main__':
    if not ROM: sys.exit('needs the GRiD MS-DOS EPROM image (GRID_MSDOS330_ROM_300909-00.BIN)')
    t = time.time()
    g, gout = run_gridos()
    print('==== Grid-OS ====\n' + gout.strip() + '\n')
    d, dout = run_msdos()
    print('==== GRiD MS-DOS 3.30 ====\n' + dout.strip() + '\n')
    rg, rd = results(g), results(d)
    print('%-32s %10s %10s %8s   %s' % ('emulator timing (s)', 'Grid-OS', 'MS-DOS', 'ratio', 'BIOS disk calls / sectors  Grid-OS | MS-DOS'))
    for n, a, b in zip(NAMES, rg, rd):
        if a and b:
            print('%-32s %10.3f %10.3f %7.2fx   %5d / %5d  | %5d / %5d' % (n, a[0], b[0], a[0] / b[0] if b[0] else 0, a[1], a[2], b[1], b[2]))
        else:
            print('%-32s %10s %10s' % (n, a and '%.3f' % a[0], b and '%.3f' % b[0]))
    print('(wall %.0f s)' % (time.time() - t))
