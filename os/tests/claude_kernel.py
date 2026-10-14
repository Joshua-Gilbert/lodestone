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
    1520's expanded memory (resident Claude needs it)."""
    def __init__(s, script=None, patched=True, files=None, mode='ask', answer='y',
                 claude_com=G.CLAUDE_COM, baud=115200, term=None, ems_pages=0):
        s.tmp = tempfile.mkdtemp(prefix='gridk-')
        disk = [LODE_SYS, LCMD_COM, 'CLAUDE.COM=' + claude_com, 'TESTKEY.COM=' + G.TESTKEY_COM]
        for k, v in (files or {}).items():
            name = k.split('\\', 1)[1]
            p = os.path.join(s.tmp, name.replace('\\', '_'))
            open(p, 'wb').write(v)
            disk.append(name + '=' + p)
        img = mkimg.build(os.path.join(s.tmp, 'a.img'), disk)
        chip = G.Chip(S.bus())
        s.m = m = KMachine(img, chip, ems_pages=ems_pages)
        chip.clock = m.clock
        s.pending = []
        s.nano = AR488Model(m.clock, addr=7, patched=patched, to_pi=s._to_pi, baud=baud)
        chip.devices[7] = s.nano
        m.on_due = s.pump_pi
        s.transport = ModelTransport(s.nano, patched, baud=baud)
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
