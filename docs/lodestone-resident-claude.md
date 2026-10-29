# Resident Claude (0.5) — plan

Planned 2026-10-09. This builds on Term (0.4.0, `docs/term.md`, including its "Phase 2" sketch) and on Command (0.4.2).

## What it is for
Claude stays with Joshua while he works inside a DOS program such as TM5000G, at an instrument. It can see that program, type into it, read and write files, and query instruments, much as Claude Code works on his PC. It is the real `claude` on the Pi 5, on his plan, through Term. All the intelligence stays on the Pi; the GRiD provides a console, the program's screen and keys, and the tools.

## Decisions (Joshua, 2026-10-09)
- **Pop-up first, background next.**
  - 0.5a: a hot key brings Claude Code up over the paused program.
  - 0.5b: Claude also works between Joshua's keystrokes without touching the screen (files, instrument queries).
- **A TSR loaded when wanted:** `CLAUDE /R`. Nothing is resident when it isn't loaded. It may move into the kernel once it has settled.
- **Full screen.** The hot key flips between Claude Code's 80×24 screen and the program, whose screen is kept in EMS.
- **Hot key CODE-\\** (Alt-\\). The BIOS hands it only to programs that ask for extended keys (AH=10h/11h), so programs using AH=00h/01h never see it.

## How it fits together
```
program (TM5000G) ── INT 16h ──► CLAUDE /R stub (conventional, ~1.2 KB)
                                   │ CODE-\ or a Pi request at a key wait
                                   ▼
                        maps its EMS pages into the frame
                        (the program's own mapping saved and restored)
                                   │
           ┌───────────────────────┴───────────────────────┐
     Term console (EMS page 1)                    program's screen (EMS pages 2-3)
     TERMLINK + TERMCELL + TERMKEYS               32 KB video memory + BIOS video state
     glyphs, shadow, link buffers                 (saved at pop-up, put back at pop-down)
           │
     INT 60h (the kernel's GPIB driver) ── bridge ── Pi 5: gridlink ── claude (same session)
```

### On the GRiD
- **The stub** (conventional memory, the only part that costs DOS programs anything): an INT 16h hook, extended from RUN's 205-byte hook in CLAUDE.COM. It holds:
  - the key-script feeder;
  - hot-key detection for both AH=10h/11h and AH=00h/01h callers;
  - pop-up and pop-down;
  - saving and restoring the EMS page registers (4 IN + 4 OUT, written directly as M: does);
  - a switch to a stack of its own;
  - the `indos` check.
  - Target 1.2 KB, against Phase 2's 1.1 KB estimate.
- **EMS:** about 3 or 4 pages (48-64 KB), allocated once with INT 67h at load. Joshua's 1520 has 352 KB free next to M: at 1 MB.
  - Page 1 holds the console: CLAUDE.COM's `TERMLINK`, `TERMCELL` and `TERMKEYS` (written CS-relative, with no DOS calls), the glyphs and font, the 24×80 shadow, and the link buffers.
  - Pages 2 and 3 hold the program's screen.
  - Without EMS, `CLAUDE /R` says so and doesn't load.
- **Reused, not copied:**
  - the kernel's GPIB driver (INT 60h, with the block fast path);
  - the kernel's EMS manager (allocation) and M:'s direct page-register technique (speed);
  - CLAUDE.COM's console code and the key-script format, as they are;
  - the kernel's `indos` byte, through the address F0h already gives.
- **Pop-up:** only from inside the INT 16h hook, when the program is waiting for a key. The sequence is:
  1. save the video mode, video memory and BIOS video data (40:49-66h);
  2. switch to mode 40h and draw the console from its shadow;
  3. serve the link until CODE-\\ is pressed again (or the Pi says done);
  4. put the program's screen back exactly, byte for byte, then return to the program.
- **New REQUESTs:**
  - **12h TYPE:** a key script in RUN's format, fed to the program after pop-down. ~~A snapshot mark brings Claude back silently at the next key wait~~ When the keys are done the console comes back up (visibly: decided with Joshua for M3, so he sees the keys play and Claude Code's question before each TYPE) and Claude sees what they did.
  - **SCREEN of the paused program:** from the saved copy.
  - HELLO says `app=resident` and names the program (its PSP name).
- **What Claude may do while a program is paused:**
  - READ, DIR, STAT, FREE, WRITE, DELETE and RENAME, run on the kernel's own stack when `indos` is set.
  - GPIB queries, only while INT 60h isn't busy (AX=6 means try later).
  - **Never** RUN: the program holds the memory, and EXEC would reset `indos`.
  - Never INT 60h AH=0Bh (SRQ check), which would clear TM5000G's SRQ latch.
  - Never anything from INT 08h.

### On the Pi
- `gridlink` keeps the same `claude` session across pop-ups, so the conversation continues.
- New MCP tools:
  - `grid_program` (what is running, and its screen) — a look tool;
  - `grid_type` (keys into the program, then its screen afterwards) — a change tool, so Claude Code asks first.
  - Existing tools that can't run while a program is paused, such as `grid_command`, say why.

## 0.5b: background (after 0.5a)
- At the program's key waits, the stub serial-polls the bridge (at most every 200 ms; never AH=0Bh). If the Pi has work, it serves it without drawing anything, for at most about 50 ms at a time, then lets the program go on. (Done in M4, below, with changes: the console, called by the stub, does the polling, and a request runs whole in one pass.)
- Background requests are limited to the safe list above (files, GPIB queries). Anything that needs the screen waits for the next pop-up.
- A small indicator on the program's screen is optional; to be decided after 0.5a. (Decided in M4: none.)

## Spikes first (de-risk before writing it all)
1. **Code in the EMS frame under a program that uses EMS.** A 300-byte TSR that maps its page, runs, and restores the program's mapping. Test in pcemu, then on the 1520.
2. **Pop-up over TM5000G while it polls an instrument.** Uses the 7210 model in pcemu: TM5000G's GPIB state and SRQ latch must be untouched.
3. **Graphics state round trip.** Byte-compare video memory and 40:49-66h before and after a pop-up over a graphics program, then GRIDPROBE on the 1520 for the V6366's registers.

## Spike results (2026-10-09)
The spike programs are in `os/claude`:
- **RSPIKE.COM** — the TSR. It keeps 0.9 KB of conventional memory and uses 3 EMS pages: its code, plus the program's screen.
- **EMSUSE**, **GFXUSE** and **KEYCODE** — test programs.
- **SPIKES.BAT** — runs the steps on the 1520.

The emulator tests are in `os/tests/test_resident.py` (21 checks).

On the 1520 (SPIKES.TXT; run without a GPIB address):

| Step | Result |
|---|---|
| Hot key | CODE-\\ reads 2B00h with AH=10h, as expected |
| RSPIKE | loads |
| EMSUSE | the program's 4 EMS pages are untouched across the pop-up (0 bad) |
| Video, modes 4, 6 and 40h | video memory and 40:49–66h come back byte for byte (0 bad) |
| Flip speed | Joshua: "nothing went weird between switching screens and it was almost instantaneous" |

- **Mode 6:** one prompt was answered "looked DIFFERENT". It was answered so again in M1, and that time Joshua said what he saw: the screen was black, and then the pattern flashed briefly. Both were real, and neither was the video memory, which came back byte for byte; see "Mode 6 on the 1520" under M1.
- **Toward multitasking:** the flip is an EMS register swap plus a 32 KB copy. Joshua noted it is useful later for switching between programs. It is the same mechanism a program switcher would use.

### Bug found on the 1520: the hook's first instruction was missing
- **What Joshua saw:** with RSPIKE loaded, TM5000G's auto-detect got stuck during module detection, and mouse clicks did nothing. Without RSPIKE both worked.
- **Cause:** a comment edit swallowed the hook's first instruction, `cmp ah, 0`. So INT 16h branched on the caller's ZF. A key peek (AH=01h/11h) made with ZF set, as the kernel's `con_ready` always does, turned into a wait for a key.
- **Effect:**
  - TM5000G's `kbhit()` blocked until a key. It calls `kbhit()` between mouse reads and before each GPIB probe, which explains both symptoms.
  - The Executive's AH=11h key checks blocked the same way, and so would LCMD's prompt screen saver.
- **Fixed:** RSPIKE.COM is now 1,693 bytes and is on the floppy, verified.
- **Why the tests missed it:** they always pressed keys, and a key unblocks the wait.
- **New checks, with no key pressed:**
  - a TM5000G mouse click opens Configure Modules;
  - auto-detect goes through all 30 addresses on its own, before and after a pop-up;
  - a click in the Executive selects.

  These fail 6 ways on the old hook and pass on the fixed one, with both the repo's and the floppy's TM5000G builds.
- **Rule for M1 onward:** every program the hook sits under is also tested polling without keys (`kbhit`, the mouse, GPIB scans).

### Carried into M1
- **Hot-key check:** look at the BIOS keyboard buffer directly (40:1Ah/1Ch, the raw word 2BF0h) instead of an extra INT 16h AH=11h on every call.
  - It is cheaper on every key call a program makes.
  - It also catches CODE-\\ when it sits behind another CODE-key. AH=01h drops consecutive "enhanced-only" keys together, so the hot key could be lost there.
- **The `indos` check and `CLAUDE /U`:** neither is in the spike.
- **Writing the window registers directly is safe with Lodestone's EMM.** It keeps no copy of the mappings: 44h writes straight to the port, and 47h reads the registers back. A third-party EMM loaded instead would need `CLAUDE /R` to go through INT 67h 47h/48h; Lodestone has its own, so that is moot for now.

## Milestones
1. **M1:** `CLAUDE /R` loads (EMS pages, stub) and unloads (`CLAUDE /U`). CODE-\\ flips to an empty console and back over TM5000G and over the Executive, with no link yet. Memory is measured. Done in the emulator and on the 1520 (below).
2. **M2:** the Term session in the pop-up; the same `claude` session as `CLAUDE /T`. Done in the emulator (below).
3. **M3:** the paused program's SCREEN and TYPE, the console back with the screen after the keys. Claude can drive TM5000G. Done in the emulator (below).
4. **M4 (0.5b):** background requests at key waits. Done in the emulator (below).

Each milestone has emulator tests:
- pcemu with TM5000G and the 7210 model;
- gridlink's GridSim with fake `claude`;
- the real CLAUDE /R code.

Only the spikes and the final check need the 1520. Real use needs the Pi 5 and the bridge, which aren't set up yet.

## Open points (to settle as we go)
- **Loading from LCMD.** The stub lands after LCMD, so when LCMD exits the Executive's block moves past it (`ui_room`, as for any TSR). A `RESIDENT=` line in LODE.INI could load it at start-up instead, right after the UI block.
- **Programs that hook INT 16h themselves**, and programs that read the keyboard through INT 09h only (not covered: Phase 2 left INT 09h hooks out).
- **The mouse during a pop-up.** It is probably ignored.

## M1: `CLAUDE /R` and `CLAUDE /U` (2026-10-13)
`CLAUDE /R` makes Claude resident. CODE-\ over a program waiting for a key brings up its console, and CODE-\ again goes back to the program as it was. `CLAUDE /U` takes it out again. M1's console is empty: Term's 24 rows blank and its status band. The link comes in M2.

- **Exit codes:**
  - `/R`: 0 resident, 1 no EMS (or not enough), 2 resident already.
  - `/U`: 0 taken out, 1 not resident, 2 a program loaded after it has INT 16h (take that out first).
- **Where it lives:** in CLAUDE.COM.
  - `/R` and `/U` are handled before the GPIB driver is looked for, so they work without the bridge.
  - The console is its own assembly, `RCON.ASM` (org 0, 2,946 bytes). `/R` copies it into the first of three EMS pages.
  - Everything only `/R` and `/U` use (their code and messages, the stub as it will run, assembled for offset 100h with `vstart`, and the console) is where CLAUDE.COM's BSS goes, so chat and Term runs don't carry it in memory; only `res_args` (32 bytes), which looks for `/R` and `/U`, stays. (PR #27's review: before, a chat or Term run carried 1,248 bytes of it.)
  - It draws with `cell` from `CELL.INC`, split out of `TERMCELL.INC` (CLAUDE.COM is byte for byte the same after the split), and the Terminus font. This is the shape M2 needs: the console code CS-relative in EMS.
- **The stub: in a block of its own at the top of memory, with no PSP.** This changed from the plan (and from RSPIKE, which keeps its PSP with INT 21h AH=31h).
  - **Why:** measured with the stub kept that way and loaded at the prompt, a program the Executive started afterwards got 534.8 KB instead of 578.4: 43.6 KB less. When LCMD ended, the Executive's block couldn't grow back past the stub (`ui_room`), so it moved above it, leaving everything below unused. Any TSR loaded at the prompt does this today.
  - **How:**
    1. `/R` takes the largest free block and cuts it to its size less the stub's paragraphs (`R_PARAS`: 47 then, 57 since M7c) and an MCB. The kernel leaves the rest, at that block's top, as a free block of exactly the stub's size.
    2. It claims that block for the stub, as the system's block (owner 8), called CLAUDE, and gives the rest of the largest block back. (A second INT 21h AH=48h would take the first hole that fits, possibly one lower down, which would bring the 43.6 KB loss back; HOLE.COM makes such a hole in the tests.)
    3. It copies the stub in at the same offsets: the stub's CS is 10h paragraphs below its block.
    4. CLAUDE.COM then ends like any program.
  - The Executive's block never has anything in its way, wherever `/R` ran. It also saves the 256-byte PSP. This settles the open point "Loading from LCMD" below, with no `RESIDENT=` needed.
  - **The EMS pages** are asked for through a 3-byte thunk in the stub (`int 67h`, `retf`). Lodestone's EMS manager gives pages asked for from outside a program's memory to no program, so they aren't taken back when CLAUDE.COM ends. The first try asked from CLAUDE.COM: its pages went back at its end, the next program got the same ones, and the console's code was overwritten (EMSUSE caught it).
- **The hot key, from the BIOS's buffer:** every INT 16h call first scans the keyboard buffer for CODE-\, and takes that word out.
  - The buffer runs from 40:1Ah to 40:1Ch and wraps at 40:80h/82h, as the 1520's BIOS does (`KbBufStart`/`KbBufEnd`).
  - The raw word is 2BF0h (2B00h is taken too), and it is found anywhere in the buffer.
  - So there is no extra BIOS call per key check. CODE-\ is also caught behind another CODE-key, which an AH=01h peek would drop with it (the BIOS skips enhanced-only keys there).
  - A read waits in the hook with HLT, peeking with the caller's own kind (AH=01h for 00h, 11h for 10h). So the BIOS's skipping happens while the hook still sees CODE-\.
  - **Never inside a hardware interrupt.** A TSR may look at the keyboard from INT 1Ch, which the BIOS's INT 08h calls before its EOI. A console brought up there would wait with the timer's IRQ in service, so the keyboard's IRQ, ranking below it, could never come: the 1520 would hang. So the hook reads the PIC's in-service register (OCW3 0Bh, as the kernel's screen capture does). If anything is in service, it still takes CODE-\ out of the buffer (the BIOS's AH=01h further down would drop it), notes it, and brings the console up at the next INT 16h call made with nothing in service. (Found in PR #27's review; T1C.COM, a TSR peeking from INT 1Ch, and BUSY.COM, three seconds without a key call, reproduce it.)
  - **While the console is up, others' peeks (AH=01h/11h) see no key.** The console reads the BIOS directly, but a TSR peeking from an interrupt meanwhile would make the BIOS's AH=01h drop the CODE-\ meant for the console, which would then never go away.
  - pcemu now models the buffer:
    - the first 15 of its queued keys sit in 40:1Eh-3Dh as the BIOS would hold them, going in at the tail;
    - the head moves on as INT 16h takes them;
    - what guest code changes there goes back into the queue.

    All 1050 existing checks passed on that change alone, before any resident code.
- **The program's type-ahead:** keys in the buffer when CODE-\ is taken are kept aside by the console and put back in front at pop-down, so they reach the program and not the console.
- **Everything the program had comes back byte for byte:**
  - its video mode;
  - the 32 KB of video memory (to EMS pages 2-3);
  - the BIOS's video data (40:49h-66h);
  - the text cursor, or the CGA colour register;
  - its four EMS windows, read and written directly as M: does.
- **The mouse:**
  - The Executive's pointer is drawn when it polls, so a move during the pop-up draws nothing.
  - A DOS program's INT 33h event handler (AX=0Ch) is called from the mouse's IRQ, on whatever stack is current: the stub's, during a pop-up. Clicks meant for the console reached the program, which can't be seen then (it could start a measurement), and a deep handler could overrun the stub's stack. The console swaps the handler out with AX=14h (no events) when it comes up and back when it goes (PR #27's review). AX=14h makes a DOS call (AH=62h, to note whose handler it is), so it is skipped while DOS is busy: the handler keeps running then. A handler that a TSR set is noted as the paused program's when it comes back, so the kernel takes it off when that program ends. The click counts (AX=05h/06h) still count the console's clicks.
  - A DOS program's INT 33h pointer is drawn from the mouse's IRQ. Moving TM5000G's mouse during a pop-up drew on the console, and after a move it left a wrong cell on TM5000G's screen. The console now hides the INT 33h pointer (AX=2) before keeping the screen and shows it again (AX=1) after putting it back.
- **The stack:** 384 bytes in the stub's block (conventional memory: an interrupt during the pop-up runs on it, and an ISR remapping window 0 would break a stack in EMS).
- **`indos`:** its address comes from INT 21h AH=34h at load.
  - The stub passes it to the console, which says "DOS busy" in its band when the program was inside DOS (COPY CON at the prompt). (From CLAUDE 1.9 only where files can't be used: not over COPY CON.)
  - The console calls nothing but INT 10h, the BIOS's INT 16h and INT 33h (whose AX=14h makes a DOS call: only when DOS isn't busy).
  - Acting on it (file requests while a program is paused) comes after M3; M3's name lookup uses it (one call deep only).
- **The stub's header**, at the same offsets in every CLAUDE.COM from now on: `CLRS` (100h), its version, where its hook is, the INT 16h it goes on to, its EMS handle, and the byte that stops pop-ups (10Dh). `/U` finds the stub among the memory blocks (owner 8, `CLRS` at 100h), so `/R` also knows when it is there already, even under another hook, and both work on a stub that another version of CLAUDE.COM left (copied to the floppy without a restart). M1 at first found it by its hook's offset, which another version's wouldn't share (PR #27's review). `/U` is refused when INT 16h no longer points at the stub's hook; otherwise it puts INT 16h back and frees the EMS pages and the block.
- **Cost:**
  - **Resident:** 768 bytes of conventional memory: 360 of code and data, the 384-byte stack, and the block's MCB (704 before the review's fixes: the header, the in-service check, the no-key answer). DOS programs get 0.8 KB less, at the prompt and from the Executive alike (the plan's target was 1.2 KB). `/U` gives all of it back.
  - **EMS:** 3 pages (48 KB).
  - **CLAUDE.COM:** 16,646 bytes on disk (+4,326). It takes 32 bytes more in memory when it runs as chat or Term (`res_args`).
- **Tests** (`test_resident.py`, 43 new checks; the spike's 21 stay as they were):
  - `/R`, `/R` again, `/U`, `/U` again, `/U` under RSPIKE, no EMS: messages and exit codes;
  - memory at the prompt, from the Executive, and after `/U`; the EMS handle kept after CLAUDE.COM ends, and freed by `/U`;
  - the console over EMSUSE (AH=00h and AH=10h readers, all four EMS windows), over GFXUSE in modes 4, 6, 40h and 3 (video memory and 40:49h-66h byte for byte), over COPY CON ("DOS busy"), over the Executive (the mouse meanwhile), and over TM5000G (its keyboard, mouse and bus polling with no key pressed, auto-detect, and the mouse meanwhile);
  - type-ahead kept;
  - CODE-\ behind CODE-;;
  - from the review: CODE-\ while T1C peeks from INT 1Ch and BUSY runs (no console inside the timer's interrupt, the console at the prompt's next key call, with nothing in service, and back again); MHAND's event handler (no calls from the console's clicks, and back afterwards); `/R` and `/U` from a CLAUDE.COM whose stub is laid out otherwise (`-DSTUB_PAD`), both ways; the stub at the top with HOLE.COM's hole lower down; what only `/R` and `/U` use lies where BSS goes, below the stack `/R` runs on (from CLAUDE.MAP).
- **Controls:** each design choice was run against the alternative, which failed:
  - RSPIKE's AH=11h hot-key check misses CODE-\ behind CODE-;;
  - a console that leaves the keys in the buffer gives EMSUSE 1 key of 3;
  - without hiding INT 33h's pointer, TM5000G's screen gets a wrong cell;
  - the PSP-kept stub cost a program from the Executive 43.6 KB;
  - from the review: without the in-service check, the console comes up inside the timer's interrupt (in service 01h); without the no-key answer, T1C's peeks eat the CODE-\ that should close the console; without the swap, MHAND counts 8 calls instead of 2; finding the stub by its hook's offset, the other version loads a second copy and can't take it out; a second AH=48h puts the stub in HOLE's hole.
- **On the 1520:** `os/claude/M1TEST.BAT` runs these step by step and logs the answers to `M1TEST.TXT`. Copy it with CLAUDE.COM, EMSUSE.COM and GFXUSE.COM (`os/claude`), MEMSZ.COM (`os/tests`) and TM5000G.EXE. It was run through in pcemu, answering as its instructions say. It checks:
  - MEMSZ, `CLAUDE /R`, MEMSZ again, and `CLAUDE /R` once more (refused).
  - CODE-\ and back:
    - over EMSUSE (its four EMS pages kept);
    - over GFXUSE in modes 4, 6 and 40h (`M1TEST GFX 6` runs one mode on its own, with `CLAUDE /R` loaded);
    - over COPY CON (the band says DOS busy, and COPY CON goes on; from CLAUDE 1.9 it doesn't, but for MULTITASK=1);
    - over TM5000G, with its mouse moved while the console is up.
  - Keys typed straight after the console goes away reach the program.
  - `CLAUDE /U`, then MEMSZ as at the start.
  - By hand at the end: CODE-\ over the Executive.

  CODE-\ behind another CODE-key and keys typed just before CODE-\ need timing no one can type; the emulator's tests cover them. Nothing on that floppy looks at the keyboard from an interrupt, so the 1520 can't show the in-service check either (pcemu can't show the hang itself: it lets a nested IRQ 0 in).

### M1 on the 1520 (2026-10-14)
`M1TEST.BAT` with M2's CLAUDE.COM, no Pi on the bus (`os/bench/M1TEST_1520_2026-10-14.TXT`):

| Step | Result |
|---|---|
| 1. `CLAUDE /R` | 559.5 KB for programs before, 558.7 KB after: 0.8 KB, as in the emulator. `/R` again refused |
| 2. EMSUSE | its four EMS pages kept (0 bad); the console came up and went away |
| 3. GFXUSE | modes 4, 6 and 40h: video memory and 40:49h-66h kept (0 bad). Modes 4 and 40h looked the same; mode 6 "DIFFERENT" (below), and the same after the fix |
| 4. COPY CON | the band said DOS busy, and the file held the line typed |
| 5. Keys after | typed straight after CODE-\, they reached EMSUSE (2 keys, 0 bad) |
| 6. TM5000G | came back right and worked |
| 7. `CLAUDE /U` | taken out: 559.5 KB again |

### Mode 6 on the 1520
Joshua: before the pattern flashed briefly, the screen was black. Two causes, both found and fixed, and the fix seen on the 1520 (2026-10-14):

- **GFXUSE's colour.** It set colour 1 with INT 10h AH=0Bh BH=0. In mode 4 that is the background; in mode 6 it is the colour of every set pixel. The 1520 shows CGA colours as greys through the V6366's colour maps (`grid_vid2.asm`, `VidExpRegTable`), and colour 1 is black in four of its six, the default among them. So mode 6's pattern was drawn black on black. GFXUSE now sets colour 0Ch, which is a grey in all six maps, neither black nor the BIOS's default white. A colour register not put back would now show: mode 6 in white, or mode 4 with a black background. (Mode 4 couldn't show it before: on the 1520 its old register and the BIOS's default give the same greys.)
- **The console's order going back.** It set the program's mode, copied its 32 KB of screen back, and only then wrote the program's colour register (port 3D9h, from 40:66h). The BIOS's mode set writes its own register: 3Fh, white, in mode 6. So for as long as the copy took, the pattern showed in white: the flash. The console now writes the program's register straight after the mode set, before the screen. It does so in the text modes too, where it is the border colour and wasn't put back before. RCON is 2 bytes smaller and CLAUDE.COM 19,558 bytes; the resident part doesn't change.
- **Test:** pcemu now has the colour register as the 1520's BIOS keeps it: the mode set (30h, 3Fh in mode 6, kept in 40:66h, and not written to the port above the CGA modes), AH=0Bh, and port 3D9h. A new check in modes 4, 6 and 3 watches each write to 3D9h while the console goes back: the register must end as the program's, and none may be written with the program's screen already back. The old console fails it in modes 4 and 6 (the register written last, with the screen back); the new one passes. `test_resident.py` now has 70 checks.
- **On the 1520, again:** with the fixed CLAUDE.COM and GFXUSE.COM, `CLAUDE /R` and `M1TEST GFX 6` (the last two lines of the log): 0 bad, and it looked the same. Joshua: it worked.

## M2: Claude Code in the pop-up (2026-10-13)
CODE-\ over a program now brings up Claude Code itself: Term, the same `claude` on the Pi that `CLAUDE /T` shows, so what is typed in one is on the other's screen. CODE-\ (or CODE-Q) goes back to the program as it was. This runs in the emulator. On the 1520 only the no-Pi case can be tried until the Pi 5 and the bridge are set up.

- **The console is CLAUDE.COM's own Term code**, assembled into `RCON.ASM`: `TERMLINK.INC` (the link), `TERMCELL.INC` (the screen and its shadow) and `TERMKEYS.INC` (the keys). `GLP.INC` (the message types) and `CELLTEXT.INC` (the band's text) were split out of CLAUDE.ASM; CLAUDE.COM assembled byte for byte the same after the split. Where the console differs, a define says so:
  - **no INT 60h AH=0Bh** (`NO_SRQ`): the driver's SRQ check clears the flag the program would see, so the console finds the Pi's answer by serial-polling the bridge every few ms instead;
  - **the keys through the BIOS's INT 16h**, past the stub; CODE-\ and CODE-Q go back (`K_QUIT`, `K_QUIT2`).
- **No DOS calls.** The GPIB driver is found from the vectors at every pop-up (60h-66h, 'GRIDGPIB' at entry+2, AH=0 answering 4747h). The HELLO says `app=resident`, the bridge's address and `grid=`; gridlink gives `app=resident` Term, the same session as `app=term`.
- **Its data stays in its EMS page between pop-ups:** Term's 24-row shadow, the link's state, the title. `CLAUDE /R` clears the page after the code: 5.6 KB of code and font, 11.1 KB of the 16 KB with the data and the shadow (checked when it is assembled). `CLAUDE /R /A:nn` sets the bridge's address (7 if not given).
- **Each pop-up:**
  1. Term's screen is drawn from the shadow at once, then the console says HELLO.
  2. The HELLO carries a CRC-16 of the shadow and the cursor (`screen=`). If that is the screen of the Pi's last frame, or of the one before, gridlink goes on from it and sends only what changed while the program ran (0 bytes in the test, where nothing had; the first paint and an echo had taken 409). Otherwise, when CLAUDE /T had the link meanwhile, the Pi draws the screen again from a clear one.
  3. Keys go to Claude Code and frames come back, as in CLAUDE /T.
- **Going back:** the keys typed before CODE-\ go to Claude Code first, then the last frame gets its answer, so the bridge never holds an answer (and SRQ) while the program has the bus; 3 s at most. If the link failed meanwhile, the bridge gets SDC. The program's screen, BIOS data, keys and mouse pointer come back as in M1.
- **Its own GPIB timeout:** the driver's timeout is global, so the console would run under the paused program's. That is 2 s by default, but TM5000G sets it for each call, and its TIME OUT n can leave up to 60 s, which each byte to a stuck bridge would wait (the console sluggish, the 3 s of going back stretched). The console sets 2 s with AH=0Ah at each pop-up, and puts the program's back when it goes (PR #28's review).
- **The GRiD's tools wait for M3.** While the console is up, gridlink's MCP tools (files, programs, GPIB) answer that Claude Code is popped up over a DOS program and that CLAUDE /T has them. A request that reaches the GRiD anyway is answered at once with status F6h, a DOS program is paused. gridlink doesn't set the clock from the console.
- **CLAUDE.COM turns the hot key off while it runs** (chat, /T, and the programs it runs), because it has the link. It finds the stub among the memory blocks, as `/U` does (`res_peek`, before BSS is touched), so also under a program that hooked INT 16h after it (PR #28's review; M2 first looked only at INT 16h's head), and sets the header's `r_off` (10Eh), and clears it when it ends. `CLAUDE /R` again clears it too, should CLAUDE.COM ever end without. `r_off` is new in M2, so the header's version is now 2, and a stub of version 1 is left alone. (Not `r_inpop`, which since the review also makes the stub answer others' peeks with no key: CLAUDE.COM's own keys would never come.)
- **The driver's SRQ flag:** the console never clears it. The bridge's own requests while the console talks to the Pi can set it, so after a pop-up AH=0Bh may say yes once with no instrument asking; a program that then polls its instruments finds none. Nothing an instrument asked for is lost.
- **Cost:**
  - conventional memory: unchanged from M1, 768 bytes (0.8 KB);
  - EMS: 3 pages as in M1 (4.9 KB of the console's page spare);
  - CLAUDE.COM: 19,560 bytes on disk (+2,914, the console's code and font), and 48 bytes more in memory when it runs as chat or Term (80 more than before M1);
  - the stub's stack: at most 92 of its 384 bytes in the tests (Claude Code, typing, the mouse, GPIB, over TM5000G). pcemu's BIOS is Python, so the 1520 BIOS's own use isn't counted; M1's pop-ups on the 1520 already ran the BIOS on this stack.
- **Tests** (`test_resident_term.py`, 49 checks, on the kernel harness, which now has Term too: gridlink's router and the stand-in Claude Code in a pty):
  - over EMSUSE: Claude Code, its screen in step with pyte's on the Pi, typing ("You said: hello"), back with the screen and BIOS data byte for byte and the bridge quiet; the second pop-up drawn from the shadow before the Pi answers, then resumed (0 bytes), a 60-line answer, the same `claude`;
  - Claude Code at work while the program runs: `big` and Enter typed right before CODE-\ still reach it, and the next pop-up goes on from the kept screen with the 60 lines that came meanwhile (scrolled); CODE-\ in the middle of a streamed answer, the bridge quiet, and the rest there at the next pop-up;
  - with CLAUDE /T: what was typed in the console is on CLAUDE /T's screen and the other way round; the hot key off while CLAUDE runs and on after; the console drawn again from a clear screen afterwards (its CRC isn't the Pi's last);
  - the tools: an MCP call refused with the reason, a REQUEST sent anyway answered F6h at once;
  - no bridge, with `CLAUDE /R /A:9`: the band says "No answer from the bridge at GPIB address 9", and CODE-\ goes back in 37 ms;
  - the program's GPIB timeout at 60 s: the console's own 2 s while it is up, and the program's back after; then a stuck bridge (on the bus, taking no byte): CODE-\ still goes back in 1.8 s;
  - over TM5000G: Claude Code and typing, the mouse moved meanwhile; afterwards its screen as it was, REN as it was, no chip reset or IFC, its SRQ flag still set, no AH=0Bh from the console, the bridge quiet, and auto-detect still finds the three instruments;
  - the stub's stack, painted before and read after;
  - claude-link's `test_term.py`: the encoder's resume (the last frame's screen, the one before, a wrong CRC, none).

  `test_resident.py`: CLAUDE.COM over a stub of version 1 (built `-DSTUB_VER=1`) leaves its byte 10Eh alone while it runs (in PR #27's stub that is `r_pend`, and writing it would bring the console up over CLAUDE), and over its own sets and clears `r_off`; without the version check, 10Eh is written. Under HOOK16, a TSR that hooks INT 16h after `CLAUDE /R` and passes every call on, CLAUDE.COM still finds the stub and sets `r_off`, and CODE-\ in CLAUDE brings no console. claude-link's `grid_emu` now answers INT 21h AH=52h (its blocks as an MCB chain), as CLAUDE.COM walks the memory blocks at its start. M1's other 64 checks pass with the new console: they have no bridge on the bus, and the band says so. The console keeps the review's fixes to M1's (the program's event handler swapped out, `keys_back`'s room), and its tests (MHAND, T1C and BUSY) run with it.
- **Controls**, each run against the change it guards and failing a check:
  - going back at once: the keys typed before CODE-\ are lost, and over TM5000G the bridge still holds the answer and SRQ;
  - waiting for the answer but not sending the keys typed before CODE-\: they never reach Claude Code;
  - CLAUDE.COM's AH=0Bh in the link: 627 calls while the console was up;
  - no REPLY to a REQUEST: the call waits instead of getting F6h;
  - no screen from the shadow at the pop-up: blank, and as the Pi goes on from the kept screen it sends nothing, so it stays blank;
  - the program's GPIB timeout kept: 60 s while the console is up, and with the stuck bridge CODE-\ not back after 10 s;
  - the stub looked for only at INT 16h's head: under HOOK16, `r_off` stays 0 while CLAUDE runs, and CODE-\ there brings the console up over it.
- **On the 1520 now:** with no Pi, the console says "No answer from the bridge at GPIB address 7", and CODE-\ should still come back at once. `M1TEST.BAT` went through that with M2's console on 2026-10-14 (above): it came up and went back over every program. The rest waits for the Pi 5 and the bridge.

## M3: Claude sees the paused program and types into it (2026-10-14)
In the console, Claude Code can now look at the program it is popped up over and type into it: it drives TM5000G. Decided with Joshua: after Claude's keys the console comes back up in view, not silently as the plan had it, so the keys can be watched as they play, and Claude Code's question is on the screen before each `grid_type`.

- **Two tools, in the console only** (gridlink's MCP server):
  - `grid_program` looks: the program's name and its screen (text, or an image of a graphics screen).
  - `grid_type` asks every time: keys into the program (`1A{WAIT 30}`), then its screen.
  - The other GRiD tools still answer that they can't run while a program is paused (the program holds the GRiD); outside the console these two answer that no program is paused. The tool server now asks gridlink about each tool by name.
- **The program's name:** the console asks DOS for the current PSP (INT 21h AH=62h) and takes the file name from the path after its environment's strings. That is a DOS call from inside INT 16h. The kernel runs a call made inside another on a stack of its own (`astack`), its frame there and nothing kept outside it, so the call is safe while DOS is one call deep; TM5000G reads its keys through DOS, so it is always one deep when the console comes up over it. Two deep, that stack is an INT 24h handler's, and the name is left out. It is also left out when the environment's block isn't the program's any more (EXEC gives it the block; a program that freed it leaves PSP:2Ch pointing at a block that may hold anything now), and it ends at a control character, so nothing stray reaches HELLO's lines (PR #30's review). HELLO says `prog=TM5000G.EXE`, and the band shows it after the title (where a long status on the right, "No answer from the bridge…", covers it: the band reads as in M2 then, as M1TEST expects).
- **SCREEN** (11h) answers with the program's screen as the console keeps it, in CLAUDE.COM's SCREEN format:
  - text from 40:4Eh (any page) at 40:4Ah columns by 25 rows;
  - modes 4, 5 and 6: 16 KB; anything else (40h): 32 KB;
  - mode 7 (B000h) isn't in the console's copy: status F5h.
  - The reply goes straight from the saved screen (windows 1-2), its first 11 or 12 bytes just in front of it: the console page's last 12 bytes, kept free, or for a text page further on the saved screen's own bytes there, kept aside and put back once the reply has gone, or when the console goes.
- **TYPE** (new request 12h): a key script in RUN's format (keys and waits; `{SNAP}` only at the end, where the screen is taken anyway), at most 2 KB, about 1,000 keys, kept in the console's page.
  1. The console goes back to the program at once.
  2. At each INT 16h call the stub maps the console's page into window 0 for a moment and asks it for the next key (`r_feed`, the console's `rc_feed` at E000:0005): a peek sees it, a read takes it, a wait holds them back, and real keys still work.
  3. When the keys are done the stub brings the console back up at the program's next key call, as CODE-\ does (after the same in-service check), and the console answers TYPE with the program's screen then and "all played".
  4. It comes back without a HELLO, the link as it was (the frames numbered on): gridlink cancels a waiting call at a HELLO. If the link failed meanwhile, or the bridge was cleared on the way down, it says HELLO, and Claude gets an error instead.
  - CODE-\ while the keys play stops them: the console comes up and answers with the screen, not all played. The stub's flag is cleared at every pop-up.
- **Going back** (PR #30's review): when the user goes back to the program with CODE-\ (not when the console goes for TYPE's keys), the console sends EVENT 04h, away, with the last keys. gridlink then ends any call waiting for the GRiD and refuses new ones at once ("the user has gone back…") until the next HELLO. Before, a call made in the 10 s after waited 120 s for an answer, or ended at the next pop-up. A REQUEST that reaches the console on its way out gets no answer, as the EVENT has ended it on the Pi, so the program doesn't wait while a screen goes. (With M4's background, files and GPIB go on instead: below.)
- **Cost:**
  - conventional memory: the stub is 816 bytes with its MCB (768 in M2): its code grew 46 bytes, from 368 to 414 (the feeder's call, less 8 bytes of a test `r_hot` never needed, PR #30's review), three paragraphs more (47 to 50). DOS programs still get 0.8 KB less;
  - EMS: 3 pages as before. The console is 6.4 KB of code and font, and with its data and the 2 KB for keys it uses 13.9 KB of its 16 KB page (2.1 KB spare);
  - CLAUDE.COM: 20,404 bytes on disk (+846), and no more memory than M2's when it runs as chat or Term.
- **Tests** (`test_resident_term.py`, `t_type` and `t_drive`, 28 checks):
  - over TESTKEY (it echoes its keys): HELLO and the band name it; `grid_program` has its screen, and SCREEN's bytes are its cells byte for byte; `grid_type "hello"` plays into it, and the console comes back by itself with "TESTKEY ready: hello", with no HELLO (gridlink's count of them unchanged) and in step with the Pi, the band's status its own text; CODE-\ during a `{WAIT}` stops the keys, and TYPE says so; afterwards TESTKEY has had the 5 keys and no more;
  - going back: after CODE-\, `grid_program` is refused at once (the EVENT), and works again after the next pop-up's HELLO; a `grid_program` on its way as the user presses CODE-\ (sent between the console's polls) gets no answer from the console and ends at once on the Pi;
  - the name: TESTKEY's environment's block made someone else's, no name in HELLO or the band; a line feed put in its name, the name ends there and HELLO has no line of its own for the rest;
  - into EMSUSE and EMSUSE /X (INT 16h AH=00h and 10h), which map EMS in all four windows and check them after every key: `grid_type "abc"`, then "3 keys, 0 bad";
  - over GFXUSE in mode 6: an image, and SCREEN's 16 KB byte for byte; GFXUSE's own check afterwards, 0 bad;
  - over PAGE1, a new test program with its text on page 1 (B800:1000h; pcemu's INT 10h AH=05h now keeps 40:62h and 40:4Eh as the BIOS does): its page in SCREEN; `grid_type "x"` into it and back with page 1, the band's status the console's own; its 32 KB byte for byte afterwards, the 12 bytes in front of page 1 too;
  - over the Executive (mode 40h): SCREEN's 32 KB byte for byte, the reply running to the last byte of window 2, and its screen as it was afterwards;
  - over TM5000G: `grid_program` has its main menu and its name; `grid_type "1A{WAIT 60}"` (Configure Modules, auto-detect) and the console comes back with FG5010, 8753D and DC5009 found, and TM5000G is left so.

  claude-link's `test_mcp.py`: the two tools (look and ask), `grid_type`'s keys (a `{SNAP}` at the end dropped, one in the middle refused, too many keys or waits refused before the GRiD), its answers (all played, stopped, no screen), and `grid_program` without a name.
- **Controls**, each run against the change it guards and failing a check:
  - a HELLO when the console comes back: gridlink cancels the call ("the GRiD restarted the link"), 4 checks;
  - the bytes in front of the screen not put back: PAGE1's screen differs at FF5h;
  - the name asked only when DOS isn't busy: none for TM5000G;
  - the stub's flag not cleared at the pop-up: the keys after CODE-\ play on (into GFXUSE and PAGE1);
  - a peek that takes the key: TM5000G loses its keys (it peeks before it reads), and no auto-detect;
  - from the review: the status not set after TYPE's return: the band's status is what was at the reply's address (over TESTKEY, empty), over TESTKEY and PAGE1; no EVENT away: gridlink doesn't learn the user went back, so the call after CODE-\ isn't refused, and the one on its way isn't ended; requests answered on the way out: the console sends TESTKEY's screen for a call already ended; the environment's owner not checked: the name from a block that isn't TESTKEY's in HELLO; the name not ended at a control character: a line of its own in HELLO.
- **On the 1520 now:** nothing new to try without the Pi: the tools need it. The stub's new code runs only while Claude has keys for the program, and M1's and M2's checks pass in the emulator, so M1TEST should go as it did; worth a rerun with this CLAUDE.COM.

## Open points, after M3
- **Programs that hook INT 16h themselves**, and programs that read the keyboard through INT 09h only (not covered: Phase 2 left INT 09h hooks out). `/U` refuses while one sits above the stub. (CLAUDE.COM finds the stub under such a program too, and turns its hot key off.) Claude's keys (TYPE) go in through the stub's INT 16h too, so such a program doesn't get them either.
- **An empty bus** (no instrument, no bridge): what the 1520's 7210 and the driver do with the console's commands to the bridge, and how long CODE-\ then takes, is to be seen on the 1520.
- **A CRC that matches by chance** (1 in 65,536) would leave a wrong Term screen until those cells change; CODE-R draws it all again.
- **Files and GPIB while a program is paused** (the plan's READ, DIR, WRITE..., GPIB queries): done in CLAUDE 1.9, below. The kernel already runs a call made inside another on a stack of its own, so no kernel change was needed. Then M4 (0.5b), Claude working between keys: done in CLAUDE 1.10, below.
- **The mouse during a pop-up:** the INT 33h pointer is hidden meanwhile, and its event handler swapped out unless DOS is busy (M1). The console itself ignores the mouse. M3's name lookup showed that AH=62h (which AX=14h makes) is safe while DOS is one call deep: the kernel runs a call made inside another on a stack of its own. So the swap could happen then too (TM5000G reads its keys through DOS: always one deep); not done in M3, as it needs its own test. If the kernel's INT 33h noted a handler's owner without a DOS call (reading the current PSP itself), AX=0Ch and 14h would be safe from anywhere.
- **Keys that quit the program:** the rest of a TYPE's keys go to whatever calls INT 16h next (the prompt, the Executive), as RUN's do, and the console comes back over that. `grid_type` says so.
- **The program's name when DOS is two calls deep** (an INT 24h handler reading a key): not asked, as that stack is the handler's. A kernel call giving the current PSP's address (as AH=34h gives `indos`'s) would make it free.

## With Lodestone's multitasking (M7c, 2026-10-22)
`docs/lodestone-multitasking.md` (M7c) has the details. With `MULTITASK=1`:
- **`CLAUDE /R` tells MT about the stub** (`MT_TSR`, F0h AL=1Ah). MT may then switch from the stub's key wait, so tasks behind keep running while the front program waits for a key through it. The stub reads which task is in front and which is running. A task switched from there waits as in MT, so it costs the others nothing; behind, the loop looks at the BIOS's buffer only with AH=11h, which drops none of the front task's keys.
- **The console comes up only in the front task's call.** A CODE-\ seen in a background task's call waits for the front task's next one, which MT brings on as for a key. TYPE's keys go to the front task alone, and while they are under way (a wait, or just done) the front task's call asks MT for its turn, so a task behind doesn't hold them up.
- **CLAUDE.COM run as a task** turns the pop-up off for every task while it runs (`r_off`); ended with `KILL`, it leaves it off until `CLAUDE /R` again.
- **CODE-Tab typed in the console is the console's,** not a switch.
- **`CLAUDE /R` inside a task is refused** (exit code 3): load it at the Executive's prompt (CODE-P), before starting tasks. `CLAUDE /U` refuses while other tasks exist (M7a).
- **The stub is version 3** (`r_mt`, after `r_pend`).

## The console on the GPIB driver 1.23 (2026-10-23)
CLAUDE.COM took up the kernel driver's new calls in 1.21 and 1.23; the console now does too.
- **The driver's frame check** (1.23, `KSUM`): the driver keeps the Fletcher sum as it moves the bytes. The console checks each frame from the Pi from that sum in a dozen instructions (`ks_check`), and its own frames go out with the check the driver adds (INT 60h 02h AL=3). On the 1520 the console's own pass was about 2.65 ms of the ~5 ms between 2 KB frames, as CLAUDEP measured for CLAUDE.COM; that is the time saved, to be measured on the 1520 for the console.
- **The SRQ interrupt** (1.21): the console reads the driver's count (AH=0Eh, AL=FFh: only asks) and never calls AH=0Bh, which would clear the program's SRQ latch. Waiting for an answer it sleeps (HLT) until the count moves, a tick or a key, and serial-polls once the SRQ has come, not every 2-4 ms by the PIT. With `GPIBIRQ=0` it polls as before.
- **GF_WAKE**: with the interrupt, the console's HELLO offers it, so the Pi rings (an SRQ) when it has something for a quiet console, and the console POLLs at once rather than at its next idle POLL, once a second. In the emulator a title from the Pi reached the band in 9 ms, against 837 ms polled.
- **Never a ring for the program.** gridlink rings only while the console is up: not once the user has gone back (EVENT away), and not while TYPE's keys play (the console is down then without saying so: `Grid.typing`). `Term.may_ring` says so, and `Link.ring_check` takes back any ring it gave meanwhile. (M4: while away with a quiet bridge it rings, quietly, for the background: below.)
- **The next frame straight after an answer** (`LINK_CHAIN`), as CLAUDE.COM; not while the console is going back, when only what is queued goes.
- **A fourth EMS page.** Term's shadow (3,840 bytes) moves out of the console's page into a page of its own in window 3 (EC00h). The stub maps all four of its pages and, as before, saves and puts back all four of the program's windows. `CLAUDE /R` now asks for 4 free pages (64 KB); the stub is version 4. TERMLINK's CRC reads ES:SI in RCON (ES = CS but for the shadow's CRC in HELLO). The console's page has 3,801 bytes free (it had 4), which files and GPIB in the pop-up can use next.
- **An SRQ line held by another device.** When an instrument of the program's holds SRQ (asking for service), the bridge's SRQ makes no edge and no interrupt, so each answer would wait for the next tick (~55 ms, against 2-4 ms polled). An answer found at a tick's look with no interrupt for it sets `srq_held`: from then on the link polls by the PIT and doesn't sleep for an SRQ, until an answer comes with its interrupt again (the line has been let go). Before the 2026-10-26 audit's X49 it stayed set until the next HELLO. This is in TERMLINK, so CLAUDE.COM does it too.
- **A TYPE given up on.** If the Pi's call times out while the program isn't yet back at a key call (a busy program, or keys it never reads), `Grid.type_out` keeps the rings off until the console is heard from (TYPE's reply comes first) or says HELLO.
- **Cost:** RCON.BIN 6,868 bytes (+386), CLAUDE.COM 21,756 (+434, with CLAUDE 1.8); EMS 64 KB (+16 KB). Conventional memory is unchanged: the stub is still 816 bytes with its MCB, as `r_hw`'s fourth byte fits in its paragraphs.
- **Not changed:**
  - While the console is up, the program's SRQ latch still gets the bridge's SRQs. The driver ORs every SRQ it sees into the latch: from the interrupt, and from its polled reads of ISR2 before 1.21 too. So TM5000G may see one SRQ after a pop-up and serial-poll its instruments for nothing. Taking those out would need a driver call to put the latch back.
  - A TYPE's own REQUEST isn't rung for: the rings are off from the moment it is queued, so the console fetches it at its next idle POLL (up to a second).
  - A ring that comes just after the idle console's last look can wait a tick.
  - `srq_held` can still latch when two SRQ edges merge into one interrupt (as the PIC's request register does if the first isn't serviced in time; seen in the emulator after seconds of back-to-back polling). The link then polls by the PIT until an answer comes with its interrupt again (X49).
- **Tests** (`test_resident_term.py`, `t_driver`, 24 checks, on the Pico bridge's model, which can ring):
  - every frame from the Pi passed by the driver's sum, and every frame of the console's was good at the Pi;
  - the count was found, GF_WAKE offered and taken up by gridlink;
  - one serial poll an answer, and the PIT never asked;
  - the console asleep while answers are due;
  - a title from the Pi rings a quiet console;
  - no ring, and no SRQ held by the bridge, while TYPE's keys wait, after a TYPE given up on (until the console is back), or once the user has gone back;
  - a second session in the same boot takes its answers at their SRQ as the first did;
  - never AH=0Bh;
  - with `GPIBIRQ=0`: no count, no GF_WAKE, polled by the PIT, never asleep while an answer is due, the title at the next idle POLL, no ring;
  - in a boot of its own, the SRQ line held: the console finds that out and polls by the PIT; another device's edge meanwhile doesn't make it sleep for an SRQ; once the line is let go, an answer with its interrupt puts it back to sleeping till the SRQ (X49).
- **Controls**, each run against the change it guards, and each failed a check:
  - gridlink ringing whatever the console's state (both no-ring checks);
  - TYPE not counted, or a TYPE given up on not counted (their checks);
  - the user's going back not counted;
  - the console without the driver's check (its frames counted by its own scan);
  - without GF_WAKE, or without the count (no ring; the title at the next idle POLL);
  - waiting by the PIT (it is asked);
  - not sleeping while an answer is due;
  - AH=0Bh put back (47 calls);
  - no held-line fallback (the PIT never asked);
  - sleeping with the line held.
- **Review** (three reviewers, then the fixes re-reviewed). It found:
  - the TYPE given up on, which reopened the rings while the console was still down;
  - the held line's tick-per-answer;
  - a few test checks that proved less than they said: the driver's check tied to `ksum`, and the ring's time bound tightened from 300 to 100 ms.
  - the re-review: `srq_held` could latch when an answer's SRQ came between the tick's look and the serial poll (the count is now read again before it latches), and a REPLY landing just as a TYPE timed out could leave `type_out` set (it is set only if no REPLY came during the call).

## Files and GPIB in the pop-up (CLAUDE 1.9, 2026-10-23)
With the console up, Claude can now use the GRiD's files and its GPIB instruments, as under CLAUDE /T: `grid_files`, `grid_change_files`, `gpib_read`, `gpib_measure` and `gpib_send`. `grid_command`, `grid_info`, `grid_screen` and the picture tools still say why not.
- **The same code as CLAUDE.COM's.** The request handlers (DIR, READ, WRITE, DELETE, RENAME, MKDIR, RMDIR, STAT, FREE, GPIB) moved out of CLAUDE.ASM into `OPS.INC`, which both include; INFO and SETTIME stay CLAUDE.COM's (`%ifndef RCON`). CLAUDE.COM was byte-identical after the move; then WRITE's close got its error checked (a disk error there was reported as success), for both. The console runs them from its loop (`req_service`), as CLAUDE.COM does, not from inside the link's frame handling.
- **When DOS may be called** (`dos_ok`, settled at each pop-up):
  - DOS not busy (`indos` 0): the program called INT 16h itself (EMSUSE, the Executive).
  - DOS one call deep, in the kernel's own key wait: the INT 16h call's CS, on the stack the stub came in on, is the kernel's segment (the one AH=34h gave `indos` in). COPY CON, DOS's AH=01h-0Ah and AH=3Fh on CON, and TM5000G, which reads its keys through DOS. The kernel runs a call made inside another on a stack of its own (512 bytes under `astack_top`), and its only INT 16h calls inside INT 21h are in its console reads, so no disk state is in use.
  - Not two deep, and not one deep from anywhere else: a program's INT 24h handler waiting for a key (CRITKEY) is one call deep, but the kernel is in the middle of the failed call.
  - Never from MT's segment (`MULTITASK=1`): MT's key wait calls INT 16h from there, and so does its INT 24h prompt (`mt_i24`), even with DOS not busy (a disk error under INT 25h/26h). So with tasks, files work over programs that call INT 16h themselves, and over COPY CON or TM5000G they get F7h (the kernel's own `con_ready` peeks still count as its key wait).
  - Never over DEFRAG (by its name, `DEFRAG.COM`; the screen saver runs it too): it reads and writes the disk itself, its FAT and directories in its own memory, so a file Claude wrote meanwhile could be lost when it writes them back. (Found in review.)
  - Otherwise a file request is answered F7h (DOS busy: gridlink says why) and the band says DOS busy, as it used to whenever DOS was busy at all. GPIB requests run anyway: they don't call DOS.
  - Not covered: a program's own INT 24h handler reading a key during INT 25h/26h (DOS not busy then; a critical-error flag in the kernel, as MS-DOS keeps next to InDOS, would close it); other programs that write the disk themselves; a program that calls INT 16h from an interrupt handler after its EOI (the stub's in-service check can't see that).
- **The nested call's stack** (512 bytes under `astack_top`, just above the paused call's frame, so an overflow would wreck that frame): in the emulator a read went 60 bytes deep (98 with the interrupts that came meanwhile). The emulator's BIOS runs outside the machine, so on the 1520 its INT 13h, the hardware interrupts during the call and a disk error's INT 24h add to that; the review put the worst case at about 330-430 bytes. Shift-PrtSc's file writes already run nested on that stack from the kernel's key wait, on the 1520 too. To measure on the 1520 (paint, use, read); enlarging it would cost space, not speed.
- **Devices.** A file request that opens a device's name (CON, AUX, PRN, GPIBnn..., in any directory, with any extension) is refused (5, access denied; IOCTL 4400h after the open): reading CON would wait for a key the console never gives, and hang it. gridlink refused the DOS names already, and now `GPIBnn` too. (Found in review.)
- **Each file request** runs with INT 23h and INT 24h the console's, and its own DTA, all put back after. A critical error fails the call (Fail, AL=3) instead of a prompt or the program's handler, which would run on our stack over Term's screen; ^C does nothing. The file's handle is in the program's PSP's table, closed before the reply. The program's DTA, INT 23h and INT 24h are as they were afterwards (the tests read them).
- **Room.** The request and its reply share one buffer in window 3, after Term's shadow (CF00h-F0FBh): each handler uses the request's arguments before it writes the reply. It is 8,700 bytes, so HELLO says `req=8700` (gridlink writes in 8 KB pieces) and a read answers 8 KB (gridlink's chunk). The frame being sent moves there too and grows to CLAUDE.COM's 3,300 bytes, which also makes SCREEN and TYPE's answers go in 10 frames, not 128. TYPE's key script is copied to a 2 KB buffer in the console's own page, as the stub's feeder maps only that page. Window 3 has 536 bytes left, the console's page 2,748.
- **HELLO** says `req=8700` and `ops=files,gpib`, and `grid=CLAUDE 1.9`. gridlink's `Term.why_not` lets the tools for what `ops=` lists through (`Term.paused_tools`), so an older console's tools still say why not. F7h has its own text.
- **The kernel's windows.** The disk cache and M: map pages into a window for a moment inside the kernel. Both pick a window the caller's buffer isn't in (the cache with interrupts off; M: maps into window 0, the console's code, while it copies, with interrupts on, but nothing of the console's runs from an interrupt). The tests read and write through the cache and through M:.
- **A request while a reply is on its way** (its bytes are the request buffer's) or one waits to run is dropped whole, not gathered over the reply: that only happens after gridlink gave up on a call (60 s), and gridlink makes one at a time. (Found in review: before, it could overwrite the reply's unsent frames, or run the waiting request's operation with the new one's arguments.)
- **GPIB:** as CLAUDE.COM's, with the driver's timeout the request's for its time and the console's 2 s after. Decided with Joshua: `scan` and `poll` stay allowed, and `gpib_read`'s description says that over a program that watches for service requests (TM5000G) they take the status bytes it was waiting to read. The driver's SRQ latch isn't touched (no AH=0Bh). `max_bytes` is at most 8,192 in the pop-up (gridlink refuses more, rather than a reply cut short).
- **Cost:** RCON.BIN 8,086 bytes (+1,218); CLAUDE.COM 22,974 (+1,218). No more EMS or conventional memory: the stub is unchanged.
- **Tests** (`test_resident_term.py`, `t_ops` and `t_ops_mt`, 35 checks, and one more in `t_tm5000g`; `test_term.py`'s `test_resident_tools` in claude-link):
  - over EMSUSE (DOS not busy): HELLO's `ops=` and `req=`; list, a 22 KB read (three reads), a 23 KB write through NAME.$$$ read back, mkdir, rename, info, delete, rmdir, free; a disk error fails the call without a prompt; a 6 KB write sent while an 8 KB read's reply goes is dropped and the reply comes whole; a READ of `A:\CON.TXT` sent past gridlink's own check gets 5 at once; `gpib_read scan` finds the three instruments and not the bridge; `gpib_send` queries the DC5009; the program's DTA, INT 23h and INT 24h as they were; the stub's stack (60 of 384 bytes);
  - over COPY CON (the kernel's key wait): the same file checks; M:, written and read back; the kernel's second stack has room; COPY CON goes on afterwards with what was typed;
  - over CRITKEY's INT 24h handler waiting for a key: the band says DOS busy, a file request gets F7h, GPIB still works, and the handler gets its key afterwards;
  - over CRITKEY waiting for Esc, its INT 24h handler still in: a disk error fails our call without calling its handler;
  - over a program named DEFRAG.COM (DOS not busy): DOS busy, F7h;
  - with `MULTITASK=1`: files over EMSUSE; DOS busy over COPY CON;
  - over TM5000G (`t_tm5000g`): files work (its keys come through DOS);
  - gridlink: the tools by `ops=`, an older console's refusals, and `GPIBnn` as a device's name.
- **Controls**, each failed a check: the gate always open (CRITKEY's band); the gate shut at the kernel's key wait (COPY CON); the DTA not put back; INT 23h/24h not put back; no INT 24h of our own (the read over CRITKEY's handler hangs in it); no `ops=` in HELLO; TYPE's keys read from the request buffer (window 3, not mapped for the feeder); a request gathered over a reply on its way; a device opened (the console hangs on CON: 19 checks fail); DEFRAG let through. Not controlled by a test: MT's segment refused with DOS not busy (an INT 24h prompt under INT 25h/26h), the mouse handler swapped at the kernel's key wait, and WRITE's close checked.
- **Review** (three reviewers: the assembly, the kernel's side, gridlink with the tests and docs). Fixed: a request gathered over the reply on its way (the buffer they share); a device's name opened (CON hangs the console); DEFRAG; MT's INT 24h prompt with DOS not busy; the program's mouse handler left in at the kernel's key wait (its DOS calls would land on the kernel's second stack under ours: now swapped out there too); WRITE's close unchecked; GPIB replies over 8,192 bytes cut short without a word (gridlink now refuses `max_bytes` over 8,192 in the pop-up); `GPIBnn` names on the Pi; and stale text (claude-link's README, PROTOCOL's F6h, M1TEST step 4, which now expects no DOS busy over COPY CON without MULTITASK=1).

## M4: Claude in the background (CLAUDE 1.10, 2026-10-24)
Once the user has gone back to the program (CODE-\), Claude goes on: the files and GPIB tools work between the program's key calls, and nothing is drawn. This is 0.5b.

Decided with Joshua (2026-10-24):
- **The SRQ line: a quiet bridge.** The Pi's answers raise SRQ, and the kernel's driver puts every SRQ it sees in its latch (the IRQ 5 handler and every polled read of ISR2), which the program reads with AH=0Bh: TM5000G would serial-poll its instruments after each exchange. So the GPIB-Pico2 firmware got a quiet flag (CONFIG bit 2, `bridge fw 2026-10-24`, `bridge_pico2.uf2` built with arduino-cli 1.5.1 and `rp2040:rp2040` 6.3.0): the status byte as ever (60h, 40h for a WAKE, READY until read), the SRQ line never driven. There was no such mode before: the firmware's non-auto mode would have made the Pi keep READY itself and lose EARLY and HOLD, and GPIBIRQ=0 still latches SRQ on the driver's polled reads. An older firmware, or the AR488, gets no background: the Pi doesn't offer it there, and the tools say so as before.
- **No indicator** on the program's screen: it is never touched. The next pop-up's band says how many requests ran meanwhile (`3 in background`: run in a pass, F7h ones not counted). A permission prompt from Claude Code waits on Term's screen until then.
- **All drives**: a request runs whole in one pass, so a floppy access holds the program for as long as it takes (a disk error's retries too). A GPIB `scan` waits at every address that doesn't answer: in the emulator it held EMSUSE about 5 s; `gpib_read`'s description says so.

How it works:
- **The stub** (version 5): at every INT 16h call of the program's, a peek or a read's wait, it calls `r_bg` after the hot-key check. While the console has asked for it (`r_bgon`, header byte 10Fh, 1), 4 ticks (~220 ms) after the last look, with no TYPE keys under way, no CLAUDE.COM running (`r_off`; one before 1.10 doesn't know to clear `r_bgon`, so the stub clears it then), in the front task's call and with no hardware interrupt in service (as for the pop-up), it brings the console in exactly as for a pop-up, with `r_bgon` 2. Peeks count: TM5000G looks for keys (through DOS) between its bus work and never waits in a read. `r_popup` now keeps the caller's flags too (the console clears DF; a pop-up on CODE-\ did that before as well), so `dos_check` finds the caller's CS 2 bytes further up. `r_isr`, the PIC's in-service read, is shared with `r_hot`.
- **The console's background pass** (`bg_pass`): no screen kept, no mode set, no keys, no mouse pointer. It serial-polls the bridge (the driver's timeout at its shortest, 2 ticks: a bridge gone costs that once). Nothing (no 40h): back at once; in the emulator a look held EMSUSE under 0.75 ms. RQS (the Pi's WAKE, quiet), or work left over (a request taken on the way down; a REPLY queued or under way, a NAK, a frame to send again or one in flight from a pass that ran out of time: the Pi may have nothing to ring for then): DOS is looked at as at a pop-up (`indos`, the program's name, `dos_check`: settled again each pass), the program's mouse event handler swapped out if DOS will be called, the console's 2 s timeout, and the link runs as in the console, polled by the PIT every few ms (the session went over to that at EVENT 04h: no SRQ comes), until the Pi answers a POLL with a NOP and a request taken has run and its REPLY gone, 5 s at most. An answer due since an earlier pass gets its 2 s from this one: the bridge keeps it till it is read. Then everything back, and `r_bgon` 1 to look again; 0 after a link failure, or no answer to the serial poll (an SDC either way, which tells the Pi), until the next pop-up; a driver busy at the look (only one that can be switched from mid-call, under tasks) just waits for the next. A NOP from the Pi ends any REQUEST it had begun (it gave it up), so a pass never waits for the rest.
- **Only what needs no screen:** files (as `dos_ok` allows; F7h otherwise, also for a request kept from the pop-down if DOS is busy by the time it runs) and GPIB. SCREEN and TYPE are F6h (from CLAUDE 1.11 SCREEN is answered: below). CELLS and TITLE from the Pi wouldn't be drawn (the Pi sends none meanwhile), and a link failure draws nothing.
- **Going back:** when the Pi's HELLO said HF_BG, the console sends EVENT 04h as before and from then on polls by the PIT (the Pi makes the bridge quiet when it reads the EVENT, so its answers raise no SRQ). A REQUEST that arrives on the way out is kept (files and GPIB; not when the console goes for TYPE's keys) and runs at the first look, which comes at the program's next key call. At the end of a session the console sets `r_bgon` 1 if the user went back (not TYPE's keys), the link is up and idle, and the Pi works so.
- **gridlink:** at EVENT 04h with HF_BG it makes the bridge quiet (`PicoBridge.set_quiet`; if it can't, a bridge reconnected meanwhile with older firmware, there is no background), answers POLLs at once (the program waits meanwhile), sends no CELLS or TITLE, and ends only the calls the background can't answer (SCREEN, until CLAUDE 1.11: below): files and GPIB go on, and new ones are sent. `Link.ring_check` rings (WAKE, quietly) whenever it has something, whatever GF_WAKE and without giving up after five tries, since the console looks only at the program's key calls. The console stops the background only with an SDC to the bridge (a link failure in a pass, or the link not idle as it went), which the bridge reports: then gridlink ends the calls it kept and the tools say the user has gone back, as without the background (`Term.background`). Any HELLO from the GRiD makes the bridge loud again (`Link.handle`, before its answer: chat and CLAUDE /T too). `Term.why_not` lets the files and GPIB tools through while away (without the 10-s check: the background talks only when it has work) and names them for the rest. A call the GRiD hasn't taken when it times out (the program busy, not at a key call), or one ended by a HELLO before its REQUEST was queued, is withdrawn from the queue (`Link.withdraw`), so it can't run after Claude was told it failed.
- **CLAUDE.COM** turns the looks off when it starts (version 5 stubs): it takes the link, and the Pi's state for it is CLAUDE.COM's.
- **Cost:** the stub grows 94 bytes, so its block grows 6 paragraphs: 1,024 bytes with its MCB (928 before, since M7c's `r_mt`). RCON.BIN 8,690 bytes (+604), CLAUDE.COM 23,686 (+712); the console's page has 2,136 bytes free. No more EMS. Each idle look is a serial poll of the bridge every ~220 ms at the program's key calls; the stub's stack went 56 bytes deep in the background. A file read of several 8 KB pieces takes a pass a piece (each REPLY is answered at once, and the next piece waits for the next look).
- **Tests** (`test_resident_term.py`: `t_bg`, `t_bg_tm`, `t_bg_mt`, 36 checks; the bridge firmware's bus simulation, 4 more, 103; claude-link's `test_term.py`, `test_resident_background`):
  - a quiet bridge's model: GF_BG offered and HF_BG taken; a call on its way as the user goes back, taken on the way out and answered at the first look; idle looks every ~220 ms, a serial poll each, with nothing sent to the Pi;
  - over EMSUSE, away: list, a 22 KB read, a 23 KB write read back, a disk error failing the call without a prompt, a GPIB scan and query; a SCREEN answered by the console in a pass (CLAUDE 1.11: the text page byte for byte; F6h before); `grid_type` refused and the working tools named; EMSUSE's screen, BIOS video data and mode untouched through every pass with work; no SRQ from the bridge (the latch, cleared at the start, and the interrupt count as they were, and the console never waited for one); never AH=0Bh; the stub's stack; a call given up on withdrawn and never run; the Pi sending nothing but REQUESTs and NOPs while Claude Code's screen changed; the next pop-up's band with the number of requests run and what Claude Code wrote meanwhile, the bridge loud again; EMSUSE's keys typed meanwhile and its EMS windows whole;
  - at the prompt (the kernel's key wait), files; over CRITKEY's INT 24h handler, F7h and GPIB working; CLAUDE /T turning the looks off and the bridge loud, and no looks while it runs even with them left on (as a CLAUDE.COM before 1.10 would);
  - over TM5000G (no key pressed): files and a query at its key looks, its screen, SRQ flag, REN and chip as it left them; a query during its auto-detect answered before it was done, and auto-detect finding all three;
  - with `MULTITASK=1`: files over the front task's EMSUSE; F7h over COPY CON (MT's key wait), GPIB working; a link failure in a pass (the Pi answering nothing): no more looks, the Pi told by the SDC, the call ended at once and the tools saying so; the bridge gone while away: the looks stop after one serial poll, the program goes on.
- **Controls**, each failing a check: the bridge not made quiet at EVENT 04h; CELLS sent while away; no withdrawal (LATE.TXT written after its call failed); the bridge not made loud at HELLO; requests on the way out dropped; `dos_ok` not settled again in the pass (CRITKEY); no PIT polls after the EVENT (`srq_held`); no looks at peeks (TM5000G); CLAUDE.COM leaving the looks on; the stub looking while one runs (`r_off`); the Pi not taking the SDC as the console's stop; the band's count not kept; the firmware raising SRQ despite quiet (the bus simulation). A separate switch to PIT polls inside the pass was taken out when its control passed: the session has made it already.
- **Review** (three reviewers: the assembly, gridlink and the firmware, the tests and docs; then the fixes re-reviewed). The re-review found the wider gate could wait out every look on a REQUEST the Pi gave up (now a NOP ends it), stops the Pi didn't hear of (now an SDC after a failed serial poll; a busy driver just waits), the emulator's bridge reporting a DCL as an SDC, and the reason gridlink gave for the stop. Fixed first: a REPLY stranded by the 5-s cap (the next look didn't take it up, as the Pi had nothing to ring for); an answer due across passes failing the link at its 2 s; the console stopping without the Pi knowing (now the SDC tells it); the firmware's quiet read once per request loop (a moment's SRQ possible after a CONFIG: now read in `set_srq`); quiet not checked at EVENT 04h; a call ended by a HELLO still run; a CLAUDE.COM before 1.10 leaving the looks on after it; the caller's DF changed; a request on the way out to TYPE's keys counted; and tests that proved less than they said (a ring check that couldn't fail, the band's count, the idle serial polls, the SRQ latch's baseline, the query during auto-detect).
- **Not covered:**
  - a floppy access or a `scan` holds the program for as long as it takes;
  - each look addresses the bridge (a serial poll: UNL, MTA, SPE... UNT): a program that drives the 7210 itself, or keeps devices addressed across its driver calls, and peeks the keyboard mid-transfer, would have its transfer broken; programs that go through INT 60h address for each call;
  - a program's interrupt handler that writes into its EMS windows during a pass writes into the console's pages (the pop-up has the same exposure, but a pass comes without the user asking);
  - one failed serial poll stops the looks until the next pop-up (trying again would mean the driver's recovery, IFC, on the program's bus each time);
  - gridlink restarted in the middle of a pass (at most 5 s): its new link answers the pass's POLLs as a fresh one, loud;
  - an SDC that comes while gridlink's serve thread is still behind the EVENT 04h it follows (the console's 3-s way out run out just after it) is taken as before the background, so its calls wait their time out;
  - not tested on their own: the in-service and front-task checks for the looks (the pop-up's), the mouse handler swapped in a pass, no looks while TYPE's keys play, a request kept from the pop-down meeting DOS busy;
  - on the 1520: the quiet firmware is to be flashed, and the looks' cost there measured.

## The program's screen in the background (CLAUDE 1.11, 2026-10-24)
Back in the program, Claude can now also read its screen: `grid_program` works in the background, so Claude can follow what TM5000G shows (a reading, a trace) while the user works. `grid_type` still needs the console up.
- **On the GRiD:** SCREEN in a background pass, or kept from the way out, is `op_bgscreen`: it copies the screen as it is then (the 32 KB at B800h) and the BIOS's video data (40:49h-66h) to where a pop-up keeps them (windows 1-2 and `bios`), then answers through `screen_msg`, as at a pop-up: the same format, the same modes (mode 7 F5h), the reply's first bytes in front of the copy. Nothing is drawn and the program's video memory is only read; the next pop-up keeps its own copy. It needs no DOS, so it runs where files can't (F7h). It counts in the band's number.
- **HELLO** says `ops=files,gpib,bgscreen` and `grid=CLAUDE 1.11`. gridlink lets `grid_program` through while away only for a console that says `bgscreen` (`Term.bg_tools`), keeps a SCREEN call going at EVENT 04h for one, and words the tool's answer for a running program: the name is the one from the last pop-up, as another program may run by then.
- **Cost:** RCON.BIN 8,760 bytes (+70), CLAUDE.COM 23,756 (+70); the stub doesn't change. A read holds the program while the copy and the reply go: a text page is about 4 KB, a graphics screen 16 or 32 KB over the link.
- **Tests** (`t_bg_screen`, 7 checks; in `t_bg` the SCREEN now the text page byte for byte, and `grid_program` over CRITKEY's INT 24h handler, where files are F7h; `test_term.py`): over TESTKEY, away, what the user typed after the console went is on the screen Claude reads (a background pass, the console never up), TESTKEY's video memory untouched; `grid_type` refused, with `grid_program` among the tools that work; GFXUSE started after the console went (mode 6, no pop-up over it, so the mode and BIOS data are read then): the image, named as the last pop-up's program with the caveat, and SCREEN's 16 KB byte for byte, GFXUSE's own check afterwards (0 bad); gridlink lets `grid_program` through only with `bgscreen`, and keeps a SCREEN call at EVENT 04h only for such a console. **Controls:** the screen answered from the pop-up's copy, not the live one (TESTKEY's "abc" missing); SCREEN not answered in the background (F6h).
- **Review** (three reviewers, then the fixes re-reviewed). Fixed: a background SCREEN's reply cut short (a link failure) left its 12 borrowed bytes to be put back over the next pop-up's fresh copy of the screen, a stripe on the program's screen afterwards (rc_main now puts them back on the old copy first); `grid_program`'s answer worded before the read; stale text; and tests that proved less than they said (the BIOS data's copy, SCREEN where files are F7h, gridlink's keep at EVENT 04h).
- **Not covered:** a SCREEN kept from the way out isn't tested on its own (the files' path, which is); the program's name in the answer is the last pop-up's; the borrowed bytes put back at a pop-up after a reply cut short (it needs a link failure in the middle of a reply from a text page other than 0).

## The mascot's glyphs (CLAUDE 1.12, 2026-10-25)
The console now draws Claude Code's mascot as CLAUDE.COM does. Before, it had no glyphs for the 2x2 block elements (`▘▝▖▗▌▐▀▄▛▜▙▟▚▞`), so the Pi sent it blanks and inverse blanks, and the mascot lost its eyes.
- **On the GRiD:** RCON.ASM defines `QUAD_GLYPHS` and `GLYPH_END` 0AFh as CLAUDE.ASM does, so GLYPHS.INC gives it the same codes A1h-AEh, and its HELLO says GF_QUAD (flags bit 4) and `grid=CLAUDE 1.12`.
- **gridlink:** `Term` maps the block elements for any GRiD whose HELLO says GF_QUAD; it no longer leaves out resident Claude's console. Either side alone changes nothing: an older console doesn't say GF_QUAD, and an older gridlink still sends this console blanks.
- **Cost:** RCON.BIN 8,984 bytes (+224, 14 glyphs of 16 bytes), CLAUDE.COM 23,980 (+224). The console's EMS page has 1,842 bytes left before its last 12 bytes, a reply's first ones (2,066 before). The stub doesn't change.
- **Tests** (`t_popup`, 1 check more; `test_term.py`'s `test_resident_quads`): the mascot and a row of all 14 block elements fed to the Pi's screen come to the console as codes A1h-AEh, the full blocks as inverse blanks, in step with pyte, and drawn byte for byte with the console's glyphs, which are CLAUDE.COM's own; on the Pi, a console's HELLO with GF_QUAD turns the block elements on, an older console's leaves them off. **Mutations**, all caught: gridlink leaving the console out again (both tests); the HELLO without GF_QUAD; RCON without `GLYPH_END` (drawn as '?'); RCON without the glyphs.
- **Review** (three reviewers, GRiD, Pi, tests and docs; then the fixes re-reviewed): nothing blocking. Added from it: all 14 codes and the full blocks' inverse checked, the console's glyphs compared with CLAUDE.COM's, the Pi-side test, and PROTOCOL.md's glyph ranges, stale since 1.8.
- **Not covered:** untried on the 1520; an older gridlink with the new console isn't run (it leaves the console out, as before: term.py's old `not s.resident()`).

## The link's 2 s after a NAK (T5c, 2026-10-25)
A link whose answers came empty, or damaged, every time never failed.
- **What happened:** in a background pass (M4), with the Pi not answering but ringing (a call queued), the bridge's status said 40h without 20h; the console read anyway, the driver's read waited out its 2 s and came back empty, and the console NAKed it as a damaged frame. With `LINK_CHAIN` the NAK went at once, before the pass read the time again, so it set `t_sent` to a `now` from before that read: `link_wait`'s ~2 s (more than 40 ticks) never ran out while each read lasted 40 ticks or less (about 38 on the 1520: the driver's 37, from 2000 ms, and its spin). The pass ran out of time instead, the next began, there was no SDC and the call never ended. CLAUDE.COM's own link had the same flaw, whenever the status said 40h with nothing to read, or every answer came damaged (each NAK a fresh 2 s).
- **Now:** a NAK leaves `t_sent` alone (TERMLINK.INC, so CLAUDE.COM and the console; with CLAUDE 1.12): the ~2 s run from the frame the answer is for, and only good answers keep the link up. A damaged answer is still NAKed and the Pi sends it again within those 2 s; one that comes late and damaged has less time than before.
- **Cost:** CLAUDE.COM 24,006 bytes (+26), RCON.BIN 8,994 (+10); the console's EMS page has 1,832 bytes left (1,842 before).
- **Tests:** `t_bg_mt` under `irq_exact` (the call ended in the same pass); claude-link's `test_damaged_answers_fail_the_link` (every answer damaged: the link fails in under 5 s, then goes on; the old code NAKed 999 times in 6 s); the whole of test_resident_term, test_claude_kernel and claude-link's emulator tests with the new CLAUDE.COM. Details in docs/lodestone-multitasking.md, T5c.
- **Not covered:** on the 1520.

## The 2026-10-26 audit, step 5 (2026-10-28)
The audit's rows for CLAUDE.COM, the stub and RCON (R44, R45's free parts, R47, R49, R50, R51, R53, R55, O12-O14), two older bugs the review found, and the link's hot code on even offsets.
- **The stub:** 61 paragraphs (63 before): 992 bytes with its MCB, every one of its 976 used. INT 16h's AH test is two TESTs (R44); one `r_tell` writes MT's byte (R45); the pop-up saves the program's windows and maps ours in one loop. `r_look` (merging r_hot/r_bg/r_feed's calls) was left out: a call on every INT 16h for a paragraph.
- **CODE-\ under a program that polls (an older bug):** the BIOS's AH=01h drops CODE keys, so a CODE-\ typed while a program polled with AH=01h was often lost (2-3 of 8 timings). Now, without MT, the stub first looks with AH=11h, which drops nothing, and its own read loop does the same; with MT, CLAUDE /R patches the stub to pass a program's peeks on as before, and MT's `mt_drop` keeps CODE-\ (as 2B00h) for the stub, also through a TSR's INT 16h hook loaded after /R. It costs an AH=01h peek with nothing waiting about 60 clocks without MT; under MT a polling program's peeks give the other tasks their turns as before. A task started before CLAUDE /R (no stub in its chain) now gets CODE-\ as Alt-\ (2B00h) instead of losing it. Left: without MT, a CODE-\ typed right behind a key AH=01h won't give (F11, F12, another CODE key) within one peek; under MT, a call MT passes on as it is (inside another passed-on call, INT 13h, the INT 24h prompt).
- **RUN (an older bug):** without capture, any existing file named with a dot was EXECuted, so SETUP.BAT or README.TXT ran as a .COM image. Only NAME.COM and NAME.EXE are EXECuted now; the rest goes through COMSPEC /C (claude-link/PROTOCOL.md). `exists` uses GET ATTRIBUTES (O13).
- **RCON:** one `keep_screen` (which gives the borrowed bytes back before it copies the screen: a background SCREEN after a lost reply could send 12 stale bytes) and `dos_probe` (R50); the no-DOS ops first in its table (R53); OPS.INC's shared GPIB tails, `op_path` and `find_first` in both binaries (R51); the driver's check mode set once at HELLO, and again whenever RCON finds the driver (R55; the wire is unchanged).
- **Hot code:** pads keep the link's hot labels on even offsets in TERMLINK (both binaries), RCON and CLAUDE.COM, with `EVEN` lists that stop the build if one goes odd; the stub's are even by its layout. Taken entries landing odd: CLAUDE.COM about 35 % → 17-21 %, the stub 38 % → 14-18 %, TERMLINK about 58 % → 19-34 %, RCON 50-60 % → 27-41 %.
- **Cost:** CLAUDE.COM 25,620 bytes (25,884 before), CLAUDE's memory while it runs a program 144 bytes less; RCON.BIN 8,882 (9,000), the console's page has 1,949 bytes left; LODEMT.SYS 20,249 (+62, MT's CODE-\ keep).
- **Tests:** test_resident `t_rpoll`, `t_rother`, `t_rload` (61 paragraphs); test_mt `t_rpoll` (CODE-\ under a polling program with and without a TSR's hook, a task behind it at least 0.15 of its speed, CODE-Tab within 100 ms); test_resident_term `t_bg_hot`, `t_bg_ksum`, `t_ops_codes`, the borrowed bytes in `t_popup` and `t_bg_screen`; test_claude_kernel's RUN, ops and NAK tests.
- **Not covered:** on the 1520.
