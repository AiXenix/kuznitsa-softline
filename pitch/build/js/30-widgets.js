// ——— 4. плитки: нажали — запрос уходит на живой слайд ———
function buildTiles() {
  $$('.un[data-q]').forEach(function (t) {
    t.addEventListener('click', function (e) {
      if (!t.classList.contains('on')) return;
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

// ——— запуск ———
function clonePage(src, paint) { // дополнительная страница PDF с другим состоянием того же слайда
  var c = src.cloneNode(true);
  c.removeAttribute('id');
  src.parentNode.insertBefore(c, src.nextSibling);
  paint(c);
  return c;
}
function boot() {
  var live = $('#s-live'), sg = $('#s-suggest');
  chrome();
  paintProblem(); buildBars(); paintUpsellStatic();
  buildLive(live); buildSuggest(sg); buildTiles();
  paintLiveStatic(live, LIVE_STEPS[0]);
  paintSuggestStatic(sg, SG_STEPS[0]);
  if (PRINT) {
    document.documentElement.classList.add('print');
    heroPaint($('#s-title'), HERO[0], true);
    var after = live;
    LIVE_STEPS.slice(1).forEach(function (q) { after = clonePage(after, function (c) { paintLiveStatic(c, q); }); });
    clonePage(sg, function (c) { paintSuggestStatic(c, SG_STEPS[1]); });
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
