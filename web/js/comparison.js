import {api} from './api.js';
import {caption} from './labels.js';
import {freshSession} from './state.js';
import {add,button,stateBox,rows,line,num,moneyRate} from './dom.js';
import {mini} from './product.js';


export function compare(panel,kind,req,profiles,preset=[],onClose=()=>{},onSelect=()=>{}) {
  panel.hidden=false;panel.replaceChildren();
  const head=add(panel,'div',null,'sectionHead');
  add(head,'h2',kind==='profiles' ? 'Сравнение профилей' : 'Сравнение режимов');
  const area=add(panel,'div');
  button(head,'Закрыть',()=>{panel.replaceChildren();panel.hidden=true;onClose();});
  if(!req.q){stateBox(area,'Введите запрос в строке поиска и выберите сравнение.');return;}

  const selectors=[];
  let baseline='naive';
  if(kind==='modes'){
    const picker=add(add(head,'label','Сравнить с умным режимом '),'select');
    picker.add(new Option(caption('mode','naive'),'naive'));picker.add(new Option(caption('mode','fast'),'fast'));
    picker.onchange=()=>{baseline=picker.value;refresh();};
  }
  if(kind==='profiles') {
    const settings=add(area,'div',null,'settings');
    const ids=[...new Set([...preset,req.profile_id,...profiles.map(p=>p.id)])].slice(0,3);
    for (const [i,id] of ids.entries()) {
      const l=add(settings,'label','Профиль '+(i+1)), s=add(l,'select');
      if(i===2) s.add(new Option('Без третьего профиля',''));
      for(const p of profiles) s.add(new Option(p.title.split(/ [—–] /)[0],p.id));
      s.value=id;s.onchange=()=>{onSelect(selectors.map(s=>s.value));refresh();};selectors.push(s);
    }
  }
  const summary=add(area,'p',null,'compareSummary');
  const plural=new Intl.PluralRules('ru');
  const count=n=>n+' '+({one:'результат',few:'результата',many:'результатов'}[plural.select(n)] || 'результата');
  let generation=0;
  const columns=add(area,'div',null,'columns');
  async function refresh() {
    const seq=++generation;summary.textContent='';columns.replaceChildren();
    const values=kind==='profiles' ? [...new Set(selectors.map(s=>s.value).filter(Boolean))] : [baseline,'smart'];
    if(values.length<2){stateBox(columns,'Выберите разные профили.');return;}
    const groups=await Promise.all(values.map(async v=>{
      const p=add(columns,'section',null,'comparisonColumn');
      add(p,'h3',kind==='profiles' ? profiles.find(row=>row.id===v)?.title.split(/ [—–] /)[0] : v==='smart'?'Кузница · умный режим':caption('mode',v));
      const body=add(p,'div'); stateBox(body,'Идёт поиск…','loading');
      try {
        const r=await api('/api/search',{...req,[kind==='profiles'?'profile_id':'mode']:v,session_id:freshSession(),source:'compare',page:1,page_size:8});
        body.replaceChildren();
        const blocks=rows(r.blocks);
        for(const b of blocks.filter(b=>b.type==='my_licenses')){
          const owned=line(body,'Ваши лицензии · '+rows(b.items).map(i=>i.title).join(', '),'owned');
          owned.title=owned.textContent;
        }
        const main=blocks.find(b=>['products','analogs','services','promo'].includes(b.type));
        const cards=rows(main?.items).map(i=>i.card || i);
        const total=main?.total ?? cards.length;
        line(body,[count(total),r.timing_ms?.total==null?'':num(r.timing_ms.total)+' мс',moneyRate(r.cost?.rub)].filter(Boolean).join(' · '),'compareMetrics');
        const nodes=cards.map(c=>mini(body,c));
        if(!cards.length)stateBox(body,r.notes?.[0] || 'Подходящих товаров нет.');
        return {cards,nodes,total:main?.total ?? cards.length};
      }catch(err){body.replaceChildren();stateBox(body,err.message,'error');return null;}
    }));
    if(seq!==generation || groups.some(g=>!g))return;
    const key=c=>c?.card_ref || c?.card_id;
    const first=groups[0].cards.map(key);
    if(kind==='modes'){
      groups.forEach((group,col)=>group.cards.forEach((card,i)=>{
        const pos=groups[1-col].cards.findIndex(c=>key(card) && key(c)===key(card));
        const other=col===0?'у умного поиска':baseline==='fast'?'у быстрого поиска':'у обычного поиска';
        line(group.nodes[i],pos<0?'Нет в показанном списке '+other:other+' · '+(pos+1)+'-я','movement','small');
      }));
    }else for(const group of groups.slice(1))group.cards.forEach((c,i)=>{
      const pos=key(c)?first.indexOf(key(c)):-1, shift=pos-i;
      if(pos<0 || shift)line(group.nodes[i],pos<0?'нет в первом столбце':(shift>0?'↑':'↓')+Math.abs(shift),'movement','small');
    });
    const windowSize=Math.min(5,Math.max(...groups.map(g=>g.cards.length)));
    const matches=first.slice(0,windowSize).filter((id,i)=>id && groups.every(g=>key(g.cards[i])===id)).length;
    summary.textContent=kind==='profiles' ? 'Совпадает '+matches+' из '+windowSize+' позиций в первой пятёрке' :
      caption('mode',baseline)+': '+count(groups[0].total)+' · Умный: '+count(groups[1].total);
  }
  refresh();
}
