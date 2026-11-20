import {api} from './api.js';
import {freshSession,modes} from './state.js';
import {add,button,stateBox} from './dom.js';
import {result} from './result.js';

export function compare(panel,kind,req,profiles,preset=[]) {
  panel.hidden=false;panel.replaceChildren();
  const head=add(panel,'div',null,'sectionHead');
  add(head,'h2',kind==='profiles' ? 'Сравнение профилей' : 'Сравнение режимов');
  const area=add(panel,'div');
  button(head,'Закрыть',()=>{panel.replaceChildren();panel.hidden=true;});
  if(!req.q){stateBox(area,'Введите запрос в строке поиска и выберите сравнение.');return;}
  add(area,'p','Запрос «'+req.q+'»','hint');
  const selectors=[];
  if(kind==='profiles') {
    const settings=add(area,'div',null,'settings');
    const ids=[...new Set([...preset,req.profile_id,...profiles.map(p=>p.id)])].slice(0,3);
    for (const [i,id] of ids.entries()) {
      const l=add(settings,'label','Профиль '+(i+1)), s=add(l,'select');
      if(i===2) s.add(new Option('Без третьего профиля',''));
      for(const p of profiles) s.add(new Option(p.title,p.id));
      s.value=id;s.onchange=refresh;selectors.push(s);
    }
  }
  const columns=add(area,'div',null,'columns');
  async function refresh() {
    columns.replaceChildren();
    const values=kind==='profiles' ? [...new Set(selectors.map(s=>s.value).filter(Boolean))] : ['naive','smart'];
    if(values.length<2){stateBox(columns,'Выберите разные профили.');return;}
    const groups=await Promise.all(values.map(async v=>{
      const p=add(columns,'section',null,'comparisonColumn');
      add(p,'h3',kind==='profiles' ? profiles.find(row=>row.id===v)?.title : modes[v]);
      const body=add(p,'div'); stateBox(body,'Идёт поиск…','loading');
      try {
        const r=await api('/api/search',{...req,[kind==='profiles'?'profile_id':'mode']:v,session_id:freshSession(),source:'compare',page:1,page_size:5});
        body.replaceChildren();result(body,r);
        return [...body.querySelectorAll('[data-card]')];
      }catch(err){body.replaceChildren();stateBox(body,err.message,'error');return null;}
    }));
    if(groups.some(g=>!g)) return;
    for(const group of groups) for(const [i,node] of group.entries()) {
      if(groups.some(other=>other[i]?.dataset.card!==node.dataset.card || other[i]?.dataset.offer!==node.dataset.offer)) {
        node.classList.add('different');node.prepend(Object.assign(document.createElement('small'),{textContent:'Отличается на этой позиции'}));
      }
    }
  }
  refresh();
}
