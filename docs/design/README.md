# AXION Design Package V1

Единый дизайн-пакет проекта AXION.

Здесь лежат:
- брендовые референсы;
- утверждённые экраны;
- визуальные ориентиры для разработки.

Правила:
1. Экранные решения брать из `screens/`.
2. Брендовые решения брать из `brand/`.
3. Не придумывать визуальный стиль по памяти, если уже есть утверждённый референс.
4. При изменении утверждённого экрана добавлять новую версию (`v2`, `v3`), не перезаписывая предыдущую без решения владельца.
5. Код интерфейса должен следовать этим материалам; если референс и текущая реализация расходятся, сначала уточнить решение, а не импровизировать.

## Основной visual reference

Принятая Главная AXION V2 (`screens/home/01_home_axion_v2_candidate.png`; историческое имя файла) задаёт общий visual shell продукта:
- тёмный graphite background;
- emerald / teal accent;
- светлый основной текст;
- тонкие контуры карточек;
- компактные статусные бейджи;
- технологичный, спокойный, аналитический характер.

## Основной пользовательский поток

`Данные → Признаки → Алгоритм → Проверка качества → Результат`

Для шага **«Проверка качества»** принят Visual Lock `screens/new-analysis/05_quality_v1.png`: pre-run state строится как автоматическая проверка готовности с одной primary CTA **«Начать обучение»**; технический smoke не выдаётся за quality metric evaluation.

Для будущего trusted-plugin onboarding принят Visual Lock `screens/algorithm/01_connect_algorithm_v1.png`: это **«Подключить алгоритм»**, а не импорт уже обученной ModelVersion. Один и тот же flow должен открываться из `Новый анализ → Алгоритм` и из `Модели`.

Для раздела **«Модели»** приняты visual lock:
- `screens/models/01_models_hub_v1.png` — общий каталог сохранённых ModelVersion;
- `screens/models/02_algorithm_detail_v1.png` — конкретный алгоритм и все его сохранённые обучения;
- `screens/models/02_algorithm_detail_highlight_v1.png` — тот же Algorithm Detail с опциональной относительной подсветкой OOF Gini / ROC-AUC / PR-AUC;
- `screens/models/03_model_version_detail_v1.png` — detail конкретной сохранённой ModelVersion с OOF quality, dataset/features, saved configuration и дальнейшими действиями;
- `screens/models/04_saved_model_inference_v1.png` — применение сохранённой ModelVersion к новым данным после trusted compatibility check, без переобучения;
- `screens/models/05_saved_model_inference_result_v1.png` — accepted Visual Lock результата targetless inference; immutable inference Result отделён от mutable saved view configuration. Runtime action — `Сохранить конфигурацию`; reset доступен условно через `⋯`; default threshold без saved config = 0,50.

Product semantics и backend gap зафиксированы в `docs/workstreams/generic_dataset_onboarding_v1/MODELS_UX_V1.md`.

Для раздела **«История»** принят Visual Lock `screens/history/01_analysis_history_v1.png`.
History V1 — read-only каталог завершённых `ExperimentArtifact`, а не Project Manager. Отдельной `Project` entity в V1 нет. Исторический V3 result открывается через существующий Result V2, legacy artifact — только в честном `LEGACY_SUMMARY_ONLY` режиме. Product/architecture semantics и будущий `AnalysisHistoryService.list()/detail()` зафиксированы в `docs/workstreams/generic_dataset_onboarding_v1/HISTORY_UX_V1.md`.

Для раздела **«Настройки»** приняты два visual lock:
- `screens/settings/01_settings_v1.png` — основной collapsed state;
- `screens/settings/02_settings_privacy_expanded_v1.png` — тот же screen с раскрытым privacy explanation.

Settings V1 содержит только реальные global controls: interface presentation preference и Result Interpreter integration controls. ML/Result scientific parameters остаются в своих flows. До отдельного authentication/users contract в shell нет fake profile/login/account UI. Product/architecture semantics и backend order `SET-BE1 → SET-BE2 → SET-UI1` зафиксированы в `docs/workstreams/generic_dataset_onboarding_v1/SETTINGS_UX_V1.md`.

Для Result V2 active visual locks перечислены в `docs/design/MANIFEST.md`. Для Result Interpreter единственный canonical reference — `screens/result/06_result_object_detail_llm_v2.png` (master/detail: роли слева, один широкий response справа).

Старые `06_result_object_detail_llm_v1.png`, `11_result_object_detail_llm_loading_v1.png`, `12_result_object_detail_llm_error_v1.png` — historical/non-canonical и не используются как visual authority.

Контракты:
- Result/SHAP UX: `docs/workstreams/generic_dataset_onboarding_v1/RESULT_UX_V2.md`;
- scientific Result/OOF/SHAP: `docs/workstreams/generic_dataset_onboarding_v1/RESULT_V2_ARCHITECTURE_LOCK.md`;
- current Result Interpreter V2: `docs/workstreams/generic_dataset_onboarding_v1/RESULT_INTERPRETER_V2_LOCK.md`.

Макеты не являются источником backend semantics и не разрешают hardcode демонстрационных данных.

Дизайн отдельных экранов уточняется по факту реализации, но без самовольной смены общего визуального языка.

## Язык действий

AXION использует короткие, разговорно-понятные CTA там, где контекст уже объясняет действие. Иконка помогает считывать действие визуально, а длинное техническое описание не дублирует очевидное. Пример: `▶ Анализ` на экране применения сохранённой модели к новым данным. Если действие может быть понято неоднозначно или имеет важные последствия, рядом допускается короткая поясняющая подпись/tooltip. Утверждённые mockup PNG не требуют перерисовки только ради таких текстовых сокращений: runtime copy можно точечно улучшать при реализации, не меняя semantics и visual hierarchy.


## Runtime assets

Clean implementation-ready brand and hero assets are stored under `app/assets/`. Screen PNGs under `docs/design/screens/` remain visual references and should not be cropped into runtime assets.
