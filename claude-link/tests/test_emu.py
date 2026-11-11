"""The real CLAUDE.COM + GRIDGPIB.COM in emulation, against the real gridlink.

    python3 tests/test_emu.py [outdir]     (screens go to outdir as PNG + TXT)
"""
import os, re, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_emu import EmuHarness
from fake_anthropic import reply
from gridlink import glp, tools

OUT = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('EMU_OUT', '')
CFG_C = b'#include <stdio.h>\r\nint rate = 1;\r\nint main(void) { return rate; }\r\n'


def shot(h, name):
    if OUT:
        os.makedirs(OUT, exist_ok=True)
        h.shot(os.path.join(OUT, name + '.png'))


def results(h, i):
    return [b for b in h.client.requests[i]['messages'][-1]['content']
            if isinstance(b, dict) and b.get('type') == 'tool_result']


def runs_of(h):
    """Each RUN's answer as gridlink read it: its outfile, the name the GRiD made the capture under."""
    runs, grun = [], h.session.grid.run
    h.session.grid.run = lambda *a, **k: runs.append(grun(*a, **k)) or runs[-1]
    return runs


def check(h, fails=0):
    assert not h.m.crash, h.m.crash
    assert not h.nano.violations, h.nano.violations
    errs = [l for l in h.log if 'Traceback' in str(l) or 'error' in str(l).lower()]
    assert not errs, errs
    assert h.var('n_fail', 2) == fails, ('link failures', h.var('n_fail', 2))
    if hasattr(h, 'stk'):                       # CLAUDE.COM's stack: under a quarter of it used
        used, size = h.claude_stack_used()
        assert used <= size // 4, ('stack', used, size)


def start(script, **kw):
    h = EmuHarness(script, **kw)
    h.boot()
    assert h.connect(), ('no connection', h.m.crash, h.screen())
    h.paint_claude_stack()                      # (check() reads how deep it went)
    return h


def test_connect_and_chat(patched=True, name='chat'):
    h = start([reply(('text', 'Hello from the Pi. The GRiD is **connected** and the link runs at '
                      'GPIB speed.\n\n- one\n- two'))], patched=patched)
    shot(h, name + '_0_welcome')
    assert h.turn('hi'), h.screen()
    t = h.screen()
    assert 'Welcome to Claude for GRiD' in t and 'Hello from the Pi.' in t, t
    assert '> hi' in t, t
    rows = t.split('\n')                        # (the bands' right-hand texts end in columns 78 and 79)
    assert 'GPIB link  ' in rows[0] and len(rows[0]) == 79 and rows[21].endswith(' F1 help') and len(rows[21]) == 80, \
        (rows[0], rows[21])
    assert h.m.clock_set is not None and h.m.rtc_set, 'clock not set'
    shot(h, name + '_1_reply')
    check(h)
    return h


def test_stock_bridge():
    test_connect_and_chat(patched=False, name='stock')


def test_read_file():
    h = start([reply(('text', "I'll read it."), ('tool', 'str_replace_based_edit_tool',
                                                 {'command': 'view', 'path': 'A:\\CFG.C'})),
               reply(('text', 'It sets `rate` to 1 and returns it.'))], files={'A:\\CFG.C': CFG_C})
    assert h.turn('what does cfg.c do?')
    res = results(h, 1)[0]
    assert '2\tint rate = 1;' in res['content'], res
    t = h.screen()
    assert 'Read(A:\\CFG.C)' in t and 'Read 3 lines' in t, t
    shot(h, 'read')
    check(h)


def test_edit_with_permission():
    seen = {}
    def on_ask(h):
        if 'shot' not in seen:
            seen['shot'] = h.screen(); shot(h, 'edit_0_ask')
        h.key(ord('y'))
    h = start([reply(('tool', 'str_replace_based_edit_tool',
                      {'command': 'str_replace', 'path': 'A:\\CFG.C',
                       'old_str': 'int rate = 1;', 'new_str': 'int rate = 5;'})),
               reply(('text', 'Done - rate is now 5.'))], files={'A:\\CFG.C': CFG_C})
    assert h.turn('set rate to 5', on_ask=on_ask)
    assert 'shot' in seen and '[Y] Yes' in seen['shot'], seen
    assert bytes(h.m.fs['A:\\CFG.C']) == CFG_C.replace(b'rate = 1', b'rate = 5'), h.m.fs['A:\\CFG.C']
    assert 'A:\\CFG.$$$' not in h.m.fs
    t = h.screen()
    assert 'Updated A:\\CFG.C with 1 addition and 1 removal' in t, t
    shot(h, 'edit_1_done')
    check(h)


def test_edit_rejected():
    h = start([reply(('tool', 'str_replace_based_edit_tool',
                      {'command': 'str_replace', 'path': 'A:\\CFG.C',
                       'old_str': 'int rate = 1;', 'new_str': 'int rate = 5;'})),
               reply(('text', 'OK, I will wait.'))], files={'A:\\CFG.C': CFG_C}, answer='n')
    assert h.turn('set rate to 5')
    assert bytes(h.m.fs['A:\\CFG.C']) == CFG_C
    res = results(h, 1)[0]
    assert res.get('is_error') and res['content'] == tools.REJECTED, res
    check(h)


def test_run_program_with_keys():
    # (keys after the {SNAP}, and TESTKEY's "bye" at Esc: the screen returned is the {SNAP}'s, not the exit's)
    h = start([reply(('tool', 'grid_command', {'command': 'TESTKEY', 'capture': False,
                                               'keys': 'hello{WAIT 0.2}{SNAP}abc{ESC}'})),
               reply(('text', 'TESTKEY read eight keys.'))], mode='auto')
    assert h.turn('run testkey', sim_s=30)
    res = results(h, 1)[0]
    text = str(res['content'])
    assert 'Exit code: 8' in text, text
    assert 'TESTKEY ready: hello' in text, text
    assert 'helloabc' not in text and 'bye' not in text, text
    assert any('[EXEC A:\\TESTKEY.COM' in l for l in h.m.log), h.m.log
    assert h.m.mode() == 0x40
    shot(h, 'run')
    check(h)


def test_run_exe_found():
    """A first word without a dot is looked for as NAME.COM, then NAME.EXE (TESTKEY's bytes as KEYS.EXE:
    no MZ, so DOS loads it as a .COM), and that is run directly."""
    import grid_emu
    h = start([reply(('tool', 'grid_command', {'command': 'KEYS', 'capture': False, 'keys': 'ab{ESC}'})),
               reply(('text', 'Done.'))], mode='auto', files={'A:\\KEYS.EXE': open(grid_emu.TESTKEY_COM, 'rb').read()})
    assert h.turn('run keys', sim_s=30)
    text = str(results(h, 1)[0]['content'])
    assert 'Exit code: 2' in text and any('[EXEC A:\\KEYS.EXE' in str(l) for l in h.m.log) \
        and not any('/C KEYS' in str(l) for l in h.m.log), (text, h.m.log)        # (not through the shell)
    check(h)


def test_dos_command_capture():
    h = start([reply(('tool', 'grid_command', {'command': 'DIR'})),
               reply(('text', 'There are a few files.'))], mode='auto', files={'A:\\CFG.C': CFG_C})
    assert h.turn('what is on the disk?')
    res = results(h, 1)[0]
    text = str(res['content'])
    assert 'CFG' in text and 'CLAUDE' in text, text
    assert 'A:\\CLAUDE.OUT' not in h.m.fs            # read, then deleted
    check(h)


def test_capture_whole_line():
    """A capture takes every command of the line (CLAUDE.COM's stdout is the output file, the shell's
    then), and a "> FILE" in the line takes its own command's output: the shell's tail is the line as
    given, with no redirect added.  (It was " >CLAUDE.OUT" at the end: A && B gave B's output alone,
    and a > FILE of the line was replaced by it, so FILE was never written.)"""
    emu = EmuHarness.__name__ == 'EmuHarness'
    h = start([reply(('tool', 'grid_command', {'command': 'ECHO one && ECHO two'})),
               reply(('tool', 'grid_command', {'command': 'DIR > A:\\D.TXT && ECHO two'})),
               reply(('tool', 'grid_command', {'command': 'DIR > A:\\D2.TXT'})),
               reply(('text', 'Done.'))], mode='auto', files={'A:\\CFG.C': CFG_C})
    jft = bytes(h.m.rd(h.claude_psp, 0x18, 20))     # (CLAUDE's handles: as they were after each RUN)
    assert h.turn('echo twice, then list the disk to files')
    one, two, three = (str(results(h, i)[0]['content']) for i in (1, 2, 3))
    assert 'one' in one and 'two' in one, one
    assert any(l.endswith(' /C ECHO one && ECHO two]') for l in map(str, h.m.log)), h.m.log
    assert 'two' in two and 'CFG' not in two, two
    d = bytes(h.m.fs.get('A:\\D.TXT', b''))
    assert b'CFG' in d and b'two' not in d, d
    assert 'CFG' not in three and '(no output)' in three, three      # (1.17: the line's > replaced by its own)
    assert b'CFG' in bytes(h.m.fs.get('A:\\D2.TXT', b'')), sorted(h.m.fs)
    assert 'A:\\CLAUDE.OUT' not in h.m.fs
    assert ''.join(h.m.tty).count('Output goes to Claude, not this screen') == 3, ''.join(h.m.tty)[-400:]
    if emu: assert not h.m.handles, h.m.handles               # (handle 1 the console again, the dup closed)
    else: assert bytes(h.m.rd(h.claude_psp, 0x18, 20)) == jft, (jft, h.m.rd(h.claude_psp, 0x18, 20))
    check(h)


def test_capture_file_held():
    """CLAUDE.OUT held open (by a program an earlier RUN left resident, or a task START began): the
    capture is made as CLAUDE.OU1 beside it, read and deleted there, instead of every RUN failing with 5.
    (The stand-in DOS only: it holds the file with a handle of its own.)"""
    if EmuHarness.__name__ != 'EmuHarness': return
    h = start([reply(('tool', 'grid_command', {'command': 'DIR'})), reply(('text', 'Done.'))], mode='auto',
              files={'A:\\CFG.C': CFG_C, 'A:\\CLAUDE.OUT': b'old'})
    h.m.handles[19] = {'p': 'A:\\CLAUDE.OUT', 'pos': 0}
    runs = runs_of(h)
    assert h.turn('what is on the disk?')
    res = results(h, 1)[0]
    assert runs and runs[-1]['outfile'] == 'A:\\CLAUDE.OU1', runs
    assert 'CFG' in str(res['content']) and not res.get('is_error'), res
    assert 'A:\\CLAUDE.OU1' not in h.m.fs and bytes(h.m.fs['A:\\CLAUDE.OUT']) == b'old', sorted(h.m.fs)
    del h.m.handles[19]
    check(h)


def test_run_defaults():
    """COMSPEC, TEMP and TMP not in CLAUDE's environment: the shell is A:\\COMMAND.COM and the capture
    goes to the current drive's root.  (The stand-in DOS: started in A:\\WORK, which the HELLO's cwd says.)"""
    emu = EmuHarness.__name__ == 'EmuHarness'   # (not test_claude_kernel.py's Lodestone kernel)
    h = EmuHarness([reply(('tool', 'grid_command', {'command': 'DIR'})), reply(('text', 'Done.'))], mode='auto',
                   files={'A:\\WORK\\CFG.C': CFG_C} if emu else {})
    if emu: h.m.dirs.add('A:\\WORK\\'); h.m.cwd = 'A:\\WORK\\'
    h.boot()
    env = h.m.u16(h.claude_psp, 0x2C)
    raw = bytearray(h.m.rd(env, 0, 512))
    for v in (b'\0COMSPEC=', b'\0TEMP=', b'\0TMP='):
        i = (b'\0' + raw).find(v)
        if i >= 0: raw[i] = ord('X')
    h.m.wr(env, 0, bytes(raw))
    assert h.connect(), ('no connection', h.m.crash)
    assert not emu or h.session.hello.get('cwd') == 'A:\\WORK', h.session.hello
    runs = runs_of(h)
    assert h.turn('what is on the disk?')
    assert not emu or (runs and runs[-1]['outfile'] == 'A:\\CLAUDE.OUT'), runs   # (the root, not the cwd;
                                                    #  the kernel's disk has no A:\COMMAND.COM: the EXEC fails)
    assert any('[EXEC A:\\COMMAND.COM /C DIR]' in str(l) for l in h.m.log), h.m.log
    text = str(results(h, 1)[0]['content'])
    assert not emu or ('CFG' in text and 'A:\\CLAUDE.OUT' not in h.m.fs), text
    check(h)


def test_run_tmp_only():
    """TMP in CLAUDE's environment and not TEMP: the capture goes there (A:\\WORK under the stand-in DOS,
    a '\\' put between; A:\\ under the kernel, which ends in one)."""
    emu = EmuHarness.__name__ == 'EmuHarness'
    h = EmuHarness([reply(('tool', 'grid_command', {'command': 'DIR'})), reply(('text', 'Done.'))], mode='auto',
                   files={'A:\\CFG.C': CFG_C})
    if emu: h.m.dirs.add('A:\\WORK\\')
    h.boot()
    env = h.m.u16(h.claude_psp, 0x2C)
    raw = bytes(h.m.rd(env, 0, 1024))
    end = raw.find(b'\0\0')                     # (the variables; then a count word and the program's name)
    keep = [v for v in raw[:end].split(b'\0') if v.upper().startswith(b'COMSPEC=')]     # (and TMP: no more room)
    tmp = b'A:\\WORK' if emu else b'A:\\'
    new = b'\0'.join(keep + [b'TMP=' + tmp]) + b'\0\0' + raw[end + 2:raw.index(b'\0', end + 4) + 1]
    paras = h.m.block(env)[1] if emu else h.m.u16(env - 1, 3)
    assert len(new) <= paras * 16, (len(new), paras)                # (its block holds it)
    h.m.wr(env, 0, new)
    assert h.connect(), ('no connection', h.m.crash)
    runs = runs_of(h)
    assert h.turn('what is on the disk?')
    out = tmp.decode() + ('\\' if emu else '') + 'CLAUDE.OUT'
    assert runs and runs[-1]['outfile'] == out, (out, runs)
    assert any('/C DIR]' in str(l) for l in h.m.log), h.m.log
    text = str(results(h, 1)[0]['content'])
    assert 'CFG' in text and out.upper() not in h.m.fs, text
    check(h)


def test_run_capture_unwritable():
    """The capture file made before the program: TEMP naming a directory that is not there answers
    'path not found', and nothing runs (the shell's redirection would have failed the command, or from a
    protected floppy waited for a key)."""
    h = EmuHarness([reply(('tool', 'grid_command', {'command': 'DIR'})), reply(('text', 'Done.'))], mode='auto',
                   files={'A:\\CFG.C': CFG_C})
    h.boot()
    env = h.m.u16(h.claude_psp, 0x2C)
    raw = bytes(h.m.rd(env, 0, 1024))
    end = raw.find(b'\0\0')
    keep = [v for v in raw[:end].split(b'\0') if v.upper().startswith(b'COMSPEC=')]
    new = b'\0'.join(keep + [b'TEMP=A:\\NOPE']) + b'\0\0' + raw[end + 2:raw.index(b'\0', end + 4) + 1]
    h.m.wr(env, 0, new)
    assert h.connect(), ('no connection', h.m.crash)
    assert h.turn('what is on the disk?')
    res = results(h, 1)[0]
    assert res.get('is_error') and 'path not found' in str(res['content']), res
    assert not any('/C DIR' in str(l) for l in h.m.log), h.m.log      # (the shell never started for it)
    check(h)


def test_gpib_query():
    h = start([reply(('tool', 'gpib', {'action': 'query', 'address': 29, 'command': 'ID?'})),
               reply(('tool', 'gpib', {'action': 'write', 'address': 6, 'command': 'FREQ 1E6'})),
               reply(('text', 'The DC5009 counter is at 29; the FG5010 is set.'))])
    assert h.turn('what is at 29, then set the FG5010 to 1 MHz', sim_s=30)
    q = results(h, 1)[0]
    assert q['content'] == 'ID TEK/DC5009,V79.1,F2.1', q
    w = results(h, 2)[0]
    assert not w.get('is_error'), w
    shot(h, 'gpib')
    check(h)


def test_big_file_both_ways():
    big = ''.join('line %05d: the quick brown fox jumps over the lazy dog\n' % i for i in range(400))
    h = start([reply(('tool', 'str_replace_based_edit_tool',
                      {'command': 'create', 'path': 'A:\\BIG.TXT', 'file_text': big})),
               reply(('tool', 'str_replace_based_edit_tool', {'command': 'view', 'path': 'A:\\BIG.TXT',
                                                               'view_range': [395, 400]})),
               reply(('text', 'Written and checked.'))], mode='edits')
    t0 = h.m.us
    assert h.turn('write a big file', sim_s=120)
    assert bytes(h.m.fs['A:\\BIG.TXT']) == big.replace('\n', '\r\n').encode()
    res = results(h, 2)[0]
    assert 'line 00399' in res['content'], res['content'][-200:]
    h.big_s = (h.m.us - t0) / 1e6
    check(h)
    return h


def test_damaged_frames():
    h = start([reply(('tool', 'str_replace_based_edit_tool', {'command': 'view', 'path': 'A:\\CFG.C'})),
               reply(('text', 'Read it despite the noise. ' * 20))], files={'A:\\CFG.C': CFG_C})
    h.transport.corrupt_every = 5
    assert h.turn('read cfg.c', sim_s=60)
    assert 'noise.' in h.screen()
    assert h.var('n_bad', 2) > 0
    assert h.link.stats['rx_nak'] > 0, h.link.stats         # (the GRiD's NAKs reach the Pi as NAKs)
    h.transport.corrupt_every = 0
    assert h.m.crash is None


def test_damaged_answers_fail_the_link():
    # A NAK keeps link_wait's ~2 s from the frame the answer is for, so a Pi whose every answer comes
    # damaged fails the link (a HELLO again) within about 2 s, not NAK after NAK for ever; good answers again,
    # it goes on
    h = start([reply(('text', 'Back after the noise.'))])
    assert h.run_until(h.idle, 20), h.screen()
    f0, b0 = h.var('n_fail', 2), h.var('n_bad', 2)
    h.transport.corrupt_every = 1
    t0 = h.m.us
    failed = h.run_until(lambda: h.var('n_fail', 2) > f0, 6)
    dt, nb = (h.m.us - t0) / 1e6, h.var('n_bad', 2) - b0
    h.transport.corrupt_every = 0
    assert failed and nb > 3 and dt < 5, (failed, dt, nb, h.link.stats)
    assert h.run_until(lambda: 'Reconnected' in h.screen(), 20) and h.run_until(h.idle, 20), h.screen()
    assert h.turn('hello again', sim_s=60), h.screen()
    assert 'noise.' in h.screen(), h.screen()
    check(h, fails=1)                               # (the one it was meant to have)


def test_help_and_slash():
    h = start([])
    h.key(0x3B00)                          # F1
    h.run_until(lambda: h.var('help_open'), 2)
    shot(h, 'help')
    assert 'keys' in h.screen() and 'CODE-Q' in h.screen(), h.screen()
    h.key(0x011B)
    h.run_until(lambda: not h.var('help_open'), 2)
    assert h.turn('/model sonnet') and h.turn('/cost')
    t = h.screen()
    assert 'Model: claude-sonnet-5-5' in t, t
    assert 'sonnet-5-5' in t.split('\n')[0], t.split('\n')[0]
    check(h)



def test_interrupt_and_continue():
    long = ' '.join('word%03d' % i for i in range(400))
    h = start([reply(('text', long), delay=0.01), reply(('text', 'Carrying on.'))])
    h.type('write a lot')
    assert h.run_until(lambda: h.var('c_count', 2) > 8, 20), h.screen()
    h.key(0x011B)                                   # Esc
    assert h.run_until(h.idle, 20), h.screen()
    t = h.screen()
    assert 'Interrupted by user' in t, t
    shot(h, 'interrupt')
    assert h.turn('go on')
    msgs = h.client.requests[-1]['messages']
    assert any('interrupted' in str(m['content']).lower() for m in msgs), msgs
    assert 'Carrying on.' in h.screen()
    check(h)


def test_queued_prompt():
    h = start([reply(('text', 'First answer, slowly streamed. ' * 6), delay=0.01),
               reply(('text', 'Second answer.'))])
    h.type('first')
    assert h.run_until(lambda: h.var('busy') and h.var('c_count', 2) > 6, 20)
    h.type('second')
    assert h.run_until(lambda: h.var('queued'), 5), h.screen()
    # (the flag is set just before the status line is drawn: give the drawing a moment)
    assert h.run_until(lambda: 'Prompt queued; it goes when Claude finishes (' in h.screen().split('\n')[21], 0.5), \
        h.screen()
    assert h.run_until(lambda: not h.var('queued') and h.idle(), 30), h.screen()
    t = h.screen()
    assert '> second' in t and 'Second answer.' in t, t
    check(h)


def test_chat_scroll():
    """With the window full and at its end, a TEXT frame's new lines
    scroll rows 1-20 and draw only the lines they reach, not all 20 rows
    (1,600 cells) a frame; the screen then is what a whole redraw draws."""
    from unicorn import UC_HOOK_CODE
    text = '\n'.join('Line %03d of a long answer, streamed.' % i for i in range(1, 121))
    h = start([reply(('text', text))])
    at, n = h.claude_psp * 16 + h.sym['cell'], [0]
    def hk(uc, a, sz, ud):
        if a == at: n[0] += 1
    h.m.mu.hook_add(UC_HOOK_CODE, hk, None, at, at); h.m.mu.ctl_flush_tb()
    assert h.turn('count to 120', sim_s=60)
    h.settle()
    cells = n[0]
    v0 = h.m.rd(0xB800, 0, 0x8000)
    t = h.screen().split('\n')
    assert 'Line 120' in '\n'.join(t[1:21]), t
    h.key(0x7500)                                  # Ctrl-End: draw_conv, the whole window
    h.settle()
    v1 = h.m.rd(0xB800, 0, 0x8000)
    rows = lambda v: b''.join(v[b * 0x2000 + 320: b * 0x2000 + 21 * 320] for b in range(4))
    assert rows(v0) == rows(v1), 'rows 1-20 differ from a whole redraw'
    # (a whole window a frame, as before 2026-11-03: 37,533 cells here, the frames ~5 lines each)
    assert cells < 24000, cells
    print('   %d cells drawn for 120 lines (%.0f a line)' % (cells, cells / 120))
    check(h)


def test_long_answer_scrollback():
    text = '\n'.join('Line %03d of a long answer.' % i for i in range(1, 201))
    h = start([reply(('text', text))])
    assert h.turn('count to 200', sim_s=60)
    assert h.var('c_count', 2) == 160                # the ring is full and wrapped
    t = h.screen().split('\n')
    assert 'Line 200' in '\n'.join(t[1:21]), t
    h.key(0x4900); h.key(0x4900)                   # PgUp twice
    h.settle()
    t = h.screen().split('\n')
    nums = [int(l.split()[1]) for l in t[1:21] if l.strip().startswith('Line')]
    assert nums and nums == list(range(nums[0], nums[0] + len(nums))) and nums[-1] < 200, nums
    assert 'PgDn' in t[21], t[21]
    shot(h, 'scrollback')
    h.key(0x7500)                                  # Ctrl-End
    h.settle()
    assert 'Line 200' in h.screen()
    check(h)


def test_long_prompt_and_history():
    p = 'please look at ' + ' '.join('file%02d.c' % i for i in range(20))
    h = start([reply(('text', 'Looked.')), reply(('text', 'Again.'))])
    h.type(p, enter=False)
    h.settle()
    shot(h, 'long_prompt')
    assert h.var('inlen', 2) == len(p)
    h.key(0x1C0D)
    assert h.run_until(lambda: h.var('busy'), 5)
    assert h.run_until(h.idle, 20)
    assert h.client.requests[0]['messages'][-1]['content'][-1]['text'] == p
    h.key(0x4800)                                  # Up: the last prompt again
    h.settle()
    assert h.var('inlen', 2) == len(p)
    check(h)


def test_link_loss_and_reconnect():
    h = start([reply(('text', 'Back again.'))])
    real = h.transport.answer
    h.transport.answer = lambda f: None            # the Pi goes quiet
    assert h.run_until(lambda: not h.var('connected'), 10), 'no link loss noticed'
    h.settle()
    assert 'Link to the Pi lost, reconnecting' in h.screen().split('\n')[21], h.screen()
    shot(h, 'link_lost')
    # link_reset clears the link's state (TERMLINK_RESET_VARS, first to last): set it while a HELLO
    # waits for no answer, and look at it when the next reset builds its HELLO
    from unicorn import UC_HOOK_CODE
    LR = ('g_seq', 'p_ack', 'have_pi', 'nak_pending', 'resend', 'rq_type', 'rq_len', 'keyn', 'keys_q', 'rep_q')
    base = h.claude_psp * 16
    assert h.run_until(lambda: h.var('lstate') == 2, 5), h.var('lstate')
    for n in LR: h.m.mu.mem_write(base + h.sym[n], b'\x01')
    seen = []
    at = base + h.sym['build_hello']
    hk = h.m.mu.hook_add(UC_HOOK_CODE, lambda uc, a, sz, ud: seen or seen.append(
        [uc.mem_read(base + h.sym[n], 1)[0] for n in LR]), None, at, at)
    h.m.mu.ctl_remove_cache(at, at + 1)            # (unicorn hooks only code it translates afresh)
    assert h.run_until(lambda: seen, 5), 'no link reset'
    h.m.mu.hook_del(hk)
    assert seen[0] == [0] * len(LR), list(zip(LR, seen[0]))
    h.transport.answer = real
    assert h.run_until(h.idle, 15), h.screen()
    assert h.var('n_fail', 2) >= 1
    assert h.turn('are you there?')
    assert 'Back again.' in h.screen()
    assert not h.m.crash and not h.nano.violations


def test_quit_to_dos():
    h = start([])
    h.key(0x1000)                                  # CODE-Q (Alt-Q)
    h.run_until(lambda: h.m.stopped, 5)
    assert h.m.stopped and h.m.exit_code == 0, (h.m.stopped, h.m.exit_code, h.m.crash)
    assert h.m.mode() == 3
    for n in (0x23, 0x24, 0x16):                   # DOS vectors back as they were
        off, seg = struct.unpack('<HH', h.m.rd(0, n * 4, 4))
        assert (seg, off) == (0xF000, n * 8), (hex(n), hex(seg), hex(off))
    assert 'Claude for GRiD ended.' in ''.join(h.m.tty)


def test_claude_md_and_info():
    md = b'# This GRiD\r\nTM5000G lives in A:\\TM5000.\r\n'
    h = start([reply(('text', 'Noted.'))], files={'A:\\CLAUDE.MD': md})
    assert h.turn('hi')
    system = str(h.client.requests[0].get('system'))
    assert 'TM5000G lives in' in system, system[:500]
    assert 'gpib=GRIDGPIB 1.10 on INT 60h' in system or 'GRIDGPIB' in system, system[:800]
    check(h)


def test_gpib_scan():
    h = start([reply(('tool', 'gpib', {'action': 'scan'})), reply(('text', 'Found them.'))])
    assert h.turn('what is on the bus?', sim_s=60)
    r = results(h, 1)[0]
    text = str(r['content'])
    for a in ('6', '14', '29'):
        assert a in text, text
    check(h)


def test_gridgpib_unload():
    """GRIDGPIB /U with the driver resident on its own (GRiD MS-DOS): INT 60h
    back as it was before the install, the driver's memory freed."""
    import grid_emu as G
    m = G.Machine()
    m.fs['A:\\GRIDGPIB.COM'] = bytearray(open(G.GRIDGPIB_COM, 'rb').read())
    m.mu.mem_write(0x70010, b'\xCF'); m.mu.mem_write(0x60 * 4, struct.pack('<HH', 0x0010, 0x7000))   # an IRET before
    vec0, blocks0 = m.rd(0, 0x60 * 4, 4), sorted(map(tuple, m.blocks))
    m.run_program('A:\\GRIDGPIB.COM', limit_us=5e6)
    assert m.rd(0, 0x60 * 4, 4) != vec0, 'not installed'
    m.tty.clear()
    out = m.run_program('A:\\GRIDGPIB.COM', '/U', limit_us=5e6)
    assert 'Unloaded' in out, out
    assert m.rd(0, 0x60 * 4, 4) == vec0, (m.rd(0, 0x60 * 4, 4).hex(), vec0.hex())
    assert sorted(map(tuple, m.blocks)) == blocks0, (m.blocks, blocks0)


def test_missing_program():
    h = start([reply(('tool', 'grid_command', {'command': 'NOSUCH /X'})),
               reply(('text', 'It does not exist.'))], mode='auto')
    assert h.turn('run nosuch')
    r = results(h, 1)[0]
    assert 'Bad command' in str(r['content']), r
    check(h)


def test_run_directory_name():
    """A program run directly (no capture): a first word that is a directory's name, ending .COM or
    .EXE (a name without a dot is looked for as both), is found by GET ATTRIBUTES, so EXEC fails and its
    DOS error is the answer; a dotted directory's name with another extension, and one that is nothing's,
    go to the shell (COMSPEC /C), which runs."""
    h = start([reply(('tool', 'grid_files', {'action': 'mkdir', 'path': 'A:\\SUB.COM'})),
               reply(('tool', 'grid_files', {'action': 'mkdir', 'path': 'A:\\SUB.D'})),
               reply(('tool', 'grid_command', {'command': 'SUB.COM', 'capture': False})),
               reply(('tool', 'grid_command', {'command': 'SUB.D', 'capture': False})),
               reply(('tool', 'grid_command', {'command': 'NOSUCH', 'capture': False})),
               reply(('text', 'Done.'))], mode='auto')
    g, replies = h.session.grid, []
    on_reply = g.on_reply
    g.on_reply = lambda b: (replies.append(bytes(b)), on_reply(b))
    assert h.turn('run them', sim_s=60)
    sub, subd, nosuch = replies[-3:]
    assert len(sub) == 2 and sub[1] in (2, 3, 5) and results(h, 3)[0].get('is_error'), (sub, results(h, 3))
    assert not any('/C SUB.COM' in str(l) for l in h.m.log), h.m.log
    assert subd[1] == 0 and any('/C SUB.D' in str(l) for l in h.m.log), (subd, h.m.log)
    assert nosuch[1] == 0 and any('/C NOSUCH' in str(l) for l in h.m.log), (nosuch, h.m.log)
    check(h)


def test_run_dotted_names():
    """A program run directly (no capture), named with its extension: only a .COM or .EXE (any case) is
    EXECed itself; FOO.BAT and README.TXT go to the shell (COMSPEC /C), not loaded as a program."""
    import grid_emu
    tk = open(grid_emu.TESTKEY_COM, 'rb').read()
    G = lambda c, keys='': reply(('tool', 'grid_command', {'command': c, 'capture': False, 'keys': keys}))
    emu = EmuHarness.__name__ == 'EmuHarness'   # (a dot in a directory's name: the stand-in DOS's subdirectory)
    files = {'A:\\FOO.BAT': b'@echo off\r\n', 'A:\\README.TXT': b'Read me.\r\n', 'A:\\KEYS.EXE': tk}
    if emu: files['A:\\SUB.D\\KEYS.COM'] = tk
    h = start([G('FOO.BAT'), G('README.TXT'), G('keys.exe', 'ab{ESC}'), G('TESTKEY.COM', 'a{ESC}')]
              + ([G('sub.d\\keys', 'b{ESC}')] if emu else []) + [reply(('text', 'Done.'))], mode='auto', files=files)
    if emu: h.m.dirs.add('A:\\SUB.D\\')
    assert h.turn('run them', sim_s=90)
    log = [str(l) for l in h.m.log]
    assert not emu or any(l.startswith('[EXEC A:\\SUB.D\\KEYS.COM') for l in log), log
    assert any('/C FOO.BAT' in l for l in log) and any('/C README.TXT' in l for l in log), log
    assert not any(l.startswith('[EXEC A:\\FOO.BAT') or l.startswith('[EXEC A:\\README.TXT') for l in log), log
    assert any(l.startswith('[EXEC A:\\KEYS.EXE') for l in log) and 'Exit code: 2' in str(results(h, 3)[0]['content']), \
        (log, results(h, 3))
    assert any(l.startswith('[EXEC A:\\TESTKEY.COM') for l in log) and not any('/C KEYS' in l.upper() for l in log), log
    check(h)


def dta_dt(h):
    """The emulator's clock as DIR and STAT give it ('2026-10-21 12:21'),
    or None under the Lodestone kernel (test_claude_kernel.py)."""
    if not hasattr(h.m, 'dos_dt'): return None
    t, d = h.m.dos_dt()
    return glp.date_text(d) + ' ' + glp.time_text(t)


def test_files_list_info_errors():
    """DIR and STAT copy the find's attribute, time, date, size and name;
    a STAT that fails and a WRITE whose create fails answer the DOS error."""
    h = start([reply(('tool', 'grid_files', {'action': 'list', 'path': 'A:\\'})),
               reply(('tool', 'grid_files', {'action': 'info', 'path': 'A:\\CFG.C'})),
               reply(('tool', 'str_replace_based_edit_tool', {'command': 'view', 'path': 'A:\\NOSUCH.C'})),
               reply(('tool', 'str_replace_based_edit_tool',
                      {'command': 'create', 'path': 'A:\\NODIR\\X.C', 'file_text': 'x\n'})),
               reply(('tool', 'grid_files', {'action': 'mkdir', 'path': 'A:\\SUB'})),
               reply(('tool', 'grid_files', {'action': 'list', 'path': 'A:\\SUB'})),
               reply(('text', 'Done.'))], files={'A:\\CFG.C': CFG_C}, mode='auto')
    g, replies = h.session.grid, []
    on_reply = g.on_reply
    g.on_reply = lambda b: (replies.append(bytes(b)), on_reply(b))
    dts = {dta_dt(h)}
    assert h.turn('look around', sim_s=60)
    dts.add(dta_dt(h))
    # the failures: STAT of A:\NOSUCH.C (FIND FIRST's no more files), then of A:\NODIR\X.C and the
    # create of A:\NODIR\X.$$$ (path not found); each just the id and the status
    assert [r[1:] for r in replies if r[1]] == [b'\x12', b'\x03', b'\x03'], replies
    lst = results(h, 1)[0]['content'].split('\n')
    cfg = [l for l in lst if l.startswith('CFG.C ')]
    assert len(cfg) == 1 and cfg[0].split()[1] == str(len(CFG_C)), lst
    when = ' '.join(cfg[0].split()[2:])
    assert re.fullmatch(r'20[2-9]\d-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01]) ([01]\d|2[0-3]):[0-5]\d', when), lst
    if None not in dts: assert when in dts, (lst, dts)                      # (grid_emu's clock)
    ents = lst[1:-1]                                                        # (each entry 22 bytes, in step)
    assert len(ents) >= 3 and all(re.fullmatch(r'[A-Z0-9_$~-]{1,8}(\.[A-Z0-9_$~-]{1,3})? +(\d+|<DIR>)  \S+ \S+', l)
                                  for l in ents) and any(l.startswith('CLAUDE.COM ') for l in ents), lst
    info = results(h, 2)[0]['content']
    attr = '20h' if None not in dts else info[-3:]                          # (grid_emu: archive)
    assert info == 'A:\\CFG.C: %d bytes, modified %s, attributes %s' % (len(CFG_C), when, attr), info
    r = results(h, 3)[0]
    assert r.get('is_error') and r['content'] == 'Error: the path A:\\NOSUCH.C does not exist.', r
    r = results(h, 4)[0]
    assert r.get('is_error') and r['content'] == 'Error on the GRiD: path not found', r
    r = results(h, 6)[0]                        # (an empty subject: grid_emu's has no . or .., its FIND FIRST 18)
    assert not r.get('is_error') and r['content'].startswith('Directory of A:\\SUB\\\n(empty)\n'), r
    check(h)


def test_prompt_keys():
    """The prompt emptied (Esc while idle, Enter, Down past the newest
    prompt), Ctrl-L's redraw, /clear's CLEAR, and STATUS and TITLE cut at
    70 characters."""
    from gridlink import glp
    h = start([reply(('text', 'One.')), reply(('text', 'Two.'))])
    def line(): return (h.var('inlen', 2), h.var('incur', 2), h.screen().split('\n')[23].rstrip())
    h.type('abc', enter=False); h.settle()
    assert line() == (3, 3, '> abc'), line()
    h.key(0x011B); h.settle()                                  # Esc, Claude not working: emptied
    assert line() == (0, 0, '>'), line()
    assert h.turn('one') and line() == (0, 0, '>'), line()     # Enter empties it too
    assert h.turn('two') and line() == (0, 0, '>'), line()
    h.type('xyz', enter=False); h.settle()
    h.key(0x4800); h.settle()                                  # Up
    assert line() == (3, 3, '> two'), line()
    h.key(0x4800); h.settle()
    assert line() == (3, 3, '> one'), line()
    h.key(0x5000); h.settle()                                  # Down
    assert line() == (3, 3, '> two'), line()
    h.key(0x5000); h.settle()                                  # past the newest: empty
    assert line() == (0, 0, '>'), line()
    def noclock(): s = h.screen().split('\n'); return [s[0][:70]] + s[1:]     # (its minute may turn)
    t = noclock()
    h.m.wr(0xB800, 0, bytes(0x8000))                           # Ctrl-L draws it all again
    h.key(0x260C); h.settle()
    assert noclock() == t, h.screen()
    def text(name): return bytes(h.m.mu.mem_read(h.claude_psp * 16 + h.sym[name], 72))
    h.link.send(glp.P_STATUS, b'S' * 69 + b'+tail')
    h.run_until(lambda: text('status_text').startswith(b'S' * 69), 5); h.settle()
    assert text('status_text') == b'S' * 69 + b'+\0' + text('status_text')[71:], text('status_text')
    assert h.screen().split('\n')[21].startswith('S' * 69 + '+ '), h.screen().split('\n')[21]
    h.link.send(glp.P_TITLE, b'T' * 69 + b'+tail')
    h.run_until(lambda: text('title_text').startswith(b'T' * 69), 5); h.settle()
    assert text('title_text') == b'T' * 69 + b'+\0' + text('title_text')[71:], text('title_text')
    assert h.screen().split('\n')[0].startswith(' ' + 'T' * 56 + ' '), h.screen().split('\n')[0]
    n = h.var('c_count', 2)
    assert h.turn('/clear') and h.var('c_count', 2) < 4 < n, (n, h.var('c_count', 2), h.screen())
    assert 'New conversation.' in h.screen() and 'Two.' not in h.screen(), h.screen()
    v = h.m.rd(0xB800, 0, 0x8000)                              # the rows under it: blank cells, attribute 0
    sp = bytes(h.m.rd(h.claude_psp, h.sym['font'], 16))       # (the space's glyph)
    bad = [(r, c) for r in range(1 + h.var('c_count', 2), 21) for c in range(80)
           if bytes(v[(i & 3) * 0x2000 + (r * 4 + (i >> 2)) * 80 + c] for i in range(16)) != sp]
    assert not bad, bad[:5]
    check(h)


if __name__ == '__main__':
    import traceback
    names = [n for n in sorted(globals()) if n.startswith('test_')]
    if len(sys.argv) > 2: names = [n for n in names if any(a in n for a in sys.argv[2:])]
    bad = 0
    for n in names:
        t0 = time.time()
        try:
            r = globals()[n]()
            extra = ''
            if r is not None and hasattr(r, 'big_s'): extra = '  (22.8 KB each way in %.2f s simulated)' % r.big_s
            print('ok   %-30s %5.1fs%s' % (n, time.time() - t0, extra))
        except Exception:
            bad += 1
            print('FAIL %s' % n); traceback.print_exc()
    print('%d of %d passed' % (len(names) - bad, len(names)))
    sys.exit(1 if bad else 0)
