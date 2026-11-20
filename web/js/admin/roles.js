import {add,line,rows} from '../dom.js';
import {adminApi,section,table,loadBox,queryCols,options,phrase,fmt,pct,valid,shortRub,groupText,tile,date,empty,shop} from './common.js';
import {bar} from './charts.js';
import {findings} from './agent.js';
import {rules} from './rules.js';

function queries(p,kind){
  loadBox(p,async box=>{
    const data=await adminApi('queries?kind='+encodeURIComponent(kind));
    const leader=rows(data.items)[0];
    if(kind==='rising' && leader){
      const lead=add(box,'p',null,'roleLead');lead.append(phrase(leader.q,leader.search_id));
      if(valid(leader.recent) && valid(leader.previous))lead.append(' · прирост '+fmt(leader.recent-leader.previous)+' поисков');
    }
    const cols=[...queryCols];
    if(kind==='rising')cols.splice(2,3,['Текущее окно','recent'],['Предыдущее','previous'],['Прирост поисков','growth',(_,r)=>valid(r.recent)&&valid(r.previous)?fmt(r.recent-r.previous):'—']);
    table(box,data.items,cols,{limit:12,sortable:true});
  });
}
export function ecom(p,params){
  loadBox(section(p,'Где поиск теряет заказ'),async box=>{
    const t=(await adminApi('kpi')).totals || {},grid=add(box,'div',null,'adminTiles');
    if(!Object.keys(t).length){empty(box,'Добавьте историю с событиями кликов и заказов.');return;}
    const n=t.behavioral_searches ?? t.searches;
    for(const [name,key,rate] of [['Поиски','behavioral_searches'],['С кликом','clicked','ctr'],['В корзину','carts','cart_rate'],['Заказ','orders','conversion']]){
      const value=t[key] ?? (!rate?n:valid(n)&&valid(t[rate])?Math.round(n*t[rate]):null);
      tile(grid,name,fmt(value),rate && valid(t[rate])?pct(t[rate]):'');
    }
    const metrics=add(box,'div',null,'chips');
    for(const [title,k] of [['CTR первых трёх','ctr_top3'],['Средняя позиция клика','mean_click_position'],['Переформулировки','reformulation_rate'],['Уходы после неудачи','exit_after_failure']]){
      if(valid(t[k]))add(metrics,'span',title+' · '+(k==='mean_click_position'?fmt(t[k]):pct(t[k])),'chip');
    }
  });
  const panel=section(p,'Запросы для разбора'),choices={low_ctr:'Низкий CTR',reformulated:'Переформулировки',zero:'Без результата'};
  const selected=Object.hasOwn(choices,params.get('kind'))?params.get('kind'):'low_ctr';
  options(add(panel,'div',null,'adminControls'),'Подборка',choices,selected,v=>location.hash='ecom?kind='+v);queries(panel,selected);
  loadBox(section(p,'Причины неудач'),async box=>{
    const items=rows((await adminApi('failures')).items);
    if(!items.length)empty(box,'Соберите журнал неудачных поисков.');
    const max=Math.max(0,...items.map(i=>i.count || 0));
    for(const r of items){const row=add(box,'div',null,'failureRow');add(row,'b',r.label || r.reason);add(row,'strong',fmt(r.count));bar(row,r.count,max,'#20786d');row.append(phrase(r.example?.q || r.example,r.example?.search_id || r.search_id));}
  });
  findings(p,params,'ecom_manager');rules(p);
}
const searchColumns=[['Поиски','searches'],['Пустые','zero_rate',pct],['Конверсия','conversion',pct]];
export function product(p,params){
  const pulse=section(p,'Пульс спроса');
  const split=add(pulse,'div',null,'adminSplit');
  for(const [title,k] of [['Растущий спрос','rising'],['Популярные фразы','top']]){const box=add(split,'section');add(box,'h3',title);queries(box,k);}
  loadBox(section(p,'Срезы спроса'),async box=>{
    const slices=(await adminApi('kpi')).slices || {};
    for(const [key,name] of [['intent','Сценарии'],['category','Категории'],['segment','Сегменты']]){
      add(box,'h3',name);table(box,slices[key],[['Название','label',(v,r)=>v || r.key],...searchColumns],{sortable:true,limit:key==='category'?15:null});
    }
  });
  loadBox(section(p,'Импортозамещение'),async box=>{
    const g=await adminApi('gaps'),tiles=add(box,'div',null,'adminTiles');
    if(!g.bridge)empty(tiles,'Нужны показы и клики по аналогам.');
    for(const [key,title] of [['impressions','Показы замен'],['clicks','Клики'],['carts','Корзины']])if(valid(g.bridge?.[key]))tile(tiles,title,fmt(g.bridge[key]));
    table(box,g.departed,[['Исходный продукт','title'],['Вендор','vendor'],['Поиски','searches'],['Сессии','sessions'],['Предыдущее окно','previous'],['Изменение','change']]);
  });
  findings(p,params,'product_manager');
}
export function content(p,params){
  loadBox(section(p,'Каких товаров не хватает'),async box=>{
    const g=await adminApi('gaps');
    const lead=rows(g.items)[0];
    if(lead)line(box,[lead.title,valid(lead.searches)?fmt(lead.searches)+' поисков':'',valid(lead.expected_rub)?shortRub(lead.expected_rub)+' потенциальных потерь':''].filter(Boolean).join(' · '),'roleLead');
    table(box,g.items,[['Кластер','title'],['Пример запроса','queries',(v,r)=>{const q=rows(v)[0];return phrase(q?.q || q,q?.search_id || r.search_id);}],['Вендор','vendor'],['Категория','category'],['Поиски','searches'],['Изменение','change'],['Сегменты','segments',groupText],['Оценка потерь','expected_rub',shortRub]],{limit:15,sortable:true});
    for(const [key,title] of [['vendor','По вендорам'],['category','По категориям']]){
      add(box,'h3',title);table(box,g.breakdown?.[key],[['Группа','key'],['Поиски','searches'],['Предыдущее окно','previous'],['Оценка потерь','expected_rub',shortRub]],{limit:8});
    }
  });
  loadBox(section(p,'Дефекты карточек'),async box=>{
    const g=await adminApi('gaps');table(box,g.card_defects,[['Карточка','title',(v,r)=>{const a=document.createElement('a');a.href=r.card_id?'/card/'+encodeURIComponent(r.card_id):shop(v);a.textContent=v || r.card_id;return a;}],['Пропущенные поля','fields',v=>rows(v).join(', ')],['Показы','impressions']],{limit:12});
  });findings(p,params,'content_manager');
}
export function log(p){
  loadBox(section(p,'Журнал поисков'),async box=>{
    try{
      const r=await adminApi('queries?kind=recent');
      table(box,r.items,[['Москва','ts',date],['Запрос','q',(q,r)=>phrase(q || r.q_raw,r.search_id)],['Профиль','profile_id',(v,r)=>v || r.client_id || r.segment],['Режим','mode'],['Сценарий','intent'],['Карточки','n_cards'],['Время, мс','ms'],['Расход, $','llm_cost_usd',v=>fmt(v,8)]]);
    }catch(e){
      if(![404,422].includes(e.status))throw e;
      line(box,'Служебный API пока возвращает агрегаты. Ниже — популярные фразы со ссылками на записи.','hint');queries(box,'top');
    }
  });
  loadBox(section(p,'Состав журнала'),async box=>{table(box,(await adminApi('ingest')).sources,[['Источник','source'],['Поиски','searches',v=>fmt(v)]]);});
}
