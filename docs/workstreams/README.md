# Workstreams

`docs/workstreams/` хранит рабочую документацию по отдельным направлениям проекта. Она нужна, чтобы следующая роль могла прочитать принятое решение и handoff без доступа к исходному обсуждению.

## Источники и назначение

- Чаты предназначены для обсуждения.
- Git фиксирует решения, handoff и историю их изменений.
- Глобальные документы в `docs/` содержат принятую истину, действующую для всего проекта.
- Принятый документ workstream содержит подробное принятое решение по конкретному направлению; он не заменяет глобальные документы.
- `STATUS.md` служит навигацией и показывает состояние направления, но не является источником смысла решения.
- Draft-документы являются предложениями до их принятия.

Не переносите сюда содержимое `ARCHITECTURE.md` или других глобальных документов и не используйте workstreams как архив всех разговоров.

## Ownership

Автор документа отвечает за точность его содержания. Роль, принимающая решение, переводит документ в `ACCEPTED`; последующие роли используют его как входной материал и не меняют смысл без нового явно зафиксированного решения. Координатор поддерживает навигацию в `STATUS.md` в соответствии с фактическим состоянием документов.

## Статусы документов

- `DRAFT` — предложение в работе.
- `READY_FOR_REVIEW` — готов к проверке.
- `FIX_REQUIRED` — требует исправлений по итогам проверки.
- `ACCEPTED` — решение принято.
- `BLOCKED` — работа заблокирована.
- `SUPERSEDED` — заменён более новым решением.

## Фазы workstream

- `DESIGN`
- `READY_FOR_IMPLEMENTATION`
- `IMPLEMENTATION`
- `REVIEW`
- `CLOSED`
- `BLOCKED`

## Порядок чтения

1. `docs/CURRENT_STATE.md`
2. `STATUS.md` нужного направления
3. Раздел `READ FIRST` в этом `STATUS.md`

Пустые placeholder-файлы не создаются: документ появляется только при наличии исходного материала и реальной ответственности.

## Dataset Preparation V1

Принятый и закрытый backend workstream:

[dataset_preparation_v1/STATUS.md](dataset_preparation_v1/STATUS.md)

Граница:

`proposal → human confirmation → materialization → PreparedDatasetContext`.

Техническая интеграция Dataset Preparation UI V1 и browser-native file flow приняты.

Historical `Data_final` рассматривается только как frozen compatibility profile, а не как отдельный основной режим продукта.

## Generic Dataset Onboarding / Feature Selection UX

Canonical downstream flow:

`PreparedDatasetContext → Признаки → Алгоритм → Проверка качества → Результат`.

Документы:

- [generic_dataset_onboarding_v1/SPEC.md](generic_dataset_onboarding_v1/SPEC.md)
- [generic_dataset_onboarding_v1/FEATURE_SELECTION_UX_V1.md](generic_dataset_onboarding_v1/FEATURE_SELECTION_UX_V1.md)

Текущий product status:

- Данные / Файл — UX/VISUAL LOCK;
- Данные / Роли колонок — UX/VISUAL LOCK;
- Данные / Подтверждение — UX/VISUAL LOCK;
- Признаки — UX/VISUAL LOCK.

Экран «Алгоритм» поставлен на паузу до завершения backend blockers.

## Active backend workstreams

### Configurable Model Platform V1

Status:

**MP-A + MP-B ACCEPTED / MP-C READY_FOR_IMPLEMENTATION**

Документы:

- [configurable_model_platform_v1/STATUS.md](configurable_model_platform_v1/STATUS.md)
- [configurable_model_platform_v1/ARCHITECT_LOCK.md](configurable_model_platform_v1/ARCHITECT_LOCK.md)

Цель:

`ModelPlugin → parameter schema/capabilities → ResolvedModelConfiguration → mandatory technical smoke → existing Runner → provider-based persistence`.

Текущий ML-core не переписывается.

### Feature Grouping Propagation V1

Status:

**DESIGN / ARCHITECT LOCK REQUIRED BEFORE CODE**

Документы:

- [feature_grouping_propagation_v1/STATUS.md](feature_grouping_propagation_v1/STATUS.md)
- [feature_grouping_propagation_v1/SPEC.md](feature_grouping_propagation_v1/SPEC.md)

Текущий Analyzer уже строит technical groups каскадом:

`structural stem → repeated name token → logical type → fallback`.

Открытый gap — перенести эту grouping metadata через generic materialization в downstream `FeatureRegistry → FeatureGroup`, не меняя permissions/selection semantics.

## Current order

1. Configurable Model Platform V1 — **MP-A + MP-B ACCEPTED**, далее MP-C → MP-E через Developer → Reviewer.
2. Feature Grouping Propagation V1 — narrow Architect Lock → Developer → Reviewer.
3. После ACCEPT обеих backend-задач — продолжить UX с экраном «Алгоритм».
4. Затем «Проверка качества → Результат» и финальный product E2E.

## Later

Отдельными последующими направлениями остаются:

- Dataset History / Persistence V1;
- Model Package UX;
- production React/Next.js + thin FastAPI boundary;
- semantic business taxonomy/features при наличии trusted source;
- threshold/business policy UI;
- production auth/DB/deployment.

