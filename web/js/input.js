import {api} from './api.js';
import {button,actionIcon} from './dom.js';

export function voice(bar,input,search,notice){
  const Speech=window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!Speech)return;
  const mic=button(bar,'',()=>{
    const speech=new Speech();speech.lang='ru-RU';speech.interimResults=false;
    speech.onresult=e=>{const q=e.results[0]?.[0]?.transcript?.trim();if(q){input.value=q;search(q);}};
    speech.onerror=e=>{notice.textContent=e.error==='not-allowed'?'Разрешите доступ к микрофону в браузере.':'Распознать речь не удалось. Попробуйте ещё раз.';};
    speech.onend=()=>{mic.disabled=false;mic.classList.remove('listening');};
    mic.disabled=true;mic.classList.add('listening');
    try{speech.start();}catch{speech.onend();notice.textContent='Микрофон недоступен.';}
  },'mic');
  actionIcon(mic,'M9 6a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0ZM5 11v1a7 7 0 0 0 14 0v-1M12 19v3m-4 0h8');
  mic.title='Голосовой поиск';mic.setAttribute('aria-label',mic.title);
}
export function upload(file,req){
  if(file.size>2*1024*1024)throw Error('Файл превышает 2 МБ.');
  const params=new URLSearchParams({name:file.name,profile_id:req.profile_id,mode:req.mode==='smart'?'smart':'fast',session_id:req.session_id});
  return api('/api/spec/upload?'+params,null,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
}
