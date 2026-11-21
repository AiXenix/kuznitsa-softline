import {add,button,link,line,rows,details} from '../dom.js';
import {loadMeta,caption} from '../labels.js';
import {section,loadBox,adminApi,field,taskButton,table,pct,rub,date} from './common.js';
import {weights} from './head.js';

const types={categories:'category',vendors:'vendor',families:'family',cards:'card',tags:'tag',segments:'segment',profiles:'profile',regions:'region',intents:'intent',queries:'query',channels:'channel',criteria:'criterion'};
const titles={categories:'Разделы каталога',vendors:'Вендоры',families:'Линейки',cards:'Карточки',tags:'Признаки',segments:'Сегменты',profiles:'Профили',regions:'Регионы',intents:'Виды запроса',queries:'Фразы',channels:'Каналы'};
const names={domestic:'Отечественное ПО',fstec:'ФСТЭК',fsb:'ФСБ',in_stock:'В наличии',promo:'Акция',new:'Новинка',subscription:'Подписка',perpetual:'Бессрочная',cloud:'Облако',electronic:'Электронная поставка',box:'Коробка',edu:'Образование',gov:'Госсектор',ui:'Витрина',widget:'Виджет',api:'API',popularity:'Популярность',margin:'Маржа',personal:'Персонализация',stock:'Наличие и доставка',novelty:'Новизна',price_low:'Низкая цена',conversion:'Конверсия'};
const label=(key,id)=>caption(types[key],id,names[id]);
function candidates(key,meta,catalog){
  const ids=new Set(Object.keys(meta.labels?.[key] || {}));
  for(const row of rows(meta[key]))if(row.id)ids.add(row.id);
  for(const row of rows(catalog[key]))ids.add(row.id || row);
  if(key==='segments')for(const row of rows(meta.profiles))if(row.segment)ids.add(row.segment);
  if(key==='channels')for(const id of ['ui','widget','api'])ids.add(id);
  return [...ids].map(id=>[id,label(key,id)]);
}
let sequence=0;
function tags(p,key,values,choices){
  const box=add(p,'div'),control=field(box,titles[key]),chips=add(box,'div',null,'chips');
  const list=add(box,'datalist');list.id='choices-'+(++sequence);control.setAttribute('list',list.id);
  const display=new Map(choices);
  for(const [id,name] of choices){const o=add(list,'option');o.value=name;o.label=id;}
  const selected=new Set(values || []);
  const paint=()=>{chips.replaceChildren();for(const id of selected)button(chips,(display.get(id) || label(key,id))+' ×',()=>{selected.delete(id);paint();control.dispatchEvent(new Event('input',{bubbles:true}));},'chip');};
  function commit(){const text=control.value.trim();if(text){selected.add(choices.find(([id,n])=>n===text || id===text)?.[0] || text);control.value='';paint();}}
  control.onchange=commit;control.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();commit();}};
  paint();return ()=>{commit();return [...selected];};
}
function preview(p,r,sceneRule){
  p.replaceChildren();add(p,'h3','Было → стало');const s=r.summary || {};
  const summary=sceneRule ? details(p,'Оценка по истории поисков') : p;
  line(summary,s.effect_text,'roleLead');line(summary,s.note);
  for(const [key,title,format] of [['share_top5','Доля в первой пятёрке',pct],['avg_margin','Средняя маржа',rub]]){
    if(s[key+'_before']!=null && s[key+'_after']!=null)line(summary,title+' · '+format(s[key+'_before'])+' → '+format(s[key+'_after']));
  }
  if(s.searches_affected!=null)line(summary,'Затронуто поисков · '+s.searches_affected);
  for(const q of rows(r.queries)){
    add(p,'h4',q.q);if(q.moved!=null)line(p,'Сдвинуто позиций · '+q.moved,sceneRule?'roleLead':'');
    const cols=add(p,'div',null,'adminSplit');
    for(const [key,title] of [['before','Было'],['after','Стало']]){
      const col=add(cols,'section');
      const enabled=key==='before'?sceneRule?.enabled:!sceneRule?.enabled;
      add(col,'b',sceneRule?title+' · '+(enabled?'с акцией':'без акции'):title);
      const list=add(col,'ol');
      for(const c of rows(q[key]))add(list,'li',[c.title,c.tier!=null?caption('tier',c.tier,'Уровень '+c.tier):''].filter(Boolean).join(' · '));
    }
  }
  if(sceneRule)p.append(summary);
}
function editor(p,rule,meta,catalog,reload){
  p.replaceChildren();add(p,'h3',rule.id?'Изменить правило':'Новое правило');
  const form=add(p,'form');form.onsubmit=e=>e.preventDefault();
  const title=field(form,'Название',rule.title);title.required=true;
  const order=field(form,'Порядок применения',rule.order ?? 10,'number');
  const scope=rule.scope || {},target=rule.target || {},action=rule.action || {};
  function group(name,data,keys){
    const box=details(form,name);box.open=true;
    const grid=add(box,'div',null,'ruleGrid'),fields={};
    for(const key of keys)fields[key]=tags(grid,key,data[key],candidates(key,meta,catalog));
    return [grid,()=>Object.fromEntries(Object.entries(fields).map(([k,get])=>[k,get()]))];
  }
  const [direction,getTarget]=group('Направление',target,['categories','vendors','families','cards','tags']);
  const min=field(direction,'Цена от, ₽',target.price_rub?.min,'number'),max=field(direction,'Цена до, ₽',target.price_rub?.max,'number');
  for(const price of [min,max]){price.min=0;price.step='0.01';}
  const [audience,getScope]=group('Где действует',scope,['segments','profiles','regions','intents','queries','channels']);
  const from=field(audience,'С даты',scope.from,'date'),to=field(audience,'По дату',scope.to,'date');
  const controls=section(form,'Действие'),grid=add(controls,'div',null,'ruleGrid');
  const boost=field(grid,'Сила приоритета','','range');boost.min=-100;boost.max=100;boost.value=action.boost ?? 0;
  const level=add(boost.parentElement,'output',boost.value);boost.oninput=()=>{level.value=boost.value;};
  const weights={};
  for(const [id,name] of candidates('criteria',meta,catalog)){const i=field(grid,name,action.criteria?.[id],'number');i.min=0;i.step='any';weights[id]=i;}
  const n=field(grid,'В первых N позициях',action.max_in_top?.n,'number'),k=field(grid,'Не более K карточек',action.max_in_top?.k,'number');
  const pin=field(grid,'Закрепить карточку (ID)',action.pin?.card_id),pos=field(grid,'Позиция закрепления',action.pin?.position,'number');
  const badge=field(grid,'Подпись для покупателя',action.public_label),note=field(grid,'Комментарий',rule.note);
  const num=i=>i.value===''?null:i.valueAsNumber;
  function draft(){
    if(!form.reportValidity())throw Error('Проверьте поля правила.');
    if((n.value==='')!==(k.value==='') || (!!pin.value)!=(!!pos.value))throw Error('Заполните оба поля ограничения или закрепления.');
    return {title:title.value.trim(),enabled:rule.enabled ?? false,order:num(order),note:note.value,
      target:{...target,...getTarget(),price_rub:min.value || max.value?{min:num(min),max:num(max)}:null},
      scope:{...scope,...getScope(),from:from.value || null,to:to.value || null},
      action:{...action,boost:Number(boost.value),criteria:Object.fromEntries(Object.entries(weights).filter(([,v])=>v.value!=='').map(([key,v])=>[key,num(v)])),
        max_in_top:n.value?{n:num(n),k:num(k)}:null,pin:pin.value?{card_id:pin.value,position:num(pos)}:null,public_label:badge.value || null},
      ...(rule.cross_tier!=null?{cross_tier:rule.cross_tier}:{})};
  }
  const queries=field(form,'Фразы для проверки через точку с запятой');queries.placeholder='По умолчанию — частые запросы';
  const actions=add(form,'div',null,'adminControls'),out=add(form,'div');
  let revision=0;
  form.addEventListener('input',()=>{revision++;out.replaceChildren();});
  taskButton(actions,'Предпросмотр',async()=>{const pending=revision,phrases=queries.value.split(';').map(x=>x.trim()).filter(Boolean);
    const data=await adminApi('priorities/preview','POST',{rule:{...draft(),...(rule.id?{id:rule.id}:{}),enabled:true},limit:30,...(phrases.length?{queries:phrases}:{})});if(pending===revision)preview(out,data);},'',false);
  taskButton(actions,'Сохранить',async()=>{await adminApi(rule.id?'priorities/'+encodeURIComponent(rule.id):'priorities',rule.id?'PUT':'POST',draft());reload();});
}
function auditValue(value,key){
  if(value==null)return '—';
  if(typeof value==='boolean')return value?'Да':'Нет';
  if(Array.isArray(value))return value.map(id=>label(key,id)).join(', ') || 'Все';
  if(typeof value!=='object')return String(value);
  const keys={...titles,from:'Начало',to:'Конец',boost:'Сила',criteria:'Веса',public_label:'Подпись',max_in_top:'Ограничение',pin:'Закрепление',card_id:'Карточка',position:'Позиция',price_rub:'Цена',min:'От',max:'До'};
  return Object.entries(value).filter(([,v])=>v!=null && (!Array.isArray(v) || v.length))
    .map(([k,v])=>(keys[k] || (key==='criteria'?label('criteria',k):k))+' · '+auditValue(v,k)).join(' / ') || 'Без ограничений';
}
export function settings(p,params){
  const nav=add(p,'nav',null,'adminTabs'),tab=params.get('section') || 'priorities';
  for(const [id,title] of [['weights','Веса выдачи'],['priorities','Приоритеты направлений'],['audit','Журнал изменений']]){
    const a=link(nav,title,'#settings?section='+id);if(tab===id)a.setAttribute('aria-current','page');
  }
  if(tab==='weights'){weights(p,params);return;}
  if(tab==='audit'){
    loadBox(section(p,'Журнал изменений'),async box=>{
      const r=await adminApi('priorities/audit'),items=rows(r.items || r);
      if(!items.length)line(box,'Изменений пока нет.');
      else table(box,items,[['Когда','ts',(v,r)=>date(v ?? r.created_at)],['Автор','author'],['Правило','title',(v,r)=>v || r.after?.title || r.before?.title || r.rule_id],['Изменение','action',(v,r)=>r.note || ({create:'Создание',update:'Изменение',delete:'Удаление',toggle:'Переключение',import:'Импорт'})[r.operation || v] || r.operation || v],['Подробности','after',(_,r)=>{
        const cell=document.createElement('div');
        const d=details(cell,'Изменённые поля'), keys=new Set([...Object.keys(r.before || {}),...Object.keys(r.after || {})]);
        for(const key of keys){
          const a=r.before?.[key],b=r.after?.[key];
          if(JSON.stringify(a)===JSON.stringify(b) || ['created_at','updated_at','id'].includes(key))continue;
          const title=({title:'Название',enabled:'Действует',order:'Порядок',target:'Направление',scope:'Область',action:'Действие',note:'Комментарий',author:'Автор',cross_tier:'Переход между уровнями'})[key] || key;
          line(d,title,null,'b');line(d,[a,b].map(x=>auditValue(x,key)).join(' → '));
        }
        return cell;
      }]]);
    });return;
  }
  const area=section(p,'Приоритеты направлений');
  function render(){
    area.replaceChildren();add(area,'h2','Приоритеты направлений');
    loadBox(area,async box=>{
      const [catalog,meta]=await Promise.all([adminApi('priorities'),loadMeta()]);
      const phase=params.get('phase');
      if(params.get('scene')==='backup' && ['enable','preview','disable'].includes(phase)){
        const rule=rows(catalog.items).find(r=>r.id==='seed-backup-promo');
        if(!rule){line(box,'Пример акции RuBackup отсутствует в этом снимке.');return;}
        add(box,'h3',rule.title);
        line(box,rule.enabled?'Правило включено':'Правило выключено','badge');
        if(phase==='preview'){
          const out=add(box,'section');
          line(out,rule.enabled?'Слева правило действует, справа показана выдача без него.':'Слева текущая выдача, справа показана выдача с правилом.');
          const {id,title,order,target,scope,action,cross_tier}=rule;
          const draft={id,title,order,target,scope:{...scope,profiles:['guest']},action,cross_tier,enabled:!rule.enabled};
          const data=await adminApi('priorities/preview','POST',{rule:draft,queries:['резервное копирование'],limit:1});
          preview(add(out,'div'),data,rule);
        }else{
          const enable=phase==='enable';
          if(Boolean(rule.enabled)!==enable)taskButton(box,enable?'Включить пример':'Выключить пример',async()=>{
            await adminApi('priorities/'+encodeURIComponent(rule.id)+'/toggle','POST',{});render();
          });
        }
        return;
      }
      const ed=add(box,'section',null,'ruleEditor');
      const edit=r=>{editor(ed,r,meta,catalog,render);ed.scrollIntoView({block:'start'});};
      button(box,'Создать правило',()=>edit({}));box.append(ed);
      if(params.get('scene')==='gov'){
        const title='Отечественные антивирусы для госзаказчиков';
        const existing=rows(catalog.items).find(r=>r.title===title);
        const rule=existing || {title,target:{categories:[meta.labels?.categories?.antivirus?'antivirus':'endpoint_security'],tags:['domestic']},scope:{segments:['gov']},action:{boost:40,criteria:{margin:.6,popularity:.4}}};
        button(box,existing?'Открыть правило показа':'Подготовить правило показа',()=>edit(rule));
      }
      const items=rows(catalog.items);if(!items.length){line(box,'Пока нет правил. Создайте направление для предпросмотра.');return;}
      const t=add(box,'div');box.insertBefore(t,ed);
      const describe=(values)=>Object.entries(values || {}).flatMap(([key,v])=>Array.isArray(v)?v.map(id=>label(key,id)):[]).join(' · ') || 'Все';
      table(t,items,[['Состояние','enabled',(v,r)=>{const cell=document.createElement('div');taskButton(cell,v?'Выключить':'Включить',async()=>{await adminApi('priorities/'+encodeURIComponent(r.id)+'/toggle','POST',{});render();});return cell;}],
        ['Название','title',(v,r)=>{const cell=document.createElement('div');button(cell,v,()=>edit(r));return cell;}],['Направление','target',v=>[describe(v),v?.price_rub?[v.price_rub.min,v.price_rub.max].map(n=>n==null?'…':rub(n)).join(' – '):''].filter(Boolean).join(' · ')],['Где действует','scope',describe],
        ['Период','scope',v=>[v?.from,v?.to].filter(Boolean).join(' — ') || 'Всегда'],['Сила','action',a=>a?.boost],['Эффект за сутки','stats',s=>s?[s.fired_24h!=null?'Сработало · '+s.fired_24h:'',s.searches_in_scope_24h!=null?'В области · '+s.searches_in_scope_24h:'',s.share_top5!=null?'В топ-5 · '+pct(s.share_top5):''].filter(Boolean).join(' / '):''],
        ['','id',id=>{const cell=document.createElement('div');taskButton(cell,'Удалить',async()=>{if(!confirm('Удалить это правило?'))return;await adminApi('priorities/'+encodeURIComponent(id),'DELETE');render();});return cell;}]]);
    });
  }
  render();
}
