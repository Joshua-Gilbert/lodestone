# Lodestone 0.6: the ROM

Lodestone now boots from an EPROM in the 1520's application-ROM socket, as GRiD MS-DOS 3.30 did. Floppy boot still works the same as before. **First booted from ROM on the 1520 on 2026-10-18**, burned from `LODE1_EPROM.BIN`.

## What's in ROM 1

`os/build.sh` builds two 131,072-byte files:
- `os/LODE1_EPROM.BIN` is the one to burn, to a TMS27C010A (or any 27C010 / 128K × 8), with Xgpro set to that part and the address range on ALL.
- `os/LODE1.BIN` is the same image as the BIOS sees it, which the emulators and tests use.

**The 1520 inverts A16 to its ROM sockets,** so the chip's two 64 KB halves are swapped in the BIOS's window. GRiD's EPROM, read in a programmer, has its trailer at FF00h, not at the end. `LODE1_EPROM.BIN` is `LODE1.BIN` with its halves swapped (`mkrom.py` writes both). Both have the same Xgpro checksum (the sum of their bytes), so check the bytes instead: 10000h starts `EB 3C 90` and then `LODE ROM`. The first burn of `LODE1.BIN` itself gave the BIOS's "Disk Boot Error": with the halves swapped, it found no trailer and no ROM.

| File | What it is |
|---|---|
| LODE.SYS | the kernel, Executive and UI core (first, contiguous) |
| LODEMT.SYS | multitasking's resident part, read only with `MULTITASK=1` (`docs/lodestone-multitasking.md`) |
| LODE.PIC | the start-up picture |
| LCMD.COM | the command prompt (COMSPEC) |
| SYSTEM.RUN, WRITE.RUN, CALC.RUN, TASKS.RUN | the programs |
| TERM.RUN | the terminal window (with `MULTITASK=1`: a text program in a window; its font, TERM.FNT, is on ROM 2) |
| CALC.COM | the calculator at the prompt |
| LODE.INI | the ROM's own settings (also the built-in defaults) |

2,048 bytes (4 sectors) are left (512 before 2026-11-05, when TERMINUS.FNT went to ROM 2 with GRIDFONT.FNT: Lodefont, built into LODE.SYS, is the font now; 1,024 before a program's modes on the Executive's right-click menu, 2026-11-04; 1,536 before the Executive's right-click menu's LODE.SYS, 2026-11-04; 2,048 before M12's LODE.SYS, 2026-11-04; 3,584 before 2026-11-03: M10's LODE.SYS and LCMD's pipes in %TEMP% took three): DEFRAG.COM has moved to ROM 2 (below), so that multitasking's terminal windows have room in ROM 1 (20 sectors then; their kernel core, T1, took one, the window, T2, four: TERM.RUN and LODEMT.SYS's growth, graphics, T3, one: TERM.RUN's notes, select and paste, T4, three: TERM.RUN two, LODEMT.SYS one, regions that grow, T5a, one: LODEMT.SYS, a screen a program publishes, T5b, two: LODEMT.SYS one, TERM.RUN one, a program woken by SRQ, T5c, one: LODEMT.SYS, CLAUDE.COM in a window, T5d, one: TERM.RUN, and the 2026-10-26 audit's bug fixes, one: LODEMT.SYS; its MT space batch gave two back). Paint (PAINT.RUN) and CLAUDE.COM are on ROM 2 (below).

## ROM 2

`os/build.sh` also builds **`os/LODE2.BIN`** and **`os/LODE2_EPROM.BIN`** (burn the latter): a data ROM (`mkrom.py --data`: system type 2, not bootable, id `LJ`), burned as the second half of R: (below). It holds **DEFRAG.COM**, **TERM.FNT** (the terminal window's font: without ROM 2 a text program, and CODE-P's prompt, starts full screen as a task in front, as without windows), **PAINT.RUN** (Paint and the BMP viewer: from the ROM, Return on a `.BMP` finds it on R: through PATH; without ROM 2 it says "PAINT.RUN is not on this disk") **CLAUDE.COM** (Claude for GRiD, resident Claude's console inside it: CODE-A and `CLAUDE` at the prompt find it on R: through PATH, a newer copy in C:\LODE first) and the two font files, **GRIDFONT.FNT** (GRiD's TC8X16) and **TERMINUS.FNT** (System's Display lists and switches to them on R:; without ROM 2 there is only Lodefont, built in), and the disk utilities, **FORMAT.COM**, **CHKDSK.COM**, **FDISK.COM**, **SYS.COM** and **LABEL.COM**, the file tools **ATTRIB.COM**, **XCOPY.COM** and **TREE.COM**, and the filters **FIND.COM**, **MORE.COM**, **SORT.COM** and **COMP.COM** (from the ROM, PATH finds them on R:), now, with 38,400 bytes (75 sectors) left (46,080 before ATTRIB, XCOPY and TREE; 51,712 before SYS and LABEL; 55,808 before the filters; 60,416 before FDISK; 76,800 before the disk utilities; 79,872 before the fonts; 80,384 before CLAUDE 1.17's modes) (test_rom's `t_rom2_free` checks this figure, and ROM 1's above, against the build); what doesn't fit in ROM 1 goes there. ROM 2 takes CLAUDE.COM as committed (`os/claude/CLAUDE.COM`): run `os/claude/build.sh` before `os/build.sh` after a change to it (t_rom2 fails on a stale copy).

- **R: is both ROMs' files** (`KROM.INC`), whichever socket each is in:
  - with ROM 2 in, R: is one volume of the two: its FAT two sectors (ROM 1's, then ROM 2's), its root 64 entries (ROM 1's 32, then ROM 2's), then ROM 1's clusters 2-253, a gap (254-341, marked bad, on neither ROM) and ROM 2's as 342-593 (ROM 2's cluster n is R:'s n + 340);
  - **ROM 2 is burned as that second half** (since the 2026-10-26 audit's O10): its FAT sector is R:'s second, entries from 341 on (so that none of its own is in ROM 1's sector), and its root holds its own entries, numbered as R:'s, without a label. ROM 1's FAT marks the gap bad up to its sector's end. So R:'s sectors are plain copies from the two ROMs. Only ROM 1's root is changed as it is read: its empty entries read as deleted ones, so that a search goes on to ROM 2's. ROM 1 itself keeps them empty, so a search of ROM 1 alone still stops at its end. (Before O10 the read routine made each FAT and root sector up from two volumes that stood alone: 224 bytes more were kept, and every FAT read went through each entry);
  - either ROM works alone: ROM 1 alone is R: as before. ROM 2 alone (a floppy start) is R: by itself: the same volume with ROM 1's half missing, its FAT sector 1 ROM 2's spare (sector 254, all bad), its root ROM 2's 32 entries alone;
  - so ROM 2 can be changed and burned without ROM 1, and the other way round, as long as both are in this layout. A ROM 2 burned before O10 (id `L2`) isn't joined: R: is then ROM 1 alone. ROM 2 is no FAT volume by itself any more: `mkrom.joined()` writes R: as an image that mtools reads.
- **DEFRAG.COM on R:** the screen saver's round of the disks looks for it in the root of the start-up drive, so from the ROM it finds it there with ROM 2 in, as before (without ROM 2: no round, only the dark clock). From a floppy, DEFRAG.COM is on A: as before.
- **Cost:** R:'s module is 29 paragraphs with ROM 1 alone (27 before ROM 2's support; 32 until the start-up patched `r_dio`'s call of `.map` out, audit O9) and 39 with ROM 2 (160 bytes more; 50 before O10): what joins them, `.map` with it, and R:'s answer to INT 21h 36h, are kept only when ROM 2 is there. ROM 2 alone keeps them too.
- **INT 21h 36h (free space) for R:**, with ROM 2 in, is answered without walking R:'s FAT: nothing free, and the clusters the ROMs really have, the gap left out: 504 with both ROMs (252 KB), 252 with ROM 2 alone. (Walked, the gap's 88 entries would count as in use, and cost a DIR R: the time to step through them.) ROM 1 alone is walked as before: 252 clusters.
- **Speed (O10, instructions counted in pcemu):**
  - with ROM 2, reads of R:'s FAT and root are much cheaper. `type r:\f17.txt` with nothing cached takes 45% fewer instructions, a missed command 29% fewer, and COPY of a 60 KB file from ROM 2 22% fewer;
  - ROM 1 alone is unchanged;
  - DIR R: takes 4.3% fewer than before O10 with ROM 2 in, and 3.7% fewer with ROM 2 alone (INT 21h 36h answered, above);
  - one path is slower: ROM 2 alone, which now maps its sectors as the joined volume does, takes 1.2% more for a COPY from R:, 4% more for a TYPE with nothing cached;
  - with ROM 2 in, INT 21h 36h for any other drive goes through R:'s check first: a few instructions, against the hundreds of FAT entries it walks.

### Re-burning for O10

O10 changed both ROMs' layout. Burn both from one build of this tree (`os/build.sh`):
- ROM 1: `os/LODE1_EPROM.BIN` (its FAT now marks R:'s gap bad);
- ROM 2: `os/LODE2_EPROM.BIN` (R:'s second half, id `LJ`).

A mix of old and new is safe:
- the new ROM 1 doesn't join a ROM 2 burned before (id `L2`). R: is then ROM 1 alone: no DEFRAG.COM round, and no TERM.FNT, so text programs start full screen;
- an old ROM 1 started from its own kernel, or an older kernel started from a floppy, doesn't join the new ROM 2 (`LJ`): R: is ROM 1 alone again;
- an old ROM 1 (0.6's, id `LO`) beside the new ROM 2, with this kernel started from a floppy, **does** join them. The old ROM 1's FAT leaves the gap's entries free, not bad, but nothing uses them: R: answers INT 21h 36h for itself (nothing free of 504), and a write to R: is refused. t_rom2 runs this with 0.6's layout (the current ROM 1 with its FAT zero past entry 253, as pre-O10 mkrom left it): DIR R: shows 17 files and 0 bytes free, both ROMs' files read as built, and a COPY to R: is refused. Burn both all the same.

## Which socket

**The 1520's BIOS boots the last bootable image it finds.** Its `GridBootRom` (bootrom.asm) counts the images down from the highest. Run against the real BIOS in `tools/simgrid.py`:

- Lodestone alone, in either socket: Lodestone boots.
- MS-DOS in the first socket, Lodestone in the second: Lodestone boots.
- Lodestone in the first socket, MS-DOS in the second: MS-DOS boots.

So Lodestone goes in the second socket, where the GRiD MS-DOS EPROM has been. That EPROM can sit in the first socket, and the boot menu starts it from there. A data ROM (ROM 2, system type 2) is never booted, so it can go in the first socket. (The older note in `gridos-kernel-hardware-spec.md`, that the first socket is scanned first, was wrong.)

## The image format

`tools/mkrom.py` builds a FAT12 volume in GRiD's own ROM format, as on GRiD's EPROM (part 300909-00):

- **Sectors:** 512-byte sectors, 256 of them; one FAT; a 32-entry root at sectors 2-3; one-sector clusters from sector 4.
- **Files:** contiguous, in order, all marked read-only. The kernel is first.
- **Nothing free:** every cluster no file uses is marked bad (FF7h), so DIR says 0 bytes free. That includes the last one, which holds the trailer.
- **The trailer** ([GridEprom D-3]) is in the last 256 bytes:
  - BB66h, system type 1, bootable 80h, boot segment 0;
  - 128 KB at 3 wait states;
  - the directory and data selectors;
  - ROM id `LO`.
  - ROM 2 is system type 2, id `LJ` (`mkrom.py --data`). Its FAT and root are R:'s second halves (above), and its sector 254 is R:'s first FAT sector when there is no ROM 1. Its BPB is ROM 1's, kept only as the signature R: checks.
- **The boot sector is `ROMBOOT.ASM`.** The BIOS copies the whole image to 8000:0000 and jumps there with DL = 'r'. ROMBOOT finds LODE.SYS in the root and copies it to 1000:0000. It starts it as the floppy boot sector does, with DS:SI pointing at its BPB and DL = 17 (R:).

## R:, the ROM drive

R: is drive 17. It is read-only, and there whether Lodestone started from the ROM or from a floppy (`KROM.INC`).

- **No copy of the ROM is kept: R:'s sector routine maps it in on demand.** It uses the BIOS's own calls, INT 15h E403/E404, the same ones GRIDPROBE uses on the 1520.
  - The image is mapped into A000-BFFF.
  - Up to 8 sectors (4 KB) are copied with interrupts off: video memory is hidden while the ROM is in, so nothing may draw.
  - Then the ROM is mapped out again.
  - A read whose destination lies under the window (into video memory) goes through the kernel's bounce buffer a sector at a time.
  - No EMS is used.
- **Writes fail** with "write-protected".
- **Resident only when the ROM is there.** The module is placed after whatever modules the start-up kept (EMS's, C:'s) and relocated there, like M:'s. It holds:
  - the BIOS's 5 paragraphs of ROM data;
  - R:'s drive table entry and current directory;
  - hooks into use_drive, drv_present, cwd_of and dio. M: chains after them.
- **INT 21h 0Eh** now counts from one byte (`lastdrv`): 2, then 3 with C:, 13 with M:, 18 with R:. M: no longer hooks it.
- **The Executive** shows R: as "ROM R:" and offers it in Device.

## Booting from the ROM

- **Current drive:** C: when the hard disk is there, else R:.
- **COMSPEC=R:\LCMD.COM.** With C:, **PATH=C:\LODE;R:\** (without it, R:\). The Executive finds `.RUN` programs and CLAUDE.COM by PATH after the current subject. A copy in C:\LODE is used before the ROM's, so an update needs no new ROM.
- **TEMP=M:\\** (2026-11-03). A `TEMP=` line in LODE.INI goes into the environment at start-up, after COMSPEC, PATH and PROMPT (KSPLASH.INC's `te_boot`, boot code: 0 resident bytes). The ROM's LODE.INI says `TEMP=M:\`. CLAUDE.COM puts a captured command's output, CLAUDE.OUT, in %TEMP% (then %TMP%, then the current drive's root), so from the ROM it goes to M:, not the read-only R: (X51).
  - **The ROM's own line counts only without C:** (2026-11-03, Joshua's choice). With the hard disk, C:\ has room and M:'s 256 KB could cut a big pipe short, so CLAUDE.OUT and pipe files stay on C:\ unless C:\LODE.INI has a `TEMP=` line of its own. `ini_read` notes where the changes' text ends (`ini_mid`), so `te_boot` knows a line found past it is the ROM's. The menu's 2 (the ROM's settings alone) with C: there sets none either.
  - **A drive that isn't there sets none.** With EMS, `te_boot` runs at the end of md_boot, once M: is made (or not); without EMS, in sp_boot. INT 21h 47h says whether the value's drive is there. So with M: off (no EMS, `MDISK=0`) there is no TEMP: CLAUDE.OUT goes to the current drive; from R: with no hard disk and no M:, a captured command still fails cleanly with DOS's error, and a pipe with "File creation error".
  - **Other values.** `TEMP=C:\TMP` in C:\LODE.INI puts it elsewhere; an empty `TEMP=` sets none. The value is taken to a blank or the line's end, 64 characters at most (a captured RUN's command line then has 64 fewer of its 126). From a floppy, nothing is set unless its LODE.INI has the line.
  - **CLAUDE.COM and LCMD read TEMP** in Lodestone itself. LCMD's pipe files (`PIPEx1.$$n`, `PIPEx2.$$n`) go in %TEMP%, LCMD's own (a `SET TEMP=` counts), or with none in the current drive's root as before; so a pipe works from R: too, typed or run by Claude. TEMP (or TMP) is read once by the outermost pipe running, for it and every pipe inside it (a CALLed batch file's), so a `SET TEMP=` in the middle moves none of its files. A TEMP naming a directory that isn't there fails a pipe with DOS's error, as MS-DOS 5's would; `M:` alone means M:'s root. With no TEMP, LCMD takes TMP, as CLAUDE.COM does. The ROM's LODE.INI stays in one sector (503 bytes; test_rom checks it). Without a hard disk, a DOS program of yours that honours TEMP writes to M:, RAM lost at power-off.
- **Screen captures** go to C: (A: without it).
- **Fonts** are on the drive started from (R:).

### Settings

- **R:\LODE.INI holds the ROM's own settings.** These are also the built-in defaults.
- **Changes go in C:\LODE.INI** (A:\LODE.INI without the hard disk) and are read over the ROM's file. System writes only what differs from the defaults.
- **How readers find them:** INT 21h 3305h returns DL = the boot drive and DH = the drive whose LODE.INI goes over it (0: none). Every reader reads both files:
  - the start-up's readers (the picture's SPLASH=, M:'s MDISK=) take the first match, with the changes read first (`ini_read`);
  - the UI's (FONT=, SAVER=, TIDY=) take the last line, with the changes read last.
- **From a floppy,** DH is 0 and only the floppy's LODE.INI is read, as before.
- **System's Settings topic** shows where the settings come from and where changes go. Return goes back to the ROM's settings: it deletes the changes' file, after asking.

### The menu

Hold Shift while the 1520 starts (from the ROM):

1. Lodestone
2. Lodestone with the ROM's own settings (the changes aren't read, this time only)
3. GRiD MS-DOS, offered when another bootable image is in a socket. It is started as the BIOS would start it: copied to 8000:0000, its boot sector entered with DL = 'r'.
4. The floppy in A:

The BIOS's own `f` at its boot prompt still boots the floppy as well.

## Memory

Measured in pcemu by `tests/test_rom.py t_memory`: a DOS program's KB.

**Without the ROM, 0.6 costs 0.1 KB against 0.4.5 (562.2 / 578.3 KB, was 562.3 / 578.4).** That is the PATH search in the Executive and the two-file settings reader. With the ROM in, R:'s module added 446 bytes in 0.6 (432 after the 2026-10-20 audit's PR #55; 512 since ROM 2's support, 464 since O9; with ROM 2 in, 800, and 624 since O10).

## Review (2026-10-18)

An independent review found three bugs, all fixed and tested:
- The menu offered any other system-type-1 image as GRiD MS-DOS. GRiD's application ROMs are type 1 too, with no boot sector. It now checks the bootable flag (BB66h, 80h), as the BIOS does.
- ini_read could read the second file past its buffer when the first was 4 KB or more. It now stops when there's no room.
- Started with the ROM's own settings (the menu's 2), saving in System would have replaced the changes file's settings with the ROM's. System now says "not saved this time" instead.

Also from the review:
- Started from the external floppy (B:), captures go to B: again.
- M: turned off while current goes back to R:, not A:.
- A PATH entry too long for the search buffer is cut.
- pcemu now refuses E402-E404 without E401's DS, as the BIOS does.

## Tests

- **`tests/test_rom.py`** covers:
  - the image, read back by mtools;
  - the real BIOS (which socket boots; pcemu's E400-E404 against the BIOS's answers, with `ROMT.COM`);
  - booting from the ROM with and without EMS and C:;
  - R:'s reads, including one into video memory (`ROMVID.COM`), and its refused writes;
  - a floppy start with the ROM in;
  - settings precedence, and no disk in A:;
  - the menu, including chaining to GRiD MS-DOS;
  - System's Settings topic and saving;
  - PATH;
  - memory;
  - ROM 2 (t_rom2, 26 checks): LODE2.BIN a data ROM (id `LJ`), TERM.FNT on it; the two FATs as burned (ROM 1's gap bad to its sector's end, ROM 2's sector R:'s second, its spare sector 254); mtools reading R: as `mkrom.joined()` builds it, with ROM 1 and ROM 2 alone; a test ROM 2 with 20 files (its root past 16 entries, R:'s sector 6) and a 60 KB file; with ROM 1, in either socket (with EMS; with C:), what DOS programs get (0.1-0.2 KB less than ROM 1 alone: 10 paragraphs), DIR R: both ROMs' files (one label, 33 files, 0 bytes free) and DEFRAG.COM, the 60 KB file, ROM 1's last file and ROM 2's 21st entry copied as built, after a program has run; the FAT (fatbuf) and the root sectors in the buffers byte for byte against what R: should read; ROM 2 alone as the second image (another ROM the first): its 4 files (DEFRAG.COM, TERM.FNT, PAINT.RUN, CLAUDE.COM) read as built, 0 bytes free, its drive table and sector map; an `L2` ROM 2 not joined; a file whose cluster is in the gap fails to read; ROM 1 alone without DEFRAG.COM; INT 21h 36h for R: (FREE36.COM) with both ROMs (0 free of 504, f_36's loop not run), ROM 1 alone (252, walked) and ROM 2 alone (252); 0.6's ROM 1 layout beside the new ROM 2 from a floppy, joined (files read, a write refused, 36h); the screen saver from the ROM running R:\DEFRAG.COM with ROM 2 in, the dark clock without it. Eleven of twelve mutations of O10 each fail a check (the gap, ROM 2 alone's root and FAT sector, the sector map, ROM 1's root not fixed or its fix-up skipped, the id, mkrom's padding, spare sector and cluster numbers); one is equivalent: `jnc .m1` made `jmp short .m1`, as the gap's CF goes through `.m1` anyway. A 3-byte `MOV DI, R_PIECE` fails the build (the module's parity assert).
  - t_rom2_paint: a `.BMP` on C: opened with R:\PAINT.RUN from the ROM; ROM 1 alone: "PAINT.RUN is not on this disk".
  - t_rom2_claude: CLAUDE /R and /U from R: with EMS (exit codes 0), with R:\ current and with C: (by PATH: R:\CLAUDE.COM loaded); ROM 1 alone: "Bad command or file name".
- **pcemu** models the sockets (`roms=`) and the BIOS's boot (`boot_rom`).
- **The real-BIOS checks** need `rom/ROM_F000.BIN` and the GRiD MS-DOS EPROM image. These are not in the repo.
