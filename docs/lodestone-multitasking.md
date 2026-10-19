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
| M2a | Spawning, task regions, switching when one waits for a key | This PR. |
| M2b | The front: the CODE-] hot key, each task's screen saved and restored | |
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

M2 was split in two: **M2a**, tasks and switching (this part), and **M2b**, the front: the CODE-] hot key and each task's screen, saved and restored in EMS. All of M2a is in LODEMT.SYS; the kernel gains one label (`k_retf`, on `run_ui`'s RETF) and no bytes.

**What it does:** a program can start another as a task, INT 21h F0h AL=10h (`MT_SPAWN`, MTAPI.INC). The task runs when the running one waits for a key in DOS, and the tasks take turns that way. Only the front task reads keys. Another that waits for one waits without reading, until it is brought to the front (F0h AL=13h, `MT_FRONT`, at the next key wait). Each task has its own memory, current directories, DTA, console line and PSP. When its program ends, the task ends: its region is freed, and the handles its stub inherited are closed.

**The limit, plainly:** a task switches only when one waits for a key *inside DOS* (INT 21h AH=01h, 07h, 08h, 0Ah, or a read from CON).
- The Executive and LCMD's prompt don't: they ask whether a key is there (INT 16h AH=11h, INT 21h AH=0Bh) and halt in their own loops. So with either in front, nothing switches.
- A task that computes without waiting keeps the machine until it waits or ends.
- M3's preemption (INT 08h at safe points) removes both limits.
- Until M4 the tasks also share one screen: what a background task prints lands on the front one's.

**How:**
- **The key wait:** `kbd_get.k` (`MOV AH,1` / `INT 16h` / `JNZ .have`, 6 bytes at 06BCh, checked in the listing and by `test_mt`) becomes a far jump to `mt_kwait`.
  - There, the front task looks for a key. If none is there, it lets a task that is ready run, and if there is none, it goes on to the kernel's own wait (PrtSc, INT 28h, HLT).
  - A background task waits without looking. Its state becomes "waiting for a key" (`TS_WAITK`), and a ready task, or the front one, runs.
  - So a background task can never take a keystroke meant for the front task.
- **Switching** (`mt_switch`, `mt_load`) is done only inside INT 21h (`indos` 1, never in a nested call such as an INT 24h answer), and only at `mt_kwait` or when a task ends. A task's context, its TX, holds:
  - its SS:SP;
  - the kernel's per-task variables (`mt_ranges`): `indos`, the break and console state (`brkflag`..`onebyte`), `first_mcb`, the drives' current-directory clusters and strings, `cur_drv`, the DTA and the file and console-line state (`dta`..`rw_t0`), `cur_psp`, `last_exit`, `term_keep`;
  - the kernel stack's slice from SP up, because a task waits inside INT 21h.

  The slice measured 32–42 bytes for every console read; a TX has room for 256, and `mt_kwait` doesn't switch if it would need more.
- **A task's region** is carved from the top of the highest free block that has room (the arena walked from its first MCB, free neighbours merged), downward from MT's block. It is a block of its own, owner 8, "T1".."T7", holding:
  - its TX (42 paragraphs);
  - its stub, a PSP and a few instructions at 100h: EXEC the program, then F0h AL=11h (`MT_END`). `make_psp` (called through `KCALL`) gives it the spawner's handles;
  - a copy of the spawner's environment (up to 1 KB), because the spawner may end first;
  - the task's own MCB chain, its `first_mcb`, ended by a 'Z' in the region.

  The task's program gets its memory from that chain (a .COM takes all of it, as it would take all memory). Task 0's TX is in MT's block (`mttbss`), so MT's block is 148 paragraphs now.
- **Ending** (`MT_END`, from the stub only): `close_all` on the stub's PSP (`KCALL`), the exit code kept, the region freed, and the next task runs without its context being saved.
- **Calling the kernel:** `KCALL r` pushes MT's far return, then the offset of `k_retf`, and jumps to KSEG:r. The routine's near RET goes to the RETF, which comes back to MT.
- **The API** (MTAPI.INC):
  - `MT_SPAWN`: DS:DX = the program (with its extension), ES:BX = EXEC's block plus a word of paragraphs (0: 64 KB) and a flags byte (`SPF_FRONT`). → AL = the task, or CF with AX = 4 (8 tasks already) or 8 (no room).
  - `MT_FRONT`: BL = a task.
  - `MT_LIST` records now carry each task's state (1 running or ready, 2 waiting for a key).

**Cost:**
- **Switch off:** nothing. `test_mt` pins the map and MEMSZ; LODE.SYS grows 48 bytes, all in `mt_boot`.
- **Switch on:** MT's block is 148 paragraphs plus its MCB, 2.3 KB; a DOS program gets 575.3 KB instead of 577.6. Each task takes its region: about 1.6 KB plus its environment, plus its memory (64 KB unless asked).
- **Files:** LODEMT.SYS is 1,682 bytes; ROM 1 has 20,992 bytes left.

**Tests:** `test_mt.py`, 68 checks. The new group is `t_tasks`, with three test programs:
- `MTLAUNCH` starts the tasks it is given (`/F`, `/M:n`, `/R:n`), lists them, then waits for a line itself;
- `MTLINE FILE` writes a line to FILE;
- `MTCWD DIR FILE` changes directory, waits for a key, then writes its current directory.

What the group checks:
- **Two MTLINE tasks:**
  - they run to their key waits and wait there in the background;
  - their regions are T1 and T2, under MT's block;
  - task 1 is brought to the front, "hel" typed, then task 2 gets "world" and ends;
  - task 1, at the front again, gets "lo": its half-typed line survived ("hello");
  - afterwards memory (free neighbours merged) and the SFT are exactly as before, and the prompt answers.
- **`/F`:** the second task gets the first line.
- **MTCWD:** each task keeps its own directory and writes its file there; the prompt's stays A:\.
- **Errors:** no room gives error 8; with 8 at once, tasks 1–7 start and the eighth gives error 4. Each of the 7 then gets its own line in turn.
- **Switch off:** MTLAUNCH reports error 1.
- **The patches:**
  - the 6 bytes at `kbd_get.k` are as expected in LODE.SYS, patched with the switch on and untouched with it off;
  - task 0's TX sits on the paragraph after the image.
