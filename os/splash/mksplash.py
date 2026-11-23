"""The start-up picture: a terrella, the "little earth" William Gilbert
describes in De Magnete (1600): a lodestone turned into a sphere.  Here it
turns on a rod set 25 degrees from upright, shaded with rings open to one
side, in a dipole's lines of force.  The drawing is Lodestone's own, worked
out below, not one of the book's woodcuts.  Under it LODESTONE, underlined.

    python3 mksplash.py            writes ../src/SPLASH.INC and splash.png

SPLASH.INC is the drawing for ../src/SPLASH.ASM, which builds LODE.PIC: the
picture program the kernel's bootstrap (KSPLASH.INC) loads, runs and drops
at start-up.

The drawing is worked out here (the numbers below: edit freely), packed as
a list of paths, and drawn exactly as SPLASH.ASM does, for the tests and
the preview.  1 bit, mode 40h: a dark screen, and everything drawn is lit.

A path is a pen, a first point and steps to each next one:
  THIN   a line 1 pixel wide through its points
  THICK  the same, 2 x 2 pixels at each point
A path can also be drawn again with each pixel mirrored about the stone's
centre: left to right (MX), top to bottom (MY), or both, which draws it
four times (the outline is kept as a quarter); or only turned half round
(TURN: a dipole's lines are the same turned half round, so half of them
are kept).  LODE.PIC must stay within 2 sectors of ROM 1 (1,024 bytes).
"""
import math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 640, 400
THIN, THICK = 1, 2
MX, MY = 0x40, 0x80                 # with the pen: also drawn mirrored,
TURN = MX | MY | 0x20               #  or only turned half round
H_PATH, H_THICK, H_REL = 4, 1, 8    # a path's header: always; the THICK pen; first point as a step

CX, CY = 320, 164                   # the stone's centre
R = 84                              # its radius
TILT = 25                           # the axis, in degrees left of upright
ROD = 18                            # how far the rod stands out past each pole
RINGS = (72, 60, 48, 36, 24, 12)    # the rings' radii, outermost first
RING_SHIFT = 5                      # each ring's centre this much nearer the upper pole than the last
OPEN_AT = 28                        # the rings open to the right, this many degrees below the equator
OPENINGS = (36, 63, 45, 81, 42, 69) # half of each ring's opening, in degrees
SHELLS = (1.5, 2.2, 3.4, 6.5, 16)   # lines of force: where each crosses the equator, in radii
CLEAR = 5                           # they start this far off the stone
BOX = (8, 12, 631, 318)             #  and stay inside this
ARROW = (2.2, 7)                    # the arrowheads: on this shell, this long
TOL = 0.65                          # rings and lines are fitted to within this (pixels)

AX = (-math.sin(math.radians(TILT)), -math.cos(math.radians(TILT)))    # along the axis, to the upper pole
EQ = (math.cos(math.radians(TILT)), -math.sin(math.radians(TILT)))     # along the equator, to the right

# The title: "LODESTONE" in Lodefont's capitals (docs/lodestone-font.md) as
# thin strokes: tall rectangles with cut corners, and N's diagonal ending
# high.  Each glyph is strokes on a 20 x 32 grid; a stroke is a polyline,
# and E, T and N go back over a part of themselves so that each is one
# stroke.  Drawn with the THICK pen.
GLYPHS = {
    'L': [[(0, 0), (0, 32), (20, 32)]],
    'O': [[(5, 0), (15, 0), (20, 5), (20, 27), (15, 32), (5, 32), (0, 27), (0, 5), (5, 0)]],
    'D': [[(0, 0), (14, 0), (20, 6), (20, 26), (14, 32), (0, 32), (0, 0)]],
    'E': [[(20, 32), (0, 32), (0, 15), (15, 15), (0, 15), (0, 0), (20, 0)]],
    'S': [[(20, 5), (15, 0), (5, 0), (0, 5), (0, 11), (5, 16), (15, 16), (20, 21), (20, 27), (15, 32), (5, 32), (0, 27)]],
    'T': [[(0, 0), (20, 0), (10, 0), (10, 32)]],
    'N': [[(0, 32), (0, 0), (20, 22), (20, 0), (20, 32)]],
}
TITLE = 'LODESTONE'
TADV = 28                           # letter advance
TW = (len(TITLE) - 1) * TADV + 22   # its width (2-pixel strokes)
TX = (W - TW) // 2                  # centred under the stone
TY = 340
RULE_Y = TY + 40                    # the rule under it (the THICK pen: 2 rows)


def rnd(v):
    return int(math.floor(v + 0.5))


def bresenham(x0, y0, x1, y1):
    """the points of a line, from (x0, y0), as SPLASH.ASM's sp_line steps"""
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
    return pts


# ---------------------------------------------------------------------
# The drawing
# ---------------------------------------------------------------------
def quarter(a, b, off=0.0, n=4096):
    """a quarter of an ellipse about (off, off), from its right end to its
    lowest point, as a chain of pixels: each next to the last, none only
    cutting a corner"""
    pts = []
    for i in range(n + 1):
        t = math.pi / 2 * i / n
        p = (max(0, rnd(off + a * math.cos(t))), max(0, rnd(off + b * math.sin(t))))
        if not pts or p != pts[-1]:
            pts.append(p)
    i = 1
    while i < len(pts) - 1:
        (ax, ay), (bx, by) = pts[i - 1], pts[i + 1]
        if max(abs(ax - bx), abs(ay - by)) <= 1:
            del pts[i]
            i = max(i - 1, 1)
        else:
            i += 1
    return pts


def fit(chain):
    """the fewest points whose lines, drawn as sp_line draws them, are
    exactly the chain's pixels"""
    out = [chain[0]]
    i = 0
    while i < len(chain) - 1:
        j = i + 1
        while (j + 1 < len(chain)
               and max(abs(chain[j + 1][0] - chain[i][0]), abs(chain[j + 1][1] - chain[i][1])) <= 127
               and bresenham(*chain[i], *chain[j + 1]) == chain[i:j + 2]):
            j += 1
        out.append(chain[j])
        i = j
    return out


def ellipse(a, b, pen=THIN):
    """the lower right quarter of an ellipse about the centre, as a path
    to draw mirrored four ways.  The THICK pen's pixels reach 1 right and
    1 down: its path runs half a pixel up and left, and half a pixel
    inside, so that its pixels mirrored about the centre meet."""
    k = 1 if pen == THICK else 0
    q = quarter(a - k / 2, b - k / 2, -k / 2)
    assert q[0][1] == 0 and q[-1][0] == 0, 'the quarters would not meet'
    return (pen, MX | MY, fit([(CX + x, CY + y) for x, y in q]))


def short_steps(pts):
    """the same polyline with no step longer than a signed byte"""
    out = [pts[0]]
    for p in pts[1:]:
        while True:
            q = out[-1]
            dx, dy = p[0] - q[0], p[1] - q[1]
            m = max(abs(dx), abs(dy))
            if m <= 127:
                break
            k = -(-m // 127)
            out.append((q[0] + rnd(dx / k), q[1] + rnd(dy / k)))
        out.append(p)
    return out


def along(samples, tol=TOL):
    """a polyline through a curve's samples, none of them further than
    tol from it"""
    def dist(p, a, b):
        (px, py), (ax, ay), (bx, by) = p, a, b
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy
        t = 0 if ll == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / ll))
        return math.hypot(px - ax - t * dx, py - ay - t * dy)

    def P(q):
        return (rnd(q[0]), rnd(q[1]))
    out, i = [P(samples[0])], 0
    while i < len(samples) - 1:
        j = i + 1
        while j + 1 < len(samples):
            q = P(samples[j + 1])
            if max(abs(q[0] - out[-1][0]), abs(q[1] - out[-1][1])) > 127:
                break
            if any(dist(samples[k], out[-1], q) > tol for k in range(i + 1, j + 1)):
                break
            j += 1
        if P(samples[j]) != out[-1]:
            out.append(P(samples[j]))
        i = j
    return out


def place(u, w):
    """the screen's point u along the equator and w along the axis from the centre"""
    return (CX + u * EQ[0] + w * AX[0], CY + u * EQ[1] + w * AX[1])


def rings():
    """the stone's shading: rings open to one side, each one's centre
    nearer the upper pole than the last, so they gather round the rod"""
    out = []
    mid = math.degrees(math.atan2(EQ[1], EQ[0])) + OPEN_AT
    for n, r in enumerate(RINGS):
        cx, cy = CX + RING_SHIFT * (n + 1) * AX[0], CY + RING_SHIFT * (n + 1) * AX[1]
        a0, a1 = mid + OPENINGS[n % len(OPENINGS)], mid - OPENINGS[n % len(OPENINGS)] + 360
        k = max(8, int(r * math.radians(a1 - a0)))
        out.append((THIN, 0, along([(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
                                    for a in [a0 + (a1 - a0) * i / k for i in range(k + 1)]])))
    return out


def shell(k, th, side=1):
    """the point at angle th from the upper pole on a dipole's line of
    force that crosses the equator k radii out: r = k R sin^2(th)"""
    r = k * R * math.sin(th) ** 2
    return r, place(side * r * math.sin(th), r * math.cos(th))


def force():
    """the lines of force right of the axis, where they are off the stone
    and inside BOX; those left of it are these turned half round"""
    out = []
    for k in SHELLS:
        run = []
        for i in range(1, 1801):
            r, (x, y) = shell(k, math.pi * i / 1800)
            if i < 1800 and r >= R + CLEAR and BOX[0] <= x <= BOX[2] and BOX[1] <= y <= BOX[3]:
                run.append((x, y))
            else:
                if len(run) > 12:
                    out.append((THIN, TURN, along(run)))
                run = []
    return out


def arrows():
    """an arrowhead each side where ARROW's shell crosses the equator,
    pointing the way the field runs: out of the upper pole and round.
    (Turned half round an arrowhead would point against the field, so
    each is kept.)"""
    k, size = ARROW
    out = []
    for side in (1, -1):
        (x, y), (x2, y2) = shell(k, math.pi / 2, side)[1], shell(k, math.pi / 2 + 0.02, side)[1]
        d = math.atan2(y2 - y, x2 - x)
        out.append((THIN, 0, [(rnd(x - size * math.cos(d - 0.5)), rnd(y - size * math.sin(d - 0.5))), (rnd(x), rnd(y)),
                              (rnd(x - size * math.cos(d + 0.5)), rnd(y - size * math.sin(d + 0.5)))]))
    return out


def drawing():
    """the picture: a list of (pen, mirrorings, points)"""
    paths = [ellipse(R, R, THICK)]                                          # the stone's outline
    a, b = place(0, R + 1), place(0, R + ROD)                               # the rod, past each pole
    paths.append((THICK, TURN, [(rnd(a[0]), rnd(a[1])), (rnd(b[0]), rnd(b[1]))]))
    paths += rings() + force() + arrows()
    # the title and its rule
    for i, ch in enumerate(TITLE):
        for stroke in GLYPHS[ch]:
            paths.append((THICK, 0, [(TX + i * TADV + x, TY + y) for x, y in stroke]))
    paths.append((THICK, 0, [(TX, RULE_Y), (TX + TW - 2, RULE_Y)]))
    return [(pen, mir, short_steps(pts)) for pen, mir, pts in paths]


def flips(mir):
    """the mirrorings a path is drawn with: as it is, then each it has
    (TURN: only both at once)"""
    return [f for f in ((0, MX | MY) if mir == TURN else (0, MX, MY, MX | MY)) if not f & ~mir]


# ---------------------------------------------------------------------
# The drawing, as the 286 does it
# ---------------------------------------------------------------------
def render(paths):
    """the screen as rows of 0/1"""
    scr = [[0] * W for _ in range(H)]

    def plot(x, y):
        # SPLASH.ASM doesn't clip: every point must be on the screen
        assert 0 <= x < W and 0 <= y < H, ('off the screen', x, y)
        scr[y][x] = 1

    for pen, mir, pts in paths:
        lit = set()
        for a, b in zip(pts, pts[1:]):
            for x, y in bresenham(*a, *b):
                lit.add((x, y))
                if pen == THICK:
                    lit |= {(x + 1, y), (x, y + 1), (x + 1, y + 1)}
        for f in flips(mir):
            # each pixel mirrored about the centre
            for x, y in lit:
                plot(2 * CX - x if f & MX else x, 2 * CY - y if f & MY else y)
    return scr


# ---------------------------------------------------------------------
# Packing (SPLASH.INC)
# ---------------------------------------------------------------------
def pack(paths):
    """each path: a header byte (PATH; THICK for the 2 x 2 pen; REL if its
    first point is stored as a step from the last path's first point;
    its mirrorings), its steps (a byte), its first point (signed bytes
    with REL, else words), then each step (dx, dy: signed bytes).  A
    header of 0 ends the list."""
    out = ['; made by splash/mksplash.py - do not edit',
           'SP_PATH equ %d' % H_PATH, 'SP_THICK equ %d' % H_THICK, 'SP_REL equ %d' % H_REL,
           'SP_MX equ %d' % MX, 'SP_MY equ %d' % MY, 'SP_TURN equ %d' % (TURN & ~(MX | MY)),
           'SP_CX2 equ %d' % (2 * CX), 'SP_CY2 equ %d' % (2 * CY),
           'sp_paths:']
    last = None
    for pen, mir, pts in paths:
        assert 1 <= len(pts) - 1 <= 127, ('too many steps in a path', len(pts))
        hdr = H_PATH | (H_THICK if pen == THICK else 0) | mir
        if last and all(-128 <= a - b <= 127 for a, b in zip(pts[0], last)):
            out.append('        db %d, %d, %d,%d' % (hdr | H_REL, len(pts) - 1, pts[0][0] - last[0], pts[0][1] - last[1]))
        else:
            out.append('        db %d, %d' % (hdr, len(pts) - 1))
            out.append('        dw %d, %d' % pts[0])
        last = pts[0]
        steps = []
        for a, b in zip(pts, pts[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            assert -128 <= dx <= 127 and -128 <= dy <= 127, ('step too long', a, b)
            steps.append('%d,%d' % (dx, dy))
        for i in range(0, len(steps), 12):
            out.append('        db ' + ', '.join(steps[i:i + 12]))
    out.append('        db 0')
    return '\n'.join(out) + '\n'


def amber_png(scr, path, scale=2):
    from PIL import Image
    img = Image.new('RGB', (W, H))
    img.putdata([(255, 120, 40) if v else (36, 8, 2) for row in scr for v in row])
    if scale != 1:
        img = img.resize((W * scale, H * scale), Image.NEAREST)
    img.save(path)


if __name__ == '__main__':
    paths = drawing()
    inc = pack(paths)
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'src', 'SPLASH.INC')
    open(out, 'w').write(inc)
    scr = render(paths)
    amber_png(scr, os.path.join(HERE, 'splash.png'))
    print('%d paths, %d steps -> %s' % (len(paths), sum(len(p) - 1 for _, _, p in paths), out))
