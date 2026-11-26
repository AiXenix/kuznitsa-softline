# Заметки Neon‑4 · ход 9 (настоящий каталог store.softline.ru)

Подготовлены файлы в зоне Neon‑4 по спецификации `design/spec-v1.0.md` (30.1, 30.2, 30.4, 30.5) и дереву разделов `design/proposals/neon4/real-categories.tsv`:

| Файл | Назначение | Объём |
|---|---|---|
| `kb/upsell_r9.yaml` | Правила допродаж («Вам может пригодиться» / `crosssell`) в формате 30.5 | **176 правил** по 11 направлениям |
| `kb/slang_r9.yaml` | Жаргон, сокращения, транслит и опечатки под настоящий фид (без дублей с базовыми `slang*.yaml`) | **220 терминов** (163 ПО + 57 оборудование) |
| `design/proposals/neon4/hardware-sw-hints-r9.yaml` | Подписи «Искали ПО для …?» для классов оборудования (30.4, п. 1) | **18 классов** (7 обязательных + 11 доп.) |

---

## 1. Формат и охват `kb/upsell_r9.yaml` (для потока A)

Файл — чистый верхнеуровневый YAML-список правил строго по разделу 30.5:

```yaml
- id: office_antivirus
  when: {classes: [1145, 222323, 870], families: [], vendors: [], query_words: []}
  offer: {classes: [650], families: [], vendors: []}
  reason: "К офисному пакету обычно берут антивирус для защиты рабочих мест"
  weight: 0.90
  source: "kb"   # либо "vendor_site:<url>"
```

### Важные детали для `kuznitsa/rank/upsell.py`

1. **ID классов фида:** все `when.classes` и `offer.classes` — целочисленные `id` уровня 2 из `real-categories.tsv`. Ни в одном `offer.classes` нет пустых разделов (у всех указанных классов > 0 предложений в фиде).
2. **Совпадение правила (`when`):**
   - если заданы `vendors` / `families` / `query_words` — сужают срабатывание правила к конкретному продукту или вендору (например `astra_ald_pro` только на Astra Linux, а не на любую ОС из `222320`; `win_server_cal` только на Windows Server, а не на Windows 11);
   - если `families`, `vendors`, `query_words` пусты — правило применяется ко всему классу(ам) в `when.classes`.
3. **Приоритет и отбор (`offer`):**
   - сначала выбирать продаваемые карточки, совпадающие по `offer.classes` + `offer.families` / `offer.vendors` (если не пусты), с fallback на класс `offer.classes`;
   - сортировать кандидатов по `weight` (диапазон `0.68–0.95`), соблюдая ограничения 30.5 (не на 1-м месте, не два подряд, не больше половины основной выдачи).
4. **Охват 10 контрольных запросов 30.3:** для всех 10 (`astra linux`, `Microsoft Office для дома и бизнеса`, `kaspersky small office security`, `крипто про csp 5.0`, `anydesk`, `кибер бэкап`, `сканер-вс`, `мтс`, `max patrol`, `365`) добавлены целевые продуктовые правила с высоким весом (`0.84–0.94`).

### Распределение правил по направлениям

| # | Направление | Кол-во правил |
|---|---|---:|
| 1 | Офисные пакеты (MS Office, M365, МойОфис, Р7-Офис) | 14 |
| 2 | ОС (Astra Linux, РЕД ОС, Альт, Windows, Linux, macOS) | 22 |
| 3 | Серверное ПО и СУБД (Windows Server, CAL, MS SQL, Postgres Pro, Oracle) | 14 |
| 4 | Виртуализация и облака (Брест, zVirt, VMware, IaaS/SaaS) | 12 |
| 5 | 1С, бухгалтерия, склад, торговля, кадры, СЭД | 15 |
| 6 | САПР, BIM, ГИС, сметы, инженерное ПО | 16 |
| 7 | Графика, дизайн, мультимедиа, PDF, OCR | 12 |
| 8 | Антивирусы, ИБ, MaxPatrol, Сканер-ВС, КриптоПро, токены, NGFW, SSL | 20 |
| 9 | Резервное копирование, восстановление и утилиты | 8 |
| 10 | Удалённый доступ, ВКС, МТС Линк, почта (MDaemon), телефония, ДО, разработка | 15 |
| 11 | Оборудование → ПО и сопутствующие товары | 28 |
| | **Итого** | **176** |

---

## 2. Формат и состав `kb/slang_r9.yaml` (для потока A)

Файл автоматически подхватывается загрузчиком `kuznitsa/kb/loader.py` (`slang*.yaml`) и валидируется `kuznitsa/kb/validate.py`.

- **Без дублей:** все 220 терминов проверены на отсутствие пересечений с `kb/slang.yaml`, `kb/slang_r3.yaml` и `kb/slang_audience_r3.yaml`.
- **Аудит примеров из задания:**
  - уже были в `kb/slang.yaml` (не дублированы, но дополнены опечатками и вариантами в `slang_r9.yaml`): `антивирь`, `винда`, `крипто про`, `дрвеб`, `автокад`, `нанокад`, `эксель`, `ворд`;
  - добавлены в `kb/slang_r9.yaml`: `офис`, `вин сервер`, `астра`, `астра линукс`, `мдаемон`, `мдэмон`, `мтс`, `мтс линк`, `365`, `офис 365`, `макс патрол`, `макспатрол`, `max patrol`, `сканер вс`, `сканер-вс`, `крипта`, `касп`, `каспер`, `касперский`, `драйвер`, `доктор веб`, `1эс`, `один эс`, `компас`, `кибер бэкап` и др.
- **Продукты фида без собственной линейки в `kb/families/*.yaml`** (`MDaemon`, `Сканер-ВС`, `Radmin`, `Paragon`, `MACROSCOP`, `Directum RX`, `Pilot-ICE`, `SmetaWIZARD`, `ТИМ КРЕДО`, `Базис`, `V-Ray`, `The Bat!`, `Traffic Inspector`, `Kerio Control`, `BarTender`, `LiteManager`, `Ammyy Admin`, `Parallels`): сопоставлены с валидными категориями `kb/categories.yaml`, а каноническое название продукта указано в `note`.
- **Оборудование (`attr: hardware_class`):** 57 жаргонных/разговорных терминов для железа из фида (`рэк сервер`, `свитч`, `ибп`, `упс`, `бесперебойник`, `мфу`, `моноблок`, `минипк`, `тсд`, `нас`, `схд`, `вебка`, `докстанция`, `ссд`, `озу`, `видюха` и т. д.) записаны через `maps_to: {attr: hardware_class, value: <класс>}` — схема `loader.py` допускает произвольный `attr`/`value`, а движок A может напрямую использовать `attr == "hardware_class"` для определения `domain=hardware` (раздел 30.4, п. 1).

---

## 3. Формат `design/proposals/neon4/hardware-sw-hints-r9.yaml` (для потока A)

Отдельный файл (чтобы не смешивать схему с плоским списком правил 30.5 в `kb/upsell_r9.yaml`). При интеграции поток A может либо читать его напрямую, либо перенести в `kb/hardware_sw_hints.yaml`.

Структура каждой записи:

```yaml
- id: hw_hint_server
  hardware_class: server                      # совпадает с value в slang_r9.yaml (attr: hardware_class)
  hardware_feed_classes: [86563, 87417, 87268, 87317] # id классов оборудования уровня 2 в фиде
  trigger_words: ["сервер", "серверы", "рэк сервер", ...] # голые запросы → domain=hardware
  prompt: "Искали ПО для сервера?"            # подпись/чип переключения в интерфейсе (30.4, п. 1)
  software_classes: [369, 222320, 2050, 222321, 2500, 650, 1033] # какие классы ПО предлагать при клике
  software_query_hint: "серверное ПО, серверные ОС, виртуализация, бэкап и защита серверов"
  sw_examples: ["Windows Server", "Astra Linux Special Edition", "MS SQL Server", "Кибер Бэкап", "zVirt"]
```

Покрыты все 7 классов из задания (`server`, `laptop`, `switch`, `all_in_one`, `monitor`, `printer_mfp`, `ups`) и 11 дополнительных ходовых классов оборудования фида (`desktop`, `mini_pc`, `router`, `nas_storage`, `scanner`, `plotter`, `ip_phone`, `ip_camera`, `pos_tsd`, `graphics_tablet`, `webcam_conf`).

---

## 4. Связи для ручной проверки на сайтах вендоров

В `kb/upsell_r9.yaml` метка `source: vendor_site:<url>` проставлена только для канонических порталов совместимости и страниц продуктов, в адресах которых мы уверены (прежде всего `https://astralinux.ru/ready/`, `https://redos.red-soft.ru/product/compatibility/`, `https://www.basealt.ru/compatibility/`, `https://www.cryptopro.ru/products/csp`, `https://cyberprotect.ru/products/backup/`, `https://postgrespro.ru/products/postgrespro`, `https://www.kaspersky.ru/small-to-medium-business-security`).

Ниже перечислены продуктовые связки, которые стоит проверить человеку на сайтах вендоров для уточнения точных страниц совместимости / версий (после проверки `source` можно перевести из `kb` в точный `vendor_site:<url>` или уточнить URL):

| Правило (`id`) | Что проверить | Предполагаемая страница вендора |
|---|---|---|
| `astra_ald_pro`, `astra_rubackup`, `astra_brest_virt`, `astra_secret_net_lsp`, `astra_linux_av`, `astra_ru_office`, `astra_cryptopro`, `astra_cyber_backup` | Актуальную матрицу версий ALSE 1.7/1.8 с ALD Pro, RuBackup, Брест, Secret Net LSP/Studio, Kaspersky, Dr.Web, МойОфис, Р7-Офис, КриптоПро, Кибер Бэкап | `https://astralinux.ru/ready/` и `https://wiki.astralinux.ru/` (раздел «Совместимость продуктов Группы Астра») |
| `redos_antivirus`, `redos_ru_office`, `redos_cryptopro`, `redos_backup`, `redos_red_db` | Наличие действующих сертификатов совместимости для РЕД ОС 7.3 / 8 | `https://redos.red-soft.ru/product/compatibility/` |
| `alt_linux_av`, `alt_linux_ru_office`, `alt_linux_virt` | Совместимость для Альт Рабочая станция 10 / Альт СП / Альт Сервер | `https://www.basealt.ru/compatibility/` |
| `win_server_cal`, `win_server_rds_cal`, `ms_sql_cal` | Точные формулировки схемы лицензирования CAL / RDS CAL / SQL CAL для актуальных редакций в каталоге | `https://www.microsoft.com/licensing/terms/` |
| `onec_cryptopro`, `onec_tokens`, `onec_postgres` | Сертификаты совместимости 1С:Предприятие 8 с КриптоПро CSP 5.0, токенами Рутокен/JaCarta и Postgres Pro для 1С | `https://v8.1c.ru/tekhnologii/sovmestimye-resheniya/`, `https://www.cryptopro.ru/products/csp`, `https://postgrespro.ru/products/postgrespro` |
| `cryptopro_tokens`, `tokens_cryptopro`, `cryptopro_mobile` | Поддерживаемые модели JaCarta-2 и Рутокен ЭЦП 3.0 для КриптоПро CSP 5.0 | `https://www.cryptopro.ru/products/csp`, `https://www.rutoken.ru/products/`, `https://www.aladdin-rd.ru/catalog/jacarta/` |
| `cyber_backup_av`, `cyber_backup_nas_storage`, `ru_virt_backup` | Список поддерживаемых ОС, гипервизоров (zVirt, Брест, Альт) и хранилищ в Кибер Бэкап 16/17 | `https://cyberprotect.ru/products/backup/` |
| `kompas_pilot_ice` | Совместимость актуальной версии КОМПАС-3D V25 с Pilot-ICE и ЛОЦМАН:PLM | `https://ascon.ru/products/` и `https://pilotems.com/` |
| `nanocad_point_cloud` | Совместимость Платформы nanoCAD с модулем «nanoCAD Облака точек» | `https://www.nanocad.ru/products/` |
| `sed_cryptopro` | Поддержка КриптоПро CSP 5.0 и ключевых носителей в Directum RX | `https://www.directum.ru/products/rx` |
| `mdaemon_activesync` | Совместимость модуля MDaemon ActiveSync с версиями MDaemon Messaging Server в фиде | `https://mdaemon.com/pages/mdaemon-email-server` |
| `maxpatrol_av_edr`, `scanner_vs_infosec` | Рекомендованные сценарии интеграции MaxPatrol и Сканер-ВС со смежными СЗИ | `https://www.ptsecurity.com/ru-ru/products/` и `https://www.npo-echelon.ru/solutions/scanner-vs.php` |
| `hw_ip_cam_vms` | Список поддерживаемых IP-камер в MACROSCOP ML/LS/NVR | `https://macroscop.com/podderzhivaemye-ip-kamery.html` |
| `virt_usb_redirect`, `remote_access_usb_redirect` | Совместимость FabulaTech USB/Printer/Scanner for Remote Desktop с RDP и VDI | `https://www.fabulatech.com/` |
