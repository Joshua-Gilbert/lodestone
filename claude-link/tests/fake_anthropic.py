"""A scripted stand-in for anthropic.Anthropic, for tests without an API key.

Each call to messages.stream() plays the next scripted reply.  A reply is a
list of blocks: ('text', 'hello'), ('tool', 'name', {input}), and an optional
stop reason.  It also records every request so tests can inspect them.
"""
import itertools, time


class Block(dict):
    """Content block that works both as a dict and with attribute access."""
    __getattr__ = dict.get
    def to_dict(self): return dict(self)


class Event:
    def __init__(s, **kw): s.__dict__.update(kw)


class Message:
    def __init__(s, content, stop_reason, usage):
        s.content, s.stop_reason, s.usage = content, stop_reason, usage


class _Stream:
    def __init__(s, owner, reply):
        s.owner, s.reply = owner, reply
        s.snapshot = Message([], None, None)

    def __enter__(s): return s
    def __exit__(s, *a): return False

    @property
    def current_message_snapshot(s): return s.snapshot

    def __iter__(s):
        ids = itertools.count(1)
        for i, item in enumerate(s.reply['blocks']):
            if item[0] == 'text':
                b = Block(type='text', text='')
                s.snapshot.content.append(b)
                yield Event(type='content_block_start', index=i, content_block=Block(type='text', text=''))
                text = item[1]
                for k in range(0, len(text), 7):        # arrive in small pieces
                    if s.reply.get('delay'): time.sleep(s.reply['delay'])
                    piece = text[k:k + 7]
                    b['text'] += piece
                    yield Event(type='content_block_delta', index=i,
                                delta=Event(type='text_delta', text=piece))
                yield Event(type='content_block_stop', index=i)
            elif item[0] == 'tool':
                b = Block(type='tool_use', id='toolu_%02d_%d' % (s.owner.calls, next(ids)),
                          name=item[1], input=item[2])
                yield Event(type='content_block_start', index=i, content_block=b)
                s.snapshot.content.append(b)
                yield Event(type='content_block_stop', index=i)
        s.snapshot.stop_reason = s.reply['stop']

    def get_final_message(s):
        return Message(list(s.snapshot.content), s.reply['stop'],
                       Block(input_tokens=1000, output_tokens=100,
                             cache_read_input_tokens=0, cache_creation_input_tokens=0))


class _Messages:
    def __init__(s, owner): s.owner = owner

    def stream(s, **params):
        s.owner.requests.append(params)
        s.owner.calls += 1
        if not s.owner.script:
            reply = {'blocks': [('text', '(script ended)')], 'stop': 'end_turn'}
        else:
            reply = s.owner.script.pop(0)
        return _Stream(s.owner, reply)

    def create(s, **params):
        s.owner.requests.append(params)
        if 'compaction' in params.get('extra_body', {}):
            return Message([Block(type='compaction', content='summary', signature='sig')],
                           'compaction', Block(input_tokens=0, output_tokens=0))
        return Message([Block(type='text', text='ok')], 'end_turn', Block(input_tokens=1, output_tokens=1))


class FakeAnthropic:
    def __init__(s, script=None):
        s.script = list(script or []); s.requests = []; s.calls = 0
        s.beta = type('B', (), {})(); s.beta.messages = _Messages(s)
        s.messages = s.beta.messages


def reply(*blocks, stop=None, delay=0):
    """reply(('text', 'Hi'), ('tool', 'gpib', {...})) - stop defaults to
    tool_use when there is a tool block, else end_turn."""
    if stop is None:
        stop = 'tool_use' if any(b[0] == 'tool' for b in blocks) else 'end_turn'
    return {'blocks': list(blocks), 'stop': stop, 'delay': delay}
