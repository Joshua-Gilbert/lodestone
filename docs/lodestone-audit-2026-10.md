# Lodestone audit, 2026-10-17: duplication, memory, speed

Seven read-only auditors went through the code in parallel:
- the resident kernel;
- the optional kernel modules;
- the UI and the apps;
- the shell and the standalone programs;
- Resident Claude;
- the Python tooling;
- a search for copied routines across all the assembly.

Sizes come from `LODE.MAP`, `CLAUDE.MAP` and `RCON.MAP`, not from line counts. Findings marked ✔ were checked against the source by hand. The others are as the auditors reported them, so read the code before acting on them. Nothing was changed.

"Resident" means DOS programs lose those bytes. "Transient" means the bytes only take disk space and load time.

## 0. Bugs found along the way

| # | What | Where | Fix |
|---|---|---|---|
| B1 **fixed** (8efe8d4) | **Settings past byte 511 of LODE.INI are lost at boot.** `font_boot` reads only 511 bytes. SYSTEM keeps up to 1,024 and rewrites the file with the user's lines first and FONT=/SAVER=/TIDY= at the end (SYSTEM.ASM:1698-1765), so a long file loses those settings at boot. MDISK= and SPLASH= are read up to 4,095 bytes and keep working. | [UICORE.INC:246](../os/src/UICORE.INC#L246); the font goes to `entries+512` (334) | Move the font buffer to `entries+4096` and read 4,095 bytes. Later, use one `scan_ini` for KSPLASH, KMDISK and UICORE. |
| B2 **fixed** (a5cbbaa) | **A failed `SET` deletes the old value.** LCMD removes the old NAME= before it checks for room, so "Out of environment space" leaves the variable gone. CALC's copy (`setvar`) checks first. | [LCMD.ASM:3777-3830](../os/src/LCMD.ASM#L3777-L3830) vs [CALC.ASM:221-325](../os/src/CALC.ASM#L221-L325) | Use CALC's order. Put one copy in `LCMDENV.INC`, which both programs already include. |
| B3 | **The GPIB driver copies have drifted.** The standalone `GRIDGPIB.ASM`, used under GRiD MS-DOS, lacks the kernel's fast block loops. They also differ in version (0110h vs 0120h) and in the unload call. | `KGPIB.INC` vs `tools/GRIDGPIB.ASM` | One `GPIBCORE.INC` with a label-prefix define. |
| B4 (latent) | **DEFRAG's copy of the drawing code lacks `clip_rows`** (a count of 0 would loop 65,536 times). Today every caller passes constants, so nothing breaks yet. | `DEFRAG.ASM:3002-3141` vs `UICORE.INC:1174-1460` | Shared `GFX40.INC`. DEFRAG can't use UIAPI because it also runs under MS-DOS. |
| B5 (latent) | **`mount_bpb` never checks the cluster count against the FAT size.** A malformed boot sector can make FAT writes run past `spf*512`. That is harmless today, because the writes stay inside `fatbuf`. It becomes a real overrun if M1 below is done. | [KDISK.INC:241-247](../os/src/KDISK.INC#L241-L247) | Clamp NCL to `spf*512*2/3`. |

## 1. Memory: resident bytes

Measured on Joshua's 1520 (EMS, C:, GPIB). Risk is L(ow), M(edium) or H(igh).

### Kernel (resident .text 17.5 KB plus .bss 13.9 KB, plus ems 2.0 KB and hd 1.4 KB)

| # | Change | Saving | Risk | Notes |
|---|---|---:|:-:|---|
| K1 | **Move start-up-only code into a section run over `fatbuf`.** The routines are each called only from `init`. Covers init, ui_load, s_nouimem, ivt_init, vec_table, clock_init, drv_init, sft_init, proc_init, env0, bootbpb, optionally mem_init and gpib_init, and hd_drv_init in KHD. | 785–930 B | M | **Hazard:** `init.go` is patched to jump to the splash and M: start-ups. Those open `\LODE.INI` and `\LODE.PIC` with INT 21h, which loads `fatbuf`. So nothing may come back into code that lives there. Also check that none of the routines moved there loads the FAT itself (e.g. drv_init or proc_init). KEMS/KHD patch `vec_table.v25/.v67` and `init.cdrv`; point those patches at the copy. `kern_top` becomes a BSS word. KMDISK.INC:881 asserts that `init` is within 128 B of `start`. |
| M1 | **With EMS, put C:'s 3-sector FAT window in the unused end of `fatbuf`** (`fatbuf+9*512`). On a 1520, every FAT12 medium uses 9 FAT sectors or fewer; M: needs 5 with 88 EMS pages. | 1,536 B | M | **Changes behaviour:** floppies with 10–12 FAT sectors are refused when C: exists. Needs B5 first. |
| K2 | **Put EXEC's and RENAME's scratch buffers in the screen-capture area at the bottom of the kernel stack.** Covers `ex_hdr`, `ex_name`, `ex_rel`, `path2_buf` and `ren_de`. The capture area is only used at INT 21h entry with indos=1. | 416–578 B | L-M | Fallback: put only `ex_name` on top of `path2_buf` (132 B). |
| K3 | Move the body of screen capture into EMS behind a 6-byte resident check, as KMDISK does with its installer. | ~470 B | M | |
| K4 | Small kernel duplicates: | ~450 B | L | Leave `ctrlc` vs `done` alone; it's a stack switch on a hot path. |
| | • the time-of-day arithmetic, written twice (`f_2C` / `dos_stamp`) | 55–60 | | |
| | • six copies of `r_name`→`nm11` that do nothing, plus the repeated resolve/check sequence | 66 + 60 | | |
| | • two line editors (`f_0A` / `con_readline`) | 60–80 | | |
| | • SFT-index arithmetic, written 4× | 25 | | |
| | • `badchars` repeats the end of `sepchars` | 12 | | |
| | • boot-sector re-reads | 25 | | |
| | • CHS setup | 18 | | |
| | • KGPIB: 3 identical exit paths, unused `gp_oldvec`, a constant `gp_intno` | 25 | | |
| | • KHD `hd_fget`/`hd_fset` share a prologue; the mouse code has two near-copies | 40–60 | | |
| K5 | Load the GPIB driver only when the 7210 chip answers. It is already position-independent. | 1,762 B | M | Saves nothing on Joshua's machine, which has the chip. |
| K6 | Without EMS, assemble KHD a second time at `bss_end` to remove a 480 B gap. | 480 B | M-L | Saves nothing with EMS. |

### UI block (27.2 KB stays resident under DOS programs; only the 7.7 KB `entries` buffer is lent to them, ✔)

| # | Change | Saving | Risk | Notes |
|---|---|---:|:-:|---|
| U1 | **Run the start-up-only UI code over `entries`.** Covers font_boot/font_file, mouse_init/probe, sysinfo/fpu_detect/build_info, the no-hi-res strings and reboot. | ~950 B | M | `font_boot`'s read buffers have to move above it. `ex_start` reruns sysinfo on every restart; run it only on the first. |
| U2 ✔ | **Remove `rowtab`** (800 B, [UICORE.INC:162](../os/src/UICORE.INC#L162)). Row loops can step through the 4 banks instead; single lookups can use `(y>>2)*80 + ((y&3) ror 3)`. | ~730 B | M | Do U3 first, so `putc` doesn't work the formula out for every glyph. |
| U3 | Make `puts`/`putc` go through `putsn`, removing the second unrolled glyph routine. This is also a speed win (S9). | ~150 B | L | Keep the "SI ends past the NUL" contract that `fm_value` relies on. |
| U4 | Merge `crit_msgs` into `dos_msgs`: 9 of the 13 strings are the same, and DOS error = `crit_err`+18. | ~185 B | L | |
| U5 | A TAB in help lines means "column 25", replacing 236 bytes of padding spaces. | ~220 B | L | Also shrinks the apps' help tables. |
| U6 | Small duplicates: `sb_hm`/`sb_dmy` repeat `api_sbtime`/`sb_date`; the end of `show_cursor`; the "X:\" prefix written 4×; 13 shared `show_msg` endings; `hline`/`hline_dots`; the `ui_msg`/`ui_ask` band save. | ~200 B | L | |
| U7 | Move `entlist` (480 B) and the file-command buffers (~450 B) past `ui_keep_end`, so they are lent to DOS programs too. | ~930 B while DOS programs run | L/M | `sub_erase` needs a guard for a block that came back short. |
| U8 | Load the file commands (Copy/Move/Rename/Delete) as an overlay, like a .RUN. | ~4.8 KB | H | Costs one floppy read per command and needs a private interface to the Executive. |

### LCMD (stays fully loaded under every program started from the prompt: ~16 KB)

| # | Change | Saving | Risk |
|---|---|---:|:-:|
| L1 | Let the late BSS overwrite start-up-only code (start, switch parser, env_init, banner and AUTOEXEC strings). | ~500 B | M |
| L2 | Let buffers that are never used at the same time share space: canon1/2 with pat/pat_dir, and the FCB buffers with tail/fcb1. | ~250 B | L |
| L3 | Duplicates: "add `\`" written 5×, "directory part of path + name" 3×, `$P` vs CD, the CR/LF on every `crit_msgs`/`e_*` string, and the `days` table. | 150–200 B | L |
| L4 | Size each CALL level's batch context up to `for_dta` when no FOR is running. | ~300 B per CALL level | L |
| L5 | A COMMAND.COM-style split into a resident part and a transient part (or swap to EMS). | ~12 KB | H |

### Resident Claude (816 B conventional plus 3 EMS pages, as the auditor measured; already lean)
- `blankline` (160 B, [CLAUDE.ASM:3137](../os/claude/CLAUDE.ASM#L3137)) → `xor ah,ah; call blank_row`. Saves 154 B while CLAUDE.COM runs. Low risk.
- The RCON stack could move into EMS page 0. That saves 384 of the 816 B, but it is risky: an interrupt handler that remaps window 0 while running on that stack would crash. This is an option, not a recommendation.

## 2. Speed

| # | Change | Hot path | Gain | Risk | In BENCH? |
|---|---|---|---|:-:|:-:|
| ~~S1~~ | **False finding.** Only the first 256-byte batch of relocations misses read-ahead: that read sets `S_RAE` itself, so every later batch counts as in order. TM5000G (6,889 relocations): 41 BIOS reads against 40, 11.09 s either way. Not changed. | | none | | |
| S2 **fixed** (dcc2714) | **Make the COPY buffer whole sectors:** `and bx, 0FE00h` in `cbuf_get`. 65,520 bytes is 496 bytes into a sector, so from the second chunk on every read and write was partial. | Each 64 KB of COPY | 300 KB COPY: 22.85 s → 21.26 s (−7%, real drive timing) | very L | no |
| S3 ✔ | **DEFRAG: drop the second FAT flush in each move.** Leave the freed clusters in memory and flush at the next move, at the end of `tidy` and in `stop1`. A power cut then leaves lost clusters, which a power cut between steps 4 and 5 already does, and which `defrag_cut.py` accepts. A later move can reuse the old chain's clusters before the flush without harm: step 4 has already pointed the directory entry at the new chain, so nothing references the overwritten data. | Each file moved | ~0.7 s per file, 1–2 min per run | M | no |
| S4 | **Console output to a file or pipe:** `f_09` should make one `sft_write` per string, and DIR should build each line and write it with one AH=40h call. Today redirected output writes one character per call. The deeper fix is write-back for the last data buffer (dirty flag), which changes when write errors appear. | `PROG > FILE`, `DIR \| …` | Per-character writes become one per line | L (write-back: H) | no |
| S5 | DEFRAG: read a whole source track, then write it in destination-aligned pieces, instead of the smaller of the two tracks. | Each track of data moved | 10–15% of copy time | M | no |
| S6 | DEFRAG on C: find free runs with `repe scasb`, and draw each cell once per move rather than once per cluster. | 65K-cluster scans | ~10× CPU | L | no |
| S7 | KHD: read several FAT sectors per command for the first free-space count. | First DIR or System view of C: | ~3 s → 0.25 s if the drive has no look-ahead | L | no |
| S8 | KGPIB fast loops: keep the count in CX instead of updating memory counters on every byte. | Every GPIB byte (Claude Term) | 15–25% CPU per byte | L | no |
| S9 | UI: `puts` via `putsn` (U3) removes ~70 cycles per glyph. Partial redraw on Tab instead of `draw_all`. `fm_outline` drawn a byte at a time instead of a pixel at a time (~100K cycles per keystroke in a choice field). Scroll lists with a block move. | Executive redraws and keys | 25–30% per glyph; most of each Tab redraw | L-M | no |
| S10 | WRITE: draw only the changed span of a row. | Every keystroke | ~130 glyphs → a few | L-M | no |
| S11 | CLAUDE chat: scroll the screen instead of a full 1,600-cell redraw on every newline. Factor out `term_scroll`'s screen-only loop; calling it directly would also shift the conversation ring. | Each TEXT frame | ~50–60 ms per frame | M | no |
| S12 ✔ | TERMCELL `put_cell`: work out the offsets once per run of cells rather than two multiplications and four saved registers per cell. `blank_row`: fill with `rep stosw`. | Each cell applied (Term, RCON) | ~20% of applying a CELLS frame | L | no |
| S13 | MOUSE33 pointer: step the row address and shift with CL instead of a `mul` and a one-bit-at-a-time shift. | Each mouse packet with the pointer on | ~½ of 0.8 ms with interrupts off | L | no |
| S14 | KEMS: inline `ems_map` into function 44h; move word-wise in 57h exchange and backward moves. | Each EMS map call | ~7% | L | **yes** (map ×10,000) |
| S15 | Smaller items: LCMD finds an external command with one `NAME.*` search per directory instead of 3 lookups; DEFRAG reads a whole directory cluster per call in `walk_dir`; `find_next` restarts the cluster walk for every entry. | | small | L | no |

## 3. Test suites and Python

| # | Change | Gain |
|---|---|---|
| P1 **fixed** (a76daf9) | **Speed up the screen reader** ([os/ktest.py:157](../os/ktest.py#L157)). Columns built with slices, and the last result kept for the same video memory. The output was identical on 204 calls across five groups. 27× faster per call (15 ms → 0.5 ms); the auditor's "40 s" estimate was too high (each call was 15 ms, not 75). | test_apps 58 → 46 s, test_defrag 102 → 91 s; the full run ~27 s shorter |
| P2 | **Let the suites run in parallel.** Build once up front (or skip when outputs are newer than sources), give each suite its own output directory, and run the independent `t_*` groups in a pool (`defrag_cut.py` already does). | Wall time ≈ the longest suite |
| P3 | Build disk images with one `mcopy` for many files, or with `fat16img` in-process. | ~600 process starts, ~6–12 s |
| P4 | Block hooks: compare the `addr` argument instead of reading CS:IP on every block (`claude_kernel.py:40`, test_kernel/apps/resident). `ktest.KPC` should install `watch` only when it is needed. | 20–40% emulation speed in those suites |
| P5 | Cache the parsed `LODE.MAP` by path and modification time (it is parsed ~150 times); profilers use `Syms.name()`. | ~1.5 s, ~30 lines |
| P6 | gridlink: rebuild only pyte's dirty rows instead of all 1,920 cells per CELLS frame. | 2–4 ms per frame on the Pi |
| P7 | Boot snapshots (unicorn context save) would help only repeated boots of the same image. Time a boot before trying. | uncertain |

## 4. Duplication with no runtime cost (maintenance)

- ✔ **`sim7210.py` is in the repo three times, byte for byte:** `os/`, `tools/`, `claude-link/tests/`. Which one loads depends on `sys.path`. Keep one; make the others re-exports.
- **Dead files:**
  - `os/src/GRIDOS01.ASM` is the 0.1 kernel, identical to `os/releases/0.1/GRIDOS.ASM`, and nothing builds it.
  - The emulators in `tools/` (`dosemu`, `tm5trace`, `tm5scen`, `simgrid`, `bootsim`, `mkrom`) are used by no test or script.
  - `os/claude/KEYCODE` is used only by hardware SPIKES.BAT.
  - RSPIKE and its four tests are superseded by `CLAUDE /R`.
- **Python test harnesses:**
  - the gridlink setup is pasted 4× (`claude_kernel.py`, `grid_emu.py`, `gridsim.py` ×2), and `pump_pi` 3×;
  - `grid_emu.Machine` repeats pcemu's CPU and BIOS scaffold (`text_screen`, `png`, timing; ~120 lines);
  - there are three amber screen renderers.
- **Assembly test harness:** the print/report code is pasted 5× across TESTDOS, EMSTEST, MDTEST, CACHETST and EMSKEEP (+ BENCH). The copies have different register rules under the same names. Make an `os/tests/TESTLIB.INC`.
- **Decimal printers:** seven, each with a different register contract (UICORE, DEFRAG, CALC.INC, CLAUDE, RCON, LCMD, HEADCLN), plus `pnum` pasted into EMSUSE, GFXUSE, LODEBOOT and MEMSZ. `put_str`/`copyz` in CLAUDE and RCON belong in `CELLTEXT.INC`.
- **The fonts are in CLAUDE.COM twice:** its own copy and the one inside `RCON.BIN`, 2,064 B of the file. Copy them into RCON's area in `res_load`. Saves file size only, no RAM.
- **CLAUDE/RCON:** `find_gpib`/`gg_call`, `msg_sent`/`link_lost` and the `pi_frame` prologue are copied. The prologue could go into TERMLINK's `took_answer`. TERMLINK's variables are declared by hand twice, and the lists already differ (use a `TERMLINK_BSS` macro).
- **tools/:**
  - `common.inc` = `timing.inc` + `io.inc`;
  - `GPIBSCAN.ASM` is a 900-line fork of GPIBTEST with no includes;
  - D488TEST, MEMPROBE, RAMSPEED and GRIDMEM paste the shared includes inline.
- **gridlink:** `tools.py` and `mcp.py` repeat the command, GPIB and snapshot logic (~60 lines), but their validation differs.

## 5. Already good (no need to audit again)

**Kernel:**
- INT 21h entry costs ~50 µs per call.
- The SFT remembers its current cluster, so reads and writes don't walk the chain from the start.
- Whole-sector transfers go straight into the caller's memory, with track-sized runs and read-ahead into the cylinder cache.
- FAT writes go out only for the changed sectors.
- 57h saves the page map once per call; the cache is mapped once per transfer piece.
- KMDISK reuses the kernel's FAT12 engine rather than a second block layer.
- KSPLASH, the M: installer and the EMS and C: start-ups cost nothing resident.

**UI:**
- The glyph routine is unrolled.
- The list redraws only the two rows that change.
- Write keeps a shadow copy of the screen.
- The window save-under uses the disk cache's EMS.
- The apps use the jump table.

**Shell and DEFRAG:**
- Batch files are read 128 bytes at a time.
- COPY asks for 64 KB.
- DEFRAG works a track at a time and flushes only the dirty FAT sectors, as runs.

**Claude:**
- The Pi sends only the cells that change, so nothing is compared on the GRiD.
- The CRC is table-driven.
- Both programs idle with HLT.
- The `res_*` code and the RCON image sit in BSS, which programs get back.

**Python:**
- Emulated time uses block hooks, and HLT skips ahead.
- AR488 reads come in blocks.
- Disk images are in memory.

## Suggested order

1. ~~Bugs B1 and B2~~ (fixed).
2. ~~S2 (COPY alignment)~~ (fixed). S1 was a false finding.
3. ~~P1 (screen reader)~~ (done); P2 (parallel suites) next. These make every later change cheaper to test.
4. **Resident memory, low risk:** U3+U2, U4, U5, K4, L2, L3. About 2 KB in total.
5. **Resident memory, medium risk:** K1+U1 (~1.8 KB of start-up-only code) and K2. M1 only if refusing 10–12-sector FAT floppies is acceptable.
6. **DEFRAG:** S3 and S5, each checked with `defrag_cut.py`.
