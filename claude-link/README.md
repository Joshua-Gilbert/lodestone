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

The GRiD's tools (MCP server `grid`, in `~/grid/.mcp.json`). Seven only look,
and you can allow them for good ("Yes, and don't ask again"). Three change
something, and Claude Code asks before every call: they carry
`anthropic/requiresUserInteraction`, so it offers no "don't ask again" for
them, no allow rule skips the question, and not even bypassPermissions does.

| Tool | Asks | What |
|---|---|---|
| `grid_info` | until allowed | DOS version, drives, memory, EMS, GPIB driver, clock |
| `grid_files` | until allowed | list, info, read (up to 48 KB), free |
| `grid_screen` | until allowed | the last screenshot (text, or an image of a graphics screen) |
| `gpib_read` | until allowed | scan, serial poll, read (sends nothing; a poll clears the instrument's service request); `save_to` puts a reply in a new Pi file instead |
| `grid_command` | every time | run a DOS command or program; capture its output, or drive it with a key script (`1{ENTER}{WAIT 2}{SNAP}{ESC}`) and take a screenshot |
| `grid_change_files` | every time | write, delete, rename, mkdir, rmdir; copy_from_grid / copy_to_grid (edit a GRiD file with Claude Code's own tools: copy it over, edit, copy it back) |
| `gpib_send` | every time | query, write, clear, trigger, local/remote; a query's reply can go to a new Pi file (`save_to`) |
| `grid_plot` | until allowed | a line or scatter plot on the GRiD's screen, from data or a Pi file (a trace saved with `save_to`); drawn in one bit with the GRiD's own font |
| `grid_image` | until allowed | a picture file from `~/grid` (a matplotlib PNG), dithered to the GRiD's screen |
| `grid_pick` | until allowed | asks the user to click points on the plot or picture, and returns them (data coordinates, the nearest point) |
| `grid_program` | until allowed | resident Claude only: the DOS program its console is popped up over (its name and screen) |
| `grid_type` | every time | resident Claude only: keys into that program (`1A{WAIT 30}`); the console goes while they play and comes back with the program's screen |

While Claude Code is in resident Claude's console (CLAUDE /R, CODE-\ over a
program), only `grid_program` and `grid_type` run: the program holds the
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

Measured in the emulator (real CLAUDE.COM and GRIDGPIB on a 7210 model,
4 us per basic block, which is about a 10 MHz 286; whole turns including
the screen updates, 22.8 KB file):

| Bridge | Serial | Pi to GRiD | GRiD to Pi |
|---|---|---|---|
| patched | 115,200 | 4.4 KB/s | 7.9 KB/s |
| patched | 230,400 | 5.7 KB/s | 9.7 KB/s |
| patched | 500,000 | 6.8 KB/s | 9.7 KB/s |
| stock | 115,200 | 3.2 KB/s | 7.4 KB/s |

At 115,200 baud the Nano's serial line is the limit; above that the GRiD
itself is (GRIDGPIB spends about 60 us per byte, most of it in the
per-byte timeout bookkeeping). Raising `AR_SERIAL_SPEED` (and `baud` in
the config) is the cheap win; a fast path in GRIDGPIB's read and write
loops would be the next. Treat the numbers as +-30 % until the bench test.

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
