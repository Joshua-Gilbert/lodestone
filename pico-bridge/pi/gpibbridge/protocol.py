"""The USB protocol between the Pi and the GPIB-Pico2 bridge firmware (firmware/bridge/PROTOCOL.md).

Every frame is COBS-encoded and ends with a 0x00 byte.  Decoded, a frame is one type byte and its fields,
little-endian.  These constants mirror firmware/bridge/host_link.h and gpib_engine.h.

claude-link's gridlink/pico.py speaks the same protocol (gridlink's own transport).  This copy stays here, kept
in step with that one by hand, so gpib-bridge installs on its own (/opt/gpib-bridge, gpibctl's PYTHONPATH):
the constants, the encoder and the port finder are the same as pico.py's.
"""
import struct

PROTO_VERSION = 1
PICO_VID = 0x2E8A

# Pi -> Pico
F_HELLO_REQ = 0x01
F_CONFIG = 0x02      # u8 address 0..30, u8 flags (CF_*): the daemon sets CF_ONLINE alone (it drives STB itself)
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

CF_ONLINE = 0x01     # (CF_AUTO_RSV 0x02 and CF_QUIET 0x04 are gridlink's: the bridge raises SRQ itself)
DF_EOI = 0x01
DF_END = 0x02
TXF_EOI = 0x01
DATA_CHUNK = 240     # data bytes per DATA frame from the Pico
TX_CHUNK = 512       # per TX frame to it: 4 + 512 + COBS's 3 fit the firmware's 600-byte input buffer

EVENTS = {
    0x10: "LISTEN", 0x11: "UNLISTEN", 0x12: "TALK", 0x13: "UNTALK", 0x14: "TALK_WAIT",
    0x15: "DCL", 0x16: "SDC", 0x17: "GET", 0x18: "GTL", 0x19: "LLO", 0x1A: "IFC",
    0x1B: "REN", 0x1C: "SPOLL", 0x1D: "TX_DONE", 0x1E: "ONLINE", 0x1F: "OFFLINE",
    0x20: "RX_END", 0x21: "TX_IN", 0x22: "SRQ",      # (fw 2026-10-23b: for gridlink's trace)
}

PONG_FIELDS = ("online", "address", "listener", "talker", "ren", "llo", "spms", "rsv", "gen",
               "tx_consumed", "commands", "bytes_in", "bytes_out", "polls", "events_lost", "rx_holds",
               "pico_uptime_ms", "engine_alive")
PONG_FMT = "<8BH9I"


def cobs_encode(data: bytes) -> bytes:
    """COBS, and the 0x00 that ends the frame: each run between zeros as its length + 1 and the run (254 bytes
    at most: then FFh, and the run goes on).  By runs, not bytes: ~20 times faster in Python (pico.py's)."""
    out = bytearray()
    for run in bytes(data).split(b"\0"):
        while len(run) >= 254:
            out.append(255)
            out += run[:254]
            run = run[254:]
        out.append(len(run) + 1)
        out += run
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
        self.skip = False                      # an overlong frame's rest: dropped up to its 0x00

    def feed(self, data: bytes):
        frames = []
        runs = bytes(data).split(b"\0")          # (by runs, not bytes: each but the last ended by a 0x00)
        for i, run in enumerate(runs):
            if self.skip:
                if i == len(runs) - 1:
                    break
                self.skip = False
                continue
            self.buf += run
            if len(self.buf) > 4096:            # no frame is this long: resynchronise at the next 0x00
                self.buf.clear()
                self.bad += 1
                self.skip = i == len(runs) - 1
                continue
            if i == len(runs) - 1:
                break
            if self.buf:
                try:
                    frames.append(cobs_decode(bytes(self.buf)))
                except ValueError:
                    self.bad += 1
                self.buf.clear()
        return frames


# ---- frame builders ----------------------------------------------------------------------------------------------
def hello_req():
    return cobs_encode(bytes([F_HELLO_REQ]))


def config(address: int, online: bool):
    """CONFIG's flags byte: CF_ONLINE or 0 (no auto service request, no quiet: the daemon drives STB)."""
    return cobs_encode(bytes([F_CONFIG, address, CF_ONLINE if online else 0]))


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
