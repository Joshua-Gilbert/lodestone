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
- At the program's key waits, the stub serial-polls the bridge (at most every 200 ms; never AH=0Bh). If the Pi has work, it serves it without drawing anything, for at most about 50 ms at a time, then lets the program go on.
- Background requests are limited to the safe list above (files, GPIB queries). Anything that needs the screen waits for the next pop-up.
- A small indicator on the program's screen is optional; to be decided after 0.5a.

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
4. **M4 (0.5b):** background requests at key waits.

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
  - The stub passes it to the console, which says "DOS busy" in its band when the program was inside DOS (COPY CON at the prompt).
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
    - over COPY CON (the band says DOS busy, and COPY CON goes on);
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
- **Going back** (PR #30's review): when the user goes back to the program with CODE-\ (not when the console goes for TYPE's keys), the console sends EVENT 04h, away, with the last keys. gridlink then ends any call waiting for the GRiD and refuses new ones at once ("the user has gone back…") until the next HELLO. Before, a call made in the 10 s after waited 120 s for an answer, or ended at the next pop-up. A REQUEST that reaches the console on its way out gets no answer, as the EVENT has ended it on the Pi, so the program doesn't wait while a screen goes.
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
- **Files and GPIB while a program is paused** (the plan's READ, DIR, WRITE..., GPIB queries): when DOS is busy under the program they need the kernel's own stack, a kernel change. Then M4 (0.5b), Claude working between keys.
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
- **Never a ring for the program.** gridlink rings only while the console is up: not once the user has gone back (EVENT away), and not while TYPE's keys play (the console is down then without saying so: `Grid.typing`). `Term.may_ring` says so, and `Link.ring_check` takes back any ring it gave meanwhile.
- **The next frame straight after an answer** (`LINK_CHAIN`), as CLAUDE.COM; not while the console is going back, when only what is queued goes.
- **A fourth EMS page.** Term's shadow (3,840 bytes) moves out of the console's page into a page of its own in window 3 (EC00h). The stub maps all four of its pages and, as before, saves and puts back all four of the program's windows. `CLAUDE /R` now asks for 4 free pages (64 KB); the stub is version 4. TERMLINK's CRC reads ES:SI in RCON (ES = CS but for the shadow's CRC in HELLO). The console's page has 3,801 bytes free (it had 4), which files and GPIB in the pop-up can use next.
- **An SRQ line held by another device.** When an instrument of the program's holds SRQ (asking for service), the bridge's SRQ makes no edge and no interrupt, so each answer would wait for the next tick (~55 ms, against 2-4 ms polled). An answer found at a tick's look with no interrupt for it sets `srq_held`: from then on, until the next HELLO, the link polls by the PIT and doesn't sleep for an SRQ. This is in TERMLINK, so CLAUDE.COM does it too.
- **A TYPE given up on.** If the Pi's call times out while the program isn't yet back at a key call (a busy program, or keys it never reads), `Grid.type_out` keeps the rings off until the console is heard from (TYPE's reply comes first) or says HELLO.
- **Cost:** RCON.BIN 6,868 bytes (+386), CLAUDE.COM 21,756 (+434, with CLAUDE 1.8); EMS 64 KB (+16 KB). Conventional memory is unchanged: the stub is still 816 bytes with its MCB, as `r_hw`'s fourth byte fits in its paragraphs.
- **Not changed:**
  - While the console is up, the program's SRQ latch still gets the bridge's SRQs. The driver ORs every SRQ it sees into the latch: from the interrupt, and from its polled reads of ISR2 before 1.21 too. So TM5000G may see one SRQ after a pop-up and serial-poll its instruments for nothing. Taking those out would need a driver call to put the latch back.
  - A TYPE's own REQUEST isn't rung for: the rings are off from the moment it is queued, so the console fetches it at its next idle POLL (up to a second).
  - A ring that comes just after the idle console's last look can wait a tick.
  - `srq_held` can still latch when two SRQ edges merge into one interrupt (as the PIC's request register does if the first isn't serviced in time; seen in the emulator after seconds of back-to-back polling). The link then polls by the PIT until the next HELLO, as it did before this change.
- **Tests** (`test_resident_term.py`, `t_driver`, 23 checks, on the Pico bridge's model, which can ring):
  - every frame from the Pi passed by the driver's sum, and every frame of the console's was good at the Pi;
  - the count was found, GF_WAKE offered and taken up by gridlink;
  - one serial poll an answer, and the PIT never asked;
  - the console asleep while answers are due;
  - a title from the Pi rings a quiet console;
  - no ring, and no SRQ held by the bridge, while TYPE's keys wait, after a TYPE given up on (until the console is back), or once the user has gone back;
  - a second session in the same boot takes its answers at their SRQ as the first did;
  - never AH=0Bh;
  - with `GPIBIRQ=0`: no count, no GF_WAKE, polled by the PIT, never asleep while an answer is due, the title at the next idle POLL, no ring;
  - in a boot of its own, the SRQ line held: the console finds that out, polls by the PIT and never sleeps for an SRQ again.
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
