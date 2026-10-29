"""gridlink/tests/test_emu.py's scenarios with CLAUDE.COM running on the
Lodestone 0.2 kernel (built-in GPIB, the real LCMD.COM shell) instead of the Python
stand-in for DOS.

    python3 tests/test_claude_kernel.py [outdir] [name ...]
"""
import os, struct, sys, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import claude_kernel as CK
import test_emu as T

T.EmuHarness = CK.KernelHarness
T.OUT = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('test') else ''


def test_quit_to_dos():
    """CODE-Q: back to the Executive, the vectors CLAUDE took given back."""
    h = T.start([])
    h.key(0x1000)
    assert h.back_in_executive(10), (h.m.crash, h.k.where())
    h.k.settle()
    assert any('CLAUDE.COM ended' in l for l in h.k.band()), h.k.band()
    off, seg = struct.unpack('<HH', h.m.rd(0, 0x16 * 4, 4))
    assert (seg, off) == (0xF000, 0x16 * 8), (hex(seg), hex(off))
    off, seg = struct.unpack('<HH', h.m.rd(0, 0x23 * 4, 4))
    assert seg == 0x60, (hex(seg), hex(off))
    off, seg = struct.unpack('<HH', h.m.rd(0, 0x24 * 4, 4))     # (0.3: the UI's own)
    assert (seg, off) == (h.k.useg, h.k.Y['ui_int24']), (hex(seg), hex(off))
    assert 'Claude for GRiD ended.' in ''.join(h.m.tty)


def test_run_tm5000g_from_claude():
    """Claude starts TM5000G (an EXE, 290 KB) through the kernel and gets its
    screen back."""
    from test_kernel import TM5000G
    exe = open(TM5000G, 'rb').read()
    h = T.start([T.reply(('tool', 'grid_command', {'command': 'TM5000G', 'capture': False,
                                                   'keys': '{WAIT 1}{ENTER}{WAIT 0.5}{SNAP}0'})),
                 T.reply(('text', 'TM5000G started and quit.'))], mode='auto', files={'A:\\TM5000G.EXE': exe})
    assert h.turn('start tm5000g and quit it', sim_s=90)
    res = T.results(h, 1)[0]
    text = str(res['content'])
    assert 'TM5000 CONTROL SYSTEM' in text or 'Exit code: 0' in text, text[:600]
    assert h.m.mode() == 0x40
    T.check(h)


def test_write_no_name_leaves_no_temp():
    """A file the Pi writes under a name DOS won't take (a second dot): the
    write is refused, the file of its first 8.3 name is left alone, and the
    NAME.$$$ written first is deleted again (the stand-in DOS can't say 3)."""
    h = T.start([T.reply(('tool', 'str_replace_based_edit_tool',
                          {'command': 'create', 'path': 'A:\\NOTES.V2.TXT', 'file_text': 'new text\n'})),
                 T.reply(('text', 'It could not be written.'))], files={'A:\\NOTES.V2': b'old text\r\n'})
    assert h.turn('write the notes', on_ask=lambda h: h.key(ord('y')))
    assert bytes(h.m.fs['A:\\NOTES.V2']) == b'old text\r\n', h.m.fs.get('A:\\NOTES.V2')
    assert not [n for n in h.m.fs if n.endswith('.$$$')], sorted(h.m.fs)
    T.check(h)


def test_write_safe_keeps_the_only_copy():
    """write_file_safe's order on a stub link: the old file deleted, then the rename failing, leaves NAME.$$$
    (the new data's only copy); the old file's delete refused takes NAME.$$$ away again."""
    from gridlink import grid as G
    class Stub(G.Grid):
        def __init__(s, fail): s.fs, s.fail = {'A:\\NOTES.TXT': b'old'}, fail
        def write_file(s, path, data, progress=None): s.fs[path] = data
        def delete(s, path):
            if s.fail == 'delete' and path == 'A:\\NOTES.TXT': raise G.GridError('access denied', 5)
            if path not in s.fs: raise G.GridError('file not found', 2)
            del s.fs[path]
        def rename(s, old, new):
            if s.fail == 'rename': raise G.GridError('disk error', 31)
            s.fs[new] = s.fs.pop(old)
    for fail, want in (('rename', {'A:\\NOTES.$$$': b'new'}), ('delete', {'A:\\NOTES.TXT': b'old'}),
                       (None, {'A:\\NOTES.TXT': b'new'})):
        g = Stub(fail)
        try: g.write_file_safe('A:\\NOTES.TXT', b'new')
        except G.GridError: pass
        assert g.fs == want, (fail, g.fs)


def gp(h, name, size=1):
    a = h.m.Y[name]
    return h.m.u16(0x60, a) if size == 2 else h.m.rd(0x60, a, 1)[0]


def test_srq_on_irq5():
    """The kernel's GPIB driver takes SRQ on IRQ 5 (KGPIB.INC): its vector, IRQ 5 unmasked, SRQI in IMR2, AH=0Eh
    says 5; a turn through the Pico model, every SRQ an interrupt (the handler counts them)."""
    h = T.start([T.reply(('text', 'Hello over the interrupt. ' * 20))], bridge='pico')
    assert gp(h, 'gp_irq') == 5 and not h.m.pic_mask & 0x20 and h.m.chip.imr2 == 0x40, \
        (gp(h, 'gp_irq'), hex(h.m.pic_mask), h.m.chip.imr2)
    off, seg = struct.unpack('<HH', h.m.rd(0, 0x0D * 4, 4))
    assert (seg, off) == (0x60, h.m.Y['gp_isr']), (hex(seg), hex(off))
    n0, i0 = gp(h, 'gp_nsrq', 2), h.m.irqs5
    assert h.turn('hello', sim_s=30)
    n, i = gp(h, 'gp_nsrq', 2) - n0, h.m.irqs5 - i0
    assert n > 3 and n == i, (n, i)
    assert gp(h, 'gp_irq') == 5                    # (no storm)
    T.check(h)


def test_gpibirq_0_turns_it_off():
    """GPIBIRQ=0 in LODE.INI: the start-up (KSPLASH.INC's gi_boot) turns the interrupt off (AH=0Eh AL=0);
    CLAUDE polls as before."""
    h = T.start([T.reply(('text', 'Polled.'))], bridge='pico', files={'A:\\LODE.INI': b'GPIBIRQ=0\r\n'})
    assert gp(h, 'gp_irq') == 0 and h.m.pic_mask & 0x20 and h.m.chip.imr2 == 0, \
        (gp(h, 'gp_irq'), hex(h.m.pic_mask), h.m.chip.imr2)
    i0 = h.m.irqs5
    assert h.turn('hello', sim_s=30)
    assert gp(h, 'gp_nsrq', 2) == 0 and h.m.irqs5 == i0
    T.check(h)


def test_irq5_storm_masks_it():
    """IRQ 5 that keeps firing (no jumper, a floating line): after 32 in one tick the driver masks it and takes
    SRQI out of IMR2; the link goes on polled."""
    h = T.start([T.reply(('text', 'Still here.'))], bridge='pico')
    assert gp(h, 'gp_irq') == 5
    n0 = gp(h, 'gp_nsrq', 2)
    for i in range(40):
        h.m.irq_pending.add(5)
        h.m.run(50)
        if gp(h, 'gp_irq') == 0: break
    assert gp(h, 'gp_irq') == 0 and h.m.pic_mask & 0x20 and h.m.chip.imr2 == 0, (i, gp(h, 'gp_irq'))
    assert 32 <= gp(h, 'gp_nsrq', 2) - n0 <= 34, gp(h, 'gp_nsrq', 2) - n0
    assert h.turn('are you there', sim_s=30)
    T.check(h)


def test_driver_frame_check():
    """GPIB driver 1.23 keeps the frame check as it moves the bytes (and CLAUDE 1.5 takes 8 KB write requests,
    req= in its HELLO, so this 22 KB file goes in three): CLAUDE checks every frame from the Pi by
    the driver's sum (03h AL=2, ks_check: none left for find_frame's scan), and its own frames go out with the
    check the driver added (02h AL=3), every one good at the Pi.  A 22 KB file each way."""
    big = ''.join('line %05d: the quick brown fox jumps over the lazy dog\n' % i for i in range(400))
    h = T.start([T.reply(('tool', 'str_replace_based_edit_tool',
                          {'command': 'create', 'path': 'A:\\BIG.TXT', 'file_text': big})),
                 T.reply(('tool', 'str_replace_based_edit_tool', {'command': 'view', 'path': 'A:\\BIG.TXT',
                                                                   'view_range': [395, 400]})),
                 T.reply(('text', 'Written and checked.'))], mode='edits', bridge='pico')
    assert h.var('ksum', 1) == 1 and h.var('use_fl', 1) == 2, (h.var('ksum', 1), h.var('use_fl', 1))   # (1 before audit3 R55)
    assert h.link.grid_req == 16700, h.link.grid_req     # (CLAUDE 1.6's HELLO: req=, so 16 KB write requests)
    st = h.link.stats                                    # (audit3 R56: the HELLO too, and its answer)
    assert st['rx_fletcher'] == st['rx_frames'] >= 2 and h.var('n_bad', 2) == 0, (dict(st), h.var('n_bad', 2))
    k0, st0 = h.var('n_kok', 2), dict(h.link.stats)
    assert h.turn('write a big file', sim_s=120)
    assert bytes(h.m.fs['A:\\BIG.TXT']) == big.replace('\n', '\r\n').encode()
    st = {k: v - st0.get(k, 0) for k, v in h.link.stats.items()}
    assert h.var('n_bad', 2) == 0 and not st.get('rx_nak') and not st.get('rx_bad'), st
    assert h.var('n_kok', 2) - k0 == st['tx_frames'] > 40, (h.var('n_kok', 2) - k0, st)   # (every Pi frame)
    assert st['rx_fletcher'] == st['rx_frames'], st                                       # (every one of ours)
    T.check(h)


def test_executive_saver():
    """CLAUDE 1.14: idle for the saver's delay (SAVER=1: a minute), the Executive's screen saver comes on inside
    it (INT 21h F0h AL=5, as at LCMD's prompt): DEFRAG first on A: (on the disk), then the dark screen.  A GRiD
    tool call from the Pi more than 10 s in rings, which ends it (DEFRAG stopped by it too, through CLAUDE's INT
    16h hook inside DOS), and is answered; the chat drawn again.  Idle again, it comes on again; a key ends it,
    taken (not typed into the prompt)."""
    defrag = open(os.path.join(os.path.dirname(HERE), 'src', 'DEFRAG.COM'), 'rb').read()
    h = T.start([T.reply(('text', 'Hi from the Pi.'))], bridge='pico',
                files={'A:\\LODE.INI': b'SAVER=1\r\n', 'A:\\DEFRAG.COM': defrag})
    sv, hits, w0 = h.k.useg * 16 + h.k.Y['saver'], [], h.m.watch
    def w(a):
        if a == sv: hits.append(h.m.us)
        if w0: w0(a)
    h.m.watch = w
    assert h.turn('hello', sim_s=30)
    assert 'Hi from the Pi.' in h.screen(), h.screen()
    t0 = h.m.us
    assert h.run_until(lambda: hits, 120), ('no saver', h.var('sv_st'), h.var('sv_t', 2))
    on = (hits[0] - t0) / 1e6
    assert 58 <= on <= 70, on                              # (SAVER=1: 1,092 ticks, from the turn's last frame)
    h.run_until(lambda: False, 15)                          # (DEFRAG, then the dark screen; past the Pi's 10 s)
    assert h.m.r('cs') != h.claude_psp and 'Hi from the Pi.' not in h.screen(), h.screen()
    def call(when):
        res = {}
        th = __import__('threading').Thread(target=lambda: res.update(r=h.session.grid.get_info()))
        th.start()
        t1 = h.m.us
        assert h.run_until(lambda: not th.is_alive(), 30), ('the call never came back', when, h.k.ocr()[:6])
        assert 'CLAUDE 1.15' in res.get('r', {}).get('grid', ''), res
        assert h.run_until(lambda: 'Hi from the Pi.' in h.screen(), 10), h.screen()
        return (h.m.us - t1) / 1e6
    ended = call('dark')                                    # (in the dark screen)
    assert h.run_until(lambda: len(hits) == 2, 90), 'not on again'
    h.run_until(lambda: False, 0.3)
    df = any('Lodestone Defrag' in x[1] for x in h.k.ocr())
    assert df, h.k.ocr()
    ended2 = call('defrag')                                 # (DEFRAG reading the disk: stopped by the ring)
    assert h.run_until(lambda: len(hits) == 3, 90), 'not on a third time'
    h.run_until(lambda: False, 5)
    h.key(0x1E61)                                           # "a"
    assert h.run_until(lambda: 'Hi from the Pi.' in h.screen(), 10), h.screen()
    h.run_until(lambda: False, 1)
    assert h.var('inlen', 2) == 0, ('the waking key typed', h.var('inlen', 2))
    assert len(hits) == 3
    print('     on after %.1f s idle; a tool call ended it, answered in %.2f s (in DEFRAG: %.2f s)'
          % (on, ended, ended2))
    T.check(h)


def test_driver_frame_check_slow_start():
    """A listener slow to take the first byte of a write (DO later than the fast loop polls for, 256 x 64): the
    whole frame goes through the careful loop, and the check the driver adds (02h AL=3) is still good at the Pi
    (audit3 X30: the fast loop kept its start for the first byte's add, the careful loop left that byte out too,
    so every such frame went out with a bad check)."""
    h = T.start([T.reply(('tool', 'str_replace_based_edit_tool', {'command': 'view', 'path': 'A:\\NOTES.TXT'})),
                 T.reply(('text', 'Read it.'))], mode='edits', bridge='pico',
                files={'A:\\NOTES.TXT': b''.join(b'note %03d: a slow start\r\n' % i for i in range(60))})
    assert h.var('ksum', 1) == 1, h.var('ksum', 1)
    st0 = dict(h.link.stats)
    h.m.chip.slow_start = 20000                    # (ISR1 reads after GTS: more than the fast loop's 16384)
    assert h.turn('read the notes', sim_s=60), (h.m.chip.n_slow, {k: v - st0.get(k, 0) for k, v in h.link.stats.items()})
    st = {k: v - st0.get(k, 0) for k, v in h.link.stats.items()}
    assert h.m.chip.n_slow >= 2 and st['rx_frames'] >= 2, (h.m.chip.n_slow, st)
    assert not st.get('rx_nak') and not st.get('rx_bad') and st['rx_fletcher'] == st['rx_frames'], st
    T.check(h)


T.test_executive_saver = test_executive_saver
T.test_driver_frame_check = test_driver_frame_check
T.test_driver_frame_check_slow_start = test_driver_frame_check_slow_start
T.test_srq_on_irq5 = test_srq_on_irq5
T.test_gpibirq_0_turns_it_off = test_gpibirq_0_turns_it_off
T.test_irq5_storm_masks_it = test_irq5_storm_masks_it
T.test_quit_to_dos = test_quit_to_dos
T.test_write_no_name_leaves_no_temp = test_write_no_name_leaves_no_temp
T.test_write_safe_keeps_the_only_copy = test_write_safe_keeps_the_only_copy
T.test_run_tm5000g_from_claude = test_run_tm5000g_from_claude


def test_key_script_peeks():
    """audit3 (X42's panel): a TSR's INT 16h peek from its INT 1Ch while CLAUDE's ks_ready moves a RUN's
    {WAIT} on (test_resident_term's t_type_peek, for CLAUDE.COM's own feeder): the waits and keys play as
    typed.  ks_ready runs with interrupts off (the peek comes after it)."""
    import test_resident_term as RT
    script = RT.PEEK_SCRIPT + '{SNAP}{ESC}'
    turns = []
    for _ in RT.PEEK_AT:
        turns += [T.reply(('tool', 'grid_command', {'command': 'TESTKEY', 'capture': False, 'keys': script})),
                  T.reply(('text', 'Done.'))]
    h = T.start(turns, mode='auto')
    base, sym = h.claude_psp * 16, h.sym
    lo, hi = base + sym['ks_ready'], base + sym['build_hello']
    code = bytes(h.m.mu.mem_read(lo, hi - lo))
    kw, kp = struct.pack('<H', sym['ks_wait']), struct.pack('<H', sym['ks_pos'])
    e0 = code.find(b'\x2E\xC6\x06' + kw + b'\0')
    assert code.count(b'\x2E\xC6\x06' + kw + b'\0') == 1 and code[e0 + 6:e0 + 12] == b'\x2E\x83\x06' + kp + b'\3', code.hex()
    at = {'look': lo + code.index(b'\x2E\x80\x3E' + kw + b'\0'), 'end0': lo + e0, 'end1': lo + e0 + 6}
    bad = []
    for i, where in enumerate(RT.PEEK_AT):
        def run():
            ok = h.turn('run testkey', sim_s=60)
            return ok and str(T.results(h, 2 * i + 1)[0]['content'])
        d, after, text = RT.peek_race(h.m, lo, hi, h.var, lambda: True, at, where, run, RT.peek_waits(script, 0))
        if not (None not in d and d[0] > 0.15 and d[1] > 0.85 and text and 'Exit code: 3' in text and
                'TESTKEY ready: abc' in text and 'bye' not in text and isinstance(after, tuple)
                and (where != 'start' or after == (1, RT.peek_waits(script, 0)[1], 0x40))):
            bad.append((where, d, after, text))
    assert not bad, bad
    T.check(h)


T.test_key_script_peeks = test_key_script_peeks


def test_key_script_other_int16():
    """Under CLAUDE's key-script hook, INT 16h's other functions (K16: 02h, 12h, 04h-80h) go on to the
    BIOS and leave the script's keys alone; its reads (00h, 10h) take them."""
    import test_resident as R
    h = T.start([T.reply(('tool', 'grid_command', {'command': 'K16', 'capture': False, 'keys': 'ab'})),
                 T.reply(('text', 'Done.'))], mode='auto', files={'A:\\K16.COM': open(R.k16(), 'rb').read()})
    assert h.turn('run k16', sim_s=60)
    text = str(T.results(h, 1)[0]['content'])
    assert 'Exit code: 0' in text, text                # (K16's count of calls that came back otherwise)
    T.check(h)


T.test_key_script_other_int16 = test_key_script_other_int16


def test_run_exec_block():
    """A RUN's EXEC block (filled once at CLAUDE's start): the child gets CLAUDE's environment, the command's
    tail and two blank FCBs in its PSP."""
    h = T.start([T.reply(('tool', 'grid_command', {'command': 'TESTKEY one two', 'capture': False,
                                                   'keys': '{WAIT 1}x{ESC}'})),
                 T.reply(('text', 'Done.'))], mode='auto')
    h.type('run testkey')
    cur = lambda: h.m.u16(0x60, h.m.Y['cur_psp'])
    root = h.m.u16(0x60, h.m.Y['root_psp'])
    assert h.run_until(lambda: cur() not in (root, h.claude_psp) or h.m.crash, 20), h.m.crash
    psp = cur()
    fcbs, tail = h.m.rd(psp, 0x5C, 32), h.m.rd(psp, 0x80, 10)
    env = h.m.rd(h.m.u16(psp, 0x2C), 0, 256)
    assert h.run_until(h.idle, 30)
    text = str(T.results(h, 1)[0]['content'])
    blank = b'\0' + b' ' * 11 + b'\0' * 4
    assert fcbs == blank * 2 and tail == b'\x08 one two\r' and b'COMSPEC=' in env and 'Exit code: 1' in text, \
        (fcbs, tail, env, text)
    T.check(h)


T.test_run_exec_block = test_run_exec_block


def test_run_memory_and_reconnect():
    """audit3 O11: a RUN's buffers live under hellobuf, and build_kv's cwdbuf under sline.  O17: while MEMSZ
    runs, CLAUDE's block is cut back to reqbuf's start (the key script's end; 2,844 paragraphs before O17),
    and MEMSZ, loaded in what was CLAUDE's tail (the conversation and the replies at the top: alloc_top),
    gets all the rest; after it CLAUDE's block is whole again (run_back).  Then the link is lost and comes
    back: the HELLO built over the RUN's buffers says what the first one said, and a second RUN gets the
    same memory.  Each RUN's REPLY names its outname (X:\\...\\CLAUDE.OUT): a HELLO built during a RUN would
    be under it.  The screenshot at a RUN's end goes in a block made after the program (one 48h): none while
    MEMSZ runs; with {SNAP} in its key script the block is made before, at the top (alloc_top), and MEMSZ gets
    that much less, all the rest still."""
    import re
    from unicorn import UC_HOOK_CODE
    G = lambda **k: T.reply(('tool', 'grid_command', dict({'command': 'MEMSZ', 'capture': False,
                                                           'screenshot': True}, **k)))
    h = T.start([G(), T.reply(('text', 'Done.')), G(), T.reply(('text', 'Again.')), G(keys='{SNAP}'),
                 T.reply(('text', 'Marked.'))], mode='auto',
                files={'A:\\MEMSZ.COM': open(os.path.join(HERE, 'MEMSZ.COM'), 'rb').read()})
    hello = dict(h.session.hello)
    runs, grun = [], h.session.grid.run            # (each RUN's REPLY: outname, read back from under hellobuf)
    h.session.grid.run = lambda *a, **k: runs.append(grun(*a, **k)) or runs[-1]
    keep = (h.sym['reqbuf'] + 7 + 15) // 16         # (no key script: up to ks_ptr)
    full = (h.sym['bss_end'] + 15) // 16
    def run(i, prompt, script=0):
        lo, st = (h.claude_psp + keep) * 16, {}
        def at(uc, addr, size, ud):                         # (MEMSZ's first instruction: CS its PSP)
            if 'got' not in st:
                p = h.m.r('cs'); st['got'], st['psp'] = h.m.u16(p, 2) - p, p
                st['mine'] = h.m.u16(h.claude_psp - 1, 3)   # (CLAUDE's block meanwhile)
                st['snap'] = h.var('snapseg', 2)            #  and the snapshot's
        hk = h.m.mu.hook_add(UC_HOOK_CODE, at, None, lo, 0x9FFFF)
        h.m.mu.ctl_remove_cache(lo, 0xA0000)
        h.type(prompt)
        try: assert h.run_until(lambda: h.idle() and 'got' in st, 60), (st, h.screen())
        finally: h.m.mu.hook_del(hk)
        text = str(T.results(h, i))
        kb = '%d.%d KB for programs' % divmod(st['got'] * 10 // 64, 10)
        out = runs[-1]['outfile']
        assert 'Exit code: 0' in text and kb in text and 'Screen (text mode 03h' in text and \
            re.fullmatch(r'[A-Z]:\\(\S+\\)?CLAUDE\.OUT', out), (kb, out, text)
        assert st['mine'] == (h.sym['reqbuf'] + 7 + script + 15) // 16 and st['psp'] < h.claude_psp + full and \
            h.m.u16(h.claude_psp - 1, 3) == full and (st['snap'] > st['psp'] if script else st['snap'] == 0), \
            (st, keep, full, hex(h.claude_psp), h.m.u16(h.claude_psp - 1, 3))
        return st['got'], st['mine'], out
    got, mine, out = run(1, 'how much memory')
    print('     MEMSZ got %d paragraphs (%.1f KB); CLAUDE kept %d of its %d meanwhile' % (got, got / 64, mine, full))
    real = h.transport.answer
    h.transport.answer = lambda f: None            # the Pi goes quiet: a HELLO over the RUN's buffers
    assert h.run_until(lambda: not h.var('connected'), 10), 'no link loss noticed'
    h.session.hello = {}
    h.transport.answer = real
    assert h.run_until(lambda: h.idle() and h.session.hello, 15), h.screen()
    same = lambda d: {k: v for k, v in d.items() if k != 'date'}
    assert same(h.session.hello) == same(hello) and hello['cwd'] == 'A:\\', (h.session.hello, hello)
    assert run(3, 'and again') == (got, mine, out)
    g5 = run(5, 'and with a mark', 3)[0]
    assert g5 == got - (32768 + 11 + 15) // 16 - 1, (g5, got)       # (the snapshot's block and its MCB)
    print('     with {SNAP} in its script %d paragraphs (%.1f KB)' % (g5, g5 / 64))
    T.check(h, fails=1)


T.test_run_memory_and_reconnect = test_run_memory_and_reconnect


def mcbs(h):
    """The kernel's MCB chain: [(segment, owner, paragraphs)]"""
    seg, out = h.m.u16(0x60, h.m.Y['first_mcb']), []
    while len(out) < 200:
        kind, owner, n = struct.unpack('<BHH', h.m.rd(seg, 0, 5))
        out.append((seg, owner, n))
        if kind == 0x5A: return out
        seg += n + 1
    raise AssertionError(out)


def test_run_tsr_moves_claude():
    """audit3 O17: a RUN's program that stays resident (TSRK: 64 paragraphs and its environment) where CLAUDE's
    tail was: CLAUDE's block can't grow back, so CLAUDE moves, whole, to a block of its own (run_back), its
    PSP's block keeping the PSP alone.  The memory it left is scribbled over at once (as the next program would
    do): the RUN is answered; a message queued before the RUN from CLAUDE's own memory still arrives whole;
    a second RUN gets its tail and FCBs (the EXEC block's segments); a 31 KB file is written and read back
    (the link's buffers).  TSRK again: CLAUDE moves a second time, and the block it left (not the PSP's) is
    freed, not kept as a 256-byte orphan.  CODE-Q ends CLAUDE, none of its blocks left, both TSRKs there."""
    from unicorn import UC_HOOK_CODE
    from gridlink import glp
    text = P7_DATA.decode().replace('\r\n', '\n')
    h = T.start([T.reply(('tool', 'grid_command', {'command': 'TSRK', 'capture': False})),
                 T.reply(('text', 'It stays.')),
                 T.reply(('tool', 'grid_command', {'command': 'TESTKEY one two', 'capture': False,
                                                   'keys': '{WAIT 1}x{ESC}'})),
                 T.reply(('text', 'Ran.')),
                 T.reply(('tool', 'str_replace_based_edit_tool', {'command': 'create', 'path': 'A:\\P7.TXT',
                                                                   'file_text': text})),
                 T.reply(('tool', 'str_replace_based_edit_tool', {'command': 'view', 'path': 'A:\\P7.TXT'})),
                 T.reply(('text', 'Written and read.')),
                 T.reply(('tool', 'grid_command', {'command': 'TSRK', 'capture': False})),
                 T.reply(('text', 'Another.'))], mode='auto',
                files={'A:\\TSRK.COM': open(os.path.join(HERE, 'TSRK.COM'), 'rb').read()})
    old, Y = h.claude_psp, h.sym
    keep = (Y['reqbuf'] + 7 + 15) // 16
    full = (Y['bss_end'] + 15) // 16
    ev = bytes(h.m.rd(old, Y['msg_bye'], 12))
    st, events = {}, []
    onm = h.link.on_message
    def om(mt, body):
        if mt == glp.G_EVENT: events.append(bytes(body))
        return onm(mt, body)
    h.link.on_message = om
    def at_run(uc, addr, size, ud):                 # (a message queued from our memory as the RUN starts)
        if 'ev' in st: return
        st['ev'] = 1
        n, hd = h.var('txq_n'), h.var('txq_head')
        e = old * 16 + Y['txq'] + (hd + n) % 6 * 10
        h.m.mu.mem_write(e, struct.pack('<BBHHHH', glp.G_EVENT, 0, old, Y['msg_bye'], len(ev), 0))
        h.m.mu.mem_write(old * 16 + Y['txq_n'], bytes([n + 1]))
    def high(uc, addr, size, ud):                   # (past what CLAUDE keeps: TSRK's first instruction, then
        cs = h.m.r('cs')                            #  run_back's first in the block it moved to, where the
        if 'tsr' not in st: st['tsr'] = cs          #  memory it left is scribbled over)
        elif 'new' not in st and cs != st['tsr'] and addr - cs * 16 == Y['run_back.there']:
            st['new'] = h.claude_psp = cs           # (its data, its stack: the harness looks there now)
            h.m.mu.mem_write(old * 16 + 0x100, b'\xCC' * ((keep - 0x10) * 16))
    hks = [h.m.mu.hook_add(UC_HOOK_CODE, at_run, None, old * 16 + Y['op_run'], old * 16 + Y['op_run']),
           h.m.mu.hook_add(UC_HOOK_CODE, high, None, (old + keep) * 16, 0x9FFFF)]
    h.m.mu.ctl_remove_cache(old * 16, 0xA0000)
    h.type('run tsrk')
    try: assert h.run_until(lambda: h.idle() and 'new' in st, 60), (st, h.screen())
    finally:
        for k in hks: h.m.mu.hook_del(k)
    new = st['new']
    assert 'Exit code: 0' in str(T.results(h, 1)) and events == [ev], (T.results(h, 1), events, ev)
    blocks = {s + 1: (o, n) for s, o, n in mcbs(h)}
    assert blocks[old] == (old, 0x10) and blocks[new] == (old, full) and blocks[st['tsr']] == (st['tsr'], 64) \
        and old < st['tsr'] < new, (hex(old), hex(new), hex(st['tsr']), blocks.get(old), blocks.get(new))
    h.type('run testkey')
    cur = lambda: h.m.u16(0x60, h.m.Y['cur_psp'])
    root = h.m.u16(0x60, h.m.Y['root_psp'])
    assert h.run_until(lambda: cur() not in (root, old) or h.m.crash, 20), h.m.crash
    psp = cur()
    fcbs, tail = h.m.rd(psp, 0x5C, 32), h.m.rd(psp, 0x80, 10)
    assert h.run_until(h.idle, 30)
    blank = b'\0' + b' ' * 11 + b'\0' * 4
    assert fcbs == blank * 2 and tail == b'\x08 one two\r' and 'Exit code: 1' in str(T.results(h, 3)), \
        (fcbs, tail, T.results(h, 3))
    assert h.turn('write the file and read it back', sim_s=200)
    assert bytes(h.m.fs['A:\\P7.TXT']) == P7_DATA and 'p7 line 00200' in str(T.results(h, 6)[0]['content'])
    assert h.m.u16(new - 1, 3) == full             # (whole again after the second RUN)
    st2 = {}
    def again(uc, addr, size, ud):                  # (the second move's run_back, in the block it moved to)
        cs = h.m.r('cs')
        if 'new' not in st2 and cs != new and addr - cs * 16 == Y['run_back.there']:
            st2['new'] = h.claude_psp = cs
    hk = h.m.mu.hook_add(UC_HOOK_CODE, again, None, (new + keep) * 16, 0x9FFFF)
    h.m.mu.ctl_remove_cache((new + keep) * 16, 0xA0000)
    h.type('run tsrk again')
    try: assert h.run_until(lambda: h.idle() and 'new' in st2, 60), (st2, h.screen())
    finally: h.m.mu.hook_del(hk)
    mine = [(s + 1, n) for s, o, n in mcbs(h) if o == old]
    assert 'Exit code: 0' in str(T.results(h, 8)) and (old, 0x10) in mine and (st2['new'], full) in mine \
        and not [b for b in mine if b[1] == 0x10 and b[0] != old] and not [b for b in mine if b[0] == new], \
        ([(hex(s), n) for s, n in mine], hex(new), hex(st2['new']))
    T.check(h)
    h.key(0x1000)                                   # CODE-Q
    assert h.back_in_executive(10), (h.m.crash, h.k.where())
    left = [(hex(s), hex(o), n) for s, o, n in mcbs(h) if o in (old, new, st2['new'])]
    tsrs = [b for b in mcbs(h) if b[1] == b[0] + 1 and b[2] == 64]
    assert not left and (st['tsr'] - 1, st['tsr'], 64) in mcbs(h) and len(tsrs) == 2, (left, mcbs(h))


def test_run_tsr_no_room():
    """audit3 O17: a RUN's program that stays resident with all it got but 160 paragraphs: no block for CLAUDE
    to move to, so CLAUDE ends, as CODE-Q does, saying so; the Executive is back, the vectors CLAUDE took
    given back, and none of its blocks left."""
    h = T.start([T.reply(('tool', 'grid_command', {'command': 'TSRK B', 'capture': False})),
                 T.reply(('text', 'It stays.'))], mode='auto',
                files={'A:\\TSRK.COM': open(os.path.join(HERE, 'TSRK.COM'), 'rb').read()})
    old = h.claude_psp
    h.type('run tsrk b')
    assert h.back_in_executive(30), (h.m.crash, h.k.where(), h.screen())
    assert 'Not enough memory for CLAUDE.' in ''.join(h.m.tty), ''.join(h.m.tty)[-300:]
    off, seg = struct.unpack('<HH', h.m.rd(0, 0x16 * 4, 4))
    assert (seg, off) == (0xF000, 0x16 * 8), (hex(seg), hex(off))
    off, seg = struct.unpack('<HH', h.m.rd(0, 0x23 * 4, 4))
    assert seg == 0x60, (hex(seg), hex(off))
    assert not [b for b in mcbs(h) if b[1] == old], mcbs(h)


T.test_run_tsr_moves_claude = test_run_tsr_moves_claude
T.test_run_tsr_no_room = test_run_tsr_no_room


def test_run_script_length_checked():
    """audit3 O17's panel: a RUN whose key script length runs past the request (the script and the command's
    NUL must be in it) is refused with F0h before anything is cut (do_exec cuts CLAUDE's block at the script's
    end); one that fits runs, and CLAUDE's block is whole after each."""
    import threading
    from gridlink import glp
    h = T.start([], mode='auto')
    g = h.session.grid
    full = (h.sym['bss_end'] + 15) // 16
    def call(args):
        res = {}
        th = threading.Thread(target=lambda: res.update(r=g.call(glp.OP_RUN, args, timeout=30)))
        th.start()
        assert h.run_until(lambda: not th.is_alive(), 60), 'no answer'
        return res.get('r')
    keys = struct.pack('<H', 0x011B)                # (Esc: TESTKEY ends)
    cmd = b'TESTKEY\0'                              # (the request: 7 + 2 + 8 bytes; a script of 10 leaves no NUL)
    for n, want in ((10, 0xF0), (0xFFF9, 0xF0), (0xFFFF, 0xF0), (len(keys), 0)):
        st, r = call(struct.pack('<BHH', 0, 10, n) + keys + cmd)
        assert st == want and h.m.u16(h.claude_psp - 1, 3) == full, (n, st, r)
    T.check(h)


def test_in_place_ask():
    """audit3 P7's panel: an ASK in fragments (Pi frames of 448 bytes; gridlink's own ASKs are one frame), its
    last read in place after the first: the 6 bytes its header went over are put back before open_ask copies
    the ASK (they lie within the 896 bytes it keeps)."""
    from gridlink import glp
    h = T.start([], frame_cap=448)
    body = bytes([0x55, 0]) + b'May I?' + b'\0' + bytes(range(65, 91)) * 20 + b'\0' + b'always\0'
    h.link.send(glp.P_ASK, body)
    assert h.run_until(lambda: h.var('ask_open'), 30), h.screen()
    got = bytes(h.m.rd(h.claude_psp, h.sym['askbuf'], len(body)))
    assert got == body, [i for i in range(len(body)) if got[i] != body[i]]
    assert h.var('n_kok', 2) and h.var('rq_at', 2) == 0


T.test_run_script_length_checked = test_run_script_length_checked
T.test_in_place_ask = test_in_place_ask


def test_key_script_snap_peek():
    """audit3 (X42's panel): a tick, and a TSR's INT 16h peek from its INT 1Ch, as ks_ready's {SNAP} copies the
    screen on the read path (interrupts on): the peek finds ks_pos past the mark, so one snapshot, and every
    key typed.  With the copy first and ks_pos moved after, the peek took the snapshot again and ks_pos went
    on by 6, into the middle of the next key."""
    import test_resident_term as RT
    from unicorn import UC_HOOK_CODE
    h = T.start([T.reply(('tool', 'grid_command', {'command': 'TESTKEY', 'capture': False,
                                                   'keys': 'a{WAIT 0.3}b{SNAP}cd{ESC}'})),
                 T.reply(('text', 'Done.'))], mode='auto')
    ts = h.claude_psp * 16 + h.sym['take_snapshot']
    st = {'n': 0, 'at': None}
    def snap(uc, addr, size, ud):               # (take_snapshot, while the script runs)
        if not h.var('ks_active'): return
        if h.m.r('sp') == st.get('sp'):         # (the same call again, after the tick's IRET)
            st['sp'] = None; return
        st['n'] += 1
        if st['at'] is None:
            st['at'] = (h.var('ks_pos', 2), bool(h.m.r('flags') & 0x200))
            st['sp'] = h.m.r('sp')
            RT.tick_before(h.m, addr)
    old = RT.tsr_1ch(h.m)
    hk = h.m.mu.hook_add(UC_HOOK_CODE, snap, None, ts, ts)
    h.m.mu.ctl_remove_cache(ts, ts + 1)
    try: ok = h.turn('run testkey', sim_s=60)
    finally:
        h.m.mu.hook_del(hk); h.m.wr(0, 0x1C * 4, old)
    text = ok and str(T.results(h, 1)[0]['content'])
    assert st['at'] and st['at'][1] and st['n'] == 1 and text and 'Exit code: 4' in text and \
        'TESTKEY ready: ab' in text and 'abc' not in text, (st, text)
    T.check(h)


T.test_key_script_snap_peek = test_key_script_snap_peek


def test_ops_codes():
    """audit3 R51: OPS.INC's file and GPIB requests, each one's status and reply (DOS's error codes, the
    driver's) as claude_kernel's OPS_PROBE has them: the table test_resident_term's t_ops_codes holds RCON to (the same
    source in both binaries)."""
    h = T.start([], bridge='pico')
    got = CK.ops_probe(h.session.grid, lambda c: h.run_until(c, 60), h.m.chip.devices)
    want = CK.ops_want('claude')
    bad = [(g, w) for g, w in zip(got, want) if g != w]
    assert len(got) == len(want) and not bad, bad or got
    T.check(h)


T.test_ops_codes = test_ops_codes


def test_nak_resend_keeps_the_check():
    """audit3 R55: driver 1.23 (use_fl 2): the Pi's answer to the prompt's frame damaged, and the GRiD's NAK
    for it lost too, so the Pi NAKs and the GRiD sends its frame again: byte for byte as the first time,
    the driver's check after it (02h AL=3); the NAK's own mode (AL=1) doesn't stick.  The turn goes on."""
    from gridlink import glp
    h = T.start([T.reply(('text', 'After two faults. ' * 20))])
    st = {'arm': 0, 'resent': []}
    answer, to_pi = h.transport.answer, h.nano.to_pi
    def ans(frame):
        if st['arm'] == 1 and frame[1] & 0x7F != glp.P_NAK:        # (the answer to the prompt)
            f = bytearray(frame); f[len(f) // 2] ^= 0x10; frame = bytes(f); st['arm'] = 2
        return answer(frame)
    def tp(data, t):
        k = data[1] & 0x7F if len(data) > 1 else 0
        if st['arm'] == 0 and k == glp.G_PROMPT:
            st['first'] = bytes(data); st['arm'] = 1
        elif st['arm'] == 2 and k == glp.G_NAK:            # (lost: the Pi asks again, as its idle_check
            st['arm'] = 3                                   #  would after 0.15 s of damaged bytes)
            h.link._answer_nak()
            return
        elif st['arm'] == 3 and k == glp.G_PROMPT:
            st['resent'].append(bytes(data))
        return to_pi(data, t)
    h.transport.answer, h.nano.to_pi = ans, tp
    s0 = dict(h.link.stats)
    assert h.turn('hello', sim_s=60), (st['arm'], len(st['resent']), h.screen())
    assert st['arm'] == 3 and st['resent'] == [st['first']], (st['arm'], st.get('first'), st['resent'])
    assert h.var('use_fl', 1) == 2 and h.link.stats.get('rx_dup', 0) > s0.get('rx_dup', 0), (h.var('use_fl', 1), h.link.stats)
    T.check(h)


T.test_nak_resend_keeps_the_check = test_nak_resend_keeps_the_check

P7_DATA = b''.join(b'p7 line %05d: the quick brown fox jumps over the lazy dog %s\r\n' % (i, b'#' * (i % 11))
                   for i in range(480))         # (36 KB: three writes, three reads)
REQ_END = 16700 + 4                             # (reqbuf's size: REQMAX + 4)


def p7_start(**kw):
    """A turn writing P7_DATA and reading it back, with every driver write (02h) and read (03h) of CLAUDE's
    seen (ah, seg, offset, cx, the frame the write sends), the Pi's REQUEST bodies and the REPLYs it got"""
    from unicorn import UC_HOOK_CODE
    from gridlink import glp
    text = P7_DATA.decode().replace('\r\n', '\n')
    h = T.start([T.reply(('tool', 'str_replace_based_edit_tool', {'command': 'create', 'path': 'A:\\P7.TXT',
                                                                   'file_text': text})),
                 T.reply(('tool', 'str_replace_based_edit_tool', {'command': 'view', 'path': 'A:\\P7.TXT'})),
                 T.reply(('text', 'Written and read.'))], mode='edits', **dict(dict(bridge='pico'), **kw))
    st = {'calls': [], 'reqs': [], 'replies': []}
    a = h.claude_psp * 16 + h.sym['gg_call']
    def at(uc, addr, size, ud):
        ah, cx = h.m.r('ax') >> 8, h.m.r('cx')
        if ah == 2:
            ds, si = h.m.r('ds'), h.m.r('si')
            st['calls'].append((2, ds, si, cx, h.m.rd(ds, si, cx)))
        elif ah == 3: st['calls'].append((3, h.m.r('es'), h.m.r('di'), cx, (h.var('rq_type'), h.var('rq_len', 2))))
    hk = h.m.mu.hook_add(UC_HOOK_CODE, at, None, a, a)
    h.m.mu.ctl_remove_cache(a, a + 1)
    send, onm = h.link.send, h.link.on_message
    def sn(mtype, body=b''):
        if mtype == glp.P_REQUEST: st['reqs'].append(bytes(body))
        return send(mtype, body)
    def om(mt, body):
        if mt == glp.G_REPLY: st['replies'].append(bytes(body))
        return onm(mt, body)
    h.link.send, h.link.on_message = sn, om
    return h, st


def p7_check(h, st, again=(0, 0)):
    """The file written and read back whole; every read CLAUDE made in rxbuf or inside reqbuf, a whole one
    (CX) short of its end; in-place reads (in reqbuf) and sends (in ioseg, from the 6 bytes before a 3,300-byte
    fragment) counted; and reqbuf and ioseg still hold the last big REQUEST's and REPLY's bytes as the Pi
    sent and got them (each 6-byte header's place put back)."""
    assert bytes(h.m.fs['A:\\P7.TXT']) == P7_DATA
    assert 'p7 line 00200' in str(T.results(h, 2)[0]['content'])  # (the view shows 20,000 characters)
    cs, Y = h.claude_psp, h.sym
    ios = h.var('ioseg', 2)
    rd = [(seg, off, cx) for k, seg, off, cx, _ in st['calls'] if k == 3]
    bad = [(hex(off), cx) for seg, off, cx in rd if seg != cs or off != Y['rxbuf'] and not
           (Y['reqbuf'] <= off and off + cx <= Y['reqbuf'] + REQ_END)]
    assert not bad, bad
    n_in = sum(off != Y['rxbuf'] for seg, off, cx in rd)
    wr = [(seg, off, cx) for k, seg, off, cx, _ in st['calls'] if k == 2]
    n_out = sum(seg != cs for seg, off, cx in wr)
    bad = [(hex(seg), off) for seg, off, cx in wr if seg != cs and (seg != ios or (off + 6) % 3300)]
    assert not bad, bad
    m = h.link.maxpay                                   # (each later fragment in place while a read has room)
    want_in = sum(1 for r in st['reqs'] for j in range(1, -(-len(r) // m)) if j * m - 6 + 3349 <= REQ_END)
    want_out = sum(-(-len(r) // 3300) - 1 for r in st['replies']) if h.var('use_fl') == 2 else 0
    assert (n_in, n_out) == (want_in + again[0], want_out + again[1]), (n_in, want_in, n_out, want_out)
    big = [r for r in st['reqs'] if len(r) > 6000]
    assert big and bytes(h.m.rd(cs, Y['reqbuf'] + 100, len(big[-1]) - 100)) == big[-1][100:]
    rep = [r for r in st['replies'] if len(r) > 6000]
    assert rep and bytes(h.m.rd(ios, 0, len(rep[-1]))) == rep[-1]
    return n_in, n_out


def test_frames_in_place():
    """audit3 P7 (driver 1.23, use_fl 2): a 16 KB write's REQUEST comes in five frames, the four after the first
    read straight into reqbuf after what it holds, the 6 bytes under each header put back; a 16 KB read's REPLY
    goes in five, the four after the first sent from ioseg where they lie, a header swapped in over the 6 bytes
    before each and back after.  Only the first of each is copied (pf_reasm's, frame_next's REP MOVSW).  Pi
    frames of 2 KB (frame_cap): a write in nine, the later ones in rxbuf again where a whole read would go
    past reqbuf's end.  With CLAUDE's own Fletcher sum (use_fl 1, an older driver's), reads in place too
    (find_frame from where the read went), every frame sent from txframe."""
    from unicorn import UC_HOOK_CODE
    for cap, own in ((None, 0), (2048, 0), (None, 1)):
        h, st = p7_start(frame_cap=cap)
        if own: h.m.wr(h.claude_psp, h.sym['use_fl'], b'\1')
        k0 = h.var('n_kok', 2)
        lo, hi = h.claude_psp * 16 + h.sym['pf_reasm'], h.claude_psp * 16 + h.sym['pf_reasm.over']
        n = {'pf': 0}
        def cnt(uc, addr, size, ud): n['pf'] += 1          # (each REP MOVSW step a hook: a copy shows)
        hk = h.m.mu.hook_add(UC_HOOK_CODE, cnt, None, lo, hi)
        h.m.mu.ctl_remove_cache(lo, hi)
        assert h.turn('write the file and read it back', sim_s=200)
        h.m.mu.hook_del(hk)
        n_in, n_out = p7_check(h, st)
        frames = sum(1 for k, *_ in st['calls'] if k == 3)
        copies = len([r for r in st['reqs'] if len(r) > 3000])      # (the first fragment of each)
        assert n_in >= (12 if cap else 8) and n_out >= (0 if own else 7) and \
            n['pf'] < 40 * frames + 1800 * copies and (h.var('n_kok', 2) - k0) * own == 0, \
            (cap, n_in, n_out, n['pf'], frames, copies)
        if cap:                                         # (mid-request in rxbuf: no room left in reqbuf)
            assert h.link.maxpay == 2048 and any(off == h.sym['rxbuf'] and rq[0] and rq[1] + cx - 6 > REQ_END
                                                 for k, seg, off, cx, rq in st['calls'] if k == 3)
        T.check(h)


def test_in_place_resend():
    """audit3 P7: the Pi's answer to a REPLY fragment sent in place damaged, and the GRiD's NAK lost too: the
    GRiD sends that fragment again, byte for byte (its header swapped in again: the 6 bytes there were put back
    after the first)."""
    from gridlink import glp
    h, st = p7_start(bridge='ar488')                # (its to_pi: whole frames)
    arm = {'n': 0}
    answer, to_pi = h.transport.answer, h.nano.to_pi
    def ans(frame):
        if arm['n'] == 1 and frame[1] & 0x7F != glp.P_NAK:
            f = bytearray(frame); f[len(f) // 2] ^= 0x10; frame = bytes(f); arm['n'] = 2
        return answer(frame)
    def tp(data, t):
        k = data[1] & 0x7F if len(data) > 1 else 0
        if arm['n'] == 0 and k == glp.G_REPLY and len(data) > 3000 and st['calls'][-1][1] != h.claude_psp:
            arm['first'] = bytes(data); arm['n'] = 1                # (an in-place fragment)
        elif arm['n'] == 2 and k == glp.G_NAK:
            arm['n'] = 3; h.link._answer_nak(); return
        elif arm['n'] == 3 and k == glp.G_REPLY:
            arm['resent'] = bytes(data); arm['n'] = 4
        return to_pi(data, t)
    h.transport.answer, h.nano.to_pi = ans, tp
    assert h.turn('write the file and read it back', sim_s=200)
    assert arm['n'] == 4 and arm['resent'] == arm['first'], (arm['n'], len(arm.get('resent', b'')))
    p7_check(h, st, (0, 1))
    T.check(h)


def test_in_place_read_damaged():
    """audit3 P7: a REQUEST fragment read in place into reqbuf damaged: CLAUDE NAKs it and puts back the 6 bytes
    its header went over; the Pi sends it again, read in place again, and the file is written whole.  With
    CLAUDE's own sum (use_fl 1) too: find_frame's scan of the damaged read stops at the read's end."""
    from unicorn import UC_HOOK_CODE
    from gridlink import glp
    for own in (0, 1):
        h, st = p7_start()
        if own: h.m.wr(h.claude_psp, h.sym['use_fl'], b'\1')
        seen = {'n': 0, 'scan': 0}
        answer = h.transport.answer
        def ans(frame):
            if frame[1] == glp.P_REQUEST | glp.MORE and len(frame) > 3000:
                seen['n'] += 1
                if seen['n'] == 2:                                  # (the second: read in place)
                    f = bytearray(frame); f[len(f) - 40] ^= 0x01; frame = bytes(f)
            return answer(frame)
        h.transport.answer = ans
        def scan(uc, addr, size, ud): seen['scan'] += 1             # (find_frame's steps)
        a = h.claude_psp * 16 + h.sym['find_frame.s']
        hk = h.m.mu.hook_add(UC_HOOK_CODE, scan, None, a, a)
        h.m.mu.ctl_remove_cache(a, a + 1)
        assert h.turn('write the file and read it back', sim_s=200)
        h.m.mu.hook_del(hk)
        frames = sum(1 for k, *_ in st['calls'] if k == 3)
        assert h.var('n_bad', 2) == 1 and seen['scan'] < frames + 3400, (own, h.var('n_bad', 2), seen, frames)
        p7_check(h, st, (1, 0))                                     # (the damaged one read twice)
        T.check(h)


def test_in_place_new_message():
    """audit3 P7: a REQUEST's first fragment that comes as an ASK's (the Pi never sends that: a type changed in
    flight), then the REQUEST's second, read in place after it: pf_reasm starts a new message with it, copied
    to reqbuf's start over the 6 bytes its header went over, which then stay as copied (not put back).  (The
    rest of that request is garbage: the test ends there.)"""
    from unicorn import UC_HOOK_CODE
    from gridlink import glp
    h, st = p7_start()
    seen = {'n': 0}
    answer = h.transport.answer
    def ans(frame):
        if frame[1] == glp.P_REQUEST | glp.MORE and len(frame) > 3000:
            seen['n'] += 1
            if seen['n'] == 1:
                frame = glp.encode(glp.P_ASK | glp.MORE, frame[2], frame[3], frame[6:-2], fl=True)
            elif seen['n'] == 2: seen['two'] = frame[6:-2]
        return answer(frame)
    h.transport.answer = ans
    base, Y = h.claude_psp * 16, h.sym
    got = {}
    def back(uc, addr, size, ud):                   # (link_read's rq_back done with the second)
        if 'two' in seen and 'buf' not in got and h.var('rq_type') == glp.P_REQUEST:
            got['buf'] = bytes(h.m.rd(h.claude_psp, Y['reqbuf'], h.var('rq_len', 2)))
            got['at'] = h.var('rq_at', 2)
    a = base + Y['rq_back.x']
    hk = h.m.mu.hook_add(UC_HOOK_CODE, back, None, a, a)
    h.m.mu.ctl_remove_cache(a, a + 1)
    h.type('write the file and read it back')
    try: assert h.run_until(lambda: 'buf' in got, 60), seen
    finally: h.m.mu.hook_del(hk)
    assert got['buf'] == seen['two'] and got['at'] == 0, (len(got['buf']), len(seen['two']), got['at'])


T.test_frames_in_place = test_frames_in_place
T.test_in_place_resend = test_in_place_resend
T.test_in_place_read_damaged = test_in_place_read_damaged
T.test_in_place_new_message = test_in_place_new_message

if __name__ == '__main__':
    names = [n for n in sorted(vars(T)) if n.startswith('test_')]
    want = [a for a in sys.argv[1:] if a.startswith('test')]
    if want: names = [n for n in names if any(a in n for a in want)]
    bad = 0
    for n in names:
        t0 = time.time()
        try:
            r = getattr(T, n)()
            extra = ''
            if r is not None and hasattr(r, 'big_s'): extra = '  (22.8 KB each way in %.2f s simulated)' % r.big_s
            print('ok   %-34s %5.1fs%s' % (n, time.time() - t0, extra), flush=True)
        except Exception:
            bad += 1
            print('FAIL %s' % n); traceback.print_exc()
    print('%d of %d passed' % (len(names) - bad, len(names)))
    sys.exit(1 if bad else 0)
