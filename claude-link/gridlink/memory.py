"""Client side of the Anthropic memory tool (memory_20250818), kept in a
directory on the Pi: Claude's notes that survive between sessions."""
import os, shutil
from pathlib import Path

ROOT = '/memories'


class Memory:
    def __init__(s, base):
        s.base = Path(os.path.expanduser(base)).resolve()
        s.base.mkdir(parents=True, exist_ok=True)

    def _path(s, p):
        if not p or not (p == ROOT or p.startswith(ROOT + '/')):
            raise ValueError('Error: paths must be inside /memories')
        if '..' in p.split('/') or '%2e' in p.lower():
            raise ValueError('Error: invalid path %s' % p)
        real = (s.base / p[len(ROOT):].lstrip('/')).resolve()
        if real != s.base and s.base not in real.parents:
            raise ValueError('Error: invalid path %s' % p)
        return real

    @staticmethod
    def _size(n):
        for unit in ('', 'K', 'M'):
            if n < 1024: return ('%d' % n if unit == '' else '%.1f' % n) + unit
            n /= 1024.0
        return '%.1fG' % n

    def execute(s, inp):
        try:
            return s._execute(inp)
        except ValueError as e:
            return str(e), True
        except OSError as e:
            return 'Error: %s' % e, True

    def _execute(s, inp):
        cmd = inp.get('command'); p = inp.get('path', '')
        if cmd == 'view':
            real = s._path(p)
            if real.is_dir():
                lines = ['%s\t%s' % (s._size(sum(f.stat().st_size for f in real.rglob('*') if f.is_file())), p)]
                for f in sorted(real.rglob('*')):
                    rel = f.relative_to(real)
                    if len(rel.parts) > 2 or any(x.startswith('.') for x in rel.parts): continue
                    lines.append('%s\t%s/%s' % (s._size(f.stat().st_size if f.is_file() else 0),
                                                p.rstrip('/'), rel.as_posix()))
                return ("Here're the files and directories up to 2 levels deep in %s, excluding hidden "
                        "items and node_modules:\n" % p) + '\n'.join(lines), False
            if not real.exists():
                return 'The path %s does not exist. Please provide a valid path.' % p, True
            text = real.read_text(errors='replace')
            lines = text.split('\n')
            if text.endswith('\n'): lines.pop()
            rng = inp.get('view_range')
            start = 1
            if rng:
                start = max(1, int(rng[0])); end = int(rng[1]) if len(rng) > 1 else -1
                lines = lines[start - 1:(None if end == -1 else end)]
            body = '\n'.join('%6d\t%s' % (start + i, l) for i, l in enumerate(lines))
            if len(body) > 16000: body = body[:16000] + '\n[truncated; use view_range]'
            return "Here's the content of %s with line numbers:\n%s" % (p, body), False
        if cmd == 'create':
            real = s._path(p)
            if real == s.base: return 'Error: cannot write the memory root', True
            real.parent.mkdir(parents=True, exist_ok=True)
            real.write_text(inp.get('file_text', ''))
            return 'File created successfully at: %s' % p, False
        if cmd == 'str_replace':
            real = s._path(p)
            if not real.is_file():
                return 'Error: The path %s does not exist. Please provide a valid path.' % p, True
            text = real.read_text(errors='replace'); old = inp.get('old_str', ''); new = inp.get('new_str', '')
            n = text.count(old) if old else 0
            if n == 0:
                return 'No replacement was performed, old_str `%s` did not appear verbatim in %s.' % (old, p), True
            if n > 1:
                nums = [str(text[:i].count('\n') + 1) for i in _find_all(text, old)]
                return ('No replacement was performed. Multiple occurrences of old_str `%s` in lines: %s. '
                        'Please ensure it is unique' % (old, ', '.join(nums))), True
            real.write_text(text.replace(old, new, 1))
            return 'The memory file has been edited.', False
        if cmd == 'insert':
            real = s._path(p)
            if not real.is_file(): return 'Error: The path %s does not exist' % p, True
            lines = real.read_text(errors='replace').split('\n')
            n = int(inp.get('insert_line', 0))
            if n < 0 or n > len(lines):
                return ('Error: Invalid `insert_line` parameter: %d. It should be within the range of lines '
                        'of the file: [0, %d]' % (n, len(lines))), True
            lines[n:n] = inp.get('insert_text', '').rstrip('\n').split('\n')
            real.write_text('\n'.join(lines))
            return 'The file %s has been edited.' % p, False
        if cmd == 'delete':
            real = s._path(p)
            if real == s.base: return 'Error: cannot delete the /memories directory itself', True
            if not real.exists(): return 'Error: The path %s does not exist' % p, True
            shutil.rmtree(real) if real.is_dir() else real.unlink()
            return 'Successfully deleted %s' % p, False
        if cmd == 'rename':
            old = inp.get('old_path', ''); new = inp.get('new_path', '')
            ro, rn = s._path(old), s._path(new)
            if ro == s.base: return 'Error: cannot rename the /memories directory itself', True
            if not ro.exists(): return 'Error: The path %s does not exist' % old, True
            if rn.exists(): return 'Error: The destination %s already exists' % new, True
            rn.parent.mkdir(parents=True, exist_ok=True)
            ro.rename(rn)
            return 'Successfully renamed %s to %s' % (old, new), False
        return 'Error: unknown command %s' % cmd, True

    def listing(s):
        files = [f for f in sorted(s.base.rglob('*')) if f.is_file()]
        return ['%s (%s)' % (f.relative_to(s.base).as_posix(), s._size(f.stat().st_size)) for f in files]


def _find_all(text, sub):
    i = text.find(sub)
    while i >= 0:
        yield i
        i = text.find(sub, i + 1)
