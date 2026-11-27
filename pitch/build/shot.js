// Снимки слайдов и PDF через локальный Chrome (DevTools Protocol, без сторонних пакетов)
// node shot.js --url <адрес> --out <папка> [--steps all|last|"3.0,3.1"] [--pdf <файл>] [--wait 1600] [--scale 1]
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn } = require('child_process');

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const URL0 = arg('url'), OUT = arg('out'), PDF = arg('pdf'), STEPS = arg('steps', 'all');
const ACTS = arg('acts'), PAGES = arg('pages');
const WAIT = +arg('wait', 1600), SCALE = +arg('scale', 1), PORT = 9300 + Math.floor(Math.random() * 500);
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'kz-shot-'));
  const chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=' + PORT, '--user-data-dir=' + prof, '--hide-scrollbars',
    '--no-first-run', '--disable-gpu', '--window-size=1920,1080', '--allow-file-access-from-files', 'about:blank'], { stdio: 'ignore' });
  let ws, id = 0;
  const wait = new Map(), errors = [];
  try {
    let target;
    for (let i = 0; i < 50 && !target; i++) {
      await sleep(200);
      try { target = (await (await fetch('http://127.0.0.1:' + PORT + '/json')).json()).find((t) => t.type === 'page'); } catch (e) {}
    }
    if (!target) throw new Error('Chrome не ответил');
    ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && wait.has(m.id)) { const [r, j] = wait.get(m.id); wait.delete(m.id); m.error ? j(new Error(m.error.message)) : r(m.result); }
      else if (m.method === 'Runtime.exceptionThrown') errors.push('EXC ' + (m.params.exceptionDetails.exception || {}).description);
      else if (m.method === 'Runtime.consoleAPICalled' && /error|warning/.test(m.params.type)) errors.push(m.params.type + ' ' + m.params.args.map((a) => a.value || a.description).join(' '));
      else if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errors.push('LOG ' + m.params.entry.text + ' ' + (m.params.entry.url || '').slice(0, 90));
    };
    const send = (method, params) => new Promise((r, j) => { wait.set(++id, [r, j]); ws.send(JSON.stringify({ id, method, params: params || {} })); });
    const ev = async (expr) => (await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result.value;
    const ready = async () => { for (let i = 0; i < 100; i++) { if (await ev('window.__ready === true')) return; await sleep(150); } throw new Error('страница не готова'); };
    await send('Page.enable'); await send('Runtime.enable'); await send('Log.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: SCALE, mobile: false });

    if (OUT) {
      fs.mkdirSync(OUT, { recursive: true });
      await send('Page.navigate', { url: URL0 });
      await ready();
      const plan = await ev('(function(){var a=[];document.querySelectorAll(".slide").forEach(function(s,i){var m=+s.dataset.steps||0;' +
        's.querySelectorAll("[data-step]").forEach(function(e){m=Math.max(m,+e.dataset.step)});a.push(m)});return a})()');
      let list = [];
      if (STEPS === 'all') plan.forEach((m, i) => { for (let k = 0; k <= m; k++) list.push([i, k]); });
      else if (STEPS === 'last') plan.forEach((m, i) => list.push([i, m]));
      else list = STEPS.split(',').map((x) => { const p = x.split('.'); return [+p[0] - 1, +p[1] || 0]; });
      for (const [i, k] of list) {
        await ev('__deck.show(' + i + ',' + k + ')');
        await sleep(WAIT + (i === 0 ? 1000 : 0) + (i === 5 ? 1200 : 0));
        const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 90 });
        const name = String(i + 1).padStart(2, '0') + '-' + k + '.jpg';
        fs.writeFileSync(path.join(OUT, name), Buffer.from(shot.data, 'base64'));
        console.log('снимок', name, JSON.stringify(await ev('__deck.state()')));
      }
      // сценарий проверки интерактива: [{eval, wait, shot, log}]
      for (const a of ACTS ? JSON.parse(fs.readFileSync(ACTS, 'utf8')) : []) {
        if (a.eval) await ev(a.eval);
        await sleep(a.wait || 800);
        if (a.shot) {
          const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 90 });
          fs.writeFileSync(path.join(OUT, a.shot + '.jpg'), Buffer.from(shot.data, 'base64'));
        }
        console.log('шаг', a.shot || '', a.log ? JSON.stringify(await ev(a.log)) : '');
      }
    }
    if (PDF) {
      await send('Page.navigate', { url: URL0 + (URL0.includes('?') ? '&' : '?') + 'print=1' });
      await ready(); await sleep(600);
      const pdf = await send('Page.printToPDF', { printBackground: true, preferCSSPageSize: true, marginTop: 0, marginBottom: 0, marginLeft: 0, marginRight: 0 });
      fs.mkdirSync(path.dirname(PDF), { recursive: true });
      fs.writeFileSync(PDF, Buffer.from(pdf.data, 'base64'));
      console.log('pdf', PDF, (fs.statSync(PDF).size / 1024).toFixed(0) + ' КБ', 'страниц', await ev('document.querySelectorAll(".slide").length'));
      if (PAGES) { // те же страницы картинками — чтобы просмотреть вёрстку PDF
        fs.mkdirSync(PAGES, { recursive: true });
        const n = await ev('document.querySelectorAll(".slide").length');
        for (let i = 0; i < n; i++) {
          const r = await ev('(function(){var b=document.querySelectorAll(".slide")[' + i + '].getBoundingClientRect();return {x:b.left+scrollX,y:b.top+scrollY,w:b.width,h:b.height}})()');
          const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 88, captureBeyondViewport: true, clip: { x: r.x, y: r.y, width: r.w, height: r.h, scale: 0.5 } });
          fs.writeFileSync(path.join(PAGES, 'p' + String(i + 1).padStart(2, '0') + '.jpg'), Buffer.from(shot.data, 'base64'));
        }
        console.log('страницы', n, '→', PAGES);
      }
    }
    console.log(errors.length ? 'ОШИБКИ В КОНСОЛИ:\n' + errors.join('\n') : 'ошибок в консоли нет');
  } finally {
    try { ws && ws.close(); } catch (e) {}
    chrome.kill();
    await sleep(400);
    try { fs.rmSync(prof, { recursive: true, force: true }); } catch (e) {}
  }
}
main().catch((e) => { console.error('СБОЙ', e.message); process.exit(1); });
