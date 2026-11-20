import {api} from './api.js';
import {add,rows} from './dom.js';
export function suggestions(input,p,params,launch) {
  let version=0,timer,options=[],active=-1;
  function close() {
    clearTimeout(timer);version++;active=-1;options=[];p.hidden=true;
    input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');
  }
  input.addEventListener('input',()=>{
    close();
    if (!input.value.trim()) return;
    const id=version;
    timer=setTimeout(async()=>{
      try {
        const r=await api('/api/suggest?'+new URLSearchParams({...params(),q:input.value}));
        if(id!==version) return;
        p.replaceChildren();
        if(r.corrected && r.corrected!==input.value) add(p,'p','Исправлено на «'+r.corrected+'»');
        for(const g of rows(r.groups)) {
          const group=add(p,'div');group.setAttribute('role','group');
          if (g.title) {group.setAttribute('aria-label',g.title);add(group,'small',g.title);}
          for(const item of rows(g.items)) {
            const o=add(group,'div',item.text,'option');o.setAttribute('role','option');
            o.id='suggest-'+options.length;o.onmousedown=e=>e.preventDefault();
            o.onclick=()=>launch(item.text);options.push(o);
          }
        }
        p.hidden=!options.length;input.setAttribute('aria-expanded',String(!p.hidden));
      } catch {if(id===version) close();}
    },150);
  });
  input.addEventListener('keydown',e=>{
    if(e.key==='Escape') close();
    if(!options.length) return;
    if(e.key==='Enter' && active>=0){e.preventDefault();options[active].click();return;}
    if(!['ArrowDown','ArrowUp'].includes(e.key))return;
    e.preventDefault();
    active=e.key==='ArrowDown' ? (active+1)%options.length : (active<=0 ? options.length-1 : active-1);
    options.forEach((o,i)=>o.setAttribute('aria-selected',String(i===active)));
    input.setAttribute('aria-activedescendant',options[active].id);options[active].scrollIntoView({block:'nearest'});
  });
  input.addEventListener('blur',close);
  return close;
}
