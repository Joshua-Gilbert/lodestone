"""MODEMID.COM (tools/) under Lodestone in pcemu, against COM1 (3F8h) as the
1520's internal modem might be: no UART at all, a UART with no modem behind
it, Option 330 (a Hayes 1200: answers at 1200 and 300 baud) and Option 331
(a 2400: 2400, 1200 and 300).  It must name the right one, never dial, and
put the UART's registers back as it found them.

    python3 os/tests/test_modemid.py
"""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
TOOLS = os.path.join(os.path.dirname(GOS), 'tools')
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg, fatcheck
OUT = os.environ.get('KOUT', os.path.join(__import__('tempfile').gettempdir(), 'lodestone-modem'))
os.makedirs(OUT, exist_ok=True)
TOOL = os.path.join(TOOLS, 'MODEMID.COM')

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

class Modem:
    """A 16450 at 3F8h with, optionally, a Hayes modem behind it that only
    understands the speeds in `speeds` (divisors: 48 = 2400, 96 = 1200,
    384 = 300).  At any other speed what it's sent is noise and it says
    nothing.  `info`: its ATIn answers; `slow`: the ones it takes 0.8 s
    over (the 1520's took that long over ATI1, its checksum).  As the
    1520's 16450: one received character held, the next overwriting it if
    it isn't read, each taking a character's time on the line."""
    def __init__(s, speeds=(), info=None, slow=()):
        s.speeds, s.info, s.slow = set(speeds), info or {}, set(slow)
        s.lcr, s.mcr, s.ier, s.scr, s.dll, s.dlm = 0x03, 0x00, 0x00, 0x00, 0x0C, 0x00
        s.q, s.rbr, s.full, s.overruns, s.tx_until = [], 0, False, 0, 0
        s.line, s.echo, s.cmds, s.dialed, s.pc = '', True, [], False, None
    def now(s): return s.pc.us if s.pc else 0
    def ctime(s): return 10e6 * (s.dlm << 8 | s.dll) / 115200     # (us a character)
    def send(s, data, delay=0):
        t = max([s.now()] + [q[0] for q in s.q]) + delay
        for c in data:
            t += s.ctime(); s.q.append((t, c))
    def take(s):
        while s.q and s.q[0][0] <= s.now():
            if s.full: s.overruns += 1
            s.rbr, s.full = s.q.pop(0)[1], True
    def read(s, o):
        s.take()
        if o == 0:
            if s.lcr & 0x80: return s.dll
            s.full = False; return s.rbr
        if o == 1: return s.dlm if s.lcr & 0x80 else s.ier
        if o == 2: return 0x01
        if o == 3: return s.lcr
        if o == 4: return s.mcr
        if o == 5: return (0x60 if s.now() >= s.tx_until else 0) | (1 if s.full else 0)
        if o == 6: return 0xB0 if s.speeds and s.mcr & 1 else 0x00
        return s.scr
    def write(s, o, v):
        if o == 0:
            if s.lcr & 0x80: s.dll = v
            else: s.tx_until = s.now() + s.ctime(); s.char(v)
        elif o == 1:
            if s.lcr & 0x80: s.dlm = v
            else: s.ier = v
        elif o == 3: s.lcr = v
        elif o == 4: s.mcr = v
        elif o == 7: s.scr = v
    def char(s, c):
        if not s.speeds or (s.dlm << 8 | s.dll) not in s.speeds or s.lcr & 0x7F != 0x03: return
        if s.echo: s.send([c], s.ctime())
        if c != 13: s.line += chr(c); return
        l, s.line = s.line.upper(), ''
        s.cmds.append(l)
        if not l.startswith('AT'): return
        a = l[2:]
        if 'D' in a.replace('ATD', ''): s.dialed = True
        if a.startswith('E1'): s.echo = True
        r = 'OK'
        n = a[1:2] or '0'
        if a.startswith('I'):
            r = s.info[n] + '\r\n\r\nOK' if n in s.info else 'ERROR'
        s.send(('\r\n%s\r\n' % r).encode(), 800000 if a.startswith('I') and n in s.slow else 20000)

def run(name, modem):
    img = mkimg.build(os.path.join(OUT, name + '.img'), [os.path.join(GOS, 'src', 'LODE.SYS'), TOOL])
    k = ktest.KPC(img)
    k.pc.com1 = modem
    if modem is not None: modem.pc = k.pc
    k.start()
    before = None if modem is None else (modem.lcr, modem.dll, modem.dlm, modem.ier, modem.mcr)
    k.run_file('MODEMID.COM', 60)
    rep = fatcheck.read_files(k.pc.drives[0].img).get('A:\\MODEMID.TXT', b'').decode('latin-1')
    print('   --- %s ---' % name)
    for l in rep.splitlines(): print('   ' + l)
    after = None if modem is None else (modem.lcr, modem.dll, modem.dlm, modem.ier, modem.mcr)
    return rep, before == after, k

def main():
    subprocess.run(['nasm', '-f', 'bin', '-o', TOOL, os.path.join(TOOLS, 'MODEMID.ASM')], check=True)
    rep, same, k = run('md_none', None)
    check('no UART at 3F8h (the port reads FFh): says so, and MODEMID.TXT is written',
          'RESULT: no serial port at 3F8h' in rep and not k.crashed, rep)
    m = Modem()
    rep, same, k = run('md_uart', m)
    check('a UART with nothing behind it: AT at 2400, 1200 and 300, no answer; its registers put back',
          'RESULT: COM1\'s UART is there, but nothing answered' in rep and rep.count('(nothing)') == 3
          and same and not k.crashed, rep)
    m = Modem({96, 384}, {'0': '120', '1': '017'})
    rep, same, k = run('md_330', m)
    check('Option 330 (a Hayes 1200): silent at 2400, answers at 1200; ATI0 120, ATI1 its checksum, ATI2-4 ERROR; '
          'Option 330 named; registers put back; never dialed',
          'RESULT: it answered at 1200 baud but not 2400: Option 330' in rep and '120' in rep and 'ERROR' in rep
          and same and not m.dialed and m.cmds[:2] == ['AT', 'ATE1V1Q0'] and not k.crashed, (rep, m.cmds))
    m = Modem({48, 96, 384}, {'0': '249', '1': '017', '3': '04-00027-16'}, slow={'1'})
    rep, same, k = run('md_331', m)
    body = rep[rep.index('Asking it'):] if 'Asking it' in rep else ''
    check('as the 1520 answered (2026-11-03): each echo whole though the UART holds one character (read while '
          'sending), and ATI1\'s slow checksum under ATI1, not ATI2 (each answer waits for its OK or ERROR)',
          'answer: ATE1V1Q0' in body and 'answer: ATI0' in body and 'answer: ATI1\r\n          017' in body
          and 'answer: ATI2\r\n          ERROR' in body and '04-00027-16' in body, (rep, m.overruns))
    check('Option 331 (a 2400): answers at 2400 at once; ATI0 249, ATI3 04-00027-16; Option 331 named; registers '
          'put back; never dialed; only AT, ATE1V1Q0 and ATI0-4 sent',
          'RESULT: it answered at 2400 baud: Option 331' in rep and '249' in rep
          and same and not m.dialed and m.cmds == ['AT', 'ATE1V1Q0', 'ATI0', 'ATI1', 'ATI2', 'ATI3', 'ATI4']
          and not k.crashed, (rep, m.cmds))
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else ''))
    sys.exit(1 if bad else 0)

if __name__ == '__main__':
    main()
