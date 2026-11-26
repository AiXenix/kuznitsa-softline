import {api} from './api.js';
import {state} from './state.js';

let active;
export function watch(r, session) {active = {r,session};}

export async function record(r, type, card={}, block, session=state.session,action) {
  if (!r?.search_id && !r?.standalone) return;
  if (active?.r === r && ['click','cart','lead','order','reformulate'].includes(type)) active = null;
  const body = {type,search_id:r.search_id,session_id:session,client_id:r.profile?.id,
    card_id:card.card_id,offer_id:card.offer?.offer_id,position:card.position,qty:card.calc?.qty,
    value:card.calc?.total,payload:{block,action,rule_id:card.rule_id,...(card.rule_id?{kind:block==='crosssell'?'crosssell':'upsell'}:{}),...(card.action?.type==='repeat_order'?{action:card.action.type,order_id:card.action.order_id}:{})}};
  if(type==='impression' && !card.card_id)body.payload.cards=(r.blocks || []).flatMap(b=>(b.items || []).map(i=>(i.card || i).offer?.offer_id)).filter(Boolean);
  const sent=[api('/api/event',body,{keepalive:true})];
  if(type==='impression' && !card.card_id){
    for(const block of r.blocks || [])for(const item of block.items || []){
      const c=item.card || item,rule_id=item.rule_id || c.rule_id;
      if(rule_id && c.card_id)sent.push(record(r,type,{...c,rule_id},block.type,session));
    }
  }
  await Promise.all(sent);
}
export function leave() {
  const previous = active;
  active = null;
  if (previous) record(previous.r,'exit',{},undefined,previous.session).catch(() => {});
}
window.addEventListener('pagehide', leave);
