# Result Interpreter V2 — UX / Architecture Lock

Status: **ACCEPTED / IMPLEMENTATION PENDING**

Canonical visual reference:
`docs/design/screens/result/06_result_object_detail_llm_v2.png`

Этот документ — компактный источник решений для native React/FastAPI Result Interpreter. Историческая Streamlit-реализация и старые LLM PNG не определяют новый product path.

## 1. Canonical flow

```text
Object Detail + validated Local SHAP
→ explicit user action
→ 4 independent role interpretations
→ MASTER = выбор роли + status
→ DETAIL = один читаемый response
→ Copy / PDF / Print
```

Роли:
- `sales_manager` — Менеджер по продажам;
- `credit_controller` — Кредитный контролёр;
- `lawyer` — Юрист;
- `information_security` — Информационная безопасность.

Четыре длинных explanation одновременно не показываются.
## 2. UI state

`selectedRole` — transient state Object Detail, default `sales_manager`. Он не хранится в URL, NativeSession или artifact. Переключение роли не вызывает LLM и не отменяет запросы других ролей.

На каждую роль независимо:
`IDLE / LOADING / READY / ERROR`.

Действия:
- IDLE → `Сформировать объяснение`;
- ERROR → `Повторить`;
- READY → `Сформировать заново`, `Копировать`, `Экспортировать ▾`;
- LOADING → progress, generation actions disabled.

Failed regenerate не уничтожает предыдущий READY response: старый текст остаётся, рядом показывается transient action-error.

Reload/unmount не восстанавливает LLM responses и не запускает provider автоматически. Не добавлять localStorage, NativeSession persistence или artifact persistence без отдельного решения.

## 3. Bulk

`Сформировать все объяснения` — один explicit user action, который запускает независимые role requests только для IDLE/ERROR.

READY и LOADING не перезапускаются. Ошибка одной роли не отменяет остальные. Отдельный bulk backend endpoint в V1 не нужен.
## 4. Reading layout

Desktop: `MASTER | DETAIL`. Master имеет ограниченную ширину; detail получает основную ширину.

Narrow viewport: вертикальный список ролей сверху, detail ниже на всю ширину.

Explanation использует natural expansion + page scroll. Запрещены fixed-height textbox, nested scroll основного текста и horizontal text scroll.

Actions находятся только в right detail panel; master показывает icon, role name, short purpose и status.

## 5. Export V1

READY role получает `Экспортировать ▾`:
- `Скачать PDF`;
- `Распечатать`.

Также READY содержит отдельное действие `Копировать`.

`Экспортировать все` в V1 не входит.

PDF создаётся на frontend из уже полученных trusted public DTO через отдельный document view model. Это не screenshot DOM и не новый provider call.

Print использует тот же document view model, CSS print presentation и `window.print()`; отдельный frontend route не нужен.
PDF/Print одной выбранной READY роли содержат только доступные trusted public facts:
- AXION;
- `identifier_display`;
- model identity/version, если они уже есть в public Result context;
- OOF model score;
- роль;
- explanation text;
- `created_at` из ResultInterpreterResponse;
- disclaimer: LLM explanation основано на проверенном результате модели и SHAP, не является отдельным прогнозом или автоматическим решением.

Не включать prompt, API key, raw provenance, provider internals или UI chrome. `response_hash` допустим только как secondary technical metadata.

## 6. Backend boundary

Native V1 contract:

```text
POST /api/v1/result/objects/{object_id}/interpretations/{role}
```

Browser задаёт только route object identity и role. Он не отправляет SHAP payload, artifact_id, threshold, provider или prepared request.
Backend сам выполняет trusted chain:

```text
current session
→ current artifact_id
→ OOFExplanationService.local(artifact_id, object_id)
→ trusted LocalExplanationEvidence
→ IntegrationWorkflowService.prepare_interpretation(..., recipient_role=role)
→ REDACTED_V1
→ IntegrationWorkflowService.interpret(...)
→ safe ResultInterpreterResponse projection
```

Использовать существующие core/runtime части; не создавать второй interpreter pipeline.

Result Interpreter остаётся interpreter, не predictor. Role/generate/regenerate/export не меняют score, threshold, TP/TN/FP/FN или SHAP. Provider call разрешён только existing runtime policy/capability. `REDACTED_V1` не расширять ради UI.

## 7. Visual authority

Canonical active:
`06_result_object_detail_llm_v2.png`.

Non-canonical historical refs:
- `06_result_object_detail_llm_v1.png`;
- `11_result_object_detail_llm_loading_v1.png`;
- `12_result_object_detail_llm_error_v1.png`.

Физически их пока не перемещать и не удалять. После implementation/review — отдельный docs-cleanup в archive.
## 8. Implementation order

1. **RI-BE** — role-specific FastAPI contract поверх trusted Local SHAP + existing IntegrationWorkflowService.
2. **RI-UI** — master/detail, per-role lifecycle, individual actions, bulk orchestration, Copy.
3. **RI-EXPORT** — PDF + Print.

Каждый этап отдельно reviewable; export не должен блокировать или усложнять базовую генерацию interpretation.

## Developer MUST NOT decide

Не менять самостоятельно:
- master/detail обратно на 4 text columns;
- selected role ownership;
- auto-LLM on open/role switch;
- per-role lifecycle или bulk semantics;
- successful-response retention on failed regenerate;
- actions одновременно в master и detail;
- nested explanation scroll;
- icon-only export;
- backend-generated/repeated-LLM PDF;
- Export All;
- LLM persistence;
- browser-trusted SHAP;
- scientific Result/SHAP contracts.

## Acceptance

Реализация считается соответствующей lock, если exact trusted object/SHAP binding остаётся backend-owned, provider вызывается только по explicit user action, четыре роли независимы, один detail response читается без nested scroll, Copy/PDF/Print не меняют evidence и не вызывают LLM повторно.
