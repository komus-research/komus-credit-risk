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
- [generic_dataset_onboarding_v1/ALGORITHM_UX_V1.md](generic_dataset_onboarding_v1/ALGORITHM_UX_V1.md)
- [generic_dataset_onboarding_v1/CONNECT_ALGORITHM_UX_V1.md](generic_dataset_onboarding_v1/CONNECT_ALGORITHM_UX_V1.md)
- [generic_dataset_onboarding_v1/MODELS_UX_V1.md](generic_dataset_onboarding_v1/MODELS_UX_V1.md)
- [generic_dataset_onboarding_v1/QUALITY_UX_V1.md](generic_dataset_onboarding_v1/QUALITY_UX_V1.md)

Текущий product status:

- Данные / Файл — UX/VISUAL LOCK;
- Данные / Роли колонок — UX/VISUAL LOCK;
- Данные / Подтверждение — UX/VISUAL LOCK V2 (`docs/design/screens/new-analysis/02_data_confirmation_v2.png`);
- Native Features V1 — CLOSED / ACCEPTED;
- Native Algorithm V2 — CLOSED / ACCEPTED, source commit `e85994017fd08c1dadede0694700f1847cf72f2b`;
- Connect Algorithm V1 — PRODUCT / VISUAL LOCK ACCEPTED, backend implementation pending; один flow из `Новый анализ → Алгоритм` и `Модели`;
- Models UX V1 — PRODUCT / VISUAL LOCK ACCEPTED, backend implementation pending; Models Hub + Algorithm Detail + optional Metric Highlight + ModelVersion Detail + Saved Model Inference;
- Quality V1 semantics — UX ACCEPTED; primary visual lock обновлён до Quality V2 (`docs/design/screens/new-analysis/05_quality_v2.png`).

Quality V1 использует автоматический backend preflight и одну primary CTA **«Начать обучение»**; technical smoke не является quality verdict.

Cross-cutting native UI visual authority:

- Buttons — `docs/design/components/buttons/02_button_system_v2.png`;
- Data Warnings — `docs/design/components/data-warnings/01_data_warnings_v2.png`;
- Sidebar — `docs/design/components/sidebar/01_sidebar_final_v1.png` с явным исключением fake profile/auth footer;
- Long Operations — `docs/design/components/long-operations/01_long_operations_v1.png`.

Эти locks применяются при реализации, не меняя action/backend/scientific semantics. Runtime ещё не объявлен полностью приведённым к новым visual locks.

## Active backend workstreams

### Configurable Model Platform V1

Status:

**CLOSED — MP-A + MP-B + MP-C + MP-D + MP-E ACCEPTED**

Документы:

- [configurable_model_platform_v1/STATUS.md](configurable_model_platform_v1/STATUS.md)
- [configurable_model_platform_v1/ARCHITECT_LOCK.md](configurable_model_platform_v1/ARCHITECT_LOCK.md)

Цель:

`ModelPlugin → parameter schema/capabilities → ResolvedModelConfiguration → mandatory technical smoke → existing Runner → provider-based persistence`.

Текущий ML-core не переписывается.

### Feature Grouping Propagation V1

Status:

**CLOSED / ACCEPTED**

Документы:

- [feature_grouping_propagation_v1/STATUS.md](feature_grouping_propagation_v1/STATUS.md)
- [feature_grouping_propagation_v1/SPEC.md](feature_grouping_propagation_v1/SPEC.md)

Текущий Analyzer уже строит technical groups каскадом:

`structural stem → repeated name token → logical type → fallback`.

Gap закрыт: Materializer V2 переносит trusted Analyzer technical groups в downstream `FeatureRegistry → FeatureGroup`, не меняя permissions/selection semantics.

## Current order

1. Configurable Model Platform V1 — **CLOSED / ACCEPTED**.
2. Feature Grouping Propagation V1 — **CLOSED / ACCEPTED**.
3. Native Features V1 — **CLOSED / ACCEPTED**.
4. Native Algorithm V2 — **CLOSED / ACCEPTED**.
5. Native Quality semantics / full training — **CLOSED / ACCEPTED**; visual polish идёт по `05_quality_v2.png` и Long Operations V1.
6. Immediate corrective priority — Global OOF Explanation reliability/performance на реальном большом XGBoost artifact; затем продолжается оставшийся Result/native product work.

## Later

Отдельными последующими направлениями остаются:

- Dataset History / Persistence V1;
- Model Package UX;
- production React/Next.js + thin FastAPI boundary;
- semantic business taxonomy/features при наличии trusted source;
- threshold/business policy UI;
- production auth/DB/deployment.

