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
import ktest, mkimg, pcemu, fatcheck

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

def boot(b=None, files=SYSF + ('FORMAT.COM',), extra=()):
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(SRC, f) for f in files] + list(extra))
    k = ktest.KPC(img, b)
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
    for line, want in (('format', 'which drive'), ('format c:', 'floppies only'), ('format m:', 'floppies only'),
                       ('format b: /f:1200', 'not supported by drive'), ('format b: /n:15 /t:40', 'not supported'),
                       ('format b: /x', 'Invalid parameter'), ('format b: /f:999', 'Invalid parameter'),
                       ('format b: /v:twelve-chars', 'Invalid characters'), ('format b: /v:a.b', 'Invalid characters')):
        o = shell(k, line + ' && echo FORMAT-OK || echo FORMAT-FAILED')
        check('%s: "%s", exit code 4, nothing done' % (line.upper(), want),
              want in o and said(o, 'FORMAT-FAILED') and 'Insert new' not in o and not k.pc.drives[1].formats, o)
    k = boot()
    o = shell(k, 'format b: && echo FORMAT-OK || echo FORMAT-FAILED')
    check('FORMAT B: with no drive B:: "Invalid drive specification"', 'Invalid drive' in o and said(o, 'FORMAT-FAILED'), o)

if __name__ == '__main__':
    t0 = time.time()
    for t in (t_full, t_720, t_525, t_bad, t_wp_empty, t_quick, t_sys, t_own_drive, t_answers, t_refused):
        t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
