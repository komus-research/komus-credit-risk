# CURRENT STATE — AXION

## Назначение

Это компактный актуальный snapshot, а не историческая летопись. Канонический ответ на вопросы «где проект сейчас / что дальше» находится в корневом [`PROJECT_MAP.md`](../PROJECT_MAP.md). Полная предыдущая версия сохранена в [`history/CURRENT_STATE_FULL_2026-10-01.md`](history/CURRENT_STATE_FULL_2026-10-01.md).

## Canonical product path

React + TypeScript + Vite → FastAPI → application/core.

Streamlit — frozen compatibility frontend. Новые продуктовые UI этапы не реализуются там без отдельного решения.

## Текущая точка

Native AXION подтверждён через Quality → OOF run → persisted `ExperimentArtifact` → Result Overview → Threshold Explorer → Objects → Object Detail → Local Explanation/SHAP. Local Explanation/SHAP принят. На реальном XGBoost artifact `362 018 × 49`, 3 OOF folds обнаружен отдельный blocker Global OOF Explanation: `GET /api/v1/result/explanation/global` после долгого расчёта возвращает `409`, при этом основной Result остаётся доступен. Полный replay persisted fold models совпал с OOF scores с max absolute difference `0.0` во всех трёх folds, поэтому ослабление `1e-12` tolerance не требуется. Подтверждён scalability bottleneck текущего generic XGBoost path: `explain_batch()` фактически вызывает one-row Local SHAP для каждой OOF-строки. Architect готовит `GLOBAL OOF EXPLANATION RELIABILITY / PERFORMANCE V1`; после его brief — отдельная Codex implementation-задача.

Подробные статусы, границы и evidence — в корневом [`PROJECT_MAP.md`](../PROJECT_MAP.md).

Cross-screen visual locks приняты: Button System V2 (`docs/design/components/buttons/02_button_system_v2.png`), Data Warnings V2 (`docs/design/components/data-warnings/01_data_warnings_v2.png`), Sidebar Final V1 (`docs/design/components/sidebar/01_sidebar_final_v1.png`) и Long Operations V1 (`docs/design/components/long-operations/01_long_operations_v1.png`). Button System V2 supersedes V1 по visual treatment и применяется ко всем экранам и confirmation/native modal; Home application reference — `docs/design/screens/home/02_home_button_system_v2.png`. Confirmation V2 (`docs/design/screens/new-analysis/02_data_confirmation_v2.png`) и Quality V2 (`docs/design/screens/new-analysis/05_quality_v2.png`) являются основными screen refs. В Sidebar sheet fake profile/auth card явно исключена из contract; navigation IA остаётся `Главная / Новый анализ / Модели / История / Настройки`. Runtime ещё не считается полностью приведённым к этим locks.

## Следующий этап

Canonical native artifact ownership уже зафиксирован: один `ExperimentArtifactStore` в `<repository root>/.axion-artifacts`; `.streamlit-artifacts` остаётся compatibility-only storage.

**IMMEDIATE NEXT:** закрыть blocker **Global OOF Explanation Reliability / Performance V1** без изменения scientific semantics `mean(abs(local OOF SHAP))` по всей OOF population. Сейчас Architect формирует implementation-ready brief; после его ACCEPT — узкая Codex implementation-задача и Reviewer.

После blocker-fix продолжается отложенный Result Interpreter track: **RI-BE → RI-UI → RI-EXPORT** по [`RESULT_INTERPRETER_V2_LOCK.md`](workstreams/generic_dataset_onboarding_v1/RESULT_INTERPRETER_V2_LOCK.md).

## Уже существующие reusable части

- `ExperimentApplicationService` и путь полного эксперимента;
- `ExperimentArtifact` V3 и проверяемая persistence-семантика;
- `OOFResultService`, `OOFExplanationService`, Local OOF SHAP; Global OOF scientific semantics приняты, но текущий large-XGBoost execution path требует reliability/performance corrective;
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