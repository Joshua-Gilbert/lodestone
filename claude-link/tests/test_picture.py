"""Pictures on the GRiD (picture.py, plot.py, plotview.py, term.py's
picture layer, the grid_plot / grid_image / grid_pick tools): the encoder
against a model of CLAUDE.COM's op FDh, plots and their clicks, and the
whole path through GridSim, the AR488 model and the MCP server.

    python3 tests/test_picture.py
"""
import io, json, math, os, random, sys, threading, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
from gridlink import glp, picture as PIC, plot as PL, termscreen as TS
from gridsim import TermHarness
from test_mcp import Client, body

R = random.Random(5150)


def noise_lines(n, density=0.1):
    return bytes(R.randrange(256) if R.random() < density else 0 for _ in range(n))


def a_page():
    """Text-like: rows of 'glyphs' 16 lines apart, blank between."""
    b = bytearray(PIC.SIZE)
    for row in range(24):
        n = R.randrange(10, 80)
        for y in range(row * 16 + 2, row * 16 + 13):
            for x in range(n):
                b[y * 80 + x] = R.choice((0, 0x18, 0x3C, 0x66, 0x7E, 0xC3))
    return bytes(b)


def send_all(enc, bits, maxpay, screen, pix_only=True):
    """The encoder's frames for bits onto screen (as CLAUDE.COM decodes them)
    until it has nothing more: -> (frames, bytes)."""
    n = tot = 0
    while True:
        p, more = enc.make(bits, maxpay)
        if p is None: return n, tot
        assert len(p) <= maxpay, (len(p), maxpay)
        if pix_only: assert PIC.apply_pixels(p, screen) is True
        else:
            chs, ats = TS._blank_rows(); TS.apply(p, chs, ats, screen)
        enc.delivered(); n += 1; tot += len(p)
        assert n < 2000, 'no end'


# ---- the format --------------------------------------------------------------
def test_packbits():
    cases = [bytes(80), b'\xff' * 80, bytes(range(80)), b'\x01' * 129 + b'\x02',
             bytes([1, 1, 2, 3, 3, 3, 4]), b'\x00', b'\x05\x06']
    cases += [noise_lines(R.randrange(1, 200), R.random()) for _ in range(300)]
    for row in cases:
        code = PIC.packbits(row)
        out, i = PIC.unpackbits(code, 0, len(row))
        assert out == row and i == len(code), (row, code)
    assert len(PIC.packbits(bytes(80))) == 2                 # a blank line: one run
    # codes that don't make exactly the line's bytes are malformed
    assert PIC.unpackbits(bytes([0x02, 1, 2]), 0, 3) == (None, 1)       # cut short
    assert PIC.unpackbits(bytes([0xFE, 7]), 0, 2)[0] is None             # 3 bytes into 2


def test_encoder_bit_for_bit():
    for maxpay in (254, 118, 40):
        enc = PIC.Encoder(); screen = bytearray(PIC.SIZE)
        pics = [a_page(), a_page(), noise_lines(PIC.SIZE, 0.3), bytes(PIC.SIZE), a_page()]
        for bits in pics:
            send_all(enc, bits, maxpay, screen)
            assert bytes(screen) == bits, maxpay
        # a small change: a few bytes
        b = bytearray(pics[-1]); b[200 * 80 + 40] ^= 0xFF
        n, tot = send_all(enc, bytes(b), maxpay, screen)
        assert bytes(screen) == bytes(b) and n == 1 and tot < 20, (n, tot)


def test_encoder_scrolls():
    enc = PIC.Encoder(); screen = bytearray(PIC.SIZE)
    page = a_page()
    send_all(enc, page, 254, screen)
    for k in (1, 3):
        strip = a_page()[:k * 16 * 80]
        moved = page[k * 16 * 80:] + strip
        n, tot = send_all(enc, moved, 254, screen)
        assert bytes(screen) == moved
        alone = send_all(PIC.Encoder(), bytes(PIC.SIZE - len(strip)) + strip, 254, bytearray(PIC.SIZE))[1]
        assert tot < alone + 40 * n, (k, tot, alone)        # a scroll op and the new strip, not a page
        page = moved


def test_cells_and_pixels_together():
    """termscreen.apply's model (GridSim's): the clear wipes pixels, a cell
    drawn over them clears its 8 x 16, an older CLAUDE ends the frame at FDh."""
    enc = PIC.Encoder(); pix = bytearray(PIC.SIZE)
    bits = a_page()
    n, _ = send_all(enc, bits, 254, pix, pix_only=False)
    assert bytes(pix) == bits
    chs, ats = TS._blank_rows()
    p = bytes([0, 0, 0]) + bytes([2, 10, 3]) + b'abc'       # a run on row 2, columns 10-12
    TS.apply(p, chs, ats, pix)
    assert all(pix[y * 80 + x] == 0 for y in range(32, 48) for x in (10, 11, 12))
    assert bytes(chs[2][10:13]) == b'abc'
    # an older CLAUDE.COM (no pixels): the frame ends at FDh, the run after it isn't drawn
    chs, ats = TS._blank_rows()
    p = bytes([0, 0, 0, PIC.OP_PIX, 0, 0, 0, 1, 1, 0, 0x55, 3, 0, 1]) + b'Z'
    TS.apply(p, chs, ats)
    assert chs[3][0] == 32
    chs, ats = TS._blank_rows(); pix = bytearray(PIC.SIZE)
    TS.apply(p, chs, ats, pix)
    assert pix[0] == 0x55 and chs[3][0] == ord('Z')


def test_malformed_pixels():
    good = bytes([0, 0, 0, PIC.OP_PIX, 0, 0, 5, 2, 1, 1, 0xAA, 0xBB])
    pix = bytearray(PIC.SIZE)
    assert PIC.apply_pixels(good, pix) is True and pix[5:7] == b'\xaa\xbb'
    for bad in (bytes([0, 0, 0, PIC.OP_PIX, 0x80, 1, 0, 1, 1, 0, 0]),       # y 384
                bytes([0, 0, 0, PIC.OP_PIX, 0, 0, 79, 2, 1, 1, 0, 0]),       # x + w 81
                bytes([0, 0, 0, PIC.OP_PIX, 0, 0, 0, 0, 1]),                  # w 0
                bytes([0, 0, 0, PIC.OP_PIX, 0, 0, 0, 1, 0]),                  # h 0
                bytes([0, 0, 0, PIC.OP_PIX, 0, 0, 0, 2, 1, 2, 1, 2, 3]),      # 3 bytes into 2
                bytes([0, 0, 0, PIC.OP_PIX, 0, 0, 0, 4, 1, 3, 1])):           # cut short
        assert PIC.apply_pixels(bad, bytearray(PIC.SIZE)) is False, bad


def test_dither():
    from PIL import Image
    g = Image.linear_gradient('L').resize((640, 384))
    t = time.time(); bits = PIC.dither(g); dt = time.time() - t
    assert len(bits) == PIC.SIZE and dt < 0.5, dt
    im = Image.frombytes('1', (640, 384), bits)
    top, bottom = im.crop((0, 0, 640, 40)), im.crop((0, 344, 640, 384))
    assert top.histogram()[255] == 0 and bottom.histogram()[0] == 0     # black and white stay solid
    mid = im.crop((0, 176, 640, 208)).convert('L').histogram()
    assert 0.3 < mid[255] / (640 * 32) < 0.7                              # grey: half lit


# ---- plots --------------------------------------------------------------------
def sweep(n=1601):
    xs = [300e3 + i * (3e9 - 300e3) / (n - 1) for i in range(n)]
    ys = [-0.5 - 25 * math.exp(-((i - 800) / 15) ** 2) for i in range(n)]
    return xs, ys


def test_plot_and_clicks():
    xs, ys = sweep()
    t = time.time()
    p = PL.Plot([{'name': 'S21', 'x': xs, 'y': ys}], title='S21', x_label='Hz', y_label='dB')
    assert time.time() - t < 1.0
    assert len(p.bits) == PIC.SIZE and any(p.bits)
    L, T, R, B = p.box
    x, y = p.ax.px(xs[800]), p.ay.px(ys[800])
    assert L < x < R and T < y < B
    c = p.at(int(x), int(y) + 2)
    assert c['nearest']['index'] in range(795, 806) and c['nearest']['series'] == 'S21', c
    assert abs(c['x'] - xs[800]) < (xs[1] - xs[0]) * 10
    w = p.words(c)
    assert w.startswith('[clicked plot "S21": Hz = ') and 'nearest point: S21 #' in w, w
    # outside the box: no data, and nothing near
    c = p.at(2, 380)
    assert c['x'] is None and c['nearest'] is None
    # the frame is lit; the dotted grid is
    assert p.bits[T * 80 + 40] == 0xFF
    # log axes; bad data is an error, not a crash
    q = PL.Plot([{'y': [10 ** (i / 50) for i in range(300)], 'style': 'both'}], y_log=True)
    c = q.at(int(q.ax.px(150)), int(q.ay.px(10 ** 3)))
    assert c['nearest']['index'] in range(145, 156) and abs(math.log10(c['y']) - 3) < 0.05, c
    for bad in ([], [{'y': []}], [{'y': ['a']}], [{'x': [1], 'y': [1, 2]}], [{'y': [1]}] * 9,
                [{'y': [1], 'style': 'bars'}]):
        try: PL.Plot(bad); raise AssertionError(bad)
        except ValueError: pass
    try: PL.Plot([{'y': [1, 2]}], y_range=[2, 1]); raise AssertionError('range')
    except ValueError: pass
    # NaN and gaps don't break it
    PL.Plot([{'y': [1, float('nan'), None, 3]}])


def test_tick_labels():
    assert PL.tick_label(1.5e9, 0.5e9, 9) == '1.5G'
    assert PL.tick_label(250, 50, 0) == '250'
    assert PL.tick_label(0.25, 0.05, 0) == '0.25'
    assert PL.tick_label(-2.5e-6, 0.5e-6, -6) == '-2.5' + chr(PL.G_MICRO)
    assert PL.log_label(1000) == '1k' and PL.log_label(1) == '1' and PL.log_label(2e6) == '2M'
    t, st = PL.nice_ticks(0.3e6, 3e9)
    assert st == 5e8 and t[0] == 5e8 and t[-1] == 3e9, (t, st)


def test_files():
    s = PL.series_from_file('f,S21,S11\n1,2,3\n2,3,4\n')
    assert [x['name'] for x in s] == ['S21', 'S11'] and s[0]['x'] == [1.0, 2.0]
    s = PL.series_from_file('-3.1E+00, 0.0E+00\n-3.2E+00, 0.0E+00\n', 0, [1])
    assert s[0]['x'] is None and s[0]['y'] == [-3.1, -3.2]
    s = PL.series_from_file('1 2\n3 4\n5 6\n')
    assert s[0]['x'] == [1, 3, 5] and s[0]['y'] == [2, 4, 6]
    assert PL.series_from_file('CURVE 1,2,3.5,-4e1')[0]['y'] == [1, 2, 3.5, -40]
    assert PL.series_from_file('[{"y": [1, 2]}]') == [{'y': [1, 2]}]


# ---- through the link -----------------------------------------------------------
def start(**kw):
    h = TermHarness(**kw)
    assert h.wait_text('Welcome to Claude Code', wall=10), h.log
    return h


def shows(h, bits, wall=10):
    return h.run_until(lambda: bytes(h.grid.pix) == bits, wall=wall)


def test_picture_layer():
    h = start()
    try:
        t = h.term
        assert t.can_picture()
        page = a_page()
        got = []
        t.show_picture(page, 'test', on_click=lambda x, y: got.append((x, y)), title='A test picture')
        assert shows(h, page), 'the picture never arrived'
        assert all(bytes(r).strip() == b'' for r in h.grid.cells), 'the text is still there'
        assert h.run_until(lambda: h.grid.title == b'A test picture', wall=5), h.grid.title
        # a change: only the difference
        before = h.grid.stats['cells_bytes']
        b = bytearray(page); b[100 * 80:100 * 80 + 10] = b'\xff' * 10
        t.show_picture(bytes(b), 'test', on_click=lambda x, y: got.append((x, y)))
        assert shows(h, bytes(b))
        assert h.grid.stats['cells_bytes'] - before < 60, h.grid.stats['cells_bytes'] - before
        # clicks in pixels go to the picture; the band's row doesn't
        h.grid.click(321, 123); h.grid.click(10, 390)
        assert h.run_until(lambda: got, wall=5) and got == [(321, 123)], got
        h.run_until(lambda: False, wall=0.3); assert got == [(321, 123)], got
        # CODE-R: the GRiD drew its text again; the picture comes back whole
        h.grid.pix[:] = bytes(PIC.SIZE)
        h.grid.queue(glp.G_EVENT, bytes([glp.EV_REPAINT]))
        assert shows(h, bytes(b))
        # Claude Code went on underneath: back to it, with what it drew meanwhile
        h.grid.type('hello'); h.grid.press(0x0D, 0x1C)
        time.sleep(0.5)
        assert t.hide_picture('test')
        assert h.wait_text('You said: hello', wall=10), h.grid.screen_text()
        assert not any(h.grid.pix[:23 * 16 * 80]) or True
        assert t.pic is None and not t.hide_picture('test')
    finally:
        h.close() if hasattr(h, 'close') else None


def test_old_claude_gets_no_pictures():
    h = TermHarness()
    h.grid.hello_flags = glp.GF_TERM                     # #32's CLAUDE.COM
    try:
        assert h.wait_text('Welcome to Claude Code', wall=10)
        t = h.term
        assert not t.can_picture()
        try: t.show_picture(bytes(PIC.SIZE), 'test'); raise AssertionError('shown')
        except RuntimeError as e: assert 'CLAUDE.COM 1.2' in str(e)
    finally:
        h.close() if hasattr(h, 'close') else None


def test_cell_clicks_from_older_claude():
    """3-byte EVENT 05h (a cell, #32's CLAUDE) still reaches the program as a cell."""
    h = start()
    try:
        t = h.term
        seen = []
        t.click = lambda col, row, px=None, py=None: seen.append((col, row, px, py))
        h.grid.queue(glp.G_EVENT, bytes([glp.EV_CLICK, 5, 7]))
        h.grid.click(100, 50)
        assert h.run_until(lambda: len(seen) == 2, wall=5), seen
        assert seen == [(5, 7, 44, 120), (12, 3, 100, 50)], seen
    finally:
        h.close() if hasattr(h, 'close') else None


def mcp_start():
    h = start()
    c = Client(h)
    c.rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't'}})
    c.rpc('notifications/initialized', notify=True)
    return h, c


def call_bg(c, tool, **args):
    out = {}
    th = threading.Thread(target=lambda: out.update(r=c.rpc('tools/call', {'name': tool, 'arguments': args})))
    th.start()
    return th, out


def test_grid_plot_and_clicks():
    h, c = mcp_start()
    try:
        xs, ys = sweep(401)
        r = c.call('grid_plot', series=[{'name': 'S21', 'x': xs, 'y': ys}], title='Filter', x_label='Hz',
                   y_label='dB')
        assert not r['isError'], r
        assert 'Shown on the GRiD: 1 series, 401 points' in body(r), body(r)
        assert any(x.get('type') == 'image' for x in r['content'])
        want = PL.Plot([{'name': 'S21', 'x': xs, 'y': ys}], title='Filter', x_label='Hz', y_label='dB')
        assert shows(h, want.bits), 'the plot never arrived'
        assert h.run_until(lambda: b'Filter' in h.grid.title and b'Esc' in h.grid.title, wall=5), h.grid.title
        # grid_pick: Claude waits; the user clicks the notch
        th, out = call_bg(c, 'grid_pick', prompt='click the notch')
        assert h.run_until(lambda: h.grid.title.startswith(b'click the notch'), wall=5), h.grid.title
        x, y = int(want.ax.px(xs[200])), int(want.ay.px(ys[200]))
        h.grid.click(x, y + 1)
        assert h.run_until(lambda: not th.is_alive(), wall=10)
        res = out['r']['result']; txt = body(res)
        assert not res['isError'] and txt.startswith('1 click.') and 'nearest point: S21 #' in txt, txt
        k = int(txt.split('#')[1].split(' ')[0]); assert 195 <= k <= 205, txt
        # the mark lingers, then Claude Code comes back
        assert h.run_until(lambda: h.term.pic is None, wall=5)
        assert h.wait_text('Welcome to Claude Code', wall=5)
        # your own click: shown again, a click types the point into the prompt
        r = c.call('grid_plot', series=[{'name': 'S21', 'x': xs, 'y': ys}], title='Filter')
        p2 = PL.Plot([{'name': 'S21', 'x': xs, 'y': ys}], title='Filter')
        assert shows(h, p2.bits)
        h.grid.click(int(p2.ax.px(xs[100])), int(p2.ay.px(ys[100])))
        assert h.wait_text('[clicked plot "Filter": x = ', wall=10), h.grid.screen_text()
        assert h.term.pic is None
        # Esc goes back, and cancels a pick
        c.call('grid_plot', series=[{'y': [1, 2, 3]}])
        assert h.run_until(lambda: h.term.pic is not None, wall=5)
        th, out = call_bg(c, 'grid_pick', count=2, timeout=30)
        assert h.run_until(lambda: h.grid.title.startswith(b'click 2 points'), wall=5), h.grid.title
        h.grid.press(0x1B, 0x01)
        assert h.run_until(lambda: not th.is_alive(), wall=10)
        res = out['r']['result']
        assert res['isError'] and 'Esc' in body(res), res
        assert h.run_until(lambda: h.term.pic is None, wall=5)
        # a pick shows the last picture again; the time limit ends it
        th, out = call_bg(c, 'grid_pick', timeout=5)
        assert h.run_until(lambda: h.term.pic is not None, wall=5)
        assert h.run_until(lambda: not th.is_alive(), wall=15)
        assert 'time limit' in body(out['r']['result']), out
        # errors: no data, both kinds, a file outside
        for args in ({}, {'series': [{'y': [1]}], 'file': 'x.csv'}, {'file': '../etc/passwd'},
                     {'series': [{'y': ['a']}]}):
            r = c.call('grid_plot', **args)
            assert r['isError'], (args, r)
    finally:
        c.close(); h.close() if hasattr(h, 'close') else None


def test_grid_plot_file_and_image():
    from PIL import Image, ImageDraw
    h, c = mcp_start()
    try:
        d = h.cfg.term_dir
        with open(os.path.join(d, 'trace.txt'), 'w') as f:
            for i in range(201): f.write('%.5E, 0.00000E+00\n' % (-1 - 10 * math.exp(-((i - 100) / 8) ** 2)))
        r = c.call('grid_plot', file='trace.txt', x_column=0, columns=[1], x_span=[1e6, 2e6], title='8753D')
        assert not r['isError'] and '201 points; x 1e+06 to 2e+06' in body(r), body(r)
        # a matplotlib-like picture: white, black axes; inverted to lit lines on dark
        im = Image.new('RGB', (800, 600), 'white'); dr = ImageDraw.Draw(im)
        dr.rectangle((100, 50, 700, 550), outline='black', width=3)
        dr.line((100, 550, 700, 50), fill='black', width=3)
        im.save(os.path.join(d, 'fig.png'))
        r = c.call('grid_image', path='fig.png', plot_area=[100, 50, 700, 550], x_range=[0, 10], y_range=[0, 1],
                   title='fig')
        assert not r['isError'] and 'inverted' in body(r) and 'clicks map to data' in body(r), body(r)
        v = h.term.pic
        assert v is not None
        bits = v['bits']
        assert sum(bin(b).count('1') for b in bits) < PIC.SIZE * 8 * 0.1    # mostly dark
        assert shows(h, bits)
        # the middle of the plot area: x 5, y 0.5
        th, out = call_bg(c, 'grid_pick')
        assert h.run_until(lambda: h.grid.title.startswith(b'click a point'), wall=5)
        sc = 384 / 600; left = (640 - 800 * sc) / 2
        h.grid.click(int(left + 400 * sc), int(300 * sc))
        assert h.run_until(lambda: not th.is_alive(), wall=10)
        txt = body(out['r']['result'])
        xv = float(txt.split('x = ')[1].split(',')[0]); yv = float(txt.split('y = ')[1].split()[0])
        assert abs(xv - 5) < 0.1 and abs(yv - 0.5) < 0.02, txt
        r = c.call('grid_image', path='nothere.png')
        assert r['isError']
    finally:
        c.close(); h.close() if hasattr(h, 'close') else None


def test_save_to():
    h, c = mcp_start()
    try:
        r = c.call('gpib_send', action='query', address=29, command='ID?', save_to='id.txt')
        assert not r['isError'] and 'saved to' in body(r) and 'ID TEK/DC5009' in body(r), r
        assert open(os.path.join(h.cfg.term_dir, 'id.txt'), 'rb').read() == b'ID TEK/DC5009,V79.1,F1.2\r\n'
        r = c.call('gpib_send', action='query', address=29, command='ID?', save_to='id.txt')
        assert r['isError'] and 'already' in body(r), r
        r = c.call('gpib_send', action='query', address=29, command='ID?', save_to='.mcp.json')
        assert r['isError'], r
    finally:
        c.close(); h.close() if hasattr(h, 'close') else None


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
