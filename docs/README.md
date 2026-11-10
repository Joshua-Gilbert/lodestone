# docs

How each part of Lodestone works and how it was built, with its tests:

- `lodestone-0.2-kernel.md`: the kernel, the disk cache, the benchmark results on the 1520, and the tests.
- `lodestone-0.3-apps.md`: the UI core and its API, `.RUN` programs and their loader, System, Write, and their tests.
- `lodestone-defrag.md`: DEFRAG and the screen saver, worn-disk handling, and the power-cut tests.
- `lodestone-floppy-dev.md`: the floppy development loop, and what's on the floppy.
- `lodestone-splash.md`: the start-up picture (0.4.3): tracing the 1921 plate, the drawing and its packing, the bootstrap, System's switch, the tests; and the pcemu bug found on the way.
- `lodestone-font.md`: Lodefont, Lodestone's own 8×16 screen font: its design, its metrics, how it is built, and the other fonts on ROM 2.
- `lodestone-rom.md`: the EPROMs: ROM 1, which Lodestone boots from since 0.6, and ROM 2, the second EPROM added on 2026-10-24 for the programs that don't fit; their file systems, and how they are built.
- `lodestone-multitasking.md`: multitasking (`MULTITASK=1`): tasks, windows, and the kernel's switching.
- `term.md`: Term (0.4.0), the real Claude Code on the GRiD's screen through the Pi.
- `lodestone-resident-claude.md`: resident Claude (0.5, `CLAUDE /R`): Claude over a running DOS program, and how it was proved on the 1520.
- `gridfox.md`: gridfox (`CLAUDE /W`), Firefox on the Pi shown as text on the GRiD through Term's path: how it works, its keys, the tests.
- `lodestone-pictures.md`: pictures on the GRiD: gridfox's picture view and Claude Code's clickable plots, sharing one CELLS pixel operation and one Pi-side picture layer.
- `lodestone-paint.md`: Paint (`PAINT.RUN`), a painter that is also the BMP viewer: the screen as the canvas, two buffers in file order, INT 33h for the mouse, its resident cost, its tests.
- `serial-link.md`: the Claude link over a null-modem cable, for a GRiD without the GPIB cartridge (SERLINK).

Dated log entries keep the names in use at the time (Grid-OS, `GRIDOS.SYS`, `GRIDCMD.COM`, `GOSBOOT.COM`).
