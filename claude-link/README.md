# Claude for GRiD

Work with Claude from a GRiDCase 1520: Claude reading and editing files on
the GRiD, running DOS programs (and typing into them), taking screenshots,
and talking to the instruments on the GPIB bus. Two ways, one link (and a
third use of it: `CLAUDE /W`, Firefox on the Pi as text, below):

- **Term (`CLAUDE /T`): the real Claude Code, on your Claude subscription.**
  The Pi (a Pi 5; Claude Code needs 4 GB) runs the unmodified `claude`
  program; the GRiD is its screen and keyboard. Only the screen cells that
  change cross the link. The GRiD's files, DOS programs, screen and GPIB bus
  are Claude Code tools through an MCP server. No API key.
- **Chat (`CLAUDE`): gridlink's own agent, on an API key.** A conversation
  in Claude Code's style, run by `gridlink` on the Pi (it fits a Pi 3), with
  a Yes / Always / No question before anything that changes something.

## Term: Claude Code on the GRiD

```
GRiD 1520 ── GPIB ── AR488 Nano ── USB ── Raspberry Pi 5 ── internet ── Claude (your plan)
 CLAUDE /T            (device, addr 7)      gridlink + the real `claude` in a pty
 screen, keys,                              pyte screen -> changed cells -> the GRiD
 GRiD tools                                 GRiD tools -> MCP server -> REQUESTs
```

Your subscription may only be used through the real Claude Code program,
not through something built on it; so in Term nothing sits between you and
`claude` but a terminal. Claude Code looks and works as it does anywhere
else: its prompt box, slash commands, permission dialogs, Shift-Tab modes.

On the GRiD: every key goes to Claude Code. CODE is Alt (Meta);
CODE-Return or Ctrl-Return starts a new line in the prompt; Esc, Ctrl-C,
Shift-Tab, the arrows and PgUp/PgDn do what they do in a terminal. Two keys
stay on the GRiD: **CODE-Q** quits, **CODE-R** redraws the screen. Row 25
shows the session's title and the link.

What crosses the link: about 15-20 bytes for a typed key or a spinner step,
100 for a line of a streamed answer, 500 for a whole first screen. The
real `claude`'s theme picker redraws 1.2 KB a keypress; 55 bytes of it reach
the GRiD. The emulator measures 48 ms of GRiD time from a key to its echo on
the screen, plus the Pi's own (about 20-25 ms on the simulated link, and
Claude Code's rendering).

The GRiD's tools (MCP server `grid`, in `~/grid/.mcp.json`). Eight only look,
and you can allow them for good ("Yes, and don't ask again"). Four change
something, and Claude Code asks before every call: they carry
`anthropic/requiresUserInteraction`, so it offers no "don't ask again" for
them, no allow rule skips the question, and not even bypassPermissions does.

| Tool | Asks | What |
|---|---|---|
| `grid_info` | until allowed | DOS version, drives, memory, EMS, GPIB driver, clock |
| `grid_files` | until allowed | list, info, read (up to 48 KB), free |
| `grid_screen` | until allowed | the last screenshot (text, or an image of a graphics screen) |
| `gpib_read` | until allowed | scan, serial poll, read (sends nothing; a poll clears the instrument's service request) |
| `grid_command` | every time | run a DOS command or program; capture its output, or drive it with a key script (`1{ENTER}{WAIT 2}{SNAP}{ESC}`) and take a screenshot |
| `grid_change_files` | every time | write, delete, rename, mkdir, rmdir; copy_from_grid / copy_to_grid (edit a GRiD file with Claude Code's own tools: copy it over, edit, copy it back) |
| `gpib_send` | every time | query, write, clear, trigger, local/remote; a query's reply can go to a new Pi file (`save_to`) |
| `grid_plot` | until allowed | a line or scatter plot on the GRiD's screen, from data or a Pi file (a trace saved with `save_to`); drawn in one bit with the GRiD's own font |
| `grid_image` | until allowed | a picture file from `~/grid` (a matplotlib PNG), dithered to the GRiD's screen |
| `grid_pick` | until allowed | asks the user to click points on the plot or picture, and returns them (data coordinates, the nearest point) |
| `grid_program` | until allowed | resident Claude only: the DOS program its console is popped up over (its name and screen) |
| `grid_type` | every time | resident Claude only: keys into that program (`1A{WAIT 30}`); the console goes while they play and comes back with the program's screen |

While Claude Code is in resident Claude's console (CLAUDE /R, CODE-\ over a
program), `grid_program` and `grid_type` run, and from CLAUDE 1.9 the file
and GPIB tools too (not where DOS is busy under the program: its own
disk-error handler, or Lodestone's tasks' key wait); `grid_command`,
`grid_info`, `grid_screen` and the pictures don't: the program holds the
GRiD. Outside it, those two say no program is paused. Once the user has
gone back to the program (CODE-\ again), every GRiD tool says so at once
until the console is up again.

GPIB queries ask too: a query is a command, and some (`MEAS?` and `READ?`
on a Keithley source-meter) switch a source's output on.

**Plots and pictures** (CLAUDE.COM 1.2, any Term): the picture replaces
Claude Code's screen until Esc, and Claude Code goes on underneath. Your own
click on a plot types the point into Claude Code's prompt, not sent, e.g.
`[clicked plot "S21": Hz = 1.5e+09, dB = -25.7; nearest point: S21 #800
(1.50015e+09, -25.6999)]`; you add words and press Return. Claude can also
ask you to click (`grid_pick`). The GRiD needs the mouse (the kernel's
INT 33h) for clicks; without one, plots still show. Details:
`docs/lodestone-pictures.md` in the Lodestone tree.

Limits the tools keep, whatever Claude asks for:

- **Pi files** (the copies) only inside `~/grid`, symlinks followed first;
  never a name starting with a dot (`.claude/settings.json`, `.mcp.json`)
  or `CLAUDE.md`. Only regular files with one link are sent to the GRiD; a
  copy from the GRiD replaces the name, never writes through a link there.
- **Sizes:** a copy or write is at most 1 MB (five minutes on the stock
  link); a read into the conversation 48 KB (Claude Code puts longer results
  in a file). Bigger is an error naming the size, never a file cut short.
  A program's output past 48 KB comes back as its start and its end, with
  how many bytes are left out between them.
- **Arguments** are checked before anything reaches the GRiD: GPIB
  addresses 0-30 (not 21 or the bridge), a command line of 100 characters,
  a `{WAIT}` of at most 600 s and a key script of about 2,000 keys, all
  waits together shorter than the timeout (at most 3,600 s), no DOS device
  names (`AUX`, `COM1`... would hang the GRiD), CP437 text without control
  characters. A malformed message gets an error, and the server goes on.
- `.mcp.json` starts Python isolated (`-I`), so nothing in `~/grid` is
  imported in place of gridlink's own code.

A Claude Code older than `requiresUserInteraction` asks for the four until
you allow them; to make it always ask, add to `~/grid/.claude/settings.json`:

```json
{"permissions": {"ask": ["mcp__grid__grid_command", "mcp__grid__grid_change_files", "mcp__grid__gpib_send", "mcp__grid__grid_type"]}}
```

### Setting up Term (Pi 5, 4 GB)

1. Raspberry Pi OS 64-bit (Bookworm), headless; turn on zram (`sudo apt
   install zram-tools`): 4 GB is Claude Code's minimum.
2. Claude Code, then sign in once with your plan, at the Pi's own terminal:
   ```
   curl -fsSL https://claude.ai/install.sh | bash
   claude                                  # sign in, pick the theme, /exit
   ```
3. gridlink as below (`install.sh` adds `pyte`). No API key is needed:
   without one, `CLAUDE` alone gives Term too.
4. Put a `CLAUDE.md` for the GRiD in `~/grid` (where Claude Code starts).
   gridlink writes `~/grid/.mcp.json` itself; the first time, Claude Code
   asks whether to use the `grid` server.

On the GRiD: `CLAUDE /T`. Settings: `[term]` in the config (`command`,
`dir`), and `[grid] app` for what `CLAUDE` without /T or /C gets.

## Web: Firefox on the GRiD (`CLAUDE /W`)

The same terminal path as Term, with `gridfox` in the pty instead of
`claude`: a headless Firefox on the Pi, driven through Marionette, each page
laid out as text at 80 columns. Links are underlined; Tab moves between
them, Return follows, F numbers them, G goes to an address or searches.
A new page is a few hundred bytes on the link. V shows the page as Firefox
draws it, dithered: clicks and typing go to the page itself (Esc: back to
the text). `sudo apt install firefox` on
the Pi; `[web]` in the config. Details: `docs/gridfox.md` in the Lodestone
tree.

## Chat: gridlink's own agent

```
GRiD 1520 ── GPIB ── AR488 Nano (device, addr 7) ── USB ── Raspberry Pi ── internet ── Claude API
 CLAUDE.COM                                                  gridlink
 screen, keyboard, GRiD tools                                agent loop, Pi tools
```

The GRiD stays the GPIB controller (address 21); your instruments share the
bus. The Pi runs the conversation with the Claude API, plus a Linux shell,
scratch files and web search for Claude to use.

Why the agent runs on the Pi rather than real Claude Code: Claude Code needs
4 GB of RAM and a 64-bit OS; the Pi 3 B+ has 1 GB. `gridlink` is a lean
re-creation of the parts that matter here, written for the Pi 3 and the
GPIB link.

## What Claude can do

| Tool | On | What |
|---|---|---|
| `str_replace_based_edit_tool` | GRiD and Pi | view, create, edit files (`A:\...` = GRiD, `/home/...` = Pi). DOS files stay CP437 with CR LF. Edits write `NAME.$$$` first and swap it in. |
| `grid_command` | GRiD | run a DOS command or program; capture its output, or drive it with a key script (`1{ENTER}{WAIT 2}{SNAP}{ESC}`) and screenshots |
| `grid_files` | GRiD | list, info, delete, rename, mkdir, rmdir, free space, copy to/from the Pi |
| `gpib` | GRiD's bus | query, write, read, serial poll, clear, trigger, local/remote, scan |
| `bash` | Pi | shell in `~/gridlink/work` (Python, plotting, nasm, downloads...) |
| `memory` | Pi | Claude's own notes, kept between sessions |
| `web_search`, `web_fetch` | Anthropic | datasheets, manuals, anything current |

Permissions: reading is free. Edits, DOS commands, file changes, GPIB
commands that are not plain `...?` queries, and Pi shell commands ask first.
`/mode edits` accepts file edits without asking; `/mode auto` asks nothing.

On the GRiD: Enter sends, Ctrl-Enter adds a line, Esc interrupts Claude,
PgUp/PgDn scroll, Up/Down recall prompts, F1 help, CODE-Q quits.
Slash commands (`/help`, `/clear`, `/compact`, `/model`, `/mode`, `/cost`,
`/status`, `/memory`, `/init`) go to the Pi. A file `A:\CLAUDE.MD` (or
CLAUDE.MD in the current directory) is read at the start of every session,
like Claude Code's CLAUDE.md; `/init` has Claude write one.

## Setting up

### 1. The bridge (Arduino Nano + AR488)

Flash AR488 to the Nano. Two choices:

- **Patched (recommended):** apply `AR488-gridlink.patch` to AR488
  0.53.46 (`src/AR488/AR488.ino` and `AR488_Config.h`). It makes the Nano
  raise SRQ by itself when a reply is fully in its buffer, keeps a reply
  that is still arriving instead of throwing it away, and doubles the
  buffer to 255 bytes. Builds to 24.8 KB flash, 1,312 bytes RAM (64 %) on
  a Nano. `++ver real` then ends in `+GRiD1`.
- **Stock AR488** also works: the Pi tells the GRiD how long to wait
  before reading each reply. It's slower (127-byte replies).

`gridlink` configures the rest itself (`++mode 0`, `++addr 7`, `++eos 3`,
`++eoi 1`, `++eot_enable 0`); `--save-bridge` stores it in the Nano's
EEPROM. Pick a free GPIB address; 7 is free on your bus.

### 2. The Pi

```
bash install.sh
nano ~/.config/gridlink/config.toml        # port, address, model, your bus
echo 'sk-ant-...' > ~/.config/gridlink/api_key; chmod 600 ~/.config/gridlink/api_key   # chat only
venv/bin/python -m gridlink --console      # chat in the terminal, no GRiD needed
sudo systemctl enable --now gridlink        # then leave it running
```

The API key (chat only) comes from the Claude Console
(console.anthropic.com); usage is billed per token. `/cost` shows the
session's running total. Term needs no key (see above).

### 3. The GRiD

Copy `CLAUDE.COM` to the floppy, then:

```
GRIDGPIB        (not on Lodestone: GPIB is built in; CODE-A in the Executive runs CLAUDE)
CLAUDE          chat (CLAUDE /T: Term; CLAUDE /W: Firefox; CLAUDE /A:nn if the bridge is not at address 7)
```

It connects, sets the GRiD's clock from the Pi, and shows the welcome.

## Speed

Measured on the 1520 (Lodestone, CLAUDE /T, the Pico 2 bridge), with
`python3 -m gridlink.bench` on the Pi: 128 KB copied each way through M:,
every byte checked.

| | Round trip | First call after idle | Pi to GRiD | GRiD to Pi |
|---|---|---|---|---|
| Before 2026-10-21 | 990 ms | up to 1 s | 3.0 KB/s | 5.7 KB/s |
| gridlink's read and hold fixes | 8 ms | up to 1 s | 22.7 KB/s | 43.0 KB/s |
| bridge fw 2026-10-21a, 2 KB frames to the GRiD | 8 ms | up to 1 s | 34.3 KB/s | 42.8 KB/s |
| 2 KB frames from the GRiD, the Fletcher sum (CLAUDE 1.3) | 7.0 ms | up to 1 s | 34.0 KB/s | 56.5 KB/s |
| bridge fw 2026-10-22a (bulk USB reads) and 22b (wake-up) | 7.0 ms | 51 ms median | 45.7 KB/s | 56.7 KB/s |
| SRQ on IRQ 5 (Lodestone's GPIB driver 1.21, CLAUDE 1.3) | 7.0 ms | 9 ms median | 44.9 KB/s | 56.7 KB/s |
| the driver's fast loops (1.22, GPIBLOOP) | 6.4 ms | 8 ms median | 70.2 KB/s | 73.3 KB/s |
| the driver's frame check (1.23, CLAUDE 1.4) | 6.0 ms | 8 ms median | 73.6 KB/s | 82.2 KB/s |
| bridge fw 2026-10-23a: EARLY answers (read while the rest crosses USB) | 6.0 ms | 8 ms median | 87.2 KB/s | 81.9 KB/s |
| CLAUDE 1.5: 8 KB write requests, the next frame straight after an answer | 6.0 ms | 8 ms median | 89.4 KB/s | 82.1 KB/s |
| bridge fw 2026-10-23c: held replies (the bridge answers the POLLs between fragments) | 6.0 ms | 8 ms median | 94.1 KB/s | 82.1 KB/s |
| CLAUDE 1.6: 3340-byte frames and 16 KB write requests | 6.0 ms | 8 ms median | 109.5 KB/s | 82.1 KB/s |
| CLAUDE 1.7: 3300-byte frames out of the GRiD and 16 KB reads | 6.0 ms | 8 ms median | 109.5 KB/s | 89.6 KB/s |
| bridge fw 2026-10-23d: held NOPs (checked by the bridge) | **6.0 ms** | **8 ms** median | **109.3 KB/s** | **91.1 KB/s** |

- **What was slow:** gridlink's Pico transport waited out a 20 ms read for
  every message. A REPLY was answered NOP at once, so the next request waited
  for the GRiD's 1 s idle POLL. The bridge read USB a byte at a time
  (106 KB/s; now 510 KB/s). The table CRC cost the 286 about 34 clocks a
  byte; the Fletcher sum costs 8.5.
- **The first call after idle:** CLAUDE POLLs once a second between
  messages. The bridge now raises SRQ when gridlink has news for an idle GRiD
  (WAKE, PROTOCOL.md), and CLAUDE POLLs at once. That left 51 ms: CLAUDE's
  HLT until the next timer tick. With the GPIB driver's SRQ interrupt (IRQ 5:
  Lodestone's built-in driver 1.21 and up, or GRIDGPIB 1.2) the SRQ itself wakes it,
  and the first call after idle takes 9 ms: a round trip and about 2 ms.
  gridlink rings only a GRiD that has read its last answer and been quiet
  for 50 ms, five times at most, then takes the SRQ back.
- **Code alignment matters on the 286:** it fetches words, and a jump to an
  odd address costs another fetch. When the kernel grew by an odd number of
  bytes, the GPIB driver's two fast loops moved by one, and a 2 KB frame into
  the GRiD took 30.0 ms instead of 27-28 (copies 42.7 / 54.8 KB/s). Two pad
  bytes keep them where they were measured fastest.
- **The driver's byte loops** (tools/GPIBLOOP.COM, 4 KB echoes, 1.0-1.6):
  both are CPU-bound, so every clock counts and a taken jump costs about
  0.6 µs. Reading went 70 -> 152 KB/s (the count in a register, END from the
  chip, the wait out of line), writing 77 -> 112 (no INC in memory per byte,
  the next byte fetched while the bus handshakes, a miss costing one jump).
  A 2 KB frame into the GRiD went from 28 to 13 ms.
- **The frame check** (CLAUDEP.COM, a profiling build of CLAUDE that
  times its pieces on the PIT and writes CLPROF.TXT): of the GRiD's 5 ms
  between 2 KB frames, the Fletcher pass took ~2.65 ms (1.3 µs a byte) and
  the frame copy ~0.7 ms. The GPIB driver (1.23) now keeps the sum as it
  moves the bytes, two ADDs a byte, and CLAUDE checks a frame from it and
  lets the driver append its own (copies are REP MOVSW now). The GRiD's
  time between frames went from 4.9 to 2.8 ms into the GRiD and from 4.8
  to 1.1 ms out of it.
- **Where a 2 KB frame's time goes**, on the bridge's own clock (fw 2026-10-23b
  stamps its events; `bench --trace`), so the GRiD is now the limit both ways:

  | Pi to GRiD | | GRiD to Pi | |
  |---|---:|---|---:|
  | GRiD reads it (TALK -> TX_DONE) | 14.5 ms | GRiD writes it (LISTEN -> RX_END) | 18.8 ms |
  | GRiD between frames (CLAUDE 1.5; 1.4: 2.9) | 1.4 ms | GRiD between frames (1.4: 1.3) | 1.0 ms |
  | USB, the reply's first 128 bytes | 1.0 ms | USB, the Pi's NOP | 0.6 ms |
  | SRQ, serial poll, addressing | ~1 ms | SRQ, serial poll, addressing | ~0.7 ms |
  | gridlink | 0.2 ms | gridlink | 0.1 ms |

  The GPIB time is the GRiD's byte loops (7 µs a byte reading, 9 writing,
  with the frame check). CLAUDE 1.5's 8 KB write requests halve the DOS
  open, seek and close per byte copied to the GRiD, and its next frame goes
  straight after an answer instead of after a round of its main loop (keys
  and the mouse were 0.27 ms of it). With bridge fw 2026-10-23a the bridge says an
  answer is ready once its first 128 bytes are in, so the ~4 ms of USB per
  2 KB frame overlaps the GRiD's read (21.6 ms a frame instead of 25.6).
- **Held replies** (bridge fw 2026-10-23c): while a message goes to the
  GRiD in fragments, its next frame is known to the byte: a POLL for the
  next fragment. gridlink hands the bridge that POLL and the answer to it
  along with each fragment. When the POLL comes, the bridge raises SRQ at
  its last byte and sends the answer itself; the USB trip to the Pi and back
  and gridlink's turn (~1.5 ms of each frame) are gone. Anything else (keys,
  a NAK, a REPLY) and the bridge drops it and gridlink answers as before.
  Measured: 94.1 KB/s into the GRiD against 89.5 with `--nohold`, 64 of a
  128 KB copy's 80 frames held (each 8 KB write request is five frames, and
  the GRiD's answer to the last is its REPLY, not a POLL).
- **Frames of 3340 bytes and 16 KB write requests** (CLAUDE 1.6): with 2 KB
  frames an 8 KB request took five, the last a few bytes long, and every
  frame costs the GRiD ~2.5 ms of SRQ, serial poll and addressing whatever
  its size. A 16 KB request is now exactly five full frames, and there are
  half as many requests (DOS open, seek and close) per file: 128 KB goes in
  40 frames instead of 80. Pi to GRiD went from 94.1 to 109.5 KB/s.
  CLAUDE 1.7 does the same the other way: 3300-byte frames out of the GRiD
  and 16 KB reads (the GRiD's HELLO says `rd=16384`; an older CLAUDE
  answers at most 16,382 bytes, so gridlink asks it for 8 KB). GRiD to Pi
  went from 82.1 to 89.6 KB/s.
- **Held NOPs** (bridge fw 2026-10-23d): out of the GRiD, the frame after a
  MORE fragment is the next fragment. Its payload isn't known, but gridlink's
  answer to it is a NOP either way. So the bridge gets that frame's first 4
  bytes and the NOP, and checks the rest itself, the length and the Fletcher
  sum, before it sends the NOP. It's the check gridlink makes, on the same
  bytes. GRiD to Pi went from 89.6 to 91.1 KB/s (3 of each 16 KB read's 5
  frames: the last one is answered with the next request, not a NOP).
- **The GPIB ceilings**, with no protocol: GPIBLOOP's loops, 152 KB/s into
  the GRiD and 112 out of it (119 unbounded). The 1.0 figures with the old
  loops (tools/GPIBXFER.COM) were 72-77 and 105. DMA isn't wired on the
  1520's GPIB cartridge.
- **The frame sizes** (2026-10-21, before the bridge's USB fix): 246, 512,
  1024, 2048 and 4096 bytes to the GRiD gave 22.7, 27.7, 31.1, 32.4 and
  33.1 KB/s. 2 KB frames get 98 % of 4 KB's rate for 1.8 KB less memory.
- `gridlink.bench`: `--sweep 246,1024,2048` tries frame sizes on the
  running link; `--trace` shows where each copy's time goes, gap by gap;
  `--usb` times the Pi to Pico USB alone; `--idle N` the first call after
  idle; `--nohold` turns held replies off, to compare. The AR488 Nano's figures, from the emulator, were 3.2-6.8 KB/s.

## Files

- `gridlink/` - the Pi service (Python 3.9+, `pyserial`, `pyte`, `pillow`; `anthropic` for chat).
  Term: `term.py` (the pty), `termscreen.py` (pyte, the cell diff), `router.py`
  (chat, Term or web), `mcp.py` (the MCP server and its socket). Pictures:
  `picture.py` (the encoder, dithering), `plot.py` (plots in one bit),
  `plotview.py` (what's shown and the clicks), `gridfont.py` (the GRiD's font)
- `gridfox/` - Firefox as text for `CLAUDE /W`: `marionette.py` (Firefox's
  remote control), `extract.js` / `act.js` (run in the page), `page.py`
  (80-column layout), `app.py` (the screen and keys)
- `PROTOCOL.md` - GLP 1, the link protocol, including why it works the way it does
- `AR488-gridlink.patch` - the optional AR488 patch
- `CLAUDE.ASM` / `GLYPHS.INC` (Lodestone source tree, `os/claude/`) - the
  GRiD program, NASM; `TERMLINK.INC` (the link), `TERMCELL.INC` (cells,
  Term's screen), `TERMKEYS.INC` (Term's keys) are shared with resident
  Claude's console (`RCON.ASM`, CLAUDE /R: Claude Code popped up over a
  DOS program, `app=resident`). `build.sh` / `BUILD.BAT` there make
  CLAUDE.COM (with RCON.BIN inside), CLAUDE.MAP and RCON.MAP (symbols for
  the emulator) and TESTKEY.COM
- `tests/` - `test_e2e.py` (Python model of the GRiD side, fast) and
  `test_emu.py` (the real CLAUDE.COM and GRIDGPIB.COM in an x86 emulator:
  `grid_emu.py`, with `sim7210.py`, `ar488_model.py`, `fake_anthropic.py`).
  Term: `test_term.py` (screen, encoder, keys, end to end with the GRiD
  model), `test_emu_term.py` (the real CLAUDE.COM /T), `test_mcp.py` (the
  MCP server); `fake_claude.py` stands in for Claude Code in a pty (no
  login, no model). Pictures: `test_picture.py` (the encoder, plots, the
  tools end to end), `test_emu_picture.py` (the real CLAUDE.COM, bit for bit).
  gridfox: `test_gridfox.py`, with `fake_firefox.py`, a stand-in Firefox
  (Marionette over jsdom; Node, and `npm ci` in `tests/`) serving
  `tests/web/`.
  `python3 tests/test_emu.py shots/` also saves every screen as PNG + text.
  Needs `unicorn` and `pillow`; `bin/GRIDGPIB.COM` is the driver it loads.

## Status

Version 1.1: Term. Tested in emulation (and the MCP server against the real
Claude Code's `claude mcp list`), not yet on the Pi 5: 18 Term checks with
the GRiD model, 8 with the real CLAUDE.COM, 13 for the MCP bridge (its
limits included). On the
Pi 5: a real Claude Code session from the GRiD, the echo, a permission
dialog answered on the GRiD, an MCP call that runs a DOS program.

Version 1.0 (chat), tested in emulation, not yet on hardware. The real CLAUDE.COM
(11 KB) runs under an emulated DOS 3.30 with the real GRIDGPIB driver,
talking through the 7210 and AR488 models to the real gridlink with a
scripted Claude: 20 scenarios pass (connect, chat, read, edit with Yes and
No, a DOS program driven by a key script with a screenshot, captured DOS
output, GPIB query/write/scan, 22.8 KB each way, damaged frames, stock
bridge, interrupt, queued prompt, 200-line scroll-back, long prompt and
history, link loss and reconnect, quit to DOS, CLAUDE.MD, help, slash
commands). Next: `--console` on the Pi with a real key, then the bench.
