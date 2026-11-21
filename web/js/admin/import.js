import {add,line,rows,details} from '../dom.js';
import {caption} from '../labels.js';
import {section,loadBox,adminApi,date,fmt,pct,rub,tile,table} from './common.js';
import {bar} from './charts.js';

export function catalogImport(parent){
  loadBox(section(parent,'Импорт каталога'),async p=>{
    const c=(await adminApi('ingest')).catalog;
    if(!c){line(p,'Отчёт импорта появится после загрузки каталога.');add(p,'code','python -m kuznitsa.cli import-catalog <файл>');return;}
    line(p,[c.ts?date(c.ts)+' МСК':'',...rows(c.files).map(f=>String(f).split(/[\\/]/).at(-1))].filter(Boolean).join(' · '),'muted');
    const tiles=add(p,'div',null,'adminTiles');
    for(const [key,title] of [['rows','Входные строки'],['offers','Предложения'],['rejected','Отклонено'],['duplicates','Дубли']])
      if(c[key]!=null)tile(tiles,title,fmt(c[key]));
    const parts={vendor:'Вендор',family:'Семейство',edition:'Редакция',licence:'Условия лицензии',category:'Категория'};
    for(const [key,value] of Object.entries(c.recognized || {})){
      if(value==null)continue;
      line(p,(parts[key] || caption('',key))+' · '+pct(value));bar(p,value,1,'#087969');
    }
    const auto=Object.entries(c.auto || {}).map(([key,n])=>(({vendors:'Вендоры',categories:'Категории',families:'Семейства'})[key] || caption('',key))+' · '+fmt(n));
    if(auto.length)line(p,'Добавлено в базу знаний · '+auto.join(' / '));
    if(rows(c.issues).length)table(p,c.issues,[['Замечание','title',(v,r)=>v || caption('',r.code)],['Количество','count'],['Примеры строк','examples',items=>rows(items).map(i=>[i.row,i.name].filter(x=>x!=null).join(' · ')).join(', ')]]);
    for(const [key,title] of [['vendors','Нераспознанные вендоры'],['families','Нераспознанные семейства']]){
      if(rows(c.unmatched?.[key]).length)table(details(p,title),c.unmatched[key],[['Название','name'],['Строки','rows']]);
    }
  });
}

export function dataPage(p){
  loadBox(section(p,'Загруженные данные'),async box=>{
    const d=await adminApi('ingest'),tiles=add(box,'div',null,'adminTiles');
    if(d.cards!=null)tile(tiles,'Карточки каталога',fmt(d.cards));
    if(d.offers!=null)tile(tiles,'Предложения',fmt(d.offers));
    const history=rows(d.sources).find(s=>s.source==='history');
    if(history)tile(tiles,'Поиски в истории',fmt(history.searches));
    const reports=rows(d.history);
    add(box,'h3','История поиска и Метрика');
    if(!reports.length)line(box,'Отчётов загрузки истории и Метрики пока нет.');
    for(const r of reports){
      const metrika=r.logs || rows(r.recognized).some(field=>String(field).startsWith('ym:'));
      const report=details(box,[r.source_type || (metrika?'Метрика':'История поиска'),r.file].filter(Boolean).join(' · '));
      if(r.kind==='metrika_external_phrases'){
        table(report,r.external_phrases,[['Фраза привлечения','q'],['Визиты','visits']]);
      }
      if(r.crm)line(report,'Заявок связано с поиском · '+fmt(r.crm.linked)+'. Ожидают привязки · '+fmt(r.crm.unlinked));
      for(const [key,title] of Object.entries({visits:'Визиты',searches:'Поиски',events:'События',skipped:'Пропущено',duplicates:'Дубли'})){
        if(r[key]!=null)line(report,title+' · '+fmt(r[key]));
      }
      rows(r.missing).forEach(message=>line(report,message));
    }
  });
  catalogImport(p);review(p);
}
export function review(p){
  loadBox(section(p,'Проверка раскладки каталога'),async box=>{
    const d=await adminApi('ingest'),ai=d.catalog?.ai;
    if(ai){
      const cost=ai.cost_rub ?? ai.rub ?? (ai.usd===0?0:null);
      if(cost!=null)line(box,'Цена раскладки · '+rub(cost),'roleLead');
      else if(typeof ai.usd==='number'){
        const rate=(await adminApi('cost')).usd_rub;
        if(typeof rate==='number')line(box,'Цена раскладки · '+rub(ai.usd*rate),'roleLead');
      }
      line(box,[ai.sent==null?'':'Внешние вызовы · '+fmt(ai.sent),ai.cached==null?'':'Из кэша · '+fmt(ai.cached)].filter(Boolean).join(' / '));
    }
    if(!rows(d.review).length){line(box,'В очереди пока нет решений для проверки.');return;}
    table(box,d.review,[['Объект','object',v=>caption('family',Array.isArray(v)?v.join(' / '):v)],['Поле','question',v=>({category:'Категория',parent:'Раздел',analogs:'Аналоги',roles:'Роли',industries:'Отрасли'})[v] || caption('',v)],
      ['Решение','choice',(v,r)=>r.options?.[v] || caption(r.question,Array.isArray(v)?v.join(', '):v)],['Вероятность','probability',pct]]);
  });
}
