# Заметки Neon-4 — ход 6: аудитории, платформы, «для кого» у линеек, «система, а не вендор»

База: `main` = `ebfdfe4`, спецификация `design/spec-addendum-v0.7.md` (разделы 29.1, 29.2, 29.3, 29.4, 29.8).

## 1. Созданные файлы

| Файл | Назначение | Объём |
|---|---|---|
| `kb/slang_audience_r3.yaml` | Словарь аудиторий (9 значений 29.2) и платформ (6 значений): разговорные формы, жаргон, падежи. Подхватывается `loader.py` автоматически (`slang_*.yaml`). | ~215 терминов, 0 дубликатов с `slang.yaml` / `slang_r3.yaml` |
| `kb/families/home_r3.yaml` | Отсутствовавшие домашние/персональные линейки (`catalog: no`, `analogs` → ближайшая бизнес-линейка). Подхватывается `loader.py` автоматически. | 5 семейств (`eset_home_security`, `myoffice_home`, `r7_office_home`, `microsoft_365_personal`, `cyber_backup_personal`) |
| `design/proposals/neon4/family-for-whom-r6.yaml` | Короткие подписи `for_whom` для категоризатора `refine` (29.2) по всем линейкам 12 популярных вендоров + `analogs` для непродаваемых линеек и рекомендации по правке 3 базовых домашних линеек. | 12 вендоров, 69 линеек |
| `design/proposals/neon4/system-compat-r6.yaml` | Связи совместимости «Система, а не вендор» (29.4): резервное копирование, мониторинг и защита для 1С, PostgreSQL, Exchange, MS SQL, Astra Linux. | 5 систем, только подтверждённые `catalog: yes` линейки |
| `design/proposals/neon4/probes-audience-r6.jsonl` | Публичный набор контрольных проб (29.8). | Ровно 80 строк |
| `design/proposals/neon4/NOTES-r6.md` | Настоящие заметки, описания форматов, просьбы к потоку A и список сомнительных связок на проверку. | — |

---

## 2. Формат данных и просьбы к потоку A

### A1. Словарь `kb/slang_audience_r3.yaml`
Файл оформлен строго по существующей схеме `kb/slang*.yaml` (`term`, `type`, `maps_to`, `note`), без новых полей:
- аудитории: `maps_to: {attr: audience, value: <v>}`, где `<v>` из закрытого списка 29.2:
  `home`, `micro_office`, `business`, `enterprise`, `gov`, `edu`, `server`, `mobile`, `industrial`;
- платформы: `maps_to: {attr: platform, value: <p>}`, где `<p>` из закрытого списка из 6 платформ:
  `server`, `windows`, `linux`, `macos`, `android`, `ios`.

**Просьбы к A по разбору словаря:**
1. **Связка `platform: server` ↔ `audience: server` и термин `"на сервер"`.** В `kb/slang_r3.yaml` уже есть запись `{term: "на сервер", maps_to: {attr: license_metric, value: server}}`, поэтому в `slang_audience_r3.yaml` она не дублировалась. Просьба в парсере/разборе:
   - если перед `"на сервер"` нет числа (т.е. это не «на 2 сервера» как метрика количества), выставлять также `platform: server` и `audience: server`;
   - при срабатывании `platform: server` (например «для серверов», «серверный») синхронно выставлять `audience: server`, если не задана более узкая организационная аудитория (`gov`, `enterprise` и т.п.).
2. **Расширить `schema.Audience`.** Сейчас в `kuznitsa/kb/schema.py` `Audience` ограничен 6 значениями (`business`, `gov`, `edu`, `home`, `nonprofit`, `med`). Для `slang.maps_to` валидатор этого не проверяет, поэтому `kb/slang_audience_r3.yaml` загружается чисто, но при использовании новых аудиторий в `families` потребуется добавить `micro_office`, `enterprise`, `server`, `mobile`, `industrial`.
3. **Уточнить `"для ип"` в базовом `kb/slang.yaml`.** В базовом файле `"для ип"` сейчас привязан к `audience: business`, тогда как разговорные варианты (`"ипэшнику"`, `"в ипэшку"`, `"для ипэшки"`) в `slang_audience_r3.yaml` привязаны к `micro_office`. Просьба перевести `"для ип"` в `micro_office` (или ранжировать малые редакции для обоих случаев при малом числе мест).
4. **Термины `"на ноут"`, `"ноут"`, `"ноутбук"`.** Поскольку список платформ закрытый (6 значений), они привязаны к `platform: windows` как десктопной платформе по умолчанию. Если в запросе явно указан `macos` или `linux` (например «на макбук», «на ноут с линуксом»), явная ОС должна перекрывать `windows`.
5. **Сочетание `home` + `mobile` (например «антивирус ребёнку на телефон»).** Если в одном запросе найдены и `home`, и `mobile`, для срабатывания правила 29.3 (домашних лицензий в B2B-каталоге нет) приоритет должен быть у `audience: home`, а мобильная составляющая может сохраняться в `platform` (`android`/`ios`) или дополнительном теге.

### A2. Подписи «для кого» и домашние линейки (`family-for-whom-r6.yaml`, `home_r3.yaml`)
В `kuznitsa/kb/loader.py` список `FIELDS["families"]` пока не включает поле `for_whom` (неизвестное поле даёт предупреждение/пропуск записи). Поэтому подписи вынесены в `design/proposals/neon4/family-for-whom-r6.yaml` с полями `id`, `vendor`, `catalog`, `audiences`, `seats`, `for_whom`, `analogs`.

**Просьбы к A:**
6. **Подключить `for_whom` для шага `refine` (29.2).** Добавить опциональное поле `for_whom` в `FIELDS["families"]` / `schema.py` (либо считывать `family-for-whom-r6.yaml` как overlay по `family.id`) и передавать `for_whom` в описания кандидатов `line` для Decisions.
7. **Обновить 3 базовые домашние линейки в `kb/families/security.yaml` (или `kb/overrides/families.yaml`).** Эти файлы вне зоны записи Neon-4. Сейчас у `kaspersky_standard_home`, `drweb_security_space` и `pro32_total_security` стоит `catalog: yes`, а `analogs` указывают друг на друга (на другие домашние антивирусы), из-за чего правило 29.3 не сможет предложить ближайшую продаваемую бизнес-линейку. Рекомендуемые правки (продублированы в блоке `base_overrides_recommended` файла `family-for-whom-r6.yaml`):
   - `kaspersky_standard_home` → `catalog: no`, `analogs: [kaspersky_ksos, kaspersky_kesb]`, `upgrade_to: kaspersky_ksos`
   - `drweb_security_space` → `catalog: no`, `analogs: [drweb_small_business, drweb_enterprise_security_suite]`, `upgrade_to: drweb_small_business`
   - `pro32_total_security` → `catalog: no`, `analogs: [pro32_endpoint_security]`, `upgrade_to: pro32_endpoint_security`

### A3. «Система, а не вендор» (`system-compat-r6.yaml`)
8. **Правило снятия фильтра по вендору целевой системы (29.4).** Подключить `design/proposals/neon4/system-compat-r6.yaml` (или перенести его в `kb/` после согласования имени файла в загрузчике):
   - Если в запросе распознаны категория из `compatible.<group>.categories` (`backup_recovery`, `monitoring_apm`, `db_management_tools`, `endpoint_security`, `edr_xdr`, `mail_security`, `dlp`, `nsd_access_control`, `iam_pam_mfa`, `siem_soc`) и алиас системы из `systems[].aliases`, а найденный вендор входит в `system_vendors` (`onec`, `postgres_pro`, `tantor_labs`, `microsoft`, `astra_group`) и у этого вендора нет продаваемых товаров в запрошенной категории:
     - снять жёсткий фильтр по `vendor`;
     - оставить фильтр по `category`;
     - поднять в выдаче линейки из `compatible.<group>.families`;
     - показать чип `label` («Для 1С», «Для PostgreSQL», «Для Exchange», «Для MS SQL», «Для Astra Linux»).
   - **Важный граничный случай:** если запрос относится к собственным продуктам вендора (например «лицензия на сервер 1с», «postgres pro enterprise», «астра линукс на сервер»), вендор остаётся жёстким фильтром и правило 29.4 не срабатывает.
   - **Особый случай `astra_group` + `rubackup`:** в базе знаний `rubackup` заведён под вендором `rubackup`, а не `astra_group`. Поэтому для запроса «резервное копирование для astra linux» снятие фильтра `vendor: astra_group` критично — иначе RuBackup и Кибер Бэкап выпадут из выдачи.

---

## 3. Сомнительные пункты (вынесены на проверку, в `system-compat-r6.yaml` НЕ включены)

1. **RuBackup для 1С (`rubackup` + `1c`).** RuBackup уверенно поддерживает резервное копирование СУБД PostgreSQL / Postgres Pro / Tantor DB (на которых часто работает 1С), но поддержку файловых баз 1С и выделенного модуля уровня приложения 1С следует уточнить по актуальной матрице совместимости вендора.
2. **RuBackup для Microsoft Exchange и MS SQL (`rubackup` + `ms_exchange`, `ms_sql`).** В KB для RuBackup явно подтверждены Linux-ОС (Astra Linux, РЕД ОС) и PostgreSQL; статус нативных агентов под MS Exchange и MS SQL Server в актуальных релизах требует проверки.
3. **Handy Backup для Microsoft Exchange (`handy_backup` + `ms_exchange`).** В KB явно указаны плагины для 1С, PostgreSQL и MS SQL, но прямое подтверждение нативного агента MS Exchange отсутствует (только общие механизмы почтового/файлового копирования).
4. **Ключ-АСТРОМ для 1С (`klyuch_astrom` + `1c`).** В KB подтверждён APM-мониторинг приложений, PostgreSQL, MS SQL и Astra Linux, но нативная глубина мониторинга технологического журнала и кластера 1С требует подтверждения.
5. **Astra Linux Common Edition (Орёл) как «домашняя» линейка.** В B2B-каталоге представлена только Special Edition (`astra_linux_se`), поэтому отдельная домашняя запись не заводилась.
6. **Редакция `Home` внутри `windows_11` / `windows_10`.** В текущих базовых файлах `kb/families/` редакции `Pro` и `Home` объединены в одном семействе `windows_11` (`catalog: yes`). Если в реальном B2B-каталоге ключи Windows Home не продаются, стоит либо выделить `windows_11_home` (`catalog: no`, `analogs: [windows_11]`), либо обрабатывать это на уровне `edition`.
7. **Актуальность агентов `drweb_enterprise_security_suite` (`edition: mail`) для современных сборок MS Exchange.** В KB указана защита почтовых серверов, линейка включена в `ms_exchange.security`, но для приоритетного ранжирования почтового шлюза Exchange первым оставлен `kaspersky_ksmg` (у него в KB прямая явная формулировка «защита RuPost, Exchange, CommuniGate Pro»).

---

## 4. Комментарий по `probes-audience-r6.jsonl` (80 строк)

- **Арифметика подгрупп:** в тексте задания указано «80 строк (29.8)», при этом перечисленная сумма подгрупп даёт 70 (`10 + 10 + 10 + 15 + 15 + 10 = 70`). Чтобы строго выдержать 80 строк из спецификации 29.8 и не уменьшить ни одну из пяти базовых групп, сохранена разбивка:
  - строки 1–10 (10): аудитории (все 9 значений закрытого списка 29.2);
  - строки 11–20 (10): платформы (все 6 платформ: `server`, `windows`, `linux`, `macos`, `android`, `ios`);
  - строки 21–30 (10): жаргон аудиторий («хоум», «домик», «маме», «бабушке», «ребёнку», «себе», «папе», «в ипэшку», «для универа по академке», «в промку на завод»);
  - строки 31–45 (15): «нет в продаже, нужен ближайший» (`not_sold: true` — домашние линейки Kaspersky, Dr.Web, PRO32, ESET, МойОфис, Р7-Офис, Кибер Бэкап, Microsoft 365 Personal + ушедшие бизнес-линейки ESET PROTECT, Microsoft 365 Business, MS Exchange, MS SQL Server);
  - строки 46–60 (15): «система, а не вендор» (по 3 пробы на каждую из 5 систем: 1С, PostgreSQL, Exchange, MS SQL, Astra Linux — бэкап, мониторинг, защита);
  - строки 61–80 (20): смешанные запросы (комбинации аудитория + платформа + вендор/линейка + жаргон + система + `not_sold`, а также контрольный запрос «лицензия на сервер 1с», где `onec` — именно вендор).
- **Конвенция `expect` при `not_sold: true`:** поле `line` (если у того же вендора есть ближайшая продаваемая бизнес-линейка) или `category` (если весь вендор ушёл из РФ) обозначает целевую ближайшую продаваемую альтернативу для блока `analogs` (29.3). Все идентификаторы `vendor`, `line` и `category` взяты строго из базы знаний.

---

## 5. Ход 7: обновление `probes-audience-r6.jsonl` под возвращённые домашние линейки

В ходе 7 поток A вернул в продажу домашние антивирусные линейки:
- `kaspersky_standard_home` (Kaspersky Standard / Plus / Premium);
- `drweb_security_space` (Dr.Web Security Space);
- `pro32_total_security` (PRO32 Total Security).

> Примечание: рекомендация пункта `A2.7` выше о переводе этих трёх линеек в `catalog: no` утратила силу — в ходе 7 они возвращены в продажу (`catalog: yes`), а для организаций выдаются с пометкой EULA и бизнес-заменами (`kaspersky_ksos`, `drweb_small_business`, `pro32_endpoint_security`).

Состав запросов и общее число строк в `design/proposals/neon4/probes-audience-r6.jsonl` не менялись (**ровно 80 строк**). Исправлены **14 строк**, ранее ожидавших `not_sold: true` для этих линеек:
- **12 строк** (профиль по умолчанию `guest` / домашняя аудитория) — снят `not_sold: true`, ожидается домашняя линейка (`kaspersky_standard_home`, `drweb_security_space`, `pro32_total_security`) или категория `home_antivirus` (для запросов без указания вендора);
- **2 строки** (строки 32 и 34 — запросы с явным названием домашней линейки без семейного контекста) — задан профиль организации `"profile": "smb_trade"`, ожидается домашняя линейка с пометкой EULA и бизнес-заменой (`"eula_note": true`).

### Список 14 изменённых строк

| № | Запрос (`q`) | Профиль | Было (`expect`) | Стало (`expect`) |
|---|---|---|---|---|
| 1 | `антивирус для дома на 3 устройства` | `guest` | `audience: home`, `category: endpoint_security`, `not_sold: true` | `audience: home`, `category: home_antivirus` |
| 21 | `каспер для хоума` | `guest` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_ksos`, `not_sold: true` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_standard_home` |
| 22 | `касперский для домика` | `guest` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_ksos`, `not_sold: true` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_standard_home` |
| 23 | `антивирус маме на ноут` | `guest` | `audience: home`, `platform: windows`, `category: endpoint_security`, `not_sold: true` | `audience: home`, `platform: windows`, `category: home_antivirus` |
| 24 | `доктор веб бабушке на компьютер` | `guest` | `audience: home`, `platform: windows`, `vendor: drweb`, `line: drweb_small_business`, `not_sold: true` | `audience: home`, `platform: windows`, `vendor: drweb`, `line: drweb_security_space` |
| 25 | `антивирус ребёнку на андроид` | `guest` | `audience: home`, `platform: android`, `category: endpoint_security`, `not_sold: true` | `audience: home`, `platform: android`, `category: home_antivirus` |
| 27 | `антивирус папе на макбук` | `guest` | `audience: home`, `platform: macos`, `category: endpoint_security`, `not_sold: true` | `audience: home`, `platform: macos`, `category: home_antivirus` |
| 31 | `касперский для дома` | `guest` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_ksos`, `not_sold: true` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_standard_home` |
| 32 | `kaspersky standard на 3 устройства` | `smb_trade` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_ksos`, `not_sold: true` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_standard_home`, `eula_note: true` |
| 33 | `kaspersky plus для семьи` | `guest` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_ksos`, `not_sold: true` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_standard_home` |
| 34 | `dr web security space на 2 пк` | `smb_trade` | `audience: home`, `vendor: drweb`, `line: drweb_small_business`, `not_sold: true` | `audience: home`, `vendor: drweb`, `line: drweb_security_space`, `eula_note: true` |
| 35 | `доктор веб для дома на год` | `guest` | `audience: home`, `vendor: drweb`, `line: drweb_small_business`, `not_sold: true` | `audience: home`, `vendor: drweb`, `line: drweb_security_space` |
| 36 | `pro32 total security домашний` | `guest` | `audience: home`, `vendor: pro32`, `line: pro32_endpoint_security`, `not_sold: true` | `audience: home`, `vendor: pro32`, `line: pro32_total_security` |
| 65 | `антивирус на 3 компа домой от касперского` | `guest` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_ksos`, `not_sold: true` | `audience: home`, `vendor: kaspersky`, `line: kaspersky_standard_home` |

### Сверка оставшихся `not_sold: true` (11 строк) с `kb/families/*.yaml`

Во всех 11 оставшихся строках с `not_sold: true` целевые линейки имеют `catalog: no` в базе знаний:
- строка 26 (`офис себе на домашний ноут`) — домашние офисные редакции (`myoffice_home`, `r7_office_home`, `microsoft_365_personal`) в `kb/families/home_r3.yaml` имеют `catalog: no`;
- строка 37 (`eset nod32 для дома`) — `eset_home_security` (`catalog: no` в `kb/families/home_r3.yaml`);
- строка 38 (`eset protect на 50 рабочих мест`) — `eset_protect` (`catalog: no` в `kb/families/security.yaml`);
- строка 39 (`мойофис стандартный домашняя версия`) — `myoffice_home` (`catalog: no` в `kb/families/home_r3.yaml`);
- строка 40 (`р7-офис домашний на 1 пк`) — `r7_office_home` (`catalog: no` в `kb/families/home_r3.yaml`);
- строка 41 (`кибер бэкап персональный для домашнего пк`) — `cyber_backup_personal` (`catalog: no` в `kb/families/home_r3.yaml`);
- строка 42 (`microsoft 365 персональный на год`) — `microsoft_365_personal` (`catalog: no` в `kb/families/home_r3.yaml`);
- строка 43 (`microsoft 365 для бизнеса на 30 человек`) — `microsoft_365` (`catalog: no` в `kb/families/office.yaml`);
- строка 44 (`microsoft exchange server лицензия`) — `ms_exchange` (`catalog: no` в `kb/families/office.yaml`);
- строка 45 (`microsoft sql server standard купить`) — `ms_sql_server` (`catalog: no` в `kb/families/databases.yaml`);
- строка 75 (`офис 365 семейный на макбук`) — `microsoft_365_personal` (`catalog: no` в `kb/families/home_r3.yaml`).
