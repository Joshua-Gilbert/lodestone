# Pi ↔ Pico protocol (bridge firmware, protocol version 1)

The Pico is a USB CDC serial port (`/dev/ttyACM0`, or `/dev/gpib-bridge` with the udev rule). The baud rate
is ignored. Every frame is **COBS-encoded and ends with one 0x00 byte**, so either side can resynchronise
at the next 0x00. A decoded frame is one type byte and its fields, little-endian. The
reference code is `host_link.c` (Pico) and `pi/gpibbridge/protocol.py` (Pi).

## Pi → Pico

| Type | Name | Fields | What it does |
|---|---|---|---|
| 0x01 | HELLO_REQ | — | The Pico answers HELLO |
| 0x02 | CONFIG | u8 address (0–30), u8 flags (bit 0 online, bit 1 auto service request) | Online: take part in the bus at this address. Offline: release everything. Auto service request: see below |
| 0x03 | TX | u16 gen, u8 flags (bit 0 = EOI on the last byte; bit 1 = EARLY, bit 2 = ANNOUNCED: fw 2026-10-23a; bit 3 = HELD: fw 2026-10-23c, below), data | Reply bytes for the 1520's next read. Dropped if `gen` isn't the current one (HELD: the next one) |
| 0x04 | STB | u8 status byte, u8 rsv | Serial-poll status byte. rsv = 1 asserts SRQ until the 1520 polls |
| 0x05 | PING | — | Every second. No PING for 5 s: the Pico goes offline |
| 0x07 | BOOTSEL | — | Reboot into the USB bootloader (to flash firmware) |
| 0x08 | WAKE | u16 gen | Auto service request mode: assert SRQ (status 40h, no READY) for an idle 1520 until it polls or sends a message; void if the 1520 has sent a newer message than `gen` (fw 2026-10-22b) |
| 0x09 | HOLD | u16 gen, 1–16 bytes | Auto service request mode: the 1520's message of generation `gen` is expected to be exactly these bytes, and the HELD TX frames that follow are the answer to it (fw 2026-10-23c, below) |
| 0x0A | HOLD_GLP | u16 gen, 4 bytes | The same, for a message that is one GLP frame starting with these 4 bytes (sync, type, seq, ack), its length field right (payload up to 8 KB) and its Fletcher sum good (fw 2026-10-23d, below) |

## Pico → Pi

| Type | Name | Fields |
|---|---|---|
| 0x81 | HELLO | u8 protocol version, u16 tx ring size, u16 data chunk (240), u32 tx consumed, u16 tx entries queued, firmware tag |
| 0x82 | DATA | u16 gen, u8 flags (bit 0 = EOI on the last byte: message ends; bit 1 = message ended without EOI; bit 2 = with bit 0, the message was the HOLD's: its held answer answers it, fw 2026-10-23c), data |
| 0x83 | EVENT | u8 code, u16 gen, u8 b, u32 arg, and (fw 2026-10-23b) u32 t: when it happened, on the Pico's microsecond timer |
| 0x84 | LOG | text |
| 0x85 | PONG | u8 online, address, listener, talker, ren, llo, spms, rsv; u16 gen; u32 tx consumed, commands, bytes in, bytes out, polls, events lost, NRFD holds, uptime ms, engine alive |
| 0x87 | CREDIT | u32 tx entries consumed so far |

**Event codes:** 0x10 LISTEN, 0x11 UNLISTEN, 0x12 TALK, 0x13 UNTALK, 0x14 TALK_WAIT (arg = tx consumed),
0x15 DCL, 0x16 SDC, 0x17 GET, 0x18 GTL, 0x19 LLO, 0x1A IFC, 0x1B REN (arg 1 = asserted), 0x1C SPOLL
(b = byte sent), 0x1D TX_DONE, 0x1E ONLINE (b = address), 0x1F OFFLINE.  From fw 2026-10-23b, for
`gridlink.bench --trace`: 0x20 RX_END (the last byte of a message from the 1520, with EOI, came; from fw
2026-10-23c b = 1 when the held answer answers it), 0x21 TX_IN
(a reply is queued: READY from now), 0x22 SRQ (asserted).  A Pi that reads only the first 9 bytes of an EVENT
sees nothing new.

## Generations: how a reply is matched to its question

- The Pico counts a **generation** (`gen`). It goes up at the first byte of every new message from the 1520,
  at every DCL or SDC, and when the Pi brings it online.
- Every DATA and EVENT frame carries the current gen. The Pi tags each reply with the gen of the message it
  answers.
- The Pico drops any reply whose gen is no longer current. A reply that arrives late (after the 1520 has
  sent something new or cleared the device) can therefore never answer the wrong question.

## Flow control

- **1520 → Pi.** If the Pi falls behind, the Pico's receive ring fills and the Pico holds NRFD, which is
  ordinary GPIB flow control. The 1520 waits; nothing is lost. PONG counts these holds.
- **Pi → 1520.** The Pi may have at most *tx ring size* reply bytes outstanding: sent but not yet consumed
  (sent to the 1520, or dropped as stale). CREDIT frames report consumption. HELLO tells a new session
  where the count stands.

## Talking with nothing queued

When the 1520 addresses the bridge to talk and the ring holds nothing for the current gen, the Pico sends
TALK_WAIT once and waits, without driving the bus. The arg is the consumed count at that moment.

- If the Pi has already sent reply bytes the Pico hasn't consumed, they are on their way, and the Pi ignores
  the TALK_WAIT.
- Otherwise it asks the handler (`on_talk`).

After a reply's EOI byte, the Pico doesn't ask again until it is next addressed to talk.

## Auto service request (CONFIG flags bit 1): gridlink's GLP mode

For CLAUDE.COM's link (GLP, `lodestone/claude-link`), the bridge requests service by itself, as the AR488
+GRiD1 patch does:

- **It raises SRQ when a whole answer is in.** Status 60h (RQS + READY) appears once, when a TX with EOI on
  its last byte has been queued for the current gen. The serial poll serves the RQS.
- **It keeps READY (20h) until the answer has been read**, then reports 00h.
- **A stale answer is dropped, and its SRQ and READY with it.** That happens after an SDC, or when the GRiD
  has started a new message.
- **The Pi sends each answer as one TX.** It needs credit for the whole frame first. (An answer bigger than
  the 600-byte input buffer goes as several TX frames, EOI only on the last.)
- **EARLY (fw 2026-10-23a): the answer is ready at its first TX frame.** A TX with flags bit 1 (EARLY) and no
  EOI begins an answer and counts it as queued at once: SRQ and 60h come then, and the 1520 reads while the
  rest crosses USB (~3.5 times faster than the 1520 reads; if the bridge runs dry it waits, as for any answer
  not yet there). The answer's last TX has EOI and bit 2 (ANNOUNCED), so it isn't counted again. An announced
  answer that won't be finished (stale before its end, another EARLY or a new generation from the Pi, a new
  session, the port closed) is closed by the bridge itself, and its READY goes. gridlink uses EARLY with
  firmware from 2026-10-23 on: a 128-byte first frame, then 512s.
- **HOLD (fw 2026-10-23c): an answer held for the next message.** While a message goes to the 1520 in
  fragments, its next frame is all but certain: a POLL for the next fragment. So with its answer the Pi sends
  HOLD for the next generation (current + 1) with that POLL's bytes, then the answer to it as TX frames with
  bit 3 (HELD) and that generation, EOI on the last. They wait behind the current answer, which goes first.
  The bridge compares the 1520's next message with the HOLD as it arrives. If it is exactly that, the held
  answer is ready at the message's last byte: SRQ and 60h at once, with no trip to the Pi and back. DATA bit
  2 tells the Pi, which then doesn't answer. If it is anything else (another message, shorter, longer,
  ended without EOI, a clear first), the held answer is dropped and the Pi answers as usual (DATA without
  bit 2). A HOLD is taken by the first message after it arrives and only if that message is its generation:
  one that comes too late is void. Held answers never count in READY until they match, so EARLY and ANNOUNCED
  don't apply to them. gridlink holds with firmware from 2026-10-23c on.
- **HOLD_GLP (fw 2026-10-23d): held for a frame the bridge checks.** Out of the 1520 the next frame is the
  next fragment of the same message: its first 4 bytes are known, its payload isn't, and the Pi's answer (a
  NOP) doesn't depend on it. With HOLD_GLP the bridge takes the message if it is one GLP frame with those 4
  bytes, as long as its length field says (8 + length bytes, EOI on the last) and with a good Fletcher sum
  over all but the sync byte (A = 1 + the bytes, B = the sum of the A's, both mod 256, stored A then B):
  the check the Pi itself makes, on the same bytes. A frame checked with the CRC isn't taken.
- **The STB frame's bits 5 and 6 are ignored in this mode.**
