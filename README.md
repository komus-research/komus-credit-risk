# Komus Credit Risk

KOMUS Credit Risk — исследовательский прототип для воспроизводимых ML-экспериментов по прогнозированию дефолта организаций.

Текущий пользовательский flow: Данные → Признаки → Модель → Эксперимент → Результат.

Frontend: Streamlit.

## Быстрый запуск

Требования:

- Git;
- uv;
- Windows и локальный запуск;
- версия Python берётся из проекта: [`.python-version`](.python-version).

```powershell
git clone https://github.com/komus-research/komus-credit-risk.git
cd komus-credit-risk
uv sync
uv run python -m streamlit run app/streamlit_app.py
```

Репозиторий: [github.com/komus-research/komus-credit-risk](https://github.com/komus-research/komus-credit-risk).

## Датасет

`Data_final.xlsb` не хранится в Git. Для полного historical flow нужен локальный accepted `Data_final.xlsb`.

Есть два способа указать файл:

- положить его по пути `data/raw/Data_final.xlsb`;
- запустить приложение, выбрать «Другой локальный файл» и выбрать `Data_final` с диска.

Другой локальный файл можно выбрать и проверить, но пока только accepted historical `Data_final` имеет готовые Dataset Contract и Evaluation Population и допускается к experiment flow.

## Что можно попробовать

- выбрать источник данных;
- включать и выключать группы и отдельные признаки;
- выбрать CatBoost, XGBoost, LightGBM или `GBDT_mean`;
- настроить experiment config;
- посмотреть plan перед запуском;
- запустить 3-fold OOF experiment;
- посмотреть и сравнить сохранённый результат;
- свободно переходить между уже достигнутыми этапами.

## Текущие ограничения

- arbitrary dataset onboarding ещё не реализован;
- новый dataset требует собственного Dataset Contract, Feature Registry и Evaluation Population;
- `Q_B1_norm` и `Q_B2_norm` не являются predictors;
- final test не используется для выбора модели;
- LLM Result Interpreter не является credit predictor;
- пользовательское LLM-объяснение в текущий Streamlit flow ещё не подключено как готовая функция.

## Текущий статус

- core model research Stage 1–20 закрыт и зафиксирован согласно текущим project docs;
- текущая разработка — reproducible experiment pipeline и пользовательский prototype;
- следующий product direction: new dataset preparation / feature onboarding, model onboarding и result interpretation.

## Главная цель

Не просто получить высокий Gini, а построить воспроизводимую исследовательскую систему, которая позволяет:

- честно сравнивать модели на одинаковом протоколе;
- включать, отключать и группировать признаки;
- исследовать новые факторы и современные CPU-подходы;
- измерять Gini, ROC-AUC, PR-AUC, Precision, Recall, F1 и структуру ошибок;
- учитывать CPU runtime, ресурсы и размер модели;
- объяснять глобальные и локальные предсказания;
- настраивать порог и бизнес-сценарий стоимости FN/FP;
- учитывать ограничение на объём ручной проверки;
- сохранять воспроизводимые артефакты экспериментов;
- сохранять presentation-ready историю каждого исследовательского этапа;
- постепенно превратиться в backend и затем в исследовательский frontend без дублирования ML-логики.

## Документация

Актуальная документация проекта хранится в `docs/`:

- [`PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md) — текущая точка проекта, baseline, источники и ограничения;
- [`PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) — что должен уметь исследовательский продукт;
- [`BUSINESS_RULES.md`](docs/BUSINESS_RULES.md) — подтверждённые требования и ограничения заказчика;
- [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) — границы модулей и направление развития системы;
- [`ROADMAP.md`](docs/ROADMAP.md) — этапы работы и критерии завершения;
- [`DECISIONS.md`](docs/DECISIONS.md) — журнал существенных продуктовых, исследовательских и архитектурных решений;
- [`RESEARCH_RECORD.md`](docs/RESEARCH_RECORD.md) — единое правило хранения доказательств каждого Stage и подготовки материалов для будущего отчёта/презентации.

## Research evidence

Каталог `reports/` является частью source of truth исследования:

- `reports/summary/` — компактные проверяемые summaries;
- `reports/generated/` — machine-readable результаты, diagnostics и checkpoints, необходимые для воспроизводимости или следующего Stage;
- `reports/figures/` — отдельные графики и визуальные таблицы для анализа, отчёта и презентации;
- `reports/presentation/` — итоговый curated-набор материалов непосредственно для защиты.

Эти каталоги разрешено хранить в Git и они не должны целиком исключаться через `.gitignore`.

## Правило работы

Один исследовательский вопрос → один контролируемый эксперимент → измерение → вывод.

Рабочий baseline не переписывается без причины. Final test не используется для выбора модели, признаков, гиперпараметров или порога. Любой важный результат должен быть воспроизводим по данным, конфигурации, seed/split и сохранённым метаданным.

После значимого Stage должны остаться notebook, machine-readable summary, необходимые generated artifacts, ключевые figure-файлы, ограничения, решение и следующий исследовательский вопрос. Это позволяет в конце собрать отчёт и презентацию из проверенных источников, а не восстанавливать историю по памяти или старым чатам.

## Данные и Git

Raw dataset `Data_final.xlsb`, другие тяжёлые табличные файлы, секреты, локальное окружение, caches/logs и тяжёлые model checkpoints остаются вне обычного Git.

Это не означает blanket-запрет на исследовательские результаты: проверенные таблицы, diagnostics, OOF/checkpoints разумного размера и графики должны храниться в репозитории, когда они нужны для воспроизводимости или будущей защиты.

Если позже в проекте появляются действительно чувствительные данные, отдельное правило для них сначала явно добавляется в `.gitignore` и документацию.
