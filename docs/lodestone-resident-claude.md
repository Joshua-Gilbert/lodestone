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
  - **12h TYPE:** a key script in RUN's format, fed to the program after pop-down. A snapshot mark brings Claude back silently at the next key wait, so it can see what the keys did.
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

- **Mode 6:** one prompt was answered "looked DIFFERENT". Joshua's later note says nothing went weird, so it was most likely a misread; to look at again in M1.
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
1. **M1:** `CLAUDE /R` loads (EMS pages, stub) and unloads (`CLAUDE /U`). CODE-\\ flips to an empty console and back over TM5000G and over the Executive, with no link yet. Memory is measured.
2. **M2:** the Term session in the pop-up; the same `claude` session as `CLAUDE /T`.
3. **M3:** the paused program's SCREEN and TYPE, with silent snapshot returns. Claude can drive TM5000G.
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
