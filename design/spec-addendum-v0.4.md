# Дополнение v0.4 к SPEC.md — третий ход

Действует вместе с `SPEC.md` v0.2 и `design/spec-addendum-v0.3.md`. Там, где тексты расходятся, верно это дополнение.
Общая ветка — `main` (сейчас `21b0312`: движок M2a, аналитика B1, витрина и консоль C2, база знаний r2); она развёрнута на стенде.

## 26.1 Потоки и зоны записи

| Поток | Рабочая копия, ветка | Зона записи |
|---|---|---|
| A · движок | `/home/bb/kuznitsa-softline`, `main` | как в 25.1, **кроме** файлов, переданных потокам B и D в этой таблице |
| B · аналитика | `/home/bb/kuznitsa-softline-analytics`, `analytics` | как в 25.1 **плюс** `kuznitsa/plans/naive.py` (прежний поиск магазина) |
| C · интерфейс | `/home/bb/kuznitsa-softline-ui`, `ui` | как в 25.1 |
| D · данные | `/home/bb/kuznitsa-softline-data`, `data` | `kuznitsa/ingest/**` кроме `history.py`; `kuznitsa/mock/catalog_gen.py`, `naming.py`, `pricing.py`, `sample_codes.py`, `clients_gen.py`, `fallback.tsv`; `tests/ingest/**`, `tests/mock/**`, `tests/test_m2_catalog.py`; `docs/INGEST.md`, `docs/ingest_examples/**`; `design/proposals/data/**` |
| K · база знаний (Gemini) | `/home/bb/kuznitsa-softline-kb`, `kb` | новые файлы `kb/*_r3.yaml`, `kb/families/*_r3.yaml`, `docs/PITCH.md`, `docs/STACK.md`, `design/proposals/neon3/**`, `design/proposals/neon4/**` |

Правила прежние: чужие файлы не правятся; если без вставки в чужой файл не обойтись — она описывается в отчёте дословно.
`git commit`, слияния, выкладку и пересборку данных стенда делает ведущий поток. Наборы `eval/**` в этом ходе заморожены;
`eval/queries.holdout.jsonl` никто не читает и под него не настраивает — контрольный замер делает ведущий.

## 26.2 Живой категоризатор для потоков разработки

На сервере работает локальный шлюз `http://127.0.0.1:8098/decisions`. Он принимает тело Decisions API, сам подставляет ключ
и пропускает только модель `typesafe/jev-1.13`. Общий дневной предел всех потоков — 2 $ (после него ответ 429, движок уходит
в быстрый режим). Состояние: `curl -s http://127.0.0.1:8098/health` → `{"limit_usd", "day", "usd", "calls", "refused"}`.

```bash
KZ_JEV_URL=http://127.0.0.1:8098/decisions OPENROUTER_API_KEY=gateway HF_HUB_OFFLINE=1 \
  /home/bb/kuznitsa-softline/.venv/bin/python -m kuznitsa.cli eval eval/queries.dev.jsonl --mode smart --budget-usd 0.3
```

Значение `OPENROUTER_API_KEY` здесь — любая непустая строка: настоящий ключ есть только у шлюза, искать и печатать его нельзя.
Полный прогон dev в умном режиме стоит около 0,03 $; повтор с теми же вопросами берётся из кэша журнала копии.
Модульные тесты в сеть не ходят никогда — только подменный транспорт.

Замер ведущего на стенде (main `c014d60`, боевой каталог): fast 232/310 = 74,8 %, smart 228/310 = 73,5 %; 346 вызовов,
0,0285 $ за прогон, ≈ 0,0094 ₽ на умный запрос; smart p50 203 мс, p95 411 мс; fast p50 5 мс, p95 28 мс.

## 26.3 Публичный ответ поиска: добавления (делает A, читает C и B)

Форма ответа не ломается — только новые поля.

- `profile.short` — короткое имя профиля для шапки, до 24 знаков («Торговый дом Вектор»); `profile.segment_title` — сегмент
  по‑русски («Малый бизнес», «Госсектор»…).
- `score.tier_label` — подпись уровня соответствия для покупателя (уровни 0–3), например «Точное соответствие»,
  «Подходит по условиям», «Близкий вариант», «Расширенный поиск».
- Каждый элемент `variants[]` несёт те же ключи, что `offer`: `offer_id, sku, name, price, price_on_request, available,
  action, model, term_months, metric, qty_min, qty_max, pack, audience, delivery, version` — у любого источника вариантов.
- `understood.zero_reason` — причина пустой товарной выдачи из закрытого списка или `null`. Это же значение уходит в журнал
  (`journal.search(..., reason, ...)`).

| `zero_reason` | Когда | Что видит покупатель |
|---|---|---|
| `off_topic` | запрос не о программах и ИТ‑услугах: оборудование, посторонние товары, пиратство, бессмыслица | вежливый отказ и разделы каталога, товаров нет |
| `unknown_term` | слово не распознано: его нет ни в каталоге, ни в базе знаний | уточнение и заявка; для бизнеса — кандидат в словарь |
| `not_in_catalog` | известный продукт, вендор или класс ПО, которого нет в каталоге магазина | аналоги и заявка; для бизнеса — пробел ассортимента |
| `vendor_left` | продукт ушедшего с рынка вендора | российские аналоги |
| `filters_too_strict` | товары есть, но все отсечены условиями; `relax_hints` непуст | подсказки «снять условие» |
| `qty_out_of_range` | под запрошенное количество нет ступени или пакета | ближайшие ступени и заявка |
| `no_available_offer` | подходящее есть, но недоступно к заказу или только «цена по запросу» | заявка менеджеру |

## 26.4 Дополнение базы знаний файлами

- Загрузчик читает для каждой группы `kb/<группа>.yaml` **и** `kb/<группа>_*.yaml` (например `kb/slang_r3.yaml`,
  `kb/faq_r3.yaml`); семейства — все `kb/families/*.yaml`, как сейчас. При совпадении ключа выигрывает первое определение
  (основной файл), повтор попадает в отчёт `kb-check` как предупреждение, а не ошибка.
- Автодополнение при импорте каталога: если есть `<KZ_DATA_DIR>/kb_auto.yaml`, его строки добавляются к базе знаний после
  файлов `kb/`. Формат — три необязательных списка в формате `kb/SCHEMA.md`, обязательны только перечисленные поля:

```yaml
vendors:    [{id: auto_v_acme, name: "ACME Soft", aliases: ["акме софт"]}]
categories: [{id: auto_c_geo, parent: null, title: "Геоинформационные системы", synonyms: ["гис"]}]
families:
  - {id: auto_f_acme_planner, vendor: auto_v_acme, name: "ACME Planner", aliases: ["акме планер"], category: auto_c_geo,
     editions: [{id: pro, name: "Pro", aliases: []}], summary: "", catalog: yes}
```

  Идентификаторы автозаписей начинаются с `auto_`; запись базы знаний они не заменяют никогда. Отсутствующие поля
  получают значения по умолчанию, `kb-check` считает автозаписи отдельно, `/health` показывает
  `kb.auto = {vendors, categories, families}`. Без файла движок ведёт себя как сейчас.

## 26.5 Импорт каталога магазина (делает D)

```bash
python -m kuznitsa.cli import-catalog <файл>... [--mapping map.yaml] [--out <каталог данных>] [--report report.json] [--dry-run]
```

- Вход: CSV и TSV (любой разделитель и кодировка), XLSX, JSON, JSONL, YML‑фид (Yandex Market Language). Столбцы
  распознаются по синонимам заголовков и по содержимому; файл соответствия нужен только для спорных случаев.
- Выход в каталоге данных: `catalog.jsonl` в каноническом формате `Offer` (`kuznitsa/schema.py`), `kb_auto.yaml` (26.4),
  `import_report.json`. После этого `build-index` и поиск работают без правок кода.
- Команда живёт в `kuznitsa/ingest/cli.py` с функциями `register(sub)` и `run(args, cfg)` — как `kuznitsa.analytics.cli`;
  поток A подключает её в `kuznitsa/cli.py` через `optional_module("kuznitsa.ingest.cli")`. До слияния она запускается
  напрямую: `python -m kuznitsa.ingest.cli import-catalog …`.
- `import_report.json`:

```json
{"ts": "…", "files": ["…"], "rows": 0, "offers": 0, "rejected": 0, "duplicates": 0,
 "columns": {"name": "Наименование", "price": "Цена, руб."},
 "recognized": {"vendor": 0.0, "family": 0.0, "edition": 0.0, "licence": 0.0, "category": 0.0},
 "auto": {"vendors": 0, "categories": 0, "families": 0},
 "issues": [{"code": "no_price", "title": "Нет цены", "count": 0, "examples": [{"row": 0, "name": "…"}]}],
 "unmatched": {"vendors": [{"name": "…", "rows": 0}], "families": [{"name": "…", "rows": 0}]}}
```

  Поток B отдаёт сводку этого файла в `GET /api/admin/ingest` полем `catalog` (или `null`, если файла нет).

## 26.6 Служебный API: добавления (делает B, читает C)

- `GET /kpi` → `pairs: [{key, label, unit, before, after, better, n_before, n_after, note}]`; `unit` ∈ `rate` (доля 0–1),
  `rub`, `count`, `ms`; `better` ∈ `lower`, `higher`. Обязательные ключи: `zero_rate`, `top5_hit`, `exit_after_fail`,
  `search_to_order`, `lost_orders_rub`. «До» — прежний поиск на истории, «после» — Кузница на тех же запросах; смешивать их
  в одном числе нельзя. Плюс `funnel: [{key, label, count}]` с абсолютными числами этапов.
- `GET /queries?kind=recent&limit=` → `items: [{ts, q, search_id, profile_id, segment, mode, engine, intent, n_cards, ms,
  cost_rub, zero_reason}]`, свежие сверху, источники `ui`, `api`, `gallery`, `compare`.
- У каждого примера запроса в `failures`, `gaps` и `insights.evidence` есть собственный `search_id`.
- `GET /search/{id}` всегда содержит `ts` и `n_cards`; `verification.before/after` — `n_cards` и `search_id` по каждой фразе.
- `GET /cost` → фактические `sent` (внешние вызовы) и `cached`, цена запроса по режимам, прогноз на месяц при заданной
  нагрузке и цена 100 000 запросов.
- `GET /ingest` → `catalog` (26.5).

## 26.7 Цели хода

| Что | Сейчас | Цель |
|---|---|---|
| dev, быстрый режим | 74,8 % | не ниже 82 % |
| dev, умный режим | 73,5 % | не ниже 86 % и выше быстрого |
| запросы показа из `docs/DEMO.md` в обоих режимах | 4 шага из 9 расходятся со сценарием | все совпадают, закреплены тестами |
| скорость | fast p95 28 мс, smart p95 411 мс | fast p95 ≤ 40 мс, smart p95 ≤ 700 мс |
| цена умного запроса | ≈ 0,0094 ₽ | не выше 0,03 ₽ |
| «прежний поиск» в истории: пустая выдача | 73 % | 25–35 %, у Кузницы на тех же запросах 3–8 % |
| конверсия поиска в заказ и чек в истории | 1,41 %, выручка 34,3 млрд ₽ | 2–4 %, медиана заказа 80–250 тыс. ₽, среднее до 600 тыс. ₽ |
