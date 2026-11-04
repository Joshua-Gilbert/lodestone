# Working in this repo with Claude Code

Lodestone is a DOS 3.30-compatible operating system for the GRiDCase
1520 (80C286), plus the bridge that links it to Claude: `os/` is the
system (NASM sources in `os/src`, apps in `os/apps`, CLAUDE.COM in
`os/claude`), `claude-link/` the Pi side, `pico-bridge/` the GPIB-Pico2
bridge, `plotter-nano/` the plotter's Nano.

## Build and test

The tools are Linux ones (nasm, mtools, Python 3 with unicorn and Pillow).

- Build: `sh build.sh` in `os/`, and `sh build.sh` in `os/claude/` for
  CLAUDE.COM.
- Tests: `python3 tests/test_<suite>.py` in `os/`, one suite at a time.
  Suites share build outputs (`src/LODE.MAP`, the ROM images), so two
  running at once give wrong results. `claude-link/tests/` has
  gridlink's tests, `pico-bridge/sim/host/run_sim_tests.py` the Pico
  bridge's.
- Most sources are CRLF in the working tree. Don't rewrite them with
  tools that drop the CR.

## PR and commit messages

Substance only: the problem, the changes, why. No process narration
("did a deslop pass", "ran two reviews", "added tests"), no validation
play-by-play, no AI-attribution trailer.
