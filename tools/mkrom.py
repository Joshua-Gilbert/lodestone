# Build a 128 KB GRiD application-ROM image with the [GridEprom D-3] trailer.
import struct
def trailer(sys_type=1, bootable=0x80, boot_seg=0, size_kb=128, rom_id=0x4F53, text=b'Lodestone',
            part=b'LODE01', copyright=b'(C) Lodestone project'):
    h = bytearray(256)
    struct.pack_into('<HBBH', h, 0, 0xBB66, sys_type, bootable, boot_seg)
    h[6] = 0; h[7] = size_kb; h[8] = 0                     # romAddr, romSize (KB), waitStates
    struct.pack_into('<HHHHHH', h, 9, 0, 0, 0, 0, size_kb * 1024 // 512, rom_id)
    h[21:21 + len(copyright)] = copyright
    h[77:77 + len(part)] = part
    msg = b'Booting ' + text; h[101] = len(msg); h[102:102 + len(msg)] = msg
    h[133] = 1                                              # numRomsInPkg
    h[142:142 + len(text)] = text
    h[255] = (-sum(h[:255])) & 0xFF                         # byte checksum (not checked by BIOS)
    return bytes(h)
def image(code=b'', **kw):
    img = bytearray(b'\xFF' * 131072)
    img[:len(code)] = code
    img[-256:] = trailer(**kw)
    return bytes(img)
if __name__ == '__main__':
    open('TESTROM.BIN', 'wb').write(image(b'\xEB\xFE'))
