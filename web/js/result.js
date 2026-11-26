import {readable,caption} from './labels.js';
import {add,line,button,details,rows,label,counted,stateBox} from './dom.js';
import {block} from './blocks.js';

export function result(p,r,ctx={}) {
  ctx={profile:r.profile?.id,mode:r.mode,...ctx,weights:rows(r.trace).find(s=>s.detail?.weights)?.detail.weights || ctx.weights};
  const u=r.understood || {};
  function action(parent,title,patch) {
    if (ctx.apply) return button(parent,title,()=>ctx.apply(patch),'chip');
    return line(parent,title,'chip','span');
  }
  if (Object.keys(u).length) {
    const panel=add(ctx.understanding || p,'section',null,'understood');
    add(panel,'h2','Понято так');
    line(panel,u.intent_title,'intent');
    const chips=add(panel,'div',null,'chips');
    const refined=u.refined;
    const audiences={home:'для дома',micro_office:'для малого офиса',business:'для организации',enterprise:'для крупного предприятия',gov:'для госучреждения',edu:'для образования',server:'для серверов',mobile:'для мобильных устройств',industrial:'для промышленности'};
    const audience=audiences[refined?.audience];
    const family=refined?.line && refined.line!=='none' ? caption('family',refined.line) : '';
    if(audience || family){
      const title='Понято: '+[audience,family].filter(Boolean).join(' · ');
      const chip=action(chips,title+(ctx.apply?' ×':''),{ignore:['refined']});
      if(refined.source==='dict' || refined.source==='jev')chip.title=refined.source==='dict'?'по словарю':'уточнено умным режимом';
    }
    for(const c of rows(u.chips)) {
      if((audience || family) && (c.key==='refined' || (audience && c.key==='audience')))continue;
      const title=c.key==='profile' ? 'Профиль · '+(r.profile?.short || r.profile?.title || c.label || '').split(/ [—–] /)[0] : readable(c.label);
      if(c.removable && c.key) action(chips,title+' ×',{ignore:[c.key]});
      else line(chips,title,'badge','span');
      if(c.key==='profile' && chips.lastChild)chips.lastChild.title=r.profile?.title || c.label;
    }
    for(const e of rows(u.entities).filter(e=>e.type==='okved')){
      if(!rows(u.chips).some(c=>c.label?.includes(e.id)))line(chips,['ОКВЭД '+e.id,e.title || e.name].filter(Boolean).join(' · '),'badge','span');
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
  const domainHint=u.domain_hint || r.domain_hint || rows(u.chips).find(c=>c.label?.startsWith('Искали ПО'));
  if(domainHint){
    const title=typeof domainHint==='string'?domainHint:domainHint.label || domainHint.text;
    action(p,title || 'Искали ПО для сервера?',domainHint.apply || {q:domainHint.q || 'ПО для сервера'});
  }
  for(const b of rows(r.banners)) line(p,b.text,'banner');
  for(const n of rows(r.notes)) line(ctx.understanding || p,label(n),'hint');
  const facets=rows(r.facets).filter(f=>rows(f.values).length);
  if(facets.length && ctx.apply) {
    const d=details(p,'Уточнить выдачу');
    for(const f of facets) {
      line(d,f.title,null,'h3');
      for(const v of rows(f.values)) action(d,counted(v.label,v.count),{filters:{[f.key]:v.id}});
    }
  }
  const reason=u.zero_reason, raw=r.query?.raw || '';
  const messages={off_topic:'Мы помогаем подобрать программы и ИТ-услуги. Выберите раздел каталога.',
    unknown_term:'Не узнали '+(raw?'«'+raw+'»':'термин')+'. Попробуйте название программы или уточните запрос.',
    not_in_catalog:'Этого продукта нет в каталоге.',vendor_left:'Поставки вендора ограничены.',
    filters_too_strict:'Все предложения отсечены условиями. Снимите одно из ограничений.',
    qty_out_of_range:'Для такого количества нет ступени лицензирования.',no_available_offer:'Подходящее предложение сейчас недоступно к заказу.'};
  let blocks=rows(r.blocks);
  // The unavailable offer is already explained by the analogs block.
  const replacement=blocks.find(b=>b.type==='analogs' && b.source?.status==='unavailable' && b.source.note);
  if(replacement){
    const faq=blocks.find(b=>b.type==='answer' && b.source?.startsWith?.('faq:') && rows(b.links).some(l=>l.q));
    ctx={...ctx,replacementFAQ:rows(faq?.links).filter(l=>l.q)};
    blocks=blocks.filter(b=>!(b.type==='not_in_catalog' && b.text===replacement.source.note));
  }
  const explained=replacement && ['not_in_catalog','no_available_offer'].includes(reason);
  if(Object.hasOwn(messages,reason) && !explained){
    const note=add(p,'section',null,'zeroReason');add(note,'h2',messages[reason]);
    if(reason==='not_in_catalog' && blocks.some(b=>b.type==='analogs' && rows(b.items).length))line(note,'Мы нашли варианты замены.');
    if(reason==='off_topic' && !blocks.some(b=>b.type==='categories'))
      for(const c of rows(ctx.categories).slice(0,6))action(note,c.title,{q:c.title,category:c.id});
    if(reason==='qty_out_of_range'){
      const steps=new Map(),qty=u.qty?.value;
      for(const b of blocks)for(const i of rows(b.items)){
        const c=i.card || i;
        for(const o of [c.offer,...rows(c.variants)].filter(Boolean)){
          const min=o.pack ?? o.qty_min,max=o.pack ?? o.qty_max;
          if(min==null && max==null)continue;
          const range=min==null?'до '+max:max==null?'от '+min:min===max?String(min):min+'–'+max;
          const distance=qty==null?0:Math.max(0,(min ?? qty)-qty,qty-(max ?? qty));
          steps.set(range,distance);
        }
      }
      const nearest=[...steps].sort((a,b)=>a[1]-b[1]).slice(0,3);
      if(nearest.length)line(note,'Ближайшие ступени · '+nearest.map(([range])=>range).join(', '));
    }
    if(reason==='vendor_left' || reason==='not_in_catalog')blocks=[...blocks.filter(b=>b.type==='analogs'),...blocks.filter(b=>b.type!=='analogs')];
    const lead=['unknown_term','not_in_catalog','qty_out_of_range','no_available_offer'].includes(reason);
    if(lead && !blocks.some(b=>b.type==='lead'))blocks=[...blocks,{type:'lead',action:'request_quote'}];
    if(lead)blocks=[...blocks.filter(b=>b.type!=='lead'),...blocks.filter(b=>b.type==='lead').map(b=>({...b,button:reason==='not_in_catalog'?'Сообщить о появлении':'Запросить счёт'}))];
  }else if(!blocks.length)stateBox(p,'Подходящих предложений нет. Попробуйте изменить запрос.');
  for(const h of rows(r.relax_hints))action(p,counted(readable(h.label),h.count),{ignore:[h.drop],...h.apply});
  for(const b of blocks){
    const inline=b.type==='my_licenses' && blocks.some(other=>other.type==='products');
    const container=inline ? details(p,counted(b.title || 'Ваши лицензии',rows(b.items).length)) : p;
    block(container,b,ctx.forBlock ? {...ctx,...ctx.forBlock(b.type)} : ctx);
  }
  if(rows(r.related_queries).length) {
    add(p,'h2','Похожие запросы');
    for(const q of r.related_queries) {if(ctx.related)button(p,label(q),()=>ctx.related(label(q)),'chip');else action(p,label(q),{q:label(q)});}
  }
}
