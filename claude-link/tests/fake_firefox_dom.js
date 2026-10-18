// The page side of the stand-in Firefox (fake_firefox.py): jsdom, one page at
// a time, driven by JSON lines on stdin.
//   {op: 'load', url, html}          -> {ok}
//   {op: 'exec', script, args}       -> {ok, value} or {ok: false, error}; {nav} if it followed
//                                       a link or sent a form (jsdom itself doesn't navigate)
//   {op: 'lines'}                    -> {ok, lines: [[text, kind]], y}: the stand-in's "layout" for
//                                       its screenshot, one line of 16 pixels a block or link
//   {op: 'point', x, y, down}        -> a click at viewport (x, y): the line's link, button or field
//   {op: 'key', value}               -> a key (WebDriver's code) to the focused field
//   {op: 'resize', w, h}             -> window.innerWidth and innerHeight
const {JSDOM, VirtualConsole} = require('jsdom');
const readline = require('readline');

let dom = null, nav = null, sy = 0, size = [1024, 768], laid = [];
const ELEMENT = 'element-6066-11e4-a52e-4f735466cecf';
let elements = [];                      // web element references handed out for this page

// what Marionette does to a script's result: elements become references
function serial(v, w) {
  if (v === undefined || v === null) return null;
  if (v instanceof w.Element) { elements.push(v); return {[ELEMENT]: String(elements.length - 1)}; }
  if (Array.isArray(v)) return v.map((x) => serial(x, w));
  if (typeof v === 'object') { const o = {}; for (const k of Object.keys(v)) o[k] = serial(v[k], w); return o; }
  return v;
}

function load(url, html) {
  const vc = new VirtualConsole();           // (quiet: "navigation not implemented" and the like)
  dom = new JSDOM(html, {url, runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc});
  elements = [];
  const w = dom.window;
  // scrolling, which jsdom doesn't do: whole lines of the stand-in's layout
  sy = 0;
  Object.defineProperty(w, 'scrollY', {get: () => sy, configurable: true});
  Object.defineProperty(w, 'innerWidth', {get: () => size[0], configurable: true});
  Object.defineProperty(w, 'innerHeight', {get: () => size[1], configurable: true});
  Object.defineProperty(w.document.documentElement, 'scrollHeight', {get: () => layout().length * 16, configurable: true});
  const clamp = () => { sy = Math.max(0, Math.min(sy, Math.max(0, layout().length * 16 - size[1]))); };
  w.scrollBy = function (o, y) { sy += (typeof o === 'object' ? o.top : y) || 0; clamp(); };
  w.scrollTo = function (o, y) { sy = (typeof o === 'object' ? o.top : y) || 0; clamp(); };
  // what a browser would do after the page's own handlers: follow the link, send the form
  w.addEventListener('click', (e) => {
    if (e.defaultPrevented) return;
    const a = e.target.closest && e.target.closest('a[href]');
    if (a) {
      const here = w.location.href.split('#')[0], there = a.href.split('#')[0];
      if (there === here && a.href.includes('#')) { w.location.hash = a.href.split('#')[1]; return; }  // same document
      nav = a.href; return;
    }
    const b = e.target.closest && e.target.closest('button, input[type=submit], input[type=image]');
    if (b && b.form && (b.type || 'submit') === 'submit') b.form.requestSubmit(b.tagName === 'BUTTON' || b.type === 'submit' ? b : undefined);
  });
  w.addEventListener('submit', (e) => {
    if (e.defaultPrevented) return;
    const f = e.target;
    const u = new w.URL(f.getAttribute('action') || w.location.href, w.location.href);
    const q = new w.URLSearchParams();
    for (const el of f.elements) {
      if (!el.name || el.disabled) continue;
      if ((el.type === 'checkbox' || el.type === 'radio') && !el.checked) continue;
      if (el.type === 'submit' || el.type === 'button' || el.type === 'image') { if (el !== e.submitter) continue; }
      q.append(el.name, el.value);
    }
    u.search = q.toString();
    nav = u.href;
    e.preventDefault();
  });
}

// The stand-in's layout: a line for each heading, paragraph or list item
// (its own text, without its links), and a line for each link, button or field.
function layout() {
  const d = dom.window.document, out = [];
  const keep = 'h1,h2,h3,h4,p,li,pre,a[href],button,input,textarea,select';
  for (const el of d.body ? d.body.querySelectorAll(keep) : []) {
    if (el.matches('a[href],button,input,textarea,select')) {
      const t = el.matches('input,textarea') ? '[' + (el.value || el.placeholder || el.name || '') + ']'
                                             : el.textContent.trim();
      out.push([t || '(link)', el.tagName.toLowerCase(), el]);
      continue;
    }
    let t = '';
    for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent;
    t = t.replace(/\s+/g, ' ').trim();
    if (t) out.push([t, 'text', el]);
  }
  laid = out;
  return out;
}

const rl = readline.createInterface({input: process.stdin});
rl.on('line', (line) => {
  const m = JSON.parse(line);
  let out;
  try {
    if (m.op === 'load') { load(m.url, m.html); out = {ok: true}; }
    else if (m.op === 'exec') {
      nav = null;
      const fn = dom.window.eval('(function(){' + m.script + '\n})');
      const v = fn.apply(dom.window, m.args || []);
      out = {ok: true, value: serial(v, dom.window)};
      if (nav) out.nav = nav;
    } else if (m.op === 'click') {
      nav = null;
      const el = elements[+m.id];
      if (!el || !el.isConnected) out = {ok: false, error: 'stale element reference'};
      else if (el.hasAttribute('data-covered')) out = {ok: false, error: 'element click intercepted'};
      else { el.click(); out = {ok: true, value: null}; if (nav) out.nav = nav; }
    } else if (m.op === 'lines') {
      out = {ok: true, lines: layout().map((l) => [l[0], l[1]]), y: sy, w: size[0], h: size[1]};
    } else if (m.op === 'resize') {
      size = [m.w, m.h]; out = {ok: true};
    } else if (m.op === 'point') {
      nav = null;
      const l = layout()[Math.floor((m.y + sy) / 16)];
      out = {ok: true, hit: l ? l[1] : null};
      if (l && l[1] !== 'text') {
        if (l[2].matches('input,textarea')) l[2].focus();
        else l[2].click();
      }
      if (nav) out.nav = nav;
    } else if (m.op === 'key') {
      nav = null;
      const el = dom.window.document.activeElement;
      out = {ok: true};
      if (el && el.matches && el.matches('input,textarea')) {
        if (m.value === '\ue003') el.value = el.value.slice(0, -1);
        else if (m.value === '\ue007') { if (el.form) el.form.requestSubmit(); }
        else if (m.value.length === 1 && m.value < '\ue000') el.value += m.value;
        out.typed = el.value;
      }
      if (nav) out.nav = nav;
    } else if (m.op === 'unload') {
      // a slow page on its way: the old one gets beforeunload and pagehide, and stays up
      dom.window.dispatchEvent(new dom.window.Event('beforeunload'));
      dom.window.dispatchEvent(new dom.window.Event('pagehide'));
      out = {ok: true};
    } else out = {ok: false, error: 'unknown op'};
  } catch (e) {
    out = {ok: false, error: String(e && e.stack || e)};
  }
  process.stdout.write(JSON.stringify(out) + '\n');
});
