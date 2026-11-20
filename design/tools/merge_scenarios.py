"""Собирает сводную карту сценариев поиска: docs/scenarios.yaml и docs/SCENARIOS.md.

Источники — design/proposals/neon/scenarios.yaml и design/proposals/neon2/scenarios.yaml.
Запуск из корня проекта: python design/tools/merge_scenarios.py
"""
from __future__ import annotations

import collections
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCES = [("neon", "design/proposals/neon/scenarios.yaml"), ("neon2", "design/proposals/neon2/scenarios.yaml")]

GROUPS = {
    "direct_product": "Прямой поиск: продукт, вендор, категория",
    "sku_codes": "Артикулы и коды",
    "licensing": "Лицензии: количество, срок, тип",
    "import_substitution": "Импортозамещение и аналоги",
    "compliance_regulatory": "Требования регуляторов и закупок",
    "compatibility_platform": "Совместимость и платформы",
    "tasks_use_cases": "Поиск по задаче",
    "roles_bundles": "Роли, рабочие места, комплекты",
    "commercial_filters": "Цена, поставка, исключения",
    "language_errors": "Язык: раскладка, опечатки, сленг",
    "advisory_qa": "Вопросы и сравнения",
    "edge_cases_oob": "Границы каталога",
    "context_personalization": "Контекст клиента",
    "session_refinement_chains": "Цепочки уточнений в сессии",
    "non_list_answers": "Ответ не списком: смета, ТЗ, расчёт, заявка",
    "buyer_persona_journeys": "Пути покупателей по ролям",
    "suggest_and_assistance": "Подсказки и восстановление выдачи",
    "business_analytics_signals": "Сигналы для бизнеса",
}

INTENT_TITLES = {
    "sku": "Артикул или код", "product": "Конкретный продукт", "vendor": "Производитель", "category": "Категория программ",
    "task": "Задача", "role_kit": "Комплект для роли или офиса", "industry": "Отраслевая подборка",
    "analog": "Замена и аналоги", "compliance": "Требования регулятора", "renewal": "Продление и докупка",
    "license_ops": "Правила и тип лицензии", "spec_list": "Список позиций", "compare": "Сравнение", "question": "Вопрос",
    "broad": "Слишком общий запрос", "out_of_catalog": "Нет в продаже", "off_topic": "Не по теме",
    "account": "Мои лицензии и заказы", "service": "Услуги", "promo": "Акции и пробные версии",
}

# Основное намерение сценария (закрытый список раздела 8 спецификации).
INTENT = {
    "exact_product_family": "product", "vendor_catalog_browse": "vendor", "product_with_edition": "product",
    "product_with_version": "product", "direct_category_search": "category", "module_or_plugin_search": "product",
    "exact_vendor_sku": "sku", "partial_or_obsolete_sku": "sku", "registry_number_lookup": "sku",
    "okpd2_ktru_code_search": "sku", "mixed_cyrillic_latin_sku": "sku",
    "renewal_by_quantity": "renewal", "new_license_by_quantity_and_term": "product", "perpetual_vs_subscription": "license_ops",
    "license_addon_expansion": "renewal", "license_upgrade_and_crossgrade": "license_ops",
    "server_and_infrastructure_metrics": "license_ops", "concurrent_vs_named_licensing": "license_ops",
    "cal_and_rds_client_access": "license_ops", "audience_specific_pricing": "category", "vat_and_tax_preference": "compliance",
    "explicit_analog_query": "analog", "departed_vendor_direct_query": "out_of_catalog", "restricted_vendor_query": "out_of_catalog",
    "stack_migration_complex": "analog", "format_preserving_analog": "analog", "domestic_alternative_by_category": "category",
    "open_source_with_commercial_support": "product",
    "registry_mincifry_filter": "compliance", "fstec_certified_search": "compliance", "fsb_crypto_search": "compliance",
    "personal_data_152fz": "compliance", "kii_187fz_compliance": "compliance", "procurement_44fz_223fz": "compliance",
    "state_secret_and_gis": "compliance",
    "compat_with_russian_os": "category", "platform_os_filter": "category", "hardware_architecture_compat": "category",
    "deployment_model_filter": "category", "ecosystem_integration_search": "task", "file_format_search": "task",
    "security_incident_or_threat_task": "task", "document_workflow_task": "task", "remote_work_and_comms_task": "task",
    "infra_admin_and_devops_task": "task", "business_automation_task": "task", "engineering_and_creative_task": "task",
    "role_workplace_bundle": "role_kit", "office_size_starter_pack": "role_kit", "industry_solution_bundle": "industry",
    "multi_item_spec_paste": "spec_list", "accessory_and_token_bundle": "product", "training_and_support_services": "service",
    "price_budget_filter": "category", "delivery_format_and_urgency": "category", "negation_and_exclusions": "category",
    "price_on_request_enterprise": "product", "promo_and_free_trial_intent": "promo",
    "keyboard_layout_error": "product", "phonetic_translit_and_mixed_script": "product", "typos_and_merged_tokens": "product",
    "professional_it_slang_and_abbr": "product", "obsolete_and_rebranded_names": "product",
    "ambiguous_homonyms_disambiguation": "broad",
    "licensing_faq_question": "question", "product_vs_product_comparison": "compare", "compatibility_check_question": "question",
    "legal_and_audit_readiness": "question",
    "too_broad_generic_query": "broad", "catalog_gap_known_software": "out_of_catalog", "hardware_vs_software_boundary": "off_topic",
    "piracy_crack_free_query": "off_topic", "completely_offtopic_or_gibberish": "off_topic",
    "same_query_different_segment": "category", "os_fleet_auto_filtering": "category", "proactive_expiring_renewal": "category",
    "addon_vs_new_by_ownership": "renewal", "ksos_to_kes_seat_threshold_upgrade": "category",
    "category_page_scoped_search": "category", "account_my_licenses_lookup": "account", "repeat_order_from_history": "account",
    "chain_qty_recalculation": "renewal", "chain_cheaper_or_budget_pivot": "category", "chain_os_or_compliance_pivot": "category",
    "chain_term_or_model_pivot": "product", "chain_reformulation_after_failure": "category",
    "chain_competitor_alternative_pivot": "analog", "chain_narrowing_from_broad_to_sku": "broad",
    "chain_upsell_companion_addition": "product",
    "spec_list_messy_email_paste": "spec_list", "tender_tz_fragment_paste": "spec_list", "license_audit_deficit_check": "license_ops",
    "budget_estimation_tco_query": "role_kit", "manager_presale_lead_routing": "service",
    "honest_no_impossible_requirement": "compliance", "clarify_before_commit_ambiguous_task": "broad",
    "migration_checklist_answer": "question", "post_purchase_activation_support_query": "question",
    "accountant_closing_docs_and_urgent_report": "renewal", "procurement_officer_quote_comparison": "compare",
    "ciso_audit_preparation_bundle": "compliance", "sysadmin_emergency_outage_or_expiry": "renewal",
    "ceo_smb_plain_language_exploration": "task", "engineer_cad_module_ecosystem": "product",
    "gov_buyer_ban_and_registry_proof": "compliance",
    "prefix_autocomplete_high_intent": "product", "suggest_layout_and_typo_live_fix": "product",
    "suggest_instant_entity_jump": "sku", "zero_result_smart_recovery": "category",
    "related_and_next_step_suggestions": "product", "did_you_mean_soft_correction": "product",
}

# Где показывать сценарий: search — витрина, chain — цепочка запросов, suggest — подсказки, admin — консоль.
SURFACE_BY_GROUP = {"session_refinement_chains": "chain", "business_analytics_signals": "admin"}
SURFACE = {"prefix_autocomplete_high_intent": "suggest", "suggest_layout_and_typo_live_fix": "suggest",
           "suggest_instant_entity_jump": "suggest"}

# Показ в галерее, если первый пример из файла не подходит.
DEMO = {
    "keyboard_layout_error": {"q": "rfcgthcrbq"},
    "same_query_different_segment": {"q": "антивирус на 30 пк", "compare": ["guest", "smb_trade", "gov_clinic", "edu_university"]},
    "os_fleet_auto_filtering": {"q": "удаленный доступ", "profile": "gov_clinic"},
    "proactive_expiring_renewal": {"q": "антивирус", "profile": "smb_trade"},
    "addon_vs_new_by_ownership": {"q": "1с лицензии на 10 человек", "profile": "smb_trade"},
    "ksos_to_kes_seat_threshold_upgrade": {"q": "антивирус на 30 пк", "profile": "smb_trade"},
    "category_page_scoped_search": {"q": "фстэк", "category": "security"},
    "account_my_licenses_lookup": {"q": "что у нас скоро истекает", "profile": "smb_trade"},
    "repeat_order_from_history": {"q": "повторить прошлый заказ антивируса", "profile": "smb_trade"},
    "chain_qty_recalculation": {"chain": ["каспер продление на 30 компов", "а на 50?"], "profile": "smb_trade"},
    "chain_cheaper_or_budget_pivot": {"chain": ["антивирус на 50 пк", "подешевле"]},
    "chain_os_or_compliance_pivot": {"chain": ["антивирус на 50 пк", "а под астру?", "с сертификатом фстэк"]},
    "chain_term_or_model_pivot": {"chain": ["р7 офис 50 лицензий на год", "а на 2 года?", "а бессрочная есть?"]},
    "chain_reformulation_after_failure": {"chain": ["файрвол", "межсетевой экран"]},
    "chain_competitor_alternative_pivot": {"chain": ["касперский на 50 пк", "что вместо этого"]},
    "chain_narrowing_from_broad_to_sku": {"chain": ["защита информации", "антивирус", "на 50 пк", "продление"]},
    "chain_upsell_companion_addition": {"chain": ["астра линукс 50 шт", "офис к ней"]},
    "accountant_closing_docs_and_urgent_report": {"profile": "accounting_firm"},
    "procurement_officer_quote_comparison": {"profile": "gov_clinic"},
    "ciso_audit_preparation_bundle": {"q": "защита информации по гост 57580 для банка", "profile": "fin_bank"},
    "sysadmin_emergency_outage_or_expiry": {"profile": "smb_trade"},
    "engineer_cad_module_ecosystem": {"profile": "design_bureau"},
    "gov_buyer_ban_and_registry_proof": {"profile": "gov_clinic"},
    "signal_hot_enterprise_lead": {"admin_tab": "manager"},
    "signal_rising_demand_trend": {"admin_tab": "product"},
    "signal_catalog_gap_monetization": {"admin_tab": "content"},
    "signal_vocabulary_gap_synonym_discovery": {"admin_tab": "agent"},
    "signal_card_content_gap_high_bounce": {"admin_tab": "content"},
    "signal_proactive_renewal_wave": {"admin_tab": "manager"},
    "signal_margin_safe_merchandising": {"admin_tab": "manager"},
}


def one_line(text: str, limit: int = 90) -> str:
    text = " ⏎ ".join(part.strip() for part in str(text).splitlines() if part.strip())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def main() -> int:
    merged, seen, problems = [], set(), []
    for source, rel in SOURCES:
        path = ROOT / rel
        if not path.exists():
            problems.append(f"нет файла {rel}")
            continue
        for row in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            sid = row.get("id")
            if not sid or sid in seen:
                problems.append(f"{rel}: пропущен или повторный id {sid!r}")
                continue
            seen.add(sid)
            group = row.get("group")
            if group not in GROUPS:
                problems.append(f"{sid}: неизвестная группа {group!r}")
            surface = SURFACE.get(sid) or SURFACE_BY_GROUP.get(group, "search")
            intent = INTENT.get(sid)
            if intent is None and surface != "admin":
                problems.append(f"{sid}: не задано намерение")
            examples = [str(e) for e in (row.get("examples") or [])]
            demo = dict(DEMO.get(sid, {}))
            if "q" not in demo and "chain" not in demo and surface != "admin" and examples:
                demo["q"] = examples[0]
            if surface != "admin" and "compare" not in demo:
                demo.setdefault("profile", "guest")
            merged.append({
                "id": sid, "group": group, "group_title": GROUPS.get(group, group), "title": row.get("title"),
                "user_goal": row.get("user_goal"), "intent": intent, "surface": surface, "examples": examples, "demo": demo,
                "detection": row.get("detection"), "behaviour": row.get("behaviour"), "data_needed": row.get("data_needed") or [],
                "priority": row.get("priority"), "wow": row.get("wow"), "source": source,
            })
    order = {g: i for i, g in enumerate(GROUPS)}
    merged.sort(key=lambda s: order.get(s["group"], 99))  # сортировка устойчивая: порядок внутри группы сохраняется
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "scenarios.yaml").write_text(
        "# Сводная карта сценариев поиска. Файл собран design/tools/merge_scenarios.py — руками не править.\n"
        + yaml.safe_dump(merged, allow_unicode=True, sort_keys=False, width=140), encoding="utf-8")

    by_group = collections.OrderedDict((g, []) for g in GROUPS)
    for s in merged:
        by_group.setdefault(s["group"], []).append(s)
    prio = collections.Counter(s["priority"] for s in merged)
    out = ["# Карта сценариев поиска «Кузница Softline»", "",
           f"Сценариев: {len(merged)}, групп: {sum(1 for v in by_group.values() if v)}. "
           f"Приоритеты: P0 — {prio.get('P0', 0)}, P1 — {prio.get('P1', 0)}, P2 — {prio.get('P2', 0)}.", "",
           "Сценарий — это вид запроса, по которому поиск ведёт себя по-своему: по-другому понимает запрос, отбирает товары и",
           "строит ответ. Полные описания (как распознаётся, что делает поиск, какие данные нужны) — в `docs/scenarios.yaml`.", "",
           "Колонка «Намерение» — основной план обработки из закрытого списка: "
           + "; ".join(f"`{k}` — {v.lower()}" for k, v in INTENT_TITLES.items()) + ".", ""]
    n = 0
    for gi, (group, rows) in enumerate(((g, r) for g, r in by_group.items() if r), 1):
        out += [f"## {gi}. {GROUPS.get(group, group)} ({len(rows)})", "", "| № | Сценарий | Примеры запросов | Намерение | Приоритет |",
                "|---|---|---|---|---|"]
        for s in rows:
            n += 1
            shown = s["demo"].get("chain") or s["examples"][:3]
            sep = " → " if s["demo"].get("chain") else " · "
            ex = sep.join("«" + one_line(e, 60).replace("|", "/") + "»" for e in shown)
            where = {"suggest": " (подсказки)", "admin": " (консоль)", "chain": " (цепочка)"}.get(s["surface"], "")
            out.append(f"| {n} | {one_line(s['title'], 120).replace('|', '/')} | {ex} | "
                       f"{('`' + s['intent'] + '`') if s['intent'] else '—'}{where} | {s['priority']} |")
        out.append("")
    (docs / "SCENARIOS.md").write_text("\n".join(out), encoding="utf-8")
    print(f"scenarios: {len(merged)}; groups: {sum(1 for v in by_group.values() if v)}; problems: {len(problems)}")
    for p in problems:
        print("  !", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
