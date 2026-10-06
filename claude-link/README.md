# Claude for GRiD

Work with Claude from a GRiDCase 1520, Claude Code style: a conversation on
the GRiD's amber screen, Claude reading and editing files on the GRiD,
running DOS programs (and typing into them), taking screenshots, and talking
to the instruments on the GPIB bus, with a Yes / Always / No question before
anything that changes something.

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
echo 'sk-ant-...' > ~/.config/gridlink/api_key; chmod 600 ~/.config/gridlink/api_key
venv/bin/python -m gridlink --console      # chat in the terminal, no GRiD needed
sudo systemctl enable --now gridlink        # then leave it running
```

The API key comes from the Claude Console (console.anthropic.com); usage is
billed per token. `/cost` shows the session's running total.

### 3. The GRiD

Copy `CLAUDE.COM` to the floppy, then:

```
GRIDGPIB
CLAUDE          (or CLAUDE /A:nn if the bridge is not at address 7)
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

- `gridlink/` - the Pi service (Python 3.9+, `anthropic`, `pyserial`, `pillow`)
- `PROTOCOL.md` - GLP 1, the link protocol, including why it works the way it does
- `AR488-gridlink.patch` - the optional AR488 patch
- `CLAUDE.ASM` / `GLYPHS.INC` (Grid-OS source tree, `gridos/claude/`) - the
  GRiD program, NASM; `build.sh` / `BUILD.BAT` there make CLAUDE.COM,
  CLAUDE.MAP (symbols for the emulator) and TESTKEY.COM
- `tests/` - `test_e2e.py` (Python model of the GRiD side, fast) and
  `test_emu.py` (the real CLAUDE.COM and GRIDGPIB.COM in an x86 emulator:
  `grid_emu.py`, with `sim7210.py`, `ar488_model.py`, `fake_anthropic.py`).
  `python3 tests/test_emu.py shots/` also saves every screen as PNG + text.
  Needs `unicorn` and `pillow`; `bin/GRIDGPIB.COM` is the driver it loads.

## Status

Version 0.1, tested in emulation, not yet on hardware. The real CLAUDE.COM
(11 KB) runs under an emulated DOS 3.30 with the real GRIDGPIB driver,
talking through the 7210 and AR488 models to the real gridlink with a
scripted Claude: 20 scenarios pass (connect, chat, read, edit with Yes and
No, a DOS program driven by a key script with a screenshot, captured DOS
output, GPIB query/write/scan, 22.8 KB each way, damaged frames, stock
bridge, interrupt, queued prompt, 200-line scroll-back, long prompt and
history, link loss and reconnect, quit to DOS, CLAUDE.MD, help, slash
commands). Next: `--console` on the Pi with a real key, then the bench.
