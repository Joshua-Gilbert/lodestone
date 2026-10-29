"""Where to put the kernel's parity pads (LODE.ASM's EVEN list), from hot.py's
counts.  The resident .text splits into runs between points no path falls
through (after a JMP, RET or data); a pad byte at a run's head moves that run
and everything after it, up to the next self-correcting pad (KGPIB's fast
loops', `times ($ - $$) & 1`; one emitting 0 bytes now would emit 1 if what
comes before moved by one).  A DP finds, for each byte budget, the run
heads that put the fewest taken entries on odd addresses.
    python3 bench/plan.py B HOT.json...              (from os/, on the build
                                                       HOT.json was made on)
B: the most pad bytes (the slack: image_end - lastdrv - 1).  Each HOT.json
weighs the same (NORM=0: raw counts).  NOPAD=lo-hi,... (hex): no pads there
(the GPIB fast loops: gp_fast_write up to after gp_fast_read).  SHOW=n: the
plan for n bytes (default B).  SECTION=ui: the UI's pads instead (section ui,
hot.py's "ui_taken"; B the slack to the paragraph: uibss's start -
ui_image_end; NOPAD there: the jump table, and the code test_apps assembles
on its own, row_di's and xor_rect's).  SECTION=claude: CLAUDE.COM's
(claude/CLAUDE.LST and .MAP, hot.py's "cl_taken"; B the slack to bss's
paragraph); SECTION=rstub: the CLAUDE /R stub's ("st_taken"; B the slack to
R_PARAS's paragraph); SECTION=rcon: resident Claude's console's
(claude/RCON.LST, which claude/build.sh doesn't make: nasm -l; RCON.MAP;
"rc_taken"; no pad in its header, which CLAUDE.ASM reads).  There no pad goes
inside an included file's code (the ones RCON.ASM shares, and TERMLINK.INC),
only in front of its %include.  SC=1: self-correcting pads only, E or O (any
SECTION; sc_main): such a pad holds wherever its code is put, so it may go
inside TERMLINK.INC or OPS.INC, which sit at other offsets in CLAUDE.COM and
RCON; B is then the most pads.
Output: per budget the share of taken entries left odd and the run heads;
then, for the plan shown, its sites (pad each with `times ($ - $$) & 1 db
90h` before the label marked E, or `($ + 1 - $$)` for O), and the hot labels
(THR: the count) even and odd after it: the even ones go in the EVEN list."""
import os, re, sys, json, collections
GOS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(GOS, 'src')
SEC = os.environ.get('SECTION', '.text')
KEY = {'ui': 'ui_taken', 'claude': 'cl_taken', 'rstub': 'st_taken', 'rcon': 'rc_taken'}.get(SEC, 'taken')
CLAUDE = SEC in ('claude', 'rstub', 'rcon')
if CLAUDE: SRC = os.path.join(GOS, 'claude')
LSEC = '.text' if SEC in ('claude', 'rcon') else SEC    # (the section's name in the listing and the map)
ORG = 0x100 if SEC in ('claude', 'rstub') else 0        # (CLAUDE's listing counts from the section's start, 100h)
FILES = [os.path.join(SRC, n) for n in (('RCON.LST', 'RCON.MAP') if SEC == 'rcon' else ('CLAUDE.LST', 'CLAUDE.MAP')
                                        if CLAUDE else ('LODE.LST', 'LODE.MAP'))]
INC = set()                                     # (offsets of code from an included file)

def parse(lst, mp):
    """SEC from the listing: (offset, size, code/xfer/data, source); the map's SEC labels by offset"""
    sec, items = '.text', []
    for l in open(lst, encoding='latin-1'):
        m = re.match(r'^\s*\d+\s+(?:([0-9A-F]{8})\s+([0-9A-F\[\]\(\)]+)(-?)\s+)?(<\d+>\s?)?(.*)$', l.rstrip('\n'))
        if not m: continue
        addr, hexb, cont, inc, src = m.groups()
        if addr: addr = '%X' % (int(addr, 16) + ORG)
        code = src.split(';')[0].strip()
        ms = re.match(r'(?i)^\[?section\s+(\S+?)\]?(\s|$)', code)
        if ms: sec = ms.group(1); continue
        if re.match(r'(?i)^\[?absolute', code): sec = 'abs'; continue
        if sec != LSEC: continue
        if not addr:                            # a self-correcting pad of 0 bytes has no address
            if '$$) & 1 db 90h' in code and items:
                items.append((items[-1][0] + items[-1][1], 0, 'data', code))
            continue
        n = len(re.sub(r'[\[\]\(\)]', '', hexb)) // 2
        if not code:                            # (a long line's next bytes; its last has no '-')
            if items: items[-1] = items[-1][:1] + (items[-1][1] + n,) + items[-1][2:]
            continue
        op = re.sub(r'^[\w.$@?]+:\s*', '', code)
        ws = [x.lower() for x in op.split()]
        DATA = ('db', 'dw', 'dd', 'times', 'incbin')
        kind = 'data' if ws and (ws[0] in DATA or ws[1:2] and ws[1] in DATA) else \
               'xfer' if ws and ws[0] in ('jmp', 'ret', 'retf', 'iret') else 'code'
        items.append((int(addr, 16), n, kind, code))
        if inc: INC.add(int(addr, 16))
    syms, s = {}, None
    for l in open(mp, encoding='latin-1'):
        m = re.match(r'---- Section (\S+)', l)
        if m: s = m.group(1); continue
        m = re.match(r'\s+([0-9A-F]+)\s+([0-9A-F]+)\s+(\S+)\s*$', l)
        if m and s == LSEC: syms.setdefault(int(m.group(2), 16), []).append(m.group(3))
    return items, syms

def main():
    if len(sys.argv) < 3: sys.exit(__doc__)
    B = int(sys.argv[1])
    items, syms = parse(*FILES)
    tot = collections.Counter()
    for f in sys.argv[2:]:
        c = {int(k): v for k, v in json.load(open(f))[KEY].items()}
        if os.environ.get('NORM', '1') != '0':
            s = sum(c.values()); c = {k: v * 250000 // s for k, v in c.items()}
        tot.update(c)
    after = {a + n: (k, t) for a, n, k, t in items if n}
    SC = {a + n: n for a, n, k, t in items if k == 'data' and '$$) & 1 db 90h' in t}
    heads = sorted(set([0] + [a for a, (k, t) in after.items() if k in ('xfer', 'data')] + list(SC)))
    runs = []
    for i, s in enumerate(heads):
        e = heads[i + 1] if i + 1 < len(heads) else 1 << 20
        runs.append((s, sum(v for a, v in tot.items() if s <= a < e and not a & 1),
                        sum(v for a, v in tot.items() if s <= a < e and a & 1)))
    NOPAD = [tuple(int(x, 16) for x in r.split('-')) for r in os.environ.get('NOPAD', '').split(',') if r]
    if SEC == 'ui' and 'NOPAD' not in os.environ:   # (the jump table; test_apps' xor_rect_unit: row_di, xor_rect)
        at = {n: a for a, ns in syms.items() for n in ns}
        NOPAD = [(0, at['exec_main']), (at['row_di'], at['hires']), (at['xor_rect'], at['fm_value'])]
    if SEC == 'rcon': NOPAD.append((0, 8))      # (the header: CLAUDE.ASM reads nano, term, busy, feed_e there)
    total = sum(tot.values())
    data_at = {a for a, n, k, t in items if k == 'data' and n}     # (no pad in front of data)
    if CLAUDE:                                  # (nor inside an included file: in front of its %include only)
        before = {a + n: a for a, n, k, t in items if n}
        data_at |= {s for s in heads if s in INC and before.get(s) in INC}
    print('as built: %.2f%% of taken entries odd' % (100.0 * sum(r[2] for r in runs) / total))
    best = {(0, 0): (0, [])}                   # (flipped, bytes) -> (entries even, run heads padded)
    rank = lambda vp: (vp[0], -len(vp[1]))      # (a tie: fewer pads)
    for s, E, O in runs:
        if s in SC:                             # a self-correcting pad: parity as built again
            b2 = {}
            for (d, b), vp in best.items():
                key = (0, b + (d and (1 if SC[s] == 0 else -1)))
                if key not in b2 or rank(b2[key]) < rank(vp): b2[key] = vp
            best = b2
        nb = {}
        for (d, b), (val, path) in best.items():
            for nd in (0, 1):
                if nd != d and (s in SC or s in data_at or any(lo <= s < hi for lo, hi in NOPAD)): continue
                key = (nd, b + (nd != d))
                if key[1] > B: continue
                vp = (val + (O if nd else E), path + ([s] if nd != d else []))
                if key not in nb or rank(nb[key]) < rank(vp): nb[key] = vp
        best = nb
    name = lambda a: '/'.join(syms.get(a, ['?']))
    last = -1
    for b in range(min(k[1] for k in best), B + 1):
        c = [vp for (d, bb), vp in best.items() if bb == b]
        if c:
            v, p = max(c, key=rank)
            if v <= last: continue              # (a byte more that buys nothing)
            last = v
            print('%2d B: %.2f%% of taken entries odd   %s' % (b, 100.0 * (total - v) / total, ' '.join('%04X:%s' % (x, name(x)[:20]) for x in p)))
    NB = int(os.environ.get('SHOW', B))
    v, p = max((vp for (d, bb), vp in best.items() if bb == NB), key=rank)
    ev = sorted([(x, 'T') for x in p] + [(x, 'S') for x in SC])
    def shift(a):
        sh = 0
        for x, k in ev:
            if x > a: break
            if k == 'T': sh += 1
            elif sh & 1: sh += 1 if SC[x] == 0 else -1
        return sh
    print('\nplan for %d B (net %d):' % (NB, shift(1 << 20)))
    for x in p:
        print('  pad before %04X %-26s -> %s   (after: %s)' % (x, name(x)[:26], 'O' if (x + shift(x)) & 1 else 'E', after.get(x, ('', ''))[1][:40]))
    thr = int(os.environ.get('THR', 1500))
    lab = [(a, n) for a, n in sorted(tot.items()) if a in syms and n >= thr]
    print('\neven after (>= %d):' % thr, ' '.join(name(a) for a, n in lab if not (a + shift(a)) & 1))
    print('\nodd after (>= %d):' % thr, ' '.join('%s:%d' % (name(a), n) for a, n in lab if (a + shift(a)) & 1))

def sc_main():
    """SC=1: self-correcting pads only: TERMLINK.INC and OPS.INC sit at other
    offsets in CLAUDE.COM and RCON, and such a pad makes the label after it
    even (E) or odd (O) in both.  A new pad at a run head makes the parity
    from there on the listing's offset from it, or that plus one; B is the
    most new pads."""
    B = int(sys.argv[1])
    items, syms = parse(*FILES)
    tot = collections.Counter()
    for f in sys.argv[2:]:
        c = {int(k): v for k, v in json.load(open(f))[KEY].items()}
        if os.environ.get('NORM', '1') != '0':
            s = sum(c.values()); c = {k: v * 250000 // s for k, v in c.items()}
        tot.update(c)
    after = {a + n: (k, t) for a, n, k, t in items if n}
    SC = {a + n for a, n, k, t in items if k == 'data' and '$$) & 1 db 90h' in t}
    heads = sorted(set([ORG] + [a for a, (k, t) in after.items() if k in ('xfer', 'data')] + list(SC)))
    data_at = {a for a, n, k, t in items if k == 'data' and n}
    NOPAD = [tuple(int(x, 16) for x in r.split('-')) for r in os.environ.get('NOPAD', '').split(',') if r]
    if SEC == 'rcon': NOPAD.append((0, 8))      # (the header: CLAUDE.ASM reads nano, term, busy, feed_e there)
    total = sum(tot.values())
    runs = []
    for i, s in enumerate(heads):
        e = heads[i + 1] if i + 1 < len(heads) else 1 << 20
        runs.append((s, [(a, v) for a, v in tot.items() if s <= a < e]))
    print('as built: %.2f%% of taken entries odd' % (100.0 * sum(v for a, v in tot.items() if a & 1) / total))
    # d: the parity of the shift so far (an existing pad: 0 after it; a new E one at s: s & 1, O: the other)
    best = {(0, 0): (0, [])}
    rank = lambda vp: (vp[0], -len(vp[1]))
    for s, ent in runs:
        nb = {}
        for (d, b), (val, path) in best.items():
            opts = [(0 if s in SC else d, b, path)]
            if not (s in SC or s in data_at or any(lo <= s < hi for lo, hi in NOPAD)) and b < B:
                opts += [(s & 1, b + 1, path + [(s, 'E')]), (~s & 1, b + 1, path + [(s, 'O')])]
            for nd, nb_, np in opts:
                vp = (val + sum(v for a, v in ent if not (a + nd) & 1), np)
                if (nd, nb_) not in nb or rank(nb[(nd, nb_)]) < rank(vp): nb[(nd, nb_)] = vp
        best = nb
    name = lambda a: '/'.join(syms.get(a, ['?']))
    last = -1
    for b in range(B + 1):
        c = [vp for (d, bb), vp in best.items() if bb == b]
        if c:
            v, p = max(c, key=rank)
            if v <= last: continue
            last = v
            print('%2d pads: %.2f%% of taken entries odd   %s' % (b, 100.0 * (total - v) / total, ' '.join('%04X:%s:%s' % (x, name(x)[:20], k) for x, k in p)))
    NB = int(os.environ.get('SHOW', B))
    v, p = max((vp for (d, bb), vp in best.items() if bb <= NB), key=rank)
    kind = dict(p)
    def par(a):                                 # the parity a ends up with
        d = 0
        for s in sorted(set(kind) | SC):
            if s > a: break
            d = (s if kind.get(s) == 'E' else s + 1) & 1 if s in kind else 0
        return (a + d) & 1
    print('\nplan for %d pads:' % len(p))
    for x, k in p:
        print('  pad before %04X %-26s %s  (after: %s)' % (x, name(x)[:26], k, after.get(x, ('', ''))[1][:40]))
    thr = int(os.environ.get('THR', 1500))
    lab = [(a, n) for a, n in sorted(tot.items()) if a in syms and n >= thr]
    print('\neven after (>= %d):' % thr, ' '.join(name(a) for a, n in lab if not par(a)))
    print('\nodd after (>= %d):' % thr, ' '.join('%s:%d' % (name(a), n) for a, n in lab if par(a)))

if __name__ == '__main__':
    sc_main() if os.environ.get('SC') else main()
