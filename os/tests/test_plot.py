"""PLOT.COM in the emulator, from the command prompt, against a model of the
plotter's Nano on the GPIB bus (tools/sim7210.py): what reaches the Nano
byte for byte, each write within the room its serial poll gave and ending
a whole command (gridlink's hpgl_ends), a command longer than the room in
parts, the Nano full for a while, Esc (the pen up after the last whole
command), the end's wait for idle, and what is refused before anything is
sent, the same files gridlink's hpgl_check refuses.

    python3 tests/test_plot.py
"""
import os, struct, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(GOS, '..', 'tools')); sys.path.insert(0, os.path.join(GOS, '..', 'claude-link'))
import ktest, mkimg, sim7210
from gridlink.mcp import hpgl_check, hpgl_ends, hpgl_label

OUT = tempfile.mkdtemp()
SRC = os.path.join(GOS, 'src')
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))


class Chip(sim7210.NEC7210):
    """sim7210's 7210 and bus, and a Selected Device Clear (SDC, 04h): the
    addressed listeners' clear()"""
    refuse = False                      # True: data bytes to the bus aren't taken (a write fails)
    def cdor(s, v):
        if s.atn and s.cic and v == 0x04:
            for a in s.listeners:
                if hasattr(s.devices.get(a), 'clear'): s.devices[a].clear()
        if s.refuse and not s.atn and s.chip_talks(): s.errlatch = True; return
        return sim7210.NEC7210.cdor(s, v)


class Nano(sim7210.Device):
    """The plotter's Nano (plotter-nano/, firmware v4 on): a serial poll
    says the room in its 240-byte buffer (bits 0-5, 4-byte units) and bit 7
    when it is empty; each poll the pen has drawn `drain` bytes more.  The
    bytes since the last poll are one write (PLOT polls before each).  A
    Selected Device Clear empties its buffer (v7.7: old=False), or is
    ignored (v7.6: old=True); `clears` has where each came in the bytes.
    stuck: never idle (left in a label: cmdLen > 0) until a clear it takes.
    `wheld`: what it still held as each write came.  block: polls its ring
    stands still, bytes in it (waiting on the plotter's status reply);
    busy: polls it is still drawing a label it took whole (ring empty, not
    idle; a clear it takes stops that)."""
    def __init__(s, addr=1, drain=60, full=0, old=False, held=0, stuck=False, block=0, busy=0):
        s.addr, s.answers, s.inbuf, s.out = addr, {}, b'', b''
        s.got = bytearray(); s.held = held; s.seen = 0; s.said = 0
        s.writes = []; s.over = []; s.polls = 0; s.clears = []; s.wheld = []
        s.drain, s.full, s.old, s.stuck = drain, full, old, stuck
        s.block, s.busy, s.cut = block, busy, None   # (cut: polls of drawing a clear stopped)
        s.fixed = None                  # a status byte to give every poll (another device)
    def message(s, msg): s.got += msg               # (at each EOI or LF)
    def data(s): return bytes(s.got) + s.inbuf
    def took(s):
        n = len(s.got) + len(s.inbuf)
        if n > s.seen:
            w = n - s.seen
            s.writes.append(w)
            if w > s.said: s.over.append((w, s.said))
            s.wheld.append(s.held); s.held += w; s.seen = n
    def clear(s):
        s.took(); s.clears.append(s.seen)
        if not s.old:
            if s.busy: s.cut = s.busy
            s.held = 0; s.stuck = False; s.busy = 0
    @property
    def status(s):
        s.took()
        s.polls += 1
        if s.fixed is not None: return s.fixed
        if s.full:                     # (full and drawing: 0, as the firmware's statusByte gives it)
            s.full -= 1; s.said = 0
            return 0
        if s.block: s.block -= 1
        else: s.held = max(0, s.held - s.drain)
        room = (240 - s.held) // 4 if s.held < 240 else 0
        busy = s.busy > 0
        if busy: s.busy -= 1
        s.said = room * 4
        return (0x80 if not s.held and not s.stuck and not busy and not s.inhand() else 0) | room
    def inhand(s):
        """a command in hand (statusByte's cmdLen > 0: never idle), from the bytes since the last clear it took"""
        d = s.data()[s.clears[-1] if s.clears and not s.old else 0:]
        return nano_parse(d, hand=True) if d else False


def nano_parse(data, hand=False):
    """The Nano's parser (feedChar, plotter-nano/) over data, as firmware
    that a clear doesn't reset has it: (still in a label at the end, the
    mnemonics it took, in order); hand: whether a command is in hand at
    the end (cmdLen > 0, coordinates or a label)"""
    lab = coords = charg = False; cmd = bytearray(); nat = nl = last = 0; cmds = []
    NAT_MAX = 32
    def end():
        nonlocal lab, coords
        if coords: coords = False; cmd.clear(); return
        if len(cmd) >= 2: cmds.append(bytes(cmd[:2]).upper())
        cmd.clear(); lab = False
    def put(c):                         # (natPut: at most NAT_MAX kept)
        nonlocal nl, last
        if nl < NAT_MAX: nl += 1; last = c
    dig = lambda c: 48 <= c <= 57
    for c in data:
        if nat:                         # (natChar: one of the 4662's own commands)
            if nat == 1: put(c); nat = 2 if 65 <= c <= 68 else 0; continue
            if nat == 2:
                put(c); nat = 3 if c == 66 else 0 if c == 0 or c in b'EF(NQVMKL' else 4 if c in b'USR' else 5; continue
            if nat == 3: put(c); nat = 5; continue
            if nat == 4: put(c); nat = 0; continue
            p = last if nl else 0       # (numbers: E only after a digit, an exponent)
            if (dig(c) or c in b'+-. ,' or (c in b'Ee' and dig(p))) and nl < NAT_MAX: put(c); continue
            nat = 0
            if c in (0x1A, 59): continue
        if lab:
            if c == 3: end()
            elif len(cmd) < 255: cmd.append(c)
            continue
        if c == 0x1B:
            if cmd or coords: end()
            nl = 0; nat = 1; put(c); continue
        if c == 0x1A: continue
        if c == 59: end(); continue
        if 97 <= (c | 0x20) <= 122 and len(cmd) >= 2 + charg: end()
        if coords: continue
        if c < 32 or c > 126 or (c == 32 and not cmd): continue
        if len(cmd) < 255: cmd.append(c)
        if len(cmd) == 2:
            m = bytes(cmd).upper(); charg = m in (b'SM', b'DT')
            if m in (b'LB', b'BL', b'WD'): lab = True
            elif m in (b'PU', b'PD', b'PA'): cmds.append(m); coords = True
    if hand: return bool(lab or coords or cmd)
    return lab, cmds

def stop_ok(nano, want, ends):
    """After Esc: the file's start reached the Nano, then a clear, then the pen-up bytes: "PU;" after a whole command
    (gridlink's hpgl_ends), or ETX and "PU;" with the Nano in a label's text; and the Nano (no reset at the clear) out
    of any label, PU the last thing it took"""
    d = nano.data(); lab, cmds = nano_parse(d)
    for pu, inl in ((b'\x03PU;', True), (b'PU;', False)):
        h = d[:-len(pu)]
        if d.endswith(pu) and want.startswith(h) and nano.clears[-1:] == [len(h)]:
            return nano_parse(h)[0] == inl and (inl or len(h) in ends) and not lab and cmds[-1:] == [b'PU']
    return False


def f(name, data):
    p = os.path.join(OUT, name); open(p, 'wb').write(data)
    return '%s=%s' % (name, p)

def boot(files, nano=None, chip=True):
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(SRC, n) for n in ('LODE.SYS', 'LCMD.COM', 'PLOT.COM')]
                      + [f(n, d) for n, d in files])
    devs = {1: nano} if nano else {}
    k = ktest.KPC(img, chip=Chip(devs) if chip else None)
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
    check('... the Nano idle at the start: no clear (an idle Nano is in no label), none at all; no "still busy"',
          nano.clears == [] and 'still busy' not in o, (nano.clears, o[:300]))

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
    check('... Esc while it is in parts: no "PU;" in the middle of the PD (only what was sent of it, the clear after it); exit 1',
          big.startswith(d) and 9 < len(d) < len(big) and e == 1 and 'Stopped' in o and nano.clears[-1:] == [len(d)],
          (d[-30:], e, nano.clears, o[-200:]))
    # a long PA list with a label after it in the same command: Esc in the numbers, no ETX (it would end a half number)
    pal = b'IN;PA' + b','.join(b'%d,%d' % (i, i * 7 % 1000) for i in range(120)) + b'LBxy\x03;PU;'
    nano = Nano(drain=8)
    k = boot([('PAL.PLT', pal)], nano)
    o, e = run(k, 'plot pal.plt', esc_after=1)
    d = nano.data()
    check('a PA list of %d bytes, a label at its end: Esc in the list: no ETX and no "PU;" (only what was sent of it); exit 1'
          % len(pal), pal.startswith(d) and b'\x03' not in d and 9 < len(d) < pal.index(b'LB') and e == 1
          and nano.clears[-1:] == [len(d)], (d[-30:], e, nano.clears))

def t_full():
    nano = Nano(full=40)
    k = boot([('D.PLT', DRAWING)], nano)
    o, e = run(k, 'plot d.plt')
    check('the Nano full for 40 polls at the start (status 0, still drawing, as after an Esc): PLOT starts all the same, '
          'waits (no write meanwhile), then plots it all; exit 0', 'does not answer' not in o and
          nano.data() == hpgl_check(DRAWING) and e == 0 and nano.polls > 40 and not nano.over, (nano.polls, e, o[-300:]))
    check('... "The plotter is still busy.  Waiting for it (Esc: plot now)." and no clear',
          'The plotter is still busy.  Waiting for it (Esc: plot now).' in o and nano.clears == [],
          (nano.clears, o[:400]))

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
    for old in (False, True):           # (firmware that takes the clear, v7.7, and one that ignores it, v7.6)
        for n in (1, 2, 3):             # (its 4th write is its last)
            nano = Nano(drain=8, old=old)
            k = boot([('L.PLT', LABEL)], nano)
            o, e = run(k, 'plot l.plt', esc_after=n)
            d = nano.data()
            check('... Esc after %d writes (%s): the clear, then ETX and "PU;" in the label\'s text, "PU;" after a whole '
                  'command (%d bytes, ending %r); the Nano out of the label; exit 1' % (n, 'v7.6' if old else 'v7.7',
                  len(d), d[-4:]), stop_ok(nano, want, ends) and len(d) < len(want) + 4 and e == 1 and 'Stopped' in o
                  and 'could not be sent' not in o and not nano.over, (d[-30:], e, nano.clears, nano.over))
    # no room for the pen-up (the Nano not drawing): with v7.6 the clear frees nothing, so ETX and "PU;" can't go
    for old in (False, True):
        nano = Nano(drain=0, old=old)
        k = boot([('L.PLT', LABEL)], nano)
        o, e = run(k, 'plot l.plt', esc_after=1)
        d = nano.data()
        if old:
            check('... Esc in the text, no room (v7.6, the clear ignored): no ETX, no "PU;"; "Stopped: n of %d bytes sent.", '
                  '"The pen-up could not be sent ...", "... still in a label ... switch the Nano off and on"; exit 1'
                  % len(want), want.startswith(d) and nano_parse(d)[0] and 'Stopped: %d of %d bytes sent.  What the Nano still holds may draw.\n' % (len(d),
                  len(want)) in o and 'The pen-up could not be sent: the Nano had no room for it, or the write failed.' in o
                  and 'it is still in a label' in o and 'switch the Nano off and on' in o and e == 1, (d[-10:], e, o[-400:]))
        else:
            check('... the same with v7.7 (the clear frees its room): the clear, ETX and "PU;"; nothing more said; exit 1',
                  stop_ok(nano, want, ends) and d.endswith(b'\x03PU;') and 'could not be sent' not in o
                  and 'still draws' not in o and e == 1, (d[-10:], e, o[-400:]))
    for mn in (b'BL', b'WD'):           # (the same label as BL and WD: text to an ETX too)
        lab = LABEL.replace(b'LB', mn)
        want = hpgl_check(lab); ends = set(hpgl_ends(want)); semi = lab.index(b';', 11) + 1
        nano = Nano()
        k = boot([('L.PLT', lab)], nano)
        o, e = run(k, 'plot l.plt')
        at = [sum(nano.writes[:i + 1]) for i in range(len(nano.writes))]
        check('%s with a ";" in its text: all of it, no write ending at that ";" (not a command\'s end); exit 0'
              % mn.decode(), nano.data() == want and e == 0 and semi not in at and not nano.over, (nano.writes, e))
        nano = Nano(drain=8)
        k = boot([('L.PLT', lab)], nano)
        o, e = run(k, 'plot l.plt', esc_after=1)
        d = nano.data()
        check('... Esc in its text: the clear, then ETX and "PU;"; the Nano out of the label; exit 1 (%d bytes)' % len(d),
              stop_ok(nano, want, ends) and d.endswith(b'\x03PU;') and e == 1, (d[-30:], e, nano.clears))

def t_midlabel():
    """a label after a command's start (PA10,20LB...): found anywhere before the command's first ';'"""
    pre = b'IN;' + b'PU;' * 71 + b'SP1;SP2;'      # (224 bytes of whole commands)
    assert len(pre) == 224
    mid = pre + b'PA10,20LBab;' + b'cdefg\x03;' + b''.join(b'PA%d,%d;' % (i, i) for i in range(60))
    want = hpgl_check(mid)
    nano = Nano()
    k = boot([('M.PLT', mid)], nano)
    o, e = run(k, 'plot m.plt')
    check('"PA10,20LBab;cdefg<ETX>;" after %d bytes: kept whole (no write ends at "LBab;", %d, the room\'s 240 '
          'reaching it); all of it; exit 0' % (len(pre), len(pre) + 12), nano.data() == want and e == 0
          and not ends_ok(nano, want) and nano.writes[0] == len(pre), (nano.writes[:4], ends_ok(nano, want), e))
    mid = pre + b'PA1L\x03Bab;' + b'cdefgh\x03;' + b''.join(b'PA%d,%d;' % (i, i) for i in range(60))
    want = hpgl_check(mid)
    nano = Nano()
    k = boot([('M.PLT', mid)], nano)
    o, e = run(k, 'plot m.plt')
    check('"PA1L<ETX>Bab;cdefgh<ETX>;" after %d bytes (the Nano drops that first ETX: LB): kept whole (no write ends at '
          '"Bab;", %d); all of it; exit 0' % (len(pre), len(pre) + 9), nano.data() == want and e == 0
          and not ends_ok(nano, want) and nano.writes[0] == len(pre), (nano.writes[:4], ends_ok(nano, want), e))
    big = b'IN;PU0,0;PA10,20LBab;' + b'c' * 300 + b'\x03;PU;PA0,0;'
    want = hpgl_check(big); ends = set(hpgl_ends(want))
    nano = Nano(drain=8)
    k = boot([('M.PLT', big)], nano)
    o, e = run(k, 'plot m.plt', esc_after=1)
    d = nano.data()
    check('a label of 300 bytes after "PA10,20" (split): Esc in its text: the clear, then ETX and "PU;"; the Nano out of '
          'the label; exit 1', stop_ok(nano, want, ends) and d.endswith(b'\x03PU;') and e == 1, (d[-30:], e, nano.clears))
    # a cut that would fall between the mnemonic's letters (CR LF between them, which the Nano drops): before them
    pa = b'PA' + b','.join(b'%d' % (i % 10) for i in range(118))       # (237 bytes)
    pa += b'0' * (238 - len(pa))
    spl = pa + b'L\r\nBab;cd\x03;PU;'
    want = hpgl_check(spl)
    nano = Nano()
    k = boot([('S.PLT', spl)], nano)
    o, e = run(k, 'plot s.plt')
    check('a label whose mnemonic is "L<CR><LF>B" at 238-241 of a 240-byte room: the first write ends before the "L" '
          '(%r); all of it, the rest whole (gridlink\'s ends); exit 0' % nano.writes[:3], nano.data() == want and e == 0
          and nano.writes[0] == 238 and not ends_ok(nano, want)[1:], (nano.writes, ends_ok(nano, want), e))

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
    check('... a Selected Device Clear first (what the Nano holds dropped), the "PU;" after it (kept)',
          nano.clears == [len(d) - 3] and stop_ok(nano, hpgl_check(DRAWING), ends), nano.clears)
    check('... "Stopped: n of %d bytes sent.  What the Nano still holds may draw." (true with either firmware), no more'
          % len(hpgl_check(DRAWING)), 'bytes sent.  What the Nano still holds may draw.\n' in o and 'still draws' not in o
          and 'could not be sent' not in o, o[-300:])
    nano = Nano(drain=8, old=True)
    k = boot([('D.PLT', DRAWING)], nano)
    o, e = run(k, 'plot d.plt', esc_after=4)
    d = nano.data()
    check('... the same with v7.6 (the clear ignored): the clear, "PU;" after it, a whole command\'s end; exit 1',
          nano.clears == [len(d) - 3] and stop_ok(nano, hpgl_check(DRAWING), ends) and e == 1, (d[-40:], nano.clears, e))
    nano = Nano(drain=8)
    k = boot([('D.PLT', DRAWING)], nano)
    k.pc.tty.clear()
    k.key('plot d.plt'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: len(nano.writes) >= 4, 60)
    k.key(0x2E03, settle=False)          # (^C, typed)
    k.pc.run_until(lambda: 'Stopped' in out(k), 30); k.settle(2)
    o = out(k); d = nano.data()
    check('^C part-way: stopped as Esc stops it, the clear, "PU;" after a whole command; exit 1', 'Stopped: ' in o
          and d.endswith(b'PU;') and (len(d) - 3) in ends and nano.clears[-1:] == [len(d) - 3] and code(k) == 1,
          (d[-40:], nano.clears, o[-300:]))

def t_finish():
    """Esc while the pen only finishes what the Nano holds (all sent): no clear, what it holds gets drawn"""
    d0 = b'IN;SP1;' + b''.join(b'PA%d,%d;' % (i, i) for i in range(20))
    want = hpgl_check(d0)
    two = b'IN;PU5,5;PD9,9;PU;'
    nano = Nano(drain=4)
    k = boot([('F.PLT', d0), ('TWO.PLT', two)], nano)
    k.pc.tty.clear()
    k.key('plot f.plt'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: 'the pen is finishing' in out(k), 60)
    k.key(ktest.ESC, settle=False)
    k.pc.run_until(lambda: 'Left to finish' in out(k), 30); k.settle(2)
    o = out(k); held = nano.held
    check('Esc while the pen finishes (%d bytes, all sent, the Nano still drawing): "Left to finish", no clear, nothing '
          'after the file; exit 0' % len(want), 'Left to finish' in o and nano.data() == want
          and nano.clears == [] and held > 0 and code(k) == 0, (nano.clears, held, nano.data()[-20:], o[-300:]))
    # then another plot at once: it waits for the first drawing's rest (no clear: that would drop it), then goes
    k.pc.tty.clear(); k.key('plot two.plt'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: 'still busy' in out(k), 30)
    h1 = nano.held
    k.pc.run_until(lambda: out(k).rstrip().endswith('A:\\>'), 120); k.settle(2)
    o = out(k); e = code(k)
    check('... PLOT TWO.PLT straight after, %d bytes of the first still held: "still busy", waits; no clear; the first\'s '
          'bytes all drawn before its first write (none held then); then all of it; exit 0' % h1, h1 > 0
          and 'The plotter is still busy.' in o and nano.clears == [] and nano.wheld[-1] == 0
          and nano.data() == want + hpgl_check(two) and e == 0, (h1, nano.clears, nano.wheld, o[-300:]))

def t_start():
    """a busy Nano at the start: waited for; Esc clears it and plots; ^C stops, nothing sent"""
    d0 = b'IN;SP1;PA1,1;PD2,2;PU;'
    want = hpgl_check(d0)
    def go(nano, key):
        k = boot([('S.PLT', d0)], nano)
        k.pc.tty.clear(); k.key('plot s.plt'); k.key(ktest.ENTER, settle=False)
        k.pc.run_until(lambda: 'still busy' in out(k), 30)
        k.pc.run_until(lambda: False, 3)                    # (waiting a while)
        n = nano.polls
        k.key(key, settle=False)
        k.pc.run_until(lambda: out(k).rstrip().endswith('A:\\>'), 120); k.settle(2)
        return k, out(k), n
    nano = Nano(drain=1, held=200)                          # (an earlier drawing's 200 bytes, slowly)
    k, o, n = go(nano, ktest.ESC)
    check('busy at the start (200 bytes held): "still busy", polled while waiting (%d), no write; Esc: the clear, then '
          'all of it; exit 0' % n, 'still busy' in o and n > 2 and nano.clears == [0] and nano.data() == want
          and code(k) == 0, (n, nano.clears, nano.data(), o[-300:]))
    nano = Nano(stuck=True)                                 # (left in a label: never idle, room though)
    k, o, n = go(nano, ktest.ESC)
    check('a Nano left in a label (never idle): "still busy" till Esc; the clear; all of it; exit 0',
          'still busy' in o and nano.clears == [0] and nano.data() == want and code(k) == 0, (nano.clears, o[-300:]))
    nano = Nano(stuck=True)
    k, o, n = go(nano, 0x2E03)                              # (^C)
    check('... ^C while waiting: "Stopped: 0 of %d bytes sent."; no clear, nothing sent; exit 1' % len(want),
          ('Stopped: 0 of %d bytes sent.' % len(want)) in o and nano.clears == [] and not nano.data() and code(k) == 1,
          (nano.clears, o[-300:]))
    def plain(nano, typed=None, files=(), line='plot s.plt'):     # (no key once it runs; typed: one queued at once)
        k = boot([('S.PLT', d0)] + list(files), nano)
        k.pc.tty.clear(); k.key(line); k.key(ktest.ENTER, settle=False)
        if typed: k.key(typed, settle=False)
        t0 = k.pc.us
        k.pc.run_until(lambda: out(k).rstrip().endswith('A:\\>'), 300); k.settle(2)
        return k, out(k), (k.pc.us - t0) / 1e6
    nano = Nano(drain=2, held=100)                          # (draining: its room changes every ~2 polls, for ~50 s)
    k, o, s = plain(nano)
    check('draining for %.0f s (its status changing): waited for, no clear; nothing of the earlier '
          'drawing lost (none held at the first write); all of it; exit 0' % s, s > 20 and nano.clears == []
          and nano.wheld[:1] == [0] and 'not changed' not in o and nano.data() == want and code(k) == 0,
          (s, nano.clears, nano.wheld, o[-300:]))
    nano = Nano(stuck=True)
    k, o, s = plain(nano)
    check('a Nano left in a label (its ring empty), no key: "The plotter has not changed for 60 s: plotting now."; the '
          'clear; all of it; exit 0 (%.0f s)' % s, 'The plotter has not changed for 60 s: plotting now.' in o
          and nano.clears == [0] and nano.data() == want and 59 < s < 120 and code(k) == 0, (s, nano.clears, o[-300:]))
    nano = Nano(busy=40)                                    # (a label it took whole, drawn for ~40 s from its buffer)
    k, o, s = plain(nano)
    check('ring empty, not idle for ~40 s (a label still being drawn), then idle: waited for, no clear (it would stop the '
          'label); all of it; exit 0 (%.0f s)' % s, nano.clears == [] and nano.cut is None and 'not changed' not in o
          and nano.data() == want and s > 35 and code(k) == 0, (s, nano.clears, nano.cut, o[-300:]))
    nano = Nano(drain=4, held=100, block=100)               # (its ring standing still ~100 s: waiting on the plotter)
    k, o, s = plain(nano)
    check('bytes in its ring, the status unchanged ~100 s (the Nano waiting on the plotter), then draining: waited for, '
          'no clear; nothing of the earlier drawing lost (none held at the first write); all of it; exit 0 (%.0f s)' % s,
          nano.clears == [] and nano.wheld[:1] == [0] and nano.data() == want and s > 95 and code(k) == 0,
          (s, nano.clears, nano.wheld, o[-300:]))
    nano = Nano(drain=4, held=100, block=10 ** 9)           # (never moving)
    k, o, s = plain(nano)
    check('bytes in its ring, unchanged past 200 s: "PLOT: the plotter still holds an earlier drawing and has not moved '
          'for 200 s (Esc while it waits plots now).  Nothing was sent."; no clear; exit 3 (%.0f s)' % s,
          'PLOT: the plotter still holds an earlier drawing and has not moved for 200 s\n\n(Esc while it waits plots '
          'now).  Nothing was sent.' in o and nano.clears == [] and not nano.data() and 195 < s < 260 and code(k) == 3,
          (s, nano.clears, o[-300:]))
    nano = Nano(stuck=True)
    k = boot([('S.PLT', d0)], nano)
    k.pc.tty.clear(); k.key('plot s.plt'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: 'still busy' in out(k), 30)
    nano.fixed = 0x60                                       # (asking for service: not the Nano after all)
    k.pc.run_until(lambda: out(k).rstrip().endswith('A:\\>'), 120); k.settle(2)
    o = out(k)
    check('RQS appearing while waited for: "GPIB 1 asks for service: it is not the Nano.  Nothing was sent."; no clear; '
          'exit 2', 'GPIB 1 asks for service: it is not the Nano' in o and nano.clears == [] and not nano.data()
          and code(k) == 2, (nano.clears, o[-300:]))
    nano = Nano(drain=2, held=100)
    k, o, s = plain(nano, typed=ktest.ESC)
    check('an Esc typed before the wait began (queued while the file was read): not its answer, no clear; waited for; '
          'all of it; exit 0', 'still busy' in o and nano.clears == [] and nano.data() == want and code(k) == 0,
          (nano.clears, o[-300:]))
    nano = Nano(stuck=True)
    k = boot([('S.PLT', d0)], nano)
    k.pc.tty.clear(); k.key('plot s.plt'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: 'still busy' in out(k), 30)
    del k.pc.chip.devices[1]                                # (gone while waited for)
    k.pc.run_until(lambda: out(k).rstrip().endswith('A:\\>'), 300); k.settle(2)
    o = out(k)
    check('the Nano gone while waited for: "PLOT: the Nano stopped answering serial polls.  Nothing was sent."; exit 3',
          'PLOT: the Nano stopped answering serial polls.  Nothing was sent.' in o and code(k) == 3, o[-300:])
    # Esc in a long PD (sent a room at a time) on firmware that ignores the clear: the Nano left in its coordinates,
    # never idle; the next PLOT, no key, plots after the short wait, its first letter ending that PD
    big = b'IN;PU0,0;PD' + b','.join(b'%d,%d' % (i, i * 3 % 1000) for i in range(300)) + b';PU;'
    nano = Nano(drain=8, old=True)
    k = boot([('BIG.PLT', big), ('S.PLT', d0)], nano)
    o, e = run(k, 'plot big.plt', esc_after=3)
    d1 = nano.data()
    o, e = run(k, 'plot s.plt', sim=200)
    d = nano.data(); lab, cmds = nano_parse(d)
    check('Esc in a long PD on firmware that ignores the clear (%d bytes, the Nano left in it), then PLOT S.PLT, no key: '
          '"not changed for 60 s: plotting now"; all of it after the PD\'s part; the PD ended by its first letter (IN '
          'after the last PD); exit 0' % len(d1), big.startswith(d1) and d == d1 + want
          and 'The plotter has not changed for 60 s: plotting now.' in o
          and b'IN' in cmds[cmds.index(b'PD') + 1:] and cmds[-1] == b'PU' and not nano_parse(d, hand=True) and e == 0,
          (len(d1), cmds[-6:], e, o[-300:]))

def t_giveup():
    """given up part-way with the Nano answering: a clear before the exit, best-effort"""
    nano = Nano(drain=0)                                    # (takes the first write, then never any room)
    k = boot([('L.PLT', LABEL)], nano)
    o, e = run(k, 'plot l.plt', sim=260)
    d = nano.data()
    check('no room for 200 s inside a split label: "the Nano had no room for 200 s"; a clear after the last byte; exit 3',
          'the Nano had no room for 200 s' in o and nano.clears == [len(d)] and 0 < len(d) < len(LABEL) and e == 3,
          (nano.clears, len(d), e, o[-300:]))
    nano = Nano(drain=8)
    k = boot([('L.PLT', LABEL)], nano)
    k.pc.tty.clear(); k.key('plot l.plt'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: len(nano.writes) >= 1, 60)
    k.pc.chip.refuse = True                                 # (its data bytes no longer taken)
    k.pc.run_until(lambda: 'failed' in out(k) or out(k).rstrip().endswith('A:\\>'), 260); k.settle(2)
    k.pc.chip.refuse = False
    o = out(k); d = nano.data()
    check('a write failing part-way (in a split label): "a write to the Nano failed"; a clear after the last byte; exit 3',
          'a write to the Nano failed' in o and nano.clears[-1:] == [len(d)] and code(k) == 3, (nano.clears, len(d), o[-300:]))

def t_crit():
    """a disk error part-way (the file's later sectors unreadable): the read fails (INT 24h: Fail, no question; LCMD's
    question answered Abort if it asks), and the pen still goes up"""
    nano = Nano()
    k = boot([('D.PLT', DRAWING)], nano)
    raw = bytes(k.pc.drives[0].img)
    ent = [raw[19 * 512 + 32 * i:19 * 512 + 32 * i + 32] for i in range(224)]
    cl = [struct.unpack_from('<H', e, 26)[0] for e in ent if e[:11] == b'D       PLT'][0]
    k.pc.tty.clear()
    k.key('plot d.plt'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: len(nano.writes) >= 3, 60)
    k.pc.drives[0].bad = {33 + cl - 2 + i for i in range(8, 30)}; k.pc.drives[0].changed = True   # (from 4 KB on; the
    asked = False                                                                                   #  cache let go)
    k.pc.run_until(lambda: 'Abort, Retry, Fail?' in out(k) or 'A:\\>' in out(k)[-8:], 120)
    if 'Abort, Retry, Fail?' in out(k):
        asked = True; k.key('a', settle=False)
        k.pc.run_until(lambda: 'A:\\>' in out(k)[-8:], 30)
    k.settle(2)
    o = out(k); d = nano.data(); k.pc.drives[0].bad = set()
    ans = k.rd('c24_ans', 1)[0]         # (the kernel's record of the last INT 24h answer)
    ends = set(hpgl_ends(hpgl_check(DRAWING)))
    check('the file unreadable part-way: no Abort, Retry, Fail question (%s); "the file can\'t be read", the pen up ("PU;" '
          'after a whole command, no clear); exit 3' % ('asked' if asked else 'none'), not asked and
          'the file can\'t be read' in o and d.endswith(b'PU;') and (len(d) - 3) in ends and DRAWING.startswith(d[:-3])
          and nano.clears == [] and code(k) == 3, (asked, d[-30:], nano.clears, o[-300:]))
    check('... its INT 24h answered 83h, a Fail nobody was asked for (KDISK.INC rule 4: the kernel drops nothing, no '
          'unmount), not the user\'s 3 (%02Xh)' % ans, ans == 0x83, ans)

def t_bridge():
    nano = Nano(); nano.fixed = 0x60     # (RQS and a frame waiting: what the Claude bridge says)
    k = boot([('D.PLT', DRAWING)], nano)
    o, e = run(k, 'plot d.plt', sim=20)
    check('an address that asks for service (the bridge): "GPIB 1 asks for service: it is not the Nano"; nothing sent, '
          'not even a clear; exit 2', 'GPIB 1 asks for service: it is not the Nano' in o and not nano.data()
          and not nano.clears and e == 2, (e, nano.clears, o[-300:]))

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
             ('OPEN4.PLT', b'IN;PU0,0;L\r\nBhello;PU;', 'a label (LB, BL or WD) has no ETX'),   # (the Nano drops CR LF)
             ('OPEN5.PLT', b'LBa\x03;PU;B\x1a\x08L', 'a label (LB, BL or WD) has no ETX'),
             ('OPEN6.PLT', b'IN;L\x03Bxy;PU;', 'a label (LB, BL or WD) has no ETX'),   # (outside a label ETX is dropped)
             ('OPEN7.PLT', b'LBab\x03L\x03Bcd;', 'a label (LB, BL or WD) has no ETX'),
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
    for d in (b'IN;\x1bA\x56;SP1;', b'LBab\x08\x0e\x0fc\x03', b'IN;SP1;PU', b'pa1,2;lbx\x03;wd\x03',
              b'LBxyB\x03LT;', b'PA10,20LBab;c\x03;BLd;\x03WDe;f\x03',      # (an ETX between B and L: no BL)
              b'L\x03Ba;b\x03;PA1,2;'):                                     # (L<ETX>B: a label, to the second ETX)
        nano = Nano()
        k = boot([('A.PLT', d)], nano)
        o, e = run(k, 'plot a.plt', sim=30)
        check('%r: plotted as hpgl_check gives it (%r); exit 0' % (d, hpgl_check(d)), nano.data() == hpgl_check(d) and e == 0,
              (nano.data(), e, o[-300:]))

def t_units():
    """gridlink's hpgl_ends and hpgl_check, PLOT's reference: BL and WD labels, a label anywhere before a command's
    first ';', a mnemonic's letters as the Nano reads them"""
    for d, want in ((b'IN;BLa;b\x03;PU;', [3, 10, 13]), (b'IN;WDa;b\x03;PU;', [3, 10, 13]),
                    (b'PA10,20LBab;c\x03;PU;', [15, 18]), (b'PA1L\r\nBa;b\x03;', [12]),
                    (b'IN;lB\x08x;y\x03;', [3, 11]), (b'PA1,2;LT;PU;', [6, 9, 12]),
                    (b'L\x03Ba;b\x03;PA1,2;', [8, 14])):   # (outside a label the Nano drops an ETX: L<ETX>B is LB)
        check('hpgl_ends(%r) == %r' % (d, want), hpgl_ends(d) == want, hpgl_ends(d))
    for d, want in ((b'LBab\x03', (0, 2)), (b'PA10,20lb;', (7, 9)), (b'PA1L\r\nBa;', (3, 7)), (b'IN;W\x1aD', (3, 6)),
                    (b'PA1,2;LT;', (-1, -1)), (b'L\x03B', (0, 3)), (b'L\x00B', (0, 3)), (b'L\x7fB', (0, 3)),
                    (b'L\x80B', (0, 3)), (b'L\x1bB', (-1, -1)), (b'L B', (-1, -1))):
        check('hpgl_label(%r) == %r (its first letter, after its second: never a cut between)' % (d, want),
              hpgl_label(d, 0, len(d)) == want, hpgl_label(d, 0, len(d)))
    cases = ((b'IN;L\nBab;', False), (b'IN;W\tD x;', False), (b'LBa\x03;B\r\x0e\x0fL', False), (b'IN;b\x1aL;', False),
             (b'IN;L\x03Bxy;PU;', False), (b'LBab\x03L\x03Bcd;', False), (b'LBxyB\x03LT;', True), (b'IN;L\x1bBE;', True),
             (b'IN;L B;', True), (b'IN;L1B;', True), (b'L\x03Ba;b\x03;PA1,2;', True))
    for d, ok in cases:
        try: hpgl_check(d); g = True
        except ValueError: g = False
        check('hpgl_check(%r): %s' % (d, 'taken' if ok else 'refused (a label left open)'), g == ok)
    for d, lab in ((b'\x1bAIeLB', False), (b'\x1bAJ3eLB', True), (b'\x1bAJ30;LB', True), (b'\x1bAJ' + b'1' * 30 + b'BL', False)):
        check('the test\'s Nano parser (feedChar): %r %s' % (d, 'in a label' if lab else 'no label (E only after a digit, '
              'NAT_MAX)'), nano_parse(d)[0] == lab, nano_parse(d))
    def ends_open(d):                   # (hpgl_ends' last command: a label with no ETX after its mnemonic)
        e = [0] + hpgl_ends(d); a = e[-2]
        while a < len(d) and d[a] in b' \r\n\t;': a += 1
        k = d.find(b';', a)
        t = hpgl_label(d, a, len(d) if k < 0 else k)[1]
        return t >= 0 and d.find(b'\x03', t) < 0
    def check_open(d):
        try: hpgl_check(d); return False
        except ValueError as x: return 'label' in str(x)
    every = [d for d, _ in cases] + [
        b'IN;BLa;b\x03;PU;', b'PA10,20LBab;c\x03;PU;', b'IN;LBno end;PU;', b'IN;\x03 bl', b'IN;WDhello;PU;', b'IN;PU0,0;L\r\nBhello;PU;', b'LBa\x03;PU;B\x1a\x08L',
        b'LBab\x08\x0e\x0fc\x03', b'pa1,2;lbx\x03;wd\x03', b'PA10,20LBab;c\x03;BLd;\x03WDe;f\x03', LABEL, DRAWING]
    bad = [d for d in every if check_open(d) != ends_open(d)]
    check('hpgl_check refuses a label left open exactly where hpgl_ends\' last command is a label with no ETX (%d files)'
          % len(every), not bad, bad)

def t_address():
    nano = Nano(addr=5)
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(SRC, n) for n in ('LODE.SYS', 'LCMD.COM', 'PLOT.COM')]
                      + [f('D.PLT', b'IN;PU;')])
    k = ktest.KPC(img, chip=Chip({5: nano})); k.start(); k.code_p()
    o, e = run(k, 'plot d.plt', sim=30)
    check('no Nano at GPIB 1: "the Nano at GPIB 1 does not answer a serial poll ... Nothing was sent"; exit 2',
          'the Nano at GPIB 1 does not answer a serial poll' in o and 'Nothing was sent' in o and e == 2 and not nano.data()
          and not nano.clears, (e, nano.clears, o[-300:]))
    o, e = run(k, 'plot d.plt /A:5', sim=30)
    check('/A:5: plotted there; exit 0', nano.data() == b'IN;PU;' and e == 0, (nano.data(), e, o[-300:]))

def t_nogpib():
    k = boot([('D.PLT', b'IN;')], chip=False)
    o, e = run(k, 'plot d.plt', sim=20)
    check('no GPIB (no 7210, so no INT 60h driver): "there is no GPIB driver"; exit 2', 'there is no GPIB driver' in o and e == 2,
          (e, o[-300:]))


if __name__ == '__main__':
    only = sys.argv[1:]
    for t in (t_units, t_plot, t_long, t_full, t_label, t_midlabel, t_esc, t_finish, t_start, t_giveup, t_crit, t_bridge,
              t_stall, t_refused,
              t_accepted, t_address, t_nogpib):
        if not only or t.__name__ in only: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed' % (len(results), len(bad)))
    sys.exit(1 if bad else 0)
