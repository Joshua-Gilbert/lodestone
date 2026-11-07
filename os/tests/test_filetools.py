"""ATTRIB, TREE and XCOPY in the emulator, from the command prompt, each
result read back from the disk image (fatcheck, fat16img): ATTRIB's
listing and each bit, wildcards, /S, a hidden file, directories and the
label left alone; TREE's listing with and without /F, a hidden directory,
a deep tree; XCOPY from A: to B: and on one disk, a directory with /S and
/E, a name with wildcards, the F/D question answered from a file, /A /M
/D /P /V /W, a file onto itself, a cyclic copy, a full disk (the old
destination kept, nothing half-written left), a file bigger than memory,
and the exit codes.

    python3 tests/test_filetools.py [name ...]
"""
import os, struct, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, pcemu, fatcheck, fat16img as F

OUT = tempfile.mkdtemp()
SRC = os.path.join(GOS, 'src')
LCMD = os.path.join(SRC, 'LCMD.COM')
TOOLS = ('ATTRIB.COM', 'TREE.COM', 'XCOPY.COM')
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

def said(o, line):
    return any(l.strip() == line for l in o.split('\n'))

def mk(name, files=(), size=1440):
    """a floppy: files as mkimg takes them ('NAME=path', 'DIR\\'), or (name, bytes)"""
    fs = []
    for f in files:
        if isinstance(f, tuple):
            p = os.path.join(OUT, 'f_' + f[0].replace('\\', '_'))
            open(p, 'wb').write(f[1]); fs.append(f[0] + '=' + p)
        else: fs.append(f)
    return mkimg.build(os.path.join(OUT, name), fs, size=size)

DATA = [bytes((i * 7 + n) & 0xFF for i in range(600 + 377 * n)) for n in range(8)]
def adisk(extra=()):
    return mk('a.img', [os.path.join(SRC, f) for f in ('LODE.SYS', 'LCMD.COM') + TOOLS]
              + [('ONE.TXT', DATA[0]), ('TWO.DAT', DATA[1]), 'SUB\\', ('SUB\\X.TXT', DATA[2]),
                 'SUB\\DEEP\\', ('SUB\\DEEP\\Y.TXT', DATA[3]), 'EMPTY\\', 'SUB\\HOLLOW\\'] + list(extra))

def boot(a=None, b=None, **kw):
    k = ktest.KPC(a or adisk(), b if b is not None else mk('b.img'), **kw)
    k.start(); k.code_p()
    return k

def out(k): return ''.join(k.pc.tty).replace('\r', '')

def run(k, line, keys=(), sim=60):
    """line at the prompt (keys typed as it asks) -> all it printed, and a line E0, E1, ... with its exit code"""
    k.pc.tty.clear()
    k.key(line); k.key(ktest.ENTER, settle=False)
    for x in keys:
        k.settle(sim); k.key(x, settle=False)
    k.settle(sim)
    o = out(k)
    lv = 0
    for n in (1, 2, 3, 4, 5):
        k.pc.tty.clear()
        k.key('if errorlevel %d echo L%d' % (n, n)); k.key(ktest.ENTER)
        lv += said(out(k), 'L%d' % n)
    return o + '\nE%d\n' % lv

def files(img, drive='A'):
    return fatcheck.read_files(bytes(img), drive)

def entries(img, path=''):
    """{name: (attr, time, date, size)} of the directory at path ('' the root) of a FAT12 image"""
    v = F.Volume(bytes(img), 0)
    cl = 0
    for part in [p for p in path.split('\\') if p]:
        cl = next(f for n, a, f, s in v.entries(cl) if n == part)
    out = {}
    raw = v.sec(v.root, v.data - v.root) if cl == 0 else b''.join(v.clu(c) for c in v.chain(cl)[0])
    for i in range(0, len(raw), 32):
        e = raw[i:i + 32]
        if e[0] == 0: break
        if e[0] == 0xE5 or e[11] == 0x0F: continue
        n = e[:8].decode('latin-1').rstrip() + ('.' + e[8:11].decode('latin-1').rstrip() if e[8:11].strip() else '')
        out[n] = (e[11], struct.unpack_from('<H', e, 22)[0], struct.unpack_from('<H', e, 24)[0], struct.unpack_from('<I', e, 28)[0])
    return out

def setattr_img(img, path, attr):
    """an entry's attribute byte set in the image (as another DOS would have)"""
    v = F.Volume(bytes(img), 0)
    d, _, name = path.rpartition('\\')
    nm = (name.split('.')[0].ljust(8) + (name.split('.')[1] if '.' in name else '').ljust(3)).encode()
    cl = 0
    for part in [p for p in d.split('\\') if p]:
        cl = next(f for n, a, f, s in v.entries(cl) if n == part)
    secs = [v.root + i for i in range(v.data - v.root)] if cl == 0 else [v.data + (c - 2) * v.spc + j for c in v.chain(cl)[0] for j in range(v.spc)]
    for s in secs:
        o = s * 512
        for i in range(o, o + 512, 32):
            if img[i:i + 11] == nm: img[i + 11] = attr; return
    raise KeyError(path)

# ---------------------------------------------------------------------
def t_attrib():
    k = boot(adisk(['OTHER\\', ('OTHER\\Z.TXT', b'z')]))
    o = run(k, 'attrib')
    check('ATTRIB alone: the current directory\'s files, "A  SHR  path" (archive on), exit code 0',
          'A       A:\\ONE.TXT' in o and 'A       A:\\LCMD.COM' in o and 'SUB' not in o and said(o, 'E0'), o)
    o = run(k, 'attrib /s')
    check('ATTRIB /S: the files below too, their paths whole (a directory after one with directories in it too)',
          'A       A:\\SUB\\X.TXT' in o and 'A       A:\\SUB\\DEEP\\Y.TXT' in o and 'A       A:\\OTHER\\Z.TXT' in o
          and said(o, 'E0'), o)
    o = run(k, 'attrib +r -a one.txt')
    e = entries(k.pc.drives[0].img)
    check('ATTRIB +R -A ONE.TXT: read-only on, archive off, nothing printed', e['ONE.TXT'][0] == 0x01 and said(o, 'E0')
          and 'ONE' not in o.split('\n', 1)[1], (o, e['ONE.TXT']))
    o = run(k, 'attrib one.txt')
    check('... listed so: "     R  A:\\ONE.TXT"', '     R  A:\\ONE.TXT' in o, o)
    run(k, 'cd sub\\deep')
    o = run(k, 'attrib +h +s ..\\..\\t*.dat')
    o2 = run(k, 'attrib \\*.dat')
    e = entries(k.pc.drives[0].img)
    check('a relative path with ..\\..\\ and a wildcard: +H +S on TWO.DAT, still found and listed hidden ("A  SH   ")',
          e['TWO.DAT'][0] == 0x26 and 'A  SH   A:\\TWO.DAT' in o2, (o, o2, e['TWO.DAT']))
    run(k, 'cd \\')
    o = run(k, 'attrib +r /s *.txt')
    check('ATTRIB +R *.TXT /S: in every directory', entries(k.pc.drives[0].img, 'SUB')['X.TXT'][0] & 1
          and entries(k.pc.drives[0].img, 'SUB\\DEEP')['Y.TXT'][0] & 1 and said(o, 'E0'), o)
    o = run(k, 'attrib -r -h -s *.*')
    e = entries(k.pc.drives[0].img)
    check('... and -R -H -S *.*: bits off, directories (SUB 10h) and the label (08h) as they were',
          e['ONE.TXT'][0] == 0 and e['TWO.DAT'][0] == 0x20 and e['SUB'][0] == 0x10 and e['LODESTON.E'][0] == 0x08, e)
    for line, want in (('attrib +r sub', 'File not found - SUB'), ('attrib nosuch.*', 'File not found - NOSUCH.*'),
                       ('attrib +x one.txt', 'Invalid parameter'), ('attrib +r -r one.txt', 'Invalid parameter'),
                       ('attrib q:x', 'Invalid drive')):
        o = run(k, line)
        check('%s: "%s", exit code 1' % (line.upper(), want), want in o and said(o, 'E1'), o)

def t_tree():
    a = adisk()
    img = bytearray(open(a, 'rb').read())
    setattr_img(img, 'EMPTY', 0x12)                         # a hidden directory
    open(a, 'wb').write(img)
    k = boot(a)
    o = run(k, 'tree')
    want = ['DIRECTORY PATH LISTING FOR VOLUME LODESTONE', 'Path: \\SUB', 'Sub-directories:  DEEP', 'HOLLOW',
            'Path: \\SUB\\DEEP', 'Sub-directories:  None', 'Path: \\SUB\\HOLLOW', 'Path: \\EMPTY']
    lines = [l.strip() for l in o.split('\n')]
    pos = [lines.index(w) if w in lines else -1 for w in want]
    check('TREE: each directory, a parent before those in it (the hidden one too), no files, exit code 0',
          -1 not in pos and pos == sorted(pos) and 'Files:' not in o and 'Path: \\\n' not in o and said(o, 'E0'), o)
    o = run(k, 'tree a: /f')
    check('TREE A: /F: the root first, then each, its files as "NAME    .EXT", "None" where there are none',
          'Path: \\' in o and 'Files:            LODE    .SYS' in o and '                  ONE     .TXT' in o
          and 'Files:            Y       .TXT' in o and 'Files:            None' in o and said(o, 'E0'), o)
    o = run(k, 'tree b:')
    check('TREE B: (no directories): "No sub-directories exist"', 'No sub-directories exist' in o and said(o, 'E0'), o)
    deep = ['D%d\\' % 0] + ['\\'.join('D%d' % j for j in range(i + 1)) + '\\' for i in range(1, 8)]
    k = boot(b=mk('bd.img', deep + [('D0\\D1\\D2\\D3\\D4\\D5\\D6\\D7\\Z.TXT', b'z')]))
    o = run(k, 'tree b: /f')
    check('a tree 8 deep: each path whole, the file at the bottom', 'Path: \\D0\\D1\\D2\\D3\\D4\\D5\\D6\\D7' in o
          and 'Files:            Z       .TXT' in o, o)
    for line, want in (('tree q:', 'Invalid drive'), ('tree /x', 'Invalid parameter'), ('tree a: b:', 'Invalid parameter')):
        o = run(k, line)
        check('%s: "%s", exit code 1' % (line.upper(), want), want in o and said(o, 'E1'), o)

def t_xcopy():
    k = boot()
    o = run(k, 'xcopy *.txt b:')
    got = files(k.pc.drives[1].img, 'B')
    ea, eb = entries(k.pc.drives[0].img), entries(k.pc.drives[1].img)
    check('XCOPY *.TXT B:: "Reading source file(s)...", the name of each, "1 File(s) copied", the bytes, exit code 0',
          'Reading source file(s)...' in o and 'A:\\ONE.TXT' in o and '        1 File(s) copied' in o
          and got == {'B:\\ONE.TXT': DATA[0]} and said(o, 'E0'), (o, sorted(got)))
    check('... the copy\'s date and time its source\'s', eb['ONE.TXT'][1:3] == ea['ONE.TXT'][1:3], (ea['ONE.TXT'], eb['ONE.TXT']))
    a = adisk([('HID.TXT', b'hidden'), ('RO.TXT', b'read-only')])
    img = bytearray(open(a, 'rb').read()); setattr_img(img, 'HID.TXT', 0x22); setattr_img(img, 'RO.TXT', 0x21); open(a, 'wb').write(img)
    k = boot(a)
    o = run(k, 'xcopy a:\\ b:\\all /s', ['d'])
    got = files(k.pc.drives[1].img, 'B'); eb = entries(k.pc.drives[1].img, 'ALL')
    check('XCOPY A:\\ B:\\ALL /S (D: a directory): every file, its tree made, the hidden one skipped, the read-only one a plain copy',
          got.get('B:\\ALL\\SUB\\DEEP\\Y.TXT') == DATA[3] and got.get('B:\\ALL\\SUB\\X.TXT') == DATA[2]
          and 'B:\\ALL\\HID.TXT' not in got and eb['RO.TXT'][0] == 0x20 and 'EMPTY' not in eb
          and 'HOLLOW' not in entries(k.pc.drives[1].img, 'ALL\\SUB') and said(o, 'E0'), (o, sorted(got)))
    o = run(k, 'xcopy a:\\sub b:\\e\\ /s /e')
    check('XCOPY A:\\SUB B:\\E\\ /S /E: a directory named, all of it; the empty one made too',
          'HOLLOW' in entries(k.pc.drives[1].img, 'E') and files(k.pc.drives[1].img, 'B').get('B:\\E\\DEEP\\Y.TXT') == DATA[3]
          and said(o, 'E0'), o)
    o = run(k, 'xcopy *.txt b:\\*.bak')
    got = files(k.pc.drives[1].img, 'B')
    check('XCOPY *.TXT B:\\*.BAK: the names from the wildcards', got.get('B:\\ONE.BAK') == DATA[0] and got.get('B:\\RO.BAK') == b'read-only'
          and said(o, 'E0'), (o, sorted(got)))
    # the F/D question answered from a file
    k = boot(adisk([('F.ANS', b'F'), ('D.ANS', b'D')]))
    o = run(k, 'xcopy sub\\x.txt b:\\one.txt < f.ans')
    o2 = run(k, 'xcopy sub\\x.txt b:\\two.txt < d.ans')
    got = files(k.pc.drives[1].img, 'B')
    check('the F/D question, answered from a file: F a file of that name, D a directory with the file in it',
          'Does B:\\ONE.TXT specify a file name' in o and got.get('B:\\ONE.TXT') == DATA[2]
          and got.get('B:\\TWO.TXT\\X.TXT') == DATA[2] and said(o, 'E0') and said(o2, 'E0'), (o, o2, sorted(got)))
    o = run(k, 'xcopy one.txt b:\\one.txt')
    check('... a file that is there already: no question, it is replaced', 'Does' not in o and
          files(k.pc.drives[1].img, 'B').get('B:\\ONE.TXT') == DATA[0] and said(o, 'E0'), o)

def t_switches():
    a = adisk([('NEW.TXT', b'new')])
    img = bytearray(open(a, 'rb').read())
    for n in ('ONE.TXT', 'TWO.DAT', 'SUB\\X.TXT'): setattr_img(img, n, 0x00)     # archive off: all but NEW.TXT and Y.TXT
    e = img.find(b'NEW     TXT'); struct.pack_into('<H', img, e + 24, (2026 - 1980) << 9 | 11 << 5 | 9)
    e = img.find(b'ONE     TXT'); struct.pack_into('<H', img, e + 24, (1991 - 1980) << 9 | 4 << 5 | 9)
    open(a, 'wb').write(img)
    k = boot(a)
    o = run(k, 'xcopy *.* b:\\a\\ /a /s')
    got = files(k.pc.drives[1].img, 'B')
    check('/A: only the files with the archive bit, which stays on', sorted(got) == ['B:\\A\\ATTRIB.COM', 'B:\\A\\LCMD.COM', 'B:\\A\\LODE.SYS',
          'B:\\A\\NEW.TXT', 'B:\\A\\SUB\\DEEP\\Y.TXT', 'B:\\A\\TREE.COM', 'B:\\A\\XCOPY.COM']
          and entries(k.pc.drives[0].img)['NEW.TXT'][0] == 0x20, (o, sorted(got)))
    o = run(k, 'xcopy *.txt b:\\m\\ /m')
    check('/M: the same, the archive bit then cleared on each source', sorted(files(k.pc.drives[1].img, 'B'))[-1:] == ['B:\\M\\NEW.TXT']
          and entries(k.pc.drives[0].img)['NEW.TXT'][0] == 0x00 and said(o, 'E0'), o)
    o = run(k, 'xcopy *.txt b:\\m2\\ /m')
    check('... again: nothing to copy, "File not found", exit code 1', 'File not found' in o and said(o, 'E1'), o)
    o = run(k, 'xcopy *.txt b:\\d\\ /d:11-09-2026')
    o2 = run(k, 'xcopy *.txt b:\\d2\\ /d:1-1-80')
    got = files(k.pc.drives[1].img, 'B')
    check('/D:11-09-2026: only files dated on or after it (NEW.TXT, that day; not ONE.TXT, 1991); /D:1-1-80 all',
          [f for f in got if f.startswith('B:\\D\\')] == ['B:\\D\\NEW.TXT'] and 'B:\\D2\\ONE.TXT' in got and 'B:\\D2\\NEW.TXT' in got, (o, o2))
    open(os.path.join(OUT, 'P.ANS'), 'wb').write(b'YN')
    k = boot(adisk([('P.ANS', b'NY')]))
    o = run(k, 'xcopy *.txt b:\\p\\ /p < p.ans')
    o = run(k, 'xcopy *.txt b:\\p\\ /p', ['n'])
    o2 = run(k, 'xcopy one.txt b:\\p\\ /p', ['y'])
    check('/P: "A:\\ONE.TXT (Y/N)?" for each, N leaves it, Y copies it', 'A:\\ONE.TXT (Y/N)?' in o and
          files(k.pc.drives[1].img, 'B').get('B:\\P\\ONE.TXT') == DATA[0] and said(o2, 'E0'), (o, o2))
    o = run(k, 'xcopy sub\\*.* b:\\v\\ /s /v')
    check('/V: each copy read back and compared: no error', files(k.pc.drives[1].img, 'B').get('B:\\V\\DEEP\\Y.TXT') == DATA[3]
          and 'Verify' not in o and said(o, 'E0'), o)
    k2 = boot(adisk([('K.BIN', bytes(range(256)) * 4)]))
    k2.pc.drives[1].bad = {33 + 1}                        # (B:'s first copy's second sector: written whole, it won't read back)
    o2 = run(k2, 'xcopy k.bin b: /v')
    check('/V: a copy that doesn\'t read back: "Verify error - B:\\K.BIN", exit code 5', 'Verify error - B:\\K.BIN' in o2
          and said(o2, 'E5'), o2)
    k2 = boot()
    k2.pc.drives[1].bad = {33 + 1}
    o2 = run(k2, 'xcopy one.txt b:\\')
    check('a write the disk refuses (a sector read for it fails): "Disk error writing - B:\\ONE.TXT" (not "disk full"), exit code 5',
          'Disk error writing - B:\\ONE.TXT' in o2 and 'Insufficient' not in o2 and said(o2, 'E5'), o2)
    o = run(k, 'xcopy one.txt b:\\w\\ /w', ['x'])
    check('/W: "Press any key to begin copying file(s)", then copies', 'Press any key to begin copying' in o
          and files(k.pc.drives[1].img, 'B').get('B:\\W\\ONE.TXT') == DATA[0] and said(o, 'E0'), o)
    o = run(k, 'xcopy one.txt b:\\w2\\ /w', [chr(3)])
    check('... Ctrl-C there: nothing copied, exit code 2', 'B:\\W2\\ONE.TXT' not in files(k.pc.drives[1].img, 'B') and said(o, 'E2'), o)

def t_refuse():
    k = boot()
    o = run(k, 'xcopy one.txt one.txt')
    check('a file onto itself: "File cannot be copied onto itself", exit code 4', 'File cannot be copied onto itself - A:\\ONE.TXT' in o
          and '0 File(s) copied' in o and said(o, 'E4'), o)
    run(k, 'cd sub')
    o = run(k, 'xcopy ..\\one.txt a:\\')
    check('... named another way (..\\ONE.TXT into A:\\): the same', 'onto itself' in o and said(o, 'E4'), o)
    run(k, 'cd \\')
    o = run(k, 'xcopy a:\\ a:\\sub\\all /s', ['d'])
    check('a tree into itself (/S): "Cannot perform a cyclic copy", exit code 4', 'cyclic copy' in o and said(o, 'E4'), o)
    for line, want, lv in (('xcopy', 'Required parameter missing', 4), ('xcopy one.txt b: /q', 'Invalid parameter', 4),
                           ('xcopy one.txt b: /d:13-01-90', 'Invalid parameter', 4), ('xcopy nosuch.* b:', 'File not found - NOSUCH.*', 1),
                           ('xcopy one.txt q:', 'Invalid drive', 4)):
        o = run(k, line)
        check('%s: "%s", exit code %d' % (line.upper(), want, lv), want in o and said(o, 'E%d' % lv), o)

def t_full():
    big = bytes((i * 13) & 0xFF for i in range(300000))
    b = mk('full.img', [('FILL.DAT', bytes(500000)), ('BIG.DAT', b'old contents\r\n')], size=720)
    k = boot(adisk([('BIG.DAT', big), ('SMALL.TXT', b'small')]), b)
    v0 = F.Volume(bytes(k.pc.drives[1].img), 0).free()
    o = run(k, 'xcopy *.dat b: /v')
    got = files(k.pc.drives[1].img, 'B')
    check('a full disk: "Insufficient disk space - B:\\BIG.DAT", exit code 5, the old B:\\BIG.DAT as it was',
          'Insufficient disk space - B:\\BIG.DAT' in o and got.get('B:\\BIG.DAT') == b'old contents\r\n' and said(o, 'E5'), o)
    v = F.Volume(bytes(k.pc.drives[1].img), 0)
    files_, probs = v.files()
    check('... nothing half-written left (no new file, its clusters free again), the disk consistent, the rest copied',
          probs == [] and sorted(got) == ['B:\\BIG.DAT', 'B:\\FILL.DAT', 'B:\\TWO.DAT'] and got['B:\\TWO.DAT'] == DATA[1], (sorted(got), probs))
    # bigger than memory: a piece at a time
    huge = bytes((i * 31 + i // 1000) & 0xFF for i in range(700000))
    k = boot(adisk(), mk('hb.img', [('HUGE.BIN', huge)]), mem_kb=256)
    o = run(k, 'xcopy b:\\huge.bin a:\\ /v', sim=200)
    check('a file bigger than memory (700 KB, 256 KB machine): copied through memory a piece at a time, verified',
          files(k.pc.drives[0].img).get('A:\\HUGE.BIN') == huge and 'Verify' not in o and said(o, 'E0'), o)

if __name__ == '__main__':
    t0 = time.time()
    names = sys.argv[1:]
    for t in (t_attrib, t_tree, t_xcopy, t_switches, t_refuse, t_full):
        if not names or t.__name__[2:] in names: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
