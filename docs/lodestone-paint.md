# Paint: a fast painter and BMP viewer for Lodestone (plan, 2026-10-21; P1 built)

**Status:** P1 is built on branch `claude/paint`, rebased onto main at #132 (4411f75), and is on ROM 2. §10 says what was built and where it differs from the plan below. P2's scope is decided after P1; P3 starts with 4-bit BMPs.

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
- The alternative is a core guard ("no band when both lines are 0", about 10 B resident, a new API version). It would change how a program that sets a blank band redraws, so it is not proposed.

**Invariants:**
- **What goes into C:** a commit (screen → C) happens only with the pointer hidden (INT 33h function 2) and no window open. Otherwise the pointer or a window would end up in the picture.
- **The core's arrow:** the core shows its own arrow inside `UI_EVENT`, `UI_MSG`, `UI_ASK`, `UI_HELP` and `UI_FORM`. Paint calls function 2 before any of them, so two pointers never show, and function 1 after.
- **Moving the tool window:** dragging a window by its title strip (`win_ev`) works only inside `UI_EVENT`, not `UI_POLL`. While the tool window is open, Paint waits in `UI_EVENT`.

**Under MULTITASK=1:** Paint writes video memory directly. In the background it is frozen like any direct-writing DOS program, as the approved multitasking design does.

### The mouse: INT 33h, no core change
`UI_EVENT` and `UI_POLL` report only presses: the left button's, and since UI API 7 (PR #58) the right one's as `EV_RCLICK`, to a `.RUN` that needs API 7. Paint declares API 6 for now. A painter also needs motion, releases and the button state. The core's own INT 33h driver already provides them:
- `int33_ui` is installed at start-up (`m33_hook`), and `mouse_isr` calls `m33_pkt` on every packet, whoever is running.
- **Function 0** in the UI's context leaves `mbase` alone (it calls `mouse_on` only when the mouse is off) and resets the virtual screen to 0–639 × 0–399 in mode 40h (`m33_maxy`).
- **Function 0Fh with CX = DX = 8** makes motion 1:1, as the Executive's pointer moves. The default is half speed vertically.
- **Function 3** returns the position and buttons.
- **Functions 1 and 2** show and hide the driver's own mode-40h pointer. Paint hides it around each piece of drawing, so the pointer never ends up in C.
- **Function 9** sets the pointer's shape, so each tool can have its own pointer (crosshair, pencil, eraser box) at no core cost.
- **Under MULTITASK=1,** `mt_i33` passes calls from the front task straight through (KMT.INC:1627). Paint runs in the Executive's task, so it uses the driver directly. §8 planned a test that switching away and back while Paint holds the driver keeps `mt_33ot` / M4c's "another driver" logic right. Since W1 that case can't arise in a matched build (a LODEMT.SYS whose UI patches fail, or a core before API 8, would run Paint full screen on INT 33h): under MULTITASK=1 Paint is always a window session (a fifth window `.RUN` is refused, not run full screen) and takes its strokes by `UI_MOUSE`, never INT 33h, so the UI's own driver state is task 0's, which MT saves and puts back. `t_paintw` checks that instead (2026-11-03): CODE-F6, CODE-P (LCMD a full-screen task in front), CODE-Tab back, CODE-Tab to LCMD and back again (the switch's own save then), CODE-F6 to Paint: task 0's driver state as it was (its hot spot and masks made distinct first, LCMD's changed while it was in front), and a stroke drawn where the mouse went.
- **Paint's own loop** is `UI_POLL` (keys, saver, Shift-PrtSc, the CODE-Tab hot key), then function 3, then HLT. On exit it calls function 2 and then function 0, so the Executive starts with a clean driver. One known cosmetic effect: the Executive's arrow comes back where it was before Paint ran, because the UI's own position isn't reachable through the API.
- **Fallback, only if a check in §8 fails:** a `UI_MOUSE` API entry (about 15 B resident, a new API version). It would be put to Joshua with the byte count first.

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
| Text tool (v2) | `UI_PUTSN` with the screen font (Lodefont, or the .FNT chosen) | 0 |
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
- **P3, deeper colour: starts with 4-bit (16-colour) BMPs** (Joshua, 2026-10-21), about +0.3 KB. 8- and 24-bit files would follow later, for about +0.3 KB more. What the decoder does for every depth:
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
2. **An Executive hot key (optional, §9):** CODE-G "Paint", one `KEY()` entry, a help line and a 4-byte handler, about **45 B**. CODE-P is taken (the command prompt). CODE-G is free in `ex_keys`, and the help had room (14 of 18 lines used, before main's menus, #58 on).
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
  - With `MULTITASK=1`: strokes, the saver and Return on a `.BMP`. (CODE-Tab away and back: `t_paintw`, as above.)
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
1. **Deeper-colour BMPs (P3):** decided, 4-bit first (§4).
1a. **The Executive's `.BMP` opener:** decided, in P1 (Return on a `.BMP` opens it in Paint, about 30 B resident, §6).
2. **CODE-G "Paint" in the Executive:** left out for now (Joshua, 2026-10-21).
3. **Polarity:** decided, dark paper by default (§4).
4. **Undo memory:** decided, 64 KB while Paint runs (both buffers).
5. **P2's scope:** decided after P1 is built.

## 10. P1 as built (2026-10-21)

**Files:**

| File | What changed |
|---|---|
| `os/apps/PAINT.ASM` | → `PAINT.RUN`, built by `mkrun.py`, `RUN_API 6` |
| `os/src/EXEC.INC` | `'BMP'` is kind "Picture", opener 4; `confirm`'s Write branch takes opener 3 or 4 |
| `os/tests/test_apps.py` | `t_paint`, `t_paint_bmp`, `t_paint_more` |
| `os/tests/test_mt.py` | the `OFF_MAP` pin |
| `os/build.sh` | `PAINT.RUN` with the other `.RUN` programs, and on ROM 2 (`LODE2.BIN`) |
| `os/tests/test_rom.py` | `t_rom2`: ROM 2's files; `t_rom2_paint`: a `.BMP` on C: opened from the ROM |

**Sizes:**

| What | Size |
|---|---|
| `PAINT.RUN` on disk | 4,645 bytes (4,465 in P1; W0 added 180: the patterns twice over, 64, the canvas's limits, the parity pads) |
| Its BSS | 1.6 KB: the line table, the bit-count table, names |
| Memory while it runs | 2 × 32,000 bytes from `UI_ALLOC` |
| Resident | +32 bytes in the UI block: `ui_keep_end` 64C2h → 64E2h (on main at #132, 2026-11-02; 6164h → 6184h after #58, 6134h → 6154h before). The kernel's `image_end` / `bss_end` are unchanged. A pad after `confirm.x` (never run) makes the opener 10 bytes, so the Executive's code after it keeps its parity (9 bytes would have put `to_fcb`'s hot labels odd). |
| MEMSZ | Unchanged: 564.8 KB without EMS, 580.9 KB with it, on main at #132 (566.2 / 582.3 after #58). Paint's 32 bytes don't cross a rounding step. `test_mt`'s `OFF_MAP` pin is moved (64E2h). |

**W0 (2026-11-02), the preparation for Paint in a window (MULTITASK=1), nothing seen to change:**
- the patterns are kept twice over (16 bytes each), and `curpat` starts a fill at `pph` (0-7) into one, so that in a scrolled window a fill can follow the picture's lines, not the screen's (`pph` 0: as before);
- the canvas is `clx0`-`clx1` by `cly0`-`cly1` (0-639 by 0-399, the whole screen): `dot` cuts the brush and the eraser there, not at the screen's edges;
- a stroke's points come from `sample` (HLT, then INT 33h function 3, as before) and are clamped to the canvas by `clamp`, the press too (the driver keeps them on the screen anyway);
- the hot code on even offsets (the 286 fetches a word at a time): a pad (never run) before `plot`, `line`, `fillrect`, `frame`, `dot`, `band_fix` and `commit`, so each starts even wherever the code before it moves; `line`'s `xor bp, bp` is `mov bp, 0` (one byte more, as fast), so its loop's targets are even too; `EVEN` (EVEN.INC) stops the build if one goes odd. P1 had `line`, `fillrect` (its row loop, `.xor`, `.last`, `.put`) and `dot` odd. `fillrect.next` stays odd: even, the wide fills' path through `.last` would run a NOP each line, and it is a jump's target only for fills one byte wide;
- the speeds are as before: undo and the whole picture 15.0 ms, a stroke's end 15.0, a 640-pixel line 5.2, a full-screen box 22.6 (pcemu doesn't charge for odd targets; the 1520 does).

**Where it differs from the plan:**
- **The mouse: `UI_EVENT` between strokes, INT 33h only during one.**
  - Between strokes Paint waits in `UI_EVENT`, as every program does. So the core's arrow shows, the saver and the windows work, and under `MULTITASK=1` the core's idle point (`..@ui_idle`) is still where tasks switch.
  - A press (EV_CLICK) starts a stroke. Function 4 puts the driver's position where the press was, and function 3 then follows the position and button until it comes up (`sti` / `hlt` between samples). Functions 1, 2 and 9 aren't used, so there are no per-tool pointers.
  - Paint declares API 6, so it gets no right clicks yet: the right button doesn't erase (E does). Since UI API 7 (#58) the core can report it (`EV_RCLICK`), so a right-drag to erase is a step of its own.
  - Without a mouse, Paint shows pictures and takes every key, but has no keyboard drawing.
- **The band after the saver: a key of Paint's own.**
  - The redraw routine shows C, then, when Paint is in its own `UI_EVENT` (`in_ev`), puts `K_MEND` (FF00h) in the BIOS's buffer with INT 16h AH=05h. The wait ends at once and the main loop puts lines 360–399 back from C. It does that after every key and every dialog anyway.
  - It costs no resident bytes. If a BIOS has no AH=05h, the band only stays until the next key.
- **Drawing:**
  - `plot` and lines are solid; patterns are only for fills.
  - A 1-pixel line has its pixel inline (the `PIXEL` macro), with no call per point.
  - `fillrect` works out its edge masks once a box and fills the bytes between a word at a time.
  - `frame` is two one-line fills and the sides.
- **Loading:**
  - Every 1-bit file is read in one `3Fh` into U, then placed in C, so the native size isn't a special case.
  - Bits past the width are cleared.
  - Polarity: the kernel's own palette (exact bytes) keeps the picture as saved. Otherwise the lit bits are counted with a 256-byte table and, if more than half are lit, the picture is placed again inverted.
- **Saving** always writes 640 × 400 in Shift-PrtSc's format, through `NAME.$$$` and a rename, as Write does. A smaller picture saved over its own name grows to the full screen.
- **Not in P1:**
  - Shift to constrain lines and boxes;
  - an Open form inside Paint (pictures come from the Executive);
  - PgUp / PgDn through a directory.
- **The ROM:** `PAINT.RUN` is on ROM 2, the application ROM (decided 2026-10-23), not ROM 1: 14 sectors of R: (9 in P1, 10 after W0, 12 after W1). Started from the ROM, Return on a `.BMP` finds it through PATH (`C:\LODE;R:\`, a copy in C:\LODE first). With ROM 1 alone it says "PAINT.RUN is not on this disk" unless `PAINT.RUN` is in the subject or the PATH. `os/build.sh` builds it with the other `.RUN` programs; `t_rom2` and `t_rom2_paint` check it.

**Speed (pcemu's 286 model, checked by `t_paint_bmp`):**

| Operation | Time |
|---|---|
| The whole picture to the screen (undo, after the saver) | 15.0 ms |
| A stroke's end (the screen into C) | 15.0 ms |
| A 640-pixel line | 5.2 ms (10.3 ms before the pixel was inline) |
| A full-screen box with a pattern | 22.6 ms (27.0 ms with a call and masks per line) |

The copies are `REP MOVSW`, the floor. The checks allow 16, 16, 6 and 25 ms.

**During a stroke** Paint waits with HLT and doesn't call INT 16h. Under `MULTITASK=1` that means two things, both safe (the re-review checked):
- CODE-Tab is seen only when the button comes up.
- No other task runs while the button is down.

**Tests (89 checks; 3 more in test_rom's `t_rom2_paint` and 37 in test_mt's `t_paintw`, W1's and W2's, 129 in all):** `t_paint`, `t_paint_bmp` and `t_paint_more` cover:
- Every tool (pencil, line, box, filled box with patterns, brush, eraser, sizes) against `PaintModel`, a Python model with the same integer rules. All 256,000 pixels are compared, of C and of the screen (but for the pointer).
- Undo and redo; Invert; the tools' window (clicks, keys); help.
- The saver, with the band mended; Transfer byte for byte; Return on a `.BMP`, View, ESC and CODE-Q.
- Shift-PrtSc's picture round trip.
- Eight other programs' 1-bit files: polarity, top-down, odd widths, `bfOffBits`, a 124-byte header.
- Nine refused files; without a mouse; `MULTITASK=1` (strokes, the saver, the band).
- The four speeds.

**The review panel (three reviewers: the asm, the integration, the tests) found, all fixed with a test each:**
- **A key in the tools' window:** U, I or CODE-E ran before the window closed. The window's save-under then put back a patch of the old picture, which the next stroke committed into C. Now the window closes first.
- **The start-up hint swallowed** the click or key that dismissed it. Now that click starts a stroke, and the key goes to the key table. ESC, or a click on the band where the hint is, only dismisses it.
- **`K_MEND` typed ahead:** a key typed before the saver's end came out ahead of `K_MEND`, so `K_MEND` could reach the tools' window (closing it) or a form. Now `K_MEND` goes only into an empty buffer (INT 16h AH=11h first).
- **The redraw routine was set before the load**, so a failed load with the saver could show the uninitialised C. The failed-load exit also skipped the INT 33h reset. Both fixed.
- **The brush and eraser at the edges** were moved inward at the left and top, but cut at the right and bottom. Now they are centred and cut on all four sides.
- **A press right after the saver**, before the band was mended, would have committed the core's band into C (found by the re-review). Now the redraw routine sets `mend`, `band_fix` clears it, and a stroke mends the band first when it is set. Otherwise a stroke costs nothing extra. Tested with a poke.
- **Tests added:**
  - strokes past every edge;
  - Erase;
  - CODE-Q on a new picture (the name form);
  - a save that fails (read-only: the message, still in Paint, no `.$$$` left);
  - a picture in a subject;
  - the Executive's mouse after Paint;
  - the saver checks now assert that the core's `saver` actually ran;
  - the multitasking check asserts that INT 16h goes through MT;
  - refused files leave memory as it was.

**Not tested here:**
- the "Paint needs 63 KB" path;
- a failed load while the saver runs;
- a BIOS without INT 16h AH=05h (then the band stays until the next key).

**Mutation checks:** each of these mutations made at least one check fail:
1. no `K_MEND`;
2. no band repair;
3. never invert;
4. bits past the width kept;
5. top-down read as bottom-up;
6. a fill's edge ignoring A;
7. no commit;
8. a shown file drawing;
9. undo without the swap;
10. the rubber band not taken off;
11. the kernel's palette not recognised;
12. a short file accepted.

After the review, six more, each caught by its own new check:
1. the window closed after the key;
2. `K_MEND` behind a key typed ahead;
3. the hint's click dropped;
4. the dot moved in at the left and top;
5. a stroke ignoring `mend`;
6. a click on the hint's band drawing.

## 11. W1: Paint in a window (MULTITASK=1, 2026-11-02)

Joshua's decisions (2026-11-02): a 1:1 view of the 640 x 400 picture, scrolled; a window by default with the switch on, and a key to the whole screen and back (W2); `.BMP` files open in a window too; panning by a drag in the margin (W2); no cap on Paint windows; the first view centred.

**What it is:**
- `RUN_FLAGS equ RF_WIN`: with `MULTITASK=1` KMW starts Paint as a session, beside the other windows, from the list and from Return on a `.BMP` alike (the opener is unchanged). With the switch off nothing reads the flag: the whole screen, as before (`t_paint*`, and `MULTITASK=1` with no LODEMT.SYS). `RUN_API` stays 6.
- Paint asks `MT_WIN` at start, as Write does. In a session: `ses`; Transfer is CODE-X (`kt_xfer`, as Write's: CODE-T is the tasks'); the help gets the view's keys (two lines patched in, `kh_view`); `WIN_STAGGER` for a second Paint; strokes by `UI_MOUSE` (`umouse`, from UI API 8: an older core, INT 33h as before). No `UI_SETREDRAW` or `UI_CLS`: the window's `W_DRAW`, `w_draw`, draws the view.
- **The window:** column 2, row 32, 76 bytes by 328 lines (over the band), moved, resized and closed as any (`WF_MOVE`, `WF_CLOSE`, `WF_SIZE`); title "Paint", or "Paint: NAME.BMP" (in capitals, 8.3 as DOS keeps a longer name typed in Transfer; after Transfer the new name).
- **The canvas** is the window's inside (win_paint's): byte columns `W_COL + 1` to `W_COL + W_W - 2`, lines `W_Y + 20` to `W_Y + W_H - 2` (`geom`). At the smallest a window is resized to (24 x 72), 22 bytes by 51 lines.
- **The view:** `vx` bytes and `vy` lines into the picture, centred at first, kept inside it (`geom`). The arrows move it 16 pixels, PgUp and PgDn a canvas's height, Ctrl-Left and Ctrl-Right its width. The band: the hint, and "View: from X, Y of 640 x 400".

**Drawing in screen co-ordinates, as before.** `line`, `fillrect`, `frame`, `plot` and `dot` are W0's (and P1's), at their speeds:
- a stroke's points, the press too, are clamped to the canvas (W0's `clamp`), so every shape is inside it; `dot` cuts at it;
- a click on the window's frame or past the canvas starts no stroke (main's hit test; W2: a drag on the frame pans);
- fills follow the picture's lines: `pph` = (`vy` - the canvas's first line) mod 8 (W0's patterns twice over).

**C and U in a window.** The screen is no longer the whole picture, so a stroke's end can't copy it into C, and a swap at its start would leave C stale outside the view (copying the rest from U at the end took 26 ms, against 15 for the whole screen). Instead:
- **D**, the lines `dy0`-`dy1` and bytes `dx0`-`dx1` where C and U may differ, is kept;
- a stroke's start (`sync_u`) copies C into U in D only, so U = C (the picture before the stroke); D empty;
- its end (`commit_view`) copies the canvas into C at the view; D = the view;
- undo swaps them (still alike outside D); Erase and Invert make D the whole picture;
- the whole screen still swaps and copies the screen, as P1.

**The hot code even** (W0's rule): `blit_view`, `commit_view`, `sync_u` and their loops start even (pads never run; `commit_view`'s `MOV DI,0`, `MOV CL,40`, `sync_u`'s `IMUL` with a word: as fast, a byte more), asserted by `EVEN`. Copies to and from the screen put the screen's side on a whole word (`MOVSV`: a byte first if it is odd): a word across two costs the 1520's screen two accesses, RAM's side odd much less. (pcemu charges neither, and counts the extra test as a block: 12.1 -> 14.4 ms for the view there.)

**Speed** (pcemu, a 74 x 307 canvas): a stroke's start 12.1 ms (its last view's lines into U), its end 14.4 (the canvas into C), undo and the view 14.4; the whole screen's: 15.0 and 15.0.

**Size:** PAINT.RUN 6,035 bytes (4,645 after W0: +1,390), 12 sectors of ROM 2; its BSS 1,734 bytes. Resident: nothing (LODE.SYS, LODEMT.SYS unchanged).

**Memory:** each Paint is a slot (its image, BSS and a 2,560-byte stack) and 64,000 bytes from UI_ALLOC, as on the whole screen. No cap: a Paint that doesn't fit says "Paint needs 63 KB of memory".

**Not in W1:** the zoom key (CODE-F, the whole screen and back) and panning by a drag in the margin: W2 (§12); a stroke scrolling the view, still not.

**Tests (`t_paintw`, test_mt, W1's 25 checks):** Return on PIC.BMP: a session, the window, API 6 with RF_WIN, UI_MOUSE, the view centred, the canvas's place, `pph`; the title, C the file, the canvas C's view, the band; a drag on a picture shown draws nothing until Return; strokes (pencil, a line past the canvas, a slant fill, the brush past its edge) against `PaintModel` at the view's offset, all 32,000 bytes of C; a drag on the frame (left, bottom, right) draws nothing (W2: it pans); the arrows, PgDn and Ctrl-Left (kept inside); a fill and the eraser after scrolling (`pph` 1); speed; U, U; Invert, a stroke, U, U; F1's help (the view's keys, CODE-X); CODE-K's calculator over it and closed (W_DRAW); CODE-T the tasks; CODE-F8 smaller, the view to its limits, CODE-F8 bigger again (the view kept inside the picture); the screen saver; Tab's tools window over the canvas; a drag of the title (the canvas follows, `pph` 5, a slant fill); CODE-X saving DRAWN.BMP (the title follows); the close box; MTSPIN switching in 60 times while a stroke is held 3 s, every switch by the rules; an unnamed picture saved as a long name (the title the name as DOS keeps it, VERYLONG.BMP); a second Paint (staggered, its own C and U, a stroke in it leaving the first's alone). In test_apps: the view's keys do nothing on the whole screen, and the help is as before.

## 12. W2: the zoom and the frame's pan (2026-11-02)

**The zoom (CODE-F, in a window; on the whole screen it does nothing).** The window itself becomes the whole screen, in place: `win` is kept (`wsave`) and becomes `zwin`, 0, 0, 80 x 360 (down to the band) with no title and no flags (nothing to move, close or size; CODE-F8 is then Paint's, and does nothing). Zoomed, `ses` is 0, so everything takes the whole screen's path, as without windows: a stroke swaps C and U and its end copies the screen into C (15 ms: `commit`), undo and Invert show all of it, `main` mends the band before each wait, and the canvas is the whole screen (`full`: 0-639, 0-399, `pph` 0). The view (`vx`, `vy`) is kept for the way back. CODE-F again: the window closed (KMW draws the screen again without it), `win` as it was, opened again (`w_draw`: the view), the band saying where; D is then the whole picture (`d_all`: strokes zoomed changed C and U anywhere), so the next stroke's `sync_u` copies all of it once.

**The clock.** A session starts with the Executive's globals, its title on, so the core would draw the clock over the picture's top lines each minute while Paint is in front. Zoomed, `w_zoom` (the window's W_DRAW) calls `UI_CLS` before drawing the picture when it runs on Paint's own stack (between `run_bss_end` and `sp0`, the stack's top at start): its session's redraw, or `k_zoom`. That turns its session's title off. The Executive's redraw (the base, under any redraw of Paint's) turns it on again, and Paint's window, drawn after the base, turns it off. Drawn from another session's redraw (another window in front, over the zoomed Paint; SP is enough: every redraw runs on the UI's SS, and the saver on a task's stack draws no windows), it leaves that one's title alone. Out of the zoom, KMW's redraw puts the title back.

**Why down to the band, not 400 lines.** Paint in front draws all 400 lines (`w_zoom` on its own stack, `band_fix` in `main` as on the whole screen), so the picture is the whole screen. But the window stops at the band, as every window does (KMW keeps them above it): `win_paint` clears a window's rectangle before its W_DRAW, so a 400-line window would wipe the band of whichever session is in front whenever that one's redraw drew Paint's window; KMW would give clicks on the band to Paint, not to the one in front; and with the Executive in front its band, and a question it asks there (Delete's, Copy's), would be cut away under Paint's window.

**Another session in front.** Its redraw (its help closed, the saver's end, a resize) draws Paint's zoomed window too, from its own stack: `w_zoom` then draws only the window, the picture's lines above the band, so that session's band, and a question it has waiting, stay. With the Executive in front (CODE-F6) its list is under Paint's window, as under any window, but its band shows. (Its clock may be drawn over the picture's top lines meanwhile; the screen only: Paint raised again is drawn again, and a stroke mends those 16 lines first, below.)

**A question of Paint's while zoomed** (CODE-Q's, ESC's, Transfer's form, an error's message) waits in the band, inside `UI_ASK`/`UI_FORM`/`UI_MSG`: a redraw on Paint's own stack then (the saver's end, another session ending) mustn't draw the picture over it. So `w_zoom` draws all 400 lines (and calls `UI_CLS`) only in `main`'s wait (`in_ev`) or from `k_zoom`; otherwise the window only, above the band, and it sets `tz`, so that `main`, the question over, draws all of it with the title off (the Executive's redraw may have turned it on: the clock meanwhile is mended by a stroke, as below).

**The band.** KMW draws the band of the one in front after a change of focus (CODE-F6, a click) or when another session ends (the calculator closed), and Paint gets no event then. So zoomed, Paint's band ("The whole picture.  CODE-F: back to the window") stays over the picture's last 40 lines until the next key or click, as the full-screen hint does. A stroke mends it first (`stroke`: zoomed, `band_fix` as after the saver, and lines 0-15, where another session's clock may have been drawn while one without windows was in front), so neither gets into the picture. (Mending it at once would take KMW not drawing the band of a window that covers it: a change to LODEMT.SYS, not made.) A click on the band goes to the session in front, as ever (Paint's window stops above it).

**The frame's pan.** A press on the window's frame under its title strip (its left and right byte columns, a byte's width, and its bottom line; the title strip is KMW's drag, the corner its resize) drags the view, as a hand moving the picture: the view where it was less the drag (across, to the nearest byte: `(x0 - x + 4) >> 3`), kept inside the picture by `geom`, drawn when it changes, the band saying where at the end. It works on a picture shown too (before Return). `pan` samples with `sample`, its clamp opened up (`clx0`-`cly1` 8000h-7FFFh; `geom` puts the canvas's limits back), so nothing in the strokes' path changed. A press on the band is not a pan. (KMW gives Paint only clicks on its windows and on the band: off the canvas and not below the frame is the frame, so that is `pan`'s only test; and only in a window, `ses`.)

**Help:** with windows, "A drag on the frame" and "CODE-F" are patched in (`kh_view`'s third line, `kh_zoom`), as W1's view keys.

**Size:** PAINT.RUN 6,691 bytes (W1's 6,035: +656), 14 sectors of ROM 2 (80,384 bytes left there); its BSS 1,756 bytes. Resident: nothing.

**Tests (`t_paintw`, test_mt, 37 checks now, 12 more):** a drag on the frame of a picture shown pans (and back); drags on the frame pan (the left edge, the right edge, the bottom rule; to the nearest byte; kept inside), a drag from the band's first line doesn't, no stroke; F1's help (the frame's drag, CODE-F); CODE-F: the window 0, 0, 80 x 360, no title nor flags, `ses` 0, the screen all of C, the canvas the whole screen, the title off; U first (the window's last stroke undone), U; zoomed strokes (a line across the top and the band, a slant fill) against the model in screen co-ordinates, the commit in 16 ms; U, U; Tab's tools window and the calculator over it (its F1 and ESC: the calculator's title and band left on, the picture above it), the band after it until a key, Paint's title still off; CODE-F6 twice (the Executive's band shown; Paint's band, and something written over the top 16 lines; a stroke with no key first mending both); ESC's question zoomed, the saver over it and a key (the question still in the band), ESC (all of the picture, the title off); CODE-X zoomed (ZOOMED.BMP, no title shown); CODE-F back (the window, the view, the title on, D the whole picture); U first (the last zoomed stroke undone), U; a stroke and U after it. test_apps: CODE-F does nothing on the whole screen, and the help has no zoom line. Nineteen mutations of W2's code (UI_CLS, the stack test, all of the picture from another's redraw, all of it while a question waits, `tz` ignored, `zwin` 400 lines high, the zoomed mend and its clock lines, `d_all`, the rounding, the frame's limit and its line, `pph`, `ses`, Transfer, the pan's drawing and band, the help, the zoomed band) are each caught but one (Transfer reopening the window zoomed: as right, only slower).

**On the 1520 (2026-11-04):** Joshua ran Paint in a window there: it works.
