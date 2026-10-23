"""Build a Lodestone .RUN program (UI core API, src/UIAPI.INC).

    python3 mkrun.py apps/SYSTEM.ASM apps/SYSTEM.RUN

The source starts with  %include "UIAPI.INC"  and  org RUN_ORG  and ends its
.bss section with the label  run_bss_end.  Its first byte is the entry.

It is assembled twice, with RUN_ORG = 0 and RUN_ORG = 1110h, and the two
images are compared word by word:
  * a word 1110h larger in the second is an address inside the program:
    the loader adds the load offset to it;
  * a word 1110h smaller is a near call or jump into the core's jump table
    (a fixed address, so its displacement shrinks as the program moves up):
    the loader subtracts the load offset.
Anything else that differs is an error (a byte-sized address, say).

File layout (all words little-endian):
  0  'GRUN'
  4  API version the program needs: its RUN_API (RUN_API equ n after the
     include; the core refuses a program that needs more than it has), else
     UI_API when it was built
  6  image bytes          8  BSS bytes (zeroed by the loader)
  10 absolute fixups      12 relative fixups
  14 RUN_FLAGS (RUN_FLAGS equ n after the include; 0 without one): bit 0,
     RF_WIN, a window .RUN, which runs as a session beside others with
     MULTITASK=1 (M8).  The core with the switch off ignores the word
  16 the image, then the absolute fixups, then the relative ones (offsets
     into the image)
"""
import os, re, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DELTA = 0x1110


def assemble(src, org, tmp, incs):
    out = os.path.join(tmp, 'o%X.bin' % org)
    mp = os.path.join(tmp, 'o%X.map' % org)
    wrap = os.path.join(tmp, 'w%X.asm' % org)
    with open(wrap, 'w') as f:
        f.write('[map symbols %s]\n%%define RUN_ORG %d\n%%include "%s"\n' % (mp, org, os.path.abspath(src)))
    cmd = ['nasm', '-f', 'bin', '-o', out] + sum((['-i', d.rstrip('/') + '/'] for d in incs), []) + [wrap]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.stderr.write(r.stderr.replace(wrap, src)); sys.exit(1)
    syms = {}
    for line in open(mp):
        m = re.match(r"\s*([0-9A-F]+)\s+([0-9A-F]+)\s+(\S+)\s*$", line)
        if m: syms[m.group(3)] = int(m.group(2), 16)
        m = re.match(r"([0-9A-F]+)\s+(\S+)\s*$", line)
        if m: syms.setdefault(m.group(2), int(m.group(1), 16))
    return open(out, 'rb').read(), syms


def build(src, dst, incs=()):
    incs = list(incs) + [os.path.dirname(os.path.abspath(src)), os.path.join(HERE, 'src')]
    with tempfile.TemporaryDirectory() as tmp:
        a, sa = assemble(src, 0, tmp, incs)
        b, sb = assemble(src, DELTA, tmp, incs)
    if len(a) != len(b):
        raise SystemExit('%s: the two builds differ in length (%d, %d)' % (src, len(a), len(b)))
    if 'run_bss_end' not in sa:
        raise SystemExit('%s: no run_bss_end label at the end of .bss' % src)
    api = sa.get('RUN_API', sa.get('UI_API', 1))
    if api > sa.get('UI_API', 1):
        raise SystemExit('%s: RUN_API %d is newer than UIAPI.INC (%d)' % (src, api, sa.get('UI_API', 1)))
    bss = sa['run_bss_end'] - len(a)
    if bss < 0: raise SystemExit('%s: run_bss_end is inside the image' % src)
    absf, relf = [], []
    i = 0
    while i < len(a):
        if a[i] == b[i]: i += 1; continue
        if i + 1 >= len(a): raise SystemExit('%s: a byte differs at the end (%04X)' % (src, i))
        wa, wb = struct.unpack_from('<H', a, i)[0], struct.unpack_from('<H', b, i)[0]
        d = (wb - wa) & 0xFFFF
        if d == DELTA: absf.append(i)
        elif d == (-DELTA) & 0xFFFF: relf.append(i)
        else: raise SystemExit('%s: offset %04X differs by %04X: not a word address' % (src, i, d))
        i += 2
    hdr = b'GRUN' + struct.pack('<6H', api, len(a), bss, len(absf), len(relf), sa.get('RUN_FLAGS', 0))
    data = hdr + a + struct.pack('<%dH' % len(absf), *absf) + struct.pack('<%dH' % len(relf), *relf)
    open(dst, 'wb').write(data)
    return dict(image=len(a), bss=bss, abs=len(absf), rel=len(relf), size=len(data), syms=sa)


if __name__ == '__main__':
    args = sys.argv[1:]
    incs = []
    while args and args[0] == '-i':
        incs.append(args[1]); args = args[2:]
    if len(args) != 2:
        print(__doc__); sys.exit(2)
    info = build(args[0], args[1], incs)
    print('%s: %d bytes (image %d, BSS %d, %d + %d fixups)' % (args[1], info['size'], info['image'], info['bss'], info['abs'], info['rel']))
