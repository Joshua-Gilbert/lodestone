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
  - Pictures load (the picture view shows them; the text view gives their
    `alt` text). `--no-images` leaves them out, for the text view alone:
    they are most of a page's weight, though only the Pi's own network
    carries them, never GPIB.
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
  - `[web] command` in the config sets the program. The default is
    gridlink's own Python (its venv, which has `wcwidth`) with
    `-m gridfox`.

### On the GRiD (`os/claude/CLAUDE.ASM`)
`/W` is `/T` with `app=web` in the HELLO: 32 bytes. With the mouse
(below), CLAUDE.COM is 20,564 bytes. (A check that put "Pi has no /W" on the band was tried and
taken out: 96 bytes for something the band's title already shows.)

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
| A left click | on a link, button or field: uses it (as Tab to it and Return); on the address: Go; in a list's choices: that one; elsewhere: closes what is open |
| . (period) | read the page again, without reloading (nothing is sent again) |
| Ctrl-Q | closes gridfox; Return starts it again |
| CODE-Q | leaves CLAUDE on the GRiD; gridfox and Firefox keep running on the Pi |

**Forms:**
- Return on a text field asks for its text on the bottom row.
- Return there fills it in, then goes on to the form's next field, or sends
  the form after the last one. A password is shown as stars.
- Return on a check box ticks it.
- Return on a list opens its choices: Up/Down, then Return.
- The prompt is the field's `<label>`, else its placeholder or name.

**Pages:** a link to `#section` on the same page scrolls there, as does an
address with a `#fragment`. A page that changes its own address
(`history.pushState`) keeps your place. A closed `<details>` shows only its
summary, as `[+] …`; Return on it opens it.

## The mouse (2026-10-17)
Joshua asked for the mouse the OS already supports in this mode. It uses
the kernel's own INT 33h (`src/MOUSE33.INC`, the serial mouse) as it stands.

- **On the GRiD (CLAUDE.COM; under `/W` only at first, all of Term since the pictures):**
  - When the screen is set up, CLAUDE checks that INT 33h is there (GRiD
    MS-DOS may have no mouse driver), resets it, and shows the pointer. The
    kernel draws it in mode 40h.
  - The key loop asks INT 33h AX=5 for left presses. That function counts
    presses since it was last asked, so a quick click between two polls
    isn't missed.
  - Each press goes to the Pi as EVENT 05h with its cell, 8 x 16 pixels to
    a cell; since the pictures, as EVENT 06h with its pixel. It shares the one-EVENT-at-a-time flag with CODE-R's repaint.
  - After each CELLS frame the pointer is hidden and shown again. Hiding
    puts back only bytes not drawn over since, so the pointer comes back on
    top of the new screen instead of vanishing until the mouse moves.
  - An older gridlink ignores the EVENT. RCON (resident Claude) is unchanged.
    (Plain Term didn't take the mouse at first; since the pictures it does,
    for clicks on plots, and Claude Code still sees no click unless it asks.)
  - **Cost:** 124 bytes of code and data. The `align 16` before the font
    makes it 128 in the file: CLAUDE.COM is 20,564 bytes.
- **gridlink:** EVENT 05h goes to the pty as an xterm mouse report (press,
  then release), in SGR form (`?1006`) or the older X10 form. It goes only
  to a program that turned reports on (`?1000`, `?1002` or `?1003`), so
  Claude Code under `/T` never sees a click. Row 24, CLAUDE's band, isn't
  passed on.
- **gridfox:** turns reports on when it starts (`?1000h ?1006h`) and off
  when it ends.
  - A click on a link, button or field uses it: it is selected first, then
    used as Return would.
  - A click on the address opens Go.
  - A click on one of a list's choices picks it.
  - A click elsewhere closes the choices, the numbers or the line being
    typed. The status line does nothing.
- Left only: Backspace already goes back. A serial Microsoft mouse has no
  wheel.

## The picture view (W2, 2026-10-17)
Joshua asked for "video dithering mode for the full browsing experience".
V shows the page as Firefox draws it; Esc goes back to the text. The text
view stays the default: it is the fast one.

- **Firefox's own pixels:** the viewport becomes 640 x 384, the GRiD's rows
  0-23 (the window is set, then corrected by what Firefox draws around the
  page). gridfox takes a screenshot (`WebDriver:TakeScreenshot`), writes it
  to `view.png` in its folder, and asks for it with `OSC 5150` (PROTOCOL.md,
  section 6). gridlink dithers it and sends it as pixels: Term's picture
  layer, shared with Claude Code's plots (`docs/lodestone-pictures.md`).
  - A light page is shown dark, lit text on a dark screen as the GRiD
    draws; Ctrl-I turns it the other way. The choice is kept while the page
    stays about as light, so it doesn't flicker as you scroll.
  - Text is drawn without antialiasing (a fontconfig file of gridfox's own,
    and `gfx.text.disable-aa`), so it stays crisp after dithering. Not yet
    seen on the Pi.
- **Clicks are real clicks** at that pixel (`WebDriver:PerformActions`):
  anything on the page answers, not only what the text view found. gridfox
  asks for reports in pixels (`?1016`) while the picture is up.
- **Typing goes to the page**, into whatever has the focus: characters,
  Return, Tab, Backspace, Delete, Left and Right. A few keys are gridfox's:

  | Key | Does (picture view) |
  |---|---|
  | Esc | back to the text view |
  | Up / Down | scroll 3 rows (48 pixels) |
  | PgUp / PgDn | scroll 22 rows |
  | Home / End | top, bottom |
  | F6 or Ctrl-L | an address: the text view comes back with its Go line, then the picture of the new page |
  | Ctrl-B / Ctrl-F | back / forward |
  | Ctrl-R | reload |
  | Ctrl-I | light or dark the other way |

- **Scrolling in whole rows** (and `general.smoothScroll` off): the encoder
  sees the picture moved by 16-line rows and sends a scroll op and the new
  strip.
- **Refresh:** a screenshot at once after each action, then at 0.5, 1.5 and
  4 s; while idle, one every 2 s. Only a changed one goes to the GRiD (a
  hash of the PNG), and the encoder sends only the lines that changed.
- **A page that changes by itself** (a video, an animation; seen on the
  1520 with YouTube, about a frame every 1.5 s at the idle pace): while
  each look finds the page changed, the next comes as soon as the GRiD has
  the last picture whole (gridlink says so on the pty, `OSC 5150 ; shown`),
  and at most every 0.25 s: one screenshot a frame the link can carry,
  none wasted on the Pi. The first look that finds the page still goes back
  to the idle pace. These pictures go to
  gridlink as frames (`OSC 5150` flag `frame`): a frame waits until the GRiD
  has the one on its way whole, the newest of those waiting kept. So the
  rate is the link's, every frame arrives whole, and a top that keeps
  changing can't starve the bottom (the encoder works top down). A key or
  a click's picture still goes at once. Firefox's caret doesn't blink
  (`ui.caretBlinkTime` 0), so a text field doesn't count as moving.
- **Only with a GRiD that can:** gridlink tells gridfox (`GRIDLINK_PICTURES`)
  when the GRiD's HELLO says it takes pictures; otherwise V says CLAUDE.COM
  1.2 is needed.
- **Not yet:** a `<select>`'s choices open in a window of Firefox's own,
  which a viewport screenshot doesn't show: use the text view for lists.

## Measured (emulator and GridSim, stand-in Firefox)

| | |
|---|---|
| A new page (the long test page), bytes to the GRiD | 563-587 |
| One screen down | 318-337 |
| At 3.2 KB/s (stock bridge) | about 0.18 s and 0.1 s |
| At 70 KB/s (Pico 2 bridge, measured on the 1520), a round trip included | about 15 ms and 11 ms |
| The picture view: the index page (the stand-in's picture of it) | 2,440 |
| Its next screen (PgDn) / three rows down | 1,914 / 675 |
| A page that changes by itself, in GridSim (a fast link) | 11 whole frames in 3 s, against 2 at the idle pace |

The ranges are runs here and on Joshua's machine. The page's own weight
never crosses GPIB, only the cells that change. How
long Firefox takes on the Pi 5 for a real site is not measured yet.

## Tests

- `claude-link/tests/test_gridfox.py` (25 tests, about 15 s: one stand-in
  Firefox for the whole run):
  - layout and wrapping, the key parser and line editor;
  - the real `extract.js` and `act.js` against a stand-in Firefox;
  - the app key by key: follow, back with the place kept, hints, find;
    a search form, a two-field sign-in (the password not shown), a button
    a script answers, a list, a check box;
  - a page filled in late by script;
  - end to end through gridlink and GridSim, with the byte counts;
  - the review's findings (below): the session's shape, real clicks and the
    fallback, a hostile page, a form not sent early, a slow page, Back from
    help, an error kept, Esc timing, no busy loop while typing, a lost
    Firefox, gridfox's own folder and no API key;
  - Joshua's review (below): `#fragment` links and addresses, `pushState`,
    `<label>`s, `<details>`, Firefox's clean quit, Term's exit line.
- `tests/fake_firefox.py` is the stand-in: a Marionette server whose pages
  are jsdom (`fake_firefox_dom.js`), served from `tests/web/`. It needs Node,
  and `npm ci` in `tests/` (jsdom pinned, `package-lock.json` kept). Without
  them the tests that need it say so and are skipped, in `test_gridfox.py`
  and `test_emu_term.py` alike.
  - It refuses a session asked for in geckodriver's shape, as a real
    Firefox would silently ignore it.
  - It hands out element references and answers ElementClick.
  - It can keep the old page up while a slow one loads.
  - It wants scripts in gridfox's sandbox, kept between calls.
  - It follows a `#fragment` link in the same document, as a browser does.
- `os/tests/test_claude_mouse.py` (22 checks): the real CLAUDE.COM `/W` on
  the Lodestone kernel in pcemu, with its serial mouse and the kernel's
  INT 33h, the real gridlink, and gridfox on the stand-in Firefox.
  - A click on a link follows it, and a click on the address opens Go.
  - With no mouse, `/W` works from the keys.
  - Under plain Term, a click on a plot types its point into Claude Code's
    prompt (`docs/lodestone-pictures.md`).
  - In chat, CLAUDE leaves the mouse alone (no pointer).
- `test_gridfox.py` `test_picture_view` and `test_picture_view_end_to_end`:
  V, the viewport, a pixel click on a link, scrolling, typing into a
  field, the Go line from the picture view, Ctrl-I, Esc back; V refused when gridlink doesn't say the GRiD can show pictures; and through
  gridlink and GridSim, the GRiD's pixels equal to gridlink's picture, with
  the byte counts. The stand-in's screenshot is its page's text drawn with
  Pillow (jsdom lays nothing out), one line of 16 pixels a block or link.
  - `test_term.py` `test_click_only_when_asked` covers gridlink's side:
    nothing reaches a program that asked for no reports, and both report
    forms come out right.
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

## Review (2026-10-17)

An independent review read the change against Firefox's own Marionette
source. Everything it found is fixed and tested where the stand-in can show
it:

- **The session settings were in the wrong shape.** Marionette takes the
  capabilities as the parameters themselves. In geckodriver's
  `{capabilities: {alwaysMatch}}` shape, a real Firefox ignores them without
  a word: no "eager" loads, 300 s page timeouts. Now flat, with alert dialogs
  dismissed (`unhandledPromptBehavior`).
- **A page could hang gridfox.**
  - `<ol start="1e80">` made a marker wider than the screen, and `wrap()`
    looped forever at width 0; `start="Infinity"` crashed it.
  - Now the numbers are clamped (1-99999), any number from the page goes
    through `_int`, and widths have a floor.
- **Control characters from the page could reach the pty.** They came
  through the line editor: a field's value or label could carry `ESC c` or
  `ESC [2J`, and a textarea's new lines scrolled the screen.
  - Both are now cleaned like page text, and a textarea's lines show as `⏎`.
- **A busy loop** while typing with a timed look due (a whole core on the
  Pi). The timed looks now wait while something is being typed.
- **A slow page after a click was missed.** The old page stays up until the
  new one answers.
  - `act.js` now notes `beforeunload`/`pagehide`, so gridfox waits for the
    new page.
  - When idle it checks the address once a second.
  - `.` reads the page again without reloading.
- **No recovery from a lost Firefox.** A timeout or broken stream now marks
  the connection dead (a half-read message can't put it out of step), and
  gridfox ends with code 3. Term then offers Return to start it again.
  Ctrl-Q quits from anywhere. Firefox dies with gridfox (`PR_SET_PDEATHSIG`).
- **gridfox ran in `~/grid`,** where Claude Code writes files. `python3 -m`
  puts that folder first on `sys.path`, so a `json.py` there would have
  been imported.
  - It now runs in `~/.cache/gridfox` (`[web] dir`).
  - It never gets the API key, even with `keep_api_key`.
- **Clicks were script clicks.** Those are untrusted, so pop-up blockers and
  the like may refuse them. Now `WebDriver:ElementClick` (trusted); a script
  click only when that is refused (a covered element).
- **Forms were sent too early.** Return on the last text field sent the form
  even with a check box or list after it. Now only when nothing but buttons
  follows.
- **The page could tamper with gridfox's scripts.** Its globals and the DOM
  built-ins they call were reachable. Scripts now run in a named Marionette
  sandbox.
- **Smaller:**
  - shadow DOM read through its slots;
  - nested tables;
  - menus with `list-style: none` have no bullets;
  - the visually-hidden check also works on pages whose body has height 0;
  - zero-width characters dropped by pyte's own `wcwidth`;
  - downloads go to a temporary folder, not the SD card;
  - Back from help returns to the page without touching Firefox's history;
  - an error opening a page stays on the status line.

## Joshua's review (2026-10-17, on the PR)

"Approve with changes." He ran the suites under WSL and read Firefox ESR
128's Marionette source. That confirmed the flat capabilities (the BiDi
path, `--remote-debugging-port`, is the one that takes the wrapped shape,
and gridfox never uses it) and that the named sandbox is kept between calls.
All of his findings are fixed:

1. **`#section` links threw the reader to the top.** Any change of address
   counted as a new page, and a page changing its own hash or query
   reset the view every second.
   - Now an address that differs only by its fragment, or a document that
     is still the one marked when it loaded (`pushState`), keeps the place.
   - `extract.js` gives each block the ids (and `<a name>`s) that start
     there, so a fragment scrolls to its line.
2. **The emulator suite needed Node.** Without Node and jsdom,
   `test_web_gridfox` (and the browser tests) now say so and are skipped.
   jsdom is pinned (24.1.3), and `package-lock.json` is committed.
3. **Firefox had 1.5 s before SIGKILL.** That is too short to flush cookies
   and the session store on a Pi.
   - Now gridfox asks Firefox to quit as from its menu (`Marionette:Quit`,
     `eAttemptQuit`) and waits up to 8 s.
   - SIGTERM follows only if that fails, and a kill is the last resort.
   - Term waits 15 s for gridfox, so it never kills it first.
4. **Hardening.**
   - `PYTHONSAFEPATH=1` for gridfox, so its folder isn't on `sys.path` at
     all (Python 3.11+).
   - `newSandbox: false` is passed explicitly; the stand-in checks for it.
5. **Form prompts ignored `<label>`.** Fields now read `el.labels` first.
6. **Term's exit line named the interpreter.** It now says "gridfox exited
   (it lost Firefox) (code 3)" rather than "python3 exited".
7. **The tests were slow.** About 6.5 s each, from a node and jsdom per
   test; now one stand-in per run, and the suite takes about 15 s.
8. **Nits.** The test counts are corrected, and PROTOCOL.md's HELLO lists
   `app=web`.

Also from the review: a closed `<details>` showed its contents (Firefox
hides them without `display: none`, inside a shadow tree a script can't
walk). Now only its summary shows, and Return opens it.

## Not yet tried
- **A real Firefox.** Firefox could not be downloaded in the build
  workspace, so the scripts have only run under jsdom.
  - jsdom lays nothing out, so `extract.js` falls back to tag names there.
    In Firefox it uses computed styles, the better path but untested.
  - Untried in particular: the named sandbox with React-style value
    setting, ElementClick, `Marionette:Quit`, and downloads.
- **The first check on the Pi** should drive the page, not only show it:
  1. `~/gridlink/venv/bin/python -m gridfox --console https://example.com`
     in an 80x24 terminal, run from `~/gridlink`;
  2. Tab to a link and Return;
  3. Back;
  4. a form field (fill it in, send it).

  Those paths depend on the sandbox and element references, which jsdom
  can't prove. gridfox's log is `~/.cache/gridfox/gridfox.log`.
- **DuckDuckGo's HTML page sometimes serves a bot check** to headless
  browsers. If the first search shows a near-empty page, that is why;
  `--search` takes another search address (`%s` for the words).
- **Busy waits.** gridfox waits while a page loads. Keys typed meanwhile
  are kept and act after it.
- **The Pi's Marionette port is local only.** Any program on the Pi can
  still drive that Firefox, with its sign-ins: fine for a single-user Pi.
- **Switching apps leaves the other running.** From `/W` to `/T`, Firefox
  stays up beside Claude Code, which matters for a 4 GB Pi.
- **Not handled yet:**
  - PDFs (Firefox shows them in its own viewer);
  - frames (shown as `[frame]`);
  - pop-up windows (opened in the one tab);
  - an action that unloads the page without loading another (some downloads)
    waits up to 20 s.

## Setting up (Pi 5)
1. Get `claude-link/` from this branch onto the Pi and run `bash install.sh`
   there.
   - It copies `gridlink/` and `gridfox/` to `~/gridlink`, adds `wcwidth`
     to the venv, and installs Firefox if it is missing.
   - It keeps your `config.toml`.
2. `sudo systemctl restart gridlink`.
3. On the GRiD: `CLAUDE /W`.

**If `CLAUDE /W` shows Claude Code**, and the band's title says
"Claude Code" instead of a page title, the Pi's gridlink is older than
gridfox (step 1). It doesn't
know `app=web` and falls back to Term. Its log
(`journalctl -u gridlink -n 20`) then says `Term (Claude Code on the Pi)`
where the new one says `web (Firefox on the Pi)`.

The first build of `install.sh` (2026-10-16) left out `gridfox/`, and the
default command used the system Python, which has no `wcwidth`. Both are
fixed.

## Next
- **W2, the picture view.** A key flips to a picture of the same page:
  1. Firefox's screenshot (`WebDriver:TakeScreenshot`), dithered to the
     1520's 640x400.
  2. Only changed tiles are sent, run-length coded, in one new GLP frame
     kind.
  3. A bitmap blitter in CLAUDE.COM, about 1 KB.
  4. The mouse for clicks is in already (text view, 2026-10-17); the
     picture view would use the same EVENT, in pixels.
- **W3, Claude Code shares the browser.** Marionette takes one session at a
  time, so gridfox would keep it and offer a small local socket. A
  `grid_browser` MCP tool would then look at and act on the page you have
  open.
- An entry in the Executive for `CLAUDE /W`, as CODE-A is for Claude.
