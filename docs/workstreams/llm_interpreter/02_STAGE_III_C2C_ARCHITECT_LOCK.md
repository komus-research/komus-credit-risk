# ARCHITECT LOCK — Stage III-C2c Role-Based Result Interpretation

Дата: 2026-09-25

## STATUS

`READY_FOR_IMPLEMENTATION`

Основание:

- Stage III-C2a / External Data Boundary — ACCEPTED;
- Stage III-C2b / Runtime + Streamlit Integration — ACCEPTED;
- manual E2E подтвердил реальный OpenAI path через `REDACTED_V1`;
- Stage 20 V1 / Role-Based Result Interpreter — ACCEPTED research evidence.

## PROBLEM

Текущий product UI подключает только один общий Result Interpreter response.
Это технически работает, но продуктово теряет принятую Stage 20 семантику:

- нет `recipient_role`;
- один и тот же ML result не адаптируется для четырёх рабочих ролей;
- Streamlit вызывает `prepare_interpretation(evidence=evidence)` без trusted feature descriptions;
- поэтому provider получает technical names вроде `B3_norm` без предметного смысла и вынужден явно сообщать, что описания признаков отсутствуют.

Manual E2E 2026-09-25 считается:

- runtime/provider/REDACTED_V1 path — PASS;
- role-based interpretation UX — GAP;
- trusted feature-description propagation — GAP.

Stage III-C2b ACCEPT не отменяется.

## ACCEPTED SOURCE

Ролевой contract берётся из accepted Stage 20 V1:

1. `sales_manager` — менеджер по продажам;
2. `credit_controller` — кредитный контролёр;
3. `lawyer` — юрист;
4. `information_security` — информационная безопасность.

Stage 20 доказал только role adaptation уже рассчитанного ML result. Его synthetic threshold/`ml_decision` contract НЕ переносится автоматически в product runtime.

## ARCHITECTURAL DECISION

Канонический flow C2c:

```text
PredictionBatch
  ↓
selected row
  ↓
LocalExplanationEvidence
  ↓
trusted FeatureSpec descriptions from saved ModelVersion
  ↓
ResultInterpreterRequest + recipient_role
  ↓
REDACTED_V1 allowlist projection
  ↓
provider
  ↓
role-specific Russian explanation
```

Один ML result может иметь до четырёх независимых interpretation responses — по одной на каждую роль.

## ROLE SEMANTICS

### sales_manager

Цель: коротко и понятным деловым языком объяснить, что показала модель и какие факторы сильнее всего повлияли на оценку.

Не перегружать SHAP/internal terminology, если её можно выразить обычными словами.

Не формулировать кредитное решение.

### credit_controller

Цель: показать probability, основные повышающие/понижающие факторы, ограничения интерпретации и отсутствие причинного вывода.

Не выбирать threshold и не выводить approve/reject.

### lawyer

Цель: отделить model facts от interpretation, явно назвать ограничения, provenance и отсутствие причинности/самостоятельного юридического решения.

Не делать нормативных или юридических выводов сверх входных фактов.

### information_security

Цель: объяснить data-sharing boundary текущего вызова.

Разрешено описывать только фактически применённую runtime policy:

- `REDACTED_V1`;
- наружу не передаются identifier value, row identity и raw feature values;
- передаются только allowlisted обезличенные model facts;
- `store=false` не трактуется как Zero Data Retention.

## TRUSTED FEATURE DESCRIPTIONS

Источник человекочитаемого смысла признака — только immutable `FeatureSpec`, сохранённый внутри active `ModelVersion.metadata["feature_specs"]`.

Для каждого top feature допустимо использовать:

- `display_name_ru`;
- `description_ru`.

Frontend не придумывает descriptions и не поддерживает отдельный словарь.

Если trusted description отсутствует/является generic technical placeholder, LLM обязан использовать technical column name и прямо не придумывать business meaning.

## OUTBOUND BOUNDARY

`REDACTED_V1` остаётся positive allowlist.

Наружу НЕ передаются:

- identifier column/value;
- row id/source position;
- raw feature values;
- raw model output/base value;
- model/dataset provenance beyond fields explicitly allowed by policy.

В C2c разрешается добавить в allowlist:

- `recipient_role`;
- trusted `display_name_ru`;
- trusted `description_ru`;

при условии, что это metadata признаков, а не client row data.

## SESSION STATE

Interpretation state становится role-keyed.

Conceptually:

```text
requests_by_role
responses_by_role
dispatch_receipts_by_role
errors_by_role
```

Изменение selected row / prediction batch / LocalExplanationEvidence очищает все role responses downstream.

Ошибка одной роли не должна очищать:

- ModelVersion;
- PredictionBatch;
- selected row;
- Local SHAP;
- успешные ответы других ролей.

## UI CONTRACT

После Local SHAP показывается блок:

`Объяснение для разных ролей`

Внутри — четыре понятные вкладки/секции:

- Менеджер по продажам
- Кредитный контролёр
- Юрист
- Информационная безопасность

Каждая роль запускается отдельно и имеет независимый retry.

C2c НЕ является общим visual redesign. Перестройка визуальной иерархии глобальных CTA-кнопок фиксируется отдельным следующим UX pass.

## NON-GOALS

Не добавлять:

- business threshold;
- approve/reject;
- `ml_decision`;
- credit policy;
- новые модели;
- новые explainers;
- новый outbound policy;
- передачу raw values;
- full Stage 20 synthetic card schema;
- общий redesign приложения.

## ACCEPTANCE CRITERIA

1. Все четыре accepted роли доступны в product UI.
2. Для одного evidence можно независимо получить четыре role-specific responses.
3. ML probability/SHAP не пересчитываются и не меняются между ролями.
4. Trusted descriptions берутся из active ModelVersion `feature_specs`, не из UI hardcode.
5. Внешний payload остаётся `REDACTED_V1` и не содержит identifier/raw values/row identity.
6. Role входит в provider payload и влияет только на форму/акценты объяснения.
7. Unknown role rejected fail-closed.
8. Failure одной роли не инвалидирует prediction/SHAP/другие role responses.
9. `DISABLED` и `MISCONFIGURED` semantics C2b не меняются.
10. Regression tests покрывают policy projection, application service, session invalidation и Streamlit role UI.
11. Full test suite, `compileall src app`, `git diff --check` — PASS.
12. Manual defense E2E выполняется минимум для двух существенно разных ролей на synthetic/non-client input и подтверждает различие explanation при неизменном ML result.

## NEXT

После C2c ACCEPT открыть отдельный UX pass для визуальной иерархии CTA/buttons на экране `Результат`.
