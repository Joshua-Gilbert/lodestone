#!/usr/bin/env python3
"""A stand-in for Claude Code in a pty, for Term's tests (no model, no login).

It draws the way Claude Code's renderer does: a static part that is written
once and scrolls away, and a live part at the bottom (spinner, prompt box,
dialogs) redrawn in place with cursor-up and erase-line, each frame inside
synchronised output (?2026).  It asks the terminal for DA1 at start, sets
the window title, uses 256-colour and background colours, bracketed paste,
and the alternate screen for /pager.

With --full it draws as Claude Code 2.1 does instead: the logo (the
mascot) at the top, the prompt box pinned to the bottom of the terminal,
the screen laid out again for its rows at SIGWINCH (Full, below).

Prompts it understands:
    run CMD     a permission dialog, then "Bash(CMD)" with a result
    big         60 lines of output at once (scrolling)
    diff        a diff with red/green backgrounds
    slow        an answer streamed word by word for a few seconds
    /pager      the alternate screen until q
    /exit       exits (code 0)
    anything else: a short answer
"""
import os, select, signal, sys, termios, time, tty

W = 80
ESC = '\x1b'
SPIN = '·✢✳✶✻✽'
MODES = ['', '⏵⏵ accept edits on (shift+tab to cycle)', '⏸ plan mode on (shift+tab to cycle)']


class App:
    def __init__(s):
        s.welcome = []; s.resized = False                  # (SIGWINCH: drawn again whole, as Ink does)
        s.inp = ''; s.live_h = 0; s.mode = 0; s.spin = None; s.dialog = None
        s.status = ''; s.history = []; s.ctrl_c = 0; s.stream = None
        s.out = sys.stdout.buffer

    def w(s, text):
        s.out.write(text.encode('utf-8')); s.out.flush()

    # ---- the live area ------------------------------------------------------
    def live_lines(s):
        L = []
        if s.spin is not None:
            L.append('\x1b[38;5;174m%s\x1b[39m %s… \x1b[2m(esc to interrupt)\x1b[22m'
                     % (SPIN[s.spin % 6], s.status or 'Thinking'))
            L.append('')
        if s.dialog:
            L += s.dialog_lines()
        else:
            L.append('\x1b[38;5;246m╭' + '─' * (W - 2) + '╮\x1b[39m')
            lines = s.inp.split('\n')
            for i, t in enumerate(lines):
                pre = '> ' if i == 0 else '  '
                cur = '\x1b[7m \x1b[27m' if i == len(lines) - 1 else ''
                body = pre + t
                L.append('\x1b[38;5;246m│\x1b[39m ' + body + cur + ' ' * max(0, W - 4 - len(body) - (1 if cur else 0))
                         + ' \x1b[38;5;246m│\x1b[39m')
            L.append('\x1b[38;5;246m╰' + '─' * (W - 2) + '╯\x1b[39m')
            hint = '  \x1b[2m? for shortcuts\x1b[22m'
            m = MODES[s.mode]
            L.append(hint + ' ' * max(1, W - 17 - len(m) - 1) + ('\x1b[38;5;105m' + m + '\x1b[39m' if m else ''))
        return L

    def dialog_lines(s):
        cmd, sel = s.dialog
        L = ['\x1b[38;5;174m╭' + '─' * (W - 2) + '╮\x1b[39m',
             '│ \x1b[1mBash command\x1b[22m' + ' ' * (W - 15) + '│',
             '│   ' + cmd + ' ' * (W - 5 - len(cmd)) + '│',
             '│ Do you want to proceed?' + ' ' * (W - 26) + '│']
        for i, o in enumerate(["Yes", "Yes, and don't ask again for this command", "No, and tell Claude what to do differently"]):
            mark = '\x1b[38;5;105m❯\x1b[39m' if i == sel else ' '
            t = ' %s %d. %s' % (mark, i + 1, o)
            L.append('│' + t + ' ' * (W - 2 - len(' x %d. %s' % (i + 1, o))) + '│')
        L.append('\x1b[38;5;174m╰' + '─' * (W - 2) + '╯\x1b[39m')
        return L

    def render(s, static=()):
        """Erase the live area, write new static lines, draw the live area."""
        buf = ESC + '[?2026h'
        if s.live_h:
            buf += (ESC + '[2K' + ESC + '[1A') * (s.live_h - 1) + ESC + '[2K' + ESC + '[G'
        for line in static:
            buf += line + '\r\n'
        lines = s.live_lines()
        buf += '\r\n'.join(lines)
        s.live_h = len(lines)
        buf += ESC + '[?2026l'
        s.w(buf)

    # ---- answers ------------------------------------------------------------
    def answer(s, text):
        words = text.split(' ')
        line = '\x1b[38;5;231m⏺\x1b[39m '; out = []
        for wd in words:
            if len(line) - 15 + len(wd) > W - 4:
                out.append(line); line = '  '
            line += wd + ' '
        out.append(line)
        return out

    def submit(s):
        text = s.inp.strip(); s.inp = ''
        if not text: s.render(); return
        s.history.append(text)
        echo = ['\x1b[48;5;237m> ' + text.replace('\n', '\r\n  ') + '\x1b[49m', '']
        if text == '/exit':
            s.render(echo); s.w('\r\n'); raise SystemExit(0)
        if text == '/pager':
            s.render(echo); s.pager(); return
        if text.startswith('run '):
            s.render(echo)
            s.dialog = [text[4:], 0]; s.render(); return
        s.spin = 0; s.status = 'Thinking'; s.render(echo)
        for _ in range(3):
            time.sleep(0.12); s.spin += 1; s.render()
        if text == 'big':
            s.spin = None
            s.render(['\x1b[38;5;231m⏺\x1b[39m Here are 60 lines:'] +
                     ['  line %02d: %s' % (i, 'abcdefghij' * (i % 7)) for i in range(60)] + [''])
        elif text == 'diff':
            s.spin = None
            s.render(['\x1b[38;5;231m⏺\x1b[39m \x1b[1mUpdate\x1b[22m(CONFIG.C)',
                      '  ⎿  Updated CONFIG.C with 1 addition and 1 removal',
                      '       12   int main(void) {',
                      '       13 \x1b[48;5;52m-   int rate = 1;            \x1b[49m',
                      '       13 \x1b[48;5;22m+   int rate = 5;            \x1b[49m',
                      '       14   return rate;', ''])
        elif text == 'slow':
            s.stream = s.answer('This answer arrives slowly, a word at a time, the way a long reply '
                                'streams in from the model while the spinner keeps turning below it. ' * 3)
            s.render()
            return
        else:
            s.spin = None
            s.render(s.answer('You said: %s. That is all this fake Claude Code knows how to say.' % text) + [''])
        s.title('Claude Code')

    def run_cmd(s, cmd, allowed):
        s.dialog = None
        if not allowed:
            s.render(['\x1b[38;5;231m⏺\x1b[39m Bash(%s)' % cmd, '  ⎿  \x1b[38;5;203mUser rejected\x1b[39m', ''])
            return
        s.spin = 0; s.status = 'Running'; s.render()
        time.sleep(0.15); s.spin = None
        s.render(['\x1b[38;5;231m⏺\x1b[39m Bash(%s)' % cmd, '  ⎿  ran %s' % cmd, ''])

    def pager(s):
        s.w(ESC + '[?1049h' + ESC + '[H' + 'PAGER: alternate screen\r\n' +
            '\r\n'.join('page line %d' % i for i in range(20)) + '\r\n(q to quit)')
        while True:
            k = os.read(0, 16)
            if k.startswith(b'q'): break
        s.w(ESC + '[?1049l')
        s.render()

    def title(s, t):
        s.w(ESC + ']0;' + t + '\x07')

    # ---- keys -----------------------------------------------------------
    def key(s, k):
        if s.dialog:
            if k in (b'\x1b[A', b'\x1bOA'): s.dialog[1] = max(0, s.dialog[1] - 1); s.render()
            elif k in (b'\x1b[B', b'\x1bOB'): s.dialog[1] = min(2, s.dialog[1] + 1); s.render()
            elif k in (b'1', b'2', b'3'): s.run_cmd(s.dialog[0], k != b'3')
            elif k == b'\r': s.run_cmd(s.dialog[0], s.dialog[1] != 2)
            elif k == b'\x1b': s.run_cmd(s.dialog[0], False)
            return
        if k == b'\x03':
            if s.inp: s.inp = ''; s.render(); return
            s.ctrl_c += 1
            if s.ctrl_c >= 2: raise SystemExit(0)
            s.render(['\x1b[2mPress Ctrl-C again to exit\x1b[22m']); return
        s.ctrl_c = 0
        if k == b'\x1b':
            if s.stream is not None or s.spin is not None:
                s.stream = None; s.spin = None
                s.render(['  ⎿  \x1b[38;5;203mInterrupted by user\x1b[39m', ''])
            return
        if k == b'\x1b[Z': s.mode = (s.mode + 1) % 3; s.render(); return
        if k in (b'\x1b\r', b'\\\r'):
            s.inp = s.inp.rstrip('\\') + '\n'; s.render(); return
        if k == b'\r': s.submit(); return
        if k in (b'\x7f', b'\x08'): s.inp = s.inp[:-1]; s.render(); return
        if k in (b'\x1b[A', b'\x1bOA') and s.history: s.inp = s.history[-1]; s.render(); return
        if k.startswith(b'\x1b[200~'):
            s.inp += k[6:].split(b'\x1b[201~')[0].decode('utf-8', 'replace'); s.render(); return
        if k.startswith(b'\x1b'): return
        t = k.decode('utf-8', 'replace')
        if t.isprintable(): s.inp += t; s.render()

    def tick(s):
        if s.resized:
            s.resized = False; s.live_h = 0
            s.w(ESC + '[2J' + ESC + '[H'); s.render(s.welcome); return
        if s.stream is not None:
            if s.stream:
                line = s.stream.pop(0)
                s.spin = (s.spin or 0) + 1; s.status = 'Writing'
                s.render([line])
            else:
                s.stream = None; s.spin = None; s.render([''])
        elif s.spin is not None:
            s.spin += 1; s.render()


class Full:
    """Claude Code 2.1's look: the logo with the mascot in rows 1-3, what was
    said under it, the prompt box pinned to the bottom (its input rows - 4),
    the hidden cursor there; all drawn again for the terminal's rows when
    it changes (SIGWINCH).  Enter: "You said: ..."; /exit ends it."""
    LOGO = [' \u2590\u259b\u2588\u2588\u2588\u259c\u258c   Claude Code (fake, full)',
            '\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598  rows: %d',
            '  \u2598\u2598 \u259d\u259d    ~/grid']

    def __init__(s):
        s.inp = ''; s.said = []; s.out = sys.stdout.buffer; s.resized = False

    def w(s, text):
        s.out.write(text.encode('utf-8')); s.out.flush()

    def rows(s):
        try: return os.get_terminal_size(0).lines
        except OSError: return 24

    def render(s):
        n = s.rows()
        b = ESC + '[?2026h' + ESC + '[2J'
        put = lambda r, t: ESC + '[%d;1H' % (r + 1) + t
        for i, t in enumerate(s.LOGO): b += put(1 + i, t % n if '%d' in t else t)
        room = max(0, n - 10)                          # (rows 5 .. n - 6)
        for i, t in enumerate(s.said[-room:] if room else []): b += put(5 + i, t)
        b += put(n - 5, '\u2500' * W) + put(n - 4, '\u276f ' + s.inp) + put(n - 3, '\u2500' * W)
        b += put(n - 2, '  ? for shortcuts') + ESC + '[%d;%dH' % (n - 3, 3 + len(s.inp))
        s.w(b + ESC + '[?2026l')

    def key(s, k):
        if k in (b'\r', b'\n'):
            t = s.inp.strip(); s.inp = ''
            if t == '/exit': raise SystemExit(0)
            if t: s.said.append('You said: ' + t)
        elif k in (b'\x7f', b'\x08'):
            s.inp = s.inp[:-1]
        else:
            t = k.decode('utf-8', 'replace')
            if t.isprintable(): s.inp += t
        s.render()

    def tick(s):
        if s.resized:
            s.resized = False; s.render()


def split_keys(data):
    """One read may hold several keys; escape sequences stay whole."""
    out = []; i = 0
    while i < len(data):
        if data[i:i + 6] == b'\x1b[200~':
            j = data.find(b'\x1b[201~', i)
            j = len(data) if j < 0 else j + 6
            out.append(data[i:j]); i = j
        elif data[i] == 0x1b and i + 1 < len(data) and data[i + 1] in b'[O':
            j = i + 2
            while j < len(data) and not (0x40 <= data[j] <= 0x7e): j += 1
            out.append(data[i:j + 1]); i = j + 1
        elif data[i] == 0x1b and i + 1 < len(data) and data[i + 1] == 0x0d:
            out.append(data[i:i + 2]); i += 2
        else:
            out.append(data[i:i + 1]); i += 1
    return out


def main():
    fd = 0
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    app = Full() if '--full' in sys.argv else App()
    signal.signal(signal.SIGWINCH, lambda *a: setattr(app, 'resized', True))
    try:
        app.w(ESC + '[c')                              # DA1: wait for the answer (Ink does)
        r, _, _ = select.select([fd], [], [], 1.0)
        da = os.read(fd, 64) if r else b''
        app.w(ESC + '[?25l' + ESC + '[?2004h')
        if isinstance(app, Full):
            app.render()
        else:
            app.title('✳ Claude Code')
            app.welcome = ['\x1b[38;5;174m╭───────────────────────────────────────────╮\x1b[39m',
                    '\x1b[38;5;174m│\x1b[39m \x1b[38;5;174m✻\x1b[39m Welcome to \x1b[1mClaude Code\x1b[22m (fake)                 \x1b[38;5;174m│\x1b[39m',
                    '\x1b[38;5;174m│\x1b[39m   cwd: ~/grid    terminal: %-15s \x1b[38;5;174m│\x1b[39m' % ('DA ok' if da.startswith(b'\x1b[?') else 'no DA'),
                    '\x1b[38;5;174m│\x1b[39m   api key: %-30s \x1b[38;5;174m│\x1b[39m' % ('SET' if os.environ.get('ANTHROPIC_API_KEY') else 'none'),
                    '\x1b[38;5;174m╰───────────────────────────────────────────╯\x1b[39m', '']
            app.render(app.welcome)
        while True:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                data = os.read(fd, 1024)
                if not data: break
                for k in split_keys(data): app.key(k)
            else:
                app.tick()
    except SystemExit as e:
        return e.code or 0
    finally:
        app.w(ESC + '[?25h' + ESC + '[?2004l')
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == '__main__':
    sys.exit(main())
