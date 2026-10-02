# CURRENT STATE — AXION

## Назначение

Это компактный актуальный snapshot, а не историческая летопись. Канонический ответ на вопросы «где проект сейчас / что дальше» находится в [`PROJECT_MAP.md`](PROJECT_MAP.md). Полная предыдущая версия сохранена в [`history/CURRENT_STATE_FULL_2026-10-01.md`](history/CURRENT_STATE_FULL_2026-10-01.md).

## Canonical product path

React + TypeScript + Vite → FastAPI → application/core.

Streamlit — frozen compatibility frontend. Новые продуктовые UI этапы не реализуются там без отдельного решения.

## Текущая точка

Native AXION подтверждён через полный путь Quality → OOF run → persisted `ExperimentArtifact` → React Result Overview → Threshold Explorer → Objects. Главная, Данные, Признаки, Алгоритм, Quality preflight, полное обучение, обзор результата, исследование порога и список OOF-объектов готовы. Native Result дальше Objects, History и Models реализованы частично; Settings UI и backend ещё не реализованы. Product / Architecture / Visual Lock для Settings принят.

Подробные статусы, границы и evidence — в [`PROJECT_MAP.md`](PROJECT_MAP.md).

## Следующий этап

Canonical native artifact ownership уже зафиксирован: один `ExperimentArtifactStore` в `<repository root>/.axion-artifacts`; `.streamlit-artifacts` остаётся compatibility-only storage.

**NEXT:** native Object Detail через `OOFResultService.object_detail()` → затем Local Explanation/SHAP.

## Уже существующие reusable части

- `ExperimentApplicationService` и путь полного эксперимента;
- `ExperimentArtifact` V3 и проверяемая persistence-семантика;
- `OOFResultService`, `OOFExplanationService`, Global OOF SHAP;
- Result Interpreter — интерпретатор результата;
- `AnalysisHistoryService`;
- принятые native Home / Data / Features / Algorithm / Quality preflight / full training / Result Overview / Threshold Explorer / Objects.

Новый React UI использует существующие application/core контракты через FastAPI, а не создаёт второй ML pipeline.

## Stable research invariants

- Target: `DefMark`; identifier: `INN`.
- `Q_B1_norm` и `Q_B2_norm` — только diagnostic/reference, не predictors рабочей модели.
- Final test — только финальная проверка; он не используется для выбора модели, признаков, threshold или направления исследования.
- Random CV/OOF не доказывает temporal stability.
- LLM используется только как Result Interpreter, не как credit predictor.

## Правила чтения контекста

Сначала `PROJECT_MAP.md`, затем этот snapshot, потом только документ или код, относящийся к текущей задаче. В больших документах искать точечно и читать небольшой нужный диапазон. Историю читать только при конкретной необходимости: старый `NEXT` не определяет текущий. Не восстанавливать актуальное состояние по истории чатов или памяти, если доступны эти документы и repository evidence.