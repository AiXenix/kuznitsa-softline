// Проверка окна суфлёра и клавиш: node ptest.js <адрес> [папка для снимка]
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn } = require('child_process');

const URL0 = process.argv[2], OUT = process.argv[3], PORT = 9300 + Math.floor(Math.random() * 500);
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function connect(url) {
  const ws = new WebSocket(url), wait = new Map(), errors = [];
  let id = 0;
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && wait.has(m.id)) { const [r, j] = wait.get(m.id); wait.delete(m.id); m.error ? j(new Error(m.error.message)) : r(m.result); }
    else if (m.method === 'Runtime.exceptionThrown') errors.push('EXC ' + (m.params.exceptionDetails.exception || {}).description);
  };
  const send = (method, params) => new Promise((r, j) => { wait.set(++id, [r, j]); ws.send(JSON.stringify({ id, method, params: params || {} })); });
  const ev = async (expr) => (await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result.value;
  return new Promise((r, j) => { ws.onopen = () => r({ ws, send, ev, errors }); ws.onerror = j; });
}
const KEYS = { p: ['KeyP', 80], ArrowRight: ['ArrowRight', 39], ArrowLeft: ['ArrowLeft', 37], b: ['KeyB', 66], ' ': ['Space', 32], Enter: ['Enter', 13], 7: ['Digit7', 55], 3: ['Digit3', 51], End: ['End', 35] };
async function key(c, k) {
  const [code, vk] = KEYS[k];
  await c.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', key: k, code, windowsVirtualKeyCode: vk });
  await c.send('Input.dispatchKeyEvent', { type: 'keyUp', key: k, code, windowsVirtualKeyCode: vk });
  await sleep(500);
}

async function main() {
  const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'kz-ptest-'));
  const chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=' + PORT, '--user-data-dir=' + prof, '--no-first-run', '--disable-gpu',
    '--window-size=1920,1080', '--allow-file-access-from-files', 'about:blank'], { stdio: 'ignore' });
  const list = async () => (await (await fetch('http://127.0.0.1:' + PORT + '/json')).json()).filter((t) => t.type === 'page');
  let main, pop;
  try {
    let target;
    for (let i = 0; i < 50 && !target; i++) { await sleep(200); try { target = (await list())[0]; } catch (e) {} }
    main = await connect(target.webSocketDebuggerUrl);
    await main.send('Page.enable'); await main.send('Runtime.enable');
    await main.send('Page.navigate', { url: URL0 });
    for (let i = 0; i < 100 && !(await main.ev('window.__ready === true')); i++) await sleep(150);
    await key(main, 'p');
    const pages = await list();
    console.log('окон после P:', pages.length, pages.map((p) => p.title).join(' | '));
    const pt = pages.find((p) => p.id !== target.id);
    if (!pt) throw new Error('окно суфлёра не открылось: ' + await main.ev('document.getElementById("toast").textContent'));
    pop = await connect(pt.webSocketDebuggerUrl);
    await pop.send('Runtime.enable');
    const read = () => pop.ev('JSON.stringify({ttl:document.getElementById("ttl").textContent,t:document.getElementById("t").textContent,' +
      'lag:document.getElementById("lag").textContent,now:(document.querySelector("#notes p.now")||{}).textContent,n:document.querySelectorAll("#notes p").length,' +
      'nx:document.getElementById("nx").textContent})');
    console.log('суфлёр на старте  ', await read());
    await key(main, 'ArrowRight');
    console.log('→ в основном окне ', await read(), JSON.stringify(await main.ev('__deck.state()')));
    await key(pop, 'ArrowRight'); await key(pop, ' ');
    console.log('→ и пробел в суфлёре', await read(), JSON.stringify(await main.ev('__deck.state()')));
    await pop.ev('document.getElementById("bn").click()'); await sleep(400);
    await pop.ev('document.getElementById("bp").click()'); await sleep(400);
    console.log('кнопки дальше/назад', await read(), JSON.stringify(await main.ev('__deck.state()')));
    await key(main, '7'); await key(main, 'Enter');
    console.log('7 + Enter          ', await read(), JSON.stringify(await main.ev('__deck.state()')));
    await key(main, 'b');
    console.log('B — тёмный экран   ', await main.ev('document.getElementById("black").classList.contains("on")'));
    await key(main, 'b'); await key(main, 'End'); await key(main, 'ArrowRight');
    await sleep(1600);
    console.log('End и → на последнем', await read(), JSON.stringify(await main.ev('__deck.state()')));
    await pop.ev('document.getElementById("br").click()'); await sleep(700);
    console.log('сброс таймера      ', await read());
    if (OUT) {
      fs.mkdirSync(OUT, { recursive: true });
      await key(main, '3'); await key(main, 'Enter'); await key(main, 'ArrowRight');
      await pop.send('Emulation.setDeviceMetricsOverride', { width: 1040, height: 780, deviceScaleFactor: 1, mobile: false });
      await sleep(600);
      const shot = await pop.send('Page.captureScreenshot', { format: 'jpeg', quality: 90 });
      fs.writeFileSync(path.join(OUT, 'speaker.jpg'), Buffer.from(shot.data, 'base64'));
      console.log('снимок суфлёра → speaker.jpg');
    }
    const errs = main.errors.concat(pop.errors);
    console.log(errs.length ? 'ОШИБКИ:\n' + errs.join('\n') : 'исключений нет');
  } finally {
    try { main && main.ws.close(); pop && pop.ws.close(); } catch (e) {}
    chrome.kill();
    await sleep(400);
    try { fs.rmSync(prof, { recursive: true, force: true }); } catch (e) {}
  }
}
main().catch((e) => { console.error('СБОЙ', e.message); process.exit(1); });
