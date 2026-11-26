import {add} from './dom.js';

export function merchandise(card){
  const o=card.offer || {},attrs=o.attrs || card.attrs || {};
  const price=o.price ?? card.price,old=Number(o.oldprice ?? card.oldprice ?? attrs.extra?.oldprice);
  return {price,old,discount:price>0 && price<old ? Math.round((1-price/old)*100) : null,
    quote:o.price_on_request || card.price_on_request || price===0,
    picture:card.picture || o.picture || card.image || o.image || attrs.picture || attrs.extra?.picture};
}

export function picture(parent,src,brand=''){
  const box=add(parent,'div',null,'productPic');box.setAttribute('aria-hidden','true');
  const face=add(box,'b',String(brand || 'ПО').slice(0,2).toUpperCase(),'pack');
  if(typeof src==='string' && /^(?:https?:\/\/|\/(?!\/))/i.test(src)){
    const img=add(box,'img');img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';
    img.onload=()=>{face.hidden=true;img.classList.add('ready');};img.onerror=()=>img.remove();img.src=src;
  }
}
