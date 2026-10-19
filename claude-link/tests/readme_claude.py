#!/usr/bin/env python3
"""A scripted Claude Code screen for the README's screenshots (no model, no
login): fake_claude.py's renderer, opened on a short session at the bench.
It then behaves as fake_claude.py does."""
import os, select, sys, termios, tty
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fake_claude as F

O, D, B, G, R, C = '\x1b[38;5;174m', '\x1b[2m', '\x1b[1m', '\x1b[38;5;114m', '\x1b[22m', '\x1b[39m'
DOT = '\x1b[38;5;231m⏺\x1b[39m'
SESSION = [
    O + '╭' + '─' * 31 + '╮' + C,
    O + '│' + C + ' ' + O + '✻' + C + ' Welcome to ' + B + 'Claude Code' + R + '      ' + O + '│' + C,
    O + '╰' + '─' * 31 + '╯' + C,
    '',
    '> sweep the filter on the 8753D, 300 kHz to 3 GHz, and plot S21',
    '',
    DOT + ' grid - gpib_send (MCP)(action: "write", address: 16, command: "STAR 300KHZ;',
    '                         STOP 3GHZ;POIN 1601;S21;LOGM;SING")',
    '  ⎿  done',
    '',
    DOT + ' grid - gpib_send (MCP)(action: "query", address: 16,',
    '                         command: "FORM4;OUTPFORM", save_to: "s21.txt")',
    '  ⎿  1601 points saved to ~/grid/s21.txt',
    '',
    DOT + ' grid - grid_plot (MCP)(file: "s21.txt", title: "8753D S21", y_label: "dB")',
    '  ⎿  shown on the GRiD',
    '',
    DOT + ' The filter notches at ' + B + '1.50 GHz' + R + ', down to ' + B + '-25.5 dB' + R + '; elsewhere the',
    '  passband loss is 0.5 dB. Want the trace copied to C:\\TRACES on the GRiD?',
    '',
]


def main():
    fd = 0
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    app = F.App()
    try:
        app.w(F.ESC + '[c')
        r, _, _ = select.select([fd], [], [], 1.0)
        if r: os.read(fd, 64)
        app.w(F.ESC + '[?25l' + F.ESC + '[?2004h')
        app.title('✳ Claude Code')
        app.render(SESSION)
        while True:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                data = os.read(fd, 1024)
                if not data: break
                for k in F.split_keys(data): app.key(k)
            app.tick()
    except SystemExit:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == '__main__':
    main()
