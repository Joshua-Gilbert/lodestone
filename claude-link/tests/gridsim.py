"""A Python model of the GRiD side (what CLAUDE.COM does), wired to the AR488
model and to the real gridlink Link + Session with a scripted Claude.
Used to test the Pi side end to end without the GRiD or the API.

The link logic here mirrors CLAUDE.ASM: strict alternation, serial polls,
stock-firmware waits, NAK / resend / duplicate handling, fragments.
"""
import collections, os, struct, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from gridlink import glp, keys as K
from gridlink import termscreen as TS
from gridlink import picture as PIC
from gridlink.link import Link, answer_bytes
from gridlink.agent import Session
from gridlink.config import Config
from gridlink.router import Router
from ar488_model import AR488Model
from fake_anthropic import FakeAnthropic


class Clock:
    def __init__(s): s.t = 0.0
    def __call__(s): return s.t
    def advance(s, us): s.t += us


class ModelTransport:
    """gridlink's view of the bridge, but writing into the AR488 model."""
    def __init__(s, nano, patched, baud=115200, latency_us=1500):
        s.nano, s.patched, s.baud, s.latency = nano, patched, baud, latency_us
        s.version = 'AR488 model' + (' +GRiD1' if patched else '')
        s.answers = 0; s.corrupt_every = 0
    big = 0                                   # > 0: frames up to this (the Pico's way), else the AR488's
    @property
    def frame_limit(s):
        if s.big: return s.big
        return glp.PATCHED_FRAME_MAX if s.patched else glp.STOCK_FRAME_MAX
    def answer(s, frame):
        s.answers += 1
        if s.corrupt_every and s.answers % s.corrupt_every == 0:
            f = bytearray(frame); f[len(f) // 2] ^= 0x10; frame = bytes(f)
        s.nano.pi_write(answer_bytes(frame, s.patched, s.baud), latency_us=s.latency)


def dos_date(y, mo, d): return ((y - 1980) << 9) | (mo << 5) | d
def dos_time(h, mi, sec=0): return (h << 11) | (mi << 5) | (sec // 2)


class GridSim:
    """The GRiD: CLAUDE.COM's link state machine plus its request handlers
    over an in-memory DOS file system."""
    def __init__(s, h, answer_policy='y'):
        s.h = h; s.nano = h.nano; s.clock = h.clock
        s.state = 'reset'; s.t_reset = -10e6; s.t_sent = 0
        s.g_seq = 0; s.p_ack = 0; s.have_pi = False
        s.txq = collections.deque(); s.pend = None
        s.nak = False; s.resend = False; s.lastframe = b''
        s.connected = False; s.busy = False; s.pi_active = False; s.t_last = 0
        s.screen = bytearray(); s.status = b''; s.title = b''
        s.asks = []; s.answer_policy = answer_policy
        s.req = bytearray(); s.rqtype = 0
        s.fs = {}; s.dirs = {'A:\\'}
        s.snapshot = None; s.time_set = None
        s.stats = collections.Counter()
        s.corrupt_rx_every = 0
        s.damage_hellos = 0             # (HELLOs sent damaged, first)
        # Term (CLAUDE /T)
        s.app = None; s.term = False; s.keybuf = bytearray(); s.t_active = -10e6
        s.cells, s.attrs = TS._blank_rows(); s.cursor = (0, 0, True)
        s.pix = bytearray(PIC.SIZE)                 # pictures (CLAUDE.COM 1.2: hello_flags GF_PIX)
        s.on_cells = None
        s.last_flags = 0                # (the last CELLS frame's flags)

    # ---- outgoing ----------------------------------------------------------
    def queue(s, t, body):
        s.txq.append([t, bytes(body), 0])

    def prompt(s, text):
        s.queue(glp.G_PROMPT, text.encode('cp437')); s.busy = True
        s.screen += b'\n> ' + text.encode('cp437') + b'\n\n'

    def interrupt(s):
        s.queue(glp.G_EVENT, bytes([glp.EV_INTERRUPT]))

    def hello_body(s):
        kv = 'os=MS-DOS 3.30\ncwd=A:\\\ndrives=A: B: C: \nmem=480\nems=none\n' \
             'gpib=GRIDGPIB 1.10 on INT 60h\naddr=7\ndate=2026-10-04 20:30\ngrid=gridsim\n'
        if s.app: kv += 'app=%s\n' % s.app
        if s.rx != glp.GRID_RX_DEFAULT: kv += 'rx=%d\n' % s.rx      # CLAUDE 1.3's 2 KB frames
        return bytes([1, s.hello_flags]) + struct.pack('<H', 1024) + bytes([80, 20]) + kv.encode()

    hello_flags = glp.GF_TERM | glp.GF_PIX
    rx = glp.GRID_RX_DEFAULT                  # payload it reads (CLAUDE 1.3: 2048)

    def click(s, x, y):
        """A left click at pixel (x, y): EVENT 06h as CLAUDE.COM 1.2 sends it."""
        s.queue(glp.G_EVENT, bytes([glp.EV_PIXCLICK]) + struct.pack('<HH', x, y))

    # ---- Term ------------------------------------------------------------
    def press(s, al, ah):
        s.keybuf += bytes([al, ah]); s.t_active = s.clock()

    def type(s, text):
        for ch in text:
            al, ah = K.char_key(ch); s.press(al, ah)

    def screen_text(s):
        return [bytes(r).decode('latin1') for r in s.cells]

    def _frame(s, kind, payload=b'', seq=None):
        if seq is None:
            s.g_seq = (s.g_seq + 1) & 0xFF; seq = s.g_seq
        return glp.encode(kind, seq, s.p_ack, payload)

    def _write(s, frame):
        for i, b in enumerate(frame):
            s.nano.rx_byte(b, i == len(frame) - 1)
        s.clock.advance(len(frame) * 90)          # paced by the Nano's serial port
        s.state = 'wait'; s.t_sent = s.clock()
        s.stats['tx'] += 1

    # ---- the main loop -------------------------------------------------
    def step(s):
        s.h.pump_pi()
        s.nano.service()
        if s.state == 'reset':
            if s.clock() - s.t_reset < 1e6: s.clock.advance(1000); return
            s.nano.sdc()
            s.g_seq = 0; s.p_ack = 0; s.have_pi = False; s.txq.clear(); s.pend = None
            s.nak = False; s.resend = False; s.req = bytearray(); s.rqtype = 0
            s.txq.append([glp.G_HELLO, s.hello_body(), 0])
            s.state = 'idle'
        elif s.state == 'idle':
            if s.nak:
                s.nak = False
                s._write(glp.encode(glp.G_NAK, s.g_seq, s.p_ack)); s.stats['nak'] += 1
            elif s.resend:
                s.resend = False; s._write(s.lastframe); s.stats['resend'] += 1
            elif s.term and s.keybuf and not s.txq:
                body = bytes(s.keybuf[:1024]); del s.keybuf[:len(body)]
                s.txq.append([glp.G_KEYS, body, 0]); s.stats['keys_frames'] += 1
            elif s.txq:
                t, body, pos = s.txq[0]
                chunk = body[pos:pos + 1024]
                kind = t | (glp.MORE if pos + len(chunk) < len(body) else 0)
                if t == glp.G_HELLO: s.g_seq = 0; seq = 0
                else: s.g_seq = (s.g_seq + 1) & 0xFF; seq = s.g_seq
                s.pend = len(chunk)
                s.lastframe = glp.encode(kind, seq, s.p_ack, chunk)
                if t == glp.G_HELLO and s.damage_hellos:   # (damaged on the bus; a resend goes whole)
                    s.damage_hellos -= 1
                    d = bytearray(s.lastframe); d[8] ^= 0x55; s._write(bytes(d))
                else: s._write(s.lastframe)
            elif s.connected and (s.busy or s.pi_active or s.clock() - s.t_last > 1e6
                                  or (s.term and s.clock() - s.t_active < 2e6)):
                s.pend = None
                s.lastframe = s._frame(glp.G_POLL); s._write(s.lastframe)
            else:
                s.clock.advance(5000)
                time.sleep(0.0005)
        elif s.state == 'wait':
            if s.clock() - s.t_sent > 2.2e6:
                s.fail(); return
            s.clock.advance(1000)
            s.h.pump_pi(); s.nano.service()
            st = s.nano.status
            s.stats['spoll'] += 1
            if not st & glp.ST_RQS:
                if s.busy or s.pi_active: time.sleep(0.0002)
                return
            if not st & glp.ST_READY:
                s.clock.advance((st & glp.ST_WAITMASK) * 1000)
                s.h.pump_pi()
                s.nano.service()
            s.nano.on_talk()
            data = s.nano.out[:s.rx + 9]
            s.clock.advance(len(data) * 25)
            s.stats['rx_bytes'] += len(data)
            if s.corrupt_rx_every:
                s.stats['rx_n'] += 1
                if s.stats['rx_n'] % s.corrupt_rx_every == 0 and data:
                    d = bytearray(data); d[len(d) // 2] ^= 0x04; data = bytes(d)
            f, _ = glp.decode(data, s.rx)
            if f and f.fl and not s.connected: f = None     # (CLAUDE before 1.15: CRC till its HELLO's answer)
            s.state = 'idle'
            if not f:
                s.nak = True; s.stats['bad_rx'] += 1; return
            s.t_last = s.clock()
            if f.type == glp.P_NAK:
                s.resend = True; return
            if s.pend is not None and s.txq:      # our frame got through
                s.txq[0][2] += s.pend
                if s.txq[0][2] >= len(s.txq[0][1]): s.txq.popleft()
            s.pend = None
            if s.have_pi and f.seq == s.p_ack:
                s.stats['dup'] += 1; return
            s.p_ack = f.seq; s.have_pi = True
            s.pi_frame(f)
        if not s.txq and s.req_ready:
            s.run_request()

    req_ready = False

    def fail(s):
        s.stats['fail'] += 1
        s.state = 'reset'; s.t_reset = s.clock(); s.connected = False; s.busy = False

    # ---- frames from the Pi --------------------------------------------
    def pi_frame(s, f):
        t = f.type; p = f.payload
        s.pi_active = t != glp.P_NOP
        if t == glp.P_HELLO:
            s.connected = True
            s.term = bool(p[1] & glp.HF_TERM) if len(p) >= 2 else False
            s.busy = not s.term                                     # chat: until the Pi's READY
        elif t == glp.P_CELLS:
            if p[0] & TS.F_CLEAR: s.stats['clears'] += 1
            s.last_flags = p[0]
            s.cursor = TS.apply(p, s.cells, s.attrs, s.pix if s.hello_flags & glp.GF_PIX else None)
            s.t_active = s.clock()
            s.stats['cells_frames'] += 1; s.stats['cells_bytes'] += len(p)
            if s.on_cells: s.on_cells()
        elif t == glp.P_TEXT: s.screen += p
        elif t == glp.P_STATUS: s.status = p
        elif t == glp.P_TITLE: s.title = p
        elif t == glp.P_READY: s.busy = False
        elif t == glp.P_CLEAR: s.screen = bytearray()
        elif t in (glp.P_REQUEST, glp.P_ASK):
            if t != s.rqtype: s.req = bytearray(); s.rqtype = t
            s.req += p
            if not f.more:
                s.rqtype = 0
                if t == glp.P_ASK: s.ask(bytes(s.req))
                else: s.req_ready = True

    def ask(s, body):
        aid, kind = body[0], body[1]
        q, d, a = (body[2:].split(b'\0') + [b'', b'', b''])[:3]
        s.asks.append((q.decode('cp437'), d.decode('cp437'), a.decode('cp437')))
        ans = s.answer_policy(q.decode('cp437')) if callable(s.answer_policy) else s.answer_policy
        s.queue(glp.G_EVENT, bytes([glp.EV_ANSWER, aid, ord(ans)]))

    # ---- requests ------------------------------------------------------
    def reply(s, rid, status, data=b''):
        s.queue(glp.G_REPLY, bytes([rid, status]) + bytes(data))

    def run_request(s):
        s.req_ready = False
        r = bytes(s.req); rid, op, a = r[0], r[1], r[2:]
        s.stats['op_%02X' % op] += 1
        z = lambda b: b.split(b'\0')[0].decode('cp437').upper()
        if op == glp.OP_INFO:
            return s.reply(rid, 0, s.hello_body()[6:])
        if op == glp.OP_DIR:
            pat = z(a); base = pat.rpartition('\\')[0] + '\\'
            out = b''
            for name in sorted(s.fs):
                if name.rpartition('\\')[0] + '\\' == base:
                    nm = name.rpartition('\\')[2].encode()
                    out += struct.pack('<BHHI', 0x20, dos_time(17, 31), dos_date(2026, 10, 4),
                                       len(s.fs[name])) + nm.ljust(13, b'\0')
            for d in sorted(s.dirs):
                if d.rstrip('\\').rpartition('\\')[0] + '\\' == base and d != base:
                    nm = d.rstrip('\\').rpartition('\\')[2].encode()
                    out += struct.pack('<BHHI', 0x10, 0, dos_date(2026, 10, 4), 0) + nm.ljust(13, b'\0')
            return s.reply(rid, 0, out)
        if op == glp.OP_READ:
            off, n = struct.unpack_from('<IH', a); path = z(a[6:])
            if path not in s.fs: return s.reply(rid, 2)
            return s.reply(rid, 0, s.fs[path][off:off + min(n, 16382)])
        if op == glp.OP_WRITE:
            mode, off = struct.unpack_from('<BI', a); rest = a[5:]
            path = z(rest); data = rest.split(b'\0', 1)[1]
            if mode == 0: s.fs[path] = data
            elif mode == 2: s.fs[path] = s.fs.get(path, b'') + data
            else:
                old = bytearray(s.fs.get(path, b'')); old[off:off + len(data)] = data; s.fs[path] = bytes(old)
            return s.reply(rid, 0, struct.pack('<H', len(data)))
        if op == glp.OP_DELETE:
            p = z(a)
            if p not in s.fs: return s.reply(rid, 2)
            del s.fs[p]; return s.reply(rid, 0)
        if op == glp.OP_RENAME:
            old, new = [x.decode('cp437').upper() for x in a.split(b'\0')[:2]]
            if old not in s.fs: return s.reply(rid, 2)
            if new in s.fs: return s.reply(rid, 5)
            s.fs[new] = s.fs.pop(old); return s.reply(rid, 0)
        if op == glp.OP_MKDIR:
            s.dirs.add(z(a).rstrip('\\') + '\\'); return s.reply(rid, 0)
        if op == glp.OP_RMDIR:
            s.dirs.discard(z(a).rstrip('\\') + '\\'); return s.reply(rid, 0)
        if op == glp.OP_STAT:
            p = z(a)
            if p in s.fs:
                return s.reply(rid, 0, struct.pack('<BHHI', 0x20, dos_time(17, 31), dos_date(2026, 10, 4), len(s.fs[p])))
            if p.rstrip('\\') + '\\' in s.dirs:
                return s.reply(rid, 0, struct.pack('<BHHI', 0x10, 0, dos_date(2026, 10, 4), 0))
            return s.reply(rid, 18)
        if op == glp.OP_FREE:
            return s.reply(rid, 0, struct.pack('<II', 512000, 737280))
        if op == glp.OP_SETTIME:
            s.time_set = struct.unpack('<HBBBBB', a[:7]); return s.reply(rid, 0)
        if op == glp.OP_RUN:
            flags, tmo, kl = struct.unpack_from('<BHH', a)
            keys = a[5:5 + kl]; cmd = z(a[5 + kl:])
            s.last_run = (cmd, keys)
            out = {'DIR': '\n'.join(n for n in sorted(s.fs)) + '\n', 'VER': 'MS-DOS Version 3.30\n'}.get(
                cmd.split()[0], 'ran %s\n' % cmd)
            rflags = 0
            if flags & 1:
                s.fs['A:\\CLAUDE.OUT'] = out.replace('\n', '\r\n').encode(); rflags |= 1
            if flags & 2 or b'\xff\xfe' in keys:
                text = ('C:\\> %s' % cmd).ljust(80) + 'TM5000G v3.7'.ljust(80)
                cells = b''.join(bytes([ord(c), 7]) for c in text.ljust(80 * 25))
                s.snapshot = struct.pack('<BBBHHH', 3, 1, 0, 80, 25, 160) + cells; rflags |= 2
            return s.reply(rid, 0, struct.pack('<HB', 0, rflags) + b'A:\\CLAUDE.OUT\0')
        if op == glp.OP_SCREEN:
            if not s.snapshot: return s.reply(rid, 0xF5)
            return s.reply(rid, 0, s.snapshot)
        if op == glp.OP_GPIB:
            gop, addr, flags, tmo, mx = struct.unpack_from('<BBBHH', a); data = a[7:]
            devs = {29: 'ID TEK/DC5009,V79.1,F1.2', 6: 'ID TEK/FG5010,V79.1,F04', 16: 'ID TEK/DM5120,V81.1,FV1.0'}
            s.gpib_log = getattr(s, 'gpib_log', []) + [(gop, addr, data)]
            old_nano = getattr(s, 'plot_nopoll', False)               # a Nano before v4: no serial poll
            if gop == glp.GP_SCAN: return s.reply(rid, 0, bytes(sorted(set(devs) | ({1} if not old_nano else set()))))
            if addr == 1:                   # the 4662's HP-GL Nano (v4): a listener, and a serial poll
                held = getattr(s, 'plot_held', 0)                     # bytes in its buffer
                if gop == glp.GP_SPOLL:
                    if old_nano: return s.reply(rid, 1)
                    held = max(0, held - getattr(s, 'plot_drain', 60))  # the pen works between polls
                    s.plot_held = held
                    room = min(63, max(0, 240 - held) // 4)
                    return s.reply(rid, 0, bytes([(0x80 if held == 0 else 0) | room]))
                if gop != glp.GP_WRITE: return s.reply(rid, 1)
                fail = getattr(s, 'plot_fail_after', None)            # a test: the Nano stops taking bytes
                if fail is not None and len(getattr(s, 'plot_parts', [])) >= fail: return s.reply(rid, 1)
                if held + len(data) > 240: s.plot_overrun = True        # more than its poll said: it'd hold the bus
                s.plot_held = held + len(data)
                s.plot_parts = getattr(s, 'plot_parts', []) + [bytes(data)]
                return s.reply(rid, 0)
            if addr not in devs: return s.reply(rid, 2)
            if gop == glp.GP_QUERY: return s.reply(rid, 0, (devs[addr] + '\r\n').encode())
            if gop == glp.GP_SPOLL: return s.reply(rid, 0, b'\x00')
            return s.reply(rid, 0)
        return s.reply(rid, 0xFF)


class TermHarness:
    """GridSim in Term mode <-> AR488 model <-> gridlink (Router + TermSession)
    <-> a program in a real pty (tests/fake_claude.py).  Real time runs here:
    the Pi's holds and the program's output are real; the clock also counts
    the time the Pi takes."""
    def __init__(s, command=None, patched=True, app='term', files=None, cfg_app='auto', key=False,
                 web_command=None):
        s.clock = Clock()
        s.pending = []
        s.nano = AR488Model(s.clock, addr=7, patched=patched, to_pi=s._to_pi)
        s.transport = ModelTransport(s.nano, patched)
        s.tmp = tempfile.mkdtemp(prefix='gridlink-term-')
        cfg = Config()
        cfg.workdir = os.path.join(s.tmp, 'work'); cfg.memory_dir = os.path.join(s.tmp, 'mem')
        cfg.sessions_dir = os.path.join(s.tmp, 'sessions'); cfg.web = False
        cfg.term_dir = os.path.join(s.tmp, 'grid'); cfg.app = cfg_app
        cfg.term_socket = os.path.join(s.tmp, 'gridlink.sock')
        cfg.term_command = command or '%s %s' % (sys.executable, os.path.join(HERE, 'fake_claude.py'))
        cfg.web_command = web_command or '%s -m gridfox' % sys.executable
        cfg.web_dir = os.path.join(s.tmp, 'web')
        cfg.api_key = 'sk-test' if key else None
        cfg.env_key = lambda: False
        s.cfg = cfg
        s.log = []
        s.router = Router(cfg, log=s.log.append)
        s.link = Link(s.transport, s.router.on_message, log=s.log.append)
        s.router.attach(s.link)
        s.grid = GridSim(s, 'y'); s.grid.app = app
        if files:
            for k, v in files.items(): s.grid.fs[k.upper()] = v

    _to_pi = lambda s, data, t: s.pending.append((t, data))

    def pump_pi(s):
        now = s.clock()
        ready = [p for p in s.pending if p[0] <= now]
        if not ready: return
        s.pending = [p for p in s.pending if p[0] > now]
        for t, data in sorted(ready, key=lambda p: p[0]):
            t0 = time.time()
            s.link.feed(data)
            s.clock.advance((time.time() - t0) * 1e6)

    def run_until(s, cond, wall=10.0):
        end = time.time() + wall
        while time.time() < end:
            s.grid.step()
            if cond(): return True
        return False

    def run_for(s, secs):
        s.run_until(lambda: False, wall=secs)

    @property
    def term(s): return s.router.web if s.router.app == 'web' else s.router.term

    def pi_screen(s):
        return s.term.text() if s.term else []

    def synced(s):
        """The GRiD shows what pyte has (and nothing is still on its way)."""
        t = s.term
        if t is None: return False
        pic = t.pic
        if pic is not None:                             # a picture over the text
            return not t.ready() and bytes(s.grid.pix) == pic['bits']
        if t.dirty: return False
        with t.lock:
            tc, ta = t.screen.cells()
        return [bytes(r) for r in tc] == [bytes(r) for r in s.grid.cells] and \
               [bytes(r) for r in ta] == [bytes(r) for r in s.grid.attrs]

    def settle(s, wall=10.0, quiet=0.3):
        """Run until the GRiD matches the Pi's screen and stays so for `quiet` s."""
        end = time.time() + wall; since = None
        while time.time() < end:
            s.grid.step()
            if s.synced():
                if since is None: since = time.time()
                elif time.time() - since >= quiet: return True
            else:
                since = None
        return False

    def wait_text(s, text, wall=10.0):
        return s.run_until(lambda: any(text in l for l in s.grid.screen_text()), wall=wall)

    def close(s):
        if s.router.term: s.router.term.stop()
        if s.router.web: s.router.web.stop()


class Harness:
    def __init__(s, script=None, patched=True, answer='y', files=None, hold=0.0, mode='ask'):
        s.clock = Clock()
        s.pending = []
        s.nano = AR488Model(s.clock, addr=7, patched=patched, to_pi=s._to_pi)
        s.transport = ModelTransport(s.nano, patched)
        s.tmp = tempfile.mkdtemp(prefix='gridlink-test-')
        cfg = Config()
        cfg.workdir = os.path.join(s.tmp, 'work'); cfg.memory_dir = os.path.join(s.tmp, 'mem')
        cfg.sessions_dir = os.path.join(s.tmp, 'sessions'); cfg.mode = mode; cfg.web = False
        s.cfg = cfg
        s.client = FakeAnthropic(script)
        s.log = []
        s.session = Session(cfg, s.client, log=s.log.append)
        s.link = Link(s.transport, s.session.on_message, log=s.log.append, hold=hold)
        s.session.attach(s.link)
        threading.Thread(target=s.session.run, daemon=True).start()
        s.grid = GridSim(s, answer)
        if files:
            for k, v in files.items(): s.grid.fs[k.upper()] = v

    def _to_pi(s, data, t):
        s.pending.append((t, data))

    def pump_pi(s):
        now = s.clock()
        ready = [p for p in s.pending if p[0] <= now]
        if not ready: return
        s.pending = [p for p in s.pending if p[0] > now]
        for t, data in sorted(ready, key=lambda p: p[0]):
            s.link.feed(data)

    def run_until(s, cond, steps=200000, wall=20.0):
        end = time.time() + wall
        for _ in range(steps):
            s.grid.step()
            if cond(): return True
            if time.time() > end: break
        return False

    def connect(s):
        # connected, and the Pi's READY after its set-up has arrived
        return s.run_until(lambda: s.grid.connected and not s.grid.busy and not s.link.busy()
                           and s.grid.state == 'idle')

    def turn(s, text):
        s.grid.prompt(text)
        s.run_until(lambda: not s.grid.busy and not s.link.busy() and not s.grid.txq
                    and s.grid.state == 'idle', wall=30.0)

    def text(s):
        out = []
        for b in bytes(s.grid.screen):
            if b == 0x0A: out.append('\n')
            elif 32 <= b < 127: out.append(chr(b))
            elif b >= 0x80: out.append('*')
        return ''.join(out)
