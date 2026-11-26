import {caption,setMeta} from './labels.js';
import {moneyRate,add,line,rows,num,link} from './dom.js';
import {api} from './api.js';
const pipeline=[
 ['Нормализация','Приводит строку к форме для поиска.'],['Точный артикул','Проверяет код поставщика.'],['Проверка написания','Исправляет раскладку и опечатки.'],
 ['Сущности и параметры','Выделяет продукт, количество и срок.'],['Контекст клиента','Учитывает покупки и предыдущий запрос.'],['Сценарий запроса','Определяет задачу покупателя.'],
 ['План поиска','Выбирает способ собрать ответ.'],['Отбор кандидатов','Находит близкие товары.'],['Проверка ограничений','Отбирает подходящие предложения.'],
 ['Выбор лицензии','Сопоставляет варианты и считает стоимость.'],['Проверка категоризатором','Проверяет релевантность кандидатов.'],['Порядок карточек','Применяет коммерческие веса внутри уровня.'],
 ['Правила магазина','Учитывает закрепления и исключения.'],['Сборка ответа','Собирает блоки, чипы и фасеты.'],['Журнал и стоимость','Сохраняет результат и расходы.']
];
export async function about(main){
  document.title='О решении · Кузница Softline';add(main,'h1','Как устроен поиск');
  link(main,'Как работает поиск · схемы по видам запроса','/flows');
  link(main,'Документы проекта','/docs');
  const section=title=>{const p=add(main,'section',null,'panel');add(p,'h2',title);return p;};
  const roles=section('Кому помогает');
  for(const [who,what] of [['Клиент','Находит нужную лицензию с первого запроса.'],['Менеджер e-com','Видит, где теряются заказы, и управляет выдачей правилами.'],['Продукт-менеджер','Следит за спросом и его изменениями.'],['Контент-менеджер','Находит недостающие товары и поля карточек.'],['Руководитель e-com','Оценивает эффект в заказах и деньгах.']]){
    const row=add(roles,'p');add(row,'strong',who+' · ');row.append(what);
  }
  const steps=add(section('Что происходит с запросом'),'ol',null,'pipeline');
  for(const [title,text] of pipeline){const li=add(steps,'li');add(li,'strong',title);line(li,text);}
  const groups=section('Какие запросы понимает');
  line(section('Почему поиск не выдумывает'),'Движок передаёт Jev закрытый список сценариев, категорий, готовых ответов или оценок кандидата. Товары, цены и условия берутся из каталога. При недоступности сервиса или исчерпании бюджета поиск переходит в быстрый режим и отмечает это в трассе.');
  const rank=section('Порядок выдачи');line(rank,'Поиск распределяет кандидатов по четырём уровням релевантности. Популярность, маржа и профиль влияют на порядок внутри уровня. Карточки верхнего уровня сохраняют приоритет.');
  const tech=section('Модели и библиотеки'), t=add(tech,'table');
  const h=add(t,'tr');['Название','Зачем','Лицензия'].forEach(v=>add(h,'th',v));
  for(const row of [['FastAPI, Uvicorn','Веб-сервис','MIT, BSD'],['pydantic','Схемы','MIT'],['NumPy, SciPy','Векторы','BSD'],['scikit-learn','Текстовые признаки','BSD'],['RapidFuzz','Близкие написания','MIT'],['pymorphy3','Морфология русского языка','MIT'],['fastembed, ONNX Runtime','Локальная модель','Apache 2.0, MIT'],['Локальная модель векторов','Смысловая близость','Apache 2.0'],['SQLite','Журнал','Общественное достояние'],['Jev через OpenRouter','Категоризатор','Внешний платный сервис']]){
    const tr=add(t,'tr');row.forEach(v=>add(tr,'td',v));
  }
  const cost=section('Стоимость запроса'), quality=section('Качество на проверочном наборе');
  line(section('Данные стенда'),'Адаптер загружает предложения и цены из фида магазина. В разделе «Данные» консоли можно посмотреть состав каталога, историю и отчёт импорта.');
  const [meta,health,c,e]=await Promise.all(['/api/meta','/health','/api/admin/cost','/api/admin/eval'].map(url=>api(url).catch(()=>null)));
  setMeta(meta || {});
  const examples=new Map();
  for(const s of rows(meta?.scenarios)){
    const q=s.demo?.q || s.demo?.chain?.[0] || s.examples?.[0];
    if(s.intent && q && !examples.has(s.intent))examples.set(s.intent,{q,profile:s.demo?.profile || 'guest'});
  }
  const gallery=add(groups,'div',null,'intentGallery');
  for(const [intent,{q,profile}] of examples){
    const item=add(gallery,'article');add(item,'strong',caption('intent',intent));
    link(item,q,'/?'+new URLSearchParams({q,profile,mode:'smart'}));
  }
  if(health?.version)line(tech,'Версия сервиса · '+health.version);
  for(const [key,value] of Object.entries({...meta?.versions,...health?.versions,...meta?.models,...health?.models})){
    const description=typeof value==='string'?value:[value?.name || value?.model || value?.id,value?.version].filter(Boolean).join(' · ');
    if(description)line(tech,caption('',key)+' · '+description);
  }
  if(health?.llm?.model)line(tech,'Категоризатор · '+health.llm.model);
  const counts=new Map();for(const s of rows(meta?.scenarios))counts.set(s.group_title,(counts.get(s.group_title)||0)+1);
  for(const [name,n] of counts)line(groups,name+' · '+num(n),'chip','span');link(groups,'Открыть галерею →','/scenarios');
  if(health?.llm)line(tech,'Внешняя модель '+(health.llm.enabled?'включена':'отключена'));
  const values=rows(c?.items).filter(x=>x.requests && x.mode!=='fast');
  const pending=p=>{add(p,'p','Ожидаются данные').dataset.pending='';};
  if(values.some(x=>x.rub_per_query>0) || (values.length && c.cache_rate>0))for(const x of values)line(cost,(x.mode==='smart_cached'?'Умный с кэшем':'Умный без кэша')+' · '+moneyRate(x.rub_per_query,x.rub_per_1000));else pending(cost);
  const stats=Object.values(e?.scenarios || {}),total=stats.reduce((n,r)=>n+r.total,0);
  if(total)line(quality,'Пройдено '+num(stats.reduce((n,r)=>n+r.passed,0))+' из '+num(total));else pending(quality);
}
