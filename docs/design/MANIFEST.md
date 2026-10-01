# Design Manifest V1

Этот файл связывает визуальные референсы с экранами продукта. Разработчик должен сначала проверить этот manifest и соответствующий PNG, а уже затем менять UI.

## Бренд AXION

| Файл | Назначение | Статус |
| --- | --- | --- |
| `brand/brandbook/01_logo-system.png` | Логосистема: основной, горизонтальный, вертикальный логотип, знак, wordmark, светлая/тёмная версии | PRIMARY BRAND REFERENCE |
| `brand/brandbook/02_rules-and-parameters.png` | Пропорции, охранное поле, минимальные размеры, палитра, типографика, запрещённые изменения | PRIMARY BRAND RULES |
| `brand/brandbook/03_application-in-product.png` | Применение AXION в интерфейсе, шапке, splash/login, отчёте, презентации, уведомлениях | PRIMARY PRODUCT BRAND REFERENCE |

## Экраны

| Экран | Файл | Роль |
| --- | --- | --- |
| Главная | `screens/home/01_home_axion_v1.png` | PREVIOUS ACCEPTED VISUAL REFERENCE |
| Главная V2 | `screens/home/01_home_axion_v2_candidate.png` | VISUAL LOCK; основной reference общего AXION shell / Home V2 |
| Новый анализ — данные / роли колонок | `screens/new-analysis/01_data_roles_v1.png` | Рабочий референс шага подготовки данных |
| Новый анализ — подтверждение | `screens/new-analysis/02_data_confirmation_v1.png` | Рабочий референс шага подтверждения |
| Новый анализ — признаки | `screens/new-analysis/03_features_v1.png` | Рабочий референс выбора признаков |
| Новый анализ — алгоритм | `screens/new-analysis/04_algorithm_v1.png` | PREVIOUS ACCEPTED VISUAL REFERENCE |
| Новый анализ — алгоритм V2 | `screens/new-analysis/04_algorithm_v2.png` | VISUAL LOCK; основной reference для native Algorithm V2 |
| Подключить алгоритм V1 | `screens/algorithm/01_connect_algorithm_v1.png` | VISUAL LOCK; trusted algorithm/plugin onboarding, доступен из «Новый анализ → Алгоритм» и «Модели» |
| Модели — библиотека V1 | `screens/models/01_models_hub_v1.png` | VISUAL LOCK; общий каталог сохранённых ModelVersion + вкладка «Алгоритмы» |
| Модели — алгоритм V1 | `screens/models/02_algorithm_detail_v1.png` | VISUAL LOCK; конкретный algorithm/plugin и история его сохранённых ModelVersion |
| Модели — алгоритм / подсветка метрик V1 | `screens/models/02_algorithm_detail_highlight_v1.png` | VISUAL LOCK; optional relative metric highlighting для текущего filtered list |
| Модели — сохранённая модель V1 | `screens/models/03_model_version_detail_v1.png` | VISUAL LOCK; detail одной сохранённой ModelVersion, её OOF quality, данные, признаки и действия |
| Модели — анализ новых данных V1 | `screens/models/04_saved_model_inference_v1.png` | VISUAL LOCK; применение сохранённой ModelVersion к новому совместимому dataset без переобучения |
| Модели — результат анализа новых данных V1 | `screens/models/05_saved_model_inference_result_v1.png` | VISUAL LOCK; `Сохранить конфигурацию`, saved view восстанавливается на том же Result, `Сбросить настройки` доступен условно в `⋯`; default threshold без config = 0.50 |
| Новый анализ — проверка качества V1 | `screens/new-analysis/05_quality_v1.png` | VISUAL LOCK; основной reference для native Quality V1 |
| Результат V1 | `screens/result/01_result_v1.png` | PREVIOUS ACCEPTED VISUAL REFERENCE |
| Результат модели V2 | `screens/result/02_result_model_overview_v2.png` | VISUAL LOCK; основной обзор завершённого experiment result |
| Исследование порога V1 | `screens/result/03_threshold_explorer_v1.png` | VISUAL LOCK; threshold exploration по OOF scores без переобучения |
| Объекты оценки V1 | `screens/result/04_result_objects_v2.png` | VISUAL LOCK; аналитический список OOF-объектов и ошибок |
| Объект оценки V1 | `screens/result/05_result_object_detail_v1.png` | VISUAL LOCK; detail одного OOF-объекта, Local Explanation READY и LLM entry |
| Объект оценки + LLM V1 | `screens/result/06_result_object_detail_llm_v1.png` | VISUAL LOCK; тот же detail после успешной LLM-интерпретации |
| Влияние признаков OOF V1 | `screens/result/07_result_global_oof_shap_v1.png` | VISUAL LOCK; Global OOF feature influence через row-weighted mean(abs(local SHAP)) |
| Объект оценки — explanation loading V1 | `screens/result/08_result_object_detail_explanation_loading_v1.png` | VISUAL LOCK; basic result доступен, Local Explanation рассчитывается отдельно, LLM action disabled |
| Объект оценки — explanation error V1 | `screens/result/09_result_object_detail_explanation_error_v1.png` | VISUAL LOCK; ошибка Local Explanation локализована, basic result сохраняется, retry доступен, LLM disabled |

## Правила для V2 references

Статус каждого V2-файла указан в таблице выше. Functional/backend contracts имеют приоритет над демонстрационными данными внутри PNG.

### Home V2

- использовать фирменный знак + слово **AXION**;
- под логотипом не должно быть мелкой подписи, слогана или `Аналитическая платформа`;
- блоки истории/проектов/моделей нельзя наполнять выдуманными runtime-данными: при реализации они подключаются только к существующим backend capabilities либо получают честный empty/disabled state.

### Algorithm V2

- `screens/new-analysis/04_algorithm_v2.png` — принятый VISUAL LOCK центральной области Algorithm;
- sidebar на PNG не является source of truth: использовать общий shell/sidebar из реализованного Home V2;
- фирменный знак + **AXION**, без мелкой подписи;
- `GBDT Mean` является встроенным ensemble и должен иметь источник **«Встроенная»**, а не демонстрационное «Подключённая» на PNG;
- действие **«Удалить подключённую модель»** доступно только для реально импортированных пользовательских моделей;
- встроенные модели можно скрыть из рабочего списка, но не удалять из registry;
- демонстрационный `Проект: Анализ контрагентов 2026` не является runtime-данными и не должен хардкодиться;
- общий layout, действие `Подключить алгоритм`, меню `⋯`, `Рекомендуемые / Расширенные`, блок `Технические сведения` и footer сохранить;
- отдельный trusted-plugin flow зафиксирован в `screens/algorithm/01_connect_algorithm_v1.png` и `CONNECT_ALGORITHM_UX_V1.md`; он не является импортом обученной ModelVersion.

### Models V1

- `screens/models/01_models_hub_v1.png` — accepted visual lock общего каталога сохранённых ModelVersion;
- `screens/models/02_algorithm_detail_v1.png` — accepted visual lock истории обучений конкретного algorithm/plugin;
- `screens/models/02_algorithm_detail_highlight_v1.png` — accepted optional highlight-state того же Algorithm Detail;
- `screens/models/03_model_version_detail_v1.png` — accepted visual lock detail одной сохранённой ModelVersion;
- `screens/models/04_saved_model_inference_v1.png` — accepted visual lock применения сохранённой ModelVersion к новым данным без retraining;
- `screens/models/05_saved_model_inference_result_v1.png` — accepted VISUAL LOCK targetless inference result; immutable Result + separate mutable saved view configuration are locked; `Сохранить конфигурацию` is canonical, `Сбросить настройки` lives conditionally in `⋯`, demo threshold 0.37 is not the no-config default;
- canonical distinction: Algorithm/ModelPlugin ≠ trained ModelVersion;
- Metric Highlight default OFF и сравнивает OOF Gini / ROC-AUC / PR-AUC только относительно текущего filtered list, отдельно по каждой колонке;
- highlighting не является ranking, winner selection, final-test evidence или business verdict;
- backend browse/list/history contract пока не реализован; UI не сканирует filesystem и не фабрикует catalog rows/counts;
- product semantics: `docs/workstreams/generic_dataset_onboarding_v1/MODELS_UX_V1.md`.

### Quality V1

- `screens/new-analysis/05_quality_v1.png` — принятый VISUAL LOCK pre-run состояния native Quality;
- sidebar и wizard shell берутся из общего AXION shell, а не перерисовываются отдельно;
- stepper сохраняет название **«Проверка качества»**, заголовок страницы — **«Проверка перед запуском»**;
- верхняя сводка показывает только реальные runtime данные: dataset, число выбранных признаков, выбранный алгоритм, режим его настроек;
- у dataset на этом шаге нет локального действия «Изменить»; изменение source требует upstream flow;
- preflight запускается автоматически, отдельной primary-кнопки «Проверить настройки» нет;
- successful preflight показывается как **«Готово к запуску»**, но не является оценкой качества модели;
- основная CTA — **«Начать обучение»**;
- `Дополнительные настройки` и `Технические сведения` по умолчанию collapsed;
- demo `dataset_2026.xlsx`, `30`, `CatBoost` и другие значения PNG не являются runtime truth и не хардкодятся;
- после старта этот же шаг превращается в progress state и показывает только реальные backend events; fake percentages/ETA запрещены;
- функциональный контракт: `docs/workstreams/generic_dataset_onboarding_v1/QUALITY_UX_V1.md`.

### Result V2

- `screens/result/02_result_model_overview_v2.png` — accepted visual lock общего обзора результата;
- `screens/result/03_threshold_explorer_v1.png` — accepted visual lock исследования threshold по OOF scores;
- `screens/result/04_result_objects_v2.png` — accepted visual lock списка OOF-объектов;
- `screens/result/05_result_object_detail_v1.png` — accepted visual lock detail одного OOF-объекта с Local Explanation READY и pre-action LLM block;
- `screens/result/06_result_object_detail_llm_v1.png` — accepted visual lock того же Object Detail после successful LLM interpretation;
- `screens/result/07_result_global_oof_shap_v1.png` — accepted visual lock Global OOF feature influence;
- `screens/result/08_result_object_detail_explanation_loading_v1.png` — accepted visual lock Object Detail во время Local Explanation loading;
- `screens/result/09_result_object_detail_explanation_error_v1.png` — accepted visual lock Object Detail при Local Explanation error;
- подробная UX/semantic спецификация: `docs/workstreams/generic_dataset_onboarding_v1/RESULT_UX_V2.md`;
- backend architecture lock: `docs/workstreams/generic_dataset_onboarding_v1/RESULT_V2_ARCHITECTURE_LOCK.md`;
- universal model explainability lock: `docs/workstreams/generic_dataset_onboarding_v1/UNIVERSAL_MODEL_EXPLAINABILITY_V1.md`;
- demo values в PNG не являются runtime truth и не хардкодятся;
- `Result model → Threshold Explorer → Objects → Object Detail` — принятый visual flow;
- Object Detail visual lock включает Local Explanation READY и pre-action LLM entry; отдельный `06_result_object_detail_llm_v1.png` фиксирует LLM READY state;
- `08_result_object_detail_explanation_loading_v1.png` фиксирует Local Explanation LOADING state без блокировки basic result;
- `09_result_object_detail_explanation_error_v1.png` фиксирует Local Explanation ERROR state: basic result остаётся доступен, retry повторяет только explanation;
- отдельные LLM loading/error variants пока не имеют visual lock;
- для objects: target marker, threshold position и TP/TN/FP/FN — разные смыслы и не должны сливаться;
- object table проектируется как scrollable/virtualizable view, а не как browser-side загрузка всей выборки;
- Fold остаётся read-only OOF provenance с tooltip;
- отсутствующие backend/public contracts не додумываются из макета: Developer должен остановиться и поднять точный gap.

## Приоритет источников для UI

1. Для конкретного экрана использовать последний принятый `VISUAL LOCK` из таблицы выше.
2. Общий shell/sidebar брать из принятого Home V2 reference `screens/home/01_home_axion_v2_candidate.png` (историческое имя файла сохраняется, статус — accepted VISUAL LOCK).
3. Previous accepted reference используется только как fallback, если для экрана ещё нет более нового Visual Lock.
4. Brandbook AXION из `brand/brandbook/` задаёт обязательные правила бренда.
5. Accepted UX/backend docs задают поведение и реальные данные, но не являются основанием самостоятельно изобретать новый визуальный стиль.

Если референс конфликтует с фактическим backend-контрактом, не подделывать данные под картинку: сохранить визуальную композицию и поднять точное расхождение на согласование.


## Production assets

Runtime-ready assets for implementation live in `app/assets/`:

| File | Purpose |
| --- | --- |
| `app/assets/brand/logo-primary-dark.png` | Primary logo for dark UI |
| `app/assets/brand/logo-primary-light.png` | Primary logo for light UI |
| `app/assets/brand/logo-mark-primary.png` | Standalone AXION mark |
| `app/assets/brand/wordmark-dark.png` | Light AXION wordmark for dark UI |
| `app/assets/brand/wordmark-light.png` | Dark AXION wordmark for light UI |
| `app/assets/brand/app-icon-1024.png` | Application icon |
| `app/assets/brand/favicon-32.png` | 32 px favicon |
| `app/assets/brand/favicon-16.png` | 16 px favicon |
| `app/assets/images/home-hero-banner.png` | Wide home hero, source PNG |
| `app/assets/images/home-hero-banner.webp` | Wide home hero, optimized WebP |

SVG exports are not available in V1 and are not a blocker for the current Streamlit implementation.
