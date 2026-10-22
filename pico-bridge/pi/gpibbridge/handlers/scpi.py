"""A small IEEE-488.2 / SCPI-style instrument, as a starting point for real services on the Pi.

Common commands: *IDN? *RST *CLS *ESE n *ESE? *ESR? *SRE n *SRE? *STB? *OPC? *OPC *WAI *TST?
Plus:            SYSTem:ERRor?  SYSTem:TIME?  SYSTem:DATE?  ECHO <text>  PI:TEMPerature?  PI:UPTime?
Several commands may share a message, separated by ';'.  Replies to queries in one message are joined with ';'
and end with a newline (EOI on it), as 488.2 asks.

Add your own commands without touching this file:

    from gpibbridge.handlers.scpi import Scpi
    class MyLab(Scpi):
        def setup_commands(self):
            super().setup_commands()
            self.command("MEAS:VOLT?", lambda arg: "1.2345")      # a query returns its answer as text
            self.command("RELay", self.relay)                   # a setting returns None

and set handler = "/home/pi/mylab.py:MyLab" in /etc/gpib-bridge/bridge.toml.
"""
import datetime
import re
import socket
import time

from .base import Handler

ESR_OPC, ESR_QYE, ESR_DDE, ESR_EXE, ESR_CME = 0x01, 0x04, 0x08, 0x10, 0x20
STB_ESB, STB_MAV, STB_EAV = 0x20, 0x10, 0x04


def _short(word):
    """SCPI short form of one header word: its leading capitals (and digits)."""
    m = re.match(r"[A-Z0-9*]+", word)
    return m.group(0) if m else word


class Scpi(Handler):
    name = "scpi"

    def __init__(self, ctx, options):
        super().__init__(ctx, options)
        self.ident = options.get("idn", f"PounceLab,GPIB-Pico2 Bridge,{socket.gethostname()},{ctx.firmware}")
        self.esr = 0
        self.ese = 0
        self.sre = 0
        self.last_reason = 0
        self.errors = []
        self.started = time.time()
        self.table = []          # (list of (short, long) per header word, query?, fn)
        self.setup_commands()

    # ---- the command table ------------------------------------------------------------------------------------
    def command(self, header, fn):
        """header like 'SYSTem:ERRor?' (capitals = short form) or '*IDN?'."""
        q = header.endswith("?")
        words = header.rstrip("?").split(":")
        self.table.append(([(_short(w).upper(), w.upper()) for w in words], q, fn))

    def setup_commands(self):
        c = self.command
        c("*IDN?", lambda a: self.ident)
        c("*RST", lambda a: self.reset())
        c("*CLS", lambda a: self.clear_status())
        c("*ESE", lambda a: setattr(self, "ese", int(a) & 0xFF))
        c("*ESE?", lambda a: str(self.ese))
        c("*ESR?", lambda a: str(self.read_esr()))
        c("*SRE", lambda a: setattr(self, "sre", int(a) & 0xBF))
        c("*SRE?", lambda a: str(self.sre))
        c("*STB?", lambda a: str(self.stb()))
        c("*OPC?", lambda a: "1")
        c("*OPC", lambda a: self.set_esr(ESR_OPC))
        c("*WAI", lambda a: None)
        c("*TST?", lambda a: "0")
        c("SYSTem:ERRor?", lambda a: self.pop_error())
        c("SYSTem:TIME?", lambda a: datetime.datetime.now().strftime("%H,%M,%S"))
        c("SYSTem:DATE?", lambda a: datetime.datetime.now().strftime("%Y,%m,%d"))
        c("ECHO", lambda a: a)
        c("PI:TEMPerature?", lambda a: self.cpu_temp())
        c("PI:UPTime?", lambda a: f"{time.time() - self.started:.0f}")

    def lookup(self, header):
        q = header.endswith("?")
        words = header.rstrip("?").upper().split(":")
        for pat, pq, fn in self.table:
            if pq == q and len(pat) == len(words) and all(w in (s, l) for w, (s, l) in zip(words, pat)):
                return fn
        return None

    # ---- status ---------------------------------------------------------------------------------------------
    def stb(self):
        s = 0
        if self.esr & self.ese:
            s |= STB_ESB
        if self.errors:
            s |= STB_EAV
        return s

    def update_status(self):
        """488.2: request service when a summary bit enabled in *SRE goes from false to true (a new reason)."""
        s = self.stb()
        reason = s & self.sre
        if reason & ~self.last_reason:
            self.ctx.request_service(s)
        else:
            self.ctx.set_status(s)
        self.last_reason = reason

    def set_esr(self, bits):
        self.esr |= bits
        return None

    def read_esr(self):
        v, self.esr = self.esr, 0
        return v

    def error(self, code, text, esr_bit=ESR_CME):
        if len(self.errors) < 10:
            self.errors.append(f'{code},"{text}"')
        self.esr |= esr_bit

    def pop_error(self):
        return self.errors.pop(0) if self.errors else '0,"No error"'

    def clear_status(self):
        self.esr = 0
        self.errors.clear()

    def reset(self):
        self.ese = self.sre = 0

    @staticmethod
    def cpu_temp():
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                return f"{int(f.read()) / 1000:.1f}"
        except OSError:
            return "9.91E+37"

    # ---- the handler ------------------------------------------------------------------------------------------
    def on_message(self, data, eoi):
        text = data.decode("ascii", "replace").strip()
        answers = []
        for unit in filter(None, (u.strip() for u in text.split(";"))):
            header, _, arg = unit.partition(" ")
            fn = self.lookup(header)
            if fn is None:
                self.error(-113, "Undefined header")
                continue
            try:
                r = fn(arg.strip())
            except (ValueError, TypeError) as e:
                self.error(-224, f"Illegal parameter value ({e})", ESR_EXE)
                continue
            if header.endswith("?") or r is not None:     # ECHO answers too
                answers.append("" if r is None else str(r))
        self.update_status()
        if answers:
            return (";".join(answers) + "\n").encode("ascii", "replace")
        return None

    def on_talk(self):
        self.error(-420, "Query UNTERMINATED", ESR_QYE)
        self.update_status()
        return None

    def on_clear(self, kind):
        pass

    def on_poll(self, status):
        self.ctx.set_status(self.stb())        # the poll served the request; only a new reason raises SRQ again
