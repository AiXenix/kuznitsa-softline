import {$,add,line,button,details,rows,num,stateBox,link} from './dom.js';
import {api} from './api.js';
import {state,segments,freshSession} from './state.js';
import {suggestions} from './suggest.js';
import {trace} from './trace.js';
import {result} from './result.js';
import {cart} from './cart.js';
import {watch,leave} from './events.js';
import {compare} from './comparison.js';
import {page} from './pages.js';

const main=$('main');
for (const a of document.querySelectorAll('header nav a')) {
  if (a.pathname===location.pathname) a.setAttribute('aria-current','page');
}
async function store() {
  main.append($('storefront').content.cloneNode(true));
  const input=$('query'), results=$('results'), timeline=$('trace'), profile=$('profile'), category=$('category');
  let version=0, chain=[], comparisonProfiles=[];
  const spec=$('specForm'),specText=$('specText');
  const interactions=cart();
  $('traceWidth').onclick=e=>{
    const expanded=timeline.closest('.workspace').classList.toggle('traceWide');
    e.currentTarget.setAttribute('aria-pressed',String(expanded));
    e.currentTarget.textContent=expanded ? 'Свернуть' : 'Развернуть';
    $('traceTitle').scrollIntoView({block:'start'});
  };
  const params=()=>({profile_id:profile.value,category:category.value,session_id:state.session});
  const close=suggestions(input,$('suggestions'),params,q=>run(q));
  const currentQ=()=>spec.hidden ? input.value.trim() : specText.value.trim();
  function settings(q) {
    return {...params(),category:category.value || null,q,mode:$('mode').value,source:'ui',explain:true};
  }
  function editor(q) {
    if(q.includes('\n')) {spec.hidden=false;specText.value=q;input.value='';}
    else {spec.hidden=true;input.value=q;}
    $('specMode').setAttribute('aria-expanded',String(!spec.hidden));
  }
  async function run(q,patch={},previous={}) {
    if(!q.trim())return;
    close();leave();editor(q);
    $('comparison').hidden=true;
    const now=++version;
    const request={...previous,...settings(q),...patch};
    state.request=request;
    $('notice').textContent='Идёт поиск…';
    results.replaceChildren();timeline.replaceChildren();
    stateBox(results,'Подбираем предложения…','loading');
    timeline.textContent='Ожидаем ответ движка.';
    results.setAttribute('aria-busy','true');
    try {
      const r=await api('/api/search',request);
      if(now!==version)return;
      results.replaceChildren();timeline.replaceChildren();watch(r,request.session_id);
      result(results,r,{
        apply:change=>{
          if(change.q) return run(change.q,change);
          const next={page:1,...change};
          if(change.filters) next.filters={...request.filters,...change.filters};
          if(change.ignore) {
            next.ignore=[...new Set([...(request.ignore || []),...change.ignore])];
            next.filters={...request.filters,...change.filters};
            change.ignore.forEach(k=>delete next.filters[k]);
          }
          run(q,next,request);
        },
        variants:c=>api('/api/card/'+encodeURIComponent(c.card_id)+'?'+new URLSearchParams({profile_id:request.profile_id})),
        forBlock:type=>interactions(r,type,request.session_id)
      });
      const products=rows(r.blocks).find(b=>b.type==='products');
      const size=request.page_size || 20, page=request.page || 1;
      if(page>1 || products?.total>page*size) {
        const pages=add(results,'nav');pages.setAttribute('aria-label','Страницы выдачи');
        if(page>1)button(pages,'← Предыдущая',()=>run(q,{page:page-1},request));
        if(products?.total>page*size)button(pages,'Следующая →',()=>run(q,{page:page+1},request));
      }
      if(chain.length) button(results,'Следующий запрос · '+chain[0],()=>run(chain.shift(),{source:'gallery'}));
      const jump=link(results,'Как работал поиск ↓','#traceTitle');
      jump.className='traceJump';results.prepend(jump);
      trace(timeline,r);$('notice').textContent='Поиск завершён.';
    } catch(err) {
      if(now!==version)return;
      results.replaceChildren();stateBox(results,err.message,'error');button(results,'Повторить поиск',()=>run(q,patch,previous));
      timeline.textContent='Трасса недоступна.';$('notice').textContent='Ошибка поиска.';
    } finally {if(now===version) results.removeAttribute('aria-busy');}
  }
  $('search').onsubmit=e=>{e.preventDefault();chain=[];run(input.value.trim());};
  $('specMode').onclick=()=>{spec.hidden=!spec.hidden;$('specMode').setAttribute('aria-expanded',String(!spec.hidden));if(!spec.hidden) specText.focus();};
  spec.onsubmit=e=>{e.preventDefault();chain=[];run(specText.value.trim());};
  function openCompare(kind) {
    const q=currentQ();
    compare($('comparison'),kind,{...(q===state.request.q ? state.request : {}),...settings(q)},rows(state.meta.profiles),comparisonProfiles);
  }
  $('profileCompare').onclick=()=>openCompare('profiles');$('modeCompare').onclick=()=>openCompare('modes');
  async function profileInfo() {
    const id=profile.value, container=$('profileInfo');container.replaceChildren();
    if(id==='guest') {
      const d=details(container,'Кто это · Гость');
      line(d,'Посетитель без истории покупок. Поиск учитывает запрос и выбранную категорию.');
      return;
    }
    try {
      const p=await api('/api/profile/'+encodeURIComponent(id));
      if(profile.value!==id)return;
      const d=details(container,'Кто это · '+p.title);
      line(d,[segments[p.segment] || p.segment,p.size_seats==null?'':num(p.size_seats)+' мест',...rows(p.fleet?.os)].filter(Boolean).join(' · '));
      for(const item of rows(p.owned)) line(d,[item.product || item.title || item.family_id,item.qty==null?'':item.qty+' мест',
        item.expires_in_days==null?'':'До окончания '+item.expires_in_days+' дн.'].filter(Boolean).join(' · '));
    }catch(err){if(profile.value===id)line(container,err.message);}
  }
  for(const field of [profile,category,$('mode')]) field.onchange=()=>{
    close();if(field===profile){sessionStorage.kzSession=state.session=freshSession();profileInfo();}
    if(currentQ()) run(currentQ());
  };
  stateBox(results,'Загружаем каталог…','loading');
  const m=await api('/api/meta');state.meta=m;
  for(const p of rows(m.profiles)) if(p.id!=='guest') profile.add(new Option(p.title,p.id));
  for(const c of rows(m.categories)) category.add(new Option(c.title,c.id));
  $('stats').textContent=[m.catalog?.cards==null?'':num(m.catalog.cards)+' карточек',m.catalog?.offers==null?'':num(m.catalog.offers)+' вариантов лицензий'].filter(Boolean).join(' · ');
  const url=new URLSearchParams(location.search), scenario=rows(m.scenarios).find(s=>s.id===url.get('scenario'));
  const demo=scenario?.demo || {};
  if(scenario) sessionStorage.kzSession=state.session=freshSession();
  if([...profile.options].some(o=>o.value===demo.profile)) profile.value=demo.profile;
  if(demo.category) category.value=demo.category;
  chain=[...rows(demo.chain)];comparisonProfiles=rows(demo.compare);
  const example=url.get('q');
  if(example) chain=[];
  const q=example || demo.q || chain.shift() || (scenario && scenario.examples?.[0]);
  profileInfo();
  if(q){await run(q,{source:scenario?'gallery':'ui'});if(comparisonProfiles.length)openCompare('profiles');return;}
  if(version)return;
  results.replaceChildren();
  add(results,'h2','Что вы подбираете?');
  const examples=add(results,'div',null,'exampleGrid');
  const groups=new Set();
  for(const s of rows(m.scenarios)) {
    if(groups.has(s.group) || !s.demo?.q)continue;
    groups.add(s.group);
    const a=link(examples,s.demo.q,'/?scenario='+encodeURIComponent(s.id));line(a,s.group_title,'muted','small');
    if(groups.size===6)break;
  }
  link(results,'Все сценарии поиска →','/scenarios');
}
(location.pathname==='/' ? store() : page(main)).catch(err=>stateBox(main,err.message,'error'));
