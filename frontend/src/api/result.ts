export type ResultFoldMetric = {
  fold: number
  roc_auc: number
  gini: number
  pr_auc: number
  recall_at_0_5: number
}

export type ResultSummary = {
  artifact_id: string
  result_id: string
  model_id: string
  model_version: string
  object_count: number
  feature_count: number
  folds: number
  evaluation_level: string
  runtime_seconds: number | null
  gini: number
  roc_auc: number
  pr_auc: number
  fold_metrics: ResultFoldMetric[]
  limitations: string[]
}

export type ThresholdMetrics = {
  threshold: number
  tp: number
  tn: number
  fp: number
  fn: number
  precision: number
  recall: number
  f1: number
  above_threshold_count: number
  above_threshold_share: number
}

export type ResultCapturePoint = {
  object_share: number
  event_share: number
}

export type ResultCapture = {
  total_positive_events: number
  points: ResultCapturePoint[]
  marker: ResultCapturePoint | null
}

export type SavedModel = {
  model_version_id: string
  display_name: string
  display_version: string
  saved_at: string
  decision_threshold: number | null
  decision_threshold_state: 'USER_APPLIED' | 'NOT_SET'
}

export type ResultOverview = {
  summary: ResultSummary
  threshold: ThresholdMetrics
  capture: ResultCapture
  saved_model: SavedModel | null
}

export type ModelVersionSaveResponse = SavedModel & {
  save_state: 'CREATED' | 'ALREADY_SAVED'
  artifact_id: string
}

export class ModelVersionSaveAPIError extends Error {
  constructor(message: string, readonly code: string | null = null) {
    super(message)
    this.name = 'ModelVersionSaveAPIError'
  }
}

export type GlobalOOFFeatureImportance = {
  feature_id: string
  column_name: string
  mean_abs_shap: number
  rank: number
}

export type GlobalOOFExplanation = {
  artifact_id: string
  model_id: string
  model_version: string
  dataset_name: string
  row_count: number
  feature_count: number
  folds: number
  output_space: string
  evidence_hash: string
  features: GlobalOOFFeatureImportance[]
}

export type GlobalOOFOperation = {
  artifact_id: string
  derivation_key: string
  status: 'NOT_STARTED' | 'RUNNING' | 'READY' | 'FAILED'
  stage: 'VALIDATING' | 'PROCESSING_FOLD' | 'AGGREGATING' | 'PERSISTING' | 'READY' | 'FAILED'
  stage_label: string
  current_fold: number | null
  total_folds: number
  processed_rows: number
  total_rows: number
  started_at: string | null
  updated_at: string
  elapsed_seconds: number
  safe_error_code: string | null
  message: string | null
}

export class GlobalOOFAPIError extends Error {
  constructor(message: string, readonly code: string | null = null) {
    super(message)
    this.name = 'GlobalOOFAPIError'
  }
}

async function globalOOFRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const fallback = 'Не удалось загрузить влияние признаков.'
  let response: Response
  try {
    response = await fetch(url, init)
  } catch (reason) {
    if (init?.signal?.aborted || (reason instanceof Error && reason.name === 'AbortError')) throw reason
    throw new GlobalOOFAPIError(fallback)
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { code?: string; message?: string } } | null
    throw new GlobalOOFAPIError(payload?.detail?.message ?? fallback, payload?.detail?.code ?? null)
  }
  return response.json() as Promise<T>
}

export function runCurrentGlobalOOF(retry = false, signal?: AbortSignal): Promise<GlobalOOFOperation> {
  return globalOOFRequest('/api/v1/result/explanation/global/run', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ retry }), signal,
  })
}

export function getCurrentGlobalOOFStatus(signal?: AbortSignal): Promise<GlobalOOFOperation> {
  return globalOOFRequest('/api/v1/result/explanation/global/status', { signal })
}

export type ResultObjectItem = {
  object_id: string
  identifier_display: string
  y_true: number
  score: number
  predicted_positive: boolean
  outcome: 'TP' | 'TN' | 'FP' | 'FN'
}

export type ResultObjectList = {
  artifact_id: string
  threshold: number
  total_count: number
  filtered_count: number
  offset: number
  limit: number
  returned_count: number
  items: ResultObjectItem[]
}

export type ResultObjectDetail = {
  artifact_id: string
  object_id: string
  identifier_display: string
  y_true: number
  score: number
  threshold: number
  predicted_positive: boolean
  outcome: 'TP' | 'TN' | 'FP' | 'FN'
  fold_number: number
}

export type LocalExplanationDirection = 'increases_output' | 'decreases_output' | 'neutral'

export type LocalExplanationFeature = {
  feature_id: string
  column_name: string
  display_name_ru: string | null
  description_ru: string | null
  raw_value: number
  shap_value: number
  abs_rank: number
  direction: LocalExplanationDirection
}

export type LocalExplanationRemainder = {
  feature_count: number
  shap_value: number
  direction: LocalExplanationDirection
}

export type LocalExplanation = {
  evidence_version: string
  artifact_id: string
  object_id: string
  evidence_hash: string
  prediction_probability: number
  base_value: number
  explained_output_value: number
  output_space: string
  explanation_method_id: string
  explanation_method_version: string
  explanation_provider_id: string
  explanation_provider_version: string
  features: LocalExplanationFeature[]
  remainder: LocalExplanationRemainder | null
}

export type ResultInterpreterRole =
  | 'sales_manager'
  | 'credit_controller'
  | 'lawyer'
  | 'information_security'

export type ResultInterpretation = {
  artifact_id: string
  object_id: string
  role: ResultInterpreterRole
  text: string
  created_at: string
  response_hash: string
}

export type GlobalResultInterpretation = {
  artifact_id: string
  role: ResultInterpreterRole
  text: string
  created_at: string
  response_hash: string
}

export type ResultObjectsQuery = {
  offset: number
  limit: number
  search?: string
  target: 'ANY' | 'POSITIVE' | 'NEGATIVE'
  outcomes?: Array<'TP' | 'TN' | 'FP' | 'FN'>
  min_score: number
  max_score: number
  sort: 'SCORE_DESC' | 'SCORE_ASC' | 'DISTANCE_TO_THRESHOLD_ASC'
}

export async function getCurrentResult(): Promise<ResultOverview> {
  const response = await fetch('/api/v1/result')
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } } | null
    throw new Error(payload?.detail?.message ?? 'Не удалось загрузить результат обучения.')
  }
  return response.json() as Promise<ResultOverview>
}

export async function saveCurrentResultModel(displayName?: string): Promise<ModelVersionSaveResponse> {
  const fallback = 'Не удалось сохранить модель.'
  let response: Response
  try {
    response = await fetch('/api/v1/result/model-version', displayName === undefined ? { method: 'POST' } : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ display_name: displayName }) })
  } catch {
    throw new ModelVersionSaveAPIError(fallback)
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { code?: string; message?: string } } | null
    throw new ModelVersionSaveAPIError(payload?.detail?.message ?? fallback, payload?.detail?.code ?? null)
  }
  try {
    return await response.json() as ModelVersionSaveResponse
  } catch {
    throw new ModelVersionSaveAPIError(fallback)
  }
}

export async function getCurrentGlobalOOFExplanation(signal?: AbortSignal): Promise<GlobalOOFExplanation> {
  const fallback = 'Не удалось загрузить влияние признаков.'
  const abort = (reason: unknown) => signal?.aborted || (typeof reason === 'object' && reason !== null && 'name' in reason && reason.name === 'AbortError')
  try {
    return await globalOOFRequest<GlobalOOFExplanation>('/api/v1/result/explanation/global', { signal })
  } catch (reason) {
    if (abort(reason)) throw reason
    throw reason instanceof GlobalOOFAPIError ? reason : new GlobalOOFAPIError(fallback)
  }
}

export async function getCurrentThresholdPreview(threshold: number, signal?: AbortSignal): Promise<ThresholdMetrics> {
  const response = await fetch(`/api/v1/result/threshold?threshold=${encodeURIComponent(String(threshold))}`, { signal })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } } | null
    throw new Error(payload?.detail?.message ?? 'Не удалось пересчитать метрики для выбранного порога.')
  }
  return response.json() as Promise<ThresholdMetrics>
}

export async function getCurrentThresholdSweep(signal?: AbortSignal): Promise<ThresholdMetrics[]> {
  const response = await fetch('/api/v1/result/threshold/sweep', { signal })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } } | null
    throw new Error(payload?.detail?.message ?? 'Не удалось загрузить график зависимости метрик от порога.')
  }
  return response.json() as Promise<ThresholdMetrics[]>
}

export async function updateCurrentThreshold(threshold: number): Promise<ThresholdMetrics> {
  const response = await fetch('/api/v1/result/threshold', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ threshold }),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } } | null
    throw new Error(payload?.detail?.message ?? 'Не удалось сохранить выбранный порог.')
  }
  return response.json() as Promise<ThresholdMetrics>
}

export async function getCurrentObjects(query: ResultObjectsQuery, signal?: AbortSignal): Promise<ResultObjectList> {
  const params = new URLSearchParams({
    offset: String(query.offset),
    limit: String(query.limit),
    target: query.target,
    min_score: String(query.min_score),
    max_score: String(query.max_score),
    sort: query.sort,
  })
  if (query.search?.trim()) params.set('search', query.search)
  query.outcomes?.forEach(outcome => params.append('outcomes', outcome))
  const response = await fetch(`/api/v1/result/objects?${params.toString()}`, { signal })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } } | null
    throw new Error(payload?.detail?.message ?? 'Не удалось загрузить объекты из сохранённого OOF-результата.')
  }
  return response.json() as Promise<ResultObjectList>
}

export async function getCurrentObjectDetail(objectId: string, signal?: AbortSignal): Promise<ResultObjectDetail> {
  let response: Response
  try {
    response = await fetch(`/api/v1/result/objects/${encodeURIComponent(objectId)}`, { signal })
  } catch (reason) {
    if (signal?.aborted) throw reason
    throw new Error('Не удалось загрузить карточку объекта.')
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } } | null
    throw new Error(payload?.detail?.message ?? 'Не удалось загрузить карточку объекта.')
  }
  try {
    return await response.json() as ResultObjectDetail
  } catch {
    throw new Error('Не удалось загрузить карточку объекта.')
  }
}

export async function getCurrentObjectExplanation(objectId: string, signal?: AbortSignal): Promise<LocalExplanation> {
  const fallback = 'Не удалось построить объяснение. Сам результат объекта остаётся доступен.'
  let response: Response
  try {
    response = await fetch(`/api/v1/result/objects/${encodeURIComponent(objectId)}/explanation`, { signal })
  } catch (reason) {
    if (signal?.aborted) throw reason
    throw new Error(fallback)
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } } | null
    throw new Error(payload?.detail?.message ?? fallback)
  }
  try {
    return await response.json() as LocalExplanation
  } catch {
    throw new Error(fallback)
  }
}

export async function createCurrentGlobalResultInterpretation(
  role: ResultInterpreterRole,
  signal?: AbortSignal,
): Promise<GlobalResultInterpretation> {
  const fallback = 'Не удалось сформировать интерпретацию общего результата.'
  const isAbort = (reason: unknown) => signal?.aborted || (typeof reason === 'object' && reason !== null && 'name' in reason && reason.name === 'AbortError')
  let response: Response
  try {
    response = await fetch(`/api/v1/result/interpretations/${role}`, {
      method: 'POST',
      signal,
    })
  } catch (reason) {
    if (isAbort(reason)) throw reason
    throw new Error(fallback)
  }
  if (!response.ok) {
    let payload: { detail?: { message?: string } } | null = null
    try { payload = await response.json() as { detail?: { message?: string } } }
    catch (reason) { if (isAbort(reason)) throw reason }
    throw new Error(payload?.detail?.message ?? fallback)
  }
  try {
    return await response.json() as GlobalResultInterpretation
  } catch (reason) {
    if (isAbort(reason)) throw reason
    throw new Error(fallback)
  }
}

export async function createCurrentObjectInterpretation(
  objectId: string,
  role: ResultInterpreterRole,
  signal?: AbortSignal,
): Promise<ResultInterpretation> {
  const fallback = 'Не удалось сформировать интерпретацию.'
  const isAbort = (reason: unknown) => signal?.aborted || (typeof reason === 'object' && reason !== null && 'name' in reason && reason.name === 'AbortError')
  let response: Response
  try {
    response = await fetch(`/api/v1/result/objects/${encodeURIComponent(objectId)}/interpretations/${role}`, {
      method: 'POST',
      signal,
    })
  } catch (reason) {
    if (isAbort(reason)) throw reason
    throw new Error(fallback)
  }
  if (!response.ok) {
    let payload: { detail?: { message?: string } } | null = null
    try { payload = await response.json() as { detail?: { message?: string } } }
    catch (reason) { if (isAbort(reason)) throw reason }
    throw new Error(payload?.detail?.message ?? fallback)
  }
  try {
    return await response.json() as ResultInterpretation
  } catch (reason) {
    if (isAbort(reason)) throw reason
    throw new Error(fallback)
  }
}
