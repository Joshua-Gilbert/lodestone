"""The README's Claude screenshots (os/screens/readme/), from the emulator:
the real CLAUDE.COM and gridlink, with a scripted stand-in for Claude Code
(readme_claude.py) and the stand-in Firefox. The README's plot,
claude_plot.png, is a real capture from the 1520 (Shift-PrtSc), not made here.

    python3 tests/readme_shots.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PIL import Image
from grid_emu import EmuHarness
from test_emu_term import in_step, mismatch, wait_screen

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
    assert wait_screen(h, 'measure it again', 20), h.screen()
    h.term_type('yes, after the cal kit is on')
    assert in_step(h), mismatch(h)
    shot(h, 'claude_code')
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
