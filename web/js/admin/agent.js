import {add,button,line,link,details,rows} from '../dom.js';
import {adminApi,roles,types,statuses,fmt,pct,rub,shortRub,valid,groupText,phrase,loadBox,section,options,taskButton,empty} from './common.js';

const priorities={high:'Высокий',medium:'Средний',low:'Низкий'};
const actionFields={product:'Продукт',category:'Категория',field:'Поле карточки',card_ids:'Карточки',client_id:'Клиент',text:'Текст баннера',phrase:'Фраза',to:'Замена',rel:'Релевантность',pop:'Популярность',margin:'Маржа',pers:'Профиль',kind:'Тип',intent:'Сценарий',segment:'Сегмент'};
function verification(p,v){
  if(!v?.after)return;
  const box=add(p,'section',null,'verification');add(box,'h3','Было → стало');line(box,v.summary);
  for(const q of new Set([...Object.keys(v.before || {}),...Object.keys(v.after || {})])){
    const b=v.before?.[q],a=v.after?.[q],row=add(box,'article');
    row.append(phrase(q,a?.search_id || b?.search_id));
    if(rows(v.regressions).includes(q))line(row,'Выдача ухудшилась','badge warn','span');
    if(rows(v.recovered).includes(q))line(row,'Выдача восстановлена','badge','span');
    const split=add(row,'div',null,'adminSplit');
    for(const [title,side] of [['Было',b],['Стало',a]]){
      const cell=add(split,'div');add(cell,'b',title+' · '+(Array.isArray(side?.cards)?fmt(side.cards.length)+' в сохранённом списке':'нет записи'));
      const ol=add(cell,'ol');for(const c of rows(side?.cards).slice(0,5))add(ol,'li',c.title || c.card_id || c);
      for(const banner of rows(side?.banners))line(cell,banner.text || banner);
      if(side?.search_id)link(cell,'Трасса →','/inspect/'+encodeURIComponent(side.search_id));
    }
  }
}
function card(p,i,change,expanded){
  const box=add(p,'article',null,'finding');
  const meta=add(box,'div',null,'chips');add(meta,'span',types[i.type] || i.type,'badge');add(meta,'b',statuses[i.status] || i.status,'stage');
  line(meta,roles[i.role] || i.role,'muted','small');line(meta,priorities[i.priority]?'Приоритет · '+priorities[i.priority]:i.priority,'muted','small');
  const h=add(box,'h3');link(h,i.title || i.id,'#agent?id='+encodeURIComponent(i.id));
  line(box,i.summary);
  const impact=i.impact || {};
  if(valid(impact.expected_rub)||valid(impact.conservative_rub)){
    const e=add(box,'p',null,'impact');line(e,impact.metric_label,'muted','small');
    add(e,'strong',[valid(impact.conservative_rub)?'Осторожно · '+shortRub(impact.conservative_rub):'',valid(impact.expected_rub)?'Ожидаемо · '+shortRub(impact.expected_rub):''].filter(Boolean).join('   /   '));
    e.title=[rub(impact.conservative_rub),rub(impact.expected_rub)].join(' / ');
  }
  if(valid(i.confidence)){
    const label=add(box,'label','Уверенность · '+pct(i.confidence),'confidence');
    label.title=i.confidence_note || 'Число сессий / (число сессий + 20)';
    const meter=add(label,'progress');meter.max=1;meter.value=i.confidence;
  }
  const d=details(box,'Доказательства и действие');d.open=expanded;
  const ev=i.evidence || {};
  line(d,[valid(ev.searches_30d)?fmt(ev.searches_30d)+' поисков':'',valid(ev.sessions_30d)?fmt(ev.sessions_30d)+' сессий':'',groupText(ev.segments)].filter(Boolean).join(' · '));
  for(const q of rows(ev.sample_queries)){
    const text=typeof q==='string'?q:q.q;
    const row=add(d,'div');row.append(phrase(text,q.search_id || ev.search_ids?.[text] || i.verification?.before?.[text]?.search_id));
  }
  for(const [q,n] of Object.entries(ev.reformulated_to || {})){
    const row=add(d,'p','Переходили на ');row.append(phrase(q),document.createTextNode(' · '+fmt(n)));
  }
  const action=i.action || {};line(d,action.label,null,'h4');
  for(const [key,v] of [...Object.entries(action.conditions || {}),...Object.entries(action.payload_json || {})]){
    if(key==='clients'){const clients=details(d,'Клиенты · '+fmt(rows(v).length));for(const client of rows(v))line(clients,[client.client_id,valid(client.licenses)?fmt(client.licenses)+' лицензий':''].filter(Boolean).join(' · '));}
    else line(d,(actionFields[key] || key)+' · '+(Array.isArray(v)?v.join(', '):typeof v==='object'?JSON.stringify(v):v));
  }
  line(d,impact.formula_note,'muted');
  if(i.verification?.after){d.open=false;verification(box,i.verification);box.insertBefore(box.querySelector('.verification'),d);}
  const controls=add(box,'div',null,'adminControls');
  const ops=i.status==='new'?['apply','reject']:i.status==='applied'?['verify']:[];
  if(ops.length)box.insertBefore(controls,d);
  for(const op of ops)taskButton(controls,({apply:'Применить',verify:'Проверить',reject:'Отклонить'})[op],async()=>{
    if(box.dataset.pending)throw Error('Дождитесь завершения действия.');
    box.dataset.pending='true';
    try{const updated=await adminApi('insights/'+encodeURIComponent(i.id)+'/'+op,'POST',{});change(updated);}
    finally{delete box.dataset.pending;}
  },op==='reject'?'':'primary');
}

export function findings(parent,params,role=''){
  const panel=section(parent,role?'Предложения для роли':'Предложения агента');
  const path='insights'+(role?'?role='+encodeURIComponent(role):'');
  loadBox(panel,async wrapper=>{
    let all=rows((await adminApi(path)).items),focus=params.get('id'),limit=8;
    const view=add(wrapper,'div');
    function render(){
      view.replaceChildren();
      const filters=focus?details(view,'Фильтры и виды предложений'):view;
      const counts=add(filters,'div',null,'chips');
      for(const [key,title] of Object.entries(types)){
        const n=all.filter(i=>i.type===key).length;
        if(n)add(counts,'span',title+' · '+n,'chip');
      }
      if(!role){
        const controls=add(filters,'div',null,'adminControls');
        const set=(k,v)=>{const next=new URLSearchParams(params);next.delete('id');if(v)next.set(k,v);else next.delete(k);location.hash='agent?'+next;};
        for(const [k,title,values] of [['role','Роль',roles],['type','Вид',types],['status','Статус',statuses],['sort','Порядок',{asc:'Меньший эффект сначала'}]]){
          options(controls,title,{'':k==='sort'?'Больший эффект сначала':'Все',...values},params.get(k)||'',v=>set(k,v));
        }
        taskButton(controls,'Найти новые',async()=>{await adminApi('insights/refresh','POST',{});all=rows((await adminApi(path)).items);render();});
      }
      const filtered=all.filter(i=>role || (focus?i.id===focus:['role','type','status'].every(k=>!params.get(k)||i[k]===params.get(k))));
      filtered.sort((a,b)=>((b.impact?.expected_rub??0)-(a.impact?.expected_rub??0))*(params.get('sort')==='asc'?-1:1));
      if(!filtered.length){empty(view,'Измените фильтры или запустите поиск новых предложений.');return;}
      if(!role && params.get('first')==='1' && !focus){
        const chosen=filtered[0];const next=new URLSearchParams({id:chosen.id});
        const u=new URL(location.href);u.hash='agent?'+next;
        history.replaceState(history.state,'',u);params=next;focus=chosen.id;render();return;
      }
      const lead=filtered[0];
      if(!focus)line(view,lead.title,'roleLead');
      if(focus)link(view,'← Все предложения','#agent');
      for(const i of filtered.slice(0,limit)){
        card(view,i,updated=>{
          all=all.map(row=>row.id===updated.id?updated:row);
          if(!role && params.get('status') && updated.status!==params.get('status')){
            location.hash='agent?id='+encodeURIComponent(updated.id);
          }else render();
        },i.id===focus || filtered.length===1);
      }
      if(filtered.length>limit)button(view,'Показать ещё',()=>{limit+=8;render();});
    }
    render();
  });
}
