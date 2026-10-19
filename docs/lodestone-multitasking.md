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

**What it does:** with `MULTITASK=1` (or `Yes`, or `On`, in any case, with nothing after it on the line) in LODE.INI, the kernel installs multitasking's resident part at start-up. Any other value leaves it off. It needs EMS, and enough of it (3 pages or more) for the disk cache to be there. With less, or with no EMS, it stays off without a word: System will say so in M7. A `-dNOTC` build (no disk cache) has none of it. There is one task, the Executive, and nothing switches yet. LCMD's new `TASKS` lists the tasks:

```
A:\>tasks
  0  Executive (in front)
```

With the switch off, `TASKS` says `Multitasking is off (MULTITASK=1 in LODE.INI)` and sets ERRORLEVEL 1. `TASKS` sets CF before the call, so under another DOS, which leaves the flags alone for a call it doesn't have, it reports the same.

**How:** `KMT.INC`, with the calls and the task record in `MTAPI.INC` (shared with LCMD).
- **Reading the switch:** `md_boot`'s search for `MDISK=` became `ini_key`, which `md_boot` now uses for both settings. Both are read from the one LODE.INI read (KROM's `ini_read`, into `INI_BUF` at 1000:F000), before M: is made. `md_boot` only runs when the disk cache is in EMS, which is where the "needs EMS" comes from.
- **`mt_boot`** (section `boot`: in the load image only) runs after M:. It:
  - puts the resident part (section `mtt`, assembled from 0) in a block of its own, owner 8, called "MT", at the very top of memory. A filler block takes everything but MT's paragraphs first, then goes. `mem_alloc` is first-fit, so MT only lands at the top if no free hole of its size sits lower down. That is always so at start-up, but `mt_boot` checks that MT's block is the last one, and frees it and stays off if not;
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
- **Switch off:** nothing resident. `image_end` (4450h), `bss_end` (7A90h), `ui_keep_end` (6CE4h) and MEMSZ from the Executive (561.7 / 577.8 KB) are unchanged, and `test_mt` pins all of them.
- **One exception: LCMD.** It is 173 bytes bigger (`TASKS`). It keeps 11 paragraphs (176 bytes) more while a program runs from its prompt, so such programs get that much less, switch on or off.
- **Switch on:** MT's block is 14 paragraphs plus its MCB, 240 bytes. A DOS program gets 577.5 KB instead of 577.8. `test_mt` checks the free paragraphs exactly.
- **Files:**
  - LODE.SYS is 48,828 bytes (+448, all in the load image);
  - LCMD.COM is 11,143 bytes;
  - ROM 1 has 24,064 bytes left (one sector less).

**Tests:** `tests/test_mt.py`, 43 checks, with `MTPROBE.COM`, which calls F0h AL=00h, 10h, 11h, 12h (with no room), 13h and FFh and prints CF, AX, BX and CX for each.
- **The map:** with the switch off, the three map values above are pinned. MT's image must end below 1000:F000, where LODE.INI is read.
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
- **DOS programs:** free memory is exactly 15 paragraphs less with the switch on. MEMSZ from the Executive is 577.8 KB with `MULTITASK=0`. TESTDOS, EMSTEST and CACHETST pass. Afterwards MT is still at the top, still ticking, and F0h still goes through it.
- **From the ROM** (the 1520's own start-up): `C:\LODE.INI` with `MULTITASK=1` turns it on, and `TASKS` lists the Executive. With the ROM's own settings, it is off.

**Risk for later milestones: the load image's ceiling.**
- LODE.SYS is loaded at 1000:0000, and LODE.INI is read into 1000:F000 (`INI_BUF`; KSPLASH's `SP_BUF` is there too). So everything `mt_boot` copies must lie below 61,440 bytes into the file, and the ROM loader refuses 64 KB in any case. LODE.SYS is 48,828 bytes now.
- The plan expects multitasking to add 8–12 KB. Its "slow paths in an EMS page" frees conventional memory, but that image still travels inside LODE.SYS, so it doesn't help here.
- **Two ways out:**
  - **a quick one:** move the 4 KB INI buffer out of segment 1000h, which gains 4 KB, up to the 64 KB limit;
  - **the real one:** load multitasking from a file of its own (`LODEMT.SYS`, the resident image and the EMS image) in `mt_boot`. That file would never be read with the switch off. It is to be decided before M2 adds the bulk.
