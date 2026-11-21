import {caption} from '../labels.js';
import {money,add,link,rows,line,details,stateBox} from '../dom.js';
import {adminApi,keyField,fmt,date,tile,shop,loadBox,empty} from './common.js';
import {trace} from '../trace.js';
import {result} from '../result.js';

export function inspector(main){
  document.title='Разбор запроса · Кузница Softline';
  const top=add(main,'div',null,'sectionHead');link(top,'← Журнал поисков','/admin#log');keyField(add(top,'div',null,'keyBox'),load);
  const view=add(main,'div');
  function load(){
    view.replaceChildren();loadBox(view,async p=>{
      const id=location.pathname.split('/').pop();
      const qParam=new URLSearchParams(location.search).get('q');
      if(id==='by-query' && qParam){
        let ref;
        try{ref=await adminApi('ui/search-reference?q='+encodeURIComponent(qParam));}
        catch(e){stateBox(p,e.message,'error');link(p,'Искать фразу на витрине',shop(qParam));return;}
        const url=new URL(location.href);url.pathname='/inspect/'+encodeURIComponent(ref.search_id);url.searchParams.delete('q');location.replace(url);return;
      }
      const data=await adminApi('search/'+id);
      const r=data.response || data.result || data.search || data;
      const q=r.query?.raw || r.q_raw || data.q_raw;
      const profile=r.profile?.id || r.client_id || data.client_id;
      const when=r.ts ?? data.ts, segment=r.profile?.segment || r.segment || data.segment;
      add(p,'h1',q || 'Разбор запроса');
      line(p,[when==null?'':date(when)+' МСК',r.profile?.short || r.profile?.title?.split(/ [—–] /)[0] || caption('profile',profile),caption('segment',segment),caption('mode',r.mode),r.understood?.intent_title || caption('intent',r.intent)].filter(Boolean).join(' · '),'muted');
      const products=rows(r.blocks).find(b=>b.type==='products');
      const n=r.n_cards ?? data.n_cards ?? products?.total;
      const stats=add(p,'div',null,'adminTiles');
      for(const [title,value] of [['Карточки',n],['Время, мс',r.timing_ms?.total ?? r.ms],['Вызовы модели',r.cost?.llm_calls ?? r.llm_calls],['Стоимость',r.cost?.pending?'Уточняется':r.cost?.rub!=null || data.cost_rub!=null?money(r.cost?.rub ?? data.cost_rub):null]]){
        if(value!=null)tile(stats,title,typeof value==='number'?fmt(value,2):value);
      }
      if(q){
        const params=new URLSearchParams({q,profile:profile || 'guest',mode:r.mode || 'smart'});
        const actions=add(p,'nav',null,'adminControls');link(actions,r.archived_summary?'Повторить запрос сейчас':'Открыть на витрине','/?'+params);
        params.set('compare','modes');link(actions,'Сравнить с обычным поиском по словам','/?'+params);
      }
      if(r.archived_summary)line(p,'Архивная сводка. Журнал хранит метаданные этой выдачи.','hint');
      const split=add(p,'div',null,'inspectSplit');
      if(rows(r.trace).length){
        const panel=add(split,'section',null,'trace');add(panel,'h2','Как работал поиск');trace(panel,r,false);
        panel.querySelectorAll('.steps>li>details').forEach(d=>{d.open=true;});
      }
      if(rows(r.blocks).some(b=>typeof b==='object')){const right=add(split,'section');add(right,'h2','Сохранённая выдача');result(right,r);}
      if(!split.childElementCount && !r.archived_summary)empty(split,'Повторите запрос на витрине, чтобы записать трассу.');
      const raw=details(p,'Полная запись журнала');
      raw.ontoggle=()=>{if(raw.open && !raw.querySelector('pre'))add(raw,'pre',JSON.stringify(data,null,2));};
    });
  }
  load();
}
