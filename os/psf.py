import gzip, struct
def load(path):
    d = gzip.open(path).read()
    if d[:4] == b'\x72\xb5\x4a\x86':
        _, ver, hsz, flags, n, cb, h, w = struct.unpack('<IIIIIIII', d[:32])
        glyphs = [d[hsz + i * cb: hsz + (i + 1) * cb] for i in range(n)]
        tab = d[hsz + n * cb:]; umap = {}
        if flags & 1:
            i = 0; g = 0
            while g < n and i < len(tab):
                j = i
                while tab[j] != 0xFF: j += 1
                for ch in tab[i:j].decode('utf-8', 'ignore').split('￾')[0]: umap.setdefault(ord(ch), g)
                i = j + 1; g += 1
        return glyphs, umap, w, h
    mode, cs = d[2], d[3]; n = 512 if mode & 1 else 256
    glyphs = [d[4 + i * cs: 4 + (i + 1) * cs] for i in range(n)]
    umap = {}
    if mode & 2:
        tab = d[4 + n * cs:]; g = 0; i = 0
        while g < n and i + 1 < len(tab):
            u = struct.unpack('<H', tab[i:i + 2])[0]; i += 2
            if u == 0xFFFF: g += 1; continue
            umap.setdefault(u, g)
    return glyphs, umap, 8, cs
def ascii16(path):
    glyphs, umap, w, h = load(path)
    assert w == 8 and h == 16, (w, h)
    return [glyphs[umap.get(c, c)] for c in range(256)]
