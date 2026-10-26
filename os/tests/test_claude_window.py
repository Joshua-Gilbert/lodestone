"""CLAUDE.COM 1.13 in a terminal window (T5d), on the Lodestone kernel with
its multitasking (LODEMT.SYS, MULTITASK=1, EMS), TERM.RUN and TERM.FNT:
CODE-A starts CLAUDE as a task behind, in a window, its screen published
(MT_PUB) and drawn there with its own font, the bridge's SRQ waking it
(MT_WAKE); a picture full screen and back; Shift-CODE-A full screen in the
Executive's task as before.  The 7210 with the AR488 bridge model, the
real gridlink and a stand-in Claude Code in a pty (claude-link/tests).

    python3 tests/test_claude_window.py [name ...]
"""
import os, struct, sys, threading, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import claude_kernel as CK                      # (claude-link's tests on the path)
import grid_emu as G
import ktest
from gridlink import picture as PIC

FAKE = '%s %s' % (sys.executable, os.path.join(CK.GL_TESTS, 'fake_claude.py'))
CODE_A, CODE_Q, CODE_TAB, ENTER = 0x1E00, 0x1000, 0xA500, 0x1C0D
INI = b'MULTITASK=1\r\nMTMEM=LCMD.COM:64,CLAUDE.COM:128\r\n'      # (the ROM's line)
PBF_SHOWN = 1

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''),
          flush=True)


class Win(CK.KernelHarness):
    """The floppy with LODEMT.SYS, TERM.RUN, TERM.FNT and LODE.INI, EMS, the
    router with the stand-in Claude Code.  CLAUDE's PSP found by its image
    (it runs in a task: cur_psp is the running task's)."""
    def __init__(s, more=None, claude_com=G.CLAUDE_COM, **kw):
        files = {'A:\\LODEMT.SYS': open(os.path.join(GOS, 'src', 'LODEMT.SYS'), 'rb').read(),
                 'A:\\TERM.RUN': open(os.path.join(GOS, 'apps', 'TERM.RUN'), 'rb').read(),
                 'A:\\TERM.FNT': open(os.path.join(GOS, 'fonts', 'TERM.FNT'), 'rb').read(),
                 'A:\\LODE.INI': INI}
        files.update(more or {})
        super().__init__(files=files, term=FAKE, ems_pages=88, claude_com=claude_com, **kw)
        s.img = open(claude_com, 'rb').read()
        s.font_img = s.img[s.sym['font'] - 0x100:s.sym['font'] - 0x100 + (0xAF - 0x20) * 16]
        s.claude_psp = None
        s.probe = []                             # (win_probe: was MT_PUB's first AL 0? win_front_task called)
        wft, watch = s.sym['win_front_task'], s.m.watch
        def w(addr):
            if s.m.r('ip') == wft and s.m.rd(s.m.r('cs'), 0x100, 32) == s.img[:32]: s.probe.append(s.m.us)
            watch(addr)
        s.m.watch = w

    def boot_exec(s):
        k = ktest.KPC.__new__(ktest.KPC)
        k.pc = s.m; k.Y = s.m.Y; k.dos = []; k.pending = {}; k.trace = False; k.hooks = []
        s.k = k
        s.m.boot(0); k.settle(8)
        assert s.m.mode() == 0x40, (s.m.crash, k.where())
        s.mcb0 = s.m.u16(0x60, s.m.Y['first_mcb'])     # (the whole arena's: first_mcb is per task)

    def find_psp(s):
        """CLAUDE's PSP: CD 20, then its code at 100h."""
        mem = bytes(s.m.mu.mem_read(0, 0xA0000))
        sig = s.img[:64]
        i = mem.find(sig, 0x1000)
        while i >= 0:
            if (i - 0x100) % 16 == 0 and mem[i - 0x100:i - 0xFE] == b'\xcd\x20': return (i - 0x100) // 16
            i = mem.find(sig, i + 1)
        return None

    def code_a(s, shift=False, sim_s=20):
        if shift: s.m.wr(0x40, 0x17, bytes([s.m.rd(0x40, 0x17, 1)[0] | 2]))
        s.m.keys.append(CODE_A); s.m.halted = False
        s.run_until(lambda: s.find_psp() is not None or s.m.crash, 5)
        if shift: s.m.wr(0x40, 0x17, bytes([s.m.rd(0x40, 0x17, 1)[0] & 0xFC]))
        s.claude_psp = s.find_psp()
        assert s.claude_psp, ('CLAUDE never started', s.m.crash, s.k.where())
        return s.run_until(lambda: s.var('connected') and s.var('term'), sim_s)

    # MT's own (its block, LODE.MAP's offsets in it)
    def mt_seg(s):
        seg = s.mcb0
        for _ in range(300):
            t, own, sz = s.m.rd(seg, 0, 1)[0], s.m.u16(seg, 1), s.m.u16(seg, 3)
            if own == 8 and s.m.rd(seg, 8, 2) == b'MT': return seg + 1
            if t != 0x4D: return None
            seg += sz + 1
    def mb(s, name): return s.m.rd(s.mt_seg(), s.m.Y[name], 1)[0]

    def desc(s):
        b = s.m.rd(s.claude_psp, s.sym['wdesc'], 22)
        return dict(flags=b[1], cur=struct.unpack_from('<H', b, 14)[0], chg=struct.unpack_from('<H', b, 16)[0])

    def text(s): return s.k.text()
    def band24(s):
        """The shadow's row 24 (the status band, published with the rest)."""
        raw = s.m.rd(s.var('shadseg', 2), 24 * 160, 160)
        return ''.join(chr(c) if 32 <= c < 127 else ' ' for c in raw[::2])
    def wait_text(s, t, sim_s=20): return s.run_until(lambda: t in s.text(), sim_s)


def glyph_shown(h, code):
    """Code's glyph (CLAUDE's font) drawn somewhere on the screen, byte for
    byte: 16 lines of one byte column."""
    v = h.m.rd(0xB800, 0, 0x8000)
    lin = b''.join(v[(y & 3) * 0x2000 + (y >> 2) * 80:(y & 3) * 0x2000 + (y >> 2) * 80 + 80] for y in range(400))
    g = h.font_img[(code - 0x20) * 16:(code - 0x1F) * 16]
    return any(g in lin[x::80] for x in range(80))


def in_step(h):
    """CLAUDE's shadow, rows 0-23, is what pyte has on the Pi."""
    t = h.router.term
    with t.lock:
        if t.dirty: return False
        tc, ta = t.screen.cells()
    raw = h.m.rd(h.var('shadseg', 2), 0, 24 * 160)
    return [bytes(raw[r * 160:(r + 1) * 160:2]) for r in range(24)] == [bytes(r) for r in tc] and \
        [bytes(raw[r * 160 + 1:(r + 1) * 160:2]) for r in range(24)] == [bytes(r) for r in ta]


def pixels(h):
    v = h.m.rd(0xB800, 0, 0x8000)
    return b''.join(v[(y & 3) * 0x2000 + (y >> 2) * 80:(y & 3) * 0x2000 + (y >> 2) * 80 + 80] for y in range(PIC.H))


def t_window():
    h = Win(irq_exact=True)
    try:
        h.boot_exec()
        conn = h.code_a()
        task = h.mb('mt_wkt')                   # (CLAUDE's task: its wake's, MT_WAKE)
        ok = h.wait_text('Welcome to Claude Code', 30)
        check('CODE-A with MULTITASK=1: CLAUDE.COM a task behind (task 0 still in front, mode 40h), in a terminal window '
              '(a session showing its task), connected in Term, the login screen drawn in the window',
              conn and ok and h.mb('mt_front') == 0 and h.m.mode() == 0x40 and h.mb('mw_n') == 1
              and h.var('wmode') and h.var('win'), (conn, ok, h.mb('mt_front'), h.mb('mw_n'), h.var('wmode'), h.text()[-600:]))
        check('... its first MT_PUB said a window shows it (AL 1: no wait for one)', not h.probe, h.probe)
        check('... MT_WAKE asked: the wake is its task\'s (mt_wkt)', h.mb('mt_wkt') not in (0, 0xFF), h.mb('mt_wkt'))
        check('... the status band in its shadow\'s row 24, published with the rest', 'CODE-Q quits' in h.band24(), h.band24())
        # the mascot: CLAUDE's own glyphs, drawn by TERM from its memory
        t = h.router.term
        with t.lock:
            t.stream.feed(('\x1b[2J\x1b[H' + ' \u2590\u259b\u2588\u2588\u2588\u259c\u258c\r\n'
                           '\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598\r\n').encode())
            t._mark()
        t.link.wake()
        ok = h.run_until(lambda: all(glyph_shown(h, c) for c in (0xA6, 0xA9, 0xAA, 0xA5, 0xA2)), 20)
        check('the mascot\'s glyphs (A2h, A5h, A6h, A9h, AAh) drawn in the window byte for byte with CLAUDE\'s font', ok)
        # typed in the window: to CLAUDE (MT_TKEY), to the Pi, its answer drawn
        h.k.key('hello', settle=False); h.m.keys.append(ENTER); h.m.halted = False
        ok = h.wait_text('You said: hello', 30)
        check('"hello" typed in the window: to CLAUDE, the Pi\'s answer drawn there', ok, h.text()[-600:])
        # CODE-Tab: the window is its screen (nothing else to go to)
        h.m.keys.append(CODE_TAB); h.m.halted = False
        h.run_until(lambda: False, 1.5)
        check('CODE-Tab: passes over it (its window is its screen): task 0 still in front, the window drawn',
              h.mb('mt_front') == 0 and h.m.mode() == 0x40 and 'You said: hello' in h.text(), (h.mb('mt_front'), h.text()[-300:]))
        # a picture: full screen (CLAUDE's task in front, mode 40h, its pixels), and back
        page = bytes((y * 7 + x) & 0xFF if (y // 16) % 3 == 0 else 0 for y in range(PIC.H) for x in range(80))
        t0 = h.m.us
        t.show_picture(page, 'test', title='A picture')
        ok = h.run_until(lambda: h.mb('mt_front') == task and pixels(h) == page, 30)
        check('a picture: CLAUDE full screen (its task in front, mode 40h), the picture bit for bit (%.0f ms)'
              % ((h.m.us - t0) / 1000), ok and h.var('pic') and not h.desc()['flags'] & PBF_SHOWN,
              (h.mb('mt_front'), h.var('pic'), [i for i, (a, b) in enumerate(zip(pixels(h), page)) if a != b][:12],
               sum(a != b for a, b in zip(pixels(h), page))))
        t.hide_picture('test')
        ok = h.run_until(lambda: h.mb('mt_front') == 0 and h.var('win') and 'You said: hello' in h.text(), 30)
        check('... the picture gone: back to its window (task 0 in front), its text drawn there again',
              ok and h.desc()['flags'] & PBF_SHOWN, (h.mb('mt_front'), h.var('win'), h.text()[-400:]))
        # RUN in the window: the program's text there; its snapshot through INT 10h (its pages, not B800h)
        g = t.grid; res = {}
        th = threading.Thread(target=lambda: res.update(r=g.run('VER', capture=False, snapshot=True)))
        th.start()
        h.run_until(lambda: not th.is_alive(), 60)
        snap = {}
        th = threading.Thread(target=lambda: snap.update(r=g.screen(0)))
        th.start()
        h.run_until(lambda: not th.is_alive(), 30)
        s = snap.get('r') or b''
        txt = bytes(s[9::2]).decode('cp437', 'replace') if s[:1] == b'\x03' else ''
        check('a RUN of VER in the window: done, its snapshot the program\'s text screen (mode 3, "Lodestone"), not '
              'the Executive\'s', res.get('r', {}).get('exit') == 0 and 'Lodestone' in txt, (h.m.crash, res, s[:9], txt[:300]))
        ok = h.run_until(lambda: h.mb('mt_front') == 0 and h.desc()['flags'] & PBF_SHOWN and in_step(h), 20)
        check('... afterwards its screen in the window again (published, shown), its shadow Claude Code\'s screen',
              ok, (h.m.crash, h.text()[-300:]))
        # CODE-Q: it ends, the window closes
        h.m.keys.append(CODE_Q); h.m.halted = False
        ok = h.run_until(lambda: h.mb('mw_n') == 0 and any('CLAUDE.COM ended' in l for l in h.k.band()), 20)
        check('CODE-Q: CLAUDE ends, its window closes ("CLAUDE.COM ended")', ok, (h.mb('mw_n'), h.k.band()))
        check('no link failure, nothing wrong in gridlink\'s log', not h.m.crash and not [l for l in h.log if 'Traceback' in str(l)],
              (h.m.crash, [l for l in h.log if 'Traceback' in str(l)][:2]))
    finally:
        h.close()


def t_shift():
    h = Win()
    try:
        h.boot_exec()
        conn = h.code_a(shift=True)
        ok = h.run_until(lambda: 'Welcome to Claude Code' in h.text(), 30)
        check('Shift-CODE-A: full screen in the Executive\'s task as before (no window, mode 40h, CLAUDE drawing), '
              'MT_WAKE asked (task 0\'s)', conn and ok and h.mb('mw_n') == 0 and not h.var('wmode') and h.mb('mt_wkt') == 0,
              (conn, ok, h.mb('mw_n'), h.var('wmode'), h.mb('mt_wkt')))
        h.k.key('hi', settle=False); h.m.keys.append(ENTER); h.m.halted = False
        check('... typed: the Pi\'s answer on the screen', h.wait_text('You said: hi', 30), h.text()[-300:])
        h.m.keys.append(CODE_Q); h.m.halted = False
        check('... CODE-Q: back in the Executive', h.back_in_executive(10), h.k.where())
    finally:
        h.close()


def flood(t, scroll=False):
    """The Pi's screen always changed, whole, at once: every frame the GRiD
    asks for is a full one (the encoder's own; its making costs the GRiD
    no time in the emulation).  scroll: instead 3 new lines at its foot a
    frame, the rest scrolled up (the encoder's scroll op, FEh)."""
    import random
    rnd = random.Random(5150); take = t.take
    line = lambda: ''.join(rnd.choice('abcdefghij klmnop') for _ in range(79))
    def take2(maxpay):
        with t.lock:
            if scroll: t.stream.feed(('\x1b[24;1H' + ''.join('\r\n' + line() for _ in range(3))).encode())
            else: t.stream.feed(('\x1b[H' + '\r\n'.join(line() for _ in range(23))).encode())
        return take(maxpay)
    t.take = take2
    t.ready = lambda: True


def no_wake(src):
    """A copy of CLAUDE.COM (and its map) that asks MT_WAKE with BL = 0."""
    import shutil, tempfile
    d = tempfile.mkdtemp(prefix='nowake-')
    img = bytearray(open(src, 'rb').read())
    o = G.symbols(os.path.splitext(src)[0] + '.MAP')['win_probe'] - 0x100
    assert img[o:o + 5] == bytes([0xB8, 0x23, 0xF0, 0xB3, 0x01]), img[o:o + 5].hex()
    img[o + 4] = 0
    p = os.path.join(d, 'CLAUDE.COM'); open(p, 'wb').write(img)
    shutil.copy(os.path.splitext(src)[0] + '.MAP', os.path.join(d, 'CLAUDE.MAP'))
    return p


def copy_rates(h, kb=64):
    """KB a simulated second each way, a file of kb KB through M: (the RAM
    disk, as gridlink.bench copies: the link, not the floppy)."""
    g = h.router.term.grid
    data = bytes((i * 7) & 0xFF for i in range(kb * 1024))
    out = []
    for f in (lambda: g.write_file('M:\\BENCH.BIN', data), lambda: g.read_file('M:\\BENCH.BIN')):
        res = {}; us0 = h.m.us
        th = threading.Thread(target=lambda: res.update(r=f())); th.start()
        assert h.run_until(lambda: not th.is_alive(), 60), 'the copy did not finish'
        out.append(kb / ((h.m.us - us0) / 1e6))
    assert res['r'][:len(data)] == data or res['r'] == data, 'the copy back differs'
    return out


def measure(shift=False, spin=False, wake=True, scroll=False, sim_s=6.0):
    """KB a simulated second each way through M: (copy_rates), then CELLS
    bytes a simulated second through a flood: full screen in task 0 (shift)
    or in a window; MTSPIN computing behind (spin); MT_WAKE asked or not."""
    files = {'A:\\MTSPIN.COM': open(os.path.join(HERE, 'MTSPIN.COM'), 'rb').read(),
             'A:\\MTLAUNCH.COM': open(os.path.join(HERE, 'MTLAUNCH.COM'), 'rb').read(),
             'A:\\LODE.INI': INI + b'MDISK=256\r\n'}
    kw = {} if wake else {'claude_com': no_wake(G.CLAUDE_COM)}
    h = Win(irq_exact=True, more=files, bridge='pico', **kw)            # (the 1520's: frames of 3,340 bytes)
    h.cfg.set_clock = False                         # (the clock set at the HELLO would end MTSPIN's count)
    try:
        h.boot_exec()
        if spin:
            h.k.code_p()
            for line in ('mtlaunch mtspin.com 30000 x.txt', '', 'exit'):
                h.k.key(line, settle=False); h.m.keys.append(ENTER); h.k.settle(3)
            assert h.m.mode() == 0x40, 'not back in the Executive'
        assert h.code_a(shift=shift) and h.wait_text('Welcome to Claude Code', 30), h.text()[-300:]
        t = h.router.term
        to_grid, to_pi = copy_rates(h)
        flood(t, scroll)
        h.run_until(lambda: False, 1.0)                 # (under way)
        b0, f0, us0 = t.enc.stats['bytes'], t.enc.stats['frames'], h.m.us
        moves, watch = [0], h.m.watch                   # (TERM's scrl moving what scrolled: T5d)
        if not shift:
            import test_apps as A
            Y = h.m.Y
            base = h.m.u16(h.mt_seg(), Y['mw_ses'] + 128 + 2)      # (KMW.INC: SE_SIZE, SE_BASE; the first window's)
            at = h.m.u16(0x60, Y['ui_seg']) * 16 + base + A.run_syms('apps/TERM.ASM')['scrl.m']
            def w(a):
                watch(a)
                if a == at: moves[0] += 1
            h.m.watch = w
        h.run_until(lambda: h.m.crash, sim_s)
        h.m.watch = watch
        s = (h.m.us - us0) / 1e6
        if spin:                                        # (MTSPIN still there, ready to run)
            ents = [h.m.rd(h.mt_seg(), h.m.Y['mt_tab'] + n * 32, 22) for n in range(8)]
            assert any(e[0] == 1 and e[10:20] == b'MTSPIN.COM' for e in ents), [(e[0], e[10:22]) for e in ents]
        return to_grid, to_pi, (t.enc.stats['bytes'] - b0) / s, (t.enc.stats['frames'] - f0) / s, h.mb('mt_wkt'), \
            moves[0] / s
    finally:
        h.close()


def t_speed():
    """The link through a flood ("no speed for space"): windowed with the
    wake within 10% of full screen's bytes a second, nothing behind."""
    r = {}
    for name, kw in (('full screen, task 0', dict(shift=True)), ('window, MT_WAKE', {}),
                     ('window, no MT_WAKE', dict(wake=False)),
                     ('full screen, MTSPIN behind', dict(shift=True, spin=True)),
                     ('window, MT_WAKE, MTSPIN behind', dict(spin=True)),
                     ('window, no MT_WAKE, MTSPIN behind', dict(wake=False, spin=True)),
                     ('full screen, scrolling', dict(shift=True, scroll=True)),
                     ('window, MT_WAKE, scrolling', dict(scroll=True))):
        r[name] = measure(**kw)
        print('     %-36s copies %5.1f KB/s to the GRiD, %5.1f to the Pi; flood %7.0f bytes/s %5.1f frames/s  (mt_wkt %02X; '
              'TERM moved rows %.1f times a second)' % ((name,) + r[name]), flush=True)
    full, win = r['full screen, task 0'][2], r['window, MT_WAKE'][2]
    check('the flood in a window with MT_WAKE: %.0f bytes/s, within 10%% of full screen\'s %.0f (%.0f%%)'
          % (win, full, 100.0 * win / full), win >= 0.9 * full, r)
    fs, ws = r['full screen, scrolling'], r['window, MT_WAKE, scrolling']
    check('... scrolling (3 new lines a frame): %.0f bytes/s in the window, %.0f full screen (%.0f%%); TERM moving what '
          'scrolled (scrl, %.1f times a second)' % (ws[2], fs[2], 100.0 * ws[2] / fs[2], ws[5]), ws[5] > 0, r)
    a, b = r['window, MT_WAKE, MTSPIN behind'], r['window, no MT_WAKE, MTSPIN behind']
    check('MTSPIN computing behind: copies in a window with MT_WAKE faster both ways than without (%.1f, %.1f KB/s '
          'against %.1f, %.1f)' % (a[0], a[1], b[0], b[1]), a[0] > b[0] and a[1] > b[1] * 1.2, r)


TESTS = [t_window, t_shift, t_speed]
if __name__ == '__main__':
    want = sys.argv[1:]
    for t in TESTS:
        if want and t.__name__[2:] not in want: continue
        print('==', t.__name__[2:], flush=True)
        t0 = time.time()
        try: t()
        except Exception:
            traceback.print_exc(); check(t.__name__ + ' ran to the end', False)
        print('   (%.1f s)' % (time.time() - t0), flush=True)
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s' % (len(results), len(bad), (': ' + ', '.join(bad)) if bad else ''))
    sys.exit(1 if bad else 0)
