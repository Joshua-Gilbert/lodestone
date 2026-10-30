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
#
# A data ROM (ROM 2) is written as the second half of R:, the volume KROM.INC
# joins of the two ROMs, so that R:'s FAT and root sectors are plain copies:
# its FAT sector is R:'s second (entries from 341 on: its cluster n is R:'s
# n + R_OFF, 340, the first entry wholly in that sector), its root R:'s last
# 32 entries (no label, clusters R_OFF on).  A boot ROM's FAT marks R:'s
# entries 254-341 bad (the gap between the two) up to its sector's end.  With
# no ROM 1, R:'s first FAT sector is ROM 2's spare P1_AT (all bad).  So ROM 2
# is no FAT volume by itself; its BPB is only the signature KROM.INC checks.
#
# The 1520 inverts A16 to its ROM sockets: the chip's first 64 KB appears in
# the upper half of the BIOS's window (GRiD's EPROM, read in a programmer, has
# its trailer at FF00h).  So OUT.BIN is the image as the BIOS sees it (the
# emulators' and the tests'), and OUT_EPROM.BIN, its halves swapped, is the
# file to burn.
import datetime, os, struct, sys

SECT = 512
NSECT = 256
NROOT = 32
FAT_AT, ROOT_AT = 1, 2
DATA_AT = ROOT_AT + NROOT * 32 // SECT       # sector 4: cluster 2
LAST_CLU = NSECT - 1 - DATA_AT + 2           # 253: the trailer's sector
ROM_ID_BOOT = 0x4F4C                         # 'LO': Lodestone's boot ROM (ROM 1)
ROM_ID_DATA = 0x4A4C                         # 'LJ': a Lodestone data ROM (ROM 2), joined
ROM_ID_DATA_OLD = 0x324C                     # 'L2': ROM 2 before O10, a volume by itself
R_OFF = 340                                  # ROM 2's cluster n is R:'s n + 340 (KROM.INC)
P1_AT = NSECT - 2                            # 254: ROM 2's spare, R:'s FAT sector 1 without ROM 1


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


def eprom(img):
    """The image as the chip holds it: the 1520 inverts A16, so the halves swap."""
    return img[65536:] + img[:65536]


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
    off = R_OFF if data else 0                             # (a data ROM's clusters as R:'s)
    top = P1_AT - DATA_AT + 2 if data else LAST_CLU        # (the first cluster no file may use)
    fat = [0xFF8, 0xFFF] + [0xFF7] * (2 * SECT * 2 // 3)   # unused (the trailer's, the gap): bad
    root = bytearray(NROOT * 32)
    tm, dt = dos_time(when)
    ent = 0
    if label and not data:
        root[0:11] = label[:11].ljust(11); root[11] = 0x08
        struct.pack_into('<HH', root, 22, tm, dt)
        ent = 1
    clu = 2
    for name, body in files:
        n = (len(body) + SECT - 1) // SECT
        if clu + max(n, 1) - 1 >= top:
            raise ValueError('ROM full: %s needs %d sectors, %d left' % (name, n, top - clu))
        if ent >= NROOT: raise ValueError('root full')
        e = 32 * ent
        root[e:e + 11] = fat_name(name)
        root[e + 11] = 0x01                                # read-only: it's in ROM
        struct.pack_into('<HHHI', root, e + 22, tm, dt, clu + off if n else 0, len(body))
        if n:
            a = (DATA_AT + clu - 2) * SECT
            img[a:a + len(body)] = body
            img[a + len(body):a + n * SECT] = bytes(n * SECT - len(body))
            for i in range(n): fat[clu + off + i] = clu + off + i + 1
            fat[clu + off + n - 1] = 0xFFF
            clu += n
        ent += 1
    fb = fat12(fat)                                        # R:'s two FAT sectors: ROM 1's
    img[FAT_AT * SECT:(FAT_AT + 1) * SECT] = fb[SECT:] if data else fb[:SECT]     # first, ROM 2's second
    if data:
        img[P1_AT * SECT:(P1_AT + 1) * SECT] = fat12([0xFF8, 0xFFF] + [0xFF7] * (2 * SECT * 2 // 3))[:SECT]
    img[ROOT_AT * SECT:DATA_AT * SECT] = root
    nfiles = sum(1 for _ in files)
    layout = (ROOT_AT * SECT // 16, NROOT * 32 // 16, nfiles, DATA_AT * SECT // 16, NSECT - DATA_AT)
    if data:
        t = trailer(sys_type=2, bootable=0, rom_id=ROM_ID_DATA, text=text, part=part, layout=layout, when=when)
    else:
        t = trailer(sys_type=1, bootable=0x80, rom_id=ROM_ID_BOOT, text=text, part=part, layout=layout, when=when)
    img[-256:] = t
    return bytes(img), (top - clu) * SECT


def fat12(fat):
    """entries -> two sectors of FAT12 (those past them dropped)"""
    fb = bytearray(2 * SECT + 2)
    for i, v in enumerate(fat[:2 * SECT * 2 // 3 + 1]):
        o = i * 3 // 2
        if i & 1: fb[o] |= (v << 4) & 0xF0; fb[o + 1] = v >> 4
        else: fb[o] = v & 0xFF; fb[o + 1] |= (v >> 8) & 0x0F
    return bytes(fb[:2 * SECT])


def joined(r1, r2):
    """R: as KROM.INC maps it, of ROM 1 and ROM 2 images (r1 None: ROM 2
    alone), as a FAT12 volume another reader can take: a boot sector with
    its geometry, FAT (ROM 1's sector or ROM 2's P1, then ROM 2's), root
    (ROM 1's 32 entries, their empties made deleted as KROM.INC's .fix does,
    then ROM 2's), clusters 2-253 ROM 1's, 254-341 the gap, then ROM 2's."""
    S = lambda r, n: bytes(r[n * SECT:(n + 1) * SECT])
    fat = (S(r1, FAT_AT) if r1 else S(r2, P1_AT)) + S(r2, FAT_AT)
    root1 = bytearray(S(r1, ROOT_AT) + S(r1, ROOT_AT + 1) if r1 else bytes(NROOT * 32))
    for e in range(0, len(root1), 32):
        if root1[e] == 0: root1[e] = 0xE5
    root = bytes(root1) + S(r2, ROOT_AT) + S(r2, ROOT_AT + 1)
    ncl = LAST_CLU + 1 + R_OFF
    data_at = 1 + 2 + len(root) // SECT
    bs = bytearray(r1[:SECT] if r1 else r2[:SECT])
    struct.pack_into('<HBHBHHBH', bs, 0x0B, SECT, 1, 1, 1, 2 * NROOT, data_at + ncl - 2, 0xF8, 2)
    img = bytearray(bs) + fat + root
    img += (r1[DATA_AT * SECT:] if r1 else bytes((NSECT - DATA_AT) * SECT)) + bytes((R_OFF - (NSECT - DATA_AT)) * SECT)
    return bytes(img + r2[DATA_AT * SECT:])


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
    burn = os.path.splitext(out)[0] + '_EPROM.BIN'
    open(burn, 'wb').write(eprom(img))
    print('%s: %d files, %d bytes left; burn %s' % (out, len(files), left, burn))
