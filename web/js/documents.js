import {add,link,button} from './dom.js';
import {diagram} from './diagram.js';

const catalog={
  GUIDE:['Руководство','Как искать ПО, разбирать выдачу и работать с консолью.'],
  FLOWS:['Схемы поиска','Пути запроса, решения движка и измерения времени.'],
  DEMO:['Сценарий показа','Маршруты демонстрации для ведущего.'],
  PITCH:['Питч','Задача магазина и ценность решения.'],
  'QA-JURY':['Вопросы жюри','Ответы о качестве, данных и ограничениях.'],
  STACK:['Стек и цена','Библиотеки, модели и экономика запросов.'],
  'SEARCH-KINDS':['Виды поиска','Примеры запросов и ожидаемые результаты.'],
  INTEGRATION:['Встраивание','Подключение виджета к сайту партнёра.'],
  INGEST:['Приём данных','Подготовка и импорт каталога и истории.'],
  QUOTE:['Коммерческое предложение','Спецификация закупки и выгрузка расчёта.'],
  ADMIN_API:['API консоли','Маршруты, параметры и форматы ответов.'],
  'KB-REVIEW':['Проверка базы знаний','Полнота справочников и проверка связей.'],
  'README-ИТОГ':['Итог проекта','Сводка результатов и готовности решения.'],
  UI:['Интерфейс','Страницы и компоненты стенда.'],SCENARIOS:['Галерея сценариев','Примеры поисковых задач покупателей.']
};
function inline(p,text){
  const pattern=/(`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*|\[[^\]]+\]\([^\s)]+\)|<br\s*\/?>)/gi;
  let end=0;
  for(const m of text.matchAll(pattern)){
    p.append(text.slice(end,m.index));end=m.index+m[0].length;
    const t=m[0];
    if(t.startsWith('`'))add(p,'code',t.slice(1,-1));
    else if(t.startsWith('*')){const n=t.startsWith('**')?2:1;inline(add(p,n===2?'strong':'em'),t.slice(n,-n));}
    else if(t.startsWith('<'))add(p,'br');
    else{
      const [,label,href]=/^\[(.*)\]\((.*)\)$/.exec(t);
      const url=URL.parse(href,location.href);
      const internal=url?.origin===location.origin && (href.startsWith('#') || /^\/docs\/.+\.md$/u.test(url.pathname) || /^\/(?:flows|scenarios|admin|about|embed|)$/.test(url.pathname));
      if(internal || (url?.protocol==='https:' && url.origin!==location.origin))inline(link(p,'',url.href),label);
      else inline(add(p,'span'),label);
    }
  }
  p.append(text.slice(end));
}
function mermaid(p,source){
  const nodes=new Map(),edges=[];
  for(const row of source.split('\n')){
    const t=row.trim();if(!t || /^(flowchart|graph)\s/.test(t))continue;
    const node=/^([\w-]+)\s*(\[|\{)"(.*)"[\]}];?$/.exec(t);
    const edge=/^([\w-]+)\s*-->\s*(?:\|([^|]+)\|\s*)?([\w-]+);?$/.exec(t);
    if(node)nodes.set(node[1],{id:node[1],title:node[3],type:node[2]==='{'?'decision':'step'});
    else if(edge)edges.push({from:edge[1],to:edge[3],label:edge[2]});
    else return false;
  }
  if(!nodes.size || edges.some(e=>!nodes.has(e.from)||!nodes.has(e.to)))return false;
  diagram(p,{title:'Схема поиска',nodes:[...nodes.values()],edges});return true;
}
const item=/^(\s*)([-*]|\d+\.)\s+(.+)/;
function markdown(p,lines){
  const ids=new Map();
  const cells=t=>t.trim().replace(/^\||\|$/g,'').split(/(?<!\\)\|/).map(x=>x.trim().replace(/\\\|/g,'|'));
  for(let i=0;i<lines.length;){
    const t=lines[i++].trim();if(!t)continue;
    if(t.startsWith('```')){
      const code=[];while(i<lines.length && !lines[i].trim().startsWith('```'))code.push(lines[i++]);i++;
      if(t!=='```mermaid' || !mermaid(p,code.join('\n')))add(add(p,'pre'),'code',code.join('\n'));
    }else if(/^<a\s+id=["'][^"']+["']\s*>\s*<\/a>$/i.test(t))add(p,'a').id=t.split(/["']/)[1];
    else if(/^#{1,6}\s/.test(t)){
      const [,marks,name]=/^(#+)\s+(.+)/.exec(t),h=add(p,'h'+marks.length);inline(h,name);
      const slug=h.textContent.toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu,'').trim().replace(/\s+/g,'-');
      const n=ids.get(slug)||0;ids.set(slug,n+1);if(!document.getElementById(slug))h.id=n?slug+'-'+n:slug;else if(n)h.id=slug+'-'+n;
    }else if(t.includes('|') && /^\s*\|?\s*:?-{3,}/.test(lines[i] || '')){
      const table=add(add(p,'div',null,'docTable'),'table'),row=add(add(table,'thead'),'tr');
      cells(t).forEach(x=>inline(add(row,'th'),x));i++;
      const body=add(table,'tbody');while(i<lines.length && lines[i].includes('|') && lines[i].trim()){
        const r=add(body,'tr');cells(lines[i++]).forEach(x=>inline(add(r,'td'),x));
      }
    }else if(item.test(t)){
      i--;const stack=[];
      while(i<lines.length && item.test(lines[i])){
        const [,space,marker,body]=item.exec(lines[i++]),depth=space.length,kind=marker.endsWith('.')?'ol':'ul';
        while(stack.length && (stack.at(-1).depth>depth || (stack.at(-1).depth===depth && stack.at(-1).kind!==kind)))stack.pop();
        if(!stack.length || stack.at(-1).depth<depth){
          const list=add(stack.at(-1)?.last || p,kind);if(kind==='ol')list.start=parseInt(marker);
          stack.push({depth,kind,list});
        }
        const level=stack.at(-1);level.last=add(level.list,'li');inline(level.last,body);
      }
    }else if(t.startsWith('>')){
      const quote=[t.slice(1).trim()];while(lines[i]?.startsWith('>'))quote.push(lines[i++].slice(1).trim());
      markdown(add(p,'blockquote'),quote);
    }else if(/^---+$/.test(t))add(p,'hr');
    else{
      const parts=[t];
      while(i<lines.length && lines[i].trim() && !/^(?:#{1,6}\s|[-*]\s|\d+\.\s|>|~{3}|`{3}|<a\s|\||---+$)/i.test(lines[i].trim())){
        if(lines[i].includes('|') && /^\s*\|?\s*:?-{3,}/.test(lines[i+1] || ''))break;
        parts.push(lines[i++].trim());
      }
      inline(add(p,'p'),parts.join(' '));
    }
  }
}
export function renderMarkdown(parent,source){
  markdown(parent,source.split(/\r?\n/));
}

export async function documents(main){
  main.classList.add('documentPage');
  const name=decodeURIComponent(location.pathname.slice('/docs/'.length));
  document.title=(catalog[name.replace(/\.md$/,'')]?.[0] || 'Документы')+' · Кузница Softline';
  if(!name){
    add(main,'h1','Документы');
    const response=await fetch('/web-data/documents');if(!response.ok)throw Error('Не удалось открыть список документов.');
    const available=new Set(await response.json()),list=add(main,'div',null,'docLibrary');
    for(const k of new Set([...Object.keys(catalog),...[...available].map(f=>f.slice(0,-3))])){
      const [title,description]=catalog[k] || [k,'Документ проекта.'],card=add(list,'article'),file=k+'.md';
      if(available.has(file))link(card,title,'/docs/'+encodeURIComponent(file));else add(card,'strong',title+' · ожидает публикации');
      add(card,'p',description);
    }
    return;
  }
  const nav=add(main,'nav',null,'docTools');link(nav,'← Все документы','/docs');button(nav,'Скачать PDF',()=>window.print());
  const res=await fetch('/web-data/documents/'+name.split('/').map(encodeURIComponent).join('/'));
  if(!res.ok)throw Error('Документ недоступен.');
  const article=add(main,'article',null,'docBody');renderMarkdown(article,await res.text());
  if(location.hash)document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView();
}
