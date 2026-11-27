const extraKeys=['ignore','filters','exclude','verbatim','context','page'];
const sortValues=new Set(['price_asc','price_desc']);
export function address(req,compare='',base='/') {
  const url=new URL(base,location.href);
  url.searchParams.delete('upload');
  const sort=sortValues.has(req.sort) ? req.sort : '';
  const view={q:req.q,profile:req.profile_id,mode:req.mode,category:req.category,sort,compare};
  const criteria=Object.fromEntries(extraKeys.filter(k=>{
    const v=req[k];
    if(v==null)return false;
    if(Array.isArray(v))return v.length>0;
    if(typeof v==='object')return Object.keys(v).length>0;
    if(k==='page' && v===1)return false;
    return true;
  }).map(k=>[k,req[k]]));
  if(Object.keys(criteria).length)view.criteria=JSON.stringify(criteria);
  else url.searchParams.delete('criteria');
  for(const [key,value] of Object.entries(view)){
    if(value)url.searchParams.set(key,value);else url.searchParams.delete(key);
  }
  return url.pathname+url.search+url.hash;
}
export function readAddress(search){
  const p=new URLSearchParams(search);
  const sort=sortValues.has(p.get('sort')) ? p.get('sort') : '';
  let criteria={};
  try{
    const data=JSON.parse(p.get('criteria'));
    if(data)criteria=Object.fromEntries(extraKeys.filter(k=>data[k]!=null).map(k=>[k,data[k]]));
  }catch{ /* Остальные параметры ссылки по-прежнему применимы. */ }
  if(sort)criteria.sort=sort;
  return {q:p.get('q') || '',profile_id:p.get('profile') || 'guest',mode:p.get('mode') || 'smart',category:p.get('category') || '',sort,compare:p.get('compare') || '',criteria};
}
