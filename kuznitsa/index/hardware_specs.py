"""Разбор параметров оборудования из запроса и сопоставление с карточками фида (N9)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import re
import yaml

from kuznitsa.text import normalize

# Греческая заглавная/строчная гамма перед «Б» в названиях каталога («10 ΓБ» → «10 ГБ»).
_GREEK_GAMMA_GB = re.compile(r"[\u0393\u03b3](?=[бБ])")

# Торговое оборудование (принтер этикеток, чековый принтер, сканер штрихкодов) — отдельный раздел.
_TRADE_QUALIFIER_RE = re.compile(
    r"\b(?:этикет\w*|чек\w*|штрих-?код\w*|касс\w*|торгов\w*|термо\w*)\b", re.I
)

# Признаки запроса про ПО, а не про железо.
_SOFTWARE_GUARD_RE = re.compile(
    r"\b(?:программ\w*|софт\w*|антивирус\w*|бэкап\w*|backup|резервн\w*\s+копир\w*|"
    r"виртуализ\w*|шифрован\w*|крипто\w*|мониторинг\w*|защит\w*|антиспам\w*|"
    r"почтов\w*|windows|виндовс|linux|линукс|sql|exchange|1с|1c|"
    r"веб-?сервер\w*|прокси-?сервер\w*|терминальн\w*\s+сервер\w*|"
    r"уязвимост\w*|сканер-?вс|сканер\s+вс|очистк\w*|восстановлен\w*|дефрагментац\w*|"
    r"распознаван\w*|pdf|редактор\w*|лицензи\w*|подписк\w*|сертификат\w*|"
    r"техподдержк\w*|поддержк\w*|обучен\w*|курс\w*|внедрен\w*|"
    r"офисн\w*\s+пакет\w*|операционн\w*\s+систем\w*|утилит\w*|драйвер\w*|"
    r"удаленн\w*\s+доступ\w*|средств\w*\s+защит\w*|арм|печат\w*\s+этикеток)\b",
    re.I,
)
_PO_FOR_RE = re.compile(r"(?:^|\s)по\s+(?:для|на|под)\b", re.I)

# Количество штук для оборудования («ноутбук 5 шт»).
_HW_QTY_RE = re.compile(r"\b(\d{1,4})\s*(?:шт\.?|штук\w*|ед\.?)\b", re.I)

# Единицы измерения и параметры.
_RES_DIM_RE = re.compile(r"\b(\d{4})\s*[xх×]\s*(\d{3,4})\b", re.I)
_RES_4K_RE = re.compile(r"\b(?:4k|4к|uhd|ultra\s*hd)\b", re.I)
_RES_QHD_RE = re.compile(r"\b(?:2k|2к|qhd|wqhd)\b", re.I)
_RES_FHD_RE = re.compile(r"\b(?:full\s*hd|fullhd|fhd)\b", re.I)
_RES_HD_RE = re.compile(r"\bhd\b", re.I)

_WIFI_RE = re.compile(r"\b(?:wi-?fi|вай-?фай)\s*(6e|7|6|5)\b|\b802\.11\s*(ax|be|ac)\b", re.I)
_WIFI_MODEL_7_RE = re.compile(r"(?:^|[\s\-/])(?:BE\d{3,5}|BT\d{2})\b")
_WIFI_MODEL_6_RE = re.compile(r"(?:^|[\s\-/])AX\d{2,5}\b")
_WIFI_MODEL_5_RE = re.compile(r"(?:^|[\s\-/])AC\d{3,4}\b")

_RAM_TYPE_RE = re.compile(r"\b(?:lp)?(ddr[345])l?\b", re.I)
_RAM_KIT_RE = re.compile(r"\b(\d{1,2})\s*[xх×]\s*(\d{1,3})\s*(?:гб|gb)\b", re.I)

_CPU_INTEL_RE = re.compile(
    r"\b(?:intel\s+)?core\s+(?:ultra\s+)?i?([3579])(?=\s|$|-|\d)|\bi([3579])(?=\s|$|-)", re.I
)
_CPU_INTEL_CARD_RE = re.compile(
    r"\bcore\s+(?:ultra\s+)?i?([3579])(?=\s|-|\b)|\bi([3579])-\d", re.I
)
_CPU_RYZEN_RE = re.compile(r"\b(?:amd\s+)?ryzen(?:\s+([3579]))?\b", re.I)
_CPU_XEON_RE = re.compile(r"\bxeon(?:\s+(silver|gold|bronze|platinum|e|w))?\b", re.I)
_CPU_OTHER_RE = re.compile(r"\b(epyc|celeron|pentium)\b", re.I)
_CPU_APPLE_RE = re.compile(r"\b(m[1234](?:\s+(?:pro|max|ultra))?)\b", re.I)

_GPU_RTX_RE = re.compile(r"\b(rtx|gtx)\s*(\d{4}(?:\s*(?:ti|super))?)?\b", re.I)
_GPU_OTHER_RE = re.compile(r"\b(quadro|radeon\s+rx\s*\d{4}|radeon|geforce)\b", re.I)

_CAPACITY_RE = re.compile(
    r"(?:\b(?P<pre>озу|ram|оператив\w*|ssd|ссд|hdd|диск\w*)\s*[:=]?\s*)?"
    r"(?<!\d)(?P<val>\d+(?:[.,]\d+)?)\s*(?P<unit>тб|tb|гб|gb)\b"
    r"(?:\s*(?P<post>озу|ram|ddr[345]|lpddr[45]|ssd|ссд|hdd))?",
    re.I,
)

_POWER_W_RE = re.compile(r"(?<!\d)(\d{2,4}(?:[.,]\d+)?)\s*(?:вт|ватт|w)\b", re.I)
_POWER_VA_RE = re.compile(r"(?<!\d)(\d{3,5}(?:[.,]\d+)?)\s*(?:ва|va|вольт-?ампер\w*)\b", re.I)
_POWER_KVA_RE = re.compile(r"(?<!\d)(\d{1,2}(?:[.,]\d+)?)\s*(?:ква|kva)\b", re.I)

_PORTS_RE = re.compile(r"(?<!\d)(\d{1,2})\s*(?:-?\s*портов\w*|порт\w*|port\w*)\b", re.I)
_DESC_PORTS_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*[xх×]\s*(?:10/100(?:/1000)?|gigabit|fast|sfp|poe|port|rj-?45)", re.I
)
_SWITCH_MODEL_PORTS_RE = re.compile(
    r"\b(?:TL-S[GF]\d{2}|DES-\d{2}|DGS-\d{2}|S[GF]\d{2}|GS\d{2}|ES\d{2}|MES\d{2})(05|08|16|24|48)\b",
    re.I,
)

_DIAG_RAW_RE = re.compile(
    r"(?<!\d)(\d{1,2}(?:[.,]\d)?)\s*(?:\"|″|''|дюйм\w*|-?inch(?:es)?\b|in\b)", re.I
)
_DIAG_WORD_RE = re.compile(r"(?<!\d)(\d{1,2}(?:[.,]\d)?)\s*(?:дюйм\w*|inch(?:es)?)\b", re.I)

_PAPER_FMT_RE = re.compile(r"\b([aа][01234])\b", re.I)
_RACK_U_RE = re.compile(r"\b([1-6]u)\b", re.I)

_PRINT_TECH_RE = (
    ("laser", re.compile(r"\b(?:лазерн\w*|laser\w*)\b", re.I)),
    ("inkjet", re.compile(r"\b(?:струйн\w*|inkjet)\b", re.I)),
    ("led", re.compile(r"\bсветодиодн\w*\b", re.I)),
)
_PRINT_COLOR_RE = (
    ("color", re.compile(r"\b(?:цветн\w*|color|colour)\b", re.I)),
    ("mono", re.compile(r"\b(?:ч/б|чб|черно-?бел\w*|чёрно-?бел\w*|монохром\w*)\b", re.I)),
)

_INTERFACE_PATTERNS = (
    ("USB-C", re.compile(r"\b(?:usb\s*(?:3\.\d\s*)?type\s*-?\s*c|usb\s*-?\s*c|type\s*-?\s*c|тайп\s*-?\s*си)\b", re.I)),
    ("USB 3.0", re.compile(r"\busb\s*3(?:\.[012])?\b", re.I)),
    ("USB 2.0", re.compile(r"\busb\s*2(?:\.0)?\b", re.I)),
    ("HDMI", re.compile(r"\bhdmi\b", re.I)),
    ("DisplayPort", re.compile(r"\bdisplay\s*port\b", re.I)),
    ("NVMe", re.compile(r"\bnvme\b", re.I)),
    ("M.2", re.compile(r"\bm\.?2\b", re.I)),
    ("SATA", re.compile(r"\bsata\s*(?:iii|3|2)?\b", re.I)),
    ("SAS", re.compile(r"\bsas\b", re.I)),
    ("SO-DIMM", re.compile(r"\bso-?dimm\b", re.I)),
)

_POE_RE = re.compile(r"\b(?:poe|пое)\b", re.I)
_WIRELESS_RE = re.compile(r"\b(?:беспроводн\w*|wireless|bluetooth|блютуз|радиоканал\w*)\b", re.I)
_WIRED_RE = re.compile(r"\b(?:проводн\w*|wired)\b", re.I)
_WITH_MIC_RE = re.compile(r"\bс\s+микрофон\w*\b", re.I)
_UNIVERSAL_RE = re.compile(r"\b(?:универсальн\w*|universal)\b", re.I)

_COMPAT_CLAUSE_RE = re.compile(r"\b(?:для|к|под|на)\s+(.+)$", re.I)
_COMPAT_HOST_STOP = frozenset({
    "принтера", "принтеров", "принтер", "мфу", "ноутбука", "ноутбуков", "ноутбук",
    "планшета", "планшетов", "планшет", "смартфона", "смартфонов", "смартфон",
    "телефона", "телефонов", "телефон", "монитора", "мониторов", "монитор",
    "телевизора", "телевизоров", "ибп", "пк", "компьютера", "компьютеров",
    "печатных", "устройств", "устройства", "серии", "модели",
})

_CASE_TABLET_RE = re.compile(r"\b(?:ipad|айпад\w*|планшет\w*|matepad|galaxy\s+tab)\b", re.I)
_CASE_LAPTOP_RE = re.compile(r"\b(?:ноутбук\w*|macbook|макбук\w*|ультрабук\w*)\b", re.I)
_CASE_PHONE_RE = re.compile(
    r"\b(?:iphone|айфон\w*|смартфон\w*|телефон\w*|galaxy\s+[aszm]|xiaomi|redmi|huawei|honor|pixel|infinix|tecno)\b",
    re.I,
)

# Номинальные эквиваленты объёмов (1 ТБ = 1000 = 1024 ≈ 960 ГБ и т.д.).
_STORAGE_EQUIV_BANDS = (
    (120, 128),
    (240, 256),
    (480, 512),
    (960, 1024),
    (1920, 2048),
    (3840, 4096),
    (7680, 8192),
)


def _clean_text(text: str) -> str:
    if not text:
        return ""
    return _GREEK_GAMMA_GB.sub("г", text)


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def _classify_pixels(w: int, h: int) -> str | None:
    if w >= 7600:
        return "8K"
    if 3800 <= w <= 4200 and 2000 <= h <= 2400:
        return "4K"
    if 3400 <= w <= 3500 and 1400 <= h <= 1500:
        return "3440x1440"
    if 2500 <= w <= 2600 and 1400 <= h <= 1650:
        return "2560x1440"
    if 1900 <= w <= 1950 and 1180 <= h <= 1220:
        return "1920x1200"
    if 1900 <= w <= 1950 and 1050 <= h <= 1100:
        return "Full HD"
    if 1280 <= w <= 1400 and 720 <= h <= 820:
        return "HD"
    return None


def _storage_match_tier(target_gb: float, values: tuple[float, ...]) -> tuple[int, float]:
    """Вернуть (tier, distance): tier=2 точное/эквивалентное, tier=1 номинальное (±5%), tier=0 нет."""
    if not values:
        return (0, float("inf"))
    best_tier = 0
    best_dist = float("inf")
    for v in values:
        dist = abs(v - target_gb)
        if dist < best_dist:
            best_dist = dist
        if dist <= max(1.0, target_gb * 0.005):
            best_tier = max(best_tier, 2)
            continue
        # 1 ТБ = 1000 ГБ = 1024 ГБ; 2 ТБ = 2000 = 2048 и т.д.
        if target_gb >= 1000 and abs(v - target_gb * 1.024) <= 8 or (
            v >= 1000 and abs(target_gb - v * 1.024) <= 8
        ):
            best_tier = max(best_tier, 2)
            continue
        for lo, hi in _STORAGE_EQUIV_BANDS:
            if lo <= target_gb <= hi and lo <= v <= hi:
                # 500 vs 512, 960 vs 1000 — подтверждённое совпадение, но чуть ниже точного
                best_tier = max(best_tier, 1)
                break
    return (best_tier, best_dist)


def _format_gb(val: float) -> str:
    if val >= 1000 and (val % 1000 == 0 or val % 1024 == 0):
        tb = int(round(val / 1000.0)) if val % 1000 == 0 else int(round(val / 1024.0))
        return f"{tb} ТБ"
    if val == int(val):
        return f"{int(val)} ГБ"
    return f"{val:g} ГБ"


def _format_spec_value(key: str, val) -> str:
    if key == "storage_gb":
        return _format_gb(val)
    if key == "ram_gb":
        return f"{int(val) if val == int(val) else val:g} ГБ"
    if key == "diagonal":
        return f"{int(val) if val == int(val) else val:g}″"
    if key == "power_w":
        return f"{int(val) if val == int(val) else val:g} Вт"
    if key == "power_va":
        return f"{int(val) if val == int(val) else val:g} ВА"
    if key == "ports":
        return str(int(val))
    if key == "print_tech":
        return {"laser": "Лазерный", "inkjet": "Струйный", "led": "Светодиодный"}.get(val, str(val))
    if key == "print_color":
        return {"color": "Цветная", "mono": "Чёрно-белая"}.get(val, str(val))
    if key == "wireless":
        return "Беспроводное" if val else "Проводное"
    if key == "with_mic":
        return "С микрофоном"
    if key == "poe":
        return "PoE"
    if key == "cpu":
        if val.startswith("ryzen"):
            return val.title()
        if val.startswith("xeon"):
            return val.title()
        return val
    return str(val)


@dataclass(slots=True)
class OfferSpecs:
    storage_gb: tuple[float, ...] = ()
    ram_gb: tuple[float, ...] = ()
    ram_types: frozenset[str] = frozenset()
    diagonals: tuple[float, ...] = ()
    resolutions: frozenset[str] = frozenset()
    cpus: frozenset[str] = frozenset()
    gpus: frozenset[str] = frozenset()
    wifi: frozenset[str] = frozenset()
    interfaces: frozenset[str] = frozenset()
    print_tech: str | None = None
    print_color: str | None = None
    title_has_color: bool = False
    device_subtype: str | None = None
    paper_formats: frozenset[str] = frozenset()
    power_w: tuple[float, ...] = ()
    power_va: tuple[float, ...] = ()
    ports: tuple[int, ...] = ()
    wireless: bool | None = None
    with_mic: bool = False
    poe: bool = False
    rack_u: frozenset[str] = frozenset()
    compat_tokens: frozenset[str] = frozenset()
    compat_brand_tokens: frozenset[str] = frozenset()
    universal: bool = False
    title_tokens: frozenset[str] = frozenset()


@dataclass
class HardwareQuery:
    device_id: str
    section: str | None
    specs: dict[str, object] = field(default_factory=dict)
    display_specs: dict[str, str] = field(default_factory=dict)
    vendor_id: str | None = None
    vendor_ids: frozenset[str] = frozenset()
    vendor_label: str | None = None
    absent_vendor: bool = False
    series: str | None = None
    compat_raw: str | None = None
    compat_brand: str | None = None
    compat_terms: tuple[str, ...] = ()
    device_subtype: str | None = None
    is_consumable: bool = False
    hw_qty: dict | None = None
    suppress_cond_platform: bool = False
    no_sibling_fill: bool = True

    @property
    def has_constraints(self) -> bool:
        return bool(
            self.specs
            or self.vendor_id
            or self.absent_vendor
            or self.series
            or self.compat_terms
            or self.hw_qty
            or self.is_consumable
        )


def _fast_tokens(text: str) -> frozenset[str]:
    if not text:
        return frozenset()
    return frozenset(re.findall(r"[a-zа-я0-9]+", text.casefold().replace("ё", "е")))


def _extract_offer_specs(offer, card_title: str, section_name: str) -> OfferSpecs:
    attrs = offer.attrs or {}
    name = _clean_text(offer.name or "")
    title = _clean_text(card_title or "")
    desc = _clean_text(offer.description or "")
    sec_low = section_name.casefold()

    is_storage_sec = any(
        w in sec_low for w in ("ssd", "твердотельн", "жестк", "жёстк", "hdd", "флеш", "карт", "хранилищ", "накопит")
    )
    is_ram_sec = any(w in sec_low for w in ("оперативн", "озу", "память")) and not is_storage_sec
    is_gpu_sec = "видеокарт" in sec_low
    is_monitor_sec = "монитор" in sec_low
    is_laptop_sec = "ноутбук" in sec_low or "моноблок" in sec_low or "планшет" in sec_low
    is_computer_sec = is_laptop_sec or any(w in sec_low for w in ("компьютер", "сервер", "мини-пк", "неттоп", "системн"))
    is_ups_sec = "ибп" in sec_low or "бесперебойн" in sec_low
    is_psu_sec = "блоки питания" in sec_low or "источники питания" in sec_low
    is_switch_sec = "коммутатор" in sec_low
    is_router_sec = "роутер" in sec_low or "маршрутизатор" in sec_low or "точк" in sec_low
    is_printer_sec = "принтер" in sec_low or "мфу" in sec_low or "плоттер" in sec_low or "сканер" in sec_low
    is_periph_sec = any(w in sec_low for w in ("клавиатур", "мыш", "наушник", "микрофон", "гарнитур", "камер", "колонк"))
    is_consumable_sec = any(w in sec_low for w in ("расходн", "чехл", "сумк", "источники питания", "батаре", "кабел", "кронштейн", "док-станц", "подставк"))
    is_phone_sec = "смартфон" in sec_low

    title_name = title if title == name else f"{title} {name}"
    title_tokens = _fast_tokens(title_name)

    # Быстрый выход для разделов без интересующих техпараметров (мебель, электроинструмент и т.п.)
    if not (
        is_storage_sec or is_ram_sec or is_gpu_sec or is_monitor_sec or is_computer_sec
        or is_ups_sec or is_psu_sec or is_switch_sec or is_router_sec or is_printer_sec
        or is_periph_sec or is_consumable_sec or is_phone_sec or "проектор" in sec_low
    ):
        return OfferSpecs(title_tokens=title_tokens)

    full_text = f"{title_name} {desc}" if desc else title_name

    # 1. Storage & RAM capacities
    storages: list[float] = []
    rams: list[float] = []
    if is_storage_sec or is_ram_sec or is_gpu_sec or is_computer_sec or is_phone_sec:
        def add_cap_attr(key: str, target: list[float]):
            val = attrs.get(key)
            if val is None:
                return
            st = _clean_text(str(val)).strip()
            if not st:
                return
            m = _CAPACITY_RE.search(st)
            if m:
                num = _to_float(m.group("val"))
                if m.group("unit").casefold() in ("тб", "tb"):
                    num *= 1000.0
                target.append(num)
            elif st.replace(".", "", 1).replace(",", "", 1).isdigit():
                target.append(_to_float(st))

        if is_storage_sec or is_computer_sec:
            add_cap_attr("Ёмкость диска", storages)
            add_cap_attr("Объем установленного SSD", storages)
            add_cap_attr("Объем установленного HDD", storages)
        if is_storage_sec:
            add_cap_attr("Ёмкость", storages)
        if is_computer_sec:
            add_cap_attr("Объем установленной ОЗУ", rams)
            add_cap_attr("Объем оперативной памяти", rams)
        if is_gpu_sec:
            add_cap_attr("Объем памяти", rams)
        if is_ram_sec:
            mod_gb = attrs.get("Ёмкость одного модуля")
            if mod_gb is not None:
                m_mod = re.search(r"(\d+(?:[.,]\d+)?)", str(mod_gb))
                if m_mod:
                    single = _to_float(m_mod.group(1))
                    cnt_raw = attrs.get("Количество в комплекте")
                    cnt = 1
                    if cnt_raw is not None:
                        m_cnt = re.search(r"(\d+)", str(cnt_raw))
                        if m_cnt:
                            cnt = max(1, int(m_cnt.group(1)))
                    rams.append(single * cnt)
                    if cnt > 1:
                        rams.append(single)
            for m in _RAM_KIT_RE.finditer(full_text):
                rams.append(float(int(m.group(1)) * int(m.group(2))))

        for m in _CAPACITY_RE.finditer(full_text):
            val = _to_float(m.group("val"))
            unit = m.group("unit").casefold()
            if unit in ("тб", "tb"):
                val *= 1000.0
            pre = (m.group("pre") or "").casefold()
            post = (m.group("post") or "").casefold()
            if pre in ("озу", "ram") or pre.startswith("оператив") or post in ("озу", "ram") or post.startswith(("ddr", "lpddr")):
                rams.append(val)
            elif pre in ("ssd", "ссд", "hdd") or pre.startswith("диск") or post in ("ssd", "ссд", "hdd"):
                storages.append(val)
            elif is_storage_sec:
                storages.append(val)
            elif is_ram_sec or is_gpu_sec:
                rams.append(val)
            elif is_computer_sec or is_phone_sec:
                if unit in ("тб", "tb") or val >= 128:
                    storages.append(val)
                else:
                    rams.append(val)

    # 2. RAM type
    ram_types = set()
    if is_ram_sec or is_computer_sec:
        rt_src = f"{attrs.get('Тип памяти', '')} {full_text}"
        for m in _RAM_TYPE_RE.finditer(rt_src):
            ram_types.add(m.group(1).upper())

    # 3. Diagonal (prefer exact description/title over rounded attrs["Диагональ экрана"])
    diags: list[float] = []
    if is_monitor_sec or is_laptop_sec or is_consumable_sec or "проектор" in sec_low or "графическ" in sec_low:
        for src in (desc, title_name):
            if not src:
                continue
            for m in _DIAG_RAW_RE.finditer(src):
                d = _to_float(m.group(1))
                if 5.0 <= d <= 98.0:
                    diags.append(d)
        for key in ("Диагональ", "Диагональ экрана"):
            raw_d = attrs.get(key)
            if raw_d is not None:
                m_d = re.search(r"(\d{1,2}(?:[.,]\d)?)", str(raw_d))
                if m_d:
                    d = _to_float(m_d.group(1))
                    if 5.0 <= d <= 98.0:
                        if not any(abs(d - existing) < 0.6 and existing != d for existing in diags):
                            diags.append(d)

    # 4. Resolution (prefer exact pixel dimensions from description/name over buggy FullHD attr)
    resolutions = set()
    if is_monitor_sec or is_laptop_sec or "проектор" in sec_low or "камер" in sec_low:
        for m in _RES_DIM_RE.finditer(full_text):
            tag = _classify_pixels(int(m.group(1)), int(m.group(2)))
            if tag:
                resolutions.add(tag)
        if not resolutions:
            res_src = f"{title_name} {attrs.get('Разрешение экрана', '')}"
            if _RES_4K_RE.search(res_src):
                resolutions.add("4K")
            if _RES_QHD_RE.search(res_src):
                resolutions.add("2560x1440")
            if _RES_FHD_RE.search(res_src):
                resolutions.add("Full HD")
            elif _RES_HD_RE.search(res_src):
                resolutions.add("HD")

    # 5. CPU
    cpus = set()
    if is_computer_sec:
        cpu_src = f"{attrs.get('Серия процессора', '')} {attrs.get('Процессор', '')} {full_text}"
        for m in _CPU_INTEL_CARD_RE.finditer(cpu_src):
            digit = m.group(1) or m.group(2)
            if digit:
                cpus.add(f"i{digit}")
        for m in _CPU_RYZEN_RE.finditer(cpu_src):
            cpus.add("ryzen")
            if m.group(1):
                cpus.add(f"ryzen {m.group(1)}")
        for m in _CPU_XEON_RE.finditer(cpu_src):
            cpus.add("xeon")
            if m.group(1):
                cpus.add(f"xeon {m.group(1).casefold()}")
        for m in _CPU_OTHER_RE.finditer(cpu_src):
            cpus.add(m.group(1).casefold())
        for m in _CPU_APPLE_RE.finditer(title_name):
            cpus.add(m.group(1).casefold().split()[0])

    # 6. GPU
    gpus = set()
    if is_gpu_sec or is_computer_sec:
        gpu_src = f"{attrs.get('Графический процессор', '')} {attrs.get('Видеопроцессор', '')} {full_text}"
        for m in _GPU_RTX_RE.finditer(gpu_src):
            fam = m.group(1).upper()
            gpus.add(fam)
            if m.group(2):
                gpus.add(f"{fam} {re.sub(r'\s+', ' ', m.group(2).strip()).upper()}")
        for m in _GPU_OTHER_RE.finditer(gpu_src):
            tok = m.group(1).strip().upper()
            gpus.add(tok.split()[0])
            if " " in tok:
                gpus.add(re.sub(r"\s+", " ", tok))

    # 7. Wi-Fi
    wifi = set()
    if is_router_sec or is_laptop_sec:
        wifi_src = f"{attrs.get('Протоколы Wi-Fi', '')} {attrs.get('Диапазоны частот', '')} {full_text}"
        for m in _WIFI_RE.finditer(wifi_src):
            g1 = (m.group(1) or "").upper()
            g2 = (m.group(2) or "").casefold()
            if g1 == "7" or g2 == "be":
                wifi.add("Wi-Fi 7")
            elif g1 == "6E":
                wifi.add("Wi-Fi 6E")
                wifi.add("Wi-Fi 6")
            elif g1 == "6" or g2 == "ax":
                wifi.add("Wi-Fi 6")
            elif g1 == "5" or g2 == "ac":
                wifi.add("Wi-Fi 5")
        if is_router_sec:
            if _WIFI_MODEL_7_RE.search(title_name):
                wifi.add("Wi-Fi 7")
            if _WIFI_MODEL_6_RE.search(title_name) or "6.0 ггц" in wifi_src.casefold():
                wifi.add("Wi-Fi 6")
            if _WIFI_MODEL_5_RE.search(title_name):
                wifi.add("Wi-Fi 5")

    # 8. Interfaces
    interfaces = set()
    if is_storage_sec or is_monitor_sec or is_ram_sec or is_consumable_sec or is_laptop_sec or is_periph_sec:
        iface_src = f"{attrs.get('Интерфейс', '')} {attrs.get('Интерфейсы', '')} {attrs.get('Форм-фактор', '')} {full_text}"
        for label, rx in _INTERFACE_PATTERNS:
            if rx.search(iface_src):
                interfaces.add(label)
        if is_storage_sec and "pci express" in iface_src.casefold():
            interfaces.add("NVMe")

    # 9. Print tech, color, subtype, paper format
    print_tech = None
    print_color = None
    title_has_color = False
    device_subtype = None
    for k in ("Тип устройства", "Тип", "kind"):
        v = attrs.get(k)
        if isinstance(v, str) and v.strip():
            device_subtype = v.strip()
            break
    paper_formats = set()
    if is_printer_sec or is_consumable_sec:
        title_has_color = bool(re.search(r"\b(?:color|colour|цветн\w*)\b", title_name, re.I))
        pt_src = f"{attrs.get('Тип принтера', '')} {desc} {title_name}"
        for tag, rx in _PRINT_TECH_RE:
            if rx.search(pt_src):
                print_tech = tag
                break
        pc_src = f"{attrs.get('Печать', '')} {title_name} {desc}"
        for tag, rx in _PRINT_COLOR_RE:
            if rx.search(pc_src):
                print_color = tag
                break
        for m in _PAPER_FMT_RE.finditer(f"{desc} {title_name} {attrs.get('Формат', '')}"):
            paper_formats.add(m.group(1).upper().replace("А", "A"))

    # 10. Power W / VA
    power_w: list[float] = []
    power_va: list[float] = []
    if is_psu_sec or is_ups_sec:
        for k in ("Мощность", "Эффективная мощность"):
            raw_p = attrs.get(k)
            if raw_p is not None:
                m_p = re.search(r"(\d+(?:[.,]\d+)?)", str(raw_p))
                if m_p:
                    power_w.append(_to_float(m_p.group(1)))
        raw_va = attrs.get("Выходная мощность")
        if raw_va is not None:
            m_va = re.search(r"(\d+(?:[.,]\d+)?)", str(raw_va))
            if m_va:
                power_va.append(_to_float(m_va.group(1)))
        for m in _POWER_W_RE.finditer(full_text):
            power_w.append(_to_float(m.group(1)))
        for m in _POWER_VA_RE.finditer(full_text):
            power_va.append(_to_float(m.group(1)))
        for m in _POWER_KVA_RE.finditer(full_text):
            power_va.append(_to_float(m.group(1)) * 1000.0)
        if is_ups_sec and not power_va:
            for m in re.finditer(r"(?<!\d)(\d{3,4})(?=[uUaA]?\b)", title_name):
                v = float(m.group(1))
                if 300 <= v <= 10000 and v % 50 == 0:
                    power_va.append(v)

    # 11. Ports
    ports: list[int] = []
    if is_switch_sec or is_router_sec:
        if desc:
            for m in _DESC_PORTS_RE.finditer(desc):
                pt = int(m.group(1))
                if 2 <= pt <= 64:
                    ports.append(pt)
        for m in _PORTS_RE.finditer(full_text):
            pt = int(m.group(1))
            if 2 <= pt <= 64:
                ports.append(pt)
        if not ports:
            for m in _SWITCH_MODEL_PORTS_RE.finditer(title_name):
                ports.append(int(m.group(1)))

    # 12. Wireless, mic, PoE, rack U
    wireless = None
    with_mic = False
    if is_periph_sec:
        conn_src = f"{attrs.get('Подключение', '')} {attrs.get('Интерфейс', '')} {full_text}"
        if _WIRELESS_RE.search(conn_src):
            wireless = True
        elif _WIRED_RE.search(conn_src):
            wireless = False
        if device_subtype and "гарнитур" in device_subtype.casefold():
            with_mic = True
        elif re.search(r"\b(?:гарнитур\w*|headset)\b", title_name, re.I):
            with_mic = True
        elif re.search(r"\bнаушник\w*\b", title_name, re.I) and re.search(r"\bмикрофон\w*\b", full_text, re.I):
            with_mic = True

    poe = False
    if is_switch_sec or is_router_sec:
        poe_attr = str(attrs.get("ПредоставлениеPoE", "")).strip().casefold()
        poe = bool((poe_attr and poe_attr not in ("нет", "no", "false", "0")) or _POE_RE.search(full_text))

    rack_u = frozenset()
    if is_computer_sec or is_ups_sec or is_switch_sec:
        rack_u = frozenset(m.group(1).upper() for m in _RACK_U_RE.finditer(f"{attrs.get('Высота Rackmount', '')} {full_text}"))

    # 13. Compatibility (только для расходников и аксессуаров)
    compat_brand_tokens = frozenset()
    compat_tokens = frozenset()
    universal = False
    if is_consumable_sec:
        compat_brand_src = f"{attrs.get('Производитель принтера', '')} {attrs.get('Совместимость', '')}"
        compat_model_src = f"{attrs.get('Модель принтера', '')} {full_text}"
        compat_brand_tokens = _fast_tokens(compat_brand_src)
        compat_tokens = _fast_tokens(f"{compat_brand_src} {compat_model_src}")
        universal = bool(_UNIVERSAL_RE.search(full_text))

    return OfferSpecs(
        storage_gb=tuple(dict.fromkeys(storages)),
        ram_gb=tuple(dict.fromkeys(rams)),
        ram_types=frozenset(ram_types),
        diagonals=tuple(dict.fromkeys(diags)),
        resolutions=frozenset(resolutions),
        cpus=frozenset(cpus),
        gpus=frozenset(gpus),
        wifi=frozenset(wifi),
        interfaces=frozenset(interfaces),
        print_tech=print_tech,
        print_color=print_color,
        title_has_color=title_has_color,
        device_subtype=device_subtype,
        paper_formats=frozenset(paper_formats),
        power_w=tuple(dict.fromkeys(power_w)),
        power_va=tuple(dict.fromkeys(power_va)),
        ports=tuple(dict.fromkeys(ports)),
        wireless=wireless,
        with_mic=with_mic,
        poe=poe,
        rack_u=rack_u,
        compat_tokens=compat_tokens,
        compat_brand_tokens=compat_brand_tokens,
        universal=universal,
        title_tokens=title_tokens,
    )

def _merge_offer_specs(items: list[OfferSpecs]) -> OfferSpecs:
    if len(items) == 1:
        return items[0]
    return OfferSpecs(
        storage_gb=tuple(dict.fromkeys(v for s in items for v in s.storage_gb)),
        ram_gb=tuple(dict.fromkeys(v for s in items for v in s.ram_gb)),
        ram_types=frozenset().union(*(s.ram_types for s in items)),
        diagonals=tuple(dict.fromkeys(v for s in items for v in s.diagonals)),
        resolutions=frozenset().union(*(s.resolutions for s in items)),
        cpus=frozenset().union(*(s.cpus for s in items)),
        gpus=frozenset().union(*(s.gpus for s in items)),
        wifi=frozenset().union(*(s.wifi for s in items)),
        interfaces=frozenset().union(*(s.interfaces for s in items)),
        print_tech=next((s.print_tech for s in items if s.print_tech), None),
        print_color=next((s.print_color for s in items if s.print_color), None),
        title_has_color=any(s.title_has_color for s in items),
        device_subtype=next((s.device_subtype for s in items if s.device_subtype), None),
        paper_formats=frozenset().union(*(s.paper_formats for s in items)),
        power_w=tuple(dict.fromkeys(v for s in items for v in s.power_w)),
        power_va=tuple(dict.fromkeys(v for s in items for v in s.power_va)),
        ports=tuple(dict.fromkeys(v for s in items for v in s.ports)),
        wireless=True if any(s.wireless is True for s in items) else (False if any(s.wireless is False for s in items) else None),
        with_mic=any(s.with_mic for s in items),
        poe=any(s.poe for s in items),
        rack_u=frozenset().union(*(s.rack_u for s in items)),
        compat_tokens=frozenset().union(*(s.compat_tokens for s in items)),
        compat_brand_tokens=frozenset().union(*(s.compat_brand_tokens for s in items)),
        universal=any(s.universal for s in items),
        title_tokens=frozenset().union(*(s.title_tokens for s in items)),
    )


def _match_single_spec(key: str, target, spec: OfferSpecs) -> tuple[int, float]:
    """Оценка совпадения одного параметра: (tier, distance). tier=2 точно, 1 близко, 0 нет."""
    if key == "storage_gb":
        return _storage_match_tier(float(target), spec.storage_gb)
    if key == "ram_gb":
        t = float(target)
        if not spec.ram_gb:
            return (0, float("inf"))
        best_dist = min(abs(v - t) for v in spec.ram_gb)
        if best_dist <= 0.1:
            return (2, 0.0)
        return (0, best_dist)
    if key == "ram_type":
        return (2, 0.0) if target in spec.ram_types else (0, 1.0)
    if key == "diagonal":
        t = float(target)
        if not spec.diagonals:
            return (0, float("inf"))
        best_dist = min(abs(v - t) for v in spec.diagonals)
        if best_dist <= 0.15:
            return (2, best_dist)
        if best_dist <= 0.45:
            return (1, best_dist)
        return (0, best_dist)
    if key == "resolution":
        if target in spec.resolutions:
            return (2, 0.0)
        if target == "Full HD" and "1920x1200" in spec.resolutions:
            return (1, 0.5)
        return (0, 1.0)
    if key == "cpu":
        if target in spec.cpus:
            return (2, 0.0)
        if " " in str(target) and str(target).split()[0] in spec.cpus:
            return (1, 0.5)
        return (0, 1.0)
    if key == "gpu":
        t = str(target).upper()
        if t in spec.gpus:
            return (2, 0.0)
        if " " in t and t.split()[0] in spec.gpus:
            return (1, 0.5)
        return (0, 1.0)
    if key == "wifi":
        if target in spec.wifi:
            return (2, 0.0)
        if target == "Wi-Fi 6" and "Wi-Fi 7" in spec.wifi:
            return (1, 0.5)
        return (0, 1.0)
    if key == "interface":
        if target in spec.interfaces:
            return (2, 0.0)
        if target == "NVMe" and "M.2" in spec.interfaces:
            return (1, 0.5)
        if target == "M.2" and "NVMe" in spec.interfaces:
            return (1, 0.5)
        return (0, 1.0)
    if key == "print_tech":
        return (2, 0.0) if spec.print_tech == target else (0, 1.0)
    if key == "print_color":
        return (2, 0.0) if spec.print_color == target else (0, 1.0)
    if key == "paper_format":
        return (2, 0.0) if target in spec.paper_formats else (0, 1.0)
    if key == "power_w":
        t = float(target)
        if not spec.power_w:
            return (0, float("inf"))
        best_dist = min(abs(v - t) for v in spec.power_w)
        if best_dist <= 15.0:
            return (2, best_dist)
        return (0, best_dist)
    if key == "power_va":
        t = float(target)
        if not spec.power_va:
            return (0, float("inf"))
        best_dist = min(abs(v - t) for v in spec.power_va)
        if best_dist <= 50.0:
            return (2, best_dist)
        return (0, best_dist)
    if key == "ports":
        t = int(target)
        if not spec.ports:
            return (0, float("inf"))
        best_dist = min(abs(v - t) for v in spec.ports)
        if best_dist == 0:
            return (2, 0.0)
        return (0, float(best_dist))
    if key == "wireless":
        return (2, 0.0) if spec.wireless is target else (0, 1.0)
    if key == "with_mic":
        return (2, 0.0) if spec.with_mic else (0, 1.0)
    if key == "poe":
        return (2, 0.0) if spec.poe else (0, 1.0)
    if key == "rack_u":
        return (2, 0.0) if target in spec.rack_u else (0, 1.0)
    return (0, 1.0)


class HardwareSpecIndex:
    """Индекс подтверждённых параметров карточек оборудования и разбор запросов."""

    def __init__(self, feed_index, kb_dir: Path | str):
        self.index = feed_index
        self.kb_dir = Path(kb_dir)
        data = self._load_yaml(self.kb_dir / "hardware_specs.yaml")
        self.devices: list[dict] = data.get("devices", [])
        self.device_by_id: dict[str, dict] = {d["id"]: d for d in self.devices}
        self.known_brands: dict[str, str] = {
            normalize(k): v for k, v in data.get("known_brands", {}).items()
        }
        self.model_series: dict[str, str] = {
            normalize(s): s for s in data.get("model_series", [])
        }
        self.spec_labels: dict[str, str] = data.get("spec_labels", {})

        # Таблица триггеров: сортируем от самых длинных к коротким.
        triggers: list[tuple[str, re.Pattern, dict]] = []
        for dev in self.devices:
            for trig in dev.get("triggers", ()):
                tn = normalize(trig)
                if not tn:
                    continue
                rx = re.compile(r"(?<!\w)" + re.escape(tn) + r"(?!\w)")
                triggers.append((tn, rx, dev))
        triggers.sort(key=lambda item: (-len(item[0]), item[0]))
        self._triggers = triggers

        # Все фактические vendor_id аппаратных карточек в каталоге (например «hp inc.», «dell technologies»).
        hw_vendor_ids: dict[str, set[str]] = {}
        for cid, card in feed_index.cat.cards.items():
            if card.offers[0].domain != "hardware":
                continue
            vid = feed_index.card_vendors.get(cid)
            if not vid:
                continue
            clean_v = re.sub(r"[^a-zа-я0-9]+", " ", normalize(vid)).strip()
            if clean_v:
                hw_vendor_ids.setdefault(clean_v, set()).add(vid)
                first_tok = clean_v.split()[0]
                if len(first_tok) >= 2:
                    hw_vendor_ids.setdefault(first_tok, set()).add(vid)

        def resolve_vids(key: str) -> frozenset[str]:
            clean_k = re.sub(r"[^a-zа-я0-9]+", " ", normalize(key)).strip()
            found = set(hw_vendor_ids.get(clean_k, ()))
            for alias_k in (key, clean_k, clean_k.replace(" ", "-")):
                v = feed_index.vendor_names.get(alias_k)
                if v:
                    found.add(v)
            if clean_k == "wd":
                found.update(hw_vendor_ids.get("western digital", ()))
            elif clean_k == "western digital":
                found.update(hw_vendor_ids.get("wd", ()))
            elif clean_k == "hewlett packard":
                found.update(hw_vendor_ids.get("hp", ()))
            return frozenset(found)

        # Бренды для поиска в запросе (от самых длинных к коротким).
        all_brands: dict[str, tuple[frozenset[str], str]] = {}
        for k, disp in self.known_brands.items():
            vids = resolve_vids(k)
            all_brands[k] = (vids, disp)
            if " " in k:
                all_brands.setdefault(k.replace(" ", "-"), (vids, disp))
        for name_key, vid in feed_index.vendor_names.items():
            if len(name_key) >= 2 and name_key not in all_brands:
                cards = feed_index.tags["vendors"].get(vid, ())
                if any(feed_index.cat.cards[c].offers[0].domain == "hardware" for c in cards):
                    sample_c = next(
                        (c for c in cards if feed_index.cat.cards[c].offers[0].domain == "hardware"),
                        None,
                    )
                    disp = feed_index.cat.cards[sample_c].offers[0].vendor if sample_c else name_key.title()
                    all_brands[name_key] = (frozenset({vid}), disp)
        self._brand_patterns = [
            (k, re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)"), vids, disp)
            for k, (vids, disp) in sorted(all_brands.items(), key=lambda kv: -len(kv[0]))
            if len(k) >= 2
        ]
        self._series_patterns = [
            (k, re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)"), raw)
            for k, raw in sorted(self.model_series.items(), key=lambda kv: -len(kv[0]))
        ]

        # Предвычисленные параметры всех аппаратных карточек каталога (1 раз при запуске).
        self.card_specs: dict[str, OfferSpecs] = {}
        self.offer_specs: dict[str, list[tuple[object, OfferSpecs]]] = {}
        self.hardware_sections: set[str] = set()
        for sec_id, members in feed_index.groups.items():
            if not members:
                continue
            first_card = feed_index.cat.cards[members[0]]
            if first_card.offers[0].domain != "hardware":
                continue
            self.hardware_sections.add(sec_id)
            sec_name = feed_index.classes.get(sec_id, "")
            for cid in members:
                card = feed_index.cat.cards[cid]
                per_offer = [_extract_offer_specs(o, card.title, sec_name) for o in card.offers]
                self.card_specs[cid] = _merge_offer_specs(per_offer)
                if len(card.offers) > 1:
                    self.offer_specs[cid] = list(zip(card.offers, per_offer))

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        if not path.exists():
            fallback = Path(__file__).resolve().parents[2] / "kb" / path.name
            if fallback.exists():
                path = fallback
            else:
                return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def resolve_section(self, device: dict, req_category: str | None = None) -> str | None:
        if req_category and req_category in self.hardware_sections:
            return req_category
        for cid in device.get("feed_classes", ()):
            s = str(cid)
            if s in self.hardware_sections:
                return s
        # Фоллбэк для синтетических каталогов в тестах — поиск по словам названия раздела.
        for kw in device.get("section_keywords", ()):
            kn = normalize(kw)
            for sec_id in self.hardware_sections:
                sec_name = self.index.class_names.get(sec_id, "")
                if kn == sec_name or kn in sec_name:
                    return sec_id
        return None

    def _detect_device(self, text: str) -> tuple[dict | None, str]:
        # Особый случай для «чехол для ...» — определяем раздел по целевому устройству.
        if re.search(r"\bчех[ое]л\w*\b", text):
            if _CASE_LAPTOP_RE.search(text):
                return self.device_by_id.get("laptop_bag"), "чехол"
            if _CASE_TABLET_RE.search(text):
                return self.device_by_id.get("tablet_case"), "чехол"
            if _CASE_PHONE_RE.search(text):
                return self.device_by_id.get("phone_case"), "чехол"
        for trig_str, rx, dev in self._triggers:
            if rx.search(text):
                return dev, trig_str
        return None, ""

    def parse_query(
        self,
        raw_q: str,
        norm: str,
        base: str,
        req_category: str | None = None,
        ignore: tuple | list | set = (),
        cond_platform: str | None = None,
    ) -> HardwareQuery | None:
        if req_category and req_category not in self.hardware_sections:
            return None
        if not base and not norm:
            return None

        # Строгий фильтр от программного обеспечения и торгового оборудования.
        if _TRADE_QUALIFIER_RE.search(norm):
            return None
        if _PO_FOR_RE.search(norm):
            return None

        # Проверяем, не начинается ли запрос с программного термина (до слова устройства).
        if _SOFTWARE_GUARD_RE.search(norm):
            return None

        # Если feed_conditions снял «для ipad / для iphone / для mac» как платформу ПО,
        # для аксессуаров («чехол для ipad», «блок питания для macbook») восстанавливаем цель из norm.
        work_base = _clean_text(base)
        work_norm = _clean_text(norm)
        suppress_platform = False
        dev, matched_trig = self._detect_device(work_base)
        if cond_platform and (dev is None or dev.get("is_consumable") or re.search(r"\b(?:чех[ое]л\w*|сумк\w*|заряд\w*|адаптер\w*|блок\w*\s+питан\w*)\b", work_norm)):
            dev_norm, trig_norm = self._detect_device(work_norm)
            if dev_norm and dev_norm.get("is_consumable"):
                dev, matched_trig = dev_norm, trig_norm
                work_base = work_norm
                suppress_platform = True

        if dev is None:
            return None

        section = self.resolve_section(dev, req_category=req_category)
        if not section:
            return None

        work = work_base
        ignore_set = set(ignore or ())
        ignore_all_specs = "specs" in ignore_set

        # 1. Количество штук («ноутбук 5 шт») — снимаем до парсинга голых чисел!
        hw_qty = None
        m_qty = _HW_QTY_RE.search(work)
        if m_qty:
            val_q = int(m_qty.group(1))
            if val_q > 0:
                hw_qty = {"value": val_q, "unit": "шт"}
            work = _HW_QTY_RE.sub(" ", work, count=1)

        specs: dict[str, object] = {}
        device_subtype = (dev.get("implied_specs") or {}).get("device_subtype")
        if (dev.get("implied_specs") or {}).get("with_mic"):
            specs["with_mic"] = True
        if matched_trig == "тонер" or matched_trig == "тонеры":
            device_subtype = "Тонер"
        elif matched_trig in ("картридж", "картриджи", "тонер-картридж", "тонер картридж"):
            device_subtype = "Картридж"

        # 2. Совместимость для расходников и аксессуаров («картридж для hp laserjet», «чехол для ipad»).
        compat_raw = None
        compat_brand = None
        compat_terms: tuple[str, ...] = ()
        is_consumable = bool(dev.get("is_consumable"))
        if is_consumable:
            # Снимаем сам триггер устройства для аккуратного извлечения цели совместимости.
            after_trig = re.sub(r"(?<!\w)" + re.escape(matched_trig) + r"(?!\w)", " ", work, count=1).strip()
            m_comp = _COMPAT_CLAUSE_RE.search(work)
            target_str = ""
            if m_comp:
                target_str = m_comp.group(1).strip()
                # Если триггер уже включал «для ноутбука», остаток после триггера точнее.
                if "для " in matched_trig and after_trig:
                    target_str = after_trig
            elif dev["id"] in ("tablet_case", "phone_case") and "для " in work_norm:
                m_c2 = _COMPAT_CLAUSE_RE.search(work_norm)
                if m_c2:
                    target_str = m_c2.group(1).strip()
            elif after_trig:
                # Беспредложная запись: «картридж hp», «тонер kyocera», «картридж hp laserjet»
                for bk, brx, bvids, bdisp in self._brand_patterns:
                    if brx.search(after_trig):
                        target_str = after_trig
                        break
            if target_str:
                raw_tokens = re.findall(r"[a-zа-я0-9]+", normalize(target_str))
                # Убираем слова самого устройства («принтера», «ноутбука»), но оставляем бренд/модель («hp», «laserjet», «ipad», «asus»).
                kept = [t for t in raw_tokens if t not in _COMPAT_HOST_STOP and not t.isdigit()]
                # Если после «для» было число модели (например «iphone 16» или «p1102»), сохраняем.
                if kept:
                    kept_full = [t for t in raw_tokens if t not in _COMPAT_HOST_STOP]
                    compat_terms = tuple(dict.fromkeys(kept_full))
                    for bk, brx, bvids, bdisp in self._brand_patterns:
                        if brx.search(" ".join(kept_full)):
                            compat_brand = next(iter(bvids), bk)
                            break
                    # Красивое форматирование для чипа «Совместимость · ...».
                    pretty_parts = []
                    for t in kept_full:
                        if t in self.known_brands:
                            pretty_parts.append(self.known_brands[t])
                        elif t == "ipad":
                            pretty_parts.append("iPad")
                        elif t == "iphone":
                            pretty_parts.append("iPhone")
                        elif t == "macbook":
                            pretty_parts.append("MacBook")
                        elif t == "laserjet":
                            pretty_parts.append("LaserJet")
                        elif t in self.model_series:
                            pretty_parts.append(t.title())
                        else:
                            pretty_parts.append(t.upper() if len(t) <= 3 and t.isascii() else t.title())
                    compat_raw = " ".join(pretty_parts)
                    # Убираем часть совместимости из work, чтобы «laserjet» не дал print_tech=laser.
                    if m_comp:
                        work = work[:m_comp.start()].strip()
                    else:
                        work = re.sub(r"(?<!\w)" + re.escape(target_str) + r"(?!\w)", " ", work, count=1)

        # 3. Разрешение экрана
        m_dim = _RES_DIM_RE.search(work)
        if m_dim:
            tag = _classify_pixels(int(m_dim.group(1)), int(m_dim.group(2)))
            specs["resolution"] = tag or f"{m_dim.group(1)}x{m_dim.group(2)}"
            work = work[:m_dim.start()] + " " + work[m_dim.end():]
        elif _RES_4K_RE.search(work):
            specs["resolution"] = "4K"
            work = _RES_4K_RE.sub(" ", work, count=1)
        elif _RES_QHD_RE.search(work):
            specs["resolution"] = "2560x1440"
            work = _RES_QHD_RE.sub(" ", work, count=1)
        elif _RES_FHD_RE.search(work):
            specs["resolution"] = "Full HD"
            work = _RES_FHD_RE.sub(" ", work, count=1)

        # 4. Wi-Fi стандарт
        m_wifi = _WIFI_RE.search(work)
        if m_wifi:
            g1 = (m_wifi.group(1) or "").upper()
            g2 = (m_wifi.group(2) or "").casefold()
            if g1 == "7" or g2 == "be":
                specs["wifi"] = "Wi-Fi 7"
            elif g1 == "6E":
                specs["wifi"] = "Wi-Fi 6E"
            elif g1 == "6" or g2 == "ax":
                specs["wifi"] = "Wi-Fi 6"
            elif g1 == "5" or g2 == "ac":
                specs["wifi"] = "Wi-Fi 5"
            work = work[:m_wifi.start()] + " " + work[m_wifi.end():]

        # 5. Тип памяти DDR3/DDR4/DDR5
        m_rt = _RAM_TYPE_RE.search(work)
        if m_rt:
            specs["ram_type"] = m_rt.group(1).upper()
            work = work[:m_rt.start()] + " " + work[m_rt.end():]

        # 6. Процессор
        m_cpu = _CPU_INTEL_RE.search(work)
        if m_cpu:
            d = m_cpu.group(1) or m_cpu.group(2)
            specs["cpu"] = f"i{d}"
            work = work[:m_cpu.start()] + " " + work[m_cpu.end():]
        else:
            m_ry = _CPU_RYZEN_RE.search(work)
            if m_ry:
                specs["cpu"] = f"ryzen {m_ry.group(1)}" if m_ry.group(1) else "ryzen"
                work = work[:m_ry.start()] + " " + work[m_ry.end():]
            else:
                m_xn = _CPU_XEON_RE.search(work)
                if m_xn:
                    specs["cpu"] = f"xeon {m_xn.group(1).casefold()}" if m_xn.group(1) else "xeon"
                    work = work[:m_xn.start()] + " " + work[m_xn.end():]
                else:
                    m_co = _CPU_OTHER_RE.search(work)
                    if m_co:
                        specs["cpu"] = m_co.group(1).casefold()
                        work = work[:m_co.start()] + " " + work[m_co.end():]

        # 7. Видеокарта / GPU
        m_gpu = _GPU_RTX_RE.search(work)
        if m_gpu:
            fam = m_gpu.group(1).upper()
            specs["gpu"] = f"{fam} {re.sub(r'\\s+', ' ', m_gpu.group(2).strip()).upper()}" if m_gpu.group(2) else fam
            work = work[:m_gpu.start()] + " " + work[m_gpu.end():]
        else:
            m_go = _GPU_OTHER_RE.search(work)
            if m_go:
                specs["gpu"] = re.sub(r"\s+", " ", m_go.group(1).strip()).upper()
                work = work[:m_go.start()] + " " + work[m_go.end():]

        # 8. Объём накопителя и ОЗУ с единицами измерения (ГБ / ТБ / GB / TB)
        gb_role = dev.get("gb_role")
        for m_cap in list(_CAPACITY_RE.finditer(work)):
            val = _to_float(m_cap.group("val"))
            unit = m_cap.group("unit").casefold()
            if unit in ("тб", "tb"):
                val *= 1000.0
            pre = (m_cap.group("pre") or "").casefold()
            post = (m_cap.group("post") or "").casefold()
            if pre in ("озу", "ram") or pre.startswith("оператив") or post in ("озу", "ram") or post.startswith(("ddr", "lpddr")):
                specs["ram_gb"] = val
            elif pre in ("ssd", "ссд", "hdd") or pre.startswith("диск") or post in ("ssd", "ссд", "hdd"):
                specs["storage_gb"] = val
            elif gb_role in ("ram", "vram"):
                specs["ram_gb"] = val
            elif gb_role == "storage":
                specs["storage_gb"] = val
            else:
                if unit in ("тб", "tb") or val >= 128:
                    specs["storage_gb"] = val
                else:
                    specs["ram_gb"] = val
        work = _CAPACITY_RE.sub(" ", work)

        # 9. Мощность (Вт / ВА / кВА)
        m_kva = _POWER_KVA_RE.search(work)
        if m_kva:
            specs["power_va"] = _to_float(m_kva.group(1)) * 1000.0
            work = work[:m_kva.start()] + " " + work[m_kva.end():]
        m_va = _POWER_VA_RE.search(work)
        if m_va:
            specs["power_va"] = _to_float(m_va.group(1))
            work = work[:m_va.start()] + " " + work[m_va.end():]
        m_w = _POWER_W_RE.search(work)
        if m_w:
            specs["power_w"] = _to_float(m_w.group(1))
            work = work[:m_w.start()] + " " + work[m_w.end():]

        # 10. Число портов
        m_ports = _PORTS_RE.search(work)
        if m_ports:
            p = int(m_ports.group(1))
            if 2 <= p <= 64:
                specs["ports"] = p
                work = work[:m_ports.start()] + " " + work[m_ports.end():]

        # 11. Диагональ с единицей (дюйм / " / ″ из raw_q)
        m_dw = _DIAG_WORD_RE.search(work)
        if m_dw:
            d = _to_float(m_dw.group(1))
            if 5.0 <= d <= 98.0:
                specs["diagonal"] = d
                work = work[:m_dw.start()] + " " + work[m_dw.end():]
        else:
            m_dr = _DIAG_RAW_RE.search(raw_q)
            if m_dr:
                prefix = raw_q[:m_dr.start()].casefold()
                if not re.search(r"\b(?:до|от|дешевле|дороже)\s*$", prefix):
                    d = _to_float(m_dr.group(1))
                    if 5.0 <= d <= 98.0:
                        specs["diagonal"] = d
                        work = re.sub(r"(?<!\d)" + re.escape(m_dr.group(1).replace(",", ".")) + r"(?!\d)", " ", work, count=1)

        # 12. Формат бумаги (A3 / A4)
        if dev["id"] in ("printer", "mfp", "scanner", "plotter", "consumable"):
            m_pf = _PAPER_FMT_RE.search(work)
            if m_pf:
                specs["paper_format"] = m_pf.group(1).upper().replace("А", "A")
                work = work[:m_pf.start()] + " " + work[m_pf.end():]

        # 13. Высота в стойке (1U / 2U / 4U)
        if dev["id"] in ("server", "ups", "switch"):
            m_ru = _RACK_U_RE.search(work)
            if m_ru:
                specs["rack_u"] = m_ru.group(1).upper()
                work = work[:m_ru.start()] + " " + work[m_ru.end():]

        # 14. Тип печати и цветность
        if dev["id"] in ("printer", "mfp", "plotter", "consumable"):
            for tag, rx in _PRINT_TECH_RE:
                if rx.search(work):
                    specs["print_tech"] = tag
                    work = rx.sub(" ", work, count=1)
                    break
            for tag, rx in _PRINT_COLOR_RE:
                if rx.search(work):
                    specs["print_color"] = tag
                    work = rx.sub(" ", work, count=1)
                    break

        # 15. Интерфейсы и подключение
        for label, rx in _INTERFACE_PATTERNS:
            if rx.search(work):
                specs["interface"] = label
                work = rx.sub(" ", work, count=1)
                break
        if _POE_RE.search(work):
            specs["poe"] = True
            work = _POE_RE.sub(" ", work, count=1)
        if _WIRELESS_RE.search(work):
            specs["wireless"] = True
            work = _WIRELESS_RE.sub(" ", work, count=1)
        elif _WIRED_RE.search(work):
            specs["wireless"] = False
            work = _WIRED_RE.sub(" ", work, count=1)
        if dev["id"] in ("headphones", "headset") and _WITH_MIC_RE.search(work):
            specs["with_mic"] = True
            work = _WITH_MIC_RE.sub(" ", work, count=1)

        # 16. Производитель и модельный ряд (для не-расходников)
        vendor_id = None
        vendor_ids: frozenset[str] = frozenset()
        vendor_label = None
        absent_vendor = False
        series = None

        work_no_trig = re.sub(r"(?<!\w)" + re.escape(matched_trig) + r"(?!\w)", " ", work, count=1)
        if not is_consumable:
            for bk, brx, bvids, bdisp in self._brand_patterns:
                if brx.search(work_no_trig):
                    # Не принимаем «intel»/«amd»/«nvidia» за производителя ноутбука/сервера, если уже задан CPU/GPU.
                    if bk in ("intel", "amd", "nvidia") and ("cpu" in specs or "gpu" in specs):
                        continue
                    vendor_ids = bvids
                    vendor_id = next(iter(bvids), None)
                    vendor_label = bdisp
                    absent_vendor = not bvids
                    work_no_trig = brx.sub(" ", work_no_trig, count=1)
                    break

        for sk, srx, sraw in self._series_patterns:
            if srx.search(work_no_trig):
                series = sraw
                work_no_trig = srx.sub(" ", work_no_trig, count=1)
                break

        # 17. Голое число при устройстве («монитор 27», «ssd 500», «коммутатор 24», «ибп 1000»)
        bare_spec = dev.get("bare_number_spec")
        bare_range = dev.get("bare_number_range")
        if bare_spec and bare_range and bare_spec not in specs:
            for m_num in re.finditer(r"(?<![a-zа-я0-9-])(\d+(?:[.,]\d)?)(?![a-zа-я0-9-])", work_no_trig):
                val = _to_float(m_num.group(1))
                lo, hi = bare_range[0], bare_range[1]
                if lo <= val <= hi:
                    if bare_spec == "ports" and int(val) != val:
                        continue
                    specs[bare_spec] = int(val) if bare_spec == "ports" else val
                    break

        # 18. Учёт снятых пользователем чипов (req.ignore)
        if ignore_all_specs:
            specs.clear()
            series = None
            compat_raw = None
            compat_brand = None
            compat_terms = ()
        else:
            for k in list(specs):
                if f"spec:{k}" in ignore_set:
                    del specs[k]
            if "spec:series" in ignore_set:
                series = None
            if "spec:compat" in ignore_set:
                compat_raw = None
                compat_brand = None
                compat_terms = ()

        display_specs: dict[str, str] = {}
        for k, v in specs.items():
            display_specs[k] = _format_spec_value(k, v)
        if series:
            display_specs["series"] = series.title() if series.islower() and len(series) > 3 else series.upper() if len(series) <= 3 else series
        if compat_raw:
            display_specs["compat"] = compat_raw

        return HardwareQuery(
            device_id=dev["id"],
            section=section,
            specs=specs,
            display_specs=display_specs,
            vendor_id=vendor_id,
            vendor_ids=vendor_ids,
            vendor_label=vendor_label,
            absent_vendor=absent_vendor,
            series=series,
            compat_raw=compat_raw,
            compat_brand=compat_brand,
            compat_terms=compat_terms,
            device_subtype=device_subtype,
            is_consumable=is_consumable,
            hw_qty=hw_qty,
            suppress_cond_platform=suppress_platform,
            no_sibling_fill=bool(
                dev["id"] != "server"
                or specs
                or vendor_id
                or absent_vendor
                or series
                or compat_terms
                or hw_qty
            ),
        )

    def apply(
        self,
        section: str,
        members: list[str],
        hw_query: HardwareQuery,
        preferred: dict,
        vendor: str | None = None,
    ) -> tuple[list[str], str, bool]:
        """Отсортировать/отобрать карточки раздела по параметрам, серии, вендору и совместимости.

        Возвращает (ordered_members, note, vendor_absent_in_section).
        """
        if not members:
            return members, "", False

        sec_label = self.index.classes.get(section, "")
        notes: list[str] = []
        pool = list(members)
        vendor_absent = False

        # 1. Производитель (для не-расходников)
        eff_vids = set(hw_query.vendor_ids)
        if vendor:
            eff_vids.add(vendor)
        if not hw_query.is_consumable and (eff_vids or hw_query.absent_vendor):
            v_matches = [cid for cid in pool if self.index.card_vendors.get(cid) in eff_vids]
            if v_matches:
                pool = v_matches
            else:
                vendor_absent = True
                v_disp = hw_query.vendor_label or (vendor.title() if vendor else "")
                notes.append(f"В разделе «{sec_label}» товаров производителя {v_disp} нет.")

        # 2. Подтип устройства в составном разделе (МФУ vs Принтер, Тонер vs Картридж)
        if hw_query.device_subtype:
            sub_low = hw_query.device_subtype.casefold()

            def subtype_tier(cid: str) -> int:
                cs = self.card_specs.get(cid)
                title = self.index.cat.cards[cid].title.casefold()
                st = (cs.device_subtype or "").casefold() if cs else ""
                if sub_low == "мфу":
                    if "мфу" in st or re.search(r"\b(?:мфу|mfp)\b", title):
                        return 2
                    if "плоттер" in st or "designjet" in title:
                        return 0
                    return 1
                if sub_low == "принтер":
                    if st == "принтер" or re.search(r"\b(?:принтер|printer)\b", title):
                        return 2
                    if "мфу" in st or re.search(r"\b(?:мфу|mfp)\b", title):
                        return 1
                    return 0
                if sub_low == "тонер":
                    if "тонер" in st or "тонер" in title:
                        return 2
                    if "картридж" in st or "картридж" in title:
                        return 1
                    return 0
                if sub_low == "картридж":
                    if "картридж" in st or "картридж" in title:
                        return 2
                    if "тонер" in st or "тонер" in title:
                        return 1
                    return 0
                return 1

            sub_tiers = {subtype_tier(cid) for cid in pool}
            if len(sub_tiers) > 1 and max(sub_tiers) >= 2:
                # В разделе Принтеры и МФУ при запросе «мфу» не смешиваем с плоттерами DesignJet.
                pool.sort(key=subtype_tier, reverse=True)

        # 3. Совместимость для расходников и аксессуаров
        if hw_query.is_consumable and hw_query.compat_terms:
            c_terms = hw_query.compat_terms
            c_brand = normalize(hw_query.compat_brand or "")
            c_brand_first = c_brand.split()[0] if c_brand else ""

            def compat_score(cid: str):
                cs = self.card_specs.get(cid)
                if not cs:
                    return (0, 0, 0, 0)
                term_hits = sum(1 for t in c_terms if t in cs.compat_tokens)
                all_terms = 1 if term_hits == len(c_terms) else 0
                brand_hit = 1 if (c_brand_first and (c_brand_first in cs.compat_brand_tokens or c_brand_first in cs.compat_tokens)) else 0
                orig_vendor = 1 if (hw_query.compat_brand and self.index.card_vendors.get(cid) == hw_query.compat_brand) else 0
                # Подтип расходника (картридж vs тонер vs плёнка/обложки)
                sub_bonus = 0
                if hw_query.device_subtype:
                    st = (cs.device_subtype or "").casefold()
                    tl = self.index.cat.cards[cid].title.casefold()
                    if hw_query.device_subtype.casefold() in st or hw_query.device_subtype.casefold() in tl:
                        sub_bonus = 1
                univ = 1 if cs.universal else 0
                return (all_terms, term_hits, brand_hit, sub_bonus, orig_vendor, univ)

            scored = [(compat_score(cid), idx, cid) for idx, cid in enumerate(pool)]
            has_compat = any(s[0][1] > 0 or s[0][2] > 0 for s in scored)
            has_univ = any(s[0][5] > 0 for s in scored)
            scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)
            pool = [cid for _, _, cid in scored]
            if not has_compat:
                if has_univ:
                    notes.append(
                        f"В разделе «{sec_label}» моделей с подтверждённой совместимостью с {hw_query.compat_raw} нет, показаны универсальные и доступные варианты."
                    )
                else:
                    notes.append(
                        f"В разделе «{sec_label}» моделей с подтверждённой совместимостью с {hw_query.compat_raw} нет. Показаны доступные товары раздела."
                    )

        # 4. Серия модели («ThinkPad», «Odyssey», «Archer», «FURY»)
        if hw_query.series:
            s_tok = normalize(hw_query.series)
            s_hits = [
                cid for cid in pool
                if s_tok in (self.card_specs[cid].title_tokens if cid in self.card_specs else ())
                or s_tok in normalize(self.index.cat.cards[cid].title)
            ]
            if s_hits:
                s_set = set(s_hits)
                pool = s_hits + [cid for cid in pool if cid not in s_set]
            else:
                notes.append(
                    f"Моделей серии «{hw_query.display_specs.get('series', hw_query.series)}» в разделе «{sec_label}» нет, показаны ближайшие."
                )

        # 5. Технические параметры (объём, память, диагональ, разрешение, CPU, GPU, Wi-Fi, порты, мощность и т.д.)
        if hw_query.specs:
            req_specs = list(hw_query.specs.items())

            def eval_card(cid: str):
                cs = self.card_specs.get(cid)
                if not cs:
                    return (0, 0, 0, float("inf"), 0)
                matched_count = 0
                exact_count = 0
                total_dist = 0.0
                for k, v in req_specs:
                    tier, dist = _match_single_spec(k, v, cs)
                    if tier >= 1:
                        matched_count += 1
                    if tier >= 2:
                        exact_count += 1
                    if math.isfinite(dist):
                        total_dist += dist
                    else:
                        total_dist += 1e9
                # Бонус, если цветность/параметр явно в заголовке карточки (например «Color LaserJet» для «мфу лазерное цветное»).
                title_bonus = 1 if (hw_query.specs.get("print_color") == "color" and cs.title_has_color) else 0
                # Для «мфу» / «принтер» сохраняем приоритет точного подтипа внутри совпавших по параметрам.
                sub_bonus = 0
                if hw_query.device_subtype:
                    st = (cs.device_subtype or "").casefold()
                    tl = self.index.cat.cards[cid].title.casefold()
                    if hw_query.device_subtype.casefold() == "мфу":
                        sub_bonus = 2 if ("мфу" in st or "мфу" in tl or "mfp" in tl) else (0 if "designjet" in tl or "плоттер" in st else 1)
                    elif hw_query.device_subtype.casefold() == "принтер":
                        sub_bonus = 2 if (st == "принтер" or "принтер" in tl) else 1
                return (matched_count, exact_count, sub_bonus, title_bonus, -total_dist)

            scored_specs = [(eval_card(cid), idx, cid) for idx, cid in enumerate(pool)]
            max_matched = max((s[0][0] for s in scored_specs), default=0)

            # Выбор наилучшего оффера для многовариантных карточек
            for _, _, cid in scored_specs:
                if cid in self.offer_specs:
                    best_o = max(
                        self.offer_specs[cid],
                        key=lambda pair: (
                            sum(1 for k, v in req_specs if _match_single_spec(k, v, pair[1])[0] >= 1),
                            sum(1 for k, v in req_specs if _match_single_spec(k, v, pair[1])[0] >= 2),
                            pair[0].available,
                        ),
                    )
                    if any(_match_single_spec(k, v, best_o[1])[0] >= 1 for k, v in req_specs):
                        preferred[cid] = best_o[0]

            scored_specs.sort(key=lambda item: (item[0], -item[1]), reverse=True)
            pool = [cid for _, _, cid in scored_specs]

            if max_matched < len(req_specs):
                # Не нашлось карточек с полным совпадением всех параметров — честное пояснение и ближайшие!
                missing_parts = []
                for k, v in req_specs:
                    any_hit = any(
                        cid in self.card_specs and _match_single_spec(k, v, self.card_specs[cid])[0] >= 1
                        for cid in pool
                    )
                    if not any_hit:
                        missing_parts.append((k, hw_query.display_specs.get(k, str(v))))
                if len(missing_parts) == 1:
                    mk, mv = missing_parts[0]
                    phrase = {
                        "storage_gb": f"С объёмом {mv}",
                        "ram_gb": f"С памятью {mv}",
                        "diagonal": f"С диагональю {mv}",
                        "resolution": f"С разрешением {mv}",
                        "cpu": f"С процессором {mv}",
                        "gpu": f"С графикой {mv}",
                        "wifi": f"Со стандартом {mv}",
                        "ports": f"С числом портов {mv}",
                        "power_w": f"С мощностью {mv}",
                        "power_va": f"С мощностью {mv}",
                        "paper_format": f"С форматом {mv}",
                    }.get(mk, f"С параметром «{self.spec_labels.get(mk, mk)} · {mv}»")
                    notes.append(f"{phrase} в разделе «{sec_label}» нет, показаны ближайшие.")
                elif missing_parts:
                    joined = ", ".join(f"{self.spec_labels.get(k, k)} · {v}" for k, v in missing_parts)
                    notes.append(f"С параметрами ({joined}) в разделе «{sec_label}» нет, показаны ближайшие.")
                else:
                    joined = ", ".join(f"{self.spec_labels.get(k, k)} · {hw_query.display_specs.get(k, v)}" for k, v in req_specs)
                    notes.append(f"Точного сочетания параметров ({joined}) в разделе «{sec_label}» нет, показаны ближайшие.")

        if vendor_absent and len(notes) == 1:
            if hw_query.specs:
                matched_str = ", ".join(
                    f"{self.spec_labels.get(k, k)} · {hw_query.display_specs.get(k, v)}"
                    for k, v in hw_query.specs.items()
                )
                notes.append(f"Показаны доступные товары раздела с учётом параметров ({matched_str}).")
            else:
                notes.append("Показаны доступные товары раздела.")

        return pool, " ".join(notes), vendor_absent

    def populate_result(self, hw_query: HardwareQuery | None, result: dict, chips: list[dict]) -> None:
        if not hw_query:
            return
        if hw_query.display_specs:
            result["understood"]["filters"]["specs"] = dict(hw_query.display_specs)
            seen = {c.get("key") for c in chips}
            for k, disp in hw_query.display_specs.items():
                chip_key = f"spec:{k}"
                if chip_key in seen:
                    continue
                label_prefix = self.spec_labels.get(k, k)
                chips.append(dict(key=chip_key, label=f"{label_prefix} · {disp}", removable=True))
                seen.add(chip_key)
        if hw_query.hw_qty and not result["understood"].get("qty"):
            result["understood"]["qty"] = hw_query.hw_qty
            if not any(c.get("key") == "quantity" for c in chips):
                chips.append(dict(key="quantity", label=f"Количество · {hw_query.hw_qty['value']}", removable=False))
