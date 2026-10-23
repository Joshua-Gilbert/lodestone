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


T.test_driver_frame_check = test_driver_frame_check
T.test_srq_on_irq5 = test_srq_on_irq5
T.test_gpibirq_0_turns_it_off = test_gpibirq_0_turns_it_off
T.test_irq5_storm_masks_it = test_irq5_storm_masks_it
T.test_quit_to_dos = test_quit_to_dos
T.test_write_no_name_leaves_no_temp = test_write_no_name_leaves_no_temp
T.test_write_safe_keeps_the_only_copy = test_write_safe_keeps_the_only_copy
T.test_run_tm5000g_from_claude = test_run_tm5000g_from_claude

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
