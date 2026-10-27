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
    assert h.var('ksum', 1) == 1 and h.var('use_fl', 1) == 1, (h.var('ksum', 1), h.var('use_fl', 1))
    assert h.link.grid_req == 16700, h.link.grid_req     # (CLAUDE 1.6's HELLO: req=, so 16 KB write requests)
    k0, st0 = h.var('n_kok', 2), dict(h.link.stats)
    assert h.turn('write a big file', sim_s=120)
    assert bytes(h.m.fs['A:\\BIG.TXT']) == big.replace('\n', '\r\n').encode()
    st = {k: v - st0.get(k, 0) for k, v in h.link.stats.items()}
    assert h.var('n_bad', 2) == 0 and not st.get('rx_nak') and not st.get('rx_bad'), st
    assert h.var('n_kok', 2) - k0 == st['tx_frames'] > 40, (h.var('n_kok', 2) - k0, st)   # (every Pi frame)
    assert st['rx_fletcher'] == st['rx_frames'], st                                       # (every one of ours)
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
