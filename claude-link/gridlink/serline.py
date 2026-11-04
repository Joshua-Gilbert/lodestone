"""gridlink's transports for SERLINK.COM on the GRiD (tools/SERLINK.ASM): the link without the GPIB cartridge.

GLP frames go over the line as they are: they carry their length, so SERLINK finds where each ends, and the Link's
StreamParser does the same here.  Strict alternation as over GPIB: the GRiD writes a frame, we answer with one.

SerialLink   a null-modem cable from the GRiD's COM2 to a USB serial adapter (--bridge serial, 19200 baud by default:
             SERLINK /P:2's).
ModemLink    a USB modem the GRiD dials (--bridge modem): its internal 2400-baud modem on COM1, through the
             Grandstream HT802 and Asterisk (docs/serial-link.md).  The modem answers by itself (ATS0=1); when the
             carrier goes, it is set up again for the next call.

Each frame to the GRiD is kept to about a second on the line (frame_limit), so a 2400-baud link answers within
CLAUDE.COM's 2 s and the GRiD isn't held for long by one read.
"""
import time
from . import glp

FRAME_MAX = 3340 + glp.OVERHEAD                 # CLAUDE 1.6's RXPAY, as the Pico bridge's
FRAME_MIN = 128 + glp.OVERHEAD
RING = b'\x07'                                  # a byte SERLINK skips while it hunts for a frame: its arrival wakes
                                                #  CLAUDE.COM (SERLINK's 0Eh count, 0Bh latch) as an SRQ would


def frame_limit_for(baud, secs=1.0):
    """The biggest frame (header and check too) that takes about `secs` at `baud` (8N1: 10 bits a byte)."""
    return max(FRAME_MIN, min(FRAME_MAX, int(baud / 10 * secs)))


class SerialLink:
    """gridlink transport over a plain serial line: frame_limit, open(), configure(), answer(frame), read(), ring().
    `ser` may be given (the tests' model of the line); else the port is opened with pyserial."""
    patched = True
    can_ring = True

    def __init__(s, port='/dev/ttyUSB0', baud=19200, log=print, ser=None):
        s.port, s.baud, s.log, s.ser = port, baud, log, ser
        s.version = 'serial %d baud' % baud
        s.line_baud = baud
        s.online = True
        s.rung = False

    @property
    def frame_limit(s):
        return frame_limit_for(s.line_baud)

    def open(s):
        if s.ser is None:
            import serial
            s.ser = serial.Serial(s.port, s.baud, timeout=0.05, write_timeout=10)
            try: s.ser.dtr = True; s.ser.rts = True
            except Exception: pass
        s.ser.reset_input_buffer()

    def configure(s):
        s.log('serial line on %s at %d baud: frames up to %d bytes' % (s.port, s.baud, s.frame_limit))
        return s.version

    def save(s):
        pass

    def answer(s, frame):
        if s.online:
            s.rung = False
            s.ser.write(frame)

    def ring(s):
        """Wake an idle CLAUDE.COM (Link.ring_check): one byte it skips; once till our next answer."""
        if s.online and not s.rung:
            s.rung = True
            s.ser.write(RING)

    def read(s):
        d = s.ser.read(1)
        if d:
            n = s.ser.in_waiting
            if n: d += s.ser.read(n)
        return d


class ModemLink(SerialLink):
    """A USB modem the GRiD calls: set up to answer by itself; online from CONNECT till the carrier goes."""
    INIT = ('ATZ', 'ATE0V1Q0', 'AT&C1&D2', 'ATS0=1')

    def __init__(s, port='/dev/ttyACM0', baud=115200, log=print, ser=None, line_baud=2400):
        SerialLink.__init__(s, port, baud, log, ser)
        s.version = 'modem'
        s.line_baud = line_baud                 # till a CONNECT says
        s.online = False
        s.lbuf = b''
        s.calls = 0

    def configure(s):
        s.setup()
        s.log('modem on %s: waiting for the GRiD\'s call' % s.port)
        return s.version

    def _cmd(s, text, wait=2.0):
        """A command; -> its result line (OK, ERROR, or '' if none)."""
        s.ser.reset_input_buffer()
        s.ser.write(text.encode() + b'\r')
        t_end = time.monotonic() + wait; buf = b''
        while time.monotonic() < t_end:
            buf += s.ser.read(64)
            for line in buf.replace(b'\n', b'\r').split(b'\r'):
                line = line.strip()
                if line in (b'OK', b'ERROR'): return line.decode()
        return ''

    def setup(s):
        try: s.ser.dtr = True
        except Exception: pass
        for c in s.INIT:
            r = s._cmd(c)
            if c in ('ATZ', 'ATE0V1Q0') and r != 'OK':
                s.log('modem: no OK to %s (%r)' % (c, r))
        s.online = False; s.lbuf = b''

    def hangup(s):
        try:
            s.ser.dtr = False; time.sleep(1.0); s.ser.dtr = True
        except Exception:
            pass
        s.online = False

    def carrier(s):
        try: return bool(s.ser.cd)
        except Exception: return True              # (a port that can't say: NO CARRIER in the stream instead)

    def read(s):
        if s.online:
            if not s.carrier():
                s.log('modem: the call ended (carrier gone)'); s.hangup(); s.setup()
                return b''
            return SerialLink.read(s)
        d = s.ser.read(64)                          # the modem's own lines: RING, CONNECT ...
        if not d: return b''
        s.lbuf += d
        while True:
            s.lbuf = s.lbuf.lstrip(b'\r\n')
            i = min([k for k in (s.lbuf.find(b'\r'), s.lbuf.find(b'\n')) if k >= 0], default=-1)
            if i < 0: break
            line, s.lbuf = s.lbuf[:i].strip(), s.lbuf[i + 1:]
            if line.startswith(b'CONNECT'):
                parts = line.split()
                speed = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 2400
                s.line_baud = speed; s.online = True; s.calls += 1
                s.log('modem: the GRiD called: %s (frames up to %d bytes)' % (line.decode('latin1'), s.frame_limit))
                rest, s.lbuf = s.lbuf, b''
                return rest                         # (anything after CONNECT: the GRiD's first bytes)
            if line in (b'RING',):
                s.log('modem: ringing')
            elif line.startswith(b'NO CARRIER'):
                s.log('modem: no connection (%s)' % line.decode('latin1'))
        if len(s.lbuf) > 256: s.lbuf = s.lbuf[-64:]
        return b''
