"""CLAUDE.COM end to end on the Lodestone 0.2 kernel: the floppy image boots in
pcemu (BIOS only), the Executive runs CLAUDE.COM, the kernel's built-in GPIB
talks to the uPD7210 + bus model with the AR488 bridge on it, and the real
gridlink answers with a scripted Claude.  The same scenarios as
gridlink/tests/test_emu.py, which ran on a Python stand-in for DOS.

    python3 tests/claude_kernel.py [outdir] [name ...]
"""
import os, struct, sys, tempfile, threading
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
GL_TESTS = next((p for p in (os.environ.get('GRIDLINK_TESTS', ''), os.path.join(GOS, '..', 'claude-link', 'tests'),
                              '/home/claude/gridlink/tests') if p and os.path.isdir(p)), '/home/claude/gridlink/tests')
sys.path.insert(0, GOS); sys.path.insert(0, HERE); sys.path.insert(0, GL_TESTS); sys.path.insert(0, os.path.dirname(GL_TESTS))
import pcemu, mkimg, fatcheck, ktest
import grid_emu as G
import sim7210 as S
from ar488_model import AR488Model
from gridsim import ModelTransport
from fake_anthropic import FakeAnthropic
from gridlink.link import Link
from gridlink.agent import Session
from gridlink.config import Config

LODE_SYS = os.path.join(GOS, 'src', 'LODE.SYS')
LCMD_COM = os.path.join(GOS, 'src', 'LCMD.COM')
FONT = pcemu.load_font(os.path.join(GOS, 'src', 'FONT.INC'))


class KMachine(pcemu.PC):
    """pcemu with what the CLAUDE harness looks at: the disk's files as a
    dict, EXECs and RTC settings in the log, exit of the program."""
    def __init__(s, img, chip, **kw):
        super().__init__(img, chip=chip, **kw)
        s.Y = ktest.Syms()
        s.watch = s._watch
        s.exit_code = None
        s.tsr = False

    def _watch(s, addr):
        if s.r('cs') == 0x60 and s.r('ip') == s.Y['f_4B']:
            bp = s.r('bp')
            ds, dx = s.u16(0x60, bp + 16), s.u16(0x60, bp + 10)
            p = s.asciiz(ds, dx).decode('cp437').upper()
            if ':' not in p: p = 'A:' + ('' if p.startswith('\\') else '\\') + p
            es, bx = s.u16(0x60, bp + 18), s.u16(0x60, bp + 8)
            toff, tseg = s.u16(es, bx + 2), s.u16(es, bx + 4)
            n = s.rd(tseg, toff, 1)[0]
            s.log.append('[EXEC %s%s]' % (p, s.rd(tseg, toff + 1, n).decode('cp437')))

    @property
    def fs(s): return fatcheck.read_files(bytes(s.drives[0].img))
    @property
    def rtc_set(s): return [l for l in s.log if l.startswith('[RTC set')]
    @property
    def clock_set(s): return True if s.rtc_set else None
    def png(s, path, scale=2): super().png(path, FONT, scale)


class KernelHarness(G.EmuHarness):
    """term: a command for Claude Code (a stand-in, in a pty): gridlink's
    router then, Term or chat as the GRiD's HELLO asks.  ems_pages: the
    1520's expanded memory (resident Claude needs it).  irq_exact: pcemu's
    (an IRQ held under CLI taken as soon as IF is set again)."""
    def __init__(s, script=None, patched=True, files=None, mode='ask', answer='y',
                 claude_com=G.CLAUDE_COM, baud=115200, term=None, ems_pages=0, bridge='ar488', frame_cap=None,
                 irq_exact=False):
        s.tmp = tempfile.mkdtemp(prefix='gridk-')
        disk = [LODE_SYS, LCMD_COM, 'CLAUDE.COM=' + claude_com, 'TESTKEY.COM=' + G.TESTKEY_COM]
        for k, v in (files or {}).items():
            name = k.split('\\', 1)[1]
            p = os.path.join(s.tmp, name.replace('\\', '_'))
            open(p, 'wb').write(v)
            disk.append(name + '=' + p)
        img = mkimg.build(os.path.join(s.tmp, 'a.img'), disk)
        chip = G.Chip(S.bus())
        s.m = m = KMachine(img, chip, ems_pages=ems_pages, irq_exact=irq_exact)
        chip.clock = m.clock
        s.pending = []
        if bridge in ('pico', 'pico-quiet'):           # (pico-quiet: fw 2026-10-24's, resident Claude's M4)
            s.nano = G.PicoModel(m.clock, addr=7, to_pi=s._to_pi, quiet=bridge == 'pico-quiet')
            s.transport = G.PicoModelTransport(s.nano)
        else:
            s.nano = AR488Model(m.clock, addr=7, patched=patched, to_pi=s._to_pi, baud=baud)
            s.transport = ModelTransport(s.nano, patched, baud=baud)
        chip.devices[7] = s.nano
        s.nano.wake = m.schedule                  # (the 7210's SRQ interrupt: a HLT ends when it rises)
        m.on_due = s.pump_pi
        cfg = Config()
        cfg.workdir = os.path.join(s.tmp, 'work'); cfg.memory_dir = os.path.join(s.tmp, 'mem')
        cfg.sessions_dir = os.path.join(s.tmp, 'sessions'); cfg.mode = mode; cfg.web = False
        s.cfg = cfg
        s.client = FakeAnthropic(script or [])
        s.log = []
        if term:
            cfg.term_dir = os.path.join(s.tmp, 'grid'); cfg.term_command = term
            cfg.term_socket = os.path.join(s.tmp, 'gridlink.sock')
            cfg.api_key = None; cfg.env_key = lambda: False; cfg.app = 'auto'
            s.router = G.Router(cfg, log=s.log.append)
            s.link = Link(s.transport, s.router.on_message, log=s.log.append, hold=0.0)
            s.router.attach(s.link)
            s.session = None
        else:
            s.router = None
            s.session = Session(cfg, s.client, log=s.log.append)
            s.link = Link(s.transport, s.session.on_message, log=s.log.append, hold=0.0)
            s.session.attach(s.link)
            threading.Thread(target=s.session.run, daemon=True).start()
        s.link.clock = lambda: s.m.us / 1e6        # (ring_check's times: the GRiD's, simulated)
        if hasattr(s.transport, 'proto'): s.transport.proto.clock = s.link.clock
        s.sym = G.symbols(os.path.splitext(claude_com)[0] + '.MAP')
        s.font = G.Font(open(claude_com, 'rb').read(), s.sym['font'] - 0x100)
        s.answer = answer
        s.shots = []
        s.k = None

    def boot(s):
        """Boot the floppy, wait for the Executive, run CLAUDE.COM from it."""
        k = ktest.KPC.__new__(ktest.KPC)          # the Executive helpers on our machine
        k.pc = s.m; k.Y = s.m.Y; k.dos = []; k.pending = {}; k.trace = False; k.hooks = []
        s.k = k
        s.m.boot(0)
        k.settle(8)
        assert s.m.mode() == 0x40 and 'CLAUDE.COM' in k.exec_list(), (s.m.crash, k.where())
        s.gridgpib_out = 'built in (gp_ok=%d)' % s.m.rd(0x60, s.m.Y['gp_ok'], 1)[0]
        s.m.tty.clear()
        k.select('CLAUDE.COM')
        s.m.keys.append(ktest.ENTER)
        s.m.halted = False
        cur = lambda: s.m.u16(0x60, s.m.Y['cur_psp'])
        root = s.m.u16(0x60, s.m.Y['root_psp'])
        s.run_until(lambda: cur() != root or s.m.crash, 5)
        s.claude_psp = cur()
        return s.gridgpib_out

    def back_in_executive(s, sim_s=5):
        return s.run_until(lambda: s.m.mode() == 0x40 and s.m.u16(0x60, s.m.Y['cur_psp']) == s.m.u16(0x60, s.m.Y['root_psp']), sim_s)


def _gp(op, addr, data=b'', tmo=100, mx=200):
    return struct.pack('<BBBHH', op, addr, 1, tmo, mx) + data

def _z(*paths): return b''.join(p.encode() + b'\0' for p in paths)

# OPS.INC's requests, each with the status and reply the kernel gives: the
# same table for CLAUDE.COM and for resident Claude's console (RCON), which
# build the same source.  (name, op, arguments, status, the reply: its bytes,
# or only its length)
OPS_PROBE = [
    ('mkdir', 7, _z('A:\\PRB'), 0, 0),
    ('mkdir, there', 7, _z('A:\\PRB'), 5, 0),
    ('mkdir, no path', 7, _z('A:\\NOPE\\SUB'), 3, 0),
    ('write', 4, b'\0' + struct.pack('<I', 0) + _z('A:\\PRB\\F.TXT') + b'probe\r\n', 0, b'\x07\x00'),
    ('rmdir, not empty', 8, _z('A:\\PRB'), 5, 0),
    ('rename to another dir', 6, _z('A:\\PRB\\F.TXT', 'A:\\G.TXT'), 0, 0),
    ('rename, none', 6, _z('A:\\PRB\\F.TXT', 'A:\\H.TXT'), 2, 0),
    ('rename, no path', 6, _z('A:\\G.TXT', 'A:\\NOPE\\G.TXT'), 3, 0),
    ('rename over a file', 6, _z('A:\\G.TXT', 'A:\\LCMD.COM'), 5, 0),
    ('stat', 9, _z('A:\\G.TXT'), 0, 9),
    ('stat, none', 9, _z('A:\\NONE.TXT'), 18, 0),
    ('stat, no path', 9, _z('A:\\NOPE\\X'), 3, 0),
    ('stat, no drive', 9, _z('Q:\\X'), 3, 0),
    ('dir', 2, _z('A:\\PRB\\*.*'), 0, 44),
    ('dir, none', 2, _z('A:\\NONE*.*'), 0, 0),
    ('dir, no path', 2, _z('A:\\NOPE\\*.*'), 3, 0),
    ('dir, no drive', 2, _z('Q:\\*.*'), 3, 0),
    ('read', 3, struct.pack('<IH', 0, 100) + _z('A:\\G.TXT'), 0, b'probe\r\n'),
    ('read, none', 3, struct.pack('<IH', 0, 100) + _z('A:\\NONE.TXT'), 2, 0),
    ('delete', 5, _z('A:\\G.TXT'), 0, 0),
    ('delete, none', 5, _z('A:\\G.TXT'), 2, 0),
    ('delete, no path', 5, _z('A:\\NOPE\\X'), 3, 0),
    ('rmdir', 8, _z('A:\\PRB'), 0, 0),
    ('rmdir, none', 8, _z('A:\\PRB'), 3, 0),
    ('free, no drive', 10, b'\x11', 15, 0),
    ('gpib clear', 0x20, _gp(5, 29), 0, b''),
    ('gpib remote', 0x20, _gp(8, 29), 0, b''),
    ('gpib local', 0x20, _gp(7, 29), 0, b''),
    ('gpib trigger', 0x20, _gp(6, 29), 0, b''),
    ('gpib write', 0x20, _gp(1, 29, b'ID?'), 0, b''),
    ('gpib read', 0x20, _gp(2, 29), 0, b'ID TEK/DC5009,V79.1,F2.1\r\n'),
    ('gpib query', 0x20, _gp(3, 29, b'ID?'), 0, b'ID TEK/DC5009,V79.1,F2.1\r\n'),
    ('gpib query, short', 0x20, _gp(3, 29, b'ID?', mx=6), 0, b'ID TEK'),
    ('gpib spoll', 0x20, _gp(4, 29), 0, b'A'),
    ('gpib scan', 0x20, _gp(9, 0), 0, b'\x06\x0e\x1d'),
    ('gpib write, none', 0x20, _gp(1, 20, b'ID?'), 2, b''),
    ('gpib read, none', 0x20, _gp(2, 20), 5, b''),
    ('gpib query, none', 0x20, _gp(3, 20, b'ID?'), 2, b''),
    ('gpib spoll, none', 0x20, _gp(4, 20), 1, b''),
    ('gpib clear, none', 0x20, _gp(5, 20), 0, b''),
    ('gpib trigger, none', 0x20, _gp(6, 20), 0, b''),
    ('gpib local, none', 0x20, _gp(7, 20), 0, b''),
    ('gpib remote, none', 0x20, _gp(8, 20), 0, b''),
    ('gpib op 10', 0x20, _gp(10, 29), 4, b''),
]

OPS_WANT = [(n, st, r) for n, op, a, st, r in OPS_PROBE]

def ops_probe(grid, run):
    """OPS_PROBE through gridlink's Grid (run(cond): the machine until cond):
    [(name, status, reply)], the reply its bytes or its length as OPS_PROBE
    has it."""
    out = []
    for name, op, args, st0, r0 in OPS_PROBE:
        r = {}
        def call():
            try: r['v'] = grid.call(op, args, timeout=60)
            except Exception as e: r['v'] = (None, str(e))
        th = threading.Thread(target=call); th.start()
        run(lambda: not th.is_alive())
        th.join(5)
        st, data = r.get('v', (None, b''))
        out.append((name, st, data if st is None else bytes(data) if isinstance(r0, bytes) else len(data)))
    return out
