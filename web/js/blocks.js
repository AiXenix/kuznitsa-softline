import {add, line, button, details, rows, label, money, num, counted, stateBox} from './dom.js';

const titles = {products:'Подходящие лицензии',kit:'Комплект',analogs:'Варианты замены',answer:'Ответ на вопрос',
  spec:'Разбор спецификации',compare:'Сравнение программ',not_in_catalog:'Нет в каталоге',categories:'Категории',
  vendors:'Производители',my_licenses:'Ваши лицензии',clarify:'Уточните запрос',services:'Услуги',promo:'Предложения',
  lead:'Запрос поставки',crosssell:'С этим обычно берут'};
const factors = {rel:'Релевантность',pop:'Популярность',margin:'Маржа',pers:'Персонализация'};

function offerRow(parent, o) {
  line(parent, [label(o), o?.sku, o?.price_on_request ? 'Цена по запросу' : money(o?.price)].filter(Boolean).join(' · '));
}
function price(c) {
  if (c.offer?.price_on_request) return 'Цена по запросу';
  if (c.calc?.text) return c.calc.text;
  const calc = c.calc || {};
  if ([calc.qty,calc.unit_price,calc.total].every(n => n != null)) {
    return num(calc.qty) + ' × ' + money(calc.unit_price) + ' = ' + money(calc.total);
  }
  const from = c.price_from ?? calc.unit_price;
  return from != null ? 'от ' + money(from) : money(c.offer?.price);
}
function card(parent, c, ctx) {
  if (!c) return;
  const a = add(parent,'article',null,'product');
  if (c.card_id) a.dataset.card = c.card_id;
  if (c.offer?.offer_id) a.dataset.offer = c.offer.offer_id;
  line(a,[label(c.vendor),label(c.category)].filter(Boolean).join(' / '),'eyebrow');
  const h = add(a,'h3');
  if (ctx.click && c.title && (c.offer || rows(c.variants).length)) {
    button(h,c.title,() => {info.open = !info.open;},'productTitle');
  } else line(h,c.title,null,'span');
  line(a,c.summary,'muted');
  const badges = add(a,'div',null,'chips');
  rows(c.badges).forEach(b => line(badges,label(b),'badge','span'));
  line(a,c.offer?.name,'license');
  line(a,price(c),'price');
  const info = details(a,'Лицензия и варианты' + (c.variants_count == null ? '' : ' · ' + num(c.variants_count)));
  info.hidden = !c.offer && !rows(c.variants).length;
  if (ctx.click) info.ontoggle = () => {if (info.open) ctx.click(c);};
  if (c.offer) offerRow(info,c.offer);
  const variants = add(info,'div',null,'variantList');
  rows(c.variants).forEach(o => offerRow(variants,o));
  if (ctx.variants && c.card_id && c.variants_count > variants.childElementCount + (c.offer ? 1 : 0)) {
    const load = button(info,'Все варианты лицензии',async () => {
      load.disabled=true;
      try {
        const full=await ctx.variants(c);
        variants.replaceChildren();
        for(const o of rows(full.variants)) if(!c.offer || o.offer_id!==c.offer.offer_id) offerRow(variants,o);
        load.remove();
      } catch(err) {load.disabled=false;load.textContent=err.message+' Повторить';}
    });
  }
  if (c.score) {
    const why = details(a,'Почему здесь');
    if (ctx.click) why.ontoggle = () => {if (why.open) ctx.click(c);};
    if (c.score.tier != null) line(why,'Уровень релевантности · ' + c.score.tier);
    rows(c.score.why).forEach(w => line(why,label(w)));
    const dl = add(why,'dl',null,'metrics');
    for (const [k,title] of Object.entries(factors)) {
      const n = c.score.parts?.[k];
      if (n != null) {add(dl,'dt',title); add(dl,'dd',num(n));}
    }
  }
  if (ctx.act && c.offer?.offer_id && c.offer.available !== false) {
    const quote = c.offer.price_on_request;
    button(a,quote ? 'Запросить цену' : 'В корзину',e => ctx.act(quote ? 'lead' : 'cart',c,e.currentTarget),'buy');
  }
}
function alternatives(parent, options, ctx) {
  if (!rows(options).length) return;
  const d = details(parent,'Другие варианты');
  for (const o of options) card(d,o.card || o,ctx);
}
function collection(parent,b,ctx) {
  if (b.source?.title) line(parent,[b.source.title,b.source.note].filter(Boolean).join(' · '));
  if (!rows(b.items).length && b.type === 'products') stateBox(parent,'По этим условиям товаров нет.');
  for (const item of rows(b.items)) {
    line(parent,item.reason || item.note,'hint');
    card(parent,item.card || item,ctx);
    line(parent,item.text);
  }
}
function kit(p,b,ctx) {
  line(p,[label(b.role), b.seats == null ? '' : num(b.seats)+' мест'].filter(Boolean).join(' · '));
  for (const s of rows(b.slots)) {
    line(p,s.title,null,'h3');
    if (typeof s.must === 'boolean') line(p,s.must ? 'Обязательная позиция' : 'По выбору','badge','span');
    line(p,s.note); card(p,s.card,ctx); alternatives(p,s.alternatives,ctx);
  }
  if (b.total != null) line(p,'Стоимость комплекта · '+money(b.total),'price');
}
const statuses = {matched:'Подобрано',ambiguous:'Нужно уточнить',not_found:'Не найдено'};
function spec(p,b,ctx) {
  for (const l of rows(b.lines)) {
    const box = add(p,'section',null,'specLine');
    line(box,[l.n,l.raw].filter(v => v != null).join('. '),null,'h3');
    line(box,statuses[l.status] || l.status,'badge','span');
    line(box,label(l.understood)); card(box,l.card,ctx); alternatives(box,l.alternatives,ctx);
    if (l.qty != null && l.unit_price != null) line(box,num(l.qty)+' × '+money(l.unit_price));
    line(box,money(l.total),'price');
  }
  if (b.total != null) line(p,'Итого по подобранным позициям · '+money(b.total),'price');
  if (typeof b.unresolved === 'number') line(p,'Требуют уточнения · '+num(b.unresolved));
  rows(b.unresolved).forEach(l => line(p,l.raw || label(l)));
}
function compare(p,b) {
  const wrap = add(p,'div',null,'scroll');
  const t = add(wrap,'table'), h = add(add(t,'thead'),'tr');
  add(h,'th','Характеристика');
  for (const c of rows(b.columns)) add(h,'th',label(c));
  const body = add(t,'tbody');
  for (const row of rows(b.rows)) {
    const tr = add(body,'tr'); add(tr,'th',row.title);
    for (const v of row.values || []) add(tr,'td',typeof v === 'boolean' ? (v ? 'Да' : 'Нет') : label(v));
  }
}
function choice(p,title,apply,ctx) {
  if (!title) return;
  if (ctx.apply && apply && typeof apply==='object') button(p,title,()=>ctx.apply(apply),'chip'); else line(p,title,'chip','span');
}
function licenses(p,b,ctx) {
  for (const item of rows(b.items)) {
    line(p,item.title,null,'h3');
    if (item.qty != null) line(p,'Количество · '+num(item.qty));
    if (item.expires_in_days != null) line(p,'До окончания · '+num(item.expires_in_days)+' дн.');
    if (item.renew_offer) {
      offerRow(p,item.renew_offer);
      if (item.title) choice(p,'Подобрать продление',{q:'продление '+item.title},ctx);
    }
  }
}
export function block(parent,b,actions={}) {
  if (!b) return;
  const ctx = {...actions};
  const p = add(parent,'section',null,'block');
  add(p,'h2',counted(b.title || titles[b.type] || 'Блок не поддержан',b.type==='products' ? b.total : null));
  if (!(Object.hasOwn(titles,b.type))) {if (b.title) line(p,'Блок не поддержан'); return;}
  line(p,b.text);
  switch (b.type) {
    case 'kit': return kit(p,b,ctx);
    case 'spec': return spec(p,b,ctx);
    case 'compare': return compare(p,b);
    case 'my_licenses': return licenses(p,b,ctx);
    case 'categories': case 'vendors':
      for (const i of rows(b.items)) choice(p,counted(i.title,i.count),{q:i.title},ctx);
      break;
    case 'answer':
      line(p,b.source,'muted');
      for (const l of rows(b.links)) choice(p,label(l),{q:l.q || label(l)},ctx);
      break;
    case 'not_in_catalog': if (!b.text) line(p,b.reason); break;
    case 'clarify':
      line(p,b.question);
      for (const o of rows(b.options)) choice(p,o.label,o.apply,ctx);
      break;
    case 'lead':
      if (ctx.act && b.action==='request_quote') button(p,'Оставить запрос',e=>ctx.act('lead',{},e.currentTarget));
      break;
    default: collection(p,b,ctx);
  }
}
