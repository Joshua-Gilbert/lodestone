"""GLP 1 - GRiD Link Protocol: frames, CRC, AR488 escaping, message codec.

See PROTOCOL.md.  Shared by the Pi service and the test models.
"""
import binascii, itertools, struct

SYNC = 0x47
MORE = 0x80
VERSION = 1

# GRiD -> Pi
G_HELLO, G_POLL, G_PROMPT, G_EVENT, G_REPLY, G_NAK, G_KEYS = 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07
# Pi -> GRiD
P_HELLO, P_NOP, P_TEXT, P_STATUS, P_REQUEST, P_ASK, P_READY, P_NAK, P_TITLE, P_CLEAR, P_CELLS = range(0x41, 0x4C)

EV_INTERRUPT, EV_ANSWER, EV_REPAINT, EV_AWAY = 0x01, 0x02, 0x03, 0x04
EV_CLICK = 0x05            # Term: a left click on a cell: column, row (bytes; CLAUDE /W of PR #32)
EV_PIXCLICK = 0x06         # Term: a left click at a pixel: x, y (words; CLAUDE 1.2)

# HELLO flags
GF_TERM = 0x01             # GRiD: this CLAUDE can be a terminal (Term)
GF_PIX = 0x02              # GRiD: its CELLS take pictures (op FDh, picture.py); CLAUDE 1.2
GF_FCS = 0x04              # GRiD: it can check frames with the Fletcher sum (fletcher16); CLAUDE 1.3
GF_WAKE = 0x08             # GRiD: an SRQ while it is idle makes it POLL at once (Link.ring_check); CLAUDE 1.3
HF_TERM = 0x01             # Pi: Term: the GRiD is Claude Code's screen and keyboard
HF_FCS = 0x04              # Pi: frames after this HELLO carry the Fletcher sum, both ways

# REQUEST ops
OP_INFO, OP_DIR, OP_READ, OP_WRITE, OP_DELETE, OP_RENAME, OP_MKDIR, OP_RMDIR, OP_STAT, OP_FREE = range(1, 11)
OP_RUN, OP_SCREEN = 0x10, 0x11
OP_TYPE = 0x12                  # resident Claude's console: keys into the paused program
OP_GPIB = 0x20
OP_SETTIME = 0x30

GP_WRITE, GP_READ, GP_QUERY, GP_SPOLL, GP_CLEAR, GP_TRIGGER, GP_LOCAL, GP_REMOTE, GP_SCAN = range(1, 10)

NAMES = {G_HELLO: 'HELLO', G_POLL: 'POLL', G_PROMPT: 'PROMPT', G_EVENT: 'EVENT', G_REPLY: 'REPLY',
         G_NAK: 'NAK', G_KEYS: 'KEYS', P_CELLS: 'CELLS', P_HELLO: 'HELLO', P_NOP: 'NOP', P_TEXT: 'TEXT', P_STATUS: 'STATUS',
         P_REQUEST: 'REQUEST', P_ASK: 'ASK', P_READY: 'READY', P_NAK: 'NAK', P_TITLE: 'TITLE',
         P_CLEAR: 'CLEAR'}

# status byte of the Nano
ST_RQS, ST_READY, ST_WAITMASK = 0x40, 0x20, 0x1F

STOCK_FRAME_MAX = 127      # AR488 PBSIZE 128, minus one so the LF ends the line
PATCHED_FRAME_MAX = 254    # patched PBSIZE 255
HEADER = 6
GRID_RX_DEFAULT = 246      # Pi -> GRiD payload a CLAUDE without rx= in its HELLO reads (255-byte buffer)
GRID_RX_MAX = 8192
GRID_REQ_DEFAULT = 4700     # the biggest REQUEST a CLAUDE without HELLO's req= takes (its REQMAX)
OVERHEAD = 8               # header + CRC

# TEXT control codes
T_NL, T_INV_ON, T_INV_OFF, T_UL_ON, T_UL_OFF = 0x0A, 0x0E, 0x0F, 0x10, 0x11
# extra glyphs
GL_BULLET, GL_CORNER, GL_ELLIPSIS, GL_ARROW, GL_CHECK, GL_CROSS, GL_MIDDOT = range(0x80, 0x87)
GL_SPIN = list(range(0x87, 0x8D))
GL_RULE, GL_BAR, GL_TRI = 0x8D, 0x8E, 0x8F
GL_BL, GL_BR, GL_TL, GL_TR, GL_TEE_R, GL_TEE_L, GL_TEE_D, GL_TEE_U, GL_CROSSING = range(0x98, 0xA1)
GL_LAST = 0xA0


def _make_table():
    t = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) if c & 0x8000 else (c << 1)
        t.append(c & 0xFFFF)
    return t

_CRC = _make_table()

def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE: binascii's C crc_hqx (the table loop below cost ~0.3 ms a 2 KB frame)."""
    return binascii.crc_hqx(data, crc)


def crc16_table(data, crc=0xFFFF):
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC[(crc >> 8) ^ b]
    return crc


def fletcher16(data):
    """The GRiD's cheaper frame check (TERMLINK.INC fl16): A = 1 + the bytes,
    B = the sum of the A's, both mod 256; B << 8 | A."""
    # B is the sum of the running A's: accumulate() makes them in C, twice the speed of a Python loop
    return ((sum(itertools.accumulate(data, initial=1)) - 1) & 0xFF) << 8 | (1 + sum(data)) & 0xFF


def encode(kind, seq, ack, payload=b'', fl=False):
    body = struct.pack('<BBBH', kind & 0xFF, seq & 0xFF, ack & 0xFF, len(payload)) + bytes(payload)
    return bytes([SYNC]) + body + struct.pack('<H', fletcher16(body) if fl else crc16(body))


class Frame:
    __slots__ = ('kind', 'seq', 'ack', 'payload', 'fl')
    def __init__(s, kind, seq, ack, payload, fl=False):
        s.kind, s.seq, s.ack, s.payload, s.fl = kind, seq, ack, payload, fl
    @property
    def type(s): return s.kind & 0x7F
    @property
    def more(s): return bool(s.kind & MORE)
    def __repr__(s):
        return '<%s%s seq=%d ack=%d len=%d>' % (NAMES.get(s.type, '%02X' % s.type), '+' if s.more else '',
                                                s.seq, s.ack, len(s.payload))


def decode(buf, max_len=4096, fl_first=False):
    """Find the first complete frame with a good check (CRC-16, or the
    Fletcher sum when HELLO agreed to it: Frame.fl) at any sync position;
    fl_first tries the Fletcher sum first (one check fewer a frame).
    Returns (frame, end) or (None, keep) where keep is the index of the first
    sync byte (bytes before it are garbage)."""
    buf = bytes(buf)
    first = buf.find(bytes([SYNC]))
    if first < 0: return None, len(buf)
    i = first
    while i >= 0:
        if len(buf) - i >= OVERHEAD:
            kind, seq, ack, n = struct.unpack_from('<BBBH', buf, i + 1)
            end = i + OVERHEAD + n
            if n <= max_len and end <= len(buf):
                (crc,) = struct.unpack_from('<H', buf, i + HEADER + n)
                body = buf[i + 1:i + HEADER + n]
                for fl in ((True, False) if fl_first else (False, True)):   # (the Fletcher sum once HELLO
                    if (fletcher16(body) if fl else crc16(body)) == crc:    #  has agreed to it)
                        return Frame(kind, seq, ack, buf[i + HEADER:i + HEADER + n], fl=fl), end
        i = buf.find(bytes([SYNC]), i + 1)
    return None, first


class StreamParser:
    """Accumulates bytes from the serial side and yields frames.  Garbage
    before a good frame is dropped.  When the line goes quiet with bytes
    still pending, call idle(): they can never become a frame, so the
    caller should NAK."""
    def __init__(s, max_len=4096): s.buf = bytearray(); s.max_len = max_len; s.fl = False
    def pending(s): return len(s.buf)
    def idle(s):
        had = bool(s.buf)
        s.buf.clear()
        return had
    def feed(s, data):
        s.buf += data
        out = []
        while s.buf:
            f, used = decode(s.buf, s.max_len, s.fl)
            del s.buf[:used]
            if f is None: break
            s.fl = f.fl                                  # the next frame most likely has the same check
            out.append(f)
        return out


# ---- AR488 serial escaping (Pi -> Nano) --------------------------------
SPECIAL = {0x0D, 0x0A, 0x1B, 0x2B}

def escape(data):
    out = bytearray()
    for b in data:
        if b in SPECIAL: out.append(0x1B)
        out.append(b)
    return bytes(out)

def line_time_ms(nbytes, baud):
    return nbytes * 10 * 1000.0 / baud


# ---- messages ------------------------------------------------------------
def fragments(mtype, body, maxpay):
    """Split a message body into (kind, payload) frames of at most maxpay."""
    body = bytes(body)
    if not body: return [(mtype, b'')]
    out = []
    for i in range(0, len(body), maxpay):
        last = i + maxpay >= len(body)
        out.append((mtype | (0 if last else MORE), body[i:i + maxpay]))
    return out


class Reassembler:
    def __init__(s): s.parts = {}
    def add(s, frame):
        """Returns (type, body) when a message is complete, else None."""
        t = frame.type
        s.parts.setdefault(t, []).append(frame.payload)
        if frame.more: return None
        return t, b''.join(s.parts.pop(t))


def asciiz(s):
    if isinstance(s, str): s = s.encode('cp437', 'replace')
    return bytes(s) + b'\0'

def split_z(data, n=1):
    parts = bytes(data).split(b'\0', n)
    return parts

def kv_lines(data):
    d = {}
    for line in bytes(data).decode('cp437', 'replace').splitlines():
        if '=' in line:
            k, v = line.split('=', 1); d[k.strip()] = v.strip()
    return d


def hello_req(body):
    """The biggest REQUEST a GRiD HELLO says it takes (a `req=` line, CLAUDE 1.5 on), else the 4,700 of
    every CLAUDE before."""
    for line in bytes(body[6:]).split(b'\n'):
        if line.startswith(b'req='):
            try: return max(GRID_REQ_DEFAULT, min(int(line[4:]), 65000))
            except ValueError: break
    return GRID_REQ_DEFAULT


def hello_rx(body):
    """The Pi -> GRiD payload limit a GRiD HELLO announces (an `rx=` line), else
    the 246 every CLAUDE before 1.3 reads."""
    for line in bytes(body[6:]).split(b'\n'):
        if line.startswith(b'rx='):
            try: n = int(line[3:])
            except ValueError: break
            return max(GRID_RX_DEFAULT, min(n, GRID_RX_MAX))
    return GRID_RX_DEFAULT
