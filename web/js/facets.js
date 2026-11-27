import {caption} from './labels.js';
import {add,button,rows,counted,money} from './dom.js';

const MAX_VALUES=8;
const ORDER=['vendor','category','price_max','price','price_min'];
const MULTI=new Set(['vendor','category','family','edition','certs','platform']);

function parseRange(id){
  if(typeof id!=='string')return null;
  const m=id.trim().match(/^(\d*(?:\.\d+)?)\s*(?:-|\.\.|–)\s*(\d*(?:\.\d+)?)$/);
  if(!m || (!m[1] && !m[2]))return null;
  return {min:m[1]?Number(m[1]):null,max:m[2]?Number(m[2]):null};
}

function facetAction(facet,val){
  if(val.apply && typeof val.apply==='object'){
    const keys=Object.keys(val.apply.filters || {});
    return {patch:val.apply,keys:keys.length?keys:[facet.key]};
  }
  if(facet.key==='price' || facet.key==='price_range'){
    const range=parseRange(val.id);
    const min=val.price_min ?? val.min ?? range?.min ?? null;
    const max=val.price_max ?? val.max ?? range?.max ?? null;
    if(min!=null || max!=null){
      const filters={price_min:min!=null?Number(min):null,price_max:max!=null?Number(max):null};
      return {patch:{filters},keys:['price_min','price_max']};
    }
    if(val.id && typeof val.id==='object'){
      return {patch:{filters:val.id},keys:Object.keys(val.id)};
    }
  }
  if(['price_min','price_max','term_months'].includes(facet.key)){
    const n=Number(val.id);
    return {patch:{filters:{[facet.key]:Number.isFinite(n)?n:val.id}},keys:[facet.key]};
  }
  if(facet.key==='registry'){
    return {patch:{filters:{registry:val.id===true || val.id==='true'}},keys:['registry']};
  }
  if(MULTI.has(facet.key)){
    const list=Array.isArray(val.id)?val.id.map(String):[String(val.id)];
    return {patch:{filters:{[facet.key]:list}},keys:[facet.key]};
  }
  return {patch:{filters:{[facet.key]:val.id}},keys:[facet.key]};
}

function matchesValue(facet,val,activeFilters){
  const {patch}=facetAction(facet,val);
  const f=patch.filters;
  if(!f)return false;
  let checked=0;
  for(const [k,expected] of Object.entries(f)){
    const current=activeFilters[k];
    if(expected==null){
      if(current!=null && current!=='')return false;
      continue;
    }
    if(current==null || current==='')return false;
    checked++;
    const expList=Array.isArray(expected)?expected.map(String):[String(expected)];
    const curList=Array.isArray(current)?current.map(String):[String(current)];
    if(!expList.every(x=>curList.includes(x)))return false;
  }
  return checked>0;
}

function activeLabel(key,val,facets){
  const list=Array.isArray(val)?val:[val];
  for(const f of facets){
    if(f.key!==key)continue;
    const found=rows(f.values).find(v=>list.map(String).includes(String(v.id)));
    if(found?.label)return found.label;
  }
  if(key==='price_max' && Number.isFinite(Number(val)))return 'До '+money(Number(val));
  if(key==='price_min' && Number.isFinite(Number(val)))return 'От '+money(Number(val));
  if(key==='registry')return val?'Реестр отечественного ПО':'Не из реестра';
  const text=list.map(v=>caption(key,v,String(v))).join(', ');
  const prefix={vendor:'Производитель',category:'Раздел',platform:'ОС',audience:'Назначение',action:'Действие',delivery:'Поставка'}[key];
  return prefix?prefix+': '+text:text;
}

export function renderFacets(parent,rawFacets,ctx={}){
  const facets=rows(rawFacets)
    .map(f=>({...f,values:rows(f.values).filter(v=>v.label!=null && v.label!=='')}))
    .filter(f=>f.values.length)
    .sort((a,b)=>{
      const ia=ORDER.indexOf(a.key), ib=ORDER.indexOf(b.key);
      if(ia<0 && ib<0)return 0;
      if(ia<0)return 1;
      if(ib<0)return -1;
      return ia-ib;
    });
  if(!facets.length)return null;

  const active=ctx.filters || {};
  const bar=add(parent,'div',null,'facetBar');
  bar.setAttribute('aria-label','Фильтры выдачи');
  const shownFilterKeys=new Set();

  // Applied filter chips with × removal right in the bar.
  const appliedKeys=Object.keys(active).filter(k=>{
    const v=active[k];
    return v!=null && v!=='' && !(Array.isArray(v) && !v.length);
  });
  if(appliedKeys.length){
    const appliedRow=add(bar,'div',null,'facetApplied');
    const handled=new Set();
    // Collapse price_min + price_max into a single matching price facet chip when possible.
    const priceFacet=facets.find(f=>f.key==='price' || f.key==='price_range');
    if(priceFacet && (appliedKeys.includes('price_min') || appliedKeys.includes('price_max'))){
      const matched=priceFacet.values.find(v=>matchesValue(priceFacet,v,active));
      const label=matched?.label || [
        active.price_min!=null?'от '+money(Number(active.price_min)):'',
        active.price_max!=null?'до '+money(Number(active.price_max)):''
      ].filter(Boolean).join(' ');
      const keys=appliedKeys.filter(k=>k==='price_min' || k==='price_max');
      if(ctx.apply)button(appliedRow,label+' ×',()=>ctx.apply({ignore:keys}),'facetChip active');
      else add(appliedRow,'span',label,'facetChip active');
      keys.forEach(k=>{handled.add(k);shownFilterKeys.add(k);});
    }
    for(const key of appliedKeys){
      if(handled.has(key))continue;
      const text=activeLabel(key,active[key],facets);
      if(ctx.apply)button(appliedRow,text+' ×',()=>ctx.apply({ignore:[key]}),'facetChip active');
      else add(appliedRow,'span',text,'facetChip active');
      shownFilterKeys.add(key);
    }
  }

  for(const f of facets){
    const group=add(bar,'div',null,'facetGroup');
    group.dataset.facet=f.key;
    add(group,'span',f.title || caption('criterion',f.key),'facetTitle');
    const valuesBox=add(group,'div',null,'facetValues');
    const hiddenNodes=[];
    for(const [idx,v] of f.values.entries()){
      const isSelected=matchesValue(f,v,active);
      const {patch,keys}=facetAction(f,v);
      const text=counted(v.label,v.count);
      const node=ctx.apply
        ? button(valuesBox,text,()=>ctx.apply(isSelected?{ignore:keys}:patch),isSelected?'facetChip active':'facetChip')
        : add(valuesBox,'span',text,isSelected?'facetChip active':'facetChip');
      if(ctx.apply)node.setAttribute('aria-pressed',String(isSelected));
      if(idx>=MAX_VALUES){
        node.hidden=true;
        hiddenNodes.push(node);
      }
    }
    if(hiddenNodes.length){
      let expanded=false;
      const more=button(valuesBox,'ещё '+hiddenNodes.length,()=>{
        expanded=!expanded;
        hiddenNodes.forEach(n=>{n.hidden=!expanded;});
        more.setAttribute('aria-expanded',String(expanded));
        more.textContent=expanded?'Свернуть':'ещё '+hiddenNodes.length;
      },'facetMore');
      more.setAttribute('aria-expanded','false');
    }
  }
  return {element:bar,shownFilterKeys};
}
