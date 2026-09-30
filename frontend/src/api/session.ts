export type NativeSession = {
  current_step: number
  analysis_active: boolean
  data_substep: 'FILE' | 'ROLES' | 'CONFIRMATION' | 'PREPARED'
  has_meaningful_temporary_work: boolean
  resume_route: '#/home' | '#/analysis/data/file' | '#/analysis/data/roles' | '#/analysis/data/confirmation' | '#/analysis/features' | '#/analysis/algorithm' | '#/analysis/quality'
}

export type NewAnalysisResponse = NativeSession & { status: 'STARTED' | 'CONFIRMATION_REQUIRED' }

export class NativeApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) { super(message) }
}

export async function getNativeSession(): Promise<NativeSession> {
  const response = await fetch('/api/v1/session')
  if (!response.ok) {
    throw new Error('Не удалось получить состояние нативной сессии.')
  }
  return response.json() as Promise<NativeSession>
}

export async function startNewAnalysis(confirmReset = false): Promise<NewAnalysisResponse> {
  const response = await fetch('/api/v1/analysis/new', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm_reset: confirmReset }),
  })
  if (!response.ok) throw new Error('Не удалось начать новый анализ.')
  return response.json() as Promise<NewAnalysisResponse>
}

export type DatasetPreparation = {
  source: { handle: string; display_name: string; format: string; size: number; rows: number; columns: number }
  draft: { target: string | null; positive_class: string | number | boolean | null; identifier: string | null }
  options: { columns: string[]; positive_classes: Array<string | number | boolean> }
  summary: { permission_counts: Record<string, number>; warnings: string[]; actions: string[]; population_policy: string; population_policy_acknowledged: boolean }
}

export type DatasetInspectionProgress = {
  status: 'IDLE' | 'RUNNING' | 'READY' | 'ERROR'
  stage: string | null
  stage_label: string | null
  started_at: string | null
  updated_at: string | null
  message: string | null
}

async function datasetResponse(response: Response): Promise<DatasetPreparation> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string; code?: string } } | null
    throw new NativeApiError(payload?.detail?.message ?? 'Не удалось обработать данные.', response.status, payload?.detail?.code)
  }
  return response.json() as Promise<DatasetPreparation>
}

export function isDatasetNotUploaded(error: unknown): boolean {
  return error instanceof NativeApiError && error.code === 'DATASET_NOT_UPLOADED'
}

export function getDatasetPreparation(): Promise<DatasetPreparation> {
  return fetch('/api/v1/dataset/preparation').then(datasetResponse)
}

export async function getDatasetProgress(): Promise<DatasetInspectionProgress> {
  const response = await fetch('/api/v1/dataset/progress')
  if (!response.ok) throw new Error('Не удалось получить ход проверки файла.')
  return response.json() as Promise<DatasetInspectionProgress>
}

export function uploadDataset(file: File): Promise<DatasetPreparation> {
  const form = new FormData()
  form.append('file', file)
  return fetch('/api/v1/dataset/upload', { method: 'POST', body: form }).then(datasetResponse)
}

export function patchDatasetDraft(changes: Record<string, unknown>): Promise<DatasetPreparation> {
  return fetch('/api/v1/dataset/preparation/draft', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  }).then(datasetResponse)
}

async function sessionResponse(response: Response): Promise<NativeSession> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string; code?: string } } | null
    throw new NativeApiError(payload?.detail?.message ?? 'Не удалось перейти к следующему шагу.', response.status, payload?.detail?.code)
  }
  return response.json() as Promise<NativeSession>
}

export function reviewDatasetPreparation(): Promise<NativeSession> {
  return fetch('/api/v1/dataset/preparation/review', { method: 'POST' }).then(sessionResponse)
}

export function returnToDatasetRoles(): Promise<NativeSession> {
  return fetch('/api/v1/dataset/preparation/roles', { method: 'POST' }).then(sessionResponse)
}

export function confirmDatasetPreparation(populationPolicyAcknowledged: boolean): Promise<NativeSession> {
  return fetch('/api/v1/dataset/preparation/confirm', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ population_policy_acknowledged: populationPolicyAcknowledged }),
  }).then(sessionResponse)
}

export type FeatureGroup = { group_id: string; name_ru: string; description_ru: string; display_order: number }
export type FeatureRow = { feature_id: string; display_name_ru: string; description_ru: string; column_name: string; group_id: string; display_order: number }
export type FeatureSelection = {
  dataset: { display_name: string; row_count: number; column_count: number; source_type: string; source_format: string }
  available_count: number; selected_feature_ids: string[]; selected_count: number; groups: FeatureGroup[]; features: FeatureRow[]
}

async function featureResponse(response: Response): Promise<FeatureSelection> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: { message?: string; code?: string } } | null
    throw new NativeApiError(payload?.detail?.message ?? 'Не удалось обновить выбор признаков.', response.status, payload?.detail?.code)
  }
  return response.json() as Promise<FeatureSelection>
}
export function getFeatures(): Promise<FeatureSelection> { return fetch('/api/v1/features').then(featureResponse) }
export function patchFeatureSelection(selected_feature_ids: string[]): Promise<FeatureSelection> {
  return fetch('/api/v1/features/selection', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ selected_feature_ids }) }).then(featureResponse)
}
export function continueFeatures(): Promise<NativeSession> { return fetch('/api/v1/features/continue', { method: 'POST' }).then(sessionResponse) }

export type CatalogParameter = { parameter_path: string; display_name_ru: string; description_ru: string; value_type: 'boolean' | 'integer' | 'float' | 'enum'; nullable: boolean; editable: boolean; recommended_value: unknown; bounds: { minimum?: number; maximum?: number }; choices: unknown[]; ui_level: string; group_id: string; display_order: number; visibility_condition: { parameter_path?: string; equals_value?: unknown } | null }
export type CatalogModel = {
  model_id: string; display_name_ru: string; description_ru: string; state: string; task_types: string[]
  capabilities: Array<{ domain: string; support: string; provider_id?: string | null; requirements?: unknown }>
  parameter_schema: { schema_id: string; schema_version: string; schema_hash: string; parameters: CatalogParameter[] }
  model_version: string; adapter_version: string; plugin_contract_hash: string
  recommended_profile: { profile_id: string; profile_version: string; profile_hash: string }
  input_contract: { prepared_predictor_kinds: string[]; prepared_dtype: string; missing_values_supported: boolean; categorical_handling: string; runtime_kind: string }
  runtime_requirements: unknown
  [key: string]: unknown
}
export type AlgorithmState = { dataset_name: string; selected_feature_count: number; available_feature_count: number; selected_model_id: string | null; configuration_mode: 'RECOMMENDED' | 'ADVANCED'; user_overrides: Record<string, unknown>; hidden_model_ids: string[]; models: CatalogModel[] }
async function algorithmResponse(response: Response): Promise<AlgorithmState> {
  if (!response.ok) { const body = await response.json().catch(() => null) as { detail?: { message?: string; code?: string } } | null; throw new NativeApiError(body?.detail?.message ?? 'Не удалось обновить алгоритм.', response.status, body?.detail?.code) }
  return response.json() as Promise<AlgorithmState>
}
export const getAlgorithm = () => fetch('/api/v1/algorithm').then(algorithmResponse)
export const selectAlgorithmModel = (model_id: string) => fetch('/api/v1/algorithm/model', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model_id }) }).then(algorithmResponse)
export const patchAlgorithmConfiguration = (configuration_mode: 'RECOMMENDED' | 'ADVANCED', user_overrides: Record<string, unknown>) => fetch('/api/v1/algorithm/configuration', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ configuration_mode, user_overrides }) }).then(algorithmResponse)
export const hideAlgorithmModel = (model_id: string) => fetch(`/api/v1/algorithm/models/${encodeURIComponent(model_id)}/hide`, { method: 'POST' }).then(algorithmResponse)
export const restoreAlgorithmModel = (model_id: string) => fetch(`/api/v1/algorithm/models/${encodeURIComponent(model_id)}/restore`, { method: 'POST' }).then(algorithmResponse)
export const continueAlgorithm = () => fetch('/api/v1/algorithm/continue', { method: 'POST' }).then(sessionResponse)
