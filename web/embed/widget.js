(() => {
  const script=document.currentScript;
  const host=document.createElement('div');
  script.after(host);
  const root=host.attachShadow({mode:'open'});
  const origin=new URL(script.src).origin;
  import(new URL('./search.js',script.src)).then(module=>module.mount(root,origin,script.dataset))
    .catch(()=>{root.textContent='Поиск временно недоступен.';});
})();
