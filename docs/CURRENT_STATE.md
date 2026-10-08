# CURRENT STATE — AXION

Это компактный актуальный snapshot. Исторические детали и research stages остаются в `ROADMAP.md`; они не переопределяют текущую delivery-точку.

## Canonical product path

React + TypeScript + Vite → FastAPI → application/core. Streamlit — frozen compatibility frontend.

## Готовые пользовательские потоки

В native path доступны: Home; загрузка и подготовка датасета; выбор признаков и алгоритма; Quality/preflight; полный OOF experiment; Result и исследование порога; Objects/Object Detail; Local SHAP; сохранение `ModelVersion`; Model Library; saved-model inference и его Result; Result Interpreter с четырьмя ролями; Report Draft и immutable Analyst Report с Preview/PDF/DOCX; Project Workspace; History; Settings V1.

Global OOF explanation реализован отдельной операцией: UI запускает расчёт, показывает его статус и читает только успешно сформированное совместимое OOF evidence. Его нельзя считать доступным для конкретного результата до успешного завершения операции.

## Хранилище и границы

`ExperimentArtifact` и `ModelVersion` сохраняются как application-managed local artifacts в `.axion-artifacts`. Production database пока не требуется. Streamlit storage остаётся compatibility-only.

Result Interpreter использует LLM только для объяснения уже рассчитанного результата. Он не является предиктором и не принимает кредитное решение. Local SHAP описывает вклад признаков в модельный результат, а не причинность.

## Исследовательские ограничения

- Random CV/OOF не доказывает temporal stability.
- `Q_B1_norm` и `Q_B2_norm` исключены из рабочих predictors.
- Final test не используется для выбора модели, признаков или threshold.
- `Data_final.xlsb` не хранится в Git; данные загружаются пользователем через UI.

## Delivery NEXT

Перед сдачей приоритетны verification, presentation и evidence: проверить launcher, критический пользовательский путь и демонстрационные материалы. Открывать новый крупный product workstream следует только при подтверждённом blocker.
