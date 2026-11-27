// ——— 1. титул: строка поиска сама перебирает примеры ———
var HERO = ['винда хоум', 'rfcgthcrbq', 'мдаемон', 'антивирь', 'астра линкус'];
function heroPaint(s, q, full) {
  var d = snapSearch(q, 'smart'), und = el(s, 'hund'), rows = el(s, 'hrows');
  el(s, 'hq').textContent = q;
  if (!full || !d) { und.classList.remove('on'); rows.innerHTML = ''; return; }
  und.innerHTML = '<svg><use href="#i-ok"/></svg>Понял как <b>' + esc(d.corr || q) + '</b>';
  und.classList.add('on');
  rows.innerHTML = itemsOf(d, ['products'], 3).map(function (it, i) { return row(it, i); }).join('');
}
hooks['s-title'] = {
  enter: function (s, st, tok) {
    var i = 0, alive = function () { return tok === token; };
    (function loop() {
      if (!alive()) return;
      var q = HERO[i++ % HERO.length];
      heroPaint(s, '', false);
      sleep(450).then(function () { return typeInto(function (t) { el(s, 'hq').textContent = t; }, q, alive, 70); })
        .then(function (ok) { if (!ok) return false; return sleep(280).then(function () { if (alive()) heroPaint(s, q, true); return alive(); }); })
        .then(function (ok) { if (ok) return sleep(3000).then(loop); });
    })();
  }
};

// ——— 2. проблема: первая строка контрольного поиска из снимка ———
function paintProblem() {
  $$('.found[data-first]').forEach(function (f) {
    var d = D.search[f.dataset.first], it = d && itemsOf(d, ['products'], 1)[0];
    if (it) f.innerHTML = row(it, 0);
  });
}
hooks['s-problem'] = { enter: function () { warm(); } };

// ——— 3. живое сравнение: один запрос — два поиска ———
var LIVE_CHIPS = ['сервер', 'офис', 'винда хоум', 'мдаемон', 'антивирь', 'rfcgthcrbq', '3д макс', 'KW9-00664'];
var LIVE_STEPS = ['сервер', 'офис', 'мдаемон', 'rfcgthcrbq'];
var liveSeq = 0, jump = null; // jump — запрос, с которым пришли с другого слайда, и куда вернуться

function undChips(d, q) {
  var a = [], fb = firstBlock(d);
  if (d.corr && norm(q).indexOf(norm(d.corr)) < 0) a.push(['u', 'понял как: ' + d.corr]); // «аналог винды» → «винды» не показываем
  if (d.intent === 'out_of_catalog') a.push(['u g', 'нет в каталоге → аналоги']);
  else if (d.intent === 'category' && fb) a.push(['u g', 'раздел: ' + fb.title]);
  else if (d.it) a.push(['u g', d.it.toLowerCase()]);
  (d.chips || []).forEach(function (c) { a.push(['u g', c]); });
  if (d.src === 'jev') {
    var c = d.cost || {};
    a.push(['u ai', 'ИИ-категоризатор · ' + (c.cached ? 'из кэша, 0 ₽' : c.rub ? num(c.rub, 3) + ' ₽' : 'ответ модели')]);
  }
  return '<span class="lbl">Понял:</span>' + a.map(function (x) {
    return '<span class="' + x[0] + '">' + esc(x[1]) + '</span>';
  }).join('');
}
function zeroBox(title, text) {
  return '<div class="zero-box"><b>0</b><strong>' + esc(title) + '</strong><span>' + esc(text) + '</span></div>';
}
function offBox() {
  return '<div class="zero-box"><strong>Нет связи со стендом</strong><span>Без сети работают готовые примеры — нажмите любой из них над таблицей.</span></div>';
}
function paintLive(s, q, rn, rs) {
  var n = rn.d, m = rs.d, live = rn.live && rs.live;
  var st = el(s, 'status');
  $('.cols', s).classList.remove('pending');
  st.classList.toggle('live', live);
  st.lastElementChild.textContent = live ? 'вживую · стенд отвечает сейчас' : 'снимок ответов стенда от 27.11';
  // слева — контрольный поиск по словам
  if (!n) { el(s, 'nmeta').textContent = ''; el(s, 'nund').innerHTML = ''; el(s, 'nrows').innerHTML = offBox(); }
  else {
    var ni = n.zero === 'unknown_term' ? [] : itemsOf(n, ['products'], 5), nb = firstBlock(n);
    el(s, 'nund').innerHTML = '<span class="lbl">Ищет:</span>совпадение слов запроса с названием и описанием';
    el(s, 'nmeta').textContent = ni.length ? (nb && nb.total ? num(nb.total, 0) + ' совпад. · ' : '') + fmtMs(n.ms) : '0 совпадений';
    el(s, 'nrows').innerHTML = ni.length ? ni.map(function (it, i) { return row(it, i); }).join('') :
      zeroBox('совпадений', (/\s/.test(q.trim()) ? 'Нет товара, в котором встретились бы все слова запроса, — ' :
        'Такого слова нет ни в названиях, ни в описаниях товаров — ') + 'покупатель видит пустую страницу.');
  }
  // справа — наш поиск
  if (!m) { el(s, 'smeta').textContent = ''; el(s, 'sund').innerHTML = ''; el(s, 'srows').innerHTML = offBox(); return; }
  var note = /^(analog|out_of_catalog|renewal)$/.test(m.intent) || m.qty ? m.note : '';
  var mi = itemsOf(m, ['products', 'analogs', 'crosssell'], note ? 4 : 5), mb = firstBlock(m);
  el(s, 'sund').innerHTML = undChips(m, q);
  el(s, 'smeta').textContent = (mb && mb.total > mi.length ? (m.intent === 'category' ? num(mb.total, 0) + ' в разделе · ' : 'найдено ' + num(mb.total, 0) + ' · ') : '') + fmtMs(m.ms);
  el(s, 'srows').innerHTML = (note ? '<div class="note-row">' + esc(note) + '</div>' : '') +
    (mi.length ? mi.map(function (it, i) { return row(it, i); }).join('') : zeroBox('товаров', 'Подходящих товаров в каталоге нет.'));
}
function markChip(s, q) {
  $$('.chip', s).forEach(function (c) { c.classList.toggle('on', norm2(c.dataset.q) === norm2(q)); });
}
// typed — запрос ввели руками, набор в строке не анимируем
function runLive(s, q, typed) {
  q = String(q || '').trim();
  if (!q) return;
  var seq = ++liveSeq, inp = $('input', s), alive = function () { return seq === liveSeq; };
  var st = el(s, 'status');
  $('.cols', s).classList.add('pending');
  st.classList.remove('live');
  st.lastElementChild.textContent = 'ищем…';
  el(s, 'nmeta').textContent = 'ищем…';
  el(s, 'smeta').textContent = 'ищем…';
  markChip(s, q);
  var data = Promise.all([search(q, 'naive'), search(q, 'smart')]);
  var typing = typed ? Promise.resolve(true) : typeInto(function (t) { inp.value = t; }, q, alive, 38);
  if (typed) inp.value = q;
  Promise.all([data, typing]).then(function (r) { if (alive()) paintLive(s, q, r[0][0], r[0][1]); }).catch(function () {});
}
function buildLive(s) {
  var box = $('.chips', s), inp = $('input', s);
  box.innerHTML = LIVE_CHIPS.map(function (q) {
    return '<button type="button" class="chip" data-q="' + esc(q) + '">' + esc(q) + '</button>';
  }).join('');
  box.addEventListener('click', function (e) {
    var c = e.target.closest('.chip');
    if (c) runLive(s, c.dataset.q, false);
  });
  $('form', s).addEventListener('submit', function (e) { e.preventDefault(); runLive(s, inp.value, true); inp.blur(); });
  $('.back', s).addEventListener('click', function () {
    var j = jump; jump = null;
    s.classList.remove('ret');
    if (j) show(j.from, j.step);
  });
}
function jumpToLive(q) {
  jump = { q: q, from: cur, step: step };
  show(indexOfSlide('s-live'), 0);
}
hooks['s-live'] = {
  enter: function (s) { s.classList.toggle('ret', !!jump); },
  step: function (s, st, tok, entered) {
    if (entered && jump) return runLive(s, jump.q, false);
    runLive(s, LIVE_STEPS[st] || LIVE_STEPS[0], false);
  },
  leave: function (s) { liveSeq++; jump = null; s.classList.remove('ret'); }
};
// Статичная отрисовка по снимку: для PDF и на случай, если слайд увидят до ответа стенда
function paintLiveStatic(s, q) {
  $('input', s).value = q;
  markChip(s, q);
  paintLive(s, q, { d: snapSearch(q, 'naive'), live: false }, { d: snapSearch(q, 'smart'), live: false });
}
