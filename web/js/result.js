import {add,line,button,details,rows,label,counted,stateBox} from './dom.js';
import {block} from './blocks.js';

export function result(p,r,ctx={}) {
  const u=r.understood || {};
  function action(parent,title,patch) {
    if (ctx.apply) button(parent,title,()=>ctx.apply(patch),'chip');
    else line(parent,title,'chip','span');
  }
  if (Object.keys(u).length) {
    const panel=add(p,'section',null,'understood');
    add(panel,'h2','Понято так');
    line(panel,u.agent_note || u.intent_title);
    const chips=add(panel,'div',null,'chips');
    for(const c of rows(u.chips)) {
      if(c.removable && c.key) action(chips,c.label+' ×',{ignore:[c.key]});
      else line(chips,c.label,'badge','span');
    }
    if(r.query?.corrected && rows(r.query.corrections).length) {
      line(panel,'Показаны результаты по «'+r.query.corrected+'»');
      action(panel,'Искать как было',{verbatim:true});
    }
    if (typeof r.query?.did_you_mean==='string') {
      action(panel,'Возможно, вы искали «'+r.query.did_you_mean+'»',{q:r.query.did_you_mean});
    }
    if(u.inherited?.from_q) {
      line(panel,'В контексте запроса «'+(u.inherited.from_q || '')+'»');
      action(panel,'Начать заново',{context:'off'});
    }
  }
  for(const b of rows(r.banners)) line(p,b.text,'banner');
  for(const n of rows(r.notes)) line(p,label(n),'hint');
  const facets=rows(r.facets).filter(f=>rows(f.values).length);
  if(facets.length && ctx.apply) {
    const d=details(p,'Уточнить выдачу');
    for(const f of facets) {
      line(d,f.title,null,'h3');
      for(const v of rows(f.values)) action(d,counted(v.label,v.count),{filters:{[f.key]:v.id}});
    }
  }
  for(const h of rows(r.relax_hints)) action(p,counted(h.label,h.count),{ignore:[h.drop],...h.apply});
  if(!rows(r.blocks).length) stateBox(p,'Подходящих предложений нет. Попробуйте изменить запрос.');
  for(const b of rows(r.blocks)) block(p,b,ctx.forBlock ? {...ctx,...ctx.forBlock(b.type)} : ctx);
  if(rows(r.related_queries).length) {
    add(p,'h2','Похожие запросы');
    for(const q of r.related_queries) action(p,label(q),{q:label(q)});
  }
}
