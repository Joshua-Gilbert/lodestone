"""Resident Claude, M2: CLAUDE /R's console is Term, Claude Code on the Pi in
the same session as CLAUDE /T, over DOS programs.  The Lodestone kernel in
pcemu with its built-in GPIB, the 7210 and the AR488 bridge model, and the
real gridlink with a stand-in Claude Code in a pty (claude-link/tests).

    python3 tests/test_resident_term.py [name ...]
"""
import json, os, sys, threading, time, traceback
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
    def __init__(s, tm=False, bridge=True, **kw):
        files = {'A:\\' + n: open(os.path.join(CL, n), 'rb').read() for n in ('EMSUSE.COM', 'GFXUSE.COM')}
        files['A:\\MEMSZ.COM'] = open(os.path.join(HERE, 'MEMSZ.COM'), 'rb').read()
        if tm: files['A:\\TM5000G.EXE'] = open(TR.TM5000G, 'rb').read()
        super().__init__(files=files, term=FAKE, ems_pages=88, **kw)
        if not bridge: del s.m.chip.devices[7]
        s.rsym = G.symbols(os.path.join(CL, 'RCON.MAP'))
        rcon = open(os.path.join(CL, 'RCON.BIN'), 'rb').read()
        s.font_img = rcon[s.rsym['font']:s.rsym['font'] + 0x81 * 16]
        s.srq_calls = 0                         # the driver's SRQ check (AH=0Bh) while the console is up
        srq, watch = s.m.Y['gp_f_srq'], s.m.watch
        def w(addr):
            if s.m.r('cs') == 0x60 and s.m.r('ip') == srq and s.stub() != 0xF000 and s.inpop() == 1 \
                    and s.m.ems_reg[0] == s.m.rd(s.stub(), s.sym['r_hw'], 1)[0]:    # (the console's page in)
                s.srq_calls += 1
            watch(addr)
        s.m.watch = w

    def boot(s):
        """To LCMD's prompt."""
        k = ktest.KPC.__new__(ktest.KPC)
        k.pc = s.m; k.Y = s.m.Y; k.dos = []; k.pending = {}; k.trace = False; k.hooks = []
        s.k = k
        s.m.boot(0); k.settle(8)
        k.key(ktest.CODE_P)

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

    def term_cells(s):
        raw = s.m.ems_read(s.page(), s.rsym['shadow'], 24 * 160)
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
        check('... the band: how to go back', 'CODE-\\ back' in h.band(), h.band())
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
        # the second time: Term's screen from the shadow at once, then the Pi again
        seen = []
        b0, r0 = enc.stats['bytes'], enc.stats.get('resumes', 0)
        h.press(HOT)
        h.wait(lambda: h.up() and ('You said: hello' in h.screen() and seen.append(h.rv('connected')) is None), 10)
        check('the second CODE-\\: Term\'s screen drawn from the console\'s shadow before the Pi answers',
              seen and seen[0] == 0, (seen, h.screen()))
        check('... then the Pi\'s, in step', h.wait(lambda: h.rv('connected'), 10) and in_step(h), h.screen())
        n = enc.stats['bytes'] - b0
        check('... the Pi went on from the console\'s kept screen (its HELLO\'s CRC): %d bytes of CELLS, '
              'not the whole screen again (%d so far)' % (n, full),
              enc.stats.get('resumes', 0) == r0 + 1 and n < full // 4, (n, full, enc.stats))
        h.term_type('big'); h.press(ENTER)
        check('... the same session goes on (a 60-line answer, scrolled)', h.has('line 59') and in_step(h), h.screen())
        check('... the same claude on the Pi', h.router.term.child.pid == pid)
        used = h.stack_used()
        check('the stub\'s stack: %d of %d bytes used, 96 or more spare' % (used, h.rstack()),
              h.rstack() - used >= 96, used)
        h.press(HOT)
        h.wait(lambda: h.m.mode() == 3 and h.inpop() == 0, 5)
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
    """The GRiD's tools while the console is up: the MCP tools say why not;
    a request that comes anyway is answered F6h at once."""
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


TESTS = [t_popup, t_midstream, t_session, t_requests, t_nopi, t_tm5000g]
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
