"""HDPROBE.COM (tools/) under Grid-OS in pcemu, against the 1520's internal
hard disk as pcemu.Ata plays it: absent, a working Conner the BIOS knows, a
CompactFlash card it doesn't, unformatted, stuck busy, still spinning up,
heads that can't find track 0 or their way, a failed self-test, a dead
interrupt line, a disk that doesn't turn; and HDPROBE /X, the exercise.

    python3 tests/test_hdprobe.py [name ...]
"""
import os, re, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
TOOLS = os.path.join(os.path.dirname(GOS), 'tools')
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, fatcheck, pcemu
OUT = os.environ.get('KOUT', os.path.join(__import__('tempfile').gettempdir(), 'gridos-hd'))
os.makedirs(OUT, exist_ok=True)
PROBE = os.path.join(TOOLS, 'HDPROBE.COM')

def build():
    subprocess.run(['nasm', '-f', 'bin', '-i', TOOLS + '/', '-o', PROBE, os.path.join(TOOLS, 'HDPROBE.ASM')], check=True)

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:900]) if detail and not cond else ''))

def mbr():
    """A partition table: one 40 MB DOS partition, as FDISK would make it."""
    b = bytearray(512)
    b[446:462] = struct.pack('<BBBBBBBBII', 0x80, 1, 1, 0, 0x04, 4, 0xD1, 0xD0, 17, 83028)
    b[510:512] = b'\x55\xAA'
    return bytes(b)

def probe(name, ata):
    """Run HDPROBE; -> (its report, the files it left, simulated seconds)."""
    img = mkimg.build(os.path.join(OUT, name + '.img'), [os.path.join(GOS, 'src', 'GRIDOS.SYS'), PROBE])
    k = ktest.KPC(img, ata=ata); k.start()
    if ata: del ata.cmds[:]                         # (the kernel's own look at it, booting)
    t0 = k.pc.us
    k.run_file('HDPROBE.COM', 120)
    files = fatcheck.read_files(bytes(k.pc.drives[0].img))
    rep = files.get('A:\\HDPROBE.TXT', b'').decode('latin-1')
    print('   --- %s (%.1f s) ---' % (name, (k.pc.us - t0) / 1e6))
    for l in rep.splitlines(): print('   ' + l)
    ok = not k.crashed and k.pc.mode() == 0x40 and any('HDPROBE.COM ended' in l for l in k.band())
    return rep, files, (k.pc.us - t0) / 1e6, ok, k

def probe_x(name, ata, stop_at=None):
    """HDPROBE /X from the command prompt (CODE-P); stop_at: a key once the
    report has that text.  -> (report, simulated seconds, ok, k)"""
    img = mkimg.build(os.path.join(OUT, name + '.img'), [os.path.join(GOS, 'src', 'GRIDOS.SYS'), PROBE,
                                                          os.path.join(GOS, 'src', 'GRIDCMD.COM')])
    k = ktest.KPC(img, ata=ata); k.start()
    del ata.cmds[:]                                 # (the kernel's own look at it, booting)
    k.key(ktest.CODE_P)
    k.key('hdprobe /x'); k.key(ktest.ENTER, settle=False)
    tty = lambda: ''.join(k.pc.tty)
    t0 = k.pc.us
    if stop_at:
        k.pc.run_until(lambda: stop_at in tty() or k.pc.crash, 120)
        k.pc.keys.append(0x1071)                        # q
    back = lambda: 'Done.' in tty() and tty().rfind('>') > tty().rfind('Done.')
    ktest.run_answering(k.pc, back, 240)
    files = fatcheck.read_files(bytes(k.pc.drives[0].img))
    rep = files.get('A:\\HDPROBEX.TXT', b'').decode('latin-1')
    k.plain = files.get('A:\\HDPROBE.TXT')
    sec = (k.pc.us - t0) / 1e6
    print('   --- %s (%.1f s) ---' % (name, sec))
    for l in rep.splitlines(): print('   ' + l)
    return rep, sec, back() and not k.crashed, k

def t_absent():
    rep, f, sec, ok, k = probe('absent', None)
    check('no drive: back in the Executive, report written', ok and rep, k.band())
    check('no drive: every register FF, "nothing answers", the rest skipped quickly',
          'nothing answers' in rep and 'No drive answers at 1F0h' in rep and '[4]' not in rep and sec < 10, sec)
    check('no drive: the BIOS view (backplane, CMOS 12h 00, no INT 13h disk)',
          'CMOS 12h (hard disk type) = 00' in rep and 'the BIOS has no hard disk' in rep)

def t_floating():
    """No drive, and the bus floats: what Joshua's 1520 showed (2026-10-07):
    registers 75h, alt status A6h, no echo, garbage IDENTIFY in HDPROBE 1.0."""
    img = mkimg.build(os.path.join(OUT, 'floating.img'), [os.path.join(GOS, 'src', 'GRIDOS.SYS'), PROBE])
    k = ktest.KPC(img, float_bus=True); k.start()
    k.run_file('HDPROBE.COM', 120)
    rep = fatcheck.read_files(bytes(k.pc.drives[0].img)).get('A:\\HDPROBE.TXT', b'').decode('latin-1')
    for l in rep.splitlines(): print('   ' + l)
    check('a floating bus: "no drive answers", nothing past the registers, the next steps',
          'no drive answers' in rep and 'nothing drives the bus' in rep and '[4]' not in rep and
          'Does the drive spin up' in rep and 'identifies itself' not in rep, rep[-1500:])

def t_conner():
    ata = pcemu.Ata(data={0: mbr()})
    rep, f, sec, ok, k = probe('conner', ata)
    check('Conner CP3044: back in the Executive', ok, k.band())
    check('registers answer, the disk turns at about 3,480 rpm',
          "registers answer" in rep and 'rpm: the disk is turning' in rep and
          re.search(r'thousand reads: busy 0%, ready 100%, seek complete 100%, error 0%', rep) and
          any(3300 <= int(w) <= 3700 for w in rep.replace(',', ' ').split() if w.isdigit() and len(w) == 4), rep[:2000])
    check('ready at once (status 50), self-test code 01 passed; no 3F6h anywhere in the probe',
          re.search(r'Ready\? \(up to 31 s\): 0\.\d ms, status 50 \(DRDY DSC\)', rep) and
          rep.count('code 01: passed') == 1 and
          b'\xba\xf6\x03' not in open(PROBE, 'rb').read(), rep[:2500])
    check('its interrupt (IRQ 14) arrives; the masks and INT 76h are put back',
          'Interrupt (IRQ 14) after another 90h: it arrives' in rep and k.pc.pic2_mask == 0xFF and
          k.pc.u16(0, 0x76 * 4 + 2) == pcemu.STUB, (k.pc.pic2_mask, hex(k.pc.u16(0, 0x76 * 4 + 2))))
    check('IDENTIFY: model, firmware, serial, 977 x 5 x 17 = 42 MB',
          '"Conner Peripherals 40MB - CP3044"' in rep and '"1.03"' in rep and '"CP3044-123456"' in rep and
          '977 cylinders, 5 heads, 17 sectors a track = 42 MB' in rep)
    check('the BIOS knows it (type 11), yet CMOS 12h is 00: it gave up at power-on',
          'The BIOS knows CP3044: it would make it type 11' in rep and 'Yet CMOS 12h is 00' in rep)
    check('geometry set, recalibrate ok, three reads ok, the partition table',
          'All three test reads worked' in rep and '1: type 04  boot 80  41514 KB' in rep, rep[-1500:])
    check('HDIDENT.BIN is the IDENTIFY block, HDSECT0.BIN the first sector',
          f.get('A:\\HDIDENT.BIN') == ata.ident_block() and f.get('A:\\HDSECT0.BIN') == mbr())
    sent = [c for c, *_ in ata.cmds]
    check('only 90h, ECh, 91h, 10h, seeks and reads were sent: nothing written',
          set(sent) <= {0x90, 0xEC, 0x91, 0x10, 0x70, 0x20} and sent.count(0x20) == 3 and sent.count(0x70) == 3,
          [hex(c) for c in sent])
    check('reads at the start, middle and end of the disk',
          [(c, h, n) for cmd, c, h, n in ata.cmds if cmd == 0x20] == [(0, 0, 1), (488, 2, 9), (976, 4, 17)],
          ata.cmds)

def t_cp30104():
    """Joshua's spare (2026-10-07): a CP30104H, 120 MB.  The BIOS's list has
    CP3104 (100 MB), not CP30104, so it stays off for the BIOS; HDPROBE
    should say so and still read it.  Its first sector, as HDPROBE read it
    once the drive came free: one 121 MB FAT16 partition (type 06)."""
    sect0 = open(os.path.join(os.path.dirname(GOS), 'rom', 'hd_cp30104h', 'HDSECT0.BIN'), 'rb').read()
    rep, f, sec, ok, k = probe('cp30104', pcemu.Ata(model='Conner Peripherals 120MB - CP30104H',
                                                    cyls=762, heads=8, spt=39, rpm=3600, data={0: sect0}))
    check('a CP30104H: identified, 762 x 8 x 39 = 121 MB, not on the BIOS list, reads fine',
          ok and '"Conner Peripherals 120MB - CP30104H"' in rep and '= 121 MB' in rep and
          "The BIOS doesn't know this model" in rep and 'All three test reads worked' in rep, rep[-1800:])
    check('its partition, 237,393 sectors, in MB: "1: type 06  boot 80  121 MB"',
          '1: type 06  boot 80  121 MB' in rep, rep[-1500:])

def t_mech():
    """Joshua's CP30104H on the 1520 (2026-10-07): it answers and identifies
    (762 x 8 x 39), its interrupt arrives, but recalibrate aborts after
    seconds, seeks drop BSY and never complete, reads end IDNF."""
    rep, f, sec, ok, k = probe('mech', pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=762, heads=8,
                                                 spt=39, rpm=0, mech_fail=True, fail_ms=800))
    check('the interface works; recalibrate ABRT after 0.8 s, 3 seeks no DSC, 3 reads IDNF',
          ok and "hard-disk interface works" in rep and rep.count('error 04 (ABRT)') == 1 and
          re.search(r'Recalibrate, heads to track 0 \(10h\): [78]\d\d\.\d ms', rep) and
          rep.count('no seek complete (DSC) in 10 s') == 3 and rep.count('error 10 (IDNF)') == 3, rep[-2500:])
    check('... the verdict: the heads or the mechanics, not a lost low-level format',
          "can't find its way on the disk" in rep and 'low-level format is gone' not in rep, rep[-1500:])

def t_spinup():
    """Still spinning up when HDPROBE starts: busy for 10 s from the first look
    (the kernel's, booting: it gives up on the drive after 5 s)."""
    rep, f, sec, ok, k = probe('spinup', pcemu.Ata(unready=10, data={0: mbr()}))
    check('busy: the echo fails ("[4] waits for it"), busy throughout [3], ready in [4] after a few s',
          ok and '[4] waits' in rep and 'busy or not ready most of the time' in rep and
          any(l.strip().startswith('Ready? (up to 31 s): ') and 'status 50' in l and
              1000 < float(l.split(': ')[1].split(' ms')[0]) < 4000 for l in rep.splitlines()), rep[:2500])
    check('... then everything works', 'All three test reads worked' in rep and 'not ready after' not in rep, rep[-800:])

def t_exercise():
    """HDPROBE /X on a drive whose arm frees up on the second recalibrate."""
    ata = pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=762, heads=8, spt=39, rpm=0,
                    mech_fail=True, fail_ms=300, frees=2, data={0: mbr()})
    rep, sec, ok, k = probe_x('exercise', ata)
    lines = [l for l in rep.splitlines() if l[:2].strip().isdigit() and l[2:3] == ':']
    check('/X: back at the prompt; its own report (HDPROBEX.TXT); IDENTIFY, then the exercise instead of [6] and [7]',
          ok and k.plain is None and '[6] EXERCISE' in rep and '[5] IDENTIFY' in rep and '[7]' not in rep and len(lines) == 20,
          rep[-2500:])
    check('round 1: recal ABRT after ~300 ms, both seeks no DSC, the read IDNF',
          lines and re.search(r'recal [23]\d\dms ABRT', lines[0]) and 'ABRT' in lines[0] and lines[0].count('noDSC') == 2 and
          'IDNF' in lines[0], lines[:2])
    check('round 2 frees it: recal ABRT, then seeks and the read ok; rounds 3-20 all ok',
          len(lines) == 20 and 'ABRT' in lines[1] and lines[1].count(' ok') == 3 and
          all(l.count(' ok') == 4 for l in lines[2:]), lines[1:4])
    check('the summary: 18 recalibrates, 38 of 40 seeks, 19 reads; "run HDPROBE again"',
          '20 rounds: recalibrate worked 18 times, seeks 38 of 40, the read 19 times.' in rep and
          'It reads now' in rep, rep[-600:])
    sent = [c for c, *_ in ata.cmds]
    check('only 90h, ECh, 91h, 10h, 70h and 20h sent: nothing written',
          set(sent) <= {0x90, 0xEC, 0x91, 0x10, 0x70, 0x20} and sent.count(0x10) == 20 and sent.count(0x20) == 20,
          [hex(c) for c in sent][:30])

def t_exstop():
    """A key stops the exercise after the round under way."""
    rep, sec, ok, k = probe_x('exstop', pcemu.Ata(), stop_at=' 3:')
    lines = [l for l in rep.splitlines() if l[:2].strip().isdigit() and l[2:3] == ':']
    check('a key stops it: 3 or 4 rounds, all ok, and the summary says so',
          ok and len(lines) in (3, 4) and all(l.count(' ok') == 4 for l in lines) and
          ('%d rounds: recalibrate worked %d times' % (len(lines), len(lines))) in rep, rep[-1500:])

def t_cf():
    rep, f, sec, ok, k = probe('cf', pcemu.Ata(model='SanDisk SDCFB-64', cyls=490, heads=8, spt=32, rpm=0))
    check('a CompactFlash card: identified, but not a model the BIOS knows',
          ok and '"SanDisk SDCFB-64"' in rep and "The BIOS doesn't know this model" in rep and
          'not as a Conner the BIOS knows' in rep, rep[-1500:])

def t_unformatted():
    rep, f, sec, ok, k = probe('unformatted', pcemu.Ata(formatted={0}))
    check('sector IDs gone past cylinder 0: IDNF on the two other reads',
          ok and rep.count('error 10 (IDNF)') == 2 and 'Sector not found (IDNF)' in rep and
          'Some reads worked' in rep, rep[-1500:])

def t_stuck():
    rep, f, sec, ok, k = probe('stuck', pcemu.Ata(stuck=True))
    check('stuck busy: "a busy drive ignores writes", not ready after 31 s, IDENTIFY skipped',
          ok and 'busy (BSY)' in rep and 'not ready after 31 s' in rep and 'skipped: the drive never came ready' in rep
          and 'stays busy' in rep, rep[-1500:])

def t_tk0():
    rep, f, sec, ok, k = probe('tk0', pcemu.Ata(tk0=True))
    check('heads stuck: recalibrate says track 0 not found, and the verdict names it',
          ok and 'error 02 (TK0)' in rep and 'track 0 not found' in rep, rep[-1500:])

def t_diag():
    rep, f, sec, ok, k = probe('diag', pcemu.Ata(diag=0x03))
    check('self-test fails: code 03 sector buffer error, in the verdict too',
          ok and 'code 03: sector buffer error' in rep and 'self-test reports a fault' in rep, rep[-1500:])

def t_noirq():
    rep, f, sec, ok, k = probe('noirq', pcemu.Ata(irq=False))
    check('a dead interrupt line: "none in 2 s", and the verdict says this alone leaves CMOS 12h at 00',
          ok and 'none in 2 s' in rep and 'never arrives' in rep and 'Yet CMOS 12h is 00' not in rep and
          'All three test reads worked' in rep, rep[-1500:])

def t_still():
    rep, f, sec, ok, k = probe('still', pcemu.Ata(rpm=0))
    check('no index pulses: "may not be turning"', ok and 'Index pulses seen: 0' in rep and 'may not be turning' in rep)

TESTS = [t_absent, t_floating, t_conner, t_noirq, t_cp30104, t_mech, t_spinup, t_cf, t_unformatted, t_stuck, t_tk0,
         t_diag, t_still, t_exercise, t_exstop]
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
