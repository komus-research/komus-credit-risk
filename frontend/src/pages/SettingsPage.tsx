import { useEffect, useState } from 'react'
import { checkConnection, deleteCredential, getSettings, patchSettings, setCredential, type InterpreterRole, type SettingsState } from '../api/settings'
import { Icon } from '../components/Icon'

const roleNames: Record<InterpreterRole, string> = {
  credit_controller: 'Кредитный контролёр', sales_manager: 'Менеджер по продажам', lawyer: 'Юрист', information_security: 'Информационная безопасность',
}

export function SettingsPage({ onTechnicalDetailsPreferenceChange }: { onTechnicalDetailsPreferenceChange: (expanded: boolean) => void }) {
  const [state, setState] = useState<SettingsState | null>(null)
  const [privacy, setPrivacy] = useState(false)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [connection, setConnection] = useState<'idle' | 'checking' | 'ok' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { void getSettings().then(setState).catch(reason => setError(reason instanceof Error ? reason.message : 'Не удалось загрузить настройки.')) }, [])
  const save = (values: Parameters<typeof patchSettings>[0]) => {
    setBusy(true); setError(null)
    void patchSettings(values).then(next => { setState(next); if (values.technical_details_expanded !== undefined) onTechnicalDetailsPreferenceChange(next.technical_details_expanded) }).catch(reason => setError(reason instanceof Error ? reason.message : 'Не удалось сохранить настройку.')).finally(() => setBusy(false))
  }
  const storeCredential = () => {
    if (!key.trim()) return
    setBusy(true); setError(null)
    void setCredential(key).then(next => { setKey(''); setState(next) }).catch(reason => setError(reason instanceof Error ? reason.message : 'Не удалось сохранить ключ.')).finally(() => setBusy(false))
  }
  const removeCredential = () => {
    setBusy(true); setError(null)
    void deleteCredential().then(setState).catch(reason => setError(reason instanceof Error ? reason.message : 'Не удалось удалить ключ.')).finally(() => setBusy(false))
  }
  const runConnectionCheck = () => {
    setConnection('checking'); setError(null)
    void checkConnection().then(() => setConnection('ok')).catch(reason => { setConnection('error'); setError(reason instanceof Error ? reason.message : 'Не удалось проверить подключение.') })
  }
  if (!state) return <main className="settings-workspace"><h1>Настройки</h1><p className="settings-muted">Загружаем настройки…</p>{error && <p className="settings-error">{error}</p>}</main>
  const model = state.models.find(item => item.model_id === state.selected_model_id)
  const provider = state.providers.find(item => item.provider_id === state.selected_provider_id)
  const systemManaged = state.credential.managed_by_system
  return <main className="settings-workspace">
    <header className="settings-header"><h1>Настройки</h1><p>Глобальные настройки интерфейса и интеграций AXION.</p></header>
    {error && <p className="settings-error" role="alert">{error}</p>}
    <section className="settings-section panel"><h2>Интерфейс</h2><div className="settings-row"><strong>Технические сведения</strong><label className="settings-toggle"><input type="checkbox" checked={state.technical_details_expanded} disabled={busy} onChange={event => save({ technical_details_expanded: event.target.checked })} /><span /><b>Показывать развёрнутыми по умолчанию</b></label><small>Технические блоки содержат provenance, идентификаторы, параметры и другие подробности для опытных пользователей.</small></div></section>
    <section className="settings-section panel"><h2>Интеграции</h2><div className="settings-integration"><header><div><h3>Интерпретатор результатов</h3><p>Помогает сформировать текстовое объяснение уже рассчитанного ML / SHAP результата. Не участвует в прогнозировании.</p></div><span className={state.runtime.available ? 'settings-status ready' : 'settings-status'}><Icon name={state.runtime.available ? 'check' : 'info'} size={17} />{state.runtime.available ? 'Готов к работе' : 'Недоступен'}</span></header>
      <div className="settings-table">
        <div className="settings-control"><strong>Использовать интерпретатор результатов</strong><label className="settings-toggle"><input type="checkbox" checked={state.interpreter_enabled} disabled={busy || !state.interpreter_toggle_editable} onChange={event => save({ interpreter_enabled: event.target.checked })} /><span /><b>{state.interpreter_toggle_editable ? 'Включает генерацию текстовых объяснений для рассчитанных результатов.' : 'Отключено политикой развёртывания.'}</b></label></div>
        <div className="settings-control"><strong>Модель интерпретатора</strong><output>{model?.display_name ?? 'Не настроена'}</output><small>Только поддерживаемые модели.</small></div>
        <div className="settings-control"><strong>Роль по умолчанию</strong><select value={state.default_role} disabled={busy} onChange={event => save({ default_role: event.target.value as InterpreterRole })}>{state.roles.map(role => <option key={role} value={role}>{roleNames[role]}</option>)}</select><small>Используется для начального выбора роли в новом Result Interpreter.</small></div>
        <div className="settings-control"><strong>Учётные данные</strong>{systemManaged ? <output>Учётные данные управляются системой</output> : <div className="settings-credential"><span className={state.credential.configured ? 'configured' : ''}>{state.credential.configured ? 'Настроены' : 'Не настроены'}</span><input aria-label="API-ключ" type="password" value={key} disabled={busy || !state.credential.secure_store_available} placeholder={state.credential.configured ? 'Новый API-ключ' : 'API-ключ'} onChange={event => setKey(event.target.value)} /><button className="secondary-action" disabled={busy || !key.trim() || !state.credential.secure_store_available} onClick={storeCredential}>{state.credential.configured ? 'Заменить' : 'Подключить API-ключ'}</button>{state.credential.configured && <button className="destructive-action" disabled={busy} onClick={removeCredential}>Удалить</button>}</div>}<small>{!systemManaged && !state.credential.secure_store_available ? 'Защищённое хранилище учётных данных недоступно.' : 'Значение ключа никогда не отображается и не сохраняется в настройках.'}</small></div>
        <div className="settings-control"><strong>Provider</strong><output>{provider?.display_name ?? 'Не настроен'}</output><small>Системное значение</small></div>
        <div className="settings-control"><strong>Передача внешних данных</strong><output>{state.external_data_policy}</output><button className="settings-link" onClick={() => setPrivacy(value => !value)}>Подробнее <span>{privacy ? '⌃' : '›'}</span></button></div>
        <div className="settings-control"><strong>Проверить подключение</strong><button className="secondary-action" disabled={connection === 'checking'} onClick={runConnectionCheck}>{connection === 'checking' ? 'Проверяем…' : 'Проверить подключение'}</button>{connection === 'ok' && <span className="configured">✓ Соединение работает</span>}</div>
      </div>
    </div></section>
    <section className={`settings-privacy panel ${privacy ? 'expanded' : ''}`}><button onClick={() => setPrivacy(value => !value)}><Icon name="info" /> <strong>Как защищаются данные?</strong><span>{privacy ? '⌃' : '›'}</span></button>{privacy && <div className="settings-privacy-content"><article><h3>✓ Какие данные отправляются</h3><ul><li>Выбранная роль.</li><li>Расчётный score / probability.</li><li>Пространство выходных значений.</li><li>Названия значимых признаков и SHAP-вклады.</li><li>Доверенные описания признаков.</li></ul></article><article><h3>⊘ Какие данные не отправляются</h3><ul><li>Идентификатор объекта / ИНН и строка данных.</li><li>Сырые значения признаков.</li><li>Базовое значение SHAP и raw model output.</li><li>Полный provenance модели или набора данных.</li></ul></article></div>}</section>
    <footer className="settings-footer"><Icon name="info" /> Изменения настроек интерфейса и интерпретатора применяются к новым действиям и не меняют сохранённые результаты, оценки модели или SHAP.</footer>
  </main>
}
