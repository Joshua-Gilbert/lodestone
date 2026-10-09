"""A bootable FreeDOS floppy image for the emulator: FreeDOS's FAT12 boot
sector (with the floppy's BPB), KERNEL.SYS, FreeCOM's COMMAND.COM, an
optional FDCONFIG.SYS and AUTOEXEC.BAT, then the given files.  The FreeDOS
files are in bench/freedos (kernel 2.45 built for the 8086, FAT12/16;
FreeCOM; both GPL, built from github.com/FDOS/kernel and FDOS/freecom).

    python3 fdimg.py out.img [files...]
"""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
FD = os.path.join(HERE, 'freedos')

def build(out, files=(), size=1440, config=None, autoexec=None):
    if os.path.exists(out): os.remove(out)
    subprocess.run(['mformat', '-C', '-f', str(size), '-i', out, '::'], check=True)
    img = bytearray(open(out, 'rb').read())
    bs = bytearray(open(os.path.join(FD, 'BOOT12.BIN'), 'rb').read())
    bs[0x0B:0x3E] = img[0x0B:0x3E]                  # the floppy's BPB, FreeDOS's boot code
    img[0:512] = bs
    open(out, 'wb').write(img)
    tmp = tempfile.mkdtemp()
    extra = []
    for name, data in (('FDCONFIG.SYS', config), ('AUTOEXEC.BAT', autoexec)):
        if data is not None:
            p = os.path.join(tmp, name); open(p, 'wb').write(data); extra.append(p)
    for f in [os.path.join(FD, 'KERNEL.SYS'), os.path.join(FD, 'COMMAND.COM')] + extra + list(files):
        dest, src = (f.split('=', 1) if '=' in f else (os.path.basename(f).upper(), f))
        subprocess.run(['mcopy', '-i', out, src, '::' + dest], check=True)
    return out

if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2:])
