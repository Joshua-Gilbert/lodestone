# DEFRAG and the screen saver (Grid-OS 0.2.2, 2026-10-05)

Joshua's idea: a floppy defragmenter that doubles as a screen saver. It gives a live view of the disk while it tidies it, and keeps something moving on the GRiD's irreplaceable gas-plasma panel when the machine is idle. It's built as a separate program that the Executive loads only while it runs; the only resident cost is the saver's ~0.5 KB.

Decisions (Joshua, 2026-10-05):
- defragment while idle, after 5 minutes;
- also pack the root directory (the DIRPACK idea);
- a separate DEFRAG.COM, not built into the Executive;
- **on a worn disk, keep going — don't just stop.** "These disks do degrade over the years." Added after the first real run stopped at a disk error.

## How it behaves
- **After 5 minutes without a key or the mouse**, the Executive runs `A:\DEFRAG.COM /S M=seg:off` from the root of the current drive, if the file is there. M= is the address of the Executive's mouse flag, so moving the mouse stops DEFRAG too.
- DEFRAG shows every cluster as a cell on the 640x400 screen, tidies the disk, shows "Disk in order: …" for ~4 s and exits.
- The Executive then shows a **dark screen with just the time and date, moving to a new place every 20 s**, so the plasma never holds one picture.
- **Any key or the mouse** brings the Executive back with the same selection. The waking key does nothing else, and a held mouse button isn't taken as a click.
- The next idle period: DEFRAG takes a quick look ("Disk in order", a few seconds), then the dark screen. With no DEFRAG.COM on the disk it goes straight to the dark screen.
- DEFRAG can also be run by hand, from the Executive list or `DEFRAG` at the prompt. It does the same, but waits for a key at the end and restores the text mode.
- **`DEFRAG /T`** tests the free space instead of tidying (below).
- **`DEFRAG B:`** (or `B: /T`) works on the floppy in drive B: (BIOS unit 1). Without a drive letter it works on the current drive. The log then goes to DEFRAG.TXT on that disk, and drive A: isn't touched. On a GRiD without a second drive it says "there is no floppy drive B:".
- Help window line: "5 minutes idle — screen saver".

## The map
- 80 cells per row: 8-pixel cells for 1.44 MB (36 rows), 16-pixel cells for 720 KB and smaller.
- Patterns:
  - file: solid;
  - in pieces: checker;
  - free: 3x3 dot (lone plasma dots fire badly; see the cursor-flicker finding);
  - directory/system: box;
  - bad: X;
  - lost: sparse dots;
  - being read: box with a centre;
  - being written: solid with a hole.
- Status line examples:
  - "Tidying the root directory (61 deleted)";
  - "Moving GRIDOS.SYS into one piece / forward / out of the way";
  - "Testing the free space, cylinder by cylinder";
  - "Disk in order: 15 files, 1053 KB free in one piece[, N lost clusters][, N bad clusters marked]";
  - "Done - N files couldn't be read, left as they are";
  - "Done, but N files still in pieces (not enough room)".
- Screenshots: `gridos\screens\0.2.2` (defrag_map, saver_dark, help).

## What it does
1. **Root directory:** deleted entries are squeezed out. The bridge's copies leave 4 dead entries per file; see `gridos-0.2-kernel.md`.
   - Long-name parts stay with their file.
   - Leftover parts are dropped: a deleted entry's parts, and parts whose checksum doesn't match the next name.
   - A second copy of an entry (same name and first cluster) is also dropped, with its long-name parts.
2. **Files:**
   - Every fragmented file is joined, into the lowest gap that fits.
   - Then the gaps are walked from the start of the disk. Each is filled with the biggest file after it that fits.
   - When nothing fits, the file just after the gap is moved out of the way to the far end, at most once per file. The gap grows, and that file usually comes straight back, slid forward.
   - This always ends: every move either joins a file or moves one nearer the start, apart from the one-off moves out of the way.
   - Directories and system-attribute files never move; gaps before them stay.

## Worn disks: it keeps going (added 2026-10-05)
Floppies degrade, and the first real run stopped at a disk error, so a bad spot no longer stops DEFRAG.
- **A copy that won't write or read back right** is abandoned. Nothing has been switched, so the file is still where it was.
  - The clusters it was copying into are tested one sector at a time, and those that fail are **marked bad (FF7)** in both FATs. MS-DOS and Windows respect the marks too.
  - A **weak spot** — one that fails as part of a multi-sector run but passes when tested alone — is marked the second time it fails at the same place.
  - There's no limit on how many it marks. The old build stopped after 16, which is what happened on the 1520.
- **A file sector that can't be read** is retried 4 times, one sector at a time. If it still fails, the file stays where it is, the rest of the disk is tidied, and the final message says so (exit 2).
- **8 failures in a row:** it makes two test writes near the start of the disk.
  - If they work, the trouble is local: from then on, files moved out of the way go just past themselves rather than to the far end, where the bad tracks probably are.
  - If they fail too: "Writes fail everywhere - stopped (the drive?), files fine".
- **`DEFRAG /T`** writes a pattern into every free sector, track by track, reads it back, and marks the clusters that fail. It ends with "Free space tested: N KB, E disk errors, M bad clusters marked" and logs a per-cylinder count.
  - E counts every failed multi-sector read-back, weak spots included. That makes it the number to compare between drives or after a head cleaning.
- **`A:\DEFRAG.TXT`:** every run that changed something or failed adds a dated line, written through the kernel. The line carries the final message, up to 8 disk errors, and with /T the bad sectors per cylinder.
  - Error lines look like "Disk error 10h reading cylinder 64 side 0 sector 1". The sector is where the failing request started, not necessarily the bad sector itself.
- DEFRAG's own INT 24h handler answers Fail, so a kernel error while logging never shows the Abort/Retry box.

## Safety design
- **A file only ever moves whole:**
  1. Copy its data into clusters that are free on the disk, a track at a time; read it back and compare.
  2. Re-read its directory sector and check the entry is still the one recorded (no write yet).
  3. FAT: add the new chain (the old one untouched) to both copies, and read it back.
  4. The **switch**: write the one directory sector with the new first cluster.
  5. FAT: free the old chain.
- A power cut or a pulled disk leaves the old file or the new one, never a damaged one. At worst there are lost clusters.
- Clusters freed in memory are always written to disk before they can be reused. Destinations are always free on disk.
- **Root packing** is one multi-sector write, lowest sector first. A cut can leave an entry twice but never lose one; the next run removes the second copy.
  - **Past the end marker, everything must be zeros.** A cut part way through the packing write can leave the new end marker in place with old sectors still behind it. They are hidden, but DOS brings them back the moment it uses the end slot for a new file. Those old copies then point at clusters that may have been reused.
    - Found by the power-cut test on 2026-10-05: DEFRAG's own DEFRAG.TXT took the end slot on the second run, and files were cross-linked.
    - Fixed: every run first clears anything after the end marker.
  - Residual risks, both needing a cut during packing *and* another system using the disk before DEFRAG runs again:
    - a duplicate deleted with another OS leaves the other copy pointing at freed clusters;
    - enough new files fill the last packed sector and uncover the old entries behind it.
- **The change line is checked before every INT 13h access**, and right after a failed one, before the reset that could clear it. A change stops DEFRAG with no further I/O.
  - At the start it checks that the drive has a working change line; without one it only shows the map.
- **Map only (exit 2), nothing written**, when any of these hold:
  - not Grid-OS — checked with the INT 21h F0h call. GRiD MS-DOS keeps its own FAT and directory copies;
  - a write-protected disk (the first write fails before anything has changed);
  - files open on A:, e.g. DEFRAG run from a .BAT file or from a program that shelled out;
  - the kernel couldn't save its own changes (INT 21h 0Dh returned AL=FFh);
  - the disk needs CHKDSK: broken, cross-linked or looping chains, or a cluster count that doesn't match the size;
  - more than 240 files or 64 directories.
- A key or the mouse stops it only during a move's copy phase, when nothing has been written yet for that move. Exit 1.
- At the start and the end it calls INT 21h 0Dh. The kernel drops its cache and re-checks the disk's identity at the next access.
- FAT copies that differ (from an earlier cut) are made to match the first FAT.
- Lost clusters are not freed, because an open file's clusters could look lost. They're shown, counted in the final message, and left for CHKDSK.

## Kernel support added for it (Grid-OS 0.2.2)
- **INT 21h F0h** (Grid-OS's own call):
  - AL=0 → AX=4F47h ('GO'), BX=0201h;
  - AL=1, DL=drive → CX = files open on that drive.
- **INT 21h 0Dh:**
  - writes the dirty FAT only if its disk is still the same one (drv_ready/same_disk first), otherwise drops it;
  - always drops everything, and returns AL=FFh if the FAT couldn't be written.
- **D_CHK:** after 0Dh, the next access re-checks the boot sector, because a program may have used the disk and its change line behind the kernel's back.
- **After DEFRAG the Executive calls INT 21h 36h**, so the FAT is cached again while the disk is surely the same. Without this, a later swap to a same-format disk couldn't be told apart.

## On the 1520 (2026-10-05)
- **First idle run (old build):** the saver started DEFRAG on schedule, and DEFRAG began tidying. It then stopped at "disk error" and went to the dark clock. Joshua: "I don't want it to just stop!" That led to the worn-disk handling above.
- **The 16-cluster build** stopped with "Too many bad sectors" (15:46). The limit was then removed.
- **`DEFRAG /T` (16:10):** 1,022 KB of free space tested, 4 clusters marked (cylinders 66 ×2, 77, 78). The errors logged were on cylinders 64–71.
- **Full run (16:20) finished:** "Disk in order: 18 files, 988 KB free in 26 pieces, 67 bad clusters marked".
  - The 18th "file" is Windows' System Volume Information folder.
  - The free space is in 26 pieces only because of the marks; every file is in one piece.
  - The root went from 78 entries to ~21.
- **Every file was intact** afterwards, compared byte for byte.
- **The error pattern:** every error in all three runs is on **side 0 (head 0), cylinders 61–78**; side 1 of the same cylinders had none.
  - They are mostly CRC (10h) errors when reading back a run of sectors just written, with each sector passing alone.
  - This points at the drive's lower head (dirty, or writing weakly at the dense inner tracks) more than at the floppy.
  - **To tell which:** clean the heads, then run `DEFRAG /T` on another floppy.
  - 71 clusters (~35 KB) are marked on the development floppy. A full format (not a quick one) gets them back if the drive was the cause.
- **BENCH afterwards (run 7):** directory ×10 took **0.05 s** (it had been 0.43; MS-DOS takes 0.21). Grid-OS is now ahead of GRiD MS-DOS on all ten tests; see `gridos-0.2-kernel.md`.

## Tests (emulator)
- `tests\test_defrag.py` — **33 checks, all pass:**
  - a fragmented 1.44 MB disk: in order, files byte for byte, root packed; a second run writes nothing;
  - write-protected; no change line;
  - a key part way through; the disk swapped part way through (the new disk untouched);
  - run from a .BAT file: map only, and the batch carries on;
  - root duplicates and long-name leftovers; old entries after the root's end marker cleared; a 720 KB disk; GRiD MS-DOS: map only;
  - drive B: from A: — `B: /T` and `B:` work on B: only (log on B:, errors counted), and with no drive B: it says so;
  - the saver:
    - not before 5 minutes; then DEFRAG, then the moving dark clock;
    - a waking key is swallowed; the mouse wakes it;
    - the mouse during the work; no DEFRAG.COM.
  - worn disks:
    - bad spots in the free space are marked and the tidying goes on, logged in DEFRAG.TXT;
    - an unreadable file stays put while the rest is tidied;
    - a bad spot every 23 free clusters: it keeps going to the end;
    - `/T` marks exactly the bad ones and logs `cylinder (count): 55(1) 78(4)`;
    - a weak spot (fails in a run, passes alone) is marked;
    - the far end all bad (cylinders 60–79): it maps out what it meets and finishes nearer the start;
    - a drive whose writes never take: it stops after the test writes, files intact.
- `tests\defrag_cut.py` — **a power cut in the middle of every one of DEFRAG's writes** (half the sectors of that write land), then a second, uninterrupted run.
  - After each cut: every file intact; the only problems allowed are lost clusters and differing FAT copies (and an entry twice while the root is packed).
  - Between the cut and the second run, **another system adds a file** (mtools). It takes the first free root slot, which would uncover anything left after the end marker.
  - After the second run: every file intact (the new one too) and in one piece, and nothing after the root's end marker.
  - Earlier builds passed 191 and 192 cut points. On 2026-10-05 the build with logging failed at 1 of 202: the cut during root packing described above.
  - **Fixed build (9,158 bytes): 202 cut points, 0 failures**, with the added file. The old build fails the new test at that point, as it should.
  - **`defrag_cut.py N worn`** runs the same on a simulated worn drive: the 1520's pattern (multi-sector reads starting at sectors 1–4 of side 0 fail, each sector passes alone, plus 4 hard-bad sectors), placed where this test disk's moves go. The uninterrupted run there: exit 0, 8 clusters marked, 314 writes. **Fixed build: 314 cut points, 0 failures.**
- On an exact copy of Joshua's floppy (from DISKMAP.BIN): root 78 → 18 entries, everything in one piece, free space in one block. About 3 minutes with real drive timing.
- An independent review found:
  - one high-severity issue: files held open by a parent process (fixed by the open-files check);
  - kernel 0Dh issues (fixed);
  - a swallowed write-protect error code (fixed);
  - several smaller issues, all fixed.

## Files
- **Source:** `src\DEFRAG.ASM` (its header describes all of the above). The saver is in `src\EXECRUN.INC` (`saver`, `sv_move`, `sv_defrag`) and the `main` loop of EXEC.INC.
- **Size:** DEFRAG.COM is **9,158 bytes**, including the 1.5 KB font. While it runs it needs about 46 KB plus a 36 KB DMA buffer block; nothing stays behind.
- **Version:** Grid-OS 0.2.2, kernel 24,400 bytes, 570 KB for programs.

## Possible later
- Move directories too (update "." and the children's ".."), so the gaps before them close.
- Have the kernel remove exact duplicate entries at mount, to close the root-packing residual risk.
- Saver variations (big solid shapes, as the roadmap suggested).
- A "re-test the marks" option for after a head cleaning: free the FF7 clusters that now pass, without a format.
