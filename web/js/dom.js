export const $ = id => document.getElementById(id);
export const rows = value => Array.isArray(value) ? value.filter(v => v != null) : [];
export const label = v => typeof v === 'object' && v !== null ? v.title ?? v.label ?? v.name ?? v.text ?? '' : v;
export function add(parent, tag, text, cls) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
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
export const money = n => n == null ? '' : num(n) + ' ₽';
export const counted = (title, count) => [title, count == null ? '' : num(count)].filter(Boolean).join(' · ');
export function stateBox(parent, text, kind='empty') {
  return add(parent, 'p', text, 'state ' + kind);
}
