import {add,line,details,rows} from '../dom.js';
import {adminApi,loadBox,section,fmt,pct,rub,shortRub,ratio,valid,tile,table,empty,field,taskButton} from './common.js';
import {bar,trend} from './charts.js';

const weightNames={rel:'Релевантность',pop:'Популярность',margin:'Маржа',pers:'Профиль клиента'};
function headParam(key,value){
  const url=new URL(location.href);
  const [tab,query]=url.hash.slice(1).split('?');
  if(tab && tab!=='head')return;
  const params=new URLSearchParams(query);if(value)params.set(key,value);else params.delete(key);
  url.hash='head?'+params;history.replaceState(history.state,'',url);
}
function weights(parent,params){
  const panel=section(parent,'Рычаг прибыли');panel.dataset.section='weights';
  loadBox(panel,async p=>{
    const [config,top]=await Promise.all([adminApi('weights'),adminApi('queries?kind=top')]);
    const values={...config.weights};
    if(!Object.keys(weightNames).every(k=>valid(values[k]))){empty(p,'Проверьте настройки весов.');return;}
    const grid=add(p,'div',null,'weightGrid'), inputs={},out={};
    function update(k){
      const value=Number(inputs[k].value),others=Object.keys(values).filter(key=>key!==k);
      const sum=others.reduce((a,key)=>a+values[key],0);
      let remaining=10000-Math.round(value*10000);
      others.forEach((key,i)=>{
        const scaled=i===others.length-1?remaining:Math.min(remaining,Math.round(10000*(1-value)*(sum?values[key]/sum:1/others.length)));
        remaining-=scaled;values[key]=scaled/10000;
      });
      values[k]=value;paint();preview.replaceChildren();
    }
    function paint(){for(const k of Object.keys(inputs)){inputs[k].value=values[k];out[k].textContent=pct(values[k]);}}
    for(const [k,title] of Object.entries(weightNames)){
      const l=add(grid,'label',title);out[k]=add(l,'output');
      const i=inputs[k]=add(l,'input');i.type='range';i.min=0;i.max=1;i.step=.0001;i.oninput=()=>update(k);
    }
    paint();
    const form=add(p,'div',null,'adminControls');
    const input=field(form,'Запрос для сравнения',params.get('q') || top.items?.[0]?.q);
    const preview=add(p,'div');
    taskButton(form,'Предпросмотр',async()=>{
      const query=input.value.trim(),base=JSON.stringify(values);
      const r=await adminApi('preview','POST',{q:query||null,weights:{...values},limit:1});
      if(base!==JSON.stringify(values) || input.value.trim()!==query)return 'Параметры изменились. Повторите предпросмотр.';
      headParam('q',query);preview.replaceChildren();
      const tiles=add(preview,'div',null,'adminTiles');
      tile(tiles,'Инверсий полос',fmt(r.band_inversions));tile(tiles,'Позиций сдвинулось',fmt(r.moved));
      for(const item of rows(r.items)){
        line(preview,item.q,null,'h3');line(preview,'Изменение маржи · '+rub(item.margin_delta_rub));
        const before=rows(item.before),after=rows(item.after);
        table(preview,Array.from({length:Math.max(before.length,after.length)},(_,i)=>({before:before[i]?.title,after:after[i]?.title})),[['Было','before'],['Стало','after']]);
      }
      line(preview,r.formula,'muted');
    });
    taskButton(form,'Сохранить веса',async()=>{await adminApi('weights','POST',{...values});return 'Веса сохранены.';});
  });
}
function pair(p,item){
  if(!valid(item.before)||!valid(item.after))return;
  const card=add(p,'article',null,'pair');
  add(card,'h3',item.label || item.key);
  const rate=['rate','ratio','fraction'].includes(item.unit), percent=rate || ['percent','%','pct'].includes(item.unit);
  const scale=rate?100:1,unit=percent?' %':item.unit==='rub'?' ₽':'';
  const delta=(item.after-item.before)*scale;
  const low=['lower','less','down','min'].includes(item.better);
  const high=['higher','more','up','max'].includes(item.better);
  add(card,'strong',(delta>0?'+':'')+fmt(delta)+(percent?' п. п.':unit), 'delta'+((low && delta>0)||(high && delta<0)?' worse':''));

  const max=percent?100/scale:Math.max(item.before,item.after);
  for(const [name,n,color] of [['Прежний поиск',item.before,'#869895'],['Кузница',item.after,'#087969']]){
    const row=add(card,'div',null,'barLabel');add(row,'span',name);add(row,'b',fmt(n*scale)+unit);
    bar(card,n,max,color);
  }
}
async function replay(p,id){
  if(!id)return {};
  try{return await adminApi('replay/'+encodeURIComponent(id));}
  catch(e){line(p,e.message,'error');return {};}
}
export function head(p,params=new URLSearchParams()){
  loadBox(section(p,'Как изменился поиск'),async box=>{
    const k=await adminApi('kpi'), c=k.comparison || {};
    const r=await replay(box,c.run_id);
    const count=r.frequency ?? c.searches;
    const pairs=rows(k.pairs).length?k.pairs:[
      {label:'Пустая выдача',unit:'rate',better:'lower',before:ratio(r.before_zero ?? c.before_zero,count),after:ratio(r.after_zero ?? c.after_zero,count)},
      {label:'Цель в первой пятёрке',unit:'rate',better:'higher',before:ratio(r.before_top5,r.labeled),after:ratio(r.after_top5,r.labeled)}];
    const grid=add(box,'div',null,'adminTiles');
    for(const item of pairs)pair(grid,item);
    if(valid(r.recovered))tile(grid,'Возвращено поисков',fmt(r.recovered),'Появились подходящие предложения');
    if(!grid.childElementCount)empty(box,'Запустите парный прогон истории.');
    line(box,['Парный прогон на одной истории',valid(r.processed)?fmt(r.processed)+' фраз':'',valid(count)?fmt(count)+' поисков':'',valid(r.labeled)?'с разметкой цели · '+fmt(r.labeled):''].filter(Boolean).join(' · '),'muted');
  });
  loadBox(section(p,'Потенциал возврата заказов'),async box=>{
    const k=await adminApi('kpi'), lost=k.lost_orders || {};
    const r=await replay(box,k.comparison?.run_id);
    const grid=add(box,'div',null,'adminTiles');
    for(const [title,value] of [['Осторожная оценка',lost.conservative_rub],['Базовая оценка',lost.expected_rub],['С восстановленной выдачей',r.estimated_rub]]){
      if(valid(value))tile(grid,title,shortRub(value)).title=rub(value);
    }
    if(!grid.childElementCount)empty(box,'Добавьте историю поисков и заказов.');
    if(lost.formula_note || r.formula){const d=details(box,'Как рассчитано');line(d,lost.formula_note);line(d,r.formula);}
  });
  loadBox(section(p,'Поиски и заказы'),async box=>{
    const k=await adminApi('kpi'),grid=add(box,'div',null,'adminTiles');
    for(const t of rows(k.tiles))tile(grid,t.label,t.unit==='₽'?shortRub(t.value):fmt(t.value)+' '+(t.unit || ''));
    const charts=add(box,'div',null,'adminSplit');trend(charts,k.slices?.day,'searches','Поиски по дням');trend(charts,k.slices?.day,'zero_rate','Доля пустых выдач');
  });
  weights(p,params);
  const economics=section(p,'Экономика ИИ');economics.dataset.section='cost';
  loadBox(economics,async box=>{
    const dailyParam=params.get('daily');
    let data=await adminApi(dailyParam && /^\d+$/.test(dailyParam)?'cost?daily='+encodeURIComponent(dailyParam):'cost');
    const form=add(box,'div',null,'adminControls'), daily=field(form,'Запросов в сутки',data.requests_per_day,'number');daily.min=0;daily.step=1;
    const body=add(box,'div');
    function draw(){
      body.replaceChildren();
      line(body,valid(data.usd_rub)?'Курс · '+rub(data.usd_rub)+' за доллар':'','muted');
      if(!rows(data.items).some(i=>i.rub_per_query>0) && !data.cache_rate){line(body,'Ожидаются данные. Выполните поиск с обращением к модели.');return;}
      line(body,'Из кэша · '+pct(data.cache_rate));
      table(body,data.items,[['Режим','mode',v=>({smart_uncached:'Умный',smart_cached:'Умный с кэшем',fast:'Быстрый'})[v]||v],['За запрос','rub_per_query',v=>fmt(v,8)+' ₽'],['Прогноз за месяц','monthly_rub',rub]]);
      line(body,data.formula,'muted');
    }
    draw();taskButton(form,'Пересчитать',async()=>{if(!daily.value || !daily.reportValidity())throw Error('Введите целое число запросов.');data=await adminApi('cost?daily='+encodeURIComponent(daily.value));headParam('daily',daily.value);draw();},null,false);
  });
  loadBox(section(p,'Качество на проверочном наборе'),async box=>{
    const r=await adminApi('eval');line(box,r.file,'muted');
    table(box,Object.entries(r.scenarios || {}).map(([key,value])=>({key,...value})),[['Сценарий','key',v=>v==='unknown'?'Без разметки сценария':v],['Пройдено','passed'],['Проверок','total']]);
  });
}
