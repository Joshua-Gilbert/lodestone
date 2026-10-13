"""Resident Claude, the spikes (RSPIKE.COM, os/claude): its pop-up's code
runs from an EMS page of its own over programs that use all four EMS
windows, over graphics and text modes and the Executive, and over TM5000G
while it talks to instruments.

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
    for n in ('RSPIKE', 'EMSUSE', 'GFXUSE'):
        subprocess.run(['nasm', '-f', 'bin', '-o', os.path.join(CL, n + '.COM'), os.path.join(CL, n + '.ASM')], check=True)
    for d, n in ((os.path.join(GOS, 'src'), 'LCMD'), (HERE, 'MEMSZ')):
        subprocess.run(['nasm', '-f', 'bin', '-o', n + '.COM', n + '.ASM'], check=True, cwd=d)   # (its includes)

def image(name, *files):
    return mkimg.build(os.path.join(OUT, name), [os.path.join(GOS, 'src', 'LODE.SYS'), os.path.join(GOS, 'src', 'LCMD.COM'),
                                                 os.path.join(HERE, 'MEMSZ.COM')] + [os.path.join(CL, f) for f in
                                                 ('RSPIKE.COM', 'EMSUSE.COM', 'GFXUSE.COM')] + list(files))

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

def popped(k):
    """The pop-up on the screen?  (mode 40h, its lines written through the
    BIOS: pcemu logs them rather than draw them in mode 40h)"""
    return k.pc.mode() == 0x40 and 'Resident spike: pop-up' in ''.join(k.pc.tty)[-400:]

def t_ems():
    """Spike 1: code in the EMS frame over a program that keeps its own
    pages in all four windows."""
    k = ktest.KPC(image('ems.img'), ems_pages=88); k.start()
    k.key(ktest.CODE_P)
    before = memsz(k)
    o = prompt(k, 'rspike')
    after = memsz(k)
    check('RSPIKE loads (EMS found, 3 pages)', 'RSPIKE resident' in o, o)
    check('... and keeps under 1 KB of conventional memory (%.1f KB)' % ((before or 0) - (after or 0)),
          before and after and 0 < before - after <= 1.0, (before, after))
    for flag, how in (('', 'AH=00h'), (' /x', 'AH=10h')):
        prompt(k, 'emsuse' + flag)
        k.key('a')
        text0 = k.pc.text_screen()
        k.key(HOT)
        up = popped(k)
        k.key(HOT)
        back = k.pc.mode() == 3 and k.pc.text_screen() == text0
        k.key('b'); k.key(ktest.ESC)
        o = k.pc.text_screen()
        check('EMSUSE reading keys with %s: CODE-\\ pops up, CODE-\\ goes back to its screen as it was' % how, up and back,
              (up, k.pc.mode(), o))
        check('... its four EMS pages in all four windows: still there, whole', 'EMSUSE: 2 keys, 0 bad' in o, o)

def t_video():
    """Spike 3: the screen and the BIOS's video data come back after a
    pop-up, in CGA graphics, the 640x400 mode and text."""
    k = ktest.KPC(image('vid.img'), ems_pages=88); k.start()
    k.key(ktest.CODE_P)
    prompt(k, 'rspike')
    for mode in ('4', '6', '40', '3'):
        k.key('cls'); k.key(ktest.ENTER); k.key('gfxuse ' + mode); k.key(ktest.ENTER)
        vram0, bios0 = k.pc.rd(0xB800, 0, 0x8000), k.pc.rd(0x40, 0x49, 30)
        k.key(HOT)
        up = popped(k)
        k.key(HOT)
        same = k.pc.rd(0xB800, 0, 0x8000) == vram0 and k.pc.rd(0x40, 0x49, 30) == bios0
        k.key('x'); k.key(ktest.ESC)
        o = k.pc.text_screen()
        check('mode %s: pop-up and back, video memory and 40:49h-66h byte for byte' % mode, up and same and 'GFXUSE: 1 keys, 0 bad' in o,
              (up, same, o))

def t_exec():
    """Over the Executive (its UI reads keys with AH=11h)."""
    k = ktest.KPC(image('ex.img'), ems_pages=88); k.pc.mouse = True; k.start()
    k.key(ktest.CODE_P)
    prompt(k, 'rspike')
    k.key('exit'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    k.key(ktest.DOWN)
    vram0, sel = k.pc.rd(0xB800, 0, 0x8000), k.u16('sel')
    k.key(HOT)
    up = popped(k)
    k.key(HOT)
    same = k.pc.rd(0xB800, 0, 0x8000) == vram0
    k.key(ktest.DOWN)
    check('over the Executive: pop-up and back, its screen byte for byte, it goes on', up and same and k.u16('sel') == sel + 1,
          (up, same, sel, k.u16('sel')))
    check('... the Executive lists its files after the TSR moved in', 'RSPIKE.COM' in k.exec_list(), k.exec_list())
    # its key checks (AH=11h) go through the hook and must not wait there:
    # a click with no key pressed
    click(k, 40, 24 + 8)
    check('... and its mouse works with the hook in place (a click selects, no key pressed)', k.u16('sel') == 0, k.u16('sel'))

def t_tm5000g():
    """Spike 2: a pop-up over TM5000G that talks to an instrument itself
    (INT 60h), and TM5000G carries on with the bus."""
    if not TM5000G:
        print('(no TM5000G.EXE: skipped)'); return
    chip = sim7210.NEC7210(sim7210.bus())
    k = ktest.KPC(image('tm.img', 'TM5000G.EXE=' + TM5000G), chip=chip, ems_pages=88); k.pc.mouse = True; k.start()
    k.key(ktest.CODE_P)
    o = prompt(k, 'rspike /g:6')
    check('RSPIKE /G:6 loads', 'RSPIKE resident' in o, o)
    k.key('cls'); k.key(ktest.ENTER); k.key('tm5000g'); k.key(ktest.ENTER, settle=False); k.settle(40)
    k.key(ktest.ENTER)
    check('TM5000G runs (main menu)', 'TM5000 CONTROL SYSTEM' in k.pc.text_screen(), k.pc.text_screen())
    # TM5000G polls the keyboard (kbhit: INT 16h AH=01h through the hook)
    # between its mouse reads and its GPIB probes: a peek must not wait
    for i in range(4): k.pc.mouse_move(0, -28 & 0xFF); k.pc.run_for(0.05)
    k.pc.mouse_move(0, 0, 1); k.pc.run_for(0.05); k.pc.mouse_move(0, 0, 0); k.settle(5)
    check('TM5000G\'s mouse with RSPIKE loaded: a click on "Configure Modules" opens it', 'Module Configuration' in k.pc.text_screen(),
          k.pc.text_screen()[:300])
    k.key('A', settle=False); k.settle(60)
    scr = k.pc.text_screen()
    check('... auto-detect goes through all 30 addresses with no key pressed (its table: FG5010 and DC5009 new)',
          '-> slot 0 (new)' in scr and '-> slot 1 (new)' in scr, scr)
    k.key('Y'); k.key(ktest.ENTER); k.key(ktest.ESC)
    text0 = k.pc.text_screen()
    check('TM5000G finds and configures its modules', 'Active Modules: S0, S1' in text0, text0)
    k.key(HOT)
    tty = ''.join(k.pc.tty)[-400:]
    check('CODE-\\ over TM5000G: the pop-up asks the FG5010 at 6 itself', popped(k) and 'GPIB 6 says: ID TEK/FG5010' in tty, tty)
    k.key(HOT)
    check('... CODE-\\: TM5000G\'s screen back as it was', k.pc.text_screen() == text0, k.pc.text_screen())
    k.key('1'); k.key('A', settle=False); k.settle(60)
    scr = k.pc.text_screen()
    check('TM5000G talks to the bus as before: auto-detect finds FG5010, 8753D, DC5009 again (no key pressed)',
          all(x in scr for x in ('FG5010', '8753D', 'DC5009')) and scr.count('already set up') == 2, scr)

TESTS = [t_ems, t_video, t_exec, t_tm5000g]
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
