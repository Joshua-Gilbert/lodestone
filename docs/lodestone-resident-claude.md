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
    1. `/R` takes the largest free block and cuts it to its size less the stub's 47 paragraphs and an MCB. The kernel leaves the rest, at that block's top, as a free block of exactly the stub's size.
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
  - Acting on it is M3's (file requests while a program is paused).
- **The stub's header**, at the same offsets in every CLAUDE.COM from now on: `CLRS` (100h), its version, where its hook is, the INT 16h it goes on to, its EMS handle, and the byte that stops pop-ups (10Dh). `/U` finds the stub among the memory blocks (owner 8, `CLRS` at 100h), so `/R` also knows when it is there already, even under another hook, and both work on a stub that another version of CLAUDE.COM left (copied to the floppy without a restart). M1 at first found it by its hook's offset, which another version's wouldn't share (PR #27's review). `/U` is refused when INT 16h no longer points at the stub's hook; otherwise it puts INT 16h back and frees the EMS pages and the block.
- **Cost:**
  - **Resident:** 768 bytes of conventional memory: 362 of code and data, the 384-byte stack, and the block's MCB (704 before the review's fixes: the header, the in-service check, the no-key answer). DOS programs get 0.8 KB less, at the prompt and from the Executive alike (the plan's target was 1.2 KB). `/U` gives all of it back.
  - **EMS:** 3 pages (48 KB).
  - **CLAUDE.COM:** 16,644 bytes on disk (+4,324). It takes 32 bytes more in memory when it runs as chat or Term (`res_args`).
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
- **On the 1520 (to do):** `os/claude/M1TEST.BAT` runs these step by step and logs the answers to `M1TEST.TXT`. Copy it with CLAUDE.COM, EMSUSE.COM and GFXUSE.COM (`os/claude`), MEMSZ.COM (`os/tests`) and TM5000G.EXE. It was run through in pcemu, answering as its instructions say. It checks:
  - MEMSZ, `CLAUDE /R`, MEMSZ again, and `CLAUDE /R` once more (refused).
  - CODE-\ and back:
    - over EMSUSE (its four EMS pages kept);
    - over GFXUSE in modes 4, 6 (the spike's "looked DIFFERENT" answer, to look at again) and 40h;
    - over COPY CON (the band says DOS busy, and COPY CON goes on);
    - over TM5000G, with its mouse moved while the console is up.
  - Keys typed straight after the console goes away reach the program.
  - `CLAUDE /U`, then MEMSZ as at the start.
  - By hand at the end: CODE-\ over the Executive.

  CODE-\ behind another CODE-key and keys typed just before CODE-\ need timing no one can type; the emulator's tests cover them. Nothing on that floppy looks at the keyboard from an interrupt, so the 1520 can't show the in-service check either (pcemu can't show the hang itself: it lets a nested IRQ 0 in).

## Open points, after M1
- **Loading from LCMD:** settled by the stub's block at the top of memory (M1).
- **Programs that hook INT 16h themselves**, and programs that read the keyboard through INT 09h only (not covered: Phase 2 left INT 09h hooks out). `/U` refuses while one sits above the stub.
- **The mouse during a pop-up:** the INT 33h pointer is hidden meanwhile, and its event handler swapped out unless DOS is busy (M1). The console itself ignores the mouse. If the kernel's INT 33h noted a handler's owner without a DOS call (reading the current PSP itself), AX=0Ch and 14h would be safe from anywhere, and the swap could happen while DOS is busy too.
- **The program's name in the band** needs a DOS call or a kernel hook while DOS may be busy: M3, with HELLO's.
