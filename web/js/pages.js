import {loadMeta} from './labels.js';
import {consolePage} from './admin/index.js';
import {inspector} from './admin/inspect.js';
import {about} from './about.js';
import {address} from './address.js';
import {mini,card} from './product.js';
import {api} from './api.js';
import {add,line,rows,label,details,link,num,stateBox} from './dom.js';
import {result} from './result.js';
import {trace} from './trace.js';

function heading(main,title) {
  document.title=title+' · Кузница Softline';
  add(main,'h1',title);
}
async function gallery(main) {
  heading(main,'Галерея сценариев');
  const form=add(main,'div',null,'settings panel');
  const input=add(add(form,'label','Поиск по галерее'),'input');input.type='search';input.placeholder='Название или пример запроса';
  const select=add(add(form,'label','Группа'),'select');select.add(new Option('Все группы',''));
  const status=add(main,'p',null,'muted');status.setAttribute('role','status');
  const container=add(main,'div');
  const meta=await loadMeta(), all=rows(meta.scenarios);
  const checks=new Map();
  const groups=new Map(all.map(s=>[s.group || '',s.group_title || 'Другие сценарии']));
  for(const [id,title] of groups) if(id) select.add(new Option(title,id));
  function show() {
    container.replaceChildren();const found=all.filter(s=>(!select.value || s.group===select.value) &&
      [s.title,s.group_title,s.demo?.q,...rows(s.examples)].join(' ').toLowerCase().includes(input.value.trim().toLowerCase()));
    status.textContent='Сценариев в подборке · '+num(found.length);
    if(!found.length)stateBox(container,'По вашему запросу сценариев нет.');
    for(const [id,title] of groups) {
      const matches=found.filter(s=>(s.group || '')===id);
      if(!matches.length)continue;
      add(container,'h2',title);const grid=add(container,'div',null,'gallery');
      for(const s of matches) {
        const box=add(grid,'article',null,'product');
        add(box,'h3',s.title);line(box,s.user_goal,'muted');
        const examples=rows(s.examples),base='/?scenario='+encodeURIComponent(s.id);
        const first=s.demo?.q || s.demo?.chain?.[0] || examples[0];
        const launch=q=>address({q,profile_id:s.demo?.profile || 'guest',mode:'smart',category:s.demo?.category},s.demo?.compare?'profiles':'',base);
        if(first){line(box,first);link(box,'Запустить →',launch(first)).className='launch';}
        if(examples.some(q=>q!==first)){
          const d=details(box,'Другие примеры');
          for(const q of examples.filter(q=>q!==first)) link(d,q,launch(q));
        }
        if(s.demo?.admin_tab) link(box,'К аналитике','/admin');
        const st=s.eval_status ?? checks.get(s.id) ?? s.status;
        if(st)line(box,'Проверка · '+label(st),'muted');
      }
    }
  }
  input.oninput=select.onchange=show;show();
  try {
    const report=await api('/api/admin/eval');
    for (const row of rows(report?.rows || report?.results || report)) {
      if (row.scenario && row.status) checks.set(row.scenario,row.status);
    }
    for(const [id,v] of Object.entries(report.scenarios || {}))if(v.total)checks.set(id,v.passed+' / '+v.total);
    if(checks.size) show();
  } catch { /* Метаданные галереи доступны независимо от журнала проверок. */ }
}
async function styleguide(main) {
  heading(main,'Образцы интерфейса');
  line(main,'Примеры ответов из локальных файлов. Покупки и запросы в журнал не записываются.');
  const files=await api('/web/fixtures/index.json');
  const examples=await Promise.all(files.map(f=>api('/web/fixtures/'+f+'.json')));
  const nav=add(main,'nav',null,'chips');nav.setAttribute('aria-label','Образцы блоков');
  for(const [i,r] of examples.entries()){
    const b=rows(r.blocks)[0], id=files[i];
    link(nav,b?.title || id,'#'+id);
    const s=add(main,'section');s.id=id;
    result(s,r,{apply:()=>{},act:(_t,_c,b)=>{b.textContent='Демонстрационный образец';}});
    if(id==='products'){
      add(s,'h3','Карточка в сравнении');mini(s,r.blocks[0].items[0]);
      add(s,'span','В реестре ПО','badge');add(s,'span','Поставки ограничены','badge warn');
    }
    if(r.trace){const t=add(s,'section',null,'trace');add(t,'h2','Как работал поиск');trace(t,r,false);}
  }
  add(main,'h2','Состояния выдачи');
  const states=await api('/web/fixtures/states.json');
  for(const [kind,text] of Object.entries(states))stateBox(main,text,kind);
}
export async function page(main) {
  if(location.pathname.startsWith('/card/')){
    const c=await api('/api/card/'+location.pathname.split('/').pop());
    heading(main,'Карточка каталога');card(main,c,{});
    if(c.title)link(main,'Подобрать лицензию на витрине','/?'+new URLSearchParams({q:c.title}));
    return;
  }
  if(location.pathname==='/admin' || location.pathname.startsWith('/inspect/'))await loadMeta().catch(()=>null);
  switch(location.pathname) {
    case '/scenarios':return gallery(main);
    case '/about':return about(main);
    case '/styleguide':return styleguide(main);
    case '/admin':return consolePage(main);
    default:return inspector(main);
  }
}
