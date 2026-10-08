"""Grid-OS 0.3: the UI core and the .RUN programs, in pcemu.

    python3 tests/test_apps.py [t_core t_system t_write t_exec t_font t_memory t_saver t_mouse t_form t_files] [shots]

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
    check('a DOS program gets %.1f KB (0.2.2: 570.7 KB; INT 33h and the File form cost 2.8 KB, the file commands 2.8 KB, the saver setting 0.2 KB, wildcards and making subjects 1.1 KB, deleting subjects 0.4 KB, '
          'screen capture 0.5 KB, the kernel\'s part of drive C: 0.2 KB, the saver\'s round of the disks and its switch 0.1 KB, '
          'copying subjects 0.9 KB): the directory buffer is lent while it runs' % kb, kb >= 562.5, out[-200:])
    check('afterwards the Executive has its whole list again', k.u16('ent_max') == 240 and 'MEMSZ.COM' in k.exec_list(), k.u16('ent_max'))
    # with EMS the disk cache is two EMS pages: programs get its 18 KB
    # (less the EMS manager's 2), and System says where it went
    k = ktest.KPC(image('mem_ems.img', MEMSZ, SYSTEM), ems_pages=88); k.start()
    out = k.run_file('MEMSZ.COM', 20)
    m = re.search(r'([\d.]+) KB for programs', out)
    kbe = float(m.group(1)) if m else 0
    check('with EMS a DOS program gets %.1f KB: the disk cache is in EMS (%.1f KB more)' % (kbe, kbe - kb),
          kbe >= kb + 16.0, out[-200:])
    k.key(ktest.ENTER)
    k.key(CODE['U'])
    m = re.search(r'Free for programs\s+([\d.]+) KB', screen(k))
    check('... System: "Disk cache  32 KB of EMS", and "Free for programs" is what MEMSZ got',
          has(k, '32 KB of EMS') and m and abs(float(m.group(1)) - kbe) < 1.0, screen(k))
    k.key(ktest.ESC)
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
    k.key(K_BTAB)
    check('a subject with an extension is listed', '  DOS.330' in subjects(k), subjects(k))
    k.key(ktest.ESC)
    to_subject(k, 'DOS.330')
    check('... and opens (CHDIR was given only its first 8 characters)', 'INNER.TXT' in k.exec_list(), (k.exec_list(), k.band()))
    to_subject(k, 'Root')
    k.select('ODD.TX'); k.key(ktest.ENTER)
    check('an unknown short kind: "ODD  TX - nothing opens this kind yet" (no stray spaces)',
          any('ODD  TX - nothing opens' in l for l in k.band()), k.band())
    k.key(ktest.ENTER)
    # more files than the list holds (in a subject: the root has 224 slots)
    empty = os.path.join(OUT, 'EMPTY.DAT'); open(empty, 'wb').write(b'')
    img = image('many.img', 'MANY\\', *['MANY\\F%03d.DAT=%s' % (i, empty) for i in range(245)])
    k = ktest.KPC(img); k.start()
    to_subject(k, 'MANY')
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
          and has(k, 'Fonts on the start-up disk:') and 'RETURN: the next font' in ' '.join(k.band()), (screen(k), k.band()))
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


def idle(k, ticks):
    """Make the Executive think it has been idle this many ticks; run a bit."""
    t = struct.unpack('<H', k.pc.rd(0, 0x46C, 2))[0]
    k.wr('lastact', struct.pack('<H', (t - ticks) & 0xFFFF))
    for _ in range(40):
        k.pc.run_for(0.1)
        if has(k, 'Drive A:'): break
    return has(k, 'Drive A:')

def t_saver_delay():
    print('== the screen saver\'s delay (System, Screen saver; GRIDOS.INI SAVER=)')
    img = image('svd.img', SYSTEM, DEFRAG, TERMFNT)
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    check('5 minutes to start with', k.rd('saver_min', 1) == b'\x05' and k.u16('saver_t') == 5460, (k.rd('saver_min', 1), k.u16('saver_t')))
    k.key(CODE['U'])
    for _ in range(6): k.key(ktest.DOWN, settle=False)
    k.settle()
    check('System: the Screen saver topic says 5 minutes', has(k, 'Screen saver') and has(k, 'Starts after') and has(k, '5 minutes')
          and 'RETURN: the next delay' in ' '.join(k.band()), (screen(k), k.band()))
    k.key(ktest.ENTER)
    check('Return: 10 minutes, at once, and GRIDOS.INI says SAVER=10', has(k, '10 minutes') and k.u16('saver_t') == 10920
          and disk_file(k, 'GRIDOS.INI') == b'SAVER=10\r\n', (screen(k), disk_file(k, 'GRIDOS.INI')))
    k.key(ktest.ENTER); k.key(ktest.ENTER)
    check('... 15, then 30 minutes', has(k, '30 minutes') and k.rd('saver_min', 1) == b'\x1e', screen(k))
    k.key(ktest.ENTER)
    check('... then never (SAVER=0)', has(k, 'never') and k.u16('saver_t') == 0xFFFF and disk_file(k, 'GRIDOS.INI') == b'SAVER=0\r\n',
          (screen(k), disk_file(k, 'GRIDOS.INI')))
    k.key(ktest.ESC)
    check('never: idle 30 minutes in the Executive, no saver', not idle(k, 30000) and not k.crashed, lines(k)[:2])
    k.key(CODE['U'])
    for _ in range(6): k.key(ktest.DOWN, settle=False)
    k.settle()
    k.key(ktest.ENTER)
    check('... then 1 minute', has(k, '1 minute') and disk_file(k, 'GRIDOS.INI') == b'SAVER=1\r\n', screen(k))
    k.key(ktest.ESC)
    check('1 minute: not after 50 s', not idle(k, 910), lines(k)[:2])
    check('... but after a minute (DEFRAG\'s map)', idle(k, 1092 + 18), lines(k)[:2])
    k.key(ktest.ESC); k.settle(8)
    # the font and the saver together in GRIDOS.INI, other lines kept
    k = reboot(k, 'svd2.img')
    check('after a restart: 1 minute from GRIDOS.INI', k.rd('saver_min', 1) == b'\x01', k.rd('saver_min', 1))
    to_display(k); k.key(ktest.ENTER); k.key(ktest.ESC)
    check('a font too: FONT= and SAVER= both in GRIDOS.INI', disk_file(k, 'GRIDOS.INI') == b'FONT=TERMINUS.FNT\r\nSAVER=1\r\n', disk_file(k, 'GRIDOS.INI'))
    ini = os.path.join(OUT, 'GRIDOS.INI'); open(ini, 'wb').write(b'KEYS=1\r\nsaver=2\r\nFONT=TERMINUS.FNT\r\n')
    k = ktest.KPC(image('svd3.img', SYSTEM, TERMFNT, ini)); k.start()
    check('"saver=2" (any case) before FONT=: both taken at start-up', k.rd('saver_min', 1) == b'\x02' and core_font(k) == open(TERMFNT, 'rb').read(),
          k.rd('saver_min', 1))
    k.key(CODE['U'])
    for _ in range(6): k.key(ktest.DOWN, settle=False)
    k.settle()
    k.key(ktest.ENTER)
    check('Return: 5 minutes again, its SAVER= line gone, the others kept', disk_file(k, 'GRIDOS.INI') == b'KEYS=1\r\nFONT=TERMINUS.FNT\r\n',
          disk_file(k, 'GRIDOS.INI'))
    ini2 = os.path.join(OUT, 'GRIDOS2.INI'); open(ini2, 'wb').write(b'SAVER=99\r\n')
    k = ktest.KPC(image('svd4.img', 'GRIDOS.INI=' + ini2)); k.start()
    check('SAVER=99: 30 minutes at most', k.rd('saver_min', 1) == b'\x1e' and k.u16('saver_t') == 32760, k.rd('saver_min', 1))


def t_saver_tidy():
    print('== the saver tidies the disks, or not (System, Screen saver, Space; GRIDOS.INI TIDY=0)')
    SPACE = 0x3920
    img = image('svt.img', SYSTEM, DEFRAG)
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    def topic(k):
        k.key(CODE['U'])
        for _ in range(6): k.key(ktest.DOWN, settle=False)
        k.settle()
    topic(k)
    tidy = lambda: next((l for l in lines(k) if 'Tidies the disks first' in l), '')
    check('Screen saver: "Tidies the disks first: yes", SPACE in the band and the text',
          tidy().rstrip().endswith('yes') and 'SPACE: tidy or not' in ' '.join(k.band()) and has(k, 'SPACE: tidy the disks first'),
          (screen(k), k.band()))
    k.key(SPACE)
    check('Space: "no" at once, GRIDOS.INI says TIDY=0', tidy().rstrip().endswith('no') and k.rd('sv_notidy', 1) == b'\x01'
          and disk_file(k, 'GRIDOS.INI') == b'TIDY=0\r\n', (tidy(), disk_file(k, 'GRIDOS.INI')))
    k.key(ktest.ENTER)
    check('... with a delay too: SAVER=10 and TIDY=0', disk_file(k, 'GRIDOS.INI') == b'SAVER=10\r\nTIDY=0\r\n', disk_file(k, 'GRIDOS.INI'))
    k.key(ktest.ESC)
    shown = idle(k, 10 * 1092 + 18)
    k.pc.run_for(2)
    dark = [l.strip() for l in lines(k) if len(l.strip()) > 2]
    check('idle 10 minutes: the dark clock at once, no DEFRAG', not shown and len(dark) == 2 and dark[0].endswith('m')
          and dark[1].count('-') == 2, dark)
    k.key(ktest.ESC); k.settle()
    k = reboot(k, 'svt2.img')
    check('after a restart: still not tidying (TIDY=0 taken)', k.rd('sv_notidy', 1) == b'\x01', k.rd('sv_notidy', 1))
    topic(k)
    k.key(SPACE)
    check('Space again: "yes", the TIDY= line gone', tidy().rstrip().endswith('yes') and k.rd('sv_notidy', 1) == b'\x00'
          and disk_file(k, 'GRIDOS.INI') == b'SAVER=10\r\n', (tidy(), disk_file(k, 'GRIDOS.INI')))
    k.key(ktest.ESC)
    check('... and the saver runs DEFRAG again', idle(k, 10 * 1092 + 18), lines(k)[:2])


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

# ---------------------------------------------------------------------
FORM_Y, ITEM_H = 244, 20                # the File form (EXEC.INC)
K_BTAB = 0x0F00

def focus(k): return k.rd('focus', 1)[0]           # 0 Title, 1 Device, 2 Subject
def subjects(k):
    """The Subject list: '' for Root, else NAME.EXT indented two per level."""
    out = []
    for i in range(k.u16('nsubj')):
        e = k.rd('entries', 14, i * 14)
        nm, ext = e[1:9].decode('latin-1').rstrip(), e[9:12].decode('latin-1').rstrip()
        out.append('  ' * e[0] + (nm + ('.' + ext if ext else '') if e[0] else 'Root'))
    return out
def form(k):
    """Device, Subject, Title, Kind values as shown."""
    rows = dict(k.ocr())
    return [rows.get(FORM_Y + i * ITEM_H, '')[14:].strip() for i in range(4)]
def outlined(k, item):
    """The outline's top line is drawn above form item 0..2 (Device, Subject, Title)."""
    y = FORM_Y - 2 + item * ITEM_H
    v = k.pc.rd(0xB800, (y & 3) * 0x2000 + (y >> 2) * 80 + 20, 40)
    return all(b == 0xFF for b in v)
def to_subject(k, name):
    """Outline Subject (Shift-Tab from Title), choose the subject, Return: its titles."""
    k.key(K_BTAB)
    want = [x.strip() for x in subjects(k)].index(name)
    for _ in range(40):
        if k.u16('sel') == want: break
        k.key(ktest.DOWN if k.u16('sel') < want else ktest.UP)
    k.key(ktest.ENTER)

def t_form():
    print('== the File form: Device, Subject, Title (GRiDManager-style; Tab too)')
    notes = os.path.join(OUT, 'BNOTES.TXT'); open(notes, 'wb').write(b'on drive B\r\n')
    a = image('forma.img', SYSTEM, WRITE, TERMFNT, 'DOS.330\\', 'DOS.330\\INNER.TXT=' + notes, 'DOS.330\\DEEP\\',
              'DOS.330\\DEEP\\X.TXT=' + notes, 'WORK\\')
    b = mkimg.build(os.path.join(OUT, 'formb.img'), ['NOTES.TXT=' + notes, 'DATA\\'])
    k = ktest.KPC(a, b=b); k.pc.mouse = True; k.start()
    check('the titles only (subjects are their own item); Title outlined', k.exec_list() == ['GRIDOS.SYS', 'SYSTEM.RUN', 'TERMINUS.FNT', 'WRITE.RUN']
          and focus(k) == 0 and outlined(k, 2) and not outlined(k, 0), k.exec_list())
    check('the form: Device Floppy A:, Subject Root, the title and its kind', form(k)[:3] == ['Floppy A:', 'Root', 'GRIDOS'] and form(k)[3].startswith('System'), form(k))
    k.key(CODE['W']); k.key(ktest.ESC); k.key(ktest.ENTER)    # (a .RUN and back: the place is kept)
    k.key(ktest.DOWN)
    k.key(ktest.TAB)
    check('Tab: Device outlined, the drives in the list, its prompt', focus(k) == 1 and outlined(k, 0) and k.u16('nent') == 2 and
          has(k, 'Floppy B:') and k.band()[0] == 'Device: Select item and confirm', (focus(k), k.band()))
    k.key(ktest.TAB)
    check('Tab: Subject outlined, Root and the subjects as a tree', focus(k) == 2 and outlined(k, 1) and
          subjects(k) == ['Root', '  DOS.330', '    DEEP', '  WORK'] and has(k, '    DEEP'), subjects(k))
    k.key(ktest.TAB)
    check('Tab: Title again, the same title chosen (nothing changed)', focus(k) == 0 and k.u16('sel') == 1 and form(k)[2] == 'SYSTEM', form(k))
    k.key(K_BTAB)
    check('Shift-Tab: back to Subject', focus(k) == 2, focus(k))
    k.key(ktest.ESC)
    check('ESC: Title', focus(k) == 0 and k.u16('sel') == 1, focus(k))
    to_subject(k, 'DEEP')
    check('a subject two down: its titles, the form says DOS.330\\DEEP', k.exec_list() == ['X.TXT'] and form(k)[1] == 'DOS.330\\DEEP', (k.exec_list(), form(k)))
    to_subject(k, 'DOS.330')
    check('a subject with an extension (CHDIR gets NAME.EXT)', k.exec_list() == ['INNER.TXT'], k.exec_list())
    # B:, by the Device item
    k.key(ktest.TAB); k.key(ktest.DOWN)
    check('Device: Down chooses B: at once', form(k)[0] == 'Floppy B:', form(k))
    k.key(ktest.ENTER)
    check('Return: Subject, on B:', focus(k) == 2 and subjects(k) == ['Root', '  DATA'], subjects(k))
    k.key(ktest.ENTER)
    check('Return: Title, B:\'s titles', focus(k) == 0 and k.exec_list() == ['NOTES.TXT'], k.exec_list())
    k.key(ktest.ENTER)
    check('a text file on B: opens in Write (from A:)', has(k, 'Write: NOTES.TXT') and has(k, 'n drive B'), screen(k))
    k.key(ktest.ESC); k.key(ktest.ENTER)
    k.key(CODE['U'])
    check('CODE-U from B:: System, from the start-up disk', has(k, 'Free for programs'), screen(k))
    for _ in range(5): k.key(ktest.DOWN, settle=False)
    k.settle()
    check('Display lists the fonts on the start-up disk (A:)', has(k, 'TERMINUS.FNT') and has(k, 'Fonts on the start-up disk:'), screen(k))
    k.key(ktest.ENTER)
    check('... and GRIDOS.INI goes to A:, not B:', disk_file(k, 'GRIDOS.INI') == b'FONT=TERMINUS.FNT\r\n' and
          fatcheck.read_files(bytes(k.pc.drives[1].img)).get('A:\\GRIDOS.INI') is None, disk_file(k, 'GRIDOS.INI'))
    k.key(ktest.ENTER); k.key(ktest.ESC)
    check('back in the Executive, still on B:', k.exec_list() == ['NOTES.TXT'] and form(k)[0] == 'Floppy B:', (k.exec_list(), form(k)))
    # the mouse: a click on an item outlines it; a second click on a choice goes on
    click(k, 3 * 8, FORM_Y + 4)
    check('a click on Device outlines it', focus(k) == 1, focus(k))
    click(k, 40, 24 + 8); click(k, 40, 24 + 8)
    check('a click on Floppy A:, and again: A:, Subject outlined', form(k)[0] == 'Floppy A:' and focus(k) == 2, (form(k), focus(k)))
    click(k, 3 * 8, FORM_Y + 2 * ITEM_H + 4)
    check('a click on Title: Title outlined, A:\'s titles (A: is still in DOS.330: each drive keeps its subject)',
          focus(k) == 0 and k.exec_list() == ['INNER.TXT'] and form(k)[1] == 'DOS.330', (focus(k), k.exec_list(), form(k)))
    k.key(ktest.TAB); k.key(ktest.RIGHT)
    check('Left / Right work as Up / Down in Device', form(k)[0] == 'Floppy B:', form(k))
    k.key(ktest.LEFT); k.key(ktest.ESC)
    # help: the items; the file commands CODE-C, CODE-D, CODE-M, CODE-R; CODE-P the prompt
    k.key(ktest.F1)
    hl = screen(k)
    check('help: Tab for the items; Copy, Erase, Move, Rename', 'Device, Subject, Title' in hl and 'CODE-C                   Copy the file' in hl
          and 'CODE-R' in hl and 'Rename the file' in hl and 'CODE-D                   Delete' in hl and 'CODE-M' in hl
          and 'CODE-P                   command prompt' in hl and 'CODE is the Alt key' in hl, hl)
    k.key(ktest.ENTER)
    k.key(CODE['R']); k.key(ktest.ESC); k.key(CODE['C']); k.key(ktest.ESC)
    check('CODE-R, CODE-D open their forms; ESC changes nothing', not k.crashed and k.exec_list() == ['INNER.TXT'] and k.pc.mode() == 0x40, k.where())
    # B: with no disk
    k.pc.drives[1].empty = True
    k.key(ktest.TAB); k.key(ktest.DOWN); k.key(ktest.ENTER, settle=False); k.settle(20)
    check('B: with no disk: Subject has Root only and the band says why', subjects(k) == ['Root'] and "Can't read the disk" in ' '.join(k.band())
          and not k.crashed, (subjects(k), k.band()))
    k.key(ktest.ENTER)
    k.key(K_BTAB); k.key(ktest.UP); k.key(ktest.ESC)
    check('... Shift-Tab, Up, ESC: back to A:', k.exec_list() == ['INNER.TXT'] and form(k)[0] == 'Floppy A:', (k.exec_list(), form(k), k.band()))
    # one drive
    k = ktest.KPC(a); k.start()
    k.key(ktest.TAB)
    check('one drive: Device lists Floppy A: alone', k.u16('nent') == 1 and form(k)[0] == 'Floppy A:', k.u16('nent'))

# ---------------------------------------------------------------------
def root_entry(img, name):
    """Offset of NAME.EXT's entry in the root directory of a disk image."""
    b = fatcheck.bpb(img)
    off = (b['res'] + b['nfat'] * b['spf']) * b['bps']
    nm, _, ext = name.partition('.')
    want = (nm.ljust(8) + ext.ljust(3)).encode()
    for i in range(b['nroot']):
        if bytes(img[off + 32 * i:off + 32 * i + 11]) == want: return off + 32 * i
    return None

def t_files():
    print('== the Executive: Copy, Erase, Move, Rename (verb, form, confirm)')
    notes = os.path.join(OUT, 'NOTES.TXT'); open(notes, 'wb').write(TEXT)
    BIG = bytes(range(256)) * 300                   # 76800 bytes: more than the 32 KB buffer twice over
    big = os.path.join(OUT, 'BIG.DAT'); open(big, 'wb').write(BIG)
    keep = os.path.join(OUT, 'KEEP.TXT'); open(keep, 'wb').write(b'keep\r\n')
    a = image('filesa.img', notes, big, keep, 'WORK\\')
    raw = bytearray(open(a, 'rb').read()); raw[root_entry(raw, 'KEEP.TXT') + 11] |= 1     # read-only
    open(a, 'wb').write(raw)
    b = mkimg.build(os.path.join(OUT, 'filesb.img'), ['DATA\\'])
    k = ktest.KPC(a, b=b); k.pc.mouse = True; k.start()
    A = lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
    B = lambda: fatcheck.read_files(bytes(k.pc.drives[1].img))
    sound = lambda d: fatcheck.check(bytes(k.pc.drives[d].img))[0]
    chosen = lambda: k.exec_list()[k.u16('sel')]
    # Copy to the other drive
    k.select('BIG.DAT'); k.key(CODE['C'])
    shot(k, 'exec_copy')
    check('CODE-C: the Copy form, filled in with where the file is', has(k, 'Copy BIG.DAT') and has(k, 'Subject') and
          k.band()[0] == 'Copy: Fill in form and confirm', (screen(k), k.band()))
    k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\data', K_CODE_ENTER)
    check('Copy to B:\\DATA: every byte there, the band says where', B().get('A:\\DATA\\BIG.DAT') == BIG and
          k.band()[0] == 'Copied to B:\\DATA\\BIG.DAT', (k.band(), sorted(B())))
    check('... no temporary file left, both disks sound', not [n for n in B() if n.endswith('TMP')] and not sound(0) and not sound(1),
          (sorted(B()), sound(0), sound(1)))
    k.key(ktest.ENTER)
    # Copy here, as another title: chosen in the list, the same date and time
    k.select('NOTES.TXT'); k.key(CODE['C'])
    k.key(ktest.ENTER, ktest.ENTER, ktest.ENTER, 'copy.txt', K_CODE_ENTER)
    img = k.pc.drives[0].img
    check('Copy as COPY.TXT here: listed and chosen, its date and time from NOTES.TXT', A().get('A:\\COPY.TXT') == TEXT and chosen() == 'COPY.TXT'
          and img[root_entry(img, 'COPY.TXT') + 22:][:4] == img[root_entry(img, 'NOTES.TXT') + 22:][:4], (k.exec_list(), k.band()))
    k.key(ktest.ENTER)
    # the file onto itself; then onto another: the question
    k.select('NOTES.TXT'); k.key(CODE['C']); k.key(K_CODE_ENTER)
    check('Copy onto itself: "NOTES.TXT is there now"', k.band()[0] == 'NOTES.TXT is there now: choose another place', k.band())
    k.key(ktest.ENTER)
    k.select('BIG.DAT'); k.key(CODE['C']); k.key(ktest.ENTER, ktest.ENTER, ktest.ENTER, 'COPY.TXT', K_CODE_ENTER)
    check('Copy onto COPY.TXT: asks first', k.band()[0] == 'COPY.TXT is there already: Confirm to replace it', k.band())
    k.key(ktest.ESC)
    check('... ESC: COPY.TXT as it was', A().get('A:\\COPY.TXT') == TEXT and not has(k, 'Copied'), k.band())
    k.key(CODE['C']); k.key(ktest.ENTER, ktest.ENTER, ktest.ENTER, 'COPY.TXT', K_CODE_ENTER, ktest.ENTER)
    check('... Return: replaced', A().get('A:\\COPY.TXT') == BIG and not sound(0), (k.band(), sound(0)))
    k.key(ktest.ENTER)
    # a write-protected disk: nothing changes, the band says why
    k.pc.drives[1].wp = True
    before = bytes(k.pc.drives[1].img)
    k.select('NOTES.TXT'); k.key(CODE['C']); k.key(ktest.ENTER, ktest.RIGHT, K_CODE_ENTER, settle=False); k.settle(20)
    check('Copy to a write-protected disk: "Can\'t copy NOTES.TXT: Disk is write-protected", B: untouched',
          k.band()[0] == "Can't copy NOTES.TXT: Disk is write-protected" and bytes(k.pc.drives[1].img) == before and not k.crashed, k.band())
    k.pc.drives[1].wp = False
    k.key(ktest.ENTER)
    # Move: on the same drive (RENAME), to the other drive (copy, then erase)
    k.select('NOTES.TXT'); k.key(CODE['M'])
    check('CODE-M: the Move form, Device and Subject', has(k, 'Move NOTES.TXT') and k.band()[0] == 'Move: Fill in form and confirm', screen(k))
    k.key(ktest.ENTER, ktest.ENTER, '\\work', K_CODE_ENTER)
    check('Move to \\WORK: there, not here, the band says where', 'A:\\WORK\\NOTES.TXT' in A() and 'A:\\NOTES.TXT' not in A()
          and 'NOTES.TXT' not in k.exec_list() and k.band()[0] == 'Moved to A:\\WORK\\NOTES.TXT' and not sound(0), (k.band(), sound(0)))
    k.key(ktest.ENTER)
    k.select('COPY.TXT'); k.key(CODE['M']); k.key(ktest.ENTER, ktest.RIGHT, K_CODE_ENTER)
    check('Move COPY.TXT to B:: on B:, gone from A:', B().get('A:\\COPY.TXT') == BIG and 'A:\\COPY.TXT' not in A()
          and not sound(0) and not sound(1), (k.band(), sorted(A()), sorted(B())))
    k.key(ktest.ENTER)
    k.select('KEEP.TXT'); k.key(CODE['M']); k.key(ktest.ENTER, ktest.RIGHT, K_CODE_ENTER)
    check('Move a read-only file to B:: "Access denied", not copied', k.band()[0] == "Can't move KEEP.TXT: Access denied"
          and 'A:\\KEEP.TXT' not in B(), k.band())
    k.key(ktest.ENTER)
    # Rename
    k.select('BIG.DAT'); k.key(CODE['R'])
    check('CODE-R: the Rename form', has(k, 'Rename BIG.DAT') and has(k, 'New title') and k.band()[0] == 'Rename: Fill in form and confirm', screen(k))
    k.key('huge.dat', ktest.ENTER)
    check('Rename to HUGE.DAT: renamed and chosen', A().get('A:\\HUGE.DAT') == BIG and 'A:\\BIG.DAT' not in A() and chosen() == 'HUGE.DAT', k.exec_list())
    k.key(CODE['R']); k.key('gridos.sys', ktest.ENTER)
    check('Rename onto a title that is there: "File already exists"', k.band()[0] == "Can't rename HUGE.DAT: File already exists"
          and 'A:\\HUGE.DAT' in A(), k.band())
    k.key(ktest.ENTER)
    # Erase
    k.select('HUGE.DAT'); k.key(CODE['D'])
    check('CODE-D: the Delete form, Titles filled in', k.band()[0] == 'Delete: Confirm to erase (* or ? for several)' and has(k, 'Delete HUGE.DAT')
          and has(k, 'Titles'), (k.band(), screen(k)))
    k.key(ktest.ESC)
    check('... ESC: still there', 'A:\\HUGE.DAT' in A() and 'HUGE.DAT' in k.exec_list(), k.exec_list())
    k.key(CODE['D']); k.key(ktest.ENTER)
    check('... Return: erased, the next one chosen', 'A:\\HUGE.DAT' not in A() and k.exec_list() == ['GRIDOS.SYS', 'KEEP.TXT']
          and chosen() == 'KEEP.TXT' and not sound(0), (k.exec_list(), sound(0)))
    k.select('KEEP.TXT'); k.key(CODE['D']); k.key(ktest.ENTER)
    check('Erase a read-only file: "it is read-only"', k.band()[0] == "Can't erase KEEP.TXT: it is read-only" and 'A:\\KEEP.TXT' in A(), k.band())
    k.key(ktest.ENTER)
    # only on a title
    k.key(ktest.TAB); k.key(CODE['D'])
    check('in Device: CODE-D does nothing (a beep)', focus(k) == 1 and not k.crashed and 'A:\\KEEP.TXT' in A(), k.band())
    k.key(ktest.ESC)

# ---------------------------------------------------------------------
def idle_saver(k):
    """Five minutes idle: the screen saver starts."""
    t = struct.unpack('<H', k.pc.rd(0, 0x46C, 2))[0]
    k.wr('lastact', struct.pack('<H', (t - 5462 + 18) & 0xFFFF))
    k.pc.run_for(4)

def t_file_safety():
    print('== the file commands: the review\'s cases (one file however spelled, the saver, long subjects ...)')
    notes = os.path.join(OUT, 'NOTES.TXT'); open(notes, 'wb').write(TEXT)
    BIG = bytes(range(256)) * 100
    big = os.path.join(OUT, 'BIG.DAT'); open(big, 'wb').write(BIG)
    deep = ['AAAAAAAA.AAA', 'BBBBBBBB.BBB', 'CCCCCCCC.CCC', 'DDDDDDDD.DDD', 'EEEEEEEE.EEE']
    dirs = ['\\'.join(deep[:i + 1]) + '\\' for i in range(5)]
    a = image('safea.img', DEFRAG, 'LONGNAME\\', 'LONGNAME\\NOTES.TXT=' + notes, 'WORK\\', *dirs,
              '\\'.join(deep) + '\\NAMENAME.EXT=' + notes, big)
    b = mkimg.build(os.path.join(OUT, 'safeb.img'), ['COPY.TXT=' + notes])
    k = ktest.KPC(a, b=b); k.start()
    A = lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
    B = lambda: fatcheck.read_files(bytes(k.pc.drives[1].img))
    sound = lambda d: fatcheck.check(bytes(k.pc.drives[d].img))[0]
    LN = 'A:\\LONGNAME\\NOTES.TXT'
    # 1. the file itself under another spelling: said so, nothing asked, nothing lost
    to_subject(k, 'LONGNAME')
    for sub in ('\\LONGNAME.', '\\LONGNAMEX', '\\LONGNAME\\.', '\\WORK\\..\\LONGNAME'):
        for cmd in 'MC':
            k.select('NOTES.TXT'); k.key(CODE[cmd]); k.key(ktest.ENTER, ktest.ENTER, sub, K_CODE_ENTER)
            check('%s to "%s" (the same subject): "is there now", the file intact' % ('Move' if cmd == 'M' else 'Copy', sub),
                  k.band()[0] == 'NOTES.TXT is there now: choose another place' and A().get(LN) == TEXT, (k.band(), sorted(A())))
            k.key(ktest.ENTER)
    k.key(CODE['C']); k.key(ktest.ENTER, ktest.ENTER, ktest.ENTER, 'notes.txtx', K_CODE_ENTER)
    check('Copy as "NOTES.TXTX" (the kernel cuts it to NOTES.TXT): "is there now"',
          k.band()[0] == 'NOTES.TXT is there now: choose another place' and A().get(LN) == TEXT, k.band())
    k.key(ktest.ENTER)
    # ... and should that check ever miss one: the source is held open while the old destination goes.
    # (same_file switched off on a machine that hasn't run it yet: the emulator keeps code it translated)
    k0 = ktest.KPC(image('safe0.img', 'LONGNAME\\', 'LONGNAME\\NOTES.TXT=' + notes)); k0.start()
    A0 = lambda: fatcheck.read_files(bytes(k0.pc.drives[0].img))
    k0.wr('same_file', b'\x0b\xe4\xc3')             # or sp, sp / ret: "not the same file"
    to_subject(k0, 'LONGNAME')
    k0.key(CODE['M']); k0.key(ktest.ENTER, ktest.ENTER, '\\LONGNAME.', K_CODE_ENTER, ktest.ENTER)
    check('... (check off) Move onto itself, confirmed: "Access denied", the file intact',
          k0.band()[0] == "Can't move NOTES.TXT: Access denied" and A0().get(LN) == TEXT, (k0.band(), sorted(A0())))
    k0.key(ktest.ENTER)
    k0.key(CODE['C']); k0.key(ktest.ENTER, ktest.ENTER, '\\LONGNAME.', K_CODE_ENTER, ktest.ENTER)
    check('... (check off) Copy onto itself, confirmed: "Access denied", the file intact, no temporary file',
          k0.band()[0] == "Can't copy NOTES.TXT: Access denied" and A0().get(LN) == TEXT and not [n for n in A0() if n.endswith('TMP')]
          and not fatcheck.check(bytes(k0.pc.drives[0].img))[0], (k0.band(), sorted(A0())))
    # 2. the screen saver while a question waits: no DEFRAG, and the question is still the band after
    k.key(CODE['D'])
    idle_saver(k)
    check('saver during the Delete form: the dark clock, not DEFRAG', not has(k, 'Delete') and not has(k, 'Defrag') and not has(k, 'NOTES'), screen(k))
    k.key(ktest.DOWN)
    check('... woken: the form and its band again', k.band()[0] == 'Delete: Confirm to erase (* or ? for several)' and has(k, 'Delete NOTES.TXT'), k.band())
    k.key(ktest.ESC)
    check('... ESC: not erased, the usual band', A().get(LN) == TEXT and k.band()[0] == 'Select a file and confirm', k.band())
    k.key(CODE['C'])
    idle_saver(k); k.key(ktest.DOWN)
    check('saver while the Copy form is open: its band and the form are back', k.band()[0] == 'Copy: Fill in form and confirm' and has(k, 'Copy NOTES.TXT'),
          (k.band(), screen(k)))
    k.key(ktest.ESC)
    check('... ESC: the usual band', k.band()[0] == 'Select a file and confirm', k.band())
    # 5. no path or wildcard in a title, no wildcard in a subject
    for cmd, keys, want in (('R', ('\\work\\x.txt', ktest.ENTER), "Can't rename NOTES.TXT: a title can't have \\ : * or ?"),
                            ('R', ('a:b', ktest.ENTER), "Can't rename NOTES.TXT: a title can't have \\ : * or ?"),
                            ('C', (ktest.ENTER, ktest.ENTER, ktest.ENTER, '*.txt', K_CODE_ENTER), "Can't copy NOTES.TXT: a title can't have \\ : * or ?"),
                            ('C', (ktest.ENTER, ktest.ENTER, '\\w*', K_CODE_ENTER), "Can't copy NOTES.TXT: a subject can't have : * or ?"),
                            ('M', (ktest.ENTER, ktest.ENTER, '\\wor?', K_CODE_ENTER), "Can't move NOTES.TXT: a subject can't have : * or ?")):
        k.key(CODE[cmd]); k.key(*keys)
        check('%s with %r: refused' % ({'R': 'Rename', 'C': 'Copy', 'M': 'Move'}[cmd], ''.join(x for x in keys if isinstance(x, str))),
              k.band()[0] == want and A().get(LN) == TEXT and k.exec_list() == ['NOTES.TXT'], (k.band(), sorted(A())))
        k.key(ktest.ENTER)
    # 3. a long subject: five levels of 8.3 names (as deep as the Subject list goes), 65 characters
    to_subject(k, 'EEEEEEEE.EEE')
    D = 'A:\\' + '\\'.join(deep)
    check('the deepest subject: 65 characters (Copy\'s field held 63)', len(D) - 2 == 65 and k.exec_list() == ['NAMENAME.EXT'], k.exec_list())
    k.key(CODE['C'])
    check('... the Copy form holds all of it, and the title field is intact', bytes(k.rd('c_sub', 67)).split(b'\0')[0].decode() == D[2:]
          and bytes(k.rd('c_tit', 13)).split(b'\0')[0] == b'NAMENAME.EXT', (k.rd('c_sub', 67), k.rd('c_tit', 13)))
    k.key(ktest.ENTER, ktest.ENTER, ktest.ENTER, 'copy.ext', K_CODE_ENTER)
    check('... Copy there as COPY.EXT works', A().get(D + '\\COPY.EXT') == TEXT and k.exec_list() == ['COPY.EXT', 'NAMENAME.EXT']
          and k.band()[0].startswith('Copied to ' + D[:60]), (k.band(), [n for n in A() if 'EEE' in n]))
    k.key(ktest.ENTER)
    k.select('NAMENAME.EXT'); k.key(CODE['M']); k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\', K_CODE_ENTER)
    check('... Move from there to B:\\ works', B().get('A:\\NAMENAME.EXT') == TEXT and D + '\\NAMENAME.EXT' not in A() and not sound(0) and not sound(1),
          (k.band(), sorted(B())))
    k.key(ktest.ENTER)
    to_subject(k, 'Root')
    # 4. Move to the other drive when the original can't be erased: said as it is
    k.pc.drives[0].wp = True
    k.select('BIG.DAT'); k.key(CODE['M']); k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\', K_CODE_ENTER, settle=False); k.settle(20)
    check('Move from a write-protected disk: "Copied, but can\'t erase BIG.DAT here: Disk is write-protected"',
          k.band()[0] == "Copied, but can't erase BIG.DAT here: Disk is write-protected" and B().get('A:\\BIG.DAT') == BIG
          and A().get('A:\\BIG.DAT') == BIG and not k.crashed, (k.band(), sorted(B())))
    k.pc.drives[0].wp = False
    k.key(ktest.ENTER)
    check('... and still listed (the kernel forgot the directory sector it couldn\'t write)', 'BIG.DAT' in k.exec_list(), k.exec_list())
    k.select('BIG.DAT'); k.key(CODE['C']); k.key(ktest.ENTER, ktest.ENTER, ktest.ENTER, 'big2.dat', K_CODE_ENTER)
    check('... a later write to that directory sector (Copy as BIG2.DAT) leaves BIG.DAT there, the disk sound',
          A().get('A:\\BIG.DAT') == BIG and A().get('A:\\BIG2.DAT') == BIG and not sound(0), (sorted(A()), sound(0)))
    k.key(ktest.ENTER)
    # 6. the old destination erased, then the new file can't take its name: kept, and said where
    def wp_at_rename(pc):
        if pc.r('cs') == 0x60 and pc.r('ip') == k.Y['f_56']: k.pc.drives[1].wp = True
    k.hooks.append(wp_at_rename)
    k.select('BIG.DAT'); k.key(CODE['C']); k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, ktest.ENTER, 'copy.txt', K_CODE_ENTER, ktest.ENTER, settle=False); k.settle(20)
    k.hooks.remove(wp_at_rename)
    kept = [n for n in B() if n.endswith('TMP')]
    check('the rename after replacing fails: "Copy kept as B:\\....TMP", the copy all there',
          k.band()[0].startswith('Copy kept as B:\\') and k.band()[0].endswith('TMP: Disk is write-protected')
          and len(kept) == 1 and B()[kept[0]] == BIG and 'A:\\COPY.TXT' not in B() and A().get('A:\\BIG.DAT') == BIG, (k.band(), sorted(B())))
    k.pc.drives[1].wp = False
    k.key(ktest.ENTER)
    check('... and both disks sound', not sound(0) and not sound(1), (sound(0), sound(1)))

# ---------------------------------------------------------------------
def dir_entries(img, name):
    """Offsets of every directory entry called NAME.EXT on a disk image."""
    nm, _, ext = name.partition('.')
    want = (nm.ljust(8) + ext.ljust(3)).encode()
    return [o for o in range(0, len(img), 32) if bytes(img[o:o + 11]) == want and img[o + 11] & 0x18 == 0]

def set_date(path, name, y, m=1, d=1):
    raw = bytearray(open(path, 'rb').read())
    for o in dir_entries(raw, name):
        raw[o + 24:o + 26] = struct.pack('<H', ((y - 1980) << 9) | (m << 5) | d)
    open(path, 'wb').write(raw)

def t_wild():
    print('== wildcards: Titles in Copy, Move and Delete; Replace; Only newer')
    files = {}
    for n, data in (('A.TXT', b'aaa\r\n'), ('B.TXT', b'bbb\r\n'), ('OLD.TXT', b'old new\r\n'), ('NEW.TXT', b'new old\r\n'),
                    ('C.DAT', b'ccc' * 1000), ('D.DAT', b'ddd' * 1000), ('RO.TXT', b'read only\r\n')):
        files[n] = data
        open(os.path.join(OUT, n), 'wb').write(data)
    a = image('wilda.img', *[os.path.join(OUT, n) for n in files], 'WORK\\')
    raw = bytearray(open(a, 'rb').read()); raw[root_entry(raw, 'RO.TXT') + 11] |= 1; open(a, 'wb').write(raw)
    for n in files: set_date(a, n, 2026, 6)
    old = os.path.join(OUT, 'BOLD.TXT'); open(old, 'wb').write(b'was on B\r\n')
    b = mkimg.build(os.path.join(OUT, 'wildb.img'), ['DATA\\', 'DATA\\B.TXT=' + old, 'DATA\\OLD.TXT=' + old, 'DATA\\NEW.TXT=' + old,
                    'FULL\\'] + ['FULL\\F%02d.TXT=%s' % (i, old) for i in range(14)])  # FULL: its one cluster full
    raw = bytearray(open(b, 'rb').read()); bp = fatcheck.bpb(raw)  # free space not zeros, as on a used disk
    d0 = (bp['res'] + bp['nfat'] * bp['spf']) * bp['bps'] + bp['nroot'] * 32
    for o in range(d0, len(raw), 512):
        if not any(raw[o:o + 512]): raw[o:o + 512] = b'A' * 512
    open(b, 'wb').write(raw)
    set_date(b, 'OLD.TXT', 2020)                        # older on B: Only newer replaces it
    set_date(b, 'NEW.TXT', 2026, 9)                     # newer on B: Only newer leaves it
    set_date(b, 'B.TXT', 2020)
    k = ktest.KPC(a, b=b); k.start()
    A = lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
    B = lambda: fatcheck.read_files(bytes(k.pc.drives[1].img))
    sound = lambda d: fatcheck.check(bytes(k.pc.drives[d].img))[0]
    band = lambda: k.band()[0]
    # the form
    k.select('A.TXT'); k.key(CODE['C'])
    shot(k, 'exec_copy_wild')
    check('the Copy form: Titles, Device, Subject, Title, Replace, Only newer', all(has(k, t) for t in ('Titles', 'Replace', 'Ask', 'None', 'Only newer'))
          and has(k, 'Copy A.TXT'), screen(k))
    # *.TXT to B:\DATA, Replace None: B.TXT, OLD.TXT, NEW.TXT left
    k.key('*.txt', ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\data', ktest.ENTER, ktest.ENTER, ktest.RIGHT, ktest.RIGHT, K_CODE_ENTER)
    check('Copy *.TXT to B:\\DATA, Replace None: "Copied 2 titles to B:\\DATA, 3 left as they were"',
          band() == 'Copied 2 titles to B:\\DATA, 3 left as they were' and B().get('A:\\DATA\\A.TXT') == files['A.TXT']
          and B().get('A:\\DATA\\RO.TXT') == files['RO.TXT'] and B().get('A:\\DATA\\B.TXT') == b'was on B\r\n', (k.band(), sorted(B())))
    check('... the list as it was, A.TXT still chosen, both disks sound', k.exec_list()[k.u16('sel')] == 'A.TXT' and not sound(0) and not sound(1), k.exec_list())
    k.key(ktest.ENTER)
    # Only newer, Replace All: OLD.TXT replaced (older on B), NEW.TXT left (newer on B), the others replaced
    k.key(CODE['C']); k.key('*.txt', ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\data', ktest.ENTER, ktest.ENTER, ktest.RIGHT, ktest.ENTER, ktest.RIGHT, K_CODE_ENTER)
    check('Only newer, Replace All: OLD.TXT replaced, NEW.TXT (newer on B:) left, A.TXT and RO.TXT (as new) left',
          band() == 'Copied 2 titles to B:\\DATA, 3 left as they were' and B().get('A:\\DATA\\OLD.TXT') == files['OLD.TXT']
          and B().get('A:\\DATA\\NEW.TXT') == b'was on B\r\n' and B().get('A:\\DATA\\B.TXT') == files['B.TXT'], (k.band(), B()))
    k.key(ktest.ENTER)
    # Replace Ask: Return for one, ESC for the next, on to the rest
    k.key(CODE['C']); k.key('*.txt', ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\data', K_CODE_ENTER)
    check('Replace Ask: the question for the first one there', band() == 'A.TXT is there already: Confirm to replace it', k.band())
    k.key(ktest.ENTER)
    check('... Return: the next question', band().endswith('is there already: Confirm to replace it') and not band().startswith('A.TXT'), k.band())
    for _ in range(3): k.key(ktest.ESC)
    k.key(ktest.ESC)
    check('... ESC leaves each one, the rest go on: "Copied 1 title ..., 4 left"', band() == 'Copied 1 title to B:\\DATA, 4 left as they were', k.band())
    k.key(ktest.ENTER)
    # Move *.DAT to \WORK (same drive)
    k.key(CODE['M']); k.key('*.dat', ktest.ENTER, ktest.ENTER, '\\work', K_CODE_ENTER)
    check('Move *.DAT to \\WORK: "Moved 2 titles to A:\\WORK", gone from the list', band() == 'Moved 2 titles to A:\\WORK'
          and A().get('A:\\WORK\\C.DAT') == files['C.DAT'] and A().get('A:\\WORK\\D.DAT') == files['D.DAT']
          and not [n for n in k.exec_list() if n.endswith('.DAT')] and not sound(0), (k.band(), k.exec_list()))
    k.key(ktest.ENTER)
    # a pattern that matches nothing; a path in Titles; Title changed with a pattern; into its own subject
    for cmd, keys, want in (('C', ('*.xyz', K_CODE_ENTER), "Can't copy *.XYZ: File not found"),
                            ('C', ('work\\*.dat', K_CODE_ENTER), "Can't copy A.TXT: titles can't have \\ or :"),
                            ('C', ('*.txt', ktest.ENTER, ktest.ENTER, ktest.ENTER, 'x.txt', K_CODE_ENTER), "Can't copy A.TXT: with * or ? in Titles, leave Title as it was"),
                            ('C', ('*.txt', K_CODE_ENTER), 'A.TXT is there now: choose another place'),
                            ('D', ('*.xyz', ktest.ENTER), "Can't erase *.XYZ: File not found")):
        before = A()
        k.key(CODE[cmd]); k.key(*keys)
        check('%s %r: %s' % (cmd, keys[0], want), band() == want and A() == before, k.band())
        k.key(ktest.ENTER)
    # one title typed over the chosen one: that one, under its own title
    k.select('A.TXT'); k.key(CODE['C']); k.key('b.txt', ktest.ENTER, ktest.RIGHT, K_CODE_ENTER)
    check('Copy with Titles B.TXT (A.TXT chosen): B.TXT, as B.TXT, to B:\\', band() == 'Copied to B:\\B.TXT' and B().get('A:\\B.TXT') == files['B.TXT'], k.band())
    k.key(ktest.ENTER)
    # Replace None for one title: said so
    k.key(CODE['C']); k.key('b.txt', ktest.ENTER, ktest.RIGHT, ktest.ENTER, ktest.ENTER, ktest.ENTER, ktest.RIGHT, ktest.RIGHT, K_CODE_ENTER)
    check('one title, Replace None: "B.TXT is there already: left as it was"', band() == 'B.TXT is there already: left as it was', k.band())
    k.key(ktest.ENTER)
    # a write-protected B:: stops at the first, says why
    k.pc.drives[1].wp = True
    before = bytes(k.pc.drives[1].img)
    k.key(CODE['C']); k.key('*.txt', ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\', ktest.ENTER, ktest.ENTER, ktest.RIGHT, K_CODE_ENTER, settle=False); k.settle(30)
    check('*.TXT to a write-protected B:: "Can\'t copy A.TXT: Disk is write-protected", B: untouched',
          band() == "Can't copy A.TXT: Disk is write-protected" and bytes(k.pc.drives[1].img) == before and not k.crashed, k.band())
    k.pc.drives[1].wp = False
    k.key(ktest.ENTER)
    # Titles left empty: the chosen title (not what runpath held before it)
    k.select('A.TXT'); k.wr('runpath', b'XXXXXXXXXXXX\\W*\0'); k.key(CODE['C'])
    k.key(*([ktest.BKSP] * 5)); k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\', ktest.ENTER, 'a2.txt', K_CODE_ENTER)
    check('Copy with Titles empty: the chosen title, under the Title typed', band() == 'Copied to B:\\A2.TXT' and B().get('A:\\A2.TXT') == files['A.TXT'], k.band())
    k.key(ktest.ENTER)
    # a wildcard Move that copies but can't erase: said so, and it stops there
    k.pc.drives[0].wp = True
    before = A()
    k.key(CODE['M']); k.key('*.txt', ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\', K_CODE_ENTER, settle=False); k.settle(30)
    check('Move *.TXT from a write-protected A:: "Copied, but can\'t erase A.TXT here", the rest not tried',
          band() == "Copied, but can't erase A.TXT here: Disk is write-protected" and A() == before and 'A:\\B2.TXT' not in B()
          and 'A:\\OLD.TXT' not in B() and not k.crashed, (k.band(), sorted(B())))
    k.pc.drives[0].wp = False
    k.key(ktest.ENTER)
    # a subject that isn't there: made after a question, each level
    k.select('A.TXT'); k.key(CODE['C']); k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\new\\deep', K_CODE_ENTER)
    check('Copy to B:\\NEW\\DEEP (not there): "B:\\NEW\\DEEP isn\'t there: Confirm to make it"', band() == "B:\\NEW\\DEEP isn't there: Confirm to make it", k.band())
    k.key(ktest.ESC)
    check('... ESC: nothing made, nothing said', not [n for n in B() if 'NEW\\' in n] and band() == 'Select a file and confirm' and not sound(1), (k.band(), sorted(B())))
    k.key(CODE['C']); k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\new\\deep', K_CODE_ENTER, ktest.ENTER)
    check('... Return: both levels made, the copy in it', band() == 'Copied to B:\\NEW\\DEEP\\A.TXT' and B().get('A:\\NEW\\DEEP\\A.TXT') == files['A.TXT']
          and not sound(1), (k.band(), sorted(B())))
    k.key(ktest.ENTER)
    k.pc.drives[1].wp = True
    k.key(CODE['C']); k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\other', K_CODE_ENTER, ktest.ENTER, settle=False); k.settle(30)
    check('... on a write-protected disk: "Can\'t copy A.TXT: Disk is write-protected"', band() == "Can't copy A.TXT: Disk is write-protected" and not k.crashed, k.band())
    k.pc.drives[1].wp = False
    k.key(ktest.ENTER)
    check('... and B: still sound (the failed MKDIR left no lost cluster)', not sound(1), sound(1))
    k.pc.drives[1].wp = True
    k.key(CODE['C']); k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\full', K_CODE_ENTER, settle=False); k.settle(30)
    check('Copy into a full subject on a write-protected B:: refused', band() == "Can't copy A.TXT: Disk is write-protected" and not k.crashed, k.band())
    k.pc.drives[1].wp = False
    k.key(ktest.ENTER)
    k.key(CODE['C']); k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\full', K_CODE_ENTER)
    check('... then with B: writable: the subject grows, B: sound (no cluster lost by the failed growth)',
          band() == 'Copied to B:\\FULL\\A.TXT' and B().get('A:\\FULL\\A.TXT') == files['A.TXT'] and not sound(1)
          and len([n for n in B() if n.startswith('A:\\FULL\\')]) == 15, (k.band(), sound(1), sorted(B())))
    k.key(ktest.ENTER)
    # Delete *.TXT: the question, ESC, then Return: the read-only one kept
    k.key(CODE['D']); k.key('*.txt', ktest.ENTER)
    check('Delete *.TXT: "Erase: Confirm to erase 5 titles *.TXT"', band() == 'Erase: Confirm to erase 5 titles *.TXT', k.band())
    k.key(ktest.ESC)
    check('... ESC: all there', len([n for n in A() if n.endswith('.TXT')]) == 5, sorted(A()))
    k.key(CODE['D']); k.key('*.txt', ktest.ENTER, ktest.ENTER)
    check('... Return: "Erased 4 titles, 1 read-only kept"', band() == 'Erased 4 titles, 1 read-only kept'
          and [n for n in A() if n.endswith('.TXT')] == ['A:\\RO.TXT'] and k.exec_list() == ['GRIDOS.SYS', 'RO.TXT'] and not sound(0), (k.band(), sorted(A())))
    k.key(ktest.ENTER)
    # Move *.* from \WORK to B: (copy, then erase)
    to_subject(k, 'WORK')
    k.key(CODE['M']); k.key('*.*', ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\data', K_CODE_ENTER)
    check('Move *.* from \\WORK to B:\\DATA: "Moved 2 titles to B:\\DATA", \\WORK empty', band() == 'Moved 2 titles to B:\\DATA'
          and B().get('A:\\DATA\\C.DAT') == files['C.DAT'] and k.exec_list() == [] and not sound(0) and not sound(1), (k.band(), k.exec_list(), sound(0), sound(1)))
    k.key(ktest.ENTER)
    check('... and the Executive\'s memory as it was (the block for the titles freed)', not k.crashed, '')
    # a subject that must grow, on a write-protected disk whose free space isn't zeros (as on a used disk)
    g = mkimg.build(os.path.join(OUT, 'growb.img'), ['FULL\\'] + ['FULL\\F%02d.TXT=%s' % (i, old) for i in range(14)])
    raw = bytearray(open(g, 'rb').read()); bp = fatcheck.bpb(raw)
    d0 = (bp['res'] + bp['nfat'] * bp['spf']) * bp['bps'] + bp['nroot'] * 32
    for o in range(d0, len(raw), 512):
        if not any(raw[o:o + 512]): raw[o:o + 512] = b'A' * 512
    open(g, 'wb').write(raw)
    k = ktest.KPC(a, b=g); k.start()
    G = lambda: fatcheck.read_files(bytes(k.pc.drives[1].img))
    k.pc.drives[1].wp = True
    k.key(CODE['C']); k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\full', K_CODE_ENTER, settle=False); k.settle(30)
    k.key(ktest.ENTER); k.key(K_BTAB)
    check('... and with B: still write-protected, A:\'s subjects list (B:\'s FAT not left "changed": 0.3.13)',
          subjects(k) == ['Root', '  WORK'] and k.band()[0] == 'Subject: Select item and confirm', (subjects(k), k.band()))
    k.key(ktest.ESC)
    k.pc.drives[1].wp = False
    k.key(CODE['C']); k.key(ktest.ENTER, ktest.RIGHT, ktest.ENTER, '\\full', K_CODE_ENTER)
    check('a subject that couldn\'t grow (write-protected) grows cleanly later: no stray entries, the disk sound',
          k.band()[0].startswith('Copied to B:\\FULL\\') and len([n for n in G() if n.startswith('A:\\FULL\\')]) == 15
          and not fatcheck.check(bytes(k.pc.drives[1].img))[0], (k.band(), sorted(G())))

# ---------------------------------------------------------------------
def pick_subject(k, name):
    """Outline Subject and choose NAME in it (Subject stays outlined)."""
    if focus(k) != 2: k.key(K_BTAB)
    want = [x.strip() for x in subjects(k)].index(name)
    for _ in range(40):
        if k.u16('sel') == want: break
        k.key(ktest.DOWN if k.u16('sel') < want else ktest.UP)

def t_subdel():
    print('== Delete on a subject: it and all in it, after a question')
    t = os.path.join(OUT, 'T.TXT'); open(t, 'wb').write(b'text\r\n')
    a = image('subdel.img', t, 'OLD\\', 'OLD\\A.TXT=' + t, 'OLD\\RO.TXT=' + t, 'OLD\\SUB\\', 'OLD\\SUB\\B.TXT=' + t,
              'OLD\\SUB\\A long name.txt=' + t, 'OLD\\SUB\\DEEP\\', 'OLD\\EMPTY\\', 'KEEP\\', 'KEEP\\K.TXT=' + t, 'NOTHING\\')
    raw = bytearray(open(a, 'rb').read())
    for o in dir_entries(raw, 'RO.TXT'): raw[o + 11] |= 1           # read-only inside
    open(a, 'wb').write(raw)
    k = ktest.KPC(a); k.start()
    A = lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
    sound = lambda: fatcheck.check(bytes(k.pc.drives[0].img))[0]
    band = lambda: k.band()[0]
    pick_subject(k, 'Root'); k.key(CODE['D'])
    check('Root: CODE-D does nothing (a beep)', focus(k) == 2 and not k.crashed and 'A:\\T.TXT' in A() and band() != '', k.band())
    pick_subject(k, 'OLD'); k.key(CODE['D'])
    check('OLD: "Erase: Confirm to erase \\OLD and all in it"', band() == 'Erase: Confirm to erase \\OLD and all in it', k.band())
    k.key(ktest.ESC)
    check('... ESC: all there, OLD still chosen in Subject', len([n for n in A() if n.startswith('A:\\OLD\\')]) == 4 and focus(k) == 2
          and subjects(k)[k.u16('sel')].strip() == 'OLD', (sorted(A()), subjects(k), k.u16('sel')))
    k.key(CODE['D']); k.key(ktest.ENTER)
    check('... Return: "Erased \\OLD", the read-only one, a long-named one (Windows) and the subjects in it too', band() == 'Erased \\OLD'
          and not [n for n in A() if 'OLD' in n] and A().get('A:\\KEEP\\K.TXT') == b'text\r\n' and not sound(), (k.band(), sorted(A()), sound()))
    check('... the Subject list without OLD, Root chosen', [x.strip() for x in subjects(k)] == ['Root', 'KEEP', 'NOTHING']
          and subjects(k)[k.u16('sel')].strip() == 'Root', (subjects(k), k.u16('sel')))
    root = bytes(k.pc.drives[0].img)
    b = fatcheck.bpb(root)
    check('... and no OLD entry left in the root directory', not [o for o in range(0, len(root), 32) if root[o:o + 11] == b'OLD        ' and root[o + 11] & 0x10], '')
    pick_subject(k, 'NOTHING'); k.key(CODE['D'])
    check('an empty subject: "Erase: Confirm to erase \\NOTHING and all in it"', band() == 'Erase: Confirm to erase \\NOTHING and all in it', k.band())
    k.key(ktest.ENTER)
    check('... Return: "Erased \\NOTHING", gone', band() == 'Erased \\NOTHING' and [x.strip() for x in subjects(k)] == ['Root', 'KEEP'] and not sound(),
          (k.band(), subjects(k)))
    k.key(ktest.ENTER)
    # a write-protected disk: said so, nothing lost
    k.pc.drives[0].wp = True
    pick_subject(k, 'KEEP'); k.key(CODE['D']); k.key(ktest.ENTER, settle=False); k.settle(30)
    check('KEEP on a write-protected disk: "Can\'t erase K.TXT: Disk is write-protected"',
          band() == "Can't erase K.TXT: Disk is write-protected" and A().get('A:\\KEEP\\K.TXT') == b'text\r\n' and not k.crashed, k.band())
    k.pc.drives[0].wp = False
    k.key(ktest.ENTER)
    check('... and Title lists the titles of where it is now', not k.crashed, '')

def attr_at(img, name):
    """Offsets of every directory entry called NAME.EXT, subjects too."""
    nm, _, ext = name.partition('.')
    want = (nm.ljust(8) + ext.ljust(3)).encode()
    return [o for o in range(0, len(img), 32) if bytes(img[o:o + 11]) == want and not img[o + 11] & 8 and img[o + 11] != 0x0F]

def date_of(img, path):
    """The FAT date of the entry at path ('WORK\\SUB\\B.TXT') as (y, m, d)."""
    raw = bytes(img)
    offs = [o for o in dir_entries(raw, path.split('\\')[-1])]
    want = fatcheck.read_files(raw).get('A:\\' + path)
    for o in offs:                                  # (the one whose bytes match, if several)
        d = struct.unpack_from('<H', raw, o + 24)[0]
        return ((d >> 9) + 1980, (d >> 5) & 15, d & 31)

def t_subcopy():
    print('== Copy on a subject: it and all in it, titles and subjects')
    BIG = bytes(range(256)) * 300                   # 76800 bytes: more than the 32 KB buffer twice over
    big = os.path.join(OUT, 'BIG.DAT'); open(big, 'wb').write(BIG)
    t = os.path.join(OUT, 'T.TXT'); open(t, 'wb').write(b'text\r\n')
    u = os.path.join(OUT, 'U.TXT'); open(u, 'wb').write(b'other text\r\n')
    a = image('subcopy.img', t, 'WORK\\', 'WORK\\A.TXT=' + t, 'WORK\\RO.TXT=' + u, 'WORK\\SUB\\', 'WORK\\SUB\\B.TXT=' + u,
              'WORK\\SUB\\DEEP\\', 'WORK\\SUB\\DEEP\\C.DAT=' + big, 'WORK\\EMPTY\\', 'KEEP\\', 'KEEP\\K.TXT=' + t,
              'HID\\', 'HID\\H.TXT=' + t, 'HID\\S.SYS=' + u, 'HID\\HSUB\\', 'HID\\HSUB\\X.TXT=' + t)
    raw = bytearray(open(a, 'rb').read())
    for o in dir_entries(raw, 'RO.TXT'): raw[o + 11] |= 1           # read-only inside
    for o in dir_entries(raw, 'H.TXT'): raw[o + 11] |= 2            # hidden
    for o in dir_entries(raw, 'S.SYS'): raw[o + 11] |= 4            # system
    for o in attr_at(raw, 'HSUB'): raw[o + 11] |= 2                 # a hidden subject
    open(a, 'wb').write(raw)
    for n in ('A.TXT', 'RO.TXT', 'B.TXT', 'C.DAT'): set_date(a, n, 2026, 6, 15)
    old = os.path.join(OUT, 'OLDB.TXT'); open(old, 'wb').write(b'was on B\r\n')
    b = mkimg.build(os.path.join(OUT, 'subcopyb.img'), ['DATA\\', 'OLDBAK\\', 'OLDBAK\\A.TXT=' + old, 'OLDBAK\\SUB\\', 'OLDBAK\\SUB\\B.TXT=' + old,
                    'EFILE=' + old])
    set_date(b, 'A.TXT', 2026, 9)                       # newer on B: Only newer leaves it
    set_date(b, 'B.TXT', 2020)                          # older on B: Only newer replaces it
    k = ktest.KPC(a, b=b); k.start()
    A = lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
    B = lambda: fatcheck.read_files(bytes(k.pc.drives[1].img))
    def D(d):
        out = []; fatcheck.read_files(bytes(k.pc.drives[d].img), dirs=out); return out
    sound = lambda d: fatcheck.check(bytes(k.pc.drives[d].img))[0]
    band = lambda: k.band()[0]
    WORK = {n[len('A:\\WORK'):]: v for n, v in A().items() if n.startswith('A:\\WORK\\')}
    under = lambda files, base: {n[len(base):]: v for n, v in files.items() if n.startswith(base + '\\')}
    free0 = free_paras(k)[0]
    # the form
    pick_subject(k, 'WORK'); k.key(CODE['C'])
    shot(k, 'exec_copy_subject')
    check('WORK, CODE-C: the form "Copy WORK": Device, Subject (\\WORK), Replace, Only newer; no Titles or Title',
          has(k, 'Copy WORK') and all(has(k, x) for x in ('Device', 'Subject', 'Replace', 'Only newer', '\\WORK'))
          and not has(k, 'Titles') and band() == 'Copy: Fill in form and confirm', (screen(k), k.band()))
    k.key(K_CODE_ENTER)
    check('... confirmed as it is: "Can\'t copy WORK into itself: choose another place", nothing made',
          band() == "Can't copy WORK into itself: choose another place" and len(D(0)) == 7, (k.band(), D(0)))
    k.key(ktest.ENTER)
    k.key(CODE['C']); idle_saver(k); k.key(ktest.DOWN); k.key(K_CODE_ENTER)
    check('... the screen saver while the form is open, then confirmed: the name still WORK (the redraw reads the subjects)',
          band() == "Can't copy WORK into itself: choose another place", k.band())
    k.key(ktest.ENTER)
    # to B:, a new subject there
    k.key(CODE['C']); k.key(ktest.RIGHT, K_CODE_ENTER)
    check('Device B:: "B:\\WORK isn\'t there: Confirm to make it"', band() == "B:\\WORK isn't there: Confirm to make it", k.band())
    k.key(ktest.ENTER, settle=False); k.settle(30)
    check('... Return: "Copied 4 titles to B:\\WORK"; every title and subject there, every byte (a read-only one, 75 KB three levels down)',
          band() == 'Copied 4 titles to B:\\WORK' and under(B(), 'A:\\WORK') == WORK
          and sorted(D(1)) == sorted(['A:\\DATA', 'A:\\OLDBAK', 'A:\\OLDBAK\\SUB', 'A:\\WORK', 'A:\\WORK\\SUB', 'A:\\WORK\\SUB\\DEEP', 'A:\\WORK\\EMPTY']),
          (k.band(), sorted(B()), D(1)))
    check('... the dates kept, no temporary file, both disks sound', date_of(k.pc.drives[1].img, 'WORK\\SUB\\DEEP\\C.DAT') == (2026, 6, 15)
          and not [n for n in B() if n.endswith('TMP')] and not sound(0) and not sound(1), (date_of(k.pc.drives[1].img, 'WORK\\SUB\\DEEP\\C.DAT'), sound(0), sound(1)))
    check('... Subject still outlined, WORK still chosen, the memory as it was', focus(k) == 2 and subjects(k)[k.u16('sel')].strip() == 'WORK'
          and free_paras(k)[0] == free0, (focus(k), subjects(k), k.u16('sel'), free_paras(k)[0], free0))
    k.key(ktest.ENTER)
    # again, Replace Ask: a question for each title there
    k.key(CODE['C']); k.key(ktest.RIGHT, K_CODE_ENTER)
    check('again (Replace Ask): "A.TXT is there already: Confirm to replace it"', band() == 'A.TXT is there already: Confirm to replace it', k.band())
    idle_saver(k); k.key(ktest.DOWN)                    # (the saver reads the subjects again under it)
    check('... the screen saver meanwhile: the question again after', band() == 'A.TXT is there already: Confirm to replace it', k.band())
    k.key(ktest.ENTER)
    asked = []
    while band().endswith('is there already: Confirm to replace it') and len(asked) < 6:
        asked.append(band().split()[0]); k.key(ktest.ESC)
    check('... Return for A.TXT, ESC for the rest (asked each, subjects below too): "Copied 1 title to B:\\WORK, 3 left as they were"',
          band() == 'Copied 1 title to B:\\WORK, 3 left as they were' and sorted(asked) == ['B.TXT', 'C.DAT', 'RO.TXT']
          and under(B(), 'A:\\WORK') == WORK and not sound(1), (k.band(), asked))
    k.key(ktest.ENTER)
    # Only newer, Replace All, into a backup there already
    k.key(CODE['C']); k.key(ktest.RIGHT, ktest.ENTER, '\\oldbak', ktest.ENTER, ktest.RIGHT, ktest.ENTER, ktest.RIGHT, K_CODE_ENTER)
    check('to B:\\OLDBAK, Only newer, Replace All: B.TXT (older there) replaced, A.TXT (newer there) left, the rest new',
          band() == 'Copied 3 titles to B:\\OLDBAK, 1 left as they were' and B().get('A:\\OLDBAK\\A.TXT') == b'was on B\r\n'
          and B().get('A:\\OLDBAK\\SUB\\B.TXT') == b'other text\r\n' and B().get('A:\\OLDBAK\\SUB\\DEEP\\C.DAT') == BIG
          and 'A:\\OLDBAK\\EMPTY' in D(1) and not sound(1), (k.band(), sorted(B())))
    k.key(ktest.ENTER)
    # hidden and system titles, a hidden subject: copied, and hidden or system as they were
    pick_subject(k, 'HID'); k.key(CODE['C']); k.key(ktest.RIGHT, K_CODE_ENTER, ktest.ENTER, settle=False); k.settle(30)
    bimg = bytes(k.pc.drives[1].img)
    check('HID (a hidden title, a system title, a hidden subject with a title in it) to B:: all copied, still hidden or system',
          band() == 'Copied 3 titles to B:\\HID' and under(B(), 'A:\\HID') == under(A(), 'A:\\HID')
          and [bimg[o + 11] for o in dir_entries(bimg, 'H.TXT')] == [2] and [bimg[o + 11] for o in dir_entries(bimg, 'S.SYS')] == [4]
          and [bimg[o + 11] for o in attr_at(bimg, 'HSUB')] == [0x12] and not sound(1),
          (k.band(), sorted(B()), [bimg[o + 11] for o in attr_at(bimg, 'HSUB')]))
    k.key(ktest.ENTER)
    pick_subject(k, 'WORK')
    # into itself, however near
    for sub, why in (('\\work\\backup', 'a subject in it'), ('\\work\\', 'itself, with a \\ after')):
        k.key(CODE['C']); k.key(ktest.ENTER, sub, K_CODE_ENTER)
        check('to %s (%s): "into itself", nothing made' % (sub.upper(), why), band() == "Can't copy WORK into itself: choose another place"
              and len(D(0)) == 7, (k.band(), D(0)))
        k.key(ktest.ENTER)
    k.key(CODE['C']); k.key(ktest.ENTER, '\\works', K_CODE_ENTER, ktest.ENTER, settle=False); k.settle(30)
    check('... but \\WORKS (only the name starts the same) is somewhere else: copied', band() == 'Copied 4 titles to A:\\WORKS'
          and under(A(), 'A:\\WORKS') == WORK and not sound(0), (k.band(), sorted(A())))
    k.key(ktest.ENTER)
    pick_subject(k, 'Root'); k.key(CODE['C'])
    check('Root: the form "Copy Root", Subject \\', has(k, 'Copy Root'), screen(k))
    k.key(ktest.ENTER, '\\all', K_CODE_ENTER)
    check('... to \\ALL on its own drive: "Can\'t copy Root into itself"', band() == "Can't copy Root into itself: choose another place", k.band())
    k.key(ktest.ENTER)
    # Root to another drive: every title and subject (the root's "\" and the paths meet once)
    k.key(CODE['C']); k.key(ktest.RIGHT, ktest.ENTER, '\\all', K_CODE_ENTER, ktest.ENTER, settle=False); k.settle(60)
    allA = A()
    check('Root to B:\\ALL: all of A: there', band() == 'Copied %d titles to B:\\ALL' % len(allA)
          and under(B(), 'A:\\ALL') == {n[2:]: v for n, v in allA.items()} and not sound(1), (k.band(), len(allA), sorted(B())))
    k.key(ktest.ENTER)
    # a subject two down to Root of B: (where it goes is the root)
    pick_subject(k, 'SUB'); k.key(CODE['C']); k.key(ktest.RIGHT, ktest.ENTER, '\\', K_CODE_ENTER, settle=False); k.settle(30)
    check('\\WORK\\SUB to B:\\ (the root): "Copied 2 titles to B:\\", DEEP under B:\\ too', band() == 'Copied 2 titles to B:\\'
          and B().get('A:\\B.TXT') == b'other text\r\n' and B().get('A:\\DEEP\\C.DAT') == BIG and not sound(1), (k.band(), sorted(B())))
    k.key(ktest.ENTER)
    # on the same drive: the Subject list shows the copy
    k.key(CODE['C']); k.key(ktest.ENTER, '\\subcopy', K_CODE_ENTER)
    check('SUB to \\SUBCOPY on A:: the question', band() == "A:\\SUBCOPY isn't there: Confirm to make it", k.band())
    k.key(ktest.ENTER, settle=False); k.settle(30)
    check('... Return: copied; the Subject list has SUBCOPY and DEEP in it, SUB still chosen', band() == 'Copied 2 titles to A:\\SUBCOPY'
          and A().get('A:\\SUBCOPY\\DEEP\\C.DAT') == BIG and '  SUBCOPY' in subjects(k) and '    DEEP' in subjects(k)
          and subjects(k)[k.u16('sel')].strip() == 'SUB' and not sound(0), (k.band(), subjects(k)))
    k.key(ktest.ENTER)
    k.key(CODE['C']); k.key(ktest.ENTER, '\\nope', K_CODE_ENTER, ktest.ESC)
    check('ESC at "isn\'t there": nothing made, nothing said', 'A:\\NOPE' not in D(0) and band() == 'Subject: Select item and confirm', (k.band(), D(0)))
    # an empty subject
    pick_subject(k, 'EMPTY'); k.key(CODE['C']); k.key(ktest.RIGHT, ktest.ENTER, '\\empty2', K_CODE_ENTER, ktest.ENTER)
    check('an empty subject: "Copied 0 titles to B:\\EMPTY2", made', band() == 'Copied 0 titles to B:\\EMPTY2' and 'A:\\EMPTY2' in D(1), (k.band(), D(1)))
    k.key(ktest.ENTER)
    # where it goes is a file; no disk in B:
    pick_subject(k, 'EMPTY'); k.key(CODE['C']); k.key(ktest.RIGHT, ktest.ENTER, '\\efile', K_CODE_ENTER)
    check('an empty subject to B:\\EFILE, a file there: "Can\'t copy EFILE: Access denied", the file as it was',
          band() == "Can't copy EFILE: Access denied" and B().get('A:\\EFILE') == b'was on B\r\n', (k.band(), B().get('A:\\EFILE')))
    k.key(ktest.ENTER)
    k.pc.drives[1].empty = True
    k.key(CODE['C']); k.key(ktest.RIGHT, ktest.ENTER, '\\x2', K_CODE_ENTER, settle=False); k.settle(60)
    check('... to B: with no disk in it: "Can\'t copy X2: ..." (not "Copied 0 titles")', band().startswith("Can't copy X2: ") and not k.crashed, k.band())
    k.pc.drives[1].empty = False
    k.key(ktest.ENTER)
    # a path DOS can't take where it goes: said before anything is made
    longsub = '\\' + '\\'.join(['ABCDEFGH'] * 6) + '\\ABCDEF'       # 61 characters: \WORK\EMPTY under it would be 67
    pick_subject(k, 'WORK'); k.key(CODE['C']); k.key(ktest.RIGHT, ktest.ENTER, longsub, K_CODE_ENTER)
    check('to a subject 61 characters long (\\EMPTY under it too long for DOS): "Can\'t copy WORK: Path not found", nothing made',
          band() == "Can't copy WORK: Path not found" and not [x for x in D(1) if 'ABCDEFGH' in x], (k.band(), D(1)))
    k.key(ktest.ENTER)
    pick_subject(k, 'KEEP'); k.key(CODE['C']); k.key(ktest.RIGHT, ktest.ENTER, ('ABCDEFGH\\' * 7) + 'ABC', K_CODE_ENTER)
    check('KEEP (a title, no subjects) to one of 67 characters (66 typed without the first \\): "Can\'t copy KEEP: Path not found", nothing made',
          band() == "Can't copy KEEP: Path not found" and not [x for x in D(1) if 'ABCDEFGH' in x], (k.band(), D(1)))
    k.key(ktest.ENTER)
    # a write-protected disk
    k.pc.drives[1].wp = True
    pick_subject(k, 'KEEP'); k.key(CODE['C']); k.key(ktest.RIGHT, K_CODE_ENTER, ktest.ENTER, settle=False); k.settle(30)
    check('KEEP to a write-protected B:: "Can\'t copy KEEP: Disk is write-protected", B: as it was',
          band() == "Can't copy KEEP: Disk is write-protected" and 'A:\\KEEP' not in D(1) and not k.crashed, (k.band(), D(1)))
    check('... and the Subject list as it was, KEEP chosen (the failed MKDIR leaves B:\'s FAT unchanged: 0.3.13)',
          [x.strip() for x in subjects(k)] == ['Root', 'HID', 'KEEP', 'SUBCOPY', 'DEEP', 'WORK', 'EMPTY', 'SUB', 'DEEP', 'WORKS', 'EMPTY', 'SUB', 'DEEP']
          and subjects(k)[k.u16('sel')].strip() == 'KEEP', [x.strip() for x in subjects(k)])
    k.key(ktest.ENTER)
    pick_subject(k, 'WORK'); k.key(CODE['C']); k.key(ktest.RIGHT, ktest.ENTER, ktest.ENTER, ktest.RIGHT, K_CODE_ENTER, settle=False); k.settle(30)
    check('WORK onto itself on the write-protected B: (Replace All): "Can\'t copy A.TXT: Disk is write-protected"',
          band() == "Can't copy A.TXT: Disk is write-protected" and under(B(), 'A:\\WORK') == WORK and not k.crashed, k.band())
    k.pc.drives[1].wp = False
    k.key(ktest.ENTER)
    check('... and the Executive\'s memory as it was (the blocks freed)', free_paras(k)[0] == free0 and not sound(0) and not sound(1),
          (free_paras(k)[0], free0))
    # help, and Move on a subject (not offered: a beep)
    k.key(ktest.F1)
    check('help: "CODE-C  Copy the file / subject"', has(k, 'CODE-C                   Copy the file / subject'), screen(k))
    k.key(ktest.ENTER)
    k.key(CODE['M'])
    check('CODE-M on a subject: nothing (a beep)', focus(k) == 2 and band() == 'Subject: Select item and confirm' and not k.crashed, k.band())

if __name__ == '__main__':
    t0 = time.time()
    build()
    only = [a for a in sys.argv[1:] if a.startswith('t_')]
    for t in (t_core, t_system, t_write, t_exec, t_font, t_memory, t_saver, t_mouse, t_form, t_files, t_file_safety, t_wild, t_subdel, t_subcopy, t_saver_delay, t_saver_tidy):
        if not only or t.__name__ in only: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
