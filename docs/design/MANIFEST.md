# Design Manifest V1

Этот файл связывает визуальные референсы с экранами продукта. Разработчик должен сначала проверить этот manifest и соответствующий PNG, а уже затем менять UI.

## Бренд AXION

| Файл | Назначение | Статус |
| --- | --- | --- |
| `brand/brandbook/01_logo-system.png` | Логосистема: основной, горизонтальный, вертикальный логотип, знак, wordmark, светлая/тёмная версии | PRIMARY BRAND REFERENCE |
| `brand/brandbook/02_rules-and-parameters.png` | Пропорции, охранное поле, минимальные размеры, палитра, типографика, запрещённые изменения | PRIMARY BRAND RULES |
| `brand/brandbook/03_application-in-product.png` | Применение AXION в интерфейсе, шапке, splash/login, отчёте, презентации, уведомлениях | PRIMARY PRODUCT BRAND REFERENCE |

## Общие компоненты

| Компонент | Файл | Роль |
| --- | --- | --- |
| Button System V2 | `components/buttons/02_button_system_v2.png` | VISUAL LOCK / PRIMARY SHARED COMPONENT REFERENCE для `Primary`, `Secondary`, `Tertiary / Ghost`, `Back`, `Destructive`, `Disabled` и состояний Default / Hover / Pressed / Focus / Disabled на native React экранах и modal dialogs |
| Button System V1 | `components/buttons/01_button_system_v1.png` | PREVIOUS SHARED COMPONENT REFERENCE; superseded по visual treatment системой V2 |
| Data Warnings V2 | `components/data-warnings/01_data_warnings_v2.png` | VISUAL LOCK; collapsed warning summary, `ACTION_REQUIRED / RESOLVED / INFO`, tooltip и secondary accordions |
| Sidebar Final V1 | `components/sidebar/01_sidebar_final_v1.png` | VISUAL LOCK с явным исключением fake profile/auth footer; canonical pattern/motif, плотность и active navigation treatment |
| Long Operations V1 | `components/long-operations/01_long_operations_v1.png` | VISUAL LOCK; общий presentation contract для `LOADING`, `RUNNING_LONG_OPERATION`, training, after-folds, error и ready states |

Button System V2 задаёт внешний вид кнопки, но не семантику действия. Роль `Primary / Secondary / Tertiary / Back / Destructive` определяется UX конкретного состояния экрана. Рекомендуемое направление Primary — `Graphite + Emerald Border`; яркая сплошная emerald-заливка больше не является canonical default.

V2 применяется ко всем runtime-кнопкам, включая header/footer actions, cards и confirmation/native modal. `screens/home/02_home_button_system_v2.png` фиксирует применение системы на Главной. До полной runtime-конвергенции расхождения существующих React-кнопок с V2 считаются известным visual debt.

## Экраны

| Экран | Файл | Роль |
| --- | --- | --- |
| Главная | `screens/home/01_home_axion_v1.png` | PREVIOUS ACCEPTED VISUAL REFERENCE |
| Главная V2 | `screens/home/01_home_axion_v2_candidate.png` | PREVIOUS VISUAL REFERENCE; исторический reference Home V2 |
| Главная — Button System V2 application | `screens/home/02_home_button_system_v2.png` | PREVIOUS APPLICATION REFERENCE; canonical Button System V2 сохраняется, но полный Home authority обновлён |
| Главная V3 | `screens/home/03_home_final_v3.png` | **CURRENT VISUAL LOCK**; актуальный полный reference Home + persistent Sidebar + нижнее меню справки |
| История анализов V1 | `screens/history/01_analysis_history_v1.png` | VISUAL LOCK; read-only каталог завершённых ExperimentArtifact, без Project entity |
| Настройки V1 | `screens/settings/01_settings_v1.png` | VISUAL LOCK; основной collapsed state глобальных настроек AXION |
| Настройки V1 — privacy expanded | `screens/settings/02_settings_privacy_expanded_v1.png` | VISUAL LOCK; тот же Settings screen с раскрытым `Как защищаются данные?` |
| Новый анализ — данные / роли колонок | `screens/new-analysis/01_data_roles_v1.png` | Рабочий референс шага подготовки данных |
| Новый анализ — подтверждение V1 | `screens/new-analysis/02_data_confirmation_v1.png` | PREVIOUS ACCEPTED VISUAL REFERENCE |
| Новый анализ — подтверждение V2 | `screens/new-analysis/02_data_confirmation_v2.png` | VISUAL LOCK; компактный desktop-state подтверждения подготовки данных |
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
| Новый анализ — проверка качества V1 | `screens/new-analysis/05_quality_v1.png` | PREVIOUS ACCEPTED VISUAL REFERENCE |
| Новый анализ — проверка качества V2 | `screens/new-analysis/05_quality_v2.png` | VISUAL LOCK; основной pre-run reference, compact secondary controls и separation после `Готово к запуску` |
| Результат V1 | `screens/result/01_result_v1.png` | PREVIOUS ACCEPTED VISUAL REFERENCE |
| Результат модели V2 | `screens/result/02_result_model_overview_v2.png` | VISUAL LOCK; основной обзор завершённого experiment result |
| Исследование порога V1 | `screens/result/03_threshold_explorer_v1.png` | VISUAL LOCK; threshold exploration по OOF scores без переобучения |
| Объекты оценки V1 | `screens/result/04_result_objects_v2.png` | VISUAL LOCK; аналитический список OOF-объектов и ошибок |
| Объект оценки V1 | `screens/result/05_result_object_detail_v1.png` | VISUAL LOCK; basic detail одного OOF-объекта + Local Explanation foundation |
| Объект оценки + LLM V1 | `screens/result/06_result_object_detail_llm_v1.png` | HISTORICAL / NON-CANONICAL; прежний четырёхколоночный Result Interpreter |
| Объект оценки + Result Interpreter V2 | `screens/result/06_result_object_detail_llm_v2.png` | VISUAL LOCK; canonical master/detail для 4 ролей, один широкий response panel |
| Влияние признаков OOF V1 | `screens/result/07_result_global_oof_shap_v1.png` | VISUAL LOCK; Global OOF feature influence через row-weighted mean(abs(local SHAP)) |
| Объект оценки — explanation loading V1 | `screens/result/08_result_object_detail_explanation_loading_v1.png` | VISUAL LOCK; basic result доступен, Local Explanation рассчитывается отдельно, LLM action disabled |
| Объект оценки — explanation error V1 | `screens/result/09_result_object_detail_explanation_error_v1.png` | VISUAL LOCK; ошибка Local Explanation локализована, basic result сохраняется, retry доступен, LLM disabled |
| Объект оценки — detailed explanation V1 | `screens/result/10_result_object_detail_explanation_detailed_v1.png` | VISUAL LOCK; режим `Подробно` того же Object Detail: SHAP base/output, waterfall и полный список вкладов |
| Объект оценки — LLM loading V1 | `screens/result/11_result_object_detail_llm_loading_v1.png` | HISTORICAL / NON-CANONICAL; loading semantics теперь живут внутри V2 detail panel |
| Объект оценки — LLM error V1 | `screens/result/12_result_object_detail_llm_error_v1.png` | HISTORICAL / NON-CANONICAL; error semantics теперь живут внутри V2 detail panel |

## Правила для V2 references

Статус каждого V2-файла указан в таблице выше. Functional/backend contracts имеют приоритет над демонстрационными данными внутри PNG.

### Sidebar Final V1

- `components/sidebar/01_sidebar_final_v1.png` — canonical shared visual lock sidebar поверх принятого Home V2 shell;
- принимаются фирменный волновой/точечный motif, плотность, отступы, иконки и emerald active-state;
- navigation IA не меняется: `Главная`, `Новый анализ`, `Модели`, `История`, `Настройки`; демонстрационное `Проекты / История` не является новым route/доменом;
- карточка пользователя `Андреев П. С. / Аналитик` в нижней зоне PNG **не является принятой функциональностью** и не должна попадать в runtime до отдельного auth/users contract;
- нижняя зона должна оставаться неинтерактивной и брендовой, без выдуманных имени, роли, avatar, profile menu, login/logout;
- logo/wordmark берутся из Brandbook/Home V2; мелкая подпись `Аналитическая платформа` на демонстрационном sheet не supersede ранее принятые logo rules.

### Data Confirmation V2

- `screens/new-analysis/02_data_confirmation_v2.png` — основной VISUAL LOCK подтверждения подготовки;
- V2 сохраняет semantics V1, но делает экран примерно на 12–15% плотнее за счёт реальных размеров/gaps/paddings, без `transform: scale()`;
- сохраняются File, Key roles, preparation summary, population policy, acknowledgement и footer navigation;
- policy OOF/final-test не меняется визуальным обновлением;
- demo filename/counts/format внутри PNG не являются runtime truth;
- кнопки берутся из Button System V2.

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

### History V1

- `screens/history/01_analysis_history_v1.png` — accepted VISUAL LOCK read-only каталога завершённых анализов;
- canonical sidebar label — `История`; отдельной `Project` entity в V1 нет;
- одна строка = один immutable `ExperimentArtifact` / завершённый experiment run;
- access modes: `FULL_RESULT_V2` и `LEGACY_SUMMARY_ONLY`;
- History не дублирует Models Hub и targetless inference history;
- открытие historical result не мутирует текущую analysis session;
- runtime implementation ждёт `PH-BE1 / PH-UI1`; UI не сканирует filesystem;
- product/architecture semantics: `docs/workstreams/generic_dataset_onboarding_v1/HISTORY_UX_V1.md`.

### Settings V1

- `screens/settings/01_settings_v1.png` — accepted VISUAL LOCK основного collapsed Settings state;
- `screens/settings/02_settings_privacy_expanded_v1.png` — accepted VISUAL LOCK того же экрана с раскрытым privacy explanation;
- Settings содержит две группы: `Интерфейс` и `Интеграции / Интерпретатор результатов`;
- editable controls не смешиваются с read-only system state и actions;
- privacy по умолчанию collapsed; `Подробнее` открывает единственный блок `Как защищаются данные?`;
- provider read-only при одном trusted provider; model — только trusted catalog, без free-text;
- user enable может только сузить deployment policy; external-data policy остаётся read-only;
- API key никогда не читается/показывается обратно UI; credential editing требует secure backend;
- connection check — explicit synthetic request без client/model data; persisted health history не обещается;
- canonical artifact/model/history storage application-managed и не переключается через Settings;
- до отдельного auth/users contract sidebar не показывает fake profile/avatar/name/login;
- runtime implementation ждёт `SET-BE1 / SET-BE2 / SET-UI1`;
- product/architecture semantics: `docs/workstreams/generic_dataset_onboarding_v1/SETTINGS_UX_V1.md`.

### Quality V2

- `screens/new-analysis/05_quality_v2.png` — основной VISUAL LOCK pre-run состояния native Quality; `05_quality_v1.png` остаётся previous accepted reference;
- sidebar и wizard shell берутся из общего AXION shell, а не перерисовываются отдельно;
- stepper сохраняет название **«Проверка качества»**, заголовок страницы — **«Проверка перед запуском»**;
- верхняя сводка показывает только реальные runtime данные: dataset, число выбранных признаков, выбранный алгоритм, режим его настроек;
- у dataset на этом шаге нет локального действия «Изменить»; изменение source требует upstream flow;
- preflight запускается автоматически, отдельной primary-кнопки «Проверить настройки» нет;
- successful preflight показывается как **«Готово к запуску»**, но не является оценкой качества модели;
- основная CTA — **«Начать обучение»**;
- `Дополнительные настройки` и `Технические сведения` по умолчанию collapsed;
- demo `dataset_2026.xlsx`, `30`, `CatBoost` и другие значения PNG не являются runtime truth и не хардкодятся;
- после `Готово к запуску` secondary controls визуально отделены дополнительным вертикальным пространством;
- `Дополнительные настройки` и `Технические сведения` остаются collapsed и показываются компактными, выровненными secondary controls вместо full-width тяжёлых полос;
- после старта этот же шаг превращается в progress state и показывает только реальные backend events; fake percentages/ETA запрещены;
- training/long-operation presentation берётся из `components/long-operations/01_long_operations_v1.png`;
- функциональный контракт: `docs/workstreams/generic_dataset_onboarding_v1/QUALITY_UX_V1.md`.

### Long Operations V1

- `components/long-operations/01_long_operations_v1.png` — canonical shared visual lock долгих и обычных загрузок;
- обычный `LOADING` показывает только title/message + indeterminate AXION indicator: без elapsed, backend stages, percentage и ETA;
- `RUNNING_LONG_OPERATION` может показывать только реально известные backend stage, elapsed и discrete units;
- training использует реальные folds/stages (`Часть X из N`, completed folds, aggregate metrics, persistence), но не превращает folds в fake overall percentage;
- `ERROR` и `READY/COMPLETED` являются устойчивыми состояниями, а не вечным loading text;
- точный percent допустим только если backend реально публикует determinate units для конкретной операции; ETA не придумывается;
- визуальный lock не заменяет performance/reliability fix: тяжёлая операция должна быть исправлена технически, а не замаскирована spinner.

### Result V2

Active visual locks:
- `screens/result/02_result_model_overview_v2.png` — обзор результата;
- `screens/result/03_threshold_explorer_v1.png` — threshold exploration по OOF;
- `screens/result/04_result_objects_v2.png` — список OOF-объектов;
- `screens/result/05_result_object_detail_v1.png` — basic Object Detail;
- `screens/result/08_result_object_detail_explanation_loading_v1.png` — Local SHAP LOADING;
- `screens/result/09_result_object_detail_explanation_error_v1.png` — Local SHAP ERROR;
- `screens/result/10_result_object_detail_explanation_detailed_v1.png` — Local SHAP DETAILED;
- `screens/result/06_result_object_detail_llm_v2.png` — canonical Result Interpreter master/detail;
- `screens/result/07_result_global_oof_shap_v1.png` — Global OOF feature influence.

Non-canonical historical Result Interpreter refs:
`06_result_object_detail_llm_v1.png`, `11_result_object_detail_llm_loading_v1.png`, `12_result_object_detail_llm_error_v1.png`.

Contracts:
- Result UX: `docs/workstreams/generic_dataset_onboarding_v1/RESULT_UX_V2.md`;
- scientific Result/OOF/SHAP architecture: `docs/workstreams/generic_dataset_onboarding_v1/RESULT_V2_ARCHITECTURE_LOCK.md`;
- current Result Interpreter V2: `docs/workstreams/generic_dataset_onboarding_v1/RESULT_INTERPRETER_V2_LOCK.md`;
- universal explainability: `docs/workstreams/generic_dataset_onboarding_v1/UNIVERSAL_MODEL_EXPLAINABILITY_V1.md`.

Demo values в PNG не являются runtime truth. Developer не додумывает отсутствующие public/backend contracts из макета.

## Приоритет источников для UI

1. Accepted backend/UX contracts определяют данные, доступность действий, state transitions и scientific semantics.
2. Для shared component использовать последний принятый component `VISUAL LOCK`; для кнопок это `components/buttons/02_button_system_v2.png`.
3. Для композиции конкретного экрана использовать последний принятый screen `VISUAL LOCK` из таблицы выше.
4. Общий shell брать из принятого Home V2 reference `screens/home/01_home_axion_v2_candidate.png`; для sidebar поверх него действует более новый component lock `components/sidebar/01_sidebar_final_v1.png` с исключением fake profile/auth footer.
5. Previous accepted reference используется только как fallback, если для экрана или компонента ещё нет более нового Visual Lock.
6. Brandbook AXION из `brand/brandbook/` задаёт обязательные правила бренда.

Если старый screen PNG показывает кнопку иначе, чем более новый Button System V2, сохраняется композиция экрана и семантика действия, а внешний вид кнопки берётся из Button System V2.

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
