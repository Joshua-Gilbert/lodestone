"""The page as the GRiD shows it: extract.js's blocks laid out at 80 columns.

Each line is its text plus, per column, an attribute (A_LINK, A_INV, ...) and
the act (link, button or field) the cell belongs to, -1 for none.  Nothing
here talks to Firefox, so it is tested on its own.
"""
import unicodedata
from wcwidth import wcwidth             # (pyte's own: what it gives a cell is what counts)

W = 80
A_LINK, A_INV, A_BOLD, A_FIELD, A_DIM = 1, 2, 4, 8, 16
F_BOLD, F_ITALIC, F_CODE, F_IMAGE, F_FIELD = 1, 2, 4, 8, 16

BULLET = '•'
RULE = '─'
BAR = '│'
TRI = '▸'
ELL = '…'

# what a page often has that the GRiD's font hasn't: nearest plain forms
SUBST = {
    '‘': "'", '’': "'", '‚': "'", '‛': "'", '“': '"', '”': '"',
    '„': '"', '′': "'", '″': '"', '­': '', '​': '', '‌': '', '‍': '',
    '⁠': '', '﻿': '', ' ': ' ', ' ': ' ', ' ': ' ', ' ': ' ', ' ': ' ',
    '–': '-', '—': RULE, '−': '-', '‐': '-', '‑': '-', ' ': ' ',
    '→': '→', '™': '(TM)', '©': '(c)', '®': '(R)', '…': ELL,
    '\t': '    ',
}


def clean_char(ch):
    """One cell's worth for a character: '' to drop it."""
    if ch in SUBST: return SUBST[ch]
    if ch == '\n': return ch
    o = ord(ch)
    if o < 32 or 0x7F <= o < 0xA0: return ''
    cat = unicodedata.category(ch)
    if cat in ('Mn', 'Me', 'Cf', 'Cs', 'Co', 'Cn', 'Zl', 'Zp'): return ''   # marks, format, separators
    if 0x1F000 <= o: return ''                                          # emoji and the like
    w = wcwidth(ch)
    if w == 1: return ch
    if w == 2: return '' if cat == 'So' else '?'                        # two cells wide: not on an 80x24 grid
    return ''                                                           # no width (it would shift the row)


def clean(text):
    text = unicodedata.normalize('NFC', text)
    return ''.join(clean_char(c) for c in text)


class Doc:
    """The laid-out page: lines, and where each act is."""
    def __init__(s):
        s.text = []; s.attr = []; s.act = []
        s.where = {}            # act -> (line, col) of its first cell
        s.anchors = {}          # id -> the line its block starts on (for #fragments)

    def add(s, text, attr, act):
        n = len(s.text)
        for c, a in enumerate(act):
            if a >= 0 and a not in s.where: s.where[a] = (n, c)
        s.text.append(text); s.attr.append(attr); s.act.append(act)

    def blank(s):
        if s.text and s.text[-1].strip(): s.add('', [], [])

    def __len__(s): return len(s.text)

    def acts_in(s, top, rows):
        """Acts with a cell in lines top..top+rows-1, in reading order."""
        seen, out = set(), []
        for ln in range(top, min(top + rows, len(s.text))):
            for a in s.act[ln]:
                if a >= 0 and a not in seen: seen.add(a); out.append(a)
        return out

    def find(s, needle, start=0):
        n = needle.lower()
        for i in list(range(start, len(s.text))) + list(range(0, start)):
            if n in s.text[i].lower(): return i
        return -1


def cells(runs, link_attr=A_LINK):
    """[[text, flags, act], ...] -> [(char, attr, act), ...]"""
    out = []
    for r in runs:
        text, f, a = r[0], r[1], r[2]
        at = 0
        if a >= 0: at |= link_attr
        if f & F_BOLD: at |= A_BOLD
        if f & F_FIELD: at |= A_FIELD
        if f & (F_ITALIC | F_IMAGE) and a < 0: at |= A_DIM
        for ch in clean(text):
            out.extend((c, at, a) for c in ch)
    return out


def wrap(cs, width):
    """Word-wrap cells to lines of at most width; spaces at a break go."""
    width = max(1, width)
    lines, line, word = [], [], []

    def put_word():
        nonlocal line, word
        while word:
            room = width - len(line)
            if len(word) <= room:
                line.extend(word); word = []
            elif not line or len(word) > width:
                # longer than a whole line: break it where it stands
                take = room if room > 0 else width
                if room <= 0: lines.append(line); line = []; take = width
                line.extend(word[:take]); word = word[take:]
                if word: lines.append(line); line = []
            else:
                while line and line[-1][0] == ' ': line.pop()
                lines.append(line); line = []
    for c in cs:
        if c[0] == ' ':
            put_word()
            if line and len(line) < width: line.append(c)
            elif line: lines.append(line); line = []
        elif c[0] == '\n':
            put_word(); lines.append(line); line = []
        else:
            word.append(c)
    put_word()
    while line and line[-1][0] == ' ': line.pop()
    if line or not lines: lines.append(line)
    return lines


SPACED = ('p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'quote', 'hr')


def layout(model, width=W):
    doc = Doc()
    prev = None
    for b in model.get('blocks', []):
        k = b.get('k', 'p'); d = max(0, _int(b.get('d')) - 1); q = max(0, _int(b.get('q')))
        if k in SPACED or (k in ('li', 'tr') and prev != k) or (prev in ('li', 'tr') and prev != k):
            doc.blank()
        prev = k
        for i in b.get('ids') or ():
            if isinstance(i, str): doc.anchors.setdefault(i, len(doc.text))
        qp = (BAR + ' ') * min(q, 4)
        if k == 'hr':
            doc.add(RULE * width, [0] * width, [-1] * width); continue
        cs = cells(b.get('r', []))
        if k == 'pre':
            first, rest = '  ' + qp, '  ' + qp
            lines = []
            for part in _split_nl(cs):
                lines.extend(_hard(part, max(20, width - len(first))) or [[]])
            while lines and not lines[-1]: lines.pop()
        else:
            # strip edge spaces
            while cs and cs[0][0] == ' ': cs.pop(0)
            while cs and cs[-1][0] == ' ': cs.pop()
            if not cs: continue
            if k == 'li':
                ind = '  ' * min(d, 8) + qp
                m = _int(b.get('m'))
                mark = ('%d. ' % m)[:7] if m > 0 else (BULLET + ' ' if m < 0 else '  ')
                first, rest = ind + mark, ind + ' ' * len(mark)
            elif k in ('h1', 'h2'):
                first = rest = qp
                cs = [(c, a | A_INV, x) for c, a, x in cs]
            elif k in ('h3', 'h4', 'h5', 'h6'):
                first, rest = qp + TRI + ' ', qp + '  '
                cs = [(c, a | A_BOLD, x) for c, a, x in cs]
            else:
                first = rest = qp
            lines = wrap(cs, max(20, width - max(len(first), len(rest))))
        for i, ln in enumerate(lines):
            pre = first if i == 0 else rest
            text = pre + ''.join(c for c, _, _ in ln)
            attr = [0] * len(pre) + [a for _, a, _ in ln]
            act = [-1] * len(pre) + [x for _, _, x in ln]
            if k == 'h1':                                      # a whole inverse band
                pad = width - len(text)
                text += ' ' * pad; attr += [A_INV] * pad; act += [-1] * pad
            doc.add(text, attr, act)
    while doc.text and not doc.text[-1].strip():
        doc.text.pop(); doc.attr.pop(); doc.act.pop()
    if not doc.text:
        doc.add('(This page shows no text.)', [A_DIM] * 26, [-1] * 26)
    return doc


def _int(v):
    """A number from the page (which may send null, 1e80 or text): 0 if not one."""
    try: return max(-99999, min(99999, int(v)))
    except (TypeError, ValueError, OverflowError): return 0


def _split_nl(cs):
    part = []
    for c in cs:
        if c[0] == '\n': yield part; part = []
        else: part.append(c)
    yield part


def _hard(cs, width):
    if not cs: return [[]]
    return [cs[i:i + width] for i in range(0, len(cs), width)]
