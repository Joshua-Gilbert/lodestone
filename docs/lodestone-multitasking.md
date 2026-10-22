# Multitasking (0.7, being built)

Joshua's plan of 2026-10-19: use ROM 1's free space (about 24.5 KB after 0.6) to make Lodestone multitask preemptively. The README has said so from the start: "The Executive stays resident on purpose: Lodestone is meant to become multitasking".

**His decisions:**
- Several ordinary DOS programs run at once, time-sliced, alongside the Executive.
- Programs that write the screen directly are frozen while they are in the background.
- Running tasks split conventional memory; extra tasks can be parked in EMS.
- Switching works three ways: a hot key, a task list in the Executive, and LCMD commands.
- Lodestone's own `.RUN` programs become movable windows, the calculator first.
- **It is a switch:** off unless `MULTITASK=1` is in LODE.INI. Off means nothing resident and exactly today's behaviour.

## Milestones (one PR each)

| | | Status |
|---|---|---|
| M0 | Windows that move and close (UI API 6), the calculator first | PR #40, merged. Costs 0.5 KB with the switch off: it is UI code, wanted anyway. See `lodestone-0.3-apps.md`. |
| M1 | The switch and the skeleton | PR #43, merged. |
| M2a | Spawning, task regions, switching when one waits for a key | PR #44, merged. |
| M2b | The front: the CODE-Tab hot key, each task's screen saved and restored | PR #45, merged. |
| M3 | Preemption from INT 08h at safe points | PR #46, merged. |
| M3b | Each task's own coprocessor state | PR #47, merged. |
| M4a | Each task's own screen (an INT 10h hook) and the direct-write detector | PR #50, merged. |
| M4b | Keys for the front task only (an INT 16h hook: waits that can be switched from, CODE-Tab anywhere) | PR #52, merged. |
| M4c | Each task's own mouse | This PR. |
| M5 | Per-task vectors, ending and killing tasks | |
| M6 | Parking tasks in EMS and bringing them back | |
| M7 | The Executive's task list (TASKS.RUN, CODE-T), LCMD START/FG/KILL/PARK/WAIT, System's switch | |
| M8 | Several `.RUN` windows at once, as coroutines in the UI task | |
| M9 | On the 1520, and release 0.7 | |

Each milestone's PR adds its section below, describing what was built and any departure from the plan.

## M1: the switch and the skeleton (2026-10-19)

**What it does:** with `MULTITASK=1` (or `Yes`, or `On`, in any case, with nothing after it on the line) in LODE.INI, the kernel reads multitasking's resident part from `LODEMT.SYS` at start-up. Any other value leaves it off. It needs EMS, and enough of it (3 pages or more) for the disk cache to be there. With less, or with no EMS, it stays off without a word: System will say so in M7. A `-dNOTC` build (no disk cache) has none of it. There is one task, the Executive, and nothing switches yet. LCMD's new `TASKS` lists the tasks:

```
A:\>tasks
  0  Executive (in front)
```

With the switch off, `TASKS` says `Multitasking is off (MULTITASK=1 in LODE.INI)` and sets ERRORLEVEL 1. `TASKS` sets CF before the call, so under another DOS, which leaves the flags alone for a call it doesn't have, it reports the same.

**How:** `KMT.INC`, with the calls and the task record in `MTAPI.INC` (shared with LCMD).
- **Reading the switch:** `md_boot`'s search for `MDISK=` became `ini_key`, which `md_boot` now uses for both settings, before M: is made.
  - After PR #42 merged, `ini_key` moved beside `ini_read` in KROM.INC. KSPLASH's `SPLASH=` and `PRINTER=` readers use it too, so there is one key scan instead of four copies of the loop.
  - `ini_read` now reads the LODE.INI files from the disks once per start-up, into `INI_BUF` at 1000:F000, and hands the later readers the same text. That's one read, not three: `pr_boot`, `sp_wanted` and `md_boot` each read both files before. `rs_boot` has chosen the "changes" drive by the first read, and nothing writes `INI_BUF` meanwhile; `test_splash`'s "MDISK= read after the picture" shows the text survives the picture. `md_boot` only runs when the disk cache is in EMS, which is where the "needs EMS" comes from.
- **`LODEMT.SYS`:** the resident part (section `mtt`, assembled from 0) is the last section of LODE.ASM's output. The build's `mkmt.py` cuts it off LODE.SYS into `LODEMT.SYS`, and writes its checksum into LODE.SYS's `mt_sum` (a 16-bit word, rotated left one bit before each byte is added; the Real column of LODE.MAP gives the places). So LODE.SYS carries only the start-up, and a build with the switch off never reads the file.
  - **Joshua's choice (2026-10-19):** the alternative was moving the 4 KB INI buffer out of the load segment. A file of its own frees the load image for good: everything multitasking adds from M2 on goes into LODEMT.SYS.
  - `mkmt.py` refuses a LODE.SYS that doesn't end with the part (one cut already), skips a `-dNOTC` build, and is deterministic: two builds give the same bytes.
- **`mt_boot`** (section `boot`: in the load image only) runs after M:. It:
  - opens `\LODEMT.SYS` on the drive started from (INT 21h 3305h, as `sp_load` finds LODE.PIC; R: when started from the ROM). No file: off, with nothing to undo;
  - puts it in a block of its own, owner 8, called "MT", at the very top of memory. A filler block takes everything but MT's paragraphs first, then goes. `mem_alloc` is first-fit, so MT only lands at the top if no free hole of its size sits lower down. That is always so at start-up, but `mt_boot` checks that MT's block is the last one, and frees it and stays off if not;
  - reads the file into it, and checks it read exactly `MT_LEN` bytes with the checksum `mt_sum` holds. A LODEMT.SYS from another build, a cut-short one or an empty one fails this: the block is freed, the file closed, and it stays off;
  - points INT 08h at `mt_tick`, which runs the BIOS's handler first and then counts the tick (M3 will switch tasks there);
  - turns `f_F0`'s first 5 bytes (`MOV AL,[BP+F_AX]` and `OR AL,AL`, checked in the listing) into a far jump to `mt_f0`. That routine handles AL=12h and otherwise does those two instructions and jumps back past them. KEMS patches `f_F0.lend` and `f_F0.back`, both further in, so they don't clash.
- **The API:** INT 21h AH=F0h, AL=10h and up. With the switch off, every one of them fails with CF set and AX=1 (`f_F0` sends unknown functions to `f_bad`), so the off state needs no code at all.
  - AL=12h, list: ES:DI = room for CX records of 16 bytes → CX = the number of tasks, the records filled in (as many as fit), AL = the front task.
  - A record: number (byte), state (byte), PSP (word), name (12 bytes, NUL-padded; a whole 8.3 name fills it with no NUL, so readers stop at 12).
  - M2 is expected to keep these 16-byte records for the API and give the task table its own, larger entries.

**A change from the approved plan: where the resident part goes.** The plan put the MT block between the root PSP and the UI block, inside KSEG's 64 KB, so that the kernel patches could be near jumps. M1 puts it at the top of memory and uses far jumps instead (5 bytes, the same size as the planned patch at `done`).
- Placing it low would mean moving the UI block after it is loaded.
- The UI block also needs 16 KB free right after it for a `.RUN` (`ui_room`), and a block there would make the UI move again on the first `.RUN`.
- At the top, the block never moves, and DOS programs still get a single block below it.

In M1 the UI goes on lending its directory buffer to DOS programs as before, so with the switch on DOS programs lose only MT's own block. Whether lending can stay on once tasks have regions of their own is for M2 to settle. The plan assumed not (7.5 KB); regions allocated downward from MT's block would let it stay.

**Cost:**
- **Switch off:** nothing resident, and LODEMT.SYS isn't read. `image_end`, `bss_end`, `ui_keep_end` and MEMSZ from the Executive are main's, unchanged, and `test_mt` pins all of them (44F0h, 7B40h, 6CE4h and 561.5 / 577.6 KB with PrtSc's printing, PR #42; 42B0h, 77E0h, 6CB4h and 562.4 / 578.5 KB since the audit's kernel batch; 42B0h, 77E0h, 67A8h and 563.7 / 579.7 KB since its UI batch; 3EA0h, 73D0h, 6134h and 566.3 / 582.4 KB since its medium-risk batches).
- **One exception: LCMD.** It is 173 bytes bigger (`TASKS`). It keeps 11 paragraphs (176 bytes) more while a program runs from its prompt, so such programs get that much less, switch on or off.
- **Switch on:** MT's block is 14 paragraphs plus its MCB, 240 bytes. A DOS program gets 577.4 KB instead of 577.6. `test_mt` checks the free paragraphs exactly.
- **Files:**
  - LODE.SYS is 48,976 bytes (+308 over main's 48,668, all in the load image: `mt_boot` and the MULTITASK= parse, less the key-scan loops `ini_key` replaced);
  - LODEMT.SYS is 221 bytes;
  - LCMD.COM is 11,143 bytes;
  - ROM 1 holds LODEMT.SYS too (and PS.PRN, from #42), and has 22,528 bytes left.

**Tests:** `tests/test_mt.py`, 50 checks, with `MTPROBE.COM`, which calls F0h AL=00h, 10h, 11h, 12h (with no room), 13h and FFh and prints CF, AX, BX and CX for each.
- **The files:**
  - LODEMT.SYS is exactly the resident part, cut off the end of LODE.SYS;
  - `mt_sum` is its checksum;
  - the start-ups end below 1000:F000, where LODE.INI is read;
  - LODE.SYS is under the ROM loader's 64 KB;
  - with the switch off, the three map values above are pinned.
- **LODEMT.SYS missing, one byte changed (another build), a byte short, or empty:** off. Memory is as with `MULTITASK=0` (the freed block merges on the next allocation), no file is left open, and INT 08h and `f_F0` are untouched. The file as built turns it on.
- **Off, in eleven ways:** no LODE.INI; no line; `0`, `Off`, `No`, `2`, `10`, `Yikes`, `One`, and an empty value; and `1` without EMS. In each:
  - there is no MT block;
  - INT 08h is still the BIOS's handler (segment and offset);
  - `f_F0`'s 5 bytes are as in LODE.SYS.

  Two of these cases also run MTPROBE and `TASKS`: AL=00h answers, the rest fail with AX=1, and `TASKS` reports that it's off and sets ERRORLEVEL 1.
- **On:**
  - The block: MT is the last block, owner 8, ending at A000h, after one free block.
  - The hooks: INT 08h goes through `mt_tick` and on to the BIOS's handler, and `f_F0` jumps to `mt_f0`. Task 0's PSP is `root_psp`.
  - Timing: `mt_tick` counts the same ticks as the BIOS over 2 s.
  - MTPROBE through `mt_f0`: AL=00h still answers 4F47h/0201h (so `OR AL,AL` is redone), the unknown calls still fail, and AL=12h with no room returns a count of 1.
  - `TASKS` lists the Executive, in front.
  - The help window's save-under is lent (AL=2; with EMS, `ems_lend`'s block) and given back (AL=3, `ems_su` clear), twice.
  - The setting's spellings: `Yes`, `on`, `1` with no line end, `yes` with a blank after it, and a `MULTITASK=0` that is only part of another line's value.
  - `MDISK=512` and `MDISK=0` beside it. MT is at the top in every case.
- **DOS programs:** free memory is exactly 15 paragraphs less with the switch on. MEMSZ from the Executive is 577.6 KB with `MULTITASK=0`, main's figure. TESTDOS, EMSTEST and CACHETST pass. Afterwards MT is still at the top, still ticking, and F0h still goes through it.
- **From the ROM** (the 1520's own start-up): `C:\LODE.INI` with `MULTITASK=1` turns it on, and `TASKS` lists the Executive. With the ROM's own settings, it is off.

**The load image's ceiling, settled.** LODE.SYS is loaded at 1000:0000, and LODE.INI is read into 1000:F000 (`INI_BUF`; KSPLASH's `SP_BUF` is there too), so the start-ups must end below 61,440 bytes into the file. The plan expects multitasking to add 8–12 KB. Moving its slow paths into an EMS page would not have helped here, because that image would still travel inside LODE.SYS. With the resident part (and, from M2, the EMS part too) in LODEMT.SYS, LODE.SYS grows only by `mt_boot`, and `test_mt` checks the start-ups' end.

## M2a: tasks, switched when one waits for a key (2026-10-19)

M2 was split in two: **M2a**, tasks and switching (this part), and **M2b**, the front: the CODE-Tab hot key and each task's screen, saved and restored in EMS. The plan's hardware check for M2 moves to M2b, since there is no hot key to press yet. All of M2a is in LODEMT.SYS; the kernel gains one label (`k_retf`, on `run_ui`'s RETF) and no bytes.

**What it does:** a program can start another as a task, INT 21h F0h AL=10h (`MT_SPAWN`, MTAPI.INC). The task runs when the running one waits for a key in DOS, and the tasks take turns that way. Only the front task reads keys. Another that waits for one waits without reading, until it is brought to the front (F0h AL=13h, `MT_FRONT`, at the next key wait). Each task has its own memory, current directories on A: to D:, DTA, console line, PSP and EMS mapping. When its program ends, the task ends: its region is freed, and the handles its stub inherited are closed.

**The limit, plainly:** a task switches only when one waits for a key *inside DOS* (INT 21h AH=01h, 07h, 08h, 0Ah, or a read from CON).
- The Executive and LCMD's prompt don't: they ask whether a key is there (INT 16h AH=11h, INT 21h AH=0Bh) and halt in their own loops. So with either in front, nothing switches.
- A task that computes without waiting keeps the machine until it waits or ends.
- M3's preemption (INT 08h at safe points) removes both limits.
- Until M4a the tasks also share one screen: what a background task prints lands on the front one's.
- Only DOS's own key waits keep a background task off the keyboard. One that hasn't reached its wait yet can still see or take the front task's keys:
  - INT 21h AH=0Ch flushes the BIOS's key buffer;
  - AH=0Bh, and AH=06h with DL=FFh, see a key typed for the front task. AH=06h then waits in the background until it is brought to the front;
  - INT 16h, called directly, reads them.

  M4b's INT 16h hook closes this, except for the calls it leaves as they are (through a TSR's hook loaded after MT, from an interrupt handler, a read with interrupts off: M4b).
- A task that waits for a key inside a nested INT 21h (an INT 24h handler asking for its answer with AH=01h, say) can't be switched from there. It reads the keyboard, in the background too: the prompt is answered, then it waits like the others.

**Not per task yet (kept for later milestones, stated here so nobody relies on them):**
- **M: and R:'s current directories** are shared by all tasks. M: is turned on and off at run time (INT 67h AH=5Bh) and its drive entry moves with it, so it isn't in the fixed list of per-task variables. Sharing one directory is consistent, so nothing is damaged.
- **INT 22h–24h** are global (per-task vectors are M5's). When a program ends, the kernel puts back the INT 23h/24h it found at its start. So a task can undo another's handler, or bring back one that has since ended; ^C or a disk error in one task runs whichever handler is in the table.
- **A directory a waiting task is in.** Its directory is saved as a cluster number. So don't remove a directory (RD) a waiting task is in, and don't change the disk in a drive where one has its current directory. Its next file operation there would use a cluster the disk no longer has as that directory, and could damage the disk. The fix (a per-drive mount count in each task's context, and RD refusing any task's directory) needs two more patches in the kernel and comes with its own change.
- **INT 21h AH=52h's** first MCB is the whole memory chain's, not the running task's own.
- **A program whose start fails:** `MT_SPAWN` succeeds once the task is made. If its program isn't there, or EXEC fails, the task ends at once, unseen; its exit code (`TE_EXIT`) is kept, but no call returns it until M7's WAIT.

**How:**
- **The key wait:** `kbd_get.k` (`MOV AH,1` / `INT 16h` / `JNZ .have`, 6 bytes at 06BCh, checked in the listing and by `test_mt`) becomes a far jump to `mt_kwait`.
  - There, the front task looks for a key. If none is there, it lets a task that is ready run, and if there is none, it goes on to the kernel's own wait (PrtSc, INT 28h, HLT).
  - A background task waits without looking. Its state becomes "waiting for a key" (`TS_WAITK`), and a ready task, or the front one, runs.
- **Switching** (`mt_switch`, `mt_load`) is done only inside INT 21h (`indos` 1, never in a nested call such as an INT 24h answer), and only at `mt_kwait` or when a task ends. A task's context, its TX, holds:
  - its SS:SP;
  - the EMS windows' 4 page registers (the kernel keeps no copy of them: KEMS reads the ports);
  - the kernel's per-task variables (`mt_ranges`): `indos`, the break and console state (`brkflag`..`onebyte`), `first_mcb`, the drives' current-directory clusters and strings, `cur_drv`, the DTA and the file and console-line state (`dta`..`rw_t0`), `cur_psp`, `last_exit`, `term_keep`;
  - the kernel stack's slice from SP up, because a task waits inside INT 21h.

  The slice measured 32–42 bytes for every console read; a TX has room for 256, and `mt_kwait` doesn't switch if it would need more.
- **A task's region** is carved from the top of the highest free block that has room (the arena walked from its first MCB, free neighbours merged, a chain gone bad refused), downward from MT's block. It is a block of its own, owner 8, "T1".."T7", holding:
  - its TX (42 paragraphs);
  - its stub, a PSP and a few instructions at 100h: EXEC the program, then F0h AL=11h (`MT_END`). `make_psp` (called through `KCALL`) gives it the spawner's handles. The stub is its own parent: its PSP:0Ah points at its `MT_END`, and its PSP:2Eh/30h at its own EXEC call's frame, where INT 21h puts it on the stub's stack (as EXEC itself sets it once the program is loaded). So if it is ended itself (Abort on a disk error while its EXEC reads the program), `terminate` lands on `MT_END`, not on the spawner, which may have no frame to go back to, or may have ended;
  - a copy of the spawner's environment (up to 1 KB), because the spawner may end first;
  - the task's own MCB chain, its `first_mcb`, ended by a 'Z' in the region.

  The task's program gets its memory from that chain (a .COM takes all of it, as it would take all memory). Task 0's TX is in MT's block (`mttbss`).
- **The UI's lending** of its directory buffer stays on. Regions come from the top of memory, away from the UI block, so they don't stand in the way of taking the buffer back.
- **Ending** (`MT_END`, from the stub only): `close_all` on the stub's PSP (`KCALL`), the exit code kept, the region freed, and the next task runs without its context being saved. A program that stayed resident (AH=31h, `last_exit` AH=3) keeps the whole region, renamed "TR": its hooks may point into it. That costs the region (its TX, stub and the unused rest of its memory) until M5 handles it.
- **Calling the kernel:** `KCALL r` pushes MT's far return, then the offset of `k_retf`, and jumps to KSEG:r. The routine's near RET goes to the RETF, which comes back to MT.
- **The API** (MTAPI.INC):
  - `MT_SPAWN`: DS:DX = the program (with its extension), ES:BX = EXEC's block plus a word of paragraphs (0: 64 KB) and a flags byte (`SPF_FRONT`). → AL = the task, or CF with AX = 4 (8 tasks already) or 8 (no room).
  - `MT_FRONT`: BL = a task.
  - `MT_LIST` records now carry each task's state (1 running or ready, 2 waiting for a key).

**Cost:**
- **Switch off:** nothing. `test_mt` pins the map and MEMSZ; LODE.SYS grows 48 bytes, all in `mt_boot`.
- **Switch on:** MT's block is 155 paragraphs plus its MCB, 2.4 KB; a DOS program gets 575.2 KB instead of 577.6. Each task takes its region: 1.5 KB plus its environment, plus its memory (64 KB unless asked).
- **Files:** LODEMT.SYS is 1,803 bytes; ROM 1 has 20,992 bytes left.

**Tests:** `test_mt.py`, 77 checks. The new groups are `t_tasks` and `t_ends`, with three test programs:
- `MTLAUNCH` starts the tasks it is given (`/F`, `/M:n`, `/R:n`), brings one to the front (`/G:n`, through `MT_FRONT`), lists them, then waits for a line itself;
- `MTLINE FILE` writes a line to FILE;
- `MTCWD DIR FILE` changes directory, waits for a key, then writes its current directory.

What they check:
- **Two MTLINE tasks:**
  - they run to their key waits and wait there in the background;
  - their regions are T1 and T2, under MT's block;
  - task 1 is brought to the front, "hel" typed, then task 2 gets "world" and ends;
  - task 1, at the front again, gets "lo": its half-typed line survived ("hello");
  - afterwards memory (free neighbours merged) and the SFT's reference counts are exactly as before, and the prompt answers.
- **The front:** `/F` brings the second task to the front; so does `MT_FRONT` (`/G:2`). With task 8 or a free one, `MT_FRONT` fails (MTPROBE).
- **MTCWD:** each task keeps its own directory and writes its file there; the prompt's stays A:\.
- **Errors:** no room gives error 8, and so does a size past 1 MB; with 8 at once, tasks 1–7 start and the eighth gives error 4. Each of the 7 then gets its own line in turn.
- **Endings:**
  - a program that isn't there: the task starts and ends, and everything is as before;
  - the spawner ends first: its task gets its line later, at another key wait;
  - a read error while the stub EXECs its program, answered Abort: the stub ends itself, its task with it, and MTLAUNCH and the prompt go on. EXEC's own entry for the file it reads stays taken: the kernel's EXEC doesn't give it back when it is aborted, with multitasking on or off. That is a kernel bug of its own, outside multitasking;
  - TSR.COM in a task: its region stays as "TR", and the next task's region goes below it.
- **Switch off:** MTLAUNCH reports error 1.
- **The patches:**
  - the 6 bytes at `kbd_get.k` are as expected in LODE.SYS, patched with the switch on, and untouched with it off or with a bad LODEMT.SYS;
  - task 0's TX sits on the paragraph after the image.

**The review** (three reviewers, 2026-10-19) found what the sections above now describe. Two crashes it found and reproduced are fixed: Abort while a stub EXECs its program (the stub had the spawner as its parent, and `terminate` went back through a frame the spawner never had), and a program staying resident in a task (its region was freed under it). Also fixed:
- a background task waiting for a key in a nested INT 21h hung the machine;
- the EMS mapping wasn't part of a task's context;
- a new task got the spawner's half-read console line;
- a command tail longer than 126 characters kept its old count;
- an environment segment of 0 copied the interrupt table;
- `mt_carve` left an MCB of no paragraphs.

## M2b: the front, CODE-Tab, and each task's screen (2026-10-19)

**What it does:** CODE-Tab brings the next task to the front, in turn (0, 1, 2, ..., back to 0), and each task has a screen of its own. The front task's screen is the one shown. When another comes to the front, the screen is kept in the first task's own EMS pages, and the new front task's is put back.

**Departure from the plan:** the plan had CODE-Tab bring up the Executive's Tasks window, and CODE-Tab again go back. The Tasks window is M7's (TASKS.RUN). Until then CODE-Tab cycles through the tasks, and M7 decides what it does then.

**The limits, plainly:**
- **CODE-Tab works only while a task waits for a key in DOS**, where tasks switch (M2a). Anywhere that only asks whether a key is there, the BIOS drops CODE keys (INT 16h AH=01h; only AH=10h/11h give them), so the key is lost:
  - with the Executive or LCMD's prompt in front, it does nothing;
  - a program that asks before it reads loses it too: INT 21h AH=0Bh, AH=06h with DL=FFh, AH=0Ch's flush, and IOCTL 4406h on CON all ask;
  - a program that reads keys through INT 16h itself never gets to DOS's wait, so its tasks don't switch at all.

  M4b's INT 16h hook (catching the key before anyone asks) lifts this. (This first said M3 too; it doesn't: see M3's limits.)
- **A small race:** a CODE-Tab typed in the instant between `mt_hot`'s look and the front task's own INT 16h AH=01h is dropped there; pressed again, it works. M4b's hook narrows it (M4b's limits).
- **A background task's output still lands on the front screen** until M4a's hook: it is kept with whichever task's screen is shown.
- **Before M4a: a task's screen, the first time it came to the front, was mode 3 and clear.** What it wrote before then went to the front task's screen. M4a gives each task its screen from the start. A program that sets a graphics mode should come to the front first (`/F`).
- **The mouse:** a DOS program's INT 33h pointer is hidden while the screens change, at CODE-Tab and when the front task ends (AX=2, then AX=1, as Resident Claude does), but there is one mouse state for all tasks until M4c. The Executive's pointer is drawn into its screen, which comes back byte for byte.
- **What isn't kept:** a palette written straight to port 3D9h without the BIOS's copy (40:66h), and port 3D8h's settings beyond the mode (say blink off).
- **A program that frees MT's pages:** EMS's AH=45h frees any handle, for anyone (CLAUDE /U frees its own that way, so KEMS can't refuse). EMS hands out the lowest free number next, so a freed number comes back soon. MT guards in two ways:
  - before each map, it checks that the handle is still its own: open, 2 pages, owner 0. A program's own allocation has its PSP as owner;
  - when `MT_SPAWN` gets a number that another entry still holds, that entry keeps none.

  Either way that task keeps no screen from then on: nothing is copied, it comes to the front clear, and MT never frees that number. What it can't tell is a 2-page allocation made with owner 0 (from code outside the current program's memory, an interrupt handler's, say) on a number it lost.
- **The 1520 itself:** the key was first CODE-]. On the 1520 that takes CODE-Shift-], and its code depends on the order the keys go down. So Joshua chose CODE-Tab: `os/claude/KEYCODE.COM` shows it as A500h there (INT 16h AH=10h), every time. Its scan code, A5h, is one AH=01h drops, like the CODE keys. The words are in one place, `mt_hotk` (A500h, and A5F0h in case a BIOS keeps it with F0h).

**How:**
- **The key:** `mt_kwait`, on each pass (each key wait, and each tick while one waits), looks through the BIOS's key buffer for A500h (or A5F0h). It looks before its own INT 16h AH=01h, which would drop the key.
  - **Order:** the key counts only when nothing is ahead of it but keys AH=01h drops anyway. On the 1520's BIOS (as pcemu models it) those are scan codes 85h and up but E0h's (F11, F12, Ctrl-Up and the like) and CODE keys (xxF0h with a scan code). Keys typed before it are the front task's, and it reads them first; CODE-Tab then counts at its next pass.
  - **Taking it:** `mt_hot` takes the key out (the words after it move back, as Resident Claude's `r_hot` does) and asks for the next task after the front one (`mt_swreq`; pressed again before that happens, the one after that).
  - **The look is bounded:** at most 16 words, so a buffer whose pointers a program has spoiled isn't followed round.
  - **Not from INT 08h:** there the buffer could be changed under the BIOS's own INT 16h code on the 1520.
- **The switch** is made only where `mt_kwait` could switch tasks (`mt_can`). A request made in a nested INT 21h (an INT 24h answer) waits until then, so a task never reads keys in the background with another task's screen shown.
- **The screens:** each task has 2 EMS pages, 32 KB, enough for any mode (the 1520's 640 × 400 is 32 KB at B800h).
  - They are allocated with INT 67h when the task starts (task 0's in `mt_boot`) and freed when it ends.
  - They are MT's (owner 0), not the program's, so ending the program doesn't free them.
  - If there are none, `MT_SPAWN` fails with error 8 (its region given back), and with none for task 0, multitasking stays off.
  - `mt_scrsv` keeps the screen: B800:0000's 32 KB into the pages, mapped into windows 0 and 1 (INT 67h AH=44h, the windows' page registers put back after), and the BIOS's video data (40:49h–66h, 30 bytes) into the task's TX.
  - `mt_scrld` puts one back, in Resident Claude's order: the mode (INT 10h AH=00h); for CGA's modes, port 3D9h from 40:66h, before the screen; the 32 KB; the BIOS data. In text modes it then sets the page shown (AH=05h) and the cursor's shape and place. A task whose screen was never kept gets mode 3, clear.
  - When the front task ends, task 0 comes to the front with its screen.
- **The entries** grew to 32 bytes (`TE_SH`, the pages' handle; `TE_SF`, a screen kept), and a TX to 44 paragraphs (`TX_VID`).

**Cost:**
- **Switch off:** nothing. `test_mt` pins the map and MEMSZ. LODE.SYS grows 32 more bytes, all in `mt_boot` (19 of code, the rest alignment).
- **Switch on:** MT's block is 201 paragraphs plus its MCB, 3.2 KB, so a DOS program gets 574.4 KB instead of 577.6.
- **Each task's region** is 97 paragraphs (1.5 KB) plus its environment and memory.
- **EMS:** 32 KB per task, task 0 included.
- **Files:** LODEMT.SYS is 2,505 bytes; ROM 1 has 20,480 bytes left.

**Tests:** `test_mt.py`, 98 checks. The new group is `t_front`, with two new test programs:
- `MTMODE MM FILE` sets video mode MM, fills the 32 KB with a pattern, waits for a key, then writes "ok" to FILE if the pattern is all still there;
- `FREEH N` frees EMS handle N, as a program that frees a handle not its own might.

The checks:
- **The cycle:**
  - each task takes 2 EMS pages;
  - with two MTLINE tasks, CODE-Tab while MTLAUNCH waits brings up task 1: the key is gone from the buffer, and the screen is clear in mode 3;
  - "hel" typed shows there;
  - CODE-Tab gives task 2 (clear), then task 0 with MTLAUNCH's screen, cursor and BIOS video data exactly as they were, then task 1 with "hel".
- **Ending:** task 1 gets "lo" and ends, and task 0 is in front with its screen. When all have ended, memory, files and EMS pages are as before.
- **Graphics:**
  - MTMODE in mode 40h, in front: CODE-Tab to task 0 (mode 3, MTLAUNCH's screen), then CODE-Tab back gives mode 40h and all 32 KB as they were, and MTMODE finds its pattern intact.
  - In mode 4, with palette 25h, 3D9h gets 25h after the mode set and before the screen, and 40:66h is 25h.
- **Order:**
  - "xy", CODE-Tab, "z", Enter typed ahead: MTLAUNCH reads "xy", and task 1 gets "z";
  - CODE-? or Ctrl-Up ahead of CODE-Tab (keys AH=01h drops) don't hold it back;
  - a character F0h (00F0h) ahead of it is MTLAUNCH's. Each time task 1 gets "z".
- **Other cases:**
  - with one task besides task 0, CODE-Tab goes to it and back;
  - at LCMD's prompt, with a task waiting, CODE-Tab does nothing and is gone; with MTLAUNCH waiting, it brings the task up;
  - `/F` gives the task a screen of its own, and task 0's comes back when it ends.
- **EMS:**
  - FREEH frees task 0's handle:
    - at the next CODE-Tab it keeps no screen, comes back clear, and nothing leaks;
    - the same when its screen was kept and the handle goes while it is in the background;
    - when the number is then given to a new task, task 0 keeps none, and the new task's screen isn't written over;
  - with no EMS left for a task's screen, MTLAUNCH gets error 8, and memory, files and EMS are as before;
  - with `MDISK=` taking all of EMS, multitasking stays off;
  - the abort and TSR endings give their pages back.
- **The checks can fail:** each of these, broken on purpose, fails its check:
  - the screen copy in `mt_scrld`;
  - the key's order, and each of its exceptions (Ctrl-Up's range, the F0h character);
  - the failed-map test;
  - the spawn's clearing of a number given out again;
  - the 3D9h write;
  - `mt_boot`'s allocation;
  - the key taken out;
  - the AH=45h at a task's end.

**The review** (three reviewers, 2026-10-19) found no bug in the normal paths. Fixed from it:
- keys typed before CODE-Tab went to the new front task;
- a freed screen handle wasn't noticed (MT copied through whatever pages were mapped, then freed the number again);
- the buffer scan wasn't bounded;
- the DOS program's pointer wasn't hidden;
- the page shown wasn't set again;
- BX was trusted across the mode set.

It also added the checks for 3D9h, the cursor, EMS running out at a spawn, `/F`'s screen, and the prompt with a task waiting.

A second look at those fixes found two gaps, both reproduced, now fixed and tested:
- **A reused number:** a freed number given out again (by `MT_SPAWN` itself) passed the failed-map test.
- **The order rule was too narrow:** Ctrl-Up or F11 ahead of CODE-Tab held it back, and then AH=01h dropped both; a character F0h was skipped as droppable.

It also had the pointer hidden when the front task ends.

Not testable in pcemu: the page shown (AH=05h; pcemu shows page 0 whatever), BX across the mode set (pcemu's INT 10h keeps it), the INT 33h hiding (no test program uses INT 33h), and the owner check against a program's own allocation.

## M3: preemption, at the timer's tick where it is safe (2026-10-20)

**What it does:** a task no longer has to wait for a key to let another run. Each has a turn of timer ticks: 2 in front, 1 in the background. At the end of a turn, MT switches to the next ready task, provided the running one is at a safe point. A task interrupted just after a HLT is idle, so its turn ends at once. A front task waiting for a key in the background gets the next turn as soon as a key is in the buffer.

So, unlike M2a:
- tasks run with the Executive or LCMD's prompt in front;
- a task that computes without waiting no longer keeps the machine;
- a new task starts within a tick, not at someone's key wait.

**Where it switches:**
- **At the tick** (`mt_tick`, after the BIOS's own INT 08h handler: the tick counted, INT 1Ch run, the EOI sent).
- **On the way out of INT 21h**, if a turn ended while the task was inside it. The common exit's `MOV SS,AX / MOV SP,BX / POPA` (5 bytes at `done.sw`, checked in the listing and by `test_mt`) becomes a far jump to `mt_exit`. Without it, a task that lives in DOS calls would hardly ever be caught outside them. `ctrlc` has a copy of those 5 bytes (`ctrlc.sw`), left alone.

**A safe point** (`mt_safe`), checked against the interrupted (or calling) code:
- no INT 21h under way (`indos` 0): the kernel is never preempted;
- interrupts were on, and no other hardware interrupt is in service (the PIC's in-service register, read as `capture` reads it);
- CS below A000h (not the BIOS, the ROM, the EMS frame or Resident Claude's console), and not the kernel's or MT's own segment;
- in the UI's segment, only at its two idle HLTs (`..@ui_idle` in `ui_event`, `..@ui_sidle` in the saver). These are labels the UI gained for this, at no cost in bytes. So the Executive is switched from only while it waits, never in the middle of drawing or a directory load;
- no INT 33h event handler running (the UI's `m33_busy`);
- SS and CS in the task's own memory (`mt_mine`), so not a TSR's or a driver's stack or code:
  - a task's: its region;
  - task 0's, while the Executive runs: the UI's block;
  - task 0's, while it runs a program (LCMD, or one started from the Executive): a block that program owns, found by walking the arena.

  CS in the UI's segment has already passed the idle-HLT rule, and isn't checked again. That is how LCMD's screen saver, the UI's code called from LCMD, is switched from.

A turn that ends anywhere else waits, as `mt_pend`, for the next safe tick or INT 21h exit. (On INT 21h's way out the rules see the INT 21h caller only: see the limits for a task's own timer hook.)

**A hook on INT 08h goes ahead of `mt_tick`,** however it is set (AH=25h or the vector table), as in DOS. What `mt_tick` then finds interrupted is that hook, not the task, so while INT 08h isn't `mt_tick` the tick doesn't switch at all. INT 21h's way out still does, as long as the hook chains on to `mt_tick` (whatever AH=35h or the table gave it). See the limits.

**Disks written behind DOS's back:** DEFRAG and System (resizing M:) ask INT 21h F0h AL=1 how many files are open on the drive before writing its FAT and directories themselves. With another task there, MT answers at least 1, since that task could open one meanwhile. So DEFRAG only shows the map, and System won't resize M:, while tasks are alive.

**How:**
- A task switched from outside INT 21h keeps no kernel-stack slice: `mt_switch` saves one only when `indos` is non-zero, and a TX notes its length (0 here).
- It is resumed inside `mt_tick` or `mt_exit`, which then restore its registers from its own stack and return to it with IRET. A tick that finds MT's own code interrupted leaves at once: in the last two instructions of a resume that keeps the new turn whole, and anywhere else in MT `indos` is 1 anyway.
- `mt_preempt` chooses the next task: the front one, if it waits for a key that is in the buffer; else the next ready one, in turn. None: the running one goes on.
- `mt_load` starts each turn.

**The limits, plainly:**
- **Background output still lands on the front screen** until M4a's INT 10h hook, now while the front task runs too. Background tasks should write to files, as the tests' do.
- **Background tasks can read the front task's keys.** M2a's limit (AH=0Bh, AH=06h with DL=FFh, AH=0Ch, INT 16h directly) now applies while the user types into the Executive or LCMD too. M4b's INT 16h hook.
- **CODE-Tab still needs a DOS key wait** (M2b), contrary to what the M2b section first said. M3 doesn't change that, because the Executive and LCMD poll for keys, and that poll loses CODE keys. M4b's INT 16h hook lifts it.
- **A program waiting in the BIOS** (INT 16h AH=00h called directly, as many do) can't be preempted on the 1520: the tick finds CS in the ROM. The other tasks wait until it has a key. (pcemu blocks such a call at the program's own INT 16h, so there it can be preempted; `test_mt` notes the difference.) M4b's INT 16h hook lifts this too.
- **The idle test is a guess:** the byte before the interrupted instruction is F4h. Any instruction ending in that byte (`ADD SP,-12` is 83 C4 F4) ends that turn early. That costs the task some of its share, never safety.
- **The idle front task** sleeps out the rest of the tick it is given (it HLTs; MT only notices at the next tick). With the Executive or the prompt idle in front, a background task gets 55–65% of the processor in pcemu, not all of it.
- **Index and data port pairs** (the CRTC's 3D4h/3D5h, the PIT's latch and its two reads): a task switched from between the two can find the index changed by another. `mt_safe` itself leaves the PIC reading its request register, as the BIOS does. M4a's screen virtualisation, for the CRTC (see M4a).
- **The EOI's order:** the in-service test assumes the BIOS's INT 08h sends the EOI before it returns. pcemu's does, and so does the 1520's (read in its ROM); M9 checks it on the machine.
- **A timer hook stops the tick switching.** While any program or TSR has INT 08h hooked (a clock, a spooler, a game), only INT 21h's way out switches. So a task that computes without calling DOS keeps the machine until the hook goes, or until it calls DOS. A hook that doesn't chain on stops `mt_tick` altogether, as it stops the BIOS's tick in DOS. M5's per-task vectors lift this: each task's own hooks run only while it does, inside `mt_tick`.

  M3 first tried keeping INT 08h MT's by catching AH=25h and 35h for it, so a hook set that way would run inside `mt_tick`. That one global chain, mixed with programs that read or write the vector table themselves, gave two re-reviews four ways to hang the machine or lose `mt_tick` for good. So it was taken out again, and the job is left to M5's per-task vectors.
- **A task's own timer hook that calls DOS** can be switched from on that INT 21h's way out. The rules are checked against the hook, the INT 21h caller (its own code, its stack), not against what the hook interrupted underneath. That could be a TSR's code or, on the 1520, the BIOS's, which another task could then enter again. It needs a program whose own INT 08h handler chains on and then calls INT 21h. A TSR's hook doing so is refused (its CS isn't the task's). M5 runs a task's hooks inside `mt_tick`, where what was interrupted is known.
- **Vectors are global until M5:** two tasks that hook the same vector and end out of order (the first to hook ends first and puts back what it found) leave it pointing into the other's freed memory. For INT 08h that hangs the machine once the memory is used again. DOS, running one program at a time, never sees that order. Load programs that hook vectors one at a time, or as TSRs before starting tasks.
- **C:'s INT 25h/26h** run kernel code outside INT 21h. An INT 24h handler raised from inside them (a disk error) could be preempted with that code's state half used. That needs a disk error on C: during INT 25h/26h. M5.
- **Resident Claude's console** runs at E000h, so it is never preempted. But CLAUDE /R doesn't yet hold switching while it is up (the plan's `mt_hold`, M7).
- **The UI's code in two tasks:** LCMD started as a task runs the Executive's screen saver in that task (it asked F0h AL=5 once, at its start), while the Executive is task 0. And the Executive, in the background, still draws its clock. Both are rare in M3 (tasks are started with MTLAUNCH); M7 gives the Executive its task list and the saver its owner.

**Cost:**
- **Switch off:** nothing. `test_mt` pins the map and MEMSZ. LODE.SYS grows 16 bytes, in `mt_boot` (the new patch). The UI's two labels, KCORE's `done.sw` and `ctrlc.sw` cost no bytes.
- **Switch on:** MT's block is 238 paragraphs plus its MCB, 3.7 KB, so a DOS program gets 573.9 KB instead of 577.6.
- **A task's stack:** switching from outside INT 21h, MT uses at most about 44 bytes of the task's own stack below its SP at the tick (the interrupt's 6 included), and 56 on INT 21h's way out (the 26-byte INT 21h frame included). `test_mt` measures 42 and 54 at the start of every block run on the task's stack meanwhile (MT's, the kernel's, the BIOS's, an interrupt's); a block's own pushes add 2.
- **Files:** LODEMT.SYS is 3,093 bytes; ROM 1 has 19,456 bytes left.

**Tests:** `test_mt.py`, 122 checks. The new groups are `t_preempt` and `t_rules`, with two new test programs:
- `MTSPIN T CNTFILE [mode]` counts for T ticks of the BIOS's clock, then writes its count. It prints nothing. Its modes: D, an INT 21h call each count; W, a 64-byte record written to a file each count; C, the INT 21h call with interrupts off; S, its stack outside its memory (B800h) meanwhile; F, its stack in a block it took and gave back (free memory); R, INT 62h (MTHOOK S's service) each count; H, its own INT 1Ch handler (STI, then INT 21h); T, its own INT 08h handler, written in the vector table; O, no counting, the count is F0h AL=1's answer.
- `MTHOOK` is a TSR that hooks INT 08h with AH=35h and 25h (STI, then PUSHF / CALL FAR). `MTHOOK S` is one with an INT 62h service instead, which waits 2 ticks with interrupts on.

The checks:
- **Spinners:** two take turns, about half each of what one counts alone, on a floppy 300 KB full. With one in front (turns of 2 ticks against 1), it counts about twice the other's.
- **DOS calls:** the same with an INT 21h call each count, with switches on INT 21h's way out among them.
- **Files:** two writers at once: both files whole.
- **A key for the front task:** with two spinners behind it, MTLAUNCH gets Enter within 3 ticks.
- **In front:** with LCMD's prompt in front, a spinner runs most of the time. With the Executive idle in front, more than 1.5 times what it counts alone in a third of the ticks. With the Executive busy (moving its selection 120 times), it still runs, and the Executive is still there.
- **An audit hook** checks every time `mt_safe` says yes (several hundred) against every rule above, independently: it reads the interrupted CS:IP and flags from the frame on the task's own stack, tells the tick from INT 21h's way out by the return address, and finds the task's own memory from the arena itself. It also measures MT's stack use at every step.
- **Each rule met** (`t_rules`), counting the times `mt_safe` refused for that rule alone:
  - an INT 33h handler running: no switch at all;
  - a stack outside the task's memory, in a task, and in task 0 from the prompt (at B800h, and in free memory: the arena walked): never switched from there;
  - code outside the task's memory on its stack (MTHOOK's INT 62h): never switched from there;
  - INT 21h with interrupts off, and from INT 1Ch with IRQ 0 in service (with a switch made due on every way out, by the audit);
  - a task's own INT 08h hook in the vector table: no switch at the tick while it is there;
  - MTHOOK's INT 08h hook: `mt_tick` still runs every tick, the tick switches nothing, INT 21h's way out still does (spinners calling INT 21h take turns, others run one after the other);
  - F0h AL=1 with and without other tasks;
  - LCMD's screen saver: switched from at its idle HLT.
- **The patch:** `done.sw` pinned in LODE.SYS, patched with the switch on, untouched with it off; `ctrlc.sw`'s copy untouched.
- **The checks can fail:** each of these, broken on purpose, fails a check:
  - switching at the tick (the spinners, a key for the front task, the Executive, LCMD's saver);
  - switching on INT 21h's way out (the INT 21h spinners' way-out switches, and the rules met there);
  - the idle-HLT rule (the prompt, the idle Executive, LCMD's saver);
  - the UI's idle-point rule (the audit, with the Executive busy);
  - the front task's turn for a key (a key for the front task);
  - each safe-point rule: interrupts on, none in service (the audit, in `t_rules`); `m33_busy`; SS the task's own; CS the task's own (INT 62h); task 0's blocks found in the arena, in both directions (the prompt and LCMD's saver; B800h and free memory from the prompt); CS in the UI's not checked again (LCMD's saver);
  - the check that INT 08h is still `mt_tick` (a task's own hook), F0h AL=1's answer.

## M3b: each task's own coprocessor (2026-10-20)

**Why:** the 80287 holds one set of registers, its control word and its status. A task switched from in the middle of a calculation, at the tick since M3 or at a key wait since M2a, found them as the last task to use the coprocessor left them. Two tasks using it at once (the calculator in the Executive and a program behind it, say) would each corrupt the other's numbers.

**What it does:**
- When a task is switched from, `mt_switch` saves its coprocessor state (FNSAVE, then FWAIT, as Intel requires before anything else touches it) in its TX, with a flag (`TX_FPV`).
- `mt_load` puts back the incoming task's state (FRSTOR). A task with none saved yet (a new one) gets FNINIT's. That matters when a task ends straight into a new one; otherwise FNSAVE has already left the chip as FNINIT does.
- **Only with a coprocessor:** `mt_boot` reads INT 11h's bit once (`mt_fpu`). On the 1520 that bit is POST's own probe (its reset.asm). With no chip the 286's EM bit may be set and these instructions would trap, so MT doesn't touch it.

**The 287's errors, on the 1520:**
- **How they arrive:** the 1520 is wired like an AT (the GRiD BIOS's int75.asm). An unmasked error raises IRQ 13 and holds the 287's BUSY line to the 286 until the IRQ 13 handler (the BIOS's INT 75h) clears it with an OUT to port F0h. The 286 waits on BUSY before any coprocessor instruction but FNINIT.
- **So an error is drained first** (`mt_fdrain`). FNSAVE with interrupts off would hang the machine if an error were still pending: it would wait on BUSY for ever, and IRQ 13 couldn't run to clear it. So before a switch saves anything (at the start of `mt_preempt`, before it chooses the next task too; of `mt_kwait`'s `.park`, inside INT 21h, where nothing else can run meanwhile; and of `mt_end`), MT turns interrupts on and runs FNOP, which also waits on BUSY. A pending error is then delivered there, as in DOS, through INT 75h and INT 02h, to the task it belongs to, still the running one in every respect. After FNOP the 287 is idle, nothing of the task's in flight, so FNSAVE and FRSTOR, with interrupts off, can't be held up.
- **Coming back into the scheduler from there is safe.** The error's handler may read a key through DOS, or a tick may land in it, and so switch tasks. But nothing is half saved at that point: such a switch is the task being preempted in its own handler, like any other, and when the task comes back, the switch it was starting goes on from the beginning (`test_mt` shows it). An earlier version ran FNSAVE itself with interrupts on, and two re-reviews found ways a handler there could overwrite a context half saved; draining first leaves nothing to guard.
- **An error is delivered once.** Once the drain is done, its error has been delivered. MT then clears, in the saved status word, the error summary (ES) and the exceptions that weren't masked, so that FRSTOR doesn't raise IRQ 13 again at each of the task's turns. A 387-class chip in the 287's socket (a 287XL) works ES out from those flags, so clearing ES alone wouldn't do. The masked exceptions' flags stay.
- **Also found:** MT never cleared the direction flag. A task interrupted inside `STD ... REP MOVS` (a memmove running backwards, an editor scrolling) reached `mt_switch` with DF set, and MT's copies of its context ran backwards over the TX and the kernel's memory. That has been there since M3. `mt_switch` and `mt_load` now CLD; the task gets its own DF back from its interrupt frame.

**The coprocessor can't be a second thread.** It has no instruction fetch and no memory access of its own. It runs the instructions the 286 hands it, one at a time, while the 286 goes on with its own work until the next one. That overlap pays for the long instructions (divides, square roots, the transcendentals, a few hundred cycles each), and it is something a program arranges in its own code. A scheduler can't give the coprocessor a task.

**The limits:**
- **Every switch saves and restores it**, whether or not either task uses the coprocessor. That costs about 200 of the 287's cycles each way, plus 47 word transfers: 0.1 to 0.2 ms a switch, with about 18 switches a second at the tick and more at key waits. Saving only for tasks that use it would avoid that: the 286's TS bit traps a task's first coprocessor instruction to INT 7 (in real mode too, and pcemu shows it). But it needs an INT 7 handler of MT's, which isn't worth it at this rate.
- **INT 02h and INT 75h are global** until M5, so a task's error goes to whichever handler is hooked there, as with any vector.
- **A handler that doesn't free BUSY stops every task.** If IRQ 13 is masked, or a program's own INT 75h doesn't do the OUT to F0h, the drain's FNOP waits for ever with interrupts on. In DOS that stops only that program, at its next coprocessor instruction.
- **Between FNOP and CLI**, an interrupt whose handler uses the coprocessor with exceptions unmasked could leave a new error pending, and FNSAVE would then wait for it. Nothing on a 286 closes that last instruction's gap; the handlers that could do it are other programs' (an NMI is the same).
- **An error pending at a key wait inside an interrupt handler** (a key read from an INT 1Ch hook, say, with IRQ 0 in service) can't be delivered, so the drain's FNOP waits for ever. DOS hangs the same way, at that program's next coprocessor instruction.
- **The drain's stack:** interrupts taken in it (the BIOS's tick and INT 1Ch, IRQ 13's handler) use the task's stack from about 20 bytes below where it was interrupted at the tick (the interrupt's frame, `mt_tick`'s pushes, two calls), or 32 on INT 21h's way out (its 26-byte frame too), where before nothing nested.
- **The error wiring is read from the GRiD BIOS:** pcemu has no BUSY latch, and its coprocessor raises no IRQ 13 (`test_mt` raises one itself). The drain also relies on the 286 taking interrupts while it waits on BUSY, which the AT's design needs too. M9 checks a coprocessor error on the 1520 with a task behind it.

**Cost:**
- **Switch off:** nothing. `test_mt` pins the map and MEMSZ. LODE.SYS grows 10 bytes, in `mt_boot` (reading INT 11h's bit), within section boot's padding, so its size is unchanged.
- **Switch on:** each task's TX grows by 6 paragraphs (96 bytes: its flag, then the state, even-aligned), so a task's region is 103 paragraphs plus its environment and memory. Task 0's TX is in MT's block, now 250 paragraphs plus its MCB, 3.9 KB, so a DOS program gets 573.7 KB instead of 577.6.
- **Files:** LODEMT.SYS is 3,186 bytes; ROM 1 has 19,456 bytes left.

**Tests:** `test_mt.py`, 128 checks. The new group is `t_fpu`, with four new MTSPIN modes:
- P keeps its own values on the coprocessor (n and 2n in ST0 and ST1, n from its segment, and its own rounding in the control word, never FNINIT's) and checks them on every count. If any has changed, the count it writes is 0.
- I checks that the control word is FNINIT's (037Fh) before it uses the coprocessor.
- B counts with the direction flag set.
- E hooks INT 75h with a handler like the BIOS's (both PICs' EOI, then STI; without its OUT F0h and INT 02h, which pcemu doesn't need), which calls INT 21h and waits for the next tick, so that a tick lands in it.

The checks:
- Two P tasks switched at the tick all along: neither sees a change, and each counts about half of what one alone does.
- Task 0 (P run from the prompt) with a P task behind it: both kept.
- A new task (I) run straight after one that set its own control word and ended: FNINIT's, three times.
- INT 11h saying there is no coprocessor, with the 286's EM bit set so that any coprocessor instruction would trap: `mt_fpu` is 0, no INT 7, and tasks take turns as before.
- Two B tasks switched at the tick: they take turns, the machine intact (`t_rules`).
- An E task and a P task, the test raising IRQ 13 at the drain each time the E task is switched from, but not again in a drain inside its handler (pcemu's PIC delivers it there): the handler runs there every time, and is itself switched from, both at a tick in it and on its INT 21h's way out; both tasks count, P's values kept, the machine intact.
- **The checks can fail:** each of these, broken on purpose, fails a check: the save; the restore; FNINIT for a new task; the INT 11h gate; the CLD (9 checks fail); the drain moved to after the context is half saved (the IRQ 13 check). What pcemu can't show is the BUSY latch itself, so a drain left out altogether only fails the check for want of the IRQ; and the clearing of a delivered error.

## M4a: each task's own screen, and the screen writers frozen behind (2026-10-20)

**M4 is split in two,** as M2 was. M4a is the screen: INT 10h and the detector. M4b is the keys (an INT 16h hook: keys only for the front task, a program waiting in the BIOS switched from, CODE-Tab wherever the front task asks for a key) and each task's own mouse. (The mouse then moved to M4c.)

**What it does:** INT 10h goes through `mt_v10`, with interrupts off from its first instruction. INT itself clears them, but a hook installed after MT that chains with PUSHF / CALL FAR comes in with them on; the IRET gives the caller's back.
- **A background task's calls are done in its own screen:** its 2 EMS pages (M2b's, 32 KB), with its BIOS video data (40:49h-66h) in its TX. They are done the way the 1520's BIOS does them, read from GRiD's source (philip-searle/gridcase-bios, `int10.asm`, with the mode tables in `at_compat.asm`). So its output no longer lands on the screen in front, and when it comes to the front its screen is there, as it would have been.
- **Done there:** 00h for the text modes (the 1520's mapping: 0-3 text; 4-6, 40h, 48h, 74h graphics; anything else mode 2, cleared, bit 7 included), 01h-05h, 06h and 07h, 08h, 09h, 0Ah, 0Bh, 0Ch and 0Dh in a text mode (nothing, as on the 1520), 0Eh, 0Fh, 13h; 10h-12h and 14h up do nothing, as on the 1520. Their quirks are kept:
  - the teletype writes on the page shown, whatever BH says;
  - its scroll gives the new line the attribute of the cell under the cursor it had;
  - BS at the line's start stays there;
  - 13h writes through 09h, so with the attribute in BL even for its kinds 0 and 1;
  - a mode set clears 16 KB;
  - a scroll's counts are bytes, unchecked, as VidWinScroll and VidScrollImpl have them (`mt_vscr` follows them register for register). So a window the wrong way round after the clamps runs on as on the 1520: "clear below the cursor" with the cursor on the last line blanks 256 rows from the line below the page. That is 40 KB on the 1520, past B800h's 32 KB; MT and pcemu stop at the 32 KB (about 28 KB), 12 KB of it inside the 16 KB the detector compares;
  - pages are whole bytes, unchecked: page 8's cursor is 40:60h (the cursor's shape), and its screen past the 32 KB in 80 columns;
  - 09h and 0Ah run on past the 32 KB round 16 bits to page 0, as the BIOS's DI does; 03h gives the shape in CX whatever the page; 08h past the 32 KB gives FFFFh;
  - AX comes back as the BIOS leaves it: 00h with Mode Control in AL, 05h 0, 0Bh the new colour select in AL, 0Ch and 0Dh the mode in AH.

  Neither the CRTC nor the hardware is touched: that is the front task's. MT keeps the cursors of pages 0-10 (up to 40:65h); a call on a page past that does nothing. Nothing is written past the task's 32 KB, where on the 1520 the segment runs on past video memory.
- **A graphics mode or a pixel asked for in the background:** the task waits to be in front (`TS_WAITF`, 3 in MT_LIST), if the caller is at a safe point (`mt_safe`, as at the tick, against the INT 10h caller). The call is done for real once it is (`mt_scrld` makes it ready again). Not at a safe point (interrupts off, the Executive's own code, a TSR's), the call is dropped, and since the program may then go on to write the screen itself, it is marked as one that does (`VF_DIRECT`): frozen from its next safe point.
- **To the real screen:**
  - calls from the BIOS itself, inside a call MT passed on to it (the 1520's teletype calls INT 10h again for each step: 03h, 0Ah, 08h, 06h, 02h), as they are. MT marks its own calls to the BIOS (`mt_inb`, around each one: VCALL), since a driver's INT 10h hook loaded after MT (below A000h) hides the BIOS's CS;
  - calls from code at A000h or above otherwise (a ROM's; the EMS frame's: Resident Claude's console), as they are, not shadowed;
  - calls made inside an INT 13h call (MT counts them: `mt_i13`), taken as an interrupt's: a floppy's DMA may be going into the EMS frame then (KDISK and KEMS's cache fills read straight into it), so MT maps no window for them: as they are, not shadowed. No switch is made inside one (an INT 15h or INT 40h hook the BIOS calls out to meanwhile);
  - a background task's own calls with `SPF_BG` (below), shadowed;
  - calls made with a hardware interrupt in service, or while an INT 33h event handler runs, shadowed. A TSR's clock is the common case, and it lands on the real screen, as in DOS: GRiD's INT 08h (`rtc.asm`) calls INT 1Ch before its EOI;
  - calls made while the kernel's INT 24h runs (a critical error's "Abort, Retry, Fail", which everything waits for; MT counts it, `mt_c24`), whether the handler prints through the BIOS or through DOS, shadowed. Everything else inside INT 21h is the task's own, whatever hook it comes through: the kernel's console output goes in its screen.

  The shadowed ones count as the front task's own calls (below), so they don't count against it.
- **A stack in the EMS frame's windows 0 and 1,** where MT maps a task's pages, can't be used while they are mapped: such a caller's calls go to the BIOS as they are, not shadowed. A 13h string there isn't done in the background, nor shadowed in front. Either loses the shadow (below).

**The detector:** a task that writes B800h itself can't run behind another, since what it writes would land on the front screen.
- **Shadowed:** while another task exists, every call that writes the real screen in a text mode (00h, 06h, 07h, 09h, 0Ah, 0Eh, 13h) is also done in the front task's own pages (`mt_shd`), before the BIOS does it. The pages then hold what the screen would hold if only INT 10h wrote it.
  - The shadow starts in step with the screen: in `mt_scrld` (its pages were just copied to the screen), at a text mode set, or when the first other task is spawned (`mt_sync` copies B800h's first 16 KB into the front task's pages, with the INT 33h pointer hidden).
  - It stops with a graphics mode, and when the last other task ends.
  - **It is lost** (`mt_vlose`) when a call writes the real screen without being shadowed. It stops, and the next compare is skipped: not known, so the task runs. That happens:
    - for a stack or 13h string in windows 0 and 1;
    - for a call from code at A000h or above that isn't inside a call MT passed on to the BIOS (a ROM's, Resident Claude's console);
    - for a call inside an INT 13h call;
    - for an interrupt's call while MT has pages mapped itself (`mt_vbusy`), or inside a call MT passed on to the BIOS. MT notes the interrupts in service when it passes a call on (`mt_vcall`), so an interrupt-time call it shadowed doesn't lose the shadow through the BIOS's own nested calls.

    It starts again when the task next comes to the front, at a text mode set in front, at the next spawn, and at MT_SCREEN.
  - **MT_SCREEN** (F0h AL=1Ch) lets a program say that the screen it wrote itself is as it should be (put back after a screen saver): the front task's pages are given the screen again. LCMD calls it after its saver has put its text back.
- **Compared** when the front task is switched from (`mt_scrsv`, after the INT 33h pointer is hidden), B800h's first 16 KB against its pages:
  - a difference, or a graphics mode, sets `VF_DIRECT`;
  - no difference clears it;
  - not shadowed (no other task when it last came to the front, the shadow lost, or its pages gone) clears it: not known, so it runs.
- **Frozen:** `mt_pick` passes over a background task with `VF_DIRECT`. A running task found frozen with nothing else ready gives way to the front one (`mt_preempt`). It is compared again each time it is switched from in front, so a task that stops writing the screen itself is let run again. MT_LIST shows a frozen task as `TS_FROZEN` (4).
- **Overrides (MT_SPAWN's flags):**
  - `SPF_BG` (2): it runs behind whatever it does, its output on the front screen (as before M4a);
  - `SPF_FREEZE` (4): it never runs behind.

  MTLAUNCH /B and /Z set them; LODE.INI's `BG=` and `FREEZE=` lists come with START in M7.
- **The Executive** is in a graphics mode, so it is frozen while another task is in front. Its clock no longer lands on the front screen (an M3 limit), and its polls stop meanwhile.
- **Shadowing always, not until a task is classified:** a departure from the plan, which shadowed a task until its first switch away and then trusted that. That would have needed a per-program classification, reset when a task's program changes. It would also have let a program that writes the screen itself only now and then run behind and scribble. Comparing at every switch away costs output speed instead, but only while another task exists (see the cost).
- **Short ways:** a printable character inside a line, and CR, LF (not on the last line), BS and BEL, which change only the cursor, skip the general emulator (`mt_vfast`). A whole-width scroll the right way up (every teletype scroll) moves the rows at once.

**Also:**
- **MT_LIST** (F0h AL=12h) returns the caller's task in AH, with the front task in AL.
- **LCMD's screen saver** starts only when LCMD is in front (AL = AH). In the background the screen isn't its own: its saver's direct drawing would have landed on the front screen, and the screen it saved and put back would have been the front task's.
- **`mt_vbusy`:** while MT has a task's pages mapped itself with interrupts on (switching screens, `mt_sync`, a spawn's clear screen), an interrupt's INT 10h call goes straight to the BIOS, so that it can't map pages over MT's. The shadow is lost for it.
- **Two new hooks:** INT 13h goes through `mt_i13`, which counts the calls running and passes CF back as the BIOS gives it. The kernel's one INT 24h call (`crit_disk.c24`, 5 bytes) becomes a far call to `mt_c24`, which counts it. M5's per-task vector tables must keep `mt_i13` at the base of every task's INT 13h.
- **Left over:** `mt_inb`, `mt_crit` and `mt_in13` are cleared when a task ends or is spawned, and at every switch, where none can be under way, in case a program was ended inside one. A `mt_crit` left by an INT 24h handler that never came back counts only inside INT 21h.
- **The mapping** reads KEMS's tables directly (`mt_smap`), as INT 67h AH=44h would: no INT 67h call on the way.
- **A new task's screen** is set up at spawn: mode 3 (its BIOS video data from the 1520's tables), clear. Before M4a it was cleared when first shown; now a task can print before it is ever in front.

**pcemu's INT 10h now follows the 1520's BIOS:**
- per-page cursors, pages as whole bytes;
- the teletype on the page shown, its scroll's attribute;
- the scroll register for register;
- 13h, which pcemu used to ignore;
- 09h and 0Ah running on past a line;
- 03h's shape from 40:60h;
- 0Ch and 0Dh in a text mode;
- the AX it gives back;
- a mode set's clear (16 KB; 32 KB in 40h, 48h, 74h), its BIOS data (40:4Ch, 60h, 65h) and its mapping of other modes;
- 04h (no light pen: AH 0), 08h, 09h and 0Ah past the 32 KB, and 0Fh's AH from 40:4Ah;
- its INT 10h stub returns with IRET, so the caller gets its own flags back, as from the 1520's. Its other services keep RETF 2.

pcemu's BIOS does each INT 10h and INT 13h call at once, interrupts off: no tick lands inside one, so the checks set `mt_in13` themselves, and an interrupt landing inside a call MT passed on to the BIOS isn't tried.

Every other suite passes unchanged with it. MT's emulation and pcemu's were written from the same reading of the source, so `test_mt`'s byte-for-byte checks show they agree with each other, not that they agree with the 1520.

**The limits, plainly:**
- **Not tried on the 1520,** a departure from the plan, which asked for a hardware check of the frozen direct programs at M4. The emulation is read from GRiD's source. If that reading is wrong in any detail the shadow uses, every program printing in front through INT 10h with a task behind it will fail the comparison at its switch away, and so be frozen behind. M9 checks it first.
- **A program that starts writing the screen itself only once it is behind** isn't caught until it has been in front and is switched from again. The same goes for one started behind and never brought to the front. Until then it scribbles over the front screen; memory is never damaged, and a repaint puts it right. This is the plan's stated failure mode.
- **A dropped graphics call** freezes its task only from its next safe point. Until then (within its turn) it may write the screen itself. The Executive is the likely one: if a DOS program it ran ends while task 0 is behind, the UI's mode set is dropped (its code is never at a safe point but its idle HLTs), and it may draw over the front screen until its next tick.
- **A false "writes the screen itself"** freezes a front task behind until its next time in front:
  - a DOS INT 33h driver's text pointer over a cell the program writes (Lodestone's restores the cell it saved);
  - a TSR's call made after its EOI (no interrupt in service) inside a front task's call that MT passed on to the BIOS. It goes to the BIOS unshadowed;
  - a graphics mode set reaching the real screen from someone else's call (an `SPF_BG` task's, an INT 24h handler's, a TSR's): the front task is found in a graphics mode at its switch away;
  - a program that puts its own screen back without saying so (MT_SCREEN).
- **Only B800h's first 16 KB are compared:** text pages 0-3 in 80 columns, 0-7 in 40. Writes to the pages past them aren't seen.
- **The BIOS data area:** a background program that reads 40:50h (the cursor) or 40:4Ah itself sees the front task's.
- **The CRTC:** a background program that programs 3D4h/3D5h itself (its cursor, say) but prints through INT 10h isn't caught, and its port writes reach the screen. The BIOS's own CRTC writes are now only ever the front task's.
- **On the real screen:** an INT 10h call made with an interrupt in service, or by an INT 33h event handler, goes there, whichever task it lands in. That is right for a TSR's clock, and wrong for a background task's own INT 1Ch or mouse handler that draws (M4c gives each task its own mouse). A background task's INT 24h prompt goes there on purpose, over the front screen.
- **In a background task's screen:** a TSR's call made after its EOI (a clock hooked on INT 08h that chains first), landing while a background task runs, goes in that task's screen, not on the real one: MT can't tell that code from the task's own, since a driver's INT 10h hook loaded after MT hides every caller's CS. So does a TSR's INT 28h popup, which then shows when that task comes to the front.
- **Inside an INT 13h call** every INT 10h call is taken as an interrupt's, unshadowed: an interrupt's that lands during a transfer, or an INT 15h (AH=90h) or INT 40h hook the BIOS calls out to, loses the front task's shadow, or from a background task goes on the real screen. (A driver's INT 13h hook loaded after MT runs outside the count: its drawing is its task's own.)
- **An interrupt handler's data in windows 0 and 1** (a terminal program's receive buffer in its own page there, say) is under MT's pages for the 10-30 ms a switch takes to copy screens, as it is during KEMS's cache fills. Bytes it writes meanwhile land in a screen page.
- **A handler that never sends its EOI and then reads a key through DOS** lets another task run with its IRQ in service (`mt_can` doesn't read the PIC). That task's INT 10h calls then go to the real screen. M5 looks at it.
- **A graphics call's wait trusts its caller,** as M3's INT 21h way out does: a task's own interrupt handler that sends its EOI, turns interrupts on and then asks for graphics is switched from inside that handler.
- **Resident Claude,** popped up from a background task's own INT 16h call, shows and types into the front screen while it names that task's program. M4b's INT 16h hook can't change that, Resident Claude's hook being loaded after it: M7 does (M4b's limits).
- **No beep** for a background task's BEL.
- **Interrupts stay off** for the whole of an emulated call. A long 13h string that scrolls many times delays the tick.
- **LCMD behind never starts its screen saver.**
- **Keys are still shared** until M4b: background tasks can read the front task's keys (AH=0Bh, INT 16h directly), CODE-Tab needs a DOS key wait, and a program waiting in the BIOS can't be switched from on the 1520.

**Cost:**
- **Switch off:** nothing. `test_mt` pins the map and MEMSZ. LODE.SYS grows 64 bytes, in `mt_boot` (INT 10h's and INT 13h's hooks, the INT 24h patch); KDISK's new label costs nothing. LCMD.COM grows 25 bytes (the saver's check and MT_SCREEN).
- **Switch on:** MT's block is 416 paragraphs plus its MCB (6.5 KB; it was 250), so a DOS program gets 572.0 KB instead of 578.5.
- **Output speed in front, while another task exists:** 120 lines of 54 characters through DOS take 934 ms alone and 1,648 ms shadowed, in pcemu's time. pcemu counts its blocks at 4 µs, calibrated to the 1520's 10 MHz; its polling makes these good to about ±10%. That is about 110 µs more a character. Against it, DOS's own path costs about 145 µs a character in pcemu, where the BIOS costs nothing (that figure also includes loading the program). On the 1520 the BIOS's own teletype comes on top of both, so the slowdown there should be smaller than pcemu's 1.8 times; M9 measures it.
- **With no other task,** nothing is shadowed: each INT 10h call only passes `mt_v10`'s few checks on its way to the BIOS.
- **Files:** LODEMT.SYS is 5,842 bytes; ROM 1 has 17,408 bytes left.

**Tests:** `test_mt.py`, 165 checks (was 128). The new group is `t_screens`, with five new test programs:
- `MTSCR MODE [FILE]`:
  - P prints a script that uses every call MT does itself and the 1520's odd cases (windows the wrong way round, page 8, 09h past the 32 KB, 03h for page 11, 0Ch and 0Dh in a text mode), and what 03h, 08h, 0Fh and the AX of 00h, 05h, 0Bh, 0Dh answer, then waits for a key. A page of its own in window 2, signed, shows nothing was written past the 32 KB. C does the same in mode 1 (40 columns), M after a mode set of 83h;
  - L prints 120 lines through DOS;
  - D writes B800h itself;
  - G asks for mode 6;
  - Q does the same with interrupts off;
  - I hooks INT 1Ch with a handler that draws through INT 10h;
  - W waits for a key, then writes B800h itself, with no mode set;
  - K calls MT_SCREEN;
  - R calls INT 10h from code at D800h, which the test puts there (a ROM's).
- `VNEST.BIN`: a teletype as the 1520's, calling INT 10h again for each step. The test puts it at D000h, behind MT, as the BIOS would be.
- `MTCRIT`: its own INT 24h handler prompting through DOS (from the panel's review); with B, through the BIOS's teletype.
- `MTNEST`: INT 10h called with interrupts on (PUSHF / CALL FAR), an INT 1Ch handler calling INT 10h meanwhile, its own EMS page in window 0 checked after every call (from the panel's review). With S its stack is in that page; with E it prints a 13h string from there; N and I run as they are (the test sets `mt_in13` under I).
- `VHOOK`: stays resident, hooking INT 10h as a driver loaded after MT does; with T, INT 08h too, drawing a new digit each tick through INT 10h after chaining (a TSR's clock).

The checks:
- **MT off:** INT 10h untouched. **On:** INT 10h through `mt_v10`, on to the BIOS's.
- **In the background:** P, C and M behind MTLAUNCH: none of their output on the front screen; their own screens byte for byte what the BIOS drew for them alone in front (16 KB), and their BIOS video data the same. Brought to the front, that is what shows.
- **The shadow:** on from the moment a task is behind MTLAUNCH; on for a task brought to the front by CODE-Tab or MT_FRONT, with no mode set (`mt_scrld`); MTLAUNCH found clean at the switch away; off again when the last task ends, whichever ends last.
- **In front, with another task there:**
  - P is found not to write the screen itself (all its output in front, shadowed), and so is a task whose prompt was printed behind and its line typed in front (`t_front`);
  - D is found to write it, and so is G (graphics), and W, brought to the front with no mode set;
  - MT_SCREEN from a task behind doesn't hide D;
  - P again with VNEST as the BIOS (thousands of nested calls) is still clean, also with VHOOK's hook in the way.
- **To the real screen, shadowed:**
  - P with SPF_BG puts its output on the front screen, and MTLAUNCH is still clean at its switch away;
  - I's handler, behind, draws on the real screen, not in I's own, and MTLAUNCH is still clean;
  - VHOOK T's clock, inside an INT 13h call, draws on the real screen, never in the background task's own;
  - the INT 24h prompts below are shadowed in the front task's pages.
- **Frozen:**
  - a task marked `VF_DIRECT` doesn't run behind;
  - one marked while it runs, with every other task waiting for a key, gives way to the front one at once;
  - with `SPF_BG` too it runs;
  - with `SPF_FREEZE` it runs only in front, and MT_LIST lists it as `TS_FROZEN`.
- **Graphics behind:**
  - G waits as `TS_WAITF`, switched from at a safe point (the audit's third way in, `mt_wfront`, checked against every rule). Its line is in its own screen, and the front screen is untouched. Brought to the front, it gets mode 6.
  - Q's mode set, with interrupts off, is dropped, and Q is frozen; brought to the front, it carries on in mode 3.
- **A critical error behind:**
  - MTLAUNCH's task aborted while its stub EXECs (`t_ends`): the prompt, printed through the BIOS, is on the front screen, and Abort works;
  - MTCRIT's prompt, printed through DOS or (B) through the BIOS, is on the front screen, not in its own, and the key typed answers it.
- **Interrupts on at the way in:** MTNEST's EMS page stays where it was through 3000 calls with ticks landing (at least 3).
- **The shadow lost:** I behind inside an INT 13h call; R behind (its 'R' on the real screen); MTNEST S, E and I (inside an INT 13h call) brought to the front by MTLAUNCH /F. Each loses the shadow, and its front task isn't frozen; MTNEST N, the same way, keeps it.
- **A task's pages gone** (`t_front`): its VF_DIRECT is cleared at its switch away.
- **LCMD's saver:** behind MTLAUNCH, past its saver's time, it doesn't start, and the front screen is untouched. In front, with a task behind, the saver runs and ends, and LCMD is still clean at its switch away (MT_SCREEN).
- **The cost:** measured as above.
- **The checks can fail:** each of these, broken on purpose, fails a check:
  - **Which calls are shadowed:** the BIOS's own nested calls shadowed again (no A000h test), or through a hook (MT's own calls not marked, or not passed on as MT's); a call from an interrupt handler, or a critical error's prompt (the INT 24h count not tested, or its patch not made), taken as the task's; the real-screen calls not shadowed for the front task; interrupts left on at the way in; the INT 13h test left out (in front or behind), INT 13h not hooked, or its count never brought down; the stack test, the 13h string test or a ROM's call's loss left out; the BIOS's own calls, inside one MT passed on, taken as a ROM's, or as an interrupt's (the interrupts in service then not noted).
  - **The detector:** no compare at the switch away; graphics not taken as writing the screen; the shadow not started when a second task appears or a task comes to the front, or not stopped when the last one ends; VF_DIRECT cleared only once the pages are mapped; MT_SCREEN taken from a task behind; LCMD's saver not checking it is in front, or not reporting its restore (MT_SCREEN).
  - **Freezing:** `VF_DIRECT` or `SPF_FREEZE` ignored; a task frozen while it runs not giving way; MT_LIST not showing `TS_FROZEN`; graphics behind not waiting, or the wait never ended; a dropped mode set not freezing its task.
  - **The emulation:** the teletype's cursor not stored, its character not written, the attribute not taken from the screen, BS not moving back; 13h's attribute bytes not skipped; 09h writing like 0Ah, or stopping at the 32 KB; the page always 0, masked to 0-7, or pages 8-10 doing nothing; the BIOS's literal scroll skipped; blanks written past the 32 KB; 0Ch in a text mode waiting to be in front; 0Bh's AL, 0Dh's AH, 00h's AX or 05h's AX not set as the BIOS leaves them; 03h's CX not set past page 10; 00h's AX not given back to the BIOS; 80 columns for the 40-column modes.

  With the teletype's and the scroll's short paths turned off, so the long paths do everything, every check still passes.

  **Not tested here:** a TSR's clock that chains INT 08h first, landing in a background task's screen (the limit above); a switch refused inside an INT 13h call; an INT 33h event handler's call; an interrupt's call during MT's own screen copies (`mt_vbusy`, through `.busy` or, from code at A000h up, `.rom`; and `mt_vlost`'s tests in `mt_scrsv`, `mt_scrld` and `mt_sync`, reachable only from one); an interrupt landing inside a call MT passed on to the BIOS (pcemu's BIOS never turns interrupts on); a switch refused inside a hook's code nested in MT's call to the BIOS (`mt_inb` in `mt_safe` and `mt_can`), and its clearing at a switch; `mt_sync` hiding the pointer; a task waiting for the front (`mt_wfront`) that its own handler brought there meanwhile; pcemu's 04h, and its 0Fh's AH from 40:4Ah (equal to the columns in every mode tried).

## M4b: keys for the front task only, and CODE-Tab wherever it is typed (2026-10-21)

**The mouse moves to M4c.** M4b was to be the keys and each task's own mouse. The mouse is a change of its own, in the INT 33h driver (in the Executive's segment), so it gets its own PR, as M2 and M4 were split.

**What it does:** INT 16h goes through `mt_i16`.
- **CODE-Tab is caught at every INT 16h call** made with no hardware interrupt in service, before the call goes on (`mt_hot`, M2b's), so a peek (AH=01h) no longer drops it first. The tick looks for it too, at the end of a turn, where it may switch (`mt_safe`), so it is found while the front program computes and asks for no keys.
- **The task asked for comes to the front at the next safe point:** on the way out of the INT 21h call that found it, at the tick, at a peek or a read (below), or at a key wait. Before, only a key wait in DOS did it. So CODE-Tab now works with the Executive in front, at LCMD's prompt, in a program that reads keys through the BIOS, and in one that reads none. MT_FRONT is carried out the same way.
- **Keys go to the front task only.** For the reads and peeks (AH = 00h, 01h, 10h, 11h):
  - **DOS's own calls** (key status AH=0Bh, AH=06h with DL=FFh, AH=0Ch's flush, IOCTL 4406h on CON) from a background task find no key. They are known by the stack: the kernel's, even through a TSR's INT 16h hook that calls on with its caller's stack (one that moves to a stack of its own first hides them). DOS's key reads already waited (M2a).
  - **A program's own calls** (its code in its task's own memory, `mt_mine`): in the background, a peek finds no key. A read made where the task may be switched from (`mt_safe`, as at the tick) waits in MT as `TS_WAITK`: in the background until it is in front and a key comes, in front while nothing is typed, the other tasks running meanwhile (`mt_wkey`). The key brings it back as soon as it is typed, as for a DOS key wait (`mt_kwant`). The look for the key is a peek of the reader's own kind (AH=01h for 00h, 11h for 10h), so the BIOS drops what that read would skip.
  - **A peek whose task's turn is over** (or with a task asked for in front) switches there, at a safe point, as INT 21h's way out does. A program that only polls INT 16h is otherwise seldom found at a safe point by the tick: the tick lands in MT or the BIOS.
  - **As they are:** a call made with an interrupt in service (a TSR's pop-up or clock: the machine's, as its screen output is in M4a); any call while a critical error's prompt is up (everything waits for its answer, and the prompt is on the real screen); any call inside a call MT passed on to the BIOS, an INT 13h call, or a change of the front (`mt_inb`, `mt_in13`, `mt_swing`: an interrupt's, as M4a takes INT 10h's there); a call through a TSR's INT 16h hook loaded after MT, or from the ROM or the EMS frame; a TSR's call from the kernel's idle at a key wait (popping up from its INT 28h on the kernel's stack: `mt_idle`); a read made where the task can't be switched from (interrupts off, say).
  - **Other functions** go to the BIOS as they are.
- **A program waiting in the BIOS is now switched from on the 1520 too:** its read with nothing typed waits in MT, not in the ROM, where the tick couldn't switch (M3's limit).
- **A background task that must have a key but can't be switched from** (a nested INT 21h's key wait, say, or with too much kernel stack in use) comes to the front for it, since only the front task gets keys. Before, it read the front task's keys there. Inside a critical error's prompt, an INT 13h call, MT's call to the BIOS or a change of the front it reads them as before: no screen is changed there.
- **A task switched from in the middle of its run** (at the tick or INT 21h's way out, not at a key wait), whose shadow was lost (M4a: not known whether it writes the screen itself), is now frozen behind, to be safe. Before M4b the front changed only at key waits, where a program isn't half-way through drawing.

**Departures from the plan:**
- **No poll counting.** The plan had a background poller yield after 50 empty peeks a tick (`MTPOLL`). A background task's turn is 1 tick anyway, and a peek with its turn over gives way at once.
- **No per-task type-ahead.** Keys stay in the BIOS's buffer. CODE-Tab still counts only once the keys typed before it are read (M2b), so those reach the task they were typed for.
- **INT 16h isn't per task:** one hook in front of the BIOS's, as INT 10h is. Per-task vectors are M5's.

**The limits, plainly:**
- **INT 16h hooks loaded after MT,** Resident Claude's included, hide whose call it is (the hook's code, not the program's). What a program asks through one is as before M4b: a background peek sees the front task's keys. A read that waits in the hook's own loop (Resident Claude's does) holds the processor there until a key is typed, since the tick can't switch from the hook's code (M3's rule); then its read, passed on with the program's own frame, waits in MT for the front, and the key goes to the front task. In front the same loop keeps the other tasks waiting. With Resident Claude loaded, its console can also pop up from a background task's call. DOS's own calls through such a hook are still known (by the stack). M7 makes Resident Claude ask MT whose call it is (the M4a section said M4b would; it can't from MT's side alone).
- **CODE-Tab waits behind keys typed before it** that the front task never reads, as in M2b.
- **The M2b race is narrower, not gone:** a CODE-Tab arriving in the moment between `mt_hot`'s look and the BIOS's own AH=01h (once MT has passed the call on) is still dropped there.
- **Key latency in front:** a front read waiting in MT gets its key when the tick finds the running background task at a safe point (or on its INT 21h's way out). A background task in a long INT 13h call, in ROM or TSR code, or with interrupts off delays it until then; before, the front task's BIOS wait kept the processor. A key typed just after the BIOS's look, before MT halts, waits for the next interrupt: up to a tick.
- **The tick's look rewrites the buffer** (CODE-Tab taken out, the words after it moved back) inside the task's own code, at a safe point. A program that writes 40:1Ch itself at that moment (its own INT 09h hook after its EOI, a key stuffer) could lose a key or see stale ones. It needs CODE-Tab in the buffer at that same tick.
- **A program that ends inside a change of the front** (its own mouse event handler, run on MT's stack while the screens are copied, exiting to DOS) leaves that change half done until the next CODE-Tab, and a DOS program's mouse pointer, hidden for it, can stay hidden until a program resets the mouse (INT 33h AX=0; M4c puts the front task's INT 33h state back there). MT's own state (`mt_swing`, `mt_vbusy`) is cleared at the task's end, so nothing else stays held.
- **A forced front** (a background task at a key wait it can't be switched from) replaces a CODE-Tab or MT_FRONT request still pending: it has to be asked again.
- **A front program that only polls,** switched from at a peek with its shadow lost, is taken as in the middle of its run and frozen behind, to be safe, though it is in effect at a key wait.
- **The BIOS isn't called while a front task waits:** MT HLTs instead, so anything the BIOS does in its own wait (INT 15h AH=90h, "device busy", which some idle detectors and power managers watch) doesn't happen.
- **Whose code:** task 0's own memory is the running program's blocks (`cur_psp`'s), so a child's call through its parent's INT 16h hook counts as not task 0's own there, as it is (in tasks 1-7 the whole region is the task's). Code running in the EMS frame is never a task's own (`mt_safe` refuses A000h up): its reads go to the BIOS.
- **The front changes mid-run now:** the index and data port pairs (M3's limit: 3D4h/3D5h, the PIT) can be split by the new front's mode set too.
- **Programs that read the keyboard themselves** (port 60h, 40:1Ah-1Ch, their own INT 09h or INT 1Bh hooks) see the front task's keys, as before; INT 09h/1Bh are global until M5. A background task's AH=05h (a key put in the buffer) goes to the front task.
- **Not tried on the 1520 yet** (M9). The 1520's INT 16h is taken to turn interrupts on, as the AT's does; pcemu's now does too.

**How:**
- **`mt_i16`** sorts the call:
  1. an interrupt in service; inside MT's call to the BIOS, an INT 13h call or a change of the front; a critical error's prompt up (`mt_crit`, inside INT 21h): on to the BIOS;
  2. `mt_hot`, then a task asked for makes a switch due (`mt_pend`);
  3. not a read or a peek: on to the BIOS;
  4. on the kernel's stack (DOS's calls, MT's key wait): in the background, a peek finds no key (ZF and IF set in the caller's flags; AX as it was);
  5. not the program's own code (`mt_mine` on the caller's CS): on to the BIOS;
  6. a peek: with a switch due, `mt_safe` and `mt_preempt` (the audit's fifth way in, path "peek"); then as in 4;
  7. a read: `mt_safe`, or on to the BIOS. A task asked for comes to the front (`mt_swkw`). In front with a key there, on to the BIOS, which has it at once. Else `mt_wkey`: the task waits as `TS_WAITK` while the next ready one runs (in the background, the front one if none is), and then back to step 2. In front with no other task ready, it HLTs until the next interrupt.
- **`mt_wkey`** is the audit's fourth way in, after the tick, INT 21h's way out and M4a's graphics wait: each switch it makes is checked against every safe-point rule.
- **`mt_swnow`** (the task asked for to the front, if still there; from `mt_preempt`, `mt_i16`, `mt_kwait`) now runs outside INT 21h too, at the tick, on the interrupted task's own stack. So, once it has drained the coprocessor on the caller's stack (an error pending is taken there), it moves to a stack of MT's own: 1 KB in its BSS, for the screens' copies, the BIOS's mode set, the INT 33h driver, a program's mouse event handler and any interrupt meanwhile. Interrupts are on (the serial mouse isn't held up) and `mt_swing` is set: no switch meanwhile (`mt_safe` and `mt_can` test the flag; `mt_safe` also refuses MT's stack), and an interrupt handler's request meanwhile waits. `mt_preempt` drains again after it, for what a handler did meanwhile. `mt_mid`, set only once a change is under way, tells `mt_scrsv` whether the one in front may be in the middle of its run.
- **`mt_idle`** marks the kernel's own idle at a key wait (`mt_kwait`'s jump to `kbd_get`'s INT 28h and HLT). A TSR popping up from that INT 28h runs on the kernel's stack, so without it its peeks would be taken as DOS's and, in the background, never find the key it waits for.
- **`mt_tick`**, at the end of a turn (`mt_pend`), where it may switch: `mt_hot`, then `mt_preempt`.
- **`mt_hot`** keeps the caller's interrupt flag (it turned interrupts on before), so a tick isn't taken inside MT, where it is lost.
- **pcemu:** its INT 16h stub returned with RETF 2 and interrupts off (the INT's), so every call MT passed on came back to the program with interrupts off, which the BIOS doesn't do. It turns them on now, as the BIOS's STI does. The other suites pass unchanged.

**Cost:**
- **Switch off:** nothing. LODE.SYS grows 32 bytes, in `mt_boot` (INT 16h's hook).
- **Switch on:** MT's block is 508 paragraphs plus its MCB (8.0 KB; it was 416), 64 of them `mt_swnow`'s stack, so a DOS program gets 571.8 KB instead of 579.7 (main's UI batch, PR #51).
- **Speed:** each INT 16h call passes `mt_i16`'s checks and `mt_hot`'s look at the buffer; console output is untouched.
- **Files:** LODEMT.SYS is 6,289 bytes (5,842 after M4a); ROM 1 has 17,920 bytes left.

**Tests:** `test_mt.py`, 191 checks (was 165). The new group is `t_keys`, with a new test program:
- `MTKEY MODE FILE`:
  - R reads a key with INT 16h AH=00h, E with AH=10h, C with AH=00h and interrupts off; each writes the key it got;
  - P peeks with AH=01h and 11h for 18 ticks, Q the same with interrupts off, T from an INT 1Ch handler of its own, Y as P with its own INT 08h hook ahead of MT's; each writes how many peeks it made and how many found a key;
  - D asks DOS (AH=0Bh, AH=06h with DL=FFh) for 18 ticks, then flushes (AH=0Ch); X the same with its own INT 08h hook;
  - H stays resident, hooking INT 16h: its reads wait in its own loop, as Resident Claude's do, and it calls on with PUSHF / CALL FAR.

The checks:
- **MT off:** INT 16h untouched. **On:** INT 16h through `mt_i16`, on to the BIOS's.
- **The references:** P, Q, T and D in front, alone, find the keys typed.
- **Behind a task that reads no keys** (MTSPIN in front), keys typed: P and Q find none (each of Q's peeks back with interrupts on, as the BIOS's are), nor does D (DOS's status, AH=06h, the flush), and the keys are still there for the front task. T, from its INT 1Ch handler, finds them in every peek, some of them in its own task behind.
- **Polling:** Y in front, the tick unable to switch: MTSPIN behind still runs, switched to from Y's peeks, at a safe point. (Once there, it keeps the processor until it ends: Y's timer hook keeps the tick from switching back, and MTSPIN makes no calls.)
- **Inside an INT 13h call, or a call MT passed on to the BIOS** (the test sets the count as P starts peeking behind): P's peeks go on as they are and find the keys.
- **A read behind:** R waits as `TS_WAITK` while MTLAUNCH in front gets its line; brought to the front at the command prompt, it gets the next key.
- **A read in front:** R waits as `TS_WAITK` while MTSPIN runs; then the key reaches it. E's wait keeps CODE-? (a key AH=01h drops), and gets it.
- **CODE-Tab:**
  - while R waits in its read in front: the next task comes to the front, and back again;
  - while MTSPIN computes in front: the tick finds it, and a request with no key is carried out too;
  - while X asks DOS for keys in front, its own timer hook ahead of MT's: on the way out of the very INT 21h call that found it, no tick between;
  - at LCMD's prompt (`t_front`, which until now checked it did nothing there), and in the Executive itself.
- **Frozen when not known:** MTSPIN, computing in front, its shadow lost (set by the test), switched from by CODE-Tab: `VF_DIRECT`. MTLINE the same way at its key wait: not; nor MTLINE in front at its key wait, switched from at the tick while MTSPIN runs behind.
- **Can't be switched from:** MTLINE behind at a nested DOS key wait (InDOS 2, set by the test for that wait) comes to the front and gets its line; inside an INT 13h call, or while the front is being changed (`mt_swing`, set by the test), it reads its keys from behind, as before. C's read with interrupts off waits in the BIOS, isn't switched from, and gets its key.
- **A TSR's hook** (H): DOS's key status behind, through it, still finds none; a program's peek through it finds the keys (the hook's code); a background read through its wait loop waits in MT for the front, the key going to the front task; brought to the front, it gets the next.
- **A change of the front under way** (`mt_swing`, set by the test): CODE-Tab's change waits until it is done.
- **The audit:** every switch from INT 16h, and every other, at a safe point. MT uses under 64 bytes of the caller's stack at the tick, at INT 16h and at a peek (42-44). At the tick the front changes on MT's own stack (72-74 without it).
- **The checks can fail:** each of these, broken on purpose, fails a check:
  - **The hook:** INT 16h not hooked (the group hangs); `mt_hot` not called there, or turning interrupts on; no switch made due there; the tests for an interrupt in service, a critical error's prompt, MT's call to the BIOS, an INT 13h call or a change of the front left out; the kernel's stack not told apart; a background peek's ZF or IF not set; `mt_mine` not asked.
  - **Reads and peeks:** a read not checked with `mt_safe`; `mt_wkey` not called, or not marking `TS_WAITK`; the front read's look made with AH=01h for AH=10h; the task asked for not brought to the front at a read, or brought there as from mid-run (`mt_swnow` for `mt_swkw`); no `mt_preempt` at a peek.
  - **The tick:** `mt_hot` not called at the end of a turn.
  - **Changing the front:** `mt_swnow` not called from `mt_preempt` or `mt_kwait`; not on its own stack; a second change not refused meanwhile (in `mt_swnow`, or `mt_can` testing `mt_in13` alone); `mt_mid` not tested, or not set, the detector freezing nothing, or a task at its key wait taken as mid-run.
  - **A background task that can't be switched from:** not brought to the front; brought there inside a critical error's prompt, an INT 13h call or MT's call to the BIOS; `mt_can` not testing the INT 13h count.

  **Not tested here:** the M2b race and the key latency (both timing); a real interrupt landing in `mt_swnow`'s window (the tests set `mt_swing` themselves), so neither `mt_safe`'s test of `mt_swing` (a handler on its own stack there), `mt_swnow`'s first drain (an error pending as it starts), nor a task ending there (`mt_end` clearing `mt_swing`); a TSR popping up from the kernel's INT 28h in a background task's idle (`mt_idle`: reached only when nothing can run and the front task waits for something other than a key); the 1520's INT 16h turning interrupts on (M9); AH=05h from a background task.

## M4c: each task's own mouse (2026-10-21)

**What it does:** each task has its own INT 33h state. The UI's driver (MOUSE33.INC) is unchanged. It keeps one state, `m33_st` (138 bytes: where the pointer is, its ranges and speeds, the counts of presses and releases, the show count, the pointer's shape, the event handler), which its own functions 15h-17h already save and restore. MT keeps one copy of it per task, in the task's TX (`TX_M33`).
- **The driver's state is the front task's.** The mouse moves it, its pointer is the one drawn, and its event handler is the one called.
- **A change of the front swaps it** (`mt_scrto`). The task leaving the front keeps its state, its pointer is taken away (AX=2) before its screen is saved, and the task coming to the front gets its own back through the driver's own function 17h. 17h draws the pointer as that state says, so its show count comes back exactly as the program left it. The same happens when the front task ends and the Executive's task comes back. `m33_busy` is set for the whole change, so no event handler runs while the state is being swapped (and the tick doesn't switch).
- **A background task's own INT 33h call is done on its own state** (`mt_i33`, an INT 33h hook in front of the UI's driver). Its state is swapped in for the call and the front task's goes back afterwards. Meanwhile the pointer on the real screen is left as it is, and no event handler runs:
  - **The mode the driver draws in:** for most functions, none (40:49h is 0FFh for the call, made with interrupts off). For a reset (AX=00h or 21h), the task's own mode, so its ranges are right; its show count is set to -1 (hidden) first, so a mouse packet while the reset turns the mouse on draws nothing. For 0Ch and 14h, which turn interrupts on in the driver (its INT 21h AH=62h), 40:49h is left as it is and the mouse's IRQ is masked at the PIC for the call; a packet that comes meanwhile is the front task's, after it.
  - The pointer drawn on the screen is taken as none (`m33_dn`, `m33_dmode` kept aside).
  - `m33_busy` is set, which also keeps the tick from switching, and the front task's pending events are kept aside.
- **As they are** (on the driver's state, as before M4c): the front task's calls; MT's own (`mt_in33`); a call made with an interrupt in service (a TSR's, or a background task's own INT 1Ch handler: the machine's, as for INT 10h and 16h) or by an event handler (`m33_busy`); a call inside MT's call to the BIOS, an INT 13h call, a change of the front or a critical error's prompt; and a call that isn't from the running task's own code (a TSR's: `mt_mine`).
- **A new task's state** is the driver's when it starts, with the pointer off, no event handler, and its counts (motion, presses, releases) zero, until its program resets the mouse. (Not all zeros: a mouse packet divides by the speed.)
- **A background program's end** (`ui_progend`, which tells the driver, now a far jump to `mt_pgend` first): if its event handler is in its task's own state, it is forgotten there, as the driver's `m33_gone` forgets the front task's. A program the Executive ran (the root's child), ending in task 0 while task 0 is behind, has its pointer taken as off in task 0's own state, as the UI's `m33_end` would do; `m33_end` itself then acts on the front task's (see the limits).
- **The hook is put in place** at a task's spawn and at each change of the front, when INT 33h is the UI's driver: the UI sets it at its start, after `mt_boot`, and again when the root restarts or its block moves. A program's own hook put there since is left alone. Each time the hook is put in place, the front task's state is saved to its TX; the first time, that is task 0's, which no change of the front has saved yet. The hook takes the driver's segment from `ui_seg` at each call, as the UI's block can move.
- **Another INT 33h driver** (a program's own, installed from the Executive and not chaining): MT's hook stays off it. At a change of the front its pointer is taken away (AX=2) and put back (AX=1) through INT 33h, so its show count comes back as it was; its state is one for all tasks. MT tells it from a program's hook in front of the UI's driver by whether the UI's driver answered that AX=1 (its show count moved). If it didn't, the UI's 17h for the new front task draws in no mode, so the UI's pointer isn't drawn over the other driver's; if it did (a hook), 17h draws as usual.
- **M4b's limit for a task ending inside a change of the front** is smaller. With `m33_busy` held for the change, the UI's driver runs no event handler inside it, so that way in is gone; another driver's handler, or any other handler that ends its program there, remains. Then `mt_end` puts the front task's own INT 33h state back (and another driver's pointer), so no pointer stays hidden, and clears `m33_busy`, so the tick switches again and event handlers run. The screen can still be half done until the next CODE-Tab. If the task ended before the change's AX=2, or after its AX=1, another driver gets one AX=1 too many, and its show count ends one high (drivers that stop it at 0, as most do, are unaffected); and with a program's hook in front of the UI's driver, MT can then take the hook for another driver, so the new front's pointer is drawn in no mode, an old pointer's image can stay on the screen, and the pointer comes back at the next mouse packet.

**Departures from the plan:**
- **The event handler isn't held back** until its task is running. The plan had `mouse_isr` call a task's handler only while that task is current. A handler runs at the mouse's interrupt, the way DOS mouse drivers call it, so it is written for that; holding it back would drop or delay the front task's clicks during another task's turn. So the front task's handler runs whichever task the interrupt lands in, as before M4c.
- **No change to the driver.** The plan called for swapping inside the INT 33h driver; MT does it from outside instead, with the driver's own 17h, and the UI block's size with MT off is unchanged.

**The limits, plainly:**
- **The front task's event handler runs in whichever task the interrupt lands in** (above). Its EMS windows may then be another task's, so a handler that reads its own EMS pages reads that task's. Its INT 10h calls go on the real screen (M4a), its INT 16h calls pass as an interrupt's. Its INT 21h calls are made as that task's (its PSP, its files, its directory): a handler that ends its program (4Ch) ends that task's. Its own 0Ch or 14h (setting a new handler from inside one) records that task's PSP as the handler's owner, since the driver asks DOS (AH=62h); the handler is then not forgotten when its own program ends, only when that task's does.
- **While a background task's reset is in the driver with interrupts on** (it turns the mouse on): a mouse packet then moves that task's state, not the front task's, and draws nothing (its show count -1), and its events are dropped. An interrupt handler that reads the video mode then (40:49h) reads the task's own. (For 0Ch and 14h, whose INT 21h AH=62h runs with interrupts on, the mouse's IRQ is masked instead; so a packet is held off, not dropped, unless the call takes long enough for the serial port to overrun, about 7 ms, as a Shift-PrtSc capture taken inside it would. With no mouse found nothing is masked, and 40:49h is left as it is.) In either window, an INT 33h call from another interrupt's handler (a TSR's, or a task's INT 1Ch handler) passes as it is, so it acts on the background task's state, not the front task's; in 0Ch's and 14h's window 40:49h is the real mode, so a pointer it shows is drawn on the real screen.
- **The mouse itself is one for all tasks:** a background task's reset turns the serial port on, as a front one's does, and the Executive's `ui_run` turns it off before it runs a program, in task 0 whichever task is in front.
- **Only the UI's driver.** A program that installs a mouse driver of its own replaces this one for every task, as before; MT's hook goes only over the UI's driver. Its pointer is taken away and put back at a change of the front (above), but its state is one for all tasks, and it isn't told of the mode a change of the front sets (MT sets it through the BIOS, past any INT 10h hook): between tasks in different modes, a driver that keeps the mode from INT 10h AH=00h draws its pointer for the wrong one. The UI's driver's own state for each task is still swapped, and a change of the front draws none of it. A driver that takes the mouse's interrupt, as real ones do, keeps the UI's from drawing afterwards too; one that doesn't leaves the UI's interrupt handler drawing the front task's UI pointer at the next mouse packet, as without MT. A driver that answers AX=1 itself and also passes it on to the UI's is taken for a hook, so both pointers are drawn.
- **A program's INT 33h hook that calls on** (PUSHF / CALL FAR, put in place after MT's) sits in front of MT's for every task. Other tasks' calls through it reach MT's hook with its code's CS, not theirs, so a background task's calls are done on the front task's state (`mt_mine`) until it takes its hook away (a TSR never does). A hook that jumps on (JMP FAR) leaves the caller's CS on the stack and changes nothing.
- **The Executive's own tidying after a program it ran ends behind** (`m33_end`, called in the UI, not through INT 33h) acts on the front task's state: its pointer is taken away (show count -1) and its event handler forgotten, whoever's it is. The front program keeps that loss, even across changes of the front, until it shows its pointer and sets its handler again (or resets the mouse). Task 0's programs seldom end behind.
- **A TSR's call from a background task's time** (not the task's own code) is done on the front task's state, as before.
- **After the UI sets INT 33h again** (the root's restart, or the UI's block moving), background calls are done on the front task's state until the next spawn or change of the front puts MT's hook back.
- **The test for an interrupt in service** (a background task's INT 1Ch handler) assumes the BIOS's INT 08h calls INT 1Ch before its EOI, as GRiD's does (M4a) and pcemu's.
- **Not tried on the 1520 yet** (M9).

**How:** `mt_i33` sorts the call as `mt_i16` does. A background task's own call goes through `mt_33in`, which saves the front task's state to its TX, keeps the drawn pointer, the pending events and `m33_busy` aside, copies the task's own state in and sets the mode the driver draws in (or, for 0Ch and 14h, masks the mouse's IRQ). The call is then made with the caller's registers. `mt_33out` unmasks the IRQ if it was unmasked before, copies the task's state back to its TX, the front task's back in, and the rest as it was. `mt_m33to` and `mt_m33ld` save and restore at a change of the front, `mt_m33bz` and `mt_m33nb` hold `m33_busy` across it, and `mt_m33on` puts another driver's pointer back; `mt_m33new` makes a new task's state; `mt_33hk` puts the hook in place; `mt_pgend` is the program end's patch.

**Cost:**
- **Switch off:** nothing. `test_mt` pins the map and MEMSZ. LODE.SYS grows 16 bytes, in `mt_boot` (the `ui_progend` patch). MOUSE33.INC is unchanged.
- **Switch on:** each TX grows by 9 paragraphs (`TX_M33`), so each task's region does too. MT's block is 579 paragraphs plus its MCB (9.1 KB; it was 508): task 0's TX and the new code. A DOS program gets 570.7 KB instead of 579.7.
- **Files:** LODEMT.SYS is 7,287 bytes (6,289 after M4b); ROM 1 has 17,920 bytes left (after PR #53).

**Tests:** `test_mt.py`, 209 checks (was 191). The new group is `t_mouse`, with a serial mouse on COM1 (pcemu's, `mouse=True`) and a new test program:
- `MTM33 MODE FILE`:
  - F resets the mouse, sets an event handler that counts its calls, shows the pointer and reads keys through DOS until "q", then writes its handler's calls and its position (03h);
  - B is F with its position set to (200, 96) first, writing at once too;
  - H sets a handler, swaps it for itself (14h), writes, and ends without taking it away; X runs H as a child, then waits as F;
  - T sets its position, then for 18 ticks its INT 1Ch handler asks for the position, counting the answers that are its own;
  - G sets mode 40h, waits 18 ticks (to be sent behind meanwhile), resets the mouse and writes as F, then waits for "q";
  - D stays resident as another INT 33h driver (not chaining), counting AX=1 up and AX=2 down, and its AX=2 calls;
  - J stays resident as a hook on INT 33h that jumps on to the one before.

The checks:
- **The hook:** INT 33h is the UI's driver until a task is spawned, then MT's, on to the UI's.
- **B behind, F in front:** B's reset, position, pointer and handler are its own (its 03h gives (200, 96)); F's pointer stays on the real screen, nothing of B's is drawn there, the mode is as it was, and the driver's state is F's.
- **The mouse moved:** F's pointer follows. CODE-Tab: B in front, its pointer where it put it, F's gone with F's screen; moved, B's follows and B's handler is called.
- **B ends in front:** the Executive's task comes back with its own state (the pointer off, not B's position); none drawn.
- **F in front again:** its pointer where it was, its handler called only while it was in front (twice), its position moved only then.
- **H, a child of X behind:** its handler, set on X's own state, is forgotten when it ends, and X's position is its own. A mouse packet while H's 14h call is in the driver with interrupts on is held off, then goes to the front task: H's handler isn't called, H's position isn't moved, the front task's moves.
- **A new task that never asks for the mouse:** its state the driver's, the pointer off, no handler (on memory the test zeroed first); the mouse moving while it is in front draws and calls nothing.
- **T's INT 1Ch handler, behind** (the timer's interrupt in service): its calls get F's position, never its own; its own code gets its own.
- **Inside MT's call to the BIOS or an INT 13h call** (set by the test as B's first call comes): B's calls go to the driver's state as they are.
- **G, sent behind in mode 40h before its reset:** its ranges are its own mode's (y in the middle of 400 rows), and the screen in front stays text.
- **A hook that jumps on (J), in front of MT's:** B behind still gets its own state; CODE-Tab to B draws B's pointer and leaves none of F's on B's screen.
- **Another driver (D), put in place while F (its pointer shown by the UI's driver) is behind:** F comes back to the front with the UI's pointer not drawn by the change. (D doesn't take the mouse's interrupt, so the mouse isn't moved here.)
- **D with a task in front:** MT's hook isn't put over D. Through the task's spawn, three changes of the front and its end, D's pointer is taken away (AX=2, counted after each) and put back, and its show count ends as it was.
- **No mouse found** (a second machine, with no serial mouse): H behind; for its 0Ch and 14h nothing is masked and the mode byte is left as it is (the test makes MT's saved copy of it stale as the call comes).
- **The checks can fail:** each of these, broken on purpose, fails a check (three of them by hanging the group: a new task's state not made, the program end's patch not made, the IRQ not masked for 0Ch and 14h):
  - the hook not put in place;
  - a background call not swapped, or a front task's call swapped;
  - the tests for an interrupt in service, MT's call to the BIOS or an INT 13h call left out;
  - the drawn pointer not kept aside, or the driver left a mode to draw in;
  - a reset given 0FFh, not the task's own mode;
  - the front task's state not saved, or not put back after the call;
  - 17h replaced by AX=1 at a change of the front, or when the front task ends (or the Executive's state not loaded there);
  - another driver's pointer not put back (AX=1), or the UI's drawn in its place, or a hook in front of the UI's driver taken for another driver;
  - with no mouse, MT's saved mode byte written back for 0Ch or 14h.

  **Not tested here:**
  - **Calls let through twice over,** so leaving out one test alone fails nothing: MT's own calls (`mt_in33`, and their code is no task's own); an event handler's calls (`m33_busy`, and the handler is the front task's code).
  - **Fixes no check reaches:**
    - `m33_busy` set for a background call. With interrupts off, or the IRQ masked, no packet comes; only a packet in a reset's window would show it.
    - The show count -1 for a reset, which matters only for a packet in that window.
    - `m33_busy` held across a change of the front.
    - The front task's events kept aside (`mt_33eb`).
    - The first save in `mt_33hk`.
    - The driver's segment refreshed from `ui_seg` (the UI's block moving).
    - Task 0's pointer taken as off at its program's end behind (`mt_pgend`).
    - A new task's counts zeroed.
  - **Situations not set up:** a TSR's call from a background task's time (`mt_mine`); a task ending inside a change of the front (`mt_end`'s 17h, its AX=1 to another driver and its clearing of `m33_busy`); a background task's 16h and 17h; a critical error's prompt; the UI setting INT 33h again; the 1520's own mouse (M9).
