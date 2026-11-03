"""Lodestone 0.4.3: the start-up picture, in pcemu.  LODE.PIC (SPLASH.ASM)
draws it; the kernel's bootstrap (KSPLASH.INC) loads it, calls it and
drops it.

    python3 tests/test_splash.py [t_paths t_timing t_key t_typeahead t_ini t_pic t_system t_memory]

The picture against splash/mksplash.py's drawing of it, bit for bit, in
every way the kernel starts (floppies only, EMS, the hard disk as C:,
both, the build without a disk cache); how long it takes to draw and how
long it stays; a key ends it and is taken, but keys typed before it
don't; SPLASH= in LODE.INI, in any case, among other lines and past its
first KB; M:'s MDISK= still read after it; no LODE.PIC, or a file of that
name that isn't one or is cut short; System's switch (Display, Space),
which reads LODE.INI only when needed and keeps SPLASH=0 when other
settings are saved; and that DOS programs get exactly the memory they
had under 0.4.2, with or without the picture.

LODE.PIC marks its start, the end of the drawing and its end with
INT 1Ah, BX = BEF0h / BEF2h / BEF1h; pcemu keeps those as marks.
"""
import os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path[:0] = [GOS, HERE, os.path.join(GOS, 'splash')]
import ktest, mkimg, pcemu, fat16img as F
import mksplash
import test_apps as A
from test_apps import check, results, has, screen, disk_file, CODE

OUT = A.OUT
PIC = os.path.join(GOS, 'src', 'LODE.PIC')
ON, DRAWN, OFF = 0xF0, 0xF2, 0xF1
SPACE = 0x3920


def marks(k):
    return {b: us for b, us, *_ in k.pc.marks if b in (ON, DRAWN, OFF)}

def boot_to_drawn(k):
    k.pc.boot(0)
    return k.pc.run_until(lambda: DRAWN in marks(k), 20)

def screen_bits(k):
    vram = k.pc.rd(0xB800, 0, 0x8000)
    return [[(vram[(y & 3) * 0x2000 + (y >> 2) * 80 + (x >> 3)] >> (7 - (x & 7))) & 1 for x in range(640)] for y in range(400)]

REF = None
def reference():
    global REF
    if REF is None:
        rock, nails = mksplash.read_trace()
        REF = mksplash.render(*mksplash.build(rock, nails))
    return REF

def differing(k):
    ref, got = reference(), screen_bits(k)
    return sum(a != b for ra, rb in zip(ref, got) for a, b in zip(ra, rb))

def ini_file(text):
    p = os.path.join(OUT, 'LODE.INI'); open(p, 'wb').write(text); return p

def hd():
    """a small FAT16 drive C: with one file"""
    cyl, heads, spt, plba = 70, 4, 17, 17
    f = F.Fat(cyl * heads * spt - plba, 1, plba, True, label='GRIDHD')
    f.finish(f.tree([('README.TXT', 0x20, b'Hello from drive C:\r\n')]))
    return pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=cyl, heads=heads, spt=spt,
                     disk=F.disk(cyl, heads, spt, plba, f))


def t_paths():
    print('== the picture, bit for bit, every way the kernel starts')
    img = A.image('sp.img', PIC, A.LCMD, A.SYSTEM)
    for tag, kw, image in (('floppies only', {}, img), ('EMS', {'ems_pages': 88}, img),
                           ('the hard disk as C:', {'ata': hd()}, img), ('C: and EMS', {'ata': hd(), 'ems_pages': 88}, img)):
        k = ktest.KPC(image, **kw)
        ok = boot_to_drawn(k)
        d = differing(k) if ok else -1
        m = marks(k)
        check('%s: the picture is drawn, every pixel as mksplash.py draws it' % tag, ok and d == 0 and k.pc.mode() == 0x40,
              (ok, d, '%02X' % k.pc.mode()))
        k.settle(10)
        check('%s: then the Executive, as always' % tag, OFF in marks(k)
              and k.pc.mode() == 0x40 and 'LCMD.COM' in k.exec_list() and has(k, 'Select a file'), (marks(k), screen(k)))
        if 'ems_pages' in kw:
            check('%s: M:\'s start-up ran after it (256 KB)' % tag, A.md_pages(k) == 16, A.md_pages(k))
        if 'ata' in kw:
            k.key(CODE['U']); k.key(ktest.DOWN)
            check('%s: C: is there (System, Disks)' % tag, has(k, 'Drive C:'), screen(k))
    # the build without the disk cache: no KMDISK.INC, so the jump at
    # KSEG:0000 is the picture's own
    notc = os.path.join(OUT, 'LODE_NOTC.SYS')
    subprocess.run(['nasm', '-f', 'bin', '-dNOTC', '-i', os.path.join(GOS, 'src') + '/', '-o', notc,
                    os.path.join(GOS, 'src', 'LODE.ASM')], check=True)
    img_notc = mkimg.build(os.path.join(OUT, 'sp_notc.img'), ['LODE.SYS=' + notc, PIC, A.LCMD])
    for tag, kw in (('no disk cache (-dNOTC)', {}), ('no disk cache, EMS', {'ems_pages': 88})):
        k = ktest.KPC(img_notc, **kw)
        ok = boot_to_drawn(k)
        d = differing(k) if ok else -1
        k.settle(10)
        check('%s: the picture, bit for bit, then the Executive' % tag, ok and d == 0 and OFF in marks(k)
              and k.pc.mode() == 0x40 and has(k, 'Select a file') and has(k, 'LCMD'), (ok, d, marks(k), screen(k)))


def t_timing():
    print('== how long')
    k = ktest.KPC(A.image('sp.img', PIC, A.LCMD))
    boot_to_drawn(k)
    k.settle(10)
    m = marks(k)
    draw, hold = (m[DRAWN] - m[ON]) / 1e6, (m[OFF] - m[DRAWN]) / 1e6
    check('drawn in %.0f ms on pcemu\'s 286 (no more than 0.3 s)' % (draw * 1000), draw < 0.3, draw)
    check('it stays 2 seconds (%.2f s: 36 ticks, to a tick)' % hold, 1.9 < hold < 2.1, hold)


def t_key():
    print('== a key ends it, and is taken')
    k = ktest.KPC(A.image('sp.img', PIC, A.LCMD, A.SYSTEM))
    boot_to_drawn(k)
    k.pc.run_for(0.3)
    t = k.pc.us
    k.pc.keys.append(0x1C0D)            # Return: in the Executive it would run LCMD.COM
    k.settle(10)
    m = marks(k)
    check('Return ends it at once', OFF in m and (m[OFF] - t) / 1e6 < 0.12, (m, t))
    check('... and the Executive never sees it: its list, nothing run', k.pc.mode() == 0x40 and has(k, 'Select a file')
          and 'LCMD.COM' in k.exec_list() and not k.pc.keys, screen(k))


def t_typeahead():
    print('== keys typed before it (spare taps at the BIOS\'s prompt)')
    k = ktest.KPC(A.image('sp.img', PIC, A.LCMD, A.SYSTEM))
    k.pc.keys.extend([ord('s')] * 3)     # (in the Executive: find SYSTEM.RUN)
    boot_to_drawn(k)
    k.settle(10)
    m = marks(k)
    hold = (m[OFF] - m[DRAWN]) / 1e6 if OFF in m and DRAWN in m else 0
    check('they don\'t end it: it stays its 2 seconds (%.2f s)' % hold, 1.9 < hold < 2.1, m)
    check('... and the Executive doesn\'t get them: LCMD is still the title, not SYSTEM', not k.pc.keys
          and re.search(r'Title\s+LCMD', screen(k)), screen(k))


def t_ini():
    print('== SPLASH= in LODE.INI')
    off = [b'SPLASH=0\r\n', b'splash=0\r\n', b'SPLASH=No\r\n', b'Splash=off\r\n', b'SPLASH=OFF', b'KEYS=1\r\nSPLASH=0\r\nLAST=2\r\n']
    on = [b'SPLASH=1\r\n', b'SPLASH=On\r\n', b'SPLASH=yes\r\n', b'XSPLASH=0\r\n', b'KEYS=1\r\nFONT=TERMINUS.FNT\r\n',
          b'NOTES SPLASH=0\r\n']
    for text, want in [(t, False) for t in off] + [(t, True) for t in on]:
        k = ktest.KPC(A.image('sp_ini.img', PIC, A.LCMD, ini_file(text)))
        k.start(10)
        shown = ON in marks(k)
        check('%-36r: %s' % (text, 'the picture' if want else 'no picture, straight to the Executive'),
              shown == want and 'LCMD.COM' in k.exec_list(), (marks(k), screen(k)))
    pad = b''.join(b'NOTE%02d=%s\r\n' % (i, b'x' * 40) for i in range(26))       # 1,274 bytes of other lines
    k = ktest.KPC(A.image('sp_ini.img', PIC, A.LCMD, ini_file(pad + b'SPLASH=0\r\n'))); k.start(10)
    check('SPLASH=0 after %d bytes of other lines: no picture (the kernel reads up to 4 KB)' % len(pad), ON not in marks(k), marks(k))
    k = ktest.KPC(A.image('sp_md.img', PIC, A.LCMD, ini_file(pad + b'MDISK=512\r\n')), ems_pages=88); k.start(10)
    check('MDISK=512 after %d bytes of other lines: M: is 512 KB (md_boot reads up to 4 KB too)' % len(pad), A.md_pages(k) == 32, A.md_pages(k))
    k = ktest.KPC(A.image('sp_ini.img', PIC, A.LCMD, ini_file(b'SPLASH=0\r\n')))
    t0 = k.pc.us; k.start(10)
    check('SPLASH=0: started in %.2f s, as before the picture' % ((k.pc.us - t0) / 1e6), (k.pc.us - t0) / 1e6 < 1.2)
    # M: reads LODE.INI after the picture: its line still counts
    for text in (b'MDISK=512\r\nSPLASH=0\r\n', b'MDISK=512\r\n'):
        k = ktest.KPC(A.image('sp_md.img', PIC, A.LCMD, ini_file(text)), ems_pages=88)
        k.start(10)
        check('%r: M: is 512 KB (MDISK= read after the picture)' % text, A.md_pages(k) == 32, A.md_pages(k))


def t_pic():
    print('== LODE.PIC: none, or not one')
    for tag, files in (('no LODE.PIC on the disk', []),
                       ('LODE.PIC that is a text file', ['LODE.PIC=' + ini_file(b'Not a picture at all, just text.\r\n' * 4)]),
                       ('LODE.PIC too short', ['LODE.PIC=' + ini_file(b'\xEB\x0ALODEPIC\x01')]),
                       ('LODE.PIC cut short (its first 2 KB)', ['LODE.PIC=' + ini_file(open(PIC, 'rb').read()[:2048])]),
                       ('LODE.PIC with more after it', ['LODE.PIC=' + ini_file(open(PIC, 'rb').read() + b'\0' * 512)])):
        k = ktest.KPC(A.image('sp_pic.img', A.LCMD, *files))
        t0 = k.pc.us; k.start(10)
        check('%s: no picture, the Executive as before (%.2f s)' % (tag, (k.pc.us - t0) / 1e6), ON not in marks(k)
              and k.pc.mode() == 0x40 and 'LCMD.COM' in k.exec_list() and not k.crashed and (k.pc.us - t0) / 1e6 < 1.2,
              (marks(k), screen(k)))
    for tag, kw in (('EMS', {'ems_pages': 88}), ('C:', {'ata': hd()})):
        k = ktest.KPC(A.image('sp_pic.img', A.LCMD), **kw); k.start(10)
        check('no LODE.PIC, %s: the Executive as before' % tag, ON not in marks(k) and 'LCMD.COM' in k.exec_list(), marks(k))


def t_system():
    print('== System: Display, Space')
    k = ktest.KPC(A.image('sp_sys.img', PIC, A.SYSTEM, A.LCMD)); k.pc.mouse = True; k.start()
    A.to_display(k)
    check('Display: "Start-up picture  yes"', re.search(r'Start-up picture\s+yes', screen(k))
          and 'SPACE: picture or not' in ' '.join(k.band()), (screen(k), k.band()))
    k.key(SPACE)
    check('Space: "no", and LODE.INI says SPLASH=0', re.search(r'Start-up picture\s+no', screen(k))
          and disk_file(k, 'LODE.INI') == b'SPLASH=0\r\n', (screen(k), disk_file(k, 'LODE.INI')))
    k.key(ktest.ESC)
    k = A.reboot(k, 'sp_sys2.img')
    check('after a restart: no picture', ON not in marks(k) and 'SYSTEM.RUN' in k.exec_list(), marks(k))
    A.to_display(k)
    check('... and System says "no"', re.search(r'Start-up picture\s+no', screen(k)), screen(k))
    k.key(SPACE)
    check('Space again: "yes", and LODE.INI goes (nothing else in it)', re.search(r'Start-up picture\s+yes', screen(k))
          and disk_file(k, 'LODE.INI') is None, (screen(k), disk_file(k, 'LODE.INI')))
    k.key(ktest.ESC)
    k = A.reboot(k, 'sp_sys3.img')
    check('after a restart: the picture again', ON in marks(k) and OFF in marks(k), marks(k))
    # other lines stay, and the font and saver lines live with it
    k = ktest.KPC(A.image('sp_sys4.img', PIC, A.SYSTEM, A.TERMFNT, ini_file(b'KEYS=1\r\nsplash=no\r\nSAVER=10\r\n')))
    k.pc.mouse = True; k.start()
    check('"splash=no" among other lines: no picture', ON not in marks(k), marks(k))
    A.to_display(k)
    check('... System says "no"', re.search(r'Start-up picture\s+no', screen(k)), screen(k))
    k.key(ktest.ENTER)                  # the next font: TERMINUS.FNT
    check('Return (the font): SPLASH=0 kept with it, the other lines too',
          disk_file(k, 'LODE.INI') == b'KEYS=1\r\nFONT=TERMINUS.FNT\r\nSAVER=10\r\nSPLASH=0\r\n', disk_file(k, 'LODE.INI'))
    k.key(SPACE)
    check('Space: the picture on; only its line goes',
          disk_file(k, 'LODE.INI') == b'KEYS=1\r\nFONT=TERMINUS.FNT\r\nSAVER=10\r\n', disk_file(k, 'LODE.INI'))
    k.key(ktest.ESC)
    # System doesn't read LODE.INI to start (a disk read): only for Display
    k = ktest.KPC(A.image('sp_sys5.img', PIC, A.SYSTEM, ini_file(b'SPLASH=0\r\n'))); k.pc.mouse = True; k.start()
    opened = []
    a21 = k.Y['int21']
    def h(pc):
        if pc.r('cs') == 0x60 and pc.r('ip') == a21 and pc.r('ah') == 0x3D:
            opened.append(pc.asciiz(pc.r('ds'), pc.r('dx')).decode('latin-1').upper())
    k.hooks.append(h)
    k.key(CODE['U'])
    check('System starts without reading LODE.INI', not any('LODE.INI' in o for o in opened) and has(k, 'Memory'), opened)
    for _ in range(6): k.key(ktest.DOWN, settle=False)
    k.settle()
    k.key(ktest.ENTER)
    check('... Screen saver, Return: SAVER=10 saved, and SPLASH=0 kept (read as it saves)',
          disk_file(k, 'LODE.INI') == b'SAVER=10\r\nSPLASH=0\r\n', disk_file(k, 'LODE.INI'))
    k.key(ktest.UP)
    check('... Display: "no", LODE.INI read once there', re.search(r'Start-up picture\s+no', screen(k)), (screen(k), opened))
    # a write-protected disk: Space can't save, so nothing changes
    k.pc.drives[0].wp = True
    k.key(SPACE)
    check('write-protected: Space says LODE.INI can\'t be saved', has(k, "LODE.INI can't be saved"), (screen(k), k.band()))
    k.key(ktest.ENTER); k.settle()
    k.pc.drives[0].wp = False
    check('... and it still says "no", LODE.INI as it was', re.search(r'Start-up picture\s+no', screen(k))
          and disk_file(k, 'LODE.INI') == b'SAVER=10\r\nSPLASH=0\r\n', (screen(k), disk_file(k, 'LODE.INI')))
    k.key(ktest.ESC)
    # the help says so
    A.to_display(k)
    k.key(A.K_CODE_HELP)
    check('CODE-? lists Space (the picture, as the band says)', has(k, 'Space                        on or off (see the band)'), screen(k))


# What a DOS program gets in 0.4.4 (MEMSZ, from the Executive): 0.2 KB less
# than 0.4.2 and 0.4.3, for the coprocessor lamp and the calculator's key
# (test_apps.t_memory).  0.4.2's LODE.SYS can't be run here any more: the
# Executive's layout moved, and ktest drives it by the new LODE.MAP.
MEM_044 = {0: '564.9', 88: '581.0'}   # (0.6: 0.1 KB less, the PATH search and two settings files;
                                      #  then 0.5 KB less, windows that move and close, UI API 6; printer drivers 0.2 KB;
                                      #  then 0.9 KB more, the 2026-10-20 audit's kernel batch; 1.3 / 1.2 KB more, its UI batch;
                                      #  2.6 / 2.7 KB more, its medium-risk kernel and UI batches: start-up code run from buffers, no row table;
                                      #  then 0.1 KB less, 32 bytes, right clicks: UI API 7;
                                      #  0.1 KB less, names and devices answered as MS-DOS 3.30;
                                      #  0.1 KB less (no EMS), a device behind a directory: DIR\NUL;
                                      #  0.1 KB less, the path calls' error codes as MS-DOS 3.30's: X17, X20;
                                      #  0.2 KB less, the Executive's part of multitasking: Return
                                      #  as a task, CODE-T, the UI block moved once no task is left, 182 bytes;
                                      #  0.3 KB less, GPIB's SRQ on IRQ 5;
                                      #  0.1 KB less, INT 24h for a drive with no disk;
                                      #  0.5 KB less, pop-up menus and drags: UI API 8;
                                      #  0.3 KB less, the clipboard: UI_CLIP;
                                      #  0.1 KB more, 160 bytes, the 2026-10-26 audit's kernel batch;
                                      #  0.1 KB more, 48 bytes, its UI batch: R39-R41;
                                      #  32 bytes, the Executive opening .BMP files with Paint;
                                      #  0.1 KB more, 64 bytes, its ROM 1 batch: XI-13, G1-5 and UI-7)

def t_memory():
    print('== what DOS programs get: the same with the picture as without it')
    got = {}
    for tag, more in (('now', [PIC]), ('now, no LODE.PIC', [])):
        for ems in (0, 88):
            img = mkimg.build(os.path.join(OUT, 'sp_mem.img'), [os.path.join(GOS, 'src', 'LODE.SYS'), A.MEMSZ, A.LCMD] + more)
            k = ktest.KPC(img, ems_pages=ems); k.start(10)
            out = k.run_file('MEMSZ.COM', 20)
            m = re.search(r'([\d.]+) KB for programs', out)
            got[tag, ems] = m and m.group(1)
    for ems in (0, 88):
        check('%s: a DOS program gets %s KB after the picture, %s KB without LODE.PIC (UI API 6: %s KB)'
              % ('EMS' if ems else 'no EMS', got['now', ems], got['now, no LODE.PIC', ems], MEM_044[ems]),
              got['now', ems] and got['now', ems] == got['now, no LODE.PIC', ems] == MEM_044[ems], got)


if __name__ == '__main__':
    t0 = time.time()
    A.build()
    subprocess.run(['nasm', '-f', 'bin', '-i', os.path.join(GOS, 'src') + '/', '-o', PIC, os.path.join(GOS, 'src', 'SPLASH.ASM')], check=True)
    only = [a for a in sys.argv[1:] if a.startswith('t_')]
    for t in (t_paths, t_timing, t_key, t_typeahead, t_ini, t_pic, t_system, t_memory):
        if not only or t.__name__ in only: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
