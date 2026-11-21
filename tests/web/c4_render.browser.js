import {mount} from './embed/search.js';
import {upload,voice} from './store/input.js';
import {spreadsheet} from './store/download.js';
import {caption,setMeta} from './store/labels.js';
import {result} from './store/result.js';

const main=document.querySelector('main'),status=document.querySelector('output');
const check=(ok,msg)=>{if(!ok)throw Error(msg);};
try{
  setMeta({categories:[{id:'office',title:'Старое название'}],labels:{categories:{office:{title:'Офисный пакет',parent:'software'}},tiers:{0:'Полное совпадение'}}});
  check(caption('category','office')==='Офисный пакет' && caption('tier',0)==='Полное совпадение','Приоритет справочника');
  const file=new File(['название;количество\nАстра;50'], 'заявка #1.csv');
  window.fetch=async(url,opts)=>{
    const p=new URL(url,'https://example.invalid');
    check(p.pathname==='/api/spec/upload' && p.searchParams.get('name')===file.name && p.searchParams.get('profile_id')==='gov_clinic' && p.searchParams.get('mode')==='smart' && p.searchParams.get('session_id')==='session','Адрес загрузки');
    check(opts.method==='POST' && opts.body===file && opts.headers['Content-Type']==='application/octet-stream','Тело загрузки');
    return Response.json({search_id:'saved-file',upload:{positions:1,skipped:[]}});
  };
  const r=await upload(file,{profile_id:'gov_clinic',session_id:'session',mode:'smart'});
  check(r.upload.positions===1,'Разбор ответа загрузки');
  window.fetch=async()=>Response.json({error:{message:'Не найдены позиции'}},{status:400});
  try{await upload(file,{});throw Error('Ожидалась ошибка');}catch(e){check(e.message==='Не найдены позиции','Текст ошибки');}
  let request;
  result(main,{understood:{entities:[{type:'okved',id:'86.23',title:'Стоматологическая практика'}]},blocks:[{type:'kit',parent:{id:'health',title:'Здравоохранение',q:'ПО для клиники'}}]}, {apply:v=>request=v.q});
  const parent=main.querySelector('a');check(new URL(parent.href).searchParams.get('q')==='ПО для клиники','Ссылка на общий набор');parent.click();check(request==='ПО для клиники' && main.innerText.includes('ОКВЭД 86.23'),'Отрасль и общий набор');
  const clarify=document.createElement('section');
  result(clarify,{blocks:[{type:'clarify',title:'Уточните назначение',question:'Какой класс программ вы ищете?',
    options:[{label:'Серверные ОС',apply:{q:'Серверные ОС'}},{label:'Настольные ОС',apply:{q:'Настольные ОС'}}]}]}, {apply:patch=>request=patch.q});
  clarify.querySelectorAll('button')[1].click();
  check(clarify.textContent.includes('Какой класс программ вы ищете?') && request==='Настольные ОС','Выбор класса программы');
  let heard,lang;const field=document.createElement('input');
  window.SpeechRecognition=class {start(){lang=this.lang;this.onresult({results:[[{transcript:'на тридцать компьютеров'}]]});this.onend();}};
  voice(main,field,q=>heard=q,main);main.querySelector('.mic').click();check(heard===field.value && heard==='на тридцать компьютеров' && lang==='ru-RU' && !main.querySelector('.mic').disabled,'Голосовой ввод');
  const workbook=JSON.parse(document.querySelector('#fixtures').textContent).xlsx;
  const binary=Uint8Array.from(atob(workbook),ch=>ch.charCodeAt(0));

  let saved,objectURL;HTMLAnchorElement.prototype.click=function(){saved=this.download;objectURL=this.href;};
  window.fetch=async url=>{check(url==='/api/export/saved-file?format=xlsx','Экспорт');return new Response(new Blob([binary]),{headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','Content-Disposition':'attachment; filename="KP-demo.xlsx"'}});};
  spreadsheet(main,'Скачать КП','/api/export/saved-file?format=xlsx','КП.xlsx');main.querySelector('.download').click();
  await new Promise(resolve=>setTimeout(resolve,20));check(saved==='KP-demo.xlsx','Скачивание');
  const fileReader=new XMLHttpRequest();fileReader.open('GET',objectURL);fileReader.responseType='arraybuffer';
  const complete=new Promise(resolve=>fileReader.onload=resolve);fileReader.send();await complete;
  check(btoa(String.fromCharCode(...new Uint8Array(fileReader.response)))===workbook,'Целостность файла КП');
  const partner=document.createElement('div'),root=partner.attachShadow({mode:'open'});
  let expectedMode='fast';
  const sent=[],origin='https://partner-api.invalid';
  window.fetch=async(url,opts)=>{
    check(url.startsWith(origin+'/api/'),'Виджет должен обращаться к серверу скрипта');
    if(url.endsWith('/meta'))return Response.json({});
    if(url.includes('/suggest?'))return Response.json({groups:[{type:'queries',title:'Запросы',items:[{text:'Астра',q:'Astra Linux'}]}]});
    const body=JSON.parse(opts.body);
    if(url.endsWith('/event')){sent.push(body.type);return new Response(null,{status:204});}
    check(url.endsWith('/search') && body.q==='Astra Linux' && body.profile_id==='gov_clinic' && body.mode===expectedMode,'Поиск из подсказки виджета');
    return Response.json({search_id:'embedded',understood:{intent_title:'Поиск продукта'},blocks:[{type:'products',items:[{title:'Astra Linux',card_id:'astra',offer:{price:513}}]}]});
  };
  const shown=new Promise(resolve=>partner.addEventListener('kuznitsa:results',resolve,{once:true}));
  mount(root,origin,{profile:'gov_clinic',mode:'fast',modeSwitch:'1'});
  const i=root.querySelector('input');i.value='Аст';i.dispatchEvent(new Event('input'));
  await new Promise(resolve=>setTimeout(resolve,200));root.querySelector('.option').click();
  check((await shown).detail.search_id==='embedded' && root.querySelector('.purchase').textContent.includes('513'),'Цена и событие партнёра');
  root.querySelector('.productTitle').click();
  check(['impression','suggest_click','click'].every(v=>sent.includes(v)),'События виджета');
  const picker=root.querySelector('select');check(picker.value==='fast','Начальный режим');
  expectedMode='smart';const next=new Promise(resolve=>partner.addEventListener('kuznitsa:results',resolve,{once:true}));
  picker.value='smart';picker.dispatchEvent(new Event('change'));await next;
  check(new URL(root.querySelector('a').href).searchParams.get('mode')==='smart','Переход в выбранный режим');
  status.textContent='passed';
}catch(e){status.textContent=e.stack;}
