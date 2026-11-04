# Bisecting the Claude-window resize restart (T5e, 2026-11-04)

`t5e` and `t5e-nofpu` both restarted the 1520 on a resize of CLAUDE.COM's
window (old gridlink: the Pi never resized), not caught (stage 1), last
steps `P`, then `l`. Each folder here is one half of the question; all are
CRASHLOG builds. Copy a folder's files to the boot floppy's root (TERM.RUN
there is used before ROM 1's), `MULTITASK=1`, CODE-A, resize the Claude
window with the mouse.

- `A-kernel-only`: T5e's LODE.SYS/LODEMT.SYS, main's TERM.RUN and CLAUDE.COM
  1.15 (the feature dormant: a version 1 descriptor, PB_VIEW never
  written). Restarts: the T5e kernel build itself (MT 28 bytes bigger, the
  arena moved), not the window-size logic.
- `B-apps-only`: main's kernel (os/diag's, with the floppy fix), T5e's
  TERM.RUN and CLAUDE.COM 1.16 (main's MT never writes PB_VIEW).
- `C-nodwait`: all of T5e, built `-dNODWAIT` (M10 never gives a floppy wait
  away). No restart: floppy waits are in it again.
