"""Decode GRiD screen snapshots (SCREEN reply) into text or a PNG."""
import base64, io, struct

AMBER = (255, 170, 0)
DARK = (24, 10, 0)


def parse(data):
    """SCREEN reply: mode, banks, bpp (1 byte each), width, height, bytes per
    line (2 bytes each), then video memory as captured."""
    mode, banks, bpp, w, h, bpl = struct.unpack_from('<BBBHHH', data)
    return dict(mode=mode, banks=banks, bpp=bpp, width=w, height=h, bpl=bpl, data=bytes(data[9:]))


def is_text(snap):
    return snap['bpp'] == 0


def text(snap):
    """Text modes: width x height cells of (char, attribute)."""
    w, h, d = snap['width'], snap['height'], snap['data']
    lines = []
    for r in range(h):
        row = d[r * w * 2:(r + 1) * w * 2:2]
        lines.append(bytes(row).decode('cp437', 'replace').rstrip())
    while lines and not lines[-1]: lines.pop()
    return '\n'.join(lines)


def image(snap):
    """Graphics modes -> PIL image (amber on dark, aspect corrected)."""
    from PIL import Image
    w, h, bpl, banks, bpp, d = (snap['width'], snap['height'], snap['bpl'],
                                snap['banks'] or 1, snap['bpp'], snap['data'])
    img = Image.new('RGB', (w, h), DARK)
    px = img.load()
    levels = [DARK, (120, 70, 0), (190, 120, 0), AMBER]
    for y in range(h):
        base = (y % banks) * 0x2000 + (y // banks) * bpl
        row = d[base:base + bpl]
        if bpp == 1:
            for x in range(min(w, len(row) * 8)):
                if row[x >> 3] & (0x80 >> (x & 7)): px[x, y] = AMBER
        else:
            for x in range(min(w, len(row) * 4)):
                v = (row[x >> 2] >> (6 - 2 * (x & 3))) & 3
                if v: px[x, y] = levels[v]
    if h <= 200:                                 # CGA modes: square the pixels
        img = img.resize((w if w >= 640 else w * 2, h * 2 if w >= 640 else h * 2), Image.NEAREST)
    return img


def png_block(snap):
    img = image(snap)
    buf = io.BytesIO(); img.save(buf, 'PNG')
    return {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                        'data': base64.b64encode(buf.getvalue()).decode()}}


def describe(snap):
    if is_text(snap):
        return 'text mode %02Xh, %dx%d' % (snap['mode'], snap['width'], snap['height'])
    return 'graphics mode %02Xh, %dx%d' % (snap['mode'], snap['width'], snap['height'])
