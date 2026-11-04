# Older builds, to find where the restart crash came in

Each folder has the LODE.SYS, LODEMT.SYS and LCMD.COM that main had after that merge. They are the normal builds, without CRASHLOG. Nothing else on the floppy changed since #142, apart from SYSTEM.RUN.

| Folder | main after | What it adds |
|---|---|---|
| `1-pre-M10` | #142 (`4e2c984`) | LCMD's pipes in %TEMP%; nothing of M10 or later |
| `2-M10` | #143 (`9b4b06c`) | M10: tasks run during floppy waits (INT 15h 90h/91h, IRQ 6, the gate) |
| `3-M11` | #146 (`a16f2da`) | M11: SysReq to the next task |
| `4-infoline` | #147 (`8b1d674`) | the Executive's info line with free memory |

After those come #148 (a frozen floppy owner always picked; HDPROBE and HDSCAN refuse beside tasks) and #149 (M12, the hard-disk waits): that is main, in `os/src`.

**To test one:** copy its three files onto the boot floppy, with `MULTITASK=1` in LODE.INI. Then do what crashed before: open a terminal window (CODE-P), resize it with the mouse, let go. Then open and close a picture, and try CODE-A with a resize. Try each a few times.

**What it tells us:**
- Crashes in `1-pre-M10`: the bug is older than everything from today and yesterday. It's in the windows themselves (T2-T5, Paint W1/W2).
- `1` clean and `2` crashes: M10 brought it.
- And so on down the table.

Start with `1-pre-M10`, then `3-M11`: two tries split the four.
