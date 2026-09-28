# AXION Design System V1

Status: **PRIMARY VISUAL SYSTEM / IMPLEMENTATION REFERENCE**

Этот документ фиксирует визуальный язык первой продуктовой сборки AXION. Конкретные экраны из `docs/design/screens/` имеют приоритет для композиции; этот документ задаёт общие правила между экранами.

## 1. Brand

Продуктовое направление: **AXION — аналитическая платформа**.

Основные брендовые источники:

- `brand/brandbook/01_logo-system.png`
- `brand/brandbook/02_rules-and-parameters.png`
- `brand/brandbook/03_application-in-product.png`

Не изменять пропорции, ориентацию, начертание или фирменные цвета логотипа. Не добавлять произвольные тени, обводки и эффекты поверх знака.

## 2. Цветовая система

Основные цвета брендбука:

| Token | HEX | Назначение |
| --- | --- | --- |
| Emerald | `#00E5C2` | основной accent, active state, primary interactive highlight |
| Deep Teal | `#00B894` | дополнительный accent, градиент, secondary highlight |
| Graphite | `#0B1417` | основной тёмный фон интерфейса |
| Off White | `#EAF6F4` | основной светлый текст и графика |
| Slate | `#2A3A40` | вторичный текст, контуры, secondary UI surfaces |

Общий принцип: тёмный спокойный интерфейс, emerald/teal используется дозированно для активных и важных состояний, а не как сплошная заливка всего экрана.

## 3. Типографика

Рекомендуемая иерархия брендбука:

- заголовки / навигация / ключевые элементы: `Inter`, `Manrope` или `SF Pro`, Semibold / Bold;
- основной интерфейсный текст: `Inter`, `Manrope` или `SF Pro`, Regular / Medium;
- вторичная информация, метрики и подписи: Regular / Light.

В реализации использовать один фактически доступный основной UI-font последовательно. Не смешивать семейства на одном экране без необходимости.

## 4. Общий shell

Главный source of truth:

`screens/home/01_home_axion_v1.png`

Общие элементы продукта:

- фиксированная левая навигация;
- логотип AXION в верхней части sidebar;
- primary action `Новый анализ`;
- рабочая область справа;
- верхняя зона контекста / поиска / действий;
- компактные карточки, таблицы и status badges;
- тонкие границы и умеренные скругления;
- высокая информационная плотность без ощущения инженерной консоли.

## 5. Навигация

Базовая структура из референсов:

- Главная
- Новый анализ
- Модели
- Проекты / История
- Настройки

Во flow нового анализа сохраняется верхний stepper:

`Данные → Признаки → Алгоритм → Проверка качества → Результат`

Навигация не должна менять scientific state без явного действия пользователя.

## 6. Карточки и панели

- поверхность темнее/светлее основного Graphite только настолько, чтобы отделить блок;
- тонкий teal/slate border;
- selected/active — emerald outline/glow в пределах референса;
- primary action — emerald/teal;
- secondary action — outline / low-emphasis;
- technical blocks визуально вторичны и по умолчанию свёрнуты, если это предусмотрено UX lock.

## 7. Статусы

Статусные цвета должны сохранять смысл и не конкурировать с основным emerald brand accent.

- success / ready — emerald/teal;
- warning / requires attention — amber;
- error / blocked — red;
- informational / secondary — cool blue/slate.

Точный текст статуса приходит из UX/backend semantics, а не придумывается только ради цвета.

## 8. Данные и таблицы

- компактные строки;
- читаемые заголовки;
- secondary metadata приглушена;
- действия справа;
- статусные badges короткие;
- не превращать таблицу в spreadsheet с лишними рамками;
- числовые метрики выравнивать последовательно.

## 9. Изображения и декоративная графика

Большой AXION banner на главной — часть утверждённого визуального референса.

Декоративные изображения не должны заменять рабочие данные или мешать чтению. Если для production нужен отдельный logo/banner asset, использовать чистый экспорт из `brand/exports/`, а не вырезать его из скриншота без согласования.

## 10. Приоритет при реализации

1. Фактический backend contract — истина для данных, доступности и поведения.
2. Accepted UX document — истина для state transitions и interaction semantics.
3. Конкретный PNG screen reference — истина для композиции и визуальной иерархии.
4. Этот Design System — истина для общего визуального языка.
5. Brandbook — истина для бренда, логотипа, цветов и ограничений.

Если источники конфликтуют, Developer не принимает решение самостоятельно: STOP и сообщает точное расхождение.

## 11. Итерационный режим

V1 реализуется максимально близко к утверждённым референсам. После просмотра реального приложения владелец может давать мелкие визуальные корректировки. Такие корректировки не должны автоматически менять backend/UX semantics.


## 12. Production assets V1

Approved implementation assets are already prepared under `app/assets/`. The home page should use the wide `home-hero-banner.webp` (or PNG when lossless source is needed) and the dark-UI AXION logo. Favicon and app icon are generated from the approved square brand asset. SVG is deferred and not required for V1.
