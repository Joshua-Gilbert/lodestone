"""Term (CLAUDE /T): pyte screen, CELLS encoder, key map, and end to end with
a stand-in Claude Code (tests/fake_claude.py) in a real pty.

    python3 tests/test_term.py
"""
import os, random, statistics, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pyte
from gridsim import TermHarness
from gridlink import glp, keys as K
from gridlink import termscreen as TS
from gridlink.termscreen import TermScreen, PreFilter, Encoder, apply, glyph


def feed(scr, data):
    pf = PreFilter(lambda: scr.mode)
    st = pyte.ByteStream(scr)
    out, ans = pf.feed(data)
    st.feed(out)
    return ans


def rows(scr):
    return [l.rstrip() for l in scr.text()]


# ---- the screen model -------------------------------------------------------
def test_prefilter():
    scr = TermScreen()
    ans = feed(scr, b'\x1b[>4;2mA\x1b[>0q\x1b[?uB\x1bP+q544e\x1b\\C\x1b[?2026$p\x1b]11;?\x07D')
    assert rows(scr)[0] == 'ABCD', rows(scr)[0]
    assert not scr.buffer[0][0].underscore                     # CSI > 4;2 m is not underline
    assert b'\x1b[?2026;2$y' in ans, ans                       # DECRQM: known, reset
    assert any(a.startswith(b'\x1b]11;rgb:0000') for a in ans), ans
    # a sequence split across reads
    pf = PreFilter(); out1, _ = pf.feed(b'x\x1b[38;5'); out2, _ = pf.feed(b';214my')
    assert out1 == b'x' and out2 == b'\x1b[38;5;214my', (out1, out2)
    pf = PreFilter(); a, _ = pf.feed(b'\x1b]0;tit'); b, _ = pf.feed(b'le\x07z')
    assert a == b'' and b == b'\x1b]0;title\x07z', (a, b)


def test_answers_in_order():
    # a program asks colour, DECRQM, then DA1 (which pyte answers): the
    # answers must come back in that order, or DA1 ends its wait too soon
    scr = TermScreen(); got = []
    scr.write_process_input = lambda d: got.append(d.encode() if isinstance(d, str) else d)
    st = pyte.ByteStream(scr); pf = PreFilter(lambda: scr.mode)
    for kind, b in pf.parts(b'\x1b]11;?\x07\x1b[?2026$p\x1b[c'):
        if kind == 'data': st.feed(b)
        else: got.append(b)
    assert [g[:4] for g in got] == [b'\x1b]11', b'\x1b[?2', b'\x1b[?6'], got
    # SGR with colons (curly underline, colon colours) is turned into what pyte reads
    scr = TermScreen()
    feed(scr, b'\x1b[4:3mU\x1b[0m\x1b[38:2::1:2:3mC')
    assert rows(scr)[0] == 'UC' and scr.buffer[0][0].underscore, rows(scr)[0]


def test_csi_arity():
    """TS.CSI_ARITY is what pyte's handlers take, as measured on TermScreen:
    a newer pyte that changes one fails here, not in a user's Term."""
    for final, name in pyte.Stream.csi.items():
        f = ord(final); most = {}
        for priv in (False, True):
            took = 0
            for n in range(1, 8):
                scr = TermScreen(); scr.write_process_input = lambda t: None
                try: getattr(scr, name)(*([1] * n), **({'private': True} if priv else {})); took = n
                except TypeError: pass
            most[priv] = took
        if most[False] == 7:                                    # any number
            assert f not in TS.CSI_ARITY, (final, name)
            continue
        assert f in TS.CSI_ARITY, (final, name, most)
        n, priv = TS.CSI_ARITY[f]
        assert n == (1 if final == 'K' else most[False]), (final, name, most)   # (K's 2nd is its '?')
        assert priv == (most[True] >= n), (final, name, most)


def test_csi_cut_to_fit():
    """A CSI with more parameters than pyte's handler takes (or a '?' it
    doesn't) used to raise in pyte's feed and kill Term's reader (X94)."""
    pf = PreFilter()
    for got, want in ((b'\x1b[1;2A', b'\x1b[1A'), (b'\x1b[1;2;3H', b'\x1b[1;2H'), (b'\x1b[1;2c', b'\x1b[1c'),
                      (b'\x1b[?6n', b'\x1b[6n'), (b'\x1b[?1;2K', b'\x1b[?1K'), (b'\x1b[0;1K', b'\x1b[0K'),
                      (b'\x1b[?3A', b'\x1b[3A'), (b'\x1b[2;3;4r', b'\x1b[2;3r'),
                      (b'\x1b[5A', b'\x1b[5A'), (b'\x1b[2;3H', b'\x1b[2;3H'), (b'\x1b[H', b'\x1b[H'),
                      (b'\x1b[?25h', b'\x1b[?25h'), (b'\x1b[1;2;3;4m', b'\x1b[1;2;3;4m'),
                      (b'\x1b[2;3J', b'\x1b[2;3J'), (b'\x1b[?1K', b'\x1b[?1K'),
                      (b"\x1b[1;2'", b"\x1b[1'"), (b"\x1b[7'", b"\x1b[7'")):   # (' is HPA's final to pyte)
        out, _ = pf.feed(got)
        assert out == want, (got, out, want)
    scr = TermScreen(); got = []
    scr.write_process_input = lambda d: got.append(d)
    feed(scr, b'a\x1b[1;2Ab\x1b[3;4;5Hc\x1b[1;2cd\x1b[?6ne\x1b[?0;2Kf')
    assert rows(scr)[0] == 'ab' and rows(scr)[2] == '   cdef', rows(scr)[:3]
    assert got == ['\x1b[3;6R'], got                            # ESC[?6n: a cursor report
    feed(scr, b"\x1b[5;1Hxy\x1b[6;2'z")                          # (ESC[6;2' raised in pyte)
    assert rows(scr)[4] == 'xy   z', rows(scr)[4]


def test_alt_screen_and_sync():
    scr = TermScreen()
    feed(scr, b'main text\x1b[?1049h\x1b[Halt screen')
    assert rows(scr)[0] == 'alt screen', rows(scr)[0]
    feed(scr, b'\x1b[?1049l')
    assert rows(scr)[0] == 'main text', rows(scr)[0]
    feed(scr, b'\x1b[?2026h'); assert scr.sync
    feed(scr, b'\x1b[?2026l'); assert not scr.sync


def test_glyphs_and_attributes():
    scr = TermScreen()
    feed(scr, '⏺ ⎿ ✻ ❯ ╭─╮ │ ╰─╯ █ 中x'.encode() + b'\x1b[7mI\x1b[27m\x1b[48;5;22mG\x1b[49m\x1b[4mU')
    tc, ta = scr.cells()
    want = [glp.GL_BULLET, 32, glp.GL_CORNER, 32, glp.GL_SPIN[4], 32, ord('>'), 32, glp.GL_TL, glp.GL_RULE,
            glp.GL_TR, 32, glp.GL_BAR, 32, glp.GL_BL, glp.GL_RULE, glp.GL_BR, 32, 32]
    assert list(tc[0][:19]) == want, list(tc[0][:19])
    assert ta[0][18] == TS.A_INV                                # a full block: an inverse blank
    assert tc[0][20:23] == b'? x', tc[0][20:23]                 # a wide character and its right half
    i = 23
    assert (tc[0][i], ta[0][i]) == (ord('I'), TS.A_INV)
    assert (tc[0][i + 1], ta[0][i + 1]) == (ord('G'), TS.A_INV)   # a coloured background
    assert (tc[0][i + 2], ta[0][i + 2]) == (ord('U'), TS.A_UL)
    assert TS.fold_title('✳ Fix the build') == 'Fix the build'


def test_encoder_fuzz():
    random.seed(7)
    for budget in (glp.STOCK_FRAME_MAX - glp.OVERHEAD, glp.PATCHED_FRAME_MAX - glp.OVERHEAD):
        enc = Encoder(); gc, ga = TS._blank_rows()
        scr = TermScreen(); st = pyte.ByteStream(scr)
        for step in range(250):
            r = random.random()
            if r < 0.3:
                st.feed(('\x1b[24;1H\r\n%s' % ('w%d ' % step) * random.randint(1, 15)).encode())
            elif r < 0.5:
                st.feed(('\x1b[%d;%dH\x1b[7m%s\x1b[0m' % (random.randint(1, 24), random.randint(1, 70),
                                                           'x' * random.randint(1, 10))).encode())
            elif r < 0.6:
                st.feed(b'\x1b[2J')
            elif r < 0.8:
                st.feed(('\x1b[%dA\x1b[2K── %d ✻' % (random.randint(0, 5), step)).encode())
            else:
                st.feed(('\x1b[%d;1H\x1b[4m%s\x1b[24m' % (random.randint(1, 24), '-' * 80)).encode())
            tc, ta = scr.cells(); cur = (scr.cursor.y, scr.cursor.x, scr.cursor.hidden)
            for _ in range(200):
                p, more = enc.make(tc, ta, cur, budget)
                if p is None: break
                assert len(p) <= budget
                apply(p, gc, ga)
                if random.random() < 0.5: enc.delivered()
                else:                                       # an answer resent: the GRiD sees it once
                    enc.delivered()
                if not more: break
            assert [bytes(x) for x in gc] == [bytes(x) for x in tc], (budget, step)
            assert [bytes(x) for x in ga] == [bytes(x) for x in ta], (budget, step)


def test_encoder_scroll_and_fill():
    enc = Encoder(); gc, ga = TS._blank_rows()
    scr = TermScreen(); st = pyte.ByteStream(scr)
    st.feed(b'\r\n'.join(b'line %02d ' % i + b'abcdefgh' * 8 for i in range(24)))
    tc, ta = scr.cells(); cur = (scr.cursor.y, scr.cursor.x, True)
    while True:
        p, more = enc.make(tc, ta, cur, 246)
        apply(p, gc, ga); enc.delivered()
        if not more: break
    st.feed(b'\r\nline 24 ' + b'abcdefgh' * 8)                # the screen scrolls by one
    tc, ta = scr.cells()
    p, more = enc.make(tc, ta, cur, 246)
    assert p[3] == TS.OP_SCROLL and not more, p[:8]
    assert len(p) < 100, len(p)                                 # not a whole screen
    apply(p, gc, ga); enc.delivered()
    assert [bytes(x) for x in gc] == [bytes(x) for x in tc]
    st.feed(b'\x1b[5;1H' + '─'.encode() * 70)
    tc, ta = scr.cells()
    p, _ = enc.make(tc, ta, cur, 246)
    assert len(p) == 3 + 4, p                                   # one fill


def test_encoder_resume():
    """CLAUDE /R's console keeps its screen between pop-ups and says HELLO
    with its sum: the encoder goes on from it when it is the screen of the
    last frame or the one before; anything else starts from a clear screen.
    The sum is the Fletcher sum (from 2026-10-29), or a CRC-16 from an older
    console, whose HELLO came with the CRC (resume's fl False)."""
    enc = Encoder(); gc, ga = TS._blank_rows()
    scr = TermScreen(); st = pyte.ByteStream(scr)
    grid = {}
    def send(apply_it=True, deliver=True):
        tc, ta = scr.cells(); cur = (scr.cursor.y, scr.cursor.x, bool(scr.cursor.hidden))
        p, more = enc.make(tc, ta, cur, 246)
        if p is not None and apply_it:
            apply(p, gc, ga); grid['cur'] = (p[1], p[2], bool(p[0] & 2))
        if deliver: enc.delivered()
        return p, more
    def crc(fl=True): return '%04X' % TS.screen_sum((gc, ga), grid['cur'], fl)
    st.feed(b'\r\n'.join(b'row %02d ' % i + b'x' * 60 for i in range(20)))
    while send()[1]: pass
    assert enc.resume(crc()) and send()[0] is None              # all delivered: nothing to send
    st.feed(b'\x1b[3;1Hchanged')
    send(deliver=False)                                         # the GRiD has it, the Pi doesn't know
    assert enc.resume(crc()) and send()[0] is None
    st.feed(b'\x1b[5;1Hagain')
    send(apply_it=False, deliver=False)                         # lost on the way: the screen before it
    assert enc.resume(crc())
    p, _ = send()
    assert p is not None and not p[0] & TS.F_CLEAR              # the change again, no clear
    tc, ta = scr.cells()
    assert [bytes(x) for x in gc] == [bytes(x) for x in tc] and [bytes(x) for x in ga] == [bytes(x) for x in ta]
    for bad in (None, '', 'zz', '%04X' % ((int(crc(), 16) + 1) & 0xFFFF)):
        assert not enc.resume(bad), bad
    # the bytes RCON.ASM's screen_sum takes, and an older console's CRC-16 of them
    data = b''.join(bytes(x for p in zip(gc[r], ga[r]) for x in p) for r in range(TS.ROWS))
    data += bytes([grid['cur'][0], grid['cur'][1], int(grid['cur'][2])])
    assert int(crc(), 16) == glp.fletcher16(data) and int(crc(False), 16) == glp.crc16(data)
    assert crc() != crc(False)
    assert not enc.resume(crc(False)) and not enc.resume(crc(), False)  # (each by its own HELLO's check)
    assert enc.resume(crc(False), False) and send()[0] is None          # an older console: the CRC
    assert enc.resume(crc()) and send()[0] is None
    enc.reset()
    assert not enc.resume(crc())                                # nothing sent since: unknown


def test_keymap():
    T = lambda ax, app=False: K.term_bytes(ax & 0xFF, ax >> 8, app)
    assert T(0x011B) == b'\x1b' and T(0x2E03) == b'\x03' and T(0x0F00) == b'\x1b[Z'
    assert T(0x4800) == b'\x1b[A' and T(0x48E0) == b'\x1b[A' and T(0x4800, True) == b'\x1bOA'
    assert T(0x1C00) == b'\x1b\r' and T(0x1C0A) == b'\x1b\r' and T(0x1C0D) == b'\r' and T(0xE00D) == b'\r'
    assert T(0x0E08) == b'\x7f' and T(0x5300) == b'\x1b[3~' and T(0x4900) == b'\x1b[5~'
    assert T(0x1E00) == b'\x1ba' and T(0x2B00) == b'\x1b\\' and T(0x7800) == b'\x1b1'
    assert T(0x1312) == b'\x12' and T(0x3B00) == b'\x1bOP'
    assert T(0x2308) == b'\x08' and T(0x4700, True) == b'\x1bOH' and T(0x4F00) == b'\x1b[F'
    assert K.term_keys(bytes([0x68, 0x23, 0x69, 0x17])) == b'hi'


# ---- end to end -------------------------------------------------------------
def start(**kw):
    h = TermHarness(**kw)
    assert h.wait_text('Welcome to Claude Code', wall=10), ('no welcome', h.log, h.grid.screen_text())
    assert h.settle(), 'not in step'
    return h


def check(h):
    assert not h.nano.violations, h.nano.violations
    errs = [l for l in h.log if 'Traceback' in str(l) or 'error' in str(l).lower()]
    assert not errs, errs
    assert h.grid.stats['fail'] == 0, h.grid.stats


def enter(h): h.grid.press(0x0D, 0x1C)


def test_term_session():
    h = start()
    try:
        assert 'DA ok' in ''.join(h.grid.screen_text())      # pyte answered the program's DA query
        assert h.grid.title == b'Claude Code', h.grid.title
        assert h.grid.stats['clears'] == 1
        h.grid.type('hello'); enter(h)
        assert h.wait_text('You said: hello'), h.grid.screen_text()
        assert h.settle()
        h.grid.type('big'); enter(h)
        assert h.wait_text('line 59'), h.grid.screen_text()
        assert h.settle()
        h.grid.type('diff'); enter(h)
        assert h.wait_text('int rate = 5'), h.grid.screen_text()
        assert h.settle()
        r = [i for i, l in enumerate(h.grid.screen_text()) if 'int rate = 5' in l][0]
        assert h.grid.attrs[r][20] & TS.A_INV                   # the green line is inverse
        check(h)
    finally:
        h.close()


def test_term_dialog_and_keys():
    h = start()
    try:
        h.grid.type('run dir'); enter(h)
        assert h.wait_text('Do you want to proceed?'), h.grid.screen_text()
        h.grid.press(0, 0x50)                                   # Down: "Yes, and don't ask again"
        assert h.run_until(lambda: any('\x83' in l or '> 2.' in l for l in h.grid.screen_text()), 5)
        enter(h)
        assert h.wait_text('ran dir'), h.grid.screen_text()
        h.grid.press(0, 0x0F)                                   # Shift-Tab
        assert h.wait_text('accept edits on'), h.grid.screen_text()
        h.grid.type('two'); h.grid.press(0, 0x1C); h.grid.type('lines')   # CODE-Return
        assert h.wait_text('  lines'), h.grid.screen_text()
        h.grid.press(0x1B, 0x01)
        h.grid.press(0x03, 0x2E)                                # Ctrl-C clears the input
        assert h.run_until(lambda: not any('lines' in l for l in h.grid.screen_text()), 5)
        assert h.settle()
        check(h)
    finally:
        h.close()


def test_term_alt_screen_and_repaint():
    h = start()
    try:
        before = h.grid.screen_text()
        h.grid.type('/pager'); enter(h)
        assert h.wait_text('PAGER: alternate screen'), h.grid.screen_text()
        h.grid.type('q')
        assert h.run_until(lambda: not any('PAGER' in l for l in h.grid.screen_text()), 5)
        assert h.settle()
        assert any('/pager' in l for l in h.grid.screen_text())
        # CODE-R on the GRiD: EVENT 03h, the Pi repaints from a clear screen
        clears = h.grid.stats['clears']
        h.grid.cells[3][:] = b'X' * 80                          # the GRiD's screen got spoilt
        h.grid.queue(glp.G_EVENT, bytes([glp.EV_REPAINT]))
        assert h.run_until(lambda: h.grid.stats['clears'] > clears, 5)
        assert h.settle()
        check(h)
    finally:
        h.close()


def test_term_stock_firmware_and_noise():
    h = start(patched=False)
    try:
        h.transport.corrupt_every = 5
        h.grid.corrupt_rx_every = 7
        h.grid.type('slow'); enter(h)
        assert h.wait_text('keeps turning below it', wall=15), h.grid.screen_text()
        assert h.run_until(lambda: not h.term.screen.sync and h.synced(), 10)
        assert h.settle(wall=15)
        assert h.grid.stats['bad_rx'] > 0 and h.grid.stats['nak'] > 0, h.grid.stats
        assert not h.nano.violations
    finally:
        h.close()


def test_term_restart_and_reconnect():
    h = start()
    try:
        h.grid.type('/exit'); enter(h)
        assert h.wait_text('exited (code 0)', wall=10), h.grid.screen_text()
        enter(h)
        assert h.wait_text('Welcome to Claude Code', wall=10), h.grid.screen_text()
        assert h.settle()
        # the GRiD restarts the link (HELLO): a full repaint, same program
        pid = h.term.child.pid; clears = h.grid.stats['clears']
        h.grid.fail()
        assert h.run_until(lambda: h.grid.stats['clears'] > clears, 10), h.grid.stats
        assert h.settle()
        assert h.term.child.pid == pid
    finally:
        h.close()


def test_no_api_key_for_claude_code():
    os.environ['ANTHROPIC_API_KEY'] = 'sk-test-not-for-claude-code'
    try:
        h = start()
        try:
            assert 'api key: none' in ''.join(h.grid.screen_text()), h.grid.screen_text()
        finally:
            h.close()
    finally:
        del os.environ['ANTHROPIC_API_KEY']


def test_lone_esc_written_alone():
    h = start()
    try:
        writes = []
        h.term._write = writes.append
        h.term.keys(bytes([0x1B, 0x01, 0x1B, 0x01, 0x61, 0x1E]))          # Esc Esc a
        assert writes == [b'\x1b', b'\x1b', b'a'], writes
    finally:
        h.close()


def child(code):
    """A program for the pty (TermHarness's command=): code in a file of its own."""
    import tempfile
    d = tempfile.mkdtemp(prefix='gridlink-child-'); p = os.path.join(d, 'child.py')
    with open(p, 'w') as f: f.write('import os, select, sys, time, tty\ntty.setraw(0)\n' + code)
    return '%s %s' % (sys.executable, p)


ODD_CSI = r'''
os.write(1, b'before\r\n\x1b[1;2Aodd\r\n\x1b[1;2;3H\x1b[1;2c\x1b[?6n')
got = b''; end = time.time() + 5
while not got.endswith(b'R') and time.time() < end:
    if select.select([0], [], [], 0.5)[0]: got += os.read(0, 64)
os.write(1, b'\x1b[5;1Hanswer %s\r\n' % got[1:])
time.sleep(0.3)
os.write(1, b'still drawing\r\n')
time.sleep(30)
'''


def test_term_odd_csi():
    """A program that writes CSIs with more parameters than pyte takes
    (ESC[1;2A, ESC[1;2;3H, ESC[1;2c, ESC[?6n): Term goes on (X94)."""
    h = TermHarness(command=child(ODD_CSI))
    try:
        assert h.wait_text('still drawing'), (h.log, h.grid.screen_text())
        scr = h.grid.screen_text()
        assert any('answer [1;2R' in l for l in scr), scr       # ESC[?6n answered as ESC[6n, at row 1 col 2
        assert h.term.reader.is_alive() and h.term.child is not None
        assert not [l for l in h.log if 'pyte' in str(l) or 'reading from' in str(l)], h.log
        assert h.settle()
        # and pyte raising on something no filter knows loses that data, not the reader
        st = h.term.stream
        class Bad:
            def feed(s, b): raise TypeError('test')
        h.term.stream = Bad()
        h.term.feed(b'x' * 50 + b'END'); h.term.feed(b'y')
        h.term.stream = st
        h.term.feed(b'\x1b[7;1Hagain\r\n')
        assert h.wait_text('again'), h.grid.screen_text()
        h.term.stream = Bad(); h.term.feed(b'z')               # (a redraw with it again: not logged again)
        h.term.stream = st
        said = [str(l) for l in h.log if 'term: pyte' in str(l)]
        assert len(said) == 1 and '53 bytes' in said[0] and "xxEND'" in said[0], said
        assert h.term.pyte_bad == 2, h.term.pyte_bad            # (counted, for the next line said)
    finally:
        h.close()


WAITS = r'''
import signal
DEAF = %r
if DEAF: signal.signal(signal.SIGTERM, signal.SIG_IGN)
os.write(1, b'ready\r\n')
time.sleep(60)
'''


def test_reader_error_stops_the_program():
    """An error in Term's reader itself: the program is stopped (SIGTERM,
    then a kill after 3 s for one that ignores it), not left running with
    nothing reading it (X94)."""
    for deaf in (False, True):
        h = TermHarness(command=child(WAITS % deaf))
        try:
            assert h.wait_text('ready'), (h.log, h.grid.screen_text())
            kid = h.term.child
            def boom(*a, **k): raise RuntimeError('test')
            t0 = time.time()
            h.term._send_title = boom                         # (called in the reader's loop)
            h.term.reader.join(10)
            del h.term._send_title
            assert not h.term.reader.is_alive() and kid.poll() is not None, (deaf, h.log)
            assert (time.time() - t0 >= 2.5) == deaf, (deaf, time.time() - t0)
            assert any('reading from' in str(l) and 'stopping it' in str(l) for l in h.log), h.log
            assert h.term.child is None and h.term.fd is None, (h.term.child, h.term.fd)
        finally:
            h.close()


STOPS_READING = r'''
import hashlib
go = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'go')
os.write(1, b'ready\r\n')
while not os.path.exists(go): time.sleep(0.05)        # (the test says when to read again)
got = b''
while select.select([0], [], [], 1.0)[0]: got += os.read(0, 65536)
d = got.rstrip(b'abc')
os.write(1, b'got %d %s %s\r\n' % (len(d), hashlib.md5(d).hexdigest().encode(), got[len(d):] or b'-'))
time.sleep(30)
'''


def test_term_program_stops_reading():
    """A raw-mode program that stops reading its input: the pty fills, the
    rest waits in Term's queue and the link goes on; past WQ_MAX keys are
    dropped (said once, and every key after until the program reads again,
    so none arrives ahead of a dropped one), and what was kept arrives in
    order when the program reads again (X123).  Before, the 20,481st byte
    blocked the link."""
    import hashlib, threading
    from gridlink import term as T
    cmd = child(STOPS_READING); go = os.path.join(os.path.dirname(cmd.split()[1]), 'go')
    h = TermHarness(command=cmd)
    try:
        assert h.wait_text('ready'), (h.log, h.grid.screen_text())
        sent = b''.join(bytes([48 + i % 10]) * 1024 for i in range(120))
        def writes():
            for i in range(0, len(sent), 1024): h.term._write(sent[i:i + 1024])
            h.term._write(b'Z')                                 # (it would fit: dropped all the same)
        w = threading.Thread(target=writes, daemon=True); w.start(); w.join(5)
        assert not w.is_alive(), 'a write blocked'
        assert 0 < h.term.wq_bytes <= T.WQ_MAX, h.term.wq_bytes
        assert len([l for l in h.log if 'not reading' in str(l)]) == 1, h.log
        h.grid.type('abc')                                      # keys through the link: never held
        assert h.settle(), h.log
        open(go, 'w').close()
        assert h.wait_text('got '), (h.log, h.grid.screen_text())
        line = [l for l in h.grid.screen_text() if 'got ' in l][0].split()
        n, md5, tail = int(line[1]), line[2], line[3]
        assert 20000 <= n < len(sent) and md5 == hashlib.md5(sent[:n]).hexdigest(), (n, md5)
        assert tail == '-', tail                                # ('abc' came while it was dropping)
        assert h.term.wq_bytes == 0 and not h.term.wq
        again = [str(l) for l in h.log if 'reading again' in str(l)]
        assert len(again) == 1 and '%d bytes of keys were dropped' % (len(sent) + 1 + 3 - n) in again[0], \
            (again, len(sent) + 4 - n)
    finally:
        h.close()


def bare(fd):
    """A TermSession with only its write queue, writing to fd."""
    import threading
    from gridlink import term as T
    class S(T.TermSession):
        def __init__(s): pass
    s = S(); s.said = []; s.log = s.said.append; s.name = 'x'; s.stats = dict(pty_out=0, pty_in=0)
    s.wlock = threading.Lock(); s.wq = T.deque(); s._wq_clear(); s.wake = None; s.fd = fd
    return s


def fill(w):
    while True:
        try: os.write(w, b'.' * 4096)
        except BlockingIOError: return


def full_pipe():
    r, w = os.pipe()
    os.set_blocking(w, False)
    fill(w)
    return r, w


def drain(r):
    while select_ready(r): os.read(r, 65536)


def test_esc_gap_kept_when_queued():
    """Keys queued behind a full pty keep each lone Esc's own write and its gap."""
    from gridlink import term as T
    r, w = full_pipe()
    s = bare(w)
    try:
        s._write(b'\x1b'); s._gap(); s._write(b'a')
        assert [c[0] for c in s.wq] == [b'\x1b', b'a'] and s.wq[0][1], list(s.wq)
        drain(r)                                                # the program reads again
        assert s._flush(w)[0] == [] and [c[0] for c in s.wq] == [b'a']
        wl, wait = s._flush(w)                                  # the Esc's gap: 'a' waits
        assert wl == [] and 0 < wait <= T.ESC_GAP and s.wq, (wl, wait)
        time.sleep(wait + 0.005)
        assert s._flush(w) == ([], 0.5) and not s.wq
    finally:
        os.close(r); os.close(w)


def test_keys_esc_gap_without_waiting():
    """keys() never waits: each lone Esc followed by more keys goes in a
    write of its own, and what follows it waits in the queue for ESC_GAP
    (Esc a; Esc Esc a, a gap after each Esc). On a clock of the test's own."""
    import types
    from gridlink import term as T
    clk, slept = [100.0], []
    was = T.time
    T.time = types.SimpleNamespace(monotonic=lambda: clk[0], sleep=slept.append)
    try:
        for body, writes in ((b'\x1b\x01a\x1e', [b'\x1b', b'a']),
                             (b'\x1b\x01\x1b\x01a\x1e', [b'\x1b', b'\x1b', b'a'])):
            r, w = os.pipe()
            os.set_blocking(w, False)
            s = bare(w); s.stats['keys'] = 0; s.pic = None; s.child = object()
            s.screen = types.SimpleNamespace(app_cursor=False)
            try:
                s.keys(body)
                assert slept == [], slept                        # the link's thread didn't wait
                got = [os.read(r, 100)]                          # the first Esc, alone
                for _ in writes[1:]:
                    wl, wait = s._flush(w)                       # the Esc's gap: the rest waits
                    assert wl == [] and abs(wait - T.ESC_GAP) < 1e-9 and s.wq, (body, wl, wait, list(s.wq))
                    assert not select_ready(r), body
                    clk[0] += T.ESC_GAP
                    s._flush(w); got.append(os.read(r, 100))
                assert got == writes and not s.wq, (body, got, list(s.wq))
            finally:
                os.close(r); os.close(w)
    finally:
        T.time = was


def test_queue_drops_till_empty():
    """Past WQ_MAX: that write and every one after are dropped till the
    queue empties, even one that would fit; said once, then the count when
    it reads again; and the next time it fills it is said again (X123)."""
    from gridlink import term as T
    r, w = full_pipe()
    s = bare(w); was = T.WQ_MAX; T.WQ_MAX = 10
    try:
        s._write(b'12345678'); s._write(b'abc'); s._write(b'x')
        assert [c[0] for c in s.wq] == [b'12345678'] and s.wq_dropped == 4, (list(s.wq), s.wq_dropped)
        assert s._flush(w) == ([w], 0.5) and len(s.said) == 1 and 'not reading' in s.said[0], s.said
        drain(r)
        assert s._flush(w) == ([], 0.5) and not s.wq and s.wq_dropped == 0
        assert len(s.said) == 2 and 'x reading again; 4 bytes of keys were dropped' in s.said[1], s.said
        s._write(b'y'); drain(r)                                # (straight to the pipe)
        fill(w)
        s._write(b'12345678'); s._write(b'abc')
        assert len(s.said) == 3 and 'not reading' in s.said[2], s.said
    finally:
        T.WQ_MAX = was; os.close(r); os.close(w)


class Kid:
    """A stand-in child for _read: wait() blocks till terminate()."""
    def __init__(s):
        import threading
        s.ev = threading.Event(); s.pid = 1
    def wait(s, timeout=None):
        s.ev.wait(timeout); return 0
    def terminate(s): s.ev.set()
    kill = terminate
    def poll(s): return 0 if s.ev.is_set() else None


def reader(s, fd):
    """_read on fd for session s (bare()), in a thread, as _start runs it."""
    import threading
    wake_r, wake_w = os.pipe()
    os.set_blocking(wake_r, False); os.set_blocking(wake_w, False)
    s.wake = wake_w; s.child = Kid(); s.got = []
    s.feed = s.got.append; s._send_title = lambda: None; s.hide_picture = lambda why: None
    s._message = lambda text: None; s.web = False
    t = threading.Thread(target=s._read, args=(fd, s.child, wake_r, wake_w), daemon=True)
    t.start()
    return t


def test_reader_wakes_for_queued_keys():
    """A key queued while the reader sits in select (here: behind a lone
    Esc's gap) is written after the gap, not at select's 0.5 s time-out:
    the queue's start wakes the reader (X123)."""
    import socket
    a, b = socket.socketpair()
    a.setblocking(False); fd = a.detach()                  # (_read closes it)
    s = bare(fd)
    t = reader(s, fd)
    try:
        time.sleep(0.1)                                         # (the reader is in its select)
        t0 = time.monotonic()
        s._write(b'\x1b'); s._gap(); s._write(b'a')
        b.settimeout(2); got = b''
        while len(got) < 2: got += b.recv(16)
        dt = time.monotonic() - t0
        assert got == b'\x1ba' and dt < 0.25, (got, dt)
    finally:
        s.child.terminate(); b.close(); t.join(5)               # (EOF: the reader ends)
    assert not t.is_alive() and s.fd is None


def test_old_reader_leaves_a_new_session():
    """The program started again before the old reader has finished (its
    child gone, the new one running): the old reader's end leaves the new
    pty, wake pipe, queue and child alone (X123)."""
    import socket
    a, b = socket.socketpair()
    a.setblocking(False); fd = a.detach()
    s = bare(fd)
    t = reader(s, fd); old = s.child
    c, d = socket.socketpair()
    try:
        new = Kid()
        with s.wlock: s.fd = c.fileno(); s.wake = 99; s.wq.append([b'k', False]); s.wq_bytes = 1
        s.child = new
        old.terminate(); b.close(); t.join(5)
        assert not t.is_alive()
        assert s.fd == c.fileno() and s.wake == 99 and s.wq_bytes == 1 and s.child is new, \
            (s.fd, s.wake, s.wq_bytes, s.child)
    finally:
        c.close(); d.close()
    # started again while the old reader says its program exited (a Return then)
    a, b = socket.socketpair()
    a.setblocking(False); fd = a.detach()
    s = bare(fd)
    t = reader(s, fd); old = s.child; new = Kid()
    def restart(text):                                     # (the old child still there: it goes last)
        assert s.child is old, s.child
        s.child = new; s.exited = None
    s._message = restart
    old.terminate(); b.close(); t.join(5)
    assert not t.is_alive() and s.child is new and s.exited is None, (s.child, s.exited)


def test_reader_no_data_is_not_the_end():
    """A read the pty has no data for (EAGAIN: the master is non-blocking)
    is not the program's end: the reader goes on (X123)."""
    import socket
    from gridlink import term as T
    a, b = socket.socketpair()
    a.setblocking(False); fd = a.detach()                  # (_read closes it)
    s = bare(fd)
    real = os.read; once = []
    class OS:
        def __getattr__(o, n): return getattr(os, n)
        def read(o, f, n):
            if f == fd and not once: once.append(1); raise BlockingIOError(11, 'EAGAIN')
            return real(f, n)
    T.os = OS()
    t = None
    try:
        t = reader(s, fd)
        b.sendall(b'hello')
        end = time.time() + 3
        while not s.got and time.time() < end: time.sleep(0.02)
        assert once and s.got == [b'hello'] and t.is_alive(), (once, s.got, t.is_alive())
    finally:
        T.os = os; s.child.terminate(); b.close()               # (EOF: the reader ends)
        if t is not None: t.join(5)
    assert not t.is_alive() and s.fd is None



def test_restart_closes_its_fds():
    """Each start opens a pty and a wake-up pipe; the program's end closes
    all three, so starting it again and again leaks none (X123)."""
    h = TermHarness(command=child("os.write(1, b'ready\\r\\n')\ntime.sleep(0.2)\n"))
    try:
        def fds(): return len(os.listdir('/proc/self/fd'))
        assert h.wait_text('ready'), (h.log, h.grid.screen_text())
        h.term.reader.join(5)
        n0 = fds()
        for i in range(5):
            assert h.term.start(), h.log
            h.term.reader.join(5)
            assert not h.term.reader.is_alive()
        assert fds() == n0, (n0, fds())
    finally:
        h.close()


def select_ready(fd):
    import select
    return bool(select.select([fd], [], [], 0)[0])


def test_switch_quiesces_chat():
    import threading
    from gridlink.router import Router
    from gridlink.link import Link
    from gridlink.config import Config

    class Agent:                                    # a chat turn still running
        def __init__(s, port):
            s.port = port; s.busy = True; s.interrupt = threading.Event()
            s.ask_cv = threading.Condition(); s.seen = []
            class G:
                n = 0
                def on_restart(g): g.n += 1
            s.grid = G()
        def on_message(s, t, b): s.seen.append(t)

    class T:
        frame_limit = 254
        def answer(s, f): pass
    cfg = Config(); cfg.api_key = 'k'; cfg.env_key = lambda: False
    import tempfile; cfg.term_dir = tempfile.mkdtemp(); cfg.term_command = 'true'
    cfg.term_socket = os.path.join(cfg.term_dir, 's.sock')
    R = Router(cfg, log=lambda *a: None, make_agent=lambda port: Agent(port))
    L = Link(T(), R.on_message, log=lambda *a: None); R.attach(L)
    hello = lambda app: bytes([1, glp.GF_TERM, 0, 4, 80, 20]) + ('app=%s\n' % app).encode()
    R.on_message(glp.G_HELLO, hello('chat'))
    ag = R.agent
    ag.port.send(glp.P_TEXT, b'before'); assert L.outq and L.outq[-1][1] == b'before'
    L.outq.clear()
    R.on_message(glp.G_HELLO, hello('term'))
    try:
        assert ag.interrupt.is_set() and ag.grid.n == 1
        n = len(L.outq)
        ag.port.send(glp.P_TEXT, b'after')          # the old turn's output: dropped
        assert len(L.outq) == n and all(b != b'after' for _, b in L.outq)
    finally:
        R.term.stop()


def test_router():
    from gridsim import TermHarness as TH
    h = TH(app=None, cfg_app='auto', key=False)                 # no key, no /T: Term anyway
    try:
        assert h.wait_text('Welcome to Claude Code', wall=10)
    finally:
        h.close()
    h = TH(app=None, key=False)                                 # an older CLAUDE: never Term
    h.grid.hello_flags = 0
    try:
        assert h.run_until(lambda: b'CLAUDE /T' in bytes(h.grid.screen), 10), bytes(h.grid.screen)
        assert not h.grid.term and h.router.term is None
    finally:
        h.close()
    h = TH(app='chat', key=False)                               # chat asked for, no key
    try:
        assert h.run_until(lambda: b'CLAUDE /T' in bytes(h.grid.screen), 10), bytes(h.grid.screen)
        assert not h.grid.term and h.router.term is None
    finally:
        h.close()


def test_click_only_when_asked():
    """EVENT 05h (a click, CLAUDE /W): passed on only to a program that
    turned mouse reports on.  The stand-in Claude Code doesn't."""
    h = start()
    try:
        n = h.router.term.stats['pty_out']
        h.grid.txq.append([glp.G_EVENT, bytes([glp.EV_CLICK, 3, 4]), 0])
        assert h.settle()
        assert h.router.term.stats['pty_out'] == n, 'a click reached a program that asked for none'
        t = h.router.term
        for mode, want in (((1000,), b'\x1b[M\x20\x24\x25\x1b[M\x23\x24\x25'),
                           ((1000, 1006), b'\x1b[<0;4;5M\x1b[<0;4;5m')):
            got = []
            w = t._write; t._write = got.append
            t.screen.mode.update(m << 5 for m in mode)
            t.click(3, 4); t.click(3, 24)                                    # (row 24 is CLAUDE's band: not)
            t._write = w; t.screen.mode.difference_update(m << 5 for m in mode)
            assert got == [want], (mode, got)
        check(h)
    finally:
        h.close()


def test_echo_latency():
    """Spike 1 (simulated): key -> KEYS -> pty -> echo -> pyte -> CELLS -> GRiD.
    The clock counts the modelled link and the Pi's real time."""
    out = {}
    for patched in (True, False):
        h = start(patched=patched)
        try:
            lat = []; typed = ''
            for ch in 'latency check':
                h.run_for(0.05)
                t0 = h.grid.clock()
                h.grid.type(ch); typed += ch
                want = '> ' + typed + ' '
                assert h.run_until(lambda: any(want in l for l in h.grid.screen_text()), 5), typed
                lat.append((h.grid.clock() - t0) / 1000.0)
            out[patched] = (statistics.median(lat), max(lat))
        finally:
            h.close()
    print('     echo latency (ms, median / worst): patched %.0f / %.0f, stock %.0f / %.0f'
          % (out[True] + out[False]))
    assert out[True][0] < 150 and out[False][0] < 150, out


def test_hold_waits_till_ready_at():
    """A held answer sleeps till the source's ready_at (Term's: its echo settled), not in 5 ms looks; a source
    that can't say, or has nothing timed (None), is looked at every 5 ms as before; never a busy loop."""
    from gridlink.link import Link
    class Src:
        def __init__(s, at): s.at = at
        def ready_at(s): return s.at
    L = Link.__new__(Link)
    L.source = None
    assert L._source_wait(1.0) == 1.0
    L.source = object(); assert L._source_wait(1.0) == 0.005
    L.source = Src(None); assert L._source_wait(1.0) == 0.005
    L.source = Src(time.monotonic() + 0.003); w = L._source_wait(1.0)
    assert 0.002 < w <= 0.003, w
    L.source = Src(time.monotonic() + 5); assert L._source_wait(0.06) == 0.06       # (the hold ends first)
    L.source = Src(time.monotonic() - 1); assert L._source_wait(1.0) == 0.0005      # (due: look again soon)
    # Term's own: nothing to draw, None; drawn soon after its last pty byte, SETTLE after it
    from gridlink import term as TM
    t = TM.TermSession.__new__(TM.TermSession)
    import threading
    t.lock = threading.RLock(); t.away = False; t.pic = None; t.dirty = False
    t.screen = TermScreen()
    assert t.ready_at() is None
    now = time.monotonic()
    t.dirty = True; t.last_byte = now; t.first_dirty = now
    assert t.ready_at() == now + TM.SETTLE and not t.ready()
    t.first_dirty = now - TM.MAX_WAIT + 0.001                                        # (MAX_WAIT comes first)
    assert t.ready_at() == t.first_dirty + TM.MAX_WAIT


def test_resident_tools():
    """Resident Claude's console: grid_program and grid_type, then the tools
    for what its HELLO's ops= lists (files, gpib); the rest say why not."""
    from types import SimpleNamespace
    from gridlink.term import TermSession as T
    link = SimpleNamespace(last_rx=time.monotonic())
    def why(hello, tool):
        s = SimpleNamespace(link=link, hello=hello, away=False, PAUSED_TOOLS=T.PAUSED_TOOLS, OPS_TOOLS=T.OPS_TOOLS,
                            RESIDENT=T.RESIDENT, AWAY=T.AWAY, NOT_PAUSED=T.NOT_PAUSED)
        link.source = s
        s.resident = lambda: T.resident(s)
        s.paused_tools = lambda: T.paused_tools(s)
        return T.why_not(s, tool)
    old = {'app': 'resident', 'prog': 'TM5000G.EXE'}                 # (CLAUDE 1.8's console: no ops=)
    new = dict(old, ops='files,gpib')
    for tool in ('grid_program', 'grid_type'):
        assert why(old, tool) is None and why(new, tool) is None, tool
    for tool in ('grid_files', 'grid_change_files', 'gpib_read', 'gpib_measure', 'gpib_send'):
        w = why(old, tool)
        assert w and 'TM5000G.EXE' in w and 'grid_program, grid_type work' in w, (tool, w)
        assert why(new, tool) is None, tool
    assert why(dict(old, ops='gpib'), 'gpib_send') is None and why(dict(old, ops='gpib'), 'grid_files')
    for tool in ('grid_command', 'grid_info', 'grid_screen', 'grid_plot'):
        w = why(new, tool)
        assert w and 'grid_files, grid_change_files, gpib_read, gpib_measure, gpib_send work' in w, (tool, w)
    assert why({'app': 'term'}, 'grid_files') is None and why({'app': 'term'}, 'grid_type')
    from gridlink.grid import is_device                 # (Lodestone's GPIBnn devices too)
    assert is_device('A:\\GPIB7') and is_device('A:\\X\\GPIB07.TXT') and is_device('A:\\X\\CON.TXT')
    assert not is_device('A:\\GPIB123') and not is_device('A:\\GPIBX') and not is_device('A:\\GPIB.TXT')


def test_resident_quads():
    # CLAUDE 1.12: resident Claude's console says GF_QUAD too, and gets the block elements as CLAUDE.COM does
    from gridlink.router import Router
    from gridlink.link import Link
    from gridlink.config import Config
    from gridlink.termscreen import glyph

    class T:
        frame_limit = 254
        def answer(s, f): pass
    cfg = Config(); cfg.api_key = 'k'; cfg.env_key = lambda: False
    import tempfile; cfg.term_dir = tempfile.mkdtemp(); cfg.term_command = 'true'
    cfg.term_socket = os.path.join(cfg.term_dir, 's.sock')
    R = Router(cfg, log=lambda *a: None)
    L = Link(T(), R.on_message, log=lambda *a: None); R.attach(L)
    hello = lambda fl, app: bytes([1, glp.GF_TERM | fl, 0, 4, 80, 24]) + ('app=%s\n' % app).encode()
    eyes = (glp.GL_QUADS['▛'], False)
    try:
        R.on_message(glp.G_HELLO, hello(glp.GF_QUAD, 'resident'))
        assert R.app == 'term' and R.term.resident() and R.term.screen.quads
        assert glyph('▛', R.term.screen.quads) == eyes
        R.on_message(glp.G_HELLO, hello(0, 'resident'))             # (an older console, 1.11: blanks)
        assert not R.term.screen.quads and glyph('▛', R.term.screen.quads) != eyes
        R.on_message(glp.G_HELLO, hello(glp.GF_QUAD, 'term'))       # (CLAUDE /T, 1.8 on)
        assert not R.term.resident() and R.term.screen.quads
    finally:
        R.term.stop()


def test_resident_background():
    """Once the user has gone back to the program, with a quiet bridge (HF_BG) the files and GPIB tools
    go on in the background (whatever the link's last word: the background speaks only when it has work);
    the rest name them.  Going back ends only the calls the background can't answer; a call given up on
    before it went is withdrawn; the Link rings (quietly) for an away console whatever GF_WAKE, untiringly."""
    import threading
    from types import SimpleNamespace
    from gridlink.term import TermSession as T
    from gridlink.grid import Grid, GridError, OPS_BG
    from gridlink.link import Link
    link = SimpleNamespace(last_rx=time.monotonic() - 3600, t=SimpleNamespace(sdcs=3))
    ended = []
    def term(bg):
        s = SimpleNamespace(link=link, hello={'app': 'resident', 'prog': 'TM5000G.EXE', 'ops': 'files,gpib'},
                            away=True, bg=bg, bg_sdc=3, PAUSED_TOOLS=T.PAUSED_TOOLS, OPS_TOOLS=T.OPS_TOOLS,
                            RESIDENT=T.RESIDENT, AWAY=T.AWAY, AWAY_BG=T.AWAY_BG, NOT_PAUSED=T.NOT_PAUSED,
                            BG_STOPPED=T.BG_STOPPED, grid=SimpleNamespace(end_calls=ended.append))
        link.source = s
        s.resident = lambda: T.resident(s)
        s.paused_tools = lambda: T.paused_tools(s)
        s.bg_tools = lambda: T.bg_tools(s)
        s.background = lambda: T.background(s)
        return s
    def why(tool, bg): return T.why_not(term(bg), tool)
    for tool in ('grid_files', 'grid_change_files', 'gpib_read', 'gpib_measure', 'gpib_send'):
        assert why(tool, True) is None, tool
        assert 'no GRiD tool works' in why(tool, False), tool
    for tool in ('grid_program', 'grid_type', 'grid_command'):
        w = why(tool, True)
        assert w and 'in the background' in w and 'grid_files, grid_change_files, gpib_read' in w, (tool, w)
    # CLAUDE 1.11 (ops=...,bgscreen): grid_program in the background too; grid_type still not
    s = term(True); s.hello = dict(s.hello, ops='files,gpib,bgscreen')
    assert T.why_not(s, 'grid_program') is None, T.why_not(s, 'grid_program')
    w = T.why_not(s, 'grid_type')
    assert w and 'grid_program, grid_files' in w, w
    # EVENT away with a bgscreen console: its SCREEN call goes on too; a 1.10 console's (no bgscreen) ends
    for ops, kept in (('files,gpib,bgscreen', True), ('files,gpib', False)):
        keeps = []
        s = term(True)
        s.hello = dict(s.hello, ops=ops); s.away = False; s.AWAY_CALL = T.AWAY_CALL
        s.link = SimpleNamespace(t=SimpleNamespace(set_quiet=lambda on: True, sdcs=3), hold=1)
        s.grid = SimpleNamespace(end_calls=lambda why, keep=(): keeps.append(set(keep)))
        T.on_message(s, glp.G_EVENT, bytes([glp.EV_AWAY]))
        assert s.away and s.bg and keeps and (glp.OP_SCREEN in keeps[0]) == kept and glp.OP_TYPE not in keeps[0] \
            and OPS_BG <= keeps[0], (ops, keeps)
    # the console stopped (an SDC to the bridge since it went): the calls kept end, the tools say so
    s = term(True)
    link.t.sdcs = 4
    w = T.why_not(s, 'grid_files')
    assert 'no GRiD tool works' in w and ended == [T.BG_STOPPED] and not s.bg and not T.background(s), (w, ended)
    link.t.sdcs = 3
    # going back: a SCREEN's call ends, a DIR's waits for the background's REPLY
    sent = []
    g = Grid(SimpleNamespace(send=lambda t, b: sent.append(b), withdraw=lambda t, b: False))
    out = {}
    def call(k, op):
        try: out[k] = g.call(op, b'', timeout=5)
        except GridError as e: out[k] = str(e)
    ths = [threading.Thread(target=call, args=(k, op)) for k, op in (('dir', glp.OP_DIR), ('screen', glp.OP_SCREEN))]
    for th in ths: th.start()
    while len(sent) < 2: time.sleep(0.01)
    g.end_calls('gone back', keep=OPS_BG)
    ths[1].join(2)
    assert out.get('screen') == 'gone back' and 'dir' not in out, out
    rid = next(b[0] for b in sent if b[1] == glp.OP_DIR)
    g.on_reply(bytes([rid, 0]) + b'listing')
    ths[0].join(2)
    assert out['dir'] == (0, b'listing'), out
    # a call given up on before it went: withdrawn from the queue
    L = Link(SimpleNamespace(), lambda *a: None)
    g = Grid(L)
    try: g.call(glp.OP_WRITE, b'\0\0\0\0\0A:\\LATE.TXT\0late', timeout=0.2); assert False
    except GridError as e: assert 'withdrawn' in str(e), e
    assert not L.outq and not L.withdraw(glp.P_REQUEST, b'x')
    # the rings: for an away console in the background, without GF_WAKE, and past RING_TRIES
    rings = []
    tr = SimpleNamespace(ring=lambda: rings.append('ring'), unring=lambda: rings.append('unring'))
    L = Link(tr, lambda *a: None)
    L.connected = True; L.grid_wake = False
    now = [100.0]; L.clock = lambda: now[0]
    L.source = SimpleNamespace(background=lambda: True, may_ring=lambda: True, ready=lambda: False)
    L.send(glp.P_REQUEST, b'\x01\x02')
    for _ in range(L.RING_TRIES + 3):
        now[0] += L.RING_AGAIN + 0.01; L.ring_check()
    assert rings == ['ring'] * (L.RING_TRIES + 3), rings
    L.source = SimpleNamespace(background=lambda: False, may_ring=lambda: True, ready=lambda: False)
    rings.clear(); now[0] += L.RING_AGAIN + 0.01; L.ring_check()
    assert rings == [], rings                   # (no GF_WAKE, not in the background: no ring)


if __name__ == '__main__':
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    bad = 0
    for n in names:
        t0 = time.time()
        try:
            globals()[n]()
            print('ok   %-34s %.1fs' % (n, time.time() - t0))
        except Exception:
            bad += 1
            print('FAIL %s' % n); traceback.print_exc()
    print('%d of %d passed' % (len(names) - bad, len(names)))
    sys.exit(1 if bad else 0)
