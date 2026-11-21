"""Подписи линеек и подтверждённая совместимость систем с классами ПО."""


def load_purposes(kb, root, read):
    def entries(group, key):
        paths = [root / (group + ".yaml"), *sorted(root.glob(group + "_*.yaml"))]
        seen = set()
        for path in paths:
            if not path.is_file():
                continue
            data = read(kb, path)
            rows = data.get(key) if isinstance(data, dict) else data
            if not isinstance(rows, list):
                kb.warnings.append(f"{path.name}: ожидается список {key}")
                continue
            for row in rows:
                ident = row.get("id") if isinstance(row, dict) else None
                if not isinstance(ident, str) or ident in seen:
                    kb.warnings.append(f"{path.name}: пропущен пустой или повторный идентификатор {ident}")
                    continue
                seen.add(ident)
                yield path, row

    def references(value, group, where):
        result = []
        for ref in value if isinstance(value, list) else []:
            ident = ref.get("id") if isinstance(ref, dict) else ref
            if isinstance(ident, str) and ident in kb.rows[group]:
                result.append(ref)
            else:
                kb.dangling.append(f"{where} → {ident}")
        return result

    for path, row in entries("for_whom", "families"):
        ident = row["id"]
        family = kb.rows["families"].get(ident)
        if family is None:
            kb.warnings.append(f"{path.name}: неизвестная линейка {ident}")
            continue
        if isinstance(row.get("for_whom"), str):
            family.setdefault("for_whom", row["for_whom"])
        family["target_audiences"] = [a for a in row.get("audiences") or [] if isinstance(a, str)]
        if row.get("catalog") is False:
            family["for_sale_b2b"] = False
            analogs = references(row.get("analogs"), "families", ident)
            family["analogs"] = list(dict.fromkeys([*analogs, *family.get("analogs", [])]))
        kb.sources["for_whom"]["base" if path.stem == "for_whom" else "extensions"] += 1

    for path, row in entries("system_compat", "systems"):
        label = row.get("label")
        groups = row.get("compatible")
        if not isinstance(label, str) or not label or not isinstance(groups, dict):
            kb.warnings.append(f"{path.name} [{row['id']}]: нужны подпись и группы совместимости")
            continue
        compatible = {}
        for kind, group in groups.items():
            if isinstance(group, dict):
                compatible[kind] = dict(
                    categories=references(group.get("categories"), "categories", row["id"]),
                    families=references(group.get("families"), "families", row["id"]),
                )
        kb.systems[label.removeprefix("Для ")] = {
            **row,
            "compatible": compatible,
            "system_vendors": references(row.get("system_vendors"), "vendors", row["id"]),
        }
        kb.sources["system_compat"]["base" if path.stem == "system_compat" else "extensions"] += 1
