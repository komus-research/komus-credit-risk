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

Главный source of truth для общей композиции:

`screens/home/01_home_axion_v2_candidate.png` — accepted VISUAL LOCK общего shell; имя файла историческое.

Для sidebar поверх Home V2 действует более новый shared-component lock:

`components/sidebar/01_sidebar_final_v1.png`.

Он фиксирует фирменный волновой/точечный motif, плотность, иконки и active-state. Демонстрационная карточка пользователя внизу этого PNG исключена из принятого contract: до отдельного auth/users workstream нельзя показывать выдуманные avatar/name/role/profile/login.

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
- История
- Настройки

Во flow нового анализа сохраняется верхний stepper:

`Данные → Признаки → Алгоритм → Проверка качества → Результат`

Навигация не должна менять scientific state без явного действия пользователя.

До отдельного authentication/users workstream sidebar не показывает fake user profile: avatar, имя, роль пользователя, profile menu, login/logout не являются частью V1 shell. Нижняя зона sidebar остаётся неинтерактивной брендовой областью; точный auth UI появится только после отдельного контракта.

Canonical navigation IA остаётся `Главная / Новый анализ / Модели / История / Настройки`; демонстрационные подписи вроде `Проекты / История` не создают новую domain-сущность или route.

## 5.1. Система кнопок

Canonical shared-component visual lock:

`components/buttons/02_button_system_v2.png`

Статус: **VISUAL LOCK / PRIMARY SHARED COMPONENT REFERENCE**. Button System V2 supersedes V1 по visual treatment; V1 сохраняется как previous reference.

Button System V2 применяется последовательно на native React экранах и в confirmation/native modal. Роли: `Primary`, `Secondary`, `Tertiary / Ghost`, `Back`, `Destructive`, `Disabled`. Состояния: Default / Hover / Pressed / Focus / Disabled.

Базовая геометрия из visual lock:

- height / min-height: `44 px`;
- horizontal padding: `18 px`;
- border radius: `12 px`;
- icon: `16 px`;
- gap icon → text: `10 px`;
- typography: `15 px`, Semibold;
- border: `1 px`;
- subtle shadow/glow: `0 2px 8px rgba(16, 185, 129, 0.15)`;
- focus ring: `0 0 0 2px rgba(16, 185, 129, 0.5)`.

Canonical Primary direction — **Graphite + Emerald Border**: заметный emerald accent без яркой сплошной зелёной плитки. Кнопки по умолчанию content-based по ширине; full-width допустим только когда этого требует layout.

Класс кнопки определяется **ролью действия в текущем состоянии экрана**, а не текстом примера на component sheet. На одном action level не должно быть нескольких конкурирующих Primary без отдельного UX-решения.

Component visual lock определяет внешний вид, но не меняет routing, доступность действия, backend gate или scientific semantics. Если старый screen PNG показывает кнопку иначе, чем Button System V2, сохранить композицию и смысл экрана, а внешний вид кнопки брать из Button System V2.

## 5.2. Long Operations

Canonical shared-component reference:

`components/long-operations/01_long_operations_v1.png`.

Различаются два базовых режима:

- `LOADING` — чтение уже существующего state/result; показывает title/message и indeterminate AXION indicator, без elapsed/stage/percent/ETA;
- `RUNNING_LONG_OPERATION` — реальная длительная backend-операция; может показывать только фактически известные stage, elapsed и discrete units/folds.

Training показывает реальные folds/stages и elapsed. Folds не переводятся автоматически в overall percentage. Fake ETA и smooth 0–100% запрещены. Если backend позже публикует точные determinate units, UI может показать их как реальные processed/total, не выдавая за ETA.

`ERROR` должен завершать loading и давать стабильное понятное состояние; `READY/COMPLETED` — короткий переход к следующему доступному действию.

## 5.3. Data Confirmation / Quality density

Canonical screen locks:

- `screens/new-analysis/02_data_confirmation_v2.png`;
- `screens/new-analysis/05_quality_v2.png`.

Оба экрана используют более плотный desktop rhythm. Уменьшение выполняется реальными typography/gap/padding/card-height значениями, а не `transform: scale()`. На Quality secondary controls (`Дополнительные настройки`, `Технические сведения`) остаются визуально вторичными и компактными.

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
3. Accepted shared-component visual lock — истина для внешнего вида соответствующего общего компонента; в текущем наборе это Buttons, Data Warnings, Sidebar и Long Operations.
4. Конкретный PNG screen reference — истина для композиции и визуальной иерархии экрана; для Confirmation и Quality основными являются V2 refs.
5. Этот Design System — истина для общего визуального языка.
6. Brandbook — истина для бренда, логотипа, цветов и ограничений.

Если источники конфликтуют, Developer не принимает решение самостоятельно: STOP и сообщает точное расхождение.

## 11. Итерационный режим

V1 реализуется максимально близко к утверждённым референсам. После просмотра реального приложения владелец может давать мелкие визуальные корректировки. Такие корректировки не должны автоматически менять backend/UX semantics.


## 12. Production assets V1

Approved implementation assets are already prepared under `app/assets/`. The home page should use the wide `home-hero-banner.webp` (or PNG when lossless source is needed) and the dark-UI AXION logo. Favicon and app icon are generated from the approved square brand asset. SVG is deferred and not required for V1.
