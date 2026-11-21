import {settings} from './admin/priorities.js';

const p=document.querySelector('main'),status=document.querySelector('output');
const tick=()=>new Promise(resolve=>setTimeout(resolve,30));
const click=t=>[...p.querySelectorAll('button')].find(b=>b.textContent===t).click();
const rule={id:'demo',title:'Правило для клиник',enabled:false,order:10,target:{tags:['domestic']},scope:{segments:['gov']},action:{criteria:{margin:.6},boost:40}};
const requests=[];
window.fetch=async(path,opts={})=>{
  requests.push([path,opts]);
  if(path==='/api/meta')return Response.json({labels:{tags:{domestic:'Из реестра'},criteria:{margin:'Маржа сегмента'}}});
  if(path.endsWith('/preview'))return Response.json({queries:[{q:'антивирус',before:[{title:'Карточка А'}],after:[{title:'Карточка Б'}]}],summary:{effect_text:'Изменение состава первой пятёрки'}});
  if(path.endsWith('/audit'))return Response.json({items:[{operation:'toggle',after:rule,ts:1,author:'Менеджер'}]});
  return Response.json({items:[rule],criteria:['margin'],tags:['domestic']});
};
try{
  settings(p,new URLSearchParams());await tick();click(rule.title);
  if(!p.innerText.includes('Из реестра') || !p.innerText.includes('Маржа сегмента'))throw Error('Подписи из справочника');
  click('Предпросмотр');await tick();
  const preview=JSON.parse(requests.find(([url])=>url.endsWith('/preview'))[1].body);
  if(preview.rule.id!==rule.id || !preview.rule.enabled || preview.rule.action.boost!==40 || !p.innerText.includes('Карточка Б'))throw Error('Предпросмотр включённой версии');
  click('Сохранить');await tick();if(!p.innerText.includes('Нужен ключ'))throw Error('Защита записи');
  sessionStorage.kzAdminKey='test-only';click('Сохранить');await tick();
  const update=requests.find(([url,o])=>url.endsWith('/demo') && o.method==='PUT');
  if(!update || JSON.parse(update[1].body).enabled || update[1].headers['X-Admin-Token']!=='test-only')throw Error('Сохранение черновика');
  click('Включить');await tick();if(!requests.some(([url])=>url.endsWith('/demo/toggle')))throw Error('Включение правила');
  p.replaceChildren();settings(p,new URLSearchParams({section:'audit'}));await tick();
  if(!p.innerText.includes('Переключение') || !p.innerText.includes('Менеджер'))throw Error('Журнал изменений');
  status.textContent='passed';
}catch(e){status.textContent=e.stack;}
