"""FORMAT.COM in the emulator, from the command prompt: a blank 1.44 MB disk
in B: formatted (every track once, with the right sector IDs, a clean FAT12
volume, the Lodestone boot sector, the label), 720 KB in the same drive,
bad sectors (their clusters marked bad; in track 0 the disk refused),
a write-protected disk, an empty drive, /Q (the disk's old files gone, its
bad clusters kept, no track formatted), /S (the system copied; the disk
boots), drive A: formatted with /S from the disk Lodestone started from,
answers from a file, Esc, and the switches it refuses.

    python3 tests/test_format.py
"""
import os, struct, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, pcemu, fatcheck, fat16img as F

OUT = tempfile.mkdtemp()
SRC = os.path.join(GOS, 'src')
SYSF = ('LODE.SYS', 'LODEMT.SYS', 'LODE.PIC', 'LCMD.COM')
BOOT = open(os.path.join(SRC, 'BOOT.BIN'), 'rb').read()
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)) if detail and not cond else ''))

def blank(name, size=1474560):
    """A disk never formatted: no sector can be read."""
    p = os.path.join(OUT, name)
    open(p, 'wb').write(bytes(size))
    return p

def boot(b=None, files=SYSF + ('FORMAT.COM',), extra=(), ata=None):
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(SRC, f) for f in files] + list(extra))
    k = ktest.KPC(img, b, ata=ata)
    if b and open(b, 'rb').read(512) == bytes(512):
        k.pc.drives[1].noid = set(range(len(k.pc.drives[1].img) // 512))
    k.start()
    k.code_p()
    return k

def scr(k): return k.pc.text_screen()

def cmd(k, line):
    k.key('cls'); k.key(ktest.ENTER)
    k.key(line); k.key(ktest.ENTER, settle=False)

def wait(k, text, sim_s):
    k.pc.run_until(lambda: text in scr(k), sim_s)
    return text in scr(k)

def fmt(k, line, more='n'):
    """FORMAT at the prompt, Enter for the disk, `more` to Format another;
    the screen after (with FORMAT-OK or FORMAT-FAILED: its exit code)."""
    cmd(k, line + ' && echo FORMAT-OK || echo FORMAT-FAILED')
    if wait(k, 'strike ENTER', 20):
        k.key(ktest.ENTER, settle=False)
        wait(k, 'another (Y/N)?', 400)
        k.key(more)
    k.settle(20)
    return scr(k)

def said(o, line):
    """line on a line of its own (not in the command line that ECHOs it)"""
    return any(l.strip() == line for l in o.split('\n'))

def shell(k, line):
    cmd(k, line); k.settle(20)
    return scr(k)

def bpb(img):
    return struct.unpack_from('<HBHBHHBHHH', img, 11)

def fat12(img, n, spf=9):
    v = struct.unpack_from('<H', img, 512 + n * 3 // 2)[0]
    return v >> 4 if n & 1 else v & 0xFFF

def mdir(img):
    p = os.path.join(OUT, 'm.img'); open(p, 'wb').write(img)
    return subprocess.run(['mdir', '-a', '-i', p, '::'], capture_output=True, text=True).stdout

def t_full():
    k = boot(blank('b.img'))
    o = fmt(k, 'format b: /v:test')
    d = k.pc.drives[1]; img = bytes(d.img)
    check('FORMAT B: /V:TEST: says what it formats, completes, the figures, exit code 0',
          all(x in o for x in ('Formatting 1.44M', 'Format complete', '   1457664 bytes total disk space',
                               '   1457664 bytes available on disk', 'Volume Serial Number is', 'FORMAT-OK')), o)
    check('every track formatted once, in order, with its sector IDs (all readable after)',
          d.formats == [(c, h) for c in range(80) for h in (0, 1)] and not d.noid, (len(d.formats), len(d.noid)))
    check('a 1.44 MB FAT12 BPB, both FATs the same and empty, CHKDSK-clean',
          bpb(img) == (512, 1, 1, 2, 224, 2880, 0xF0, 9, 18, 2) and fatcheck.check(img) == ([], {})
          and img[512:515] == b'\xF0\xFF\xFF' and not any(img[515:512 * 10]), (bpb(img), fatcheck.check(img)))
    check('the Lodestone boot sector, with an extended BPB: serial number, label',
          img[0x3E:510] == BOOT[0x3E:510] and img[510:512] == b'\x55\xAA' and img[0x26] == 0x29
          and img[0x2B:0x36] == b'TEST       ' and img[0x36:0x3E] == b'FAT12   ', img[0:0x40])
    root = img[19 * 512:]
    check('the label in the root (attribute 08h), nothing else there',
          root[0:11] == b'TEST       ' and root[11] == 8 and root[32] == 0, root[:64])
    o = shell(k, 'dir b:')
    check('the kernel sees the new disk: DIR B: gives its label, no files',
          'Volume in drive B is TEST' in o and 'File not found' in o, o)
    shell(k, 'echo hello > b:\\x.txt')
    img = bytes(k.pc.drives[1].img)
    check('... and writes to it', 'X        TXT' in mdir(img) and fatcheck.check(img)[0] == [], mdir(img))
    # formatted again: the kernel must not trust what it remembers of the old disk
    shell(k, 'md b:\\sub'); shell(k, 'cd b:\\sub'); shell(k, 'echo x > b:\\sub\\y.txt')
    o = fmt(k, 'format b:')
    o2 = shell(k, 'dir b:')
    o3 = shell(k, 'cd b:')
    check('formatted again over files the kernel has cached, and its current directory there: gone',
          said(o, 'FORMAT-OK') and 'X        TXT' not in o2 and 'SUB' not in o2 and 'File not found' in o2
          and 'B:\\' in o3 and 'SUB' not in o3, (o2, o3))
    check('... no label this time (none asked for): NO NAME in the BPB',
          bytes(k.pc.drives[1].img)[0x2B:0x36] == b'NO NAME    ' and 'has no label' in o2, o2)

def t_720():
    k = boot(blank('b.img'))
    o = fmt(k, 'format b: /f:720')
    d = k.pc.drives[1]; img = bytes(d.img)
    check('/F:720 in the 1.44 MB drive: 720 KB (80 cylinders of 9 sectors), its BPB',
          'Formatting 720K' in o and '    730112 bytes total disk space' in o and said(o, 'FORMAT-OK')
          and len(img) == 737280 and bpb(img) == (512, 2, 1, 2, 112, 1440, 0xF9, 3, 9, 2)
          and fatcheck.check(img)[0] == [], (o, bpb(img)))
    shell(k, 'copy a:\\lcmd.com b:')
    img = bytes(k.pc.drives[1].img)
    p, files = fatcheck.check(img)
    check('... the kernel mounts it and writes to it', p == [] and 'LCMD     COM' in mdir(img), (p, mdir(img)))
    o = fmt(k, 'format b: /n:18 /t:80')
    check('/N:18 /T:80: back to 1.44 MB', 'Formatting 1.44M' in o and len(k.pc.drives[1].img) == 1474560, o)

def t_525():
    k = boot(blank('b.img', 1228800))
    k.pc.drives[1].kind = 2                             # a 5.25-inch 1.2 MB drive
    o = fmt(k, 'format b:')
    img = bytes(k.pc.drives[1].img)
    check('a 1.2 MB drive: 1.2 MB by default, its BPB', 'Formatting 1.2M' in o and said(o, 'FORMAT-OK')
          and '   1213952 bytes total disk space' in o and bpb(img) == (512, 1, 1, 2, 224, 2400, 0xF9, 7, 15, 2)
          and fatcheck.check(img)[0] == [], (o, bpb(img)))
    o = fmt(k, 'format b: /4')
    shell(k, 'copy a:\\lcmd.com b:')
    img = bytes(k.pc.drives[1].img)
    check('/4: 360 KB (40 cylinders of 9 sectors) in it, and the kernel uses it',
          'Formatting 360K' in o and said(o, 'FORMAT-OK') and '    362496 bytes total disk space' in o
          and len(img) == 368640 and bpb(img) == (512, 2, 1, 2, 112, 720, 0xFD, 2, 9, 2)
          and fatcheck.check(img)[0] == [] and 'LCMD     COM' in mdir(img), (o, bpb(img)))
    o = fmt(k, 'format b: /f:1.44')
    check('/F:1.44 in it: "not supported by drive"', 'not supported by drive' in o and said(o, 'FORMAT-FAILED'), o)

def t_bad():
    k = boot(blank('b.img'))
    d = k.pc.drives[1]
    d.bad = {1000, 1001, 2879}                          # two clusters (1.44 MB: one sector each) and the last
    o = fmt(k, 'format b:')
    img = bytes(d.img)
    cl = [n - 33 + 2 for n in sorted(d.bad)]
    check('bad sectors: their clusters marked FF7h, the rest free, "bytes in bad sectors"',
          all(fat12(img, c) == 0xFF7 for c in cl) and sum(fat12(img, c) == 0xFF7 for c in range(2, 2849)) == 3
          and '      1536 bytes in bad sectors' in o and '   1456128 bytes available on disk' in o
          and said(o, 'FORMAT-OK') and fatcheck.check(img)[0] == [], o)
    shell(k, 'echo x > b:\\x.txt')
    o = shell(k, 'dir b:')
    check('... DIR B: counts them out of the free space', '1455616 bytes free' in o, o)
    k = boot(blank('b.img'))
    k.pc.drives[1].bad = {20}                           # (the root directory's second sector)
    o = fmt(k, 'format b:')
    check('a bad sector in the system area: "Track 0 bad - disk unusable", exit code 4',
          'Track 0 bad' in o and 'Format terminated' in o and said(o, 'FORMAT-FAILED'), o)

def t_wp_empty():
    p = mkimg.build(os.path.join(OUT, 'wp.img'), [os.path.join(SRC, 'LCMD.COM')])
    k = boot(p)
    d = k.pc.drives[1]; d.wp = True; raw = bytes(d.img)
    o = fmt(k, 'format b:')
    check('write-protected: "Write protect error", the disk as it was, exit code 4',
          'Write protect error' in o and 'Format terminated' in o and said(o, 'FORMAT-FAILED')
          and bytes(d.img) == raw, o)
    d.wp = False; d.empty = True
    o = fmt(k, 'format b: /q')
    check('no disk in the drive (/Q): "Not ready", exit code 4', 'Not ready' in o and said(o, 'FORMAT-FAILED'), o)
    o = fmt(k, 'format b:')
    check('no disk in the drive: "Not ready", exit code 4', 'Not ready' in o and said(o, 'FORMAT-FAILED'), o)

def t_quick():
    p = mkimg.build(os.path.join(OUT, 'q.img'), [os.path.join(SRC, 'LCMD.COM'), 'SUB\\',
                                                  'SUB\\F.COM=' + os.path.join(SRC, 'FORMAT.COM')])
    img = bytearray(open(p, 'rb').read())                # a bad cluster (2800) in its FAT
    for f in (0, 1):
        o = 512 + f * 9 * 512 + 2800 * 3 // 2
        img[o] = 0xF7; img[o + 1] = (img[o + 1] & 0xF0) | 0x0F
    open(p, 'wb').write(img)
    k = boot(p)
    shell(k, 'cd b:\\sub')
    o0 = shell(k, 'dir b:')
    d = k.pc.drives[1]
    n0 = len(d.formats)
    o = fmt(k, 'format b: /q /v:quick')
    img = bytes(d.img)
    check('/Q: no track formatted, the files gone, the bad cluster kept (and counted), the label',
          'QuickFormatting' in o and said(o, 'FORMAT-OK') and len(d.formats) == n0 and fat12(img, 2800) == 0xFF7
          and sum(fat12(img, c) != 0 for c in range(2, 2849)) == 1 and '       512 bytes in bad sectors' in o
          and fatcheck.check(img) == ([], {}) and img[19 * 512:19 * 512 + 11] == b'QUICK      ', (o0, o))
    o = shell(k, 'dir b:')
    check('... the kernel sees it empty, its current directory there back at the root',
          'Volume in drive B is QUICK' in o and 'File not found' in o and 'Directory of  B:\\' in o
          and 'SUB' not in o, o)
    k = boot(blank('b.img'))
    o = fmt(k, 'format b: /q')
    check('/Q on a disk never formatted: refused ("cannot be QuickFormatted"), exit code 4',
          'cannot be QuickFormatted' in o and said(o, 'FORMAT-FAILED') and not k.pc.drives[1].formats, o)
    p = mkimg.build(os.path.join(OUT, 'q.img'), [], size=720)
    k = boot(p)
    o = fmt(k, 'format b: /q /f:1.44')
    check('/Q /F:1.44 on a 720 KB disk: refused ("differs")', 'differs' in o and said(o, 'FORMAT-FAILED'), o)
    o = fmt(k, 'format b: /q')
    check('/Q on a 720 KB disk: stays 720 KB', said(o, 'FORMAT-OK') and '    730112 bytes total' in o
          and bpb(bytes(k.pc.drives[1].img))[5] == 1440, o)

def t_sys():
    k = boot(blank('b.img'))
    o = fmt(k, 'format b: /s')
    img = bytes(k.pc.drives[1].img)
    p, files = fatcheck.check(img)
    got = fatcheck.read_files(img)
    same = all(open(os.path.join(SRC, f), 'rb').read() == got.get('A:\\' + f) for f in SYSF)
    used = sum((len(open(os.path.join(SRC, f), 'rb').read()) + 511) // 512 * 512 for f in SYSF)
    check('/S: "System transferred", the four files on it as on the start-up disk, the space they take',
          'System transferred' in o and said(o, 'FORMAT-OK') and p == [] and same
          and '%10d bytes used by system' % used in o
          and '%10d bytes available' % (1457664 - used) in o, (o, p, sorted(files)))
    # the new disk starts Lodestone
    bp = os.path.join(OUT, 'sys.img'); open(bp, 'wb').write(img)
    k2 = ktest.KPC(bp); k2.start()
    check('... and it starts Lodestone: the Executive, its files listed', 'LCMD.COM' in k2.exec_list()
          and not k2.crashed, k2.exec_list())
    # without LODE.SYS on the start-up disk
    k = boot(blank('b.img'), files=('LODE.SYS', 'LCMD.COM', 'FORMAT.COM'))
    o = fmt(k, 'format b: /s')
    img = bytes(k.pc.drives[1].img)
    p, files = fatcheck.check(img)
    check('/S with only LODE.SYS and LCMD.COM there: those two', 'System transferred' in o
          and sorted(files) == ['\\LCMD.COM', '\\LODE.SYS'], (o, sorted(files)))
    # a disk without the system says so when started from
    k = boot(blank('b.img'))
    fmt(k, 'format b:')
    bp = os.path.join(OUT, 'nosys.img'); open(bp, 'wb').write(bytes(k.pc.drives[1].img))
    k2 = ktest.KPC(bp)
    k2.pc.boot(0); k2.pc.run_for(2)
    check('a disk formatted without /S, started from: "no LODE.SYS on this disk"',
          'no LODE.SYS on this disk' in ''.join(k2.pc.tty), ''.join(k2.pc.tty)[-200:])

def t_own_drive():
    k = boot()
    cmd(k, 'format a: /s /v:mine && echo FORMAT-OK || echo FORMAT-FAILED')
    ok = wait(k, 'strike ENTER', 20)
    old = k.pc.drives[0]
    new = pcemu.Floppy(bytes(1474560)); new.noid = set(range(2880)); new.changed = True
    k.pc.drives[0] = new                                # the start-up disk out, a new one in
    k.key(ktest.ENTER, settle=False)
    wait(k, 'another (Y/N)?', 400)
    k.key('n', settle=False)
    k.pc.run_for(1)
    o = scr(k)
    old.changed = True; k.pc.drives[0] = old            # (back, for the prompt's own files)
    k.settle(20)
    img = bytes(new.img)
    p, files = fatcheck.check(img)
    check('FORMAT A: /S on a one-drive start: the system read first, the new disk in A: made bootable',
          ok and 'System transferred' in o and p == [] and all('\\' + f in files for f in SYSF)
          and img[0x2B:0x36] == b'MINE       ', (o, p, sorted(files)))
    check('... back at the prompt with the start-up disk', said(scr(k), 'FORMAT-OK') and not k.crashed, scr(k))

def t_answers():
    p = os.path.join(OUT, 'ANS.TXT'); open(p, 'wb').write(b'\r\nN\r\n')
    k = boot(blank('b.img'), extra=(p,))
    cmd(k, 'format b: < ans.txt && echo FORMAT-OK || echo FORMAT-FAILED')
    k.pc.run_until(lambda: said(scr(k), 'FORMAT-OK') or said(scr(k), 'FORMAT-FAILED'), 400)
    o = scr(k)
    check('the answers from a file (FORMAT B: < ANS.TXT): formats, no key pressed',
          'Format complete' in o and said(o, 'FORMAT-OK') and len(k.pc.drives[1].formats) == 160, o)
    k = boot(blank('b.img'))
    cmd(k, 'format b:')
    wait(k, 'strike ENTER', 20)
    k.key(chr(27)); k.settle(10)
    o = shell(k, 'if errorlevel 3 echo LEVEL3')
    check('Esc at the prompt: nothing touched, exit code 3',
          'LEVEL3' in o and not k.pc.drives[1].formats, o)
    cmd(k, 'format b:')
    wait(k, 'strike ENTER', 20)
    k.key(ktest.ENTER, settle=False)
    wait(k, 'Cylinder: 10', 200)
    k.key(chr(27)); k.settle(10)
    n = len(k.pc.drives[1].formats)
    o = shell(k, 'if errorlevel 3 echo LEVEL3')
    check('Esc while it formats: stops there, exit code 3', 'LEVEL3' in o and 20 <= n < 40, (n, o))
    o = fmt(k, 'format b:', more='y')
    check('Format another: Y asks for the next disk', o.count('strike ENTER') == 2, o)
    k.key(chr(27)); k.settle(10)

def t_refused():
    k = boot(blank('b.img'))
    for line, want in (('format', 'which drive'), ('format c:', 'No hard disk answers'), ('format m:', 'hard disk (C:) only'),
                       ('format b: /f:1200', 'not supported by drive'), ('format b: /n:15 /t:40', 'not supported'),
                       ('format b: /x', 'Invalid parameter'), ('format b: /f:999', 'Invalid parameter'),
                       ('format b: /v:twelve-chars', 'Invalid characters'), ('format b: /v:a.b', 'Invalid characters')):
        o = shell(k, line + ' && echo FORMAT-OK || echo FORMAT-FAILED')
        check('%s: "%s", exit code 4, nothing done' % (line.upper(), want),
              want in o and said(o, 'FORMAT-FAILED') and 'Insert new' not in o and not k.pc.drives[1].formats, o)
    k = boot()
    o = shell(k, 'format b: && echo FORMAT-OK || echo FORMAT-FAILED')
    check('FORMAT B: with no drive B:: "Invalid drive specification"', 'Invalid drive' in o and said(o, 'FORMAT-FAILED'), o)

# ---------------------------------------------------------------------
#  C:, the hard disk: 120 x 4 x 17 (8,160 sectors, 4 MB), one FAT16
#  partition from sector 17 with 512-byte clusters (8,079 of them)
# ---------------------------------------------------------------------
HCYL, HHEADS, HSPT, PLBA = 120, 4, 17, 17
PSECS = HCYL * HHEADS * HSPT - PLBA
STUB = bytes.fromhex('fa31c08ed0bc007c8ed8fbfc')   # (the C: boot sector's code, at 3Eh)

def hdisk(tree=None, spc=1, label='OLDHD'):
    f = F.Fat(PSECS, spc, PLBA, True, label=label, spt=HSPT, heads=HHEADS)
    if tree is None:
        tree = [('SUB', 0, [('A.TXT', 0x20, b'a' * 3000), ('B.TXT', 0x20, b'b' * 700)]),
                ('README.TXT', 0x20, b'Hello from C:\r\n' * 40), ('BIG.DAT', 0x20, bytes(range(256)) * 300)]
    f.finish(f.tree(tree))
    return F.disk(HCYL, HHEADS, HSPT, PLBA, f)

def hdrive(d, **kw):
    return pcemu.Ata(model='Test CF 4MB', cyls=HCYL, heads=HHEADS, spt=HSPT, disk=d, **kw)

def hfmt(k, line, answer='y', sim_s=600):
    """FORMAT C: at the prompt, `answer` to Proceed with Format; the screen after."""
    cmd(k, line + ' && echo FORMAT-OK || echo FORMAT-FAILED')
    if answer is not None and wait(k, 'Proceed with Format (Y/N)?', 30):
        k.key(answer, settle=False)
    k.pc.run_until(lambda: said(scr(k), 'FORMAT-OK') or said(scr(k), 'FORMAT-FAILED'), sim_s)
    k.settle(20)
    return scr(k)

def bpb16(v):
    return (v.spc, v.rsv, v.nfats, v.nroot, v.spf, v.total)

def t_hd_full():
    ata = hdrive(hdisk())
    old = F.Volume(ata.disk, PLBA)
    ata.bad = {PLBA + old.data + 4000}                  # a data sector: cluster 4002's
    k = boot(ata=ata)
    sub = next(c for n, a, c, sz in old.entries(0) if n == 'SUB')
    shell(k, 'dir c:\\sub'); shell(k, 'cd c:\\sub')       # (SUB's sector in the kernel's buffers)
    r0 = ata.reads
    o = hfmt(k, 'format c: /v:newhd')
    v = F.Volume(ata.disk, PLBA)
    files, probs = v.files()
    check('FORMAT C: /V:NEWHD (the kernel\'s C:): the warning, Y, the disk read through, the figures, exit code 0',
          all(x in o for x in ('ALL DATA ON NON-REMOVABLE DISK', 'DRIVE C: WILL BE LOST!', '100 percent of disk formatted',
                               'Format complete', '%10d bytes total disk space' % ((v.ncl - 2) * 512),
                               '       512 bytes in bad sectors', 'Volume Serial Number is'))
          and said(o, 'FORMAT-OK') and 'Restart' not in o and ata.reads > r0 + 100, o)
    check("... its layout as it was, the files gone, CHKDSK-clean, the bad sector's cluster FFF7h",
          bpb16(v) == bpb16(old) and files == {} and probs == [] and v.fat(4002) == 0xFFF7
          and sum(v.fat(c) != 0 for c in range(2, v.ncl)) == 1 and (v.fat(0), v.fat(1)) == (0xFFF8, 0xFFFF), (bpb16(v), bpb16(old), files, probs))
    b = v.sec(0)
    check('... the boot sector: code that starts nothing, the BPB, the serial, label NEWHD, FAT16',
          b[0x3E:0x3E + len(STUB)] == STUB and b[510:512] == b'\x55\xAA' and b[0x24] == 0x80 and b[0x26] == 0x29
          and b[0x2B:0x36] == b'NEWHD      ' and b[0x36:0x3E] == b'FAT16   ' and b[0x0B:0x24] == old.sec(0)[0x0B:0x24], b[:64])
    r = v.sec(v.root)
    check('... the label in the root, nothing else', r[0:11] == b'NEWHD      ' and r[11] == 8 and r[32] == 0, r[:64])
    o = shell(k, 'dir c:')
    check('the kernel sees it at once: DIR C: the new label, no files, its current directory the root',
          'Volume in drive C is NEWHD' in o and 'File not found' in o and 'Directory of  C:\\' in o and 'SUB' not in o, o)
    shell(k, 'md c:\\new'); shell(k, 'echo hello > c:\\new\\f.txt'); shell(k, 'copy a:\\lcmd.com c:\\')
    o = shell(k, 'dir c:\\new')
    v = F.Volume(ata.disk, PLBA)
    files, probs = v.files()
    new = next(c for n, a, c, sz in v.entries(0) if n == 'NEW')
    check("... and writes to it: a directory in SUB's old cluster (., .. and its file only), files, CHKDSK-clean",
          new == sub and 'F        TXT' in o and 'A        TXT' not in o and '3 File(s)' in o and probs == []
          and (files.get('\\NEW\\F.TXT') or b'').strip() == b'hello'
          and files.get('\\LCMD.COM') == open(os.path.join(SRC, 'LCMD.COM'), 'rb').read() and v.fat(4002) == 0xFFF7,
          (o, probs, sorted(files)))
    o = shell(k, 'dir c:')
    check('... DIR C: counts the bad cluster out of the free space', '%d bytes free' % (v.free() * 512) in o, (o, v.free()))

def t_hd_quick():
    ata = hdrive(hdisk())
    old = F.Volume(ata.disk, PLBA)
    for n in range(2):                                  # cluster 5000 bad in the old FAT
        o = (PLBA + old.rsv + n * old.spf) * 512 + 5000 * 2
        ata.disk[o:o + 2] = b'\xF7\xFF'
    k = boot(ata=ata)
    r0 = ata.reads
    o = hfmt(k, 'format c: /q')
    v = F.Volume(ata.disk, PLBA)
    files, probs = v.files()
    check('FORMAT C: /Q: the old FAT read, no surface read, the bad cluster kept, no label, exit code 0',
          said(o, 'FORMAT-OK') and 'percent' not in o and ata.reads - r0 < 40 and files == {} and probs == []
          and v.fat(5000) == 0xFFF7 and '       512 bytes in bad sectors' in o and v.sec(0)[0x2B:0x36] == b'NO NAME    '
          and bpb16(v) == bpb16(old), (o, ata.reads - r0, probs))

def t_hd_no():
    ata = hdrive(hdisk()); raw = bytes(ata.disk)
    k = boot(ata=ata)
    o = hfmt(k, 'format c:', answer='n')
    o2 = shell(k, 'if errorlevel 5 echo LEVEL5')
    check('N at Proceed with Format: nothing written, exit code 5',
          said(o, 'FORMAT-FAILED') and 'LEVEL5' in o2 and bytes(ata.disk) == raw and not ata.writes, (o, o2))
    cmd(k, 'format c:'); wait(k, 'Proceed with Format', 30)
    k.key('y', settle=False); wait(k, 'percent of disk formatted', 60)
    k.key(chr(27)); k.settle(20)
    o = scr(k)
    o2 = shell(k, 'if errorlevel 3 echo LEVEL3')
    check('Esc while it reads the disk: "nothing written", exit code 3, the disk as it was',
          'nothing written' in o and 'LEVEL3' in o2 and bytes(ata.disk) == raw and not ata.writes, (o, o2))
    ata = hdrive(hdisk(tree=[('F.BAT', 0x20, b'@format c: && echo FORMAT-OK || echo FORMAT-FAILED\r\n')]))
    raw = bytes(ata.disk)
    k = boot(ata=ata)
    cmd(k, 'c:\\f.bat'); k.settle(30)
    o = scr(k)
    check('run from a batch file on C:: "Files are open on drive C:", exit code 4, nothing written',
          'Files are open on drive C:' in o and said(o, 'FORMAT-FAILED') and bytes(ata.disk) == raw, o)
    k = boot(ata=hdrive(hdisk()))
    for line in ('format c: /s', 'format c: /f:720', 'format c: /4', 'format c: /n:9 /t:80'):
        o = shell(k, line + ' && echo FORMAT-OK || echo FORMAT-FAILED')
        check('%s: "Invalid parameter", exit code 4, no warning' % line.upper(),
              'Invalid parameter' in o and said(o, 'FORMAT-FAILED') and 'Proceed' not in o, o)

def t_hd_own():
    d = hdisk()
    d[PLBA * 512:(PLBA + 1) * 512] = bytes(512)          # the boot sector gone: the kernel finds no C:
    ata = hdrive(d)
    bad = PLBA + 3000
    ata.bad = {bad}
    k = boot(ata=ata)
    o0 = shell(k, 'c:')
    o = hfmt(k, 'format c: /v:fresh')
    v = F.Volume(ata.disk, PLBA)
    files, probs = v.files()
    check('no C: for the kernel: FORMAT drives the disk itself, verifies it, "Restart Lodestone to use C:"',
          'Invalid drive' in o0 and 'Proceed with Format' in o and '100 percent' in o and said(o, 'FORMAT-OK')
          and 'Restart Lodestone to use C:' in o and getattr(ata, 'verifies', 0) > 50, (o0, o))
    check('... a new FAT16 layout: 512-byte clusters (4 MB), 512 root entries, the FAT it needs, CHKDSK-clean',
          (v.spc, v.rsv, v.nfats, v.nroot) == (1, 1, 2, 512) and v.total == PSECS and 4085 <= v.ncl - 2 <= 65524
          and v.spf == -(-v.ncl // 256) and files == {} and probs == [] and v.fat(0) == 0xFFF8
          and struct.unpack_from('<I', v.sec(0), 0x1C)[0] == PLBA
          and struct.unpack_from('<HH', v.sec(0), 0x18) == (HSPT, HHEADS), (bpb16(v), v.ncl, probs))
    cl = (bad - PLBA - v.data) // v.spc + 2
    check("... the unreadable sector's cluster FFF7h, the label", v.fat(cl) == 0xFFF7
          and v.sec(v.root)[0:11] == b'FRESH      ', (cl, v.fat(cl)))
    k = boot(ata=ata)                                   # restarted
    shell(k, 'echo hi > c:\\x.txt')
    o = shell(k, 'dir c:')
    v = F.Volume(ata.disk, PLBA)
    check('... and after a restart the kernel has C: and writes to it',
          'Volume in drive C is FRESH' in o and 'X        TXT' in o and v.files()[1] == [], o)
    f = F.Fat(68640 - 39, 4, 39, True)                  # 34 MB: 2 KB clusters, as MS-DOS
    f.finish([])
    d = F.disk(220, 8, 39, 39, f)
    d[39 * 512:40 * 512] = bytes(512)
    ata = pcemu.Ata(model='Test 34MB', cyls=220, heads=8, spt=39, disk=d)
    k = boot(ata=ata)
    o = hfmt(k, 'format c: /q')
    v = F.Volume(ata.disk, 39)
    check('/Q on a 34 MB partition the kernel has no file system on: 2 KB clusters, nothing verified, CHKDSK-clean',
          said(o, 'FORMAT-OK') and v.spc == 4 and v.files()[1] == [] and getattr(ata, 'verifies', 0) == 0, (o, bpb16(v)))

def t_hd_nopart():
    d = hdisk()
    d[446 + 4] = 0x0B                                   # FAT32's type: no partition of ours
    ata = hdrive(d); raw = bytes(ata.disk)
    k = boot(ata=ata)
    o = shell(k, 'format c: && echo FORMAT-OK || echo FORMAT-FAILED')
    check('a disk with no FAT16 partition: "FDISK it first", exit code 4, no warning, nothing written',
          'FDISK it first' in o and said(o, 'FORMAT-FAILED') and 'Proceed' not in o and bytes(ata.disk) == raw, o)

if __name__ == '__main__':
    t0 = time.time()
    for t in (t_full, t_720, t_525, t_bad, t_wp_empty, t_quick, t_sys, t_own_drive, t_answers, t_refused,
              t_hd_full, t_hd_quick, t_hd_no, t_hd_own, t_hd_nopart):
        if sys.argv[1:] and t.__name__ not in sys.argv[1:]: continue
        t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
