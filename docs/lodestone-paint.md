# Paint: a fast painter and BMP viewer for Lodestone (plan, 2026-10-21)

**Status:** a plan only; nothing is built yet. It was written on branch `worktree-paint-plan`, off main at 3a4235e (after #55).

**The ask:** Paint as a Lodestone application. It should be very fast, double as a BMP viewer, use little space, and reuse as much existing code as possible.

## 1. What "space" means here

| Budget | What it costs | Rule for Paint |
|---|---|---|
| **Resident:** LODE.SYS, the UI block, MEMSZ | Every DOS program loses it, for good | As close to **0 bytes** as possible. Every byte gets a number in the PR, as #51 did. |
| **ROM 2:** PAINT.RUN on R: | 128 KB shared with CLAUDE.COM and the other programs | Keep it small: v1 ≈ 3 KB on disk. |
| **PAINT.RUN's BSS and UI_ALLOC** | Memory only while Paint runs; given back when it ends | Spend it freely on speed: tables and buffers. |

Two rules hold throughout: speed is never traded for bytes without asking, and nothing resident is added without its cost in bytes and Joshua's yes.

## 2. The architecture

### The screen is the canvas
- **The picture is the whole 640 × 400 screen in mode 40h.** There is no title bar, band or tool strip on top of it.
  - Paint starts with `UI_CLS`, not `UI_SCREEN`.
  - `api_cls` clears `title_on`, and `clock_tick` checks `title_on` (UICORE.INC:1724), so the clock never draws into the picture. This was checked.
- **640 × 400 is exactly the kernel's Shift-PrtSc format** (`bmp_hdr` in KCORE.INC: 62-byte header, bottom-up, 80 bytes per line, bit 1 = lit). So every `SCREENnn.BMP` opens 1:1, and Paint's files are captures.
- Tools, help, and the forms for names appear as **UI windows** (`UI_WOPEN`, `UI_HELP`, `UI_FORM`). The core's save-under puts the picture back when they close.

### Two 32,000-byte buffers, kept in file order
Paint allocates two buffers with `UI_ALLOC`, 2,000 paragraphs each:
- **C, the committed picture:** what the screen shows between strokes.
- **U, the undo copy:** the picture before the last stroke.

Both hold the picture **in BMP file order**: line 399 first, 80 bytes per line, lit = 1. That makes C the file body itself.

| Operation | How it works |
|---|---|
| **Stroke start** (button down, or Return in a key-driven shape) | Swap the two pointers, so U is the picture before this stroke. This is free: C still has the old picture, and U already holds the same picture. |
| **During the stroke** | Draw on the screen only. C is scratch space now (flood fill's mask, §4). |
| **Stroke end** (button up) | Copy the screen into C: 400 × `rep movsw` 40, about 10 ms. |
| **Undo (CODE-Z, or U)** | Swap U and C, then copy C to the screen. Pressed again it is redo, as in MacPaint. |
| **Screen saver** | The core calls Paint's redraw routine afterwards, which copies C to the screen. No checkpoint timer is needed, because C always holds the committed picture. |
| **Band in use** (`UI_MSG` / `UI_ASK`) | Afterwards, copy C's lines 360–399 back. No 3.2 KB band buffer is needed. |
| **Save** | `3Ch`, then two writes: the 62-byte header and C (32,000 bytes). The kernel writes straight to disk, so big writes matter: one write per line cost 94 s for the capture. |
| **Load** (native 640 × 400, 1-bit, bottom-up) | One `3Fh` reads the file straight into C (after reading the header), fixes the polarity if needed, then copies C to the screen. A top-down file, or any other size, goes through U (§4). |

If the second buffer can't be allocated (MT with a small region, a TSR in the way), Paint runs without undo **and without flood fill**, which needs U (§3), and says so once.

**The band after the saver (checked, UICORE.INC:595 and :1810):**
- `redraw_all` calls the program's redraw routine first, then `band_redraw`, then the open windows.
- `band_redraw` always fills lines 360–399 with an inverse band, even when `band1` and `band2` are 0. So after the saver the band lands on the picture.
- **The fix costs 0 resident bytes:**
  - Paint's redraw routine copies C to the screen and sets a flag.
  - Paint's loop sees the flag after `UI_POLL` and the other calls that wait (`UI_EVENT`, `UI_HELP`, `UI_FORM`), and copies C's lines 360–399 back. If a window is open, this waits until it closes.
  - The band shows for a few milliseconds.
- The alternative is a core guard ("no band when both lines are 0", about 10 B resident, API 7). It would change how a program that sets a blank band redraws, so it is not proposed.

**Invariants:**
- **What goes into C:** a commit (screen → C) happens only with the pointer hidden (INT 33h function 2) and no window open. Otherwise the pointer or a window would end up in the picture.
- **The core's arrow:** the core shows its own arrow inside `UI_EVENT`, `UI_MSG`, `UI_ASK`, `UI_HELP` and `UI_FORM`. Paint calls function 2 before any of them, so two pointers never show, and function 1 after.
- **Moving the tool window:** dragging a window by its title strip (`win_ev`) works only inside `UI_EVENT`, not `UI_POLL`. While the tool window is open, Paint waits in `UI_EVENT`.

**Under MULTITASK=1:** Paint writes video memory directly. In the background it is frozen like any direct-writing DOS program, as the approved multitasking design does.

### The mouse: INT 33h, no core change
`UI_EVENT` and `UI_POLL` report only left-button presses. A painter also needs motion, releases and the button state. The core's own INT 33h driver already provides them:
- `int33_ui` is installed at start-up (`m33_hook`), and `mouse_isr` calls `m33_pkt` on every packet, whoever is running.
- **Function 0** in the UI's context leaves `mbase` alone (it calls `mouse_on` only when the mouse is off) and resets the virtual screen to 0–639 × 0–399 in mode 40h (`m33_maxy`).
- **Function 0Fh with CX = DX = 8** makes motion 1:1, as the Executive's pointer moves. The default is half speed vertically.
- **Function 3** returns the position and buttons.
- **Functions 1 and 2** show and hide the driver's own mode-40h pointer. Paint hides it around each piece of drawing, so the pointer never ends up in C.
- **Function 9** sets the pointer's shape, so each tool can have its own pointer (crosshair, pencil, eraser box) at no core cost.
- **Under MULTITASK=1,** `mt_i33` passes calls from the front task straight through (KMT.INC:1627). Paint runs in the Executive's task, so it uses the driver directly. One test (§8) checks that switching away and back while Paint holds the driver keeps `mt_33ot` / M4c's "another driver" logic right.
- **Paint's own loop** is `UI_POLL` (keys, saver, Shift-PrtSc, the CODE-Tab hot key), then function 3, then HLT. On exit it calls function 2 and then function 0, so the Executive starts with a clean driver. One known cosmetic effect: the Executive's arrow comes back where it was before Paint ran, because the UI's own position isn't reachable through the API.
- **Fallback, only if a check in §8 fails:** a `UI_MOUSE` API entry (about 15 B resident, API 7). It would be put to Joshua with the byte count first.

### Reuse map

| Need | Reused from | Cost |
|---|---|---|
| BMP header, bottom-up line order, palette | KCORE.INC `bmp_hdr` / capture `.row` loop (copied into PAINT.RUN, 62 B + loop) | 0 resident |
| Line-to-offset mapping, `NEXTROW` | UICORE.INC `row_di`, `NEXTROW` macro | 0 |
| Fast branchless Bresenham | SPLASH.ASM's nail loop (vectors set up first, no per-pixel direction test; 1.47 s → 252 ms there) | 0 |
| Byte-aligned fills/erase, frames of windows | `UI_FILL`, `UI_INVERT`, `UI_VLINE` | 0 |
| Pointer, buttons | the core's INT 33h (MOUSE33.INC) | 0 |
| Help window | `UI_HELP` from Paint's key table (help can't drift from keys) | 0 |
| File name prompt | `UI_FORM` (one text field) | 0 |
| Errors in words | `UI_SBERR` + `UI_MSG` | 0 |
| Text tool (v2) | `UI_PUTSN` with the screen font (GRiD's or TERMINUS) | 0 |
| Opening `.BMP` from the Executive | `kinds` table + the existing "Write opens it" path, generalised | ~30 B resident (§6) |
| Build | `mkrun.py`, `RUN_API equ 6` (no new API needed) | 0 |

## 3. The speed design ("hyper fast")
Every inner loop works on whole bytes or words where it can, and on the screen in place. Nothing is drawn twice.

- **A line table in BSS:** 400 words, `y → bank offset`, filled at start from `row_di`'s formula. A pixel costs one table read, a mask read (an 8-byte `80h >> n` table) and one `or`/`and`/`xor` on `es:[di+bx]`. Lines step with `NEXTROW` and never recompute.
- **One drawing op as two masks, with no code patching:** every write is `and [es:di], ah` then `xor [es:di], al`.
  - For a pixel with bit b, AH = ~(b & A) and AL = b & X, where (A, X) is (FFh, FFh) for ink, (FFh, 00h) for erase or the right button, and (00h, FFh) for XOR (rubber band, invert).
  - A pattern span uses A = FFh and X = the pattern's byte.
  - So one loop serves every op, with no test of the mode per pixel.
  - Patching the opcode (self-modifying code) was rejected: unicorn, under pcemu, keeps a stale translation of code it has already run (found in M4a), so the tests would only ever exercise the first op.
  - If the line target in the table below is missed, the fallback is three copies of the line loop, chosen by an indirect jump once per stroke (about +60 B in PAINT.RUN).
- **Spans are the workhorse:** `span(x0, x1, y, pattern byte)` handles the left edge mask, then `rep stosw` across the middle, then the right edge mask. Filled rectangles, ellipses, the eraser, thick brushes and flood fill all go through it. Patterns are 8 rows of 8 bits: the span's byte is `pat[y & 7]`, written `(screen & ~m) | (pat & m)`. Solid black and white are just two of the 8 patterns.
- **The pencil and brush** draw a Bresenham segment from the last sample to this one. The 1,200-baud mouse gives about 40 packets a second, so fast strokes would otherwise have gaps. Each segment hides the pointer once, draws, and shows it once.
- **Rubber bands** (line, rectangle, ellipse) draw in XOR: draw, then on the next sample undraw and draw again. The figure is drawn in ink only on release. The canvas is never copied for a preview.
- **Rectangles:** pixel-exact edges come from span (top, bottom) and a one-column vertical pass (sides). The core's `UI_BOX` / `UI_FILL` work in byte columns, so they serve only the byte-aligned fast path. `xor_rect` is internal to the core and is being changed on `claude/ui12-xor`, so Paint doesn't depend on it.
- **Ellipses:** midpoint algorithm, integer only, 4-way symmetry. Filled ellipses emit one span per line pair.
- **Flood fill (v2):** a scanline fill that reads **U** (the picture before the stroke, so a pattern fill can't leak into itself) and marks visited spans as bits in **C**, which is scratch during the stroke. A 2 KB explicit seed stack lives in BSS; on overflow it falls back to rescanning. Then one pass applies `screen = (screen & ~mask) | (pattern & mask)` a byte at a time, and the stroke ends as usual (screen → C).
- **Blits:** C → screen and screen → C copy 400 lines of `rep movsw` 40, with the line table, about 10–15 ms. Loading inverts the polarity once, in C, if needed (32,000 bytes `not`), so the blit is a plain move.

**Targets, measured in pcemu's 286 model (`pc.us`) in the tests:**

| Operation | Target |
|---|---|
| Full-screen blit | ≤ 15 ms |
| Commit at stroke end | ≤ 15 ms |
| A 640-pixel line | ≤ 2 ms |
| Full-screen filled rectangle with a pattern | ≤ 15 ms |
| Flood fill of an empty screen | ≤ 150 ms |
| Load of a 32,062-byte BMP on the real-floppy model | disk-bound: one read, no per-line DOS calls |

## 4. The BMP viewer
- **Started on a file** (from the Executive's Return on a `.BMP`, or `PAINT.RUN NAME.BMP` with SI = the path), Paint loads the file and shows it full screen in **View**:
  - clicks don't draw;
  - Esc goes back to the Executive;
  - Return, or any tool key, starts editing;
  - PgDn / PgUp step to the next or previous `.BMP` in the same directory (v2), for flipping through `SCREENnn.BMP` captures.
- **The 1-bit file checks (v1)**, done before anything is read into C. Anything else gives "Not a picture Paint can show" through `UI_MSG`, and nothing is touched.
  - `'BM'`;
  - `biBitCount` = 1;
  - `biCompression` = 0;
  - width 1–640 and |height| 1–400;
  - `bfOffBits` inside the file.
- **Reading the file:**
  - Use `bfOffBits`, not 62.
  - Line stride = `((w + 31) / 32) × 4`.
  - A negative height means top-down: the line step is flipped.
  - A smaller picture is centred on a dark screen.
  - **Polarity: dark paper by default** (Joshua, 2026-10-21).
    - A file with the kernel's own palette (dark red, then orange: Paint's and Shift-PrtSc's files) is shown exactly as saved. That keeps the start-up picture's lit paper, and every capture, as they were.
    - Any other 1-bit file: the colour covering more of the picture is shown dark. The lit bits are counted with a 256-entry table built in BSS, about 30 ms. So a Windows black-on-white file shows as lit ink on dark paper.
    - **I** inverts the view and the picture.
    - Cost: about 50 B in PAINT.RUN (palette compare, count, invert, the I key), 0 resident.
  - Files that aren't exactly 640 × 400, and top-down files, are read through **U** in pieces and placed into C one line at a time. A native-size bottom-up file reads straight into C.
- **Option V2, deeper colour (a decision for Joshua, §9):** 4-, 8- and 24-bit uncompressed BMPs.
  - Each pixel's luma (`(77R + 150G + 29B) >> 8`, a 256-byte table from the palette for 4/8-bit) is compared with a 4 × 4 Bayer threshold (16 bytes) fixed to the screen. This is the ordered dither the Pi uses for gridfox pictures, scaled down.
  - Larger pictures are **fitted** by nearest-line and nearest-pixel steps (a DDA while streaming), keeping the aspect ratio.
  - Estimated +500 B in PAINT.RUN, 0 resident. A 640 × 480 24-bit file is 922 KB, so on a floppy it is disk-bound (tens of seconds); from C: or M: it is quick.
  - RLE-compressed BMPs stay refused.

## 5. Tools and keys (GRiD conventions, as Write's)
- **The tool window** opens with Tab or the right button held on an empty spot. It is a `UI_WOPEN` window with `WF_MOVE | WF_CLOSE`, listing one tool per line with its letter, the current tool inverse. It closes on a choice, Esc or its close box. The pointer's shape shows the tool while the window is closed.
- **v1 tools:**

  | Key | Tool |
  |---|---|
  | P | Pencil |
  | B | Brush, sizes 1–4 with `[` `]` |
  | E | Eraser (also: the right button with any tool) |
  | L | Line |
  | R | Rectangle |
  | F | Filled rectangle |
  | 1–8 | Pattern |

  Shift held while drawing constrains: lines to 45° steps, rectangles to squares.
- **v2 tools:**

  | Key | Tool |
  |---|---|
  | O | Ellipse / filled ellipse |
  | K | Fill (flood) |
  | T | Text, through `UI_EDIT` at the click: rows round to 4 lines, columns to bytes |
  | S | Select: then move, copy (CODE-D duplicate, as Write), flip, invert |
  | Z | Zoom 8×, MacPaint's FatBits, built on the same span routine |

- **Commands:**

  | Key | Command |
  |---|---|
  | CODE-T | Transfer (save; asks a name if the picture has none) |
  | CODE-Q | Quit (`UI_ASK` if there are unsaved changes) |
  | CODE-Z or U | Undo / redo |
  | CODE-E | Erase all (undoable) |
  | I | Invert all |
  | F1 / CODE-? | Help (`UI_HELP` from the key table) |
  | Esc | Quit when nothing is unsaved, else ask |

- **Keyboard drawing:** arrows move the pointer by 1 pixel (Ctrl: 8), and Space acts as the button. Paint stays usable without a mouse, and the tests can drive it without packets.

## 6. Resident changes (the only ones)
1. **The Executive opens `.BMP` with Paint.**
   - `kinds` gets `'BMP', k_picture - k_file, 4`, and `k_picture db 'Picture', 0`.
   - `confirm`'s `.write` branch becomes "opener ≥ 3: path the file, SI = `[apps + 2·(AL − 3)]`", with `apps dw s_write, s_paint` and `s_paint db 'PAINT.RUN', 0`.
   - About **30 B** in the UI block, so `ui_keep_end` moves by about 2 paragraphs and MEMSZ by about −0.03 KB. The exact numbers go in the PR, and the MT branches get the new OFF_MAP pins.
   - `kind_of`'s other callers (EXEC.INC:541, 2714, 2780) only show the kind's string, so opener 4 doesn't affect them. This was checked.
2. **An Executive hot key (optional, §9):** CODE-G "Paint", one `KEY()` entry, a help line and a 4-byte handler, about **45 B**. CODE-P is taken (the command prompt). CODE-G is free in `ex_keys`, and the help has room (14 of 18 lines used).
3. **Nothing in the kernel, and no new UI API.** RUN_API stays 6, so PAINT.RUN runs on 0.6's LODE.SYS too.

## 7. Delivery: one PR each, every one paneled before it's reported

| PR | Contents | PAINT.RUN (estimate) |
|---|---|---|
| **P1** | Viewer + core painter: the INT 33h loop; the C/U buffers; the line table; span / line / pixel with the patched op; pencil, brush, eraser, line, rectangles, patterns; undo; save / load 1-bit; View mode; keys and help; the Executive `.BMP` opener | ≈ 3.0 KB file + ≈ 1.3 KB BSS (+ 64,000 B UI_ALLOC while running) |
| **P2** | Ellipse, flood fill, text, select / move / copy / flip, zoom | +≈ 1.5 KB |
| **P3** | (if chosen) 4/8/24-bit viewing with dithering and fitting; PgUp / PgDn through a directory's BMPs | +≈ 0.6 KB |
| **ROM** | PAINT.RUN on ROM 2 with CLAUDE.COM (the ROM 2 work), and in `releases/` | |

## 8. Tests (`os/tests/test_apps.py`, group `t_paint`; each fix mutation-checked)
- **Mouse checks first, before any painting code relies on them:**
  - INT 33h function 0 / 0Fh / 3 from a `.RUN` leaves the mode, `mbase` and the screen alone;
  - packets move function 3's position 1:1;
  - the buttons show on press and release;
  - after exit the Executive's pointer and list are as before.
  - With `MULTITASK=1`: Paint in front, CODE-Tab away and back, and `mt_33ot` and the background task's own mouse are still right.
  - A `mouse=False` run uses keyboard drawing.
- **Bit-for-bit drawing:** injected packets (and keyboard strokes) against a Python reference model (Bresenham, spans, patterns, ellipse, fill) that renders the same integer rules, as `mksplash.render` does for the splash. All 256,000 pixels are compared.
- **Round trip:** Shift-PrtSc's `SCREEN01.BMP` → Paint → CODE-T → the bytes are identical to the capture. A Pillow-made 1-bit BMP shows exactly as Pillow reads it.
- **Viewer edge cases:**
  - top-down;
  - odd widths (stride padding);
  - smaller than the screen (centred);
  - inverted palette;
  - `bfOffBits` ≠ 62;
  - refused files: 4-bit (until P3), RLE, a truncated file, width 641, height 0, `bfOffBits` past the end. Each must give the message and leave the screen and memory unchanged.
- **State:**
  - undo and redo after each tool;
  - the screen saver mid-session: the whole screen equals C afterwards, lines 360–399 included (the band repair), also with the tool window open during the saver;
  - only one pointer ever drawn; C never holds a pointer or window pixel;
  - every op (ink, erase, XOR, pattern) exercised in one session, so stale translated code can't hide a wrong op;
  - `UI_MSG` / `UI_ASK` restore lines 360–399;
  - Esc with changes asks;
  - only one buffer allocated → no undo, and still correct.
- **Speed:** the §3 targets as `pc.us` checks, so a slower change fails the suite.
- **Pins:** MEMSZ and OFF_MAP as moved by §6 only. The README's check count goes up.

## 9. Decisions for Joshua
1. **Deeper-colour BMPs (P3):** 4/8/24-bit dithered and fitted, +≈ 0.6 KB in PAINT.RUN and 0 resident? Or 1-bit only?
2. **CODE-G "Paint" in the Executive:** +≈ 45 B resident? Without it, Paint starts from its file in the list, or from a `.BMP`.
3. **Polarity:** decided, dark paper by default (§4).
4. **Undo memory:** 64 KB while Paint runs (both buffers). Without U, 32 KB and no undo.
5. **P2's scope:** decided after P1 is built.
