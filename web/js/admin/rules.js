import {caption,readable} from '../labels.js';
import {add,details,link,rows} from '../dom.js';
import {adminApi,section,field,options,loadBox,taskButton,empty,shop} from './common.js';

const kinds={synonym:'Синоним',redirect:'Переадресация',pin:'Закрепление',ban:'Скрытие',boost:'Подъём',bury:'Понижение',banner:'Баннер'};
const labels={phrase:'Точная фраза',pattern:'Маска',intent:'Сценарий',category:'Категория',segment:'Сегмент',start:'Начало · Unix',end:'Окончание · Unix',q:'Запрос',to:'Замена',card_id:'ID карточки',factor:'Коэффициент',position:'Позиция',text:'Текст'};
export function rules(parent){
  const panel=section(parent,'Правила выдачи');
  const editor=details(panel,'Создать правило');const form=add(editor,'div',null,'adminControls');
  const kind=options(form,'Вид',kinds,'synonym',draw);
  add(editor,'h3','Когда срабатывает');
  const conditions=add(editor,'div',null,'adminFields'),inputs={};
  for(const k of ['phrase','pattern','intent','category','segment','start','end'])inputs[k]=field(conditions,labels[k],'',['start','end'].includes(k)?'number':'text');
  add(editor,'h3','Что изменить');
  const action=add(editor,'div',null,'adminControls');let fields,redirect,entity;
  function draw(){
    action.replaceChildren();fields={};
    if(kind.value==='synonym')entity=options(action,'Вид замены',{text:'Текст',vendor:'Вендор',family:'Семейство',category:'Категория',use_case:'Задача'},'text',()=>{});
    if(kind.value==='redirect')redirect=options(action,'Цель',{q:'Запрос',category:'Категория',intent:'Сценарий'},'q',()=>{});
    const keys=({synonym:['phrase','to'],redirect:['target'],pin:['card_id','position'],ban:['card_id'],boost:['card_id','factor'],bury:['card_id','factor'],banner:['text']})[kind.value];
    for(const k of keys){fields[k]=field(action,labels[k] || 'Значение',k==='position'||k==='factor'?1:'',['position','factor'].includes(k)?'number':'text');fields[k].required=true;}
  }
  draw();
  const list=add(panel,'div');
  function refresh(){list.replaceChildren();loadBox(list,async box=>{
    const r=await adminApi('rules');if(!rows(r.items).length)empty(box,'Создайте первое правило.');
    for(const row of rows(r.items)){
      const item=add(box,'article',null,'ruleRow');
      add(item,'strong',kinds[row.kind] || row.kind);add(item,'span',row.enabled?'Включено':'Выключено','badge');
      const cond=row.conditions || {},act=row.action || {};
      add(item,'p',[...Object.entries(cond),...Object.entries(act)].map(([k,v])=>(labels[k] || caption('',k))+' · '+(['intent','segment','category'].includes(k)?caption(k,v):readable(v))).join(' / '));
      const ops=add(item,'div',null,'adminControls');
      if(cond.phrase || act.phrase){const a=link(ops,'Проверить на запросе ↗',shop(cond.phrase || act.phrase));a.target='_blank';a.rel='noopener';}
      const path='rules/'+encodeURIComponent(row.id);
      taskButton(ops,row.enabled?'Выключить':'Включить',async()=>{await adminApi(path,'PUT',{kind:row.kind,conditions:cond,action:act,enabled:!row.enabled});refresh();});
      taskButton(ops,'Удалить',async()=>{if(!sessionStorage.kzAdminKey)throw Error('Нужен ключ доступа');if(!confirm('Удалить правило «'+(kinds[row.kind] || row.kind)+'»?'))return 'Отменено';await adminApi(path,'DELETE');refresh();});
    }
  });}
  taskButton(editor,'Создать',async()=>{
    const cond={},act={};
    for(const [k,i] of Object.entries(inputs))if(i.value.trim())cond[k]=i.type==='number'?Number(i.value):i.value.trim();
    for(const [k,i] of Object.entries(fields)){if(!i.reportValidity())throw Error('Заполните поля действия.');act[k==='target'?redirect.value:k]=i.type==='number'?Number(i.value):i.value.trim();}
    if(kind.value==='synonym')act.kind=entity.value;
    await adminApi('rules','POST',{kind:kind.value,conditions:cond,action:act,enabled:true});refresh();editor.open=false;
  });
  refresh();
}
