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
1200 baud, address A); switch A without its Copy bit for standard mode, which
uses the whole page (v7.5). Power the Nano before the plotter; on the Pi's USB it
shares the bus's ground and its console is a `miniterm` away.

**v7.6: labels, and the 4662's own commands.** HP-GL's label commands now
reach the plotter as its own alpha commands (070-4164-00 p. 4-16 to 4-23),
sent just before the label that needs them and only when they change:

| HP-GL | 4662 |
|---|---|
| `SI w,h` (cm), `SR w,h` (% of the page), `ES` | SET ALPHA DIMENSION `ESC A I cs,ls` |
| `DI run,rise`, `DR run,rise` | SET ALPHA ROTATION `ESC A J deg` |
| `CS n`, `CA n`, `SS`/`SA`, SO/SI in a label | SELECT ALPHA FONT `ESC A T n` |
| `IN`, `DF` | RESET ALPHA PARAMETERS `ESC A V` |

Sizes scale with the drawing (HP-GL's page is enlarged to the 4662's), so a
label keeps its place in a plot. The 4662's fonts (Figure 4-2) differ only in
a few characters: 1 Swedish/Finnish (CS3, CS30, CS31), 2 German (CS2, CS33),
3 UK (CS35), 4 Spanish (CS4, CS37), 9 Danish/Norwegian (CS32, CS39); 5, 6 and 8
are symbol variants, and other sets get font 0. `CS100`-`CS109` pick fonts 0-9
directly (not HP-GL). Firmware level 3 or older has different fonts 1-6
(Figure 4-3). CR and LF in a label now reach the plotter: a new line under the
label's start (the Nano sets the left margin there). If the 4662's rear-panel
"CR implies CR+LF" is set, CR LF gives two lines.

Any of the 4662's own commands (Appendix A) can be sent too: an ESC outside a
label starts one, and the Nano passes it to the plotter as it is.
- `ESC A <code> <numbers>` ends at `;` or SUB (both go as SUB), or at the first
  character that can't be part of its numbers, which is then HP-GL again; end
  them with `;` to be sure (an HP-GL `E..` mnemonic straight after a number
  would read as an exponent). `\x1bAJ30;` rotates labels 30 degrees, `\x1bAI112,176;`
  doubles their size, `\x1bABP2;` takes pen 2 and `\x1bABY100;` sets the pen
  speed (Option 31).
- Codes without arguments end with the code (`E F ( N Q V M K L`), those with
  one character after it (`U S R`); `ESC` and any other character (e.g. `ESC FF`,
  MOVE-TO-HOME) is a Style II escape.
- The 4662 goes back to the mode it was in after one (Figure 3-3), and the Nano
  re-enters graph mode at its own pen position before the next stroke, so
  HP-GL carries on where it was even after a command that moves the pen.
- Native `I`, `J`, `T`, `V` and `N` (DEVICE RESET) also set what the next labels
  use, as `SI`, `DI` and `CS` do.
- Replies the plotter sends (SIZE, DIGITIZE) aren't passed back to GPIB; the Nano
  reads only its own status replies. Commands that change the plotter's units
  or page (Option 31's `ESC A B V`, the front-panel page) change where HP-GL
  lands, and BLOCK START needs a host that sends blocks: the Nano doesn't.

gridlink's `grid_plotter` lets ESC, SUB, BS, SO and SI through for these.

**v7.5: the page.** Copy Mode addresses 0-4096 x 0-3124 ADUs and leaves
the right-most 13% of the page unreachable; standard mode addresses
0-4096 x 0-2731 over the whole 15 x 10 in page (070-4164-00 p. 1-3). The
4662 reports its COPY MODE switch in bit 14 of READ STATUS 1 (Table 4-3,
p. 4-14), the reply the Nano already reads for flow control, so the Nano maps
HP-GL onto whichever page the switch selects, at its probe and at each `IN`
(never in the middle of a plot). Outside Copy Mode the 4662 powers up
logically off and ignores everything but PLOTTER ON (p. 4-2), so the Nano
sends PLOTTER ON (`ESC A E`) before its probe and at every `IN`; in Copy Mode
it is already on and the command changes nothing. `!m 0` forces standard
mode, `!m 1` Copy Mode, `!m 2` (the default) follows the switch. v7.4 had
already mapped Copy Mode's full height (v1-v7.3 used standard mode's 2731
there: the top 13% of the page unused, plots 15% too wide). `tests/test_nano.cpp`
checks the switch bit, the mapping, `!m` and PLOTTER ON.

**v7.3:** `;` is optional, as in HP-GL: a letter after a mnemonic and its
arguments starts the next mnemonic. `PD100,200PU300,400` now lifts the pen for
300,400 (v5-v7.2 took the PU for separators and drew it), and `INPU100,200`
or `SP2PD100,200` no longer lose everything after the IN or SP up to the next
`;`. SM and DT keep the one character they take, and BL and WD, like LB, take
text up to ETX (the Nano ignores those four; it draws LB). A plot must still
end with `;` (or a label's ETX): like a plotter, the Nano draws the last point
only when the command ends, and grid_plotter adds a `;` if the HP-GL lacks
one. `tests/test_nano.cpp` checks it on the PC: the sketch compiled with g++
against stub Arduino headers, fed HP-GL (the command line is at its top).
And the serial-poll byte now settles on the bus for a `gpibService()` pass
before DAV; it used to get ~1.7 us, under IEEE-488.1's 2 us (T1).

**v7.2:** no bumps in long lines. After a status request, v5-v7 re-entered
graph mode with GS and a move to the pen's position, which lifted the pen in
the middle of a stroke every ~600 bytes. The 4662 goes back to the mode it was
in once a Style I command is processed (Figure 3-3, p. 3-5), so the stroke now
just carries on. `!g 1` puts the old re-entry back.

**Defaults (v7.1):** `!r`, `!a`, `!w` and `!b` are all off. The drag that v6
and v7 worked around turned out to be the pen adapter pressing the pen too
hard on the paper; with the adapter corrected, plots are clean without them.
They stay on the console for a pen that lifts slowly (`!r 22`, `!a 150`,
`!w 150`).

**v7:** labels. The 4662's own characters left a ~1 cm tail on the move
after a label and small marks at the spaces in one (TESTPAT5); v3, whose
timed pacing happened to leave the plotter idle after each label, had none.
So after a label (`!a`) and before a space in one (`!w`), the Nano can wait
until a status reply shows the 4662's buffer empty, then pauses 150 ms, before
sending more. `!b 1` adds a BS after a label (a short pen-up move back one
character space) as another cure to try; off by default.

**v6:** the pen leaves the paper about 1 mm into a pen-up move (Claude's
detour test on the GRiD), which bridged short gaps and put a tail on every
move. Before a move, the Nano can lift the pen with a pen-up move of 22 ADU
(about 2 mm) back along the stroke just drawn, so the drag lands on ink that
is already there. `!r n` on the console sets it (0 turns it off).

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
flow state; HP-GL and ESC commands typed on the console go to the plotter too; `#` ask the plotter now; `!` the page (`!m`), the timed pacing, the lift (`!r`)
and the label settles (`!a`, `!w`, `!b`), and the mode re-entry after status requests (`!g`).

**Flashing from the Pi:**
```
arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328 plotter-nano/gpib_hpgl_tek4662
arduino-cli upload -p /dev/ttyUSB0 --fqbn arduino:avr:nano:cpu=atmega328 plotter-nano/gpib_hpgl_tek4662
```
