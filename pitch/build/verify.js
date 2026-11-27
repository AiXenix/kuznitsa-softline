// Сверка утверждений на слайдах со снимком ответов стенда
const fs = require('fs');
const path = require('path');
const D = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'data', 'pitch-data.json'), 'utf8'));
const claims = [
  ['сервер', ['Rack-сервер']], ['по для сервера', ['Альт Сервер']], ['винда хоум', ['Windows 11 Home']], ['антивирь', []],
  ['астра линкус', ['Astra Linux Special Edition']], ['мдаемон', ['MDaemon']], ['rfcgthcrbq', ['Kaspersky']], ['3д макс', ['3ds Max']],
  ['kw9-00664', ['Windows 11 Home']], ['антивирус на 20 компьютеров', []], ['продление криптопро', ['КриптоПро']],
  ['аналог автокад', ['nanoCAD', 'КОМПАС']], ['чем открыть pdf', ['Acrobat', 'Master PDF']], ['чем заменить фотошоп', ['AliveColors', 'ФотоМАСТЕР']],
  ['как учить сотрудников удалённо', ['Unicraft', 'IT-курсы']], ['luminar', ['Lightroom']], ['astra linux', ['Astra Linux Special Edition']], ['офис', ['Office']]
];
const flat = (o) => (o.blocks || o.b || []).map((b) => '[' + (b.type || b.y) + ' «' + (b.title || b.h || '') + '» ' + (b.total || b.n || '') + '] ' +
  (b.items || b.i || []).slice(0, 5).map((x) => x.t + (x.p ? ' {' + x.p + '}' : '')).join(' | ')).join('\n      ');
let bad = 0;
for (const [q, need] of claims) {
  const d = D.search[q + '|smart'];
  if (!d) { console.log('НЕТ В СНИМКЕ:', q); bad++; continue; }
  const text = flat(d), miss = need.filter((s) => !text.toLowerCase().includes(s.toLowerCase()));
  if (miss.length) bad++;
  console.log((miss.length ? 'РАСХОЖДЕНИЕ ' + JSON.stringify(miss) : 'ок') + ' · ' + q + ' → corr=' + (d.corr || '') + ' intent=' + d.intent + ' src=' + d.src +
    ' chips=' + JSON.stringify(d.chips || []) + (d.note ? ' note=' + d.note.slice(0, 90) : '') + '\n      ' + text);
}
console.log(bad ? 'РАСХОЖДЕНИЙ: ' + bad : 'все утверждения сходятся со снимком');
console.log('ключи одного ответа:', Object.keys(D.search['сервер|smart']).join(','));
