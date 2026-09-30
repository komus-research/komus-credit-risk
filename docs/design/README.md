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

Для Result V2 приняты три visual lock:
- `screens/result/02_result_model_overview_v2.png` — общий обзор результата;
- `screens/result/03_threshold_explorer_v1.png` — исследование threshold по OOF scores;
- `screens/result/04_result_objects_v1.png` — список OOF-объектов и ошибок.

Поведение Result V2 и границы реализации зафиксированы в `docs/workstreams/generic_dataset_onboarding_v1/RESULT_UX_V2.md`. Макеты не являются источником backend semantics и не разрешают hardcode демонстрационных данных.

Дизайн отдельных экранов уточняется по факту реализации, но без самовольной смены общего визуального языка.


## Runtime assets

Clean implementation-ready brand and hero assets are stored under `app/assets/`. Screen PNGs under `docs/design/screens/` remain visual references and should not be cropped into runtime assets.
