"""The start-up picture: Fig. 1 of F. A. Annett, Electrical Machinery (1921),
"Lodestone attracting some iron nails" (public domain), as vectors, and
beside it LODESTONE, underlined.

    python3 mksplash.py            writes ../src/SPLASH.INC and splash.png

SPLASH.INC is the drawing for ../src/SPLASH.ASM, which builds LODE.PIC: the
picture program the kernel's bootstrap (KSPLASH.INC) loads, runs and drops
at start-up.

trace.txt holds the drawing in the plate's own pixels (532 x 668): the
stone's outline and the nails, head first.  This scales it to the screen,
packs it, and draws it exactly as SPLASH.ASM does, for the tests and the
preview.  1 bit, mode 40h: lit or not.

The picture is the plate as printed: lit paper, a dark stone; a nail is
lit where it lies on the stone and dark where it crosses the paper.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 640, 400
NUM, DEN = 9, 16                    # plate pixels -> screen: 9/16
PX, PY = 24, 12                     # the plate's top left on the screen
PW, PH = 299, 375                   # its size (532 x 668 at 9/16)
TAPER = 3                           # a nail's last 3 pixels: 2, 2, then 1 wide (the point)

# The title: "LODESTONE" in chamfered capitals, like the lettering of a
# 1920s engineering drawing.  Each glyph is strokes on a 20 x 32 grid; a
# stroke is a polyline.  Drawn 2 pixels wide.
GLYPHS = {
    'L': [[(0, 0), (0, 32), (20, 32)]],
    'O': [[(6, 0), (14, 0), (20, 6), (20, 26), (14, 32), (6, 32), (0, 26), (0, 6), (6, 0)]],
    'D': [[(0, 0), (12, 0), (20, 8), (20, 24), (12, 32), (0, 32), (0, 0)]],
    'E': [[(20, 0), (0, 0), (0, 32), (20, 32)], [(0, 16), (14, 16)]],
    'S': [[(20, 5), (15, 0), (5, 0), (0, 5), (0, 11), (5, 16), (15, 16), (20, 21), (20, 27), (15, 32), (5, 32), (0, 27)]],
    'T': [[(0, 0), (20, 0)], [(10, 0), (10, 32)]],
    'N': [[(0, 32), (0, 0), (20, 32), (20, 0)]],
}
TITLE = 'LODESTONE'
TADV = 28                           # letter advance
TW = (len(TITLE) - 1) * TADV + 22   # its width (2-pixel strokes)
TX = (PX + PW + W - TW) // 2        # centred in the space beside the plate,
TY = (H - 40) // 2                  #  with its rule, 40 rows in all
RULE = (TX, TX + TW, TY + 38)       # the rule under it: x0, x1 (excl.), y


def read_trace(path=os.path.join(HERE, 'trace.txt')):
    rock, nails = [], []
    for ln in open(path):
        ln = ln.split('#')[0].split()
        if not ln:
            continue
        if ln[0] == 'R':
            rock.append((float(ln[1]), float(ln[2])))
        elif ln[0] == 'N':
            nails.append(tuple(float(v) for v in ln[1:5]))
    return rock, nails


def to_screen(x, y):
    """plate pixel -> screen pixel, rounded (the same for every point)"""
    return (int(x * NUM / DEN + 0.5) + PX, int(y * NUM / DEN + 0.5) + PY)


def build(rock, nails):
    """screen-space outline and nails (head, tip), nails sorted by head row"""
    poly = []
    for x, y in rock:
        p = to_screen(x, y)
        if not poly or p != poly[-1]:
            poly.append(p)
    if poly[0] == poly[-1]:
        poly.pop()
    ns = []
    for x1, y1, x2, y2 in nails:
        h, t = to_screen(x1, y1), to_screen(x2, y2)
        if h != t:
            ns.append((h, t))
    ns.sort(key=lambda n: (n[0][1], n[0][0]))
    return poly, ns


# ---------------------------------------------------------------------
# The drawing, as the 286 does it (integers only)
# ---------------------------------------------------------------------
def spans(poly):
    """per row: [xl, xr] of the stone (inclusive), or None.  Every edge
    that isn't level marks its rows y0 <= y < y1; x by IDIV (truncates)."""
    xl = [0x7FFF] * H
    xr = [-1] * H
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if y0 == y1:
            continue
        if y0 > y1:
            x0, y0, x1, y1 = x1, y1, x0, y0
        for y in range(y0, y1):
            num = (x1 - x0) * (y - y0)
            q = abs(num) // (y1 - y0)
            x = x0 + (q if num >= 0 else -q)
            xl[y] = min(xl[y], x)
            xr[y] = max(xr[y], x)
    return xl, xr


def bresenham(x0, y0, x1, y1):
    """the points of a line, from (x0, y0), and whether it is steep"""
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x1 >= x0 else -1
    sy = 1 if y1 >= y0 else -1
    steep = dy > dx
    if steep:
        dx, dy = dy, dx
    err = dx // 2
    x, y = x0, y0
    pts = []
    for i in range(dx + 1):
        pts.append((x, y))
        err -= dy
        if err < 0:
            err += dx
            if steep:
                x += sx
            else:
                y += sy
        if steep:
            y += sy
        else:
            x += sx
    return pts, steep


def render(poly, nails):
    """the screen as rows of 0/1"""
    scr = [[0] * W for _ in range(H)]
    xl, xr = spans(poly)

    def plot(x, y, v):
        # SPLASH.ASM doesn't clip: every point must be on the screen
        assert 0 <= x < W and 0 <= y < H, ('off the screen', x, y)
        scr[y][x] = v

    def nail_px(x, y):              # lit on the stone, dark on the paper
        assert 0 <= y < H, ('off the screen', x, y)
        plot(x, y, 1 if xl[y] <= x <= xr[y] else 0)

    # the plate: paper lit, the stone left dark
    for y in range(PY, PY + PH):
        for x in range(PX, PX + PW):
            scr[y][x] = 0 if xl[y] <= x <= xr[y] else 1
    # the nails: the shank 3 wide across its minor axis, the point
    # narrowing to 2 then 1, and the head across the shank, 5 long and
    # 2 deep, behind its end
    for (hx, hy), (tx, ty) in nails:
        pts, steep = bresenham(hx, hy, tx, ty)
        n = len(pts)
        for i, (x, y) in enumerate(pts):
            if i < n - TAPER:
                offs = (-1, 0, 1)
            elif i < n - 1:
                offs = (0, 1)
            else:
                offs = (0,)
            for o in offs:
                if steep:
                    nail_px(x + o, y)
                else:
                    nail_px(x, y + o)
        sx = -1 if tx > hx else 1
        sy = -1 if ty > hy else 1
        for k in (-2, -1, 0, 1, 2):
            if steep:
                nail_px(hx + k, hy)
                nail_px(hx + k, hy + sy)
            else:
                nail_px(hx, hy + k)
                nail_px(hx + sx, hy + k)
    # the title, 2 pixels wide, lit
    for i, ch in enumerate(TITLE):
        ox = TX + i * TADV
        for stroke in GLYPHS[ch]:
            for (ax, ay), (bx, by) in zip(stroke, stroke[1:]):
                pts, steep = bresenham(ox + ax, TY + ay, ox + bx, TY + by)
                for x, y in pts:
                    plot(x, y, 1)
                    plot(x + 1, y, 1)
                    plot(x, y + 1, 1)
                    plot(x + 1, y + 1, 1)
    x0, x1, y = RULE
    for x in range(x0, x1):
        scr[y][x] = 1
    return scr


# ---------------------------------------------------------------------
# Packing (SPLASH.INC)
# ---------------------------------------------------------------------
def pack(poly, nails):
    """outline: its first vertex (words), then (dx, dy) signed bytes to
    each next one; nails: 4 bytes each, sorted by head row:
      x low byte | x bit 8 (bit 7) + rows down from the last head (bits 0-6)
      | tip dx | tip dy (signed bytes)"""
    out = []
    out.append('; made by splash/mksplash.py from splash/trace.txt - do not edit')
    out.append('SP_PX equ %d' % PX)
    out.append('SP_PY equ %d' % PY)
    out.append('SP_PW equ %d' % PW)
    out.append('SP_PH equ %d' % PH)
    out.append('SP_TAPER equ %d' % TAPER)
    out.append('SP_NV equ %d' % len(poly))
    out.append('SP_NN equ %d' % len(nails))
    assert all(0 <= x < W and 0 <= y < H for x, y in poly)
    out.append('sp_poly dw %d, %d' % poly[0])
    rows = []
    n = len(poly)
    for i in range(1, n + 1):
        a, b = poly[i - 1], poly[i % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        assert -128 <= dx <= 127 and -128 <= dy <= 127, ('outline edge too long', a, b)
        rows.append('%d,%d' % (dx, dy))
    for i in range(0, len(rows), 12):
        out.append('        db ' + ', '.join(rows[i:i + 12]))
    out.append('sp_ndata:')
    lasty = 0
    for (hx, hy), (tx, ty) in nails:
        step = hy - lasty
        assert 0 <= step <= 127 and 0 <= hx <= 511, (hx, hy)
        dx, dy = tx - hx, ty - hy
        assert -128 <= dx <= 127 and -128 <= dy <= 127, ('nail too long', hx, hy, tx, ty)
        out.append('        db %d, %d, %d, %d' % (hx & 255, (hx >> 8) << 7 | step, dx & 255, dy & 255))
        lasty = hy
    # the title: per letter, its glyph's address; a glyph: x, y bytes,
    # 0FFh = lift the pen, 0FEh = its end
    out.append('SP_TX equ %d' % TX)
    out.append('SP_TY equ %d' % TY)
    out.append('SP_TADV equ %d' % TADV)
    out.append('sp_title db %d' % len(TITLE))
    out.append('        dw ' + ', '.join('sp_g%s' % c for c in TITLE))
    for c in sorted(set(TITLE)):
        b = []
        for k, stroke in enumerate(GLYPHS[c]):
            if k:
                b.append('0FFh')
            b += ['%d,%d' % p for p in stroke]
        b.append('0FEh')
        out.append('sp_g%s db %s' % (c, ', '.join(b)))
    out.append('SP_RX0 equ %d' % RULE[0])
    out.append('SP_RX1 equ %d' % (RULE[1] - 1))
    out.append('SP_RY equ %d' % RULE[2])
    return '\n'.join(out) + '\n'


def amber_png(scr, path, scale=2):
    from PIL import Image
    img = Image.new('RGB', (W, H))
    img.putdata([(255, 170, 50) if v else (28, 12, 0) for row in scr for v in row])
    if scale != 1:
        img = img.resize((W * scale, H * scale), Image.NEAREST)
    img.save(path)


if __name__ == '__main__':
    rock, nails = read_trace()
    poly, ns = build(rock, nails)
    inc = pack(poly, ns)
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'src', 'SPLASH.INC')
    open(out, 'w').write(inc)
    scr = render(poly, ns)
    amber_png(scr, os.path.join(HERE, 'splash.png'))
    print('%d outline points, %d nails -> %s' % (len(poly), len(ns), out))
