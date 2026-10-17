# Pictures on the GRiD: gridfox's picture view and Claude Code's plots (plan)

Planned 2026-10-17, after W1 (gridfox, text view) and the mouse (PR #32) ran on the 1520.

## What Joshua asked for
- **A dithered picture mode for gridfox:** the whole browsing experience, the page as Firefox draws it.
- **Claude Code showing plots on the GRiD that he can click on.**
- Both should share code.

## The shared part
Both are "the Pi draws a 640×384 one-bit picture and the GRiD shows it; a click
comes back in pixels". Only the source of the picture differs:

```
                    ┌ gridfox: Firefox's screenshot ─ dither ┐
Pi:                 ┤                                         ├─ picture layer ─ encoder ─ CELLS frames ─┐
                    └ Claude Code: grid_plot / grid_image ────┘   (what the GRiD shows,                   │
                                                                    latest only)                          │ GPIB
GRiD: CELLS op FDh (a rectangle of pixels) ─ video memory; the pointer re-shown ◄────────────────────────┘
      a click ─ EVENT 05h in pixels ─► Pi: to whoever owns the picture (gridfox, or the plot's tool)
```

### On the GRiD (CLAUDE.COM): one CELLS operation, about 100–120 bytes
- **CELLS op `FDh`, pixels:** `y` (2), `x` in bytes (1), width in bytes (1), height in lines (1), a flag, then the rectangle coded as below.
  - CELLS today uses 00h–97h (runs and fills) and FEh (scroll), so FDh is free. An older CLAUDE.COM reads FDh as a fill on row 7Dh, which doesn't fit the screen, so the frame ends there: nothing breaks. The Pi sends pictures only to a CLAUDE that says it can, through HELLO flags bit 1 (no extra bytes: `mov al, 1` becomes `mov al, 3`).
  - **Coding, chosen per rectangle by the flag:** PackBits run-lengths of the bytes, or of each line XORed with the line above.
    - The GRiD undoes the XOR from video memory as it goes, with the 4-bank arithmetic Term already uses: line y is in bank y mod 4, at (y div 4) × 80.
    - Measured on three typical screens (below), the right choice saves up to three-quarters.
  - Every rectangle is checked against the screen (rows 0–383) and the payload, as CELLS operations are now.
- **Scrolling reuses what is there.** The CELLS scroll op (FEh) moves rows of 16 lines. A page scrolled in 16-line steps arrives as a scroll plus a 16-line strip: about 200 bytes for text.
  - Only scrolling up exists today. Scrolling back sends the strip at the top as pixels; a scroll-down op could come later if it's worth its bytes.
- **No "picture mode" on the GRiD.**
  - The Pi decides what is on the screen. While a picture is up, it sends no text frames; pyte goes on keeping the text screen.
  - Going back to text is a clear plus a full redraw: the Pi resets its text encoder, as for CODE-R.
  - CLAUDE keeps no picture memory, so a picture costs the GRiD no RAM.
- **Clicks in pixels:** EVENT 05h carries x and y as words, 4 bytes instead of the column and row. That drops the two shifts, so it is about the same size. gridlink tells the two apart by length (3 bytes: cells, from #32's CLAUDE).
- **The pointer in all of Term, not only under `/W`:** plots are under `/T`. Dropping the `/W` check saves 5 bytes; Claude Code still never sees a click unless a picture is up.
- After an FDh rectangle the pointer is hidden and shown again, through the code #32 added for CELLS.
- **RCON (resident Claude) unchanged,** as before: the new op is left out of it by `%ifdef`.

### On the Pi (gridlink): `picture.py`, the shared layer
- **A picture layer on the Term session** (Claude Code's or gridfox's):
  - `show(image, on_click)` and `hide()`;
  - while shown, it is the link's frame source instead of the text encoder.
- **The encoder** keeps what the GRiD shows (a 640×384 bitmap) and sends only the difference:
  - the lines that changed, grouped into rectangles;
  - a vertical shift found by comparing 16-line bands, sent as a scroll op;
  - each rectangle coded both ways, the smaller kept;
  - split to fit the bridge's 254-byte frames (127 for the stock AR488).
- **Latest picture, never a backlog,** as for text: a slow link means fewer pictures, not a queue. The rule that a frame counts as shown when the next one comes is Term's own.
- **Dithering** (Pillow):
  - grey → one bit with an 8×8 ordered (Bayer) pattern fixed to the screen;
  - text-like pixels (near black or near white) thresholded rather than dithered, so text stays crisp.
  - A fixed pattern keeps unchanged areas unchanged, so diffs stay small. Error diffusion would shimmer at every change.
  - A 16-line scroll keeps the pattern aligned (16 is a multiple of 8), so a scrolled area really is a moved one.
- **Clicks:**
  - EVENT 05h in pixels goes to the picture's `on_click(x, y)` while a picture is up.
  - Otherwise it becomes a cell, and the click goes to the pty as now (gridfox's text view).

## Use 1: gridfox's picture view (W2)
- **A key flips between text and picture views** of the same page. Firefox's viewport is set to 640×384.
- **The picture:** Firefox's screenshot (`WebDriver:TakeScreenshot`, viewport), dithered.
  - Pictures go on in Firefox's profile. The Pi's internet is fast; only GPIB is slow.
  - For crisper text, fontconfig settings for gridfox's Firefox only: antialiasing off, full hinting. That is untested.
- **A click is a real click at that pixel:** `WebDriver:PerformActions`, pointer move and click. Anything on the page answers it, not only the links the text view found.
- **Typing** goes to the page through `WebDriver:PerformActions` key actions, into whatever has focus.
  - A few keys stay gridfox's own: back, Go, the view key, Ctrl-Q.
- **Scrolling:**
  - PgUp, PgDn and arrows scroll the page by multiples of 16 pixels, so the encoder can send a scroll op.
  - The GRiD's arrow keys move the page.
- **Refresh:**
  - a new screenshot after each action (at once, then at 0.5, 1.5 and 4 s, like the text view's rereads);
  - while idle, at most one every 2 s, and only when the page changed (a cheap image hash on the Pi).
  - Animations and video play as fast as the link allows: a frame or two a second for a changing area, never a backlog.
- **The text view stays the default:** it is the fast one, and the picture view is a key away.

## Use 2: Claude Code's plots
- **Two MCP tools on the `grid` server** (look tools, so they can be allowed for good):
  - **`grid_plot`:** data in (series of x/y, or a CSV/JSON file on the Pi), with title, axis labels, line or scatter, log axes.
    - gridlink draws it itself in one bit, at 640×384, with the GRiD's own Terminus font: crisp lines, no dithering.
    - It knows the axes, so a click maps to data coordinates and the nearest point.
  - **`grid_image`:** any picture file on the Pi (a matplotlib PNG, a scope screenshot), dithered.
    - If Claude passes the plot area and axis ranges, clicks map to data coordinates too.
- **On the GRiD:**
  - The picture replaces Claude Code's screen until Esc, which goes back to Claude Code as it was. The band says so ("Esc: back to Claude Code").
  - Claude Code goes on in the background meanwhile.
- **Clicks** (both, decided below):
  - **(a)** a click types the point into Claude Code's prompt, not sent, e.g. `[S21 at 1.2345 GHz, -3.10 dB]`, and goes back to the text. You add words and press Return. It is your own click, so it is your input.
  - **(b)** `grid_pick`: Claude asks you to click ("click the dip you mean") and the tool waits for one or more clicks, with a time limit, and returns them.
- **The bench is the point:**
  - Claude reads an 8753D trace with `gpib_read` (1,601 points, a few KB, as now), shows it with `grid_plot`, and you click the notch to get its frequency.
  - The same works for a 7854 or 11403 waveform, or a DM5120 log over time.
- **The roadmap's rule** ("send numbers over the link, not pictures, unless only the Pi can make it") holds in spirit. A one-bit line plot is about 4 KB, under a second, and it costs the GRiD no plotting code. A native PLOT on the GRiD for data already there (the bench-app idea) stays separate and possible.

## Measured (sizes, 2026-10-17)
640×384, one bit, coded with PackBits, in a Python model of the encoder:

| Screen | Plain | Each line XORed with the one above | Kept | At 8 KB/s | At 15 KB/s |
|---|---|---|---|---|---|
| A text page (gridfox's own screenshot) | 5,170 B | 4,203 B | 4,203 B | 0.5 s | 0.3 s |
| A dithered picture (gradients and shapes) | 6,882 B | 10,361 B | 6,882 B | 0.8 s | 0.4 s |
| A line plot with a 9 × 7 grid | 16,645 B | 3,937 B | 3,937 B | 0.5 s | 0.3 s |
| A 16-line strip of text (one scroll step) | 194 B | | | 0.02 s | |

- **The link speed:** the Pico 2 bridge removed the Nano's serial limit, so the GRiD's polled 7210 loop sets the rate now.
  - It hasn't been measured on the 1520: **your THRUTEST results through the Pi will set these numbers.**
  - In emulation the kernel's fast path did 22.8 KB in 2.9 s (7.9 KB/s) with a 2 Mbaud bridge. The table assumes 8–15 KB/s.
- **Real photos** dither less tidily than the test picture: a full new photo-heavy page could be 15–25 KB, 1–3 s.

## Milestones
1. **P1, the shared base.**
   - GRiD: op FDh, pixel clicks, the pointer in all of Term.
   - Pi: `picture.py` (layer, encoder, dither) and a test pattern.
   - Tests:
     - pcemu, video memory against the Pi's bitmap bit for bit, in both codings, scrolls included;
     - GridSim with a bitmap model;
     - the kernel test with the serial mouse for pixel clicks.
   - Bench: THRUTEST numbers, and the time for a full picture and for a scroll.
2. **P2, Claude Code's plots.**
   - `grid_plot` and `grid_image`, with Esc back to the text and clicks as decided.
   - Tests: plot pixels against a reference, click to data point, the stand-in Claude Code calling the tools.
3. **P3, gridfox's picture view.**
   - The view key, screenshots, clicks and typing through Actions, 16-pixel scrolling, timed refreshes.
   - The stand-in Firefox can't draw (jsdom lays nothing out). Its screenshot will be a picture of its page text drawn with Pillow, enough for the pipeline. How real pages look is a bench check on the Pi.
4. **Later:**
   - a scroll-down op if scrolling back is slow;
   - zoom (Firefox's own, `layout.css.devPixelsPerPx`);
   - Claude Code sharing the browser (W3), which can show its findings with the same layer.

## Decided (Joshua, 2026-10-17)
1. **Clicks on a plot: both.** Your clicks type the point into Claude Code's prompt, not sent, and Claude can ask you to pick points with `grid_pick`.
2. **The pointer is always on in Term**, `/T` included (the smallest way: the `/W` check goes, 5 bytes saved). A click does nothing unless a picture is up or the program asked for mouse reports.
3. **gridfox's text view stays the default.** One key (V) flips to the picture of the same page and back.
