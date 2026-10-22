"""What a handler is: the code that decides how the bridge answers the GRiD.

The daemon calls these methods, one at a time, from its single thread.  Keep them quick (well under the GRiD
driver's timeout, about 2 s); for slow work, answer later with ctx.reply() and/or ctx.request_service().

A message is everything the 1520 sends to the bridge between being addressed to listen and EOI (or being
unaddressed).  A reply is what the 1520 gets when it next reads from the bridge.  Write your own handler by
subclassing Handler in a .py file and pointing `handler = "/path/file.py:ClassName"` at it in bridge.toml.
"""


class Context:
    """Given to handlers.  Implemented by the daemon."""

    address: int        # the bridge's GPIB address
    firmware: str       # the Pico firmware tag

    def reply(self, data: bytes, eoi: bool = True):
        """Queue data for the GRiD's next read.  A reply still waiting for an older message is dropped."""
        raise NotImplementedError

    def request_service(self, status: int):
        """Assert SRQ with this status byte (bit 6, RQS, is added); cleared when the GRiD serially polls."""
        raise NotImplementedError

    def set_status(self, status: int):
        """The status byte a serial poll returns when no service is requested."""
        raise NotImplementedError

    def log(self, text: str):
        raise NotImplementedError


class Handler:
    name = "base"

    def __init__(self, ctx: Context, options: dict):
        self.ctx = ctx
        self.options = options

    def on_message(self, data: bytes, eoi: bool):
        """A whole message from the GRiD.  Return the reply (bytes, sent with EOI on its last byte) or None."""
        return None

    def on_talk(self):
        """The GRiD reads from the bridge and there is no reply waiting.  Return bytes, or None to let it time out."""
        return None

    def on_clear(self, kind: str):
        """DCL (every device) or SDC (addressed to the bridge): drop any half-done work."""

    def on_trigger(self):
        """GET (group execute trigger) while addressed to listen."""

    def on_remote(self, ren: bool, llo: bool, local_requested: bool):
        """REN changed, LLO was sent, or GTL addressed the bridge."""

    def on_poll(self, status: int):
        """The GRiD serially polled the bridge and got this byte."""

    def on_interface_clear(self):
        """IFC: the 1520 reset the bus interface (the bridge is unaddressed)."""

    def tick(self):
        """Called about every 100 ms."""
