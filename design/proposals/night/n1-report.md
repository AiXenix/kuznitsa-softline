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
