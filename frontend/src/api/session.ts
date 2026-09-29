export type NativeSession = {
  current_step: number
  analysis_active: boolean
  data_substep: 'FILE' | 'ROLES' | 'CONFIRMATION' | 'PREPARED'
  has_meaningful_temporary_work: boolean
  resume_route: '#/home' | '#/analysis/data/file' | '#/analysis/data/roles' | '#/analysis/data/confirmation' | '#/analysis/features'
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
