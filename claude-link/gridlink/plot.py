"""Plots Claude Code shows on the GRiD (grid_plot in mcp.py): drawn here in
one bit, 640 x 384, with the GRiD's own font, so lines and text are crisp
and nothing is dithered.  A plot keeps its axes, so a click on it maps back
to data coordinates and the nearest point.  Pure Python: no Pillow.

Lit lines on a dark screen, the GRiD's way.  Horizontal grid lines are
dotted; there are no vertical grid lines, only ticks (a vertical line
changes every line of the picture, which costs the link the most).
"""
import math
from . import gridfont, render
from . import picture as PIC

W, H = PIC.W, PIC.H
BPL = PIC.BPL
MAX_SERIES = 8
MAX_POINTS = 200000             # in all series
TOP, BOTTOM = 40, 343           # the plot box's frame (lines 0-31: title, axis name, legend)
RIGHT = W - 9
G_MICRO = render.G_MICRO
PREFIXES = {-12: 'p', -9: 'n', -6: chr(G_MICRO), -3: 'm', 3: 'k', 6: 'M', 9: 'G', 12: 'T'}
DASHES = [None, (6, 4), (1, 2), (8, 3, 1, 3)]          # on, off, ... pixels (None: solid)
MARKS = ['square', 'plus', 'cross', 'diamond']


class Bitmap:
    """640 x 384, 80 bytes a line, bit 7 the leftmost pixel: the GRiD's way."""
    def __init__(s):
        s.b = bytearray(PIC.SIZE)

    def set(s, x, y):
        if 0 <= x < W and 0 <= y < H: s.b[y * BPL + (x >> 3)] |= 0x80 >> (x & 7)

    def hline(s, x0, x1, y, every=1):
        for x in range(x0, x1 + 1, every): s.set(x, y)

    def vline(s, x, y0, y1, every=1):
        for y in range(y0, y1 + 1, every): s.set(x, y)

    def text(s, x, y, t, invert=False):
        """GRiD codes (render.fold's) at pixel (x, y), any x."""
        for ch in t:
            g = gridfont.glyph(ord(ch))
            for r in range(16):
                v = g[r] ^ (0xFF if invert else 0)
                if not v or not 0 <= y + r < H: continue
                i = (y + r) * BPL
                sh = x & 7; bx = x >> 3
                if 0 <= bx < BPL: s.b[i + bx] |= v >> sh
                if sh and 0 <= bx + 1 < BPL: s.b[i + bx + 1] |= (v << (8 - sh)) & 0xFF
            x += 8

    def clear_box(s, x0, y0, x1, y1):
        for y in range(max(0, y0), min(H, y1 + 1)):
            for x in range(max(0, x0), min(W, x1 + 1)):
                s.b[y * BPL + (x >> 3)] &= ~(0x80 >> (x & 7)) & 0xFF

    def line(s, x0, y0, x1, y1, clip, dash=None, phase=0):
        """Bresenham, inside clip (x0, y0, x1, y1); dash: on/off lengths.  ->
        the dash phase after it, so a polyline's dashes run on."""
        c = _clip(x0, y0, x1, y1, clip)
        if c is None: return phase + int(max(abs(x1 - x0), abs(y1 - y0)))
        x0, y0, x1, y1 = (int(round(v)) for v in c)
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        per = sum(dash) if dash else 0
        while True:
            if dash is None or _on(dash, phase % per): s.set(x0, y0)
            phase += 1
            if x0 == x1 and y0 == y1: return phase
            e2 = 2 * err
            if e2 >= dy: err += dy; x0 += sx
            if e2 <= dx: err += dx; y0 += sy

    def mark(s, x, y, kind):
        x, y = int(round(x)), int(round(y))
        if kind == 'square':
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1): s.set(x + dx, y + dy)
        elif kind == 'plus':
            for d in range(-2, 3): s.set(x + d, y); s.set(x, y + d)
        elif kind == 'cross':
            for d in range(-2, 3): s.set(x + d, y + d); s.set(x + d, y - d)
        else:                                                   # diamond
            for d in range(-2, 3):
                k = 2 - abs(d); s.set(x + d, y - k); s.set(x + d, y + k)

    def bytes(s):
        return bytes(s.b)


def _on(dash, p):
    for i, n in enumerate(dash):
        if p < n: return i % 2 == 0
        p -= n
    return True


def _clip(x0, y0, x1, y1, box):
    """Liang-Barsky: the part of the segment inside box, or None."""
    bx0, by0, bx1, by1 = box
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - bx0), (dx, bx1 - x0), (-dy, y0 - by0), (dy, by1 - y0)):
        if p == 0:
            if q < 0: return None
            continue
        r = q / p
        if p < 0:
            if r > t1: return None
            t0 = max(t0, r)
        else:
            if r < t0: return None
            t1 = min(t1, r)
    return x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy


# ---- axes -----------------------------------------------------------------
class Axis:
    """Data value <-> pixel, linear or log10."""
    def __init__(s, lo, hi, log, p_lo, p_hi):
        s.lo, s.hi, s.log, s.p_lo, s.p_hi = lo, hi, log, p_lo, p_hi
        s.a, s.b = (math.log10(lo), math.log10(hi)) if log else (lo, hi)

    def px(s, v):
        """-> pixel (a float), or None for a value a log axis can't show."""
        if v is None or (s.log and v <= 0): return None
        t = math.log10(v) if s.log else v
        return s.p_lo + (t - s.a) / (s.b - s.a) * (s.p_hi - s.p_lo)

    def val(s, p):
        t = s.a + (p - s.p_lo) / (s.p_hi - s.p_lo) * (s.b - s.a)
        return 10 ** t if s.log else t


def auto_range(vals, log, pad):
    """(lo, hi) around the values; pad: a fraction of the span on each side."""
    v = [x for x in vals if x is not None and (not log or x > 0)]
    if not v: return (1.0, 10.0) if log else (0.0, 1.0)
    lo, hi = min(v), max(v)
    if log:
        a, b = math.log10(lo), math.log10(hi)
        if a == b: a, b = a - 0.5, b + 0.5
        sp = (b - a) * pad
        return 10 ** (a - sp), 10 ** (b + sp)
    if lo == hi:
        d = abs(lo) * 0.1 or 1.0
        return lo - d, hi + d
    sp = (hi - lo) * pad
    return lo - sp, hi + sp


def nice_ticks(lo, hi, n=6):
    """Round tick values in [lo, hi]: (ticks, step)."""
    span = hi - lo
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if span / step <= n: break
    k0 = math.ceil(lo / step - 1e-9)
    ticks = []
    k = k0
    while k * step <= hi + step * 1e-9:
        v = k * step
        ticks.append(0.0 if abs(v) < step * 1e-9 else v)
        k += 1
    return ticks, step


def log_ticks(lo, hi):
    """Decades (and 2, 5 between them when the range is short): (labelled, minor)."""
    a, b = math.floor(math.log10(lo) + 1e-9), math.ceil(math.log10(hi) - 1e-9)
    lab, minor = [], []
    few = b - a <= 2
    for e in range(a, b + 1):
        for m in range(1, 10):
            v = m * 10.0 ** e
            if not lo * (1 - 1e-9) <= v <= hi * (1 + 1e-9): continue
            if m == 1 or (few and m in (2, 5)): lab.append(v)
            else: minor.append(v)
    if b - a > 8:                                       # many decades: label every few
        k = math.ceil((b - a) / 8)
        lab = [v for v in lab if round(math.log10(v)) % k == 0]
    return lab, minor


def scale_of(ticks):
    """The SI prefix exponent for an axis's labels (0 for none)."""
    big = max((abs(v) for v in ticks), default=0)
    if big == 0 or 1e-2 <= big < 1e5: return 0
    e = int(math.floor(math.log10(big) / 3) * 3)
    return max(-12, min(12, e))


def tick_label(v, step, e3):
    """A short label: 1.5k, 250, 0.25, 2.5M (GRiD codes)."""
    v = v / 10 ** e3
    if v == 0: return '0'
    st = step / 10 ** e3 if step else abs(v)
    d = 0
    while d < 6 and abs(round(st * 10 ** d) - st * 10 ** d) > 1e-6 * max(1, st * 10 ** d): d += 1
    s = '%.*f' % (d, v)
    if '.' in s: s = s.rstrip('0').rstrip('.')
    if s == '-0': s = '0'
    return s + PREFIXES.get(e3, '')


def log_label(v):
    """A log axis's label: 1, 10, 100, 1k, 2k, 1M, 1m (GRiD codes)."""
    e3 = max(-12, min(12, int(math.floor(math.log10(v) / 3 + 1e-9) * 3)))
    return ('%g' % round(v / 10 ** e3, 6)) + PREFIXES.get(e3, '')


def num(v):
    """A number for the prompt or the tool's answer: 6 significant digits."""
    return '%.6g' % v


# ---- series -----------------------------------------------------------------
def clean(vals, what):
    out = []
    for v in vals:
        if v is None: out.append(None); continue
        if isinstance(v, bool) or not isinstance(v, (int, float)): raise ValueError('%s: %r is not a number' % (what, v))
        v = float(v)
        out.append(v if math.isfinite(v) else None)
    return out


def series_from(raw):
    """[{'name', 'x' (optional), 'y', 'style'}] checked -> the same, cleaned."""
    if not isinstance(raw, list) or not raw: raise ValueError('series: a list of one or more {x, y} objects')
    if len(raw) > MAX_SERIES: raise ValueError('at most %d series' % MAX_SERIES)
    out = []; total = 0
    for i, s in enumerate(raw):
        if not isinstance(s, dict) or not isinstance(s.get('y'), list) or not s['y']:
            raise ValueError('series %d: needs y, a list of numbers' % (i + 1))
        y = clean(s['y'], 'series %d y' % (i + 1))
        x = s.get('x')
        if x is None: x = [float(k) for k in range(len(y))]
        elif not isinstance(x, list) or len(x) != len(y):
            raise ValueError('series %d: x and y must be lists of the same length' % (i + 1))
        else: x = clean(x, 'series %d x' % (i + 1))
        style = s.get('style') or 'line'
        if style not in ('line', 'points', 'both'): raise ValueError('series %d: style is line, points or both' % (i + 1))
        name = s.get('name')
        if name is not None and not isinstance(name, str): raise ValueError('series %d: name is text' % (i + 1))
        total += len(y)
        if total > MAX_POINTS: raise ValueError('at most %d points in all' % MAX_POINTS)
        out.append({'name': name or '', 'x': x, 'y': y, 'style': style})
    return out


NUM = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'


def series_from_file(text, x_column=None, columns=None, style=None):
    """A data file -> series: JSON (a list of series, or {"series": [...]}),
    or rows of numbers (commas, semicolons, tabs or spaces between them; a
    first row of names is a header).  One long line of numbers (an
    instrument's CURVE 1,2,3...) is one series.  x_column: 1-based, 0 for
    none (default 1 with two or more columns); columns: the y ones."""
    import json, re
    t = text.lstrip('\ufeff \t\r\n')
    if t[:1] in '[{':
        d = json.loads(t)
        if isinstance(d, dict): d = d.get('series', [d])
        if not isinstance(d, list): raise ValueError('a JSON file holds a list of series')
        return d
    lines = [l for l in t.splitlines() if l.strip()]
    if not lines: raise ValueError('the file is empty')
    if len(lines) == 1:
        ys = [float(v) for v in re.findall(NUM, lines[0])]
        if not ys: raise ValueError('no numbers in the file')
        return [{'name': '', 'y': [v if math.isfinite(v) else None for v in ys], 'style': style}]
    split = lambda l: [c.strip() for c in re.split(r'[,;\t]' if re.search(r'[,;\t]', l) else r'\s+', l.strip())]
    rows = [split(l) for l in lines]
    head = None
    if rows[0] and not any(_f(c) is not None for c in rows[0]):
        head = rows[0]; rows = rows[1:]
    if not rows: raise ValueError('the file has names but no numbers')
    ncol = max(len(r) for r in rows)
    xc = (1 if ncol >= 2 else 0) if x_column is None else x_column
    if xc > ncol: raise ValueError('x_column %d: the file has %d columns' % (xc, ncol))
    if columns is not None:
        if not isinstance(columns, list) or not all(isinstance(c, int) and not isinstance(c, bool) for c in columns):
            raise ValueError('columns: a list of column numbers')
        bad = [c for c in columns if not 1 <= c <= ncol]
        if bad: raise ValueError('columns %s: the file has %d columns' % (bad, ncol))
        ycols = columns
    else:
        ycols = [c for c in range(1, ncol + 1) if c != xc]
    if not ycols: raise ValueError('no y columns')
    col = lambda c: [_f(r[c - 1]) if c - 1 < len(r) else None for r in rows]
    xs = col(xc) if xc else None
    name = lambda c: (head[c - 1] if head and c - 1 < len(head) else '') or ('' if len(ycols) == 1 else 'column %d' % c)
    return [{'name': name(c), 'x': xs, 'y': col(c), 'style': style} for c in ycols]


def _f(c):
    try:
        v = float(c)
        return v if math.isfinite(v) else None
    except ValueError: return None


def decimate(px, py, width):
    """Many points to a pixel column: keep each column's first, lowest,
    highest and last, in order (the line looks the same)."""
    if len(px) <= 4 * width: return list(range(len(px)))
    keep = []; col = None; idx = []
    def flush():
        if not idx: return
        lo = min(idx, key=lambda i: py[i]); hi = max(idx, key=lambda i: py[i])
        keep.extend(sorted({idx[0], lo, hi, idx[-1]}))
    for i in range(len(px)):
        if px[i] is None or py[i] is None:
            flush(); idx = []; keep.append(i); col = None; continue
        c = int(px[i])
        if c != col: flush(); idx = []; col = c
        idx.append(i)
    flush()
    return keep


# ---- the plot -----------------------------------------------------------------
class Plot:
    """A plot drawn for the GRiD: .bits (picture.SIZE bytes), and clicks
    mapped back with .at(x, y)."""
    def __init__(s, series, title='', x_label='', y_label='', x_log=False, y_log=False,
                 x_range=None, y_range=None):
        s.series = series_from(series)
        s.title, s.x_label, s.y_label = title or '', x_label or '', y_label or ''
        xs = [v for sr in s.series for v in sr['x']]
        ys = [v for sr in s.series for v in sr['y']]
        s.xr = _range(x_range, 'x_range', x_log) or auto_range(xs, x_log, 0.0)
        s.yr = _range(y_range, 'y_range', y_log) or auto_range(ys, y_log, 0.05)
        s.x_log, s.y_log = bool(x_log), bool(y_log)
        s.draw()

    def draw(s):
        bm = Bitmap()
        # ticks and their labels first: the y labels set the box's left side
        if s.y_log: ylab, ymin = log_ticks(*s.yr); ystep = None; ye3 = 0
        else: ylab, ystep = nice_ticks(*s.yr, n=6); ymin = []; ye3 = scale_of(ylab)
        ytext = [(v, log_label(v) if s.y_log else tick_label(v, ystep, ye3)) for v in ylab]
        left = max(8 * max([len(t) for _, t in ytext] + [3]) + 10, 40)
        s.box = (left, TOP, RIGHT, BOTTOM)
        s.ax = Axis(s.xr[0], s.xr[1], s.x_log, left + 1, RIGHT - 1)
        s.ay = Axis(s.yr[0], s.yr[1], s.y_log, BOTTOM - 1, TOP + 1)
        L, T, R, B = s.box
        # the frame
        bm.hline(L, R, T); bm.hline(L, R, B); bm.vline(L, T, B); bm.vline(R, T, B)
        # y: ticks, dotted grid lines, labels
        for v, t in ytext:
            y = int(round(s.ay.px(v)))
            if not T <= y <= B: continue
            bm.hline(L, L + 5, y); bm.hline(R - 5, R, y)
            if T < y < B: bm.hline(L + 8, R - 8, y, every=4)
            bm.text(L - 4 - 8 * len(t), max(0, y - 8), t)
        for v in ymin:
            y = int(round(s.ay.px(v)))
            if T < y < B: bm.hline(L, L + 2, y); bm.hline(R - 2, R, y)
        # x: ticks and labels
        if s.x_log: xlab, xmin = log_ticks(*s.xr); xstep = None; xe3 = 0
        else: xlab, xstep = nice_ticks(*s.xr, n=max(3, min(8, (R - L) // 80))); xmin = []; xe3 = scale_of(xlab)
        last = -99
        for v in xlab:
            x = int(round(s.ax.px(v)))
            if not L <= x <= R: continue
            bm.vline(x, B - 5, B); bm.vline(x, T, T + 5)
            t = log_label(v) if s.x_log else tick_label(v, xstep, xe3)
            tx = min(max(0, x - 4 * len(t)), W - 8 * len(t))
            if tx > last + 8: bm.text(tx, B + 4, t); last = tx + 8 * len(t)
        for v in xmin:
            x = int(round(s.ax.px(v)))
            if L < x < R: bm.vline(x, B - 2, B); bm.vline(x, T, T + 2)
        # names
        if s.title:
            t = render.fold(s.title).replace('\n', ' ')[:80]
            bm.text((W - 8 * len(t)) // 2, 0, t)
        if s.y_label:
            bm.text(0, 18, render.fold(s.y_label).replace('\n', ' ')[:40])
        if s.x_label:
            t = render.fold(s.x_label).replace('\n', ' ')[:80]
            bm.text(max(0, min(W - 8 * len(t), (L + R) // 2 - 4 * len(t))), B + 22, t)
        # the legend: when there are names
        named = [i for i, sr in enumerate(s.series) if sr['name']]
        if named:
            x = W
            parts = []
            for i in named:
                nm = render.fold(s.series[i]['name']).replace('\n', ' ')[:20]
                parts.append((i, nm)); x -= 8 * len(nm) + 28
            x = max(x, 8 * min(len(s.y_label), 40) + 16 if s.y_label else 0)
            for i, nm in parts:
                sr = s.series[i]
                if sr['style'] != 'points': bm.line(x, 26, x + 16, 26, (0, 0, W - 1, H - 1), DASHES[i % 4])
                if sr['style'] != 'line': bm.mark(x + 8, 26, MARKS[i % 4])
                bm.text(x + 20, 18, nm); x += 8 * len(nm) + 28
        # the data, clipped to inside the frame
        clip = (L + 1, T + 1, R - 1, B - 1)
        s.pts = []
        for i, sr in enumerate(s.series):
            px = [s.ax.px(v) for v in sr['x']]
            py = [s.ay.px(v) for v in sr['y']]
            s.pts.append((px, py))
            if sr['style'] != 'points':
                keep = decimate(px, py, R - L)
                phase = 0; prev = None
                for k in keep:
                    if px[k] is None or py[k] is None: prev = None; continue
                    if prev is not None: phase = bm.line(prev[0], prev[1], px[k], py[k], clip, DASHES[i % 4], phase)
                    else: bm.line(px[k], py[k], px[k], py[k], clip)
                    prev = (px[k], py[k])
            if sr['style'] != 'line':
                kind = MARKS[i % 4]
                for x, y in zip(px, py):
                    if x is None or y is None or not (L < x < R and T < y < B): continue
                    bm.mark(x, y, kind)
        bm.hline(L, R, T); bm.hline(L, R, B); bm.vline(L, T, B); bm.vline(R, T, B)   # (over marks at the edge)
        s.bm = bm
        s.bits = bm.bytes()

    def inside(s, x, y):
        L, T, R, B = s.box
        return L <= x <= R and T <= y <= B

    def at(s, x, y):
        """A click at pixel (x, y) -> {'x', 'y' (data; None outside the
        box), 'nearest': {'series', 'index', 'x', 'y'} or None}."""
        out = {'pixel': [x, y], 'x': None, 'y': None, 'nearest': None}
        if s.inside(x, y):
            out['x'], out['y'] = s.ax.val(x), s.ay.val(y)
        best = None
        for i, (px, py) in enumerate(s.pts):
            for k in range(len(px)):
                if px[k] is None or py[k] is None: continue
                d = (px[k] - x) ** 2 + (py[k] - y) ** 2
                if best is None or d < best[0]: best = (d, i, k)
        if best is not None and best[0] <= 40 ** 2:
            d, i, k = best
            sr = s.series[i]
            out['nearest'] = {'series': sr['name'] or 'series %d' % (i + 1), 'index': k,
                              'x': sr['x'][k], 'y': sr['y'][k], 'pixel': [s.pts[i][0][k], s.pts[i][1][k]]}
        return out

    def words(s, c):
        """A click (at()'s) as words for Claude Code's prompt."""
        what = 'plot "%s"' % s.title if s.title else 'the plot'
        xl, yl = s.x_label or 'x', s.y_label or 'y'
        bits = []
        if c['x'] is not None: bits.append('%s = %s, %s = %s' % (xl, num(c['x']), yl, num(c['y'])))
        n = c['nearest']
        if n is not None:
            bits.append('nearest point: %s #%d (%s, %s)' % (n['series'], n['index'], num(n['x']), num(n['y'])))
        if not bits: return '[a click on %s, outside its axes]' % what
        return '[clicked %s: %s]' % (what, '; '.join(bits))


def _range(r, what, log):
    if r is None: return None
    if (not isinstance(r, list) or len(r) != 2 or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                         and math.isfinite(v) for v in r) or r[0] >= r[1]):
        raise ValueError('%s: [low, high], two numbers, low first' % what)
    if log and r[0] <= 0: raise ValueError('%s: a log axis starts above 0' % what)
    return float(r[0]), float(r[1])


# ---- an image file, dithered (grid_image) ------------------------------------------
class ImageView:
    """A picture file fitted to 640 x 384 and dithered; with plot_area and
    the axis ranges, clicks map to data coordinates too."""
    def __init__(s, im, title='', invert=None, plot_area=None, x_range=None, y_range=None, x_log=False, y_log=False):
        from PIL import ImageStat
        s.title = title or ''
        s.size = im.size
        g = im.convert('L')
        light = ImageStat.Stat(g).mean[0] > 128
        if invert is None: invert = light     # (a white page: lit lines on dark, the GRiD's way)
        s.inverted = bool(invert)
        fitted, (s.left, s.top, s.scale) = PIC.fit(g, (W, H), 255 if light else 0)
        s.bits = PIC.dither(fitted, invert=invert)
        s.ax = s.ay = None
        if plot_area is not None:
            if (not isinstance(plot_area, list) or len(plot_area) != 4
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in plot_area)):
                raise ValueError('plot_area: [left, top, right, bottom] in the image\'s pixels')
            l, t, r, b = plot_area
            xr = _range(x_range, 'x_range', x_log); yr = _range(y_range, 'y_range', y_log)
            if xr is None or yr is None: raise ValueError('plot_area needs x_range and y_range')
            if r <= l or b <= t: raise ValueError('plot_area: right > left and bottom > top')
            s.area = (l, t, r, b)
            s.ax = Axis(xr[0], xr[1], x_log, l, r)
            s.ay = Axis(yr[0], yr[1], y_log, b, t)

    def image_px(s, x, y):
        return (x - s.left) / s.scale, (y - s.top) / s.scale

    def at(s, x, y):
        ix, iy = s.image_px(x, y)
        out = {'pixel': [x, y], 'image_pixel': [round(ix, 1), round(iy, 1)], 'x': None, 'y': None, 'nearest': None}
        if not (0 <= ix < s.size[0] and 0 <= iy < s.size[1]): out['image_pixel'] = None
        if s.ax is not None and out['image_pixel'] is not None:
            l, t, r, b = s.area
            if l <= ix <= r and t <= iy <= b: out['x'], out['y'] = s.ax.val(ix), s.ay.val(iy)
        return out

    def words(s, c):
        what = 'image "%s"' % s.title if s.title else 'the image'
        if c['x'] is not None: return '[clicked %s: x = %s, y = %s]' % (what, num(c['x']), num(c['y']))
        if c['image_pixel'] is not None:
            return '[clicked %s at pixel (%d, %d) of the image]' % (what, c['image_pixel'][0], c['image_pixel'][1])
        return '[a click beside %s]' % what


def mark_click(bits, x, y, label=''):
    """A small cross where a pick landed, and its number: so you see it took."""
    bm = Bitmap(); bm.b[:] = bits
    x, y = int(round(x)), int(round(y))
    bm.clear_box(x - 5, y - 5, x + 5, y + 5)
    for d in range(-5, 6):
        if abs(d) > 1: bm.set(x + d, y); bm.set(x, y + d)
    if label:
        tx, ty = x + 6, y - 18 if y >= 18 else y + 4
        bm.clear_box(tx, ty, tx + 8 * len(label) - 1, ty + 15)
        bm.text(tx, ty, label)
    return bm.bytes()
