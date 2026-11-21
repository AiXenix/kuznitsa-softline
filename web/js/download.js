import {button} from './dom.js';

export function spreadsheet(parent,title,url,filename,admin=false){
  const control=button(parent,title,async()=>{
    control.disabled=true;status.textContent='';
    try{
      const token=admin && sessionStorage.getItem('kzAdminKey');
      const response=await fetch(url,{headers:token?{'X-Admin-Token':token}:{}});
      const type=response.headers.get('Content-Type') || '';
      if(!response.ok || !/spreadsheet|octet-stream|excel/i.test(type)){
        const error=await response.json().catch(()=>null);
        throw Error(error?.error?.message || (response.status===403?'Для выгрузки нужен ключ доступа.':'Выгрузка XLSX пока недоступна.'));
      }
      const object=URL.createObjectURL(await response.blob()),a=document.createElement('a');
      const header=response.headers.get('Content-Disposition') || '';
      const encoded=/filename\*=UTF-8''([^;]+)/i.exec(header);
      const name=/filename\s*=\s*(?:"([^"]+)"|([^;]+))/i.exec(header);
      a.download=(encoded?decodeURIComponent(encoded[1]):name?.[1] || name?.[2]?.trim()) || filename;
      a.href=object;a.click();setTimeout(()=>URL.revokeObjectURL(object),60000);
    }catch(e){status.textContent=e.message;}
    finally{control.disabled=false;}
  },'download');
  const status=document.createElement('span');status.setAttribute('role','status');parent.append(status);
}
