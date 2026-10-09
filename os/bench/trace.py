"""Per-call disk trace of one BENCH test on both systems.

    python3 bench/trace.py N [max-lines]      (N = 1..10, the test number)

Each line: start time (ms from the test's start), CPU time since the previous
call ended, op, cylinder/head/sector, count, time in the call, and how much
of that was waiting for the sector to come round (rotation).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_bench

FD_REV = 200000.0


def window(pc, n):
    m = {b: us for b, us, _, _ in pc.marks}
    return m[2 * n], m[2 * n + 1]


def dump(pc, n, lim):
    a, b = window(pc, n)
    calls = [c for c in pc.t13 if a <= c[0] <= b]
    prev = a; cpu = 0; busy = 0
    for i, (t0, t1, ah, c, h, s, k) in enumerate(calls):
        gap = t0 - prev; cpu += gap; busy += t1 - t0
        if i < lim:
            print('  %9.1f  cpu %7.2f  %s c%2d h%d s%2d x%2d  %7.2f ms' % ((t0 - a) / 1e3, gap / 1e3, 'RD' if ah == 2 else 'WR' if ah == 3 else 'VF',
                                                                     c, h, s, k, (t1 - t0) / 1e3))
        prev = t1
    cpu += b - prev
    print('  calls %d, disk %.3f s, CPU between calls %.3f s, total %.3f s' % (len(calls), busy / 1e6, cpu / 1e6, (b - a) / 1e6))


if __name__ == '__main__':
    n = int(sys.argv[1]); lim = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    g, _ = run_bench.run_lodestone()
    d, _ = run_bench.run_msdos()
    print('== Lodestone: %s' % run_bench.NAMES[n - 1]); dump(g, n, lim)
    print('== MS-DOS: %s' % run_bench.NAMES[n - 1]); dump(d, n, lim)
