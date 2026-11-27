// ——— движок: сцена, шаги, клавиши, таймер ———
var stage = $('#stage');
var slides = $$('.slide');
var cur = 0, step = 0, token = 0, started = false;
var hooks = {};
var PLAN = slides.map(function (s) { return +s.dataset.time || 0; });
var TOTAL = PLAN.reduce(function (a, b) { return a + b; }, 0);
var t0 = 0; // момент старта выступления; 0 — ещё не начали

function maxSteps(s) {
  if (s.dataset.steps) return +s.dataset.steps;
  var m = 0;
  $$('[data-step]', s).forEach(function (e) { m = Math.max(m, +e.dataset.step); });
  return m;
}
function fit() {
  if (PRINT) return;
  var k = Math.min(innerWidth / 1920, innerHeight / 1080);
  stage.style.transform = 'translate(-50%,-50%) scale(' + k + ')';
}
function chrome() {
  slides.forEach(function (s, i) {
    var n = i + 1, plain = s.id !== 's-title' && s.id !== 's-final', dots = '';
    for (var k = 0, m = maxSteps(s); m && k <= m; k++) dots += '<i></i>';
    var hd = document.createElement('div');
    hd.className = 'hd';
    hd.innerHTML = '<div class="logo"><svg viewBox="0 0 793.7 114.2"><use href="#i-logo"/></svg><span>Кузница Softline</span></div>' +
      (plain ? '<div class="trk">Хакатон «ИИкузница» · умный поиск</div>' : '');
    var ft = document.createElement('div');
    ft.className = 'ft';
    ft.innerHTML = '<span>' + (plain ? 'Команда AiXenix' : '') + '</span><div class="pos"><div class="dots">' + dots +
      '</div><span class="cnt"><b>' + n + '</b> / ' + slides.length + '</span></div>';
    s.insertBefore(hd, s.firstChild);
    s.appendChild(ft);
  });
}
function paintDots(s, st) {
  $$('.ft .dots i', s).forEach(function (d, k) { d.classList.toggle('on', PRINT || k <= st); });
}
function show(i, st) {
  i = Math.max(0, Math.min(slides.length - 1, i));
  var changed = !started || i !== cur;
  if (changed) {
    slides[cur].classList.remove('active');
    if (started && hooks[slides[cur].id] && hooks[slides[cur].id].leave) hooks[slides[cur].id].leave(slides[cur]);
    cur = i;
    slides[cur].classList.add('active');
    token++;
  }
  started = true;
  var s = slides[cur];
  step = Math.max(0, Math.min(maxSteps(s), st || 0));
  s.dataset.at = step;
  $$('[data-step]', s).forEach(function (e) { e.classList.toggle('on', +e.dataset.step <= step); });
  paintDots(s, step);
  try { history.replaceState(null, '', '#' + (cur + 1) + (step ? '.' + step : '')); } catch (e) {}
  var h = hooks[s.id];
  if (h && changed && h.enter) h.enter(s, step, token);
  if (h && h.step) h.step(s, step, token, changed);
  syncSpeaker();
  tickTimer();
}
function showHash() {
  var m = /^#(\d+)(?:\.(\d+))?$/.exec(location.hash);
  var i = m ? +m[1] - 1 : 0, st = m ? +m[2] || 0 : 0;
  if (started && i === cur && st === step) return;
  show(i, st);
}
function next() {
  if (!t0) t0 = Date.now();
  if (step < maxSteps(slides[cur])) show(cur, step + 1);
  else if (cur < slides.length - 1) show(cur + 1, 0);
}
function prev() {
  if (step > 0) show(cur, step - 1);
  else if (cur > 0) show(cur - 1, maxSteps(slides[cur - 1]));
}
function indexOfSlide(id) { return slides.indexOf(document.getElementById(id)); }

// ——— таймер и отставание от плана ———
function mmss(sec) {
  var a = Math.abs(Math.round(sec));
  return (sec < 0 ? '−' : '') + Math.floor(a / 60) + ':' + ('0' + (a % 60)).slice(-2);
}
function planUpTo(i) { // сколько секунд по плану должно пройти к концу слайда i
  var a = 0;
  for (var k = 0; k <= i; k++) a += PLAN[k];
  return a;
}
function elapsed() { return t0 ? (Date.now() - t0) / 1000 : 0; }
function tickTimer() {
  var hud = $('#hud-timer'), e = elapsed();
  hud.textContent = mmss(e) + ' / ' + mmss(TOTAL);
  hud.classList.toggle('late', e > planUpTo(cur) + 10);
  if (speaker && !speaker.closed) {
    var d = speaker.document, lag = e - planUpTo(cur);
    var te = d.getElementById('t'), tl = d.getElementById('lag');
    if (te) te.textContent = mmss(e) + ' / ' + mmss(TOTAL);
    if (tl) {
      tl.textContent = !t0 ? 'Таймер пойдёт с первого перехода' :
        lag > 10 ? 'Отстаёте на ' + mmss(lag) + ' — ускоряйтесь' :
        'По плану к концу слайда: ' + mmss(planUpTo(cur)) + ' · запас ' + mmss(Math.max(0, -lag));
      tl.className = t0 && lag > 10 ? 'late' : '';
    }
  }
}

// ——— окно суфлёра ———
var speaker = null;
var SPEAKER_HTML = '<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Суфлёр · Кузница Softline</title><style>' +
  'body{margin:0;font:400 22px/1.5 "Segoe UI",Roboto,Arial,sans-serif;background:#16181c;color:#e8e9ec;padding:26px 34px}' +
  '#top{display:flex;justify-content:space-between;align-items:baseline;gap:20px;border-bottom:1px solid #33363d;padding-bottom:14px}' +
  '#ttl{font-size:26px;font-weight:700}#t{font:700 40px/1 Consolas,monospace;color:#fff}' +
  '#lag{font-size:18px;color:#9aa0aa;margin-top:10px}#lag.late{color:#ff8fa6;font-weight:700}' +
  '#notes p{margin:18px 0;padding:14px 18px;border-radius:10px;color:#868b95;border-left:5px solid transparent}' +
  '#notes p.now{color:#fff;background:#23262c;border-left-color:#d2143a;font-size:27px;line-height:1.45}' +
  '#notes p.done{color:#5d626b}#notes p::before{content:attr(data-k);display:block;font-size:14px;font-weight:700;letter-spacing:.1em;color:#d2143a;text-transform:uppercase}' +
  '#nx{margin-top:22px;font-size:18px;color:#9aa0aa;border-top:1px solid #33363d;padding-top:14px}' +
  'button{font:600 18px "Segoe UI",sans-serif;padding:10px 22px;margin:14px 10px 0 0;border-radius:8px;border:1px solid #4a4e57;background:#23262c;color:#fff;cursor:pointer}' +
  '</style></head><body><div id="top"><div id="ttl"></div><div id="t">0:00</div></div><div id="lag"></div><div id="notes"></div>' +
  '<div id="nx"></div><button id="bp">← Назад</button><button id="bn">Дальше →</button><button id="br">Сбросить таймер</button></body></html>';
function openSpeaker() {
  if (speaker && !speaker.closed) { speaker.focus(); return; }
  speaker = window.open('', 'kz-speaker', 'width=1040,height=780');
  if (!speaker) { toast('Браузер заблокировал окно суфлёра — разрешите всплывающие окна'); return; }
  speaker.document.open(); speaker.document.write(SPEAKER_HTML); speaker.document.close();
  var d = speaker.document;
  d.getElementById('bn').onclick = next;
  d.getElementById('bp').onclick = prev;
  d.getElementById('br').onclick = function () { t0 = 0; tickTimer(); };
  d.addEventListener('keydown', onKey);
  syncSpeaker();
}
function syncSpeaker() {
  if (!speaker || speaker.closed) return;
  var d = speaker.document, s = slides[cur], html = '';
  d.getElementById('ttl').textContent = (cur + 1) + ' / ' + slides.length + ' · ' + (s.dataset.title || '');
  $$('.notes p', s).forEach(function (p) {
    var at = +p.dataset.at || 0;
    html += '<p class="' + (at === step ? 'now' : at < step ? 'done' : '') + '" data-k="' +
      (at ? 'клик ' + at : 'сразу') + '">' + esc(p.textContent) + '</p>';
  });
  d.getElementById('notes').innerHTML = html;
  var left = maxSteps(s) - step, nx = slides[cur + 1];
  d.getElementById('nx').textContent = (left ? 'На этом слайде ещё кликов: ' + left + '. ' : '') +
    (nx ? 'Дальше: ' + (nx.dataset.title || '') : 'Это последний слайд');
  var now = d.querySelector('#notes p.now');
  if (now && now.scrollIntoView) now.scrollIntoView({ block: 'nearest' });
}

// ——— клавиши, клики, жесты ———
var numbuf = '', toastTimer = 0;
function toast(t) {
  var e = $('#toast');
  e.textContent = t; e.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { e.classList.remove('on'); }, 3200);
}
function setNum(v) {
  numbuf = v;
  var e = $('#numbuf');
  e.textContent = 'Слайд ' + v + ' — Enter';
  e.classList.toggle('on', !!v);
}
function onKey(e) {
  var inField = e.target && /^(INPUT|TEXTAREA)$/.test(e.target.tagName);
  if (inField) { if (e.key === 'Escape') e.target.blur(); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  var c = e.code, k = e.key;
  if ($('#help').classList.contains('on') && c !== 'KeyH') { $('#help').classList.remove('on'); if (c === 'Escape') return; }
  if (/^\d$/.test(k)) { setNum((numbuf + k).slice(-2)); return e.preventDefault(); }
  if (c === 'Enter' || c === 'NumpadEnter') {
    if (numbuf) { var n = +numbuf; setNum(''); if (n >= 1 && n <= slides.length) show(n - 1, 0); } else next();
    return e.preventDefault();
  }
  if (numbuf) setNum('');
  if (c === 'ArrowRight' || c === 'Space' || c === 'PageDown' || c === 'ArrowDown') { next(); e.preventDefault(); }
  else if (c === 'ArrowLeft' || c === 'PageUp' || c === 'Backspace' || c === 'ArrowUp') { prev(); e.preventDefault(); }
  else if (c === 'Home') show(0, 0);
  else if (c === 'End') show(slides.length - 1, 0);
  else if (c === 'KeyF') { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen().catch(function () {}); }
  else if (c === 'KeyP') openSpeaker();
  else if (c === 'KeyB') $('#black').classList.toggle('on');
  else if (c === 'KeyT') $('#hud-timer').classList.toggle('on');
  else if (c === 'KeyR') { t0 = 0; tickTimer(); toast('Таймер сброшен'); }
  else if (c === 'KeyH') $('#help').classList.toggle('on');
  else if (c === 'Escape') $('#black').classList.remove('on');
}
function bindInput() {
  document.addEventListener('keydown', onKey);
  stage.addEventListener('click', function (e) {
    if (e.target.closest('[data-nonav],a,button,input,form')) return;
    next();
  });
  $('#black').addEventListener('click', function () { this.classList.remove('on'); });
  $('#help').addEventListener('click', function () { this.classList.remove('on'); });
  var tx = 0, ty = 0;
  document.addEventListener('touchstart', function (e) { tx = e.touches[0].clientX; ty = e.touches[0].clientY; }, { passive: true });
  document.addEventListener('touchend', function (e) {
    if (e.target.closest && e.target.closest('[data-nonav],input,button')) return;
    var dx = e.changedTouches[0].clientX - tx, dy = e.changedTouches[0].clientY - ty;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) { if (dx < 0) next(); else prev(); }
  }, { passive: true });
  addEventListener('resize', fit);
  addEventListener('hashchange', showHash);
  setInterval(tickTimer, 500);
}
