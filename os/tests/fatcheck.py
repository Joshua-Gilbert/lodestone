"""Check a FAT12 floppy image the way CHKDSK would: both FAT copies equal,
every chain valid and the right length for its file, no cluster in two
chains, no lost clusters, "." and ".." right in every subdirectory.

    problems, files = check(open('a.img','rb').read())
"""
import struct, sys


def bpb(img):
    bps, spc, res, nfat, nroot, tot16, media, spf, spt, heads = struct.unpack_from('<HBHBHHBHHH', img, 11)
    return dict(bps=bps, spc=spc, res=res, nfat=nfat, nroot=nroot, tot=tot16, spf=spf)


def check(img):
    b = bpb(img)
    bps, spc = b['bps'], b['spc']
    fat_off = b['res'] * bps
    fats = [img[fat_off + i * b['spf'] * bps: fat_off + (i + 1) * b['spf'] * bps] for i in range(b['nfat'])]
    probs = []
    if any(f != fats[0] for f in fats[1:]): probs.append('FAT copies differ')
    fat = fats[0]
    root_off = fat_off + b['nfat'] * b['spf'] * bps
    root_secs = (b['nroot'] * 32 + bps - 1) // bps
    data_sec = b['res'] + b['nfat'] * b['spf'] + root_secs
    nclu = (b['tot'] - data_sec) // spc + 2
    def get(n):
        v = struct.unpack_from('<H', fat, n * 3 // 2)[0]
        return v >> 4 if n & 1 else v & 0xFFF
    def chain(start, what):
        out = []
        n = start
        while True:
            if n < 2 or n >= nclu:
                probs.append('%s: bad cluster %d in chain' % (what, n)); break
            out.append(n)
            if len(out) > nclu: probs.append('%s: chain loops' % what); break
            v = get(n)
            if v >= 0xFF8: break
            if v == 0 or v == 0xFF7:
                probs.append('%s: chain hits %s at %d' % (what, 'free' if v == 0 else 'bad', n)); break
            n = v
        return out
    def cluster_data(n):
        o = (data_sec + (n - 2) * spc) * bps
        return img[o:o + spc * bps]
    owner = {}
    files = {}
    def claim(cl, what):
        for c in cl:
            if c in owner: probs.append('%s: cluster %d cross-linked with %s' % (what, c, owner[c]))
            owner[c] = what
    def walk(raw, path, mycl, parentcl):
        for i in range(0, len(raw), 32):
            e = raw[i:i + 32]
            if e[0] == 0: break
            if e[0] == 0xE5 or e[11] == 0x0F or e[11] & 8: continue
            name = e[0:8].decode('latin-1').rstrip()
            ext = e[8:11].decode('latin-1').rstrip()
            full = name + ('.' + ext if ext else '')
            attr, cl, size = e[11], struct.unpack_from('<H', e, 26)[0], struct.unpack_from('<I', e, 28)[0]
            if name in ('.', '..'):
                want = mycl if name == '.' else parentcl
                if path == '': probs.append('root has a %s entry' % name)
                elif cl != want: probs.append('%s\\%s points at %d, should be %d' % (path, name, cl, want))
                continue
            p = path + '\\' + full
            if attr & 0x10:
                if cl == 0: probs.append('%s: directory with no cluster' % p); continue
                cls = chain(cl, p); claim(cls, p)
                files[p + '\\'] = 0
                data = b''.join(cluster_data(c) for c in cls)
                if data[0:1] != b'.' or data[32:34] != b'..': probs.append('%s: no . and .. at the start' % p)
                walk(data, p, cl, mycl)
            else:
                files[p] = size
                if size == 0:
                    if cl != 0: probs.append('%s: empty but has cluster %d' % (p, cl))
                    continue
                cls = chain(cl, p); claim(cls, p)
                need = (size + spc * bps - 1) // (spc * bps)
                if len(cls) != need:
                    probs.append('%s: %d bytes need %d clusters, chain has %d' % (p, size, need, len(cls)))
    walk(img[root_off:root_off + b['nroot'] * 32], '', 0, 0)
    lost = [n for n in range(2, nclu) if get(n) not in (0, 0xFF7) and n not in owner]
    if lost: probs.append('%d lost clusters (%s...)' % (len(lost), lost[:8]))
    return probs, files


if __name__ == '__main__':
    p, f = check(open(sys.argv[1], 'rb').read())
    for k in sorted(f): print('%-30s %d' % (k, f[k]))
    print('\n'.join(p) if p else 'no problems')


def read_files(img, drive='A', dirs=None):
    """Every file's bytes: {'A:\\DIR\\NAME.EXT': bytes}.  The subjects go in
    the list dirs, if one is given ('A:\\DIR').  img may be pcemu's own
    bytearray: only the root and each file's clusters are copied."""
    b = bpb(img)
    bps, spc = b['bps'], b['spc']
    fat_off = b['res'] * bps
    fat = img[fat_off:fat_off + b['spf'] * bps]
    root_off = fat_off + b['nfat'] * b['spf'] * bps
    root_secs = (b['nroot'] * 32 + bps - 1) // bps
    data_sec = b['res'] + b['nfat'] * b['spf'] + root_secs
    def get(n):
        v = struct.unpack_from('<H', fat, n * 3 // 2)[0]
        return v >> 4 if n & 1 else v & 0xFFF
    def chain_data(cl):
        out = bytearray(); seen = 0
        while 2 <= cl < 0xFF0 and seen < 4096:
            o = (data_sec + (cl - 2) * spc) * bps
            out += img[o:o + spc * bps]; cl = get(cl); seen += 1
        return bytes(out)
    files = {}
    def walk(raw, path):
        for i in range(0, len(raw), 32):
            e = raw[i:i + 32]
            if e[0] == 0: break
            if e[0] == 0xE5 or e[11] == 0x0F or e[11] & 8: continue
            name = e[0:8].decode('latin-1').rstrip(); ext = e[8:11].decode('latin-1').rstrip()
            if name in ('.', '..'): continue
            full = path + '\\' + name + ('.' + ext if ext else '')
            cl, size = struct.unpack_from('<H', e, 26)[0], struct.unpack_from('<I', e, 28)[0]
            if e[11] & 0x10:
                if dirs is not None: dirs.append(full)
                walk(chain_data(cl), full)
            else: files[full] = chain_data(cl)[:size] if size else b''
    walk(img[root_off:root_off + b['nroot'] * 32], drive + ':')
    return files
