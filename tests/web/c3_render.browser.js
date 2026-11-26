import {setMeta,caption} from './store/labels.js';
import {money,moneyRate} from './store/dom.js';
import {result} from './store/result.js';
import {trace} from './store/trace.js';
import {suggestions} from './store/suggest.js';

const out=document.querySelector('output'),main=document.querySelector('main');
function check(ok,msg){if(!ok)throw Error(msg);}
try{
  setMeta({vendors:[{id:'red_hat',name:'Red Hat'}]});
  check(caption('vendor','red_hat')==='Red Hat' && caption('category','new_ai')==='New ai','Словари и резервная подпись');
  check(money(31500)==='31 500 ₽' && money(.00954284)==='≈ 0,0095 ₽' && money(null)==='','Деньги');
  check(moneyRate(.0095).includes('9,5 ₽ за 1 000'),'Масштаб цены');
  for(const r of JSON.parse(document.querySelector('#fixtures').textContent)){
    main.replaceChildren();result(main,r);trace(main,r);
    check(!main.innerText.includes('undefined'),'Образец '+r.understood?.intent);
  }
  for(const [id,expected] of Object.entries({off_topic:'Раздел',unknown_term:'Не узнали',not_in_catalog:'Сообщить о появлении',vendor_left:'Поставки',filters_too_strict:'Снять бюджет',qty_out_of_range:'10–20',no_available_offer:'Запросить счёт'})){
    let patch=null;main.replaceChildren();
    result(main,{understood:{zero_reason:id},blocks:[{type:'analogs',items:[{title:'Замена',offer:{qty_min:10,qty_max:20}}]}],
      relax_hints:[{label:'Снять бюджет',drop:'budget'}]}, {categories:[{id:'security',title:'Раздел защиты'}],apply:v=>patch=v,act:()=>{}});
    check(main.innerText.includes(expected),id);
    [...main.querySelectorAll('button.chip')].find(b=>b.textContent.includes('Снять бюджет')).click();check(patch.ignore?.[0]==='budget','Снятие условия');
  }
  let action;main.replaceChildren();
  const product={title:'Длинное название семейства',offer:{name:'Название семейства, продление',available:false,offer_id:'o',action:'renewal',term_months:12},score:{tier_label:'Точное соответствие',why:['По условиям запроса','По отрасли']}};
  result(main,{blocks:[{type:'products',items:[product]}]},{act:(type,c)=>action=[type,c]});
  check(main.querySelector('.cardHead').innerText.includes('Точное соответствие') && main.querySelector('.whyFirst').textContent==='По условиям запроса','Уровень и причина');
  check(main.querySelector('.conditions').textContent.includes('Продление') && main.querySelector('.purchase').textContent.includes('Под заказ'),'Лицензия и наличие');
  main.querySelector('.purchase button').click();check(action[0]==='lead' && action[1]===product,'Заявка по карточке');
  main.replaceChildren();result(main,{});trace(main,{cost:{llm_calls:0,cached:2,rub:0,saved_rub:.0123},trace:[{step:'log',detail:{}}]});
  check(main.innerText.includes('оба из кэша') && main.innerText.includes('без кэша') && !main.querySelector('pre'),'Кэш и стоимость');
  const input=document.createElement('input'),panel=document.createElement('div');
  main.append(input,panel);let chosen,signal;
  window.fetch=async (url,opts)=>{
    signal=opts.signal;
    return new Response(JSON.stringify({corrected:'Касперский',groups:['extra','vendors','licenses','queries','corrections','categories','products'].map(type=>({type,title:'Группа '+type,items:[{text:'Касперский',q:'защита',hint:'для офиса'}]}))}));
  };
  suggestions(input,panel,()=>({}),q=>chosen=q);
  input.value='кас';input.dispatchEvent(new Event('input'));await new Promise(resolve=>setTimeout(resolve,200));
  const groups=[...panel.querySelectorAll('[role=group]')].map(g=>g.getAttribute('aria-label'));
  check(groups.join(',')==='Возможно, вы имели в виду,Разделы,Запросы,Товары,Группа licenses,Группа vendors,Группа extra','Порядок групп');
  check(panel.querySelector('mark').textContent==='Кас' && panel.innerText.includes('для офиса') && panel.innerText.includes('Возможно, вы имели в виду'),'Текст подсказки');
  for(const key of ['ArrowDown','Enter','Escape'])input.dispatchEvent(new KeyboardEvent('keydown',{key}));
  check(chosen==='защита' && signal.aborted && panel.hidden,'Клавиши, запрос и отмена');
  out.textContent='passed';
}catch(e){out.textContent=e.stack;}
