"""gridlink restarted under a running CLAUDE (a crash, a deploy, `systemctl restart gridlink`): the fresh process
answers nothing before the GRiD's HELLO, so CLAUDE's link wait fails once and it starts the link over, instead of
taking NOP for "nothing new" for as long as it runs.  The real CLAUDE.COM in the emulator (grid_emu.py), and Link
on its own.

    python3 tests/test_emu_restart.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_anthropic import reply
from grid_emu import EmuHarness
from gridlink import glp
from gridlink.link import Link


class Sink:
    """A transport that keeps what Link answers."""
    frame_limit = glp.PATCHED_FRAME_MAX
    def __init__(s): s.out = []
    def answer(s, frame): s.out.append(frame)


def frame(kind, seq, payload=b''):
    return glp.encode(kind, seq, 0, payload, fl=True)


def test_link_silent_before_hello():
    # three frames from a CLAUDE mid-session reach a fresh Link: none answered, none passed on, one line
    t, got, log = Sink(), [], []
    L = Link(t, lambda mt, body: got.append(mt), log=log.append, hold=0)
    for i, (k, p) in enumerate(((glp.G_POLL, b''), (glp.G_PROMPT, b'again'), (glp.G_KEYS, b'x'))):
        assert L.feed(frame(k, 10 + i, p)) == 1
    assert not t.out and not got and not L.connected, (t.out, got)
    early = [l for l in log if 'before its HELLO' in l]
    assert len(early) == 1 and L.stats['rx_early'] == 3, (log, L.stats)
    assert L.last_g is None and L.rx_new == 0
    # a NAK is still answered (with a NAK: nothing answered yet), and a HELLO connects as ever
    L.feed(frame(glp.G_NAK, 13))
    assert len(t.out) == 1 and t.out[0][1] == glp.P_NAK, t.out
    L.feed(frame(glp.G_HELLO, 1, bytes([1, glp.GF_FCS, 0, 4, 80, 24])))
    assert L.connected and got == [glp.G_HELLO] and len(t.out) == 2, (got, t.out)
    L.feed(frame(glp.G_POLL, 2))
    assert len(t.out) == 3 and len([l for l in log if 'before its HELLO' in l]) == 1


def restart(bridge):
    h = EmuHarness([reply(('text', 'first answer XYZZY')), reply(('text', 'second answer PLUGH'))], bridge=bridge)
    h.boot(); assert h.connect(), ('no connection', h.m.crash, h.screen())
    assert h.turn('hi') and 'XYZZY' in h.screen(), h.screen()
    assert h.var('n_fail', 2) == 0
    old = h.session
    h.restart_gridlink()
    assert h.session is not old and h.router.app is None and not h.link.connected
    # the prompt typed now meets the fresh gridlink: unanswered, the link fails once and CLAUDE starts over
    h.type('lost')
    assert h.run_until(lambda: h.var('n_fail', 2) >= 1 and h.idle() and h.link.connected, 15), \
        ('no new link', h.var('n_fail', 2), h.var('connected'), h.link.stats, h.screen())
    assert h.var('n_fail', 2) == 1, h.var('n_fail', 2)
    assert h.router.app == 'chat' and h.session.grid is not None
    early = [l for l in h.log if 'before its HELLO' in str(l)]
    assert len(early) == 1, h.log
    # the link works: typed again, the answer comes, and no more failures
    assert h.turn('again') and 'PLUGH' in h.screen(), h.screen()
    assert h.var('n_fail', 2) == 1 and not h.m.crash, (h.var('n_fail', 2), h.m.crash)
    assert len(h.client.requests) == 2, len(h.client.requests)     # ('lost' never reached Claude)


def test_restart_ar488():
    restart('ar488')


def test_restart_pico():
    restart('pico')


if __name__ == '__main__':
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    if len(sys.argv) > 1: names = [n for n in names if any(a in n for a in sys.argv[1:])]
    ok = 0
    for n in names:
        try:
            globals()[n](); ok += 1; print('ok  ', n)
        except Exception:
            import traceback; print('FAIL', n); traceback.print_exc()
    print('%d of %d passed' % (ok, len(names)))
    sys.exit(0 if ok == len(names) else 1)
