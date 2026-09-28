export type NativeSession = {
  current_step: number
  has_meaningful_temporary_work: boolean
}

export async function getNativeSession(): Promise<NativeSession> {
  const response = await fetch('/api/v1/session')
  if (!response.ok) {
    throw new Error('Не удалось получить состояние нативной сессии.')
  }
  return response.json() as Promise<NativeSession>
}

export type DatasetPreparation = {
  source: { handle: string; display_name: string; format: string; size: number; rows: number; columns: number }
  draft: { target: string | null; positive_class: string | number | boolean | null; identifier: string | null }
  options: { columns: string[]; positive_classes: Array<string | number | boolean> }
  summary: { permission_counts: Record<string, number>; warnings: string[]; actions: string[] }
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
    const payload = await response.json().catch(() => null) as { detail?: { message?: string } } | null
    throw new Error(payload?.detail?.message ?? 'Не удалось обработать данные.')
  }
  return response.json() as Promise<DatasetPreparation>
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
