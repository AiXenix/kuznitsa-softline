import {add,rows} from '../dom.js';
import {fmt,pct,valid,empty} from './common.js';
function svg(parent,tag,attrs,text){
  const e=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);
  if(text!=null)e.textContent=text;parent.append(e);return e;
}
export function bar(parent,value,max,color){
  if(!valid(value)||!valid(max))return;
  const s=svg(parent,'svg',{viewBox:'0 0 100 6',preserveAspectRatio:'none',class:'barSvg','aria-hidden':true});
  svg(s,'rect',{width:100,height:6,fill:'#e6ece8'});svg(s,'rect',{width:max>0?Math.max(0,Math.min(100,100*value/max)):0,height:6,fill:color});
}
export function trend(p,days,key,title){
  const data=rows(days).filter(d=>d.key && valid(d[key])).sort((a,b)=>a.key.localeCompare(b.key));
  if(!data.length){empty(p,'Загрузите историю с датами.');return;}
  const f=key==='zero_rate'?pct:fmt;
  const max=Math.max(...data.map(d=>d[key])), chart=add(p,'figure');add(chart,'figcaption',title);
  const s=svg(chart,'svg',{viewBox:'0 0 460 130',role:'img','aria-label':title});
  const x=i=>58+390*i/Math.max(1,data.length-1),y=v=>98-(max>0?v/max:0)*78;
  for(const v of new Set([0,max/2,max])){
    svg(s,'line',{x1:58,x2:448,y1:y(v),y2:y(v),stroke:'#d9e3de'});svg(s,'text',{x:52,y:y(v)+4,'text-anchor':'end'},f(v));
  }
  svg(s,'polyline',{points:data.map((d,i)=>x(i)+','+y(d[key])).join(' '),fill:'none',stroke:'#00695b','stroke-width':3});
  svg(s,'text',{x:58,y:122},data[0].key);svg(s,'text',{x:448,y:122,'text-anchor':'end'},data.at(-1).key);
}
