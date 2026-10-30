"""The tools Claude uses, their permission rules, and how each call is shown
on the GRiD (Claude Code style: "● Read(A:\\FOO.C)" then "  ⎿ Read 40 lines")."""
import difflib, os, unicodedata
from pathlib import Path
from . import glp, keys as K, screen
from .grid import GridError, is_grid_path, norm, errtext

BULLET = chr(glp.GL_BULLET) + ' '
CORNER = '  ' + chr(glp.GL_CORNER) + '  '
INDENT = '     '

REJECTED = ("The user doesn't want to proceed with this tool use. The tool use was rejected "
            "(eg. if it was a file edit, the new_str was NOT written to the file). STOP what you "
            "are doing and wait for the user to tell you how to proceed.")
MAX_VIEW = 20000


class Rejected(Exception):
    pass


def to_cp437(text):
    """Text for a DOS file: CP437 where possible, ASCII look-alikes otherwise."""
    out = []
    for ch in text:
        try:
            ch.encode('cp437'); out.append(ch)
        except UnicodeEncodeError:
            d = unicodedata.normalize('NFKD', ch)
            a = ''.join(c for c in d if ord(c) < 128)
            out.append(a or {'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
                             '\u2013': '-', '\u2014': '--', '\u2026': '...', '\u2192': '->'}.get(ch, '?'))
    return ''.join(out).encode('cp437')


def numbered(lines, start=1):
    return '\n'.join('%6d\t%s' % (start + i, l) for i, l in enumerate(lines))


def looks_binary(data):
    if not data: return False
    sample = data[:4096]
    bad = sum(1 for b in sample if b < 9 or (13 < b < 32 and b != 26))
    return bad > len(sample) // 20


def hexdump(data, limit=256):
    rows = []
    for i in range(0, min(len(data), limit), 16):
        chunk = data[i:i + 16]
        rows.append('%04X  %-48s %s' % (i, ' '.join('%02X' % b for b in chunk),
                                        ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)))
    return '\n'.join(rows)


class Doc:
    """A text file as Claude sees it (LF line ends) plus how to write it back."""
    def __init__(s, text, crlf, where):
        s.text, s.crlf, s.where = text, crlf, where

    def encode(s, text):
        if s.where == 'grid':
            body = text.replace('\r\n', '\n')
            if s.crlf: body = body.replace('\n', '\r\n')
            return to_cp437(body)
        return text.encode('utf-8')


class Tools:
    def __init__(s, session):
        s.S = session

    # ---- definitions ---------------------------------------------------
    def definitions(s):
        c = s.S.cfg
        defs = [
            {'type': 'text_editor_20250728', 'name': 'str_replace_based_edit_tool',
             'max_characters': MAX_VIEW},
            {'name': 'grid_command',
             'description': (
                 "Run a DOS command line or program on the GRiD (through COMMAND.COM /C, in the "
                 "GRiD's current directory). With capture=true (default) the program's text output "
                 "is redirected to a file and returned to you; use that for commands like DIR, TYPE, "
                 "CHKDSK or batch files. Programs that draw their own screen (TM5000G, editors, games) "
                 "need capture=false: drive them with `keys` and look at them with `screenshot`. "
                 "The user can see the program and may type into it too. Runs until the program exits."),
             'input_schema': {'type': 'object', 'properties': {
                 'command': {'type': 'string', 'description': 'DOS command line, e.g. "DIR A:\\\\TM5000" or "TM5000G"'},
                 'keys': {'type': 'string', 'description': (
                     'Keystrokes to type into the program, in order. Plain characters type themselves; '
                     'named keys in braces: {ENTER} {ESC} {TAB} {BKSP} {UP} {DOWN} {LEFT} {RIGHT} {HOME} '
                     '{END} {PGUP} {PGDN} {INS} {DEL} {F1}..{F10} {ALT+X} {CTRL+X} {SHIFT+F1}; {WAIT 2.5} '
                     'pauses (seconds); {SNAP} takes a screenshot at that moment (the program is waiting '
                     'for a key then). When the script ends the real keyboard takes over, so end with the '
                     "keys that quit the program unless the user will.")},
                 'capture': {'type': 'boolean', 'description': 'Return the text output (default true).'},
                 'screenshot': {'type': 'boolean', 'description': 'Also capture the screen when the program exits '
                                                            '(unless a {SNAP} in keys took one; default false).'},
                 'timeout': {'type': 'integer', 'description': 'Seconds to wait for the program (default 900).'},
             }, 'required': ['command']}},
            {'name': 'grid_files',
             'description': (
                 "File operations on the GRiD, and copies between the GRiD and the Pi. Paths on the "
                 "GRiD are DOS paths with a drive letter (A:\\\\TM5000\\\\DATA.TXT, 8.3 names); paths on the "
                 "Pi are absolute POSIX paths. Actions: list (directory with sizes and dates), info, "
                 "delete, rename (to = new name), mkdir, rmdir, free (space on the drive of path), "
                 "copy_to_grid (path = Pi file, to = GRiD file), copy_from_grid (path = GRiD file, to = Pi file). "
                 "Copies are binary-safe; the link runs at roughly 5-10 KB/s, so keep them modest."),
             'input_schema': {'type': 'object', 'properties': {
                 'action': {'type': 'string', 'enum': ['list', 'info', 'delete', 'rename', 'mkdir', 'rmdir',
                                                       'free', 'copy_to_grid', 'copy_from_grid']},
                 'path': {'type': 'string'}, 'to': {'type': 'string'},
             }, 'required': ['action', 'path']}},
            {'name': 'gpib',
             'description': (
                 "Talk to instruments on the GRiD's GPIB bus (the GRiD is controller at address 21; "
                 "this link's own bridge sits at address %d). Actions: query (send command, read reply), "
                 "write (send command only), read (read a reply), poll (serial poll status byte), "
                 "clear (selected device clear), trigger (GET), local (go to local), remote, scan "
                 "(list responding addresses). Commands get CR LF and EOI appended unless "
                 "terminator says otherwise. Anything that changes an instrument's state needs the "
                 "user's approval; power supplies drive real circuits, so never change their outputs "
                 "unless asked." % c.address),
             'input_schema': {'type': 'object', 'properties': {
                 'action': {'type': 'string', 'enum': ['query', 'write', 'read', 'poll', 'clear', 'trigger',
                                                       'local', 'remote', 'scan']},
                 'address': {'type': 'integer', 'minimum': 0, 'maximum': 30},
                 'command': {'type': 'string'},
                 'terminator': {'type': 'string', 'enum': ['crlf', 'lf', 'none']},
                 'timeout_ms': {'type': 'integer', 'description': 'Per-byte read timeout (default 2000).'},
                 'max_bytes': {'type': 'integer', 'description': 'Largest reply to accept (default 4096).'},
             }, 'required': ['action']}},
            {'type': 'bash_20250124', 'name': 'bash'},
            {'type': 'memory_20250818', 'name': 'memory'},
        ]
        if c.web:
            defs.append({'type': 'web_search_20260318', 'name': 'web_search', 'max_uses': 8})
            defs.append({'type': 'web_fetch_20260318', 'name': 'web_fetch', 'max_uses': 8})
        return defs

    # ---- display -------------------------------------------------------
    def head(s, label, arg):
        s.S.show(s.S.render.block('%s(%s)' % (label, arg), first=BULLET, rest='  ', gap=True))

    def result(s, text):
        s.S.show(s.S.render.block(text, first=CORNER, rest=INDENT))

    def output(s, text, lines=6):
        if not text.strip():
            s.result('(no output)'); return
        rows = text.rstrip('\n').split('\n')
        s.S.show(s.S.render.verbatim(rows[0], prefix=CORNER))
        if len(rows) > 1:
            s.S.show(s.S.render.verbatim('\n'.join(rows[1:]), prefix=INDENT, max_lines=lines - 1))

    def diff_lines(s, old_lines, new_lines, start):
        """Claude Code style: line numbers with - and + markers."""
        out = []
        sm = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                for k in range(i1, i2): out.append('%4d   %s' % (start + k, old_lines[k]))
                continue
            for k in range(i1, i2): out.append('%4d - %s' % (start + k, old_lines[k]))
            for k in range(j1, j2): out.append('%4d + %s' % (start + j1 + (k - j1), new_lines[k]))
        return out

    def diff(s, lines, most=14):
        if len(lines) > most:
            lines = lines[:most - 1] + ['     ' + chr(glp.GL_ELLIPSIS) + ' %d more lines' % (len(lines) - most + 1)]
        if lines: s.S.show(s.S.render.verbatim('\n'.join(lines), prefix=INDENT))

    @staticmethod
    def ask_detail(lines, most=5):
        """The diff inside the permission box (5 rows of 64 columns)."""
        if len(lines) > most:
            lines = lines[:most - 1] + ['     ' + chr(glp.GL_ELLIPSIS) + ' %d more lines' % (len(lines) - most + 1)]
        return '\n'.join(l[:64] for l in lines)

    # ---- permissions ----------------------------------------------------
    def allow(s, kind, key, question, detail='', always=''):
        """Ask the user unless the mode or an earlier "always" covers it.
        kinds: edit (file contents), files (create/rename/copy), delete,
        cmd (DOS program), gpib (instrument address), bash (first word)."""
        S = s.S
        if S.mode == 'auto': return
        if kind in ('edit', 'files') and S.mode == 'edits': return
        if (kind, key) in S.allowed or (kind, '*') in S.allowed: return
        ans = S.ask(question, detail, always)
        if ans == 'a': S.allowed.add((kind, key))
        elif ans != 'y': raise Rejected()

    # ---- dispatch ------------------------------------------------------
    def execute(s, name, inp):
        try:
            if name == 'str_replace_based_edit_tool': return s.editor(inp)
            if name == 'grid_command': return s.grid_command(inp)
            if name == 'grid_files': return s.grid_files(inp)
            if name == 'gpib': return s.gpib(inp)
            if name == 'bash': return s.bash(inp)
            if name == 'memory': return s.memory(inp)
            return 'Error: unknown tool %s' % name, True
        except Rejected:
            s.result('Rejected by user')
            return REJECTED, True
        except GridError as e:
            s.result('Error: %s' % e)
            return 'Error on the GRiD: %s' % e, True
        except K.KeyError_ as e:
            s.result('Error: %s' % e)
            return 'Error in keys: %s' % e, True
        except OSError as e:
            s.result('Error: %s' % e)
            return 'Error: %s' % e, True

    # ---- files: shared helpers ----------------------------------------
    def load(s, path):
        """Returns (Doc or None, raw bytes)."""
        if is_grid_path(path):
            s.S.status('Reading %s' % path)
            raw = s.S.grid.read_file(norm(path), limit=256 * 1024,
                                     progress=lambda n: s.S.status('Reading %s  %d KB' % (path, n // 1024)))
            if looks_binary(raw): return None, raw
            text = raw.decode('cp437').replace('\x1a', '')
            return Doc(text.replace('\r\n', '\n'), '\r\n' in text or '\n' not in text, 'grid'), raw
        p = Path(path)
        raw = p.read_bytes()
        if looks_binary(raw): return None, raw
        return Doc(raw.decode('utf-8', 'replace'), False, 'pi'), raw

    def save(s, path, doc, text):
        data = doc.encode(text)
        if is_grid_path(path):
            s.S.status('Writing %s' % path)
            s.S.grid.write_file_safe(norm(path), data,
                                     progress=lambda n: s.S.status('Writing %s  %d KB' % (path, n // 1024)))
        else:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(data)

    def where(s, path):
        if is_grid_path(path): return 'grid'
        if path.startswith('/') or path.startswith('~'): return 'pi'
        return None

    # ---- the text editor tool ------------------------------------------
    def editor(s, inp):
        cmd = inp.get('command'); path = (inp.get('path') or '').strip()
        if path.startswith('~'): path = os.path.expanduser(path)
        side = s.where(path)
        if side is None:
            return ('Error: use an absolute path: A:\\DIR\\FILE.EXT for files on the GRiD, or '
                    '/home/... for files on the Pi (your scratch area is %s).' % s.S.cfg.workdir), True
        if is_grid_path(path): path = norm(path)
        if cmd == 'view': return s.view(path, inp.get('view_range'))
        if cmd == 'create': return s.create(path, inp.get('file_text', ''))
        if cmd == 'str_replace': return s.str_replace(path, inp.get('old_str', ''), inp.get('new_str', ''))
        if cmd == 'insert': return s.insert(path, int(inp.get('insert_line', 0)), inp.get('insert_text', ''))
        return 'Error: unknown command %s' % cmd, True

    def view(s, path, rng):
        side = s.where(path)
        is_dir = False
        if side == 'grid':
            if path.endswith('\\') or path.endswith(':'):
                is_dir = True
            else:
                try: is_dir = s.S.grid.stat(path)['dir']
                except GridError as e:
                    if e.code in (2, 3, 18) and len(path) == 3: is_dir = True
                    elif e.code in (2, 3, 18):
                        s.head('Read', path); s.result('File not found')
                        return 'Error: the path %s does not exist.' % path, True
                    else: raise
        else:
            is_dir = Path(path).is_dir()
            if not is_dir and not Path(path).exists():
                s.head('Read', path); s.result('File not found')
                return 'Error: the path %s does not exist.' % path, True
        if is_dir: return s.listdir(path)
        s.head('Read', path)
        doc, raw = s.load(path)
        if doc is None:
            s.result('Binary file, %d bytes' % len(raw))
            return ('%s is a binary file (%d bytes). First 256 bytes:\n%s'
                    % (path, len(raw), hexdump(raw))), False
        lines = doc.text.split('\n')
        if lines and lines[-1] == '': lines.pop()
        start = 1
        if rng:
            start = max(1, int(rng[0])); end = int(rng[1]) if len(rng) > 1 else -1
            lines = lines[start - 1:(None if end == -1 else end)]
        body = numbered(lines, start)
        note = ''
        if len(body) > MAX_VIEW:
            body = body[:MAX_VIEW]; note = '\n[file truncated at %d characters; use view_range]' % MAX_VIEW
        s.result('Read %d lines' % len(lines))
        return body + note, False

    def listdir(s, path):
        s.head('List', path)
        if s.where(path) == 'grid':
            pat = path if path.endswith('\\') else path + '\\'
            entries = s.S.grid.dir(pat + '*.*')
            rows = []
            for e in entries:
                if e['name'] in ('.', '..'): continue
                rows.append('%-12s %10s  %s %s' % (e['name'], '<DIR>' if e['dir'] else e['size'],
                                                   e['date'], e['time']))
            s.result('Listed %d entries' % len(rows))
            free = ''
            try:
                fb, tb = s.S.grid.free(ord(path[0].upper()) - 64)
                free = '\n%d bytes free of %d' % (fb, tb)
            except GridError: pass
            return 'Directory of %s\n%s%s' % (pat, '\n'.join(rows) or '(empty)', free), False
        rows = []
        base = Path(path)
        for f in sorted(base.rglob('*')):
            rel = f.relative_to(base)
            if len(rel.parts) > 2 or any(x.startswith('.') for x in rel.parts): continue
            rows.append('%s%s' % (rel.as_posix(), '/' if f.is_dir() else '  (%d bytes)' % f.stat().st_size))
        s.result('Listed %d entries' % len(rows))
        return 'Files in %s (2 levels):\n%s' % (path, '\n'.join(rows) or '(empty)'), False

    def create(s, path, text):
        side = s.where(path)
        exists = s.S.grid.exists(path) if side == 'grid' else Path(path).exists()
        s.head('Write', path)
        nlines = text.count('\n') + (0 if text.endswith('\n') else 1)
        rows = text.rstrip('\n').split('\n')
        s.allow('edit', path, ('Overwrite %s? (%d lines)' if exists else 'Create %s? (%d lines)') % (path, nlines),
                s.ask_detail(['%4d  %s' % (i + 1, r) for i, r in enumerate(rows[:6])]),
                'Yes, allow all edits this session')
        doc = Doc('', True, side)
        s.save(path, doc, text)
        s.result('Wrote %d lines to %s' % (nlines, path))
        s.S.show(s.S.render.verbatim('\n'.join(rows), prefix=INDENT, max_lines=6))
        return 'File %s %s successfully.' % (path, 'overwritten' if exists else 'created'), False

    def snippet(s, text, line, before=4, after=4):
        lines = text.split('\n')
        a = max(0, line - 1 - before); b = min(len(lines), line + after)
        return numbered(lines[a:b], a + 1)

    def str_replace(s, path, old, new):
        s.head('Update', path)
        doc, raw = s.load(path)
        if doc is None:
            s.result('Binary file'); return 'Error: %s is a binary file.' % path, True
        text = doc.text
        n = text.count(old) if old else 0
        if n == 0:
            s.result('Text not found')
            return 'No replacement was performed, old_str `%s` did not appear verbatim in %s.' % (old, path), True
        if n > 1:
            nums = []
            i = text.find(old)
            while i >= 0:
                nums.append(str(text.count('\n', 0, i) + 1)); i = text.find(old, i + 1)
            s.result('Text not unique')
            return ('No replacement was performed. Multiple occurrences of old_str `%s` in lines %s. '
                    'Please ensure it is unique.' % (old, ', '.join(nums))), True
        at = text.find(old); line = text.count('\n', 0, at) + 1
        new_text = text.replace(old, new, 1)
        old_l = old.split('\n'); new_l = new.split('\n')
        adds = sum(1 for t, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old_l, b=new_l).get_opcodes()
                   if t != 'equal' for _ in range(j2 - j1))
        rems = sum(1 for t, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old_l, b=new_l).get_opcodes()
                   if t != 'equal' for _ in range(i2 - i1))
        dl = s.diff_lines(old_l, new_l, line)
        s.allow('edit', path, 'Make this edit to %s?' % path, s.ask_detail(dl),
                'Yes, allow all edits this session')
        s.save(path, doc, new_text)
        s.result('Updated %s with %d addition%s and %d removal%s'
                 % (path, adds, '' if adds == 1 else 's', rems, '' if rems == 1 else 's'))
        s.diff(dl)
        return ("The file %s has been edited. Here's the result of running `cat -n` on a snippet of %s:\n%s\n"
                "Review the changes and make sure they are as expected. Edit the file again if necessary."
                % (path, path, s.snippet(new_text, line))), False

    def insert(s, path, at, ins):
        s.head('Update', path)
        doc, raw = s.load(path)
        if doc is None:
            s.result('Binary file'); return 'Error: %s is a binary file.' % path, True
        lines = doc.text.split('\n')
        trailing = doc.text.endswith('\n')
        if trailing: lines.pop()
        if at < 0 or at > len(lines):
            s.result('Bad line number')
            return ('Error: Invalid `insert_line` parameter: %d. It should be within the range of lines of '
                    'the file: [0, %d]' % (at, len(lines))), True
        new_lines = ins.rstrip('\n').split('\n')
        dl = s.diff_lines([], new_lines, at + 1)
        s.allow('edit', path, 'Insert %d line%s into %s after line %d?'
                % (len(new_lines), '' if len(new_lines) == 1 else 's', path, at),
                s.ask_detail(dl), 'Yes, allow all edits this session')
        lines[at:at] = new_lines
        new_text = '\n'.join(lines) + ('\n' if trailing else '')
        s.save(path, doc, new_text)
        s.result('Inserted %d line%s after line %d' % (len(new_lines), '' if len(new_lines) == 1 else 's', at))
        s.diff(dl)
        return ("The file %s has been edited. Here's the result of running `cat -n` on a snippet of the edited "
                "file:\n%s\nReview the changes and make sure they are as expected (correct indentation, no "
                "duplicate lines, etc). Edit the file again if necessary."
                % (path, s.snippet(new_text, at + 1, 2, len(new_lines) + 2))), False

    # ---- DOS commands on the GRiD -------------------------------------
    def grid_command(s, inp):
        command = (inp.get('command') or '').strip()
        if not command: return 'Error: empty command', True
        capture = inp.get('capture', True)
        script = inp.get('keys') or ''
        shot = bool(inp.get('screenshot', False))
        timeout = int(inp.get('timeout') or 900)
        prog = os.path.splitext(command.split()[0].replace('/', '\\').split('\\')[-1])[0].upper()
        label = command if not script else '%s  keys: %s' % (command, K.describe(script))
        s.head('DOS', label)
        kbytes = K.compile_script(script) if script else b''
        snap = shot or b'\xff\xfe' in kbytes
        s.allow('cmd', prog, 'Run on the GRiD?', command,
                "Yes, and don't ask again for %s" % prog)
        s.S.status('Running %s on the GRiD' % prog)
        r = s.S.grid.run(command, capture=capture, snapshot=snap, keys=kbytes, timeout=timeout)
        parts = []
        text_out = ''
        if capture and r['output'] and r['outfile']:
            raw = s.S.grid.read_file(r['outfile'], limit=64 * 1024)
            try: s.S.grid.delete(r['outfile'])
            except GridError: pass
            text_out = raw.decode('cp437').replace('\r\n', '\n').replace('\x1a', '').strip('\n')
            s.output(text_out)
        else:
            s.result('Program finished, exit code %d' % r['exit'])
        msg = 'Exit code: %d' % r['exit']
        if capture:
            out = text_out if len(text_out) < 30000 else text_out[:15000] + '\n[...]\n' + text_out[-15000:]
            msg += '\nOutput:\n' + (out or '(no output)')
        parts.append({'type': 'text', 'text': msg})
        if r['snapshot']:
            snapd = screen.parse(s.S.grid.screen(0))
            if screen.is_text(snapd):
                parts.append({'type': 'text', 'text': 'Screen (%s):\n%s' % (screen.describe(snapd), screen.text(snapd))})
            else:
                parts.append({'type': 'text', 'text': 'Screenshot: %s' % screen.describe(snapd)})
                parts.append(screen.png_block(snapd))
            s.result('Screenshot taken (%s)' % screen.describe(snapd))
        elif shot:
            parts.append({'type': 'text', 'text': 'No screenshot was taken.'})
        return parts, False

    # ---- file operations ----------------------------------------------
    def grid_files(s, inp):
        G = s.S.grid
        act = inp.get('action'); path = (inp.get('path') or '').strip(); to = (inp.get('to') or '').strip()
        if act in ('list', 'info', 'delete', 'rename', 'mkdir', 'rmdir', 'free', 'copy_from_grid'):
            if not is_grid_path(path): return 'Error: path must be a GRiD path like A:\\NAME.EXT', True
            path = norm(path)
        if act == 'list':
            return s.listdir(path)
        if act == 'info':
            s.head('Info', path); st = G.stat(path)
            s.result('%s, %s %s' % ('directory' if st['dir'] else '%d bytes' % st['size'], st['date'], st['time']))
            return '%s: %s, modified %s %s, attributes %02Xh' % (
                path, 'directory' if st['dir'] else '%d bytes' % st['size'], st['date'], st['time'], st['attr']), False
        if act == 'free':
            s.head('Free', path[:2]); fb, tb = G.free(ord(path[0].upper()) - 64)
            s.result('%d KB free of %d KB' % (fb // 1024, tb // 1024))
            return '%s %d bytes free of %d' % (path[:2], fb, tb), False
        if act == 'delete':
            s.head('Delete', path)
            s.allow('delete', path, 'Delete %s?' % path, '', 'Yes, allow deletes this session')
            G.delete(path); s.result('Deleted'); return 'Deleted %s' % path, False
        if act == 'rename':
            if not is_grid_path(to) and '\\' not in to:
                to = path.rpartition('\\')[0] + '\\' + to
            to = norm(to)
            s.head('Rename', '%s %s %s' % (path, chr(glp.GL_ARROW), to))
            s.allow('files', path, 'Rename %s?' % path, 'to ' + to, 'Yes, allow file changes this session')
            G.rename(path, to); s.result('Renamed'); return 'Renamed %s to %s' % (path, to), False
        if act == 'mkdir':
            s.head('Mkdir', path)
            s.allow('files', path, 'Make directory %s?' % path, '', 'Yes, allow file changes this session')
            G.mkdir(path); s.result('Created'); return 'Created directory %s' % path, False
        if act == 'rmdir':
            s.head('Rmdir', path)
            s.allow('files', path, 'Remove directory %s?' % path, '', 'Yes, allow file changes this session')
            G.rmdir(path); s.result('Removed'); return 'Removed directory %s' % path, False
        if act == 'copy_to_grid':
            src = Path(os.path.expanduser(path))
            if not is_grid_path(to): return 'Error: `to` must be a GRiD path', True
            to = norm(to)
            data = src.read_bytes()
            s.head('Copy', '%s %s %s' % (path, chr(glp.GL_ARROW), to))
            s.allow('files', to, 'Copy %s to the GRiD?' % src.name, '%s, %d bytes' % (to, len(data)),
                    'Yes, allow file changes this session')
            G.write_file_safe(to, data, progress=lambda n: s.S.status('Copying to %s  %d / %d KB'
                                                                    % (to, n // 1024, len(data) // 1024)))
            s.result('Copied %d bytes' % len(data))
            return 'Copied %s (%d bytes) to %s' % (path, len(data), to), False
        if act == 'copy_from_grid':
            dest = Path(os.path.expanduser(to or os.path.join(s.S.cfg.workdir, path.rpartition('\\')[2])))
            s.head('Copy', '%s %s %s' % (path, chr(glp.GL_ARROW), dest))
            data = G.read_file(path, limit=4 * 1024 * 1024,
                               progress=lambda n: s.S.status('Copying %s  %d KB' % (path, n // 1024)))
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)
            s.result('Copied %d bytes' % len(data))
            return 'Copied %s (%d bytes) to %s' % (path, len(data), dest), False
        return 'Error: unknown action %s' % act, True

    # ---- GPIB ----------------------------------------------------------
    def gpib(s, inp):
        G = s.S.grid; cfg = s.S.cfg
        act = inp.get('action'); addr = inp.get('address')
        cmd = inp.get('command') or ''
        term = {'crlf': b'\r\n', 'lf': b'\n', 'none': b''}[inp.get('terminator') or 'crlf']
        tmo = int(inp.get('timeout_ms') or 2000); maxb = int(inp.get('max_bytes') or 4096)
        name = cfg.bus.get(addr, '') if addr is not None else ''
        who = '%s%s' % (addr, (' ' + name) if name else '')
        if act == 'scan':
            s.head('GPIB', 'scan')
            r = G.gpib(glp.GP_SCAN, 0, timeout_ms=tmo)
            found = list(r)
            s.result('Found %s' % (', '.join(str(a) for a in found) or 'nothing'))
            return 'Responding addresses: %s' % (', '.join('%d%s' % (a, ' (%s)' % cfg.bus[a] if a in cfg.bus else '')
                                                           for a in found) or 'none'), False
        if addr is None: return 'Error: address is required', True
        if addr in (21, cfg.address): return 'Error: %d is the GRiD or this bridge, not an instrument' % addr, True
        if act in ('query', 'write') and not cmd: return 'Error: command is required', True
        if act == 'query':
            s.head('GPIB', '%s: %s' % (addr, cmd))
            c = cmd.strip()
            if not (c.endswith('?') and ';' not in c and not any(ord(ch) < 32 or ord(ch) == 127 for ch in c)):
                # (a query asks nothing, as gpib_measure's rule: one command, no ';', and no control characters,
                # since a CR or LF inside would end a command the instrument then takes before the '?')
                s.allow('gpib', addr, 'Send to GPIB %s?' % who, cmd, "Yes, and don't ask again for address %d" % addr)
            r = G.gpib(glp.GP_QUERY, addr, cmd.encode('latin1') + term, timeout_ms=tmo, maxlen=maxb)
            text = r.decode('latin1').rstrip('\r\n')
            s.output(text, lines=4)
            return text or '(empty reply)', False
        if act == 'write':
            s.head('GPIB', '%s %s %s' % (addr, chr(glp.GL_ARROW), cmd))
            s.allow('gpib', addr, 'Send to GPIB %s?' % who, cmd, "Yes, and don't ask again for address %d" % addr)
            G.gpib(glp.GP_WRITE, addr, cmd.encode('latin1') + term, flags=1, timeout_ms=tmo)
            s.result('Sent'); return 'Sent to %d' % addr, False
        if act == 'read':
            s.head('GPIB', 'read %s' % addr)
            r = G.gpib(glp.GP_READ, addr, timeout_ms=tmo, maxlen=maxb)
            text = r.decode('latin1').rstrip('\r\n'); s.output(text, lines=4)
            return text or '(empty reply)', False
        if act == 'poll':
            s.head('GPIB', 'poll %s' % addr)
            r = G.gpib(glp.GP_SPOLL, addr, timeout_ms=tmo)
            v = r[0] if r else 0
            s.result('Status %02Xh%s' % (v, ' (requesting service)' if v & 0x40 else ''))
            return 'Status byte %02Xh (%s)' % (v, format(v, '08b')), False
        ops = {'clear': glp.GP_CLEAR, 'trigger': glp.GP_TRIGGER, 'local': glp.GP_LOCAL, 'remote': glp.GP_REMOTE}
        if act in ops:
            s.head('GPIB', '%s %s' % (act, addr))
            s.allow('gpib', addr, '%s GPIB %s?' % (act.capitalize(), who), '', "Yes, and don't ask again for address %d" % addr)
            G.gpib(ops[act], addr, timeout_ms=tmo)
            s.result('Done'); return '%s sent to %d' % (act, addr), False
        return 'Error: unknown action %s' % act, True

    # ---- the Pi's shell ------------------------------------------------
    def bash(s, inp):
        if inp.get('restart'):
            s.head('Bash', 'restart'); s.result(s.S.bash.restart()); return 'Shell restarted', False
        cmd = inp.get('command') or ''
        first = cmd.strip().split()[0] if cmd.strip() else ''
        s.head('Bash', cmd if len(cmd) < 200 else cmd[:200] + chr(glp.GL_ELLIPSIS))
        s.allow('bash', first, 'Run on the Pi?', cmd, "Yes, and don't ask again for %s commands" % first)
        s.S.status('Running on the Pi')
        out, code = s.S.bash.run(cmd, timeout=s.S.cfg.bash_timeout)
        s.output(out)
        if code: out = out + ('\n' if out else '') + '[exit code %d]' % code
        return out or '(no output)', bool(code)

    def memory(s, inp):
        cmd = inp.get('command'); p = inp.get('path') or inp.get('old_path') or ''
        text, err = s.S.memory.execute(inp)
        if cmd in ('create', 'str_replace', 'insert', 'delete', 'rename') and not err:
            s.S.show(s.S.render.block('Updated memory (%s)' % p.replace('/memories/', ''),
                                      first=BULLET, rest='  '))
        return text, err
