"""GLP 1 - GRiD Link Protocol: frames, CRC, AR488 escaping, message codec.

See PROTOCOL.md.  Shared by the Pi service and the test models.
"""
import struct

SYNC = 0x47
MORE = 0x80
VERSION = 1

# GRiD -> Pi
G_HELLO, G_POLL, G_PROMPT, G_EVENT, G_REPLY, G_NAK, G_KEYS = 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07
# Pi -> GRiD
P_HELLO, P_NOP, P_TEXT, P_STATUS, P_REQUEST, P_ASK, P_READY, P_NAK, P_TITLE, P_CLEAR, P_CELLS = range(0x41, 0x4C)

EV_INTERRUPT, EV_ANSWER, EV_REPAINT, EV_AWAY = 0x01, 0x02, 0x03, 0x04
EV_CLICK = 0x05            # Term: a left click on a cell (column, row); CLAUDE /W

# HELLO flags
GF_TERM = 0x01             # GRiD: this CLAUDE can be a terminal (Term)
HF_TERM = 0x01             # Pi: Term: the GRiD is Claude Code's screen and keyboard

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
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC[(crc >> 8) ^ b]
    return crc


def encode(kind, seq, ack, payload=b''):
    body = struct.pack('<BBBH', kind & 0xFF, seq & 0xFF, ack & 0xFF, len(payload)) + bytes(payload)
    return bytes([SYNC]) + body + struct.pack('<H', crc16(body))


class Frame:
    __slots__ = ('kind', 'seq', 'ack', 'payload')
    def __init__(s, kind, seq, ack, payload):
        s.kind, s.seq, s.ack, s.payload = kind, seq, ack, payload
    @property
    def type(s): return s.kind & 0x7F
    @property
    def more(s): return bool(s.kind & MORE)
    def __repr__(s):
        return '<%s%s seq=%d ack=%d len=%d>' % (NAMES.get(s.type, '%02X' % s.type), '+' if s.more else '',
                                                s.seq, s.ack, len(s.payload))


def decode(buf, max_len=4096):
    """Find the first complete frame with a good CRC at any sync position.
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
                if crc16(buf[i + 1:i + HEADER + n]) == crc:
                    return Frame(kind, seq, ack, buf[i + HEADER:i + HEADER + n]), end
        i = buf.find(bytes([SYNC]), i + 1)
    return None, first


class StreamParser:
    """Accumulates bytes from the serial side and yields frames.  Garbage
    before a good frame is dropped.  When the line goes quiet with bytes
    still pending, call idle(): they can never become a frame, so the
    caller should NAK."""
    def __init__(s, max_len=4096): s.buf = bytearray(); s.max_len = max_len
    def pending(s): return len(s.buf)
    def idle(s):
        had = bool(s.buf)
        s.buf.clear()
        return had
    def feed(s, data):
        s.buf += data
        out = []
        while s.buf:
            f, used = decode(s.buf, s.max_len)
            del s.buf[:used]
            if f is None: break
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
