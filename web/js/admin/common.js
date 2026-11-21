import {caption,readable} from '../labels.js';
import {putText,money,add,button,line,link,rows,stateBox} from '../dom.js';

const pending=new Map();
export function resetData(path){if(path)pending.delete(path);else pending.clear();}
export async function adminApi(path,method='GET',body){
  const token=sessionStorage.getItem('kzAdminKey');
  if(method!=='GET' && !token)throw Error('Нужен ключ доступа. Введите его в шапке консоли.');
  const cached=pending.get(path);
  if(method==='GET' && cached)return cached;
  const load=async()=>{
    let r;
    const signal=method==='GET'?AbortSignal.timeout(15000):undefined;
    try{r=await fetch('/api/admin/'+path,{method,signal,headers:{...(token?{'X-Admin-Token':token}:{}),...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});}
    catch{if(signal?.aborted)throw Error('Сервер не ответил за 15 секунд.');throw Error('Нет связи со служебным API. Проверьте подключение.');}
    if(!r.ok){
      const data=await r.json().catch(()=>null);
      const text=r.status===403?'Доступ закрыт. Проверьте ключ в шапке.':data?.error?.message || 'Данные недоступны.';
      const err=Error('HTTP '+r.status+' · '+text);err.status=r.status;throw err;
    }
    if(method!=='GET')resetData();
    return r.status===204?{}:await r.json() || {};
  };
  const task=load();
  if(method==='GET'){
    pending.set(path,task);
    task.catch(err=>{
      const unsupportedRecent=path.startsWith('queries?kind=recent&') && [404,422].includes(err.status);
      if(!unsupportedRecent && pending.get(path)===task)pending.delete(path);
    });
  }
  return task;
}
export const roles={head_ecom:'Руководитель',ecom_manager:'Менеджер e-com',product_manager:'Продукт-менеджер',content_manager:'Контент-менеджер'};
export const types={add_synonym:'Синоним',add_product:'Новый товар',fix_card:'Данные карточки',merch_rule:'Правило выдачи',rising_demand:'Рост спроса',hot_lead:'Горячий лид',renewal_campaign:'Продления',weights_advice:'Веса'};
export const statuses={new:'Новое',applied:'Применено',verified:'Проверено',rejected:'Отклонено'};
export const valid=n=>typeof n==='number' && Number.isFinite(n);
export const fmt=(n,digits=1)=>valid(n)?n.toLocaleString('ru-RU',{maximumFractionDigits:digits}):'—';
export const pct=n=>valid(n)?fmt(n*100)+' %':'—';
export const rub=n=>valid(n)?money(n):'—';
export function shortRub(n){
  if(valid(n) && Math.abs(n)>=1e9)return fmt(n/1e9)+' млрд ₽';
  if(valid(n) && Math.abs(n)>=1e6)return fmt(n/1e6)+' млн ₽';
  return rub(n);
}
export const ratio=(n,d)=>valid(n)&&valid(d)&&d>0?n/d:null;
export function date(v){
  if(v==null || v==='')return '—';
  const dt=new Date(typeof v==='number' && Math.abs(v)<1e11?v*1000:v);
  return Number.isNaN(+dt)?'—':dt.toLocaleString('ru-RU',{timeZone:'Europe/Moscow',dateStyle:'short',timeStyle:'short'});
}
export function empty(p,help='Измените фильтры или выполните поиск на витрине.'){stateBox(p,'Данных нет. '+help);}
export function section(p,title){const s=add(p,'section',null,'adminPanel');add(s,'h2',title);return s;}
export function tile(p,title,value,sub){const box=add(p,'div',null,'adminTile');add(box,'small',title);add(box,'strong',value);line(box,sub,'muted');return box;}
export function options(p,title,choices,value,change){
  const l=add(p,'label',title),s=add(l,'select');
  for(const [id,name] of Object.entries(choices))s.add(new Option(name,id));
  s.value=value;s.onchange=()=>change(s.value);return s;
}
export function field(p,title,value='',type='text'){
  const input=add(add(p,'label',title),'input');input.type=type;input.value=value ?? '';return input;
}
export function shop(q){return '/?'+new URLSearchParams({q});}
export function phrase(q,id){
  const box=document.createElement('span');if(!q)return box;
  if(id)link(box,q,'/inspect/'+encodeURIComponent(id));
  else {const a=link(box,q,'/inspect/by-query?'+new URLSearchParams({q}));a.title='Последняя запись журнала с этой фразой';}
  const a=link(box,' ↗',shop(q));a.setAttribute('aria-label','На витрину · '+q);a.target='_blank';a.rel='noopener';
  return box;
}
export function samplePhrases(values,ids={}){
  const cell=document.createElement('div');
  const items=Array.isArray(values)?rows(values):values?[values]:[];
  let container=cell;
  for(const [index,sample] of items.entries()){
    const q=typeof sample==='string'?sample:sample.q;
    if(!q)continue;
    if(index===1){
      const more=add(cell,'details');add(more,'summary','Ещё примеры · '+fmt(items.length-1));container=more;
    }
    const row=add(container,'div');row.append(phrase(q,sample.search_id || ids[q]));
  }
  return cell;
}
// Column definitions share the same accessor for sorting and numeric display.
export function table(p,items,cols,{limit,sortable=false,rowHref}={}){
  let data=[...rows(items)],expanded=false,sortKey=null,ascending=true;
  if(!data.length){empty(p);return;}
  const wrap=add(p,'div',null,'adminTable');const t=add(wrap,'table'),head=add(add(t,'thead'),'tr'),body=add(t,'tbody');
  const render=()=>{
    body.replaceChildren();
    for(const r of expanded || !limit?data:data.slice(0,limit)){
      const tr=add(body,'tr');
      if(rowHref && rowHref(r)){tr.className='linkedRow';tr.onclick=e=>{if(!e.target.closest('a'))location.assign(rowHref(r));};}
      for(const [,key,format] of cols){
        const td=add(tr,'td'),v=r[key],out=format?format(v,r):v;
        if(out instanceof Node)td.append(out);else putText(td,typeof out==='number'?fmt(out):out==null?'—':readable(String(out)));
      }
    }
  };
  for(const [title,key] of cols){
    const th=add(head,'th');
    if(!sortable){th.textContent=title;continue;}
    button(th,title+' ↕',()=>{
      ascending=sortKey===key?!ascending:typeof data.find(r=>r[key]!=null)?.[key]!=='number';sortKey=key;
      data.sort((a,b)=>(ascending?1:-1)*(typeof a[key]==='number' && typeof b[key]==='number'?a[key]-b[key]:String(a[key]??'').localeCompare(String(b[key]??''),'ru')));
      render();
    });
  }
  render();if(limit && data.length>limit)button(p,'Ещё · '+fmt(data.length-limit),e=>{expanded=true;render();e.currentTarget.remove();});
}
export function loadBox(p,fn){
  const content=add(p,'div');
  let version=0;
  function retry(message){
    content.replaceChildren();stateBox(content,message,'error');button(content,'Повторить',run);
  }
  async function run(){
    const current=++version,temp=document.createElement('div');
    content.replaceChildren();
    const skeleton=add(content,'div',null,'skeleton');
    skeleton.setAttribute('aria-label','Загрузка данных');skeleton.setAttribute('role','status');
    const timeout=setTimeout(()=>{if(current===version)retry('Отчёт готовится дольше 15 секунд.');},15000);
    try{await fn(temp);if(current===version)content.replaceChildren(temp);}
    catch(e){if(current===version)retry(e.message);}
    finally{clearTimeout(timeout);}
  }
  run();return content;
}
export function taskButton(p,title,fn,cls,needsKey=true){
  const note=add(p,'small',null,'actionNote');note.setAttribute('role','status');
  const b=button(p,title,async()=>{
    if(needsKey && !sessionStorage.kzAdminKey){note.textContent='Нужен ключ доступа';return;}
    b.disabled=true;note.textContent='Выполняется…';
    try {const msg=await fn();note.textContent=msg || 'Готово';}
    catch(e){note.textContent=e.message;}
    finally{b.disabled=false;}
  },cls);p.insertBefore(b,note);return b;
}
export function keyField(p,refresh){
  const input=field(p,'Ключ доступа',sessionStorage.getItem('kzAdminKey'),'password');input.autocomplete='off';
  function store(){sessionStorage.setItem('kzAdminKey',input.value.trim());resetData();}
  input.oninput=store;
  input.onchange=()=>{store();if(document.querySelector('.error'))refresh?.();};
  input.onkeydown=e=>{if(e.key==='Enter'){store();refresh?.();}};

}
export const queryCols=[['Запрос','q',(v,r)=>phrase(v,r.search_id)],['Поиски','count',v=>fmt(v)],['С кликом','clicks',v=>fmt(v)],['Пустые','zero',v=>fmt(v)],['Переформулировки','reformulated',v=>fmt(v)]];
export function groupText(v){return Object.entries(v || {}).map(([k,n])=>caption('segment',k)+' · '+fmt(n)).join(', ');}
