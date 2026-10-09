# Execute the real BIOS GridBootRom (F000:E831) against a Lodestone-format EPROM image.
import struct, simgrid as G, sim7210 as S, mkrom
from unicorn import *
from unicorn.x86_const import *
def boot(img, label):
    m = G.Grid(S.bus()); m.setup2({0: img}, [])
    mu = m.mu
    # stack + a near return to a HLT stub inside F000 so we can see "returned = not booted"
    mu.mem_write(0xF0000 + 0x0100, b'\xF4')               # F000:0100 hlt (scratch, mirrored half)
    mu.reg_write(UC_X86_REG_SS, 0x0030); mu.reg_write(UC_X86_REG_SP, 0x0100)
    sp = 0x0100 - 2; mu.mem_write(0x300 + sp, struct.pack('<H', 0x0100)); mu.reg_write(UC_X86_REG_SP, sp)
    mu.reg_write(UC_X86_REG_CS, 0xF000)
    hits = []
    def code(uc, addr, size, ud):
        cs = uc.reg_read(UC_X86_REG_CS)
        if cs >= 0x8000 and cs < 0xA000 and not hits:
            hits.append((cs, uc.reg_read(UC_X86_REG_IP), uc.reg_read(UC_X86_REG_DL), uc.reg_read(UC_X86_REG_FLAGS) & 0x200))
    mu.hook_add(UC_HOOK_CODE, code)
    try: mu.emu_start(0xFE831, 0, count=5_000_000)
    except UcError as e: pass
    cs = mu.reg_read(UC_X86_REG_CS); ip = mu.reg_read(UC_X86_REG_IP)
    ram = bytes(mu.mem_read(0x80000, 0x20000))
    print('%-34s' % label, 'entered %04X:%04X DL=%r IF=%d' % (hits[0][0], hits[0][1], chr(hits[0][2]), bool(hits[0][3])) if hits else 'NOT BOOTED (BIOS returned)',
          '| AX=%04X' % mu.reg_read(UC_X86_REG_AX), '| 8000:0 copy ok' if ram == img else '', '| window unmapped' if not (m.p6f8 & 1) else '| window STILL MAPPED')
code = bytes.fromhex('B84B4F') + b'\xF4'                       # mov ax,'OK' ; hlt
boot(mkrom.image(code), 'Lodestone image, bootSeg 0')
img = bytearray(mkrom.image(b'', boot_seg=0x0100)); img[0x1000:0x1004] = code
boot(bytes(img), 'Lodestone image, bootSeg 0100h')
boot(mkrom.image(code, bootable=0x00), 'bootable flag clear')
boot(mkrom.image(code, sys_type=2), 'system type 2 (not MS-DOS)')
bad = bytearray(mkrom.image(code)); bad[-256] = 0x65
boot(bytes(bad), 'bad BB66 signature')
