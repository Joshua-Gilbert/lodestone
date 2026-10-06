"""Grid-OS 0.3: the UI core and the .RUN programs, in pcemu.

    python3 tests/test_apps.py [t_core t_system t_write t_exec t_font t_memory t_saver] [shots]

UITEST.RUN exercises the core's API (lists, forms, ask, help, errors,
cleanup); SYSTEM.RUN and WRITE.RUN are driven from the Executive as a user
would.  With "shots", screenshots go to screens/0.3.
"""
import os, re, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, mkrun, fatcheck, sim7210
OUT = os.environ.get('KOUT', os.path.join(__import__('tempfile').gettempdir(), 'gridos-apps'))
os.makedirs(OUT, exist_ok=True)
SHOTS = os.path.join(GOS, 'screens', '0.3') if 'shots' in sys.argv else None
if SHOTS: os.makedirs(SHOTS, exist_ok=True)

SYS = os.path.join(GOS, 'src', 'GRIDOS.SYS')
SYSTEM = os.path.join(GOS, 'apps', 'SYSTEM.RUN')
WRITE = os.path.join(GOS, 'apps', 'WRITE.RUN')
UITEST = os.path.join(HERE, 'UITEST.RUN')
MEMSZ = os.path.join(HERE, 'MEMSZ.COM')
TSR = os.path.join(HERE, 'TSR.COM')
M33TEST = os.path.join(HERE, 'M33TEST.COM')
M33 = {n: os.path.join(HERE, n + '.COM') for n in ('M33GFX', 'M33QUIT', 'M33HSET', 'M33HVIC')}
GRIDCMD = os.path.join(GOS, 'src', 'GRIDCMD.COM')
TM5000G = os.environ.get('TM5000G') or os.path.join(GOS, '..', 'tools', 'TM5000G.EXE')
TERMFNT = os.path.join(GOS, 'fonts', 'TERMINUS.FNT')
DEFRAG = os.path.join(GOS, 'src', 'DEFRAG.COM')

K_HOME, K_END, K_PGDN, K_PGUP, K_DEL, K_INS = 0x4700, 0x4F00, 0x5100, 0x4900, 0x5300, 0x5200
K_CHOME, K_CEND, K_CLEFT, K_CRIGHT = 0x7700, 0x7500, 0x7300, 0x7400
K_CODE_HELP, K_CODE_ENTER, K_CODE_ESC = 0x3500, 0x1C00, 0x0100     # as INT 16h AH=10h returns them
CODE = {c: v for c, v in zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        (0x1E00, 0x3000, 0x2E00, 0x2000, 0x1200, 0x2100, 0x2200, 0x2300, 0x1700, 0x2400, 0x2500, 0x2600, 0x3200,
         0x3100, 0x1800, 0x1900, 0x1000, 0x1300, 0x1F00, 0x1400, 0x1600, 0x2F00, 0x1100, 0x2D00, 0x1500, 0x2C00))}

def build():
    subprocess.run([os.path.join(GOS, 'kbuild.sh')], check=True, stdout=subprocess.DEVNULL)
    for src, dst in (('apps/SYSTEM.ASM', SYSTEM), ('apps/WRITE.ASM', WRITE), ('tests/UITEST.ASM', UITEST)):
        mkrun.build(os.path.join(GOS, src), dst)
    subprocess.run(['nasm', '-f', 'bin', '-o', MEMSZ, os.path.join(HERE, 'MEMSZ.ASM')], check=True)
    subprocess.run(['nasm', '-f', 'bin', '-o', TSR, os.path.join(HERE, 'TSR.ASM')], check=True)
    for c in [M33TEST] + list(M33.values()):
        subprocess.run(['nasm', '-f', 'bin', '-o', c, c[:-4] + '.ASM'], check=True)

SYMS = {}
def run_syms(src):
    """Symbols of a .RUN (offsets from its load address)."""
    if src not in SYMS:
        SYMS[src] = mkrun.build(os.path.join(GOS, src), os.path.join(OUT, '_' + os.path.basename(src) + '.RUN'))['syms']
    return SYMS[src]

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:600]) if detail and not cond else ''))

def image(name, *files):
    return mkimg.build(os.path.join(OUT, name), [SYS] + list(files))

def shot(k, name):
    if SHOTS: k.shot(os.path.join(SHOTS, name + '.png'))

def lines(k): return [l for y, l in k.ocr()]
def screen(k): return '\n'.join(lines(k))
def has(k, text): return any(text in l for l in lines(k))

def free_paras(k):
    """Free paragraphs in the MCB chain, and the UI block's size."""
    pc, seg, free, ui = k.pc, k.u16('first_mcb'), 0, None
    while True:
        t, own, sz, nm = pc.rd(seg, 0, 1)[0], pc.u16(seg, 1), pc.u16(seg, 3), pc.rd(seg, 8, 2)
        if own == 0: free += sz + 1
        if own == 8 and nm == b'UI': ui = sz
        if t != ord('M'): return free, ui
        seg += sz + 1

def run_ret(k): return k.u16('run_ret')

def click(k, x, y):
    """Move the pointer to (x, y) and press the left button."""
    dx, dy = x - k.u16('mx'), y - k.u16('my')
    while dx or dy:
        sx, sy = max(-100, min(100, dx)), max(-100, min(100, dy))
        k.pc.mouse_move(sx & 0xFF, sy & 0xFF); k.pc.run_for(0.05)
        dx -= sx; dy -= sy
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.settle()

# ---------------------------------------------------------------------
def t_core():
    print('== core (UITEST.RUN)')
    img = image('core.img', UITEST, os.path.join(GOS, 'src', 'GRIDCMD.COM'))
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    free0, ui0 = free_paras(k)
    shot(k, 'executive')
    k.key(ktest.F1); shot(k, 'executive_help'); k.key(ktest.ENTER)
    # the 1520's BIOS gives CODE-? (and CODE-Return, CODE-ESC) only through
    # INT 16h AH=10h; pcemu now models that
    k.key(K_CODE_HELP)
    check('CODE-? opens the Executive\'s help', has(k, 'Grid-OS 0.3 Help'), screen(k))
    k.key(ktest.ESC)
    check('the Executive lists .RUN files as Program', 'UITEST.RUN' in k.exec_list() and has(k, 'Program'), screen(k))
    k.select('UITEST.RUN'); k.key(ktest.ENTER)
    check('UITEST.RUN loads and draws its screen', has(k, 'UI test') and has(k, 'Item 1') and not k.crashed, (k.where(), screen(k)))
    free1, ui1 = free_paras(k)
    check('the UI block grew for it, and its UI_ALLOC block came from DOS', ui1 > ui0 and free1 < free0 - 100, (ui0, ui1, free0, free1))
    k.key(ktest.DOWN, ktest.DOWN)
    k.key(K_PGDN)
    check('list: Down, PgDn move and scroll', lines(k)[1].strip().startswith('Item 4'), lines(k)[:3])
    k.key(CODE['F'])
    shot(k, 'core_form')
    check('form: a window with text and choice fields', has(k, 'Find       hello') and has(k, 'Independent of case') and has(k, 'Fill in form'), screen(k))
    k.key('world'); k.key(ktest.ENTER); k.key(ktest.RIGHT); k.key(ktest.ENTER); k.key(' '); k.key(ktest.ENTER)
    check('form: typing replaces the old text, Right and Space change choices, Return confirms', has(k, 'Find: world 1 1'), screen(k))
    k.key(CODE['F']); k.key('again'); k.key(K_CODE_ENTER)
    check('form: CODE-Return confirms from the first field', has(k, 'Find: again 1 1'), screen(k))
    k.key(CODE['F']); k.key('world'); k.key(K_CODE_ENTER)
    k.key(CODE['F']); k.key(ktest.ESC)
    check('form: ESC cancels and changes nothing', has(k, 'Find: world 1 1') and not has(k, 'Fill in form'), screen(k))
    # review fixes (2026-10-06)
    k.key(CODE['F'])
    click(k, 320, 5)                    # above the form's window
    check('form: a click above the window does nothing (it was a divide fault: the machine hung)',
          not k.crashed and has(k, 'Fill in form') and k.where().split()[-1].split('+')[0] != 'ui_form.click', (k.where(), k.band()))
    k.key(ktest.LEFT, K_PGDN, 'Z', K_CODE_ENTER)
    check('form: a key the form ignores keeps the field as it was (Left, PgDn, Z: "worlZd")', has(k, 'Find: worlZd'), screen(k))
    k.key(CODE['R'])
    check('UI_RUN given a .RUN: error 11 (it ran the header as code)', has(k, 'UI_RUN error 11'), screen(k))
    k.key(CODE['Q'])
    check('ask: the band asks', k.band() == ['Quit: Confirm to quit', 'Press RETURN to confirm or ESC to cancel'], k.band())
    k.key(ktest.ESC)
    check('ask: ESC = cancelled, band as before', has(k, 'cancelled') and k.band()[0].startswith('UI test'), (screen(k), k.band()))
    k.key(CODE['Q']); k.key(ktest.ENTER)
    check('ask: Return = confirmed', has(k, 'confirmed'), screen(k))
    k.key(CODE['E'])
    check('error text: 19 is "Disk is write-protected"', has(k, 'Disk is write-protected'), screen(k))
    before = k.pc.rd(0xB800, 0, 0x8000)
    k.key(ktest.F1)
    check('help window from the key table', has(k, 'CODE-F     the form') and has(k, 'ESC        leave'), screen(k))
    k.key('x')
    check('help: any key closes it, the screen as it was', k.pc.rd(0xB800, 0, 0x8000) == before)
    lst = k.u16('run_base') + run_syms('tests/UITEST.ASM')['lst']
    click(k, 40, 40 + 16 * 5 + 8)      # a click on the sixth row shown
    check('a click selects a list row', k.pc.u16(k.useg, lst + 6) == k.pc.u16(k.useg, lst + 8) + 5,
          (k.pc.u16(k.useg, lst + 6), k.pc.u16(k.useg, lst + 8)))
    k.key(ktest.ESC)
    check('ESC: back in the Executive', k.band()[0] == 'Select a file and confirm' and 'UITEST.RUN' in k.exec_list(), k.band())
    check('exit code 42 came back to the loader', run_ret(k) == 42, run_ret(k))
    free2, ui2 = free_paras(k)
    check('afterwards: UI block its own size, its memory and the UI_ALLOC block free again', ui2 == ui0 and free2 == free0, (ui0, ui2, free0, free2))
    check('BSS was zeroed (else exit code 99)', run_ret(k) != 99)
    # a file that isn't a .RUN
    open(os.path.join(OUT, 'BAD.RUN'), 'wb').write(b'MZ not a run file' + bytes(100))
    img = image('bad.img', os.path.join(OUT, 'BAD.RUN'))
    k = ktest.KPC(img); k.start()
    k.select('BAD.RUN'); k.key(ktest.ENTER)
    check('a .RUN that isn\'t one: "Can\'t run BAD.RUN: Not a program"', any("Can't run BAD.RUN: Not a program" in l for l in k.band()), k.band())
    free3, ui3 = free_paras(k)
    k.key(ktest.ENTER)
    check('... and the UI block is its own size', ui3 == ui0, (ui0, ui3))
    # damaged headers: fixup counts that overflow, a fixup outside the image
    hdr = lambda size, bss, na, nr: b'GRUN' + struct.pack('<6H', 1, size, bss, na, nr, 0)
    open(os.path.join(OUT, 'BAD2.RUN'), 'wb').write(hdr(4, 0, 0x8000, 0x8000) + b'\xc3\x90\x90\x90')
    open(os.path.join(OUT, 'BAD3.RUN'), 'wb').write(hdr(4, 0, 1, 0) + b'\xc3\x90\x90\x90' + struct.pack('<H', 0xFFF0))
    img = image('bad2.img', os.path.join(OUT, 'BAD2.RUN'), os.path.join(OUT, 'BAD3.RUN'))
    k = ktest.KPC(img); k.start()
    table = k.pc.rd(k.useg, 0, 135)
    for name in ('BAD2.RUN', 'BAD3.RUN'):
        k.select(name); k.key(ktest.ENTER)
        check('%s (a damaged header): "Not a program", the core untouched' % name,
              any("Can't run %s: Not a program" % name in l for l in k.band()) and not k.crashed and k.pc.rd(k.useg, 0, 135) == table,
              (k.band(), k.where()))
        k.key(ktest.ENTER)

# ---------------------------------------------------------------------
def t_system():
    print('== System (SYSTEM.RUN)')
    img = image('sys.img', SYSTEM, MEMSZ, os.path.join(GOS, 'src', 'GRIDCMD.COM'))
    chip = sim7210.NEC7210(sim7210.bus())
    k = ktest.KPC(img, chip=chip); k.pc.mouse = True; k.start()
    out = k.run_file('MEMSZ.COM', 20)
    m = re.search(r'([\d.]+) KB for programs', out)
    memsz = float(m.group(1)) if m else 0
    k.key(ktest.ENTER)
    k.key(CODE['U'])
    shot(k, 'system_memory')
    m = re.search(r'Free for programs\s+([\d.]+) KB', screen(k))
    free = float(m.group(1)) if m else 0
    check('CODE-U: System, Memory first', has(k, 'System') and has(k, 'Kernel (DOS + GPIB)') and has(k, 'Disk cache            ') , screen(k))
    check('... with its own band from the start (it was blank)', k.band()[:1] == ['System: Select a topic'], k.band())
    check('"Free for programs" is what a DOS program gets (MEMSZ %.1f KB, System %.1f KB)' % (memsz, free),
          memsz > 0 and abs(free - memsz) < 1.0, (memsz, free))
    k.key(ktest.DOWN)
    shot(k, 'system_disks')
    check('Disks: label, size, free', has(k, 'Drive A:') and has(k, 'GRIDOS') and has(k, '1423 KB'), screen(k))
    k.key('C')
    check('a letter: the topic starting with it (Clock)', has(k, 'Date') and has(k, 'October 2026'), screen(k))
    k.key(ktest.ENTER)
    shot(k, 'system_clock_form')
    check('Return on Clock: the date and time form', has(k, 'Date and time') and has(k, '4-Oct-2026'), screen(k))
    k.key('7 nov 26'); k.key(ktest.ENTER); k.key('8:05 am'); k.key(ktest.ENTER)
    check('the clock is set: details and the title bar', has(k, 'Saturday, 7 November 2026') and has(k, '8:05 am') and lines(k)[0].strip().startswith('7-Nov-26'),
          screen(k))
    k.key(ktest.ENTER); k.key('31 feb 2026'); k.key(ktest.ENTER); k.key(ktest.ENTER)
    check('a date that doesn\'t exist: said so, the form again', any('Not a date' in l for l in k.band()), k.band())
    k.key(ktest.ENTER); k.key(ktest.ESC)
    check('after the form: System\'s band again', k.band()[:1] == ['System: Select a topic'], k.band())
    k.key(ktest.ENTER); k.key(ktest.ENTER); k.key('8:20 am'); k.key(ktest.ENTER)
    check('the clock set 15 minutes on: no screen saver straight away', has(k, '8:20 am') and has(k, 'Saturday, 7 November 2026'), screen(k))
    k.key(ktest.ENTER); k.key('1 jan 2030'); k.key(ktest.ENTER); k.key('99:99'); k.key(ktest.ENTER)
    check('a bad time: said so', any('Not a time' in l for l in k.band()), k.band())
    k.key(ktest.ENTER); k.key(ktest.ESC)
    check('... and the date wasn\'t changed either', lines(k)[0].strip().startswith('7-Nov-26'), lines(k)[0])
    for bad in ('65567-Oct-2026', '5-Octx-2026', '5-Oct-2026 x'):
        k.key(ktest.ENTER); k.key(bad); k.key(ktest.ENTER); k.key(ktest.ENTER)
        check('"%s" is not a date' % bad, any('Not a date' in l for l in k.band()), k.band())
        k.key(ktest.ENTER); k.key(ktest.ESC)
    for bad in ('13 pm', '9:41 xm'):
        k.key(ktest.ENTER); k.key(ktest.ENTER); k.key(bad); k.key(ktest.ENTER)
        check('"%s" is not a time' % bad, any('Not a time' in l for l in k.band()), k.band())
        k.key(ktest.ENTER); k.key(ktest.ESC)
    k.key('D')
    check('Devices: 80287, BIOS, panel, mouse', has(k, '80287') and has(k, '10/25/89') and has(k, 'Plasma 640x400') and has(k, 'COM2'), screen(k))
    k.key('G')
    check('GPIB: the built-in driver', has(k, 'built in, version 1.20, INT 60h') and has(k, '21'), screen(k))
    k.key(ktest.ENTER); k.key(ktest.ENTER, settle=False); k.settle(30)
    shot(k, 'system_gpib')
    check('GPIB scan finds the instruments on the simulated bus (6, 14, 29)', re.search(r'Instruments at\s+6, 14, 29', screen(k)), screen(k))
    k.key('A')
    check('About', has(k, 'Grid-OS 0.3') and has(k, '3.30 compatible'), screen(k))
    k.key(ktest.F1)
    check('help', has(k, 'System Help') and has(k, 'back to the Executive'), screen(k))
    k.key('x'); k.key(K_CODE_HELP)
    check('CODE-? opens System\'s help', has(k, 'System Help'), screen(k))
    k.key('x'); k.key(ktest.ESC)
    check('ESC: back in the Executive', k.band()[0] == 'Select a file and confirm', k.band())

# ---------------------------------------------------------------------
TEXT = b'The quick brown fox\r\njumps over\r\nthe lazy dog.\r\n\tTabbed line\r\nlast line'

def write_open(name='NOTES.TXT', data=TEXT, extra=(), mouse=False, **kw):
    p = os.path.join(OUT, name)
    open(p, 'wb').write(data)
    img = image('w_' + name + '.img', WRITE, p, *extra)
    k = ktest.KPC(img, **kw); k.pc.mouse = mouse; k.start()
    k.select(name); k.key(ktest.ENTER)
    return k

def busy(k, key):
    """Emulated milliseconds from a key to the program asking for the next."""
    ev, rec = k.Y['ui_event'], {}
    def h(pc):
        if 't' not in rec and pc.r('ip') == ev and pc.r('cs') == k.useg: rec['t'] = pc.us
    k.hooks.append(h)
    t0 = k.pc.us; k.pc.keys.append(key); k.settle()
    k.hooks.remove(h)
    return (rec['t'] - t0) / 1e3 if 't' in rec else -1

def disk_file(k, name):
    return fatcheck.read_files(bytes(k.pc.drives[0].img)).get('A:\\' + name)

def t_write():
    print('== Write (WRITE.RUN)')
    k = write_open()
    shot(k, 'write_open')
    check('a Text file opens in Write', lines(k)[0].strip().endswith('pm') and has(k, 'Write: NOTES.TXT') and has(k, 'jumps over')
          and has(k, 'Line 1 of 5'), screen(k))
    check('tabs show as spaces to the next stop', any(l.startswith('        Tabbed line') for l in lines(k)), lines(k))
    k.key('Hello. ')
    k.key(ktest.DOWN, K_END); k.key(' high')
    check('typing inserts; Down, End', has(k, 'jumps over high') and has(k, 'Changed'), screen(k))
    k.key(K_CHOME, K_CRIGHT, K_CRIGHT, CODE['E'], K_CRIGHT)
    shot(k, 'write_select')
    check('Erase: the band asks for a selection', k.band()[0] == 'Erase: Make a selection and confirm', k.band())
    k.key(ktest.ENTER)
    k.key(ktest.DOWN, K_HOME, CODE['M'], ktest.DOWN, ktest.ENTER)
    check('Move: then it asks for the destination', k.band()[0] == 'Move: Point to destination and confirm', k.band())
    k.key(K_CEND, ktest.ENTER)
    k.key(K_CHOME, CODE['D'], K_END, ktest.ENTER, K_CEND, ktest.ENTER)   # Duplicate line 1 at the end
    k.key(K_CHOME, CODE['F']); k.key('lazy'); shot(k, 'write_find_form'); k.key(ktest.ENTER, ktest.ENTER, ktest.ENTER)
    shot(k, 'write_found')
    check('Find: found, Confirm for next', k.band()[0] == 'Find: Confirm for next occurrence' and has(k, 'Line 2 of'), (k.band(), screen(k)))
    k.key(ktest.ENTER)
    check('Find again: "No further matches to text specified"', any('No further matches' in l for l in k.band()), k.band())
    k.key(ktest.ENTER)
    k.key(K_CHOME, CODE['S']); k.key('line'); k.key(ktest.ENTER); k.key('LINE'); k.key(ktest.ENTER, ktest.ENTER, ktest.ENTER, ktest.RIGHT, ktest.ENTER)
    check('Substitute, without verification: 2', any('Number of substitutions: 2' in l for l in k.band()), k.band())
    k.key(ktest.ENTER)
    k.key(K_CHOME, CODE['S']); k.key('the'); k.key(ktest.ENTER); k.key('THE'); k.key(ktest.ENTER, ktest.ENTER, ktest.ENTER, ktest.LEFT, ktest.ENTER)
    check('Substitute with verification: it asks', k.band()[0] == 'Substitute this occurrence of the text?', k.band())
    k.key('n'); k.key('y'); k.key(ktest.ESC)
    check('Substitute with verification: N skips, Y replaces', any('Number of substitutions: 1' in l for l in k.band()), k.band())
    k.key(ktest.ENTER)
    k.key(CODE['J']); k.key('3'); k.key(ktest.ENTER)
    check('Jump to line 3', has(k, 'Line 3 of'), screen(k))
    k.key(CODE['U'])
    check('Usage: characters, lines, room', any(re.search(r'\d+ characters in \d+ lines; room for \d+ more', l) for l in k.band()), k.band())
    k.key(ktest.ENTER)
    k.key(K_CODE_HELP)
    check('CODE-? opens Write\'s help', has(k, 'Begin       CODE-B'), screen(k))
    k.key('x')
    k.key(ktest.F1)
    shot(k, 'write_help')
    check('help: GRiDWrite\'s command summary', has(k, 'Begin       CODE-B    Restart the selection') and has(k, 'Cancel      CODE-ESC'), screen(k))
    k.key('x')
    k.key(CODE['Q'])
    check('Quit asks', k.band()[0] == 'Quit: Confirm to save and exit', k.band())
    k.key(ktest.ENTER)
    want = (b'Hello. The brown fox\r\nTHE lazy dog.\r\n\tTabbed LINE\r\nlast LINEjumps over high\r\nHello. The brown fox')
    got = disk_file(k, 'NOTES.TXT')
    check('saved with CR LF: Erase, Move, Duplicate, Substitute all in it', got == want, (got, want))
    files = fatcheck.read_files(bytes(k.pc.drives[0].img))
    probs, _ = fatcheck.check(bytes(k.pc.drives[0].img))
    check('no NOTES.$$$ left, the disk consistent', 'A:\\NOTES.$$$' not in files and not probs, (sorted(files), probs))
    check('back in the Executive', k.band()[0] == 'Select a file and confirm', k.band())

    # Return: a full redraw, the cursor on the new line (not the last row)
    k = write_open()
    ws = run_syms('apps/WRITE.ASM')
    wv = lambda n: k.pc.u16(k.useg, k.u16('run_base') + ws[n])
    k.key(ktest.ENTER)
    check('after Return the cursor is drawn on row 2 (a full redraw)', wv('cur_r') == 1 and wv('cur_c') == 0 and has(k, 'Line 2 of 6'),
          (wv('cur_r'), wv('cur_c')))
    k.key(K_INS, ktest.RIGHT)
    check('Ins: the old cursor shape goes (the first letter is plain again)', lines(k)[1].startswith('The quick'),
          lines(k)[:4])
    k.key(K_INS, ktest.ESC, ktest.ENTER)

    # Substitute backward doesn't run into its own replacements
    k = write_open('BACK.TXT', b'xaaab yaab')
    k.key(K_CEND, CODE['S']); k.key('ab'); k.key(ktest.ENTER); k.key('b')
    k.key(ktest.ENTER, ktest.ENTER, ktest.RIGHT, ktest.ENTER, ktest.RIGHT, ktest.ENTER)
    check('Substitute backward: 2, not 5', any('Number of substitutions: 2' in l for l in k.band()), k.band())
    k.key(ktest.ENTER, CODE['Q'], ktest.ENTER)
    check('... and the text is right', disk_file(k, 'BACK.TXT') == b'xaab yab', disk_file(k, 'BACK.TXT'))

    # Write to a file called X.$$$ (the temporary file's own kind of name)
    k = write_open()
    k.key(CODE['T'], ktest.RIGHT, ktest.ENTER); k.key('COPY.$$$'); k.key(ktest.ENTER)
    k.key(ktest.ESC, ktest.ENTER)
    check('Transfer, Write to a file named COPY.$$$: it is there', disk_file(k, 'COPY.$$$') == TEXT, disk_file(k, 'COPY.$$$'))

    # Cancel keeps the file as it was
    k = write_open()
    k.key('junk'); k.key(K_CODE_ESC)
    check('CODE-ESC: Cancel asks (changed)', k.band()[0] == 'Cancel: Confirm to exit without saving (changed)', k.band())
    k.key(ktest.ESC); k.key(ktest.ESC)
    check('ESC: Cancel asks (changed)', k.band()[0] == 'Cancel: Confirm to exit without saving (changed)', k.band())
    k.key(ktest.ENTER)
    check('Cancel: the file is as it was', disk_file(k, 'NOTES.TXT') == TEXT)

    # a new file with CODE-W
    img = image('wnew.img', WRITE)
    k = ktest.KPC(img); k.start()
    k.key(CODE['W'])
    check('CODE-W: Write with a new file', has(k, 'Write: (new)'), screen(k))
    k.key('first line'); k.key(ktest.ENTER); k.key('second')
    k.key(CODE['Q'], ktest.ENTER)
    check('Quit on a new file asks for its name', has(k, 'Save as'), screen(k))
    k.key('memo'); k.key(ktest.ENTER)
    check('... saved as MEMO.TXT', disk_file(k, 'MEMO.TXT') == b'first line\r\nsecond', disk_file(k, 'MEMO.TXT'))

    # a big file: Ctrl-End, the count, the same bytes back
    big = b''.join(b'%05d The quick brown fox jumps over the lazy dog, again and again\r\n' % i for i in range(600))
    k = write_open('BIG.TXT', big)
    check('a 41 KB file opens', has(k, 'Line 1 of 601'), screen(k))
    t0 = k.pc.us
    k.key(K_CEND)
    check('Ctrl-End: the last line (%.2f s)' % ((k.pc.us - t0) / 1e6), has(k, 'Line 601 of 601') and has(k, '00599 The quick'), screen(k))
    topline = lambda: k.pc.u16(k.useg, k.u16('run_base') + run_syms('apps/WRITE.ASM')['topline'])
    k.key(K_PGUP)
    check('PgUp', has(k, 'Line 583 of 601'), screen(k))
    check('... and the text is redrawn (top row: line %d; it stayed as it was)' % topline(), lines(k)[1].startswith('%05d' % topline()), lines(k)[1:3])
    dt = busy(k, ord('X'))
    check('typing a key on a big file: %.1f ms to the next key (its row only)' % dt, 0 < dt < 20, dt)
    dt = busy(k, ktest.BKSP)
    check('Backspace: %.1f ms' % dt, 0 < dt < 20, dt)
    dt = busy(k, 0x1C0D)
    check('Return (every row below moves): %.1f ms' % dt, 0 < dt < 200, dt)
    k.key(ktest.BKSP)
    k.key(K_CHOME, K_PGDN)
    # (the cursor's cell doesn't read back: compare from the second column)
    check('PgDn redraws the text (top row: line %d)' % topline(), topline() > 0 and lines(k)[1][1:5] == ('%05d' % topline())[1:], lines(k)[1:3])
    k.key(CODE['J']); k.key('300'); k.key(ktest.ENTER)
    check('Jump to line 300 redraws the text (top row: line %d)' % topline(),
          has(k, 'Line 300 of 601') and lines(k)[1][1:5] == ('%05d' % topline())[1:] and has(k, '0299 The quick'), (lines(k)[1:3], k.band()))
    k.key(K_CHOME, CODE['T'])
    check('Transfer: Save, Write to a file, Include a file', has(k, 'Write to a file') and has(k, 'Include a file'), screen(k))
    k.key(ktest.ESC)
    k.key(CODE['Q'], ktest.ENTER)
    check('... saved byte for byte the same', disk_file(k, 'BIG.TXT') == big)

    # a write-protected disk: Quit says why, and stays
    k = write_open()
    k.key('more ')
    k.pc.drives[0].wp = True
    k.key(CODE['Q'], ktest.ENTER)
    check('write-protected: "Disk is write-protected", still in Write', any('write-protected' in l for l in k.band()) and has(k, 'Write: NOTES.TXT'),
          (k.band(), screen(k)))
    k.key(ktest.ENTER)
    k.pc.drives[0].wp = False
    k.key(CODE['Q'], ktest.ENTER)
    check('... tab off, Quit saves', disk_file(k, 'NOTES.TXT') == b'more ' + TEXT, disk_file(k, 'NOTES.TXT'))

    # Include a file at the cursor
    p2 = os.path.join(OUT, 'PART.TXT'); open(p2, 'wb').write(b'INCLUDED\r\n')
    k = write_open(extra=(p2,))
    k.key(CODE['T'], ktest.RIGHT, ktest.RIGHT, ktest.ENTER)
    k.key('PART.TXT'); k.key(ktest.ENTER)
    k.key(CODE['Q'], ktest.ENTER)
    check('Transfer, Include: the file goes in at the cursor', disk_file(k, 'NOTES.TXT') == b'INCLUDED\r\n' + TEXT, disk_file(k, 'NOTES.TXT'))

    # the mouse: a click puts the cursor there
    k = write_open(mouse=True)
    click(k, 6 * 8 + 4, 24 + 2 * 16 + 8)
    check('a click in the text: the cursor there', has(k, 'Line 3 of 5   Column 7'), screen(k))

    # a click after Find: back to editing
    k = write_open(mouse=True)
    k.key(CODE['F']); k.key('lazy'); k.key(ktest.ENTER, ktest.ENTER, ktest.ENTER)
    click(k, 8 * 3, 24 + 8)            # the first text row
    check('a click in the text after Find: back to editing (the band and the highlight went on)',
          k.band()[0].startswith('Type, or choose a command'), k.band())

# ---------------------------------------------------------------------
def t_memory():
    print('== memory')
    img = image('mem.img', MEMSZ, os.path.join(GOS, 'src', 'GRIDCMD.COM'))
    k = ktest.KPC(img); k.start()
    out = k.run_file('MEMSZ.COM', 20)
    m = re.search(r'([\d.]+) KB for programs', out)
    kb = float(m.group(1)) if m else 0
    check('a DOS program gets %.1f KB (0.2.2: 570.7 KB; the INT 33h mouse costs 2 KB): the directory buffer is lent while it runs' % kb, kb >= 569.4, out[-200:])
    check('afterwards the Executive has its whole list again', k.u16('ent_max') == 240 and 'MEMSZ.COM' in k.exec_list(), k.u16('ent_max'))
    img = image('tsr.img', TSR, SYSTEM, MEMSZ)
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    u0 = k.useg
    k.run_file('TSR.COM', 10)
    check('... "TSR.COM ended" stays in the band, and the selection stays on it, after the move',
          k.band()[0] == 'TSR.COM ended' and k.exec_list()[k.u16('sel')] == 'TSR.COM', (k.band(), k.u16('sel')))
    k.key(ktest.ENTER)
    check('a TSR right after the UI block: the UI block moves past it', k.useg != u0 and k.u16('ent_max') == 240 and
          k.exec_list() == ['GRIDOS.SYS', 'MEMSZ.COM', 'SYSTEM.RUN', 'TSR.COM'], (hex(u0), hex(k.useg), k.u16('ent_max'), k.exec_list()))
    off, seg = struct.unpack('<HH', k.pc.rd(0, 0x24 * 4, 4))
    moff, mseg = struct.unpack('<HH', k.pc.rd(0, 0x0B * 4, 4))
    m33seg = k.pc.u16(0, 0x33 * 4 + 2)
    check('... the kernel, INT 24h, the mouse and INT 33h know where it went', k.pc.u16(0x60, k.Y['ui_seg']) == k.useg and seg == k.useg and
          mseg == k.useg and m33seg == k.useg, (hex(seg), hex(mseg), hex(m33seg)))
    k.key(CODE['U'])
    check('... and .RUN programs load again (System)', has(k, 'Free for programs'), screen(k))
    k.key(ktest.ESC)
    out = k.run_file('MEMSZ.COM', 20)
    check('... and DOS programs still run', 'KB for programs' in out and k.band()[0] == 'MEMSZ.COM ended', (out[-100:], k.band()))
    k.key(ktest.ENTER)
    click(k, 40, 24 + 16 * 1 + 8)
    check('... and the mouse still works (a click selects)', k.u16('sel') == 1, k.u16('sel'))

# ---------------------------------------------------------------------
def t_exec():
    print('== the Executive')
    inner = os.path.join(OUT, 'INNER.TXT'); open(inner, 'wb').write(b'inside\r\n')
    odd = os.path.join(OUT, 'ODD.TX'); open(odd, 'wb').write(b'x')
    img = image('exec.img', 'DOS.330\\', 'DOS.330\\INNER.TXT=' + inner, odd)
    k = ktest.KPC(img); k.start()
    check('a subject with an extension is listed', 'DOS.330' in k.exec_list(), k.exec_list())
    k.select('DOS.330'); k.key(ktest.ENTER)
    check('... and opens (CHDIR was given only its first 8 characters)', 'INNER.TXT' in k.exec_list(), (k.exec_list(), k.band()))
    k.select('..'); k.key(ktest.ENTER)
    k.select('ODD.TX'); k.key(ktest.ENTER)
    check('an unknown short kind: "ODD  TX - nothing opens this kind yet" (no stray spaces)',
          any('ODD  TX - nothing opens' in l for l in k.band()), k.band())
    k.key(ktest.ENTER)
    # more files than the list holds (in a subject: the root has 224 slots)
    empty = os.path.join(OUT, 'EMPTY.DAT'); open(empty, 'wb').write(b'')
    img = image('many.img', 'MANY\\', *['MANY\\F%03d.DAT=%s' % (i, empty) for i in range(245)])
    k = ktest.KPC(img); k.start()
    k.select('MANY'); k.key(ktest.ENTER)
    check('more entries than fit (246 > 240): the band says only the first 240 are listed',
          any('Only the first 240 are listed' in l for l in k.band()) and k.u16('nent') == 240, (k.band(), k.u16('nent')))

# ---------------------------------------------------------------------
GRIDF = b''.join(bytes(g) for c, g in sorted(__import__('pcemu').load_font(os.path.join(GOS, 'src', 'FONT.INC')).items()))

def core_font(k): return bytes(k.pc.rd(k.useg, k.Y['font'], 1536))

def cell(k, col, y0):
    """The 16 bytes of the character cell at column col, rows y0..y0+15."""
    return bytes(k.pc.rd(0xB800, (y & 3) * 0x2000 + (y >> 2) * 80 + col, 1)[0] for y in range(y0, y0 + 16))

def reboot(k, name):
    p = os.path.join(OUT, name); open(p, 'wb').write(bytes(k.pc.drives[0].img))
    k2 = ktest.KPC(p); k2.pc.mouse = True; k2.start()
    return k2

def to_display(k):
    k.key(CODE['U'])
    for _ in range(5): k.key(ktest.DOWN, settle=False)
    k.settle()

def t_font():
    print('== fonts (System, Display)')
    term = open(TERMFNT, 'rb').read()
    img = image('font.img', SYSTEM, TERMFNT, DEFRAG)
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    check('GRiD\'s font at the start (no GRIDOS.INI)', core_font(k) == GRIDF)
    to_display(k)
    shot(k, 'system_display')
    check('Display: the font in use and the fonts on the disk', has(k, 'GRiD (built in)') and has(k, 'TERMINUS.FNT')
          and has(k, 'Fonts on this disk:') and 'RETURN: the next font' in ' '.join(k.band()), (screen(k), k.band()))
    k.key(ktest.ENTER)
    shot(k, 'system_display_terminus')
    tF = term[(ord('F') - 32) * 16:(ord('F') - 31) * 16]
    check('Return: TERMINUS.FNT is the font, the screen redrawn in it ("Font" in Terminus)', core_font(k) == term
          and has(k, 'TERMINUS.FNT') and cell(k, 20, 32) == tF, (screen(k), cell(k, 20, 32).hex()))
    check('... and GRIDOS.INI says so', disk_file(k, 'GRIDOS.INI') == b'FONT=TERMINUS.FNT\r\n', disk_file(k, 'GRIDOS.INI'))
    k.key(ktest.ESC)
    k = reboot(k, 'font2.img')
    check('after a restart: TERMINUS.FNT from GRIDOS.INI', core_font(k) == term)
    # the saver's DEFRAG draws its map in the same font
    t = struct.unpack('<H', k.pc.rd(0, 0x46C, 2))[0]
    k.wr('lastact', struct.pack('<H', (t - 5462 + 18) & 0xFFFF))
    for _ in range(60):                 # until DEFRAG's map is up
        k.pc.run_for(0.1)
        if has(k, 'Drive A:'): break
    tD = term[(ord('D') - 32) * 16:(ord('D') - 31) * 16]
    check('the screen saver\'s DEFRAG uses it too ("Drive A:" in Terminus)', has(k, 'Drive A:') and cell(k, 1, 0) == tD,
          (cell(k, 1, 0).hex(), tD.hex(), lines(k)[:1]))
    k.key(ktest.ESC); k.settle(8)
    to_display(k)
    k.key(ktest.ENTER)
    check('Return again: GRiD\'s font, and GRIDOS.INI goes (nothing else in it)', core_font(k) == GRIDF and disk_file(k, 'GRIDOS.INI') is None,
          disk_file(k, 'GRIDOS.INI'))
    # other lines in GRIDOS.INI stay; any case; a missing or wrong-sized file
    ini = os.path.join(OUT, 'GRIDOS.INI'); open(ini, 'wb').write(b'KEYS=1\r\nfont=terminus.fnt\r\nLAST=2')
    k = ktest.KPC(image('font3.img', SYSTEM, TERMFNT, ini)); k.pc.mouse = True; k.start()
    check('"font=terminus.fnt" among other lines: Terminus at the start', core_font(k) == term)
    to_display(k)
    k.key(ktest.ENTER)
    check('... Return: GRiD\'s again, the other lines kept', core_font(k) == GRIDF and disk_file(k, 'GRIDOS.INI') == b'KEYS=1\r\nLAST=2\r\n',
          disk_file(k, 'GRIDOS.INI'))
    open(ini, 'wb').write(b'FONT=NOSUCH.FNT\r\n')
    bad = os.path.join(OUT, 'BAD.FNT'); open(bad, 'wb').write(term[:1000])
    k = ktest.KPC(image('font4.img', SYSTEM, bad, ini)); k.start()
    check('GRIDOS.INI names a missing file: GRiD\'s font, no harm', core_font(k) == GRIDF and 'SYSTEM.RUN' in k.exec_list())
    to_display(k)
    k.key(ktest.ENTER)
    check('a .FNT of the wrong size is passed over (GRiD\'s stays)', core_font(k) == GRIDF and not k.crashed, screen(k))

# ---------------------------------------------------------------------
def t_saver():
    print('== the screen saver while a program runs')
    k = write_open(extra=(os.path.join(GOS, 'src', 'DEFRAG.COM'),))
    k.key('typed ')
    t = struct.unpack('<H', k.pc.rd(0, 0x46C, 2))[0]
    k.wr('lastact', struct.pack('<H', (t - 5462 + 18) & 0xFFFF))
    k.pc.run_for(4)
    dark = not any('Write' in l for l in lines(k)) and not any('Defrag' in l for l in lines(k))
    check('5 minutes idle in Write: the dark clock, no DEFRAG', dark, screen(k))
    k.key(ktest.DOWN)
    check('a key: Write back as it was', has(k, 'Write: NOTES.TXT') and has(k, 'he quick brown fox') and has(k, 'typed') and has(k, 'Line 1 of 5') and
          k.band()[0].startswith('Type'), (screen(k), k.band()))
    k.key(ktest.DOWN)
    check('... and goes on working', has(k, 'Line 2 of 5'), screen(k))


# ---------------------------------------------------------------------
def start_dos(k, name):
    """Start a DOS program from the Executive; run until it waits for a key."""
    k.select(name)
    k.pc.tty.clear()
    k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() != 0x40, 5)
    k.settle()

def tty_lines(k): return ''.join(k.pc.tty).replace('\r', '').split('\n')
def tty_line(k, name):
    for l in tty_lines(k):
        if l.startswith(name + ':'): return l.split(':', 1)[1].split()
    return None
def tcell(k, col, row): return k.pc.rd(0xB800, (row * 80 + col) * 2, 2)

ARROW_C = (0x0000, 0x4000, 0x6000, 0x7000, 0x7800, 0x7C00, 0x7E00, 0x7F00, 0x7F80, 0x7C00, 0x6C00, 0x4600, 0x0600, 0x0300, 0x0300, 0x0000)
def arrow_bits(x, y, hx, hy, H, two):
    """(bit, row) set by the arrow's cursor mask on a blank screen: masks
    apply bit for bit (in modes 4/5 two bits are a pixel; x and the hot
    spot are virtual pixels, one bit each)"""
    b0 = x - hx
    if two: b0 &= ~1
    out = set()
    for r in range(16):
        yy = y - hy + r
        if not 0 <= yy < H: continue
        for c in range(16):
            if 0 <= b0 + c < 640 and ARROW_C[r] >> (15 - c) & 1: out.add((b0 + c, yy))
    return out

def screen_bits(k, H, banks):
    v, out = k.pc.rd(0xB800, 0, 0x8000), set()
    sh = {2: 1, 4: 2}[banks]
    for y in range(H):
        base = (y & (banks - 1)) * 0x2000 + (y >> sh) * 80
        for xb in range(80):
            b = v[base + xb]
            for i in range(8):
                if b & 0x80 >> i: out.add((xb * 8 + i, y))
    return out

def t_mouse():
    print('== INT 33h for DOS programs')
    img = image('m33.img', M33TEST, MEMSZ)
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    seen = set()                        # the port's IER while the program runs
    k.hooks.append(lambda pc: seen.add(pc.uart['ier']) if pc.mode() != 0x40 else None)
    out = k.run_file('MEMSZ.COM', 20)
    k.hooks.clear()
    ier = max(seen) if seen else None
    check('a program that doesn\'t ask for the mouse: its port is left alone (%s)' % out.strip().split('\n')[-1][:30],
          'KB for programs' in out and ier == 0 and k.pc.uart['ier'] & 1, (ier, out[-80:]))
    v = struct.unpack('<HH', k.pc.rd(0, 0x33 * 4, 4))
    check('INT 33h is the core\'s', v == (k.Y['int33_ui'], k.useg), (v, hex(k.useg)))
    start_dos(k, 'M33TEST.COM')
    check('reset: AX = FFFFh, 2 buttons', tty_line(k, 'reset')[:2] == ['FFFF', '0002'], tty_line(k, 'reset'))
    check('version 6.26, serial, IRQ 3', tty_line(k, 'version')[1:3] == ['0626', '0203'], tty_line(k, 'version'))
    c = tcell(k, 40, 12)
    check('the pointer shows in the middle as an inverse cell', c[1] == 0x70, c)
    k.pc.mouse_move(40, 20); k.pc.run_for(0.05)
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05)
    check('it follows the mouse (and the old cell is back)', tcell(k, 45, 13)[1] == 0x70 and tcell(k, 40, 12)[1] == 0x07, (tcell(k, 45, 13), tcell(k, 40, 12)))
    k.key(ktest.ENTER)
    check('position: 8 mickeys a pixel across, 16 down (360, 110)', tty_line(k, 'pos')[1:] == ['0000', '0168', '006E'], tty_line(k, 'pos'))
    check('one press and one release of the left button, where', tty_line(k, 'press')[1:] == ['0001', '0168', '006E'] and
          tty_line(k, 'release')[1:] == ['0001', '0168', '006E'], (tty_line(k, 'press'), tty_line(k, 'release')))
    check('mickeys counted (40, 20)', tty_line(k, 'mickeys')[2:] == ['0028', '0014'], tty_line(k, 'mickeys'))
    check('ranges (one given backwards) hold the position', tty_line(k, 'range')[2:] == ['0064', '0032'], tty_line(k, 'range'))
    k.pc.mouse_move(8, 0); k.pc.run_for(0.05)
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05)
    k.key(ktest.ENTER)
    ev = tty_line(k, 'events')
    check('the event handler is called: move, press, release, with the position', ev and int(ev[0], 16) >= 3 and ev[1:] == ['0007', '006C', '0032'], ev)
    check('hidden: the cell is as it was', tcell(k, 13, 6)[1] == 0x07, tcell(k, 13, 6))
    k.key(ktest.ENTER)
    check('shown again', tcell(k, 13, 6)[1] == 0x70, tcell(k, 13, 6))
    k.pc.wr(0xB800, (6 * 80 + 13) * 2, b'Z\x1e')
    k.key(ktest.ENTER)
    check('a cell the program wrote over stays as written', tcell(k, 13, 6) == b'Z\x1e', tcell(k, 13, 6))
    k.key(ktest.ENTER)
    check('mode 4: reset knows 640 x 200', tty_line(k, 'max')[2:] == ['027F', '00C7'], tty_line(k, 'max'))
    gfx = lambda: b''.join(k.pc.rd(0xB800, 0x2000 * (y & 1) + (y >> 1) * 80 + 40, 2) for y in range(100, 116))
    g = gfx()
    check('mode 4: the arrow is drawn at (160, 100)', g[2] == 0x40 and any(g), g.hex())
    k.key(ktest.ENTER)
    check('... and taken away', not any(gfx()), gfx().hex())
    k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 10); k.settle()
    check('the program ends with the pointer on and a handler set: the Executive is back', k.band()[0] == 'M33TEST.COM ended' and not k.crashed, k.band())
    check('... the pointer is off and the handler forgotten', k.u16('m33_cnt') == 0xFFFF and k.u16('m33_hmask') == 0)
    k.key(ktest.ENTER)
    click(k, 40, 24 + 16 * 1 + 8)
    check('... and the Executive\'s mouse works (a click selects)', k.u16('sel') == 1, k.u16('sel'))
    shot(k, 'mouse_back')
    # no mouse: reset says so
    k = ktest.KPC(image('m33n.img', M33TEST)); k.start()
    start_dos(k, 'M33TEST.COM')
    check('without a mouse, reset returns AX = 0', tty_line(k, 'reset')[:2] == ['0000', '0000'], tty_line(k, 'reset'))
    check('... and the other calls do nothing (no version, no pointer)', tty_line(k, 'version')[1] != '0626' and tcell(k, 40, 12)[1] == 0x07,
          (tty_line(k, 'version'), tcell(k, 40, 12)))
    for i in range(7): k.key(ktest.ENTER)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 10); k.settle()
    check('... and the program runs to its end', k.band()[0] == 'M33TEST.COM ended', k.band())
    # the graphics pointer, bit for bit; the reset and shape asked with DF set
    k = ktest.KPC(image('m33g.img', M33['M33GFX'])); k.pc.mouse = True; k.start()
    rows0 = k.rd('rowtab', 800)
    start_dos(k, 'M33GFX.COM')
    for x, y, hx, hy, H, banks, two, what in ((0, 0, 5, 7, 400, 4, 0, 'mode 40h, top left, hot spot (5, 7)'),
                                              (639, 399, 5, 7, 400, 4, 0, 'mode 40h, bottom right'),
                                              (333, 201, 5, 7, 400, 4, 0, 'mode 40h, an odd column'),
                                              (630, 190, 0, 0, 200, 2, 0, 'mode 6, clipped right and below'),
                                              (101, 50, 5, 7, 200, 2, 1, 'mode 4, hot spot in virtual pixels')):
        e, a = arrow_bits(x, y, hx, hy, H, two), screen_bits(k, H, banks)
        check('pointer: ' + what, e == a and e, (len(e), len(a), sorted(e - a)[:4], sorted(a - e)[:4]))
        k.key(ktest.ENTER, settle=False); k.pc.run_for(0.05)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 10); k.settle()
    check('DF set by the program: the reset and the shape still land where they should', k.rd('rowtab', 800) == rows0 and
          k.band()[0] == 'M33GFX.COM ended', k.band())
    # a program that ends inside its event handler; then the next one's handler
    k = ktest.KPC(image('m33q.img', M33['M33QUIT'], M33TEST)); k.pc.mouse = True; k.start()
    start_dos(k, 'M33QUIT.COM')
    k.pc.mouse_move(3, 0); k.pc.run_for(0.1)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 10); k.settle()
    check('a program can end from its event handler', k.band()[0] == 'M33QUIT.COM ended, exit code 1' and k.rd('m33_busy', 1) == b'\0', k.band())
    start_dos(k, 'M33TEST.COM'); k.key(ktest.ENTER)
    k.pc.mouse_move(8, 0); k.pc.run_for(0.05)
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05)
    k.key(ktest.ENTER)
    ev = tty_line(k, 'events')
    check('... and the next program\'s handler is called', ev and int(ev[0], 16) >= 3, ev)
    # under the shell: a handler left by a program that ended must not reach
    # the next program loaded at the same place
    k = ktest.KPC(image('m33s.img', GRIDCMD, M33['M33HSET'], M33['M33HVIC'])); k.pc.mouse = True; k.start()
    start_dos(k, 'GRIDCMD.COM')
    k.key('M33HSET\r')
    check('a program that ends without a reset: its handler is forgotten', k.u16('m33_hmask') == 0 and k.u16('m33_hseg') == 0,
          (hex(k.u16('m33_hmask')), hex(k.u16('m33_hseg'))))
    k.key('M33HVIC\r', settle=False); k.pc.run_for(0.5)
    k.pc.mouse_move(5, 0); k.pc.run_for(0.1); k.pc.mouse_move(5, 0); k.pc.run_for(0.1)
    k.key(' ')
    check('... and never reaches the next program at the same segment', any(l.startswith('hits: 0000') for l in tty_lines(k)) and not k.crashed,
          [l for l in tty_lines(k) if 'hits' in l])
    # a packet arriving while fn 0Ch asks the kernel for the PSP (STI there)
    k = ktest.KPC(image('m33r.img', M33TEST)); k.pc.mouse = True; k.start()
    start_dos(k, 'M33TEST.COM')
    st = {'armed': True}
    def h(pc):
        if st['armed'] and pc.r('cs') == 0x60 and pc.r('ip') == k.Y['int21'] + 1 and pc.r('ax') >> 8 == 0x62:
            pc.mouse_move(1, 0); pc.mu.emu_stop(); st['armed'] = False
    k.hooks.append(h)
    k.key(ktest.ENTER)
    k.hooks.clear()
    k.pc.mouse_move(8, 0); k.pc.run_for(0.05)
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05)
    k.key(ktest.ENTER)
    ev = tty_line(k, 'events')
    check('a mouse packet while the handler is being set doesn\'t lose it', not st['armed'] and ev and int(ev[0], 16) >= 3, (st, ev))
    # TM5000G, which found no mouse on 0.3
    if not os.path.exists(TM5000G):
        print('(no TM5000G.EXE: skipped)'); return
    chip = sim7210.NEC7210(sim7210.bus())
    k = ktest.KPC(image('m33tm.img', 'TM5000G.EXE=' + TM5000G), chip=chip); k.pc.mouse = True; k.start()
    k.select('TM5000G.EXE'); k.pc.tty.clear(); k.key(ktest.ENTER, settle=False); k.settle(40)
    check('TM5000G: "Mouse support enabled."', 'Mouse support enabled.' in ''.join(k.pc.tty), ''.join(k.pc.tty)[-300:])
    k.key(ktest.ENTER)
    check('TM5000G: "Mouse: ON" in the main menu', 'Mouse: ON' in k.pc.text_screen(), k.pc.text_screen())
    for i in range(4): k.pc.mouse_move(0, -28 & 0xFF); k.pc.run_for(0.05)
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.settle(5)
    check('TM5000G: a click on "Configure Modules" opens it', 'Module Configuration' in k.pc.text_screen(), k.pc.text_screen()[:300])
    k.key(ktest.ESC); k.key('0', settle=False)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 10); k.settle()
    check('TM5000G: back in the Executive', any('TM5000G.EXE ended' in l for l in k.band()), k.band())

if __name__ == '__main__':
    t0 = time.time()
    build()
    only = [a for a in sys.argv[1:] if a.startswith('t_')]
    for t in (t_core, t_system, t_write, t_exec, t_font, t_memory, t_saver, t_mouse):
        if not only or t.__name__ in only: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
