"""Resident Claude, M2: CLAUDE /R's console is Term, Claude Code on the Pi in
the same session as CLAUDE /T, over DOS programs.  The Lodestone kernel in
pcemu with its built-in GPIB, the 7210 and the AR488 bridge model, and the
real gridlink with a stand-in Claude Code in a pty (claude-link/tests).

    python3 tests/test_resident_term.py [name ...]
"""
import json, os, struct, sys, threading, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import test_resident as TR                      # (its build, and TM5000G)
import claude_kernel as CK                      # (claude-link's tests on the path)
import grid_emu as G
import ktest
from gridlink import glp

CL = os.path.join(GOS, 'claude')
FAKE = '%s %s' % (sys.executable, os.path.join(CK.GL_TESTS, 'fake_claude.py'))
HOT, CODE_Q, ENTER, ESC = 0x2B00, 0x1000, 0x1C0D, 0x011B

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''),
          flush=True)


class Res(CK.KernelHarness):
    """The floppy with CLAUDE.COM and the resident tests' programs, EMS,
    gridlink's router with the stand-in Claude Code; the console's state
    read from its EMS page (RCON.MAP)."""
    def __init__(s, tm=False, bridge=True, ini=None, pico=False, more=None, **kw):
        files = {'A:\\' + n: open(os.path.join(CL, n), 'rb').read()
                 for n in ('EMSUSE.COM', 'GFXUSE.COM', 'PAGE1.COM', 'CRITKEY.COM')}
        # (TESTKEY.COM is on the harness's disk already)
        files['A:\\MEMSZ.COM'] = open(os.path.join(HERE, 'MEMSZ.COM'), 'rb').read()
        if tm: files['A:\\TM5000G.EXE'] = open(TR.TM5000G, 'rb').read()
        if ini: files['A:\\LODE.INI'] = ini
        if more: files.update(more)
        if pico: kw['bridge'] = 'pico-quiet' if pico == 'quiet' else 'pico'   # (the Pico 2 bridge's model:
                                                                          #  it can ring, GF_WAKE; quiet, M4)
        super().__init__(files=files, term=FAKE, ems_pages=88, **kw)
        if not bridge: del s.m.chip.devices[7]
        s.rsym = G.symbols(os.path.join(CL, 'RCON.MAP'))
        rcon = open(os.path.join(CL, 'RCON.BIN'), 'rb').read()
        s.font_img = rcon[s.rsym['font']:s.rsym['font'] + 0x8F * 16]
        s.glyph_end = 0xAF                      # (the console's 2x2 block elements, as CLAUDE.COM's: 1.12)
        s.srq_calls = 0                         # the driver's SRQ check (AH=0Bh) while the console is up
        s.spolls = 0                            # and its serial polls (AH=05h)
        s.pit_dues = 0                          # the console's look at the PIT for its next poll (pit_due)
        srq, spoll, watch = s.m.Y.lin('gp_f_srq'), s.m.Y.lin('gp_f_spoll'), s.m.watch
        s.naps = 0                              # and its sleeps till an answer's SRQ (idle's HLT)
        due, nap = 0xE0000 + s.rsym['pit_due'], 0xE0000 + s.rsym['idle.z']
        def w(addr):
            if (addr in (due, nap) or addr in (srq, spoll) and s.m.r('cs') == 0x60) and s.stub() != 0xF000 \
                    and s.inpop() == 1 and s.m.ems_reg[0] == s.m.rd(s.stub(), s.sym['r_hw'], 1)[0]:
                if addr == due: s.pit_dues += 1     # (the console's page in)
                elif addr == nap: s.naps += 1
                elif addr == srq: s.srq_calls += 1
                else: s.spolls += 1
            watch(addr)
        s.m.watch = w

    def boot(s):
        """To LCMD's prompt."""
        k = ktest.KPC.__new__(ktest.KPC)
        k.pc = s.m; k.Y = s.m.Y; k.dos = []; k.pending = {}; k.trace = False; k.hooks = []
        s.k = k
        s.m.boot(0); k.settle(8)
        k.code_p()

    def cmd(s, text, sim_s=6):
        s.k.key('cls'); s.k.key(ENTER); s.k.key(text); s.k.key(ENTER, settle=False); s.k.settle(sim_s)
        return s.m.text_screen()

    # the resident stub (INT 16h's, once loaded) and the console's page
    def stub(s): return s.m.u16(0, 0x16 * 4 + 2)
    def inpop(s): return s.m.rd(s.stub(), s.sym['r_inpop'], 1)[0]     # the console up
    def roff(s): return s.m.rd(s.stub(), s.sym['r_off'], 1)[0]         # the hot key off (CLAUDE.COM runs)
    def page(s): return s.m.ems_page(s.m.rd(s.stub(), s.sym['r_hw'], 1)[0])
    def rv(s, name, n=1):
        b = s.m.ems_read(s.page(), s.rsym[name], n)
        return int.from_bytes(b, 'little') if n <= 2 else b
    def rw(s, name, data):                      # (the console's variables, as it would leave them)
        a = s.page() * 0x4000 + s.rsym[name]
        s.m.ems_store[a:a + len(data)] = data

    def term_cells(s):
        sh = s.m.ems_page(s.m.rd(s.stub(), s.sym['r_hw'] + 3, 1)[0])       # (the fourth page, window 3)
        raw = s.m.ems_read(sh, 0, 24 * 160)
        return ([bytes(raw[r * 160:(r + 1) * 160:2]) for r in range(24)],
                [bytes(raw[r * 160 + 1:(r + 1) * 160:2]) for r in range(24)])

    def rstack(s): return s.sym['r_stack_top'] - s.sym['r_code_end']    # (R_STACK)

    def paint_stack(s):
        """The stub's stack (used only while the console is up) painted, to
        find how deep it went."""
        s.m.wr(s.stub(), s.sym['r_code_end'], b'\xA5' * s.rstack())

    def stack_used(s):
        d = s.m.rd(s.stub(), s.sym['r_code_end'], s.rstack())
        return len(d) - next((i for i, b in enumerate(d) if b != 0xA5), len(d))

    def pi_wait(s, cond, wall=20):
        """Wait for the Pi (real time; the GRiD's simulated time can run far
        ahead while it idles in a program)."""
        end = time.time() + wall
        while time.time() < end:
            if cond(): return True
            s.run_until(lambda: False, 0.02); time.sleep(0.01)
        return cond()

    def up(s): return s.m.mode() == 0x40 and s.inpop() == 1
    def band(s): return s.screen().split('\n')[24]
    def wait(s, cond, sim_s=10): return s.run_until(cond, sim_s)
    def has(s, text, sim_s=20): return s.run_until(lambda: text in s.screen(), sim_s)


def pi_cells(h):
    t = h.router.term
    with t.lock:
        tc, ta = t.screen.cells()
        c = t.screen.cursor
        cur = None if c.hidden else (c.y, c.x)
    return [bytes(r) for r in tc], [bytes(r) for r in ta], cur

def in_step(h, sim_s=20):
    """The console's shadow and the screen are what pyte has on the Pi."""
    def same():
        if h.m.crash or h.router.term.dirty: return False
        tc, ta, cur = pi_cells(h)
        gc, ga = h.term_cells()
        return gc == tc and ga == ta and not h.term_vram_ok(tc, ta, cur)
    return h.run_until(same, sim_s)

def clean(h):
    """No crash, no link failure in the console, nothing wrong in gridlink's log."""
    errs = [l for l in h.log if 'Traceback' in str(l) or 'error' in str(l).lower()]
    return not h.m.crash and not h.nano.violations and not errs and h.rv('n_fail', 2) == 0, \
        (h.m.crash, h.nano.violations, errs, h.rv('n_fail', 2))

def bridge_quiet(h):
    """The bridge holds no answer and no SRQ (the program has the bus)."""
    h.nano.service()
    return not h.nano.srq and h.nano.lnrdy != 2 and not h.nano.pbuf


def t_popup():
    """CODE-\\ over EMSUSE: Claude Code, typing, back; the second pop-up."""
    h = Res(); h.boot()
    try:
        o = h.cmd('claude /r')
        check('CLAUDE /R loads', 'Claude is resident' in o, o)
        h.cmd('emsuse')
        h.k.key('a')
        text0, bios0 = h.m.rd(0xB800, 0, 0x8000), h.m.rd(0x40, 0x49, 30)
        h.paint_stack()
        h.press(HOT)
        ok = h.has('Welcome to Claude Code', 30)
        check('CODE-\\ over EMSUSE: the console connects and shows Claude Code', ok and h.up(), h.screen())
        enc = h.router.term.enc
        check('... its HELLO says app=resident, and gridlink gives it Term', h.router.term.hello.get('app') == 'resident'
              and h.router.app == 'term', (h.router.term.hello, h.router.app))
        check('... the console\'s shadow and screen are pyte\'s on the Pi', in_step(h), h.screen())
        check('... the band: how to go back, its last letter in column 78', 'CODE-\\ back' in h.band()
              and len(h.band()) == 79, h.band())
        # 1.12: the block elements drawn as in CLAUDE.COM, so Claude Code's mascot keeps its eyes
        t = h.router.term
        mascot = ' ▐▛███▜▌\r\n▝▜█████▛▘\r\n  ▘▘ ▝▝\r\n▘▝▖▗▌▐▀▄▛▜▙▟▚▞\r\n'
        with t.lock:
            t.stream.feed(('\x1b[2J\x1b[H' + mascot).encode())
            t._mark()
        t.link.wake()
        ok = in_step(h)
        gc, ga = h.term_cells()
        Q = glp.GL_QUADS
        want = [bytes([0x20, Q['▐'], Q['▛'], 0x20, 0x20, 0x20, Q['▜'], Q['▌']]),
                bytes([Q['▝'], Q['▜'], 0x20, 0x20, 0x20, 0x20, 0x20, Q['▛'], Q['▘']])]
        inv = ga[0][3:6] + ga[1][2:7]                   # (the full blocks: inverse blanks)
        cl = open(os.path.join(CL, 'CLAUDE.COM'), 'rb').read()
        cf = G.symbols(os.path.join(CL, 'CLAUDE.MAP'))['font'] - 0x100
        quads = h.font_img[0x81 * 16:]                  # (A1h-AEh: the console's, then CLAUDE.COM's)
        check('... Claude Code\'s mascot: its HELLO says GF_QUAD and the block elements come as A1h-AEh, all 14, '
              'the full blocks inverse blanks, drawn with the console\'s glyphs byte for byte, CLAUDE.COM\'s own',
              ok and t.screen.quads and t.gflags & glp.GF_QUAD and [gc[0][:8], gc[1][:9]] == want
              and gc[3][:14] == bytes(range(0xA1, 0xAF)) and inv == bytes([1]) * 8
              and len(quads) == 14 * 16 and quads == cl[cf + 0x81 * 16:cf + 0x8F * 16],
              (t.gflags, gc[:4], ga[:2], len(quads)))
        h.term_type('hello'); h.press(ENTER)
        check('typing in the console reaches Claude Code ("You said: hello")', h.has('You said: hello') and in_step(h),
              h.screen())
        full = enc.stats['bytes']
        pid = h.router.term.child.pid
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        check('CODE-\\ again: EMSUSE\'s screen and the BIOS\'s video data back byte for byte',
              back and h.m.rd(0xB800, 0, 0x8000) == text0 and h.m.rd(0x40, 0x49, 30) == bios0, h.m.text_screen())
        check('... and the bridge holds no answer and no SRQ while EMSUSE runs', bridge_quiet(h),
              (h.nano.srq, h.nano.lnrdy, bytes(h.nano.pbuf)))
        # a reply's first bytes still out on the kept screen (a background SCREEN's cut short by a link
        # failure; here on its row 3): they go back on that copy before the screen is kept again
        h.rw('borrowed', b'\xEE' * 12); h.rw('borrow_at', struct.pack('<H', 0x10 + 3 * 160 + 20))
        h.rw('borrow_on', b'\1')
        # the second time: Term's screen from the shadow at once, then the Pi again
        seen, hs = [], []
        b0, r0 = enc.stats['bytes'], enc.stats.get('resumes', 0)
        ss, hx, w0 = 0xE0000 + h.rsym['screen_sum'], 0xE0000 + h.rsym['put_hex16'], h.m.watch
        def w(a):
            if a in (ss, hx) and len(hs) < 2 and (a == ss) == (not hs): hs.append(h.m.us)
            w0(a)
        h.m.watch = w
        h.press(HOT)
        h.wait(lambda: h.up() and ('You said: hello' in h.screen() and seen.append(h.rv('connected')) is None), 10)
        check('the second CODE-\\: Term\'s screen drawn from the console\'s shadow before the Pi answers',
              seen and seen[0] == 0, (seen, h.screen()))
        check('... then the Pi\'s, in step', h.wait(lambda: h.rv('connected'), 10) and in_step(h), h.screen())
        h.m.watch = w0
        n = enc.stats['bytes'] - b0
        check('... the Pi went on from the console\'s kept screen (its HELLO\'s sum): %d bytes of CELLS, '
              'not the whole screen again (%d so far)' % (n, full),
              enc.stats.get('resumes', 0) == r0 + 1 and n < full // 4, (n, full, enc.stats))
        st = h.link.stats
        hus = hs[1] - hs[0] if len(hs) == 2 else None
        check('... every frame from the console with the Fletcher sum, its HELLOs too (audit3 R56: %d), and its '
              'screen\'s sum %s us by the emulator\'s blocks (the CRC-16: 15.4 ms)'
              % (st['rx_frames'], hus), st['rx_frames'] > 10 and st['rx_fletcher'] == st['rx_frames']
              and hus is not None and hus < 5000, (dict(st), hs))
        h.term_type('big'); h.press(ENTER)
        check('... the same session goes on (a 60-line answer, scrolled)', h.has('line 59') and in_step(h), h.screen())
        check('... the same claude on the Pi', h.router.term.child.pid == pid)
        used = h.stack_used()
        check('the stub\'s stack: %d of %d bytes used, 96 or more spare' % (used, h.rstack()),
              h.rstack() - used >= 96, used)
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        check('... back: EMSUSE\'s screen byte for byte, the bytes a reply had borrowed put back on the old '
              'copy before this pop-up kept the screen (unborrow before keep_screen)',
              back and h.m.rd(0xB800, 0, 0x8000) == text0 and h.rv('borrow_on') == 0, h.m.text_screen())
        h.k.key('b'); h.k.key(ESC)
        o = h.m.text_screen()
        check('EMSUSE afterwards: its keys, and its four EMS pages whole', 'EMSUSE: 2 keys, 0 bad' in o, o)
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()


def t_midstream():
    """Claude Code at work while the program runs: keys typed just before
    CODE-\\ still go, CODE-\\ in the middle of a streamed answer, and the
    next pop-up goes on from the kept screen with what came meanwhile."""
    h = Res(); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('emsuse')
        h.press(HOT)
        h.has('Welcome to Claude Code', 30)
        h.wait(lambda: h.rv('connected'), 10)
        enc = h.router.term.enc
        for k in [G.SCAN[c] << 8 | ord(c) for c in 'big'] + [ENTER, HOT]:
            h.press(k)                                      # all at once: CODE-\ right behind them
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        check('keys typed just before CODE-\\ go to Claude Code before the program is back',
              back and h.pi_wait(lambda: 'line 59' in '\n'.join(h.router.term.text())), h.router.term.text()[-3:])
        check('... and the bridge is quiet while EMSUSE runs', bridge_quiet(h), (h.nano.srq, h.nano.lnrdy))
        r0 = enc.stats.get('resumes', 0)
        h.press(HOT)
        ok = h.has('line 59', 20) and in_step(h)
        check('the next CODE-\\: the 60 lines that came meanwhile, on from the kept screen (resumed), in step',
              ok and enc.stats.get('resumes', 0) == r0 + 1, (enc.stats, h.screen()))
        h.term_type('slow'); h.press(ENTER)
        streaming = h.has('This answer arrives', 20)
        h.press(HOT)                                        # in the middle of it
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        quiet = bridge_quiet(h)
        check('CODE-\\ in the middle of a streamed answer: back to EMSUSE, the bridge quiet',
              streaming and back and quiet, (streaming, back, quiet, h.nano.srq, h.nano.lnrdy))
        t = h.router.term                                   # (the answer goes on on the Pi meanwhile:
        end, last, since = time.time() + 30, None, time.time()     #  until its screen is still for 1.5 s)
        while time.time() < end and time.time() - since < 1.5:
            h.run_until(lambda: False, 0.2)
            if t.text() != last: last, since = t.text(), time.time()
        r0 = enc.stats.get('resumes', 0)
        h.press(HOT)
        ok = h.wait(lambda: h.up() and h.rv('connected'), 10) and in_step(h)
        check('... CODE-\\ again once it has finished: the rest of it there, on from the kept screen, in step',
              ok and enc.stats.get('resumes', 0) == r0 + 1 and 'This answer arrives' in h.screen(),
              (enc.stats, h.screen()))
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        check('EMSUSE afterwards', 'EMSUSE: 0 keys, 0 bad' in h.m.text_screen(), h.m.text_screen())
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()


def t_session():
    """The same Claude Code as CLAUDE /T, both ways; CLAUDE.COM keeps the
    hot key off while it runs."""
    h = Res(); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('emsuse')
        h.press(HOT)
        h.has('Welcome to Claude Code', 30)
        h.term_type('hello'); h.press(ENTER)
        h.has('You said: hello')
        pid = h.router.term.child.pid
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        h.k.key('cls'); h.k.key(ENTER); h.k.key('claude /t'); h.press(ENTER)
        ok = h.has('You said: hello', 30)
        check('CLAUDE /T after the console: the same Claude Code, what was typed there on its screen', ok, h.screen())
        check('... the hot key off while CLAUDE runs (it has the link)', h.roff() == 1 and h.inpop() == 0, (h.roff(), h.inpop()))
        h.term_type('diff'); h.press(ENTER)
        h.has('int rate = 5')
        h.press(CODE_Q)
        h.k.settle(5)
        check('... and on again when it ends', h.roff() == 0 and h.m.mode() == 3, (h.roff(), h.m.mode()))
        h.cmd('emsuse')
        r0 = h.router.term.enc.stats.get('resumes', 0)
        h.press(HOT)
        ok = h.has('int rate = 5', 30)
        check('the console after CLAUDE /T: what was typed in CLAUDE /T on its screen', ok and in_step(h), h.screen())
        check('... the same claude on the Pi throughout', h.router.term.child.pid == pid)
        check('... drawn again from a clear screen: the console\'s kept screen isn\'t the Pi\'s last (CLAUDE /T\'s)',
              h.router.term.enc.stats.get('resumes', 0) == r0, h.router.term.enc.stats)
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        check('EMSUSE afterwards', 'EMSUSE: 0 keys, 0 bad' in h.m.text_screen(), h.m.text_screen())
    finally:
        h.close()


def t_requests():
    """The GRiD's tools while the console is up: those it can't do there
    (grid_info among them) say why not; such a request that comes anyway is answered
    F6h at once (files and GPIB are done in the pop-up since 1.9)."""
    h = Res(); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('emsuse')
        h.press(HOT)
        h.has('Welcome to Claude Code', 30)
        res = h.router.term.tools.request(json.dumps({'tool': 'grid_info', 'arguments': {}}).encode() + b'\n')
        check('an MCP tool while the console is up: an error saying why, nothing sent to the GRiD',
              res[1] and 'popped up over a DOS program' in res[0][0]['text'], res)
        r = {}
        th = threading.Thread(target=lambda: r.update(v=h.router.term.grid.call(glp.OP_INFO, timeout=60)))
        th.start()
        h.wait(lambda: not th.is_alive(), 10)
        check('a REQUEST that comes anyway: REPLY status F6h at once (not a wait)', r.get('v') == (0xF6, b''), r)
        check('... the console still in step', in_step(h), h.screen())
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        check('EMSUSE afterwards', 'EMSUSE: 0 keys, 0 bad' in h.m.text_screen(), h.m.text_screen())
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()


def t_nopi():
    """No bridge on the bus: the console says so and goes back at once."""
    h = Res(bridge=False); h.boot()
    try:
        h.cmd('claude /r /a:9')
        h.cmd('emsuse')
        h.press(HOT)
        ok = h.wait(lambda: h.up() and 'No answer from the bridge at GPIB address 9' in h.band(), 10)
        check('no bridge (CLAUDE /R /A:9): the console\'s band says "No answer from the bridge at GPIB address 9"',
              ok, h.band())
        t0 = h.m.us
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        ms = (h.m.us - t0) / 1000
        check('... CODE-\\ goes back within half a second (%.0f ms)' % ms, back and ms < 500, ms)
        h.k.key(ESC)
        check('EMSUSE afterwards', 'EMSUSE: 0 keys, 0 bad' in h.m.text_screen(), h.m.text_screen())
    finally:
        h.close()


def tool(h, name, args, sim_s=30, wall=60):
    """An MCP tool call, as Claude Code makes it (in a thread: it waits for
    the GRiD, which runs meanwhile) -> (content, isError), or None."""
    r = {}
    th = threading.Thread(target=lambda: r.update(v=h.router.term.tools.request(
        json.dumps({'tool': name, 'arguments': args}).encode() + b'\n')))
    th.start()
    h.run_until(lambda: not th.is_alive(), sim_s, wall)
    th.join(30)
    return r.get('v')

def generation(h):
    """gridlink's count of the GRiD's HELLOs (None before the first)."""
    return h.router.term.grid.generation if h.router.term else None

def popped(h, gen):
    """CODE-\\ pressed: the console up and its HELLO through (the tools work)."""
    return h.wait(lambda: generation(h) not in (None, gen) and h.rv('connected') == 1 and h.up(), 30)

def raw_screen(h):
    """The SCREEN reply's bytes (Grid.screen), the GRiD run meanwhile."""
    r = {}
    th = threading.Thread(target=lambda: r.update(v=h.router.term.grid.screen(0)))
    th.start()
    h.wait(lambda: not th.is_alive(), 30)
    th.join(30)
    return r.get('v')

def status_ok(h):
    """The band's status (shown when the link is down) the console's own
    text after TYPE's return, not what was at its reply's address."""
    return h.rv('status_text', 20) == b'Connecting to the Pi'

def t_type():
    """M3: Claude sees the program the console is up over and types into it
    (TESTKEY echoes its keys): the console goes, the keys play, and it comes
    back by itself with the program's screen; CODE-\\ stops the keys."""
    h = Res(); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('testkey')
        cells = h.m.rd(0xB800, 0, 4000)
        h.press(HOT)
        ok = h.has('Welcome to Claude Code', 30)
        check('CODE-\\ over TESTKEY: HELLO names it (prog=TESTKEY.COM), and so does the band',
              ok and h.router.term.hello.get('prog') == 'TESTKEY.COM' and 'TESTKEY.COM' in h.band(),
              (h.router.term.hello, h.band()))
        res = tool(h, 'grid_program', {})
        check('grid_program: "TESTKEY.COM is paused", and its screen ("TESTKEY ready:")',
              res and not res[1] and 'TESTKEY.COM is paused' in res[0][0]['text'] and
              'TESTKEY ready:' in res[0][1]['text'], res)
        raw = raw_screen(h)
        check('... SCREEN\'s bytes: mode 3, 80x25 text, its cells as they were, byte for byte',
              raw is not None and raw[:9] == bytes([3, 1, 0, 80, 0, 25, 0, 160, 0]) and raw[9:] == cells,
              raw[:9] if raw else raw)
        gen = generation(h)
        res = tool(h, 'grid_type', {'keys': 'hello{WAIT 0.3}'}, 60)
        check('grid_type "hello": the keys played into TESTKEY, and its screen afterwards ("TESTKEY ready: hello")',
              res and not res[1] and res[0][0]['text'] == 'Typed into TESTKEY.COM.' and
              'TESTKEY ready: hello' in res[0][1]['text'], res)
        check('... the console back up by itself, the link as it was (no HELLO, the call not cancelled), in step',
              h.up() and h.router.term.grid.generation == gen and in_step(h), (h.up(), gen, h.router.term.grid.generation))
        check('... and the stub feeds nothing more (r_ks 0)', h.m.rd(h.stub(), h.sym['r_ks'], 1)[0] == 0)
        check('... the band\'s status the console\'s own ("Connecting to the Pi"), not bytes at the reply\'s address',
              status_ok(h), h.rv('status_text', 72))
        # CODE-\ while the keys wait: they stop there, and TYPE says so
        res, t0 = {}, None
        th = threading.Thread(target=lambda: res.update(v=h.router.term.tools.request(
            json.dumps({'tool': 'grid_type', 'arguments': {'keys': '{WAIT 5}abc', 'timeout': 30}}).encode() + b'\n')))
        th.start()
        down = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 20)
        h.run_until(lambda: False, 0.5)
        h.press(HOT)
        h.wait(lambda: not th.is_alive(), 30); th.join(30)
        res = res.get('v')
        check('grid_type with CODE-\\ during its {WAIT}: the console back, "the user stopped the keys", none typed',
              down and h.up() and res and not res[1] and 'stopped the keys (CODE-\\)' in res[0][0]['text'] and
              'abc' not in res[0][1]['text'] and h.m.rd(h.stub(), h.sym['r_ks'], 1)[0] == 0, res)
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        away = h.pi_wait(lambda: h.router.term.away, 10)
        t0 = time.time()
        res = tool(h, 'grid_program', {}, 5, 20)
        check('CODE-\\ back to TESTKEY: the console says so (EVENT away), and grid_program is refused at once',
              back and away and res and res[1] and 'gone back' in res[0][0]['text'] and time.time() - t0 < 5, res)
        # a call on its way as the user goes back: the console drops it, and the EVENT ends it on the Pi.
        # (CODE-\ is read before the console's next poll: if that ever fails, the call succeeds with the
        # screen, and `replies` isn't empty; the drop isn't at fault then)
        gen = generation(h)
        h.press(HOT)
        popped(h, gen)
        check('... CODE-\\ again: its HELLO, and the tools work again', not h.router.term.away and
              h.router.term.why_not('grid_program') is None, h.router.term.why_not('grid_program'))
        h.run_until(lambda: False, 3)           # (quiet: then it polls once a second)
        t = h.rv('t_last', 2)
        quiet = h.run_until(lambda: h.rv('t_last', 2) != t and h.rv('lstate') == 1 and h.rv('pi_active') == 0 and
                            h.rv('txq_n') == 0, 5)
        g, replies = h.router.term.grid, []
        on_reply = g.on_reply
        g.on_reply = lambda b: (replies.append(bytes(b)), on_reply(b))
        r = {}
        th = threading.Thread(target=lambda: r.update(v=h.router.term.tools.request(
            json.dumps({'tool': 'grid_program', 'arguments': {}}).encode() + b'\n')))
        th.start()
        end = time.time() + 10
        while not g.waiting and time.time() < end: time.sleep(0.01)
        h.press(HOT)                            # (before the console's next poll)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.wait(lambda: not th.is_alive(), 10); th.join(30)
        g.on_reply = on_reply
        res = r.get('v')
        check('... a grid_program on its way as the user goes back: the console answers nothing, and the call '
              'ends at once ("the user went back")', quiet and back and res and res[1] and
              'went back' in res[0][0]['text'] and not replies, (quiet, back, res, replies))
        # the name only from an environment TESTKEY still owns (one it freed may be anyone's now), and
        # only up to a control character (HELLO is lines)
        psp = h.m.u16(0x60, h.m.Y['cur_psp'])
        env = h.m.u16(psp, 0x2C)
        owner, blk = h.m.rd(env - 1, 1, 2), h.m.rd(env, 0, 256)
        at = blk.find(b'TESTKEY.COM')
        seen = []
        for mcb, name in ((b'\0\0', b'TESTKEY.COM'), (owner, b'TE\nXX=1.COM')):
            h.m.wr(env - 1, 1, mcb); h.m.wr(env, at, name)
            gen = generation(h)
            h.press(HOT)
            popped(h, gen)
            seen.append((dict(h.router.term.hello), h.band()))
            h.press(HOT)
            h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.m.wr(env - 1, 1, owner); h.m.wr(env, 0, blk)
        check('its environment not its own (freed, PSP:2Ch stale): no name in HELLO or the band',
              at > 0 and 'prog' not in seen[0][0] and 'TESTKEY' not in seen[0][1], seen[0])
        check('... a control character in the name: the name ends there, no line of its own in HELLO',
              seen[1][0].get('prog') == 'TE' and 'XX' not in seen[1][0], seen[1][0])
        h.k.key(ESC)
        check('TESTKEY afterwards: the 5 keys, no more ("TESTKEY ready: hello", then bye)',
              back and 'TESTKEY ready: hello\nbye' in h.m.text_screen().replace('\r', ''), h.m.text_screen())
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
        # a program with EMS in all four windows, which it checks after every key: the stub's feeder maps
        # the console's page into window 0 for each key, and the program's back
        for arg, call in (('', '00h'), (' /x', '10h')):
            h.cmd('emsuse' + arg)
            gen = generation(h)
            h.press(HOT)
            popped(h, gen)
            res = tool(h, 'grid_type', {'keys': 'abc{WAIT 0.3}'}, 60)
            typed = res and not res[1] and res[0][0]['text'] == 'Typed into EMSUSE.COM.' and h.up()
            h.press(HOT)
            back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
            h.k.key(ESC)
            o = h.m.text_screen()
            check('grid_type "abc" into EMSUSE%s (INT 16h AH=%s): its four EMS windows whole after every key '
                  '("3 keys, 0 bad")' % (arg.upper(), call), typed and back and 'EMSUSE: 3 keys, 0 bad' in o, (res, o))
        # a graphics screen: mode 6, its 16 KB as they were
        h.cmd('gfxuse 6')
        vram = h.m.rd(0xB800, 0, 0x4000)
        gen = generation(h)
        h.press(HOT)
        popped(h, gen)
        res = tool(h, 'grid_program', {})
        raw = raw_screen(h)
        check('over GFXUSE in mode 6: grid_program\'s image, SCREEN\'s bytes its 640x200 as they were',
              res and not res[1] and res[0][-1]['type'] == 'image' and raw is not None and
              raw[:9] == bytes([6, 2, 1, 128, 2, 200, 0, 80, 0]) and raw[9:] == vram,
              (res and res[0][0].get('text'), raw and raw[:9]))
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 6 and h.inpop() == 0, 5)
        h.k.key('x'); h.k.key(ESC)
        check('... GFXUSE afterwards: its screen and data kept (0 bad)', '0 bad' in h.m.text_screen(), h.m.text_screen())
        # text on page 1: the reply's first bytes stand on the saved screen in front of it, and go back
        h.cmd('page1')
        vram = h.m.rd(0xB800, 0, 0x8000)
        gen = generation(h)
        h.press(HOT)
        popped(h, gen)
        res = tool(h, 'grid_program', {})
        raw = raw_screen(h)
        check('over PAGE1 (text on page 1, B800:1000h): its screen ("PAGE1 ready"), SCREEN\'s bytes page 1\'s',
              res and not res[1] and 'PAGE1 ready' in res[0][1]['text'] and raw is not None and
              raw[9:] == vram[0x1000:0x1000 + 4000], (res and res[0][1].get('text', '')[:40], raw and raw[:9]))
        res = tool(h, 'grid_type', {'keys': 'x{WAIT 0.3}'}, 60)
        check('... grid_type "x" into it: back with page 1, the band\'s status the console\'s own',
              res and not res[1] and 'PAGE1 ready' in res[0][1]['text'] and h.up() and status_ok(h),
              (res, h.rv('status_text', 72)))
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        check('... CODE-\\ back: its 32 KB byte for byte, the 12 in front of page 1 too',
              back and h.m.rd(0xB800, 0, 0x8000) == vram,
              next((hex(i) for i in range(0x8000) if h.m.rd(0xB800, i, 1)[0] != vram[i]), None))
        h.k.key(ESC)
        # mode 40h (the Executive): the 32 KB reply, to the last byte of window 2
        h.cmd('exit')
        h.k.settle(3)
        vram = h.m.rd(0xB800, 0, 0x8000)
        gen = generation(h)
        h.press(HOT)
        popped(h, gen)
        raw = raw_screen(h)
        check('over the Executive (mode 40h): SCREEN\'s 640x400, 32 KB, byte for byte',
              h.m.mode() == 0x40 and raw is not None and raw[:9] == bytes([0x40, 4, 1, 128, 2, 144, 1, 80, 0]) and
              raw[9:] == vram, raw and (raw[:9], len(raw)))
        h.press(HOT)
        back = h.wait(lambda: h.inpop() == 0, 5)
        h.k.settle(1)
        check('... CODE-\\ back: the Executive\'s screen as it was', back and h.m.rd(0xB800, 0, 0x8000) == vram,
              next((hex(i) for i in range(0x8000) if h.m.rd(0xB800, i, 1)[0] != vram[i]), None))
    finally:
        h.close()


PEEK_SCRIPT = 'a{WAIT 0.3}b{WAIT 1}c'
PEEK_AT = {'start': 'just after it says the second {WAIT} is under way',
           'look': 'between its read of ks_pos and its look at ks_wait, as the first {WAIT} ends',
           'end0': 'as the first {WAIT} ends, before ks_wait goes 0',
           'end1': 'as the first {WAIT} ends, ks_wait 0, before ks_pos moves on'}

def tsr_1ch(m):
    """A TSR on INT 1Ch at F000:1300 (the BIOS stub's spare RAM): an INT 16h AH=01h peek when F000:1320h is
    set, then the INT 1Ch before.  -> the vector to put back."""
    old = m.rd(0, 0x1C * 4, 4)
    m.wr(0xF000, 0x1300, bytes([0x2E, 0x80, 0x3E, 0x20, 0x13, 0x00,      # cmp byte [cs:1320h], 0
                                0x74, 0x0C,                              # je .chain
                                0x2E, 0xC6, 0x06, 0x20, 0x13, 0x00,      # mov byte [cs:1320h], 0
                                0x50, 0xB4, 0x01, 0xCD, 0x16, 0x58,      # push ax / mov ah,1 / int 16h / pop ax
                                0xEA]) + old)                            # .chain: jmp far
    m.wr(0xF000, 0x1320, b'\0')
    m.wr(0, 0x1C * 4, struct.pack('<HH', 0x1300, 0xF000))
    return old

def tick_before(m, addr):
    """IRQ 0, the TSR's peek armed, before the instruction at addr, as deliver_irqs gives it (an emu_stop in
    a code hook ends only the block); with interrupts off, held till they are on (as the PIC holds it)."""
    m.wr(0xF000, 0x1320, b'\1')
    fl, cs = m.r('flags'), m.r('cs')
    if not fl & 0x200:
        m.irq_pending.add(0); return
    m.push(fl); m.push(cs); m.push(addr - cs * 16); m.isr |= 1
    off, seg = struct.unpack('<HH', m.rd(0, 8 * 4, 4))
    m.w('flags', fl & ~0x300); m.w('cs', seg); m.w('ip', off)

def peek_race(m, lo, hi, var, here, at, where, run, waits):
    """A key-script feeder's code at lo..hi (linear), its state var(name, size), in place when here(); at:
    its instructions 'look' (CMP ks_wait, 0), 'end0' (MOV ks_wait, 0) and 'end1' (the ADD to ks_pos after).
    A TSR's INT 1Ch peek, PEEK_AT[where], while run() types PEEK_SCRIPT (its two waits at ks_pos `waits`).
    -> (the waits' simulated seconds (None: never at or past one), the state the peek left
    (ks_wait, ks_pos, ZF: no key), run()'s result)"""
    from unicorn import UC_HOOK_CODE
    w1, w2 = waits
    st = {'t': {}, 'done': False, 'prev': var('ks_wait', 1), 'after': None}
    def feeder(uc, addr, size, ud):
        if not here(): return
        w, pos = var('ks_wait', 1), var('ks_pos', 2)
        st['t'].setdefault(pos, m.us)
        start = st['prev'] == 0 and w == 1 and pos == w2
        st['prev'] = w
        if st['done'] or not (where == 'start' and start or addr == at.get(where) and pos == w1 and (
                where != 'look' or w == 1 and m.u16(0, 0x46C) == (var('ks_until', 2) - 1) & 0xFFFF)):
            return
        st['done'] = True
        tick_before(m, addr)                    # (look: the tick that ends the wait)
    def peeked(uc, addr, size, ud):             # (the TSR's pop ax: its peek back)
        if st['after'] is None: st['after'] = (var('ks_wait', 1), var('ks_pos', 2), m.r('flags') & 0x40)
    old = tsr_1ch(m)
    hk = [m.mu.hook_add(UC_HOOK_CODE, feeder, None, lo, hi - 1),
          m.mu.hook_add(UC_HOOK_CODE, peeked, None, 0xF1313, 0xF1313)]
    m.mu.ctl_remove_cache(lo, hi); m.mu.ctl_remove_cache(0xF1300, 0xF1320)
    try: res = run()
    finally:
        for x in hk: m.mu.hook_del(x)
        m.wr(0, 0x1C * 4, old)
    t = st['t']
    d = [(t[w + 3] - t[w]) / 1e6 if w in t and w + 3 in t else None for w in (w1, w2)]
    return d, st['after'] if st['done'] else 'no race', res

def peek_waits(script, base):
    """ks_pos of each {WAIT} in the compiled script, from base."""
    from gridlink import keys as K
    b, i, out = K.compile_script(script), 0, []
    while i < len(b):
        if b[i:i + 2] == b'\xff\xff': out.append(base + i)
        i += 3 if b[i] == 0xFF else 2
    return out

def t_type_peek():
    """audit3 X42 and its panel: a TSR's INT 16h peek from its INT 1Ch (a tick: the PIC's ISR set, so only the
    stub's feeder runs) while the console's feeder moves a {WAIT} on: the peek sees the wait whole, and the
    waits and keys play as typed.  rc_feed runs with interrupts off (the peek comes after it).  Before X42 a
    wait's end was stored after ks_wait, in two parts: the peek saw the last wait's end (passed) and the keys
    after went at once.  Before the panel's fix, as a wait ended: a peek before ks_wait went 0 moved ks_pos on
    by 3 twice ('b' lost), one before ks_pos moved on, or between .l and the look at ks_wait, began the wait
    again and left ks_wait 1 for the next, cut short."""
    h = Res(); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('testkey')
        h.press(HOT)
        up = h.has('Welcome to Claude Code', 30)
        lo, hi = 0xE0000 + h.rsym['rc_feed'], 0xE0000 + h.rsym['keys_back']
        code = h.m.ems_read(h.page(), h.rsym['rc_feed'], hi - lo)
        kw, kp = struct.pack('<H', h.rsym['ks_wait']), struct.pack('<H', h.rsym['ks_pos'])
        e0 = code.find(b'\xC6\x06' + kw + b'\0')
        assert code.count(b'\xC6\x06' + kw + b'\0') == 1 and code[e0 + 5:e0 + 10] == b'\x83\x06' + kp + b'\3', code.hex()
        at = {'look': lo + code.index(b'\x80\x3E' + kw + b'\0'), 'end0': lo + e0, 'end1': lo + e0 + 5}
        here = lambda: h.m.ems_reg[0] == h.m.rd(h.stub(), h.sym['r_hw'], 1)[0]
        waits = peek_waits(PEEK_SCRIPT, 2)
        line = 'TESTKEY ready: '
        for where in PEEK_AT:
            d, after, res = peek_race(h.m, lo, hi, lambda n, k: h.rv(n, k), here, at, where,
                                      lambda: tool(h, 'grid_type', {'keys': PEEK_SCRIPT}, 60), waits)
            text = res[0][1]['text'] if res and not res[1] else ''
            line += 'abc'
            check('a TSR\'s peek %s: the waits held (%s s), the keys as typed%s' % (
                  PEEK_AT[where], d, '; the peek no key, the wait under way and whole' if where == 'start' else ''),
                  up and None not in d and d[0] > 0.15 and d[1] > 0.85 and line in text and isinstance(after, tuple)
                  and (where != 'start' or after == (1, waits[1], 0x40)), (d, after, res))
        ok, why = clean(h)
        check('... no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()


def t_title_room():
    """audit3 X41: the band's title at its longest (the Pi's 36, a 12-character program name, 99 requests in
    the background, DOS busy: 87 bytes and the NUL) stays in title_text's 69 bytes, status_text after it
    untouched; what the band shows (48 cells) as before."""
    h = Res(); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('testkey')
        h.press(HOT)
        up = h.has('Welcome to Claude Code', 30) and in_step(h)
        base = h.page() * 0x4000
        def poke(name, data): h.m.ems_store[base + h.rsym[name]:base + h.rsym[name] + len(data)] = data
        poke('prog', b'LONGNAME.COM\0'); poke('bg_shown', b'\x63'); poke('dos_ok', b'\0')
        st0 = h.rv('status_text', 72)
        h.link.send(glp.P_TITLE, b'T' * 40)
        shown = h.run_until(lambda: 'T' * 36 in h.band(), 5)
        title = h.rv('title_text', 69)
        check('the longest title: in title_text (its NUL by byte 68), status_text untouched',
              up and shown and 0 in title and h.rv('status_text', 72) == st0, (up, shown, title, st0, h.rv('status_text', 72)))
        check('... the band shows the Pi\'s title and the program\'s name, as far as its 48 cells go',
              title.startswith(b'T' * 36 + b'  \x86  LONGNAME.COM') and 'LONGNA' in h.band().split('T' * 36)[-1],
              (title, h.band()))
        ok, why = clean(h)
        check('... no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()


def t_noscreen():
    """A program in a mode the console keeps no copy of (mono, mode 7):
    SCREEN's REPLY is F5h and nothing after it; TYPE's is F5h and its
    flags."""
    h = Res(); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('testkey')
        gen = generation(h)
        h.press(HOT)
        popped(h, gen)
        g = h.router.term.grid
        replies, on_reply = [], g.on_reply
        g.on_reply = lambda b: (replies.append(bytes(b)), on_reply(b))
        mode = h.page() * 0x4000 + h.rsym['bios']               # (the program's mode as the console kept it)
        h.m.ems_store[mode] = 7
        r = {}
        th = threading.Thread(target=lambda: r.update(v=g.call(glp.OP_SCREEN, b'\0', timeout=60)))
        th.start(); h.wait(lambda: not th.is_alive(), 30); th.join(30)
        h.m.ems_store[mode] = 3
        check('over a program in mode 7: SCREEN\'s REPLY is F5h, nothing after it',
              r.get('v') == (0xF5, b'') and len(replies) == 1 and len(replies[0]) == 2, (r, replies))
        del replies[:]
        res = {}
        th = threading.Thread(target=lambda: res.update(v=h.router.term.tools.request(
            json.dumps({'tool': 'grid_type', 'arguments': {'keys': '{WAIT 1}x'}}).encode() + b'\n')))
        th.start()
        down = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 20)
        h.m.wr(0x40, 0x49, b'\x07')                             # mode 7 when the console comes back
        h.run_until(lambda: not th.is_alive(), 30, 60); th.join(30)
        res = res.get('v')
        up = h.up()
        h.m.ems_store[mode] = 3                                 # (so CODE-\ goes back to mode 3)
        check('... grid_type there: TYPE\'s REPLY is F5h and its flags (all played), "No screenshot"',
              down and up and res and not res[1] and len(replies) == 1 and replies[0][1:] == b'\xF5\x01' and
              'Typed into TESTKEY.COM. No screenshot' in res[0][0]['text'], (down, up, res, replies))
        g.on_reply = on_reply
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        check('TESTKEY afterwards: the key it was typed ("TESTKEY ready: x")',
              back and 'TESTKEY ready: x' in h.m.text_screen(), h.m.text_screen())
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()


def t_replies():
    """audit3 R52: the console's own REPLYs (no data, or TYPE's flags) on the wire, byte for byte: the
    request's id and the status, from each place that makes one -- a request over REQMAX (F0h), a TYPE over
    KSMAX (F0h), an op it doesn't do (F6h), a file's with DOS busy as it comes (F7h) and as it is to run
    (F7h, req_service: dos_ok gone meanwhile), SCREEN with no screen kept (F5h)."""
    h = Res(); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('emsuse')
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and h.has('Welcome to Claude Code', 30)
        g = h.router.term.grid
        replies, on_reply = [], g.on_reply
        g.on_reply = lambda b: (replies.append(bytes(b)), on_reply(b))
        def call(op, args=b''):
            del replies[:]
            rid, r = g.next_id, {}
            th = threading.Thread(target=lambda: r.update(v=g.call(op, args, timeout=60)))
            th.start(); h.wait(lambda: not th.is_alive(), 30); th.join(30)
            one = len(replies) == 1 and len(replies[0]) == 2 and replies[0][0] == rid
            return one and r.get('v') == (replies[0][1], b''), list(replies)
        stat = glp.asciiz('A:\\EMSUSE.COM')
        got = {'big': call(glp.OP_WRITE, struct.pack('<BI', 0, 0) + b'A:\\BIG.DAT\0' + b'x' * 9000),
               'type': call(glp.OP_TYPE, b'\0' * 2100),
               'op': call(glp.OP_INFO)}
        h.rw('dos_ok', b'\0')
        got['dos'] = call(glp.OP_STAT, stat)
        h.rw('dos_ok', b'\1')
        a0, st, watch = 0xE0000 + h.rsym['req_service'], {'n': 0}, h.m.watch
        def w(addr):                            # (DOS gone busy after rf_request took the request)
            if addr == a0 and h.m.ems_reg[0] == h.m.rd(h.stub(), h.sym['r_hw'], 1)[0] and h.rv('req_ready'):
                h.rw('dos_ok', b'\0'); st['n'] += 1
            watch(addr)
        h.m.watch = w
        got['dos2'] = call(glp.OP_STAT, stat)
        h.m.watch = watch
        h.rw('dos_ok', b'\1')
        mode = h.page() * 0x4000 + h.rsym['bios']
        h.m.ems_store[mode] = 7
        got['screen'] = call(glp.OP_SCREEN, b'\0')
        h.m.ems_store[mode] = 3
        g.on_reply = on_reply
        want = {'big': 0xF0, 'type': 0xF0, 'op': 0xF6, 'dos': 0xF7, 'dos2': 0xF7, 'screen': 0xF5}
        check('each of the console\'s own REPLYs: the request\'s id and the status, nothing more',
              up and st['n'] == 1 and all(got[k][0] and got[k][1][0][1] == v for k, v in want.items()), (up, st, got))
        check('... the console still up, in step', h.up() and in_step(h), h.screen())
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
    finally:
        h.close()


def t_drive():
    """M3's aim: Claude drives TM5000G, the console popped up over it (its
    module auto-detect through grid_type, the screen of what it found)."""
    if not TR.TM5000G:
        print('(no TM5000G.EXE: skipped)'); return
    h = Res(tm=True); h.boot()
    try:
        h.cmd('claude /r')
        h.k.key('cls'); h.k.key(ENTER); h.k.key('tm5000g'); h.k.key(ENTER, settle=False); h.k.settle(40)
        h.k.key(ENTER)
        gen = generation(h)
        h.press(HOT)
        popped(h, gen)
        res = tool(h, 'grid_program', {})
        check('over TM5000G: grid_program has its main menu ("TM5000 CONTROL SYSTEM")',
              res and not res[1] and 'TM5000G.EXE is paused' in res[0][0]['text'] and
              'TM5000 CONTROL SYSTEM' in res[0][1]['text'], res)
        res = tool(h, 'grid_type', {'keys': '1A{WAIT 60}', 'timeout': 120}, sim_s=120, wall=300)
        txt = res[0][1]['text'] if res and not res[1] and len(res[0]) > 1 else ''
        check('grid_type "1A{WAIT 60}" (Configure Modules, auto-detect): TM5000G finds FG5010, 8753D, DC5009, '
              'and the console comes back with that screen', all(x in txt for x in ('FG5010', '8753D', 'DC5009'))
              and h.up(), res)
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        check('... CODE-\\ back: TM5000G as Claude left it', back and all(x in h.m.text_screen() for x in
              ('FG5010', '8753D', 'DC5009')), h.m.text_screen())
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()


def t_timeout():
    """The console's own GPIB timeout: the driver's is global, and the program's
    may be long (TM5000G's TIME OUT n leaves up to 60 s), which each byte to a
    stuck bridge would wait."""
    h = Res(); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('emsuse')
        def tmo(v=None):                        # the driver's timeout, in ticks
            if v is not None: h.m.wr(0x60, h.m.Y['gp_tdata'], v.to_bytes(2, 'little'))
            return h.m.u16(0x60, h.m.Y['gp_tdata'])
        tmo(1091)                               # 60 s, as TIME OUT 60 leaves it
        h.press(HOT)
        ok = h.has('Welcome to Claude Code', 30)
        during = tmo()
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        check('the console\'s own GPIB timeout while it is up, 2 s (37 ticks), and the program\'s 60 s (1091) back '
              'after: %s, %s' % (during, tmo()), ok and back and during == 37 and tmo() == 1091, (ok, back, during, tmo()))
        h.nano.rx_byte = lambda v, eoi: float('inf')        # the bridge stuck: on the bus, taking no byte (to the end)
        tmo(1091)
        h.press(HOT)
        up = h.wait(lambda: h.up(), 5)
        h.run_until(lambda: False, 0.5)         # (its HELLO under way)
        t0 = h.m.us
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 10)
        s_ = (h.m.us - t0) / 1e6
        check('... a stuck bridge, under the program\'s 60 s: CODE-\\ still goes back within 5 s (%.1f s), '
              'the program\'s timeout as it was' % s_, up and back and s_ < 5 and tmo() == 1091, (up, back, s_, tmo()))
    finally:
        h.close()


def t_tm5000g():
    """Over TM5000G: the console talks to the Pi on the bus TM5000G uses;
    TM5000G's bus state afterwards."""
    if not TR.TM5000G:
        print('(no TM5000G.EXE: skipped)'); return
    h = Res(tm=True); h.m.mouse = True; h.boot()
    try:
        h.cmd('claude /r')
        h.k.key('cls'); h.k.key(ENTER); h.k.key('tm5000g'); h.k.key(ENTER, settle=False); h.k.settle(40)
        h.k.key(ENTER)
        text0 = h.m.text_screen()
        check('TM5000G runs with Claude resident (main menu)', 'TM5000 CONTROL SYSTEM' in text0, text0)
        Y = h.m.Y
        # as if an instrument had asked for service and TM5000G not yet looked:
        # the driver's SRQ flag set, which the console must not clear (AH=0Bh would)
        h.m.wr(0x60, Y['gp_shadow2'], bytes([h.m.rd(0x60, Y['gp_shadow2'], 1)[0] | 0x40]))
        ren0, srq0 = h.m.rd(0x60, Y['gp_renon'], 1)[0], h.m.rd(0x60, Y['gp_shadow2'], 1)[0] & 0x40
        resets0 = h.m.chip.log.count('reset')
        h.paint_stack()
        h.press(HOT)
        ok = h.has('Welcome to Claude Code', 30)
        h.term_type('hello'); h.press(ENTER)
        ok = ok and h.has('You said: hello') and in_step(h)
        check('CODE-\\ over TM5000G: Claude Code, typing reaches it', ok, h.screen())
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'})
        check('... the GRiD\'s files over TM5000G (it reads its keys through DOS: the kernel\'s key wait)',
              r and not r[1] and 'TM5000G.EXE' in r[0][0]['text'] and 'DOS busy' not in h.band(), (r, h.band()))
        for _ in range(2): h.m.mouse_move(16, 16); h.run_until(lambda: False, 0.05)
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        for _ in range(2): h.m.mouse_move(-16 & 0xFF, -16 & 0xFF); h.run_until(lambda: False, 0.05)
        h.k.settle()
        check('CODE-\\ again: TM5000G\'s screen as it was', h.m.text_screen() == text0, h.m.text_screen())
        ren1, srq1 = h.m.rd(0x60, Y['gp_renon'], 1)[0], h.m.rd(0x60, Y['gp_shadow2'], 1)[0] & 0x40
        check('... the bus as TM5000G left it: REN, no chip reset or IFC, its SRQ flag still set',
              ren1 == ren0 and h.m.chip.log.count('reset') == resets0 and srq0 and srq1,
              (ren0, ren1, srq0, srq1, h.m.chip.log[-6:]))
        check('... the console never asked the driver\'s SRQ check (AH=0Bh clears the program\'s flag)',
              h.srq_calls == 0, h.srq_calls)
        used = h.stack_used()
        check('the stub\'s stack: %d of %d bytes used (Claude Code, typing, the mouse, GPIB), 96 or more spare'
              % (used, h.rstack()), h.rstack() - used >= 96, used)
        check('... the bridge holds no answer and no SRQ', bridge_quiet(h), (h.nano.srq, h.nano.lnrdy))
        h.k.key('1'); h.k.key('A', settle=False); h.k.settle(60)
        scr = h.m.text_screen()
        check('TM5000G talks to the bus as before: auto-detect finds FG5010, 8753D, DC5009 (no key pressed)',
              all(x in scr for x in ('FG5010', '8753D', 'DC5009')), scr)
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()


def t_driver():
    """The console on the kernel's GPIB driver 1.23: the frame check the
    driver keeps as it moves the bytes, the SRQ interrupt's count (read, never
    AH=0Bh) to take each answer as it comes and to sleep till it, GF_WAKE so
    the Pi rings an idle console, and never a ring once the console has gone
    back to the program.  GPIBIRQ=0: polled, as before."""
    for irq in (True, False):
        what = 'SRQ interrupt' if irq else 'GPIBIRQ=0'
        h = Res(ini=None if irq else b'GPIBIRQ=0\r\n', pico=True); h.boot()
        try:
            h.cmd('claude /r')
            h.cmd('emsuse')
            h.press(HOT)
            h.has('Welcome to Claude Code', 30)
            st0, k0, p0, d0, n0 = dict(h.link.stats), h.rv('n_kok', 2), h.spolls, h.pit_dues, h.naps
            h.term_type('big'); h.press(ENTER)
            ok = h.has('line 59', 60) and in_step(h)
            st = {k: v - st0.get(k, 0) for k, v in h.link.stats.items()}
            kok, polls, dues, naps = h.rv('n_kok', 2) - k0, h.spolls - p0, h.pit_dues - d0, h.naps - n0
            seg = h.rv('irq_ptr', 4)[2:]
            check('[%s] the console checks the Pi\'s frames by the driver\'s sum (1.23): all %d of them'
                  % (what, st.get('tx_frames', 0)),
                  ok and h.rv('ksum') == 1 and h.rv('use_fl') == 2 and st.get('tx_frames', 0) > 5   # (use_fl 1 before audit3 R55)
                  and abs(kok - st['tx_frames']) <= 1           # (the two counts read a frame apart at most)
                  and h.rv('n_bad', 2) == 0, (ok, h.rv('ksum'), kok, st))
            check('[%s] ... and its own go with the check the driver adds (02h AL=3), every one good at the Pi'
                  % what, h.rv('ksum') == 1 and h.rv('use_fl') == 2 and st.get('rx_fletcher') == st.get('rx_frames') > 5
                  and not st.get('rx_bad'), st)
            if irq:
                check('the SRQ interrupt\'s count found (AH=0Eh, the kernel\'s) and GF_WAKE offered',
                      seg == b'\x60\x00' and h.rv('wake_ok') == 1 and h.link.grid_wake, (seg, h.rv('wake_ok')))
                check('... each answer taken at its SRQ, the PIT never asked: %d serial polls for %d frames'
                      % (polls, st.get('rx_frames', 0)), polls <= st['rx_frames'] * 1.2 + 2 and dues == 0, (polls, dues, st))
                check('... asleep (HLT) till the SRQ while an answer is due: %d times' % naps, naps > 0, naps)
            else:
                check('GPIBIRQ=0: never asleep while an answer is due', naps == 0, naps)
                check('GPIBIRQ=0: no count, no GF_WAKE, polled by the PIT (%d looks; %d serial polls for %d frames)'
                      % (dues, polls, st.get('rx_frames', 0)), seg == b'\x00\x00' and h.rv('wake_ok') == 0
                      and not h.link.grid_wake and dues > 0, (seg, h.rv('wake_ok'), polls, dues))
            check('[%s] ... never the driver\'s SRQ check (AH=0Bh)' % what, h.srq_calls == 0, h.srq_calls)
            # the Pi has something for the console once it is quiet (polling once a second): with the
            # interrupt it rings, and the console POLLs at once
            h.run_until(lambda: False, 3)
            r0, t0 = h.link.stats.get('rang', 0), h.m.us
            h.link.send(glp.P_TITLE, b'Rung up')
            ok = h.run_until(lambda: 'Rung up' in h.band(), 3)
            ms, rang = (h.m.us - t0) / 1000, h.link.stats.get('rang', 0) - r0
            if irq:
                check('a title from the Pi while the console is quiet: it rings, the band has it in %.0f ms' % ms,
                      ok and rang > 0 and ms < 100, (ok, rang, ms, h.band()))
                # the console down while TYPE's keys wait: nothing rings
                res = {}
                th = threading.Thread(target=lambda: res.update(v=h.router.term.tools.request(
                    json.dumps({'tool': 'grid_type', 'arguments': {'keys': '{WAIT 3}', 'timeout': 30}}).encode()
                    + b'\n')))
                th.start()
                down = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 20)
                r1 = h.link.stats.get('rang', 0)
                h.link.send(glp.P_TITLE, b'While the keys wait')
                quiet = h.run_until(lambda: not bridge_quiet(h) or h.link.stats.get('rang', 0) != r1, 1)
                h.wait(lambda: not th.is_alive() and h.up(), 30); th.join(30)
                res = res.get('v')
                check('... while TYPE\'s keys wait (the console down): no ring, the bridge holds no SRQ',
                      down and not quiet and res and not res[1], (down, quiet, h.link.stats, res))
                # a TYPE the Pi gives up on while its keys still wait (the console still down): no ring
                # after it either, until the console is heard from again
                h.run_until(lambda: in_step(h, 0.1), 10)
                g, res = h.router.term.grid, {}
                def give_up():
                    try: res['v'] = g.type_keys(b'\xff\xff\xc8', timeout=1)        # (an 11 s wait; 1 s for it)
                    except Exception as e: res['e'] = str(e)
                th = threading.Thread(target=give_up); th.start()
                down = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 20)
                h.pi_wait(lambda: not th.is_alive(), 10); th.join(10)
                r1 = h.link.stats.get('rang', 0)
                h.link.send(glp.P_TITLE, b'Given up on')
                rings = h.run_until(lambda: h.up() or not bridge_quiet(h) or h.link.stats.get('rang', 0) != r1, 2)
                gated = not h.router.term.may_ring()
                back = h.wait(lambda: h.up(), 20) and h.pi_wait(lambda: not g.type_out, 10)
                check('... a TYPE given up on while its keys wait: no ring while the console is down, and rings '
                      'again once it is back', down and 'did not answer' in res.get('e', '') and not rings and gated
                      and back and h.router.term.may_ring(), (down, res, rings, gated, back, h.link.stats))
                # the user goes back: nothing rings while EMSUSE runs, whatever the Pi has
                h.run_until(lambda: in_step(h, 0.1), 10)
                h.press(HOT)
                h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
                away = h.pi_wait(lambda: h.router.term.away, 10)
                r1 = h.link.stats.get('rang', 0)
                h.link.send(glp.P_TITLE, b'Nobody there')
                rings = h.run_until(lambda: not bridge_quiet(h) or h.link.stats.get('rang', 0) != r1, 2)
                check('... gone back to the program: no ring, the bridge holds no SRQ for it',
                      away and not rings, (away, h.link.stats, h.nano.srq))
                # a second session in the same boot: the answers at their SRQ as in the first (keys typed only
                # once the link is up again: before its HELLO the console drops them)
                h.press(HOT)
                up = h.wait(lambda: h.up() and h.rv('connected') == 1 and h.rv('lstate') == 1, 10)
                h.run_until(lambda: in_step(h, 0.1), 10)
                d2, n2, f2 = h.pit_dues, h.naps, h.link.stats['rx_frames']
                h.term_type('diff'); h.press(ENTER)
                ok = h.has('int rate = 5', 60) and in_step(h)
                check('a second session in the same boot: each answer at its SRQ (%d frames, %d sleeps), the PIT '
                      'never asked' % (h.link.stats['rx_frames'] - f2, h.naps - n2),
                      up and ok and h.rv('srq_held') == 0 and h.pit_dues == d2 and h.naps > n2,
                      (up, ok, h.rv('srq_held'), h.pit_dues - d2, h.m.irqs5, h.m.u16(0x60, h.m.Y['gp_nsrq'])))
                h.press(HOT)
                h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
                h.k.key(ESC)
                check('EMSUSE afterwards', 'EMSUSE: 0 keys, 0 bad' in h.m.text_screen(), h.m.text_screen())
            else:
                check('GPIBIRQ=0: the title at the next idle POLL (%.0f ms), no ring' % ms, ok and rang == 0,
                      (ok, rang, ms))
            ok, why = clean(h)
            check('[%s] no link failure, nothing wrong in gridlink\'s log' % what, ok, why)
        finally:
            h.close()
    # an instrument of the paused program holding SRQ: the bridge's SRQ makes no edge, so no interrupt;
    # an answer found at a tick's look says so, and the console polls by the PIT (a boot of its own)
    h = Res(pico=True); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('emsuse')
        h.press(HOT)
        up = h.has('Welcome to Claude Code', 30) and in_step(h)
        h.m.chip.int_line = lambda: bool(h.m.chip.imr2 & 0x40)
        d1, f1 = h.pit_dues, h.link.stats['rx_frames']
        h.term_type('diff'); h.press(ENTER)
        ok = h.has('int rate = 5', 60) and in_step(h)
        check('the SRQ line held by another device: the console finds it out (%d frames) and polls by the PIT '
              '(%d looks)' % (h.link.stats['rx_frames'] - f1, h.pit_dues - d1),
              up and ok and h.rv('srq_held') == 1 and h.pit_dues > d1, (up, ok, h.rv('srq_held'), h.screen()))
        n2, f2 = h.naps, h.link.stats['rx_frames']
        # another device's SRQ edge meanwhile (the driver's count bumped just after a frame went): the line still held
        from unicorn import UC_HOOK_CODE
        lw, bumped, sent = 0xE0000 + h.rsym['link_wait'], [], [h.rv('t_sent', 2)]
        def foreign(uc, addr, size, ud):
            if bumped or h.m.ems_reg[0] != h.m.rd(h.stub(), h.sym['r_hw'], 1)[0]: return
            t, sent[0] = sent[0], h.rv('t_sent', 2)
            if t != sent[0] and h.rv('srq_held') == 1 and not h.nano.srq:
                bumped.append(h.m.us)
                h.m.wr(0x60, h.m.Y['gp_nsrq'], struct.pack('<H', (h.m.u16(0x60, h.m.Y['gp_nsrq']) + 1) & 0xFFFF))
        hk = h.m.mu.hook_add(UC_HOOK_CODE, foreign, None, lw, lw); h.m.mu.ctl_remove_cache(lw, lw + 1)
        h.term_type('big'); h.press(ENTER)
        ok = h.has('line 59', 60) and in_step(h)
        h.m.mu.hook_del(hk)
        check('... and from then on never asleep waiting for an SRQ that can\'t come (%d frames), another '
              'device\'s SRQ edge meanwhile too' % (h.link.stats['rx_frames'] - f2),
              ok and bumped and h.naps == n2 and h.rv('srq_held') == 1 and h.link.stats['rx_frames'] - f2 > 3,
              (ok, bumped, h.naps - n2, h.rv('srq_held')))
        # the line let go: the first answer's SRQ edge clears srq_held (X49; it was kept till HELLO)
        del h.m.chip.int_line
        n3 = h.naps
        h.term_type('freed'); h.press(ENTER)
        ok = h.has('You said: freed', 60) and in_step(h)
        check('... the line let go: an SRQ edge again ends it, the console asleep till the SRQ again (%d times)'
              % (h.naps - n3), ok and h.rv('srq_held') == 0 and h.naps > n3, (ok, h.rv('srq_held'), h.naps - n3))
        ok, why = clean(h)
        check('... no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()

def bg_looks(h):
    """M4's background looks, counted from the console's own code (its page in window 0): how many, how many
    found work (bg_pass.w), and how long each held the program, in simulated µs: [(µs, found work)]."""
    st = {'n': 0, 'work': 0, 'held': [], 't0': None, 'wk': False, 'kept': 0}
    a0, aw = (0xE0000 + h.rsym[n] for n in ('bg_pass', 'bg_pass.w'))
    watch, rb = h.m.watch, h.sym['..@r_back']
    def w(addr):
        if addr != a0 and addr != aw and (st['t0'] is None or (addr - rb) & 15):
            watch(addr); return                 # (none of the three below: r_back's is stub*16 + rb)
        stub = h.stub()
        if stub != 0xF000 and h.m.ems_reg[0] == h.m.rd(stub, h.sym['r_hw'], 1)[0]:
            if addr == a0:
                st['n'] += 1; st['t0'] = h.m.us; st['wk'] = False
                st['kept'] += h.rv('req_ready')        # (a request the console took on its way out)
            elif addr == aw: st['work'] += 1; st['wk'] = True
            elif addr == stub * 16 + rb and st['t0'] is not None:   # (back in the stub)
                st['held'].append((h.m.us - st['t0'], st['wk'])); st['t0'] = None
        watch(addr)
    h.m.watch = w
    return st

def r_bgon(h): return h.m.rd(h.stub(), 0x10F, 1)[0]
def srq_state(h):
    """The program's view of SRQ: the driver's latch (AH=0Bh's) and its interrupt count."""
    Y = h.m.Y
    return h.m.rd(0x60, Y['gp_shadow2'], 1)[0] & 0x40, h.m.u16(0x60, Y['gp_nsrq'])

def t_bg():
    """M4 (CLAUDE 1.10): Claude works in the background while the user is back in the program.  A quiet
    bridge (fw 2026-10-24: the status byte, no SRQ line); the stub calls the console every ~220 ms at the
    program's key calls; it serial-polls the bridge and, when the Pi has rung, runs the link without drawing:
    files and GPIB, and (CLAUDE 1.11) SCREEN; not TYPE.  The program's screen, keys, EMS windows and SRQ latch
    untouched."""
    h = Res(pico='quiet', more={'A:\\BIG.TXT': BIG, 'A:\\CRITKEY.COM': open(os.path.join(CL, 'CRITKEY.COM'), 'rb').read(),
                                'A:\\ZZ.DAT': ZZ}); h.boot()
    try:
        looks = bg_looks(h)
        make_bad(h, ZZ)
        h.cmd('claude /r')
        h.cmd('emsuse')
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and h.has('Welcome to Claude Code', 30)
        t = h.router.term
        check('a quiet bridge: the console offers the background (GF_BG), the Pi takes it up (HF_BG)',
              up and t.gflags & glp.GF_BG and t.bg and h.rv('bg_ok') == 1 and not h.transport.proto.quiet,
              (up, t.gflags, t.bg, h.rv('bg_ok')))
        kinds = []                              # what the Pi sends the console while the user is away
        answer = h.link._answer
        h.link._answer = lambda k, p: (t.away and kinds.append(k), answer(k, p))
        statuses = []                           # and the REPLYs' statuses from it meanwhile
        on_reply = t.grid.on_reply
        t.grid.on_reply = lambda b: (t.away and len(b) >= 2 and statuses.append(b[1]), on_reply(b))
        # a call on its way as the user goes back: not ended (as without the background), it runs there,
        # whether the console takes it on its way out (then the first look runs it) or the Pi rings later
        h.run_until(lambda: False, 3)           # (quiet: then the console polls once a second)
        t1 = h.rv('t_last', 2)
        quiet = h.run_until(lambda: h.rv('t_last', 2) != t1 and h.rv('lstate') == 1 and h.rv('pi_active') == 0
                            and h.rv('txq_n') == 0, 5)
        r = {}
        th = threading.Thread(target=lambda: r.update(v=t.tools.request(json.dumps(
            {'tool': 'grid_files', 'arguments': {'action': 'list', 'path': 'A:\\'}}).encode() + b'\n')))
        th.start()
        end = time.time() + 10
        while not h.link.outq and time.time() < end: time.sleep(0.01)
        # (srq_held cleared: the pop-up's back-to-back polls can set it, two SRQ edges merged, until the next
        # edge, which a quiet bridge never makes, or HELLO; from here on only a wait for an SRQ that a quiet
        # bridge never sends could set it again)
        h.m.ems_store[h.page() * 0x4000 + h.rsym['srq_held']] = 0
        h.press(HOT)                            # (before the console's next poll: its EVENT's answer is the REQUEST)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.wait(lambda: not th.is_alive(), 20); th.join(30)
        res = r.get('v')
        check('a grid_files call on its way as the user goes back: taken on the way out, answered at the first '
              'background look', quiet and back and res and not res[1] and 'BIG.TXT' in res[0][0]['text']
              and looks['kept'] == 1, (quiet, back, res, looks['kept']))
        away = h.pi_wait(lambda: t.away and h.transport.proto.quiet, 10)
        vram0, bios0 = h.m.rd(0xB800, 0, 4000), h.m.rd(0x40, 0x49, 0x1E)
        Y = h.m.Y                               # (the latch cleared, as after the program's AH=0Bh: any SRQ
        h.m.wr(0x60, Y['gp_shadow2'], bytes([h.m.rd(0x60, Y['gp_shadow2'], 1)[0] & ~0x40 & 0xFF]))   #  shows)
        srq0 = srq_state(h)
        f0 = h.link.stats['rx_frames']
        check('back to EMSUSE: the stub looks at its key calls (r_bgon 1), the bridge made quiet',
              back and away and r_bgon(h) == 1, (back, away, r_bgon(h)))
        n0, w0, p0 = looks['n'], looks['work'], h.spolls
        h.run_until(lambda: False, 3)
        idle = [us for us, wk in looks['held'][-(looks['n'] - n0):] if not wk]
        check('idle: a look every ~220 ms (%d in 3 s), a serial poll each (%d), at most %d µs, nothing sent to the Pi'
              % (looks['n'] - n0, h.spolls - p0, max(idle or [0])), 10 <= looks['n'] - n0 <= 16
              and h.spolls - p0 == looks['n'] - n0 and looks['work'] == w0
              and idle and max(idle) < 3000 and h.link.stats['rx_frames'] == f0,
              (looks['n'] - n0, h.spolls - p0, looks['work'] - w0, idle[:5], h.link.stats['rx_frames'] - f0))
        h.paint_stack()
        t.feed(b'\r\nWritten on the Pi meanwhile\r\n')        # (Claude Code's screen changes while away)
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'})
        check('away: grid_files list, in the background', r and not r[1] and 'BIG.TXT' in r[0][0]['text'], r)
        r = tool(h, 'grid_files', {'action': 'read', 'path': 'A:\\BIG.TXT'})
        check('... read: BIG.TXT whole (%d bytes, three reads)' % len(BIG),
              r and not r[1] and r[0][0]['text'] == BIG.decode().replace('\r\n', '\n'), r and r[0][0]['text'][-200:])
        note = 'written in the background\n' * 900                                          # 23,400 bytes
        r = tool(h, 'grid_change_files', {'action': 'write', 'path': 'A:\\NOTE.TXT', 'content': note})
        r2 = tool(h, 'grid_files', {'action': 'read', 'path': 'A:\\NOTE.TXT'})
        check('... write (%d bytes) and read back' % len(note), r and not r[1] and r2 and r2[0][0]['text'] == note,
              (r, r2 and r2[0][0]['text'][-100:]))
        r = tool(h, 'grid_files', {'action': 'read', 'path': 'A:\\ZZ.DAT'})
        check('... a disk error: the call fails (CRC), no prompt, EMSUSE\'s screen untouched',
              r and r[1] and 'data error (CRC)' in r[0][0]['text'] and h.m.rd(0xB800, 0, 4000) == vram0, r)
        r = tool(h, 'gpib_read', {'action': 'scan'})
        r2 = tool(h, 'gpib_send', {'action': 'query', 'address': 29, 'command': 'ID?'})
        check('... gpib_read scan and gpib_send query (the DC5009\'s ID?)',
              r and not r[1] and r[0][0]['text'] == 'Responding addresses: 6, 14, 29' and r2 and not r2[1]
              and 'TEK/DC5009' in r2[0][0]['text'], (r, r2))
        G, out = t.grid, {}
        def scr():
            try: out['s'] = G.call(glp.OP_SCREEN, b'\0', timeout=20)
            except Exception as e: out['s'] = e
        th = threading.Thread(target=scr); th.start()
        h.run_until(lambda: not th.is_alive(), 20); th.join(10)
        s = out.get('s')
        check('... SCREEN in a pass (CLAUDE 1.11): EMSUSE\'s text page as it is, byte for byte',
              isinstance(s, tuple) and s[0] == 0 and s[1][9:] == h.m.rd(0xB800, 0, 4000), str(s)[:200])
        r = tool(h, 'grid_type', {'keys': 'x'})
        check('... grid_type needs the console: refused, the tools that work named',
              r and r[1] and 'in the background' in r[0][0]['text'] and 'grid_files' in r[0][0]['text'], r)
        busy = [us for us, wk in looks['held'] if wk]
        check('EMSUSE\'s screen, the BIOS\'s video data and mode 3 untouched through %d passes with work (the '
              'longest held it %d ms)' % (len(busy), max(busy or [0]) // 1000),
              h.m.rd(0xB800, 0, 4000) == vram0 and h.m.rd(0x40, 0x49, 0x1E) == bios0 and h.m.mode() == 3
              and h.inpop() == 0 and len(busy) >= 6, (len(busy), busy[:8]))
        check('no SRQ from the bridge all the while: the program\'s SRQ latch and the interrupt count as they were; '
              'the console never waited for one (srq_held 0: the PIT\'s polls)',
              srq_state(h) == srq0 and h.rv('srq_held') == 0, (srq_state(h), srq0, h.rv('srq_held')))
        check('... the console never asked the driver\'s SRQ check (AH=0Bh)', h.srq_calls == 0, h.srq_calls)
        used = h.stack_used()
        check('the stub\'s stack: %d of %d bytes used in the background, 96 or more spare' % (used, h.rstack()),
              h.rstack() - used >= 96, used)
        # a request the GRiD hasn't taken when its call gives up (the program not at a key call): withdrawn,
        # so it can't run later, after Claude was told it failed
        G, out = t.grid, {}
        def call():
            try: out['r'] = G.call(glp.OP_WRITE, struct.pack('<BI', 0, 0) + b'A:\\LATE.TXT\0' + b'late', timeout=1)
            except Exception as e: out['r'] = e
        th = threading.Thread(target=call); th.start(); th.join(10)        # (the GRiD frozen meanwhile)
        h.run_until(lambda: False, 2)
        check('a call given up on before the GRiD took it: withdrawn, never run (no LATE.TXT)',
              'withdrawn' in str(out.get('r')) and 'A:\\LATE.TXT' not in h.m.fs, (out, sorted(h.m.fs)[:20]))
        check('the Pi sent the console nothing but REQUESTs and NOPs meanwhile (no CELLS, no TITLE: %d frames)'
              % len(kinds), kinds and set(kinds) <= {glp.P_REQUEST, glp.P_REQUEST | glp.MORE, glp.P_NOP},
              sorted(set(kinds)))
        nreq = sum(1 for st in statuses if st != 0xF6)  # (the requests run, the SCREEN among them)
        h.k.key('a'); h.k.key('b')
        # the next pop-up: the count in the band, the bridge rings again
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and in_step(h)
        check('the next pop-up: the band says how many requests ran meanwhile (%d); what Claude Code wrote '
              'meanwhile there; the bridge not quiet' % nreq,
              up and ('  %d in background' % nreq) in h.band() and 'Written on the Pi meanwhile' in h.screen() and not h.transport.proto.quiet and h.rv('srq_held') == 0,
              (up, h.band(), h.transport.proto.quiet))
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        check('EMSUSE afterwards: the keys typed meanwhile, its four EMS windows whole through every look',
              'EMSUSE: 2 keys, 0 bad' in h.m.text_screen(), h.m.text_screen())
        # at the prompt: LCMD reads its keys through DOS (the kernel's key wait): files there too
        h.k.key('cls'); h.k.key(ENTER); h.k.settle(2)
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and in_step(h)
        h.press(HOT)
        h.wait(lambda: h.inpop() == 0, 5)
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'})
        check('away at the prompt (the kernel\'s key wait, DOS one call deep): grid_files list',
              up and r and not r[1] and 'NOTE.TXT' in r[0][0]['text'], (up, r))
        # a program's own INT 24h handler waiting for a key: DOS busy, GPIB still
        h.k.key('cls'); h.k.key(ENTER); h.k.key('critkey'); h.k.key(ENTER, settle=False); h.k.settle(10)
        waits = 'CRITKEY waits' in h.m.text_screen()
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'})
        r2 = tool(h, 'gpib_send', {'action': 'query', 'address': 6, 'command': 'ID?'})
        r3 = tool(h, 'grid_program', {})
        check('over a program\'s INT 24h handler waiting for a key: files F7h (DOS busy), GPIB works, and the '
              'screen too (no DOS: "CRITKEY waits")',
              waits and r and r[1] and 'DOS is busy' in r[0][0]['text'] and r2 and not r2[1]
              and 'TEK/FG5010' in r2[0][0]['text'] and r3 and not r3[1] and 'CRITKEY waits' in r3[0][1]['text'],
              (waits, r, r2, r3))
        h.k.key('x'); h.k.settle(10)
        h.k.key(ESC); h.k.settle(2)
        # CLAUDE.COM takes the link: no more looks till the next pop-up; its HELLO makes the bridge loud again
        h.k.key('cls'); h.k.key(ENTER); h.k.key('claude /t'); h.k.key(ENTER, settle=False)
        ok = h.has('Welcome to Claude Code', 30)
        check('CLAUDE /T meanwhile: no background looks (r_bgon 0), the bridge not quiet, the Pi not away',
              ok and r_bgon(h) == 0 and not h.transport.proto.quiet and not t.away, (ok, r_bgon(h), t.away))
        h.m.wr(h.stub(), 0x10F, b'\1')         # (as a CLAUDE.COM before 1.10 would leave it)
        n0 = looks['n']
        h.term_type('hello'); h.press(ENTER)
        ok = h.has('You said: hello', 30)
        h.run_until(lambda: False, 2)
        check('... and with r_bgon left on (an older CLAUDE.COM): no looks while CLAUDE runs (r_off)',
              ok and looks['n'] == n0, (ok, looks['n'] - n0))
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()
    # a bridge that can't be quiet (older firmware): no background, the tools refused as before
    h = Res(pico=True); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('emsuse')
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen)
        h.press(HOT)
        h.wait(lambda: h.inpop() == 0, 5)
        t = h.router.term
        h.pi_wait(lambda: t.away, 10)
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'})
        check('a bridge that can\'t be quiet: no HF_BG, no looks (r_bgon 0), the tools refused while away',
              up and not t.bg and h.rv('bg_ok') == 0 and r_bgon(h) == 0 and r and r[1]
              and 'no GRiD tool works' in r[0][0]['text'], (up, t.bg, h.rv('bg_ok'), r_bgon(h), r))
    finally:
        h.close()

BIG = b''.join(b'line %05d of BIG.TXT, read from the pop-up\r\n' % i for i in range(500))    # 21,500 bytes
ZZ = b'ZZ.DAT: its sectors are made bad\r\n' * 62                                            # 2,108 bytes

def kvars(h):
    """The kernel's DTA and INT 23h/24h: the program's, before and after."""
    return h.m.rd(0x60, h.m.Y['dta'], 4), h.m.rd(0, 0x23 * 4, 8)

def make_bad(h, data):
    """The floppy's sectors holding data: they don't read any more."""
    img = bytes(h.m.drives[0].img)
    at = img.find(data[:512])
    assert at >= 0 and at % 512 == 0, at
    h.m.drives[0].bad.update(range(at // 512, (at + len(data) + 511) // 512))

def astack(h, paint=False):
    """The kernel's stack for a call made inside another (512 bytes under
    astack_top): painted, or how deep it went."""
    lo, n = h.m.Y['kstack_top'], h.m.Y['astack_top'] - h.m.Y['kstack_top']
    if paint: h.m.wr(0x60, lo, b'\xA5' * n); return n
    d = h.m.rd(0x60, lo, n)
    return n - next((i for i, b in enumerate(d) if b != 0xA5), n)

def files_work(h, what):
    """The file tools through the console: list, read (three 8 KB reads),
    write (through NAME.$$$, 8 KB requests), info, rename, mkdir, rmdir,
    delete, free; a disk error a failed call, no prompt."""
    r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'})
    check('%s: grid_files list' % what, r and not r[1] and 'BIG.TXT' in r[0][0]['text'], r)
    r = tool(h, 'grid_files', {'action': 'read', 'path': 'A:\\BIG.TXT'})
    check('... read: BIG.TXT whole (%d bytes, three reads)' % len(BIG),
          r and not r[1] and r[0][0]['text'] == BIG.decode().replace('\r\n', '\n'), r and r[0][0]['text'][-200:])
    note = 'written from resident Claude\'s pop-up\n' * 600                                # 23,400 bytes
    r = tool(h, 'grid_change_files', {'action': 'write', 'path': 'A:\\NOTE.TXT', 'content': note})
    r2 = tool(h, 'grid_files', {'action': 'read', 'path': 'A:\\NOTE.TXT'})
    check('... write (%d bytes) and read back' % len(note), r and not r[1] and r2 and r2[0][0]['text'] == note,
          (r, r2 and r2[0][0]['text'][-100:]))
    steps = [('grid_change_files', {'action': 'mkdir', 'path': 'A:\\SUB'}),
             ('grid_change_files', {'action': 'rename', 'path': 'A:\\NOTE.TXT', 'to': 'A:\\SUB\\NOTE2.TXT'}),
             ('grid_files', {'action': 'info', 'path': 'A:\\SUB\\NOTE2.TXT'}),
             ('grid_change_files', {'action': 'delete', 'path': 'A:\\SUB\\NOTE2.TXT'}),
             ('grid_change_files', {'action': 'rmdir', 'path': 'A:\\SUB'}),
             ('grid_files', {'action': 'free', 'path': 'A:'})]
    rs = [tool(h, n, a) for n, a in steps]
    check('... mkdir, rename, info, delete, rmdir, free',
          all(r and not r[1] for r in rs) and '%d bytes' % len(note.replace('\n', '\r\n')) in rs[2][0][0]['text']
          and 'bytes free of' in rs[5][0][0]['text'], rs)
    r = tool(h, 'grid_files', {'action': 'read', 'path': 'A:\\ZZ.DAT'})
    check('... a disk error (ZZ.DAT\'s sectors bad): the call fails (CRC), no prompt, the console still up',
          r and r[1] and 'data error (CRC)' in r[0][0]['text'] and h.up() and in_step(h), (r, h.screen()))

def t_ops():
    """Files and GPIB from the pop-up (OPS.INC): over a program at its own
    INT 16h call (DOS not busy) and over COPY CON (the kernel's key wait,
    DOS one call deep: ours runs on the kernel's second stack); DOS busy
    (F7h, the band says so) over a program's INT 24h handler waiting for a
    key; GPIB everywhere.  The program's DTA, INT 23h and 24h as they were."""
    h = Res(more={'A:\\BIG.TXT': BIG, 'A:\\ZZ.DAT': ZZ,                # (DEFRAG.COM: EMSUSE under DEFRAG's name)
                  'A:\\DEFRAG.COM': open(os.path.join(CL, 'EMSUSE.COM'), 'rb').read()}); h.boot()
    try:
        make_bad(h, ZZ)
        h.cmd('claude /r')
        h.cmd('emsuse')
        kv0 = kvars(h)
        h.paint_stack()
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and h.has('Welcome to Claude Code', 30)
        hello = h.router.term.hello
        check('HELLO offers files and GPIB (ops=files,gpib,bgscreen; req=8700: 8 KB writes); the band doesn\'t say DOS busy',
              up and hello.get('ops') == 'files,gpib,bgscreen' and hello.get('req') == '8700' and 'DOS busy' not in h.band(),
              (up, hello, h.band()))
        check('(the disk cache on: its pages in EMS, the kernel\'s copies through windows clear of the buffer)',
              h.m.u16(0x60, h.m.Y['ems_tcpg']) != 0)
        files_work(h, 'over EMSUSE (DOS not busy)')
        # a request while another's reply is on its way (gridlink gave up on that call): dropped, not
        # gathered over the reply's bytes (the same buffer) or run with the waiting request's op
        G, out = h.router.term.grid, {}
        def call(k, op, args, tmo):
            try: out[k] = G.call(op, args, timeout=tmo)
            except Exception as e: out[k] = e
        rd = threading.Thread(target=call, args=('read', glp.OP_READ, struct.pack('<IH', 0, 8192) + b'A:\\BIG.TXT\0', 30))
        wr = threading.Thread(target=call, args=('write', glp.OP_WRITE, struct.pack('<BI', 0, 0) + b'A:\\X.DAT\0'
                                                 + b'\xAA' * 6000, 4))      # (longer than the reply's first frame)
        rd.start()                      # (the write once the read's reply is on its way)
        h.pi_wait(lambda: h.rv('reply_busy') == 1, 20)
        wr.start()
        h.pi_wait(lambda: len(out) == 2, 40)
        check('a request while a read\'s reply goes: the reply whole (8 KB of BIG.TXT), the second (a 6 KB write) '
              'dropped', out.get('read') == (0, BIG[:8192]) and isinstance(out.get('write'), Exception),
              {k: str(v)[:80] for k, v in out.items()})
        out.clear()                     # a device's name past gridlink's own check: refused, not opened
        th = threading.Thread(target=call, args=('con', glp.OP_READ, struct.pack('<IH', 0, 100) + b'A:\\CON.TXT\0', 20))
        th.start(); h.pi_wait(lambda: 'con' in out, 30)
        check('a READ of A:\\CON.TXT (the CON device): status 5 at once, no wait for a key',
              out.get('con') == (5, b'') and h.up() and in_step(h), (out, h.screen()))
        r = tool(h, 'gpib_read', {'action': 'scan'})
        check('gpib_read scan: the instruments (6, 14, 29), not the bridge', r and not r[1]
              and r[0][0]['text'] == 'Responding addresses: 6, 14, 29', r)
        r = tool(h, 'gpib_send', {'action': 'query', 'address': 29, 'command': 'ID?'})
        check('gpib_send query: the DC5009 answers ID?', r and not r[1] and 'TEK/DC5009' in r[0][0]['text'], r)
        check('the program\'s DTA, INT 23h and INT 24h as they were', kvars(h) == kv0, (kvars(h), kv0))
        used = h.stack_used()
        check('the stub\'s stack: %d of %d bytes used (files and GPIB too), 96 or more spare'
              % (used, h.rstack()), h.rstack() - used >= 96, used)
        check('... the console in step with the Pi', in_step(h), h.screen())
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        check('EMSUSE afterwards', 'EMSUSE: 0 keys, 0 bad' in h.m.text_screen(), h.m.text_screen())

        # COPY CON: the kernel reading the keyboard, DOS one call deep
        h.k.key('cls'); h.k.key(ENTER); h.k.key('copy con hi.txt'); h.k.key(ENTER); h.k.key('hi')
        text0 = h.m.text_screen()
        kv0 = kvars(h)
        astack(h, paint=True)
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and in_step(h)
        check('over COPY CON: the band doesn\'t say DOS busy', up and 'DOS busy' not in h.band(), h.band())
        files_work(h, 'over COPY CON (DOS one call deep, the kernel\'s key wait)')
        used = astack(h)
        check('... the kernel\'s second stack: %d of 512 bytes used (a disk error\'s INT 24h too), 96 or more spare'
              % used, 512 - used >= 96, used)
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'M:\\'})
        r2 = tool(h, 'grid_change_files', {'action': 'write', 'path': 'M:\\BIG.TXT', 'content': BIG.decode().replace('\r\n', '\n')})
        r3 = tool(h, 'grid_files', {'action': 'read', 'path': 'M:\\BIG.TXT'})
        check('... M: (its pages through a window the buffer isn\'t in): write and read back',
              r and not r[1] and r2 and not r2[1] and r3 and r3[0][0]['text'] == BIG.decode().replace('\r\n', '\n'),
              (r, r2, r3 and r3[0][0]['text'][-100:]))
        check('... the program\'s DTA, INT 23h and INT 24h as they were', kvars(h) == kv0, (kvars(h), kv0))
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5) and h.m.text_screen() == text0
        h.k.key(ENTER); h.k.key(0x2C1A); h.k.key(ENTER)
        o = h.cmd('type hi.txt')
        check('... back: COPY CON goes on (the file has what was typed)',
              back and 'hi' in [l.strip() for l in o.split('\n')], (back, o))

        # a program's own INT 24h handler waiting for a key: DOS busy
        h.k.key('cls'); h.k.key(ENTER); h.k.key('critkey'); h.k.key(ENTER, settle=False); h.k.settle(10)
        waits = 'CRITKEY waits' in h.m.text_screen()
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and in_step(h)
        check('over a program\'s INT 24h handler waiting for a key: the band says DOS busy',
              waits and up and 'DOS busy' in h.band(), (waits, up, h.band()))
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'})
        check('... a file request answered F7h, DOS busy: the tool says why',
              r and r[1] and 'DOS is busy' in r[0][0]['text'], r)
        r = tool(h, 'gpib_send', {'action': 'query', 'address': 6, 'command': 'ID?'})
        check('... GPIB still works there (the FG5010 answers ID?)', r and not r[1] and 'TEK/FG5010' in r[0][0]['text'], r)
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key('x'); h.k.settle(10)
        check('... back: the handler gets its key, the read fails, CRITKEY goes on (one INT 24h)',
              'CRITKEY: 1' in h.m.text_screen(), h.m.text_screen())
        # its handler still in INT 24h, CRITKEY at its own key wait (DOS not busy)
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and in_step(h)
        r = tool(h, 'grid_files', {'action': 'read', 'path': 'A:\\ZZ.DAT'})
        n24 = h.m.rd(h.m.u16(0, 0x24 * 4 + 2), 0x100 + open(os.path.join(CL, 'CRITKEY.COM'), 'rb').read().index(b'CRITKEY: ') + 13, 1)[0]   # (n24, after s_done and s_n)
        check('... over CRITKEY waiting for Esc (its INT 24h handler still in): a disk error fails our call, '
              'its handler not called', up and r and r[1] and 'data error (CRC)' in r[0][0]['text'] and n24 == 1
              and 'CRITKEY waits' not in h.screen(), (up, r, n24, h.screen()))
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        # DEFRAG (the screen saver's too) writes the disk itself: no file requests over it
        h.k.key('cls'); h.k.key(ENTER); h.k.key('defrag'); h.k.key(ENTER, settle=False); h.k.settle(10)
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and in_step(h)
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'})
        check('over DEFRAG.COM (DOS not busy): the band says DOS busy, a file request F7h',
              up and 'DOS busy' in h.band() and r and r[1] and 'DOS is busy' in r[0][0]['text'], (up, h.band(), r))
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()

def t_ops_codes():
    """audit3 R51: OPS.INC's file and GPIB requests from the pop-up, each one's status and reply (DOS's
    error codes, the driver's) as claude_kernel's OPS_PROBE has them: the table test_claude_kernel's test_ops_codes
    holds CLAUDE.COM to (the same source in both binaries)."""
    h = Res(); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('emsuse')
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and h.has('Welcome to Claude Code', 30)
        got = CK.ops_probe(h.router.term.grid, lambda c: h.pi_wait(c, 40), h.m.chip.devices)
        want = CK.ops_want('rcon')
        bad = [(g, w) for g, w in zip(got, want) if g != w]
        check('the file and GPIB requests\' statuses and replies: %d as CLAUDE.COM\'s' % len(want),
              up and len(got) == len(want) and not bad, (up, bad or got))
        check('... the console still up, in step', h.up() and in_step(h), h.screen())
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()

def t_ops_mt():
    """With Lodestone's tasks (MULTITASK=1): files over a program at its own
    INT 16h call; DOS busy over COPY CON (MT's key wait calls INT 16h from
    MT's segment, as its INT 24h prompt does: not the kernel's)."""
    mt = open(os.path.join(GOS, 'src', 'LODEMT.SYS'), 'rb').read()
    h = Res(ini=b'MULTITASK=1\r\n', more={'A:\\BIG.TXT': BIG, 'A:\\LODEMT.SYS': mt}); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('emsuse')
        mt_on = h.m.u16(h.stub(), h.sym['r_mt'] + 2) != 0
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and in_step(h)
        r = tool(h, 'grid_files', {'action': 'read', 'path': 'A:\\BIG.TXT'})
        check('MULTITASK=1 (the stub has MT\'s address), over EMSUSE: files work (BIG.TXT read)',
              mt_on and up and r and not r[1] and r[0][0]['text'] == BIG.decode().replace('\r\n', '\n'),
              (mt_on, up, r and r[0][0]['text'][-100:]))
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        h.k.key('cls'); h.k.key(ENTER); h.k.key('copy con hi.txt'); h.k.key(ENTER)
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and in_step(h)
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'})
        check('... over COPY CON: the band says DOS busy, a file request F7h',
              up and 'DOS busy' in h.band() and r and r[1] and 'DOS is busy' in r[0][0]['text'], (up, h.band(), r))
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(0x2C1A); h.k.key(ENTER)
        ok, why = clean(h)
        check('... no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()

def t_bg_tm():
    """M4 over TM5000G, which looks for keys (through DOS) between its bus work: Claude's files and an
    instrument query in the background, one while its auto-detect runs.  Its screen, its SRQ flag (set as
    if an instrument had asked), REN and the chip as it left them; auto-detect finds its three."""
    if not TR.TM5000G:
        print('(no TM5000G.EXE: skipped)'); return
    h = Res(tm=True, pico='quiet'); h.m.mouse = True; h.boot()
    try:
        looks = bg_looks(h)
        h.cmd('claude /r')
        h.k.key('cls'); h.k.key(ENTER); h.k.key('tm5000g'); h.k.key(ENTER, settle=False); h.k.settle(40)
        h.k.key(ENTER)
        text0 = h.m.text_screen()
        Y = h.m.Y
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen)
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5) and h.pi_wait(lambda: h.router.term.away, 10)
        h.k.settle()
        h.m.wr(0x60, Y['gp_shadow2'], bytes([h.m.rd(0x60, Y['gp_shadow2'], 1)[0] | 0x40]))
        ren0, srq0, resets0 = h.m.rd(0x60, Y['gp_renon'], 1)[0], srq_state(h), h.m.chip.log.count('reset')
        h.srq_calls = 0
        n0 = looks['n']
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'})
        r2 = tool(h, 'gpib_send', {'action': 'query', 'address': 29, 'command': 'ID?'})
        check('back in TM5000G (no key pressed): files and a query in the background, at its key looks (%d)'
              % (looks['n'] - n0), up and back and r and not r[1] and 'TM5000G.EXE' in r[0][0]['text'] and r2
              and not r2[1] and 'TEK/DC5009' in r2[0][0]['text'] and looks['n'] > n0, (up, back, r, r2))
        h.k.settle()
        ren1, srq1 = h.m.rd(0x60, Y['gp_renon'], 1)[0], srq_state(h)
        check('... TM5000G\'s screen untouched; its SRQ flag still set and no SRQ interrupt; REN, no chip reset',
              h.m.text_screen() == text0 and srq1 == srq0 and srq0[0] and ren1 == ren0
              and h.m.chip.log.count('reset') == resets0, (srq0, srq1, ren0, ren1, h.m.text_screen()))
        check('... never the driver\'s SRQ check (AH=0Bh), the bridge holding nothing', h.srq_calls == 0
              and bridge_quiet(h), (h.srq_calls, h.nano.srq, h.nano.lnrdy))
        h.k.key('1'); h.k.key('A', settle=False)
        r = tool(h, 'gpib_send', {'action': 'query', 'address': 6, 'command': 'ID?'})      # (during auto-detect)
        mid = h.m.text_screen()
        h.k.settle(60)
        scr = h.m.text_screen()
        found = ('FG5010', '8753D', 'DC5009')
        check('a query while TM5000G\'s auto-detect polls the bus: answered before it was done, and auto-detect '
              'finds FG5010, 8753D, DC5009', r and not r[1] and 'TEK/FG5010' in r[0][0]['text']
              and not all(x in mid for x in found) and all(x in scr for x in found), (r, mid, scr))
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()

def t_bg_mt():
    """M4 with Lodestone's tasks (MULTITASK=1): the background over the front task's EMSUSE; over COPY CON
    (MT's key wait) files are F7h there as in the pop-up, GPIB works."""
    mt = open(os.path.join(GOS, 'src', 'LODEMT.SYS'), 'rb').read()
    h = Res(ini=b'MULTITASK=1\r\n', pico='quiet', more={'A:\\BIG.TXT': BIG, 'A:\\LODEMT.SYS': mt})
    h.boot()                                    # (ticks on time, irq_exact: the read then lasts 40 ticks, T5c)
    try:
        h.cmd('claude /r')
        h.cmd('emsuse')
        mt_on = h.m.u16(h.stub(), h.sym['r_mt'] + 2) != 0
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen)
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        r = tool(h, 'grid_files', {'action': 'read', 'path': 'A:\\BIG.TXT'})
        check('MULTITASK=1, back in EMSUSE: files in the background (BIG.TXT read)',
              mt_on and up and r and not r[1] and r[0][0]['text'] == BIG.decode().replace('\r\n', '\n'),
              (mt_on, up, r and r[0][0]['text'][-100:]))
        h.k.key(ESC)
        h.k.key('cls'); h.k.key(ENTER); h.k.key('copy con hi.txt'); h.k.key(ENTER)
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'})
        r2 = tool(h, 'gpib_send', {'action': 'query', 'address': 29, 'command': 'ID?'})
        check('... over COPY CON (MT\'s key wait): a file request F7h, GPIB works',
              r and r[1] and 'DOS is busy' in r[0][0]['text'] and r2 and not r2[1] and 'TEK/DC5009' in r2[0][0]['text'],
              (r, r2))
        h.k.key('hi'); h.k.key(0x2C1A); h.k.key(ENTER)
        o = h.cmd('type hi.txt')
        check('... COPY CON goes on (the file has what was typed)', 'hi' in [l.strip() for l in o.split('\n')], o)
        # a link failure in a pass (the Pi answers nothing): the console clears the bridge (SDC) and stops
        # looking; the Pi, told of the SDC, ends the call at once and the tools say so
        h.cmd('emsuse')
        gen = generation(h)
        h.press(HOT)
        popped(h, gen)
        h.press(HOT)
        h.wait(lambda: h.inpop() == 0, 5)
        t = h.router.term
        h.pi_wait(lambda: t.away, 10)
        handle = h.link.handle
        h.link.handle = lambda f: None
        t0 = time.time()
        r = tool(h, 'grid_files', {'action': 'list', 'path': 'A:\\'}, 20, 40)
        h.link.handle = handle
        w = t.why_not('grid_files')
        check('a link failure in a pass: no more looks (r_bgon 0), the call ended at the SDC (%.0f s), the tools '
              'say the user has gone back' % (time.time() - t0), r_bgon(h) == 0 and r and r[1]
              and 'stopped working in the background' in r[0][0]['text'] and w and 'no GRiD tool works' in w,
              (r_bgon(h), r, w))
        # the bridge gone (the next pop-up's background on again): one serial poll that fails, then no looks
        gen = generation(h)
        h.press(HOT)
        popped(h, gen)
        h.press(HOT)
        h.wait(lambda: h.inpop() == 0, 5)
        on = r_bgon(h)
        del h.m.chip.devices[7]
        h.run_until(lambda: False, 2)
        h.k.key('a'); h.k.key(ESC)
        check('the bridge gone while away: the looks stop (r_bgon %d, then 0), the program goes on' % on,
              on == 1 and r_bgon(h) == 0 and 'EMSUSE: 1 keys, 0 bad' in h.m.text_screen(), (on, r_bgon(h), h.m.text_screen()))
        errs = [l for l in h.log if 'Traceback' in str(l)]
        check('... nothing wrong in gridlink\'s log', not h.m.crash and not errs, (h.m.crash, errs))
    finally:
        h.close()


def t_bg_screen():
    """CLAUDE 1.11: grid_program in the background.  Back in the program, Claude reads its screen as it is
    then (copied to the console's windows for the reply, nothing drawn): text with what the user typed since
    the console went, and a graphics screen byte for byte.  grid_type still needs the console."""
    h = Res(pico='quiet'); h.boot()
    try:
        looks = bg_looks(h)
        h.cmd('claude /r')
        h.cmd('testkey')
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen)
        t = h.router.term
        check('HELLO says the console reads the screen in the background (ops=files,gpib,bgscreen)',
              up and t.hello.get('ops') == 'files,gpib,bgscreen', (up, t.hello))
        h.press(HOT)
        back = h.wait(lambda: h.inpop() == 0, 5) and h.pi_wait(lambda: t.away and h.transport.proto.quiet, 10)
        for k in 'abc': h.k.key(k)              # (the user types into TESTKEY meanwhile)
        vram0 = h.m.rd(0xB800, 0, 4000)
        w0 = looks['work']
        r = tool(h, 'grid_program', {})
        check('away: grid_program has TESTKEY\'s screen as it is now ("TESTKEY ready: abc", typed after the '
              'console went), read in a background pass',
              back and r and not r[1] and 'back in the DOS program' in r[0][0]['text']
              and 'TESTKEY ready: abc' in r[0][1]['text'] and looks['work'] > w0 and h.inpop() == 0, r)
        check('... TESTKEY\'s video memory untouched by the read, still mode 3',
              h.m.rd(0xB800, 0, 4000) == vram0 and h.m.mode() == 3, h.m.text_screen())
        r = tool(h, 'grid_type', {'keys': 'x'})
        check('... grid_type still needs the console: refused, grid_program among the tools that work',
              r and r[1] and 'in the background' in r[0][0]['text'] and 'grid_program' in r[0][0]['text'], r)
        # a reply's first bytes still out on the kept screen (a SCREEN's reply cut short by a link failure; here
        # on its row 3): op_bgscreen puts them back on that copy before it keeps the screen again (R50), so
        # they are not in this SCREEN's bytes
        h.rw('borrowed', b'\xEE' * 12); h.rw('borrow_at', struct.pack('<H', 0x10 + 3 * 160 + 20))
        h.rw('borrow_on', b'\1')
        raw = raw_screen(h)
        check('... a background SCREEN with a reply\'s bytes left borrowed: TESTKEY\'s text page byte for byte '
              '(unborrow before the screen is kept)',
              raw is not None and raw[:3] == bytes([3, 1, 0]) and raw[9:] == h.m.rd(0xB800, 0, 4000)
              and h.wait(lambda: h.rv('borrow_on') == 0, 5), raw and (raw[:9], raw[9 + 480:9 + 520]))
        h.k.key(ESC)
        # a graphics screen, of a program started after the console went (no pop-up over it: the mode and the
        # BIOS's data are read then, not the last pop-up's mode 3): GFXUSE in mode 6, its 16 KB byte for byte
        h.cmd('gfxuse 6')
        mode6 = h.m.mode() == 6 and h.inpop() == 0 and t.away
        vram = h.m.rd(0xB800, 0, 0x4000)
        res = tool(h, 'grid_program', {})
        raw = raw_screen(h)
        check('GFXUSE in mode 6, started after the console went: grid_program\'s image (named as the last '
              'pop-up\'s program, "another may run now"), SCREEN\'s bytes its 640x200 as they are',
              mode6 and res and not res[1] and res[0][-1]['type'] == 'image' and 'another may run now' in
              res[0][0]['text'] and raw is not None and raw[:9] == bytes([6, 2, 1, 128, 2, 200, 0, 80, 0])
              and raw[9:] == vram, (mode6, res and res[0][0].get('text'), raw and raw[:9]))
        still6 = h.m.mode() == 6
        h.k.key('x'); h.k.key(ESC)
        check('... GFXUSE afterwards: mode 6 through the reads, its screen and data kept (0 bad)',
              still6 and '0 bad' in h.m.text_screen(), (still6, h.m.text_screen()))
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()


def t_bg_ksum():
    """audit3 R55's panel: use_fl is set at the Pi's HELLO (2: the driver keeps the check), but the link goes
    on without one in the background.  A driver found there without the frame check (older than 1.23; here
    the kernel's, made to say 1.22) gets no 02h AL=3 or 03h AL=2: use_fl 1, the sum by software, and the
    request answered; the next pop-up's HELLO with 1.23 again: use_fl 2."""
    h = Res(pico='quiet', more={'A:\\BIG.TXT': BIG}); h.boot()
    try:
        Y, m = h.m.Y, h.m
        h.cmd('claude /r')
        h.cmd('emsuse')
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and h.has('Welcome to Claude Code', 30)
        t = h.router.term
        check('a pop-up with driver 1.23: use_fl 2 from the HELLO', up and h.rv('ksum') == 1 and h.rv('use_fl') == 2,
              (up, h.rv('ksum'), h.rv('use_fl')))
        h.press(HOT)
        back = h.wait(lambda: h.inpop() == 0, 5) and h.pi_wait(lambda: t.away and h.transport.proto.quiet, 10)
        ver = 0x600 + Y['gp_f_present']                 # (mov ax,4747h / mov cx,0123h)
        code = bytes(m.mu.mem_read(ver, 6))
        def say(v):
            m.mu.mem_write(ver + 4, bytes([v])); m.mu.ctl_remove_cache(ver, ver + 6)
        say(0x22)
        als, w0 = [], m.watch
        fw, fr = 0x600 + Y['gp_f_write'], 0x600 + Y['gp_f_read']
        def w(a):
            if a in (fw, fr): als.append(('w' if a == fw else 'r', m.rd(0x60, Y['gp_c_al'], 1)[0]))
            w0(a)
        m.watch = w
        r = tool(h, 'grid_files', {'action': 'read', 'path': 'A:\\BIG.TXT'})
        m.watch = w0
        check('away, the driver now 1.22: a background read answered (three 8 KB replies), use_fl 1 (ksum 0), no '
              '02h AL=3 and no 03h AL=2 to it',
              back and code == b'\xB8\x47\x47\xB9\x23\x01' and r and not r[1]
              and r[0][0]['text'] == BIG.decode().replace('\r\n', '\n') and h.rv('ksum') == 0 and h.rv('use_fl') == 1
              and als and ('w', 3) not in als and ('r', 2) not in als,
              (back, code.hex(), r and str(r)[:100], h.rv('ksum'), h.rv('use_fl'), sorted(set(als))))
        say(0x23)
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen); st = in_step(h)
        check('... 1.23 again, the next pop-up\'s HELLO: use_fl 2', up and st and h.rv('ksum') == 1 and h.rv('use_fl') == 2,
              (up, st, generation(h), gen, h.rv('connected'), h.up(), h.rv('ksum'), h.rv('use_fl'), h.screen()[-300:]))
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()


def t_bg_hot():
    """CODE-\\ typed while a background look runs, under a program that reads (EMSUSE, AH=00h): the console
    comes after the look.  (The stub's read loop peeks with the BIOS's AH=01h, which drops CODE-\\ at the
    head of the buffer: it now looks for CODE-\\ after the background look, not before it.)"""
    h = Res(pico='quiet'); h.boot()
    try:
        h.cmd('claude /r')
        h.cmd('emsuse')
        gen = generation(h)
        h.press(HOT)
        up = popped(h, gen) and h.has('Welcome to Claude Code', 30)
        h.press(HOT)
        back = h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        a0, st, watch = 0xE0000 + h.rsym['bg_pass'], {'at': None}, h.m.watch
        def w(addr):                            # (CODE-\ typed as a look starts)
            if addr == a0 and st['at'] is None and h.m.ems_reg[0] == h.m.rd(h.stub(), h.sym['r_hw'], 1)[0]:
                st['at'] = h.m.us; h.m.keys.append(HOT)
            watch(addr)
        h.m.watch = w
        gen = generation(h)
        came = h.wait(lambda: st['at'] is not None, 5) and popped(h, gen)
        h.m.watch = watch
        check('CODE-\\ typed as a background look starts, EMSUSE reading: the console comes after it',
              up and back and came, (up, back, st, h.m.mode(), h.inpop(), r_bgon(h)))
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
        h.k.key(ESC)
        ok, why = clean(h)
        check('no link failure, nothing wrong in gridlink\'s log', ok, why)
    finally:
        h.close()


TESTS = [t_popup, t_midstream, t_session, t_requests, t_type, t_type_peek, t_title_room, t_noscreen, t_replies, t_nopi, t_timeout, t_tm5000g, t_drive, t_driver,
         t_ops, t_ops_codes, t_ops_mt, t_bg, t_bg_tm, t_bg_mt, t_bg_screen, t_bg_ksum, t_bg_hot]
if __name__ == '__main__':
    TR.build()
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
