"""Helpers for testing DEFRAG.COM in the emulator: fragmented images, a
run through the command prompt, and a layout summary."""
import os, sys, struct, subprocess, random
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, fatcheck

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
