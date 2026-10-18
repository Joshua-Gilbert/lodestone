"""Pictures on the GRiD: one 640x384 one-bit picture over Term's screen.

A CLAUDE.COM that says so in its HELLO (flags bit 1) takes CELLS operation
FDh, a rectangle of pixels:

    FDh, y (word, 0-383), x (bytes, 0-79), w (bytes), h (lines),
    then each line's w bytes as PackBits

and Term's scroll (FEh) moves rows of 16 lines.  The Picture encoder keeps
what the GRiD shows and sends only the difference, the latest picture only:
a slow link means fewer pictures, never a queue (as Term's text encoder).

A picture is 384 lines of 80 bytes (`bytes`, 30,720), bit 7 of a byte the
leftmost pixel, 1 lit.  `to_bits` makes one from a Pillow image; `dither`
from anything grey or in colour.
"""
W, H = 640, 384                 # rows 0-23 of the GRiD's screen; row 24 is CLAUDE's band
BPL = W // 8                    # bytes a line
SIZE = BPL * H
LINES = 16                      # a text row: what the scroll op moves
F_CLEAR, F_HIDDEN = 0x01, 0x02
OP_PIX, OP_SCROLL = 0xFD, 0xFE
OP_HEAD = 6                     # FDh, y (2), x, w, h

BLANK = bytes(SIZE)

# 8x8 ordered dither (Bayer), fixed to the screen: an area that doesn't
# change keeps its pixels, so only what changed crosses the link, and a
# scroll by 16 lines keeps the pattern aligned.
BAYER = [[0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
         [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
         [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
         [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]]
DARK, LIGHT = 56, 200           # thresholds: below and above these, no dither (text stays crisp)


# ---- PackBits -----------------------------------------------------------
def packbits(row):
    """One line's bytes -> PackBits (n < 80h: n + 1 bytes follow; else one
    byte, 257 - n times).  A pair inside literal bytes stays literal, so w
    bytes never take more than w + 1 (w <= 128)."""
    row = bytes(row); out = bytearray(); lit = bytearray(); i = 0; n = len(row)
    def flush():
        for k in range(0, len(lit), 128):
            part = lit[k:k + 128]; out.append(len(part) - 1); out.extend(part)
        lit.clear()
    while i < n:
        j = i
        while j + 1 < n and row[j + 1] == row[i] and j - i < 127: j += 1
        run = j - i + 1
        if run >= 3 or (run == 2 and not lit):
            flush(); out += bytes([257 - run, row[i]])
        else:
            lit += row[i:j + 1]
        i = j + 1
    flush()
    return bytes(out)


def unpackbits(data, i, n):
    """-> (n bytes, the offset after them), as the GRiD decodes them; None
    if the codes don't make exactly n bytes inside data."""
    out = bytearray()
    while len(out) < n:
        if i >= len(data): return None, i
        c = data[i]; i += 1
        if c < 0x80:
            k = c + 1
            if len(out) + k > n or i + k > len(data): return None, i
            out += data[i:i + k]; i += k
        else:
            k = 257 - c
            if len(out) + k > n or i >= len(data): return None, i
            out += bytes([data[i]]) * k; i += 1
    return bytes(out), i


# ---- pictures from images -------------------------------------------------
def to_bits(img):
    """A Pillow image, 640 x 384 (mode '1', or anything: lit where light)
    -> the GRiD's bytes."""
    if img.size != (W, H): raise ValueError('a picture is %d x %d, not %d x %d' % (W, H, img.size[0], img.size[1]))
    return img.convert('1', dither=0).tobytes()


def fit(img, box=(W, H), fill=0):
    """An image scaled to fit the box (aspect kept), centred on fill; ->
    (image, (left, top, scale)) so a click can be mapped back."""
    from PIL import Image
    iw, ih = img.size
    sc = min(box[0] / iw, box[1] / ih)
    nw, nh = max(1, round(iw * sc)), max(1, round(ih * sc))
    out = Image.new(img.mode if img.mode in ('L', 'RGB', '1') else 'RGB', box, fill)
    left, top = (box[0] - nw) // 2, (box[1] - nh) // 2
    out.paste(img.convert(out.mode).resize((nw, nh), Image.LANCZOS if sc < 1 else Image.NEAREST), (left, top))
    return out, (left, top, sc)


def dither(img, invert=False):
    """Grey or colour -> one bit, 640 x 384 (scaled to fit): near black and
    near white thresholded (text stays crisp), the greys between by the
    8 x 8 pattern fixed to the screen.  Pillow's own C, no per-pixel Python."""
    from PIL import Image, ImageChops
    g = img.convert('L')
    if g.size != (W, H): g, _ = fit(g)
    if invert: g = g.point(lambda v: 255 - v)
    g = g.point(lambda v: 0 if v <= DARK else 255 if v >= LIGHT else v)
    out = ImageChops.subtract(g, threshold()).point(lambda v: 255 if v else 0)
    return out.convert('1', dither=0).tobytes()


_THRESH = None
def threshold():
    """The 640 x 384 grey picture of the pattern's thresholds (2-254)."""
    global _THRESH
    if _THRESH is None:
        from PIL import Image
        tile = bytes(int((BAYER[y][x] + 0.5) * 4) for y in range(8) for x in range(8))
        t = Image.frombytes('L', (8, 8), tile)
        _THRESH = Image.new('L', (W, H))
        for y in range(0, H, 8):
            for x in range(0, W, 8): _THRESH.paste(t, (x, y))
    return _THRESH


# ---- the encoder --------------------------------------------------------
class Encoder:
    """What the GRiD shows (shown, after the last frame it has) and the
    picture wanted; make() sends the difference in one CELLS payload."""
    def __init__(s):
        s.reset()

    def reset(s):
        """The GRiD's screen unknown: the next frame clears it first."""
        s.shown = None; s.pending = None
        s.target = None                 # the picture the last frame went towards (its scroll is in shown)

    def delivered(s):
        if s.pending is not None:
            s.shown, s.pending = s.pending, None

    def dirty(s, bits):
        """Something to send for bits (counting a frame not yet known to be there)."""
        have = s.pending if s.pending is not None else s.shown
        return have is None or have != bits

    def make(s, bits, maxpay):
        """-> (payload, more): a CELLS payload that brings the GRiD towards
        bits, and whether more is left (None, False: nothing to send)."""
        if s.shown is not None and s.shown == bits: return None, False
        clear = s.shown is None
        base = bytearray(BLANK if clear else s.shown)
        out = bytearray([F_HIDDEN | (F_CLEAR if clear else 0), 0, 0])
        start = 3
        if not clear and bits != s.target:              # a new picture: did it scroll?
            k = shift_of(base, bits)
            if k:
                out += bytes([OP_SCROLL, 0, H // LINES - 1, k])
                base = scroll(base, k); start = len(out)
        more = False
        y = 0
        while y < H:
            line = bits[y * BPL:(y + 1) * BPL]
            if line == base[y * BPL:(y + 1) * BPL]:
                y += 1; continue
            # a run of changed lines, as wide as their changes
            y1 = y; x0, x1 = BPL, 0
            while y1 < H and y1 - y < 255:
                a = bits[y1 * BPL:(y1 + 1) * BPL]; b = base[y1 * BPL:(y1 + 1) * BPL]
                if a == b: break
                l, r = span(a, b)
                x0, x1 = min(x0, l), max(x1, r)
                y1 += 1
            done = s._rect(out, base, bits, y, y1, x0, x1, maxpay)
            if done == y and len(out) == start:
                # not one line of it fits a frame (a small one): a narrower piece now, the rest next
                w = maxpay - len(out) - OP_HEAD - 2   # (PackBits makes w bytes into w + 1 at most)
                l, r = span(bits[y * BPL:(y + 1) * BPL], base[y * BPL:(y + 1) * BPL])
                while w > 0 and s._rect(out, base, bits, y, y + 1, l, min(r, l + w), maxpay) == y: w //= 2
            if done < y1:
                more = True; break
            y = y1
        s.pending = bytes(base); s.target = bits
        return bytes(out), more

    @staticmethod
    def _rect(out, base, bits, y0, y1, x0, x1, maxpay):
        """Lines y0..y1-1, bytes x0..x1-1, as FDh operations into out while
        they fit; the lines sent are put into base.  -> the first line not sent."""
        w = x1 - x0
        y = y0
        while y < y1:
            if len(out) + OP_HEAD + 2 > maxpay: return y
            head = len(out)
            out += bytes([OP_PIX, y & 0xFF, y >> 8, x0, w, 0])
            h = 0
            while y < y1 and h < 255:
                code = packbits(bits[y * BPL + x0:y * BPL + x1])
                if len(out) + len(code) > maxpay: break
                out += code
                base[y * BPL + x0:y * BPL + x1] = bits[y * BPL + x0:y * BPL + x1]
                y += 1; h += 1
            if h == 0:
                del out[head:]; return y
            out[head + 5] = h
        return y


def span(a, b):
    """The bytes where two lines differ: (first, last + 1)."""
    l = 0
    while a[l] == b[l]: l += 1
    r = len(a)
    while a[r - 1] == b[r - 1]: r -= 1
    return l, r


def scroll(bits, k):
    """The screen moved up by k rows of 16 lines, blank lines below (what
    the GRiD's FEh 0, 23, k does)."""
    n = k * LINES * BPL
    return bytearray(bits[n:]) + bytearray(n)


def shift_of(shown, bits, min_gain=4 * LINES):
    """k (1-23) if the new picture is mostly the old one moved up by k rows
    of 16 lines (the page scrolled down): worth a scroll op first.  0 if not."""
    def same(a, b, k):
        off = k * LINES
        return sum(1 for y in range(H - off) if b[y * BPL:(y + 1) * BPL] == a[(y + off) * BPL:(y + off + 1) * BPL]
                   and any(b[y * BPL:(y + 1) * BPL]))
    here = sum(1 for y in range(H) if bits[y * BPL:(y + 1) * BPL] == shown[y * BPL:(y + 1) * BPL]
               and any(bits[y * BPL:(y + 1) * BPL]))
    best, bk = here + min_gain, 0
    for k in range(1, H // LINES):
        n = same(shown, bits, k)
        if n > best: best, bk = n, k
    return bk


def apply_pixels(payload, bits, one=False):
    """What the GRiD does to its screen's pixels with a CELLS payload's
    clear, scroll and FDh operations (cell operations are skipped).  For
    tests and GridSim; returns False on a malformed FDh (the frame ends).
    one: only the FDh at payload[3:]: -> its length, or False."""
    p = payload
    if p[0] & F_CLEAR: bits[:] = BLANK
    i = 3
    while i < len(p):
        op = p[i]
        if op == OP_SCROLL:
            k = p[i + 3]; bits[:] = scroll(bits, k) if (p[i + 1], p[i + 2]) == (0, H // LINES - 1) else bits
            i += 4; continue
        if op == OP_PIX:
            if i + OP_HEAD > len(p): return False
            y = p[i + 1] | p[i + 2] << 8; x, w, h = p[i + 3], p[i + 4], p[i + 5]
            if w == 0 or x + w > BPL or h == 0 or y + h > H: return False
            i += OP_HEAD
            for yy in range(y, y + h):
                line, i = unpackbits(p, i, w)
                if line is None: return False
                bits[yy * BPL + x:yy * BPL + x + w] = line
            if one: return i - 3
            continue
        # a cell operation: run or fill (skipped here)
        row, ln = op, p[i + 2]; i += 3
        if ln & 0x80: i += 1
        i += 1 if row & 0x80 else (ln & 0x7F)
    return True
