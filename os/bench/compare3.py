"""BENCH 1.3 on Lodestone, GRiD MS-DOS 3.30 and FreeDOS, all in pcemu with the
real-drive timing model and the 1520's 1408 KB of EMS (88 pages): Lodestone
with its own EMS manager, the other two with GRiD's EMM.SYS.  Also the
memory each leaves for programs, with and without EMS (MEMSZ).

    python3 bench/compare3.py <GRiD MS-DOS EPROM image> <EMM.SYS>
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import pcemu, mkimg, ktest, dosimg, fdimg, run_bench

ROM, EMM = sys.argv[1], sys.argv[2]
BENCH = os.path.join(HERE, 'BENCH.COM')
MEMSZ = os.path.join(GOS, 'tests', 'MEMSZ.COM')
TMP = run_bench.TMP
NAMES = run_bench.NAMES + ['EMS: map a page x 10000', 'EMS: move 1 MB to EMS (57h)', 'EMS: move 1 MB from EMS (57h)']
EMS = 88


def results(pc):
    m = {b: (us, n13, secs) for b, us, n13, secs in pc.marks}
    return [((m[2 * i + 1][0] - m[2 * i][0]) / 1e6) if 2 * i in m and 2 * i + 1 in m else None
            for i in range(1, len(NAMES) + 1)]


def lodestone(prog, ems, limit=900):
    img = mkimg.build(os.path.join(TMP, 'g3.img'), [os.path.join(GOS, 'src', 'LODE.SYS'),
                                                    os.path.join(GOS, 'src', 'LCMD.COM'), prog])
    k = ktest.KPC(img, disk_model='real', ems_pages=ems)
    k.start(20)
    k.pc.tty.clear()
    k.select(os.path.basename(prog).upper()); k.key(ktest.ENTER, settle=False)
    k.pc.run_until(lambda: k.pc.mode() != 0x40, 10)
    ktest.run_answering(k.pc, lambda: k.pc.mode() == 0x40, limit)
    return k.pc, ''.join(k.pc.tty)


def msdos(prog, ems, limit=900):
    cfg = b'DEVICE=EMM.SYS\r\n' if ems else None
    img = dosimg.build(os.path.join(TMP, 'm3.img'), ROM, [prog] + ([EMM] if ems else []), config=cfg)
    pc = pcemu.PC(img, disk_model='real', ems_pages=ems, irq_exact=True)  # (IRQs as ktest.KPC delivers Lodestone's)
    raw = open(img, 'rb').read()
    pc.mu.mem_write(0x7C00, raw[:512])
    data = 1 + 2 * 9 + 14
    pc.mu.mem_write(0x700, raw[data * 512:(data + 3) * 512])
    for r, v in (('cs', 0x70), ('ip', 0), ('ax', 0), ('dx', 0), ('ss', 0), ('sp', 0x7C00), ('ds', 0), ('es', 0)):
        pc.w(r, v)
    pc.w('flags', 0x202)
    tty = lambda: ''.join(pc.tty)
    pc.run_until(lambda: 'new date' in tty(), 60); pc.keys.append(0x1C0D)
    pc.run_until(lambda: 'new time' in tty(), 30); pc.keys.append(0x1C0D)
    pc.run_until(lambda: tty().rstrip().endswith('>'), 30)
    n0 = len(pc.tty)
    for ch in os.path.splitext(os.path.basename(prog))[0].upper(): pc.keys.append(ord(ch))
    pc.keys.append(0x1C0D)
    ktest.run_answering(pc, lambda: tty()[n0:].rstrip().endswith('>') and len(tty()) > n0 + 40, limit)
    return pc, tty()[n0:]


def freedos(prog, ems, limit=900):
    cfg = b'DEVICE=EMM.SYS\r\n' if ems else b''
    name = os.path.splitext(os.path.basename(prog))[0].upper()
    img = fdimg.build(os.path.join(TMP, 'f3.img'), [prog] + ([EMM] if ems else []), config=cfg,
                      autoexec=b'@ECHO OFF\r\n' + name.encode() + b'\r\n')
    pc = pcemu.PC(img, disk_model='real', ems_pages=ems, irq_exact=True)  # (as msdos())
    pc.boot(0)
    tty = lambda: ''.join(pc.tty)
    ktest.run_answering(pc, lambda: 'FreeCom' in tty() and tty().rstrip().endswith('>'), limit)
    return pc, tty()


if __name__ == '__main__':
    t = time.time()
    systems = (('Lodestone', lodestone), ('GRiD MS-DOS 3.30', msdos), ('FreeDOS 2046+FreeCOM', freedos))
    mem = {}
    for name, run in systems:
        for ems in (0, EMS):
            pc, out = run(MEMSZ, ems, 120)
            line = [l for l in out.splitlines() if 'for programs' in l]
            mem[name, ems] = line[-1].strip() if line else '?'
    res, outs = {}, {}
    for name, run in systems:
        pc, out = run(BENCH, EMS)
        res[name] = results(pc); outs[name] = out
        print('==== %s ====\n%s\n' % (name, out.strip()[-2500:]))
    hdr = '%-34s' % 'emulator timing (s)' + ''.join('%14s' % n.split()[0] for n, _ in systems)
    print(hdr)
    for i, n in enumerate(NAMES):
        if i == 10: print('%-34s' % 'Total (file system)' + ''.join('%14.2f' % sum(x for x in res[s][:10] if x) for s, _ in systems))
        print('%-34s' % n + ''.join('%14s' % ('%.3f' % res[s][i] if res[s][i] is not None else '-') for s, _ in systems))
    print('\nmemory for programs:')
    for name, _ in systems:
        print('  %-20s no EMS: %-22s with EMS: %s' % (name, mem[name, 0], mem[name, EMS]))
    print('(wall %.0f s)' % (time.time() - t))
