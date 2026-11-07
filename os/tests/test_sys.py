"""SYS.COM in the emulator, from the command prompt: a floppy with files
made to start Lodestone (its files kept, the boot sector BOOT.BIN's code
with the disk's own BPB, the system as on the start-up disk; it then
starts), an old system replaced, one drive (the disk changed at "Insert
the disk"), the source given, too little room (nothing written), a
write-protected disk, a disk changed before the boot sector goes on, no
LODE.SYS to copy, multitasking, and the drives and disks it refuses.

    python3 tests/test_sys.py [name ...]
"""
import os, struct, sys, tempfile, time
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
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

def said(o, line): return any(l.strip() == line for l in o.split('\n'))
def out(k): return ''.join(k.pc.tty).replace('\r', '')

def data_disk(name='b.img', files=None, size=1440):
    """a floppy of someone's files (mformat's boot sector, not Lodestone's)"""
    p = os.path.join(OUT, name)
    if os.path.exists(p): os.remove(p)
    import subprocess
    subprocess.run(['mformat', '-C', '-f', str(size), '-v', 'MYDATA', '-i', p, '::'], check=True)
    for n, data in (files or [('NOTES.TXT', b'my notes\r\n' * 50), ('WORK.DAT', bytes(range(256)) * 20)]):
        q = os.path.join(OUT, 'x'); open(q, 'wb').write(data)
        subprocess.run(['mcopy', '-i', p, q, '::' + n], check=True)
    return p

def boot(b=None, files=SYSF + ('SYS.COM',), **kw):
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(SRC, f) for f in files])
    k = ktest.KPC(img, b, **kw)
    k.start(); k.code_p()
    return k

def run(k, line, keys=(), sim=60):
    """line at the prompt -> what it printed, and E0/E1/E3: its exit code"""
    k.pc.tty.clear()
    k.key(line); k.key(ktest.ENTER, settle=False)
    for key in keys:
        k.pc.run_until(lambda: 'strike ENTER' in out(k), 20)
        k.key(key, settle=False)
    k.settle(sim)
    o = out(k)
    for n in (1, 2, 3):
        k.key('if errorlevel %d echo L%d' % (n, n)); k.key(ktest.ENTER)
    lv = max([n for n in (1, 2, 3) if said(out(k)[len(o):], 'L%d' % n)] or [0])
    return o + '\nE%d\n' % lv

def files_of(img): return fatcheck.read_files(img)

def want_sys():
    return {'A:\\' + n: open(os.path.join(SRC, n), 'rb').read() for n in SYSF}

def t_basic():
    b = data_disk()
    k = boot(b)
    raw = bytes(k.pc.drives[1].img)
    o = run(k, 'sys b:')
    img = bytes(k.pc.drives[1].img)
    got = files_of(img)
    check('SYS B:: "System transferred", exit code 0', said(o, 'System transferred') and said(o, 'E0'), o)
    check('... the four system files as on the start-up disk, the disk\'s own files kept, CHKDSK-clean',
          all(got.get(n) == v for n, v in want_sys().items()) and got.get('A:\\NOTES.TXT') == b'my notes\r\n' * 50
          and got.get('A:\\WORK.DAT') == bytes(range(256)) * 20 and fatcheck.check(img)[0] == [], (sorted(got), fatcheck.check(img)[0]))
    check('... the boot sector: BOOT.BIN\'s code, the disk\'s own BPB (0Bh-3Dh: its serial and label kept)',
          img[0:11] == BOOT[0:11] and img[0x3E:512] == BOOT[0x3E:512] and img[0x0B:0x3E] == raw[0x0B:0x3E], img[:64].hex())
    o = run(k, 'dir b:')
    check('... the kernel goes on with it (DIR B:: its label, the files)', 'MYDATA' in o and 'NOTES    TXT' in o and 'LODE     SYS' in o, o)
    p = os.path.join(OUT, 'started.img'); open(p, 'wb').write(img)
    k2 = ktest.KPC(p); k2.start()
    check('... and the disk starts Lodestone: the Executive, its files listed', 'NOTES.TXT' in k2.exec_list()
          and not k2.crashed, k2.exec_list())

def t_again():
    # a disk with an older (other) system, LODE.SYS read-only and hidden: replaced
    b = data_disk('b2.img', [('LODE.SYS', b'an old kernel\r\n' * 3000), ('LCMD.COM', b'old shell')])
    import subprocess
    subprocess.run(['mattrib', '-i', b, '+r', '+h', '::LODE.SYS'], check=True)
    k = boot(b)
    o = run(k, 'sys b:')
    img = bytes(k.pc.drives[1].img)
    got = files_of(img)
    check('an older system there (LODE.SYS read-only and hidden): replaced, nothing else left behind',
          said(o, 'E0') and all(got.get(n) == v for n, v in want_sys().items()) and 'A:\\LODESYS.$$$' not in got
          and fatcheck.check(img)[0] == [], (o, sorted(got)))
    o = run(k, 'sys b:')
    check('... and SYS again over it: the same', said(o, 'E0') and files_of(bytes(k.pc.drives[1].img)) == got, o)

def t_one_drive():
    k = boot()
    target = pcemu.Floppy(open(data_disk('t.img'), 'rb').read())
    k.pc.tty.clear()
    k.key('sys a:'); k.key(ktest.ENTER, settle=False)
    ok = k.pc.run_until(lambda: 'strike ENTER' in out(k), 20)
    start = k.pc.drives[0]
    target.changed = True; k.pc.drives[0] = target       # the start-up disk out, the one to make start in
    k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: 'System transferred' in out(k) or 'nnot' in out(k), 60)
    o = out(k)
    start.changed = True; k.pc.drives[0] = start
    k.settle(20)
    got = files_of(bytes(target.img))
    check('SYS A: with one drive: the system read first, "Insert the disk", the new disk in A: made to start',
          'Insert the disk' in o and 'System transferred' in o and all(got.get(n) == v for n, v in want_sys().items())
          and bytes(target.img)[0x3E:512] == BOOT[0x3E:512], (o, sorted(got)))
    k = boot()
    o = run(k, 'sys a:', keys=(chr(27),))
    check('... Esc at "Insert the disk": nothing written, exit code 3', said(o, 'E3') and 'transferred' not in o, o)

def t_source():
    b = data_disk()
    k = boot(b, files=('LODE.SYS', 'LCMD.COM', 'SYS.COM'))
    o = run(k, 'sys b:')                                  # from A:, which has LODE.SYS and LCMD.COM only
    got = files_of(bytes(k.pc.drives[1].img))
    check('SYS B: with only LODE.SYS and LCMD.COM on the start-up disk: those two', said(o, 'E0')
          and 'A:\\LODE.SYS' in got and 'A:\\LCMD.COM' in got and 'A:\\LODEMT.SYS' not in got, (o, sorted(got)))
    k = boot(data_disk('t2.img'), files=('LODE.SYS', 'LCMD.COM', 'SYS.COM'))
    o = run(k, 'sys a: b:')
    check('SYS A: B:: the source given (here, A: onto B:)', said(o, 'E0') and 'A:\\LODE.SYS' in files_of(bytes(k.pc.drives[1].img)), o)
    k = boot(data_disk('t3.img'), files=('LCMD.COM', 'SYS.COM', 'LODE.SYS'))
    o = run(k, 'sys b: a:')
    check('SYS B: A:: B: (no LODE.SYS there) onto A:: "Cannot find the system", exit code 1, nothing written',
          'Cannot find the system' in o and said(o, 'E1'), o)

def t_room():
    b = data_disk('full.img', [('BIG%d.DAT' % i, bytes([i]) * 200000) for i in range(7)])
    k = boot(b)
    raw = bytes(k.pc.drives[1].img)
    o = run(k, 'sys b:')
    check('too little room for the system: "No room", exit code 1, nothing written',
          'No room for the system' in o and said(o, 'E1') and bytes(k.pc.drives[1].img) == raw, o)
    b = data_disk('wp.img')
    k = boot(b)
    k.pc.drives[1].wp = True; raw = bytes(k.pc.drives[1].img)
    o = run(k, 'sys b:')
    check('a write-protected disk: "Write protect error", exit code 1, nothing written',
          'Write protect error' in o and said(o, 'E1') and bytes(k.pc.drives[1].img) == raw, o)

def t_changed():
  for how in ('another disk', 'a copy of it as it was (the same boot sector, serial and all)'):
    b = data_disk()
    k = boot(b)
    if how == 'another disk':
        other = pcemu.Floppy(open(data_disk('o.img', [('OTHER.TXT', b'not mine')]), 'rb').read())
    else:
        other = pcemu.Floppy(bytes(k.pc.drives[1].img))
    raw2 = bytes(other.img)
    seen = []
    _o = pcemu.PC.int13
    def hook(s):
        root = bytes(s.drives[1].img[19 * 512:33 * 512])  # (the change line asked once the files are on: SYS's,
        if s.r('ah') == 0x16 and not seen and b'LCMD    COM' in root and b'LODESYS $$$' not in root:   #  before the boot sector)
            seen.append(1); other.changed = True; s.drives[1] = other
        return _o(s)
    pcemu.PC.int13 = hook
    try:
        o = run(k, 'sys b:')
    finally:
        pcemu.PC.int13 = _o
    check('the disk changed before its boot sector goes on (%s): "The disk was changed", its boot sector untouched' % how,
          'The disk was changed' in o and said(o, 'E1') and bytes(other.img)[:512] == raw2[:512], o)

def t_refused():
    k = boot(data_disk())
    for line, want in (('sys', 'which drive'), ('sys c:', 'floppies only'), ('sys m:', 'floppies only'),
                       ('sys r:', 'floppies only'), ('sys b: /x', 'Invalid parameter'), ('sys a: b: a:', 'Invalid parameter')):
        o = run(k, line)
        check('%s: "%s", exit code 1' % (line.upper(), want), want in o and said(o, 'E1'), o)
    k = boot()
    o = run(k, 'sys b:')
    check('SYS B: with no drive B:: "Invalid drive specification"', 'Invalid drive' in o and said(o, 'E1'), o)
    b = os.path.join(OUT, 'blank.img'); open(b, 'wb').write(bytes(1474560))
    k = boot(b)
    o = run(k, 'sys b:')
    check('a disk that is no FAT floppy: "Not a floppy Lodestone can start from", nothing written',
          'Not a floppy Lodestone can start from' in o and said(o, 'E1') and bytes(k.pc.drives[1].img) == bytes(1474560), o)

def t_mt():
    import test_mt as M
    from test_kernel import Shell
    b = data_disk('mt.img')
    k = M.boot('mtsys.img', b'MULTITASK=1\r\n', 88, os.path.join(SRC, 'SYS.COM'), b=b)
    raw = bytes(k.pc.drives[1].img)
    sh = Shell(k)
    sh.run('start /w sys.com b: > o.txt'); k.run_for(10)
    o = sh.run('type o.txt')
    check('with multitasking, SYS run as a task: refused ("other tasks are running"), nothing written',
          'other tasks are running' in o and bytes(k.pc.drives[1].img) == raw, o)

def t_review():
    # the review panel's findings, each held to
    import fat16img as F
    BOOT = open(os.path.join(SRC, 'BOOT.BIN'), 'rb').read()
    f = F.Fat(2880, 1, 0, False, rootents=224, spt=18, heads=2)
    items = [('LODE.SYS', 0x20, b'old kernel' * 100), ('LCMD.COM', 0x20, b'old shell')] + [('F%03d.TXT' % i, 0x20, b'') for i in range(221)]
    f.finish(f.tree(items))
    img = bytearray(f.img); img[0:11] = BOOT[0:11]; img[0x3E:512] = BOOT[0x3E:512]   # an old Lodestone disk, its root nearly full
    p = os.path.join(OUT, 'rootf.img'); open(p, 'wb').write(img)
    k = boot(p)
    raw = bytes(k.pc.drives[1].img)
    o = run(k, 'sys b:')
    check('a root with too few free entries (one, where LODEMT.SYS and LODE.PIC need their own and a rename one more): '
          'refused before anything is written', 'No room for the system in the root directory' in o and said(o, 'E1')
          and bytes(k.pc.drives[1].img) == raw, o)

if __name__ == '__main__':
    t0 = time.time()
    names = sys.argv[1:]
    for t in (t_basic, t_again, t_one_drive, t_source, t_room, t_changed, t_refused, t_mt, t_review):
        if not names or t.__name__[2:] in names: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
