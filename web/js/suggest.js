import {api} from './api.js';
import {add,rows} from './dom.js';
export function suggestions(input,p,params,launch,origin='') {
  const groups=['corrections','queries','licenses','products','categories','vendors'];
  const icons=['↺','⌕','▤','▦','▧','◇'];
  let version=0,controller,timer,options=[],active=-1;
  function close() {
    clearTimeout(timer);controller?.abort();version++;active=-1;options=[];p.hidden=true;
    input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');
  }
  input.addEventListener('input',()=>{
    close();
    if (!input.value.trim()) return;
    const id=version;
    timer=setTimeout(async()=>{
      try {
        controller=new AbortController();
        const r=await api(origin+'/api/suggest?'+new URLSearchParams({...params(),q:input.value}),null,{signal:controller.signal});
        if(id!==version) return;
        p.replaceChildren();
        if(r.corrected && r.corrected!==input.value) add(p,'p','Исправлено: '+r.corrected);
        const order=g=>groups.includes(g.type)?groups.indexOf(g.type):groups.length;
        for(const g of rows(r.groups).sort((a,b)=>order(a)-order(b))) {
          const group=add(p,'div');group.setAttribute('role','group');
          if (g.title) {group.setAttribute('aria-label',g.title);add(group,'small',(icons[order(g)] || '•')+' '+g.title);}
          for(const item of rows(g.items)) {
            if(!item.text)continue;
            const o=add(group,'div',null,'option');
            const name=add(o,'span');
            const query=[input.value,r.corrected].find(q=>q && item.text.toLowerCase().includes(q.toLowerCase())) || input.value, idx=item.text.toLowerCase().indexOf(query.toLowerCase());
            if(idx<0)name.textContent=item.text;
            else {name.append(item.text.slice(0,idx));add(name,'mark',item.text.slice(idx,idx+query.length));name.append(item.text.slice(idx+query.length));}
            if(item.hint)add(name,'small',item.hint);
            add(o,'small',({products:'продукт',categories:'категория',vendors:'вендор',licenses:'ваша лицензия',corrections:'исправление',my:'ваша лицензия',queries:'запрос',answers:'ответ'})[g.type] || g.title);
            o.setAttribute('role','option');
            o.id='suggest-'+options.length;o.onmousedown=e=>e.preventDefault();
            o.onclick=()=>launch(item.q || item.text);options.push(o);
          }
        }
        if(!options.length && !r.corrected)add(p,'p','Подсказок пока нет. Нажмите Enter, чтобы искать в каталоге.','muted');
        p.hidden=false;input.setAttribute('aria-expanded',String(!p.hidden));
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
