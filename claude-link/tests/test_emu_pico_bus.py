"""The real CLAUDE.COM over pico_model's closer looks at the bus (H26), each opt-in, so the default model and the
1520 suites' timing stay as they are:

  pico-early  EARLY answers (fw 2026-10-23a): SRQ at a big reply's first TX frame, the rest readable as it crosses
              USB, so KGPIB's read meets a reply still arriving and waits in the middle of the message
  pico-nrfd   the GRiD's messages held by NRFD at every 240 bytes (the bridge's receive ring backed up)

and TALK_WAIT (addressed to talk with nothing ready, the bridge says so and waits off the bus) on the model and
PicoProto alone: CLAUDE.COM reads only after SRQ, so through it the bridge never meets that.

    python3 tests/test_emu_pico_bus.py
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_emu_pico import big_turn
from pico_model import PicoModel
from gridlink import pico
from gridlink.pico import PicoProto


def test_early_read_while_arriving():
    h, t = big_turn(bridge='pico-early')
    assert h.link.t.proto.early and h.nano.early
    assert h.nano.early_frames > 0, h.nano.early_frames           # (gridlink sent its replies EARLY)
    assert h.nano.n_streamed > 0, h.nano.n_streamed               # (big replies read while their rest came)
    assert h.nano.bus_waits() > 0, h.nano.bus_waits()             # (and KGPIB waited mid-message for bytes)
    assert h.nano.big_tx == 0 and not h.nano.violations, h.nano.violations
    assert h.var('n_fail', 2) == 0


def test_nrfd_held():
    h, t = big_turn(bridge='pico-nrfd')
    assert h.nano.nrfd_holds > 10, h.nano.nrfd_holds               # (the 22 KB file's REPLYs, held as they went)
    assert h.var('n_fail', 2) == 0 and not h.nano.violations, h.nano.violations


def test_talk_wait_then_reply():
    # the bridge addressed to talk before the Pi's reply is in: TALK_WAIT to the Pi (its consumed count, which
    # PicoProto takes: X122), then the reply goes on the bus once it comes, nothing driven meanwhile
    now = [0.0]
    to_pi = []
    lose = []                                            # (frame types lost on the way to the Pi)
    m = PicoModel(lambda: now[0], to_pi=lambda d, t: to_pi.append(d), talk_wait=True)
    p = PicoProto(m.pi_write, log=lambda *a: None)
    def pump():
        now[0] += 1000; m.service()
        while to_pi:
            d = to_pi.pop(0)
            if pico.cobs_decode(d[:-1])[0] not in lose: p.feed(d)
    p.hello(); pump(); pump()
    assert p.connected and m.online
    def message(text):
        for b in text: m.rx_byte(b, b == ord('?'))      # (a message, so a generation to answer)
        m.on_listen(False); pump()
    message(b'GRiD?')
    p.answer(b'first'); pump()
    lose.append(pico.F_CREDIT)                          # (the CREDIT for it lost)
    m.on_talk(); pump()
    assert bytes(m.out) == b'first' and m.consumed == 5 and p.consumed == 0, (m.out, m.consumed, p.consumed)
    message(b'again?')
    m.on_talk()
    assert m.waiting_talk and m.talk_waits == 1 and not m.out
    pump()
    assert p.stats['TALK_WAIT'] == 1 and p.consumed == 5, (p.stats, p.consumed)   # (TALK_WAIT's count taken)
    del lose[:]
    p.answer(b'the reply')
    pump()
    assert bytes(m.out) == b'the reply' and not m.waiting_talk, m.out


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
