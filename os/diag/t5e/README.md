# CRASHLOG build of T5e (the Claude window as tall as it shows)

Joshua's 1520, 2026-11-04: with T5e, resizing CLAUDE.COM's window (only that
window) restarts the machine. Main's build doesn't. Not reproduced in pcemu,
with the stand-in or the real Claude Code 2.1.318, floppy timed and strict,
by keys or mouse drags.

This folder is that branch's build with `-dCRASHLOG` (`os/diag/README.md`
says what it records and how to read it), with the same branch's TERM.RUN
and CLAUDE.COM 1.16. Copy all of them to the boot floppy's root, in place
of the normal LODE.SYS and LODEMT.SYS (TERM.RUN there is found before ROM
1's). `LODE.INI` needs `MULTITASK=1`.

1. After the start-up, run `CRASHRPT` (a "Last session" line: the build is
   running).
2. CODE-A, then resize Claude's window with the mouse till it restarts.
3. A report screen instead of the POST: photograph it, press a key, then
   run `CRASHRPT` and send `CRASH.BIN`. The POST instead: run `CRASHRPT`
   and photograph what it says (the breadcrumbs: how far it got).
