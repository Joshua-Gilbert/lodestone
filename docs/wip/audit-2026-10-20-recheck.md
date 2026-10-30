# Closing the 2026-10-20 audit: the rows left open, re-checked at ede102d

**What this covers.** Every row of the 2026-10-26 audit's §9 (the status of the 2026-10-20 audit) that says "left" with no audit-3 row taking it over, plus:
- X20's and X28's leftovers, X23, X24, X25 and X27;
- K2 and K5 (from the 2026-10-17 audit), S4, KC-2 and AP-1;
- the GPIB query builders in claude-link, XR-14, XR-17 and XR-20.

XR-13 (TESTLIB) is H7/H8's (fork D) and isn't repeated here. The rows §9 hands to an audit-3 row (R1, R5, R7, R16, R17, R34, R61, R63, R68, R70, O1, O4, O6, O18, F2, P5, P10, T10, H4-H8, H12) are closed by those.

**How each row was checked.** Each was re-read against today's code. **†** marks a figure test-assembled in a scratch checkout of ede102d and read from the map. The others are counted encodings, or the 2026-10-20 count where the code is unchanged.

**The rules applied.** "Needs yes" is the audit's rule: the row slows something, grows the resident cost with MULTITASK off, or grows LODEMT.SYS.

**ROM 1.** "ROM 1" means the row changes what's on ROM 1: LODE.SYS, LODEMT.SYS, LODE.PIC, LCMD.COM, or the .RUNs. **A row that changes ROM 1 belongs before the burn, or waits for the next ROM change.**

**Today's layout:**

| What | Value |
|---|---|
| Kernel | `lastdrv` 40CFh, `image_end` 40D0h (the code fills its last paragraph), `bss_end` 7600h |
| UI | `ui_keep_end` 64C2h (2 bytes into a paragraph) |
| LCMD | `prog_end` 3AB0h |
| LODEMT.SYS | 20,335 B (40 sectors, 145 B left in the last) |
| ROM 1 | 3,584 B left |

## Bugs and MS-DOS differences

| Prior id | Still holds? | What | Cost / gain | Needs yes / ROM | Recommendation |
|---|---|---|---|---|---|
| X23 | yes: f_4E finds no device name ([KFILE.INC:1651](../os/src/KFILE.INC#L1651)) | GRiD MS-DOS 3.30 finds `NUL`, `CON`… with attribute 40h; Lodestone answers 2 | Kernel grows by a dev_lookup on the failure path (~20-40 B, counted). First every caller must skip 40h: LCMD's DIR and Tab, the Executive's pat_here/xfer_do ([EXEC.INC:1553](../os/src/EXEC.INC#L1553), [2093](../os/src/EXEC.INC#L2093)), where a Copy of a title CON would read the keyboard for good, CLAUDE.COM's lookups, and claude-link's stat ([grid.py:191](../claude-link/gridlink/grid.py#L191)) | yes (resident kernel); ROM 1 | **Won't do.** No program seen needs it. Today's answer protects four callers that would each need a change. Keep it listed as a known difference. |
| X24 | yes: an empty name is filled with `?` ([KFILE.INC:1661-1664](../os/src/KFILE.INC#L1661-L1664)) | `\`, `A:`, `A.B\` and `E.F\..` find something; MS-DOS answers 18 or 3 | ~4-8 B kernel. **It breaks claude-link's Info of `A:\`**, which searches with no name and shows the root's first file, so claude-link would need a change too | yes (behaviour); ROM 1 | **Won't do.** Lodestone's own callers rely on it; no outside program seen does. |
| X25 | yes: f_4E writes the search into the DTA before find_next ([KFILE.INC:1655-1675](../os/src/KFILE.INC#L1655-L1675)) | A failed FIND FIRST spoils the search before it; MS-DOS lets a FIND NEXT carry on | ~20-30 B kernel: the state built in scratch, copied on success | yes; ROM 1 | **Won't do** till a program is seen to need it. Nothing in Lodestone does it. |
| X27 | yes: resolve looks up each name, `..` included ([KFAT.INC:190](../os/src/KFAT.INC#L190)) | `zzz\..\f.txt` through a missing directory; MS-DOS also refuses a directory part over 64 characters | `.` and `..` worked out in the text before the walk: ~60-100 B kernel, risk M (resolve is the hot path) | yes; ROM 1 | **Won't do.** Only an edge case, and the cost lands on every path call. |
| X20 leftovers | yes, all as listed in the 2026-10-20 row (`\\`, over 128 characters, `\DEV\NUL` with five calls, `.` in the root, `SUB\.`, `SUB\..`, an empty name, `Q:`, CREATE TEMPORARY with no path, RENAME onto `SUB\NUL.*`, a bare `A:`) | Error codes that differ from MS-DOS 3.30 in edge cases | ~20 B each, kernel | yes; ROM 1 | **Won't do.** Close them as a recorded list of known differences. ERRS_MS.TXT already holds MS-DOS's answers. |
| X28 leftovers | yes | 47h of a drive with no disk answered from memory; FCB 0Fh/11h without INT 24h; `DIR B:` ending "File not found" after Fail | Kernel bytes for the first two; LCMD for the third | yes; ROM 1 | **Won't do.** These are cosmetic or FCB-only (no FCB program seen). The `DIR B:` text matches what LCMD does for any Fail. |

## The kernel (resident: lost to DOS programs)

| Prior id | Still holds? | What | Cost / gain | Needs yes / ROM | Recommendation |
|---|---|---|---|---|---|
| XI-13 (kernel) | yes: push ladders in same_disk and crit_disk ([KDISK.INC:307-355](../os/src/KDISK.INC#L307-L355), [1613-1640](../os/src/KDISK.INC#L1613-L1640)) | pusha/popa; crit_disk puts AL into the frame (`mov bp,sp / mov [bp+18],al`) | −15 B .text (−14 with a parity pad). **Alone: no paragraph**, since the code fills its last one exactly | no; ROM 1 | **Do, together with G1-5.** |
| G1-5 | yes: terminate keeps the return address in t_ip/t_cs ([KPROC.INC:666-679](../os/src/KPROC.INC#L666-L679), [692](../os/src/KPROC.INC#L692)) | Keep it in SI/CX instead | † −10 B .text, −4 B BSS: bss_end 7600h → 75F0h, **one paragraph alone**. † **With XI-13: image_end 40D0h → 40C0h and bss_end 7600h → 75E0h, two paragraphs (32 B)**, builds with EVEN's asserts | no (faster); ROM 1 | **Do** (kernel PR). Re-pin test_mt's OFF_MAP and the multitasking doc's figures, as the row says. |
| KF-15 | yes: rw_where calls use_drive every time ([KFILE.INC:786-791](../os/src/KFILE.INC#L786-L791)) | Drop the call, read D_SHIFT from [actp] | −6 B. It has three callers (856, 1017, 1195); the third must be shown to have the drive set | no; ROM 1 | **Won't do.** 6 B, no paragraph after the two rows above, and a new invariant. |
| KF-10 (rest) | yes | rw_locate/rw_extend/rw_partbuf shared by file_read and file_write | ~86 B, but a call and return on every chunk and two compares a cluster: **slower** | yes (slower); ROM 1 | **Won't do.** Declined as slower in PR #55; nothing has changed since. |
| K2 | yes: ex_name 132 ([KPROC.INC:30](../os/src/KPROC.INC#L30)), path2_buf 130 ([KFAT.INC:15](../os/src/KFAT.INC#L15)) and ren_de 32 ([KFAT.INC:1114](../os/src/KFAT.INC#L1114)) are their own BSS | Put them in the bottom 1 KB of the INT 21h stack (kstack_end), which the screen capture and the PrtSc driver lend out | 294 B BSS, about **−18 paragraphs resident** (counted). Risk **M-H**: the capture area, the PrtSc driver's load, MT's kernel-stack slices and a nested INT 24h during EXEC must never meet | no; ROM 1 | **User's call.** It is the largest resident saving left in either audit. It needs its own PR, with a test that captures during EXEC's INT 24h prompt under MT. |
| KC-2 = XR-1 | yes: capture's file writer is in the kernel ([KCORE.INC:182](../os/src/KCORE.INC#L182), cap_b 403, cap_fl 406) | Screen capture as a SCREEN.PRN-style driver read at Shift-PrtSc, like PS.PRN | ~340-355 B kernel (the 2026-10-20 count), about −21 paragraphs. Shift-PrtSc then needs the file on a disk or ROM, plus one ROM 1 sector of the 7 free. Risk M (the 2026-10-20 verifier said H) | it changes a feature; ROM 1 (a new file) | **User's call** (a product decision): about 340 B for every DOS program, against Shift-PrtSc depending on a file. |
| K5 | yes | Load the GPIB driver only when the 7210 answers | 1,762 B, but **nothing on the 1520 that has the cartridge** | — | **Won't do.** It saves nothing on the target machine. |
| KC-16 | yes: rs_aini's own INT 24h ([KROM.INC:889-915](../os/src/KROM.INC#L889-L915)) | Use the kernel's default int24 | 33 B of LODE.SYS's start-up section (file-only). LODE.SYS keeps its 97 ROM sectors | no; ROM 1 | **Won't do.** It frees no sector, and rs_i24 makes the "no disk is no error" contract explicit. |
| S4 | yes: f_09 makes one con_out per character ([KCORE.INC:797-805](../os/src/KCORE.INC#L797-L805)) | Batch AH=09h through dev_write.con | Faster `$` strings (most visible redirected); +bytes kernel | yes (grows resident); ROM 1 | **User's call**, low priority. |
| S14 | yes: ems57's exchange is a byte loop ([KEMS.INC:455-459](../os/src/KEMS.INC#L455-L459)); ems_int67 still calls ems_map | Word-wise exchange and backward moves; inline ems_map in 44h | ~7 % per EMS map (2026-10 measure); +bytes in the EMS module (resident with EMS) | yes; ROM 1 | **User's call.** Do it only if EMS exchanges show up in a profile. |

## Multitasking (LODEMT.SYS, MT-only)

| Prior id | Still holds? | What | Cost / gain | Needs yes / ROM | Recommendation |
|---|---|---|---|---|---|
| XI-14 | yes, and grown: ~224 `cs:` prefixes from mt_f0 to the F0h handlers ([KMT.INC:1984-4200](../os/src/KMT.INC#L1984)) | Run the F0h handlers with DS = CS | Up to ~150-200 B MT-only (counted: one byte a prefix, less the DS brackets and `ss:` for kernel variables). It frees no ROM sector (367 B would be needed). Risk M | no; ROM 1 | **User's call.** Worth it only if MT's memory matters; every F0h handler changes. |
| G2-2 | yes: mt_scrsv/mt_scrld/mt_sync copy 32 KB with rep movsw through windows 0-1 ([KMT.INC:5388-5548](../os/src/KMT.INC#L5388)) | Use INT 67h 57h | 39 B MT-only; 57h's speed against rep movsw unmeasured; ~90 B more kernel stack inside INT 21h. Risk M | maybe slower: measure first; ROM 1 | **Won't do** unless 57h measures as fast. A screen switch is hot. |
| G2-3 | yes | mt_kwant and mt_preempt share a test | ~8 B (re-measured in audit 3) | ROM 1 | **Won't do.** It's 8 B, and both are hot. |
| G2-6 | yes: four copies | A shared mt_safe/mt_preempt call tail | 8-16 B; test_mt's Audit keys on the return addresses | ROM 1 | **Won't do.** Too little gain for a rewrite of test_mt's Audit. |

## The resident UI and the apps

| Prior id | Still holds? | What | Cost / gain | Needs yes / ROM | Recommendation |
|---|---|---|---|---|---|
| UI-7 (rest) | yes: ui_msg and ui_ask save and restore the band each ([UICORE.INC:2093-2106](../os/src/UICORE.INC#L2093-L2106), [2122-2135](../os/src/UICORE.INC#L2122)) | One band save/restore | ~20 B UI; ui_keep_end 64C2h → about 64AEh, **−2 paragraphs** (counted; parity to be kept). Risk M: UI_MSG returns BX/CX for a click | no; ROM 1 | **Do** (UI PR), with a test of a click on a message and on an ask. |
| UI-1 (rest) | yes, by design: build_info, s_cpu…s_bios run at every draw_all ([EXEC.INC:2622](../os/src/EXEC.INC#L2622), [2869](../os/src/EXEC.INC#L2869)) | Move them to uiboot | — | — | **Won't do.** They aren't start-up-only any more. |
| UI-5/XI-5 (sv_tail) | yes, by design ([UICORE.INC:4331-4358](../os/src/UICORE.INC#L4331)) | sv_tail over tmp | 30 B UI BSS | — | **Won't do.** It is live across DEFRAG, and under MT the Executive can draw into tmp meanwhile. |
| UI-11 (form prompts) | dropped in PR #55 | Form prompts built in msgbuf | ~14 B net | — | **Won't do.** The saver's redraw writes msgbuf during a form (that rejection stands). |
| XI-6 | yes: m33_save/m33_drawn/m33_tmp are their own BSS ([MOUSE33.INC:65-67](../os/src/MOUSE33.INC#L65-L67)) | INT 33h's save-under over ubuf | 102 B UI BSS | — | **Won't do.** Unsafe with MULTITASK=1: mt_scrto re-shows the pointer when task 0 comes to the front. Today's separate buffers are the safe state. |
| AP-2/XS-7 | yes | SYSTEM and CALC use the Executive's sysinfo | −75-90 transient, **+3-7 B resident UI**; breaks the RUN_API policy | yes (grows UI); ROM 1 | **Won't do.** Resident bytes for transient ones. |
| AP-6 | yes: LODE.PIC 2,544 B | sp_npx/sp_lpx called, not expanded; variables not shipped | −256 B file-only, but **~60 ms slower** to draw, and LODE.PIC keeps its 5 ROM sectors (2,288 B) | yes (slower); ROM 1 | **Won't do.** It frees no ROM sector and is slower. |
| AP-13 | yes | SYSTEM's set_clock through UI_SBDATE | −18 B transient; **the form shows a 2-digit year** | ROM 1 | **Won't do.** A visible change for 18 B; the row ranked it last. |
| AP-14 | yes: Write walks the cursor's line three times a key ([WRITE.ASM](../os/apps/WRITE.ASM): cur_col in fix_view, update, status) | Cache the column | **+7 B** transient, −2 of 3 line walks per key (faster typing on long lines). WRITE.RUN stays in 20 sectors (174 B left) | no (faster, transient); ROM 1 | **Do** (apps PR), before the burn if it goes with one. |

## LCMD (lost to programs started from the prompt)

| Prior id | Still holds? | What | Cost / gain | Needs yes / ROM | Recommendation |
|---|---|---|---|---|---|
| SH-5 | yes: TYPE has its own read/^Z-scan/write pump ([LCMD.ASM:3018-3060](../os/src/LCMD.ASM#L3018)); COPY makes IOCTL 4400h calls per chunk (3109, 3255, 3281) | One pump, the IOCTL answer taken once at open | ~47 B LCMD: prog_end 3AB0h → about 3A80h, **−3 paragraphs**; COPY a call per chunk faster. Risk M (COPY CON and the short write are untested) | no; ROM 1 | **Do** (LCMD PR), with tests for COPY CON and a full disk. |
| L4 | yes: for_dta 44 + for_buf 130 + for_cmd 130 sit in BATCTX all the time ([LCMD.ASM:4890-4900](../os/src/LCMD.ASM#L4890)) | Have them only while a FOR runs | ~304 B LCMD-under-child, about −19 paragraphs. Risk M-H: BATCTX is saved per CALL level | no; ROM 1 | **User's call.** It's big, but every nested CALL/FOR path needs care. |
| S15 | yes: try_exts makes one 43h per extension per PATH directory ([LCMD.ASM:1082-1112](../os/src/LCMD.ASM#L1082-L1112)) | One FIND FIRST `name.*` per directory | Faster PATH search; bytes about even | ROM 1 | **Won't do.** The directory cache makes the repeat lookups memory hits, and since X28 a missing directory stops after one. |

## Claude and the link

| Prior id | Still holds? | What | Cost / gain | Needs yes / ROM | Recommendation |
|---|---|---|---|---|---|
| CL-17 | yes: blank_row draws 80 cells one call at a time ([CELLTEXT.INC:35-50](../os/claude/CELLTEXT.INC#L35-L50)); put_cell does imul and an ES switch per cell ([TERMCELL.INC:221-235](../os/claude/TERMCELL.INC#L221-L235)); term_redraw switches DS per cell | (a) blank_row as rep stosw; (b) term_redraw's DS hoisted; (c) put_cell per run | (a) ~7× on the spinner and console redraws; (c) ~25 % of a CELLS frame, **Term's hot path**. A few bytes either way in CLAUDE.COM and RCON | yes if CLAUDE's resident part grows (as X51); not on the ROMs | **Do** (Claude PR): (a) and (c) first. Run test_term, test_resident_term and the stub's stack check. |
| CL-16 | yes ([CLAUDE.ASM](../os/claude/CLAUDE.ASM) conv_newline) | Chat: scroll rows on a newline, not a full redraw | ~40 → ~8 ms a TEXT frame; **+40-60 B** Claude-resident | yes; not on the ROMs | **User's call.** It only helps chat (the API-key agent), not Term. |
| GPIB query builders | yes: mcp.py's gpib_measure ([mcp.py:576-589](../claude-link/gridlink/mcp.py#L576-L589)), mcp.py's gpib tool (690) and tools.py's chat agent ([tools.py:529-536](../claude-link/gridlink/tools.py#L529-L536)) each decide "a plain query" themselves | One `is_plain_query()` in grid.py | ~10 lines. **tools.py's rule lacks mcp.py's control-character check**, so the chat agent skips approval for a query with control characters | — (Pi only) | **Do** (claude-link PR, after fork A's), tools.py getting mcp.py's stricter rule. |
| XR-14 | yes, on purpose | The EMMXXXX0 and GRIDGPIB finders in many files | Source only | — | **Won't do.** RCON reads the IVT and CLAUDE uses 35h on purpose (DOS may be busy under RCON). |

## Tests and tools

| Prior id | Still holds? | What | Cost / gain | Needs yes / ROM | Recommendation |
|---|---|---|---|---|---|
| SH-9 | yes: three `times 512 db 0` buffers ([LODEBOOT.ASM:192-194](../os/src/LODEBOOT.ASM#L192-L194)) | Move them to .bss | LODEBOOT.COM 3,052 → 1,516 B (file-only) | no; **not on a ROM** | **Do** (tools PR). Its test_kernel boot check stays. |
| XR-20 | yes: ROMVID.ASM:42's and UPPER.ASM:27's dead `mov cx,ax`, RAMSPEED's `ndig` (681, 743), HDPROBE's unprinted s_echobad (1549) | Delete them | 91 B file-only | no; not on a ROM | **Do** (tools PR). |
| XR-17 | yes | STRLIB.INC: strlen/streq/upcase/… shared at source | Source only, every binary touched | ROM 1 if any byte moves | **Won't do.** Source-only gain for a change that would touch every ROM binary. |

## Product decisions

| Prior id | Still holds? | What | Cost / gain | Needs yes / ROM | Recommendation |
|---|---|---|---|---|---|
| KC-2 | see the kernel table | Capture as a driver file | ~340 B resident | it changes a feature; ROM 1 | **User's call.** |
| AP-1 | yes: padded help lines (CALC, SYSTEM, WRITE; the core's table) | A TAB in help_draw, with the stop computed | −287 B transient, ~−177 B resident UI (about −11 paragraphs). Needs RUN_API 7 for three .RUNs and a change to test_apps' RUN_API policy. Risk M | ROM 1 (the UI and three .RUNs) | **User's call.** It is the second-largest resident saving here, after K2 and KC-2. |

## Totals

| Bucket | Count | Rows |
|---|---:|---|
| Do | 9 | XI-13 with G1-5, UI-7, AP-14, SH-5, CL-17, the GPIB query builders, SH-9, XR-20 |
| User's call | 9 | K2, KC-2, AP-1, L4, S4, S14, XI-14, CL-16, G2-2 (measure first) |
| Won't do | 22 | X23, X24, X25, X27, X20's leftovers, X28's leftovers, KF-15, KF-10, K5, KC-16, G2-3, G2-6, UI-1, UI-5/XI-5, UI-11, XI-6, AP-2/XS-7, AP-6, AP-13, S15, XR-14, XR-17 |

G2-2 is counted under user's call: do it only if 57h measures fast. KC-2 is the same row in the kernel table and under product decisions.

## Suggested next PRs

1. **ROM 1 batch, before the burn (or with the next ROM change):**
   - the kernel's XI-13 + G1-5 (−2 paragraphs, measured);
   - the UI's UI-7 (−2 paragraphs);
   - LCMD's SH-5 (−3 paragraphs);
   - Write's AP-14 (faster typing).
   - Then ROM 1 rebuilt once.
2. **Claude: CL-17 (a) and (c).** Term's redraw and the CELLS path. It needs the user's yes if CLAUDE's resident part grows.
3. **Off the ROMs:**
   - SH-9 and XR-20 (tools);
   - one `is_plain_query()` in claude-link (after fork A's PR).
4. **User's calls, one PR each if taken:** K2, KC-2, AP-1, L4. Then the speed rows S4, S14 and CL-16, and XI-14 for MT's memory.
5. **Closing the doc.** Add a closing section to the 2026-10-20 audit with each won't-do and its reason, and mark the rows done as their PRs land.
