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
  fold_metrics: Array<Record<string, unknown>>
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

export type ResultOverview = { summary: ResultSummary; threshold: ThresholdMetrics }

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

export async function getCurrentGlobalOOFExplanation(signal?: AbortSignal): Promise<GlobalOOFExplanation> {
  const fallback = 'Не удалось загрузить влияние признаков.'
  const abort = (reason: unknown) => signal?.aborted || (typeof reason === 'object' && reason !== null && 'name' in reason && reason.name === 'AbortError')
  let response: Response
  try {
    response = await fetch('/api/v1/result/explanation/global', { signal })
  } catch (reason) {
    if (signal?.aborted || (reason instanceof DOMException && reason.name === 'AbortError')) throw reason
    throw new Error(fallback)
  }
  if (!response.ok) {
    let payload: { detail?: { message?: string } } | null = null
    try { payload = await response.json() as { detail?: { message?: string } } }
    catch (reason) { if (abort(reason)) throw reason }
    throw new Error(payload?.detail?.message ?? fallback)
  }
  try {
    return await response.json() as GlobalOOFExplanation
  } catch (reason) {
    if (abort(reason)) throw reason
    throw new Error(fallback)
  }
}

export async function updateCurrentThreshold(threshold: number): Promise<ThresholdMetrics> {
  const response = await fetch('/api/v1/result/threshold', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ threshold }),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } } | null
    throw new Error(payload?.detail?.message ?? 'Не удалось изменить диагностический порог.')
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
