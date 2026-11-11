"""LABEL.COM in the emulator, from the command prompt: a floppy's label
shown, set at the question and on the command line, replaced, deleted
(Y/N), the root entry and the boot sector's label (DOS 4's BPB) as they
should be and the kernel's VOL showing it at once, the current directory
on that drive kept, a DOS 3 disk (no extended BPB: its boot sector left
alone), a full root, a write-protected disk, a disk changed at the
question, C: (through INT 25h/26h), multitasking, and what it refuses.

    python3 tests/test_label.py [name ...]
"""
import os, struct, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, pcemu, fatcheck, fat16img as F

OUT = tempfile.mkdtemp()
SRC = os.path.join(GOS, 'src')
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

def said(o, line): return any(l.strip() == line for l in o.split('\n'))
def out(k): return ''.join(k.pc.tty).replace('\r', '')

def boot(b=None, **kw):
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(SRC, f) for f in ('LODE.SYS', 'LCMD.COM', 'LABEL.COM')])
    k = ktest.KPC(img, b, **kw)
    k.start(); k.code_p()
    return k

def disk(name='b.img', files=('SUB\\',)):
    return mkimg.build(os.path.join(OUT, name), [os.path.join(SRC, 'LCMD.COM')] + list(files))

def run(k, line, answers=(), sim=30):
    """line at the prompt, each answer then Enter at its question -> what it printed, and E0/E1/E3"""
    k.pc.tty.clear()
    k.key(line); k.key(ktest.ENTER, settle=False)
    for a in answers:
        n = out(k).count('?')
        k.pc.run_until(lambda: out(k).count('?') > n, 20)
        if a is None: continue
        if a: k.key(a, settle=False)
        if a not in (chr(27),): k.key(ktest.ENTER, settle=False)
    k.settle(sim)
    o = out(k)
    for n in (1, 2, 3):
        k.key('if errorlevel %d echo L%d' % (n, n)); k.key(ktest.ENTER)
    lv = max([n for n in (1, 2, 3) if said(out(k)[len(o):], 'L%d' % n)] or [0])
    return o + '\nE%d\n' % lv

def root_label(img, rootsec=19, n=14):
    for i in range(0, n * 512, 32):
        e = img[rootsec * 512 + i:rootsec * 512 + i + 32]
        if e[0] == 0: return None
        if e[0] != 0xE5 and e[11] != 0x0F and e[11] & 8: return e
    return None

def t_spaces():
    """labels written by another system: spaces where the 8.3 split falls, a dot (which LABEL refuses):
    VOL, DIR and TREE read them through an extended FCB's search, as DOS's COMMAND does: the 11 bytes"""
    img_a = mkimg.build(os.path.join(OUT, 'sa.img'), [os.path.join(SRC, f) for f in ('LODE.SYS', 'LCMD.COM', 'TREE.COM')])
    outs = []
    for lab in (b'ABC     DEF', b'ABCDEFGH  I', b'AB      C  ', b'A          ', b'V1.0       ', b'V1      0  '):
        p = disk('sp.img')
        img = bytearray(open(p, 'rb').read())
        at = img.find(root_label(img), 19 * 512)
        img[at:at + 11] = lab
        open(p, 'wb').write(img)
        k = ktest.KPC(img_a, p)
        k.start(); k.code_p()
        run(k, 'cd b:\\sub')
        outs.append((lab, run(k, 'vol b:') + run(k, 'dir b:') + run(k, 'tree b:')))
    want = lambda lab: lab.decode().rstrip()
    check('VOL and DIR of labels with spaces anywhere in their 11 characters, or a dot: shown as on the disk (the '
          'trailing spaces aside), B:\\SUB current', all(o.count('Volume in drive B is %s\n' % want(lab)) == 2 for lab, o in outs), outs)
    check('... TREE too ("FOR VOLUME ...")', all(('FOR VOLUME %s\n' % want(lab)) in o for lab, o in outs), outs)

def t_floppy():
    k = boot(disk())
    o = run(k, 'label b:', ['newlab'])
    img = bytes(k.pc.drives[1].img)
    e = root_label(img)
    check('LABEL B:: the label and serial shown, the question; the new one in the root (attribute 08h) and the '
          'boot sector, exit code 0', 'Volume in drive B is LODESTONE' in o and 'Serial Number is' in o
          and '(11 characters, ENTER for none)?' in o and said(o, 'E0') and e and e[0:11] == b'NEWLAB     '
          and e[11] == 8 and img[0x2B:0x36] == b'NEWLAB     ' and fatcheck.check(img)[0] == [], (o, e))
    o = run(k, 'vol b:')
    check('... the kernel\'s VOL shows it at once', 'Volume in drive B is NEWLAB' in o, o)
    run(k, 'cd b:\\sub')
    o = run(k, 'label b:hello world')
    run(k, 'dir b:')                                    # (the disk read: mounted afresh, the new BPB label)
    o2 = run(k, 'cd b:')
    img = bytes(k.pc.drives[1].img)
    check('LABEL B:HELLO WORLD (on the command line, a space in it): replaces it, in the same entry; B:\'s current '
          'directory kept (B:\\SUB)', said(o, 'E0') and root_label(img)[0:11] == b'HELLO WORLD' and img[0x2B:0x36] == b'HELLO WORLD'
          and sum(1 for i in range(0, 14 * 512, 32) if img[19 * 512 + i + 11] == 8 and img[19 * 512 + i] not in (0, 0xE5)) == 1
          and 'B:\\SUB' in o2, (o, o2))
    o = run(k, 'vol b:')
    check('... VOL and DIR show it with its space (FIND FIRST\'s name keeps a label\'s inside spaces, as MS-DOS\'s)',
          'Volume in drive B is HELLO WORLD\n' in o and 'Volume in drive B is HELLO WORLD\n' in run(k, 'dir b:'), o)
    raw = bytes(k.pc.drives[1].img)
    o = run(k, 'label b:', ['', 'n'])
    check('Enter alone, then N at "Delete current volume label (Y/N)?": nothing written, exit code 0',
          'Delete current volume label (Y/N)?' in o and said(o, 'E0') and bytes(k.pc.drives[1].img) == raw, o)
    o = run(k, 'label b:', ['', 'y'])
    img = bytes(k.pc.drives[1].img)
    check('... Y: the label deleted, the boot sector\'s NO NAME', said(o, 'E0') and root_label(img) is None
          and img[0x2B:0x36] == b'NO NAME    ', o)
    o = run(k, 'vol b:')
    check('... VOL: no label', 'has no label' in o, o)
    raw = bytes(k.pc.drives[1].img)
    o = run(k, 'label b:', [''])
    check('no label, Enter alone: nothing to do, nothing written', said(o, 'E0') and 'has no label' in o
          and bytes(k.pc.drives[1].img) == raw and 'Delete' not in o, o)
    o = run(k, 'label b:', ['a.b', 'ok'])
    check('a label with a "." at the question: "Invalid characters", asked again', 'Invalid characters' in o
          and root_label(bytes(k.pc.drives[1].img))[0:11] == b'OK         ', o)
    o = run(k, 'label b:', ['', chr(27)])
    check('Esc at the Y/N question: exit code 3, the label as it was', said(o, 'E3')
          and root_label(bytes(k.pc.drives[1].img))[0:11] == b'OK         ', o)

def t_dos3():
    p = disk('d3.img')
    img = bytearray(open(p, 'rb').read())
    img[0x24:0x3E] = bytes(0x1A)                             # (DOS 3's BPB: nothing after 1Dh)
    for i in range(0, 14 * 512, 32):                         # (and no label in the root)
        if img[19 * 512 + i + 11] == 8: img[19 * 512 + i] = 0xE5
    open(p, 'wb').write(img)
    k = boot(p)
    raw = bytes(k.pc.drives[1].img)
    o = run(k, 'label b:dosthree')
    img = bytes(k.pc.drives[1].img)
    check('a DOS 3 disk (no extended BPB): the label in the root only, its boot sector as it was, no serial shown',
          said(o, 'E0') and root_label(img)[0:11] == b'DOSTHREE   ' and img[:512] == raw[:512], o)
    o = run(k, 'label b:')
    check('... shown (no serial number)', 'Volume in drive B is DOSTHREE' in o and 'Serial' not in o, o)

def t_full():
    f = F.Fat(2880, 1, 0, False, rootents=224, spt=18, heads=2)
    f.finish(f.tree([('F%03d.TXT' % i, 0x20, b'') for i in range(224)]))
    p = os.path.join(OUT, 'full.img'); open(p, 'wb').write(f.img)
    k = boot(p)
    raw = bytes(k.pc.drives[1].img)
    o = run(k, 'label b:full')
    check('no label and the root full: "no room for a label", exit code 1, nothing written',
          'no room for a label' in o and said(o, 'E1') and bytes(k.pc.drives[1].img) == raw, o)

def t_wp_changed():
    k = boot(disk())
    k.pc.drives[1].wp = True; raw = bytes(k.pc.drives[1].img)
    o = run(k, 'label b:x')
    check('write-protected: "Write protect error", exit code 1, nothing written',
          'Write protect error' in o and said(o, 'E1') and bytes(k.pc.drives[1].img) == raw, o)
    k = boot(disk())
    other = pcemu.Floppy(open(disk('o.img', ('OTHER\\',)), 'rb').read())
    raw2 = bytes(other.img)
    k.pc.tty.clear()
    k.key('label b:'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: 'ENTER for none)?' in out(k), 20)
    other.changed = True; k.pc.drives[1] = other           # another disk in, at the question
    k.key('mine'); k.key(ktest.ENTER, settle=False); k.settle(20)
    o = out(k)
    check('the disk changed at the question: "The disk was changed", the other disk untouched',
          'The disk was changed' in o and bytes(other.img) == raw2, o)
    k = boot(disk())
    k.pc.drives[1].no_changeline = True                    # (a drive that always says "changed")
    o = run(k, 'label b:same')
    check('... a drive without a change line: the same disk known by its boot sector and root, the label written',
          said(o, 'E0') and root_label(bytes(k.pc.drives[1].img))[0:11] == b'SAME       ', o)

def t_hd():
    fat = F.Fat(100 * 4 * 17 - 17, 1, 17, True, label='HDISK', spt=17, heads=4)
    fat.finish(fat.tree([('HDISK', 0x08, None), ('A.TXT', 0x20, b'hello\r\n' * 30)]))
    d = F.disk(100, 4, 17, 17, fat)
    ata = pcemu.Ata(cyls=100, heads=4, spt=17, disk=d)
    k = boot(ata=ata)
    o = run(k, 'label c:', ['harddisk'])
    v = F.Volume(ata.disk, 17)
    files, probs = v.files()
    b = v.sec(0)
    check('LABEL C: (through INT 25h/26h): shown, set; the root entry and the boot sector\'s label; the partition consistent',
          'Volume in drive C is HDISK' in o and said(o, 'E0') and v.sec(v.root)[0:11] == b'HARDDISK   '
          and b[0x2B:0x36] == b'HARDDISK   ' and probs == [] and files.get('\\A.TXT') == b'hello\r\n' * 30, (o, probs))
    o = run(k, 'vol c:')
    check('... VOL C: shows it at once', 'Volume in drive C is HARDDISK' in o, o)

def t_refused():
    k = boot(ems_pages=88)
    for line, want in (('label m:', 'temporary disk'), ('label r:', 'the ROM'), ('label q:', 'Invalid drive'),
                       ('label b:', 'Invalid drive'), ('label c:', 'Invalid drive'), ('label a:twelve-chars', 'Invalid characters'),
                       ('label a:a*b', 'Invalid characters')):
        o = run(k, line)
        check('%s: "%s", exit code 1' % (line.upper(), want), want in o and said(o, 'E1'), o)

def t_mt():
    import test_mt as M
    from test_kernel import Shell
    b = disk('mt.img')
    k = M.boot('mtlab.img', b'MULTITASK=1\r\n', 88, os.path.join(SRC, 'LABEL.COM'), b=b)
    raw = bytes(k.pc.drives[1].img)
    sh = Shell(k)
    sh.run('start /w label.com b:x > o.txt'); k.run_for(10)
    o = sh.run('type o.txt')
    check('with multitasking, LABEL run as a task: refused ("other tasks are running"), nothing written',
          'other tasks are running' in o and bytes(k.pc.drives[1].img) == raw, o)

def t_review():
    # regression cases, each held to
    img = mkimg.build(os.path.join(OUT, 'cap.img'), [os.path.join(SRC, f) for f in ('LODE.SYS', 'LCMD.COM', 'LABEL.COM')]
                      + [os.path.join(GOS, 'drivers', 'SCREEN.PRN')])
    k = ktest.KPC(img); k.start(); k.code_p()
    k.pc.tty.clear()
    k.key('label a:'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: 'ENTER for none)?' in out(k), 20)
    k.pc.prtsc(); k.settle(8)                           # (Shift-PrtSc: A:\SCREEN01.TXT, while LABEL waits)
    k.key('newlab'); k.key(ktest.ENTER, settle=False); k.settle(20)
    im = bytes(k.pc.drives[0].img)
    files = fatcheck.read_files(im)
    check('a file written to the root while LABEL waits (a screen capture): kept, the label beside it',
          'A:\\SCREEN01.TXT' in files and fatcheck.check(im)[0] == [] and b'NEWLAB     ' in im[19 * 512:33 * 512], sorted(files))
    k = boot(disk())
    o = run(k, 'label b:abcdefghijk ')
    check('an 11-character label with a space after it: taken (the space cut first)', said(o, 'E0')
          and (root_label(bytes(k.pc.drives[1].img)) or b'')[:11] == b'ABCDEFGHIJK', o)
    run(k, 'label b:xy')
    o = run(k, 'label ', answers=('',))
    check('LABEL with only a space after it, after a longer tail: the current drive, not a bad drive letter',
          'Invalid drive' not in o, o)

def t_redirect():
    # LABEL's output sent to a file on the disk it labels: the file open (the kernel's) while LABEL writes the
    # root and the boot sector through INT 13h; INT 21h F008h has the kernel take the disk as it now is
    for ext in (1, 0):
        p = disk('rd%d.img' % ext, files=('K.TXT=' + os.path.join(SRC, 'LCMD.COM'),))
        img = bytearray(open(p, 'rb').read())
        if not ext: img[0x24:0x3E] = bytes(0x1A)                 # (DOS 3's BPB)
        open(p, 'wb').write(img)
        k = boot(p)
        o = run(k, 'echo newlab| label b: > b:out.txt')
        o2 = run(k, 'type b:out.txt')
        im = bytes(k.pc.drives[1].img)
        f = fatcheck.read_files(im).get('A:\\OUT.TXT', b'')
        check('%s: "echo newlab| label b: > b:out.txt": the label set (root%s), OUT.TXT has LABEL\'s output, nothing '
              'asked, the disk consistent' % ('a DOS 4 BPB' if ext else 'a DOS 3 disk', ' and boot sector' if ext else ''),
              said(o, 'E0') and (root_label(im) or b'')[:11] == b'NEWLAB     ' and (not ext or im[0x2B:0x36] == b'NEWLAB     ')
              and b'Volume label' in f and 'Volume label' in o2 and 'Fail' not in o + o2 and fatcheck.check(im)[0] == [],
              (o, o2, f[:80], fatcheck.check(im)[0]))
        o = run(k, 'echo more>> b:out.txt')
        o = run(k, 'type b:out.txt')
        check('... the file written on after it (the same disk)', 'more' in o and 'Fail' not in o
              and fatcheck.check(bytes(k.pc.drives[1].img))[0] == [], o)

def t_swapq():
    # the disk swapped at LABEL's question, its output sent to a file on that disk and its answer a pipe from A:
    # (each read of it loads A:'s FAT, B:'s changed): the kernel's FAT of the first disk isn't written onto the
    # disk in (B:'s FAT goes to B: only after a look there: "Invalid disk change", LABEL's handler's Fail).  (LABEL
    # itself reads the disk in again after its question, the kernel having looked at it, and labels it)
    for x in ('2', '4'):
        p = disk('sq1.img', files=('K.TXT=' + os.path.join(SRC, 'LCMD.COM'),))
        d1 = open(p, 'rb').read()
        if x == '2':
            d = bytearray(open(disk('sq2.img', files=('SUB\\',)), 'rb').read()); d[0x27:0x2B] = b'\x12\x34\x56\x78'
        else:
            d = bytearray(d1); i = d.find(b'K       TXT', 19 * 512); d[i:i + 11] = b'Q       TXT'
        d = bytes(d); other = pcemu.Floppy(bytearray(d))
        k = boot(p); pc = k.pc; first = pc.drives[1]
        st = {'sw': 0}
        def hook(pc):
            if k.addr == k.i21 and pc.r('ah') == 0x0A and not st['sw']:
                st['sw'] = 1; other.changed = True; pc.drives[1] = other
        k.hooks.append(hook)
        pc.tty.clear()
        k.key('echo newlab| label b: > b:out.txt'); k.key(ktest.ENTER, settle=False)
        for _ in range(8):
            n = out(k).count('Fail?')
            pc.run_until(lambda: out(k).count('Fail?') > n or out(k).rstrip().endswith('>'), 40)
            if out(k).count('Fail?') == n: break
            k.key('f', settle=False)
        k.settle()
        o = out(k); probs = fatcheck.check(bytes(first.img))[0]; im = bytes(other.img)
        po = [q for q in fatcheck.check(im)[0] if 'lost clusters' not in q]
        check('the disk swapped at LABEL\'s question (%s), its output on it, its answer from A:: that disk\'s FAT '
              'and data not written (B:\'s FAT not put on it), the disk consistent; the first one with no '
              'cross-links' % ('another disk' if x == '2' else 'a copy, a name changed elsewhere'),
              st['sw'] and im[512:19 * 512] == d[512:19 * 512] and im[33 * 512:] == d[33 * 512:] and not po
              and not [q for q in probs if 'cross' in q], (o[-600:], probs, po))

def t_ownref():
    # another disk put in just after LABEL looked at the drive (at its first INT 13h read), its output sent to a
    # file on the first disk: LABEL labels the disk it read (the root and, a DOS 4 BPB, the boot sector: one
    # label), INT 21h F008h refuses (what was read isn't the kernel's disk), LABEL says so (ERRORLEVEL 1); nothing
    # of the kernel's written to that disk; with nothing open (no redirection) the kernel just takes the disk in
    for redir in (True, False):
        p = disk('or1.img', files=('K.TXT=' + os.path.join(SRC, 'LCMD.COM'),))
        d1 = open(p, 'rb').read()
        d2 = bytearray(open(disk('or2.img', files=('OTH.TXT=' + os.path.join(SRC, 'LCMD.COM'),)), 'rb').read())
        d2[0x27:0x2B] = b'\x12\x34\x56\x78'; d2 = bytes(d2)
        k = boot(p); pc = k.pc; first = pc.drives[1]; other = pcemu.Floppy(bytearray(d2))
        st = {'go': 0, 'sw': 0, 'own': []}
        o13 = pc.int13
        def i13():
            if st['go'] and not st['sw'] and pc.r('dl') == 1 and pc.r('ah') == 2 and pc.rd(0x60, k.Y['indos'], 1)[0] == 0:
                st['sw'] = 1; other.changed = True; pc.drives[1] = other
            return o13()
        pc.int13 = i13
        def hook(pc):
            if k.addr == k.i21 and pc.r('ah') == 0x4B: st['go'] = 1
            if k.addr == k.i21 and pc.r('ax') == 0xF008: st['own'].append(pc.r('cx'))
        k.hooks.append(hook)
        o = run(k, 'label b: newlab' + (' > b:out.txt' if redir else ''))
        im = bytes(other.img); i1 = bytes(first.img)
        check('%s: the disk read labelled (root and boot sector: NEWLAB), %s; that disk consistent, only its root\'s '
              'and boot sector\'s label written; the first disk%s' % (
                  'output to B:OUT.TXT (a file of the kernel\'s open on the first disk), another disk put in as '
                  'LABEL reads' if redir else '... no redirection (nothing open)',
                  'F008h refused (its root not told again), ERRORLEVEL 1' if redir else 'the disk in taken, '
                  'ERRORLEVEL 0', ' consistent (OUT.TXT empty: the message lost, the other disk in the drive)' if redir
                  else ' untouched'), st['sw'] and (root_label(im) or b'')[:11] == b'NEWLAB     '
              and im[0x2B:0x36] == b'NEWLAB     ' and fatcheck.check(im)[0] == []
              and im[512:19 * 512] == d2[512:19 * 512] and im[20 * 512:] == d2[20 * 512:]
              and (said(o, 'E1') and st['own'] == [19] and fatcheck.check(i1)[0] == [] if redir
                   else said(o, 'E0') and i1 == d1 and 'another disk' not in o), (o, st, fatcheck.check(im)[0]))

if __name__ == '__main__':
    t0 = time.time()
    names = sys.argv[1:]
    for t in (t_floppy, t_spaces, t_dos3, t_full, t_wp_changed, t_hd, t_refused, t_mt, t_review, t_redirect, t_swapq, t_ownref):
        if not names or t.__name__[2:] in names: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
