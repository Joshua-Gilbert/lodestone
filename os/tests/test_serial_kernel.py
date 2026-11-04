"""The kernel built with -dSERIAL (KSER.INC: the serial link on INT 60h in place of the GPIB driver, for a GRiD
without the cartridge) in pcemu: what INT 60h answers, the port taken at the link's first call and set as
SERLINK= says, no listener for the instruments' addresses, no IRQ to sleep on (pre-interrupt style), the link
off with SERLINK=OFF; and the GPIB build left as it was.  CLAUDE.COM over the same driver code, end to end, is
claude-link/tests/test_emu_serial.py's (SERLINK.COM's resident part).

    python3 tests/test_serial_kernel.py
"""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
sys.path.insert(0, GOS); sys.path.insert(0, HERE)
import ktest, mkimg
from test_modemid import Modem
OUT = os.environ.get('KOUT', os.path.join(__import__('tempfile').gettempdir(), 'lodestone-serk'))
os.makedirs(OUT, exist_ok=True)
SRC = os.path.join(GOS, 'src')

results = []
def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print('%s  %s%s' % ('ok  ' if cond else 'FAIL', name, ('  -- ' + str(detail)[:1500]) if detail and not cond else ''))

# INT 60h as CLAUDE.COM asks it, then the two UARTs' line settings:
#   Pxxxx,yyyy  00h: AX, CX         Sfxxxx  05h, the link's address 7 (f: N, or C with CF)
#   Ifxxxx  05h, address 6          Exxxx   0Eh: AX (0: no IRQ)       Bfxxxx  0Bh
#   2ll,dd  COM2's LCR and divisor  1ll,dd  COM1's
SLTEST = r"""cpu 286
org 100h
        mov     ah, 00h
        int     60h
        push    cx
        mov     dl, 'P'
        call    pc
        call    hexw
        mov     dl, ','
        call    pc
        pop     ax
        call    hexw
        mov     dl, 'S'
        mov     bl, 7
        call    spoll
        mov     dl, 'I'
        mov     bl, 6
        call    spoll
        mov     dl, 'E'
        call    pc
        mov     ax, 0E02h
        int     60h
        call    hexw
        mov     dl, 'B'
        call    pc
        mov     ah, 0Bh
        int     60h
        call    flag
        call    hexw
        mov     dx, 2F8h
        mov     bl, '2'
        call    uart
        mov     dx, 3F8h
        mov     bl, '1'
        call    uart
        mov     ax, 4C00h
        int     21h
spoll:  call    pc
        mov     ah, 05h
        int     60h
        call    flag
        jmp     hexw
flag:   pushf
        push    ax
        mov     dl, 'N'
        jnc     .n
        mov     dl, 'C'
.n:     call    pc
        pop     ax
        popf
        ret
uart:   mov     si, dx                  ; ' ' BL, LCR, ',', the divisor's low byte
        mov     dl, ' '
        call    pc
        mov     dl, bl
        call    pc
        lea     dx, [si + 3]
        in      al, dx
        mov     bh, al
        or      al, 80h
        out     dx, al
        mov     dx, si
        in      al, dx
        mov     cl, al
        lea     dx, [si + 3]
        mov     al, bh
        out     dx, al
        call    hexb
        mov     dl, ','
        call    pc
        mov     al, cl
        call    hexb
        ret
hexw:   push    ax
        mov     al, ah
        call    hexb
        pop     ax
hexb:   push    ax
        shr     al, 4
        call    .d
        pop     ax
        and     al, 0Fh
.d:     add     al, '0'
        cmp     al, '9'
        jbe     .p
        add     al, 7
.p:     mov     dl, al
pc:     push    ax
        mov     ah, 02h
        int     21h
        pop     ax
        ret
"""


def build_serial():
    """LODE.SYS / LODEMT.SYS / LODE.MAP built with -dSERIAL into OUT (os/src's own build left alone)."""
    sysf, mapf, mtf = (os.path.join(OUT, n) for n in ('LODE.SYS', 'LODE.MAP', 'LODEMT.SYS'))
    m = os.path.join(OUT, '_s.asm')
    open(m, 'w').write('[map symbols %s]\n%%include "LODE.ASM"\n' % mapf)
    subprocess.run(['nasm', '-f', 'bin', '-dSERIAL', '-i', SRC + '/', '-o', sysf, m], check=True)
    subprocess.run(['python3', os.path.join(GOS, 'mkmt.py'), sysf, mapf, mtf], check=True, stdout=subprocess.DEVNULL)
    t = os.path.join(OUT, 'SLTEST.ASM'); c = os.path.join(OUT, 'SLTEST.COM')
    open(t, 'w').write(SLTEST)
    subprocess.run(['nasm', '-f', 'bin', '-o', c, t], check=True)
    return sysf, mtf, mapf, c


def run(name, sysf, mtf, sltest, ini=None, com1=None):
    files = ['LODE.SYS=' + sysf, 'LODEMT.SYS=' + mtf, sltest]
    if ini is not None:
        p = os.path.join(OUT, name + '.INI'); open(p, 'wb').write(ini); files.append('LODE.INI=' + p)
    img = mkimg.build(os.path.join(OUT, name + '.img'), files)
    k = ktest.KPC(img)
    k.Y = ktest.Syms(MAPF)                     # (this build's symbols: the Executive's list moved)
    k.i21 = k.Y.lin('int21')
    if com1 is not None: k.pc.com1 = com1; com1.pc = k.pc
    k.start()
    out = k.run_file('SLTEST.COM', 20)
    return out.strip(), k


def main():
    gsys = open(os.path.join(SRC, 'LODE.SYS'), 'rb').read()
    global MAPF
    sysf, mtf, mapf, sltest = build_serial()
    MAPF = mapf
    sym = open(mapf).read()
    check('-dSERIAL builds: KSER.INC in (sl_isr), the GPIB driver out (no gp_cmd_begin); LODE.SYS %d bytes, '
          'the GPIB build\'s %d' % (os.path.getsize(sysf), len(gsys)),
          'sl_isr' in sym and 'gp_cmd_begin' not in sym and os.path.getsize(sysf) <= len(gsys))

    out, k = run('sk_def', sysf, mtf, sltest)
    print('   ', out)
    check('INT 60h: GRIDGPIB\'s presence (4747h), version 1.10 (CLAUDE.COM keeps the frame check)',
          out.startswith('P4747,0110'), out)
    check('05h for the link\'s address 7: nothing waiting (0); for 6, an instrument\'s: CF, no listener (2)',
          'SN0000' in out and 'IC0002' in out, out)
    check('0Eh: no IRQ (pre-interrupt style: CLAUDE.COM polls); 0Bh: nothing came', 'E0000' in out and 'BN0000' in out, out)
    check('the port taken at the first call: COM2 at 19200 baud (divisor 6), 8N1 (LCR 03)', ' 203,06' in out, out)
    check('nothing crashed', not k.crashed, k.crashed)

    m = Modem()
    out, k = run('sk_com1', sysf, mtf, sltest, ini=b'SERLINK=COM1,2400\r\n', com1=m)
    print('   ', out)
    check('SERLINK=COM1,2400: the internal modem\'s port at 2400 baud (divisor 48 = 30h), 8N1; DTR, RTS, OUT2',
          ' 103,30' in out and m.dll == 0x30 and m.lcr == 0x03 and m.mcr == 0x0B, (out, m.dll, m.lcr, m.mcr))

    out, k = run('sk_off', sysf, mtf, sltest, ini=b'SERLINK=OFF\r\n')
    print('   ', out)
    check('SERLINK=OFF: the link is off (05h: error 3), the port left alone', 'SC0003' in out and 'IC0002' in out, out)

    out, k = run('sk_fast', sysf, mtf, sltest, ini=b'SERLINK=COM2,115200\r\n')
    check('SERLINK=COM2,115200: divisor 1', ' 203,01' in out, out)

    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else ''))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
