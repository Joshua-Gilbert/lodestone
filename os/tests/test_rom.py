"""Lodestone 0.6: booting from the ROM, and R:, in pcemu (and, for the
BIOS's own part, the real 1520 BIOS in tools/simgrid.py when the dumps are
in rom/).

    python3 tests/test_rom.py [t_image t_bios t_boot t_read t_write t_floppy t_settings t_mdisk t_menu t_system t_paths t_memory]

The image (tools/mkrom.py): GRiD's ROM format, read back by mtools, the
trailer, nothing free.  The BIOS: which socket it boots, and pcemu's
INT 15h E400-E404 against the real BIOS's answers.  Booting from the ROM
with and without EMS and the hard disk: R: there, the current drive, PATH
and COMSPEC, INT 21h 0Eh, the picture.  R:'s reads (files as burned, a
read into video memory under the ROM's window), its writes refused.  A
floppy start with the ROM in: R: there, everything else as before.  The
settings: the ROM's, C:'s over them (A:'s without C:), no disk in A: is no
error.  The menu (Shift held): Lodestone, the ROM's settings, GRiD MS-DOS
in the other socket, the floppy.  System's Settings topic, and a setting
saved from a ROM start going to C:\\LODE.INI with only that change.
Programs found by PATH: C:\\LODE before R:.  Memory for DOS programs.
"""
import os, re, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
GOS = os.path.dirname(HERE)
ROOT = os.path.dirname(GOS)
sys.path[:0] = [GOS, HERE, os.path.join(ROOT, 'tools')]
import ktest, mkimg, pcemu, mkrom
import test_apps as A
import test_splash as TS
from test_apps import check, results, has, CODE

OUT = A.OUT
ROM1 = os.path.join(GOS, 'LODE1.BIN')
ROM2 = os.path.join(GOS, 'LODE2.BIN')
MSDOS = os.environ.get('GRID_ROM') or os.path.join(ROOT, 'rom', 'GRID_MSDOS330_ROM_300909-00.BIN')
BIOS = os.path.join(ROOT, 'rom', 'ROM_F000.BIN')
ROMVID = os.path.join(HERE, 'ROMVID.COM')
ROMT = os.path.join(HERE, 'ROMT.COM')
LCMD = os.path.join(GOS, 'src', 'LCMD.COM')
SHIFT = 0x02


def build():
    A.build()
    subprocess.run([os.path.join(GOS, 'build.sh')], check=True, stdout=subprocess.DEVNULL)
    for n in ('ROMVID', 'ROMT'):
        subprocess.run(['nasm', '-f', 'bin', '-o', os.path.join(HERE, n + '.COM'), os.path.join(HERE, n + '.ASM')], check=True)

def rom(): return open(ROM1, 'rb').read()
def rom2(): return open(ROM2, 'rb').read()

def floppy(name, *files):
    return mkimg.build(os.path.join(OUT, name), list(files))

def u8(k, n): return k.pc.rd(0x60, k.Y[n], 1)[0]

def boot(img=None, sock=1, roms=None, shift=False, keys=(), **kw):
    """A machine with the ROM in socket `sock`, started the way the BIOS
    starts it (or from the floppy, sock=None)."""
    roms = roms if roms is not None else {sock if sock is not None else 1: rom()}
    k = ktest.KPC(img if img is not None else floppy('rom_blank.img'), roms=roms, **kw)
    if shift: k.pc.wr(0, 0x417, [SHIFT])
    if sock is None: k.pc.boot(0)
    else: k.pc.boot_rom(sock)
    for x in keys: k.pc.keys.append(x)
    k.settle(25)
    return k

def env(k):
    e = k.pc.u16(0x60, k.Y['ex_env'])
    return k.pc.rd(e, 0, 512).split(b'\0\0')[0].decode('latin-1').split('\0')

def prompt(k, cmd, sim_s=8):
    k.key('cls'); k.key(ktest.ENTER); k.key(cmd); k.key(ktest.ENTER, settle=False); k.settle(sim_s)
    return k.pc.text_screen()

def to_prompt(k):
    k.code_p(); k.settle()

def sysinfo_hd(*files):
    """the test hard disk (C:), with files [(path, bytes)]"""
    import fat16img as F
    cyl, heads, spt, plba = 70, 4, 17, 17
    f = F.Fat(cyl * heads * spt - plba, 1, plba, True, label='GRIDHD')
    tree = [('README.TXT', 0x20, b'Hello from drive C:\r\n')]
    dirs = {}
    for path, body in files:
        if '\\' in path:
            d, n = path.split('\\', 1)
            dirs.setdefault(d, []).append((n, 0x20, body))
        else:
            tree.append((path, 0x20, body))
    for d, ents in dirs.items(): tree.append((d, 0x10, ents))
    f.finish(f.tree(tree))
    return pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=cyl, heads=heads, spt=spt,
                     disk=F.disk(cyl, heads, spt, plba, f))

def hd_file(k, path):
    import fat16img as F
    return F.Volume(k.pc.ata.disk, 17).files()[0].get('\\' + path)


# ---------------------------------------------------------------------
def t_image():
    print('== the ROM image')
    img = rom()
    check('128 KB', len(img) == 131072, len(img))
    t = img[-256:]
    check('trailer: BB66h, a boot image (system type 1, bootable 80h), id LO', t[0:2] == b'\x66\xBB' and t[2] == 1 and t[3] == 0x80
          and struct.unpack_from('<H', t, 19)[0] == mkrom.ROM_ID_BOOT, t[:24].hex())
    dsel, dlen, nf, p0, pages = struct.unpack_from('<HHHHH', t, 9)
    check('trailer: the directory and data where they are', (dsel, dlen, p0, pages) == (0x40, 0x40, 0x80, 252), (dsel, dlen, p0, pages))
    check('its boot sector is ROMBOOT, with the volume\'s BPB', img[3:11] == b'LODE ROM' and img[510:512] == b'\x55\xAA'
          and img[0x3E:0x60] == open(os.path.join(GOS, 'src', 'ROMBOOT.BIN'), 'rb').read()[0x3E:0x60])
    p = os.path.join(OUT, 'rom_image.bin'); open(p, 'wb').write(img)
    e = dict(os.environ, MTOOLS_SKIP_CHECK='1')
    d = subprocess.run(['mdir', '-i', p, '::'], capture_output=True, text=True, env=e).stdout
    check('mtools reads it: LODE.SYS first, nothing free', 'LODE     SYS' in d and ' 0 bytes free' in d.replace('\u202f', ' '), d)
    first = d.split('Directory for ::/')[1].strip().split('\n')[0]
    check('LODE.SYS is the first file', first.startswith('LODE     SYS'), first)
    srcs = {'LODE.SYS': 'src/LODE.SYS', 'LODEMT.SYS': 'src/LODEMT.SYS', 'LCMD.COM': 'src/LCMD.COM', 'SYSTEM.RUN': 'apps/SYSTEM.RUN',
            'TERMINUS.FNT': 'fonts/TERMINUS.FNT', 'LODE.INI': 'rom/LODE.INI',
            'PS.PRN': 'drivers/PS.PRN', 'TASKS.RUN': 'apps/TASKS.RUN', 'TERM.RUN': 'apps/TERM.RUN'}
    bad = []
    for n, s in srcs.items():
        o = os.path.join(OUT, 'rom_x')
        subprocess.run(['mcopy', '-n', '-o', '-i', p, '::' + n, o], env=e, check=True)
        if open(o, 'rb').read() != open(os.path.join(GOS, s), 'rb').read(): bad.append(n)
    check('the files read back as built', not bad, bad)
    burn = open(os.path.join(GOS, 'LODE1_EPROM.BIN'), 'rb').read()
    check('the file to burn has its halves swapped (the 1520 inverts A16): trailer at FF00h, boot sector at 10000h',
          burn == img[65536:] + img[:65536] and burn[0xFF00:0xFF02] == b'\x66\xBB' and burn[0x10003:0x1000B] == b'LODE ROM')
    try:
        mkrom.volume([('BIG.BIN', bytes(130000))])
        check('a ROM that would overflow is refused', False)
    except ValueError as x:
        check('a ROM that would overflow is refused', 'ROM full' in str(x), x)


def joined(r1, r2):
    """R:'s sectors 1-6 as KROM.INC makes them of ROM 1 and ROM 2: the FAT
    (ROM 1's sector, ROM 2's entries from 254 on, clusters + 252) and the
    root (ROM 1's empty entries deleted; ROM 2's label gone, clusters + 252)."""
    def get(f, n):
        o = n * 3 // 2; w = f[o] | f[o + 1] << 8
        return w >> 4 if n & 1 else w & 0xFFF
    fb = bytearray(1024); fb[0:512] = r1[512:1024]
    for n in range(254, 506):
        v = get(r2[512:1024], n - 252)
        if 2 <= v <= 0xFF6: v += 252
        o = n * 3 // 2
        if n & 1: fb[o] = (fb[o] & 0x0F) | ((v & 0x0F) << 4); fb[o + 1] = v >> 4
        else: fb[o] = v & 0xFF; fb[o + 1] = (fb[o + 1] & 0xF0) | (v >> 8)
    a = bytearray(r1[1024:2048]); b = bytearray(r2[1024:2048])
    for e in range(0, 1024, 32):
        if a[e] == 0: a[e] = 0xE5
        if b[e] in (0, 0xE5): continue
        if b[e + 11] & 0x08: b[e] = 0xE5
        elif struct.unpack_from('<H', b, e + 26)[0] >= 2: struct.pack_into('<H', b, e + 26, struct.unpack_from('<H', b, e + 26)[0] + 252)
    return bytes(fb) + bytes(a) + bytes(b)

def t_rom2():
    """ROM 2 (LODE2.BIN: mkrom.py --data, DEFRAG.COM on it) joined to R:
    beside ROM 1's files, in either socket; either ROM alone; the saver's
    DEFRAG from it; what it costs."""
    print('== ROM 2, joined to R:')
    img = rom2(); t = img[-256:]
    defrag = open(os.path.join(GOS, 'src', 'DEFRAG.COM'), 'rb').read()
    check('LODE2.BIN: a data ROM (system type 2, not bootable, id L2); ROM 1 has no DEFRAG.COM now',
          t[2] == 2 and t[3] == 0 and struct.unpack_from('<H', t, 19)[0] == mkrom.ROM_ID_DATA
          and b'DEFRAG  COM' in img[1024:2048] and b'DEFRAG  COM' not in rom()[1024:2048], t[:24].hex())
    big = bytes((i * 7 + i // 512) & 0xFF for i in range(60000))
    small = [('F%02d.TXT' % i, b'file %d\r\n' % i) for i in range(18)]    # (ROM 2's root past 16 entries: R:'s sector 6)
    r2 = mkrom.volume([('DEFRAG.COM', defrag), ('BIG.BIN', big)] + small, data=True)[0]
    e = r2[1024:2048].index(b'BIG     BIN')
    c0 = struct.unpack_from('<H', r2, 1024 + e + 26)[0]
    c1 = c0 + (len(big) + 511) // 512 - 1
    check('the test ROM 2: BIG.BIN\'s clusters on R: (%d-%d) span the FAT entry split over its two sectors (341)' % (c0 + 252, c1 + 252),
          c0 + 252 < 341 < c1 + 252)
    for sockets, kw in (({0: r2, 1: rom()}, {'ems_pages': 88}), ({1: r2, 0: rom()}, {'ata': 1})):
        sock1 = [s for s, v in sockets.items() if v is not r2][0]
        where = 'ROM 2 in socket %d (%s)' % (1 - sock1, 'EMS' if 'ems_pages' in kw else 'C:')
        mem = []
        for rs in (sockets, {sock1: rom()}):
            kk = dict(kw)
            if 'ata' in kk: kk['ata'] = TS.hd()
            k = boot(floppy('rom2.img', A.MEMSZ), sock=sock1, roms=rs, **kk)
            to_prompt(k)
            m = re.search(r'([\d.]+) KB for programs', prompt(k, 'a:memsz'))
            mem.append(m and float(m.group(1)))
        k = boot(floppy('rom2.img', A.MEMSZ), sock=sock1, roms=sockets, **dict(kw, **({'ata': TS.hd()} if 'ata' in kw else {})))
        to_prompt(k)
        prompt(k, 'a:memsz')                                            # (a program first: the module stays whole)
        oh = prompt(k, 'dir r:\\lode.sys')
        o = prompt(k, 'dir r:')                                        # (the end of it: 32 lines scroll)
        o2 = ''.join(prompt(k, 'copy r:\\%s a:\\' % n) for n in ('defrag.com', 'big.bin', 'tasks.run', 'f17.txt'))
        got = (A.disk_file(k, 'DEFRAG.COM') == defrag, A.disk_file(k, 'BIG.BIN') == big,
               A.disk_file(k, 'TASKS.RUN') == open(os.path.join(GOS, 'apps', 'TASKS.RUN'), 'rb').read(),
               A.disk_file(k, 'F17.TXT') == b'file 17\r\n')
        want = joined(rom(), r2)
        fat = bytes(k.rd('fatbuf', 1024)) if k.rd('fat_drv', 1)[0] == 17 else None
        roots = {}
        for i in range(5):                                              # (KDISK.INC: NBUF buffers)
            if k.rd('buf_drv', 1, i)[0] == 17 and 3 <= k.u16('buf_lba', 2 * i) <= 6:
                roots[k.u16('buf_lba', 2 * i)] = bytes(k.rd('bufs', 512, 512 * i))
        check('%s: what DOS programs get: %.1f KB, ROM 1 alone %.1f KB (R:\'s module 18 paragraphs more, what joins the two)'
              % (where, mem[0] or 0, mem[1] or 0), mem[0] and mem[1] and 0.2 <= round(mem[1] - mem[0], 1) <= 0.4, mem)
        check('%s: the FAT R: made of the two (fatbuf, both sectors: ROM 2\'s entries from 254, clusters + 252, the one split '
              'over the sectors) and its root sectors in the buffers (ROM 2\'s, past 16 entries too; its label gone), byte for byte' % where,
              fat == want[:1024] and 5 in roots and 6 in roots and all(v == want[1024 + 512 * (n - 3):1536 + 512 * (n - 3)] for n, v in roots.items()),
              (fat is not None and next((i for i in range(1024) if fat[i] != want[i]), None), sorted(roots)))
        check('%s: DIR R: ROM 1\'s files then ROM 2\'s (DEFRAG.COM, BIG.BIN, F00-F17.TXT), one label, 33 files, 0 bytes free' % where,
              'Volume in drive R is LODESTONE' in oh and 'LODE     SYS' in oh
              and 'F17      TXT' in o and '33 File(s)' in o and ' 0 bytes free' in o and not k.crashed, o)
        check('%s: copied from R: as built: DEFRAG.COM, BIG.BIN (its chain over both FAT sectors R: makes), ROM 1\'s last file '
              '(TASKS.RUN) and ROM 2\'s 21st entry (F17.TXT)' % where, got == (True, True, True, True), (got, o2[-300:]))
    fake = bytearray(rom2()); fake[-256 + 19:-256 + 21] = b'XX'                  # (a data ROM, not Lodestone's: its id)
    k = boot(floppy('rom2a.img', A.SYS, LCMD), sock=None, roms={0: bytes(fake), 1: rom2()})
    to_prompt(k)
    o = prompt(k, 'dir r:') + prompt(k, 'copy r:\\defrag.com a:\\')
    check('a floppy start with ROM 2 alone (its image the second, another ROM the first): R: is it (DEFRAG.COM, 1 file), '
          'read as built', 'DEFRAG   COM' in o and '1 File(s)' in o and 'LODE     SYS' not in o and A.disk_file(k, 'DEFRAG.COM') == defrag, o)
    k = boot(floppy('rom2b.img'))
    to_prompt(k)
    o = prompt(k, 'dir r:')
    check('ROM 1 alone: R: as before, without DEFRAG.COM (13 files)', 'LODE     SYS' in o and 'DEFRAG' not in o and '13 File(s)' in o, o)
    # the saver's round of the disks: DEFRAG.COM from R: (the start-up drive's root) with ROM 2 in; without it, the clock
    seen = []
    for rs in ({0: rom2(), 1: rom()}, {1: rom()}):
        k = boot(floppy('rom2s.img'), sock=1, roms=rs)
        tk = struct.unpack('<H', k.pc.rd(0, 0x46C, 2))[0]
        k.wr('lastact', struct.pack('<H', (tk - 5462 + 18) & 0xFFFF))
        d = False
        for _ in range(60):
            k.pc.run_for(0.1)
            if has(k, 'Drive A:'): d = True; break
        seen.append((d, not has(k, 'Select a file and confirm')))
    check('the screen saver from the ROM: DEFRAG.COM from R: with ROM 2 in (its map: "Drive A:"); with ROM 1 alone, the '
          'dark clock without it', seen == [(True, True), (False, True)], seen)


def masked(b):
    """ROMT.BIN with the flags words kept to CF and IF (the rest is whatever
    the code before left)"""
    b = bytearray(b)
    for o in [8] + [10 + 32 * i + 10 for i in range(8)]:
        struct.pack_into('<H', b, o, struct.unpack_from('<H', b, o)[0] & 0x201)
    return bytes(b)


def t_bios():
    print('== the 1520\'s BIOS (tools/simgrid.py, the real one)')
    if not (os.path.exists(BIOS) and os.path.exists(MSDOS)):
        print('   (skipped: rom/ROM_F000.BIN and the GRiD MS-DOS EPROM image are not here)'); return
    import simgrid as G, sim7210 as S, dosemu as D
    from unicorn import UcError, UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_CS, UC_X86_REG_SS, UC_X86_REG_SP
    ms = open(MSDOS, 'rb').read()
    def booted(roms):
        m = G.Grid(S.bus()); m.setup2(roms, [])
        mu = m.mu
        mu.mem_write(0xF0100, b'\xF4'); mu.reg_write(UC_X86_REG_SS, 0x30)
        mu.mem_write(0x300 + 0xFE, struct.pack('<H', 0x100)); mu.reg_write(UC_X86_REG_SP, 0xFE)
        mu.reg_write(UC_X86_REG_CS, 0xF000)
        hits = []
        def hk(uc, a, z, d):
            if 0x8000 <= uc.reg_read(UC_X86_REG_CS) < 0xA000 and not hits:
                hits.append(1); uc.emu_stop()
        mu.hook_add(UC_HOOK_CODE, hk)
        try: mu.emu_start(0xFE831, 0, count=5_000_000)
        except UcError: pass
        return bytes(mu.mem_read(0x80000, 0x20000)) if hits else None
    r = rom()
    check('Lodestone alone, either socket: the BIOS boots it', booted({0: r}) == r and booted({1: r}) == r)
    check('with GRiD MS-DOS in the first socket and Lodestone in the second: Lodestone', booted({0: ms, 1: r}) == r)
    check('the other way round: MS-DOS (the BIOS boots the last one it finds)', booted({0: r, 1: ms}) == ms)
    out = {}
    for roms in ({1: r}, {0: ms, 1: r}, {0: r, 1: ms}):
        m = G.Grid(S.bus()); m.setup2(roms, [])
        D.Machine.run(m, ROMT, seg=0x1000, maxins=20_000_000)
        real = m.files['A:\\ROMT.BIN']
        k = ktest.KPC(floppy('rom_t.img', A.SYS, ROMT), roms=roms); k.start()
        k.run_file('ROMT.COM', 20)
        emu = A.disk_file(k, 'ROMT.BIN')
        out[tuple(roms)] = (real, emu)
        where = ', '.join('%d: %s' % (s, 'Lodestone' if roms[s] is r else 'MS-DOS') for s in roms)
        check('pcemu answers E400-E404 as the BIOS does, sockets %s' % where, emu and masked(real) == masked(emu),
              (real[:40].hex(), emu[:40].hex() if emu else None))
        # what E403 leaves of BX, CX, DX (ROMT passes 1111h, 2222h, 33h:image)
        regs = lambda b: [struct.unpack_from('<3H', b, 10 + 32 * i + 16) for i in range(b[6])]
        check('... and BX, CL, DH after E403 changed as the BIOS changes them (%s)' % where,
              emu and regs(real) == regs(emu) and all(bx != 0x1111 and cx == 0x2200 and dx >> 8 == 0x0B
                                                     for bx, cx, dx in regs(real)),
              (regs(real), regs(emu) if emu else None))


def t_boot():
    print('== starting from the ROM')
    for tag, kw in (('floppies only', {}), ('EMS', {'ems_pages': 88}), ('the hard disk', {'ata': TS.hd()}),
                    ('EMS and the hard disk', {'ems_pages': 88, 'ata': TS.hd()})):
        k = boot(**kw)
        hd = 'ata' in kw
        check('%s: the Executive, on %s' % (tag, 'C:' if hd else 'R:'), not k.crashed and k.pc.mode() == 0x40
              and has(k, 'Lodestone 0.6') and has(k, 'Hard disk C:' if hd else 'ROM R:'), A.screen(k))
        check('%s: started from R: (3305h), INT 21h 0Eh counts to R:' % tag, u8(k, 'bootdrv') == 17 and u8(k, 'lastdrv') == 18)
        e = env(k)
        want = ['COMSPEC=R:\\LCMD.COM', 'PATH=C:\\LODE;R:\\' if hd else 'PATH=R:\\', 'PROMPT=$P$G']
        check('%s: COMSPEC and PATH' % tag, e == want, e)
        check('%s: the picture was shown' % tag, TS.ON in [m[0] for m in k.pc.marks] and TS.OFF in [m[0] for m in k.pc.marks])
        check('%s: the settings: the ROM\'s, %s over them' % (tag, 'C:\'s' if hd else 'none'), u8(k, 'setdrv') == (3 if hd else 0))


def t_read():
    print('== R:\'s reads')
    k = boot(floppy('rom_rd.img', ROMVID), ems_pages=88)
    to_prompt(k)
    o = prompt(k, 'dir r:')
    check('DIR R:', 'Volume in drive R is LODESTONE' in o and 'LODE     SYS' in o and 'SYSTEM   RUN' in o and ' 0 bytes free' in o, o)
    o = prompt(k, 'copy r:\\*.* a:')
    check('COPY R:\\*.* A:', '11 File(s) copied' in o or 'File(s) copied' in o, o)
    bad = [n for n, s in (('LODE.SYS', 'src/LODE.SYS'), ('SYSTEM.RUN', 'apps/SYSTEM.RUN'), ('LCMD.COM', 'src/LCMD.COM'),
                          ('LODE.INI', 'rom/LODE.INI'))
           if A.disk_file(k, n) != open(os.path.join(GOS, s), 'rb').read()]
    check('the copies are the files as built', not bad, bad)
    o = prompt(k, 'a:romvid')
    check('a read into video memory (under the ROM\'s window) bounces right', 'ROMVID: the same' in o, o)
    check('the ROM was mapped in and out (video memory back each time)', k.pc.rom_mapped is None and k.pc.rom_maps > 10, k.pc.rom_maps)
    o = prompt(k, 'type r:\\lode.ini')
    check('TYPE R:\\LODE.INI', 'SPLASH=1' in o and 'MDISK=256' in o, o)


def t_write():
    print('== R: can\'t be written')
    k = boot(floppy('rom_wr.img', ROMVID), ata=TS.hd())
    to_prompt(k)
    before = rom()
    o = prompt(k, 'copy c:\\readme.txt r:')
    check('COPY to R: fails', 'File(s) copied' not in o or '0 File(s) copied' in o, o)
    o = prompt(k, 'del r:\\lode.ini')
    o2 = prompt(k, 'dir r:')
    check('DEL on R: fails, the file is still there', 'LODE     INI' in o2, o + o2)
    o = prompt(k, 'md r:\\new')
    check('MD on R: fails', 'NEW' not in prompt(k, 'dir r:'), o)
    check('the ROM unchanged', k.pc.roms[1] == before)
    check('nothing crashed', not k.crashed)


def t_floppy():
    print('== starting from a floppy with the ROM in')
    img = floppy('rom_fl.img', A.SYS, LCMD, A.MEMSZ)
    k = boot(img, sock=None)
    check('the Executive on A:, R: there too', has(k, 'Floppy A:') and u8(k, 'bootdrv') == 0 and u8(k, 'lastdrv') == 18)
    check('PATH and COMSPEC on A: as before', env(k) == ['COMSPEC=A:\\LCMD.COM', 'PATH=A:\\', 'PROMPT=$P$G'], env(k))
    check('the settings: A:\'s alone', u8(k, 'setdrv') == 0)
    to_prompt(k)
    o = prompt(k, 'dir r:')
    check('DIR R: from a floppy start', 'LODE     SYS' in o, o)
    k2 = ktest.KPC(floppy('rom_fl2.img', A.SYS, LCMD)); k2.start()
    check('no ROM: no R:, the count as before', u8(k2, 'lastdrv') == 2)


def t_settings():
    print('== the settings: the ROM\'s, and the changes over them')
    k = boot(ata=sysinfo_hd(('LODE.INI', b'SAVER=10\r\nSPLASH=0\r\n')))
    ui = k.pc.u16(0x60, k.Y['ui_seg'])
    check('C:\\LODE.INI over the ROM\'s: SAVER=10', k.pc.rd(ui, k.Y['saver_min'], 1)[0] == 10, k.pc.rd(ui, k.Y['saver_min'], 1))
    check('C:\\LODE.INI\'s SPLASH=0: no picture', TS.ON not in [m[0] for m in k.pc.marks])
    k = boot(ata=sysinfo_hd(), ems_pages=88)
    check('no C:\\LODE.INI: the ROM\'s (the picture, M: 256 KB)', TS.ON in [m[0] for m in k.pc.marks])
    open(os.path.join(OUT, 'LODE.INI'), 'wb').write(b'SPLASH=0\r\n')
    a = floppy('rom_set.img', os.path.join(OUT, 'LODE.INI'))
    k = boot(a)
    check('no C:, A:\\LODE.INI over the ROM\'s', u8(k, 'setdrv') == 1 and TS.ON not in [m[0] for m in k.pc.marks])
    big = b'SAVER=10\r\n' + b'; padding\r\n' * 410          # (past the 4 KB the readers take)
    k = boot(ata=sysinfo_hd(('LODE.INI', big)), ems_pages=88)
    ui = k.pc.u16(0x60, k.Y['ui_seg'])
    check('a C:\\LODE.INI of %d bytes: started, its SAVER= taken' % len(big), not k.crashed
          and k.pc.mode() == 0x40 and k.pc.rd(ui, k.Y['saver_min'], 1)[0] == 10, (k.pc.crash, k.pc.rd(ui, k.Y['saver_min'], 1)))
    k = ktest.KPC(None, roms={1: rom()})
    k.pc.boot_rom(1); k.settle(25)
    check('no drive A: and no C:: started, the ROM\'s settings', not k.crashed and k.pc.mode() == 0x40
          and has(k, 'ROM R:') and u8(k, 'setdrv') == 0, A.screen(k))
    k = ktest.KPC(floppy('rom_empty.img'), roms={1: rom()})
    k.pc.drives[0].empty = True
    k.pc.boot_rom(1); k.settle(40)
    check('no disk in A: and no C:: started, no error asked, the ROM\'s settings', not k.crashed and k.pc.mode() == 0x40
          and has(k, 'ROM R:') and u8(k, 'setdrv') == 0 and not has(k, 'Not ready'), A.screen(k))


def t_mdisk():
    print('== M: made again, with R: hooked before it')
    k = boot(ems_pages=88)
    k.key(CODE['U'])
    for _ in range(7): k.key(ktest.DOWN)                        # Temporary disk
    k.key(ktest.ENTER)                                          # the next size: M: made again
    k.key(ktest.ESC)
    check('M: made again: INT 21h 0Eh still counts to R:', u8(k, 'lastdrv') == 18)
    to_prompt(k)
    o = prompt(k, 'dir r:') + prompt(k, 'dir m:')
    check('R: and M: both there', 'LODE     SYS' in o and 'Volume in drive M' in o, o)


def t_menu():
    print('== the menu (Shift held at start-up)')
    k = ktest.KPC(floppy('rom_m.img'), roms={1: rom()})
    k.pc.wr(0, 0x417, [SHIFT]); k.pc.boot_rom(1); k.settle(10)
    s = k.pc.text_screen()
    check('Shift held: the menu', '1  Lodestone' in s and "2  Lodestone with the ROM's own settings" in s and '4  The floppy in A:' in s, s)
    check('no other boot ROM: no GRiD MS-DOS in it', '3  GRiD MS-DOS' not in s)
    k.key(ord('1')); k.settle(20)
    check('1: Lodestone', k.pc.mode() == 0x40 and has(k, 'Lodestone 0.6'))
    k = boot(ata=sysinfo_hd(('LODE.INI', b'SPLASH=0\r\n')), shift=True, keys=[ord('2')])
    check('2: the ROM\'s own settings (C:\\LODE.INI not read)', u8(k, 'setdrv') == 0 and TS.ON in [m[0] for m in k.pc.marks])
    if os.path.exists(MSDOS):
        ms = open(MSDOS, 'rb').read()
        k = ktest.KPC(floppy('rom_m3.img'), roms={0: ms, 1: rom()})
        k.pc.wr(0, 0x417, [SHIFT]); k.pc.boot_rom(1); k.settle(10)
        check('GRiD MS-DOS in the other socket: 3 offered', '3  GRiD MS-DOS' in k.pc.text_screen(), k.pc.text_screen())
        k.pc.keys.append(ord('3'))
        k.pc.run_until(lambda: k.pc.r('cs') >= 0x8000 and k.pc.r('cs') < 0xA000 or k.crashed, 5)
        check('3: MS-DOS\'s boot sector, as the BIOS starts it', k.pc.rd(0x8000, 0, 0x20000) == ms and k.pc.r('dl') == 0x72,
              '%04X:%04X' % (k.pc.r('cs'), k.pc.r('ip')))
    else:
        print('   (GRiD MS-DOS: skipped, no EPROM image)')
    other = mkrom.image(b'\xEB\xFE', sys_type=1, bootable=0, rom_id=0x1234)
    k = ktest.KPC(floppy('rom_m5.img'), roms={0: other, 1: rom()})
    k.pc.wr(0, 0x417, [SHIFT]); k.pc.boot_rom(1); k.settle(10)
    check('a GRiD application ROM (system type 1, not bootable) in the other socket: no 3', '1  Lodestone' in k.pc.text_screen()
          and '3  GRiD MS-DOS' not in k.pc.text_screen(), k.pc.text_screen())
    fl = floppy('rom_m4.img', A.SYS, LCMD)
    k = boot(fl, shift=True, keys=[ord('4')])
    check('4: the floppy (Lodestone from A:)', has(k, 'Floppy A:') and u8(k, 'bootdrv') == 0, A.screen(k))


def t_system():
    print('== System: Settings, and saving from a ROM start')
    k = boot(ata=sysinfo_hd(), ems_pages=88)
    k.key(CODE['U'])
    for _ in range(8): k.key(ktest.DOWN)
    s = A.screen(k)
    check('Settings: started from the ROM, the ROM\'s file, changes in C:', 'the ROM, R:' in s and "R:\\LODE.INI, the ROM's own" in s
          and 'C:\\LODE.INI (none yet)' in s, s)
    k.key(ktest.UP, ktest.UP)                                   # Screen saver
    k.key(ktest.ENTER)                                          # the next delay
    k.key(ktest.ESC)
    ini = hd_file(k, 'LODE.INI')
    check('a changed setting goes in C:\\LODE.INI, alone', ini is not None and b'SAVER=' in ini and b'MDISK' not in ini and b'SPLASH' not in ini, ini)
    check('the ROM untouched', k.pc.roms[1] == rom())
    k.key(CODE['U'])
    for _ in range(8): k.key(ktest.DOWN)
    k.key(ktest.ENTER)                                          # back to the ROM's: asks
    asked = any('Confirm' in l for l in k.band())
    k.key(ktest.ENTER)                                          # Return confirms
    check('Return: asks, then back to the ROM\'s (C:\\LODE.INI gone)', hd_file(k, 'LODE.INI') is None, (asked, k.band()))


def t_nosave():
    print('== started with the ROM\'s own settings: changes not saved over the file')
    k = boot(ata=sysinfo_hd(('LODE.INI', b'SAVER=10\r\nSPLASH=0\r\n')), shift=True, keys=[ord('2')])
    k.key(CODE['U'])
    for _ in range(6): k.key(ktest.DOWN)                        # Screen saver
    k.key(ktest.ENTER)
    said = ' '.join(k.band())
    k.key(ktest.ESC); k.key(ktest.ESC)
    check('a change is not saved, and it says so; C:\\LODE.INI as it was', hd_file(k, 'LODE.INI') == b'SAVER=10\r\nSPLASH=0\r\n'
          and 'not saved this time' in said, (said, hd_file(k, 'LODE.INI')))
    img = floppy('rom_b.img')
    b = floppy('rom_bb.img', A.SYS, LCMD)
    k = ktest.KPC(img, b, roms={1: rom()})
    k.pc.boot(1); k.settle(25)
    check('started from a floppy in B:: captures on B:, as before 0.6', u8(k, 'bootdrv') == 1 and u8(k, 'capdrv') == ord('B'), u8(k, 'capdrv'))


def t_paths():
    print('== programs found by PATH: C:\\LODE before R:')
    calc = open(os.path.join(GOS, 'apps', 'CALC.RUN'), 'rb').read()
    for tag, files in (('only on R:', ()), ('a copy in C:\\LODE', (('LODE\\CALC.RUN', calc),))):
        k = boot(ata=sysinfo_hd(*files), trace=True)
        k.dos.clear()
        k.key(CODE['K']); k.key(ktest.ESC)
        opened = [l for l in k.dos_log() if 'CALC.RUN' in l and ('AH=3D' in l or 'AH=4B' in l) and ' CF' not in l]
        where = 'C:\\LODE\\CALC.RUN' if files else 'R:\\CALC.RUN'
        check('CODE-K, %s: %s' % (tag, where), any(where in l for l in opened), k.dos_log()[-12:])


def rom_ini(ini):
    """ROM 1 as build.sh makes it, with another LODE.INI"""
    names = ['src/LODE.SYS', 'src/LODE.PIC', 'src/LCMD.COM', 'apps/SYSTEM.RUN', 'apps/WRITE.RUN', 'apps/CALC.RUN',
             'src/CALC.COM', 'fonts/TERMINUS.FNT', 'drivers/PS.PRN']
    files = [(os.path.basename(n), open(os.path.join(GOS, n), 'rb').read()) for n in names] + [('LODE.INI', ini)]
    return mkrom.volume(files, boot=open(os.path.join(GOS, 'src', 'ROMBOOT.BIN'), 'rb').read())[0]


def t_printer():
    print('== the printer driver from the ROM: PRINTER= found as PATH finds programs (C:\\LODE, then R:)')
    ps = open(os.path.join(GOS, 'drivers', 'PS.PRN'), 'rb').read()
    path = lambda k: k.rd('prn_path', 24).split(b'\0')[0]
    ini = ('LODE.INI', b'PRINTER=PS.PRN\r\n')
    k = boot(ata=sysinfo_hd(ini))
    check('PRINTER=PS.PRN in C:\\LODE.INI, none in C:\\LODE: R:\\PS.PRN', path(k) == b'R:\\PS.PRN', path(k))
    k.pc.tty.clear(); k.pc.lpt.clear(); k.pc.prtsc(); k.settle(8)
    out = bytes(k.pc.lpt)
    check('... PrtSc prints with it, read from the ROM (one beep)', out.startswith(b'%!PS') and out.endswith(b'showpage\n\x04')
          and ''.join(k.pc.tty).count('\x07') == 1, (out[:20], ''.join(k.pc.tty).count('\x07')))
    k = boot(ata=sysinfo_hd(ini, ('LODE\\PS.PRN', ps)))
    check('a copy in C:\\LODE: that one (C:\\LODE\\PS.PRN)', path(k) == b'C:\\LODE\\PS.PRN', path(k))
    # System, Devices, Return from the ROM: C:\LODE's drivers, then R:'s, then none
    k = boot(ata=sysinfo_hd(('LODE\\PCL.PRN', ps)))
    k.key(CODE['U'])
    for _ in range(3): k.key(ktest.DOWN)
    seen = []
    for _ in range(3):
        k.key(ktest.ENTER); seen.append(path(k))
    check('System from the ROM: Return steps C:\\LODE\\PCL.PRN, R:\\PS.PRN, then none', seen == [b'C:\\LODE\\PCL.PRN', b'R:\\PS.PRN', b''],
          seen)
    k.key(ktest.ESC)
    # the ROM's settings naming a driver: "none" chosen in System stays none
    r = rom_ini(b'PRINTER=PS.PRN\r\n')
    k = boot(roms={1: r}, ata=sysinfo_hd())
    check('the ROM\'s LODE.INI says PRINTER=PS.PRN: R:\\PS.PRN', path(k) == b'R:\\PS.PRN', path(k))
    k.key(CODE['U'])
    for _ in range(3): k.key(ktest.DOWN)
    k.key(ktest.ENTER)                                          # (past R:\PS.PRN: none)
    ini = hd_file(k, 'LODE.INI')
    check('none chosen: C:\\LODE.INI says PRINTER= (empty), so the ROM\'s line doesn\'t win', path(k) == b'' and
          ini == b'PRINTER=\r\n', (path(k), ini))
    k.key(ktest.ESC)
    k = boot(roms={1: r}, ata=pcemu.Ata(model='Conner Peripherals 120MB - CP30104H', cyls=70, heads=4, spt=17,
                                         disk=k.pc.ata.disk))
    check('... after a restart: still none', path(k) == b'', path(k))


def t_memory():
    print('== what DOS programs get (MEMSZ at the command prompt)')
    got = {}
    for tag, kw in (('floppies', {}), ('EMS', {'ems_pages': 88}), ('C:', {'ata': 1}), ('EMS, C:', {'ems_pages': 88, 'ata': 1})):
        for how in ('no ROM', 'ROM in, from A:', 'from the ROM'):
            kk = dict(kw)
            if 'ata' in kk: kk['ata'] = TS.hd()
            img = floppy('rom_mem.img', A.SYS, A.MEMSZ, LCMD)
            if how == 'no ROM':
                k = ktest.KPC(img, **kk); k.start(10)
            else:
                k = boot(img, sock=None if how == 'ROM in, from A:' else 1, **kk)
            to_prompt(k)
            m = re.search(r'([\d.]+) KB for programs', prompt(k, 'a:memsz'))
            got[tag, how] = m and float(m.group(1))
        print('   %-8s no ROM %s KB, the ROM in (started from A:) %s KB, started from the ROM %s KB'
              % (tag, got[tag, 'no ROM'], got[tag, 'ROM in, from A:'], got[tag, 'from the ROM']))
        n, f, r = got[tag, 'no ROM'], got[tag, 'ROM in, from A:'], got[tag, 'from the ROM']
        check('%s: R: costs DOS programs 0.6 KB at most (its module, and from the ROM a longer PATH in each program'"'"'s environment)' % tag,
              n and f and r and round(n - f, 1) <= 0.5 and round(n - r, 1) <= 0.6, (n, f, r))   # (MEMSZ's tenths)
    return got


if __name__ == '__main__':
    t0 = time.time()
    if 'nobuild' not in sys.argv: build()
    only = [a for a in sys.argv[1:] if a.startswith('t_')]
    for t in (t_image, t_bios, t_boot, t_read, t_write, t_floppy, t_settings, t_mdisk, t_menu, t_system, t_nosave, t_paths, t_printer, t_memory, t_rom2):
        if not only or t.__name__ in only: t()
    bad = [n for n, ok in results if not ok]
    print('\n%d checks, %d failed%s   (%.0f s)' % (len(results), len(bad), (': ' + '; '.join(bad)) if bad else '', time.time() - t0))
    sys.exit(1 if bad else 0)
