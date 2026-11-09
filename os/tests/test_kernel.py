"""Lodestone 0.2 kernel tests in pcemu: the DOS API suite, a FAT check of the
disk afterwards, TM5000G run and return with the built-in GPIB.

    python3 tests/test_kernel.py [name ...]
"""
import os, re, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, fatcheck, sim7210, pcemu
OUT = os.environ.get('KOUT', os.path.join(__import__('tempfile').gettempdir(), 'lodestone-kt'))
os.makedirs(OUT, exist_ok=True)
def _find(env, *cands):
    """A file from the environment variable, else the first that exists."""
    if os.environ.get(env): return os.environ[env]
    for c in cands:
        if os.path.exists(c): return c
    return cands[-1]

TM5000G = _find('TM5000G', os.path.join(GOS, '..', 'tools', 'TM5000G.EXE'))

def build():
    subprocess.run([os.path.join(GOS, 'kbuild.sh')], check=True, stdout=subprocess.DEVNULL)
    for d, n in ((HERE, 'TESTDOS'), (HERE, 'UPPER'), (HERE, 'CACHETST'), (HERE, 'EMSTEST'), (HERE, 'MEMSZ'), (HERE, 'CAPTEST'), (HERE, 'MDTEST'),
                 (HERE, 'RUNCALC'), (os.path.join(GOS, 'src'), 'LCMD'), (os.path.join(GOS, 'src'), 'CALC')):
        subprocess.run(['nasm', '-f', 'bin', '-i', d + '/', '-o', os.path.join(d, n + '.COM'), os.path.join(d, n + '.ASM')], check=True)

SCR = os.path.join(GOS, 'drivers', 'SCREEN.PRN')    # Shift-PrtSc's file writer (KC-2), read from the boot disk's root
def image(name, *files):
    return mkimg.build(os.path.join(OUT, name), [os.path.join(GOS, 'src', 'LODE.SYS')] + list(files))

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
    check('test files cleaned up', set(files) == {'\\LODE.SYS', '\\TESTDOS.COM'}, sorted(files))
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
    """LCMD.COM (the command prompt) started from the Executive with
    Shift-CODE-P: the Executive's own prompt, full screen (ktest's code_p)."""
    def __init__(s, k):
        s.k = k
        k.code_p()
    def run(s, cmd, *answers):
        k = s.k
        k.key('cls'); k.key(ktest.ENTER)
        k.key(cmd); k.key(ktest.ENTER)
        for a in answers: k.key(a); k.key(ktest.ENTER)
        lines = k.pc.text_screen().rstrip().split('\n')
        return '\n'.join(lines[1:])

ZTXT = b'before\x1aafter\r\n'
def t_shell():
    open(os.path.join(OUT, 'Z.TXT'), 'wb').write(ZTXT)
    img = image('sh.img', os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(HERE, 'UPPER.COM'), 'GAMES\\', os.path.join(OUT, 'Z.TXT'))
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    check('CODE-P starts the shell', 'command shell' in k.pc.text_screen() and k.pc.mode() == 3, k.pc.text_screen())
    o = sh.run('dir')
    check('DIR lists the disk', all(x in o for x in ('Volume in drive A is LODESTONE', 'Directory of  A:\\', 'LCMD     COM', 'GAMES           <DIR>', '5 File(s)', 'bytes free')), o)
    check('VER', 'Lodestone version 1.0' in sh.run('ver'))
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
    check('pipe into a file', 'VOLUME IN DRIVE A IS LODESTONE' in o and 'A        TXT' in o, o)
    check('pipe files cleaned up', 'PIPE' not in sh.run('dir'))
    sh.run('md tmp')
    for tv in ('a:\\tmp', 'A:\\TMP\\'):                 # (a '\\' put between, or not)
        sh.run('set temp=' + tv)
        o = sh.run('dir tmp | upper')                  # (the pipe's file there while DIR runs)
        o2 = sh.run('dir | upper')
        check('TEMP=%s: the pipe\'s file in it (PIPEA1.$$$ in DIR TMP\'s own output), none in the root' % tv,
              'PIPEA1   $$$' in o and 'PIPEA1' not in o2 and 'VOLUME IN DRIVE A' in o2, (o, o2))
        check('... cleaned up there', 'PIPE' not in sh.run('dir tmp'))
    sh.run('set temp=')
    sh.run('md t2')
    sh.run('set tmp=a:\\tmp')                          # (no TEMP: TMP, as CLAUDE.COM)
    o = sh.run('dir tmp | upper')
    sh.run('set temp=a:\\t2')
    o2 = sh.run('dir t2 | upper') + sh.run('dir tmp | upper')      # (both: TEMP)
    sh.run('set tmp=')
    sh.run('set temp=')
    check('no TEMP, TMP=a:\\tmp: the pipe\'s file there; TEMP=a:\\t2 as well: in T2 (TEMP\'s), not in TMP',
          'PIPEA1   $$$' in o and o2.count('PIPEA1   $$$') == 1 and o2.index('PIPEA1') < o2.index('DIRECTORY OF  A:\\TMP')
          and 'PIPE' not in sh.run('dir tmp') + sh.run('dir t2'), (o, o2))
    sh.run('rd t2')
    sh.run('set temp=a:')                              # (a drive alone: its root)
    o = sh.run('dir | upper')
    check('TEMP=a: (a drive alone): the pipe\'s file in A:\\', 'PIPEA1   $$$' in o and 'PIPE' not in sh.run('dir'), o)
    sh.run('set temp=a:\\nope')
    o = sh.run('echo hi | upper')
    check('TEMP=a:\\nope (no such directory): the pipe fails with DOS\'s error, nothing left',
          'File creation error' in o and not re.search(r'^(hi|HI)\s*$', o, re.M) and 'PIPE' not in sh.run('dir')
          and not k.crashed, o)
    sh.run('set temp=a:\\' + 'x' * 70)
    o = sh.run('echo hi | upper') + sh.run('ver')
    check('TEMP of 72 characters (64 taken): the pipe fails cleanly, the next command runs',
          'File creation error' in o and 'Lodestone version' in o and not k.crashed, o)
    sh.run('set temp=a:\\tmp')
    o = sh.run('set temp=a:\\ | upper')                # (TEMP changed while its pipe runs)
    check('SET TEMP= inside a pipe: its files where TEMP was when it started, both cleaned up there',
          'PIPE' not in sh.run('dir') + sh.run('dir tmp') and 'not found' not in o, o)
    sh.run('set temp=')
    sh.run('rd tmp')
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
    # the serial ports, through an INT 14h like the 1520's: a port whose
    # base in the BDA is 0 answers with AX as it was (no time-out bit)
    pc = k.pc; com = {}; asked = []; sent = {0: b'', 1: b''}
    pc.mu.mem_write(0x400, struct.pack('<HH', 0x3F8, 0x2F8))
    def int14():
        ah, dx = pc.r('ah'), pc.r('dx')
        if ah == 2: asked.append(dx)
        if not pc.u16(0x40, 2 * dx) and len(asked) < 200: return
        if ah == 1: sent[dx] += bytes([pc.r('al')]); pc.w('ax', pc.r('al')); return
        if ah == 2 and com.get(dx): pc.w('ax', com[dx].pop(0)); return
        pc.w('ax', 0x8000 | (pc.r('ax') & 0xFF))
    pc.int14 = int14
    com[1] = list(b'two\r\n')
    sh.run('copy com2 c2.txt')
    o = sh.run('type c2.txt')
    check('COM2 reads COM2 (they read nothing)', 'two' in o and set(asked) == {1}, (o, asked))
    com[0] = list(b'one\r\n'); asked.clear()
    sh.run('copy aux c1.txt')
    o = sh.run('type c1.txt')
    check('AUX reads COM1', 'one' in o and set(asked) == {0}, (o, asked))
    sh.run('echo to1 > aux'); sh.run('echo to2 > com2')
    check('AUX writes COM1, COM2 writes COM2', sent == {0: b'to1 \r\n', 1: b'to2 \r\n'}, sent)
    pc.mu.mem_write(0x402, b'\0\0'); asked.clear()          # no COM2
    o = sh.run('copy com2 c3.txt')
    check('no COM2: the BIOS not asked (it would answer for ever), COPY back', not asked and 'A:\\>' in o, (asked[:5], o))
    del pc.int14
    sh.run('del c?.txt')
    sh.run('echo y | del *.bak')
    check('DEL from a pipe', 'B        BAK' not in sh.run('dir'))
    sh.run('set foo=bar')
    check('SET', 'FOO=bar' in sh.run('set'))
    sh.run('set foo=')
    check('SET removes', 'FOO' not in sh.run('set'))
    sh.run('copy con x.bat', 'echo off', 'echo batch says %1', 'ver', '\x1a')
    xb = fatcheck.read_files(k.pc.drives[0].img).get('A:\\X.BAT')
    check('COPY CON: the lines typed, up to the ^Z and not it', xb == b'echo off\r\necho batch says %1\r\nver\r\n', xb)
    sh.run('copy z.txt z2.txt')
    z2 = fatcheck.read_files(k.pc.drives[0].img).get('A:\\Z2.TXT')
    check('COPY of a file with a ^Z inside: all of it (only a device\'s text ends at one)', z2 == ZTXT, z2)
    o = sh.run('type z.txt')
    check('TYPE stops at the ^Z', 'before' in o and 'after' not in o, o)
    sh.run('del z2.txt')
    o = sh.run('x hi')
    check('batch file, %1, ECHO OFF', 'batch says hi' in o and 'Lodestone version 1.0' in o and 'echo batch' not in o, o)
    check('ECHO back on after the batch', 'A:\\>' in sh.run('rem'))
    sh.run('date 1-2-27')
    check('DATE', 'Sat 01-02-2027' in sh.run('date', ''))
    sh.run('time 10:11:12')
    check('TIME', 'Current time is 10:11' in sh.run('time', ''))
    sh.run('del a.txt'); sh.run('del d.txt'); sh.run('del x.bat')
    k.key('exit'); k.key(ktest.ENTER)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    check('EXIT returns to the Executive', k.pc.mode() == 0x40 and any('LCMD.COM ended' in l for l in k.band()), k.band())
    probs, files = fatcheck.check(bytes(k.pc.drives[0].img))
    check('disk consistent after the shell', not probs, '; '.join(probs))
    check('shell files cleaned up', set(files) == {'\\LODE.SYS', '\\LCMD.COM', '\\UPPER.COM', '\\GAMES\\', '\\Z.TXT'}, sorted(files))

def t_tabs():
    """tty_out: a tab is spaces to the next multiple of 8, from the line's start (TYPE writes through it)."""
    t = os.path.join(OUT, 'TAB.TXT'); open(t, 'wb').write(b'A\tB\r\nABCDEFGH\tC\r\n\tD\r\nABCDEFG\tE\r\n')
    k = ktest.KPC(image('tabs.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'TAB.TXT=' + t)); k.start()
    o = Shell(k).run('type tab.txt').split('\n')
    check('TYPE of tabs: "A" then B at column 8, "ABCDEFGH" then C at 16, D at 8, "ABCDEFG" then E at 8',
          [l.rstrip() for l in o[:4]] == ['A       B', 'ABCDEFGH        C', '        D', 'ABCDEFG E'], o[:5])

def t_disks():
    """Write protect (Retry, Fail), changing floppies, a drive with no
    change line."""
    import pcemu
    img = image('dk.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'SUB\\')
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
    """LCMD /P is a first shell (as GRiD MS-DOS would start one): it runs
    AUTOEXEC.BAT and EXIT does nothing; without /P, EXIT ends it."""
    bat = os.path.join(OUT, 'AUTOEXEC.BAT')
    open(bat, 'wb').write(b'@echo off\r\necho autoexec ran\r\n')
    img = image('pm.img', os.path.join(GOS, 'src', 'LCMD.COM'), bat)
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    psp0 = k.pc.u16(0x60, k.Y['cur_psp'])
    o = sh.run('lcmd /p')
    check('/P runs AUTOEXEC.BAT', 'autoexec ran' in o, o)
    psp1 = k.pc.u16(0x60, k.Y['cur_psp'])
    sh.run('exit')
    check('/P: EXIT does nothing', k.pc.u16(0x60, k.Y['cur_psp']) == psp1 != psp0 and 'Lodestone version' in sh.run('ver'))
    o = sh.run('lcmd /c echo one shot')
    check('/C inside', 'one shot' in o and k.pc.u16(0x60, k.Y['cur_psp']) == psp1, o)

def t_capture():
    """Shift-PrtSc (the BIOS's INT 5): SCREENnn.BMP / .TXT in the root of
    the boot disk, at the next DOS call or wait for a key."""
    import io
    from PIL import Image
    pad = os.path.join(OUT, 'PAD.DAT')
    k = ktest.KPC(image('cap.img', os.path.join(HERE, 'CAPTEST.COM'), os.path.join(GOS, 'src', 'LCMD.COM'), SCR)); k.start()
    files = lambda: fatcheck.read_files(k.pc.drives[0].img)
    beeps = lambda: ''.join(k.pc.tty).count('\x07')
    calls21 = []                                # (AX) of the 3Eh, 40h and F0h calls made during a shot
                                                #  (only the capture's: the Executive is idle then)
    def rec(pc):
        if pc.r('cs') == 0x60 and pc.r('ip') == k.Y['int21'] and pc.r('ah') in (0x3E, 0x40, 0xF0): calls21.append(pc.r('ax'))
    closes = lambda: sum(1 for a in calls21 if a >> 8 == 0x3E)
    def shot(sim_s=6.0):
        calls21.clear(); k.hooks.append(rec)
        k.pc.tty.clear(); k.pc.prtsc(); k.settle(sim_s)
        k.hooks.remove(rec)
    def bmp_ok(data, line):
        """640 x 400, 1 bit, amber on brown, line y of the screen = line(y)."""
        im = Image.open(io.BytesIO(data))
        if im.size != (640, 400) or im.getpalette()[:6] != [36, 8, 2, 255, 120, 40]: return False
        raw = im.tobytes()                      # (mode P: a byte a pixel)
        return all(bytes(sum((raw[y * 640 + x * 8 + b] != 0) << (7 - b) for b in range(8)) for x in range(80)) == line(y)
                   for y in range(400))
    check('INT 5 is the kernel\'s', k.pc.u16(0, 5 * 4 + 2) == 0x60)
    vram = k.pc.rd(0xB800, 0, 0x8000)
    shot()
    f = files()
    check('Executive: SCREEN01.BMP, 32062 bytes, one beep', len(f.get('A:\\SCREEN01.BMP', b'')) == 32062 and beeps() == 1,
          (sorted(f), beeps()))
    check('Executive: the picture is the screen (mode 40h, 4 banks)',
          bmp_ok(f['A:\\SCREEN01.BMP'], lambda y: vram[(y & 3) * 0x2000 + (y >> 2) * 80:][:80]))
    check('the screen is left as it was', k.pc.rd(0xB800, 0, 0x8000) == vram)
    check('the disk cache\'s memory (the buffer) given back', k.rd('tc_lock', 1) == b'\0')
    # the cache's memory lent already (the help window has it): 1 KB at the
    # bottom of the kernel stack instead, and the cache stays lent
    k.wr('tc_lock', b'\1'); vram = k.pc.rd(0xB800, 0, 0x8000); shot(); lock = k.rd('tc_lock', 1); k.wr('tc_lock', b'\0')
    f = files()
    check('the next one: SCREEN02.BMP, through the 1 KB buffer; the cache still lent', 'A:\\SCREEN02.BMP' in f and
          bmp_ok(f['A:\\SCREEN02.BMP'], lambda y: vram[(y & 3) * 0x2000 + (y >> 2) * 80:][:80]) and lock == b'\1' and beeps() == 1,
          (sorted(f), lock, beeps()))
    # a DOS program: mode 6, text in 80 and 40 columns, then a BIOS wait
    k.select('CAPTEST.COM'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() == 6, 5); k.settle()
    shot()
    f = files()
    check('mode 6: SCREEN03.BMP, each line twice', 'A:\\SCREEN03.BMP' in f and
          bmp_ok(f['A:\\SCREEN03.BMP'], lambda y: bytes([y >> 1]) * 80) and beeps() == 1, (sorted(f), beeps()))
    nw = -(-32062 // (1024 - os.path.getsize(SCR)))
    check('... in a DOS program, through the rest of SCREEN.PRN\'s 1 KB (no lend: with EMS it would be free memory): '
          '%d writes' % nw, 0xF002 not in calls21 and sum(1 for a in calls21 if a >> 8 == 0x40) == nw, [hex(a) for a in calls21][:6])
    k.key(ktest.ENTER); shot()
    want = 'Line one\r\nSecond line\r\n\r\nABCDE GHIJ\r\n' + '\r\n' * 21
    got = files().get('A:\\SCREEN01.TXT', b'').decode('latin-1')
    check('text: SCREEN01.TXT, trailing blanks off, the NUL a blank', got == want, repr(got))
    k.key(ktest.ENTER); shot()
    got = files().get('A:\\SCREEN02.TXT', b'').decode('latin-1')
    check('40 columns: SCREEN02.TXT', got == 'Forty\r\n' + '\r\n' * 24, repr(got))
    calls = []
    k.hooks.append(lambda pc: calls.append(1) if pc.r('cs') == 0x60 and pc.r('ip') == k.Y['int21'] and pc.r('ah') == 0x2A else None)
    k.key(ktest.ENTER); shot(); k.run_for(3.0)
    check('a BIOS wait, a timer hook calling DOS: not inside the interrupt', 'A:\\SCREEN03.TXT' not in files() and
          beeps() == 0 and len(calls) > 40, (sorted(files()), len(calls)))
    k.hooks.pop()
    k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    got = files().get('A:\\SCREEN03.TXT', b'').decode('latin-1')
    check('... taken at the next DOS call outside it', got.startswith('BIOS wait\r\n\r\n') and beeps() == 1, repr(got[:40]))
    check('the program ended as usual', any('CAPTEST.COM ended' in l for l in k.band()), k.band())
    sh = Shell(k); sh.run('ver'); shot()
    got = files().get('A:\\SCREEN04.TXT', b'').decode('latin-1')
    check('at the DOS prompt (LCMD): SCREEN04.TXT', 'Lodestone version 1.0' in got and beeps() == 1, repr(got[:200]))
    sh.run('exit'); k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    probs, _ = fatcheck.check(bytes(k.pc.drives[0].img))
    check('disk consistent', not probs, '; '.join(probs))
    # write-protected: a long beep, nothing written, no INT 24h (the UI's
    # handler would have kept the error for its next message)
    before = bytes(k.pc.drives[0].img)
    k.pc.drives[0].wp = True; shot(); k.pc.drives[0].wp = False
    check('write-protected: a long beep, the disk untouched, no INT 24h, nothing to close but SCREEN.PRN, read',
          beeps() == 4 and bytes(k.pc.drives[0].img) == before and k.u16('crit_err') == 0 and closes() == 1,
          (beeps(), k.u16('crit_err'), closes()))
    # another disk put in, which a program already read through the BIOS
    # (the change line is clear) and no INT 21h 0Dh yet: the capture must
    # not write the first disk's FAT and directory over it
    import pcemu
    data = []
    for i in range(30):
        open(os.path.join(OUT, 'D%02d.TXT' % i), 'wb').write(b'data %d\r\n' % i * 200)
        data.append(os.path.join(OUT, 'D%02d.TXT' % i))
    other = mkimg.build(os.path.join(OUT, 'capother.img'), data + [SCR])     # (the driver is read from the disk in A:)
    before = fatcheck.read_files(open(other, 'rb').read())
    k = ktest.KPC(image('cap2.img', os.path.join(HERE, 'CAPTEST.COM'), SCR)); k.start()
    k.select('CAPTEST.COM'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() == 6, 5); k.settle()
    k.pc.drives[0] = pcemu.Floppy(other); k.pc.drives[0].changed = False
    shot()
    after = fatcheck.read_files(k.pc.drives[0].img)
    probs, _ = fatcheck.check(bytes(k.pc.drives[0].img))
    check('a disk changed behind the kernel\'s back: its files kept, the picture on it',
          all(after.get(n) == d for n, d in before.items()) and 'A:\\SCREEN01.BMP' in after and not probs and beeps() == 1,
          (sorted(set(before) - set(after)), probs[:3], beeps()))
    # no room for all of it: none of it is left
    open(pad, 'wb').write(bytes(1400000))
    k = ktest.KPC(image('capfull.img', SCR, pad)); k.start()
    before = sorted(files())
    shot()
    probs, _ = fatcheck.check(bytes(k.pc.drives[0].img))
    check('disk full: a long beep, no SCREEN01.BMP, disk consistent, no write after the one that failed, closed once '
          '(and SCREEN.PRN, read)', beeps() == 4 and sorted(files()) == before and not probs
          and sum(1 for a in calls21 if a >> 8 == 0x40) == 1 and closes() == 2, (beeps(), sorted(files()), probs, [hex(a) for a in calls21]))
    # KC-2: no SCREEN.PRN on the disk started from: no file, the long beep; nothing of it in the kernel
    k = ktest.KPC(image('capnone.img', os.path.join(GOS, 'src', 'LCMD.COM'))); k.start()
    shot()
    check('no SCREEN.PRN on the boot disk: Shift-PrtSc gives the long beep, no file, PrtSc free again (cap_req 0)',
          beeps() == 4 and not any('SCREEN0' in n for n in files()) and k.rd('cap_req', 1) == b'\0' and not k.crashed,
          (beeps(), sorted(files())))
    check('SCREEN.PRN: one sector, the driver\'s signature, its buffer at least 512 bytes', os.path.getsize(SCR) <= 512
          and open(SCR, 'rb').read()[2:6] == b'PRN\x01', os.path.getsize(SCR))


def t_print():
    """PRINTER=PS.PRN in LODE.INI: PrtSc reads that driver (a file of
    up to 1 KB) into the capture's 1 KB, calls it, and forgets it; PS.PRN
    sends the screen to LPT1 as PostScript (the Brother HL-5370DW's)."""
    import binascii, subprocess
    ini = os.path.join(OUT, 'LODE.INI'); open(ini, 'wb').write(b'printer=ps.prn\r\n')
    ps = os.path.join(GOS, 'drivers', 'PS.PRN')
    k = ktest.KPC(image('prn.img', os.path.join(HERE, 'CAPTEST.COM'), ini, ps, SCR)); k.start()
    files = lambda: fatcheck.read_files(k.pc.drives[0].img)
    beeps = lambda: ''.join(k.pc.tty).count('\x07')
    def shot(sim_s=8.0):
        k.pc.tty.clear(); k.pc.lpt.clear(); k.pc.prtsc(); k.settle(sim_s)
        return bytes(k.pc.lpt)
    path = lambda: k.rd('prn_path', 24).split(b'\0')[0]
    check('PRINTER=ps.prn in LODE.INI: found as programs are, the kernel has A:\\ps.prn', path().upper() == b'A:\\PS.PRN', path())
    check('PS.PRN fits the 1 KB buffer, in one sector, and has the signature',
          os.path.getsize(ps) <= 512 and open(ps, 'rb').read()[2:6] == b'PRN\x01', os.path.getsize(ps))
    vram = k.pc.rd(0xB800, 0, 0x8000)
    out = shot()
    head, _, rest = out.partition(b'image\n')
    rows = rest.split(b'\n')
    want = [bytes(255 - v for v in vram[(y & 3) * 0x2000 + (y >> 2) * 80:][:80]) for y in range(399, -1, -1)]
    check('Executive: PostScript to LPT1, a 640 x 400 image, one beep, no file',
          out.startswith(b'%!PS-Adobe-3.0\n') and b'640 400 1[640 0 0 400 0 0]' in head and out.endswith(b'showpage\n\x04')
          and beeps() == 1 and not any('SCREEN0' in n for n in files()), (out[:80], out[-20:], beeps(), sorted(files())))
    check('... the screen, bottom line first, a lit pixel black (0), 80 bytes a line in hex',
          [binascii.unhexlify(r) for r in rows[:400]] == want and rows[400] == b'showpage', (len(rows), rows[400:401]))
    k.select('CAPTEST.COM'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() == 6, 5); k.settle()
    out = shot()
    rows = out.partition(b'image\n')[2].split(b'\n')
    check('mode 6, in a DOS program: the image, each line twice', [binascii.unhexlify(r) for r in rows[:400]] ==
          [bytes([255 - (y >> 1)]) * 80 for y in range(399, -1, -1)] and beeps() == 1, beeps())
    k.key(ktest.ENTER); out = shot()
    lines = out.partition(b'def}def\n')[2].split(b'\n')
    check('text: 25 lines in Courier, each "(...)l"', b'/Courier findfont' in out and len(lines) == 27 and
          all(l.startswith(b'(') and l.endswith(b')l') for l in lines[:25]) and lines[25] == b'showpage', lines[:5])
    check('... as the screen has them (80 columns, the NUL a blank)', lines[0] == b'(' + b'Line one'.ljust(80) + b')l'
          and lines[3] == b'(' + b'ABCDE GHIJ'.ljust(80) + b')l', lines[:4])
    k.pc.wr(0xB800, 0, b'(\x07)\x07\\\x07\xC9\x07'); out = shot()
    check('( ) and \\ escaped, a box-drawing character as ?', b'\n(\\(\\)\\\\?' in out, out[:200])
    k.pc.lpt_status = 0x11; out = shot(14.0); k.pc.lpt_status = 0x90
    check('printer busy 10 s: the long beep, nothing sent', out == b'' and beeps() == 4, (out[:20], beeps()))
    k.pc.lpt_status = 0x38; out = shot(); k.pc.lpt_status = 0x90
    check('out of paper: the long beep at once', out == b'' and beeps() == 4, (out[:20], beeps()))
    k.pc.wr(0, 0x408, b'\0\0'); out = shot(); k.pc.wr(0, 0x408, b'\x78\x03')
    check('no LPT1: the long beep', out == b'' and beeps() == 4, (out[:20], beeps()))
    # any driver: one that prints "Hi" through the BIOS and says it did
    drv = os.path.join(OUT, 'drv.asm'); open(drv, 'w').write(
        "org 0\njmp short s\ndb 'PRN', 1\ns: mov ax, 0048h\nxor dx, dx\nint 17h\nmov ax, 0069h\nint 17h\nxor al, al\nretf\n")
    subprocess.run(['nasm', '-f', 'bin', '-o', os.path.join(OUT, 'HI.PRN'), drv], check=True)
    hi = open(os.path.join(OUT, 'HI.PRN'), 'rb').read()
    big = os.path.join(OUT, 'BIG.PRN'); open(big, 'wb').write(hi + bytes(1100))
    # not drivers: a print job saved as .PRN (it would hang the machine if
    # run), an empty file (the buffer's old contents), one too small, one
    # without the signature
    job = os.path.join(OUT, 'JOB.PRN'); open(job, 'wb').write(b'\x1b&l0O\x1bEHello from a saved print job\r\n\x0c')
    zero = os.path.join(OUT, 'ZERO.PRN'); open(zero, 'wb').write(b'')
    tiny = os.path.join(OUT, 'TINY.PRN'); open(tiny, 'wb').write(hi[:6] + b'\xcb' * 4)
    nosig = os.path.join(OUT, 'NOSIG.PRN'); open(nosig, 'wb').write(hi[:2] + b'XXX\x01' + hi[6:])
    k2 = ktest.KPC(image('prn2.img', os.path.join(OUT, 'HI.PRN'), big, job, zero, tiny, nosig, SCR)); k2.start()
    def shot2(name):
        k2.wr('prn_path', name.encode() + b'\0'); k2.pc.tty.clear(); k2.pc.lpt.clear(); k2.pc.prtsc(); k2.settle(6)
        return bytes(k2.pc.lpt), ''.join(k2.pc.tty).count('\x07')
    check('another driver (HI.PRN): it is what prints', shot2('A:\\HI.PRN') == (b'Hi', 1), shot2('A:\\HI.PRN'))
    check('a driver over 1 KB: not run, the long beep', shot2('A:\\BIG.PRN') == (b'', 4), shot2('A:\\BIG.PRN'))
    check('a driver that isn\'t there: the long beep', shot2('A:\\NONE.PRN') == (b'', 4), shot2('A:\\NONE.PRN'))
    for n, what in (('JOB', 'a print job saved as .PRN'), ('ZERO', 'an empty file'), ('TINY', 'under 16 bytes'),
                    ('NOSIG', 'no signature')):
        got = shot2('A:\\%s.PRN' % n)
        check('%s: not run, the long beep, and PrtSc free again (cap_req 0)' % what, got == (b'', 4) and
              k2.rd('cap_req', 1) == b'\0', (got, k2.rd('cap_req', 1)))
    check('... and the real driver still prints after them', shot2('A:\\HI.PRN') == (b'Hi', 1), shot2('A:\\HI.PRN'))
    k2.wr('prn_path', b'\0')
    out, _ = shot2('')
    check('no driver: SCREEN01.BMP as before', 'A:\\SCREEN01.BMP' in fatcheck.read_files(k2.pc.drives[0].img),
          sorted(fatcheck.read_files(k2.pc.drives[0].img)))
    check('still no file on the printing disk', not any('SCREEN0' in n for n in files()), sorted(files()))
    # Shift-PrtSc: the file all the same, the driver set
    k.pc.wr(0, 0x417, bytes([k.pc.rd(0, 0x417, 1)[0] | 2])); out = shot(); k.pc.wr(0, 0x417, bytes([k.pc.rd(0, 0x417, 1)[0] & ~3]))
    check('Shift-PrtSc with a driver set: SCREEN01.BMP, nothing to the printer', out == b'' and beeps() == 1 and
          any('SCREEN01' in n for n in files()), (out[:20], beeps(), sorted(files())))
    out = shot()
    check('... and PrtSc alone prints again', out.startswith(b'%!PS'), out[:20])

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
        return image(name, os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(HERE, 'CACHETST.COM'), data)
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
        check('... and M: on all along (256 KB, no MDISK= line), as it was', md_info(k)[1] == 16 and all(hooks_in(k)),
              md_info(k)[:2])
    probs, files = fatcheck.check(bytes(k.pc.drives[0].img))
    check('disk consistent after CACHETST' + tag, not probs and '\\CACHE_A.TST' not in files, '; '.join(probs) or sorted(files))
    log = fatcheck.read_files(k.pc.drives[0].img).get('A:\\CACHETST.TXT', b'').decode('latin-1')
    check('CACHETST leaves its results in CACHETST.TXT' + tag, 'on Lodestone' in log and ' 0 errors' in log, log[-300:])
    # the help window's save-under: the cache's memory, lent and given back;
    # with the cache in EMS, a block of its own while it is open (the cache
    # stays as it is)
    rows = [(y & 3) * 0x2000 + (y >> 2) * 80 for y in range(64, 64 + 232)]   # (the screen's four banks)
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
    img4 = image('c4.img', os.path.join(GOS, 'src', 'LCMD.COM'))
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
    img5 = image('c5.img', os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(GOS, 'bench', 'BENCH.COM'))
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
    img3 = image('c3.img', os.path.join(GOS, 'src', 'LCMD.COM'), big)
    raw = open(img3, 'rb').read()
    cl = [struct.unpack_from('<H', raw, 19 * 512 + 32 * i + 26)[0] for i in range(16)
          if raw[19 * 512 + 32 * i:19 * 512 + 32 * i + 11] == b'BIG     TXT'][0]
    k = ktest.KPC(img3, ems_pages=ems); k.start()
    k.pc.drives[0].bad = {33 + cl - 2 + 30}         # the file's 31st sector
    sh = Shell(k)
    o = sh.run('type big.txt', 'f')
    good = all('line %04d of the bad-sector file' % i in o for i in range(440, 451))
    check('bad sector: the file reads up to it, then Data error, read-ahead gave up once' + tag,
          good and 'Data error reading drive A' in o and 'line 0460' not in o and getattr(k.pc, 'calls_bad', 0) <= 9,
          '%d failed reads; %s' % (getattr(k.pc, 'calls_bad', 0), o[-400:]))
    # a weak drive head (the 1520's side 0, inner tracks): a read of several
    # sectors on these tracks always fails with a CRC error, each sector on
    # its own reads fine.  The kernel falls back to sector-by-sector: the
    # file copies whole, no Data error
    img4 = image('c4.img', os.path.join(GOS, 'src', 'LCMD.COM'), big)
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

EMS_BUDGET = 1984       # bytes the EMS manager may keep (with 88 pages): 124 paragraphs (S14's word-wise 57h: +16)
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
    ltab, tc = k.rd('ems_ltab', 86), k.rd('ems_tcpg', 2)
    check('EMS: 88 pages found: 86 for programs and the disk cache\'s two, all different (the table past the 86 is '
          'the arena\'s: ems_tcpg keeps the cache\'s)', npg == 86 and len(set(ltab + tc)) == 88, (npg, tc, ltab[84:]))
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
    check('EMS: no EMS left in use afterwards but M:\'s 16 pages', ems_used(k) == 16 and md_info(k)[1] == 16, ems_used(k))
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

# ---------------------------------------------------------------------
#  M:, the temporary disk in EMS (KMDISK.INC)
# ---------------------------------------------------------------------
MDTEST = os.path.join(HERE, 'MDTEST.COM')
SYSF = os.path.join(GOS, 'src', 'LODE.SYS')

def md_info(k):
    """M: as the kernel has it: (handle, pages, its whole disk from EMS),
    from the installer's own data (in the disk cache's EMS page) and the
    EMS manager's tables."""
    Y = k.Y
    tp = k.rd('ems_tcpg', 2)[1] & 0x7F
    h = struct.unpack('<H', k.pc.ems_read(tp, Y['md_h'], 2))[0]
    if not k.pc.ems_read(tp, Y['md_pg'], 1)[0]: return 0, 0, b''
    st, n = k.rd('ems_h', 2, 4 * h)
    ltab = k.rd('ems_ltab', 128)
    return h, n, b''.join(k.pc.ems_read(ltab[st + i] & 0x7F, 0, 0x4000) for i in range(n))

def md_owner(k, h): return k.pc.u16(0x60, k.Y['ems_h'] + 4 * h + 2)

def env_split(k):
    """(the master environment's paragraphs, the MD block's (owner, paragraphs) or None)"""
    b = mcbs(k)
    md = b[1] if b[1][4] == b'MD' else None
    return b[0][3], ((md[2], md[3]) if md else None)

HOOKED = ('use_drive', 'drv_present', 'cwd_of', 'dio')
def hooks_in(k):
    """M:'s hooks in, and INT 21h 0Eh counting to M: (0.6: the count is a
    byte, lastdrv, which M: raises to 13 and puts back)"""
    return [k.pc.rd(0x60, k.Y[n], 1)[0] == 0xE9 for n in HOOKED] + [k.pc.rd(0x60, k.Y['lastdrv'], 1)[0] == 13]

def md_size(out):
    m = re.search(r'result (\w\w) size (\d+)', out)
    return (m.group(1), int(m.group(2))) if m else (None, None)

def md_query(out):
    m = re.search(r'M: setting (\d+) size (\d+) max (\d+) handle (\d+)', out)
    return tuple(map(int, m.groups())) if m else None

def shell_memsz(sh):
    m = re.search(r'([\d.]+) KB for programs', sh.run('memsz'))
    return float(m.group(1)) if m else 0

def ini_image(name, text, *files):
    ini = os.path.join(OUT, 'LODE.INI')
    open(ini, 'wb').write(text)
    return image(name, *(list(files) + [ini]))

def t_mdisk():
    """M:, the temporary disk in EMS: nothing without EMS or while it is
    off; 256 KB by default, MDISK= in LODE.INI; its block split off the
    environment's 512 bytes (DOS programs get as much); every size, the
    file calls, COPY with A: and C:, a program run from M:, M: full,
    refused while a file is open, EMS held by a program, a program's own
    pages in all four windows and a buffer in the frame while it works
    (MDTEST), a warm restart (kept, or made new)."""
    files = [os.path.join(GOS, 'src', 'LCMD.COM'), MDTEST, os.path.join(HERE, 'MEMSZ.COM'), os.path.join(HERE, 'UPPER.COM')]
    sysb = open(SYSF, 'rb').read()
    img = image('md.img', *files)
    # --- no EMS
    k = ktest.KPC(img); k.start()
    env, md = env_split(k)
    check('M: without EMS: the environment keeps its 512 bytes, no MD block, no hook, KSEG:0000 as `start\' left it',
          env == 32 and md is None and not any(hooks_in(k)) and k.pc.rd(0x60, 0, 0x2D)[:10] == sysb[:10]
          and k.pc.rd(0x60, 0x12, 0x1B) == sysb[0x12:0x2D], (env, md, hooks_in(k)))
    sh = Shell(k)
    kb_noems = shell_memsz(sh)
    o = sh.run('mdtest /q')
    check('... INT 67h 5Bh answers 84h (no EMS) and there is no drive M:', 'says 84' in o and 'Invalid drive' in sh.run('m:'), o)
    # --- EMS, M: off (MDISK=0)
    k = ktest.KPC(ini_image('md0.img', b'MDISK=0\r\n', *files), ems_pages=88); k.start()
    env, md = env_split(k)
    h, n, mi = md_info(k)
    check('MDISK=0: M: off: no MD block (the environment has its 512 bytes), no hook, no EMS pages',
          env == 32 and md is None and not any(hooks_in(k)) and n == 0 and ems_used(k) == 0, (env, md, hooks_in(k), n, ems_used(k)))
    check('... the stub at KSEG:0012h (where `start\' was) and INT 67h 5Bh to it; init\'s last jump back as it was',
          k.pc.u16(0x60, k.Y['ems_tab'] + 2 * 0x1B) == 0x12 and k.pc.rd(0x60, 0, 5) == sysb[:5], k.pc.rd(0x60, 0, 0x2D).hex())
    sh = Shell(k)
    kb_off = shell_memsz(sh)
    check('... "M:": invalid drive; MDTEST /Q: off', 'Invalid drive' in sh.run('m:') and md_query(sh.run('mdtest /q'))[:2] == (0, 0))
    # --- EMS, no LODE.INI: 256 KB
    k = ktest.KPC(img, ems_pages=88); k.start()
    h, n, mi = md_info(k)
    env, md = env_split(k)
    check('no MDISK= line: M: is 256 KB, 16 pages in a handle of its own (%d, owner 0: no exit frees it)' % h,
          n == 16 and h and md_owner(k, h) == 0 and ems_used(k) == 16, (h, n, ems_used(k)))
    check('... its resident part: a block of its own (owner 8, "MD", %d bytes) split off the end of the environment\'s 512 bytes '
          '(the environment keeps %d)' % ((md or (0, 0))[1] * 16, env * 16),
          md and md[0] == 8 and env + 1 + md[1] == 32 and env * 16 >= 128, (env, md))
    check('... the kernel hooked (use_drive, drv_present, cwd_of, dio, INT 21h 0Eh)', all(hooks_in(k)), hooks_in(k))
    probs, fs = fatcheck.check(mi)
    b = fatcheck.bpb(mi)
    check('... M: is an empty FAT12 disk: 512 sectors of 512 bytes, 2 a cluster, 1 FAT, 128 root entries',
          not probs and not fs and b == dict(bps=512, spc=2, res=1, nfat=1, nroot=128, tot=512, spf=1) and mi[3:11] == b'LODE M: ',
          (probs, fs, b))
    sh = Shell(k)
    kb_on = shell_memsz(sh)
    check('DOS programs get as much with M: on as with it off (%.1f KB, %.1f KB off; %.1f KB without EMS)' % (kb_on, kb_off, kb_noems),
          kb_on == kb_off and kb_on > 0, (kb_on, kb_off))
    q = md_query(sh.run('mdtest /q'))
    check('MDTEST /Q: setting 256, size 256, all free would give 1376 KB (86 pages)', q and q[:3] == (256, 256, 1376), q)
    # the shell on M:
    o = sh.run('m:')
    check('"M:" makes M: the current drive', 'M:\\>' in o, o)
    sh.run('copy a:lcmd.com'); sh.run('copy a:upper.com'); sh.run('md sub'); sh.run('cd sub')
    o = sh.run('copy ..\\lcmd.com x.com')
    check('COPY A: -> M:, MD, CD and COPY within M:', '1 File(s) copied' in o and 'M:\\SUB>' in o, o)
    o = sh.run('dir')
    check('DIR of M:\\SUB', 'Directory of  M:\\SUB' in o and 'X        COM' in o and '.               <DIR>' in o, o)
    sh.run('cd \\')
    o = sh.run('echo hello there | upper')
    check('a program run from M: (UPPER.COM)', 'HELLO THERE' in o, o)
    o = sh.run('copy m:\\sub\\x.com a:\\back.com')
    check('COPY M: -> A:', '1 File(s) copied' in o, o)
    fa = fatcheck.read_files(k.pc.drives[0].img)
    h, n, mi = md_info(k)
    fm = fatcheck.read_files(mi, 'M')
    gc = open(os.path.join(GOS, 'src', 'LCMD.COM'), 'rb').read()
    check('... every copy byte for byte (on M: and back on A:)', fm.get('M:\\LCMD.COM') == gc and fm.get('M:\\SUB\\X.COM') == gc
          and fa.get('A:\\BACK.COM') == gc, sorted(fm))
    probs, _ = fatcheck.check(mi)
    check('... M: consistent (CHKDSK\'s checks)', not probs, probs)
    sh.run('del sub\\x.com')
    o = sh.run('rd sub')
    check('DEL, RD on M:', 'SUB' not in sh.run('dir'), o)
    # page boundaries, the frame, all four windows; full
    o = sh.run('mdtest /w')
    check('MDTEST /W: our pages in all four windows and buffers in the frame while M: works: as they were, the data right',
          o.count('ok ') == 8 and 'FAIL' not in o, o)
    o = sh.run('mdtest /f')
    check('MDTEST /F: M: filled to the last cluster, read back, emptied', o.count('ok ') == 4 and 'FAIL' not in o, o)
    # a file open: refused
    o = sh.run('mdtest /o 64')
    check('a new size while a file on M: is open: refused (80h), M: as it was', md_size(o) == ('80', 256)
          and 'LCMD     COM' in sh.run('dir m:'), o)
    # every size
    sizes = [(64, 64), (128, 128), (512, 512), (1024, 1024), ('all', 1376), (0, 0), (256, 256)]
    for want, got in sizes:
        o = sh.run('mdtest /s %s' % want)
        h, n, mi = md_info(k)
        env, md = env_split(k)
        if got:
            probs, fs = fatcheck.check(mi)
            ok = md_size(o) == ('00', got) and n * 16 == got and not probs and not fs and md and env + 1 + md[1] == 32 and all(hooks_in(k))
        else:
            ok = md_size(o) == ('00', 0) and n == 0 and env == 32 and md is None and not any(hooks_in(k)) and ems_used(k) == 0
        check('M: set to %s: %d KB, %s' % (want, got, 'empty, consistent, its block split off the environment' if got else
                                         'off: no block, the environment whole, no hook, no EMS'), ok, (o, n, env, md, hooks_in(k)))
    check('... and DOS programs still get %.1f KB' % kb_on, shell_memsz(sh) == kb_on)
    o = sh.run('mdtest /w')
    check('MDTEST /W again at 256 KB after all that', o.count('ok ') == 8 and 'FAIL' not in o, o)
    # EMS held by a program
    o = sh.run('mdtest /h 60')
    o = sh.run('mdtest /s 512')
    check('60 pages held by a resident program: M: at 512 KB gets what is free (26 pages, 416 KB)', md_size(o) == ('00', 416), o)
    q = md_query(sh.run('mdtest /q'))
    check('... MDTEST /Q: setting 512, size 416', q and q[:2] == (512, 416), q)
    sh.run('mdtest /s 0'); sh.run('mdtest /h 26')
    o = sh.run('mdtest /s 64')
    check('no EMS free at all: M: off (82h), the setting kept', md_size(o) == ('82', 0) and md_query(sh.run('mdtest /q'))[:2] == (64, 0)
          and env_split(k)[1] is None, o)
    k.key('exit'); k.key(ktest.ENTER); k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    # LODE.INI
    for text, want in ((b'MDISK=ALL\r\n', 1376), (b'mdisk=all\r\n', 1376), (b'FONT=X.FNT\r\nMDISK=128\r\nSAVER=10\r\n', 128),
                       (b'MDISK=100\r\n', 96), (b'MDISK=junk\r\n', 256), (b'MDISK=\r\n', 256), (b'MDISK=99999\r\n', 1376),
                       (b'MDISK=5', 16)):
        k = ktest.KPC(ini_image('mdi.img', text, *files), ems_pages=88); k.start()
        h, n, mi = md_info(k)
        check('LODE.INI %r: M: is %d KB' % (text, want), n * 16 == want and not k.crashed, (n, k.crashed))
    k = ktest.KPC(img, ems_pages=8); k.start()
    h, n, mi = md_info(k)
    check('a board of 8 pages (6 for programs): M: is as big as fits, 96 KB', n == 6 and not fatcheck.check(mi)[0], n)
    k = ktest.KPC(img, ems_pages=2); k.start()
    env, md = env_split(k)
    check('a board of 2 pages (no disk cache in EMS): no M:, nothing kept for it', md is None and env == 32
          and k.pc.u16(0x60, k.Y['ems_tab'] + 2 * 0x1B) != 0x12 and k.pc.rd(0x60, 0, 10) == sysb[:10]
          and k.pc.rd(0x60, 0x12, 0x1B) == sysb[0x12:0x2D], (env, md))
    # warm restart
    for ems, kept in (('keep', True), ('lose', False), ({0}, False)):
        k = ktest.KPC(img, ems_pages=88); k.start()
        sh = Shell(k)
        sh.run('copy a:lcmd.com m:a.com'); sh.run('md m:\\d'); sh.run('copy a:upper.com m:\\d\\u.com')
        k.key('exit'); k.key(ktest.ENTER); k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
        h0, n0, mi0 = md_info(k)
        k.pc.warm_boot(ems); k.settle(10)
        h, n, mi = md_info(k)
        fs = fatcheck.read_files(mi, 'M') if n else {}
        what = 'EMS kept' if ems == 'keep' else 'EMS lost' if ems == 'lose' else "M:'s first page lost"
        if kept:
            ok = fs.get('M:\\A.COM') == gc and 'M:\\D\\U.COM' in fs and not fatcheck.check(mi)[0]
        else:
            ok = n == 16 and not fs and not fatcheck.check(mi)[0]
        check('a warm restart (%s): M: %s' % (what, 'keeps its files' if kept else 'made new, empty'), ok and not k.crashed, (sorted(fs), k.crashed))
    k = ktest.KPC(img, ems_pages=88); k.start()
    sh = Shell(k)
    sh.run('copy a:lcmd.com m:a.com'); sh.run('echo MDISK=128> a:\\lode.ini')
    k.key('exit'); k.key(ktest.ENTER); k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    k.pc.warm_boot('keep'); k.settle(10)
    h, n, mi = md_info(k)
    check('a warm restart after MDISK= changed (128 KB): M: made new at that size', n == 8 and not fatcheck.read_files(mi, 'M'), n)

EMS_PAGE = 0x4000

def ems_rec(k, i):
    """EMS handle i's record: (start in ems_ltab (FFh: closed), pages, owner)"""
    b = k.rd('ems_h', 4, 4 * i)
    return b[0], b[1], b[2] | b[3] << 8

def t_mdreview():
    """The review's cases (0.3.14), each of which failed before its fix: a
    closed file's slot on M: isn't an open file; EXEC with a drive the
    kernel doesn't have ("F:X.EXE") overran ex_name; M:'s EMS handle
    closed by a program by mistake and given to another: M: neither writes
    into its pages nor closes it; M: turned off doesn't come back at a warm
    restart; no EMS handle free; called from inside INT 21h; the current
    drive M: kept through a new size."""
    gc = open(os.path.join(GOS, 'src', 'LCMD.COM'), 'rb').read()
    img = image('mdr.img', os.path.join(GOS, 'src', 'LCMD.COM'), MDTEST)
    k = ktest.KPC(img, ems_pages=88); k.start()
    sh = Shell(k)
    sh.run('copy a:lcmd.com m:\\')
    o = sh.run('mdtest /s 64')
    check('COPY to M:, then a new size at once: done, not "a file is open" (the copy\'s closed slot keeps its drive and mode)',
          md_size(o) == ('00', 64), o)
    # EXEC "F:X.EXE": full_name took F:'s "current directory" from past
    # cwdstr (bounce, here as a floppy read across 64 KB leaves it), with no
    # end, over ex_name and on into KEMS
    sh.run('copy a:mdtest.com m:\\'); sh.run('m:')
    past = k.pc.rd(0x60, k.Y['bss_end'], 64)
    k.wr('bounce', b'A' * 450, 0x3E)
    o1, o2 = sh.run('mdtest /x f:x.exe'), sh.run('mdtest /x 1:x.exe')
    c = [re.search(r'exec (\w\w)', o) for o in (o1, o2)]
    check('EXEC "F:X.EXE" and "1:X.EXE": refused (%s), the kernel\'s memory past its BSS (KEMS) as it was, INT 67h still right' %
          ', '.join(m.group(1) if m else '?' for m in c),
          all(m and m.group(1) != '00' for m in c) and k.pc.rd(0x60, k.Y['bss_end'], 64) == past and
          md_query(sh.run('mdtest /q'))[:2] == (64, 64) and not k.crashed, (o1, o2))
    # the current drive M: through a new size
    o = sh.run('a:mdtest /s 128')
    check('a new size with M: the current drive: M: still current (empty, at 128 KB)', md_size(o) == ('00', 128) and
          'M:\\>' in sh.run('ver'), o)
    sh.run('a:')
    # M:'s handle closed by mistake, and a resident program given it
    h, n, _ = md_info(k)
    o = sh.run('mdtest /c %d' % h)
    sh.run('mdtest /h 4')
    tsr = [i for i in range(1, 32) if ems_rec(k, i)[0] != 0xFF and ems_rec(k, i)[1] == 4 and ems_rec(k, i)[2] not in (0,)]
    st, pg, own = ems_rec(k, tsr[0]) if tsr else (0, 0, 0)
    ltab = k.rd('ems_ltab', 128)
    raw = [ltab[st + i] & 0x7F for i in range(pg)]
    snap = [k.pc.ems_read(p, 0, EMS_PAGE) for p in raw]   # (M:'s old disk, likely: the same raw pages)
    o = sh.run('copy a:lcmd.com m:\\z.com')
    for i in range(10):
        if 'Fail?' not in o.rstrip().split('\n')[-1]: break
        k.key('f'); o = '\n'.join(k.pc.text_screen().rstrip().split('\n')[1:])
    kept = lambda: [k.pc.ems_read(p, 0, EMS_PAGE) for p in raw] == snap
    check('M:\'s handle (%d) closed by a program by mistake, then a resident program\'s (%s): COPY to M: refused, '
          'the program\'s pages untouched' % (h, tsr), tsr == [h] and '1 File(s) copied' not in o and kept() and not k.crashed, o)
    o = sh.run('mdtest /s 0')
    check('... M: off then: the program\'s handle not closed, its pages as they were; M: gone',
          ems_rec(k, h) == (st, pg, own) and kept() and md_size(o) == ('00', 0) and md_info(k)[1] == 0, (ems_rec(k, h), o))
    # no handle free: 82h, as no pages
    busy = [i for i in range(1, 32) if ems_rec(k, i)[0] == 0xFF]
    for i in busy: k.wr('ems_h', bytes((0, 0, 0xFE, 0xFF)), 4 * i)
    o = sh.run('mdtest /s 128')
    for i in busy: k.wr('ems_h', bytes((0xFF, 0, 0, 0)), 4 * i)
    check('every EMS handle in use: 82h (as no EMS free), M: off', md_size(o) == ('82', 0), o)
    # from inside INT 21h (as from a handler or a hot key): 80h, nothing changed
    sh.run('mdtest /s 256')
    state = [0]
    def inside(pc):
        a = (pc.r('cs') * 16 + pc.r('ip')) & 0xFFFFF
        if state[0] == 0 and a == 0x600 + 0x12:
            k.wr('indos', b'\x01'); state[0] = 1
        elif state[0] == 1 and 0x11000 <= a < 0xA0000:
            k.wr('indos', b'\x00'); state[0] = 2
    k.hooks.append(inside)
    o = sh.run('mdtest /s 64')
    k.hooks.remove(inside)
    check('called from inside INT 21h: 80h, M: as it was (256 KB)', md_size(o) == ('80', 256) and md_info(k)[1] == 16
          and state[0] == 2, (o, state))
    # M: off by a program (LODE.INI as it was: no line, 256 KB), then a
    # warm restart (M:'s pages the same again): its first page was
    # cleared, so M: is made new
    k = ktest.KPC(img, ems_pages=88); k.start()
    sh = Shell(k)
    sh.run('copy a:lcmd.com m:\\a.com')
    sh.run('mdtest /s 0')
    k.key('exit'); k.key(ktest.ENTER); k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    k.pc.warm_boot('keep'); k.settle(10)
    h, n, mi = md_info(k)
    check('M: turned off (not through System), then a warm restart: M: made new, empty (not its old files back)',
          n == 16 and not fatcheck.read_files(mi, 'M') and not fatcheck.check(mi)[0], (n, sorted(fatcheck.read_files(mi, 'M')) if n else None))

    # a start-up with MDISK=0 leaves M: off; at a later start-up with M: on
    # again (its pages the same), the old disk must not come back: the
    # start-up without M: cleared its boot sector (md_wipe)
    k = ktest.KPC(img, ems_pages=88); k.start()
    sh = Shell(k)
    sh.run('copy a:lcmd.com m:\\a.com'); sh.run('echo MDISK=0> a:\\lode.ini')
    k.key('exit'); k.key(ktest.ENTER); k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    k.pc.warm_boot('keep'); k.settle(10)
    h, n0, mi = md_info(k)
    sh = Shell(k)
    sh.run('del a:\\lode.ini')
    k.key('exit'); k.key(ktest.ENTER); k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    k.pc.warm_boot('keep'); k.settle(10)
    h, n, mi = md_info(k)
    check('a start-up with MDISK=0, then one with M: on again: M: made new, empty (not the old disk back)',
          not n0 and n == 16 and not fatcheck.read_files(mi, 'M') and not fatcheck.check(mi)[0],
          (n0, n, sorted(fatcheck.read_files(mi, 'M')) if n else None))

def t_lodeboot():
    """A Grid-OS floppy moving to Lodestone: its boot sector still loads
    GRIDOS.SYS; LODEBOOT run at the prompt puts in the one that loads
    LODE.SYS, keeping the BPB, and the disk then boots without GRIDOS.SYS."""
    lodeboot = os.path.join(GOS, 'src', 'LODEBOOT.COM')
    subprocess.run(['nasm', '-f', 'bin', '-o', lodeboot, os.path.join(GOS, 'src', 'LODEBOOT.ASM')], check=True,
                   cwd=os.path.join(GOS, 'src'))
    new = open(os.path.join(GOS, 'src', 'BOOT.BIN'), 'rb').read()
    img = mkimg.build(os.path.join(OUT, 'lb.img'), ['GRIDOS.SYS=' + os.path.join(GOS, 'src', 'LODE.SYS'),
                      os.path.join(GOS, 'src', 'LODE.SYS'), os.path.join(GOS, 'src', 'LCMD.COM'), lodeboot])
    raw = bytearray(open(img, 'rb').read())
    raw[3:11] = b'GRID-OS '                                 # the old loader: GRIDOS.SYS
    k = raw.find(b'LODE    SYS', 0, 512); raw[k:k + 11] = b'GRIDOS  SYS'
    open(img, 'wb').write(raw)
    bpb = bytes(raw[11:0x3E])
    k = ktest.KPC(img); k.start()
    check('the old loader boots GRIDOS.SYS', k.pc.mode() == 0x40 and 'LODEBOOT.COM' in k.exec_list(), k.where())
    sh = Shell(k)
    o = sh.run('lodeboot', 'y')
    s0 = bytes(k.pc.drives[0].img[:512])
    check('LODEBOOT under Lodestone: the new loader, the BPB kept',
          'Done' in o and s0[3:11] == b'LODESTON' and s0[11:0x3E] == bpb and s0[0x3E:] == new[0x3E:], o)
    check('... asking about drive A: (the letter in its place)', 'to drive A:?' in o, o)
    k.pc.drives[0].save(os.path.join(OUT, 'lb2.img'))
    subprocess.run(['mdel', '-i', os.path.join(OUT, 'lb2.img'), '::GRIDOS.SYS'], check=True)
    k = ktest.KPC(os.path.join(OUT, 'lb2.img')); k.start()
    check('then it boots LODE.SYS', k.pc.mode() == 0x40 and 'LODE.SYS' in k.exec_list(), k.where())

def t_gridgpib():
    """GRIDGPIB /U, the standalone driver's unloader, under Lodestone: the
    driver on INT 60h is the kernel's, so nothing is unloaded (it re-pointed
    INT 60h at junk and freed a block it took for the driver's)."""
    gg = os.path.join(GOS, '..', 'tools', 'GRIDGPIB.COM')
    chip = sim7210.NEC7210(sim7210.bus())       # (the kernel's driver only with the chip)
    k = ktest.KPC(image('gg.img', os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(HERE, 'MEMSZ.COM'), gg), chip=chip); k.start()
    check('the kernel\'s GPIB driver on INT 60h', k.pc.u16(0, 0x60 * 4 + 2) == 0x60)
    sh = Shell(k)
    vec, kb, ren = k.pc.rd(0, 0x60 * 4, 4), shell_memsz(sh), chip.ren
    o = sh.run('gridgpib /u && echo EL0 || if errorlevel 5 echo EL5')
    lines = [l.strip() for l in o.split('\n')]
    check('GRIDGPIB /U: refused (built in), exit code 5', 'built into the system' in o and 'EL5' in lines, o)
    check('... INT 60h still the kernel\'s, memory as it was', k.pc.rd(0, 0x60 * 4, 4) == vec and shell_memsz(sh) == kb,
          (k.pc.rd(0, 0x60 * 4, 4).hex(), vec.hex(), kb))
    check('... the bus left alone (REN still on: it sent everyone to local first)', ren and chip.ren, (ren, chip.ren))
    check('... and GRIDGPIB still finds the driver', 'Already installed' in sh.run('gridgpib'))

def t_gpcheck0():
    """02h AL=3 (the frame check appended) with no bytes: the check of nothing, 01 00, whatever ES:SI points at; and
    of two bytes, the second's from 1, 0.  (The start for the first byte's add, set at the write's entry since
    audit3 X30, came from the byte at ES:SI even when there were none.)"""
    com = os.path.join(OUT, 'GPCHK0.COM')
    open(com, 'wb').write(bytes([0xBE, 0x1A, 0x01,          # mov si, ab
                                 0x31, 0xC9, 0xBB, 0x06, 0x00, 0xB8, 0x03, 0x02, 0xCD, 0x60,   # CX = 0 to 6, AL = 3
                                 0xB9, 0x02, 0x00, 0xB8, 0x03, 0x02, 0xCD, 0x60,               # CX = 2
                                 0xB8, 0x00, 0x4C, 0xCD, 0x21]) + b'AB')
    chip = sim7210.NEC7210(sim7210.bus())
    got, dev = [], chip.devices[6]
    dev.message = lambda m, f=dev.message: (got.append(bytes(m)), f(m))
    k = ktest.KPC(image('gpchk0.img', com), chip=chip); k.start()
    k.run_file('GPCHK0.COM', 10)
    check('02h AL=3 of no bytes sends the check 01 00; of "AB", AB 43 43', got == [b'\x01\x00', b'AB\x43\x43'], got)

def t_gpirq():
    """SRQ on IRQ 5: the start-up hooks INT 0Dh (keeping the BIOS's vector for the exception) with GPIBIRQ=0 too;
    INT 60h AH=0Eh AL=1 turns the interrupt on again with that vector, AL=0 off."""
    com = os.path.join(OUT, 'GPIRQ.COM')
    open(com, 'wb').write(bytes([0xB8, 0x01, 0x0E, 0xCD, 0x60,              # mov ax, 0E01h / int 60h
                                 0xB8, 0x00, 0x4C, 0xCD, 0x21]))            # mov ax, 4C00h / int 21h
    com0 = os.path.join(OUT, 'GPIRQ0.COM')
    open(com0, 'wb').write(bytes([0xB8, 0x00, 0x0E, 0xCD, 0x60, 0xB8, 0x00, 0x4C, 0xCD, 0x21]))
    for ini in (b'', b'GPIBIRQ=0\r\n'):
        files = (com, com0)
        k = ktest.KPC(ini_image('gpirq.img', ini, *files) if ini else image('gpirq.img', *files),
                      chip=sim7210.NEC7210(sim7210.bus()))
        bios = k.pc.rd(0, 0x0D * 4, 4)
        k.start()
        on = lambda: (k.rd('gp_irq', 1)[0], k.pc.pic_mask & 0x20, k.rd('gp_imr2', 1)[0],
                      k.pc.u16(0, 0x0D * 4), k.pc.u16(0, 0x0D * 4 + 2), k.rd('gp_oldirq', 4) == bios)
        isr = (k.Y['gp_isr'], 0x60, True)
        tag = 'GPIBIRQ=0' if ini else 'at start-up'
        check('%s: INT 0Dh ours, the BIOS\'s vector kept; IRQ 5 %s' % (tag, 'masked' if ini else 'on, SRQI in IMR2'),
              on() == ((0, 0x20, 0) if ini else (5, 0, 0x40)) + isr, on())
        k.run_file('GPIRQ0.COM', 10)
        check('... AH=0Eh AL=0: off, the vector stays', on() == (0, 0x20, 0) + isr, on())
        k.run_file('GPIRQ.COM', 10)
        check('... AH=0Eh AL=1: on again, the same vector, the BIOS\'s still kept', on() == (5, 0, 0x40) + isr, on())

def t_exerel():
    """An .EXE whose relocation table is cut off: EXEC refuses it (11) rather
    than applying entries nobody read (they would be what ex_rel held from
    before: the INT 21h stack's low area since K2); the whole one runs."""
    import struct
    code = bytes([0x0E, 0x1F, 0xBA, 0x0E, 0x00, 0xB4, 0x09, 0xCD, 0x21, 0xB8, 0x00, 0x4C, 0xCD, 0x21]) + b'RAN$'
    def exe(nrel, rels=b''):
        size = 32 + len(code) + len(rels)
        hdr = struct.pack('<2s13H', b'MZ', size % 512, (size + 511) // 512, nrel, 2, 0x20, 0x20,
                          1, 0x100, 0, 0, 0, 32 + len(code), 0)
        return hdr + bytes(32 - len(hdr)) + code + rels
    for n, data in (('CUT.EXE', exe(3)), ('WHOLE.EXE', exe(1, struct.pack('<HH', 0x30, 0)))):
        open(os.path.join(OUT, n), 'wb').write(data)
    k = ktest.KPC(image('exe.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'CUT.EXE=' + os.path.join(OUT, 'CUT.EXE'),
                        'WHOLE.EXE=' + os.path.join(OUT, 'WHOLE.EXE'))); k.start()
    sh = Shell(k)
    src = open(os.path.join(GOS, 'src', 'KFILE.INC')).read()
    eq = lambda n: int(re.search(r'^%s\s+equ\s+(\d+)' % n, src, re.M).group(1))
    refs = lambda: [k.pc.rd(0x60, k.Y['sft'] + i * eq('SFT_SZ') + eq('S_REF'), 1)[0] for i in range(eq('NSFT'))]
    r0 = refs()
    o = sh.run('cut')
    check('relocation table past the end: not run', 'RAN' not in o and not k.crashed, o)
    check('... the handles it inherited given back (SFT counts as before)', refs() == r0, (r0, refs()))
    o = sh.run('whole')
    check('... the same with its table there: runs', 'RAN' in o and not k.crashed, o)

def t_trunc():
    """CREATE onto a file there (here a redirection): truncated and stamped,
    but bytes 12-21 of its entry, which other systems use (creation time,
    last access), kept as they were."""
    open(os.path.join(OUT, 'KEEP.TXT'), 'wb').write(b'old contents\r\n' * 50)
    k = ktest.KPC(image('trunc.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'KEEP.TXT=' + os.path.join(OUT, 'KEEP.TXT'))); k.start()
    ent = lambda: (lambda b, i: b[i:i + 32])(bytes(k.pc.drives[0].img), bytes(k.pc.drives[0].img).find(b'KEEP    TXT'))
    before = ent()
    sh = Shell(k)
    sh.run('echo new > keep.txt')
    after = ent()
    check('CREATE truncates: the new contents', 'new' in sh.run('type keep.txt') and after[28:32] == bytes([6, 0, 0, 0]), after.hex())
    check('... its entry\'s bytes 12-21 kept (%s)' % before[12:22].hex(), before[12:22] == after[12:22] and any(before[12:22]),
          (before[12:22].hex(), after[12:22].hex()))
    # deleted, then a new file takes its slot (E5h, the first free one):
    # there bytes 12-21 are the deleted file's, so they are zeroed
    at = bytes(k.pc.drives[0].img).find(b'KEEP    TXT')
    sh.run('del keep.txt'); sh.run('echo x > again.txt')
    img = bytes(k.pc.drives[0].img)
    check('... a new file in a deleted one\'s slot: bytes 12-21 zeroed', img[at:at + 11] == b'AGAIN   TXT' and
          img[at + 12:at + 22] == bytes(10), img[at:at + 32].hex())
    probs, _ = fatcheck.check(bytes(k.pc.drives[0].img))
    check('... disk consistent', not probs, probs)

def t_dollar():
    """S4 (2026-10-20 audit): INT 21h 09h's '$' string goes to handle 1 in
    one write, a file's or a device's, not one call a character: redirected
    to a file, the bytes as written and one file_write for the 1,502-byte
    string; an empty string ('$' alone) writes nothing (a write of 0 would
    cut the file there); on the screen, as before."""
    print('== INT 21h 09h in one write (S4)')
    p = os.path.join(OUT, 'DOLLAR.ASM')
    open(p, 'w').write("""org 100h
        mov ah, 40h
        mov bx, 1
        mov cx, 2
        mov dx, ab
        int 21h
        mov ah, 9
        mov dx, none
        int 21h
        mov ah, 9
        mov dx, lng
        int 21h
        mov ax, 4C00h
        int 21h
ab      db 'AB'
none    db '$'
lng     times 1500 db 'x'
        db 'CD$'
""")
    com = os.path.join(OUT, 'DOLLAR.COM')
    subprocess.run(['nasm', '-f', 'bin', '-o', com, p], check=True)
    k = ktest.KPC(image('dollar.img', os.path.join(GOS, 'src', 'LCMD.COM'), com)); k.start()
    sh = Shell(k)
    from unicorn import UC_HOOK_CODE
    at, n = 0x600 + k.Y['file_write'], [0]
    def hk(uc, a, sz, ud):
        if a == at: n[0] += 1
    k.pc.mu.hook_add(UC_HOOK_CODE, hk, None, at, at); k.pc.mu.ctl_flush_tb()
    sh.run('dollar > out.txt')
    got = fatcheck.read_files(k.pc.drives[0].img).get('A:\\OUT.TXT')
    check('DOLLAR > OUT.TXT: 40h\'s "AB", 09h\'s "$" (nothing) and 1,500 x + "CD": the file as written (%s bytes), '
          'in 2 file writes (%d), not 1,504' % (len(got) if got else None, n[0]),
          got == b'AB' + b'x' * 1500 + b'CD' and n[0] == 2, (got and got[:8], n[0]))
    o = sh.run('dollar')
    check('DOLLAR on the screen: AB, then the x\'s and CD, wrapped as tty_out wraps them',
          ('AB' + 'x' * 1500 + 'CD') in o.replace('\n', ''), o[:200])

def t_kmedium():
    """The 2026-10-20 audit's medium-risk kernel batch, where it shows: a
    file over 64 KB through the SFT's copies of its entry (time, date,
    cluster and size in the entry's order); FIND FIRST/NEXT's attributes
    (one scanner for them and the path lookups); standard input from a
    file, and with no handle 0 (stdin_con hands back the SFT); RENAME,
    MKDIR and CREATE of names that can't be made (RENAME onto a wildcard
    name: 3, as GRiD MS-DOS 3.30 says); CD past 8.3 (kept as MS-DOS keeps
    it: ABCDEFGH for ABCDEFGHIJ)."""
    def com(name, src):
        p = os.path.join(OUT, name + '.ASM')
        open(p, 'w').write('org 100h\n' + src + LIB)
        subprocess.run(['nasm', '-f', 'bin', '-o', os.path.join(OUT, name + '.COM'), p], check=True)
        return os.path.join(OUT, name + '.COM')
    LIB = """
hex:    push ax
        shr al, 4
        call .d
        pop ax
        and al, 15
.d:     add al, '0'
        cmp al, '9'
        jbe .p
        add al, 7
.p:     mov dl, al
        mov ah, 2
        int 21h
        ret
"""
    names = com('NAMES', """
        mov si, t
.l:     lodsw
        or ax, ax
        jz .x
        mov bx, ax
        lodsw
        mov dx, ax
        lodsw
        mov di, ax
        push si
        push ds
        pop es
        mov ah, bh
        xor cx, cx
        int 21h
        jc .e
        xor al, al
.e:     call hex
        mov dl, ' '
        mov ah, 2
        int 21h
        pop si
        jmp .l
.x:     mov ax, 4C00h
        int 21h
t       dw 5600h, a, bw, 5600h, a, dot, 3900h, cw, 0, 3C00h, dw_, 0, 3C00h, dot, 0, 0
a       db 'A.TXT', 0
bw      db 'B?.TXT', 0
dot     db '.', 0
cw      db 'C?', 0
dw_     db 'D?.TXT', 0
""")
    Y = ktest.Syms(os.path.join(GOS, 'src', 'LODE.MAP'))
    stdin = com('STDIN', """
        mov si, ops
.l:     lodsb
        or al, al
        jz .x
        mov ah, al
        push si
        int 21h
        call hex
        mov dl, ' '
        mov ah, 2
        int 21h
        pop si
        jmp .l
.x:     mov ax, 4C00h
        int 21h
ops     db 0Bh, 08h, 0Bh, 08h, 0Bh, 08h, 0
""")
    stdk = com('STDK', """
        mov ax, 3D00h           ; A.TXT open ("ab"): its SFT entry where
        mov dx, fname           ;  the stack will be, so int21's SI (the
        int 21h                 ;  caller's SP) points at it
        jc .err
        mov bx, ax
        mov al, [bx+18h]
        xor ah, ah
        mov cx, SFTSZ
        mul cx
        add ax, SFT0
        mov [newsp], ax
        mov ah, 3Eh             ; no handle 0
        xor bx, bx
        int 21h
        mov bp, ops
.l:     mov al, [bp]
        inc bp
        or al, al
        jz .x
        mov ah, al
        cli
        mov [oldsp], sp
        mov sp, [newsp]
        sti
        int 21h
        cli
        mov sp, [oldsp]
        sti
        call hex
        mov dl, ' '
        mov ah, 2
        int 21h
        jmp .l
.err:   mov al, 0EEh
        call hex
.x:     mov ax, 4C00h
        int 21h
ops     db 08h, 07h, 01h, 0Bh, 0
fname   db 'A.TXT', 0
oldsp   dw 0
newsp   dw 0
""".replace('SFT0', str(Y['sft'])).replace('SFTSZ', '44'))
    find = com('FIND', """
        mov si, attrs
.a:     lodsb
        cmp al, 0FFh
        je .x
        push si
        xor ah, ah
        mov cx, ax
        mov dx, pat
        mov ah, 4Eh
        int 21h
.f:     jc .nx
        mov si, 80h + 30
.n:     lodsb
        or al, al
        jz .pe
        mov dl, al
        mov ah, 2
        int 21h
        jmp .n
.pe:    mov dl, ','
        mov ah, 2
        int 21h
        mov ah, 4Fh
        int 21h
        jmp .f
.nx:    mov dl, '/'
        mov ah, 2
        int 21h
        pop si
        jmp .a
.x:     mov ax, 4C00h
        int 21h
attrs   db 00h, 02h, 04h, 10h, 08h, 16h, 0FFh
pat     db '*.*', 0
""")
    open(os.path.join(OUT, 'AB.TXT'), 'wb').write(b'ab')
    big = bytes((i * 7 + i // 251) & 0xFF for i in range(100000))
    open(os.path.join(OUT, 'BIG.BIN'), 'wb').write(big)
    img = image('kmed.img', os.path.join(GOS, 'src', 'LCMD.COM'), names, stdin, stdk, find, 'A.TXT=' + os.path.join(OUT, 'AB.TXT'),
                'HID.TXT=' + os.path.join(OUT, 'AB.TXT'), 'SYS.TXT=' + os.path.join(OUT, 'AB.TXT'), 'SUB\\', 'ABCDEFGH\\',
                'A.B\\', 'BIG.BIN=' + os.path.join(OUT, 'BIG.BIN'))
    subprocess.run(['mattrib', '-i', img, '+h', '::HID.TXT'], check=True)
    subprocess.run(['mattrib', '-i', img, '+s', '::SYS.TXT'], check=True)
    k = ktest.KPC(img, image('kmedb.img')); k.start()
    reads0 = [c for c in k.pc.calls13 if c[0] == 2 and c[1] == 0 and c[2:5] == (0, 0, 1)]
    check("booted: A: mounted from the boot sector's BPB start was given (no INT 13h read of A:'s sector 0 for it)",
          not reads0, reads0)
    sh = Shell(k)
    fs = lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
    o = sh.run('copy big.bin big2.bin') + sh.run('copy big.bin b:big3.bin') + sh.run('copy b:big3.bin big4.bin')
    f = fs()
    fb = fatcheck.read_files(bytes(k.pc.drives[1].img))
    probs = fatcheck.check(bytes(k.pc.drives[0].img))[0] + fatcheck.check(bytes(k.pc.drives[1].img))[0]
    check('a file over 64 KB read and written through the SFT (its entry\'s size, cluster, time, date): %d bytes, on A:, '
          'from A: to B: and back (each read and write on its own drive)' % len(big),
          f.get('A:\\BIG2.BIN') == big and fb.get('A:\\BIG3.BIN') == big and f.get('A:\\BIG4.BIN') == big and not probs,
          (len(f.get('A:\\BIG2.BIN', b'')), len(fb.get('A:\\BIG3.BIN', b'')), len(f.get('A:\\BIG4.BIN', b'')), probs, o))
    sh.run('find > fo.txt')
    o = fs().get('A:\\FO.TXT', b'').decode('latin-1')
    got = [set(x for x in part.split(',') if x) for part in o.split('/')[:6]]
    plain = {'LODE.SYS', 'LCMD.COM', 'NAMES.COM', 'STDIN.COM', 'STDK.COM', 'FIND.COM', 'A.TXT', 'BIG.BIN', 'BIG2.BIN', 'BIG4.BIN',
             'FO.TXT'}
    want = [plain, plain | {'HID.TXT'}, plain | {'SYS.TXT'}, plain | {'SUB', 'ABCDEFGH', 'A.B'}, {'LODESTON.E'},
            plain | {'HID.TXT', 'SYS.TXT', 'SUB', 'ABCDEFGH', 'A.B'}]
    check('FIND FIRST/NEXT with 0, hidden, system, directory, the label alone (as 8.3: LODESTON.E), all three: those entries each time',
          got == want, (o, got))
    sh.run('stdin < a.txt > o1.txt'); sh.run('stdk > o2.txt')
    f = fs()
    check('standard input from a file ("ab"): 0Bh, 08h each time FF a FF b, then at its end 00 and 1Ah; with no handle 0 '
          '(and SI at another open file\'s SFT entry): 08h, 07h, 01h 1Ah, 0Bh 00',
          f.get('A:\\O1.TXT') == b'FF 61 FF 62 00 1A ' and f.get('A:\\O2.TXT') == b'1A 1A \x1a1A 00 ',   # (01h echoes it)
          (f.get('A:\\O1.TXT'), f.get('A:\\O2.TXT')))
    sh.run('names > no.txt')
    o = fs().get('A:\\NO.TXT', b'')
    check('RENAME onto B?.TXT: 3 (as MS-DOS 3.30); onto ".": 5; MKDIR C?: 3; CREATE D?.TXT: 2 (as MS-DOS); CREATE ".": 5',
          o.split() == [b'03', b'05', b'03', b'02', b'05'], o)
    o = sh.run('cd abcdefghij')
    o2 = sh.run('cd')
    sh.run('cd \\')
    check('CD ABCDEFGHIJ: the directory ABCDEFGH, kept 8.3 (A:\\ABCDEFGH, as MS-DOS keeps it)',
          o.rstrip().endswith('A:\\ABCDEFGH>') and 'A:\\ABCDEFGH\n' in o2 + '\n', (o, o2))
    outs = [sh.run(c) for c in ('cd a.b.c', 'cd \\a.b.c\\made', 'cd a.b.c\\..')]
    check('CD A.B.C, CD \\A.B.C\\MADE, CD A.B.C\\.. (A.B there): "Invalid directory" each time, still A:\\ (a second dot '
          'is no name, as MS-DOS 3.30 says)', all('Invalid directory' in o and o.rstrip().endswith('A:\\>') for o in outs), outs)
    probs, _ = fatcheck.check(bytes(k.pc.drives[0].img))
    check('... disk consistent', not probs, probs)


def t_renfull():
    """RENAME in a subdirectory full to its last entry: dir_slot gives the directory a cluster more, in the FAT kept
    in memory.  That cluster is linked on the disk before the old entry is deleted there (audit3 X31); the FAT was
    written last, so power lost between the two left the file with no entry at all, its clusters lost."""
    one = os.path.join(OUT, 'ONE.TXT')
    open(one, 'wb').write(b'x\r\n')
    k = ktest.KPC(image('renfull.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'SUB\\',
                        *['SUB\\F%02d.TXT=%s' % (i, one) for i in range(14)]))   # (with . and .., 16: one sector)
    k.start()
    pc, d = k.pc, k.pc.drives[0]
    def fat(img, cl):                   # (1.44 MB FAT12: FAT 1 at LBA 1, cluster 2 at LBA 33)
        v = img[512 + cl * 3 // 2] | img[512 + cl * 3 // 2 + 1] << 8
        return v >> 4 if cl & 1 else v & 0xFFF
    def ents(img, cl): return [bytes(img[(31 + cl) * 512 + i * 32:(31 + cl) * 512 + i * 32 + 32]) for i in range(16)]
    img = bytes(d.img)
    sub = next(e[26] | e[27] << 8 for e in (img[19 * 512 + i * 32:19 * 512 + i * 32 + 32] for i in range(224))
               if e[:11] == b'SUB        ')
    old = [e[:11] for e in ents(img, sub)].index(b'F00     TXT')
    check('SUB is full: 16 entries in its one cluster', fat(img, sub) >= 0xFF8
          and all(e[0] not in (0, 0xE5) for e in ents(img, sub)), [e[:11] for e in ents(img, sub)])
    seen = []                           # the disk as the old entry's E5 reaches it
    int13 = pc.int13
    def hook():
        ah = pc.r('ah')
        int13()
        if ah == 3 and not seen and d.img[(31 + sub) * 512 + old * 32] == 0xE5:
            new = fat(d.img, sub)
            seen.append((new, 2 <= new < 0xFF8 and b'G00     TXT' in [e[:11] for e in ents(d.img, new)]))
    pc.int13 = hook
    k.code_p()
    k.key('ren sub\\f00.txt g00.txt'); k.key(ktest.ENTER)
    del pc.int13
    check('RENAME in a full SUB: when the old entry is deleted on the disk, the FAT there already links SUB\'s new '
          'cluster, which holds the new entry', seen and seen[0][1], (seen, hex(fat(d.img, sub))))
    probs, files = fatcheck.check(bytes(d.img))
    check('... and the disk is consistent afterwards, G00.TXT in SUB, F00.TXT gone', not probs
          and '\\SUB\\G00.TXT' in files and '\\SUB\\F00.TXT' not in files, (probs, sorted(files)))

def t_fatstraddle():
    """fat_set: a FAT12 entry across two sectors (1.44 MB: 341 at bytes 511-512, 682 at 1023-1024) marks both
    changed; deleting a file whose chain ends there writes the second sector too, though nothing else changed in it."""
    com = os.path.join(OUT, 'DELF.COM')     # DELF.COM: delete the file named in its command tail (PSP 82h, CR-ended)
    open(com, 'wb').write(bytes([0xBE, 0x82, 0x00, 0x89, 0xF2, 0xAC, 0x3C, 0x0D, 0x75, 0xFB, 0xC6, 0x44, 0xFF, 0x00,
                                 0xB4, 0x41, 0xCD, 0x21, 0xB8, 0x00, 0x4C, 0xCD, 0x21]))
    def mk(n1, n2):
        b1 = os.path.join(OUT, 'BIG1.DAT'); open(b1, 'wb').write(b'\x11' * (n1 * 512))
        b2 = os.path.join(OUT, 'BIG2.DAT'); open(b2, 'wb').write(b'\x22' * (n2 * 512))
        return image('straddle.img', os.path.join(GOS, 'src', 'LCMD.COM'), com, b1, b2)
    def ent(img, n, copy=0):            # (FAT 1 at LBA 1, FAT 2 at LBA 10)
        v = struct.unpack_from('<H', img, 512 + copy * 9 * 512 + n * 3 // 2)[0]
        return v >> 4 if n & 1 else v & 0xFFF
    raw = open(mk(10, 10), 'rb').read()     # where BIG1 starts, from its entry
    s1 = next(struct.unpack_from('<H', raw, 19 * 512 + i * 32 + 26)[0] for i in range(224)
              if raw[19 * 512 + i * 32:19 * 512 + i * 32 + 11] == b'BIG1    DAT')
    img = mk(341 - s1 + 1, 682 - 342 + 1)
    raw = open(img, 'rb').read()
    check('the image: BIG1 ends at cluster 341, BIG2 is 342-682', ent(raw, 341) == 0xFFF and ent(raw, 342) == 343
          and ent(raw, 682) == 0xFFF, (ent(raw, 341), ent(raw, 342), ent(raw, 682)))
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    assert run_long(k, 'delf big2.dat')
    d = bytes(k.pc.drives[0].img)
    check('BIG2 deleted: entry 682 (bytes 1023-1024, sectors 1 and 2) free on the disk in both copies, no lost clusters',
          ent(d, 682) == 0 and ent(d, 682, 1) == 0 and ent(d, 342) == 0 and not fatcheck.check(d)[0],
          (ent(d, 682), ent(d, 682, 1), fatcheck.check(d)[0]))
    assert run_long(k, 'delf big1.dat')
    d = bytes(k.pc.drives[0].img)
    check('BIG1 deleted: entry 341 (bytes 511-512, sectors 0 and 1) free on the disk in both copies, no lost clusters',
          ent(d, 341) == 0 and ent(d, 341, 1) == 0 and not fatcheck.check(d)[0], (ent(d, 341), ent(d, 341, 1), fatcheck.check(d)[0]))

def ms_build(name, com=None):
    """tests/NAME.ASM (PROBE.INC's driver, or ATTR's or NODISK's own) -> OUT/com (NAME.COM)."""
    com = os.path.join(OUT, com or name + '.COM')
    subprocess.run(['nasm', '-f', 'bin', '-i', HERE + '/', '-o', com, os.path.join(HERE, name + '.ASM')], check=True)
    return com

def ms_probe(k, name, what, sim_s=30):
    """Run the probe NAME > OUT.TXT at the prompt, and check its "fn" lines against NAME_MS.TXT's, GRiD MS-DOS
    3.30's answers (recorded in the emulator from its ROM image): `what` % how many.  -> the disk's files."""
    assert run_long(k, name.lower() + ' > out.txt', sim_s)
    f = fatcheck.read_files(bytes(k.pc.drives[0].img))
    fn = lambda t: [' '.join(l.split()) for l in t.replace('\r', '').split('\n') if l.startswith('fn ')]   # (spaces as one)
    got = fn(f.get('A:\\OUT.TXT', b'').decode('latin-1'))
    want = fn(open(os.path.join(HERE, name + '_MS.TXT'), encoding='latin-1').read())
    check(what % len(want), got == want, [(w, g) for w, g in zip(want, got) if w != g][:8] or (len(want), len(got)))
    return f

def t_names():
    """Names that are no names (a second dot, a bad character), device names,
    CREATE over hidden and system files: NAMES.COM's 58 calls answer as GRiD
    MS-DOS 3.30's do, and nothing is deleted, renamed or truncated that MS-DOS
    leaves alone (B.TXT.X deleted B.TXT, E.F.G removed E.F, A.TXT became C.D,
    MKDIR CON made a directory)."""
    com = ms_build('NAMES', 'NAMES_MS.COM')               # (t_kmedium has a NAMES.COM of its own)
    names = ('a', 'b', 'hid', 'hid2', 'hid3', 'sys', 'sys2', 'hs', 'hs2', 'ro', 'clock', 'x')
    for n in names:
        open(os.path.join(OUT, 'NM_%s.TXT' % n), 'wb').write(n.encode() + b'\r\n')
    img = image('names.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'NAMES.COM=' + com,
                *['%s.TXT=%s' % (n.upper(), os.path.join(OUT, 'NM_%s.TXT' % n)) for n in names if n != 'x'])
    m = lambda *a: subprocess.run(list(a), check=True, stdin=subprocess.DEVNULL, capture_output=True)
    m('mmd', '-i', img, '::A.B'); m('mmd', '-i', img, '::E.F')
    m('mcopy', '-i', img, os.path.join(OUT, 'NM_x.TXT'), '::A.B/X.TXT')
    for n, a in (('HID', 'h'), ('HID2', 'h'), ('HID3', 'h'), ('SYS', 's'), ('SYS2', 's'), ('RO', 'r')):
        m('mattrib', '-i', img, '+' + a, '::%s.TXT' % n)
    for n in ('HS', 'HS2'):
        m('mattrib', '-i', img, '+h', '+s', '::%s.TXT' % n)
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    ms_probe(k, 'NAMES', "NAMES.COM: all %d calls answer as GRiD MS-DOS 3.30's do (a second dot or a bad character: 2 "
             "from OPEN, CREATE and EXEC on the last part, 3 otherwise; a device's name, where its directory is there: "
             "5 for MKDIR, RMDIR, DELETE and RENAME onto it (RENAME's old name looked up first); CREATE over a hidden "
             "or system file not asking for it: 5)")
    dl = []; f = fatcheck.read_files(bytes(k.pc.drives[0].img), dirs=dl)
    keep = {n: (n.lower()[:-4] + '\r\n').encode() for n in ('B.TXT', 'A.TXT', 'HS.TXT', 'SYS2.TXT', 'RO.TXT')}
    check('... and the disk as MS-DOS leaves it: HID, SYS and CLOCK.TXT deleted, HID2, HID3 and HS2 made empty; B, A, '
          'HS, SYS2 and RO.TXT as they were, E.F there; no C.D, no directory CON, NUL, CLOCK or CLOCK$',
          all(f.get('A:\\' + n) == v for n, v in keep.items()) and 'A:\\E.F' in dl
          and not {'A:\\HID.TXT', 'A:\\SYS.TXT', 'A:\\CLOCK.TXT', 'A:\\C.D'} & set(f)
          and all(f.get('A:\\%s.TXT' % n) == b'' for n in ('HID2', 'HID3', 'HS2'))
          and not {'A:\\CON', 'A:\\NUL', 'A:\\CLOCK', 'A:\\CLOCK$'} & set(dl), (sorted(f), dl))
    probs, _ = fatcheck.check(bytes(k.pc.drives[0].img))
    check('... disk consistent', not probs, probs)


def run_long(k, cmd, sim_s=30):
    """A command at the prompt that may run past settle()'s 6 s (a probe writing its answers to a file a call at
    a time: its directory entry is written at the close): until the prompt is back.  True if it is"""
    k.key('cls'); k.key(ktest.ENTER)
    k.key(cmd); k.key(ktest.ENTER, settle=False)
    return k.settle(sim_s)

def t_nul():
    """A device's name after a directory (X18, "IF EXIST DIR\\NUL"): OPEN, CREATE and CREATE NEW find the
    device only where the directory is there, [X:]\\DEV\\ in front is the devices' own, and a wildcard or a
    bad name after the directory is 2, as GRiD MS-DOS 3.30 answers; NUL, A:NUL and Q:NUL need no disk."""
    com = ms_build('NULDIR')
    open(os.path.join(OUT, 'NM_a.TXT'), 'wb').write(b'a\r\n')
    img = image('nul.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'NULDIR.COM=' + com,
                'A.TXT=' + os.path.join(OUT, 'NM_a.TXT'), 'A.B\\', 'E.F\\')
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    ms_probe(k, 'NULDIR', "NULDIR.COM: all %d calls answer as GRiD MS-DOS 3.30's do (a device's name behind a directory "
             "that isn't there, or is a file: 3; \\DEV\\ the devices' own; a wildcard or bad name after a directory: 2)")
    o = sh.run('if exist nosuch\\nul echo nosuch') + sh.run('if exist a.b\\nul echo dir') + sh.run('type nul')
    check("... and LCMD (its IF EXIST looks at the directory itself): IF EXIST NOSUCH\\NUL no, A.B\\NUL yes; TYPE NUL",
          'nosuch' not in o.replace('nosuch\\nul', '') and 'dir\n' in o + '\n', o)

def t_devname():
    """Device names by dev_look_ax: DEVNAME.COM's 88 calls (OPEN, then CREATE, of each name) answer as the
    kernel did before its table walk became a length-prefixed table and REPE CMPSB, and its GPIBnn parse AAD;
    each device opened is the same one, with the same GPIB address.  EMMXXXX0 only with EMS."""
    com = os.path.join(OUT, 'DEVNAME.COM')
    subprocess.run(['nasm', '-f', 'bin', '-o', com, os.path.join(HERE, 'DEVNAME.ASM')], check=True)
    for ems in (0, 88):
        k = ktest.KPC(image('devname.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'DEVNAME.COM=' + com, 'A.B\\'),
                      ems_pages=ems)
        at, devs = 0x600 + k.Y['dev_open'], []
        from unicorn import UC_HOOK_CODE                # (exact: pcemu's block hook sees a block it stops the
        k.pc.mu.hook_add(UC_HOOK_CODE, lambda uc, a, size, ud: devs.append(k.pc.r('ax')), None, at, at)  # emulator at twice)
        k.pc.mu.ctl_flush_tb()
        k.start()
        sh = Shell(k)
        assert run_long(k, 'devname > out.txt')
        f = fatcheck.read_files(bytes(k.pc.drives[0].img))
        got = [l.strip() for l in f.get('A:\\OUT.TXT', b'').decode('latin-1').replace('\r', '').split('\n') if l.startswith('fn ')]
        devs = ['%d/%d' % (a & 0xFF, a >> 8) for a in devs]
        want, wdevs = [], []
        for l in DEVNAME_ANS.strip().split('\n'):
            n, o, c, d = l.split()
            if ems and n in DEVNAME_EMS: o, c, d = DEVNAME_EMS[n]
            want += ['fn 3D %s -> %s' % (n, o.replace('e', 'err ')), 'fn 3C %s -> %s' % (n, c.replace('e', 'err '))]
            wdevs += [d] * ((o == 'ok') + (c == 'ok')) if d != '-' else []
        tag = ' (with EMS)' if ems else ''
        check('DEVNAME.COM%s: all %d calls answer as before (CON.X and NUL. a device, NUL.. and NUL.X.Y 2, CONX and '
              'CLOCK$$ files; GPIB00-GPIB30, GPIBn and GPIBnn.X a device, GPIB31, GPIB1Z and GPIB123 files)' % (tag, len(want)),
              got == want, [(w, g) for w, g in zip(want, got) if w != g] or (len(want), len(got)))
        check('... each device opened is the one named, GPIBnn at address nn (%d opens)' % len(wdevs), devs == wdevs, devs)

def t_fcbnames():
    """Names as MS-DOS keeps them (FCBNAMES.COM): a first E5h made as 05h on the disk and given back as E5h, a space
    inside a name made, opened and found; FCB FIND FIRST/NEXT (11h, 12h): the label's 11 bytes through an extended
    FCB (from a subdirectory: the root's), files through a plain one; and 47h's answer in its 64 bytes."""
    com = os.path.join(OUT, 'FCBNAMES.COM')
    subprocess.run(['nasm', '-f', 'bin', '-o', com, os.path.join(HERE, 'FCBNAMES.ASM')], check=True)
    sep = os.path.join(OUT, 'ABXCD.SEP'); open(sep, 'wb').write(b'sep')
    p = image('fcbnames.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'FCBNAMES.COM=' + com, 'SUB\\', 'SUB\\ABXCD.SEP=' + sep)
    img = bytearray(open(p, 'rb').read())
    i = img.find(b'ABXCD   SEP'); img[i + 2] = ord('+')                 # (another system's: a separator in a name)
    at = next(19 * 512 + i for i in range(0, 224 * 32, 32) if img[19 * 512 + i + 11] == 8)
    img[at:at + 11] = b'V1.0  X    '                         # (another system's: a dot, spaces inside)
    open(p, 'wb').write(img)
    k = ktest.KPC(p); k.start()
    sh = Shell(k)
    sh.run('cd sub')
    sh.run('fcbnames c > \\n.out')
    d = bytes(k.pc.drives[0].img)
    o = fatcheck.read_files(d).get('A:\\N.OUT', b'').decode('latin-1').replace('\r', '')
    check('a first E5h (CREATE, then OPEN): made and opened again', 'M \xe5ABC.TXT ok\n' in o, o)
    check('a space inside a name ("AB CD.TXT"): made and opened again, as MS-DOS', 'M AB CD.TXT ok\n' in o, o)
    check('FIND FIRST/NEXT gives both back as made ("\\xe5ABC.TXT", "AB CD.TXT")', 'F \xe5ABC.TXT\n' in o and 'F AB CD.TXT\n' in o, o)
    check('extended FCB FIND FIRST (attribute 08h), from A:\\SUB: the root\'s label, its 11 bytes as on the disk',
          'L [V1.0  X    ]\n' in o, o)
    check('plain FCB FIND FIRST/NEXT of ????????TXT: both, unpacked, the E5h as E5h', 'T [\xe5ABC    TXT]\n' in o
          and 'T [AB CD   TXT]\n' in o and o.count('\nT [') == 2, o)
    check('... a plain FCB\'s "*       txt" (small letters, a *): both, as MS-DOS 3 takes it; one starting E5h: '
          'that one (and the * stays in the name part: not AB CD.DAT)', 'U [\xe5ABC    TXT]\n' in o
          and 'U [AB CD   TXT]\n' in o and o.count('\nU [') == 2 and 'E [\xe5ABC    TXT]\n' in o, o)
    check('... a separator in an FCB\'s name ("AB+CD   SEP", an entry there by that name): nothing (FFh), as MS-DOS\'s '
          'TransFCB; the label with 09h (read-only no matter); 4Eh: *.* with 08h from A:\\SUB nothing (GRiD MS-DOS 3.30: '
          'the path\'s directory, not the root), '
          '\\*.* with 09h the label only, with 3Fh the label among the rest, as MS-DOS\'s', '\nV [' not in o
          and 'K [V1.0  X    ]\n' in o and '\nC ' not in o and o.count('\nB ') == 1 and 'B V1.0  X\n' in o
          and 'A V1.0  X\n' in o and 'A SUB\n' in o, o)
    ents = [d[i:i + 11] for i in range(0, len(d) - 32, 32) if d[i + 11:i + 12] == b'\x20' and d[i + 8:i + 11] == b'TXT']
    check('... on the disk the first E5h is 05h (E5h there is a free entry)', b'\x05ABC    TXT' in ents, ents)
    o = sh.run('dir').replace('\r', '') + sh.run('copy *.txt \\').replace('\r', '')
    check('DIR lists them, COPY *.TXT copies both (the names FIND FIRST gives open)', ' ABC     TXT' in o
          and 'AB CD    TXT' in o and '2 File(s) copied' in o and {'A:\\AB CD.TXT', 'A:\\\x05ABC.TXT'} <= set(fatcheck.read_files(bytes(k.pc.drives[0].img))), o)
    sh.run('cd \\')
    for c in ('AAAAAAAA', 'BBBBBBBB', 'CCCCCCCC', 'DDDDDDDD', 'EEEEEEEE', 'FFFFFFFF', 'GGGGGG', 'HH'):
        sh.run('md ' + c); sh.run('cd ' + c)
    o = sh.run('fcbnames w')
    check('47h in the deepest directory: 63 characters and the NUL, its 64-byte buffer\'s next byte untouched',
          'W 63 G' in o, o)

def t_copycat():
    """COPY's concatenation as MS-DOS 3.30's: one plain destination and a source with wildcards or a "+" list;
    ASCII by default (each source to its first ^Z, one ^Z at the end, none to a device), /B whole files, /A and
    /B by position; each source's name shown and "1 File(s) copied"; "+" with blanks or switches around it, to
    no destination (the first source's), a directory or a wildcard name (made once); the destination as the
    first source kept, cut at its first ^Z, and appended to; met later, "Content of destination lost before
    copy"; a "+" part not there passed over; an empty result deleted; "COPY A+" onto itself, "+,," the date of
    now (in ASCII cut at its first ^Z); ",," ends the list; a first source with wildcards and "+" to no
    destination, a directory or a wildcard name pairs names (MS-DOS's).  And the user's file safe: a
    concatenation that fails (a source not read, or found and not opened; the disk full, at its ^Z too) leaves
    the user's file exactly as it was (more after its first ^Z included), deletes one it made after its own
    write error, keeps and counts it after a source's; no handle left open; lists past 79 characters; a word
    past the destination refused."""
    def mkf(n, b):
        t = os.path.join(OUT, n); open(t, 'wb').write(b); return t
    fl = ['F%02d.TXT=' % i + mkf('cf%02d' % i, b'f%02d' % i) for i in range(14)]
    p = image('cat.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'A.TXT=' + mkf('ca', b'aaa\x1aJUNK'),
              'B.TXT=' + mkf('cb', b'bbb\x1a'), 'C.REF=' + mkf('cc', b'ccc'), 'D.REF=' + mkf('cd2', b'ddd'),
              'BIN1.DAT=' + mkf('cd', b'x\x1ay'), 'G.TXT=' + mkf('cg2', b'ggg\x1a\x1a'), 'B.BAK=' + mkf('cbk', b'KEEP-ME'),
              'E0.LST=' + mkf('ce0', b''), 'E1.LST=' + mkf('ce1', b'\x1a'), 'T.TXT=' + mkf('ct', b'touch'),
              'Q.TXT=' + mkf('cq', b'q-old'), 'R.TXT=' + mkf('cr', b'r-new'), 'P.REF=' + mkf('cpp', b'ppp'),
              'S.REF=' + mkf('css', b'sss'), 'CC.REF=' + mkf('ccc2', b'cc-old'), 'U.REF=' + mkf('cu', b'u\x1aTAIL'),
              'D\\', 'D\\M1.TXT=' + mkf('ce', b'm1'), 'D\\ZZ.TXT=' + mkf('cf', b'zz-old'),
              'E\\', 'E\\AA.TXT=' + mkf('cg', b'aa\x1a'), 'E\\BB.TXT=' + mkf('ch', b'bb'), 'L\\', *['L\\' + f for f in fl])
    k = ktest.KPC(p); k.start()
    sh = Shell(k)
    raw = lambda: bytes(k.pc.drives[0].img)
    fs = lambda: fatcheck.read_files(raw())
    def ent(name, sub=None):
        """a root entry (11-byte name) -> (time, date)"""
        r = raw(); b = fatcheck.bpb(r)
        root = (b['res'] + b['nfat'] * b['spf']) * 512
        for i in range(root, root + b['nroot'] * 32, 32):
            if r[i:i + 11] == name: return struct.unpack_from('<HH', r, i + 22)
    def el(cmd):
        o = sh.run(cmd)
        k.key('if errorlevel 1 echo LVL1'); k.key(ktest.ENTER)
        return o + ('\nE1' if any(l.strip() == 'LVL1' for l in k.pc.text_screen().split('\n')) else '\nE0')
    o = sh.run('copy *.txt cat.dat')
    check('COPY *.TXT CAT.DAT: ASCII, each to its first ^Z, one ^Z at the end; each name shown, "1 File(s) copied"',
          fs().get('A:\\CAT.DAT') == b'aaabbbgggtouchq-oldr-new\x1a' and 'A.TXT' in o and 'B.TXT' in o and '1 File(s) copied' in o,
          (o, fs().get('A:\\CAT.DAT')))
    o = sh.run('copy /b a.txt+b.txt catb.dat')
    check('COPY /B A.TXT+B.TXT CATB.DAT: whole files, nothing added', fs().get('A:\\CATB.DAT') == b'aaa\x1aJUNKbbb\x1a'
          and '1 File(s) copied' in o, (o, fs().get('A:\\CATB.DAT')))
    o = sh.run('copy a.txt+c.ref ac.dat') + sh.run('copy a.txt + c.ref ac2.dat') + sh.run('copy c.ref +a.txt ac3.dat /b')
    f = fs()
    check('COPY A.TXT+C.REF AC.DAT, with blanks around the "+"; /B after the destination is the destination\'s: '
          'the sources ASCII, no ^Z added', f.get('A:\\AC.DAT') == b'aaaccc\x1a' and f.get('A:\\AC2.DAT') == b'aaaccc\x1a'
          and f.get('A:\\AC3.DAT') == b'cccaaa' and o.count('1 File(s) copied') == 3,
          (o, f.get('A:\\AC.DAT'), f.get('A:\\AC2.DAT'), f.get('A:\\AC3.DAT')))
    o = sh.run('copy /b bin1.dat + c.ref/a mix.dat')
    check('/A and /B by position: COPY /B BIN1.DAT + C.REF/A MIX.DAT: BIN1.DAT whole (a later /A doesn\'t cut it), '
          'C.REF and the destination ASCII', fs().get('A:\\MIX.DAT') == b'x\x1ayccc\x1a', (o, fs().get('A:\\MIX.DAT')))
    o = sh.run('copy c.ref+bin1.dat /b nb.dat') + sh.run('copy /b bin1.dat + c.ref /a mix2.dat')
    f = fs()
    check('a switch after the last source but before the destination is that source\'s (MS-DOS\'s SWITCH, past the '
          'blanks): C.REF+BIN1.DAT /B NB.DAT: BIN1.DAT whole, and the destination binary (no ^Z); /B BIN1.DAT + C.REF '
          '/A MIX2.DAT: C.REF and the destination ASCII', f.get('A:\\NB.DAT') == b'cccx\x1ay'
          and f.get('A:\\MIX2.DAT') == b'x\x1ayccc\x1a', (o, f.get('A:\\NB.DAT'), f.get('A:\\MIX2.DAT')))
    o = sh.run('copy bin1.dat /b /a bin6.dat') + sh.run('copy bin1.dat bin7.dat /b /a') + sh.run('copy bin1.dat /b /a+c.ref m3.dat')
    f = fs()
    check('/B and /A on one name, the source\'s or the destination\'s: both for nothing (MS-DOS\'s SETASC): a binary '
          'single copy; in a concatenation its ASCII', f.get('A:\\BIN6.DAT') == b'x\x1ay' and f.get('A:\\BIN7.DAT') == b'x\x1ay'
          and f.get('A:\\M3.DAT') == b'xccc\x1a', (o, f.get('A:\\BIN6.DAT'), f.get('A:\\BIN7.DAT'), f.get('A:\\M3.DAT')))
    o = sh.run('copy s.ref/+c.ref sc.dat')
    check('"/" then "+" is no switch (COPY S.REF/+C.REF SC.DAT): the two, in one', fs().get('A:\\SC.DAT') == b'sssccc\x1a',
          (o, fs().get('A:\\SC.DAT')))
    o = sh.run('copy s.ref+,, cc.ref')
    f = fs()
    check('",," after a "+" ends the list (MS-DOS\'s CPARSE): COPY S.REF+,, CC.REF: CC.REF the destination, S.REF\'s '
          '(ASCII), S.REF as it was', f.get('A:\\CC.REF') == b'sss\x1a' and f.get('A:\\S.REF') == b'sss',
          (o, f.get('A:\\CC.REF')))
    o = sh.run('copy p.ref+s.ref+p.ref')
    check('COPY P.REF+S.REF+P.REF: P.REF kept, S.REF after it; P.REF met again: "Content of destination lost before '
          'copy", passed over', fs().get('A:\\P.REF') == b'pppsss\x1a' and 'Content of destination lost before copy' in o,
          (o, fs().get('A:\\P.REF')))
    o = sh.run('copy u.ref+,,')
    check('COPY U.REF+,, (ASCII): cut at its first ^Z, as MS-DOS (U.REF was u^ZTAIL)', fs().get('A:\\U.REF') == b'u\x1a',
          (o, fs().get('A:\\U.REF')))
    c0 = fs().get('A:\\C.REF'), fs().get('A:\\D.REF')
    o = sh.run('copy a.txt + /b c.ref out.dat') + sh.run('copy a.txt+/a d.ref out2.dat') + sh.run('copy a.txt/b+c.ref cat2.dat')
    f = fs()
    check('a switch next to a "+" (A.TXT + /B C.REF OUT.DAT, A.TXT+/A D.REF, A.TXT/B+C.REF): the list goes on past it, '
          'the destination the word after; C.REF and D.REF untouched', (f.get('A:\\C.REF'), f.get('A:\\D.REF')) == c0
          and f.get('A:\\OUT.DAT') == b'aaaccc' and f.get('A:\\OUT2.DAT') == b'aaaddd\x1a'
          and f.get('A:\\CAT2.DAT') == b'aaa\x1aJUNKccc', (o, f.get('A:\\OUT.DAT'), f.get('A:\\OUT2.DAT'), f.get('A:\\CAT2.DAT')))
    o = el('copy a.txt b.dat c.dat')
    check('a word past the destination (COPY A.TXT B.DAT C.DAT): "Too many parameters", nothing made, ERRORLEVEL 1',
          'Too many parameters' in o and 'A:\\B.DAT' not in fs() and 'A:\\C.DAT' not in fs() and o.endswith('E1'), o)
    o = sh.run('copy bin1.dat/a bin4.dat') + sh.run('copy bin1.dat bin5.dat/a') + sh.run('copy bin1.dat bin2.dat')
    f = fs()
    check('a switch stuck to a name: BIN1.DAT/A (the source ASCII, and the destination after it), BIN5.DAT/A (the '
          'destination only); a single copy binary', f.get('A:\\BIN4.DAT') == b'x\x1a' and f.get('A:\\BIN5.DAT') == b'x\x1ay\x1a'
          and f.get('A:\\BIN2.DAT') == b'x\x1ay', (o, f.get('A:\\BIN4.DAT'), f.get('A:\\BIN5.DAT'), f.get('A:\\BIN2.DAT')))
    long = '+'.join('f%02d.txt' % i for i in range(14))
    sh.run('cd l')
    o = sh.run('copy ' + long + ' all.dat')
    sh.run('cd \\')
    check('a "+" list of %d characters (14 files): every one, in order' % len(long),
          fs().get('A:\\L\\ALL.DAT') == b''.join(b'f%02d' % i for i in range(14)) + b'\x1a' and 'File not found' not in o,
          (o, fs().get('A:\\L\\ALL.DAT')))
    o = sh.run('copy a.txt+' + 'x' * 80 + ' long.dat')
    check('a name in the list past 79 characters: "Invalid path or file name", nothing made',
          'Invalid path or file name' in o and 'A:\\LONG.DAT' not in fs(), o)
    o = sh.run('copy a.txt+b.txt *.bak')
    f = fs()
    check('COPY A.TXT+B.TXT *.BAK: one destination, A.BAK (the name made once, from the first source, as MS-DOS); '
          'B.BAK, there before, untouched', f.get('A:\\A.BAK') == b'aaabbb\x1a' and f.get('A:\\B.BAK') == b'KEEP-ME', (o, f.get('A:\\A.BAK'), f.get('A:\\B.BAK')))
    k.pc.tty.clear()
    o = sh.run('copy a.txt+c.ref con')
    t = ''.join(k.pc.tty)
    check('to a device (COPY A.TXT+C.REF CON): the text (each name before its own), no ^Z between or after, '
          '"1 File(s) copied"', 'A.TXT\r\naaaC.REF\r\nccc' in t and '\x1a' not in t and '1 File(s) copied' in t, repr(t[-200:]))
    k.key('cls'); k.key(ktest.ENTER)
    k.key('copy con+c.ref cona.dat'); k.key(ktest.ENTER); k.key('typed'); k.key(ktest.ENTER); k.key('\x1a'); k.key(ktest.ENTER)
    check('a device in a list (COPY CON+C.REF CONA.DAT): what was typed, then C.REF, one ^Z',
          fs().get('A:\\CONA.DAT') == b'typed\r\nccc\x1a', (k.pc.text_screen(), fs().get('A:\\CONA.DAT')))
    k.key('cls'); k.key(ktest.ENTER); k.pc.tty.clear()
    k.key('copy con+c.ref'); k.key(ktest.ENTER); k.key('hi'); k.key(ktest.ENTER); k.key('\x1a'); k.key(ktest.ENTER)
    t = ''.join(k.pc.tty)
    check('COPY CON+C.REF (no destination: CON, the first source\'s, a device): to the screen, no "onto itself", '
          'no file made', 'ccc' in t and 'onto itself' not in t and '1 File(s) copied' in t
          and not any(n.startswith('A:\\CON') and n != 'A:\\CONA.DAT' for n in fs()), repr(t[-200:]))
    o = el('copy nosuch.ref+a.txt+nosuch2.ref+c.ref anc.dat')
    check('"+" parts not there (first and in the middle): passed over without a word, ERRORLEVEL 0, the rest copied',
          fs().get('A:\\ANC.DAT') == b'aaaccc\x1a' and 'File not found' not in o and o.endswith('E0'), (o, fs().get('A:\\ANC.DAT')))
    o = sh.run('copy *.xyz all2.dat')
    check('... a wildcard concatenation that finds nothing: "File not found"', 'File not found' in o and 'A:\\ALL2.DAT' not in fs(), o)
    o = sh.run('copy e0.lst+e1.lst ez.dat')
    check('a concatenation that comes out empty (0 bytes, then only a ^Z): deleted, "0 File(s) copied"',
          'A:\\EZ.DAT' not in fs() and '0 File(s) copied' in o, (o, sorted(fs())))
    a0 = fs().get('A:\\A.TXT')
    o = sh.run('copy a.txt+')
    check('COPY A.TXT+: "File cannot be copied onto itself", A.TXT as it was (its JUNK after the ^Z too)',
          'cannot be copied onto itself' in o and fs().get('A:\\A.TXT') == a0, (o, fs().get('A:\\A.TXT')))
    o = sh.run('copy a.txt+c.ref') + sh.run('copy g.txt+c.ref') + sh.run('copy b.txt+c.ref')
    f = fs()
    check('the destination the first source: cut at its first ^Z (A.TXT\'s JUNK, G.TXT\'s second ^Z), the rest '
          'appended, one ^Z', f.get('A:\\A.TXT') == b'aaaccc\x1a' and f.get('A:\\G.TXT') == b'gggccc\x1a'
          and f.get('A:\\B.TXT') == b'bbbccc\x1a' and 'onto itself' not in o, (o, f.get('A:\\A.TXT'), f.get('A:\\G.TXT')))
    o = sh.run('copy r.txt+c.ref q.txt')
    check('COPY R.TXT+C.REF Q.TXT (Q.TXT not in the list): made afresh from them', fs().get('A:\\Q.TXT') == b'r-newccc\x1a', (o, fs().get('A:\\Q.TXT')))
    o = sh.run('copy c.ref+bin1.dat d')
    check('COPY C.REF+BIN1.DAT D (a directory): D\\C.REF, the two in it', fs().get('A:\\D\\C.REF') == b'cccx\x1a', (o, fs().get('A:\\D\\C.REF')))
    o = sh.run('copy d\\*.txt d\\zz.txt')
    check('COPY D\\*.TXT D\\ZZ.TXT, ZZ.TXT found after the copy made it: "Content of destination lost before copy", '
          'the rest kept on', fs().get('A:\\D\\ZZ.TXT') == b'm1\x1a' and 'Content of destination lost before copy' in o
          and '1 File(s) copied' in o, (o, fs().get('A:\\D\\ZZ.TXT')))
    o = sh.run('copy e\\*.txt e\\aa.txt')
    check('COPY E\\*.TXT E\\AA.TXT, AA.TXT the first found: kept, BB.TXT appended (over its ^Z), not "onto itself"',
          fs().get('A:\\E\\AA.TXT') == b'aabb\x1a' and 'onto itself' not in o and '1 File(s) copied' in o, (o, fs().get('A:\\E\\AA.TXT')))
    # dates: a binary single copy keeps its source's; a concatenation, /A and "+,," get the clock's
    src_d = ent(b'BIN1    DAT')
    sh.run('copy bin1.dat bdate.dat'); sh.run('copy bin1.dat+c.ref cdate.dat')
    t0 = ent(b'T       TXT')
    o = sh.run('copy /b t.txt+,,')
    check('dates: a binary single copy keeps its source\'s; a concatenation the clock\'s', ent(b'BDATE   DAT') == src_d
          and ent(b'CDATE   DAT') != src_d, (src_d, ent(b'BDATE   DAT'), ent(b'CDATE   DAT')))
    check('COPY /B T.TXT+,, : T.TXT\'s date and time now (the clock\'s), what it holds the same',
          ent(b'T       TXT') != t0 and ent(b'T       TXT')[1] == ent(b'CDATE   DAT')[1] and fs().get('A:\\T.TXT') == b'touch'
          and 'onto itself' not in o, (o, t0, ent(b'T       TXT'), ent(b'CDATE   DAT')))
    o = sh.run('copy b.txt+a.txt a.txt')
    check('COPY B.TXT+A.TXT A.TXT: "Content of destination lost before copy" (as MS-DOS: A.TXT made from B.TXT first)',
          'Content of destination lost before copy' in o and fs().get('A:\\A.TXT') == b'bbbccc\x1a', (o, fs().get('A:\\A.TXT')))
    probs, _ = fatcheck.check(raw())
    check('... the disk consistent', not probs, probs)
    # the user's file safe when an append fails: a read error (Fail at INT 24h), the disk full
    def fail_ans(k, cmd):
        k.key('cls'); k.key(ktest.ENTER)
        n0 = len(k.pc.tty)
        k.key(cmd); k.key(ktest.ENTER)
        for i in range(6):
            if ''.join(k.pc.tty)[n0:].count('Fail?') > i: k.key('f')
            else: break
        return k.pc.text_screen()
    p = image('catbad.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'A.TXT=' + mkf('xa', b'original'),
              'U.TXT=' + mkf('xu', b'u\x1aTAIL'),
              'BAD.TXT=' + mkf('xb', bytes(range(32, 127)) * 20), 'N.TXT=' + mkf('xn', b'new'),
              'BAD.BAK=' + mkf('xbk', b'keep-bak'))
    k = ktest.KPC(p); k.start()
    sh = Shell(k)
    r = raw(); b = fatcheck.bpb(r)
    root = (b['res'] + b['nfat'] * b['spf']) * 512
    data = (b['res'] + b['nfat'] * b['spf'] + (b['nroot'] * 32 + 511) // 512)
    i = r.index(b'BAD     TXT', root)
    cl = struct.unpack_from('<H', r, i + 26)[0]
    k.pc.drives[0].bad = {data + (cl - 2) * b['spc'] + 1}
    o = fail_ans(k, 'copy a.txt+bad.txt')
    check('COPY A.TXT+BAD.TXT, BAD.TXT\'s second sector unreadable (Fail): A.TXT exactly as it was (no ^Z added), '
          '"0 File(s) copied"', fatcheck.read_files(raw()).get('A:\\A.TXT') == b'original'
          and '0 File(s) copied' in o, (o, fatcheck.read_files(raw()).get('A:\\A.TXT')))
    o = fail_ans(k, 'copy u.txt+bad.txt') + fail_ans(k, 'copy n.txt+u.txt+bad.txt')
    f = fatcheck.read_files(raw())
    check('... COPY U.TXT+BAD.TXT and N.TXT+U.TXT+BAD.TXT (U.TXT u^ZTAIL, N.TXT appended first): each exactly as it '
          'was, TAIL and all', f.get('A:\\U.TXT') == b'u\x1aTAIL' and f.get('A:\\N.TXT') == b'new', (o, f.get('A:\\U.TXT'), f.get('A:\\N.TXT')))
    o = fail_ans(k, 'copy n.txt+bad.txt nb.dat')
    f = fatcheck.read_files(raw())
    check('COPY N.TXT+BAD.TXT NB.DAT (made by this copy), a source not read: kept, what was read and its ^Z, '
          '"1 File(s) copied" (MS-DOS\'s ENDCOPY), the disk consistent', (f.get('A:\\NB.DAT') or b'').startswith(b'new')
          and f.get('A:\\NB.DAT', b'').endswith(b'\x1a') and '1 File(s) copied' in o and not fatcheck.check(raw())[0], (o, f.get('A:\\NB.DAT')))
    o = fail_ans(k, 'copy n.txt+bad.txt *.bak')
    f = fatcheck.read_files(raw())
    check('COPY N.TXT+BAD.TXT *.BAK failing so: N.BAK (the one destination) kept, BAD.BAK (there before; what the '
          'second source\'s name would map to) untouched', (f.get('A:\\N.BAK') or b'').startswith(b'new')
          and f.get('A:\\BAD.BAK') == b'keep-bak', (o, sorted(f)))
    k.pc.drives[0].bad = set()
    pf = image('catfull.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'A.TXT=' + mkf('fa', b'original'),
               'BIG.TXT=' + mkf('fb', b'B' * 30000))
    r = open(pf, 'rb').read(); b = fatcheck.bpb(r)
    data = b['res'] + b['nfat'] * b['spf'] + (b['nroot'] * 32 + 511) // 512
    fat = r[b['res'] * 512:(b['res'] + b['spf']) * 512]
    get = lambda n: (struct.unpack_from('<H', fat, n * 3 // 2)[0] >> 4) if n & 1 else (struct.unpack_from('<H', fat, n * 3 // 2)[0] & 0xFFF)
    free = sum(1 for n in range(2, (b['tot'] - data) // b['spc'] + 2) if get(n) == 0) * b['spc'] * 512
    subprocess.run(['mcopy', '-i', pf, mkf('ffill', b'F' * (free - 8192)), '::FILL.DAT'], check=True)
    k = ktest.KPC(pf); k.start()
    sh = Shell(k)
    o = sh.run('copy a.txt+big.txt')
    check('COPY A.TXT+BIG.TXT, the disk full on the way: A.TXT exactly as it was, "Insufficient disk '
          'space", "0 File(s) copied"', fatcheck.read_files(raw()).get('A:\\A.TXT') == b'original'
          and 'Insufficient disk space' in o and '0 File(s) copied' in o and not fatcheck.check(raw())[0],
          (o, fatcheck.read_files(raw()).get('A:\\A.TXT')))
    o = sh.run('copy a.txt+big.txt ab.dat')
    check('... COPY A.TXT+BIG.TXT AB.DAT (made by it): deleted, "0 File(s) copied", the disk consistent',
          'A:\\AB.DAT' not in fatcheck.read_files(raw()) and '0 File(s) copied' in o and not fatcheck.check(raw())[0], o)
    # the disk full for the last ^Z only, and over several sources (the earlier ones not left appended)
    def full(name, files, left):
        pf = image(name, os.path.join(GOS, 'src', 'LCMD.COM'), *files)
        r = open(pf, 'rb').read(); b = fatcheck.bpb(r)
        data = b['res'] + b['nfat'] * b['spf'] + (b['nroot'] * 32 + 511) // 512
        fat = r[b['res'] * 512:(b['res'] + b['spf']) * 512]
        get = lambda n: (struct.unpack_from('<H', fat, n * 3 // 2)[0] >> 4) if n & 1 else (struct.unpack_from('<H', fat, n * 3 // 2)[0] & 0xFFF)
        free = sum(1 for n in range(2, (b['tot'] - data) // b['spc'] + 2) if get(n) == 0) * b['spc'] * 512
        subprocess.run(['mcopy', '-i', pf, mkf('ffill2', b'F' * (free - left)), '::FILL.DAT'], check=True)
        k = ktest.KPC(pf); k.start()
        return k, Shell(k)
    x12 = ('X1.TXT=' + mkf('fx1', b'x' * 256), 'X2.TXT=' + mkf('fx2', b'y' * 256), 'K.TXT=' + mkf('fk', b'k' * 1024))
    k, sh = full('catz.img', x12, 512)
    o = sh.run('copy x1.txt+x2.txt out.dat')
    check('the disk full for the last ^Z only (COPY X1.TXT+X2.TXT OUT.DAT, 512 bytes free): OUT.DAT, made by it, '
          'deleted, "0 File(s) copied", the disk consistent', 'A:\\OUT.DAT' not in fatcheck.read_files(raw())
          and '0 File(s) copied' in o and not fatcheck.check(raw())[0], (o, sorted(fatcheck.read_files(raw()))))
    k, sh = full('catz2.img', x12, 512)
    o = sh.run('copy k.txt+x1.txt+x2.txt')
    check('... COPY K.TXT+X1.TXT+X2.TXT so (K.TXT the user\'s): K.TXT exactly as it was, X1 and X2 not left in it, '
          '"0 File(s) copied"', fatcheck.read_files(raw()).get('A:\\K.TXT') == b'k' * 1024 and '0 File(s) copied' in o
          and not fatcheck.check(raw())[0], (o, len(fatcheck.read_files(raw()).get('A:\\K.TXT') or b'')))
    k, sh = full('catm.img', ('X1.TXT=' + mkf('mx1', b'x' * 300), 'BIG.TXT=' + mkf('mbg', b'B' * 20000),
                              'K.TXT=' + mkf('mk', b'orig\x1a')), 4096)
    o = sh.run('copy k.txt+x1.txt+big.txt')
    check('the disk full in a third source (COPY K.TXT+X1.TXT+BIG.TXT): K.TXT exactly as it was (X1.TXT not left in it)',
          fatcheck.read_files(raw()).get('A:\\K.TXT') == b'orig\x1a' and '0 File(s) copied' in o, (o, fatcheck.read_files(raw()).get('A:\\K.TXT', b'')[:40]))
    sh.run('del fill.dat')
    o = sh.run('copy k.txt+x1.txt+big.txt')
    check('... room made, the same again: whole, X1.TXT in it once', fatcheck.read_files(raw()).get('A:\\K.TXT')
          == b'orig' + b'x' * 300 + b'B' * 20000 + b'\x1a' and '1 File(s) copied' in o, o)
    # a source found but not opened (another system's name, "A+B.TXT"): the destination closed, its handle with
    # it, 20 times over; the user's (more after its ^Z) exactly as it was; one made kept and counted (a source's error)
    big = b'keep-me\x1a' + b'T' * 5000
    p = image('catopen.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('ok', big), 'C.TXT=' + mkf('oc', b'c' * 1500),
              'AXB.TXT=' + mkf('ob', b'bbb'), 'N.TXT=' + mkf('on', b'nnn'))
    img = bytearray(open(p, 'rb').read()); i = img.find(b'AXB     TXT'); img[i:i + 11] = b'A+B     TXT'; open(p, 'wb').write(img)
    k = ktest.KPC(p); k.start()
    sh = Shell(k)
    o = ''
    for _ in range(20): o = sh.run('copy *.txt k.txt')
    o2 = sh.run('copy n.txt n2.txt')
    f = fatcheck.read_files(raw())
    check('a source found but not opened (A+B.TXT), COPY *.TXT K.TXT 20 times: K.TXT (more after its ^Z) exactly as '
          'it was each time, "0 File(s) copied"; then COPY N.TXT N2.TXT still copies (no handle left open)',
          f.get('A:\\K.TXT') == big and '0 File(s) copied' in o and '1 File(s) copied' in o2 and f.get('A:\\N2.TXT') == b'nnn'
          and not fatcheck.check(raw())[0], (o, o2, len(f.get('A:\\K.TXT') or b'')))
    o = sh.run('copy *.txt all.dat')
    f = fatcheck.read_files(raw())
    check('... COPY *.TXT ALL.DAT (made by it): K.TXT and C.TXT in it and its ^Z, then the one not opened: kept, '
          '"1 File(s) copied"', f.get('A:\\ALL.DAT') == b'keep-me' + b'c' * 1500 + b'\x1a' and '1 File(s) copied' in o
          and not fatcheck.check(raw())[0], (o, (f.get('A:\\ALL.DAT') or b'')[:20]))
    o = sh.run('copy k.txt+n.txt')
    check('the user\'s with more after its first ^Z, appended to: what came moved down over the ^Z, the rest gone '
          '(as MS-DOS)', fatcheck.read_files(raw()).get('A:\\K.TXT') == b'keep-menn' + b'n\x1a' and '1 File(s) copied' in o,
          (o, fatcheck.read_files(raw()).get('A:\\K.TXT', b'')[:30]))
    # pairs (MS-DOS's): a first source with wildcards and "+" to a wildcard name, here, a directory
    p = image('catpair.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'X1.TXT=' + mkf('px1', b'x1'), 'X1.REF=' + mkf('pr1', b'r1'),
              'X2.TXT=' + mkf('px2', b'x2\x1a'), 'X2.REF=' + mkf('pr2', b'r2'), 'X3.TXT=' + mkf('px3', b'x3'),
              'X2.LST=' + mkf('pl2', b'l2'), 'D2\\')
    k = ktest.KPC(p); k.start()
    sh = Shell(k)
    o = sh.run('copy *.txt+*.ref+*.lst *.dat')
    f = fatcheck.read_files(raw())
    check('COPY *.TXT+*.REF+*.LST *.DAT: each .TXT with its .REF and .LST (one not there passed over) into its .DAT, '
          '"3 File(s) copied"', f.get('A:\\X1.DAT') == b'x1r1\x1a' and f.get('A:\\X2.DAT') == b'x2r2l2\x1a'
          and f.get('A:\\X3.DAT') == b'x3\x1a' and '3 File(s) copied' in o, (o, {n: v for n, v in f.items() if n.endswith('.DAT')}))
    o = sh.run('copy *.txt+*.ref d2')
    f = fatcheck.read_files(raw())
    check('COPY *.TXT+*.REF D2: into the directory, of their names', f.get('A:\\D2\\X1.TXT') == b'x1r1\x1a'
          and f.get('A:\\D2\\X2.TXT') == b'x2r2\x1a' and f.get('A:\\D2\\X3.TXT') == b'x3\x1a' and '3 File(s) copied' in o,
          (o, sorted(f)))
    o = sh.run('copy *.txt+*.ref')
    f = fatcheck.read_files(raw())
    check('COPY *.TXT+*.REF (no destination): each .REF appended to its .TXT (over its ^Z); X3.TXT, no partner, as it '
          'was and not counted, nothing said; "2 File(s) copied"', f.get('A:\\X1.TXT') == b'x1r1\x1a'
          and f.get('A:\\X2.TXT') == b'x2r2\x1a' and f.get('A:\\X3.TXT') == b'x3' and '2 File(s) copied' in o
          and 'onto itself' not in o and not fatcheck.check(raw())[0], (o, f.get('A:\\X3.TXT')))
    # the review of 0444069's cases
    def lcmd21(k, fn):
        # fn(AH, pc) at each INT 21h LCMD makes (its segment: the kernel's current PSP, at the prompt)
        seg = k.u16('cur_psp')
        h = lambda pc: fn(pc.r('ax') >> 8, pc) if k.addr == k.i21 and pc.u16(pc.r('ss'), pc.r('sp') + 2) == seg else None
        k.hooks.append(h)
        return h
    def wp_at(k, cmd, nth, ah=0x40, cx0=False, off=True, cxv=None):
        # cmd, the disk write-protected at LCMD's nth call AH (CX = 0 ones only if cx0); F at each INT 24h
        # prompt (the tab off again first if off) -> the screen
        d = k.pc.drives[0]; st = {'n': 0}
        def on(a, pc):
            if a == ah and pc.r('bx') >= 5 and (not cx0 or pc.r('cx') == 0) and (cxv is None or pc.r('cx') == cxv):
                st['n'] += 1
                if st['n'] == nth: d.wp = True
        h = lcmd21(k, on)
        pc = k.pc; k.key('cls'); k.key(ktest.ENTER); n0 = len(pc.tty)
        k.key(cmd); k.key(ktest.ENTER, settle=False)
        for i in range(8):
            pc.run_until(lambda: ''.join(pc.tty)[n0:].count('Fail?') > i or 'copied' in ''.join(pc.tty)[n0:], 30)
            if ''.join(pc.tty)[n0:].count('Fail?') <= i: break
            if off: d.wp = False
            pc.keys.append(ord('f'))
        k.settle(); d.wp = False; k.hooks.remove(h)
        return pc.text_screen()
    def fresh(name, *files):
        k = ktest.KPC(image(name, os.path.join(GOS, 'src', 'LCMD.COM'), *files)); k.start()
        return k, Shell(k), lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
    k, sh, F = fresh('catr1.img', 'REPORT.TXT=' + mkf('rr', b'USER-REPORT'), 'ADD.TXT=' + mkf('ra', b'add'),
                     'MORE.TXT=' + mkf('rm', b'more'), 'SUB\\', 'SUB\\X=' + mkf('rx', b'x'))
    o = sh.run('copy sub\\report.txt+add.txt') + sh.run('copy nosuch\\report.txt+add.txt+more.txt')
    f = F()
    check('"+" to no destination, the first typed not there (SUB\\REPORT.TXT+ADD.TXT): named from the first found, '
          'ADD.TXT (kept, MORE.TXT appended), not REPORT.TXT, which is untouched (MS-DOS\'s SDIRBUF)',
          f.get('A:\\REPORT.TXT') == b'USER-REPORT' and f.get('A:\\ADD.TXT') == b'addmore\x1a'
          and 'A:\\SUB\\REPORT.TXT' not in f and 'onto itself' not in o, (o, f.get('A:\\REPORT.TXT'), f.get('A:\\ADD.TXT')))
    o = sh.run('copy report.txt+nosuch.txt')
    check('COPY REPORT.TXT+NOSUCH.TXT: "1 File(s) copied" (only a bare A+ is onto itself, MS-DOS\'s CHECKDONE), '
          'REPORT.TXT as it was', '1 File(s) copied' in o and 'onto itself' not in o and F().get('A:\\REPORT.TXT') == b'USER-REPORT', o)
    k, sh, F = fresh('catr2.img', 'LONGNAME.TXT=' + mkf('rl', b''), 'NAME.TXT=' + mkf('rn', b'USER-PRECIOUS'))
    o = sh.run('copy longn*.txt+' + '.\\' * 38 + '*.* *.cat')
    f = F()
    check('pairs, a partner\'s pattern of 79 characters that its name makes longer: passed over, the destination\'s '
          'name not written over (NAME.TXT, not named, untouched)', f.get('A:\\NAME.TXT') == b'USER-PRECIOUS'
          and not fatcheck.check(bytes(k.pc.drives[0].img))[0], (o, sorted(f)))
    k, sh, F = fresh('catr3.img', 'X1.TXT=' + mkf('rp1', b'x1'), 'X1.REF\\', 'LODESTON.TXT=' + mkf('rp2', b'lt'))
    o = sh.run('copy x*.txt+*.ref *.dat') + sh.run('copy lodes*.txt+*.e *.dat')
    f = F()
    check('pairs, a partner that is a directory (X1.REF) or the label (LODESTON.E, "LODESTONE"): passed over',
          f.get('A:\\X1.DAT') == b'x1\x1a' and f.get('A:\\LODESTON.DAT') == b'lt\x1a' and o.count('1 File(s) copied') == 2
          and 'not found' not in o, (o, {n: v for n, v in f.items() if n.endswith('.DAT')}))
    K0 = b'keep-me\r\n\x1a'
    k, sh, F = fresh('catr4.img', 'K.TXT=' + mkf('rk', K0), 'X1.TXT=' + mkf('rx1', b'x' * 3000),
                     'X2.TXT=' + mkf('rx2', b'y' * 3000), 'OUT.DAT=' + mkf('ro', b'OLD-OUT'))
    o = wp_at(k, 'copy k.txt+x1.txt', 1, cx0=True)
    check('the user\'s (its ^Z last) appended to, the last cut refused (Fail): K.TXT exactly as it was, "0 File(s) '
          'copied" (it was written over its ^Z in place, and said 1)', F().get('A:\\K.TXT') == K0 and '0 File(s) copied' in o, (o, F().get('A:\\K.TXT')))
    o = wp_at(k, 'copy k.txt+x1.txt+x2.txt', 3, ah=0x3E)
    check('... its close refused (LCMD\'s third close: X1.TXT, X2.TXT, then K.TXT): K.TXT exactly as it was, not counted',
          F().get('A:\\K.TXT') == K0 and '1 File(s) copied' not in o, (o, F().get('A:\\K.TXT')))
    o = wp_at(k, 'copy x1.txt+x2.txt out.dat', 1, cx0=True)
    check('a made one\'s last cut refused: not counted ("0 File(s) copied")', '0 File(s) copied' in o, (o, F().get('A:\\OUT.DAT', b'')[:10]))
    o = wp_at(k, 'copy x1.txt out2.dat', 1, ah=0x3E)
    check('a single copy\'s close refused: not counted, "Write error"', '0 File(s) copied' in o and 'Write error' in o, o)
    P = b'PRECIOUS-P\r\n'; Q = b'user-Q-after-the-Z' * 100
    k, sh, F = fresh('catr5.img', 'K.TXT=' + mkf('rk5', P + b'\x1a' + Q), 'BIG.TXT=' + mkf('rb5', b'B' * 100000))
    cxs = []                                            # (a dry run: LCMD's writes, their sizes)
    k0, _, _ = fresh('catr5d.img', 'K.TXT=' + mkf('rk5', P + b'\x1a' + Q), 'BIG.TXT=' + mkf('rb5', b'B' * 100000))
    h0 = lcmd21(k0, lambda a, pc: cxs.append(pc.r('cx')) if a == 0x40 and pc.r('bx') >= 5 else None)
    k0.key('copy k.txt+big.txt'); k0.key(ktest.ENTER); k0.settle(30)
    mv2 = cxs.index(1) + 3                              # (the ^Z's write, past the old end, then the move's: its second)
    o = wp_at(k, 'copy k.txt+big.txt', mv2)
    f = F()
    check('the user\'s (more after its ^Z), what came moved down, its second write refused: its text kept, its ^Z '
          'back, cut there (what was after the ^Z lost: the one exception), "0 File(s) copied"',
          f.get('A:\\K.TXT') == P + b'\x1a' and '0 File(s) copied' in o and not fatcheck.check(bytes(k.pc.drives[0].img))[0],
          (o, len(f.get('A:\\K.TXT', b'')), f.get('A:\\K.TXT', b'')[:30]))
    k, sh, F = fresh('catr6.img', 'K.TXT=' + mkf('rk6', P + b'\x1a' + Q), 'BIG.TXT=' + mkf('rb6', b'B' * 100000))
    o = wp_at(k, 'copy k.txt+big.txt', 2)
    check('... the disk refusing while it is appended (before any move): K.TXT exactly as it was, tail and all',
          F().get('A:\\K.TXT') == P + b'\x1a' + Q and '0 File(s) copied' in o, (o, len(F().get('A:\\K.TXT', b''))))
    o = wp_at(k, 'copy k.txt+big.txt', mv2, off=False)
    check('... refused and the tab left on (the put-back refused too): said, "Destination not put back as it was"',
          'Destination not put back as it was' in o, o)
    k, sh, F = fresh('catr7.img', 'K.TXT=' + mkf('rk7', K0), 'X.TXT=' + mkf('rx7', b'x' * 100), 'M.TXT=' + mkf('rm7', b'm'))
    for cmd in ('copy k.txt+x.txt+con', 'copy x.txt+con made.dat'):
        k.key('cls'); k.key(ktest.ENTER)
        k.key(cmd); k.key(ktest.ENTER)
        k.key('typed line'); k.key(ktest.ENTER)
        k.key('\x03'); k.key(ktest.ENTER)
    o = sh.run('copy m.txt m2.txt')
    f = F()
    check('Ctrl-C with CON in the list: the user\'s (K.TXT) exactly as it was; one to be made (MADE.DAT) not made; a '
          'copy still works after', f.get('A:\\K.TXT') == K0 and 'A:\\MADE.DAT' not in f and f.get('A:\\M2.TXT') == b'm'
          and not fatcheck.check(bytes(k.pc.drives[0].img))[0], (f.get('A:\\K.TXT'), sorted(f)))
    # the review of d6ef9cd's cases.  The destination made only when the first data go out (MS-DOS's): Ctrl-C
    # while CON is typed into leaves one there of that name as it was
    k, sh, F = fresh('catr8.img', 'NOTES.TXT=' + mkf('rn8', b'USER-NOTES'), 'OUT.DAT=' + mkf('ro8', b'USER-OUT'),
                     'A.TXT=' + mkf('ra8', b'aaa'), 'K.TXT=' + mkf('rk8', b'keep\x1a'))
    f0 = F()
    for cmd in ('copy con notes.txt', 'copy con+a.txt out.dat', 'copy a.txt+con out.dat', 'copy con+k.txt k.txt',
                'copy con new.dat'):
        k.key('cls'); k.key(ktest.ENTER)
        k.key(cmd); k.key(ktest.ENTER)
        k.key('typed line'); k.key(ktest.ENTER)
        k.key('\x03'); k.key(ktest.ENTER)
    f = F()
    check('Ctrl-C while CON is typed into (COPY CON NOTES.TXT, CON+A.TXT OUT.DAT, A.TXT+CON OUT.DAT, CON+K.TXT K.TXT, '
          'CON NEW.DAT): each destination there before as it was, none made (MS-DOS: made at the first flush)',
          all(f.get(n) == f0[n] for n in f0) and 'A:\\NEW.DAT' not in f and not fatcheck.check(bytes(k.pc.drives[0].img))[0],
          {n: v for n, v in f.items() if n != 'A:\\LCMD.COM' and n != 'A:\\LODE.SYS'})
    k.key('cls'); k.key(ktest.ENTER)
    k.key('copy con notes.txt'); k.key(ktest.ENTER); k.key('new text'); k.key(ktest.ENTER); k.key('\x1a'); k.key(ktest.ENTER)
    check('... and ended with ^Z: NOTES.TXT made from what was typed', F().get('A:\\NOTES.TXT') == b'new text\r\n',
          F().get('A:\\NOTES.TXT'))
    # the user's (more after its ^Z): what came, its ^Z with it, moved down; the last cut refused (the tab off before
    # F): its text kept, its ^Z back (what was after it lost: said), "Write error", 0
    P8 = b'PRECIOUS-P\r\n'; Q8 = b'user-Q-after-the-Z' * 40
    k, sh, F = fresh('catr9.img', 'K.TXT=' + mkf('rk9', P8 + b'\x1a' + Q8), 'X1.TXT=' + mkf('rx9', b'x' * 3000))
    o = wp_at(k, 'copy k.txt+x1.txt', 1, cx0=True)
    check('the user\'s with more after its ^Z, the last cut (it shrinks it) refused: its text kept, its ^Z back, the rest '
          'lost and said ("Destination put back without what followed its ^Z"), "Write error", "0 File(s) copied"',
          F().get('A:\\K.TXT') == P8 + b'\x1a' and 'Write error' in o and '0 File(s) copied' in o
          and 'Destination put back without what followed its ^Z' in o, (o, F().get('A:\\K.TXT', b'')[:40]))
    k, sh, F = fresh('catr9b.img', 'K.TXT=' + mkf('rk9b', P8 + b'\x1a' + Q8), 'X1.TXT=' + mkf('rx9b', b'x' * 3000))
    o = wp_at(k, 'copy k.txt+x1.txt', 1, cxv=1)
    check('... its ^Z (written past the old end, before the move) refused: K.TXT exactly as it was, tail and all',
          F().get('A:\\K.TXT') == P8 + b'\x1a' + Q8 and '0 File(s) copied' in o, (o, F().get('A:\\K.TXT', b'')[:40]))
    # a refused close: the put-back (or the delete) asks again at INT 24h; the tab off then, R: put back
    def wp2(k, cmd, nth, ah):
        # the disk write-protected at LCMD's nth call AH (a file's); F at the first prompt (the tab on), the tab off
        # and R at the next -> (the screen, how many asked)
        d = k.pc.drives[0]; st = {'n': 0}
        def on(a, pc):
            if a == ah and pc.r('bx') >= 5:
                st['n'] += 1
                if st['n'] == nth: d.wp = True
        h = lcmd21(k, on)
        pc = k.pc; k.key('cls'); k.key(ktest.ENTER); n0 = len(pc.tty)
        k.key(cmd); k.key(ktest.ENTER, settle=False)
        asked = 0
        for i in range(8):
            pc.run_until(lambda: ''.join(pc.tty)[n0:].count('Fail?') > i or 'copied' in ''.join(pc.tty)[n0:], 30)
            if ''.join(pc.tty)[n0:].count('Fail?') <= i: break
            if i: d.wp = False
            pc.keys.append(ord('f' if i == 0 else 'r')); asked += 1
        k.settle(); d.wp = False; k.hooks.remove(h)
        return pc.text_screen(), asked
    k, sh, F = fresh('catr10.img', 'K.TXT=' + mkf('rk10', K0), 'X1.TXT=' + mkf('rx10', b'x' * 3000),
                     'X2.TXT=' + mkf('rx10b', b'y' * 3000), 'OUT.DAT=' + mkf('ro10', b'OLD-OUT'))
    def dt(name):
        r = bytes(k.pc.drives[0].img); b = fatcheck.bpb(r)
        root = (b['res'] + b['nfat'] * b['spf']) * 512
        for i in range(root, root + b['nroot'] * 32, 32):
            if r[i:i + 11] == name: return r[i + 22:i + 26]
    t0 = dt(b'K       TXT')
    o, n = wp2(k, 'copy k.txt+x1.txt+x2.txt', 3, 0x3E)
    check('the user\'s close refused (F, the tab on): the put-back asks again; the tab off, R: K.TXT exactly as it was, '
          'its date and time too', n >= 2 and F().get('A:\\K.TXT') == K0 and dt(b'K       TXT') == t0
          and '1 File(s) copied' not in o, (o, n, F().get('A:\\K.TXT'), t0, dt(b'K       TXT')))
    o, n = wp2(k, 'copy k.txt+x1.txt+x2.txt', 2, 0x40)
    check('... its ^Z refused (F, the tab on: cat_fail\'s way): the put-back asks again; the tab off, R: K.TXT exactly as '
          'it was', n >= 2 and F().get('A:\\K.TXT') == K0, (o, n, F().get('A:\\K.TXT')))
    o, n = wp2(k, 'copy x1.txt out.dat', 2, 0x3E)            # (OUT.DAT there: the first, the look at what it is)
    check('a single copy\'s close refused (F): its delete asks again; the tab off, R: OUT.DAT gone, "Write error"',
          n >= 2 and 'A:\\OUT.DAT' not in F() and 'Write error' in o, (o, n, sorted(F())))
    # the user's date and time as they were after a failed concatenation (a read error: X1.TXT, more than the
    # buffer holds, already out in it), and after Ctrl-C
    k, sh, F = fresh('catr11.img', 'K.TXT=' + mkf('rk11', K0), 'X1.TXT=' + mkf('rx11', b'x' * 70000),
                     'BAD.TXT=' + mkf('rb11', b'b' * 3000), 'J.TXT=' + mkf('rj11', b'jj\x1a'))
    r = bytes(k.pc.drives[0].img); b = fatcheck.bpb(r)
    root = (b['res'] + b['nfat'] * b['spf']) * 512
    data = b['res'] + b['nfat'] * b['spf'] + (b['nroot'] * 32 + 511) // 512
    cl = struct.unpack_from('<H', r, r.index(b'BAD     TXT', root) + 26)[0]
    k.pc.drives[0].bad = {data + (cl - 2) * b['spc'] + 2}
    t0, j0 = dt(b'K       TXT'), dt(b'J       TXT')
    o = fail_ans(k, 'copy k.txt+x1.txt+bad.txt')
    k.pc.drives[0].bad = set()
    k.key('cls'); k.key(ktest.ENTER)
    k.key('copy j.txt+con'); k.key(ktest.ENTER); k.key('typed'); k.key(ktest.ENTER); k.key('\x03'); k.key(ktest.ENTER)
    check('the user\'s after a failed concatenation (a read error: K.TXT), and after Ctrl-C (J.TXT+CON): each exactly as '
          'it was, its date and time too', F().get('A:\\K.TXT') == K0 and dt(b'K       TXT') == t0
          and F().get('A:\\J.TXT') == b'jj\x1a' and dt(b'J       TXT') == j0, (o, t0, dt(b'K       TXT'), j0, dt(b'J       TXT')))
    # MS-DOS's delimiters (";", "="), "A+ +", "A+/B"; pairs: a partner the destination this copy is to make is no
    # "lost" one
    k, sh, F = fresh('catr12.img', 'A.TXT=' + mkf('ra12', b'aaa'), 'C.REF=' + mkf('rc12', b'ccc'),
                     'X1.TXT=' + mkf('rx12', b'x1'), 'X1.REF=' + mkf('rr12', b'r1'), 'X2.TXT=' + mkf('rx12b', b'x2'))
    o = sh.run('copy a.txt+;c.ref sem.dat') + sh.run('copy c.ref=eq.dat')
    f = F()
    check('";" and "=" are delimiters, as MS-DOS\'s (COPY A.TXT+;C.REF SEM.DAT: the two; COPY C.REF=EQ.DAT)',
          f.get('A:\\SEM.DAT') == b'aaaccc\x1a' and f.get('A:\\EQ.DAT') == b'ccc', (o, f.get('A:\\SEM.DAT'), f.get('A:\\EQ.DAT')))
    o = sh.run('copy a.txt+ +') + sh.run('copy a.txt+/b')
    check('COPY A.TXT+ + and COPY A.TXT+/B: no further source, "onto itself" each, A.TXT as it was',
          o.count('cannot be copied onto itself') == 2 and F().get('A:\\A.TXT') == b'aaa', o)
    o = sh.run('copy *.txt+*.ref *.ref')
    f = F()
    check('pairs into *.REF: X2.REF (none before, the one this copy makes) no "lost" partner; X1.REF (there before) '
          'is ("Content of destination lost before copy", once)', f.get('A:\\X2.REF') == b'x2\x1a'
          and o.count('Content of destination lost before copy') == 1, (o, f.get('A:\\X1.REF'), f.get('A:\\X2.REF')))
    # pairs: a partner's name of 79 characters taken, of 80 passed over
    k, sh, F = fresh('catr13.img', 'X1.TXT=' + mkf('rx13', b'x1'), 'X1.REF=' + mkf('rr13', b'r1'),
                     'X12.TXT=' + mkf('rx13b', b'x12'), 'X12.REF=' + mkf('rr13b', b'r12'))
    o = sh.run('copy x12*.txt+' + '.\\' * 36 + '*.ref *.dat') + sh.run('copy x1.t*+' + '.\\' * 37 + '*.ref *.dat')
    f = F()
    check('pairs, a partner\'s name of 79 characters (.\\ 36 times, X12.REF): in; of 80 (.\\ 37 times, X1.REF): passed over',
          f.get('A:\\X12.DAT') == b'x12r12\x1a' and f.get('A:\\X1.DAT') == b'x1\x1a', (o, f.get('A:\\X12.DAT'), f.get('A:\\X1.DAT')))
    # pairs: one pair's destination not made (A.CAT read-only): the pairs stop there (MS-DOS's COPERR), and no
    # pair's data reach another's destination (B.CAT got A's)
    pimg = image('catr14.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'A.TXT=' + mkf('rp14a', b'aaa'), 'A.REF=' + mkf('rp14b', b'AAA'),
                 'B.TXT=' + mkf('rp14c', b'bbb'), 'B.REF=' + mkf('rp14d', b'BBB'), 'A.CAT=' + mkf('rp14e', b'RO-A-CAT'))
    praw = bytearray(open(pimg, 'rb').read()); i = praw.find(b'A       CAT', 19 * 512); praw[i + 11] |= 1; open(pimg, 'wb').write(praw)
    k = ktest.KPC(pimg); k.start(); sh = Shell(k); F = lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
    o = sh.run('copy *.txt+*.ref *.cat') + sh.run('copy /b *.txt+*.ref *.cat')
    f = F()
    check('pairs, a destination not made (A.CAT read-only): "File creation error", the pairs stopped, 0 counted; B.CAT '
          'not made with A\'s data', o.count('File creation error') == 2 and o.count('0 File(s) copied') == 2
          and 'A:\\B.CAT' not in f and f.get('A:\\A.CAT') == b'RO-A-CAT', (o, sorted(f)))
    # pairs onto the user's own files: pair 1's write refused (F, the tab off after): B.TXT, pair 2's kept file, as it was
    k, sh, F = fresh('catr15.img', 'A.TXT=' + mkf('rp15a', b'aaa\x1a'), 'A.REF=' + mkf('rp15b', b'A' * 700),
                     'B.TXT=' + mkf('rp15c', b'bbb-user\x1a'), 'B.REF=' + mkf('rp15d', b'BBB'))
    e0 = {n: ent(n) for n in (b'A       TXT', b'B       TXT')}
    o = wp_at(k, 'copy *.txt+*.ref', 1)
    f = F(); img = bytes(k.pc.drives[0].img)
    check('pairs onto the user\'s files, pair 1\'s write refused: the pairs stop; A.TXT and B.TXT as they were (bytes, '
          'date and time), 0 counted', f.get('A:\\A.TXT') == b'aaa\x1a' and f.get('A:\\B.TXT') == b'bbb-user\x1a'
          and all(ent(n) == e0[n] for n in e0) and '0 File(s) copied' in o
          and not fatcheck.check(img)[0], (o, f.get('A:\\A.TXT'), f.get('A:\\B.TXT')))
    # put back after its close was refused, nothing after its ^Z: no "without what followed its ^Z"
    k, sh, F = fresh('catr16.img', 'K.TXT=' + mkf('rp16k', b'keep-me\r\n\x1a'), 'X1.TXT=' + mkf('rp16x', b'x' * 3000),
                     'X2.TXT=' + mkf('rp16y', b'y' * 3000))
    o = wp_at(k, 'copy k.txt+x1.txt+x2.txt', 3, ah=0x3E)
    f = F()
    check('the user\'s close refused (the tab off before F): put back exactly; nothing followed its ^Z, so no "without '
          'what followed its ^Z"', f.get('A:\\K.TXT') == b'keep-me\r\n\x1a' and 'what followed' not in o
          and '0 File(s) copied' in o, (o, f.get('A:\\K.TXT')))
    # Ctrl-C before anything went out, the disk write-protected: nothing asked of it (no cut, no date), all as it was
    k, sh, F = fresh('catr17.img', 'K.TXT=' + mkf('rp17k', b'keep-me\r\n\x1a'), 'OUT.DAT=' + mkf('rp17o', b'USER-OUT'),
                     'X.TXT=' + mkf('rp17x', b'xx'))
    d = k.pc.drives[0]; img0 = bytes(d.img)
    outs = []
    for cmd in ('copy k.txt+con', 'copy x.txt+con out.dat'):
        k.key('cls'); k.key(ktest.ENTER); d.wp = True
        k.key(cmd); k.key(ktest.ENTER); k.key('typed line'); k.key(ktest.ENTER); k.key('\x03', settle=False)
        k.pc.run_until(lambda: 'Fail?' in k.pc.text_screen(), 5)
        if 'Fail?' in k.pc.text_screen(): k.pc.keys.append(ord('f'))
        k.settle(); d.wp = False
        outs.append(k.pc.text_screen())
    check('Ctrl-C into CON before anything went out, the disk write-protected: no "Write protect" asked; K.TXT and '
          'OUT.DAT as they were', not any('Write protect' in o for o in outs) and bytes(d.img) == img0, outs)
    # delimiters before a "+" (MS-DOS's skips them)
    k, sh, F = fresh('catr18.img', 'A.TXT=' + mkf('rp18a', b'aaa'), 'B.TXT=' + mkf('rp18b', b'bbb'), 'OUT.DAT=' + mkf('rp18o', b'OLD'))
    o = sh.run('copy a.txt ;+b.txt out.dat')
    o2 = sh.run('copy a.txt, +b.txt out2.dat')
    f = F()
    check('COPY A.TXT ;+B.TXT OUT.DAT and A.TXT, +B.TXT: the delimiters before the "+" skipped, A and B in one',
          f.get('A:\\OUT.DAT') == b'aaabbb\x1a' and f.get('A:\\OUT2.DAT') == b'aaabbb\x1a', (o, o2))
    # the disk changed mid-COPY (B: another disk at X2's open), the user's K.TXT on B: written to (past 64 KB):
    # the kernel's "Invalid disk change", F: nothing done by name on the disk now in (its own K.TXT untouched)
    b1 = mkimg.build(os.path.join(OUT, 'catdc1.img'), ['BIG.TXT=' + mkf('rpdcb', b'B' * 70000),
                     'K.TXT=' + mkf('rpdck', b'keep-me\r\n\x1a'), 'X2.TXT=' + mkf('rpdcx', b'y' * 3000)])
    b2 = mkimg.build(os.path.join(OUT, 'catdc2.img'), ['K.TXT=' + mkf('rpdck2', b'OTHER-DISK-K' * 300),
                     'P1.TXT=' + mkf('rpdcp', b'P1' * 3000), 'X2.TXT=' + mkf('rpdcz', b'z' * 3000)])
    raw2 = bytearray(open(b2, 'rb').read())
    for at in (raw2.find(b'LODESTONE  ', 19 * 512), raw2.find(b'LODESTONE  ', 0, 512)):
        if at > 0: raw2[at:at + 11] = b'OTHERDISK  '
    raw2[0x27:0x2B] = b'\x12\x34\x56\x78'
    two0 = bytes(raw2)
    k = ktest.KPC(image('catdca.img', os.path.join(GOS, 'src', 'LCMD.COM')), b=b1); k.start(); Shell(k)
    other = pcemu.Floppy(bytearray(raw2)); st = {'n': 0}
    def swap(a, pc):
        if a == 0x3D and pc.r('bx') != 1:
            st['n'] += 1
            if st['n'] == 3: other.changed = True; k.pc.drives[1] = other
    h = lcmd21(k, swap)
    pc = k.pc; k.key('cls'); k.key(ktest.ENTER); n0 = len(pc.tty)
    k.key('copy b:k.txt+b:big.txt+b:x2.txt b:k.txt'); k.key(ktest.ENTER, settle=False)
    for i in range(6):
        pc.run_until(lambda: ''.join(pc.tty)[n0:].count('Fail?') > i or 'copied' in ''.join(pc.tty)[n0:], 30)
        if ''.join(pc.tty)[n0:].count('Fail?') <= i: break
        pc.keys.append(ord('f'))
    k.settle(); k.hooks.remove(h)
    o = pc.text_screen()
    check('the disk changed mid-COPY ("Invalid disk change", F): the disk in now untouched (its own K.TXT, P1.TXT), '
          '"Disk changed: the destination not touched", 0 counted', bytes(other.img) == two0
          and 'Disk changed: the destination not touched' in o and '0 File(s) copied' in o, o)
    # ... at the first source's second read, the destination still to be made (dstate 4, its data in the
    # buffer): F or A, then "Read error": not made by name on the disk in now (its own OUT.DAT as it was), 0
    # counted; R with the first disk back: the copy whole; the destination on A: (the change on B:): made as
    # after any source's error (what came, counted).  Past 64 KB (the destination open), at the second source's
    # search, F: the list passes it over, so the third is found by name on the disk in now: neither opened nor
    # read, one "Disk changed" said
    c1 = mkimg.build(os.path.join(OUT, 'catdd1.img'), ['BIG.TXT=' + mkf('rpddb', b'B' * 70000), 'K.TXT=' + mkf('rpddk', b'keep-me\r\n\x1a'),
                     'X1.TXT=' + mkf('rpddx', b'x' * 3000), 'X2.TXT=' + mkf('rpddy', b'y' * 3000),
                     'OUT.DAT=' + mkf('rpddo', b'OLD')])
    c2 = bytearray(open(mkimg.build(os.path.join(OUT, 'catdd2.img'), ['OUT.DAT=' + mkf('rpddo2', b'OTHER-DISK-OUT' * 100),
                   'X2.TXT=' + mkf('rpddz', b'z' * 3000)]), 'rb').read())
    for at in (c2.find(b'LODESTONE  ', 19 * 512), c2.find(b'LODESTONE  ', 0, 512)):
        if at > 0: c2[at:at + 11] = b'OTHERDISK  '
    c2[0x27:0x2B] = b'\x12\x34\x56\x78'
    one0 = open(c1, 'rb').read(); c2 = bytes(c2)
    for cmd, fn, keys, back, dest in (('copy b:x1.txt+b:x2.txt b:out.dat', 0x3F, 'f', False, 'none'),
                                      ('copy b:x1.txt+b:x2.txt b:out.dat', 0x3F, 'a', False, 'none'),
                                      ('copy b:x1.txt+b:x2.txt b:out.dat', 0x3F, 'r', True, 'whole'),
                                      ('copy b:k.txt+b:x1.txt', 0x3F, 'f', False, 'a'),
                                      ('copy b:big.txt+b:x1.txt+b:x2.txt b:out.dat', 0x4E, 'f', False, 'open')):
        k = ktest.KPC(image('catdda.img', os.path.join(GOS, 'src', 'LCMD.COM')), b=c1); k.start(); Shell(k)
        first = k.pc.drives[1]; other = pcemu.Floppy(bytearray(c2)); st = {'n': 0}
        def swap(a, pc):
            if a == fn and pc.r('bx') != 1:
                st['n'] += 1
                if st['n'] == 2: other.changed = True; k.pc.drives[1] = other
        h = lcmd21(k, swap)
        pc = k.pc; k.key('cls'); k.key(ktest.ENTER); n0 = len(pc.tty)
        k.key(cmd); k.key(ktest.ENTER, settle=False)
        for i in range(6):
            pc.run_until(lambda: ''.join(pc.tty)[n0:].count('Fail?') > i or 'copied' in ''.join(pc.tty)[n0:], 30)
            if ''.join(pc.tty)[n0:].count('Fail?') <= i: break
            if back: first.changed = True; k.pc.drives[1] = first
            pc.keys.append(ord(keys))
        k.settle(); k.hooks.remove(h)
        o = pc.text_screen(); f1 = fatcheck.read_files(bytes(first.img)); fa = fatcheck.read_files(bytes(k.pc.drives[0].img))
        ok = bytes(other.img) == c2 and not fatcheck.check(bytes(first.img))[0]
        if dest == 'none':
            ok = ok and bytes(first.img) == one0 and 'Read error' in o and 'Disk changed: the destination not touched' in o \
                 and '0 File(s) copied' in o
            what = 'nothing made on either disk ("Read error", "Disk changed: the destination not touched", 0 counted)'
        elif dest == 'whole':
            ok = ok and f1.get('A:\\OUT.DAT') == b'x' * 3000 + b'y' * 3000 + b'\x1a' and 'Disk changed' not in o \
                 and '1 File(s) copied' in o
            what = 'OUT.DAT on the first disk, X1 and X2 whole, 1 counted'
        elif dest == 'open':
            ok = ok and 'X2.TXT' not in o and o.count('Disk changed: the destination not touched') == 1 \
                 and 'Insufficient' not in o and '0 File(s) copied' in o
            what = 'X2.TXT on it not opened, one "Disk changed: the destination not touched", 0 counted'
        else:
            ok = ok and bytes(first.img) == one0 and fa.get('A:\\K.TXT') == b'keep-me\r\n\x1a' and 'Disk changed' not in o \
                 and '1 File(s) copied' in o
            what = 'A:\\K.TXT made from what came, 1 counted, B: as it was'
        check('... %s, another disk at the second %s, %s%s: %s; the other disk untouched'
              % (cmd.upper(), 'search' if fn == 0x4E else 'read', keys.upper(), ' (the first disk back)' if back else '', what), ok, o)

def t_spacenames():
    """Names with a space inside (another system's, or a program's: MS-DOS takes them) through LCMD's COPY
    and REN with wildcards, XCOPY's and CHKDSK's names: each the whole name, never cut at its space (COPY
    *.TXT *.BAK wrote AB CD.TXT and AB EF.TXT both into AB.BAK, over what was there).  The names are mapped
    as the kernel packs them (MS-DOS's PackName) and as MS-DOS's REN (FCB rename) maps them; MS-DOS's own
    COPY drops the spaces, which can name another file.  Also COPY to a wildcard name replaces each file
    there (it appended), its "onto itself" as the kernel reads names, Tab, CD @:."""
    def mkf(n, b):
        t = os.path.join(OUT, n); open(t, 'wb').write(b); return t
    p = image('spn.img', os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(GOS, 'src', 'XCOPY.COM'),
              os.path.join(GOS, 'src', 'CHKDSK.COM'), 'ABXCD.TXT=' + mkf('sn1', b'one'), 'ABXEF.TXT=' + mkf('sn2', b'two'),
              'AB.BAK=' + mkf('sn3', b'precious'), 'AB.TXT=' + mkf('sn4', b'mine'), 'P1.TXT=' + mkf('sn5', b'p1new'),
              'P2.TXT=' + mkf('sn6', b'p2new'), 'P1.OLD=' + mkf('sn7', b'p1old'), 'P2.OLD=' + mkf('sn8', b'p2old'),
              'LONGFILE.TXT=' + mkf('sn9', b'long'), 'NOEXT=' + mkf('sn10', b'noext'))
    img = bytearray(open(p, 'rb').read())
    for n in (b'ABXCD   TXT', b'ABXEF   TXT'):
        i = img.find(n); img[i + 2] = 0x20
    open(p, 'wb').write(img)
    k = ktest.KPC(p); k.start()
    sh = Shell(k)
    fs = lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
    o = sh.run('copy ab?cd.txt *.bak') + sh.run('copy ab?ef.txt *.bak')
    f = fs()
    check('COPY AB?CD.TXT *.BAK, AB?EF.TXT *.BAK: AB CD.BAK and AB EF.BAK, each its own; AB.BAK as it was',
          f.get('A:\\AB CD.BAK') == b'one' and f.get('A:\\AB EF.BAK') == b'two' and f.get('A:\\AB.BAK') == b'precious', (o, sorted(f)))
    o = sh.run('ren ab?cd.bak *.old')
    f = fs()
    check('REN AB?CD.BAK *.OLD: AB CD.OLD', f.get('A:\\AB CD.OLD') == b'one' and 'A:\\AB CD.BAK' not in f
          and f.get('A:\\AB.BAK') == b'precious', (o, sorted(f)))
    o = sh.run('xcopy ab?ef.txt *.new')
    f = fs()
    check('XCOPY AB?EF.TXT *.NEW: AB EF.NEW (not ABEF.NEW)', f.get('A:\\AB EF.NEW') == b'two' and 'A:\\ABEF.NEW' not in f, (o, sorted(f)))
    o = sh.run('chkdsk /v')
    check('CHKDSK /V names them whole ("A:\\AB CD.TXT", not "A:\\AB.TXT" twice)', 'A:\\AB CD.TXT' in o and 'A:\\AB EF.TXT' in o, o)
    f = fs()
    check('... and AB.TXT, the file a cut name would have hit, untouched throughout', f.get('A:\\AB.TXT') == b'mine', sorted(f))
    o = sh.run('copy p?.txt *.old') + sh.run('copy p?.txt all.dat')
    f = fs()
    check('COPY P?.TXT *.OLD onto two that are there: each replaced (the second was appended to), as MS-DOS; '
          'COPY P?.TXT ALL.DAT: the two in one', f.get('A:\\P1.OLD') == b'p1new' and f.get('A:\\P2.OLD') == b'p2new'
          and f.get('A:\\ALL.DAT', b'').startswith(b'p1newp2new'), (o, f.get('A:\\P2.OLD'), f.get('A:\\ALL.DAT')))
    o = sh.run('copy longfile.txt longfilename.txt') + sh.run('copy noext noext.')
    check('COPY LONGFILE.TXT LONGFILENAME.TXT, and NOEXT NOEXT.: "File cannot be copied onto itself" (the same '
          'file, as the kernel reads the name: cut to 8.3, a dot last dropped)', o.count('cannot be copied onto itself') == 2
          and fs().get('A:\\LONGFILE.TXT') == b'long', o)
    k.key('cls'); k.key(ktest.ENTER)
    k.key('type ab'); k.key(ktest.TAB); k.key(ktest.ENTER)
    o = k.pc.text_screen()
    check('Tab after "type ab" passes over the names with a space inside (the line would take "AB CD.TXT" for '
          '"AB" and "CD.TXT"): AB.BAK, the first without', 'TYPE AB.BAK' in o.upper() and 'precious' in o, o)
    k.key('cls'); k.key(ktest.ENTER)
    k.key('type ab'); k.key(ktest.TAB); k.key(ktest.TAB); k.key(ktest.TAB); k.key(ktest.ENTER)
    o = k.pc.text_screen()
    check('... Tab, Tab, Tab: AB.BAK, AB.TXT, then (every name after them with a space) round to AB.BAK again',
          'TYPE AB.BAK' in o.upper() and 'precious' in o, o)
    o = sh.run('cd @:') + sh.run('cd [:') + sh.run('cd')
    check('CD @: and CD [: (no drives: "@" was taken as the current one): "Invalid drive specification" each '
          '("@:" alone is "@" and a label, as COMMAND\'s: nothing)', o.count('Invalid drive specification') == 2, o)

def t_wpfail():
    """A write-protected floppy, each kind of call that changes the FAT or a directory refused, F at INT 24h
    (Fail): nothing of it reaches the disk once the tab is off.  The cached FAT's changes went out with the
    next write: COPY N.TXT K.TXT (a create over K: its chain freed before its entry, which the disk refused)
    left K with 1 cluster of its 10 and Z.TXT, written next, cross-linked with it.  Now the kernel writes a
    chain before the entry that names it and an entry before the frees it lets go of, so a cached change is
    always right to write later; a buffer whose write failed (Fail or Abort) is read again.  Also: a FAT
    flush failing on its second run, Abort at a create over K (with the program's own INT 24h, and at the
    shell's prompt: one prompt, then terminate's closes Fail), another open file's writes kept across a
    failed one.  Retry, with the tab off by then, still works.  KDISK.INC's rules each: another disk with the
    same boot sector put in under a changed cache; INT 21h 0Dh when the FAT can't be written; a refused append
    giving back its clusters; a growing directory's cluster zeroed before it is linked (Abort); a flush failing
    half-way, then a restart or a reset; a RENAME whose old entry can't be written."""
    com = os.path.join(OUT, 'WPFAIL.COM')
    subprocess.run(['nasm', '-f', 'bin', '-o', com, os.path.join(HERE, 'WPFAIL.ASM')], check=True)
    big = b'keep-me\x1a' + b'T' * 5000
    def mkf(n, b):
        t = os.path.join(OUT, n); open(t, 'wb').write(b); return t
    files = ('K.TXT=' + mkf('wpk', big), 'C.TXT=' + mkf('wpc', b'c' * 1500), 'N.TXT=' + mkf('wpn', b'nnn'),
             'D\\', 'WPFAIL.COM=' + com)
    def answer(k, cmd, key):
        pc = k.pc
        k.key('cls'); k.key(ktest.ENTER)
        n0 = len(pc.tty)
        k.key(cmd); k.key(ktest.ENTER, settle=False)
        for i in range(8):
            pc.run_until(lambda: ''.join(pc.tty)[n0:].count('Fail?') > i or pc.crash, 15)
            if ''.join(pc.tty)[n0:].count('Fail?') <= i: break
            if key == 'r': pc.drives[0].wp = False      # (the tab off, then Retry)
            pc.keys.append(ord(key))
        k.settle()
        return ''.join(pc.tty)[n0:]
    fs = lambda k: fatcheck.read_files(bytes(k.pc.drives[0].img))
    for cmd in ('copy n.txt k.txt', 'copy k.txt+c.txt', 'echo more>> k.txt', 'ren k.txt q.txt', 'del k.txt',
                'md newdir', 'copy c.txt d\\c2.txt'):
        k = ktest.KPC(image('wpf.img', os.path.join(GOS, 'src', 'LCMD.COM'), *files)); k.start()
        sh = Shell(k)
        k.pc.drives[0].wp = True
        o = answer(k, cmd, 'f')
        k.pc.drives[0].wp = False
        sh.run('echo hello> z.txt'); sh.run('copy c.txt c3.txt')
        f = fs(k); probs = fatcheck.check(bytes(k.pc.drives[0].img))[0]
        check('%s on a write-protected A:, Fail: refused; the tab off, two files written: K.TXT as it was, the disk '
              'consistent' % cmd.upper(), 'Fail?' in o and f.get('A:\\K.TXT') == big and not probs
              and f.get('A:\\Z.TXT') == b'hello\r\n' and f.get('A:\\C3.TXT') == b'c' * 1500, (o, probs, len(f.get('A:\\K.TXT') or b'')))
    # a file held open across the failed write (100 bytes: through a sector buffer): written again after the tab
    # is off, then closed: the second write whole, the cluster the first took in the cached FAT written with it
    for kdata in (big, b''):
        k = ktest.KPC(image('wpf.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wpk2', kdata),
                            'WPFAIL.COM=' + com)); k.start()
        sh = Shell(k)
        k.pc.drives[0].wp = True
        k.key('cls'); k.key(ktest.ENTER)
        n0 = len(k.pc.tty)
        k.key('wpfail'); k.key(ktest.ENTER, settle=False)
        k.pc.run_until(lambda: 'W1' in ''.join(k.pc.tty)[n0:] or k.pc.crash, 15); k.settle()
        k.pc.drives[0].wp = False
        k.key(ktest.ENTER, settle=False)
        k.pc.run_until(lambda: 'C ' in ''.join(k.pc.tty)[n0:] or k.pc.crash, 15); k.settle()
        o = ''.join(k.pc.tty)[n0:].replace('\r', '')
        sh.run('echo hello> z.txt'); sh.run('echo hello2> z2.txt')
        f = fs(k); probs = fatcheck.check(bytes(k.pc.drives[0].img))[0]
        kk = f.get('A:\\K.TXT')
        check('a file held open (%d bytes): its write refused (Fail), the tab off, written again and closed: the '
              'disk consistent, K.TXT with the second write whole' % len(kdata),
              'W1 err' in o and 'W2 ok' in o and 'C ok' in o and not probs and kk == kdata + b'w' * 100
              and f.get('A:\\Z.TXT') == b'hello\r\n', (o, probs, len(kk or b'')))
    def probe(name):
        c = os.path.join(OUT, name + '.COM')
        subprocess.run(['nasm', '-f', 'bin', '-o', c, os.path.join(HERE, name + '.ASM')], check=True)
        return name + '.COM=' + c
    # a FAT flush failing on its second run (FAT sector 3 refuses, the first run gone out): the cache kept
    # changed, so the next flush (terminate's, R at the shell's prompt) writes it whole.  K's entry, refused at
    # its close, still says 1000 bytes: its chain the longer, nothing cross-linked
    k = ktest.KPC(image('wpp.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wpk3', b'k' * 1000),
                        'FILLER.BIN=' + mkf('wpfill', b'f' * 420000), probe('WPAPPK'))); k.start()
    sh = Shell(k); pc = k.pc; d = pc.drives[0]
    class Bad:                                          # (writes to LBA 3 refused while on)
        on = False
        def __bool__(s):
            if not s.on: return False
            cx, dx, al = pc.r('cx'), pc.r('dx'), pc.r('ax') & 0xFF
            lba = (((cx >> 8) | ((cx & 0xC0) << 2)) * d.heads + (dx >> 8)) * d.spt + (cx & 63) - 1
            return lba <= 3 < lba + al
    bad = Bad(); d.wp = bad; bad.on = True
    o = answer(k, 'wpappk', 'r')
    bad.on = False
    sh.run('echo hello> z.txt'); sh.run('copy k.txt k2.txt')
    f = fs(k); probs = fatcheck.check(bytes(d.img))[0]
    check('a FAT flush failing on its second run (WPAPPK, Fail), then R at terminate\'s flush: no cluster free in a '
          'chain, none cross-linked (K.TXT\'s refused entry: its chain the longer, at worst), K.TXT\'s 1000 bytes kept',
          'Fail?' in o and all('K.TXT' in p and 'chain has' in p for p in probs) and f.get('A:\\K.TXT') == b'k' * 1000
          and f.get('A:\\Z.TXT') == b'hello\r\n' and f.get('A:\\K2.TXT') == b'k' * 1000, (o, probs))
    # Abort at a create over K: the directory buffer it wrote read again (it was left as written, and the next
    # write to that sector took K's new entry, size 0, out: K emptied, its chain lost); terminate's closes
    # and flush Fail an Abort (each one terminated again, the prompt back)
    for name, keys, what in (('WPCROVA', '', 'its own INT 24h'), ('WPCROV', 'a', 'A at the shell\'s prompt')):
        k = ktest.KPC(image('wpa.img', os.path.join(GOS, 'src', 'LCMD.COM'), *files, probe(name))); k.start()
        sh = Shell(k)
        k.pc.drives[0].wp = True
        o = answer(k, name.lower(), keys or 'f')
        k.pc.drives[0].wp = False
        sh.run('echo hello> z.txt'); sh.run('copy c.txt c3.txt')
        f = fs(k); probs = fatcheck.check(bytes(k.pc.drives[0].img))[0]
        check('a create over K.TXT on a write-protected A:, Abort (%s): one prompt at most; the tab off, two files '
              'written: K.TXT as it was, the disk consistent' % what, o.count('Fail?') == (1 if keys else 0)
              and f.get('A:\\K.TXT') == big and not probs and f.get('A:\\Z.TXT') == b'hello\r\n', (o, probs))
    # a cut (a write of 0 bytes at 100) on the write-protected disk, Fail: its entry, the new size, goes first,
    # and only then the clusters past it are freed; refused, nothing is freed (they went out later while K's
    # entry, refused too, still named them: cross-linked with the next file written)
    k = ktest.KPC(image('wpt.img', os.path.join(GOS, 'src', 'LCMD.COM'), *files, probe('WPTRUNC'))); k.start()
    sh = Shell(k)
    k.pc.drives[0].wp = True
    o = answer(k, 'wptrunc', 'f')
    k.pc.drives[0].wp = False
    sh.run('echo hello> z.txt'); sh.run('copy c.txt c3.txt')
    f = fs(k); probs = fatcheck.check(bytes(k.pc.drives[0].img))[0]
    check('K.TXT cut at 100 bytes on a write-protected A: (a write of 0 bytes), Fail: refused ("T-"); the tab off, '
          'two files written: K.TXT as it was, the disk consistent', 'T-' in o and f.get('A:\\K.TXT') == big
          and not probs and f.get('A:\\C3.TXT') == b'c' * 1500, (o, probs))
    # an append onto a whole cluster (a cluster taken, the FAT changed, before its write fails) with its own
    # INT 24h answering Abort always: terminate's closes (that handler still) and its flush (the shell's: A)
    # Fail an Abort (each one terminated again, and asked again, for ever)
    kw = b'k' * 5120
    k = ktest.KPC(image('wpt.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wpk5', kw),
                        probe('WPAPPA'))); k.start()
    sh = Shell(k)
    k.pc.drives[0].wp = True
    o = answer(k, 'wpappa', 'a')
    k.pc.drives[0].wp = False
    back = sh.run('ver')
    sh.run('echo hello> z.txt')
    f = fs(k); probs = fatcheck.check(bytes(k.pc.drives[0].img))[0]
    check('an append refused on a write-protected A: (Abort, its own INT 24h), A at the shell\'s prompt (%d): '
          'terminate\'s closes and flush Fail an Abort, the prompt back; the tab off: K.TXT as it was, the disk '
          'consistent but for the cluster the append took (its chain the longer: lost at worst)' % o.count('Fail?'),
          o.count('Fail?') == 1 and 'Lodestone' in back and f.get('A:\\K.TXT') == kw
          and all('K.TXT' in p and 'chain has' in p for p in probs), (o, probs))
    # another file open and written, then a failed create (Fail), then written again: none of it lost
    kd = b'keep-me' + b'T' * 1000
    k = ktest.KPC(image('wpc.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wpk4', kd), probe('WPCOLL')))
    k.start()
    sh = Shell(k); pc = k.pc
    k.key('cls'); k.key(ktest.ENTER)
    n0 = len(pc.tty)
    k.key('wpcoll'); k.key(ktest.ENTER, settle=False)
    pc.run_until(lambda: 'A' in ''.join(pc.tty)[n0 + 6:] or pc.crash, 15); k.settle()
    pc.drives[0].wp = True
    k.key(ktest.ENTER, settle=False)
    pc.run_until(lambda: 'Z' in ''.join(pc.tty)[n0 + 6:] or pc.crash, 15); k.settle()
    pc.drives[0].wp = False
    k.key(ktest.ENTER, settle=False)
    pc.run_until(lambda: 'C' in ''.join(pc.tty)[n0 + 6:].replace('WPCOLL', '') or pc.crash, 15); k.settle()
    o = ''.join(pc.tty)[n0:]
    f = fs(k); probs = fatcheck.check(bytes(pc.drives[0].img))[0]
    check('K.TXT open, 600 bytes written, a create on the write-protected disk refused (Fail), the tab off, 600 '
          'more and closed: K.TXT with both, its writes and close accepted, the disk consistent',
          'A+' in o and 'Z-' in o and 'B+' in o and 'C+' in o and f.get('A:\\K.TXT') == kd + b'w' * 1200 and not probs,
          (o, probs, len(f.get('A:\\K.TXT') or b'')))
    # Retry with the tab off by then: done after all
    k = ktest.KPC(image('wpf.img', os.path.join(GOS, 'src', 'LCMD.COM'), *files)); k.start()
    sh = Shell(k)
    k.pc.drives[0].wp = True
    o = answer(k, 'copy n.txt k.txt', 'r')
    f = fs(k); probs = fatcheck.check(bytes(k.pc.drives[0].img))[0]
    check('COPY N.TXT K.TXT on a write-protected A:, the tab off, R: copied, K.TXT is N.TXT\'s, the disk consistent',
          'Fail?' in o and '1 File(s) copied' in o and f.get('A:\\K.TXT') == b'nnn' and not probs, (o, probs))
    lost_only = lambda probs, n: all('lost clusters' in p for p in probs) and sum(
        int(p.split()[0]) for p in probs) <= n
    def run3(k, name, *keys_then):
        # NAME at the prompt; at each of its pauses (a status letter seen) keys_then's function, then a key
        pc = k.pc
        k.key('cls'); k.key(ktest.ENTER)
        n0 = len(pc.tty)
        k.key(name); k.key(ktest.ENTER, settle=False)
        for mark, fn in keys_then:
            pc.run_until(lambda: mark in ''.join(pc.tty)[n0 + len(name):] or pc.crash, 15); k.settle()
            fn()
            k.key(ktest.ENTER, settle=False)
        pc.run_until(lambda: 'C' in ''.join(pc.tty)[n0 + len(name):] or pc.crash, 15); k.settle()
        return ''.join(pc.tty)[n0:]
    # rule 1: another disk put in while the FAT cache holds a file's changes (K.TXT appended to, still open): it
    # has this disk's boot sector (BPB, serial and label), so only its FAT sector 0 tells it apart.  Taken for
    # the same disk (a changed cache vouched for it), that disk got this one's FAT: every file cross-linked
    kd = b'keep-me' + b'T' * 1000
    p = image('wps.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wps1', kd), probe('WPCOLL'))
    p2 = image('wps2.img', 'D2A.TXT=' + mkf('wps2a', b'a' * 3000), 'D2B.TXT=' + mkf('wps2b', b'b' * 7000))
    d1 = open(p, 'rb').read(); d2 = bytearray(open(p2, 'rb').read()); d2[0:512] = d1[0:512]
    k = ktest.KPC(p); k.start(); sh = Shell(k); pc = k.pc
    def swap():
        pc.drives[0].img[:] = bytes(d2); pc.drives[0].changed = True
    o = run3(k, 'wpcoll', ('A', swap), ('Z', lambda: None))
    img = bytes(pc.drives[0].img); probs = fatcheck.check(img)[0]; f = fatcheck.read_files(img)
    check('a disk with the same boot sector put in while K.TXT\'s changes are in the cached FAT (WPCOLL): known for '
          'another by its FAT sector 0, "Invalid disk change" (its own INT 24h: Fail): Z.TXT refused, K.TXT\'s '
          'writes and close refused, the other disk\'s files whole',
          'A+' in o and 'Z-' in o and 'B-5' in o and 'C-5' in o and not probs and f.get('A:\\D2B.TXT') == b'b' * 7000
          and f.get('A:\\D2A.TXT') == b'a' * 3000 and 'A:\\Z.TXT' not in f, (o, probs, sorted(f)))
    # rule 4: INT 21h 0Dh when the FAT can't be written (E.TXT made and 600 bytes written, then the tab on): the
    # cache dropped, and E.TXT's later write and close refused.  Its handle kept its place in a chain the disk
    # never had: the next write walked into a free entry and took clusters until the disk was full
    k = ktest.KPC(image('wpr.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wpr1', kd),
                        probe('WPDRSTE'))); k.start()
    sh = Shell(k); pc = k.pc
    def wpon(): pc.drives[0].wp = True
    def wpoff(): pc.drives[0].wp = False
    o = run3(k, 'wpdrste', ('A', wpon), ('Z', wpoff))
    sh.run('copy k.txt k2.txt'); sh.run('echo hello> z.txt')
    img = bytes(pc.drives[0].img); probs = fatcheck.check(img)[0]; f = fatcheck.read_files(img)
    check('E.TXT written, INT 21h 0Dh on the write-protected disk (WPDRSTE): its changes dropped, its later write '
          'and close refused (5); the tab off: the disk consistent, nothing taken, K.TXT copied whole',
          'A+' in o and 'B-5' in o and 'C-5' in o and not probs and f.get('A:\\K2.TXT') == kd
          and f.get('A:\\Z.TXT') == b'hello\r\n', (o, probs, len(f.get('A:\\E.TXT') or b'')))
    # rule 5: an append refused (Fail) gives back what it took: no FAT left changed, so a program's start and
    # end, and DIR, after it ask nothing (each asked again "Write protect error"), and C:'s calls are C:'s
    k = ktest.KPC(image('wpk.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wpk6', b'k' * 1024),
                        probe('WPAPW'), probe('WPNOP'))); k.start()
    sh = Shell(k)
    k.pc.drives[0].wp = True
    o = answer(k, 'wpapw', 'f')
    o2 = answer(k, 'wpnop', 'f') + answer(k, 'wpnop', 'f') + answer(k, 'dir', 'f')
    k.pc.drives[0].wp = False
    sh.run('echo hi> z.txt')
    img = bytes(k.pc.drives[0].img); probs = fatcheck.check(img)[0]; f = fatcheck.read_files(img)
    check('an append refused on a write-protected A: (WPAPW, its own Fail): the clusters it took given back; two '
          'programs and DIR after it: no prompt; the tab off: K.TXT as it was, the disk consistent',
          'Fail?' not in o2 and 'File(s)' in o2 and not probs and f.get('A:\\K.TXT') == b'k' * 1024, (o, o2, probs))
    # rule 2 (dir_slot): SUB full, its directory grows on the write-protected disk (WPDSLOT), Abort at the
    # shell's prompt, then F or R at terminate's flush (the tab off for R): the new cluster was linked before it
    # was zeroed, and the link went out: SUB showed 16 stale entries (old data), cross-linked with K.TXT.  Now
    # zeroed first: one cluster lost at worst
    for keys in ('af', 'ar'):
        files2 = [os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wpd1', b'k' * 1000), 'SUB\\'] + \
                 ['SUB\\F%02d.TXT=%s' % (i, mkf('wpd_f%d' % i, b'x' * 10)) for i in range(14)] + [probe('WPDSLOT')]
        p = image('wpd.img', *files2)
        img = bytearray(open(p, 'rb').read())
        b = fatcheck.bpb(img)
        root = (b['res'] + b['nfat'] * b['spf']) * 512
        kcl = next(struct.unpack_from('<H', img, root + i + 26)[0] for i in range(0, 224 * 32, 32)
                   if img[root + i:root + i + 11] == b'K       TXT')
        ghost = b'GHOST   TXT ' + b'\0' * 14 + struct.pack('<HI', kcl, 1000)
        data = root + 14 * 512
        fat = img[b['res'] * 512:(b['res'] + b['spf']) * 512]
        get = lambda n: (struct.unpack_from('<H', fat, n * 3 // 2)[0] >> 4) if n & 1 else (struct.unpack_from('<H', fat, n * 3 // 2)[0] & 0xFFF)
        for c in range(2, 2849):
            if get(c) == 0: img[data + (c - 2) * 512:data + (c - 1) * 512] = ghost * 16
        open(p, 'wb').write(img)
        k = ktest.KPC(p); k.start(); sh = Shell(k); pc = k.pc
        pc.drives[0].wp = True
        k.key('cls'); k.key(ktest.ENTER)
        n0 = len(pc.tty)
        k.key('wpdslot'); k.key(ktest.ENTER, settle=False)
        for i, key in enumerate(keys):
            pc.run_until(lambda: ''.join(pc.tty)[n0:].count('Fail?') > i or pc.crash, 15)
            if ''.join(pc.tty)[n0:].count('Fail?') <= i: break
            if key == 'r': pc.drives[0].wp = False
            pc.keys.append(ord(key))
        k.settle()
        pc.drives[0].wp = False
        sh.run('echo hello> z.txt')
        img = bytes(pc.drives[0].img); probs, fl = fatcheck.check(img)
        check('SUB full, SUB\\NEW.TXT on the write-protected disk (its directory grows), %s: no stale entries in SUB, '
              'nothing cross-linked: one cluster lost at most' % ' then '.join(keys.upper()),
              lost_only(probs, 1) and not any('GHOST' in n for n in fl), (probs, sorted(n for n in fl if 'SUB' in n)))
    # a FAT flush that fails half-way (FAT sector 3 refuses), then the cache dropped: a restart, or INT 21h 0Dh
    # (WPRST): what of it reached the disk stays, but nothing names a cluster the FAT has free; the disk filled
    # after (FILLER.BIN copied): nothing cross-linked
    for mode in ('reset', 'restart'):
        k = ktest.KPC(image('wpp2.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wpk7', b'k' * 1000),
                            'FILLER.BIN=' + mkf('wpfill2', b'f' * 420000), probe('WPAPPK'), probe('WPRST'))); k.start()
        sh = Shell(k); pc = k.pc; d = pc.drives[0]
        bad = Bad(); d.wp = bad; bad.on = True
        o = answer(k, 'wpappk', 'f')
        if mode == 'reset':
            answer(k, 'wprst', 'f'); bad.on = False
        else:
            bad.on = False
            sv = os.path.join(OUT, 'wpp2_after.img'); d.save(sv)
            k = ktest.KPC(sv); k.start(); sh = Shell(k); d = k.pc.drives[0]
        sh.run('copy filler.bin f2.bin')
        probs = fatcheck.check(bytes(d.img))[0]
        check('a FAT flush failing on its second run (WPAPPK, Fail), then %s, then FILLER.BIN copied: nothing '
              'cross-linked, no cluster free in a chain' % ('INT 21h 0Dh' if mode == 'reset' else 'a restart'),
              all('cross-linked' not in p and 'free' not in p for p in probs), (o, probs))
    # RENAME across directories (K.TXT to SUB\K2.TXT) with only the old entry's sector (the root's first)
    # refusing: the new entry written, the old one not; the new one taken out again, so no two entries name
    # K.TXT's chain (DEL SUB\K2.TXT then freed it under K.TXT: cross-linked with the next file)
    k = ktest.KPC(image('wpn.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wpn1', b'k' * 3000), 'SUB\\',
                        probe('WPRNM'))); k.start()
    sh = Shell(k); pc = k.pc; d = pc.drives[0]
    class Bad19:
        on = False
        def __bool__(s):
            if not s.on: return False
            cx, dx, al = pc.r('cx'), pc.r('dx'), pc.r('ax') & 0xFF
            lba = (((cx >> 8) | ((cx & 0xC0) << 2)) * d.heads + (dx >> 8)) * d.spt + (cx & 63) - 1
            return lba <= 19 < lba + al
    bad = Bad19(); d.wp = bad; bad.on = True
    o = sh.run('wprnm')
    bad.on = False
    o2 = sh.run('del sub\\k2.txt') + sh.run('copy lcmd.com x.com')
    img = bytes(d.img); probs = fatcheck.check(img)[0]; f = fatcheck.read_files(img)
    check('K.TXT renamed SUB\\K2.TXT, the old entry\'s sector refusing: "-", K.TXT as it was, no SUB\\K2.TXT; DEL '
          'and a copy after: the disk consistent', '-' in o and f.get('A:\\K.TXT') == b'k' * 3000
          and 'A:\\SUB\\K2.TXT' not in f and not probs, (o, o2, probs))
    # rule 4's INT 24h 0Fh: COPY B:K.TXT+B:X1.TXT+B:X2.TXT B:K.TXT, another disk put in B: at X2's open (its own
    # files, label and serial), K.TXT's changes still to go: "Invalid disk change" (LCMD: its code past its list,
    # "General failure").  Fail: K.TXT's changes dropped, the other disk untouched (K.TXT's chain and entry went to
    # it); Retry with the right disk back: the copy goes on as if nothing happened
    k0 = b'keep-me\r\n\x1a'
    b1 = image('dcb1.img', 'K.TXT=' + mkf('dck', k0), 'X1.TXT=' + mkf('dcx1', b'x' * 3000),
               'X2.TXT=' + mkf('dcx2', b'y' * 3000), 'OUT.DAT=' + mkf('dco', b'OLD'))
    b2 = image('dcb2.img', 'P1.TXT=' + mkf('dcp1', b'P1' * 3000), 'X2.TXT=' + mkf('dcx2b', b'z' * 3000),
               'P2.TXT=' + mkf('dcp2', b'P2' * 3000))
    img2 = bytearray(open(b2, 'rb').read())
    i = img2.find(b'LODESTONE  ', 19 * 512); img2[i:i + 11] = b'OTHERDISK  '
    j = img2.find(b'LODESTONE  ', 0, 512)
    if j > 0: img2[j:j + 11] = b'OTHERDISK  '
    img2[0x27:0x2B] = b'\x12\x34\x56\x78'
    img2 = bytes(img2)
    for ans in ('f', 'r'):
        k = ktest.KPC(image('dca.img', os.path.join(GOS, 'src', 'LCMD.COM')), b=b1); k.start()
        sh = Shell(k); pc = k.pc
        first, other = pc.drives[1], pcemu.Floppy(bytearray(img2))
        def swap(pc):
            if k.addr == k.i21 and pc.r('ax') >> 8 == 0x3D and pc.drives[1] is first \
                    and pc.asciiz(pc.r('ds'), pc.r('dx')).upper().endswith(b'X2.TXT'):
                other.changed = True; pc.drives[1] = other
        k.hooks.append(swap)
        k.key('cls'); k.key(ktest.ENTER)
        n0 = len(pc.tty)
        k.key('copy b:k.txt+b:x1.txt+b:x2.txt b:k.txt'); k.key(ktest.ENTER, settle=False)
        n = 0
        for _ in range(6):
            pc.run_until(lambda: ''.join(pc.tty)[n0:].count('Fail?') > n or 'copied' in ''.join(pc.tty)[n0:], 30)
            if ''.join(pc.tty)[n0:].count('Fail?') <= n: break
            n += 1
            if ans == 'r':
                k.hooks.remove(swap); first.changed = True; pc.drives[1] = first
            pc.keys.append(ord(ans))
        k.settle()
        o = ''.join(pc.tty)[n0:]
        if pc.drives[1] is other:
            first.changed = True; pc.drives[1] = first
        o2 = sh.run('dir b:') + sh.run('echo x> b:zz.txt')
        img = bytes(first.img); probs = fatcheck.check(img)[0]; f = fatcheck.read_files(img)
        if ans == 'f':
            check('COPY B:K.TXT+B:X1.TXT+B:X2.TXT B:K.TXT, another disk in B: at X2\'s open, K.TXT\'s changes still to '
                  'go: "Fail?" asked; Fail: the other disk untouched; the right one back: K.TXT as it was, nothing '
                  'cross-linked (lost clusters at most), a file made after', n >= 1 and bytes(other.img) == img2
                  and f.get('A:\\K.TXT') == k0 and lost_only(probs, 16) and f.get('A:\\ZZ.TXT') == b'x\r\n',
                  (o, o2, probs, f.get('A:\\K.TXT', b'')[:20]))
        else:
            kt = f.get('A:\\K.TXT') or b''
            check('... Retry with the right disk back: the copy goes on (1 file copied), K.TXT whole, the disk '
                  'consistent, the other disk untouched', n == 1 and 'copied' in o and bytes(other.img) == img2
                  and kt.startswith(b'keep-me\r\n' + b'x' * 3000 + b'y' * 3000) and not probs,
                  (o, o2, probs, len(kt)))
    # ... and from a program (WPSWAP: K.TXT appended to, INT 21h 0Dh, so only its entry is still to go, a key,
    # Z.TXT made, its end with K.TXT open), the shell's prompt answered Abort or Fail: K.TXT's changes dropped
    # before terminate's closes (its entry went to the other disk); Retry with the right disk back: Z.TXT made,
    # K.TXT closed whole
    p2 = image('wpw2.img', 'D2A.TXT=' + mkf('wpw2a', b'a' * 3000), 'D2B.TXT=' + mkf('wpw2b', b'b' * 7000))
    d2 = open(p2, 'rb').read()
    for ans in ('a', 'f', 'r'):
        k = ktest.KPC(image('wpw.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wpw1', kd),
                            probe('WPSWAP'))); k.start()
        sh = Shell(k); pc = k.pc; d = pc.drives[0]
        k.key('cls'); k.key(ktest.ENTER)
        n0 = len(pc.tty)
        k.key('wpswap'); k.key(ktest.ENTER, settle=False)
        pc.run_until(lambda: 'A' in ''.join(pc.tty)[n0 + 6:] or pc.crash, 15); k.settle()
        d1 = bytes(d.img); d.img[:] = d2; d.changed = True
        pc.keys.append(13)
        pc.run_until(lambda: 'Fail?' in ''.join(pc.tty)[n0:] or pc.crash, 15); k.settle()
        asked = 'Fail?' in ''.join(pc.tty)[n0:]
        if ans == 'r':
            other = bytes(d.img); d.img[:] = d1; d.changed = True
        else:
            other = None
        pc.keys.append(ord(ans))
        pc.run_until(lambda: ''.join(pc.tty)[n0:].count('Fail?') > 1 or ''.join(pc.tty).endswith('>') or pc.crash, 15)
        k.settle()
        o = ''.join(pc.tty)[n0:]
        if ans != 'r':
            other = bytes(d.img); d.img[:] = d1; d.changed = True
        sh.run('echo hello> y.txt')
        img = bytes(d.img); probs = fatcheck.check(img)[0]; f = fatcheck.read_files(img)
        if ans != 'r':
            check('WPSWAP: K.TXT appended to and its FAT written, another disk in, Z.TXT made: "Invalid disk change" '
                  'asked; %s the other disk untouched; the right one back: K.TXT\'s entry as it was (its chain longer: '
                  'what the FAT took first, rule 2)'
                  % ('Abort:' if ans == 'a' else 'Fail: Z.TXT refused (Z-),'),
                  asked and other == d2 and f.get('A:\\K.TXT') == kd and ('Z-' in o) == (ans == 'f') and 'Z+' not in o
                  and all('K.TXT' in p and 'chain has' in p for p in probs)
                  and f.get('A:\\Y.TXT') == b'hello\r\n', (o, probs))
        else:
            check('... Retry with the right disk back: Z.TXT made (Z+), K.TXT closed whole, the disk consistent, the '
                  'other disk untouched', asked and 'Z+' in o and other == d2 and len(f.get('A:\\K.TXT') or b'') == len(kd) + 600
                  and f['A:\\K.TXT'].startswith(kd) and 'A:\\Z.TXT' in f
                  and not probs, (o, probs, len(f.get('A:\\K.TXT') or b'')))
    # rule 7: a broken chain (its first entry free) walked to its end: an append to K.TXT, a file made in a full
    # SUB.  Taken as a cluster, the free entry led to entry 0 (the media byte's, read as an end): K.TXT took
    # clusters until the disk was full; SUB's new cluster was its own (free in the FAT), zeroed
    def fat12(img, n, v=None):
        b = fatcheck.bpb(img); o = b['res'] * 512 + n * 3 // 2
        w = struct.unpack_from('<H', img, o)[0]
        if v is None: return (w >> 4) if n & 1 else (w & 0xFFF)
        w = ((w & 0x000F) | (v << 4)) if n & 1 else ((w & 0xF000) | v)
        struct.pack_into('<H', img, o, w)
    def first(img, name, d=None):
        b = fatcheck.bpb(img)
        root = (b['res'] + b['nfat'] * b['spf']) * 512
        return next(struct.unpack_from('<H', img, root + i + 26)[0] for i in range(0, 224 * 32, 32)
                    if img[root + i:root + i + 11] == name)
    files2 = [os.path.join(GOS, 'src', 'LCMD.COM'), 'K.TXT=' + mkf('wpb1', b'k' * 3000), 'SUB\\'] + \
             ['SUB\\F%02d.TXT=%s' % (i, mkf('wpb_f%d' % i, b'x' * 10)) for i in range(14)]
    # (also its first entry bad, FF7h, or reserved, FF0h: once taken for its end; and SUB's chain looping on
    # itself: once walked for ever)
    for what, name, cmd, v in (('an append to K.TXT', b'K       TXT', 'echo hi>> k.txt', 0),
                               ('a file made in the full SUB', b'SUB        ', 'echo hi> sub\\new.txt', 0),
                               ('an append to K.TXT (bad: FF7h)', b'K       TXT', 'echo hi>> k.txt', 0xFF7),
                               ('an append to K.TXT (reserved: FF0h)', b'K       TXT', 'echo hi>> k.txt', 0xFF0),
                               ('a file made in the full SUB (a loop)', b'SUB        ', 'echo hi> sub\\new.txt', None)):
        p = image('wpb.img', *files2)
        img = bytearray(open(p, 'rb').read())
        b = fatcheck.bpb(img)
        fat12(img, first(img, name), first(img, name) if v is None else v)
        f2 = (b['res'] + b['spf']) * 512
        img[f2:f2 + b['spf'] * 512] = img[b['res'] * 512:(b['res'] + b['spf']) * 512]
        open(p, 'wb').write(img)
        h0 = bytes(img[b['res'] * 512:(b['res'] + b['nfat'] * b['spf']) * 512])
        k = ktest.KPC(p); k.start(); sh = Shell(k)
        o = sh.run(cmd)
        o2 = sh.run('dir sub' if v is not None else 'dir sub\\f13.txt')
        img = bytes(k.pc.drives[0].img)
        h1 = img[b['res'] * 512:(b['res'] + b['nfat'] * b['spf']) * 512]
        check('%s, its chain broken (its first entry free unless said): refused, the FAT as it was (no cluster taken, none '
              'linked from entry 0), SUB\'s entries all there' % what, h1 == h0 and 'F13      TXT' in o2, (o, o2[-60:], h0[:3].hex(), h1[:3].hex(),
              sum(1 for i in range(len(h0)) if h0[i] != h1[i])))

def t_mount():
    """A floppy's mounts (KDISK.INC rules 1, 4, 7, 9): another disk in B: while a file is open on the old one,
    with changes to go or none, and with the FAT cache moved to A: (each floppy's own FAT sector 0 sum): "Invalid
    disk change", Fail: the file's later calls refused, the other disk untouched.  INT 21h 0Dh, then a program
    rewriting the FAT (as CHKDSK /F, DEFRAG): the current directory kept.  A chain leading past the disk's end, or
    into a bad or reserved entry, or a directory looping on itself: a broken chain, nothing written past the FAT."""
    def mkf(n, b):
        t = os.path.join(OUT, 'mnt_' + n.replace('\\', '_')); open(t, 'wb').write(b); return n + '=' + t
    def probe(name, defs=()):
        c = os.path.join(OUT, name + ''.join('_' + d for d in defs) + '.COM')
        subprocess.run(['nasm', '-f', 'bin'] + ['-D' + d for d in defs] + ['-o', c, os.path.join(HERE, name + '.ASM')],
                       check=True)
        return name + '.COM=' + c
    lcmd = os.path.join(GOS, 'src', 'LCMD.COM')
    def run_swap(k, name, swap, keys):
        pc = k.pc
        k.key('cls'); k.key(ktest.ENTER)
        n0 = len(pc.tty)
        k.key(name); k.key(ktest.ENTER, settle=False)
        pc.run_until(lambda: 'R' in ''.join(pc.tty)[n0 + len(name):] or pc.crash, 15); k.settle()
        swap()
        k.key(ktest.ENTER, settle=False)
        for i, key in enumerate(keys):
            pc.run_until(lambda: ''.join(pc.tty)[n0:].count('Fail?') > i or 'C' in ''.join(pc.tty)[n0 + len(name):]
                         or pc.crash, 15)
            if ''.join(pc.tty)[n0:].count('Fail?') <= i: break
            pc.keys.append(ord(key))
        pc.run_until(lambda: 'C' in ''.join(pc.tty)[n0 + len(name):] or pc.crash, 15); k.settle()
        return ''.join(pc.tty)[n0 + len(name):]
    kk = b'k' * 3000
    b1 = image('mnt_b1.img', mkf('K.TXT', kk), mkf('X1.TXT', b'x' * 3000))
    b2 = image('mnt_b2.img', mkf('P1.TXT', b'P' * 9000), mkf('P2.TXT', b'Q' * 9000), mkf('P3.TXT', b'R' * 900))
    d1 = open(b1, 'rb').read(); d2 = bytearray(open(b2, 'rb').read()); d2[0:512] = d1[0:512]; d2 = bytes(d2)
    for defs, what in (((), 'B:OUT.DAT written, the FAT cache moved to A:'),
                       (('OPENK',), 'B:K.TXT open, nothing written'),
                       (('OPENK', 'NOA'), 'B:K.TXT open, nothing written, the FAT cache B:\'s')):
        k = ktest.KPC(image('mnt_a.img', lcmd, probe('MNTSWB', defs)), b=b1); k.start()
        sh = Shell(k); pc = k.pc
        first = pc.drives[1]; other = pcemu.Floppy(bytearray(d2)); other.change_err = True
        def swap():
            other.changed = True; pc.drives[1] = other
        o = run_swap(k, 'mntswb', swap, 'f')
        first.changed = True; pc.drives[1] = first
        o2 = sh.run('dir b:') + sh.run('echo x> b:zz.txt')
        img = bytes(first.img); probs = fatcheck.check(img)[0]; f = fatcheck.read_files(img)
        check('%s, another disk (the same boot sector) in B:: "Invalid disk change" asked, Fail: the write refused '
              '(B-5: 5, a handle call\'s code), %s; the other disk untouched; the first back: K.TXT as it was, the disk consistent'
              % (what, 'its close too, the other disk mounted for it (C-5)' if not defs else 'its close lets it go (C+)'),
              'Fail?' in o and 'B-5' in o and ('C-5' if not defs else 'C+') in o and bytes(other.img) == d2
              and f.get('A:\\K.TXT') == kk and not [p for p in probs if 'lost clusters' not in p]
              and f.get('A:\\ZZ.TXT') == b'x\r\n', (o, o2[-200:], probs))
    # a file open on B: (nothing to go), another disk in B:, Retry with it still there: asked again
    k = ktest.KPC(image('mnt_a.img', lcmd, probe('MNTSWB', ('OPENK',))), b=b1); k.start()
    sh = Shell(k); pc = k.pc
    first = pc.drives[1]; other = pcemu.Floppy(bytearray(d2)); other.change_err = True
    def swap2():
        other.changed = True; pc.drives[1] = other
    o = run_swap(k, 'mntswb', swap2, 'rf')
    check('... Retry with the other disk still in: asked again, then Fail: the write refused, nothing written to it',
          o.count('Fail?') == 2 and 'B-5' in o and bytes(other.img) == d2, (o,))
    # B:K.TXT open, another disk with a K.TXT in the same directory slot: DEL B:K.TXT asks, Fail (the old disk
    # dropped); again: the new disk's K.TXT deleted, not refused for the old disk's file still open (sft_busy
    # skips SF_LOST: another mount's)
    d3 = bytearray(open(image('mnt_b3.img', mkf('K.TXT', b'n' * 5000)), 'rb').read()); d3[0:512] = d1[0:512]; d3 = bytes(d3)
    k = ktest.KPC(image('mnt_a.img', lcmd, probe('MNTSWB', ('OPENK', 'DELB'))), b=b1); k.start()
    sh = Shell(k); pc = k.pc
    first = pc.drives[1]; other = pcemu.Floppy(bytearray(d3)); other.change_err = True
    def swap3():
        other.changed = True; pc.drives[1] = other
    o = run_swap(k, 'mntswb', swap3, 'f')
    f3 = fatcheck.read_files(bytes(other.img))
    check('B:K.TXT open, another disk with its own K.TXT in the same slot: DEL B:K.TXT asked, Fail (3, as resolve answers a drive it can\'t ready); DEL '
          'again: the new disk\'s K.TXT deleted (the old file\'s SFT not taken for it), the first disk untouched',
          o.count('Fail?') == 1 and 'D-3' in o and 'E+' in o and 'A:\\K.TXT' not in f3
          and not fatcheck.check(bytes(other.img))[0] and bytes(first.img) == d1, (o, sorted(f3)))
    # INT 21h 0Dh, then a program rewrites A:'s FAT sector 0 through INT 13h, INT 21h 0Dh: the current directory
    # kept (found again by its name), its files listed
    k = ktest.KPC(image('mnt_w.img', lcmd, probe('MNTFATW'), 'SUB\\', mkf('SUB\\A.TXT', b'a' * 100))); k.start()
    sh = Shell(k)
    sh.run('cd sub')
    o = sh.run('mntfatw') + sh.run('cd') + sh.run('dir /w')
    check('CD SUB, then MNTFATW (INT 21h 0Dh, the FAT rewritten through INT 13h, 0Dh): still A:\\SUB, A.TXT listed',
          'Directory of  A:\\SUB' in o and 'A        TXT' in o and 'A:\\>' not in o, o[-300:])
    # another disk in B: with nothing of the old one's open: mounted, B:'s current directory found on it by its
    # name (MS-DOS's), else the root
    s1 = image('mnt_s1.img', 'SUB\\', mkf('SUB\\ONE.TXT', b'1'))
    s2 = image('mnt_s2.img', mkf('PAD.TXT', b'p' * 5000), 'SUB\\', mkf('SUB\\TWO.TXT', b'2'))
    s3 = image('mnt_s3.img', mkf('THREE.TXT', b'3'))
    k = ktest.KPC(image('mnt_sa.img', lcmd), b=s1); k.start()
    sh = Shell(k); pc = k.pc
    o1 = sh.run('cd b:sub') + sh.run('dir b:')
    pc.drives[1] = pcemu.Floppy(s2); pc.drives[1].changed = True
    o2 = sh.run('dir b:') + sh.run('cd b:')
    pc.drives[1] = pcemu.Floppy(s3); pc.drives[1].changed = True
    o3 = sh.run('dir b:') + sh.run('cd b:')
    check('CD B:SUB, another disk with a SUB of its own (another cluster) in B:: its SUB\'s files, B:\\SUB; one '
          'without: the root\'s, B:\\', 'ONE      TXT' in o1 and 'TWO      TXT' in o2 and '>B:\\SUB\n' in o2
          and 'THREE    TXT' in o3 and '>B:\\\n' in o3, (o1[-150:], o2[-150:], o3[-150:]))
    # ... from a batch file on A: (open while MNTFATW runs: the rewritten disk is still the same disk, its FAT
    # sector 0 sum forgotten at 0Dh with nothing to go, not "Invalid disk change" for the rest of it)
    k = ktest.KPC(image('mnt_w.img', lcmd, probe('MNTFATW'), 'SUB\\', mkf('SUB\\A.TXT', b'a' * 100),
                        mkf('T.BAT', b'cd sub\r\nmntfatw\r\ncd\r\ndir /w\r\n'))); k.start()
    sh = Shell(k)
    o = sh.run('t')
    check('... from a batch file on A:: no question asked, the batch file read on, still A:\\SUB, A.TXT listed',
          'Fail?' not in o and 'Directory of  A:\\SUB' in o and 'A        TXT' in o, o[-300:])
    # a write's INT 13h failing 06h (another disk put in B: after the call looked at the drive): not tried again
    # on that disk; asked there and then ("Invalid disk change", as MS-DOS), Fail: the write refused, the old
    # disk's files with it (the close refused, not asked again)
    k = ktest.KPC(image('mnt_a.img', lcmd, probe('MNTSWB', ('NOA',))), b=b1); k.start()
    sh = Shell(k); pc = k.pc
    first = pc.drives[1]; other = pcemu.Floppy(bytearray(d2)); other.change_err = True
    st = {'arm': False}
    dio = 0x600 + k.Y['disk_io']
    def at_dio(pc):
        if st['arm'] and k.addr == dio and pc.r('ax') & 0xFF == 1 and pc.r('ax') >> 8 == 3:
            st['arm'] = False; other.changed = True; pc.drives[1] = other
    k.hooks.append(at_dio)
    o = run_swap(k, 'mntswb', lambda: st.update(arm=True), 'f')
    first.changed = True; pc.drives[1] = first
    o2 = sh.run('dir b:')
    img = bytes(first.img); probs = fatcheck.check(img)[0]
    check('a write\'s INT 13h failing 06h (another disk put in under it): "Invalid disk change" asked at once, '
          'Fail: refused (B-), the close too (C-5, not asked again), the other disk untouched; the first back: '
          'consistent but for lost clusters', not st['arm'] and 'B-' in o and 'B+' not in o and 'C-5' in o
          and o.count('Fail?') == 1 and o.find('Fail?') < o.find('B-')
          and bytes(other.img) == d2 and not [p for p in probs if 'lost clusters' not in p], (o, probs))
    # a file open on B: (nothing to go), the change line set and B:'s boot sector failing to read once: INT 24h
    # for that read (Retry: the same disk, the file goes on), not "Invalid disk change"
    k = ktest.KPC(image('mnt_a.img', lcmd, probe('MNTSWB', ('OPENK',))), b=b1); k.start()
    sh = Shell(k); pc = k.pc; first = pc.drives[1]
    def badboot():
        first.bad = {0}; first.changed = True
    k.key('cls'); k.key(ktest.ENTER)
    n0 = len(pc.tty)
    k.key('mntswb'); k.key(ktest.ENTER, settle=False)
    pc.run_until(lambda: 'R' in ''.join(pc.tty)[n0 + 6:] or pc.crash, 15); k.settle()
    badboot(); k.key(ktest.ENTER, settle=False)
    pc.run_until(lambda: 'Fail?' in ''.join(pc.tty)[n0:] or 'C' in ''.join(pc.tty)[n0 + 6:] or pc.crash, 15); k.settle()
    first.bad = set(); pc.keys.append(ord('r'))
    pc.run_until(lambda: 'C' in ''.join(pc.tty)[n0 + 6:] or pc.crash, 15); k.settle()
    o = ''.join(pc.tty)[n0:]
    check('B:K.TXT open, B:\'s boot sector unreadable at the change line\'s look: "reading drive B" asked (not '
          '"Invalid disk change"), Retry: the write goes on (B+), closed (C+)', 'reading drive B' in o
          and 'General failure' not in o and 'B+' in o and 'C+' in o, o[-300:])
    # rule 7: a chain leading past the disk's end (B:, 720 KB: cluster 500h).  fat_get read the cache past B:'s
    # FAT (A:'s entries, an end), DEL's fat_set marked a sector past it, and the flush wrote B:'s root with it
    def fat12(img, off, n, v=None):
        o = off + n * 3 // 2; w = struct.unpack_from('<H', img, o)[0]
        if v is None: return (w >> 4) if n & 1 else (w & 0xFFF)
        struct.pack_into('<H', img, o, ((w & 0x000F) | (v << 4)) if n & 1 else ((w & 0xF000) | v))
    def ent(img, off, n, name):
        return next(struct.unpack_from('<H', img, off + i + 26)[0] for i in range(0, n * 32, 32)
                    if img[off + i:off + i + 11] == name)
    bp = mkimg.build(os.path.join(OUT, 'mnt_oor.img'), ['SUB\\', mkf('SUB\\K.TXT', b'k' * 2048), mkf('M.TXT', b'm' * 3000)],
                     size=720)
    b = bytearray(open(bp, 'rb').read()); B = fatcheck.bpb(b)
    root = (B['res'] + B['nfat'] * B['spf']) * 512
    so = (B['res'] + B['nfat'] * B['spf'] + 7 + (ent(b, root, 112, b'SUB        ') - 2) * 2) * 512
    kcl = ent(b, so, 32, b'K       TXT')
    for c in range(B['nfat']): fat12(b, (B['res'] + c * B['spf']) * 512, kcl, 0x500)
    open(bp, 'wb').write(b); b0 = bytes(b)
    def safe_files(img):
        try: return fatcheck.read_files(img)
        except struct.error: return {}
    # a file starting past the disk's end (B:Q.TXT at 500h), the cache past B:'s FAT holding A:'s entry for it, a
    # link to 3 (A:'s FAT made so): an append walked into B:'s cluster 3's chain and linked onto it
    bq = mkimg.build(os.path.join(OUT, 'mnt_q.img'), [mkf('X.TXT', b'x' * 5000), mkf('Q.TXT', b'q' * 3000)], size=720)
    b = bytearray(open(bq, 'rb').read()); B = fatcheck.bpb(b)
    root = (B['res'] + B['nfat'] * B['spf']) * 512
    i = next(i for i in range(0, 112 * 32, 32) if b[root + i:root + i + 11] == b'Q       TXT')
    struct.pack_into('<H', b, root + i + 26, 0x500); open(bq, 'wb').write(b)
    pa = image('mnt_qa.img', lcmd, mkf('FILL.BIN', b'f' * 1400 * 512))
    a = bytearray(open(pa, 'rb').read()); fat12(a, 512, 0x500, 3); open(pa, 'wb').write(a)
    k = ktest.KPC(pa, b=bq); k.start()
    sh = Shell(k); pc = k.pc
    sh.run('dir a:fill.bin')
    data = root + 7 * 512
    f0 = bytes(pc.drives[1].img[512:root]); x0 = bytes(pc.drives[1].img[data:data + 5 * 1024])
    o = sh.run('echo hi>> b:q.txt')
    check('B:Q.TXT starting past the disk\'s end, an append: refused, B:\'s FATs and X.TXT as they were (no stale '
          'entry of A:\'s followed)', bytes(pc.drives[1].img[512:root]) == f0
          and bytes(pc.drives[1].img[data:data + 5 * 1024]) == x0, o[-200:])
    # (A:'s FILL.BIN takes cluster 500h and on: the cache past B:'s FAT, A:'s entries, links them)
    k = ktest.KPC(image('mnt_oa.img', lcmd, mkf('FILL.BIN', b'f' * 1400 * 512)), b=bp); k.start()
    sh = Shell(k); pc = k.pc
    sh.run('dir a:fill.bin')
    o0 = sh.run('type b:sub\\k.txt')
    check('B:SUB\\K.TXT\'s chain leading past the disk\'s end, TYPE: its first cluster, then the end (no sector '
          'past the disk read)', 'Fail?' not in o0 and o0.count('k') >= 1024, o0[-200:])
    o = sh.run('del b:sub\\k.txt') + sh.run('dir b:')
    x = bytes(pc.drives[1].img)
    check('B:SUB\\K.TXT\'s chain leading past the disk\'s end, DEL: B:\'s root and the FATs past it as they were, '
          'M.TXT whole', x[root:root + 7 * 512] == b0[root:root + 7 * 512]
          and x[B['res'] * 512:(B['res'] + B['spf']) * 512] == x[(B['res'] + B['spf']) * 512:root]
          and safe_files(x).get('A:\\M.TXT') == b'm' * 3000,
          (o[-200:], fatcheck.check(x)[0][:4]))

def t_chg06():
    """The disk changed under a transfer (the BIOS's 06h: KDISK.INC rule 4, dio.st, chg_ask): CHG06 reads 30000
    bytes of B:BIG.TXT in one call, the disk swapped before its Nth INT 13h read of B: (read-ahead's, the cylinder
    cache's or a plain one's; with the cache in EMS too).  Another disk: "Invalid disk change" (INT 24h 0Fh) asked
    there and then, Fail: the read fails (34), nothing of the other disk's read as the file's, neither disk
    written; the first disk back and Retry: the read goes on, every byte the file's.  The same disk's change line
    alone: no question, the read whole.  A drive without a change line (AH=15h): a handle call looks at the disk
    only after ~2 s unused (MS-DOS's rule), so 128-byte reads don't read its boot sector each; a swap in such a
    pause is still seen."""
    def mkf(n, b):
        t = os.path.join(OUT, 'c6_' + n.replace('\\', '_')); open(t, 'wb').write(b); return n + '=' + t
    def probe(defs=()):
        c = os.path.join(OUT, 'CHG06' + ''.join('_' + d for d in defs) + '.COM')
        subprocess.run(['nasm', '-f', 'bin'] + ['-D' + d for d in defs] + ['-o', c, os.path.join(HERE, 'CHG06.ASM')],
                       check=True)
        return 'CHG06.COM=' + c
    lcmd = os.path.join(GOS, 'src', 'LCMD.COM')
    data1 = bytes(0x31 + i % 7 for i in range(40000))
    b1 = image('c6_b1.img', mkf('BIG.TXT', data1))
    b2 = bytearray(open(image('c6_b2.img', mkf('BIG.TXT', b'2' * 40000)), 'rb').read())
    b2[0x27:0x2B] = b'\x12\x34\x56\x78'; b2 = bytes(b2)            # (another serial: another boot sector)
    d1 = open(b1, 'rb').read()
    b3 = bytearray(open(image('c6_b3.img', mkf('PAD.TXT', b'p' * 3000), mkf('BIG.TXT', b'3' * 40000)), 'rb').read())
    b3[0:512] = d1[0:512]; b3 = bytes(b3)                           # (the same boot sector, another FAT)
    def run(k, n, swap, answer, ems_tag=''):
        """CHG06, the disk swapped before B:'s nth read (swap()), each question answered by answer(i) -> key"""
        pc = k.pc; orig = pc.int13; st = {'n': 0, 'spec': None}
        spec = k.Y['io_spec']
        def int13():
            if pc.r('ah') == 2 and pc.r('dl') == 1:
                st['n'] += 1
                if st['n'] == n:
                    st['spec'] = pc.rd(0x60, spec, 1)[0]; swap()
            return orig()
        pc.int13 = int13
        try:
            k.key('cls'); k.key(ktest.ENTER)
            n0 = len(pc.tty)
            k.key('chg06'); k.key(ktest.ENTER, settle=False)
            asked = 0
            while True:
                pc.run_until(lambda: ''.join(pc.tty)[n0 + 5:].count('[') > asked or '.' in ''.join(pc.tty)[n0 + 5:]
                             or pc.crash, 30)
                o = ''.join(pc.tty)[n0 + 5:]
                if o.count('[') <= asked: break
                pc.keys.append(ord(answer(asked))); asked += 1
                if asked > 4: break
            k.settle()
        finally:
            pc.int13 = orig
        return ''.join(pc.tty)[n0 + 5:], st
    kinds = set()
    for ems in (0, 88):
        tag = ' (EMS)' if ems else ''
        for other_img, what in ((b2, 'another serial'), (b3, 'the same boot sector, another FAT')):
            bad = []; seen = []
            for n in range(2, 9):
                k = ktest.KPC(image('c6_a.img', lcmd, probe()), b=b1, ems_pages=ems); k.start()
                sh = Shell(k); pc = k.pc
                first = pc.drives[1]; other = pcemu.Floppy(bytearray(other_img)); other.change_err = True
                def swap():
                    other.changed = True; pc.drives[1] = other
                o, st = run(k, n, swap, lambda i: 'f')
                kinds.add(st['spec'])
                out = fatcheck.read_files(bytes(pc.drives[0].img)).get('A:\\OUT.TXT')
                theirs = fatcheck.read_files(other_img)['A:\\BIG.TXT'][:30000]
                asked = o.count('[P]') == 1 and 'R+' not in o and out is None      # (the open's, or the read's: R-R)
                fresh = '[' not in o and out == theirs and st['n'] - n > 4         # (before anything but the boot
                if not ((asked or fresh) and bytes(other.img) == other_img          #  sector: that disk's file)
                        and bytes(first.img) == d1):
                    bad.append((n, o, st, None if out is None else len(out)))
                seen.append('R-R' in o)
            check('B: swapped for a disk with %s before B:\'s Nth read (N = 2-8), Fail at "Invalid disk change": '
                  'nothing of the file read with that disk\'s, nothing written, neither disk touched%s'
                  % (what, tag), not bad and any(seen), (bad[:2], seen))
        # the first disk back at the question, Retry: the read goes on, the file's bytes all
        bad = []
        for n in (2, 5, 8):
            k = ktest.KPC(image('c6_a.img', lcmd, probe()), b=b1, ems_pages=ems); k.start()
            sh = Shell(k); pc = k.pc
            first = pc.drives[1]; other = pcemu.Floppy(bytearray(b2)); other.change_err = True
            first.change_err = True
            def swap():
                other.changed = True; pc.drives[1] = other
            def back(i):
                if i == 0: first.changed = True; pc.drives[1] = first
                return 'r'
            o, st = run(k, n, swap, back)
            out = fatcheck.read_files(bytes(pc.drives[0].img)).get('A:\\OUT.TXT')
            if not (o.count('[P]') == 1 and 'R+' in o and out == data1[:30000] and bytes(other.img) == b2
                    and bytes(first.img) == d1):
                bad.append((n, o, st, None if out is None else len(out)))
        check('... the first disk put back at the question, Retry: the read goes on, all 30000 bytes the file\'s'
              + tag, not bad, bad[:2])
        # the change line alone (the same disk taken out and put back): no question, the file's bytes all
        bad = []
        for n in (2, 5, 8):
            k = ktest.KPC(image('c6_a.img', lcmd, probe()), b=b1, ems_pages=ems); k.start()
            sh = Shell(k); pc = k.pc; first = pc.drives[1]; first.change_err = True
            o, st = run(k, n, lambda: setattr(first, 'changed', True), lambda i: 'f')
            out = fatcheck.read_files(bytes(pc.drives[0].img)).get('A:\\OUT.TXT')
            if not ('[' not in o and 'R+' in o and out == data1[:30000]):
                bad.append((n, o, st))
        check('... the same disk\'s change line set under the read (06h): no question, all 30000 bytes the file\'s'
              + tag, not bad, bad[:2])
    check('... the 06h met in read-ahead (one try, no INT 24h) and in plain reads both', kinds == {0, 1}, kinds)
    # a drive without a change line: 128-byte reads of B:BIG.TXT (each a handle call) don't read its boot sector
    # each; after a pause of 3 s the next one looks, and sees the disk swapped meanwhile
    for wait in (False, True, 'zd'):
        k = ktest.KPC(image('c6_a.img', lcmd, probe(('SMALL', 'WAIT', 'ZD') if wait == 'zd' else ('SMALL', 'WAIT')
                                                   if wait else ('SMALL',))), b=b1)
        k.pc.drives[1].no_changeline = True; k.start()
        sh = Shell(k); pc = k.pc; first = pc.drives[1]
        orig = pc.int13; st = {'b0': 0}
        def int13():
            if pc.r('ah') == 2 and pc.r('dl') == 1 and pc.r('cx') == 1 and pc.r('dh') == 0:
                st['b0'] += 1
            return orig()
        pc.int13 = int13
        if not wait:
            o = sh.run('chg06')
            pc.int13 = orig
            out = fatcheck.read_files(bytes(pc.drives[0].img)).get('A:\\OUT.TXT')
            check('B: without a change line: 313 reads of 128 bytes, the boot sector read %d times (the open\'s, '
                  'and one each ~2 s at most), every byte right' % st['b0'], 'R+' in o and out == data1
                  and st['b0'] <= 4, (o[-100:], st))
        else:
            other = pcemu.Floppy(bytearray(b2)); other.no_changeline = True
            k.key('cls'); k.key(ktest.ENTER)
            n0 = len(pc.tty)
            k.key('chg06'); k.key(ktest.ENTER, settle=False)
            pc.run_until(lambda: 'a' in ''.join(pc.tty)[n0 + 5:] or pc.crash, 30)
            pc.drives[1] = other
            pc.run_until(lambda: '[' in ''.join(pc.tty)[n0 + 5:] or '.' in ''.join(pc.tty)[n0 + 5:] or pc.crash, 30)
            pc.keys.append(ord('f'))
            pc.run_until(lambda: '.' in ''.join(pc.tty)[n0 + 5:] or pc.crash, 30); k.settle()
            pc.int13 = orig
            o = ''.join(pc.tty)[n0 + 5:]
            check('... the disk swapped in a 3 s pause: the next 128-byte read looks, "Invalid disk change", Fail: '
                  'refused, the other disk untouched' if wait is True else '... INT 21h 0Dh, the disk swapped 0.3 s '
                  'before the next 128-byte read: a look due (D_CHK), so it looks despite the 2 s, "Invalid disk '
                  'change", Fail: refused', '[P]' in o and 'R-' in o and bytes(other.img) == b2, o[-100:])
    # INT 21h 0Dh (the root's sectors forgotten), then a CREATE on B:, the disk swapped under the root's read-ahead
    # (root_pre, whose errors are left to the reads after it): Fail at "Invalid disk change", and none of the
    # call's later transfers go to the disk in (dio: none to an unmounted floppy), so it is untouched
    z0d = os.path.join(OUT, 'Z0D.COM')
    open(os.path.join(OUT, 'Z0D.ASM'), 'w').write('org 100h\n mov ah, 0Dh\n int 21h\n mov ax, 4C00h\n int 21h\n')
    subprocess.run(['nasm', '-f', 'bin', '-o', z0d, os.path.join(OUT, 'Z0D.ASM')], check=True)
    many = [mkf('F%02d.TXT' % i, b'f' * 100) for i in range(20)]       # (a root past its first sector)
    z1 = image('c6_z1.img', *many); dz1 = open(z1, 'rb').read()
    z2 = bytearray(open(image('c6_z2.img', *many[:18]), 'rb').read()); z2[0x27:0x2B] = b'\x12\x34\x56\x78'
    z2 = bytes(z2)
    k = ktest.KPC(image('c6_z.img', lcmd, 'Z0D.COM=' + z0d), b=z1); k.start()
    sh = Shell(k); pc = k.pc
    first = pc.drives[1]; other = pcemu.Floppy(bytearray(z2)); other.change_err = True
    sh.run('dir b:'); sh.run('z0d')
    rp, st, orig = 0x600 + k.Y['root_pre'], {'arm': False, 'done': False}, pc.int13
    def at_rp(pc):
        if k.addr == rp and not st['done']: st['arm'] = True
    def int13():
        if st['arm'] and pc.r('ah') == 2 and pc.r('dl') == 1:
            st['arm'] = False; st['done'] = True; other.changed = True; pc.drives[1] = other
        return orig()
    k.hooks.append(at_rp); pc.int13 = int13
    k.key('cls'); k.key(ktest.ENTER)
    n0 = len(pc.tty)
    k.key('echo x>b:new.txt'); k.key(ktest.ENTER, settle=False)
    pc.run_until(lambda: 'Fail?' in ''.join(pc.tty)[n0:] or pc.crash, 20)
    k.key('f')
    pc.int13 = orig
    o = ''.join(pc.tty)[n0:]
    check('... 0Dh, then ECHO > B:NEW.TXT, another disk in under the root\'s read-ahead: "Invalid disk change" '
          'asked, Fail: nothing written to the disk in, nor to the first', st['done'] and 'Fail?' in o
          and bytes(other.img) == z2 and bytes(first.img) == dz1, (st, o[-200:]))

def t_mntback():
    """A floppy's mount after a Fail at "Invalid disk change" (KDISK.INC rules 4, 9): the disk that was let go
    put back before another is mounted keeps its mount number, so a file open on it reads (and writes) on, as
    MS-DOS's after a Fail with the volume back; another disk mounted between: its files refused (5).  A write
    failed so leaves the FAT cache nobody's and unchanged (fat_forget, fat_back): the next disk's FAT doesn't come
    in "changed".  A drive whose AH=15h says "no change line" but whose AH=16h says "not changed" has one
    (D_PRES 3 to 1).  Without a change line, the 2 s rule counts the BIOS's whole tick: an hour later is no
    "fresh" use."""
    def mkf(n, b):
        t = os.path.join(OUT, 'mb_' + n.replace('\\', '_')); open(t, 'wb').write(b); return n + '=' + t
    def probe(name, defs=()):
        c = os.path.join(OUT, name + ''.join('_' + d for d in defs) + '.COM')
        subprocess.run(['nasm', '-f', 'bin'] + ['-D' + d for d in defs] + ['-o', c, os.path.join(HERE, name + '.ASM')],
                       check=True)
        return name + '.COM=' + c
    lcmd = os.path.join(GOS, 'src', 'LCMD.COM')
    kdat = b'k' * 3000
    b1 = image('mb_b1.img', mkf('K.TXT', kdat))
    b2 = bytearray(open(image('mb_b2.img', mkf('OTH.TXT', b'o' * 100)), 'rb').read())
    b2[0x27:0x2B] = b'\x12\x34\x56\x78'; b2 = bytes(b2)                    # (another serial)
    d1 = open(b1, 'rb').read()
    def run(k, cmd, at_keys, nkeys):
        """cmd run; at its ith '?' (a key awaited) at_keys(i), then a key"""
        pc = k.pc
        k.key('cls'); k.key(ktest.ENTER)
        n0 = len(pc.tty)
        k.key(cmd); k.key(ktest.ENTER, settle=False)
        for i in range(nkeys):
            pc.run_until(lambda: ''.join(pc.tty)[n0 + len(cmd):].count('?') > i or pc.crash, 30)
            at_keys(i); pc.keys.append(ord(' '))
        pc.run_until(lambda: 'Z' in ''.join(pc.tty)[n0 + len(cmd):] or pc.crash, 30); k.settle()
        return ''.join(pc.tty)[n0 + len(cmd):]
    for defs, what in (((), 'read-only'), (('RW',), 'read and write')):
        for mid in (False, True):
            k = ktest.KPC(image('mb_a.img', lcmd, probe('MNTBK', defs + (('MID',) if mid else ()))), b=b1); k.start()
            Shell(k); pc = k.pc
            first = pc.drives[1]; other = pcemu.Floppy(bytearray(b2))
            def at(i):
                d = [other, other, first][i] if mid else [other, first][i]
                if pc.drives[1] is not d: d.changed = True; pc.drives[1] = d
            o = run(k, 'mntbk', at, 3 if mid else 2)
            f = fatcheck.read_files(bytes(first.img)).get('A:\\K.TXT')
            clean = bytes(other.img) == b2 and not fatcheck.check(bytes(first.img))[0]
            if not mid:
                ok = ('[P]R-5' in o and ('S+k' if not defs else 'S+') in o and 'Z+' in o and clean
                      and f == (kdat if not defs else b'AS' + kdat[2:]))
                check('B:K.TXT open (%s), another disk in, "Invalid disk change", Fail: that call fails (5); the '
                      'first disk back: the file %s on (S+), its close done%s, the other disk untouched'
                      % (what, 'reads' if not defs else 'is written', '' if not defs else ', K.TXT "AS" then the rest'),
                      ok, (o[-120:], None if f is None else f[:4]))
            else:
                ok = ('[P]R-5' in o and 'M+' in o and 'S-5' in o and ('Z+' if not defs else 'Z-5') in o and clean
                      and f == (kdat if not defs else b'A' + kdat[1:]))
                check('... (%s) the other disk mounted between (a search of B:): another mount, the file refused (S-5)%s'
                      % (what, '' if not defs else ', its close too (Z-5), K.TXT with A alone'), ok,
                      (o[-120:], None if f is None else f[:4]))
    # a write failed by "Invalid disk change" (the disk swapped under its first INT 13h write): the FAT cache
    # nobody's and unchanged after; then A: write-protected: a program run, a file read, DIR A:\ ask nothing
    for ems in (0, 88):
        nop = os.path.join(OUT, 'MBNOP.COM')
        open(os.path.join(OUT, 'MBNOP.ASM'), 'w').write('org 100h\n mov ax, 4C00h\n int 21h\n')
        subprocess.run(['nasm', '-f', 'bin', '-o', nop, os.path.join(OUT, 'MBNOP.ASM')], check=True)
        big = bytes((65 + i % 26) for i in range(20000))
        k = ktest.KPC(image('mb_w.img', lcmd, probe('WR06'), 'NOP.COM=' + nop, mkf('BIGA.TXT', big)), b=b1,
                      ems_pages=ems); k.start()
        sh = Shell(k); pc = k.pc
        first = pc.drives[1]; other = pcemu.Floppy(bytearray(b2)); other.change_err = True
        st = {'n40': 0, 'armed': False, 'wA': 0}
        def hook(pc):
            if k.addr == k.i21 and pc.r('ax') >> 8 == 0x40 and pc.r('bx') > 4:
                st['n40'] += 1
                if st['n40'] == 2: st['armed'] = True
        k.hooks.append(hook)
        orig = pc.int13
        def int13():
            if st['armed'] and pc.r('ah') == 3 and pc.r('dl') == 1:
                st['armed'] = False; other.changed = True; pc.drives[1] = other
            if pc.r('dl') == 0 and pc.r('ah') == 3: st['wA'] += 1
            return orig()
        pc.int13 = int13
        o = sh.run('wr06')
        kv = [pc.rd(0x60, k.Y[n], 1)[0] for n in ('fat_drv', 'fat_dirty', 'fk_dirty')] + \
             [pc.u16(0x60, k.Y[n]) for n in ('fat_dmask', 'fk_dmask')]
        pc.drives[0].wp = True
        o2 = ''.join(sh.run(c) for c in ('type biga.txt > nul', 'nop', 'dir a:\\'))
        pc.drives[0].wp = False
        check('X.DAT grown (4 KB), then 8 KB more with another disk in under its first write: "Invalid disk change", '
              'Fail; the FAT cache nobody\'s and unchanged after (FFh, 0, 0, 0, 0: %s); A: write-protected then: a '
              'file read, a program run, DIR A:\\ ask nothing, write nothing; the other disk untouched%s'
              % (kv, ' (EMS)' if ems else ''), '[P]2-' in o and kv == [0xFF, 0, 0, 0, 0] and 'Write protect' not in o2
              and 'Fail?' not in o2 and st['wA'] == 0 and bytes(other.img) == b2 and 'BIGA     TXT' in o2,
              (o[-80:], kv, o2[-300:], st))
    # AH=15h says "no change line" (1), AH=16h works: D_PRES 3 at start, 1 at its first "not changed"; a drive
    # that has none (16h: "changed" every time) keeps 3
    for real in (False, True):
        k = ktest.KPC(image('mb_a.img', lcmd), b=b1)
        pc = k.pc
        if real:
            pc.drives[1].no_changeline = True
        else:
            orig15 = pc.int13
            def int13(orig15=orig15):
                if pc.r('ah') == 0x15 and pc.r('dl') == 1:
                    pc.w('ax', 0x0100); pc.cf(0); return
                return orig15()
            pc.int13 = int13
        k.start(); sh = Shell(k)
        dp = lambda: pc.rd(0x60, k.Y['drvtab'] + 32 + 27, 1)[0]
        p0 = dp(); sh.run('dir b:'); sh.run('dir b:'); p1 = dp()
        check('B:: AH=15h "no change line", %s: D_PRES %d, then %d after two DIR B:' %
              ('AH=16h "changed" every time (none)' if real else 'AH=16h "not changed" (it has one)', p0, p1),
              p0 == 3 and p1 == (3 if real else 1), (p0, p1))
    # without a change line: the next use an hour and 5 ticks after the last (the BIOS tick's low word 5 more)
    # isn't "fresh": it looks, sees the other disk, "Invalid disk change"
    for hour in (False, True):
        k = ktest.KPC(image('mb_a.img', lcmd, probe('MNTBK')), b=b1)
        pc = k.pc; pc.drives[1].no_changeline = True; k.start()
        Shell(k)
        first = pc.drives[1]; other = pcemu.Floppy(bytearray(b2)); other.no_changeline = True
        def at(i):
            if i == 0:
                if hour:
                    t = struct.unpack('<I', pc.rd(0, 0x46C, 4))[0]
                    pc.wr(0, 0x46C, struct.pack('<I', t + 0x10000))
                pc.drives[1] = other
            else:
                pc.drives[1] = first
        o = run(k, 'mntbk', at, 2)
        if hour:
            check('B: without a change line, another disk in, the BIOS tick an hour (65536 ticks) on: the read looks, '
                  '"Invalid disk change" (R-5), the first back: S+', '[P]R-5' in o and 'S+k' in o
                  and bytes(other.img) == b2, o[-120:])
        else:
            check('... (the same at once, under 2 s: no look, no question: the rule as MS-DOS\'s)',
                  '[' not in o and 'R+' in o, o[-120:])

def t_swaps():
    """Disks swapped around a file's calls (SWAPS.COM; KDISK.INC rules 1, 4, 9).  After "Invalid disk change" and
    Fail, the close and the commit of a changed file fail (CF, 5: a handle call's code), and COPY says so; the last
    close of a changed file is asked about with another disk in (it counts as open till its entry is written), and
    Retry with the disk back writes it.  A disk with the same boot sector but another FAT doesn't get the old
    mount back after INT 21h 0Dh, nor after 0Dh with a file open and no Fail; an empty drive while the old disk is
    looked for is "Not ready" (Retry with it back: the file reads on; Fail: the same, at the next call).  The disk
    changed on another machine with its FAT's first sector as it was is told apart by its root's first sector, also
    after a write of it that failed.  INT 21h F008h takes a sector the program wrote itself only if what it read is the
    kernel's disk and only a boot sector's label changed (a boot sector's label never makes another disk), and then
    knows the disk by what was written; either way the drive is looked at at its next access; with nothing open on
    it, the disk is just forgotten.  A floppy's changed FAT is written, from another drive's call, only after its
    drive is looked at; a look that can't read the disk keeps the changes (the call fails).  A root write that lands
    but is reported failed, read back by the kernel: that sector the disk's.  A create's entry Ignored: no nameless
    entry at the close.  Without a change line (from boot), within 2 s nothing is looked at (MS-DOS's rule)."""
    def mkf(n, b):
        t = os.path.join(OUT, 'sw_' + n.replace('\\', '_')); open(t, 'wb').write(b); return n + '=' + t
    c = os.path.join(OUT, 'SWAPS.COM')
    subprocess.run(['nasm', '-f', 'bin', '-o', c, os.path.join(HERE, 'SWAPS.ASM')], check=True)
    lcmd = os.path.join(GOS, 'src', 'LCMD.COM')
    kk = b'k' * 3000
    b1 = image('sw_b1.img', mkf('K.TXT', kk), mkf('L.TXT', b'l' * 3000), mkf('PAD.TXT', b'p' * 700))
    d1 = open(b1, 'rb').read()
    d2 = bytearray(open(image('sw_b2.img', mkf('OTH.TXT', b'o' * 3000), mkf('K.TXT', b'K2' * 2000)), 'rb').read())
    d2[0x27:0x2B] = b'\x12\x34\x56\x78'; d2 = bytes(d2)                    # (another serial)
    d4 = bytearray(open(image('sw_b4.img', mkf('BIG.TXT', b'B' * 9000), mkf('Q.TXT', b'q' * 100)), 'rb').read())
    d4[0:512] = d1[0:512]; d4 = bytes(d4)                                  # (the same boot sector, another FAT)
    d5 = bytearray(d1); i = d5.find(b'K       TXT', 19 * 512)               # disk 1 changed elsewhere: K.TXT's
    d5[i:i + 11] = b'Q       TXT'; d5[i + 28:i + 32] = struct.pack('<I', 10); d5 = bytes(d5)     # slot a small Q.TXT
    p8 = os.path.join(OUT, 'sw_b8.img')                                    # another layout: 4-sector clusters,
    if os.path.exists(p8): os.remove(p8)                                   #  7 root sectors
    subprocess.run(['mformat', '-C', '-f', '1440', '-c', '4', '-r', '7', '-v', 'LODESTONE', '-i', p8, '::'], check=True)
    subprocess.run(['mcopy', '-i', p8, mkf('EIGHT.TXT', b'8' * 9000).split('=')[1], '::EIGHT.TXT'], check=True)
    d8 = open(p8, 'rb').read()
    d6 = bytearray(d1); d6[0x2B:0x36] = b'ELSEWHERE  '; d6 = bytes(d6)        # disk 1 labelled on another machine
    last = {}
    def run(script, a24='', ce=False, nocl=False, cd=None):
        k = ktest.KPC(image('sw_a.img', lcmd, 'SWAPS.COM=' + c, 'SUB\\', mkf('SUB\\S.TXT', b's' * 10)), b=b1)
        k.pc.drives[1].no_changeline = nocl                                # (from boot: D_PRES 3, AH=15h's)
        k.start(); Shell(k); pc = k.pc; last['k'] = k
        if cd: k.key('cd ' + cd); k.key(ktest.ENTER)
        um = 0x600 + k.Y['unmount']; last['um'] = []
        D = {'1': pc.drives[1], '2': pcemu.Floppy(bytearray(d2)), '3': pcemu.Floppy(bytearray(d1)),
             '4': pcemu.Floppy(bytearray(d4)), '5': pcemu.Floppy(bytearray(d5)), '8': pcemu.Floppy(bytearray(d8)),
             '6': pcemu.Floppy(bytearray(d6))}
        for f in D.values(): f.change_err = ce; f.no_changeline = nocl
        st = {'n24': 0}
        def put(ch):
            if ch == '.': return
            if ch == 'L': st['land'] = 1; return                         # the next root write lands, fails (20h)
            if ch == 'Z': pc.drives[1].changed = False; return          # the change line cleared
            if ch == 'E':
                pc.drives[1].empty = True; pc.drives[1].changed = True; return
            if ch in 'PU':                                              # the write-protect tab on, off
                pc.drives[1].wp = ch == 'P'; return
            if ch == 'T':                                               # 3 s later (the BIOS's ticks)
                pc.wr(0, 0x46C, struct.pack('<H', (pc.u16(0, 0x46C) + 55) & 0xFFFF)); return
            for f in D.values(): f.empty = False
            D[ch].changed = True; pc.drives[1] = D[ch]
        def hook(pc):
            if k.addr == um: last['um'].append(pc.r('al'))
            if k.addr == k.i21 and pc.r('ah') == 0x30 and pc.r('bx') == 0x5A5A:
                if chr(pc.r('cl')) in D or chr(pc.r('cl')) in 'EPUTLZ': put(chr(pc.r('cl')))
            a = pc.u16(0, 0x24 * 4) + pc.u16(0, 0x24 * 4 + 2) * 16
            if k.addr == a and k.addr != k.i21:
                st['land'] = 0
                if st['n24'] < len(a24): put(a24[st['n24']])
                st['n24'] += 1
        k.hooks.append(hook)
        o13 = pc.int13
        def i13():                                  # 'L': a root write that lands but is reported failed
            if st.get('land') and pc.r('ah') == 3 and pc.r('dl') == 1:
                cx, dx = pc.r('cx'), pc.r('dx'); lba = ((cx >> 8) * 2 + (dx >> 8)) * 18 + (cx & 63) - 1
                if lba <= 19 < lba + pc.r('al'):
                    r = o13(); pc.w('ax', 0x2000); pc.cf(1); return r
            return o13()
        pc.int13 = i13
        k.key('cls'); k.key(ktest.ENTER); n0 = len(pc.tty)
        k.key('\\swaps ' + script); k.key(ktest.ENTER, settle=False)
        pc.run_until(lambda: ''.join(pc.tty)[n0:].count('>') >= 2 or pc.crash, 60); k.settle()
        o = ''.join(pc.tty)[n0 + len(script) + 8:]
        return o, {n: bytes(f.img) for n, f in D.items()}
    def sane(img):
        return not [p for p in fatcheck.check(img)[0] if 'lost clusters' not in p]
    o, im = run('oew2cv1')
    check('B:K.TXT grown 600 bytes, another disk in: its close asked about ("Invalid disk change"), Fail: the close '
          'fails, CF, 5 (59h: 5); the other disk untouched; K.TXT as it was', 'c[0F1B]-0005' in o and 'v+0005' in o
          and im['2'] == d2 and fatcheck.read_files(im['1']).get('A:\\K.TXT') == kk and sane(im['1']), o)
    o, im = run('oew2mv1c')
    check('... its commit (68h) instead: fails, CF, 5; the first disk back: the close goes (its changes were the '
          'cache\'s, dropped); K.TXT as it was, the disk consistent', 'm[0F1B]-0005' in o and ' 1 c+' in o
          and im['2'] == d2 and fatcheck.read_files(im['1']).get('A:\\K.TXT') == kk and sane(im['1']), o)
    o, im = run('oewa2cv1')
    probs = fatcheck.check(im['1'])[0]
    check('... B:\'s FAT written first (A:\'s loaded): nothing of the file dropped with the cache, its close fails all '
          'the same (CF, 5); the first disk back: K.TXT as it was (its chain longer than its size: the entry wasn\'t '
          'written, rule 2)', 'c[0F1B]-0005 v+0005' in o and im['2'] == d2
          and fatcheck.read_files(im['1']).get('A:\\K.TXT') == kk and all('chain has' in p for p in probs), (o, probs))
    o, im = run('oewa2c/1', '1')
    f = fatcheck.read_files(im['1']).get('A:\\K.TXT')
    check('B:K.TXT grown, B:\'s FAT written (A:\'s loaded), another disk in, the last close: asked ("Invalid disk '
          'change"), the first disk put back, Retry: the close done, K.TXT 3,600 bytes, the disk consistent',
          'c[0F1B]+' in o and f is not None and len(f) == 3600 and f[:3000] == kk and sane(im['1']) and im['2'] == d2,
          (o, None if f is None else len(f)))
    o, im = run('or2rd4rwc')
    check('B:K.TXT open, another disk in, Fail, INT 21h 0Dh, a disk with K\'s boot sector but another FAT in: '
          'another mount, the file refused (r-0005, w-0005), that disk untouched', 'd+0D00 4 r-0005 w-0005' in o
          and im['4'] == d4 and im['2'] == d2, o)
    o, im = run('ord4rwc')
    check('B:K.TXT open (no Fail), INT 21h 0Dh, that disk in: the sum kept with a file open, "Invalid disk change" '
          '(r[0F1B]-0005), the file refused after the Fail, that disk untouched',
          '4 r[0F1B]-0005 w-0005' in o and im['4'] == d4, o)
    o, im = run('or2r5rwc')
    check('B:K.TXT open, another disk in, Fail, then K\'s disk as changed on another machine (K.TXT\'s slot a '
          'small Q.TXT, FAT sector 0 as it was): its root\'s first sector differs, another mount, the file refused '
          '(r-0005, w-0005), Q.TXT not written over', '5 r-0005 w-0005' in o and im['5'] == d5, o)
    o, im = run('o5rwc')
    check('... with no Fail before: "Invalid disk change" (r[0F1B]-0005), that disk untouched',
          '5 r[0F1B]-0005 w-0005' in o and im['5'] == d5, o)
    o, im = run('or2r3rwc')
    check('... a DISKCOPY of the disk instead: the same disk (nothing tells it apart), the file reads and is '
          'written on', '3 r+0001 w+0258 c+' in o and im['2'] == d2, o)
    o, im = run('or2rErr1rwc/31', '.1')
    check('B:K.TXT open, another disk in, Fail, then the drive empty: "Not ready" as the old disk is looked for '
          '(r[021A]); the first disk put in, Retry: the file reads on (r+), and is written', 'E r[021A]+0001 r+0001'
          in o and ' 1 r+0001 w+0258 c+' in o and im['2'] == d2, o)
    o, im = run('or2rEr1rwc')
    check('... Fail at "Not ready": that call fails (5); the first disk back: the file reads on (r+)',
          'E r[021A]-0005 1 r+0001 w+0258 c+' in o and im['2'] == d2, o)
    o, im = run('or2rErwc/31', '.2')
    check('... the drive empty at that look, another disk put in, Retry: that disk is another disk (its own mount '
          'number, the old files refused: r-0005, w-0005), not written', 'E r[021A]-0005 w-0005' in o
          and im['2'] == d2, o)
    o, im = run('or2rEreewc/311', '.5')
    check('... K\'s disk as changed on another machine put in at "Not ready", Retry: refused (w-0005), Q.TXT in '
          'K\'s slot not written over', 'E r[021A]-0005 e+0BB8 e+0BB8 w-0005' in o and im['5'] == d5, o)
    def opn(k):                                     # files of B: still counted as open (not devices)
        sa = k.Y['sft']
        return [i for i in range(24) if k.pc.rd(0x60, sa + 44 * i, 44)[0] and not k.pc.rd(0x60, sa + 44 * i, 44)[2] & 0x80]
    o, im = run('oew2c/2')
    check('B:K.TXT grown, another disk in, its close asked about, Abort: the program ends, its handle closed by '
          'terminate (the SFT free again, not left in use), K.TXT as it was', 'c[0F1B]' in o
          and not opn(last['k']) and fatcheck.read_files(im['1']).get('A:\\K.TXT') == kk and sane(im['1']),
          (o, opn(last['k'])))
    o, im = run('oewdXxdrc/1')
    f = fatcheck.read_files(im['1'])
    check('B:K.TXT open and grown, 0Dh, the root\'s first sector rewritten by the program through INT 13h (L.TXT '
          'renamed M.TXT), INT 21h F008h with it as read and as written: taken (x+), 0Dh: the same disk, the file '
          'reads on and closes (K.TXT 3,600 bytes, M.TXT kept), nothing asked', '[' not in o and 'x+' in o
          and 'r+' in o and 'c+' in o and f.get('A:\\K.TXT', b'')[:3000] == kk
          and len(f.get('A:\\K.TXT', b'')) == 3600 and 'A:\\M.TXT' in f and sane(im['1']), (o, sorted(f)))
    o, im = run('oewdYxdrc/1')
    f = fatcheck.read_files(im['1'])
    check('... the boot sector\'s label changed that way instead (as LABEL does), F008h: the same disk, K.TXT '
          '3,600 bytes, nothing asked', '[' not in o and 'x+' in o and 'c+' in o
          and len(f.get('A:\\K.TXT', b'')) == 3600 and im['1'][0x2B:0x36] == b'NEWLAB     ' and sane(im['1']),
          (o, len(f.get('A:\\K.TXT', b''))))
    o, im = run('oewX5xrwc/33')
    check('... the root written, then K\'s disk as changed on another machine put in before F008h: taken as '
          'written (x+), and so the disk in is another disk at the next look ("Invalid disk change"), Fail: the '
          'file refused, that disk untouched', 'x+' in o and 'r[0F1B]-0005 w-0005' in o and im['5'] == d5, o)
    o, im = run('oewX5xrwc/1', '1')
    f = fatcheck.read_files(im['1'])
    check('... the first disk put back at the question, Retry: the same disk (as written), the file written on, '
          'K.TXT 4,200 bytes, M.TXT there, the disk consistent', 'r[0F1B]+' in o and 'w+0258 c+' in o
          and len(f.get('A:\\K.TXT', b'')) == 4200 and 'A:\\M.TXT' in f and sane(im['1']) and im['5'] == d5,
          (o, len(f.get('A:\\K.TXT', b''))))
    for sc, ce, nocl, why in (('oew5kxwc/3', False, False, 'K\'s disk as changed on another machine put in, the '
                               'program\'s own INT 13h read of its root, F008h with that'),
                              ('oew4kxwc/3', False, False, '... a disk with K\'s boot sector and another FAT'),
                              ('oew5kxdwc/33', False, False, '... then 0Dh (LABEL\'s order: its flush looks at the '
                               'disk, asked there)'),
                              ('oew5kxwc/3', True, False, '... with an AT BIOS\'s 06h (the program\'s read cleared '
                               'the change line: the look F008h leaves due)'),
                              ('oew5kxdwc/33', True, False, '... and then 0Dh'),
                              ('oew5kxwc/3', False, True, '... a drive without a change line (D_PRES 3 from boot), '
                               'within its 2 s'),
                              ('oewEx5wc/3', False, False, 'the drive empty, F008h with nothing read (zeros as its '
                               'boot sector)')):
        o, im = run(sc, '', ce, nocl)
        check(why + ': refused (x-0005: what was read isn\'t the kernel\'s disk), nothing taken; the next call '
              'asked about ("Invalid disk change"), Fail: the write refused, that disk untouched', 'x-0005' in o
              and ('w[0F1B]-0005' in o or '[0F1B]' in o and 'w-0005' in o) and im['5'] == d5 and im['4'] == d4, o)
    o, im = run('oewX5xrwc/33', '', True)
    check('the root written, K\'s disk as changed elsewhere put in, F008h, with an AT BIOS\'s 06h: nothing read '
          'by F008h (taken as written), the next look asks ("Invalid disk change"), Fail: refused, that disk '
          'untouched', 'x+' in o and 'r[0F1B]-0005 w-0005' in o and im['5'] == d5, o)
    o, im = run('ocd8Yxnwc')
    f = fatcheck.read_files(im['8'])
    check('nothing open, 0Dh, a disk of another layout in (1.44 MB, 4-sector clusters, 7 root sectors), its label '
          'written by the program and F008h: taken (nothing open, nothing to go: the drive unmounted, the disk in '
          'taken as it is at the next access); B:N.TXT then made on that disk as its own layout has it (the disk '
          'consistent)', 'x+' in o and 'n+' in o
          and 'c+' in o and len(f.get('A:\\N.TXT', b'')) == 600 and sane(im['8']), (o, sorted(f)))
    o, im = run('oew6Yxwc/3')
    f = fatcheck.read_files(im['6'])
    check('K\'s disk as labelled on another machine put in (its boot sector\'s label alone differs: the same disk, '
          'the root\'s label is the one that counts), the program\'s own label written there, F008h: taken, the '
          'file written on there (K.TXT 4,200 bytes), nothing asked', '[' not in o and 'x+' in o and 'w+0258 c+' in o
          and len(f.get('A:\\K.TXT', b'')) == 4200 and sane(im['6']), (o, len(f.get('A:\\K.TXT', b''))))
    o, im = run('oew5Yxdwc/1', '1')
    f = fatcheck.read_files(im['1'])
    check('K\'s disk as changed on another machine put in (the same boot sector, another root), its label written '
          'by the program and F008h: taken (only the label changed), the look it leaves due finds another disk '
          '(0Dh: "Invalid disk change"); the first disk put back, Retry: the same disk (its boot sector\'s label '
          'aside), the file written on: K.TXT 4,200 bytes, that disk only the program\'s sector written',
          'x+' in o and 'd[0F1B]+' in o and 'w+0258 c+' in o and len(f.get('A:\\K.TXT', b'')) == 4200
          and sane(im['1']) and im['5'][512:] == d5[512:], (o, len(f.get('A:\\K.TXT', b''))))
    o, im = run('oew5YxZdwc/3')
    check('... the change line cleared after F008h: the look it left due all the same (0Dh asked), Fail: the write '
          'refused, that disk only the program\'s sector written', 'x+' in o and 'd[0F1B]' in o and 'w-0005' in o
          and im['5'][512:] == d5[512:], o)
    o, im = run('oGxrc')
    check('F008h with more than the boot sector\'s label changed (its sectors a track): refused, the file reads '
          'on', 'x-0005 r+0001 c+' in o, o)
    o, im = run('oewPnU5wc/3333')
    check('B:K.TXT grown, B: write-protected, a create\'s root write answered Fail, the tab off, K\'s disk as '
          'changed on another machine in: another disk (the root\'s sum kept at the Fail: the disk has the old '
          'sector), "Invalid disk change", the write refused, that disk untouched', '5 w[0F1B]-0005' in o
          and im['5'] == d5, o)
    for sc, nocl, ce, why in (('oew2awc/3', False, False, ''), ('oew2Tawc/3', True, False, ', a drive without a change '
                              'line (D_PRES 3 from boot), 3 s after its last use'),
                              ('oew2awc/3', False, True, ', an AT BIOS\'s 06h')):
        o, im = run(sc, '', ce, nocl)
        check('B:K.TXT grown (B:\'s FAT changed), another disk in, an A: call (36h, A:\'s FAT loaded)%s: B: looked '
              'at first, "Invalid disk change", Fail: B:\'s changes dropped, the A: call done; the write refused, '
              'the other disk untouched' % why, 'a[0F1B]+' in o and 'w-0005' in o and im['2'] == d2, o)
    o, im = run('oew2awc/3', '', False, True)
    check('... a drive without a change line, within 2 s of its last use: not looked at (MS-DOS\'s rule, KDISK.INC '
          'rule 9): B:\'s FAT written to the disk in, nothing asked', '2 a+' in o and '[' not in o and im['2'] != d2, o)
    o, im = run('oewEa1wc/3333')
    f = fatcheck.read_files(im['1'])
    check('B:K.TXT grown, the drive emptied, an A: call (A:\'s FAT loaded): B: looked at first, "Not ready" as a '
          'write\'s (its FAT\'s: [021B]), the user\'s Fail: B:\'s changes given up (as MS-DOS\'s buffer whose write '
          'fails), the A: call done; the disk back: the file refused (w-0005, c-0005), K.TXT as it was, the disk '
          'consistent', 'E a[021B]+' in o and ' 1 w-0005 c-0005' in o
          and f.get('A:\\K.TXT') == kk and sane(im['1']), (o, len(f.get('A:\\K.TXT', b''))))
    for sc, a24, nocl, why in (('oewEa1wc/a333', '', False, 'a Fail nobody was asked for (83h: the Executive\'s, '
                                'a task\'s behind a graphics screen): B:\'s changes kept (rule 3), the A: call fails'),
                               ('oewEa1wc/1', '1', False, 'the disk put back at the question, Retry: B:\'s FAT '
                                'written there, the A: call done'),
                               ('oewEa1wc/3333', '', True, 'a drive without a change line, within 2 s: written blind, '
                                'the write failing, Fail: kept (rule 3), the A: call fails')):
        o, im = run(sc, a24, False, nocl)
        f = fatcheck.read_files(im['1'])
        check('... %s; the file written on after, K.TXT 4,200 bytes, the disk consistent' % why,
              ('E a[021B]' in o or 'E a[023F]-' in o) and ' 1 w+0258 c+' in o
              and len(f.get('A:\\K.TXT', b'')) == 4200 and sane(im['1']), (o, len(f.get('A:\\K.TXT', b''))))
    o, im = run('oew2a1wc/a')
    f = fatcheck.read_files(im['1'])
    check('B:K.TXT grown, another disk in, an A: call: "Invalid disk change", a Fail nobody was asked for (a text '
          'task in front of the Executive): nothing dropped, the A: call fails; the first disk back: the file '
          'written on (K.TXT 4,200 bytes), the other disk untouched', 'a[0F1B]-' in o and ' 1 w+0258 c+' in o
          and len(f.get('A:\\K.TXT', b'')) == 4200 and sane(im['1']) and im['2'] == d2,
          (o, len(f.get('A:\\K.TXT', b''))))
    o, im = run('doewEa1wc/a', cd='\\sub')
    check('A:\\SUB current, INT 21h 0Dh (its directory to be found again), B:K.TXT grown, B: emptied, an A: call: '
          'A:\'s FAT can\'t come in (B:\'s kept, nobody asked): the call fails, A:\'s directory kept by name, not '
          'taken for the root; B:\'s disk back: found again (the prompt A:\\SUB>)', 'E a[021B]-' in o
          and 'A:\\SUB>' in o, o)
    o, im = run('oewYxwc')
    check('B:K.TXT open and grown, its boot sector\'s label written by the program and F008h: taken, the disk '
          'still mounted (no unmount, nothing dropped), the file written on', 'x+' in o and 'w+0258 c+' in o
          and last['um'] == [], (o, last['um']))
    o, im = run('oewLnTTPnU1wc/3333')
    f = fatcheck.read_files(im['1'])
    check('B:K.TXT grown, a create whose root write lands but is reported failed (the root\'s new sector kept as the '
          'one the disk may have), the kernel\'s own read of it (that one kept now), another create\'s root write '
          'refused by a write-protected disk, the tab off: the disk is the same disk, the file written on (K.TXT '
          '4,200 bytes)', 'U 1 w+0258 c+' in o and len(f.get('A:\\K.TXT', b'')) == 4200 and sane(im['1']),
          (o, len(f.get('A:\\K.TXT', b''))))
    o, im = run('oew2a1wc/1', '1')
    f = fatcheck.read_files(im['1'])
    check('... the first disk put back at the question, Retry: B:\'s FAT written there, the A: call done, the '
          'file written on: K.TXT 4,200 bytes, the disk consistent, the other untouched', 'a[0F1B]+' in o
          and 'w+0258 c+' in o and len(f.get('A:\\K.TXT', b'')) == 4200 and sane(im['1']) and im['2'] == d2,
          (o, len(f.get('A:\\K.TXT', b''))))
    o, im = run('PnwU21rc/000')
    check('B: write-protected, B:N.TXT created and written, each INT 24h answered Ignore, the tab off, another disk '
          'and the same one back: still the same disk (the root\'s sum forgotten at the write Ignored, not kept '
          'as the cache had it): the file reads on (r+), closes', 'U 2 1 r+0000 c+' in o and im['2'] == d2, o)
    ents = [im['1'][19 * 512 + 32 * j:19 * 512 + 32 * j + 32] for j in range(16)]
    check('... its entry, never written (Ignored), not made a nameless one at the close (no entry with a 00h first '
          'byte and a chain); the disk consistent but for lost clusters', not [e for e in ents if e[0] == 0 and e[26:32]
          != b'\0' * 6] and sane(im['1']), [e.hex() for e in ents[:6]])
    # COPY's destination's close with another disk in: Write error, 0 copied
    k = ktest.KPC(image('sw_c.img', lcmd), b=b1); k.start()
    sh = Shell(k); pc = k.pc; other = pcemu.Floppy(bytearray(d2))
    st = {'sw': False}
    def hook(pc):
        if k.addr == k.i21 and pc.r('ah') == 0x3E and pc.r('bx') > 4 and not st['sw']:
            st['sw'] = True; other.changed = True; pc.drives[1] = other
    k.hooks.append(hook)
    k.key('cls'); k.key(ktest.ENTER); n0 = len(pc.tty)
    k.key('copy a:lcmd.com b:new.dat'); k.key(ktest.ENTER, settle=False)
    pc.run_until(lambda: 'Fail?' in ''.join(pc.tty)[n0:] or pc.crash, 30)
    pc.keys.append(ord('f'))
    pc.run_until(lambda: 'copied' in ''.join(pc.tty)[n0:] or pc.crash, 30); k.settle()
    o = ''.join(pc.tty)[n0:]
    check('COPY A:LCMD.COM B:NEW.DAT, another disk in B: at its close: "Invalid disk change", Fail: "Write error", '
          '0 File(s) copied, the other disk untouched', 'Invalid disk change' in o and 'Write error' in o
          and '0 File(s) copied' in o and bytes(other.img) == d2, o[-200:])
    # a create's entry dropped by the disk (Ignored), its slot another file's since: left alone at the close
    rc = os.path.join(OUT, 'REUSE.COM')
    subprocess.run(['nasm', '-f', 'bin', '-o', rc, os.path.join(HERE, 'REUSE.ASM')], check=True)
    zf = mkf('Z.TXT', b'z' * 10).split('=')[1]
    k = ktest.KPC(image('sw_r.img', lcmd, 'REUSE.COM=' + rc, 'SUB\\', *['SUB\\Z%02d.TXT=%s' % (i, zf)
                  for i in range(40)]), b=image('sw_rb.img', mkf('K.TXT', kk)))
    k.start(); Shell(k); pc = k.pc; st = {'drop': False}
    def hook(pc):
        if k.addr == k.i21 and pc.r('ah') == 0x30 and pc.r('bx') == 0x5A5A: st['drop'] = chr(pc.r('cl')) == 'V'
    k.hooks.append(hook)
    o13 = pc.int13
    def i13():                                      # the root's writes dropped (sector not found) while 'V'
        if st['drop'] and pc.r('ah') == 3 and pc.r('dl') == 1:
            cx, dx = pc.r('cx'), pc.r('dx'); lba = ((cx >> 8) * 2 + (dx >> 8)) * 18 + (cx & 63) - 1
            if lba <= 19 < lba + pc.r('al'): pc.w('ax', 0x0400); pc.cf(1); return
        return o13()
    pc.int13 = i13
    k.key('cls'); k.key(ktest.ENTER); n0 = len(pc.tty)
    k.key('reuse'); k.key(ktest.ENTER); k.settle()
    o = ''.join(pc.tty)[n0:]; im = bytes(pc.drives[1].img); f = fatcheck.read_files(im)
    check('B:N.TXT created, its entry\'s write dropped by the disk and Ignored, the buffer gone; B:X.TXT made in '
          'that slot (free on the disk), written, closed; N then written and closed: X.TXT\'s entry left alone '
          '(not N\'s name there: 100 bytes of X), N\'s chain lost clusters, K.TXT whole',
          f.get('A:\\X.TXT') == b'X' * 100 and f.get('A:\\K.TXT') == kk and sane(im), (o, sorted(f)))

def t_cwdfind():
    """A floppy's current directory after another disk (KDISK.INC rule 1, cwd_find): B:\\SUB current, INT 21h 0Dh
    (or not), then a copy of the disk's boot sector with no SUB, a file over SUB's cluster: a relative create goes
    to the new disk's root (its D_CWD 0 too, not the old SUB's cluster), the file over it whole.  The first look
    after 0Dh failing (Fail at "reading drive B"): the directory still found again at the next (D_CHK 2, not 3)."""
    def mkf(n, b):
        t = os.path.join(OUT, 'cf_' + n.replace('\\', '_')); open(t, 'wb').write(b); return n + '=' + t
    lcmd = os.path.join(GOS, 'src', 'LCMD.COM')
    z0d = os.path.join(OUT, 'Z0D.COM')
    open(os.path.join(OUT, 'Z0D.ASM'), 'w').write('org 100h\n mov ah, 0Dh\n int 21h\n mov ax, 4C00h\n int 21h\n')
    subprocess.run(['nasm', '-f', 'bin', '-o', z0d, os.path.join(OUT, 'Z0D.ASM')], check=True)
    b1 = image('cf_b1.img', 'SUB\\', mkf('SUB\\A.TXT', b'a' * 100), mkf('K.TXT', b'k' * 100))
    d1 = open(b1, 'rb').read()
    d2 = bytearray(open(image('cf_b2.img', mkf('PAD.TXT', b''), mkf('BIG.TXT', (b'B' * 480 + b'\0' * 32) * 39)),
                        'rb').read())
    d2[0:512] = d1[0:512]; d2 = bytes(d2)
    big = fatcheck.read_files(d2)['A:\\BIG.TXT']
    for z in (True, False):
        k = ktest.KPC(image('cf_a.img', lcmd, 'Z0D.COM=' + z0d), b=b1); k.start()
        sh = Shell(k); pc = k.pc
        sh.run('b:'); sh.run('cd sub'); sh.run('dir')
        if z: sh.run('a:z0d')
        other = pcemu.Floppy(bytearray(d2)); other.changed = True; pc.drives[1] = other
        o = sh.run('echo hello>new.txt') + sh.run('cd')
        f = fatcheck.read_files(bytes(other.img)); probs = fatcheck.check(bytes(other.img))[0]
        check('B:\\SUB current,%s a copy of the boot sector with no SUB put in: ECHO > NEW.TXT goes to its root, '
              'B:\\ the current directory, BIG.TXT (over SUB\'s cluster) whole'
              % (' INT 21h 0Dh,' if z else ''), f.get('A:\\NEW.TXT') == b'hello\r\n' and f.get('A:\\BIG.TXT') == big
              and not probs and o.rstrip().endswith('B:\\\nB:\\>'), (o[-80:], probs))
    # finding the directory again after 0Dh, the first look failing: D_CHK 2 again (cwd_find at the next)
    k = ktest.KPC(image('cf_a.img', lcmd, 'Z0D.COM=' + z0d), b=b1); k.start()
    sh = Shell(k); pc = k.pc
    sh.run('b:'); sh.run('cd sub'); sh.run('a:z0d')
    pc.drives[1].bad = {0}
    k.key('cls'); k.key(ktest.ENTER)
    n0 = len(pc.tty)
    k.key('dir'); k.key(ktest.ENTER, settle=False)
    pc.run_until(lambda: 'Fail?' in ''.join(pc.tty)[n0:] or pc.crash, 20)
    seen = []; dr = 0x600 + k.Y['drv_ready']
    k.hooks.append(lambda pc: seen.append(pc.rd(0x60, k.Y['drvtab'] + 32 + 31, 1)[0])
                   if k.addr == dr and pc.r('ax') & 0xFF == 1 else None)
    pc.drives[1].bad = set(); k.key('f')
    check('... after 0Dh, B:\'s first look failing (Fail): a look that finds the directory again still due at the '
          'next (D_CHK %s)' % seen[:1], seen[:1] == [2], seen)

def t_batswap():
    """A batch file is opened for each line and closed again (as COMMAND's), at its whole name and place, so
    one that has the user change its disk asks for it back ("Insert disk with batch file", a key), never
    "Invalid disk change"; CALL's levels each keep theirs; deleted while it runs: "Batch file missing"."""
    def mkf(n, b):
        t = os.path.join(OUT, 'bsw_' + n.replace('\\', '_')); open(t, 'wb').write(b); return n + '=' + t
    lcmd = os.path.join(GOS, 'src', 'LCMD.COM')
    def drive(k, keys_at):
        """k's tty from now as each (text, action) comes: run until text is on it, then action()"""
        pc = k.pc; n0 = len(pc.tty)
        for text, act in keys_at:
            pc.run_until(lambda: text in ''.join(pc.tty)[n0:] or pc.crash, 20)
            if text not in ''.join(pc.tty)[n0:]: break
            act()
        k.settle()
        return ''.join(pc.tty)[n0:].replace('\r', '')
    key = lambda k: (lambda: k.pc.keys.append(ord(' ')))
    b1 = image('bsw_b1.img', mkf('S.BAT', b'@echo off\r\necho one\r\npause && dir b:\r\necho two\r\n'),
               mkf('A.BAT', b'@echo off\r\necho outer\r\ncall b:c\r\necho back\r\n'),
               mkf('C.BAT', b'@echo off\r\necho inner\r\npause\r\necho inner2\r\n'))
    b2 = image('bsw_b2.img', mkf('P1.TXT', b'P' * 900))
    d1 = open(b1, 'rb').read(); d2 = bytearray(open(b2, 'rb').read()); d2[0:512] = d1[0:512]; d2 = bytes(d2)
    for name, what in (('s', 'a PAUSE, the other disk (the same boot sector) put in, DIR B: on it'),
                       ('a', 'CALL C, C\'s PAUSE, the other disk put in')):
        k = ktest.KPC(image('bsw_a.img', lcmd), b=b1); k.start()
        Shell(k); pc = k.pc
        first = pc.drives[1]; other = pcemu.Floppy(bytearray(d2))
        def put(d):
            def f():
                d.changed = True; pc.drives[1] = d; pc.keys.append(ord(' '))
            return f
        k.key('cls'); k.key(ktest.ENTER)
        k.key('b:' + name); k.key(ktest.ENTER, settle=False)
        o = drive(k, (('Strike a key', put(other)), ('Insert disk with batch file', lambda: None),
                      ('Strike a key', put(first))))
        img = bytes(first.img)
        want = ('one', 'P1       TXT', 'Insert disk with batch file', 'two') if name == 's' else \
               ('outer', 'inner', 'Insert disk with batch file', 'inner2', 'back')
        at = [o.find(w) for w in want]
        check('a batch file on B:, %s: no "Invalid disk change"; its next line asks "Insert disk with batch file", '
              'the first disk back and a key: it goes on (%s); both disks as they were' % (what, ', '.join(want)),
              'Fail?' not in o and -1 not in at and at == sorted(at) and bytes(other.img) == d2 and img == d1
              and not fatcheck.check(img)[0], o[-500:])
    # deleted while it runs (a removable disk): asked for again after each key, as COMMAND's, till Ctrl-C
    k = ktest.KPC(image('bsw_d.img', lcmd, mkf('D.BAT', b'@echo off\r\ndel d.bat\r\necho after\r\n'))); k.start()
    sh = Shell(k); pc = k.pc
    k.key('cls'); k.key(ktest.ENTER); n0 = len(pc.tty)
    k.key('d'); k.key(ktest.ENTER, settle=False)
    for i in range(1, 4):
        pc.run_until(lambda: ''.join(pc.tty)[n0:].count('Strike a key') >= i or pc.crash, 20)
        pc.keys.append(3 if i == 3 else ord(' '))
    k.settle()
    o = ''.join(pc.tty)[n0:].replace('\r', ''); o2 = sh.run('echo still')
    check('a batch file that deletes itself: "Insert disk with batch file" again after each key (three times), '
          'never "Batch file missing"; Ctrl-C there ends it, the rest not run, the prompt back',
          o.count('Insert disk with batch file\nStrike a key') == 3 and 'Batch file missing' not in o and 'after' not in o
          and o.rstrip().endswith('A:\\>') and o2.startswith('still'), (o[-400:], o2))
    # ... a directory of its name made in its place: the open refused with 5: "Access denied", the batch ends
    k = ktest.KPC(image('bsw_d.img', lcmd, mkf('D.BAT', b'@echo off\r\ndel d.bat && md d.bat\r\necho after\r\n')))
    k.start()
    o = Shell(k).run('d')
    check('... a directory of its name in its place: "Access denied" (asked for not), the rest not run, the prompt back',
          'Access denied' in o and 'Insert disk' not in o and 'Batch file missing' not in o and 'after' not in o
          and o.rstrip().endswith('A:\\>'), o[-300:])
    k = ktest.KPC(image('bsw_d.img', lcmd, mkf('D.BAT', b'@echo off\r\ndel d.bat\r\necho after\r\n'))); k.start()
    sh = Shell(k)
    k.key('cls'); k.key(ktest.ENTER)
    k.key('d'); k.key(ktest.ENTER, settle=False)
    o = drive(k, (('Strike a key', lambda: k.pc.keys.append(3)),))
    o2 = sh.run('echo still')
    check('... Ctrl-C at its "Insert disk with batch file": the batch ends, the rest not run, the prompt back',
          'Insert disk with batch file' in o and 'Batch file missing' not in o and 'after' not in o
          and o.rstrip().endswith('A:\\>') and o2.startswith('still'), (o[-300:], o2))
    # GOTO and a long file: each line from its place (the next one's offset kept, not a handle's)
    lines = b'@echo off\r\ngoto two\r\n:one\r\necho at one\r\ngoto end\r\n:two\r\n' + b'rem ' + b'x' * 200 + b'\r\n' \
            + b'echo at two\r\ngoto one\r\n:end\r\necho done\r\n'
    k = ktest.KPC(image('bsw_g.img', lcmd, mkf('G.BAT', lines))); k.start()
    o = Shell(k).run('g')
    at = [o.find(w) for w in ('at two', 'at one', 'done')]
    check('GOTO forward and back past a 200-character line: each line read from its place, in order',
          -1 not in at and at == sorted(at), o[-300:])
    # a line longer than 127: cut, the rest passed over up to its end (not run as a line of its own); one of 127
    # and CR LF read whole (no empty line after it): each line's number as counted (an error says it)
    for nl in (b'\r\n', b'\n', b'\r'):
        e = nl if nl == b'\r' else b'\r\n'          # (a file of CRs only: each a line's end, MS-DOS's)
        lines = (b'@echo off' + e + b'rem ' + b'r' * 123 + e + b'echo ' + b'y' * 200 + b'Q.BAT' + nl + b'echo '
                 + b'z' * 300 + nl + b'nosuch' + e + b'echo done' + e)
        k = ktest.KPC(image('bsw_l.img', lcmd, mkf('L.BAT', lines))); k.start()
        o = Shell(k).run('l')
        check('lines of 210 and 305 characters (%s): each cut, its rest never run, the next line its own; '
              '"L line 5: Bad command or file name" (the 127-character line one line), then done'
              % {b'\r\n': 'CR LF', b'\n': 'LF', b'\r': 'CR only'}[nl], 100 < o.count('y') < 124 and 'Q.BAT' not in o
              and o.count('z') == o.count('y')
              and o.count('Bad command') == 1 and 'L line 5: Bad command or file name' in o and 'done' in o, o[-700:])
    # a line of 128 characters then CR LF (the read's 129th byte its CR, the LF after it not yet read): one line,
    # the LF its end, not an empty line of its own; CR only the same
    for nl in (b'\r\n', b'\r'):
        lines = b'@echo off' + nl + b'rem ' + b'r' * 124 + nl + b'nosuch' + nl + b'echo done' + nl
        k = ktest.KPC(image('bsw_l.img', lcmd, mkf('L.BAT', lines))); k.start()
        o = Shell(k).run('l')
        check('a line of 128 characters and %s: one line, "L line 3: Bad command or file name", then done'
              % ('CR LF' if nl == b'\r\n' else 'CR'), 'L line 3: Bad command or file name' in o
              and o.count('Bad command') == 1 and 'done' in o, o[-300:])
    # ... a ^Z in a long line's rest: the file's end there
    k = ktest.KPC(image('bsw_l.img', lcmd, mkf('L.BAT', b'@echo off\r\necho ' + b'y' * 200 + b'\x1a\r\necho never\r\n')))
    k.start()
    o = Shell(k).run('l')
    check('... a ^Z in the rest of a long line passed over: the batch ends there (the line after not run)',
          'never' not in o and 100 < o.count('y') < 124 and o.rstrip().endswith('A:\\>'), o[-300:])
    # its directory gone while it runs (path not found, 3, on a removable disk): asked for, as for 2
    k = ktest.KPC(image('bsw_s.img', lcmd, 'SUB\\', mkf('SUB\\S.BAT', b'@echo off\r\ncd \\ && del sub\\s.bat && rd sub\r\n'
                                                     b'echo after\r\n'))); k.start()
    sh = Shell(k)
    k.key('cls'); k.key(ktest.ENTER)
    k.key('sub\\s'); k.key(ktest.ENTER, settle=False)
    o = drive(k, (('Strike a key', lambda: k.pc.keys.append(3)),))
    check('... its directory removed while it runs: "Insert disk with batch file" (not "Batch file missing"), Ctrl-C '
          'ends it, the rest not run', 'Insert disk with batch file' in o and 'Batch file missing' not in o
          and 'after' not in o and o.rstrip().endswith('A:\\>'), o[-300:])
    # its whole name past what the kernel opens (127): "Batch file missing" (none of it run, nothing written past
    # its place); 127 exactly: run.  From a directory 53 deep, a name of its 7 directories more
    top = ['AAAAAAA%d' % i for i in range(1, 7)]; deep = ['BBBBBBB%d' % i for i in range(1, 8)]
    ds = ['\\'.join(top[:i + 1]) + '\\' for i in range(6)] + ['\\'.join(top + deep[:i + 1]) + '\\' for i in range(7)]
    full = '\\'.join(top + deep)
    more = ['CCCCCCC%d' % i for i in range(1, 6)]
    ds += ['\\'.join(top + deep + more[:i + 1]) + '\\' for i in range(5)]
    far = '\\'.join(top + deep + more)
    k = ktest.KPC(image('bsw_p.img', lcmd, *ds, mkf(full + '\\ABC.BAT', b'echo ran-127\r\n'),
                        mkf(full + '\\ABCD.BAT', b'echo ran-128\r\n'), mkf(far + '\\ABCD.BAT', b'echo ran-173\r\n'))); k.start()
    sh = Shell(k); sh.run('cd \\' + '\\'.join(top))
    rel = '\\'.join(deep) + '\\'
    o1 = sh.run(rel + 'abc'); o2 = sh.run(rel + 'abcd'); o4 = sh.run(rel + '\\'.join(more) + '\\abcd')
    o3 = sh.run('echo after'); o5 = sh.run(rel + 'abc')
    check('a batch file whose whole name is 127 characters (A:\\%s\\ABC.BAT): run; 128 (ABCD.BAT): "Batch file '
          'missing", none of it run; 173 (5 directories more: the kernel finds it not) not run; the shell as it was '
          '(no batch on, the 127 one runs again)' % full, len('A:\\' + full + '\\ABC.BAT') == 127
          and len('A:\\' + far + '\\ABCD.BAT') == 173
          and 'ran-127' in o1 and 'Batch file missing' in o2 and 'ran-128' not in o2 and 'ran-173' not in o4 and o3.startswith('after') and o3.rstrip().endswith('AAAAAAA6>') and 'ran-127' in o5,
          (o1[-200:], o2[-200:], o4[-200:], o3, o5[-200:]))
    # DIR's header after a silent remount: B: in \SUB, another disk put in with nothing open: its label and its
    # root, not the old disk's directory (the label's search is what mounts it; 47h asked before is stale)
    h1 = image('bsw_h1.img', 'SUB\\', mkf('SUB\\IN1.TXT', b'x' * 10))
    h2 = bytearray(open(image('bsw_h2.img', mkf('P2.TXT', b'y' * 10)), 'rb').read())
    i = h2.find(b'LODESTONE  \x08'); h2[i:i + 11] = b'OTHERDISK  '
    k = ktest.KPC(image('bsw_a.img', lcmd), b=h1); k.start()
    sh = Shell(k); sh.run('cd b:\\sub')
    d = pcemu.Floppy(h2); d.changed = True; k.pc.drives[1] = d
    o = sh.run('dir b:')
    check('DIR B: in B:\\SUB, another disk put in (nothing open): "Volume in drive B is OTHERDISK", "Directory of  '
          'B:\\", its files', i > 0 and 'drive B is OTHERDISK\n Directory of  B:\\\n' in o and 'P2       TXT' in o, o)

def t_newname():
    """new_name: CREATE, CREATE NEW, MKDIR and RENAME onto a name with no last part (A:\\, \\, A:, ., A.B\\.: 5;
    A.B\\ and the empty name: 3) make nothing, and the disk stays consistent."""
    com = os.path.join(OUT, 'NEWNAME.COM')
    subprocess.run(['nasm', '-f', 'bin', '-o', com, os.path.join(HERE, 'NEWNAME.ASM')], check=True)
    x = os.path.join(OUT, 'NN_X.TXT'); open(x, 'wb').write(b'hello')
    k = ktest.KPC(image('newname.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'NEWNAME.COM=' + com, 'X.TXT=' + x, 'A.B\\'))
    k.start()
    sh = Shell(k)
    assert run_long(k, 'newname > out.txt')
    d = bytes(k.pc.drives[0].img)
    got = [l.strip() for l in fatcheck.read_files(d).get('A:\\OUT.TXT', b'').decode('latin-1').replace('\r', '').split('\n')
           if l.startswith('fn ')]
    want = ['fn %s -> err %s' % (c, a) for c, a in MS_NEWNAME]
    check('NEWNAME.COM: all %d calls answer as before (no last part: 5; A.B\\ and the empty name: 3)' % len(want),
          got == want, [(w, g) for w, g in zip(want, got) if w != g] or (len(want), len(got)))
    dl = []; f = fatcheck.read_files(d, dirs=dl)
    probs, _ = fatcheck.check(d)
    check('... nothing made, X.TXT as it was, the disk consistent',
          set(f) == {'A:\\LODE.SYS', 'A:\\LCMD.COM', 'A:\\NEWNAME.COM', 'A:\\X.TXT', 'A:\\OUT.TXT'} and dl == ['A:\\A.B']
          and f['A:\\X.TXT'] == b'hello' and not probs, (sorted(f), dl, probs))

# NEWNAME.COM's calls and their errors (the kernel's before new_name tested r_wild first)
MS_NEWNAME = [('3C A:\\', '05'), ('3C \\', '05'), ('3C A:', '05'), ('3C A.B\\', '03'), ('3C .', '05'), ('3C A.B\\.', '05'),
              ('3C ', '03'), ('5B A:\\', '05'), ('5B A:', '05'), ('5B .', '05'),
              ('39 A:\\', '05'), ('39 \\', '05'), ('39 A:', '05'), ('39 A.B\\', '03'), ('39 .', '05'), ('39 A.B\\.', '05'),
              ('56 A:\\', '05'), ('56 \\', '05'), ('56 A:', '05'), ('56 .', '05'), ('56 A.B\\.', '05')]

# DEVNAME.COM's names: OPEN's answer, CREATE's, the device opened (number/GPIB address; '-' none)
DEVNAME_ANS = r'''
CON ok ok 0/0
NUL ok ok 1/0
AUX ok ok 2/0
COM1 ok ok 2/0
COM2 ok ok 4/0
PRN ok ok 3/0
LPT1 ok ok 3/0
CLOCK$ ok ok 1/0
NUL.TXT ok ok 1/0
COM e02 ok -
CONX e02 ok -
NU e02 ok -
CON.X ok ok 0/0
NUL. ok ok 1/0
NUL.. e02 e02 -
NUL.X. e02 e02 -
NUL.X.Y e02 e02 -
LPT1.PRN ok ok 3/0
CLOCK e02 ok -
CLOCK$$ e02 ok -
A.B\CLOCK$ ok ok 1/0
A.B\EMMXXXX0 e02 ok -
EMMXXXX0 e02 ok -
EMMXXXX e02 ok -
EMMXXXX0.X e02 ok -
\DEV\\NUL e03 e03 -
GPIB5 ok ok 5/5
GPIB05 ok ok 5/5
GPIB30 ok ok 5/30
GPIB31 e02 ok -
GPIB e02 ok -
GPIBX e02 ok -
GPIB5.X ok ok 5/5
GPIB5.X.Y ok ok 5/5
GPIB1Z e02 ok -
NOSUCH\GPIB5 e03 e03 -
\DEV\GPIB9 ok ok 5/9
A:GPIB12 ok ok 5/12
GPIB99 e02 ok -
GPIB5\ e03 e03 -
GPIB0 ok ok 5/0
GPIB123 e02 ok -
GPIB/5 e03 e03 -
GPIB:5 e02 e02 -
'''
DEVNAME_EMS = {'A.B\\EMMXXXX0': ('ok', 'ok', '6/0'), 'EMMXXXX0': ('ok', 'ok', '6/0'), 'EMMXXXX0.X': ('ok', 'ok', '6/0')}


def t_nomatch():
    """FIND FIRST that finds nothing is 18, "no more files", as in GRiD MS-DOS 3.30 (X22; it was 2): a name
    that isn't there, a pattern that matches nothing, an empty directory, a hidden file without the bit; a
    directory that isn't there is still 3.  (LCMD looks at CF only; the Executive's two that took 2 as "not
    there" are test_apps's: Copy and Move to a new name, a Copy to a subject that isn't there.)"""
    com = ms_build('NOMATCH')
    names = ('a', 'hid', 'sys', 'hs', 'x')
    for n in names:
        open(os.path.join(OUT, 'NM_%s.TXT' % n), 'wb').write(n.encode() + b'\r\n')
    img = image('nomatch.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'NOMATCH.COM=' + com,
                *['%s.TXT=%s' % (n.upper(), os.path.join(OUT, 'NM_%s.TXT' % n)) for n in names if n != 'x'])
    m = lambda *a: subprocess.run(list(a), check=True, stdin=subprocess.DEVNULL, capture_output=True)
    m('mmd', '-i', img, '::A.B'); m('mmd', '-i', img, '::E.F')
    m('mcopy', '-i', img, os.path.join(OUT, 'NM_x.TXT'), '::A.B/X.TXT')
    m('mattrib', '-i', img, '+h', '::HID.TXT'); m('mattrib', '-i', img, '+s', '::SYS.TXT')
    m('mattrib', '-i', img, '+h', '+s', '::HS.TXT')
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    ms_probe(k, 'NOMATCH', "NOMATCH.COM: all %d calls answer as GRiD MS-DOS 3.30's do (nothing found: 18; a directory "
             "that isn't there, or a bad name: 3)")
    o = sh.run('dir z*.*') + sh.run('dir e.f\\*.txt') + sh.run('del z*.*') + sh.run('if exist nosuch.txt echo yes')
    check('... and LCMD (CF only, as before): DIR and DEL of nothing say "File not found"; IF EXIST of nothing is false',
          o.count('File not found') == 3 and 'yes' not in o.replace('echo yes', ''), o)

def t_slashend():
    """A "/" at the very end of a line (X14): COPY, DEL, DIR and CHOICE stop there, and don't read on into what an
    earlier, longer line left in the buffer (COPY X.TXT / made a file named from it; DIR / listed it)."""
    open(os.path.join(OUT, 'NM_x.TXT'), 'wb').write(b'x\r\n')
    img = image('slash.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'X.TXT=' + os.path.join(OUT, 'NM_x.TXT'))
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    sh.run('rem 0123456789 abcdefghijklmnopqrst')       # (the buffer after "copy x.txt /": "9 abcdefghijklmnopqrst")
    o = sh.run('copy x.txt /')
    f = fatcheck.read_files(bytes(k.pc.drives[0].img))
    check('COPY X.TXT /: no file made from what an earlier line left (it made 9)', not [n for n in f if n not in
          ('A:\\LODE.SYS', 'A:\\LCMD.COM', 'A:\\X.TXT')] and 'copied onto itself' in o, (sorted(f), o))
    sh.run('rem 0123456789 abcdefghijklmnopqrst')
    o = sh.run('del /')
    check('DEL /: "Required parameter missing", nothing read past the end', 'Required parameter missing' in o
          and 'A:\\X.TXT' in fatcheck.read_files(bytes(k.pc.drives[0].img)), o)
    sh.run('rem   zzz*.q')                            # (after "dir /": "zzz*.q")
    o = sh.run('dir /')
    check('DIR /: the directory, not a pattern from an earlier line', 'X        TXT' in o and 'LCMD     COM' in o and '3 File(s)' in o
          and 'File not found' not in o, o)
    sh.run('rem xxxxxx,1 hello')                     # (after "choice /t": ",1 hello")
    o = sh.run('choice /t')
    check('CHOICE /T: "Syntax error", no default, time or text from an earlier line', 'Syntax error' in o and 'hello' not in o, o)
    o = sh.run('choice /')
    check('CHOICE /: "Syntax error"', 'Syntax error' in o, o)
    k = ktest.KPC(img); k.start()                       # (a fresh shell: a CHOICE above that waits can't spill over)
    sh = Shell(k)
    sh.run('rem 0123456789 abcdefghijklmnopqrst')
    o = sh.run('choice /c') + sh.run('choice /c hello')
    check('CHOICE /C with no keys (/C last, or a space after it): "Syntax error", not keys from an earlier line '
          'that no key can answer', o.count('Syntax error') == 2 and '[' not in o, o)
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    o = sh.run('set ' + 'A' * 87 + '=x') + sh.run('echo still here') + sh.run('set ' + 'B' * 79 + '=x')
    sh.run('set ' + 'C' * 78 + '=y')
    e = sh.run('set')
    check('SET of a name longer than the shell keeps (87, 79 letters): "Syntax error", and the shell as it was (it wrote '
          'over its own variables); 78 letters are kept', o.count('Syntax error') == 2 and 'still here' in o and 'A' * 87 not in e
          and 'B' * 79 not in e and 'C' * 78 + '=Y' in e.upper().replace('\n', ''), (o, e))

def t_dirlong():
    """DIR of a path whose pattern is longer than pat takes (X26): "File not found", and the shell goes on.  Its
    directory part ran past pat into pat_dir, and canon then copied over LCMD's own code: the machine hung.  The
    pattern (the path with its \\*.* or .*) may be 79 characters: a real 79-character path, the longest MS-DOS
    has, is listed.  DIR and COPY on a drive that isn't there start from "X:\\" each time.  DIR from a deep
    directory (canon's output past pat_dir) works.  (With no check at all, LCMD's overwritten code can loop
    where the clock hardly moves: then this test hangs, not fails.)"""
    img = image('dirlong.img', os.path.join(GOS, 'src', 'LCMD.COM'))
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    o = sh.run('dir ' + 'abcdefgh\\' * 8 + 'abcdefg\\x') + sh.run('dir ' + 'abcdefgh\\' * 9 + 'x') + sh.run('echo still here')
    check('DIR of an 81- and an 82-character path (directory parts of 80 and 81): "File not found", the shell as it was (it hung)',
          o.count('File not found') == 2 and 'still here' in o and not k.crashed, o)
    sh.run('md d')
    p75, p76 = 'd\\..\\' * 14 + '.\\.\\d', 'd\\..\\' * 15 + 'd'
    assert len(p75) == 75 and len(p76) == 76
    o75 = sh.run('dir ' + p75); o76 = sh.run('dir ' + p76) + sh.run('echo still here')
    check('a 75-character path naming a directory (its \\*.* makes 79) is listed; 76: "File not found", no header',
          'Directory of  A:\\D\n' in o75 and 'File not found' not in o75 and 'Directory' not in o76
          and 'File not found' in o76 and 'still here' in o76 and not k.crashed, (o75, o76))
    k = ktest.KPC(img); k.start()                       # (a fresh shell: on main the DIRs above leave it hung)
    sh = Shell(k)
    runs = [sh.run('dir b:' + 'a' * 72 + '\\').replace('\n', '') for _ in range(6)]
    o = sh.run('copy lcmd.com q:' + 'b' * 70 + '\\c') + sh.run('copy lcmd.com q:' + 'b' * 70 + '\\c') + sh.run('echo still here')
    check('DIR and COPY on a drive that isn\'t there, six and two times: each from "B:\\" afresh (canon took what the one '
          'before left as the current directory, growing until it wrote over the shell); DIR says "Invalid drive '
          'specification" (DOS\'s), COPY File creation error',
          all('Invalid drive specification' in r and 'Directory of' not in r for r in runs) and o.count('File creation error') == 2
          and 'still here' in o, (runs[-1], o))
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    deep = 'aaaaaaaa.aaa\\bbbbbbbb.bbb\\cccccccc.ccc\\dddddddd.ddd\\eeeeeeee.ee'
    for p in deep.split('\\'):
        sh.run('md ' + p); sh.run('cd ' + p)
    sh.run('echo x > ffffffff.ttt')
    full = 'a:\\' + deep + '\\ffffffff.ttt'
    assert len(full) == 79
    o = sh.run('dir ' + full) + sh.run('dir ' + full[:-3] + '*')
    check('DIR of a real 79-character path (an 8.3 name in a 64-character directory, the longest MS-DOS has), and of it as '
          'a pattern: listed', o.count('FFFFFFFF TTT') == 2 and 'File not found' not in o, o)
    o = sh.run('dir ' + 'z' * 60 + '\\..\\f.txt') + sh.run('echo still here')
    check('DIR from that directory of a 69-character relative path (canon past pat_dir): its header right, no hang',
          'Directory of  A:\\' + deep.upper() + 'File not found' in o.replace('\n', '') and 'still here' in o
          and not k.crashed, o)


def t_attr():
    """CREATE, CREATE NEW and CREATE TEMPORARY give a file the archive bit, new or made anew (X19), as GRiD MS-DOS
    3.30 does; CREATE and CREATE NEW refuse CX with 10h, 40h or 80h (5, before the path is looked at, for a
    device too) and leave CX's high byte alone; a file written gets the archive bit, one only opened doesn't."""
    com = ms_build('ATTR')
    for n in ('t0', 't2', 'th', 'w', 'o'):
        open(os.path.join(OUT, 'AT_%s.TXT' % n), 'wb').write(n.encode() + b'\r\n')
    img = image('attr.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'ATTR.COM=' + com,
                *['%s.TXT=%s' % (n.upper(), os.path.join(OUT, 'AT_%s.TXT' % n)) for n in ('t0', 't2', 'th', 'w', 'o')])
    m = lambda *a: subprocess.run(list(a), check=True, stdin=subprocess.DEVNULL, capture_output=True)
    for n in ('T0', 'T2', 'TH', 'W', 'O'):
        m('mattrib', '-i', img, '-a', '::%s.TXT' % n)
    m('mattrib', '-i', img, '+h', '::TH.TXT')
    for n in ('A.B', 'E.F', 'G.H'):
        m('mmd', '-i', img, '::' + n)
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    f = ms_probe(k, 'ATTR', "ATTR.COM: all %d calls answer as GRiD MS-DOS 3.30's do (a file created gets 20h; 10h, 40h, "
                 "80h refused with 5)")
    check('... disk consistent', not fatcheck.check(bytes(k.pc.drives[0].img))[0], fatcheck.check(bytes(k.pc.drives[0].img))[0])
    # CX with a label's bit (8): MS-DOS makes a volume label, leaving a file of that name alone; Lodestone has none
    # to make: 5, the file kept (it was truncated)
    src, cr8 = os.path.join(OUT, 'CR8.ASM'), os.path.join(OUT, 'CR8.COM')
    open(src, 'w').write('org 100h\n mov dx, nm\n mov cx, 8\n mov ah, 3Ch\n int 21h\n jc e\n mov bx, ax\n mov ah, 3Eh\n'
                         ' int 21h\n xor al, al\ne: mov ah, 4Ch\n int 21h\nnm db "W.TXT", 0\n')
    subprocess.run(['nasm', '-f', 'bin', '-o', cr8, src], check=True)
    before = f.get('A:\\W.TXT')
    open(img, 'r+b').write(bytes(k.pc.drives[0].img))  # (the disk ATTR.COM left)
    subprocess.run(['mcopy', '-o', '-i', img, cr8, '::CR8.COM'], check=True, stdin=subprocess.DEVNULL, capture_output=True)
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    o = sh.run('cr8') + sh.run('if errorlevel 5 if not errorlevel 6 echo refused')
    check('CREATE of W.TXT with CX=8: 5, and W.TXT as it was', 'refused' in o.replace('echo refused', '') and before
          and fatcheck.read_files(bytes(k.pc.drives[0].img)).get('A:\\W.TXT') == before, (o, before))

def t_errs():
    """X17 and X20: the path calls (OPEN, CREATE, CREATE NEW, DELETE, GET ATTRIBUTES, FIND FIRST, MKDIR, RMDIR, CHDIR,
    RENAME) answer as GRiD MS-DOS 3.30 does for a missing directory with a bad last name (2 for open and create),
    a \\ last (3), two \\s (one), a wildcard where one name is wanted (3), an invalid drive (3), ".." in the root
    (3), a device's name with a second dot (no device), RENAME of a device's name (5), RMDIR of the current
    directory or of a wildcard (16) and of a file or a name not there (5).  ERRS_MS.TXT holds MS-DOS's answers;
    what is left as it is (X20's row) is not in ERRS.ASM."""
    com = ms_build('ERRS')
    open(os.path.join(OUT, 'ER_a.TXT'), 'wb').write(b'a\r\n')
    a = os.path.join(OUT, 'ER_a.TXT')
    img = image('errs.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'ERRS.COM=' + com, 'A.TXT=' + a, 'SUB\\', 'SUB\\X.TXT=' + a)
    k = ktest.KPC(img); k.start()
    Shell(k)
    ms_probe(k, 'ERRS', "ERRS.COM: all %d calls answer as GRiD MS-DOS 3.30's do", 300)
    check('... disk consistent', not fatcheck.check(bytes(k.pc.drives[0].img))[0], fatcheck.check(bytes(k.pc.drives[0].img))[0])


def t_nodisk():
    """A drive with no disk (B:): each path call raises INT 24h as GRiD MS-DOS 3.30 does (AH 1Ah: Retry or Fail,
    read, the FAT's area; DI 2, not ready), then answers 3 (free space FFFFh) when it is told Fail.  It answered 21
    with no INT 24h: the mount read the boot sector without one.  LCMD asks "Abort, Retry, Fail?" as COMMAND.COM."""
    com = ms_build('NODISK')
    k = ktest.KPC(image('nodisk.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'NODISK.COM=' + com), bytes(1474560))
    k.pc.drives[1].empty = True
    k.start()
    sh = Shell(k)
    ms_probe(k, 'NODISK', "NODISK.COM: all %d calls answer as GRiD MS-DOS 3.30's do (INT 24h, then 3)")
    # a handler that answers Ignore, which the mount doesn't offer: Fail, as MS-DOS (it mounted B: from A:'s boot sector)
    ig = os.path.join(OUT, 'NODISKIG.COM')
    subprocess.run(['nasm', '-f', 'bin', '-o', ig, os.path.join(HERE, 'NODISKIG.ASM')], check=True)
    cmds = os.path.join(OUT, 'CMDS.TXT'); open(cmds, 'wb').write(b'dir b:*.txt' + bytes([13, 10]) + b'dir b:*.txt' + bytes([13, 10]) + b'exit' + bytes([13, 10]))
    nd2 = os.path.join(OUT, 'ND2.BAT'); open(nd2, 'wb').write(b'@dir b:*.txt' + bytes([13, 10]) + b'@echo hi > b:y.txt' + bytes([13, 10]))
    k = ktest.KPC(image('nodiskig.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'NODISKIG.COM=' + ig, 'ND2.BAT=' + nd2, 'CMDS.TXT=' + cmds, 'BIN' + chr(92),
                        'BIN' + chr(92) + 'NODISKMT.COM=' + os.path.join(HERE, 'NODISKMT.COM')), bytes(1474560))
    k.pc.drives[1].empty = True
    k.start()
    sh = Shell(k)
    assert run_long(k, 'nodiskig > out.txt')
    o = fatcheck.read_files(k.pc.drives[0].img).get('A:\\OUT.TXT', b'').decode('latin-1')
    check('... a handler that answers Ignore at the mount: Fail all the same (open and FIND FIRST 3, free space FFFFh), '
          'not B: mounted from what A: left', 'open B:X.TXT err 0003' in o and 'B: free FFFF' in o and 'find B:*.* err 0003' in o, o)
    k.key('cls'); k.key(ktest.ENTER)
    k.key('type b:x.txt'); k.key(ktest.ENTER)
    o1 = k.pc.text_screen()
    k.key('f')
    o = k.pc.text_screen()
    check('LCMD: TYPE B:X.TXT with no disk: "Not ready error reading drive B", "Abort, Retry, Fail?"; F: back at the prompt',
          'Not ready error reading drive B' in o1 and 'Abort, Retry, Fail?' in o1 and o.rstrip().endswith('A:\\>'), (o1, o))
    # B: current, no disk: nothing asked at each prompt (a pipe's files went only after a pipe); a program looked for
    # there: one question, not one for each of .COM .EXE .BAT; Tab: a beep, no question in the line
    k.key('cls'); k.key(ktest.ENTER)
    k.key('b:'); k.key(ktest.ENTER); k.key(ktest.ENTER); k.key(ktest.ENTER)
    o1 = k.pc.text_screen()
    k.key('x'); k.key(ktest.ENTER)
    o2 = k.pc.text_screen()
    k.key('f')
    o3 = k.pc.text_screen()
    k.key('a:'); k.key(ktest.ENTER); k.key('cls'); k.key(ktest.ENTER)
    k.key('type b:'); k.key(ktest.TAB)
    o4 = k.pc.text_screen()
    k.key(ktest.ESC); k.key(ktest.ENTER)
    check('... B: current with no disk: no question at the prompts; X there: one, then "Bad command or file name"; '
          'Tab on B:: none, the line as typed', 'Fail?' not in o1 and o1.count('B:\\>') >= 3 and o2.count('Fail?') == 1
          and o3.count('Fail?') == 1 and 'Bad command or file name' in o3 and 'Fail?' not in o4 and 'A:\\>type b:' in o4,
          (o1, o2, o3, o4))
    # a pipe whose second command's redirection fails: the first's file deleted all the same
    k.key('cls'); k.key(ktest.ENTER)
    k.key('echo hi | echo x < nosuch.txt'); k.key(ktest.ENTER)
    k.key('dir \\pipe*.*'); k.key(ktest.ENTER)
    o = k.pc.text_screen()
    check('... "echo hi | echo x < nosuch.txt": "File not found" for the redirection, and no \\PIPEA1.$$$ left',
          o.count('File not found') == 2 and 'PIPEA1' not in o, o)
    # one question for each command, though it makes several calls (COMMAND.COM asks up to 5 times): F, or A, answers
    # the rest of it; a batch file's next line asks again
    def asks(c, ans='f'):
        n0 = len(k.pc.tty)
        k.key(c); k.key(ktest.ENTER)
        for i in range(8):
            if ''.join(k.pc.tty)[n0:].count('Fail?') > i: k.key(ans)
            else: break
        return ''.join(k.pc.tty)[n0:]
    n = {c: asks(c).count('Fail?') for c in ('dir b:*.txt', 'dir b:\\sub', 'copy b:x.bat a:', 'del b:x.bat',
                                             'dir b:x.txt > o.txt', 'copy b:x.txt+a.txt c.txt')}
    na = asks('copy b:*.* a:', 'a').count('Fail?')
    check('... DIR, COPY, DEL on B:: one question each, F answering the rest of the command (A as F, in LCMD\'s own work)',
          set(n.values()) == {1} and na == 1, (n, na))
    k.key('echo dir b:*.txt > nd.bat'); k.key(ktest.ENTER)
    k.key('echo del b:x.bat >> nd.bat'); k.key(ktest.ENTER)
    o = asks('nd')
    check('... a batch file of two such lines: one question for each line', o.count('Fail?') == 2, o)
    # the next line's redirection asks too (it's opened before the command runs)
    o = asks('nd2')
    check('... a batch line redirected to B: after one answered F: asked again (two questions)', o.count('Fail?') == 2, o)
    # a program LCMD runs is asked, though LCMD's own PATH search on B: was answered F in the same line
    k.key('set path=b:\\;a:\\bin'); k.key(ktest.ENTER)
    n0 = len(k.pc.tty)
    k.key('nodiskmt'); k.key(ktest.ENTER, settle=False)
    seen = 0
    for i in range(6):
        k.run_for(1.5)
        if ''.join(k.pc.tty)[n0:].count('Fail?') > seen: seen += 1; k.key('f', settle=False)
    k.settle()
    o = ''.join(k.pc.tty)[n0:]
    res = fatcheck.read_files(k.pc.drives[0].img).get('A:\\RES.TXT')
    check('... NODISKMT found in A:\\BIN after the PATH\'s B:\\: two questions, the PATH search\'s and the program\'s own '
          '(RES.TXT "03")', o.count('Fail?') == 2 and res == b'03', (o, res))
    # lines read from a file, not the console (lcmd < cmds.txt): each asks again too
    o = asks('lcmd < cmds.txt')
    check('... LCMD reading its lines from a file (two DIR B:*.TXT): one question for each line', o.count('Fail?') == 2, o)
    # a COPY whose writes fail part way (B: write-protected after its 3rd sector): F, then the partial copy's close and
    # delete ask again, so a Retry with the disk put right leaves no 0-byte file and no lost clusters
    big = os.path.join(OUT, 'BIG.DAT'); open(big, 'wb').write(bytes(range(256)) * 160)
    k = ktest.KPC(image('nodiskcp.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'BIG.DAT=' + big),
                  open(image('nodiskb.img', 'ND2.BAT=' + nd2), 'rb').read())
    k.start()
    k.key('cls'); k.key(ktest.ENTER)
    free0 = re.search(r'([\d,]+) bytes free', asks('dir b:')).group(1)
    orig, st = type(k.pc).int13, {'on': True, 'w': 0}
    def int13(s):
        if st['on'] and s.r('ah') == 3 and s.r('dl') == 1:
            st['w'] += 1
            if st['w'] == 4: s.drives[1].wp = True
        return orig(s)
    type(k.pc).int13 = int13
    try:
        n0 = len(k.pc.tty)
        k.key('copy big.dat b:'); k.key(ktest.ENTER)
        k.key('f'); st['on'] = False; k.pc.drives[1].wp = False
        for i in range(6):
            if ''.join(k.pc.tty)[n0:].count('Fail?') > i + 1: k.key('r')
        o = ''.join(k.pc.tty)[n0:]
    finally:
        type(k.pc).int13 = orig
    m = re.search(r'([\d,]+) bytes free', asks('dir b:'))
    files = fatcheck.read_files(k.pc.drives[1].img)
    check('... COPY to B: failing part way: F, then its clean-up asks again; R there: no BIG.DAT left, B:\'s free space as '
          'before', o.count('Fail?') >= 2 and 'B:\\BIG.DAT' not in files and m and m.group(1) == free0,
          (o, sorted(files), free0, m and m.group(1)))

def t_command():
    """LCMD 0.4.2's batch language: && and ||, ERRORLEVEL from built-ins,
    errors that say where, IF, GOTO, SHIFT, FOR, CALL, %NAME%, CHOICE."""
    def bat(name, *lines):
        p = os.path.join(OUT, name)
        open(p, 'wb').write(('\r\n'.join(lines) + '\r\n').encode())
        return name + '=' + p
    open(os.path.join(OUT, 'EMPTY.TXT'), 'wb').close()
    img = image('cmd.img', os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(HERE, 'UPPER.COM'), os.path.join(HERE, 'MEMSZ.COM'),
                'EMPTY.TXT=' + os.path.join(OUT, 'EMPTY.TXT'), os.path.join(HERE, 'CMDTEST.BAT'), 'SUB\\',
                bat('EL.BAT', '@echo off', 'type nosuch.txt', 'if errorlevel 1 echo E1', 'echo hi > a.txt', 'type a.txt',
                    'if not errorlevel 1 echo E0', 'del a.txt'),
                bat('ARGS.BAT', '@echo off', ':loop', 'if "%1"=="" goto end', 'echo arg %1', 'shift', 'goto loop', ':end', 'echo done'),
                bat('NOLAB.BAT', '@echo off', 'goto nowhere', 'echo not here'),
                bat('EX.BAT', '@echo off', 'if exist ex.bat echo yes1', 'if not exist nosuch.x echo yes2', 'if exist sub echo yes3',
                    'if exist nosuch.x echo no1', 'if %1==a echo yes4', 'if NOT %1==a echo no2'),
                bat('FORS.BAT', '@echo off', 'for %%f in (one two,three) do echo item %%f', 'for %%f in (sub\\*.txt) do type %%f'),
                bat('OUTER.BAT', '@echo off', 'echo outer start', 'call inner x y', 'if errorlevel 3 echo el3', 'echo outer back %1'),
                bat('INNER.BAT', 'echo inner %1 %2', 'choice /c:abc /n /t:c,0'),
                bat('VAR.BAT', '@echo off', 'set greet=hello', 'echo %greet% there %nosuch%end', 'echo 50% done', 'set greet='),
                bat('CH.BAT', '@echo off', 'choice /c:abc Pick', 'if errorlevel 2 echo atleast2', 'if errorlevel 3 echo three'),
                bat('FORCALL.BAT', '@echo off', 'for %%f in (p q) do call sub1 %%f', 'echo fc done'),
                bat('SUB1.BAT', '@echo off', 'goto lab', 'echo skipped', ':lab', 'echo sub %1'),
                bat('FORGO.BAT', '@echo off', 'for %%f in (1 2 3) do if %%f==2 goto out', 'echo not reached', ':out', 'echo out ok'),
                bat('O1.BAT', '@echo off', 'call i1 && echo AFTER1', 'if exist o1.bat call i1 && echo AFTER2', 'call i1 | upper'),
                bat('I1.BAT', 'echo hello world from the inner batch file, a long line'),
                bat('O2.BAT', '@echo off', 'call i2'),
                bat('O2F.BAT', '@echo off', 'for %%a in (1 2) do call i2'),
                bat('I2.BAT', 'pause'),
                bat('O3.BAT', '@echo off', 'for %%d in (1 2) do call i3 %%d'),
                bat('I3.BAT', '@echo off', 'for %%e in (a b) do echo in %1 %%e'),
                bat('I7.BAT', '@echo off', 'echo abc | upper'),
                bat('I8.BAT', '@echo off', 'echo abc | upper', 'upper'),
                bat('ST.BAT', '@echo off', 'set temp=a:\\tmp2', 'echo abc | upper', 'upper'),
                bat('SUB\\TT.BAT', '@echo off', 'set temp=a:\\tmp2', 'dir tmp2 | upper', 'set temp=', 'dir tmp2 | upper'),
                bat('SH.BAT', '@echo off', 'shift', 'type nosuch.x'),
                bat('CS.BAT', '@echo off', 'choice /c:yn /s Case'))
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    o = sh.run('echo.hello')
    o2 = sh.run('echo. >> e.txt')
    o3 = sh.run('type e.txt')
    check('ECHO.text: the text; ECHO. into a file: a blank line (the name parse kept AL from strlen)', 'hello' in o.split('\n')
          and 'ECHO is' not in o + o2 + o3 and o3.split('\n')[0].strip() == '', (o, o2, o3))
    sh.run('del e.txt')
    sh.run('cd sub')
    o = sh.run('cd..')
    sh.run('cd sub')
    o2 = sh.run('cd\\')
    check('CD.. and CD\\ (no space)', o.split('\n')[-1].startswith('A:\\>') and 'A:\\>' == o2.split('\n')[-1] and 'SUB' not in o + o2, (o, o2))
    o = sh.run('echo a && echo b')
    check('&&: both', 'a\n' in o + '\n' and '\nb' in o, o)
    o = sh.run('type nosuch.x && echo NOPE')
    check('&& after a failure: not run', 'File not found' in o and 'NOPE' not in o, o)
    o = sh.run('type nosuch.x || echo YES1')
    check('|| after a failure: run', 'YES1' in o, o)
    o = sh.run('ver && type nosuch.x || echo YES2')
    check('a && b || c: c when b fails', 'Lodestone version' in o and 'YES2' in o, o)
    o = sh.run('nosuchcmd || echo YES3')
    check('a bad command fails too', 'Bad command' in o and 'YES3' in o, o)
    o = sh.run('echo xyz > m.txt && type m.txt && del m.txt')
    check('redirection belongs to its own part', 'xyz' in o and 'M        TXT' not in sh.run('dir'), o)
    o = sh.run('echo a | upper || echo CODE1')
    o2 = sh.run('rem | upper && echo CODE0')
    check('a pipe: && and || go by its last program (UPPER: exit code = lines)', 'A' in o.split('\n') and 'CODE1' in o and 'CODE0' in o2, (o, o2))
    o = sh.run('el')
    check('ERRORLEVEL from built-ins: 1 after a failure, 0 after success',
          'E1' in o and 'E0' in o and 'hi' in o, o)
    check('an error in a batch file says where', 'EL line 2: File not found' in o, o)
    o = sh.run('args a b c')
    check('IF "%1"=="", GOTO, SHIFT', [l for l in o.split('\n') if l.startswith('arg ')] == ['arg a', 'arg b', 'arg c'] and 'done' in o, o)
    o = sh.run('nolab')
    check('GOTO to no label: says so, the batch file stops', 'NOLAB line 2: Label not found' in o and 'not here' not in o, o)
    o = sh.run('ex a')
    check('IF EXIST (a directory too), IF NOT EXIST, IF a==b, IF NOT',
          all(x in o for x in ('yes1', 'yes2', 'yes3', 'yes4')) and 'no1' not in o and 'no2' not in o, o)
    sh.run('echo in sub > sub\\s.txt')
    o = sh.run('fors')
    check('FOR in a batch file: a list, then names with a directory', all(('item ' + x) in o for x in ('one', 'two', 'three')) and 'in sub' in o, o)
    o = sh.run('for %f in (*.bat) do echo B %f')
    check('FOR at the prompt: the names that match', 'B ARGS.BAT' in o and 'B VAR.BAT' in o, o)
    o = sh.run('outer z')
    check('CALL: the other batch file runs, gets its arguments, this one goes on',
          'outer start' in o and 'inner x y' in o and 'outer back z' in o and 'echo inner' not in o, o)
    check('... with the ERRORLEVEL it left (CHOICE /T: the default)', 'el3' in o, o)
    o = sh.run('forcall')
    check('FOR ... DO CALL: each runs to its end; a GOTO in it stays in it', 'sub p' in o and 'sub q' in o and 'fc done' in o
          and 'skipped' not in o, o)
    o = sh.run('forgo')
    check('GOTO out of a FOR', 'out ok' in o and 'not reached' not in o, o)
    o = sh.run('o1')
    check('&&, IF and | after a CALL: the line goes on where it was', o.count('hello world from the inner') == 2
          and 'AFTER1' in o and 'AFTER2' in o and 'HELLO WORLD FROM THE INNER' in o and 'Bad command' not in o, o)
    o = sh.run('call i1 && echo AFTER3')
    check('... at the prompt too', 'AFTER3' in o, o)
    o = sh.run('o3')
    check('a FOR in a batch file CALLed from a FOR', all(('in %s %s' % (d, e)) in o for d in '12' for e in 'ab') and 'Syntax' not in o, o)
    o = sh.run('echo zzz | call i7')
    check('a pipe in a batch file CALLed in a pipe: its own pipe files', 'ABC' in o and 'creation' not in o
          and 'PIPE' not in sh.run('dir'), o)
    o = sh.run('echo zzz | call i8')
    check('... the outer pipe\'s input still there after the inner pipe (UPPER after it reads zzz)',
          'ABC' in o and 'ZZZ' in o and 'PIPE' not in sh.run('dir'), o)
    sh.run('md tmp2')
    for tv in ('', 'a:\\tmp2'):
        sh.run('set temp=' + tv)
        o = sh.run('echo abc | upper | upper | upper')
        check('three pipes (TEMP=%s): each its own file, ABC through all of them, none left' % (tv or 'none'),
              'ABC' in o and 'PIPE' not in sh.run('dir') + sh.run('dir tmp2'), o)
    sh.run('set temp=')
    o = sh.run('echo zzz | call st')                   # (SET TEMP= in a batch file CALLed in a pipe)
    check('SET TEMP= in a batch file CALLed in a pipe, a pipe of its own after: all of them in the root '
          '(TEMP read when the outer pipe began), the outer input still read, none left', 'ABC' in o and 'ZZZ' in o
          and 'PIPE' not in sh.run('dir') + sh.run('dir tmp2'), o)
    sh.run('set temp=')
    o = sh.run('call sub\\tt')                         # (CALLed: its lines with no prompt between)
    check('a batch file CALLed: TEMP set, a pipe; TEMP removed, a pipe: the first\'s file in TMP2, the second\'s not '
          '(TEMP read again by each line\'s pipe; PIPEB: a level in)', o.count('PIPEB1   $$$') == 1 and o.count('DIRECTORY OF  A:\\TMP2') == 2
          and 'PIPE' not in sh.run('dir tmp2'), o)
    sh.run('rd tmp2')
    o = sh.run('if exist sub\\nul echo DIRNUL')
    o2 = sh.run('if exist ex.bat\\nul echo FILENUL')
    check('IF EXIST dir\\NUL: a directory (not a file)', 'DIRNUL' in o and 'FILENUL' not in o2, (o, o2))
    o = sh.run('sh a b')
    check('after SHIFT an error still names the batch file', 'SH line 3: File not found' in o, o)
    o = sh.run('cs', 'y')
    check('CHOICE /S: the keys as typed', 'Case[y,n]?y' in o, o)
    o = sh.run('pause < empty.txt')
    check('PAUSE with standard input from an empty file: goes on', 'Strike a key' in o and o.rstrip().endswith('>'), o)
    k.key('choice /t:y,4000 Long'); k.key(ktest.ENTER)
    k.key('n')
    check('CHOICE /T:y,4000 (more than 99 s): waits, takes a key', 'Long[Y,N]?N' in k.pc.text_screen() and not k.crashed,
          k.pc.text_screen())
    o = sh.run('o2')
    k.key(0x2E03)
    o = k.pc.text_screen()
    sh.run('echo visible')
    check('Ctrl-C in a CALLed batch file: the prompt shows again', k.pc.text_screen().split('\n')[0].startswith('A:\\>echo visible'),
          k.pc.text_screen())
    o = sh.run('var')
    check('%NAME% from the environment (none: nothing), a lone % kept', 'hello there end' in o and '50% done' in o, o)
    o = sh.run('ch', 'b')
    check('CHOICE: [A,B,C]?, the key shown, ERRORLEVEL its place', 'Pick[A,B,C]?B' in o and 'atleast2' in o and 'three' not in o, o)
    k.key('choice /c:yn /t:n,2 Wait'); k.key(ktest.ENTER)
    k.pc.run_for(1.0)
    early = 'Wait[Y,N]?N' in k.pc.text_screen()
    k.pc.run_for(2.0); k.settle()
    k.key('if errorlevel 2 echo TIMED'); k.key(ktest.ENTER)
    check('CHOICE /T: the default after the time', not early and 'Wait[Y,N]?N' in k.pc.text_screen() and 'TIMED' in k.pc.text_screen(),
          k.pc.text_screen())
    k.key('cmdtest'); k.key(ktest.ENTER); k.pc.run_for(4); k.settle()
    o = k.pc.text_screen()
    check('CMDTEST.BAT (the self-test for the 1520): all 11 pass, the error line named', 'All 11 tests passed.' in o
          and 'CMDTEST line 37: File not found' in o and 'FAIL' not in o, o)
    def largest():
        k.key('cls'); k.key(ktest.ENTER)
        k.key('memsz'); k.key(ktest.ENTER)
        m = re.search(r'([\d.]+) KB for programs', k.pc.text_screen())
        return m.group(1) if m else None
    m0 = largest()
    for _ in range(3):
        k.key('type con'); k.key(ktest.ENTER); k.key('abc'); k.key(0x2E03)
    m1 = largest()
    check('Ctrl-C in TYPE CON three times: no memory lost', m0 and m0 == m1, (m0, m1))
    # FOR's set, command and DTA are in a block of their own only while it runs (L4)
    k.key('cls'); k.key(ktest.ENTER)
    k.key('for %a in (x) do memsz'); k.key(ktest.ENTER)
    m = re.search(r'([\d.]+) KB for programs', k.pc.text_screen())
    m2 = m.group(1) if m else None
    for b in ('fors', 'forcall', 'forgo', 'o3'):
        k.key('cls'); k.key(ktest.ENTER); k.key(b); k.key(ktest.ENTER)
    m3 = largest()
    check('a program run by a FOR: 0.1-0.2 KB less (FOR\'s block, 11 paragraphs and its MCB, 192 bytes); after FORs (a list, '
          'names, CALL in one, GOTO out of one, FOR in a CALLed batch file in a FOR): no memory lost',
          m2 and m3 == m0 and 0.05 < float(m0) - float(m2) < 0.25, (m0, m2, m3))
    for _ in range(3):
        k.key('cls'); k.key(ktest.ENTER)
        k.key('for %a in (1 2 3) do pause'); k.key(ktest.ENTER); k.key(0x2E03)
    k.key('cls'); k.key(ktest.ENTER)
    k.key('for %a in (q) do echo after %a'); k.key(ktest.ENTER)
    o = k.pc.text_screen()
    m4 = largest()
    check('Ctrl-C in a FOR three times: its block given back each time, and a FOR runs again', m4 == m0 and 'after q' in o, (m0, m4, o))
    k.key('cls'); k.key(ktest.ENTER)
    k.key('o2f'); k.key(ktest.ENTER); k.key(0x2E03)
    m5 = largest()
    check('Ctrl-C in a batch file CALLed from a FOR: the FOR\'s block (kept at the CALL) given back too', m5 == m0, (m0, m5))
    k.key('exit'); k.key(ktest.ENTER)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    probs, files = fatcheck.check(bytes(k.pc.drives[0].img))
    check('back in the Executive, disk consistent', k.pc.mode() == 0x40 and not probs, probs)

def t_cmdedit():
    """The prompt's line editor: cursor keys, Del, ESC, history, F3, Tab;
    Ctrl-C; a long line; standard input from a file (DOS's line input)."""
    HOME, END, DEL, F3, CTLC = 0x4700, 0x4F00, 0x5300, 0x3D00, 0x2E03
    p = os.path.join(OUT, 'S.TXT'); open(p, 'wb').write(b'echo from a file\r\nexit\r\n')
    p2 = os.path.join(OUT, 'S2.TXT'); open(p2, 'wb').write(b'echo no exit\r\n')
    img = image('ed.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'SUBDIR\\', 'S.TXT=' + p, 'S2.TXT=' + p2)
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    def run(*keys):
        k.key('cls'); k.key(ktest.ENTER)
        for x in keys: k.key(x)
        k.key(ktest.ENTER)
        return '\n'.join(k.pc.text_screen().rstrip().split('\n')[1:])
    o = run('echo helo', ktest.LEFT, 'l')
    check('Left, then a character goes in', 'hello' in o.split('\n'), o)
    o = run('cho hi', HOME, 'e')
    check('Home', 'hi' in o.split('\n'), o)
    o = run('echo xhi', HOME, *([ktest.RIGHT] * 5), DEL)
    check('Del', 'hi' in o.split('\n'), o)
    o = run('echo ab', ktest.BKSP, 'c', END)
    check('Backspace, End', 'ac' in o.split('\n'), o)
    o = run('garbage', ktest.ESC, 'echo clean')
    check('ESC clears the line', 'clean' in o.split('\n') and 'Bad command' not in o, o)
    def last(*keys):
        """Keys, Enter: the line printed just before the new prompt."""
        for x in keys: k.key(x)
        k.key(ktest.ENTER)
        l = [x for x in k.pc.text_screen().rstrip().split('\n') if x.strip()]
        return l[-2] if len(l) > 1 else ''
    last('echo first'); last('echo second')
    o = last(ktest.UP, ktest.UP)
    check('Up, Up: the line before last', o == 'first', o)
    o = last(ktest.UP, ktest.UP, ktest.DOWN)
    check('... Down: the next one', o == 'first', o)
    o = last(ktest.UP, ktest.UP, ktest.UP, ktest.DOWN)       # first, second, first, second
    check('... Up three times, Down', o == 'second', o)
    o = last(F3)
    check('F3: the last line again', o == 'second', o)
    o = last('echo sec', F3)
    check('F3 after some of it: the rest', o == 'second', o)
    run('echo one > longname.txt'); run('echo two > ab1.txt'); run('echo three > ab2.txt')
    o = run('type longn', ktest.TAB)
    check('Tab completes a name', 'one' in o.split('\n'), o)
    o = run('type ab', ktest.TAB, ktest.TAB)
    check('Tab again: the next name', 'three' in o.split('\n'), o)
    o = run('cd subd', ktest.TAB)
    check('Tab on a directory: with its \\', 'A:\\SUBDIR>' in o, o)
    run('cd ..')
    long = 'x' * 100
    o = run('echo ' + long, HOME, *([ktest.RIGHT] * 5), 'Y')
    check('a line over two rows: edited in the middle', ('Y' + long) in o.replace('\n', ''), o)
    run('echo nope', CTLC)
    o = k.pc.text_screen()
    check('Ctrl-C drops the line', 'echo nope^C' in o and 'nope' not in o.replace('echo nope', ''), o)
    lines = ['rem line %02d %s' % (i, 'x' * (i % 17)) for i in range(40)]  # ~1 KB: the history (over
    for l in lines: k.key(l); k.key(ktest.ENTER)                           #  LCMD's start-up code) wraps
    seen = []
    for i in range(20):
        k.key(ktest.UP); seen.append(k.pc.text_screen().rstrip().split('\n')[-1].split('>', 1)[-1].rstrip())
    k.key(ktest.ESC)
    check('the history after 1 KB of lines: Up recalls the newest 20, newest first, and the shell still runs',
          seen == [l.rstrip() for l in lines[::-1][:20]] and 'Lodestone version' in sh.run('ver'), seen)
    o = sh.run('lcmd < s.txt')
    check('standard input from a file: DOS line input, EXIT at its end', 'from a file' in o, o)
    o = sh.run('lcmd < s2.txt')
    check('... a file without EXIT: the shell ends at its end', 'no exit' in o and o.rstrip().endswith('A:\\>'), o)
    for f in ('longname.txt', 'ab1.txt', 'ab2.txt'): sh.run('del ' + f)
    k.key('exit'); k.key(ktest.ENTER)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    check('EXIT: the Executive', k.pc.mode() == 0x40, k.where())

def t_cmdshare():
    """The 2026-10-20 audit's LCMD batch: messages byte for byte with their
    new line from err, INT 24h's message for each code (counted out of one
    run of strings), buffers that share space, the built-ins as one table,
    .COM before .EXE before .BAT, PROMPT $D $T; DIR after a path that named
    a drive."""
    def bat(name, *lines):
        p = os.path.join(OUT, name)
        open(p, 'wb').write(('\r\n'.join(lines) + '\r\n').encode())
        return name + '=' + p
    src = os.path.join(OUT, 'CRITALL.ASM')        # INT 24h for each code, 0-16, writing drive A
    open(src, 'w').write('org 100h\n xor di,di\nl: mov ax,0100h\n push di\n int 24h\n pop di\n inc di\n'
                         ' cmp di,17\n jb l\n mov ax,4C00h\n int 21h\n')
    subprocess.run(['nasm', '-f', 'bin', '-o', os.path.join(OUT, 'CRITALL.COM'), src], check=True)
    img = image('share.img', os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(HERE, 'UPPER.COM'), os.path.join(GOS, 'src', 'CALC.COM'),
                os.path.join(OUT, 'CRITALL.COM'), 'T.COM=' + os.path.join(HERE, 'UPPER.COM'), 'SUB\\',
                bat('GO.BAT', '@echo off', 'type nosuch'), bat('T.BAT', '@echo off', 'echo the batch file'),
                bat('U.BAT', '@echo off', 'echo U is a batch file'))
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    fs = lambda: fatcheck.read_files(k.pc.drives[0].img)
    sh.run('echo hello > a.txt')
    sh.run('nosuch > e1.txt'); sh.run('call go > e2.txt'); sh.run('path ;'); sh.run('path > e3.txt')
    sh.run('copy a.txt sub > e4.txt'); sh.run('rd sub > e5.txt'); sh.run('dir sub > e6.txt')
    f = fs()
    check('messages byte for byte, each with its new line', (f.get('A:\\E1.TXT'), f.get('A:\\E2.TXT'), f.get('A:\\E3.TXT'),
          f.get('A:\\E4.TXT'), f.get('A:\\E5.TXT')) == (b'Bad command or file name\r\n', b'GO line 2: File not found\r\n',
          b'No Path\r\n', b'        1 File(s) copied\r\n', b'Invalid path, not directory,\r\nor directory not empty\r\n')
          and f.get('A:\\E6.TXT', b'').endswith(b' bytes free\r\n') and b'A        TXT' in f.get('A:\\E6.TXT', b''),
          [(n, f.get(n)) for n in sorted(f) if n.startswith('A:\\E')])
    check('... COPY into a directory with its output redirected (path1/path2 share in_name/out_name)', 'A:\\SUB\\A.TXT' in f, sorted(f))
    k.key('cls'); k.key(ktest.ENTER); k.key('critall'); k.key(ktest.ENTER)
    seen = []
    for i in range(17):
        L = k.pc.text_screen().rstrip().split('\n')
        seen.append(tuple(x.rstrip() for x in L[-3:]))
        k.key('f')
    msgs = ['Write protect error', 'Unknown unit error', 'Not ready error', 'Unknown command error', 'Data error', 'Bad request error',
            'Seek error', 'Unknown media type', 'Sector not found', 'Printer out of paper', 'Write fault', 'Read fault', 'General failure',
            'General failure', 'General failure', 'Invalid disk change', 'General failure']
    check("INT 24h: each code's message (15: Invalid disk change; 13, 14 and over 15: General failure), a new line "
          "before it", seen ==
          [('', m + ' writing drive A', 'Abort, Retry, Fail?') for m in msgs], seen)
    sh.run('dir a:')
    o = sh.run('dir')
    sh.run('copy a.txt sub\\b.txt')
    o2 = sh.run('dir')
    check('DIR after DIR A: or a COPY: the current drive (not a drive from what the buffer held before)',
          'Volume in drive A is LODESTONE' in o and 'Volume in drive A is LODESTONE' in o2 and o.count('bytes free') == 1, (o, o2))
    sh.run('dir sub')
    o = sh.run('calc 6*7')
    o2 = sh.run('type a.txt | upper > up.txt')
    check("a program's command tail after DIR (tail shares DIR's pattern); a pipe into a file after TYPE",
          '42' in o.split('\n') and fs().get('A:\\UP.TXT') == b'HELLO \r\n', (o, o2, fs().get('A:\\UP.TXT')))
    sh.run('copy a.txt *.bak'); sh.run('ren a.bak c.bak')
    o = sh.run('calc 1+2')
    check("COPY's and REN's names mapped (in the EXEC block's place), then a program", 'A:\\C.BAK' in fs() and '3' in o.split('\n'), (o, sorted(fs())))
    sh.run('path a:\\'); sh.run('cd sub')
    o = sh.run('calc 2+2')
    check('a program found on the PATH, then $P (CD and $P share the PATH walk\'s buffer)', '4' in o.split('\n')
          and o.rstrip().endswith('A:\\SUB>'), o)
    sh.run('cd ..')
    o = sh.run('cd q:')
    check('CD of a drive that isn\'t there', 'Invalid drive specification' in o, o)
    o = sh.run('dir c:') + sh.run('vol c:') + sh.run('dir q:\\x') + sh.run('vol q:') + sh.run('dir @:') + sh.run('vol @:')
    check('DIR and VOL of a drive that isn\'t there (C: with no hard disk, Q:, @:): DOS\'s "Invalid drive specification", '
          'no volume header', o.count('Invalid drive specification') == 6 and 'Volume' not in o and 'Directory of' not in o, o)
    o = sh.run('type nosuch.x') + sh.run('echo kept && if errorlevel 1 echo P1')
    o2 = sh.run('dir sub > nul && tasks || if errorlevel 1 echo T1')
    check('the built-ins: ECHO (the first that leaves ERRORLEVEL) keeps it, TASKS (the last that sets it) sets it',
          'P1' in o and 'Multitasking is off' in o2 and 'T1' in o2, (o, o2))
    outs = [sh.run(c) for c in ('erase nosuch', 'rename nosuch x', 'mkdir mk', 'chdir mk', 'chdir ..', 'rmdir mk', 'rmdir mk')]
    check('ERASE, RENAME, MKDIR, CHDIR, RMDIR: the same commands', 'File not found' in outs[0] and 'Duplicate file name' in outs[1]
          and 'A:\\MK>' in outs[3] and 'Invalid path' in outs[6] and 'Bad command' not in ''.join(outs), outs)
    o = sh.run('t < a.txt')
    o2 = sh.run('u')
    check('.COM before .BAT; a .BAT alone runs as a batch file', 'HELLO' in o and 'the batch file' not in o
          and 'U is a batch file' in o2, (o, o2))
    sh.run('date 1-2-27'); sh.run('time 9:05')
    sh.run('prompt $d $t$g')
    o = sh.run('rem')
    sh.run('prompt $p$g')
    check('PROMPT $D $T: "01-02-2027  9:05>"', o.rstrip().endswith('01-02-2027  9:05>'), o)
    deep = ''.join('\\' + c * 8 for c in 'ABCDEF') + '\\GGGGGG\\HH'   # as deep as CHDIR allows ("\" and 63, MS-DOS's)
    for c in ('AAAAAAAA', 'BBBBBBBB', 'CCCCCCCC', 'DDDDDDDD', 'EEEEEEEE', 'FFFFFFFF', 'GGGGGG'):
        sh.run('md ' + c); sh.run('cd ' + c)
    sh.run('md HH'); sh.run('cd HH')
    sh.run('echo hi > x.txt'); sh.run('echo DECOY > t')
    outs = [sh.run(c) for c in ('copy x.txt longname.txt', 'copy x.txt longname.tx', 'copy x*.txt *.bak')]
    o = sh.run('copy longname.txt longname.txt')
    sh.run('md s1234567'); sh.run('md s1234567\\s2345678'); sh.run('echo deep > s1234567\\s2345678\\big.dat')
    o3 = sh.run('copy s1234567\\s2345678\\big.dat s1234567\\s2345678\\..\\s2345678\\big.dat')
    sh.run('cd \\')
    f = fs()
    check("COPY from a 64-character directory (the deepest): COPY's two names checked (72-80 bytes) don't reach its source name",
          [f.get('A:' + deep + n) for n in ('\\LONGNAME.TXT', '\\LONGNAME.TX', '\\X.BAK')] == [b'hi \r\n'] * 3
          and all('1 File(s) copied' in o for o in outs), (outs, sorted(n for n in f if n.startswith('A:\\A'))))
    check("... and a file there copied onto itself (a 79-character name): refused as such", 'cannot be copied onto itself' in o, o)
    check("... and one two directories below it, named another way (its whole name 94 characters, past the 82 its check "
          "once had): refused as such, the file as it was", 'cannot be copied onto itself' in o3
          and f.get('A:' + deep + '\\S1234567\\S2345678\\BIG.DAT') == b'deep \r\n', (o3, f.get('A:' + deep + '\\S1234567\\S2345678\\BIG.DAT')))
    sh.run('cd ' + deep[:-3]); sh.run('md HHHHHHHH')
    o = sh.run('cd HHHHHHHH') + sh.run('cd')                       # 70 characters: refused (was cut to ...\HHH)
    sh.run('echo one > y1.txt')
    sh.run('cd HH'); sh.run('md IJ')
    o2 = sh.run('cd IJ') + sh.run('cd')                            # 67
    sh.run('echo two > y2.txt')
    sh.run('cd ' + deep[:-3])
    o3 = sh.run('cd HHHHHHHH\\..\\HH') + sh.run('cd')             # down past it and back: only the end counts
    sh.run('cd ' + deep[:-3])
    o4 = sh.run('cd HHHHHHHH\\..') + sh.run('cd')
    sh.run('md HHH')
    o5 = sh.run('cd HHH') + sh.run('cd')                           # 65: past MS-DOS's (Lodestone took it before)
    sh.run('cd \\')
    f = fs()
    check('CD a path that goes past 63 characters and comes back ("HHHHHHHH\\..\\HH"): the end is what counts, as MS-DOS',
          'Invalid directory' not in o3 + o4 and ('A:' + deep + '\n') in o3.replace('\r', '')
          and ('A:' + deep[:-3] + '\n') in o4.replace('\r', ''), (o3, o4))
    check('CD to a directory past 63 characters ("\\" and 63, MS-DOS\'s: 47h\'s 64 bytes): "Invalid directory", '
          'the current one kept (its name and its cluster: a file made next lands there)', 'Invalid directory' in o and ('A:' + deep[:-3] + '\n') in o.replace('\r', '')
          and 'Invalid directory' in o2 and ('A:' + deep + '\n') in o2.replace('\r', '')
          and f.get('A:' + deep[:-3] + '\\Y1.TXT') == b'one \r\n' and f.get('A:' + deep + '\\Y2.TXT') == b'two \r\n'
          and 'Invalid directory' in o5 and ('A:' + deep[:-3] + '\n') in o5.replace('\r', ''), (o, o2, o5, sorted(n for n in f if 'Y' in n)))
    sh.run('cd sub')
    outs = [sh.run('copy ?.txt ' + '.\\' * n + '????????.' + e) for n, e in ((34, 'BBK'), (51, 'CCK'))]   # 80 and 114 characters
    sh.run('md \\q'); sh.run('cd \\q'); sh.run('echo 1 > a'); sh.run('echo 2 > b')
    outs.append(sh.run('for %a in (' + '.\\' * 27 + ') do copy. %a%a.\\????????.DDK'))   # 122, the longest a line allows
    sh.run('cd \\')
    f = fs()
    check("COPY with wildcards to a destination of 80, 114 and 122 characters (past its buffer): every file",
          all(('A:\\SUB\\%s.%s' % (b, e)) in f for b in 'AB' for e in ('BBK', 'CCK'))
          and 'A:\\Q\\A.DDK' in f and 'A:\\Q\\B.DDK' in f
          and all('2 File(s) copied' in o for o in outs), (outs, sorted(n for n in f if n.startswith(('A:\\SUB', 'A:\\Q')))))
    # X29: a name found by a pattern in a 68- or 69-character directory runs past src's 79 characters;
    # COPY hung.  Now such a name is skipped and the rest copied (LONGNAME.TXT, 80, before LONGNAME.TX, 79)
    # (directories deeper than CD goes: made, and written in, by their paths)
    x29 = ''.join('\\' + c * 8 for c in 'ABCDEFG') + '\\HH'
    pre68, pre69 = 'A:' + x29[:-3] + '\\H\\', 'A:' + x29 + '\\'
    sh.run('md ' + x29[:-3]); sh.run('cd ' + x29[:-3]); sh.run('md h'); sh.run('md hh')    # (62: CD goes there)
    for n in ('h\\longname.txt', 'h\\longname.tx', 'hh\\longname.txt', 'hh\\longname.tx', 'hh\\abcdef.ghi'):
        sh.run('echo hi > ' + n)
    sh.run('cd \\')
    for pre, pat, got in ((pre68, 'longname.*', ['LONGNAME.TX']), (pre68, '*.txt', []), (pre69, '*.tx', []), (pre69, 'l*.txt', [])):
        f = fs()
        back = run_long(k, 'copy %s%s \\q' % (pre, pat), 6)      # (a hang: no prompt in 6 s)
        o = k.pc.text_screen()
        check('COPY %s%s to a directory: %s (directory part %d, names over %d characters skipped), the total, the prompt back'
              % (pre, pat, ', '.join(got) or 'nothing copied', len(pre), 79 - len(pre)), back and not k.crashed
              and set(fs()) - set(f) == {'A:\\Q\\' + n for n in got} and '%d File(s) copied' % len(got) in o
              and 'File not found' not in o, (back, k.where(), o))
        if not back: return
    k.trace = True; k.dos.clear()
    o = sh.run('ren %sl*.txt x.y' % pre69)
    r1 = [e[5] for e in k.dos if e[0] == 0x56]; k.dos.clear()
    o2 = sh.run('ren %sa*.* l.y' % pre69)
    r2 = [e[5] for e in k.dos if e[0] == 0x56]; k.trace = False
    f = fs()
    check('... REN %sl*.txt (LONGNAME.TXT: 81 characters): "Duplicate file name", no rename asked of DOS; a*.* (ABCDEF.GHI: '
          '79): renamed' % pre69, 'Duplicate file name' in o and not r1 and len(r2) == 1 and 'A:' + x29 + '\\L.Y' in f
          and 'A:' + x29 + '\\LONGNAME.TXT' in f and 'A:' + x29 + '\\X.Y' not in f, (o, r1, o2, r2))
    k.key('exit'); k.key(ktest.ENTER)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    probs, files = fatcheck.check(bytes(k.pc.drives[0].img))
    check('back in the Executive, disk consistent', k.pc.mode() == 0x40 and not probs, probs)
    # X43: a COMSPEC of 80 characters lost its NUL in prog2, and MT_SPAWN got it and the tail as its path
    k = ktest.KPC(ini_image('sharemt.img', b'MULTITASK=1\r\n', os.path.join(GOS, 'src', 'LCMD.COM'),
                            'LODEMT.SYS=' + os.path.join(GOS, 'src', 'LODEMT.SYS'), bat('TB.BAT', '@echo off', 'echo ran > tb.txt')),
                  ems_pages=88)
    k.start(10)
    sh = Shell(k)
    ds = [c * 8 for c in 'ABCDEF'] + ['GGGG', 'HHHH']                  # (63 characters)
    for i in range(len(ds)): sh.run('md \\' + '\\'.join(ds[:i + 1]))
    sh.run('md \\' + '\\'.join(ds) + 'H')
    outs = []
    for h in ('HHHHH', 'HHHH'):
        c = 'A:\\' + '\\'.join(ds[:-1] + [h]) + '\\LCMDLCMD.COM'
        sh.run('copy lcmd.com ' + c); sh.run('set comspec=' + c)
        o = sh.run('start /w tb.bat'); k.run_for(2)
        outs.append((len(c), 'Bad command or file name' in o, 'A:\\TB.TXT' in fs(), o))
    check('START of a batch file with a COMSPEC of 80 characters: "Bad command or file name", nothing started; of 79: '
          'it runs', [x[:3] for x in outs] == [(80, True, False), (79, False, True)] and not k.crashed, outs)

def t_cmdsaver():
    """The Executive's screen saver at the prompt (and in PAUSE): DEFRAG,
    the dark screen, then the prompt as it was; the Executive's memory
    as before afterwards."""
    img = image('csv.img', os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(GOS, 'src', 'DEFRAG.COM'))
    k = ktest.KPC(img); k.start()
    k.wr('saver_t', struct.pack('<H', 36))          # 2 s instead of 5 minutes
    sh = Shell(k)
    psp = k.pc.u16(0x60, k.Y['cur_psp'])
    k.key('echo kept')
    seen = set()
    for _ in range(60):
        k.pc.run_for(0.25)
        seen.add(k.pc.mode())
        if k.pc.mode() == 0x40 and any(':' in l and l.strip().endswith('m') for y, l in k.ocr()): break
    dark = [l.strip() for y, l in k.ocr() if len(l.strip()) > 2]
    check('2 s idle at the prompt: the saver (DEFRAG ran, then the dark screen)', k.pc.mode() == 0x40 and len(dark) == 2, (seen, dark))
    check('... the Executive lent its memory once more, no more', k.rd('lent', 1) == b'\x02' or k.rd('lent', 1) == b'\x01', k.rd('lent', 1))
    k.key(ktest.DOWN)
    scr = k.pc.text_screen()
    check('a key: the prompt back as it was, the key taken', k.pc.mode() == 3 and 'A:\\>echo kept' in scr and 'command shell' in scr, scr)
    check('... the Executive lends its memory once, as before', k.rd('lent', 1) == b'\x01', k.rd('lent', 1))
    v24 = k.pc.u16(0, 0x92)
    check('... LCMD\'s INT 24h again', v24 == psp, (hex(v24), hex(psp)))
    k.key(ktest.ENTER)
    check('... and the line still runs', 'kept' in k.pc.text_screen().split('\n'), k.pc.text_screen())
    k.key('pause'); k.key(ktest.ENTER)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 8)
    in_pause = k.pc.mode() == 0x40
    k.key(ktest.DOWN)
    k.pc.run_for(0.5)
    check('PAUSE: the saver too; its key wakes it, PAUSE goes on waiting', in_pause and k.pc.mode() == 3 and
          'Strike a key' in k.pc.text_screen() and k.pc.halted, k.pc.text_screen())
    k.key(ktest.ENTER)
    k.key('exit'); k.key(ktest.ENTER)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    check('EXIT: the Executive with its directory back', k.pc.mode() == 0x40 and k.rd('lent', 1) == b'\x00'
          and 'LCMD.COM' in k.exec_list() and 'DEFRAG.COM' in k.exec_list(), (k.rd('lent', 1), k.exec_list()))
    # the start-up floppy taken out at the prompt (the change line stays on, reads time out): the saver's
    # look for A:\DEFRAG.COM fails without LCMD's "Abort, Retry, Fail?", the dark screen as in the Executive
    k = ktest.KPC(img); k.start()
    k.wr('saver_t', struct.pack('<H', 36))
    Shell(k)
    orig, st = type(k.pc).int13, {'out': True, 'n': 0}
    def int13(s):
        if st['out'] and s.r('dl') == 0 and s.r('ah') in (2, 3, 4, 0x16):
            st['n'] += s.r('ah') != 0x16                # (reads tried, not the change line's looks)
            s.w('ax', 0x0600 if s.r('ah') == 0x16 else 0x8000); s.cf(1); return
        return orig(s)
    type(k.pc).int13 = int13
    try:
        n0 = len(k.pc.tty)
        for _ in range(60):
            k.pc.run_for(0.25)
            if 'Fail?' in ''.join(k.pc.tty)[n0:]: break
            if k.pc.mode() == 0x40 and any(':' in l and l.strip().endswith('m') for y, l in k.ocr()): break
        dark = [l.strip() for y, l in k.ocr() if len(l.strip()) > 2] if k.pc.mode() == 0x40 else []
        q = ''.join(k.pc.tty)[n0:]
        check('A: taken out at the prompt: the saver looks for DEFRAG there, fails without a question, the dark screen',
              st['n'] and 'Fail?' not in q and len(dark) == 2, (st['n'], q, dark))
        k.key(ktest.DOWN)
        back = k.pc.mode() == 3
        n0 = len(k.pc.tty)
        k.key('pause && dir'); k.key(ktest.ENTER)
        k.pc.run_until(lambda: k.pc.mode() == 0x40, 8)
        in_pause = k.pc.mode() == 0x40
        k.key(ktest.DOWN); k.pc.run_for(0.5); k.key(ktest.ENTER)
        q = ''.join(k.pc.tty)[n0:]
        check('... a key: the prompt back; "pause && dir": the saver in PAUSE without a question, then DIR of A: asks (the '
              'rest of the line as before the saver)', back and in_pause and q.count('Fail?') == 1, (back, in_pause, q))
        k.key('f')
    finally:
        type(k.pc).int13 = orig

def t_calc():
    """CALC.COM (0.4.4): sums at the prompt, errors with ERRORLEVEL, name=
    for batch files (only into LCMD's environment), the 80287's own code
    paths (a build that treats the emulator's 287XL as an 80287), and
    whole numbers when there is no coprocessor."""
    import math
    def bat(name, *lines):
        p = os.path.join(OUT, name)
        open(p, 'wb').write(('\r\n'.join(lines) + '\r\n').encode())
        return name + '=' + p
    c287 = os.path.join(OUT, 'CALC287.COM')
    subprocess.run(['nasm', '-f', 'bin', '-DCALC_287', '-i', os.path.join(GOS, 'src') + '/', '-o', c287,
                    os.path.join(GOS, 'src', 'CALC.ASM')], check=True)
    img = image('calc.img', os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(GOS, 'src', 'CALC.COM'),
                'CALC287.COM=' + c287, os.path.join(HERE, 'RUNCALC.COM'),
                bat('COUNT.BAT', '@echo off', 'set i=0', ':loop', 'calc i=i+1', 'if not %i%==3 goto loop', 'echo counted %i%'),
                bat('PCT.BAT', '@echo off', 'calc 7%%2'))
    def res(o):     # the lines it printed, without the prompt after them
        return [l.strip() for l in o.split('\n') if l.strip() and not re.match(r'[A-Z]:\\.*>$', l.strip())]
    def one(o):
        r = res(o)
        return r[0] if len(r) == 1 else r
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    for e, want in (('4*4', '16'), ('2+3*4', '14'), ('-2^2', '-4'), ('2^10', '1024'), ('2^-1', '0.5'), ('1/3', '0.333333333333333'),
                    ('7\\2', '3'), ('7%2', '1'), ('-7\\2', '-3'), ('/d sin(30)', '0.5'), ('sqrt(2)', '1.4142135623731'),
                    ('1000', '1000'), ('0.001', '0.001'), ('1E15', '1E+15'), ('999999999999999.9', '1E+15'),
                    ('0.1+0.2', '0.3'), ('1E-6', '1E-06'), ('(1+2)*(3+4)', '21'), ('1e400/1e399', '10'),
                    ('+5', '5'), ('0^0.5', '0'), ('abcdefghijklmno=7', '7')):
        o = sh.run('calc ' + e)
        check('CALC %s = %s' % (e, want), one(o) == want, o)
    # degrees: reduced by 45 before radians, so the zeros are exact, on either chip (the persona review)
    DEG = (('/d cos(90)', '0'), ('/d sin(180)', '0'), ('/d tan(180)', '0'), ('/d sin(-360)', '0'), ('/d cos(-270)', '0'),
           ('/d tan(45)', '1'), ('/d sin(-270)', '1'), ('/d cos(360)', '1'), ('/d cos(60)', '0.5'), ('/d sin(150)', '0.5'),
           ('/d tan(-45)', '-1'), ('/d sin(45)^2', '0.5'))
    for e, want in DEG:
        o = sh.run('calc ' + e)
        check('CALC %s = %s' % (e, want), one(o) == want, o)
    for e, want in (('/d sin(1E6)', math.sin(math.radians(280))), ('/d cos(1234.5)', math.cos(math.radians(1234.5))),
                    ('/d tan(-100)', math.tan(math.radians(-100)))):
        o = sh.run('calc ' + e)
        try: got = float(one(o))
        except (ValueError, TypeError): got = None
        check('CALC %s = %.12g' % (e, want), got is not None and abs(got - want) <= 1e-12 * max(1, abs(want)), o)
    for e, msg in (('1/0', 'Divide by zero'), ('(', 'Syntax error'), ('sqrt(-1)', 'Not a number'), ('ln(0)', 'Not a number'),
                   ('log(-1)', 'Not a number'), ('nosuch+1', 'Unknown name: NOSUCH'), ('1e5000', 'Too big'),
                   ('0^-0.5', 'Divide by zero'), ('sin(1e5000)', 'Too big'), ('(1/0)%3', 'Divide by zero'),
                   ('/d tan(90)', 'Divide by zero'), ('abcdefghijklmnop=1', 'Name too long: ABCDEFGHIJKLMNO'),
                   ('1+abcdefghijklmnop', 'Name too long: ABCDEFGHIJKLMNO')):
        o = sh.run('calc %s || echo EL' % e)
        check('CALC %s: "%s", ERRORLEVEL 1' % (e, msg), 'CALC: ' + msg in o and 'EL' in res(o), o)
    o = sh.run('set')
    check('... a name cut short is never set (ABCDEFGHIJKLMNO=7 is the 15-letter one)',
          'ABCDEFGHIJKLMNO=7' in res(o) and not any(l.startswith('ABCDEFGHIJKLMNO=1') for l in res(o)), o)
    sh.run('set abcdefghijklmno=')
    sh.run('set v=' + '1' * 32)
    o = sh.run('calc v+1 || echo EL')
    check('a variable longer than 31 characters: "Value too long: V", not a smaller number', 'CALC: Value too long: V' in o
          and 'EL' in res(o), o)
    sh.run('set v=' + '0' * 29 + '42')
    o = sh.run('calc v+1')
    check('... 31 characters: read whole', one(o) == '43', o)
    sh.run('set v=')
    o = sh.run('calc 6*7 && echo EL0')
    check('a sum: ERRORLEVEL 0', res(o) == ['42', 'EL0'], o)
    from unicorn.x86_const import UC_X86_REG_FPSW
    sh.run('calc 1/3')
    fpsw = k.pc.mu.reg_read(UC_X86_REG_FPSW)
    check('... and the coprocessor left as FNINIT leaves it, status word 0 (pcemu sets no precision flag, but CALC\'s'
          ' last compare leaves C0; on the 1520 1/3 also leaves PE, sticky for the next program)', fpsw == 0, hex(fpsw))
    o = sh.run('calc || echo EL')
    check('CALC alone: how to use it, and the coprocessor (pcemu\'s is 387-class: a 287XL); ERRORLEVEL 1',
          'CALC [/D] [name=]expression' in o and 'Coprocessor: 80287XL' in o and 'EL' in res(o), o)
    o = sh.run('calc /x > bad.txt || echo EL')
    check('a wrong switch: the same on standard error (not into > file), ERRORLEVEL 1',
          'CALC [/D] [name=]expression' in o and 'EL' in res(o) and res(sh.run('type bad.txt')) == [], o)
    o = sh.run('calc /? > help.txt && echo EL0')
    check('CALC /?: on standard output, ERRORLEVEL 0', res(o) == ['EL0'] and 'CALC [/D] [name=]expression' in sh.run('type help.txt'),
          o)
    sh.run('calc 6*7 > six.txt')
    o = sh.run('type six.txt')
    check('redirected to a file', one(o) == '42', o)
    sh.run('set n=41')
    o = sh.run('calc n=n+1')
    check('CALC n=n+1: names are variables, name= sets one', one(o) == '42' and 'N=42' in res(sh.run('set')), sh.run('set'))
    o = sh.run('calc n=n*2')
    check('... again, replacing it', one(o) == '84' and 'N=84' in res(sh.run('set')) and 'N=42' not in res(sh.run('set')), sh.run('set'))
    o = sh.run('count')
    check('a batch file counts with CALC i=i+1', res(o) == ['1', '2', '3', 'counted 3'], o)
    o = sh.run('pct')
    check('in a batch file %% is %', one(o) == '1', o)
    # LCMD's environment nearly full (the review's cases)
    def env():
        psp = k.pc.u16(0x60, k.Y['cur_psp'])
        b = k.pc.rd(k.pc.u16(psp, 0x2C), 0, 1024)
        i = 0
        while b[i]: i = b.index(0, i) + 1
        return b[:i]
    pads = []
    def pad_to(n):
        d = n - len(env())
        while d > 0:
            m = min(100, d - 4)
            if 0 < d - (m + 4) < 5: m -= 5
            sh.run('set q%s=%s' % (chr(97 + len(pads)), 'x' * m)); pads.append(chr(97 + len(pads)))
            d -= m + 4
    sh.run('set n=1')
    pad_to(1000)
    o = sh.run('runcalc')
    check("a parent whose copy of the environment is LCMD's size (1 KB): not written (its copy ends in 0001h and its name)",
          len(env()) == 1000 and '5' in res(o) and '[N=1]' in o and '[N=5]' not in o, (len(env()), o))
    check("... and CALC says so after the answer, ERRORLEVEL 1 (a batch file's count can't stall silently)",
          'CALC: name= works only at the command prompt' in o and '(EL1)' in o, o)
    pad_to(1016)
    o = sh.run('calc n=n+1')
    check('... nearly full, CALC n=n+1 still fits', one(o) == '2' and b'N=2' + bytes(1) in env() and len(env()) == 1016, (o, len(env())))
    o = sh.run('calc n=123456789 || echo EL')
    check('... full: "Out of environment space", ERRORLEVEL 1, and N as it was',
          'CALC: Out of environment space' in o and 'EL' in res(o) and b'N=2' + bytes(1) in env() and len(env()) == 1016, (o, env()[-40:]))
    # SET the same way: a new value that fits only once the old one is out
    # is taken; one that doesn't fit even then leaves the old one (SET
    # used to take it out first, then find no room)
    sh.run('set n=1234567')
    check('... SET N= a value that fits in place of the old one', b'N=1234567' + bytes(1) in env() and len(env()) == 1022, env()[-40:])
    o = sh.run('set n=12345678 || echo EL')
    check('... SET N= one too long even then: "Out of environment space", ERRORLEVEL 1, and N as it was',
          'Out of environment space' in o and 'EL' in res(o) and b'N=1234567' + bytes(1) in env() and len(env()) == 1022, (o, env()[-40:]))
    for c in pads: sh.run('set q%s=' % c)
    # found on the 1520: a real 80287's FNINIT leaves C0-C3 as they were,
    # and fpu_detect wanted the whole status word 0 (the -DCALC_287 build
    # sets them after FNINIT, as the 80287 may)
    o = sh.run('calc287 /?')
    check('an 80287 that leaves C0-C3 set after FNINIT is still found ("Coprocessor: 80287")',
          'Coprocessor: 80287' in o and 'Coprocessor: 80287XL' not in o, o)
    # the 80287's paths: FPREM, FPTAN, FPATAN, F2XM1, FYL2X, kept in range
    for e, want in (('sin(1)', math.sin(1)), ('cos(2)', math.cos(2)), ('tan(1.5)', math.tan(1.5)), ('sin(-100)', math.sin(-100)),
                    ('cos(1234.5)', math.cos(1234.5)), ('tan(-3)', math.tan(-3)), ('atan(3)', math.atan(3)),
                    ('atan(-0.25)', math.atan(-0.25)), ('exp(-0.7)', math.exp(-0.7)), ('ln(10)', math.log(10)),
                    ('log(2)', math.log10(2)), ('2^0.5', 2 ** 0.5), ('1.5^-3.7', 1.5 ** -3.7), ('/d tan(45)', 1.0),
                    ('/d atan(1)', 45.0), ('sin(0)', 0.0), ('atan(1)*4', math.pi), ('-7.5%2', -1.5), ('7.5\\2', 3.0)):
        o = sh.run('calc287 ' + e)
        try: got = float(one(o))
        except (ValueError, TypeError): got = None
        check('80287 path: %s = %.12g' % (e, want), got is not None and abs(got - want) <= 1e-12 * max(1, abs(want)), o)
    for e, msg in (('sin(1/0)', 'Divide by zero'), ('(1/0)%3', 'Divide by zero'), ('sin(1e5000)', 'Too big')):
        o = sh.run('calc287 ' + e)
        check('80287 path: %s: "%s" (no FPREM on an infinity)' % (e, msg), 'CALC: ' + msg in o, o)
    for e, want in DEG:
        o = sh.run('calc287 ' + e)
        check('80287 path: %s = %s, as on the 287XL' % (e, want), one(o) == want, o)
    k.key('exit'); k.key(ktest.ENTER)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    out = k.run_file('RUNCALC.COM', 20)
    check('name= with a parent that isn\'t LCMD: the answer, its environment untouched, ERRORLEVEL 1 and why',
          '5' in out.split('\r\n') and '[N=' not in out and '[PATH=' in out and '(EL1)' in out
          and 'CALC: name= works only at the command prompt' in out, out)
    # no coprocessor (INT 11h says none): whole numbers
    k.pc.wr(0, 0x410, struct.pack('<H', k.pc.u16(0, 0x410) & ~2))
    sh = Shell(k)
    sh.run('set n=42')
    for e, want in (('6/2', '3'), ('7\\2', '3'), ('2^30', '1073741824'), ('-2147483647-1', '-2147483648'), ('n+1', '43')):
        o = sh.run('calc ' + e)
        check('no coprocessor: CALC %s = %s' % (e, want), one(o) == want, o)
    for e, msg in (('7/2', 'Needs an 80287'), ('1.5', 'Needs an 80287'), ('sqrt(4)', 'Needs an 80287'), ('2^31', 'Too big'),
                   ('46341*46341', 'Too big')):
        o = sh.run('calc ' + e)
        check('no coprocessor: CALC %s: "%s"' % (e, msg), 'CALC: ' + msg in o, o)
    o = sh.run('calc')
    check('no coprocessor: CALC alone says so', 'Coprocessor: none: whole numbers only' in o, o)
    # a full disk: the answer can't be written, so ERRORLEVEL 1 and why, not an empty file and 0 (the persona review)
    fimg = image('calcfull.img', os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(GOS, 'src', 'CALC.COM'))
    d = subprocess.run(['mdir', '-i', fimg, '::'], capture_output=True, text=True, check=True).stdout
    free = int(re.sub(r'\D', '', re.search(r'([\d ]+) bytes free', d).group(1)))
    filler = os.path.join(OUT, 'FILLER.BIN'); open(filler, 'wb').write(bytes(free))
    subprocess.run(['mcopy', '-i', fimg, filler, '::FILLER.BIN'], check=True)
    k = ktest.KPC(fimg); k.start()
    sh = Shell(k)
    o = sh.run('calc 6*7 > full.txt || echo EL')
    check("a full disk: \"CALC: Can't write the answer\", ERRORLEVEL 1", "CALC: Can't write the answer" in o and 'EL' in res(o), o)

def t_execabort():
    """A disk error while EXEC loads a program, answered Abort: the program never ran, so the EXEC fails (as Fail)
    and its caller goes on.  It ended the caller instead (LCMD), and the blocks EXEC had given the program (for a
    .COM, the largest free one) and its file stayed taken: the Executive had no room left to list the disk."""
    com = os.path.join(OUT, 'BIG.COM')
    code = bytes([0xB4, 0x09, 0xBA, 0x08, 0x01, 0xCD, 0x21, 0xC3]) + b'HELLO$'
    open(com, 'wb').write(code + b'Q' * (4096 - len(code)))
    badx = os.path.join(OUT, 'BADX.EXE')            # a header bigger than the file: EXEC says 11 (bad format)
    open(badx, 'wb').write((b'MZ' + struct.pack('<4H', 88, 2, 0, 0x40)).ljust(600, b'\0'))
    k = ktest.KPC(image('exabort.img', os.path.join(GOS, 'src', 'LCMD.COM'), com, os.path.join(HERE, 'UPPER.COM'), badx, SCR))
    k.start()
    pc, d = k.pc, k.pc.drives[0]
    def lbas(name):                     # the file's sectors (1.44 MB FAT12)
        img, out = bytes(d.img), []
        for i in range(224):
            e = img[19 * 512 + i * 32:19 * 512 + i * 32 + 32]
            if e[:11] == name:
                cl = e[26] | e[27] << 8
                while 2 <= cl < 0xFF8:
                    out.append(33 + cl - 2)
                    v = img[512 + cl * 3 // 2] | img[512 + cl * 3 // 2 + 1] << 8
                    cl = v >> 4 if cl & 1 else v & 0xFFF
        return out
    def arena():                        # the MCBs, free neighbours merged
        seg, out = k.u16('first_mcb'), []
        while len(out) < 200:
            t, own, sz = chr(pc.rd(seg, 0, 1)[0]), pc.u16(seg, 1), pc.u16(seg, 3)
            if out and own == 0 and out[-1][1] == 0: out[-1] = (out[-1][0], 0, out[-1][2] + sz + 1)
            else: out.append((seg, own, sz))
            if t != 'M': break
            seg += sz + 1
        return out
    def refs(): return [pc.rd(0x60, k.Y['sft'] + i * 44, 1)[0] for i in range(24)]
    sec = lbas(b'BIG     COM')
    k.code_p()
    k.key('ver'); k.key(ktest.ENTER)
    a0, r0 = arena(), refs()
    # Retry is no answer that says why EXEC fails: BADX's header unreadable, then read on Retry, then bad: said
    d.bad = {lbas(b'BADX    EXE')[0]}
    k.key('cls'); k.key(ktest.ENTER)
    k.key('badx'); k.key(ktest.ENTER, settle=False)
    pc.run_until(lambda: 'Fail?' in pc.text_screen() or pc.crash, 10)
    o1 = pc.text_screen()
    d.bad = set()
    pc.keys.append(ord('r')); k.settle()
    o = pc.text_screen()
    check('a read error in BADX.EXE\'s header answered Retry, then the header bad: "Bad command or file name" all the same',
          'Fail?' in o1 and 'Bad command or file name' in o, (o1[-200:], o))
    # (the header first: once read, a sector buffer keeps it, and the image's read from 0 hits it instead)
    for what, bad, key in (('its header', sec[0], 'a'), ('its image', sec[1], 'a'), ('its image', sec[1], 'f')):
        d.bad = {bad}
        k.key('cls'); k.key(ktest.ENTER)
        k.key('big'); k.key(ktest.ENTER, settle=False)
        pc.run_until(lambda: 'Fail?' in pc.text_screen() or pc.crash, 10)
        o1 = pc.text_screen()
        given = arena() != a0           # (the header's read comes before EXEC gives it memory, the image's after)
        d.bad = set()
        check('... %s: the error comes %s EXEC gives the program its memory' % (what, 'before' if bad == sec[0] else 'after'),
              given == (bad != sec[0]), (what, arena(), a0))
        pc.keys.append(ord(key)); k.settle()
        o = pc.text_screen().rstrip()
        check('a read error in %s while LCMD runs BIG.COM, answered %s: LCMD\'s prompt again, nothing more said, '
              'memory and the files as before' % (what, 'Abort' if key == 'a' else 'Fail'),
              'Data error reading drive A' in o1 and pc.mode() == 3 and o.endswith('A:\\>') and 'Bad command' not in o
              and o.count('Data error') == 1 and 'HELLO' not in o and arena() == a0 and refs() == r0 and not k.crashed,
              (o1[-200:], o, arena(), a0, refs(), r0))
    # the next EXEC that fails otherwise says why (nothing kept from the answer before)
    k.key('cls'); k.key(ktest.ENTER)
    k.key('badx'); k.key(ktest.ENTER)
    check('... then BADX.EXE: "Bad command or file name"', 'Bad command or file name' in pc.text_screen(), pc.text_screen())
    # once a program runs, Abort ends it again (EXEC's flag not left set): UPPER reading BIG.COM's bad sector
    d.bad = {sec[1]}
    k.key('cls'); k.key(ktest.ENTER)
    k.key('upper < big.com > nul'); k.key(ktest.ENTER, settle=False)
    pc.run_until(lambda: 'Fail?' in pc.text_screen() or pc.crash, 10)
    o1 = pc.text_screen()
    d.bad = set()
    pc.keys.append(ord('a')); k.settle()
    check('... then a program that runs, answered Abort on its own read: it ends (a critical error, last_exit AH 2)',
          'Fail?' in o1 and k.u16('last_exit') >> 8 == 2 and pc.text_screen().rstrip().endswith('A:\\>'),
          (o1[-200:], hex(k.u16('last_exit'))))
    k.key('cls'); k.key(ktest.ENTER)
    k.key('big'); k.key(ktest.ENTER)
    check('... then it reads: BIG.COM runs', 'HELLO' in pc.text_screen(), pc.text_screen())
    # K2: EXEC's buffers (ex_name, ex_rel, the header) are in the INT 21h stack's low area, where a screen capture
    # puts its buffer: Shift-PrtSc at the prompt of an error inside EXEC, answered Retry.  The capture waits for
    # the next outermost DOS call (the handler's own calls are nested), after EXEC: both whole
    d.bad = {sec[1]}
    k.key('cls'); k.key(ktest.ENTER)
    k.key('big'); k.key(ktest.ENTER, settle=False)
    pc.run_until(lambda: 'Fail?' in pc.text_screen() or pc.crash, 10)
    o1 = pc.text_screen()
    pc.prtsc(); pc.run_for(0.5)
    d.bad = set()
    pc.keys.append(ord('r')); k.settle(3)
    o = pc.text_screen()
    shots = [n for n in fatcheck.read_files(d.img) if 'SCREEN0' in n]
    check('Shift-PrtSc at the prompt of an error inside EXEC (K2: the low area), answered Retry: BIG.COM loads and runs '
          'whole, and the screen is saved after (SCREEN01.TXT)', 'Fail?' in o1 and 'HELLO' in o and shots == ['A:\\SCREEN01.TXT']
          and not k.crashed, (o[-300:], shots))
    k.key('exit'); k.key(ktest.ENTER)
    check('... and the Executive lists the disk once LCMD ends', 'BIG.COM' in k.exec_list() and 'LCMD.COM' in k.exec_list(),
          k.exec_list())

def t_execnest():
    """An INT 24h handler's own DOS call while EXEC loads (NEST24.COM): its read's error, answered Abort, fails, as
    BIG.COM's then does: "EXEC loads" is the outer call's (4Bh), not the nested call's (3Fh) whose frame BP holds.
    NEST24 goes on and says both errors; memory as before."""
    com = os.path.join(OUT, 'NEST24.COM')
    subprocess.run(['nasm', '-f', 'bin', '-o', com, os.path.join(HERE, 'NEST24.ASM')], check=True)
    big = os.path.join(OUT, 'NBIG.COM')
    code = bytes([0xB4, 0x09, 0xBA, 0x08, 0x01, 0xCD, 0x21, 0xC3]) + b'HELLO$'
    open(big, 'wb').write(code + b'Q' * (4096 - len(code)))
    x = os.path.join(OUT, 'NX.DAT'); open(x, 'wb').write(b'x' * 1024)
    k = ktest.KPC(image('exnest.img', os.path.join(GOS, 'src', 'LCMD.COM'), 'NEST24.COM=' + com, 'BIG.COM=' + big,
                        'X.DAT=' + x))
    k.start()
    pc, d = k.pc, k.pc.drives[0]
    def first(name):                    # a file's first sector (1.44 MB FAT12)
        img = bytes(d.img)
        for i in range(224):
            e = img[19 * 512 + i * 32:19 * 512 + i * 32 + 32]
            if e[:11] == name: return 33 + (e[26] | e[27] << 8) - 2
    def arena():                        # the MCBs, free neighbours merged
        seg, out = k.u16('first_mcb'), []
        while len(out) < 200:
            t, own, sz = chr(pc.rd(seg, 0, 1)[0]), pc.u16(seg, 1), pc.u16(seg, 3)
            if out and own == 0 and out[-1][1] == 0: out[-1] = (out[-1][0], 0, out[-1][2] + sz + 1)
            else: out.append((seg, own, sz))
            if t != 'M': break
            seg += sz + 1
        return out
    k.code_p()
    k.key('ver'); k.key(ktest.ENTER)
    a0 = arena()
    d.bad = {first(b'BIG     COM') + 1, first(b'X       DAT')}
    k.key('cls'); k.key(ktest.ENTER)
    k.key('nest24'); k.key(ktest.ENTER)
    o = pc.text_screen()
    m = re.search(r'exec ([0-9A-F]{4}) read ([0-9A-F]{4})', o)
    d.bad = set()
    check('NEST24: the nested read\'s Abort fails (an error back), BIG.COM\'s fails the EXEC; NEST24 ends itself '
          '(exit 0), memory as before',
          m and m.group(1) not in ('FFFF', '0000') and m.group(2) not in ('FFFF', '0000') and k.u16('last_exit') == 0
          and 'HELLO' not in o and o.rstrip().endswith('A:\\>') and arena() == a0 and not k.crashed,
          (o[-200:], hex(k.u16('last_exit')), arena(), a0))

def t_cmdword():
    """LCMD's command word is kept to 70 characters (cword): a program named by a path of exactly 70 gets its
    arguments, not the path's last character in front of them (LCMD took SI back one at the 70th as at a word's
    end).  START reads its program's name the same way (get_word)."""
    tail = os.path.join(OUT, 'TAILPRG.COM')        # its command tail to standard output
    open(tail, 'wb').write(bytes([0x8A, 0x0E, 0x80, 0x00, 0x32, 0xED, 0xBA, 0x81, 0x00, 0xBB, 0x01, 0x00, 0xB4, 0x40, 0xCD, 0x21, 0xC3]))
    dirs = [c * 8 for c in 'ABCDEF'] + ['G']
    files = ['\\'.join(dirs[:i + 1]) + '\\' for i in range(len(dirs))]
    img = image('cmdword.img', os.path.join(GOS, 'src', 'LCMD.COM'), *files, '\\'.join(dirs) + '\\TAILPRG.COM=' + tail)
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    p = 'A:\\' + '\\'.join(dirs) + '\\TAILPRG.COM'
    assert len(p) == 70
    sh.run(p.lower() + ' hello > t.txt')
    t = fatcheck.read_files(k.pc.drives[0].img).get('A:\\T.TXT')
    check('a program named by a path of 70 characters ("%s hello"): its tail is " hello" (%r)' % (p, t),
          t is not None and t.strip() == b'hello', t)

TESTS = [t_emsboard, t_noems, t_ems, t_dosapi, t_tm5000g, t_shell, t_tabs, t_disks, t_permanent, t_capture, t_print, t_cache, t_cache_ems, t_mdisk,
         t_mdreview, t_lodeboot, t_gridgpib, t_gpcheck0, t_gpirq, t_exerel, t_trunc, t_dollar, t_kmedium, t_renfull, t_fatstraddle, t_names, t_nul, t_devname, t_fcbnames, t_spacenames, t_copycat, t_wpfail, t_mount, t_chg06, t_mntback, t_swaps, t_cwdfind, t_batswap, t_newname, t_nomatch, t_slashend, t_dirlong, t_attr, t_errs, t_nodisk, t_execabort, t_execnest, t_cmdword, t_command, t_cmdedit, t_cmdshare, t_cmdsaver, t_calc]
if __name__ == '__main__':
    want = [w[2:] if w.startswith('t_') else w for w in sys.argv[1:]]       # (shell or t_shell)
    if set(want) - {t.__name__[2:] for t in TESTS}:
        sys.exit('no such test: %s' % ' '.join(sorted(set(want) - {t.__name__[2:] for t in TESTS})))
    build()
    for t in TESTS:
        if want and t.__name__[2:] not in want: continue
        print('==', t.__name__[2:])
        t0 = time.time(); t(); print('   (%.1f s)' % (time.time() - t0))
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s' % (len(results), len(bad), (': ' + ', '.join(bad)) if bad else ''))
    sys.exit(1 if bad else 0)
