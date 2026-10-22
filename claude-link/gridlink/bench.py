"""Measure the GRiD <-> Pi link as Claude Code sees it.

    venv/bin/python -m gridlink.bench                 64 KB each way through M:, 20 round trips
    venv/bin/python -m gridlink.bench --size 128 --to A:\\BENCH.BIN --trips 50

Run it on the Pi while gridlink is serving and CLAUDE /T is up on the GRiD (the tools socket exists only in
Term).  It talks to gridlink over the same socket as Claude Code's MCP server, so the numbers include
everything a real copy goes through: GLP frames, the bridge, CLAUDE.COM and the GRiD's DOS calls.

Uses ~/grid/bench.bin and ~/grid/bench.back on the Pi and one file on the GRiD, which it deletes afterwards.
Put the GRiD file on M: (the RAM disk) to time the link and not the floppy.
"""
import argparse, os, sys, time
from .mcp import call_gridlink, socket_path


def tool(sock, name, args):
    t0 = time.monotonic()
    r = call_gridlink(sock, name, args)
    dt = time.monotonic() - t0
    msg = ' '.join(c.get('text', '') for c in r.get('content', []))
    if r.get('isError'): sys.exit('%s failed: %s' % (name, msg))
    return dt, msg


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gridlink.bench', description=__doc__.split('\n')[0])
    ap.add_argument('--size', type=int, default=64, help='KB to send each way (default 64)')
    ap.add_argument('--to', default='M:\\BENCH.BIN', help='the GRiD file (default M:\\BENCH.BIN)')
    ap.add_argument('--trips', type=int, default=20, help='small requests for the round-trip time (default 20)')
    ap.add_argument('--dir', default='~/grid', help="Claude Code's directory on the Pi (default ~/grid)")
    a = ap.parse_args(argv)
    sock = socket_path()
    if not os.path.exists(sock):
        sys.exit('no gridlink socket at %s: is gridlink running, with CLAUDE /T up on the GRiD?' % sock)
    d = os.path.expanduser(a.dir)
    src, back = os.path.join(d, 'bench.bin'), os.path.join(d, 'bench.back')
    n = a.size * 1024
    data = os.urandom(n)                      # every byte value, nothing to compress
    with open(src, 'wb') as f: f.write(data)

    rt = [tool(sock, 'grid_info', {})[0] for _ in range(a.trips)]
    rt.sort()
    print('round trip (grid_info, %d): best %.1f ms, median %.1f ms, worst %.1f ms'
          % (a.trips, rt[0] * 1e3, rt[len(rt) // 2] * 1e3, rt[-1] * 1e3))

    up, _ = tool(sock, 'grid_change_files', {'action': 'copy_to_grid', 'path': src, 'to': a.to})
    print('Pi -> GRiD: %d bytes in %.2f s = %.1f KB/s' % (n, up, n / up / 1024))
    down, _ = tool(sock, 'grid_change_files', {'action': 'copy_from_grid', 'path': a.to, 'to': back})
    print('GRiD -> Pi: %d bytes in %.2f s = %.1f KB/s' % (n, down, n / down / 1024))
    with open(back, 'rb') as f: ok = f.read() == data
    print('copy back: %s' % ('every byte right' if ok else 'DIFFERENT from what was sent'))
    tool(sock, 'grid_change_files', {'action': 'delete', 'path': a.to})
    for p in (src, back):
        try: os.unlink(p)
        except OSError: pass
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
