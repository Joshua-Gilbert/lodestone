"""Power cut at every disk write DEFRAG makes, then a second DEFRAG run.

For each write N: the machine stops in the middle of DEFRAG's Nth write
call (the first half of its sectors written, the rest not).  The disk must
then still hold every file, byte for byte; the only problems allowed are
lost clusters, the two FAT copies differing, and (while the root directory
is being packed) an entry that appears twice.  Then another system adds a
file (mtools - it takes the first free root slot, which can bring back
whatever lies after the end marker).  A second, uninterrupted run on that
disk must finish with every file intact and in one piece, and nothing
left after the root's end marker.

    python3 defrag_cut.py [jobs]          (all write points)
    python3 defrag_cut.py [jobs] worn     (the same on a worn drive, below)

"worn": the pattern the GRiD's drive showed on 2026-10-05 (side 0 of
cylinders 61-78), moved to where this test disk's moves go: on side 0 of
cylinders 76-79, multi-sector reads starting at sectors 1-4 fail with a
CRC error (each sector passes alone), and four sectors fail outright (two
of them where the forward moves go).
A 150 KB file is added.  The second
run may end "still in pieces" (exit 2) only if the uninterrupted run did.
"""
import os, sys, re, shutil, tempfile, multiprocessing
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import defrag_util as D, fatcheck, pcemu

CUT = [None]
WORN = [False]
HARD = {c * 36 + h * 18 + n - 1 for c, h, n in ((20, 0, 7), (20, 0, 8), (79, 0, 5), (79, 0, 6))}
_o13 = pcemu.PC.int13
def _worn13(s):
    if WORN[0] and s.r('ah') == 2 and s.r('dl') == 0 and s.r('al') > 1:
        cx, dx = s.r('cx'), s.r('dx')
        if dx >> 8 == 0 and 76 <= cx >> 8 <= 79 and (cx & 63) <= 4:
            s.w('ax', 0x1000); s.cf(1); return
    return _o13(s)
def _setbad(k):
    if WORN[0]: k.pc.drives[0].bad.update(HARD)
def _i13(s):
    if CUT[0] is not None and s.r('ah') == 3 and s.r('dl') == 0:
        CUT[0] -= 1
        if CUT[0] == 0:
            al = s.r('al')
            if al >= 2:                         # half the sectors land
                s.w('ax', 0x0300 | (al // 2))
                _worn13(s)
            s.stopped = 'power cut'
            s.mu.emu_stop()
            return
    return _worn13(s)
pcemu.PC.int13 = _i13


def files_of(raw):
    return {n: v for n, v in fatcheck.read_files(raw).items() if not n.endswith('\\DEFRAG.TXT')}


def allowed(probs, during_pack):
    bad = []
    for p in probs:
        if 'lost clusters' in p or p == 'FAT copies differ': continue
        m = re.match(r'(.*): cluster \d+ cross-linked with (.*)$', p)
        if m and m.group(1) == m.group(2) and during_pack: continue
        bad.append(p)
    return bad


NEW = bytes((i * 7) & 255 for i in range(5000))


def after_end(raw):
    """Non-zero bytes after the root directory's end marker?"""
    for i in range(224):
        e = raw[19 * 512 + 32 * i:19 * 512 + 32 * i + 32]
        if e[0] == 0:
            return any(raw[19 * 512 + 32 * i:33 * 512])
    return False


def one(args):
    n, base, files0, npack, tmp, ref = args
    img = os.path.join(tmp, 'cut%04d.img' % n)
    open(img, 'wb').write(base)
    CUT[0] = n
    k, code = D.run(img, before_start=_setbad)
    CUT[0] = None
    raw = bytes(k.pc.drives[0].img)
    if code is not None:
        return n, 'finished before write %d' % n
    probs, _ = fatcheck.check(raw)
    bad = allowed(probs, n <= npack)
    if bad: return n, 'after the cut: %s' % bad
    if files_of(raw) != files0: return n, 'after the cut: files differ'
    open(img, 'wb').write(raw)
    t = os.path.join(tmp, 'n%04d' % n); os.makedirs(t, exist_ok=True)
    D.mcopy(img, NEW, 'NEW.DAT', t)
    files0 = dict(files0); files0['A:\\NEW.DAT'] = NEW
    k, code = D.run(img, before_start=_setbad)
    raw = bytes(k.pc.drives[0].img)
    probs, _ = fatcheck.check(raw)
    bad = allowed(probs, False)
    frag, runs, used = D.layout(raw)
    os.remove(img)
    if code != 0 and not (code == 2 and ref[0] == 2): return n, 'second run exit %s' % code
    if bad: return n, 'after the second run: %s' % bad
    if frag and not ref[1]: return n, 'after the second run, in pieces: %s' % frag
    if files_of(raw) != files0: return n, 'after the second run: files differ'
    if after_end(raw): return n, 'after the second run: old entries after the root end marker'
    return n, None


if __name__ == '__main__':
    jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    WORN[0] = 'worn' in sys.argv[2:]
    tmp = tempfile.mkdtemp()
    img = D.fragmented(os.path.join(tmp, 'base.img'), tmp)
    if WORN[0]: D.mcopy(img, bytes(range(256)) * 600, 'ZBIG.DAT', tmp)
    base = open(img, 'rb').read()
    files0 = fatcheck.read_files(base)
    # how many writes, and how many of them pack the root
    log = []
    def i13(s):
        if s.r('ah') == 3 and s.r('dl') == 0:
            cx, dx = s.r('cx'), s.r('dx')
            log.append(((cx >> 8) * 2 + (dx >> 8)) * 18 + (cx & 63) - 1)
        return _i13(s)
    pcemu.PC.int13 = i13
    k, code = D.run(img, before_start=_setbad)
    pcemu.PC.int13 = _i13
    raw1 = bytes(k.pc.drives[0].img)
    ref = (code, D.layout(raw1)[0])
    if WORN[0]:
        fat = raw1[512:512 + 9 * 512]
        get = lambda c: (fat[c * 3 // 2] | fat[c * 3 // 2 + 1] << 8) >> (4 if c & 1 else 0) & 0xFFF
        nb = sum(1 for c in range(2, 2849) if get(c) == 0xFF7)
        st = fatcheck.read_files(raw1).get('A:\\DEFRAG.TXT', b'').decode('latin-1').splitlines()
        print('worn drive: uninterrupted run exit %s, %d bad clusters marked, in pieces %s; files %s'
              % (code, nb, ref[1], 'intact' if files_of(raw1) == files_of(base) else 'DIFFER'))
        print('  ' + (st[0] if st else '(no DEFRAG.TXT)'))
    total = len(log)
    npack = next((i for i, l in enumerate(log) if not 19 <= l < 33), total)   # root writes come first
    print('%d writes (the first %d pack the root); first run exit %s' % (total, npack, code))
    with multiprocessing.Pool(jobs) as pool:
        res = pool.map(one, [(n, base, files0, npack, tmp, ref) for n in range(1, total + 1)])
    fails = [(n, r) for n, r in res if r]
    for n, r in fails: print('write %d: %s' % (n, r))
    print('%d cut points, %d failed' % (total, len(fails)))
    shutil.rmtree(tmp)
    sys.exit(1 if fails else 0)
