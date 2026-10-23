# GPIB-Pico2 bridge firmware (`bridge fw 2026-10-22b`)

This is the production firmware: the Pico is the 1520's GPIB device, and everything the 1520 sends to it
goes to the Raspberry Pi over USB.

- The bench sketch (`firmware/bench_test/`) stays as the board's test tool.
- This firmware replaces it once the board has passed TEST_PLAN stage 6b.
- The Pi side is in `pi/`. Setup is in `pi/README.md`.

| | |
|---|---|
| Files | `bridge.ino` (glue, pin init, USB, LED, watchdog) · `gpib_engine.c/.h` (core 1: the bus) · `host_link.c/.h` (core 0: the protocol) · `PROTOCOL.md` |
| Ready-built | `bridge_pico2.uf2` (157 kB, fw 2026-10-22b) |
| USB | VID 2E8A / PID 000F (the arduino-pico Pico 2 IDs), product **"GPIB-Pico2 Bridge"**, max power 500 mA in the descriptor |
| GPIB subsets | SH1 AH1 T6 L4 SR1 RL1 PP0 DC1 DT1 C0. No secondary addresses, no parallel poll, never a controller |
| Address | set by the Pi (0–30), from `address =` in `/etc/gpib-bridge/bridge.toml` |

## What it does on the bus

- **Until the Pi says CONFIG online, it takes no part in the bus at all.** NRFD, NDAC and SRQ are released
  and nothing is driven, like a powered-off instrument. The same applies:
  - whenever the Pi's port closes;
  - when PINGs stop for 5 s;
  - during IFC;
  - while it reboots, because R1–R6 hold the safe state.

  If core 0 ever hangs, the 2 s hardware watchdog resets the chip into that safe state.
- **Online**, it is an ordinary device at its address:
  - it takes part in every command handshake (ATN);
  - it listens when sent its MLA, and passes the message to the Pi;
  - it talks when sent its MTA, sending the Pi's reply with EOI on the last byte;
  - it answers serial polls with the Pi's status byte, and asserts SRQ when the Pi requests service;
  - it reports DCL, SDC, GET, GTL, LLO, REN and IFC to the Pi.
- **Messages end** at EOI, or when the 1520 unaddresses it mid-message (UNL, or its own MTA). A message
  half-received when IFC arrives or the bridge goes offline is thrown away.
- **Flow control:** if the Pi is behind, the bridge holds NRFD, which is plain GPIB flow control.
- **SRQ is edge-triggered.** Each service request from the Pi is asserted once. The 1520's serial poll
  serves it (RQS in the byte), and later traffic can't bring it back.

## The ATN response (the 200 ns rule)

Core 1 runs only `engine_run()`. Interrupts are off, and all of it is in SRAM: the build places
`spin`, `accept`, `apply_requests`, `bus_lines` and `engine_run` at 0x2000xxxx, and none of them calls
into flash. So nothing can delay it.

**Where ATN arrives:** in the idle wait, while the bridge is not addressed. Online, this is where it
spends nearly all its time, and the talker's wait for the Pi uses the same loop. That loop is hand-written
assembly (`spin()`):

- It samples GPIO_IN four times in a row: `ldr` / `tst #0x200` / `beq`, 3 instructions each.
- Then it spends 6 instructions checking IFC, REN and the request counter.
- On ATN: one taken branch, then `str` to SIO GPIO_CLR with the mask that asserts NDAC and drops TE_C, PE
  and TE_D.

**Worst-case estimate at the stock 150 MHz (6.7 ns/cycle).** The cycle counts are from the M33 pipeline,
not measured; check them with the scope test below.

| Step | Cycles | ns |
|---|---|---|
| ATN → Pico pin: U3 bus→terminal tPHL, max ([TI SN75161B](https://www.ti.com/lit/ds/symlink/sn75161b.pdf)) | — | 22 |
| 1 kΩ × pin capacitance | — | ~10 |
| Input synchroniser | 2 | 13 |
| Longest unsampled gap (the 6-instruction check) | ~11 | 73 |
| Taken branch + store | ~5 | 33 |
| NDAC pin → bus: U3 terminal→bus tPHL, max | — | 20 |
| **Total, worst case** | | **~170** |
| Typical (mid-loop sample, typ chip delays) | | ~90 |

- **While the bridge is part-way through a byte of its own reply,** the talk loops are compiled C (about
  10–13 instructions per pass). Allow ~200–230 ns worst case there, plus U3/U2 disable times. That only
  matters if the 1520 cuts a read short with ATN mid-byte.
- **If the scope shows too little margin,** build with `freq=200`. Note that arduino-pico lists 200 MHz as
  an overclock for the RP2350. **[U]**

**Check it on the bench before the live bus (TEST_PLAN stage 8):**
1. Put only the 1520 and the bridge on the cable, with the Pi daemon running.
2. Connect CH1 to ATN (J1 pad 11) and CH2 to NDAC (J1 pad 8). Trigger on ATN falling.
3. Run THRUTEST or any Lodestone command to another address.
4. Measure from ATN to the bridge's NDAC (the 1520 itself doesn't assert NDAC while it talks). It must be
   **≤ 200 ns**.

## Changes since 2026-10-16d

Measured on the 1520 with gridlink.bench (claude-link/gridlink/bench.py), 128 KB each way:

- **2026-10-21a.** T1 (data settling before DAV) timed on core 1's SysTick in CPU cycles: 1.1 us, the
  IEEE-488.1 figure for a three-state source. It was 2–3 us on the 1 us timer. A reply's bytes now go back
  to back instead of each one returning to the main loop.
- **2026-10-22a.** USB from the Pi is read with one `tud_cdc_read` per loop. `Serial.readBytes` read a byte
  at a time, and every byte took the USB mutex and ran `tud_task`. Pi → Pico went from 106 to 510 KB/s, and
  a 2 KB reply from 18.6 to 4.6 ms between gridlink's write and the 1520's read.
- **2026-10-22b.** WAKE (`0x08`, u16 generation; PROTOCOL.md). In auto service request mode the bridge
  raises SRQ (status 40h, no READY) for an idle 1520 until it serial-polls or sends a message. A WAKE for
  an older message than the 1520's last is ignored. gridlink uses it so news reaches an idle CLAUDE at
  once instead of at its once-a-second idle POLL: median 51 ms instead of up to a second.
- **2026-10-23a.** EARLY answers (TX flags bit 1, bit 2 on the last; PROTOCOL.md). A 2 KB answer counts as
  ready when its first TX frame is in, so the 1520 reads while the rest crosses USB, instead of after: the
  ~4 ms of USB per 2 KB frame overlaps the GPIB transfer. Every announced answer puts exactly one EOI entry in
  the ring (core 1 counts answers done by them): one that won't be finished gets a stand-in, an EOI entry of
  an older generation that core 1 drops as stale. The bus simulation's J tests cover a streamed read, an SDC
  in the middle and an answer never finished. On the 1520 (gridlink.bench --size 128): Pi → GRiD 73.6 →
  87.2 KB/s.
- **2026-10-23b.** Every event frame carries the time it happened (u32, the microsecond timer; core 1 stamps
  its records), and three new events say when the 1520's message ended (RX_END), a reply was queued (TX_IN)
  and SRQ went up (SRQ). gridlink's trace puts the bridge's events on its own clock with them: the Pico sends
  its events between USB reads, so a TALK used to reach the Pi ms after it happened.
- **2026-10-23c.** HOLD (`0x09`) and held answers (TX flags bit 3; PROTOCOL.md). The Pi gives the bridge the
  1520's next message, expected byte for byte (its POLL for the next fragment), and the answer to it. Core 1
  compares the message as it arrives (`got_data`, a few instructions a byte, between handshakes) and if it
  matches makes the held answer ready at its EOI byte: SRQ at once instead of after a trip to the Pi and back
  (~1.5 ms of each ~17 ms 2 KB frame into the GRiD). Held entries wait in the ring (a newer generation is no
  longer "stale", only an older one) and are dropped if the message doesn't match. They never count in
  `tx_eoi_pushed`: core 1 makes them ready itself (`hold_ok`, one RQS). The bus simulation's J tests cover a
  match, another message, a shorter and a longer one, a HOLD too late, an SDC after a match and 11 held 2 KB
  answers in a row.
- **2026-10-23d.** HOLD_GLP (`0x0A`). A hold for the 1520's next GLP frame by its first 4 bytes, its length and
  its Fletcher sum, so the Pi's NOP for the next fragment of a message out of the 1520 waits in the bridge too.
  Core 1 keeps the sum as the bytes come (two adds a byte, `hold_glp_byte`). The J tests add a good frame, an
  empty one, and a wrong sequence number, a bad sum, a changed byte, one too short, one too long and one with
  the CRC: 99 checks.

## Build

Use arduino-cli with the arduino-pico core (`rp2040:rp2040` 6.3.0 was used). Put the `.c/.h` files next to
the sketch. (With arduino-cli on Linux, `bridge.ino` may need to become `bridge_main.cpp` with
`#include <Arduino.h>` on top, next to a `bridge.ino` that is only a comment, when its ctags step fails.
If arduino-cli has no ctags at all, point it at a stand-in that prints nothing:
`--build-property 'runtime.tools.ctags.path=DIR'`, DIR holding an executable `ctags` that exits 0.)

```
arduino-cli compile -b rp2040:rp2040:rpipico2:opt=Optimize2,freq=150 \
  --build-property 'build.usb_product="GPIB-Pico2 Bridge"' \
  --build-property 'build.usb_manufacturer="GPIB-Pico2"' \
  --build-property 'build.usbpwr=-DUSBD_MAX_POWER_MA=500' \
  --output-dir out bridge
```

The product string matters: the Pi's udev rule finds the bridge by it. In the Arduino IDE, set CPU Speed
to 150 MHz and Optimize to -O2. The IDE build has the default product string "Pico 2". That still works,
because the daemon also finds any Pico, but `/dev/gpib-bridge` won't appear.

## Flash

Use either:
- **From the Pi, once it's set up:** `sudo gpibctl flash /opt/gpib-bridge/bridge_pico2.uf2`. It reboots
  the Pico into its bootloader over USB, copies the file and restarts the daemon.
- **From any PC:** hold BOOTSEL while plugging the Pico in, then copy `bridge_pico2.uf2` onto the RP2350
  drive.

To go back to the bench firmware, use BOOTSEL and `firmware/bench_test/bench_test_pico2.uf2`.

## LED

| LED | Meaning |
|---|---|
| Off | No Pi has the port open |
| Short blink every 2 s | Pi connected, bridge offline |
| Steady on | Online |
| Flicker | Bytes moving to or from the bridge |

## Tested (no hardware): `sim/host/run_sim_tests.py`, 65 / 65

`sim/host/bus_sim.c` compiles this same `gpib_engine.c` and `host_link.c` for Linux, with a model of the
board:

- the GPIO latches and output enables;
- U2/U3 direction rules, including EOI steered by ATN;
- R1–R6;
- wired-OR bus lines;
- a controller playing the 1520;
- a second instrument at address 5.

The real Pi daemon connects through a pseudo-terminal.

What it covers:

- THRUTEST's 9 steps, including every byte value both ways.
- Traffic to the other instrument: the bridge stays out of it.
- SRQ and serial poll, including SRQ staying served after later traffic.
- Messages of 241–20000 bytes.
- A message ended by UNL.
- The Pi stalled 2.5 s, and the Pico's USB output stalled 2.5 s: NRFD held, nothing lost.
- The daemon stalled past the 5 s PING timeout: it recovers by itself.
- Daemon stopped: the bridge goes offline and the bus still works.
- The scpi handler.
- Address changes.

The model checks logic, not nanoseconds, so the ATN timing is the scope test above. An independent
review (a fresh agent, 2026-10-16) found 13 issues, all fixed in 16c. Among them:

- SRQ came back after being served;
- a stalled daemon left the bridge offline;
- core 0 could drop frames when USB backed up;
- a TALK_WAIT race;
- the T1 settle time was 1–2 µs, not 2;
- IFC handling.
