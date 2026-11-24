"""gridlink's serial transports when their port fails (gridlink/link.py's PortKeeper): AR488Serial, SerialLink and
ModemLink drop the port, say so once, and open it again every 2 s, set up as at the start; serve() and the Link
never see the error.  And PicoBridge (gridlink/pico.py), which reopens in its own threads.  The ports are
serial_model's PiPort, given through `opener`, so no pyserial port is needed.

    python3 tests/test_transports.py
"""
import os, struct, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import termios
from serial_model import PiPort
from ar488_model import AR488Model
from gridlink import glp, pico
from gridlink.link import AR488Serial, Link, serve
from gridlink.serline import SerialLink, ModemLink, RING

EVERY = 0.1                                 # (REOPEN_EVERY, shortened)


def port(**kw):
    """A PiPort on the wall clock: bytes arrive at once; a read with nothing waits 5 ms, as a timeout would."""
    p = PiPort(time.monotonic, lambda t: None)
    p.timeout = 0.005
    for k, v in kw.items(): setattr(p, k, v)
    return p


def give(*made):
    """An opener handing out these ports in turn (an exception in the list: that open fails), then fresh ones;
    -> (opener, the ports it handed out)."""
    made = list(made); out = []
    def opener(name):
        p = made.pop(0) if made else port()
        if isinstance(p, BaseException): raise p
        out.append(p); return p
    return opener, out


def lines(log, text):
    return [l for l in log if text in l]


def until(cond, secs=2.0, step=None):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond(): return True
        if step: step()
        else: time.sleep(0.005)
    return cond()


def hello():
    return glp.encode(glp.G_HELLO, 1, 0, bytes([1, glp.GF_FCS, 0, 4, 80, 24]), fl=True)


def test_serial_read_fails_once():
    # serve() over a SerialLink whose read raises once (a USB adapter pulled): the port is closed, reopened,
    # and the Link goes on with the next port's bytes; one line each way, nothing raised out of serve()
    for err in (OSError(5, 'Input/output error'), termios.error(5, 'Input/output error')):
        log = []
        first = port(fail=err)
        opener, ports = give(first)
        t = SerialLink('/dev/x', 19200, log=log.append, opener=opener); t.REOPEN_EVERY = EVERY
        t.open(); t.configure()
        got = []
        L = Link(t, lambda mt, body: got.append(mt), log=log.append, hold=0)
        stop = threading.Event()
        th = threading.Thread(target=serve, args=(t, L, stop), daemon=True); th.start()
        assert until(lambda: len(ports) == 2), (ports, log)
        assert first.closed
        for b in hello(): ports[1].arrive(b, 0)
        assert until(lambda: got and ports[1].written), (got, log)
        stop.set(); th.join(1)
        assert not th.is_alive() and got == [glp.G_HELLO] and ports[1].written[0] == glp.SYNC, (got, log)
        assert len(lines(log, 'read on /dev/x failed')) == 1 and len(lines(log, 'open again')) == 1, log


def test_missing_at_start():
    # no port at the start (an adapter not plugged in): no exception from open() or configure(), one line,
    # and read() opens it when it comes
    log = []
    opener, ports = give(FileNotFoundError(2, 'No such file or directory'), FileNotFoundError(2, 'No such file'))
    t = SerialLink('/dev/x', 19200, log=log.append, opener=opener); t.REOPEN_EVERY = EVERY
    t.open(); t.configure()
    assert t.ser is None and len(lines(log, 'cannot open /dev/x')) == 1, log
    assert until(lambda: t.read() == b'' and len(ports) == 1, 1.0), (ports, log)
    assert len(lines(log, 'cannot open /dev/x')) == 1, log      # (the second failure: not said again)


def test_flapping_port_bounded():
    # a port that opens and fails at its first read: opened no more than every REOPEN_EVERY, and said once
    log = []
    opener, ports = give(*[port(fail=OSError(5, 'EIO')) for _ in range(50)])
    t = SerialLink('/dev/x', 19200, log=log.append, opener=opener); t.REOPEN_EVERY = EVERY
    t.open()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.55: t.read()
    assert 4 <= len(ports) <= 7, len(ports)
    assert len(lines(log, 'failed')) == 1 and len(lines(log, 'open again')) == 1, log


class NoFlushPort(PiPort):
    """A port that opens and then fails its tcflush (reset_input_buffer), as a half-dead adapter's node can."""
    def __init__(s, err):
        PiPort.__init__(s, time.monotonic, lambda t: None); s.timeout = 0.005; s.err = err
    def reset_input_buffer(s):
        raise s.err


def test_open_then_flush_fails_closed():
    # a port that opens but fails as it is set up (reset_input_buffer, after AR488's reset wait): each attempt's
    # port is closed, as it is not yet s.ser for _drop to close (one fd lost every 2 s, else); said once
    for make in (lambda o, log: SerialLink('/dev/x', 19200, log=log.append, opener=o),
                 lambda o, log: AR488Serial('/dev/x', 115200, 7, log=log.append, opener=o)):
        for err in (OSError(5, 'EIO'), termios.error(5, 'Input/output error')):
            log = []
            made = []
            t = make(lambda p: made.append(NoFlushPort(err)) or made[-1], log)
            t.RESET_WAIT = 0; t.REOPEN_EVERY = 0.02
            t.open(); t.configure()
            assert until(lambda: t.read() == b'' and len(made) >= 4, 1.0), (made, log)
            assert t.ser is None and all(p.closed for p in made), [p.closed for p in made]
            assert len(lines(log, 'cannot open /dev/x')) == 1, log


def test_ring_again_on_a_new_port():
    # a ring that went on a port that then failed: the new port's _setup lets ring() write one again (rung
    # would otherwise stay True there till the next answer, and an idle CLAUDE.COM would never be woken)
    log = []
    opener, ports = give()
    t = SerialLink('/dev/x', 19200, log=log.append, opener=opener); t.REOPEN_EVERY = EVERY
    t.open()
    t.ring()
    assert t.rung and bytes(ports[0].written) == RING, ports[0].written
    ports[0].fail = OSError(5, 'EIO')
    assert t.read() == b'' and t.ser is None
    assert until(lambda: t.read() == b'' and t.ser is not None, 1.0)
    t.ring()
    assert t.rung and bytes(ports[1].written) == RING, ports[1].written


def test_said_again_after_recovery():
    # fail, recover, fail on an idle port (no bytes from the GRiD between: no CLAUDE, a modem waiting): the
    # second failure is said too, once the reopened port was set up cleanly and read without failing
    def serial(log):
        opener, ports = give()
        t = SerialLink('/dev/x', 19200, log=log.append, opener=opener)
        return t, ports
    def modem(log):
        opener, ports = give(modem_port(), modem_port(), modem_port())
        t = ModemLink('/dev/x', 115200, log=log.append, opener=opener)
        return t, ports
    def ar488(log):
        made = []
        t = AR488Serial('/dev/x', 115200, 7, log=log.append, opener=lambda p: made.append(ModelPort()) or made[-1])
        t.RESET_WAIT = 0
        return t, made
    for make in (serial, modem, ar488):
        log = []
        t, ports = make(log)
        t.REOPEN_EVERY = EVERY
        t.open(); t.configure()
        for k in (1, 2):
            ports[-1].fail = OSError(5, 'EIO')
            assert t.read() == b'' and t.ser is None, (make.__name__, log)
            assert until(lambda: t.read() == b'' and t.ser is not None, 6.0), (make.__name__, log)
            for _ in range(3): assert t.read() == b''                 # (idle)
            assert len(lines(log, 'read on /dev/x failed')) == k, (make.__name__, k, log)
            assert len(lines(log, 'open again')) == k, (make.__name__, k, log)


def test_fault_not_a_port_error():
    # an error that is gridlink's own (an AttributeError in _read, say) is no unplugged port: its traceback said
    # once, the port kept and not reopened (a reopen resets the AR488's Nano through DTR), the next read reads
    log = []
    opener, ports = give()
    t = SerialLink('/dev/x', 19200, log=log.append, opener=opener); t.REOPEN_EVERY = EVERY
    t.open()
    for _ in range(3):
        ports[0].fail = AttributeError("'NoneType' object has no attribute 'x'")
        assert t.read() == b''
    assert t.ser is ports[0] and not ports[0].closed and len(ports) == 1, (ports, log)
    faults = lines(log, 'a fault in gridlink')
    assert len(faults) == 1 and 'Traceback' in faults[0] and 'AttributeError' in faults[0], log
    assert not lines(log, 'reopening'), log
    ports[0].arrive(ord('x'), 0)
    assert t.read() == b'x'


def test_fault_in_setup_kept():
    # a fault in a reopen's _setup (gridlink's, not the port's): said once with its traceback, the port kept,
    # not opened again and again
    log = []
    opener, ports = give()
    t = SerialLink('/dev/x', 19200, log=log.append, opener=opener); t.REOPEN_EVERY = EVERY
    t._setup = lambda: {}['no such key']
    t.open()
    ports[0].fail = OSError(5, 'EIO')
    t.read()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.5: t.read()
    assert len(ports) == 2 and t.ser is ports[1], (ports, log)
    faults = lines(log, 'setup on /dev/x: a fault in gridlink')
    assert len(faults) == 1 and 'KeyError' in faults[0], log


def test_ring_write_fails():
    # a ring whose write fails never went: on the reopened port the next ring() writes it (rung stayed True,
    # so ring() did nothing on the new port till the next answer)
    log = []
    opener, ports = give(port(fail_write=OSError(5, 'EIO')))
    t = SerialLink('/dev/x', 19200, log=log.append, opener=opener); t.REOPEN_EVERY = EVERY
    t.open()
    t.ring()
    assert not t.rung and t.ser is None, (t.rung, log)
    assert until(lambda: t.read() == b'' and t.ser is not None, 1.0)
    t.ring()
    assert t.rung and bytes(ports[1].written) == RING, ports[1].written


def test_answer_fails():
    # answer()'s write failing: dropped and said once, not raised into the Link
    log = []
    opener, ports = give(port(fail_write=OSError(5, 'EIO')))
    t = SerialLink('/dev/x', 19200, log=log.append, opener=opener); t.REOPEN_EVERY = EVERY
    t.open()
    t.answer(b'frame')
    assert t.ser is None and len(lines(log, 'write on /dev/x failed')) == 1, log
    assert until(lambda: t.read() == b'' and t.ser is not None, 1.0)
    t.answer(b'again')
    assert bytes(ports[1].written) == b'again'


def test_given_port_not_reopened():
    # ser= given (grid_emu's PiPort): a failure is raised, as before
    p = port(fail=OSError(5, 'EIO'))
    t = SerialLink('/dev/x', 19200, log=lambda *a: None, ser=p)
    t.open()
    try:
        t.read()
    except OSError:
        pass
    else:
        raise AssertionError('not raised')
    assert t.ser is p and not p.closed


def modem_port(**kw):
    """A USB modem that answers OK to every command."""
    p = port(**kw)
    def on_write(d):
        if d.endswith(b'\r'):
            for b in b'\r\nOK\r\n': p.arrive(b, 0)
    p.on_write = on_write
    return p


def test_modem_set_up_again():
    # the modem's port reopened: set up again (ATZ ... ATS0=1), offline, waiting for the next call
    log = []
    first = modem_port()
    opener, ports = give(first, modem_port())
    t = ModemLink('/dev/m', 115200, log=log.append, opener=opener); t.REOPEN_EVERY = EVERY
    t.open(); t.configure()
    assert b'ATS0=1' in first.written and not t.online, (first.written, log)
    t.online = True; first.cd = True
    first.fail = OSError(5, 'EIO')
    assert t.read() == b'' and t.ser is None
    assert until(lambda: t.read() == b'' and len(ports) == 2, 1.0), log
    assert b'ATZ' in ports[1].written and b'ATS0=1' in ports[1].written and not t.online, ports[1].written


class ModelPort:
    """AR488Model behind a pyserial-like port on the wall clock: what the Pi writes reaches the model at once,
    what the model sends is readable when its serial time comes."""
    def __init__(s):
        s.clock = lambda: time.monotonic() * 1e6
        s.model = AR488Model(s.clock, addr=7, patched=True, to_pi=s._to_pi)
        s.inq = bytearray(); s.fail = None; s.closed = False; s.lock = threading.RLock()
    def _to_pi(s, data, t):
        with s.lock: s.inq += data          # (the serial time is under a ms for these replies)
    def read(s, n=1):
        if s.fail: e, s.fail = s.fail, None; raise e
        s.model.service()
        with s.lock:
            if not s.inq: time.sleep(0.005); s.model.service()
            d = bytes(s.inq[:n]); del s.inq[:n]
        return d
    @property
    def in_waiting(s):
        with s.lock: return len(s.inq)
    def write(s, data):
        s.model.pi_write(data, latency_us=0); s.model.service(); return len(data)
    def reset_input_buffer(s):
        with s.lock: s.inq.clear()
    def close(s): s.closed = True


def test_ar488_configured_again():
    # AR488Serial.configure through the AR488 model: device mode, our address, the patched firmware found;
    # after its port fails it is configured again (the Nano was reset through DTR)
    log = []
    made = []
    t = AR488Serial('/dev/n', 115200, 7, log=log.append, opener=lambda p: made.append(ModelPort()) or made[-1])
    t.RESET_WAIT = 0; t.REOPEN_EVERY = EVERY
    t.open()
    v = t.configure()
    m = made[0].model
    assert '+GRiD1' in v and t.patched and t.frame_limit == glp.PATCHED_FRAME_MAX, (v, log)
    assert m.mode_device and m.addr == 7 and m.eoi and m.eos == 3, (m.mode_device, m.addr, m.eoi, m.eos)
    assert len(lines(log, 'patched firmware, address 7')) == 1, log
    made[0].fail = OSError(5, 'EIO')
    assert t.read() == b'' and t.ser is None and made[0].closed
    assert until(lambda: t.read() == b'' and len(made) == 2 and t.ser is not None, 6.0), log
    assert made[1].model.mode_device and len(lines(log, 'patched firmware, address 7')) == 2, log


# ---- PicoBridge -------------------------------------------------------------------------------------------
class PicoPort(PiPort):
    """The bridge's USB port, as far as PicoBridge needs: HELLO and PONG answered (pong=False: PONGs stop);
    then, with `fail` set, its next read raises that.  fail_hello: no HELLO, the first read after HELLO_REQ
    raises that instead (a port that fails as it opens).  before_read, after_read: called once, at the start of
    the next read or once it has its bytes (another thread's doing, in the middle of a read)."""
    def __init__(s, fail=None, pong=True, fail_hello=None):
        PiPort.__init__(s, time.monotonic, lambda t: None)
        s.timeout = 0.005; s.after_hello = fail; s.pong = pong; s.fail_hello = fail_hello
        s.before_read = s.after_read = None
        s.on_write = s._got
    def _got(s, data):
        for raw in data.split(b'\0')[:-1]:
            f = pico.cobs_decode(raw)
            if f[0] == pico.F_HELLO_REQ and s.fail_hello:
                s.fail = s.fail_hello
            elif f[0] == pico.F_HELLO_REQ:
                s.send(struct.pack('<BBHHIH', pico.F_HELLO, 1, 16383, 240, 0, 0) + b'bridge fw 2026-10-24 (test)')
                s.armed = True
            elif f[0] == pico.F_PING and s.pong:
                s.send(bytes([pico.F_PONG, 1, 7]) + bytes(44))
    def read(s, n=1):
        if getattr(s, 'armed', False) and not s.inq:      # (the HELLO read: the next read fails)
            s.armed = False; s.fail = s.after_hello
        if s.before_read: f, s.before_read = s.before_read, None; f()
        d = PiPort.read(s, n)
        if s.after_read and d: f, s.after_read = s.after_read, None; f()
        return d
    def send(s, frame):
        for b in pico.cobs_encode(frame): s.arrive(b, 0)


def test_pico_dropped_in_hello_wait():
    # _open_once's guard after its HELLO wait (`s.ser is ser`): another thread (the pinger, on its view from
    # before the reopen) drops the port while the wait's read is taking the HELLO.  The feed then sets
    # connected again, with s.ser gone, so connected alone would pass the port for open: open() would return
    # with no port, and say "bridge on" for it.  It is dropped instead and the next port opened
    log = []
    made = []
    ports = [PicoPort(), PicoPort()]
    b = pico.PicoBridge('/dev/p', log=log.append, opener=lambda p: made.append(ports[len(made)]) or made[-1])
    ports[0].after_read = b._drop                # (as the other thread would, as the HELLO is read)
    try:
        b.open()
        assert ports[0].closed and len(made) == 2 and b.ser is ports[1] and b.proto.connected, (made, log)
        assert len(lines(log, 'bridge on /dev/p')) == 1, log
    finally:
        b.stop.set()


def test_pico_reader_dropped_meanwhile():
    # the reader's guard (`if s.ser is ser`): a read that fails because another thread (the pinger) has just
    # dropped the port under it is not said as a failure; the reader opens the port again
    log = []
    made = []
    b = pico.PicoBridge('/dev/p', log=log.append, opener=lambda p: made.append(PicoPort()) or made[-1])
    try:
        b.open()
        gate, entered = threading.Event(), threading.Event()
        def hold():                              # (the reader's read, held till the port is dropped)
            entered.set(); gate.wait(2)
        made[0].before_read = hold
        assert entered.wait(2)
        b._drop()                                # (the pinger's: the held read then raises, the port closed)
        gate.set()
        assert until(lambda: len(made) == 2 and b.proto.connected, 4.0), (made, log)
        assert made[0].closed and not lines(log, 'read failed'), log
    finally:
        b.stop.set()


def test_pico_opens_and_fails_bounded():
    # a bridge port that opens, answers HELLO and fails at its first read: opened again no sooner than 2 s on
    # (the reader used to reopen at once, in a loop), and the failure said once a connection
    log = []
    made = []
    def opener(p):
        made.append(PicoPort(fail=OSError(5, 'EIO'))); return made[-1]
    b = pico.PicoBridge('/dev/p', log=log.append, opener=opener)
    try:
        b.open()
        assert len(made) == 1
        time.sleep(1.0)
        assert len(made) == 1, len(made)
        time.sleep(1.5)
        assert len(made) == 2, len(made)
        assert len(lines(log, 'read failed')) <= 2, log      # (once a connection: each one came up)
    finally:
        b.stop.set()


def test_pico_fails_as_it_opens():
    # the reader's reopen: a port whose read fails in the wait for HELLO (_open_once's except) is said once and
    # tried again, the reader thread alive; one whose HELLO_REQ write fails is not read again once dropped (the
    # wait's `s.ser is ser`); then a good port opens
    for bad in (dict(fail_hello=OSError(5, 'EIO')), dict(fail_write=OSError(5, 'EIO'))):
        log = []
        made = []
        ports = [PicoPort(fail=OSError(5, 'EIO')), PicoPort(), PicoPort()]
        for k, v in bad.items(): setattr(ports[1], k, v)
        def opener(p):
            made.append(ports[len(made)]); return made[-1]
        b = pico.PicoBridge('/dev/p', log=log.append, opener=opener)
        before = set(threading.enumerate())
        try:
            b.open()
            reader = [th for th in threading.enumerate() if th.name == 'pico-reader' and th not in before]
            assert len(reader) == 1, reader
            assert until(lambda: len(made) == 3 and b.proto.connected, 8.0), (bad, made, log)
            assert reader[0].is_alive(), bad
            if 'fail_hello' in bad:
                assert len(lines(log, '/dev/p failed as it opened')) == 1, log
            else:
                assert len(lines(log, 'write failed')) == 1 and not lines(log, 'failed as it opened'), log
        finally:
            b.stop.set()


def data(gen, payload):
    return struct.pack('<BHB', pico.F_DATA, gen, pico.DF_EOI) + payload


def test_pico_reader_and_reopen():
    # PicoBridge's reader: the GRiD's bytes out of DATA frames through read(); serve() over a port whose read
    # raises once: reopened (HELLO again), the Link fed from the new port, nothing raised
    log = []
    made = []
    def opener(p):
        made.append(PicoPort()); return made[-1]
    b = pico.PicoBridge('/dev/p', log=log.append, opener=opener)
    got = []
    L = Link(b, lambda mt, body: got.append(mt), log=log.append, hold=0)
    stop = threading.Event()
    try:
        b.open()
        th = threading.Thread(target=serve, args=(b, L, stop), daemon=True); th.start()
        made[0].send(data(1, hello()))
        assert until(lambda: got == [glp.G_HELLO]), (got, log)
        assert until(lambda: any(pico.cobs_decode(r)[0] == pico.F_TX for r in made[0].written.split(b'\0')[:-1]))
        made[0].fail = OSError(5, 'EIO')
        assert until(lambda: len(made) == 2 and b.proto.connected, 4.0), (made, log)
        assert made[0].closed and len(lines(log, 'read failed')) == 1, log
        made[1].send(data(2, glp.encode(glp.G_POLL, 2, 1, b'', fl=True)))
        assert until(lambda: L.stats['rx_frames'] == 2), L.stats
        assert th.is_alive()
    finally:
        stop.set(); b.stop.set()


def test_pico_pinger():
    # PONGs stop: after 6 s without one the pinger drops the port, and the reader opens it again
    log = []
    made = []
    def opener(p):
        made.append(PicoPort(pong=bool(made))); return made[-1]     # (the first port's PONGs have stopped)
    b = pico.PicoBridge('/dev/p', log=log.append, opener=opener)
    try:
        b.open()
        b.proto.last_pong -= 10                        # (as if 10 s had gone by without one)
        assert until(lambda: len(made) == 2 and b.proto.connected, 5.0), (made, log)
        assert len(lines(log, 'no PONG for 6 s')) == 1 and made[0].closed, log
        n = b.proto.pongs
        assert until(lambda: b.proto.pongs > n, 2.5), log          # (the new port answers PINGs)
    finally:
        b.stop.set()


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
