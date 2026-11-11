# CRASHLOG without the 287 at switches

The same CRASHLOG build as `os/diag`, built with `-dNOMTFPU` as well: MT never saves or restores the coprocessor at a switch (no FNSAVE, FRSTOR or FNINIT; `mt_fpu` left 0). Tasks then share the 287's state, so don't run programs that use it in two tasks at once while testing.

**Why:** on the 1520 (2026-11-04), Return on CLAUDE.COM restarted the machine with the last step `L`: inside `mt_load`, after the 287's FNSAVE (`n`, `N`), and before the next task was loaded (`l`). `mt_load`'s FRSTOR (or FNINIT) is a multi-word 287 transfer, made there while the floppy's DMA is under way; no other kind of switch does that. If this build doesn't crash where `os/diag` does, the 287 during the floppy's DMA is the cause.

Use its `LODE.SYS`, `LODEMT.SYS` and `CRASHRPT.COM` as `os/diag`'s.
