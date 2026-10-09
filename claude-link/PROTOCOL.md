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

The GRiD stays controller-in-charge; the instruments share the bus. Every
instrument access Claude makes goes through the GRiD.

## 1. Why the link works the way it does (AR488 device-mode facts)

From the AR488 source (`AR488.ino`, ver 0.53.46):

* Data the Pi writes is parsed into one 128-byte line buffer (`pBuf`,
  `PBSIZE`; 255 with the Grid-OS patch). A line ends at an unescaped CR or
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
| 6+len | 2 | CRC-16/CCITT-FALSE (poly 1021h, init FFFFh, no reflection) over bytes 1 .. 5+len, little-endian |

* Pi → GRiD frames are at most 127 bytes in total with stock AR488 (payload
  ≤ 119) and 254 with the patched firmware (payload ≤ 246), one byte under
  the line buffer so the terminating LF always ends the line. The GRiD reads
  up to 255 bytes and scans for the sync byte, so leading garbage is
  tolerated.
* GRiD → Pi frames carry up to 1024 payload bytes (the GRiD announces its
  limit in HELLO). The GRiD writes them with EOI on the last byte.
* On the serial side the Pi escapes CR, LF, ESC and `+` with ESC and ends
  the frame with LF. In stock mode it sends `++status <64+ms>\n` first,
  in the same write.

### Sequencing and retransmission

* HELLO resets both sequence counters to 0 (the HELLO frame itself has seq 0).
* Each side increments seq for every new frame it sends, and copies the last
  good seq it received into ack.
* Bad CRC: the receiver answers with a NAK (GRiD → Pi type 06h, Pi → GRiD
  48h); the sender then retransmits its last frame unchanged.
* A frame whose seq equals the last one accepted is a duplicate (its answer
  was lost): don't process it again, just resend the last answer.

## 4. Messages

A message is a type plus a body; long bodies are split across frames with
the MORE bit set on all but the last.

### GRiD → Pi

| Type | Name | Body |
|---|---|---|
| 01h | HELLO | ver (1), flags (1: bit 0 = this CLAUDE can be a terminal, Term), max payload (2), cols (1), rows (1), then `key=value\n` lines: `os`, `gpib`, `addr`, `drives`, `mem`, `ems`, `cwd`, `date`, `grid`, and `app=term` or `app=chat` when CLAUDE was started with `/T` or `/C` |
| 02h | POLL | — (nothing to say; the Pi may hold its answer up to 250 ms waiting for output) |
| 03h | PROMPT | text (CP437) — a prompt or a slash command |
| 04h | EVENT | code (1) + data: 01h interrupt (Esc); 02h permission answer: id (1), choice (`y`, `n`, `a`); 03h repaint (Term: send the whole screen again) |
| 05h | REPLY | id (1), status (1: 0 = OK, else DOS error code or 0FFh), data |
| 06h | NAK | — |
| 07h | KEYS | Term: key words as INT 16h AH=10h returns them (AL, AH; 2 bytes each) |

### Pi → GRiD

| Type | Name | Body |
|---|---|---|
| 41h | HELLO | ver (1), flags (1: bit 0 = Term), then text: model name (or `Claude Code`) |
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
Codes above A0h show as '?'.

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
FFh unknown request.

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
  HELLO with flags bit 0. Without `app=`, gridlink's `[grid] app` setting
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
| 0 | 1 | flags: bit 0 clear rows 0-23 first; bit 1 cursor hidden |
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
(20h-7Eh and 80h-A0h, as in TEXT). An operation that does not fit the
screen or the payload ends the frame. The cursor is drawn as an inverted
underline (glyph rows 14-15).

What the Pi does with Claude Code's output: Unicode is folded to one GRiD
glyph per cell (box drawing, ● ⎿ ✻ ❯ and the spinner have glyphs; a full
block is an inverse blank; wide characters are `?` and a blank); a
non-default background or reverse video is inverse; underline stays;
colours, bold and dim are plain. The alternate screen (`?1049`) and
synchronised output (`?2026`) are handled before pyte; DA and cursor
position queries are answered by pyte, DECRQM and the colour queries
(OSC 10/11: amber on black) by gridlink; modifyOtherKeys and kitty
keyboard sequences are dropped.

**The GRiD's tools in Term.** Claude Code reaches the GRiD through an MCP
server (`python -m gridlink.mcp`, registered in the project's `.mcp.json`)
that passes each call over a Unix socket to gridlink, which sends it as a
REQUEST (section 4) — one at a time, as CLAUDE runs one at a time. A RUN
switches the GRiD to the program's screen; when it ends, CLAUDE redraws the
terminal from its own copy and the Pi sends whatever changed meanwhile.
