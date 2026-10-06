import { useCallback, useEffect, useRef, useState } from 'react'
import { deleteSavedInferenceConfiguration, getSavedInferenceConfiguration, getSavedInferenceObjects, getSavedInferenceResult, putSavedInferenceConfiguration, type SavedInferenceConfigurationResponse, type SavedInferenceObjects, type SavedInferenceViewConfiguration, type SavedInferenceResult } from '../api/inference'
import { buildModelDetailRoute, navigate } from '../routing'
import { Icon } from '../components/Icon'

const numberFormat = new Intl.NumberFormat('ru-RU')
const percentFormat = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 })
const scoreFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
const thresholdFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const PAGE_SIZE = 50

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
  const latest = useRef(0)

  const applyResponse = useCallback((response: SavedInferenceConfigurationResponse) => {
    setSaved(response.saved); setView(response.configuration); setModelThreshold(response.model_decision_threshold); setConfigError(null)
    return response.configuration
  }, [])
  const load = useCallback(async (configuration: SavedInferenceViewConfiguration, offset = 0) => {
    const token = ++latest.current
    setObjectsLoading(true); setResultError(null); setObjectsError(null)
    try {
      const [nextSummary, nextObjects] = await requestView(inferenceResultId, configuration, offset)
      if (token !== latest.current) return
      setSummary(nextSummary); setObjects(nextObjects)
    } catch (reason) {
      if (token !== latest.current) return
      setResultError(message(reason)); setObjectsError(message(reason))
    } finally { if (token === latest.current) setObjectsLoading(false) }
  }, [inferenceResultId])

  useEffect(() => {
    let active = true
    setLoading(true); setView(null); setSummary(null); setObjects(null); setModelThreshold(null); setConfigError(null); setResultError(null); setObjectsError(null); setSaveSuccess(false)
    void getSavedInferenceConfiguration(inferenceResultId).then(async response => {
      if (!active) return
      const configuration = applyResponse(response)
      await load(configuration)
    }).catch(reason => { if (active) setConfigError(message(reason)) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false; latest.current += 1 }
  }, [applyResponse, inferenceResultId, load])

  const updateView = (patch: Partial<SavedInferenceViewConfiguration>) => {
    if (!view) return
    const next = { ...view, ...patch }
    setView(next); void load(next)
  }
  const goPage = (offset: number) => { if (view) void load(view, Math.max(0, offset)) }
  const save = async () => {
    if (!view || saveBusy) return
    setSaveBusy(true); setSaveError(null); setSaveSuccess(false)
    try { applyResponse(await putSavedInferenceConfiguration(inferenceResultId, view)); setSaveSuccess(true) }
    catch (reason) { setSaveError(message(reason)) }
    finally { setSaveBusy(false) }
  }
  const reset = async () => {
    if (saveBusy) return
    setSaveBusy(true); setSaveError(null); setSaveSuccess(false)
    try { const next = applyResponse(await deleteSavedInferenceConfiguration(inferenceResultId)); await load(next) }
    catch (reason) { setSaveError(message(reason)) }
    finally { setSaveBusy(false) }
  }

  if (loading) return <main className="workspace inference-result-workspace"><section className="inference-state"><Icon name="clock" size={30} /><p>Восстанавливаем сохранённую конфигурацию результата…</p></section></main>
  if (configError) return <main className="workspace inference-result-workspace"><section className="inference-state inference-error" role="alert"><Icon name="warning" size={28} /><div><strong>Не удалось прочитать конфигурацию просмотра</strong><p>{configError}</p><button className="secondary-action" disabled={saveBusy} onClick={() => void reset()}>Сбросить настройки</button></div></section></main>
  if (!view) return null
  const maximum = Math.max(...(summary?.histogram.map(bin => bin.count) ?? [1]), 1)
  const thresholdChanged = modelThreshold !== null && view.threshold !== modelThreshold

  return <main className="workspace inference-result-workspace">
    <header className="inference-result-header"><div><button className="back-action inference-back" onClick={() => summary && navigate(buildModelDetailRoute(summary.model_version_id))}>← Назад к модели</button><p className="eyebrow">Модели / Анализ / Результат</p><h1>Результат анализа</h1><p>Оценки сохранённой модели для новых данных.</p></div><div className="inference-result-actions"><button className="secondary-action" disabled={saveBusy} onClick={() => void save()}><Icon name="file" />{saveBusy ? 'Сохраняем…' : 'Сохранить конфигурацию'}</button><button className="secondary-action" disabled title="Экспорт пока не подключён"><Icon name="download" />Экспорт</button><button className="secondary-action" disabled={!summary} onClick={() => summary && navigate(buildModelDetailRoute(summary.model_version_id))}><Icon name="folder" />Открыть модель</button><div className="inference-more"><button className="inference-more-action" type="button" aria-label="Дополнительные действия" aria-expanded={moreOpen} onClick={() => setMoreOpen(value => !value)}>⋯</button>{moreOpen && <div className="inference-more-menu"><button type="button" disabled={saveBusy} onClick={() => { setMoreOpen(false); void reset() }}>Сбросить настройки</button></div>}</div></div></header>
    {saveError && <p className="inference-inline-error" role="alert"><Icon name="warning" />{saveError}</p>}
    {saveSuccess && <p className="inference-inline-status">✓ Конфигурация сохранена</p>}
    <p className="inference-inline-status"><strong>{modelThreshold === null ? 'Технический порог по умолчанию: 0,50' : `Рабочий порог модели: ${thresholdFormat.format(modelThreshold)}`}</strong>{thresholdChanged && <> Текущий порог просмотра: {thresholdFormat.format(view.threshold)}.</>}{modelThreshold !== null && <button className="text-action" onClick={() => updateView({ threshold: modelThreshold })}>Вернуть рабочий порог модели</button>}</p>
    {summary && <><section className="panel inference-result-context"><div className="inference-card-icon"><Icon name="box" size={31} /></div><div><small>Модель</small><strong>{summary.display_name}</strong><span>Сохранённая модель</span></div><div><small>Алгоритм</small><strong>{summary.model_display_name}</strong></div><div><small>Данные</small><strong>{summary.source_display_name}</strong></div><div><small>Объектов</small><strong>{numberFormat.format(summary.row_count)}</strong></div><div><small>Признаков модели</small><strong>{summary.required_feature_count}</strong></div><div><small>Статус</small><strong className="inference-completed">● Расчёт завершён</strong></div></section>
      <section className="panel inference-summary"><div><h2>Оценки модели</h2><div className="inference-metrics"><article><small>Объектов</small><strong>{numberFormat.format(summary.row_count)}</strong></article><article><small>Выше порога</small><strong>{numberFormat.format(summary.above_threshold_count)}</strong><span>{percentFormat.format(summary.above_threshold_share)}</span></article><article><small>Ниже порога</small><strong>{numberFormat.format(summary.below_threshold_count)}</strong><span>{percentFormat.format(summary.below_threshold_share)}</span></article><article><small>Диапазон оценок</small><strong>{scoreFormat.format(summary.score_min)}–{scoreFormat.format(summary.score_max)}</strong></article></div></div><div className="inference-histogram"><h3>Распределение оценок</h3><div className="histogram-bars">{summary.histogram.map(bin => <span key={bin.lower_bound} title={`${scoreFormat.format(bin.lower_bound)}–${scoreFormat.format(bin.upper_bound)}: ${bin.count}`} style={{ height: `${Math.max(2, (bin.count / maximum) * 100)}%` }} />)}<i className="histogram-threshold-marker" style={{ left: `${view.threshold * 100}%` }}><b>Порог {scoreFormat.format(view.threshold)}</b></i></div><div className="histogram-axis"><span>0,00</span><span>0,50</span><span>1,00</span></div></div></section>
      <section className="panel inference-threshold-note"><Icon name="info" size={28} /><div><strong>Текущий порог: {scoreFormat.format(view.threshold)}</strong><p>Порог используется только для аналитического разделения объектов на группы «Выше порога» и «Ниже порога». Он не изменяет оценки и не переобучает модель.</p></div><label>Порог<input type="number" min="0" max="1" step="0.01" value={view.threshold} onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value) && value >= 0 && value <= 1) updateView({ threshold: value }) }} /></label></section>
    </>}
    <section className="panel inference-objects"><h2>Объекты</h2><div className="inference-object-controls"><label className="inference-search"><Icon name="search" /><input value={view.search} onChange={event => updateView({ search: event.target.value })} placeholder="Найти по идентификатору" /></label><label>От <input type="number" min="0" max="1" step="0.01" value={view.min_score} onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value) && value >= 0 && value <= view.max_score) updateView({ min_score: value }) }} /></label><label>До <input type="number" min="0" max="1" step="0.01" value={view.max_score} onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value) && value >= view.min_score && value <= 1) updateView({ max_score: value }) }} /></label><div className="inference-filter-buttons">{([['ALL', 'Все'], ['ABOVE', '↑ Выше порога'], ['BELOW', '↓ Ниже порога']] as const).map(([value, label]) => <button key={value} className={view.position_filter === value ? 'active' : ''} onClick={() => updateView({ position_filter: value })}>{label}</button>)}</div><select value={view.sort} onChange={event => updateView({ sort: event.target.value as SavedInferenceViewConfiguration['sort'] })}><option value="SCORE_DESC">Оценка по убыванию</option><option value="SCORE_ASC">Оценка по возрастанию</option><option value="SOURCE_ASC">Порядок источника</option></select></div>
      {objectsError && <p className="inference-inline-error" role="alert"><Icon name="warning" />{objectsError}</p>}
      <div className="inference-table-wrap"><table><thead><tr><th>Объект</th><th>Оценка модели</th><th>Относительно порога</th></tr></thead><tbody>{objectsLoading && <tr><td colSpan={3} className="inference-table-state">Загружаем объекты…</td></tr>}{!objectsLoading && objects?.items.map(item => <tr key={item.row_id}><td>{item.identifier_display}</td><td><span className="inference-score"><b>{scoreFormat.format(item.score)}</b><i><em style={{ width: `${item.score * 100}%` }} /></i></span></td><td className={item.above_threshold ? 'above' : 'below'}>{item.above_threshold ? '↑ Выше порога' : '↓ Ниже порога'}</td></tr>)}{!objectsLoading && objects && objects.items.length === 0 && <tr><td colSpan={3} className="inference-table-state">Объекты по текущему фильтру не найдены.</td></tr>}</tbody></table></div>
      {objects && <footer className="inference-pagination"><span>Показано {objects.returned_count} из {numberFormat.format(objects.filtered_count)} объектов</span><div><button className="secondary-action" disabled={objects.offset === 0 || objectsLoading} onClick={() => goPage(objects.offset - PAGE_SIZE)}>← Назад</button><button className="secondary-action" disabled={objects.offset + objects.returned_count >= objects.filtered_count || objectsLoading} onClick={() => goPage(objects.offset + PAGE_SIZE)}>Вперёд →</button></div></footer>}
    </section>
    <section className="panel inference-explanation-strip"><div><Icon name="info" size={26} /><h2>Объяснение результатов</h2></div><span><Icon name="check" />Local Explanation / SHAP</span><span><Icon name="check" />Result Interpreter</span><p>После выбора объекта можно будет открыть объяснение оценки модели.</p></section>
  </main>
}
