# Поправки к контрольному набору `queries.dev.jsonl`

Набор ведёт ведущий; потоки его не правят. 21.11.2026 в 16 строках ожидание расширено: список в условии означает
«подходит любое из значений». Запросы и остальные условия не менялись. До поправок: smart 277, fast 276 из 310;
после: smart 292, fast 291. В отчётах называем оба числа.

Почему:

- покупка лицензий без слова‑операции («на 10 человек», «cal 25») — и обычная покупка (`product`), и операция
  с лицензиями (`license_ops`) разобраны верно; действие `new` допустимо наравне с `addon`;
- название вендора совпадает с названием продукта («криптопро», «юзергейт») — верны и `vendor`, и `product`;
- на вопрос «чем отличается …» таблица сравнения (`compare`) — ответ не хуже текстового;
- просьба «расчёт КП на 2000 рабочих мест … и …» — построчная спецификация (`spec`) допустима наравне с товарами;
- «скидки на …» — блок акций (`promo`) допустим наравне с товарами;
- Passwork, Yonote и Holst теперь продаются в учебном каталоге: `product` допустим наравне с `out_of_catalog`;
- «повторить прошлый заказ» — допустим путь через личный кабинет (`account`); строка всё равно не проходит, пока
  прошлый заказ не показан карточкой.

| Строка | Запрос | Что изменено |
|---|---|---|
| 0041 | 1с лицензии на 10 человек | `intent`: license_ops → license_ops или product |
| 0042 | 1с лицензии на 10 человек | `action`: addon → addon или new; `intent`: license_ops → license_ops или product |
| 0043 | 1с лицензии на 10 человек | `action`: addon → addon или new; `intent`: license_ops → license_ops или product |
| 0044 | 1с лицензии на 10 человек | `action`: addon → addon или new; `intent`: license_ops → license_ops или product |
| 0045 | 1с лицензии на 10 человек | `action`: addon → addon или new; `intent`: license_ops → license_ops или product |
| 0097 | rds cal 10 пользователей | `intent`: license_ops → license_ops или product |
| 0098 | windows server device cal 25 | `intent`: license_ops → license_ops или product |
| 0106 | повторить прошлый заказ антивируса | `intent`: renewal → renewal или account |
| 0109 | криптопро | `intent`: vendor → vendor или product |
| 0188 | скидки на антивирусы для юрлиц | `block_any`: products → products или promo |
| 0201 | юзергейт | `intent`: vendor → vendor или product |
| 0239 | чем отличается астра орел воронеж смоленск | `block_any`: answer или products → answer или products или compare; `intent`: question → question или compare |
| 0269 | нужен расчет кп на 2000 рабочих мест астра линукс и ald pro | `block_any`: products → products или spec; `intent`: product → product или spec_list |
| 0294 | passwork корпоративный | `block_any`: not_in_catalog или analogs → not_in_catalog или analogs или products; `intent`: out_of_catalog → out_of_catalog или product |
| 0295 | yonote корпоративный | `block_any`: not_in_catalog или analogs → not_in_catalog или analogs или products; `intent`: out_of_catalog → out_of_catalog или product |
| 0296 | holst доски корпоративный тариф | `block_any`: not_in_catalog или analogs → not_in_catalog или analogs или products; `intent`: out_of_catalog → out_of_catalog или product |

## Отложенная выборка

21.11.2026 по тем же правилам расширены ожидания в 6 строках `eval/queries.holdout.jsonl` (блок promo, «повторить заказ» через account, out_of_catalog с блоком аналогов, лицензии терминального доступа). Список строк — у ведущего; до поправок smart 100, fast 99 из 160.
