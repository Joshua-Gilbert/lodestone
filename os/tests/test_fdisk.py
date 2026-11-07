"""FDISK.COM in the emulator, on pcemu.Ata: a blank disk shown, the DOS
partition made (the biggest, by size in MB, by /PRI with no questions),
its entry checked field by field (type, active, LBA, cylinder ends, CHS),
then FORMAT C: and a restart: the whole way from a new disk to C:.  A
DOS partition there already, the free cylinders after another system's
partition, the active one set, a DOS partition deleted under the kernel's
C: (Lodestone restarts, and C: is gone), another system's left alone,
answers from a file, Esc, multitasking, no disk.

    python3 tests/test_fdisk.py
"""
import os, struct, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, pcemu, fat16img as F

OUT = tempfile.mkdtemp()
SRC = os.path.join(GOS, 'src')
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

CYL, HEADS, SPT = 300, 8, 32                            # 76,800 sectors: 37.5 MB
HS = HEADS * SPT

def ata(d=None, **kw):
    return pcemu.Ata(model='Test CF 37MB', cyls=CYL, heads=HEADS, spt=SPT,
                     disk=d if d is not None else bytes(CYL * HS * 512), **kw)

def boot(a=None, files=('LODE.SYS', 'LCMD.COM', 'FDISK.COM', 'FORMAT.COM'), extra=()):
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(SRC, f) for f in files] + list(extra))
    k = ktest.KPC(img, ata=a)
    k.start(); k.code_p()
    return k

def out(k): return ''.join(k.pc.tty).replace('\r', '')

def said(o, line): return any(l.strip() == line for l in o.split('\n'))

def run(k, line, *answers, sim=30):
    """line at the prompt, then each answer (and Enter) once it waits -> all it printed, E<exit code>"""
    k.pc.tty.clear()
    k.key(line); k.key(ktest.ENTER)
    for a in answers:
        if a == 'ESC': k.key(chr(27))
        else: k.key(a); k.key(ktest.ENTER)
    k.settle(sim)
    o = out(k)
    for n in (1, 2, 3):
        k.key('if errorlevel %d echo L%d' % (n, n)); k.key(ktest.ENTER)
    return o + '\nE%d\n' % sum(said(out(k)[len(o):], 'L%d' % n) for n in (1, 2, 3))

def parts(d):
    m = bytes(d[0:512])
    return [struct.unpack_from('<B3sB3sII', m, 446 + 16 * i) for i in range(4)], m

def chs(lba):
    c, r = divmod(lba, HS); h, s = divmod(r, SPT)
    c = min(c, 1023)
    return bytes([h, (s + 1) | (c >> 8 << 6), c & 255])

def t_blank():
    a = ata()
    k = boot(a)
    o = run(k, 'fdisk /status')
    check('/STATUS on a blank disk: no partitions, its size and geometry, exit 0, nothing written',
          '(no partitions)' in o and 'Total disk space is 37 MB (300 cylinders, 8 heads, 32 sectors a track)' in o
          and said(o, 'E0') and not a.writes, o)
    o = run(k, 'fdisk', '1', 'Y', 'ESC')
    p, m = parts(a.disk)
    boot0, s0, typ, e0, lba, n = p[0]
    check('the menu, 1, Y: the biggest DOS partition, active, from head 1 of cylinder 0 to the last cylinder\'s end',
          'DOS partition created' in o and 'FORMAT C: next' in o and said(o, 'E0') and m[510:512] == b'\x55\xAA'
          and (boot0, typ, lba, n) == (0x80, 0x06, SPT, CYL * HS - SPT) and p[1][2] == p[2][2] == p[3][2] == 0, (o, p[0]))
    check('... its CHS fields: start and end as the geometry gives them', s0 == chs(SPT) and e0 == chs(CYL * HS - 1), (s0, e0))
    check('... only sector 0 written, the table\'s code our "starts nothing" stub',
          {l for l, c in a.writes} == {0} and b'This disk starts nothing' in m[:446], a.writes)
    o = run(k, 'fdisk /status')
    check('/STATUS after: " C: 1  A  PRI DOS  0  299  37 MB"', ' C: 1' in o and 'PRI DOS' in o and '      0    299' in o
          and '37 MB' in o and ' A ' in o, o)
    # on to a C: the kernel uses
    k.pc.tty.clear()
    k.key('format c: /q'); k.key(ktest.ENTER)
    k.pc.run_until(lambda: '(Y/N)?' in out(k), 30)
    k.key('y'); k.key(ktest.ENTER); k.settle(60)
    o = out(k)
    k = boot(a)                                         # restarted
    o2 = run(k, 'echo hi > c:\\x.txt')
    o2 = run(k, 'dir c:')
    files, probs = F.Volume(a.disk, SPT).files()
    check('... then FORMAT C: and a restart: C: is there, written to, its partition as FDISK made it',
          'Restart Lodestone to use C:' in o and 'X        TXT' in o2 and probs == [] and files.get('\\X.TXT') == b'hi \r\n', (o, o2, probs))

def t_size():
    a = ata()
    k = boot(a)
    o = run(k, 'fdisk', '1', 'N', '10', 'ESC')
    p, m = parts(a.disk)
    want = -(-(10 * 2048 + SPT) // HS) * HS - SPT       # (to the end of the cylinder 10 MB ends in)
    check('N, 10: 10 MB to its cylinder\'s end, type 04h (under 32 MB), not active',
          'DOS partition created' in o and p[0][2] == 0x04 and p[0][4] == SPT and p[0][5] == want and p[0][0] == 0, (o, p[0], want))
    o = run(k, 'fdisk', '1', 'ESC')
    check('a DOS partition there already: said, nothing written', 'There is a DOS partition already' in o
          and len(a.writes) == 1, o)
    a = ata()
    k = boot(a)
    o = run(k, 'fdisk', '1', 'N', '200', '2', 'ESC')
    check('a size that doesn\'t fit (200 MB, then 2 MB): said, asked again', o.count('That size does not fit') == 2
          and 'Size of the DOS partition in MB (3-37)?' in o and not a.writes, o)
    a = ata()
    k = boot(a)
    o = run(k, 'fdisk /pri:5')
    p, m = parts(a.disk)
    check('/PRI:5: 5 MB (to a cylinder\'s end), active, no questions, exit 0',
          p[0][0] == 0x80 and p[0][2] == 0x04 and p[0][5] == -(-(5 * 2048 + SPT) // HS) * HS - SPT and said(o, 'E0')
          and 'Y/N' not in o, (o, p[0]))
    o = run(k, 'fdisk /pri')
    check('/PRI with one there: refused, exit 1', 'There is a DOS partition already' in o and said(o, 'E1'), o)

def t_others():
    d = bytearray(CYL * HS * 512)
    d[0:512] = F.mbr([(0x00, 0x83, SPT, 50 * HS - SPT)], CYL, HEADS, SPT)     # another system's first 50 cylinders
    a = ata(d)
    k = boot(a)
    o = run(k, 'fdisk', '1', 'Y', 'ESC')
    p, m = parts(a.disk)
    check('another system\'s partition at the front: the DOS one in the free cylinders after it, in the next entry, '
          'the other left as it was (31 MB: type 04h)', p[0] == struct.unpack_from('<B3sB3sII', d, 446) and p[1][2] == 0x04
          and p[1][4] == 50 * HS and p[1][5] == (CYL - 50) * HS and p[1][0] == 0x80, (o, p))
    o = run(k, 'fdisk', '2', '1', 'ESC')
    p, m = parts(a.disk)
    check('2, 1: the other system\'s partition made active, the DOS one not', p[0][0] == 0x80 and p[1][0] == 0
          and 'Active partition set' in o, (o, p))
    o = run(k, 'fdisk', '3', '1', 'ESC')
    p2, m2 = parts(a.disk)
    check('3, 1 (the other system\'s): "Not a DOS partition", left', 'Not a DOS partition' in o and p2 == p, o)
    o = run(k, 'fdisk', '3', '2', 'N', 'ESC')
    check('3, 2, N: nothing deleted', parts(a.disk)[0] == p, o)
    o = run(k, 'fdisk', '3', '2', 'Y', 'ESC')
    p3, m3 = parts(a.disk)
    check('3, 2, Y: the DOS partition deleted, its entry all zeros', 'DOS partition deleted' in o and p3[1][2] == 0
          and m3[446 + 16:446 + 32] == bytes(16) and p3[0] == p[0], (o, p3))

def t_under_c():
    f = F.Fat(CYL * HS - SPT, 4, SPT, True, label='OLD', spt=SPT, heads=HEADS)
    f.finish(f.tree([('A.TXT', 0x20, b'a' * 900)]))
    a = ata(F.disk(CYL, HEADS, SPT, SPT, f))
    k = boot(a)
    o0 = run(k, 'dir c:')
    k.pc.tty.clear()
    k.key('fdisk'); k.key(ktest.ENTER)
    for x in ('3', '1', 'Y'): k.key(x); k.key(ktest.ENTER)
    k.key(chr(27))
    k.pc.run_until(lambda: 'restarts now' in out(k), 30)
    o = out(k)
    k.pc.run_for(6); k.settle(20)                       # (the restart: the BIOS, the floppy, Lodestone again)
    k.code_p()
    o2 = run(k, 'c:')
    check('the DOS partition deleted under the kernel\'s C:: Lodestone restarts, and then has no C:',
          'A        TXT' in o0 and 'restarts now' in o and parts(a.disk)[0][0][2] == 0 and 'Invalid drive' in o2, (o, o2))

def t_answers():
    p = os.path.join(OUT, 'ANS.TXT'); open(p, 'wb').write(b'1\r\nY\r\n\x1b')
    a = ata()
    k = boot(a, extra=(p,))
    o = run(k, 'fdisk < ans.txt')
    check('the answers from a file (FDISK < ANS.TXT): the partition made, the end at Esc', 'DOS partition created' in o
          and parts(a.disk)[0][0][2] == 0x06, o)
    a = ata()
    k = boot(a)
    o = run(k, 'fdisk', '1', 'ESC', 'ESC')
    check('Esc at a question: back to the menu, then the end; nothing written, exit 0', not a.writes and said(o, 'E0')
          and o.count('Enter choice') == 2, o)
    o = run(k, 'fdisk', '9', '3', '7', 'ESC')
    check('a choice that isn\'t one, a partition number that isn\'t one: asked again, said', 'No such partition' in o
          and o.count('Enter choice') == 3 and not a.writes, o)
    for line, want in (('fdisk /x', 'Invalid parameter'), ('fdisk /status /pri', 'Invalid parameter'), ('fdisk /pri:0', 'Invalid parameter')):
        o = run(k, line)
        check('%s: "%s", exit 1' % (line.upper(), want), want in o and said(o, 'E1') and not a.writes, o)
    k = boot()
    o = run(k, 'fdisk /status')
    check('no hard disk: "no hard disk answers", exit 1', 'no hard disk answers' in o and said(o, 'E1'), o)

def t_mt():
    import test_mt as M
    from test_kernel import Shell
    a = ata()
    k = M.boot('mtfd.img', b'MULTITASK=1\r\n', 88, os.path.join(SRC, 'FDISK.COM'), ata=a)
    sh = Shell(k)
    sh.run('start /w fdisk.com /pri > o.txt'); k.run_for(10)
    o = sh.run('type o.txt')
    check('with multitasking, FDISK run as a task: refused ("other tasks are running"), nothing written',
          'other tasks are running' in o and not a.writes, o)

if __name__ == '__main__':
    t0 = time.time()
    names = sys.argv[1:]
    for t in (t_blank, t_size, t_others, t_under_c, t_answers, t_mt):
        if not names or t.__name__[2:] in names: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
