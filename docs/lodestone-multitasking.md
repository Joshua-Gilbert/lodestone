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
| M1 | The switch and the skeleton | This PR. |
| M2 | Spawning, task regions, cooperative switching at the kernel's key wait, the hot key | |
| M3 | Preemption from INT 08h at safe points | |
| M4 | Virtual screens (an INT 10h hook) and the direct-write detector | |
| M5 | Per-task vectors, ending and killing tasks | |
| M6 | Parking tasks in EMS and bringing them back | |
| M7 | The Executive's task list (TASKS.RUN, CODE-T), LCMD START/FG/KILL/PARK/WAIT, System's switch | |
| M8 | Several `.RUN` windows at once, as coroutines in the UI task | |
| M9 | On the 1520, and release 0.7 | |

Each milestone's PR adds its section below, describing what was built and any departure from the plan.

## M1: the switch and the skeleton (2026-10-19)

**What it does:** with `MULTITASK=1` (or `Yes`, or `On`, any case) in LODE.INI and EMS present, the kernel installs multitasking's resident part at start-up. There is one task, the Executive, and nothing switches yet. LCMD's new `TASKS` lists the tasks:

```
A:\>tasks
  0  Executive (in front)
```

With the switch off, `TASKS` says `Multitasking is off (MULTITASK=1 in LODE.INI)` and sets ERRORLEVEL 1.

**How:** `KMT.INC`, with the calls and the task record in `MTAPI.INC` (shared with LCMD).
- **Reading the switch:** `md_boot`'s search for `MDISK=` became `ini_key`, which `md_boot` now uses for both settings. Both are read from the one LODE.INI read, before M: is made. `md_boot` only runs with EMS, so without EMS multitasking stays off on its own.
- **`mt_boot`** (section `boot`: in the load image only) runs after M:. It:
  - puts the resident part (section `mtt`, assembled from 0) in a block of its own, owner 8, called "MT", at the very top of memory. A filler block takes everything but MT's paragraphs first, then goes;
  - points INT 08h at `mt_tick`, which runs the BIOS's handler first and then counts the tick (M3 will switch tasks there);
  - turns `f_F0`'s first 5 bytes (`MOV AL,[BP+F_AX]` and `OR AL,AL`, checked in the listing) into a far jump to `mt_f0`. That routine handles AL=12h and otherwise does those two instructions and jumps back past them. KEMS's patch at `f_F0.back` is further in, so the two don't clash.
- **The API:** INT 21h AH=F0h, AL=10h and up. With the switch off, every one of them fails with CF set and AX=1 (`f_F0` sends unknown functions to `f_bad`), so the off state needs no code at all.
  - AL=12h, list: ES:DI = room for CX records of 16 bytes → CX = the number of tasks, the records filled in, AL = the front task.
  - A record: number (byte), state (byte), PSP (word), name (12 bytes, ASCIIZ).

**A change from the approved plan: where the resident part goes.** The plan put the MT block between the root PSP and the UI block, inside KSEG's 64 KB, so that the kernel patches could be near jumps. M1 puts it at the top of memory and uses far jumps instead (5 bytes, the same size as the planned patch at `done`). Placing it low would mean moving the UI block after it is loaded. The UI block also needs 16 KB free right after it for a `.RUN` (`ui_room`), and a block there would make the UI move again on the first `.RUN`. At the top, DOS programs still get a single block below it. The UI keeps lending its directory buffer as before, so with the switch on DOS programs lose only MT's own block (240 bytes so far), not the planned 7.5 KB. Per-task regions (M2) will settle where that buffer stands.

**Cost:**
- **Switch off:** nothing. `image_end` (4450h), `bss_end` (7A90h), `ui_keep_end` (6CE4h) and MEMSZ (561.7 / 577.8 KB) are unchanged.
- **Switch on:** MT's block is 14 paragraphs plus its MCB, 240 bytes. A DOS program gets 577.5 KB instead of 577.8.
- **Files:**
  - LODE.SYS is 48,796 bytes (+416, all in the load image);
  - LCMD.COM is 11,128 (+158);
  - ROM 1 has 24,064 bytes left (one sector less).
- **LCMD's TASKS costs 158 bytes even with the switch off:** LCMD stays in memory while a program runs from the prompt, so such programs get that much less (the Executive's figures above are unchanged).

**Tests:** `tests/test_mt.py`, 27 checks.
- **Off:** with no line, `MULTITASK=0`, `MULTITASK=Off`, and `MULTITASK=1` without EMS:
  - there is no MT block;
  - INT 08h is still the BIOS's, and `f_F0` is as assembled;
  - `TASKS` reports that it's off and sets ERRORLEVEL 1.
- **On:**
  - The block: the last one, owner 8, at A000h's edge. The free space below it is one block.
  - The hooks: INT 08h goes through `mt_tick` and on to the BIOS's handler, and `f_F0` jumps to `mt_f0`. Task 0's PSP is the root process's.
  - Timing: `mt_tick` counts the same ticks as the BIOS over 2 simulated seconds.
  - Commands: `TASKS` lists the Executive, in front. The Executive's help window still borrows and returns the disk cache's memory through F0h AL=2/3.
  - The setting's spellings work: `Yes`, `on`, and a `MULTITASK=0` that is only part of another line's value.
  - `MDISK=` still counts beside it.
- **DOS programs:** with the switch on, MEMSZ shows 240 bytes less; TESTDOS, EMSTEST and CACHETST pass; the Executive is back afterwards with MT still in place.

**Risk for later milestones: the load image's ceiling.** LODE.SYS is loaded at 1000:0000, and `md_boot` reads LODE.INI into 1000:F000 (`MD_IBUF`). The file must therefore stay under 61,440 bytes; it is 48,796 now. The plan expects multitasking to add 8–12 KB to LODE.SYS, which is close to that limit. Before M4 or M5, move the slow paths into the EMS page the plan gives them, or move `MD_IBUF`.
