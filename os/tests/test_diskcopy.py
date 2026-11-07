"""DISKCOPY.COM and DISKCOMP.COM in the emulator, from the command prompt:
A: to B: onto a blank disk (formatted while copying, a new serial number,
the kernel reading the copy at once), DISKCOMP then (OK, and the disks
that differ), one drive with its disks swapped over three passes (the
wrong disk put in said), 720 KB, a source with bad sectors, a
write-protected target, Esc in the middle (INT 1Eh as it was), and the
switches and drives refused.

    python3 tests/test_diskcopy.py [name ...]
"""
import os, struct, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, pcemu, fatcheck

OUT = tempfile.mkdtemp()
SRC = os.path.join(GOS, 'src')
LCMD = os.path.join(SRC, 'LCMD.COM')
BIG = os.path.join(SRC, 'LODE.SYS')
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

def said(o, line): return any(l.strip() == line for l in o.split('\n'))
def out(k): return ''.join(k.pc.tty).replace('\r', '')

def blank(name, size=1474560):
    p = os.path.join(OUT, name); open(p, 'wb').write(bytes(size)); return p

def data_disk(name, size=1440, extra=()):
    return mkimg.build(os.path.join(OUT, name), [LCMD, 'SUB\\', 'SUB\\S.SYS=' + BIG, BIG] + list(extra), size=size)

def boot(b=None, **kw):
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(SRC, f) for f in
                                                    ('LODE.SYS', 'LCMD.COM', 'DISKCOPY.COM', 'DISKCOMP.COM')])
    k = ktest.KPC(img, b, **kw)
    if b and open(b, 'rb').read(512) == bytes(512):
        k.pc.drives[1].noid = set(range(len(k.pc.drives[1].img) // 512))
    k.start(); k.code_p()
    return k

def unformatted():
    f = pcemu.Floppy(bytes(1474560)); f.noid = set(range(2880)); f.changed = True
    return f

def go(k, line, steps=(), sim=600):
    """line at the prompt; steps: (text to wait for, then a key, or a function of k); -> all it printed and
    E<exit code>"""
    k.pc.tty.clear()
    k.key(line); k.key(ktest.ENTER, settle=False)
    seen = 0
    for text, act in steps:
        k.pc.run_until(lambda: out(k).count(text) > seen if text == 'Press any key' else text in out(k), sim)
        if text == 'Press any key': seen = out(k).count(text)
        if callable(act): act(k)
        elif act is not None: k.key(act, settle=False)
    k.settle(sim)
    o = out(k)
    for n in (1, 2, 3, 4):
        k.key('if errorlevel %d echo L%d' % (n, n)); k.key(ktest.ENTER)
    lv = sum(said(out(k)[len(o):], 'L%d' % n) for n in (1, 2, 3, 4))
    return o + '\nE%d\n' % lv

def shell(k, line):
    k.pc.tty.clear(); k.key(line); k.key(ktest.ENTER, settle=False); k.settle(20)
    return out(k)

def no_serial(img):
    b = bytearray(img); b[0x27:0x2B] = bytes(4); return bytes(b)

def t_two():
    k = boot(blank('b.img'))
    src = bytes(k.pc.drives[0].img)
    o = go(k, 'diskcopy a: b:', [('Press any key', ktest.ENTER), ('Copy another', 'n')])
    dst = bytes(k.pc.drives[1].img)
    check('DISKCOPY A: B: onto a blank disk: "Formatting while copying", every track formatted, exit code 0',
          'Formatting while copying' in o and 'Copying 80 tracks' in o and '18 sectors/track, 2 side(s)' in o
          and said(o, 'E0') and len(k.pc.drives[1].formats) == 160 and not k.pc.drives[1].noid, o)
    check('... the copy the source\'s, byte for byte, but its new serial number (said)',
          no_serial(dst) == no_serial(src) and dst[0x27:0x2B] != src[0x27:0x2B] and 'Volume Serial Number is' in o
          and ('%04X-%04X' % struct.unpack_from('<HH', dst, 0x27)[::-1]) in o, o)
    o = shell(k, 'dir b:')
    check('... the kernel reads the copy at once (DIR B:)', 'DISKCOPY COM' in o and 'LODE     SYS    50432' in o, o)
    o = go(k, 'diskcomp a: b:', [('Press any key', ktest.ENTER), ('Compare another', 'n')])
    check('DISKCOMP A: B: then: "Compare OK" (the serial numbers not compared), exit code 0',
          'Compare OK' in o and 'Compare error' not in o and said(o, 'E0'), o)
    k.pc.drives[1].img[(36 * 15 + 3) * 512 + 7] ^= 0x55  # one byte of B: changed: cylinder 15, side 0
    k.pc.drives[1].img[(36 * 79 + 18 + 4) * 512] ^= 1   # and one on cylinder 79, side 1
    o = go(k, 'diskcomp a: b:', [('Press any key', ktest.ENTER), ('Compare another', 'n')])
    check('DISKCOMP of disks that differ: "Compare error on side 0, track 15", "... side 1, track 79", exit code 1',
          'Compare error on side 0, track 15' in o and 'Compare error on side 1, track 79' in o
          and o.count('Compare error') == 2 and 'Compare OK' not in o and said(o, 'E1'), o)
    # B: already holding a copy (formatted): written over, not formatted again
    k.pc.drives[1].formats.clear()
    o = go(k, 'diskcopy a: b: /v', [('Press any key', ktest.ENTER), ('Copy another', 'n')])
    check('DISKCOPY /V onto a formatted disk: no tracks formatted, every one read back, exit code 0',
          'Formatting' not in o and not k.pc.drives[1].formats and said(o, 'E0')
          and no_serial(bytes(k.pc.drives[1].img)) == no_serial(src), o)

def t_one():
    s = data_disk('s1.img')
    k = boot(s)
    src = bytes(k.pc.drives[1].img)
    tgt = unformatted()
    srcdisk = k.pc.drives[1]
    def put(d):
        def f(k): d.changed = True; k.pc.drives[1] = d; k.key(ktest.ENTER, settle=False)
        return f
    wrong = pcemu.Floppy(open(mkimg.build(os.path.join(OUT, 'w.img'), [LCMD]), 'rb').read())   # (another disk: its
                                                                     #  boot sector perhaps the same, its FAT not)
    o = go(k, 'diskcopy b: b:', [('Press any key', ktest.ENTER),                 # the source
                                  ('Press any key', put(tgt)),                     # pass 1's target
                                  ('Press any key', put(wrong)),                   # pass 2: another disk, not the source
                                  ('Press any key', put(srcdisk)),
                                  ('Press any key', put(tgt)),
                                  ('Press any key', put(srcdisk)),                 # pass 3
                                  ('Press any key', put(tgt)),
                                  ('Copy another', 'n')])
    check('one drive (DISKCOPY B: B:): three passes, the disks swapped as asked, the copy whole, exit code 0',
          o.count('Insert SOURCE') == 4 and o.count('Insert TARGET') == 3 and said(o, 'E0')
          and no_serial(bytes(tgt.img)) == no_serial(src), o)
    check('... a disk that isn\'t the source put in for pass 2: "That isn\'t the SOURCE diskette", asked again',
          "That isn't the SOURCE diskette" in o and bytes(wrong.img) == open(os.path.join(OUT, 'w.img'), 'rb').read(), o)
    files = fatcheck.read_files(bytes(tgt.img))
    check('... its files as the source\'s', files.get('A:\\SUB\\S.SYS') == open(BIG, 'rb').read()
          and files.get('A:\\LODE.SYS') == open(BIG, 'rb').read(), sorted(files))
    o = go(k, 'diskcomp b: b:', [('Press any key', put(srcdisk)), ('Press any key', put(tgt)),
                                  ('Press any key', put(srcdisk)), ('Press any key', put(wrong)),   # pass 2: not the target
                                  ('Press any key', put(tgt)), ('Press any key', put(srcdisk)),
                                  ('Press any key', put(tgt)), ('Compare another', 'n')])
    check('DISKCOMP B: B: (one drive) of the two: three passes, another disk put in for the target said, "Compare OK"',
          "That isn't the TARGET diskette" in o and 'Compare OK' in o and said(o, 'E0'), o)
    tgt2 = unformatted()
    o = go(k, 'diskcopy b: b:', [('Press any key', put(srcdisk)), ('Press any key', put(tgt2)),
                                  ('Press any key', put(srcdisk)), ('Press any key', put(wrong)),  # pass 2: not the target
                                  ('Press any key', put(tgt2)), ('Press any key', put(srcdisk)),
                                  ('Press any key', put(tgt2)), ('Copy another', 'n')])
    check('DISKCOPY B: B: with another disk put in for the target at pass 2: said, asked again, that disk untouched',
          "That isn't the TARGET diskette" in o and said(o, 'E0') and no_serial(bytes(tgt2.img)) == no_serial(src)
          and bytes(wrong.img) == open(os.path.join(OUT, 'w.img'), 'rb').read(), o)

def t_720():
    s = data_disk('s7.img', size=720)
    k = boot(s)
    o = go(k, 'diskcopy b:', [('Press any key', ktest.ENTER), ('Copy another', 'n')])
    # (one drive letter: B: to the current drive, A:: the start-up disk, 1.44 MB, copied over)
    check('DISKCOPY B: with A: current: B: to A: (two drives), 720 KB: 9 sectors a track, exit code 0',
          '9 sectors/track, 2 side(s)' in o and said(o, 'E0') and 'Insert TARGET diskette in drive A:' in o, o)
    a = bytes(k.pc.drives[0].img)
    check('... A: (a 1.44 MB disk) formatted 720 KB as it is written (its BPB another layout), the copy whole',
          'Formatting while copying' in o and len(a) == 737280 and no_serial(a) == no_serial(open(s, 'rb').read()), (o, len(a)))

def t_bad():
    k = boot(blank('b2.img'))
    good = bytes(k.pc.drives[0].img)
    k.pc.drives[0].bad = {36 * 30 + 5, 36 * 30 + 18 + 2}
    o = go(k, 'diskcopy a: b:', [('Press any key', ktest.ENTER), ('Copy another', 'n')])
    dst = bytes(k.pc.drives[1].img)
    lba = [36 * 30 + 5, 36 * 30 + 20]
    check('a source with two bad sectors: "Unrecoverable read error on drive A:, side 0, track 30" and side 1, '
          'the copy goes on, exit code 1', 'Unrecoverable read error on drive A:, side 0, track 30' in o
          and 'Unrecoverable read error on drive A:, side 1, track 30' in o and said(o, 'E1'), o)
    check('... those two sectors zeros on the copy, the rest as the source',
          all(dst[n * 512:(n + 1) * 512] == bytes(512) for n in lba)
          and all(dst[n * 512:(n + 1) * 512] == good[n * 512:(n + 1) * 512] for n in range(1, 2880) if n not in lba), o)

def t_wp():
    k = boot(blank('b.img'))
    k.pc.drives[1].noid = set()                         # (formatted: written over)
    k.pc.drives[1].wp = True
    def unprotect(k): k.pc.drives[1].wp = False; k.key(ktest.ENTER, settle=False)
    o = go(k, 'diskcopy a: b:', [('Press any key', ktest.ENTER), ('write-protected', None), ('Press any key', unprotect),
                                  ('Copy another', 'n')])
    check('a write-protected target: said, the tab moved and a key: the copy made, exit code 0',
          'write-protected' in o and said(o, 'E0') and no_serial(bytes(k.pc.drives[1].img)) == no_serial(bytes(k.pc.drives[0].img)), o)

def t_esc():
    k = boot(blank('b.img'))
    dpt = bytes(k.pc.rd(0, 0x1E * 4, 4))
    o = go(k, 'diskcopy a: b:', [('Press any key', ktest.ENTER), ('Formatting while copying', None),
                                  ('Formatting while copying', lambda k: (k.pc.run_for(1), k.key('x', settle=False),
                                                                          k.key(chr(27), settle=False)))])
    check('Esc while it copies (after another key): "Copy process ended", exit code 2, INT 1Eh as it was',
          'Copy process ended' in o and said(o, 'E2') and bytes(k.pc.rd(0, 0x1E * 4, 4)) == dpt
          and 0 < len(k.pc.drives[1].formats) < 160, (o, len(k.pc.drives[1].formats)))
    o = go(k, 'diskcopy a: b:', [('Press any key', chr(27))])
    check('Esc at "Press any key": exit code 2, nothing written', said(o, 'E2') and 'Copying' not in o, o)

def t_kernel():
    k = boot(data_disk('kb.img'))
    shell(k, 'cd b:\\sub')
    o = go(k, 'diskcopy a: b:', [('Press any key', ktest.ENTER), ('Copy another', 'n')])
    o2 = shell(k, 'cd b:')
    o3 = shell(k, 'dir b:')
    check('B: in a directory of the disk copied over: its current directory the root after, the copy\'s files listed',
          said(o, 'E0') and 'B:\\' in o2 and 'SUB' not in o2 and 'DISKCOPY COM' in o3 and 'S        SYS' not in o3, (o2, o3))

def t_refused():
    k = boot()
    for line, want in (('diskcopy a: b:', 'Invalid drive'), ('diskcopy a: c:', 'Invalid drive'), ('diskcopy a: /x', 'Invalid parameter'),
                       ('diskcomp a: /v', 'Invalid parameter'), ('diskcopy a: b: c:', 'Invalid parameter')):
        o = go(k, line)
        check('%s: "%s", exit code 4' % (line.upper(), want), want in o and said(o, 'E4') and 'Insert' not in o, o)
    k = boot(blank('b.img'))
    k.pc.drives[1].noid = set()                         # (a source with no file system: zeros)
    a = bytes(k.pc.drives[0].img)
    o = go(k, 'diskcopy b: a:', [('Press any key', ktest.ENTER), ('Copy another', 'n')])
    check('a source with no layout in its boot sector: said, "Copy process ended", exit code 3, nothing written',
          'no layout this can copy' in o and 'Copy process ended' in o and said(o, 'E3') and bytes(k.pc.drives[0].img) == a
          and not k.pc.drives[0].formats, o)

def t_mt():
    import test_mt as M
    from test_kernel import Shell
    b = blank('mtb.img')
    k = M.boot('mtdc.img', b'MULTITASK=1\r\n', 88, os.path.join(SRC, 'DISKCOPY.COM'), b=b)
    sh = Shell(k)
    sh.run('start /w diskcopy.com a: b: > o.txt'); k.run_for(10)
    o = sh.run('type o.txt')
    check('with multitasking, DISKCOPY run as a task: refused ("Other tasks are running")',
          'Other tasks are running' in o and not k.pc.drives[1].formats, o)

if __name__ == '__main__':
    t0 = time.time()
    names = sys.argv[1:]
    for t in (t_two, t_one, t_720, t_bad, t_wp, t_esc, t_kernel, t_refused, t_mt):
        if not names or t.__name__[2:] in names: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
