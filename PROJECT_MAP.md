# Карта проекта AXION

Актуально для `main`, HEAD `3e64d4d21e8dce69da451a917837b1f2c18025dc`.

## Канонический путь

```text
React + TypeScript + Vite → FastAPI → application/core
```

Streamlit — frozen compatibility frontend. Он не задаёт готовность основного продукта и не является рекомендуемым запуском.

## Состояние delivery

| Область | Статус | Подтверждённый результат |
|---|---|---|
| Home и начало анализа | ГОТОВО | Native React Home и переход в новый анализ. |
| Данные | ГОТОВО | Загрузка, inspection, роли колонок, подтверждение и подготовленный контекст. |
| Признаки и алгоритм | ГОТОВО | Выбор признаков, модели и поддерживаемой конфигурации. |
| Quality / OOF experiment | ГОТОВО | Preflight, полный OOF run, прогресс и сохранённый `ExperimentArtifact`. |
| Result | ГОТОВО | Overview, threshold exploration, Objects, Object Detail и Local SHAP. |
| Global OOF explanation | ЧАСТИЧНО | Отдельная native операция с запуском, статусом, retry и выдачей только готового evidence; результат доступен только после успешного расчёта совместимого OOF evidence. |
| Result Interpreter | ГОТОВО | Native API/UI для четырёх ролей; LLM — только интерпретатор подготовленных фактов результата. |
| Model Library и saved inference | ГОТОВО | `ModelVersion`, библиотека, переименование, preflight и inference на новых данных. |
| Analyst Report | ГОТОВО | Draft, immutable report, Preview, PDF и DOCX. |
| Project Workspace | ГОТОВО | Создание и открытие рабочего пространства для inference result. |
| History | ГОТОВО | Native React каталог завершённых анализов и открытие сохранённого результата. |
| Settings V1 | ГОТОВО | Предпочтения Result Interpreter и безопасное управление credential/connection check. |

## Текущий NEXT перед сдачей

Delivery verification и presentation evidence: проверить Windows launcher, пройти ключевой пользовательский путь на доступных данных, собрать демонстрационные материалы и зафиксировать результаты проверки. Новый крупный product workstream не открывается без подтверждённого blocker.

## Архитектурные и исследовательские границы

- Application-owned версионированные артефакты хранятся локально в `.axion-artifacts`; production DB не нужна, пока не появится подтверждённая необходимость.
- `ExperimentArtifact` и `ModelVersion` — разные сущности с разными жизненными циклами.
- `Q_B1_norm` и `Q_B2_norm` — diagnostic/reference, а не рабочие predictors.
- Random CV/OOF не является доказательством temporal stability.
- LLM не предсказывает дефолт, не принимает кредитное решение и не делает SHAP причинным объяснением.
- Streamlit и `.streamlit-artifacts` — compatibility-only и не смешиваются с native product path.
