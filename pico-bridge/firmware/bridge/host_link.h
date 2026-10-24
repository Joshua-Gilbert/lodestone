// host_link.h -- core 0's side: the framed USB protocol to the Raspberry Pi (see PROTOCOL.md).
// Shared by the Arduino sketch and the host simulation; the glue provides link_write_some() and link_bootsel().
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

// frame types, Pi -> Pico
#define F_HELLO_REQ 0x01
#define F_CONFIG    0x02   // u8 address 0..30, u8 flags: bit 0 online, bit 1 auto service request (GLP),
                           //  bit 2 quiet: the status byte as ever, the SRQ line never driven (2026-10-24)
#define F_TX        0x03   // u16 gen, u8 flags (bit 0: EOI with the last byte; bit 1 EARLY, bit 2 ANNOUNCED), data
#define TXF_EARLY   0x02   // (TX flags, 2026-10-23a) the first frame of a reply: count it ready now, the rest follows
#define TXF_ANN     0x04   //  the last frame (EOI) of a reply an EARLY frame announced: not counted again
#define TXF_HELD    0x08   // (2026-10-23c) part of a held reply for generation gen (the next message's): see F_HOLD
#define F_STB       0x04   // u8 status byte (bit 6 ignored), u8 rsv (1 = request service: SRQ)
#define F_PING      0x05
#define F_BOOTSEL   0x07   // reboot into the USB bootloader (to flash new firmware)
#define F_WAKE      0x08   // u16 gen: auto mode: request service (status 40h) for an idle 1520, until it sends a
                           // message newer than gen or is polled (gridlink rings when it has news; 2026-10-22b)
#define F_HOLD      0x09   // u16 gen, the bytes (1..16) the 1520's message of that generation is expected to be:
                           // the TXF_HELD reply that follows is its answer, sent only if it is (2026-10-23c)
#define F_HOLD_GLP  0x0A   // u16 gen, 4 bytes: the same, for a message that is a good GLP frame (Fletcher sum)
                           // starting with these 4 bytes, any length up to 8 KB (2026-10-23d)
// frame types, Pico -> Pi
#define F_HELLO     0x81   // u8 protocol version, u16 tx ring size, u16 data chunk max, u32 tx consumed,
                           //   u16 tx entries still queued, firmware tag text
#define F_DATA      0x82   // u16 gen, u8 flags (bit 0: EOI on the last byte = message end; bit 1: message ended
                           //   without EOI), data (may be empty when bit 1 is set)
#define F_EVENT     0x83   // u8 code, u16 gen, u8 b, u32 arg (codes: gpib_engine.h E_*)
#define F_LOG       0x84   // text
#define F_PONG      0x85   // status block, see host_link.c send_pong()
#define F_CREDIT    0x87   // u32 tx entries consumed so far (sent or dropped as stale)

#define DF_EOI 0x01
#define DF_END 0x02
#define DF_HELD 0x04       // (with DF_EOI) the message matched the hold: the held reply answers it (2026-10-23c)

#define LINK_PING_TIMEOUT_MS 5000u   // no PING for this long: go offline (release the bus)
#define DATA_CHUNK 240u

void link_init(void);
void link_input(const uint8_t *b, size_t n, uint32_t now_ms);
void link_poll(uint32_t now_ms, bool host_open);

// provided by the glue
size_t link_write_some(const uint8_t *b, size_t n);   // never blocks: returns how many it took (0 if none)
void link_bootsel(void);

#ifdef __cplusplus
}
#endif
