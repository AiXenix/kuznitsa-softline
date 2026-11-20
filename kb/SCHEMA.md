# База знаний о мире ПО (`kb/`) — схема v1

База знаний описывает **мир программного обеспечения независимо от каталога магазина**: вендоры, семейства продуктов,
категории, роли, задачи, сленг, аналоги. Из неё строятся словари поиска, mock‑каталог, подсказки, отчёт «чего нет в каталоге»
и подбор аналогов. Каталог организаторов 26 ноября будет привязан к этой базе автоматически (по названиям и артикулам).

Общие правила:

- Формат — YAML, UTF‑8, список объектов верхнего уровня. Идентификаторы — `snake_case` латиницей, уникальны в пределах файла, стабильны.
- Строки с двоеточием, `#`, кавычками или начинающиеся с цифры/спецсимвола брать в двойные кавычки.
- `aliases` — все реальные написания, как печатают люди: русское, латиница, транслит, сокращения, жаргон, **частые опечатки**,
  слитное/раздельное написание. В нижнем регистре. Чем больше — тем лучше, но без выдуманных.
- Факты указывать только при уверенности. Для сомнительного — `confidence: low` или пустое поле.
- После записи файла проверить синтаксис: `/home/bb/kuznitsa-softline/.venv/bin/python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1], encoding='utf-8'))" <файл>`.

## Закрытые списки значений

| Поле | Значения |
|---|---|
| `platforms` | `windows`, `windows_server`, `linux`, `macos`, `android`, `ios`, `aurora`, `web` |
| `compat_ru_os` | `astra`, `alt`, `redos`, `rosa`, `msvsphere` |
| `license.models` | `subscription`, `perpetual` |
| `license.metrics` | `device`, `user`, `concurrent`, `server`, `core`, `cpu`, `vm`, `mailbox`, `company`, `site`, `storage`, `other` |
| `license.actions` | `new`, `renewal`, `upgrade`, `crossgrade`, `addon`, `support` |
| `license.audiences` | `business`, `gov`, `edu`, `home`, `nonprofit`, `med` |
| `delivery` | `esd` (электронная), `box` (коробка), `paper` (бумажная лицензия/сертификат), `media` (носитель, токен), `service` |
| `deployment` | `onprem`, `cloud`, `hybrid` |
| `registry` | `yes`, `no`, `partial` (Единый реестр российского ПО Минцифры) |
| `certs` | `fstec`, `fsb`, `mo` |
| `origin` | `russian`, `foreign` |
| `market_status` | `active`, `restricted` (поставки в РФ ограничены), `left` (официально недоступен) |
| `segment` | `smb`, `mid`, `enterprise`, `gov`, `edu`, `individual` |

## `kb/categories.yaml` — дерево категорий (только ПО и смежное: токены, техподдержка, обучение, облака)

```yaml
- id: endpoint_security
  parent: security                 # null у верхнего уровня
  title: Антивирусы и защита рабочих мест
  title_short: Антивирусы
  softline_path: /antivirusi-bezopasnost/antivirusi-organizatsii/   # если есть прямое соответствие в референсе
  synonyms: [антивирус, антивирусная защита, защита конечных точек, endpoint protection, epp, савз]
  slang: [антивирь, антивирусник]
  description: Что входит и что НЕ входит (1–2 фразы).
  typical_queries: [антивирус для организации, корпоративный антивирус на 50 пк]
```

Ориентир: 14–18 групп верхнего уровня, 100–140 листовых категорий.

## `kb/vendors.yaml`

```yaml
- id: kaspersky
  name: Kaspersky
  name_ru: Лаборатория Касперского
  country: RU
  origin: russian
  market_status: active
  aliases: [касперский, лаборатория касперского, каспер, kaspersky lab, касперски, kasperski, лк]
  categories: [endpoint_security, edr_xdr, mail_security]
  notes: ""
```

Ориентир: не меньше 200 вендоров, важных для закупок юрлиц в России (российские и зарубежные, включая ушедших).

## `kb/families/<группа>.yaml` — семейства продуктов (главный файл базы)

```yaml
- id: kaspersky_kesb
  vendor: kaspersky
  name: Kaspersky Endpoint Security для бизнеса
  aliases: [kes, кес, kesb, каспер эндпоинт, касперский для бизнеса, endpoint security]
  category: endpoint_security            # листовая категория
  extra_categories: []
  summary: Защита рабочих станций и серверов организации с централизованным управлением.
  editions:
    - {id: standard, name: Стандартный, aliases: [standard, стандарт, select]}
    - {id: advanced, name: Расширенный, aliases: [advanced, расширенный]}
  versions: []                           # только если версия важна при покупке: ["2021", "2024", "ltsc 2021", "8.3"]
  platforms: [windows, windows_server, linux, macos, android]
  compat_ru_os: [astra, alt, redos]
  deployment: [onprem]
  license:
    models: [subscription]
    metrics: [device]
    terms_months: [12, 24, 36]
    actions: [new, renewal, crossgrade, addon]
    bands: ["10-14", "15-19", "20-24", "25-49", "50-99", "100-149", "150-249", "250-499", "500-999"]
    packs: []                            # либо фиксированные пакеты: [1, 2, 3, 5, 10]
    audiences: [business, gov, edu]
  delivery: [esd]
  registry: yes
  certs: [fstec, fsb]
  use_cases: [защита рабочих станций, защита файловых серверов, шифрование дисков, контроль устройств и usb]
  roles: [sysadmin, security_officer]
  industries: []
  formats: []                            # ключевые форматы файлов: [dwg, pdf, psd]
  analogs: [drweb_enterprise_security_suite, eset_protect]
  replaces: [symantec_endpoint_protection, mcafee_endpoint_security]   # для российских: что замещает
  price_rub: {unit: device_year, low: 1500, typical: 2600, high: 4200}  # грубая оценка, только для генерации mock‑цен
  popularity: 5                          # 1..5 — спрос у юрлиц в России
  catalog: yes                           # yes — попадёт в mock‑каталог; no — «мир вне каталога» (для отчёта о пробелах)
  sku_name_examples:                     # 1–3 примера, как такие позиции называют в прайсах
    - "Kaspersky Endpoint Security для бизнеса – Стандартный Russian Edition. 50-99 Node 1 year Renewal License"
  confidence: high
```

Ориентир: не меньше 450 семейств; из них примерно 25–30% с `catalog: no` — известные продукты, которых в магазине нет
(ушедшие вендоры, SaaS без дистрибуции, нишевые) — они нужны, чтобы показывать спрос вне каталога и предлагать аналоги.
Файлы по группам: `security.yaml`, `os.yaml`, `office.yaml`, `virtualization.yaml`, `databases.yaml`, `backup.yaml`,
`network_comm.yaml`, `cad_engineering.yaml`, `graphics_media.yaml`, `dev_tools.yaml`, `business_erp_crm.yaml`,
`accounting_1c.yaml`, `docs_text.yaml`, `remote_access.yaml`, `education.yaml`, `cloud_saas.yaml`, `ai.yaml`, `misc.yaml`.

## `kb/slang.yaml` — слова, не привязанные к одному продукту

```yaml
- term: продлёнка
  type: slang            # slang | abbr | translit | typo | obsolete
  maps_to: {attr: license_action, value: renewal}   # либо {category: id} | {vendor: id} | {family: id} | {platform: x} | {attr: ..., value: ...}
  note: ""
```

Ориентир: не меньше 350 записей (лицензионный жаргон, сокращения ИТ и ИБ, названия классов ПО, регуляторные сокращения).

## `kb/analogs.yaml` — импортозамещение

```yaml
- product: Microsoft Office
  family: ms_office
  aliases: [мс офис, майкрософт офис, ворд эксель]
  russian_analogs:
    - {family: r7_office, note: "Высокая совместимость с форматами OOXML"}
    - {family: myoffice_standard, note: ""}
```

## `kb/compliance.yaml` — регуляторные понятия

```yaml
- id: registry_ru
  title: Реестр российского ПО
  aliases: [реестр минцифры, из реестра, реестр отечественного по, отечественное по, российское по, импортозамещение]
  effect: {filter: {registry: yes}}        # filter — жёстко, boost — мягко
  explain: Короткое пояснение для покупателя (1–2 фразы).
```

## `kb/roles.yaml` — роли и профессии → набор ПО

```yaml
- id: accountant
  title: Бухгалтер
  aliases: [бухгалтер, главбух, бухгалтерия, для бухгалтерии, бух]
  slots:
    - {category: accounting, must: true, note: "учёт и отчётность", families: [onec_accounting]}
    - {category: e_signature, must: true, note: "электронная подпись для отчётности"}
    - {category: office_suite, must: true}
    - {category: endpoint_security, must: false}
```

## `kb/industries.yaml` — отрасли → типовые потребности (та же структура: `id`, `title`, `aliases`, `slots`, `compliance`)

## `kb/use_cases.yaml` — задачи своими словами → категории и продукты

```yaml
- id: open_dwg
  title: Открыть и редактировать чертежи DWG
  phrases: [открыть dwg, чем открыть чертеж, просмотр dwg, редактор чертежей, программа для чертежей]
  categories: [cad_2d]
  families: [nanocad, zwcad, autocad]
  features: []
```

## `kb/faq.yaml` — карточки‑ответы на вопросы о лицензировании и покупке

```yaml
- id: what_is_cal
  questions: [что такое cal, что такое клиентская лицензия, нужны ли cal для windows server]
  answer: 2–4 предложения простым языком, без выдуманных цифр.
  related_categories: [server_os]
  related_families: [windows_server]
```
