import {add,link,rows,line,stateBox} from '../dom.js';
import {adminApi,keyField,fmt,loadBox,resetData} from './common.js';
import {head} from './head.js';
import {ecom,product,content,log} from './roles.js';
import {findings} from './agent.js';
const tabs={head:['Руководитель',head],ecom:['Менеджер e-com',ecom],product:['Продукт',product],content:['Контент',content],agent:['Агент',findings],log:['Журнал',log]};
export function consolePage(main){
  document.title='Аналитика поиска · Кузница Softline';main.classList.add('console');
  const top=add(main,'header',null,'consoleHeader'),title=add(top,'div');
  add(title,'h1','Аналитика поиска');const info=add(title,'div');
  const auth=add(top,'div',null,'keyBox');
  keyField(auth,()=>{header();render();});
  const nav=add(main,'nav',null,'adminTabs');nav.setAttribute('aria-label','Разделы аналитики');
  for(const [id,[label]] of Object.entries(tabs))link(nav,label,'#'+id);
  const view=add(main,'div',null,'adminView');
  function header(){
    info.replaceChildren();line(info,'Данные синтетические','badge','span');
    loadBox(info,async box=>{
      const [ingest,k]=await Promise.all([adminApi('ingest'),adminApi('kpi')]);
      const days=rows(k.slices?.day).map(d=>d.key).filter(Boolean).sort();
      line(box,[days.length?[days[0],days.at(-1)].join(' — '):'',...rows(ingest.sources).map(r=>r.source+' · '+fmt(r.searches))].filter(Boolean).join('   /   '),'muted');
    });
  }
  function render(){
    let [tab,query]=location.hash.slice(1).split('?');if(!Object.hasOwn(tabs,tab))tab='head';
    for(const a of nav.children){if(a.hash==='#'+tab)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
    view.replaceChildren();
    try{
      const params=new URLSearchParams(query);tabs[tab][1](view,params);
      const target=[...view.querySelectorAll('[data-section]')].find(el=>el.dataset.section===params.get('section'));
      if(target)requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));
    }
    catch(e){stateBox(view,e.message,'error');}
  }
  header();render();
  window.addEventListener('hashchange',()=>{render();window.scrollTo(0,0);});
  window.addEventListener('pageshow',e=>{if(e.persisted){resetData();header();render();}});
}
