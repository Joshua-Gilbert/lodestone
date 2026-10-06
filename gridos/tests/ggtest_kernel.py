"""GGTEST.COM (the GPIBTEST read-only set through the GPIB driver API) run on
the Grid-OS kernel's built-in GPIB against the bus model.  Prints the log.

    python3 tests/ggtest_kernel.py [out.txt]
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, fatcheck, sim7210

GGTEST = next((p for p in (os.environ.get('GGTEST', ''), os.path.join(GOS, '..', 'claude-link', 'tests', 'bin', 'GGTEST.COM'),
                            os.path.join(GOS, '..', 'tools', 'GGTEST.COM'),
                            '/home/claude/TM5000/driver/gridgpib/GGTEST.COM') if p and os.path.exists(p)),
              '/home/claude/TM5000/driver/gridgpib/GGTEST.COM')

def run(out_img=os.path.join(__import__('tempfile').gettempdir(), 'gridos-gg.img')):
    img = mkimg.build(out_img, [os.path.join(GOS, 'src', 'GRIDOS.SYS'), GGTEST])
    chip = sim7210.NEC7210(sim7210.bus())
    k = ktest.KPC(img, chip=chip); k.start()
    t0 = k.pc.us
    out = k.run_file('GGTEST.COM', 600)
    sim_s = (k.pc.us - t0) / 1e6
    files = fatcheck.read_files(bytes(k.pc.drives[0].img))
    log = files.get('A:\\GGTEST.TXT', b'').decode('cp437')
    return k, out, log, sim_s

if __name__ == '__main__':
    t = time.time()
    k, out, log, sim_s = run()
    print(log)
    print('band:', k.band(), 'crash:', k.crashed, '%.1f s simulated, %.1f s wall' % (sim_s, time.time() - t))
    if len(sys.argv) > 1: open(sys.argv[1], 'w').write(log)
