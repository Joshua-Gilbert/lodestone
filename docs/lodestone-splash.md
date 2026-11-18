# Lodestone 0.4.3 — the start-up picture (2026-10-09)

At start-up Lodestone shows a terrella, the "little earth" William Gilbert describes in *De Magnete* (1600): a lodestone turned into a sphere. Here it turns on a rod set 25° from upright, shaded with rings that are open to one side, among a dipole's lines of force. LODESTONE is underlined beneath it. It stays 2 seconds or until a key.

The drawing is Lodestone's own, not a copy of any of the book's woodcuts. Its subject is Gilbert's; the rod, the rings and the lines of force, a modern dipole's, are this drawing's.

Until 2026-11-21 the picture was Fig. 1 of F. A. Annett, *Electrical Machinery* (McGraw-Hill, 1921), "Lodestone attracting some iron nails", traced into a stone's outline and 235 nails. It was changed on reviewers' feedback. That picture's sources (`plate.png`, `trace.py`, `trace.txt`) and drawing code are in the history before that date.

![The start-up picture](../os/screens/readme/splash.png)

## Design decisions

- **Monochrome:** 1 bit, lit or not, as mode 40h is anyway; no grey palette tricks.
- **A dark screen, everything drawn lit.** Nothing is drawn dark, so the order of drawing doesn't matter.
- **The stone:** a circle of radius 84, its outline 2 pixels wide, on an axis 25° left of upright. A rod, 2 pixels wide, stands 18 pixels out past each pole.
- **Its shading:** six rings, 12 pixels apart, each open on the right a little below the equator, the openings of different widths. Each ring's centre is 5 pixels nearer the upper pole than the last, so they gather round the rod's end and the stone reads as a ball turning on it.
- **Lines of force:** a dipole's about that axis, r = k sin²θ, for five values of k, drawn where they are off the stone and on the screen above the title. An arrowhead each side shows the way the field runs.
- **Only the title**, LODESTONE underlined. It is centred under the stone. The version and caption lines of the first draft are gone. Since 2026-11-05 its letters are Lodefont's capitals as thin strokes (`lodestone-font.md`): O and D tall with cut corners, N's diagonal ending high. They were chamfered 1920s drawing capitals before.
- **Its own file:** the picture is `LODE.PIC`. The kernel keeps only a small bootstrap that reads it into memory, runs it and lets the memory go. In the first version the picture was part of `LODE.SYS`'s start-up code. That was already non-resident, but it made `LODE.SYS` 2.7 KB bigger on disk.
- **Off from the Executive's side:** System, Display, Space writes `SPLASH=0` to `LODE.INI`, and the bootstrap then never opens `LODE.PIC`. With no `LODE.PIC` on the disk there is no picture either.
- **Standing rule:** minimal resident bytes, reuse, speed. The picture costs 0 resident bytes, and DOS programs get 562.5 / 578.6 KB, as under 0.4.2.

## Files

| File | What |
|---|---|
| `os/splash/mksplash.py` | The drawing: its numbers (centre, tilt, rings, lines of force, title) are at the top. Works out the paths, packs them into `src/SPLASH.INC`, and draws them in Python exactly as the 286 does (`splash.png`, and the tests' reference) |
| `os/src/SPLASH.ASM` | → `LODE.PIC` (1,020 bytes, 2 sectors of ROM 1; the nails were 2,544, 5 sectors): the drawing code and `SPLASH.INC` (607 bytes of it) |
| `os/src/KSPLASH.INC` | The bootstrap, in section boot of `LODE.SYS` (336 bytes on disk, never resident) |
| `os/apps/SYSTEM.ASM` | Display: "Start-up picture yes/no"; Space |
| `os/tests/test_splash.py` | 64 checks |

## The drawing (SPLASH.ASM, mksplash.py)

- **Everything is a path:** a pen, a first point and a step to each next one. There are 28 paths with 238 steps.
  - **THIN:** a line 1 pixel wide through the points (the rings, the lines of force, the arrowheads).
  - **THICK:** the same with 2 × 2 pixels at each point (the stone's outline, the rod, the title and its rule). E, T and N go back over part of themselves so that each letter is one path.
- **Packing:** per path, a header byte and the number of steps (below 128), then the first point, then each step as signed bytes (dx, dy, ±127). A header of 0 ends the list. mksplash splits a longer line into steps that fit.
  - **The header:** 04h, always; 01h, the 2 × 2 pen; 08h, the first point is a step (signed bytes) from the last path's first point, else it is two words; 40h, 80h and 20h, the mirrorings below.
- **Mirroring:** 40h draws the path again with each pixel mirrored left to right about the stone's centre, 80h top to bottom, and both bits draw it four times; with 20h as well, only both at once, which is the path turned half round. A mirrored pixel is at 2 CX − x, 2 CY − y; a 2 × 2 block, whose pixels reach 1 right and 1 down, at 1 less.
  - The outline is its lower right quarter, mirrored four ways.
  - A dipole's lines are the same turned half round, so only those right of the axis are kept, and one end of the rod. An arrowhead turned half round would point against the field, so both are kept.
  - The rings are kept whole: on a tilted axis nothing mirrors them.
- **The outline is exact:** mksplash works out a quarter of the circle as a chain of touching pixels, then keeps the fewest points whose lines are exactly those pixels.
- **Rings and lines of force are fitted** to within 0.65 of a pixel: the fewest points whose polyline stays that close to the curve.
- **Lines:** Bresenham from the first point, in registers. A steep line is drawn with x and y swapped, and the point routine swaps them back.
- **A point:** its row's offset from a table built at start (each row at (y & 3) × 2000h + (y >> 2) × 80, 800 bytes of scratch), and its one or two bits put in with one word OR; the 2 × 2 pen does the same on the next row.
- **Size:** `LODE.PIC` is 1,020 bytes, 2 sectors with 4 to spare: 607 of drawing and 413 of code. Another change to the picture may cost a sector.
- **Speed:** 195 ms in pcemu's 286 model, from before the mode set to the last pixel. The nails took 252 ms.
- **Python must match it bit for bit:** `mksplash.render` uses the same integer rules, and the tests compare all 256,000 pixels of the emulator's screen with it. mksplash also checks that no point falls off the screen, since the 286 code doesn't clip.

## Start-up (KSPLASH.INC)

- **Getting control:** `hd_init`'s last jump goes to `sp_hook`, which makes `init` end through the far jump at KSEG:0000 (KMDISK's way).
  - If `ems_init` already put a jump to `md_boot` there, `sp_hook` takes that over and goes on to `md_boot` afterwards.
  - Otherwise (no EMS, or the `-dNOTC` build) it saves `start`'s 5 bytes there itself and puts them back afterwards.
- **`sp_boot`** runs on the UI's stack, as `md_boot` does:
  - It reads up to 4 KB of `\LODE.INI` into 1000:F000, md_boot's buffer, which md_boot reads after it. `SPLASH=0`, `No` or `Off` (any case, at a line's start) means no picture.
  - It reads `\LODE.PIC` into 2000:0000, free at that point: the load image ends near 1000:B300, and a UI block reaching that far would have overwritten this code first.
  - The file must start with `EB 0A "LODEPIC" 01`, and the word at offset 10 must equal the number of bytes read. A cut-short or padded copy is never run.
  - It then far-calls 2000:0000 and goes on to `md_boot` or `run_ui`. The Executive's mode set clears the screen.
- **LODE.PIC itself:**
  - It sets mode 40h, or does nothing if the BIOS doesn't give it, and draws.
  - It drops keys already typed, such as spare F taps from choosing the floppy at the BIOS's prompt, which would otherwise end it at once.
  - It waits 36 ticks on 0:46Ch with `STI; HLT`, or for a key, which it takes.
  - Its scratch (each row's offset in the screen, 800 bytes, and a few words for the drawing) is the rest of its segment.
- **Test marks:** `INT 1Ah AH=0` with BX = BEF0h (start), BEF2h (drawn) and BEF1h (gone), BENCH's way of marking time; the BIOS ignores BX. Any midnight rollover flag that call returns is put back at 0:470h for the kernel's clock. `ktest.waiting()` doesn't count a halt between BEF0h and BEF1h as the machine waiting for input.

## System

- Display shows "Start-up picture yes/no", and Space turns it over. `SPLASH=0` is written to `LODE.INI` only when the picture is off, and other lines are kept.
- System reads `LODE.INI` for this only when Display is first shown, or when it saves. It doesn't read it at start, which would cost a disk read, or a critical-error prompt with the boot disk out.
- Saving the saver delay or M:'s size before Display has been shown still keeps a `SPLASH=0` line.
- If the save fails (write-protected disk, or a `LODE.INI` too long to rewrite), the switch goes back and the band says why. The messages no longer say "The font is set", which was wrong for the saver and M: too.

## Tests (tests/test_splash.py, 64 checks)

- **The picture against `mksplash.render`, every pixel,** for every way the kernel starts: floppies only, EMS, the hard disk as C:, C: with EMS, and `-dNOTC` with and without EMS. The Executive follows; M: still gets its size; C: is there.
- **The drawing itself:** `src/SPLASH.INC` is what `mksplash.py` packs now, and `LODE.PIC` fits 2 sectors.
- **Timing:** drawn in under 0.3 s (195 ms), and it stays 2 s.
  - A key ends it at once and the Executive never sees the key.
  - Keys typed before it don't end it and don't reach the Executive.
- **`SPLASH=` in `LODE.INI`:**
  - 0, No, Off, OFF and lowercase all turn it off, including among other lines.
  - 1, On, yes, `XSPLASH=0` and `NOTES SPLASH=0` don't.
  - It is still read past 1 KB of other lines. So is `MDISK=` (md_boot now reads 4 KB too).
- **LODE.PIC:** none on the disk, a text file of that name, one too short, one cut short or one with more after it all mean no picture, with the Executive as before. The same with EMS and with C:.
- **System:**
  - the Display line, Space both ways, `LODE.INI` written and removed, and a restart honouring it;
  - other lines kept, `FONT=` and `SAVER=` alongside;
  - no `LODE.INI` read at start;
  - `SAVER=` saved before Display keeps `SPLASH=0`;
  - a write-protected disk: "LODE.INI can't be saved" and nothing changes;
  - the help.
- **Memory for DOS programs:** 562.5 / 578.6 KB with the picture, without `LODE.PIC`, and under 0.4.2.

## Fixes

Fixed before release:

- `LODE.PIC`'s length wasn't checked, so a cut-short copy with an intact signature would have been called.
- The kernel read 1,023 bytes of `LODE.INI` while System can write about 1,064. The same was latent in md_boot for `MDISK=`.
- System read `LODE.INI` at every start.
- A failed save left the switch showing the new state.
- Typed-ahead keys ended the picture at once.
- A guard on the UI block's size could never usefully fire; it is gone, and the comment says why 2000:0000 is free.

## A pcemu bug found on the way (not the kernel's)

- **Symptom:** with `LODE.SYS` 2,720 bytes bigger, `t_mdisk` failed. MDTEST printed MEMSZ's number and then garbage.
- **Cause:**
  - MDTEST's first sector, the last of cylinder 3, is read by INT 13h straight into memory where MEMSZ had just run.
  - pcemu's BIOS writes that memory from Python, and Unicorn kept running its translation of the code that had been there.
  - The 0.4.1 kernel, padded by the same 2,720 bytes, did the same.
- **Fix:** `dma_write` now calls `ctl_remove_cache` on the range.
- **On the GRiD:** real DMA has nothing cached, so it was never affected.

## On the 1520 (to do)

1. Copy `LODE.SYS`, `LODE.PIC` and `SYSTEM.RUN` from `os/releases/0.4.3` to the floppy, and restart with F.
2. Check that:
   - the picture comes up and stays about 2 s, and tapping F during boot doesn't skip it;
   - a key ends it, and the Executive doesn't act on that key;
   - System, Display, Space makes it "no", and the next start has no picture.
3. Note how long the drawing takes on the plasma; the emulator's 195 ms is a model.
4. Rollback: delete `LODE.PIC`, or copy `os/releases/0.4.2/LODE.SYS` back.

## Changing the picture

Edit the numbers at the top of `os/splash/mksplash.py`, or the paths `drawing()` returns. Then run `python3 os/splash/mksplash.py` and `os/build.sh`.

`mksplash.py` refuses a path of more than 127 steps or any point off the screen.

`LODE.PIC` is read from the drive Lodestone started from, so from the ROM it is ROM 1's copy. To see a changed picture on the 1520 without burning ROM 1, start from a floppy that carries it (F at the BIOS's prompt). The nails' `LODE.PIC` (2,544 bytes) is in `os/releases/1.1`.
