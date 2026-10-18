"""Pictures on the real CLAUDE.COM (CLAUDE /T) in emulation: CELLS op FDh
against the Pi's encoder bit for bit in video memory (its 4 banks), scrolls,
the AR488's small frames, malformed rectangles, and the text coming back.

    python3 tests/test_emu_picture.py
"""
import os, random, sys, threading, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from grid_emu import EmuHarness
from gridlink import glp, picture as PIC, plot as PL
from test_emu_term import FAKE, check, in_step, mismatch, start
import test_picture as TP

R = random.Random(1520)


def vram_bits(h):
    """Rows 0-23 of the GRiD's screen (384 lines) as picture.py's bytes."""
    v = h.m.rd(0xB800, 0, 0x8000)
    return b''.join(bytes(v[(y & 3) * 0x2000 + (y >> 2) * 80:(y & 3) * 0x2000 + (y >> 2) * 80 + 80])
                    for y in range(PIC.H))


def outside(h):
    """All of B800:0000-FFFF but rows 0-23's 384 lines (96 in each bank):
    the band, the gaps after the banks, and on past the 32 KB of video memory."""
    v = h.m.rd(0xB800, 0, 0x10000)
    return b''.join(bytes(v[b * 0x2000 + 96 * 80:(b + 1) * 0x2000]) for b in range(4)) + bytes(v[0x8000:])


def band(h):
    v = h.m.rd(0xB800, 0, 0x8000)
    return b''.join(bytes(v[(y & 3) * 0x2000 + (y >> 2) * 80:(y & 3) * 0x2000 + (y >> 2) * 80 + 80])
                    for y in range(PIC.H, 400))


def shows(h, bits, sim_s=30):
    t = h.router.term
    return h.run_until(lambda: not t.ready() and vram_bits(h) == bits, sim_s)


def first_bad_line(h, bits):
    got = vram_bits(h)
    for y in range(PIC.H):
        if got[y * 80:(y + 1) * 80] != bits[y * 80:(y + 1) * 80]: return y
    return None


def run_pictures(patched):
    h = start(patched=patched)
    try:
        t = h.router.term
        assert t.gflags & glp.GF_PIX and t.can_picture(), t.gflags
        b0 = band(h)
        xs, ys = TP.sweep(401)
        plot = PL.Plot([{'name': 'S21', 'x': xs, 'y': ys}], title='Filter', x_label='Hz', y_label='dB')
        page = TP.a_page()
        noisy = TP.noise_lines(PIC.SIZE, 0.2)
        for name, bits in (('plot', plot.bits), ('page', page), ('noise', noisy),
                           ('scrolled', page[3 * 16 * 80:] + TP.a_page()[:3 * 16 * 80]),
                           ('blank', bytes(PIC.SIZE)), ('plot again', plot.bits)):
            t.show_picture(bits, 'test', title=name)
            assert shows(h, bits), (name, first_bad_line(h, bits))
        assert band(h) != b0                         # the band shows the title...
        assert h.run_until(lambda: 'plot again' in h.screen().split('\n')[24], 10), h.screen().split('\n')[24]
        # one byte changed, at the right edge, at the last line
        b = bytearray(plot.bits); b[PIC.SIZE - 1] ^= 0x81
        t.show_picture(bytes(b), 'test')
        assert shows(h, bytes(b)), first_bad_line(h, bytes(b))
        # back to Claude Code's text, as pyte kept it
        assert t.hide_picture('test')
        assert in_step(h), mismatch(h)
        check(h)
        return h.router.term.penc
    finally:
        h.close()


def test_pictures_bit_for_bit():
    run_pictures(True)


def test_pictures_stock_ar488():
    run_pictures(False)                               # 127-byte frames


def test_malformed_rectangles():
    """Rectangles off the screen or with bad codes end the frame; nothing
    is drawn outside rows 0-23, CLAUDE goes on."""
    h = start()
    try:
        t = h.router.term
        page = TP.a_page()
        t.show_picture(page, 'test')
        assert shows(h, page)
        b0 = outside(h)
        bad = [
            bytes([0x02, 0, 0, PIC.OP_PIX, 380 & 255, 380 >> 8, 0, 80, 8]) + bytes([0xB1, 0xFF]) * 8,   # y + h > 384
            bytes([0x02, 0, 0, PIC.OP_PIX, 0, 0, 70, 20, 1, 0xED, 0xFF]),                               # x + w > 80
            bytes([0x02, 0, 0, PIC.OP_PIX, 0, 0, 200, 100, 1, 0x9D, 0xFF]),                             # x + w > 255
            bytes([0x02, 0, 0, PIC.OP_PIX, 0, 0, 0, 2, 1, 0x05, 1, 2, 3, 4, 5, 6]),                      # 6 bytes into 2
            bytes([0x02, 0, 0, PIC.OP_PIX, 0, 0, 0, 0, 1]),                                             # w 0
            bytes([0x02, 0, 0, PIC.OP_PIX, 0, 0, 0, 1, 0]),                                             # h 0
            bytes([0x02, 0, 0, PIC.OP_PIX, 0, 0, 0, 40, 2, 0xD9]),                                      # cut short
            bytes([0x02, 0, 0, PIC.OP_PIX, 0x7F, 0x01]),                                                # the head cut
            bytes([0x02, 0, 0, PIC.OP_PIX, 0xFF, 0xFF, 0, 1, 1, 0, 0xFF]),                              # y FFFFh
            bytes([0x02, 0, 0, PIC.OP_PIX, 0xF0, 0xFF, 0, 80, 32]) + bytes([0xB1, 0xFF]) * 32,         # y FFF0h: wraps
        ]
        real_take, real_ready = t.take, t.ready
        q = list(bad)
        def take(maxpay):
            if q:
                p = q.pop(0); t.from_pic = False; return p
            return real_take(maxpay)
        t.take = take; t.ready = lambda: bool(q) or real_ready()
        try:
            h.link.wake()
            assert h.run_until(lambda: not q, 30)
            h.run_until(lambda: False, 1.0)
        finally:
            t.take, t.ready = real_take, real_ready
        assert outside(h) == b0, 'drawn outside rows 0-23'
        assert not h.m.crash and h.var('n_fail', 2) == 0, (h.m.crash, h.var('n_fail', 2))
        # the screen got what came before the bad parts; the Pi sends the rest again
        t.picture_lost()
        assert shows(h, page), first_bad_line(h, page)
        check(h)
    finally:
        h.close()


def test_run_and_repaint_bring_it_back():
    h = start()
    try:
        t = h.router.term
        xs, ys = TP.sweep(201)
        plot = PL.Plot([{'x': xs, 'y': ys}], title='Filter')
        t.show_picture(plot.bits, 'test')
        assert shows(h, plot.bits)
        # a DOS program in the middle: text mode, then the Term screen from the shadow; the Pi sends the picture again
        res = {}
        th = threading.Thread(target=lambda: res.update(r=t.grid.run('VER', capture=False)))
        th.start()
        assert h.run_until(lambda: not th.is_alive(), 30), 'RUN did not finish'
        assert h.m.mode() == 0x40
        assert shows(h, plot.bits), first_bad_line(h, plot.bits)
        # CODE-R
        h.m.wr(0xB800, 0, b'\xff' * 2000)
        h.press(0x1300)
        assert shows(h, plot.bits), first_bad_line(h, plot.bits)
        # Ctrl-L: CLAUDE draws its text again at once, the Pi the picture
        h.m.wr(0xB800, 0, b'\x55' * 2000)
        h.press(0x260C)
        assert shows(h, plot.bits), first_bad_line(h, plot.bits)
        assert t.hide_picture('test')
        assert in_step(h), mismatch(h)
        check(h)
    finally:
        h.close()


if __name__ == '__main__':
    names = [n for n in list(globals()) if n.startswith('test_')]
    if len(sys.argv) > 1: names = [n for n in names if any(a in n for a in sys.argv[1:])]
    ok = 0
    for n in names:
        t0 = time.time()
        try:
            globals()[n](); ok += 1
            print('ok   %-36s %.1fs' % (n, time.time() - t0), flush=True)
        except Exception:
            print('FAIL %s' % n); traceback.print_exc()
    print('%d of %d passed' % (ok, len(names)))
    sys.exit(0 if ok == len(names) else 1)
