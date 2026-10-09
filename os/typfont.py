"""GRiD InteGRiD font (.TYP) -> FONT.INC for Lodestone.

    python3 typfont.py PATH\\TO\\TC8X16.TYP > src/FONT.INC
    python3 typfont.py TC8X16.TYP --fnt TC8X16.FNT       (a font file for System's Display)
    python3 typfont.py TC8X16.TYP --sheet sheet.png      (all glyphs, for a look)

A .TYP file is an OMF object module (GRiD linked fonts into programs; GRID.EXE
carries TC8X16 and TC8X8 built in).  Its data segment is an 8-byte header

    n (number of characters, codes 0..n-1), width, height, line height,
    baseline, 0, 0, 0

then the glyphs as a strike: row 0 of every character, then row 1, and so
on, ceil(width / 8) bytes per character per row, leftmost pixel in the top
bit.  TC8X16 (n = 255, 8 x 16, line height 16, baseline 14) is the system
font InteGRiD used on 640 x 400 screens; it is byte for byte the 8 x 16
font inside GRID.EXE.

FONT.INC is what the Lodestone blitters use: 16 bytes per character, codes
32-127 (127 is a solid block in both GRiD's font and ours).
"""
import struct, sys


def omf_data(b):
    """The largest LEDATA segment of an OMF object module, as bytes."""
    segs, i = {}, 0
    while i < len(b):
        t, n = b[i], struct.unpack_from('<H', b, i + 1)[0]
        d = b[i + 3:i + 2 + n]                      # (without the checksum)
        if t == 0xA0:                               # LEDATA: seg, offset, data
            s = segs.setdefault(d[0], bytearray())
            off, data = struct.unpack_from('<H', d, 1)[0], d[3:]
            if len(s) < off + len(data): s.extend(bytes(off + len(data) - len(s)))
            s[off:off + len(data)] = data
        elif t == 0xA2:
            raise ValueError('LIDATA records are not supported')
        i += 3 + n
        if t == 0x8A: break                         # MODEND
    return bytes(max(segs.values(), key=len))


def load(path):
    s = omf_data(open(path, 'rb').read())
    n, w, h, lh, base = s[:5]
    bpr = (w + 7) // 8
    if len(s) < 8 + n * h * bpr: raise ValueError('%s: short glyph data' % path)
    g = {}
    for c in range(n):
        g[c] = [int.from_bytes(s[8 + (r * n + c) * bpr:8 + (r * n + c + 1) * bpr], 'big') for r in range(h)]
    return dict(n=n, w=w, h=h, lh=lh, base=base, bpr=bpr, glyphs=g)


def font_inc(f, name):
    if (f['w'], f['h']) != (8, 16): raise ValueError('Lodestone needs an 8 x 16 font (this one is %d x %d)' % (f['w'], f['h']))
    out = ['; 8x16 font, ASCII 32-126 (+127 = solid block): GRiD\'s InteGRiD system',
           '; font %s (the 8 x 16 font built into GRID.EXE), GRiD Systems Corp.' % name,
           '; Made from the .TYP file by typfont.py.',
           'font:']
    for c in range(32, 128):
        rows = f['glyphs'][c]
        ch = '"\'"' if c == 39 else "'%s'" % chr(c) if c < 127 else 'block'
        out.append('        db ' + ','.join('%03Xh' % v for v in rows) + '   ; ' + ch)
    return '\n'.join(out) + '\n'


def sheet(f, path, scale=3, cols=32):
    from PIL import Image
    W, H = f['w'] + 2, f['h'] + 2
    im = Image.new('L', (cols * W, (f['n'] + cols - 1) // cols * H), 40)
    px = im.load()
    for c, g in f['glyphs'].items():
        x0, y0 = c % cols * W + 1, c // cols * H + 1
        for r, v in enumerate(g):
            for x in range(f['w']):
                if v >> (f['bpr'] * 8 - 1 - x) & 1: px[x0 + x, y0 + r] = 255
    im.resize((im.width * scale, im.height * scale), Image.NEAREST).save(path)


if __name__ == '__main__':
    path = sys.argv[1]
    f = load(path)
    if '--sheet' in sys.argv:
        sheet(f, sys.argv[sys.argv.index('--sheet') + 1])
    elif '--fnt' in sys.argv:
        if (f['w'], f['h']) != (8, 16): sys.exit('a .FNT is 8 x 16 (this one is %d x %d)' % (f['w'], f['h']))
        open(sys.argv[sys.argv.index('--fnt') + 1], 'wb').write(bytes(f['glyphs'][c][r] for c in range(32, 128) for r in range(16)))
    else:
        import os
        sys.stdout.write(font_inc(f, os.path.splitext(os.path.basename(path))[0].upper()))
