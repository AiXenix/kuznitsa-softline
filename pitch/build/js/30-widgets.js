// ——— 4. плитки: нажали — запрос уходит на живой слайд ———
function buildTiles() {
  $$('.un[data-q]').forEach(function (t) {
    t.addEventListener('click', function (e) {
      if (t.hasAttribute('data-step') && !t.classList.contains('on')) return; // ещё не раскрытая плитка
      e.stopPropagation();
      jumpToLive(t.dataset.q);
    });
  });
}

// ——— 5. допродажа и аналоги ———
function paintUpsell(s, a, lum) {
  var d = a.d, l = lum.d;
  if (d) {
    var main = itemsOf(d, ['products'], 1), cs = itemsOf(d, ['crosssell'], 4);
    el(s, 'umain').innerHTML = main.map(function (it, i) { return row(it, i); }).join('');
    el(s, 'ulist').innerHTML = cs.map(function (it, i) { return row(it, i + 1, { reason: true, bare: true }); }).join('');
    el(s, 'ums').textContent = fmtMs(d.ms);
    el(s, 'usrc').textContent = a.live ? 'ответ стенда сейчас' : 'снимок ответа стенда';
  }
  if (l) {
    var name = (/«([^»]+)»/.exec(l.note || '') || [])[1] || 'Luminar';
    el(s, 'ntxt').textContent = 'Поиск честно говорит, что «' + name + '» не продаётся, и сразу предлагает замены:';
    el(s, 'nan').innerHTML = itemsOf(l, ['analogs'], 4).map(function (it) {
      return '<div>' + thumb(it.img) + '<span>' + esc(it.t) + '</span></div>';
    }).join('');
  }
}
function paintUpsellStatic() {
  paintUpsell($('#s-upsell'), { d: snapSearch('astra linux', 'smart'), live: false }, { d: snapSearch('luminar', 'smart'), live: false });
}
hooks['s-upsell'] = {
  enter: function (s, st, tok) {
    Promise.all([search('astra linux', 'smart'), search('luminar', 'smart')]).then(function (r) {
      // живой ответ показываем, только если в нём есть и товар, и блок «вместе»: иначе остаётся снимок
      if (tok !== token || !r[0].live) return;
      if (itemsOf(r[0].d, ['products'], 1).length && itemsOf(r[0].d, ['crosssell'], 4).length >= 3) {
        paintUpsell(s, r[0], r[1].live && itemsOf(r[1].d, ['analogs'], 4).length >= 2 ? r[1] : { d: null });
      }
    }).catch(function () {});
  }
};

// ——— 6. подсказки при вводе ———
var SG_LIMIT = { corrections: 1, products: 3, categories: 1, queries: 1, upsell: 2 };
var SG_STEPS = ['rfcg', 'антив'];
var SG_TRY = ['винд', 'астра лин', 'фотош', 'бэкап'];
var sgSeq = 0, sgTypeSeq = 0;
function paintSuggest(s, r) {
  var d = r.d, html = '', n = 0;
  if (!d) return false;
  (d.groups || []).forEach(function (g) {
    var lim = SG_LIMIT[g.type], items = (g.items || []).slice(0, lim == null ? 2 : lim);
    if (!items.length) return;
    html += '<div class="sg-g ' + esc(g.type) + '"><h4>' + esc(g.title) + '</h4>' + items.map(function (it) {
      var pic = it.picture || it.image, prod = it.kind === 'product';
      var price = !prod ? '' : it.price && !it.price_on_request ? '<span class="pc">' + rub(it.price) + '</span>' : '<span class="rq">по запросу</span>';
      return '<div class="sg-i" style="--i:' + (n++) + '">' + (prod ? thumb(pic) : '<svg><use href="#i-search"/></svg>') +
        '<span class="tx">' + esc(it.text) + '</span>' + price + '</div>';
    }).join('') + '</div>';
  });
  el(s, 'drop').innerHTML = html || '<div class="sg-empty">Подсказок для такого начала нет.</div>';
  if (d.ms != null) el(s, 'sgms').textContent = d.ms < 10 ? num(Math.max(d.ms, 0.1), 1) : String(Math.round(d.ms));
  return true;
}
function askSuggest(s, q) {
  var seq = ++sgSeq;
  if (!q.trim()) { el(s, 'drop').innerHTML = '<div class="sg-empty">Начните печатать — подсказки появятся сразу.</div>'; return; }
  suggest(q).then(function (r) { if (seq === sgSeq) paintSuggest(s, r); }).catch(function () {});
}
function typeSuggest(s, q) {
  var inp = $('input', s), seq = ++sgTypeSeq;
  typeInto(function (t) { inp.value = t; if (t) askSuggest(s, t); }, q, function () { return seq === sgTypeSeq; }, 230);
}
function buildSuggest(s) {
  var inp = $('input', s), box = $('.sg-try', s);
  inp.addEventListener('input', function () { sgTypeSeq++; askSuggest(s, inp.value); });
  $('form', s).addEventListener('submit', function (e) { e.preventDefault(); if (inp.value.trim()) { inp.blur(); jumpToLive(inp.value.trim()); } });
  SG_TRY.forEach(function (q) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'chip'; b.textContent = q;
    b.addEventListener('click', function () { sgTypeSeq++; typeSuggest(s, q); });
    box.appendChild(b);
  });
}
function paintSuggestStatic(s, q) {
  $('input', s).value = q;
  paintSuggest(s, { d: D.suggest[q], live: false });
}
hooks['s-suggest'] = {
  step: function (s, st) { typeSuggest(s, SG_STEPS[st] || SG_STEPS[0]); },
  leave: function () { sgSeq++; sgTypeSeq++; }
};

// ——— 7. аналоги: один запрос — выдача замен из каталога ———
var ANALOG_CHIPS = ['аналог винды', 'аналог офиса', 'чем заменить microsoft office', 'российский аналог windows',
  'аналог teamviewer', 'замена zoom', 'чем заменить фотошоп'];
var ANALOG_STEPS = ['аналог винды', 'чем заменить microsoft office', 'замена zoom'];
var analogSeq = 0;
function paintAnalog(s, q, r) {
  var d = r.d, live = r.live, col = $('.ag-col', s), st = el(s, 'status');
  col.classList.remove('pending');
  st.classList.toggle('live', live);
  st.lastElementChild.textContent = live ? 'вживую · стенд отвечает сейчас' : 'снимок ответов стенда от 27.11';
  if (!d) {
    el(s, 'ameta').textContent = '';
    el(s, 'aund').innerHTML = '';
    el(s, 'arows').innerHTML = offBox();
    return;
  }
  var hasNote = /^(analog|out_of_catalog|renewal)$/.test(d.intent) || d.qty;
  var ai = itemsOf(d, ['analogs', 'products', 'crosssell'], 5), ab = firstBlock(d);
  el(s, 'aund').innerHTML = undChips(d, q);
  el(s, 'ameta').textContent = (ab && ab.total > ai.length ? 'найдено ' + num(ab.total, 0) + ' · ' : '') + fmtMs(d.ms);
  el(s, 'arows').innerHTML = (hasNote ? '<div class="note-row">' + esc(d.note) + '</div>' : '') +
    (ai.length ? ai.map(function (it, i) { return row(it, i); }).join('') : zeroBox('товаров', 'Подходящих товаров в каталоге нет.'));
}
function runAnalog(s, q, typed) {
  q = String(q || '').trim();
  if (!q) return;
  var seq = ++analogSeq, inp = $('input', s), alive = function () { return seq === analogSeq; };
  var st = el(s, 'status');
  $('.ag-col', s).classList.add('pending');
  st.classList.remove('live');
  st.lastElementChild.textContent = 'ищем…';
  el(s, 'ameta').textContent = 'ищем…';
  markChip(s, q);
  var data = search(q, 'smart');
  var typing = typed ? Promise.resolve(true) : typeInto(function (t) { inp.value = t; }, q, alive, 38);
  if (typed) inp.value = q;
  Promise.all([data, typing]).then(function (r) { if (alive()) paintAnalog(s, q, r[0]); }).catch(function () {});
}
function buildAnalog(s) {
  var box = $('.chips', s), inp = $('input', s);
  box.innerHTML = ANALOG_CHIPS.map(function (q) {
    return '<button type="button" class="chip" data-q="' + esc(q) + '">' + esc(q) + '</button>';
  }).join('');
  box.addEventListener('click', function (e) {
    var c = e.target.closest('.chip');
    if (c) runAnalog(s, c.dataset.q, false);
  });
  $('form', s).addEventListener('submit', function (e) { e.preventDefault(); runAnalog(s, inp.value, true); inp.blur(); });
}
function paintAnalogStatic(s, q) {
  $('input', s).value = q;
  markChip(s, q);
  paintAnalog(s, q, { d: snapSearch(q, 'smart'), live: false });
}
hooks['s-analog'] = {
  step: function (s, st) { runAnalog(s, ANALOG_STEPS[st] || ANALOG_STEPS[0], false); },
  leave: function () { analogSeq++; }
};

// ——— 8. качество: полосы по типам запросов и бегущие цифры ———
var GROUPS = [['Название продукта', 27, 27], ['Класс товара', 27, 27], ['Продление лицензии', 27, 27], ['Неверная раскладка', 27, 27],
  ['Транслит', 27, 27], ['Железо или программа', 26, 26], ['Товара нет в каталоге', 22, 22], ['Пример организаторов иначе', 29, 30],
  ['Артикул', 26, 27], ['Класс + производитель', 26, 27], ['Вопрос', 25, 27], ['Опечатка', 25, 27], ['Жаргон', 23, 25],
  ['Класс + количество', 22, 27], ['Задача своими словами', 20, 27]];
function buildBars() {
  el($('#s-quality'), 'bars').innerHTML = GROUPS.map(function (g, i) {
    return '<div class="bar' + (g[1] / g[2] < 0.85 ? ' weak' : '') + '"><span class="nm">' + esc(g[0]) + '</span><span class="tr"><i style="--w:' +
      (g[1] / g[2] * 100).toFixed(1) + '%;--i:' + i + '"></i></span><span class="vl">' + g[1] + ' / ' + g[2] + '</span></div>';
  }).join('');
}
function countUp(e, tok) {
  var to = +e.dataset.to, dec = +e.dataset.dec || 0, a = performance.now(), dur = 900;
  (function f(now) {
    if (tok !== token) { e.textContent = num(to, dec); return; }
    var k = Math.min(1, (now - a) / dur), v = to * (1 - Math.pow(1 - k, 3));
    e.textContent = num(k < 1 ? v : to, dec);
    if (k < 1) requestAnimationFrame(f);
  })(a);
}
hooks['s-quality'] = {
  enter: function (s, st, tok) {
    buildBars(); // пересобираем, чтобы полосы выросли заново
    $$('.num[data-to]', s).forEach(function (e) { countUp(e, tok); });
  }
};

// ——— 13. база знаний: слово подсвечивает свой путь и источники ———
var KB_STEPS = ['vinda', 'layout', 'typo'];
function selectWord(s, w) {
  var path = null;
  $$('.kb-words .chip[data-w]', s).forEach(function (c) { c.classList.toggle('on', c.dataset.w === w); });
  $$('.kb-p[data-w]', s).forEach(function (p) {
    var on = p.dataset.w === w;
    p.classList.toggle('on', on);
    if (on) path = p;
  });
  var src = path ? path.dataset.src.split(/\s+/) : [];
  $$('.kb-src[data-src]', s).forEach(function (b) { b.classList.toggle('on', src.indexOf(b.dataset.src) >= 0); });
  s.classList.add('sel');
}
function buildKb(s) {
  $('.kb-words', s).addEventListener('click', function (e) {
    var c = e.target.closest('.chip[data-w]');
    if (c) selectWord(s, c.dataset.w);
  });
}
hooks['s-kb'] = {
  step: function (s, st) { selectWord(s, KB_STEPS[st] || KB_STEPS[0]); }
};

// ——— запуск ———
function clonePage(src, paint) { // дополнительная страница PDF с другим состоянием того же слайда
  var c = src.cloneNode(true);
  c.removeAttribute('id');
  src.parentNode.insertBefore(c, src.nextSibling);
  paint(c);
  return c;
}
function boot() {
  var live = $('#s-live'), sg = $('#s-suggest'), analog = $('#s-analog'), kb = $('#s-kb');
  chrome();
  paintProblem(); buildBars(); paintUpsellStatic();
  buildLive(live); buildSuggest(sg); buildAnalog(analog); buildKb(kb); buildTiles();
  paintLiveStatic(live, LIVE_STEPS[0]);
  paintSuggestStatic(sg, SG_STEPS[0]);
  paintAnalogStatic(analog, ANALOG_STEPS[0]);
  selectWord(kb, KB_STEPS[0]);
  if (PRINT) {
    document.documentElement.classList.add('print');
    heroPaint($('#s-title'), HERO[0], true);
    var after = live;
    LIVE_STEPS.slice(1).forEach(function (q) { after = clonePage(after, function (c) { paintLiveStatic(c, q); }); });
    clonePage(sg, function (c) { paintSuggestStatic(c, SG_STEPS[1]); });
    after = analog;
    ANALOG_STEPS.slice(1).forEach(function (q) { after = clonePage(after, function (c) { paintAnalogStatic(c, q); }); });
    $$('.slide').forEach(function (s) { s.classList.add('active'); s.dataset.at = maxSteps(s); paintDots(s, 99); });
    $$('[data-step]').forEach(function (e) { e.classList.add('on'); });
    (document.fonts && document.fonts.ready || Promise.resolve()).then(function () { window.__ready = true; });
    return;
  }
  fit(); bindInput(); warm();
  showHash();
  window.__deck = { show: show, next: next, prev: prev, state: function () { return { cur: cur, step: step, liveUp: liveUp }; } };
  (document.fonts && document.fonts.ready || Promise.resolve()).then(function () { window.__ready = true; });
}
boot();
