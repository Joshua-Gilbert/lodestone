"""The USB protocol between the Pi and the GPIB-Pico2 bridge firmware (firmware/bridge/PROTOCOL.md).

Every frame is COBS-encoded and ends with a 0x00 byte.  Decoded, a frame is one type byte and its fields,
little-endian.  These constants mirror firmware/bridge/host_link.h and gpib_engine.h.
"""
import struct

PROTO_VERSION = 1

# Pi -> Pico
F_HELLO_REQ = 0x01
F_CONFIG = 0x02      # u8 address 0..30, u8 online
F_TX = 0x03          # u16 gen, u8 flags (bit 0 EOI on the last byte), data
F_STB = 0x04         # u8 status byte, u8 rsv
F_PING = 0x05
F_BOOTSEL = 0x07
# Pico -> Pi
F_HELLO = 0x81       # u8 proto, u16 tx ring size, u16 data chunk, u32 tx consumed, u16 tx queued, text fw tag
F_DATA = 0x82        # u16 gen, u8 flags (DF_EOI, DF_END), data
F_EVENT = 0x83       # u8 code, u16 gen, u8 b, u32 arg
F_LOG = 0x84
F_PONG = 0x85
F_CREDIT = 0x87      # u32 tx entries consumed

DF_EOI = 0x01
DF_END = 0x02
TXF_EOI = 0x01
DATA_CHUNK = 240

EVENTS = {
    0x10: "LISTEN", 0x11: "UNLISTEN", 0x12: "TALK", 0x13: "UNTALK", 0x14: "TALK_WAIT",
    0x15: "DCL", 0x16: "SDC", 0x17: "GET", 0x18: "GTL", 0x19: "LLO", 0x1A: "IFC",
    0x1B: "REN", 0x1C: "SPOLL", 0x1D: "TX_DONE", 0x1E: "ONLINE", 0x1F: "OFFLINE",
}

PONG_FIELDS = ("online", "address", "listener", "talker", "ren", "llo", "spms", "rsv", "gen",
               "tx_consumed", "commands", "bytes_in", "bytes_out", "polls", "events_lost", "rx_holds",
               "pico_uptime_ms", "engine_alive")
PONG_FMT = "<8BH9I"


def cobs_encode(data: bytes) -> bytes:
    out = bytearray([0])
    code_at, code = 0, 1
    for b in data:
        if b == 0:
            out[code_at] = code
            code_at, code = len(out), 1
            out.append(0)
        else:
            out.append(b)
            code += 1
            if code == 0xFF:
                out[code_at] = code
                code_at, code = len(out), 1
                out.append(0)
    out[code_at] = code
    out.append(0)
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        code = data[i]
        i += 1
        if code == 0 or i + code - 1 > n:
            raise ValueError("bad COBS frame")
        out += data[i:i + code - 1]
        i += code - 1
        if code != 0xFF and i < n:
            out.append(0)
    return bytes(out)


class Deframer:
    """Feed it serial bytes; it returns whole decoded frames."""

    def __init__(self):
        self.buf = bytearray()
        self.bad = 0

    def feed(self, data: bytes):
        frames = []
        for b in data:
            if b == 0:
                if self.buf:
                    try:
                        frames.append(cobs_decode(bytes(self.buf)))
                    except ValueError:
                        self.bad += 1
                self.buf.clear()
            else:
                self.buf.append(b)
                if len(self.buf) > 4096:     # no frame is this long: resynchronise at the next 0x00
                    self.buf.clear()
                    self.bad += 1
        return frames


# ---- frame builders ----------------------------------------------------------------------------------------------
def hello_req():
    return cobs_encode(bytes([F_HELLO_REQ]))


def config(address: int, online: bool):
    return cobs_encode(bytes([F_CONFIG, address, 1 if online else 0]))


def tx(gen: int, data: bytes, eoi: bool):
    return cobs_encode(struct.pack("<BHB", F_TX, gen & 0xFFFF, TXF_EOI if eoi else 0) + data)


def stb(status: int, rsv: bool):
    return cobs_encode(bytes([F_STB, status & 0xBF, 1 if rsv else 0]))


def ping():
    return cobs_encode(bytes([F_PING]))


def bootsel():
    return cobs_encode(bytes([F_BOOTSEL]))


# ---- frame parser ------------------------------------------------------------------------------------------------
def parse(frame: bytes):
    """Return (kind, dict)."""
    t = frame[0]
    if t == F_HELLO:
        proto, txring, chunk, consumed, queued = struct.unpack_from("<BHHIH", frame, 1)
        return "hello", {"proto": proto, "tx_ring": txring, "chunk": chunk, "consumed": consumed,
                         "queued": queued, "fw": frame[12:].decode("ascii", "replace")}
    if t == F_DATA:
        gen, flags = struct.unpack_from("<HB", frame, 1)
        return "data", {"gen": gen, "eoi": bool(flags & DF_EOI), "end": bool(flags & (DF_EOI | DF_END)),
                        "data": frame[4:]}
    if t == F_EVENT:
        code, gen, b, arg = struct.unpack_from("<BHBI", frame, 1)
        return "event", {"name": EVENTS.get(code, f"0x{code:02X}"), "gen": gen, "b": b, "arg": arg}
    if t == F_LOG:
        return "log", {"text": frame[1:].decode("ascii", "replace")}
    if t == F_PONG:
        vals = struct.unpack_from(PONG_FMT, frame, 1)
        return "pong", dict(zip(PONG_FIELDS, vals))
    if t == F_CREDIT:
        return "credit", {"consumed": struct.unpack_from("<I", frame, 1)[0]}
    return "unknown", {"type": t, "raw": frame}
