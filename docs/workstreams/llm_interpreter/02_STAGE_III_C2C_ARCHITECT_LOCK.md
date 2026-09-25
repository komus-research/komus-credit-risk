# ARCHITECT LOCK тАФ Stage III-C2c Role-Based Result Interpretation

╨Ф╨░╤В╨░: 2026-09-25

## STATUS

`READY_FOR_IMPLEMENTATION`

╨Ю╤Б╨╜╨╛╨▓╨░╨╜╨╕╨╡:

- Stage III-C2a / External Data Boundary тАФ ACCEPTED;
- Stage III-C2b / Runtime + Streamlit Integration тАФ ACCEPTED;
- manual E2E ╨┐╨╛╨┤╤В╨▓╨╡╤А╨┤╨╕╨╗ ╤А╨╡╨░╨╗╤М╨╜╤Л╨╣ OpenAI path ╤З╨╡╤А╨╡╨╖ `REDACTED_V1`;
- Stage 20 V1 / Role-Based Result Interpreter тАФ ACCEPTED research evidence.

## PROBLEM

╨в╨╡╨║╤Г╤Й╨╕╨╣ product UI ╨┐╨╛╨┤╨║╨╗╤О╤З╨░╨╡╤В ╤В╨╛╨╗╤М╨║╨╛ ╨╛╨┤╨╕╨╜ ╨╛╨▒╤Й╨╕╨╣ Result Interpreter response.
╨н╤В╨╛ ╤В╨╡╤Е╨╜╨╕╤З╨╡╤Б╨║╨╕ ╤А╨░╨▒╨╛╤В╨░╨╡╤В, ╨╜╨╛ ╨┐╤А╨╛╨┤╤Г╨║╤В╨╛╨▓╨╛ ╤В╨╡╤А╤П╨╡╤В ╨┐╤А╨╕╨╜╤П╤В╤Г╤О Stage 20 ╤Б╨╡╨╝╨░╨╜╤В╨╕╨║╤Г:

- ╨╜╨╡╤В `recipient_role`;
- ╨╛╨┤╨╕╨╜ ╨╕ ╤В╨╛╤В ╨╢╨╡ ML result ╨╜╨╡ ╨░╨┤╨░╨┐╤В╨╕╤А╤Г╨╡╤В╤Б╤П ╨┤╨╗╤П ╤З╨╡╤В╤Л╤А╤С╤Е ╤А╨░╨▒╨╛╤З╨╕╤Е ╤А╨╛╨╗╨╡╨╣;
- Streamlit ╨▓╤Л╨╖╤Л╨▓╨░╨╡╤В `prepare_interpretation(evidence=evidence)` ╨▒╨╡╨╖ trusted feature descriptions;
- ╨┐╨╛╤Н╤В╨╛╨╝╤Г provider ╨┐╨╛╨╗╤Г╤З╨░╨╡╤В technical names ╨▓╤А╨╛╨┤╨╡ `B3_norm` ╨▒╨╡╨╖ ╨┐╤А╨╡╨┤╨╝╨╡╤В╨╜╨╛╨│╨╛ ╤Б╨╝╤Л╤Б╨╗╨░ ╨╕ ╨▓╤Л╨╜╤Г╨╢╨┤╨╡╨╜ ╤П╨▓╨╜╨╛ ╤Б╨╛╨╛╨▒╤Й╨░╤В╤М, ╤З╤В╨╛ ╨╛╨┐╨╕╤Б╨░╨╜╨╕╤П ╨┐╤А╨╕╨╖╨╜╨░╨║╨╛╨▓ ╨╛╤В╤Б╤Г╤В╤Б╤В╨▓╤Г╤О╤В.

Manual E2E 2026-09-25 ╤Б╤З╨╕╤В╨░╨╡╤В╤Б╤П:

- runtime/provider/REDACTED_V1 path тАФ PASS;
- role-based interpretation UX тАФ GAP;
- trusted feature-description propagation тАФ GAP.

Stage III-C2b ACCEPT ╨╜╨╡ ╨╛╤В╨╝╨╡╨╜╤П╨╡╤В╤Б╤П.

## ACCEPTED SOURCE

╨а╨╛╨╗╨╡╨▓╨╛╨╣ contract ╨▒╨╡╤А╤С╤В╤Б╤П ╨╕╨╖ accepted Stage 20 V1:

1. `sales_manager` тАФ ╨╝╨╡╨╜╨╡╨┤╨╢╨╡╤А ╨┐╨╛ ╨┐╤А╨╛╨┤╨░╨╢╨░╨╝;
2. `credit_controller` тАФ ╨║╤А╨╡╨┤╨╕╤В╨╜╤Л╨╣ ╨║╨╛╨╜╤В╤А╨╛╨╗╤С╤А;
3. `lawyer` тАФ ╤О╤А╨╕╤Б╤В;
4. `information_security` тАФ ╨╕╨╜╤Д╨╛╤А╨╝╨░╤Ж╨╕╨╛╨╜╨╜╨░╤П ╨▒╨╡╨╖╨╛╨┐╨░╤Б╨╜╨╛╤Б╤В╤М.

Stage 20 ╨┤╨╛╨║╨░╨╖╨░╨╗ ╤В╨╛╨╗╤М╨║╨╛ role adaptation ╤Г╨╢╨╡ ╤А╨░╤Б╤Б╤З╨╕╤В╨░╨╜╨╜╨╛╨│╨╛ ML result. ╨Х╨│╨╛ synthetic threshold/`ml_decision` contract ╨Э╨Х ╨┐╨╡╤А╨╡╨╜╨╛╤Б╨╕╤В╤Б╤П ╨░╨▓╤В╨╛╨╝╨░╤В╨╕╤З╨╡╤Б╨║╨╕ ╨▓ product runtime.

## ARCHITECTURAL DECISION

╨Ъ╨░╨╜╨╛╨╜╨╕╤З╨╡╤Б╨║╨╕╨╣ flow C2c:

```text
PredictionBatch
  тЖУ
selected row
  тЖУ
LocalExplanationEvidence
  тЖУ
trusted FeatureSpec descriptions from saved ModelVersion
  тЖУ
ResultInterpreterRequest + recipient_role
  тЖУ
REDACTED_V1 allowlist projection
  тЖУ
provider
  тЖУ
role-specific Russian explanation
```

╨Ю╨┤╨╕╨╜ ML result ╨╝╨╛╨╢╨╡╤В ╨╕╨╝╨╡╤В╤М ╨┤╨╛ ╤З╨╡╤В╤Л╤А╤С╤Е ╨╜╨╡╨╖╨░╨▓╨╕╤Б╨╕╨╝╤Л╤Е interpretation responses тАФ ╨┐╨╛ ╨╛╨┤╨╜╨╛╨╣ ╨╜╨░ ╨║╨░╨╢╨┤╤Г╤О ╤А╨╛╨╗╤М.

## ROLE SEMANTICS

### sales_manager

╨ж╨╡╨╗╤М: ╨║╨╛╤А╨╛╤В╨║╨╛ ╨╕ ╨┐╨╛╨╜╤П╤В╨╜╤Л╨╝ ╨┤╨╡╨╗╨╛╨▓╤Л╨╝ ╤П╨╖╤Л╨║╨╛╨╝ ╨╛╨▒╤К╤П╤Б╨╜╨╕╤В╤М, ╤З╤В╨╛ ╨┐╨╛╨║╨░╨╖╨░╨╗╨░ ╨╝╨╛╨┤╨╡╨╗╤М ╨╕ ╨║╨░╨║╨╕╨╡ ╤Д╨░╨║╤В╨╛╤А╤Л ╤Б╨╕╨╗╤М╨╜╨╡╨╡ ╨▓╤Б╨╡╨│╨╛ ╨┐╨╛╨▓╨╗╨╕╤П╨╗╨╕ ╨╜╨░ ╨╛╤Ж╨╡╨╜╨║╤Г.

╨Э╨╡ ╨┐╨╡╤А╨╡╨│╤А╤Г╨╢╨░╤В╤М SHAP/internal terminology, ╨╡╤Б╨╗╨╕ ╨╡╤С ╨╝╨╛╨╢╨╜╨╛ ╨▓╤Л╤А╨░╨╖╨╕╤В╤М ╨╛╨▒╤Л╤З╨╜╤Л╨╝╨╕ ╤Б╨╗╨╛╨▓╨░╨╝╨╕.

╨Э╨╡ ╤Д╨╛╤А╨╝╤Г╨╗╨╕╤А╨╛╨▓╨░╤В╤М ╨║╤А╨╡╨┤╨╕╤В╨╜╨╛╨╡ ╤А╨╡╤И╨╡╨╜╨╕╨╡.

### credit_controller

╨ж╨╡╨╗╤М: ╨┐╨╛╨║╨░╨╖╨░╤В╤М probability, ╨╛╤Б╨╜╨╛╨▓╨╜╤Л╨╡ ╨┐╨╛╨▓╤Л╤И╨░╤О╤Й╨╕╨╡/╨┐╨╛╨╜╨╕╨╢╨░╤О╤Й╨╕╨╡ ╤Д╨░╨║╤В╨╛╤А╤Л, ╨╛╨│╤А╨░╨╜╨╕╤З╨╡╨╜╨╕╤П ╨╕╨╜╤В╨╡╤А╨┐╤А╨╡╤В╨░╤Ж╨╕╨╕ ╨╕ ╨╛╤В╤Б╤Г╤В╤Б╤В╨▓╨╕╨╡ ╨┐╤А╨╕╤З╨╕╨╜╨╜╨╛╨│╨╛ ╨▓╤Л╨▓╨╛╨┤╨░.

╨Э╨╡ ╨▓╤Л╨▒╨╕╤А╨░╤В╤М threshold ╨╕ ╨╜╨╡ ╨▓╤Л╨▓╨╛╨┤╨╕╤В╤М approve/reject.

### lawyer

╨ж╨╡╨╗╤М: ╨╛╤В╨┤╨╡╨╗╨╕╤В╤М model facts ╨╛╤В interpretation, ╤П╨▓╨╜╨╛ ╨╜╨░╨╖╨▓╨░╤В╤М ╨╛╨│╤А╨░╨╜╨╕╤З╨╡╨╜╨╕╤П, provenance ╨╕ ╨╛╤В╤Б╤Г╤В╤Б╤В╨▓╨╕╨╡ ╨┐╤А╨╕╤З╨╕╨╜╨╜╨╛╤Б╤В╨╕/╤Б╨░╨╝╨╛╤Б╤В╨╛╤П╤В╨╡╨╗╤М╨╜╨╛╨│╨╛ ╤О╤А╨╕╨┤╨╕╤З╨╡╤Б╨║╨╛╨│╨╛ ╤А╨╡╤И╨╡╨╜╨╕╤П.

╨Э╨╡ ╨┤╨╡╨╗╨░╤В╤М ╨╜╨╛╤А╨╝╨░╤В╨╕╨▓╨╜╤Л╤Е ╨╕╨╗╨╕ ╤О╤А╨╕╨┤╨╕╤З╨╡╤Б╨║╨╕╤Е ╨▓╤Л╨▓╨╛╨┤╨╛╨▓ ╤Б╨▓╨╡╤А╤Е ╨▓╤Е╨╛╨┤╨╜╤Л╤Е ╤Д╨░╨║╤В╨╛╨▓.

### information_security

╨ж╨╡╨╗╤М: ╨╛╨▒╤К╤П╤Б╨╜╨╕╤В╤М data-sharing boundary ╤В╨╡╨║╤Г╤Й╨╡╨│╨╛ ╨▓╤Л╨╖╨╛╨▓╨░.

╨а╨░╨╖╤А╨╡╤И╨╡╨╜╨╛ ╨╛╨┐╨╕╤Б╤Л╨▓╨░╤В╤М ╤В╨╛╨╗╤М╨║╨╛ ╤Д╨░╨║╤В╨╕╤З╨╡╤Б╨║╨╕ ╨┐╤А╨╕╨╝╨╡╨╜╤С╨╜╨╜╤Г╤О runtime policy:

- `REDACTED_V1`;
- ╨╜╨░╤А╤Г╨╢╤Г ╨╜╨╡ ╨┐╨╡╤А╨╡╨┤╨░╤О╤В╤Б╤П identifier value, row identity ╨╕ raw feature values;
- ╨┐╨╡╤А╨╡╨┤╨░╤О╤В╤Б╤П ╤В╨╛╨╗╤М╨║╨╛ allowlisted ╨╛╨▒╨╡╨╖╨╗╨╕╤З╨╡╨╜╨╜╤Л╨╡ model facts;
- `store=false` ╨╜╨╡ ╤В╤А╨░╨║╤В╤Г╨╡╤В╤Б╤П ╨║╨░╨║ Zero Data Retention.

## TRUSTED FEATURE DESCRIPTIONS

╨Ш╤Б╤В╨╛╤З╨╜╨╕╨║ ╤З╨╡╨╗╨╛╨▓╨╡╨║╨╛╤З╨╕╤В╨░╨╡╨╝╨╛╨│╨╛ ╤Б╨╝╤Л╤Б╨╗╨░ ╨┐╤А╨╕╨╖╨╜╨░╨║╨░ тАФ ╤В╨╛╨╗╤М╨║╨╛ immutable `FeatureSpec`, ╤Б╨╛╤Е╤А╨░╨╜╤С╨╜╨╜╤Л╨╣ ╨▓╨╜╤Г╤В╤А╨╕ active `ModelVersion.metadata["feature_specs"]`.

╨Ф╨╗╤П ╨║╨░╨╢╨┤╨╛╨│╨╛ top feature ╨┤╨╛╨┐╤Г╤Б╤В╨╕╨╝╨╛ ╨╕╤Б╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╤М:

- `display_name_ru`;
- `description_ru`.

Frontend ╨╜╨╡ ╨┐╤А╨╕╨┤╤Г╨╝╤Л╨▓╨░╨╡╤В descriptions ╨╕ ╨╜╨╡ ╨┐╨╛╨┤╨┤╨╡╤А╨╢╨╕╨▓╨░╨╡╤В ╨╛╤В╨┤╨╡╨╗╤М╨╜╤Л╨╣ ╤Б╨╗╨╛╨▓╨░╤А╤М.

╨Х╤Б╨╗╨╕ trusted description ╨╛╤В╤Б╤Г╤В╤Б╤В╨▓╤Г╨╡╤В/╤П╨▓╨╗╤П╨╡╤В╤Б╤П generic technical placeholder, LLM ╨╛╨▒╤П╨╖╨░╨╜ ╨╕╤Б╨┐╨╛╨╗╤М╨╖╨╛╨▓╨░╤В╤М technical column name ╨╕ ╨┐╤А╤П╨╝╨╛ ╨╜╨╡ ╨┐╤А╨╕╨┤╤Г╨╝╤Л╨▓╨░╤В╤М business meaning.

## OUTBOUND BOUNDARY

`REDACTED_V1` ╨╛╤Б╤В╨░╤С╤В╤Б╤П positive allowlist.

╨Э╨░╤А╤Г╨╢╤Г ╨Э╨Х ╨┐╨╡╤А╨╡╨┤╨░╤О╤В╤Б╤П:

- identifier column/value;
- row id/source position;
- raw feature values;
- raw model output/base value;
- model/dataset provenance beyond fields explicitly allowed by policy.

╨Т C2c ╤А╨░╨╖╤А╨╡╤И╨░╨╡╤В╤Б╤П ╨┤╨╛╨▒╨░╨▓╨╕╤В╤М ╨▓ allowlist:

- `recipient_role`;
- trusted `display_name_ru`;
- trusted `description_ru`;

╨┐╤А╨╕ ╤Г╤Б╨╗╨╛╨▓╨╕╨╕, ╤З╤В╨╛ ╤Н╤В╨╛ metadata ╨┐╤А╨╕╨╖╨╜╨░╨║╨╛╨▓, ╨░ ╨╜╨╡ client row data.

## SESSION STATE

Interpretation state ╤Б╤В╨░╨╜╨╛╨▓╨╕╤В╤Б╤П role-keyed.

Conceptually:

```text
requests_by_role
responses_by_role
dispatch_receipts_by_role
errors_by_role
```

╨Ш╨╖╨╝╨╡╨╜╨╡╨╜╨╕╨╡ selected row / prediction batch / LocalExplanationEvidence ╨╛╤З╨╕╤Й╨░╨╡╤В ╨▓╤Б╨╡ role responses downstream.

╨Ю╤И╨╕╨▒╨║╨░ ╨╛╨┤╨╜╨╛╨╣ ╤А╨╛╨╗╨╕ ╨╜╨╡ ╨┤╨╛╨╗╨╢╨╜╨░ ╨╛╤З╨╕╤Й╨░╤В╤М:

- ModelVersion;
- PredictionBatch;
- selected row;
- Local SHAP;
- ╤Г╤Б╨┐╨╡╤И╨╜╤Л╨╡ ╨╛╤В╨▓╨╡╤В╤Л ╨┤╤А╤Г╨│╨╕╤Е ╤А╨╛╨╗╨╡╨╣.

## UI CONTRACT

╨Я╨╛╤Б╨╗╨╡ Local SHAP ╨┐╨╛╨║╨░╨╖╤Л╨▓╨░╨╡╤В╤Б╤П ╨▒╨╗╨╛╨║:

`╨Ю╨▒╤К╤П╤Б╨╜╨╡╨╜╨╕╨╡ ╨┤╨╗╤П ╤А╨░╨╖╨╜╤Л╤Е ╤А╨╛╨╗╨╡╨╣`

╨Т╨╜╤Г╤В╤А╨╕ тАФ ╤З╨╡╤В╤Л╤А╨╡ ╨┐╨╛╨╜╤П╤В╨╜╤Л╨╡ ╨▓╨║╨╗╨░╨┤╨║╨╕/╤Б╨╡╨║╤Ж╨╕╨╕:

- ╨Ь╨╡╨╜╨╡╨┤╨╢╨╡╤А ╨┐╨╛ ╨┐╤А╨╛╨┤╨░╨╢╨░╨╝
- ╨Ъ╤А╨╡╨┤╨╕╤В╨╜╤Л╨╣ ╨║╨╛╨╜╤В╤А╨╛╨╗╤С╤А
- ╨о╤А╨╕╤Б╤В
- ╨Ш╨╜╤Д╨╛╤А╨╝╨░╤Ж╨╕╨╛╨╜╨╜╨░╤П ╨▒╨╡╨╖╨╛╨┐╨░╤Б╨╜╨╛╤Б╤В╤М

╨Ъ╨░╨╢╨┤╨░╤П ╤А╨╛╨╗╤М ╨╖╨░╨┐╤Г╤Б╨║╨░╨╡╤В╤Б╤П ╨╛╤В╨┤╨╡╨╗╤М╨╜╨╛ ╨╕ ╨╕╨╝╨╡╨╡╤В ╨╜╨╡╨╖╨░╨▓╨╕╤Б╨╕╨╝╤Л╨╣ retry.

C2c ╨Э╨Х ╤П╨▓╨╗╤П╨╡╤В╤Б╤П ╨╛╨▒╤Й╨╕╨╝ visual redesign. ╨Я╨╡╤А╨╡╤Б╤В╤А╨╛╨╣╨║╨░ ╨▓╨╕╨╖╤Г╨░╨╗╤М╨╜╨╛╨╣ ╨╕╨╡╤А╨░╤А╤Е╨╕╨╕ ╨│╨╗╨╛╨▒╨░╨╗╤М╨╜╤Л╤Е CTA-╨║╨╜╨╛╨┐╨╛╨║ ╤Д╨╕╨║╤Б╨╕╤А╤Г╨╡╤В╤Б╤П ╨╛╤В╨┤╨╡╨╗╤М╨╜╤Л╨╝ ╤Б╨╗╨╡╨┤╤Г╤О╤Й╨╕╨╝ UX pass.

## NON-GOALS

╨Э╨╡ ╨┤╨╛╨▒╨░╨▓╨╗╤П╤В╤М:

- business threshold;
- approve/reject;
- `ml_decision`;
- credit policy;
- ╨╜╨╛╨▓╤Л╨╡ ╨╝╨╛╨┤╨╡╨╗╨╕;
- ╨╜╨╛╨▓╤Л╨╡ explainers;
- ╨╜╨╛╨▓╤Л╨╣ outbound policy;
- ╨┐╨╡╤А╨╡╨┤╨░╤З╤Г raw values;
- full Stage 20 synthetic card schema;
- ╨╛╨▒╤Й╨╕╨╣ redesign ╨┐╤А╨╕╨╗╨╛╨╢╨╡╨╜╨╕╤П.

## ACCEPTANCE CRITERIA

1. ╨Т╤Б╨╡ ╤З╨╡╤В╤Л╤А╨╡ accepted ╤А╨╛╨╗╨╕ ╨┤╨╛╤Б╤В╤Г╨┐╨╜╤Л ╨▓ product UI.
2. ╨Ф╨╗╤П ╨╛╨┤╨╜╨╛╨│╨╛ evidence ╨╝╨╛╨╢╨╜╨╛ ╨╜╨╡╨╖╨░╨▓╨╕╤Б╨╕╨╝╨╛ ╨┐╨╛╨╗╤Г╤З╨╕╤В╤М ╤З╨╡╤В╤Л╤А╨╡ role-specific responses.
3. ML probability/SHAP ╨╜╨╡ ╨┐╨╡╤А╨╡╤Б╤З╨╕╤В╤Л╨▓╨░╤О╤В╤Б╤П ╨╕ ╨╜╨╡ ╨╝╨╡╨╜╤П╤О╤В╤Б╤П ╨╝╨╡╨╢╨┤╤Г ╤А╨╛╨╗╤П╨╝╨╕.
4. Trusted descriptions ╨▒╨╡╤А╤Г╤В╤Б╤П ╨╕╨╖ active ModelVersion `feature_specs`, ╨╜╨╡ ╨╕╨╖ UI hardcode.
5. ╨Т╨╜╨╡╤И╨╜╨╕╨╣ payload ╨╛╤Б╤В╨░╤С╤В╤Б╤П `REDACTED_V1` ╨╕ ╨╜╨╡ ╤Б╨╛╨┤╨╡╤А╨╢╨╕╤В identifier/raw values/row identity.
6. Role ╨▓╤Е╨╛╨┤╨╕╤В ╨▓ provider payload ╨╕ ╨▓╨╗╨╕╤П╨╡╤В ╤В╨╛╨╗╤М╨║╨╛ ╨╜╨░ ╤Д╨╛╤А╨╝╤Г/╨░╨║╤Ж╨╡╨╜╤В╤Л ╨╛╨▒╤К╤П╤Б╨╜╨╡╨╜╨╕╤П.
7. Unknown role rejected fail-closed.
8. Failure ╨╛╨┤╨╜╨╛╨╣ ╤А╨╛╨╗╨╕ ╨╜╨╡ ╨╕╨╜╨▓╨░╨╗╨╕╨┤╨╕╤А╤Г╨╡╤В prediction/SHAP/╨┤╤А╤Г╨│╨╕╨╡ role responses.
9. `DISABLED` ╨╕ `MISCONFIGURED` semantics C2b ╨╜╨╡ ╨╝╨╡╨╜╤П╤О╤В╤Б╤П.
10. Regression tests ╨┐╨╛╨║╤А╤Л╨▓╨░╤О╤В policy projection, application service, session invalidation ╨╕ Streamlit role UI.
11. Full test suite, `compileall src app`, `git diff --check` тАФ PASS.
12. Manual defense E2E ╨▓╤Л╨┐╨╛╨╗╨╜╤П╨╡╤В╤Б╤П ╨╝╨╕╨╜╨╕╨╝╤Г╨╝ ╨┤╨╗╤П ╨┤╨▓╤Г╤Е ╤Б╤Г╤Й╨╡╤Б╤В╨▓╨╡╨╜╨╜╨╛ ╤А╨░╨╖╨╜╤Л╤Е ╤А╨╛╨╗╨╡╨╣ ╨╜╨░ synthetic/non-client input ╨╕ ╨┐╨╛╨┤╤В╨▓╨╡╤А╨╢╨┤╨░╨╡╤В ╤А╨░╨╖╨╗╨╕╤З╨╕╨╡ explanation ╨┐╤А╨╕ ╨╜╨╡╨╕╨╖╨╝╨╡╨╜╨╜╨╛╨╝ ML result.

## NEXT

╨Я╨╛╤Б╨╗╨╡ C2c ACCEPT ╨╛╤В╨║╤А╤Л╤В╤М ╨╛╤В╨┤╨╡╨╗╤М╨╜╤Л╨╣ UX pass ╨┤╨╗╤П ╨▓╨╕╨╖╤Г╨░╨╗╤М╨╜╨╛╨╣ ╨╕╨╡╤А╨░╤А╤Е╨╕╨╕ CTA/buttons ╨╜╨░ ╤Н╨║╤А╨░╨╜╨╡ `╨а╨╡╨╖╤Г╨╗╤М╤В╨░╤В`.
