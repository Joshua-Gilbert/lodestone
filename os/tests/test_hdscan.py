"""HDSCAN.COM (tools/) under Lodestone in pcemu, against the 1520's internal
hard disk as pcemu.Ata plays it, with a disk built here: a partition table,
a FAT16 partition (a label, hidden system files, a directory long enough
to take several clusters, scattered, a nested one, a deleted entry, a long
name's piece, a cluster marked bad) and a FAT12 one (an old boot sector,
no label); bad sectors for the sweep; a drive that sticks part way.

    python3 tests/test_hdscan.py [name ...]
"""
import os, re, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
TOOLS = os.path.join(os.path.dirname(GOS), 'tools')
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, fatcheck, pcemu
OUT = os.environ.get('KOUT', os.path.join(__import__('tempfile').gettempdir(), 'lodestone-hd'))
os.makedirs(OUT, exist_ok=True)
SCAN = os.path.join(TOOLS, 'HDSCAN.COM')

def build():
    subprocess.run(['nasm', '-f', 'bin', '-i', TOOLS + '/', '-o', SCAN, os.path.join(TOOLS, 'HDSCAN.ASM')], check=True)

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

DATE = ((1991 - 1980) << 9) | (4 << 5) | 9          # 1991-04-09
TIME = (5 << 11) | (7 << 5)                        # 05:07

class Fat:
    """A FAT12/16 partition image, files and directories laid out as DOS
    would, but for the directories' clusters, which are scattered."""
    def __init__(s, sectors, spc, hidden, fat16, label=None, oem=b'MSDOS5.0', rootents=512, nfats=2):
        s.spc, s.fat16, s.n = spc, fat16, sectors
        s.rootsecs = rootents * 32 // 512
        spf = 1
        while True:
            cl = (sectors - 1 - nfats * spf - s.rootsecs) // spc
            need = -(-((cl + 2) * (2 if fat16 else 1.5)) // 512)
            if need <= spf: break
            spf = int(need)
        s.spf, s.clusters, s.nfats = spf, cl, nfats
        assert (cl >= 4085) == fat16, cl
        s.img = bytearray(sectors * 512)
        b = bytearray(512)
        b[0:3] = b'\xEB\x3C\x90'; b[3:11] = oem
        struct.pack_into('<HBHBHHBHHHI', b, 11, 512, spc, 1, nfats, rootents,
                         sectors if sectors < 65536 else 0, 0xF8, spf, 17, 4, hidden)
        if sectors >= 65536: struct.pack_into('<I', b, 0x20, sectors)
        if label:
            b[0x24] = 0x80; b[0x26] = 0x29; struct.pack_into('<I', b, 0x27, 0x1A2B3C4D)
            b[0x2B:0x36] = label.ljust(11).encode(); b[0x36:0x3E] = b'FAT16   ' if fat16 else b'FAT12   '
        b[510:512] = b'\x55\xAA'
        s.img[0:512] = b; s.boot = bytes(b)
        s.fat = [0] * (cl + 2); s.fat[0] = 0xFFF8 if fat16 else 0xFF8; s.fat[1] = 0xFFFF if fat16 else 0xFFF
        s.free = 2
        s.data = 1 + nfats * spf + s.rootsecs

    def alloc(s, n):
        got = list(range(s.free, s.free + n)); s.free += n
        end = 0xFFFF if s.fat16 else 0xFFF
        for a, b in zip(got, got[1:] + [end]): s.fat[a] = b
        return got

    def put(s, cl, data):
        off = (s.data + (cl - 2) * s.spc) * 512
        s.img[off:off + len(data)] = data

    def write(s, data):
        if not data: return 0
        cls = s.alloc(-(-len(data) // (512 * s.spc)))
        for i, c in enumerate(cls): s.put(c, data[i * 512 * s.spc:(i + 1) * 512 * s.spc])
        return cls[0]

    @staticmethod
    def ent(name, attr, cl, size):
        n, _, e = name.partition('.')
        raw = n.ljust(8).encode()[:8] + e.ljust(3).encode()[:3] if name not in ('.', '..') else name.ljust(11).encode()
        return raw + bytes([attr]) + bytes(10) + struct.pack('<HHHI', TIME, DATE, cl, size)

    def tree(s, items, parent=0, cl=None):
        """items: [(name, attr, bytes or [items])] -> directory entries; the
        root if cl is None.  A subdirectory's clusters are allocated one by
        one with its first file between, so its chain is scattered."""
        ents = []
        if cl is not None: ents += [s.ent('.', 0x10, cl[0], 0), s.ent('..', 0x10, parent, 0)]
        for name, attr, body in items:
            if isinstance(body, list):
                per = 16 * s.spc
                n = -(-(len(body) + 2) // per)
                first = s.alloc(1)
                rest = []
                for _ in range(n - 1):
                    s.write(b'x' * 512 * s.spc)            # a gap: the chain is scattered
                    rest += s.alloc(1)
                chain = first + rest
                end = 0xFFFF if s.fat16 else 0xFFF
                for a, b2 in zip(chain, chain[1:] + [end]): s.fat[a] = b2
                sub = s.tree(body, cl[0] if cl else 0, chain)
                sub = sub.ljust(len(chain) * 512 * s.spc, b'\0')
                for i, c in enumerate(chain): s.put(c, sub[i * 512 * s.spc:(i + 1) * 512 * s.spc])
                ents.append(s.ent(name, attr | 0x10, chain[0], 0))
            elif body is None:
                ents.append(s.ent(name, attr, 0, 0))
            else:
                ents.append(s.ent(name, attr, s.write(body), len(body)))
        return b''.join(ents)

    def finish(s, root):
        off = (1 + s.nfats * s.spf) * 512
        s.img[off:off + len(root)] = root
        if s.fat16:
            f = b''.join(struct.pack('<H', v) for v in s.fat)
        else:
            f = bytearray((len(s.fat) * 3 + 1) // 2 + 1)
            for i, v in enumerate(s.fat):
                o = i * 3 // 2
                if i & 1: f[o] = (f[o] & 0x0F) | ((v << 4) & 0xF0); f[o + 1] = v >> 4
                else: f[o] = v & 0xFF; f[o + 1] = (f[o + 1] & 0xF0) | (v >> 8)
            f = bytes(f)
        for k in range(s.nfats):
            o = (1 + k * s.spf) * 512
            s.img[o:o + len(f)] = f
        return s.img

CYL, HEADS, SPT = 100, 4, 17
P1, P1N, P2, P2N = 17, 5983, 6000, 800
FILES16 = 40                                        # in C:\DOS: three clusters' worth
BAD = [3000, 6500]                                  # don't read (free space)

def chs(lba):
    c, r = divmod(lba, HEADS * SPT); h, sct = divmod(r, SPT)
    return c, h, sct + 1

def disk():
    d = bytearray(CYL * HEADS * SPT * 512)
    m = bytearray(512)
    for i, (boot, typ, start, n) in enumerate([(0x80, 0x04, P1, P1N), (0, 0x01, P2, P2N)]):
        c1, h1, s1 = chs(start); c2, h2, s2 = chs(start + n - 1)
        m[446 + 16 * i:462 + 16 * i] = struct.pack('<BBBBBBBBII', boot, h1, s1 | (c1 >> 8 << 6), c1 & 255, typ,
                                                   h2, s2 | (c2 >> 8 << 6), c2 & 255, start, n)
    m[510:512] = b'\x55\xAA'
    d[0:512] = m
    f = Fat(P1N, 1, P1, True, label='OLDDISK')
    dos = [('F%02d.EXE' % i, 0x20, bytes([i]) * (100 * i + 7)) for i in range(FILES16)]
    dos.append(('UTIL', 0, [('LIST.COM', 0x20, b'L' * 3000), ('EMPTY.TXT', 0x20, b'')]))
    root = f.tree([('OLDDISK', 0x08, None),
                   ('IO.SYS', 0x07, b'I' * 33430), ('MSDOS.SYS', 0x07, b'M' * 37394),
                   ('COMMAND.COM', 0x20, b'C' * 47845), ('AUTOEXEC.BAT', 0x20, b'A' * 64),
                   ('DOS', 0, dos)])
    root += b'\xE5' + f.ent('GONE.TXT', 0x20, 0, 10)[1:]          # deleted
    root += b'\x41' + b'l\0o\0n\0g\0n\0' + bytes([0x0F]) + bytes(20)  # a long name's piece
    f.fat[5000] = 0xFFF7                                        # marked bad
    d[P1 * 512:(P1 + P1N) * 512] = f.finish(root)
    g = Fat(P2N, 2, P2, False, oem=b'IBM  3.3', rootents=112)
    root2 = g.tree([('README.TXT', 0x20, b'R' * 1234), ('DATA', 0, [('A.DAT', 0x21, b'D' * 5000)])])
    d[P2 * 512:(P2 + P2N) * 512] = g.finish(root2)
    return bytes(d), f, g

def scan(name, ata, sim=400, stop_at=None):
    """Run HDSCAN from the Executive; stop_at: a key once the screen shows
    that text.  -> (report, the files on A:, ok, k)"""
    img = mkimg.build(os.path.join(OUT, name + '.img'), [os.path.join(GOS, 'src', 'LODE.SYS'), SCAN])
    k = ktest.KPC(img, ata=ata); k.start()
    t0 = k.pc.us; w0 = time.time()
    if stop_at:
        tty = lambda: ''.join(k.pc.tty)
        k.select('HDSCAN.COM'); k.pc.tty.clear()
        k.key(ktest.ENTER, settle=False)
        k.pc.run_until(lambda: stop_at in tty() or k.pc.crash, sim)
        k.pc.keys.append(0x1071)                        # q
        ktest.run_answering(k.pc, lambda: k.pc.mode() == 0x40, sim)
        k.settle()
    else:
        k.run_file('HDSCAN.COM', sim)
    files = fatcheck.read_files(k.pc.drives[0].img)
    rep = files.get('A:\\HDSCAN.TXT', b'').decode('latin-1')
    print('   --- %s (%.1f s simulated, %.1f s here) ---' % (name, (k.pc.us - t0) / 1e6, time.time() - w0))
    for l in rep.splitlines(): print('   ' + l)
    ok = not k.crashed and k.pc.mode() == 0x40 and any('HDSCAN.COM ended' in l for l in k.band())
    return rep, files, ok, k

def ata_for(d, **kw):
    return pcemu.Ata(model='Conner Peripherals 3MB - TEST', cyls=CYL, heads=HEADS, spt=SPT, disk=d, **kw)

def t_scan():
    d, f, g = disk()
    ata = ata_for(d, bad=BAD)
    rep, files, ok, k = scan('scan', ata)
    check('back in the Executive, report written', ok and rep, k.band())
    check('[1] the drive: model, 100 x 4 x 17, geometry set, heads to track 0',
          '"Conner Peripherals 3MB - TEST", 100 x 4 x 17 = 3400 KB' in rep and 'heads to track 0: ok' in rep, rep[:900])
    check('[2] both partitions, as the table says',
          '1: type 04  boot 80  from sector 17, 5983 sectors = 2991 KB  FAT' in rep and
          '2: type 01  boot 00  from sector 6000, 800 sectors = 400 KB  FAT' in rep, rep[:1500])
    check('[3] FAT16: who formatted it, the label, serial, the layout',
          'Formatted by "MSDOS5.0"   label "OLDDISK    "   serial 1A2B-3C4D' in rep and
          'FAT16, 1 sector(s) (0.5 KB) a cluster, %d clusters; 2 FAT(s) of %d sectors; 512 root entries' % (f.clusters, f.spf) in rep,
          rep[:2500])
    check('the root: the label, hidden system files (r h s), sizes, dates',
          'volume label "OLDDISK    "' in rep and
          re.search(r'IO       SYS +33430  1991-04-09 05:07 r h s', rep) and
          re.search(r'COMMAND  COM +47845  1991-04-09 05:07\r?\n', rep) and
          re.search(r'DOS +<DIR>  1991-04-09 05:07', rep), rep[:3000])
    dos = rep[rep.find('  C:\\DOS\r\n'):]
    check('C:\\DOS: all %d files across its three scattered clusters, then C:\\DOS\\UTIL' % FILES16,
          all(re.search(r'F%02d +EXE +%d  ' % (i, 100 * i + 7), dos) for i in range(FILES16)) and
          '%d file(s), %d bytes' % (FILES16, sum(100 * i + 7 for i in range(FILES16))) in dos and
          '  C:\\DOS\\UTIL\r\n' in rep and re.search(r'LIST +COM +3000', rep) and re.search(r'EMPTY +TXT +0  ', rep),
          dos[:1500])
    nbytes = 33430 + 37394 + 47845 + 64 + sum(100 * i + 7 for i in range(FILES16)) + 3000
    check('altogether: 3 directories, %d files, %d bytes; the deleted entry; no long-name piece listed' % (FILES16 + 6, nbytes),
          'Altogether: 3 directories, %d files, %d bytes.  (1 deleted entries.)' % (FILES16 + 6, nbytes) in rep and
          'GONE' not in rep and 'long' not in rep, rep[rep.find('Altogether'):][:300])
    used = f.free - 2
    check('free space and the cluster marked bad, from the FAT',
          'Free: %d KB (%d clusters).  Marked bad by its format: 1 clusters.' % ((f.clusters - used - 1) // 2, f.clusters - used - 1) in rep,
          rep[rep.find('Free:'):][:200])
    check('[3] FAT12 (an old boot sector: no label), its files and directory',
          'Formatted by "IBM  3.3"\r\n' in rep and 'FAT12, 2 sector(s) (1 KB) a cluster' in rep and
          re.search(r'README +TXT +1234', rep) and '  D:\\DATA\r\n' in rep and re.search(r'A +DAT +5000  1991-04-09 05:07 r', rep) and
          'Altogether: 2 directories, 2 files, 6234 bytes.' in rep, rep[rep.find('PARTITION 2'):][:1500])
    want = ['bad: cylinder %d head %d sector %d (sector %d), error 40 (UNC)' % (chs(b) + (b,)) for b in BAD]
    check('[4] the sweep: both bad sectors named, by place and number', all(w in rep for w in want), want)
    check('... in blocks of 100 cylinders, the totals, the verdict',
          'cylinders   0- 99: 2 bad sector(s)' in rep and 'All read in' in rep and
          ': 2 bad sector(s).' in rep and "Some sectors don't read" in rep, rep[rep.find('[4]'):])
    check('A:\\HDBOOT.BIN is the first partition\'s boot sector', files.get('A:\\HDBOOT.BIN') == f.boot)
    sent = [c for c, *_ in ata.cmds]
    reads = [(c, h, n) for cmd, c, h, n in ata.cmds if cmd == 0x20]
    check('only ECh, 91h, 10h and 20h: nothing written', set(sent) <= {0xEC, 0x91, 0x10, 0x20}, sorted(set(sent)))
    check('every track read whole, once (and the two with a bad sector again, sector by sector)',
          all((c, h, 1) in reads for c in range(CYL) for h in range(HEADS)) and
          sum(1 for cmd, c, h, n in ata.cmds if cmd == 0x20 and (c, h) == chs(BAD[0])[:2]) >= 1 + SPT, len(reads))

def t_clean():
    """No bad sectors: the verdict says so."""
    d, f, g = disk()
    rep, files, ok, k = scan('clean', ata_for(d))
    check('a clean disk: "Every sector reads", 0 bad, a rate in KB/s',
          ok and ': 0 bad sector(s).' in rep and 'Every sector reads' in rep and re.search(r'\(\d+ KB/s\)', rep),
          rep[rep.find('[4]'):])

def t_sticks():
    """It sticks again part way through the sweep."""
    d, f, g = disk()
    rep, files, ok, k = scan('sticks', ata_for(d, stick_at=150))
    check('stuck again: three tracks with no answer, then it stops and says HDPROBE /X',
          ok and rep.count('no answer: cylinder') == 3 and 'The drive stopped answering: stopped at cylinder' in rep and
          'Read until then in' in rep and 'stuck again?' in rep, rep[rep.find('[4]'):])

def t_blank():
    """A blank disk: no partition table; the sweep still runs."""
    rep, files, ok, k = scan('blank', pcemu.Ata(model='Blank', cyls=20, heads=2, spt=17, disk=bytes(20 * 2 * 17 * 512)))
    check('no partition table, nothing listed, every sector read',
          ok and 'No partition table' in rep and '[3]' not in rep and 'Every sector reads' in rep, rep)

def t_stuck():
    """Stuck before it starts: [1] says so and the rest is skipped."""
    rep, files, ok, k = scan('stuck', pcemu.Ata(mech_fail=True))
    check('the heads stuck: "stuck again?", nothing else tried',
          ok and "won't go to track 0" in rep and '[2]' not in rep, rep)

def t_big():
    """The real disk's size: Joshua's own partition table (sector 0 as
    HDPROBE read it, 2026-10-07) on 762 x 8 x 39, a 121 MB FAT16 partition
    behind it (32-bit sector count, 4 sectors a cluster, a FAT of 232
    sectors), a 20 MB file; a key stops the sweep as it starts."""
    sect0 = open(os.path.join(os.path.dirname(GOS), 'rom', 'hd_cp30104h', 'HDSECT0.BIN'), 'rb').read()
    lba, n = struct.unpack_from('<II', sect0, 446 + 8)
    d = bytearray(762 * 8 * 39 * 512); d[0:512] = sect0
    f = Fat(n, 4, lba, True, label='GRID')
    root = f.tree([('BIG.DAT', 0x20, bytes(20000000)), ('GAMES', 0, [('CHESS.EXE', 0x20, b'c' * 70000)])])
    d[lba * 512:(lba + n) * 512] = f.finish(root)
    rep, files, ok, k = scan('big', pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=762, heads=8, spt=39,
                                              disk=bytes(d)), stop_at='[4] EVERY')
    check('121 MB: the partition, FAT16 with 4-sector clusters, the 20 MB file, 32-bit totals',
          ok and '1: type 06  boot 80  from sector 39, 237393 sectors = 121 MB  FAT' in rep and
          'FAT16, 4 sector(s) (2 KB) a cluster, %d clusters; 2 FAT(s) of %d sectors' % (f.clusters, f.spf) in rep and
          re.search(r'BIG +DAT +20000000  ', rep) and 'Altogether: 2 directories, 2 files, 20070000 bytes.' in rep and
          'Free: %d KB (%d clusters).' % ((f.clusters - (f.free - 2)) * 2, f.clusters - (f.free - 2)) in rep, rep)
    check('a key stops the sweep at once ("Stopped (a key) at cylinder 0 or 1"), and no "every sector reads"',
          re.search(r'Stopped \(a key\) at cylinder [01]\r\n', rep) and "None bad so far; the rest wasn't read." in rep and
          'Every sector reads' not in rep, rep[rep.find('[4]'):])

TESTS = [t_scan, t_clean, t_sticks, t_blank, t_stuck, t_big]
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
