import { useCallback, useEffect, useRef, useState } from 'react'
import { addSavedInferenceReportRow, deleteSavedInferenceConfiguration, getInferenceProjectSuggestion, getSavedInferenceConfiguration, getSavedInferenceObjects, getSavedInferenceReportDraft, getSavedInferenceResult, putSavedInferenceConfiguration, removeSavedInferenceReportRow, saveInferenceProject, type SavedInferenceConfigurationResponse, type SavedInferenceObjects, type SavedInferenceReportDraft, type SavedInferenceViewConfiguration, type SavedInferenceResult } from '../api/inference'
import { buildInferenceResultRoute, buildModelDetailRoute, buildSavedInferenceObjectDetailRoute, buildSavedInferenceReportDraftRoute, navigate } from '../routing'
import { Icon } from '../components/Icon'
import { SavedInferenceObjectDetailPage } from './SavedInferenceObjectDetailPage'

const numberFormat = new Intl.NumberFormat('ru-RU')
const percentFormat = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 })
const scoreFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
const thresholdFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const PAGE_SIZE = 50

function viewKey(value: SavedInferenceViewConfiguration) {
  return JSON.stringify([value.threshold, value.min_score, value.max_score, value.position_filter, value.sort, value.search])
}

type AutosaveOperation =
  | { kind: 'put'; view: SavedInferenceViewConfiguration; dueAt: number }
  | { kind: 'reset' }

function message(reason: unknown) { return reason instanceof Error ? reason.message : 'Не удалось прочитать сохранённый результат.' }
function requestView(resultId: string, view: SavedInferenceViewConfiguration, offset = 0) {
  return Promise.all([getSavedInferenceResult(resultId, view.threshold), getSavedInferenceObjects(resultId, { ...view, offset, limit: PAGE_SIZE })])
}

export function SavedModelInferenceResultPage({ inferenceResultId }: { inferenceResultId: string }) {
  const [view, setView] = useState<SavedInferenceViewConfiguration | null>(null)
  const [saved, setSaved] = useState(false)
  const [modelThreshold, setModelThreshold] = useState<number | null>(null)
  const [summary, setSummary] = useState<SavedInferenceResult | null>(null)
  const [objects, setObjects] = useState<SavedInferenceObjects | null>(null)
  const [configError, setConfigError] = useState<string | null>(null)
  const [resultError, setResultError] = useState<string | null>(null)
  const [objectsError, setObjectsError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [objectsLoading, setObjectsLoading] = useState(false)
  const [saveBusy, setSaveBusy] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [selectedRowId, setSelectedRowId] = useState<string | null>(null)
  const [listExpanded, setListExpanded] = useState(false)
  const [reportDraft, setReportDraft] = useState<SavedInferenceReportDraft | null>(null)
  const [reportBusy, setReportBusy] = useState(false)
  const [reportError, setReportError] = useState<string | null>(null)
  const [projectName, setProjectName] = useState('')
  const [projectDialogOpen, setProjectDialogOpen] = useState(false)
  const [projectBusy, setProjectBusy] = useState(false)
  const [projectError, setProjectError] = useState<string | null>(null)
  const latest = useRef(0)
  const persistedView = useRef<string | null>(null)
  const autosaveReady = useRef(false)
  const autosaveInFlight = useRef(false)
  const autosaveOperation = useRef<AutosaveOperation | null>(null)
  const autosaveTimer = useRef<number | null>(null)
  const autosaveGeneration = useRef(0)
  const autosaveDesiredView = useRef<SavedInferenceViewConfiguration | null>(null)
  const failedAutosaveKey = useRef<string | null>(null)
  const startAutosave = useRef<() => void>(() => {})

  const applyResponse = useCallback((response: SavedInferenceConfigurationResponse) => {
    setSaved(response.saved); setView(response.configuration); setModelThreshold(response.model_decision_threshold); setConfigError(null)
    return response.configuration
  }, [])
  const load = useCallback(async (configuration: SavedInferenceViewConfiguration, offset = 0, append = false) => {
    const token = ++latest.current
    setObjectsLoading(true); setResultError(null); setObjectsError(null)
    try {
      const [nextSummary, nextObjects] = append
        ? [null, await getSavedInferenceObjects(inferenceResultId, { ...configuration, offset, limit: PAGE_SIZE })] as const
        : await requestView(inferenceResultId, configuration, offset)
      if (token !== latest.current) return
      if (nextSummary) setSummary(nextSummary)
      setObjects(current => {
        if (!append || !current) return nextObjects
        const items = [...current.items, ...nextObjects.items.filter(item => !current.items.some(existing => existing.row_id === item.row_id))]
        return { ...nextObjects, offset: 0, returned_count: items.length, items }
      })
    } catch (reason) {
      if (token !== latest.current) return
      setResultError(message(reason)); setObjectsError(message(reason))
    } finally { if (token === latest.current) setObjectsLoading(false) }
  }, [inferenceResultId])

  useEffect(() => {
    let active = true
    autosaveGeneration.current += 1
    if (autosaveTimer.current !== null) window.clearTimeout(autosaveTimer.current)
    autosaveReady.current = false; persistedView.current = null; autosaveInFlight.current = false; autosaveOperation.current = null; autosaveTimer.current = null; autosaveDesiredView.current = null; failedAutosaveKey.current = null
    setLoading(true); setView(null); setSummary(null); setObjects(null); setSelectedRowId(null); setReportDraft(null); setReportError(null); setModelThreshold(null); setConfigError(null); setResultError(null); setObjectsError(null); setSaveSuccess(false)
    void getSavedInferenceReportDraft(inferenceResultId).then(value => { if (active) setReportDraft(value) }).catch(reason => { if (active) setReportError(message(reason)) })
    void getSavedInferenceConfiguration(inferenceResultId).then(async response => {
      if (!active) return
      const configuration = applyResponse(response)
      await load(configuration)
      if (active) { persistedView.current = viewKey(configuration); autosaveReady.current = true }
    }).catch(reason => { if (active) setConfigError(message(reason)) }).finally(() => { if (active) setLoading(false) })
    return () => {
      active = false; latest.current += 1; autosaveGeneration.current += 1
      if (autosaveTimer.current !== null) window.clearTimeout(autosaveTimer.current)
      autosaveTimer.current = null
    }
  }, [applyResponse, inferenceResultId, load])

  const startNextAutosave = useCallback(() => {
    const operation = autosaveOperation.current
    if (!operation || autosaveInFlight.current || (operation.kind === 'put' && !autosaveReady.current)) return
    if (operation.kind === 'put') {
      const key = viewKey(operation.view)
      if (key === persistedView.current || key === failedAutosaveKey.current) {
        autosaveOperation.current = null
        return
      }
      const remaining = operation.dueAt - Date.now()
      if (remaining > 0) {
        if (autosaveTimer.current !== null) window.clearTimeout(autosaveTimer.current)
        autosaveTimer.current = window.setTimeout(() => {
          autosaveTimer.current = null
          startAutosave.current()
        }, remaining)
        return
      }
    }
    if (autosaveTimer.current !== null) {
      window.clearTimeout(autosaveTimer.current)
      autosaveTimer.current = null
    }
    autosaveOperation.current = null
    autosaveInFlight.current = true
    const generation = autosaveGeneration.current
    setSaveBusy(true); setSaveError(null)

    if (operation.kind === 'reset') {
      void deleteSavedInferenceConfiguration(inferenceResultId).then(async response => {
        if (generation !== autosaveGeneration.current) return
        const configuration = response.configuration
        persistedView.current = viewKey(configuration)
        autosaveReady.current = true
        failedAutosaveKey.current = null
        setSaved(response.saved)
        // Do not overwrite a view changed while reset was in flight; its queued PUT wins next.
        if (!autosaveOperation.current) {
          setSelectedRowId(null)
          applyResponse(response)
          await load(configuration)
        }
      }).catch(reason => {
        if (generation === autosaveGeneration.current) setSaveError(message(reason))
      }).finally(() => {
        if (generation !== autosaveGeneration.current) return
        autosaveInFlight.current = false; setSaveBusy(false)
        startAutosave.current()
      })
      return
    }

    const sentView = operation.view
    const sentKey = viewKey(sentView)
    void putSavedInferenceConfiguration(inferenceResultId, sentView).then(response => {
      if (generation !== autosaveGeneration.current) return
      persistedView.current = viewKey(response.configuration)
      failedAutosaveKey.current = null
      setSaved(response.saved)
    }).catch(reason => {
      if (generation !== autosaveGeneration.current) return
      setSaveError(message(reason))
      failedAutosaveKey.current = sentKey
      const desiredView = autosaveDesiredView.current
      if (!autosaveOperation.current && desiredView && viewKey(desiredView) !== sentKey) {
        autosaveOperation.current = { kind: 'put', view: desiredView, dueAt: Date.now() }
      }
    }).finally(() => {
      if (generation !== autosaveGeneration.current) return
      autosaveInFlight.current = false; setSaveBusy(false)
      startAutosave.current()
    })
  }, [applyResponse, inferenceResultId, load])

  startAutosave.current = startNextAutosave

  useEffect(() => {
    if (!view || !autosaveReady.current) return
    autosaveDesiredView.current = view
    const key = viewKey(view)
    if (key === persistedView.current && !autosaveInFlight.current) {
      if (autosaveOperation.current?.kind === 'put') autosaveOperation.current = null
      return
    }
    if (key === failedAutosaveKey.current) return
    autosaveOperation.current = { kind: 'put', view, dueAt: Date.now() + 350 }
    startAutosave.current()
  }, [view])

  const updateView = (patch: Partial<SavedInferenceViewConfiguration>) => {
    if (!view) return
    const next = { ...view, ...patch }
    setSelectedRowId(null); setView(next); void load(next)
  }
  const loadMore = () => {
    if (!view || !objects || objectsLoading || objects.returned_count >= objects.filtered_count) return
    void load(view, objects.items.length, true)
  }
  const toggleReportRow = async (rowId: string) => {
    if (reportBusy) return
    setReportBusy(true); setReportError(null)
    try {
      const next = reportDraft?.selected_row_ids.includes(rowId)
        ? await removeSavedInferenceReportRow(inferenceResultId, rowId)
        : await addSavedInferenceReportRow(inferenceResultId, rowId)
      setReportDraft(next)
    } catch (reason) { setReportError(message(reason)) }
    finally { setReportBusy(false) }
  }
  const reset = () => {
    if (autosaveTimer.current !== null) window.clearTimeout(autosaveTimer.current)
    autosaveTimer.current = null
    autosaveOperation.current = { kind: 'reset' }
    failedAutosaveKey.current = null
    setSelectedRowId(null); setSaveError(null); setSaveSuccess(false)
    startAutosave.current()
  }
  const openProjectDialog = async () => {
    if (!summary || projectBusy) return
    setProjectBusy(true); setProjectError(null); setProjectName(''); setProjectDialogOpen(true)
    try { setProjectName((await getInferenceProjectSuggestion(inferenceResultId)).suggested_name) }
    catch { setProjectError('Не удалось получить рекомендуемое название проекта. Повторите попытку.') }
    finally { setProjectBusy(false) }
  }
  const saveProject = async () => {
    if (projectBusy || !projectName.trim()) return
    setProjectBusy(true); setProjectError(null)
    try { await saveInferenceProject(inferenceResultId, projectName); setProjectDialogOpen(false); navigate('#/history') }
    catch (reason) { setProjectError(message(reason)) }
    finally { setProjectBusy(false) }
  }

  if (loading) return <main className="workspace inference-result-workspace"><section className="inference-state"><Icon name="clock" size={30} /><p>Восстанавливаем сохранённую конфигурацию результата…</p></section></main>
  if (configError) return <main className="workspace inference-result-workspace"><section className="inference-state inference-error" role="alert"><Icon name="warning" size={28} /><div><strong>Не удалось прочитать конфигурацию просмотра</strong><p>{configError}</p><button className="secondary-action" onClick={reset}>Сбросить настройки</button></div></section></main>
  if (!view) return null
  const maximum = Math.max(...(summary?.histogram.map(bin => bin.count) ?? [1]), 1)
  const thresholdChanged = modelThreshold !== null && view.threshold !== modelThreshold

  return <main className="workspace inference-result-workspace">
    <header className="inference-result-header"><div><button className="back-action inference-back" onClick={() => summary && navigate(buildModelDetailRoute(summary.model_version_id))}>← Назад к модели</button><p className="eyebrow">Модели / Анализ / Результат</p><h1>Результат анализа</h1><p>Оценки сохранённой модели для новых данных.</p></div><div className="inference-result-actions"><button className="secondary-action" disabled={!summary || projectBusy} onClick={() => void openProjectDialog()}><Icon name="folder" />Сохранить как проект</button><button className="secondary-action" onClick={() => navigate(buildSavedInferenceReportDraftRoute(inferenceResultId))}>Отчёт · {reportDraft?.selected_row_ids.length ?? 0}</button><button className="secondary-action" disabled title="Экспорт пока не подключён"><Icon name="download" />Экспорт</button><button className="secondary-action" disabled={!summary} onClick={() => summary && navigate(buildModelDetailRoute(summary.model_version_id))}><Icon name="folder" />Открыть модель</button><div className="inference-more"><button className="inference-more-action" type="button" aria-label="Дополнительные действия" aria-expanded={moreOpen} onClick={() => setMoreOpen(value => !value)}>⋯</button>{moreOpen && <div className="inference-more-menu"><button type="button" onClick={() => { setMoreOpen(false); reset() }}>Сбросить настройки</button></div>}</div></div></header>
    {saveError && <p className="inference-inline-error" role="alert"><Icon name="warning" />{saveError}</p>}
    {reportError && <p className="inference-inline-error" role="alert"><Icon name="warning" />{reportError}</p>}
    {saveSuccess && <p className="inference-inline-status">✓ Настройки просмотра сохранены и будут восстановлены при повторном открытии этого результата. Сам результат расчёта сохраняется автоматически.</p>}
    {summary && <><section className="panel inference-result-context"><div className="inference-card-icon"><Icon name="box" size={31} /></div><div><small>Модель</small><strong>{summary.display_name}</strong><span>Сохранённая модель</span></div><div><small>Алгоритм</small><strong>{summary.model_display_name}</strong></div><div><small>Рабочий порог модели</small><strong>{modelThreshold === null ? 'Не задан' : thresholdFormat.format(modelThreshold)}</strong></div><div><small>Данные</small><strong>{summary.source_display_name}</strong></div><div><small>Объектов</small><strong>{numberFormat.format(summary.row_count)}</strong></div><div><small>Признаков модели</small><strong>{summary.required_feature_count}</strong></div><div><small>Статус</small><strong className="inference-completed">● Расчёт завершён</strong></div></section>
      <section className="panel inference-summary"><div><h2>Оценки модели</h2><div className="inference-metrics"><article><small>Объектов</small><strong>{numberFormat.format(summary.row_count)}</strong></article><article><small>Выше порога</small><strong>{numberFormat.format(summary.above_threshold_count)}</strong><span>{percentFormat.format(summary.above_threshold_share)}</span></article><article><small>Ниже порога</small><strong>{numberFormat.format(summary.below_threshold_count)}</strong><span>{percentFormat.format(summary.below_threshold_share)}</span></article><article><small>Диапазон оценок</small><strong>{scoreFormat.format(summary.score_min)}–{scoreFormat.format(summary.score_max)}</strong></article></div></div><div className="inference-histogram"><h3>Распределение оценок</h3><p className="inference-histogram-hint"><Icon name="info" size={17} />График показывает, сколько объектов попало в каждый диапазон скора модели. Слева — низкие оценки, справа — высокие; высокий столбец означает много объектов в этом диапазоне. Форма распределения сама по себе не означает хорошее или плохое качество модели.</p><div className="histogram-bars">{summary.histogram.map(bin => <span key={bin.lower_bound} title={`${scoreFormat.format(bin.lower_bound)}–${scoreFormat.format(bin.upper_bound)}: ${bin.count}`} style={{ height: `${Math.max(2, (bin.count / maximum) * 100)}%` }} />)}<i className="histogram-threshold-marker" style={{ left: `${view.threshold * 100}%` }} /></div><div className="histogram-axis"><span>0,00</span><span>0,50</span><span>1,00</span></div><p className="inference-histogram-caption">Пунктир — текущий порог просмотра: {scoreFormat.format(view.threshold)}</p></div></section>
      <section className="panel inference-threshold-note"><Icon name="info" size={28} /><div><strong>Текущий порог просмотра: {scoreFormat.format(view.threshold)}</strong><p>Порог используется только для аналитического разделения объектов на группы «Выше порога» и «Ниже порога». Он не изменяет оценки и не переобучает модель.</p>{modelThreshold !== null && thresholdChanged && <p>Рабочий порог модели: {thresholdFormat.format(modelThreshold)}</p>}{modelThreshold !== null && <button className="text-action" onClick={() => updateView({ threshold: modelThreshold })}>Вернуть рабочий порог модели</button>}</div><label>Порог просмотра<input type="number" min="0" max="1" step="0.01" value={view.threshold} onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value) && value >= 0 && value <= 1) updateView({ threshold: value }) }} /></label></section>
    </>}
    <div className={`inference-analysis-split ${selectedRowId ? 'has-explanation' : ''}`}>
    <section className="panel inference-objects"><h2>Объекты</h2><div className="inference-object-controls"><label className="inference-search"><Icon name="search" /><input value={view.search} onChange={event => updateView({ search: event.target.value })} placeholder="Найти по идентификатору" /></label><div className="inference-score-range"><label>От <input type="number" min="0" max="1" step="0.01" value={view.min_score} onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value) && value >= 0 && value <= view.max_score) updateView({ min_score: value }) }} /></label><label>До <input type="number" min="0" max="1" step="0.01" value={view.max_score} onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value) && value >= view.min_score && value <= 1) updateView({ max_score: value }) }} /></label></div><div className="inference-filter-buttons">{([['ALL', 'Все'], ['ABOVE', '↑ Выше порога'], ['BELOW', '↓ Ниже порога']] as const).map(([value, label]) => <button key={value} className={view.position_filter === value ? 'active' : ''} onClick={() => updateView({ position_filter: value })}>{label}</button>)}</div><select value={view.sort} onChange={event => updateView({ sort: event.target.value as SavedInferenceViewConfiguration['sort'] })}><option value="SCORE_DESC">Оценка по убыванию</option><option value="SCORE_ASC">Оценка по возрастанию</option><option value="SOURCE_ASC">Порядок источника</option></select></div>
      {objectsError && <p className="inference-inline-error" role="alert"><Icon name="warning" />{objectsError}</p>}
      <div className={`inference-table-wrap inference-table-scroll ${listExpanded ? 'expanded' : 'compact'}`} onScroll={event => { const target = event.currentTarget; if (target.scrollHeight - target.scrollTop - target.clientHeight < 72) loadMore() }}><table><thead><tr><th>№</th><th>Объект</th><th>Оценка модели</th><th>Относительно порога</th></tr></thead><tbody>{objectsLoading && !objects && <tr><td colSpan={4} className="inference-table-state">Загружаем объекты…</td></tr>}{objects?.items.map((item, index) => <tr key={item.row_id} className={`inference-object-row ${selectedRowId === item.row_id ? 'selected' : ''}`} tabIndex={0} role="button" aria-pressed={selectedRowId === item.row_id} onClick={() => setSelectedRowId(item.row_id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedRowId(item.row_id) } }}><td>{index + 1}</td><td>{item.identifier_display}</td><td><span className="inference-score"><b>{scoreFormat.format(item.score)}</b><i><em style={{ width: `${item.score * 100}%` }} /></i></span></td><td className={item.above_threshold ? 'above' : 'below'}>{item.above_threshold ? '↑ Выше порога' : '↓ Ниже порога'}</td></tr>)}{!objectsLoading && objects && objects.items.length === 0 && <tr><td colSpan={4} className="inference-table-state">Объекты по текущему фильтру не найдены.</td></tr>}{objectsLoading && objects && <tr><td colSpan={4} className="inference-table-loading">Загружаем ещё…</td></tr>}</tbody></table></div>
      {objects && <footer className="inference-pagination"><span>Показано {objects.returned_count} из {numberFormat.format(objects.filtered_count)} объектов</span><button className="secondary-action" onClick={() => setListExpanded(value => !value)}>{listExpanded ? 'Свернуть список' : 'Развернуть список'}</button></footer>}
    </section>
    {selectedRowId && <section className="panel inference-inline-explanation-panel"><header><div><Icon name="info" size={26} /><div><h2>Объяснение объекта</h2><p>Local SHAP и Result Interpreter используют сохранённые данные выбранного объекта.</p></div></div><button className="inference-explanation-close" type="button" aria-label="Закрыть объяснение" onClick={() => setSelectedRowId(null)}>×</button></header><SavedInferenceObjectDetailPage embedded inferenceResultId={inferenceResultId} rowId={selectedRowId} threshold={view.threshold} inReport={reportDraft?.selected_row_ids.includes(selectedRowId) ?? false} reportBusy={reportBusy} onToggleReport={() => void toggleReportRow(selectedRowId)} /></section>}
    </div>
    {projectDialogOpen && <div className="native-modal-backdrop" role="presentation"><section className="native-modal" role="dialog" aria-modal="true" aria-labelledby="save-project-title"><h2 id="save-project-title">Сохранить как проект</h2><p>Проект хранит ссылку на точный сохранённый результат анализа.</p><label>Название проекта<input autoFocus value={projectName} maxLength={160} onChange={event => setProjectName(event.target.value)} /></label>{projectError && <p className="result-save-error" role="alert">{projectError}</p>}<div><button className="secondary-action" disabled={projectBusy} onClick={() => setProjectDialogOpen(false)}>Отмена</button><button className="primary-action" disabled={projectBusy || !projectName.trim()} onClick={() => void saveProject()}>{projectBusy ? 'Сохраняем…' : 'Сохранить'}</button></div></section></div>}
  </main>
}

export function SavedInferenceReportDraftPage({ inferenceResultId }: { inferenceResultId: string }) {
  const [draft, setDraft] = useState<SavedInferenceReportDraft | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyRowId, setBusyRowId] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setDraft(null); setError(null)
    void getSavedInferenceReportDraft(inferenceResultId).then(value => { if (active) setDraft(value) }).catch(reason => { if (active) setError(message(reason)) })
    return () => { active = false }
  }, [inferenceResultId])

  const remove = async (rowId: string) => {
    if (busyRowId) return
    setBusyRowId(rowId); setError(null)
    try { setDraft(await removeSavedInferenceReportRow(inferenceResultId, rowId)) }
    catch (reason) { setError(message(reason)) }
    finally { setBusyRowId(null) }
  }

  return <main className="workspace inference-result-workspace report-draft-workspace">
    <header className="inference-result-header"><div><button className="back-action inference-back" onClick={() => navigate(buildInferenceResultRoute(inferenceResultId))}>← Назад к результату</button><p className="eyebrow">Модели / Анализ / Черновик отчёта</p><h1>Черновик отчёта</h1><p>{draft ? `${draft.items.length} ${draft.items.length === 1 ? 'компания' : 'компаний'}` : 'Загружаем выбранные компании…'}</p></div></header>
    {error && <p className="inference-inline-error" role="alert"><Icon name="warning" />{error}</p>}
    {!error && !draft && <section className="panel inference-state" aria-busy="true"><Icon name="clock" size={30} /><p>Загружаем черновик отчёта…</p></section>}
    {draft && <section className="panel report-draft-list"><header><div><h2>Компании в отчёте</h2><p>Сохранены ссылки на evidence выбранных объектов; аналитические данные не копируются в черновик.</p></div><span>{draft.items.length}</span></header>{draft.items.length === 0 ? <p className="report-draft-empty">Добавьте компании из панели объяснения результата.</p> : <ol>{draft.items.map((item, index) => <li key={item.row_id}><span className="report-draft-number">{index + 1}</span><div><strong>{item.identifier_display}</strong><small>Score: {scoreFormat.format(item.score)} · {item.position === 'ABOVE' ? '↑ Выше порога' : '↓ Ниже порога'} · Порог: {thresholdFormat.format(item.threshold)}</small></div><div className="report-draft-actions"><button className="secondary-action" onClick={() => navigate(buildSavedInferenceObjectDetailRoute(inferenceResultId, item.row_id, item.threshold))}>Открыть объект</button><button className="text-action" disabled={busyRowId !== null} onClick={() => void remove(item.row_id)}>{busyRowId === item.row_id ? 'Удаляем…' : 'Удалить'}</button></div></li>)}</ol>}</section>}
  </main>
}
