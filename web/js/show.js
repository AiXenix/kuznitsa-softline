import {api} from './api.js';
import {add,button,link} from './dom.js';
import {address} from './address.js';

export async function presentation(){
  const params=new URLSearchParams(location.search);
  function enable(){const url=new URL(location.href);url.searchParams.set('show','1');location.assign(url);}
  button(document.querySelector('footer .wrap') || document.querySelector('footer'),'Режим показа',enable);
  if(params.get('show')!=='1')return;
  const steps=await api('/web/demo/steps.json');
  let current=steps.find(s=>s.id===(params.get('step') || sessionStorage.kzStep)) || steps.find(s=>s.route==='long');
  function go(step){
    const url=new URL(step.page,location.origin);
    url.searchParams.set('show','1');url.searchParams.set('step',step.id);sessionStorage.kzStep=step.id;
    if(step.action==='open'){location.assign(url);return;}
    url.searchParams.set('action',step.action);
    const compare={compare_profiles:'profiles',compare_modes:'modes'}[step.action];
    location.assign(address({q:step.q,profile_id:step.profile,mode:step.mode},compare,url));
  }
  if(!params.has('step')){go(current);return;}
  sessionStorage.kzStep=current.id;
  document.addEventListener('click',e=>{
    const a=e.target.closest('a[href]');
    if(!a || a.origin!==location.origin || a.getAttribute('href').startsWith('#'))return;
    const url=new URL(a.href);url.searchParams.set('show','1');url.searchParams.set('step',current.id);a.href=url;
  },true);
  const list=steps.filter(s=>s.route===current.route), pos=list.indexOf(current);
  const panel=add(document.body,'aside',null,'showBar');
  const route=add(panel,'select');route.setAttribute('aria-label','Регламент показа');
  route.add(new Option('Показ · 5 минут','short'));route.add(new Option('Финальный маршрут','long'));
  route.add(new Option('Показ · приоритеты','priority'));
  route.value=current.route;route.onchange=()=>go(steps.find(s=>s.route===route.value));
  const jump=n=>{if(list[pos+n])go(list[pos+n]);};
  button(panel,'←',()=>jump(-1)).disabled=pos===0;
  const choice=add(panel,'select');choice.setAttribute('aria-label','Шаг показа');
  list.forEach((s,i)=>choice.add(new Option((i+1)+'. '+s.title,s.id)));
  choice.value=current.id;choice.onchange=()=>go(list.find(s=>s.id===choice.value));
  button(panel,'→',()=>jump(1)).disabled=pos===list.length-1;
  add(panel,'span',current.say);
  if(current.traceStep){
    button(panel,'Шаг уточнения',()=>{
      const step=document.querySelector('#trace [data-step="'+current.traceStep+'"] details');
      if(!step)return;
      if(document.querySelector('#trace').hidden)document.querySelector('#traceCollapse').click();
      if(!document.querySelector('.traceWide'))document.querySelector('#traceWidth').click();
      step.open=true;step.scrollIntoView({block:'center'});step.querySelector('summary').focus({preventScroll:true});
    });
  }
  link(panel,'Схемы','/flows');
  button(panel,'Закрыть',()=>{const u=new URL(location.href);for(const k of ['show','step','action'])u.searchParams.delete(k);location.assign(u);});
  document.body.classList.add('presenting');
  new ResizeObserver(()=>document.body.style.setProperty('--show-height',panel.offsetHeight+'px')).observe(panel);
  window.addEventListener('keydown',e=>{
    if(e.target.closest('input,textarea,select,[contenteditable=true]') && !e.altKey)return;
    if(!e.ctrlKey && !e.metaKey && !document.querySelector('dialog[open]') && ['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();jump(e.key==='ArrowRight'?1:-1);}
  });
}
