// The page side of the stand-in Firefox (fake_firefox.py): jsdom, one page at
// a time, driven by JSON lines on stdin.
//   {op: 'load', url, html}          -> {ok}
//   {op: 'exec', script, args}       -> {ok, value} or {ok: false, error}; {nav} if it followed
//                                       a link or sent a form (jsdom itself doesn't navigate)
const {JSDOM, VirtualConsole} = require('jsdom');
const readline = require('readline');

let dom = null, nav = null;
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
  // what a browser would do after the page's own handlers: follow the link, send the form
  w.addEventListener('click', (e) => {
    if (e.defaultPrevented) return;
    const a = e.target.closest && e.target.closest('a[href]');
    if (a) { nav = a.href; return; }
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
