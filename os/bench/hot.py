"""How often each kernel address is entered by a taken jump, call, return or
interrupt (not by falling through), over workloads in pcemu.  On the 286 a
taken transfer to an odd address costs a fetch: plan.py places the pads.
    python3 bench/hot.py OUT.json WORKLOAD...      (from os/, after build.sh)
WORKLOAD: bench   BENCH.COM's ten tests (the real-drive timing model; minutes)
          shell   LCMD: DIR, TYPE (3 x 18 KB), COPY 60 KB and 18 KB, DEL
          exec    the Executive idling and moving, MEMSZ.COM, TESTDOS.COM
          claude  one CLAUDE.COM turn over the Pico link model
   the UI's (UICORE, EXEC: section ui; mostly for "ui_taken"):
          idle    the Executive idling (the clock), then the saver running
          list    the Executive's file list: cursor moves and scrolling
          menu    Write's right-click menus, and help (F1) there and in the Executive
          form    the Executive's forms (Tab, typing, ESC) and System's clock form
          drag    the calculator's window dragged by the mouse and by CODE-F7
          write   Write: typing, scrolling a long file
          calc    the calculator: sums typed and clicked
          system  System's screens
          term    MULTITASK=1: LCMD in a terminal window (DIR, TYPE), the
                  calculator over it (KMW's clipping gates)
          wclip   Write: drags, CODE-C, CODE-V, the menu's Cut, Paste, Erase
          tasks   MULTITASK=1: TASKS.RUN over three tasks (moves, CODE-B,
                  CODE-Z, F5)
   CLAUDE.COM's (after claude/build.sh; mostly for "cl_taken", "st_taken"):
          cchat   CLAUDE.COM on the kernel: chat turns over the Pico link model
          cfiles  ... file requests: reads, writes, a listing, info
          cops    ... a 22 KB file written and read back, then OPS_PROBE (every
                  file and GPIB request, their errors too)
          crun    ... RUNs: TESTKEY with a key script (waits, a snapshot), DIR captured
          cstub   CLAUDE /R's stub under programs that ask INT 16h: the
                  Executive (AH=11h), the prompt, EMSUSE (00h, 10h), TM5000G's
                  kbhit (01h) if tools/TM5000G.EXE is there
   resident Claude's console's (RCON over EMSUSE; "rc_taken"):
          rterm   Term: typing, a 60-line answer; a second pop-up
          rfiles  list, read, an 8 KB write, OPS_PROBE
          rbg     the background passes (a quiet bridge): idle looks, a read,
                  a write, SCREEN, a GPIB query
OUT.json: {"taken": {offset: count}, "falls": {offset: count}}, kernel .text
offsets (KSEG:offset) as in src/LODE.MAP, and "ui_taken", "ui_falls": section
ui's offsets (the UI segment, ui_seg, wherever it is: it is a block of its own,
on a paragraph, so an offset's parity is the address's; wait_ticks' polling,
which only waits, not counted); "cl_taken", "cl_falls": CLAUDE.COM's .text
offsets (from its PSP, up to bss: the start-up code not counted) and
"st_taken", "st_falls": the stub's (section rstub, from its CS), both as in
claude/CLAUDE.MAP's second column (each on a paragraph, so an offset's parity
is the address's); "rc_taken", "rc_falls": RCON's (claude/RCON.MAP), at
E000:0 while its page is in window 0; "ap_taken", "ap_falls": {name: {offset:
count}}, each .RUN's (apps/*.RUN), offsets in its image (as in its listing:
mkrun.py -l; the UI's workloads run them); all the workloads named add up.
Save src/LODE.MAP, claude/CLAUDE.MAP, RCON.MAP and the .RUNs' listings with
it: the offsets are that build's."""
import sys, os, re, json, struct, collections
GOS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in (GOS, os.path.join(GOS, 'tests'), os.path.join(GOS, 'bench')): sys.path.insert(0, d)
import pcemu, ktest, mkimg
SY = ktest.Syms()
LO, HI = 0x600, 0x600 + SY['lastdrv'] + 1       # the resident .text, linear
USEG, UEND = 0x600 + SY['ui_seg'], SY['ui_image_end']
SPIN0 = SY['wait_ticks']                        # (its polling loop and the tick calls in it: not counted)
SPIN1 = min(a for a in SY.ui_addrs if a > SPIN0 and '.' not in SY.ui_by_addr[a])
taken, falls = collections.Counter(), collections.Counter()
ui_taken, ui_falls = collections.Counter(), collections.Counter()
cl_taken, cl_falls = collections.Counter(), collections.Counter()
st_taken, st_falls = collections.Counter(), collections.Counter()
rc_taken, rc_falls = collections.Counter(), collections.Counter()

def csyms():
    """claude/CLAUDE.MAP: {section: {label: offset}} (the second column: where it runs)"""
    out, sec = collections.defaultdict(dict), None
    for l in open(os.path.join(GOS, 'claude', 'CLAUDE.MAP'), encoding='latin-1'):
        m = re.match(r'---- Section (\S+)', l)
        if m: sec = m.group(1); continue
        m = re.match(r'\s+([0-9A-F]+)\s+([0-9A-F]+)\s+(\S+)\s*$', l)
        if m and sec: out[sec][m.group(3)] = int(m.group(2), 16)
    return out
CY = csyms()
CL = [-1, -1, 0]                                # CLAUDE.COM's code, linear (from, to; its segment's base): set by the workloads
ST = [-1, -1, 0]                                # the stub's
def cl_at(psp): CL[:] = [psp * 16 + 0x100, psp * 16 + CY['.text']['bss'], psp * 16]
def st_at(seg): ST[:] = [seg * 16 + 0x100, seg * 16 + CY['rstub']['r_code_end'], seg * 16]
RC = [-1, -1, 0, None]                          # RCON's, and its page register (window 0)
def rc_at(reg, end): RC[:] = [0xE0000, 0xE0000 + end, 0xE0000, reg]

prev = [0, 0]
ui = [0, -1, -1, None]                          # (blocks to the next look at ui_seg, its base and end, linear; the PC)
ob = pcemu.PC.blk
def blk(s, uc, addr, size, ud):
    pa, ps = prev
    if addr != pa:                              # (a REP restarts its own block)
        if LO <= addr < HI:
            (falls if addr == pa + ps else taken)[addr - 0x600] += 1
        elif CL[0] <= addr < CL[1]:
            (cl_falls if addr == pa + ps else cl_taken)[addr - CL[2]] += 1
        elif ST[0] <= addr < ST[1]:
            (st_falls if addr == pa + ps else st_taken)[addr - ST[2]] += 1
        elif RC[0] <= addr < RC[1] and s.ems_reg[0] == RC[3]:
            (rc_falls if addr == pa + ps else rc_taken)[addr - RC[2]] += 1
        else:
            if ui[0] <= 0 or ui[3] is not s:    # (it moves only at the Executive's ui_room)
                seg = struct.unpack('<H', uc.mem_read(USEG, 2))[0]
                ui[:] = [4096, seg * 16 if seg else -1, seg * 16 + UEND if seg else -1, s]
            ui[0] -= 1
            if ui[1] <= addr < ui[2]:
                if not (SPIN0 <= pa - ui[1] < SPIN1 or SPIN0 <= addr - ui[1] < SPIN1):
                    (ui_falls if addr == pa + ps else ui_taken)[addr - ui[1]] += 1
            elif ui[1] > 0 and ui[2] <= addr < ui[1] + 0x10000:     # (past the UI's image: a .RUN's slot?)
                r = app_at(s, uc, addr)
                if r: (ap_falls if addr == pa + ps else ap_taken)[r[2]][addr - r[0]] += 1
    prev[0], prev[1] = addr, size
    return ob(s, uc, addr, size, ud)

# ---- the .RUNs' (apps/*.RUN; "ap_taken", "ap_falls": {name: {offset: count}}) ----
# A .RUN runs in the UI segment, at run_base (run_app) or, a window .RUN with
# MULTITASK=1, in its session's slot (KMW's mw_ses: SE_BASE, SE_NAME); both on
# a paragraph, so an offset in its image has the address's parity.  The
# regions are looked at again whenever a block lands outside them or on one's
# first byte (a .RUN started), so a slot used again is a new region
ap_taken, ap_falls = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
RUNS = {}                                       # (image, BSS) -> name; name -> image
for _n in ('SYSTEM', 'WRITE', 'CALC', 'TASKS', 'TERM'):
    try: _h = open(os.path.join(GOS, 'apps', _n + '.RUN'), 'rb').read(16)
    except OSError: continue
    RUNS[struct.unpack_from('<HH', _h, 6)] = _n; RUNS[_n] = struct.unpack_from('<H', _h, 6)[0]
def _equ(name):
    for l in open(os.path.join(GOS, 'src', 'LODE.MAP')):
        m = re.match(r'([0-9A-F]{8})\s+(\S+)\s*$', l)
        if m and m.group(2) == name: return int(m.group(1), 16)
SE_USE, SE_BASE, SE_NAME, SE_SIZE, MW_MAX = (_equ(n) for n in ('SE_USE', 'SE_BASE', 'SE_NAME', 'SE_SIZE', 'MW_MAX'))
AREG = [None, []]                               # (the PC they are for; [(base, end, name)], linear)
MTSEG = {}                                      # PC -> MT's block (its segment), once found

def mt_seg(s, uc):
    if s not in MTSEG:
        seg = struct.unpack('<H', uc.mem_read(0x600 + SY['first_mcb'], 2))[0]
        for _ in range(200):
            t, own, sz = struct.unpack('<BHH', uc.mem_read(seg * 16, 5))
            if uc.mem_read(seg * 16 + 8, 2) == b'MT' and own == 8: MTSEG[s] = seg + 1; break
            if t != 0x4D: break
            seg += sz + 1
        else: return None
    return MTSEG.get(s)

def app_regions(s, uc):
    u, out = ui[1], []
    rd = lambda a, n: bytes(uc.mem_read(a, n))
    if rd(u + SY['run_active'], 1)[0]:
        im, bss = struct.unpack('<HH', rd(u + SY['run_hdr'] + 6, 4))
        b = u + struct.unpack('<H', rd(u + SY['run_base'], 2))[0]
        if (im, bss) in RUNS: out.append((b, b + im, RUNS[(im, bss)]))
    ms = mt_seg(s, uc) if SE_SIZE else None
    if ms:
        for i in range(1, MW_MAX + 1):
            r = ms * 16 + SY['mw_ses'] + i * SE_SIZE
            if rd(r + SE_USE, 1)[0]:
                n = rd(r + SE_NAME, 12).split(b'\0')[0].decode('latin-1').upper()
                n = n[:-4] if n.endswith('.RUN') else n
                b = u + struct.unpack('<H', rd(r + SE_BASE, 2))[0]
                if n in RUNS: out.append((b, b + RUNS[n], n))
    AREG[:] = [s, out]

def app_at(s, uc, addr):
    if AREG[0] is s:
        for r in AREG[1]:
            if r[0] < addr < r[1]: return r
    app_regions(s, uc)
    for r in AREG[1]:
        if r[0] <= addr < r[1]: return r
pcemu.PC.blk = blk
TMP = os.environ.get('TMPDIR', '/tmp')

def w_bench():
    import run_bench
    run_bench.run_lodestone()

def w_shell():
    txt = os.path.join(TMP, 'hot_txt.txt')
    open(txt, 'w').write(''.join('Line %d of a text file to TYPE and COPY, as a user would.\r\n' % i for i in range(300)))
    big = os.path.join(TMP, 'hot_big.bin'); open(big, 'wb').write(os.urandom(60000))
    files = [os.path.join(GOS, 'src', 'LCMD.COM'), 'TEXT.TXT=' + txt, 'BIG.BIN=' + big] + \
            ['F%02d.TXT=%s' % (i, txt) for i in range(20)]
    k = ktest.KPC(mkimg.build(os.path.join(TMP, 'hot_shell.img'), [os.path.join(GOS, 'src', 'LODE.SYS')] + files))
    k.start(); k.code_p()
    for cmd in ('dir', 'dir *.txt', 'type text.txt', 'copy big.bin big2.bin', 'copy text.txt t2.txt',
                'type t2.txt', 'dir /w', 'del big2.bin', 'del t2.txt', 'type text.txt'):
        k.key('cls'); k.key(ktest.ENTER)
        k.key(cmd); k.key(ktest.ENTER, settle=False); k.settle(60)

def w_exec():
    k = ktest.KPC(mkimg.build(os.path.join(TMP, 'hot_exec.img'), [os.path.join(GOS, 'src', 'LODE.SYS'),
                  os.path.join(GOS, 'src', 'LCMD.COM')] + [os.path.join(GOS, 'tests', n) for n in ('TESTDOS.COM', 'MEMSZ.COM', 'UPPER.COM')]))
    k.start()
    for i in range(6): k.key(ktest.DOWN)
    k.run_for(5)
    k.run_file('MEMSZ.COM', 30)
    k.run_file('TESTDOS.COM', 120)

def w_claude():
    import test_claude_kernel as TC
    T = TC.T
    h = T.start([T.reply(('text', 'A reply over the link, long enough to fill a few frames. ' * 30))], bridge='pico')
    assert h.turn('hello', sim_s=60)

# ---- CLAUDE.COM's ------------------------------------------------------
def c_start(script, **kw):
    import claude_kernel as CK                  # (and gridlink's tests on the path)
    h = CK.KernelHarness(script, bridge='pico', mode='auto', **kw)
    h.boot(); cl_at(h.claude_psp)
    assert h.connect(), ('no connection', h.m.crash)
    return h

def w_cchat():
    import claude_kernel; from fake_anthropic import reply
    txt = ('A reply over the link, long enough to fill a few frames: **bold**, `code` and a list.\n\n'
           '- one item\n- two items\n\n') * 12
    h = c_start([reply(('text', txt)) for _ in range(3)])
    for p in ('hello', 'tell me more about it', 'and once more, with a longer prompt typed in key by key'):
        assert h.turn(p, sim_s=60)

def w_cfiles():
    import claude_kernel; from fake_anthropic import reply
    notes = b''.join(b'%05d: a line of a text file that the Pi reads, edits and writes back.\r\n' % i for i in range(160))
    E = 'str_replace_based_edit_tool'
    h = c_start([reply(('tool', E, {'command': 'view', 'path': 'A:\\NOTES.TXT'})),
                 reply(('tool', E, {'command': 'create', 'path': 'A:\\NEW.TXT', 'file_text': notes.decode() * 2})),
                 reply(('tool', 'grid_files', {'action': 'list', 'path': 'A:\\'})),
                 reply(('tool', 'grid_files', {'action': 'info', 'path': 'A:\\NOTES.TXT'})),
                 reply(('tool', E, {'command': 'str_replace', 'path': 'A:\\NOTES.TXT', 'old_str': '00001:', 'new_str': 'one:'})),
                 reply(('tool', E, {'command': 'view', 'path': 'A:\\NEW.TXT'})),
                 reply(('text', 'Done.'))], files={'A:\\NOTES.TXT': notes})
    assert h.turn('look at the notes', sim_s=240)

def w_cops():
    import claude_kernel as CK; from fake_anthropic import reply
    big = ''.join('line %05d: the quick brown fox jumps over the lazy dog\n' % i for i in range(400))
    E = 'str_replace_based_edit_tool'
    h = c_start([reply(('tool', E, {'command': 'create', 'path': 'A:\\BIG.TXT', 'file_text': big})),
                 reply(('tool', E, {'command': 'view', 'path': 'A:\\BIG.TXT'})), reply(('text', 'Written and read.'))])
    assert h.turn('write a big file', sim_s=120)
    CK.ops_probe(h.session.grid, lambda c: h.run_until(c, 60), h.m.chip.devices)

def w_crun():
    import claude_kernel; from fake_anthropic import reply
    G = lambda c, keys: reply(('tool', 'grid_command', {'command': c, 'capture': False, 'keys': keys}))
    h = c_start([G('TESTKEY', 'hello{WAIT 0.3}{SNAP}abc{ESC}'), G('TESTKEY', 'some keys typed in{WAIT 0.2}more{ESC}'),
                 reply(('tool', 'grid_command', {'command': 'DIR'})), reply(('text', 'Done.'))])
    assert h.turn('run them', sim_s=120)

def w_cstub():
    import sim7210
    CD = os.path.join(GOS, 'claude')
    tm = os.path.join(GOS, '..', 'tools', 'TM5000G.EXE')
    files = [os.path.join(GOS, 'src', n) for n in ('LODE.SYS', 'LCMD.COM')] + [os.path.join(CD, n) for n in ('CLAUDE.COM', 'EMSUSE.COM')]
    k = ktest.KPC(mkimg.build(os.path.join(TMP, 'hot_stub.img'), files + (['TM5000G.EXE=' + tm] if os.path.exists(tm) else [])),
                  ems_pages=88, chip=sim7210.NEC7210(sim7210.bus()))     # (TM5000G wants the GPIB)
    k.start(); k.code_p()
    def cmd(c, t=6):
        k.key(c); k.key(ktest.ENTER, settle=False); k.settle(t)
    cmd('claude /r')
    st_at(k.pc.u16(0, 0x16 * 4 + 2))
    for c in ('dir', 'ver', 'dir /w', 'cls'): cmd(c)            # (the prompt: the kernel's key wait asks INT 16h)
    for c in ('emsuse', 'emsuse /x'):                           # (AH=00h, 10h: the read path)
        cmd(c); k.key('some keys'); k.key(ktest.ESC)
    cmd('exit'); k.pc.run_until(lambda: k.pc.mode() == 0x40, 5); k.settle()
    k.run_for(10)                                               # (the Executive: AH=11h)
    k.key(D, D, U, U); k.run_for(5)
    if os.path.exists(tm):                                      # (its kbhit, AH=01h, polled)
        k.code_p(); cmd('tm5000g', 40); k.key(ktest.ENTER); k.run_for(10)

# ---- the UI's ----------------------------------------------------------
from test_apps import CODE, K_PGDN, K_PGUP, K_HOME, K_END, press, drag     # (its keys and mouse)
APP = lambda n: os.path.join(GOS, 'apps', n + '.RUN')
K_CODE_F7 = 0x6E00
D, U, L, R, RET, ESC = ktest.DOWN, ktest.UP, ktest.LEFT, ktest.RIGHT, ktest.ENTER, ktest.ESC

def text(name, n):
    p = os.path.join(TMP, name)
    open(p, 'wb').write(b''.join(b'Line %d: the quick brown fox jumps over the lazy dog, as a user would type it.\r\n' % i
                                 for i in range(n)))
    return p

def ui_pc(name, *files, mouse=True, **kw):
    t = text('hot_t.txt', 40)
    k = ktest.KPC(mkimg.build(os.path.join(TMP, name), [os.path.join(GOS, 'src', 'LODE.SYS')] + list(files)
                  + ['F%02d.TXT=%s' % (i, t) for i in range(24)]), **kw)
    k.pc.mouse = mouse; k.start()
    return k

def w_idle():
    k = ui_pc('hot_idle.img')
    k.run_for(30)
    k.wr('saver_t', struct.pack('<H', 36)); k.run_for(15)
    k.key(D); k.run_for(2)

def w_list():
    k = ui_pc('hot_list.img', os.path.join(GOS, 'src', 'LCMD.COM'), APP('WRITE'))
    for _ in range(3):
        k.key(*[D] * 30); k.key(*[U] * 12); k.key(K_PGDN, K_PGDN, K_PGUP, K_END, K_HOME)

def w_menu():
    k = ui_pc('hot_menu.img', APP('WRITE'), 'LONG.TXT=' + text('hot_long.txt', 300))
    for _ in range(3): k.key(ktest.F1); k.key(RET)
    k.select('LONG.TXT'); k.key(RET)
    for i in range(8):
        press(k, 100 + 40 * i, 100 + 20 * i, 2)
        k.key(*[D] * (i % 4 + 1)); k.key(ESC)
    for _ in range(3): k.key(ktest.F1); k.key(RET)

def w_form():
    k = ui_pc('hot_form.img', APP('SYSTEM'))
    k.select('F03.TXT')
    for c in 'RDRD':
        k.key(CODE[c]); k.key('NEWNAME'); k.key(ktest.TAB, ktest.TAB, D, U); k.key(ESC)
    for _ in range(3): k.key(ktest.TAB, ktest.TAB, ktest.TAB, D, D, U, ESC)
    k.key(CODE['U']); k.key('C'); k.key(RET); k.key(ktest.TAB, ktest.TAB, D, U, ESC); k.key(ESC)

def w_drag():
    k = ui_pc('hot_drag.img', APP('CALC'))
    k.key(CODE['K'])
    for i in range(4):
        drag(k, 50 * 8 + 3, 36, (30 - 6 * i) * 8 + 3, 76 + 40 * i)
        drag(k, (30 - 6 * i) * 8 + 3, 76 + 40 * i, 50 * 8 + 3, 36)
    k.key(K_CODE_F7, *[L] * 10, *[D] * 12, *[R] * 6, *[U] * 6, RET)
    k.key(K_CODE_F7, *[R] * 4, ESC)

def w_write():
    k = ui_pc('hot_write.img', APP('WRITE'), 'LONG.TXT=' + text('hot_long.txt', 300), mouse=False)
    k.select('LONG.TXT'); k.key(RET)
    k.key('Typed into Write a line at a time, the way a user would: words, spaces, a full stop. ' * 2); k.key(RET)
    k.key(*[K_PGDN] * 8); k.key(*[K_PGUP] * 4); k.key(*[D] * 40); k.key(K_END, K_HOME, *[R] * 20, *[U] * 30)
    k.key('More typing at the end of a scrolled line. ')

def w_calc():
    k = ui_pc('hot_calc.img', APP('CALC'))
    k.key(CODE['K'])
    for s in ('12+34*5', '1/7', '2^10-1', 'sqrt(2)*3.5', '100/3'):
        k.key(s); k.key(RET)
    ky = 28 + 80
    for r, c in ((0, 0), (1, 3), (1, 2), (4, 3), (2, 1), (3, 0), (4, 3)):
        press(k, (42 + 6 * c + 3) * 8, ky + 24 * r + 12, 1)

def w_system():
    k = ui_pc('hot_sys.img', APP('SYSTEM'))
    k.key(CODE['U'])
    for _ in range(2):
        k.key(*[D] * 6); k.key(*[U] * 6)
    for c in 'DCMD': k.key(c)
    k.key(ESC)

def w_term():
    k = ui_pc('hot_term.img', APP('TERM'), os.path.join(GOS, 'fonts', 'TERM.FNT'), APP('CALC'),
              os.path.join(GOS, 'src', 'LCMD.COM'), os.path.join(GOS, 'src', 'LODEMT.SYS'),
              'LODE.INI=' + ini(b'MULTITASK=1\r\n'), 'LONG.TXT=' + text('hot_long.txt', 120), ems_pages=88)
    k.key(ktest.CODE_P, settle=False); k.run_for(3.0)
    def typ(s, t):
        k.key(s, settle=False); k.key(RET, settle=False); k.run_for(t)
    for s, t in (('dir', 3), ('type long.txt', 8), ('dir /w', 3)): typ(s, t)
    typ('type long.txt', 0.2)
    k.key(CODE['K'], settle=False); k.run_for(8)       # (the calculator in front, the TYPE drawn behind it: clipped)
    k.key('12+34', settle=False); k.key(RET, settle=False); k.run_for(1)
    k.key(ESC, settle=False); k.run_for(1)             # (the calculator closed)
    for s, t in (('type long.txt', 8), ('dir', 3)): typ(s, t)

def w_wclip():
    k = ui_pc('hot_wclip.img', APP('WRITE'), 'LONG.TXT=' + text('hot_long.txt', 300))
    k.select('LONG.TXT'); k.key(RET)
    at = lambda c, r: (c * 8 + 2, 24 + r * 16 + 8)     # (column, row) of the whole-screen text area
    for i in range(4):
        drag(k, *at(4, i), *at(30, i + 1)); k.key(CODE['C'])           # a drag, CODE-C; CODE-V further down
        k.key(*[D] * 3, K_END); k.key(CODE['V'])
        drag(k, *at(0, 2 + i), *at(12, 2 + i)); press(k, *at(20, 2 + i), 2); k.key(RET)    # the menu's Cut
        press(k, *at(8, 8 + i), 2); k.key(RET)                          # ... and its Paste
        drag(k, *at(2, 3), *at(20, 3)); press(k, *at(4, 3), 2); k.key('E', RET)            # ... and its Erase
    k.key(K_PGDN, CODE['C'], CODE['V'], *[U] * 6)

def w_tasks():
    import test_mt as M
    k = M.boot('hot_tasks.img', b'MULTITASK=1\r\n', 88, APP('TASKS'))
    for i in range(3): M.ret(k, 'MTLINE.COM'); M.hot(k)
    for _ in range(3):
        k.key(CODE['T']); k.run_for(0.3)
        k.key(D, CODE['B'], CODE['B'], CODE['B'], D, CODE['Z'], CODE['Z'], U, U, D, D, D, 0x3F00, U)
        k.key(ESC); k.run_for(0.3)

def ini(t):
    p = os.path.join(TMP, 'hot_ini.txt'); open(p, 'wb').write(t); return p

# ---- resident Claude's console (RCON) -----------------------------------
def rc_harness(**kw):
    import test_resident_term as RT
    h = RT.Res(more={'A:\\BIG.TXT': RT.BIG}, **kw); h.boot()
    h.cmd('claude /r')
    h.cmd('emsuse')
    rc_at(h.m.rd(h.stub(), h.sym['r_hw'], 1)[0], h.rsym['rc_image_end'])
    return RT, h

def rc_up(RT, h):
    gen = RT.generation(h)
    h.press(RT.HOT)
    assert RT.popped(h, gen) and h.has('Welcome to Claude Code', 30)

def w_rterm():
    RT, h = rc_harness()
    try:
        rc_up(RT, h)
        for s in ('hello', 'big', 'again'):
            h.term_type(s); h.press(RT.ENTER); RT.in_step(h)
        h.press(RT.HOT); h.wait(lambda: h.inpop() == 0, 5)
        rc_up(RT, h)
        h.term_type('big'); h.press(RT.ENTER); RT.in_step(h)
        h.press(RT.HOT); h.wait(lambda: h.inpop() == 0, 5)
    finally:
        h.close()

def w_rfiles():
    import claude_kernel as CK
    RT, h = rc_harness()
    try:
        rc_up(RT, h)
        for a in ({'action': 'list', 'path': 'A:\\'}, {'action': 'read', 'path': 'A:\\BIG.TXT'}):
            RT.tool(h, 'grid_files', a)
        RT.tool(h, 'grid_change_files', {'action': 'write', 'path': 'A:\\NOTE.TXT', 'content': 'from the pop-up\n' * 900})
        CK.ops_probe(h.router.term.grid, lambda c: h.pi_wait(c, 40), h.m.chip.devices)
        h.press(RT.HOT); h.wait(lambda: h.inpop() == 0, 5)
    finally:
        h.close()

def w_rbg():
    import claude_kernel as CK
    RT, h = rc_harness(pico='quiet')
    try:
        rc_up(RT, h)
        t = h.router.term
        h.press(RT.HOT)
        h.wait(lambda: h.inpop() == 0, 5) and h.pi_wait(lambda: t.away and h.transport.proto.quiet, 10)
        h.run_until(lambda: False, 2)                  # (idle looks)
        RT.tool(h, 'grid_files', {'action': 'read', 'path': 'A:\\BIG.TXT'})
        RT.tool(h, 'grid_change_files', {'action': 'write', 'path': 'A:\\NOTE.TXT', 'content': 'in the background\n' * 900})
        RT.tool(h, 'grid_program', {})
        RT.tool(h, 'gpib_send', {'action': 'query', 'address': 29, 'command': 'ID?'})
        h.run_until(lambda: False, 2)
    finally:
        h.close()

if __name__ == '__main__':
    if len(sys.argv) < 3: sys.exit(__doc__)
    for w in sys.argv[2:]:
        print('== workload', w); CL[:] = ST[:] = [-1, -1, 0]; RC[:] = [-1, -1, 0, None]; globals()['w_' + w]()
    json.dump({'taken': taken, 'falls': falls, 'ui_taken': ui_taken, 'ui_falls': ui_falls,
               'cl_taken': cl_taken, 'cl_falls': cl_falls, 'st_taken': st_taken, 'st_falls': st_falls,
               'rc_taken': rc_taken, 'rc_falls': rc_falls, 'ap_taken': ap_taken, 'ap_falls': ap_falls}, open(sys.argv[1], 'w'))
    for n, c in ((('kernel', taken), ('UI', ui_taken), ('CLAUDE.COM', cl_taken), ('the stub', st_taken), ('RCON', rc_taken))
                 + tuple((n + '.RUN', c) for n, c in sorted(ap_taken.items()))):
        t = sum(c.values())
        print('%s: %d taken entries, %.1f%% at odd addresses' % (n, t, 100.0 * sum(v for a, v in c.items() if a & 1) / max(t, 1)))
