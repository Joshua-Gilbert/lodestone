import gosim, sys
def boot(keys, moves, png, slices=500, after=60):
    pc = gosim.PC('test.img', keys=keys, mouse_moves=moves)
    pc.mu.mem_write(0x7C00, bytes(pc.img[:512])); pc.W(gosim.UC_X86_REG_DX, 0)
    pc.run(0, 0x7C00, slices=slices, keys_after=after); pc.screen_png(png)
    print(png, 'tty', repr(pc.tty), 'keys left', len(pc.keys))
    return pc
# install the boot sector with GOSBOOT first
pc = gosim.PC('test.img', keys=[0x1579]); com = open('src/GOSBOOT.COM','rb').read()
pc.mu.mem_write(0x10000, b'\xCD\x20' + b'\0'*0x7E + b'\x00\x0D'); pc.mu.mem_write(0x10100, com)
for r in (gosim.UC_X86_REG_DS, gosim.UC_X86_REG_ES, gosim.UC_X86_REG_SS): pc.W(r, 0x1000)
pc.W(gosim.UC_X86_REG_SP, 0xFFFE); pc.run(0x1000, 0x100); open('test.img','wb').write(pc.img)
boot([0x5000]*4, [(30, 60, -40, 0), (31, 30, 30, 0)], 'shot_main.png')
boot([0x5000, 0x3B00], [], 'shot_help.png')
boot([0x4F00, 0x1C0D], [], 'shot_confirm.png')
# mouse click on the 3rd list row (y = 24 + 2*16 + 8 = 64)
boot([], [(20, 0, 0, 0), (25, -100, -127, 0), (26, 0, -9, 0), (28, 0, 0, 1), (29, 0, 0, 0)], 'shot_click.png')
boot([0x2000], [], 'shot_dos.png')
