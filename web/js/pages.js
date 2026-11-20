import {api} from './api.js';
import {add,line,rows,label,details,link,num,money,stateBox} from './dom.js';
import {result} from './result.js';
import {trace} from './trace.js';

function heading(main,title) {
  document.title=title+' · Кузница Softline';
  add(main,'h1',title);
}
function pending(p,title) {
  const x=add(p,'p',title+' · ожидаются данные','muted');
  x.dataset.pending='';
}
async function gallery(main) {
  heading(main,'Галерея сценариев');
  const form=add(main,'div',null,'settings panel');
  const input=add(add(form,'label','Поиск по галерее'),'input');input.type='search';input.placeholder='Название или пример запроса';
  const select=add(add(form,'label','Группа'),'select');select.add(new Option('Все группы',''));
  const status=add(main,'p',null,'muted');status.setAttribute('role','status');
  const container=add(main,'div');
  const meta=await api('/api/meta'), all=rows(meta.scenarios);
  const checks=new Map();
  const groups=new Map(all.map(s=>[s.group || '',s.group_title || 'Другие сценарии']));
  for(const [id,title] of groups) if(id) select.add(new Option(title,id));
  function show() {
    container.replaceChildren();const found=all.filter(s=>(!select.value || s.group===select.value) &&
      [s.title,s.group_title,s.demo?.q,...rows(s.examples)].join(' ').toLowerCase().includes(input.value.trim().toLowerCase()));
    status.textContent='Сценариев в подборке · '+num(found.length);
    if(!found.length)stateBox(container,'По вашему запросу сценариев нет.');
    for(const [id,title] of groups) {
      const matches=found.filter(s=>(s.group || '')===id);
      if(!matches.length)continue;
      add(container,'h2',title);const grid=add(container,'div',null,'gallery');
      for(const s of matches) {
        const box=add(grid,'article',null,'product');
        add(box,'h3',s.title);line(box,s.user_goal,'muted');
        const examples=rows(s.examples),base='/?scenario='+encodeURIComponent(s.id);
        const first=s.demo?.q || s.demo?.chain?.[0] || examples[0];
        if(first) link(box,first,base);
        if(examples.some(q=>q!==first)){
          const d=details(box,'Другие примеры');
          for(const q of examples.filter(q=>q!==first)) link(d,q,base+'&q='+encodeURIComponent(q));
        }
        if(s.demo?.admin_tab) link(box,'К аналитике','/admin');
        const st=s.eval_status ?? checks.get(s.id) ?? s.status;
        if(st)line(box,'Проверка · '+label(st),'muted');else pending(box,'Статус проверки');
      }
    }
  }
  input.oninput=select.onchange=show;show();
  try {
    const report=await api('/api/admin/eval');
    for (const row of rows(report?.rows || report?.results || report)) {
      if (row.scenario && row.status) checks.set(row.scenario,row.status);
    }
    if(checks.size) show();
  } catch { /* Метаданные галереи доступны независимо от журнала проверок. */ }
}
async function inspect(main) {
  heading(main,'Разбор запроса');
  const id=location.pathname.split('/').pop();
  try {
    const data=await api('/api/admin/search/'+id);
    const r=data.response || data.result || data.search || data;
    if (!r.trace && r.trace_json) r.trace=typeof r.trace_json==='string' ? JSON.parse(r.trace_json) : r.trace_json;
    if (!r.timing_ms && r.ms!=null) r.timing_ms={total:r.ms};
    if (!r.cost && (r.llm_calls!=null || r.llm_cost_usd!=null)) r.cost={llm_calls:r.llm_calls,usd:r.llm_cost_usd};
    line(main,r.query?.raw || r.q_raw,null,'h2');
    if(r.blocks || r.understood) result(main,r);
    const t=add(main,'section',null,'trace');add(t,'h2','Как работал поиск');trace(t,r,false);
    add(details(main,'Полная запись журнала'),'pre',JSON.stringify(data,null,2));
  } catch {stateBox(main,'Запись недоступна. Возможно, запрос отсутствует в журнале или доступ к журналу закрыт.');}
}
async function about(main) {
  heading(main,'Как устроен поиск');
  const grid=add(main,'div',null,'gallery');
  for(const [title,copy] of [
    ['Понимание запроса','Поиск распознаёт продукт, действие с лицензией, количество и ограничения. Словари связывают названия с жаргоном и сокращениями.'],
    ['Подбор лицензии','Индекс находит кандидатов по словам и смыслу. Фильтры учитывают платформу и аудиторию, а варианты одной редакции собираются в карточку.'],
    ['Порядок выдачи','Внутри уровня релевантности порядок зависит от популярности, маржи и профиля. Вклад каждого фактора виден в карточке.']
  ]){const p=add(grid,'article',null,'panel');add(p,'h2',title);line(p,copy);}
  const tech=add(main,'section',null,'panel');add(tech,'h2','Модели и библиотеки');
  line(tech,'Локальная модель multilingual MiniLM сопоставляет запросы по смыслу. В умном режиме предусмотрен категоризатор Jev через OpenRouter. Быстрый режим работает локально.');
  line(tech,'FastAPI обслуживает запросы, RapidFuzz находит близкие написания, scikit-learn строит текстовые признаки, fastembed и ONNX Runtime выполняют локальную модель. Журнал хранится в SQLite.');
  line(tech,'FastAPI, RapidFuzz и ONNX Runtime — MIT, scikit-learn — BSD, fastembed и multilingual MiniLM — Apache License. Jev доступен как внешний сервис.');
  try {
    const health=await api('/health');
    if(typeof health.llm?.enabled==='boolean')line(tech,health.llm.enabled?'Обращения к внешней модели включены.':'Внешняя модель сейчас отключена.','badge','span');
  }catch{pending(tech,'Состояние моделей');}
  const p=add(main,'section',null,'panel');add(p,'h2','Стоимость запроса');
  line(p,'Трасса каждого поиска показывает его время, число обращений к модели и стоимость.');
  try {
    const cost=await api('/api/admin/cost');
    if(cost.avg_rub != null)line(p,'В среднем за запрос · '+money(cost.avg_rub),'price');
    else if(cost.avg_usd != null)line(p,'В среднем за запрос · '+num(cost.avg_usd)+' $','price');
    else pending(p,'Средняя стоимость');
  }catch{pending(p,'Средняя стоимость');}
}
async function styleguide(main) {
  heading(main,'Образцы интерфейса');
  line(main,'Примеры ответов из локальных файлов. Покупки и запросы в журнал не записываются.');
  const files=await api('/web/fixtures/index.json');
  const examples=await Promise.all(files.map(f=>api('/web/fixtures/'+f+'.json')));
  const nav=add(main,'nav',null,'chips');nav.setAttribute('aria-label','Образцы блоков');
  for(const [i,r] of examples.entries()){
    const b=rows(r.blocks)[0], id=files[i];
    link(nav,b?.title || id,'#'+id);
    const s=add(main,'section');s.id=id;
    result(s,r,{apply:()=>{},act:(_t,_c,b)=>{b.textContent='Демонстрационный образец';}});
    if(r.trace){const t=add(s,'section',null,'trace');add(t,'h2','Как работал поиск');trace(t,r,false);}
  }
  add(main,'h2','Состояния выдачи');
  const states=await api('/web/fixtures/states.json');
  for(const [kind,text] of Object.entries(states))stateBox(main,text,kind);
}
export async function page(main) {
  switch(location.pathname) {
    case '/scenarios':return gallery(main);
    case '/about':return about(main);
    case '/styleguide':return styleguide(main);
    case '/admin':heading(main,'Аналитика поиска');stateBox(main,'Консоль появится после подключения служебного API. Разбор отдельного поиска доступен из трассы на витрине.');return;
    default:return inspect(main);
  }
}
