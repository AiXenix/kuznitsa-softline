import {address,readAddress} from './store/address.js';
import {result} from './store/result.js';

const main=document.querySelector('main'),out=document.querySelector('output');
const fixture=JSON.parse(document.querySelector('#fixtures').textContent);
function check(ok,msg){if(!ok)throw Error(msg);}

try{
  // 1. Address round-trip with sort=, filters, exclude, ignore.
  const req={q:'ноутбук',profile_id:'guest',mode:'fast',category:'70824',sort:'price_asc',filters:{vendor:['lenovo'],price_max:120000},exclude:{vendor:['hp']},ignore:['audience']};
  const path=address(req,'','https://demo.invalid/');
  const u=new URL(path,'https://demo.invalid');
  check(u.searchParams.get('sort')==='price_asc','sort= в адресе');
  const saved=readAddress(u.search);
  check(saved.sort==='price_asc' && saved.criteria.sort==='price_asc','восстановление sort');
  check(saved.criteria.filters.vendor?.[0]==='lenovo' && saved.criteria.filters.price_max===120000,'восстановление filters');
  check(saved.criteria.exclude.vendor?.[0]==='hp','восстановление exclude');
  check(saved.criteria.ignore[0]==='audience','восстановление ignore');
  const cleared=new URL(address({q:'ноутбук',profile_id:'guest',mode:'fast',sort:'',filters:{},exclude:{},ignore:[],page:1},'','https://demo.invalid/'),'https://demo.invalid');
  check(!cleared.searchParams.has('sort') && !cleared.searchParams.has('criteria'),'очистка пустых sort и criteria');

  // 2. Facets, sort, page-level understood bar vs drawer panel (no duplication).
  const drawer=document.createElement('aside');
  let applied=null;
  main.replaceChildren();
  result(main,fixture,{retail:true,understanding:drawer,sort:'price_asc',filters:{vendor:['lenovo']},apply:p=>{applied=p;}});

  // Sort select next to heading.
  const sortSel=main.querySelector('.blockHead select.sortSelect');
  check(sortSel && [...sortSel.options].map(o=>o.textContent).join('|')==='Сначала подходящие|Сначала дешевле|Сначала дороже','варианты сортировки');
  check(sortSel.value==='price_asc','текущая сортировка');
  sortSel.value='price_desc';sortSel.dispatchEvent(new Event('change'));
  check(applied?.sort==='price_desc','выбор price_desc');
  sortSel.value='';sortSel.dispatchEvent(new Event('change'));
  check(applied?.sort===null,'сброс сортировки');

  // Facets bar: 8 visible + "ещё 2", N7 contract filters: {vendor:[id]}, {category:[id]}, {price_max:id}, active chip with ×.
  const facetBar=main.querySelector('.facetBar');
  check(facetBar,'панель фильтров видна');
  const vendorGroup=facetBar.querySelector('[data-facet=vendor]');
  const vendorBtns=[...vendorGroup.querySelectorAll('.facetValues button.facetChip')];
  check(vendorBtns.filter(b=>!b.hidden).length===8 && vendorBtns.filter(b=>b.hidden).length===2,'8 значений и скрытый остаток');
  check(vendorBtns[0].classList.contains('active') && vendorBtns[0].getAttribute('aria-pressed')==='true','выбранный производитель подсвечен');
  const moreBtn=vendorGroup.querySelector('button.facetMore');
  check(moreBtn && moreBtn.textContent==='ещё 2','кнопка ещё 2');
  moreBtn.click();
  check(vendorBtns.every(b=>!b.hidden) && moreBtn.textContent==='Свернуть','раскрытие ещё');
  vendorBtns[1].click();
  check(Array.isArray(applied?.filters?.vendor) && applied.filters.vendor[0]==='asus','выбор фильтра производителя массивом');

  const catBtns=[...facetBar.querySelectorAll('[data-facet=category] button.facetChip')];
  catBtns[0].click();
  check(Array.isArray(applied?.filters?.category) && applied.filters.category[0]==='70824','выбор фильтра раздела массивом');

  const priceBtns=[...facetBar.querySelectorAll('[data-facet=price_max] button.facetChip')];
  priceBtns[1].click();
  check(applied?.filters?.price_max===120000,'выбор price_max числом');

  const appliedChip=facetBar.querySelector('.facetApplied button.facetChip.active');
  check(appliedChip && appliedChip.textContent.includes('Lenovo') && appliedChip.textContent.includes('×'),'активный фильтр со снятием');
  appliedChip.click();
  check(applied?.ignore?.[0]==='vendor','снятие фильтра через ignore');

  // Understood bar on page vs service badges in drawer (no duplication).
  const bar=main.querySelector('.understoodBar');
  check(bar && bar.textContent.includes('Показаны результаты по «ноутбук»'),'исправление на странице');
  check(bar.textContent.includes('Искать как было') && bar.textContent.includes('Возможно, вы искали «ноутбуки для бизнеса»'),'кнопки исправления на странице');
  check(bar.textContent.replace(/\u00a0/g,' ').includes('До 120 000 ₽ ×'),'снимаемый чип на странице');
  check(!bar.textContent.includes('Количество · 3'),'несъёмный чип не выведен в строку на странице');
  check(drawer.textContent.includes('Количество · 3'),'несъёмный чип остался в панели');
  check(!drawer.textContent.includes('Показаны результаты по') && !drawer.textContent.includes('Искать как было') && !drawer.textContent.includes('Возможно, вы искали') && !drawer.textContent.replace(/\u00a0/g,' ').includes('До 120 000 ₽'),'нет дублирования между страницей и панелью');
  [...bar.querySelectorAll('button')].find(b=>b.textContent==='Искать как было').click();
  check(applied?.verbatim===true,'кнопка Искать как было');
  [...bar.querySelectorAll('button')].find(b=>b.textContent.replace(/\u00a0/g,' ').includes('До 120 000 ₽')).click();
  check(applied?.ignore?.[0]==='price_max','снятие условия со страницы');

  // 3. Empty facets -> no .facetBar at all; sort hidden for compare, spec, empty.
  main.replaceChildren();drawer.replaceChildren();
  result(main,{...fixture,facets:[]},{retail:true,understanding:drawer,apply:()=>{}});
  check(!main.querySelector('.facetBar'),'пустые facets не рисуют строку фильтров');

  for(const nonSortable of [
    {blocks:[{type:'compare',title:'Сравнение',columns:['A','B'],rows:[{title:'Цена',values:[1,2]}]}]},
    {blocks:[{type:'spec',title:'Спецификация',lines:[{n:1,raw:'ОС',status:'matched'}],total:100,unresolved:0}]},
    {blocks:[]},
    {blocks:[{type:'products',title:'Ноутбуки',total:0,items:[]}]}
  ]){
    main.replaceChildren();
    result(main,nonSortable,{retail:true,apply:()=>{}});
    check(!main.querySelector('.sortSelect'),'сортировка скрыта для '+(nonSortable.blocks[0]?.type || 'empty'));
  }

  // Sort shown for non-empty analogs.
  main.replaceChildren();
  result(main,{blocks:[{type:'analogs',title:'Варианты замены',items:[{title:'Замена 1',offer:{price:1000}}]}]},{retail:true,apply:()=>{}});
  check(main.querySelector('.sortSelect'),'сортировка показана для analogs');

  // 4. Single absence message + analogs first + deduplicated card label.
  main.replaceChildren();drawer.replaceChildren();
  result(main,{
    query:{raw:'dallas lock'},
    understood:{zero_reason:'not_in_catalog',agent_note:'В каталоге нет «dallas lock». Уточните назначение, чтобы подобрать замену.'},
    blocks:[
      {type:'not_in_catalog',title:'Нет в каталоге',text:'В каталоге нет «dallas lock». Уточните назначение, чтобы подобрать замену.',reason:'gap'},
      {type:'clarify',title:'Уточните раздел',question:'Для какой задачи нужна замена?',options:[{label:'СЗИ',apply:{q:'СЗИ'}}]},
      {type:'analogs',title:'Варианты замены',items:[{title:'Secret Net Studio',offer:{price:5000}}]},
      {type:'products',title:'Примеры из предложенных разделов',total:1,items:[{title:'Словарь',label:'Из раздела «Справочники»',reason:'Из раздела «Справочники»',fill:true,offer:{price:500}}]}
    ]
  },{retail:true,understanding:drawer,apply:()=>{},act:()=>{}});
  const h2s=[...main.querySelectorAll('h2')].map(h=>h.textContent);
  check(h2s[0]==='В каталоге нет «dallas lock»','заголовок отсутствия');
  check(!h2s.includes('Нет в каталоге') && !main.textContent.includes('Этого продукта нет в каталоге'),'нет дублей отсутствия');
  check(main.querySelector('.zeroReason p')?.textContent==='Уточните назначение, чтобы подобрать замену.','пояснение без повтора заголовка');
  check((main.textContent.match(/В каталоге нет «dallas lock»/g) || []).length===1,'фраза об отсутствии ровно один раз');
  const blockTypes=[...main.querySelectorAll('section.block')].map(s=>s.dataset.type);
  check(blockTypes[0]==='analogs','analogs идёт первым');
  const prodTile=main.querySelector('[data-type=products] .offerTile');
  const occurrences=(prodTile.textContent.match(/Из раздела «Справочники»/g) || []).length;
  check(occurrences===1,'подпись раздела на карточке выведена один раз');

  // 5. XSS safety.
  const xss='<img src=x onerror=alert(1)>';
  main.replaceChildren();drawer.replaceChildren();
  result(main,{
    query:{raw:xss,corrected:xss,corrections:[{from:xss,to:xss}],did_you_mean:xss},
    understood:{zero_reason:'not_in_catalog',agent_note:xss,chips:[{key:'vendor',label:xss,removable:true}]},
    facets:[{key:'vendor',title:xss,values:[{id:'x',label:xss,count:1}]}],
    blocks:[{type:'products',title:xss,total:1,items:[{title:xss,label:xss,reason:xss,fill:true,offer:{price:100}}]}]
  },{retail:true,understanding:drawer,apply:()=>{}});
  check(main.querySelectorAll('img').length===0 && drawer.querySelectorAll('img').length===0,'XSS защита: нет тегов img');
  check(main.textContent.includes(xss),'XSS строка выведена как текст');

  out.textContent='passed';
}catch(e){out.textContent=e.stack;}
