"""Measure the GRiD <-> Pi link as Claude Code sees it.

    venv/bin/python -m gridlink.bench                 64 KB each way through M:, 20 round trips
    venv/bin/python -m gridlink.bench --size 128 --to A:\\BENCH.BIN --trips 50
    venv/bin/python -m gridlink.bench --sweep 246,512,1024,2048,4096   Pi -> GRiD frame sizes, one after another
    venv/bin/python -m gridlink.bench --size 32 --trace     where each copy's time goes, gap by gap
    venv/bin/python -m gridlink.bench --usb                 also the Pi -> Pico USB speed alone

Run it on the Pi while gridlink is serving and CLAUDE /T is up on the GRiD (the tools socket exists only in
Term).  It talks to gridlink over the same socket as Claude Code's MCP server, so the numbers include
everything a real copy goes through: GLP frames, the bridge, CLAUDE.COM and the GRiD's DOS calls.

Uses ~/grid/bench.bin and ~/grid/bench.back on the Pi and one file on the GRiD, which it deletes afterwards.
Put the GRiD file on M: (the RAM disk) to time the link and not the floppy.
"""
import argparse, collections, json, os, sys, time
from .mcp import call_gridlink, socket_path


def tool(sock, name, args):
    t0 = time.monotonic()
    r = call_gridlink(sock, name, args)
    dt = time.monotonic() - t0
    msg = ' '.join(c.get('text', '') for c in r.get('content', []))
    if r.get('isError'): sys.exit('%s failed: %s' % (name, msg))
    return dt, msg


def link(sock, **args):
    _, msg = tool(sock, '_link', args)
    return json.loads(msg)


def timeline(tr, title, top=14):
    """Where a copy's time went: the gaps between successive events (the Pi's frames, the GRiD's frames as
    gridlink got them, the bridge's GPIB events as they reached the Pi), summed by what came before and after."""
    gaps = collections.defaultdict(list)
    for (t0, e0), (t1, e1) in zip(tr, tr[1:]):
        gaps[(e0, e1)].append(t1 - t0)
    span = tr[-1][0] - tr[0][0] if len(tr) > 1 else 0
    print('%s: %d events over %.2f s' % (title, len(tr), span))
    print('  %-22s %-22s %5s %9s %8s %6s' % ('after', 'until', 'times', 'median', 'total', 'share'))
    for (e0, e1), d in sorted(gaps.items(), key=lambda kv: -sum(kv[1]))[:top]:
        d.sort()
        print('  %-22s %-22s %5d %6.1f ms %6.2f s %5.1f%%' % (e0, e1, len(d), d[len(d) // 2] * 1e3, sum(d),
                                                              100 * sum(d) / span if span else 0))


def traced(sock, a, title, name, args):
    if not a.trace: return tool(sock, name, args)
    link(sock, trace='start')
    try:
        r = tool(sock, name, args)
    finally:
        tr = link(sock, trace='stop').get('trace', [])
    timeline(tr, title)
    return r


def copies(sock, a, src, back, data, quiet=False):
    n = len(data)
    up, _ = traced(sock, a, 'Pi -> GRiD', 'grid_change_files', {'action': 'copy_to_grid', 'path': src, 'to': a.to})
    down, _ = traced(sock, a, 'GRiD -> Pi', 'grid_change_files',
                     {'action': 'copy_from_grid', 'path': a.to, 'to': back})
    with open(back, 'rb') as f: ok = f.read() == data
    tool(sock, 'grid_change_files', {'action': 'delete', 'path': a.to})
    if quiet: return up, down, ok
    print('Pi -> GRiD: %d bytes in %.2f s = %.1f KB/s' % (n, up, n / up / 1024))
    print('GRiD -> Pi: %d bytes in %.2f s = %.1f KB/s' % (n, down, n / down / 1024))
    print('copy back: %s' % ('every byte right' if ok else 'DIFFERENT from what was sent'))
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(prog='gridlink.bench', description=__doc__.split('\n')[0])
    ap.add_argument('--size', type=int, default=64, help='KB to send each way (default 64)')
    ap.add_argument('--to', default='M:\\BENCH.BIN', help='the GRiD file (default M:\\BENCH.BIN)')
    ap.add_argument('--trips', type=int, default=20, help='small requests for the round-trip time (default 20)')
    ap.add_argument('--dir', default='~/grid', help="Claude Code's directory on the Pi (default ~/grid)")
    ap.add_argument('--trace', action='store_true', help='show where each copy spends its time')
    ap.add_argument('--usb', action='store_true', help="time the Pi -> Pico USB with PINGs, before the copies")
    ap.add_argument('--sweep', help='Pi -> GRiD payload sizes to try, comma-separated (each capped by what the '
                                    'GRiD and the bridge take); the link goes back to its own size after')
    a = ap.parse_args(argv)
    sock = socket_path()
    if not os.path.exists(sock):
        sys.exit('no gridlink socket at %s: is gridlink running, with CLAUDE /T up on the GRiD?' % sock)
    d = os.path.expanduser(a.dir)
    src, back = os.path.join(d, 'bench.bin'), os.path.join(d, 'bench.back')
    n = a.size * 1024
    data = os.urandom(n)                      # every byte value, nothing to compress
    with open(src, 'wb') as f: f.write(data)

    info = link(sock)
    print('link: %s; Pi -> GRiD frames up to %d payload bytes (the GRiD takes %d), GRiD -> Pi up to %d'
          % (info['bridge'], info['maxpay'], info['grid_rx'], info['grid_maxpay']))
    if a.usb:
        print('bridge USB (PINGs from the Pi, answered by the Pico):')
        for count, size in ((1, 1), (20, 1), (1, 512), (4, 512), (40, 512)):
            r = [link(sock, usb=[count, size])['usb'] for _ in range(5)]
            if None in r:
                print('  %2d x %3d bytes: no answer' % (count, size)); continue
            best = min(r)
            print('  %2d x %3d bytes: best %6.2f ms%s' % (count, size, best * 1e3,
                  '  = %.0f KB/s' % (count * size / best / 1024) if count * size >= 2048 else ''))

    tool(sock, 'grid_info', {})                       # wake the link: the first call waits for an idle POLL
    rt = [tool(sock, 'grid_info', {})[0] for _ in range(a.trips)]
    rt.sort()
    print('round trip (grid_info, %d): best %.1f ms, median %.1f ms, worst %.1f ms'
          % (a.trips, rt[0] * 1e3, rt[len(rt) // 2] * 1e3, rt[-1] * 1e3))

    ok = True
    if not a.sweep:
        ok = copies(sock, a, src, back, data)
    else:
        caps = [int(x) for x in a.sweep.split(',') if x.strip()]
        print('%8s %8s %12s %12s' % ('asked', 'frames', 'Pi->GRiD', 'GRiD->Pi'))
        try:
            for c in caps:
                got = link(sock, frame_cap=c)['maxpay']
                up, down, good = copies(sock, a, src, back, data, quiet=True)
                ok = ok and good
                print('%8d %8d %9.1f KB/s %9.1f KB/s%s' % (c, got, n / up / 1024, n / down / 1024,
                                                          '' if good else '  COPY DIFFERENT'))
        finally:
            link(sock, frame_cap=0)
    for p in (src, back):
        try: os.unlink(p)
        except OSError: pass
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
