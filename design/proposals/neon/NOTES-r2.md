# Отчёт по раунду 2: витринные названия и правки фактов (Neon)

## 1. Объём выполненного

- **`kb/overrides/families.yaml`** — **481 запись** (100% семейств, в точном порядке `design/work/families_index.tsv`). Для каждого семейства задан чистый `title` (до 45 знаков, без скобок, версий и пояснений) и словарь `editions` строго по существующим id редакций без повторения имени семейства (где редакций нет — ключ опущен). Исходные `kb/families/*.yaml` не изменялись.
- **`kb/vendors.yaml`** — добавлен недостающий вендор `idera_testrail` (закрывает висячую ссылку `testrail.vendor`).
- **`max_seats` и `upgrade_to`** — проставлены для **5** SMB/домашних линеек с достоверным лимитом: `kaspersky_ksos` (`25 → kaspersky_kesb`), `kaspersky_standard_home` (`5 → kaspersky_ksos`), `drweb_small_business` (`50 → drweb_enterprise_security_suite`), `drweb_security_space` (`5 → drweb_small_business`), `pro32_total_security` (`5 → pro32_endpoint_security`).

## 2. Исправления фактов (140 правок по `popularity` 4–5 + 2 висячие ссылки)

- **`price_rub` (134 правки):**
  - Приведены к словарю §25.5 нестандартные единицы измерения (`company_year → pack_year`, `seat_year → device_year`/`user_year`, `seat → device`/`user`, `channel_year → user_year`, `operator`/`developer → user`, а также `box`/`company`/`robot_year`/`camera`/`channel`/`cpu_year`/`pack → other`).
  - В **7** семействах заменён `unit: other` на `pack_year` (где годовой пакет однозначен): `veeam_backup`, `yandex_datalens`, `aida64_business`, `mts_link_webinars`, `mango_vats`, `unisender`, `mindbox_cdp`.
  - Исправлены **2** смешения разных единиц в одном диапазоне (§25.5): `promt_translation` (разведены настольные 14–45 тыс. ₽ `device` и серверные 450 тыс. ₽) и `ispring_suite` (`user_year → pack_year` для корректного охвата авторского пакета и LMS).
- **`registry: no` (5 правок):** снят ошибочный флаг реестра Минцифры с учебных курсов и сервисных услуг — `softline_academy_courses`, `astra_training_courses`, `basealt_training_courses`, `redos_training_courses`, `softline_managed_support`.
- **Висячие ссылки (2 правки):**
  - `testrail.vendor → idera_testrail` — добавлен вендор в `kb/vendors.yaml`.
  - `rudesktop.extra_categories → endpoint_uem` — заменено через `kb/overrides/families.yaml` на `[directory_services]`.
  - **Важно для команды A (`kuznitsa/kb/loader.py:54–56`):** сейчас `missing_references(kb)` вызывается *до* `apply_titles(kb, root / "overrides/families.yaml")`. Поэтому `idera_testrail` закроется сразу, а по `rudesktop` проверка `kb-check` продолжит показывать предупреждение, пока `apply_titles` не перенесут до `missing_references`.

## 3. В чём не уверен (не трогал намеренно)

- **Многоредакционные 1С** (`onec_accounting`, `onec_zup`, `onec_trade`, `onec_unf`, `onec_bgu`, `onec_zkgu`, `onec_retail`) — не задавал `max_seats: 1`, так как лимит 1 ПК относится только к редакции `base`, а у `prof`/`corp` лимита нет (схема хранит `max_seats` на уровне семейства).
- **Пакеты вендорской техподдержки с `registry: yes`** (`astra_support_pack`, `basealt_support_pack`, `redsoft_support_pack`, `kaspersky_msa_support`, `postgres_pro_support`) — оставлены как есть, т.к. часто продаются единым правом с реестровым ПО; стоит уточнить политику НДС/реестра.
- **Корпоративное ПО с `unit: other`** (`onec_accounting`, `onec_erp`, `onec_holding`, `onec_docflow`, `pix_rpa`, `primo_rpa`, `robin_rpa`, `uipath_rpa`, `vk_private_cloud`, `basis_cloud_platform`, `visionlabs_luna`, `ntechlab_findface`, `macroscop_vms`, `trassir_vms`, `axxon_next_vms`, `paratype_fonts`, `onec_itilium`) — лицензируются по коробке/роботу/камере/каналу/CPU; точного значения в словаре §25.5 нет.
- **Оценки цен ушедших зарубежных вендоров** (`ms_office`, `windows_server`, `autocad`, `solidworks`, `atlassian_jira`, `vmware_vsphere`) — оставлены ориентировочными (все с `catalog: no`).
- **`getcourse_platform`** — в исходном YAML стоит технически некорректный id вендора `red_os_community_alt_extra`, но в `kb/vendors.yaml` он существует (`name: "GetCourse"`), ссылка не битая; не переименовывал, чтобы не сломать связность.

## 4. Чек‑лист проверки человеком перед показом жюри

1. Прогнать `kb-check` и сверить синтаксис `kb/overrides/families.yaml`, `kb/vendors.yaml` и порядок вызова `apply_titles` в `kuznitsa/kb/loader.py`.
2. Выборочно проверить актуальные прайсы 2026 года на топ‑10 хитов показа: `kaspersky_kesb`, `kaspersky_ksos`, `drweb_enterprise_security_suite`, `astra_linux_se`, `red_os`, `alt_workstation`, `r7_office`, `myoffice_standard`, `onec_accounting`, `cryptopro_csp`.
3. Сверить статус сертификатов ФСТЭК/ФСБ и записей реестра у пограничных продуктов ИБ и ОС (`pt_ngfw`, `usergate_ngfw`, `ideco_ngfw`, `astra_linux_se` 1.8, `red_os` 8, `r7_office`, `myoffice_standard`).
4. Принять решение по `registry` для 5 пакетов вендорской техподдержки (см. раздел 3).
5. Визуально пролистать витринные склейки `title + edition` на 15–20 карточках разных категорий (особенно `1С`, `Astra Linux`, `Kaspersky`, `Dr.Web`, `Контур`, `Битрикс24`).
