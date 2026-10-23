# Term: Claude Code on the GRiD (0.4.0)

`CLAUDE /T` makes the GRiD 1520 the screen and keyboard of the real Claude
Code, running on a Raspberry Pi 5 on the GPIB bus, on your own Claude
plan. Phase 1 of two; Phase 2 (Claude resident over DOS programs) is at the
end.

## Why a terminal

A Claude subscription may be used only through the unmodified Claude Code
program; anything built on the Agent SDK needs an API key. So the
subscription route puts nothing between you and `claude` but a terminal:
the Pi runs `claude` in a pty, the GRiD shows its screen and sends its keys.
The API-key route (CLAUDE's chat, gridlink's own agent) is unchanged; one
gridlink serves both, and the GRiD's HELLO says which (`app=term`).

```
GRiD 1520            GPIB          AR488 Nano       USB      Raspberry Pi 5 (4 GB)
CLAUDE /T  ── KEYS ──────────────▶ (device, 7) ──────────▶  gridlink ── pty ── claude
 rows 0-23 ◀── CELLS (changed cells) ◀───────────────────     pyte screen, cell diff
 row 24: status                                              MCP server ◀── claude
 REQUESTs (files, RUN, SCREEN, GPIB) ◀────────────────────    (the GRiD's tools)
```

The GRiD stays the GPIB controller; the Pi is a device at address 7,
through the bridge the chat already uses. GPIB only.

## How it works

**On the Pi** (`claude-link/gridlink`):
- `term.py`: `claude` in an 80x24 pty (`TERM=xterm-256color`, in `~/grid`),
  started on the GRiD's first HELLO and kept across reconnects; Return
  starts it again when it exits.
- `termscreen.py`: pyte keeps the screen. A pre-filter handles what pyte
  lacks or misreads: the alternate screen and synchronised output (`?1049`,
  `?2026`), DECRQM and colour queries (answered: amber on black),
  modifyOtherKeys and kitty keyboard sequences (dropped). Each cell becomes
  one GRiD glyph (`●` `⎿` `✻` `❯`, box drawing and the spinner have glyphs; a
  full block is an inverse blank); a coloured background or reverse video
  is inverse, underline stays, colours and dim are plain.
- The encoder keeps what the GRiD shows and sends the difference as runs,
  fills and scrolls, built only when the GRiD asks and the screen has
  settled (12 ms without output, 80 ms at most, a `?2026` block complete).
  So the GRiD always gets the latest screen, never a backlog: a slow link
  means fewer frames. A frame counts as shown when the GRiD's next new
  frame arrives; NAKs and repeats get the same frame again; a HELLO starts
  from a clear screen.
- `link.py`: the frame source is pulled when the queue gives way (the two
  take turns; the answer to HELLO comes first). The Pi holds a POLL up to
  60 ms and a KEYS frame up to 30 ms, so a key's echo comes back in the
  answer to the frame that carried it. pyserial's `read(4096)` waited out
  its 20 ms timeout on every frame; it now reads one byte, then what is
  waiting.
- `keys.py`: BIOS key words to xterm bytes (CODE = Meta; CODE-Return and
  Ctrl-Return = ESC CR, a new line in Claude Code's prompt).
- `router.py`: chat or Term, per HELLO. An older CLAUDE (no Term flag)
  always gets chat; without an API key the chat answers with how to start
  Term.
- `mcp.py`: the GRiD's tools for Claude Code, a stdio MCP server that
  gridlink registers in `~/grid/.mcp.json`. Each call goes over a Unix
  socket to gridlink and to the GRiD as a REQUEST, one at a time (CLAUDE
  drops a second REQUEST that arrives while one waits to run). Four tools
  only look (`grid_info`, `grid_files`, `grid_screen`, `gpib_read`) and can
  be allowed for good; three change something (`grid_command`,
  `grid_change_files`, `gpib_send`) and Claude Code asks before every call
  (Tool server limits, below).

**On the GRiD** (`os/claude`):
- `TERMLINK.INC`: the GLP link, moved out of CLAUDE.ASM unchanged except
  for the Term poll (back to back for 2 s after a key or a screen change,
  then once a second) and `link_lost`, the program's part of a failure.
- `TERMCELL.INC`: the cell blitter (moved), the CELLS decoder, the 24x80
  shadow (in the conversation's memory, which Term doesn't use), scroll
  (four `rep movsw` per bank), the cursor (glyph rows 14-15 inverted), the
  redraw from the shadow, the status band. Every operation is checked
  against the screen and the payload; a bad one ends the frame.
- `TERMKEYS.INC`: keys by INT 16h AH=11h/10h (01h/00h never return CODE with
  punctuation, Return, Esc or Backspace on the 1520), batched, one KEYS
  message at a time; CODE-Q quits, CODE-R redraws and asks the Pi for the
  whole screen.
- CLAUDE.ASM: `/T` and `/C`, HELLO flags bit 0 (can do Term) and `app=`,
  the mode from the Pi's HELLO, the chat's drawing routines step aside in
  Term, and RUN's return to mode 40h redraws Term from the shadow while the
  Pi's dirty cells catch up.

The frame format is in `claude-link/PROTOCOL.md`, section 6.

## Measured

| | |
|---|---|
| The real `claude` (2.1.295, first-run screens, no login): raw pty output | 6,160 bytes |
| What Term sent for it (frames included) | 1,185 bytes stock, 1,114 patched |
| A keypress in its theme picker: raw / sent | 1.2 KB / 52-58 bytes |
| The stand-in Claude Code, a whole session: raw / sent | 56.8 KB / 4.5 KB |
| A typed key's echo, a spinner step | 20 / 15 bytes |
| A line of a streamed answer (with the scroll) | about 110 bytes |
| 60 lines at once (the last screen only) | 982 bytes |
| Key to echo, simulated link and Pi (GridSim) | 20 ms patched, 25 ms stock |
| Key to echo on screen, GRiD time (pcemu, real CLAUDE.COM) | 48 ms, plus the Pi's own |

At 3.2 KB/s (stock firmware) a streamed answer can scroll about 29 lines a
second; the patched bridge doubles that. Through the Pico 2 bridge (87 KB/s
to the GRiD, measured on the 1520) the link no longer sets the pace: the
GRiD's own drawing does.

## Cost

- CLAUDE.COM 12,320 bytes (+1,168). In memory 28,576 bytes for code, data
  and stack (+1,440; the keys buffers are 256 of it), plus its buffers as
  before: about 68.9 KB while it runs. A DOS program it runs gets 1.4 KB
  less than with 1.0.
- LODE.SYS 45,438 bytes, unchanged but for the version (0.4.0); memory for
  DOS programs unchanged: floppies 562.5 KB, EMS 578.6, C: 559.2, C: and EMS
  575.7.
- Nothing on the GRiD stays resident.

## Review

An independent review agent read the whole change. It found nothing unsafe
in the GRiD's CELLS path (every operation bounded by the screen and the
payload; no 386 instructions or long conditional jumps), and these, all
fixed and tested:

- **Switching between chat and Term** left the other app talking: a chat
  turn still running could draw chat text over Term's screen (and its
  shadow), open a question Term can't answer, and run requests; Claude
  Code's title went on reaching the chat. Now the router stops the app it
  leaves (its turn interrupted, its GRiD calls failed at once), the chat's
  sends go through a gate that drops them while Term has the GRiD, the title
  only goes in Term, and CLAUDE ignores TEXT, STATUS, ASK, READY and CLEAR
  in Term (a table of its own).
- **Answers to the program's terminal queries** went out of order: pyte
  answered DA1 at once, gridlink's answers (colour, DECRQM) after the whole
  read, so a program that ends its questions with DA1 would have taken the
  late answers as typing. The pre-filter now hands pyte and the answers
  over in the order they came.
- **An API key in gridlink's environment** (for the chat) reached Claude
  Code, which could then bill the API instead of the plan. It is removed
  from `claude`'s environment (`[term] keep_api_key` to keep it).
- **Relative Pi paths** in the copy tools meant gridlink's directory, not
  Claude Code's; the MCP server (which runs where Claude Code does) makes
  them absolute.
- **A failure while answering HELLO** left the GRiD at "Connecting" for
  good: an answer to HELLO that isn't a HELLO now restarts the link, the
  chat's start-up errors become a message, `claude`'s start-up errors too,
  and `anthropic` is imported ahead.
- **`.mcp.json`** that didn't read as JSON was overwritten (losing other
  servers); now it is left alone with a message, and written atomically.
- **The MCP server** died on a socket error or a message that isn't an
  object; now an error result.
- **CODE-R held down** could fill the transmit queue so that a REPLY was
  dropped and every later request waited forever; now one repaint request
  at a time with a slot to spare, and a request runs only when its REPLY
  has room.
- Smaller: Ctrl-H is ^H (not DEL), Home and End follow DECCKM, a lone Esc
  is written on its own (not read as Meta-key), colon SGR (`4:3`, colon
  colours) is rewritten for pyte, the socket is created owner-only, the
  title and the keys no longer overlap on row 24, a restarted `claude`
  starts with a fresh parser, and the old Lodestone 0.3 strings (the
  Executive's band and help, LCMD's banner) say 0.4.

## Tool server limits

A second review, of the MCP tools alone, found four ways around Claude
Code's own permission checks, all fixed (with an advisor's review of the
fixes, which added the last four items):

- **Pi files without a prompt.** The copies could read or write any file on
  the Pi: a GRiD file over `~/.claude/settings.json` or `.bashrc`, or
  `~/.claude/.credentials.json` out to the GRiD. Now only inside `~/grid`
  (the real path, symlinks followed), never a dot-name (`.claude/`,
  `.mcp.json`) or `CLAUDE.md`; only regular files with one link go to the
  GRiD (so no FIFO hangs gridlink, no hard link carries a file out); a copy
  from the GRiD is written to a temporary file and renamed over the name, so
  a link there is replaced, not written through.
- **"Don't ask again" covered too much:** allowing a read allowed delete,
  allowing `DIR` allowed `DEL *.*`, allowing a GPIB query allowed writes to a
  power supply. Claude Code remembers permission per tool and its rules
  can't look at arguments, so the tools are split: four that only look
  (`readOnlyHint`), three that change something. Those three carry
  `_meta: {"anthropic/requiresUserInteraction": true}`: Claude Code asks on
  every call, in every mode, offers no "don't ask again" and lets no allow
  rule skip it (its docs, and its code: the flag turns into an "ask" with no
  rule to add). GPIB queries are among them: a query is a command, and some
  (`MEAS?`, `READ?` on a Keithley source-meter) turn a source's output on.
  Nothing is written into Claude Code's settings.
- **No size limits.** A huge or special Pi file could exhaust gridlink's
  memory or hang it; reads stopped quietly at 256 KB or 4 MB, so reading,
  editing and writing back could cut a GRiD file short. Now a copy or write
  is at most 1 MB and a read into the conversation 48 KB (below Claude
  Code's 50,000 characters, past which it puts a result in a file); the
  GRiD file's size is asked first, and bigger is an error naming it. A
  program's output past 48 KB comes back as its first 40 KB and last 8 KB,
  with the bytes between counted.
- **No input checks.** Every argument is checked before anything reaches
  the GRiD (types, GPIB address 0-30 and not 21 or the bridge, timeouts,
  reply sizes, CP437 without control characters: a NUL would cut a path, a
  CR end a command line). A `{WAIT}` was unbounded (`{WAIT 1e9}` built a
  210 MB script); now at most 600 s, a script at most 4,096 bytes (CLAUDE
  takes 4,700 per request), and all its waits shorter than the timeout. The
  stdio server exited on params that weren't an object, on bytes that
  weren't UTF-8, and on deeply nested JSON; now each gets a JSON-RPC error.
- **DOS device names** (the advisor): `read A:\AUX` opened the serial port
  on the GRiD and waited for good. `CON`, `AUX`, `PRN`, `NUL`, `COM1-4`,
  `LPT1-3`, `CLOCK$` are refused in any directory with any extension, in
  the tools and in `Grid.read`/`write` (so for the chat too).
- **`python -m` imported from `~/grid`** (the advisor): `-m` puts the
  working directory first on `sys.path`, and Claude Code may write files
  there, so a `json.py` in `~/grid` would have run as you before any
  prompt. `.mcp.json` now starts Python isolated (`-I`).
- **"Not connected" while busy** (the advisor): a RUN keeps the GRiD from
  polling, so a second call was told to start CLAUDE /T. It now waits its
  turn and asks after.
- **Command line and timeout** (the advisor): CLAUDE builds ` /C `,
  the command, ` >` and the output file into DOS's 125 characters, so a
  command is at most 100 (status F3h now reads "command line too long"). The
  GRiD never stops a program; the timeout is only how long the Pi waits, at
  most 3,600 s.

Left as it is: the check between resolving a path and opening it can be
raced only by a program running as you, which could read the files itself.

**Follow-ups after the merge** (from the second review):
- A device name with a colon got past the check: `A:\AUX:` and `A:\X\COM1:`
  (the colon was taken for a drive's, leaving an empty name), and Lodestone's
  own `EMMXXXX0` wasn't on the list. Both are refused now.
- `gpib_read` said it was idempotent. It is read-only, but a read empties the
  instrument's output and a poll clears its status, so it now says
  `idempotentHint: false`.
- `initialize` answered with whatever protocol version the client asked
  for; it now answers with that version only when it is one it knows
  (2025-06-18, 2025-03-26, 2024-11-05), else with its own.
- `terminator: []` (or any value that isn't crlf, lf or none) was taken as
  crlf; it is an error now.

## Tests

- `claude-link/tests/test_term.py` (17): the pre-filter, the alternate
  screen and sync, glyphs and attributes, the encoder against pyte (random
  screens, both frame sizes, scroll and fill), the key map; end to end with
  the GRiD model and `fake_claude.py` in a real pty: typing, a 60-line
  answer, a diff, a permission dialog, Shift-Tab, CODE-Return, Ctrl-C, the
  alternate screen, CODE-R, damaged frames both ways on stock firmware,
  `claude` exiting and starting again, a link restart, the router, the echo
  time; the review's cases (answers in order, colon SGR, no API key for
  Claude Code, a lone Esc, the chat stopped and gated when Term takes over).
- `test_emu_term.py` (8): the real CLAUDE.COM /T in the emulator, its
  shadow and every pixel of rows 0-23 checked against pyte: typing, scroll,
  inverse, the keys, CODE-R, a DOS program run in the middle, CODE-Q; chat
  messages ignored in Term, CODE-R held down and then a request, a HELLO
  answered with NOP (the link starts again).
- `test_mcp.py` (13): the MCP server over stdio to the GRiD model: files
  (read, write through NAME.$$$, copies both ways), a captured command, a
  key script with a screenshot, GPIB, two calls at once, the GRiD away.
  Relative paths, a `.mcp.json` it can't read. The limits: the tool list
  (which look, which always ask); Pi paths (outside `~/grid`, symlinks out,
  dot-names, `CLAUDE.md`, a FIFO, a hard link, writing over a link); about
  60 bad arguments, none of which reaches the GRiD; sizes as errors, a long
  output's start and end; the stdio server fed broken bytes, deep JSON and
  wrong shapes; a second call during a long one; a `json.py` in `~/grid`
  that must not load. The real Claude Code's `claude mcp list` connects to
  it.
- `fake_claude.py`: a stand-in for Claude Code in a pty (no login, no
  model), drawing as Claude Code does: a static part that scrolls, a live
  part redrawn with cursor-up and erase inside `?2026`, DA query, title,
  256 colours and backgrounds, bracketed paste, `/pager` on the alternate
  screen.

## On the Pi 5

1. Pi OS 64-bit, zram; Claude Code's native install; `claude` once to sign in.
2. `install.sh` (adds pyte); no API key needed for Term.
3. `CLAUDE /T` on the GRiD. Check: the first screen, the echo, a permission
   dialog answered on the GRiD, an MCP call that runs a DOS program and
   returns its screen. If the echo feels slow, raise the bridge to 500,000
   baud (claude-link/README.md, Speed).

## Phase 2: resident Claude (the original sketch)

Being built: the plan, its spikes, M1 (`CLAUDE /R` and `/U`, 0.8 KB resident) and M2 (this Term, in the pop-up: the same session, its code in EMS) are in `lodestone-resident-claude.md`.

A hot key, CODE-\\ (in the BIOS's set that AH=00h programs never see), pops
Claude Code up over a running DOS program; Claude sees that program's
screen and types into it; the program carries on. All intelligence stays
on the Pi; the GRiD needs only a screen-and-keys console and RUN's key hook.

- **About 1.1 KB conventional** (a TSR, `CLAUDE /R`): RUN's INT 16h hook
  (205 bytes today) extended to catch the hot key with AH=11h, pop-up and
  pop-down, the EMS page registers saved and restored around everything, a
  key-script buffer and a stack. **3 EMS pages:** one for TERMLINK, TERMCELL,
  TERMKEYS, the font and the link buffers (why they are written CS-relative,
  without DOS calls); two for the program's 32 KB screen, moved by INT 67h
  57h straight from video memory.
- **Typing:** a new REQUEST 12h TYPE takes a key script in RUN's format; at
  a snapshot mark or the script's end Claude pops up silently at the
  program's next key wait, answers the link for a while (SCREEN from the
  saved copy, the next TYPE) and returns: the resident agent loop with no
  timer hook.
- **Rules:** pop up only from the INT 16h hook (the program is waiting for a
  key). At `indos` 1, DOS calls run on the kernel's 512-byte stack: READ,
  DIR, STAT yes, RUN never (EXEC resets `indos`; the program holds the
  memory), new status F6h. The link is served only while popped up, never
  from INT 08h (the GPIB driver's timeouts count the BIOS tick; INT 60h is
  not re-entrant). INT 60h busy (AX=6) means later, not a failure. No
  INT 60h AH=0Bh from the resident: it would clear TM5000G's SRQ latch.
- **Spikes first:** a 300-byte TSR running code from the EMS frame over a
  program that uses EMS (pcemu, then the 1520); a pop-up over TM5000G with
  the 7210 model while it polls an instrument; video memory and 40:49-66h
  byte-compared before and after a pop-up over a graphics program, and
  GRIDPROBE on the 1520 for the V6366's state.
- **Not in Phase 2:** an INT 09h hook (programs that compute without
  reading keys), M: from the resident, the EMS swap of the UI block.
