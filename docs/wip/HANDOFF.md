# Where the audit work stopped (2026-10-30)

Delete this folder (`docs/wip/`) once its contents are merged or redone; it is not meant to ship.

## On `claude/loving-fermat-tm5l7l` (pushed, no PR yet)

Audit 3 (2026-10-26) step 9's rows, merged from three forks, each fork's suites passing with main's counts:
- **A:** P1, P3, P4, P5, P6, P9, P10 (claude-link and the Pi side).
- **B:** N1, N2, P2, H13, H14. N3 skipped: labels up to 200 characters need cmdBuf's 256.
- **D:** H7, H8, P8.

Plus:
- the chat agent's GPIB query rule fixed (a query with a CR/LF inside asked nothing: an approval bypass);
- one `is_plain_query()` in grid.py.

**Before a PR:** run the whole suite once on the merged branch, test_mt alone (it races test_apps over LODE.MAP). Then mark the rows in the audit doc and update the README's count:
- test_mcp moved one test (P6): −1;
- test_term added one (P9): +1.

## Not merged: fork C (H4, H5, H6, H9, H11, H15)

- `audit3-c/`: five commits (H11, H15, H9, H6, H5) as `git am` patches against ede102d. They conflict with fork D's H7 in `os/tests/NOMATCH.ASM`, `NULDIR.ASM` (the X15 comment, now in PROBE.INC) and `test_kernel.py`. Resolve them, then run the full suite. Their full-suite check didn't finish (it matched so far: test_apps 553, test_kernel 501, test_rom 105, test_resident 54).
- `audit3-H4-unfinished.patch`: H4 (the shared harness helpers in ktest), uncommitted and untested. Finish it or redo it.

## Next: the 2026-10-20 audit's leftovers (the user's decisions)

`audit-2026-10-20-recheck.md` is the re-check of every left row against ede102d. The user chose:

1. **Hold the ROM 1 burn** for the four "do" rows, in one PR with ROM 1 rebuilt once:
   - XI-13 + G1-5 (−2 paragraphs, kernel);
   - UI-7 (−2 paragraphs, UI);
   - SH-5 (−3 paragraphs, LCMD);
   - AP-14 (Write).
2. **Take all four big rows**, each its own PR:
   - K2: EXEC/RENAME scratch into the kernel stack's bottom, about −18 paragraphs; needs a capture-during-EXEC test under MT.
   - AP-1: help lines with a TAB, about −11 paragraphs UI.
   - L4: FOR's buffers only while a FOR runs, about −19 paragraphs LCMD.
   - KC-2: Shift-PrtSc's file writer as a driver file, about −21 paragraphs; Shift-PrtSc then needs the file, and one ROM 1 sector.
3. **Take all the speed rows:**
   - CL-17 (a)(c): Term redraw;
   - CL-16: chat scrolling;
   - S4: AH=09h;
   - S14: EMS exchange;
   - XI-14: MT's F0h handlers with DS = CS.
4. Also "do": **SH-9** (LODEBOOT's buffers to .bss) and **XR-20** (dead instructions in the tools).
5. The other 22 rows are won't-do, each with its reason in the re-check file. Copy them into a closing section of `docs/lodestone-audit-2026-10-20.md` so both audits close.

Everything in 1-3 except CL-16/CL-17 changes ROM 1: burn after those PRs.

Also out of scope but noticed: `pico-bridge/README.md` and `FIRMWARE.md` say 111 sim checks; it is 116 since X65. The X65 firmware still needs a real Pico build (`bridge_pico2.uf2` not rebuilt).
