# AXION documentation

## Порядок чтения по умолчанию

1. [`PROJECT_MAP.md`](PROJECT_MAP.md) — текущая точка проекта, canonical product path и NEXT.
2. [`CURRENT_STATE.md`](CURRENT_STATE.md) — компактный актуальный контекст и устойчивые инварианты.
3. Только документ, непосредственно относящийся к текущей задаче.
4. Код, diff или artifact как фактическое evidence.

## Не читать по умолчанию

Не загружайте целиком всю `docs/`, `history/`, `ROADMAP.md`, `DECISIONS.md`, `RESEARCH_RECORD.md` или все workstreams.

Если нужен старый факт: найдите его поиском, прочитайте небольшой диапазон вокруг совпадения и расширьте его только при необходимости. Исторические документы хранят evidence, но не переопределяют текущий NEXT.

## Правило для Coordinator / Codex / Reviewer

Если implementation/review task перечисляет документы, читать только их. Не проводить широкий аудит документации или репозитория, если задача явно этого не требует. Проверять фактические изменения по нужным коду, diff и artifacts.

Не восстанавливать актуальное состояние проекта по истории чатов или памяти, если доступны `PROJECT_MAP.md`, `CURRENT_STATE.md` и repository evidence.

## Источник истины

[`PROJECT_MAP.md`](PROJECT_MAP.md) определяет текущую продуктовую точку, canonical frontend path и NEXT. Исторические записи не меняют NEXT. `CURRENT_STATE.md` — краткая актуальная сводка; полная прежняя версия доступна в [`history/CURRENT_STATE_FULL_2026-10-01.md`](history/CURRENT_STATE_FULL_2026-10-01.md) и читается только при конкретной необходимости.