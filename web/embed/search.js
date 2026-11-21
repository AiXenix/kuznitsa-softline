import {api} from '../js/api.js';
import {add,line,rows,link} from '../js/dom.js';
import {suggestions} from '../js/suggest.js';
import {voice} from '../js/input.js';
import {result} from '../js/result.js';
import {setMeta} from '../js/labels.js';

export function mount(root,origin,options){
  for(const name of ['css/store.css','embed/widget.css']){
    const css=add(root,'link');css.rel='stylesheet';css.href=origin+'/web/'+name;
  }
  const box=add(root,'section',null,'widget'),form=add(box,'form');
  const label=add(form,'label','Поиск программ'),bar=add(form,'div',null,'bar');
  const input=add(bar,'input');input.type='search';input.placeholder='Название, лицензия или задача';
  input.id='widget-query';label.htmlFor=input.id;input.required=true;input.maxLength=1500;input.autocomplete='off';
  const submit=add(bar,'button','Найти','primary');submit.type='submit';
  const list=add(bar,'div');list.id='suggestions';list.hidden=true;list.setAttribute('role','listbox');
  input.setAttribute('role','combobox');input.setAttribute('aria-controls',list.id);input.setAttribute('aria-expanded','false');
  const notice=add(box,'p',null,'notice');notice.setAttribute('role','status');
  const output=add(box,'div');
  const params={profile_id:options.profile || 'guest',session_id:crypto.randomUUID?.() || 'widget-'+Date.now()};
  const mode=['smart','fast','naive'].includes(options.mode)?options.mode:'smart';
  let generation=0,active=null;
  const meta=api(origin+'/api/meta').then(m=>{setMeta(m);return m;}).catch(()=>({}));
  function event(r,type,c={},block){
    if(!r.search_id)return;
    return api(origin+'/api/event',{type,search_id:r.search_id,session_id:params.session_id,client_id:params.profile_id,card_id:c.card_id,offer_id:c.offer?.offer_id,position:c.position,payload:{block}},{keepalive:true})
      .catch(()=>{notice.textContent='Событие поиска не удалось сохранить.';});
  }
  function leave(){if(active)event(active,'exit');active=null;}
  const close=suggestions(input,list,()=>params,q=>search(q,{},true),origin);
  async function search(q,criteria={},suggested=false){
    if(!q.trim())return;
    leave();const version=++generation;close();input.value=q;
    notice.textContent='Подбираем лицензии…';output.replaceChildren();
    try{
      const r=await api(origin+'/api/search',{...params,q,mode,source:'ui',...criteria});
      const m=await meta;if(version!==generation)return;
      notice.textContent='';active=r;event(r,'impression');if(suggested)event(r,'suggest_click');
      result(output,r,{shopOrigin:origin,categories:m.categories,apply:change=>search(change.q || q,{...criteria,...change}),
        forBlock:block=>({click:c=>{active=null;event(r,'click',c,block);}})});
      link(output,'Продолжить в каталоге',origin+'/?'+new URLSearchParams({q,profile:params.profile_id,mode}));
      root.host.dispatchEvent(new CustomEvent('kuznitsa:results',{bubbles:true,detail:{q,search_id:r.search_id}}));
    }catch(err){if(version===generation)notice.textContent=err.message;}
  }
  form.onsubmit=e=>{e.preventDefault();search(input.value);};
  voice(bar,input,q=>search(q),notice);
  window.addEventListener('pagehide',leave);
}
