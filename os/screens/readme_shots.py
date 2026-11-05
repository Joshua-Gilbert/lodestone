"""Screenshots for the README (screens/readme/), from the emulator: a
1.44 MB floppy like the real one, the 1520's 1408 KB of EMS.

    python3 screens/readme_shots.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, os.path.join(GOS, 'tests'))
import ktest, mkimg
from test_apps import CODE, K_CODE_ENTER, click
OUT = os.path.join(HERE, 'readme')
TMP = os.path.join(__import__('tempfile').gettempdir(), 'lodestone-readme')
os.makedirs(OUT, exist_ok=True); os.makedirs(TMP, exist_ok=True)

def dummy(name, size):
    p = os.path.join(TMP, name); open(p, 'wb').write(bytes((i * 7) & 255 for i in range(size))); return p

files = [os.path.join(GOS, 'src', f) for f in ('LODE.SYS', 'LCMD.COM', 'DEFRAG.COM', 'HEADCLN.COM', 'LODE.TXT', 'CALC.COM')]
files += [os.path.join(GOS, 'apps', f) for f in ('SYSTEM.RUN', 'WRITE.RUN', 'CALC.RUN', 'TASKS.RUN')]
files += [os.path.join(GOS, 'fonts', 'GRIDFONT.FNT'), os.path.join(GOS, 'fonts', 'TERMINUS.FNT'),os.path.join(GOS, 'claude', 'CLAUDE.COM'),
          os.path.join(GOS, 'bench', 'BENCH.COM'), os.path.join(GOS, 'tests', 'EMSTEST.COM'),
          os.path.join(GOS, 'tests', 'TESTDOS.COM'), dummy('TM5000G.EXE', 296634),
          'DOCS\\', 'DOCS\\NOTES.TXT=' + os.path.join(GOS, 'src', 'LODE.TXT'), 'WORK\\']
img = mkimg.build(os.path.join(TMP, 'readme.img'), files)
k = ktest.KPC(img, ems_pages=88, disk_model='real'); k.pc.mouse = True; k.start(20)
dx, dy = 560 - k.u16('mx'), 240 - k.u16('my')         # the pointer where it hides nothing
while dx or dy:
    sx, sy = max(-100, min(100, dx)), max(-100, min(100, dy))
    k.pc.mouse_move(sx & 0xFF, sy & 0xFF); k.pc.run_for(0.05); dx -= sx; dy -= sy
k.settle()
shot = lambda n: k.shot(os.path.join(OUT, n + '.png'))
k.select('LODE.TXT'); shot('executive')
# the calculator over the Executive (CODE-K), and CALC at the prompt
k.key(CODE['K']); k.key('9.81*2.5^2/2', ktest.ENTER); shot('calculator'); k.key(ktest.ESC)
k.key(CODE['P'])
for c in ('cls', 'calc 4*4', 'calc /d sin(30)', 'calc 2^0.5', 'calc 1/0', 'set n=41', 'calc n=n+1', 'set', 'calc /?'):
    k.key(c, ktest.ENTER)
shot('calc_prompt'); k.key('exit', ktest.ENTER); k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
k.key(CODE['C']); k.key('*.txt', ktest.ENTER, ktest.RIGHT); shot('copy_wildcards'); k.key(ktest.ESC)
k.key(CODE['U']); shot('system_memory'); k.key(ktest.ESC); k.settle()
k.select('LODE.TXT'); k.key(ktest.ENTER); k.settle(); k.key(ktest.DOWN, ktest.DOWN); shot('write'); k.key(ktest.ESC, ktest.ENTER); k.settle()
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
# The start-up picture (LODE.PIC), once drawn; then System's Display,
# where Space turns it off
img = mkimg.build(os.path.join(TMP, 'splash.img'), files + [os.path.join(GOS, 'src', 'LODE.PIC')])
k = ktest.KPC(img, ems_pages=88); k.pc.mouse = True
k.pc.boot(0)
k.pc.run_until(lambda: any(m[0] == 0xF2 for m in k.pc.marks), 20)     # (its "drawn" mark)
shot('splash')
k.settle(10)
k.key(CODE['U'])
for _ in range(5): k.key(ktest.DOWN, settle=False)
k.settle(); shot('system_display'); k.key(ktest.ESC)
# Multitasking (MULTITASK=1): LCMD (CODE-P) and BENCH (Return on it) as
# tasks, each in a terminal window made smaller (CODE-F8) and placed
# (CODE-F7) over the Executive's list, which stays usable beside them
ini = os.path.join(TMP, 'LODE.INI'); open(ini, 'wb').write(b'MULTITASK=1\r\n')
img = mkimg.build(os.path.join(TMP, 'mt.img'), files + [os.path.join(GOS, 'src', 'LODEMT.SYS'),
                  os.path.join(GOS, 'apps', 'TERM.RUN'), os.path.join(GOS, 'fonts', 'TERM.FNT'), 'LODE.INI=' + ini])
k = ktest.KPC(img, ems_pages=88, irq_exact=True); k.pc.mouse = True; k.start(20)
def keys(*ks, t=0.3):                   # (no settle: with tasks running the machine never idles)
    for x in ks: k.key(x, settle=False); k.run_for(t)
def arrows(cols, rows):
    for _ in range(abs(cols)): keys(ktest.LEFT if cols < 0 else ktest.RIGHT, t=0.05)
    for _ in range(abs(rows)): keys(ktest.UP if rows < 0 else ktest.DOWN, t=0.05)
    keys(ktest.ENTER, t=1.0)
keys(CODE['P'], t=3.0); keys('dir /w', ktest.ENTER, t=2.0)
keys(0x6F00); arrows(-40, -11)          # CODE-F8: 40 columns, 8 rows
click(k, 600, 300); k.run_for(0.5)      # the Executive in front again
i, s = k.exec_list().index('BENCH.COM'), k.u16('sel')
keys(*([ktest.DOWN] * (i - s) + [ktest.UP] * (s - i)), t=0.1)
keys(ktest.ENTER, t=2.0)
keys(0x6F00); arrows(-29, -11)          # 51 columns, 8 rows ...
keys(0x6E00); arrows(28, -4)            # ... at the right, level with LCMD's
k.run_for(6.0); shot('multitasking')
keys(CODE['T'], t=1.0); shot('tasks')    # CODE-T: the tasks, over them
print('\n'.join(sorted(os.listdir(OUT))))
