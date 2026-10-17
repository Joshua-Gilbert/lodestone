// gridfox: read the page Firefox has rendered into blocks of text runs, for
// the GRiD's 80x24 text view.  Run as a WebDriver script body (arguments[0]
// = options); returns {url, title, blocks, acts}.
//
//   block  {k: kind, d: depth, m: list marker (0 none, -1 bullet, n number), r: [[text, flags, act], ...]}
//          kinds: p h1..h6 li pre quote tr hr
//   flags  1 bold, 2 italic, 4 code, 8 image, 16 field
//   act    index into acts (a link, button or field), or -1
//   acts   {t: 'link'|'button'|'field'|'check'|'select', h: href, v: value, ...}
//   block.ids  the ids (and <a name>s) that start at the block, for #fragments
//
// The elements behind acts stay in window.__gridfox, so a later script can
// click one or set its value by number (act.js).
return (function (opt) {
  opt = opt || {};
  var MAXBLOCKS = opt.maxBlocks || 4000, MAXTEXT = opt.maxText || 400000;
  var BLOCK = {ADDRESS:1, ARTICLE:1, ASIDE:1, BLOCKQUOTE:1, BODY:1, CAPTION:1, CENTER:1, DD:1, DETAILS:1,
    DIALOG:1, DIR:1, DIV:1, DL:1, DT:1, FIELDSET:1, FIGCAPTION:1, FIGURE:1, FOOTER:1, FORM:1, H1:1, H2:1,
    H3:1, H4:1, H5:1, H6:1, HEADER:1, HGROUP:1, HR:1, LEGEND:1, LI:1, MAIN:1, MENU:1, NAV:1, OL:1, P:1,
    PRE:1, SECTION:1, SUMMARY:1, TABLE:1, TBODY:1, TFOOT:1, THEAD:1, TR:1, UL:1};
  var SKIP = {SCRIPT:1, STYLE:1, NOSCRIPT:1, TEMPLATE:1, HEAD:1, TITLE:1, META:1, LINK:1, SVG:1,
    CANVAS:1, OBJECT:1, EMBED:1, MAP:1, AUDIO:1, VIDEO:1, SOURCE:1, TRACK:1, DATALIST:1, OPTION:1};
  var TEXTISH = {text:1, search:1, email:1, url:1, tel:1, password:1, number:1, date:1, time:1,
    'datetime-local':1, month:1, week:1, color:1, '':1};
  var doc = document, win = window;
  // jsdom (the tests) lays nothing out: then only the styles count
  // (the root's width, not the body's height: many script-built pages have a
  // body of height 0 with everything positioned inside it)
  var laidOut = !!(doc.documentElement && doc.documentElement.getBoundingClientRect().width > 0);
  var blocks = [], acts = [], els = [], total = 0;
  var cur = null;                 // the block being filled
  var kind = 'p', depth = 0, item = 0, pre = 0, quote = 0;
  var flags = 0, act = -1;
  var rowCell = 0;                // cells so far in the current table row
  var ids = [], nids = 0;         // anchors waiting for the next block

  function style(el) { try { return win.getComputedStyle(el); } catch (e) { return null; } }

  function hidden(el, cs) {
    if (el.hidden) return true;
    if (!cs) return false;
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse') return true;
    if (laidOut && (cs.position === 'absolute' || cs.position === 'fixed')) {
      var r = el.getBoundingClientRect();            // "visually hidden" text for screen readers
      if (r.width <= 1 && r.height <= 1) return true;
    }
    return false;
  }

  function isBlock(el, cs) {
    var d = cs && cs.display;
    if (d && d !== 'inline' && d !== 'contents' && d !== 'inline-block' && d !== 'inline-flex'
        && d !== 'inline-grid' && d !== 'inline-table' && d !== 'ruby') {
      return d !== 'table-cell' && d !== 'table-column';
    }
    if (!d || !laidOut) return !!BLOCK[el.tagName];   // (jsdom: by tag)
    return false;
  }

  function flush() { cur = null; }

  function open() {
    if (!cur) {
      if (blocks.length >= MAXBLOCKS) return null;
      cur = {k: kind, d: depth, m: kind === 'li' ? item : 0, q: quote, r: []};
      if (ids.length) { cur.ids = ids; ids = []; }
      blocks.push(cur);
      item = 0;                   // the marker goes on the item's first block only
    }
    return cur;
  }

  function put(text, f, a) {
    if (total >= MAXTEXT) return;
    if (!pre) {
      text = text.replace(/[\s ]+/g, ' ');
      var b = cur;
      // no space at the start of a block, nor two in a row
      if (!b || !b.r.length || /\s$/.test(b.r[b.r.length - 1][0])) text = text.replace(/^ /, '');
      if (!text) return;
    }
    var bl = open(); if (!bl) return;
    total += text.length;
    var last = bl.r[bl.r.length - 1];
    if (last && last[1] === f && last[2] === a) last[0] += text;
    else bl.r.push([text, f, a]);
  }

  function addAct(o, el) {
    o.i = acts.length; if (o.f === undefined) o.f = formOf(el);
    acts.push(o); els.push(el); return o.i;
  }

  function formOf(el) {
    var f = el.form;
    if (!f) return -1;
    for (var i = 0; i < doc.forms.length; i++) if (doc.forms[i] === f) return i;
    return -1;
  }

  function label(el) {
    // its <label>s first (most forms), then aria-label and title
    var t = '';
    try {
      for (var i = 0; el.labels && i < el.labels.length && !t; i++)
        t = el.labels[i].textContent.replace(/\s+/g, ' ').trim();
    } catch (e) {}
    return (t || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().slice(0, 60);
  }

  function field(el, tag) {
    var t = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'INPUT' && t === 'hidden') return;
    var o, f = 16;
    if (tag === 'TEXTAREA' || (tag === 'INPUT' && TEXTISH[t])) {
      o = {t: 'field', type: tag === 'TEXTAREA' ? 'textarea' : (t || 'text'), v: el.value || '', f: formOf(el),
           ph: el.getAttribute('placeholder') || label(el), lb: label(el), name: el.name || '',
           w: Math.max(6, Math.min(40, el.size > 1 ? el.size : 20))};
      var shown = o.type === 'password' ? el.value.replace(/./g, '*') : o.v;
      var a = addAct(o, el);
      var w = o.w, s = shown || o.ph;
      if (s.length > w) s = s.slice(0, w - 1) + '…';
      put(' ', flags, -1);
      put('[' + s + Array(w - s.length + 1).join('_') + ']', f | (shown ? 0 : 2), a);
      put(' ', flags, -1);
    } else if (tag === 'INPUT' && (t === 'checkbox' || t === 'radio')) {
      o = {t: 'check', type: t, v: el.checked};
      put((t === 'radio' ? (el.checked ? '(*)' : '( )') : (el.checked ? '[x]' : '[ ]')), f, addAct(o, el));
      put(' ', flags, -1);
    } else if (tag === 'SELECT') {
      var opts = [], sel = '';
      for (var i = 0; i < el.options.length && i < 200; i++) {
        opts.push(el.options[i].text.trim());
        if (i === el.selectedIndex) sel = opts[i];
      }
      o = {t: 'select', opts: opts, v: el.selectedIndex};
      put('[' + (sel || '-') + ' ▼]', f, addAct(o, el));
      put(' ', flags, -1);
    } else if (tag === 'BUTTON' || (tag === 'INPUT' && (t === 'submit' || t === 'button' || t === 'reset' || t === 'image'))) {
      var txt = tag === 'BUTTON' ? el.textContent.replace(/\s+/g, ' ').trim() : (el.value || el.alt || '');
      txt = txt || label(el) || (t === 'submit' || !t ? 'Submit' : 'Button');
      o = {t: 'button', v: txt, sub: tag === 'BUTTON' ? (t || 'submit') === 'submit' && !!el.form : t === 'submit' || t === 'image'};
      put('[' + txt + ']', f, addAct(o, el));
      put(' ', flags, -1);
    }
  }

  function walk(node) {
    if (total >= MAXTEXT || blocks.length >= MAXBLOCKS) return;
    if (node.nodeType === 3) { put(node.data, flags, act); return; }
    if (node.nodeType !== 1) return;
    var el = node, tag = el.tagName.toUpperCase();
    if (SKIP[tag]) return;
    var cs = style(el);
    if (hidden(el, cs)) return;
    var id = el.id || (tag === 'A' && el.getAttribute('name')) || '';
    if (id && nids < 3000) {
      nids++;
      if (cur) { (cur.ids = cur.ids || []).push(id); } else ids.push(id);
    }
    if (tag === 'BR') { if (pre) put('\n', flags, act); else { var b = cur; flush(); if (!b) open(); } return; }
    if (tag === 'IMG') {
      var alt = (el.getAttribute('alt') || '').trim();
      if (alt) put('[' + alt + ']', flags | 8, act);
      else if (act >= 0 && acts[act].t === 'link' && !acts[act].txt) put('[image]', flags | 8, act);
      return;
    }
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'BUTTON') { field(el, tag); return; }
    if (tag === 'IFRAME') { flush(); put('[frame]', 8, -1); flush(); return; }

    var save = [kind, depth, pre, quote, flags, act, rowCell], blk = isBlock(el, cs);
    if (tag === 'HR') { flush(); kind = 'hr'; open(); flush(); kind = save[0]; return; }
    if (tag === 'TD' || tag === 'TH') {
      if (rowCell++ > 0) put(' │ ', 0, -1);
    }
    if (blk) {
      flush();
      if (/^H[1-6]$/.test(tag)) kind = tag.toLowerCase();
      else if (tag === 'LI') {
        kind = 'li';
        var p = el.parentElement;
        if (p && p.tagName === 'OL') {
          var n = parseInt(p.getAttribute('start'), 10);
          if (!isFinite(n)) n = 1;
          for (var c = p.firstElementChild; c && c !== el && n < 1e6; c = c.nextElementSibling) if (c.tagName === 'LI') n++;
          item = Math.max(1, Math.min(99999, n));           // (a page's start="1e80" fits in the margin)
        } else item = -1;
        if (laidOut && cs && cs.listStyleType === 'none') item = 0;   // menus drawn as lists: no bullets
      }
      else if (tag === 'UL' || tag === 'OL' || tag === 'DL' || tag === 'MENU' || tag === 'DIR') depth++;
      else if (tag === 'DD') { kind = 'li'; item = 0; }
      else if (tag === 'PRE') { kind = 'pre'; pre = 1; }
      else if (tag === 'BLOCKQUOTE') { quote++; kind = 'quote'; }
      else if (tag === 'TR') { kind = 'tr'; rowCell = 0; }
      else if (kind !== 'li' && kind !== 'quote' && kind !== 'pre' && kind !== 'tr') kind = 'p';
    }
    if (tag === 'SUMMARY' && el.parentElement && el.parentElement.tagName === 'DETAILS' && act < 0) {
      // a <details> heading: Return opens or closes it, as a click does
      act = addAct({t: 'button', v: el.textContent.replace(/\s+/g, ' ').trim().slice(0, 40) || 'Details',
                    det: !!el.parentElement.open}, el);
      put(el.parentElement.open ? '[-] ' : '[+] ', 0, act);
    }
    if (tag === 'A' && el.hasAttribute('href') && act < 0) {
      var h = el.href || '';
      act = addAct({t: 'link', h: h, txt: el.textContent.trim().length > 0}, el);
    }
    if (tag === 'B' || tag === 'STRONG' || (cs && +cs.fontWeight >= 600 && !blk)) flags |= 1;
    if (tag === 'I' || tag === 'EM' || tag === 'CITE') flags |= 2;
    if (tag === 'CODE' || tag === 'KBD' || tag === 'SAMP' || tag === 'TT') flags |= 4;

    var kids = children(el, tag);
    for (var k = 0; k < kids.length; k++) walk(kids[k]);

    if (blk) flush();
    kind = save[0]; depth = save[1]; pre = save[2]; quote = save[3]; flags = save[4]; act = save[5];
    if (tag === 'TR') rowCell = 0;
    if (tag === 'TABLE') rowCell = save[6];              // a table inside a cell: the outer row goes on
  }

  // What is drawn inside an element: its shadow tree if it has one (light
  // children appear only where a <slot> places them), a slot's assigned
  // nodes (or its fallback content), otherwise its children.
  function children(el, tag) {
    if (tag === 'DETAILS' && !el.open) {
      // closed: only its summary shows (Firefox hides the rest without
      // display: none, inside a shadow tree a script can't walk)
      var s = [];
      for (var c = el.firstElementChild; c; c = c.nextElementSibling) if (c.tagName === 'SUMMARY') { s.push(c); break; }
      return s;
    }
    if (el.shadowRoot) return el.shadowRoot.childNodes;
    if (tag === 'SLOT' && el.assignedNodes) {
      var a = el.assignedNodes({flatten: true});
      if (a.length) return a;
    }
    return el.childNodes;
  }

  if (doc.body) walk(doc.body);
  // drop blocks with nothing in them (but keep rules)
  var carry = [];
  blocks = blocks.filter(function (b) {
    var keep = b.k === 'hr';
    for (var i = 0; !keep && i < b.r.length; i++) if (/\S/.test(b.r[i][0])) keep = true;
    // an empty block's anchors go to the next block kept
    if (b.ids) carry = carry.concat(b.ids);
    if (!keep) { delete b.ids; return false; }
    if (carry.length) { b.ids = carry; carry = []; }
    return true;
  });
  win.__gridfox = els;
  var focus = -1;
  try { focus = els.indexOf(doc.activeElement); } catch (e) {}
  return {url: String(doc.location && doc.location.href || ''), title: doc.title || '',
          blocks: blocks, acts: acts, focus: focus, full: total >= MAXTEXT || blocks.length >= MAXBLOCKS};
})(arguments[0]);
