"""Kernel routines run in each gap between BIOS disk calls of one BENCH test.
    python3 bench/gapprof.py N [min_ms]"""
import sys, os, re, bisect, collections
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H); sys.path.insert(0, os.path.dirname(H))
import pcemu, run_bench
syms = []
for l in open(os.path.join(os.path.dirname(H), 'src', 'GRIDOS.MAP')):
    m = re.match(r'\s+([0-9A-F]+)\s+([0-9A-F]+)\s+(\S+)$', l)
    if m: syms.append((int(m.group(1), 16), m.group(3)))
syms.sort(); addrs = [a for a, _ in syms]
N = int(sys.argv[1]); MIN = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
on = [False]; cur = collections.Counter(); us0 = [0]; shown = [0]
ob = pcemu.PC.blk
def blk(s, uc, addr, size, ud):
    if on[0]:
        off = addr - 0x600
        if 0 <= off < 0xBA00:
            i = bisect.bisect_right(addrs, off) - 1
            nm = syms[i][1]
            cur[nm.split('.')[0] if not nm.startswith('.') else nm] += 1
        else: cur['(other)'] += 1
    return ob(s, uc, addr, size, ud)
pcemu.PC.blk = blk
oi = pcemu.PC.int13
def i13(s):
    if on[0] and s.r('ah') in (2, 3):
        gap = (s.us - us0[0]) / 1000
        if gap >= MIN and shown[0] < 6:
            shown[0] += 1
            print('gap %.2f ms, %d blocks: %s' % (gap, sum(cur.values()), ', '.join('%s %d' % kv for kv in cur.most_common(14))))
        cur.clear()
    r = oi(s); us0[0] = s.us; return r
pcemu.PC.int13 = i13
o1 = pcemu.PC.int1a
def i1a(s):
    bx = s.r('bx')
    if bx & 0xFF00 == 0xBE00:
        if (bx & 0xFF) == 2 * N: on[0] = True
        if (bx & 0xFF) == 2 * N + 1: on[0] = False
    return o1(s)
pcemu.PC.int1a = i1a
run_bench.run_gridos()
