"""What Claude Code shows on the GRiD (grid_plot, grid_image) and the clicks
on it: yours go into Claude Code's prompt as words (not sent: you add to
them and press Return); grid_pick's go back to Claude.  Esc goes back to
Claude Code's screen, which ran on underneath.  One picture at a time, over
the Term session's text (term.py's picture layer)."""
import threading, time
from . import plot as PL

OWNER = 'claude'
ESC = 0x1B
LINGER = 0.7                    # seconds a pick's last mark stays before Claude Code comes back


class Viewer:
    def __init__(s, term):
        s.term = term           # TermSession: show_picture, hide_picture, paste, why_not
        s.view = None           # the Plot or ImageView last shown
        s.bits = None           # what is shown: the view, with a pick's marks
        s.picking = None        # {'want', 'got', 'done', 'why', 'prompt'}
        s.lock = threading.Lock()
        s.gen = 0               # bumps with each picture (a late timer hides only its own)

    # ---- for the tools -----------------------------------------------------
    def show(s, view):
        """Up on the GRiD now (raises RuntimeError if the GRiD can't)."""
        with s.lock:
            s._end_pick('another picture replaced this one')
            s.view = view; s.bits = view.bits; s.gen += 1
        s._up()

    def pick(s, prompt, count=1, timeout=120):
        """Wait for count clicks on the picture last shown (shown again if
        you went back): -> (clicks as view.at() gives them, why it ended
        early or None)."""
        with s.lock:
            if s.view is None:
                raise ValueError('nothing to pick from: show a plot or a picture first (grid_plot, grid_image)')
            s._end_pick('another grid_pick replaced this one')
            pk = {'want': count, 'got': [], 'done': threading.Event(), 'why': None, 'prompt': prompt or ''}
            s.picking = pk; s.bits = s.view.bits; s.gen += 1
        try: s._up()
        except RuntimeError:
            with s.lock:
                if s.picking is pk: s.picking = None
            raise
        end = time.monotonic() + timeout
        while not pk['done'].wait(min(1.0, max(0.0, end - time.monotonic()))):
            why = s.term.why_not('grid_pick')
            if why or time.monotonic() >= end:
                with s.lock:
                    mine = s.picking is pk            # (not ended or replaced meanwhile)
                    if mine:
                        s.picking = None
                        pk['why'] = why or 'the time limit (%d s) passed' % timeout
                if mine: s.hide()
                break
        return pk['got'], pk['why']

    def hide(s):
        s.term.hide_picture(OWNER)

    # ---- the band ------------------------------------------------------------
    def _title(s):
        pk = s.picking
        if pk is not None:
            left = pk['want'] - len(pk['got'])
            p = pk['prompt'] or ('click a point' if left == 1 else 'click %d points' % left)
            return '%s  (Esc: cancel)' % p[:44]
        name = (s.view.title if s.view is not None else '') or 'Picture'
        return '%s  (Esc: back)' % name[:46]

    def _up(s):
        s.term.show_picture(s.bits, OWNER, on_click=s._click, on_key=s._key, title=s._title())

    # ---- on the GRiD (the link's thread) ------------------------------------
    def _key(s, body):
        """While the picture is up, keys are its own: Esc goes back."""
        if any(body[i] == ESC for i in range(0, len(body) - 1, 2)):
            with s.lock: s._end_pick('you pressed Esc on the GRiD')
            s.hide()
        return b''

    def _click(s, x, y):
        with s.lock:
            view, pk = s.view, s.picking
            if view is None: return
            c = view.at(x, y)
            if pk is None:
                # your own click: into Claude Code's prompt, if it means something
                if c['x'] is None and c['nearest'] is None and not c.get('image_pixel'): return
                words = view.words(c)
            else:
                pk['got'].append(c)
                n = c['nearest']
                at = n['pixel'] if n is not None else c['pixel']
                s.bits = PL.mark_click(s.bits, at[0], at[1], str(len(pk['got'])) if pk['want'] > 1 else '')
                done = len(pk['got']) >= pk['want']
                if done:
                    s.picking = None; pk['done'].set()
                gen = s.gen
        if pk is None:
            s.term.paste(words + ' ')
            s.hide(); return
        s._up()
        if done: threading.Timer(LINGER, s._linger_end, args=(gen,)).start()

    def _linger_end(s, gen):
        with s.lock:
            if s.gen != gen or s.picking is not None: return
        s.hide()

    def _end_pick(s, why):
        """(lock held)"""
        pk = s.picking
        if pk is not None:
            pk['why'] = why; s.picking = None; pk['done'].set()
