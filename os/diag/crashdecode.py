"""Read a CRASHLOG report (CRASH.BIN, from CRASHRPT.COM after the CRASHLOG
build caught a crash; os/diag/README.md) with that build's LODE.MAP, and
print it: MT's state, the tasks, the flight recorder's ring (oldest
first, each address named), vectors that point somewhere odd, and the
stacks with the words in them that look like return addresses.

    python3 os/diag/crashdecode.py CRASH.BIN [os/diag/LODE.MAP]
"""
import bisect, os, re, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))

class Map:
    def __init__(s, path):
        s.sec, s.equs, s.by_name = {}, {}, {}
        sec = None
        for line in open(path):
            if line.startswith('---- Section'): sec = line.split()[2]; continue
            if sec is None:
                m = re.match(r"([0-9A-F]{8})\s+(\S+)\s*$", line)
                if m: s.equs.setdefault(m.group(2), int(m.group(1), 16))
                continue
            m = re.match(r"\s*([0-9A-F]+)\s+([0-9A-F]+)\s+(\S+)\s*$", line)
            if m:
                d = s.sec.setdefault(sec, {})
                a, n = int(m.group(2), 16), m.group(3)
                if '.' not in n or a not in d: d.setdefault(a, n)
                s.by_name[n] = a
        s.keys = {k: sorted(v) for k, v in s.sec.items()}
    def name(s, secs, off):
        best = None
        for k in secs:
            ks = s.keys.get(k, [])
            i = bisect.bisect_right(ks, off) - 1
            if i >= 0 and (best is None or ks[i] > best[0]): best = (ks[i], s.sec[k][ks[i]])
        if best is None: return None
        return best[1] if best[0] == off else '%s+%x' % (best[1], off - best[0])

TAGS = {'T': 'tick', 'S': 'switch (BL: to)', 'V': 'mode set (AX)', 'X': 'INT 06h', 'E': 'mw_end', 'U': 'mw_raise',
        'D': 'mw_drop', 'W': 'mw_unwin', 'O': 'mw_start', 'C': 'mw_shut', 'Z': 'mw_size', 'z': 'mw_size drop',
        'R': 'mw_rdfn (redraw)', 'F': 'mw_front'}
VARS = ('cur', 'front', 'down', 'ddev', 'swing', 'inb', 'crit', 'in13', 'vbusy', 'shd', 'mw_n', 'pend', 'slice',
        'want', 'hirq', 'htk')

def main(rep_path, map_path):
    b = open(rep_path, 'rb').read()
    M = Map(map_path); E = M.equs
    if b[:8] != b'LODECRSH': sys.exit('not a CRASHLOG report')
    ln, sm, cause, mtseg = struct.unpack_from('<HHBxH', b, 8)
    ok = sum(struct.unpack_from('<%dH' % ((ln - 16) // 2), b, 16)) & 0xFFFF == sm
    ticks, crp, useg = struct.unpack_from('<3H', b, 32)
    xr = struct.unpack_from('<14H', b, 38)
    N, MT_TASKS, MT_ENT = E['CR_N'], E['MT_TASKS'], E['MT_ENT']
    o_tab, o_ring, o_ivt, o_bda = E['CRO_TAB'], E['CRO_RING'], E['CRO_IVT'], E['CRO_BDA']
    o_k, o_l, o_t = E['CRO_KSTK'], E['CRO_LSTK'], E['CRO_TSTK']
    def where(cs, ip):
        if cs == 0x60: n = M.name(['.text'], ip)
        elif cs == mtseg: n = M.name(['mtt'], ip)
        elif cs == useg: n = M.name(['ui', 'uiboot'], ip)
        elif cs == 0xF000: n = 'BIOS'
        else: n = None
        return '%04X:%04X %s' % (cs, ip, n or '(a program, or nowhere)')
    print('CRASHLOG report: %d bytes, sum %s; caught by %s; MT at %04X, UI at %04X; tick %d'
          % (ln, 'ok' if ok else 'WRONG', {'R': 'a restart', 'X': 'INT 06h (an invalid opcode)', 'K': 'a disk wait\'s owner\'s stack changed'}.get(chr(cause), chr(cause)),
             mtseg, useg, ticks))
    print('MT: ' + '  '.join('%s %02X' % (n, b[16 + i]) for i, n in enumerate(VARS)))
    if chr(cause) == 'X':
        n = ('IP', 'CS', 'FL', 'SP', 'SS', 'AX', 'BX', 'CX', 'DX', 'SI', 'DI', 'BP', 'DS', 'ES')
        print('INT 06h at ' + where(xr[1], xr[0]) + '; ' + ' '.join('%s=%04X' % p for p in zip(n[2:], xr[2:])))
    print('\nTasks (state, PSP, TX, name):')
    for t in range(MT_TASKS):
        e = b[o_tab + t * MT_ENT:o_tab + (t + 1) * MT_ENT]
        st = e[E['TE_STATE']]
        if not st: continue
        psp, tx = struct.unpack_from('<H', e, E['TE_PSP'])[0], struct.unpack_from('<H', e, E['TE_TX'])[0]
        nm = e[E['TE_NAME']:E['TE_NAME'] + 12].split(b'\0')[0].decode('latin-1')
        sp, ss = struct.unpack_from('<HH', b, o_t + t * 260)
        print('  %d  state %d  PSP %04X  TX %04X  %-12s  last SS:SP %04X:%04X' % (t, st, psp, tx, nm, ss, sp))
    print('\nThe ring, oldest first (tick, tag, task, where, SS:SP, AX, BX/flags):')
    for i in range(N):
        off = (crp + i * 16) % (N * 16)
        tk, tag, task, ip, cs, sp, ss, ax, bx = struct.unpack_from('<HBB6H', b, o_ring + off)
        if tag == 0: continue
        w = where(cs, ip)
        if chr(tag) != 'T' and cs not in (0x60, mtseg, useg, 0xF000):      # (a near return: MT's)
            w = 'near %04X %s' % (ip, M.name(['mtt'], ip))
        print('  %5d %s %-15s %d  %-44s %04X:%04X  %04X %04X' % (tk, chr(tag), TAGS.get(chr(tag), '?'), task,
                                                                 w, ss, sp, ax, bx))
    print('\nVectors that point outside the BIOS, the kernel, MT and the UI:')
    for v in range(256):
        off, seg = struct.unpack_from('<HH', b, o_ivt + v * 4)
        if seg in (0xF000, 0x60, mtseg, useg) or (off, seg) == (0, 0) and 0x60 <= v <= 0x67: continue
        print('  INT %02Xh -> %04X:%04X' % (v, seg, off))
    def stack(title, base_ss, base_sp, data):
        print('\n%s (%04X:%04X onwards, %d bytes; words that look like return addresses named):'
              % (title, base_ss, base_sp, len(data)))
        for j in range(0, len(data) - 1, 2):
            w = struct.unpack_from('<H', data, j)[0]
            hits = [n for n in (M.name(['mtt'], w), M.name(['.text'], w), M.name(['ui'], w)) if n and '+' in n
                    and int(n.split('+')[1], 16) < 0x40]
            if hits: print('  %04X: %04X  %s' % ((base_sp + j) & 0xFFFF, w, ' / '.join(hits)))
    if chr(cause) == 'K':
        kept, now = b[o_l:o_l + 256], b[o_l + 256:o_l + 512]
        print('\nA disk wait\'s owner\'s stack CHANGED while it was out (kept at its going out, then as found on '
              'its return; from its SP up):')
        for j in range(0, 256, 2):
            a_, c_ = struct.unpack_from('<H', kept, j)[0], struct.unpack_from('<H', now, j)[0]
            if a_ != c_:
                print('  +%03X: %04X -> %04X  (%s / %s)' % (j, a_, c_, M.name(['mtt'], a_) or '', M.name(['mtt'], c_) or ''))
    lt = (crp - 16) % (N * 16)
    _, _, _, _, _, lsp, lss, _, _ = struct.unpack_from('<HBB6H', b, o_ring + lt)
    stack('The newest record\'s stack', lss, (lsp - 384) & 0xFFFF, b[o_l:o_l + 512])
    stack('The kernel\'s stack', 0x60, M.by_name['kstack_top'] - 1536, b[o_k:o_k + 1536])
    for t in range(MT_TASKS):
        sp, ss = struct.unpack_from('<HH', b, o_t + t * 260)
        if sp or ss: stack('Task %d\'s stack' % t, ss, (sp - 128) & 0xFFFF, b[o_t + t * 260 + 4:o_t + t * 260 + 260])

if __name__ == '__main__':
    if len(sys.argv) < 2: sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, 'LODE.MAP'))
