# Pictures on the GRiD: gridfox's picture view and Claude Code's plots

Planned and built 2026-10-17, after W1 (gridfox, text view) and the mouse (PR #32) ran on the 1520.
Tested in emulation and against stand-ins; not yet on the 1520 and the Pi.

## What Joshua asked for
- **A dithered picture mode for gridfox:** the whole browsing experience, the page as Firefox draws it.
- **Claude Code showing plots on the GRiD that he can click on.**
- Both should share code.

## Decided (Joshua, 2026-10-17)
1. **Clicks on a plot: both.** Your clicks type the point into Claude Code's prompt, not sent, and Claude can ask you to pick points with `grid_pick`.
2. **The pointer is always on in Term**, `/T` included. A click does nothing unless a picture is up or the program asked for mouse reports.
3. **gridfox's text view stays the default.** One key (V) flips to the picture of the same page; Esc goes back.

## The shared part
Both are "the Pi draws a 640×384 one-bit picture and the GRiD shows it; a click
comes back in pixels". Only the source of the picture differs:

```
                    ┌ gridfox: Firefox's screenshot (OSC 5150) ─ dither ┐
Pi:                 ┤                                                    ├─ picture layer ─ encoder ─ CELLS frames ─┐
                    └ Claude Code: grid_plot (drawn in one bit) /        ┘   (what the GRiD shows,                   │
                                   grid_image (dithered)                      latest only)                          │ GPIB
GRiD: CELLS op FDh (a rectangle of pixels) ─ video memory; the pointer re-shown ◄───────────────────────────────────┘
      a click ─ EVENT 06h in pixels ─► Pi: to whoever owns the picture (gridfox, or Claude Code's plot)
```

### On the GRiD (CLAUDE.COM): 128 bytes
- **CELLS op `FDh`, pixels:** `y` (2), `x` in bytes (1), width in bytes (1), height in lines (1), then each line's bytes as PackBits.
  - CELLS used 00h–97h (runs and fills) and FEh (scroll), so FDh was free. An older CLAUDE.COM reads FDh as a fill on row 7Dh, which doesn't fit the screen, so the frame ends there: nothing breaks. The Pi sends pictures only to a CLAUDE that says it can, in HELLO flags bit 1 (`mov al, 1` became `mov al, 3`: no extra bytes).
  - Line y is in bank y mod 4, at (y div 4) × 80; the next line is the next bank, or bank 0 and 80 bytes on. The decoder copies with `rep movsb` / `rep stosb` straight into video memory.
  - Every rectangle is checked against rows 0–383 (a y near FFFFh too, which would wrap) and the payload, and each line's codes must make exactly its bytes; anything else ends the frame, as for the other operations. Nothing outside rows 0–23 can be drawn over: the emulator test checks all of B800:0000–FFFF.
  - **The plan's second coding (each line XORed with the one above) was left out.** It saved most on plots with full vertical grid lines; the plots here have none (1,601 points are 5.2 KB with PackBits alone), so it wasn't worth its bytes on the GRiD.
- **Scrolling reuses what is there:** CELLS's scroll op (FEh) moves rows of 16 lines, pixels and all. The Pi uses it when a picture moved up by whole rows.
- **No "picture mode" on the GRiD.** The Pi decides what is on the screen. While a picture is up it sends only pictures (the cursor hidden); pyte goes on keeping the text. Going back is a clear and the whole text. CLAUDE keeps no copy of a picture: no RAM for it.
- **Clicks in pixels:** EVENT 06h carries x and y as words; a new code, so an older gridlink ignores it rather than reading it as #32's EVENT 05h (column, row), which gridlink still takes.
- **The pointer in all of Term**, and only in Term: chat draws without hiding it. It comes on when Term starts (with `/T` or `/W`, or when the Pi picks Term); the reset clears presses made before.
- **The pointer is hidden while a frame is drawn**, then shown again. (#32 hid and showed it after: the kernel's hide puts back only bytes still as the pointer left them, and a new byte equal to one of those would have been undone.)
- **RCON (resident Claude) unchanged**: the op and the mouse are left out of it by `%ifdef`.
- **`grid=CLAUDE 1.2`** in the HELLO.
- **Size:** CLAUDE.COM 20,564 → 20,692 bytes, the same 128 in memory (the alignment before the font included).

### On the Pi (gridlink)
- **`picture.py`, the encoder:** keeps what the GRiD shows and sends only the difference.
  - The lines that changed, grouped into rectangles as wide as their changes.
  - A vertical shift, found by comparing 16-line rows, sent as a scroll op first.
  - Split to fit the bridge's frames (254 bytes, or 127 for the stock AR488); a line too wide for a small frame goes in pieces.
  - **Latest picture, never a backlog,** as for text: a frame counts as shown when the GRiD's next new frame arrives.
- **Dithering** (Pillow, in C: about 8 ms): grey to one bit with an 8×8 ordered (Bayer) pattern fixed to the screen. Near black and near white are thresholded, so text stays crisp. A fixed pattern keeps unchanged areas unchanged, and a 16-line scroll keeps it aligned.
- **The picture layer on the Term session** (`term.py`): `show_picture(bits, owner, on_click, on_key, title)` and `hide_picture()`. While a picture is up it is the link's frame source; clicks on it go to its owner; keys too, if it wants them. The band's title says what it is and how to leave ("Filter (Esc: back)").
  - After a RUN, CODE-R or Ctrl-L the GRiD has drawn its text copy (blank under a picture), so the Pi sends the picture again.

## Use 1: Claude Code's plots
Three MCP tools on the `grid` server. They only look, so they can be allowed for good:

- **`grid_plot`:** series of x/y (or y alone), or a Pi file in `~/grid` (CSV, numbers separated by spaces, one long line like an instrument's `CURVE 1,2,3`, or JSON). Title, axis labels, line / points / both, log axes, ranges, and `x_span` for data without x (an instrument's start and stop).
  - `plot.py` draws it in one bit at 640×384 with the GRiD's own 8×16 font (`gridfont.py`, from FONT.INC and GLYPHS.INC): lit lines on a dark screen, dotted horizontal grid lines, ticks but no vertical grid lines, SI labels (1.5G, 250m, 2µ), up to 8 series told apart by dashes and marks. 1,601 points draw in about 20 ms.
  - Claude gets the picture back as an image, as the GRiD shows it.
- **`grid_image`:** a picture file from `~/grid` (a matplotlib PNG, a screenshot), fitted and dithered. A mostly white picture is inverted, lit lines on dark. With `plot_area` (the axes box in the picture's pixels) and the axis ranges, clicks map to data too.
- **`grid_pick`:** asks the user to click points (the prompt in the band, "click the notch"), waits up to the time limit, and returns each click: data coordinates and, on a plot, the nearest point (series, index, x, y). Each click is marked on the picture. Esc cancels. Other tool calls are answered while it waits.
- **Your own click** types the point into Claude Code's prompt as a paste, not sent (control characters taken out, so a name in the data can't end the paste or press Return), and goes back to Claude Code: `[clicked plot "S21": Hz = 1.49756e+09, dB = -25.9; nearest point: S21 #800 (1.50015e+09, -25.7)]`. You add words and press Return.
- **Esc** goes back to Claude Code, which went on underneath.
- **The bench path:** `gpib_send`'s query with `save_to` (checked before anything is sent; `gpib_read` stays read-only) puts an instrument's reply (an 8753D trace, 1,601 points) in a new Pi file, without passing it through the conversation; `grid_plot` with `file` shows it; you click the notch.

## Use 2: gridfox's picture view (W2)
Details in `docs/gridfox.md`. In short:
- V: the viewport becomes 640×384; screenshots go to the picture layer through `OSC 5150` (a PNG in gridfox's folder; gridlink dithers it).
- Clicks are real clicks at that pixel (`WebDriver:PerformActions`); typing goes to the page; arrows and PgUp/PgDn scroll in whole rows; Ctrl-B/F/R back, forward, reload; F6 an address; Ctrl-I light or dark; Esc the text again.
- A screenshot after each action (at once, 0.5, 1.5, 4 s) and every 2 s while idle; only a changed one is sent.
- Pictures load in Firefox now (`--no-images` for the old way); text is drawn without antialiasing.

## Measured (emulation and models, 2026-10-17)

| Picture | Bytes to the GRiD | At 109 KB/s (Pico 2 bridge) | At 8 KB/s | At 3.2 KB/s (stock bridge) |
|---|---|---|---|---|
| A plot of 1,601 points, two axes, title and labels | 5,206 (254-byte frames), 5,436 (127) | 0.05 s | 0.65 s | 1.7 s |
| A pick's mark on it | 84 | under 0.01 s | 0.01 s | 0.03 s |
| A grey gradient, dithered | 683 | 0.01 s | 0.1 s | 0.2 s |
| gridfox, the stand-in's index page | 2,440 | 0.02 s | 0.3 s | 0.8 s |
| Its next screen (PgDn) / three rows down | 1,914 / 675 | 0.02 / 0.01 s | 0.24 / 0.08 s | |

- The stand-in Firefox's page is only text: a real page with photographs dithers into more, perhaps 10–25 KB for a new photo-heavy screen.
- The link through the Pico 2 bridge, measured on the 1520 (2026-10-23, `gridlink.bench`, GPIB driver 1.23, bridge fw 2026-10-23d, CLAUDE 1.7): 109.3 KB/s to the GRiD, with 6 ms round trips (claude-link/README.md has the table). Add a round trip to each figure in that column; drawing on the GRiD takes longer than the transfer now.

## Tests
- `claude-link/tests/test_picture.py` (18): PackBits; the encoder against a model of the GRiD's decoder at 254, 118 and 40-byte frames; scrolls; cells over pixels; malformed rectangles; dithering; plots, their clicks and labels; data files; the picture layer through GridSim (clicks, CODE-R, an old CLAUDE that gets no pictures, cell clicks from #32's CLAUDE); `grid_plot`, `grid_pick`, `grid_image` and `save_to` end to end through the MCP server; names with Esc and Return pasted harmlessly; a killed program's picture going with it; a tool answered while `grid_pick` waits.
- `claude-link/tests/test_emu_picture.py` (4): the real CLAUDE.COM in the emulator, its video memory equal to the Pi's picture bit for bit after plots, a text page, noise, a scroll, a blank, one byte at the last line; with the stock AR488's frames; ten malformed rectangles, one with a y that wraps (nothing drawn anywhere in B800:0000–FFFF outside rows 0–23, CLAUDE goes on); the picture back after RUN, CODE-R and Ctrl-L.
- `os/tests/test_claude_mouse.py`: under plain Term on the Lodestone kernel, a click through the serial mouse and INT 33h on a plot's point types it into the stand-in Claude Code's prompt.
- `claude-link/tests/test_gridfox.py`: the picture view, key by key and end to end.

## Later
- A scroll-down op, if scrolling back is slow.
- Zoom (Firefox's own, `layout.css.devPixelsPerPx`).
- Claude Code sharing the browser (W3), which can show its findings with the same layer.
- A native PLOT on the GRiD for data already there (the bench-app idea) stays separate and possible.
