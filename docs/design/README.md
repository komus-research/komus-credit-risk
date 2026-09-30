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

Для Result V2 приняты пять visual lock:
- `screens/result/02_result_model_overview_v2.png` — общий обзор результата;
- `screens/result/03_threshold_explorer_v1.png` — исследование threshold по OOF scores;
- `screens/result/04_result_objects_v2.png` — список OOF-объектов и ошибок;
- `screens/result/05_result_object_detail_v1.png` — detail одного OOF-объекта, Local Explanation READY и LLM entry;
- `screens/result/06_result_object_detail_llm_v1.png` — тот же detail после успешной LLM-интерпретации.

Поведение Result V2 и границы реализации зафиксированы в `docs/workstreams/generic_dataset_onboarding_v1/RESULT_UX_V2.md`. Макеты не являются источником backend semantics и не разрешают hardcode демонстрационных данных.

Дизайн отдельных экранов уточняется по факту реализации, но без самовольной смены общего визуального языка.

## Язык действий

AXION использует короткие, разговорно-понятные CTA там, где контекст уже объясняет действие. Иконка помогает считывать действие визуально, а длинное техническое описание не дублирует очевидное. Пример: `▶ Анализ` на экране применения сохранённой модели к новым данным. Если действие может быть понято неоднозначно или имеет важные последствия, рядом допускается короткая поясняющая подпись/tooltip. Утверждённые mockup PNG не требуют перерисовки только ради таких текстовых сокращений: runtime copy можно точечно улучшать при реализации, не меняя semantics и visual hierarchy.


## Runtime assets

Clean implementation-ready brand and hero assets are stored under `app/assets/`. Screen PNGs under `docs/design/screens/` remain visual references and should not be cropped into runtime assets.
