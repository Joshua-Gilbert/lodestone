"""The conversation: a Claude Code style agent loop on the Claude API, with
the GRiD as screen, keyboard and tool host."""
import json, os, queue, random, threading, time, traceback, collections
from . import glp
from .glp import asciiz
from .grid import Grid, GridError
from .render import Renderer, to_bytes, fold
from .tools import Tools, BULLET, CORNER
from .memory import Memory
from .pibash import Bash
from .config import MODELS, CACHE_READ

COMPACT_BETA = 'compact-2026-09-04'
NO_COMPACTION = ('claude-haiku',)
VERBS = ['Thinking', 'Pondering', 'Computing', 'Calculating', 'Percolating', 'Cogitating',
         'Considering', 'Working', 'Mulling']
STAR = chr(glp.GL_SPIN[4])            # the spinner's star frame


class Interrupted(Exception):
    def __init__(s, snapshot=None):
        super().__init__('interrupted'); s.snapshot = snapshot


def jsonable(content):
    if isinstance(content, str): return content
    out = []
    for b in content:
        if isinstance(b, dict): out.append(b)
        elif hasattr(b, 'to_dict'): out.append(b.to_dict())
        else: out.append(b.model_dump(exclude_none=True))
    return out


def btype(b):
    return b.get('type') if isinstance(b, dict) else getattr(b, 'type', None)


class Session:
    def __init__(s, cfg, client, log=print):
        s.cfg, s.client, s.log = cfg, client, log
        s.link = None; s.grid = None
        s.render = Renderer(79)
        s.tools = Tools(s)
        s.memory = Memory(cfg.memory_dir)
        s.bash = Bash(cfg.workdir)
        s.mode = cfg.mode; s.model = cfg.model; s.allowed = set()
        s.history = []; s.note = None
        s.inbox = queue.Queue()
        s.interrupt = threading.Event()
        s.ask_cv = threading.Condition(); s.answers = {}; s.next_ask = 1
        s.usage = collections.Counter(); s.cost = 0.0; s.last_ctx = 0
        s.hello = {}; s.claude_md = ''; s.claude_md_path = ''
        s.busy = False; s.last_status = None; s.connected_once = False
        s.session_file = None
        os.makedirs(cfg.sessions_dir, exist_ok=True)

    def attach(s, link):
        s.link = link; s.grid = Grid(link)

    # ---- link callbacks (reader thread: keep these quick) ---------------
    def on_message(s, t, body):
        if t == glp.G_HELLO:
            s._hello(body)
        elif t == glp.G_PROMPT:
            s.inbox.put(('prompt', bytes(body).decode('cp437', 'replace')))
        elif t == glp.G_EVENT and body:
            if body[0] == glp.EV_INTERRUPT:
                s.interrupt.set()
                with s.ask_cv: s.ask_cv.notify_all()
            elif body[0] == glp.EV_ANSWER and len(body) >= 3:
                with s.ask_cv:
                    s.answers[body[1]] = chr(body[2]).lower(); s.ask_cv.notify_all()
        elif t == glp.G_REPLY:
            s.grid.on_reply(body)

    def _hello(s, body):
        info = {}
        if len(body) >= 6:
            info = dict(ver=body[0], flags=body[1], maxpay=body[2] | (body[3] << 8), cols=body[4], rows=body[5])
            info.update(glp.kv_lines(body[6:]))
        s.hello = info
        s.last_status = None
        s.grid.on_restart()
        if s.busy: s.interrupt.set()
        with s.ask_cv: s.ask_cv.notify_all()
        s.link.send_first(glp.P_HELLO, bytes([glp.VERSION, s.link.saver_flag()]) + s.model.encode())   # (EV_SAVER:
                                                                                        #  nothing to do; it rings)
        s.link.send(glp.P_TITLE, to_bytes(s.title()))
        s.inbox.put(('hello', None))

    # ---- output helpers ---------------------------------------------------
    def show(s, data):
        if data: s.link.send(glp.P_TEXT, data)

    def status(s, text):
        text = fold(text)[:70]
        if text != s.last_status:
            s.last_status = text
            s.link.send(glp.P_STATUS, to_bytes(text))

    def notice(s, text):
        s.show(s.render.block(text, first='  ', rest='  '))

    def title(s):
        short = s.model.replace('claude-', '')
        return '%s Claude for GRiD %s %s %s %s mode' % (STAR, chr(glp.GL_MIDDOT), short,
                                                      chr(glp.GL_MIDDOT), s.mode)

    def ask(s, question, detail='', always=''):
        with s.ask_cv:
            aid = s.next_ask; s.next_ask = s.next_ask % 250 + 1
            s.answers.pop(aid, None)
        kind = 1 if always else 2
        z = lambda t, n: to_bytes(fold(t)[:n]) + b'\0'     # GRiD glyph codes, not CP437
        s.status('Waiting for your answer')
        s.link.send(glp.P_ASK, bytes([aid, kind]) + z(question, 200) + z(detail, 600) + z(always, 70))
        gen = s.grid.generation
        with s.ask_cv:
            while aid not in s.answers:
                if s.interrupt.is_set() or s.grid.generation != gen: return 'n'
                s.ask_cv.wait(0.5)
            return s.answers.pop(aid)

    # ---- the agent thread -----------------------------------------------
    def run(s):
        while True:
            kind, val = s.inbox.get()
            try:
                if kind == 'hello': s.on_connect()
                elif kind == 'prompt': s.on_prompt(val)
            except Exception as e:
                s.log('agent: %s' % traceback.format_exc())
                s.show(s.render.block('Internal error: %s' % e, first='! ', rest='  ', gap=True))
                s.busy = False
                s.status(''); s.link.send(glp.P_READY)

    def on_connect(s):
        s.render.reset()
        h = s.hello
        if s.cfg.set_clock:
            try: s.grid.settime()
            except GridError as e: s.log('settime: %s' % e)
        s.load_claude_md()
        if not s.connected_once:
            s.connected_once = True
            s.show(s.render.block('%s Welcome to Claude for GRiD!' % STAR, first='', rest='  '))
            s.show(s.render.block('/help for help, /status for your setup, Esc interrupts, CODE-Q quits.',
                                  first='  ', rest='  '))
            s.show(s.render.block('cwd: %s   model: %s   mode: %s' % (h.get('cwd', '?'), s.model, s.mode),
                                  first='  ', rest='  '))
            if s.claude_md_path:
                s.show(s.render.block('Read %s (%d lines)' % (s.claude_md_path, s.claude_md.count('\n') + 1),
                                      first='  ', rest='  '))
            s.show(b'\n')
        else:
            n = len(s.history)
            s.notice('Reconnected. %s' % ('Conversation kept (%d messages); /clear starts over.' % n if n
                                          else 'Ready.'))
        s.busy = False; s.status(''); s.link.send(glp.P_READY)

    def load_claude_md(s):
        s.claude_md = ''; s.claude_md_path = ''
        cwd = s.hello.get('cwd', 'A:\\')
        for p in [cwd.rstrip('\\') + '\\CLAUDE.MD', 'A:\\CLAUDE.MD']:
            try:
                data = s.grid.read_file(p, limit=24 * 1024)
                s.claude_md = data.decode('cp437').replace('\r\n', '\n'); s.claude_md_path = p
                return
            except GridError:
                continue

    def on_prompt(s, text):
        text = text.strip()
        if not text:
            s.link.send(glp.P_READY); return
        if text.startswith('/'):
            s.slash(text)
            s.status(''); s.link.send(glp.P_READY)
            return
        s.run_turn(text)

    # ---- the API request ------------------------------------------------
    def system_prompt(s):
        h = s.hello; c = s.cfg
        bus = '; '.join('%d %s' % (a, n) for a, n in sorted(c.bus.items())) or 'unknown (use gpib scan)'
        env = ['Operating system: %s' % h.get('os', 'MS-DOS'),
               'Current directory: %s' % h.get('cwd', 'A:\\'),
               'Drives: %s' % h.get('drives', '?'),
               'Free conventional memory: %s KB' % h.get('mem', '?'),
               'EMS: %s' % h.get('ems', 'unknown'),
               'GPIB driver: %s' % h.get('gpib', '?'),
               "GRiD's clock: %s" % h.get('date', '?'),
               "Pi's time: %s" % time.strftime('%Y-%m-%d %H:%M %Z')]
        text = (
            "You are Claude, working with %(u)s, who types on a GRiDCase 1520 "
            "laptop (1988: Intel 80286 with 80287, 640 KB conventional memory plus about 1.4 MB EMS, 640x400 "
            "amber gas-plasma screen) through \"Claude for GRiD\". You run on a Raspberry Pi 3 beside it, connected to the GRiD over GPIB "
            "(IEEE-488) through an AR488 bridge at address %(a)d. The GRiD is the GPIB controller (address 21) "
            "and also runs %(u)s's test equipment on the same bus.\n\n"
            "Your replies appear on the GRiD in an 80-column amber terminal. Write plain, compact text: short "
            "paragraphs, '-' lists, code blocks when useful. No tables wider than 78 columns, no emoji, no HTML. "
            "Markdown headings and **bold** render (inverse / underline); other markup shows literally.\n\n"
            "Working on the GRiD:\n"
            "- GRiD files use DOS paths with a drive letter, e.g. A:\\TM5000\\CONFIG.C; names are 8.3 and "
            "case-insensitive. Text files are CP437 with CR LF line ends; the tools convert for you.\n"
            "- str_replace_based_edit_tool views and edits files on both machines; the path decides which.\n"
            "- grid_command runs DOS commands and programs; grid_files lists, copies, renames and deletes.\n"
            "- The link is slow (roughly 5-10 KB/s). Use view_range when you only need part of a big file, and "
            "prefer commands with short output.\n"
            "- gpib reaches the instruments through the GRiD. Known devices: %(bus)s. They are real hardware "
            "(power supplies drive real circuits): never change an instrument's state unless %(u)s asked.\n\n"
            "Working on the Pi:\n"
            "- bash runs Linux commands on the Pi, which has internet access and Python 3. Your scratch "
            "directory is %(w)s. Do heavy lifting (parsing, plotting, maths) on the Pi and copy only results "
            "to the GRiD.\n"
            "- web_search and web_fetch find datasheets, manuals and anything current.\n"
            "- memory keeps notes that survive between sessions; record what you learn about this setup.\n\n"
            "Edits, commands, instrument changes and Pi commands ask %(u)s first (Yes / Always / No). If the "
            "answer is No, stop and wait for direction.\n\n"
            "Environment at the start of this session:\n%(env)s\n"
            % dict(u=c.user, a=c.address, bus=bus, w=c.workdir, env='\n'.join(env)))
        if s.claude_md:
            text += '\nContents of %s (project notes kept on the GRiD):\n%s\n' % (s.claude_md_path, s.claude_md)
        if c.extra_prompt:
            text += '\n' + c.extra_prompt + '\n'
        return [{'type': 'text', 'text': text, 'cache_control': {'type': 'ephemeral'}}]

    def tool_defs(s):
        defs = s.tools.definitions()
        if s.model.startswith('claude-haiku'):
            for d in defs:
                if d.get('name') == 'web_search': d['type'] = 'web_search_20250305'
                if d.get('name') == 'web_fetch': d['type'] = 'web_fetch_20250910'
        defs[-1] = dict(defs[-1], cache_control={'type': 'ephemeral'})
        return defs

    def request_messages(s):
        msgs = list(s.history)
        if msgs and msgs[-1]['role'] == 'user':
            last = dict(msgs[-1]); c = last['content']
            if isinstance(c, str):
                c = [{'type': 'text', 'text': c}]
            c = list(c)
            if c and isinstance(c[-1], dict) and c[-1].get('type') in ('text', 'tool_result'):
                c[-1] = dict(c[-1], cache_control={'type': 'ephemeral'})
            last['content'] = c; msgs[-1] = last
        return msgs

    def betas(s):
        return [] if s.model.startswith(NO_COMPACTION) else [COMPACT_BETA]

    def params(s):
        p = dict(model=s.model, max_tokens=s.cfg.max_tokens, system=s.system_prompt(),
                 tools=s.tool_defs(), messages=s.request_messages())
        b = s.betas()
        if b: p['betas'] = b
        return p

    def account(s, usage):
        if usage is None: return
        g = lambda k: getattr(usage, k, None) if not isinstance(usage, dict) else usage.get(k)
        inp = g('input_tokens') or 0; out = g('output_tokens') or 0
        cr = g('cache_read_input_tokens') or 0; cw = g('cache_creation_input_tokens') or 0
        s.usage['in'] += inp; s.usage['out'] += out; s.usage['cache_read'] += cr; s.usage['cache_write'] += cw
        pi, po = s.cfg.price(s.model)
        s.cost += (inp * pi + cw * pi * 1.25 + cr * pi * CACHE_READ.get(s.model, 0.1) + out * po) / 1e6
        s.last_ctx = inp + cr + cw + out

    # ---- one turn -------------------------------------------------------
    def add_user(s, content):
        """Append user content, merging into a trailing user message."""
        if s.note:
            content = [{'type': 'text', 'text': s.note}] + (
                [{'type': 'text', 'text': content}] if isinstance(content, str) else list(content))
            s.note = None
        if s.history and s.history[-1]['role'] == 'user':
            prev = s.history[-1]['content']
            prev = [{'type': 'text', 'text': prev}] if isinstance(prev, str) else list(prev)
            add = [{'type': 'text', 'text': content}] if isinstance(content, str) else list(content)
            s.history[-1] = {'role': 'user', 'content': prev + add}
        else:
            s.history.append({'role': 'user', 'content': content})

    def run_turn(s, text):
        s.busy = True; s.interrupt.clear(); s.render.reset()
        verb = random.choice(VERBS)
        s.add_user(text)
        try:
            while True:
                s.status('%s%s' % (verb, chr(glp.GL_ELLIPSIS)))
                try:
                    msg = s.stream_once()
                except Interrupted as e:
                    s.keep_partial(e.snapshot)
                    s.show(s.render.block('Interrupted by user', first=CORNER, rest='     '))
                    break
                stop = getattr(msg, 'stop_reason', None)
                if stop == 'tool_use':
                    results = s.run_tools(msg)
                    s.add_user(results)
                    if s.interrupt.is_set():
                        s.note = '[Request interrupted by user]'
                        s.show(s.render.block('Interrupted by user', first=CORNER, rest='     '))
                        break
                    continue
                if stop == 'pause_turn':
                    continue
                if stop == 'max_tokens':
                    s.notice('(reply cut off at the output limit)')
                elif stop == 'refusal':
                    s.notice('(Claude declined to continue this request)')
                break
        except GridError as e:
            s.show(s.render.block('Link error: %s' % e, first='! ', rest='  ', gap=True))
        except Exception as e:
            name = type(e).__name__
            s.log('turn: %s' % traceback.format_exc())
            s.show(s.render.block('%s: %s' % (name, str(e)[:300]), first='! ', rest='  ', gap=True))
            # an API error leaves the last user message unanswered; keep it so
            # "try again" can resend, but don't leave a dangling tool_use
        finally:
            s.show(s.render.finish())
            s.busy = False
            s.status(''); s.link.send(glp.P_READY)
            s.save()
        if s.last_ctx > s.cfg.compact_at and not s.model.startswith(NO_COMPACTION):
            s.compact(auto=True)

    def keep_partial(s, snap):
        texts = []
        if snap is not None:
            for b in getattr(snap, 'content', []) or []:
                if btype(b) == 'text':
                    t = b.get('text') if isinstance(b, dict) else b.text
                    if t: texts.append(t)
        if texts:
            s.history.append({'role': 'assistant', 'content': [{'type': 'text', 'text': ''.join(texts)}]})
        s.note = '[Request interrupted by user]'

    def stream_once(s):
        p = s.params()
        server = {}
        with s.client.beta.messages.stream(**p) as stream:
            for ev in stream:
                if s.interrupt.is_set():
                    raise Interrupted(getattr(stream, 'current_message_snapshot', None))
                et = getattr(ev, 'type', None)
                if et == 'content_block_start':
                    cb = ev.content_block; t = btype(cb)
                    if t == 'text':
                        s.show(s.render.start_text())
                    elif t == 'thinking' or t == 'redacted_thinking':
                        s.status('Thinking%s' % chr(glp.GL_ELLIPSIS))
                    elif t == 'tool_use':
                        s.status('Preparing %s' % getattr(cb, 'name', 'tool'))
                    elif t == 'web_search_tool_result':
                        res = getattr(cb, 'content', None)
                        if isinstance(res, list):
                            s.show(s.render.block('%d results' % len(res), first=CORNER, rest='     '))
                elif et == 'content_block_delta':
                    d = ev.delta
                    if getattr(d, 'type', None) == 'text_delta':
                        s.show(s.render.feed(d.text))
                elif et == 'content_block_stop':
                    snap = stream.current_message_snapshot
                    cb = snap.content[ev.index] if ev.index < len(snap.content) else None
                    t = btype(cb)
                    if t == 'text':
                        s.show(s.render.finish())
                    elif t == 'server_tool_use':
                        name = getattr(cb, 'name', ''); inp = getattr(cb, 'input', {}) or {}
                        if name == 'web_search':
                            s.show(s.render.block('Web Search("%s")' % inp.get('query', ''), first=BULLET, rest='  ', gap=True))
                        elif name == 'web_fetch':
                            s.show(s.render.block('Fetch(%s)' % inp.get('url', ''), first=BULLET, rest='  ', gap=True))
            msg = stream.get_final_message()
        s.account(getattr(msg, 'usage', None))
        s.history.append({'role': 'assistant', 'content': msg.content})
        return msg

    def run_tools(s, msg):
        results = []
        for b in msg.content:
            if btype(b) != 'tool_use': continue
            bid = b.get('id') if isinstance(b, dict) else b.id
            name = b.get('name') if isinstance(b, dict) else b.name
            inp = (b.get('input') if isinstance(b, dict) else b.input) or {}
            if s.interrupt.is_set():
                results.append({'type': 'tool_result', 'tool_use_id': bid, 'is_error': True,
                                'content': 'Interrupted by user before this tool ran.'})
                continue
            s.status('Running %s' % name)
            try:
                content, err = s.tools.execute(name, inp)
            except Exception as e:
                s.log('tool %s: %s' % (name, traceback.format_exc()))
                content, err = 'Error: %s' % e, True
            r = {'type': 'tool_result', 'tool_use_id': bid, 'content': content}
            if err: r['is_error'] = True
            results.append(r)
        return results

    # ---- compaction -----------------------------------------------------
    def compact(s, instructions=None, auto=False):
        if not s.history:
            s.notice('Nothing to compact.'); return
        if s.model.startswith(NO_COMPACTION):
            s.notice('%s cannot compact; use /clear instead.' % s.model); return
        s.status('Compacting conversation%s' % chr(glp.GL_ELLIPSIS))
        comp = {'type': 'summarize'}
        if instructions:
            comp['instructions'] = instructions + ' Do not call tools; respond with the summary only.'
        p = dict(model=s.model, max_tokens=8192, system=s.system_prompt(), tools=s.tool_defs(),
                 messages=s.history, betas=[COMPACT_BETA], extra_body={'compaction': comp})
        try:
            r = s.client.beta.messages.create(**p)
        except Exception as e:
            s.notice('Compaction failed: %s' % e); s.status(''); return
        if getattr(r, 'stop_reason', None) == 'compaction':
            before = len(s.history)
            s.history = [{'role': 'assistant', 'content': r.content}]
            s.notice('%s compacted %d messages into a summary%s' % (
                'Context was getting long:' if auto else 'Conversation', before, '.'))
            s.last_ctx = 0
            s.save()
        else:
            s.notice('No summary came back (%s); the conversation is unchanged.' % getattr(r, 'stop_reason', '?'))
        s.status('')

    # ---- slash commands -------------------------------------------------
    def slash(s, text):
        cmd, _, arg = text[1:].partition(' ')
        cmd = cmd.lower(); arg = arg.strip()
        if cmd in ('help', '?'):
            for line in [
                    'Commands:',
                    '  /clear            start a new conversation',
                    '  /compact [what]   summarise the conversation so far',
                    '  /model [name]     show or switch: opus, sonnet, haiku, fable',
                    '  /mode [m]         ask (default), edits (accept file edits), auto (ask nothing)',
                    '  /cost             tokens and cost of this session',
                    '  /status           link, bridge and GRiD details',
                    '  /memory           list Claude\'s memory files on the Pi',
                    '  /init             have Claude write A:\\CLAUDE.MD notes for this machine',
                    'Keys: Enter sends, Ctrl-Enter new line, Esc interrupts, PgUp/PgDn scroll,',
                    '      Up/Down recall prompts, F1 help, CODE-Q quits.']:
                s.show(s.render.verbatim(line))
        elif cmd == 'clear':
            s.history = []; s.note = None; s.last_ctx = 0; s.session_file = None
            s.link.send(glp.P_CLEAR)
            s.notice('New conversation.')
        elif cmd == 'compact':
            s.compact(arg or None)
        elif cmd == 'model':
            if arg:
                s.model = MODELS.get(arg.lower(), arg)
                s.link.send(glp.P_TITLE, to_bytes(s.title()))
            s.notice('Model: %s' % s.model)
        elif cmd == 'mode':
            if arg in ('ask', 'edits', 'auto'):
                s.mode = arg; s.link.send(glp.P_TITLE, to_bytes(s.title()))
            s.notice('Permission mode: %s%s' % (s.mode, '' if arg in ('', 'ask', 'edits', 'auto')
                                                 else ' (choose ask, edits or auto)'))
        elif cmd == 'cost':
            u = s.usage
            s.notice('Tokens: %d in, %d out, %d cache reads, %d cache writes. About $%.2f this session.'
                     % (u['in'], u['out'], u['cache_read'], u['cache_write'], s.cost))
        elif cmd == 'status':
            st = s.link.stats; t = s.link.t
            lines = ['Model %s, mode %s, %d messages, context about %d tokens'
                     % (s.model, s.mode, len(s.history), s.last_ctx),
                     'Bridge: %s at address %d, %s firmware, frames up to %d bytes'
                     % (getattr(t, 'version', '?') or 'AR488', s.cfg.address,
                        'patched' if getattr(t, 'patched', False) else 'stock', t.frame_limit),
                     'Link: %d frames in, %d out, %d KB in, %d KB out, %d NAKs, %d damaged, %d repeats'
                     % (st['rx_frames'], st['tx_frames'], st['rx_bytes'] // 1024, st['tx_bytes'] // 1024,
                        st['tx_nak'] + st['rx_nak'], st['rx_damaged'], st['rx_dup']),
                     'GRiD: %s' % ', '.join('%s=%s' % kv for kv in sorted(s.hello.items())
                                           if kv[0] not in ('ver', 'flags'))]
            for line in lines: s.show(s.render.block(line, first='  ', rest='    '))
        elif cmd == 'memory':
            files = s.memory.listing()
            s.notice('Memory (%s): %s' % (s.cfg.memory_dir, ', '.join(files) if files else 'empty'))
        elif cmd == 'init':
            s.run_turn('Look around this GRiD (start with the current directory and A:\\) and write a '
                       'concise A:\\CLAUDE.MD describing the machine, the important programs and files, '
                       'and conventions for working here. Keep it under 60 lines; it is read at the start '
                       'of every session.')
        elif cmd in ('exit', 'quit'):
            s.notice('Press CODE-Q to leave Claude on the GRiD.')
        else:
            s.notice('Unknown command /%s. /help lists them.' % cmd)

    # ---- persistence ----------------------------------------------------
    def save(s):
        try:
            if s.session_file is None:
                s.session_file = os.path.join(s.cfg.sessions_dir, time.strftime('%Y%m%d-%H%M%S.json'))
            data = [{'role': m['role'], 'content': jsonable(m['content'])} for m in s.history]
            with open(s.session_file + '.tmp', 'w') as f:
                json.dump({'model': s.model, 'messages': data}, f)
            os.replace(s.session_file + '.tmp', s.session_file)
        except Exception as e:
            s.log('save: %s' % e)
