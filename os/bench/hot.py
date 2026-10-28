"""How often each kernel address is entered by a taken jump, call, return or
interrupt (not by falling through), over workloads in pcemu.  On the 286 a
taken transfer to an odd address costs a fetch: plan.py places the pads.
    python3 bench/hot.py OUT.json WORKLOAD...      (from os/, after build.sh)
WORKLOAD: bench   BENCH.COM's ten tests (the real-drive timing model; minutes)
          shell   LCMD: DIR, TYPE (3 x 18 KB), COPY 60 KB and 18 KB, DEL
          exec    the Executive idling and moving, MEMSZ.COM, TESTDOS.COM
          claude  one CLAUDE.COM turn over the Pico link model
   the UI's (UICORE, EXEC: section ui; mostly for "ui_taken"):
          idle    the Executive idling (the clock), then the saver running
          list    the Executive's file list: cursor moves and scrolling
          menu    Write's right-click menus, and help (F1) there and in the Executive
          form    the Executive's forms (Tab, typing, ESC) and System's clock form
          drag    the calculator's window dragged by the mouse and by CODE-F7
          write   Write: typing, scrolling a long file
          calc    the calculator: sums typed and clicked
          system  System's screens
          term    MULTITASK=1: LCMD in a terminal window (DIR, TYPE), the
                  calculator over it (KMW's clipping gates)
OUT.json: {"taken": {offset: count}, "falls": {offset: count}}, kernel .text
offsets (KSEG:offset) as in src/LODE.MAP, and "ui_taken", "ui_falls": section
ui's offsets (the UI segment, ui_seg, wherever it is: it is a block of its own,
on a paragraph, so an offset's parity is the address's; wait_ticks' polling,
which only waits, not counted); all the workloads named add up.  Save src/LODE.MAP with it: the offsets are that build's."""
import sys, os, re, json, struct, collections
GOS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in (GOS, os.path.join(GOS, 'tests'), os.path.join(GOS, 'bench')): sys.path.insert(0, d)
import pcemu, ktest, mkimg
SY = ktest.Syms()
LO, HI = 0x600, 0x600 + SY['lastdrv'] + 1       # the resident .text, linear
USEG, UEND = 0x600 + SY['ui_seg'], SY['ui_image_end']
SPIN0 = SY['wait_ticks']                        # (its polling loop and the tick calls in it: not counted)
SPIN1 = min(a for a in SY.ui_addrs if a > SPIN0 and '.' not in SY.ui_by_addr[a])
taken, falls = collections.Counter(), collections.Counter()
ui_taken, ui_falls = collections.Counter(), collections.Counter()
prev = [0, 0]
ui = [0, -1, -1, None]                          # (blocks to the next look at ui_seg, its base and end, linear; the PC)
ob = pcemu.PC.blk
def blk(s, uc, addr, size, ud):
    pa, ps = prev
    if addr != pa:                              # (a REP restarts its own block)
        if LO <= addr < HI:
            (falls if addr == pa + ps else taken)[addr - 0x600] += 1
        else:
            if ui[0] <= 0 or ui[3] is not s:    # (it moves only at the Executive's ui_room)
                seg = struct.unpack('<H', uc.mem_read(USEG, 2))[0]
                ui[:] = [4096, seg * 16 if seg else -1, seg * 16 + UEND if seg else -1, s]
            ui[0] -= 1
            if ui[1] <= addr < ui[2] and not (SPIN0 <= pa - ui[1] < SPIN1 or SPIN0 <= addr - ui[1] < SPIN1):
                (ui_falls if addr == pa + ps else ui_taken)[addr - ui[1]] += 1
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

# ---- the UI's ----------------------------------------------------------
from test_apps import CODE, K_PGDN, K_PGUP, K_HOME, K_END, press, drag     # (its keys and mouse)
APP = lambda n: os.path.join(GOS, 'apps', n + '.RUN')
K_CODE_F7 = 0x6E00
D, U, L, R, RET, ESC = ktest.DOWN, ktest.UP, ktest.LEFT, ktest.RIGHT, ktest.ENTER, ktest.ESC

def text(name, n):
    p = os.path.join(TMP, name)
    open(p, 'wb').write(b''.join(b'Line %d: the quick brown fox jumps over the lazy dog, as a user would type it.\r\n' % i
                                 for i in range(n)))
    return p

def ui_pc(name, *files, mouse=True, **kw):
    t = text('hot_t.txt', 40)
    k = ktest.KPC(mkimg.build(os.path.join(TMP, name), [os.path.join(GOS, 'src', 'LODE.SYS')] + list(files)
                  + ['F%02d.TXT=%s' % (i, t) for i in range(24)]), **kw)
    k.pc.mouse = mouse; k.start()
    return k

def w_idle():
    k = ui_pc('hot_idle.img')
    k.run_for(30)
    k.wr('saver_t', struct.pack('<H', 36)); k.run_for(15)
    k.key(D); k.run_for(2)

def w_list():
    k = ui_pc('hot_list.img', os.path.join(GOS, 'src', 'LCMD.COM'), APP('WRITE'))
    for _ in range(3):
        k.key(*[D] * 30); k.key(*[U] * 12); k.key(K_PGDN, K_PGDN, K_PGUP, K_END, K_HOME)

def w_menu():
    k = ui_pc('hot_menu.img', APP('WRITE'), 'LONG.TXT=' + text('hot_long.txt', 300))
    for _ in range(3): k.key(ktest.F1); k.key(RET)
    k.select('LONG.TXT'); k.key(RET)
    for i in range(8):
        press(k, 100 + 40 * i, 100 + 20 * i, 2)
        k.key(*[D] * (i % 4 + 1)); k.key(ESC)
    for _ in range(3): k.key(ktest.F1); k.key(RET)

def w_form():
    k = ui_pc('hot_form.img', APP('SYSTEM'))
    k.select('F03.TXT')
    for c in 'RDRD':
        k.key(CODE[c]); k.key('NEWNAME'); k.key(ktest.TAB, ktest.TAB, D, U); k.key(ESC)
    for _ in range(3): k.key(ktest.TAB, ktest.TAB, ktest.TAB, D, D, U, ESC)
    k.key(CODE['U']); k.key('C'); k.key(RET); k.key(ktest.TAB, ktest.TAB, D, U, ESC); k.key(ESC)

def w_drag():
    k = ui_pc('hot_drag.img', APP('CALC'))
    k.key(CODE['K'])
    for i in range(4):
        drag(k, 50 * 8 + 3, 36, (30 - 6 * i) * 8 + 3, 76 + 40 * i)
        drag(k, (30 - 6 * i) * 8 + 3, 76 + 40 * i, 50 * 8 + 3, 36)
    k.key(K_CODE_F7, *[L] * 10, *[D] * 12, *[R] * 6, *[U] * 6, RET)
    k.key(K_CODE_F7, *[R] * 4, ESC)

def w_write():
    k = ui_pc('hot_write.img', APP('WRITE'), 'LONG.TXT=' + text('hot_long.txt', 300), mouse=False)
    k.select('LONG.TXT'); k.key(RET)
    k.key('Typed into Write a line at a time, the way a user would: words, spaces, a full stop. ' * 2); k.key(RET)
    k.key(*[K_PGDN] * 8); k.key(*[K_PGUP] * 4); k.key(*[D] * 40); k.key(K_END, K_HOME, *[R] * 20, *[U] * 30)
    k.key('More typing at the end of a scrolled line. ')

def w_calc():
    k = ui_pc('hot_calc.img', APP('CALC'))
    k.key(CODE['K'])
    for s in ('12+34*5', '1/7', '2^10-1', 'sqrt(2)*3.5', '100/3'):
        k.key(s); k.key(RET)
    ky = 28 + 80
    for r, c in ((0, 0), (1, 3), (1, 2), (4, 3), (2, 1), (3, 0), (4, 3)):
        press(k, (42 + 6 * c + 3) * 8, ky + 24 * r + 12, 1)

def w_system():
    k = ui_pc('hot_sys.img', APP('SYSTEM'))
    k.key(CODE['U'])
    for _ in range(2):
        k.key(*[D] * 6); k.key(*[U] * 6)
    for c in 'DCMD': k.key(c)
    k.key(ESC)

def w_term():
    k = ui_pc('hot_term.img', APP('TERM'), os.path.join(GOS, 'fonts', 'TERM.FNT'), APP('CALC'),
              os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(GOS, 'src', 'LODEMT.SYS'),
              'LODE.INI=' + ini(b'MULTITASK=1\r\n'), 'LONG.TXT=' + text('hot_long.txt', 120), ems_pages=88)
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    def typ(s, t):
        k.key(s, settle=False); k.key(RET, settle=False); k.run_for(t)
    for s, t in (('dir', 3), ('type long.txt', 8), ('dir /w', 3)): typ(s, t)
    typ('type long.txt', 0.2)
    k.key(CODE['K'], settle=False); k.run_for(8)       # (the calculator in front, the TYPE drawn behind it: clipped)
    k.key('12+34', settle=False); k.key(RET, settle=False); k.run_for(1)
    k.key(ESC, settle=False); k.run_for(1)             # (the calculator closed)
    for s, t in (('type long.txt', 8), ('dir', 3)): typ(s, t)

def ini(t):
    p = os.path.join(TMP, 'hot_ini.txt'); open(p, 'wb').write(t); return p

if __name__ == '__main__':
    if len(sys.argv) < 3: sys.exit(__doc__)
    for w in sys.argv[2:]:
        print('== workload', w); globals()['w_' + w]()
    json.dump({'taken': taken, 'falls': falls, 'ui_taken': ui_taken, 'ui_falls': ui_falls}, open(sys.argv[1], 'w'))
    for n, c in (('kernel', taken), ('UI', ui_taken)):
        t = sum(c.values())
        print('%s: %d taken entries, %.1f%% at odd addresses' % (n, t, 100.0 * sum(v for a, v in c.items() if a & 1) / max(t, 1)))
