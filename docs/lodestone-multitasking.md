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
| M2b | The front: the CODE-] hot key, each task's screen saved and restored | This PR. |
| M3 | Preemption from INT 08h at safe points | |
| M4 | Virtual screens (an INT 10h hook) and the direct-write detector | |
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
- **Switch off:** nothing resident, and LODEMT.SYS isn't read. `image_end` (44F0h), `bss_end` (7B40h), `ui_keep_end` (6CE4h) and MEMSZ from the Executive (561.5 / 577.6 KB) are main's, with PrtSc's printing (PR #42), unchanged, and `test_mt` pins all of them.
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

M2 was split in two: **M2a**, tasks and switching (this part), and **M2b**, the front: the CODE-] hot key and each task's screen, saved and restored in EMS. The plan's hardware check for M2 moves to M2b, since there is no hot key to press yet. All of M2a is in LODEMT.SYS; the kernel gains one label (`k_retf`, on `run_ui`'s RETF) and no bytes.

**What it does:** a program can start another as a task, INT 21h F0h AL=10h (`MT_SPAWN`, MTAPI.INC). The task runs when the running one waits for a key in DOS, and the tasks take turns that way. Only the front task reads keys. Another that waits for one waits without reading, until it is brought to the front (F0h AL=13h, `MT_FRONT`, at the next key wait). Each task has its own memory, current directories on A: to D:, DTA, console line, PSP and EMS mapping. When its program ends, the task ends: its region is freed, and the handles its stub inherited are closed.

**The limit, plainly:** a task switches only when one waits for a key *inside DOS* (INT 21h AH=01h, 07h, 08h, 0Ah, or a read from CON).
- The Executive and LCMD's prompt don't: they ask whether a key is there (INT 16h AH=11h, INT 21h AH=0Bh) and halt in their own loops. So with either in front, nothing switches.
- A task that computes without waiting keeps the machine until it waits or ends.
- M3's preemption (INT 08h at safe points) removes both limits.
- Until M4 the tasks also share one screen: what a background task prints lands on the front one's.
- Only DOS's own key waits keep a background task off the keyboard. One that hasn't reached its wait yet can still see or take the front task's keys:
  - INT 21h AH=0Ch flushes the BIOS's key buffer;
  - AH=0Bh, and AH=06h with DL=FFh, see a key typed for the front task. AH=06h then waits in the background until it is brought to the front;
  - INT 16h, called directly, reads them.

  M4's INT 16h hook closes this.
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

## M2b: the front, CODE-], and each task's screen (2026-10-19)

**What it does:** CODE-] brings the next task to the front, in turn (0, 1, 2, ..., back to 0), and each task has a screen of its own. The front task's screen is the one shown. When another comes to the front, the screen is kept in the first task's own EMS pages, and the new front task's is put back.

**Departure from the plan:** the plan had CODE-] bring up the Executive's Tasks window, and CODE-] again go back. The Tasks window is M7's (TASKS.RUN). Until then CODE-] cycles through the tasks, and M7 decides what it does then.

**The limits, plainly:**
- **CODE-] works only while a task waits for a key in DOS**, where tasks switch (M2a). Anywhere that only asks whether a key is there, the BIOS drops CODE keys (INT 16h AH=01h; only AH=10h/11h give them), so the key is lost:
  - with the Executive or LCMD's prompt in front, it does nothing;
  - a program that asks before it reads loses it too: INT 21h AH=0Bh, AH=06h with DL=FFh, AH=0Ch's flush, and IOCTL 4406h on CON all ask;
  - a program that reads keys through INT 16h itself never gets to DOS's wait, so its tasks don't switch at all.

  M3 (switching anywhere) and M4's INT 16h hook (catching the key before anyone asks) lift this.
- **A small race:** a CODE-] typed in the instant between `mt_hot`'s look and the front task's own INT 16h AH=01h is dropped there; pressed again, it works. M4's hook closes this too.
- **A background task's output still lands on the front screen** until M4's hooks: it is kept with whichever task's screen is shown.
- **A task's screen, the first time it comes to the front, is mode 3 and clear.** What it wrote before then went to the front task's screen. A program that sets a graphics mode should come to the front first (`/F`).
- **The mouse:** a DOS program's INT 33h pointer is hidden while the screens change (AX=2, then AX=1, as Resident Claude does), but there is one mouse state for all tasks until M4. The Executive's pointer is drawn into its screen, which comes back byte for byte.
- **What isn't kept:** a palette written straight to port 3D9h without the BIOS's copy (40:66h), and port 3D8h's settings beyond the mode (say blink off).
- **A program that frees MT's pages:** EMS's AH=45h frees any handle, for anyone (CLAUDE /U frees its own that way, so KEMS can't refuse). If the pages can't be mapped when MT next needs them (AH=44h fails), that task keeps no screen from then on: nothing is copied, it comes to the front clear, and MT never frees that handle number, which may be someone else's by then. If the number has been handed out again before MT next maps it, MT can't tell.
- **The 1520 itself:** CODE-] hasn't been pressed on the 1520 yet. The BIOS should keep it as 1BF0h, which AH=10h gives as 1B00h, as it does CODE-\ (Resident Claude's key, which works there). `os/claude/KEYCODE.COM` shows it. If it doesn't come through, the fallback is CODE-Tab: the two words are in one place, `mt_hotk`.

**How:**
- **The key:** `mt_kwait`, on each pass (each key wait, and each tick while one waits), looks through the BIOS's key buffer for 1BF0h or 1B00h. It looks before its own INT 16h AH=01h, which would drop the key.
  - **Order:** the key counts only when nothing but other CODE keys (which AH=01h drops anyway) is ahead of it. Keys typed before it are the front task's, and it reads them first; CODE-] then counts at its next pass.
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
- **Switch on:** MT's block is 196 paragraphs plus its MCB, 3.1 KB, so a DOS program gets 574.5 KB instead of 577.6.
- **Each task's region** is 97 paragraphs (1.5 KB) plus its environment and memory.
- **EMS:** 32 KB per task, task 0 included.
- **Files:** LODEMT.SYS is 2,425 bytes; ROM 1 has 20,480 bytes left.

**Tests:** `test_mt.py`, 95 checks. The new group is `t_front`, with two new test programs:
- `MTMODE MM FILE` sets video mode MM, fills the 32 KB with a pattern, waits for a key, then writes "ok" to FILE if the pattern is all still there;
- `FREEH N` frees EMS handle N, as a program that frees a handle not its own might.

The checks:
- **The cycle:**
  - each task takes 2 EMS pages;
  - with two MTLINE tasks, CODE-] while MTLAUNCH waits brings up task 1: the key is gone from the buffer, and the screen is clear in mode 3;
  - "hel" typed shows there;
  - CODE-] gives task 2 (clear), then task 0 with MTLAUNCH's screen, cursor and BIOS video data exactly as they were, then task 1 with "hel".
- **Ending:** task 1 gets "lo" and ends, and task 0 is in front with its screen. When all have ended, memory, files and EMS pages are as before.
- **Graphics:**
  - MTMODE in mode 40h, in front: CODE-] to task 0 (mode 3, MTLAUNCH's screen), then CODE-] back gives mode 40h and all 32 KB as they were, and MTMODE finds its pattern intact.
  - In mode 4, with palette 25h, 3D9h gets 25h after the mode set and before the screen, and 40:66h is 25h.
- **Order:** "xy", CODE-], "z", Enter typed ahead: MTLAUNCH reads "xy", and task 1 gets "z".
- **Other cases:**
  - with one task besides task 0, CODE-] goes to it and back;
  - at LCMD's prompt, with a task waiting, CODE-] does nothing and is gone; with MTLAUNCH waiting, it brings the task up;
  - `/F` gives the task a screen of its own, and task 0's comes back when it ends.
- **EMS:**
  - FREEH frees task 0's handle: at the next CODE-] it keeps no screen, comes back clear, and nothing leaks;
  - with no EMS left for a task's screen, MTLAUNCH gets error 8, and memory, files and EMS are as before;
  - with `MDISK=` taking all of EMS, multitasking stays off;
  - the abort and TSR endings give their pages back.
- **The checks can fail:** each of these, broken on purpose, fails its check:
  - the screen copy in `mt_scrld`;
  - the key's order;
  - the failed-map test;
  - the 3D9h write;
  - `mt_boot`'s allocation;
  - the key taken out;
  - the AH=45h at a task's end.

**The review** (three reviewers, 2026-10-19) found no bug in the normal paths. Fixed from it:
- keys typed before CODE-] went to the new front task;
- a freed screen handle wasn't noticed (MT copied through whatever pages were mapped, then freed the number again);
- the buffer scan wasn't bounded;
- the DOS program's pointer wasn't hidden;
- the page shown wasn't set again;
- BX was trusted across the mode set.

It also added the checks for 3D9h, the cursor, EMS running out at a spawn, `/F`'s screen, and the prompt with a task waiting.
