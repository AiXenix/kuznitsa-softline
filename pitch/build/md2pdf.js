// Markdown → HTML в стиле презентации → PDF через локальный Chrome: node md2pdf.js <файл.md> <файл.pdf>
// Понимает то, что есть в SPEECH.md: заголовки, абзацы, списки, таблицы, **жирный**, *курсив*, `код`, ссылки
const fs = require('fs');
const path = require('path');
const os = require('os');
const { execFileSync } = require('child_process');

const [src, out] = process.argv.slice(2);
const root = path.resolve(__dirname, '..');
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const inline = (s) => esc(s)
  .replace(/`([^`]+)`/g, '<code>$1</code>')
  .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
  .replace(/\*([^*]+)\*/g, '<i>$1</i>')
  .replace(/https?:\/\/[^\s<)]+/g, (u) => '<a href="' + u + '">' + u + '</a>')
  .replace(/▶ КЛИК/g, '<span class="click">▶ КЛИК</span>');

const lines = fs.readFileSync(src, 'utf8').replace(/\r/g, '').split('\n');
let html = '', list = null, table = null, para = [], pre = null;
const flush = () => {
  if (para.length) { html += '<p>' + inline(para.join(' ')) + '</p>\n'; para = []; }
  if (list) { html += '<' + list.t + '>' + list.items.map((x) => '<li>' + inline(x) + '</li>').join('') + '</' + list.t + '>\n'; list = null; }
  if (table) {
    const row = (r, tag) => '<tr>' + r.map((c) => '<' + tag + '>' + inline(c) + '</' + tag + '>').join('') + '</tr>';
    html += '<table>' + row(table[0], 'th') + table.slice(2).map((r) => row(r, 'td')).join('') + '</table>\n'; table = null;
  }
};
for (const l of lines) {
  let m;
  if (/^```/.test(l)) { // блок кода — схема как есть
    if (pre) { html += '<pre>' + esc(pre.join('\n')) + '</pre>\n'; pre = null; } else { flush(); pre = []; }
    continue;
  }
  if (pre) { pre.push(l); continue; }
  if (!l.trim()) { flush(); continue; }
  if ((m = l.match(/^(#{1,3}) (.*)$/))) { flush(); const n = m[1].length; html += '<h' + n + '>' + inline(m[2]) + '</h' + n + '>\n'; continue; }
  if (/^\|/.test(l)) { if (!table) { flush(); table = []; } table.push(l.replace(/^\||\|$/g, '').split('|').map((c) => c.trim())); continue; }
  if ((m = l.match(/^(\d+)\. (.*)$/)) || (m = l.match(/^(-) (.*)$/))) {
    const t = m[1] === '-' ? 'ul' : 'ol';
    if (!list || list.t !== t) { flush(); list = { t, items: [] }; }
    list.items.push(m[2]); continue;
  }
  if (list && /^\s+\S/.test(l)) { list.items[list.items.length - 1] += ' ' + l.trim(); continue; }
  para.push(l.trim());
}
flush();

const b64 = (p) => fs.readFileSync(p).toString('base64');
const css = `@font-face{font-family:Inter;font-weight:100 900;src:url(data:font/woff2;base64,${b64(path.join(root, 'src', 'inter-cyrillic.woff2'))}) format("woff2");unicode-range:U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}
@font-face{font-family:Inter;font-weight:100 900;src:url(data:font/woff2;base64,${b64(path.join(root, 'src', 'inter-latin.woff2'))}) format("woff2")}
@page{size:A4;margin:16mm 16mm 18mm}
body{font:400 10.5pt/1.5 Inter,Arial,sans-serif;color:#1d1f23;margin:0}
h1{font-size:22pt;line-height:1.15;margin:0 0 4mm;color:#1d1f23;border-bottom:3px solid #a50f2d;padding-bottom:3mm}
h2{font-size:14pt;color:#a50f2d;margin:7mm 0 2.5mm;break-after:avoid}
h3{font-size:12pt;margin:6mm 0 1.5mm;break-after:avoid;border-left:4px solid #a50f2d;padding-left:3mm}
p{margin:0 0 2.2mm}ul,ol{margin:0 0 3mm;padding-left:6mm}li{margin:0 0 1.2mm}
i{color:#5b6070}b{font-weight:700}
a{color:#a50f2d;text-decoration:none;word-break:break-all}
code{font:9.5pt Consolas,monospace;background:#f3f4f6;border-radius:3px;padding:0 1.2mm}
pre{font:8.6pt/1.4 Consolas,monospace;background:#f6f6f7;border-left:3px solid #a50f2d;border-radius:4px;padding:3mm 4mm;margin:2mm 0 4mm;white-space:pre;break-inside:avoid}
table{border-collapse:collapse;width:100%;margin:1mm 0 4mm;font-size:9.5pt;break-inside:auto}
th{background:#a50f2d;color:#fff;text-align:left;font-weight:600;padding:1.6mm 2.2mm}
td{border-bottom:1px solid #e3e5e9;padding:1.4mm 2.2mm;vertical-align:top}tr{break-inside:avoid}
.click{display:inline-block;background:#a50f2d;color:#fff;font-weight:700;font-size:8.5pt;letter-spacing:.04em;border-radius:3px;padding:.2mm 1.6mm;margin-right:1mm}`;
const doc = '<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Кузница Softline — выступление</title><style>' + css + '</style></head><body>' + html + '</body></html>';
const tmp = path.join(os.tmpdir(), 'kz-md2pdf-' + process.pid + '.html');
fs.writeFileSync(tmp, doc);
const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'kz-md2pdf-prof-'));
execFileSync('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', ['--headless=new', '--disable-gpu', '--no-first-run', '--user-data-dir=' + prof,
  '--no-pdf-header-footer', '--print-to-pdf=' + path.resolve(out), 'file:///' + tmp.replace(/\\/g, '/')], { stdio: 'ignore', timeout: 90000 });
fs.copyFileSync(tmp, out.replace(/\.pdf$/i, '.html'));
fs.rmSync(tmp); try { fs.rmSync(prof, { recursive: true, force: true }); } catch (e) {}
console.log('pdf', out, (fs.statSync(out).size / 1024).toFixed(0) + ' КБ');
