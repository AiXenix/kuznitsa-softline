import {add,line,details,rows,num,money,moneyRate,link} from './dom.js';
import {caption,readable} from './labels.js';

const keys={kind:'Назначение',tokens_in:'Входные токены',tokens_out:'Выходные токены',ok:'Вызов успешен',model:'Модель',phrase:'Фраза',to:'Замена',redirect:'Перенаправление',rule_id:'Правило',calls:'Обращения к модели',weights:'Веса',rel:'Релевантность',pop:'Популярность',margin:'Маржа',pers:'Персонализация',sources:'Источники',ignored:'Снятые условия',synonyms:'Синонимы',residual:'Остаток запроса',fired:'Применённые правила',sent:'Отправлено',cached:'Из кэша',ms:'Время, мс',rub:'Цена',note:'Пояснение'};
const statuses={ok:'Готово',skip:'Пропущен',fallback:'Запасной путь',error:'Ошибка'};
function entries(obj){
  if(!obj || typeof obj!=='object')return [];
  return Object.entries(obj).filter(([k,v])=>!k.includes('usd') && v!=null && v!=='' && (typeof v!=='object' || entries(v).length));
}
function describe(p,obj){
  for(const [k,v] of entries(obj)){
    if(k==='rule_id' || k==='search_id')continue;
    const title=keys[k] || caption('',k);
    if(typeof v==='object'){
      const group=add(p,'div',null,'detailGroup');if(!/^\d+$/.test(k))line(group,title,null,'b');
      describe(group,v);
    }else line(p,(/^\d+$/.test(k)?'':title+' · ')+(typeof v==='boolean'?(v?'Да':'Нет'):k==='rub'?moneyRate(v):k==='source'?caption('source',v):readable(v)));
  }
}
function businessDetails(p,detail,blocks){
  const {priorities,moves,...other}=detail;
  if(rows(priorities).length){
    line(p,'Применённые приоритеты',null,'b');
    const list=add(p,'ul');
    for(const rule of priorities){
      const counts=[rule.matched!=null?'подошло карточек: '+num(rule.matched):'',rule.moved!=null?'сменили позицию: '+num(rule.moved):''].filter(Boolean);
      line(list,[rule.title || 'Правило магазина',...counts].join(' · '),null,'li');
    }
  }
  if(rows(moves).length){
    const titles=new Map();
    for(const block of rows(blocks))for(const item of rows(block.items)){
      const card=item.card || item;titles.set(card.card_id,card.title);
    }
    line(p,'Изменения позиций',null,'b');
    const list=add(p,'ul');
    for(const move of moves){
      if(move.before==null || move.after==null)continue;
      line(list,(titles.get(move.card_id) || move.title || 'Карточка '+move.card_id)+' · '+move.before+' → '+move.after,null,'li');
    }
  }
  describe(p,other);
}
export function trace(p,r,inspect=true){
  const stats=add(p,'div',null,'traceStats');
  const c=r.cost || {}, sent=c.llm_calls ?? c.sent, cached=c.cached ?? 0;
  const total=(sent ?? 0)+cached;
  const ending={one:'ответ',few:'ответа',many:'ответов',other:'ответа'}[new Intl.PluralRules('ru').select(total)];
  const cachedText=cached===2 && total===2?'оба из кэша':'из кэша '+num(cached);
  const stopped=rows(r.trace).some(s=>s.status==='fallback');
  const model=total?num(total)+' '+ending+(cached?', '+cachedText:''):
    stopped?'запасной путь':r.mode==='naive'?'поиск по словам':'не понадобился · решено правилами';
  line(stats,r.timing_ms?.total==null?'':'Поиск · '+num(r.timing_ms.total)+' мс',null,'strong');
  if(sent!=null || c.cached!=null)line(stats,'Категоризатор: '+model);
  if(c.pending)line(stats,'Цена уточняется');
  else if(c.rub!=null)line(stats,'Цена: '+moneyRate(c.rub)+(cached>0 && c.saved_rub!=null?' · без кэша '+money(c.saved_rub):''));
  const ol=add(p,'ol',null,'steps');
  for(const s of rows(r.trace)){
    const calls=rows(s.detail?.calls).filter(x=>x.sent || x.cached);
    const li=add(ol,'li',null,s.status);
    if(calls.length || s.changed || s.detail?.fired?.length || s.detail?.synonyms?.length || s.detail?.redirect || (s.step==='sku_lookup' && r.understood?.intent==='sku') || (s.step==='repair' && r.query?.corrections?.length))li.classList.add('changed');
    const d=details(li,''), header=d.firstChild;
    const title=s.title || caption('',s.step) || 'Шаг';
    const logPrice=s.step==='log' && (c.pending?'Цена уточняется':money(c.rub));
    const summary=logPrice?'Записан в журнал · '+logPrice:String(readable(s.summary) || statuses[s.status] || '');
    const titleNode=add(header,'b',title);titleNode.title=title;
    const count=summary.match(/ · (\d+)$/)?.[1];
    const concise={sku_lookup:summary.includes('нет')?'Совпадений нет':summary,retrieve:count && ('Найдено · '+count),
      variants:count && ('Подобрано · '+count),compose:count && ('Карточек · '+count),
      context:r.profile?.short || r.profile?.title?.split(/ [—–] /)[0],log:logPrice || 'Записан в журнал'};
    const brief=add(header,'span',calls.length?'◆ '+(calls.every(x=>x.cached)?'Из кэша':'Категоризатор'):concise[s.step] || summary.split(/\s+/).slice(0,5).join(' '),'stepBrief');
    brief.title=summary;
    const full=add(header,'span',summary,'stepFull');full.title=summary;
    line(header,s.ms==null?'':num(s.ms)+' мс','stepTime','small');
    line(d,summary);
    line(d,statuses[s.status],'stepStatus','small');
    for(const call of calls)line(d,['Категоризатор',call.cached?'из кэша':'',call.ms==null?'':num(call.ms)+' мс',money(call.rub)].filter(Boolean).join(' · '),'badge','span');
    if(typeof s.detail==='string')line(d,readable(s.detail));
    if(entries(s.detail).length){
      if(s.step==='business')businessDetails(d,s.detail,r.blocks);
      else describe(d,s.detail);
      const raw=details(d,'Исходные данные');
      raw.ontoggle=()=>{if(raw.open && !raw.querySelector('pre'))add(raw,'pre',JSON.stringify(s.detail,null,2));};
    }
  }
  if(!ol.childElementCount)line(p,'Трасса для этого запроса недоступна.');
  if(inspect && r.search_id)link(p,'Открыть разбор запроса →','/inspect/'+encodeURIComponent(r.search_id));
}
