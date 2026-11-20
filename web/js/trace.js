import {add,line,details,rows,num,money,link} from './dom.js';
const statuses = {ok:'Готово',skip:'Пропущен',fallback:'Запасной путь',error:'Ошибка'};
export function trace(p,r,inspect=true) {
  const stats = add(p,'div',null,'traceStats');
  for (const [title,value] of [['Время поиска',r.timing_ms?.total == null ? '' : num(r.timing_ms.total)+' мс'],
    ['Вызовы модели',r.cost?.llm_calls],['Стоимость',money(r.cost?.rub) || (r.cost?.usd == null ? '' : num(r.cost.usd)+' $')]]) {
    if (value !== '' && value != null) {
      const box = add(stats,'div');add(box,'strong',value);add(box,'small',title);
    }
  }
  const ol = add(p,'ol',null,'steps');
  for (const s of rows(r.trace)) {
    const li = add(ol,'li');
    const d = details(li,s.title || s.step || 'Шаг');
    if (s.detail != null) add(d,'pre',typeof s.detail === 'string' ? s.detail : JSON.stringify(s.detail,null,2));
    line(li,s.summary);
    line(li,[statuses[s.status] || s.status,s.ms == null ? '' : num(s.ms)+' мс'].filter(Boolean).join(' · '),'stepStatus '+s.status,'small');
  }
  if (!ol.childElementCount) line(p,'Трасса для этого запроса недоступна.');
  if (inspect && r.search_id) link(p,'Открыть разбор запроса →','/inspect/'+encodeURIComponent(r.search_id));
}
