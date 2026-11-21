import {api} from './api.js';
import {add,button,line,link,rows,num} from './dom.js';
import {caption,loadMeta} from './labels.js';

const kinds={input:'Вход',step:'Обработка',data:'Данные',decision:'Решение',llm:'Категоризатор',fallback:'Запасной путь',output:'Результат'};
function svg(parent,name,attrs,text){
  const el=document.createElementNS('http://www.w3.org/2000/svg',name);
  for(const [key,val] of Object.entries(attrs))el.setAttribute(key,val);
  if(text!=null)el.textContent=text;
  parent.append(el);return el;
}
// Each edge labels its destination, including backward branches, in print and on mobile.
function diagram(p,f){
  const nodes=rows(f.nodes),edges=rows(f.edges),grid=add(p,'div',null,'flowMap');
  for(let start=0;start<nodes.length;start+=6){
    const chunk=nodes.slice(start,start+6),indices=new Map(chunk.map((n,i)=>[n.id,i]));
    const paths=edges.filter(e=>indices.has(e.from) && indices.has(e.to));
    const graph=svg(grid,'svg',{class:'flowGraph',role:'img','aria-label':f.title,viewBox:'0 0 500 '+(chunk.length*74+12)});
    for(const [j,e] of paths.entries()){
      const y1=indices.get(e.from)*74+26,y2=indices.get(e.to)*74+38,lane=316+166*(j+1)/(paths.length+1);
      svg(graph,'path',{d:'M295 '+y1+' H'+lane+' V'+y2+' H295 l7 -4 m-7 4 7 4',fill:'none',stroke:'#387268','stroke-width':2});
      if(e.label)svg(graph,'text',{x:303,y:y1-4,'font-size':13,fill:'#254b46'},e.label);
    }
    for(const [i,node] of chunk.entries()){
      const y=i*74+7;
      svg(graph,'rect',{x:6,y,width:289,height:51,rx:8,fill:node.type==='decision'?'#fff1d9':'#e1f2ec',stroke:'#84a89c'});
      svg(graph,'text',{x:17,y:y+17,'font-size':12},(start+i+1)+' · '+(kinds[node.type] || 'Шаг'));
      const t=svg(graph,'text',{x:17,y:y+39,'font-size':15,'font-weight':650},node.title.length>29?node.title.slice(0,28)+'…':node.title);
      svg(t,'title',{},node.title);
    }
  }
  const targets=new Map(nodes.map((node,i)=>[node.id,(i+1)+'. '+node.title]));
  for(const [i,node] of nodes.entries()){
    const box=add(grid,'article',null,'flowNode');box.dataset.kind=node.type;
    line(box,kinds[node.type] || 'Шаг','eyebrow');add(box,'h3',targets.get(node.id));
    line(box,node.detail);line(box,node.code,'muted','code');
    for(const edge of edges.filter(e=>e.from===node.id)){
      const branch=add(box,'div',null,'flowEdge');
      const arrow=svg(branch,'svg',{width:27,height:24,viewBox:'0 0 27 24','aria-hidden':true});
      svg(arrow,'path',{d:'M2 2v11h19m-5-5 5 5-5 5',fill:'none',stroke:'currentColor','stroke-width':2});
      line(branch,[edge.label,targets.get(edge.to)].filter(Boolean).join(' → '),null,'span');
    }
  }
}
export async function flows(main){
  document.title='Как работает поиск · Кузница Softline';
  main.classList.add('flowPage');add(main,'h1','Как работает поиск');
  const read=n=>api('/web-data/flows/'+n);
  const [doc,timings,examples]=await Promise.all([read('flows'),read('timings').catch(()=>({})),read('examples').catch(()=>({})),loadMeta().catch(()=>null)]);
  if(doc.sample)line(main,'Пример схемы · данные локальной трассы','badge');
  const nav=add(main,'div',null,'flowTools'),select=add(add(nav,'label','Путь запроса '),'select');
  button(nav,'Печать / PDF',()=>window.print());
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
    select.value=f.id;add(panel,'h2',f.title);line(panel,f.summary);diagram(panel,f);
    if(f.llm){
      add(panel,'h3','Решение категоризатора');
      for(const [key,title] of Object.entries({when:'Условие',question:'Вопрос',options:'Варианты',threshold:'Порог',fallback:'Запасной путь'})){
        const v=f.llm[key];if(v!=null)line(panel,title+' · '+(Array.isArray(v)?v.join(', '):v));
      }
    }
    if(!Object.keys(timings.by_flow?.[f.id] || {}).length)line(panel,'Отдельные замеры этого пути пока не опубликованы.','muted');
    for(const [mode,m] of Object.entries(timings.by_flow?.[f.id] || {})){
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
  select.onchange=()=>{location.hash=new URLSearchParams({flow:select.value});};
  window.addEventListener('hashchange',draw);draw();
}
