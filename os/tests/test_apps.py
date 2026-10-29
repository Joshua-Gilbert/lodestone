"""Lodestone 0.3: the UI core and the .RUN programs, in pcemu.

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
OUT = os.environ.get('KOUT', os.path.join(__import__('tempfile').gettempdir(), 'lodestone-apps'))
os.makedirs(OUT, exist_ok=True)
SHOTS = os.path.join(GOS, 'screens', '0.3') if 'shots' in sys.argv else None
if SHOTS: os.makedirs(SHOTS, exist_ok=True)

SYS = os.path.join(GOS, 'src', 'LODE.SYS')
SYSTEM = os.path.join(GOS, 'apps', 'SYSTEM.RUN')
WRITE = os.path.join(GOS, 'apps', 'WRITE.RUN')
UITEST = os.path.join(HERE, 'UITEST.RUN')
CALCRUN = os.path.join(GOS, 'apps', 'CALC.RUN')
MEMSZ = os.path.join(HERE, 'MEMSZ.COM')
TSR = os.path.join(HERE, 'TSR.COM')
M33TEST = os.path.join(HERE, 'M33TEST.COM')
M33 = {n: os.path.join(HERE, n + '.COM') for n in ('M33GFX', 'M33QUIT', 'M33HSET', 'M33HVIC')}
LCMD = os.path.join(GOS, 'src', 'LCMD.COM')
TM5000G = os.environ.get('TM5000G') or os.path.join(GOS, '..', 'tools', 'TM5000G.EXE')
TERMFNT = os.path.join(GOS, 'fonts', 'TERMINUS.FNT')
DEFRAG = os.path.join(GOS, 'src', 'DEFRAG.COM')
MDTEST = os.path.join(HERE, 'MDTEST.COM')

K_HOME, K_END, K_PGDN, K_PGUP, K_DEL, K_INS = 0x4700, 0x4F00, 0x5100, 0x4900, 0x5300, 0x5200
K_CHOME, K_CEND, K_CLEFT, K_CRIGHT = 0x7700, 0x7500, 0x7300, 0x7400
K_CODE_HELP, K_CODE_ENTER, K_CODE_ESC = 0x3500, 0x1C00, 0x0100     # as INT 16h AH=10h returns them
CODE = {c: v for c, v in zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        (0x1E00, 0x3000, 0x2E00, 0x2000, 0x1200, 0x2100, 0x2200, 0x2300, 0x1700, 0x2400, 0x2500, 0x2600, 0x3200,
         0x3100, 0x1800, 0x1900, 0x1000, 0x1300, 0x1F00, 0x1400, 0x1600, 0x2F00, 0x1100, 0x2D00, 0x1500, 0x2C00))}

def build():
    subprocess.run([os.path.join(GOS, 'kbuild.sh')], check=True, stdout=subprocess.DEVNULL)
    for src, dst in (('apps/SYSTEM.ASM', SYSTEM), ('apps/WRITE.ASM', WRITE), ('tests/UITEST.ASM', UITEST), ('apps/CALC.ASM', CALCRUN),
                     ('apps/TASKS.ASM', os.path.join(GOS, 'apps', 'TASKS.RUN')),
                     ('tests/RCTEST.ASM', os.path.join(HERE, 'RCTEST.RUN')), ('tests/RC6.ASM', os.path.join(HERE, 'RC6.RUN')),
                     ('tests/MENUTEST.ASM', os.path.join(HERE, 'MENUTEST.RUN')),
                     ('tests/CLIPTEST.ASM', os.path.join(HERE, 'CLIPTEST.RUN'))):
        mkrun.build(os.path.join(GOS, src), dst)
    subprocess.run(['nasm', '-f', 'bin', '-o', MEMSZ, os.path.join(HERE, 'MEMSZ.ASM')], check=True)
    subprocess.run(['nasm', '-f', 'bin', '-o', TSR, os.path.join(HERE, 'TSR.ASM')], check=True)
    subprocess.run(['nasm', '-f', 'bin', '-o', MDTEST, os.path.join(HERE, 'MDTEST.ASM')], check=True)
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
def xor_rect_unit():
    """xor_rect as UICORE.INC has it (with row_di and NEXTROW), assembled on
    its own and run under unicorn against a model of the frame XORed into a
    random screen: every start bit, widths from 2 to 41 pixels, rows in each
    bank, several heights, frames to x 639 and to row 399; DF set every other
    time, DS its own segment and untouched."""
    import random
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_16
    from unicorn.x86_const import (UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX, UC_X86_REG_SI,
                                   UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_SP, UC_X86_REG_CS, UC_X86_REG_DS,
                                   UC_X86_REG_ES, UC_X86_REG_SS, UC_X86_REG_EFLAGS)
    s = open(os.path.join(GOS, 'src', 'UICORE.INC'), 'rb').read().decode('latin-1')
    part = lambda a, b: s[s.index(a):s.index(b, s.index(a))]
    src = ('cpu 286\norg 0\nVSEG equ 0B800h\n' + part('%macro  NEXTROW', '; compose the area') +
           'go: call xor_rect\n hlt\n' + part('row_di:', '; mode 40h') + part('xor_rect:', '; field SI\'s value'))
    asm, out = os.path.join(OUT, 'XORUNIT.ASM'), os.path.join(OUT, 'XORUNIT.BIN')
    open(asm, 'w').write(src)
    subprocess.run(['nasm', '-f', 'bin', '-o', out, asm], check=True)
    code = open(out, 'rb').read()               # go: at 0 (the macro makes no code), its hlt at 3
    assert code[3] == 0xF4, code[:4].hex()
    mu = Uc(UC_ARCH_X86, UC_MODE_16)
    mu.mem_map(0, 0x100000)
    mu.mem_write(0x10000, code)
    regs = (UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX, UC_X86_REG_SI, UC_X86_REG_DI, UC_X86_REG_BP)
    rnd = random.Random(1520)
    screen, dseg = bytes(rnd.getrandbits(8) for _ in range(0x10000)), bytes(rnd.getrandbits(8) for _ in range(0x10000))
    cases = [(x0, x0 + w, y, h) for y in (0, 1, 2, 3, 6, 389) for h in (2, 3, 5, 11)
             for x0 in range(0, 24) for w in range(2, 42)]
    cases += [(x0, 639, y, h) for x0 in range(600, 638) for y, h in ((0, 2), (3, 11), (388, 12))]
    cases += [(x0, x0 + w, y, 400 - y) for y in range(388, 399) for x0 in (0, 5, 600) for w in (2, 9, 30)]
    cases += [(0, 639, 0, 400), (1, 638, 1, 399)]
    bad, n = [], 0
    for x0, x1, y, h in cases:                  # DI: the right edge's pixel
        mu.mem_write(0xB8000, screen)
        mu.mem_write(0x50000, dseg)
        vals = (x0, 0x1234, h, y, 0x5678, x1, 0x9ABC)
        for r, v in zip(regs, vals): mu.reg_write(r, v)
        for r, v in ((UC_X86_REG_CS, 0x1000), (UC_X86_REG_DS, 0x5000), (UC_X86_REG_ES, 0x2000),
                     (UC_X86_REG_SS, 0x3000), (UC_X86_REG_SP, 0xFFFE), (UC_X86_REG_EFLAGS, 0x0402 if n & 1 else 0x0002)):
            mu.reg_write(r, v)
        mu.emu_start(0x10000, 0x10003, count=1000000)
        want = set()                            # the frame, each pixel XORed as often as drawn
        for yy in range(y, y + h):
            want ^= {(x0, yy)}; want ^= {(x1, yy)}
        for xx in range(x0 + 1, x1):
            want ^= {(xx, y)}; want ^= {(xx, y + h - 1)}
        exp = bytearray(screen)
        for px, py in want:
            exp[(py & 3) * 0x2000 + (py >> 2) * 80 + px // 8] ^= 0x80 >> (px & 7)
        kept = [mu.reg_read(r) for r in regs] == list(vals) and mu.reg_read(UC_X86_REG_SP) == 0xFFFE \
            and mu.reg_read(UC_X86_REG_ES) == 0x2000 and mu.reg_read(UC_X86_REG_DS) == 0x5000 \
            and bytes(mu.mem_read(0x50000, 0x10000)) == dseg
        n += 1
        if bytes(mu.mem_read(0xB8000, 0x10000)) != bytes(exp) or not kept:     # (all of ES: nothing past the plasma)
            bad.append((x0, x1, y, h, kept))
    return n, bad

# ---------------------------------------------------------------------
def t_core():
    print('== core (UITEST.RUN)')
    n, bad = xor_rect_unit()
    check('xor_rect on its own (%d frames on a random screen: every start bit, 2-41 pixels wide, each bank, heights '
          '2-11, to x 639 and row 399, DF either way): the frame XORed once, corners included, nothing else touched, '
          'the registers, DS and ES kept' % n, n > 20000 and not bad, bad[:5])
    img = image('core.img', UITEST, os.path.join(GOS, 'src', 'LCMD.COM'))
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    free0, ui0 = free_paras(k)
    check('the map: uibss on the paragraph after ui_image_end (UI_PARAS, UIBOOT_ORG and the rest count on it; NASM can\'t check it)',
          k.Y['ui_bss_start'] == (k.Y['ui_image_end'] + 15) & ~15, (hex(k.Y['ui_bss_start']), hex(k.Y['ui_image_end'])))
    shot(k, 'executive')
    hw = lambda: struct.unpack('<4H', k.rd('help_w', 8))   # (W_COL, W_Y, W_W, W_H)
    k.key(ktest.F1); shot(k, 'executive_help'); geo = [hw()]; k.key(ktest.ENTER)
    # the 1520's BIOS gives CODE-? (and CODE-Return, CODE-ESC) only through
    # INT 16h AH=10h; pcemu now models that
    k.key(K_CODE_HELP)
    check('CODE-? opens the Executive\'s help', has(k, 'Lodestone 0.6 Help'), screen(k))
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
    shot(k, 'core_form'); geo.append(hw())
    check('form: a window with text and choice fields', has(k, 'Find       hello') and has(k, 'Independent of case') and has(k, 'Fill in form'), screen(k))
    k.key('world'); k.key(ktest.ENTER); k.key(ktest.RIGHT); k.key(ktest.ENTER); k.key(' '); k.key(ktest.ENTER)
    check('form: typing replaces the old text, Right and Space change choices, Return confirms', has(k, 'Find: world 1 1'), screen(k))
    k.key(CODE['F']); k.key('again'); k.key(K_CODE_ENTER)
    check('form: CODE-Return confirms from the first field', has(k, 'Find: again 1 1'), screen(k))
    k.key(CODE['F']); k.key('world'); k.key(K_CODE_ENTER)
    k.key(CODE['F']); k.key(ktest.ESC)
    check('form: ESC cancels and changes nothing', has(k, 'Find: world 1 1') and not has(k, 'Fill in form'), screen(k))
    k.key(CODE['F']); k.key(ktest.DOWN); f1 = k.u16('fm_cur'); k.key(ktest.DOWN, ktest.DOWN); f3 = k.u16('fm_cur'); k.key(ktest.ESC)
    check('form: Down goes to the next field, and from the last back to the first', (f1, f3) == (1, 0), (f1, f3))
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
    check('... drawn where it was asked to be: column 2 of row 260', dict(k.ocr()).get(260, '')[:25] == '  Disk is write-protected',
          dict(k.ocr()).get(260))
    # each INT 24h code through 83 (the message is DOS's code + 18 since U4),
    # one past them, and the DOS codes only INT 24h's table used to hold
    line, a, case = k.u16('run_base') + run_syms('tests/UITEST.ASM')['line'], k.Y['api_sberr'], []
    def sberr(pc):
        if case and pc.r('ip') == a and pc.r('cs') == k.useg:
            ax, crit = case.pop(0)
            pc.w('ax', ax); k.wr('crit_err', struct.pack('<H', crit))
    k.hooks.append(sberr)
    want = {(83, 1): 'Disk is write-protected', (83, 2): 'Unknown drive', (83, 3): 'Drive not ready (no disk?)',
            (83, 4): 'Disk error (unknown command)', (83, 5): 'Disk error (data)', (83, 6): 'Disk error (bad request)',
            (83, 7): 'Disk error (seek)', (83, 8): 'Not a DOS disk', (83, 9): 'Disk error (sector not found)',
            (83, 10): 'Printer out of paper', (83, 11): 'Disk error (write)', (83, 12): 'Disk error (read)',
            (83, 13): 'Disk error', (83, 14): 'error 14', (83, 0): 'Disk error', (20, 0): 'Unknown drive',
            (22, 0): 'Disk error (unknown command)', (24, 0): 'Disk error (bad request)', (28, 0): 'Printer out of paper',
            (32, 0): 'error 32'}
    got = {}
    for c in want:
        case.append(c); k.key(CODE['E'])
        got[c] = k.pc.rd(k.useg, line, 80).split(b'\0')[0].decode()
    k.hooks.remove(sberr)
    check("error text: an INT 24h error (83) says the disk's (1-13), or its number; DOS's 20/22/24/28 say theirs",
          got == want, [(c, got[c]) for c in want if got[c] != want[c]])
    before = k.pc.rd(0xB800, 0, 0x8000)
    k.key(ktest.F1); geo.append(hw())
    check('help window from the key table', has(k, 'CODE-F     the form') and has(k, 'ESC        leave'), screen(k))
    check('help and form windows centred across, help\'s as wide as its longest line or title + 6, between the title rule '
          'and the band (the Executive\'s help, the form, UITEST\'s help: column, row, width, height)',
          geo == [(11, 44, 57, 292), (15, 96, 50, 100), (27, 140, 26, 100)], geo)
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
    open(os.path.join(OUT, 'BAD4.RUN'), 'wb').write(hdr(1, 0, 0, 0) + b'\xc3')     # an image under 2 bytes, no fixups
    open(os.path.join(OUT, 'BAD5.RUN'), 'wb').write(hdr(4, 0xFF00, 0, 0) + b'\xc3\x90\x90\x90')     # BSS past 64 KB
    open(os.path.join(OUT, 'BAD6.RUN'), 'wb').write(hdr(100, 0, 0, 0) + b'\xc3\x90\x90\x90')        # the file cut short
    img = image('bad2.img', *(os.path.join(OUT, 'BAD%d.RUN' % i) for i in range(2, 7)))
    k = ktest.KPC(img); k.start()
    table = k.pc.rd(k.useg, 0, 135)
    for name, why in (('BAD2.RUN', 'Not a program'), ('BAD3.RUN', 'Not a program'), ('BAD4.RUN', 'Not a program'),
                      ('BAD5.RUN', 'Not enough memory'), ('BAD6.RUN', 'Not a program')):
        k.select(name); k.key(ktest.ENTER)
        check('%s (a damaged header): "%s", the core untouched, the UI block its own size again' % (name, why),
              any("Can't run %s: %s" % (name, why) in l for l in k.band()) and not k.crashed and k.pc.rd(k.useg, 0, 135) == table
              and free_paras(k)[1] == ui0, (k.band(), k.where(), free_paras(k)[1], ui0))
        k.key(ktest.ENTER)
    # the kinds, and the band for one that nothing opens; Claude not on the disk
    kinds = {'A.TXT': 'Text', 'B.DAT': 'Data', 'C.BAT': 'Batch', 'D.INI': 'Settings', 'E.TYP': 'Font', 'F.PRO': 'Profile',
             'G.ASM': 'Source', 'H.C': 'Source', 'I.H': 'Source', 'J.XYZ': 'XYZ', 'K': 'File'}
    for n in kinds: open(os.path.join(OUT, n), 'wb').write(b'x')
    k = ktest.KPC(image('kinds.img', MEMSZ, *(os.path.join(OUT, n) for n in kinds))); k.start()
    k.run_file('MEMSZ.COM', 20); k.key(ktest.ENTER)
    check('after a DOS program the UI block is its own size again: UI_PARAS, (ui_bss_end + 15) / 16 paragraphs',
          free_paras(k)[1] == (k.Y['ui_bss_end'] + 15) // 16, (free_paras(k)[1], k.Y['ui_bss_end']))
    got = {}
    for n in kinds:
        k.select(n); got[n] = form(k)[3].split(' ')[0]
    check('the Kind of each extension', got == kinds, got)
    k.select('B.DAT'); k.key(ktest.ENTER)
    check('Return on a kind nothing opens: "B  Data - nothing opens this kind yet"', k.band()[:1] == ['B  Data - nothing opens this kind yet'], k.band())
    k.key(ktest.ENTER); k.key(CODE['A'])
    check('CODE-A with no CLAUDE.COM: "CLAUDE.COM is not on this disk"', k.band()[:1] == ['CLAUDE.COM is not on this disk'], k.band())
    k.key(ktest.ENTER)

# ---------------------------------------------------------------------
def t_system():
    print('== System (SYSTEM.RUN)')
    img = image('sys.img', SYSTEM, MEMSZ, os.path.join(GOS, 'src', 'LCMD.COM'))
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
    labels = ('Conventional memory', 'Kernel (DOS + GPIB)', 'Executive and UI core', 'System (this program)', 'Disk cache', 'Free for programs')
    check('... each line its label and figure; "Expanded memory (EMS)  1408 KB" as the GRiD BIOS has it',
          all(re.search(re.escape(l) + r'\s+[\d.]+ KB', screen(k)) for l in labels)
          and re.search(r'Expanded memory \(EMS\)\s+1408 KB', screen(k)), screen(k))
    k.key(ktest.DOWN)
    shot(k, 'system_disks')
    check('Disks: label, size, free', has(k, 'Drive A:') and has(k, 'LODESTONE') and has(k, '1423 KB'), screen(k))
    check('... "Size  1423 KB", "Free" and "In use" each labelled, adding up',
          re.search(r'  Size\s+1423 KB', screen(k)) and sum(int(re.search(r'  %s\s+(\d+) KB' % l, screen(k)).group(1))
                                                             for l in ('Free', 'In use')) == 1423, screen(k))
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
    k.key(ktest.ENTER); k.key('31 dec 1999'); k.key(ktest.ENTER); k.key(ktest.ENTER)
    check('a 19xx date: the title bar says 31-Dec-99', lines(k)[0].strip().startswith('31-Dec-99'), lines(k)[0])
    k.key(ktest.ENTER); k.key('7 nov 2026'); k.key(ktest.ENTER); k.key(ktest.ENTER)
    check('... and 7-Nov-26 again', lines(k)[0].strip().startswith('7-Nov-26'), lines(k)[0])
    for bad in ('65567-Oct-2026', '5-Octx-2026', '5-Oct-2026 x'):
        k.key(ktest.ENTER); k.key(bad); k.key(ktest.ENTER); k.key(ktest.ENTER)
        check('"%s" is not a date' % bad, any('Not a date' in l for l in k.band()), k.band())
        k.key(ktest.ENTER); k.key(ktest.ESC)
    for bad in ('13 pm', '9:41 xm'):
        k.key(ktest.ENTER); k.key(ktest.ENTER); k.key(bad); k.key(ktest.ENTER)
        check('"%s" is not a time' % bad, any('Not a time' in l for l in k.band()), k.band())
        k.key(ktest.ENTER); k.key(ktest.ESC)
    k.key('D')
    check('Devices: 80287XL (pcemu\'s is 387-class), BIOS, panel, mouse', has(k, '80287XL') and has(k, '10/25/89') and has(k, 'Plasma 640x400') and has(k, 'COM2'), screen(k))
    k.key('G')
    check('GPIB: the built-in driver, SRQ on IRQ 5', has(k, 'built in, version 1.23, INT 60h') and has(k, '21')
          and has(k, 'on IRQ 5'), screen(k))
    k.key(ktest.ENTER); k.key(ktest.ENTER, settle=False); k.settle(30)
    shot(k, 'system_gpib')
    check('GPIB scan finds the instruments on the simulated bus (6, 14, 29)', re.search(r'Instruments at\s+6, 14, 29', screen(k)), screen(k))
    k.key('A')
    check('About', has(k, 'Lodestone 0.6') and has(k, '3.30 compatible'), screen(k))
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
    check('help: GRiDWrite\'s command summary, Cut, Copy and Paste among them, all 18 lines shown',
          has(k, 'Begin       CODE-B    Restart the selection') and has(k, 'Cancel      CODE-ESC') and has(k, 'Copy        CODE-C')
          and has(k, 'Cut         CODE-Z') and has(k, 'Paste       CODE-V') and has(k, 'Any key closes')
          and has(k, 'Find        CODE-F    Find text') and has(k, 'Quit        CODE-Q    Save and exit')
          and has(k, 'A command, then select, then Return (or drag first)'), screen(k))
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

def wtext(k, ws):
    """Write's text as it holds it (the gap buffer, lines ending in LF)."""
    v = lambda n: k.pc.u16(k.useg, k.u16('run_base') + ws[n])
    seg, gs, ge, cap = v('bseg'), v('gap_s'), v('gap_e'), v('cap')
    return bytes(k.pc.rd(seg, 0, gs)) + bytes(k.pc.rd(seg, ge, cap - ge))

def t_write_mouse():
    """Write with the mouse (UI API 8): a drag selects, then a command works
    on it; a right click in the text gives a menu of the commands."""
    print('== Write with the mouse: drags and its menu (UI API 8)')
    ws = run_syms('apps/WRITE.ASM')
    T = TEXT.replace(b'\r\n', b'\n')
    at = lambda c, r: (c * 8 + 2, 24 + r * 16 + 8)          # (column, row) of the whole-screen text area
    def wv(n): return k.pc.u16(k.useg, k.u16('run_base') + ws[n])
    def wb(n): return k.pc.rd(k.useg, k.u16('run_base') + ws[n], 1)[0]
    def rpress(x, y):
        point(k, x, y); k.pc.mouse_move(0, 0, 2); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05); k.settle()
    def hold(x0, y0, path, t=0.0):
        """The left button down at (x0, y0), moved by each (dx, dy) of path, held t s more, let go."""
        point(k, x0, y0); k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05)
        for dx, dy in path: k.pc.mouse_move(dx & 0xFF, dy & 0xFF, 1); k.pc.run_for(0.05)
        if t: k.pc.run_for(t)
        k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05); k.settle()
    hdr = open(WRITE, 'rb').read(6)
    check('WRITE.RUN asks for UI API 8', hdr == b'GRUN\x08\x00', hdr)
    k = write_open(mouse=True)
    drag(k, *at(4, 0), *at(9, 0))
    check('a drag over "quick": a selection of its own (no command yet), from where it began to where it ended; the band says what to do',
          wb('mode') == 1 and wb('cmd') == 0 and wv('anchor') == 4 and wv('gap_s') == 9
          and k.band()[0].startswith('Selected: CODE-E erases'), (wb('mode'), wb('cmd'), wv('anchor'), wv('gap_s'), k.band()))
    k.key(CODE['E'])
    t1 = T.replace(b'quick', b'', 1)
    check('... CODE-E: erased at once; editing again', wtext(k, ws) == t1 and wb('mode') == 0
          and k.band()[0].startswith('Type, or choose a command'), (wtext(k, ws), wb('mode'), k.band()))
    drag(k, *at(0, 1), *at(5, 1))
    k.key(CODE['M'])
    pt = k.band()[0]
    click(k, *at(30, 2)); k.key(ktest.ENTER)
    t2 = t1.replace(b'jumps over', b' over').replace(b'dog.', b'dog.jumps')
    check('a drag over "jumps", CODE-M: where to?; a click after "dog.", Return: moved there', pt == 'Move: Point to destination and confirm'
          and wtext(k, ws) == t2 and wb('mode') == 0, (pt, wtext(k, ws)))
    drag(k, *at(0, 4), *at(5, 4))
    k.key(ktest.BKSP)
    t3 = t2.replace(b'last line', b'line')
    check('a drag over "last ", Backspace: erased', wtext(k, ws) == t3 and wb('mode') == 0, wtext(k, ws))
    drag(k, *at(0, 0), *at(3, 0))
    k.key('X')
    check('a drag, then a character: the selection goes, the character is typed at the cursor (nothing erased)',
          wtext(k, ws) == b'TheX' + t3[3:] and wb('mode') == 0, wtext(k, ws))
    drag(k, *at(0, 2), *at(6, 2))
    click(k, *at(8, 3))
    check('a drag, then a click: the selection goes, the cursor where it was clicked (line 4, after the tab: column 9 shown)',
          wb('mode') == 0 and has(k, 'Line 4 of 5   Column 9'), (wb('mode'), k.band(), screen(k)))
    hold(*at(2, 1), [(40, 0), (-40, 0)])
    check('a drag back where it began: no selection (editing, the cursor there)', wb('mode') == 0 and has(k, 'Line 2 of 5   Column 3'),
          (wb('mode'), screen(k)))
    k.key(K_CHOME, CODE['E'])
    drag(k, *at(5, 0), *at(11, 0))
    k.key(ktest.ENTER)
    check('CODE-E first, then a drag: the drag is the selection (from where it began), Return erases it',
          wtext(k, ws) == b'TheX ' + t3[10:] and wb('mode') == 0, wtext(k, ws))
    # a drag's selection: its other keys; a drag while pointing; no menu making one for a command
    k = write_open(mouse=True)
    drag(k, *at(4, 0), *at(9, 0))                       # ("quick")
    k.key(ktest.RIGHT, ktest.RIGHT)
    ext = (wb('mode'), wv('anchor'), wv('gap_s'))
    k.key(ktest.ENTER)
    ent = (wb('mode'), wtext(k, ws) == T)
    k.key(ktest.ESC)
    check('a drag\'s selection: Right x2 extends it (4 to 11); Return beeps, nothing changes; ESC ends it, nothing erased, still in Write',
          ext == (1, 4, 11) and ent == (1, True) and wb('mode') == 0 and wtext(k, ws) == T
          and k.band()[0].startswith('Type, or choose a command'), (ext, ent, wb('mode'), k.band()))
    drag(k, *at(4, 0), *at(9, 0))
    k.key(CODE['B'], CODE['E'])
    eb = (wb('mode'), wb('cmd'), wv('anchor'), wv('gap_s'))
    k.key('Y')
    check('a drag, CODE-B (it begins again at the cursor: empty), CODE-E: a beep, still a drag\'s selection (no command); a '
          'character then ends it and is typed', eb == (1, 0, 9, 9) and wb('mode') == 0 and wtext(k, ws) == T.replace(b'quick', b'quickY', 1),
          (eb, wb('mode'), wtext(k, ws)))
    k.key(ktest.BKSP)
    drag(k, *at(4, 0), *at(10, 0)); k.key(K_DEL)
    d1 = wtext(k, ws)
    drag(k, *at(0, 1), *at(5, 1)); k.key(CODE['D'])
    drag(k, *at(0, 2), *at(30, 2)); k.key(ktest.ENTER)
    check('Delete erases one ("quick "); CODE-D takes one ("jumps"), a drag while pointing puts the cursor where it ends (after "dog."), Return: duplicated there',
          d1 == T.replace(b'quick ', b'', 1) and wtext(k, ws) == d1.replace(b'dog.', b'dog.jumps'), (d1, wtext(k, ws)))
    k.key(CODE['E'])
    rpress(*at(2, 2))
    check('making a selection for a command (CODE-E): a right click gives no menu', not has(k, 'Substitute...')
          and k.band()[0] == 'Erase: Make a selection and confirm', (k.band(), screen(k)))
    k.key(ktest.ESC)
    # the menu: the cursor goes where the right click was; Find from it
    k = write_open(mouse=True)
    rpress(*at(4, 2))
    shown = has(k, 'Erase          CODE-E') and has(k, 'Substitute...  CODE-S') and has(k, 'Jump...        CODE-J')
    k.key(ktest.DOWN, ktest.DOWN, ktest.DOWN, ktest.ENTER)
    check('a right click on line 3: the menu there (Erase ... Jump); Down 3 times, Return: Find\'s form, the cursor where it was clicked',
          shown and k.band()[0] == 'Find: Fill in form and confirm' and wv('gap_s') == 35, (shown, k.band(), wv('gap_s')))
    k.key(ktest.ESC)
    drag(k, *at(4, 0), *at(10, 0))
    rpress(*at(15, 0))
    k.key(ktest.ENTER)
    check('a drag over "quick ", a right click (elsewhere on the line), Erase: the selection kept for it, erased',
          wtext(k, ws) == T.replace(b'quick ', b'', 1) and wb('mode') == 0, wtext(k, ws))
    drag(k, *at(0, 1), *at(5, 1))
    rpress(*at(2, 3))
    k.key('M', ktest.ENTER)
    check('... a drag, a right click, M (the letter), Return: Move, where to?', k.band()[0] == 'Move: Point to destination and confirm'
          and wb('mode') == 2, k.band())
    rpress(*at(2, 3))
    check('pointing: a right click gives no menu', not has(k, 'Substitute...') and wb('mode') == 2, screen(k))
    k.key(ktest.ESC)
    g = wv('gap_s')
    rpress(300, 345)
    check('a right click on the status line: no menu, the cursor stays', not has(k, 'Substitute...') and wv('gap_s') == g, screen(k))
    rpress(*at(3, 4))
    k.key(ktest.ESC)
    check('a right click, ESC: no command, the cursor where it was clicked', k.band()[0].startswith('Type, or choose a command')
          and has(k, 'Line 5 of 5   Column 4'), (k.band(), screen(k)))
    k.key(K_CHOME, CODE['F']); k.key('lazy'); k.key(ktest.ENTER, ktest.ENTER, ktest.ENTER)
    f = k.band()[0]
    rpress(*at(1, 0)); k.key(ktest.ESC)
    check('Find (found), then a right click: back to editing, the cursor where it was clicked', f == 'Find: Confirm for next occurrence'
          and wb('mode') == 0 and k.band()[0].startswith('Type, or choose a command') and wv('gap_s') == 1, (f, wb('mode'), k.band(), wv('gap_s')))
    drag(k, *at(0, 1), *at(3, 1))
    rpress(*at(1, 1)); k.key('J', ktest.ENTER); k.key('1'); k.key(ktest.ENTER)
    check('a drag, a right click, Jump: the selection ends first; line 1', wb('mode') == 0 and has(k, 'Line 1 of 5')
          and k.band()[0].startswith('Type, or choose a command'), (wb('mode'), k.band(), screen(k)))
    # a drag past the bottom of the text area: the view scrolls with it
    long = b''.join(b'Line %d\r\n' % i for i in range(60))
    k = write_open('LONG.TXT', long, mouse=True)
    hold(*at(2, 5), [(0, 40)] * 7, 1.0)
    tl, gs, cl = wv('topline'), wv('gap_s'), wv('curline')
    check('a drag held below the text area: the view scrolls on (line %d at the top), the cursor on its last row, the selection from '
          'where it began to it (%d)' % (tl, gs), tl >= 9 and cl == tl + 18 and wb('mode') == 1
          and wv('anchor') == len(b''.join(b'Line %d\n' % i for i in range(5))) + 2 and gs == len(b''.join(b'Line %d\n' % i for i in range(cl))) + 2, (tl, cl, wb('mode'), wv('anchor'), gs))
    hold(*at(2, 3), [(0, -40)] * 3, 0.5)
    tl2, cl2 = wv('topline'), wv('curline')
    check('... a drag held above it: the view scrolls back (line %d at the top, from %d), the cursor on its first row, a new selection'
          % (tl2, tl), tl2 <= tl - 4 and cl2 == tl2 and wb('mode') == 1 and wv('gap_s') < wv('anchor'), (tl2, cl2, wb('mode')))

def t_write_clip():
    """Write's Cut, Copy and Paste (CODE-Z, CODE-C, CODE-V) through the
    clipboard every .RUN shares (UI_CLIP), and in its right click's menu."""
    print('== Write: Cut, Copy and Paste (the clipboard, UI_CLIP)')
    ws = run_syms('apps/WRITE.ASM')
    T = TEXT.replace(b'\r\n', b'\n')
    at = lambda c, r: (c * 8 + 2, 24 + r * 16 + 8)
    def wb(n): return k.pc.rd(k.useg, k.u16('run_base') + ws[n], 1)[0]
    def rpress(x, y):
        point(k, x, y); k.pc.mouse_move(0, 0, 2); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05); k.settle()
    clip = lambda: (k.u16('clip_len'), disk_file(k, 'CLIP.$$$'))
    k = write_open(mouse=True)
    rpress(*at(4, 2))
    m0 = has(k, 'Erase          CODE-E') and not has(k, 'Paste') and not has(k, 'Cut ') and not has(k, 'Copy ')
    k.key(ktest.ESC)
    k.key(CODE['C'], CODE['Z'], CODE['V'])
    check('the clipboard empty, nothing selected: the menu has no Cut, Copy or Paste; CODE-C, CODE-Z, CODE-V do nothing (not even "Changed")',
          m0 and wtext(k, ws) == T and clip() == (0, None) and wb('mode') == 0 and not has(k, 'Changed'), (m0, wtext(k, ws), clip()))
    drag(k, *at(9, 0), *at(4, 0)); k.key(CODE['C'])           # (from right to left: the selection past the cursor, the gap)
    c1 = (wb('mode'), clip())
    bd = k.band()[-1]
    click(k, *at(30, 1)); k.key(CODE['V'])
    t1 = T.replace(b'jumps over', b'jumps overquick')
    check('a drag over "quick" (from its end), CODE-C: in the clipboard (CLIP.$$$, no EMS here), still selected; a click after "over", CODE-V: pasted there',
          c1 == (1, (5, b'quick')) and bd.startswith('CODE-Z cuts   CODE-C copies') and wtext(k, ws) == t1 and has(k, 'Changed') and has(k, 'Line 2 of 5   Column 16'), (c1, bd, wtext(k, ws)))
    drag(k, *at(10, 0), *at(15, 0)); k.key(CODE['Z'])
    t2 = t1.replace(b'brown', b'', 1)
    c2 = (wb('mode'), clip())
    drag(k, *at(4, 2), *at(8, 2)); k.key(CODE['V'])
    t3 = t2.replace(b'lazy', b'brown')
    check('a drag over "brown", CODE-Z: cut (in the clipboard, out of the text); a drag over "lazy", CODE-V: replaced by it',
          c2 == (0, (5, b'brown')) and wtext(k, ws) == t3 and wb('mode') == 0 and clip() == (5, b'brown'), (c2, wtext(k, ws), clip()))
    rpress(*at(0, 4))
    m1 = has(k, 'Paste          CODE-V') and not has(k, 'Cut ') and not has(k, 'Copy ')
    k.key(ktest.ENTER)
    t4 = t3.replace(b'last line', b'brownlast line')
    check('nothing selected, something to paste: the menu has Paste (first), no Cut or Copy; Return: pasted where it was clicked',
          m1 and wtext(k, ws) == t4, (m1, wtext(k, ws)))
    drag(k, *at(8, 3), *at(14, 3))
    rpress(*at(20, 3))
    m2 = has(k, 'Cut            CODE-Z') and has(k, 'Copy           CODE-C') and has(k, 'Paste          CODE-V')
    k.key(ktest.ENTER)
    t5 = t4.replace(b'Tabbed', b'', 1)
    check('a drag over "Tabbed", a right click: Cut, Copy and Paste first; Return: cut', m2 and wtext(k, ws) == t5
          and clip() == (6, b'Tabbed') and wb('mode') == 0, (m2, wtext(k, ws), clip()))
    drag(k, *at(4, 0), *at(9, 0))
    rpress(*at(2, 0)); k.key(ktest.DOWN, ktest.ENTER)
    mc = (wtext(k, ws) == t5, clip(), wb('mode'))
    drag(k, *at(11, 0), *at(14, 0))
    rpress(*at(12, 0)); k.key(ktest.DOWN, ktest.DOWN, ktest.ENTER)
    t5 = t5.replace(b'fox', b'quick', 1)
    check('a drag over "quick", a right click, Down, Return (Copy): copied, the text as it was, still selected; a drag over '
          '"fox", the menu\'s Paste (third): replaced by it', mc == (True, (5, b'quick'), 1) and wtext(k, ws) == t5 and wb('mode') == 0,
          (mc, wtext(k, ws)))
    drag(k, *at(0, 1), *at(0, 2)); k.key(CODE['C'], ktest.ESC, K_CEND, CODE['V'])
    t6 = t5 + b'jumps overquick\n'
    check('a drag over a whole line (its end too), CODE-C, ESC, Ctrl-End, CODE-V: a line more (6), the cursor on the new last one',
          wtext(k, ws) == t6 and clip()[1] == b'jumps overquick\n' and has(k, 'Line 6 of 6   Column 1'), (wtext(k, ws), clip(), screen(k)))
    k.key(CODE['Q'], ktest.ENTER)
    saved = disk_file(k, 'NOTES.TXT')
    k.select('NOTES.TXT'); k.key(ktest.ENTER); k.key(CODE['V'])
    check('saved (CR LF), quit; Write again: CODE-V pastes what the last one copied (the core keeps it)',
          saved == t6.replace(b'\n', b'\r\n') and wtext(k, ws) == b'jumps overquick\n' + t6, (saved, wtext(k, ws)))
    big = b''.join(b'%05d ' % i + b'x' * 58 + b'\r\n' for i in range(300))     # (19,500 bytes in Write: lines end in LF)
    k = write_open('BIG.TXT', big, mouse=True)
    drag(k, *at(0, 0), *at(3, 0)); k.key(CODE['C'])
    c0 = clip()
    k.key(K_CEND, CODE['C'])
    b1 = k.band()[0]
    k.key(ktest.ENTER)
    c8 = clip()
    k.key(CODE['Z'])
    b2 = k.band()[0]
    k.key(ktest.ENTER)
    z8 = wtext(k, ws) == big.replace(b'\r\n', b'\n')
    k.key(K_CHOME, ktest.DOWN, ktest.DOWN, K_END)     # (extended to line 3's end)
    k.key(CODE['C'])
    check('"000" copied; a selection of 19,500 bytes, CODE-C: "%s", the clipboard as it was ("000"); CODE-Z: the same, nothing '
          'erased; then the first 3 lines: copied' % b1,
          b1 == 'The clipboard holds 16 KB at most' and c0 == (3, b'000') and c8 == c0 and b2 == b1 and z8
          and clip()[0] == 3 * 65 - 1 and wb('mode') == 1, (b1, c0, c8, b2, z8, clip()))
    # past the cursor (after the gap), and emptied
    k = write_open(mouse=True)
    k.key('XY', K_CHOME)
    drag(k, *at(5, 0), *at(0, 0)); k.key(CODE['C'])
    c7 = clip()
    k.key(CODE['B'], CODE['C'])
    check('"XY" typed, Ctrl-Home, a drag from right to left over "XYThe", CODE-C: those; CODE-B (empty), '
          'CODE-C: a beep, the clipboard as it was', c7 == (5, b'XYThe') and clip() == (5, b'XYThe') and wb('mode') == 1, (c7, clip()))
    k.key(ktest.ESC)
    drag(k, *at(0, 0), *at(2, 0)); k.key(CODE['V'])
    check('a drag over "XY" (at the start), CODE-V: replaced by the 5 bytes (the room the gap\'s and the selection\'s, not where it ends)',
          wtext(k, ws) == b'XYThe' + T and k.band()[0].startswith('Type, or choose a command'), (wtext(k, ws)[:20], k.band()))

# ---------------------------------------------------------------------
def t_memory():
    print('== memory')
    img = image('mem.img', MEMSZ, os.path.join(GOS, 'src', 'LCMD.COM'))
    k = ktest.KPC(img); k.start()
    out = k.run_file('MEMSZ.COM', 20)
    m = re.search(r'([\d.]+) KB for programs', out)
    kb = float(m.group(1)) if m else 0
    check('a DOS program gets %.1f KB (0.2.2: 570.7 KB; INT 33h and the File form cost 2.8 KB, the file commands 2.8 KB, the saver setting 0.2 KB, wildcards and making subjects 1.1 KB, deleting subjects 0.4 KB, '
          'screen capture 0.5 KB, the kernel\'s part of drive C: 0.2 KB, the saver\'s round of the disks and its switch 0.1 KB, '
          'copying subjects 0.9 KB, the coprocessor lamp and the calculator\'s key 0.2 KB, 0.6\'s search by PATH and the two settings files 0.1 KB, '
          'windows that move and close (UI API 6) 0.5 KB, printer drivers read at PrtSc (PRINTER=) 0.2 KB; then 0.9 KB back, the kernel batch of the 2026-10-20 audit, and 1.3 KB, its UI batch, and 0.9 KB, the start-up of the UI run from the directory buffer, and 1.0 KB, the kernel\'s run from its disk buffers, and 0.7 KB, the row table; then 32 bytes, right clicks, UI API 7; 0.1 KB less, names and devices answered as MS-DOS 3.30, and 0.1 KB, DIR\\NUL; then 0.2 KB, the Executive\'s part of multitasking: Return as a task, CODE-T, the UI block moved once no task is left; 0.3 KB, GPIB\'s SRQ on IRQ 5; 0.5 KB, pop-up menus and drags, UI API 8; 0.3 KB, the clipboard, UI_CLIP; then 0.1 KB back, the kernel batch of the 2026-10-26 audit, and 0.1 KB, its UI batch): the directory buffer is lent while it runs' % kb,
          kb >= 564.8, out[-200:])
    check('afterwards the Executive has its whole list again', k.u16('ent_max') == 240 and 'MEMSZ.COM' in k.exec_list(), k.u16('ent_max'))
    # with EMS the disk cache is two EMS pages: programs get its 18 KB
    # (less the EMS manager's 2), and System says where it went
    k = ktest.KPC(image('mem_ems.img', MEMSZ, SYSTEM), ems_pages=88); k.start()
    out = k.run_file('MEMSZ.COM', 20)
    m = re.search(r'([\d.]+) KB for programs', out)
    kbe = float(m.group(1)) if m else 0
    check('with EMS a DOS program gets %.1f KB: the disk cache is in EMS (%.1f KB more)' % (kbe, kbe - kb),
          kbe - kb > 15.85, out[-200:])      # (16 KB: both figures rounded to 0.1 KB)
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
          k.exec_list() == ['LODE.SYS', 'MEMSZ.COM', 'SYSTEM.RUN', 'TSR.COM'], (hex(u0), hex(k.useg), k.u16('ent_max'), k.exec_list()))
    off, seg = struct.unpack('<HH', k.pc.rd(0, 0x24 * 4, 4))
    moff, mseg = struct.unpack('<HH', k.pc.rd(0, 0x0B * 4, 4))
    m33seg = k.pc.u16(0, 0x33 * 4 + 2)
    check('... the kernel, INT 24h, the mouse and INT 33h know where it went', k.pc.u16(0x60, k.Y['ui_seg']) == k.useg and seg == k.useg and
          mseg == k.useg and m33seg == k.useg, (hex(seg), hex(mseg), hex(m33seg)))
    dta = (k.pc.u16(0x60, k.Y['dta'] + 2), k.pc.u16(0x60, k.Y['dta']))
    check("... and the Executive's DTA is exec_dta in the new block (ui_room sets it there)", dta == (k.useg, k.Y['exec_dta']),
          (dta, (k.useg, k.Y['exec_dta'])))
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
    check('GRiD\'s font at the start (no LODE.INI)', core_font(k) == GRIDF)
    to_display(k)
    shot(k, 'system_display')
    check('Display: the font in use and the fonts on the disk', has(k, 'GRiD (built in)') and has(k, 'TERMINUS.FNT')
          and has(k, 'Fonts on the start-up disk:') and 'RETURN: the next font' in ' '.join(k.band()), (screen(k), k.band()))
    k.key(ktest.ENTER)
    shot(k, 'system_display_terminus')
    tF = term[(ord('F') - 32) * 16:(ord('F') - 31) * 16]
    check('Return: TERMINUS.FNT is the font, the screen redrawn in it ("Font" in Terminus)', core_font(k) == term
          and has(k, 'TERMINUS.FNT') and cell(k, 20, 32) == tF, (screen(k), cell(k, 20, 32).hex()))
    check('... and LODE.INI says so', disk_file(k, 'LODE.INI') == b'FONT=TERMINUS.FNT\r\n', disk_file(k, 'LODE.INI'))
    k.key(ktest.ESC)
    k = reboot(k, 'font2.img')
    check('after a restart: TERMINUS.FNT from LODE.INI', core_font(k) == term)
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
    check('Return again: GRiD\'s font, and LODE.INI goes (nothing else in it)', core_font(k) == GRIDF and disk_file(k, 'LODE.INI') is None,
          disk_file(k, 'LODE.INI'))
    # other lines in LODE.INI stay; any case; a missing or wrong-sized file
    ini = os.path.join(OUT, 'LODE.INI'); open(ini, 'wb').write(b'KEYS=1\r\nfont=terminus.fnt\r\nLAST=2')
    k = ktest.KPC(image('font3.img', SYSTEM, TERMFNT, ini)); k.pc.mouse = True; k.start()
    check('"font=terminus.fnt" among other lines: Terminus at the start', core_font(k) == term)
    to_display(k)
    k.key(ktest.ENTER)
    check('... Return: GRiD\'s again, the other lines kept', core_font(k) == GRIDF and disk_file(k, 'LODE.INI') == b'KEYS=1\r\nLAST=2\r\n',
          disk_file(k, 'LODE.INI'))
    k.key(ktest.ENTER)                  # (the font file is read where LODE.INI is: it must be in use before that)
    check('... Return: Terminus again, every glyph, with a LODE.INI to rewrite', core_font(k) == term
          and disk_file(k, 'LODE.INI') == b'KEYS=1\r\nLAST=2\r\nFONT=TERMINUS.FNT\r\n', disk_file(k, 'LODE.INI'))
    open(ini, 'wb').write(b'FONT=NOSUCH.FNT\r\n')
    bad = os.path.join(OUT, 'BAD.FNT'); open(bad, 'wb').write(term[:1000])
    k = ktest.KPC(image('font4.img', SYSTEM, bad, ini)); k.start()
    check('LODE.INI names a missing file: GRiD\'s font, no harm', core_font(k) == GRIDF and 'SYSTEM.RUN' in k.exec_list())
    to_display(k)
    k.key(ktest.ENTER)
    check('a .FNT of the wrong size is passed over (GRiD\'s stays)', core_font(k) == GRIDF and not k.crashed, screen(k))
    # the start-up's reads at their longest: they share the directory buffer with the start-up
    # code (section uiboot), which sits just past them.  4,095 bytes of LODE.INI with FONT= in
    # them, then a font file of FONT_BYTES (taken) or of one byte more (read, and passed over)
    for n in (1536, 1537):
        f = os.path.join(OUT, 'EDGE.FNT'); data = bytes((i * 7 + 1) & 0xFF for i in range(n)); open(f, 'wb').write(data)
        line = b'FONT=EDGE.FNT\r\n'
        open(ini, 'wb').write(line + b'X' * (4095 - len(line) - 2) + b'\r\n' + b'Y' * 500)
        k = ktest.KPC(image('font5.img', SYSTEM, f, ini)); k.start()
        check('a LODE.INI longer than the 4,095 bytes read, FONT= in them, a font file of %d bytes: %s; the Executive comes up'
              % (n, 'taken' if n == 1536 else 'GRiD\'s stays'), (core_font(k) == data if n == 1536 else core_font(k) == GRIDF)
              and not k.crashed and 'SYSTEM.RUN' in k.exec_list() and k.u16('convkb') > 0, (k.where(), k.exec_list(), k.u16('convkb')))

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
    print('== the screen saver\'s delay (System, Screen saver; LODE.INI SAVER=)')
    img = image('svd.img', SYSTEM, DEFRAG, TERMFNT)
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    check('5 minutes to start with', k.rd('saver_min', 1) == b'\x05' and k.u16('saver_t') == 5460, (k.rd('saver_min', 1), k.u16('saver_t')))
    k.key(CODE['U'])
    for _ in range(6): k.key(ktest.DOWN, settle=False)
    k.settle()
    check('System: the Screen saver topic says 5 minutes', has(k, 'Screen saver') and has(k, 'Starts after') and has(k, '5 minutes')
          and 'RETURN: the next delay' in ' '.join(k.band()), (screen(k), k.band()))
    k.key(ktest.ENTER)
    check('Return: 10 minutes, at once, and LODE.INI says SAVER=10', has(k, '10 minutes') and k.u16('saver_t') == 10920
          and disk_file(k, 'LODE.INI') == b'SAVER=10\r\n', (screen(k), disk_file(k, 'LODE.INI')))
    k.key(ktest.ENTER); k.key(ktest.ENTER)
    check('... 15, then 30 minutes', has(k, '30 minutes') and k.rd('saver_min', 1) == b'\x1e', screen(k))
    k.key(ktest.ENTER)
    check('... then never (SAVER=0)', has(k, 'never') and k.u16('saver_t') == 0xFFFF and disk_file(k, 'LODE.INI') == b'SAVER=0\r\n',
          (screen(k), disk_file(k, 'LODE.INI')))
    k.key(ktest.ESC)
    check('never: idle 30 minutes in the Executive, no saver', not idle(k, 30000) and not k.crashed, lines(k)[:2])
    k.key(CODE['U'])
    for _ in range(6): k.key(ktest.DOWN, settle=False)
    k.settle()
    k.key(ktest.ENTER)
    check('... then 1 minute', has(k, '1 minute') and disk_file(k, 'LODE.INI') == b'SAVER=1\r\n', screen(k))
    k.key(ktest.ESC)
    check('1 minute: not after 50 s', not idle(k, 910), lines(k)[:2])
    check('... but after a minute (DEFRAG\'s map)', idle(k, 1092 + 18), lines(k)[:2])
    k.key(ktest.ESC); k.settle(8)
    # the font and the saver together in LODE.INI, other lines kept
    k = reboot(k, 'svd2.img')
    check('after a restart: 1 minute from LODE.INI', k.rd('saver_min', 1) == b'\x01', k.rd('saver_min', 1))
    to_display(k); k.key(ktest.ENTER); k.key(ktest.ESC)
    check('a font too: FONT= and SAVER= both in LODE.INI', disk_file(k, 'LODE.INI') == b'FONT=TERMINUS.FNT\r\nSAVER=1\r\n', disk_file(k, 'LODE.INI'))
    ini = os.path.join(OUT, 'LODE.INI'); open(ini, 'wb').write(b'KEYS=1\r\nsaver=2\r\nFONT=TERMINUS.FNT\r\n')
    k = ktest.KPC(image('svd3.img', SYSTEM, TERMFNT, ini)); k.start()
    check('"saver=2" (any case) before FONT=: both taken at start-up', k.rd('saver_min', 1) == b'\x02' and core_font(k) == open(TERMFNT, 'rb').read(),
          k.rd('saver_min', 1))
    k.key(CODE['U'])
    for _ in range(6): k.key(ktest.DOWN, settle=False)
    k.settle()
    k.key(ktest.ENTER)
    check('Return: 5 minutes again, its SAVER= line gone, the others kept', disk_file(k, 'LODE.INI') == b'KEYS=1\r\nFONT=TERMINUS.FNT\r\n',
          disk_file(k, 'LODE.INI'))
    ini2 = os.path.join(OUT, 'LODE2.INI'); open(ini2, 'wb').write(b'SAVER=99\r\n')
    k = ktest.KPC(image('svd4.img', 'LODE.INI=' + ini2)); k.start()
    check('SAVER=99: 30 minutes at most', k.rd('saver_min', 1) == b'\x1e' and k.u16('saver_t') == 32760, k.rd('saver_min', 1))
    # past 511 bytes of other lines (System keeps a LODE.INI up to 1 KB and
    # puts its own lines last): font_boot read only the first 511
    ini = os.path.join(OUT, 'LODE.INI'); open(ini, 'wb').write(b'X1=1\r\n' * 160 + b'saver=2\r\nFONT=TERMINUS.FNT\r\nTIDY=0\r\n')
    k = ktest.KPC(image('svd5.img', SYSTEM, TERMFNT, ini)); k.start()
    check('SAVER=, FONT= and TIDY=0 after 960 bytes of other lines: all three taken at start-up (%d bytes)' % os.path.getsize(ini),
          k.rd('saver_min', 1) == b'\x02' and core_font(k) == open(TERMFNT, 'rb').read() and k.rd('sv_notidy', 1) == b'\x01',
          (k.rd('saver_min', 1), k.rd('sv_notidy', 1)))


def t_ini_keys():
    """System's save_ini drops each of its keys' old lines (any case) and
    keeps the others; SPLASH= and MULTITASK= read back first (ini_find)"""
    print('== LODE.INI rewritten by System: every key of its own replaced, the other lines kept')
    ini = os.path.join(OUT, 'LODE.INI')
    open(ini, 'wb').write(b'KEYS=1\r\nfont=TERMINUS.FNT\r\nSaver=2\r\ntidy=0\r\nsplash=0\r\nprinter=\r\nmultitask=on\r\n'
                          b'mdisk=512\r\nLAST=2')
    k = ktest.KPC(image('inik.img', SYSTEM, TERMFNT, ini)); k.start()
    k.key(CODE['U'])
    for _ in range(6): k.key(ktest.DOWN, settle=False)
    k.settle()
    k.key(ktest.ENTER)
    got = disk_file(k, 'LODE.INI')
    check('Return (the saver\'s delay, 2 -> 5 minutes: no SAVER= line): FONT=, SAVER=, TIDY=, SPLASH=, PRINTER= and MULTITASK= '
          'lines replaced, MDISK= (no EMS) and the others kept, the last given a line end',
          got == b'KEYS=1\r\nmdisk=512\r\nLAST=2\r\nFONT=TERMINUS.FNT\r\nTIDY=0\r\nSPLASH=0\r\nMULTITASK=1\r\n', got)


def t_saver_tidy():
    print('== the saver tidies the disks, or not (System, Screen saver, Space; LODE.INI TIDY=0)')
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
    check('Space: "no" at once, LODE.INI says TIDY=0', tidy().rstrip().endswith('no') and k.rd('sv_notidy', 1) == b'\x01'
          and disk_file(k, 'LODE.INI') == b'TIDY=0\r\n', (tidy(), disk_file(k, 'LODE.INI')))
    k.key(ktest.ENTER)
    check('... with a delay too: SAVER=10 and TIDY=0', disk_file(k, 'LODE.INI') == b'SAVER=10\r\nTIDY=0\r\n', disk_file(k, 'LODE.INI'))
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
          and disk_file(k, 'LODE.INI') == b'SAVER=10\r\n', (tidy(), disk_file(k, 'LODE.INI')))
    k.key(ktest.ESC)
    check('... and the saver runs DEFRAG again', idle(k, 10 * 1092 + 18), lines(k)[:2])


def t_prtsc_setting():
    print('== PrtSc prints with a driver, or saves files (System, Devices, Return; LODE.INI PRINTER=); Shift-PrtSc a file')
    import shutil
    ps = os.path.join(GOS, 'drivers', 'PS.PRN')
    other = os.path.join(OUT, 'EPSON.PRN'); shutil.copy(ps, other)
    job = os.path.join(OUT, 'JOB.PRN'); open(job, 'wb').write(b'\x1bEa print job saved as .PRN\r\n\x0c')
    img = image('prs.img', SYSTEM, ps, other, job)
    k = ktest.KPC(img); k.start()
    def topic(k):
        k.key(CODE['U'])
        for _ in range(3): k.key(ktest.DOWN, settle=False)
        k.settle()
    topic(k)
    line = lambda: next((l for l in lines(k) if ' PrtSc ' in l), '')
    path = lambda: k.rd('prn_path', 24).split(b'\0')[0]
    check('Devices: "PrtSc  saves SCREENnn.BMP / .TXT"; RETURN in the band', 'saves SCREENnn' in line() and path() == b''
          and 'RETURN: the next printer driver' in ' '.join(k.band()), (line(), k.band()))
    seen = []
    for _ in range(3):
        k.key(ktest.ENTER)
        seen.append((line().split('  ')[-1].strip(), path(), disk_file(k, 'LODE.INI')))
    names = [p for _, p, _ in seen]
    check('Return: each driver on the disk in turn (not JOB.PRN, a print job), then files again; the kernel told the full path',
          sorted(names[:2]) == [b'A:\\EPSON.PRN', b'A:\\PS.PRN'] and names[2] == b'' and
          all(('prints with ' + n.decode()[3:]) in t for t, n, _ in seen[:2]) and 'saves SCREENnn' in seen[2][0], seen)
    check('... LODE.INI says PRINTER=NAME, and nothing when files', seen[0][2] == b'PRINTER=' + names[0][3:] + b'\r\n'
          and seen[2][2] is None, [x[2] for x in seen])
    k.key(ktest.ENTER)                                   # the first one again, kept
    k.key(ktest.ESC); k.settle()
    k = reboot(k, 'prs2.img')
    check('after a restart: the same driver (PRINTER= taken, found along PATH)', path() == names[0], (path(), names[0]))


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
    sv = tty_line(k, 'saved')
    check('15h-17h: the state saved (a size that fits), the pointer moved, restored: back at (100, 50)',
          sv and 0 < int(sv[0], 16) <= 256 and sv[2:] == ['0064', '0032'], sv)
    check('1Ah sets the sensitivities, 1Bh gives them back (BX, CX, DX)', tty_line(k, 'sens')[1:] == ['0011', '0022', '0033'],
          tty_line(k, 'sens'))
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
    pre, i33 = [], k.Y['int33_ui']      # tmp, below m33_st, as the first INT 33h (DF set) finds it: nothing
    def first33(pc):                    #  else draws meanwhile, so a string write gone backwards shows there
        if not pre and pc.r('ip') == i33 and pc.r('cs') == k.useg: pre.append(k.rd('tmp', 96))
    k.hooks.append(first33)
    start_dos(k, 'M33GFX.COM')
    k.hooks.remove(first33)
    below = k.rd('tmp', 96)             # (after the reset and the shape, both with DF set)
    for x, y, hx, hy, H, banks, two, what in ((0, 0, 5, 7, 400, 4, 0, 'mode 40h, top left, hot spot (5, 7)'),
                                              (639, 399, 5, 7, 400, 4, 0, 'mode 40h, bottom right'),
                                              (333, 201, 5, 7, 400, 4, 0, 'mode 40h, an odd column'),
                                              (630, 190, 0, 0, 200, 2, 0, 'mode 6, clipped right and below'),
                                              (101, 50, 5, 7, 200, 2, 1, 'mode 4, hot spot in virtual pixels')):
        e, a = arrow_bits(x, y, hx, hy, H, two), screen_bits(k, H, banks)
        check('pointer: ' + what, e == a and e, (len(e), len(a), sorted(e - a)[:4], sorted(a - e)[:4]))
        k.key(ktest.ENTER, settle=False); k.pc.run_for(0.05)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 10); k.settle()
    check('DF set by the program: the reset and the shape still land where they should', pre and any(pre[0]) and below == pre[0] and
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
    k = ktest.KPC(image('m33s.img', LCMD, M33['M33HSET'], M33['M33HVIC'])); k.pc.mouse = True; k.start()
    start_dos(k, 'LCMD.COM')
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
    check('the titles only (subjects are their own item); Title outlined', k.exec_list() == ['LODE.SYS', 'SYSTEM.RUN', 'TERMINUS.FNT', 'WRITE.RUN']
          and focus(k) == 0 and outlined(k, 2) and not outlined(k, 0), k.exec_list())
    check('the form: Device Floppy A:, Subject Root, the title and its kind', form(k)[:3] == ['Floppy A:', 'Root', 'LODE'] and form(k)[3].startswith('System'), form(k))
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
    check('... and LODE.INI goes to A:, not B:', disk_file(k, 'LODE.INI') == b'FONT=TERMINUS.FNT\r\n' and
          fatcheck.read_files(bytes(k.pc.drives[1].img)).get('A:\\LODE.INI') is None, disk_file(k, 'LODE.INI'))
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
    check('help: Tab for the items; Copy, Erase, Move, Rename', 'Device, Subject, Title' in hl and 'CODE-C                   Copy (a file or subject)' in hl
          and 'CODE-R                   Rename (a file)' in hl and 'CODE-D                   Delete (a file or subject)' in hl
          and 'CODE-M                   Move (a file)' in hl and 'the file' not in hl
          and 'CODE-W                   Write (a new file)' in hl and 'F5                       read the disk again' in hl and 'CODE-M' in hl
          and 'CODE-P                   Command prompt' in hl and 'CODE is the Alt key' in hl, hl)
    k.key(ktest.ENTER)
    k.key(CODE['R']); k.key(ktest.ESC); k.key(CODE['C']); k.key(ktest.ESC)
    check('CODE-R, CODE-D open their forms; ESC changes nothing', not k.crashed and k.exec_list() == ['INNER.TXT'] and k.pc.mode() == 0x40, k.where())
    # B: with no disk (taken out: the change line says so, so B: is mounted again: INT 24h, the UI's says why)
    k.pc.drives[1].empty = True; k.pc.drives[1].changed = True
    k.key(ktest.TAB); k.key(ktest.DOWN); k.key(ktest.ENTER, settle=False); k.settle(20)
    check('B: with no disk: Subject has Root only and the band says why ("Drive not ready", not "error 0")',
          subjects(k) == ['Root'] and k.band()[:1] == ["Can't read the disk: Drive not ready (no disk?)"]
          and not k.crashed, (subjects(k), k.band()))
    k.key(ktest.ENTER)
    k.key(K_BTAB); k.key(ktest.UP); k.key(ktest.ESC)
    # a disk that isn't a DOS disk (blank): said as such, not "Path not found"
    saved = k.pc.drives[1].img
    k.pc.drives[1].img = bytearray(len(saved)); k.pc.drives[1].empty = False; k.pc.drives[1].changed = True
    k.key(ktest.TAB); k.key(ktest.DOWN); k.key(ktest.ENTER, settle=False); k.settle(20)
    check('B: with a blank disk: "Can\'t read the disk: Not a DOS disk"', k.band()[:1] == ["Can't read the disk: Not a DOS disk"]
          and not k.crashed, (subjects(k), k.band()))
    k.key(ktest.ENTER)
    k.key(K_BTAB); k.key(ktest.UP); k.key(ktest.ESC)
    k.pc.drives[1].img = saved; k.pc.drives[1].empty = True; k.pc.drives[1].changed = True
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
    k.key(CODE['R']); k.key('lode.sys', ktest.ENTER)
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
    check('... Return: erased, the next one chosen', 'A:\\HUGE.DAT' not in A() and k.exec_list() == ['KEEP.TXT', 'LODE.SYS']
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
          and [n for n in A() if n.endswith('.TXT')] == ['A:\\RO.TXT'] and k.exec_list() == ['LODE.SYS', 'RO.TXT'] and not sound(0), (k.band(), sorted(A())))
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
    # a damaged subject inside the one erased: its directory without even "." (FIND FIRST: 18, X22): a damaged
    # disk, 3, as one whose first entry isn't "."; it and the subject above it are left
    a = image('subdel2.img', t, 'OLD\\', 'OLD\\BROKEN\\', 'KEEP\\', 'KEEP\\K.TXT=' + t)
    raw = bytearray(open(a, 'rb').read())
    o = [o for o in range(0, len(raw), 32) if raw[o:o + 11] == b'BROKEN     ' and raw[o + 11] & 0x10][0]
    clus = raw[o + 26] | raw[o + 27] << 8
    dots = [d for d in range(0, len(raw), 32) if raw[d:d + 11] == b'.          ' and raw[d + 26] | raw[d + 27] << 8 == clus]
    raw[dots[0]:dots[0] + 64] = bytes(64)                               # (no ".", no "..": the directory ends at once)
    open(a, 'wb').write(raw)
    k = ktest.KPC(a); k.start()
    pick_subject(k, 'OLD'); k.key(CODE['D']); k.key(ktest.ENTER)
    check('a subject with no entries at all (not even ".") in the one erased: "Path not found", as a damaged disk; both stay',
          k.band()[0].endswith(': Path not found') and 'OLD' in [x.strip() for x in subjects(k)] and not k.crashed,
          (k.band(), subjects(k)))

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
    k.pc.drives[1].empty = True; k.pc.drives[1].changed = True     # (taken out: B: is mounted again, INT 24h)
    k.key(CODE['C']); k.key(ktest.RIGHT, ktest.ENTER, '\\x2', K_CODE_ENTER, settle=False); k.settle(60)
    check('... to B: with no disk in it: "Can\'t copy X2: Drive not ready (no disk?)" (not "Copied 0 titles", nor '
          '"B:\\X2 isn\'t there: Confirm to make it")', band() == "Can't copy X2: Drive not ready (no disk?)" and not k.crashed, k.band())
    k.pc.drives[1].empty = False; k.pc.drives[1].changed = True
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
    check('help: "CODE-C  Copy (a file or subject)"', has(k, 'CODE-C                   Copy (a file or subject)'), screen(k))
    k.key(ktest.ENTER)
    k.key(CODE['M'])
    check('CODE-M on a subject: nothing (a beep)', focus(k) == 2 and band() == 'Subject: Select item and confirm' and not k.crashed, k.band())

INFO_Y = 336
def vram(k): return k.pc.rd(0xB800, 0, 0x8000)
def vrow(buf, y): b = (y & 3) * 0x2000 + (y >> 2) * 80; return buf[b:b + 80]
def lit_cells(k, y, cols=range(80)):
    """Columns whose 16 rows from y are all set: a lit (inverse) space."""
    buf = vram(k)
    return [c for c in cols if all(vrow(buf, y + r)[c] == 0xFF for r in range(16))]
def below_title(k):
    buf = vram(k)
    return b''.join(vrow(buf, y) for y in range(20, 400))
def watch_info(k):
    """The information line each time draw_all hands it to center: it is
    built in tmp just before (infobuf), which other drawing reuses."""
    got, a = [], k.Y['center']
    def h(pc):
        if pc.r('ip') == a and pc.r('dx') == INFO_Y and pc.r('cs') == k.useg:
            got.append(pc.rd(pc.r('cs'), pc.r('si'), 128).split(b'\0')[0].decode())
    k.hooks.append(h)
    return got

def t_calc():
    """The calculator (0.4.4): the coprocessor lamp in the info line, System's
    Devices, and CALC.RUN, the window over the Executive (CODE-K)."""
    print('== the calculator, and the coprocessor lamp')
    hdr = open(CALCRUN, 'rb').read(6)
    check('CALC.RUN needs API 6 (its window moves and closes; API 5: the caller\'s redraw stays, exit code 0FFFFh)', hdr == b'GRUN\x06\x00', hdr)
    hdrs = [open(f, 'rb').read(6) for f in (SYSTEM, WRITE, UITEST)]
    check('SYSTEM and UITEST declare RUN_API 4 (a floppy with an older LODE.SYS still runs them); WRITE 8 (its drags and menu)',
          hdrs == [b'GRUN\x04\x00', b'GRUN\x08\x00', b'GRUN\x04\x00'], hdrs)
    # the lamp: pcemu's coprocessor is 387-class, so a 287XL
    k = ktest.KPC(image('lamp.img', SYSTEM)); infos = watch_info(k); k.start()
    info = infos[-1] if infos else ''
    c0 = (90 - len(info)) // 2
    check('the info line: "80286 80287XL ..." (probed, not taken from the CMOS bit)', info.startswith('80286 80287XL   640K'), info)
    check('... " 80287XL " lit (inverse), nothing else', lit_cells(k, INFO_Y) == [c0, c0 + 8], (c0, lit_cells(k, INFO_Y)))
    k.key(CODE['U']); k.key('D'); k.key('D')
    check('System, Devices: Coprocessor 80287XL', re.search(r'Coprocessor\s+80287XL', screen(k)), screen(k))
    k.key(ktest.ESC)
    check('... and the lamp is lit again after System', lit_cells(k, INFO_Y) == [c0, c0 + 8], lit_cells(k, INFO_Y))
    k = ktest.KPC(image('nolamp.img', SYSTEM))
    k.pc.wr(0, 0x410, struct.pack('<H', k.pc.u16(0, 0x410) & ~2))     # INT 11h: none
    infos = watch_info(k); k.start()
    info = infos[-1] if infos else ''
    check('no coprocessor: "80286   640K ...", nothing lit', info.startswith('80286   640K') and not lit_cells(k, INFO_Y), (info, lit_cells(k, INFO_Y)))
    k.key(CODE['U']); k.key('D'); k.key('D')
    check('... System, Devices: Coprocessor none', re.search(r'Coprocessor\s+none', screen(k)), screen(k))
    k.key(ktest.ESC)
    # the window: keys, then the screen exactly as it was (no mouse: no pointer)
    img = image('calc.img', CALCRUN, os.path.join(GOS, 'src', 'LCMD.COM'))
    k = ktest.KPC(img); k.start()
    free0, ui0 = free_paras(k)
    scr0 = below_title(k)
    k.key(CODE['K'])
    check('CODE-K opens the calculator over the Executive', has(k, 'Calculator') and has(k, 'LCMD'), screen(k))
    def ans(): return [l.strip() for l in lines(k) if l.strip().startswith('=') or 'Divide' in l]
    k.key('2+2'); k.key(ktest.ENTER)
    check('2+2, Return: = 4', ans() == ['= 4'], ans())
    k.key('*10'); k.key(ktest.ENTER)
    check('*10: goes on from the answer, = 40', ans() == ['= 40'], ans())
    k.key('+1'); k.key(ktest.ENTER)
    check('+1: goes on from the answer too, = 41', ans() == ['= 41'], ans())
    k.key('3'); k.key(ktest.ENTER)
    check('typing after an answer starts afresh: = 3', ans() == ['= 3'], ans())
    k.key('12*3', ktest.UP, '4', ktest.ENTER)
    check("a key that ends the line editor (Up) doesn't wipe the line: 12*34 = 408", ans() == ['= 408'], ans())
    k.key('sin(30', 0x3C00, ')', ktest.ENTER)
    check('... nor F2 in the middle of a sum: sin(30) in degrees = 0.5', ans() == ['= 0.5'], ans())
    k.key(0x3C00)
    k.key(ktest.ESC)
    check('ESC: exit code 0FFFFh, the .RUN gone, the UI block as before', run_ret(k) == 0xFFFF and k.rd('run_active', 1) == b'\x00'
          and free_paras(k) == (free0, ui0), (hex(run_ret(k)), free_paras(k), (free0, ui0)))
    check('... and the screen is exactly as it was (the save-under; no re-read, no redraw)', below_title(k) == scr0)
    # the keys with the mouse
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    k.key(CODE['K'])
    def key_xy(r, c): return (42 + 6 * c + 3) * 8, 108 + 24 * r + 12
    for r, c in ((0, 0), (1, 3), (1, 2), (4, 3)):
        click(k, *key_xy(r, c))
    check('clicks on 7 * 6 =: = 42', ans() == ['= 42'] and has(k, '7*6'), screen(k))
    click(k, *key_xy(0, 1))
    k.key('+1')
    check('a key clicked after an answer starts afresh, typing after a click goes on: 8+1', has(k, '8+1') and not has(k, '7*68'), screen(k))
    k.key(ktest.ENTER)
    check('... = 9', ans() == ['= 9'], ans())
    # keys typed while a click is handled (put in the BIOS's buffer as keep_line starts): after the End
    # that keeps the line, in order -- 7 then *3, = 21, not *3 from the answer (27)
    sy = run_syms('apps/CALC.ASM')
    fired, watch = [], k.pc.watch
    at = k.useg * 16 + k.u16('run_base') + sy['keep_line']
    def ahead(addr):
        if addr == at and not fired: fired.append(1); k.pc.keys.extend(ord(c) for c in '*3')
        if watch: watch(addr)
    k.pc.watch = ahead
    click(k, *key_xy(0, 0))
    k.pc.watch = watch
    k.key(ktest.ENTER)
    check('keys typed while a click is handled go after it, in order: 7, *3 typed meanwhile, = 21',
          fired and ans() == ['= 21'] and has(k, '7*3'), (fired, ans(), screen(k)))
    for r, c in ((2, 4), (0, 0), (0, 5)):
        click(k, *key_xy(r, c))
    check('sin puts "sin(" in the line', has(k, 'sin(7)'), screen(k))
    click(k, *key_xy(4, 0))
    check('C clears it', not has(k, 'sin(7)'), screen(k))
    deg = 42 + 6 * 5 + 1
    k.key(0x3C00)
    check('F2: degrees, the Deg key lit', lit_cells(k, 108 + 24 * 5 + 4, range(deg, deg + 5)) == [deg, deg + 4], screen(k))   # (the spaces around "Deg")
    k.key('sin(90)'); k.key(ktest.ENTER)
    check('... sin(90) = 1', ans() == ['= 1'], ans())
    click(k, *key_xy(5, 5))
    k.key('sin(pi/2)'); k.key(ktest.ENTER)
    check('the Deg key: radians again, sin(pi/2) = 1, the key not lit',
          ans() == ['= 1'] and not lit_cells(k, 108 + 24 * 5 + 4, range(deg, deg + 5)), ans())
    k.key(ktest.F1)
    check('F1: its help', has(k, 'Calculator Help') and has(k, 'degrees / radians'), screen(k))
    k.key(ktest.ESC)
    k.key('1/0'); k.key(ktest.ENTER)
    check('1/0: Divide by zero', ans() == ['Divide by zero'], ans())
    # the saver while it is open: the Executive and the window come back
    k.wr('saver_t', struct.pack('<H', 36))
    for _ in range(40):
        k.pc.run_for(0.25)
        if not has(k, 'Calculator'): break
    dark = not has(k, 'Calculator')
    k.wr('saver_t', struct.pack('<H', 5460))
    k.key(ktest.DOWN)
    check('the saver with the window open, then a key: the Executive and the window back',
          dark and has(k, 'Calculator') and has(k, 'LCMD') and has(k, '1/0') and has(k, 'Select a file and confirm'), screen(k))
    k.key(CODE['K'])
    check('CODE-K again closes it; after the saver, exit code 0: the Executive reads its directory again and redraws',
          not has(k, 'Calculator') and run_ret(k) == 0 and has(k, 'LCMD'), (run_ret(k), screen(k)))
    # 255 repaints so far (paints poked), then the saver twice: a byte count would wrap to 1 and say
    # "as it was" over an old save-under; it stays "repainted", exit code 0 (the persona review)
    def saver_once():
        k.wr('saver_t', struct.pack('<H', 36))
        for _ in range(40):
            k.pc.run_for(0.25)
            if not has(k, 'Calculator'): break
        dark = not has(k, 'Calculator')
        k.wr('saver_t', struct.pack('<H', 5460))
        k.key(ktest.DOWN)
        return dark and has(k, 'Calculator')
    k.key(CODE['K'])
    k.pc.wr(k.useg, k.u16('run_base') + sy['paints'], b'\xff')
    twice = saver_once() and saver_once()
    k.key(CODE['K'])
    check('... after 257 repaints too: exit code 0, the Executive redraws', twice and run_ret(k) == 0 and not has(k, 'Calculator'),
          (twice, hex(run_ret(k))))
    # CALC.RUN's whole numbers are the core's UI_SBU32 (CALC.COM keeps its own)
    k = ktest.KPC(img); k.start()
    k.key(CODE['K']); k.key('2^70'); k.key(ktest.ENTER)
    check('2^70 = 1.18059162071741E+21 (the exponent in whole numbers)', ans() == ['= 1.18059162071741E+21'], ans())
    k.key(ktest.ESC)
    k.pc.wr(0, 0x410, struct.pack('<H', k.pc.u16(0, 0x410) & ~2))     # INT 11h: no coprocessor
    k.key(CODE['K']); got = []
    for e in ('2^30', '-2147483647-1', '7*-3'):
        k.key(e); k.key(ktest.ENTER); got += ans()
    check('no coprocessor: whole numbers, 2^30, -2147483647-1, 7*-3', got == ['= 1073741824', '= -2147483648', '= -21'], got)
    k.key(ktest.ESC)
    k = ktest.KPC(image('nocalc.img', SYSTEM)); k.start()
    k.key(CODE['K'])
    check('no CALC.RUN: the band says so', any('CALC.RUN is not on this disk' in l for l in k.band()), k.band())
    k.key(ktest.ENTER)
    k.key(ktest.F1)
    check('the Executive\'s help lists CODE-K', has(k, 'CODE-K') and has(k, 'Calculator'), screen(k))
    k.key(ktest.ESC)

def point(k, x, y):
    """Move the pointer to (x, y), no button."""
    dx, dy = x - k.u16('mx'), y - k.u16('my')
    while dx or dy:
        sx, sy = max(-100, min(100, dx)), max(-100, min(100, dy))
        k.pc.mouse_move(sx & 0xFF, sy & 0xFF); k.pc.run_for(0.05)
        dx -= sx; dy -= sy
    k.settle()

def drag(k, x0, y0, x1, y1):
    """Press the left button at (x0, y0), move to (x1, y1) holding it, release."""
    point(k, x0, y0)
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05)
    dx, dy = x1 - x0, y1 - y0
    while dx or dy:
        sx, sy = max(-40, min(40, dx)), max(-40, min(40, dy))
        k.pc.mouse_move(sx & 0xFF, sy & 0xFF, 1); k.pc.run_for(0.05)
        dx -= sx; dy -= sy
    k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05); k.settle()

def t_calc_move():
    """The calculator's window moves (API 6): its title strip dragged with the
    mouse, CODE-F7 and the arrow keys; its close box closes it."""
    print('== the calculator\'s window moves and closes (API 6)')
    img = image('calcmv.img', CALCRUN, os.path.join(GOS, 'src', 'LCMD.COM'))
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    sy = run_syms('apps/CALC.ASM')
    def win():
        a = k.u16('run_base') + sy['win']
        return k.pc.u16(k.useg, a), k.pc.u16(k.useg, a + 2)
    def title_at():
        """(column, y) where "Calculator" is drawn (the pointer put back where it
        starts, out of the way)."""
        point(k, 320, 200)
        for y, l in k.ocr():
            if 'Calculator' in l: return l.index('Calculator'), y
    def ans(): return [l.strip() for l in lines(k) if l.strip().startswith('=')]
    def parked():
        """The screen under the title, the pointer back where it was at the start."""
        point(k, 320, 200); return below_title(k)
    scr0 = below_title(k)
    k.key(CODE['K'])
    check('it opens where it always did: column 41, row 28, the title at column 43',
          win() == (41, 28) and title_at() == (43, 32), (win(), title_at()))
    check('a close box, a dark cell, at the title strip\'s right end (column 77)',
          77 not in lit_cells(k, 32, range(70, 79)) and 76 in lit_cells(k, 32, range(70, 79)), lit_cells(k, 32, range(70, 79)))
    # the close box
    click(k, 77 * 8 + 4, 36)
    check('a click on the close box closes it: exit code 0FFFFh, the screen exactly as before',
          not has(k, 'Calculator') and run_ret(k) == 0xFFFF and parked() == scr0, (hex(run_ret(k)), screen(k)))
    # dragged by its title
    k.key(CODE['K'])
    k.key('12')
    drag(k, 50 * 8 + 3, 36, 30 * 8 + 3, 76)
    check('dragged by its title 20 columns left, 40 rows down: there now, drawn there',
          win() == (21, 68) and title_at() == (23, 72), (win(), title_at(), screen(k)))
    k.key('3'); k.key(ktest.ENTER)
    check('the line editor moved with it and goes on where it was: 123', ans() == ['= 123'], (ans(), screen(k)))
    ky = 68 + 80
    def key_xy(r, c): return (22 + 6 * c + 3) * 8, ky + 24 * r + 12
    for r, c in ((0, 0), (1, 3), (1, 2), (4, 3)):
        click(k, *key_xy(r, c))
    check('its keys work where it is now: 7 * 6 = 42', ans() == ['= 42'], (ans(), screen(k)))
    # the keyboard: CODE-F7, arrows, Return; ESC leaves it
    k.key(0x6E00, ktest.LEFT, ktest.LEFT, ktest.LEFT, ktest.DOWN, ktest.DOWN, ktest.ENTER)
    check('CODE-F7, Left x3, Down x2, Return: 3 columns left, 8 rows down', win() == (18, 76) and title_at() == (20, 80),
          (win(), title_at()))
    k.key(0x6E00, ktest.RIGHT, ktest.UP, ktest.ESC)
    check('... CODE-F7, moved, then ESC: where it was', win() == (18, 76) and title_at() == (20, 80), (win(), title_at()))
    check('... and the calculator still has the answer, and keeps going', has(k, '= 42'), screen(k))
    # kept on the screen
    drag(k, 25 * 8, 80, 0, 0)
    check('dragged past the top left corner: column 0, just under the title rule (24)', win() == (0, 24), win())
    drag(k, 4 * 8, 28, 639, 399)
    check('past the bottom right: column 42 (80 - 38), its bottom on the band (360 - 228 = 132)', win() == (42, 132), win())
    # the saver: the Executive and the window come back, where it was moved to
    k.wr('saver_t', struct.pack('<H', 36))
    for _ in range(40):
        k.pc.run_for(0.25)
        if not has(k, 'Calculator'): break
    dark = not has(k, 'Calculator')
    k.wr('saver_t', struct.pack('<H', 5460))
    k.key(ktest.DOWN)
    check('after the saver it is back where it was moved to', dark and title_at() == (44, 136), (dark, title_at()))
    k.key(ktest.ESC)
    check('ESC closes it; after the saver, exit code 0: the Executive redraws', not has(k, 'Calculator') and run_ret(k) == 0
          and has(k, 'LCMD'), hex(run_ret(k)))
    # moved, then closed: the save-under taken at the move puts the screen back
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    scr0 = below_title(k)
    k.key(CODE['K'])
    drag(k, 50 * 8 + 3, 36, 10 * 8 + 3, 100)
    k.key(0x6E00, ktest.RIGHT, ktest.ENTER)
    k.key(ktest.ESC)
    check('moved twice, then closed: exit code 0FFFFh and the screen exactly as before (no redraw needed)',
          run_ret(k) == 0xFFFF and parked() == scr0, hex(run_ret(k)))
    # a click on the title strip that doesn't move it: nothing happens
    k.key(CODE['K'])
    click(k, 50 * 8, 36)
    check('a click on the title (no move): still open, still there', win() == (41, 28) and title_at() == (43, 32), (win(), title_at()))
    k.key(ktest.ESC)
    # no save-under (the disk cache's memory already lent out): a move draws
    # everything again, the Executive and the window at its new place
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    scr0 = parked()
    k.wr('tc_lock', b'\x01')
    k.key(CODE['K'])
    unsaved = k.u16('wseg') == 0
    drag(k, 50 * 8 + 3, 36, 30 * 8 + 3, 76)
    check('no save-under: dragged, it is drawn at its new place, the Executive under its old one',
          unsaved and win() == (21, 68) and title_at() == (23, 72) and has(k, 'LCMD'), (unsaved, win(), title_at()))
    k.key('2+3'); k.key(ktest.ENTER)
    check('... and it works there: 2+3 = 5', ans() == ['= 5'], ans())
    k.key(ktest.ESC)
    k.wr('tc_lock', b'\x00')
    check('... closed: the screen exactly as before', not has(k, 'Calculator') and parked() == scr0, screen(k))

# ---------------------------------------------------------------------
def md_pages(k):
    """M:'s pages (0: off), from the installer's own data in the disk cache's EMS page."""
    tp = k.rd('ems_tcpg', 2)[1] & 0x7F
    return k.pc.ems_read(tp, k.Y['md_pg'], 1)[0]

def md_files(k):
    """M:'s files from its EMS pages: {'M:\\NAME': bytes}."""
    tp = k.rd('ems_tcpg', 2)[1] & 0x7F
    h = struct.unpack('<H', k.pc.ems_read(tp, k.Y['md_h'], 2))[0]
    st, n = k.rd('ems_h', 2, 4 * h)
    ltab = k.rd('ems_ltab', 128)
    img = b''.join(k.pc.ems_read(ltab[st + i] & 0x7F, 0, 0x4000) for i in range(n))
    return fatcheck.read_files(img, 'M') if n else {}

def t_mdisk():
    print('== M:, the temporary disk (System, Temporary disk; LODE.INI MDISK=; the Executive)')
    # without EMS: the topic says so, nothing to choose
    img = image('mdu0.img', SYSTEM, MEMSZ)
    k = ktest.KPC(img); k.start()
    k.key(CODE['U']); k.key('T')
    shot(k, 'system_mdisk_noems')
    check('no EMS: Temporary disk says "needs EMS"; Return does nothing', has(k, 'needs EMS') and has(k, 'no expanded memory'),
          screen(k))
    k.key(ktest.ENTER)
    check('... (LODE.INI not written)', disk_file(k, 'LODE.INI') is None and not k.crashed, disk_file(k, 'LODE.INI'))
    k.key(ktest.DOWN, ktest.UP); k.key('D')
    check('... Disks: A: only', has(k, 'Drive A:') and not has(k, 'Drive M:') and not has(k, 'Drive C:'), screen(k))
    k.key(ktest.ESC)
    k.key(ktest.TAB)
    check('... the Executive\'s Device list: A: only', k.u16('nent') == 1 and focus(k) == 1, k.u16('nent'))
    k.key(ktest.TAB); k.key(ktest.TAB)
    # with EMS: 256 KB
    notes = os.path.join(OUT, 'NOTES.TXT'); open(notes, 'wb').write(TEXT)
    img = image('mdu.img', SYSTEM, MEMSZ, MDTEST, LCMD, DEFRAG, notes, 'WORK\\')
    k = ktest.KPC(img, ems_pages=88); k.pc.mouse = True; k.start()
    k.key(CODE['U'])
    m = re.search(r'Temporary disk M:\s+([\d.]+) KB', screen(k))
    check('System, Memory: "Temporary disk M:  0.3 KB" (its block: from the environment\'s spare bytes)', m and m.group(1) == '0.3',
          screen(k))
    k.key(ktest.DOWN)
    check('Disks: A: and M: (256 KB)', has(k, 'Drive A:') and has(k, 'Drive M:') and has(k, '251 KB'), screen(k))
    k.key('T')
    shot(k, 'system_mdisk')
    check('Temporary disk: "Size 256 KB", free, all EMS free would give 1376 KB; the choices', re.search(r'Size\s+256 KB', screen(k))
          and re.search(r'Free\s+251 KB', screen(k)) and re.search(r'All free EMS would give\s+1376 KB', screen(k))
          and has(k, 'RETURN: off, 64, 128, 256, 512 KB, 1 MB, all free') and 'RETURN: the next size' in ' '.join(k.band()),
          (screen(k), k.band()))
    steps = [('512 KB', 32, b'MDISK=512\r\n'), ('1 MB', 64, b'MDISK=1024\r\n'), ('1376 KB', 86, b'MDISK=ALL\r\n'),
             ('off', 0, b'MDISK=0\r\n'), ('64 KB', 4, b'MDISK=64\r\n'), ('128 KB', 8, b'MDISK=128\r\n'), ('256 KB', 16, None)]
    for txt, pg, ini in steps:
        k.key(ktest.ENTER)
        check('Return: %s at once (%d pages), LODE.INI %s' % (txt, pg, ini if ini else 'gone (256 KB: no line)'),
              re.search(r'Size\s+' + txt, screen(k)) and md_pages(k) == pg and disk_file(k, 'LODE.INI') == ini and not k.crashed,
              (screen(k), md_pages(k), disk_file(k, 'LODE.INI')))
    k.key(ktest.ESC)
    # the Executive: M: in Device, the file commands, a program run from it
    k.key(ktest.TAB)
    check('the Executive\'s Device list: A: and M:', k.u16('nent') == 2 and has(k, 'Temporary disk M:') and has(k, 'Floppy A:'),
          k.u16('nent'))
    k.key(ktest.TAB); k.key(ktest.TAB)
    k.select('NOTES.TXT'); k.key(CODE['C'])
    k.key(ktest.ENTER, ktest.RIGHT, K_CODE_ENTER)
    check('CODE-C: Device Right is M:: NOTES.TXT copied to M:\\', md_files(k).get('M:\\NOTES.TXT') == TEXT
          and k.band()[0] == 'Copied to M:\\NOTES.TXT', (k.band(), sorted(md_files(k))))
    k.key(ktest.ENTER)
    k.select('MEMSZ.COM'); k.key(CODE['C']); k.key(ktest.ENTER, ktest.RIGHT, K_CODE_ENTER); k.key(ktest.ENTER)
    k.key(ktest.TAB); k.key(ktest.DOWN); k.key(ktest.ENTER); k.key(ktest.TAB)
    check('Device: M: chosen: its titles listed', form(k)[0] == 'Temporary disk M:' and k.exec_list() == ['MEMSZ.COM', 'NOTES.TXT'],
          (form(k), k.exec_list()))
    out = k.run_file('MEMSZ.COM', 20)
    check('a program run from M: (MEMSZ.COM): it runs, back in the Executive on M:', 'KB for programs' in out
          and k.band()[0] == 'MEMSZ.COM ended' and form(k)[0] == 'Temporary disk M:', (out[-100:], k.band()))
    k.key(ktest.ENTER)
    k.select('NOTES.TXT'); k.key(CODE['R']); k.key('n2.txt', ktest.ENTER)
    check('CODE-R on M:: renamed', 'M:\\N2.TXT' in md_files(k) and 'M:\\NOTES.TXT' not in md_files(k), (k.band(), sorted(md_files(k))))
    k.select('N2.TXT'); k.key(CODE['M']); k.key(ktest.ENTER, ktest.LEFT, ktest.ENTER, '\\work', K_CODE_ENTER)
    A = lambda: fatcheck.read_files(bytes(k.pc.drives[0].img))
    check('CODE-M from M: to A:\\WORK: there, gone from M:', A().get('A:\\WORK\\N2.TXT') == TEXT and 'M:\\N2.TXT' not in md_files(k),
          (k.band(), sorted(md_files(k))))
    k.key(ktest.ENTER)
    k.select('MEMSZ.COM'); k.key(CODE['D']); k.key(ktest.ENTER)
    check('CODE-D on M:: erased (M: empty)', not md_files(k), sorted(md_files(k)))
    # Copy on a subject to M: (0.3.13), from A:
    k.key(ktest.TAB); k.key(ktest.UP); k.key(ktest.ENTER); k.key(ktest.TAB)
    pick_subject(k, 'WORK'); k.key(CODE['C']); k.key(ktest.RIGHT, K_CODE_ENTER, ktest.ENTER, settle=False); k.settle(20)
    check('Copy on a subject: A:\\WORK to M:\\WORK', md_files(k).get('M:\\WORK\\N2.TXT') == TEXT and 'Copied' in k.band()[0],
          (k.band(), sorted(md_files(k))))
    k.key(ktest.ENTER)
    # M: holds files: the question; ESC keeps them, Return erases
    k.key(CODE['U']); k.key('T')
    k.key(ktest.ENTER)
    check('Return with files on M:: "M: holds files: Confirm to erase them"', k.band()[0] == 'M: holds files: Confirm to erase them',
          k.band())
    k.key(ktest.ESC)
    check('... ESC: M: as it was (256 KB, its files)', md_pages(k) == 16 and 'M:\\WORK\\N2.TXT' in md_files(k)
          and disk_file(k, 'LODE.INI') is None, (md_pages(k), sorted(md_files(k))))
    # a file open on M: (a resident program's): refused
    k.key(ktest.ESC)
    sh_cmd = lambda c: (k.key(ktest.CODE_P), k.key(c), k.key(ktest.ENTER), k.key('exit'), k.key(ktest.ENTER),
                        k.pc.run_until(lambda: k.pc.mode() == 0x40, 5), k.settle())
    sh_cmd('mdtest /k')
    k.key(ktest.ENTER)                                  # ("LCMD.COM ended")
    k.key(CODE['U']); k.key('T'); k.key(ktest.ENTER)
    check('a file on M: open (a resident program\'s): "A file on M: is open: M: can\'t change now"',
          k.band()[0] == "A file on M: is open: M: can't change now" and md_pages(k) == 16, k.band())
    k.key(ktest.ENTER); k.key(ktest.ESC)
    # off while the Executive is on M:
    k = ktest.KPC(img, ems_pages=88); k.pc.mouse = True; k.start()
    k.key(ktest.TAB); k.key(ktest.DOWN); k.key(ktest.ENTER); k.key(ktest.TAB)
    check('the Executive on M: (empty)', form(k)[0] == 'Temporary disk M:', form(k))
    k.key(CODE['U']); k.key('T')
    for _ in range(4): k.key(ktest.ENTER)               # 512, 1 MB, all, off
    check('M: off from System while the Executive was on it', md_pages(k) == 0 and disk_file(k, 'LODE.INI') == b'MDISK=0\r\n',
          md_pages(k))
    k.key(ktest.ESC)
    check('... back in the Executive: A: listed, no error', form(k)[0] == 'Floppy A:' and 'NOTES.TXT' in k.exec_list()
          and not k.crashed, (form(k), k.band(), k.exec_list()))
    k.key(ktest.TAB)
    check('... Device: A: only', k.u16('nent') == 1, k.u16('nent'))
    k.key(ktest.TAB); k.key(ktest.TAB)
    k = reboot(k, 'mdu2.img')
    check('after a restart: MDISK=0 taken (M: off)', md_pages(k) == 0 if k.pc.ems_pages else True, None)
    # the saver: with M: on and no C:, DEFRAG on A: only
    k = ktest.KPC(img, ems_pages=88); k.pc.mouse = True; k.start()
    seen = []
    a = k.Y['exec_raw']
    k.hooks.append(lambda pc: seen.append(k.rd('sv_tail', 1)) if pc.r('cs') == k.useg and pc.r('ip') == a else None)
    idle(k, 5 * 1092 + 18); k.pc.run_for(30)
    check('the screen saver with M: on (and no C:): DEFRAG on A: only', set(seen) == {b'A'}, seen)
    k.key(ktest.ESC); k.settle(8)
    sh = None
    k.key(ktest.CODE_P); k.key('defrag m:'); k.key(ktest.ENTER)
    check('DEFRAG M:: "M: is the temporary disk, in memory: nothing to tidy"', 'nothing to tidy' in k.pc.text_screen(), k.pc.text_screen())

# ---------------------------------------------------------------------
RCTEST = os.path.join(HERE, 'RCTEST.RUN')
RC6 = os.path.join(HERE, 'RC6.RUN')

def press(k, x, y, buttons):
    """Move the pointer to (x, y), then the buttons down and up again."""
    point(k, x, y)
    k.pc.mouse_move(0, 0, buttons); k.pc.run_for(0.05)
    k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05); k.settle()

def rc_events(k, src='tests/RCTEST.ASM'):
    """The events RCTEST.RUN has had: (AX, BX, CX) each."""
    sy, base = run_syms(src), k.u16('run_base')
    n = k.pc.u16(k.useg, base + sy['nevs'])
    return [struct.unpack('<3H', k.pc.rd(k.useg, base + sy['evs'] + 6 * i, 6)) for i in range(min(n, 32))]

def t_rclick():
    """Right clicks (UI API 7): EV_RCLICK, with x and y, only to a .RUN that
    needs API 7; the core's own waits ignore it; the Executive and older
    .RUNs never see it."""
    print('== right clicks (UI API 7)')
    hdr = open(RCTEST, 'rb').read(6), open(RC6, 'rb').read(6)
    check('RCTEST.RUN needs API 7, RC6.RUN 6 (the same program)', hdr == (b'GRUN\x07\x00', b'GRUN\x06\x00'), hdr)
    k = ktest.KPC(image('rclick.img', RCTEST, RC6)); k.pc.mouse = True; k.start()
    made, ev = [], k.Y['ui_event.got']                  # (every event UI_EVENT gets, a jump target)
    k.hooks.append(lambda pc: made.append(pc.r('ax')) if pc.r('cs') == k.useg and pc.r('ip') == ev else None)
    sel0 = k.u16('sel')
    press(k, 300, 200, 2); press(k, 320, 5, 1)
    check('in the Executive: a right click makes no event at all (the left one does: the hook sees events)',
          made == [0xFF01] and not k.crashed, [hex(a) for a in made])
    k.select('RCTEST.RUN'); k.key(ktest.ENTER)
    press(k, 100, 50, 2)
    check('in an API 7 .RUN: a right press is EV_RCLICK (FF03h) at (100, 50), its release nothing', rc_events(k) == [(0xFF03, 100, 50)],
          rc_events(k))
    press(k, 200, 60, 1)
    check('... a left press: EV_CLICK as before', rc_events(k)[1:] == [(0xFF01, 200, 60)], rc_events(k))
    press(k, 210, 70, 3)
    check('... both pressed in one packet: EV_CLICK only', rc_events(k)[2:] == [(0xFF01, 210, 70)], rc_events(k))
    point(k, 220, 80); k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 3); k.pc.run_for(0.05)
    k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05); k.settle()
    check('... left held, then the right pressed: EV_CLICK only (no right click while the left is down)',
          rc_events(k)[3:] == [(0xFF01, 220, 80)], rc_events(k))
    # a window dragged by its title, the right button pressed in the middle: the drag goes on as if not
    k.key('W')
    sy, base = run_syms('tests/RCTEST.ASM'), k.u16('run_base')
    win = lambda: struct.unpack('<2H', k.pc.rd(k.useg, base + sy['win'], 4))
    n0 = len(rc_events(k))
    point(k, 20 * 8 + 40, 108)
    for dx, dy, b in ((0, 0, 1), (40, 20, 1), (0, 0, 3), (40, 20, 3), (0, 0, 1), (0, 0, 0)):
        k.pc.mouse_move(dx, dy, b); k.pc.run_for(0.05)
    k.settle()
    got = rc_events(k)[n0:]
    check('a window dragged 80 right, 40 down, the right pressed half way: moved by exactly that, EV_MOVED, no EV_RCLICK',
          win() == (30, 140) and [e[0] for e in got] == [0xFF02], (win(), got))
    # the left let go and the right pressed in one packet, mid-drag: win_mv takes x, y from the event, not AX as x
    n0 = len(rc_events(k))
    point(k, 30 * 8 + 40, 148)
    for dx, dy, b in ((0, 0, 1), (40, 20, 1), (0, 0, 2), (0, 0, 0)):
        k.pc.mouse_move(dx, dy, b); k.pc.run_for(0.05)
    k.settle()
    got = rc_events(k)[n0:]
    check('... dragged 40 right, 20 down, then the left up and the right down in one packet: there (35, 160), no EV_RCLICK',
          win() == (35, 160) and 0xFF03 not in [e[0] for e in got], (win(), got))
    # a right click on its close box and on its title strip: neither closes nor moves it; the program gets it
    n0 = len(rc_events(k))
    press(k, (35 + 30 - 2) * 8 + 4, 168, 2); press(k, 35 * 8 + 40, 168, 2)
    got = rc_events(k)[n0:]
    check('a right click on the close box, then on the title: the window open and where it was, two EV_RCLICKs',
          win() == (35, 160) and k.pc.rd(k.useg, base + sy['wopen'], 1) == b'\x01' and [e[0] for e in got] == [0xFF03, 0xFF03], (win(), got))
    k.key(ktest.ESC)
    # the core's own waits: UI_EDIT and UI_ASK go on past a right click, which reaches them (seen at ui_event.got)
    k.key('E'); k.key('ab'); k.key(ktest.ENTER)
    n0, made[:] = len(rc_events(k)), []
    k.key('E'); press(k, 50, 100, 2); k.key('x'); k.key(ktest.ENTER)
    ed = k.pc.u16(k.useg, base + sy['edkey']), k.pc.asciiz(k.useg, base + sy['ebuf'])
    check('UI_EDIT on "ab": a right click reaches it and is ignored, "x" typed first still replaces the text',
          ed == (ktest.ENTER, b'x') and 0xFF03 in made and 0xFF03 not in [e[0] for e in rc_events(k)[n0:]], (ed, [hex(a) for a in made]))
    n0, made[:] = len(rc_events(k)), []
    k.key('A'); press(k, 50, 380, 2)
    asking = k.band()[0] if k.band() else ''
    k.key(ktest.ENTER)
    ask = k.pc.u16(k.useg, base + sy['ask'])
    check('UI_ASK: a right click (on the band too) reaches it, neither confirms nor cancels; Return confirms',
          asking == 'Ask: Confirm' and ask == 1 and 0xFF03 in made and 0xFF03 not in [e[0] for e in rc_events(k)[n0:]],
          (asking, ask, [hex(a) for a in made]))
    k.key(ktest.ESC)
    made.clear()
    press(k, 300, 200, 2); press(k, 320, 5, 1)
    check('back in the Executive (the last .RUN needed API 7): still no right clicks', made == [0xFF01] and k.rd('run_active', 1) == b'\x00',
          [hex(a) for a in made])
    k.select('RC6.RUN'); k.key(ktest.ENTER)
    press(k, 100, 50, 2); press(k, 120, 60, 1)
    got = rc_events(k, 'tests/RC6.ASM')
    check('an API 6 .RUN: no EV_RCLICK, the left click as ever', got == [(0xFF01, 120, 60)], got)
    k.key(ktest.ESC)
    check('... and the Executive afterwards', k.rd('run_active', 1) == b'\x00' and not k.crashed, k.band())

MENUTEST = os.path.join(HERE, 'MENUTEST.RUN')

def body(k):
    """The screen under the title bar (rows 24-399), row by row."""
    v = k.pc.rd(0xB800, 0, 0x8000)
    return b''.join(v[(y & 3) * 0x2000 + (y >> 2) * 80:][:80] for y in range(24, 400))

def t_menu():
    """UI_MENU and UI_MOUSE (UI API 8): a pop-up menu at a right click, chosen
    by keys or a click, cancelled by ESC or a click outside; the screen under
    it as it was; a drag followed with UI_MOUSE."""
    print('== pop-up menus and drags (UI API 8)')
    hdr = open(MENUTEST, 'rb').read(6)
    check('MENUTEST.RUN needs API 8', hdr == b'GRUN\x08\x00', hdr)
    k = ktest.KPC(image('menu.img', MENUTEST)); k.pc.mouse = True; k.start()
    k.select('MENUTEST.RUN'); k.key(ktest.ENTER)
    sy, base = run_syms('tests/MENUTEST.ASM'), k.u16('run_base')
    v16 = lambda n, i=0: k.pc.u16(k.useg, base + sy[n] + 2 * i)
    evs = lambda: [v16('evs', i) for i in range(min(v16('nevs'), 64))]
    hw = lambda: struct.unpack('<4H', k.rd('help_w', 8))
    def rpress(x, y):
        point(k, x, y); k.pc.mouse_move(0, 0, 2); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05); k.settle()
    check('UI_VERSION: API 9 (M9c: EV_CLOSE)', v16('ver') == 9, v16('ver'))
    point(k, 100, 100); v0 = body(k)
    rpress(100, 100)
    shown = hw(), has(k, 'Cut') and has(k, 'Paste') and has(k, 'Find...')
    k.key(ktest.DOWN); k.key(ktest.DOWN); k.key(ktest.ENTER)
    check('a right click at (100, 100): the menu there (column 12, row 100, 20 wide, 88 high) with its items; Down, Down, Return: item 2',
          shown == ((12, 100, 20, 88), True) and v16('mres') == 2 and v16('nmenu') == 1, (shown, v16('mres'), v16('nmenu')))
    check('... the screen under it as it was (its save-under), the keys the menu\'s, not the program\'s',
          body(k) == v0 and evs() == [0xFF03], [hex(e) for e in evs()])
    rpress(100, 100); k.key('F'); k.key(ktest.ENTER)
    check('a letter: the item starting with it (F: Find..., 4)', v16('mres') == 4, v16('mres'))
    rpress(100, 100); press(k, 120, 128, 1); point(k, 100, 100)
    check('a click on its second item: item 1; the screen as it was', v16('mres') == 1 and body(k) == v0, v16('mres'))
    n0 = v16('nevs')
    rpress(100, 100); press(k, 500, 128, 1); m1 = v16('mres'); rpress(100, 100); press(k, 100, 300, 1); point(k, 100, 100)
    check('a click right of it (on its second row\'s level), then one under it: none (FFFFh) each; the clicks taken (no EV_CLICK, no drag), the screen as it was',
          m1 == 0xFFFF and v16('mres') == 0xFFFF and v16('nmenu') == 5 and evs()[n0:] == [0xFF03, 0xFF03] and v16('dn') == 0 and body(k) == v0, ([hex(e) for e in evs()[n0:]], v16('dn')))
    rpress(100, 100); press(k, 100, 186, 1)
    check('a click inside it but on no item (its bottom edge, row 186): it stays open', has(k, 'Paste') and v16('nmenu') == 5, v16('nmenu'))
    point(k, 100, 100); k.key(ktest.ESC)
    check('ESC: none, and the ESC the menu\'s (the program\'s window still open)', v16('mres') == 0xFFFF
          and k.pc.rd(k.useg, base + sy['wopen'], 1) == b'\x01' and body(k) == v0, v16('mres'))
    k.key('M'); at = hw(); k.key(ktest.ENTER); mm = v16('mres')
    k.key('N'); at2 = hw(); k.key(ktest.ENTER)
    check('at (639, 399): kept on the screen above the band (column 60, row 272), AH = 3 lit first (Return: 3); at (0, 0): '
          'under the title rule (0, 24), and AH past the last item: the first lit (Return: 0)',
          at[:2] == (60, 272) and mm == 3 and at2[:2] == (0, 24) and v16('mres') == 0 and body(k) == v0, (at, mm, at2, v16('mres')))
    k.key('T'); at4 = hw(); k.key(ktest.ESC)
    check('20 items at (100, 399): 328 rows high, from row 32 (the band below it)', at4 == (12, 32, 20, 328) and body(k) == v0, at4)
    k.key('L'); at3 = hw(); k.key(ktest.ESC)
    check('an item of 90 characters: the menu the screen\'s width (80 columns, from column 0), the item cut at its edge',
          at3[0] == 0 and at3[2] == 80 and body(k) == v0, at3)
    rpress(100, 103); g103 = hw(); k.key(ktest.ESC); point(k, 100, 100); b1 = body(k) == v0
    rpress(100, 270); g270 = hw(); k.key(ktest.ESC); point(k, 100, 100); b2 = body(k) == v0
    check('right clicks at (100, 103) and (100, 270): rows 100 and 268 (multiples of 4, rounded down; 272 the lowest), '
          'the screen as it was after each', g103 == (12, 100, 20, 88) and g270 == (12, 268, 20, 88) and b1 and b2, (g103, g270, b1, b2))
    k.key('H'); gh = hw(); k.key(ktest.ESC); point(k, 100, 100)
    check('UI_HELP, a title of 38 characters over a line of 16: the title\'s width + 6, centred (column 18, row 164, 44 wide, '
          '52 high); the screen as it was after', gh == (18, 164, 44, 52) and body(k) == v0, gh)
    beeps, wd, nm = [], k.u16('wdepth'), v16('nmenu')
    def beep(pc):
        if pc.r('ip') == k.Y['ui_beep'] and pc.r('cs') == k.useg: beeps.append(1)
    k.hooks.append(beep)
    got = []
    for key in 'ZV':
        k.pc.wr(k.useg, base + sy['mres'], struct.pack('<H', 1234)); k.key(key); got.append(v16('mres'))
    k.hooks.remove(beep)
    check('UI_MENU with 0 items and with 21: refused at once (CF: none, FFFFh, each), a beep each, no window, the screen as it was',
          got == [0xFFFF, 0xFFFF] and v16('nmenu') - nm == 2 and len(beeps) == 2 and k.u16('wdepth') == wd and body(k) == v0,
          (got, v16('nmenu') - nm, len(beeps), k.u16('wdepth'), wd))
    k.key('O', 'O', 'O'); nm, dp = v16('nmenu'), k.u16('wdepth')
    rpress(100, 100)
    full = v16('nmenu') - nm, v16('mres'), k.u16('wdepth'), k.u16('wover'), has(k, 'Paste')
    k.key(ktest.ESC, ktest.ESC, ktest.ESC); point(k, 100, 100)
    check('four windows open (the most): a right click gives no menu, none at once (FFFFh), nothing over the windows (%s)' % (full,),
          dp == 4 and full == (1, 0xFFFF, 4, 0, False) and k.u16('wdepth') == 1 and body(k) == v0, (dp, full, k.u16('wdepth')))
    # the saver while it is open: the menu back after, with what was lit
    rpress(100, 100); k.key(ktest.DOWN)
    k.wr('saver_t', struct.pack('<H', 36))
    for _ in range(40):
        k.pc.run_for(0.25)
        if not has(k, 'Paste'): break
    dark = not has(k, 'Paste')
    k.wr('saver_t', struct.pack('<H', 5460))
    k.key(ktest.DOWN)
    back = has(k, 'Paste') and has(k, 'Menu test')
    k.key(ktest.ENTER)
    check('the saver while it is open, a key: the menu back over the window, item 1 still lit; Return: 1, the screen as it was',
          dark and back and v16('mres') == 1 and body(k) == v0, (dark, back, v16('mres')))
    # a drag: UI_MOUSE until the left button is up
    n0 = v16('nevs')
    drag(k, 200, 200, 280, 240)
    d0, d1 = [tuple(v16(n, i) for i in range(3)) for n in ('d0', 'd1')]
    check('a drag from (200, 200) to (280, 240): one EV_CLICK, then UI_MOUSE: the left down on the way (240, 240), up at (280, 240) at the end',
          evs()[n0:] == [0xFF01] and d0 == (1, 240, 240) and d1 == (0, 280, 240) and v16('dn') >= 3 and v16('dcf') == 0, (evs()[n0:], d0, d1, v16('dn')))
    press(k, 300, 250, 1)
    check('... the next press is an event again (EV_CLICK)', evs()[n0:] == [0xFF01, 0xFF01], [hex(e) for e in evs()[n0:]])
    nm = v16('nmenu')
    point(k, 200, 200)
    for b in (1, 3, 3, 2, 0):                       # (the right pressed during the drag, let go after the left)
        k.pc.mouse_move(4, 0, b); k.pc.run_for(0.05)
    k.settle()
    check('... the right pressed during a drag, let go after the left: UI_MOUSE saw it (3), so it is no EV_RCLICK after (no menu)',
          evs()[n0:] == [0xFF01] * 3 and v16('nmenu') == nm and not has(k, 'Paste'), ([hex(e) for e in evs()[n0:]], v16('nmenu') - nm))
    # no window open: the menu borrows the cache itself (ui_wopen's first window) and gives it back
    k.key(ktest.ESC)
    point(k, 100, 100); v1 = body(k)
    rpress(100, 100); lent = k.u16('wseg') != 0
    k.key(ktest.ENTER)
    check('its window closed (none open): the menu saves under it all the same, gives the cache back after; item 0',
          lent and v16('mres') == 0 and k.u16('wseg') == 0 and k.u16('wdepth') == 0 and body(k) == v1, (lent, v16('mres'), k.u16('wseg')))
    k.key(ktest.ESC)
    check('ESC: the Executive again', k.rd('run_active', 1) == b'\x00' and not k.crashed and has(k, 'MENUTEST'), k.band())
    k = ktest.KPC(image('menu.img', MENUTEST)); k.start()
    k.select('MENUTEST.RUN'); k.key(ktest.ENTER)
    base = k.u16('run_base')
    k.key('U')
    dcf = k.pc.u16(k.useg, base + sy['dcf'])
    s0 = k.pc.rd(0xB800, 0, 0x8000)
    k.key('W'); gw = struct.unpack('<4H', k.rd('help_w', 8)); hl = dict(k.ocr()).get(192, ''); k.key(ktest.ESC)
    back = k.pc.rd(0xB800, 0, 0x8000) == s0
    k.key(ktest.ESC, ktest.ESC)
    check('no mouse: UI_MOUSE says so (CF)', dcf == 0xFFFF and k.rd('run_active', 1) == b'\x00' and not k.crashed, dcf)
    s_long = 'A very long item, longer than a line of the screen: ninety characters, and then some more.'
    check('UI_HELP, a line of 90 characters: 78 wide, the most, centred (column 1, row 164, 52 high); the line cut at the '
          'inner edge (its first 72 characters, columns 4-75, two blank before the frame); ESC: the screen exactly as it was',
          gw == (1, 164, 78, 52) and hl[4:76] == s_long[:72] and hl[76:].strip() == '' and back, (gw, hl, back))

CLIPTEST = os.path.join(HERE, 'CLIPTEST.RUN')
CLIPPAT = bytes((i * 7 + 3) & 0xFF for i in range(16385))

class Clip:
    """CLIPTEST.RUN running in k: put, get, size (UI_CLIP AL = 0, 1, 2)."""
    def __init__(s, k):
        s.k = k
        k.select('CLIPTEST.RUN'); k.key(ktest.ENTER)
        s.sy, s.base = run_syms('tests/CLIPTEST.ASM'), k.u16('run_base')
    def v(s, n): return s.k.pc.u16(s.k.useg, s.base + s.sy[n])
    def set(s, n, x): s.k.pc.wr(s.k.useg, s.base + s.sy[n], struct.pack('<H', x))
    def put(s, data):
        s.k.pc.wr(s.v('bseg'), 0, data); s.set('plen', len(data)); s.k.key('P')
        return (s.v('rcf'), s.v('rret')) if s.v('rcf') else 0
    def get(s, room):
        s.k.pc.wr(s.v('bseg'), 16400, bytes(room + 16)); s.set('gmax', room); s.k.key('G')
        return (s.v('rcf'), s.v('rret')) if s.v('rcf') else bytes(s.k.pc.rd(s.v('bseg'), 16400, s.v('gcx'))), \
            bytes(s.k.pc.rd(s.v('bseg'), 16400 + s.v('gcx'), 16))
    def size(s):
        s.k.key('S'); return s.v('scx')

def t_clip():
    """UI_CLIP (UI API 8): a clipboard every .RUN shares, kept when they end:
    in an EMS page of its own, else in CLIP.$$$ on the settings drive."""
    print('== the clipboard (UI_CLIP, UI API 8)')
    k = ktest.KPC(image('clip.img', CLIPTEST), ems_pages=88); k.start()
    c = Clip(k)
    s0 = c.size()
    e0 = c.put(b'')
    h0 = k.u16('clip_h')
    r = c.put(CLIPPAT[:1000])
    h = k.u16('clip_h')
    rec = k.rd('ems_h', 4, 4 * h) if h else b''
    check('EMS: empty at first (%d), and emptied takes no page yet; 1000 bytes put: its size 1000, in a page of its own (handle %d: %r, nobody\'s), not the file'
          % (s0, h, rec.hex()), s0 == 0 and e0 == 0 and h0 == 0 and r == 0 and c.size() == 1000 and 0 < h < 32 and rec[1] == 1
          and rec[2:] == b'\0\0' and k.rd('clip_f', 1) == b'\0' and disk_file(k, 'CLIP.$$$') is None, (s0, r, h, rec))
    g, past = c.get(2000)
    g10, past10 = c.get(10)
    check('got with room for 2000: the 1000 bytes, nothing past them; with room for 10: those 10, nothing past them',
          g == CLIPPAT[:1000] and past == bytes(16) and c.v('gcx') == 10 and g10 == CLIPPAT[:10] and past10 == bytes(16),
          (len(g) if isinstance(g, bytes) else g, past, g10))
    k.key(ktest.ESC)
    c = Clip(k)
    g, _ = c.get(2000)
    check('the program ended and started again: still the 1000 bytes (kept by the core, not the program)',
          c.size() == 1000 and g == CLIPPAT[:1000] and k.u16('clip_h') == h, (c.size(), k.u16('clip_h')))
    big = c.put(CLIPPAT)
    kept, kn = c.get(2000)[0], c.size()
    full = c.put(CLIPPAT[:16384])
    g, _ = c.get(16384)
    check('16385 bytes: refused (CF, error 8), what it held kept; 16384: the page full, got back whole',
          big == (0xFFFF, 8) and kept == CLIPPAT[:1000] and kn == 1000 and full == 0 and g == CLIPPAT[:16384]
          and c.size() == 16384 and k.u16('clip_h') == h, (big, kn, full, k.u16('clip_h')))
    e = c.put(b'')
    g, _ = c.get(100)
    check('0 bytes put: empty (size 0, nothing to get)', e == 0 and c.size() == 0 and g == b'' and c.v('gcx') == 0, (e, c.size()))
    k.key(ktest.ESC)
    check('... and the Executive again', k.rd('run_active', 1) == b'\x00' and not k.crashed, k.band())
    # no EMS: CLIP.$$$ on the start-up disk (no settings drive of its own here)
    k = ktest.KPC(image('clip0.img', CLIPTEST)); k.start()
    c = Clip(k)
    e0 = c.put(b'')
    f0 = disk_file(k, 'CLIP.$$$')
    r = c.put(CLIPPAT[:3000])
    g, _ = c.get(4000)
    f = disk_file(k, 'CLIP.$$$')
    check('no EMS: emptied first writes no file; 3000 bytes put go to A:\\CLIP.$$$ (exactly them), got back whole',
          e0 == 0 and f0 is None and r == 0 and k.u16('clip_h') == 0
          and k.rd('clip_f', 1) == b'\x01' and f == CLIPPAT[:3000] and g == CLIPPAT[:3000] and c.size() == 3000,
          (r, k.u16('clip_h'), f and len(f)))
    k.key(ktest.ESC)
    c = Clip(k)
    g, _ = c.get(4000)
    r2 = c.put(CLIPPAT[5:105])
    check('... the program started again: still them; 100 others put: the file just those',
          g == CLIPPAT[:3000] and r2 == 0 and disk_file(k, 'CLIP.$$$') == CLIPPAT[5:105] and c.size() == 100, (len(g), r2))
    k.pc.drives[0].wp = True
    r3, n3 = c.put(CLIPPAT[:50]), c.size()
    k.pc.drives[0].wp = False
    g, _ = c.get(200)
    check('... A: write-protected, 50 others put: refused (CF), and the 100 still held (size 100, got back whole: the file '
          'was never made anew, so it isn\'t "empty")', r3 != 0 and n3 == 100 and g == CLIPPAT[5:105]
          and disk_file(k, 'CLIP.$$$') == CLIPPAT[5:105], (r3, n3, g if not isinstance(g, bytes) else len(g)))
    k.key('T')                          # CLIP.$$$ cut behind the core's back
    r4, _ = c.get(200)
    check('... the file cut since: a get comes up short, error 30 (Disk error (read)), not 29 (a write\'s)',
          r4 == (0xFFFF, 30) and c.size() == 100, (r4, c.size()))
    k.key(ktest.ESC)
    # EMS, every page M:'s (MDISK=ALL): none to be had, so the file
    ini = os.path.join(OUT, 'LODE.INI'); open(ini, 'wb').write(b'MDISK=ALL\r\n')
    k = ktest.KPC(image('clipm.img', CLIPTEST, 'LODE.INI=' + ini), ems_pages=88); k.start()
    c = Clip(k)
    r = c.put(CLIPPAT[:500])
    g, _ = c.get(500)
    check('EMS but every page M:\'s (MDISK=ALL): the file instead (A:\\CLIP.$$$), got back whole', r == 0 and k.u16('clip_h') == 0
          and k.rd('clip_f', 1) == b'\x01' and disk_file(k, 'CLIP.$$$') == CLIPPAT[:500] and g == CLIPPAT[:500], (r, k.u16('clip_h')))
    k.key(ktest.ESC)

# ---------------------------------------------------------------------
def rom1(*extra):
    """ROM 1 of the files built now (build.sh's, less LODEMT.SYS, TASKS.RUN
    and TERM.RUN, as test_rom's rom_ini), with the ROM's LODE.INI and extra
    files: booted with test_rom's boot(roms={1: ...})"""
    sys.path.insert(0, os.path.join(os.path.dirname(GOS), 'tools'))
    import mkrom
    names = ['src/LODE.SYS', 'src/LODE.PIC', 'src/LCMD.COM', 'apps/SYSTEM.RUN', 'apps/WRITE.RUN', 'apps/CALC.RUN',
             'src/CALC.COM', 'fonts/TERMINUS.FNT', 'drivers/PS.PRN', 'rom/LODE.INI']
    files = [(os.path.basename(n), open(os.path.join(GOS, n), 'rb').read()) for n in names]
    files += [(os.path.basename(p), open(p, 'rb').read()) for p in extra]
    return mkrom.volume(files, boot=open(os.path.join(GOS, 'src', 'ROMBOOT.BIN'), 'rb').read())[0]

def t_clip_rom():
    """UI_CLIP's file from the ROM with no settings drive (the menu's 2, or
    no C: and no A:\\LODE.INI): not R:, which takes no writes, but C: if
    there, else A: (as System and the kernel's capdrv)."""
    print('== the clipboard\'s file from the ROM (no settings drive, no EMS)')
    import test_rom as R
    rom = rom1(CLIPTEST)
    k = R.boot(roms={1: rom})
    c = Clip(k)
    r = c.put(CLIPPAT[:700])
    g, _ = c.get(1000)
    check('no C:, no A:\\LODE.INI: A:\\CLIP.$$$ (not R:\\, refused), got back whole', R.u8(k, 'setdrv') == 0
          and k.rd('s_clip', 1) == b'A' and r == 0 and disk_file(k, 'CLIP.$$$') == CLIPPAT[:700] and g == CLIPPAT[:700],
          (R.u8(k, 'setdrv'), k.rd('s_clip', 1), r))
    k.key(ktest.ESC)
    k = R.boot(roms={1: rom}, ata=R.sysinfo_hd(('CLIPTEST.RUN', open(CLIPTEST, 'rb').read()), ('LODE.INI', b'SAVER=10\r\n')),
               shift=True, keys=[ord('2')])
    c = Clip(k)
    r = c.put(CLIPPAT[:600])
    g, _ = c.get(1000)
    check('the menu\'s 2 (the ROM\'s own settings) with C:: C:\\CLIP.$$$, got back whole', R.u8(k, 'setdrv') == 0
          and k.rd('s_clip', 1) == b'C' and r == 0 and R.hd_file(k, 'CLIP.$$$') == CLIPPAT[:600] and g == CLIPPAT[:600],
          (R.u8(k, 'setdrv'), k.rd('s_clip', 1), r))
    k.key(ktest.ESC)

def t_sys_back():
    """System's Settings, Return (back to the ROM's): SPLASH= is forgotten
    with the file, as MULTITASK= is, so Display and the next save don't
    bring the deleted SPLASH=0 back."""
    print('== System: back to the ROM\'s settings forgets SPLASH= too')
    import test_rom as R
    k = R.boot(roms={1: rom1()}, ata=R.sysinfo_hd(('LODE.INI', b'SPLASH=0\r\n')))
    to_display(k)
    no = re.search(r'Start-up picture\s+no', screen(k))
    for _ in range(3): k.key(ktest.DOWN)                        # Settings
    k.key(ktest.ENTER); k.key(ktest.ENTER)                      # back to the ROM's: asked, confirmed
    gone = R.hd_file(k, 'LODE.INI') is None
    k.key(ktest.ESC)                                            # (the message read)
    for _ in range(3): k.key(ktest.UP)                          # Display
    yes = re.search(r'Start-up picture\s+yes', screen(k))
    k.key(ktest.ENTER)                                          # the next font, saved
    ini = R.hd_file(k, 'LODE.INI')
    check('C:\\LODE.INI with SPLASH=0: Display says no; back to the ROM\'s (the file gone): Display says yes, and the next '
          'font goes in a new C:\\LODE.INI without SPLASH=0', no and gone and yes and ini == b'FONT=TERMINUS.FNT\r\n',
          (bool(no), gone, bool(yes), ini, screen(k)))

def t_system_lists():
    """System's values clipped at the screen's edge: GPIB's SRQ line whole;
    the fonts on the start-up disk and GPIB's instruments cut at an entry's
    end (they used to end in half a name, or half an address)."""
    print('== System: lines that reach the screen\'s edge')
    fonts = []
    for c in 'BCDEFG':
        p = os.path.join(OUT, 'FONT%s123.FNT' % c); open(p, 'wb').write(bytes(1536)); fonts.append(p)
    devs = {a: sim7210.Device(a, 0, {}) for a in range(5, 31) if a != 21}
    k = ktest.KPC(image('lists.img', SYSTEM, *fonts), chip=sim7210.NEC7210(devs)); k.start()
    to_display(k)
    m = re.search(r'GRiD \(built in\),.*$', screen(k), re.M)
    fl = m.group(0).strip() if m else screen(k)
    check('Display: as many fonts as fit, the last one whole ("GRiD (built in)" and three NAME.FNT)',
          fl == 'GRiD (built in), FONTB123.FNT, FONTC123.FNT, FONTD123.FNT', fl)
    k.key('G')
    check('GPIB: "on IRQ 5 (GPIBIRQ=0: polled)", whole', re.search(r'SRQ\s+on IRQ 5 \(GPIBIRQ=0: polled\)$', screen(k), re.M), screen(k))
    k.key(ktest.ENTER); k.key(ktest.ENTER, settle=False); k.settle(30)
    m = re.search(r'Instruments at\s+(.*)$', screen(k), re.M)
    check('... 25 instruments found: as many as fit, the last address whole (5 to 14; 15 would end past the edge)',
          m and m.group(1).strip() == ', '.join(str(a) for a in range(5, 15)), m and m.group(1))
    k.key(ktest.ESC)

def t_gpib_tools():
    """tools/GRIDGPIB.COM, the standalone driver (here under Lodestone, the
    kernel's driver moved out of INT 60h's way), and tools/GPIBXFER.COM (in
    sim7210's own machine), both assembled from tools/ now."""
    print('== GRIDGPIB /U and GPIBXFER (tools/)')
    tools = os.path.join(os.path.dirname(GOS), 'tools')
    gg, gx = os.path.join(OUT, 'GRIDGPIB.COM'), os.path.join(OUT, 'GPIBXFER.COM')
    for src, dst in (('GRIDGPIB.ASM', gg), ('GPIBXFER.ASM', gx)):
        subprocess.run(['nasm', '-f', 'bin', '-i', tools + '/', '-o', dst, os.path.join(tools, src)], check=True)
    k = ktest.KPC(image('ggu.img', LCMD, gg), chip=sim7210.NEC7210(sim7210.bus())); k.start()
    k.code_p()
    def run(cmd):
        k.key('cls'); k.key(ktest.ENTER); k.key(cmd); k.key(ktest.ENTER)
        return k.pc.text_screen()
    i0d = k.pc.rd(0, 0x0D * 4, 4)                               # (the kernel's)
    k.pc.wr(0, 0x60 * 4, bytes(4))                              # (INT 60h free for GRIDGPIB)
    o1 = run('gridgpib')
    seg, m1 = k.pc.u16(0, 0x60 * 4 + 2), k.pc.pic_mask
    k.pc.wr(0, 0x0D * 4, i0d)                                   # INT 0Dh someone else's since
    o2 = run('gridgpib /u')
    m2, seg2 = k.pc.pic_mask, k.pc.u16(0, 0x60 * 4 + 2)
    check('GRIDGPIB /U while another program has INT 0Dh: refused, and the driver left as it was (IRQ 5 still unmasked)',
          'SRQ on IRQ 5' in o1 and seg not in (0, 0x60) and not m1 & 0x20 and 'took INT 0Dh after GRIDGPIB' in o2
          and seg2 == seg and not m2 & 0x20, (o1, o2, hex(m1), hex(m2)))
    import sim7210 as S
    class Echo(S.Device):
        """the Pico bridge's thrutest: each 4096-byte message sent back; gone
        (no listener) once it has echoed the first pair's"""
        def __init__(s, devs, gone):
            S.Device.__init__(s, 7, 0, {}); s.devs, s.acc, s.n, s.gone = devs, b'', 0, gone
        def message(s, msg):
            s.acc += msg
            if len(s.acc) >= 4096: s.out, s.acc = s.acc[:4096], s.acc[4096:]; s.n += 1
        def on_sent(s):
            if s.gone and s.n > 16: s.devs.pop(7, None)
    bus, outs = S.bus, []
    try:
        for gone in (False, True):
            devs = {}; devs[7] = Echo(devs, gone)
            S.bus = lambda: devs
            outs.append(S.run(gx, maxins=100_000_000)[0].split('DMA, channel 3:')[0])
    finally:
        S.bus = bus
    check('GPIBXFER, its CPU loop with an echoing device: both ways, every byte right', 'device -> GRiD:' in outs[0]
          and 'the echo is every byte right' in outs[0] and 'failed' not in outs[0], outs[0])
    check('... the device gone after the first pair: the second pair\'s write fails, said as "sending failed" (not "receiving")',
          'sending failed, step 03h' in outs[1] and 'receiving' not in outs[1], outs[1])

if __name__ == '__main__':
    t0 = time.time()
    build()
    only = [a for a in sys.argv[1:] if a.startswith('t_')]
    for t in (t_core, t_system, t_write, t_exec, t_font, t_memory, t_saver, t_mouse, t_form, t_files, t_file_safety, t_wild, t_subdel, t_subcopy, t_saver_delay, t_ini_keys, t_saver_tidy, t_prtsc_setting, t_mdisk, t_calc, t_calc_move, t_rclick, t_menu, t_clip, t_write_mouse, t_write_clip,
              t_clip_rom, t_sys_back, t_system_lists, t_gpib_tools):
        if not only or t.__name__ in only: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
