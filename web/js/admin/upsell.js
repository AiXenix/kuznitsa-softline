import {add,button,line,rows} from '../dom.js';
import {api} from '../api.js';
import {caption} from '../labels.js';
import {adminApi,field,fmt,loadBox,section,table,taskButton} from './common.js';

const groups={classes:['Классы','category'],families:['Линейки','family'],vendors:['Производители','vendor'],query_words:['Слова запроса','']};

function describe(side,classes){
  return Object.entries(groups).flatMap(([key,[,kind]])=>rows(side?.[key]).map(v=>key==='classes' && classes[v]?classes[v]:kind?caption(kind,v):v)).join(', ');
}
export function upsell(view){
  const list=section(view,'Правила допродаж'),editor=section(view,'Редактор правила');
  editor.hidden=true;editor.classList.add('upsellEditor');
  let catalogClasses={};
  function edit(r){
    editor.hidden=false;editor.replaceChildren();add(editor,'h2',r.reason || 'Новое правило');
    const form=add(editor,'div',null,'adminForm');
    const list=add(form,'datalist');list.id='upsell-class-ids';
    for(const [id,title] of Object.entries(catalogClasses)){const option=add(list,'option',title);option.value=id;}
    const id=field(form,'Идентификатор',r.id);id.disabled=Boolean(r.id);
    const reason=field(form,'Причина рекомендации',r.reason);
    const weight=field(form,'Вес',r.weight ?? 1,'number');weight.min=0;weight.max=1;weight.step='0.01';
    const enabled=field(form,'Правило включено','','checkbox');enabled.checked=r.enabled!==false;
    const sides={};
    for(const [side,title] of [['when','Ищут'],['offer','Предлагаем']]){
      const box=add(form,'fieldset');add(box,'legend',title);sides[side]={};
      for(const [key,[name]] of Object.entries(groups)){
        if(side==='offer' && key==='query_words')continue;
        sides[side][key]=field(box,name+' (через запятую)',rows(r[side]?.[key]).join(', '));
        if(key==='classes')sides[side][key].setAttribute('list',list.id);
      }
    }
    function draft(){
      const rule={id:id.value.trim(),reason:reason.value.trim(),source:r.source || 'kb',weight:Number(weight.value),enabled:enabled.checked};
      for(const [side,fields] of Object.entries(sides))rule[side]=Object.fromEntries(Object.entries(fields).map(([k,i])=>[k,i.value.split(',').map(v=>v.trim()).filter(Boolean)]));
      return rule;
    }
    const q=field(editor,'Поисковый запрос',rows(r.when?.query_words)[0]);
    const result=add(editor,'div');result.setAttribute('role','status');
    taskButton(editor,'Предпросмотр',async()=>{
      result.replaceChildren();
      const data=await adminApi('upsell/preview','POST',{q:q.value,rule:draft()});
      line(result,data.matched?'Условия совпали':'Условия не совпали',null,'strong');
      if(data.main_count!=null)line(result,'Основных карточек · '+fmt(data.main_count));
      for(const c of rows(data.items)){
        const place={products:'Лента товаров',crosssell:'Часто покупают вместе'}[c.block];
        line(result,[c.title,place,c.position!=null?'позиция '+fmt(c.position):''].filter(Boolean).join(' · '));
      }
      line(result,data.note,'muted');
    },'',false);
    taskButton(editor,'Сохранить',async()=>{
      await adminApi(r.id?'upsell/'+encodeURIComponent(r.id):'upsell',r.id?'PUT':'POST',draft());
      editor.hidden=true;refresh();
    },'primary');
    button(editor,'Закрыть',()=>{editor.hidden=true;});
    editor.scrollIntoView({block:'start'});
  }
  const tools=add(list,'div',null,'upsellTools');
  const create=button(tools,'Новое правило',()=>edit({}));
  const filter=field(tools,'Найти правило','','search'),body=add(list,'div');
  function refresh(){
    body.replaceChildren();loadBox(body,async box=>{
      let sample=false;
      const rules=adminApi('upsell').catch(err=>{
        if(err.status!==404)throw err;
        sample=true;return api('/web/fixtures/upsell-list.json');
      });
      const [{items},classes]=await Promise.all([rules,api('/web-data/catalog-sections?all_classes=true').catch(()=>({}))]);
      create.disabled=sample;
      if(sample)line(box,'Образец из отчёта. Редактирование и живые счётчики появятся при подключении API допродаж.','hint');
      catalogClasses=classes;
      const columns=[['Ищут','when',v=>describe(v,classes)],['Предлагаем','offer',v=>describe(v,classes)],['Причина','reason'],['Вес','weight'],
        ['Показы','counters',v=>fmt(v?.impressions)],['Клики','counters',v=>fmt(v?.clicks)],['В корзину','counters',v=>fmt(v?.carts)],
        ['Вкл.','enabled',(v,r)=>{
          if(sample)return v?'Включено':'Выключено';
          const cell=document.createElement('div');
          taskButton(cell,v?'Включено':'Выключено',async()=>{await adminApi('upsell/'+encodeURIComponent(r.id),'PUT',{enabled:!v});refresh();});
          return cell;
        }],['','id',(_,r)=>{if(sample)return '';const wrap=document.createElement('div');button(wrap,'Изменить',()=>edit(r));return wrap;}]];
      const matches=add(box,'div');
      function render(){
        const term=filter.value.trim().toLocaleLowerCase('ru');
        const filtered=rows(items).filter(r=>[r.id,r.reason,describe(r.when,classes),describe(r.offer,classes)].join(' ').toLocaleLowerCase('ru').includes(term));
        matches.replaceChildren();table(matches,filtered,columns,{limit:20});
      }
      filter.oninput=render;render();
    });
  }
  refresh();
}
