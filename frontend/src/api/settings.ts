export type InterpreterRole = 'credit_controller' | 'sales_manager' | 'lawyer' | 'information_security'

export type SettingsState = {
  technical_details_expanded: boolean
  interpreter_enabled: boolean
  interpreter_toggle_editable: boolean
  default_role: InterpreterRole
  roles: InterpreterRole[]
  providers: Array<{ provider_id: string; display_name: string }>
  selected_provider_id: string | null
  models: Array<{ model_id: string; display_name: string; provider_id: string; status: 'SUPPORTED' }>
  selected_model_id: string | null
  external_data_policy: string
  credential: { configured: boolean; managed_by_system: boolean; secure_store_available: boolean }
  runtime: { available: boolean; reason: string }
}

async function response<T>(result: Response): Promise<T> {
  if (result.ok) return result.json() as Promise<T>
  const body = await result.json().catch(() => null) as { detail?: { message?: string } } | null
  throw new Error(body?.detail?.message ?? 'Не удалось обновить настройки.')
}

export const getSettings = () => fetch('/api/v1/settings').then(response<SettingsState>)
export const patchSettings = (values: Partial<Pick<SettingsState, 'technical_details_expanded' | 'interpreter_enabled' | 'default_role'>>) => fetch('/api/v1/settings/preferences', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) }).then(response<SettingsState>)
export const setCredential = (credential: string) => fetch('/api/v1/settings/credential', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ credential }) }).then(response<SettingsState>)
export const deleteCredential = () => fetch('/api/v1/settings/credential', { method: 'DELETE' }).then(response<SettingsState>)
export const checkConnection = () => fetch('/api/v1/settings/connection-check', { method: 'POST' }).then(response<{ status: 'CONNECTED' }>)
