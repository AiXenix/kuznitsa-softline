import {add,line,rows,details} from '../dom.js';
import {caption} from '../labels.js';
import {section,loadBox,adminApi,date,fmt,pct,tile,table} from './common.js';
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
