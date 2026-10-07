"""HEADCLN.COM in the emulator: run from the Executive, the cleaning disk
swapped in (nothing on it can be read), 30 s of sweeps, then the boot disk
back.  Also: a readable disk left in by mistake, Esc at the first prompt,
and drive B:.

    python3 tests/test_headcln.py
"""
import os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, pcemu

OUT = tempfile.mkdtemp()
results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)) if detail and not cond else ''))

# every BIOS disk call: (unit, ah, cylinder, head)
CALLS = []
_o13 = pcemu.PC.int13
def _i13(s):
    cx, dx = s.r('cx'), s.r('dx')
    CALLS.append((dx & 0xFF, s.r('ah'), cx >> 8, dx >> 8))
    return _o13(s)
pcemu.PC.int13 = _i13

def cleaning_disk():
    d = pcemu.Floppy(bytes(1474560))
    d.bad = set(range(2880))            # not formatted: nothing reads
    d.changed = True
    return d

def tty(k): return ''.join(k.pc.tty)

def boot(b=None):
    img = mkimg.build(os.path.join(OUT, 'a.img'), [os.path.join(GOS, 'src', p) for p in ('GRIDOS.SYS', 'GRIDCMD.COM', 'HEADCLN.COM')])
    k = ktest.KPC(img, b, disk_model='real')
    k.start()
    return k, bytes(k.pc.drives[0].img)

def start_prog(k, args=''):
    k.pc.tty.clear()
    if args:
        k.key(ktest.CODE_P)
        k.key('headcln' + args)
        k.key(ktest.ENTER, settle=False)
    else:
        k.select('HEADCLN.COM'); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: 'press a key to start' in tty(k), 20)

def wait_for(k, text, sim_s):
    k.pc.run_until(lambda: text in tty(k), sim_s)
    return text in tty(k)

def t_clean():
    k, raw = boot()
    start_prog(k)
    check('starts and asks for the cleaning disk', 'put the cleaning disk in' in tty(k), tty(k)[-300:])
    bootdisk = k.pc.drives[0]
    k.pc.drives[0] = cleaning_disk()
    n0 = len(CALLS)
    k.key(ktest.ENTER, settle=False)
    t0 = k.pc.us
    done = wait_for(k, 'Take the cleaning disk out', 60)
    secs = (k.pc.us - t0) / 1e6
    calls = CALLS[n0:]
    cyls = {c for u, ah, c, h in calls if ah == 2}
    check('cleans for about 30 s, sweeping from cylinder 0 to 79 and back, on both sides',
          done and 29 <= secs <= 33 and 0 in cyls and 79 in cyls and len(cyls) >= 20
          and {h for u, ah, c, h in calls if ah == 2} == {0, 1} and 'Done' in tty(k),
          (done, secs, sorted(cyls), tty(k)[-400:]))
    check('never writes, formats or touches another drive',
          not [x for x in calls if x[1] not in (0, 2, 8, 0x15, 0x16)] and {u for u, *_ in calls} == {0}, calls[:10])
    # out with it, drying, own disk back
    k.pc.drives[0] = bootdisk; bootdisk.changed = True
    k.pc.run_for(3)
    check('then the drying count-down', 'Letting the heads dry' in tty(k), tty(k)[-200:])
    k.key(ktest.ENTER, settle=False)                  # skip the drying
    ok = wait_for(k, 'Put your own disk back', 5)
    k.key(ktest.ENTER, settle=False)
    k.settle(15)
    check('asks for your disk back, then returns to the Executive, the disk untouched',
          ok and any('HEADCLN.COM ended' in l for l in k.band()) and bytes(k.pc.drives[0].img) == raw
          and 'HEADCLN.COM' in k.exec_list(), (ok, k.band()))

def t_data_disk():
    k, raw = boot()
    start_prog(k)
    n0 = len(CALLS)
    k.key(ktest.ENTER, settle=False)                  # the boot disk is still in
    ok = wait_for(k, 'not a cleaning disk', 10)
    check('a readable disk left in: stops at once, says so, nothing written',
          ok and bytes(k.pc.drives[0].img) == raw and not [x for x in CALLS[n0:] if x[1] == 3], tty(k)[-300:])
    k.key(ktest.ENTER, settle=False); k.pc.run_for(1)
    k.key(ktest.ENTER, settle=False); k.settle(15)
    check('... and returns to the Executive', any('HEADCLN.COM ended' in l for l in k.band()), k.band())

def t_esc():
    k, raw = boot()
    start_prog(k)
    n0 = len(CALLS)
    k.key(chr(27), settle=False)
    k.settle(10)
    check('Esc at the first prompt: nothing done, no disk access by HEADCLN',
          'Nothing done' in tty(k) and not [x for x in CALLS[n0:] if x[1] == 2 and x[2] > 0], tty(k)[-200:])

def t_drive_b():
    b = mkimg.build(os.path.join(OUT, 'b.img'), [])
    k, raw = boot(b)
    start_prog(k, ' b: 10')
    rawb = bytes(k.pc.drives[1].img)
    k.pc.drives[1] = cleaning_disk()
    n0 = len(CALLS)
    k.key(ktest.ENTER, settle=False)
    t0 = k.pc.us
    done = wait_for(k, 'Take the cleaning disk out', 30)
    calls = [x for x in CALLS[n0:] if x[1] == 2]
    check('HEADCLN B: 10 cleans drive B: for 10 s and leaves A: alone',
          done and 9 <= (k.pc.us - t0) / 1e6 <= 12 and calls and {u for u, *_ in calls} == {1}
          and 'drive B:' in tty(k), (done, (k.pc.us - t0) / 1e6, calls[:5]))
    k.key(chr(27), settle=False)

if __name__ == '__main__':
    t0 = time.time()
    for t in (t_clean, t_data_disk, t_esc, t_drive_b):
        t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
