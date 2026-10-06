# Mimic the Arduino IDE: add prototypes for every top-level function in an .ino
import re, sys
src = open(sys.argv[1]).read()
lines = src.split('\n')
pat = re.compile(r'^((?:static\s+|inline\s+)*(?:unsigned\s+|signed\s+|const\s+)?[A-Za-z_][\w:<>\*\s&]*?[\s\*&]+)([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*\{')
protos = []; first = None
depth = 0
for i, l in enumerate(lines):
    if True:
        m = pat.match(l)
        if m and first is None and m.group(2) in ('setup', 'loop'): first = i
        if m and m.group(2) not in ('if', 'while', 'for', 'switch', 'setup', 'loop'):
            ret = m.group(1).strip()
            if not ret.startswith('#'):
                protos.append('%s %s(%s);' % (ret, m.group(2), re.sub(r'=\s*[^,)]+', '', m.group(3))))
                if first is None: first = i
    depth += l.count('{') - l.count('}')
lines.insert(first, '\n'.join(protos))
open(sys.argv[2], 'w').write('\n'.join(lines))
print(len(protos), 'prototypes inserted at line', first)
