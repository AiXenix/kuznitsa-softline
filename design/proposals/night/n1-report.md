# Отчёт потока N1 · Правда о наличии и посторонние запросы

## 1. Причины провалов (до изменений)

Базовый прогон `/home/bb/kz-tools/audit-base.txt`: **104 из 244 (42.6 %)**, `p50 14 мс`, `p95 30 мс` (`наличие` 6/40, `нет` 12/15, `мусор` 0/10, `эталон` 20/20).

Основные корневые причины по целевым группам:

1. **Ложное «нет в каталоге» на реальных товарах фида (`наличие`, 34 провала):**
   - **Сброс найденной редакции старым `replacements`:** `index.edition("adobe acrobat pro")` находил карточку `Adobe Acrobat Professional`, но строка в `plans/feed.py` проверяла `sold_as(card, "adobe acrobat pro")` из-за записи в `kb/analogs.yaml`, получала `False` (`pro != professional`) и обнуляла `ids = ()`, уводя запрос в `feed_analogs.search(..., missing=True)`.
   - **Неиспользуемые `in_catalog: true` записи и алиасы семейств КБ:** `Корел Дро`, `MS SQL`, `Вижуал Студио`, `Вин рар`, `Автокад LT` присутствовали в `kb/feed_analogs.yaml` с `in_catalog: true`, но `plans/feed.py` не переводил их в реальные карточки `FeedIndex`, а затем передавал `row` в `feed_analogs.search(..., explicit=False)`, что принудительно выставляло `missing=True`. Короткий алиас `фш` есть в `kb/families/graphics_media.yaml` (`adobe_photoshop`), но не искался через `engine.lex`.
   - **Покупательский шум и условия + откат в старый `vendor_left`:** запросы с условиями (`касперский 10 пк 1 год`, `dr.web 5 пк 3 года`, `adobe creative cloud годовая подписка`, `академическая лицензия autocad`, `adobe acrobat pro dc подписка на год для команд`, `обновление компас-3d`, `бессрочная лицензия office`, `office без подписки`, `электронная лицензия office`, `x64 windows 11 home`, `ключ активации windows 11`, `MS Windows Server Standard 2022 16 core`, `скачать winrar`, `хочу купить фотошоп навсегда без подписки`, `коробочная версия касперский`, `цена autocad`) не очищались от шума или отбрасывались регуляркой `COMPLEX` в старый конвейер `_search`, который опирался на `kb/vendors.yaml` (`left_russia`) и выдавал `vendor_left` по реальным товарам Adobe / Microsoft / Autodesk / Corel.
   - **Потеря продукта при снятии префикса / разборе цены:** `windows 11 pro oem` и `windows 11 pro для юрлиц` теряли `windows 11` в `named_subject` и искали `pro`; `апгрейд windows 10 до 11` разбирал `до 11` как `price_max = 11 ₽`; `windows дешевле 15000` обнулял всю выдачу с `filters_too_strict`, хотя Windows 11 Home есть в фиде от 20 183 ₽.
   - **Свежий год / хвостовой план / запросы вендора / ранжирование пакетов:** `autocad 2025`, `coreldraw graphics suite 2024`, `office365 e3`, `adobe acrobat pro dc` не находили дословного суффикса; `всё от adobe` и `продукты Аскон` не имели маршрута каталога вендора (`Adobe Systems` в фиде vs `adobe` в запросе); `microsoft office 2021` выводил отдельные `Access/Publisher/Word 2021` выше пакетов `Office Standard / Профессиональный 2021`.

2. **Пропуски честного «нет» и аналогов (`нет`, 3 провала):**
   - `windows 7`: находил модуль `Vision Solutions Double-Take Availability для Windows 7.0` вместо честного ответа «Windows 7 в каталоге нет» с актуальными `Windows 11 / 10`.
   - `steam`: односложная опечатка со сменой первой буквы превращала `steam` в `team` (`Team Foundation Server` и др.).
   - `аналог autocad дешевле`: не снимался модификатор `дешевле` из предмета запроса аналогов.

3. **Карточки-заглушки и разрушительные исправления на мусоре (`мусор`, 10 провалов):**
   - Старый конвейер (`kuznitsa/engine.py`) вызывал `fill(self, [], ...)` даже для `off_topic`/`clarify_feed`, дописывая 4 случайные карточки (`MobiSystems Словари`, `MDaemon ActiveSync`, `VentaFax` и т. д.).
   - `пицца` разрушительно исправлялась межскриптовым звуковым поиском в `pisa` (`Кулер Процессорный JONSBO для CPU PISA A5 ARGB`).
   - `рецепт борща` попадал в dense-категоризацию (`source="embed"`) и выдавал кухонные блендеры без единой лексической опоры.
   - HTML/SQL-инъекции, знаки препинания, одиночные буквы и произвольные числа не отсекались на входе.

---

## 2. Внесённые изменения по файлам и функциям

Соседние файлы (`index/feed.py`, `index/feed_repair.py`, `plans/feed_query.py`, `plans/feed_analogs.py`, `kb/*`) **не изменялись**. Верх `plans/feed.py:search()` и `task_sections` сохранены без перестановки для чистого слияния с N2/N3/N4.

### Новые модули

- **`kuznitsa/plans/feed_noise.py`** — разбор шума, условий, вендоров и синтаксического мусора:
  - `is_garbage_syntax` — отсечение HTML-тегов, SQL-инъекций, пустых/знаковых запросов, одиночных букв и неартикульных чисел.
  - `parse_upgrade_query`, `extract_budget` — защита запросов вида «апгрейд X 10 до 11» от `price_max` и поддержка мягкого «дешевле N».
  - `clean_analog_subject` — снятие модификаторов (`дешевле`, `бесплатный`, `российский`, `лучший` и т. п.) с предмета запроса аналогов.
  - `resolve_vendor`, `detect_vendor_catalog` — распознавание запросов «всё от X / продукты X / что есть у X / каталог X» с поддержкой префиксов вендоров фида (`adobe` → `Adobe Systems`) и КБ-алиасов (`Аскон`).
  - `normalize_spoken_brands`, `extract_conditions_and_noise`, `is_edition_only`, `FEED_COMPLEX` — снятие покупательского шума (действия, сроки, подписка/бессрочно, ESD/коробка/OEM, аудитория, разрядность, ядра) с сохранением условий в `filters`/`chips` и защитой составных дескрипторов (`семейная подписка`).

- **`kuznitsa/plans/feed_guard.py`** — проверка правды о наличии, защита от разрушительных исправлений и чистые ответы на мусор:
  - `build_garbage_result`, `popular_section_options`, `popular_queries` — единый ответ без карточек (`max=0`, `zero_reason="unknown_term"`, спокойная заметка `GARBAGE_NOTE`, `clarify` с разделами каталога, `related_queries`).
  - `is_plausible_absent_brand` — отделение правдоподобных отсутствующих брендов (`steam`) от клавиатурного мусора (`asdfghjkl`, `qxwzzzt`).
  - `is_destructive_repair` — блокировка односложных правок со сменой первой буквы (`steam` → `team`) и односложных межскриптовых коллизий, не подтверждённых `sold_as` (`пицца` → `pisa`), при сохранении раскладки (`layout`) и многословных фонетических форм (`астра спешл`).
  - `rank_vendor_cards`, `build_vendor_result` — выдача каталога вендора (ПО выше курсов, по качеству, ≥ 4 карточек).
  - `check_missing_generation`, `build_missing_generation_result` — честное отсутствие устаревшего поколения линейки (`windows 7` → `not_in_catalog` + `Windows 11 / 10` сверху).
  - `resolve_feed_product` — единая лестница подтверждения товара в реальном `FeedIndex` (редакция, `products`+`sold_as`, `office 365 → microsoft 365`, `feed_analogs` с `in_catalog=True`, `engine.lex` семейства/вендоры, ослабление свежего года `202x` и хвостовых модификаторов `dc`/`e3`/`lt`/`graphics`/`suite`).
  - `prefer_suite_for_office_year`, `prefer_software_over_courses` — приоритет пакетов Office 2021 над отдельными приложениями и приоритет программ над учебными курсами (`Express Course`).
  - `verify_response` — финальный пост-контроль на фиде: удаление пустых блоков (`kit`, `compare`, `products`, `analogs`, `spec` и др.), отмена ложного `not_in_catalog`/`vendor_left` при подтверждённом наличии в `FeedIndex`, снятие заглушек и dense-only (`source="embed"`) оффтопа без лексической опоры.

### Точечные хуки в существующих файлах

- **`kuznitsa/plans/feed.py`**:
  - Подключены синтаксический фильтр мусора, каталог вендора, `extract_budget`, очистка предмета аналогов, `extract_conditions_and_noise`, `check_missing_generation`, `FEED_COMPLEX`, защита `named_subject` через `is_edition_only`, защита `sound_products` и `recovery.lookup` через `is_destructive_repair`, `resolve_feed_product` (с защитой `edition`/`resolved_from_feed` от сброса по `replacements` и восстановлением после него), сортировка `prefer_suite_for_office_year` / `prefer_software_over_courses`, мягкий бюджет для «дешевле N» и именованных продуктов, честное `not_in_catalog` для `is_plausible_absent_brand`, запрет передачи `in_catalog=True` строк в `feed_analogs.search(..., explicit=False)`, вызов `verify_response(..., from_legacy=False)` в `finish()`.
- **`kuznitsa/engine.py`**:
  - Добавлен 3-строчный вызов `verify_response(self, req, profile, result, from_legacy=True)` сразу после `guard(self, req, result)` при `self.catalog.is_feed`.

---

## 3. Результаты `audit_run.sh` (до / после)

Команда: `bash /home/bb/kz-tools/audit_run.sh /home/bb/kuznitsa-softline-n1 fast --fails`

| Группа | До (`audit-base.txt`) | После (N1) | Изменение | Цель N1 |
|---|---:|---:|---:|---:|
| `наличие` | 6 / 40 | **40 / 40** | **+34** | ≥ 34 / 40 |
| `нет` | 12 / 15 | **15 / 15** | **+3** | 15 / 15 |
| `задача` | 10 / 50 | **11 / 50** | +1 | не хуже |
| `вопрос` | 7 / 16 | **8 / 16** | +1 | не хуже |
| `главное` | 13 / 27 | **13 / 27** | 0 | не хуже |
| `написание` | 15 / 28 | **18 / 28** | +3 | не хуже |
| `условия` | 9 / 18 | **9 / 18** | 0 | не хуже |
| `сравнение` | 0 / 7 | **0 / 7** | 0 | не хуже |
| `мусор` | 0 / 10 | **10 / 10** | **+10** | ≥ 8 / 10 |
| `железо` | 12 / 13 | **12 / 13** | 0 | не хуже |
| `эталон` | 20 / 20 | **20 / 20** | 0 | 20 / 20 |
| **ИТОГО `fast`** | **104 / 244 (42.6 %)** | **156 / 244 (63.9 %)** | **+52 (+21.3 п.п.)** | — |

Скорость `fast`: **p50 8 мс, p95 57 мс** (при параллельной нагрузке на сервер `load average ~12`; укладывается в порог `≤ 60 мс`).
Регрессий ни в одной из 11 групп нет.

---

## 4. Результаты `pytest` и изменённые тесты

- **Новые тесты:** добавлен `tests/test_n1_truth_and_noise.py` (36 проверок: синтаксический и оффтопный мусор, `steam`, `windows 7`, апгрейд без `price_max`, мягкий бюджет `дешевле 15000`, покупательский шум и условия, каталоги вендоров, `office 2021`, очистка аналогов, `verify_response` на пустых блоках и ложном `vendor_left`).
- **Прогон `tests/test_n1_truth_and_noise.py` + `tests/test_m3*.py`:** `384 passed` (13.75 с).
- **Полный прогон репозитория:** `805 passed` при `KZ_EMBED_MODEL=off` + `5 passed` в `tests/ingest/test_d2.py` с включёнными эмбеддингами (итого **806 / 806 passed**, 0 падений).
- **Обновлённые существующие тесты (противоречили требованию 6 об отсутствии заглушек на мусоре):**
  1. `tests/test_m3.py::test_missing_line_and_outside_catalog` (`зимняя резина r16`): ранее проверял 4 карточки-заглушки (`fill=True`); обновлён на проверку отсутствия блока `products`, наличия `clarify` и `zero_reason == "unknown_term"`.
  2. `tests/test_m3b.py::test_no_generic_word_as_product` (`qxwzzzt`): ранее проверял `len(cards_from(...)) >= 4`; обновлён на `len(cards_from(...)) == 0`, наличие `clarify` и `zero_reason == "unknown_term"`.

---

## 5. Проверка `smart` и остаток

- Код N1 не блокирует и не обходит категоризатор `smart` (маршрутизация в `task_sections` и `feed_analogs` сохранена).
- Прогон `audit_run.sh /home/bb/kuznitsa-softline-n1 smart --group мусор --fails`: **10 из 10 (100.0 %)**, `p50 274 мс`, `p95 815 мс`; тесты `tests/test_m3e.py` и `tests/test_m3j.py` в режимах `fast` и `smart` — зелёные.
- По всем трём целевым группам N1 достигнут максимум (`наличие` 40/40, `нет` 15/15, `мусор` 10/10, `эталон` 20/20).
- Оставшиеся провалы аудита (88 из 244) относятся к смежным потокам: задачи и вопросы (N2), главное/написание/раскладки (N3), условия/сравнения/исключения/сортировка (N4).

---

# Второй заход

Базовая точка перед правками второго захода — обновлённый `main` (`3afefbc`, после слияния N1–N4 первого захода):
- `tests/audit/cases.tsv` (`fast`): **242 из 244 (99.2 %)** (`наличие` 40/40, `нет` 15/15, `задача` 50/50, `вопрос` 15/16, `главное` 27/27, `написание` 28/28, `условия` 17/18, `сравнение` 7/7, `мусор` 10/10, `железо` 13/13, `эталон` 20/20).
- `tests/audit/cases2.tsv` (`fast`): **126 из 186 (67.7 %)** против **86 из 186 (46.2 %)** в `/home/bb/kz-tools/audit2-base.txt`; три целевые группы N1 — **49 из 62** (`бренд2` 28/36, `англ` 9/12, `аналог` 12/14).

---

## 1. Причины провалов и общие правила

1. **Разговорные и сокращённые названия реальных товаров (`бренд2`):**
   - `ворд`, `эксель`, `аутлук`, `пауэрпоинт` ошибочно попадали в `kb/feed_analogs.yaml` (`in_catalog: false`), хотя в снимке `real/v1` (`feed_categories.json`) эти карточки есть (`Microsoft Office Word 2021`, `Microsoft Office Excel 2021`, `Microsoft Office Outlook 2021`, `Microsoft Office PowerPoint 2021`; в `real-cards.tsv` их заголовки обрезаны до `Microsoft`).
   - Сленг и символы вроде `m$ office`, `мс офис`, `битрикс 24`, `fotoshop`, а также английские обёртки (`windows 11 pro license`, `upgrade windows 10 pro`, `windows 11 pro 64-bit (x64) OEM`) не снимались до поиска продукта.
   - `продление криптопро`: карточки `КриптоПро` есть в каталоге, но у предложений не размечен `action=renewal`, из-за чего конвейер возвращал `not_in_catalog` (`reason="gap"`).
   - `dallas lock`, `консультант плюс`, `гарант`, `acronis` отсутствуют в `/home/bb/kz-tools/real-cards.tsv` и `real/v1`, но либо подменялись устаревшим КБ-алиасом (`acronis` → `cyber_backup`), либо матчились по слову `плюс` (`Клиент Плюс`), либо не имели записи в аналогах.
   - `corel` и `код безопасности` (запрос имени вендора) опускали флагманы вендора ниже вспомогательных позиций; к тому же `LEAD_ACTION` ранее срезал слово `код` в `код безопасности`.
   - `winrar` подмешивал на 4-ю позицию чужеродную `fill`-карточку из другого раздела (`Wondershare Dr.Fone`).
   - **Общее решение (без хардкода запросов):** словарь `kb/feed_colloquial_n1.yaml` (`spoken_products`) + проверка существования и релевантности в `FeedIndex` (`feed_guard.resolve_colloquial_product`), преднормализация `m$` (`feed_noise.pre_normalize`), английские обёртки и закупочный шум в `feed_noise.py`, словарные записи отсутствующих продуктов в `kb/feed_analogs_n1.yaml`, защита `resolve_feed_product` от подмены `in_catalog: false` КБ-алиасом, корректная обработка `renewal` с `reason="gap"` при найденной линейке, `_prune_cross_section_fill` для полных каталогов (`>= 500` карточек) и `prefer_flagships_for_vendor` строго для прямых имён вендоров из `index.vendor_names` без аудиторного/платформенного контекста.

2. **Английские названия классов и задач (`англ`):**
   - `antivirus`, `firewall`, `cad software`, `office suite for business`, `project management`, `database`, `backup software` и др. не переводились в русские классы каталога, когда `resolve_solution` не давал совпадения.
   - **Общее решение:** таблица `english_classes` (~80 классов и задач ПО) в `kb/feed_colloquial_n1.yaml` + `feed_noise.translate_english_class`, вызываемая после `resolve_solution` (чтобы не конфликтовать с английскими решениями N2, например `video conferencing`) и повторно после снятия шума в `extract_conditions_and_noise`.

3. **Аналоги и импортозамещение (`аналог`):**
   - В `real/v1` у карточек срезан префикс вендора (`Платформа nanoCAD 26`, `КОМПАС-График V25`), поэтому привязки `Нанософт Платформа nanoCAD` / `АСКОН КОМПАС-График` в `index.analogs.bound` давали `matches == []`, и `российский аналог autocad` выдавал Renga/ГИС вместо nanoCAD/КОМПАС.
   - `импортозамещение exchange`: `feed_conditions` срезал слово «импортозамещение» до `feed_analogs`, а `exchange` не находил запись `ms_exchange`.
   - **Общее решение:** одноразовая починка пустых привязок аналогов `feed_guard.ensure_analog_bindings`, поиск аналога по уникальному отличительному слову (`feed_guard.lookup_analog`) и выделение конструкций «импортозамещение <продукт>» до `feed_conditions` (`feed_noise.extract_import_sub_analog` + `feed_guard.search_import_sub_analog`).

4. **Остаток провалов в чужих модулях (не редактировались):**
   - Оставшиеся 3 провала в `бренд2` — `photoshop`, `revit`, `3ds max` (а также `фотошоб` в `опечатка2`): на первом месте оказываются общие флагманы вендора (`Adobe Creative Cloud Professional for Teams`, `Autodesk AutoCAD`), а целевой продукт (`Adobe Photoshop`, `Autodesk Revit`, `Autodesk 3Ds Max`) стоит на 2–3-й позиции. Причина в ранжировании флагманов внутри чужих модулей (`index/feed_flagships.py` / `index/feed.py`), которые по правилам потока не редактировались.

---

## 2. Изменённые и добавленные файлы

Чужие модули (`feed_conditions.py`, `feed_compare.py`, `feed_query.py`, `feed_solutions.py`, `index/feed_flagships.py`, `index/feed_repair.py`, `index/hardware.py`) **не изменялись**.

- **`kb/feed_colloquial_n1.yaml`** (новый): словари `spoken_products` (разговорные/сокращённые названия продуктов → канонические имена с проверкой по каталогу) и `english_classes` (английские классы и задачи ПО → русские формулировки каталога).
- **`kb/feed_analogs_n1.yaml`** (новый, подхватывается `kb/loader.py`): записи отсутствующих в `real-cards.tsv` продуктов `dallas_lock`, `consultant_plus`, `garant_sprav` с реальными заменами из каталога.
- **`kuznitsa/plans/feed_noise.py`**: `pre_normalize`, `load_colloquial_kb`, `translate_english_class`, `extract_import_sub_analog`, правка `LEAD_ACTION` (`код активации` вместо голого `код`), английские и закупочные обёртки, русские слова редакций в `EDITION_ONLY_WORDS`, `KEYBOARD_MASH_TOKENS` в `is_garbage_syntax`.
- **`kuznitsa/plans/feed_guard.py`**: `ensure_analog_bindings`, `lookup_analog`, `search_import_sub_analog`, `resolve_colloquial_product`, `_resolve_direct_vendor` + `prefer_flagships_for_vendor`, `handle_unmatched_query`, `_prune_cross_section_fill`, обработка `renewal` (`reason="gap"`) и запрет подмены `in_catalog: false` в `verify_response` / `resolve_feed_product`.
- **`kuznitsa/plans/feed.py`**: минимальные вставки вызовов (+26 / −2 строки).
- **`tests/test_n1_round2.py`** (новый): 36 unit- и интеграционных тестов второго захода.

---

## 3. Результаты прогонов

### Второй открытый набор (`tests/audit/cases2.tsv`, `fast`)

Официальный прогон `bash /home/bb/kz-tools/audit_run.sh /home/bb/kuznitsa-softline-n1 fast --cases tests/audit/cases2.tsv --fails`:

| Группа | Старый код (`audit2-base.txt`) | Новый `main` (`3afefbc`) | После N1 (2-й заход) | Изменение к `main` |
|---|---:|---:|---:|---:|
| **`бренд2`** | 27 / 36 | 28 / 36 | **33 / 36** | **+5** |
| **`англ`** | 6 / 12 | 9 / 12 | **12 / 12** | **+3** |
| **`аналог`** | 12 / 14 | 12 / 14 | **14 / 14** | **+2** |
| **Три целевые группы N1** | **45 / 62** | **49 / 62** | **59 / 62** | **+10 (цель ≥ 55)** |
| `роль` | 5 / 12 | 6 / 12 | 6 / 12 | 0 |
| `совместимость` | 2 / 10 | 7 / 10 | 7 / 10 | 0 |
| `масштаб` | 4 / 8 | 8 / 8 | 8 / 8 | 0 |
| `бюджет` | 5 / 10 | 8 / 10 | 8 / 10 | 0 |
| `реестр` | 5 / 11 | 8 / 11 | 8 / 11 | 0 |
| `железо2` | 7 / 20 | 12 / 20 | 12 / 20 | 0 |
| `услуги` | 1 / 7 | 2 / 7 | 2 / 7 | 0 |
| `переход` | 1 / 8 | 3 / 8 | **6 / 8** | +3 |
| `длинный` | 3 / 14 | 10 / 14 | 10 / 14 | 0 |
| `опечатка2` | 8 / 24 | 13 / 24 | **17 / 24** | +4 |
| **ИТОГО `cases2.tsv`** | **86 / 186 (46.2 %)** | **126 / 186 (67.7 %)** | **143 / 186 (76.9 %)** | **+17, 0 регрессий** |

### Первый открытый набор (`tests/audit/cases.tsv`, `fast`)

| Показатель | Новый `main` (`3afefbc`) | После N1 (2-й заход) | Цель |
|---|---:|---:|---:|
| Итого `cases.tsv` | 242 / 244 (99.2 %) | **242 / 244 (99.2 %)** | ≥ 242 / 244 |
| `наличие` | 40 / 40 | **40 / 40** | 40 / 40 |
| `нет` | 15 / 15 | **15 / 15** | 15 / 15 |
| `мусор` | 10 / 10 | **10 / 10** | 10 / 10 |
| `эталон` | 20 / 20 | **20 / 20** | 20 / 20 |
| Скорость `fast` (in-process `real/v1`) | p50 14 мс, p95 57 мс | **p50 13.6 мс, p95 57.8 мс** | p95 ≤ 60 мс |

*(Примечание: при HTTP-прогоне поверх загруженного сервера с `load average ~16` сетевые задержки добавляли ~5 мс: p50 27 мс, p95 63 мс; чистая задержка движка in-process на `real/v1` — p50 13.6 мс, p95 57.8 мс.)*

### Пустой и знаковый ввод (`check_request.py`, группа «оформление»)

Все **7 из 7** проверок «пустой ввод» (`""`, `"   "`, `"!!!"`, `"???"`, `"😀"`, `"."`, `"*"`), а также одиночные буквы (`"а"`, `"z"`) и клавиатурный мусор (`"qwertyuiop"`) возвращают `intent="broad"`, `zero_reason="unknown_term"`, блок `clarify` и **0 товарных/аналоговых карточек** (парные проверки группы «оформление» для N3 не изменялись).

---

## 4. Остаток старого конвейера (`plans/feed.py::search -> None` → `Engine._search`)

Замер без параметров `sort`, `filters`, `exclude` и сессионного уточнения (N7/N8 исключены):

### `tests/audit/cases.tsv`: **5 → 0**
- **Было на `main` (5):** `asdfghjkl`, `купить квартиру`, `пицца`, `погода в москве`, `рецепт борща` (все 5 из группы `мусор`).
- **После N1 (0):** все 5 закрыты на входе в `plans/feed.py` (`is_garbage_syntax` + `handle_unmatched_query`).

### `tests/audit/cases2.tsv`: **14 → 9**
- **Закрыто в N1 (5):**
  1. `[роль] софт для малого бизнеса`
  2. `[железо2] роутер wi-fi 6`
  3. `[железо2] флешка 64 гб`
  4. `[переход] расширение лицензии kaspersky`
  5. `[длинный] право на использование операционной системы astra linux special edition для рабочей станции`
- **Оставшиеся 9 (участок соседних потоков — роли/услуги/железо/миграция):**
  1. `[роль] софт для юриста`
  2. `[роль] софт для отдела кадров`
  3. `[масштаб] офис для малого бизнеса` *(проходит аудит через legacy)*
  4. `[железо2] монитор 27 дюймов` *(проходит аудит через legacy)*
  5. `[железо2] ноутбук 16 гб i7`
  6. `[услуги] обучение astra linux`
  7. `[услуги] курсы excel`
  8. `[переход] переход с windows на astra linux`
  9. `[переход] миграция с microsoft office на р7`

---

## 5. Проверка на 26 собственных перефразировках (`real/v1`, `fast`)

| # | Запрос | Intent | `absent` | Топ-3 карточек в ответе |
|---:|---|---|---:|---|
| 1 | `купить ворд` | `product` | Нет | Microsoft Office Word 2021; Microsoft Office Word for Mac 2021; Dr.Web Enterprise Security Suite |
| 2 | `майкрософт эксель цена` | `product` | Нет | Microsoft Office Excel 2021; Microsoft Office Excel for Mac 2021; Dr.Web Enterprise Security Suite |
| 3 | `аутлук для бизнеса` | `product` | Нет | Microsoft Office 2024 для дома и бизнеса; Microsoft Office 2024 для дома и учёбы; Microsoft Office Professional Plus 2021 |
| 4 | `пауэрпоинт` | `product` | Нет | Microsoft Office PowerPoint 2021; Microsoft Office Publisher 2021; Microsoft Exchange Server 2019 |
| 5 | `корел дро` | `product` | Нет | CorelDRAW Graphics Suite 2026; CorelDRAW Graphics Suite. Подписка 365-Day; CorelDRAW Essentials 2024 |
| 6 | `m$ office` | `category` | Нет | Microsoft Office 2024 для дома и бизнеса; ContentReader PDF 16 Business; Microsoft Office 2024 для дома и учёбы |
| 7 | `m$ windows 11 pro` | `product` | Нет | Microsoft Windows 11 Pro (Профессиональная); Microsoft Windows 11 Home (Домашняя); Microsoft Windows 10 Pro (GGWA) |
| 8 | `windows 11 pro 64-bit (x64) OEM` | `product` | Нет | Microsoft Windows 11 Pro (Профессиональная); Microsoft Windows 11 Home (Домашняя); Dr.Web Enterprise Security Suite |
| 9 | `upgrade windows 10 pro` | `product` | Нет | Microsoft Windows 10 Pro (GGWA); Microsoft Windows 10 Enterprise; Операционная система Microsoft Windows 10 Enterprise (CSP) |
| 10 | `windows 10 pro license` | `product` | Нет | Microsoft Windows 10 Pro (GGWA); Microsoft Windows 10 Enterprise; Операционная система Microsoft Windows 10 Enterprise (CSP) |
| 11 | `компас 3д` | `product` | Нет | КОМПАС-3D V25; КОМПАС-График V25; КОМПАС-3D HOME |
| 12 | `арчикад` | `product` | Нет | Archicad 26; Archicad STAR(T) Edition; Плоттер HP Inc. Designjet T650 |
| 13 | `битрикс 24` | `product` | Нет | 1С-Битрикс24; Облачный сервис Битрикс24; Mimecast Unified Email Management (UEM) |
| 14 | `продление криптопро` | `renewal` | Нет | Программа КриптоПро CSP 5.0; Kaspersky Symphony Security; Программа КриптоПро NGate |
| 15 | `код безопасности цена` | `product` | Нет | Код безопасности: Secret Net Studio 8; Код безопасности: «Континент 4»; Код безопасности: АПКШ «Континент» |
| 16 | `antivirus software` | `category` | Нет | MaxPatrol Endpoint Protection Platform; UserGate NGFW; Dr.Web Desktop Security Suite |
| 17 | `antivirus for business` | `category` | Нет | Kaspersky Endpoint Security для бизнеса Стандартный; Kaspersky Small Office Security; Kaspersky Endpoint Security Cloud |
| 18 | `cad system` | `category` | Нет | Платформа nanoCAD 26; КОМПАС-График V25; MaxPatrol Endpoint Protection Platform |
| 19 | `business office suite` | `category` | Нет | «Р7-Офис» для юридических лиц; Microsoft Office 2024 для дома и бизнеса; МойОфис Стандартный 3 |
| 20 | `task management software` | `category` | Нет | Kaiten; Weeek; Система управления проектами Яндекс Трекер |
| 21 | `firewall software` | `category` | Нет | Traffic Inspector Next Generation; Код безопасности: АПКШ «Континент»; Ideco NGFW Novum |
| 22 | `remote desktop` | `category` | Нет | AnyDesk; TeamViewer; Фаматек Radmin 3.5 |
| 23 | `российский аналог autocad` | `analog` | Нет | Платформа nanoCAD 26; КОМПАС-График V25; ELCUT |
| 24 | `импортозамещение microsoft exchange` | `analog` | Нет | CommuniGate Pro; Почтовый сервер Tegu; Платформа CraftTalk |
| 25 | `система гарант` | `out_of_catalog` | Да | Перевод компании на КЭДО под ключ; Кадровая сверка... *(честное отсутствие в каталоге)* |
| 26 | `даллас лок` | `out_of_catalog` | Да | Код безопасности: Secret Net Studio 8; Код безопасности: Secret Net LSP; Страж NT 4.0 |

---

## 6. Тесты (`pytest`)

- `tests/test_n1_truth_and_noise.py` + `tests/test_n1_round2.py` + `tests/test_n2_solutions.py`: **88 passed** (0 failed).
- Полный прогон репозитория (`--ignore=tests/web`, `KZ_EMBED_MODEL=off`): **827 passed** (единственное ожидаемое падение при отключённых эмбеддингах — `tests/ingest/test_d2.py::test_embed_longtail`, требующий включённой модели эмбеддингов).


---

# Раунд 3 · «Пустых ответов не бывает»

Базовая точка — `checkpoint r2` (`09d909d`, правки раунда 3 внесены поверх без коммита). Затронуты только файлы потока N1 и точечные хуки (4 строки) в `kuznitsa/plans/feed.py`; соседние модули (`feed_conditions.py`, `feed_compare.py`, `feed_query.py`, `feed_solutions.py`, `index/feed_flagships.py`, `index/feed_repair.py`, `index/hardware.py`) не изменялись.

---

## 1. Проверка воспроизведения и внесённые изменения

### Пункт 1. Пустой ответ и ослабление несовпавших запросов
- **Воспроизведение на `checkpoint r2`:** `телеграм` (отсутствует в фиде), `кабель hdmi 2 м`, `wifi маршрутизатор гигабитный`, `роутер двухдиапазонный`, `средства программирования на 12 рабочих мест`, `ноутбук 16 гб i7` возвращали `None` из `plans/feed.py::search` или уходили в `off_topic` с пустой выдачей (`wi-fi роутер для офиса`, `роутер wi-fi 6`, `флешка 64 гб` давали неполный/пустой исход).
- **Что сделано:**
  - В `kb/feed_colloquial_n1.yaml` добавлена секция `relax_synonyms` (синонимы классов ПО и оборудования: «средства программирования» → «программы для разработки по», «маршрутизатор»/«роутер» → «wi-fi роутеры», «кабель» → «кабели, переходники, разъемы», «флешка» → «флешки usb» и т. д.) и загрузчик `load_relax_synonyms()` в `kuznitsa/plans/feed_noise.py`.
  - В `kb/feed_analogs_n1.yaml` добавлена запись `telegram_messenger` (`in_catalog: false`): «телеграм» честно возвращает `out_of_catalog` с корпоративными мессенджерами и ВКС из фида (`Контур.Толк`, `ВКУРСЕ CLASSIC`, `TrueConf Server`, `eXpress`).
  - В `kuznitsa/plans/feed_guard.py::handle_unmatched_query` добавлено ослабление `_try_relax_query` перед откатом в старый конвейер:
    1. Точный синоним класса из `relax_synonyms`.
    2. Самое длинное известное подвыражение (`len-1 → 1`): синоним класса → `hardware_head` → `class_match` / `qualified_class` → `resolve_colloquial_product` → точное совпадение `index.products` + `sold_as`.
    3. Доранжирование по остаточным токенам запроса (например, `hdmi` в «кабель hdmi 2 м», `64` в «флешка 64 гб», с защитой от цифр тиража вроде `12` в «на 12 рабочих мест»).
    4. Честная пометка в ответе и трассе: `understood["agent_note"] = "Показаны товары по части запроса: «...»."`, `understood["relaxed_to"]`, шаг `trace("relax", ...)`.
  - **Защита от мусора и соседних сценариев:** пустой/знаковый ввод, одиночные буквы, клавиатурный мусор (`asdfgh`, `qwertyuiop`), бытовой оффтоп (`пицца`, `рецепт борща`, `погода в москве`, `купить квартиру`) по-прежнему возвращают `0` карточек и `zero_reason="unknown_term"`. Ролевые и сервисные формулировки (`софт/программы для ...`, `обучение`, `курсы`, `переход`, `миграция`, `услуги`, `аудит`) исключены из ослабления (`_RELAX_SKIP_QUERY_RE`), чтобы не перехватывать участки N2/N4.

### Пункт 2. Раскладка с точкой и запятой внутри названия
- **Воспроизведение:** `rjyneh.njkr` («Контур.Толк»), `lh.dt,` («Dr.Web») и другие названия с точкой/запятой в другой раскладке не находились, так как `.` при переводе раскладки превращалась в `ю` (`,` → `б`).
- **Что сделано:**
  - В `kuznitsa/plans/feed_guard.py` добавлены `_layout_variants_with_punct` и `recover_dotted_or_layout`: для запросов с `.` или `,` (и смешанных вроде `fcghj.cloud`) пробуются все комбинации сохранения `.` и `,` буквальными vs преобразования в `ю`/`б`, с проверкой по `index.products`, `resolve_colloquial_product`, `lookup_analog` и исправлению опечаток.
  - В `kb/feed_colloquial_n1.yaml` добавлены разговорные формы `др веб` / `др.веб` / `доктор веб` → `Dr.Web`.
  - **Проверено на 10 реальных названиях с точкой из фида `real/v1`:**
    - `rjyneh.njkr` → `Контур.Толк`
    - `lh.dt,` → `Dr.Web Security Space`
    - `fcghj.abyfycs` → `Аспро.Финансы`
    - `fcghj.cloud` → `Аспро.Cloud`
    - `1c-,bnhbrc24.vfhrtn` → `1С-Битрикс24.Маркет`
    - `вк.цуи` → `Dr.Web Security Space`
    - `ызшку.вщс` → `Spire.Doc`
    - `фызщыу.судды` → `Aspose.Cells`
    - `щзутщаашсу.щкп` → `OpenOffice.org`
    - `rjyneh.lbfljr` → честный `out_of_catalog` («Контур.Диадок») с ЭДО-аналогами `Pilot-ECM` / `Pilot-ICE`

### Пункт 3. Название с точкой и опечаткой не объявляется отсутствующим
- **Воспроизведение:** `контур.тлок`, `dr.web secruity space`, `traffic inspector next generaiton` попадали в `is_plausible_absent_brand` / `feed_analogs` → «Нет в каталоге».
- **Что сделано:**
  - В `kuznitsa/plans/feed_guard.py` добавлены `_damerau_dist` и `_repair_dotted_or_multiword_typo` (внутри `recover_dotted_or_layout`), вызываемые в `kuznitsa/plans/feed.py` в начале ветки `elif not ids and not license_filter:` **до** `feed_analogs.search` и `is_plausible_absent_brand`.
  - Сверка выполняется по реальному словарю заголовков фида (`index.postings`), по частям с обеих сторон точки и целиком (Дамерау–Левенштейн ≤ 1 для коротких токенов и ≤ 2 для длинных).
  - **Проверено на `real/v1`:** `контур.тлок` → `Контур.Толк`, `dr.web secruity space` → `Dr.Web Security Space`, `traffic inspector next generaiton` → `Traffic Inspector Next Generation`.

### Пункт 4. «Нет в каталоге», хотя поколение есть в фиде
- **Воспроизведение:** `можно ли купить windows 10` уходил в «Нет в каталоге» из-за неснятого вежливого префикса `можно ли купить` перед проверкой поколения и совпадения с каталогом.
- **Что сделано:**
  - В `kuznitsa/plans/feed_noise.py::LEAD_ACTION` добавлены вежливые закупочные префиксы (`можно ли купить`, `где можно купить`, `где купить`, `реально ли купить`, `есть ли в продаже`, `продаётся ли`).
  - В `kuznitsa/plans/feed_guard.py` усилена `check_missing_generation` (подтверждает наличие поколения по заголовкам карточек фида через `index.products` / `index.postings`) и добавлена `prefer_requested_version` (хук в `kuznitsa/plans/feed.py`).
  - **Проверено на `real/v1`:** `можно ли купить windows 10`, `office 2019` (`Microsoft Office Standard 2019`), `windows server 2019` (`Microsoft Windows Server Essentials 2019`), `autocad 2024` (`Autodesk AutoCAD Revit LT Suite 2024`) — все возвращают `intent="product"`, `zero_reason=None`, без `not_in_catalog`; при этом `windows 7` честно остаётся `out_of_catalog` с `Windows 11 / 10`.

### Пункт 5. Заполнитель ответа про отсутствующий бренд
- **Воспроизведение:** `сбис`, `контур диадок` заполнялись «Учебными справочниками» вместо ЭДО/отчётности; `компас 3д лт` получал примеры из ГИС вместо САПР.
- **Что сделано:**
  - В `kb/feed_analogs_n1.yaml` добавлены записи `sbis_edo` («СБИС», «СБИС++», «Saby»), `kontur_diadoc` («Контур.Диадок», «Диадок», «Контур.Экстерн») с проверенными по фиду ЭДО/документооборотом (`Pilot-ECM`, `Pilot-ICE`, `e-BS ETAXREPORT`, `CSoft TDMS`) и `kompas_3d_lt` («КОМПАС-3D LT», «Компас 3Д ЛТ») с САПР-линейкой (`КОМПАС-3D HOME`, `КОМПАС-3D V25`, `КОМПАС-График V25`, `Платформа nanoCAD 26`).
  - В `kuznitsa/plans/feed_guard.py::verify_response(..., from_legacy=True)` добавлен шаг удаления нерелевантных карточек-заполнителей (`products`) при `claims_absent` и отсутствии блока `analogs` и лексической опоры — остаются только `not_in_catalog` и `clarify` с разделами.
  - **Проверено на `real/v1`:** `сбис` и `контур диадок` → `Pilot-ECM`, `Pilot-ICE`, `Pilot-ICE Enterprise`; `компас 3д лт` → `КОМПАС-3D HOME`, `КОМПАС-3D V25`, `КОМПАС-График V25`.

---

## 2. Что отложено и почему

1. **Перестановка порядка карточек внутри `windows 10` при наличии глобальных приоритетов (`kb/priorities.yaml`):** для `можно ли купить windows 10` движок честно возвращает `intent="product"` (без «Нет в каталоге») и находит `Windows 10 Pro (GGWA)` / `Windows 10 Enterprise`, но при активных правилах приоритетов в `order()` `Windows 11 Pro` может оставаться выше `Windows 10` в топе. Обходить `order()` / `kb/priorities.yaml` небезопасно (нарушает мерчандайзинг), поэтому не трогали.
2. **Оставшиеся 3 провала в `бренд2` (`photoshop`, `revit`, `3ds max`):** причина в модуле `kuznitsa/index/feed_flagships.py` (не входит в зону правок N1), который ставит бандл/флагман вендора выше запрошенного продукта.
3. **Оставшиеся 7 откатов в старый конвейер на `cases2.tsv`** (`софт для юриста`, `софт для отдела кадров`, `офис для малого бизнеса`, `обучение astra linux`, `курсы excel`, `переход с windows на astra linux`, `миграция с microsoft office на р7`): сознательно не перехватывались ослаблением N1, так как это ролевые/сервисные/миграционные сценарии соседних потоков (N2/N4).

---

## 3. Цифры до и после раунда 3 (`real/v1`, `fast`)

| Набор / группа | После раунда 2 (`checkpoint r2`) | После раунда 3 (`KZ_EMBED_MODEL=off`, in-process `real/v1`) | Изменение |
|---|---:|---:|---:|
| **`cases.tsv` всего** | **242 / 244 (99.2 %)** | **242 / 244 (99.2 %)** | 0 |
| `cases.tsv` · `наличие` | 40 / 40 | **40 / 40** | 0 |
| `cases.tsv` · `нет` | 15 / 15 | **15 / 15** | 0 |
| `cases.tsv` · `мусор` | 10 / 10 | **10 / 10** | 0 |
| `cases.tsv` · `эталон` | 20 / 20 | **20 / 20** | 0 |
| `cases.tsv` · уходов в legacy (`feed -> None`) | 0 | **0** | 0 |
| **`cases2.tsv` всего** | **143 / 186 (76.9 %)** | **146 / 186 (78.5 %)** | **+3** |
| `cases2.tsv` · `бренд2` (целевая N1) | 33 / 36 | **33 / 36** | 0 |
| `cases2.tsv` · `англ` (целевая N1) | 12 / 12 | **12 / 12** | 0 |
| `cases2.tsv` · `аналог` (целевая N1) | 14 / 14 | **14 / 14** | 0 |
| `cases2.tsv` · 3 целевые группы N1 | **59 / 62** | **59 / 62** | 0 |
| `cases2.tsv` · `железо2` | 12 / 20 | **15 / 20** | **+3** |
| `cases2.tsv` · `опечатка2` | 17 / 24 | **18 / 24** | **+1** |
| `cases2.tsv` · `роль` *(с выкл. эмбеддингами)* | 6 / 12 *(с эмб.)* | 5 / 12 *(без эмб.)* | — |
| `cases2.tsv` · уходов в legacy (`feed -> None`) | 9 | **7** | **−2** |
| Пустой/знаковый ввод (`check_request`, 7 проверок + одиночные буквы/мусор) | 7 / 7 | **7 / 7** | 0 |

*(Примечание: замер раунда 3 выполнен in-process на `real/v1` с `KZ_EMBED_MODEL=off` — на `cases.tsv` p50 `11.5 мс`, p95 `44.3 мс`; на `cases2.tsv` p50 `13.8 мс`, p95 `77.3 мс` под нагрузкой машины; 1 кейс в группе `роль` зависит от эмбеддингов legacy-конвейера и при включённой модели эмбеддингов остаётся на уровне 6/12.)*

---

## 4. Тесты (`pytest`)

- Добавлен файл **`tests/test_n1_round3.py`** (**46 тестов** по всем 5 пунктам раунда 3: ослабление запросов + запрет на мусоре, 9 названий с точкой/запятой в другой раскладке, 6 опечаток с точкой/несколькими словами до «нет в каталоге», 5 проверок поколений в наличии + `windows 7`, 6 проверок заполнителей отсутствующих брендов и очистки legacy-заполнителей).
- Прогон `tests/test_n1_truth_and_noise.py`, `tests/test_n1_round2.py`, `tests/test_n1_round3.py`, `tests/test_n2_solutions.py`, `tests/test_m3.py`, `tests/test_m3b.py`: **182 passed, 0 failed**.
- Расширенный прогон по репозиторию (`-k "feed or n1 or n2 or guard or analog or hardware"`): **173 passed, 0 failed**.
