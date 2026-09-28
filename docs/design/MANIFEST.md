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
| Главная | `screens/home/01_home_axion_v1.png` | PRIMARY VISUAL REFERENCE всего продукта |
| Новый анализ — данные / роли колонок | `screens/new-analysis/01_data_roles_v1.png` | Рабочий референс шага подготовки данных |
| Новый анализ — подтверждение | `screens/new-analysis/02_data_confirmation_v1.png` | Рабочий референс шага подтверждения |
| Новый анализ — признаки | `screens/new-analysis/03_features_v1.png` | Рабочий референс выбора признаков |
| Новый анализ — алгоритм | `screens/new-analysis/04_algorithm_v1.png` | Рабочий референс выбора модели и настроек |
| Результат | `screens/result/01_result_v1.png` | Рабочий референс итогового экрана |

## Что пока отсутствует

Отдельный визуальный референс экрана **«Проверка качества»** пока не зафиксирован. Его нельзя придумывать как отдельный стиль: он должен наследовать общий визуальный язык главной AXION и соседних экранов.

## Приоритет источников для UI

1. Конкретный screen reference из `screens/`.
2. `screens/home/01_home_axion_v1.png` как общий visual language.
3. Brandbook AXION из `brand/brandbook/`.
4. Accepted UX/backend docs — для поведения и данных, но не для самостоятельного изобретения нового визуального стиля.

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
