import {spreadsheet} from './download.js';
import {upload,voice} from './input.js';
import {caption,loadMeta} from './labels.js';
import {address,readAddress} from './address.js';
import {presentation} from './show.js';
import {$,add,line,button,details,rows,num,stateBox,link} from './dom.js';
import {api} from './api.js';
import {state,freshSession} from './state.js';
import {suggestions} from './suggest.js';
import {trace} from './trace.js';
import {result} from './result.js';
import {cart} from './cart.js';
import {record,watch,leave} from './events.js';
import {compare} from './comparison.js';


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
  const workspace=timeline.closest('.workspace'), mobile=matchMedia('(max-width:800px)');
  function collapse(closed){
    workspace.classList.toggle('traceClosed',closed);timeline.hidden=closed;
    if(closed){$('traceWidth').textContent='Развернуть';$('traceWidth').setAttribute('aria-pressed','false');}
    $('traceCollapse').textContent=closed?'Показать':'Скрыть';
    $('traceCollapse').setAttribute('aria-expanded',String(!closed));
    $('traceWidth').hidden=closed;
  }
  function restoreTrace(){collapse(localStorage.getItem('traceClosed-'+mobile.matches)==='true' ||
    (mobile.matches && localStorage.getItem('traceClosed-true')==null));}
  restoreTrace();mobile.addEventListener('change',restoreTrace);
  $('traceCollapse').onclick=()=>{workspace.classList.remove('traceWide');collapse(!timeline.hidden);localStorage.setItem('traceClosed-'+mobile.matches,String(timeline.hidden));};
  $('traceWidth').onclick=e=>{
    const expanded=timeline.closest('.workspace').classList.toggle('traceWide');
    e.currentTarget.setAttribute('aria-pressed',String(expanded));
    e.currentTarget.textContent=expanded ? 'Свернуть' : 'Развернуть';
    if(expanded)$('traceWidth').focus({preventScroll:true});
  };
  const params=()=>({profile_id:profile.value,mode:$('mode').value,category:category.value,session_id:state.session});
  function save(req,kind='',replace=false,profiles=[]) {
    const base=new URL(location.href);
    if(kind==='profiles' && profiles.length)base.searchParams.set('profiles',profiles.join(','));
    else if(kind!=='profiles')base.searchParams.delete('profiles');
    if(!replace){base.searchParams.delete('action');base.searchParams.delete('scenario');}
    const path=address(req,kind,base);
    if(path!==location.pathname+location.search)history[replace?'replaceState':'pushState'](null,'',path);
  }
  window.addEventListener('popstate',()=>location.reload());
  document.addEventListener('keydown',e=>{
    if(e.key==='/' && !e.ctrlKey && !e.metaKey && !e.target.closest('input,textarea,select,dialog,[contenteditable=true]')){
      e.preventDefault();input.focus();input.select();
    }
    if(e.key==='Escape') {
      close();
      if(document.querySelector('.traceWide')) $('traceWidth').click();
    }
  });
  const close=suggestions(input,$('suggestions'),params,q=>run(q,{}, {},{suggest:true}));
  let submittedList='';
  const currentQ=()=>spec.hidden ? submittedList || input.value.trim() : specText.value.trim();
  input.addEventListener('input',()=>{submittedList='';});
  function settings(q) {
    return {...params(),category:category.value || null,q,mode:$('mode').value,source:'ui',explain:true};
  }
  function editor(q) {
    spec.hidden=true;submittedList=q.includes('\n') ? q : '';
    if(submittedList)specText.value=q;
    input.value=q.replace(/\r?\n/g,' · ');
    $('specMode').setAttribute('aria-expanded',String(!spec.hidden));
  }
  async function run(q,patch={},previous={},navigation={}) {
    if(!q.trim())return;
    close();leave();editor(q);
    $('comparison').hidden=true;
    const now=++version;
    const request={...previous,...settings(q),...patch};
    state.request=request;
    main.classList.add('searched');
    if(!navigation.restore && !navigation.file)save(request);
    window.scrollTo(0,0);document.getElementById('pageScroll')?.scrollTo(0,0);
    $('notice').textContent='Идёт поиск…';
    results.replaceChildren();timeline.replaceChildren();
    stateBox(results,'Подбираем предложения…','loading');
    timeline.textContent='Ожидаем ответ движка.';
    results.setAttribute('aria-busy','true');
    try {
      const r=navigation.saved || (navigation.file?await upload(navigation.file,request):await api('/api/search',request));
      if(now!==version)return;
      results.replaceChildren();timeline.replaceChildren();watch(r,request.session_id);
      if(r.profile?.short || r.profile?.segment_title){responseProfiles.set(profile.value,r.profile);profileInfo();}
      if(r.upload){
        const u=r.upload, skipped=rows(u.skipped);
        const caption='Из файла '+u.name+' · позиций '+u.positions+', пропущено '+skipped.length;
        if(skipped.length){const d=details(results,caption);for(const row of skipped)line(d,'Строка '+row.row+' · '+row.reason);}
        else line(results,caption,'banner');
        q=r.query?.raw || q;request.q=q;editor(q);
        request.mode=r.mode || (request.mode==='smart'?'smart':'fast');$('mode').value=request.mode;
        category.value='';request.category=null;
        if(r.search_id && !navigation.restore){const url=new URL(location.href);url.search='';url.searchParams.set('upload',r.search_id);try{history.pushState({fileResult:r},'',url);}catch{history.pushState(null,'',url);}}
      }
      record(r,'impression').catch(err=>line(results,err.message,'error'));
      if(navigation.suggest)record(r,'suggest_click',{},'suggest').catch(err=>line(results,err.message,'error'));
      result(results,r,{categories:state.meta.categories,
        related:q=>{record(r,'reformulate',{},'related').catch(err=>line(results,err.message,'error'));run(q);},
        apply:change=>{
          if(change.q){
            if(change.category && [...category.options].some(o=>o.value===change.category))category.value=change.category;
            return run(change.q,change);
          }
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
      if(r.search_id){
        const target=results.querySelector('[data-type="spec"],[data-type="kit"],[data-type="products"]');
        const row=add(target || results,'div',null,'exportRow');
        if(target)target.querySelector('h2')?.after(row);
        spreadsheet(row,'Скачать КП (XLSX)','/api/export/'+encodeURIComponent(r.search_id)+'?format=xlsx','КП.xlsx');
      }
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
      trace(timeline,r);$('notice').textContent='';
    } catch(err) {
      if(now!==version)return;
      results.replaceChildren();stateBox(results,err.message,'error');button(results,'Повторить поиск',()=>run(q,patch,previous,navigation));
      timeline.textContent='Трасса недоступна.';$('notice').textContent='Ошибка поиска.';
    } finally {if(now===version) results.removeAttribute('aria-busy');}
  }
  voice(input.closest('.bar'),input,q=>run(q),$('notice'));
  const fileInput=$('uploadFile'),bar=input.closest('.bar');
  $('uploadButton').onclick=()=>fileInput.click();
  fileInput.onchange=()=>{const file=fileInput.files[0];if(file)run(file.name,{},{},{file});fileInput.value='';};
  bar.ondragover=e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();bar.classList.add('dropReady');}};
  bar.ondragleave=()=>bar.classList.remove('dropReady');
  bar.ondrop=e=>{e.preventDefault();bar.classList.remove('dropReady');const file=e.dataTransfer.files[0];if(file)run(file.name,{},{},{file});};
  $('search').onsubmit=e=>{e.preventDefault();chain=[];run(submittedList || input.value.trim());};
  $('specMode').onclick=()=>{spec.hidden=!spec.hidden;$('specMode').setAttribute('aria-expanded',String(!spec.hidden));if(!spec.hidden) specText.focus();};
  spec.onsubmit=e=>{e.preventDefault();chain=[];run(specText.value.trim());};
  async function openCompare(kind,restore=false) {
    const q=currentQ();
    if(q && q!==state.request.q)await run(q);
    const request={...(q===state.request.q ? state.request : {}),...settings(q)};
    if(q){main.classList.add('searched');if(!restore)save(request,kind);}
    compare($('comparison'),kind,request,rows(state.meta.profiles),comparisonProfiles,()=>save(request),ids=>{
      comparisonProfiles=ids;save(request,kind,false,ids);
    });
  }
  $('profileCompare').onclick=()=>openCompare('profiles');$('modeCompare').onclick=()=>openCompare('modes');
  const profilesById=new Map(), responseProfiles=new Map();
  async function profileInfo() {
    const id=profile.value, container=$('profileInfo');container.replaceChildren();
    if(id==='guest') {
      const d=details(container,'Гость: без истории, персонализация выключена');
      line(d,'Посетитель без истории покупок. Поиск учитывает запрос и выбранную категорию.');
      return;
    }
    try {
      if(!profilesById.has(id))profilesById.set(id,api('/api/profile/'+encodeURIComponent(id)).catch(err=>{profilesById.delete(id);throw err;}));
      const p=await profilesById.get(id);
      if(profile.value!==id)return;
      const profileMeta={...rows(state.meta.profiles).find(row=>row.id===id),...responseProfiles.get(id)};
      const next=rows(p.owned).filter(o=>Number.isFinite(o.expires_in_days) && o.expires_in_days>=0).sort((a,b)=>a.expires_in_days-b.expires_in_days)[0];
      const d=details(container,[p.short || profileMeta.short || p.title?.split(/ [—–] /)[0],p.segment_title || profileMeta.segment_title || caption('segment',p.segment),
        p.size_seats==null?'':num(p.size_seats)+' рабочих мест',p.industry_title || caption('industry',p.industry),
        next?'истекает через '+num(next.expires_in_days)+' дн. · '+(next.product || next.title || caption('family',next.family_id)):''].filter(Boolean).join(' · '));
      line(d,p.title);
      line(d,[p.segment_title || caption('segment',p.segment),p.size_seats==null?'':num(p.size_seats)+' мест',...rows(p.fleet?.os)].filter(Boolean).join(' · '));
      for(const item of rows(p.owned)) line(d,[item.product || item.title || caption('family',item.family_id),item.qty==null?'':item.qty+' мест',
        item.expires_in_days==null?'':'До окончания '+item.expires_in_days+' дн.'].filter(Boolean).join(' · '));
    }catch(err){if(profile.value===id)line(container,err.message);}
  }
  for(const field of [profile,category,$('mode')]) field.onchange=()=>{
    close();if(field===profile){sessionStorage.kzSession=state.session=freshSession();profileInfo();}
    if(currentQ()) run(currentQ());
  };
  stateBox(results,'Загружаем каталог…','loading');
  const m=await loadMeta();state.meta=m;
  for(const p of rows(m.profiles)) if(p.id!=='guest') profile.add(new Option(p.short || p.title.split(/ [—–] /)[0],p.id));
  for(const c of rows(m.categories)) category.add(new Option(c.title,c.id));
  $('stats').textContent=[m.catalog?.cards==null?'':num(m.catalog.cards)+' карточек',m.catalog?.offers==null?'':num(m.catalog.offers)+' вариантов лицензий'].filter(Boolean).join(' · ');
  const url=new URLSearchParams(location.search), scenario=rows(m.scenarios).find(s=>s.id===url.get('scenario'));
  const demo=scenario?.demo || {}, saved=readAddress(location.search);
  $('mode').value=saved.mode;
  const selected=url.get('profile') || demo.profile;
  if(scenario || url.has('step')) sessionStorage.kzSession=state.session=freshSession();
  if([...profile.options].some(o=>o.value===selected)) profile.value=selected;
  category.value=saved.category || demo.category || '';
  chain=[...rows(demo.chain)];comparisonProfiles=url.has('profiles') ? url.get('profiles').split(',') : rows(demo.compare);
  const example=url.get('q');
  if(example && example===chain[0])chain.shift();else if(example)chain=[];
  const q=example || demo.q || chain.shift() || (scenario && scenario.examples?.[0]);
  profileInfo();
  if(url.get('show')==='1' && url.get('action')==='upload'){
    const sample=await fetch('/web/demo/specification.csv');
    if(!sample.ok)throw Error('Не удалось открыть файл спецификации для показа.');
    const file=new File([await sample.blob()],'Спецификация.csv',{type:'text/csv'});
    await run(file.name,{}, {},{file,restore:true});return;
  }
  if(url.has('upload')){
    const saved=history.state?.fileResult || await api('/api/admin/search/'+encodeURIComponent(url.get('upload')));
    const r=saved.response || saved.result || saved;
    if(r.profile?.id)profile.value=r.profile.id;
    if(r.mode)$('mode').value=r.mode;
    profileInfo();await run(r.query?.raw || 'Спецификация',{}, {},{saved:r,restore:true});return;
  }
  if(q){
    if(url.get('action')==='suggest'){main.classList.add('searched');input.value=q;input.focus();input.dispatchEvent(new Event('input'));results.replaceChildren();return;}
    const kind=saved.compare || (comparisonProfiles.length?'profiles':'');
    save({...settings(q),...saved.criteria},kind,true);
    await run(q,{...saved.criteria,source:scenario?'gallery':'ui'}, {},{restore:true});
    if(kind)openCompare(kind,true);
    return;
  }
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
(location.pathname==='/' ? store() : import('./pages.js').then(({page})=>page(main))).catch(err=>stateBox(main,err.message,'error'));

presentation().catch(err=>line(main,err.message,'error'));
