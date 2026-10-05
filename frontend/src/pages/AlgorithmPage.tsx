import { useEffect, useMemo, useState } from 'react'
import {
  continueAlgorithm, getAlgorithm, hideAlgorithmModel, patchAlgorithmConfiguration,
  restoreAlgorithmModel, selectAlgorithmModel, type AlgorithmState, type CatalogModel,
  type CatalogParameter,
} from '../api/session'
import { navigate, routes } from '../routing'

const capabilityLabels: Record<string, string> = {
  targetless_inference: 'Прогноз на новых данных',
  persistence: 'Сохранение и загрузка модели',
  loading: 'Сохранение и загрузка модели',
  local_explanation: 'Локальное объяснение результата',
}
const stepNames = ['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат']

function effectiveValue(parameter: CatalogParameter | undefined, overrides: Record<string, unknown>) {
  if (!parameter) return undefined
  return parameter.parameter_path in overrides ? overrides[parameter.parameter_path] : parameter.recommended_value
}

function compactValue(value: unknown): string {
  if (value === null || typeof value !== 'object') return String(value)
  if (Array.isArray(value)) return value.map(String).join(', ')
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => `${key}: ${compactValue(item)}`).join(' · ')
}

export function AlgorithmPage() {
  const [data, setData] = useState<AlgorithmState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [hideTarget, setHideTarget] = useState<CatalogModel | null>(null)
  const [menuModelId, setMenuModelId] = useState<string | null>(null)

  useEffect(() => {
    void getAlgorithm().then(setData).catch(reason => {
      setError(reason instanceof Error ? reason.message : 'Не удалось загрузить каталог алгоритмов.')
    })
  }, [])

  const selected = useMemo(
    () => data?.models.find(model => model.model_id === data.selected_model_id),
    [data],
  )
  const hiddenIds = data?.hidden_model_ids ?? []
  const visibleModels = data?.models.filter(model => !hiddenIds.includes(model.model_id)) ?? []
  const hiddenModels = data?.models.filter(model => hiddenIds.includes(model.model_id)) ?? []
  const catalogParameters = (selected?.parameter_schema.parameters ?? [])
    .sort((left, right) => left.display_order - right.display_order || left.parameter_path.localeCompare(right.parameter_path))
  const parameters = catalogParameters.filter(parameter => parameter.editable)
  const parametersByPath = new Map(catalogParameters.map(parameter => [parameter.parameter_path, parameter]))
  const isVisible = (parameter: CatalogParameter, overrides: Record<string, unknown>) => {
    const condition = parameter.visibility_condition
    if (!condition) return true
    const controller = parametersByPath.get(condition.parameter_path ?? '')
    return controller !== undefined && effectiveValue(controller, overrides) === condition.equals_value
  }
  const visibleParameterPaths = (overrides: Record<string, unknown>) =>
    new Set(parameters.filter(parameter => isVisible(parameter, overrides)).map(parameter => parameter.parameter_path))
  const visibleOverrides = (overrides: Record<string, unknown>) => {
    const paths = visibleParameterPaths(overrides)
    return Object.fromEntries(Object.entries(overrides).filter(([path]) => paths.has(path)))
  }

  const update = (request: Promise<AlgorithmState>) => {
    setBusy(true)
    setError(null)
    void request.then(setData).catch(reason => {
      setError(reason instanceof Error ? reason.message : 'Не удалось сохранить изменения.')
    }).finally(() => setBusy(false))
  }

  const edit = (parameter: CatalogParameter, value: unknown) => {
    if (!data) return
    const next = { ...data.user_overrides }
    if (value === parameter.recommended_value) delete next[parameter.parameter_path]
    else next[parameter.parameter_path] = value
    const visiblePaths = visibleParameterPaths(next)
    for (const path of Object.keys(next)) if (!visiblePaths.has(path)) delete next[path]
    update(patchAlgorithmConfiguration('ADVANCED', next))
  }

  const renderControl = (parameter: CatalogParameter) => {
    if (!data || !isVisible(parameter, data.user_overrides)) return null
    const value = effectiveValue(parameter, data.user_overrides)
    const input = parameter.value_type === 'boolean' && parameter.nullable
      ? <select aria-label={parameter.display_name_ru} value={value === null || value === undefined ? '__null' : String(value)}
          onChange={event => edit(parameter, event.target.value === '__null' ? null : event.target.value === 'true')}>
          <option value="__null">Не задавать</option><option value="true">Да</option><option value="false">Нет</option>
        </select>
      : parameter.value_type === 'boolean'
        ? <input type="checkbox" checked={value === true} onChange={event => edit(parameter, event.target.checked)} />
      : parameter.value_type === 'enum'
        ? <select value={value === null ? '__null' : String(value)} onChange={event => edit(parameter, event.target.value === '__null' ? null : parameter.choices.find(choice => String(choice) === event.target.value) ?? event.target.value)}>
          {parameter.nullable && <option value="__null">Не задавать</option>}
          {parameter.choices.map(choice => <option key={String(choice)} value={String(choice)}>{String(choice)}</option>)}
        </select>
        : <input type="number" step={parameter.value_type === 'integer' ? 1 : 'any'}
          min={parameter.bounds.minimum} max={parameter.bounds.maximum}
          value={value === null ? '' : Number(value)}
          onChange={event => edit(parameter, event.target.value === '' && parameter.nullable ? null : Number(event.target.value))} />
    return <label className="algorithm-control" key={parameter.parameter_path}>
      <strong>{parameter.display_name_ru}</strong><small>{parameter.description_ru}</small>{input}
    </label>
  }

  const selectedIsAvailable = Boolean(selected && selected.state === 'AVAILABLE' && !hiddenIds.includes(selected.model_id))
  const availableCount = data?.models.filter(model => model.state === 'AVAILABLE').length ?? 0
  const technicalRows: Array<[string, unknown]> = selected ? [
    ['model_id', selected.model_id], ['model_version', selected.model_version], ['adapter_version', selected.adapter_version],
    ['schema id', selected.parameter_schema.schema_id], ['schema version', selected.parameter_schema.schema_version],
    ['schema hash', selected.parameter_schema.schema_hash], ['profile id', selected.recommended_profile.profile_id],
    ['profile version', selected.recommended_profile.profile_version], ['profile hash', selected.recommended_profile.profile_hash],
    ['plugin contract hash', selected.plugin_contract_hash], ['input contract', selected.input_contract],
    ['runtime requirements', selected.runtime_requirements],
    ['capabilities (domain · support · provider)', selected.capabilities.map(item => [item.domain, item.support, item.provider_id].filter(Boolean).join(' · '))],
    ['configuration mode', data?.configuration_mode], ['sparse overrides', data?.user_overrides],
  ] : []

  return <main className="workspace algorithm-workspace">
      <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{stepNames.map((name, index) => <li key={name} className={index < 2 ? 'completed' : index === 2 ? 'active' : ''}><span>{index < 2 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>
      <header className="features-header"><div><p className="eyebrow">Шаг 3 из 5</p><h1>Выбор алгоритма</h1><p>Выберите алгоритм и настройки для текущего эксперимента.</p></div></header>
      {error && <p className="feature-warning">{error}</p>}
      {!data && !error && <p className="feature-loading">Загрузка каталога алгоритмов…</p>}
      {!data && error && <p className="feature-warning">Не удалось получить каталог алгоритмов. Попробуйте обновить страницу.</p>}
      {data && <>
        <section className="algorithm-context panel">
          <span><b>Признаков выбрано:</b> {data.selected_feature_count} из {data.available_feature_count}</span>
          <span><b>Датасет:</b> {data.dataset_name}</span>
          <button className="text-action" onClick={() => navigate(routes.features)}>Изменить признаки</button>
        </section>

        {data.selected_model_id && !selected && <p className="feature-warning">Ранее выбранный алгоритм отсутствует в текущем реестре. Выберите другой алгоритм.</p>}
        {selected && !selectedIsAvailable && <p className="feature-warning">Ранее выбранный алгоритм сейчас недоступен. Выберите другой алгоритм для продолжения.</p>}

        <section>
          <div className="algorithm-section-title"><div><h2>Выберите алгоритм</h2><p>Алгоритмы из реестра для текущего эксперимента.</p></div><button className="secondary-action" disabled title="Будет доступно позже">+ Подключить модель</button></div>
          {data.models.length === 0 && <p className="feature-warning">В реестре нет зарегистрированных алгоритмов.</p>}
          {data.models.length > 0 && availableCount === 0 && <p className="feature-warning">Нет алгоритмов, готовых к запуску в текущей среде.</p>}
          {data.models.length > 0 && visibleModels.length === 0 && <p className="feature-warning">Все модели скрыты из рабочего списка. Верните нужную модель, чтобы продолжить.</p>}
          <div className="model-grid">{visibleModels.map(model => <article key={model.model_id}
            className={`model-card panel ${data.selected_model_id === model.model_id ? 'selected' : ''} ${model.state !== 'AVAILABLE' ? 'disabled' : ''}`}
            aria-disabled={model.state !== 'AVAILABLE'}
            onClick={() => model.state === 'AVAILABLE' && !busy && update(selectAlgorithmModel(model.model_id))}>
            <button className="model-menu" aria-label={`Действия: ${model.display_name_ru}`} aria-expanded={menuModelId === model.model_id}
              onClick={event => { event.stopPropagation(); setMenuModelId(menuModelId === model.model_id ? null : model.model_id) }}>⋯</button>
            {menuModelId === model.model_id && <div className="model-card-menu" onClick={event => event.stopPropagation()}>
              <button onClick={() => { setMenuModelId(null); if (model.model_id === data.selected_model_id) setHideTarget(model); else update(hideAlgorithmModel(model.model_id)) }}>Скрыть из списка</button>
            </div>}
            <div className="model-icon">◇</div><h3>{model.display_name_ru}</h3><p>{model.description_ru}</p>
            <div className="model-badges">{model.task_types.includes('binary_classification') && <span>Бинарная классификация</span>}
              <span>{model.state === 'AVAILABLE' ? 'Доступен' : model.state === 'MISCONFIGURED' ? 'Требует настройки' : 'Недоступен'}</span></div>
            {data.selected_model_id === model.model_id && <strong className="selected-label">Выбрана</strong>}
          </article>)}</div>
        </section>

        {hiddenModels.length > 0 && <section className="hidden-models panel"><h2>Скрытые модели · {hiddenModels.length}</h2>
          {hiddenModels.map(model => <div key={model.model_id}><span>{model.display_name_ru} · {model.state}</span>
            <button className="text-action" disabled={busy} onClick={() => update(restoreAlgorithmModel(model.model_id))}>Вернуть в список</button></div>)}
        </section>}

        {selected && selectedIsAvailable && <section className="algorithm-settings panel"><h2>Настройки модели</h2>
          <div className="mode-switch">
            <button className={data.configuration_mode === 'RECOMMENDED' ? 'active' : ''} disabled={busy}
              onClick={() => { if (data.configuration_mode === 'ADVANCED' && Object.keys(data.user_overrides).length) setConfirmReset(true); else update(patchAlgorithmConfiguration('RECOMMENDED', {})) }}>Рекомендуемые</button>
            <button className={data.configuration_mode === 'ADVANCED' ? 'active' : ''} disabled={busy || parameters.length === 0}
              title={parameters.length === 0 ? 'Для этой модели нет параметров, доступных для ручной настройки.' : undefined}
              onClick={() => update(patchAlgorithmConfiguration('ADVANCED', visibleOverrides(data.user_overrides)))}>Расширенные</button>
          </div>
          {data.configuration_mode === 'RECOMMENDED' ? <><p>Использовать проверенные настройки проекта.</p>
            {parameters.some(parameter => parameter.editable && parameter.ui_level === 'basic') && <div className="recommended-grid">{parameters.filter(parameter => parameter.ui_level === 'basic').map(parameter => <div key={parameter.parameter_path}><small>{parameter.display_name_ru}</small><strong>{String(parameter.recommended_value)}</strong></div>)}</div>}
          </> : parameters.length === 0 ? <p>Для этой модели нет параметров, доступных для ручной настройки.</p> : <>
            {parameters.some(parameter => parameter.ui_level === 'basic' && isVisible(parameter, data.user_overrides)) && <div className="controls-section"><h3>Основные настройки</h3>{parameters.filter(parameter => parameter.ui_level === 'basic').map(renderControl)}</div>}
            {parameters.some(parameter => parameter.ui_level !== 'basic' && isVisible(parameter, data.user_overrides)) && <details><summary>Дополнительные настройки</summary><div className="controls-section">{parameters.filter(parameter => parameter.ui_level !== 'basic').map(renderControl)}</div></details>}
            {parameters.length > 0 && visibleParameterPaths(data.user_overrides).size === 0 && <p>Для текущих значений нет доступных дополнительных настроек.</p>}
            {Object.keys(data.user_overrides).length > 0 && <button className="text-action" disabled={busy} onClick={() => update(patchAlgorithmConfiguration('ADVANCED', {}))}>Восстановить рекомендуемые</button>}
          </>}
          <details><summary>Возможности</summary><ul>{[...new Set(selected.capabilities.filter(capability => capability.support === 'SUPPORTED').map(capability => capabilityLabels[capability.domain]).filter((label): label is string => Boolean(label)))].map(label => <li key={label}>{label}</li>)}</ul></details>
          <details className="algorithm-technical-details"><summary>Технические сведения</summary><dl className="algorithm-technical-list">{technicalRows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{compactValue(value)}</dd></div>)}</dl></details>
        </section>}

        <footer className="feature-footer"><button className="back-action" onClick={() => navigate(routes.features)}>← Назад к признакам</button>
          <button className="primary-action" disabled={!selectedIsAvailable || busy} onClick={() => { setBusy(true); void continueAlgorithm().then(() => navigate(routes.quality)).catch(reason => setError(reason instanceof Error ? reason.message : 'Не удалось продолжить.')).finally(() => setBusy(false)) }}>Далее: проверка качества →</button>
        </footer>
      </>}

      {confirmReset && <div className="native-modal-backdrop"><section className="native-modal"><h2>Сбросить ручные настройки?</h2><p>Ручные изменения будут сброшены.</p><div>
        <button className="secondary-action" onClick={() => setConfirmReset(false)}>Отмена</button><button className="destructive-action" onClick={() => { setConfirmReset(false); update(patchAlgorithmConfiguration('RECOMMENDED', {})) }}>Сбросить</button>
      </div></section></div>}
      {hideTarget && <div className="native-modal-backdrop"><section className="native-modal"><h2>Скрыть «{hideTarget.display_name_ru}» из списка?</h2><p>Эта модель сейчас выбрана для эксперимента. После скрытия потребуется выбрать другую модель.</p><div>
        <button className="secondary-action" onClick={() => setHideTarget(null)}>Отмена</button><button className="destructive-action" onClick={() => { update(hideAlgorithmModel(hideTarget.model_id)); setHideTarget(null) }}>Скрыть из списка</button>
      </div></section></div>}
    </main>
}
