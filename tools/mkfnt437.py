#!/usr/bin/env python3
"""mkfnt437.py - os/fonts/TERM437.INC, the terminal window's font (TERM.FNT):
all 256 codes of code page 437, 8x16, 16 bytes each, top row first (4,096
bytes), from Terminus Bold 16 as console-setup ships it with its Unicode table:

    python3 tools/mkfnt437.py [/usr/share/consolefonts/Uni2-TerminusBold16.psf.gz]

Codes 32-126 must be TERMINUS.INC's byte for byte (the font Lodestone already
has; the tests read windows with it).  The few code page 437 pictures Terminus
lacks are drawn here: the half blocks and the dark shade from what they are, the
control codes' pictures (hearts, notes, arrows) as simple shapes.
"""
import gzip, os, re, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OS = os.path.join(HERE, '..', 'os')
PSF = sys.argv[1] if len(sys.argv) > 1 else '/usr/share/consolefonts/Uni2-TerminusBold16.psf.gz'

# code page 437's pictures for 00h-1Fh and 7Fh (Python's cp437 has the control codes there)
CTL = ('\u0000☺☻♥♦♣♠•◘○◙♂♀♪♫☼'
       '►◄↕‼¶§▬↨↑↓→←∟↔▲▼')
UNI = [ord(c) for c in CTL] + [ord(c) for c in bytes(range(32, 127)).decode('cp437')] + [0x2302] \
    + [ord(c) for c in bytes(range(128, 256)).decode('cp437')]

# drawn here: what Terminus Bold 16 has not
DRAWN = {
    0x00: [0] * 16,
    0x03: [0, 0, 0, 0, 0x6C, 0xFE, 0xFE, 0xFE, 0xFE, 0x7C, 0x38, 0x10, 0, 0, 0, 0],                  # heart
    0x05: [0, 0, 0, 0x18, 0x3C, 0x3C, 0xE7, 0xE7, 0xE7, 0x18, 0x18, 0x3C, 0, 0, 0, 0],               # club
    0x06: [0, 0, 0, 0x18, 0x3C, 0x7E, 0xFF, 0xFF, 0x7E, 0x18, 0x18, 0x3C, 0, 0, 0, 0],               # spade
    0x08: [0xFF] * 6 + [0xE7, 0xC3, 0xC3, 0xE7] + [0xFF] * 6,                                         # inverse bullet
    0x09: [0, 0, 0, 0, 0, 0x3C, 0x66, 0x42, 0x42, 0x66, 0x3C, 0, 0, 0, 0, 0],                        # circle
    0x0A: [0xFF] * 5 + [0xC3, 0x99, 0xBD, 0xBD, 0x99, 0xC3] + [0xFF] * 5,                             # inverse circle
    0x0B: [0, 0, 0x1E, 0x0E, 0x1A, 0x32, 0x78, 0xCC, 0xCC, 0xCC, 0xCC, 0x78, 0, 0, 0, 0],            # male
    0x0C: [0, 0, 0x3C, 0x66, 0x66, 0x66, 0x66, 0x3C, 0x18, 0x7E, 0x18, 0x18, 0, 0, 0, 0],            # female
    0x0D: [0, 0, 0x3F, 0x33, 0x3F, 0x30, 0x30, 0x30, 0x30, 0x70, 0xF0, 0xE0, 0, 0, 0, 0],            # note
    0x0E: [0, 0, 0x7F, 0x63, 0x7F, 0x63, 0x63, 0x63, 0x63, 0x67, 0xE7, 0xE6, 0xC0, 0, 0, 0],         # notes
    0x10: [0, 0x80, 0xC0, 0xE0, 0xF0, 0xF8, 0xFE, 0xF8, 0xF0, 0xE0, 0xC0, 0x80, 0, 0, 0, 0],         # right
    0x11: [0, 0x02, 0x06, 0x0E, 0x1E, 0x3E, 0xFE, 0x3E, 0x1E, 0x0E, 0x06, 0x02, 0, 0, 0, 0],         # left
    0x16: [0] * 8 + [0xFE] * 4 + [0] * 4,                                                            # bar
    0xDC: [0] * 8 + [0xFF] * 8,                                                                      # lower half
    0xDD: [0xF0] * 16,                                                                               # left half
    0xDE: [0x0F] * 16,                                                                               # right half
    0xDF: [0xFF] * 8 + [0] * 8,                                                                      # upper half
}

def psf(path):
    d = gzip.open(path).read()
    if d[:2] != b'\x36\x04':
        sys.exit('%s: not a PSF1 font' % path)
    mode, h = d[2], d[3]
    n = 512 if mode & 1 else 256
    if h != 16 or not mode & 2:
        sys.exit('%s: wanted 8x16 with a Unicode table' % path)
    glyphs = [d[4 + i * h:4 + (i + 1) * h] for i in range(n)]
    tab, at, g = d[4 + n * h:], {}, 0
    for i in range(0, len(tab) - 1, 2):
        v = struct.unpack_from('<H', tab, i)[0]
        if v == 0xFFFF:
            g += 1
        elif v != 0xFFFE and g < n:
            at.setdefault(v, g)
    return glyphs, at

def terminus():
    t = open(os.path.join(OS, 'src', 'TERMINUS.INC')).read()
    rows = re.findall(r'^\s*db (.*?);', t, re.M)
    return [bytes(int(x.strip()[:-1], 16) for x in r.split(',')) for r in rows]

def main():
    glyphs, at = psf(PSF)
    out, drawn = [], []
    for c, u in enumerate(UNI):
        if c == 0xB2:
            out.append(None); continue          # (below: from the light shade)
        if c in DRAWN:
            out.append(bytes(DRAWN[c])); drawn.append(c)
        elif u in at:
            out.append(glyphs[at[u]])
        else:
            sys.exit('code %02Xh (U+%04X): not in %s and not drawn here' % (c, u, PSF))
    out[0xB2] = bytes(b ^ 0xFF for b in out[0xB0])          # dark shade: the light one inverted
    drawn.append(0xB2)
    t = terminus()
    bad = [c for c in range(32, 127) if out[c] != t[c - 32]]
    if bad:
        sys.exit('codes %s differ from TERMINUS.INC' % ' '.join('%02Xh' % c for c in bad))
    lines = ['; 8x16 font, all 256 codes of code page 437 (TERM.FNT: the terminal window),',
             '; from Terminus Bold 16 (console-setup\'s Uni2-TerminusBold16.psf.gz) by',
             '; tools/mkfnt437.py; 32-126 as TERMINUS.INC; drawn by the tool, not Terminus:',
             '; ' + ' '.join('%02Xh' % c for c in sorted(drawn)),
             '; Terminus Font (c) 2020 Dimitar Toshkov Zhekov, SIL Open Font License 1.1',
             'term437:']
    for c, g in enumerate(out):
        ch = bytes([c]).decode('cp437') if c >= 32 else CTL[c]
        name = 'U+%04X' % UNI[c] if c < 32 or c >= 127 else repr(ch)
        lines.append('        db ' + ','.join('%03Xh' % b for b in g) + '   ; %02Xh %s' % (c, name))
    p = os.path.join(OS, 'fonts', 'TERM437.INC')
    open(p, 'w', newline='\r\n').write('\n'.join(lines) + '\n')
    print('%s: 256 glyphs, %d drawn here (%s)' % (p, len(drawn), ' '.join('%02Xh' % c for c in sorted(drawn))))

main()
