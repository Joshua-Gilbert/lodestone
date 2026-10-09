"""Term: the screen Claude Code draws in its pty, and what to send the GRiD.

pyte keeps the 80x24 screen the program has drawn.  The Encoder keeps what
the GRiD shows and turns the difference into CELLS frames: runs of cells,
fills and scrolls, always for the latest screen, never a backlog.

CELLS (Pi -> GRiD 4Bh), one frame, never MORE:
    flags (1)       bit 0: clear rows 0-23 first; bit 1: cursor hidden
    cursor row (1), cursor column (1)
    then operations until the end of the payload:
      run    row, col, len, [attr], len glyphs
      fill   row|80h, col, len, [attr], glyph        (one glyph len times)
      scroll FEh, top, bottom, n                      (rows top..bottom up by n,
                                                       blank rows come in below)
    len bit 7: an attribute byte follows (bit 0 inverse, bit 1 underline);
    without it the cells are plain.  Glyphs are GRiD codes 20h-A0h.
"""
import re, time, unicodedata
import pyte
from . import glp
from .render import UMAP

ROWS, COLS = 24, 80
BLANK = 0x20
A_INV, A_UL = 1, 2
F_CLEAR, F_HIDDEN = 1, 2
OP_SCROLL = 0xFE


# ---- Unicode -> one GRiD glyph per cell ------------------------------------
CELL_MAP = {
    # Claude Code's own symbols
    '⏺': glp.GL_BULLET, '●': glp.GL_BULLET, '•': glp.GL_BULLET, '◉': glp.GL_BULLET,
    '○': 'o', '◯': 'o', '◦': 'o',
    '⎿': glp.GL_CORNER, '❯': '>', '›': '>', '»': '>', '‹': '<', '«': '<',
    '⏵': glp.GL_TRI, '⏴': '<', '▸': glp.GL_TRI, '▶': glp.GL_TRI, '►': glp.GL_TRI, '▷': glp.GL_TRI,
    '◀': '<', '▲': '^', '▼': 'v', '△': '^', '▽': 'v',
    '✓': glp.GL_CHECK, '✔': glp.GL_CHECK, '✗': glp.GL_CROSS, '✘': glp.GL_CROSS, '×': 0x94,
    # the spinner: · ✢ ✳ ✶ ✻ ✽ (and the macOS set)
    '·': glp.GL_SPIN[0], '✢': glp.GL_SPIN[1], '✳': glp.GL_SPIN[2], '✶': glp.GL_SPIN[3],
    '✻': glp.GL_SPIN[4], '✽': glp.GL_SPIN[5], '∗': '*', '✱': glp.GL_SPIN[2], '✺': glp.GL_SPIN[5],
    '…': glp.GL_ELLIPSIS, '⋯': glp.GL_ELLIPSIS, '⋮': ':',
    # lines and boxes (rounded, heavy, double and dashed all on the one set)
    '─': glp.GL_RULE, '━': glp.GL_RULE, '═': glp.GL_RULE, '╌': glp.GL_RULE, '┄': glp.GL_RULE,
    '┈': glp.GL_RULE, '╍': glp.GL_RULE, '⎯': glp.GL_RULE, '—': glp.GL_RULE, '―': glp.GL_RULE,
    '│': glp.GL_BAR, '┃': glp.GL_BAR, '║': glp.GL_BAR, '╎': glp.GL_BAR, '┆': glp.GL_BAR,
    '┊': glp.GL_BAR, '▏': glp.GL_BAR, '▕': glp.GL_BAR,
    '╭': glp.GL_TL, '┌': glp.GL_TL, '┏': glp.GL_TL, '╔': glp.GL_TL,
    '╮': glp.GL_TR, '┐': glp.GL_TR, '┓': glp.GL_TR, '╗': glp.GL_TR,
    '╰': glp.GL_BL, '└': glp.GL_BL, '┗': glp.GL_BL, '╚': glp.GL_BL,
    '╯': glp.GL_BR, '┘': glp.GL_BR, '┛': glp.GL_BR, '╝': glp.GL_BR,
    '├': glp.GL_TEE_R, '┣': glp.GL_TEE_R, '╠': glp.GL_TEE_R, '┤': glp.GL_TEE_L, '┫': glp.GL_TEE_L,
    '╣': glp.GL_TEE_L, '┬': glp.GL_TEE_D, '┳': glp.GL_TEE_D, '╦': glp.GL_TEE_D,
    '┴': glp.GL_TEE_U, '┻': glp.GL_TEE_U, '╩': glp.GL_TEE_U, '┼': glp.GL_CROSSING,
    '╋': glp.GL_CROSSING, '╬': glp.GL_CROSSING,
    # shades
    '░': ':', '▒': '%', '▓': '#',
    # arrows and the rest
    '→': glp.GL_ARROW, '⇒': glp.GL_ARROW, '⟶': glp.GL_ARROW, '➜': glp.GL_ARROW, '←': '<',
    '↑': '^', '↓': 'v', '↵': '<', '⏎': '<', '↳': glp.GL_CORNER, '⇧': '^', '⌘': '#', '⌥': '~',
    '≠': '#', '−': '-', '–': '-', '‐': '-', '‑': '-',
}
for _k, _v in UMAP.items():                    # render.py's map, where it is one glyph
    if _k not in CELL_MAP and len(_v) == 1:
        CELL_MAP[_k] = _v
# Block elements: mostly-full ones are an inverse blank, the others plain.
FULL_BLOCKS = set('█▛▜▙▟▉▊▇')
EMPTY_BLOCKS = set('▌▐▀▄▖▗▘▝▚▞▁▂▃▅▆▋▍▎')

_cache = {}


def glyph(data):
    """pyte cell text -> (GRiD code, flip inverse)."""
    r = _cache.get(data)
    if r is not None: return r
    r = _glyph(data)
    if len(_cache) < 4096: _cache[data] = r
    return r


def _glyph(data):
    if not data: return BLANK, False                  # right half of a wide character
    ch = data[0]
    o = ord(ch)
    if 32 <= o < 127: return o, False
    if ch in FULL_BLOCKS: return BLANK, True
    if ch in EMPTY_BLOCKS: return BLANK, False
    v = CELL_MAP.get(ch)
    if v is not None:
        return (v if isinstance(v, int) else ord(v)), False
    if 0x2800 <= o <= 0x28FF:                         # braille spinners
        return glp.GL_SPIN[o % 6], False
    if o < 32 or 0x7F <= o <= 0x9F: return BLANK, False
    d = unicodedata.normalize('NFKD', ch)
    a = [c for c in d if 32 <= ord(c) < 127]
    if a: return ord(a[0]), False
    if unicodedata.category(ch).startswith('Z'): return BLANK, False
    return ord('?'), False


def fold_title(text):
    """A window title for the GRiD's status row: folded, the spinner dropped."""
    out = []
    for ch in text:
        g, _ = glyph(ch)
        out.append(chr(g))
    t = ''.join(out)
    t = re.sub(r'^[\x80-\xa0*\s]+', '', t).strip()
    return t[:60]


# ---- the screen -------------------------------------------------------------
class TermScreen(pyte.Screen):
    """pyte plus what it lacks: the alternate screen (1049/1047/47) and
    synchronised output (2026: hold the diff until the frame is complete)."""
    ALT = (1049, 1047, 47)

    def __init__(s, cols=COLS, rows=ROWS):
        super().__init__(cols, rows)
        s.sync = False; s.sync_t = 0.0; s.main = None

    def reset(s):
        super().reset()
        s.sync = False; s.main = None

    def set_mode(s, *modes, **kw):
        if kw.get('private'):
            if 2026 in modes:
                s.sync = True; s.sync_t = time.time()
            if any(m in s.ALT for m in modes) and s.main is None:
                if 1049 in modes: s.save_cursor()
                s.main = {y: dict(line) for y, line in s.buffer.items()}
                s.erase_in_display(2)
            modes = tuple(m for m in modes if m != 2026 and m not in s.ALT)
            if not modes: return
        super().set_mode(*modes, **kw)

    def reset_mode(s, *modes, **kw):
        if kw.get('private'):
            if 2026 in modes: s.sync = False
            if any(m in s.ALT for m in modes) and s.main is not None:
                s.buffer.clear()
                for y, line in s.main.items(): s.buffer[y].update(line)
                s.main = None
                if 1049 in modes: s.restore_cursor()
            modes = tuple(m for m in modes if m != 2026 and m not in s.ALT)
            if not modes: return
        super().reset_mode(*modes, **kw)

    def select_graphic_rendition(s, *attrs, **kw):
        if kw.get('private'): return                  # CSI > 4;2 m is not SGR
        super().select_graphic_rendition(*attrs)

    @property
    def app_cursor(s):
        return (1 << 5) in s.mode                     # DECCKM

    def cells(s):
        """-> (24 bytearrays of glyphs, 24 bytearrays of attributes)"""
        chs, ats = [], []
        for y in range(s.lines):
            line = s.buffer[y]
            ch = bytearray(s.columns); at = bytearray(s.columns)
            for x in range(s.columns):
                c = line[x]
                g, flip = glyph(c.data)
                bg = c.bg not in ('default', 'black', '000000')
                inv = (c.reverse != bg) != flip
                ch[x] = g
                at[x] = (A_INV if inv else 0) | (A_UL if c.underscore else 0)
            chs.append(ch); ats.append(at)
        return chs, ats

    def text(s):
        """The folded screen as text (tests)."""
        chs, _ = s.cells()
        return [bytes(r).decode('latin1') for r in chs]


class PreFilter:
    """Bytes from the pty -> bytes for pyte, plus answers for the program.

    Drops what pyte would misread or show as text: CSI with a < = > marker
    (modifyOtherKeys, the kitty keyboard protocol), DCS/APC/PM/SOS strings.
    Answers DECRQM and the colour queries (OSC 10/11) itself; pyte answers
    DA and the cursor position report."""
    MAXSEQ = 4096

    def __init__(s, modes=lambda: set()):
        s.carry = b''; s.modes = modes

    def feed(s, data):
        """-> (bytes for pyte, answers), for when the order doesn't matter."""
        out = bytearray(); answers = []
        for kind, b in s.parts(data):
            if kind == 'answer': answers.append(b)
            else: out += b
        return bytes(out), answers

    def parts(s, data):
        """-> [('data', bytes for pyte) | ('answer', bytes for the program)]
        in order: a program that asks several things and then DA1 (which
        pyte answers) must get the answers in the order it asked."""
        data = s.carry + bytes(data); s.carry = b''
        out = []; cur = bytearray()
        i = 0; n = len(data)
        while i < n:
            j = data.find(b'\x1b', i)
            if j < 0:
                cur += data[i:]; break
            cur += data[i:j]
            end, keep, ans = s._seq(data, j)
            if end is None:                           # incomplete: wait for more
                rest = data[j:]
                if len(rest) > s.MAXSEQ: cur += rest  # not an escape we know: let pyte have it
                else: s.carry = rest
                break
            if keep is True: cur += data[j:end]
            elif keep: cur += keep                    # rewritten
            if ans:
                if cur: out.append(('data', bytes(cur))); cur = bytearray()
                out.append(('answer', ans))
            i = end
        if cur: out.append(('data', bytes(cur)))
        return out

    def _seq(s, d, j):
        n = len(d)
        if j + 1 >= n: return None, False, None
        c = d[j + 1]
        if c == 0x5B:                                 # CSI
            k = j + 2
            while k < n and 0x30 <= d[k] <= 0x3F: k += 1
            params = d[j + 2:k]
            while k < n and 0x20 <= d[k] <= 0x2F: k += 1
            if k >= n: return None, False, None
            inter = d[j + 2 + len(params):k]; final = d[k]; end = k + 1
            if params[:1] in (b'<', b'=', b'>'): return end, False, None
            if params[:1] == b'?' and inter == b'$' and final == 0x70:        # DECRQM
                return end, False, s._decrqm(params[1:])
            if params[:1] == b'?' and final == 0x75: return end, False, None  # kitty keyboard query
            if final == 0x74: return end, False, None                         # window ops
            if final == 0x6D and b':' in params:                              # SGR with sub-parameters
                return end, b'\x1b[' + _sgr_colons(params) + b'm', None
            return end, True, None
        if c == 0x5D:                                 # OSC ... BEL or ST
            k = j + 2
            while k < n:
                if d[k] == 0x07: end = k + 1; body = d[j + 2:k]; break
                if d[k] == 0x1B and k + 1 < n and d[k + 1] == 0x5C:
                    end = k + 2; body = d[j + 2:k]; break
                if d[k] == 0x1B and k + 1 >= n: return None, False, None
                k += 1
            else:
                return None, False, None
            m = re.fullmatch(rb'(1[01]);\?', body)
            if m:
                rgb = b'rgb:ffff/aaaa/0000' if m.group(1) == b'10' else b'rgb:0000/0000/0000'
                return end, False, b'\x1b]' + m.group(1) + b';' + rgb + b'\x1b\\'
            return end, True, None
        if c in (0x50, 0x5F, 0x5E, 0x58):             # DCS APC PM SOS ... ST
            k = d.find(b'\x1b\\', j + 2)
            if k < 0: return None, False, None
            return k + 2, False, None
        return j + 1, True, None                      # other ESC sequences: pyte's

    def _decrqm(s, p):
        try: mode = int(p)
        except ValueError: return None
        known = {1, 7, 25, 47, 1047, 1049, 2004, 2026}
        st = 0 if mode not in known else (1 if (mode << 5) in s.modes() else 2)
        return b'\x1b[?%d;%d$y' % (mode, st)


def _sgr_colons(params):
    """pyte reads only ';': '4:3' (curly underline) -> '4', '38:2::r:g:b' ->
    '38;2;r;g;b', '38:5:n' -> '38;5;n'; underline colours (58) dropped."""
    out = []
    for g in params.split(b';'):
        if b':' not in g:
            out.append(g); continue
        p = g.split(b':')
        if p[0] in (b'38', b'48'):
            sub = p[1:]
            if sub[:1] == [b'2'] and len(sub) >= 5: sub = [b'2'] + sub[-3:]
            out += [p[0]] + sub
        elif p[0] != b'58':
            out.append(p[0])
    return b';'.join(x for x in out if x != b'') or b'0'


# ---- the diff encoder -------------------------------------------------------
def _blank_rows():
    return [bytearray(b' ' * COLS) for _ in range(ROWS)], [bytearray(COLS) for _ in range(ROWS)]


def _row_cost(tc, ta, bc, ba):
    """Rough bytes to bring row b to t (for choosing a scroll)."""
    if tc == bc and ta == ba: return 0
    n = sum(1 for x in range(COLS) if tc[x] != bc[x] or ta[x] != ba[x])
    return n + 4


def _nonblank(c, a):
    return c.count(BLANK) != COLS or any(a)


class Encoder:
    """Keeps what the GRiD shows; make() builds the next CELLS frame and
    delivered() commits it once the GRiD has it."""
    GAP = 3          # bridge runs over up to this many unchanged cells
    FILL_MIN = 6     # a fill pays off from this many equal glyphs

    def __init__(s):
        s.reset()
        s.stats = dict(frames=0, bytes=0, scrolls=0, fills=0, runs=0)

    def reset(s):
        """The GRiD's screen is unknown: the next frame clears it."""
        s.shown = None; s.cursor = None; s.pending = None

    def delivered(s):
        if s.pending is not None:
            s.shown, s.cursor = s.pending[0], s.pending[1]
            s.pending = None

    def dirty(s, tc, ta, cursor):
        if s.shown is None: return True
        bc, ba = s.shown
        return cursor != s.cursor or any(tc[r] != bc[r] or ta[r] != ba[r] for r in range(ROWS))

    def make(s, tc, ta, cursor, maxpay, order=None):
        """-> (payload, more) or (None, False) when the GRiD is up to date.
        cursor = (row, col, hidden)."""
        flags = 0
        if s.shown is None:
            bc, ba = _blank_rows(); flags |= F_CLEAR
        else:
            bc = [bytearray(r) for r in s.shown[0]]; ba = [bytearray(r) for r in s.shown[1]]
        crow, ccol, hidden = cursor
        if hidden: flags |= F_HIDDEN
        out = bytearray([flags, crow & 0xFF, ccol & 0xFF])
        changed = [r for r in range(ROWS) if tc[r] != bc[r] or ta[r] != ba[r]]
        if not changed and not flags & F_CLEAR and cursor == s.cursor:
            return None, False
        if len(changed) >= 2 and not flags & F_CLEAR:
            sc = s._scroll(tc, ta, bc, ba, changed)
            if sc and len(out) + 4 <= maxpay:
                bottom, k = sc
                out += bytes([OP_SCROLL, 0, bottom, k])
                for r in range(bottom - k + 1):
                    bc[r] = bytearray(bc[r + k]); ba[r] = bytearray(ba[r + k])
                for r in range(bottom - k + 1, bottom + 1):
                    bc[r] = bytearray(b' ' * COLS); ba[r] = bytearray(COLS)
                s.stats['scrolls'] += 1
                changed = [r for r in range(ROWS) if tc[r] != bc[r] or ta[r] != ba[r]]
        rows = order(changed) if order else s._order(changed, crow)
        full = False
        for r in rows:
            for op, x0, cells in s._row_ops(r, tc[r], ta[r], bc[r], ba[r]):
                room = maxpay - len(out)
                at = ta[r][x0]
                hdr = 3 + (1 if at else 0)
                if op == 'fill':
                    if room < hdr + 1: full = True; break
                    n = cells
                    out += bytes([r | 0x80, x0, n | (0x80 if at else 0)])
                    if at: out.append(at)
                    out.append(tc[r][x0])
                    s.stats['fills'] += 1
                else:
                    n = min(cells, room - hdr)
                    if n <= 0: full = True; break
                    out += bytes([r, x0, n | (0x80 if at else 0)])
                    if at: out.append(at)
                    out += tc[r][x0:x0 + n]
                    s.stats['runs'] += 1
                    if n < cells: full = True
                bc[r][x0:x0 + n] = tc[r][x0:x0 + n]; ba[r][x0:x0 + n] = ta[r][x0:x0 + n]
                if full: break
            if full: break
        s.pending = ((bc, ba), cursor)
        more = any(tc[r] != bc[r] or ta[r] != ba[r] for r in range(ROWS))
        s.stats['frames'] += 1; s.stats['bytes'] += len(out)
        return bytes(out), more

    def _order(s, rows, crow):
        return sorted(rows, key=lambda r: (abs(r - crow), -r))

    def _row_ops(s, r, tc, ta, bc, ba):
        """Yield ('run'|'fill', x0, count) for the changed cells of one row;
        each piece has one attribute."""
        diff = [x for x in range(COLS) if tc[x] != bc[x] or ta[x] != ba[x]]
        if not diff: return
        segs = []; a = diff[0]; b = diff[0]
        for x in diff[1:]:
            if x - b <= s.GAP + 1 and ta[x] == ta[b] and all(ta[y] == ta[b] for y in range(b, x)):
                b = x
            else:
                segs.append((a, b)); a = b = x
        segs.append((a, b))
        for a, b in segs:
            x = a
            while x <= b:
                # split at attribute changes, then pull out long fills
                y = x
                while y <= b and ta[y] == ta[x]: y += 1
                yield from s._pieces(tc, x, y)
                x = y

    def _pieces(s, tc, x, y):
        i = x; lit = x
        while i < y:
            j = i
            while j < y and tc[j] == tc[i]: j += 1
            if j - i >= s.FILL_MIN:
                if lit < i: yield 'run', lit, i - lit
                yield 'fill', i, j - i
                lit = j
            i = j
        if lit < y: yield 'run', lit, y - lit

    def _scroll(s, tc, ta, bc, ba, changed):
        """Find a scroll of rows 0..bottom up by k that saves bytes."""
        tkey = [bytes(tc[r]) + bytes(ta[r]) for r in range(ROWS)]
        bkey = [bytes(bc[r]) + bytes(ba[r]) for r in range(ROWS)]
        nb = [_nonblank(tc[r], ta[r]) for r in range(ROWS)]
        cands = set()
        for i in changed:
            if not nb[i]: continue
            for j in range(i + 1, ROWS):
                if tkey[i] == bkey[j]: cands.add(j - i)
        if not cands: return None
        cost = [_row_cost(tc[r], ta[r], bc[r], ba[r]) for r in range(ROWS)]
        fresh = [_row_cost(tc[r], ta[r], b' ' * COLS, bytes(COLS)) for r in range(ROWS)]
        best = None; bestgain = 8
        for k in sorted(cands):
            for bottom in range(k, ROWS):
                gain = 0
                for r in range(bottom - k + 1):
                    if tkey[r] == bkey[r + k]: gain += cost[r]
                    elif tkey[r] == bkey[r]: gain -= fresh[r]
                for r in range(bottom - k + 1, bottom + 1):
                    if tkey[r] == bkey[r]: gain -= fresh[r]
                    else: gain += cost[r] - fresh[r]
                if gain > bestgain: best, bestgain = (bottom, k), gain
        return best


def apply(payload, chs, ats):
    """What the GRiD does with a CELLS payload (for tests and the console).
    Returns (cursor_row, cursor_col, hidden)."""
    p = payload
    flags, crow, ccol = p[0], p[1], p[2]
    if flags & F_CLEAR:
        for r in range(ROWS):
            chs[r][:] = b' ' * COLS; ats[r][:] = bytes(COLS)
    i = 3
    while i < len(p):
        if p[i] == OP_SCROLL:
            top, bottom, k = p[i + 1], p[i + 2], p[i + 3]; i += 4
            for r in range(top, bottom - k + 1):
                chs[r][:] = chs[r + k]; ats[r][:] = ats[r + k]
            for r in range(max(top, bottom - k + 1), bottom + 1):
                chs[r][:] = b' ' * COLS; ats[r][:] = bytes(COLS)
            continue
        row, col, ln = p[i], p[i + 1], p[i + 2]; i += 3
        at = 0
        if ln & 0x80: at = p[i]; i += 1
        n = ln & 0x7F
        if row & 0x80:
            g = p[i]; i += 1
            chs[row & 0x7F][col:col + n] = bytes([g]) * n
        else:
            chs[row][col:col + n] = p[i:i + n]; i += n
        ats[row & 0x7F][col:col + n] = bytes([at]) * n
    return crow, ccol, bool(flags & F_HIDDEN)
