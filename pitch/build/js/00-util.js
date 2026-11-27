'use strict';
// Данные, зашитые в файл: снимки ответов стенда, подсказки и миниатюры
var D = JSON.parse(document.getElementById('deck-data').textContent);
var PRINT = /[?&]print\b/.test(location.search);
var CAN_LIVE = !PRINT && location.protocol !== 'file:';
var liveUp = null; // null — ещё не проверяли, true/false — последний известный ответ стенда
var liveGen = 0;

function $(s, r) { return (r || document).querySelector(s); }
function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
function el(root, name) { return root.querySelector('[data-el="' + name + '"]'); }
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}
function norm(s) { return String(s || '').toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ').trim(); }
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function num(n, dec) {
  var s = Number(n).toFixed(dec == null ? (n % 1 ? 2 : 0) : dec).split('.');
  s[0] = s[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  return s.join(',');
}
function rub(n) { return num(n) + ' ₽'; }
function fmtMs(ms) {
  if (ms == null) return '';
  return (ms < 10 ? num(Math.max(ms, 0.1), 1) : String(Math.round(ms))) + ' мс';
}
function timeoutSignal(ms) {
  if (window.AbortSignal && AbortSignal.timeout) return AbortSignal.timeout(ms);
  var c = new AbortController();
  setTimeout(function () { c.abort(); }, ms);
  return c.signal;
}

// Ответ стенда → короткая запись (тот же формат, что у снимков в D.search)
function cItem(i) {
  var c = i.card || i, o = c.offer || {};
  return {
    t: c.title, v: (c.vendor || {}).name, c: (c.category || {}).title, p: (c.calc || {}).text,
    pf: c.price_from, por: o.price_on_request, old: o.oldprice, pr: o.price,
    img: c.picture || c.image, k: i.kind || c.kind, fill: !!(i.fill || c.fill),
    label: i.label || c.label, r: i.reason || c.reason || i.note
  };
}
function compact(d) {
  var u = d.understood || {}, q = d.query || {};
  return {
    q: q.raw, mode: d.mode, corr: q.corrected, intent: u.intent, it: u.intent_title, src: u.intent_source,
    note: u.agent_note, zero: u.zero_reason, chips: (u.chips || []).map(function (c) { return c.label; }), qty: u.qty,
    blocks: (d.blocks || []).map(function (b) {
      return { type: b.type, title: b.title, total: b.total, items: (b.items || []).slice(0, 8).map(cItem) };
    }),
    notes: d.notes, ms: (d.timing_ms || {}).total, cost: d.cost
  };
}

function apiSearch(q, mode, ms) {
  return fetch('/api/search', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ q: q, mode: mode, source: 'api' }), signal: timeoutSignal(ms)
  }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (d) { if (!d || !Array.isArray(d.blocks)) throw new Error('Bad response'); return compact(d); });
}
function snapSearch(q, mode) { return D.search[norm2(q) + '|' + mode] || null; }
function norm2(q) { return String(q || '').toLowerCase().replace(/\s+/g, ' ').trim(); }

// Проверка стенда: без ответа сразу работаем по снимкам и не заставляем зал ждать
function probe() {
  if (!CAN_LIVE) { liveUp = false; return Promise.resolve(false); }
  var gen = ++liveGen;
  return fetch('/health', { signal: timeoutSignal(2500), cache: 'no-store' })
    .then(function (r) { if (gen !== liveGen) return liveUp !== false; liveUp = r.ok; return liveUp; })
    .catch(function () { if (gen !== liveGen) return liveUp !== false; liveUp = false; return false; });
}
var probeTimer = 0;
function reprobeLater() {
  if (!CAN_LIVE || probeTimer) return;
  probeTimer = setTimeout(function () { probeTimer = 0; probe().then(function (ok) { if (!ok) reprobeLater(); }); }, 8000);
}
// → {d, live}; d === null, если стенд недоступен и снимка такого запроса нет
function search(q, mode) {
  var s = snapSearch(q, mode);
  if (!CAN_LIVE || liveUp === false) { reprobeLater(); return Promise.resolve({ d: s, live: false }); }
  var gen = ++liveGen, p = apiSearch(q, mode, mode === 'smart' ? 6000 : 3500);
  if (mode === 'smart') p = p.catch(function () { return apiSearch(q, 'fast', 3000); });
  return p.then(function (d) { if (gen === liveGen) liveUp = true; return { d: d, live: true }; })
    .catch(function () { if (gen === liveGen) { liveUp = false; reprobeLater(); } return { d: s, live: false }; });
}
function suggest(q) {
  var s = D.suggest[norm2(q)] || null;
  if (!CAN_LIVE || liveUp === false) return Promise.resolve({ d: s, live: false });
  return fetch('/api/suggest?q=' + encodeURIComponent(q), { signal: timeoutSignal(2500) })
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (d) { if (!d || !Array.isArray(d.groups)) throw new Error('Bad response'); return { d: d, live: true }; })
    .catch(function () { return { d: s, live: false }; });
}
function warm() {
  if (!CAN_LIVE) return;
  probe().then(function (ok) {
    if (!ok) return reprobeLater();
    apiSearch('сервер', 'smart', 8000).catch(function () {});
    apiSearch('сервер', 'naive', 8000).catch(function () {});
    fetch('/api/suggest?q=rfcg', { signal: timeoutSignal(8000) }).catch(function () {});
  });
}

// ——— отрисовка карточек ———
function thumb(url) {
  var src = url && D.img[url];
  if (src) return '<span class="th"><img alt="" src="' + src + '"></span>';
  if (url && !PRINT) {
    return '<span class="th"><img alt="" referrerpolicy="no-referrer" src="' + esc(url) +
      '" onerror="this.parentNode.classList.add(\'noimg\');this.remove()"></span>';
  }
  return '<span class="th noimg"></span>';
}
function salePct(it) {
  return it.old && it.pr && it.old > it.pr ? Math.round((1 - it.pr / it.old) * 100) : 0;
}
function priceHtml(it) {
  var p = it.p || '';
  if (!p && it.pr && !it.por) p = 'от ' + rub(it.pr);
  if (!p || it.por) return '<div class="pr req">Цена по запросу</div>';
  if (/[×=]/.test(p)) { // расчёт на тираж: «20 × 3 004,02 ₽ = 60 080,40 ₽»
    p = p.replace(/(\d)\s(?=\d{3}(\D|$))/g, '$1 ').replace(/\s₽/g, ' ₽'); // число и знак рубля не рвём переносом
    var k = p.lastIndexOf('=');
    if (k < 0) return '<div class="pr calc">' + esc(p) + '</div>';
    return '<div class="pr calc">' + esc(p.slice(0, k).trim()) + '<b>' + esc(p.slice(k + 1).trim()) + '</b></div>';
  }
  var m = /^(.*?₽)\s*(.*)$/.exec(p), main = m ? m[1] : p, unit = m ? m[2] : '';
  if (unit === 'за лицензию') unit = '';
  var old = salePct(it) ? '<s>' + rub(it.old) + '</s>' : '';
  return '<div class="pr">' + old + esc(main) + (unit ? '<small>' + esc(unit) + '</small>' : '') + '</div>';
}
function metaText(it) {
  var v = it.v && !/^Программы и/.test(it.v) ? it.v : '';
  return v || it.c || '';
}
// opt: reason — показывать «почему здесь», bare — без меток и строки производителя
function row(it, i, opt) {
  opt = opt || {};
  var up = it.k === 'upsell', lb = '', pct = salePct(it);
  if (pct) lb += '<span class="lb sale">Акция −' + pct + ' %</span>';
  if (up) lb += '<span class="lb up">Вам может пригодиться</span>';
  else if (it.fill) lb += '<span class="lb fl">' + esc(it.label || 'Похожие товары') + '</span>';
  var meta = opt.bare ? '' : '<div class="pm">' + lb + '<span>' + esc(metaText(it)) + '</span></div>';
  var rs = opt.reason && it.r ? '<div class="prs">' + esc(it.r) + '</div>' : '';
  return '<div class="prow' + (up ? ' up' : '') + '" style="--i:' + i + '">' + thumb(it.img) +
    '<div class="pt"><div class="pn">' + esc(it.t) + '</div>' + meta + rs + '</div>' + priceHtml(it) + '</div>';
}
function itemsOf(d, types, n) {
  var out = [];
  (d && d.blocks || []).forEach(function (b) {
    if (types.indexOf(b.type) >= 0) out = out.concat(b.items || []);
  });
  return n ? out.slice(0, n) : out;
}
function firstBlock(d) {
  return (d && d.blocks || []).filter(function (b) { return b.items && b.items.length; })[0] || null;
}
// Посимвольный набор; ok() === false — слайд сменился, набор бросаем
function typeInto(setText, text, ok, delay) {
  var i = 0;
  function tick() {
    if (!ok()) return Promise.resolve(false);
    setText(text.slice(0, i));
    if (i >= text.length) return Promise.resolve(true);
    i++;
    return sleep(delay || 55).then(tick);
  }
  return tick();
}
