# docs

Design notes, kept in step with the claude.ai Project "Grid-OS":

- `lodestone-0.2-kernel.md`: the kernel, the disk cache, the benchmark results on the 1520, and the tests.
- `lodestone-0.3-apps.md`: the UI core and its API, `.RUN` programs and their loader, System, Write, and their tests.
- `lodestone-defrag.md`: DEFRAG and the screen saver, worn-disk handling, and the power-cut tests.
- `lodestone-floppy-dev.md`: the floppy development loop, and what's on the floppy.
- `lodestone-splash.md`: the start-up picture (0.4.3): tracing the 1921 plate, the drawing and its packing, the bootstrap, System's switch, the tests; and the pcemu bug found on the way.
- `lodestone-resident-claude.md`: resident Claude (0.5): the plan, `CLAUDE /R` and its milestones; the spikes and their results on the 1520, and the hook bug they found.
- `term.md`: Term (0.4.0), the real Claude Code on the GRiD's screen through the Pi; and the design for Phase 2, Claude resident over DOS programs.

The other notes are still only in the Project: the roadmap, the kernel hardware spec, the 1520 BIOS memory map, the GPIB driver design, the EMS investigation, the findings on the original GRiD binaries, and claude-link.

Dated log entries keep the names in use at the time (Grid-OS, `GRIDOS.SYS`, `GRIDCMD.COM`, `GOSBOOT.COM`).
