import {caption,readable} from './labels.js';
import {add,line,button,details,rows,label,num,money} from './dom.js';

const factors={rel:'Релевантность',pop:'Популярность',margin:'Маржа',pers:'Персонализация'};
const names={renewal:'Продление',new:'Новая',addon:'Докупка',upgrade:'Обновление',crossgrade:'Переход',business:'Организация',gov:'Госучреждение',edu:'Образование',home:'Дом',esd:'Электронная',box:'Коробка',perpetual:'Бессрочно'};
const columns=[
  ['Действие',o=>names[o.action] || o.action],
  ['Количество',o=>o.pack ? 'Пакет '+o.pack : [o.qty_min,o.qty_max].filter(v=>v!=null).join('–')],
  ['Срок',o=>o.term_months ? o.term_months+' мес.' : names[o.model]],
  ['Для кого',o=>names[o.audience] || o.audience],['Поставка',o=>names[o.delivery] || o.delivery],
  ['Артикул',o=>o.sku],['Цена',o=>o.price_on_request?'По запросу':money(o.price)]
];
function table(p,c,others) {
  p.replaceChildren();
  const offers=[c.offer,...rows(others).filter(o=>!c.offer || o.offer_id!==c.offer.offer_id)].filter(Boolean);
  const cols=columns.filter(([,value])=>offers.some(o=>value(o)));
  const t=add(p,'table'), header=add(add(t,'thead'),'tr');
  cols.forEach(([title])=>add(header,'th',title));
  for(const o of offers){
    const tr=add(t,'tr',null,o===c.offer?'selected':'');
    cols.forEach(([,value])=>add(tr,'td',value(o)));
  }
}
function price(c) {
  if(c.offer?.price_on_request)return 'Цена по запросу';
  if(c.calc?.text)return c.calc.text.replace(/(\d)[ \u202f](?=\d{3}(?:\D|$))/g,'$1 ').replace(/\s+₽/g,' ₽');
  const {qty,unit_price,total}=c.calc || {};
  if(qty!=null && unit_price!=null && total!=null)return num(qty)+' × '+money(unit_price)+' = '+money(total);
  if(total!=null)return money(total);
  const from=c.price_from ?? unit_price;
  return from==null?money(c.offer?.price):'от '+money(from);
}
function conditions(o={}){
  if(!o)return [];
  const quantity=o.qty_min!=null && o.qty_max==null?'от '+o.qty_min:o.qty_min==null && o.qty_max!=null?'до '+o.qty_max:[...new Set([o.qty_min,o.qty_max].filter(n=>n!=null))].join('–');
  const units={device:'устройств',user:'пользователей',server:'серверов',node:'узлов'};
  return [names[o.action],o.term_months?o.term_months+' мес.':names[o.model],
    o.pack?'Пакет · '+o.pack:quantity && (quantity+' '+(units[o.metric] || 'мест')),
    o.delivery==='esd'?'Электронная поставка':names[o.delivery]].filter(Boolean);
}
function priceLine(p,c,cls){
  const value=price(c);if(!value)return;
  const node=add(p,'p',null,cls);node.title=value;
  const parts=value.split(/\s+=\s+/);
  for(const [i,part] of parts.entries()){
    if(i)node.append(document.createTextNode(' '));
    add(node,'span',(i?'= ':'')+part,'pricePart');
  }
}
export function mini(p,c) {
  const a=add(p,'article',null,'mini');
  line(a,c.position,'rank','span');const text=add(a,'div');
  const name=line(text,c.title,null,'strong');if(name)name.title=c.title;
  const lic=line(text,conditions(c.offer).join(' · ') || c.offer?.name,'license');if(lic)lic.title=c.offer.name;
  const full=price(c);
  if(full)line(text,!c.offer?.price_on_request && c.calc?.total!=null?money(c.calc.total):full,'miniPrice').title=full;
  return a;
}
export function card(p,c,ctx) {
  if(!c)return;
  const a=add(p,'article',null,'product catalogCard');
  const identity=add(a,'div',null,'identity');
  line(identity,c.position,'rank','span');
  const vendor=caption('vendor',c.vendor?.id || label(c.vendor),label(c.vendor));
  if(vendor){
    const words=vendor.split(/\s+/);
    const mark=add(identity,'b',(words.length>1 ? words[0].slice(0,1)+words[1].slice(0,1) : vendor.slice(0,2)).toUpperCase(),'monogram');
    let hue=0;for(const char of vendor)hue=(hue*31+char.codePointAt(0))%360;
    mark.style.backgroundColor='hsl('+hue+' 35% 86%)';
  }
  const head=add(a,'div',null,'cardHead');
  const body=add(a,'div',null,'description');
  line(body,[vendor,caption('category',c.category?.id || label(c.category),label(c.category))].filter(Boolean).join(' / '),'eyebrow');
  const h=add(head,'h3'), buy=add(a,'div',null,'purchase');
  const disclosures=add(a,'div',null,'disclosures');
  const info=details(disclosures,'Лицензия и варианты');
  info.hidden=!c.offer && !rows(c.variants).length;
  let viaTitle=false;
  if(info.hidden)line(h,c.title,null,'span');
  else button(h,c.title,()=>{viaTitle=true;ctx.click?.(c,'card');info.open=!info.open;},'productTitle');
  if(ctx.click)info.ontoggle=()=>{if(info.open && !viaTitle)ctx.click(c,'variants');viaTitle=false;};
  h.title=c.title || '';
  line(h,c.score?.tier_label || (c.score?.tier!=null?caption('tier',c.score.tier,'Уровень '+c.score.tier):''),'badge','span');
  const whyFirst=line(head,readable(label(rows(c.score?.why)[0])),'whyFirst');if(whyFirst)whyFirst.title=whyFirst.textContent;
  const tags=add(body,'div',null,'conditions');
  for(const term of conditions(c.offer))add(tags,'span',term);
  if(tags.childElementCount)tags.title=c.offer?.name || '';
  const desc=line(body,c.summary,'muted');if(desc)desc.title=c.summary;
  const badges=add(body,'div',null,'chips');
  for(const b of rows(c.badges))line(badges,label(b),/left|restrict|limit|exceed/.test(b.kind)||/ограничен|ушёл|предел/i.test(label(b))?'badge warn':'badge','span');
  const unavailable=!c.offer?.offer_id || c.offer.available===false;
  const quote=unavailable || c.offer.price_on_request;
  if(unavailable)line(buy,'Нет в продаже','badge warn','span');
  priceLine(buy,c,quote?'price quote':'price');
  if(ctx.act)button(buy,c.action?.type==='repeat_order'?(c.action.label || 'Повторить'):quote?'Запросить счёт':'В корзину',e=>ctx.act(quote?'lead':'cart',c,e.currentTarget),quote?'request':'buy');
  if(rows(c.calc?.items).length){
    line(info,'Пакеты в расчёте',null,'strong');
    for(const item of c.calc.items)line(info,[item.count==null?'':item.count+' шт.',item.pack==null?'':'по '+item.pack+' мест',money(item.price)].filter(Boolean).join(' · '));
  }
  const variants=add(info,'div',null,'variantList');table(variants,c,c.variants);
  if(ctx.variants && c.variants_count>rows(c.variants).length+1){
    const more=button(info,'Все варианты · '+c.variants_count,async()=>{
      more.disabled=true;
      try{table(variants,c,(await ctx.variants(c)).variants);more.remove();}
      catch(err){more.textContent=err.message+' Повторить';more.disabled=false;}
    });
  }
  if(!c.score)return;
  const why=details(disclosures,'Почему здесь');
  if(ctx.click)why.ontoggle=()=>{if(why.open)ctx.click(c,'why');};
  line(why,c.score.tier_label || (c.score.tier==null?'':'Уровень '+c.score.tier));
  for(const [key,title] of Object.entries(factors)){
    const n=c.score.parts?.[key];if(n==null)continue;
    const row=add(why,'div',null,'factor');row.title=String(n);
    add(row,'span',title);const bar=add(row,'progress');bar.max=1;bar.value=n;
    const weight=ctx.weights?.[key];
    add(row,'small',num(Math.round(100*n))+'%'+(weight==null?'':' · вес '+num(weight)));
  }
  const list=add(why,'ul');rows(c.score.why).slice(1).forEach(w=>add(list,'li',readable(label(w))));
}
