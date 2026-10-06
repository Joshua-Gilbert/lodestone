"""Turn Claude's streamed Markdown/Unicode into GRiD TEXT bytes.

The GRiD screen is 80 columns, amber, 1 bit per pixel, with an 8x16 font of
ASCII plus a few extra glyphs (80h-A0h).  Wrapping happens here, at word
boundaries, so the GRiD only ever receives finished lines and whole words.
"""
import unicodedata
from . import glp

NL = bytes([glp.T_NL])
INV_ON, INV_OFF = bytes([glp.T_INV_ON]), bytes([glp.T_INV_OFF])
UL_ON, UL_OFF = bytes([glp.T_UL_ON]), bytes([glp.T_UL_OFF])
UL_ON_C, UL_OFF_C = '\x10', '\x11'          # underline toggles inside text

# extra glyphs on the GRiD (CLAUDE.ASM font, 90h-97h)
G_DEG, G_MICRO, G_OHM, G_PLUSMIN, G_TIMES, G_APPROX, G_LE, G_GE = range(0x90, 0x98)

UMAP = {
    '‘': "'", '’': "'", '‚': "'", '‛': "'", '′': "'",
    '“': '"', '”': '"', '„': '"', '″': '"',
    '–': '-', '—': '--', '―': '--', '−': '-', '‐': '-', '‑': '-',
    '…': chr(glp.GL_ELLIPSIS), '●': chr(glp.GL_BULLET), '•': chr(glp.GL_BULLET),
    '⎿': chr(glp.GL_CORNER), '→': chr(glp.GL_ARROW), '⇒': chr(glp.GL_ARROW),
    '✓': chr(glp.GL_CHECK), '✔': chr(glp.GL_CHECK), '✅': chr(glp.GL_CHECK),
    '✗': chr(glp.GL_CROSS), '✘': chr(glp.GL_CROSS), '❌': chr(glp.GL_CROSS),
    '·': chr(glp.GL_MIDDOT), '‧': chr(glp.GL_MIDDOT), '⋅': chr(glp.GL_MIDDOT),
    '─': chr(glp.GL_RULE), '━': chr(glp.GL_RULE), '│': chr(glp.GL_BAR),
    '┃': chr(glp.GL_BAR), '▸': chr(glp.GL_TRI), '▶': chr(glp.GL_TRI),
    '►': chr(glp.GL_TRI),
    '°': chr(G_DEG), 'µ': chr(G_MICRO), 'μ': chr(G_MICRO), 'Ω': chr(G_OHM),
    'Ω': chr(G_OHM), '±': chr(G_PLUSMIN), '×': chr(G_TIMES), '≈': chr(G_APPROX),
    '≤': chr(G_LE), '≥': chr(G_GE),
    '←': '<-', '↑': '^', '↓': 'v', '↔': '<->', '≠': '!=',
    '└': chr(glp.GL_BL), '┘': chr(glp.GL_BR), '┌': chr(glp.GL_TL), '┐': chr(glp.GL_TR),
    '╰': chr(glp.GL_BL), '╯': chr(glp.GL_BR), '╭': chr(glp.GL_TL), '╮': chr(glp.GL_TR),
    '├': chr(glp.GL_TEE_R), '┤': chr(glp.GL_TEE_L), '┬': chr(glp.GL_TEE_D), '┴': chr(glp.GL_TEE_U),
    '┼': chr(glp.GL_CROSSING), '╚': chr(glp.GL_BL), '╝': chr(glp.GL_BR), '╔': chr(glp.GL_TL),
    '╗': chr(glp.GL_TR), '╠': chr(glp.GL_TEE_R), '╣': chr(glp.GL_TEE_L), '╦': chr(glp.GL_TEE_D),
    '╩': chr(glp.GL_TEE_U), '╬': chr(glp.GL_CROSSING), '═': chr(glp.GL_RULE), '║': chr(glp.GL_BAR), ' ': ' ', ' ': ' ', '​': '',
    '©': '(c)', '®': '(R)', '™': '(TM)', '½': '1/2', '¼': '1/4',
    '²': '^2', '³': '^3', '∞': 'inf', '√': 'sqrt', 'Δ': 'delta',
    'π': 'pi', '\t': '    ', '\r': '',
}


def fold(text):
    """Unicode -> characters the GRiD can draw (ASCII + our glyphs, as chr()
    values 80h-A0h)."""
    out = []
    for ch in text:
        o = ord(ch)
        if 32 <= o < 127 or ch == '\n':
            out.append(ch)
        elif 0x80 <= o <= glp.GL_LAST:          # already a GRiD glyph
            out.append(ch)
        elif ch in UMAP:
            out.append(UMAP[ch])
        elif o < 32 or 0x7F <= o <= 0x9F:
            continue
        else:
            d = unicodedata.normalize('NFKD', ch)
            a = ''.join(c for c in d if 32 <= ord(c) < 127)
            if a: out.append(a)
            elif not unicodedata.category(ch).startswith('M'): out.append('?')
    return ''.join(out)


def to_bytes(text):
    return text.encode('latin1', 'replace')


def visible_len(w):
    return len(w) - w.count(UL_ON_C) - w.count(UL_OFF_C)


class Renderer:
    """Streaming Markdown -> wrapped GRiD text.  feed() returns bytes ready to
    send; finish() ends the current text block."""
    def __init__(s, width=79):
        s.width = width
        s.reset()

    def reset(s):
        s.pending = ''; s.col = 0; s.line_start = True; s.in_code = False
        s.heading = False; s.ul = False; s.hang = 0; s.drop_line = False
        s.margin = 0; s.bullet = False; s.started = False

    # ---- blocks of a turn: Claude Code layout ------------------------------
    def gap(s):
        """Before a new block of the answer: a blank line, except before
        the first (the GRiD leaves one after the prompt)."""
        out = bytearray()
        if not s.line_start: out += s.finish()
        if s.started: out += NL
        s.started = True
        return bytes(out)

    def start_text(s):
        """A text block: '● ' before its first line, the rest indented 2."""
        out = s.gap()
        s.margin = 2; s.bullet = True
        return out

    def _margin(s):
        if not s.margin or s.col: return b''
        s.col = s.margin
        if s.bullet:
            s.bullet = False
            return to_bytes(chr(glp.GL_BULLET) + ' ')
        return b' ' * s.margin

    # ---- output primitives ----------------------------------------------
    def _newline(s):
        out = bytearray()
        if s.ul: out += UL_OFF; s.ul = False
        if s.heading: out += b' ' + INV_OFF; s.heading = False
        out += NL
        s.col = 0
        return bytes(out)

    def _wrap(s):
        """Break inside a paragraph: continue on the next line at the hang."""
        out = bytearray()
        ul = s.ul
        if ul: out += UL_OFF
        out += NL; s.col = 0
        pad = s.margin + s.hang
        if pad: out += b' ' * pad; s.col = pad
        if ul: out += UL_ON
        return bytes(out)

    def _word(s, w):
        out = bytearray()
        n = visible_len(w)
        if s.col > s.margin + s.hang and s.col + n > s.width:
            out += s._wrap()
        for ch in w:
            if ch == UL_ON_C:
                if not s.ul: out += UL_ON; s.ul = True
                continue
            if ch == UL_OFF_C:
                if s.ul: out += UL_OFF; s.ul = False
                continue
            if s.col >= s.width:            # a word longer than the line
                out += s._wrap()
            out += to_bytes(ch); s.col += 1
        return bytes(out)

    def _space(s):
        if 0 < s.col < s.width:
            s.col += 1
            return b' '
        return b''

    def _words(s, text):
        out = bytearray()
        words = text.split(' ')
        for k, w in enumerate(words):
            if k and w: out += s._space()
            if w: out += s._word(w)
        return bytes(out)

    # ---- Markdown ------------------------------------------------------
    def _classify(s, seg):
        """First committed piece of a source line.  Returns the text to show,
        or None if the whole line is dropped (code fences)."""
        st = seg.lstrip(' ')
        lead = len(seg) - len(st)
        if st.startswith('```'):
            s.in_code = not s.in_code
            return None
        if s.in_code:
            return seg
        s.hang = min(lead, 40)
        if st.startswith('#'):
            n = len(st) - len(st.lstrip('#'))
            if n <= 6 and st[n:n + 1] == ' ':
                s.heading = True
                s.hang = 1
                return '\x00' + st[n + 1:]          # \x00 = start inverse
        if st[:2] in ('- ', '* ', '+ '):
            s.hang = min(lead + 2, 40)
            return ' ' * lead + '- ' + st[2:]
        i = 0
        while i < len(st) and st[i].isdigit(): i += 1
        if 0 < i < 4 and st[i:i + 2] in ('. ', ') '):
            s.hang = min(lead + i + 2, 40)
        elif st.startswith('> '):
            s.hang = min(lead + 2, 40)
        return seg

    def _emit(s, seg):
        out = bytearray()
        if s.line_start:
            s.line_start = False
            seg = s._classify(seg)
            if seg is None:
                s.drop_line = True
                return b''
        if s.drop_line:
            return b''
        fresh = s.col == 0
        if not seg and not s.in_code:
            return b''
        out += s._margin()
        if s.in_code:
            if fresh: out += b'  '; s.col += 2
            for ch in fold(seg):
                if s.col >= s.width:
                    out += NL + b' ' * (s.margin + 2); s.col = s.margin + 2
                out += to_bytes(ch); s.col += 1
            return bytes(out)
        if seg.startswith('\x00'):
            out += INV_ON + b' '; s.col += 1; seg = seg[1:]
        text = fold(seg).replace('`', '')
        if '**' in text:
            parts = text.split('**'); text = parts[0]
            for p in parts[1:]:
                s._ul_next = not getattr(s, '_ul_next', s.ul)
                text += (UL_ON_C if s._ul_next else UL_OFF_C) + p
        if fresh:                            # keep the line's indentation
            i = 0
            while i < len(text) and text[i] == ' ':
                i += 1
            if i: out += b' ' * min(i, 40); s.col += min(i, 40)
            text = text[i:]
        out += s._words(text)
        return bytes(out)

    def _end_line(s):
        if s.drop_line:
            s.drop_line = False; s.line_start = True; s.col = 0
            return b''
        s.line_start = True
        s._ul_next = False
        out = s._newline()
        if not s.in_code: s.hang = 0
        return out

    # ---- public --------------------------------------------------------
    def feed(s, text):
        """Add streamed text.  Returns the bytes that are safe to show now."""
        s.pending += text.replace('\r', '')
        out = bytearray()
        while '\n' in s.pending:
            line, s.pending = s.pending.split('\n', 1)
            if s.bullet and not s.in_code and not line.strip():
                continue                     # no blank lines before the bullet
            out += s._emit(line)
            out += s._end_line()
        p = s.pending
        if p:
            if s.line_start:
                st = p.lstrip(' ')
                # need the first word complete to classify the line
                if ' ' not in st: return bytes(out)
            if s.in_code: return bytes(out)  # code lines go out whole
            j = p.rfind(' ')
            if j > 0:
                out += s._emit(p[:j])
                s.pending = p[j:]            # keep the space: it separates words
        return bytes(out)

    def finish(s):
        """End of a text block."""
        out = bytearray()
        if s.pending.strip(' '):
            out += s._emit(s.pending)
        s.pending = ''
        if not s.line_start:
            out += s._end_line()
        s.in_code = False; s.hang = 0; s.margin = 0; s.bullet = False
        return bytes(out)

    # ---- pre-formatted lines (tool calls etc.) -------------------------
    def block(s, text, first='', rest='', inverse=False, gap=False):
        """Word-wrapped plain text: `first` before line one, `rest` before the
        others (and before wrapped continuations).  gap: a new block of the
        answer (a tool call), so a blank line before it."""
        out = bytearray()
        if not s.line_start: out += s.finish()
        if gap: out += s.gap()
        for n, line in enumerate(fold(text).split('\n')):
            pre = fold(first if n == 0 else rest)
            out += to_bytes(pre); s.col = len(pre); s.hang = len(fold(rest))
            if inverse: out += INV_ON
            out += s._words(line)
            if inverse: out += INV_OFF
            out += NL; s.col = 0
        s.hang = 0; s.line_start = True
        return bytes(out)

    def verbatim(s, text, prefix='', max_lines=None):
        """Program output: no wrapping at words, hard breaks at the edge."""
        out = bytearray()
        if not s.line_start: out += s.finish()
        lines = fold(text).split('\n')
        if lines and lines[-1] == '': lines.pop()
        shown = lines if max_lines is None else lines[:max_lines]
        pre = fold(prefix)
        for line in shown:
            while True:
                room = s.width - len(pre)
                out += to_bytes(pre + line[:room]) + NL
                line = line[room:]
                if not line: break
        if max_lines is not None and len(lines) > max_lines:
            out += to_bytes(pre + chr(glp.GL_ELLIPSIS) + ' +%d lines' % (len(lines) - max_lines)) + NL
        s.col = 0; s.line_start = True
        return bytes(out)
