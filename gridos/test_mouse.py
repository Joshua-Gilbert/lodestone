import gosim
def install():
    pc = gosim.PC('test.img', keys=[0x1579]); com = open('src/GOSBOOT.COM','rb').read()
    pc.mu.mem_write(0x10000, b'\xCD\x20' + b'\0'*0x7E + b'\x00\x0D'); pc.mu.mem_write(0x10100, com)
    for r in (gosim.UC_X86_REG_DS, gosim.UC_X86_REG_ES, gosim.UC_X86_REG_SS): pc.W(r, 0x1000)
    pc.W(gosim.UC_X86_REG_SP, 0xFFFE); pc.run(0x1000, 0x100); open('test.img','wb').write(pc.img)
def boot(moves, slices):
    pc = gosim.PC('test.img', mouse_moves=moves)
    pc.mu.mem_write(0x7C00, bytes(pc.img[:512])); pc.W(gosim.UC_X86_REG_DX, 0)
    pc.run(0, 0x7C00, slices=slices); return pc, bytes(pc.mu.mem_read(0xB8000, 0x8000))
install()
steps = [(3,2),(5,-4),(-7,1),(1,12),(16,0),(0,13),(-1,-1),(9,0),(0,-14),(127,100),(127,127),(127,127),(127,0),
         (0,127),(-3,-2),(-100,-60),(-1,0),(-2,1),(-6,-7),(8,3)]
moves = [(40 + i * 3, dx, dy, 0) for i, (dx, dy) in enumerate(steps)]
x, y = 320, 200
for dx, dy in steps: x = min(639, max(0, x + dx)); y = min(399, max(0, y + dy))
print('final cursor position', x, y)
ref_pc, ref = boot([], 200)
pc, scr = boot(moves, 200)
rowoff = lambda yy: (yy & 3) * 0x2000 + (yy >> 2) * 80
allowed = set()
for (cx, cy) in ((320, 200), (x, y)):
    for r in range(13):
        if cy + r < 400:
            for c in range(2): allowed.add(rowoff(cy + r) + (cx >> 3) + c)
bad = [i for i in range(32000) if scr[i] != ref[i] and i not in allowed]
print('bytes changed outside the two cursor areas:', len(bad))
shape = [(0x80,0),(0xC0,0),(0xE0,0x40),(0xF0,0x60),(0xF8,0x70),(0xFC,0x78),(0xFE,0x7C),(0xFF,0x7E),(0xFF,0x70),(0xF8,0x50),(0xDC,0x08),(0x9C,0x08),(0x0C,0)]
err = 0
for r,(m,l) in enumerate(shape):
    if y + r >= 400: break
    m16 = (m << 8) >> (x & 7); l16 = (l << 8) >> (x & 7)
    for c, (mm, ll) in enumerate(((m16 >> 8, l16 >> 8), (m16 & 0xFF, l16 & 0xFF))):
        if (x >> 3) + c >= 80: continue
        o = rowoff(y + r) + (x >> 3) + c
        if scr[o] != (ref[o] ^ mm): err += 1
print('cursor pixel errors at the final position:', err)
import re
lst = open('src/GRIDOS.LST').read()
for name in ('solid', 'vsync'):
    m = re.search(r'^\s+\d+ ([0-9A-F]{8}) [0-9A-F]+\s+%s\s' % name, lst, re.M)
    print(name, '=', pc.mu.mem_read(0x10000 + int(m.group(1), 16), 1)[0])
pc.screen_png('shot_mouse.png')
