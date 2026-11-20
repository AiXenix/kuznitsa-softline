const byId = id => document.getElementById(id);
const query = byId('query'), results = byId('results'), suggestions = byId('suggestions');
const session = sessionStorage.kzSession || (sessionStorage.kzSession = crypto.randomUUID());
const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
};
const add = (parent, tag, text, cls) => parent.appendChild(el(tag,text,cls));
const button = (parent, label, fn) => {
  const b = add(parent,'button',label,'action');
  b.type = 'button';
  b.onclick = fn;
};
async function api(path, body) {
  const response = await fetch(path, body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {});
  if (!response.ok) throw Error((await response.json()).error?.message || 'Ошибка загрузки');
  return response.status === 204 ? null : response.json();
}
let searchNumber=0, suggestNumber=0, timer;
function hideSuggestions(){++suggestNumber;suggestions.hidden=true;}
function launch(q){query.value=q; run();}
function event(r,type,c) {
  return api('/api/event',{search_id:r.search_id,session_id:session,client_id:r.profile.id,type,
    card_id:c?.card_id,offer_id:c?.offer.offer_id,position:c?.position,qty:c?.calc?.qty,value:c?.calc?.total})
    .catch(e=>add(results,'p',e.message));
}
function card(parent,c,r){
  const box=add(parent,'article');
  add(box,'small',[c.vendor.name,c.category.title].filter(Boolean).join('  /  '));
  add(box,'h3',c.title);
  if(c.summary)add(box,'p',c.summary,'muted');
  const chips=add(box,'div',null,'chips');
  c.badges.forEach(b=>add(chips,'span',b.label,'chip'));
  add(box,'p',c.offer.name);
  add(box,'p',c.calc?.text || 'Цена по запросу','cost');
  const why=add(box,'details');
  add(why,'summary','Почему здесь');
  why.ontoggle=()=>{if(why.open)event(r,'click',c);};
  c.score.why.forEach(w=>add(why,'p',w));
  const labels={rel:'Релевантность',pop:'Популярность',margin:'Маржа',pers:'Профиль'};
  add(why,'small',Object.entries(c.score.parts).map(([k,v])=>labels[k]+' '+v.toFixed(2)).join(' · '));
  const variants=add(box,'details');
  add(variants,'summary','Варианты лицензии · '+c.variants_count);
  c.variants.forEach(o=>add(variants,'p',o.name));
  if(c.offer.available) button(box,c.calc?'В корзину':'Запросить цену',async e=>{
    await event(r,c.calc?'cart':'lead',c);
    e.target.disabled=true;e.target.textContent=c.calc?'Добавлено':'Запрос принят';
    if(c.calc)button(box,'Оформить демозаказ',async ev=>{await event(r,'order',c);ev.target.disabled=true;ev.target.textContent='Заказ оформлен';});
  });
}
async function run(){
  hideSuggestions();const n=++searchNumber;if(!query.value.trim())return;
  results.setAttribute('aria-busy','true');
  try{
    const r=await api('/api/search',{q:query.value,profile_id:byId('profile').value,mode:byId('mode').value,category:byId('category').value||null,session_id:session,source:'ui'});
    if(n!==searchNumber)return;
    results.replaceChildren();const u=add(results,'section',null,'panel');
    add(u,'h2','Понято так');add(u,'p',r.understood.intent_title);
    if(r.query.corrections.length)add(u,'p','Исправлено · '+r.query.corrected);
    const chips=add(u,'div',null,'chips');
    for(const c of r.understood.chips){
      if(c.removable)button(chips,c.label+' ×',()=>launch(c.remove_q));
      else add(chips,'span',c.label,'chip');
    }
    r.notes.forEach(text=>add(results,'p',text,'muted'));
    for(const b of r.blocks){
      add(results,'h2',b.title);
      if(b.text||b.question)add(results,'p',b.text||b.question);
      b.options?.forEach(o=>button(results,o.label,()=>launch(o.apply.q)));
      if(b.type==='categories')b.items.forEach(item=>button(results,item.title,()=>launch(item.title)));
      if(b.type==='my_licenses')for(const item of b.items)add(results,'p',item.title+' · '+item.qty+' мест'+(item.expires_in_days!=null?' · до окончания '+item.expires_in_days+' дн.':''));
      if(b.type==='products'||b.type==='analogs')b.items.forEach(i=>card(results,i.card||i,r));
      if(b.type==='lead')button(results,'Оставить запрос',async e=>{await event(r,'lead');e.target.disabled=true;e.target.textContent='Запрос принят';});
    }
    const facet=r.facets.find(f=>f.key==='vendor'&&f.values.length>1);
    if(facet){
      const group=add(results,'details');
      add(group,'summary','Уточнить вендора');
      for(const v of facet.values)button(group,v.label+' · '+v.count,()=>launch(r.query.corrected+' '+v.label));
    }
    if(r.related_queries.length)add(results,'h3','Связанные запросы');
    r.related_queries.forEach(q=>button(results,q,()=>launch(q)));
    const trace=byId('trace');trace.replaceChildren();
    add(trace,'p',r.timing_ms.total+' мс · '+r.cost.rub+' ₽','muted');
    for(const step of r.trace){
      const d=add(trace,'details');add(d,'summary',step.title);add(d,'p',step.summary);add(d,'small',step.ms+' мс');
    }
  }catch(e){if(n===searchNumber)results.textContent=e.message;}
  finally{if(n===searchNumber)results.removeAttribute('aria-busy');}
}
query.oninput=()=>{
  clearTimeout(timer);hideSuggestions();const seq=suggestNumber;
  if(!query.value.trim())return;
  timer=setTimeout(async()=>{
    try{
      const r=await api('/api/suggest?'+new URLSearchParams({q:query.value,profile_id:byId('profile').value}));
      if(seq!==suggestNumber)return;
      suggestions.replaceChildren();
      for(const g of r.groups){add(suggestions,'small',g.title);g.items.forEach(i=>button(suggestions,i.text,()=>launch(i.text)));}
      suggestions.hidden=!r.groups.length;
    }catch{hideSuggestions();}
  },160);
};
query.onkeydown=e=>{if(e.key==='Escape')hideSuggestions();};
document.addEventListener('click',e=>{if(!e.target.closest('.bar'))hideSuggestions();});
byId('search').onsubmit=e=>{e.preventDefault();run();};
for(const key of ['category','mode'])byId(key).onchange=()=>{if(query.value)run();};
async function showProfile(){
  const profile=byId('profile').value;
  const p=await api('/api/profile/'+encodeURIComponent(profile));
  if(byId('profile').value!==profile)return;
  const info=byId('profileInfo');info.replaceChildren();
  if(profile==='guest')return;
  const detail=add(info,'details');
  add(detail,'summary','Парк и лицензии клиента');
  add(detail,'p',(p.fleet.os||[]).join(', ')+' · '+p.size_seats+' мест');
  for(const o of p.owned)add(detail,'p',(o.product||o.family_id||'Лицензия')+' · '+o.qty+' мест'+(o.expires_in_days==null?'':' · до окончания '+o.expires_in_days+' дн.'));
}
byId('profile').onchange=()=>{showProfile().catch(e=>{byId('profileInfo').textContent=e.message;});if(query.value)run();};
api('/api/meta').then(m=>{
  for(const [id,rows] of [['profile',m.profiles],['category',m.categories]])for(const r of rows)byId(id).add(new Option(r.title,r.id));
  byId('stats').textContent=m.catalog.cards.toLocaleString('ru')+' карточек · '+m.catalog.offers.toLocaleString('ru')+' предложений';
  add(results,'h2','Попробуйте запрос');
  const examples=m.scenarios.filter(s=>s.examples?.length).slice(0,4);
  for(const s of examples)button(results,s.examples[0],()=>launch(s.examples[0]));
}).catch(e=>{results.textContent=e.message;});
