import {api} from './api.js';
import {add,button,line,link,rows,num} from './dom.js';
import {caption,loadMeta} from './labels.js';

import {diagram,legend} from './diagram.js';
export async function flows(main){
  document.title='Как работает поиск · Кузница Softline';
  main.classList.add('flowPage');add(main,'h1','Как работает поиск');
  const read=n=>api('/web-data/flows/'+n);
  const [doc,timings,examples]=await Promise.all([read('flows'),read('timings').catch(()=>({})),read('examples').catch(()=>({})),loadMeta().catch(()=>null)]);
  if(doc.sample)line(main,'Пример схемы · данные локальной трассы','badge');
  const nav=add(main,'div',null,'flowTools'),select=add(add(nav,'label','Путь запроса '),'select');
  const modeSelect=add(add(nav,'label','Режим '),'select');
  modeSelect.add(new Option('Быстрый','fast'));modeSelect.add(new Option('Умный','smart'));
  button(nav,'Печать схемы / PDF',()=>window.print());
  button(nav,'Печать всех схем',()=>{main.classList.add('printAll');window.print();});
  const printArea=add(main,'div',null,'printSheets');
  window.addEventListener('beforeprint',()=>{
    printArea.replaceChildren();
    for(const f of rows(doc.flows).filter(f=>main.classList.contains('printAll') || f.id===select.value)){
      const sheet=add(printArea,'section');add(sheet,'h2',f.title+' · '+modeSelect.selectedOptions[0].text);
      legend(sheet);diagram(sheet,f,timings.by_flow?.[f.id]?.[modeSelect.value]?.steps || {});
    }
  });
  window.addEventListener('afterprint',()=>{main.classList.remove('printAll');printArea.replaceChildren();});
  const groups=new Map();
  for(const f of rows(doc.flows)){
    if(!groups.has(f.kind)){const group=add(select,'optgroup');group.label=f.kind==='path'?'Сквозные пути':'Виды запросов';groups.set(f.kind,group);}
    groups.get(f.kind).append(new Option(f.title,f.id));
  }
  const panel=add(main,'section',null,'panel');
  function draw(){
    const id=new URLSearchParams(location.hash.slice(1)).get('flow');
    const f=rows(doc.flows).find(f=>f.id===id) || doc.flows?.[0];
    panel.replaceChildren();if(!f){line(panel,'Схемы пока не опубликованы.');return;}
    select.value=f.id;add(panel,'h2',f.title);line(panel,f.summary);legend(panel);diagram(panel,f,timings.by_flow?.[f.id]?.[modeSelect.value]?.steps || {});
    const details=add(panel,'details');add(details,'summary','Что происходит на шагах');
    for(const n of rows(f.nodes)){add(details,'h4',n.title);line(details,n.detail);line(details,n.code,'muted','code');}
    if(f.llm){
      add(panel,'h3','Решение категоризатора');
      for(const [key,title] of Object.entries({when:'Условие',question:'Вопрос',options:'Варианты',threshold:'Порог',fallback:'Запасной путь'})){
        const v=f.llm[key];if(v!=null)line(panel,title+' · '+(Array.isArray(v)?v.join(', '):v));
      }
    }
    if(!Object.keys(timings.by_flow?.[f.id] || {}).length)line(panel,'Отдельные замеры этого пути пока не опубликованы.','muted');
    for(const [mode,m] of Object.entries(timings.by_flow?.[f.id] || {})){
      if(mode!==modeSelect.value)continue;
      if(!m.total && !m.steps)continue;
      add(panel,'h3',caption('mode',mode)+' · время в миллисекундах');if(m.n!=null)line(panel,'Замеров · '+num(m.n));
      const datasets=Object.entries(m.datasets || {}).map(([k,v])=>(({dev:'Проверочный набор',seen:'Знакомые пробы',examples:'Примеры'})[k] || k)+' · '+num(v));
      line(panel,datasets.join(' / '),'muted');
      const data=Object.entries({...(m.total?{total:m.total}:{}),...m.steps});
      const max=Math.max(1,...data.map(([,v])=>v?.p95 || 0));
      for(const [key,v] of data){
        if(v?.p50==null && v?.p95==null)continue;
        const row=add(panel,'div',null,'flowTiming');
        line(row,key==='total'?'Весь запрос':rows(doc.pipeline).find(s=>s.step===key)?.title || caption('',key),null,'b');
        const meter=add(row,'progress');meter.max=max;meter.value=v.p95 ?? v.p50;
        line(row,[v.p50!=null?'p50 · '+num(v.p50):'',v.p95!=null?'p95 · '+num(v.p95):''].filter(Boolean).join(' / '),null,'span');
      }
    }
    for(const [title,items] of [['За счёт чего быстро',f.speed],['Что получает бизнес',f.business]]){
      if(rows(items).length){add(panel,'h3',title);const list=add(panel,'ul');for(const s of items)add(list,'li',s);}
    }
    const samples=rows(examples.by_flow?.[f.id]);if(samples.length)add(panel,'h3','Запросы с разбором');
    for(const s of samples){
      const row=add(panel,'p');link(row,s.q,'/?'+new URLSearchParams({q:s.q,profile:s.profile || 'guest',mode:s.mode || 'fast',...(s.category_ctx?{category:s.category_ctx}:{})}));
      line(row,[s.first_card,caption('intent',s.intent),rows(s.blocks).map(id=>caption('block',id)).join(', '),s.ms!=null?num(s.ms)+' мс':''].filter(Boolean).join(' · '),'muted');
    }
  }
  modeSelect.onchange=draw;
  select.onchange=()=>{location.hash=new URLSearchParams({flow:select.value});};
  window.addEventListener('hashchange',draw);draw();
}
