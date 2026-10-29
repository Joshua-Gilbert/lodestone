"""hot.py's counts carried to other builds: the share of taken entries landing on
odd addresses per workload, and the hot labels' parity in each build.
    python3 bench/evalpar.py PROF.MAP OTHER.MAP... -- HOT.json...
PROF.MAP: the LODE.MAP of the build hot.py ran on; each OTHER.MAP (an older
build, the padded one) gets each counted address carried as label + offset
(exact for the labels, approximate inside code that changed).  Name the
HOT.json files <anything>_<workload>.json.  TOP=n labels (default 40, by
count with the workloads weighed the same).  SECTION=ui: the UI's (section
ui, hot.py's "ui_taken"); SECTION=claude: CLAUDE.COM's (CLAUDE.MAPs,
"cl_taken"); SECTION=rstub: the CLAUDE /R stub's ("st_taken"); SECTION=rcon:
resident Claude's console's (RCON.MAPs, "rc_taken"); SECTION=lcmd: LCMD.COM's
(src/LCMD.MAPs, "lc_taken"); SECTION=app APP=NAME: a .RUN's (its .MAPs from
mkrun.py -l, "ap_taken"[NAME]).
Output: a table per workload, then label, count (weighed, raw) and its parity
(E/O) in each map."""
import re, sys, json, collections, bisect, os
SEC = os.environ.get('SECTION', '.text')
KEY = {'ui': 'ui_taken', 'claude': 'cl_taken', 'rstub': 'st_taken', 'rcon': 'rc_taken', 'lcmd': 'lc_taken',
       'app': 'ap_taken'}.get(SEC, 'taken')
APP = os.environ.get('APP') if SEC == 'app' else None
if SEC in ('claude', 'rcon', 'lcmd', 'app'): SEC = '.text'      # (its section in CLAUDE.MAP, RCON.MAP, LCMD.MAP, a .RUN's)

def load(p):
    syms, sec = [], None
    for l in open(p, encoding='latin-1'):
        m = re.match(r'---- Section (\S+)', l)
        if m: sec = m.group(1); continue
        m = re.match(r'\s+([0-9A-F]+)\s+([0-9A-F]+)\s+(\S+)\s*$', l)
        if m and sec == SEC: syms.append((int(m.group(2), 16), m.group(3)))
    return sorted(syms)

def main():
    if '--' not in sys.argv: sys.exit(__doc__)
    i = sys.argv.index('--')
    maps, hots = sys.argv[1:i], sys.argv[i + 1:]
    prof = load(maps[0]); pa = [a for a, _ in prof]
    others = [(os.path.basename(m), dict((n, a) for a, n in load(m))) for m in maps[1:]]
    def carry(a, m):                            # the nearest label at or below, in map m
        j = bisect.bisect_right(pa, a) - 1
        while j >= 0:
            if prof[j][1] in m: return m[prof[j][1]] + a - prof[j][0]
            j -= 1
    per = {os.path.basename(f).rsplit('_', 1)[-1].split('.')[0]:
           collections.Counter({int(k): v for k, v in (json.load(open(f))[KEY].get(APP, {}) if APP else
                                                        json.load(open(f))[KEY]).items()}) for f in hots}
    per = {w: c for w, c in per.items() if c}   # (a .RUN a workload doesn't run)
    cols = [os.path.basename(maps[0])] + [n for n, _ in others]
    print('%-8s' % 'odd' + ''.join('%14s' % c[:13] for c in cols))
    for w, c in per.items():
        t = sum(c.values())
        r = [sum(v for a, v in c.items() if a & 1)] + [sum(v for a, v in c.items() if (carry(a, m) or 0) & 1) for _, m in others]
        print('%-8s' % w + ''.join('%13.1f%%' % (100.0 * o / t) for o in r) + '   (%d entries)' % t)
    by = collections.defaultdict(list)
    for a, n in prof: by[a].append(n)
    norm, raw = collections.Counter(), collections.Counter()
    for c in per.values():
        t = sum(c.values())
        for a, v in c.items(): norm[a] += v * 250000 // t; raw[a] += v
    p = lambda x: '-' if x is None else 'O' if x & 1 else 'E'
    print('\n%7s %7s  %-30s %s' % ('weighed', 'raw', 'label', ' '.join(c[:8] for c in cols)))
    for a in sorted((a for a in norm if a in by), key=lambda a: -norm[a])[:int(os.environ.get('TOP', 40))]:
        n = by[a][0]
        print('%7d %7d  %-30s %s' % (norm[a], raw[a], '/'.join(by[a])[:30], '        '.join([p(a)] + [p(m.get(n)) for _, m in others])))

if __name__ == '__main__':
    main()
