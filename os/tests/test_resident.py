"""Resident Claude (CLAUDE /R, os/claude): its console's code runs from
EMS pages of its own over programs that use all four EMS windows, over
graphics and text modes, DOS, the Executive and TM5000G while it polls
the bus.  (The spike's own tests, RSPIKE.COM's, went with the 2026-10-26
audit's H12: these mirror each of them.)

    python3 tests/test_resident.py [name ...]
"""
import os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, sim7210
OUT = os.environ.get('KOUT', os.path.join(__import__('tempfile').gettempdir(), 'lodestone-res'))
os.makedirs(OUT, exist_ok=True)
CL = os.path.join(GOS, 'claude')
HOT = 0x2B00                                    # CODE-\ (Alt-\)
TM5000G = next((p for p in (os.environ.get('TM5000G', ''), os.path.join(GOS, '..', 'tools', 'TM5000G.EXE'))
                if p and os.path.exists(p)), None)

def build():
    subprocess.run([os.path.join(GOS, 'kbuild.sh')], check=True, stdout=subprocess.DEVNULL)
    for d, n in ((os.path.join(GOS, 'src'), 'LCMD'), (HERE, 'MEMSZ')):     # (on every disk here and test_resident_term's)
        subprocess.run(['nasm', '-f', 'bin', '-i', d + '/', '-o', os.path.join(d, n + '.COM'), os.path.join(d, n + '.ASM')], check=True)
    for n in ('RSPIKE', 'EMSUSE', 'GFXUSE', 'T1C', 'BUSY', 'MHAND', 'HOLE', 'HOOK16', 'PAGE1'):
        subprocess.run(['nasm', '-f', 'bin', '-o', os.path.join(CL, n + '.COM'), os.path.join(CL, n + '.ASM')], check=True)
    subprocess.run(['sh', os.path.join(CL, 'build.sh')], check=True, stdout=subprocess.DEVNULL)  # RCON.BIN in CLAUDE.COM, its map
    # another version's CLAUDE.COM, as far as the stub goes: laid out otherwise after its header
    subprocess.run(['nasm', '-f', 'bin', '-i', '../src/', '-DSTUB_PAD=5', '-o', os.path.join(OUT, 'CLAUDEP.COM'), 'CLAUDE.ASM'],
                   check=True, cwd=CL)
    # and one whose stub is version 1 (PR #27's: no r_off, its r_pend at 10Eh)
    subprocess.run(['nasm', '-f', 'bin', '-i', '../src/', '-DSTUB_VER=1', '-o', os.path.join(OUT, 'CLAUDEV1.COM'), 'CLAUDE.ASM'],
                   check=True, cwd=CL)

def csym(name):
    """A symbol of CLAUDE.COM's (CLAUDE.MAP), the stub's included."""
    for line in open(os.path.join(CL, 'CLAUDE.MAP')):
        p = line.split()
        if len(p) == 3 and p[2] == name: return int(p[1], 16)
    raise KeyError(name)

def stub_seg(k):
    """Resident Claude's stub, as INT 16h points at it."""
    return k.pc.u16(0, 0x16 * 4 + 2)

def mcbs(k):
    """The memory blocks: (MCB segment, owner, paragraphs, name)."""
    out, seg = [], k.u16('first_mcb')
    while True:
        t = k.pc.rd(seg, 0, 1)[0]
        out.append((seg, k.pc.u16(seg, 1), k.pc.u16(seg, 3), k.pc.rd(seg, 8, 8).split(b'\0')[0].decode('latin1')))
        if t != ord('M'): return out
        seg += k.pc.u16(seg, 3) + 1

def image(name, *files):
    return mkimg.build(os.path.join(OUT, name), [os.path.join(GOS, 'src', 'LODE.SYS'), os.path.join(GOS, 'src', 'LCMD.COM'),
                                                 os.path.join(HERE, 'MEMSZ.COM')] + [os.path.join(CL, f) for f in
                                                 ('RSPIKE.COM', 'EMSUSE.COM', 'GFXUSE.COM', 'CLAUDE.COM')] + list(files))

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)) if detail and not cond else ''))

def prompt(k, cmd, sim_s=6):
    k.key('cls'); k.key(ktest.ENTER); k.key(cmd); k.key(ktest.ENTER, settle=False); k.settle(sim_s)
    return k.pc.text_screen()

def memsz(k):
    m = re.search(r'([\d.]+) KB for programs', prompt(k, 'memsz'))
    return float(m.group(1)) if m else None

def click(k, x, y):
    """Move the pointer to (x, y) in the Executive and press the left button."""
    dx, dy = x - k.u16('mx'), y - k.u16('my')
    while dx or dy:
        sx, sy = max(-100, min(100, dx)), max(-100, min(100, dy))
        k.pc.mouse_move(sx & 0xFF, sy & 0xFF); k.pc.run_for(0.05)
        dx -= sx; dy -= sy
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.settle()

def glyphs():
    """The console's font, Terminus then CLAUDE's own glyphs (80h-A0h): {16 bytes: char}."""
    out = []
    for f in (os.path.join(GOS, 'src', 'TERMINUS.INC'), os.path.join(CL, 'GLYPHS.INC')):
        for line in open(f):
            line = line.split(';')[0].strip()
            if line.startswith('db'):
                out.append(bytes(int(x.strip().rstrip('hH'), 16) for x in line[2:].split(',')))
    return {g: chr(0x20 + i) for i, g in enumerate(out) if len(g) == 16}
GLYPH = glyphs()

def con_row(k, r):
    """Row r of resident Claude's console (8x16 cells, inverse or not), as text."""
    v = k.pc.rd(0xB800, 0, 0x8000)
    def ch(c):
        g = bytes(v[(i & 3) * 0x2000 + (i >> 2) * 80 + r * 320 + c] for i in range(16))
        return GLYPH.get(bytes(b ^ 0xFF for b in g)) or GLYPH.get(g) or '?'
    return ''.join(ch(c) for c in range(80))

def console(k):
    """Resident Claude's console up?  Mode 40h, its band on row 24, the rest blank."""
    if k.pc.mode() != 0x40: return False
    v = k.pc.rd(0xB800, 0, 0x8000)
    blank = all(not any(v[b * 0x2000 + (y >> 2) * 80:b * 0x2000 + (y >> 2) * 80 + 80]) for y in range(0, 384, 4) for b in range(4))
    return blank and 'Claude (resident)' in con_row(k, 24)

K16 = r'''; K16.COM: INT 16h's other functions go on to the BIOS (resident Claude's
; stub and CLAUDE's key-script hook take 00h, 01h, 10h and 11h only): 02h and
; 12h give the shift state (40:17h), 04h-80h come back as they were asked;
; then two keys, read with AH=00h and 10h.  Exit code: the calls that came
; back otherwise.
cpu 286
org 100h
        mov     si, fns
.f:     lodsb
        or      al, al
        jz      .k
        mov     ah, al
        mov     al, 0A5h
        mov     bx, ax
        int     16h
        cmp     ah, bh
        jne     .bad
        mov     cl, 0A5h
        test    bh, 0EDh                ; (02h, 12h: the shift state)
        jnz     .c
        push    es
        push    40h
        pop     es
        mov     cl, [es:17h]
        pop     es
.c:     cmp     al, cl
        je      .f
.bad:   inc     byte [bad]
        jmp     .f
.k:     xor     ah, ah
        int     16h
        mov     ah, 10h
        int     16h
        mov     dx, s_ok
        cmp     byte [bad], 0
        je      .p
        mov     dx, s_bad
.p:     mov     ah, 9
        int     21h
        mov     al, [bad]
        mov     ah, 4Ch
        int     21h
fns     db      02h, 12h, 04h, 08h, 20h, 40h, 80h, 0
bad     db      0
s_ok    db      'K16: ok', 13, 10, '$'
s_bad   db      'K16: bad', 13, 10, '$'
'''

KEYPK = r'''; KEYPK.COM: every key through an INT 16h AH=01h peek first, then read
; (AH=00h) and shown; Esc ends.
cpu 286
org 100h
        mov     dx, msg
        mov     ah, 9
        int     21h
.l:     mov     ah, 1
        int     16h
        jz      .l
        xor     ah, ah
        int     16h
        cmp     al, 1Bh
        je      .x
        mov     ah, 0Eh
        int     10h
        jmp     .l
.x:     mov     ax, 4C00h
        int     21h
msg     db      'KEYPK ready: $'
'''

def asm(name, src):
    """NAME.COM, assembled here (OUT) from src"""
    s, com = os.path.join(OUT, name + '.ASM'), os.path.join(OUT, name + '.COM')
    open(s, 'w').write(src)
    subprocess.run(['nasm', '-f', 'bin', '-o', com, s], check=True)
    return com

def k16(): return asm('K16', K16)

def run_el(k, cmd):
    """A command at the prompt -> (its screen, its exit code: 0, 1 or 2 and more)."""
    o = prompt(k, cmd + ' && echo EL0 || if errorlevel 2 echo EL2')
    lines = [l.strip() for l in o.split('\n')]                    # (not the typed line, which names both)
    return o, 0 if 'EL0' in lines else 2 if 'EL2' in lines else 1

# ---- resident Claude, M1: CLAUDE /R and CLAUDE /U --------------------------
SEMI = 0x2700                                   # CODE-; : enhanced-only, as CODE-\ (raw 27F0h)

def t_rload():
    """CLAUDE /R loads (4 EMS pages, the stub), says so when it is there
    already or there is no EMS; CLAUDE /U takes it out, or says why not."""
    def handles():                              # EMS handles in use (the kernel's table; 0 is its own)
        t = k.rd('ems_h', 4 * 32)
        return sum(1 for i in range(1, 32) if t[4 * i] != 0xFF)
    real = {}                                   # (CLAUDE.MAP's first column: where it is in CLAUDE.COM)
    for line in open(os.path.join(CL, 'CLAUDE.MAP')):
        p = line.split()
        if len(p) != 3: continue
        try: real[p[2]] = int(p[0], 16)
        except ValueError: pass
    check('CLAUDE.COM: what only /R and /U use (the loader, the console, the stub) is where BSS goes, below '
          'the stack /R runs on', real['bss'] <= real['res_load'] < real['rcon_img'] < real['r_code_end'] < csym('stack_top') - 2048,
          [(n, hex(real[n])) for n in ('bss', 'res_load', 'rcon_img', 'r_code_end', 'stack_top')])
    k = ktest.KPC(image('rl.img', 'HOOK16.COM=' + os.path.join(CL, 'HOOK16.COM')), ems_pages=88); k.start()
    k.key(ktest.CODE_P)
    m0, h0 = memsz(k), handles()
    o, el = run_el(k, 'claude /r')
    m1 = memsz(k)
    check('CLAUDE /R: resident, exit code 0', 'Claude is resident: CODE-\\' in o and el == 0, (el, o))
    blk = [b[2] for b in mcbs(k) if b[1] == 8 and b[3] == 'CLAUDE']
    check('... the stub\'s block: 61 paragraphs and its MCB, 992 bytes (63 till the 2026-10-26 audit\'s R44 and R45)',
          blk == [61] == [(csym('r_stack_top') - 0x100 + 15) // 16], blk)
    check('... its EMS handle kept after CLAUDE.COM ended (asked for from the stub: no program\'s)', handles() == h0 + 1,
          (h0, handles()))
    check('... at the prompt it costs DOS programs %.1f KB (the plan\'s target: 1.2 KB)' % ((m0 or 0) - (m1 or 0)),
          m0 and m1 and 0 < m0 - m1 <= 1.2, (m0, m1))
    o, el = run_el(k, 'claude /r')
    check('CLAUDE /R again: "resident already", exit code 2, nothing more kept', 'resident already' in o and el == 2 and memsz(k) == m1,
          (el, o))
    o, el = run_el(k, 'claude /u')
    check('CLAUDE /U: taken out, exit code 0, the memory and the EMS handle back (%s KB)' % memsz(k),
          'no longer resident' in o and el == 0 and memsz(k) == m0 and handles() == h0, (el, o, memsz(k), m0, handles(), h0))
    prompt(k, 'emsuse'); k.key(HOT)
    up = console(k)
    k.key(ktest.ESC)
    check('... CODE-\\ does nothing then (INT 16h is the BIOS\'s again)', not up and 'EMSUSE: 0 keys, 0 bad' in k.pc.text_screen(),
          k.pc.text_screen())
    o, el = run_el(k, 'claude /u')
    check('CLAUDE /U when it isn\'t resident: says so, exit code 1', "isn't resident" in o and el == 1, (el, o))
    run_el(k, 'claude /r'); run_el(k, 'hook16')
    o, el = run_el(k, 'claude /u')
    check('CLAUDE /U under a program loaded after it (HOOK16 has INT 16h): refused, exit code 2, still resident',
          "can't be taken out" in o and el == 2 and 'resident already' in prompt(k, 'claude /r'), (el, o))
    k = ktest.KPC(image('rl0.img')); k.start()
    k.key(ktest.CODE_P)
    m0 = memsz(k)
    o, el = run_el(k, 'claude /r')
    check('no EMS: CLAUDE /R says it needs EMS, exit code 1, nothing kept', 'needs EMS' in o and el == 1 and memsz(k) == m0, (el, o))

def t_rems():
    """The console over a program that keeps its own pages in all four EMS
    windows, reading keys with AH=00h and with AH=10h; the keys typed ahead
    of CODE-\\ still reach it; CODE-\\ behind another enhanced-only key."""
    k = ktest.KPC(image('rems.img'), ems_pages=88); k.start()
    k.key(ktest.CODE_P)
    prompt(k, 'claude /r')
    for flag, how in (('', 'AH=00h'), (' /x', 'AH=10h')):
        prompt(k, 'emsuse' + flag)
        k.key('a')
        text0 = k.pc.text_screen()
        k.key(HOT)
        up = console(k)
        band = con_row(k, 24)
        k.key(HOT)
        back = k.pc.mode() == 3 and k.pc.text_screen() == text0
        k.key('b'); k.key(ktest.ESC)
        o = k.pc.text_screen()
        check('EMSUSE reading keys with %s: CODE-\\ brings up the console (Term\'s rows blank, its band), CODE-\\ its screen back'
              % how, up and back, (up, band, k.pc.mode(), o))
        check('... its four EMS pages in all four windows: still there, whole; the band doesn\'t say DOS is busy',
              'EMSUSE: 2 keys, 0 bad' in o and 'DOS busy' not in band, (o, band))
    prompt(k, 'emsuse')
    k.key('a')
    k.key('x', settle=False); k.key('y', settle=False); k.key(HOT)
    up = console(k)
    k.key(HOT); k.key(ktest.ESC)
    o = k.pc.text_screen()
    check('keys typed ahead of CODE-\\ (x y): the console up, and they reach the program afterwards, not the console',
          up and 'EMSUSE: 3 keys, 0 bad' in o, (up, o))
    prompt(k, 'emsuse')
    k.key(SEMI, settle=False); k.key(HOT)
    up = console(k)
    k.key(HOT); k.key(ktest.ESC)
    check('CODE-\\ behind another enhanced-only key (CODE-;) under an AH=00h reader: still seen (the BIOS would drop both)',
          up and 'EMSUSE: 0 keys, 0 bad' in k.pc.text_screen(), (up, k.pc.text_screen()))

def t_rother():
    """INT 16h's other functions (02h, 12h, 04h-80h) go through the stub to
    the BIOS, and come back at once; its reads still give the keys."""
    k = ktest.KPC(image('roth.img', 'K16.COM=' + k16()), ems_pages=88); k.start()
    k.key(ktest.CODE_P)
    prompt(k, 'claude /r')
    k.key('cls'); k.key(ktest.ENTER); k.key('k16'); k.key(ktest.ENTER, settle=False); k.settle(3)
    k.key('ab'); k.settle(3)
    o = k.pc.text_screen()
    check('K16 under the stub: AH=02h and 12h give the shift state, 04h-80h come back as asked, then two keys read',
          'K16: ok' in o, o)

def t_rpoll():
    """CODE-\\ under a program that polls (KEYPK: AH=01h, then AH=00h), typed
    at many moments of its loop: the console always comes.  (The BIOS's
    AH=01h drops CODE-\\ at the head of the buffer; one typed after the
    stub's look, before the BIOS's, went.)"""
    k = ktest.KPC(image('rpoll.img', 'KEYPK.COM=' + asm('KEYPK', KEYPK)), ems_pages=88); k.start()
    k.key(ktest.CODE_P)
    prompt(k, 'claude /r')
    k.key('cls'); k.key(ktest.ENTER); k.key('keypk'); k.key(ktest.ENTER, settle=False); k.settle(3)
    missed = []
    for i in range(24):
        k.pc.run_for(0.0013 * i + 0.0005)
        k.key(HOT, settle=False)
        if not k.pc.run_until(lambda: console(k), 3):
            missed.append(i)
            continue
        k.key(HOT, settle=False)
        k.pc.run_until(lambda: k.pc.mode() == 3, 3)
    k.key('a'); k.key(ktest.ESC)
    check('CODE-\\ under KEYPK at 24 moments of its peek loop: the console came each time, and back', not missed
          and 'KEYPK ready: a' in k.pc.text_screen(), (missed, k.pc.text_screen()[:200]))

def t_rvideo():
    """The console over CGA graphics, the 640x400 mode and text: the screen
    and the BIOS's video data come back byte for byte."""
    k = ktest.KPC(image('rvid.img'), ems_pages=88); k.start()
    k.key(ktest.CODE_P)
    prompt(k, 'claude /r')
    for mode in ('4', '6', '40', '3'):
        k.key('cls'); k.key(ktest.ENTER); k.key('gfxuse ' + mode); k.key(ktest.ENTER)
        vram0, bios0 = k.pc.rd(0xB800, 0, 0x8000), k.pc.rd(0x40, 0x49, 30)
        ccr0 = k.pc.ccr
        k.key(HOT)
        up = console(k)
        writes = []                     # the colour register going back: (value, the screen back yet?)
        k.pc.on_ccr = lambda v: writes.append((v, k.pc.rd(0xB800, 0, 0x8000) == vram0))
        k.key(HOT)
        k.pc.on_ccr = None; ccr1 = k.pc.ccr
        same = k.pc.rd(0xB800, 0, 0x8000) == vram0 and k.pc.rd(0x40, 0x49, 30) == bios0
        k.key('x'); k.key(ktest.ESC)
        o = k.pc.text_screen()
        check('mode %s: the console and back, video memory and 40:49h-66h byte for byte' % mode,
              up and same and 'GFXUSE: 1 keys, 0 bad' in o, (up, same, o))
        if mode != '40':                # (CGA: 3D9h; GFXUSE sets 2Ch in 4 and 6, the mode set 30h in 3)
            check('mode %s: the colour register back (%02Xh) before the screen (mode 6 came back white for a '
                  'moment on the 1520)' % (mode, ccr0),
                  ccr1 == ccr0 and writes and not any(back for v, back in writes), (hex(ccr1), writes))

def t_rdos():
    """The console while DOS is busy under the program (the prompt's COPY
    CON reads the keyboard through INT 21h): at the kernel's key wait, where
    the console may call DOS (files), so its band doesn't say DOS busy; and
    DOS carries on."""
    k = ktest.KPC(image('rdos.img'), ems_pages=88); k.start()
    k.key(ktest.CODE_P)
    prompt(k, 'claude /r')
    k.key('cls'); k.key(ktest.ENTER); k.key('copy con hi.txt'); k.key(ktest.ENTER)
    text0 = k.pc.text_screen()
    k.key(HOT)
    up, band = console(k), con_row(k, 24)
    k.key(HOT)
    back = k.pc.text_screen() == text0
    k.key('hi'); k.key(ktest.ENTER); k.key(0x2C1A); k.key(ktest.ENTER)
    o = prompt(k, 'type hi.txt')
    check('the console over COPY CON (DOS reading the keyboard, the kernel\'s key wait: files work there): its band '
          'doesn\'t say DOS is busy', up and 'DOS busy' not in band, (up, band))
    check('... and back: the screen as it was, then COPY CON goes on (the file has what was typed)',
          back and 'hi' in [l.strip() for l in o.split('\n')], (back, o))

def t_rexec():
    """The console over the Executive (its UI reads keys with AH=11h), the
    mouse meanwhile, and what CLAUDE /R costs a program the Executive runs."""
    k = ktest.KPC(image('rex.img'), ems_pages=88); k.pc.mouse = True; k.start()
    def exec_memsz():
        if any('Press any key' in l for l in k.band()): k.key(ktest.ESC)     # ("LCMD.COM ended")
        m = re.search(r'([\d.]+) KB for programs', k.run_file('MEMSZ.COM', 20))
        return float(m.group(1)) if m else None
    m0 = exec_memsz()
    k.key(ktest.CODE_P)
    prompt(k, 'claude /r')
    k.key('exit'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    m1 = exec_memsz()
    lst = k.exec_list()
    check('... the Executive lists its files after the stub moved in', 'EMSUSE.COM' in lst and 'CLAUDE.COM' in lst, lst)
    check('loaded at the prompt, then from the Executive: a program gets %.1f KB less (the stub at the top of memory: the '
          'Executive\'s block stays where it was)' % ((m0 or 0) - (m1 or 0)), m0 and m1 and 0 < m0 - m1 <= 1.2, (m0, m1))
    k.select('EMSUSE.COM')
    vram0, sel = k.pc.rd(0xB800, 0, 0x8000), k.u16('sel')
    k.key(HOT)
    up = console(k)
    con0 = k.pc.rd(0xB800, 0, 0x8000)
    for d in (20, 20, 20, -60 & 0xFF):                # (and back where it was, so the
        k.pc.mouse_move(d, d); k.pc.run_for(0.05)       #  Executive's pointer is too)
    k.settle()
    still = k.pc.rd(0xB800, 0, 0x8000) == con0
    k.key(HOT)
    same = k.pc.rd(0xB800, 0, 0x8000) == vram0
    k.key(ktest.DOWN)
    check('over the Executive: the console and back, its screen byte for byte, it goes on', up and same and k.u16('sel') == sel + 1,
          (up, same, sel, k.u16('sel')))
    check('... the mouse moved meanwhile draws nothing on the console', still, still)
    click(k, 40, 24 + 8)
    check('... and its mouse works with the hook in place (a click selects, no key pressed)', k.u16('sel') == 0, k.u16('sel'))
    k.key(ktest.CODE_P)
    o, el = run_el(k, 'claude /u')
    k.key('exit'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    m2 = exec_memsz()
    check('CLAUDE /U at a later prompt: taken out, and a program from the Executive gets all of it back (%s KB)' % m2,
          el == 0 and m2 == m0, (el, o, m2, m0))

def t_rtm5000g():
    """The console over TM5000G while it polls the keyboard, the mouse and
    the bus (the 7210 model): its polling with no key pressed, the console
    and back, and the bus afterwards."""
    if not TM5000G:
        print('(no TM5000G.EXE: skipped)'); return
    chip = sim7210.NEC7210(sim7210.bus())
    k = ktest.KPC(image('rtm.img', 'TM5000G.EXE=' + TM5000G), chip=chip, ems_pages=88); k.pc.mouse = True; k.start()
    k.key(ktest.CODE_P)
    prompt(k, 'claude /r')
    k.key('cls'); k.key(ktest.ENTER); k.key('tm5000g'); k.key(ktest.ENTER, settle=False); k.settle(40)
    k.key(ktest.ENTER)
    check('TM5000G runs with Claude resident (main menu)', 'TM5000 CONTROL SYSTEM' in k.pc.text_screen(), k.pc.text_screen())
    for i in range(4): k.pc.mouse_move(0, -28 & 0xFF); k.pc.run_for(0.05)
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.settle(5)
    check('TM5000G\'s mouse with the hook: a click on "Configure Modules" opens it (no key pressed)',
          'Module Configuration' in k.pc.text_screen(), k.pc.text_screen()[:300])
    k.key('A', settle=False); k.settle(60)
    scr = k.pc.text_screen()
    check('... auto-detect goes through all 30 addresses with no key pressed', '-> slot 0 (new)' in scr and '-> slot 1 (new)' in scr, scr)
    k.key('Y'); k.key(ktest.ENTER); k.key(ktest.ESC)
    text0 = k.pc.text_screen()
    check('TM5000G finds and configures its modules', 'Active Modules: S0, S1' in text0, text0)
    k.key(SEMI, settle=False); k.key(HOT)
    up = console(k)
    k.key(HOT)
    check('CODE-\\ over TM5000G (its kbhit: AH=01h), even behind CODE-;: the console, then its screen back as it was',
          up and k.pc.text_screen() == text0, (up, k.pc.text_screen()))
    # its mouse pointer is INT 33h's, drawn in text mode from the mouse's IRQ: hidden while the console
    # is up, so a move then neither draws on the console nor leaves a wrong cell on TM5000G's screen
    vram0 = k.pc.rd(0xB800, 0, 4000)
    k.key(HOT)
    con0 = k.pc.rd(0xB800, 0, 0x8000)
    for _ in range(2): k.pc.mouse_move(16, 16); k.pc.run_for(0.05)
    k.settle()
    clean = k.pc.rd(0xB800, 0, 0x8000) == con0
    k.key(HOT)
    for _ in range(2): k.pc.mouse_move(-16 & 0xFF, -16 & 0xFF); k.pc.run_for(0.05)
    k.settle()
    check('TM5000G\'s mouse moved while the console is up: nothing drawn on the console, and moved back afterwards, '
          'TM5000G\'s screen exactly as before (its pointer included)', clean and k.pc.rd(0xB800, 0, 4000) == vram0,
          (clean, [(i // 160, i % 160) for i in range(4000) if k.pc.rd(0xB800, 0, 4000)[i] != vram0[i]][:8]))
    k.key('1'); k.key('A', settle=False); k.settle(60)
    scr = k.pc.text_screen()
    check('TM5000G talks to the bus as before: auto-detect finds FG5010, 8753D, DC5009 again (no key pressed)',
          all(x in scr for x in ('FG5010', '8753D', 'DC5009')) and scr.count('already set up') == 2, scr)

def t_rirq():
    """CODE-\\ while a TSR looks at the keyboard from INT 1Ch (inside the
    timer's interrupt: the BIOS's INT 08h calls it before its EOI) and the
    program is busy: the console waits for a key call made with no
    interrupt in service, where the keyboard can still come."""
    k = ktest.KPC(image('rirq.img', 'T1C.COM=' + os.path.join(CL, 'T1C.COM'), 'BUSY.COM=' + os.path.join(CL, 'BUSY.COM')),
                  ems_pages=88); k.start()
    k.key(ktest.CODE_P)
    prompt(k, 'claude /r')
    o = prompt(k, 't1c')
    check('T1C loads (INT 1Ch looks at the keyboard)', 'T1C resident' in o, o)
    isr_up = []
    k.hooks.append(lambda pc: pc.r('cs') == 0xE000 and pc.r('ip') == 0 and isr_up.append(pc.isr))
    k.key('cls'); k.key(ktest.ENTER); k.key('busy'); k.key(ktest.ENTER, settle=False)
    k.pc.run_for(0.5)
    k.key(HOT, settle=False)
    k.pc.run_for(1.0)
    stub = stub_seg(k)
    pend, ring = k.pc.rd(stub, csym('r_pend'), 1)[0], k.pc.kbd_ring()
    check('CODE-\\ during BUSY, seen from INT 1Ch: no console inside the timer\'s interrupt; CODE-\\ taken, the console to come',
          not isr_up and k.pc.mode() == 3 and pend == 1 and not {0x2BF0, 0x2B00} & set(ring),
          (isr_up, k.pc.mode(), pend, [hex(w) for w in ring]))
    k.settle(10)
    up = console(k)
    check('... when BUSY is done, the prompt\'s next key call brings it up, with no interrupt in service',
          up and isr_up == [0] and 'BUSY: done' in ''.join(k.pc.tty) + k.pc.text_screen(), (up, isr_up))
    k.key(HOT)
    check('... and CODE-\\ goes back', k.pc.mode() == 3 and not console(k), k.pc.mode())

def t_rmouse():
    """A program's INT 33h event handler is swapped out while the console
    is up (clicks then are the console's, and nothing runs on the stub's
    stack), and back afterwards."""
    k = ktest.KPC(image('rmouse.img', 'MHAND.COM=' + os.path.join(CL, 'MHAND.COM')), ems_pages=88)
    k.pc.mouse = True; k.start()
    k.key(ktest.CODE_P)
    prompt(k, 'claude /r')
    def click():
        k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.pc.run_for(0.05)
    def calls(o):
        m = re.search(r'MHAND: (\d+) calls', o)
        return int(m.group(1)) if m else None
    prompt(k, 'mhand')
    click(); k.settle()
    k.key(ktest.ESC)
    one = calls(k.pc.text_screen())
    prompt(k, 'mhand')
    k.key(HOT)
    up = console(k)
    for _ in range(3): click()
    k.settle()
    k.key(HOT)
    click(); k.settle()
    k.key(ktest.ESC)
    got = calls(k.pc.text_screen())
    check('MHAND\'s handler: %s calls for a click; over the console, 3 clicks there and 1 after: %s calls, the one after\'s'
          % (one, got), up and one and got == one, (up, one, got, k.pc.text_screen()))

def t_rversion():
    """CLAUDE /R and /U from a CLAUDE.COM whose stub is laid out otherwise
    (another version): they find the stub by its header."""
    k = ktest.KPC(image('rver.img', 'CLAUDEP.COM=' + os.path.join(OUT, 'CLAUDEP.COM'),
                        'CLAUDEV1.COM=' + os.path.join(OUT, 'CLAUDEV1.COM'), 'HOOK16.COM=' + os.path.join(CL, 'HOOK16.COM')),
                  chip=sim7210.NEC7210(sim7210.bus()), ems_pages=88); k.start()     # (the GPIB, so CLAUDE runs)
    k.key(ktest.CODE_P)
    before = memsz(k)
    prompt(k, 'claude /r')
    o, el = run_el(k, 'claudep /r')
    check('another version\'s CLAUDE /R: resident already (exit code 2), no second copy', el == 2 and 'already' in o, (el, o))
    o, el = run_el(k, 'claudep /u')
    check('another version\'s CLAUDE /U: taken out (0), all its memory back',
          el == 0 and 'no longer resident' in o and memsz(k) == before, (el, o, before, memsz(k)))
    prompt(k, 'claudep /r')
    o, el = run_el(k, 'claude /u')
    check('... and the other way round', el == 0 and memsz(k) == before, (el, o, memsz(k)))
    # CLAUDE.COM turns the hot key off (r_off, 10Eh) only in a stub of version 2 on: in version 1's,
    # 10Eh is r_pend, and writing it would bring the console up over CLAUDE at its next key call
    def claude_run(ver_name):
        prompt(k, ver_name + ' /r')
        stub = stub_seg(k)
        k.key('cls'); k.key(ktest.ENTER); k.key('claude'); k.key(ktest.ENTER, settle=False); k.settle(5)
        during = (k.pc.mode(), k.pc.rd(stub, 0x10D, 2))
        k.key(0x1000); k.key(0x1000); k.settle(5)              # CODE-Q (twice, should it be busy)
        after = (k.pc.mode(), k.pc.rd(stub, 0x10D, 2))
        prompt(k, 'claude /u')
        return during, after
    during, after = claude_run('claudev1')
    check('CLAUDE over a version 1 stub (no r_off): its 10Dh-10Eh (r_inpop, r_pend) left as they were while it runs',
          during == (0x40, b'\0\0') and after == (3, b'\0\0'), (during, after))
    during, after = claude_run('claude')
    check('... over its own (version 5; r_off since 2): r_off (10Eh) set while CLAUDE runs, cleared when it ends',
          during == (0x40, b'\0\x01') and after == (3, b'\0\0'), (during, after))
    # under a TSR that hooked INT 16h after CLAUDE /R (HOOK16), CLAUDE.COM finds the stub among the memory
    # blocks all the same (through INT 16h it wouldn't, and CODE-\ in CLAUDE would bring the console up)
    prompt(k, 'claude /r')
    stub = stub_seg(k)
    o = prompt(k, 'hook16')
    k.key('cls'); k.key(ktest.ENTER); k.key('claude'); k.key(ktest.ENTER, settle=False); k.settle(5)
    during = (k.pc.mode(), k.pc.rd(stub, 0x10D, 2))
    k.key(HOT); k.settle(2)
    hot = k.pc.rd(stub, 0x10D, 2)
    k.key(0x1000); k.key(0x1000); k.settle(5)
    after = (k.pc.mode(), k.pc.rd(stub, 0x10D, 2))
    check('under a TSR that hooked INT 16h after it (HOOK16): CLAUDE finds the stub all the same, r_off set while '
          'it runs (CODE-\\ there brings no console) and cleared when it ends',
          'HOOK16 resident' in o and stub_seg(k) != stub and during == (0x40, b'\0\x01') and hot == b'\0\x01'
          and after == (3, b'\0\0'), (o, during, hot, after))

def t_rhole():
    """A free hole lower down that the stub would fit in: the stub still
    goes to the top of memory."""
    k = ktest.KPC(image('rhole.img', 'HOLE.COM=' + os.path.join(CL, 'HOLE.COM')), ems_pages=88); k.start()
    k.key(ktest.CODE_P)
    o = prompt(k, 'hole')
    check('HOLE leaves 160 paragraphs free below a block it keeps', 'HOLE: 160 paragraphs free' in o, o)
    prompt(k, 'claude /r')
    blocks = mcbs(k)
    i = next((n for n, b in enumerate(blocks) if b[1] == 8 and b[3] == 'CLAUDE'), None)
    holes = [b for b in blocks[:i or 0] if b[1] == 0 and b[2] >= (csym('r_stack_top') - 0x100 + 15) // 16]
    check('CLAUDE /R with that hole: the stub\'s block is the top one (free memory only above it)',
          i is not None and all(b[1] == 0 for b in blocks[i + 1:]) and holes,
          [(hex(s), o_, n, nm) for s, o_, n, nm in blocks])

TESTS = [t_rload, t_rems, t_rother, t_rpoll, t_rvideo, t_rdos, t_rexec, t_rtm5000g,
         t_rirq, t_rmouse, t_rversion, t_rhole]
if __name__ == '__main__':
    build()
    want = sys.argv[1:]
    for t in TESTS:
        if want and t.__name__[2:] not in want: continue
        print('==', t.__name__[2:])
        t0 = time.time(); t(); print('   (%.1f s)' % (time.time() - t0))
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s' % (len(results), len(bad), (': ' + ', '.join(bad)) if bad else ''))
    sys.exit(1 if bad else 0)
