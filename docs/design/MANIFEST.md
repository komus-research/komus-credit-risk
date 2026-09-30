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
| Новый анализ — проверка качества V1 | `screens/new-analysis/05_quality_v1.png` | VISUAL LOCK; основной reference для native Quality V1 |
| Результат | `screens/result/01_result_v1.png` | Рабочий референс итогового экрана |

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
- общий layout, `Подключить модель`, меню `⋯`, `Рекомендуемые / Расширенные`, блок `Технические сведения` и footer сохранить.

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
