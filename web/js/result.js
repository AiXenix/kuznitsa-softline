import {readable,caption} from './labels.js';
import {add,line,button,details,rows,label,counted,stateBox,money} from './dom.js';
import {block} from './blocks.js';
import {renderFacets} from './facets.js';

const AUDIENCES={home:'для дома',micro_office:'для малого офиса',business:'для организации',enterprise:'для крупного предприятия',gov:'для госучреждения',edu:'для образования',server:'для серверов',mobile:'для мобильных устройств',industrial:'для промышленности'};

function filterLabel(key,val){
  if(key==='price_max' && Number.isFinite(Number(val)))return 'До '+money(Number(val));
  if(key==='price_min' && Number.isFinite(Number(val)))return 'От '+money(Number(val));
  if(key==='registry')return val?'Реестр отечественного ПО':'Не из реестра';
  const list=Array.isArray(val)?val:[val];
  return list.map(v=>caption(key,v,String(v))).join(', ');
}

export function result(p,r,ctx={}) {
  ctx={profile:r.profile?.id,mode:r.mode,...ctx,weights:rows(r.trace).find(s=>s.detail?.weights)?.detail.weights || ctx.weights};
  const u=r.understood || {};
  function action(parent,title,patch) {
    if (ctx.apply) return button(parent,title,()=>ctx.apply(patch),'chip');
    return line(parent,title,'chip','span');
  }

  const domainHint=u.domain_hint || r.domain_hint || rows(u.chips).find(c=>c.label?.startsWith('Искали ПО'));
  const refined=u.refined;
  const audience=AUDIENCES[refined?.audience];
  const family=refined?.line && refined.line!=='none' ? caption('family',refined.line) : '';

  // Build facets into a fragment so we know which active filter keys are already shown there.
  const facetFragment=document.createDocumentFragment();
  const facetResult=renderFacets(facetFragment,r.facets,ctx);
  const shownFilterKeys=facetResult?.shownFilterKeys || new Set();

  // Classify understood chips into removable (for page strip) vs service (for panel).
  const removableChips=[];
  const serviceChips=[];
  for(const c of rows(u.chips)) {
    if((audience || family) && (c.key==='refined' || (audience && c.key==='audience')))continue;
    if(c===domainHint)continue;
    const title=c.key==='profile' ? 'Профиль · '+(r.profile?.short || r.profile?.title || c.label || '').split(/ [—–] /)[0] : readable(c.label);
    if(c.removable && c.key){
      if(!shownFilterKeys.has(c.key))removableChips.push({key:c.key,title});
    }else{
      serviceChips.push({key:c.key,title,raw:c.label});
    }
  }
  // If facets are empty but active filters exist in the request, keep them removable on the page.
  if(!facetResult && ctx.filters){
    for(const [k,v] of Object.entries(ctx.filters)){
      if(v==null || v==='' || (Array.isArray(v) && !v.length))continue;
      if(removableChips.some(c=>c.key===k))continue;
      removableChips.push({key:k,title:filterLabel(k,v)});
    }
  }
  const okvedEntities=rows(u.entities).filter(e=>e.type==='okved' && !rows(u.chips).some(c=>c.label?.includes(e.id)));
  const hasCorrection=Boolean(r.query?.corrected && rows(r.query.corrections).length);
  const hasDidYouMean=typeof r.query?.did_you_mean==='string' && r.query.did_you_mean.length>0;
  const hasInherited=Boolean(u.inherited?.from_q);

  const understoodFragment=document.createDocumentFragment();
  if(ctx.understanding){
    // Slide-out panel: service badges, intent title, OKVED, and notes only (no duplication with page strip).
    if(Object.keys(u).length){
      const panel=add(ctx.understanding,'section',null,'understood');
      add(panel,'h2','Понято так');
      line(panel,u.intent_title,'intent');
      const chips=add(panel,'div',null,'chips');
      for(const c of serviceChips){
        line(chips,c.title,'badge','span');
        if(c.key==='profile' && chips.lastChild)chips.lastChild.title=r.profile?.title || c.raw;
      }
      for(const e of okvedEntities){
        line(chips,['ОКВЭД '+e.id,e.title || e.name].filter(Boolean).join(' · '),'badge','span');
      }
    }
    for(const n of rows(r.notes)) line(ctx.understanding,label(n),'hint');

    // Compact page-level strip for corrections, did-you-mean, inherited context, removable conditions, and domain hint.
    if(hasCorrection || hasDidYouMean || hasInherited || audience || family || removableChips.length || domainHint){
      const bar=add(understoodFragment,'div',null,'understoodBar');
      if(hasCorrection){
        add(bar,'span','Показаны результаты по «'+r.query.corrected+'»','understoodText');
        action(bar,'Искать как было',{verbatim:true});
      }
      if(hasDidYouMean){
        action(bar,'Возможно, вы искали «'+r.query.did_you_mean+'»',{q:r.query.did_you_mean});
      }
      if(hasInherited){
        add(bar,'span','В контексте запроса «'+(u.inherited.from_q || '')+'»','understoodText');
        action(bar,'Начать заново',{context:'off'});
      }
      if(audience || family){
        const title='Понято: '+[audience,family].filter(Boolean).join(' · ');
        const chip=action(bar,title+(ctx.apply?' ×':''),{ignore:['refined']});
        if(refined.source==='dict' || refined.source==='jev')chip.title=refined.source==='dict'?'по словарю':'уточнено умным режимом';
      }
      for(const c of removableChips){
        action(bar,c.title+(ctx.apply?' ×':''),{ignore:[c.key]});
      }
      if(domainHint){
        const title=typeof domainHint==='string'?domainHint:domainHint.label || domainHint.text;
        action(bar,title || 'Искали ПО для сервера?',domainHint.apply || {q:domainHint.q || 'ПО для сервера'});
      }
    }
  }else{
    // Standalone renderer (styleguide, inspect, embed, unit tests): keep .understood section directly in p.
    if(Object.keys(u).length){
      const panel=add(p,'section',null,'understood');
      add(panel,'h2','Понято так');
      line(panel,u.intent_title,'intent');
      const chips=add(panel,'div',null,'chips');
      if(audience || family){
        const title='Понято: '+[audience,family].filter(Boolean).join(' · ');
        const chip=action(chips,title+(ctx.apply?' ×':''),{ignore:['refined']});
        if(refined.source==='dict' || refined.source==='jev')chip.title=refined.source==='dict'?'по словарю':'уточнено умным режимом';
      }
      for(const c of removableChips){
        action(chips,c.title+(ctx.apply?' ×':''),{ignore:[c.key]});
      }
      for(const c of serviceChips){
        line(chips,c.title,'badge','span');
        if(c.key==='profile' && chips.lastChild)chips.lastChild.title=r.profile?.title || c.raw;
      }
      for(const e of okvedEntities){
        line(chips,['ОКВЭД '+e.id,e.title || e.name].filter(Boolean).join(' · '),'badge','span');
      }
      if(hasCorrection){
        line(panel,'Показаны результаты по «'+r.query.corrected+'»');
        action(panel,'Искать как было',{verbatim:true});
      }
      if(hasDidYouMean){
        action(panel,'Возможно, вы искали «'+r.query.did_you_mean+'»',{q:r.query.did_you_mean});
      }
      if(hasInherited){
        line(panel,'В контексте запроса «'+(u.inherited.from_q || '')+'»');
        action(panel,'Начать заново',{context:'off'});
      }
    }
    if(domainHint){
      const title=typeof domainHint==='string'?domainHint:domainHint.label || domainHint.text;
      action(p,title || 'Искали ПО для сервера?',domainHint.apply || {q:domainHint.q || 'ПО для сервера'});
    }
    for(const n of rows(r.notes)) line(p,label(n),'hint');
  }

  for(const b of rows(r.banners)) line(p,b.text,'banner');

  const reason=u.zero_reason, raw=r.query?.raw || '';
  const messages={off_topic:'Мы помогаем подобрать программы и ИТ-услуги. Выберите раздел каталога.',
    unknown_term:'Не узнали '+(raw?'«'+raw+'»':'термин')+'. Попробуйте название программы или уточните запрос.',
    not_in_catalog:raw?'В каталоге нет «'+raw+'»':'Этого продукта нет в каталоге',
    vendor_left:'Поставки вендора ограничены.',
    filters_too_strict:'Все предложения отсечены условиями. Снимите одно из ограничений.',
    qty_out_of_range:'Для такого количества нет ступени лицензирования.',
    no_available_offer:'Подходящее предложение сейчас недоступно к заказу.'};
  let blocks=rows(r.blocks);
  // The unavailable offer is already explained by the analogs block.
  const replacement=blocks.find(b=>b.type==='analogs' && b.source?.status==='unavailable' && b.source.note);
  if(replacement){
    const faq=blocks.find(b=>b.type==='answer' && b.source?.startsWith?.('faq:') && rows(b.links).some(l=>l.q));
    ctx={...ctx,replacementFAQ:rows(faq?.links).filter(l=>l.q)};
    blocks=blocks.filter(b=>!(b.type==='not_in_catalog' && b.text===replacement.source.note));
  }
  const explained=replacement && ['not_in_catalog','no_available_offer'].includes(reason);
  let zeroReasonShown=false;
  if(Object.hasOwn(messages,reason) && !explained){
    zeroReasonShown=true;
    const missingBlock=reason==='not_in_catalog'?blocks.find(b=>b.type==='not_in_catalog'):null;
    if(reason==='not_in_catalog')blocks=blocks.filter(b=>b.type!=='not_in_catalog');
    const note=add(p,'section',null,'zeroReason');add(note,'h2',messages[reason]);
    if(reason==='not_in_catalog'){
      const hasAnalogs=blocks.some(b=>b.type==='analogs' && rows(b.items).length);
      let explanation=(u.agent_note || missingBlock?.text || (hasAnalogs?'Мы нашли варианты замены.':'')).trim();
      const head=messages[reason].trim();
      if(explanation.toLowerCase().startsWith(head.toLowerCase())){
        explanation=explanation.slice(head.length).replace(/^[.!?:—–\-\s]+/,'').trim();
      }
      if(explanation)line(note,explanation);
    }
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

  const hasSpecial=blocks.some(b=>['compare','spec'].includes(b.type));
  const primaryBlock=!hasSpecial ? blocks.find(b=>['products','analogs'].includes(b.type) && rows(b.items).length>0) : null;
  let understoodMounted=false, facetsMounted=false;

  if(!primaryBlock || (zeroReasonShown && primaryBlock.type!=='analogs')){
    if(understoodFragment.childNodes.length){p.append(understoodFragment);understoodMounted=true;}
    if(!primaryBlock && facetFragment.childNodes.length){p.append(facetFragment);facetsMounted=true;}
  }

  for(const h of rows(r.relax_hints))action(p,counted(readable(h.label),h.count),{ignore:[h.drop],...h.apply});
  for(const b of blocks){
    const inline=b.type==='my_licenses' && blocks.some(other=>other.type==='products');
    const container=inline ? details(p,counted(b.title || 'Ваши лицензии',rows(b.items).length)) : p;
    const isPrimary=b===primaryBlock;
    const blockCtx={
      ...(ctx.forBlock ? {...ctx,...ctx.forBlock(b.type)} : ctx),
      sortable:isPrimary && Boolean(ctx.apply),
      afterHead:isPrimary ? section=>{
        if(!understoodMounted && understoodFragment.childNodes.length){section.append(understoodFragment);understoodMounted=true;}
        if(!facetsMounted && facetFragment.childNodes.length){section.append(facetFragment);facetsMounted=true;}
      } : null
    };
    block(container,b,blockCtx);
  }
  if(!understoodMounted && understoodFragment.childNodes.length)p.prepend(understoodFragment);
  if(!facetsMounted && facetFragment.childNodes.length)p.prepend(facetFragment);

  if(rows(r.related_queries).length) {
    add(p,'h2','Похожие запросы');
    for(const q of r.related_queries) {if(ctx.related)button(p,label(q),()=>ctx.related(label(q)),'chip');else action(p,label(q),{q:label(q)});}
  }
}
