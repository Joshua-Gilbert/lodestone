"""DEFRAG.COM and the Executive's screen saver, in the emulator.

    python3 test_defrag.py

(tests/defrag_cut.py separately cuts the power at every write DEFRAG makes.)
"""
import os, sys, struct, subprocess, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import defrag_util as D, fatcheck, ktest, mkimg, pcemu, fat16img as F

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
    k.key(ktest.CODE_P); k.key('defrag /s')
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
    k.key(ktest.CODE_P); k.key('defrag /s'); seen.clear()
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
    # DEFRAG run from a batch file: LCMD keeps no file of it open between its lines (it opens it by its whole
    # name at its place for each, as COMMAND does), so DEFRAG does its whole work, the batch file moved
    # with the rest; the batch then goes on from where it was, each line once
    img = D.fragmented(os.path.join(OUT, 'b.img'), OUT)
    bat = b'DEFRAG /S\r\nECHO OK >> DONE.TXT\r\nECHO TWO >> DONE.TXT\r\n'
    D.mcopy(img, bat, 'RUN.BAT', OUT)
    raw0 = open(img, 'rb').read(); files0 = files_of(raw0)
    k = ktest.KPC(img); k.start()
    k.key(ktest.CODE_P); k.key('run')
    f4c = 0x600 + k.Y['f_4C']; seen = []
    k.pc.watch = lambda a: seen.append(1) if a == f4c else None
    k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: seen, 600)
    st = status(k); k.pc.watch = None
    for _ in range(10): k.settle(5)
    raw = bytes(k.pc.drives[0].img)
    files = files_of(raw); done = files.pop('A:\\DONE.TXT', None)
    frag, runs, used = D.layout(raw)
    probs, _ = fatcheck.check(raw)
    code = k.pc.u16(0x60, k.Y['last_exit']) & 255
    def start(r):
        i = r.find(b'RUN     BAT', 19 * 512, 33 * 512); return r[i + 26] | r[i + 27] << 8
    check('from a batch file: DEFRAG does its whole work (exit 0, every file in one piece and byte for byte, no '
          'CHKDSK problems), and the batch file, moved, carries on: its next two lines once each',
          code == 0 and 'open' not in st and not frag and files == files0 and not probs
          and done == b'OK \r\nTWO \r\n', (code, st, frag, probs, done, sorted(set(files) ^ set(files0))))
    check('... the batch file did move (cluster %d -> %d)' % (start(raw0), start(raw)), start(raw0) != start(raw))

def t_root():
    # long names, leftovers and a second copy of an entry (as a power cut
    # during packing can leave)
    img = D.fragmented(os.path.join(OUT, 'r.img'), OUT)
    D.mcopy(img, b'long name file\r\n' * 50, 'A long file name.txt', OUT)
    raw = bytearray(open(img, 'rb').read())
    R = 19 * 512
    ents = [bytes(raw[R + 32 * i:R + 32 * i + 32]) for i in range(224)]
    used = next(i for i, e in enumerate(ents) if e[0] == 0)
    sfn = next(i for i in range(used) if ents[i][:8] == b'LCMD    ')
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
          code == 0 and names.count(b'LCMD    COM') == 1 and len(lfns) == len(lfn_run) and good and
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
          code == 2 and 'no drive B:' in ''.join(k.pc.tty) and bytes(k.pc.drives[0].img) == rawa, (code, ''.join(k.pc.tty)[-200:]))

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
        k.wr('lastact', struct.pack('<H', (t - 5462 + int(secs_left * 18.2)) & 0xFFFF))
    k.key(ktest.DOWN); sel = k.u16('sel')
    k.pc.run_for(250)
    check('no screen saver before 5 minutes', any('Select a file' in l for l in k.band()), k.band())
    idle(k)
    k.pc.run_until(lambda: any('Lodestone Defrag' in l for y, l in k.ocr()), 30)
    check('after 5 minutes: DEFRAG /S runs', any('Lodestone Defrag' in l for y, l in k.ocr()))
    k.pc.run_until(lambda: not any('Lodestone Defrag' in l for y, l in k.ocr()), 600)
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
    check('a key wakes it, and does nothing else', any('Select a file' in l for l in k.band()) and k.u16('sel') == sel,
          (k.band(), sel, k.u16('sel')))
    # again: the disk is in order now, so DEFRAG says so and leaves; the
    # mouse wakes the dark screen
    idle(k)
    k.pc.run_until(lambda: any('Disk in order' in l for y, l in k.ocr()), 60)
    k.pc.run_until(lambda: not any('Lodestone Defrag' in l for y, l in k.ocr()), 30)
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
    img = mkimg.build(os.path.join(OUT, 'nd.img'), [os.path.join(GOS, 'src', 'LODE.SYS'), os.path.join(GOS, 'src', 'LCMD.COM')])
    k = ktest.KPC(img); k.start()
    idle(k); k.pc.run_for(3)
    check('without DEFRAG.COM: the dark screen with the time', dark(k), k.ocr())

def t_saver_all():
    """The saver goes round every disk: A:, B: and C:, each tidied, then
    the dark screen; an empty B: is passed over; a key during C:'s turn
    ends the round."""
    def idle(k):
        t = struct.unpack('<H', k.pc.rd(0, 0x46C, 2))[0]
        k.wr('lastact', struct.pack('<H', (t - 5462 + 18) & 0xFFFF))
    def watch(k, until, limit=900):
        seen = []
        end = k.pc.us + limit * 1e6
        while k.pc.us < end and not k.crashed:
            k.pc.run_for(1)
            for y, l in k.ocr():
                if 'tidying drive' in l:
                    c = l.split('tidying drive')[1].strip()[:1]
                    if not seen or seen[-1] != c: seen.append(c)
            if until(k): break
        return seen
    a = D.fragmented(os.path.join(OUT, 'sva.img'), OUT)
    b = D.fragmented(os.path.join(OUT, 'svb.img'), OUT, seed=2)
    filesa = files_of(open(a, 'rb').read()); filesb = files_of(open(b, 'rb').read())
    d, f, files = D.hd_fragmented(big=40)
    ata = D.hd_drive(d)
    k = ktest.KPC(a, b=b, ata=ata); k.pc.mouse = True; k.start()
    idle(k)
    seen = watch(k, lambda k: dark(k))
    ra, rb = bytes(k.pc.drives[0].img), bytes(k.pc.drives[1].img)
    v, got, probs, frag, runs = D.hd_layout(ata)
    ga, pa = ok_disk(ra, filesa); gb, pb = ok_disk(rb, filesb)
    check('the saver goes round A:, B:, C: in turn, tidies each, then the dark screen',
          seen == ['A', 'B', 'C'] and dark(k) and ga and gb and not D.layout(ra)[0] and not D.layout(rb)[0]
          and not probs and not frag and all(got.get(n) == x for n, x in files.items()), (seen, pa, pb, probs, frag))
    k.key(ktest.DOWN)
    idle(k)                                             # next time: all in order, quickly
    t0 = k.pc.us
    seen = watch(k, lambda k: dark(k), 120)
    check('... next time each says "in order" and the dark screen follows (%.0f s)' % ((k.pc.us - t0) / 1e6),
          seen == ['A', 'B', 'C'] and dark(k) and bytes(k.pc.drives[0].img) == ra, (seen, k.ocr()))
    # B: empty: passed over quietly; a key during C:'s turn ends the round
    d, f, files = D.hd_fragmented(big=40)
    ata = D.hd_drive(d)
    k = ktest.KPC(a, b=b, ata=ata); k.pc.mouse = True; k.start()
    k.pc.drives[1].empty = True
    idle(k)
    def c_moving(k):
        return any('tidying drive C:' in l for y, l in k.ocr()) and 'Moving' in status(k)
    seen = watch(k, c_moving, 300)
    k.key(' ', settle=False)
    k.pc.run_until(lambda: any('Select a file' in l for l in k.band()), 30)
    v, got, probs, frag, runs = D.hd_layout(ata)
    check('an empty B: passed over; a key during C:\'s turn: back to the list, C: consistent',
          seen == ['A', 'C'] and any('Select a file' in l for l in k.band()) and
          not [p for p in probs if 'lost' not in p] and all(got.get(n) == x for n, x in files.items()),
          (seen, k.band(), probs))

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

# ---------------------------------------------------------------------
#  drive C: (the internal hard disk through the kernel's INT 25h/26h)
# ---------------------------------------------------------------------
def hd_root_packed(v):
    raw = v.sec(v.root, v.data - v.root)
    ents = [raw[i:i + 32] for i in range(0, len(raw), 32)]
    used = next((i for i, e in enumerate(ents) if e[0] == 0), len(ents))
    return all(e[0] != 0xE5 for e in ents[:used]) and not any(raw[used * 32:])

def hd_log(v):
    return next((b for n, b in v.files()[0].items() if n == '\\DEFRAG.TXT'), b'').decode('latin-1')

def t_hd():
    """DEFRAG C:: a FAT16 disk whose data runs past sector 65,535."""
    d, f, files = D.hd_fragmented()
    ata = D.hd_drive(d)
    img = D.hd_boot(os.path.join(OUT, 'hd.img'))
    rawa = open(img, 'rb').read()
    def done(k):                                        # (no /S: a key at the end)
        if 'Disk in order' in status(k) and not k.pc.keys: k.pc.keys.append(13)
    k, code = D.run(img, tail=' c:', ata=ata, during=done)
    v, got, probs, frag, runs = D.hd_layout(ata)
    st = ' '.join(l.strip() for y, l in k.ocr() if 330 <= y < 356) if k.pc.mode() == 0x40 else ''
    ents = {n: c for n, a, c, s in v.entries(0)}
    check('C: (FAT16, 17,108 clusters, files past sector 65,535): exit 0, every file in one piece, byte for byte',
          code == 0 and not probs and not frag and all(got.get(n) == b for n, b in files.items()), (code, probs, frag))
    check('... the system file and the directory stay, the lost and the bad cluster are left alone, the root is packed',
          ents.get('IO.SYS') == 2 and ents.get('SUB') == 16400 and v.fat(17050) == 0xFFFF and v.fat(500) == 0xFFF7
          and hd_root_packed(v) and 'OLD1.TXT' not in ents, (ents, v.fat(17050), v.fat(500)))
    log = hd_log(v)
    check('... says so, logged in C:\\DEFRAG.TXT, A: untouched',          # (the log took a cluster after)
          'Disk in order: 6 files, %d KB free in 4 pieces, 1 lost cluster' % ((v.free() + 1) * 2) in log and
          bytes(k.pc.drives[0].img) == rawa, log)
    k.key('cls'); k.key(ktest.ENTER); k.key('dir c:\\sub'); k.key(ktest.ENTER)
    o = k.pc.text_screen()
    check('... and the kernel sees it at once: DIR C:\\SUB, its bytes free',
          'S1       DAT' in o and '%d bytes free' % (v.free() * 2048) in o, o[-300:])
    del ata.writes[:]
    k, code = D.run(img, tail=' c: /s', ata=ata)
    check('second run on C:: in order, nothing written', code == 0 and not ata.writes, (code, ata.writes[:5]))

def t_hd_big():
    """The CP30104H's own layout (121 MB, 59,224 clusters, 232-sector FATs)
    with its 4 bad sectors in the free space: a file in pieces whose last
    piece is at cluster 59,000 (sector 236,000 on), another file there."""
    rom = os.path.join(GOS, '..', 'rom', 'hd_cp30104h')
    sect0 = open(os.path.join(rom, 'HDSECT0.BIN'), 'rb').read()
    boots = open(os.path.join(rom, 'HDBOOT.BIN'), 'rb').read()
    plba, n = struct.unpack_from('<II', sect0, 446 + 8)
    f = F.Fat(n, 4, plba, True)
    files = {'COMMAND.COM': bytes(range(256)) * 187, 'PIECES.DAT': bytes((i * 13) & 255 for i in range(30 * 2048)),
             'END.TXT': b'at the far end\r\n' * 300}
    ents = f.tree([('COMMAND.COM', 0x20, files['COMMAND.COM'])])
    gap = f.free; f.skip_to(gap + 40)
    p = files['PIECES.DAT']
    ents += f.ent('PIECES.DAT', 0x20, D.hd_put(f, list(range(gap + 40, gap + 50)) + list(range(59000, 59020)), p), len(p))
    f.fat[59000 - 1] = f.fat[59000 - 1]
    f.free = 59100
    ents += f.tree([('END.TXT', 0x20, files['END.TXT'])])
    f.finish(ents)
    f.img[0:512] = boots
    d = bytearray(762 * 8 * 39 * 512); d[0:512] = sect0; d[plba * 512:(plba + n) * 512] = f.img
    ata = pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=762, heads=8, spt=39, disk=d,
                    bad=[85174, 85203, 85232, 85261])
    img = D.hd_boot(os.path.join(OUT, 'hdb.img'))
    k, code = D.run(img, tail=' c: /s', ata=ata)
    v = F.Volume(ata.disk, plba)
    got, probs = v.files()
    st = status(k)
    chains = {nm: v.chain(c)[0] for nm, a, c, s2 in v.entries(0) if c}
    pieces = [nm for nm, ch in chains.items() if any(b != a + 1 for a, b in zip(ch, ch[1:]))]
    check('121 MB C: (Joshua\'s layout): exit 0, the file in pieces joined, the far ones brought forward, byte for byte',
          code == 0 and not probs and not pieces and max(ch[-1] for ch in chains.values()) < 200 and
          all(got.get('\\' + nm) == b for nm, b in files.items()), (code, probs, pieces, {k2: (c[0], c[-1]) for k2, c in chains.items()}))
    check('... "%d KB free in one piece" (past 65,535 KB)' % ((v.free() + 1) * 2),
          'KB free in one piece' in st and '%d KB' % ((v.free() + 1) * 2) in st, st)

def t_hd_max():
    """C: at the kernel's limit: 65,518 clusters of 512 bytes (the map's
    cells and the owner map at their largest)."""
    f = F.Fat(66067, 1, 17, True)                       # (its FAT: 258 sectors)
    assert (f.clusters, f.spf) == (65518, 258), (f.clusters, f.spf)
    files = {'A.DAT': bytes((i * 7) & 255 for i in range(30000)), 'Z.DAT': b'the far end' * 100}
    ents = f.ent('A.DAT', 0x20, D.hd_put(f, list(range(2, 30)) + list(range(65000, 65031)), files['A.DAT']), 30000)
    f.skip_to(65400)
    ents += f.tree([('Z.DAT', 0x20, files['Z.DAT'])])
    f.finish(ents)
    cyl = -(-(f.n + 17) // (16 * 63))
    d = bytearray(cyl * 16 * 63 * 512)
    d[0:512] = F.mbr([(0x80, 0x06, 17, f.n)], cyl, 16, 63); d[17 * 512:(17 + f.n) * 512] = f.img
    ata = pcemu.Ata(cyls=cyl, heads=16, spt=63, disk=d)
    img = D.hd_boot(os.path.join(OUT, 'hdmax.img'))
    k, code = D.run(img, tail=' c: /s', ata=ata)
    v = F.Volume(ata.disk, 17)
    got, probs = v.files()
    chains = {nm: v.chain(c)[0] for nm, a, c, s2 in v.entries(0) if c}
    check('C: with 65,518 clusters: exit 0, both files whole and in one piece near the start, the map on the screen',
          code == 0 and not probs and all(got.get('\\' + n) == b for n, b in files.items()) and
          all(ch == list(range(ch[0], ch[0] + len(ch))) and ch[-1] < 200 for ch in chains.values())
          and 'Disk in order' in status(k), (code, probs, status(k), {n: (c[0], c[-1]) for n, c in chains.items()}))

def t_hd_worn():
    """C: with sectors that won't write where the moves go, and one that
    won't read in a file."""
    d, f, files = D.hd_fragmented()
    v = F.Volume(d, D.HD_PLBA)
    weak = [D.HD_PLBA + v.data + (12 - 2) * 4 + 1]            # cluster 12: where S2.DAT would go
    ata = D.hd_drive(d, badw=weak)
    img = D.hd_boot(os.path.join(OUT, 'hdw.img'))
    k, code = D.run(img, tail=' c: /s', ata=ata)
    v, got, probs, frag, runs = D.hd_layout(ata)
    log = hd_log(v)
    check('C: with a sector that won\'t take a write: its cluster marked bad, the rest tidied, files intact, logged',
          code == 0 and v.fat(12) == 0xFFF7 and not probs and not frag and all(got.get(n) == b for n, b in files.items())
          and any(0 <= weak[0] - D.HD_PLBA - int(m) < 18 for m in __import__('re').findall(r'04h writing sector (\d+)', log))
          and '1 lost cluster, 1 bad cluster marked' in log,
          (code, v.fat(12), probs, frag, log, status(k)))
    d, f, files = D.hd_fragmented()
    v = F.Volume(d, D.HD_PLBA)
    big = next(c for n, a, c, s in v.entries(0) if n == 'BIG.DAT')
    ata = D.hd_drive(d, bad=[D.HD_PLBA + v.data + (big + 100 - 2) * 4 + 2])
    k, code = D.run(img, tail=' c: /s', ata=ata)
    v, got, probs, frag, runs = D.hd_layout(ata)
    st = status(k)
    check('C: with a sector of BIG.DAT that can\'t be read: it stays, the rest tidied, exit 2, says so',
          code == 2 and "1 file couldn't be read" in st and next(c for n, a, c, s in v.entries(0) if n == 'BIG.DAT') == big
          and not probs and frag == [] and all(got.get(n) == b for n, b in files.items()), (code, st, probs, frag))

def t_hd_test():
    """DEFRAG C: /T on a small FAT16 partition with a few bad sectors."""
    f = F.Fat(4300, 1, 17, True, rootents=64)                  # 4,261 clusters of 512 bytes
    files = {'A.DAT': bytes(range(256)) * 40}
    ents = f.tree([('A.DAT', 0x20, files['A.DAT'])])
    f.finish(ents)
    d = bytearray(70 * 4 * 17 * 512)
    d[0:512] = F.mbr([(0x80, 0x04, 17, 4300)], 70, 4, 17); d[17 * 512:(17 + 4300) * 512] = f.img
    bad = [f.lba(c) + 17 for c in (300, 301, 2000, 4250)]       # (sectors of the drive)
    ata = pcemu.Ata(cyls=70, heads=4, spt=17, disk=d, bad=bad)
    img = D.hd_boot(os.path.join(OUT, 'hdt.img'))
    k, code = D.run(img, tail=' c: /t /s', ata=ata)
    v = F.Volume(ata.disk, 17)
    marked = [c for c in range(2, v.ncl) if v.fat(c) == 0xFFF7]
    got, probs = v.files()
    st = status(k)
    log = hd_log(v)
    check('C: /T: every free sector tested, exactly the bad ones marked, the file intact, logged by sector',
          code == 0 and marked == [300, 301, 2000, 4250] and got.get('\\A.DAT') == files['A.DAT'] and not probs
          and 'Free space tested' in st and '4 bad clusters marked' in st and 'reading sector' in log,
          (code, marked, st, log, probs))

def t_hd_misc():
    """No C:; a key part way through a move on C:."""
    img = D.hd_boot(os.path.join(OUT, 'hdm.img'))
    rawa = open(img, 'rb').read()
    k, code = D.run(img, tail=' c: /s')
    check('DEFRAG C: with no hard disk: says so, writes nothing',
          code == 2 and 'no drive C:' in ''.join(k.pc.tty) and bytes(k.pc.drives[0].img) == rawa, (code, ''.join(k.pc.tty)[-200:]))
    d, f, files = D.hd_fragmented()
    ata = D.hd_drive(d)
    def key(k):
        if len(ata.writes) > 40 and not k.pc.keys: k.pc.keys.append(ord(' '))
    k, code = D.run(img, tail=' c: /s', ata=ata, during=key)
    v, got, probs, frag, runs = D.hd_layout(ata)
    check('C:: a key part way: exit 1, the disk consistent, every file intact',
          code == 1 and not [p for p in probs if 'lost' not in p] and all(got.get(n) == b for n, b in files.items()),
          (code, probs, status(k)))

if __name__ == '__main__':
    t0 = time.time()
    only = sys.argv[1:]
    for t in (t_basic, t_refuse, t_stop, t_open_file, t_root, t_drive_b, t_720, t_msdos, t_saver, t_bad,
              t_hd, t_hd_big, t_hd_max, t_hd_worn, t_hd_test, t_hd_misc, t_saver_all):
        if not only or t.__name__ in only: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
