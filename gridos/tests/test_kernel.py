"""Grid-OS 0.2 kernel tests in pcemu: the DOS API suite, a FAT check of the
disk afterwards, TM5000G run and return with the built-in GPIB.

    python3 tests/test_kernel.py [name ...]
"""
import os, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, fatcheck, sim7210
OUT = os.environ.get('KOUT', os.path.join(__import__('tempfile').gettempdir(), 'gridos-kt'))
os.makedirs(OUT, exist_ok=True)
def _find(env, *cands):
    """A file from the environment variable, else the first that exists."""
    if os.environ.get(env): return os.environ[env]
    for c in cands:
        if os.path.exists(c): return c
    return cands[-1]

TM5000G = _find('TM5000G', os.path.join(GOS, '..', 'tools', 'TM5000G.EXE'), '/home/claude/TM5000/src/tm5000g.exe')

def build():
    subprocess.run([os.path.join(GOS, 'kbuild.sh')], check=True, stdout=subprocess.DEVNULL)
    for d, n in ((HERE, 'TESTDOS'), (HERE, 'UPPER'), (HERE, 'CACHETST'), (os.path.join(GOS, 'src'), 'GRIDCMD')):
        subprocess.run(['nasm', '-f', 'bin', '-o', os.path.join(d, n + '.COM'), os.path.join(d, n + '.ASM')], check=True)

def image(name, *files):
    return mkimg.build(os.path.join(OUT, name), [os.path.join(GOS, 'src', 'GRIDOS.SYS')] + list(files))

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)) if detail and not cond else ''))

def t_dosapi():
    img = image('api.img', os.path.join(HERE, 'TESTDOS.COM'))
    k = ktest.KPC(img); k.start()
    check('boots to the Executive', k.pc.mode() == 0x40 and 'TESTDOS.COM' in k.exec_list(), k.where())
    out = k.run_file('TESTDOS.COM', 120)
    print(out)
    check('TESTDOS: no failures', 'FAIL' not in out and ' 0 failed' in out, out[-200:])
    check('back in the Executive', k.pc.mode() == 0x40 and not k.crashed, k.where())
    check('Executive reports the exit', any('TESTDOS.COM ended' in l for l in k.band()), k.band())
    k.pc.drives[0].save(os.path.join(OUT, 'api_after.img'))
    probs, files = fatcheck.check(bytes(k.pc.drives[0].img))
    check('disk consistent afterwards', not probs, '; '.join(probs))
    check('test files cleaned up', set(files) == {'\\GRIDOS.SYS', '\\TESTDOS.COM'}, sorted(files))
    k.shot(os.path.join(OUT, 'api.png'))

def t_tm5000g():
    img = image('tm.img', 'TM5000G.EXE=' + TM5000G)
    chip = sim7210.NEC7210(sim7210.bus())
    k = ktest.KPC(img, chip=chip); k.start()
    check('built-in GPIB found the 7210', k.pc.rd(0x60, k.Y['gp_ok'], 1) == b'\x01')
    k.select('TM5000G.EXE'); k.key(ktest.ENTER, settle=False); k.settle(40)
    tty = ''.join(k.pc.tty)
    check('TM5000G sees GRIDGPIB on INT 60h', 'GRIDGPIB on INT 60h' in tty, tty[-300:])
    k.key(ktest.ENTER)
    check('TM5000G main menu', 'TM5000 CONTROL SYSTEM' in k.pc.text_screen())
    k.key('1'); k.key('A', settle=False); k.settle(60)
    scr = k.pc.text_screen()
    check('auto-detect finds FG5010, 8753D, DC5009', all(x in scr for x in ('FG5010', '8753D', 'DC5009')), scr)
    k.key('Y'); k.key(ktest.ENTER); k.key(ktest.ESC)
    check('modules configured', 'Active Modules: S0, S1' in k.pc.text_screen(), k.pc.text_screen())
    k.key('0', settle=False)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 10); k.settle()
    check('TM5000G returns to the Executive', any('TM5000G.EXE ended' in l for l in k.band()), k.band())
    k.shot(os.path.join(OUT, 'tm.png'))

class Shell:
    """GRIDCMD.COM (the command prompt) started from the Executive with CODE-C."""
    def __init__(s, k):
        s.k = k
        k.key(ktest.CODE_C)
    def run(s, cmd, *answers):
        k = s.k
        k.key('cls'); k.key(ktest.ENTER)
        k.key(cmd); k.key(ktest.ENTER)
        for a in answers: k.key(a); k.key(ktest.ENTER)
        lines = k.pc.text_screen().rstrip().split('\n')
        return '\n'.join(lines[1:])

def t_shell():
    img = image('sh.img', os.path.join(GOS, 'src', 'GRIDCMD.COM'), os.path.join(HERE, 'UPPER.COM'), 'GAMES\\')
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    check('CODE-C starts the shell', 'command shell' in k.pc.text_screen() and k.pc.mode() == 3, k.pc.text_screen())
    o = sh.run('dir')
    check('DIR lists the disk', all(x in o for x in ('Volume in drive A is GRIDOS', 'Directory of  A:\\', 'GRIDCMD  COM', 'GAMES           <DIR>', '4 File(s)', 'bytes free')), o)
    check('VER', 'Grid-OS version 0.3' in sh.run('ver'))
    check('bad command', 'Bad command or file name' in sh.run('nosuch'))
    check('bad drive', 'Invalid drive specification' in sh.run('b:'))
    sh.run('echo hello > a.txt')
    check('ECHO > file, TYPE', 'hello' in sh.run('type a.txt'))
    sh.run('echo world >> a.txt')
    o = sh.run('type a.txt')
    check('>> appends', 'hello' in o and 'world' in o, o)
    check('< and a program', 'HELLO' in sh.run('upper < a.txt'))
    o = sh.run('type a.txt | upper')
    check('pipe', 'HELLO' in o and 'WORLD' in o, o)
    sh.run('dir | upper > d.txt')
    o = sh.run('type d.txt')
    check('pipe into a file', 'VOLUME IN DRIVE A IS GRIDOS' in o and 'A        TXT' in o, o)
    check('pipe files cleaned up', 'PIPE' not in sh.run('dir'))
    sh.run('md sub')
    check('MD, CD', 'A:\\SUB>' in sh.run('cd sub'))
    o = sh.run('copy ..\\a.txt')
    check('COPY into the current dir', '1 File(s) copied' in o, o)
    sh.run('cd ..')
    o = sh.run('dir sub')
    check('DIR of a subdirectory', 'Directory of  A:\\SUB' in o and '.               <DIR>' in o and 'A        TXT' in o, o)
    sh.run('ren sub\\a.txt b.txt')
    check('REN', 'B        TXT' in sh.run('dir sub'))
    o = sh.run('copy sub\\*.txt *.bak')
    check('COPY with wildcards', '1 File(s) copied' in o and 'B        BAK' in sh.run('dir *.bak'), o)
    o = sh.run('del sub\\*.*', 'y')
    check('DEL *.* asks', 'Are you sure (Y/N)?' in o, o)
    check('RD', 'Invalid path' not in sh.run('rd sub') and 'SUB' not in sh.run('dir'))
    sh.run('echo y | del *.bak')
    check('DEL from a pipe', 'B        BAK' not in sh.run('dir'))
    sh.run('set foo=bar')
    check('SET', 'FOO=bar' in sh.run('set'))
    sh.run('set foo=')
    check('SET removes', 'FOO' not in sh.run('set'))
    sh.run('copy con x.bat', 'echo off', 'echo batch says %1', 'ver', '\x1a')
    o = sh.run('x hi')
    check('batch file, %1, ECHO OFF', 'batch says hi' in o and 'Grid-OS version 0.3' in o and 'echo batch' not in o, o)
    check('ECHO back on after the batch', 'A:\\>' in sh.run('rem'))
    sh.run('date 1-2-27')
    check('DATE', 'Sat 01-02-2027' in sh.run('date', ''))
    sh.run('time 10:11:12')
    check('TIME', 'Current time is 10:11' in sh.run('time', ''))
    sh.run('del a.txt'); sh.run('del d.txt'); sh.run('del x.bat')
    k.key('exit'); k.key(ktest.ENTER)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    check('EXIT returns to the Executive', k.pc.mode() == 0x40 and any('GRIDCMD.COM ended' in l for l in k.band()), k.band())
    probs, files = fatcheck.check(bytes(k.pc.drives[0].img))
    check('disk consistent after the shell', not probs, '; '.join(probs))
    check('shell files cleaned up', set(files) == {'\\GRIDOS.SYS', '\\GRIDCMD.COM', '\\UPPER.COM', '\\GAMES\\'}, sorted(files))

def t_disks():
    """Write protect (Retry, Fail), changing floppies, a drive with no
    change line."""
    import pcemu
    img = image('dk.img', os.path.join(GOS, 'src', 'GRIDCMD.COM'), 'SUB\\')
    img2 = image('dk2.img', os.path.join(HERE, 'UPPER.COM'))
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    k.pc.drives[0].wp = True
    o = sh.run('echo x > a.txt', 'r', 'f')
    check('write protect: Abort, Retry, Fail?', o.count('Write protect error writing drive A') == 2 and 'File creation error' in o, o)
    k.pc.drives[0].wp = False
    sh.run('echo x > a.txt')
    check('writes again once unprotected', 'A        TXT' in sh.run('dir'))
    sh.run('cd sub')
    k.pc.drives[0].no_changeline = True
    o = sh.run('dir')
    check('no change line: same disk kept, directory too', 'Directory of  A:\\SUB' in o and 'A:\\SUB>' in o, o)
    first = k.pc.drives[0]
    k.pc.drives[0] = pcemu.Floppy(img2); k.pc.drives[0].no_changeline = True
    o = sh.run('dir')
    check('no change line: another disk noticed', 'UPPER    COM' in o and 'A:\\>' in o, o)
    k.pc.drives[0] = first; first.no_changeline = False; first.changed = True
    o = sh.run('dir')
    check('change line: back to the first disk', 'A        TXT' in o and 'SUB' in o, o)
    probs, files = fatcheck.check(bytes(k.pc.drives[0].img))
    check('disk consistent', not probs, '; '.join(probs))

def t_permanent():
    """GRIDCMD /P is a first shell (as GRiD MS-DOS would start one): it runs
    AUTOEXEC.BAT and EXIT does nothing; without /P, EXIT ends it."""
    bat = os.path.join(OUT, 'AUTOEXEC.BAT')
    open(bat, 'wb').write(b'@echo off\r\necho autoexec ran\r\n')
    img = image('pm.img', os.path.join(GOS, 'src', 'GRIDCMD.COM'), bat)
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    psp0 = k.pc.u16(0x60, k.Y['cur_psp'])
    o = sh.run('gridcmd /p')
    check('/P runs AUTOEXEC.BAT', 'autoexec ran' in o, o)
    psp1 = k.pc.u16(0x60, k.Y['cur_psp'])
    sh.run('exit')
    check('/P: EXIT does nothing', k.pc.u16(0x60, k.Y['cur_psp']) == psp1 != psp0 and 'Grid-OS version' in sh.run('ver'))
    o = sh.run('gridcmd /c echo one shot')
    check('/C inside', 'one shot' in o and k.pc.u16(0x60, k.Y['cur_psp']) == psp1, o)

def t_cache():
    """The cylinder cache: CACHETST (random and in-order reads, writes into
    what is cached, reopening) checks every byte; a file read again after
    the floppy is changed for one laid out the same (with and without a
    change line); the help window, which borrows the cache's memory."""
    import pcemu
    data = os.path.join(OUT, 'DATA.TXT')
    def disk(name, word):
        open(data, 'wb').write(((word + ' ') * 700)[:2700].encode())
        return image(name, os.path.join(GOS, 'src', 'GRIDCMD.COM'), os.path.join(HERE, 'CACHETST.COM'), data)
    img1, img2 = disk('c1.img', 'ONE'), disk('c2.img', 'TWO')
    k = ktest.KPC(img1); k.start()
    out = k.run_file('CACHETST.COM', 900)
    check('CACHETST: every byte reads back as written', ' 0 errors' in out, out[-300:])
    probs, files = fatcheck.check(bytes(k.pc.drives[0].img))
    check('disk consistent after CACHETST', not probs and '\\CACHE_A.TST' not in files, '; '.join(probs) or sorted(files))
    log = fatcheck.read_files(bytes(k.pc.drives[0].img)).get('A:\\CACHETST.TXT', b'').decode('latin-1')
    check('CACHETST leaves its results in CACHETST.TXT', 'on Grid-OS' in log and ' 0 errors' in log, log[-300:])
    # the help window lends the cache's memory and gives it back
    rows = [k.u16('rowtab', 2 * y) for y in range(64, 64 + 232)]
    under = lambda: b''.join(k.pc.rd(0xB800, r + 16, 48) for r in rows)
    before = under()
    k.key(ktest.F1)
    lent = k.pc.rd(0x60, k.Y['tc_lock'], 1) == b'\x01' and k.pc.rd(0x60, k.Y['tc_drv'], 1) == b'\xff'
    k.key(ktest.ENTER)
    check('help window: borrows the cache, gives it back, screen restored',
          lent and k.pc.rd(0x60, k.Y['tc_lock'], 1) == b'\x00' and under() == before and 'CACHETST.COM' in k.exec_list())
    sh = Shell(k)
    o = sh.run('type data.txt')
    check('TYPE reads through the cache', 'ONE ONE' in o and k.pc.rd(0x60, k.Y['tc_drv'], 1) == b'\x00', o)
    first = k.pc.drives[0]
    k.pc.drives[0] = pcemu.Floppy(img2); k.pc.drives[0].changed = True
    o = sh.run('type data.txt')
    check('another floppy (change line): its file, not the cached one', 'TWO TWO' in o and 'ONE' not in o, o)
    k.pc.drives[0] = first; first.no_changeline = True
    o = sh.run('type data.txt')
    check('and back (no change line): the first one again', 'ONE ONE' in o and 'TWO' not in o, o)
    # a root directory with many old (deleted) entries before its end
    # marker, as on a floppy Windows has copied to a lot: a search reads it
    # in one pass, and the cached copy follows files coming and going
    img4 = image('c4.img', os.path.join(GOS, 'src', 'GRIDCMD.COM'))
    one = os.path.join(OUT, 'X.TXT'); open(one, 'w').write('x')
    names = ['F%03d.TXT' % i for i in range(120)]
    for n in names: subprocess.run(['mcopy', '-i', img4, one, '::' + n], check=True)
    subprocess.run(['mdel', '-i', img4] + ['::' + n for n in names[:-1]], check=True)
    k = ktest.KPC(img4); k.start()
    sh = Shell(k)
    sh.run('dir')
    n0 = len(k.pc.calls13)
    o = sh.run('dir')
    reads = len(k.pc.calls13) - n0
    sh.run('echo new > new.txt')
    o2 = sh.run('dir')
    sh.run('del f119.txt')
    o3 = sh.run('dir')
    probs, files = fatcheck.check(bytes(k.pc.drives[0].img))
    check('well-used root: DIR from the cache; new and deleted files show right',
          'F119     TXT' in o and reads == 0 and 'NEW      TXT' in o2 and 'F119' not in o3 and 'NEW' in o3 and not probs,
          '%d reads; %s' % (reads, '; '.join(probs) or o3[-300:]))
    # BENCH twice on a short root: the first run leaves its 20 deleted temp
    # files, so the root is three sectors long the second time.  They stay
    # in the directory buffers while files are read in part-sectors (those
    # use the data buffer), so the second run's directory test needs no disk
    img5 = image('c5.img', os.path.join(GOS, 'src', 'GRIDCMD.COM'), os.path.join(GOS, 'bench', 'BENCH.COM'))
    for i in range(13): subprocess.run(['mcopy', '-i', img5, one, '::F%02d.TXT' % i], check=True)
    calls = []
    for run in (1, 2):                  # (restarting in between)
        k = ktest.KPC(img5); k.start()
        k.run_file('BENCH.COM', 900)
        k.pc.drives[0].save()
        m = {b: n for b, us, n, secs in k.pc.marks}
        calls.append(m[13] - m[12] if 12 in m and 13 in m else -1)
    check('BENCH twice: the second directory test reads no sectors (root stays buffered)',
          calls == [0, 0], 'BIOS calls in the directory test: %s' % calls)
    # an unreadable sector part way through a file: the read-ahead that
    # runs into it gives up quietly (once), the file reads right up to it,
    # then the usual Data error
    big = os.path.join(OUT, 'BIG.TXT')
    open(big, 'wb').write(''.join('line %04d of the bad-sector file\r\n' % i for i in range(600)).encode())
    img3 = image('c3.img', os.path.join(GOS, 'src', 'GRIDCMD.COM'), big)
    raw = open(img3, 'rb').read()
    cl = [struct.unpack_from('<H', raw, 19 * 512 + 32 * i + 26)[0] for i in range(16)
          if raw[19 * 512 + 32 * i:19 * 512 + 32 * i + 11] == b'BIG     TXT'][0]
    k = ktest.KPC(img3); k.start()
    k.pc.drives[0].bad = {33 + cl - 2 + 30}         # the file's 31st sector
    sh = Shell(k)
    o = sh.run('type big.txt', 'f')
    good = all('line %04d of the bad-sector file' % i in o for i in range(440, 451))
    check('bad sector: the file reads up to it, then Data error, read-ahead gave up once',
          good and 'Data error reading drive A' in o and 'line 0460' not in o and k.pc.calls_bad <= 9,
          '%d failed reads; %s' % (k.pc.calls_bad, o[-400:]))
    # a weak drive head (the 1520's side 0, inner tracks): a read of several
    # sectors on these tracks always fails with a CRC error, each sector on
    # its own reads fine.  The kernel falls back to sector-by-sector: the
    # file copies whole, no Data error
    img4 = image('c4.img', os.path.join(GOS, 'src', 'GRIDCMD.COM'), big)
    raw = open(img4, 'rb').read()
    cl = [struct.unpack_from('<H', raw, 19 * 512 + 32 * i + 26)[0] for i in range(16)
          if raw[19 * 512 + 32 * i:19 * 512 + 32 * i + 11] == b'BIG     TXT'][0]
    first = 33 + cl - 2
    weak = {(first + 10) // 18, (first + 10) // 18 + 1}     # two tracks inside the file
    seen = {'multi': 0, 'single': 0}
    o13 = pcemu.PC.int13
    def weak13(s):
        if s.r('ah') == 2 and (s.r('dx') & 0xFF) == 0:
            cx, dx = s.r('cx'), s.r('dx')
            trk = (cx >> 8) * 2 + (dx >> 8)
            if trk in weak:
                if s.r('al') > 1:
                    seen['multi'] += 1
                    s.w('ax', 0x1000); s.cf(1); return
                seen['single'] += 1
        return o13(s)
    pcemu.PC.int13 = weak13
    try:
        k = ktest.KPC(img4); k.start()
        sh = Shell(k)
        o = sh.run('copy big.txt b2.txt')
        k.pc.drives[0].save()
    finally:
        pcemu.PC.int13 = o13
    files = fatcheck.read_files(open(img4, 'rb').read())
    check('weak tracks (runs fail, single sectors read): the kernel reads them sector by sector, the file copies whole',
          files.get('A:\\B2.TXT') == open(big, 'rb').read() and 'error' not in o.lower()
          and seen['multi'] > 0 and seen['single'] >= 18, (seen, o[-300:]))

TESTS = [t_dosapi, t_tm5000g, t_shell, t_disks, t_permanent, t_cache]
if __name__ == '__main__':
    build()
    want = sys.argv[1:]
    for t in TESTS:
        if want and t.__name__[2:] not in want: continue
        print('==', t.__name__[2:])
        t0 = time.time(); t(); print('   (%.1f s)' % (time.time() - t0))
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s' % (len(results), len(bad), (': ' + ', '.join(bad)) if bad else ''))
    sys.exit(1 if bad else 0)
