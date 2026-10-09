"""A bootable GRiD MS-DOS 3.30 floppy image for the emulator, made from the
GRiD MS-DOS EPROM image (its boot sector also boots a floppy): IO.SYS and
MSDOS.SYS first and contiguous, then COMMAND.COM, then the given files.

    python3 dosimg.py out.img GRID_MSDOS330_ROM_300909-00.BIN [files...]
"""
import os, subprocess, sys, tempfile

def build(out, rom, files=(), size=1440, config=None):
    if os.path.exists(out): os.remove(out)
    subprocess.run(['mformat', '-C', '-f', str(size), '-i', out, '::'], check=True)   # no label: IO.SYS must be entry 0
    tmp = tempfile.mkdtemp()
    for n in ('IO.SYS', 'MSDOS.SYS', 'COMMAND.COM'):
        subprocess.run(['mcopy', '-n', '-i', rom, '::' + n, os.path.join(tmp, n)], check=True)
    img = bytearray(open(out, 'rb').read())
    bs = bytearray(open(rom, 'rb').read()[:512])
    bs[0x0B:0x1E] = img[0x0B:0x1E]                  # the floppy's BPB, GRiD's boot code
    img[0:512] = bs
    open(out, 'wb').write(img)
    for n in ('IO.SYS', 'MSDOS.SYS', 'COMMAND.COM'):
        subprocess.run(['mcopy', '-i', out, os.path.join(tmp, n), '::' + n], check=True)
    subprocess.run(['mattrib', '-i', out, '+h', '+s', '+r', '::IO.SYS', '::MSDOS.SYS'], check=True)
    if config is not None:
        p = os.path.join(tmp, 'CONFIG.SYS'); open(p, 'wb').write(config)
        subprocess.run(['mcopy', '-i', out, p, '::CONFIG.SYS'], check=True)
    for f in files:
        dest, src = (f.split('=', 1) if '=' in f else (os.path.basename(f).upper(), f))
        subprocess.run(['mcopy', '-i', out, src, '::' + dest], check=True)
    return out

if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2], sys.argv[3:])
