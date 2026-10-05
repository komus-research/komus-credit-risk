export type ModelVersionListItem = {
  model_version_id: string
  experiment_artifact_id: string
  display_name: string
  display_version: string
  saved_at: string
  model_id: string
  model_display_name: string
  algorithm_version: string
  dataset_id: string
  dataset_name: string
  feature_count: number
  oof_gini: number
  oof_roc_auc: number
  oof_pr_auc: number
}

export type ModelVersionList = {
  total_count: number
  filtered_count: number
  offset: number
  limit: number
  returned_count: number
  items: ModelVersionListItem[]
}

export type ModelVersionListQuery = {
  offset: number
  limit: number
  search?: string
  model_id?: string
  dataset_id?: string
  saved_from?: string
  saved_to?: string
  sort?: 'SAVED_DESC'
}

export type ModelVersionRenameResponse = {
  model_version_id: string
  display_name: string
}

export type ModelVersionDetail = {
  model_version_id: string
  experiment_artifact_id: string
  display_name: string
  display_version: string
  saved_at: string
  status: 'SAVED'
  algorithm: {
    model_id: string
    model_display_name: string
    algorithm_version: string
    adapter_version: string
    source: Record<string, unknown> | null
    capabilities: Array<Record<string, unknown>> | null
  }
  dataset: {
    dataset_id: string
    dataset_name: string
    dataset_version: string
    dataset_fingerprint: string
  }
  population: {
    population_id: string
    population_fingerprint: string
    population_role: string
    population_row_count: number
  }
  target: string
  positive_class: string | number | boolean
  identifier: string
  features: Array<{
    feature_id: string
    column_name: string
    display_name: string
    description: string
    logical_type: string
    usage_status: string
  }>
  configuration: {
    configuration_mode: string | null
    user_overrides: Record<string, unknown> | null
    resolved_parameters: Record<string, unknown>
    seed: number
    folds: number
    protocol_id: string
    protocol_version: string
    evaluation_level: string
  }
  oof_quality: {
    gini: number
    roc_auc: number
    pr_auc: number
    precision_at_0_5: number
    recall_at_0_5: number
    f1_at_0_5: number
  }
  source_result: {
    experiment_artifact_id: string
    result_id: string
    experiment_created_at: string
  }
  technical_provenance: Record<string, unknown>
}

type ErrorPayload = { detail?: { code?: string, message?: string } }

export class ModelsAPIError extends Error {
  constructor(message: string, readonly code: string | null = null) {
    super(message)
    this.name = 'ModelsAPIError'
  }
}

async function modelsRequest<T>(url: string, signal?: AbortSignal): Promise<T> {
  const fallback = 'Не удалось загрузить сохранённые модели.'
  let response: Response
  try {
    response = await fetch(url, { signal })
  } catch (reason) {
    if (signal?.aborted || (reason instanceof Error && reason.name === 'AbortError')) throw reason
    throw new ModelsAPIError(fallback)
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as ErrorPayload | null
    throw new ModelsAPIError(payload?.detail?.message ?? fallback, payload?.detail?.code ?? null)
  }
  try {
    return await response.json() as T
  } catch {
    throw new ModelsAPIError(fallback)
  }
}

export function getModelVersions(query: ModelVersionListQuery, signal?: AbortSignal): Promise<ModelVersionList> {
  const params = new URLSearchParams({
    offset: String(query.offset),
    limit: String(query.limit),
    sort: query.sort ?? 'SAVED_DESC',
  })
  if (query.search?.trim()) params.set('search', query.search.trim())
  if (query.model_id) params.set('model_id', query.model_id)
  if (query.dataset_id) params.set('dataset_id', query.dataset_id)
  if (query.saved_from) params.set('saved_from', query.saved_from)
  if (query.saved_to) params.set('saved_to', query.saved_to)
  return modelsRequest<ModelVersionList>(`/api/v1/model-versions?${params.toString()}`, signal)
}

export function getModelVersion(modelVersionId: string, signal?: AbortSignal): Promise<ModelVersionDetail> {
  return modelsRequest<ModelVersionDetail>(`/api/v1/model-versions/${encodeURIComponent(modelVersionId)}`, signal)
}

export async function renameModelVersion(modelVersionId: string, displayName: string): Promise<ModelVersionRenameResponse> {
  const fallback = 'Не удалось изменить название модели.'
  let response: Response
  try {
    response = await fetch(`/api/v1/model-versions/${encodeURIComponent(modelVersionId)}/display-name`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: displayName }),
    })
  } catch {
    throw new ModelsAPIError(fallback)
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as ErrorPayload | null
    throw new ModelsAPIError(payload?.detail?.message ?? fallback, payload?.detail?.code ?? null)
  }
  try {
    return await response.json() as ModelVersionRenameResponse
  } catch {
    throw new ModelsAPIError(fallback)
  }
}
