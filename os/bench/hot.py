"""How often each kernel address is entered by a taken jump, call, return or
interrupt (not by falling through), over workloads in pcemu.  On the 286 a
taken transfer to an odd address costs a fetch: plan.py places the pads.
    python3 bench/hot.py OUT.json WORKLOAD...      (from os/, after build.sh)
WORKLOAD: bench   BENCH.COM's ten tests (the real-drive timing model; minutes)
          shell   LCMD: DIR, TYPE (3 x 18 KB), COPY 60 KB and 18 KB, DEL
          exec    the Executive idling and moving, MEMSZ.COM, TESTDOS.COM
          claude  one CLAUDE.COM turn over the Pico link model
OUT.json: {"taken": {offset: count}, "falls": {offset: count}}, kernel .text
offsets (KSEG:offset) as in src/LODE.MAP; all the workloads named add up.
Save src/LODE.MAP with it: the offsets are that build's."""
import sys, os, re, json, collections
GOS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in (GOS, os.path.join(GOS, 'tests'), os.path.join(GOS, 'bench')): sys.path.insert(0, d)
import pcemu, ktest, mkimg
lastdrv = next(int(m.group(1), 16) for m in (re.match(r'\s+([0-9A-F]+)\s+[0-9A-F]+\s+lastdrv\s*$', l)
               for l in open(os.path.join(GOS, 'src', 'LODE.MAP'), encoding='latin-1')) if m)
LO, HI = 0x600, 0x600 + lastdrv + 1             # the resident .text, linear
taken, falls = collections.Counter(), collections.Counter()
prev = [0, 0]
ob = pcemu.PC.blk
def blk(s, uc, addr, size, ud):
    pa, ps = prev
    if LO <= addr < HI and addr != pa:          # (a REP restarts its own block)
        (falls if addr == pa + ps else taken)[addr - 0x600] += 1
    prev[0], prev[1] = addr, size
    return ob(s, uc, addr, size, ud)
pcemu.PC.blk = blk
TMP = os.environ.get('TMPDIR', '/tmp')

def w_bench():
    import run_bench
    run_bench.run_lodestone()

def w_shell():
    txt = os.path.join(TMP, 'hot_txt.txt')
    open(txt, 'w').write(''.join('Line %d of a text file to TYPE and COPY, as a user would.\r\n' % i for i in range(300)))
    big = os.path.join(TMP, 'hot_big.bin'); open(big, 'wb').write(os.urandom(60000))
    files = [os.path.join(GOS, 'src', 'LCMD.COM'), 'TEXT.TXT=' + txt, 'BIG.BIN=' + big] + \
            ['F%02d.TXT=%s' % (i, txt) for i in range(20)]
    k = ktest.KPC(mkimg.build(os.path.join(TMP, 'hot_shell.img'), [os.path.join(GOS, 'src', 'LODE.SYS')] + files))
    k.start(); k.code_p()
    for cmd in ('dir', 'dir *.txt', 'type text.txt', 'copy big.bin big2.bin', 'copy text.txt t2.txt',
                'type t2.txt', 'dir /w', 'del big2.bin', 'del t2.txt', 'type text.txt'):
        k.key('cls'); k.key(ktest.ENTER)
        k.key(cmd); k.key(ktest.ENTER, settle=False); k.settle(60)

def w_exec():
    k = ktest.KPC(mkimg.build(os.path.join(TMP, 'hot_exec.img'), [os.path.join(GOS, 'src', 'LODE.SYS'),
                  os.path.join(GOS, 'src', 'LCMD.COM')] + [os.path.join(GOS, 'tests', n) for n in ('TESTDOS.COM', 'MEMSZ.COM', 'UPPER.COM')]))
    k.start()
    for i in range(6): k.key(ktest.DOWN)
    k.run_for(5)
    k.run_file('MEMSZ.COM', 30)
    k.run_file('TESTDOS.COM', 120)

def w_claude():
    import test_claude_kernel as TC
    T = TC.T
    h = T.start([T.reply(('text', 'A reply over the link, long enough to fill a few frames. ' * 30))], bridge='pico')
    assert h.turn('hello', sim_s=60)

if __name__ == '__main__':
    if len(sys.argv) < 3: sys.exit(__doc__)
    for w in sys.argv[2:]:
        print('== workload', w); globals()['w_' + w]()
    json.dump({'taken': taken, 'falls': falls}, open(sys.argv[1], 'w'))
    t = sum(taken.values())
    print('%d taken entries, %.1f%% at odd addresses' % (t, 100.0 * sum(v for a, v in taken.items() if a & 1) / max(t, 1)))
