// gridfox: act on element number arguments[1] of the last read (extract.js):
//   arguments[0] = 'el' | 'click' | 'set' | 'submit' | 'select' | 'stamp' | 'stamped'
//   arguments[2] = the value for set (text) or select (option index)
// 'stamp' marks this document; 'stamped' says whether it is still the same
// one, and whether it has begun to unload (a slow page on its way), so
// gridfox can tell whether an action is loading a new page.
// 'el' returns the element itself (for a real click, WebDriver:ElementClick).
// Returns {ok: true} or {ok: false, why: '...'}.
return (function (op, i, val) {
  if (op === 'stamp') {
    window.__gridfoxStamp = val; window.__gridfoxLeaving = false;
    if (!window.__gridfoxHooked) {
      window.__gridfoxHooked = true;
      var leave = function () { window.__gridfoxLeaving = true; };
      window.addEventListener('beforeunload', leave, true);
      window.addEventListener('pagehide', leave, true);
    }
    return {ok: true};
  }
  if (op === 'stamped') {
    return {ok: true, same: window.__gridfoxStamp === val, leaving: !!window.__gridfoxLeaving,
            ready: document.readyState};
  }
  var els = window.__gridfox || [], el = els[i];
  if (!el) return {ok: false, why: 'the page has changed: read it again'};
  if (!el.isConnected) return {ok: false, why: 'that is no longer on the page'};
  function fire(type) {
    el.dispatchEvent(new Event(type, {bubbles: true}));
  }
  try { el.scrollIntoView({block: 'center'}); } catch (e) {}
  if (op === 'el') return {ok: true, el: el};
  if (op === 'click') {
    if (el.focus) el.focus();
    el.click();
    return {ok: true};
  }
  if (op === 'set') {
    if (el.focus) el.focus();
    var proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    // the native setter, so frameworks that track the value (React) see the change
    var d = Object.getOwnPropertyDescriptor(proto, 'value');
    if (d && d.set) d.set.call(el, val); else el.value = val;
    fire('input'); fire('change');
    return {ok: true};
  }
  if (op === 'select') {
    el.selectedIndex = val; fire('input'); fire('change');
    return {ok: true};
  }
  if (op === 'submit') {
    var f = el.form || (el.closest && el.closest('form'));
    if (f) {
      if (f.requestSubmit) f.requestSubmit(); else f.submit();
      return {ok: true};
    }
    // no form: what a search box on a script-driven page listens for
    var o = {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true};
    el.dispatchEvent(new KeyboardEvent('keydown', o));
    el.dispatchEvent(new KeyboardEvent('keypress', o));
    el.dispatchEvent(new KeyboardEvent('keyup', o));
    return {ok: true};
  }
  return {ok: false, why: 'unknown action ' + op};
})(arguments[0], arguments[1], arguments[2]);
