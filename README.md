# Кузница Softline

Поиск по каталогу лицензий для организаций. Демонстрационный проект AiXenix. Для сборки M1 требуются Python 3.12, библиотеки из `requirements.txt` и локальный кэш MiniLM в `var/models`.

```bash
.venv/bin/python -m kuznitsa.cli kb-check
.venv/bin/python -m kuznitsa.cli build-mock
.venv/bin/python -m kuznitsa.cli build-index
.venv/bin/python -m kuznitsa.cli search "каспер продление на 30 компов" --profile smb_trade --mode fast --explain
.venv/bin/python -m pytest -q
```

После обновления базы знаний повторите сборку каталога и индексов. Уже открытый экземпляр движка использует свой снимок данных. Переменные `KZ_KB_DIR`, `KZ_DATA_DIR`, `KZ_CACHE_DIR` и `KZ_MODEL_DIR` задают пути. Значение `KZ_EMBED_MODEL=off` включает полностью лексический режим. Оба режима витрины в M1 используют локальный поиск.

Для интеграции приложение доступно как `kuznitsa.app:app`. Фабрика `create_app(engine)` принимает готовый движок для проверки через TestClient. SQLite находится в каталоге данных, отдельно от каталога лицензий и клиентов. Сборка mock обновляет JSONL и сохраняет историю поисков.

Подробности реализации, проверочные ответы и ограничения приведены в [отчёте M1](design/proposals/astra/REPORT-M1.md).
