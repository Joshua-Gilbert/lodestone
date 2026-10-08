"""Helpers for testing DEFRAG.COM in the emulator: fragmented images, a
run through the command prompt, and a layout summary."""
import os, sys, struct, subprocess, random
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, fatcheck, pcemu, fat16img as F

DEFRAG = os.path.join(GOS, 'src', 'DEFRAG.COM')


def mcopy(img, data, name, tmpdir):
    p = os.path.join(tmpdir, 'x.bin'); open(p, 'wb').write(data)
    subprocess.run(['mcopy', '-o', '-i', img, p, '::' + name], check=True)


def fragmented(path, tmpdir, seed=1, extra=(), size=1440):
    """A 1.44 MB floppy with the system files, then files deleted and
    rewritten so that several are in pieces, and deleted root entries."""
    rnd = random.Random(seed)
    img = mkimg.build(path, [os.path.join(GOS, 'src', 'GRIDOS.SYS'), os.path.join(GOS, 'src', 'GRIDCMD.COM'),
                             DEFRAG] + list(extra), size=size)
    for i in range(30):
        mcopy(img, bytes(rnd.randrange(256) for _ in range(3000 + 37 * i)), 'X%02d.DAT' % i, tmpdir)
    subprocess.run(['mdel', '-i', img] + ['::X%02d.DAT' % i for i in range(1, 30, 2)], check=True)
    mcopy(img, bytes(rnd.randrange(256) for _ in range(40000)), 'BIG1.DAT', tmpdir)
    mcopy(img, bytes(rnd.randrange(256) for _ in range(9000)), 'MED.DAT', tmpdir)
    subprocess.run(['mdel', '-i', img] + ['::X%02d.DAT' % i for i in range(0, 12, 4)], check=True)
    mcopy(img, bytes(rnd.randrange(256) for _ in range(25000)), 'BIG2.DAT', tmpdir)
    subprocess.run(['mmd', '-i', img, '::SUB'], check=True)
    for i in range(4):
        mcopy(img, bytes(rnd.randrange(256) for _ in range(2500 * (i + 1))), 'SUB/S%d.DAT' % i, tmpdir)
    subprocess.run(['mdel', '-i', img, '::X14.DAT', '::X22.DAT'], check=True)
    mcopy(img, bytes(rnd.randrange(256) for _ in range(30000)), 'SUB/BIG3.DAT', tmpdir)
    subprocess.run(['mdel', '-i', img, '::X16.DAT', '::X20.DAT', '::X24.DAT', '::SUB/S1.DAT'], check=True)
    return img


def layout(raw):
    """(files in pieces, free runs, root entries before the end marker)."""
    b = fatcheck.bpb(raw)
    fat = raw[b['res'] * 512:(b['res'] + b['spf']) * 512]
    get = lambda n: (struct.unpack_from('<H', fat, n * 3 // 2)[0] >> 4) if n & 1 else (struct.unpack_from('<H', fat, n * 3 // 2)[0] & 0xFFF)
    root = (b['res'] + b['nfat'] * b['spf']) * 512
    rsec = (b['nroot'] * 32 + 511) // 512
    data = b['res'] + b['nfat'] * b['spf'] + rsec
    ncl = (b['tot'] - data) // b['spc'] + 2
    frag = []
    def walk(entries, path):
        for e in entries:
            if e[0] in (0, 0xE5) or e[11] == 0x0F or e[11] & 8 or e[0] == ord('.'): continue
            st = struct.unpack_from('<H', e, 26)[0]
            name = path + e[:8].decode('latin-1').strip() + ('.' + e[8:11].decode('latin-1').strip() if e[8:11].strip() else '')
            c, chain = st, []
            while 2 <= c < 0xFF8 and len(chain) < 4000:
                chain.append(c); c = get(c)
            if any(b2 != a + 1 for a, b2 in zip(chain, chain[1:])): frag.append(name)
            if e[11] & 0x10:
                sub = b''.join(raw[(data + (cc - 2) * b['spc']) * 512:(data + (cc - 1) * b['spc']) * 512] for cc in chain)
                walk([sub[i:i + 32] for i in range(0, len(sub), 32)], name + '\\')
    rootb = raw[root:root + rsec * 512]
    ents = [rootb[i:i + 32] for i in range(0, len(rootb), 32)]
    used = next((i for i, e in enumerate(ents) if e[0] == 0), len(ents))
    walk(ents[:used], '')
    runs, s = [], None
    for n in range(2, ncl + 1):
        f = n < ncl and get(n) == 0
        if f and s is None: s = n
        if not f and s is not None: runs.append((s, n - 1)); s = None
    return frag, runs, used


def run(img, tail=' /S', sim_s=3600, disk_model='flat', before_start=None, during=None, syms=None, **kw):
    """Boot, CODE-P, 'DEFRAG<tail>'; run until it exits.  -> (k, exit code)
    (exit code None if it didn't finish).  during(k) is called every few
    simulated seconds while it runs."""
    k = ktest.KPC(img, disk_model=disk_model, **kw)
    if syms: k.Y = ktest.Syms(syms)
    if before_start: before_start(k)
    k.start()
    k.key(ktest.CODE_P)
    k.key('defrag' + tail)
    f4c = 0x600 + k.Y['f_4C']
    seen = []
    k.pc.watch = lambda a: seen.append(1) if a == f4c else None
    k.key(ktest.ENTER, settle=False)
    end = k.pc.us + sim_s * 1e6
    while not seen and k.pc.us < end and not k.crashed:
        k.pc.run_until(lambda: seen, 2.0)
        if during and not seen: during(k)
    k.pc.watch = None
    if not seen: return k, None
    k.settle(5)
    return k, k.pc.u16(0x60, k.Y['last_exit']) & 0xFF


# ---------------------------------------------------------------------
#  drive C: (pcemu.Ata), FAT16: the geometry of test_hd's disk (220 x 8 x
#  39, the partition from sector 39, 2 KB clusters), so the data runs past
#  sector 65,535 of the partition (cluster 16344 holds 65535-65538)
# ---------------------------------------------------------------------
HD_CYL, HD_HEADS, HD_SPT, HD_PLBA = 220, 8, 39, 39


def hd_put(f, cls, data):
    """data into clusters cls (in that order), chained -> the first."""
    per = 512 * f.spc
    for i, c in enumerate(cls):
        f.put(c, data[i * per:(i + 1) * per])
    for a, b in zip(cls, cls[1:] + [f.end]): f.fat[a] = b
    return cls[0]


def hd_fragmented(seed=1, big=300):
    """A FAT16 C: in need of tidying -> (disk bytes, Fat, {path: bytes}).
    A system file at the start (stays), gaps, a file in three pieces (the
    last past sector 65,535), files after gaps, deleted root entries, a
    subdirectory past the boundary (directories stay) with a moving file and
    one in pieces, a 600 KB file far on, a lost cluster and a bad one."""
    rnd = random.Random(seed)
    data = lambda n: bytes(rnd.randrange(256) for _ in range(n))
    f = F.Fat(HD_CYL * HD_HEADS * HD_SPT - HD_PLBA, 4, HD_PLBA, True, label='GRIDHD')
    files = {}
    def fl(name, cls, size, attr=0x20):
        b = data(size); files[name] = b
        return f.ent(name.split('\\')[-1], attr, hd_put(f, cls, b), size)
    gone = lambda name: b'\xE5' + f.ent(name, 0x20, 0, 0)[1:]
    root = [f.ent('GRIDHD', 0x08, 0, 0)]
    root.append(fl('IO.SYS', list(range(2, 10)), 8 * 2048 - 100, 0x07))
    root.append(gone('OLD1.TXT'))
    root.append(fl('B.TXT', list(range(20, 25)), 5 * 2048 - 7))
    root += [gone('OLD%d.TXT' % i) for i in range(2, 9)]
    root.append(fl('FRAG1.DAT', [25, 26, 27, 200, 201, 202, 203, 204, 16500, 16501, 16502], 11 * 2048 - 33))
    root.append(fl('C.DAT', list(range(300, 350)), 50 * 2048))
    root.append(gone('OLD9.TXT'))
    root.append(fl('BIG.DAT', list(range(16700, 16700 + big)), big * 2048 - 1))
    sub = [f.ent('.', 0x10, 16400, 0), f.ent('..', 0x10, 0, 0)]
    sub.append(fl('SUB\\S1.DAT', list(range(16405, 16421)), 16 * 2048 - 5))
    sub.append(gone('S0.DAT'))
    sub.append(fl('SUB\\S2.DAT', [16430, 16431] + list(range(16600, 16606)), 8 * 2048 - 2000))
    f.fat[16400] = f.end
    f.put(16400, b''.join(sub))
    root.append(f.ent('SUB', 0x10, 16400, 0))
    f.fat[17050] = f.end                                # lost: nobody's
    f.fat[500] = 0xFFF7                                 # bad
    f.free = f.clusters + 2
    f.finish(b''.join(root))
    return F.disk(HD_CYL, HD_HEADS, HD_SPT, HD_PLBA, f), f, files


def hd_drive(d, **kw):
    return pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=HD_CYL, heads=HD_HEADS, spt=HD_SPT,
                     disk=d, **kw)


def hd_boot(path, extra=()):
    """A boot floppy: the kernel, the shell and DEFRAG."""
    return mkimg.build(path, [os.path.join(GOS, 'src', 'GRIDOS.SYS'), os.path.join(GOS, 'src', 'GRIDCMD.COM'),
                              DEFRAG] + list(extra))


def hd_layout(ata, allow=(17050,), plba=HD_PLBA):
    """(Volume, {path: bytes}, problems, [files in pieces], free runs);
    lost clusters but those in allow are problems."""
    v = F.Volume(ata.disk, plba)
    files, probs = v.files(allow=set(allow))
    frag = []
    def walk(cl, path):
        for name, attr, first, size in v.entries(cl):
            if name in ('.', '..') or attr & 8: continue
            chain = v.chain(first)[0]
            if any(b != a + 1 for a, b in zip(chain, chain[1:])): frag.append(path + name)
            if attr & 0x10: walk(first, path + name + '\\')
    walk(0, '')
    runs, st = [], None
    for c in range(2, v.ncl + 1):
        fr = c < v.ncl and v.fat(c) == 0
        if fr and st is None: st = c
        if not fr and st is not None: runs.append((st, c - 1)); st = None
    return v, {k[1:]: b for k, b in files.items()}, probs, frag, runs


def hd_add(ata, name, data, plba=HD_PLBA):
    """Another system adds a file to C:'s root: the first free slot (deleted
    or the end), the first free clusters, both FATs."""
    v = F.Volume(ata.disk, plba)
    d = ata.disk
    base = (plba + v.root) * 512
    slot = next(i for i in range(v.nroot) if d[base + 32 * i] in (0, 0xE5))
    n = -(-len(data) // (512 * v.spc))
    cls = [c for c in range(2, v.ncl) if v.fat(c) == 0][:n]
    for i, c in enumerate(cls):
        o = (plba + v.data + (c - 2) * v.spc) * 512
        chunk = data[i * 512 * v.spc:(i + 1) * 512 * v.spc]
        d[o:o + len(chunk)] = chunk
        nxt = cls[i + 1] if i + 1 < len(cls) else 0xFFFF
        for k in range(v.nfats):
            struct.pack_into('<H', d, (plba + v.rsv + k * v.spf) * 512 + 2 * c, nxt)
    d[base + 32 * slot:base + 32 * slot + 32] = F.Fat.ent(name, 0x20, cls[0], len(data))
