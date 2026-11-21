import {caption} from '../labels.js';
import {button,add,link,rows,line,stateBox} from '../dom.js';
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
  button(auth,'Обновить',()=>{resetData();header();render();});
  keyField(auth,()=>{header();render();});
  const nav=add(main,'nav',null,'adminTabs');nav.setAttribute('aria-label','Разделы аналитики');
  for(const [id,[label]] of Object.entries(tabs))link(nav,label,'#'+id);
  const view=add(main,'div',null,'adminView');
  function header(){
    info.replaceChildren();line(info,'Данные синтетические','badge','span');
    const summary=add(info,'div',null,'journalSummary');
    loadBox(summary,async box=>{
      const report=await adminApi('ui/history-days'),days=rows(report.items).filter(d=>d.key);
      const start=report.period?.start || days[0]?.key,end=report.period?.end || days.at(-1)?.key;
      if(!start || !end)return;
      const stamp=(day,year)=>new Date(day+'T12:00:00Z').toLocaleDateString('ru-RU',{timeZone:'Europe/Moscow',day:'2-digit',month:'2-digit',...(year?{year:'numeric'}:{})});
      line(box,'Журнал: '+stamp(start,start.slice(0,4)!==end.slice(0,4))+' — '+stamp(end,true));
    });
    loadBox(summary,async box=>{
      const sources=rows((await adminApi('ingest')).sources);
      const sets=new Map(),live=['api','ui','gallery','compare'];
      for(const r of sources){
        const k=r.source==='history'?'История магазина':live.includes(r.source)?'Живые запросы':'Служебные прогоны';
        sets.set(k,(sets.get(k) || 0)+r.searches);
      }
      box.title=sources.map(r=>caption('source',r.source)+' · '+fmt(r.searches)).join(' / ');
      line(box,['История магазина','Живые запросы','Служебные прогоны'].filter(k=>sets.has(k)).map(k=>k+' '+fmt(sets.get(k))).join(' · '));
    });
  }
  function render(){
    let [tab,query]=location.hash.slice(1).split('?');if(!Object.hasOwn(tabs,tab))tab='head';
    for(const a of nav.children){if(a.hash==='#'+tab)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
    view.replaceChildren();
    try{
      const params=new URLSearchParams(query);tabs[tab][1](view,params);
      const target=[...view.querySelectorAll('[data-section]')].find(el=>el.dataset.section===params.get('section'));
      if(target && new URLSearchParams(location.search).get('show')==='1')view.prepend(target);
      else if(target)requestAnimationFrame(()=>target.scrollIntoView({block:'start'}));
    }
    catch(e){stateBox(view,e.message,'error');}
  }
  header();render();
  window.addEventListener('hashchange',()=>{window.scrollTo(0,0);document.getElementById('pageScroll')?.scrollTo(0,0);render();});
  window.addEventListener('pageshow',e=>{if(e.persisted){resetData();header();render();}});
}
