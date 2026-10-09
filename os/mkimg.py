"""Build a Lodestone test floppy: a blank FAT12 1.44 MB disk (mtools), the
Lodestone boot sector merged with its BPB (what LODEBOOT.COM does on the GRiD),
and the given files (name or name=path-on-disk; dirs as 'DIR\\' entries).

    python3 mkimg.py out.img src/LODE.SYS other.com ...
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def build(out, files=(), size=1440, boot=os.path.join(HERE, 'src', 'BOOT.BIN')):
    if os.path.exists(out): os.remove(out)
    subprocess.run(['mformat', '-C', '-f', str(size), '-v', 'LODESTONE', '-i', out, '::'], check=True)
    img = bytearray(open(out, 'rb').read())
    b = open(boot, 'rb').read()
    img[0:11] = b[0:11]
    img[0x3E:512] = b[0x3E:512]
    open(out, 'wb').write(img)
    for f in files:
        if f.endswith('\\') or f.endswith('/'):
            subprocess.run(['mmd', '-i', out, '::' + f.rstrip('\\/').replace('\\', '/')], check=True)
            continue
        if '=' in f:
            dest, src = f.split('=', 1)
        else:
            dest, src = os.path.basename(f).upper(), f
        subprocess.run(['mcopy', '-i', out, src, '::' + dest.replace('\\', '/')], check=True)
    return out


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2:])
