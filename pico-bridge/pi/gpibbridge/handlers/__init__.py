"""Built-in handlers, and loading one from bridge.toml's `handler` setting."""
import importlib.util

from .base import Handler, Context  # noqa: F401
from .thrutest import ThruTest
from .scpi import Scpi

BUILTIN = {"thrutest": ThruTest, "scpi": Scpi}


def load(spec: str):
    """'thrutest', 'scpi', or '/path/to/file.py:ClassName'."""
    if spec in BUILTIN:
        return BUILTIN[spec]
    path, _, cls = spec.rpartition(":")
    if not path or not cls:
        raise ValueError(f"handler {spec!r}: use thrutest, scpi or /path/file.py:ClassName")
    s = importlib.util.spec_from_file_location("gpib_user_handler", path)
    mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(mod)
    return getattr(mod, cls)
