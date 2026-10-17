# gridfox: Firefox on the GRiD (W1, 2026-10-16)

`CLAUDE /W` makes the GRiD 1520 the screen and keyboard of a real Firefox on
the Raspberry Pi. Firefox does all the work (JavaScript, sign-ins, modern
sites); the GRiD shows each page as text.

It is Term with a different program in the pty. Term already runs `claude` on
the Pi while the GRiD shows its screen; here gridlink runs `gridfox`. The GRiD
side is Term's code as it was, plus 32 bytes for the switch.

```
GRiD 1520            GPIB          AR488 Nano     USB      Raspberry Pi 5
CLAUDE /W  ── KEYS ──────────────▶ (device, 7) ──────▶  gridlink ── pty ── gridfox ── Marionette ── Firefox (headless)
 rows 0-23 ◀── CELLS (changed cells) ◀────────────────    pyte screen, cell diff (Term's, unchanged)
```

## Decisions (Joshua, 2026-10-16)
- **Firefox on the Pi** does the browsing; the GRiD is its terminal.
- **Text view first, picture view later.** The text view reuses Term's cell
  path whole. A dithered 640x400 picture of the page is milestone W2.
- **Claude Code shares the browser later** (W3), as a tool, after the
  browser itself works.

## How it works

### On the Pi (`claude-link/gridfox`)
- **`marionette.py`**: Firefox's own remote control, which every Firefox has.
  - Started with `--marionette`, Firefox listens on 127.0.0.1:2828.
  - A message is its length, a colon, and JSON. About 100 lines of Python,
    with no geckodriver and no packages.
  - `Firefox` starts it headless with its own profile, `~/.cache/gridfox/profile`,
    so cookies and sign-ins are kept. If a Firefox is already listening on
    the port, it uses that one.
  - Pictures are off (`permissions.default.image` 2): the text view needs
    none, and they are most of a page's weight. `--images` turns them on.
  - Pages load "eager": gridfox reads the page at DOMContentLoaded rather
    than waiting for every last script.
- **`extract.js`**: runs inside the page and walks what Firefox rendered.
  - It reads computed styles, so hidden elements stay hidden and
    screen-reader-only text is skipped.
  - It returns blocks of text runs: headings, paragraphs, list items with
    their numbers, pre (spaces kept), quotes, table rows, rules.
  - It also returns every link, button and form field, numbered. The
    elements are kept in `window.__gridfox`, so `act.js` can click one or
    set its value by number.
- **`page.py`**: lays the blocks out at 80 columns.
  - Word wrap; headings as inverse bands (`h1`, `h2`) or `▸` (`h3`-`h6`);
    `•` and numbered lists, indented by depth; `│` quotes; ` │ ` between
    table cells.
  - Characters the GRiD hasn't got are mapped to near forms (curly quotes,
    dashes); wide characters and emoji are dropped.
  - Each cell knows which link or field it belongs to.
- **`app.py`**: the 80x24 program in the pty.
  - Row 0 is the address, rows 1-22 the page, row 23 the status line. The
    page title goes to the GRiD's own band (row 24) through the terminal
    title.
  - Each change is drawn as whole rows inside `?2026`, so Term sends one
    frame. Only the rows that changed are written.
  - Back and Forward come back to where you were on the page.
  - A page is read again 0.6, 2 and 5 s after it loads, so pages filled in
    by script show up; the place on the page is kept.
- **gridlink**:
  - `app=web` in the GRiD's HELLO starts gridfox in a Term session of its
    own, kept apart from Claude Code's.
  - That session gets no MCP tools and no `.mcp.json`. The Pi's HELLO
    answer says `gridfox`.
  - `[web] command` in the config sets the program (default
    `python3 -m gridfox`).

### On the GRiD (`os/claude/CLAUDE.ASM`)
`/W` is `/T` with `app=web` in the HELLO: 32 bytes. CLAUDE.COM is
20,436 bytes.

## Keys

| Key | Does |
|---|---|
| Up / Down | a line |
| PgUp / PgDn, Space | a screen |
| Home / End | top, bottom |
| Tab / Shift-Tab | next / previous link, button or field (the address shows on the status line) |
| Return | follow the link, press the button, type in the field |
| F, then a number | follow link *n* on the screen: numbers are drawn over the links |
| Left or Backspace / Right | back / forward |
| G (or O, F6) | type an address, or words to search for |
| S | search (DuckDuckGo's HTML page; `--search` changes it) |
| / and N | find on the page, find the next |
| R | reload |
| H or ? | help |
| Esc | cancels what is being typed |
| CODE-Q | leaves CLAUDE on the GRiD; gridfox and Firefox keep running on the Pi |

**Forms:**
- Return on a text field asks for its text on the bottom row.
- Return there fills it in, then goes on to the form's next field, or sends
  the form after the last one. A password is shown as stars.
- Return on a check box ticks it.
- Return on a list opens its choices: Up/Down, then Return.

## Measured (emulator and GridSim, stand-in Firefox)

| | |
|---|---|
| A new page (the long test page), bytes to the GRiD | 563 |
| One screen down | 337 |
| At 3.2 KB/s (stock bridge) | about 0.18 s and 0.1 s |

The page's own weight never crosses GPIB, only the cells that change. How
long Firefox takes on the Pi 5 for a real site is not measured yet.

## Tests

- `claude-link/tests/test_gridfox.py` (11 tests):
  - layout and wrapping, the key parser and line editor;
  - the real `extract.js` and `act.js` against a stand-in Firefox;
  - the app key by key: follow, back with the place kept, hints, find;
    a search form, a two-field sign-in (the password not shown), a button
    a script answers, a list, a check box;
  - a page filled in late by script;
  - end to end through gridlink and GridSim, with the byte counts.
- `tests/fake_firefox.py` is the stand-in: a Marionette server whose pages
  are jsdom (`fake_firefox_dom.js`), served from `tests/web/`. It needs Node
  and `npm install` in `tests/`.
- `test_emu_term.py` `test_web_gridfox`: the real CLAUDE.COM `/W` in the
  emulator. The GRiD's screen matches the Pi's cell for cell after a page,
  a link followed and a PgDn.
- Unchanged and passing:

  | Suite | Checks |
  |---|---|
  | `test_term` | 18 |
  | `test_e2e` | 10 |
  | `test_mcp` | 14 |
  | `test_emu` | 20 |
  | `test_emu_term` | 9, with the new one |
  | `test_resident` | 70 |
  | `test_resident_term` | 77 |
  | `test_claude_kernel` | 21 |

## Not yet tried
- **A real Firefox.** Firefox could not be downloaded in the build
  workspace, so the scripts have only run under jsdom. jsdom lays nothing
  out, so `extract.js` falls back to tag names there. In Firefox it uses
  computed styles, which is the better path but untested.
  - First check on the Pi: `python3 -m gridfox --console https://example.com`
    in an 80x24 terminal.
- **Busy waits.** gridfox waits while a page loads. Keys typed meanwhile
  are kept and act after it.
- **The Pi's Marionette port is local only.** Any program on the Pi can
  still drive that Firefox, with its sign-ins: fine for a single-user Pi.
- **Not handled yet:** PDFs (Firefox shows them in its own viewer), file
  downloads, frames (shown as `[frame]`), and pop-up windows (opened in the
  one tab).

## Setting up (Pi 5)
1. `sudo apt install firefox` (Raspberry Pi OS ships Firefox; `firefox-esr`
   also works).
2. gridlink as for Term; gridfox sits beside it in `claude-link/` and is
   found without installing.
3. On the GRiD: `CLAUDE /W`.

## Next
- **W2, the picture view.** A key flips to a picture of the same page:
  1. Firefox's screenshot (`WebDriver:TakeScreenshot`), dithered to the
     1520's 640x400.
  2. Only changed tiles are sent, run-length coded, in one new GLP frame
     kind.
  3. A bitmap blitter in CLAUDE.COM, about 1 KB.
  4. The mouse for clicks.
- **W3, Claude Code shares the browser.** Marionette takes one session at a
  time, so gridfox would keep it and offer a small local socket. A
  `grid_browser` MCP tool would then look at and act on the page you have
  open.
- An entry in the Executive for `CLAUDE /W`, as CODE-A is for Claude.
