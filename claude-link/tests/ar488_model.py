"""Behavioural model of an AR488 (0.53.46) in GPIB device mode, stock or with
the Grid-OS patch, for tests.  It follows the firmware's own logic:
parseInput() / lnRdy / device_talk_h() / sendStatus(), the 64-byte Arduino
serial receive buffer, and serial timing at the configured baud rate.

Time is in microseconds from a clock function the harness supplies.
"""
import collections

CR, LF, ESC, PLUS = 0x0D, 0x0A, 0x1B, 0x2B


class AR488Model:
    def __init__(s, clock, addr=7, patched=False, baud=115200, to_pi=None):
        s.clock = clock; s.addr = addr; s.patched = patched; s.baud = baud
        s.PBSIZE = 255 if patched else 128
        s.to_pi = to_pi or (lambda data, t: None)
        s.mode_device = True; s.eoi = True; s.eos = 3
        s.stat = 0; s.srq = False
        s.pbuf = bytearray(); s.lnrdy = 0; s.is_esc = False; s.plus_esc = False
        s.grid_srq_done = False
        s.rx = collections.deque()          # (arrival_us, byte) from the Pi
        s.rxbuf = collections.deque()       # Arduino serial ring (64)
        s.tx_free = 0.0                     # when the serial TX line is free
        s.listening = False; s.violations = []; s.events = []
        s.out = b''; s.inframe = bytearray()
        s.byte_us = 10e6 / baud
        s.talks = 0; s.spolls = 0; s.lost_partial = 0

    # ---- serial from the Pi --------------------------------------------
    def pi_write(s, data, latency_us=1000):
        """The Pi writes bytes; they arrive at line rate after latency."""
        t = max(s.clock() + latency_us, s.rx[-1][0] if s.rx else 0)
        for b in data:
            t += s.byte_us
            s.rx.append((t, b))

    def service(s):
        """Run the firmware main loop up to now."""
        now = s.clock()
        while s.rx and s.rx[0][0] <= now:
            t, b = s.rx.popleft()
            if len(s.rxbuf) >= 64:
                s.violations.append(('serial overflow', t)); continue
            s.rxbuf.append(b)
            if not s.listening:
                s._loop()                   # the firmware keeps up byte by byte
        if not s.listening:
            s._loop()

    def _loop(s):
        while True:
            if s.lnrdy == 1: s.exec_cmd()
            if s.rxbuf:
                st = 0                      # serialIn_h(): parse to a terminator
                while s.rxbuf and st == 0:
                    st = s.parse(s.rxbuf.popleft())
                s.lnrdy = st                # (overwrites a waiting line's 2!)
            if s.patched:
                if s.lnrdy == 2:
                    if not s.grid_srq_done: s.set_status(0x60); s.grid_srq_done = True
                else:
                    s.grid_srq_done = False
            if s.lnrdy != 1 and not s.rxbuf: break

    def parse(s, c):
        """parseInput() from AR488.ino."""
        r = 0
        if len(s.pbuf) < s.PBSIZE:
            if c in (CR, LF):
                if s.is_esc:
                    s.pbuf.append(c); s.is_esc = False
                else:
                    if not s.pbuf:
                        return 0
                    if len(s.pbuf) > 2 and s.pbuf[:2] == b'++' and not s.plus_esc:
                        r = 1
                    else:
                        r = 2
                    s.plus_esc = False
            elif c == ESC:
                if s.is_esc: s.pbuf.append(c); s.is_esc = False
                else: s.is_esc = True
            elif c == PLUS:
                if s.is_esc:
                    s.is_esc = False
                    if len(s.pbuf) < 2: s.plus_esc = True
                s.pbuf.append(c)
            else:
                s.pbuf.append(c); s.is_esc = False
        if len(s.pbuf) >= s.PBSIZE:
            if s.pbuf[:2] == b'++' and not r: s.pbuf.clear()
            else: r = 2
        return r

    def exec_cmd(s):
        cmd = bytes(s.pbuf[2:]).decode('latin1').strip()
        s.pbuf.clear(); s.lnrdy = 0
        tok = cmd.split(None, 1); name = tok[0] if tok else ''; arg = tok[1] if len(tok) > 1 else None
        s.events.append(('cmd', cmd, s.clock()))
        if name == 'status' and arg is not None: s.set_status(int(arg))
        elif name == 'status': s.reply(str(s.stat))
        elif name == 'ver':
            s.reply('AR488 GPIB controller, ver. 0.53.46, 22/05/2026' + (' +GRiD1' if s.patched else ''))
        elif name == 'addr':
            if arg is None: s.reply(str(s.addr))
            else: s.addr = int(arg)
        elif name == 'mode' and arg is not None: s.mode_device = arg.strip() == '0'
        elif name == 'eoi' and arg is not None: s.eoi = arg.strip() == '1'
        elif name == 'eos' and arg is not None: s.eos = int(arg)

    def reply(s, text):
        s._tx((text + '\r\n').encode())

    def set_status(s, v):
        s.stat = v & 0xFF; s.srq = bool(v & 0x40)

    # ---- serial to the Pi ----------------------------------------------
    def _tx(s, data):
        t = max(s.tx_free, s.clock())
        for _ in data: t += s.byte_us
        s.tx_free = t
        s.to_pi(bytes(data), t)

    # ---- GPIB side (called by the 7210 model) --------------------------
    @property
    def status(s):
        """A serial poll: sendStatus() returns the byte and clears RQS."""
        s.service()
        v = s.stat; s.spolls += 1
        s.stat &= ~0x40; s.srq = False
        return v

    def on_listen(s, active):
        s.service()
        s.listening = active

    def rx_byte(s, v, eoi):
        """A data byte while listening.  device_listen_h() writes each byte to
        the serial port as it arrives, so the GPIB handshake waits whenever
        the 64-byte TX buffer is full.  Returns when the byte is accepted
        (the controller's DO); the Pi gets the frame when its last byte is
        through the serial line."""
        now = s.clock()
        s.listening = True
        s.tx_free = max(s.tx_free, now) + s.byte_us
        s.inframe.append(v)
        if eoi:
            s.to_pi(bytes(s.inframe), s.tx_free); s.inframe = bytearray()
            s.listening = False
            s.service()
        return max(now, s.tx_free - 65 * s.byte_us)

    def on_talk(s):
        """device_talk_h(): called when addressed to talk (not a serial poll)."""
        s.service(); s.talks += 1
        if s.lnrdy == 2:
            s.out = bytes(s.pbuf); s.pbuf.clear(); s.lnrdy = 0
            if s.patched: s.set_status(0)
        else:
            if s.pbuf and not s.patched:
                s.lost_partial += 1; s.violations.append(('partial line discarded', s.clock()))
            if not s.patched:
                s.pbuf.clear(); s.lnrdy = 0
            s.out = b''

    def sdc(s):
        s.pbuf.clear(); s.lnrdy = 0; s.stat = 0; s.srq = False
