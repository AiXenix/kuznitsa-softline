import {add,button,link,rows} from './dom.js';

const departments=[
  ['Офисные программы','офисный пакет','▤'],['Антивирусы','антивирус','◇'],
  ['Защита информации','защита информации','◈'],['Операционные системы','операционная система','▦'],
  ['Серверы','сервер','▥'],['Резервное копирование','резервное копирование','▣']
];
const query=q=>'/?'+new URLSearchParams({q});
export function merchandising(main){
  document.body.classList.add('shop');
  const header=document.querySelector('header .top');
  const form=document.querySelector('#search'),basket=document.querySelector('#basket');
  const oldNav=header.querySelector('nav');
  const panel=add(document.body,'aside',null,'judge');panel.id='judge';panel.hidden=true;
  panel.setAttribute('aria-label','Настройки и разбор поиска');
  const bar=add(panel,'div',null,'judgeHead');add(bar,'h2','Настройки поиска');
  const shut=button(bar,'Закрыть',()=>show(false));
  panel.append(form.querySelector('.settings'),document.querySelector('#profileInfo'));
  const understanding=add(panel,'div');
  panel.append(document.querySelector('.tools'),document.querySelector('#specForm'),document.querySelector('#comparison'),document.querySelector('.trace'),oldNav);
  link(oldNav,'Схемы','/flows');link(oldNav,'Образцы интерфейса','/styleguide');link(oldNav,'Режим показа','/?show=1');
  header.replaceChildren();
  const top=add(header,'div',null,'shopTop'),brand=link(top,'','/'),logo=add(brand,'img');
  logo.src='/web/assets/softline-logo.svg';logo.alt='Софтлайн Решения';
  add(top,'span','Интернет-магазин','storeName');
  const gear=button(top,'⚙',()=>show(panel.hidden),'gear');
  gear.title='Настройки и разбор поиска';gear.setAttribute('aria-label',gear.title);gear.setAttribute('aria-controls',panel.id);
  function show(open,focus=true){
    panel.hidden=!open;gear.setAttribute('aria-expanded',String(open));document.body.classList.toggle('judgeOpen',open);
    if(focus)(open?shut:gear).focus({preventScroll:true});
  }
  const row=add(header,'div',null,'shopSearch'),catalog=button(row,'☰  Каталог',()=>{menu.hidden=!menu.hidden;catalog.setAttribute('aria-expanded',String(!menu.hidden));},'catalogBtn');
  row.append(form);const actions=add(row,'div',null,'shopActions');
  const drawer=document.querySelector('#drawer'),body=document.querySelector('#cartBody');
  function selection(type){
    document.querySelector('#drawerTitle').textContent=type;body.replaceChildren();
    const saved=readList(type);
    for(const item of saved)link(add(body,'p'),item.title,'/card/'+encodeURIComponent(item.id));
    if(!saved.length)add(body,'p','Добавьте товары кнопкой на карточке.');
    if(type==='Сравнение' && saved.length>1)link(body,'Сравнить товары',query('сравнить '+saved.map(i=>i.title).join(' и ')));
    drawer.showModal();
  }
  button(actions,'Сравнение',()=>selection('Сравнение'));
  button(actions,'Войти',()=>{
    document.querySelector('#drawerTitle').textContent='Профиль покупателя';body.replaceChildren();
    const profile=document.querySelector('#profile'),label=add(body,'label','Организация');
    const select=profile.cloneNode(true);select.removeAttribute('id');label.append(select);select.value=profile.value;
    button(body,'Продолжить',()=>{profile.value=select.value;profile.dispatchEvent(new Event('change'));drawer.close();},'primary');
    drawer.showModal();
  });
  button(actions,'Избранное',()=>selection('Избранное'));actions.append(basket);
  const paths=['M4 19V11m5 8V5m5 14v-9m5 9V3','M8 8a4 4 0 1 0 8 0a4 4 0 1 0 -8 0M4 21c0-8 16-8 16 0','M12 20 3.5 11.5C-1 5 7 1 12 7c5-6 13-2 8.5 4.5Z','M2 4h3l3 12h11l3-9H6M9 20h1m7 0h1'];
  [...actions.children].forEach((b,i)=>actionIcon(b,paths[i]));
  const menu=add(header,'nav',null,'catalogMenu');menu.hidden=true;menu.setAttribute('aria-label','Каталог разделов');
  const nav=add(header,'nav',null,'departments');nav.setAttribute('aria-label','Разделы магазина');
  for(const [title,q] of [['Акции','акции'],['Производители','производители'],...departments])link(nav,title,query(q));
  document.querySelector('.hero').hidden=true;
  document.querySelector('footer span').textContent='Демонстрационный стенд хакатона. Каталог store.softline.ru.';
  document.addEventListener('keydown',e=>{if(e.key==='Escape' && !drawer.open){menu.hidden=true;if(!panel.hidden && !document.querySelector('.traceWide'))show(false);}});
  show(new URLSearchParams(location.search).get('show')==='1',false);
  return {understanding,categories(items){
    menu.replaceChildren();
    for(const c of rows(items))link(menu,c.title,'/?'+new URLSearchParams({q:c.title,category:c.id}));
  },open:()=>show(true)};
}
function actionIcon(button,path){
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),shape=document.createElementNS(ns,'path');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
  shape.setAttribute('d',path);svg.append(shape);button.prepend(svg);
}
function readList(key){
  try{return JSON.parse(sessionStorage.getItem('shop:'+key)) || [];}catch{return [];}
}
export function saveButtons(parent,c){
  if(!c.card_id)return;
  const box=add(parent,'div',null,'saveProduct');
  for(const [title,icon] of [['Избранное','♡'],['Сравнение','⇄']]){
    const b=button(box,icon,()=>{
      const list=readList(title),has=list.some(i=>i.id===c.card_id);
      sessionStorage.setItem('shop:'+title,JSON.stringify(has?list.filter(i=>i.id!==c.card_id):[...list,{id:c.card_id,title:c.title}]));
      b.setAttribute('aria-pressed',String(!has));
    });b.title=title;b.setAttribute('aria-label',title);b.setAttribute('aria-pressed',String(readList(title).some(i=>i.id===c.card_id)));
  }
}
export function shopHome(results){
  results.replaceChildren();const banners=add(results,'div',null,'shopBanners');
  for(const [cls,title,q] of [['workspaceAd','VK WorkSpace · выбрать тариф','VK WorkSpace'],['cloudAd','Виртуальное рабочее место · выбрать тариф','виртуальное рабочее место']]){
    const a=link(banners,'',query(q));a.className=cls;a.setAttribute('aria-label',title);
  }
  add(results,'h1','Каталог решений');const tiles=add(results,'div',null,'departmentTiles exampleGrid');
  for(const [title,q,icon] of departments){const a=link(tiles,'',query(q));add(a,'span',icon).setAttribute('aria-hidden','true');add(a,'b',title);add(a,'small','Перейти в раздел →');}
}
