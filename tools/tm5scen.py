import sys, collections, tm5trace as T, sim7210 as S, dosemu as D
scen = {
 'files':  "x,4,3,s:A:\\T1,x,4,4,s:A:\\T1,x,x,4,1,s:A:\\D1,x,x,4,2,s:A:\\D1,x,x,4,7,x,x,4,5,x,x,x",
 'detect': "x,1,A,x,x,ESC",
 'single': "x,1,A,x,x,ESC,2,1,x,x,x,x",
 'graph':  "x,2,3,x,x,ESC,x,ESC",
 'cont':   "x,1,A,x,x,ESC,2,2,x,x,x,x,ESC,x,x",
 'math':   "x,2,4,x,x,ESC,x",
 'exit':   "x,0,x,x",
}
union = collections.Counter(); first = {}
for name, ks in scen.items():
    keys = []
    for k in ks.split(','):
        keys += ([ord(c) for c in k[2:]] + [0x1C0D]) if k.startswith('s:') else [T.K(k)]
    m = T.Tracer(S.bus()); m.setup(keys)
    D.Machine.run(m, 'GRIDGPIB.COM', seg=0x0800)
    m.log.clear(); m.order.clear(); m.tracking = True
    m.load_exe('TM5000G.EXE', 0x1000); m.go(maxins=400_000_000)
    print('##', name, 'exit', m.exitcode, ''.join(m.out)[-120:].replace('\n',' '), '| files', {k: len(v) for k, v in m.files.items()})
    print('   last screen:', ' / '.join(l.strip() for l in m.screens[-1].split('\n') if l.strip())[:300] if m.screens else '')
    for k in m.order:
        if k not in first: first[k] = name
    union.update(m.log)
print('\n=== union of interrupt calls ===')
for k in sorted(union, key=lambda k: (k[0], k[1], k[2])): print('%-8s %-9s %-6s x%-8d first in %s' % (k[0], k[1], k[2], union[k], first[k]))
