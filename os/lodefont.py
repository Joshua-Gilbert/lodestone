"""Lodefont (fonts/LODEFONT.TXT, # and . rows) -> src/FONT.INC, the built-in font.

    python3 lodefont.py                      (writes src/FONT.INC)
    python3 lodefont.py --fnt LODEFONT.FNT   (the same glyphs as a font file)
    python3 lodefont.py --sheet sheet.png    (all glyphs, for a look)

Run it after changing LODEFONT.TXT, then build.sh: the core, System and DEFRAG
include FONT.INC.  The layout is typfont.py's, which pcemu.load_font reads.
"""
import os, re, sys
import typfont

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'fonts', 'LODEFONT.TXT')
INC = os.path.join(HERE, 'src', 'FONT.INC')
HEAD = ['8x16 font, ASCII 32-126 (+127 = solid block): Lodefont, Lodestone\'s own.',
        'Made from fonts/LODEFONT.TXT by lodefont.py: change that, not this.']


def load(path=SRC):
    """LODEFONT.TXT -> typfont's font dict (codes 32-127)."""
    g, code, rows = {}, None, []
    with open(path) as f: text = f.read().splitlines()
    for n, line in enumerate(text, 1):
        line = line.rstrip()
        if not line or line.startswith(';'): continue
        m = re.match(r'([0-9A-Fa-f]{2})h\b', line)
        if m:
            if code is not None: raise ValueError('%s:%d: glyph %02Xh has %d rows' % (path, n, code, len(rows)))
            code, rows = int(m.group(1), 16), []
            if not 32 <= code <= 127 or code in g: raise ValueError('%s:%d: code %02Xh' % (path, n, code))
            continue
        if code is None or not re.fullmatch(r'[#.]{8}', line):
            raise ValueError('%s:%d: not a row of 8 # and .: %r' % (path, n, line))
        rows.append(int(line.replace('#', '1').replace('.', '0'), 2))
        if len(rows) == 16: g[code], code = rows, None
    if code is not None or sorted(g) != list(range(32, 128)):
        raise ValueError('%s: needs codes 20h-7Fh, 16 rows each' % path)
    return dict(n=128, w=8, h=16, bpr=1, glyphs=g)


if __name__ == '__main__':
    f = load()
    if '--sheet' in sys.argv:
        shown = dict(f, n=96, glyphs={c - 32: g for c, g in f['glyphs'].items()})     # (from the space)
        typfont.sheet(shown, sys.argv[sys.argv.index('--sheet') + 1])
    elif '--fnt' in sys.argv:
        with open(sys.argv[sys.argv.index('--fnt') + 1], 'wb') as o: o.write(typfont.fnt(f))
    else:
        with open(INC, 'w', newline='\n') as o: o.write(typfont.font_inc(f, 'LODEFONT', HEAD))
