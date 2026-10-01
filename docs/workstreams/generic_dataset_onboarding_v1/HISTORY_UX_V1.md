# History UX V1 — Product / Architecture / Visual Lock

Status: **PH-BE1 ACCEPTED / CLOSED — NATIVE REACT/FASTAPI UI PENDING**

Visual source of truth:
`docs/design/screens/history/01_analysis_history_v1.png`

## 1. Product decision

В V1 отдельной domain-сущности `Project` нет.

Sidebar-пункт называется **«История»** и открывает read-only каталог завершённых experiment runs.

Одна запись History = один опубликованный immutable `ExperimentArtifact` / один завершённый experiment run.

`HistoryEntry` — только application read-проекция существующего artifact, а не новая persisted scientific сущность.

History отвечает на вопрос:

> Какие анализы я уже выполнял и какой OOF Result тогда получил?

Раздел `Модели` остаётся отдельным и отвечает за сохранённые `ModelVersion` и их дальнейшее использование.
## 2. Canonical relationships

```text
Dataset
  → Experiment run
    → ExperimentArtifact
      → ExperimentResult / OOF Result
        → optional ModelVersion(s)
          → SavedModelInferenceResult(s)
```

В History V1 входит только `ExperimentArtifact + ExperimentResult`.

Не являются отдельными History entries:
- `ModelVersion` — живёт в разделе «Модели»;
- `SavedModelInferenceResult` — operational flow сохранённой модели;
- Dataset — только provenance;
- текущая незавершённая session — только «Продолжить текущий анализ».

Historical Result открывается по exact `artifact_id` и не заменяет текущую analysis session.

Запрещено незаметно подменять historical evidence текущим dataset, latest ModelVersion, новой model config или пересчитанными metrics.
## 3. Public application boundary

Для V1 нужен trusted read boundary:

```text
AnalysisHistoryService.list(
    offset,
    limit,
    search=None,
    model_id=None,
    sort="CREATED_DESC",
) -> AnalysisHistoryPage

AnalysisHistoryService.detail(
    artifact_id,
) -> AnalysisHistoryDetail
```

`list()` даёт каталог. `detail()` даёт immutable historical summary и режим доступа к Result.

Минимальный list item:
- `artifact_id`, `result_id`;
- `created_at`;
- `dataset_name`, `dataset_id`;
- `model_id`, `model_version`;
- `feature_count`, `folds`, `evaluation_level`;
- `gini`;
- `result_access`.

Дата берётся из `ExperimentResult.created_at`, не из filesystem mtime.
UI не сканирует artifact directories.
## 4. Result access

Поддерживаются два честных режима:

```text
FULL_RESULT_V2
LEGACY_SUMMARY_ONLY
```

`FULL_RESULT_V2` — Artifact V3; открывается существующий Result V2 через принятые `OOFResultService` / `OOFExplanationService` boundaries.

`LEGACY_SUMMARY_ONLY` — старый artifact; показывается только реально сохранённая immutable сводка: dataset, algorithm, OOF metrics, folds, limitations и technical identity.

Для legacy запрещено придумывать Object List V2, Local SHAP, Global OOF SHAP или автоматически пересчитывать experiment для миграции в V3.

History persistence отдельно не создаётся. Допустим trusted store-level browse primitive, но artifact store остаётся source of truth.

## 5. History screen

Visual lock: `01_analysis_history_v1.png`.

Экран «История анализов» показывает:
- дату;
- данные;
- алгоритм;
- число признаков;
- OOF-проверку / folds;
- Gini;
- доступ: «Полный результат» или «Только сводка»;
- действие «Открыть результат» / «Открыть сводку».
Поиск V1 разрешён только по `dataset_name` и model display/id.

Default sort: `created_at DESC`.

Обычная pagination допустима: это каталог analyses, а не object table на сотни тысяч строк.

Открытие сохранённого результата не меняет текущий analysis state.

Не использовать действие «Продолжить анализ» для historical artifact: ExperimentArtifact не является сохранённой wizard session.

## 6. Out of scope V1

Не вводим:
- `Project` entity или Project Detail;
- project naming, notes, tags, folders, favourites;
- archive/delete;
- teams/users/permissions;
- DB или отдельный History store;
- activity/event log;
- failed-job history;
- inference history duplication;
- ModelVersion duplication;
- «создать новый анализ на основе» без отдельного trusted reconstruction contract;
- automatic migration legacy artifacts в V3.

## 7. Implementation order

1. Visual Lock — **ACCEPTED**.
2. `PH-BE1` — trusted browse/list + `AnalysisHistoryService.list/detail` — **ACCEPTED / CLOSED**, source commit `4a7d016a`.
3. Commit `35aba684` реализовал History Catalog только в frozen compatibility Streamlit frontend. Он сохраняется как compatibility implementation, но НЕ считается native product UI completion.
4. Native History Catalog для React/FastAPI — **PENDING**.
5. Native historical Result opening — **PENDING** и должен использовать тот же canonical native artifact source, что и full experiment/result.

PH-BE1 дополнительно фиксирует lightweight metadata browse без `np.load`/fold-model load, fail-closed проверку canonical published artifact и content-addressed identity. `detail()` использует полный `store.load()` только для выбранного artifact.

Frontend lock: новые product UI stages реализуются в canonical React/TypeScript/Vite + FastAPI path. Streamlit остаётся frozen compatibility frontend, если владелец явно не решит иначе.

Глобальный раздел «Настройки» уже имеет отдельный accepted Product/Architecture/Visual Lock и не входит в History contract.
