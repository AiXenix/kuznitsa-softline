// Сборка презентации в один самодостаточный файл dist/index.html
const fs = require('fs');
const path = require('path');
const here = __dirname;
const root = path.resolve(here, '..');
const rd = (p) => fs.readFileSync(p, 'utf8');
const b64 = (p) => fs.readFileSync(p).toString('base64');

let css = rd(path.join(here, 'deck.css'))
  .replace('__INTER_CYR__', b64(path.join(root, 'src', 'inter-cyrillic.woff2')))
  .replace('__INTER_LAT__', b64(path.join(root, 'src', 'inter-latin.woff2')));

const logo = rd(path.join(root, 'src', 'softline-logo.svg'));
const logoInner = logo.replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '').replace(/<defs>[\s\S]*?<\/defs>/, '');
const symbol = '<symbol id="i-logo" viewBox="0 0 793.7 114.2">' + logoInner + '</symbol>';

let qr = rd(path.join(root, 'data', 'pitch-qr.svg')).replace(/^[\s\S]*?(<svg)/, '$1');
qr = qr.replace(/<svg([^>]*)>/, (m, a) => '<svg' + a.replace(/\s(width|height)="[^"]*"/g, '') + '>');

let slides = rd(path.join(here, 'slides.html'))
  .replace('</svg>', symbol + '</svg>')
  .replace('__ADM__', 'data:image/jpeg;base64,' + b64(path.join(root, 'data', 'pitch-adm.jpg')))
  .replace('__QR__', qr);

const D = JSON.parse(rd(path.join(root, 'data', 'pitch-data.json')));
// запросы, которых нет на слайдах, в презентацию не берём
const DROP = ['чтобы данные не утекли с флешками', 'что от вирусов'];
for (const k of Object.keys(D.search)) if (DROP.includes(k.split('|')[0])) delete D.search[k];
const data = JSON.stringify(D).replace(/</g, '\\u003c');
const jsDir = path.join(here, 'js');
const js = fs.readdirSync(jsDir).filter((f) => f.endsWith('.js')).sort().map((f) => rd(path.join(jsDir, f))).join('\n');

const html = '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n' +
  '<meta name="viewport" content="width=device-width,initial-scale=1">\n<meta name="robots" content="noindex">\n' +
  '<title>Кузница Softline — умный поиск. Презентация</title>\n' +
  '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 16 16%27%3E%3Crect width=%2716%27 height=%2716%27 rx=%273%27 fill=%27%23a50f2d%27/%3E%3C/svg%3E">\n<style>\n' + css + '\n</style>\n</head>\n<body>\n' +
  slides + '\n<script type="application/json" id="deck-data">' + data + '</script>\n<script>\n(function () {\n' + js +
  '\n})();\n</script>\n</body>\n</html>\n';

for (const m of ['__INTER_CYR__', '__INTER_LAT__', '__ADM__', '__QR__']) {
  if (html.includes(m)) throw new Error('не подставлено: ' + m);
}
const out = path.join(here, 'dist');
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(out, 'index.html'), html);
console.log('index.html', (html.length / 1024).toFixed(0) + ' КБ', 'слайдов', (slides.match(/<section class="slide/g) || []).length);
