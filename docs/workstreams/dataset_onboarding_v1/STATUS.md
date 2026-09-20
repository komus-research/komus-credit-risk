# Dataset Onboarding V1

PHASE: READY_FOR_REVIEW

## PURPOSE

Реализовать backend-этап: произвольный поддерживаемый табличный источник → factual inspection → `DatasetPreparationProposal` → STOP.

## ACCEPTED INPUTS

- `01_ARCHITECT_LOCK.md` — архитектурная граница.
- `02_BACKEND_DESIGN.md` — backend contracts и module boundaries с принятым factual-contract delta.
- `03_UX_FLOW.md` — полный пользовательский путь; confirmation/materialization относятся к следующему этапу.
- `04_ANALYZER_POLICY.md` — детерминированные правила Analyzer V1.

## IMPLEMENTATION

- Реализован backend pipeline `TabularReader → DatasetInspector → DatasetPreparationAnalyzer → DatasetPreparationProposal → STOP`.
- Reviewer FIX: policy hash покрывает используемую policy-конфигурацию; edge cases relation blocks, role precedence, datetime warnings, insufficient data, safe examples и русские explanations исправлены.
- Targeted regression tests и существующие тесты `ReadyDatasetAdapter` пройдены.

## BLOCKED

- Нет блокирующих design-вопросов.

## NEXT

Передать Reviewer diff и targeted test evidence.

## READ FIRST

1. `01_ARCHITECT_LOCK.md`
2. `02_BACKEND_DESIGN.md`
3. `04_ANALYZER_POLICY.md`
4. `05_IMPLEMENTATION_SPEC.md`
5. `03_UX_FLOW.md` — только как product context; UI current stage не реализует.

## SUPERSEDED

- Старый `STATUS.md`, где role-документы считались отсутствующими.
