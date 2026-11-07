"""CHKDSK.COM in the emulator, from the command prompt, against disks
damaged on purpose, each read back after by fat16img's own checker: a
clean floppy (the figures, nothing written), lost chains (said; /F: Y
makes FILEnnnn.CHK of them with their data, N frees them), a cross link,
sizes that don't match the chain (both ways), a chain into a free
cluster, a chain that loops, a first cluster that is no cluster, a
subdirectory's "." and "..", FATs that differ, /F on a write-protected
disk, C: (FAT16 through INT 25h/26h, the kernel seeing the fix), M: (from
its EMS pages; /F refused there), and the drives and switches it
refuses.

    python3 tests/test_chkdsk.py
"""
import os, struct, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, pcemu, fat16img as F

OUT = tempfile.mkdtemp()
SRC = os.path.join(GOS, 'src')
LCMD = os.path.join(SRC, 'LCMD.COM')
BIG = os.path.join(SRC, 'LODE.SYS')
SMALL = os.path.join(SRC, 'CHKDSK.COM')
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

def said(o, line):
    return any(l.strip() == line for l in o.split('\n'))

class Fl:
    """A 1.44 MB FAT12 floppy image, to be damaged: both FATs at once."""
    def __init__(s, path): s.path = path; s.img = bytearray(open(path, 'rb').read())
    def get(s, n):
        v = struct.unpack_from('<H', s.img, 512 + n * 3 // 2)[0]
        return v >> 4 if n & 1 else v & 0xFFF
    def set(s, n, v, fats=(0, 1)):
        for k in fats:
            o = 512 + k * 9 * 512 + n * 3 // 2
            w = struct.unpack_from('<H', s.img, o)[0]
            w = (w & 0x000F) | (v << 4) if n & 1 else (w & 0xF000) | v
            struct.pack_into('<H', s.img, o, w)
    def ent(s, name, dircl=None):
        """the offset of name's entry (in the root, or in the directory at cluster dircl's first sector)"""
        base = 19 * 512 if dircl is None else (33 + dircl - 2) * 512
        n = 224 if dircl is None else 16
        nm = name.ljust(11).encode() if name in ('.', '..') else \
            (name.split('.')[0].ljust(8) + (name.split('.')[1] if '.' in name else '').ljust(3)).encode()
        for i in range(n):
            if s.img[base + i * 32:base + i * 32 + 11] == nm: return base + i * 32
        raise KeyError(name)
    def first(s, name, dircl=None): return struct.unpack_from('<H', s.img, s.ent(name, dircl) + 26)[0]
    def setw(s, off, v): struct.pack_into('<H', s.img, off, v)
    def setd(s, off, v): struct.pack_into('<I', s.img, off, v)
    def save(s): open(s.path, 'wb').write(s.img); return s.path

def disk(name, files=(LCMD, 'SUB\\', 'SUB\\S.COM=' + SMALL, BIG)):
    return Fl(mkimg.build(os.path.join(OUT, name), list(files)))

def boot(b=None, **kw):
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(SRC, f) for f in ('LODE.SYS', 'LCMD.COM', 'CHKDSK.COM')])
    k = ktest.KPC(img, b, **kw)
    k.start(); k.code_p()
    return k

def out(k): return ''.join(k.pc.tty).replace('\r', '')

def run(k, line, answer=None, sim=60):
    """line at the prompt -> all it printed, and a line E0, E1, ... with its exit code"""
    k.pc.tty.clear()
    k.key(line); k.key(ktest.ENTER, settle=False)
    if answer is not None:
        k.pc.run_until(lambda: '(Y/N)?' in out(k), sim)
        k.key(answer, settle=False)
    k.settle(sim)
    o = out(k)
    for n in (1, 2, 3):
        k.key('if errorlevel %d echo L%d' % (n, n)); k.key(ktest.ENTER)
    lv = sum(said(out(k)[len(o):], 'L%d' % n) for n in (1, 2, 3))
    return o + '\nE%d\n' % lv

def vcheck(img):
    return F.Volume(bytes(img), 0).files()

def t_clean():
    d = disk('b.img')
    k = boot(d.path)
    raw = bytes(k.pc.drives[1].img)
    o = run(k, 'chkdsk b: /v')
    v = F.Volume(raw, 0)
    free = v.free() * 512
    check('a clean disk: no errors, every name with /V, exit code 0, nothing written',
          said(o, 'E0') and 'Errors' not in o and 'B:\\SUB\\S.COM' in o and 'B:\\LODE.SYS' in o
          and bytes(k.pc.drives[1].img) == raw, o)
    check('... the figures: total, directories, user files, free, memory',
          '   1457664 bytes total disk space' in o and '       512 bytes in 1 directories' in o
          and '%10d bytes available on disk' % free in o and '    655360 bytes total memory' in o
          and ' bytes in 3 user files' in o and 'Volume LODESTONE' in o and 'Serial Number' in o, o)
    o = run(k, 'chkdsk')
    check('CHKDSK alone: the current drive (A:)', said(o, 'E0') and ' bytes in 3 user files' in o, o)
    o = run(k, 'chkdsk b: /f')
    check('/F on a clean disk: nothing written, exit code 0', said(o, 'E0') and bytes(k.pc.drives[1].img) == raw, o)

def lost_disk(name):
    d = disk(name)
    for c in range(2000, 2004): d.set(c, c + 1)         # a chain of 5, and a single one
    d.set(2004, 0xFFF)
    d.set(2100, 0xFFF)
    for c in range(2000, 2005): d.img[(33 + c - 2) * 512:(34 + c - 2) * 512] = bytes([c & 0xFF]) * 512
    return d

def t_lost():
    d = lost_disk('lost.img'); d.save()
    k = boot(d.path)
    raw = bytes(k.pc.drives[1].img)
    o = run(k, 'chkdsk b:')
    check('lost chains: "Errors found, F parameter not specified", "6 lost clusters found in 2 chains", '
          '"would be freed", exit code 1, nothing written',
          'Errors found, F parameter not specified' in o and '   6 lost clusters found in 2 chains.' in o
          and '      3072 bytes disk space would be freed' in o and said(o, 'E1') and bytes(k.pc.drives[1].img) == raw, o)
    o = run(k, 'chkdsk b: /f', 'y')
    img = bytes(k.pc.drives[1].img)
    files, probs = vcheck(img)
    check('/F, Y: FILE0000.CHK (the chain of 5, its data) and FILE0001.CHK, the disk consistent after',
          probs == [] and files.get('\\FILE0000.CHK') == b''.join(bytes([c & 0xFF]) * 512 for c in range(2000, 2005))
          and len(files.get('\\FILE0001.CHK', b'')) == 512 and said(o, 'E1'), (o, probs, sorted(files)))
    o = run(k, 'dir b:')
    check('... and the kernel sees them (the floppy read again)', 'FILE0000 CHK     2560' in o and 'FILE0001 CHK      512' in o, o)
    o = run(k, 'chkdsk b:')
    check('... CHKDSK again: no errors', said(o, 'E0') and 'Errors' not in o, o)
    d = lost_disk('lost2.img'); d.save()
    k = boot(d.path)
    o = run(k, 'chkdsk b: /f', 'n')
    img = bytes(k.pc.drives[1].img)
    files, probs = vcheck(img)
    v = F.Volume(img, 0)
    check('/F, N: the lost clusters freed, no .CHK files', probs == [] and not any('CHK' in f for f in files)
          and all(v.fat(c) == 0 for c in list(range(2000, 2005)) + [2100]) and '      3072 bytes disk space freed' in o, o)

def t_damage():
    # each damage alone, on its own disk: (what, setup(d), message, then fixed as)
    cases = []
    def cross(d):
        a, b = d.first('LCMD.COM'), d.first('LODE.SYS')
        d.set(a + 2, b + 3)                             # LCMD's third cluster on into LODE.SYS's fourth
        return b + 3
    def big_size(d):
        d.setd(d.ent('LCMD.COM') + 28, 30000)           # (24 clusters, 30000 needs 59)
    def small_size(d):
        d.setd(d.ent('LCMD.COM') + 28, 5000)            # (needs 10 of its 24)
    def into_free(d):
        a = d.first('LCMD.COM'); d.set(a + 4, 2700)    # (2700 is free)
        return a
    def loop(d):
        a = d.first('LCMD.COM'); d.set(a + 4, a + 1)
        return a
    def bad_first(d):
        d.setw(d.ent('LCMD.COM') + 26, 4000)            # (past the disk's 2849 clusters)
    def dots(d):
        s = d.first('SUB')
        d.setw(d.ent('.', s) + 26, 77); d.setw(d.ent('..', s) + 26, 66)
    def fats(d):
        d.set(2500, 0xFFF, fats=(1,))
    for name, fn, msg, after in (
            ('a cross link', cross, 'Is cross linked on cluster', None),
            ('a size past its chain', big_size, 'Allocation error, size adjusted', lambda f, v: len(f['\\LCMD.COM']) == 24 * 512),
            ('a chain past its size', small_size, 'Allocation error, size adjusted',
             lambda f, v: len(f['\\LCMD.COM']) == 5000 and '\\FILE0000.CHK' in f),
            ('a chain into a free cluster', into_free, 'Has invalid cluster, file truncated',
             lambda f, v: len(f['\\LCMD.COM']) == 5 * 512),
            ('a chain looping back', loop, 'Has invalid cluster, file truncated', lambda f, v: len(f['\\LCMD.COM']) == 5 * 512),
            ('a first cluster that is no cluster', bad_first, 'First cluster number is invalid, entry truncated',
             lambda f, v: f['\\LCMD.COM'] == b'' and '\\FILE0000.CHK' in f),
            ('a subdirectory\'s "." and ".."', dots, 'Invalid sub-directory entry', None),
            ('the two FATs differing', fats, 'The two copies of the File Allocation Table differ', None)):
        d = disk('d.img')
        n = fn(d); d.save()
        k = boot(d.path)
        raw = bytes(k.pc.drives[1].img)
        o = run(k, 'chkdsk b:')
        what = ('LCMD.COM' if fn not in (dots, fats) else '')
        check('%s: "%s"%s, exit code 1, nothing written' % (name, msg, ' (on its path)' if what else ''),
              msg in o and said(o, 'E1') and bytes(k.pc.drives[1].img) == raw and (what == '' or 'B:\\' + what in o)
              and (fn is not cross or 'cross linked on cluster %d' % n in o), o)
        k.pc.tty.clear()
        k.key('chkdsk b: /f'); k.key(ktest.ENTER, settle=False)
        k.pc.run_until(lambda: '(Y/N)?' in out(k) or 'bytes free' in out(k), 60)
        if '(Y/N)?' in out(k): k.key('y', settle=False)
        k.settle(60)
        o = out(k)
        img = bytes(k.pc.drives[1].img)
        files, probs = vcheck(img)
        if fn is cross:
            check('... /F: the cross link left as it is (said again)', 'cross linked' in o, o)
            continue
        if fn is dots:
            v = F.Volume(img, 0); s = d.first('SUB'); e = img[(33 + s - 2) * 512:]
            check('... /F: "." and ".." pointed at it and at the root',
                  struct.unpack_from('<H', e, 26)[0] == s and struct.unpack_from('<H', e, 58)[0] == 0 and probs == [], (o, probs))
            continue
        check('... /F: corrected, the disk consistent after', probs == [] and (after is None or after(files, None))
              and 'Errors found' not in o, (o, probs, {f: len(b) for f, b in files.items()}))
        o = run(k, 'chkdsk b:')
        check('... and CHKDSK again: no errors', said(o, 'E0'), o)

def t_deep():
    f = F.Fat(2880, 1, 0, False, rootents=224, spt=18, heads=2)
    f.finish(f.tree([('A', 0, [('B', 0, [('C', 0, [('D', 0, [('E', 0, [('DEEP.TXT', 0x20, b'x' * 3000)])]),
                                                   ('C2.TXT', 0x20, b'y' * 700)])])]), ('TOP.TXT', 0x20, b'z' * 100)]))
    img = bytearray(f.img)
    o = img.find(b'DEEP    TXT'); struct.pack_into('<I', img, o + 28, 9000)      # (6 clusters; 9000 needs 18)
    p = os.path.join(OUT, 'deep.img'); open(p, 'wb').write(img)
    k = boot(p)
    o = run(k, 'chkdsk b: /v')
    lines = [l.strip() for l in o.split('\n')]
    i = lines.index('B:\\A\\B\\C\\D\\E\\DEEP.TXT') if 'B:\\A\\B\\C\\D\\E\\DEEP.TXT' in lines else -1
    check('five directories down: /V gives each path whole, the error on the deepest file\'s, the paths right after',
          i >= 0 and 'B:\\A\\B\\C\\C2.TXT' in lines and 'B:\\TOP.TXT' in lines
          and 'Allocation error, size adjusted' in lines and said(o, 'E1') and ' bytes in 5 directories' in o, o)
    o = run(k, 'chkdsk b: /f')
    files, probs = vcheck(k.pc.drives[1].img)
    check('... /F: its size to its chain (written in its directory, 5 down)', probs == []
          and len(files.get('\\A\\B\\C\\D\\E\\DEEP.TXT', b'')) == 3072 and len(files['\\A\\B\\C\\C2.TXT']) == 700, (o, probs))

def t_720():
    d = Fl(mkimg.build(os.path.join(OUT, 's.img'), [LCMD, BIG], size=720))
    d.set(600, 601); d.set(601, 0xFFF); d.save()
    k = boot(d.path)
    o = run(k, 'chkdsk b:')
    check('720 KB (2 sectors a cluster): its figures, its lost chain', '    730112 bytes total disk space' in o
          and '   2 lost clusters found in 1 chains.' in o and '      2048 bytes disk space would be freed' in o, o)
    o = run(k, 'chkdsk b: /f', 'y')
    files, probs = vcheck(k.pc.drives[1].img)
    check('... /F: FILE0000.CHK of 2048 bytes', probs == [] and len(files.get('\\FILE0000.CHK', b'')) == 2048, (o, probs))

def t_wp():
    d = lost_disk('wp.img'); d.save()
    k = boot(d.path)
    k.pc.drives[1].wp = True
    raw = bytes(k.pc.drives[1].img)
    o = run(k, 'chkdsk b: /f', 'y')
    check('/F on a write-protected disk: "Write protect error", exit code 2, nothing changed',
          'Write protect error' in o and said(o, 'E2') and bytes(k.pc.drives[1].img) == raw, o)

def hd_disk(lost=False):
    f = F.Fat(100 * 4 * 17 - 17, 1, 17, True, label='HD')
    ents = f.tree([('HD', 0x08, None), ('A.TXT', 0x20, b'hello\r\n' * 300), ('DIR', 0, [('B.BIN', 0x20, bytes(range(256)) * 40)])])
    f.finish(ents)
    d = F.disk(100, 4, 17, 17, f)
    if lost:
        for k in range(2):
            o = (17 + 1 + k * f.spf) * 512
            for c in (5000, 5001): struct.pack_into('<H', d, o + c * 2, c + 1 if c == 5000 else 0xFFFF)
    return d, f

def t_hd():
    d, f = hd_disk(lost=True)
    ata = pcemu.Ata(cyls=100, heads=4, spt=17, disk=d)
    k = boot(ata=ata)
    o = run(k, 'chkdsk c:')
    check('C: (FAT16, through INT 25h): its lost chain said, exit code 1',
          '   2 lost clusters found in 1 chains.' in o and said(o, 'E1') and 'Volume HD' in o and ' bytes in 1 directories' in o, o)
    o = run(k, 'chkdsk c: /f', 'y')
    files, probs = F.Volume(ata.disk, 17).files()
    check('C: /F, Y: FILE0000.CHK (through INT 26h), the partition consistent', probs == [] and
          len(files.get('\\FILE0000.CHK', b'')) == 1024 and files.get('\\DIR\\B.BIN') == bytes(range(256)) * 40, (o, probs))
    o = run(k, 'dir c:')
    o2 = run(k, 'chkdsk c:')
    check('... the kernel sees it at once (DIR C:), and CHKDSK again: no errors', 'FILE0000 CHK     1024' in o and said(o2, 'E0'), (o, o2))

def t_mdisk():
    k = boot(ems_pages=88)
    run(k, 'copy a:\\lcmd.com m:\\'); run(k, 'md m:\\d'); run(k, 'copy a:\\lode.sys m:\\d\\')
    o = run(k, 'chkdsk m:')
    check('M: (read from its EMS pages): no errors, its files counted', said(o, 'E0') and ' bytes in 2 user files' in o
          and ' bytes in 1 directories' in o, o)
    o = run(k, 'copy m:\\lcmd.com m:\\x.com')
    o = run(k, 'dir m:')
    check('... the EMS map as it was after (M: still works)', 'X        COM' in o, o)
    o = run(k, 'chkdsk m: /f')
    check('/F on M:: refused, exit code 2', 'not on M:' in o and said(o, 'E2'), o)

def t_refused():
    k = boot()
    for line, want in (('chkdsk b:', 'Invalid drive'), ('chkdsk c:', 'Invalid drive'), ('chkdsk m:', 'Invalid drive'),
                       ('chkdsk r:', 'the ROM'), ('chkdsk q:', 'Invalid drive'), ('chkdsk a: /x', 'Invalid parameter'),
                       ('chkdsk a:\\lcmd.com', 'Invalid parameter')):
        o = run(k, line)
        check('%s: "%s", exit code 2' % (line.upper(), want), want in o and said(o, 'E2'), o)
    b = os.path.join(OUT, 'blank.img'); open(b, 'wb').write(bytes(1474560))
    k = boot(b)
    o = run(k, 'chkdsk b:')
    check('a disk with no FAT file system: "Probable non-DOS disk", exit code 2', 'non-DOS' in o and said(o, 'E2'), o)

if __name__ == '__main__':
    t0 = time.time()
    names = sys.argv[1:]
    for t in (t_clean, t_lost, t_damage, t_deep, t_720, t_wp, t_hd, t_mdisk, t_refused):
        if not names or t.__name__[2:] in names: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
