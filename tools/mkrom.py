# Build a 128 KB GRiD application-ROM image: a FAT12 volume in GRiD's own
# ROM format (as GRiD MS-DOS 3.30's EPROM, part 300909-00) with the
# [GridEprom D-3] trailer in its last 256 bytes.
#
#   python3 mkrom.py OUT.BIN --boot ROMBOOT.BIN LODE.SYS FILE ...    a boot ROM
#   python3 mkrom.py OUT.BIN --data FILE ...                        a data ROM
#
# The layout (512-byte sectors, 256 of them): the boot sector (0); one FAT
# (1); the root, 32 entries (2-3); then clusters of one sector from 2 (sector
# 4) to 253 (sector 255, which holds the trailer and is marked bad).  Files
# are contiguous, in the order given: a boot ROM's first is the kernel, which
# its boot sector copies out of the BIOS's RAM copy.  Every cluster no file
# uses is marked bad as well, so the volume has nothing free: it is a ROM.
# image() and trailer() are the old interface (tools/bootsim.py uses them).
import datetime, os, struct, sys

SECT = 512
NSECT = 256
NROOT = 32
FAT_AT, ROOT_AT = 1, 2
DATA_AT = ROOT_AT + NROOT * 32 // SECT       # sector 4: cluster 2
LAST_CLU = NSECT - 1 - DATA_AT + 2           # 253: the trailer's sector
ROM_ID_BOOT = 0x4F4C                         # 'LO': Lodestone's boot ROM (ROM 1)
ROM_ID_DATA = 0x324C                         # 'L2': a Lodestone data ROM (ROM 2)


def trailer(sys_type=1, bootable=0x80, boot_seg=0, size_kb=128, rom_id=0x4F53, text=b'Lodestone',
            part=b'LODE01', copyright=b'(C) Lodestone project', layout=None, when=None, boot_id=0):
    h = bytearray(256)
    struct.pack_into('<HBBH', h, 0, 0xBB66, sys_type, bootable, boot_seg)
    h[6] = 0; h[7] = size_kb; h[8] = 3                     # romAddr, romSize (KB), waitStates (GRiD's: 3)
    if layout:                                             # dirSelector, dirLength, numFiles, pageZeroSelector, totNumPages
        struct.pack_into('<HHHHHH', h, 9, *layout, rom_id)
    else:
        struct.pack_into('<HHHHHH', h, 9, 0, 0, 0, 0, size_kb * 1024 // 512, rom_id)
    h[21:21 + 45] = copyright[:45].ljust(45)
    if when:
        struct.pack_into('<H6B', h, 66, when.year, when.month, when.day, when.hour, when.minute, when.second, 0)
    h[77:77 + 9] = part[:9].ljust(9)
    msg = b'Booting ' + text
    h[101] = len(msg[:30]); h[102:102 + 30] = msg[:30].ljust(30)
    h[132] = boot_id
    h[133] = 1                                             # numRomsInPkg
    h[142:142 + 50] = text[:50].ljust(50)
    h[252] = 1; h[253] = 1                                 # numRomsInGroup, groupSequenceId
    h[255] = (-sum(h[:255])) & 0xFF                        # byte checksum (not checked by the BIOS)
    return bytes(h)


def image(code=b'', **kw):
    img = bytearray(b'\xFF' * 131072)
    img[:len(code)] = code
    img[-256:] = trailer(**kw)
    return bytes(img)


def fat_name(name):
    base, _, ext = os.path.basename(name).upper().partition('.')
    if not (1 <= len(base) <= 8 and len(ext) <= 3) or not all(c.isalnum() or c in '_-$~!#' for c in base + ext):
        raise ValueError('not an 8.3 name: %s' % name)
    return base.ljust(8).encode() + ext.ljust(3).encode()


def dos_time(t):
    return ((t.hour << 11) | (t.minute << 5) | (t.second // 2),
            ((t.year - 1980) << 9) | (t.month << 5) | t.day)


def volume(files, boot=None, label=b'LODESTONE', when=None, data=False, text=b'Lodestone', part=b'LODE'):
    """files: [(name, bytes)] in order.  boot: the boot sector (512 bytes: its
    BPB is replaced by this volume's).  -> the 128 KB image."""
    when = when or datetime.datetime(2026, 10, 18, 12, 0, 0)
    img = bytearray(b'\xFF' * (NSECT * SECT))
    bs = bytearray(boot if boot else b'\xEB\x3C\x90' + bytes(509))
    assert len(bs) == SECT
    bs[3:11] = b'LODE ROM'
    struct.pack_into('<HBHBHHBHHHII', bs, 0x0B, SECT, 1, FAT_AT, 1, NROOT, NSECT, 0xF8, 1, 1, 1, 0, 0)
    bs[0x24:0x3E] = struct.pack('<BBBI', 0x80, 0, 0x29, 0x4F4C) + label[:11].ljust(11) + b'FAT12   '
    bs[510:512] = b'\x55\xAA'
    img[0:SECT] = bs
    fat = [0xFF8, 0xFFF] + [0xFF7] * (LAST_CLU - 1)        # unused (and the trailer's): bad
    root = bytearray(NROOT * 32)
    tm, dt = dos_time(when)
    ent = 0
    if label:
        root[0:11] = label[:11].ljust(11); root[11] = 0x08
        struct.pack_into('<HH', root, 22, tm, dt)
        ent = 1
    clu = 2
    for name, body in files:
        n = (len(body) + SECT - 1) // SECT
        if clu + max(n, 1) - 1 >= LAST_CLU:
            raise ValueError('ROM full: %s needs %d sectors, %d left' % (name, n, LAST_CLU - clu))
        if ent >= NROOT: raise ValueError('root full')
        e = 32 * ent
        root[e:e + 11] = fat_name(name)
        root[e + 11] = 0x01                                # read-only: it's in ROM
        struct.pack_into('<HHHI', root, e + 22, tm, dt, clu if n else 0, len(body))
        if n:
            a = (DATA_AT + clu - 2) * SECT
            img[a:a + len(body)] = body
            img[a + len(body):a + n * SECT] = bytes(n * SECT - len(body))
            for i in range(n): fat[clu + i] = clu + i + 1
            fat[clu + n - 1] = 0xFFF
            clu += n
        ent += 1
    fb = bytearray(SECT)
    for i, v in enumerate(fat):
        o = i * 3 // 2
        if i & 1: fb[o] |= (v << 4) & 0xF0; fb[o + 1] = v >> 4
        else: fb[o] = v & 0xFF; fb[o + 1] |= (v >> 8) & 0x0F
    img[FAT_AT * SECT:(FAT_AT + 1) * SECT] = fb
    img[ROOT_AT * SECT:DATA_AT * SECT] = root
    nfiles = sum(1 for _ in files)
    layout = (ROOT_AT * SECT // 16, NROOT * 32 // 16, nfiles, DATA_AT * SECT // 16, NSECT - DATA_AT)
    if data:
        t = trailer(sys_type=2, bootable=0, rom_id=ROM_ID_DATA, text=text, part=part, layout=layout, when=when)
    else:
        t = trailer(sys_type=1, bootable=0x80, rom_id=ROM_ID_BOOT, text=text, part=part, layout=layout, when=when)
    img[-256:] = t
    return bytes(img), (LAST_CLU - clu) * SECT


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__ if __doc__ else 'mkrom.py OUT.BIN (--boot BOOT.BIN | --data) FILES...'); sys.exit(1)
    out, kind = a[0], a[1]
    boot = None
    if kind == '--boot':
        boot = open(a[2], 'rb').read(); names = a[3:]
    elif kind == '--data':
        names = a[2:]
    else:
        open(out, 'wb').write(image(b'\xEB\xFE')); sys.exit(0)
    files = []
    for n in names:
        dest, _, src = n.partition('=')
        if not src: dest, src = os.path.basename(n), n
        files.append((dest, open(src, 'rb').read()))
    img, left = volume(files, boot=boot, data=(kind == '--data'))
    open(out, 'wb').write(img)
    print('%s: %d files, %d bytes left' % (out, len(files), left))
