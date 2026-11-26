export const $ = id => document.getElementById(id);
export const rows = value => Array.isArray(value) ? value.filter(v => v != null) : [];
export const label = v => typeof v === 'object' && v !== null ? v.title ?? v.label ?? v.name ?? v.text ?? '' : v;
export function putText(node,value){
  if(typeof value!=='string' || !value.includes('₽') || ['PRE','CODE'].includes(node.tagName)){node.textContent=value;return;}
  let start=0;
  for(const match of value.matchAll(/(?:≈\s*)?[−+-]?\d+(?:[ \u00a0\u202f]\d{3})*(?:[,.]\d+)?(?:\s*(?:тыс\.|млн|млрд))?\s*₽/g)){
    node.append(value.slice(start,match.index));
    const amount=document.createElement('span');amount.className='amount';amount.textContent=match[0].replace(/\s/g,' ');
    node.append(amount);start=match.index+match[0].length;
  }
  node.append(value.slice(start));
}
export function add(parent, tag, text, cls) {
  const node = document.createElement(tag);
  if (text != null) putText(node,text);
  if (cls) node.className = cls;
  parent.append(node);
  return node;
}
export function line(parent, text, cls, tag = 'p') {
  if (text != null && text !== '') return add(parent, tag, text, cls);
}
export function button(parent, text, fn, cls) {
  const b = add(parent, 'button', text, cls);
  b.type = 'button';
  b.onclick = fn;
  return b;
}
export function details(parent, title) {
  const d = add(parent, 'details');
  add(d, 'summary', title);
  return d;
}
export function link(parent, title, href) {
  const a = add(parent, 'a', title);
  a.href = href;
  return a;
}
export const num = n => Number(n).toLocaleString('ru-RU', {maximumFractionDigits: 10});
export function money(n){
  if(n==null || !Number.isFinite(n))return '';
  const small=n!==0 && Math.abs(n)<1;
  const digits=small?{maximumSignificantDigits:2}:{maximumFractionDigits:2};
  return (small?'≈ ':'')+n.toLocaleString('ru-RU',digits)+' ₽';
}
export function moneyRate(n,perThousand){
  return money(n)+(n>0 && n<1?' · '+money(Number((perThousand ?? n*1000).toPrecision(2)))+' за 1 000 запросов':'');
}
export const counted = (title, count) => [title, count == null ? '' : num(count)].filter(Boolean).join(' · ');
export function stateBox(parent, text, kind='empty') {
  return add(parent, 'p', text, 'state ' + kind);
}

export function actionIcon(button,path){
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),shape=document.createElementNS(ns,'path');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
  shape.setAttribute('d',path);svg.append(shape);button.prepend(svg);
}
