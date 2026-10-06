type ErrorPayload = { detail?: { code?: string, message?: string } }

export class InferenceAPIError extends Error {
  constructor(message: string, readonly code: string | null = null) {
    super(message)
    this.name = 'InferenceAPIError'
  }
}

export type SavedModelInferencePreflight = {
  preparation_id: string
  model_version_id: string
  experiment_artifact_id: string
  model_display_name: string
  display_name: string
  display_version: string
  training_dataset_name: string
  source_display_name: string
  source_format: string
  source_file_sha256: string
  source_fingerprint: string
  row_count: number
  column_count: number
  identifier_column: string
  required_feature_count: number
  required_feature_columns: string[]
  ignored_column_count: number
  ignored_columns: string[]
  status: 'COMPATIBLE'
  checks: Record<'required_features' | 'input_types' | 'feature_binding' | 'rows' | 'identifier', 'PASS'>
}

export type SavedModelInferenceRun = {
  run_state: 'CREATED' | 'REUSED'
  inference_result_id: string
  model_version_id: string
  source_display_name: string
  created_at: string
}

export type InferenceHistogramBin = { lower_bound: number; upper_bound: number; count: number }
export type SavedInferenceResult = {
  inference_result_id: string
  model_version_id: string
  experiment_artifact_id: string
  display_name: string
  display_version: string
  model_display_name: string
  source_display_name: string
  source_format: string
  source_file_sha256: string
  source_fingerprint: string
  created_at: string
  status: 'COMPLETED'
  row_count: number
  column_count: number
  identifier_column: string
  required_feature_count: number
  ignored_column_count: number
  score_min: number
  score_max: number
  threshold: number
  above_threshold_count: number
  above_threshold_share: number
  below_threshold_count: number
  below_threshold_share: number
  histogram: InferenceHistogramBin[]
}

export type InferencePositionFilter = 'ALL' | 'ABOVE' | 'BELOW'
export type InferenceSort = 'SCORE_DESC' | 'SCORE_ASC' | 'SOURCE_ASC'
export type SavedInferenceViewConfiguration = {
  inference_result_id: string
  threshold: number
  min_score: number
  max_score: number
  position_filter: InferencePositionFilter
  sort: InferenceSort
  search: string
  updated_at: string | null
}
export type SavedInferenceConfigurationResponse = {
  saved: boolean
  configuration: SavedInferenceViewConfiguration
  model_decision_threshold: number | null
  default_threshold: number
  default_threshold_source: 'MODEL_DECISION' | 'TECHNICAL_DEFAULT'
}
export type SavedInferenceConfigurationInput = Pick<SavedInferenceViewConfiguration, 'threshold' | 'min_score' | 'max_score' | 'position_filter' | 'sort' | 'search'>
export type SavedInferenceObjectsQuery = SavedInferenceViewConfiguration & { offset: number; limit: number }
export type SavedInferenceObject = { row_id: string; source_row_position: number; identifier_display: string; score: number; above_threshold: boolean }
export type SavedInferenceObjects = {
  inference_result_id: string
  threshold: number
  total_count: number
  filtered_count: number
  offset: number
  limit: number
  returned_count: number
  items: SavedInferenceObject[]
}
export type SavedInferenceObjectFeature = { feature_id: string; column_name: string; display_name_ru: string | null; description_ru: string | null; raw_value: number }
export type SavedInferenceCapability = { state: 'AVAILABLE' | 'WAITING_FOR_INPUT' | 'UNSUPPORTED' | 'DISABLED' | 'MISCONFIGURED'; reason_code: string }
export type SavedInferenceObjectDetail = {
  inference_result_id: string; model_version_id: string; row_id: string; source_row_position: number
  identifier_column: string; identifier_display: string; score: number; threshold: number; position: 'ABOVE' | 'BELOW'
  features: SavedInferenceObjectFeature[]; capabilities: Record<string, SavedInferenceCapability>
}
export type SavedInferenceExplanationFeature = SavedInferenceObjectFeature & { shap_value: number; rank: number; direction: 'increases_output' | 'decreases_output' | 'neutral' }
export type SavedInferenceExplanation = {
  inference_result_id: string; model_version_id: string; row_id: string; explanation_id: string; evidence_hash: string
  prediction_probability: number; base_value: number; explained_output_value: number; output_space: string
  explanation_method_id: string; explanation_method_version: string; explanation_provider_id: string; explanation_provider_version: string
  features: SavedInferenceExplanationFeature[]; remainder: { feature_count: number; shap_value: number; direction: string } | null
  result_interpretation_capability: SavedInferenceCapability
}
export type SavedInferenceInterpretation = {
  inference_result_id: string; model_version_id: string; row_id: string; explanation_id: string; evidence_hash: string
  role: string; text: string; created_at: string; response_hash: string
}
export type SavedInferenceReportDraftItem = {
  row_id: string; source_row_position: number; identifier_display: string; score: number; threshold: number; position: 'ABOVE' | 'BELOW'
}
export type SavedInferenceReportDraft = {
  schema_version: 1; inference_result_id: string; selected_row_ids: string[]; created_at: string | null; updated_at: string | null; threshold: number
  items: SavedInferenceReportDraftItem[]
}
export type ProjectWorkspace = {
  schema_version: 1; project_id: string; name: string; work_type: 'SAVED_MODEL_INFERENCE'; inference_result_id: string
  model_version_id: string; source_fingerprint: string | null; model_display_name: string | null; source_display_name: string | null
  row_count: number | null; created_at: string; updated_at: string; last_opened_at: string | null; resumable: boolean; unavailable_code: string | null
}
export type ProjectWorkspaceList = { total_count: number; resumable_count: number; offset: number; limit: number; returned_count: number; items: ProjectWorkspace[] }

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const fallback = 'Не удалось безопасно выполнить запрос к результату прогноза.'
  let response: Response
  try {
    response = await fetch(url, init)
  } catch {
    throw new InferenceAPIError(fallback)
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as ErrorPayload | null
    throw new InferenceAPIError(payload?.detail?.message ?? fallback, payload?.detail?.code ?? null)
  }
  if (response.status === 204) return undefined as T
  try {
    return await response.json() as T
  } catch {
    throw new InferenceAPIError(fallback)
  }
}

export function preflightSavedModelInference(modelVersionId: string, file: File) {
  const body = new FormData()
  body.set('file', file)
  return request<SavedModelInferencePreflight>(`/api/v1/model-versions/${encodeURIComponent(modelVersionId)}/inference/preflight`, { method: 'POST', body })
}

export function cancelSavedModelInference(modelVersionId: string, preparationId: string) {
  return request<void>(`/api/v1/model-versions/${encodeURIComponent(modelVersionId)}/inference/${encodeURIComponent(preparationId)}`, { method: 'DELETE' })
}

export function runSavedModelInference(modelVersionId: string, preparationId: string) {
  return request<SavedModelInferenceRun>(`/api/v1/model-versions/${encodeURIComponent(modelVersionId)}/inference/${encodeURIComponent(preparationId)}/run`, { method: 'POST' })
}

export function getSavedInferenceResult(inferenceResultId: string, threshold: number) {
  return request<SavedInferenceResult>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}?threshold=${encodeURIComponent(String(threshold))}`)
}

export function getInferenceProjectSuggestion(inferenceResultId: string) {
  return request<{ suggested_name: string }>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/project-suggestion`)
}

export function saveInferenceProject(inferenceResultId: string, name: string) {
  return request<ProjectWorkspace>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/project`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) })
}

export function getProjects(offset = 0, limit = 50) {
  return request<ProjectWorkspaceList>(`/api/v1/projects?offset=${encodeURIComponent(String(offset))}&limit=${encodeURIComponent(String(limit))}`)
}

export function getProject(projectId: string) {
  return request<ProjectWorkspace>(`/api/v1/projects/${encodeURIComponent(projectId)}`)
}

export function openProject(projectId: string) {
  return request<ProjectWorkspace>(`/api/v1/projects/${encodeURIComponent(projectId)}/open`, { method: 'POST' })
}

export function getSavedInferenceObjects(inferenceResultId: string, query: SavedInferenceObjectsQuery) {
  const params = new URLSearchParams({ threshold: String(query.threshold), offset: String(query.offset), limit: String(query.limit), min_score: String(query.min_score), max_score: String(query.max_score), position_filter: query.position_filter, sort: query.sort })
  if (query.search) params.set('search', query.search)
  return request<SavedInferenceObjects>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/objects?${params.toString()}`)
}

export function getSavedInferenceConfiguration(inferenceResultId: string) {
  return request<SavedInferenceConfigurationResponse>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/configuration`)
}

export function putSavedInferenceConfiguration(inferenceResultId: string, configuration: SavedInferenceConfigurationInput) {
  const body: SavedInferenceConfigurationInput = {
    threshold: configuration.threshold,
    min_score: configuration.min_score,
    max_score: configuration.max_score,
    position_filter: configuration.position_filter,
    sort: configuration.sort,
    search: configuration.search,
  }
  return request<SavedInferenceConfigurationResponse>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/configuration`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
}

export function deleteSavedInferenceConfiguration(inferenceResultId: string) {
  return request<SavedInferenceConfigurationResponse>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/configuration`, { method: 'DELETE' })
}

export function getSavedInferenceObjectDetail(inferenceResultId: string, rowId: string, threshold: number) {
  return request<SavedInferenceObjectDetail>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/objects/${encodeURIComponent(rowId)}?threshold=${encodeURIComponent(String(threshold))}`)
}

export function getSavedInferenceExplanation(inferenceResultId: string, rowId: string) {
  return request<SavedInferenceExplanation>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/objects/${encodeURIComponent(rowId)}/explanation`)
}

export function createSavedInferenceInterpretation(inferenceResultId: string, rowId: string, role: string) {
  return request<SavedInferenceInterpretation>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/objects/${encodeURIComponent(rowId)}/interpretations/${encodeURIComponent(role)}`, { method: 'POST' })
}

export function getSavedInferenceReportDraft(inferenceResultId: string) {
  return request<SavedInferenceReportDraft>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/report-draft`)
}

export function addSavedInferenceReportRow(inferenceResultId: string, rowId: string) {
  return request<SavedInferenceReportDraft>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/report-draft/rows/${encodeURIComponent(rowId)}`, { method: 'POST' })
}

export function removeSavedInferenceReportRow(inferenceResultId: string, rowId: string) {
  return request<SavedInferenceReportDraft>(`/api/v1/inference-results/${encodeURIComponent(inferenceResultId)}/report-draft/rows/${encodeURIComponent(rowId)}`, { method: 'DELETE' })
}
