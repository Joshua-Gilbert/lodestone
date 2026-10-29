"""End-to-end tests: GRiD model <-> AR488 model <-> gridlink <-> scripted Claude.

    python3 tests/test_e2e.py            (or: python3 -m pytest tests)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gridsim import Harness
from fake_anthropic import reply
from gridlink import tools

CFG_C = b'#include <stdio.h>\r\nint rate = 1;\r\nint main(void) { return rate; }\r\n'


def check(h):
    assert not h.nano.violations, h.nano.violations
    errs = [l for l in h.log if 'Traceback' in str(l) or 'error' in str(l).lower()]
    assert not errs, errs


def test_connect_and_chat(patched=True):
    h = Harness([reply(('text', 'Hello from the Pi. The GRiD is **connected** and ready.'))], patched=patched)
    assert h.connect(), 'no connection'
    h.turn('hi')
    t = h.text()
    assert 'Welcome to Claude for GRiD' in t, t
    assert 'Hello from the Pi.' in t, t
    assert h.grid.time_set is not None
    check(h)
    return h


def test_connect_stock():
    test_connect_and_chat(patched=False)


def test_read_file():
    h = Harness([reply(('text', "I'll read it."), ('tool', 'str_replace_based_edit_tool',
                                                     {'command': 'view', 'path': 'a:\\cfg.c'})),
                 reply(('text', 'It sets rate to 1.'))], files={'A:\\CFG.C': CFG_C})
    h.connect(); h.turn('what does cfg.c do?')
    req = h.client.requests[1]['messages'][-1]['content']
    res = [b for b in req if isinstance(b, dict) and b.get('type') == 'tool_result'][0]
    assert '2\tint rate = 1;' in res['content'], res
    assert 'Read 3 lines' in h.text()
    check(h)


def test_edit_with_permission():
    h = Harness([reply(('tool', 'str_replace_based_edit_tool',
                        {'command': 'str_replace', 'path': 'A:\\CFG.C',
                         'old_str': 'int rate = 1;', 'new_str': 'int rate = 5;'})),
                 reply(('text', 'Done.'))], files={'A:\\CFG.C': CFG_C})
    h.connect(); h.turn('set rate to 5')
    assert h.grid.asks and 'edit' in h.grid.asks[0][0].lower(), h.grid.asks
    assert h.grid.fs['A:\\CFG.C'] == CFG_C.replace(b'rate = 1', b'rate = 5'), h.grid.fs
    assert 'A:\\CFG.$$$' not in h.grid.fs
    assert 'Updated A:\\CFG.C with 1 addition and 1 removal' in h.text(), h.text()
    check(h)


def test_edit_rejected():
    h = Harness([reply(('tool', 'str_replace_based_edit_tool',
                        {'command': 'str_replace', 'path': 'A:\\CFG.C',
                         'old_str': 'int rate = 1;', 'new_str': 'int rate = 5;'})),
                 reply(('text', 'OK, I will wait.'))], files={'A:\\CFG.C': CFG_C}, answer='n')
    h.connect(); h.turn('set rate to 5')
    assert h.grid.fs['A:\\CFG.C'] == CFG_C
    req = h.client.requests[1]['messages'][-1]['content']
    res = [b for b in req if isinstance(b, dict) and b.get('type') == 'tool_result'][0]
    assert res.get('is_error') and res['content'] == tools.REJECTED
    check(h)


def test_big_file_both_ways():
    big = ''.join('line %05d: the quick brown fox jumps over the lazy dog\n' % i for i in range(400))
    h = Harness([reply(('tool', 'str_replace_based_edit_tool',
                        {'command': 'create', 'path': 'A:\\BIG.TXT', 'file_text': big})),
                 reply(('tool', 'str_replace_based_edit_tool', {'command': 'view', 'path': 'A:\\BIG.TXT',
                                                                 'view_range': [399, 400]})),
                 reply(('text', 'Written and checked.'))], mode='edits')
    h.connect(); h.turn('write a big file')
    assert h.grid.fs['A:\\BIG.TXT'] == big.replace('\n', '\r\n').encode()
    req = h.client.requests[2]['messages'][-1]['content']
    res = [b for b in req if isinstance(b, dict) and b.get('type') == 'tool_result'][0]
    assert 'line 00399' in res['content'], res
    check(h)
    return h


def test_dos_command_and_screenshot():
    h = Harness([reply(('tool', 'grid_command', {'command': 'DIR'})),
                 reply(('tool', 'grid_command', {'command': 'TM5000G', 'capture': False,
                                                 'keys': '1{ENTER}{WAIT 0.5}{SNAP}{ESC}'})),
                 reply(('text', 'TM5000G is at version 3.7.'))],
                files={'A:\\TM5000G.EXE': b'MZ' + bytes(100)}, mode='auto')
    h.connect(); h.turn('look around and start TM5000G')
    first = [b for b in h.client.requests[1]['messages'][-1]['content'] if b.get('type') == 'tool_result'][0]
    assert 'A:\\TM5000G.EXE' in first['content'][0]['text'], first
    assert 'A:\\CLAUDE.OUT' not in h.grid.fs              # read and deleted
    cmd, keys = h.grid.last_run
    assert cmd == 'TM5000G' and keys.startswith(b'1\x02\r\x1c') and b'\xff\xfe\x00' in keys, (cmd, keys)
    second = [b for b in h.client.requests[2]['messages'][-1]['content'] if b.get('type') == 'tool_result'][0]
    assert 'TM5000G v3.7' in str(second['content']), second
    check(h)


def test_gpib():
    h = Harness([reply(('tool', 'gpib', {'action': 'query', 'address': 29, 'command': 'ID?'})),
                 reply(('tool', 'gpib', {'action': 'write', 'address': 6, 'command': 'FREQ 1E6'})),
                 reply(('text', 'Counter found; generator set.'))])
    h.connect(); h.turn('what is at 29, then set the FG5010 to 1 MHz')
    assert len(h.grid.asks) == 1 and 'GPIB 6' in h.grid.asks[0][0], h.grid.asks   # query didn't ask
    q = [b for b in h.client.requests[1]['messages'][-1]['content'] if b.get('type') == 'tool_result'][0]
    assert q['content'] == 'ID TEK/DC5009,V79.1,F1.2', q
    assert (1, 6, b'FREQ 1E6\r\n') in h.grid.gpib_log, h.grid.gpib_log
    check(h)


def test_damaged_frames():
    h = Harness([reply(('tool', 'str_replace_based_edit_tool', {'command': 'view', 'path': 'A:\\CFG.C'})),
                 reply(('text', 'Read it despite the noise. ' * 20))], files={'A:\\CFG.C': CFG_C})
    h.grid.corrupt_rx_every = 7          # every 7th answer arrives damaged
    h.connect(); h.turn('read cfg.c')
    assert 'noise.' in h.text()
    assert h.grid.stats['bad_rx'] > 0 and h.grid.stats['nak'] > 0
    check(h)


def test_either_check():
    """audit3 R56: every frame of a CLAUDE carries the Fletcher sum, its HELLO too; an older one's HELLO (and all
    of gridsim's frames, here above) the CRC.  gridlink tries the sum first and answers each frame with its
    check.  A frame both pass (1 in 65,536) is taken as the sum's; if it was the CRC's, the GRiD's NAK, in the
    check it reads, has the answer sent again in that one."""
    import struct
    from gridlink import glp
    from gridlink.link import Link
    class T:
        frame_limit = 4104
        def __init__(t): t.sent = []
        def answer(t, f): t.sent.append(f)
    for i in range(1 << 16):                            # a HELLO that passes both
        pay = b'\x01\x04\xf6\x00P\x18app=x\n' + struct.pack('<H', i)
        body = struct.pack('<BBBH', glp.G_HELLO, 0, 0, len(pay)) + pay
        if glp.crc16(body) == glp.fletcher16(body): break
    else: assert False, 'no HELLO passes both checks'
    def check_of(f): return 'sum' if f[-2:] == glp.encode_check(f[1:-2], True) else \
        'crc' if f[-2:] == glp.encode_check(f[1:-2], False) else None
    t = T(); k = Link(t, lambda *a: None, log=lambda *a: None, hold=0.0)
    k.feed(bytes([glp.SYNC]) + body + glp.encode_check(body, True))
    assert len(t.sent) == 1 and check_of(t.sent[-1]) == 'sum', t.sent       # (taken as a sum's)
    nak = glp.encode(glp.G_NAK, 0, k.pi_seq, b'', fl=False)                  # an older CLAUDE: it reads the CRC
    assert glp.decode(nak, fl_first=True)[0].fl is False
    k.feed(nak)
    assert check_of(t.sent[-1]) == 'crc' and t.sent[-1][:-2] == t.sent[0][:-2] and k.stats['rx_recheck'] == 1
    k.feed(nak)                                                              # (again: the same, no recheck)
    assert t.sent[-1] == t.sent[-2] and k.stats['rx_recheck'] == 1
    k.feed(glp.encode(glp.G_NAK, 0, k.pi_seq, b'', fl=True))                 # a NAK with the sum: the sum's
    assert check_of(t.sent[-1]) == 'sum' and k.stats['rx_recheck'] == 2
    k.feed(glp.encode(glp.G_POLL, 1, k.pi_seq, b'', fl=True))
    assert check_of(t.sent[-1]) == 'sum' and k.stats['rx_fletcher'] == 3, k.stats  # (HELLO, NAK, POLL)


def test_slash_commands():
    h = Harness([])
    h.connect()
    h.turn('/model sonnet'); h.turn('/mode edits'); h.turn('/cost'); h.turn('/help')
    t = h.text()
    assert 'Model: claude-sonnet-5-5' in t and 'Permission mode: edits' in t and '/compact' in t, t
    assert b'sonnet-5-5' in h.grid.title and b'edits mode' in h.grid.title, h.grid.title
    check(h)


if __name__ == '__main__':
    import time, traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    bad = 0
    for n in names:
        t0 = time.time()
        try:
            globals()[n]()
            print('ok   %-34s %.1fs' % (n, time.time() - t0))
        except Exception:
            bad += 1
            print('FAIL %s' % n); traceback.print_exc()
    print('%d of %d passed' % (len(names) - bad, len(names)))
    sys.exit(1 if bad else 0)
