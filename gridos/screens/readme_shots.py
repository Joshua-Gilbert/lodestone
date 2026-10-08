"""Screenshots for the README (screens/readme/), from the emulator: a
1.44 MB floppy like the real one, the 1520's 1408 KB of EMS.

    python3 screens/readme_shots.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, os.path.join(GOS, 'tests'))
import ktest, mkimg
from test_apps import CODE, K_CODE_ENTER
OUT = os.path.join(HERE, 'readme')
TMP = os.path.join(__import__('tempfile').gettempdir(), 'gridos-readme')
os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)

def dummy(name, size):
    p = os.path.join(TMP, name); open(p, 'wb').write(bytes((i * 7) & 255 for i in range(size))); return p

files = [os.path.join(GOS, 'src', f) for f in ('GRIDOS.SYS', 'GRIDCMD.COM', 'DEFRAG.COM', 'HEADCLN.COM', 'GRIDOS.TXT')]
files += [os.path.join(GOS, 'apps', f) for f in ('SYSTEM.RUN', 'WRITE.RUN')]
files += [os.path.join(GOS, 'fonts', 'TERMINUS.FNT'), os.path.join(GOS, 'claude', 'CLAUDE.COM'),
          os.path.join(GOS, 'bench', 'BENCH.COM'), os.path.join(GOS, 'tests', 'EMSTEST.COM'),
          os.path.join(GOS, 'tests', 'TESTDOS.COM'), dummy('TM5000G.EXE', 296634),
          'DOCS\\', 'DOCS\\NOTES.TXT=' + os.path.join(GOS, 'src', 'GRIDOS.TXT'), 'WORK\\']
img = mkimg.build(os.path.join(TMP, 'readme.img'), files)
k = ktest.KPC(img, ems_pages=88, disk_model='real'); k.pc.mouse = True; k.start(20)
dx, dy = 560 - k.u16('mx'), 240 - k.u16('my')         # the pointer where it hides nothing
while dx or dy:
    sx, sy = max(-100, min(100, dx)), max(-100, min(100, dy))
    k.pc.mouse_move(sx & 0xFF, sy & 0xFF); k.pc.run_for(0.05); dx -= sx; dy -= sy
k.settle()
shot = lambda n: k.shot(os.path.join(OUT, n + '.png'))
k.select('GRIDOS.TXT'); shot('executive')
k.key(CODE['C']); k.key('*.txt', ktest.ENTER, ktest.RIGHT); shot('copy_wildcards'); k.key(ktest.ESC)
k.key(CODE['U']); shot('system_memory'); k.key(ktest.ESC); k.settle()
k.select('GRIDOS.TXT'); k.key(ktest.ENTER); k.settle(); k.key(ktest.DOWN, ktest.DOWN); shot('write'); k.key(ktest.ESC, ktest.ENTER); k.settle()
k.select('BENCH.COM'); k.pc.tty.clear(); k.key(ktest.ENTER, settle=False)
k.pc.run_until(lambda: k.pc.mode() != 0x40, 10)
k.pc.run_until(lambda: 'Press any key' in ''.join(k.pc.tty), 900)
shot('bench')

# System's Disks with the internal hard disk as C:: the CP30104H's own
# partition table and boot sector, a few files on it
import struct, pcemu, fat16img as F
rom = os.path.join(GOS, '..', 'rom', 'hd_cp30104h')
sect0 = open(os.path.join(rom, 'HDSECT0.BIN'), 'rb').read()
plba, n = struct.unpack_from('<II', sect0, 446 + 8)
f = F.Fat(n, 4, plba, True)
f.finish(f.tree([('COMMAND.COM', 0x20, b'C' * 47845), ('TM5000', 0, [('TM5000G.EXE', 0x20, b'T' * 296634)])]))
f.img[0:512] = open(os.path.join(rom, 'HDBOOT.BIN'), 'rb').read()
d = bytearray(762 * 8 * 39 * 512); d[0:512] = sect0; d[plba * 512:(plba + n) * 512] = f.img
ata = pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=762, heads=8, spt=39, disk=d)
k = ktest.KPC(img, ems_pages=88, ata=ata); k.start(20)
k.key(CODE['U']); k.key(ktest.DOWN); shot('system_disks'); k.key(ktest.ESC)
print('\n'.join(sorted(os.listdir(OUT))))
