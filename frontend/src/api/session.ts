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
