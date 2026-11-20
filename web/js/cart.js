import {$,add,line,button,money,stateBox} from './dom.js';
import {state} from './state.js';
import {record} from './events.js';

export function cart() {
  const drawer=$('drawer'), body=$('cartBody'), basket=$('basket');
  let ordering=false;
  basket.hidden=false;
  function count() {basket.textContent=state.cart.length ? 'Корзина · '+state.cart.length : 'Корзина';}
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
          state.cart.shift();count();
        }
        ordering=false;body.replaceChildren();stateBox(body,'Демонстрационный заказ оформлен.');
      } catch(err){ordering=false;display();stateBox(body,err.message,'error');}
    },'primary');
  }
  basket.onclick=()=>{display();drawer.showModal();};
  return (r,block,session)=>({
    click:c=>record(r,'click',c,block,session).catch(err=>{$('notice').textContent=err.message;}),
    act:async(type,c,b)=>{
      b.disabled=true;
      try {
        await record(r,type,c,block,session);
        if(type==='cart'){state.cart.push({r,card:c,block,session});count();}
        b.textContent=type==='cart' ? 'В корзине' : 'Запрос принят';
        $('notice').textContent=type==='cart' ? 'Лицензия добавлена в корзину.' : 'Запрос поставки сохранён.';
      }catch(err){b.disabled=false;$('notice').textContent=err.message;}
    }
  });
}
