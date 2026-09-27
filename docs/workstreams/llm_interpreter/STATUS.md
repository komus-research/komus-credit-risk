# LLM Result Interpreter

PHASE: ACCEPTED / HANDOFF

## PURPOSE

Интерпретировать уже рассчитанные ML-результаты и Local SHAP без участия LLM в расчёте риска или кредитном решении.

## ACCEPTED

- Stage 20 V1 — ролевой прототип Result Interpreter;
- Stage III-A — Result Interpreter Core V1;
- Stage III-B — OpenAI adapter V1;
- Stage III-C2a — External Data Boundary / `REDACTED_V1`;
- Stage III-C2b — Runtime + Streamlit Integration;
- Stage III-C2c — Role-Based Result Interpretation Integration.

## CURRENT STATE

В продукте доступны четыре независимые роли: менеджер по продажам, кредитный контролёр, юрист и информационная безопасность.

Каждая роль запускается отдельным UI action и имеет независимый retry.

LLM получает только allowlisted обезличенные модельные факты через `REDACTED_V1`. Identifier, row identity и raw feature values наружу не передаются.

Trusted `display_name_ru` / `description_ru` берутся из сохранённого `ModelVersion.metadata["feature_specs"]`.

## VERIFICATION

- full suite: 255 tests PASS;
- `compileall src app` — PASS;
- `git diff --check` — PASS;
- manual external E2E на synthetic/non-client input для `sales_manager` и `lawyer` — PASS;
- ответы двух ролей различаются при неизменном ML result — PASS;
- identifier / row identity / raw values отсутствуют в provider-safe payload — PASS.

## NEXT

Ярослав отдельно проверяет качество четырёх LLM-объяснений и фактический расход API.

Отдельный следующий product workstream — UX polish экрана `Результат` и финальная упаковка материалов для защиты.

## READ FIRST

- `docs/workstreams/llm_interpreter/02_STAGE_III_C2C_ARCHITECT_LOCK.md`
- `docs/CURRENT_STATE.md`
- `docs/DECISIONS.md`
- `docs/ROADMAP.md`
