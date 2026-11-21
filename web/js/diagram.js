import {add,num} from './dom.js';

export const kinds={input:'Вход',step:'Обработка',data:'Данные',decision:'Решение',llm:'Категоризатор',fallback:'Запасной путь',output:'Результат'};
function svg(parent,name,attrs,text){
  const el=document.createElementNS('http://www.w3.org/2000/svg',name);
  for(const [key,v] of Object.entries(attrs))el.setAttribute(key,v);
  if(text!=null)el.textContent=text;
  parent.append(el);return el;
}
function wrap(text,measure,limit){
  const lines=[];
  let current='';
  for(let word of String(text).split(/\s+/)){
    const combined=current ? current+' '+word : word;
    if(measure(combined)<=limit){current=combined;continue;}
    if(current)lines.push(current);
    current='';
    for(const letter of word){
      if(current && measure(current+letter)>limit){lines.push(current);current='';}
      current+=letter;
    }
  }
  if(current)lines.push(current);
  return lines;
}
export function diagram(p,f,measurements){
  const nodes=f.nodes || [],edges=f.edges || [];
  // Longest-path layers keep alternatives together and put joins below every parent.
  const ranks=new Map(),todo=new Set(nodes.map(n=>n.id));
  while(todo.size){
    const ready=[...todo].filter(id=>!edges.some(e=>e.to===id && todo.has(e.from)));
    if(!ready.length)ready.push(todo.values().next().value);
    for(const id of ready){
      ranks.set(id,Math.max(0,...edges.filter(e=>e.to===id && ranks.has(e.from)).map(e=>ranks.get(e.from)+1)));
      todo.delete(id);
    }
  }
  const layers=Array.from({length:Math.max(0,...ranks.values())+1},()=>[]);
  nodes.forEach((n,i)=>layers[ranks.get(n.id)].push({...n,number:i+1}));
  const W=258,gap=52,width=Math.max(1,...layers.map(l=>l.length))*(W+gap)+70;
  const context=document.createElement('canvas').getContext('2d');
  const family=getComputedStyle(p).fontFamily;
  function lines(text,font){
    context.font=font+' '+family;
    return wrap(text,s=>context.measureText(s).width,W-28);
  }
  const positions=new Map();let y=12;
  for(const layer of layers){
    let h=0;
    layer.forEach((n,i)=>{
      const x=(width-layer.length*(W+gap))/2+i*(W+gap),title=lines(n.title,'650 16px');
      const m=measurements?.[n.step],branches=edges.filter(e=>e.from===n.id);
      const labels=branches.map(e=>lines([e.label,'→ '+(nodes.findIndex(v=>v.id===e.to)+1)].filter(Boolean).join(' '),'13px'));
      const timing=measurements===undefined?'':m?.p50!=null && m.p95!=null?'p50 '+num(m.p50)+' · p95 '+num(m.p95)+' мс':'Нет отдельного замера';
      const base=42+title.length*21+(timing?20:0);
      const height=base+labels.reduce((a,l)=>a+l.length*16+5,0);
      positions.set(n.id,{n,x,y,title,timing,labels,branches,base,height});h=Math.max(h,height);
    });
    y+=h+36;
  }
  const graph=svg(p,'svg',{class:'juryGraph',role:'img',width,'aria-label':f.title,viewBox:'0 0 '+width+' '+y});
  for(const b of positions.values()){
    let port=b.y+b.base;
    b.branches.forEach((e,i)=>{
      const end=positions.get(e.to),outY=port+6;port+=b.labels[i].length*16+5;
      if(!end)return;
      const lane=b.x+W+8+i*6,target=end.x+W/2;
      const rail=ranks.get(e.to)===ranks.get(e.from)+1?lane:width-6-(edges.indexOf(e)%8)*4;
      // Long branches use an outside rail, keeping all text inside node boxes.
      const firstTurn=end.y-13-(i%4)*4;
      const startTurn=layers[ranks.get(e.from)].reduce((v,n)=>Math.max(v,positions.get(n.id).y+positions.get(n.id).height),0)+8+i*3;
      svg(graph,'path',{d:'M'+(b.x+W)+' '+outY+' H'+lane+' V'+startTurn+' H'+rail+' V'+firstTurn+' H'+target+' V'+end.y+' l-4 -7 m4 7 4 -7',fill:'none',stroke:'#478078','stroke-width':1.6});
    });
  }
  for(const b of positions.values()){
    const {n,x,y}=b,g=svg(graph,'g',{'data-node':n.id,'data-type':n.type || 'step'});
    svg(g,'rect',{x,y,width:W,height:b.height,rx:9});
    const text=(str,dy,cls)=>svg(g,'text',{x:x+12,y:y+dy,class:cls},str);
    text(n.number+' · '+(kinds[n.type] || kinds.step),19,'nodeKind');
    b.title.forEach((s,i)=>text(s,43+i*21,'nodeTitle'));
    if(b.timing)text(b.timing,44+b.title.length*21,'nodeTime');
    let port=b.base;for(const parts of b.labels){parts.forEach(s=>{text(s,port+11,'edgeLabel');port+=16;});port+=5;}
    svg(g,'title',{},[n.detail,n.code].filter(Boolean).join('\n'));
  }
  return graph;
}
export function legend(p){
  const box=add(p,'div',null,'flowLegend');
  Object.entries(kinds).forEach(([key,title])=>{add(box,'span',title).dataset.type=key;});
}
