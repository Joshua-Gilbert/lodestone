"""Where the kernel's CPU time goes during one BENCH test (Lodestone only).
    python3 bench/prof.py N
Counts emulated basic blocks by kernel routine between the test's marks."""
import sys, os, re, bisect, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pcemu, run_bench
GOS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
syms = []
for l in open(os.path.join(GOS, 'src', 'LODE.MAP')):
    m = re.match(r'\s+([0-9A-F]+)\s+([0-9A-F]+)\s+(\S+)$', l)
    if m and '.' not in m.group(3): syms.append((int(m.group(1), 16), m.group(3)))
syms.sort(); addrs = [a for a, _ in syms]
N = int(sys.argv[1])
cnt = collections.Counter(); on = [False]
orig_blk = pcemu.PC.blk
def blk(s, uc, addr, size, ud):
    if on[0]:
        off = addr - 0x600
        if 0 <= off < 0x10000:
            i = bisect.bisect_right(addrs, off) - 1
            cnt[syms[i][1] if i >= 0 else '?'] += 1
        else: cnt['(program/BIOS %05X)' % (addr & 0xF0000)] += 1
    return orig_blk(s, uc, addr, size, ud)
pcemu.PC.blk = blk
orig_1a = pcemu.PC.int1a
def i1a(s):
    bx = s.r('bx')
    if bx & 0xFF00 == 0xBE00:
        if (bx & 0xFF) == 2 * N: on[0] = True
        if (bx & 0xFF) == 2 * N + 1: on[0] = False
    return orig_1a(s)
pcemu.PC.int1a = i1a
run_bench.run_lodestone()
tot = sum(cnt.values())
print('%d blocks (%.1f ms at 4 us)' % (tot, tot * 0.004))
for k, v in cnt.most_common(25): print('%7d  %5.1f%%  %s' % (v, 100.0 * v / tot, k))
