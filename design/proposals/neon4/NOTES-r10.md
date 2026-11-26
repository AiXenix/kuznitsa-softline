# Заметки · ход 10 (slang_r10 + исправление upsell_r9)

| Файл | Что | Объём |
|---|---|---|
| `slang_r10.yaml` | Новый словарь: латинские бренды и продукты кириллицей, жаргон оборудования | **607 терминов**: 449 бренды и продукты + 158 оборудование |
| `upsell_r9.yaml` | Исправленная копия (порядок, комментарии и формат сохранены; новое — в конце) | 176 исходных правил: **114 изменено**, 62 без изменений, **0 удалено целиком**, **+57 новых** `r10_` → итого 233 |

Оба файла проходят `yaml.safe_load` (PyYAML 6.0.3). Скрипты проверки лежат в `work/kb-r10/scripts/`: `check_slang.py`, `check_upsell.py`, `patch_upsell.py`, `stats.py`.

---

## 1. `slang_r10.yaml`

### 1.1. Сколько добавлено

| Раздел | Терминов |
|---|---:|
| **1. Бренды и продукты кириллицей** | **449** |
| Microsoft | 44 |
| Adobe | 24 |
| Autodesk | 17 |
| Kaspersky (продукты) | 10 |
| Антивирусы и ИБ, зарубежные вендоры фида | 38 |
| Российские СЗИ (латинские названия) | 13 |
| Zoho / ManageEngine | 7 |
| ОС и виртуализация | 28 |
| Бэкап, диски, утилиты | 25 |
| Офис, документы, OCR, PDF | 48 |
| САПР, инженерное и научное ПО | 43 |
| Сеть, мониторинг, связь, удалённый доступ | 34 |
| Разработка и СУБД | 26 |
| Мультимедиа | 15 |
| Бренды оборудования из фида | 77 |
| **2. Жаргон оборудования (`attr: hardware_class`)** | **158** |

Цели `maps_to`: `vendor` — 42, `family` — 77, `text` — 330 (235 разных латинских написаний), `hardware_class` — 158 (128 на существующие значения, 30 на новые).
Типы: translit — 399, slang — 113, typo — 68, abbr — 24, obsolete — 3.

Охвачено около 170 вендоров из `real-vendors.tsv`: все, у которых есть реальные кириллические написания, плюс бренды из `top_lines` разделов (Nero, Pinnacle, ACDSee, Wolfram, COMSOL, Kerio, Novell и др.). Для нишевых вендоров, которых кириллицей не пишут (IPKozhemyakin, Pointdev, EUtech, Lahey, /n software, KWizCom и т. п.), я ничего не придумывал.

### 1.2. Дубли и конфликты
- Сверка шла с `slang.yaml`, `slang_r3.yaml`, `slang_r9.yaml`, а также с `name`, `name_ru` и `aliases` из `vendors.yaml` и `vendors_r3.yaml` (нижний регистр, ё→е, пробелы нормализованы). Пересечений **0**, внутренних дублей **0**. Дополнительно сверил с `synonyms/slang` из `categories.yaml`: «вижуал студия» уже есть в `ide_compilers`, поэтому убрал. Файла `slang_audience_r3.yaml` в `src` нет, с ним сверки не было.
- **Примеры из задания, которые уже есть в KB** (не дублировал):
  - алиасы вендоров: майкрософт, микрософт, адобе, автодеск, тимвьюер, циско, вмвар;
  - `slang_r3`: мелкософт;
  - `slang_r9`: энидеск, эни деск, оракл, адоб, вмваре;
  - `slang.yaml`: зум, эксель, фотошоп, акробат;
  - жаргон оборудования из `slang_r9`: системник, свитч, роутер, мфу, моник, бесперебойник, ибп, ssd, оперативка, видюха.
- **Конфликты: термины заняты другим значением**, поэтому не добавлял:
  - «комп» → `license_metric: device`;
  - «сервак» → `license_metric: server`;
  - «процессор» → `license_metric: cpu`;
  - «цсп» → `license_type: csp` в `slang_r3`; вместо него добавил «крипто про цсп» → `cryptopro_csp`;
  - «бп» — конфликт с «1с бп».

  Для «комп» и «сервак» нужно решение потока A: разрешить у термина несколько `maps_to` или решать по контексту.
- **Риск «зум»**: он уже есть в `slang.yaml` → `zoom_workplace`. В фиде есть фото- и видеотехника, а «зум» — это ещё и «увеличение». Рекомендую срабатывать только без аппаратного контекста.
- **Намеренно не добавлены** (обычные слова дают ложные срабатывания):
  - ажур (Azure), майя, канон, изотоп, серфер, кактус (Cactus), гигабайт (Gigabyte), нетак (Netac), оклик (Oklick), дельта (Delta), литера (Litera), норман (Norman), патриот (Patriot);
  - голые «панда», «корона», «алкоголь», «математика», «вотсап», «икарус», «аксесс», «воркстейшн» — добавлены только фразами с брендом;
  - голые «принтер», «сканер», «монитор», «компьютер», «ноутбук», «сервер», «экран», «стабилизатор». Риск: «сканер-вс», SQL Monitor, InfoWatch Traffic Monitor, «антивирус для ноутбука», «межсетевой экран», «сервер 1с». Эти слова и так покрыты `trigger_words` в `hardware_hints.yaml`.
- Термины с умеренным риском помечены в `note`: дефендер (Microsoft Defender или бренд периферии), смол офис, спешл, комодо, ретроспект, дельфи, хард, кулер, ксерокс.

### 1.3. Новая форма `{text: "..."}` (330 терминов → 235 написаний)
Её нужно поддержать в `kuznitsa/kb/loader.py` и `validate.py`: поиск заменяет термин в запросе на латинское написание и ищет как обычно. Используется для брендов и продуктов фида, у которых в KB нет `vendor` или `family` id.

Полный список (латинское написание ← термины):

Microsoft Teams ← майкрософт тимс, тимс; OneDrive ← ван драйв, уан драйв; OneNote ← ван ноут, ванноут; Skype ← скайп; Skype for Business ← скайп для бизнеса; Microsoft Azure ← азур, азюр; Microsoft Intune ← интюн; Microsoft Dynamics ← динамикс; Dynamics CRM ← динамикс срм; Microsoft Access ← майкрософт аксесс, мс аксесс; Defender ← дефендер; Photoshop Elements ← фотошоп элементс; InDesign ← ин дизайн; After Effects ← афтер эффект, афтерэффектс, афтэр эффектс; Lightroom ← лайт рум; Adobe Audition ← адоб аудишн, аудишн; Adobe Animate ← адоб анимейт; Dreamweaver ← дримвивер; RoboHelp ← робохелп; Adobe Stock ← адоб сток; Civil 3D ← сивил 3д, цивил 3д; Fusion 360 ← фьюжн 360, фьюжен 360; Navisworks ← навизворкс; AutoCAD Electrical ← автокад электрикал; AutoCAD Mechanical ← автокад механикал; AutoCAD MEP ← автокад мэп; AutoCAD Plant 3D ← автокад плант; Autodesk Maya ← автодеск майя; Robot Structural Analysis ← робот структурал; Kaspersky Safe Kids ← сейф кидс, касперский сейф кидс; Kaspersky Security Cloud ← касперский секьюрити клауд; Kaspersky Secure Mobility Management ← ксмм; F-Secure ← эф секьюр, эфсекьюр, ф-секьюр, ф секьюр; Tripwire ← трипвайр; SecurID ← секьюр айди, секьюрайди; Clearswift ← клирсвифт; IronPort ← айронпорт, айрон порт; eScan ← ескан, эскан; Norton ← нортон; Norton AntiVirus ← нортон антивирус; Norton 360 ← нортон 360; FortiClient ← фортиклиент; Comodo ← комодо; IKARUS ← икарус антивирус; Panda ← панда антивирус; EgoSecure ← эгосекьюр; Endian ← эндиан; Faronics ← фароникс; Deep Freeze ← дип фриз, дипфриз; VAS Experts ← вас экспертс; Kerio ← керио; Kerio Connect ← керио коннект; Kerio Operator ← керио оператор; DeviceLock ← девайс лок; КриптоПро PDF ← криптопро пдф, крипто про пдф; eToken ← етокен, е-токен, итокен; Zoho ← зохо; ServiceDesk Plus ← сервис деск плюс, сервисдеск плюс; OpManager ← оп менеджер, опменеджер; Endpoint Central ← эндпоинт сентрал; Desktop Central ← десктоп сентрал; Special Edition ← спешл эдишн, спешел эдишн, спешиал эдишн, спешл; Common Edition ← коммон эдишн; Termidesk ← термидеск; BILLmanager ← биллменеджер, билл менеджер; WorksPad ← воркспад; Ansible ← ансибл; vCenter ← вицентр, ви центр; VMware Workstation ← вмваре воркстейшн; VMware Fusion ← вмваре фьюжн; VMware Horizon ← хорайзон; StarWind ← старвинд, стар винд; Arcserve ← арксерв, арк серв; StorageCraft ← сторейджкрафт; ShadowProtect ← шадоу протект; Retrospect ← ретроспект; Paragon Hard Disk Manager ← парагон хард диск менеджер; Paragon NTFS ← парагон нтфс; CCleaner ← сиклинер, си клинер; Recuva ← рекува; Defraggler ← дефраглер; Diskeeper ← дискипер; MailStore ← мейлстор; Nero ← неро; Nero Burning ROM ← неро бернинг ром; Alcohol 120% ← алкоголь 120; WinZip ← винзип; Ashampoo ← ашампу; Auslogics ← ауслоджикс, аусложикс; BoostSpeed ← бустспид; Total Network Inventory ← тотал нетворк инвентори; Aspose ← аспоуз, аспос; Stimulsoft ← стимулсофт, стимул софт; ORPALIS ← орпалис; PaperScan ← пейперскан; Wondershare ← вондершер, вандершер; Filmora ← филмора; PDFelement ← пдфэлемент; EdrawMax ← эдрав макс, эдравмакс; UltraEdit ← ультраэдит, ультра эдит; Trados ← традос; StatSoft ← статсофт; Smartsheet ← смартшит; Nintex ← нинтекс; MapiLab ← мапилаб; Teklynx ← теклинкс; LABELVIEW ← лейблвью; NiceLabel ← найслейбл, найс лейбл; Loftware ← лофтвер, лофтвэр; BarTender ← бар тендер; IrfanView ← ирфанвью, ирфан вью; ACDSee ← асдиси; Corel Painter ← корел пейнтер; VideoStudio ← корел видеостудио; WordPerfect ← вордперфект; Spotlight ← спотлайт; RasterDesk ← растрдеск, растр деск; TechnologiCS ← технолоджикс; TurboCAD ← турбокад, турбо кад; APM WinMachine ← винмашина, апм винмашина; SolidCAM ← солидкам; Golden Software ← голден софтвер; Golden Software Surfer ← голден серфер; OriginPro ← ориджин про; OriginLab ← ориджинлаб; Wolfram Mathematica ← вольфрам математика; COMSOL ← комсол; Maple ← мейпл; Minitab ← минитаб; Zuken ← зукен; Artlantis ← артлантис; ConceptDraw ← концептдро, концепт дро; Rockwell Automation ← роквелл, рокуэлл; FactoryTalk ← фактори ток; MetaStock ← метасток; Corona Renderer ← корона рендер; Cinema 4D ← ц4д, синема фор ди; ZBrush ← зибраш, збраш; Redshift ← редшифт; Boris FX ← борис фх, борис эфикс; Toon Boom ← тун бум; Ipswitch ← ипсвитч; WhatsUp Gold ← вотсап голд, ватсап голд; AdRem ← адрем; NetCrunch ← неткранч; Nagios ← нагиос; Paessler ← пэсслер; PRTG ← пртг; NGINX ← нгинкс, энджинкс, энжинкс; NetSupport ← нетсаппорт, нет саппорт; FabulaTech ← фабулатек; IceWarp ← айсварп, айс варп; Axigen ← аксиген, аксижен; CraftTalk ← крафттолк, крафт толк; LiteManager ← лайт менеджер; Ammyy Admin ← ами админ; SberDevices ← сбердевайсес, сбер девайсес; SberBox ← сбербокс; Novell ← новелл; ZENworks ← зенворкс; Red Gate ← ред гейт, редгейт; Altova ← альтова; Telerik ← телерик; Navicat ← навикат; Infragistics ← инфраджистикс; DevExpress ← девэкспресс, дев экспресс; RAD Studio ← рад студио; IntelliJ IDEA ← интелиджей, интеллиджей; PyCharm ← пайчарм; ReSharper ← решарпер; WebStorm ← вебшторм; PhpStorm ← пхпшторм; Flexera ← флексера; InstallShield ← инсталлшилд; Idera ← идера; QlikView ← клик вью, кликвью; Kentico ← кентико; QuarkXPress ← кварк экспресс; ElcomSoft ← элкомсофт; Altaro ← альтаро; iZotope ← айзотоп; CyberLink ← сайберлинк, киберлинк; PowerDirector ← пауэр директор, пауэрдиректор; PhotoDirector ← фотодиректор; PowerDVD ← пауэр двд; Pinnacle Studio ← пиннакл, пинакл; Camtasia ← камтасия, кэмтазия; Snagit ← снагит, снаг ит; ASUS ← асус, азус, асюс, эйсус; HP ← хп, эйч пи, эйчпи, хьюлетт паккард, хьюлет паккард; LaserJet ← лазерджет, ласерджет; DeskJet ← дескджет; EliteBook ← элитбук; ProBook ← пробук; TP-Link ← тп линк, тплинк, тп-линк, ти пи линк; D-Link ← д-линк, длинк, ди линк; MikroTik ← микротик; Ubiquiti ← убиквити, юбиквити; UniFi ← юнифай; Tenda ← тенда; Canon ← кэнон, кенон, кэннон; i-SENSYS ← айсенсис; Kyocera ← киосера, киоцера, куосера, кьосера; Pantum ← пантум; Logitech ← логитек, логитех, лоджитек; A4Tech ← а4тек, а4 тек; Razer ← рейзер; SVEN ← свен; Dahua ← дахуа; Powercom ← пауэрком, пауерком; Ippon ← иппон; CyberPower ← киберпауэр, сайберпауэр; APC ← эйписи; Back-UPS ← бэк упс; Smart-UPS ← смарт упс; Digma ← дигма; Intel ← интел; AMD ← амд, эйэмди; MSI ← мси, эмэсай; Acer ← асер, эйсер; Kingston ← кингстон; Samsung ← самсунг, самсунк; ADATA ← адата; Seagate ← сигейт; Philips ← филипс; Panasonic ← панасоник; Yealink ← йеалинк, еалинк, ялинк; Yeastar ← йистар; Fanvil ← фанвил; Mertech ← мертех; Deepcool ← дипкул; Bosch ← бош; Electrolux ← электролюкс; Makita ← макита; Navitel ← навител.

«Спешл эдишн» и «спешл» сделаны через `{text: "Special Edition"}`, а не через `family: astra_linux_se`. Так «астра спешл» превращается в «астра Special Edition», и голое «спешл» не привязывается жёстко к Astra.

### 1.4. Значения `hardware_class`
- **Существующие** (из `slang_r9` и `hardware_hints`): laptop, desktop, mini_pc, all_in_one, server, switch, router, wifi_ap, ups, printer_mfp, printer_consumables, plotter, office_tech, graphics_tablet, components, storage_media, nas_storage, peripherals, laptop_accessories, ip_phone, ip_camera, pos_tsd.
- **Впервые в слангах**, но уже определены в `hardware_hints.yaml`: `webcam_conf` (веб-камеры, конференц-камеры) и `scanner` (потоковый, планшетный, протяжный сканер).
- **Новые значения**:

| value | Разделы фида | Примеры терминов |
|---|---|---|
| `network_adapter` | 86247 Сетевые карты, 85588 Адаптеры Wi-Fi | сетевуха, сетевая карта, вайфай адаптер |
| `power_protection` | 82661 Сетевые фильтры и стабилизаторы | сетевой фильтр, удлинитель, стабилизатор напряжения |
| `power_bank` | 91451 Внешние аккумуляторы | павербанк, пауэрбанк, повербанк |
| `cables` | 80081 Кабели, переходники, разъемы | хдми кабель, кабель hdmi, переходник |
| `intercom` | 137173 Домофоны | домофон |
| `av_equipment` | 91916 Проекторы, 92427 Телевизоры, 364748 Интерактивные панели | проектор, телевизор, телек |
| `office_furniture` | 137214 Кресла и стулья | кресло, офисное кресло, игровое кресло |
| `home_appliances` | 235010, 399337, 173830, 174449, 323058 | микроволновка, посудомойка, пылесос |
| `power_tools` | 269802, 269373, 269374 | шуруповерт, дрель, перфоратор |

- **Несогласованность в r9**: «вебка» → `peripherals`, а `hardware_hints` относит веб-камеры (89623) к `webcam_conf`. Новые термины про веб-камеры я направил в `webcam_conf`; «вебку» в r9 стоит перевести туда же.
- **Рекомендация для движка**: `hardware_class` переключает выдачу на `domain=hardware`, только если в запросе нет слов, указывающих на ПО. Пример: «антивирус на ноут» — это запрос про ПО.

---

## 2. `upsell_r9.yaml`

### 2.1. Новые необязательные поля

| Поле | Значения | Смысл |
|---|---|---|
| `when.audience` | `[home]` / `[business]` | Правило срабатывает, только если аудитория основного товара входит в список. Если аудитория не определена, правило срабатывает. |
| `offer.audience` | `[home]` / `[business]` | Кандидаты с определённой и несовпадающей аудиторией отбрасываются. Неопределённые проходят. |
| `offer.strict` | `true` | Брать только карточки, совпавшие с `offer.families` или `offer.vendors`; без фолбэка на весь класс. Нет совпадений — ничего не показывать. |
| `offer.exclude_words` | список подстрок | Не предлагать карточки, в названии которых есть подстрока (без учёта регистра). |

**Как определять аудиторию карточки:**
- по классу: 3775 «Антивирусы для дома» → home; 650 «Антивирусы для организаций», 121467 и 5984 → business;
- по словам в названии:
  - home: «для дома», «домашн», Home, Personal, Family, «для семьи», «персональн»;
  - business: «для бизнеса», Business, Enterprise, Corporate, Small Office, Node, диапазоны вида «250-499», Open Value, «для организаций».
- Остальное считается неопределённым. Например, Windows 11 Pro попадает и в бизнес-, и в домашнее правило, то есть ведёт себя как раньше.

**Допущение о `when`.** Код `kuznitsa/rank/upsell.py` я не видел. Правила написаны так, чтобы быть корректными при любой семантике: и когда `families` / `vendors` / `query_words` работают как «ИЛИ», и когда как «И». При «ИЛИ» поле `when.vendors: ["Microsoft"]` открывало правило для любого товара Microsoft в классе:
- `windows_desktop_*` срабатывали на Windows Server CAL;
- `win_server_cal` — на Windows 10;
- `m365_*` — на Office 2021.

Поэтому там, где продукт уже задан через `when.families`, я убрал `when.vendors`. При «И» это ничего не ломает.

### 2.2. Откуда брались проблемы из задания
| Симптом | Правило-источник | Что сделано |
|---|---|---|
| К МойОфис / Р7 предлагается защита Microsoft Office 365 | `office_antivirus`: `when` включал 222323, а предлагался весь класс 650, где лежит «Kaspersky Security для Microsoft Office 365» | 222323 убран из `when`, то есть для МойОфис/Р7 правило убрано. В остальные правила, где класс 650 предлагается целиком, добавлен `exclude_words` (Office 365, Microsoft 365, Exchange, SharePoint) |
| На «1с» показывается GlobalSign SSL | Фолбэк на весь класс 687 (GlobalSign там тоже есть) в `onec_cryptopro` и `ru_db_security` (на результаты «Postgres Pro для 1С»); `ssl_site_mail` (результат 1С-Битрикс в 6788 → SSL) | `strict`, `families`; у `ssl_site_mail` — только «сайтовые» и «почтовые» `query_words` |
| На «1с» показывается zVirt | Вероятнее всего, фолбэк на весь класс 222321 в `astra_brest_virt` и `alt_linux_virt`, если в выдаче «1с» оказываются продукты Астры или Альта. Это гипотеза: логов движка я не видел | `strict: true`. Проверить на запросе «1с» |
| На «астра» показывается ИнфраМенеджер ITSM | `astra_ald_pro`: предлагались классы [2942, 369] с `vendors: Группа Астра`, фолбэк на 2942 давал ИнфраМенеджер | Только `families: ALD Pro` + `strict` |
| На «офис» показывается ДатаПлат.Сервер | `office_pdf_editor` предлагал весь класс 180 («ПО для работы с документами»), а не PDF-редакторы | PDF-редакторы через `families` + класс 127 (там Master PDF Editor) + `strict`; для 222323 — отдельное `r10_ru_office_pdf_editor` |
| К домашнему антивирусу — KSMM на 250–499 устройств | `av_home_mobile` предлагал класс 121467 (KSMM, Secret MDM, КриптоПро ЗМ — всё корпоративное) | 121467 убран, `audience: home` |

### 2.3. Все изменения (id → что сделано → почему)

**Групповые изменения**
| Правила | Что сделано | Почему |
|---|---|---|
| alt_linux_virt, astra_brest_virt, astra_cryptopro, astra_cyber_backup, astra_rubackup, cad_pdm_docflow, construction_cad_estimates, graphics_pdf_dtp, hr_kedo_cryptopro, kompas_pilot_ice, mdaemon_activesync, mts_link_lms_courses, nanocad_point_cloud, onec_postgres, onec_tokens, oracle_db_tools, postgres_pro_backup, redos_backup, redos_cryptopro, redos_red_db, ru_office_cryptopro, ru_office_sed, ru_virt_backup, sed_cryptopro, tokens_cryptopro (25) | `offer.strict: true` | Причина называет конкретный продукт, а фолбэк на весь класс давал посторонние товары (687 → GlobalSign SSL, 8983 → сметы вместо PDM, 222321 → zVirt вместо «Брест») |
| ms_office_home_biz_antivirus, cryptopro_av, maxpatrol_av_edr, scanner_vs_infosec, ngfw_av, cyber_backup_av, anydesk_av, remote_access_av, onec_antivirus, cad_antivirus, it_asset_remote_av, hw_laptop_av, hw_desktop_av, office_backup, saas_business_av (15) | `offer.exclude_words`: Office 365, Microsoft 365, Exchange, SharePoint. Дополнительно: Dynamics — в scanner_vs_infosec и anydesk_av; Skype — в it_asset_remote_av; `offer.audience: business` — в saas_business_av | Классы 650, 629 и 1033 целиком могли дать защиту или бэкап Microsoft 365 там, где основной товар не из экосистемы Microsoft 365 |
| astra_linux_av, redos_antivirus, alt_linux_av, linux_unix_server_av | `exclude_words`: Windows, Microsoft, Office 365, Exchange, SharePoint, Mac, Android; у linux_unix_server_av ещё SSL-исключения | К Linux не предлагать продукты для Windows, Microsoft, Mac и Android |
| av_org_dlp_monitoring, iaas_security, disk_wipe_infosec, hw_server_av | `exclude_words`: SSL, GlobalSign, DigiCert, Entrust (у hw_server_av ещё Office 365, Microsoft 365, Android, Mobile) | Класс 687 содержит SSL-сертификаты: они не DLP, не облачная СЗИ и не защита сервера |
| win_server_backup, ms_sql_backup | Убран `when.vendors: Microsoft` | Продукт уже задан через `families`; вендор открывал правило для любого товара Microsoft |
| win_server_cal, win_server_rds_cal, win_server_sql, ms_sql_cal, ms_sql_monitor | Убран `when.vendors`; убран `offer.vendors`, добавлен `strict` | То же; плюс в предложении должны быть только названные CAL, RDS CAL и SQL, а не любой товар Microsoft из 369 или 2050 |
| win_server_antivirus | Убран `when.vendors`; `exclude_words`: Office 365, Microsoft 365, Linux, Android, Mac | Серверу Windows нужна защита для Windows Server |
| ms_office_windows_os, hw_laptop_os | `exclude_words`: Server, Сервер, CAL, MultiPoint | Класс 2050 содержит Windows Server CAL и MultiPoint, а не ОС для рабочего места |
| windows_desktop_office, hw_laptop_office, hw_desktop_os_office | `exclude_words`: Server, Сервер, CAL, Exchange, SharePoint, Project, Visio, «Частное Облако» (+MultiPoint в hw_desktop_os_office) | Причина — «офисный пакет»; серверные и облачные позиции классов 1145 и 222323 сюда не подходят |

**Изменения по отдельным правилам**
| id | Что сделано | Почему |
|---|---|---|
| office_antivirus | Из `when.classes` убран 222323 | Для МойОфис/Р7 правило предлагало защиту Microsoft Office 365 |
| office_pdf_editor | `when` только 1145; `offer`: классы [180, 127], PDF-редакторы через `families`, `strict` | В классе 180 есть ДатаПлат.Сервер и RoboHelp, это не PDF-редакторы; для 222323 — `r10_ru_office_pdf_editor` |
| ms_office_home_biz_antivirus | Убран `when.vendors`; `exclude_words` M365 | Срабатывало на любой товар Microsoft; бессрочному Office защита Microsoft 365 не нужна |
| ms_office_excel_utils | Из `query_words` убрано общее «office», добавлено «microsoft excel» | Общее слово |
| ms_office_visio_project | В `query_words` «офис» заменено на «мс офис» и «майкрософт офис»; убран `offer.vendors`, добавлен `strict` | По общему «офис» Visio и Project показывались бы рядом с МойОфис |
| m365_antivirus | Убран `when.vendors`; `when.audience: business`; `offer` [650, 629] с `audience: business` (3775 убран) | Домашние подписки обрабатывает `r10_m365_home_antivirus` |
| m365_backup | Убран `when.vendors`; `audience: business` в `when` и `offer` | Бэкап M365 нужен бизнес-подпискам |
| astra_ald_pro | Убран `offer.vendors`; `strict` | Фолбэк на 2942 давал ИнфраМенеджер |
| astra_secret_net_lsp | Из `families` убран Secret Net Studio (он для Windows); убран `vendors` (под Кодом Безопасности ещё vGate для VMware и Континент); `strict` | Экосистема Astra Linux |
| windows_desktop_office | `when.families`: Windows 10/11; `vendors` убран; «винда» и «виндоус» заменены версионными формами | Срабатывало на Windows Server и CAL |
| windows_desktop_av | То же, плюс `when.audience: business`, `offer` [650] business | Домашний случай — `r10_windows_home_av` |
| windows_desktop_backup | `when.families`: Windows 10/11; `vendors` убран | Срабатывало на CAL |
| macos_system_av | `offer` [650] (3775 убран), `audience: business`, `exclude_words` | Причина говорит о корпоративной сети, а класс 3775 — домашний |
| ru_db_security | `families`: Secret Net Studio / LSP, Dallas Lock; `strict` | Фолбэк на 687 давал GlobalSign SSL на «1с» (через Postgres Pro для 1С) |
| server_sw_monitoring | `families`: WhatsUp Gold, PRTG, NetCrunch, Advanced Host Monitor, SQL Monitor; `strict` | Фолбэк на 3205 давал Skype for Business и Radmin, на 7864 — ASTRA32 |
| ru_virt_security | `families`: Kaspersky Security для виртуальных и облачных сред, vGate, Secret Net LSP; `strict`; исключены VMware и Hyper-V | Вместо любого товара из 687/650 — защита виртуализации, без чужих платформ |
| ru_virt_remote_access | Убран 38945; `reason` обновлён | FabulaTech «for Remote Desktop» работает с RDP, Citrix и VMware — это чужая экосистема для российской виртуализации |
| virt_backup, virt_security, virt_monitoring | `when.families`: vSphere, vCenter, Red Hat Virtualization; у security и monitoring — `strict` | В классе 2500 есть настольные VMware Workstation и Fusion |
| virt_ha_extensions | `when` только Red Hat Virtualization; `offer`: Red Hat HA, Load Balancer, Resilient Storage, `strict` | Аддоны Red Hat — не для VMware; O&O CleverCache и ElcomSoft из 5202 — не HA |
| virt_usb_redirect | Убраны общее «виртуализация» и класс 222321; `query_words` vdi, rdp, horizon, citrix; FabulaTech через `families`, `strict` | Общее слово; FabulaTech — только RDP, Citrix и Horizon |
| onec_cryptopro | `strict`; `reason`: «из 1С и других учётных программ» | Фолбэк давал GlobalSign; в классе 12792 фида — Инфо-Бухгалтер, Турбо9, БЭСТ, а не 1С |
| onec_reporting | Убран 444578 (это юридические услуги, а не электронная отчётность); `families` ETAXREPORT + PDF-редакторы; `strict`; новый `reason` | Причина не совпадала с предложением |
| onec_ocr | OCR-продукты через `families`, `strict` | Фолбэк на 180 давал ДатаПлат |
| retail_marking_service | `families`: «Честный знак»; `strict` | В 444578 есть ещё 152-ФЗ, госзакупки и маркировка рекламы |
| cad_viewers | Добавлен класс 127; `families` ABViewer + PDF-редакторы; `strict` | IrfanView и XnView — не просмотрщики DWG; фолбэк на 180 давал ДатаПлат |
| cad_raster_vectorizers | AutoCAD Raster Design заменён на Spotlight, RasterDesk, ТИМ КРЕДО ТРАНСФОРМ, Панорама-редактор; `strict` | Raster Design — надстройка AutoCAD и не подходит пользователям nanoCAD и КОМПАС; для AutoCAD — `r10_autocad_raster_design` |
| gis_infra_credo | Убран 410746; `reason` обновлён | «nanoCAD Облака точек» — модуль из экосистемы nanoCAD, а не КРЕДО |
| pdf_cryptopro | `families`: КриптоПро PDF + CSP; `strict`; `reason` обновлён | Подпись в PDF ставит КриптоПро PDF |
| ocr_text_converters | `families`: Solid Converter, 3-Heights, Adobe Acrobat, ContentReader PDF; `strict` | Фолбэк на 180 |
| diagrams_office | `when`: [131716, 8962] + Edraw и ConceptDraw (20725 убран) | В 20725 лежат LABELVIEW, FusionCharts, Highstock — это не редакторы схем |
| av_org_backup | `offer.audience: business` | Класс 1033 содержит и домашний бэкап |
| av_org_ngfw | `families`: Traffic Inspector, Kerio Control, Endian, SmoothWall; `strict` | В 3656 лежат Kaspersky xSP, DDoS Protection, KSM и ZENworks — это не межсетевые экраны |
| av_home_office | `audience: home` в `when` и `offer` | Домашний класс |
| av_home_mobile | Убран 121467; `audience: home` | Пример из задания (KSMM на 250–499 устройств) |
| cryptopro_tokens, cryptopro_pdf_docs, cryptopro_mobile, cryptopro_av | Из `query_words` убрано голое «csp»; tokens и mobile — `strict`; pdf_docs — `families` КриптоПро PDF + PDF-редакторы, `strict`; av — `exclude_words` M365 | «csp» — это ещё и Microsoft Cloud Solution Provider (в KB `csp` → `license_type`) |
| maxpatrol_security_training | `families`: StopPhish, Kaspersky Express Course, Mobile Quest; `strict` | Курс по KES и iSpring LMS — не про осведомлённость сотрудников |
| ngfw_access_control | `families` 2FA: JaCarta, Рутокен, Avanpost, Indeed; `strict` | В 4742 есть c360 для MS Dynamics CRM и DeviceLock |
| infosec_152fz_legal | `families`: 152-ФЗ, StopPhish, курсы Kaspersky; добавлен 38838; `strict` | В 444578 есть ещё «Честный знак» и госзакупки |
| mobile_sec_mdm | `when.audience: business`; `offer`: SOTI MobiControl, `strict` | Класс 4008 включает домашние антивирусы, а в 5984 есть криминалистика Elcomsoft |
| ssl_site_mail | `query_words`: сайт, ssl, https, cms, битрикс, интернет-магазин, почтовый сервер, mdaemon, communigate и т. п. | На «1с» результат 1С-Битрикс давал GlobalSign SSL |
| remote_access_usb_redirect | FabulaTech for Remote Desktop заменён на USB over Network / USB Network Gate (классы 38945, 3205, 12989); `strict`; `reason` обновлён | Продукты «for Remote Desktop» не работают в сессиях AnyDesk, TeamViewer и RMS |
| remote_access_vks | ВКС-продукты через `families`, `strict` | В 7437 — SMS-компоненты, в 22298 — Intune и CloudMigrator365 |
| mts_link_hardware | Из `query_words` убрано «вебинар» | Причина называет МТС Линк, а слово срабатывало бы и на TrueConf |
| vks_comm_headset_cam | `when`: ВКС через `families` и `query_words` | SMS-компоненты и Intune — не повод предлагать гарнитуры |
| mail_server_antispam, mail_server_backup | `when.families`: почтовые серверы (+ класс 369 для Axigen); у antispam — `exclude_words` M365 и SSL | В 1267 и 7413 лежат The Bat!, ePochta и компоненты для разработчиков; MDaemon не нужна защита Exchange |
| ip_telephony_phones | `when.families`: PBX, АТС, Kerio Operator | В 7388 лежат VentaFax и SMS-шлюзы |
| lms_vks_webinars | Убран 7437; `reason` обновлён | В 7437 — SMS-компоненты |
| dev_tools_db_git | `when.families`: JetBrains, Visual Studio, Delphi, RAD Studio, C++Builder, IntelliJ | В 414 есть Dreamweaver, OpenStack и ActiveXperts |
| hw_server_os | `families` серверных ОС (+369); `strict`; исключены CAL, «Рабочая станция», Desktop | Фолбэк давал Windows 10 Home, CAL и Альт Рабочую станцию |
| hw_server_virt | `exclude_words`: Workstation, Fusion, Player | Настольные гипервизоры не для сервера |

### 2.4. Новые правила `r10_` (57)
- **4 замены** после разделения по экосистеме и аудитории: `r10_ru_office_pdf_editor`, `r10_m365_home_antivirus`, `r10_windows_home_av`, `r10_autocad_raster_design`.
- **29 правил «оборудование → аксессуары и ПО»**:
  - ноутбук → монитор, гарнитура, внешние носители;
  - ПК → гарнитура и веб-камера; монитор → док-станция; док-станция → монитор, клавиатура и мышь; клавиатура и мышь → гарнитура;
  - коммутатор → точки доступа; роутер → точки доступа и коммутатор;
  - принтер → USB-кабель;
  - корпус → БП и охлаждение; ОЗУ → SSD; SSD → ПО клонирования дисков; видеокарта → БП и охлаждение; HDD и внешний диск → ПО бэкапа;
  - сетевой фильтр → ИБП; NAS/СХД → ИБП;
  - IP-телефон → PoE-коммутатор; IP-камера → PoE-коммутатор, NAS и HDD для архива;
  - гарнитура ↔ веб-камера; конференц-оборудование → платформа ВКС;
  - сканер штрихкодов → принтер этикеток; принтер этикеток → ПО этикеток; POS-моноблок → денежный ящик и чековый принтер;
  - графический планшет → графические и фоторедакторы; плоттер → просмотрщик DWG или САПР.
- **24 правила «прикладное ПО → периферия и смежное ПО»**:
  - фото → графический редактор, монитор; видео → наушники; аудио → наушники и микрофон; 3D → ОЗУ; визуализация → видеокарта и монитор;
  - ГИС и карты → плоттер; сметы → табличный редактор; научные расчёты → ПК и ОЗУ; IDE → монитор;
  - Линтер и Ред База Данных → бэкап; ROSA и МСВСфера → антивирус и бэкап; Linux → бэкап; восстановление данных → внешний диск;
  - российская виртуализация → серверы; ПО видеонаблюдения → IP-камеры и NAS;
  - ПО этикеток → принтер этикеток и сканер; надстройки Excel → Microsoft Office;
  - ПО для документов и OCR → сканер; СЭД → сканер и OCR;
  - Radmin, Netop, NetSupport → антивирус; шлюз безопасности → 2FA; домашний антивирус → домашний бэкап.
- Новые правила срабатывают на **60 разделов фида**. Все `offer.classes` сверены по `real-categories.tsv`: раздел существует и в нём больше 0 предложений. Пары «оборудование ↔ оборудование» без фильтров дублей с r9 не повторяют. В `reason` — одна фраза для покупателя. Вес 0.70–0.88.

### 2.5. Проверить вручную
- **Названия `families` в `strict`-правилах нужно сверить с названиями в фиде.** Если название не найдено, правило ничего не покажет: это безопасно, но допродажа пропадёт. Меньше всего уверен в: Master PDF Editor, Corel PDF Fusion, ETAXREPORT, Secret Net LSP, Dallas Lock, Advanced Host Monitor, PRTG, NetCrunch, vGate, SOTI MobiControl, USB over Network, USB Network Gate, Paragon Drive Copy / Migrate OS, Spotlight, RasterDesk, StopPhish, Avanpost, Indeed, Kerio Connect, «МСВСфера Сервер», Microsoft 365 Family / Personal.
- **Совместимость vGate и Kaspersky Security для виртуальных и облачных сред** с «Брест», zVirt и СКАЛА-Р (`ru_virt_security`).
- **Счётчики в заголовках разделов 1–11** («14 правил» и т. п.) остались верными: целиком ни одно правило не удалено.
