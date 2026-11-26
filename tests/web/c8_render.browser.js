import {result} from './store/result.js';
import {record} from './store/events.js';
import {suggestions} from './store/suggest.js';
import {upsell} from './admin/upsell.js';
import {resetData} from './admin/common.js';

const main=document.querySelector('main'),out=document.querySelector('output');
function check(v,msg){if(!v)throw Error(msg);}
const tick=()=>new Promise(r=>setTimeout(r,200));
try{
  const rule=JSON.parse(document.querySelector('#fixtures').textContent)[0];
  const offer={offer_id:'sku',available:true,price:80,oldprice:100};
  const product={card_id:'os',title:'Операционная система',offer};
  const extra={...product,card_id:'backup',title:'Резервное копирование'};
  const response={search_id:'s',understood:{chips:[{key:'domain',label:'Искали ПО для сервера?',q:'ПО для сервера'}]},
    blocks:[{type:'products',items:[product,{card:extra,kind:'upsell',rule_id:rule.id,reason:rule.reason},{...product,fill:true,offer:{price:0,available:false}}]},
      {type:'crosssell',items:[{card:extra,rule_id:rule.id}]}]};
  let patch;
  result(main,response,{retail:true,apply:p=>patch=p});
  const tiles=main.querySelectorAll('.offerTile');
  check(tiles.length===4 && tiles[1].textContent.includes(rule.reason) && tiles[2].querySelector('.fillLabel'),'Рекомендации и добор');
  check(tiles[0].querySelector('del').textContent.includes('100') && tiles[0].querySelector('.deal').textContent==='Акция −20 %','Акция');
  check(tiles[2].textContent.includes('Цена по запросу') && tiles[2].textContent.includes('Под заказ'),'Наличие и нулевая цена');
  main.querySelector('button.chip').click();check(patch.q==='ПО для сервера','Переход к ПО');
  let events=[];window.fetch=async(_,o)=>{events.push(JSON.parse(o.body));return new Response(null,{status:204});};
  await record(response,'impression');
  check(events.filter(e=>e.card_id==='backup' && e.payload.rule_id===rule.id).length===2,'Счётчики рекомендаций в двух блоках');

  const input=document.createElement('input'),panel=document.createElement('div');main.replaceChildren(input,panel);
  let calls=0,selection;
  window.fetch=async()=>{calls++;return Response.json({groups:['queries','products','categories','upsell'].map(type=>({type,items:Array.from({length:8},(_,i)=>({text:'Кас '+i,meta:type==='categories'?'650':null,price:80,badges:[{kind:'promo',label:'Акция −20 %'}]}))}))});};
  suggestions(input,panel,()=>({}),(q,criteria)=>selection=criteria);
  input.value='к';input.dispatchEvent(new Event('input'));await tick();check(calls===0,'Порог подсказок');
  input.value='ка';input.dispatchEvent(new Event('input'));await tick();
  const groups=[...panel.querySelectorAll('[role=group]')];
  check(groups.map(g=>g.querySelectorAll('.option').length).join(',')==='8,4,3,2','Лимиты товарных групп');
  check(groups[1].querySelector('.deal') && groups[1].querySelector('.suggestPrice'),'Цена и акция при наборе');
  groups[2].querySelector('.option').click();check(selection.category==='650','Раздел из подсказки');

  let current={...rule,counters:{impressions:17,clicks:3,carts:1}},preview,updated;
  window.fetch=async(url,o)=>{
    if(url.startsWith('/web-data/catalog-sections'))return Response.json({'1033':'Резервное копирование'});
    if(url.endsWith('/upsell/preview')){preview=JSON.parse(o.body);return Response.json({matched:true,items:[extra]});}
    if(url.endsWith('/upsell/'+rule.id)){updated=JSON.parse(o.body);current={...current,...updated};return Response.json({rule:current});}
    check(url.endsWith('/upsell'),'Маршрут API');return Response.json({items:[current]});
  };
  resetData();sessionStorage.kzAdminKey='local-test';main.replaceChildren();upsell(main);await tick();
  check(main.querySelector('tbody').textContent.includes('Резервное копирование') && main.querySelector('tbody').textContent.includes('17'),'Подписи и счётчики API');
  const find=t=>[...main.querySelectorAll('button')].find(b=>b.textContent===t);
  find('Изменить').click();find('Предпросмотр').click();await tick();
  check(preview.rule.id===rule.id && preview.q==='astra linux' && main.textContent.includes('Условия совпали'),'Предпросмотр черновика');
  find('Сохранить').click();await tick();check(updated.reason===rule.reason && updated.weight===rule.weight && !updated.counters,'Тело PUT по контракту B');
  find('Включено').click();await tick();check(updated.enabled===false && find('Выключено'),'Отключение правила');
  resetData();main.replaceChildren();window.fetch=async url=>{
    if(url.endsWith('/upsell'))return Response.json({}, {status:404});
    if(url.endsWith('/upsell-list.json'))return Response.json({items:[current]});
    return Response.json({});
  };
  upsell(main);await tick();
  check(main.innerText.includes('Образец из отчёта') && find('Новое правило').disabled && !find('Изменить'),'Образец до слияния API');
  out.textContent='passed';
}catch(e){out.textContent=e.stack;}
