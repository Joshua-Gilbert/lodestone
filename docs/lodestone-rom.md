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
| CALC.COM, DEFRAG.COM | the calculator at the prompt, and DEFRAG (the saver runs it) |
| TERMINUS.FNT | the second font |
| LODE.INI | the ROM's own settings (also the built-in defaults) |

512 bytes are left (with multitasking's LODEMT.SYS and TASKS.RUN, UI API 8's pop-up menus and clipboard, and Write's drags and menu). CLAUDE.COM and Paint (still on its own branch) are meant for ROM 2. Until then they live on C: or A:.

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
  - ROM 2 will be system type 2, id `L2` (`mkrom.py --data`).
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

**Without the ROM, 0.6 costs 0.1 KB against 0.4.5 (562.2 / 578.3 KB, was 562.3 / 578.4).** That is the PATH search in the Executive and the two-file settings reader. With the ROM in, R:'s module adds 446 bytes.

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
  - memory.
- **pcemu** models the sockets (`roms=`) and the BIOS's boot (`boot_rom`).
- **The real-BIOS checks** need `rom/ROM_F000.BIN` and the GRiD MS-DOS EPROM image. These are not in the repo.
