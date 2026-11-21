# Заметки K4 (Neon‑4): частное и общее, ОКВЭД, виды поиска

## 1. Что сделано

- **[`kb/industries_r3.yaml`](file:///home/bb/kuznitsa-softline-kb/kb/industries_r3.yaml)** (30 записей): проставлено поле `parent` у **24** частных отраслей (6 корневых оставлены без `parent`); почищены `aliases` (короткие названия организаций 1–3 слова, без цифр, без слов «софт/программы/по», без переноса фраз `seen: false` из `probes-kits-r3.jsonl`, без дублей внутри уровня).
- **[`kb/roles_r3.yaml`](file:///home/bb/kuznitsa-softline-kb/kb/roles_r3.yaml)** (70 записей: 50 профессий + 20 `kit_*`): проставлено поле `parent` у **47** частных записей (42 профессии + 5 комплектов; 23 корневых без `parent`); почищены `aliases` по тем же правилам, сняты пересечения внутри уровня.
- **Аудит слотов (`must: true` и `catalog: yes`)**: проверены все обязательные слоты всех 30 отраслей (`kb/industries_r3.yaml`) и всех 70 ролей/комплектов (`kb/roles_r3.yaml`) по `kb/families/*.yaml`. Во всех обязательных слотах уже присутствует как минимум одно семейство с `catalog: yes` (причём первым в списке). **Править слоты не потребовалось (0 замен).**
- **[`kb/okved_r4.yaml`](file:///home/bb/kuznitsa-softline-kb/kb/okved_r4.yaml)** (**249 строк**): все **88** действующих 2-значных классов ОКВЭД 2 (ОК 029-2014, разделы A–U) + **161** уверенный подкласс/группа (3–5 знаков) под частные отрасли из `kb/industries.yaml` и `kb/industries_r3.yaml`. Все `code` в кавычках, все `industry` — существующие `id`. Сомнительные коды в файл не включены (см. раздел 4).
- **[`docs/SEARCH-KINDS.md`](file:///home/bb/kuznitsa-softline-kb/docs/SEARCH-KINDS.md)**: добавлен раздел по 6 видам/режимам поиска четвёртого хода (ОКВЭД, спецификация и КП файлом, голосовой ввод и числа словами, бюджет в запросе, виджет `/embed`, частная и общая отрасль) с примерами, пользой для покупателя, эффектом для бизнеса и явным статусом «работает сейчас / появится в этом ходе».

---

## 2. Пары «частная → общая» (`parent`)

### Отрасли — `kb/industries_r3.yaml` (24 пары, 6 корней)

| Частная запись | `parent` | Частная запись | `parent` |
|---|---|---|---|
| `dentistry_private_clinic` | `healthcare` | `chemical_industry` | `manufacturing` |
| `diagnostic_lab` | `healthcare` | `woodworking_furniture` | `manufacturing` |
| `pharmacy_chain` | `pharma_biotech` | `printing_publishing` | `media_advertising` |
| `general_school` | `education` | `video_production_studio` | `media_advertising` |
| `college_spo` | `education` | `game_dev_studio` | `it_telecom` |
| `higher_edu_university` | `education` | `custom_software_dev` | `it_telecom` |
| `kindergarten_preschool` | `education` | `it_integrator_service` | `it_telecom` |
| `training_center_dpo` | `education` | `datacenter_hosting` | `telecom_isp` |
| `design_institute_kb` | `architecture_design` | `microfinance_org` | `banking_finance` |
| `machinery_engineering` | `manufacturing` | `leasing_company` | `banking_finance` |
| `instrument_electronics_mfg` | `manufacturing` | `housing_utilities_uk` | `energy_utilities` |
| `food_beverage_mfg` | `manufacturing` | `municipality_local_gov` | `gov_public_sector` |

**Корни без `parent` (6):** `veterinary_clinic`, `recruiting_agency`, `private_security_org`, `auto_dealer_service`, `culture_institution`, `distributed_holding`.

### Роли и комплекты — `kb/roles_r3.yaml` (47 пар, 23 корня)

| `parent` (общая запись) | Частные записи (профессии — 42, комплекты `kit_*` — 5) |
|---|---|
| `teacher_lecturer` | `school_teacher`, `university_professor`, `elearning_methodologist` |
| `doctor_clinician` | `clinic_registrar`, `medical_director` |
| `infosec_engineer` | `soc_analyst`, `security_officer_pdn` |
| `sysadmin` | `network_engineer`, `onec_administrator`, `virtualization_admin`, `backup_admin`, `mail_admin`, `vks_telephony_admin`, `it_asset_manager`, `crm_administrator` |
| `project_manager` | `product_manager` |
| `business_analyst` | `system_analyst` |
| `translator_editor` | `technical_writer` |
| `graphic_designer` | `photographer`, `artist_3d` |
| `video_editor_motion` | `sound_engineer` |
| `software_developer` | `web_developer`, `mobile_developer`, `embedded_developer`, `rpa_developer` |
| `cad_mechanical_engineer` | `process_engineer`, `cnc_engineer`, `furniture_designer` |
| `electrical_cad_engineer` | `pcb_designer` |
| `secretary_office_manager` | `archivist_records_manager` |
| `economist_financier` | `cfo_finance_director` |
| `accountant` | `internal_auditor`, `kit_accounting_outsource` |
| `procurement_specialist` | `fz44_procurement_officer`, `tender_specialist` |
| `marketing_manager` | `smm_specialist`, `copywriter` |
| `devops_sre_engineer` | `k8s_platform_engineer` |
| `logistics_dispatcher` | `supply_chain_planner` |
| `sales_manager` | `marketplace_manager` |
| `data_analyst_bi` | `bi_architect` |
| `architect_bim` | `road_civil_engineer` |
| `lawyer` | `compliance_dpo_lawyer` |
| `office_worker` | `kit_new_employee` |
| `remote_employee` | `kit_remote_department` |
| `call_center_operator` | `kit_contact_center` |
| `cashier_retail` | `kit_retail_pos_store` |

**Корни без `parent` (23):**
- Профессии (8): `pharmacist`, `occupational_safety_specialist`, `ecologist_engineer`, `hotel_administrator`, `research_scientist`, `lab_technician`, `student_learner`, `video_surveillance_operator`.
- Комплекты (15): `kit_new_branch`, `kit_windows_to_ru_os`, `kit_replace_office_suite`, `kit_pdn_152fz`, `kit_kii_object`, `kit_small_office_server`, `kit_computer_class`, `kit_meeting_room`, `kit_dev_startup`, `kit_online_school`, `kit_design_studio`, `kit_design_bureau`, `kit_ecommerce_store`, `kit_medical_clinic`, `kit_license_audit_prep`.

---

## 3. Спорные решения

1. **Запрет чисел в `aliases`.** Правило выполнено строго (цифр в `aliases` нет). У 7 записей, где цифры — часть общепринятого имени (`artist_3d`, `onec_administrator`, `fz44_procurement_officer`, `security_officer_pdn`, `k8s_platform_engineer`, `kit_pdn_152fz`, `kit_kii_object`), буквенно-цифровые маркеры (`3D`, `1С`, `44-ФЗ`, `152-ФЗ`, `187-ФЗ`, `Kubernetes`) сохранены в `title`, а в `aliases` оставлены словесные формы (`один эс`, `кубернетес`, `госзакупки`, `испдн`, `объект кии`).
2. **Отрасли без очевидного родителя.** `veterinary_clinic` оставлена корнем (в ОКВЭД 2 это класс `75`, раздел M, а не `healthcare` / `agriculture`); `distributed_holding`, `auto_dealer_service`, `recruiting_agency`, `private_security_org`, `culture_institution` — также самостоятельные вертикали без общей записи в `kb/industries.yaml`.
3. **Узкие пары `parent` в ролях.** `clinic_registrar` → `doctor_clinician` (общая медицинская роль, чтобы перехватить `"регистратура"` из базовой записи по правилу 27.3); `technical_writer` → `translator_editor` (перехват `"технический писатель"` из базы); `datacenter_hosting` → `telecom_isp` (ЦОД ближе к инфраструктурному оператору связи, чем к общему `it_telecom`).
4. **Межуровневое совпадение «испытательная лаборатория».** Фраза присутствует в `diagnostic_lab` (`industries_r3.yaml`) и в `lab_technician` (`roles_r3.yaml`); по правилу 27.3 роль перевесит отрасль — имеет смысл либо убрать её из `lab_technician` на следующей правке, либо учитывать контекст слова «лаборант».

---

## 4. Список «проверить человеком» (ОКВЭД 2, в `kb/okved_r4.yaml` не включены)

- **`86.90.9` / `86.90.1`** — медицинские диагностические лаборатории (`diagnostic_lab`): отдельного 4-значного кода КДЛ в ОКВЭД 2 нет, лаборатории регистрируются по прочей медицине `86.90` / `86.90.9`. Решить, привязывать ли `86.90.9` к `diagnostic_lab` или оставить общий `86.90` → `healthcare`.
- **`64.92.7`** — микрофинансовые организации (`microfinance_org`): 5-значная подгруппа под `64.92` (сейчас `64.92` целиком ведёт на `microfinance_org`, захватывая ломбарды `64.92.6` и КПК).
- **`68.32.1` vs `68.32.2`** — управление жилым фондом (`housing_utilities_uk`) против нежилого (`real_estate`); сейчас `68.32` ведёт на `housing_utilities_uk`.
- **`84.11.31` / `84.11.32`** — детализация органов местного самоуправления под `84.11.3` (`municipality_local_gov`).
- **`63.11.1`** — создание и использование баз данных и информресурсов под `63.11` (`datacenter_hosting`).
- **`62.02.1` / `62.02.4`** — планирование и проектирование компьютерных систем под `62.02` (`it_integrator_service`).
- **`47.91.2`** — розничная торговля непосредственно по сети Интернет под `47.91` (`ecommerce_marketplaces`).
- **`71.12.1` / `71.12.12`** — проектирование промышленных объектов под `71.12` (`design_institute_kb`).
- **Классы `17` (бумага) и `02` (лесоводство)** — сейчас привязаны к `manufacturing` и `agriculture`; проверить, не лучше ли направить их на `woodworking_furniture`.

---

## 5. Просьбы к движку и базовой базе знаний (чужие файлы не правились)

1. **Индексация буквенно-цифровых терминов из `title` (или разрешение в `aliases`).** Для запросов «администратор 1с», «3d художник», «44-фз закупщик», «152-фз пдн», «187-фз кии», «инженер k8s» движку важно учитывать буквенно-цифровые названия из `title`, т. к. из `aliases` все числа убраны по требованию хода.
2. **Конфликты в базовых файлах (вне зоны записи K4):**
   - `kb/industries.yaml`: у `agriculture` в `aliases` есть `"пищевая промышленность"` (конфликт с `food_beverage_mfg`, у которого `parent: manufacturing`, а не `agriculture` — правило 27.3 здесь не сработает).
   - `kb/industries.yaml`: у `science_rnd` в `aliases` есть `"лаборатория"` (конфликт с `diagnostic_lab`, у которого `parent: healthcare`).
   - `kb/industries.yaml` (`transport_logistics`) и `kb/roles.yaml` (`logistics_dispatcher`): оба содержат `"экспедитор"`.
   - `kb/roles.yaml`: у `procurement_specialist` есть `"специалист 44 фз"` — при запросе с цифрой «44-ФЗ» сработает родитель вместо `fz44_procurement_officer`, пока в потомке запрещены цифры.
3. **Уточнение 27.4 для «оквэд»:** предусмотреть нормализацию вариантов записи кода с пробелами и без ведущего нуля (`оквэд 6.10` → `06.10`, `оквэд 86 23` → `86.23`).
