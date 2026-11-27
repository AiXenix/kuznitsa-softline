// Хватает ли времени на текст: слова в заметках слайда против плана (темп 130 слов в минуту)
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname, 'slides.html'), 'utf8');
const WPM = +process.argv[2] || 130;
let total = 0, plan = 0;
for (const m of html.matchAll(/<section class="slide[^>]*data-title="([^"]+)" data-time="(\d+)"[\s\S]*?<aside class="notes">([\s\S]*?)<\/aside>/g)) {
  const words = m[3].replace(/<[^>]+>/g, ' ').split(/\s+/).filter((w) => /[A-Za-zА-Яа-яЁё0-9]/.test(w)).length;
  const need = words / WPM * 60;
  total += words; plan += +m[2];
  console.log(m[1].padEnd(22), 'план', String(m[2]).padStart(3) + ' с', '· слов', String(words).padStart(3), '· нужно', need.toFixed(0).padStart(3) + ' с', need > +m[2] + 3 ? '  ← не помещается' : '');
}
console.log('ИТОГО слов', total, '· план', plan, 'с · нужно', (total / WPM * 60).toFixed(0), 'с при', WPM, 'слов/мин');
