import {api} from './api.js';
import {picture,merchandise} from './retail.js';
import {add,rows,money} from './dom.js';
export function suggestions(input,p,params,launch,origin='',onCard) {
  const groups=['corrections','categories','queries','products','upsell','licenses','vendors'];
  const titles={corrections:'Возможно, вы имели в виду',queries:'Запросы',products:'Товары',categories:'Разделы',upsell:'Возможно, вам понадобится'};
  const caps={products:4,categories:3,upsell:2};
  let version=0,controller,timer,options=[],active=-1;
  function close() {
    clearTimeout(timer);controller?.abort();version++;active=-1;options=[];p.hidden=true;
    input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');
  }
  input.addEventListener('input',()=>{
    close();
    if (input.value.trim().length<2) return;
    const id=version;
    timer=setTimeout(async()=>{
      try {
        controller=new AbortController();
        const r=await api(origin+'/api/suggest?'+new URLSearchParams({...params(),q:input.value}),null,{signal:controller.signal});
        if(id!==version) return;
        p.replaceChildren();
        if(r.corrected && r.corrected!==input.value && !rows(r.groups).some(g=>g.type==='corrections' && rows(g.items).some(i=>i.text || i.title))) add(p,'p','Исправлено: '+r.corrected);
        const order=g=>groups.includes(g.type)?groups.indexOf(g.type):groups.length;
        const seen={};
        for(const g of rows(r.groups).sort((a,b)=>order(a)-order(b))) {
          const items=rows(g.items).filter(item=>item.text || item.title).slice(0,(caps[g.type] ?? Infinity)-(seen[g.type] || 0));
          if(!items.length)continue;
          seen[g.type]=(seen[g.type] || 0)+items.length;
          const group=add(p,'div');group.setAttribute('role','group');
          const title=titles[g.type] || g.title;
          if(title){group.setAttribute('aria-label',title);add(group,'small',title,'groupTitle');}
          for(const item of items) {
            const text=item.text || item.title;
            const meta=typeof item.meta==='object' && item.meta ? item.meta:{};
            const product=['products','upsell'].includes(g.type),record={...meta,...item},retail=merchandise(record);
            const o=add(group,'div',null,'option');
            if(product)picture(o,retail.picture,record.vendor?.title || text);
            const name=add(o,'span');
            const query=[input.value,r.corrected].find(q=>q && text.toLowerCase().includes(q.toLowerCase())) || input.value, idx=text.toLowerCase().indexOf(query.toLowerCase());
            if(idx<0)name.textContent=text;
            else {name.append(text.slice(0,idx));add(name,'mark',text.slice(idx,idx+query.length));name.append(text.slice(idx+query.length));}
            if(item.hint)add(name,'small',item.hint);
            if(product && (retail.quote || retail.price!=null))add(o,'b',retail.quote?'По запросу':money(retail.price),'suggestPrice');
            const promo=rows(record.badges).find(b=>b.kind==='promo')?.label;
            if(promo || retail.discount!=null)add(name,'small',promo || 'Акция −'+retail.discount+' %','deal');
            if(!product)add(o,'small',({products:'продукт',categories:'категория',vendors:'вендор',licenses:'ваша лицензия',corrections:'исправление',my:'ваша лицензия',queries:'запрос',answers:'ответ'})[g.type] || g.title);
            o.setAttribute('role','option');
            o.id='suggest-'+options.length;o.onmousedown=e=>e.preventDefault();
            o.onclick=()=>{
              const id=record.card_id || (['sku','card','product'].includes(item.kind) && typeof item.meta==='string'?item.meta:null);
              const category=record.category_id || (g.type==='categories' && ['string','number'].includes(typeof item.meta)?String(item.meta):null);
              close();
              if(product && id){
                const profile=params().profile_id;
                const url=origin+'/card/'+encodeURIComponent(id)+(profile && profile!=='guest'?'?'+new URLSearchParams({profile}):'');
                onCard?.({...record,card_id:id},g.type);
                if(origin)window.open(url,'_blank','noopener');else location.assign(url);
              }else launch(item.q || text,category?{category}:{});
            };options.push(o);
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
