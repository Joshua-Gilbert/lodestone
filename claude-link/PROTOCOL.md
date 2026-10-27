# GLP 1 — GRiD Link Protocol (Claude for GRiD over GPIB)

The GRiD runs `CLAUDE` (user interface + GRiD-side tools). A Raspberry Pi runs
`gridlink` (agent loop on the Claude API + Pi-side tools). They talk over
GPIB through an Arduino Nano running AR488 firmware in **device mode**.

Two ways to use it share the link: **chat** (`CLAUDE`, gridlink's own agent
on an API key) and **Term** (`CLAUDE /T`: the GRiD is the screen and keyboard
of the real Claude Code running on the Pi, on your Claude subscription;
section 6).

```
GRiD 1520 (controller, addr 21) ==GPIB== AR488 Nano (device, addr 7) --USB serial-- Pi --internet-- Claude API
```

Since 2026-10-16 the bridge can also be the GPIB-Pico2 board (`gridlink/pico.py`, `[bridge] kind = "pico"`,
the default). GLP is unchanged on the GPIB side: the Pico bridge behaves as the patched AR488 below (status
60h raised by itself when a whole answer is in, kept until it is read, a frame up to 254 bytes, the GRiD's
frames forwarded whole), and as for SDC, it also drops an answer a newer GRiD frame has made stale. On the USB
side it needs no escaping and no `++` commands: its own framed protocol (the bridge firmware's PROTOCOL.md)
carries each GRiD frame and each answer whole. Section 1 is about the AR488.

The GRiD stays controller-in-charge; the instruments share the bus. Every
instrument access Claude makes goes through the GRiD.

## 1. Why the link works the way it does (AR488 device-mode facts)

From the AR488 source (`AR488.ino`, ver 0.53.46):

* Data the Pi writes is parsed into one 128-byte line buffer (`pBuf`,
  `PBSIZE`; 255 with the Lodestone patch). A line ends at an unescaped CR or
  LF, or when the buffer fills.
  CR, LF, ESC and `+` inside data must be escaped with ESC.
* The line is sent only when the controller addresses the Nano to talk and
  the line is complete (`lnRdy == 2`). **If the GRiD addresses it to talk
  while a line is still arriving, the partial line is thrown away**
  (`device_talk_h` flushes unconditionally).
* While a complete line waits, further serial input is *appended* to it, and
  a `++` command is then treated as data. Nothing the Pi can send clears it;
  only the GRiD (talk or SDC) can.
* Data the GRiD writes is forwarded to the Pi byte by byte, unbuffered and
  binary-transparent; the Nano stops listening at EOI.
* While the Nano listens to the GRiD it does not read its serial input; the
  Arduino serial receive buffer is 64 bytes. **If the Pi writes while the GRiD
  is writing, Pi bytes are lost.**
* `++status n` sets the serial-poll status byte; bit 6 asserts SRQ, and a
  serial poll clears bit 6 and releases SRQ.

Hence the rules:

1. **Strict alternation.** The GRiD writes one frame; the Pi answers with
   exactly one frame; repeat. The Pi never writes to the Nano except right
   after it has received a complete GRiD frame, and the GRiD never writes
   again until it has read that answer.
2. **Read only a complete answer.** The GRiD serial-polls the Nano and reads
   only when the status byte says the answer is complete (patched firmware,
   bit 5) or after waiting the number of milliseconds the Pi put in bits 0-4
   (stock firmware).
3. **Recovery belongs to the GRiD.** On any error it waits 50 ms, sends SDC
   to the Nano (clears its buffer and status) and starts over with HELLO.

## 2. Status byte (serial poll of the Nano)

| Bit | Meaning |
|---|---|
| 6 (40h) | RQS: an answer is waiting (SRQ asserted) |
| 5 (20h) | READY: the whole answer is in the Nano's buffer, read now (patched firmware sets 60h itself) |
| 0-4 | stock firmware: milliseconds to wait after this poll before reading (the Pi sends `++status 64+ms` immediately before the frame, so the frame is still arriving) |

The GRiD acts only on bit 6. It checks SRQ (`INT 6x AH=0Bh`) every pass of
its main loop and also serial-polls the Nano at least every 20 ms while an
answer is due (instruments that hold SRQ themselves would otherwise hide the
Nano's request).

## 3. Frames

Same format both ways:

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | `47h` ('G') sync |
| 1 | 1 | kind: bits 0-6 message type, bit 7 = MORE (message continues in the next frame) |
| 2 | 1 | seq: sender's frame number (mod 256) |
| 3 | 1 | ack: seq of the last good frame received from the other side |
| 4 | 2 | len: payload bytes, little-endian |
| 6 | len | payload |
| 6+len | 2 | the check over bytes 1 .. 5+len, little-endian: CRC-16/CCITT-FALSE (poly 1021h, init FFFFh, no reflection), or the Fletcher sum once HELLO has agreed to it (below) |

* Pi → GRiD frames are at most 127 bytes in total with stock AR488 (payload
  ≤ 119) and 254 with the patched firmware (payload ≤ 246), one byte under
  the line buffer so the terminating LF always ends the line. Through the
  Pico bridge they are as big as the GRiD's HELLO says it reads (`rx=`:
  2048 for CLAUDE 1.3 and its resident console; a HELLO without `rx=` means
  246, as every CLAUDE before 1.3 reads). The Pi sends a big frame as TX
  frames of 512 bytes, EOI only on the last, so it fits the firmware's input
  buffer and the bridge raises SRQ only once the frame is whole. The GRiD
  reads up to its buffer and scans for the sync byte, so leading garbage is
  tolerated.
* GRiD → Pi frames carry up to 1024 payload bytes (the GRiD announces its
  limit in HELLO). The GRiD writes them with EOI on the last byte.
* On the serial side the Pi escapes CR, LF, ESC and `+` with ESC and ends
  the frame with LF. In stock mode it sends `++status <64+ms>\n` first,
  in the same write.

### Waking an idle GRiD

Between messages the GRiD sends an idle POLL once a second, so news for an
idle GRiD (the first tool call after Claude has been thinking, say) used to
wait up to a second. A GRiD whose HELLO set flags bit 3 also looks for an
SRQ in its idle loop (AH=0Bh of the GPIB driver); when there was one it
serial-polls the bridge and POLLs at once if the status has 40h. gridlink
then asks the GPIB-Pico2 bridge for that SRQ (its WAKE frame, bridge fw
2026-10-22b) when it has something for the GRiD and no frame of the GRiD's
is waiting for an answer, again every 100 ms until the GRiD sends. The
bridge keeps the SRQ (status 40h, without the 20h of a waiting answer) until
the GRiD polls it or sends a message, and ignores a WAKE for an older
message than the GRiD's last. Older bridges ignore WAKE, and the GRiD goes on
POLLing once a second.

With a GPIB driver that takes SRQ on IRQ 5 (Lodestone's built-in one,
version 1.21, or GRIDGPIB 1.2; INT 60h AH=0Eh gives its SRQ count), CLAUDE
sleeps (HLT) while it is idle or waiting for an answer, and the SRQ wakes it
at once: about a millisecond instead of up to the next 55 ms timer tick.
While it waits it serial-polls when the count moves, and once a tick in
case an SRQ went astray, instead of every 2-4 ms.

### Sequencing and retransmission

* HELLO resets both sequence counters to 0 (the HELLO frame itself has seq 0).
* Each side increments seq for every new frame it sends, and copies the last
  good seq it received into ack.
* **The Fletcher sum** (CLAUDE 1.3): A = 1 plus the bytes, B = the sum of
  the A after each byte, both mod 256; the check is B × 256 + A (A first on
  the wire). It costs the 286 about 8.5 clocks a byte against the CRC's 34.
  The GRiD offers it in its HELLO (flags bit 2); the Pi's HELLO answer takes
  it (flags bit 2), and both sides use it for every frame after. HELLO and
  its answer always carry the CRC, as does everything after a link reset.
  The Pi accepts either check on any frame and answers each frame with the
  check that frame came with.
* Bad check: the receiver answers with a NAK (GRiD → Pi type 06h, Pi → GRiD
  48h); the sender then retransmits its last frame unchanged.
* A frame whose seq equals the last one accepted is a duplicate (its answer
  was lost): don't process it again, just resend the last answer.

## 4. Messages

A message is a type plus a body; long bodies are split across frames with
the MORE bit set on all but the last.

### GRiD → Pi

| Type | Name | Body |
|---|---|---|
| 01h | HELLO | ver (1), flags (1: bit 0 = this CLAUDE can be a terminal, Term; bit 1 = its CELLS take pictures; bit 2 = it can use the Fletcher sum; bit 3 = wake: an SRQ while it is idle makes it serial-poll, and status 40h makes it POLL at once, section 3; bit 4 = it draws the 2x2 block elements `▘▝▖▗▌▐▀▄▛▜▙▟▚▞` as codes A1h-AEh, CLAUDE 1.8, and resident Claude's console from 1.12; without it they are blanks and inverse blanks), max payload (2), cols (1), rows (1), then `key=value\n` lines: `os`, `gpib`, `addr`, `drives`, `mem`, `ems`, `cwd`, `date`, `grid`, and `app=term` or `app=chat` when CLAUDE was started with `/T` or `/C`. CLAUDE 1.3 also sends `rx=` (the Pi → GRiD payload it reads, 2048). Resident Claude's console (CLAUDE /R, popped up over a DOS program) sends only `app=resident`, `grid`, `rx=`, `req=`, `ops=` and `addr`, `prog` (the paused program, when it could ask DOS) and `screen` once it has one: 4 hex digits, the CRC-16 of its Term screen (section 6). `ops=` lists what it answers besides SCREEN and TYPE: `files` (DIR, READ, WRITE, DELETE, RENAME, MKDIR, RMDIR, STAT, FREE) and `gpib` (CLAUDE 1.9), and `bgscreen`: SCREEN in the background too (CLAUDE 1.11). Flags bit 5 (CLAUDE 1.10, resident Claude's console only): it works in the background, below |
| 02h | POLL | — (nothing to say; the Pi may hold its answer up to 250 ms waiting for output) |
| 03h | PROMPT | text (CP437) — a prompt or a slash command |
| 04h | EVENT | code (1) + data: 01h interrupt (Esc); 02h permission answer: id (1), choice (`y`, `n`, `a`); 03h repaint (Term: send the whole screen again); 04h away (resident Claude's console: the user went back to the program); 07h saver (CLAUDE 1.14, to a Pi whose HELLO says bit 4: the Executive's screen saver comes on, and the GRiD sends nothing more until it ends; the Pi counts it as there until its next frame, and rings it for anything it has, which ends the saver) |
| 05h | REPLY | id (1), status (1: 0 = OK, else DOS error code or 0FFh), data |
| 06h | NAK | — |
| 07h | KEYS | Term: key words as INT 16h AH=10h returns them (AL, AH; 2 bytes each) |

### Pi → GRiD

| Type | Name | Body |
|---|---|---|
| 41h | HELLO | ver (1), flags (1: bit 0 = Term; bit 2 = the Fletcher sum from now on; bit 3 = resident Claude's console may work in the background, below: its bridge can be quiet; bit 4 = EVENT 07h, the saver, understood, and the bridge can ring: the Pico's), then text: model name (or `Claude Code`) |
| 42h | NOP | — |
| 43h | TEXT | text to append to the conversation; control codes below |
| 44h | STATUS | status-line text (empty = clear) |
| 45h | REQUEST | id (1), op (1), arguments |
| 46h | ASK | id (1), kind (1: 1 = Yes/Always/No, 2 = Yes/No), question (ASCIIZ), detail (ASCIIZ, may hold LF), label for Always (ASCIIZ) |
| 47h | READY | — the turn is over; the prompt is live again |
| 48h | NAK | — |
| 49h | TITLE | title-band text |
| 4Ah | CLEAR | — clear the conversation view |
| 4Bh | CELLS | Term: changed screen cells (section 6); always one frame, never MORE |

TEXT control codes: 0Ah newline; 0Eh inverse on; 0Fh inverse off;
10h underline on; 11h underline off. The Pi wraps lines at the GRiD's
width (it writes at most 79 columns), so the GRiD never has to; a
character arriving in column 80 starts a new line anyway. TEXT is shown
frame by frame as it arrives (the MORE bit does not hold it back);
REQUEST and ASK are collected until the last frame. Characters 80h-A0h
are extra glyphs: 80h ● bullet, 81h ⎿ result corner, 82h … ellipsis,
83h → arrow, 84h ✓, 85h ✗, 86h · middle dot, 87h-8Ch spinner frames
(· ✢ ✳ ✶ ✻ ✽), 8Dh ─ rule, 8Eh │ bar, 8Fh ▸, 90h °, 91h µ, 92h Ω,
93h ±, 94h ×, 95h ≈, 96h ≤, 97h ≥, and box drawing on the same lines as
8Dh/8Eh: 98h └, 99h ┘, 9Ah ┌, 9Bh ┐, 9Ch ├, 9Dh ┤, 9Eh ┬, 9Fh ┴, A0h ┼.
A GRiD whose HELLO says flags bit 4 (CLAUDE 1.8, and resident Claude's
console from 1.12) also draws A1h-AEh, the 2x2 block elements
▘▝▖▗▌▐▀▄▛▜▙▟▚▞. Codes above A0h (AEh with bit 4) show as '?'.

### REQUEST operations (executed on the GRiD)

Strings are ASCIIZ. Numbers are little-endian.

| Op | Name | Arguments | REPLY data |
|---|---|---|---|
| 01h | INFO | — | `key=value\n` lines (as HELLO) |
| 02h | DIR | pattern | entries of 22 bytes: attr (1), time (2), date (2), size (4), name (13, ASCIIZ) |
| 03h | READ | offset (4), length (2), path | file bytes (≤ length); status 0 and no data at end of file |
| 04h | WRITE | mode (1: 0 create/truncate, 1 at offset, 2 append), offset (4), path, data | written count (2) |
| 05h | DELETE | path | — |
| 06h | RENAME | old, new | — |
| 07h | MKDIR | path | — |
| 08h | RMDIR | path | — |
| 09h | STAT | path | attr (1), time (2), date (2), size (4) |
| 0Ah | FREE | drive (1, 0 = default) | free bytes (4), total bytes (4) |
| 10h | RUN | flags (1: bit0 capture output, bit1 snapshot screen at exit), timeout s (2), key script length (2), key script, command line | exit code (2), flags (1: bit0 output captured, bit1 snapshot taken), output file name |
| 11h | SCREEN | which (1: 0 = last snapshot, 1 = now) | mode (1), banks (1), bpp (1: 0 = text cells), width (2), height (2), bytes per line (2), video memory |
| 12h | TYPE | key script (the rest of the request; resident Claude's console only, at most 2,048 bytes) | flags (1: bit0 all the keys were played), then as SCREEN: the program's screen afterwards |
| 20h | GPIB | op (1), addr (1), flags (1), timeout ms (2), largest reply (2), data | bytes read, or the status byte (see below) |
| 30h | SETTIME | year (2), month, day, hour, min, sec (1 each) | — |

GPIB ops: 1 write (flags bit0 EOI), 2 read (flags bit0 stop at LF), 3 query
(write with EOI, then read), 4 serial poll (reply: status byte), 5 clear
(SDC), 6 trigger, 7 local, 8 remote, 9 scan (serial-poll 1-30 except the
GRiD's and the bridge's own addresses; reply: list of responding
addresses). The REPLY status is 0 or the GRIDGPIB error code (1 timeout,
2 no listener, 3 not controller, 4 bad function, 5 no data, 6 busy).

RUN with capture runs `COMSPEC /C command >file`; without capture, a
command whose first word is a .COM/.EXE file is EXECuted directly (true
exit code, less memory), anything else through COMSPEC /C. The output file
is %TEMP%\CLAUDE.OUT (or %TMP%, or X:\CLAUDE.OUT on the current drive);
the Pi reads it and deletes it.

Key scripts for RUN: two bytes per key, ASCII then scan code (the AX word
INT 16h returns); FFh FFh n = wait n × 55 ms; FFh FEh 00h = take a screen
snapshot now (when the program next asks for a key). Keys are fed to the
program through an INT 16h hook while it runs; the real keyboard works
throughout, and takes over once the script is used up.

DOS errors come back as the DOS error code (83 = a disk error the critical
error handler failed, e.g. drive not ready). Other statuses: F0h request
too large, F1h no memory, F3h command line too long, F5h no snapshot,
F6h a DOS program is paused (resident Claude's console answers so every
request but SCREEN, TYPE and those its HELLO's `ops=` lists, e.g. RUN,
INFO and SETTIME), F7h DOS busy (resident Claude's console, a file request: the
paused program is inside a DOS call other than the kernel's key wait,
such as its own INT 24h handler; anything from MT's segment with
MULTITASK=1, its key wait and its INT 24h prompt; or the program is
DEFRAG, which writes the disk itself; GPIB requests still run), FFh unknown request.

Resident Claude's console (`app=resident`) answers SCREEN with the paused
program's screen as it keeps it (`which` doesn't matter: there is one; in
the background, with `bgscreen`, the program's screen as it is then),
and TYPE: the console goes back to the program, the key script plays into
it (keys and waits as RUN's; a snapshot mark ends it), and when it is done
the console comes back by itself and answers, with the screen then. CODE-\
on the GRiD meanwhile stops the keys (flags bit 0 clear). The console
doesn't say HELLO when it comes back for that answer, so the Pi's call
goes on; the frames' sequence numbers go on from where they were. A mode
the console doesn't keep (7, at B000h) answers status F5h (TYPE: with its
flags byte).

When the user goes back to the program (CODE-\ in the console; not when
it goes for TYPE's keys), the console sends EVENT 04h (away), before the
keys typed so far. Without the background (below), the Pi ends the calls
waiting for the GRiD and refuses new ones until the next HELLO, instead of waiting for an answer that can't
come while the program runs. A REQUEST that reaches the console on its
way out gets no answer: the EVENT has ended it on the Pi.

**The background** (CLAUDE 1.10, the console's HELLO flags bit 5 and the
Pi's bit 3). The Pi offers it when its bridge can be quiet (GPIB-Pico2
firmware 2026-10-24: CONFIG bit 2, the status byte as ever but the SRQ
line never driven), so nothing of the link's reaches the program's SRQ
latch. Then at EVENT 04h the Pi makes the bridge quiet and goes on: the
calls for files and GPIB (`ops=`) wait instead of ending, and new ones are
sent; SCREEN and TYPE are refused as before (SCREEN goes on too where
`ops=` lists `bgscreen`). While the user is in the
program its stub calls the console at the program's key calls (a peek or
a read's wait) every 4 ticks, in the front task's calls and with no
interrupt in service. The console serial-polls the bridge; when the Pi
has something it rings (WAKE: 40h, quietly), and the console POLLs, takes
the REQUEST, runs it and sends its REPLY, polled by the PIT, until the Pi
answers a POLL with a NOP. It draws nothing (the Pi sends no CELLS or
TITLE meanwhile, and answers POLLs at once). A REQUEST taken on the way
out runs in the first of these passes (not one on the way out to TYPE's
keys). Work left over from a pass that ran out of time (5 s) goes on at
the next look. File requests where DOS is busy are refused as at a pop-up
(F7h, settled again each pass); TYPE gets F6h, and SCREEN too from a
console without `bgscreen` (with it, the screen as it is then). A link failure
in a pass stops the passes with an SDC to the bridge, which tells the
Pi: it ends the calls it kept. A bridge that doesn't answer the serial
poll stops them too. Either way, until the next pop-up. Any HELLO from the GRiD makes the bridge loud
again. A call the GRiD hasn't taken when it times out (the program busy,
not at a key call) is withdrawn on the Pi, so it can't run after it was
said to fail.

## 5. Session flow

```
GRiD: SDC to Nano, HELLO              Pi: HELLO (model)  -> title band
GRiD: POLL ... (every 1 s when idle)  Pi: NOP
user types a prompt
GRiD: PROMPT "fix CONFIG.C"           Pi: STATUS "Thinking…"
GRiD: POLL                            Pi: TEXT "I'll look at the file first."
GRiD: POLL                            Pi: TEXT "● Read(A:\TM5000\CONFIG.C)"
GRiD: POLL                            Pi: REQUEST id 5 READ A:\TM5000\CONFIG.C
GRiD: REPLY id 5 (MORE)               Pi: NOP
GRiD: REPLY id 5 (last)               Pi: TEXT "  ⎿ Read 212 lines"
...
GRiD: POLL                            Pi: ASK id 6 "Edit A:\TM5000\CONFIG.C?"
user presses A (always)
GRiD: EVENT 02 id 6 'a'               Pi: REQUEST id 7 WRITE ...
...
GRiD: POLL                            Pi: READY
```

While a turn is running the GRiD polls continuously (the Pi holds each
answer until it has output, up to 250 ms); when idle it polls once a second.

Both sides ignore message types they don't know, so a newer peer works
with an older one: an older CLAUDE (no flag bit 0) always gets chat; a
newer CLAUDE that asked for Term from an older gridlink gets chat too (the
Pi's HELLO has no Term flag).

## 6. Term

`CLAUDE /T`: the Pi runs the unmodified `claude` program in an 80x24 pty
(TERM=xterm-256color). gridlink keeps the screen with pyte, and keeps what
the GRiD shows; the difference goes to the GRiD as CELLS. Rows 0-23 of the
GRiD's screen are the terminal, row 24 is CLAUDE's own status band (the
title from TITLE, the link, the keys).

* **Mode.** The GRiD's HELLO sets flags bit 0 and `app=term`; the Pi answers
  HELLO with flags bit 0. `app=resident` (CLAUDE /R's console, popped up
  over a DOS program) is Term too, the same `claude`: what was typed in
  CLAUDE /T is on its screen, and the other way round. Its HELLO's `prog=`
  names the paused program (its file name, when the console could ask DOS:
  not when DOS is more than one call deep, nor from an environment the
  program no longer owns). While the GRiD is resident only
  grid_program (SCREEN) and grid_type (TYPE) run, and the tools for what
  its HELLO's `ops=` lists (`files`: grid_files, grid_change_files;
  `gpib`: gpib_read, gpib_measure, gpib_send); the GRiD's other tools
  answer that they can't (the program holds the GRiD), and anything sent
  anyway gets status F6h. Once the user has gone back to the program,
  files and GPIB go on in the background where the bridge can be quiet,
  and grid_program where `ops=` lists `bgscreen` (section 4). The console keeps
  its screen between pop-ups and draws it at once; its HELLO's `screen=`
  is the CRC-16 (as the frames') of its 24 rows (glyph, attribute for each
  cell, row by row), then the cursor's row, column and hidden flag (0 or
  1). If that is the screen of the Pi's last CELLS frame, or of the one
  before, the Pi goes on from it and sends only what changed; else it
  starts from a clear screen as for any HELLO. Without `app=`,
  gridlink's `[grid] app` setting
  decides (`auto`: chat when the Pi has an API key, else Term). The Pi's
  HELLO is followed by a CELLS frame that clears the screen and draws it all.
  In Term, CLAUDE ignores the chat's messages (TEXT, STATUS, ASK, READY,
  CLEAR). Any answer to HELLO that is not a HELLO makes the GRiD start the
  link again.
* **Keys.** The GRiD reads keys with INT 16h AH=11h/10h (AH=01h/00h never
  return CODE with punctuation, Return, Esc or Backspace on the 1520) and
  sends every key except CODE-Q (quit) and CODE-R (repaint here, and EVENT
  03h) as KEYS, as many as have been typed in one message, one KEYS message
  at a time. The Pi turns each word into an xterm's bytes: arrows, Home,
  End, PgUp, PgDn, Ins, Del, F1-F10, Shift-Tab `ESC [ Z`, CODE-letter
  `ESC` + letter (Meta), CODE-Return and Ctrl-Return `ESC CR` (a new line in
  Claude Code's prompt), Backspace DEL.
* **Polling.** The GRiD polls back to back for 2 s after a key or a CELLS
  frame, then once a second. The Pi holds a POLL up to 60 ms (not 250) and
  a KEYS frame up to 30 ms, so the echo of a key comes back in the answer
  to the frame that carried it.
* **Latest state, never a backlog.** The Pi builds a CELLS frame only when
  the GRiD asks and the screen has settled (no output for 12 ms, or 80 ms
  at most; a synchronised-output block `?2026h`..`l` is waited for). What
  the program drew meanwhile is merged: a slow link means fewer frames, not
  a queue. The Pi counts a frame as shown when the GRiD's next new frame
  arrives (not a NAK or a repeat; those get the same frame again); a HELLO
  starts over from a clear screen.

CELLS payload:

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | flags: bit 0 clear rows 0-23 first; bit 1 cursor hidden; bit 2 a picture's frame (every frame of a picture has it, a text frame never: CLAUDE 1.13 in a terminal window goes full screen for a picture and back to its window at the first frame without it) |
| 1 | 1 | cursor row |
| 2 | 1 | cursor column |
| 3 | ... | operations to the end of the payload |

| Operation | Bytes | Meaning |
|---|---|---|
| run | row, col, len, [attr], len glyphs | cells (row, col) .. (row, col+len-1) |
| fill | row \| 80h, col, len, [attr], glyph | the same glyph len times |
| scroll | FEh, top, bottom, n | rows top..bottom up by n; n blank rows come in at the bottom |

`len` bit 7 means an attribute byte follows (bit 0 inverse, bit 1
underline); without it the cells are plain. Glyphs are the GRiD's codes
(20h-7Eh and 80h-A0h, as in TEXT, and A1h-AEh for a GRiD whose HELLO
says flags bit 4). An operation that does not fit the
screen or the payload ends the frame. The cursor is drawn as an inverted
underline (glyph rows 14-15).

What the Pi does with Claude Code's output: Unicode is folded to one GRiD
glyph per cell (box drawing, ● ⎿ ✻ ❯ and the spinner have glyphs; a full
block is an inverse blank; the halves and quarters are A1h-AEh for a
GRiD that says flags bit 4, else blanks or inverse blanks; wide characters are `?` and a blank); a
non-default background or reverse video is inverse; underline stays;
colours, bold and dim are plain. The alternate screen (`?1049`) and
synchronised output (`?2026`) are handled before pyte; DA and cursor
position queries are answered by pyte, DECRQM and the colour queries
(OSC 10/11: amber on black) by gridlink; modifyOtherKeys and kitty
keyboard sequences are dropped.

**The GRiD's tools in Term.** Claude Code reaches the GRiD through an MCP
server (`gridlink.mcp`, registered in the project's `.mcp.json`) that
passes each call over a Unix socket to gridlink, which sends it as a
REQUEST (section 4) — one at a time, as CLAUDE runs one at a time; a call
that arrives during another waits for it. A RUN
switches the GRiD to the program's screen; when it ends, CLAUDE redraws the
terminal from its own copy and the Pi sends whatever changed meanwhile.
