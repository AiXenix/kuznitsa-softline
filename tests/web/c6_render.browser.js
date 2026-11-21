import {result} from './store/result.js';
import {trace} from './store/trace.js';

import {renderMarkdown} from './store/documents.js';
import {diagram} from './store/diagram.js';

const main=document.querySelector('main'),report=document.querySelector('output');
const fixture=JSON.parse(document.querySelector('#fixtures').textContent);
function check(ok,message){if(!ok)throw Error(message);}
try{
  for(const [source,title] of [['jev','уточнено умным режимом'],['dict','по словарю']]){
    main.replaceChildren();fixture.understood.refined.source=source;
    let patch;result(main,fixture,{apply:v=>{patch=v;}});
    const chips=main.querySelectorAll('.understood button');
    check(chips.length===1 && chips[0].textContent.includes('Понято: для дома') && chips[0].title===title,'Метка назначения');
    chips[0].click();
    check(JSON.stringify(patch)===JSON.stringify({ignore:['refined']}),'Снятие уточнения');
    const info=main.querySelector('.availabilityNote'),faq=info.querySelector('a');
    check(info.textContent.includes(fixture.blocks[0].text) && new URL(faq.href).searchParams.get('q')===fixture.blocks[2].links[0].q,'Условия и вопрос FAQ');
    check(info.compareDocumentPosition(main.querySelector('.product')) & Node.DOCUMENT_POSITION_FOLLOWING,'Пояснение до карточки');
  }
  for(const pending of [true,false]){
    main.replaceChildren();trace(main,{
      cost:{rub:0,pending},blocks:[{type:'products',items:[{card_id:'k',title:'Редакция А'}]}],
      trace:[{step:'business',detail:{priorities:[{title:'Приоритет клиник',matched:4,moved:2}],moves:[{card_id:'k',before:3,after:1}]}},
        {step:'log',summary:'устаревшая стоимость',status:'ok'}]},false);
    check(main.textContent.includes('Приоритет клиник') && main.textContent.includes('Редакция А · 3 → 1'),'Приоритеты и позиции');
    const log=main.querySelector('li:last-child .stepFull');
    check(log?.textContent.includes(pending?'Цена уточняется':'0 ₽') && !log.textContent.includes('устаревшая'),'Итоговая стоимость');
  }
  main.replaceChildren();
  renderMarkdown(main,[
    '# Руководство','<a id="sku"></a>','[По артикулу](#sku)','- Список','  - Вложенная строка',
    '| Вид | Шаг |','| --- | --- |','| Код | Проверка |','`'.repeat(3),'строка кода','`'.repeat(3),
    '`'.repeat(3)+'mermaid','flowchart TD','a["Запрос"]','b{"Чей запрос?"}','a -->|выбор| b','`'.repeat(3),
    '<img src=x onerror="throw Error()">'
  ].join('\n'));
  check(main.querySelector('h1').textContent==='Руководство' && main.querySelector('a#sku') &&
    main.querySelector('a[href$="#sku"]') && main.querySelector('li li') && main.querySelector('table td') &&
    main.querySelector('pre code') && !main.querySelector('img'),'Markdown и якоря');
  check(main.querySelectorAll('.juryGraph g').length===2 && main.querySelector('.edgeLabel').textContent.includes('выбор'),'Ветвь Mermaid');
  const graph=diagram(main,{title:'Ветвление',nodes:[{id:'a',title:'Очень длинное название шага поиска для проверки переноса',step:'intent'},
    {id:'b',title:'Первый'},{id:'c',title:'Второй'}],edges:[{from:'a',to:'b',label:'да'},{from:'a',to:'c',label:'иначе'}]},
    {intent:{p50:1,p95:5}});
  const [a,b,c]=graph.querySelectorAll('g');
  check(a.querySelectorAll('.nodeTitle').length>1 && a.querySelector('.nodeTime').textContent.includes('p95 5'),'Перенос и время');
  check(b.querySelector('rect').getAttribute('x')!==c.querySelector('rect').getAttribute('x'),'Раздельные колонки');
  report.textContent='passed';
}catch(e){report.textContent=e.stack;}
