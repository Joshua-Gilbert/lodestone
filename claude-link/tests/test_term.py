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
    with its CRC: the encoder goes on from it when it is the screen of the
    last frame or the one before; anything else starts from a clear screen."""
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
    def crc(): return '%04X' % TS.screen_crc((gc, ga), grid['cur'])
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
