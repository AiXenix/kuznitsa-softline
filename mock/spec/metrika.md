# Спецификация выгрузок в формате Яндекс Метрики (`var/data/mock_metrika/`)

Автор: Gemini 4 Neon-2 (команда **AiXenix**).
Назначение: точная схема 3 файлов выгрузки в духе Яндекс Метрики (отчёт «Поисковые фразы на сайте» + сырые логи Logs API «Визиты» и «Хиты» с целями и `ecommerce`), генерируемых из тех же 90-дневных сессий, что и `kuznitsa.sqlite` (`SPEC.md` §14.5, §19), плюс правила обратного импорта для адаптера `M4` (готовность к реальным выгрузкам организаторов 26 ноября).

---

## 1. Общие правила генерации

- **Каталог вывода:** `var/data/mock_metrika/`
- **Источник истины:** ровно те же ~24 000 сессий / 45 000 поисков за 90 дней, сгенерированные по `mock/spec/querylog.yaml`.
- **Кодировка и время:** UTF-8 (для CSV — с BOM `utf-8-sig` или стандартный UTF-8, разделитель `;`, кавычки `"`); временны́е метки в `Europe/Moscow` (`YYYY-MM-DD HH:MM:SS`).
- **Синтетические идентификаторы:**
  - `ym:s:clientID` / `ym:pv:clientID` — детерминированный 19-значный числовой ID посетителя (1-в-1 с `client_id` или уникальным гостем);
  - `ym:s:visitID` — детерминированный 19-значный ID визита (1-в-1 с `session_id`);
  - `ym:pv:watchID` — монотонно возрастающий 19-значный ID хита.

---

## 2. Словарь целей Метрики (`goals_map`)

| `goal_id` | Код цели | Название в интерфейсе Метрики | Событие в `kuznitsa.sqlite` |
|---|---|---|---|
| `301001` | `search_used` | Поиск на сайте | Запись в `searches` |
| `301002` | `search_zero_results` | Пустой результат поиска | `searches.zero = 1` |
| `301003` | `search_suggest_click` | Клик по поисковой подсказке | `events.type = 'suggest_click'` |
| `301004` | `product_card_click` | Переход в карточку из поиска | `events.type = 'click'` |
| `301005` | `add_to_cart` | Добавление лицензии в корзину | `events.type = 'cart'` |
| `301006` | `request_quote` | Запрос КП / «Цена по запросу» | `events.type = 'lead'` |
| `301007` | `order_placed` | Заказ оформлен (счёт выставлен) | `events.type = 'order'` |
| `301008` | `renewal_click` | Клик «Продлить лицензию» | `events.type = 'click'` (`action=renewal`) |

---

## 3. Файл 1: Отчёт «Поисковые фразы на сайте» (`metrika_search_phrases.csv`)

Имитирует стандартную CSV-выгрузку отчёта Яндекс Метрики *«Отчёты → Содержание → Поиск по сайту»* за 90 дней.

### Колонки CSV (разделитель `;`)

| № | Заголовок колонки | Тип | Описание / расчёт |
|---|---|---|---|
| 1 | `Поисковая фраза` | `string` | Сырой текст запроса (`searches.q_raw`, многострочные свёрнуты в одну строку через ` | `) |
| 2 | `Поиски` | `int` | Число выполнений фразы за 90 дней |
| 3 | `Визиты` | `int` | Число уникальных сессий (`session_id`) с этой фразой |
| 4 | `Посетители` | `int` | Число уникальных `clientID` |
| 5 | `Отказы` | `float` (0..1) | Доля визитов с `ym:s:bounce = 1` (выход без клика / < 15 сек) |
| 6 | `Глубина просмотра` | `float` | Среднее число хитов в визитах с этой фразой |
| 7 | `Время на сайте` | `int` (сек) | Средняя длительность визита |
| 8 | `Доля пустых выдач` | `float` (0..1) | Доля поисков с `zero = 1` (дополнительная колонка отчёта поиска по сайту) |
| 9 | `Достижения цели: Поиск на сайте` | `int` | Счётчик `goal_id = 301001` |
| 10 | `Достижения цели: Добавление в корзину` | `int` | Счётчик `goal_id = 301005` |
| 11 | `Достижения цели: Запрос КП` | `int` | Счётчик `goal_id = 301006` |
| 12 | `Достижения цели: Заказ оформлен` | `int` | Счётчик `goal_id = 301007` |
| 13 | `Доход (₽)` | `float` | Суммарная выручка заказов в визитах с этой фразой |

### Пример строк `metrika_search_phrases.csv`

```csv
Поисковая фраза;Поиски;Визиты;Посетители;Отказы;Глубина просмотра;Время на сайте;Доля пустых выдач;Достижения цели: Поиск на сайте;Достижения цели: Добавление в корзину;Достижения цели: Запрос КП;Достижения цели: Заказ оформлен;Доход (₽)
"каспер продление на 30 компов";246;214;162;0.14;4.8;312;0.00;246;48;6;27;1530900.00
"адешка под линукс";184;112;89;0.64;1.7;58;0.96;184;2;1;0;0.00
"cursor enterprise лицензия";210;142;118;0.71;1.4;44;1.00;210;0;5;0;0.00
"autocad";410;260;211;0.41;3.1;185;0.00;410;19;8;7;642000.00
```

---

## 4. Файл 2: Сырые визиты Logs API (`metrika_visits.jsonl`)

Имитирует выгрузку Яндекс Метрики Logs API (`source=visits`), одна строка = один визит (1-в-1 с `session_id`).

### Перечень полей

| Поле | Тип | Описание |
|---|---|---|
| `ym:s:visitID` | `string` | Уникальный ID визита (`session_id` в маппинге) |
| `ym:s:clientID` | `string` | Числовой ID посетителя Метрики |
| `ym:s:dateTime` | `string` | Время начала визита (`YYYY-MM-DD HH:MM:SS`, MSK) |
| `ym:s:startURL` | `string` | Точка входа (`https://demo-store.mock/`, `/category/...`, `/search?q=...`) |
| `ym:s:endURL` | `string` | Последняя страница визита |
| `ym:s:bounce` | `int` (`0|1`) | Признак отказа |
| `ym:s:pageViews` | `int` | Число просмотров страниц (хитов) |
| `ym:s:visitDuration` | `int` | Длительность визита в секундах |
| `ym:s:trafficSource` | `string` | `organic` (42%), `direct` (31%), `ad` (15%), `email` (7%), `referral` (5%) |
| `ym:s:regionCity` | `string` | Город из `clients.yaml:regions` |
| `ym:s:deviceCategory` | `string` | `desktop` (86% для B2B), `mobile` (12%), `tablet` (2%) |
| `ym:s:goalsID` | `int[]` | Массив достигнутых `goal_id` за визит |
| `ym:s:purchaseID` | `string[]` | Массив ID заказов (если была покупка) |
| `ym:s:purchaseRevenue` | `float[]` | Суммы заказов в ₽ |
| `ym:s:purchaseCurrency` | `string[]` | `["RUB"]` |
| `ym:s:parsedParamsKey1` | `string[]` | Ключи параметров визита (`["client_id", "segment", "industry"]`) |
| `ym:s:parsedParamsKey2` | `string[]` | Значения параметров (`["smb_trade", "smb", "trade"]` или `["guest", "guest", "unknown"]`) |

### Пример строки `metrika_visits.jsonl`

```json
{"ym:s:visitID":"9120261126000001421","ym:s:clientID":"1732104000000000102","ym:s:dateTime":"2026-11-18 11:24:09","ym:s:startURL":"https://demo-store.mock/","ym:s:endURL":"https://demo-store.mock/checkout/success","ym:s:bounce":0,"ym:s:pageViews":5,"ym:s:visitDuration":294,"ym:s:trafficSource":"direct","ym:s:regionCity":"Москва","ym:s:deviceCategory":"desktop","ym:s:goalsID":[301001,301004,301005,301007],"ym:s:purchaseID":["ORD-20261118-0412"],"ym:s:purchaseRevenue":[56700.0],"ym:s:purchaseCurrency":["RUB"],"ym:s:parsedParamsKey1":["client_id","segment","industry"],"ym:s:parsedParamsKey2":["smb_trade","smb","trade"]}
```

---

## 5. Файл 3: Сырые хиты с электронной коммерцией (`metrika_hits.jsonl`)

Имитирует выгрузку Logs API (`source=hits`) с параметрами поиска и стандартным объектом `ecommerce` Яндекс Метрики (`impressions`, `click`, `detail`, `add`, `purchase`).

### Перечень полей

| Поле | Тип | Описание |
|---|---|---|
| `ym:pv:watchID` | `string` | Уникальный ID хита |
| `ym:pv:visitID` | `string` | Связка с визитом (`ym:s:visitID`) |
| `ym:pv:clientID` | `string` | ID посетителя |
| `ym:pv:dateTime` | `string` | Время хита (`YYYY-MM-DD HH:MM:SS`, MSK) |
| `ym:pv:URL` | `string` | URL страницы (например, `https://demo-store.mock/search?q=...` или `/product/<card_id>`) |
| `ym:pv:referer` | `string` | Предыдущий URL в сессии |
| `ym:pv:title` | `string` | Заголовок страницы |
| `ym:pv:goalsID` | `int[]` | Цели, сработавшие на этом хите |
| `ym:pv:params` | `object` | Структурированные параметры хита: `search_id`, `site_search_query`, `search_category_ctx`, `search_results_count`, `search_zero`, `search_engine`, `ecommerce` |

### Структура `ym:pv:params.ecommerce` (стандарт Метрики)

- **Показ выдачи (`impressions`):** `{"currencyCode":"RUB","impressions":[{"id":"offer_id","name":"...","brand":"...","category":"...","price":1890.0,"list":"Search Results","position":1}]}` (первые 5 позиций выдачи для компактности лога).
- **Клик по карточке (`click`):** `{"currencyCode":"RUB","click":{"actionField":{"list":"Search Results"},"products":[{"id":"offer_id","name":"...","brand":"...","category":"...","price":1890.0,"position":1}]}}`
- **Добавление в корзину (`add`):** `{"currencyCode":"RUB","add":{"products":[{"id":"offer_id","name":"...","brand":"...","category":"...","price":1890.0,"quantity":30}]}}`
- **Оформление заказа (`purchase`):** `{"currencyCode":"RUB","purchase":{"actionField":{"id":"ORD-...","revenue":56700.0},"products":[{"id":"offer_id","name":"...","brand":"...","category":"...","price":1890.0,"quantity":30}]}}`

### Пример хита поиска и хита покупки (`metrika_hits.jsonl`)

```json
{"ym:pv:watchID":"8820261126000010501","ym:pv:visitID":"9120261126000001421","ym:pv:clientID":"1732104000000000102","ym:pv:dateTime":"2026-11-18 11:24:22","ym:pv:URL":"https://demo-store.mock/search?q=%D0%BA%D0%B0%D1%81%D0%BF%D0%B5%D1%80+%D0%BF%D1%80%D0%BE%D0%B4%D0%BB%D0%B5%D0%BD%D0%B8%D0%B5+30+%D0%BF%D0%BA","ym:pv:referer":"https://demo-store.mock/","ym:pv:title":"Поиск: каспер продление 30 пк","ym:pv:goalsID":[301001],"ym:pv:params":{"search_id":"s_hist_001421_1","site_search_query":"каспер продление 30 пк","search_category_ctx":null,"search_results_count":8,"search_zero":0,"search_engine":"legacy","ecommerce":{"currencyCode":"RUB","impressions":[{"id":"sku_kes_ren_25_49","name":"Kaspersky Endpoint Security Продление 25-49 1 год","brand":"Kaspersky","category":"endpoint_security","price":1890.0,"list":"Search Results","position":1}]}}}
{"ym:pv:watchID":"8820261126000010505","ym:pv:visitID":"9120261126000001421","ym:pv:clientID":"1732104000000000102","ym:pv:dateTime":"2026-11-18 11:29:03","ym:pv:URL":"https://demo-store.mock/checkout/success","ym:pv:referer":"https://demo-store.mock/cart","ym:pv:title":"Заказ оформлен","ym:pv:goalsID":[301007],"ym:pv:params":{"search_id":"s_hist_001421_1","ecommerce":{"currencyCode":"RUB","purchase":{"actionField":{"id":"ORD-20261118-0412","revenue":56700.0},"products":[{"id":"sku_kes_ren_25_49","name":"Kaspersky Endpoint Security Продление 25-49 1 год","brand":"Kaspersky","category":"endpoint_security","price":1890.0,"quantity":30}]}}}}
```

---

## 6. Правила адаптера импорта (`metrika → kuznitsa.sqlite`)

Чтобы 26 ноября без правок кода загрузить как наши `mock_metrika`, так и любые похожие выгрузки организаторов (`SPEC.md` §14.5, M4):

1. **Автоопределение формата:**
   - **CSV/TSV с колонкой фразы** (`Поисковая фраза` / `query` / `q` / `ym:s:searchPhrase`) → режим *агрегированного отчёта*: каждая строка разворачивается в `N = Поиски` синтетических записей `searches` (или взвешенный агрегат с полем `weight`), с `source='history'`, `engine='legacy'`, оценкой `zero` из колонки `Доля пустых выдач` (или из прогона `naive` по текущему каталогу, если колонки нет).
   - **JSONL / TSV Logs API (`ym:pv:*` + `ym:s:*`)** → режим *сырых сессий*:
     - Из хитов с `URL` вида `*[?&](q|query|search|text)=...` **или** `params.site_search_query` создаётся запись в `searches` (`session_id = visitID`, `client_id` из `parsedParams` или `clientID`).
     - Из `ecommerce.impressions` / `click` / `add` / `purchase` и `goalsID` (`request_quote`) создаются записи в `events`, привязанные к **последнему предшествующему поиску** в том же `visitID` (last-search-touch в окне визита).
     - Если в визите `bounce = 1` или после последнего поиска нет `click`/`cart`/`order`/`lead` — добавляется событие `exit`.
     - Если в одном визите идут два поиска подряд с интервалом ≤ 180 сек без `click` между ними и с разной нормализованной строкой (и второй не является уточнением цепочки §24.1) — первому поиску добавляется событие `reformulate`.
2. **Устойчивость к отсутствующим полям:** если в чужой выгрузке Метрики нет `parsedParams` (сегмента) — ставится `segment='unknown'`; если нет `margin_value` — маржа оценивается по `offer.margin` из загруженного каталога или по среднему категории (`querylog.yaml` §6).
3. **Идемпотентность:** повторный импорт того же файла дедуплицируется по `(source, visitID, watchID)` (или хэшу строки для CSV).
