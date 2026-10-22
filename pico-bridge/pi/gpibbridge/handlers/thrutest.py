"""THRUTEST compatibility: answers exactly like the bench firmware's device mode ('l'), so A:\\THRUTEST on the
1520 tests the whole chain -- GRiD -> GPIB -> Pico -> USB -> Pi -> USB -> Pico -> GPIB -> GRiD.

  *IDN? (or a read with nothing written since power-up or a clear) -> the bench ID string
  any other message                                                  -> the same message echoed back
"""
from .base import Handler

# THRUTEST compares these 38 bytes exactly (tools/grid/THRUTEST.ASM idstr), so they must not change.
BENCH_ID = b"GPIB-Pico2,bench test,rev 1.2,addr 10\n"


class ThruTest(Handler):
    name = "thrutest"

    def __init__(self, ctx, options):
        super().__init__(ctx, options)
        self.last = None

    def _answer(self):
        if self.last is None or self.last.startswith(b"*IDN?"):
            return BENCH_ID
        return self.last

    def on_message(self, data, eoi):
        self.last = data
        return self._answer()

    def on_talk(self):
        return self._answer()

    def on_clear(self, kind):
        self.last = None
