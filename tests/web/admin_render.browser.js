import {consolePage} from './admin/index.js';
import {inspector} from './admin/inspect.js';
import {resetData} from './admin/common.js';

const fixtures=JSON.parse(document.querySelector('#fixtures').textContent);
const main=document.querySelector('main'),status=document.querySelector('output');
const tick=()=>new Promise(resolve=>setTimeout(resolve,20));
let sparse=false, newer=false;
const hits=new Map();
window.fetch=async path=>{
  const url=new URL(path,'https://example.invalid'), name=url.pathname.split('/')[3];
  hits.set(path,(hits.get(path) || 0)+1);
  if(url.pathname.endsWith('/history-days'))return new Response(JSON.stringify({items:[{key:'2026-11-20',searches:2,zero_rate:0}]}));
  if(name==='digest')return Response.json({role:url.searchParams.get('role')});
  const kind=url.searchParams.get('kind');
  if(name==='queries' && kind==='recent' && newer)return new Response(JSON.stringify({items:[{search_id:hits.get(path)>1?'next-live-id':'recent-id',q:'Недавний запрос',n_cards:0,mode:'naive',intent:'role_kit',cost_rub:.00954284,zero_reason:'unknown_term'}]}));
  if(name==='queries' && kind==='recent')return new Response('{}',{status:422});
  const key=name==='queries'?'queries-'+kind:name==='replay'?'replay-result':name;
  if(!(key in fixtures))throw Error('Unexpected endpoint '+path);
  const payload=sparse?{items:null,tiles:[],totals:{behavioral_searches:0},slices:null,comparison:{searches:0,before_zero:0},pairs:null,scenarios:null,sources:null}:fixtures[key];
  return new Response(JSON.stringify(payload));
};
try{
  fixtures['replay-result'].recovered=731267;
  consolePage(main);
  for(const mode of [false,true]){
    sparse=mode;resetData();
    for(const tab of ['head','ecom','product','content','agent','log']){
      location.hash=tab;await tick();await tick();
      const text=main.innerText;
      if(!main.querySelector('.adminPanel') || /NaN|undefined|Infinity|Нет связи|HTTP 5/.test(text))throw Error(tab+' · '+text.slice(-300));
      if(!mode && tab==='head' && !text.replace(/\s+/g,'').includes('731267'))throw Error('Recovered count differs from API');
      if(!mode && tab==='agent' && !text.includes('Было → стало'))throw Error('Missing verification');
    }
  }
  sparse=false;newer=true;resetData();
  fixtures.kpi.pairs=[{key:'target',label:'Показатель B2',unit:'ms',before:12.5,after:11,better:'lower',n_before:37,n_after:36,scope_text:'Парные наблюдения',tone:'good',delta_text:'Сокращение задержки',before_label:'Исходная выборка'}];
  fixtures.kpi.note='Общее пояснение к выборке';
  fixtures.kpi.funnel=[{key:'cart',label:'Добавили в корзину',count:79}];
  fixtures.ingest.catalog={ts:'2026-11-20',files:['пример.csv'],rows:65,offers:60,rejected:3,duplicates:2,recognized:{vendor:.75},auto:{vendors:2},issues:[{title:'Нет цены',count:3,examples:[{row:21,name:'Лицензия'}]}],unmatched:{families:[{name:'Новая программа',rows:5}]}};
  fixtures.ingest.history=[
    {file:'phrases.csv',source_type:'Внешний поиск',kind:'metrika_external_phrases',external_phrases:[{q:'антивирус для офиса',visits:17}]},
    {file:'leads.csv',source_type:'CRM',crm:{linked:0,unlinked:3}},
    {file:'old.csv',recognized:['ym:s:visits']}
  ];
  fixtures.ingest.review=[{object:'Образец',question:'category',probability:.42,choice:'office',options:{office:'Офисные лицензии'}}];
  fixtures.ingest.catalog.ai={cost_rub:73.56,cached:5};
  fixtures.insights.items[0].evidence_text='Проверены сессии закупки';
  fixtures.insights.items[0].impact_text='Эффект за квартал';
  fixtures.insights.items[0].confidence=null;
  fixtures.failures.items=[{reason:'unknown_term',count:2,example:{q:'Термин',search_id:'failure-own'}}];
  fixtures.gaps.items=[{title:'Семейство',queries:[{q:'Фраза',search_id:'gap-own'}]}];
  fixtures.insights.items[0].evidence={sample_queries:[{q:'Синоним',search_id:'agent-own'}]};
  fixtures.cost={items:[{mode:'smart',rub_per_query:0.0095,monthly_rub:35,rub_per_100000:950}],sent:4,cached:7};
  hits.clear();
  location.hash='head';await tick();if(!main.innerText.includes('Показатель B2'))throw Error('B2 pairs missing');
  if(!main.innerText.includes('Сокращение задержки') || !main.innerText.includes('Исходная выборка') || !main.querySelector('.delta.good') || !main.innerText.includes('Парные наблюдения'))throw Error('Pair units or evidence missing');
  if(!main.innerText.includes('Внешние вызовы · 4') || !main.innerText.includes('950 ₽'))throw Error('Cost report');
  const comparison=main.querySelector('.comparisonTiles').parentElement;
  const basis=comparison.querySelector('details');
  if(basis.open || comparison.querySelector('.pair').textContent.includes('Парные наблюдения'))throw Error('Пояснение повторилось в плитке');
  basis.querySelector('summary').click();
  if(main.innerText.split(fixtures.kpi.note).length!==2)throw Error('Общее пояснение должно быть одно');
  main.querySelector('.keyBox .download').click();await tick();
  if(!hits.has('/api/admin/digest?role=head_ecom&format=xlsx') || !main.querySelector('.keyBox').innerText.includes('Выгрузка XLSX пока недоступна'))throw Error('Загрузка отчёта роли и ответ прежнего API');
  location.hash='agent';await tick();
  const checked=[...main.querySelectorAll('.finding')].find(el=>el.innerText.includes('Эффект за квартал'));
  if(!checked?.innerText.includes('Проверены сессии закупки') || checked.querySelector('.confidence'))throw Error('Готовые строки предложения и пустая уверенность');
  if(!main.querySelector('a[href="/inspect/agent-own"]'))throw Error('Agent example');
  location.hash='ecom';await tick();if(!main.querySelector('a[href="/inspect/failure-own"]'))throw Error('Failure example');
  if(!main.innerText.includes('Добавили в корзину') || hits.get('/api/admin/kpi')!==1)throw Error('Funnel or shared cache');
  location.hash='content';await tick();
  if(!main.querySelector('a[href="/inspect/gap-own"]'))throw Error('Gap example');
  for(const term of ['пример.csv','Нет цены','21 · Лицензия','Новая программа'])if(!main.textContent.includes(term))throw Error('Catalog: '+term);
  location.hash='data';await tick();
  if(!main.innerText.includes('73,56 ₽') || !main.innerText.includes('Офисные лицензии'))throw Error('Import costs or review missing');
  const reportByTitle=title=>[...main.querySelectorAll('details')].find(d=>d.querySelector('summary')?.textContent===title);
  const phrases=reportByTitle('Внешний поиск · phrases.csv')?.querySelector('tbody tr');
  if(phrases?.cells[0]?.textContent!=='антивирус для офиса' || phrases.cells[1]?.textContent!=='17')throw Error('Фразы привлечения и визиты');
  if(!reportByTitle('CRM · leads.csv')?.textContent.includes('Заявок связано с поиском · 0. Ожидают привязки · 3') || !reportByTitle('Метрика · old.csv'))throw Error('CRM и старые отчёты импорта');
  location.hash='log';await tick();if(!main.querySelector('a[href="/inspect/recent-id"]'))throw Error('Recent missing');
  if(!main.innerText.includes('Обычный поиск по словам') || !main.innerText.includes('Незнакомый термин') || !hits.has('/api/admin/queries?kind=recent&limit=50'))throw Error('Recent columns or URL');
  const poll=main.querySelector('.pollControl input');poll.click();
  await new Promise(resolve=>setTimeout(resolve,5100));
  if(!main.querySelector('a[href="/inspect/next-live-id"]') || hits.get('/api/admin/queries?kind=recent&limit=50')!==2)throw Error('Recent poll');
  poll.click();
  resetData();main.replaceChildren();inspector(main);await tick();
  if(!main.querySelector('.steps details[open]') || !main.querySelector('.catalogCard'))throw Error('Inspector missing trace or cards');
  status.textContent='passed';
}catch(e){status.textContent=e.message;}
