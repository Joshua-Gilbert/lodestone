"""PLOT.COM in the emulator, from the command prompt, against a model of the
plotter's Nano on the GPIB bus (tools/sim7210.py): what reaches the Nano
byte for byte, each write within the room its serial poll gave and ending
a whole command (gridlink's hpgl_ends), a command longer than the room in
parts, the Nano full for a while, Esc (the pen up after the last whole
command), the end's wait for idle, and what is refused before anything is
sent, the same files gridlink's hpgl_check refuses.

    python3 tests/test_plot.py
"""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(GOS, '..', 'tools')); sys.path.insert(0, os.path.join(GOS, '..', 'claude-link'))
import ktest, mkimg, sim7210
from gridlink.mcp import hpgl_check, hpgl_ends

OUT = tempfile.mkdtemp()
SRC = os.path.join(GOS, 'src')
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))


class Nano(sim7210.Device):
    """The plotter's Nano (plotter-nano/, firmware v4 on): a serial poll
    says the room in its 240-byte buffer (bits 0-5, 4-byte units) and bit 7
    when it is empty; each poll the pen has drawn `drain` bytes more.  The
    bytes since the last poll are one write (PLOT polls before each)."""
    def __init__(s, addr=1, drain=60, full=0):
        s.addr, s.answers, s.inbuf, s.out = addr, {}, b'', b''
        s.got = bytearray(); s.held = 0; s.seen = 0; s.said = 0
        s.writes = []; s.over = []; s.polls = 0
        s.drain, s.full = drain, full
        s.fixed = None                  # a status byte to give every poll (another device)
    def message(s, msg): s.got += msg               # (at each EOI or LF)
    def data(s): return bytes(s.got) + s.inbuf
    @property
    def status(s):
        n = len(s.got) + len(s.inbuf)
        if n > s.seen:
            w = n - s.seen
            s.writes.append(w)
            if w > s.said: s.over.append((w, s.said))
            s.held += w; s.seen = n
        s.polls += 1
        if s.fixed is not None: return s.fixed
        if s.full:                     # (full and drawing: 0, as the firmware's statusByte gives it)
            s.full -= 1; s.said = 0
            return 0
        else:
            s.held = max(0, s.held - s.drain)
            room = (240 - s.held) // 4 if s.held < 240 else 0
        s.said = room * 4
        return (0x80 if not s.held else 0) | room


def f(name, data):
    p = os.path.join(OUT, name); open(p, 'wb').write(data)
    return '%s=%s' % (name, p)

def boot(files, nano=None, chip=True):
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(SRC, n) for n in ('LODE.SYS', 'LCMD.COM', 'PLOT.COM')]
                      + [f(n, d) for n, d in files])
    devs = {1: nano} if nano else {}
    k = ktest.KPC(img, chip=sim7210.NEC7210(devs) if chip else None)
    k.start(); k.code_p()
    return k

def out(k): return ''.join(k.pc.tty).replace('\r', '\n')

def run(k, line, sim=120, esc_after=None):
    """line at the prompt -> what it printed, and E<exit code>.  esc_after: Esc once the Nano has had that many
    writes"""
    k.pc.tty.clear()
    k.key(line); k.key(ktest.ENTER, settle=False)
    n = k.pc.us + sim * 1e6
    nano = k.pc.chip.devices.get(1) if k.pc.chip else None
    if esc_after:
        k.pc.run_until(lambda: len(nano.writes) >= esc_after, sim)
        k.key(ktest.ESC, settle=False)
    k.pc.run_until(lambda: out(k).rstrip().endswith('A:\\>') and out(k).count('A:\\>') >= 1
                   and len(out(k)) > len(line) + 8, max(1, (n - k.pc.us) / 1e6))
    k.settle(2)
    return out(k), code(k)

def code(k):
    """the exit code of what ran last (0-3), from IF ERRORLEVEL n (n or more)"""
    e = 0
    for c in (1, 2, 3):
        k.pc.tty.clear()
        k.key('if errorlevel %d echo L%d' % (c, c)); k.key(ktest.ENTER)
        if any(l.strip() == 'L%d' % c for l in out(k).split('\n')): e = c
    return e

def ends_ok(nano, data):
    """every write but the last ends a whole command, as gridlink's hpgl_ends marks them"""
    ends = set(hpgl_ends(data)); pos = 0; bad = []
    for w in nano.writes:
        pos += w
        if pos not in ends and pos != len(data): bad.append(pos)
    return bad

LINES = b''.join(b'PU%d,%d;PD%d,%d,%d,%d;\r\n' % (i * 10, i * 7, i * 10 + 300, i * 7, i * 10 + 300, i * 7 + 200)
                 for i in range(400))      # (~12 KB: three of PLOT's 4 KB windows)
DRAWING = b'IN;SP1;\r\n' + LINES + b'PU100,100;SI0.3,0.4;LBHello; GRiD\x03;\r\n' + b'PA0,0;SP0'   # (no ';' at the end)


def t_plot():
    nano = Nano()
    k = boot([('D.PLT', DRAWING)], nano)
    o, e = run(k, 'plot d.plt')
    want = hpgl_check(DRAWING)
    check('PLOT D.PLT: the Nano gets the file byte for byte, a ";" on the end (as gridlink sends it); exit 0',
          nano.data() == want and e == 0, (len(nano.data()), len(want), e, o[-400:]))
    check('... "Plotting %d bytes of HP-GL on the 4662 at GPIB 1", then "Done: %d bytes in n writes"' % (len(want), len(want)),
          ('Plotting %d bytes of HP-GL on the 4662 at GPIB 1' % len(want)) in o and ('Done: %d bytes in %d writes'
          % (len(want), len(nano.writes))) in o, o[-400:])
    check('... no write is more than the room the poll before it gave', not nano.over and len(nano.writes) > 10,
          (nano.over, nano.writes))
    check('... each ends a whole command (gridlink\'s hpgl_ends), the label with its ETX and ";" in one',
          not ends_ok(nano, want), (ends_ok(nano, want), nano.writes))
    check('... at least 64 bytes each but the last', all(w >= 64 for w in nano.writes[:-1]), nano.writes)
    check('... and it waits for the Nano to be idle at the end (polls after the last write)',
          'the pen is finishing' in o and nano.held == 0, o[-300:])

def t_long():
    big = b'IN;PU0,0;PD' + b','.join(b'%d,%d' % (i, i * 3 % 1000) for i in range(300)) + b';PU;'
    nano = Nano()
    k = boot([('BIG.PLT', big)], nano)
    o, e = run(k, 'plot big.plt')
    check('a command of %d bytes (one PD, longer than the most room): sent in parts of the room, all of it, exit 0' % len(big),
          nano.data() == big and e == 0 and not nano.over and max(nano.writes) <= 240, (nano.writes, e, o[-300:]))
    nano = Nano(drain=8)
    k = boot([('BIG.PLT', big)], nano)
    o, e = run(k, 'plot big.plt', esc_after=3)
    d = nano.data()
    check('... Esc while it is in parts: no "PU;" in the middle of the PD (only what was sent of it); exit 1',
          big.startswith(d) and 9 < len(d) < len(big) and e == 1 and 'Stopped' in o, (d[-30:], e, o[-200:]))

def t_full():
    nano = Nano(full=40)
    k = boot([('D.PLT', DRAWING)], nano)
    o, e = run(k, 'plot d.plt')
    check('the Nano full for 40 polls at the start (status 0, still drawing, as after an Esc): PLOT starts all the same, '
          'waits (no write meanwhile), then plots it all; exit 0', 'does not answer' not in o and
          nano.data() == hpgl_check(DRAWING) and e == 0 and nano.polls > 40 and not nano.over, (nano.polls, e, o[-300:]))

LABEL = b'IN;PU0,0;LB' + b'a' * 300 + b';' + b'b' * 300 + b'\x03;PU;PA10,10;'   # (a ';' in a label's text)

def t_label():
    want = hpgl_check(LABEL)
    ends = set(hpgl_ends(want))
    nano = Nano()
    k = boot([('L.PLT', LABEL)], nano)
    o, e = run(k, 'plot l.plt')
    check('a label of 600 bytes with a ";" in its text: sent in parts, all of it; exit 0', nano.data() == want and e == 0
          and not nano.over, (nano.writes, e, o[-300:]))
    # a label of 240 bytes, its ETX the room's last byte: the ';' after it left, then whole commands again
    cut = b'IN;PU0,0;LB' + b'x' * 100 + b';' + b'y' * 127 + b'\x03'
    tail = b''.join(b'PA%d,%d;' % (i, i) for i in range(150))
    cw = hpgl_check(cut + b';' + tail)
    nano = Nano()
    k = boot([('C.PLT', cut + b';' + tail)], nano)
    o, e = run(k, 'plot c.plt')
    check('a label cut just after its ETX (%d bytes, the room\'s last): all of it; the writes after it whole commands again '
          '(gridlink\'s ends), not room-sized parts; exit 0' % len(cut), nano.data() == cw and e == 0
          and not ends_ok(nano, cw)[1:] and len(nano.writes) > 3, (nano.writes, ends_ok(nano, cw), e))
    for n in (1, 2, 3):                 # (its 4th write is its last)
        nano = Nano(drain=8)
        k = boot([('L.PLT', LABEL)], nano)
        o, e = run(k, 'plot l.plt', esc_after=n)
        d = nano.data()
        pu = d.endswith(b'PU;') and (len(d) - 3) in ends and want.startswith(d[:-3])
        check('... Esc after %d writes: "PU;" only after a whole command, never in the label\'s text (%d bytes, %s); exit 1'
              % (n, len(d), 'PU;' if pu else 'no PU;'), (pu or want.startswith(d)) and len(d) < len(want) and e == 1
              and 'Stopped' in o and not nano.over, (d[-30:], e, nano.over))

def t_esc():
    nano = Nano(drain=8)
    k = boot([('D.PLT', DRAWING)], nano)
    o, e = run(k, 'plot d.plt', esc_after=4)
    d = nano.data()
    ends = set(hpgl_ends(hpgl_check(DRAWING)))
    check('Esc part-way: "Stopped: n of %d bytes sent", the pen up ("PU;") after the last whole command; exit 1'
          % len(hpgl_check(DRAWING)), 'Stopped: ' in o and d.endswith(b'PU;') and (len(d) - 3) in ends
          and DRAWING.startswith(d[:-3]) and len(d) < len(DRAWING) and e == 1, (d[-40:], e, o[-300:]))
    check('... the "PU;" sent within the room a poll gave (not held on the bus)', not nano.over, nano.over)
    nano = Nano(drain=8)
    k = boot([('D.PLT', DRAWING)], nano)
    k.pc.tty.clear()
    k.key('plot d.plt'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: len(nano.writes) >= 4, 60)
    k.key(0x2E03, settle=False)          # (^C, typed)
    k.pc.run_until(lambda: 'Stopped' in out(k), 30); k.settle(2)
    o = out(k); d = nano.data()
    check('^C part-way: stopped as Esc stops it, "PU;" after a whole command; exit 1', 'Stopped: ' in o and d.endswith(b'PU;')
          and (len(d) - 3) in ends and code(k) == 1, (d[-40:], o[-300:]))

def t_bridge():
    nano = Nano(); nano.fixed = 0x60     # (RQS and a frame waiting: what the Claude bridge says)
    k = boot([('D.PLT', DRAWING)], nano)
    o, e = run(k, 'plot d.plt', sim=20)
    check('an address that asks for service (the bridge): "GPIB 1 asks for service: it is not the Nano"; nothing sent; exit 2',
          'GPIB 1 asks for service: it is not the Nano' in o and not nano.data() and e == 2, (e, o[-300:]))

def t_stall():
    nano = Nano(full=10 ** 9)
    k = boot([('D.PLT', DRAWING)], nano)
    t0 = k.pc.us
    o, e = run(k, 'plot d.plt', sim=260)
    s = (k.pc.us - t0) / 1e6
    check('the Nano never has room: "the Nano had no room for 200 s", nothing sent; exit 3 (after %.0f s)' % s,
          'the Nano had no room for 200 s.  Nothing was sent.' in o and 'paper' not in o and not nano.data()
          and e == 3 and 195 < s < 240, (e, s, o[-300:]))
    nano = Nano(drain=8)
    k = boot([('D.PLT', DRAWING)], nano)
    k.pc.tty.clear()
    k.key('plot d.plt'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: len(nano.writes) >= 3, 60)
    del k.pc.chip.devices[1]            # (unplugged: every poll times out)
    n = len(nano.data())
    k.pc.run_until(lambda: 'stopped answering' in out(k), 260)
    k.settle(2)
    o = out(k); e = code(k)
    check('the Nano gone part-way: "the Nano stopped answering serial polls", "%d of ... part of the drawing may be on the '
          'paper"; exit 3' % n, 'the Nano stopped answering serial polls' in o and ('%d of %d bytes sent; part of the drawing'
          % (n, len(hpgl_check(DRAWING)))) in o and e == 3, (e, o[-300:]))

def t_refused():
    """refused before anything is sent: the Nano not even polled"""
    cases = [('BEL.PLT', b'IN;PA1,2;\x07PD;', 'byte 07h at 9 is not HP-GL'),
             ('HI.PLT', b'IN;\xb0;', 'byte B0h at 3 is not HP-GL'),
             ('OPEN.PLT', b'IN;LBno end;PU;', 'a label (LB, BL or WD) has no ETX'),
             ('OPEN2.PLT', b'IN;\x03 bl', 'a label (LB, BL or WD) has no ETX'),
             ('OPEN3.PLT', b'IN;WDhello;PU;', 'a label (LB, BL or WD) has no ETX'),
             ('EMPTY.PLT', b' ;\r\n;\t', 'there is no HP-GL in the file')]
    for n, d, _ in cases:
        try: hpgl_check(d); g = 'sent'
        except ValueError: g = 'refused'
        check('%r: gridlink\'s hpgl_check refuses it too' % d, g == 'refused')
    nano = Nano()
    k = boot([(n, d) for n, d, _ in cases], nano)
    for n, d, msg in cases:
        o, e = run(k, 'plot ' + n.lower(), sim=20)
        check('PLOT %s: "%s"; exit 2' % (n, msg), msg in o and e == 2, (e, o[-300:]))
    for line, msg in (('plot', 'PLOT file [/A:n]'), ('plot a b', 'PLOT file [/A:n]'), ('plot x.plt /b', 'PLOT file [/A:n]'),
                      ('plot x.plt /a:31', 'PLOT file [/A:n]'), ('plot x.plt /a:', 'PLOT file [/A:n]'),
                      ('plot x.plt /a:21', 'that is the GRiD\'s own GPIB address'),
                      ('plot nosuch.plt', 'the file can\'t be opened')):
        o, e = run(k, line, sim=20)
        check('%s: "%s"; exit 2' % (line.upper(), msg), msg in o and e == 2, (e, o[-300:]))
    check('... and the Nano had nothing, not even a serial poll', nano.polls == 0 and not nano.data(), nano.polls)

def t_accepted():
    """what gridlink's check passes, PLOT plots as it would: the 4662's own commands, labels' controls, a ';' added"""
    for d in (b'IN;\x1bA\x56;SP1;', b'LBab\x08\x0e\x0fc\x03', b'IN;SP1;PU', b'pa1,2;lbx\x03;wd\x03'):
        nano = Nano()
        k = boot([('A.PLT', d)], nano)
        o, e = run(k, 'plot a.plt', sim=30)
        check('%r: plotted as hpgl_check gives it (%r); exit 0' % (d, hpgl_check(d)), nano.data() == hpgl_check(d) and e == 0,
              (nano.data(), e, o[-300:]))

def t_address():
    nano = Nano(addr=5)
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(SRC, n) for n in ('LODE.SYS', 'LCMD.COM', 'PLOT.COM')]
                      + [f('D.PLT', b'IN;PU;')])
    k = ktest.KPC(img, chip=sim7210.NEC7210({5: nano})); k.start(); k.code_p()
    o, e = run(k, 'plot d.plt', sim=30)
    check('no Nano at GPIB 1: "the Nano at GPIB 1 does not answer a serial poll ... Nothing was sent"; exit 2',
          'the Nano at GPIB 1 does not answer a serial poll' in o and 'Nothing was sent' in o and e == 2 and not nano.data(),
          (e, o[-300:]))
    o, e = run(k, 'plot d.plt /A:5', sim=30)
    check('/A:5: plotted there; exit 0', nano.data() == b'IN;PU;' and e == 0, (nano.data(), e, o[-300:]))

def t_nogpib():
    k = boot([('D.PLT', b'IN;')], chip=False)
    o, e = run(k, 'plot d.plt', sim=20)
    check('no GPIB (no 7210, so no INT 60h driver): "there is no GPIB driver"; exit 2', 'there is no GPIB driver' in o and e == 2,
          (e, o[-300:]))


if __name__ == '__main__':
    only = sys.argv[1:]
    for t in (t_plot, t_long, t_full, t_label, t_esc, t_bridge, t_stall, t_refused, t_accepted, t_address, t_nogpib):
        if not only or t.__name__ in only: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed' % (len(results), len(bad)))
    sys.exit(1 if bad else 0)
