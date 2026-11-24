"""BENCH.COM's figures for long runs, in the emulator: one real run under
Lodestone with the BIOS clock (INT 1Ah) at BENCH's own timing points (BX =
BExxh) handing out chosen tick counts, so the seconds it prints for a test
of 11,931 ticks (655 s, past a 16-bit quotient) and 65,535 ticks, and for a
total of 200,000 ticks (past a 16-bit word), are checked without hours of
simulated time.

    python3 tests/test_bench.py
"""
import os, re, struct, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, pcemu

OUT = tempfile.mkdtemp()
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

TICKS = [11931, 65535, 65535, 56999]            # tests 1-4; the other six 0: 200,000 in all
T0 = 0x0001FFF0                                 # (each test's start: its end crosses into the clock's high word)
_o1a = pcemu.PC.int1a
def _i1a(s):
    bx = s.r('bx')
    if s.r('ah') == 0 and bx & 0xFF00 == 0xBE00 and 1 <= (bx & 0xFF) >> 1 <= 10:
        n = bx & 0xFF                           # (BE02h/BE03h: the first test's start and end, ...)
        i = (n >> 1) - 1
        t = T0 + (TICKS[i] if n & 1 and i < len(TICKS) else 0)
        s.marks.append((n, s.us, len(s.calls13), sum(c[5] for c in s.calls13)))
        s.w('cx', t >> 16); s.w('dx', t & 0xFFFF); s.w('ax', 0)
        return
    return _o1a(s)
pcemu.PC.int1a = _i1a

def secs(t):
    h = t * 5493 // 1000
    return '%3d.%02d s' % (h // 100, h % 100)

def t_long():
    img = mkimg.build(os.path.join(OUT, 'b.img'), [os.path.join(GOS, 'src', f) for f in ('LODE.SYS', 'LCMD.COM')]
                      + [os.path.join(GOS, 'bench', 'BENCH.COM')])
    k = ktest.KPC(img); k.start()
    k.select('BENCH.COM'); k.pc.tty.clear()
    k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() != 0x40, 5)
    t0 = k.pc.us                                # (until the Executive is back, or BENCH is stopped)
    ktest.run_answering(k.pc, lambda: k.pc.mode() == 0x40 or 'overflow' in ''.join(k.pc.tty), 30)
    o = ''.join(k.pc.tty).replace('\r', '')
    print('   (BENCH ran %.0f s of simulated time)' % ((k.pc.us - t0) / 1e6))
    lines = o.split('\n')
    def line(name):
        return next((l for l in lines if l.startswith(name)), '')
    for name, t in (('Write 256 KB', 11931), ('Read 256 KB, 16 KB', 65535), ('Read 256 KB, 128', 56999)):
        l = line(name)
        check('a test of %d ticks: "%s"' % (t, secs(t).strip()), l[36:].startswith(secs(t)), (l, o[-800:]))
    l = line('Total')
    check('the total of %d ticks: "%s"' % (sum(TICKS), secs(sum(TICKS)).strip()),
          l == 'Total                               ' + secs(sum(TICKS)), (l, o[-800:]))
    check('... and BENCH ran to its end (BENCH.TXT written)', 'Results added to BENCH.TXT' in o, o[-800:])

if __name__ == '__main__':
    t0 = time.time()
    names = sys.argv[1:]
    for t in (t_long,):
        if not names or t.__name__[2:] in names: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
