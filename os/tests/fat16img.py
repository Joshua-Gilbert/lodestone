"""Hard-disk images for pcemu.Ata: a partition table and FAT12/16
partitions laid out as DOS would (but for directories, whose clusters are
scattered), and a reader that walks one back and checks it as CHKDSK
would: both FATs alike, every chain to its end, no cluster in two files,
none lost.
"""
import struct

DATE = ((1991 - 1980) << 9) | (4 << 5) | 9          # 1991-04-09
TIME = (5 << 11) | (7 << 5)                        # 05:07


class Fat:
    """A FAT12/16 partition image (s.img): files and directories added
    with tree(), then finish() writes the root and the FATs."""
    def __init__(s, sectors, spc, hidden, fat16, label=None, oem=b'MSDOS5.0', rootents=512, nfats=2,
                 spt=17, heads=4):
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
                         sectors if sectors < 65536 else 0, 0xF8, spf, spt, heads, hidden)
        if sectors >= 65536: struct.pack_into('<I', b, 0x20, sectors)
        if label:
            b[0x24] = 0x80; b[0x26] = 0x29; struct.pack_into('<I', b, 0x27, 0x1A2B3C4D)
            b[0x2B:0x36] = label.ljust(11).encode(); b[0x36:0x3E] = b'FAT16   ' if fat16 else b'FAT12   '
        b[510:512] = b'\x55\xAA'
        s.img[0:512] = b; s.boot = bytes(b)
        s.fat = [0] * (cl + 2); s.fat[0] = 0xFFF8 if fat16 else 0xFF8; s.fat[1] = 0xFFFF if fat16 else 0xFFF
        s.free = 2
        s.data = 1 + nfats * spf + s.rootsecs
        s.end = 0xFFFF if fat16 else 0xFFF
        s.gaps = set()                                  # used clusters no file owns

    def lba(s, cl):
        """A cluster's first sector, in the partition."""
        return s.data + (cl - 2) * s.spc

    def alloc(s, n):
        got = list(range(s.free, s.free + n)); s.free += n
        for a, b in zip(got, got[1:] + [s.end]): s.fat[a] = b
        return got

    def skip_to(s, cl):
        """Allocation goes on from cluster cl (the ones skipped stay free)."""
        assert cl >= s.free
        s.free = cl

    def put(s, cl, data):
        off = s.lba(cl) * 512
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
        """items: [(name, attr, bytes, or [items] for a directory, or None
        for a label)] -> the directory's entries (the root's if cl is None).
        A subdirectory's clusters are taken one by one with a used cluster
        between, so its chain is scattered."""
        ents = []
        if cl is not None: ents += [s.ent('.', 0x10, cl[0], 0), s.ent('..', 0x10, parent, 0)]
        for name, attr, body in items:
            if isinstance(body, list):
                per = 16 * s.spc
                n = -(-(len(body) + 2) // per)
                chain = s.alloc(1)
                for _ in range(n - 1):
                    s.gaps.add(s.write(b'x' * 512 * s.spc))  # a gap: the chain is scattered
                    chain += s.alloc(1)
                for a, b2 in zip(chain, chain[1:] + [s.end]): s.fat[a] = b2
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


def mbr(parts, cyls, heads, spt):
    """Sector 0: parts = [(boot, type, first LBA, sectors)]."""
    def chs(lba):
        c, r = divmod(lba, heads * spt); h, sct = divmod(r, spt)
        c = min(c, 1023)
        return h, sct + 1 | (c >> 8 << 6), c & 255
    m = bytearray(512)
    for i, (boot, typ, start, n) in enumerate(parts):
        m[446 + 16 * i:462 + 16 * i] = struct.pack('<B3sB3sII', boot, bytes(chs(start)), typ, bytes(chs(start + n - 1)), start, n)
    m[510:512] = b'\x55\xAA'
    return bytes(m)


def disk(cyls, heads, spt, part_lba, fat, extra=()):
    """The whole disk: the partition table, then fat's image at part_lba."""
    d = bytearray(cyls * heads * spt * 512)
    d[0:512] = mbr([(0x80, 0x06 if fat.n >= 65536 else 0x04, part_lba, fat.n)] + list(extra), cyls, heads, spt)
    d[part_lba * 512:(part_lba + fat.n) * 512] = fat.img
    return d


class Volume:
    """A FAT12/16 partition read back from a disk image: files, and a check."""
    def __init__(s, img, part_lba):
        s.d = img; s.p = part_lba
        b = s.sec(0)
        s.spc = b[13]; s.rsv, = struct.unpack_from('<H', b, 14); s.nfats = b[16]
        s.nroot, tot16 = struct.unpack_from('<HH', b, 17); s.spf, = struct.unpack_from('<H', b, 22)
        s.total = tot16 or struct.unpack_from('<I', b, 32)[0]
        s.root = s.rsv + s.nfats * s.spf
        s.data = s.root + (s.nroot * 32 + 511) // 512
        s.ncl = (s.total - s.data) // s.spc + 2
        s.fat16 = s.ncl - 2 >= 4085
        s.fats = [bytes(s.d[(s.p + s.rsv + k * s.spf) * 512:(s.p + s.rsv + (k + 1) * s.spf) * 512]) for k in range(s.nfats)]

    def sec(s, n, count=1):
        return bytes(s.d[(s.p + n) * 512:(s.p + n + count) * 512])

    def fat(s, cl, k=0):
        f = s.fats[k]
        if s.fat16: return struct.unpack_from('<H', f, cl * 2)[0]
        v = struct.unpack_from('<H', f, cl * 3 // 2)[0]
        v = v >> 4 if cl & 1 else v & 0xFFF
        return v | 0xF000 if v >= 0xFF0 else v

    def chain(s, cl):
        out = []
        while 2 <= cl < 0xFFF0 and len(out) <= s.ncl:
            out.append(cl); cl = s.fat(cl)
        return out, cl

    def clu(s, cl):
        return s.sec(s.data + (cl - 2) * s.spc, s.spc)

    def entries(s, cl):
        raw = s.sec(s.root, s.data - s.root) if cl == 0 else b''.join(s.clu(c) for c in s.chain(cl)[0])
        for i in range(0, len(raw), 32):
            e = raw[i:i + 32]
            if e[0] == 0: break
            if e[0] == 0xE5 or e[11] == 0x0F or e[11] & 8: continue
            name = e[:8].decode('latin-1').rstrip() + ('.' + e[8:11].decode('latin-1').rstrip() if e[8:11].strip() else '')
            yield name, e[11], struct.unpack_from('<H', e, 26)[0], struct.unpack_from('<I', e, 28)[0]

    def files(s, allow=()):
        """{path: bytes} for every file, and a list of problems (lost
        clusters but those in allow)."""
        out, probs, owner = {}, [], {}
        def walk(cl, path, depth=0):
            if depth > 20: probs.append('too deep: ' + path); return
            if cl:
                for c in s.chain(cl)[0]:
                    if c in owner: probs.append('%s: cluster %d also in %s' % (path, c, owner[c]))
                    owner[c] = path
            for name, attr, first, size in s.entries(cl):
                if name in ('.', '..'): continue
                p = path + '\\' + name
                if attr & 0x10: walk(first, p, depth + 1); continue
                cls, end = s.chain(first)
                for c in cls:
                    if c in owner: probs.append('%s: cluster %d also in %s' % (p, c, owner[c]))
                    owner[c] = p
                need = -(-size // (512 * s.spc))
                if len(cls) != need: probs.append('%s: %d clusters for %d bytes' % (p, len(cls), size))
                if cls and end < 0xFFF8: probs.append('%s: chain ends %04X' % (p, end))
                out[p] = b''.join(s.clu(c) for c in cls)[:size]
        walk(0, '')
        if s.nfats > 1 and s.fats[0] != s.fats[1]: probs.append('the two FATs differ')
        lost = [c for c in range(2, s.ncl) if s.fat(c) not in (0, 0xFFF7) and c not in owner and c not in allow]
        if lost: probs.append('%d lost clusters (%d...)' % (len(lost), lost[0]))
        return out, probs

    def free(s):
        return sum(1 for c in range(2, s.ncl) if s.fat(c) == 0)
