# CRASHLOG: catching a crash that restarts the 1520

A diagnostic build of Lodestone for a crash that restarts the machine (with the POST's beep) instead of hanging. Found 2026-11-04, with multitasking on:
- dropping a mouse resize of CLAUDE.COM's window (CODE-A);
- with a CODE-P window open, opening a picture from the Executive with a click;
- with a CODE-P window resized, closing a picture opened with the keyboard.

None of them happens in pcemu, so this build records what the machine did just before, and keeps that through the restart.

## What it does

- **A flight recorder.** MT keeps its last 256 events in a ring:
  - every tick: where it interrupted, and that stack;
  - every task switch, and who asked for it;
  - KMW's window operations: open, close, raise, drop, resize and its drop, redraw;
  - the front task's mode sets;
  - an INT 06h (an invalid opcode).
- **A catch for the restart.** At start-up it puts its handler at 40:67h and shutdown code 0Ah in CMOS 0Fh. At any reset after power-on, the 1520's BIOS then jumps straight there, with memory as it was and no POST (`reset.asm`, `SD_JMP_WITHOUT_INT`). That covers a CPU shutdown (the stack pointer at 1, or a fault inside a fault), the keyboard controller's reset, and a jump to FFFF:0 or F000:E05B. Ctrl-Alt-Del and Lodestone's own restarts set 40:72h to 1234h, and those go on as ever.
- **The report.** Once caught, it copies a report to 5000:0:
  - MT's state and the task table;
  - the ring;
  - the vectors and the BIOS data;
  - the kernel's stack, the newest record's stack, and each task's stack as last switched from.

  It then shows the last records on the screen, in text mode. A key restarts. That restart is a soft one, so the report stays in memory: the BIOS clears only the first 64 KB.

The normal build has none of this: built without `-dCRASHLOG`, LODE.SYS and LODEMT.SYS are byte for byte the same.

## On the 1520

1. **Make a boot floppy with this build.** Copy `LODE.SYS`, `LODEMT.SYS`, `CRASHRPT.COM` and `CRASHME.COM` from this directory onto it, in place of the normal LODE.SYS and LODEMT.SYS. Its `LODE.INI` needs `MULTITASK=1`. Boot from the floppy, not the ROM: the ROM's LODE.SYS is the normal one, and LODEMT.SYS has to match it.
2. **Check it works on the machine first.** Right after the start-up, `CRASHRPT` should print a "Last session: …" line (no line at all: this isn't the CRASHLOG build running, or multitasking is off). Then `CRASHME R` at the prompt jumps to the BIOS's reset, as a wild jump would: the report screen should come up; a key restarts, and `CRASHRPT` writes CRASH.BIN. If the screen doesn't come up, the catch doesn't work on this machine, and that is the first thing to fix. `CRASHME S` makes a CPU shutdown (a push with SP = 1) and `CRASHME K` the keyboard controller's reset: whether each is caught tells what kind of reset the real crash is (2026-11-04: R caught on Joshua's 1520, the real crashes not).
3. **Make it crash** the way it did before.
4. **The report screen should come up instead of the POST.** Take a photo of it, then press a key.
5. **After the start-up,** run `CRASHRPT` before anything big. It writes `CRASH.BIN` (9,856 bytes) to the current directory. Send that in.

If the POST runs instead (the beep and the memory count), that tells us something too:
- the reset wasn't one the BIOS takes through CMOS: power, or a cold reset;
- or MT's block was overwritten before the reset;
- or something reset the shutdown code first: a program using INT 15h AH=87h, the BIOS's extended-memory copy, which Lodestone itself doesn't use.

This build is from the M12 branch, so it also has the hard-disk waits.

## Breadcrumbs (when nothing was caught)

CMOS 3Dh survives any restart, a full POST too. Its high nibble is the stage: 1 armed, 2 in the catch, 3 the report kept, 4 on the screen, 5 (P) a restart asked for. Its low nibble is the last window operation (its tag's place in `cr_wtags`, KCRASH.INC). Each window operation also arms the catch again. At the next start-up the CRASHLOG build turns the two back into characters at 4FF0:0, and `CRASHRPT` says what they mean first:
- **1:** the restart never reached the catch: a reset the BIOS didn't send through CMOS 0Fh, or the power.
- **2:** the catch was entered but died before the report was kept, so MT's memory was probably overwritten.
- **3 or 4:** a report should be there.

**The owner's stack check (stage 8).** Each time a task gives a disk wait away (a floppy's 9001h, the hard disk's 9000h), the build keeps the top of its stack: the kernel stack's slice up to kstack_top, or 128 bytes of its own stack. That holds the BIOS's own return addresses, since the wait is inside its INT 13h. On the task's return it compares. If anything changed, it goes to the report at once (cause K, stage 8), before the BIOS could return through a broken frame and run into POST. The report keeps both copies, and crashdecode prints the words that differ. Joshua's bisect (2026-11-04) put the crash on task 0 giving a disk wait away; this is the first suspect.

Run `CRASHRPT` after every unexpected restart, and send its first lines even when it says there is no report.

**Not CMOS 3Ch.** The first breadcrumb build put the window tag in 3Ch, which the labelled BIOS source (gridcase-bios, `cmos.inc`) marks unused. Joshua's 10/25/89 ROM uses it: F000:F104 adds CMOS 34h–3Bh (the boot password) and 3Fh & FEh and compares the sum with 3Ch, and POST (F000:8D20 → F1B6) asks for the password when they match and 3Fh bit 1 is set. His 3Fh is 02h. A tag that happened to equal the sum would have locked the machine at the next POST, until CMOS was cleared. Nothing in that ROM reads or writes 3Dh. Keep Lodestone's CMOS writes to 3Dh (and 0Fh, the shutdown code).

**Not CMOS 0Ah either.** 2e3c789 and the build before it re-armed the catch at each window operation with `mov ax, 0F0Ah` into `cr_cm`, which takes the register in AL: it wrote 0Fh to status A (0Ah), the clock's divider, and stopped the time-of-day clock. The 1520's next POST said "Time-of-day clock stopped". Setting the time or the date (INT 1Ah 03h/05h, as TIME and DATE do) has the BIOS write 26h there again. test_mt now fails on any write to 00h–0Dh.

The first boot of this build may report a stage left over from before, since 3Dh's old contents weren't written by it.

## Reading the report

```
python3 os/diag/crashdecode.py CRASH.BIN os/diag/LODE.MAP
```

It prints:
- MT's state and the tasks;
- the ring, oldest first, with each address named from the map (kernel, MT, UI, BIOS, or a program's);
- the vectors that point somewhere other than the BIOS, the kernel, MT or the UI;
- the stacks, with the words that look like return addresses.

The map has to be this build's own, the one next to the LODE.SYS that crashed.

## Building it

```
sh os/diag/build.sh
```

It writes LODE.SYS, LODEMT.SYS, LODE.MAP and CRASHRPT.COM here. os/src's own build is left alone. test_mt's `t_crashlog` builds it too, and checks it in pcemu: a jump to the reset caught, the report through the restart, CRASH.BIN decoded, an INT 06h, and a restart asked for not caught. pcemu models the BIOS's jump through 40:67h for shutdown codes 05h and 0Ah, and the PC's fixed BIOS entry points.

## Costs in this build

LODEMT.SYS is 23,093 bytes, against 21,525 normally. MT's block is about 14.5 KB bigger: the ring is 4 KB, the report's copy 9.6 KB and its stack 0.5 KB. Every tick and switch costs a record, and the hot labels' parity isn't kept. So it runs a little slower, and memory is laid out a little differently. A crash that depends on exact timing or placement might move, or go away.
