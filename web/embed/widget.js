(() => {
  const script=document.currentScript;
  const host=document.createElement('div');
  script.after(host);
  const root=host.attachShadow({mode:'open'});
  const origin=new URL(script.src).origin;
  const options={...script.dataset};
  if(options.demo==='1' && origin===location.origin && location.pathname==='/embed'){
    const params=new URLSearchParams(location.search);
    if(params.get('show')==='1'){
      options.initialQuery=params.get('q') || '';
      if(['smart','fast'].includes(params.get('mode')))options.mode=params.get('mode');
    }
  }
  import(new URL('./search.js',script.src)).then(module=>module.mount(root,origin,options))
    .catch(()=>{root.textContent='Поиск временно недоступен.';});
})();
