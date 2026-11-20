import {consolePage} from './admin/index.js';
import {inspector} from './admin/inspect.js';
import {resetData} from './admin/common.js';

const fixtures=JSON.parse(document.querySelector('#fixtures').textContent);
const main=document.querySelector('main'),status=document.querySelector('output');
const tick=()=>new Promise(resolve=>setTimeout(resolve,20));
let sparse=false, newer=false;
window.fetch=async path=>{
  const url=new URL(path,'https://example.invalid'), name=url.pathname.split('/')[3];
  const kind=url.searchParams.get('kind');
  if(name==='queries' && kind==='recent' && newer)return new Response(JSON.stringify({items:[{search_id:'recent-id',q:'Недавний запрос',n_cards:0}]}));
  if(name==='queries' && kind==='recent')return new Response('{}',{status:422});
  const key=name==='queries'?'queries-'+kind:name==='replay'?'replay-result':name;
  if(!(key in fixtures))throw Error('Unexpected endpoint '+path);
  const payload=sparse?{items:null,tiles:[],totals:{behavioral_searches:0},slices:null,comparison:{searches:0,before_zero:0},pairs:null,scenarios:null,sources:null}:fixtures[key];
  return new Response(JSON.stringify(payload));
};
try{
  fixtures['replay-result'].recovered=731267;
  consolePage(main);
  for(const mode of [false,true]){
    sparse=mode;resetData();
    for(const tab of ['head','ecom','product','content','agent','log']){
      location.hash=tab;await tick();await tick();
      const text=main.innerText;
      if(!main.querySelector('.adminPanel') || /NaN|undefined|Infinity|Нет связи|HTTP 5/.test(text))throw Error(tab+' · '+text.slice(-300));
      if(!mode && tab==='head' && !text.replace(/\s+/g,'').includes('731267'))throw Error('Recovered count differs from API');
      if(!mode && tab==='agent' && !text.includes('Было → стало'))throw Error('Missing verification');
    }
  }
  sparse=false;newer=true;resetData();
  fixtures.kpi.pairs=[{key:'target',label:'Показатель B2',unit:'%',before:0,after:12.5,better:'higher'}];
  location.hash='head';await tick();if(!main.innerText.includes('Показатель B2'))throw Error('B2 pairs missing');
  location.hash='log';await tick();if(!main.querySelector('a[href="/inspect/recent-id"]'))throw Error('Recent missing');
  resetData();main.replaceChildren();inspector(main);await tick();
  if(!main.querySelector('.steps details[open]') || !main.querySelector('.catalogCard'))throw Error('Inspector missing trace or cards');
  status.textContent='passed';
}catch(e){status.textContent=e.message;}
