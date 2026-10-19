#!/usr/bin/env python3
"""Cut multitasking's resident part (KMT.INC's section mtt, the last in the
file) off LODE.SYS into LODEMT.SYS, and write its checksum into LODE.SYS's
mt_sum, which mt_boot compares (so a LODEMT.SYS from another build is
refused).  The checksum: a 16-bit word, rotated left one bit, then the next
byte added.  Positions come from LODE.MAP (the Real column is the place in
the file).  A build without it (-dNOTC) has no mt_tstart: nothing to do.
python3 mkmt.py [src/LODE.SYS src/LODE.MAP src/LODEMT.SYS]"""
import os, re, struct, sys

def real_and_virtual(path):
    syms = {}
    for line in open(path):
        m = re.match(r'\s*([0-9A-F]+)\s+([0-9A-F]+)\s+(\S+)\s*$', line)
        if m: syms.setdefault(m.group(3), (int(m.group(1), 16), int(m.group(2), 16)))
    return syms

def checksum(data):
    s = 0
    for b in data:
        s = ((s << 1) | (s >> 15)) & 0xFFFF
        s = (s + b) & 0xFFFF
    return s

def main(sysf, mapf, outf):
    syms = real_and_virtual(mapf)
    if 'mt_tstart' not in syms:
        print('mkmt: no multitasking in this build (-dNOTC): LODE.SYS as it is'); return
    start, end, sumat = syms['mt_tstart'][0], syms['mt_tend'][0], syms['mt_sum'][0]
    data = open(sysf, 'rb').read()
    if len(data) != end:
        sys.exit('mkmt: LODE.SYS is %d bytes, not %d (its multitasking part, from %d, '
                 'must be the end of the file: cut off already?)' % (len(data), end, start))
    if not sumat + 2 <= start:
        sys.exit('mkmt: mt_sum (%d) is not in the part that stays' % sumat)
    part = data[start:end]
    kept = bytearray(data[:start])
    struct.pack_into('<H', kept, sumat, checksum(part))
    open(outf, 'wb').write(part)
    open(sysf, 'wb').write(bytes(kept))
    print('mkmt: LODE.SYS %d bytes, LODEMT.SYS %d bytes (checksum %04Xh)' % (len(kept), len(part), checksum(part)))

if __name__ == '__main__':
    a = sys.argv[1:] or ['src/LODE.SYS', 'src/LODE.MAP', 'src/LODEMT.SYS']
    main(*a)
