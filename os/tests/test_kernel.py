"""Lodestone 0.2 kernel tests in pcemu: the DOS API suite, a FAT check of the
disk afterwards, TM5000G run and return with the built-in GPIB.

    python3 tests/test_kernel.py [name ...]
"""
import os, re, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, fatcheck, sim7210
OUT = os.environ.get('KOUT', os.path.join(__import__('tempfile').gettempdir(), 'lodestone-kt'))
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
    for d, n in ((HERE, 'TESTDOS'), (HERE, 'UPPER'), (HERE, 'CACHETST'), (HERE, 'EMSTEST'), (HERE, 'MEMSZ'), (HERE, 'CAPTEST'), (HERE, 'MDTEST'),
                 (HERE, 'RUNCALC'), (os.path.join(GOS, 'src'), 'LCMD'), (os.path.join(GOS, 'src'), 'CALC')):
        subprocess.run(['nasm', '-f', 'bin', '-i', d + '/', '-o', os.path.join(d, n + '.COM'), os.path.join(d, n + '.ASM')], check=True)

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
    """LCMD.COM (the command prompt) started from the Executive with CODE-P."""
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
    img = image('sh.img', os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(HERE, 'UPPER.COM'), 'GAMES\\')
    k = ktest.KPC(img); k.start()
    sh = Shell(k)
    check('CODE-P starts the shell', 'command shell' in k.pc.text_screen() and k.pc.mode() == 3, k.pc.text_screen())
    o = sh.run('dir')
    check('DIR lists the disk', all(x in o for x in ('Volume in drive A is LODESTONE', 'Directory of  A:\\', 'LCMD     COM', 'GAMES           <DIR>', '4 File(s)', 'bytes free')), o)
    check('VER', 'Lodestone version 0.6' in sh.run('ver'))
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
    check('batch file, %1, ECHO OFF', 'batch says hi' in o and 'Lodestone version 0.6' in o and 'echo batch' not in o, o)
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
    check('shell files cleaned up', set(files) == {'\\LODE.SYS', '\\LCMD.COM', '\\UPPER.COM', '\\GAMES\\'}, sorted(files))

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
    k = ktest.KPC(image('cap.img', os.path.join(HERE, 'CAPTEST.COM'), os.path.join(GOS, 'src', 'LCMD.COM'))); k.start()
    files = lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
    beeps = lambda: ''.join(k.pc.tty).count('\x07')
    calls21 = []                                # (AX) of the capture's 40h and F0h calls
    def rec(pc):
        if pc.r('cs') == 0x60 and pc.r('ip') == k.Y['int21'] and pc.r('ah') in (0x40, 0xF0): calls21.append(pc.r('ax'))
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
    check('... in a DOS program, through the 1 KB buffer (no lend: with EMS it would be free memory)',
          0xF002 not in calls21 and sum(1 for a in calls21 if a >> 8 == 0x40) == 32, [hex(a) for a in calls21][:6])
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
    check('at the DOS prompt (LCMD): SCREEN04.TXT', 'Lodestone version 0.6' in got and beeps() == 1, repr(got[:200]))
    sh.run('exit'); k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    probs, _ = fatcheck.check(bytes(k.pc.drives[0].img))
    check('disk consistent', not probs, '; '.join(probs))
    # write-protected: a long beep, nothing written, no INT 24h (the UI's
    # handler would have kept the error for its next message)
    before = bytes(k.pc.drives[0].img)
    k.pc.drives[0].wp = True; shot(); k.pc.drives[0].wp = False
    check('write-protected: a long beep, the disk untouched, no INT 24h',
          beeps() == 4 and bytes(k.pc.drives[0].img) == before and k.u16('crit_err') == 0, (beeps(), k.u16('crit_err')))
    # another disk put in, which a program already read through the BIOS
    # (the change line is clear) and no INT 21h 0Dh yet: the capture must
    # not write the first disk's FAT and directory over it
    import pcemu
    data = []
    for i in range(30):
        open(os.path.join(OUT, 'D%02d.TXT' % i), 'wb').write(b'data %d\r\n' % i * 200)
        data.append(os.path.join(OUT, 'D%02d.TXT' % i))
    other = mkimg.build(os.path.join(OUT, 'capother.img'), data)
    before = fatcheck.read_files(open(other, 'rb').read())
    k = ktest.KPC(image('cap2.img', os.path.join(HERE, 'CAPTEST.COM'))); k.start()
    k.select('CAPTEST.COM'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() == 6, 5); k.settle()
    k.pc.drives[0] = pcemu.Floppy(other); k.pc.drives[0].changed = False
    shot()
    after = fatcheck.read_files(bytes(k.pc.drives[0].img))
    probs, _ = fatcheck.check(bytes(k.pc.drives[0].img))
    check('a disk changed behind the kernel\'s back: its files kept, the picture on it',
          all(after.get(n) == d for n, d in before.items()) and 'A:\\SCREEN01.BMP' in after and not probs and beeps() == 1,
          (sorted(set(before) - set(after)), probs[:3], beeps()))
    # no room for all of it: none of it is left
    open(pad, 'wb').write(bytes(1400000))
    k = ktest.KPC(image('capfull.img', pad)); k.start()
    before = sorted(files())
    shot()
    probs, _ = fatcheck.check(bytes(k.pc.drives[0].img))
    check('disk full: a long beep, no SCREEN01.BMP, disk consistent, no write after the one that failed',
          beeps() == 4 and sorted(files()) == before and not probs and sum(1 for a in calls21 if a >> 8 == 0x40) == 1,
          (beeps(), sorted(files()), probs, [hex(a) for a in calls21]))


def t_print():
    """PRINTER=PS.PRN in LODE.INI: PrtSc reads that driver (a file of
    up to 1 KB) into the capture's 1 KB, calls it, and forgets it; PS.PRN
    sends the screen to LPT1 as PostScript (the Brother HL-5370DW's)."""
    import binascii, subprocess
    ini = os.path.join(OUT, 'LODE.INI'); open(ini, 'wb').write(b'printer=ps.prn\r\n')
    ps = os.path.join(GOS, 'drivers', 'PS.PRN')
    k = ktest.KPC(image('prn.img', os.path.join(HERE, 'CAPTEST.COM'), ini, ps)); k.start()
    files = lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
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
          and beeps() == 1 and not any('SCREEN' in n for n in files()), (out[:80], out[-20:], beeps(), sorted(files())))
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
    k2 = ktest.KPC(image('prn2.img', os.path.join(OUT, 'HI.PRN'), big, job, zero, tiny, nosig)); k2.start()
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
    check('no driver: SCREEN01.BMP as before', 'A:\\SCREEN01.BMP' in fatcheck.read_files(bytes(k2.pc.drives[0].img)),
          sorted(fatcheck.read_files(bytes(k2.pc.drives[0].img))))
    check('still no file on the printing disk', not any('SCREEN' in n for n in files()), sorted(files()))
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
    log = fatcheck.read_files(bytes(k.pc.drives[0].img)).get('A:\\CACHETST.TXT', b'').decode('latin-1')
    check('CACHETST leaves its results in CACHETST.TXT' + tag, 'on Lodestone' in log and ' 0 errors' in log, log[-300:])
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
          good and 'Data error reading drive A' in o and 'line 0460' not in o and k.pc.calls_bad <= 9,
          '%d failed reads; %s' % (k.pc.calls_bad, o[-400:]))
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
    fa = fatcheck.read_files(bytes(k.pc.drives[0].img))
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
    k.pc.drives[0].save(os.path.join(OUT, 'lb2.img'))
    subprocess.run(['mdel', '-i', os.path.join(OUT, 'lb2.img'), '::GRIDOS.SYS'], check=True)
    k = ktest.KPC(os.path.join(OUT, 'lb2.img')); k.start()
    check('then it boots LODE.SYS', k.pc.mode() == 0x40 and 'LODE.SYS' in k.exec_list(), k.where())

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
                bat('I2.BAT', 'pause'),
                bat('O3.BAT', '@echo off', 'for %%d in (1 2) do call i3 %%d'),
                bat('I3.BAT', '@echo off', 'for %%e in (a b) do echo in %1 %%e'),
                bat('I7.BAT', '@echo off', 'echo abc | upper'),
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
    o = sh.run('lcmd < s.txt')
    check('standard input from a file: DOS line input, EXIT at its end', 'from a file' in o, o)
    o = sh.run('lcmd < s2.txt')
    check('... a file without EXIT: the shell ends at its end', 'no exit' in o and o.rstrip().endswith('A:\\>'), o)
    for f in ('longname.txt', 'ab1.txt', 'ab2.txt'): sh.run('del ' + f)
    k.key('exit'); k.key(ktest.ENTER)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    check('EXIT: the Executive', k.pc.mode() == 0x40, k.where())

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

TESTS = [t_emsboard, t_noems, t_ems, t_dosapi, t_tm5000g, t_shell, t_disks, t_permanent, t_capture, t_print, t_cache, t_cache_ems, t_mdisk,
         t_mdreview, t_lodeboot, t_command, t_cmdedit, t_cmdsaver, t_calc]
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
