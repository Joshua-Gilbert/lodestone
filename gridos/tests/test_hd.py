"""Drive C:: the internal hard disk through KHD.INC, on pcemu.Ata, with
FAT16 disks built by fat16img: found or not (no drive, a floating bus, a
drive stuck busy, no FAT16 partition), the shell on C: (DIR, TYPE, COPY
both ways, MD/CD/REN/DEL/RD, a directory and files past the first 64K
sectors, a file across that boundary, a fragmented one), the FAT checked
as CHKDSK would after each, free space, a bad sector (INT 24h), a full
disk, FAT sectors that can't be read or written (nothing else harmed,
and a floppy's FAT still written), TESTDOS and CACHETST run on C:, the
Executive's drive list, and the memory it all costs.

    python3 tests/test_hd.py [name ...]
"""
import os, re, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, fatcheck, pcemu, fat16img as F
OUT = os.environ.get('KOUT', os.path.join(__import__('tempfile').gettempdir(), 'gridos-hdd'))
os.makedirs(OUT, exist_ok=True)
SRC = os.path.join(GOS, 'src')
GRIDCMD = os.path.join(SRC, 'GRIDCMD.COM')
TM5000G = next((p for p in (os.path.join(GOS, '..', 'tools', 'TM5000G.EXE'),) if os.path.exists(p)), None)

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

def image(name, *files):
    return mkimg.build(os.path.join(OUT, name), [os.path.join(SRC, 'GRIDOS.SYS')] + list(files))

class Shell:
    """GRIDCMD.COM (CODE-P) on the kernel; run() -> the screen after."""
    def __init__(s, k):
        s.k = k
        k.key(ktest.CODE_P)
    def run(s, cmd, *answers):
        k = s.k
        k.key('cls'); k.key(ktest.ENTER)
        k.key(cmd); k.key(ktest.ENTER)
        for a in answers: k.key(a); k.key(ktest.ENTER)
        return '\n'.join(k.pc.text_screen().rstrip().split('\n')[1:])

# ---------------------------------------------------------------------
#  the disk most tests use: 220 x 8 x 39 (68,640 sectors, 34 MB), one
#  FAT16 partition from sector 39 with 2 KB clusters.  Its data starts at
#  sector 167, not a multiple of 4: cluster 16344 holds sectors 65535-
#  65538 of the partition, across the 16-bit boundary.  A filler file
#  takes clusters up to 16335, so new files start right before it; FAR is
#  a directory from cluster 16400 on, past the boundary.
# ---------------------------------------------------------------------
CYL, HEADS, SPT, PLBA = 220, 8, 39, 39
README = b'Hello from drive C:\r\n'
NOTE = b'A note in a directory past the first 64K sectors.\r\n' * 3

def std():
    f = F.Fat(CYL * HEADS * SPT - PLBA, 4, PLBA, True, label='GRIDHD')
    early = [('GRIDHD', 0x08, None), ('IO.SYS', 0x07, b'I' * 33430), ('README.TXT', 0x20, README),
             ('DOS', 0, [('F%02d.EXE' % i, 0x20, bytes([65 + i % 26]) * (300 * i + 11)) for i in range(40)])]
    ents = f.tree(early)
    fill = 16342 - f.free                               # the filler, to just before the boundary
    ents += f.ent('FILLER.DAT', 0x20, f.write(b'\0' * fill * 2048), fill * 2048)
    f.skip_to(16400)
    ents += f.tree([('FAR', 0, [('NOTE.TXT', 0x20, NOTE)])])
    f.finish(ents)
    return F.disk(CYL, HEADS, SPT, PLBA, f), f

def drive(d, **kw):
    return pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=CYL, heads=HEADS, spt=SPT, disk=d, **kw)

def vol(ata, plba=PLBA):
    return F.Volume(ata.disk, plba)

def boot(name, ata=None, files=(GRIDCMD,), **kw):
    img = image(name + '.img', *files)
    k = ktest.KPC(img, ata=ata, **kw)
    t0 = k.pc.us
    k.start()
    return k, (k.pc.us - t0) / 1e6

def c_dt(k):
    return k.pc.rd(0x60, k.Y['drvtab'] + 64, 32)

def answer(k, cmd, key='f', on_prompt=None, sim=20):
    """cmd at the prompt, each INT 24h answered key (on_prompt() first)
    -> (prompts, the screen after)."""
    pc = k.pc
    k.key('cls'); k.key(ktest.ENTER)
    k.key(cmd); k.key(ktest.ENTER, settle=False)
    seen = 0
    t_end = pc.us + sim * 1e6
    while pc.us < t_end and seen < 20:
        pc.run_until(lambda: pc.text_screen().count('Fail?') > seen or pc.crash, 2)
        c = pc.text_screen().count('Fail?')
        if c <= seen: break
        seen = c
        if on_prompt: on_prompt()
        pc.keys.append(ord(key))
    k.settle()
    return seen, '\n'.join(pc.text_screen().rstrip().split('\n')[1:])

def fatw(ata, n, plba=PLBA):
    """FAT 1 of the disk as it is now: its first n entries."""
    return list(struct.unpack_from('<%dH' % n, ata.disk, (plba + 1) * 512))

# ---------------------------------------------------------------------
def t_none():
    """No drive, a floating bus, a drive stuck busy, a drive with no FAT16
    partition: no C:, and the boot isn't held up (but by the busy one)."""
    k0, t0 = boot('none')
    sh = Shell(k0)
    o = sh.run('c:')
    check('no drive: no C: ("Invalid drive specification"), nothing kept (the arena from the BSS\'s end)',
          'Invalid drive specification' in o and c_dt(k0)[27] == 0 and
          k0.pc.u16(0x60, k0.Y['mem_init'] + 1) == k0.Y['bss_end'] + 15, o)
    k1, t1 = boot('float', float_bus=True)
    check('a floating bus (the 1520 with its dead CP3044): no C:, boot as fast (%.2f s against %.2f s)' % (t1, t0),
          c_dt(k1)[27] == 0 and k1.pc.mode() == 0x40 and t1 < t0 + 0.2, (t0, t1))
    k2, t2 = boot('busy', pcemu.Ata(stuck=True))
    check('a drive stuck busy: no C:, after its 5 s (%.1f s)' % t2, c_dt(k2)[27] == 0 and k2.pc.mode() == 0x40 and t2 < t0 + 12, t2)
    k3, t3 = boot('blank', pcemu.Ata(cyls=20, heads=2, spt=17, disk=bytes(20 * 2 * 17 * 512)))
    check('a drive with no partition table: no C:', c_dt(k3)[27] == 0 and k3.pc.mode() == 0x40)
    g = F.Fat(2000, 1, 17, False)                       # a FAT12 partition (type 01): not ours
    g.finish(g.tree([('A.TXT', 0x20, b'a')]))
    d = bytearray(20 * 4 * 17 * 512); d[0:512] = F.mbr([(0x80, 0x01, 17, 2000)], 20, 4, 17); d[17 * 512:(17 + 2000) * 512] = g.img
    k4, t4 = boot('fat12', pcemu.Ata(cyls=20, heads=4, spt=17, disk=d))
    check('a FAT12 partition (type 01): no C:', c_dt(k4)[27] == 0 and k4.pc.mode() == 0x40)
    d, f = std()                                        # a drive smaller than the partition
    k5, t5 = boot('past', pcemu.Ata(cyls=CYL - 20, heads=HEADS, spt=SPT, disk=d))
    d, f = std()                                        # the boot sector more than the table
    struct.pack_into('<I', d, 446 + 12, f.n - 1)
    k6, t6 = boot('bigbpb', drive(d))
    check('a partition past the drive\'s end, a boot sector bigger than its partition: no C:',
          c_dt(k5)[27] == 0 and c_dt(k6)[27] == 0 and k5.pc.mode() == 0x40 and k6.pc.mode() == 0x40,
          (c_dt(k5)[27], c_dt(k6)[27]))

def t_shell():
    d, f = std()
    ata = drive(d)
    k, t = boot('shell', ata, files=(GRIDCMD, os.path.join(HERE, 'UPPER.COM')))
    check('C: found and mounted (FAT16, 2 KB clusters)', c_dt(k)[27] == 1 and c_dt(k)[2] == 4, c_dt(k).hex())
    sh = Shell(k)
    v0 = vol(ata)
    o = sh.run('dir c:')
    check('DIR C:: the root, and the bytes free (%d clusters)' % v0.free(),
          all(x in o for x in ('README   TXT', 'DOS             <DIR>', 'FAR             <DIR>', 'FILLER   DAT')) and
          '%d bytes free' % (v0.free() * 2048) in o and 'IO       SYS' not in o, o)
    check('VOL: the label', 'Volume in drive C is GRIDHD' in sh.run('vol c:'))
    sh.run('c:')
    check('TYPE README.TXT', 'Hello from drive C:' in sh.run('type readme.txt'))
    o = sh.run('type far\\note.txt')
    check('TYPE FAR\\NOTE.TXT: a directory past the first 64K sectors', o.count('A note in a directory past') == 3, o)
    o = sh.run('dir dos')
    check('DIR DOS: a directory of three scattered clusters', 'F39      EXE' in o and '40 File(s)' in o or '42 File(s)' in o, o)
    # copies: across the boundary, both ways
    g = open(GRIDCMD, 'rb').read()
    sh.run('copy a:\\gridcmd.com c:\\')
    v = vol(ata); files, probs = v.files(f.gaps)
    cl = next(c for n, a, c, s in v.entries(0) if n == 'GRIDCMD.COM')
    chain = v.chain(cl)[0]
    check('COPY A: to C:: the file as it is, in clusters %d-%d (across the 64K-sector boundary)' % (chain[0], chain[-1]),
          files.get('\\GRIDCMD.COM') == g and chain[0] <= 16344 <= chain[-1] and not probs, (chain[:3], probs))
    sh.run('copy c:\\gridcmd.com a:\\g2.com')
    a = fatcheck.read_files(bytes(k.pc.drives[0].img))
    check('COPY C: to A:: the same bytes back', a.get('A:\\G2.COM') == g, len(a.get('A:\\G2.COM', b'')))
    sh.run('copy a:\\gridcmd.com c:\\far')
    v = vol(ata); files, probs = v.files(f.gaps)
    check('COPY into FAR (a directory past 64K sectors): written and named there',
          files.get('\\FAR\\GRIDCMD.COM') == g and files.get('\\FAR\\NOTE.TXT') == NOTE and not probs, probs)
    o = sh.run('dir far')
    check('DIR FAR shows it', 'GRIDCMD  COM' in o and 'NOTE     TXT' in o, o)
    # directories and names
    sh.run('md new'); sh.run('cd new')
    sh.run('copy a:\\upper.com x.com'); sh.run('ren x.com y.com')
    o = sh.run('dir')
    check('MD, CD, COPY, REN in a new directory', 'Directory of  C:\\NEW' in o and 'Y        COM' in o and 'X        COM' not in o, o)
    sh.run('del y.com'); sh.run('cd \\'); o = sh.run('rd new')
    v = vol(ata); files, probs = v.files(f.gaps)
    check('DEL, RD: gone again, the FAT whole', 'NEW' not in [n for n, *_ in v.entries(0)] and not probs, probs)
    sh.run('del far\\gridcmd.com')
    o = sh.run('echo hello > c:\\far\\new.txt')
    v = vol(ata); files, probs = v.files(f.gaps)
    check('ECHO > a new file in FAR, FAR\\GRIDCMD.COM deleted', files.get('\\FAR\\NEW.TXT') == b'hello \r\n' and
          '\\FAR\\GRIDCMD.COM' not in files and not probs, (files.get('\\FAR\\NEW.TXT'), probs))
    o = sh.run('dir')
    check('the bytes free match the FAT (%d clusters)' % v.free(), '%d bytes free' % (v.free() * 2048) in o, o)
    w = [l for l, n in ata.writes if not (PLBA <= l and l + n <= PLBA + v.total)]
    check('every write inside the partition; commands only 91h ECh 20h 30h',
          not w and {c for c, *_ in ata.cmds} <= {0x91, 0xEC, 0x20, 0x30}, (w, {hex(c) for c, *_ in ata.cmds}))

def t_big():
    """A 296 KB file: copied to C: (into the gap before FAR and on past
    it: fragmented, across the boundary) and back."""
    if not TM5000G: return
    d, f = std()
    ata = drive(d)
    k, t = boot('big', ata, files=(GRIDCMD, 'TM5000G.EXE=' + TM5000G))
    sh = Shell(k)
    big = open(TM5000G, 'rb').read()
    sh.run('copy tm5000g.exe c:\\')
    v = vol(ata); files, probs = v.files(f.gaps)
    cl = next(c for n, a, c, s in v.entries(0) if n == 'TM5000G.EXE')
    chain = v.chain(cl)[0]
    runs = sum(1 for a, b in zip(chain, chain[1:]) if b != a + 1) + 1
    check('a 296 KB file to C:: right, in %d pieces, across the boundary' % runs,
          files.get('\\TM5000G.EXE') == big and runs >= 2 and chain[0] < 16344 < chain[-1] and not probs, (runs, probs))
    sh.run('copy c:\\tm5000g.exe c:\\far\\tm2.exe')
    v = vol(ata); files, probs = v.files(f.gaps)
    check('copied again on C: (into FAR): the same bytes', files.get('\\FAR\\TM2.EXE') == big and not probs, probs)
    sh.run('c:'); o = sh.run('far\\tm2', '0')
    k.pc.run_until(lambda: k.pc.mode() == 3 or k.crashed, 20)
    check('and it runs from C:\\FAR (TM5000G\'s first screen)', 'TM5000' in k.pc.text_screen() or 'GRIDGPIB' in ''.join(k.pc.tty),
          k.pc.text_screen()[-400:])

def t_real():
    """The CP30104H's own layout: its partition table and boot sector as
    HDSCAN read them (2026-10-07), 762 x 8 x 39, a 121 MB FAT16 partition:
    the free space counted over 59,224 clusters, a file at the far end."""
    rom = os.path.join(GOS, '..', 'rom', 'hd_cp30104h')
    sect0 = open(os.path.join(rom, 'HDSECT0.BIN'), 'rb').read()
    boots = open(os.path.join(rom, 'HDBOOT.BIN'), 'rb').read()
    plba, n = struct.unpack_from('<II', sect0, 446 + 8)
    f = F.Fat(n, 4, plba, True)
    assert (f.spf, f.clusters) == (232, 59224), (f.spf, f.clusters)
    ents = f.tree([('COMMAND.COM', 0x20, b'C' * 47845)])
    f.skip_to(59000)
    ents += f.tree([('END.TXT', 0x20, b'at the far end\r\n')])
    f.finish(ents)
    f.img[0:512] = boots
    d = bytearray(762 * 8 * 39 * 512); d[0:512] = sect0; d[plba * 512:(plba + n) * 512] = f.img
    ata = pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=762, heads=8, spt=39, disk=d)
    k, t = boot('real', ata)
    sh = Shell(k)
    v = vol(ata, plba)
    o = sh.run('dir c:')
    check('121 MB: DIR C: and its free space (%d KB)' % (v.free() * 2), '%d bytes free' % (v.free() * 2048) in o and
          'COMMAND  COM' in o, o)
    check('TYPE C:\\END.TXT (cluster 59000, sector 236,535 of the partition)', 'at the far end' in sh.run('type c:\\end.txt'))

def t_bad():
    """A sector of a file can't be read: INT 24h, "Data error reading drive
    C", and Fail ends the TYPE."""
    d, f = std()
    v = F.Volume(d, PLBA)
    cl = next(c for n, a, c, s in v.entries(0) if n == 'README.TXT')
    ata = drive(d, bad=[PLBA + v.data + (cl - 2) * 4])
    k, t = boot('bad', ata)
    sh = Shell(k)
    o = sh.run('type c:\\readme.txt', 'r', 'f')
    check('a bad sector: "Data error reading drive C", Abort/Retry/Fail, Retry then Fail',
          o.count('Data error reading drive C') == 2 and 'Hello' not in o, o)

def t_full():
    """A small FAT16 partition near full: COPY says so, nothing lost."""
    f = F.Fat(4300, 1, 17, True, rootents=64)           # 4,261 clusters of 512 bytes
    ents = f.tree([('A.DAT', 0x20, b'a' * ((f.clusters - 6) * 512))])
    f.finish(ents)
    d = bytearray(70 * 4 * 17 * 512)
    d[0:512] = F.mbr([(0x80, 0x04, 17, 4300)], 70, 4, 17); d[17 * 512:(17 + 4300) * 512] = f.img
    ata = pcemu.Ata(cyls=70, heads=4, spt=17, disk=d)
    k, t = boot('full', ata)
    sh = Shell(k)
    o = sh.run('copy gridcmd.com c:\\')
    v = F.Volume(ata.disk, 17); files, probs = v.files()
    check('C: full: "Insufficient disk space", the FAT still whole', 'Insufficient disk space' in o and not probs and
          '\\GRIDCMD.COM' not in files, (o, probs))

def t_fatread():
    """A FAT sector that can't be read: DEL answered Fail leaves the FATs
    and the partition's boot sector as they were (the entry goes, its
    clusters are lost, as with DOS); an Abort while one is read leaves
    nothing behind in the window, and the next DEL is right."""
    d, f = std()
    v = F.Volume(d, PLBA)
    cl = next(c for n, a, c, s in v.entries(0) if n == 'README.TXT')
    ata = drive(d, bad=[PLBA + 1 + cl // 256])
    k, t = boot('fatrd', ata)
    Shell(k)
    before = bytes(ata.disk); w0 = len(ata.writes)
    n, o = answer(k, 'del c:\\readme.txt')
    root = v.root + PLBA
    v2 = vol(ata); files, probs = v2.files(f.gaps | {cl})
    check('a FAT sector unreadable, DEL, Fail: "Data error reading", the FATs and boot sector untouched, '
          'only the directory written', n >= 1 and 'Data error reading drive C' in o and
          ata.disk[:root * 512] == before[:root * 512] and all(root <= a < PLBA + v.data for a, c in ata.writes[w0:]) and
          not probs and '\\README.TXT' not in files, (o, ata.writes[w0:], probs))
    f = F.Fat(CYL * HEADS * SPT - PLBA, 4, PLBA, True)
    f.skip_to(1792); two = f.write(b'2' * 2048 * 256)   # FAT sector 7
    f.skip_to(2560); one = f.write(b'1' * 2048 * 8)     # FAT sector 10
    f.finish(f.ent('FILE2.DAT', 0x20, two, 256 * 2048) + f.ent('FILE1.DAT', 0x20, one, 8 * 2048))
    ata = drive(F.disk(CYL, HEADS, SPT, PLBA, f), bad=[PLBA + 1 + 10])
    k, t = boot('fatab', ata, files=(GRIDCMD, os.path.join(HERE, 'UPPER.COM')))
    Shell(k)
    n, o = answer(k, 'a:upper < c:\\file1.dat > nul', key='a')
    lab = struct.unpack('<3H', k.pc.rd(0x60, k.Y['hd_wsec'], 6))
    ata.bad.clear()                                     # (it reads again)
    n2, o2 = answer(k, 'del c:\\file1.dat')
    v = vol(ata); files, probs = v.files()
    check('Abort while a FAT sector is read: no slot claims it; then DEL FILE1 frees its clusters, FILE2 whole',
          n == 1 and 10 not in lab and n2 == 0 and not probs and list(files) == ['\\FILE2.DAT'] and
          fatw(ata, 2568)[2560:] == [0] * 8, (o, lab, o2, probs))

def t_fatwrite():
    """A FAT sector that won't take a write: a DEL through five FAT
    sectors (the window's slots written back as it goes) harms no other
    file; a passing fault while a file is open, then its close writes it
    all; C:'s FAT failing for good while A:'s has changes: A:'s written."""
    f = F.Fat(CYL * HEADS * SPT - PLBA, 4, PLBA, True)
    chain = []
    for c in (300, 600, 900, 1200, 1500):               # FAT sectors 1 to 5
        f.skip_to(c); chain.append(f.write(b'F' * 2048))
    for a, b in zip(chain, chain[1:]): f.fat[a] = b
    f.skip_to(7080); other = f.write(b'O' * 2048 * 20)  # FAT sector 27
    f.finish(f.ent('FRAG.DAT', 0x20, chain[0], 5 * 2048) + f.ent('OTHER.DAT', 0x20, other, 20 * 2048))
    ata = drive(F.disk(CYL, HEADS, SPT, PLBA, f), badw=[PLBA + 1 + 1])
    k, t = boot('fatwr', ata)
    Shell(k)
    n, o = answer(k, 'del c:\\frag.dat')
    v = vol(ata); files, probs = v.files(set(chain))
    check('a FAT sector unwritable, DEL through 5 FAT sectors, Fail: "writing drive C", OTHER.DAT whole',
          n >= 1 and 'writing drive C' in o and ata.wfails >= 2 and not probs and
          files.get('\\OTHER.DAT') == b'O' * 2048 * 20 and v.chain(other)[0] == list(range(7080, 7100)), (o, probs))
    prog = (GRIDCMD, os.path.join(HERE, 'HDFLUSH.COM'))
    d, f = std()
    first = fatw(drive(d), f.clusters + 2).index(0, 2)
    ata = drive(d, badw=[PLBA + 1 + first // 256])
    k, t = boot('flush1', ata, files=prog)
    Shell(k)
    n, o = answer(k, 'a:hdflush', on_prompt=lambda: ata.badw.clear())
    v = vol(ata); files, probs = v.files(f.gaps)
    fl, ffiles = fatcheck.check(bytes(k.pc.drives[0].img))
    check('a passing write fault, Fail: then X.DAT\'s close writes it all',
          n == 1 and 'X closed ok' in o and not probs and files.get('\\X.DAT') == b'f' * 8192 and
          not fl and ffiles.get('\\F.DAT') == 12288, (o, probs, fl))
    d, f = std()
    ata = drive(d, badw=[PLBA + 1 + first // 256])
    k, t = boot('flush2', ata, files=prog)
    Shell(k)
    n, o = answer(k, 'a:hdflush')
    fl, ffiles = fatcheck.check(bytes(k.pc.drives[0].img))
    v = vol(ata); files, probs = v.files(f.gaps)
    check('C:\'s FAT never written, Fail each time: A:\\F.DAT on the floppy all the same, C:\'s other files whole',
          n >= 2 and 'X close failed' in o and not fl and ffiles.get('\\F.DAT') == 12288 and
          all('X.DAT' in p or 'lost' in p for p in probs) and files.get('\\README.TXT') == README, (o, fl, probs))

def t_testdos():
    """TESTDOS (24 DOS calls) and CACHETST (random and in-order reads,
    writes over cached parts, two interleaved files) on C:."""
    d, f = std()
    ata = drive(d)
    k, t = boot('testdos', ata, files=(GRIDCMD, os.path.join(HERE, 'TESTDOS.COM'), os.path.join(HERE, 'CACHETST.COM')))
    sh = Shell(k)
    sh.run('c:')
    k.key('cls'); k.key(ktest.ENTER); k.key('a:testdos'); k.key(ktest.ENTER, settle=False)
    tty = lambda: ''.join(k.pc.tty)
    n0 = len(tty())
    ktest.run_answering(k.pc, lambda: 'failed' in tty()[n0:] and tty().rstrip().endswith('>'), 240)
    out = tty()[n0:]
    check('TESTDOS on C:: all but its check that the current drive is A: (step 2 says 2, C:)',
          ' 23 passed, 1 failed' in out and out.count('FAIL') == 1 and 'version, drive, date (step 2, AX=0002' in out, out[-600:])
    n0 = len(tty())
    k.key('a:cachetst'); k.key(ktest.ENTER, settle=False)
    ktest.run_answering(k.pc, lambda: 'errors' in tty()[n0:] and tty().rstrip().endswith('>'), 1500)
    out = tty()[n0:]
    check('CACHETST on C:: every byte reads back as written', ' 0 errors' in out, out[-600:])
    v = vol(ata); files, probs = v.files(f.gaps)
    check('C: consistent after both', not probs, probs)

FORM_Y, ITEM_H = 244, 20                # the File form (EXEC.INC)
def form(k):
    rows = dict(k.ocr())
    return [rows.get(FORM_Y + i * ITEM_H, '')[14:].strip() for i in range(4)]

def t_exec():
    """The Executive: C: in Device ("Hard disk C:"), its titles, a program
    run from it, and in the Copy form's drives."""
    d, f = std()
    ata = drive(d)
    k, t = boot('exec', ata, files=(GRIDCMD, os.path.join(HERE, 'MEMSZ.COM')))
    k.key(ktest.TAB)
    check('Device: A:, B:, C: in the list', k.u16('nent') == 3 and any('Hard disk C:' in l for y, l in k.ocr()), k.u16('nent'))
    k.key(ktest.DOWN); k.key(ktest.DOWN)
    check('Down twice: Hard disk C: chosen at once', form(k)[0] == 'Hard disk C:', form(k))
    k.key(ktest.ENTER); k.key(ktest.TAB)
    lst = k.exec_list()
    check('C:\\ listed: its titles', 'README.TXT' in lst and 'FILLER.DAT' in lst, lst)
    sh = Shell(k); sh.run('copy a:\\memsz.com c:\\'); sh.run('exit')
    k.settle()
    k.select('MEMSZ.COM'); k.pc.tty.clear(); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() != 0x40, 5)
    ktest.run_answering(k.pc, lambda: k.pc.mode() == 0x40, 30); k.settle()
    check('a program run from C: (MEMSZ.COM ended)', any('MEMSZ.COM ended' in l for l in k.band()) and
          'KB for programs' in ''.join(k.pc.tty), (k.band(), ''.join(k.pc.tty)[-200:]))
    # CODE-C from A:: Device Right, Right is C:
    k.key(ktest.TAB); k.key(ktest.UP); k.key(ktest.UP); k.key(ktest.ENTER); k.key(ktest.TAB)
    k.select('GRIDCMD.COM'); k.key(0x2E00)              # CODE-C
    k.key(ktest.ENTER, ktest.RIGHT, ktest.RIGHT, ktest.ENTER, '\\far', ktest.ENTER, 'cmd2.com', ktest.ENTER, 0x1C00)
    v = vol(ata); files, probs = v.files(f.gaps)
    check('the Copy form: A:\\GRIDCMD.COM to C:\\FAR\\CMD2.COM', files.get('\\FAR\\CMD2.COM') == open(GRIDCMD, 'rb').read() and
          not probs and 'Copied' in k.band()[0], (k.band(), probs))

def t_mem():
    """The memory a program gets: this kernel without the drive against the
    one before the hard disk (the core's share), and with it (the module)."""
    memsz = os.path.join(HERE, 'MEMSZ.COM')
    def kb(name, sysfile, ata=None, **kw):              # (from the shell: any kernel's map)
        img = mkimg.build(os.path.join(OUT, name + '.img'), ['GRIDOS.SYS=' + sysfile, memsz, GRIDCMD])
        k = ktest.KPC(img, ata=ata, **kw); k.start()
        m = re.search(r'([\d.]+) KB for programs', Shell(k).run('memsz'))
        return float(m.group(1)) if m else None
    base = os.environ.get('BASE_SYS')
    new = os.path.join(SRC, 'GRIDOS.SYS')
    d, f = std()
    a = kb('m_new', new)
    b = kb('m_hd', new, drive(d))
    e = kb('m_ems', new, ems_pages=88)
    g = kb('m_hdems', new, drive(d), ems_pages=88)
    out = 'without a drive %.1f KB, with C: %.1f KB; with EMS %.1f and %.1f KB' % (a, b, e, g)
    if base:
        z = kb('m_base', base)
        y = kb('m_base_ems', base, ems_pages=88)
        out += '; before the hard disk %.1f KB, with EMS %.1f KB' % (z, y)
    print('   ' + out)
    check('memory: C: costs under 3 KB with EMS, 3.5 KB without (the window then fills EMS\'s place)' +
          (', the kernel without it under 0.3 KB' if base else ''),
          e - g < 3.0 and a - b < 3.5 and (not base or (z - a < 0.3 and y - e < 0.3)), out)

TESTS = [t_none, t_shell, t_big, t_real, t_bad, t_full, t_fatread, t_fatwrite, t_testdos, t_exec, t_mem]
if __name__ == '__main__':
    want = sys.argv[1:]
    subprocess.run(['nasm', '-f', 'bin', '-o', os.path.join(HERE, 'HDFLUSH.COM'), os.path.join(HERE, 'HDFLUSH.ASM')], check=True)
    for t in TESTS:
        if want and t.__name__[2:] not in want: continue
        print('==', t.__name__[2:])
        t0 = time.time(); t(); print('   (%.1f s)' % (time.time() - t0))
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s' % (len(results), len(bad), (': ' + ', '.join(bad)) if bad else ''))
    sys.exit(1 if bad else 0)
