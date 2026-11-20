const extraKeys=['ignore','filters','verbatim','context','page'];
export function address(req,compare='',base='/') {
  const url=new URL(base,location.href);
  const view={q:req.q,profile:req.profile_id,mode:req.mode,category:req.category,compare};
  const criteria=Object.fromEntries(extraKeys.filter(k=>req[k]!=null).map(k=>[k,req[k]]));
  if(Object.keys(criteria).length)view.criteria=JSON.stringify(criteria);
  else url.searchParams.delete('criteria');
  for(const [key,value] of Object.entries(view)){
    if(value)url.searchParams.set(key,value);else url.searchParams.delete(key);
  }
  return url.pathname+url.search+url.hash;
}
export function readAddress(search){
  const p=new URLSearchParams(search);
  let criteria={};
  try{
    const data=JSON.parse(p.get('criteria'));
    if(data)criteria=Object.fromEntries(extraKeys.filter(k=>data[k]!=null).map(k=>[k,data[k]]));
  }catch{ /* Остальные параметры ссылки по-прежнему применимы. */ }
  return {q:p.get('q') || '',profile_id:p.get('profile') || 'guest',mode:p.get('mode') || 'smart',category:p.get('category') || '',compare:p.get('compare') || '',criteria};
}
