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

export async function getCurrentResult(): Promise<ResultOverview> {
  const response = await fetch('/api/v1/result')
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } } | null
    throw new Error(payload?.detail?.message ?? 'Не удалось загрузить результат обучения.')
  }
  return response.json() as Promise<ResultOverview>
}
