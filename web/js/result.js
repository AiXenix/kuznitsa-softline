import {add,line,button,details,rows,label,counted,stateBox} from './dom.js';
import {block} from './blocks.js';

export function result(p,r,ctx={}) {
  ctx={...ctx,weights:rows(r.trace).find(s=>s.detail?.weights)?.detail.weights || ctx.weights};
  const u=r.understood || {};
  function action(parent,title,patch) {
    if (ctx.apply) button(parent,title,()=>ctx.apply(patch),'chip');
    else line(parent,title,'chip','span');
  }
  if (Object.keys(u).length) {
    const panel=add(p,'section',null,'understood');
    add(panel,'h2','Понято так');
    line(panel,u.intent_title,'intent');
    const chips=add(panel,'div',null,'chips');
    for(const c of rows(u.chips)) {
      const title=c.key==='profile' ? 'Профиль · '+(r.profile?.title || c.label).split(/ [—–] /)[0] : c.label;
      if(c.removable && c.key) action(chips,title+' ×',{ignore:[c.key]});
      else line(chips,title,'badge','span');
      if(c.key==='profile' && chips.lastChild)chips.lastChild.title=r.profile?.title || c.label;
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
  for(const b of rows(r.blocks)){
    const inline=b.type==='my_licenses' && r.blocks.some(other=>other.type==='products');
    const container=inline ? details(p,counted(b.title || 'Ваши лицензии',rows(b.items).length)) : p;
    block(container,b,ctx.forBlock ? {...ctx,...ctx.forBlock(b.type)} : ctx);
  }
  if(rows(r.related_queries).length) {
    add(p,'h2','Похожие запросы');
    for(const q of r.related_queries) {if(ctx.related)button(p,label(q),()=>ctx.related(label(q)),'chip');else action(p,label(q),{q:label(q)});}
  }
}
