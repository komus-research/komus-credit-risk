# CURRENT STATE — AXION

## Назначение

Это компактный актуальный snapshot, а не историческая летопись. Канонический ответ на вопросы «где проект сейчас / что дальше» находится в [`PROJECT_MAP.md`](PROJECT_MAP.md). Полная предыдущая версия сохранена в [`history/CURRENT_STATE_FULL_2026-10-01.md`](history/CURRENT_STATE_FULL_2026-10-01.md).

## Canonical product path

React + TypeScript + Vite → FastAPI → application/core.

Streamlit — frozen compatibility frontend. Новые продуктовые UI этапы не реализуются там без отдельного решения.

## Текущая точка

Native AXION подтверждён через Quality → OOF run → persisted `ExperimentArtifact` → Result Overview → Threshold Explorer → Objects → Object Detail → Local Explanation/SHAP. SHAP закрыт и принят. Result Interpreter V2 UX/architecture lock принят, но native FastAPI/React integration ещё не реализована. History и Models реализованы частично; Settings UI/backend ещё не реализованы.

Подробные статусы, границы и evidence — в [`PROJECT_MAP.md`](PROJECT_MAP.md).

## Следующий этап

Canonical native artifact ownership уже зафиксирован: один `ExperimentArtifactStore` в `<repository root>/.axion-artifacts`; `.streamlit-artifacts` остаётся compatibility-only storage.

**NEXT:** RI-BE → RI-UI → RI-EXPORT. Текущий шаг — **RI-BE**, role-specific FastAPI contract поверх trusted Local SHAP и существующего `IntegrationWorkflowService`. Canonical lock: [`RESULT_INTERPRETER_V2_LOCK.md`](workstreams/generic_dataset_onboarding_v1/RESULT_INTERPRETER_V2_LOCK.md).

## Уже существующие reusable части

- `ExperimentApplicationService` и путь полного эксперимента;
- `ExperimentArtifact` V3 и проверяемая persistence-семантика;
- `OOFResultService`, `OOFExplanationService`, Global OOF SHAP;
- Result Interpreter core/runtime: 4 роли, `ResultInterpreterResponse`, `REDACTED_V1`, provider/runtime capability и `IntegrationWorkflowService`;
- `AnalysisHistoryService`;
- принятые native Home / Data / Features / Algorithm / Quality preflight / full training / Result Overview / Threshold Explorer / Objects / Object Detail / Local SHAP.

Новый React UI использует существующие application/core контракты через FastAPI, а не создаёт второй ML pipeline.

## Stable research invariants

- Target: `DefMark`; identifier: `INN`.
- `Q_B1_norm` и `Q_B2_norm` — только diagnostic/reference, не predictors рабочей модели.
- Final test — только финальная проверка; он не используется для выбора модели, признаков, threshold или направления исследования.
- Random CV/OOF не доказывает temporal stability.
- LLM используется только как Result Interpreter, не как credit predictor.

## Правила чтения контекста

Сначала `PROJECT_MAP.md`, затем этот snapshot, потом только документ или код, относящийся к текущей задаче. В больших документах искать точечно и читать небольшой нужный диапазон. Историю читать только при конкретной необходимости: старый `NEXT` не определяет текущий. Не восстанавливать актуальное состояние по истории чатов или памяти, если доступны эти документы и repository evidence.