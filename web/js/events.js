import {api} from './api.js';
import {state} from './state.js';

let active;
export function watch(r, session) {active = {r,session};}

export async function record(r, type, card={}, block, session=state.session,action) {
  if (!r?.search_id) return;
  if (active?.r === r && ['click','cart','lead','order','reformulate'].includes(type)) active = null;
  const body = {type,search_id:r.search_id,session_id:session,client_id:r.profile?.id,
    card_id:card.card_id,offer_id:card.offer?.offer_id,position:card.position,qty:card.calc?.qty,
    value:card.calc?.total,payload:{block,action}};
  if(type==='impression')body.payload.cards=(r.blocks || []).flatMap(b=>(b.items || []).map(i=>(i.card || i).offer?.offer_id)).filter(Boolean);
  await api('/api/event',body,{keepalive:true});
}
export function leave() {
  const previous = active;
  active = null;
  if (previous) record(previous.r,'exit',{},undefined,previous.session).catch(() => {});
}
window.addEventListener('pagehide', leave);
