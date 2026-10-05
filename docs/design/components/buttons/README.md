# AXION Button System V2

Status: **VISUAL LOCK / PRIMARY SHARED COMPONENT REFERENCE**.

Canonical reference: `02_button_system_v2.png`.

Home application reference: `../../screens/home/02_home_button_system_v2.png`.

Назначение: единый внешний вид кнопок native React интерфейса AXION на всех экранах и во всех диалогах/модальных окнах.

V2 supersedes Button System V1 по внешнему виду кнопок. `01_button_system_v1.png` сохраняется как предыдущий reference, но не является текущим visual authority.

Рекомендуемое направление Primary CTA: **Graphite + Emerald Border** — спокойная тёмная кнопка с emerald accent, без яркой сплошной зелёной заливки.

Базовая геометрия: 44 px height/min-height, 18 px horizontal padding, 12 px radius, 16 px icon, 10 px icon-text gap, 15 px Semibold, border 1 px.

Система ролей: `Primary`, `Secondary`, `Tertiary / Ghost`, `Back`, `Destructive`, `Disabled`; состояния: Default / Hover / Pressed / Focus / Disabled.

Primary/Secondary/Tertiary выбираются по роли действия в конкретном UX-состоянии, а не по буквальному тексту на component sheet. По умолчанию ширина content-based; full-width допустим только если этого требует layout.

V2 применяется одинаково в основных экранах, footer actions, cards, confirmation dialogs и native modal. Не допускаются отдельные локальные стили кнопок без явного нового visual decision.

Component lock определяет visual treatment. Routing, доступность действий, backend gates, state transitions и scientific semantics остаются в соответствующих UX/backend contracts.
