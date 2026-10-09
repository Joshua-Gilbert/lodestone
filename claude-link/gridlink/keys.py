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


# ---- Term: GRiD key words -> what an xterm sends ------------------------
# KEYS carries the AX words INT 16h AH=10h returns (AL, AH).  CODE is Alt
# (Meta): CODE-letter is ESC + letter, CODE-Return ESC CR (a new line in
# Claude Code's prompt, as Ctrl-Return is).
LETTER_OF = {sc: ch for ch, sc in SCAN.items()}
CSI_KEYS = {0x47: 'H', 0x4F: 'F', 0x48: 'A', 0x50: 'B', 0x4D: 'C', 0x4B: 'D'}
TILDE_KEYS = {0x49: 5, 0x51: 6, 0x52: 2, 0x53: 3, 0x3F: 15, 0x40: 17, 0x41: 18, 0x42: 19,
              0x43: 20, 0x44: 21, 0x85: 23, 0x86: 24}
SS3_F = {0x3B: 'P', 0x3C: 'Q', 0x3D: 'R', 0x3E: 'S'}
CTRL_KEYS = {0x73: 'D', 0x74: 'C', 0x8D: 'A', 0x91: 'B', 0x77: 'H', 0x75: 'F'}   # Ctrl-arrows, -Home, -End


def term_bytes(al, ah, app_cursor=False):
    """One BIOS key -> the bytes for the pty."""
    if al in (0, 0xE0) and ah:
        if ah in CSI_KEYS:
            return ('\x1bO' if app_cursor else '\x1b[').encode() + CSI_KEYS[ah].encode()
        if ah in TILDE_KEYS: return b'\x1b[%d~' % TILDE_KEYS[ah]
        if ah in SS3_F: return b'\x1bO' + SS3_F[ah].encode()
        if ah in CTRL_KEYS: return b'\x1b[1;5' + CTRL_KEYS[ah].encode()
        if ah == 0x0F: return b'\x1b[Z'                        # Shift-Tab
        if ah == 0x1C: return b'\x1b\r'                        # CODE-Return
        if ah == 0x0E: return b'\x1b\x7f'                      # CODE-Backspace
        if ah == 0x01: return b'\x1b\x1b'                      # CODE-Esc
        if 0x78 <= ah <= 0x81: return b'\x1b' + b'1234567890'[ah - 0x78:ah - 0x77]
        if ah in LETTER_OF: return b'\x1b' + LETTER_OF[ah].encode()   # CODE-letter, CODE-punctuation
        return b''
    if al == 0x0D: return b'\r'
    if al == 0x0A: return b'\x1b\r'                            # Ctrl-Return
    if al == 0x08: return b'\x7f' if ah == 0x0E else b'\x08'   # Backspace (DEL), Ctrl-H
    if al == 0x7F: return b'\x08'                              # Ctrl-Backspace
    if al < 0x80: return bytes([al])
    return bytes([al]).decode('cp437').encode('utf-8')        # Alt-keypad characters


def term_keys(body, app_cursor=False):
    out = bytearray()
    for i in range(0, len(body) - 1, 2):
        out += term_bytes(body[i], body[i + 1], app_cursor)
    return bytes(out)
