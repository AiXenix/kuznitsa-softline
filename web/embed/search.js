import {api} from '../js/api.js';
import {add,line,rows,link} from '../js/dom.js';
import {suggestions} from '../js/suggest.js';
import {voice} from '../js/input.js';
import {result} from '../js/result.js';
import {setMeta} from '../js/labels.js';

export function mount(root,origin,options){
  for(const name of ['css/store.css','css/shop.css','embed/widget.css']){
    const css=add(root,'link');css.rel='stylesheet';css.href=origin+'/web/'+name;
  }
  const box=add(root,'section',null,'widget'),form=add(box,'form');
  const brand=add(form,'div',null,'widgetBrand');
  const label=add(brand,'label','Поиск по каталогу'),logo=add(brand,'img');
  logo.src=origin+'/web/assets/softline-logo.svg';logo.alt='Софтлайн Решения';
  const bar=add(form,'div',null,'bar');
  const input=add(bar,'input');input.type='search';input.placeholder='Продукт, производитель или артикул (SKU)';
  input.id='widget-query';label.htmlFor=input.id;input.required=true;input.maxLength=1500;input.autocomplete='off';
  const submit=add(bar,'button','Найти','primary');submit.type='submit';
  const list=add(bar,'div');list.id='suggestions';list.hidden=true;list.setAttribute('role','listbox');
  input.setAttribute('role','combobox');input.setAttribute('aria-controls',list.id);input.setAttribute('aria-expanded','false');
  const notice=add(box,'p',null,'notice');notice.setAttribute('role','status');
  const output=add(box,'div');
  const params={profile_id:options.profile || 'guest',session_id:crypto.randomUUID?.() || 'widget-'+Date.now()};
  let mode=['smart','fast','naive'].includes(options.mode)?options.mode:'smart';
  if(options.modeSwitch==='1'){
    const label=add(form,'label','Режим поиска '), picker=add(label,'select');
    for(const [id,title] of [['smart','Умный'],['fast','Быстрый']])picker.add(new Option(title,id));
    if(mode==='naive')mode='smart';
    picker.value=mode;
    picker.onchange=()=>{mode=picker.value;close();if(input.value.trim())search(input.value);};
  }
  let generation=0,active=null,source='widget',channelConfirmed=false;
  const meta=api(origin+'/api/meta').then(m=>{setMeta(m);return m;}).catch(()=>({}));
  function event(r,type,c={},block){
    if(!r.search_id)return;
    return api(origin+'/api/event',{type,search_id:r.search_id,session_id:params.session_id,client_id:params.profile_id,card_id:c.card_id,offer_id:c.offer?.offer_id,position:c.position,payload:{block,rule_id:c.rule_id,...(c.rule_id?{kind:block==='crosssell'?'crosssell':'upsell'}:{})}},{keepalive:true})
      .catch(()=>{notice.textContent='Событие поиска не удалось сохранить.';});
  }
  function leave(){if(active)event(active,'exit');active=null;}
  const close=suggestions(input,list,()=>({...params,mode}),(q,criteria)=>search(q,criteria,true),origin,(card,group)=>{if(active)event(active,'suggest_click',card,group);});
  async function search(q,criteria={},suggested=false){
    if(!q.trim())return;
    leave();const version=++generation;close();input.value=q;
    notice.textContent='Подбираем лицензии…';output.replaceChildren();
    try{
      const request={...params,q,mode,...criteria,source};
      if(!request.sort)delete request.sort;
      if(request.filters && !Object.keys(request.filters).length)delete request.filters;
      if(request.exclude && !Object.keys(request.exclude).length)delete request.exclude;
      if(request.ignore && !request.ignore.length)delete request.ignore;
      let r;
      try{r=await api(origin+'/api/search',request);}
      catch(err){
        if(channelConfirmed || err.status!==422 || err.code!=='invalid_request')throw err;
        // Releases before channel-specific priorities accept only the storefront source.
        r=await api(origin+'/api/search',{...request,source:'ui'});source='ui';
      }
      channelConfirmed=true;
      const m=await meta;if(version!==generation)return;
      notice.textContent='';active=r;event(r,'impression');
      for(const b of rows(r.blocks))for(const item of rows(b.items)){
        const c=item.card || item,rule_id=item.rule_id || c.rule_id;
        if(rule_id && c.card_id)event(r,'impression',{...c,rule_id},b.type);
      }
      if(suggested)event(r,'suggest_click');
      result(output,r,{retail:true,shopOrigin:origin,categories:m.categories,sort:request.sort || '',filters:request.filters || {},
        apply:change=>{
          if(change.q)return search(change.q,change);
          const next={...criteria,page:1,...change};
          if(change.filters){
            next.filters={...criteria.filters,...change.filters};
            for(const [k,v] of Object.entries(next.filters))if(v==null || v==='' || (Array.isArray(v) && !v.length))delete next.filters[k];
            if(criteria.ignore?.length){
              const setKeys=new Set(Object.keys(change.filters).filter(k=>change.filters[k]!=null && change.filters[k]!==''));
              next.ignore=criteria.ignore.filter(k=>!setKeys.has(k));
            }
          }
          if(change.exclude){
            next.exclude={...criteria.exclude,...change.exclude};
            for(const [k,v] of Object.entries(next.exclude))if(v==null || v==='' || (Array.isArray(v) && !v.length))delete next.exclude[k];
          }
          if(change.ignore){
            next.ignore=[...new Set([...(next.ignore ?? criteria.ignore ?? []),...change.ignore])];
            next.filters={...(next.filters ?? criteria.filters)};
            if(next.exclude || criteria.exclude)next.exclude={...(next.exclude ?? criteria.exclude)};
            change.ignore.forEach(k=>{delete next.filters[k];if(next.exclude)delete next.exclude[k];});
          }
          search(q,next);
        },
        forBlock:block=>({click:c=>{active=null;event(r,'click',c,block);}})});
      const linkParams=new URLSearchParams({q,profile:params.profile_id,mode});
      if(request.sort)linkParams.set('sort',request.sort);
      link(output,'Продолжить в каталоге',origin+'/?'+linkParams);
      root.host.dispatchEvent(new CustomEvent('kuznitsa:results',{bubbles:true,detail:{q,search_id:r.search_id}}));
    }catch(err){if(version===generation)notice.textContent=err.message;}
  }
  form.onsubmit=e=>{e.preventDefault();search(input.value);};
  voice(bar,input,q=>search(q),notice);
  window.addEventListener('pagehide',leave);
  if(options.initialQuery)search(options.initialQuery);
}
