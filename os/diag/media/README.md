# MEDIA: does the 1520's floppy drive say which kind of disk is in it?

FORMAT can't tell a 720 KB disk from a 1.44 MB one: with no size given it
keeps the size a disk was formatted before, else the drive's own, 1.44 MB.
A 720 KB disk never formatted, or formatted 1.44 MB, needs `/F:720`. The
disk's density hole sets the drive's own write current; whether the drive
also tells the computer is what this finds out. If anything below changes
with the hole, FORMAT can choose the size by itself.

## Running it

Copy `MEDIA.COM` to a floppy or C:, and run it under GRiD MS-DOS, or under
Lodestone with no other tasks (or `MULTITASK` off):

    MEDIA A:

Then, pressing a key after each:

1. a 1.44 MB disk (hole), formatted;
2. a 720 KB disk (no hole), formatted 720 KB;
3. the 720 KB disk formatted 1.44 MB, if there is one (the hole the same
   as 2, the format the same as 1: shows which lines follow the hole and
   which the format);
4. the 1.44 MB disk with its hole taped over, if you can;
5. no disk at all.

Esc ends it. Nothing is written to any disk. Send back the whole screen
(Shift-PrtSc, or a photo).

## What it shows

Once, at the start: the drive's type from the BIOS (INT 13h 08h: 4 is
1.44 MB) and CMOS 10h. Then for each disk:

- `idle 3F0-3F7`: the floppy controller's ports (and the hard disk's 3F6h
  and 3F7h, which they share) as they are. 3F5h, the data register, isn't
  read: that would take a byte from the controller.
- `boot sector`: the BIOS's read of it (AH=00h read), and the BIOS's media
  state for the drive (40:90h for A:, 40:91h for B:): the data rate it
  found the disk at, which follows the disk's format, not the hole.
- `selected 3F0-3F7`: the ports again just after that read, while the
  drive is still selected and its motor running. A drive that gives a
  density signal at all gives it only when selected, so this line matters
  most. 3F7h bit 7 is the disk-change line; the other bits there are the
  hard disk's. On some controllers 3F0h/3F1h (status A and B) or 3F3h
  (bits 7-6, media ID) carry it.
- `ST3`: the controller's Sense Drive Status, the drive's own lines (fault,
  write-protect, ready, track 0, two-sided). "no answer" means the
  controller didn't take the command; it is then reset through the BIOS.
- `INT 13h 20h`: the PS/2 BIOS's call for the media in a drive that senses
  it. CF=1 AX=01xxh means the 1520's BIOS doesn't have it.

A bit that is one way with the hole (disk 1) and the other without it
(disks 2, 3 and 4), whatever the disk's format, is the hole. If no bit changes, the drive
keeps the hole to itself and `/F:720` stays the way to format a 720 KB
disk.

`MEDIA.COM` is built from `MEDIA.ASM` with `nasm -f bin -o MEDIA.COM
MEDIA.ASM`.
