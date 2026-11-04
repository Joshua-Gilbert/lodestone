# T5e's CRASHLOG build with MT never touching the 287 at a switch

`os/diag/t5e` restarted on Joshua's 1520 (2026-11-04) at a resize of
CLAUDE.COM's window, with the old gridlink, so with the Pi never resized.
CRASHRPT: stage 1 (not caught: a hardware reset), last step `P`, inside
`mt_load` past the 287's FRSTOR and before the kernel's variables were
back (`v`): a plain memory copy, no I/O. Earlier restarts stopped at `L`
(past the FNSAVE), `P` and `w`, every one close to the 287's save or
restore, which runs on in parallel with the CPU.

This is the same build with `-dNOMTFPU`: MT neither saves nor restores the
287 at a switch (fine while no program uses it). Same files and steps as
`t5e/README.md`. If the resize no longer restarts the machine, the 287's
save and restore at a switch are the trigger.
