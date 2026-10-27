"""gpib-bridged: the Raspberry Pi side of the GPIB-Pico2 bridge.

Owns the Pico's USB serial port, keeps the bridge online at the configured GPIB address, turns what the 1520
sends into messages for a handler (handlers/), sends the handler's replies back, and serves a control socket for
gpibctl.  One select loop, and a thread that only writes PINGs (the select loop alone closes the port).

    python3 -m gpibbridge.daemon [-c /etc/gpib-bridge/bridge.toml] [--port /dev/ttyACM0] [--ctl PATH] [-v]
"""
import argparse
import collections
import glob
import json
import logging
import os
import selectors
import socket
import sys
import threading
import time

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

import serial
import serial.tools.list_ports

from . import protocol as P
from . import handlers

log = logging.getLogger("gpib-bridge")

DEFAULTS = {
    "port": "auto",
    "address": 7,              # where CLAUDE.COM looks for the Pi
    "handler": "thrutest",
    "control_socket": "/run/gpib-bridge/ctl.sock",
    "log_level": "info",
    "handler_options": {},
}

PICO_VID = 0x2E8A


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        if tomllib is None:
            raise SystemExit("Python 3.11 or later is needed to read bridge.toml")
        with open(path, "rb") as f:
            cfg.update(tomllib.load(f))
    a = int(cfg["address"])
    if not 0 <= a <= 30:
        raise SystemExit(f"address {a}: a GPIB primary address is 0..30")
    cfg["address"] = a
    return cfg


def candidate_ports(spec):
    if spec != "auto":
        return [spec]
    ports = []
    if os.path.exists("/dev/gpib-bridge"):
        ports.append("/dev/gpib-bridge")
    ports += sorted(glob.glob("/dev/serial/by-id/*Pico*"))
    ports += [p.device for p in serial.tools.list_ports.comports() if p.vid == PICO_VID]
    seen, out = set(), []
    for p in ports:
        r = os.path.realpath(p)
        if r not in seen:
            seen.add(r)
            out.append(p)
    return out


class Bridge(handlers.Context):
    """The connection to the Pico, plus the message/reply bookkeeping the handlers rely on."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.address = cfg["address"]
        self.ser = None
        self.port = None
        self.deframer = P.Deframer()
        self.firmware = "?"
        self.tx_ring = 0
        self.connected = False
        self.hello_at = 0.0
        self.last_ping = 0.0
        self.last_pong = 0.0
        self.pico = {}
        self.gen = 0                     # the Pico's message generation, as last seen
        self.msg_gen = None
        self.msg = bytearray()
        self.sent_total = 0              # tx bytes sent to the Pico (mod 2**32)
        self.consumed = 0                # tx bytes the Pico has taken off its ring (mod 2**32)
        self.pending = collections.deque()   # (gen, bytes, eoi) waiting for credit
        self.sent = collections.deque()      # (gen, sent_total after it) for bytes the Pico hasn't consumed yet
        self.want_online = True
        self.wlock = threading.Lock()        # the ping thread writes too
        self.dead = None                     # a port a write failed on: the main loop closes it (see write())
        self.status = 0
        self.rsv = False
        self.ren = False
        self.llo = False
        self.stats = collections.Counter()
        self.watchers = []               # control-socket clients that asked for events
        self.handler = None
        self.handler_cls = handlers.load(cfg["handler"])

    # ---- handler context -------------------------------------------------------------------------------------
    def reply(self, data: bytes, eoi: bool = True, gen=None):
        """Queue data for the GRiD's next read (a reply for an older message is dropped)."""
        g = self.gen if gen is None else gen
        self.pending = collections.deque(p for p in self.pending if p[0] == g)
        if data:
            self.pending.append((g, bytes(data), eoi))
            self.pump()

    def request_service(self, status: int):
        self.status, self.rsv = status & 0xBF, True
        self.write(P.stb(self.status, True))

    def set_status(self, status: int):
        self.status = status & 0xBF
        self.write(P.stb(self.status, self.rsv))

    def log(self, text):
        log.info("handler: %s", text)

    # ---- serial ---------------------------------------------------------------------------------------------
    def write(self, frame):
        ser = self.ser
        if not ser or ser is self.dead:
            return
        try:
            with self.wlock:
                ser.write(frame)
        except Exception as e:
            # Any exception: a port the main loop closes under the ping thread's write makes pyserial 3.5 raise
            # TypeError (its fd is None by then), not SerialException.
            log.warning("write to %s failed: %r", self.port, e)
            # Not closed here: this may be the ping thread, and a port closed under the main loop's read raises
            # what nothing catches (pyserial's in_waiting: TypeError); close() also tells the control clients.
            self.dead = ser

    def ping_thread(self):
        """PINGs from a thread, so a slow handler can't make the Pico think the Pi is gone."""
        while True:
            time.sleep(1.0)
            try:
                if self.ser is not None and self.connected:
                    self.write(P.ping())
            except Exception:                # nothing may end this thread: without PINGs the bridge goes offline
                log.exception("ping thread")

    def try_open(self):
        for p in candidate_ports(self.cfg["port"]):
            try:
                s = serial.Serial(p, 115200, timeout=0, write_timeout=2)
            except (serial.SerialException, OSError) as e:
                log.debug("can't open %s: %s", p, e)
                continue
            try:
                s.dtr = True
            except (serial.SerialException, OSError):
                pass                         # a pty (the simulation) has no DTR
            self.ser, self.port = s, p
            self.deframer = P.Deframer()
            self.connected = False
            self.hello_at = time.monotonic()
            self.write(P.hello_req())
            log.info("opened %s, waiting for the bridge firmware to say hello", p)
            return True
        return False

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        if self.connected:
            self.broadcast({"event": "DISCONNECTED"})
        self.ser = None
        self.dead = None
        self.connected = False

    def on_connected(self, hello):
        if hello["proto"] != P.PROTO_VERSION:
            log.error("bridge firmware speaks protocol %d, this daemon %d: update one of them",
                      hello["proto"], P.PROTO_VERSION)
            self.close()
            return
        self.firmware = hello["fw"]
        self.tx_ring = hello["tx_ring"]
        self.consumed = hello["consumed"]
        self.sent_total = (hello["consumed"] + hello["queued"]) & 0xFFFFFFFF
        self.pending.clear()
        self.sent.clear()
        self.msg_gen, self.msg = None, bytearray()
        self.connected = True
        if self.handler is None:
            self.handler = self.handler_cls(self, self.cfg.get("handler_options", {}))
            log.info("handler: %s", self.handler.name)
        self.rsv = False                     # a new session starts with no service request
        self.write(P.stb(self.status, False))
        self.write(P.config(self.address, self.want_online))
        self.last_ping = self.last_pong = time.monotonic()
        log.info("bridge on %s: %s; online at GPIB address %d", self.port, self.firmware, self.address)
        self.broadcast({"event": "CONNECTED", "firmware": self.firmware, "address": self.address})

    def pump(self):
        """Send queued reply bytes as the Pico's ring has room."""
        while self.pending and self.connected:
            room = self.tx_ring - ((self.sent_total - self.consumed) & 0xFFFFFFFF)
            if room <= 0:
                return
            g, data, eoi = self.pending[0]
            n = min(len(data), room, P.DATA_CHUNK)
            last = n == len(data)
            self.write(P.tx(g, data[:n], eoi and last))
            self.sent_total = (self.sent_total + n) & 0xFFFFFFFF
            self.sent.append((g, self.sent_total))
            self.stats["bytes_out"] += n
            if last:
                self.pending.popleft()
            else:
                self.pending[0] = (g, data[n:], eoi)

    # ---- frames from the Pico -------------------------------------------------------------------------------
    def on_readable(self):
        try:
            data = self.ser.read(self.ser.in_waiting or 1)
        except (serial.SerialException, OSError) as e:
            log.warning("bridge on %s went away: %s", self.port, e)
            self.close()
            return
        for f in self.deframer.feed(data):
            if f:
                self.on_frame(f)

    def on_frame(self, f):
        kind, d = P.parse(f)
        if kind == "hello":
            self.on_connected(d)
            return
        if not self.connected:
            return
        if kind == "data":
            self.on_data(d)
        elif kind == "event":
            self.on_event(d)
        elif kind == "credit":
            self.consumed = d["consumed"]
            while self.sent and ((self.consumed - self.sent[0][1]) & 0xFFFFFFFF) < 0x80000000:
                self.sent.popleft()          # end <= consumed: the Pico has finished with these bytes
            self.pump()
        elif kind == "pong":
            self.pico = d
            self.last_pong = time.monotonic()
            if self.want_online and not d["online"]:
                log.warning("bridge reports offline (missed PINGs?): putting it back online")
                self.write(P.config(self.address, True))
        elif kind == "log":
            log.warning("pico: %s", d["text"])
            self.broadcast({"event": "PICO_LOG", "text": d["text"]})

    def new_gen(self, g):
        if g != self.gen:
            self.gen = g
            self.pending = collections.deque(p for p in self.pending if p[0] == g)

    def on_data(self, d):
        g = d["gen"]
        self.new_gen(g)
        if self.msg_gen != g:
            self.msg_gen, self.msg = g, bytearray()
        self.msg += d["data"]
        self.stats["bytes_in"] += len(d["data"])
        if len(self.msg) > 1 << 20:
            log.warning("message over 1 MB: dropped")
            self.msg = bytearray()
        if d["end"]:
            msg, self.msg, self.msg_gen = bytes(self.msg), bytearray(), None
            self.stats["messages"] += 1
            self.broadcast({"event": "MESSAGE", "gen": g, "eoi": d["eoi"], "len": len(msg),
                            "data": msg[:200].decode("latin-1")})
            log.debug("message gen %d, %d bytes%s: %r", g, len(msg), "" if d["eoi"] else " (no EOI)", msg[:80])
            r = self.call("on_message", msg, d["eoi"])
            if r:
                self.reply(r, True, g)

    def on_event(self, d):
        name, g = d["name"], d["gen"]
        self.new_gen(g)
        self.stats[name] += 1
        ev = {"event": name, "gen": g}
        if name == "TALK_WAIT":
            # Only bytes for THIS generation, still on their way, mean the reply is coming.  (Stale bytes in
            # flight will be dropped by the Pico and don't count.)
            arg = d["arg"]
            coming = any(p[0] == g for p in self.pending) or any(
                sg == g and 0 < ((end - arg) & 0xFFFFFFFF) < 0x80000000 for sg, end in self.sent)
            if not coming:
                r = self.call("on_talk")
                if r:
                    self.reply(r, True, g)
                else:
                    ev["unanswered"] = True
        elif name in ("DCL", "SDC"):
            self.msg, self.msg_gen = bytearray(), None
            self.call("on_clear", name)
        elif name == "OFFLINE":
            self.msg, self.msg_gen = bytearray(), None
            if self.want_online:
                self.write(P.config(self.address, True))
        elif name == "GET":
            self.call("on_trigger")
        elif name == "REN":
            self.ren = bool(d["arg"])
            if not self.ren:
                self.llo = False
            ev["ren"] = self.ren
            self.call("on_remote", self.ren, self.llo, False)
        elif name == "LLO":
            self.llo = True
            self.call("on_remote", self.ren, True, False)
        elif name == "GTL":
            self.call("on_remote", self.ren, self.llo, True)
        elif name == "SPOLL":
            ev["status"] = d["b"]
            if d["b"] & 0x40:
                self.rsv = False
            self.call("on_poll", d["b"])
        elif name == "IFC":
            self.msg, self.msg_gen = bytearray(), None     # a half message is dropped
            self.call("on_interface_clear")
        elif name == "ONLINE":
            ev["address"] = d["b"]
            self.ren = bool(d["arg"])
        level = logging.DEBUG if name in ("LISTEN", "UNLISTEN", "TALK", "UNTALK", "TX_DONE", "TALK_WAIT") \
            else logging.INFO
        log.log(level, "event %s gen %d", name, g)
        self.broadcast(ev)

    def call(self, method, *args):
        try:
            return getattr(self.handler, method)(*args)
        except Exception:
            log.exception("handler %s.%s failed", self.handler.name, method)
            self.stats["handler_errors"] += 1
            return None

    # ---- housekeeping ---------------------------------------------------------------------------------------
    def tick(self):
        now = time.monotonic()
        if not self.ser:
            return
        if not self.connected:
            if now - self.hello_at > 3:
                log.warning("%s did not answer HELLO: not the bridge firmware (bench firmware?)", self.port)
                self.close()
            return
        if now - self.last_pong > 6:
            log.warning("no PONG from the bridge for 6 s: reconnecting")
            self.close()
            return
        if self.handler:
            self.call("tick")

    # ---- control socket -------------------------------------------------------------------------------------
    def broadcast(self, ev):
        if not self.watchers:
            return
        ev["t"] = round(time.time(), 3)
        line = (json.dumps(ev) + "\n").encode()
        for c in list(self.watchers):
            try:
                c.setblocking(False)
                c.send(line)                 # a watcher that can't keep up loses events, never stalls us
            except BlockingIOError:
                pass
            except OSError:
                self.watchers.remove(c)
            finally:
                try:
                    c.setblocking(True)
                except OSError:
                    pass

    def status_dict(self):
        return {"port": self.port, "connected": self.connected, "firmware": self.firmware,
                "address": self.address, "handler": self.handler.name if self.handler else None,
                "gen": self.gen, "status_byte": self.status, "rsv": self.rsv, "ren": self.ren, "llo": self.llo,
                "pending_reply_bytes": sum(len(p[1]) for p in self.pending),
                "in_flight": (self.sent_total - self.consumed) & 0xFFFFFFFF,
                "stats": dict(self.stats), "pico": self.pico}

    def control(self, req, conn):
        cmd = req.get("cmd")
        if cmd == "status":
            return {"ok": True, **self.status_dict()}
        if cmd == "events":
            self.watchers.append(conn)
            return {"ok": True, "watching": True}
        if cmd == "srq":
            self.request_service(int(req.get("status", 0)))
            return {"ok": True}
        if cmd == "status_byte":
            self.set_status(int(req.get("status", 0)))
            return {"ok": True}
        if cmd == "reply":
            data = bytes.fromhex(req["hex"]) if "hex" in req else req.get("text", "").encode("latin-1")
            self.reply(data, bool(req.get("eoi", True)))
            return {"ok": True, "queued": len(data)}
        if cmd == "address":
            a = int(req["address"])
            if not 0 <= a <= 30:
                return {"ok": False, "error": "address must be 0..30"}
            self.address = a
            self.write(P.config(a, True))
            return {"ok": True, "address": a, "note": "until restart; set it in bridge.toml to keep it"}
        if cmd == "offline":
            self.want_online = False
            self.write(P.config(self.address, False))
            return {"ok": True}
        if cmd == "online":
            self.want_online = True
            self.write(P.config(self.address, True))
            return {"ok": True}
        if cmd == "bootsel":
            self.write(P.bootsel())
            self.close()
            self.reopen_after = time.monotonic() + float(req.get("hold", 30))
            return {"ok": True, "note": "the Pico is now a USB drive (RP2350); the daemon waits before reopening"}
        return {"ok": False, "error": f"unknown command {cmd!r}"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-c", "--config", default="/etc/gpib-bridge/bridge.toml")
    ap.add_argument("--port", help="serial port (overrides the config)")
    ap.add_argument("--ctl", help="control socket path (overrides the config)")
    ap.add_argument("--address", type=int, help="GPIB address (overrides the config)")
    ap.add_argument("--handler", help="handler (overrides the config)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    for k in ("port", "address", "handler"):
        if getattr(a, k) is not None:
            cfg[k] = getattr(a, k)
    if a.ctl:
        cfg["control_socket"] = a.ctl
    logging.basicConfig(level=logging.DEBUG if a.verbose else getattr(logging, cfg["log_level"].upper(), 20),
                        format="%(levelname)s %(message)s" if os.environ.get("INVOCATION_ID")
                        else "%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    b = Bridge(cfg)
    b.reopen_after = 0.0
    threading.Thread(target=b.ping_thread, daemon=True).start()

    sel = selectors.DefaultSelector()
    path = cfg["control_socket"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.unlink(path)
    lsock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    lsock.bind(path)
    os.chmod(path, 0o660)
    lsock.listen(8)
    lsock.setblocking(False)
    sel.register(lsock, selectors.EVENT_READ, "listen")
    clients = {}
    registered_ser = None
    registered_fd = None
    next_open = 0.0
    last_tick = 0.0
    warned = False
    log.info("gpib-bridged starting: address %d, handler %s, control socket %s",
             cfg["address"], cfg["handler"], path)
    while True:
        now = time.monotonic()
        if b.ser is not None and b.dead is b.ser:
            b.close()                        # a write failed on it (maybe the ping thread's): closed in this thread
        if b.ser is None and now >= max(next_open, b.reopen_after):
            if not b.try_open():
                if not warned:
                    log.warning("no bridge found (port %s); retrying every second", cfg["port"])
                    warned = True
            else:
                warned = False
            next_open = now + 1.0
        if registered_ser is not b.ser:
            # Registered by file descriptor number: a closed port can't be asked for its fileno() any more,
            # and a reopened one usually gets the same number back.
            if registered_fd is not None:
                try:
                    sel.unregister(registered_fd)
                except (KeyError, ValueError, OSError):
                    pass
                registered_fd = None
            if b.ser is not None:
                registered_fd = b.ser.fileno()
                sel.register(registered_fd, selectors.EVENT_READ, "serial")
            registered_ser = b.ser
        for key, _ in sel.select(timeout=0.05):
            if key.data == "serial":
                if b.ser is not None:
                    b.on_readable()
            elif key.data == "listen":
                conn, _ = lsock.accept()
                conn.setblocking(True)
                conn.settimeout(2)
                clients[conn] = bytearray()
                sel.register(conn, selectors.EVENT_READ, "client")
            else:
                conn = key.fileobj
                try:
                    chunk = conn.recv(65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    sel.unregister(conn)
                    clients.pop(conn, None)
                    if conn in b.watchers:
                        b.watchers.remove(conn)
                    conn.close()
                    continue
                clients[conn] += chunk
                while b"\n" in clients[conn]:
                    line, _, rest = bytes(clients[conn]).partition(b"\n")
                    clients[conn] = bytearray(rest)
                    try:
                        resp = b.control(json.loads(line), conn)
                    except Exception as e:
                        resp = {"ok": False, "error": repr(e)}
                    try:
                        conn.sendall((json.dumps(resp) + "\n").encode())
                    except OSError:
                        pass
        if now - last_tick >= 0.1:
            last_tick = now
            b.tick()


if __name__ == "__main__":
    main()
