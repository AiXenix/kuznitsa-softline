import {catalogImport} from './import.js';
import {caption} from '../labels.js';
import {moneyRate,add,line,rows} from '../dom.js';
import {adminApi,section,table,loadBox,queryCols,options,phrase,samplePhrases,fmt,pct,valid,shortRub,groupText,resetData,tile,date,empty,shop} from './common.js';
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
    const k=await adminApi('kpi'),t=k.totals || {},grid=add(box,'div',null,'adminTiles');
    if(!Object.keys(t).length && !rows(k.funnel).length){empty(box,'Добавьте историю с событиями кликов и заказов.');return;}
    const n=t.behavioral_searches ?? t.searches;
    if(rows(k.funnel).length){for(const step of k.funnel)tile(grid,step.label || caption('',step.key),fmt(step.count));}
    else for(const [name,key,rate] of [['Поиски','behavioral_searches'],['С кликом','clicked','ctr'],['В корзину','carts','cart_rate'],['Заказ','orders','conversion']]){
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
    for(const r of items){const row=add(box,'div',null,'failureRow');add(row,'b',caption('reason',r.reason,r.label));add(row,'strong',fmt(r.count));bar(row,r.count,max,'#20786d');row.append(samplePhrases(r.examples || r.example,typeof r.example==='string'?{[r.example]:r.search_id}:{}));}
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
      add(box,'h3',name);table(box,slices[key],[['Название','label',(v,r)=>caption(key,r.key,v)],...searchColumns],{sortable:true,limit:key==='category'?15:null});
    }
  });
  loadBox(section(p,'Импортозамещение'),async box=>{
    const g=await adminApi('gaps'),tiles=add(box,'div',null,'adminTiles');
    if(!g.bridge)empty(tiles,'Нужны показы и клики по аналогам.');
    for(const [key,title] of [['impressions','Показы замен'],['clicks','Клики'],['carts','Корзины']])if(valid(g.bridge?.[key]))tile(tiles,title,fmt(g.bridge[key]));
    table(box,g.departed,[['Исходный продукт','title'],['Вендор','vendor',v=>caption('vendor',v)],['Поиски','searches'],['Сессии','sessions'],['Предыдущее окно','previous'],['Изменение','change']]);
  });
  findings(p,params,'product_manager');
}
export function content(p,params){
  loadBox(section(p,'Каких товаров не хватает'),async box=>{
    const g=await adminApi('gaps');
    const lead=rows(g.items)[0];
    if(lead)line(box,[caption('family',lead.key,lead.title),valid(lead.searches)?fmt(lead.searches)+' поисков':'',valid(lead.expected_rub)?shortRub(lead.expected_rub)+' потенциальных потерь':''].filter(Boolean).join(' · '),'roleLead');
    table(box,g.items,[['Кластер','title'],['Пример запроса','queries',(v,r)=>samplePhrases(r.examples || v,r.search_ids || (typeof v?.[0]==='string'?{[v[0]]:r.search_id}:{}))],['Вендор','vendor',v=>caption('vendor',v)],['Категория','category',v=>caption('category',v)],['Поиски','searches'],['Изменение','change'],['Сегменты','segments',groupText],['Оценка потерь','expected_rub',shortRub]],{limit:15,sortable:true});
    for(const [key,title] of [['vendor','По вендорам'],['category','По категориям']]){
      add(box,'h3',title);table(box,g.breakdown?.[key],[['Группа','key',v=>caption(key,v)],['Поиски','searches'],['Предыдущее окно','previous'],['Оценка потерь','expected_rub',shortRub]],{limit:8});
    }
  });
  loadBox(section(p,'Дефекты карточек'),async box=>{
    const g=await adminApi('gaps');table(box,g.card_defects,[['Карточка','title',(v,r)=>{const a=document.createElement('a');a.href=r.card_id?'/card/'+encodeURIComponent(r.card_id):shop(v);a.textContent=v || caption('family',r.card_id);return a;}],['Пропущенные поля','fields',v=>rows(v).join(', ')],['Показы','impressions']],{limit:12});
  });catalogImport(p);findings(p,params,'content_manager');
}
export function log(p){
  const panel=section(p,'Журнал поисков'),control=add(panel,'label','Обновлять каждые 5 с ','pollControl');
  const toggle=add(control,'input');toggle.type='checkbox';
  const host=add(panel,'div'),path='queries?kind=recent&limit=50';
  let timer,busy=false;
  function stop(){clearTimeout(timer);}
  function next(){stop();if(!busy && toggle.checked && panel.isConnected)timer=setTimeout(()=>draw(true),5000);}
  const cols=[['Москва','ts',date],['Запрос','q',(q,r)=>phrase(q || r.q_raw,r.search_id)],
    ['Профиль','profile_id',(v,r)=>caption('profile',v || r.client_id)],['Сегмент','segment',v=>caption('segment',v)],
    ['Режим','mode',v=>caption('mode',v)],['Сценарий','intent',v=>caption('intent',v)],['Карточки','n_cards'],
    ['Время, мс','ms'],['Цена','cost_rub',v=>moneyRate(v)],['Причина пустой выдачи','zero_reason',v=>caption('reason',v)]];
  function draw(fresh){
    if(busy || (!panel.isConnected && fresh))return;
    busy=true;
    if(fresh)resetData(path);
    const previous=host.firstElementChild;
    const content=loadBox(host,async box=>{
      try{
        const r=await adminApi(path);
        table(box,r.items,cols,{rowHref:r=>r.search_id && '/inspect/'+encodeURIComponent(r.search_id)});
      }catch(e){
        if(![404,422].includes(e.status))throw e;
        toggle.checked=false;control.hidden=true;
        line(box,'Журнал пока отдаёт агрегаты. Выберите фразу, чтобы открыть её последнюю запись.','hint');queries(box,'top');
      }finally{busy=false;previous?.remove();next();}
    });
    if(previous)content.setAttribute('aria-live','polite');
  }
  toggle.onchange=()=>{stop();if(toggle.checked)next();};
  window.addEventListener('hashchange',stop,{once:true});draw(false);
  loadBox(section(p,'Состав журнала'),async box=>{table(box,(await adminApi('ingest')).sources,[['Источник','source',v=>caption('source',v)],['Поиски','searches',v=>fmt(v)]]);});
  catalogImport(p);
}
