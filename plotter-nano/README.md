# The 4662's Nano

`gpib_hpgl_tek4662/gpib_hpgl_tek4662.ino`: the firmware for the Arduino Nano
that puts the Tektronix 4662 pen plotter on the GPIB bus. It is a GPIB device
at address 1 (`GPIB_ADDRESS`) that takes HP-GL and sends it to the 4662 as
Tek commands on RS-232 at 1200 baud. gridlink's `grid_plotter` drives it
(`claude-link/README.md`, The pen plotter).

**Wiring** (AR488's Nano pin map): DIO1-4 D2-D5, DIO5-8 A0-A3, DAV D7,
NRFD D8, NDAC D9, ATN D10, IFC D11, SRQ D12, EOI A4, REN A5; the GPIB
cable's ground returns (pins 18-24) and shield (12) to GND. Plotter: D6 to
the MAX3232 breakout's TXD and its RXD to D13, then the AT925MF adapter to
the 4662's MODEM port. 4662 switches A=3, B=2, C=2, D=3 (Copy Mode,
1200 baud, address A). Power the Nano before the plotter; on the Pi's USB it
shares the bus's ground and its console is a `miniterm` away.

**v5:** no bell (GS and a move to the pen's own position, instead of GS BEL,
which rings it: p. 3-6); coordinates compressed to the bytes that changed
(Table 3-3, p. 3-10); status requests overlap the drawing, so the line stays
busy; and PU/PD/PA coordinates are read as they come, so a long point list
isn't cut at 255 characters (v1-v4 did).

**Flow control:**
- To the plotter: the 4662 has no XON/XOFF here, so the Nano asks it for the
  room in its input buffer (READ STATUS 1, `ESC A O 1 SUB`; the free bytes
  are bits 0-10 of the second value of the 7-character reply; 070-4164-00
  p. 3-13, 4-13, 4-14), counting the bytes still on the line since it
  answered, and asks again before the room runs out.
  A plotter that doesn't answer gets v3's timed pacing (tunable with `!`).
- From the bus: a serial poll answers bit 7 = idle, bits 0-5 = room in its
  buffer in 4-byte units. A controller that sends more is held off with
  NRFD.

**Console** (USB, 9600): HP-GL for testing; `?` the bus lines, counters and
flow state; `#` ask the plotter now; `!` the timed pacing.

**Flashing from the Pi:**
```
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 plotter-nano/gpib_hpgl_tek4662
arduino-cli upload -p /dev/ttyUSB0 --fqbn arduino:avr:nano:cpu=atmega328 plotter-nano/gpib_hpgl_tek4662
```
