"""Key scripts for programs run on the GRiD.

Claude writes them as text with {TOKENS}; the GRiD gets two bytes per key
(ASCII, scan code: the AX word INT 16h returns) and two escapes:
FFh FFh n = wait n BIOS ticks (55 ms), FFh FEh 00h = take a screen snapshot.
"""
import re

SCAN = {}
for row, codes in (('1234567890-=', range(0x02, 0x0E)), ('qwertyuiop[]', range(0x10, 0x1C)),
                   ("asdfghjkl;'`", range(0x1E, 0x2A)), ('\\zxcvbnm,./', range(0x2B, 0x36))):
    for ch, sc in zip(row, codes): SCAN[ch] = sc
SHIFTED = dict(zip('!@#$%^&*()_+{}:"~|<>?', '1234567890-=[];\'`\\,./'))
NAMED = {
    'ENTER': (0x0D, 0x1C), 'RETURN': (0x0D, 0x1C), 'ESC': (0x1B, 0x01), 'TAB': (0x09, 0x0F),
    'BKSP': (0x08, 0x0E), 'BACKSPACE': (0x08, 0x0E), 'SPACE': (0x20, 0x39),
    'UP': (0, 0x48), 'DOWN': (0, 0x50), 'LEFT': (0, 0x4B), 'RIGHT': (0, 0x4D),
    'HOME': (0, 0x47), 'END': (0, 0x4F), 'PGUP': (0, 0x49), 'PGDN': (0, 0x51),
    'INS': (0, 0x52), 'DEL': (0, 0x53),
}
for i in range(10):
    NAMED['F%d' % (i + 1)] = (0, 0x3B + i)
    NAMED['SHIFT+F%d' % (i + 1)] = (0, 0x54 + i)
    NAMED['CTRL+F%d' % (i + 1)] = (0, 0x5E + i)
    NAMED['ALT+F%d' % (i + 1)] = (0, 0x68 + i)

TICK = 0.0549254


class KeyError_(ValueError):
    pass


def char_key(ch):
    if ch == ' ': return 0x20, 0x39
    if ch == '\n': return 0x0D, 0x1C
    if ch == '\t': return 0x09, 0x0F
    lo = ch.lower()
    if lo in SCAN: return ord(ch), SCAN[lo]
    if ch in SHIFTED: return ord(ch), SCAN[SHIFTED[ch]]
    raise KeyError_('no key for %r' % ch)


def token_key(tok):
    t = tok.upper().replace(' ', '')
    if t in NAMED: return NAMED[t]
    m = re.fullmatch(r'(CTRL|ALT)\+(.)', t)
    if m:
        ch = m.group(2).lower()
        if ch not in SCAN: raise KeyError_('no key for {%s}' % tok)
        if m.group(1) == 'CTRL':
            if not ch.isalpha(): raise KeyError_('no key for {%s}' % tok)
            return ord(ch) & 0x1F, SCAN[ch]
        if ch.isdigit():                       # Alt-1..Alt-0 have their own codes
            return 0, 0x78 + ('1234567890'.index(ch))
        return 0, SCAN[ch]
    raise KeyError_('unknown key {%s}' % tok)


def compile_script(text):
    """'1{ENTER}{WAIT 2}{SNAP}{ESC}' -> bytes for the RUN request."""
    out = bytearray()
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '{':
            if text.startswith('{{', i):
                a, sc = char_key('{'); out += bytes([a, sc]); i += 2; continue
            j = text.find('}', i)
            if j < 0: raise KeyError_('missing } in key script')
            tok = text[i + 1:j].strip(); i = j + 1
            up = tok.upper()
            if up.startswith('WAIT'):
                secs = float(tok[4:].strip() or '1')
                ticks = max(1, int(round(secs / TICK)))
                while ticks > 0:
                    n = min(ticks, 255); out += bytes([0xFF, 0xFF, n]); ticks -= n
            elif up in ('SNAP', 'SCREENSHOT'):
                out += bytes([0xFF, 0xFE, 0])
            else:
                a, sc = token_key(tok); out += bytes([a, sc])
        else:
            a, sc = char_key(ch); out += bytes([a, sc]); i += 1
    return bytes(out)


def describe(text, limit=40):
    t = text.replace('\n', '{ENTER}')
    return t if len(t) <= limit else t[:limit - 1] + '\u2026'
