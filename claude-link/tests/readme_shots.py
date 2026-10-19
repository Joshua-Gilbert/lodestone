"""The README's Claude screenshots (os/screens/readme/), from the emulator:
the real CLAUDE.COM and gridlink, with a scripted stand-in for Claude Code
(readme_claude.py) and the stand-in Firefox.

    python3 tests/readme_shots.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PIL import Image
from grid_emu import EmuHarness
from gridlink import plot as PL
from test_emu_term import in_step, mismatch, wait_screen
import test_picture as TP

OUT = os.path.join(HERE, '..', '..', 'os', 'screens', 'readme')
SCRIPT = '%s %s' % (sys.executable, os.path.join(HERE, 'readme_claude.py'))


def shot(h, name):
    p = os.path.join(OUT, name + '.png')
    h.shot(p)
    os.remove(os.path.splitext(p)[0] + '.txt')
    Image.open(p).resize((1280, 800), Image.NEAREST).save(p)       # as the other README shots
    print(name); print(h.screen())


h = EmuHarness(term=SCRIPT, args='/A:7 /T')
try:
    h.boot()
    assert h.run_until(lambda: h.var('term') and h.var('connected'), 10), (h.m.crash, h.log, h.screen())
    assert wait_screen(h, 'C:\\TRACES', 20), h.screen()
    h.term_type('yes, and plot the phase too')
    assert in_step(h), mismatch(h)
    shot(h, 'claude_code')
    xs, ys = TP.sweep(1601)
    p = PL.Plot([{'name': 'S21', 'x': xs, 'y': ys}], title='8753D S21', x_label='Hz', y_label='dB')
    h.router.term.show_picture(p.bits, 'readme', title='8753D S21')
    assert h.run_until(lambda: '8753D S21' in h.screen().split('\n')[24], 10), h.screen()
    shot(h, 'claude_plot')
finally:
    h.close()

from fake_firefox import FakeFirefox, missing
if missing():
    sys.exit('gridfox shot skipped: %s' % missing())
f = FakeFirefox()
h = EmuHarness(term=SCRIPT, web='%s -m gridfox --port %d http://test.local/bench' % (sys.executable, f.port),
               args='/A:7 /W')
try:
    h.boot()
    assert h.run_until(lambda: h.var('term') and h.var('connected'), 10), (h.m.crash, h.log, h.screen())
    assert wait_screen(h, 'Getting a trace over GPIB', 30), h.screen()
    assert h.run_until(lambda: h.screen().split('\n')[24].startswith(' Bench notes'), 5)
    assert in_step(h), mismatch(h)
    shot(h, 'gridfox')
finally:
    h.close(); f.close()
