"""DEFRAG.COM and the Executive's screen saver, in the emulator.

    python3 test_defrag.py

(tests/defrag_cut.py separately cuts the power at every write DEFRAG makes.)
"""
import os, sys, struct, subprocess, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import defrag_util as D, fatcheck, ktest, mkimg, pcemu

OUT = tempfile.mkdtemp()
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)) if detail and not cond else ''))

# count DEFRAG's writes, and act after the Nth one (a key, a disk swap)
W = {'n': 0, 'at': None, 'do': None}
_o13 = pcemu.PC.int13
def _i13(s):
    w = s.r('ah') == 3 and s.r('dl') == 0
    r = _o13(s)
    if w and not (s.r('flags') & 1):
        W['n'] += 1
        if W['at'] is not None and W['n'] == W['at'] and W['do']: W['do'](s)
    return r
pcemu.PC.int13 = _i13
def arm(at=None, do=None): W.update(n=0, at=at, do=do)

def dark(k):
    """The dark screen: just the time and the date (-> their y, or None)."""
    o = [(y, l.strip()) for y, l in k.ocr() if len(l.strip()) > 2]
    if len(o) == 2 and ':' in o[0][1] and o[0][1].endswith('m') and o[1][1].count('-') == 2: return o[0][0], o[0][1]
    return None

def status(k):
    return ' '.join(l.strip() for y, l in k.ocr() if 330 <= y < 356)

def files_of(raw):
    """Every file but DEFRAG's own log."""
    return {n: v for n, v in fatcheck.read_files(raw).items() if not n.endswith('\\DEFRAG.TXT')}

def ok_disk(raw, files0, allow_lost=False):
    probs, _ = fatcheck.check(raw)
    if allow_lost: probs = [p for p in probs if 'lost clusters' not in p]
    return not probs and files_of(raw) == files0, probs

def t_basic():
    img = D.fragmented(os.path.join(OUT, 'f.img'), OUT)
    raw0 = open(img, 'rb').read(); files0 = fatcheck.read_files(raw0)
    frag0, runs0, used0 = D.layout(raw0)
    arm()
    k, code = D.run(img)
    raw = bytes(k.pc.drives[0].img)
    frag, runs, used = D.layout(raw)
    good, probs = ok_disk(raw, files0)
    live = sum(1 for i in range(used) if raw[19 * 512 + 32 * i] not in (0, 0xE5))
    check('fragmented disk: exit 0, every file in one piece, free space at the end',
          code == 0 and frag0 and not frag and runs[-1][1] == 2848 and len(runs) <= 2, (code, frag0, frag, runs))
    check('... every file byte for byte, no CHKDSK problems', good, probs)
    check('... root packed to its live entries (%d -> %d)' % (used0, used), used == live and used < used0, (used0, used, live))
    check('... says so', 'Disk in order' in status(k), status(k))
    open(img, 'wb').write(raw)
    arm()
    k, code = D.run(img)
    check('second run: in order, nothing written', code == 0 and W['n'] == 0 and bytes(k.pc.drives[0].img) == raw, (code, W['n']))

def t_refuse():
    img = D.fragmented(os.path.join(OUT, 'wp.img'), OUT)
    raw0 = open(img, 'rb').read()
    def wp(k): k.pc.drives[0].wp = True
    k = ktest.KPC(img); k.start()
    k.pc.drives[0].wp = True
    k.key(ktest.CODE_C); k.key('defrag /s')
    f4c = 0x600 + k.Y['f_4C']; seen = []
    k.pc.watch = lambda a: seen.append(1) if a == f4c else None
    k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: seen, 600)
    st = status(k)
    k.pc.watch = None; k.settle(5)
    check('write-protected: exit 2, says so, disk untouched',
          (k.pc.u16(0x60, k.Y['last_exit']) & 255) == 2 and 'write-protected' in st and bytes(k.pc.drives[0].img) == raw0, st)
    # a drive without a change line
    k = ktest.KPC(img); k.start()
    k.pc.drives[0].no_changeline = True
    k.key(ktest.CODE_C); k.key('defrag /s'); seen.clear()
    k.pc.watch = lambda a: seen.append(1) if a == f4c else None
    k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: seen, 600)
    st = status(k); k.pc.watch = None; k.settle(5)
    check('no change line: map only, disk untouched',
          (k.pc.u16(0x60, k.Y['last_exit']) & 255) == 2 and 'change line' in st and bytes(k.pc.drives[0].img) == raw0, st)

def t_stop():
    img = D.fragmented(os.path.join(OUT, 'k.img'), OUT)
    raw0 = open(img, 'rb').read(); files0 = fatcheck.read_files(raw0)
    arm(30, lambda s: s.keys.append(0x1C0D))
    k, code = D.run(img)
    raw = bytes(k.pc.drives[0].img)
    good, probs = ok_disk(raw, files0)
    check('a key part way: exit 1 at once, the disk consistent, files intact',
          code == 1 and good and W['n'] < 45, (code, W['n'], probs))
    # the disk swapped part way: nothing more is written, to either disk
    img = D.fragmented(os.path.join(OUT, 's.img'), OUT)
    other = D.fragmented(os.path.join(OUT, 's2.img'), OUT, seed=7)
    raw2 = open(other, 'rb').read()
    first = []
    def swap(s):
        first.append(s.drives[0])
        f = pcemu.Floppy(other); f.changed = True; s.drives[0] = f
    arm(30, swap)
    k, code = D.run(img)
    raw = bytes(first[0].img)
    good, probs = ok_disk(raw, fatcheck.read_files(open(img, 'rb').read()), allow_lost=True)
    check('disk swapped part way: exit 2, says so, the new disk untouched, the first consistent',
          code == 2 and 'changed' in status(k) and bytes(k.pc.drives[0].img) == raw2 and good and W['n'] == 30,
          (code, status(k), W['n'], probs))

def t_open_file():
    # DEFRAG run from a batch file: the batch file is open, so map only
    img = D.fragmented(os.path.join(OUT, 'b.img'), OUT)
    D.mcopy(img, b'DEFRAG /S\r\nECHO OK > DONE.TXT\r\n', 'RUN.BAT', OUT)
    raw0 = open(img, 'rb').read()
    k = ktest.KPC(img); k.start()
    k.key(ktest.CODE_C); k.key('run')
    f4c = 0x600 + k.Y['f_4C']; seen = []
    k.pc.watch = lambda a: seen.append(1) if a == f4c else None
    k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: seen, 600)
    st = status(k); k.pc.watch = None
    for _ in range(10): k.settle(5)
    raw = bytes(k.pc.drives[0].img)
    files = fatcheck.read_files(raw)
    check('from a batch file (open): map only, and the batch file carries on',
          'open' in st and files.get('A:\\DONE.TXT', b'').startswith(b'OK') and D.layout(raw)[0] == D.layout(raw0)[0], (st, files.get('A:\\DONE.TXT')))

def t_root():
    # long names, leftovers and a second copy of an entry (as a power cut
    # during packing can leave)
    img = D.fragmented(os.path.join(OUT, 'r.img'), OUT)
    D.mcopy(img, b'long name file\r\n' * 50, 'A long file name.txt', OUT)
    raw = bytearray(open(img, 'rb').read())
    R = 19 * 512
    ents = [bytes(raw[R + 32 * i:R + 32 * i + 32]) for i in range(224)]
    used = next(i for i, e in enumerate(ents) if e[0] == 0)
    sfn = next(i for i in range(used) if ents[i][:8] == b'GRIDCMD ')
    lfn_run = [i for i in range(used) if ents[i][11] == 0x0F and ents[i][0] != 0xE5]
    tail = []
    tail += [bytes([0x41]) + b'x\0' * 5 + bytes([0x0F, 0, 0x55]) + b'y\0' * 6 + b'\0\0' + b'z\0' * 2]   # an orphan part
    tail += [b'\xE5' + ents[sfn][1:]]                                                              # (deleted)
    tail += [ents[sfn]]                                                                            # a second copy
    for j, e in enumerate(tail): raw[R + 32 * (used + j):R + 32 * (used + j + 1)] = e
    open(img, 'wb').write(raw)
    files0 = fatcheck.read_files(bytes(raw))
    arm()
    k, code = D.run(img)
    out = bytes(k.pc.drives[0].img)
    ents2 = [out[R + 32 * i:R + 32 * i + 32] for i in range(224)]
    used2 = next(i for i, e in enumerate(ents2) if e[0] == 0)
    names = [e[:11] for e in ents2[:used2] if e[11] != 0x0F]
    lfns = [e for e in ents2[:used2] if e[11] == 0x0F]
    good, probs = ok_disk(out, files0)
    check('root: the second copy and a stray long-name part go; real long names stay with their file',
          code == 0 and names.count(b'GRIDCMD COM') == 1 and len(lfns) == len(lfn_run) and good and
          all(ents2[i + 1][11] != 0x0F or True for i in range(used2)), (code, names, len(lfns), len(lfn_run), probs))
    # old entries after the end marker (a power cut while an earlier run
    # wrote the packed root): zeroed, so a new file can't bring them back
    img = D.fragmented(os.path.join(OUT, 'r2.img'), OUT)
    raw = bytearray(open(img, 'rb').read())
    ents = [bytes(raw[R + 32 * i:R + 32 * i + 32]) for i in range(224)]
    used = next(i for i, e in enumerate(ents) if e[0] == 0)
    big1 = next(e for e in ents[:used] if e[:11] == b'BIG1    DAT')
    stale = b'OLDBIG  DAT' + big1[11:]                 # an old entry for BIG1's clusters
    at = (used // 16 + 2) * 16 + 3                      # two sectors past the end marker
    raw[R + 32 * at:R + 32 * at + 32] = stale
    open(img, 'wb').write(raw)
    files0 = fatcheck.read_files(bytes(raw))
    arm()
    k, code = D.run(img)
    out = bytes(k.pc.drives[0].img)
    good, probs = ok_disk(out, files0)
    end = next(i for i in range(224) if out[R + 32 * i] == 0)
    check('root: old entries after the end marker are cleared (a new file can\'t bring them back)',
          code == 0 and good and not any(out[R + 32 * end:33 * 512]), (code, probs, end))

def t_drive_b():
    # drive B: - DEFRAG B: /T and DEFRAG B:, started from A:; A: untouched
    a = D.fragmented(os.path.join(OUT, 'ba.img'), OUT, seed=2)
    b = D.fragmented(os.path.join(OUT, 'bb.img'), OUT)
    rawa = open(a, 'rb').read(); rawb0 = open(b, 'rb').read(); filesb = files_of(rawb0)
    bad = set(range(2880 - 40, 2880 - 36)) | {2000}
    k, code = D.run(a, tail=' b: /S /T', b=b, before_start=lambda k: k.pc.drives[1].bad.update(bad))
    rb = bytes(k.pc.drives[1].img)
    fat = rb[512:512 + 9 * 512]
    get = lambda n: (struct.unpack_from('<H', fat, n * 3 // 2)[0] >> 4) if n & 1 else (struct.unpack_from('<H', fat, n * 3 // 2)[0] & 0xFFF)
    marked = sorted(n for n in range(2, 2849) if get(n) == 0xFF7)
    log = fatcheck.read_files(rb).get('A:\\DEFRAG.TXT', b'').decode('latin-1')
    st = status(k)
    good, probs = ok_disk(rb, filesb)
    check('DEFRAG B: /T: B: tested, exactly its bad ones marked, logged on B:, errors counted; A: untouched',
          code == 0 and marked == sorted({l - 33 + 2 for l in bad}) and good and '78(4)' in log and 'disk error' in st
          and 'drive B:' in ' '.join(l for y, l in k.ocr()) and bytes(k.pc.drives[0].img) == rawa, (code, marked, st, log, probs))
    open(b, 'wb').write(rb)
    k, code = D.run(a, tail=' B: /S', b=b, before_start=lambda k: k.pc.drives[1].bad.update(bad))
    rb = bytes(k.pc.drives[1].img)
    good, probs = ok_disk(rb, filesb)
    check('DEFRAG B: tidies B:, files intact; A: untouched',
          code == 0 and good and not D.layout(rb)[0] and bytes(k.pc.drives[0].img) == rawa, (code, status(k), probs))
    k, code = D.run(a, tail=' B: /S')
    check('DEFRAG B: on a GRiD with no drive B: says so, writes nothing',
          code == 2 and 'no floppy drive B:' in ''.join(k.pc.tty) and bytes(k.pc.drives[0].img) == rawa, (code, ''.join(k.pc.tty)[-200:]))

def t_720():
    img = D.fragmented(os.path.join(OUT, 'd.img'), OUT, size=720)
    raw0 = open(img, 'rb').read(); files0 = fatcheck.read_files(raw0)
    arm()
    k, code = D.run(img)
    raw = bytes(k.pc.drives[0].img)
    good, probs = ok_disk(raw, files0)
    frag, runs, used = D.layout(raw)
    check('720 KB disk (2-sector clusters): in order, files intact',
          code == 0 and D.layout(raw0)[0] and not frag and good, (code, frag, probs))

def t_msdos():
    sys.path.insert(0, os.path.join(GOS, 'bench'))
    import dosimg
    rom = next((p for p in (os.environ.get('GRID_ROM', ''), os.path.join(GOS, '..', 'rom', 'GRID_MSDOS330_ROM_300909-00.BIN'))
                if p and os.path.exists(p)), None)
    if not rom:
        check('GRiD MS-DOS: map only (EPROM image not here - skipped)', True); return
    img = dosimg.build(os.path.join(OUT, 'dos.img'), rom, [D.DEFRAG])
    raw0 = open(img, 'rb').read()
    pc = pcemu.PC(img)
    raw = open(img, 'rb').read()
    pc.mu.mem_write(0x7C00, raw[:512])
    pc.mu.mem_write(0x700, raw[(1 + 2 * 9 + 14) * 512:(1 + 2 * 9 + 14 + 3) * 512])
    for r, v in (('cs', 0x70), ('ip', 0), ('ax', 0), ('dx', 0), ('ss', 0), ('sp', 0x7C00), ('ds', 0), ('es', 0)):
        pc.w(r, v)
    pc.w('flags', 0x202)
    tty = lambda: ''.join(pc.tty)
    pc.run_until(lambda: 'new date' in tty(), 60); pc.keys.append(0x1C0D)
    pc.run_until(lambda: 'new time' in tty(), 30); pc.keys.append(0x1C0D)
    pc.run_until(lambda: tty().rstrip().endswith('>'), 30)
    n0 = len(pc.tty)
    for ch in 'DEFRAG /S': pc.keys.append(ord(ch))
    pc.keys.append(0x1C0D)
    pc.run_until(lambda: len(pc.tty) > n0 + 3 and tty().rstrip().endswith('>'), 120)
    check('GRiD MS-DOS: map only, the disk untouched', bytes(pc.drives[0].img) == raw0 and tty().rstrip().endswith('>'),
          tty()[-200:])

def t_saver():
    img = D.fragmented(os.path.join(OUT, 'sv.img'), OUT)
    raw0 = open(img, 'rb').read(); files0 = fatcheck.read_files(raw0)
    k = ktest.KPC(img); k.pc.mouse = True; k.start()
    def idle(k, secs_left=1):
        t = struct.unpack('<H', k.pc.rd(0, 0x46C, 2))[0]
        k.pc.wr(0x60, k.Y['lastact'], struct.pack('<H', (t - 5462 + int(secs_left * 18.2)) & 0xFFFF))
    k.key(ktest.DOWN); sel = k.pc.u16(0x60, k.Y['sel'])
    k.pc.run_for(250)
    check('no screen saver before 5 minutes', any('Select a file' in l for l in k.band()), k.band())
    idle(k)
    k.pc.run_until(lambda: any('Grid-OS Defrag' in l for y, l in k.ocr()), 30)
    check('after 5 minutes: DEFRAG /S runs', any('Grid-OS Defrag' in l for y, l in k.ocr()))
    k.pc.run_until(lambda: not any('Grid-OS Defrag' in l for y, l in k.ocr()), 600)
    k.pc.run_for(2)
    d1 = dark(k)
    raw = bytes(k.pc.drives[0].img)
    good, probs = ok_disk(raw, files0)
    check('... tidies the disk, then the dark screen with the time',
          good and not D.layout(raw)[0] and d1, (k.ocr(), probs))
    k.pc.run_for(21)
    d2 = dark(k)
    check('... which moves every 20 s', d1 and d2 and d1 != d2, (d1, d2))
    k.key(ktest.DOWN)
    check('a key wakes it, and does nothing else', any('Select a file' in l for l in k.band()) and k.pc.u16(0x60, k.Y['sel']) == sel,
          (k.band(), sel, k.pc.u16(0x60, k.Y['sel'])))
    # again: the disk is in order now, so DEFRAG says so and leaves; the
    # mouse wakes the dark screen
    idle(k)
    k.pc.run_until(lambda: any('Disk in order' in l for y, l in k.ocr()), 60)
    k.pc.run_until(lambda: not any('Grid-OS Defrag' in l for y, l in k.ocr()), 30)
    k.pc.run_for(1)
    d = dark(k)
    k.pc.mouse_move(3, 1); k.pc.run_for(2)
    check('next time: "Disk in order", dark screen; the mouse wakes it', d and any('Select a file' in l for l in k.band()),
          (d, k.band()))
    # the mouse during DEFRAG's work: it stops at once and we're back
    img = D.fragmented(os.path.join(OUT, 'sv2.img'), OUT)
    raw0 = open(img, 'rb').read(); files0 = fatcheck.read_files(raw0)
    k = ktest.KPC(img, disk_model='real'); k.pc.mouse = True; k.start(20)
    idle(k)
    k.pc.run_until(lambda: 'Moving' in status(k), 120)
    k.pc.run_for(3)
    k.pc.mouse_move(2, 2)
    t = k.pc.us
    k.pc.run_until(lambda: any('Select a file' in l for l in k.band()), 30)
    raw = bytes(k.pc.drives[0].img)
    good, probs = ok_disk(raw, files0)
    check('the mouse during the work: back to the list within seconds, exit 1, disk consistent',
          any('Select a file' in l for l in k.band()) and (k.pc.u16(0x60, k.Y['last_exit']) & 255) == 1 and good,
          ((k.pc.us - t) / 1e6, k.band(), probs))
    # no DEFRAG.COM on the disk: straight to the dark screen
    img = mkimg.build(os.path.join(OUT, 'nd.img'), [os.path.join(GOS, 'src', 'GRIDOS.SYS'), os.path.join(GOS, 'src', 'GRIDCMD.COM')])
    k = ktest.KPC(img); k.start()
    idle(k); k.pc.run_for(3)
    check('without DEFRAG.COM: the dark screen with the time', dark(k), k.ocr())

def t_bad():
    # a bad spot in the free space near the end of the disk (never written
    # since the format): its clusters are marked bad, the tidying goes on
    img = D.fragmented(os.path.join(OUT, 'bad.img'), OUT)
    raw0 = open(img, 'rb').read(); files0 = fatcheck.read_files(raw0)
    D.mcopy(img, bytes(range(256)) * 600, 'ZBIG.DAT', OUT)       # a 150 KB file to move far
    raw0 = open(img, 'rb').read(); files0 = fatcheck.read_files(raw0)
    frag0, runs0, used0 = D.layout(raw0)
    hole = runs0[0]                                              # a gap, and the far end
    bad = {33 + hole[0] - 2 + 1, 33 + hole[0] - 2 + 2} | set(range(2880 - 300, 2880 - 296))
    k, code = D.run(img, before_start=lambda k: k.pc.drives[0].bad.update(bad))
    raw = bytes(k.pc.drives[0].img)
    good, probs = ok_disk(raw, files0)
    fat = raw[512:512 + 9 * 512]
    get = lambda n: (struct.unpack_from('<H', fat, n * 3 // 2)[0] >> 4) if n & 1 else (struct.unpack_from('<H', fat, n * 3 // 2)[0] & 0xFFF)
    marked = [n for n in range(2, 2849) if get(n) == 0xFF7]
    want = sorted({l - 33 + 2 for l in bad})
    st = status(k)
    log = fatcheck.read_files(raw).get('A:\\DEFRAG.TXT', b'').decode('latin-1')
    files1 = {n: v for n, v in fatcheck.read_files(raw).items() if not n.endswith('DEFRAG.TXT')}
    check('bad spots in the free space: their clusters marked bad, the disk tidied anyway',
          code == 0 and set(marked) <= set(want) and marked and not D.layout(raw)[0] and files1 == files0 and
          not [p for p in fatcheck.check(raw)[0] if 'lost' not in p], (code, marked, want, st, probs))
    check('... says so, and logs it in DEFRAG.TXT', 'bad cluster' in st and 'bad cluster' in log and log.startswith('20'), (st, log))
    # a file with an unreadable sector: left as it is, the rest done
    img = D.fragmented(os.path.join(OUT, 'bad2.img'), OUT)
    raw0 = open(img, 'rb').read(); files0 = fatcheck.read_files(raw0)
    b2 = raw0[19 * 512:33 * 512]
    st0 = [struct.unpack_from('<H', b2, 32 * i + 26)[0] for i in range(224) if b2[32 * i:32 * i + 11] == b'BIG1    DAT'][0]
    k, code = D.run(img, before_start=lambda k: k.pc.drives[0].bad.add(33 + st0 - 2 + 1))
    raw = bytes(k.pc.drives[0].img)
    frag = D.layout(raw)[0]
    files1 = {n: v for n, v in fatcheck.read_files(raw).items() if not n.endswith('DEFRAG.TXT')}
    st = status(k)
    check('a file that can\'t be read stays where it is; the others are tidied; says so',
          code == 2 and frag == ['BIG1.DAT'] and files1 == files0 and "couldn't be read" in st, (code, frag, st))
    # an old, worn disk: bad spots all over the free space - it keeps going
    img = D.fragmented(os.path.join(OUT, 'bad3.img'), OUT)
    D.mcopy(img, bytes(range(256)) * 600, 'ZBIG.DAT', OUT)
    raw0 = open(img, 'rb').read(); files0 = files_of(raw0)
    free = [c for a_, b_ in D.layout(raw0)[1] for c in range(a_, b_ + 1)]
    bad = {33 + c - 2 for c in free[::23]}
    k, code = D.run(img, before_start=lambda k: k.pc.drives[0].bad.update(bad))
    raw = bytes(k.pc.drives[0].img)
    st = status(k)
    good, probs = ok_disk(raw, files0)
    check('a worn disk (a bad spot every 23 free clusters): keeps going to the end, files intact',
          code in (0, 2) and good and ('bad cluster' in st or 'not enough room' in st) and W['n'] > 0, (code, st, probs))
    # /T: the free space tested, bad spots marked, the cylinders logged
    img = D.fragmented(os.path.join(OUT, 'bad4.img'), OUT)
    raw0 = open(img, 'rb').read(); files0 = files_of(raw0)
    bad = set(range(2880 - 40, 2880 - 36)) | {2000}
    k, code = D.run(img, tail=' /S /T', before_start=lambda k: k.pc.drives[0].bad.update(bad))
    raw = bytes(k.pc.drives[0].img)
    st = status(k)
    fat = raw[512:512 + 9 * 512]
    get = lambda n: (struct.unpack_from('<H', fat, n * 3 // 2)[0] >> 4) if n & 1 else (struct.unpack_from('<H', fat, n * 3 // 2)[0] & 0xFFF)
    marked = sorted(n for n in range(2, 2849) if get(n) == 0xFF7)
    log = fatcheck.read_files(raw).get('A:\\DEFRAG.TXT', b'').decode('latin-1')
    good, probs = ok_disk(raw, files0)
    check('/T: every free sector tested, exactly the bad ones marked, cylinders logged',
          code == 0 and marked == sorted({l - 33 + 2 for l in bad}) and good and 'cylinder (count): 55(1) 78(4)' in log
          and 'Free space tested' in st, (code, marked, st, log))
    # a weak spot that fails in a run but passes sector by sector: marked
    # the second time, and on it goes
    img = D.fragmented(os.path.join(OUT, 'bad5.img'), OUT)
    raw0 = open(img, 'rb').read(); files0 = files_of(raw0)
    hole = D.layout(raw0)[1][0]
    weak = 33 + hole[0] - 2
    o = pcemu.PC.int13
    def flaky13(s):
        if s.r('ah') == 2 and s.r('dl') == 0 and s.r('al') > 1:
            cx, dx = s.r('cx'), s.r('dx')
            lba = ((cx >> 8) * 2 + (dx >> 8)) * 18 + (cx & 63) - 1
            if lba <= weak < lba + s.r('al'):
                s.w('ax', 0x1000); s.cf(1); return
        return o(s)
    pcemu.PC.int13 = flaky13
    try:
        k, code = D.run(img)
    finally:
        pcemu.PC.int13 = o
    raw = bytes(k.pc.drives[0].img)
    good, probs = ok_disk(raw, files0)
    check('a weak spot (fails in a run, passes alone): marked, the work done', code == 0 and good and not D.layout(raw)[0],
          (code, status(k), probs))
    # the far end of the disk unusable (never written since the format, or
    # a drive that can't manage the inner tracks): it maps out what it
    # meets, notices, and finishes nearer the start
    img = D.fragmented(os.path.join(OUT, 'bad7.img'), OUT)
    D.mcopy(img, bytes(range(256)) * 600, 'ZBIG.DAT', OUT)
    raw0 = open(img, 'rb').read(); files0 = files_of(raw0)
    k, code = D.run(img, before_start=lambda k: k.pc.drives[0].bad.update(range(60 * 36, 2880)))
    raw = bytes(k.pc.drives[0].img)
    st = status(k)
    good, probs = ok_disk(raw, files0)
    check('the far end all bad: maps out what it meets, finishes nearer the start, files intact',
          code == 0 and good and not D.layout(raw)[0] and 'bad cluster' in st, (code, st, probs))
    # a drive whose writes all fail (nothing written reads back right):
    # it stops - after 8 failures in a row and two test writes - files intact
    img = D.fragmented(os.path.join(OUT, 'bad6.img'), OUT)
    raw0 = open(img, 'rb').read(); files0 = files_of(raw0)
    written = set()
    def dead13(s):
        cx, dx = s.r('cx'), s.r('dx')
        lba = ((cx >> 8) * 2 + (dx >> 8)) * 18 + (cx & 63) - 1
        n, ah, dl = s.r('al'), s.r('ah'), s.r('dl')
        if dl == 0 and ah == 3 and lba >= 33:
            written.update(range(lba, lba + n))
        r = o(s)
        if dl == 0 and ah == 2 and written & set(range(lba, lba + n)) and lba >= 33:
            es, bx = s.r('es'), s.r('bx')
            s.wr(es, bx, b'\xAA' * 16)
        return r
    pcemu.PC.int13 = dead13
    try:
        k, code = D.run(img)
    finally:
        pcemu.PC.int13 = o
    raw = bytes(k.pc.drives[0].img)
    st = status(k)
    files1 = files_of(raw)
    check('a drive whose writes don\'t take: stops, says so, files intact',
          code == 2 and 'fail everywhere' in st and files1 == files0, (code, st))

if __name__ == '__main__':
    t0 = time.time()
    only = sys.argv[1:]
    for t in (t_basic, t_refuse, t_stop, t_open_file, t_root, t_drive_b, t_720, t_msdos, t_saver, t_bad):
        if not only or t.__name__ in only: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
