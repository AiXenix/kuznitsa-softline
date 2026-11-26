import {$,add,line,button,money,stateBox} from './dom.js';
import {state} from './state.js';
import {record} from './events.js';

export function cart() {
  const drawer=$('drawer'), body=$('cartBody'), basket=$('basket');
  let ordering=false;
  try{state.cart=JSON.parse(sessionStorage.getItem('shop:cart') || '[]');}catch{state.cart=[];}
  function persist(){try{sessionStorage.setItem('shop:cart',JSON.stringify(state.cart));}catch{/* Storage can be unavailable in private browsing. */}}
  basket.hidden=false;
  basket.replaceChildren();const basketLabel=add(basket,'span');
  function count(){basketLabel.textContent=state.cart.length?'Корзина · '+state.cart.length:'Корзина';}
  count();
  function display() {
    body.replaceChildren();
    if(!state.cart.length) stateBox(body,'Корзина пока пуста.');
    for(const {card} of state.cart) {
      const row=add(body,'article',null,'product');
      add(row,'h3',card.title);line(row,card.offer?.name);line(row,card.calc?.text || money(card.offer?.price),'price');
    }
    if (ordering) {stateBox(body,'Оформляем заказ…','loading');return;}
    if(state.cart.length) button(body,'Оформить заказ',async e=>{
      if(ordering)return;
      ordering=true;
      const target=e.currentTarget;
      target.disabled=true;
      try {
        while(state.cart.length) {
          const {r,card,block,session}=state.cart[0];
          await record(r,'order',card,block,session);
          state.cart.shift();persist();count();
        }
        ordering=false;body.replaceChildren();stateBox(body,'Демонстрационный заказ оформлен.');
      } catch(err){ordering=false;display();stateBox(body,err.message,'error');}
    },'primary');
  }
  basket.onclick=()=>{$('drawerTitle').textContent='Корзина';display();drawer.showModal();};
  return (r,block,session)=>({
    click:(c,action)=>{
      if(action==='card' && r?.search_id && c.card_id){
        sessionStorage.setItem('shop:ref:'+c.card_id,JSON.stringify({search_id:r.search_id,profile:r.profile,block,rule_id:c.rule_id,position:c.position,session}));
      }
      return record(r,'click',c,block,session,action).catch(err=>{$('notice').textContent=err.message;});
    },
    act:async(type,c,b)=>{
      if(type==='lead'){
        $('drawerTitle').textContent='Заявка менеджеру';body.replaceChildren();
        line(body,c.title || r.query?.raw,null,'h3');line(body,c.offer?.name);
        const form=add(body,'form'), label=add(form,'label','Количество'), quantity=add(label,'input');
        quantity.type='number';quantity.min=1;quantity.step=1;quantity.value=r.understood?.qty?.value ?? c.calc?.qty ?? '';
        const submit=add(form,'button','Отправить заявку','primary');
        form.onsubmit=async e=>{
          e.preventDefault();submit.disabled=true;
          try{await record(r,'lead',{...c,calc:{...c.calc,qty:quantity.value?Number(quantity.value):undefined}},block,session);
            body.replaceChildren();stateBox(body,'Заявка на поставку сохранена.');b.textContent='Заявка принята';}
          catch(err){submit.disabled=false;line(body,err.message,'error');}
        };
        drawer.showModal();return;
      }
      b.disabled=true;
      try {
        await record(r,type,c,block,session);
        if(type==='cart'){state.cart.push({r:{search_id:r.search_id,profile:r.profile,standalone:r.standalone},card:c,block,session});persist();count();}
        b.textContent=type==='cart' ? 'В корзине' : 'Запрос принят';
        $('notice').textContent=type==='cart' ? 'Лицензия добавлена в корзину.' : 'Запрос поставки сохранён.';
      }catch(err){b.disabled=false;$('notice').textContent=err.message;}
    }
  });
}
