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
    nothing.  `info`: its ATIn answers."""
    def __init__(s, speeds=(), info=None):
        s.speeds, s.info = set(speeds), info or {}
        s.lcr, s.mcr, s.ier, s.scr, s.dll, s.dlm = 0x03, 0x00, 0x00, 0x00, 0x0C, 0x00
        s.rx, s.line, s.echo, s.cmds, s.dialed = [], '', True, [], False
    def read(s, o):
        if o == 0:
            if s.lcr & 0x80: return s.dll
            return s.rx.pop(0) if s.rx else 0
        if o == 1: return s.dlm if s.lcr & 0x80 else s.ier
        if o == 2: return 0x01
        if o == 3: return s.lcr
        if o == 4: return s.mcr
        if o == 5: return 0x60 | (1 if s.rx else 0)
        if o == 6: return 0xB0 if s.speeds and s.mcr & 1 else 0x00
        return s.scr
    def write(s, o, v):
        if o == 0:
            if s.lcr & 0x80: s.dll = v
            else: s.char(v)
        elif o == 1:
            if s.lcr & 0x80: s.dlm = v
            else: s.ier = v
        elif o == 3: s.lcr = v
        elif o == 4: s.mcr = v
        elif o == 7: s.scr = v
    def char(s, c):
        if not s.speeds or (s.dlm << 8 | s.dll) not in s.speeds or s.lcr & 0x7F != 0x03: return
        if s.echo: s.rx.append(c)
        if c != 13: s.line += chr(c); return
        l, s.line = s.line.upper(), ''
        s.cmds.append(l)
        if not l.startswith('AT'): return
        a = l[2:]
        if 'D' in a.replace('ATD', ''): s.dialed = True
        if a.startswith('E1'): s.echo = True
        r = 'OK'
        if a.startswith('I'):
            n = a[1:2] or '0'
            r = s.info[n] + '\r\n\r\nOK' if n in s.info else 'ERROR'
        s.rx += list(('\r\n%s\r\n' % r).encode())

def run(name, modem):
    img = mkimg.build(os.path.join(OUT, name + '.img'), [os.path.join(GOS, 'src', 'LODE.SYS'), TOOL])
    k = ktest.KPC(img)
    k.pc.com1 = modem
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
    m = Modem({48, 96, 384}, {'0': '247', '3': 'GRiD 2400'})
    rep, same, k = run('md_331', m)
    check('Option 331 (a 2400): answers at 2400 at once; ATI0 247, ATI3 its name; Option 331 named; registers '
          'put back; never dialed; only AT, ATE1V1Q0 and ATI0-4 sent',
          'RESULT: it answered at 2400 baud: Option 331' in rep and '247' in rep and 'GRiD 2400' in rep
          and same and not m.dialed and m.cmds == ['AT', 'ATE1V1Q0', 'ATI0', 'ATI1', 'ATI2', 'ATI3', 'ATI4']
          and not k.crashed, (rep, m.cmds))
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else ''))
    sys.exit(1 if bad else 0)

if __name__ == '__main__':
    main()
