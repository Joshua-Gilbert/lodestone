"""gridlink/tests/test_emu.py's scenarios with CLAUDE.COM running on the
Grid-OS 0.2 kernel (built-in GPIB, the real GRIDCMD.COM shell) instead of the Python
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


T.test_quit_to_dos = test_quit_to_dos
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
