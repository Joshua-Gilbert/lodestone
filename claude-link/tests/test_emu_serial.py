"""The real CLAUDE.COM over the real SERLINK.COM (tools/SERLINK.ASM), with no GPIB cartridge: a null-modem cable
to the GRiD's COM2, and the internal 2400-baud modem on COM1 calling the Pi's USB modem through the HT802
(serial_model.py), with the real gridlink SerialLink / ModemLink (gridlink/serline.py) on the Pi.

    python3 tests/test_emu_serial.py
"""
import os, subprocess, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fake_anthropic import reply
from grid_emu import EmuHarness, Machine, SERLINK_COM, GRIDGPIB_COM
from serial_model import Uart, PiPort, Cable, ModemCall
from gridlink.serline import ModemLink, frame_limit_for
from gridlink import glp

BIG = ''.join('line %05d: the quick brown fox jumps over the lazy dog\n' % i for i in range(400))


def check(h, fails=0):
    assert not h.m.crash, h.m.crash
    errs = [l for l in h.log if 'Traceback' in str(l) or 'error' in str(l).lower()]
    assert not errs, errs
    assert h.var('n_fail', 2) == fails, ('link failures', h.var('n_fail', 2))
    assert h.uart.overruns == 0, ('overruns', h.uart.overruns)


def start(script, bridge, serlink, **kw):
    h = EmuHarness(script, bridge=bridge, serlink=serlink, **kw)
    h.boot()
    assert h.connect(30), ('no connection', h.m.crash, h.serlink_out, h.screen())
    return h


def test_cable_chat():
    h = start([reply(('text', 'Hello over the cable.'))], 'serial', '/P:2')
    assert 'COM2, 19200 baud' in h.serlink_out, h.serlink_out
    assert h.turn('hi'), h.screen()
    assert 'Hello over the cable.' in h.screen(), h.screen()
    assert h.uart.baud() == 19200 and h.m.irqsu > 0              # (IRQ 3: bytes came in on the interrupt)
    assert h.link.maxpay <= frame_limit_for(19200) - glp.OVERHEAD
    check(h)


def test_modem_call_and_chat():
    h = start([reply(('text', 'Hello over the phone line.'))], 'modem', '/D:300')
    out = h.serlink_out
    assert 'dialing 300' in out and 'Connected: CONNECT 2400' in out and 'COM1, 2400 baud' in out, out
    # the GRiD's modem set up, then the call; the Pi's set to answer by itself
    assert h.line.g.cmds == ['AT', 'ATE0V1Q0X4', 'AT&C1&D2', 'ATDT300'], h.line.g.cmds
    assert h.line.p.cmds == list(ModemLink.INIT) and h.line.calls == 1, h.line.p.cmds
    assert h.transport.online and h.transport.line_baud == 2400 and h.transport.frame_limit == 240
    t0 = h.m.us
    assert h.turn('hi', sim_s=60), h.screen()
    assert 'Hello over the phone line.' in h.screen(), h.screen()
    assert (h.m.us - t0) / 1e6 < 5, (h.m.us - t0) / 1e6
    check(h)


def test_big_file_over_the_cable():
    h = start([reply(('tool', 'str_replace_based_edit_tool',
                      {'command': 'create', 'path': 'A:\\BIG.TXT', 'file_text': BIG})),
               reply(('tool', 'str_replace_based_edit_tool',
                      {'command': 'view', 'path': 'A:\\BIG.TXT', 'view_range': [395, 400]})),
               reply(('text', 'Written and checked.'))], 'serial', '/P:2', mode='edits')
    assert h.turn('write a big file', sim_s=240), h.screen()
    assert bytes(h.m.fs['A:\\BIG.TXT']) == BIG.replace('\n', '\r\n').encode()
    r = [b for b in h.client.requests[2]['messages'][-1]['content'] if isinstance(b, dict) and b.get('type') == 'tool_result']
    assert 'line 00399' in r[0]['content'], r
    check(h)


def test_small_file_over_the_modem():
    text = ''.join('row %03d\n' % i for i in range(150))          # 1.2 KB: five frames at 2400 baud
    h = start([reply(('tool', 'str_replace_based_edit_tool',
                      {'command': 'create', 'path': 'A:\\NOTES.TXT', 'file_text': text})),
               reply(('text', 'Saved.'))], 'modem', '/D:300', mode='edits')
    assert h.turn('save my notes', sim_s=120), h.screen()
    assert bytes(h.m.fs['A:\\NOTES.TXT']) == text.replace('\n', '\r\n').encode()
    check(h)


def test_polled_without_the_irq():
    # the port's IRQ never comes (the 1520's modem's unknown till tried): every wait and poll drains the UART
    # (at the modem's 2400 baud: a byte every 4 ms, which CLAUDE.COM's polls keep up with; at 19200 they don't)
    h = EmuHarness([reply(('text', 'Polled, but here.'))], bridge='serial', serlink='/P:2 /B:2400', baud=2400)
    h.uart.int_pending = lambda: False
    h.boot()
    assert 'IRQ never came: polled' in h.serlink_out, h.serlink_out
    assert h.connect(30), h.screen()
    assert h.turn('hi'), h.screen()
    assert 'Polled, but here.' in h.screen() and h.m.irqsu == 0
    check(h)


def test_speeds():
    # /B: 115200 (divisor 1: its own banner, not a divide that overflows) down to 300
    for b in (115200, 38400, 9600, 300):
        h = EmuHarness([], bridge='serial')
        out = h.m.run_program('A:\\SERLINK.COM', '/P:2 /B:%d' % b, limit_us=10e6)
        assert not h.m.crash and h.m.tsr and 'COM2, %d baud' % b in out and h.uart.baud() == b, (b, out, h.m.crash)


def test_busy_number_leaves_nothing():
    h = EmuHarness([], bridge='modem')
    m = h.m
    vec60 = m.rd(0, 0x60 * 4, 4); vec0c = m.rd(0, 0x0C * 4, 4); mask = m.pic_mask
    lcr, dll, ier, mcr = h.uart.lcr, h.uart.dll, h.uart.ier, h.uart.mcr
    out = m.run_program('A:\\SERLINK.COM', '/D:999', limit_us=30e6)
    assert '** No connection: BUSY' in out and m.exit_code == 2 and not m.tsr, (out, m.exit_code)
    assert m.rd(0, 0x60 * 4, 4) == vec60 and m.rd(0, 0x0C * 4, 4) == vec0c and m.pic_mask == mask
    assert (h.uart.lcr, h.uart.dll, h.uart.ier, h.uart.mcr) == (lcr, dll, ier, mcr)


def test_unload_hangs_up_and_the_pi_answers_again():
    h = EmuHarness([], bridge='modem')
    m = h.m
    vec60 = m.rd(0, 0x60 * 4, 4); vec0c = m.rd(0, 0x0C * 4, 4)
    out = m.run_program('A:\\SERLINK.COM', '/D:300', limit_us=30e6)
    assert m.tsr and 'CONNECT 2400' in out, out
    m.stopped = False; m.tty = []
    h.pump_pi()
    assert h.transport.online
    out = m.run_program('A:\\SERLINK.COM', '', limit_us=5e6)           # loaded: how it stands
    assert 'Loaded.' in out and 'COM1, 2400 baud' in out and 'has a carrier' in out, out
    m.stopped = False; m.tty = []
    out = m.run_program('A:\\SERLINK.COM', '/U', limit_us=10e6)
    assert 'Hanging up.' in out and 'Unloaded.' in out and m.exit_code == 0, out
    assert h.line.hangups == 1
    assert m.rd(0, 0x60 * 4, 4) == vec60 and m.rd(0, 0x0C * 4, 4) == vec0c
    h.pump_pi()                                   # gridlink: the carrier gone, the modem set up for the next call
    assert not h.transport.online and h.line.p.cmds.count('ATS0=1') == 2, h.line.p.cmds
    m.stopped = False; m.tty = []
    out = m.run_program('A:\\SERLINK.COM', '/D:300', limit_us=30e6)  # and the GRiD can call again
    assert 'CONNECT 2400' in out and h.line.calls == 2, out


def term_over(bridge, serlink, sim_s):
    from test_emu_term import FAKE, in_step, mismatch
    h = EmuHarness(term=FAKE, args='/A:7 /T', bridge=bridge, serlink=serlink)
    try:
        h.boot()
        assert h.run_until(lambda: h.var('term') == 1 and h.var('connected') == 1, 30), (h.log, h.screen())
        t0 = h.m.us
        assert h.run_until(lambda: 'Welcome to Claude Code' in h.screen(), sim_s), h.screen()
        assert in_step(h, sim_s), mismatch(h)
        first = (h.m.us - t0) / 1e6
        h.type('hello', enter=False)
        assert h.run_until(lambda: 'hello' in h.screen(), sim_s), h.screen()
        assert in_step(h, sim_s), mismatch(h)
        check(h)
        return first
    finally:
        if h.router and h.router.term: h.router.term.stop()


def test_term_over_the_cable():
    t = term_over('serial', '/P:2', 30)
    assert t < 10, t


def test_term_over_the_modem():
    t = term_over('modem', '/D:300', 120)     # (Claude Code's first screen at 240 bytes a second)
    assert t < 60, t


SPOLL = """org 100h
        mov     si, 81h                 ; the address, in decimal
        xor     bx, bx
.sp:    lodsb
        cmp     al, ' '
        je      .sp
.dg:    sub     al, '0'
        cmp     al, 9
        ja      .one
        mov     cl, al
        mov     al, bl
        mov     ah, 10
        mul     ah
        add     al, cl
        mov     bl, al
        lodsb
        jmp     .dg
.one:   mov     ah, 05h
        int     60h
        mov     dl, 'N'
        jnc     .p
        mov     dl, 'C'
.p:     push    ax
        mov     ah, 02h
        int     21h
        pop     ax
        mov     cx, 4
.h:     rol     ax, 4
        push    ax
        and     al, 0Fh
        add     al, '0'
        cmp     al, '9'
        jbe     .d
        add     al, 7
.d:     mov     dl, al
        mov     ah, 02h
        int     21h
        pop     ax
        loop    .h
        mov     ax, 4C00h
        int     21h
"""


def spoll_com(tmp):
    src = os.path.join(tmp, 'SPOLL.ASM'); dst = os.path.join(tmp, 'SPOLL.COM')
    open(src, 'w').write('cpu 286\n' + SPOLL)
    subprocess.run(['nasm', '-f', 'bin', '-o', dst, src], check=True)
    return open(dst, 'rb').read()


def spoll(m, addr):
    m.stopped = False; m.tty = []
    return m.run_program('A:\\SPOLL.COM', ' %d' % addr, limit_us=5e6)


def test_other_addresses_no_listener():
    # no cartridge: an instrument's address isn't the link's, and goes nowhere (error 2, no listener)
    h = EmuHarness([], bridge='serial')
    m = h.m
    m.fs['A:\\SPOLL.COM'] = bytearray(spoll_com(h.tmp))
    out = m.run_program('A:\\SERLINK.COM', '/P:2', limit_us=10e6)
    assert m.tsr and 'GPIB instruments' not in out, out
    assert spoll(m, 6) == 'C0002', spoll(m, 6)
    assert spoll(m, 7) == 'N0000', spoll(m, 7)             # (the link: nothing waiting)
    h.uart.to_grid(b'\x07')                                  # a ring byte waiting: RQS
    m.us += 10000
    assert spoll(m, 7) == 'N0060', spoll(m, 7)


def test_over_the_cartridge_instruments_still_answer():
    # loaded over GRIDGPIB (the cartridge): the link's address on the serial line, the rest on the bus
    h = EmuHarness([], bridge='serial')
    m = h.m
    m.fs['A:\\SPOLL.COM'] = bytearray(spoll_com(h.tmp))
    out = m.run_program('A:\\GRIDGPIB.COM', '', limit_us=5e6)
    assert m.tsr, out
    m.stopped = False; m.tty = []
    out = m.run_program('A:\\SERLINK.COM', '/P:2', limit_us=10e6)
    assert m.tsr and 'GPIB instruments through the driver under it' in out, out
    assert spoll(m, 6) == 'N0041', spoll(m, 6)              # the FG5010 on the bus, through GRIDGPIB
    assert spoll(m, 7) == 'N0000', spoll(m, 7)              # the link, on the cable


if __name__ == '__main__':
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    if len(sys.argv) > 1: names = [n for n in names if any(a in n for a in sys.argv[1:])]
    ok = 0
    for n in names:
        try:
            globals()[n](); ok += 1; print('ok  ', n)
        except Exception:
            import traceback; print('FAIL', n); traceback.print_exc()
    print('%d of %d passed' % (ok, len(names)))
    sys.exit(0 if ok == len(names) else 1)
