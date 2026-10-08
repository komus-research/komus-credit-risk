# AXION

AXION — исследовательско-прикладной прототип кредитного риск-анализа организаций с production-like архитектурными границами. Он помогает подготовить табличный датасет, провести воспроизводимый OOF-эксперимент, исследовать результат и оформить аналитический отчёт. Это не production-система и не инструмент автоматического кредитного решения.

Канонический путь продукта:

```text
React + TypeScript + Vite → FastAPI → application/core ML services
```

Streamlit остаётся legacy/frozen compatibility frontend и не является основным путём работы с продуктом.

## Быстрый запуск Windows

Требуются Windows, Git, Python с `uv`, а также Node.js с `npm`.

После clone выполните один раз:

```powershell
git clone https://github.com/komus-research/komus-credit-risk.git
cd komus-credit-risk
uv sync
npm install --prefix frontend
```

Основной запуск:

```powershell
START_AXION.cmd
```

или из PowerShell:

```powershell
.\START_AXION.cmd
```

Launcher поднимает backend на `127.0.0.1:8000` и frontend на `127.0.0.1:5173`, затем открывает браузер по адресу <http://127.0.0.1:5173/#/home>.

Остановка:

```powershell
STOP_AXION.cmd
```

или:

```powershell
.\STOP_AXION.cmd
```

### Если запуск не состоялся

- Не найден `uv` — установите `uv` и повторите запуск.
- Не найден `npm` — установите Node.js и повторите запуск.
- Не установлены зависимости frontend — выполните `npm install --prefix frontend`.
- Не установлены зависимости backend — выполните `uv sync`.
- Если занят порт `8000` или `5173`, launcher завершится с сообщением, не запуская AXION поверх другого процесса.
- Логи запуска: `.axion-run/backend.log` и `.axion-run/frontend.log`.

## Что умеет AXION сейчас

Пользовательский путь начинается на Home и ведёт через следующие рабочие возможности:

- загрузка и подготовка CSV, XLSX, XLSB или Parquet-датасета, назначение ролей колонок и подтверждение контекста;
- выбор признаков, алгоритма и поддерживаемых настроек;
- технический preflight и запуск полного OOF-эксперимента;
- Result: метрики, исследование порога, список объектов и карточка объекта;
- Local SHAP для отдельного объекта; Global OOF explanation запускается как отдельная операция и отображается после успешного формирования evidence;
- сохранение результата как `ModelVersion`, библиотека моделей и применение сохранённой модели к новым данным;
- Saved Model Inference result, просмотр объектов и локальное объяснение для нового прогноза;
- Result Interpreter для четырёх ролей: кредитный контролёр, менеджер по продажам, юрист и специалист по информационной безопасности;
- черновик отчёта и immutable Analyst Report с Preview, PDF и DOCX;
- Project Workspace для продолжения работы с результатом, History завершённых анализов и Settings V1.

LLM используется только в Result Interpreter: он получает подготовленные факты результата и не является предиктором или автоматическим принимающим решение компонентом. SHAP показывает вклад признаков в конкретное предсказание, но не доказывает причинность.

## Данные и локальные артефакты

Raw `Data_final.xlsb` не хранится в Git. Данные можно загрузить через UI. Репозиторий не содержит secrets.

`.axion-artifacts` — application-managed локальное хранилище версионированных артефактов. Локальные runtime-артефакты и логи не являются source-controlled исследовательским evidence. Проверяемые research evidence, когда они нужны для воспроизводимости, хранятся отдельно в `reports/`.

## Ограничения исследования

- `Q_B1_norm` и `Q_B2_norm` исключены из рабочих predictors и используются только как diagnostic/reference.
- Random CV/OOF не доказывает temporal stability.
- Final test не используется для выбора модели, признаков или порога.
- В репозитории нет production database, облачного deployment, fake auth/users/profile или автоматизированного кредитного решения.

## Документация

- [PROJECT_MAP.md](PROJECT_MAP.md) — краткая карта готовности и delivery NEXT.
- [CURRENT_STATE.md](docs/CURRENT_STATE.md) — компактный актуальный snapshot.
- [PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) — продуктовые границы и инварианты.
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — архитектурные границы.
- [ROADMAP.md](docs/ROADMAP.md) — исследовательская история и roadmap.
