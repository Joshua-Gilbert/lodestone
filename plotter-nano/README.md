# The 4662's Nano

`gpib_hpgl_tek4662/gpib_hpgl_tek4662.ino`: the firmware for the Arduino Nano
that puts the Tektronix 4662 pen plotter on the GPIB bus. It is a GPIB device
at address 1 (`GPIB_ADDRESS`) that takes HP-GL and sends it to the 4662 as
Tek commands on RS-232 at 1200 baud. gridlink's `grid_plotter` drives it
(`claude-link/README.md`, The pen plotter), and so does `PLOT.COM` on the
GRiD itself, without the Pi (below).

**Wiring** (AR488's Nano pin map): DIO1-4 D2-D5, DIO5-8 A0-A3, DAV D7,
NRFD D8, NDAC D9, ATN D10, IFC D11, SRQ D12, EOI A4, REN A5; the GPIB
cable's ground returns (pins 18-24) and shield (12) to GND. Plotter: D6 to
the MAX3232 breakout's TXD and its RXD to D13, then the AT925MF adapter to
the 4662's MODEM port. 4662 switches A=3, B=2, C=2, D=3 (Copy Mode,
1200 baud, address A); switch A without its Copy bit for standard mode, which
uses the whole page (v7.5). Power the Nano before the plotter; on the Pi's USB it
shares the bus's ground and its console is a `miniterm` away.

**From the GRiD: `PLOT file [/A:n]`** (`os/src/PLOT.ASM`, on ROM 2, so the
prompt finds it on R: through PATH; 3.8 KB). It sends an HP-GL file to the
Nano at GPIB address n (default 1) through the GRiD's GPIB driver (INT 60h:
Lodestone's built-in one, or GRIDGPIB.COM under GRiD MS-DOS). It keeps
`grid_plotter`'s rules, so a file one plots the other plots too:
- The whole file is checked before anything is sent, as `hpgl_check` checks
  it: printable ASCII, line ends, tabs, ETX, BS, SO, SI, ESC and SUB, and no
  label left open (LB, BL or WD, in any case, after the last ETX, with the
  CR, LF, TAB, BS, SO, SI and SUB the Nano drops between a mnemonic's
  letters left out). A `;` goes on the end if there isn't one.
- A command with a label (LB, BL or WD anywhere before its first `;`, read
  as the Nano reads it) ends at the label's ETX and the `;` after it: a `;`
  in its text is text.
- Each serial poll, it sends the whole commands that fit in the room the Nano
  reports: at least 64 bytes, or the drawing's end. A single command longer
  than 200 bytes of room is sent a room's worth at a time (a label's rest is
  then read up to its ETX, whatever `;` its text holds; a cut never falls
  between a mnemonic's two letters). So no write waits
  on the bus, and the driver's own 2 s per byte time-out is left alone: it is
  one setting for every GPIB client, CLAUDE's link included.
- While the Nano is full, PLOT waits on HLT, so it is idle under multitasking
  (a task in the background plots while you work). It gives up after 200 s
  with no progress. At the end it polls until the Nano is idle.
- At the start, a Nano that polls idle (bit 7) is plotted on, with no clear:
  an idle Nano is in no label. A busy one gets "The plotter is still busy.
  Waiting for it (Esc: plot now)." and is polled about once a second (keys
  typed before that line are thrown away: they don't answer it). Idle, and
  PLOT plots, with no clear. A status that changes (an earlier drawing
  draining) is waited for as long as it takes: this plot queues behind it.
  A status of exactly 3Ch (the ring empty, the Nano not idle) unchanged for
  60 s gets "The plotter has not changed for 60 s: plotting now.", a device
  clear (SDC, the driver's function 06h; v7.7, below), best-effort, and the
  plot: a Nano left in a label, or in a command cut part-way, never goes
  idle. Any other status unchanged for 200 s gives up, nothing sent, no
  clear, exit 3: "PLOT: the plotter still holds an earlier drawing and has
  not moved for 200 s (Esc while it waits plots now).  Nothing was sent.",
  or, for a status of 0, "PLOT: the Nano had no room for 200 s.  Nothing
  was sent." No answer for 200 s gives up too, exit 3: "PLOT: the Nano
  stopped answering serial polls.  Nothing was sent." Esc while it waits
  sends the clear and plots at once; ^C stops, "Stopped: 0 of n bytes
  sent.", exit 1, no clear.
- Only 3Ch is cleared because a clear drops whatever is in the Nano's ring
  (v7.7's `markClear`): with bytes in it, that is the end of an earlier
  drawing, and the ring can stand still for minutes with bytes in it while
  the Nano waits for the plotter's status reply (up to its 180 s
  `STATUS_TIMEOUT`). At 3Ch the ring is empty. The 60 s covers a label: the
  Nano takes a whole one (up to 255 characters) out of its ring and draws
  it at 150 ms a character, some 38 s at 3Ch and not idle, which a clear
  would cut short.
- No answer to the first poll is no Nano (exit 2). An address whose poll
  asks for service (bit 6, which the Nano never sets: the Claude bridge
  with a frame waiting), at the first poll or any poll while PLOT waits, is
  refused (exit 2). Neither is sent a clear.
- Esc or ^C stops it: a device clear first, then, once a poll gives room,
  ETX and `PU;` in one write if the cut was inside a label's text, `PU;`
  alone after a whole command, and nothing inside any other command (an ETX
  in a PA or PD list would end a half number); "Stopped: n of m bytes
  sent." If no poll gives room for the pen-up in about 2 s, or its write
  fails, PLOT says "The pen-up could not be sent", and inside a label adds
  that firmware which ignores a clear is still in it: switch the Nano off
  and on before plotting again. Esc while all is sent and the pen is
  finishing leaves it to finish, with no clear.
- Given up part-way with the Nano still answering (no room for 200 s, a
  write that failed), PLOT sends a device clear first, best-effort, so the
  Nano isn't left in a label. A Nano that stopped answering is sent
  nothing. A read error part-way lifts the pen as Esc does, with no clear.
  A disk error doesn't prompt (PLOT's INT 24h handler fails it), so the
  read fails and the pen goes up.
- `/A:` should name the Nano. An idle instrument's poll (0) looks like a full
  Nano: nothing is sent, and after 200 s PLOT gives up (exit 3). The Pico
  bridge with a reply waiting gives 20h, which reads as room, so HP-GL
  would go into the Claude link.
- Exit codes: 0 plotted (or left to finish), 1 stopped, 2 nothing sent (the
  file, the switches, no GPIB driver, no Nano answering, an address asking
  for service), 3 given up (part-way, or at the start after 200 s busy).

`os/tests/test_plot.py` (129 checks) runs it in the emulator against a model
of the Nano on the bus model (`tools/sim7210.py`). The tests check:
- the bytes the Nano gets, with each write within the room the poll before
  it gave and ending a whole command, as gridlink's `hpgl_ends` marks them;
  an idle Nano at the start never cleared;
- a 2 KB command and a 600-byte label with a `;` in its text sent in parts,
  and Esc during either (nothing inside the PD, ETX and `PU;` in the label);
  a PA list with a label at its end, Esc in the list (no ETX); BL, WD and a
  label after `PA10,20`, kept whole or split, and a mnemonic `L<CR><LF>B`
  at the room's end, never cut between its letters; a label cut just after
  its ETX, whole commands again after it;
- a busy Nano at the start: full for 40 polls, then plotted on with no
  clear; 200 bytes of an earlier drawing held, or a Nano left in a label,
  then Esc (the clear, then all of it); ^C while it waits (nothing sent, no
  clear); an earlier drawing draining for ~50 s, and a ring standing still
  with bytes in it for ~100 s (both waited for, no clear, none of the
  earlier drawing lost); a Nano left in a label and no key (3Ch for 60 s:
  "plotting now", the clear, all of it); a label still drawn for ~40 s at
  3Ch (waited for, no clear); bytes in the ring unchanged past 200 s
  (exit 3, nothing sent, no clear); bit 6, and the Nano gone, while it
  waits; an Esc typed before the wait (not its answer); a long PD left
  open by firmware that ignores the clear, then the next PLOT with no key
  (plotted after 60 s, its first letter ending the PD); a second PLOT
  straight after an Esc while the pen finishes (it waits for the first's
  rest, no clear);
- Esc and ^C part-way (the clear, then the `PU;` within the room a poll
  gave), with v7.7 and with firmware that ignores the clear (v7.6: the
  pen-up that can't be sent, and the advice to switch the Nano off and
  on), a read error (no INT 24h question, the pen up, no clear), an
  address that asks for service (no clear);
- the give-ups: never any room (nothing sent, exit 3), no room for 200 s or
  a write failing inside a split label (a clear after the last byte), and
  the Nano unplugged part-way;
- that every refused file is one gridlink's `hpgl_check` refuses too, and
  that what PLOT sends is what `hpgl_check` would.

**v7.7: a device clear starts afresh.** A Selected Device Clear (SDC) while
the Nano is addressed to listen, or a Device Clear (DCL), drops what the Nano
holds of the plot: the bytes queued on the bus side before the clear (at
once, so they no longer hold NRFD or keep the poll from idle), the HP-GL in
hand (a label still waiting for its ETX, a command or coordinate list cut
short, a pen left down by a `PD` whose `PU` never came), and the rest of a
label it is drawing. Bytes sent after the clear are kept, so a controller
can cancel with SDC and then `PU;`. What the Nano has already queued for the
4662, and what the 4662 has in its own buffer, is still drawn. The label
settings (size, direction, character sets) are kept. Before v7.7 only an
ETX ended a label, so a plot cancelled in the middle of one left the Nano
in label mode, its poll never idle, and the next plot was taken as label
text up to its first ETX.

Five of the 4662's own commands are no longer passed to the 4662's address
(`PLOTTER_ADDR`), as each would stop the status replies the Nano paces by
(or everything after them), and none has a use behind the Nano, whose
receiver is always ready and which sends no blocks (070-4164-00):

| Withheld | Why |
|---|---|
| `ESC A R` SET PROMPT CHARACTER | each reply held until that character comes, and after a READ STATUS nothing but PLOTTER ON/OFF, BLOCK START and DEVICE RESET obeyed until it does (p. 2-17, 4-10) |
| `ESC A U` SET BYPASS CANCEL CHARACTER | after each reply the 4662 ignores its input up to that character (p. 2-19, 4-8) |
| `ESC A G` SET TURNAROUND DELAY | each reply held until the line has been quiet that long (p. 2-17, 4-6); a late reply overstates the room the Nano counts from it |
| `ESC A F` PLOTTER OFF | nothing obeyed until PLOTTER ON (p. 4-3) |
| `ESC A (` BLOCK START | Block mode: the Nano's own bytes spoil a block's checksum, and after a block all but PLOTTER ON/OFF and BLOCK START is ignored (p. 2-12 to 2-14) |

The ESC and the address have gone by the time the code comes, so SUB goes
in the code's place (ESC A SUB is ignored, p. 3-4); the character or the
numbers after it are read but not sent, and the USB console says
`[4662] ESC A R dropped: it would break the Nano's pacing`. The same codes
for another address still go, as does S (SET SIGNATURE CHARACTER: a
character before each reply, which the Nano reads past). A DEVICE RESET
passed through clears the 4662's output buffer (p. 4-12), so a status
request still unanswered then is given up and asked again, instead of
waiting out the 180 s `STATUS_TIMEOUT`.

A 4662 command (an ESC passed through) cut by the clear is ended there, so
the 4662 doesn't take the Nano's next byte as part of it. Where it was cut
decides how (page numbers are the 4662 programmer's manual, 070-4164-00):
- Right after its ESC: GS. ESC GS is the same as GS (Table 3-4, p. 3-10),
  and the next stroke enters graph mode with GS and a full coordinate
  anyway.
- Before its code, before Option 31's second letter, or in its numbers:
  SUB, the terminator the manual recommends (p. 3-4). A code the 4662
  doesn't know is ignored (p. 3-4), so ESC A SUB does nothing.
- Before the character S takes (any character but NUL, SYN and DEL,
  p. 3-3), or U or R for another address: SUB is the character. After S
  (SET SIGNATURE CHARACTER, p. 4-9) that only puts a SUB before each reply,
  which the Nano reads past.
- In a withheld command: nothing, as its ESC A SUB went whole at its code.
- A command cut in its numbers is carried out with the number it has when
  the SUB comes (a cut `ESC A K 1000,15` goes to 1000,15): the manual gives
  no way to abandon one (p. 3-4).

What clears, and what doesn't:
- A DCL clears every device on the bus, so a DCL from any program (an
  agent's "clear all", say) also cancels a plot running in the background.
- A sender that starts its plot with an SDC throws away the undrawn tail of
  the plot before it.
- IFC is not a device clear (IEEE-488.1: it resets the interface, not the
  device). It still unaddresses the Nano and ends a serial poll, but keeps the
  bytes and the parser. KGPIB pulses IFC after any program's failed bus
  operation, so IFC as a clear dropped plot bytes in the middle of a command
  (a cut label's tail then read as HP-GL: stray strokes), and a floating IFC
  line with the GRiD off would have wiped USB console input on every pass.
- A `LISTEN_ONLY` build hears every SDC on the bus, whichever device it is
  for (CLAUDE sends one to the Pico every second while it waits for the
  link), so it takes DCL only.

The clear is marked where the bus is served and the parser is reset in
`loop()`, because the bus is also served from inside the parser's waits for
the plotter. A serial poll's byte also no longer goes on DIO when ATN falls
just before it: the ATN test and the drive share one `cli`.
`tests/test_nano.cpp` checks the clears, including ones that arrive during a
pacing wait and in a label, the bytes sent for a 4662 command cut at each
place, the withheld commands (and S and other addresses passed), a
request given up at a DEVICE RESET, IFC kept apart from the clears, and
that ATN race; built with `-DLISTEN_ONLY=true` it checks that variant. v7.7
built with arduino:avr 1.8.8 for `arduino:avr:nano:cpu=atmega328`: 17044
bytes of flash (of 30720) and 1291 bytes of SRAM for globals (of 2048); v7.6
was 16706 and 1290.

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
label starts one, and the Nano passes it to the plotter as it is (since
v7.7 all but the five above that would break its pacing).
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
  lands.

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
