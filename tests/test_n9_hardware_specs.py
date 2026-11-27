"""Тесты трека N9: параметры оборудования, серии, вендоры и совместимость расходников."""
import json
from dataclasses import replace

import pytest

from kuznitsa.engine import Engine
from kuznitsa.llm.jev import Disabled
from kuznitsa.schema import Request


@pytest.fixture(scope="module")
def n9_engine(cfg, tmp_path_factory):
    data = tmp_path_factory.mktemp("n9_feed")
    rows = []

    def add(
        oid,
        title,
        section_id,
        section_name,
        *,
        root="Оборудование",
        domain="hardware",
        vendor="TestVendor",
        price=10000.0,
        attrs=None,
        description="",
        gid=None,
        available=True,
    ):
        a = dict(attrs or {})
        a["class_id"] = section_id
        a["domain"] = domain
        rows.append(
            dict(
                offer_id=oid,
                group_id=gid or oid,
                name=title,
                family_name=title,
                class_id=section_id,
                category_id=section_id,
                category_path=[root, section_name],
                domain=domain,
                vendor=vendor,
                price=price,
                attrs=a,
                description=description,
                lic={"model": "perpetual", "metric": "device"} if domain == "software" else {},
                available=available,
                in_stock=available,
            )
        )

    # 1. SSD (79574) — 256 ГБ, 500/512 ГБ, 1 ТБ (1000 и 1024 ГБ), 2 ТБ, 4 ТБ (3 ТБ нет!)
    add("ssd_256", "Твердотельный накопитель SSD 256GB SATA", "79574", "Внутренние твердотельные накопители (SSD)",
        vendor="Kingston", price=3200, attrs={"Ёмкость диска": "256", "Интерфейс": "SATA3"})
    add("ssd_512", "Твердотельный накопитель SSD 512 ГБ NVMe", "79574", "Внутренние твердотельные накопители (SSD)",
        vendor="ADATA", price=4900, attrs={"Ёмкость диска": "512", "Интерфейс": "PCI Express; M.2", "Форм-фактор": "M.2 (NGFF)"})
    add("ssd_1000", "Твердотельный накопитель SSD 1TB M.2", "79574", "Внутренние твердотельные накопители (SSD)",
        vendor="Samsung", price=8900, attrs={"Ёмкость диска": "1000", "Интерфейс": "PCI Express; M.2"})
    add("ssd_1024", "Твердотельный накопитель SSD 1024 ГБ SATA", "79574", "Внутренние твердотельные накопители (SSD)",
        vendor="Netac", price=7500, attrs={"Ёмкость диска": "1024", "Интерфейс": "SATA3"})
    add("ssd_2000", "Твердотельный накопитель SSD 2 ТБ NVMe", "79574", "Внутренние твердотельные накопители (SSD)",
        vendor="Kingston", price=14900, attrs={"Ёмкость диска": "2000", "Интерфейс": "PCI Express; M.2"})
    add("ssd_4000", "Твердотельный накопитель SSD 4TB NVMe", "79574", "Внутренние твердотельные накопители (SSD)",
        vendor="Samsung", price=29900, attrs={"Ёмкость диска": "4000", "Интерфейс": "PCI Express; M.2"})

    # 2. Ноутбуки (70824) — разные ОЗУ, процессоры (i5, i7, Core Ultra 7), диагонали, серии
    add("lap_i5_8", "Ноутбук ASUS VivoBook 15", "70824", "Ноутбуки",
        vendor="ASUS", price=52000,
        attrs={"Объем установленной ОЗУ": "8 ГБ", "Объем установленного SSD": "512 ГБ", "Диагональ экрана": "16"},
        description="15.6in • 1920×1080 • Intel Core i5-1335U • 8 ГБ DDR4 • SSD 512 ГБ")
    add("lap_i7_16", "Ноутбук HP ProBook 450 G10", "70824", "Ноутбуки",
        vendor="HP Inc.", price=89000,
        attrs={"Объем установленной ОЗУ": "16 ГБ", "Объем установленного SSD": "512 ГБ", "Диагональ экрана": "16"},
        description="15.6in • 1920×1080 • Intel Core i7-1355U • 16 ГБ DDR4 • SSD 512 ГБ")
    add("lap_u7_16", "Ноутбук ASUS ExpertBook P1", "70824", "Ноутбуки",
        vendor="ASUS", price=95000,
        attrs={"Объем установленной ОЗУ": "16 ГБ", "Объем установленного SSD": "1 ТБ", "Диагональ экрана": "16"},
        description="15.6in • 1920×1080 • Intel Core Ultra 7 255H • 16 ГБ DDR5 • SSD 1 ТБ")
    add("lap_len_v15", "Ноутбук LENOVO V15 G4", "70824", "Ноутбуки",
        vendor="LENOVO", price=54000,
        attrs={"Объем установленной ОЗУ": "8 ГБ", "Диагональ экрана": "16"},
        description="15.6in • Intel Core i5-13420H • 8 ГБ DDR4")
    add("lap_len_tp", "Ноутбук LENOVO ThinkPad E16 G2", "70824", "Ноутбуки",
        vendor="LENOVO", price=112000,
        attrs={"Объем установленной ОЗУ": "16 ГБ", "Диагональ экрана": "16"},
        description="16in • 1920×1200 • AMD Ryzen 7 7735HS • 16 ГБ DDR5 • SSD 512 ГБ")

    # 3. Мониторы (80843) — 24", 27" FHD, 27" 4K (с ошибочным attr FullHD!), 32" 4K, Samsung 27"
    add("mon_24", "Монитор AOC 24B2 23.8-inch", "80843", "Мониторы",
        vendor="AOC", price=12500, attrs={"Диагональ": "23.8", "Разрешение экрана": "FullHD", "Интерфейсы": "HDMI; VGA"},
        description='23.8" LCD, 1920 × 1080, черный')
    add("mon_27_fhd", "Монитор LG 27MP400 27.0-inch", "80843", "Мониторы",
        vendor="LG", price=16000, attrs={"Диагональ": "27", "Разрешение экрана": "FullHD", "Интерфейсы": "HDMI"},
        description='27" IPS, 1920 × 1080, черный')
    add("mon_27_4k", "Монитор Philips 27E1N1800AE 27.0-inch", "80843", "Мониторы",
        vendor="Philips", price=31000, attrs={"Диагональ": "27", "Разрешение экрана": "FullHD", "Интерфейсы": "HDMI; DisplayPort; USB Type-C"},
        description='27" IPS, 3840 × 2160, черный')
    add("mon_27_sam", "Монитор Samsung S27CG550EI 27.0-inch", "80843", "Мониторы",
        vendor="Samsung", price=24500, attrs={"Диагональ": "27", "Разрешение экрана": "FullHD", "Интерфейсы": "HDMI; DisplayPort"},
        description='27" VA, 2560 × 1440, черный')
    add("mon_32_sam", "Монитор Samsung S32CG550EI 32.0-inch", "80843", "Мониторы",
        vendor="Samsung", price=32000, attrs={"Диагональ": "32", "Разрешение экрана": "FullHD"},
        description='32" VA, 2560 × 1440, черный')

    # 4. Оперативная память (76963) — DDR4 16GB, DDR5 16GB, DDR5 2x16GB (=32GB)
    add("ram_ddr4_16", "Оперативная память Kingston DDR4 16GB", "76963", "Оперативная память",
        vendor="Kingston", price=3900, attrs={"Тип памяти": "DDR4", "Ёмкость одного модуля": "16", "Количество в комплекте": "1"})
    add("ram_ddr5_16", "Оперативная память Patriot DDR5 16GB", "76963", "Оперативная память",
        vendor="Patriot", price=5500, attrs={"Тип памяти": "DDR5", "Ёмкость одного модуля": "16", "Количество в комплекте": "1"})
    add("ram_ddr5_32kit", "Оперативная память Kingston FURY Renegade KF564C32RSK2-32", "76963", "Оперативная память",
        vendor="Kingston", price=12900,
        attrs={"Тип памяти": "DDR5", "Ёмкость одного модуля": "16", "Количество в комплекте": "2"},
        description="2 × 16 ГБ, DDR5, 6400 МГц")

    # 5. Флешки USB (90395)
    add("usb_32", "Флешка Netac U505 32GB", "90395", "Флешки USB",
        vendor="Netac", price=450, attrs={"Ёмкость": "32", "Интерфейс": "USB 2.0"})
    add("usb_64", "Флешка Kingston DataTraveler 64GB USB 3.2", "90395", "Флешки USB",
        vendor="Kingston", price=790, attrs={"Ёмкость": "64", "Интерфейс": "USB 3.2"})

    # 6. Wi-Fi роутеры (85353) — Wi-Fi 5 и Wi-Fi 6 (по AX в названии, несмотря на attr 802.11ac!)
    add("rt_ac", "Роутер TP-LINK Archer C64", "85353", "Wi-Fi роутеры",
        vendor="TP-LINK", price=3100, attrs={"Протоколы Wi-Fi": "802.11ac"})
    add("rt_ax", "Роутер ASUS RT-AX53U", "85353", "Wi-Fi роутеры",
        vendor="ASUS", price=6900, attrs={"Протоколы Wi-Fi": "802.11ac"}, description="Wi-Fi 6, 802.11ax")

    # 7. Коммутаторы (85741) — 8 и 24 порта (Cisco в разделе нет!)
    add("sw_8", "Коммутатор TP-LINK TL-SG1008D", "85741", "Коммутаторы",
        vendor="TP-LINK", price=2400, description="16 Гбит/с, 8 × Gigabit port")
    add("sw_24", "Коммутатор D-LINK DES-1024D", "85741", "Коммутаторы",
        vendor="D-LINK", price=5800, description="4.8 Гбит/с, 24 × 10/100 port")
    add("sw_24_poe", "Коммутатор TP-LINK TL-SG1224P", "85741", "Коммутаторы",
        vendor="TP-LINK", price=19500, attrs={"ПредоставлениеPoE": "Да"}, description="24 × Gigabit port, PoE")

    # 8. Принтеры и МФУ (93995) — ч/б, цветное лазерное МФУ, A3, плоттер DesignJet
    add("mfp_mono", "МФУ Pantum M6500", "93995", "Принтеры и МФУ",
        vendor="PANTUM", price=18500, attrs={"Тип устройства": "МФУ", "Тип принтера": "Лазерный", "Печать": "Черно-белая"},
        description="МФУ, Лазерный, A4, ч/б")
    add("mfp_col", "МФУ HP Inc. Color LaserJet Pro 4303FDW", "93995", "Принтеры и МФУ",
        vendor="HP Inc.", price=64000, attrs={"Тип устройства": "МФУ", "Тип принтера": "Лазерный", "Печать": "Цветная"},
        description="МФУ, Лазерный, A4, цветная")
    add("prn_a3", "Принтер HP Inc. LaserJet Pro CP5225dn", "93995", "Принтеры и МФУ",
        vendor="HP Inc.", price=115000, attrs={"Тип устройства": "Принтер", "Тип принтера": "Лазерный", "Печать": "Цветная"},
        description="Принтер, Лазерный, A3")
    add("plot_dj", "Плоттер HP DesignJet T210", "93995", "Принтеры и МФУ",
        vendor="HP Inc.", price=98000, attrs={"Тип устройства": "Плоттер", "Тип принтера": "Струйный", "Печать": "Цветная"})

    # 9. Серверы (86563) + Dell HDD (78997) — Dell в серверах нет!
    add("srv_depo", "Сервер DEPO Storm 3450", "86563", "Rack-серверы",
        vendor="DEPO", price=320000, attrs={"Серия процессора": "Xeon Silver", "Высота Rackmount": "2U"})
    add("srv_nerpa", "Сервер NERPA Nord 2U", "86563", "Rack-серверы",
        vendor="NERPA", price=290000, attrs={"Серия процессора": "Xeon Gold", "Высота Rackmount": "2U"})
    add("hdd_dell_4tb", "Жесткий диск Dell Technologies 4TB SAS", "78997", "Жесткие диски",
        vendor="Dell Technologies", price=24000, attrs={"Ёмкость диска": "4000"})

    # 10. Блоки питания (74887), ИБП (82080), Видеокарты (77963 с греческой ГБ)
    add("psu_500", "Блок питания Accord ACC-500", "74887", "Блоки питания", vendor="Accord", price=2500, attrs={"Мощность": "500"})
    add("psu_650", "Блок питания Chieftec PPS-650FC", "74887", "Блоки питания", vendor="Chieftec", price=6900, attrs={"Мощность": "650"})
    add("ups_600", "ИБП Ippon Back Basic 650", "82080", "ИБП", vendor="Ippon", price=4900, attrs={"Выходная мощность": "650"})
    add("ups_1000", "ИБП Powercom SPD-1000U 1000VA", "82080", "ИБП", vendor="Powercom", price=9800, attrs={"Выходная мощность": "1000"})
    add("gpu_rtx", "Видеокарта Palit GeForce RTX 4060 8 \u0393Б", "77963", "Видеокарты",
        vendor="Palit", price=36000, attrs={"Графический процессор": "GeForce RTX 4060", "Объем памяти": "8"})

    # 11. Расходники (94694), БП для ноутбуков (84326), Чехлы для планшетов (84253)
    add("cons_hp_lj", "Картридж черный NVPrint LaserJet NV-CE390X", "94694", "Расходные материалы",
        vendor="NVPrint", price=2200, attrs={"kind": "Картридж", "Производитель принтера": "HP"},
        description="Черный, для принтера HP LaserJet")
    add("cons_kyo", "Тонер-картридж черный Kyocera TK-1150", "94694", "Расходные материалы",
        vendor="Kyocera", price=4900, attrs={"kind": "Тонер-картридж", "Производитель принтера": "Kyocera"},
        description="Черный, для:Kyocera")
    add("cons_film", "Пленка для ламинирования A4", "94694", "Расходные материалы",
        vendor="Buro", price=600, attrs={"kind": "Пленка"})
    add("lpsu_65", "Блок питания Ippon D65U", "84326", "Источники питания для ноутбуков",
        vendor="Ippon", price=1900, description="Универсальный адаптер для ноутбуков мощностью 65 ватт")
    add("tcase_kv", "Чехол KVADRA B001G для планшета", "84253", "Чехлы для планшетов",
        vendor="KVADRA", price=2900, description='Чехол-книжка для планшета 10,9"')

    # 12. Маленькие/составные разделы: Графические планшеты (98055), Проекторы (91916), Наушники (88831), Мыши (82833)
    add("gt_huion", "Графический планшет Huion Inspiroy H640P", "98055", "Графические планшеты", vendor="Huion", price=4500)
    add("gt_bad", "Defender Акустическая 2.0 система SPK-33", "98055", "Графические планшеты", vendor="Defender", price=800)
    add("proj_1", "Проектор INFOCUS LCD IN1024", "91916", "Проекторы", vendor="InFocus", price=49000)
    add("spk_1", "Колонки SVEN SPS-607", "83254", "Колонки", vendor="SVEN", price=3200)
    add("mic_only", "Микрофон Defender Forte", "88831", "Наушники и микрофоны", vendor="Defender", price=900, attrs={"Тип": "Микрофон"})
    add("hs_mic", "Гарнитура Jabra Evolve 20", "88831", "Наушники и микрофоны", vendor="Jabra", price=5400, attrs={"Тип": "Гарнитура"})
    add("ms_wired", "Мышь проводная Logitech B100", "82833", "Клавиатуры, мыши, комплекты",
        vendor="Logitech", price=900, attrs={"Тип устройства": "Мышь", "Интерфейс": "USB 2.0"})
    add("ms_wl", "Мышь беспроводная Logitech M185", "82833", "Клавиатуры, мыши, комплекты",
        vendor="Logitech", price=1600, attrs={"Тип устройства": "Мышь", "Интерфейс": "Радиоканал 2,4 ГГц"})
    add("kb_combo", "Комплект клавиатура+мышь Logitech MK270", "82833", "Клавиатуры, мыши, комплекты",
        vendor="Logitech", price=3100, attrs={"Тип устройства": "Клавиатура+мышь", "Интерфейс": "Радиоканал 2,4 ГГц"})

    # 12b. Карточки Раунда 3: роутеры (гигабит/двухдиапазон), точки доступа (86348), кабели HDMI (80081),
    #      игровой ноутбук (70824), коммутатор 48 портов PoE (85741), серверный HDD (78997), IP-телефония ПО (6035).
    add("rt_gb_db", "Wi-Fi роутер TP-LINK Archer AX55", "85353", "Wi-Fi роутеры",
        vendor="TP-LINK", price=7900, description="LAN 4 × Gigabit Ethernet, Wi-Fi 6",
        attrs={"Особенности": "двухдиапазонный", "Диапазоны частот": "2.4 ГГц; 5.0 ГГц", "Интерфейс LAN": "Gigabit Ethernet"})
    add("ap_1", "Точка доступа TP-LINK EAP650", "86348", "Точки доступа",
        vendor="TP-LINK", price=12500, description="LAN 1 × Gigabit Ethernet, Wi-Fi 6",
        attrs={"Протоколы Wi-Fi": "802.11ax", "Диапазоны частот": "2.4 ГГц; 5.0 ГГц", "Интерфейс LAN": "Gigabit Ethernet"})
    add("ap_2", "Точка доступа Ubiquiti UniFi AC Lite", "86348", "Точки доступа",
        vendor="Ubiquiti", price=11900, description="LAN 1 × Gigabit Ethernet, Wi-Fi 5",
        attrs={"Протоколы Wi-Fi": "802.11ac", "Диапазоны частот": "2.4 ГГц; 5.0 ГГц", "Интерфейс LAN": "Gigabit Ethernet"})
    add("cab_hdmi_2", "Buro BHP HDMI 2", "80081", "Кабели, переходники, разъемы",
        vendor="Buro", price=490, attrs={"Длина кабеля": "200", "Входной интерфейс": "HDMI", "Выходной интерфейс": "HDMI"})
    add("cab_hdmi_5", "Buro BHP HDMI 5", "80081", "Кабели, переходники, разъемы",
        vendor="Buro", price=990, attrs={"Длина кабеля": "500", "Входной интерфейс": "HDMI", "Выходной интерфейс": "HDMI"})
    add("cab_dp_2", "Cablexpert DisplayPort 2м", "80081", "Кабели, переходники, разъемы",
        vendor="Cablexpert", price=750, attrs={"Длина кабеля": "200", "Входной интерфейс": "DisplayPort", "Выходной интерфейс": "DisplayPort"})
    add("lap_gaming", "Ноутбук ASUS G16 G614P AMD Ryzen 9", "70824", "Ноутбуки",
        vendor="ASUS", price=189000, attrs={"Объем установленной ОЗУ": "32", "Серия ноутбука": "ROG Strix G16",
                                            "Видеопроцессор": "NVIDIA GeForce RTX 5070 Ti", "Ёмкость дискретной видеопамяти": "12"})
    add("lap_tuf", "Ноутбук ASUS FA808UM TUF Gaming", "70824", "Ноутбуки",
        vendor="ASUS", price=145000, attrs={"Объем установленной ОЗУ": "16", "Серия ноутбука": "TUF Gaming A18",
                                            "Видеопроцессор": "NVIDIA GeForce RTX 5060", "Ёмкость дискретной видеопамяти": "8"})
    add("sw_48_poe", "Коммутатор MikroTik CRS354-48P-4S", "85741", "Коммутаторы",
        vendor="MikroTik", price=79000, description="Матрица 176 Гбит/с, 4 × 10G port, 48 × Gigabit port",
        attrs={"ПредоставлениеPoE": "PoE (IEEE 802.3af); PoE Plus (IEEE 802.3at)"})
    add("sw_48_nopoe", "Коммутатор TP-LINK TL-SG1048", "85741", "Коммутаторы",
        vendor="TP-LINK", price=31000, description="Матрица 96 Гбит/с, 48 × Gigabit port")
    add("hdd_barracuda", "Жесткий диск SEAGATE Barracuda 4TB", "78997", "Жесткие диски",
        vendor="Seagate", price=9500, attrs={"Ёмкость диска": "4000", "Интерфейс": "SATA3", "Скорость вращения": "5400"})
    add("hdd_usb", "Жесткий диск ADATA HV620S 1TB USB 3.1", "78997", "Жесткие диски",
        vendor="ADATA", price=5500, attrs={"Ёмкость диска": "1000", "Интерфейс": "USB 3.1"})
    add("hdd_exos", "Жесткий диск SEAGATE Exos X16 14TB SAS", "78997", "Жесткие диски",
        vendor="Seagate", price=42000, attrs={"Ёмкость диска": "14000", "Интерфейс": "SAS 12Gb/s", "Скорость вращения": "7200"})
    add("hdd_ultrastar", "Жесткий диск Western Digital Ultrastar DC HC310 6TB", "78997", "Жесткие диски",
        vendor="Western Digital", price=28000, attrs={"Ёмкость диска": "6000", "Интерфейс": "SATA3", "Скорость вращения": "7200"})
    add("sw_pbx", "Brekeke PBX", "6035", "ПО для IP-телефонии",
        root="Программное обеспечение", domain="software", vendor="Brekeke", price=45000)

    # 13. ПО для проверки границы железо/ПО
    add("sw_win_srv", "Microsoft Windows Server 2022 Standard", "369", "Серверное ПО",
        root="Программное обеспечение", domain="software", vendor="Microsoft", price=65000)
    add("sw_backup", "Кибер Бэкап Сервер", "1033", "Резервное копирование",
        root="Программное обеспечение", domain="software", vendor="Киберпротект", price=35000)
    add("sw_av", "Антивирус Kaspersky Endpoint Security", "650", "Антивирусы для организаций",
        root="Программное обеспечение", domain="software", vendor="Лаборатория Касперского", price=3200)

    (data / "catalog.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    engine = Engine.open(replace(cfg, data=data), llm=Disabled())
    yield engine
    engine.close()


def _core(res):
    return [c for c in res["blocks"][0]["items"] if c.get("kind") != "upsell"]


def test_storage_equivalences_and_missing_fallback(n9_engine):
    # 1 ТБ = 1000 ГБ = 1024 ГБ
    r = n9_engine.search(Request(q="ssd 1 тб", mode="fast"))
    core = _core(r)
    assert core[0]["card_id"] in {"ssd_1000", "ssd_1024"}
    assert {c["card_id"] for c in core[:2]} == {"ssd_1000", "ssd_1024"}
    assert r["understood"]["filters"]["specs"] == {"storage_gb": "1 ТБ"}
    assert any(ch["key"] == "spec:storage_gb" and ch["label"] == "Объём · 1 ТБ" and ch["removable"] for ch in r["understood"]["chips"])

    # Голое число при устройстве: ssd 500 → объём ~500/512 ГБ
    r500 = n9_engine.search(Request(q="ssd 500", mode="fast"))
    assert _core(r500)[0]["card_id"] == "ssd_512"
    assert r500["understood"]["filters"]["specs"]["storage_gb"] == "500 ГБ"

    # Отсутствующий объём: ssd 3 тб → честное пояснение, тот же раздел, ближайшие (2 ТБ и 4 ТБ) первыми
    r3 = n9_engine.search(Request(q="ssd 3 тб", mode="fast"))
    core3 = _core(r3)
    assert r3["blocks"][0]["category_id"] == "79574"
    assert {c["card_id"] for c in core3[:2]} == {"ssd_2000", "ssd_4000"}
    assert "3 тб" in r3["understood"]["agent_note"].lower()
    assert "ближайш" in r3["understood"]["agent_note"].lower()


def test_laptop_ram_cpu_series_and_quantity_vs_price(n9_engine):
    # ОЗУ 16 ГБ + процессор i7 (включая Intel Core Ultra 7)
    r = n9_engine.search(Request(q="ноутбук 16 гб i7", mode="fast"))
    core = _core(r)
    assert {c["card_id"] for c in core[:2]} == {"lap_i7_16", "lap_u7_16"}
    assert r["understood"]["filters"]["specs"] == {"cpu": "i7", "ram_gb": "16 ГБ"}

    # Бренд и серия: ноутбук lenovo thinkpad
    rtp = n9_engine.search(Request(q="ноутбук lenovo thinkpad", mode="fast"))
    assert _core(rtp)[0]["card_id"] == "lap_len_tp"
    assert rtp["understood"]["filters"]["specs"].get("series") == "Thinkpad"

    # Цена не путается с параметром
    rprice = n9_engine.search(Request(q="ноутбук до 60000", mode="fast"))
    assert rprice["understood"]["filters"].get("price_max") == 60000
    assert "specs" not in rprice["understood"]["filters"]
    assert all(c["price_from"] <= 60000 for c in _core(rprice))

    # Количество штук (5 шт) не путается с параметром и не даёт предупреждение о лицензии
    rqty = n9_engine.search(Request(q="ноутбук 5 шт", mode="fast"))
    assert rqty["understood"]["qty"] == {"value": 5, "unit": "шт"}
    assert "specs" not in rqty["understood"]["filters"]
    assert "лицензи" not in rqty["understood"]["agent_note"].lower()
    assert any(ch["key"] == "quantity" and "5" in ch["label"] for ch in rqty["understood"]["chips"])


def test_monitor_diagonal_resolution_vendor_and_removable_chips(n9_engine):
    # 27" 4K: берёт точное 3840 × 2160 из description, игнорируя неверный attr FullHD
    r = n9_engine.search(Request(q="монитор 27 дюймов 4k", mode="fast"))
    assert _core(r)[0]["card_id"] == "mon_27_4k"
    assert r["understood"]["filters"]["specs"] == {"resolution": "4K", "diagonal": "27″"}

    # Голое число и кавычка дюймов
    r27 = n9_engine.search(Request(q='монитор 27"', mode="fast"))
    assert _core(r27)[0]["card_id"] in {"mon_27_fhd", "mon_27_4k", "mon_27_sam"}
    r27b = n9_engine.search(Request(q="монитор 27", mode="fast"))
    assert r27b["understood"]["filters"]["specs"] == {"diagonal": "27″"}

    # Вендор + диагональ: монитор samsung 27
    rsam = n9_engine.search(Request(q="монитор samsung 27", mode="fast"))
    assert _core(rsam)[0]["card_id"] == "mon_27_sam"

    # Снятие чипа через ignore
    r_ign = n9_engine.search(Request(q="монитор 27 дюймов 4k", mode="fast", ignore=["spec:resolution"]))
    assert r_ign["understood"]["filters"]["specs"] == {"diagonal": "27″"}
    r_ign_all = n9_engine.search(Request(q="монитор 27 дюймов 4k", mode="fast", ignore=["specs"]))
    assert "specs" not in r_ign_all["understood"]["filters"]


def test_ram_flash_router_switch_printer_psu_ups_gpu(n9_engine):
    # DDR5 32GB (включая комплект 2x16GB) — даже без слов «оперативная память»
    rram = n9_engine.search(Request(q="ddr5 32gb", mode="fast"))
    assert _core(rram)[0]["card_id"] == "ram_ddr5_32kit"
    assert rram["understood"]["filters"]["specs"] == {"ram_type": "DDR5", "ram_gb": "32 ГБ"}

    # Флешка 64 гб
    rusb = n9_engine.search(Request(q="флешка 64 гб", mode="fast"))
    assert _core(rusb)[0]["card_id"] == "usb_64"

    # Роутер Wi-Fi 6
    rrt = n9_engine.search(Request(q="роутер wi-fi 6", mode="fast"))
    assert _core(rrt)[0]["card_id"] == "rt_ax"

    # Коммутатор 24 порта и отсутствующий вендор Cisco
    rsw = n9_engine.search(Request(q="коммутатор cisco 24 порта", mode="fast"))
    assert rsw["blocks"][0]["category_id"] == "85741"
    assert _core(rsw)[0]["card_id"] in {"sw_24", "sw_24_poe"}
    assert "cisco" in rsw["understood"]["agent_note"].lower()

    # МФУ лазерное цветное и принтер A3
    rmfp = n9_engine.search(Request(q="мфу лазерное цветное", mode="fast"))
    assert _core(rmfp)[0]["card_id"] == "mfp_col"
    ra3 = n9_engine.search(Request(q="принтер a3", mode="fast"))
    assert _core(ra3)[0]["card_id"] == "prn_a3"

    # БП 650 Вт, ИБП 1000 ВА, Видеокарта RTX 8 ГБ (греческая гамма ГБ)
    assert _core(n9_engine.search(Request(q="блок питания 650 вт", mode="fast")))[0]["card_id"] == "psu_650"
    assert _core(n9_engine.search(Request(q="ибп 1000 ва", mode="fast")))[0]["card_id"] == "ups_1000"
    assert _core(n9_engine.search(Request(q="видеокарта rtx 8 гб", mode="fast")))[0]["card_id"] == "gpu_rtx"


def test_hardware_vendor_gap_keeps_section(n9_engine):
    # Dell есть в HDD, но нет в Rack-серверах — остаёмся в серверах с честным пояснением!
    r = n9_engine.search(Request(q="сервер dell", mode="fast"))
    core = _core(r)
    assert r["blocks"][0]["category_id"] == "86563"
    assert all(c["card_id"] in {"srv_depo", "srv_nerpa"} for c in core)
    assert "dell" in r["understood"]["agent_note"].lower()


def test_consumables_and_compatibility(n9_engine):
    # Картридж для HP LaserJet — расходники, совместимый картридж первым, НЕ принтер HP!
    r1 = n9_engine.search(Request(q="картридж для hp laserjet", mode="fast"))
    assert r1["blocks"][0]["category_id"] == "94694"
    assert _core(r1)[0]["card_id"] == "cons_hp_lj"
    assert "HP" in r1["understood"]["filters"]["specs"]["compat"]

    # Тонер для Kyocera
    r2 = n9_engine.search(Request(q="тонер для kyocera", mode="fast"))
    assert _core(r2)[0]["card_id"] == "cons_kyo"

    # Блок питания для ноутбука Asus — раздел источников питания для ноутбуков, универсальные адаптеры + честная заметка
    r3 = n9_engine.search(Request(q="блок питания для ноутбука asus", mode="fast"))
    assert r3["blocks"][0]["category_id"] == "84326"
    assert _core(r3)[0]["card_id"] == "lpsu_65"
    assert "asus" in r3["understood"]["agent_note"].lower()

    # Чехол для iPad — раздел чехлов для планшетов (cond.platform не ломает выдачу), честная заметка
    r4 = n9_engine.search(Request(q="чехол для ipad", mode="fast"))
    assert r4["blocks"][0]["category_id"] == "84253"
    assert _core(r4)[0]["card_id"] == "tcase_kv"
    assert "ipad" in r4["understood"]["agent_note"].lower()
    assert "platform" not in r4["understood"]["filters"]


def test_small_sections_subtypes_and_software_guard(n9_engine):
    # Графический планшет: ошибочно попавшая акустика удалена, чужой раздел не подмешан
    rgt = n9_engine.search(Request(q="графический планшет", mode="fast"))
    assert [c["card_id"] for c in _core(rgt)] == ["gt_huion"]

    # Проектор: чужие колонки не подмешаны через fill
    rpr = n9_engine.search(Request(q="проектор", mode="fast"))
    assert [c["card_id"] for c in _core(rpr)] == ["proj_1"]

    # Наушники с микрофоном → гарнитура первой
    rhs = n9_engine.search(Request(q="наушники с микрофоном", mode="fast"))
    assert _core(rhs)[0]["card_id"] == "hs_mic"

    # Мышь беспроводная Logitech → беспроводная мышь первой (выше проводной и комплекта)
    rms = n9_engine.search(Request(q="мышь беспроводная logitech", mode="fast"))
    assert _core(rms)[0]["card_id"] == "ms_wl"

    # Запросы про ПО не перехватываются модулем железа
    for sq in ("windows server", "резервное копирование сервера", "антивирус для ноутбука", "по для сервера", "сканер уязвимостей"):
        assert n9_engine.catalog.feed.hardware_specs.parse_query(sq, sq, sq) is None
    for sq in ("windows server", "антивирус для ноутбука"):
        rs = n9_engine.search(Request(q=sq, mode="fast"))
        assert _core(rs)[0]["domain"] == "software"


def test_r3_routers_variants(n9_engine):
    # Пункт 1: все формулировки роутеров/маршрутизаторов ведут в раздел роутеров, не в пустой clarify
    for q in (
        "wi-fi роутер для офиса",
        "wifi маршрутизатор гигабитный",
        "роутер двухдиапазонный",
        "сетевой роутер",
        "вай-фай роутер",
        "router",
    ):
        r = n9_engine.search(Request(q=q, mode="fast"))
        assert r["blocks"][0]["type"] == "products"
        assert r["blocks"][0]["category_id"] == "85353"
        assert len(_core(r)) >= 2
    rgb = n9_engine.search(Request(q="wifi маршрутизатор гигабитный", mode="fast"))
    assert _core(rgb)[0]["card_id"] == "rt_gb_db"
    assert rgb["understood"]["filters"]["specs"].get("gigabit") == "Гигабитный"
    rdb = n9_engine.search(Request(q="роутер двухдиапазонный", mode="fast"))
    assert _core(rdb)[0]["card_id"] == "rt_gb_db"
    assert rdb["understood"]["filters"]["specs"].get("dual_band") == "Двухдиапазонный"


def test_r3_cable_hdmi_length(n9_engine):
    # Пункт 2: кабель HDMI 2 м — раздел кабелей, точный 2м HDMI первым + чипы интерфейса и длины
    r = n9_engine.search(Request(q="кабель hdmi 2 м", mode="fast"))
    assert r["blocks"][0]["category_id"] == "80081"
    assert _core(r)[0]["card_id"] == "cab_hdmi_2"
    assert r["understood"]["filters"]["specs"] == {"interface": "HDMI", "cable_length_m": "2 м"}
    labels = [ch["label"] for ch in r["understood"]["chips"]]
    assert "Интерфейс · HDMI" in labels and "Длина · 2 м" in labels

    # Отсутствующая длина (10 м): остаётся в разделе кабелей, ближайший HDMI (5 м) первым + честная заметка
    r10 = n9_engine.search(Request(q="кабель hdmi 10 м", mode="fast"))
    assert r10["blocks"][0]["category_id"] == "80081"
    assert _core(r10)[0]["card_id"] == "cab_hdmi_5"
    assert "10 м" in r10["understood"]["agent_note"].lower()


def test_r3_gaming_laptop(n9_engine):
    # Пункт 3: игровой ноутбук — игровые с RTX / ROG / TUF первыми выше офисных
    r = n9_engine.search(Request(q="игровой ноутбук", mode="fast"))
    assert r["blocks"][0]["category_id"] == "70824"
    core = _core(r)
    assert {c["card_id"] for c in core[:2]} == {"lap_gaming", "lap_tuf"}
    assert r["understood"]["filters"]["specs"] == {"gaming": "Игровой"}


def test_r3_headset_for_call_center(n9_engine):
    # Пункт 4: гарнитура для колл-центра — гарнитуры из 88831, не ПО IP-телефонии
    r = n9_engine.search(Request(q="гарнитура для колл-центра", mode="fast"))
    assert r["blocks"][0]["category_id"] == "88831"
    assert _core(r)[0]["card_id"] == "hs_mic"


def test_r3_switch_48_ports_poe(n9_engine):
    # Пункт 5: коммутатор 48 портов poe — модель с 48 портами и PoE первой
    r = n9_engine.search(Request(q="коммутатор 48 портов poe", mode="fast"))
    assert r["blocks"][0]["category_id"] == "85741"
    assert _core(r)[0]["card_id"] == "sw_48_poe"
    assert r["understood"]["filters"]["specs"] == {"ports": "48", "poe": "PoE"}


def test_r3_server_hdd(n9_engine):
    # Пункт 6: жесткий диск для сервера — серверные Exos/Ultrastar/SAS первыми, не Barracuda/USB и не «Класс ПО»
    r = n9_engine.search(Request(q="жесткий диск для сервера", mode="fast"))
    assert r["blocks"][0]["category_id"] == "78997"
    core = _core(r)
    assert {c["card_id"] for c in core[:3]} == {"hdd_dell_4tb", "hdd_exos", "hdd_ultrastar"}
    assert "класс по" not in r["understood"]["agent_note"].lower()
    assert r["understood"]["filters"]["specs"] == {"server_grade": "Серверный"}


def test_r3_access_points_unified_section(n9_engine):
    # Пункт 7: все формулировки точек доступа ведут в один аппаратный раздел 86348 (не auto_sl_86348) и работают со спеками
    for q in ("точка доступа wifi", "точка доступа", "access point", "wi-fi точка"):
        r = n9_engine.search(Request(q=q, mode="fast"))
        assert r["blocks"][0]["type"] == "products"
        assert r["blocks"][0]["category_id"] == "86348"
        assert r["understood"]["filters"].get("category") == ["86348"]
        assert {c["card_id"] for c in _core(r)} == {"ap_1", "ap_2"}
    for q in ("точка доступа wi-fi 6", "access point wi-fi 6"):
        r6 = n9_engine.search(Request(q=q, mode="fast"))
        assert r6["blocks"][0]["category_id"] == "86348"
        assert _core(r6)[0]["card_id"] == "ap_1"
        assert r6["understood"]["filters"]["specs"] == {"wifi": "Wi-Fi 6"}
