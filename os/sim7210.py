"""sim7210, the uPD7210 GPIB chip and bus model: one copy, tools/sim7210.py.
This file stands in for it on this
directory's path: it loads that one by path and registers it as `sim7210`,
so every importer, from os/, tools/ or claude-link/tests/, gets the same
module (GHOSTDEV, KEYS and the bus shared by identity).  A plain
`from sim7210 import *` here would import this file itself."""
import importlib.util, os, sys
_p = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'sim7210.py'))
_s = importlib.util.spec_from_file_location('sim7210', _p)
_m = importlib.util.module_from_spec(_s)
sys.modules['sim7210'] = _m             # (import then returns this, not the stand-in)
_s.loader.exec_module(_m)
