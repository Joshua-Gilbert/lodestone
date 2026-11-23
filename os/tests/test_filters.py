"""FIND, MORE, SORT and COMP in the emulator, from the command prompt:
each against what DOS 3.30's do, the output read whole from the
screen's teletype stream (a pipe, a redirected file, a named file),
switches, wildcards, the exit codes, and their edges (a line too long,
no LF at the end, Ctrl-Z, 63 KB, ten mismatches).  A read that fails
(Fail at the prompt, or the kernel's own INT 24h), a full disk behind
'>' or a pipe and a write that fails (a write-protected disk), each
said; NUL, the screen and pipes still taking all.

    python3 tests/test_filters.py
"""
import os, struct, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, fatcheck, fat16img as F

OUT = tempfile.mkdtemp()
SRC = os.path.join(GOS, 'src')
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

def f(name, data):
    p = os.path.join(OUT, name); open(p, 'wb').write(data)
    return '%s=%s' % (name, p)

LIST = b''.join(b'line %02d %s\r\n' % (i, [b'apple', b'Banana', b'cherry COM', b'date'][i % 4]) for i in range(1, 21))
WORDS = b'pear\r\nApple\r\nbanana\r\n\r\nCherry\r\napple\r\nzebra\r\n  indented\r\nMango'   # (no LF at the end)

def boot(*extra):
    files = [os.path.join(SRC, n) for n in ('LODE.SYS', 'LCMD.COM', 'FIND.COM', 'MORE.COM', 'SORT.COM', 'COMP.COM')]
    files += [f('LIST.TXT', LIST), f('WORDS.TXT', WORDS)] + list(extra)
    img = mkimg.build(os.path.join(OUT, 'a.img'), files)
    k = ktest.KPC(img)
    k.start(); k.code_p()
    return k

def out(k): return ''.join(k.pc.tty).replace('\r', '')

def said(o, line): return any(l.strip() == line for l in o.split('\n'))

def answer_f(k, sim):
    """each "Abort, Retry, Fail?" answered F, till the prompt is back -> how many were asked"""
    n = 0
    while n < 8:
        k.pc.run_until(lambda: out(k).count('Fail?') > n or out(k).rstrip().endswith('A:\\>') or k.pc.crash, sim)
        if out(k).count('Fail?') <= n: break
        n += 1; k.pc.keys.append(ord('f'))
    return n

def run(k, line, *keys, sim=30, fails=False):
    """line at the prompt, keys after (each once the machine waits) -> what it printed (the line itself left
    out), and E<exit code> on a line of its own.  fails: each critical error answered F"""
    k.pc.tty.clear()
    k.key(line); k.key(ktest.ENTER, settle=not fails)
    if fails: answer_f(k, sim)
    for x in keys: k.key(x)
    k.settle(sim)
    o = out(k)
    o = o[o.find('\n') + 1:] if '\n' in o else o
    for n in (1, 2, 3):
        k.key('if errorlevel %d echo L%d' % (n, n)); k.key(ktest.ENTER)
    t = out(k)
    return o + '\nE%d\n' % sum(said(t[t.find(o) + len(o):] if o else t, 'L%d' % n) for n in (1, 2, 3))

def body(o):
    """the program's output, before the prompt it returns to"""
    return o[:o.rfind('A:\\>')] if 'A:\\>' in o else o

def lines(data): return [l for l in data.decode('latin-1').replace('\r', '').split('\n')]

def sector_of(img, name, off):
    """the sector holding byte off of the root's file name"""
    v = F.Volume(bytes(img), 0)
    cl = next(c for n, a, c, s in v.entries(0) if n == name)
    return v.data + (v.chain(cl)[0][off // (512 * v.spc)] - 2) * v.spc + off % (512 * v.spc) // 512

def kernel24(k, line, **kw):
    """run with the kernel's own INT 24h in the vector (a critical error failed, nobody asked: as from the
    Executive), LCMD's put back after"""
    old = k.pc.rd(0, 0x24 * 4, 4)
    k.pc.wr(0, 0x24 * 4, struct.pack('<HH', k.Y['int24'], 0x60))
    try: return run(k, line, **kw)
    finally: k.pc.wr(0, 0x24 * 4, old)

def files_a(k): return fatcheck.read_files(bytes(k.pc.drives[0].img))

def t_find():
    k = boot(f('TWO.TXT', b'one COM\r\ntwo\r\nthree COM\r\n'))
    want = [l for l in lines(LIST) if 'COM' in l]
    o = run(k, 'find "COM" list.txt')
    got = [l for l in body(o).split('\n') if l.strip()]
    check('FIND "COM" LIST.TXT: "---------- LIST.TXT", then the lines with COM in them, as they are; exit 0',
          got[:1] == ['---------- LIST.TXT'] and got[1:] == want and said(o, 'E0'), o)
    o = run(k, 'find /v "COM" list.txt')
    check('/V: the lines without it', [l for l in body(o).split('\n') if l.strip()][1:] == [l for l in lines(LIST) if l and 'COM' not in l], o)
    o = run(k, 'find /c "COM" list.txt')
    check('/C: "---------- LIST.TXT: 5"', '---------- LIST.TXT: 5' in o, o)
    o = run(k, 'find /n "COM" list.txt')
    check('/N: "[2]line 02 cherry COM" (each line\'s number in the file)', '[2]line 02 cherry COM' in o and '[18]line 18 cherry COM' in o, o)
    o = run(k, 'find "com" list.txt')
    check('the case as given: "com" finds nothing; exit 1', 'line' not in body(o) and said(o, 'E1'), o)
    o = run(k, 'type list.txt | find "Banana"')
    check('in a pipe: the lines, no file header', '---' not in o and body(o).count('Banana') == 5, o)
    o = run(k, 'find /c "Banana" < list.txt')
    check('/C of its input: the count alone', said(body(o), '5'), o)
    o = run(k, 'find "COM" *.txt')
    check('wildcards: each file, its header, its lines', '---------- LIST.TXT' in o and '---------- TWO.TXT' in o
          and 'three COM' in o and 'line 02 cherry COM' in o, o)
    o = run(k, 'find "x" nosuch.txt')
    check('a file not there: "File not found - NOSUCH.TXT", exit 2', 'FILE NOT FOUND - NOSUCH.TXT' in o.upper() and said(o, 'E2'), o)
    o = run(k, 'find COM list.txt')
    check('no quotes: "no string", exit 2', 'no string' in o and said(o, 'E2'), o)
    k2 = boot(f('Q.TXT', b'say "hi" now\r\nno quotes\r\n'), f('LONG.TXT', b'a' * 1500 + b'XYZ\r\nshort XYZ\r\n'))
    o = run(k2, 'find """hi""" q.txt')
    check('"" in the string is one ": FIND """hi""" finds say "hi" now', 'say "hi" now' in o and 'no quotes' not in o, o)
    o = run(k2, 'find /c "XYZ" long.txt')
    check('a line longer than 1,023 characters: taken as two (both counted once each where XYZ is)', 'LONG.TXT: 2' in o, o)

def t_more():
    many = b''.join(b'row %02d\r\n' % i for i in range(1, 61))
    k = boot(f('MANY.TXT', many), f('WIDE.TXT', b'x' * 100 + b'\r\n' + b''.join(b'w%02d\r\n' % i for i in range(30))))
    k.pc.tty.clear()
    k.key('more < many.txt'); k.key(ktest.ENTER)
    k.settle(10)
    o1 = out(k)
    k.key(' '); k.settle(10)
    o2 = out(k)
    k.key(' '); k.settle(10)
    o3 = out(k)
    check('MORE < MANY.TXT: 24 rows, "-- More --", a key, 24 more, a key, the rest; nothing lost',
          'row 24' in o1 and 'row 25' not in o1 and o1.count('-- More --') == 1 and 'row 48' in o2 and 'row 49' not in o2
          and 'row 60' in o3 and all(('row %02d' % i) in o3 for i in range(1, 61)), (o1[-200:], o2[-200:], o3[-200:]))
    k.pc.tty.clear()
    k.key('type wide.txt | more'); k.key(ktest.ENTER); k.settle(10)
    o = out(k)
    check('a line of 100 characters takes two rows: the first stop after 22 more', 'w21' in o and 'w22' not in o, o[-200:])
    k.key(chr(3)); k.settle(10)
    o = out(k)
    check('... Ctrl-C there: the end, back at the prompt', 'w29' not in o and o.rstrip().endswith('A:\\>'), o[-200:])
    o = run(k, 'more wide.txt', ' ', ' ')
    check('MORE WIDE.TXT (a file named): the same', 'w29' in o and '-- More --' in o, o[-200:])

def sortkey(l, col=0): return l[col:].upper()

def t_sort():
    k = boot(f('BIG.TXT', b'x' * 70 + b'\r\n' * 1 + (b'y' * 70 + b'\r\n') * 1000))
    ws = [l for l in lines(WORDS)]
    o = run(k, 'sort < words.txt')
    got = body(o).split('\n')
    check('SORT < WORDS.TXT: the lines in order, capitals or not, the empty one first, the last (no LF) too; exit 0',
          got[:len(ws)] == sorted(ws, key=sortkey) and said(o, 'E0'), (got, sorted(ws, key=sortkey)))
    o = run(k, 'sort /r < words.txt')
    check('/R: the other way', body(o).split('\n')[:len(ws)] == sorted(ws, key=sortkey, reverse=True), body(o))
    o = run(k, 'sort /+3 < words.txt')
    got = body(o).split('\n')[:len(ws)]
    check('/+3: from the third column', [sortkey(l, 2) for l in got] == sorted(sortkey(l, 2) for l in ws), got)
    run(k, 'sort < list.txt > sorted.txt')
    data = fatcheck.read_files(bytes(k.pc.drives[0].img)).get('A:\\SORTED.TXT', b'')
    check('into a file: CR LF after each line, the sorted lines', data == b''.join(l.encode() + b'\r\n'
          for l in sorted([l for l in lines(LIST) if l], key=sortkey)), data[:200])
    k2 = boot(f('Z.TXT', b'b\r\na\r\n\x1ajunk\r\nzz\r\n'))
    o = run(k2, 'sort < z.txt')
    check('Ctrl-Z: the end of the input', body(o).split('\n')[:3] == ['a', 'b', ''] and 'junk' not in o, o)
    big = b''.join(b'%05d %s\r\n' % (i, b'q' * 60) for i in range(1100))
    k3 = boot(f('HUGE.TXT', big))
    o = run(k3, 'sort < huge.txt')
    check('more than 63 KB: "SORT: Insufficient memory", exit 1', 'Insufficient memory' in o and said(o, 'E1'), o[-300:])
    o = run(k3, 'sort /x < words.txt')
    check('a bad switch: said, exit 1', 'Invalid parameter' in o and said(o, 'E1'), o)

def t_comp():
    a = bytes(range(256)) * 8
    b = bytearray(a); b[5] ^= 0xFF; b[1000] = 0x42
    many = bytearray(a)
    for i in range(0, 2048, 100): many[i] ^= 1
    k = boot(f('A.BIN', a), f('A2.BIN', a), f('B.BIN', bytes(b)), f('M.BIN', bytes(many)), f('S.BIN', a[:100]),
             f('X.TXT', b'same\r\n'), f('X.BAK', b'same\r\n'), f('Y.TXT', b'one\r\n'), f('Y.BAK', b'two\r\n'), 'SUB\\',
             'SUB\\X.TXT=' + os.path.join(OUT, 'X.TXT'))
    o = run(k, 'comp a.bin a2.bin', 'n')
    check('COMP A.BIN A2.BIN: "A.BIN and A2.BIN", "Files compare OK", "Compare more files (Y/N)?", exit 0',
          'A.BIN and A2.BIN' in o and 'Files compare OK' in o and 'Compare more files (Y/N)?' in o and said(o, 'E0'), o)
    o = run(k, 'comp a.bin b.bin', 'n')
    check('differences: "Compare error at OFFSET 5 / 3E8", each file\'s byte in hex; exit 1',
          'Compare error at OFFSET 0005' in o and 'file1 = 05' in o and 'file2 = FA' in o and 'OFFSET 03E8' in o
          and 'file1 = E8' in o and 'file2 = 42' in o and said(o, 'E1'), o)
    o = run(k, 'comp a.bin m.bin', 'n')
    check('ten differences: "10 Mismatches - ending compare"', o.count('Compare error') == 10 and '10 Mismatches' in o, o)
    o = run(k, 'comp a.bin s.bin', 'n')
    check('different sizes: "Files are different sizes", not compared; exit 1', 'Files are different sizes' in o
          and 'Compare error' not in o and said(o, 'E1'), o)
    o = run(k, 'comp *.txt *.bak', 'n')
    check('COMP *.TXT *.BAK: X.TXT with X.BAK (the same), Y.TXT with Y.BAK (not)', 'X.TXT and X.BAK' in o
          and 'Y.TXT and Y.BAK' in o and 'Files compare OK' in o and 'Compare error' in o, o)
    o = run(k, 'comp x.txt sub', 'n')
    check('COMP X.TXT SUB: the same name in the directory', 'X.TXT and SUB\\X.TXT' in o and 'Files compare OK' in o, o)
    o = run(k, 'comp a.bin nosuch.bin', 'n')
    check('a second file not there: "File not found - NOSUCH.BIN", exit 2', 'File not found - NOSUCH.BIN' in o and said(o, 'E2'), o)
    p = os.path.join(OUT, 'ANS.TXT'); open(p, 'wb').write(b'a.bin\r\na2.bin\r\nN')
    k2 = boot(f('A.BIN', a), f('A2.BIN', a), 'ANS.TXT=' + p)
    o = run(k2, 'comp < ans.txt')
    check('no names: asked for ("Enter primary file name"), answered from a file, then N', 'Enter primary file name' in o
          and 'Enter 2nd file name' in o and 'Files compare OK' in o and said(o, 'E0'), o)

RBIG = b''.join(b'%05d %s\r\n' % (i, b'mark' if i % 100 == 0 else b'line') for i in range(2000))   # 24,000 bytes
RCR = b'ab\r' * 9000                                    # (no LF: MORE never stops for a key)
def t_rerr():
    # a sector of each file unreadable, at byte 20,000: past FIND's first 16 KB read, SORT's and MORE's fourth 4 KB
    k = boot(f('BIG.TXT', RBIG), f('CR.TXT', RCR), f('TWO.TXT', b'one mark\r\ntwo\r\n'))
    k.pc.drives[0].bad = {sector_of(k.pc.drives[0].img, n, 20000) for n in ('BIG.TXT', 'CR.TXT')}
    first = [l for l in lines(RBIG[:16384]) if 'mark' in l]
    for how, go in (('Fail at the prompt', lambda l: run(k, l, fails=True)), ('the kernel\'s INT 24h, nobody asked',
                                                                               lambda l: kernel24(k, l))):
        o = go('find "mark" big.txt two.txt')
        got = [l for l in body(o).split('\n') if 'mark' in l]
        check('FIND "mark" BIG.TXT TWO.TXT, BIG.TXT unreadable part way (%s): its lines before it, "FIND: Read error in '
              'BIG.TXT", then TWO.TXT\'s; exit 2' % how, got == first + ['one mark'] and said(o, 'FIND: Read error in BIG.TXT')
              and o.index('Read error') < o.index('---------- TWO.TXT') and said(o, 'E2')
              and ('Fail?' in o) == how.startswith('Fail'), o[-600:])
        o = go('find "mark" < big.txt')
        check('FIND "mark" < BIG.TXT (%s): "FIND: Read error in standard input", exit 2' % how,
              [l for l in body(o).split('\n') if 'mark' in l] == first and said(o, 'FIND: Read error in standard input')
              and said(o, 'E2'), o[-600:])
        o = go('sort < big.txt > s.txt')
        check('SORT < BIG.TXT > S.TXT (%s): "SORT: Read error", nothing written (not the first 16 KB sorted), exit 1' % how,
              said(o, 'SORT: Read error') and files_a(k).get('A:\\S.TXT') == b'' and said(o, 'E1'),
              (o[-600:], len(files_a(k).get('A:\\S.TXT', b''))))
        o = go('more < cr.txt > m.txt')
        check('MORE < CR.TXT > M.TXT (%s): what it read before it written, "MORE: Read error", exit 1' % how,
              said(o, 'MORE: Read error') and files_a(k).get('A:\\M.TXT') == RCR[:16384] and said(o, 'E1'),
              (o[-600:], len(files_a(k).get('A:\\M.TXT', b''))))
    o = run(k, 'more cr.txt', fails=True)
    check('MORE CR.TXT (a file named, Fail): what it read, the question, "MORE: Read error", exit 1',
          said(o, 'MORE: Read error') and o.index('Fail?') > o.index('abab') and said(o, 'E1'), o[-300:])

def boot_full(leave, *extra):
    """boot() with A: holding only leave bytes more (a PAD.DAT over the rest)"""
    k = boot(*extra)
    v = F.Volume(bytes(k.pc.drives[0].img), 0)
    return boot(*(list(extra) + [f('PAD.DAT', bytes(v.free() * 512 * v.spc - leave))]))

def t_wfull():
    # 4 KB left on A:: each one's output into a file there comes up short (a fresh disk each)
    full = lambda: boot_full(4096, f('BIG.TXT', RBIG), f('CR.TXT', RCR))
    k = full()
    o = run(k, 'find "line" big.txt > out.txt')
    got = files_a(k).get('A:\\OUT.TXT', b'')
    check('FIND "line" BIG.TXT > OUT.TXT, 4 KB left: "FIND: Insufficient disk space", exit 2, what fitted written',
          said(o, 'FIND: Insufficient disk space') and said(o, 'E2') and 0 < len(got) <= 4096
          and got.startswith(b'\r\n---------- BIG.TXT\r\n00001 line\r\n'), (o[-300:], len(got), got[:60]))
    k = full()
    o = run(k, 'sort < big.txt > s.txt')
    check('SORT < BIG.TXT > S.TXT, 4 KB left: "SORT: Insufficient disk space", exit 1 (MS-DOS 3.30\'s)',
          said(o, 'SORT: Insufficient disk space') and said(o, 'E1'), (o[-300:], len(files_a(k).get('A:\\S.TXT', b''))))
    k = full()
    o = run(k, 'more < cr.txt > m.txt')
    check('MORE < CR.TXT > M.TXT, 4 KB left: "MORE: Insufficient disk space", exit 1',
          said(o, 'MORE: Insufficient disk space') and said(o, 'E1'), (o[-300:], len(files_a(k).get('A:\\M.TXT', b''))))
    k = full()
    o = run(k, 'sort < big.txt | find "mark"')
    check('SORT < BIG.TXT | FIND "mark", 4 KB left: the pipe\'s file fills: "SORT: Insufficient disk space"',
          said(o, 'SORT: Insufficient disk space'), o[-300:])
    k = full()
    o = run(k, 'find /n "mark" big.txt > n.txt')
    check('... with room (FIND /N "mark", 20 lines): "[1]00000 mark" ... written whole, exit 0', said(o, 'E0')
          and files_a(k).get('A:\\N.TXT') == b'\r\n---------- BIG.TXT\r\n' + b''.join(b'[%d]%05d mark\r\n' % (i + 1, i)
                                                                        for i in range(0, 2000, 100)), o[-300:])
    # NUL, the screen and a pipe take all: nothing said
    k = boot()
    o = run(k, 'find "COM" list.txt > nul')
    check('FIND "COM" LIST.TXT > NUL: nothing printed, exit 0', body(o).strip() == '' and said(o, 'E0'), o)
    o = run(k, 'sort < words.txt > nul')
    check('SORT < WORDS.TXT > NUL: nothing printed, exit 0', body(o).strip() == '' and said(o, 'E0'), o)
    o = run(k, 'more < words.txt > nul')
    check('MORE < WORDS.TXT > NUL: nothing printed, exit 0', body(o).strip() == '' and said(o, 'E0'), o)
    o = run(k, 'sort < words.txt > w.txt')
    check('SORT < WORDS.TXT > W.TXT: its empty line a write of CR LF alone, no "disk space", the file whole, exit 0',
          files_a(k).get('A:\\W.TXT') == b''.join(l.encode() + b'\r\n' for l in sorted(lines(WORDS), key=sortkey))
          and body(o).strip() == '' and said(o, 'E0'), (o, files_a(k).get('A:\\W.TXT')))
    o = run(k, 'sort < words.txt | find /v "zzz"')
    check('SORT < WORDS.TXT | FIND /V "zzz": all 9 lines, the empty one too, exit 0', body(o).split('\n')[:9]
          == sorted(lines(WORDS), key=sortkey) and 'Insufficient' not in o and said(o, 'E0'), o)
    o = run(k, 'more < list.txt')
    check('MORE < LIST.TXT to the screen: its 20 lines, exit 0', [l for l in body(o).split('\n') if l.strip()]
          == [l for l in lines(LIST) if l] and said(o, 'E0'), o)
    o = run(k, 'type list.txt | find "COM" | sort /r')
    check('TYPE LIST.TXT | FIND "COM" | SORT /R: the COM lines, the other way round, exit 0',
          [l for l in body(o).split('\n') if l.strip()] == sorted([l for l in lines(LIST) if 'COM' in l], key=sortkey, reverse=True)
          and 'Insufficient' not in o and said(o, 'E0'), o)
    o = run(k, 'find /c "COM" list.txt | more')
    check('FIND /C "COM" LIST.TXT | MORE: "---------- LIST.TXT: 5", exit 0', said(o, '---------- LIST.TXT: 5')
          and 'Insufficient' not in o and said(o, 'E0'), o)

def protect_at_write(k):
    """A:'s write-protect tab on once the program run writes to standard output (after its redirection's file was
    made): the kernel's writes of it fail"""
    st = {'exec': False}
    def h(pc):
        if k.addr != k.i21 or pc.r('cs') != 0x60: return
        if pc.r('ax') >> 8 == 0x4B: st['exec'] = True
        elif st['exec'] and pc.r('ax') >> 8 == 0x40 and pc.r('bx') == 1: k.pc.drives[0].wp = True
    k.hooks.append(h)

def t_werr():
    # output into a file on a disk whose writes fail (the tab on after it was made): "Write error", not "disk space"
    for tool, line, lv in (('FIND', 'find "line" big.txt > out.txt', 2), ('SORT', 'sort < big.txt > s.txt', 1),
                           ('MORE', 'more < cr.txt > m.txt', 1)):
        for how in ('Fail at the prompt', 'the kernel\'s INT 24h, nobody asked'):
            k = boot(f('BIG.TXT', RBIG), f('CR.TXT', RCR))
            protect_at_write(k)
            o = run(k, line, fails=True) if how.startswith('Fail') else kernel24(k, line)
            check('%s, A: write-protected once its output was made (%s): "%s: Write error", not "Insufficient disk '
                  'space", exit code %d' % (line.upper(), how, tool, lv), said(o, '%s: Write error' % tool)
                  and 'Insufficient' not in o and said(o, 'E%d' % lv), o[-600:])

def t_review():
    # regression cases, each held to
    k = boot(f('NL.TXT', b'zz\r\nab\0cd\r\naa\r\n'), f('ST.TXT', b'1b\r\n2a\r\n3a\r\n4a\r\n5a\r\n'),
             f('L1023.TXT', b'a' * 1023 + b'\r\nnext\r\n'), f('LF.TXT', b'xa1\nxa2\n'))
    run(k, 'sort < nl.txt > s1.txt')
    got = fatcheck.read_files(bytes(k.pc.drives[0].img)).get('A:\\S1.TXT')
    check('SORT: a NUL in a line is a character: the line whole after it', got == b'aa\r\nab\0cd\r\nzz\r\n', got)
    o = run(k, 'sort /+2 < st.txt')
    check('SORT: equal keys keep their input order (/+2: 2a 3a 4a 5a 1b)', body(o).split('\n')[:5] == ['2a', '3a', '4a', '5a', '1b'], o)
    o = run(k, 'sort /x > s2.txt')
    got = fatcheck.read_files(bytes(k.pc.drives[0].img)).get('A:\\S2.TXT')
    check('SORT: its messages to standard error (on the screen, not in the file)', 'Invalid parameter' in o and got == b'', (o, got))
    k.pc.tty.clear()
    k.key('sort'); k.key(ktest.ENTER)
    for x in ('pear', 'apple'): k.key(x); k.key(ktest.ENTER)
    k.key(chr(0x1A)); k.key(ktest.ENTER); k.settle(10)
    o = out(k)
    check('SORT at the keyboard: Ctrl-Z (and Enter) ends the input, the lines sorted', o.rstrip().endswith('A:\\>')
          and o.index('apple', o.index('pear')) < o.rindex('pear'), o)
    o = run(k, 'find /c /v "zzz" l1023.txt')
    check('FIND: a 1,023-character line and its CR is one line', 'L1023.TXT: 2' in o, o)
    k.pc.tty.clear(); run(k, 'find "xa" lf.txt')
    raw = ''.join(k.pc.tty)
    check('FIND: lines that had only LF go out with CR LF; a blank line before the header',
          'xa1\r\nxa2\r\n' in raw and '\r\n\r\n---------- LF.TXT' in raw, repr(raw[:200]))
    a = bytes(range(256)) * 4; b = bytearray(a); b[3] = 9
    k2 = boot(f('A.BIN', a), f('A2.BIN', a), f('B.BIN', bytes(b)), f('X.TXT', b'1\r\n'), f('X.BAK', b'2\r\n'),
              f('ANS2.TXT', b'a.bin\r\na2.bin\r\nY\r\na.bin\r\nb.bin\r\nN\r\n'))
    o = run(k2, 'comp < ans2.txt')
    check('COMP: answers from a CR LF file, Y between: both pairs compared, then N', 'A.BIN and A2.BIN' in o
          and 'A.BIN and B.BIN' in o and 'Files compare OK' in o and 'Compare error at OFFSET 0003' in o, o)
    k2.pc.tty.clear()
    k2.key('comp nosuch.bin a.bin'); k2.key(ktest.ENTER)
    k2.key('y'); k2.key('x.txt'); k2.key(ktest.ENTER); k2.key('x.bak'); k2.key(ktest.ENTER); k2.key('n'); k2.settle(10)
    o = out(k2)
    k2.key('if errorlevel 2 echo L2'); k2.key(ktest.ENTER)
    t = out(k2)
    check('COMP: a file not found, then a difference: the exit code stays 2', 'File not found' in o
          and 'X.TXT and X.BAK' in o and said(t[len(o):], 'L2'), t[-400:])
    many = b''.join(b'row %02d\r\n' % i for i in range(1, 61))
    k3 = boot(f('MANY.TXT', many))
    k3.pc.tty.clear()
    k3.key('more < many.txt', settle=False); k3.key(ktest.ENTER, settle=False); k3.key(chr(3), settle=False); k3.settle(10)
    o = out(k3)
    check('MORE: a Ctrl-C typed while a screen is written ends it at the prompt', 'row 25' not in o
          and o.rstrip().endswith('A:\\>'), o[-200:])

if __name__ == '__main__':
    t0 = time.time()
    names = sys.argv[1:]
    for t in (t_find, t_more, t_sort, t_comp, t_review, t_rerr, t_wfull, t_werr):
        if not names or t.__name__[2:] in names: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
