"""Grid-OS 0.2 kernel tests in pcemu: the DOS API suite, a FAT check of the
disk afterwards, TM5000G run and return with the built-in GPIB.

    python3 tests/test_kernel.py [name ...]
"""
import os, re, struct, subprocess, sys, time
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
    for d, n in ((HERE, 'TESTDOS'), (HERE, 'UPPER'), (HERE, 'CACHETST'), (HERE, 'EMSTEST'), (HERE, 'MEMSZ'),
                 (os.path.join(GOS, 'src'), 'GRIDCMD')):
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
    """GRIDCMD.COM (the command prompt) started from the Executive with CODE-P."""
    def __init__(s, k):
        s.k = k
        k.key(ktest.CODE_P)
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
    check('CODE-P starts the shell', 'command shell' in k.pc.text_screen() and k.pc.mode() == 3, k.pc.text_screen())
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

def mcbs(k):
    """The arena: (segment, type, owner, size, name) of each block."""
    seg, out = first_mcb(k), []
    while True:
        t, own, sz, nm = k.pc.rd(seg, 0, 1)[0], k.pc.u16(seg, 1), k.pc.u16(seg, 3), k.pc.rd(seg, 8, 2)
        out.append((seg, chr(t), own, sz, nm))
        if t != ord('M'): return out
        seg += sz + 1

def t_cache(ems=0):
    """The cylinder cache: CACHETST (random and in-order reads, writes into
    what is cached, reopening, reads across 64 KB) checks every byte; a
    file read again after the floppy is changed for one laid out the same
    (with and without a change line); the help window's save-under, in the
    cache's memory (with the cache in EMS, a block of its own)."""
    import pcemu
    tag = ' (EMS)' if ems else ''
    data = os.path.join(OUT, 'DATA.TXT')
    def disk(name, word):
        open(data, 'wb').write(((word + ' ') * 700)[:2700].encode())
        return image(name, os.path.join(GOS, 'src', 'GRIDCMD.COM'), os.path.join(HERE, 'CACHETST.COM'), data)
    img1, img2 = disk('c1.img', 'ONE'), disk('c2.img', 'TWO')
    k = ktest.KPC(img1, ems_pages=ems); k.start()
    out = k.run_file('CACHETST.COM', 900)
    frame = list(k.pc.ems_reg) if ems else None     # (as CACHETST left the windows)
    check('CACHETST: every byte reads back as written' + tag, ' 0 errors' in out, out[-300:])
    if ems:
        m = re.search(r'the frame as we left it; (\d+) reads and (\d+) writes', out)
        check('CACHETST: its 4 EMS pages stay in the 4 windows, as it left them, while the cache uses the frame '
              '(%s reads and %s writes through the frame)' % (m.groups() if m else ('?', '?')),
              'EMS: 4 pages of ours' in out and m and int(m.group(1)) > 10 and int(m.group(2)) > 10, out[-400:])
    probs, files = fatcheck.check(bytes(k.pc.drives[0].img))
    check('disk consistent after CACHETST' + tag, not probs and '\\CACHE_A.TST' not in files, '; '.join(probs) or sorted(files))
    log = fatcheck.read_files(bytes(k.pc.drives[0].img)).get('A:\\CACHETST.TXT', b'').decode('latin-1')
    check('CACHETST leaves its results in CACHETST.TXT' + tag, 'on Grid-OS' in log and ' 0 errors' in log, log[-300:])
    # the help window's save-under: the cache's memory, lent and given back;
    # with the cache in EMS, a block of its own while it is open (the cache
    # stays as it is)
    rows = [k.u16('rowtab', 2 * y) for y in range(64, 64 + 232)]
    under = lambda: b''.join(k.pc.rd(0xB800, r + 16, 48) for r in rows)
    sublocks = lambda: [b for b in mcbs(k) if b[2] == 8 and b[3] == TC_PARAS]
    before, drv0, n0 = under(), k.pc.rd(0x60, k.Y['tc_drv'], 1), len(sublocks())
    k.key(ktest.F1)
    if ems:
        lent = k.pc.rd(0x60, k.Y['tc_lock'], 1) == b'\x00' and k.pc.rd(0x60, k.Y['tc_drv'], 1) == drv0 \
            and len(sublocks()) == n0 + 1
    else:
        lent = k.pc.rd(0x60, k.Y['tc_lock'], 1) == b'\x01' and k.pc.rd(0x60, k.Y['tc_drv'], 1) == b'\xff'
    k.key(ktest.ENTER)
    check('help window: ' + ('its save-under in a block of its own, the cache kept; the block freed after'
                             if ems else 'borrows the cache, gives it back') + ', screen restored',
          lent and k.pc.rd(0x60, k.Y['tc_lock'], 1) == b'\x00' and under() == before and len(sublocks()) == n0
          and 'CACHETST.COM' in k.exec_list(), (lent, len(sublocks()), n0))
    sh = Shell(k)
    o = sh.run('type data.txt')
    check('TYPE reads through the cache' + tag, 'ONE ONE' in o and k.pc.rd(0x60, k.Y['tc_drv'], 1) == b'\x00', o)
    if ems:
        check('the frame as CACHETST left it, after the help window and TYPE', k.pc.ems_reg == frame, (frame, k.pc.ems_reg))
    first = k.pc.drives[0]
    k.pc.drives[0] = pcemu.Floppy(img2); k.pc.drives[0].changed = True
    o = sh.run('type data.txt')
    check('another floppy (change line): its file, not the cached one' + tag, 'TWO TWO' in o and 'ONE' not in o, o)
    k.pc.drives[0] = first; first.no_changeline = True
    o = sh.run('type data.txt')
    check('and back (no change line): the first one again' + tag, 'ONE ONE' in o and 'TWO' not in o, o)
    # a root directory with many old (deleted) entries before its end
    # marker, as on a floppy Windows has copied to a lot: a search reads it
    # in one pass, and the cached copy follows files coming and going
    img4 = image('c4.img', os.path.join(GOS, 'src', 'GRIDCMD.COM'))
    one = os.path.join(OUT, 'X.TXT'); open(one, 'w').write('x')
    names = ['F%03d.TXT' % i for i in range(120)]
    for n in names: subprocess.run(['mcopy', '-i', img4, one, '::' + n], check=True)
    subprocess.run(['mdel', '-i', img4] + ['::' + n for n in names[:-1]], check=True)
    k = ktest.KPC(img4, ems_pages=ems); k.start()
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
    check('well-used root: DIR from the cache; new and deleted files show right' + tag,
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
        k = ktest.KPC(img5, ems_pages=ems); k.start()
        k.run_file('BENCH.COM', 900)
        k.pc.drives[0].save()
        m = {b: n for b, us, n, secs in k.pc.marks}
        calls.append(m[13] - m[12] if 12 in m and 13 in m else -1)
    check('BENCH twice: the second directory test reads no sectors (root stays buffered)' + tag,
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
    k = ktest.KPC(img3, ems_pages=ems); k.start()
    k.pc.drives[0].bad = {33 + cl - 2 + 30}         # the file's 31st sector
    sh = Shell(k)
    o = sh.run('type big.txt', 'f')
    good = all('line %04d of the bad-sector file' % i in o for i in range(440, 451))
    check('bad sector: the file reads up to it, then Data error, read-ahead gave up once' + tag,
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
        k = ktest.KPC(img4, ems_pages=ems); k.start()
        sh = Shell(k)
        o = sh.run('copy big.txt b2.txt')
        k.pc.drives[0].save()
    finally:
        pcemu.PC.int13 = o13
    files = fatcheck.read_files(open(img4, 'rb').read())
    check('weak tracks (runs fail, single sectors read): the kernel reads them sector by sector, the file copies whole' + tag,
          files.get('A:\\B2.TXT') == open(big, 'rb').read() and 'error' not in o.lower()
          and seen['multi'] > 0 and seen['single'] >= 18, (seen, o[-300:]))
    if not ems: return
    # A bad sector where the cache reads a piece across 64 KB itself
    # (CACHETST's read buffer is across one), with the cache's pages in the
    # frame: that read fails quietly (no INT 24h with the pages in), then
    # dio reads the piece itself, fails too, and INT 24h comes with the
    # program's own pages back in the frame - CACHETST's handler looks at
    # them, and so does this test at crit_disk.  Retry reads it right.
    seen = {'bad': set(), 'fill': 0, 'direct': 0, 'crit': []}
    spec, crit, tcpg = k.Y['io_spec'], k.Y['crit_disk'], k.Y['ems_tcpg']
    def fail13(s):
        if s.r('ah') == 2 and (s.r('dx') & 0xFF) == 0 and not seen['crit']:
            cx, d = s.r('cx'), s.drives[0]
            c, sct, h = (cx >> 8) | ((cx & 0xC0) << 2), cx & 63, s.r('dh')
            lba = (c * d.heads + h) * d.spt + sct - 1
            run = set(range(lba, lba + s.r('al')))
            if not seen['bad'] and 0xE0000 <= s.r('es') * 16 + s.r('bx') < 0xF0000 \
                    and set(s.ems_reg) & set(s.rd(0x60, tcpg, 2)) and s.rd(0x60, spec, 1) == b'\0':
                seen['bad'] = run           # the cache's own read of a piece
            if run & seen['bad']:
                seen['fill' if set(s.ems_reg) & set(s.rd(0x60, tcpg, 2)) else 'direct'] += 1
                s.w('ax', 0x1000); s.cf(1); return
        return o13(s)
    def at_crit(pc):
        if pc.r('cs') == 0x60 and pc.r('ip') == crit:
            seen['crit'].append(list(pc.ems_reg))
    pcemu.PC.int13 = fail13
    try:
        k = ktest.KPC(disk('c6.img', 'SIX'), ems_pages=ems); k.start()
        k.hooks.append(at_crit)
        out = k.run_file('CACHETST.COM', 900)
    finally:
        pcemu.PC.int13 = o13
    cache = set(k.rd('ems_tcpg', 2))
    regs = seen['crit'][0] if seen['crit'] else []
    check('a bad sector in a cache fill: that read fails quietly, dio\'s own fails too, INT 24h comes with the '
          'program\'s 4 pages in the frame; Retry reads it, 0 errors',
          seen['fill'] > 0 and seen['direct'] > 0 and len(seen['crit']) == 1 and len(regs) == 4
          and all(r & 0x80 and r not in cache for r in regs) and 'Disk errors retried (INT 24h): 1' in out
          and ' 0 errors' in out, (seen, sorted(cache), out[-400:]))

def t_cache_ems():
    """The same with EMS: the cache's memory is two EMS pages, in the frame
    only while it is used."""
    t_cache(88)

EMS_BOARD = '''cpu 286
org 7C00h
        mov     ax, 0E000h
        mov     es, ax
        mov     dx, 0258h               ; window 0 and window 1: raw page 5
        mov     al, 85h
        out     dx, al
        mov     dx, 4258h
        out     dx, al
        mov     word [es:0], 1234h      ; written through window 0 ...
        mov     si, [es:4000h]          ; ... read through window 1 (same block)
        mov     al, 0DDh                ; window 3: raw 93 (88 + 5: absent, or
        mov     dx, 0C258h              ;  page 5 again on an aliasing board)
        out     dx, al
        mov     bp, [es:0C000h]
        xor     al, al                  ; window 1 off: reads FFh, keeps nothing
        mov     dx, 4258h
        out     dx, al
        mov     bx, [es:4000h]
        mov     word [es:4000h], 5555h
        mov     cx, [es:4000h]
        mov     dx, 0258h               ; the register reads back
        in      al, dx
        mov     di, ax
        hlt
'''

def t_emsboard():
    """pcemu's EMS board (for the kernel's EMS tests): windows, aliasing, off."""
    src = os.path.join(OUT, 'emsboard.asm'); bin_ = os.path.join(OUT, 'emsboard.bin')
    open(src, 'w').write(EMS_BOARD)
    subprocess.run(['nasm', '-f', 'bin', '-o', bin_, src], check=True)
    for alias in (False, True):
        pc = ktest.pcemu.PC(ems_pages=88, ems_alias=alias)
        pc.wr(0, 0x7C00, open(bin_, 'rb').read())
        pc.w('cs', 0); pc.w('ip', 0x7C00); pc.w('ss', 0); pc.w('sp', 0x7C00); pc.w('flags', 2)
        pc.run(1000)
        tag = ' (aliasing board)' if alias else ''
        check('EMS board: written through one window, read through another' + tag,
              pc.r('si') == 0x1234 and pc.ems_read(5, 0, 2) == b'\x34\x12', hex(pc.r('si')))
        check('EMS board: raw page 93 is ' + ('page 5 again' if alias else 'absent (FFh)') + tag,
              pc.r('bp') == (0x1234 if alias else 0xFFFF), hex(pc.r('bp')))
        check('EMS board: a window that is off reads FFh and keeps nothing' + tag,
              pc.r('bx') == 0xFFFF and pc.r('cx') == 0xFFFF, (hex(pc.r('bx')), hex(pc.r('cx'))))
        check('EMS board: page registers read back' + tag, pc.r('di') & 0xFF == 0x85, hex(pc.r('di')))
    pc = ktest.pcemu.PC()
    pc.w('ax', 0xE442); pc.w('dx', 0xFF); pc.int15()
    check('no EMS board: INT 15h E442h unanswered', pc.r('flags') & 1, hex(pc.r('ax')))

EMS_BUDGET = 1968       # bytes the EMS manager may keep (with 88 pages): 123 paragraphs
                        # (1808 before the disk cache moved into EMS: 159 bytes for that)
TC_PARAS = 36 * 32      # the disk cache's memory, paragraphs (KDISK.INC)
def ems_npg(k): return k.rd('ems42', 1, 1)[0]     # (patched into 42h's MOV AL)
def ems_used(k): return k.rd('ems_h', 1, 2)[0]    # (handle 0's owner byte)

def first_mcb(k): return k.u16('first_mcb')

def t_noems():
    """No EMS: not a byte of the EMS manager stays, INT 67h says 84h."""
    img = image('noems.img', os.path.join(HERE, 'EMSTEST.COM'))
    k = ktest.KPC(img); k.start()
    Y = k.Y
    check('no EMS: the arena starts right after the BSS (as before the EMS manager)',
          first_mcb(k) == 0x60 + (Y['bss_end'] + 15) // 16, hex(first_mcb(k)))
    check('no EMS: INT 67h is the kernel\'s stub, no EMMXXXX0 at its segment:000Ah',
          k.pc.u16(0, 0x67 * 4) == Y['int67'] and k.pc.rd(0x60, 0x0A, 8) != b'EMMXXXX0',
          (hex(k.pc.u16(0, 0x67 * 4)), k.pc.rd(0x60, 0x0A, 8)))
    sc = [b for b in mcbs(k) if b[4] == b'SC']
    check('no EMS: the disk cache is the "SC" block at the top of memory, as before',
          len(sc) == 1 and sc[0][1:4] == ('Z', 8, TC_PARAS) and k.u16('tc_seg') == sc[0][0] + 1, sc)
    out = k.run_file('EMSTEST.COM', 30)
    print(out)
    check('no EMS: EMSTEST finds none, no EMMXXXX0 device', 'no EMS manager' in out and ' 0 failed' in out
          and 'FAIL' not in out, out[-300:])

def memsz(k):
    m = re.search(r'([\d.]+) KB for programs', k.run_file('MEMSZ.COM', 30))
    return float(m.group(1)) if m else 0

def t_ems():
    """The kernel's EMS manager on an 88-page board (the 1520's 1408 KB),
    with the disk cache in two of its pages."""
    img = image('ems.img', os.path.join(HERE, 'EMSTEST.COM'), os.path.join(HERE, 'TESTDOS.COM'),
                os.path.join(HERE, 'MEMSZ.COM'))
    k = ktest.KPC(img); k.start()
    kb0 = memsz(k)                      # (the same disk without EMS)
    k = ktest.KPC(img, ems_pages=88); k.start()
    Y = k.Y
    npg = ems_npg(k)
    ltab = k.rd('ems_ltab', 88)
    check('EMS: 88 pages found: the last two are the disk cache\'s, 86 for programs',
          npg == 86 and k.rd('ems_tcpg', 2) == ltab[86:88] and len(set(ltab)) == 88, (npg, k.rd('ems_tcpg', 2), ltab[84:]))
    blocks = mcbs(k)
    check('EMS: no "SC" block, the arena runs to the top of memory', not [b for b in blocks if b[4] == b'SC']
          and blocks[-1][1] == 'Z' and blocks[-1][0] + blocks[-1][3] + 1 == 0xA000, blocks[-3:])
    kb = memsz(k)
    check('EMS: a DOS program gets the cache\'s 18 KB, less the EMS manager\'s 2 KB (%.1f KB, %.1f KB without EMS)' % (kb, kb0),
          kb >= kb0 + 16.0, (kb, kb0))
    keep = Y['ems_ltab'] + npg - Y['bss_end']
    print('   EMS manager resident: %d bytes (code and tables %d, pages %d)' % (keep, keep - npg, npg))
    check('EMS: the arena starts after the pages it keeps', first_mcb(k) == 0x60 + (Y['ems_ltab'] + npg + 15) // 16,
          hex(first_mcb(k)))
    check('EMS: resident within %d bytes' % EMS_BUDGET, keep <= EMS_BUDGET, keep)
    check('EMS: INT 67h -> the manager, EMMXXXX0 at its segment:000Ah',
          k.pc.u16(0, 0x67 * 4) == Y['ems_int67'] and k.pc.u16(0, 0x67 * 4 + 2) == 0x60
          and k.pc.rd(0x60, 0x0A, 8) == b'EMMXXXX0', hex(k.pc.u16(0, 0x67 * 4)))
    check('EMS: all four windows off after start-up', k.pc.ems_reg == [0, 0, 0, 0], k.pc.ems_reg)
    out = k.run_file('EMSTEST.COM', 300)
    print(out)
    check('EMSTEST: no failures', 'FAIL' not in out and ' 0 failed' in out, out[-400:])
    check('EMSTEST: back in the Executive', k.pc.mode() == 0x40 and not k.crashed, k.where())
    out = k.run_file('TESTDOS.COM', 120)
    check('TESTDOS with EMS: no failures', 'FAIL' not in out and ' 0 failed' in out, out[-200:])
    out = k.run_file('MEMSZ.COM', 30)
    print('   ' + out.strip())
    check('EMS: no EMS handles left open afterwards', ems_used(k) == 0, ems_used(k))
    # the same with a board that aliases (raw page 88 = page 0, ...): the scan
    # must still find 88
    k = ktest.KPC(image('ems2.img'), ems_pages=88, ems_alias=True); k.start()
    check('EMS (aliasing board): still 88 pages (86 + the cache\'s 2)', ems_npg(k) == 86, ems_npg(k))
    k = ktest.KPC(image('ems3.img', os.path.join(HERE, 'EMSTEST.COM')), ems_pages=128); k.start()
    check('EMS (2 MB board): 128 pages (126 + the cache\'s 2)', ems_npg(k) == 126, ems_npg(k))
    out = k.run_file('EMSTEST.COM', 300)
    check('EMSTEST on a 2 MB board (all 126 pages in one handle too): no failures',
          'FAIL' not in out and ' 0 failed' in out, out[-400:])
    # a board of 2 pages: too few to give two of them to the cache
    k = ktest.KPC(image('ems4.img'), ems_pages=2); k.start()
    sc = [b for b in mcbs(k) if b[4] == b'SC']
    check('EMS (2 pages): both for programs, the cache stays the "SC" block', ems_npg(k) == 2 and len(sc) == 1, (ems_npg(k), sc))

TESTS = [t_emsboard, t_noems, t_ems, t_dosapi, t_tm5000g, t_shell, t_disks, t_permanent, t_cache, t_cache_ems]
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
