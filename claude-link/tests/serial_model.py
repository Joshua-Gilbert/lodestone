"""The GRiD's serial ports for the emulator tests (tools/SERLINK.ASM, gridlink/serline.py).

Uart        the 1520's 16450 at 3F8h (COM1, IRQ 4) or 2F8h (COM2, IRQ 3): one received byte held (the next one
            overwrites it if it isn't read), each byte taking a character's time on the line both ways.
PiPort      the Pi's end, as pyserial gives it to SerialLink / ModemLink: read(), write(), in_waiting, cd, dtr.
Cable       a null-modem cable between them, at the UART's speed.
ModemCall   the GRiD's internal modem and the Pi's USB modem, through the HT802: Hayes commands on both ends
            (the GRiD's echoes till ATE0), ATDT rings the Pi's modem, which answers by itself (ATS0=1), CONNECT
            2400 on both; then the bytes at 2400 baud; DTR down on either end hangs up (NO CARRIER, DCD down).
Times are the emulator's microseconds (Machine.us)."""
import collections


def ctime(baud):
    return 1e7 / baud                                     # us a character (8N1: 10 bits)


class Uart:
    def __init__(s, base, irq, clock, schedule):
        s.base, s.irq, s.clock, s.schedule = base, irq, clock, schedule
        s.lcr = 0x03; s.dll = 12; s.dlm = 0; s.ier = 0; s.mcr = 0; s.scr = 0; s.fcr = 0
        s.rbr = 0; s.full = False; s.overruns = 0
        s.thre = False                                    # the transmitter-empty interrupt, pending
        s.rxq = collections.deque()                       # (time, byte) on their way to the GRiD
        s.tx_until = 0.0
        s.peer = None                                     # Cable or ModemCall
        s.txd = bytearray()                               # everything the GRiD sent

    def baud(s):
        return 115200 // ((s.dlm << 8 | s.dll) or 1)

    def to_grid(s, data, t0=None):
        """Bytes onto the line toward the GRiD, starting at t0 (now), one a character's time."""
        t = max(s.clock() if t0 is None else t0, s.rxq[-1][0] if s.rxq else 0.0)
        for b in data:
            t += ctime(s.baud()); s.rxq.append((t, b))
        if s.rxq: s.schedule(s.rxq[0][0])

    def update(s):
        now = s.clock()
        while s.rxq and s.rxq[0][0] <= now:
            if s.full: s.overruns += 1
            s.rbr = s.rxq.popleft()[1]; s.full = True
        if s.rxq: s.schedule(s.rxq[0][0])

    def int_pending(s):
        s.update()
        if not s.mcr & 8: return False                    # (OUT2: the IRQ's gate)
        return bool(s.ier & 1 and s.full) or bool(s.ier & 2 and s.thre and s.clock() >= s.tx_until)

    def read(s, o):
        s.update()
        dlab = s.lcr & 0x80
        if o == 0:
            if dlab: return s.dll
            s.full = False; return s.rbr
        if o == 1: return s.dlm if dlab else s.ier
        if o == 2:
            if s.ier & 1 and s.full: return 0x04
            if s.ier & 2 and s.thre and s.clock() >= s.tx_until:
                s.thre = False; return 0x02                # (read: cleared)
            return 0x01
        if o == 3: return s.lcr
        if o == 4: return s.mcr
        if o == 5: return (0x60 if s.clock() >= s.tx_until else 0) | (1 if s.full else 0)
        if o == 6: return s.peer.msr() if s.peer else 0
        return s.scr

    def write(s, o, v):
        dlab = s.lcr & 0x80
        if o == 0:
            if dlab: s.dll = v; return
            t = max(s.clock(), s.tx_until) + ctime(s.baud()); s.tx_until = t
            s.txd.append(v); s.thre = True; s.schedule(t)
            if s.peer: s.peer.from_grid(v, t)
        elif o == 1:
            if dlab: s.dlm = v
            else:
                if v & 2 and not s.ier & 2: s.thre = True     # (enabled with the transmitter empty: at once)
                s.ier = v
        elif o == 2: s.fcr = v
        elif o == 3: s.lcr = v
        elif o == 4:
            old, s.mcr = s.mcr, v
            if s.peer and (old ^ v) & 1: s.peer.grid_dtr(bool(v & 1))
        elif o == 7: s.scr = v


class PiPort:
    """The Pi's serial port: what reaches it is readable from its time on; writes go to `on_write`."""
    def __init__(s, clock, schedule):
        s.clock, s.schedule = clock, schedule
        s.inq = collections.deque()                        # (time, byte)
        s.on_write = None; s.on_dtr = None
        s.cd = True; s._dtr = True; s.rts = True
        s.written = bytearray()

    def arrive(s, b, t):
        s.inq.append((t, b)); s.schedule(t)

    def _ready(s):
        now = s.clock(); n = 0
        for t, _ in s.inq:
            if t > now: break
            n += 1
        return n

    @property
    def in_waiting(s): return s._ready()

    def read(s, n=1):
        k = min(n, s._ready())
        return bytes(s.inq.popleft()[1] for _ in range(k))

    def write(s, data):
        s.written += data
        if s.on_write: s.on_write(bytes(data))
        return len(data)

    def reset_input_buffer(s):
        k = s._ready()
        for _ in range(k): s.inq.popleft()

    @property
    def dtr(s): return s._dtr

    @dtr.setter
    def dtr(s, v):
        s._dtr = bool(v)
        if s.on_dtr: s.on_dtr(s._dtr)


class Cable:
    """A null-modem cable: the GRiD's UART and the Pi's adapter at one speed (the UART's)."""
    def __init__(s, uart, pi):
        s.uart, s.pi = uart, pi
        uart.peer = s
        pi.on_write = lambda d: uart.to_grid(d)
        pi.cd = True

    def from_grid(s, b, t): s.pi.arrive(b, t)
    def grid_dtr(s, up): pass
    def msr(s): return 0xB0                               # DCD, DSR, CTS: the Pi's DTR and RTS


class Hayes:
    """One end's command interpreter."""
    def __init__(s, name):
        s.name = name; s.echo = True; s.line = b''; s.s0 = 0; s.cmds = []


class ModemCall:
    """The GRiD's internal modem (on its UART) and the Pi's USB modem (on PiPort), and the call between them through
    the HT802 and Asterisk: `number` reaches the Pi's modem, anything else is BUSY."""
    LINE_BAUD = 2400

    def __init__(s, uart, pi, number='300', ring_us=1.5e6, train_us=2.5e6):
        s.uart, s.pi, s.number = uart, pi, number
        s.g = Hayes('grid'); s.p = Hayes('pi')
        s.ring_us, s.train_us = ring_us, train_us
        s.t_connect = None; s.t_hangup = None
        s.calls = 0; s.hangups = 0; s.dialed = []
        uart.peer = s
        pi.on_write = s.from_pi; pi.on_dtr = s.pi_dtr
        pi.cd = False
        s.p_tx = 0.0                                      # the line's own pacing, Pi -> GRiD
        s.g_tx = 0.0                                      #  and GRiD -> Pi

    def now(s): return s.uart.clock()

    def online(s, t=None):
        t = s.now() if t is None else t
        return s.t_connect is not None and t >= s.t_connect and (s.t_hangup is None or t < s.t_hangup)

    # the GRiD's end
    def msr(s):
        return 0x30 | (0x80 if s.online() else 0)       # DSR, CTS; DCD with the carrier

    def from_grid(s, b, t):
        if s.online(t):
            t = max(t, s.g_tx) + ctime(s.LINE_BAUD); s.g_tx = t
            s.pi.arrive(b, t)
            return
        s._cmd_char(s.g, b, t, lambda d, at: s.uart.to_grid(d, at))

    def grid_dtr(s, up):
        if not up and s.online():
            s._hangup()

    # the Pi's end
    def from_pi(s, data):
        t0 = s.now()
        if s.online(t0):
            for b in data:
                t = max(t0, s.p_tx) + ctime(s.LINE_BAUD); s.p_tx = t
                s.uart.to_grid(bytes([b]), t - ctime(s.uart.baud()))
            return
        for b in data:
            s._cmd_char(s.p, b, t0, lambda d, at: [s.pi.arrive(x, at) for x in d])

    def pi_dtr(s, up):
        if not up and s.online():
            s._hangup()

    def _hangup(s):
        t = s.now()
        s.t_hangup = t; s.hangups += 1
        s.pi.cd = False
        for x in b'\r\nNO CARRIER\r\n': s.pi.arrive(x, t)

    # Hayes commands
    def _cmd_char(s, h, b, t, out):
        if h.echo: out(bytes([b]), t)
        if b != 13:
            h.line += bytes([b]); return
        line, h.line = h.line.strip().upper(), b''
        if not line.startswith(b'AT'): return
        h.cmds.append(line.decode('latin1'))
        a = line[2:]
        if a.startswith(b'DT') or a.startswith(b'DP') or a.startswith(b'D'):
            num = a[2:] if a[1:2] in (b'T', b'P') else a[1:]
            s.dialed.append(num.decode('latin1'))
            if h is s.g and num.decode('latin1') == s.number and s.p.s0:
                s.calls += 1
                t_ring = t + s.ring_us
                for x in b'\r\nRING\r\n': s.pi.arrive(x, t_ring)
                tc = t_ring + s.train_us
                s.t_connect = tc; s.t_hangup = None; s.g_tx = s.p_tx = tc
                s.pi.cd = True                              # (from tc: ModemLink reads CONNECT first)
                for x in b'\r\nCONNECT 2400\r\n': s.pi.arrive(x, tc)
                s.uart.to_grid(b'\r\nCONNECT 2400\r\n', tc)
            else:
                out(b'\r\nBUSY\r\n', t + s.ring_us)
            return
        for part in (a.replace(b'&', b' &').split() or [b'']):
            if part.startswith(b'E0'): h.echo = False
            if part.startswith(b'E1'): h.echo = True
            if b'S0=' in part:
                try: h.s0 = int(part.split(b'S0=')[1][:3] or b'0')
                except ValueError: pass
            if part.startswith(b'Z'): h.echo = True
        out(b'\r\nOK\r\n', t + 20000)
