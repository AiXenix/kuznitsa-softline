import {api} from './api.js';

const dictionaries=new Map();
const defaults={
  mode:{naive:'Обычный поиск по словам',smart:'Умный',fast:'Быстрый',smart_cached:'Умный с кэшем',smart_uncached:'Умный без кэша'},
  source:{faq:'Ответ из справочника',kb:'База знаний',rules:'Правила магазина',catalog:'Каталог',api:'Запросы через API',ui:'Витрина',compare:'Сравнения',gallery:'Галерея',history:'История магазина',replay:'Парный прогон',eval:'Проверка качества'},
  segment:{smb:'Малый бизнес',mid:'Средний бизнес',enterprise:'Крупный бизнес',gov:'Госсектор',edu:'Образование',individual:'Частный клиент',guest:'Гости'},
  industry:{manufacturing:'Производство',it_telecom:'ИТ и связь',architecture_design:'Архитектура и проектирование',accounting_audit:'Бухгалтерский учёт и аудит',banking_finance:'Банки и финансы',retail:'Розничная торговля',freelance_individual:'Частная практика',trade:'Торговля',education:'Образование',healthcare:'Здравоохранение',design:'Проектирование',it:'ИТ',accounting:'Бухгалтерские услуги'},
  reason:{off_topic:'Вне тематики магазина',unknown_term:'Незнакомый термин',not_in_catalog:'Нет в каталоге',vendor_left:'Вендор ушёл с рынка',filters_too_strict:'Слишком строгие условия',qty_out_of_range:'Нет ступени количества',no_available_offer:'Нет доступного предложения'},
  intent:{sku:'Поиск по артикулу',product:'Поиск продукта',vendor:'Поиск по вендору',category:'Подбор в категории',broad:'Уточнение запроса',out_of_catalog:'Продукта нет в продаже',off_topic:'За пределами каталога',renewal:'Продление лицензии',license_ops:'Изменение лицензии',question:'Вопрос о ПО',analog:'Поиск аналога',spec_list:'Список позиций',compare:'Сравнение',account:'Личный кабинет',service:'Услуга',promo:'Акции',role_kit:'Рабочее место',industry:'Отраслевой подбор',task:'Поиск по задаче',compliance:'Требования к ПО'}
};
export function setMeta(meta={}){
  for(const [key,kind] of Object.entries({scenarios:'scenario',intents:'intent',categories:'category',vendors:'vendor',segments:'segment',profiles:'profile',families:'family'})){
    const map=new Map(), entries=meta[key];
    for(const [id,row] of Object.entries(entries || {})){
      const title=typeof row==='string'?row:row?.short || row?.title || row?.name;
      if(title)map.set(row?.id ?? id,title);
    }
    dictionaries.set(kind,map);
  }
}
let request;
export function loadMeta(){
  return request ||= api('/api/meta').then(m=>{setMeta(m);return m;}).catch(e=>{request=null;throw e;});
}
export function caption(kind,id,title){
  if(id==null || id==='')id=title || '';
  if(kind==='source' && typeof id==='string')id=id.split(':')[0];
  const value=String(dictionaries.get(kind)?.get(id) || (kind==='intent' && dictionaries.get('scenario')?.get(id)) || (title!==id && title) || (Object.hasOwn(defaults[kind] || {},id)?defaults[kind][id]:id));
  return value.replace(/_/g,' ').replace(/^\p{Ll}/u,c=>c.toLocaleUpperCase('ru'));
}
// Descriptive strings in older journals sometimes contain embedded dictionary keys.
export function readable(text){
  return typeof text==='string'?text.replace(/\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/gi,id=>{
    for(const [kind,map] of dictionaries)if(map.has(id))return caption(kind,id);
    return caption('intent',id);
  }):text;
}
