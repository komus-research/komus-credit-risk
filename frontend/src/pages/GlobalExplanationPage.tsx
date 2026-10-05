import { useCallback, useEffect, useRef, useState } from 'react'
import { getCurrentGlobalOOFExplanation, getCurrentGlobalOOFStatus, getCurrentResult, GlobalOOFAPIError, runCurrentGlobalOOF, type GlobalOOFExplanation, type GlobalOOFOperation } from '../api/result'
import { Icon } from '../components/Icon'
import { navigate, routes } from '../routing'

type PageState = 'IDLE' | 'LOADING' | 'RUNNING' | 'READY' | 'FAILED' | 'ERROR' | 'STALE'
const integerFormat = new Intl.NumberFormat('ru-RU')
const valueFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 4 })
const staleMessage = 'Текущий результат изменился. Откройте влияние признаков заново.'

function isAbortError(reason: unknown) {
  return typeof reason === 'object' && reason !== null && 'name' in reason && reason.name === 'AbortError'
}

function waitForNextPoll(signal: AbortSignal): Promise<void> {
  return new Promise(resolve => {
    const finish = () => {
      window.clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }
    const timer = window.setTimeout(finish, 1000)
    signal.addEventListener('abort', finish, { once: true })
  })
}

export function GlobalExplanationPage() {
  const [state, setState] = useState<PageState>('IDLE')
  const [explanation, setExplanation] = useState<GlobalOOFExplanation | null>(null)
  const [operation, setOperation] = useState<GlobalOOFOperation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [presentation, setPresentation] = useState<'ALL' | 'TOP_10'>('ALL')
  const expectedArtifact = useRef<string | null>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const activeRef = useRef(false)

  const showReady = useCallback(async (artifactId: string, signal: AbortSignal) => {
    const value = await getCurrentGlobalOOFExplanation(signal)
    if (!activeRef.current || signal.aborted) return
    if (value.artifact_id !== artifactId) {
      setState('STALE')
      setError(staleMessage)
      return
    }
    setExplanation(value)
    setOperation(null)
    setState('READY')
  }, [])

  const applyOperation = useCallback(async (next: GlobalOOFOperation, artifactId: string, signal: AbortSignal) => {
    if (!activeRef.current || signal.aborted) return
    if (next.artifact_id !== artifactId) {
      setState('STALE')
      setError(staleMessage)
      return
    }
    setOperation(next)
    if (next.status === 'READY') {
      await showReady(artifactId, signal)
    } else if (next.status === 'FAILED') {
      setError(next.message ?? 'Не удалось рассчитать влияние признаков. Сам результат модели остаётся доступен.')
      setState('FAILED')
    } else {
      setState('RUNNING')
    }
  }, [showReady])

  const beginLifecycle = useCallback(async (artifactId: string, controller: AbortController, retry = false) => {
    const { signal } = controller
    setError(null)
    setExplanation(null)
    setOperation(null)
    setState('LOADING')
    try {
      let recoveredUnexpectedNotStarted = false
      let next = await runCurrentGlobalOOF(retry, signal)
      if (!activeRef.current || signal.aborted) return
      if (next.artifact_id !== artifactId) {
        setState('STALE')
        setError(staleMessage)
        return
      }
      if (next.status === 'NOT_STARTED') {
        recoveredUnexpectedNotStarted = true
        next = await runCurrentGlobalOOF(false, signal)
      }
      if (next.status === 'NOT_STARTED') throw new Error('Расчёт не запустился. Попробуйте ещё раз.')
      await applyOperation(next, artifactId, signal)
      while (activeRef.current && !signal.aborted && next.status === 'RUNNING') {
        await waitForNextPoll(signal)
        if (!activeRef.current || signal.aborted) return
        next = await getCurrentGlobalOOFStatus(signal)
        if (next.status === 'NOT_STARTED') {
          if (recoveredUnexpectedNotStarted) throw new Error('Расчёт не запустился. Попробуйте ещё раз.')
          recoveredUnexpectedNotStarted = true
          next = await runCurrentGlobalOOF(false, signal)
          if (next.status === 'NOT_STARTED') throw new Error('Расчёт не запустился. Попробуйте ещё раз.')
        }
        await applyOperation(next, artifactId, signal)
      }
    } catch (reason) {
      if (!activeRef.current || signal.aborted || isAbortError(reason)) return
      if (reason instanceof GlobalOOFAPIError && reason.code === 'RESULT_CHANGED') {
        setError(staleMessage)
        setState('STALE')
      } else {
        setError(reason instanceof Error ? reason.message : 'Не удалось рассчитать влияние признаков.')
        setState('ERROR')
      }
    }
  }, [applyOperation])

  useEffect(() => {
    activeRef.current = true
    const controller = new AbortController()
    controllerRef.current = controller
    setState('LOADING')
    void getCurrentResult().then(result => {
      if (!activeRef.current || controller.signal.aborted) return
      const artifactId = result.summary?.artifact_id
      if (!artifactId) throw new Error('Не удалось подтвердить текущий результат.')
      expectedArtifact.current = artifactId
      return beginLifecycle(artifactId, controller)
    }).catch(reason => {
      if (!activeRef.current || controller.signal.aborted || isAbortError(reason)) return
      setError(reason instanceof Error ? reason.message : 'Не удалось загрузить результат обучения.')
      setState('ERROR')
    })
    return () => {
      activeRef.current = false
      controller.abort()
    }
  }, [beginLifecycle])

  const retry = () => {
    const artifactId = expectedArtifact.current
    if (!artifactId) return
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    void beginLifecycle(artifactId, controller, true)
  }

  const allFeatures = explanation?.features ?? []
  const maxValue = allFeatures.reduce((max, feature) => Math.max(max, feature.mean_abs_shap), 0)
  const topFeatures = explanation?.features.slice(0, 10) ?? []
  const topFeaturesMax = topFeatures.reduce((max, feature) => Math.max(max, feature.mean_abs_shap), 0)
  const presentationFeatures = presentation === 'TOP_10' ? allFeatures.slice(0, 10) : allFeatures
  const visibleFeatures = presentationFeatures.filter(feature => feature.column_name.toLocaleLowerCase('ru').includes(search.trim().toLocaleLowerCase('ru')))

  return <main className="workspace result-workspace global-explanation-workspace">
    <div className="analysis-nav"><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index < 4 ? 'completed' : 'active'}><span>{index < 4 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>
    <header className="global-explanation-header">
      <button className="back-action global-back-link" onClick={() => navigate(routes.result)}>← Назад к результату</button>
      <div className="global-breadcrumb"><span>Результат</span><b>/</b><span>Влияние признаков</span></div>
      <h1>Влияние признаков</h1>
      <p>Среднее абсолютное влияние признаков на оценки модели по OOF-проверке.</p>
    </header>

    {state === 'LOADING' && <section className="global-state-card panel" aria-live="polite"><span className="global-spinner" /><div><strong>Готовим влияние признаков</strong><p>Проверяем сохранённый результат и состояние расчёта.</p></div></section>}
    {state === 'RUNNING' && <section className="global-state-card panel" aria-live="polite"><div><strong>{operation?.stage_label ?? 'Расчёт влияния признаков'}</strong>{operation?.current_fold != null && <p>Часть {integerFormat.format(operation.current_fold)} из {integerFormat.format(operation.total_folds)}</p>}{operation && operation.total_rows > 0 && <p>Обработано {integerFormat.format(operation.processed_rows)} из {integerFormat.format(operation.total_rows)} объектов</p>}{operation && <p>Прошло {integerFormat.format(Math.floor(operation.elapsed_seconds))} с</p>}</div></section>}
    {(state === 'FAILED' || state === 'ERROR' || state === 'STALE') && <section className="global-state-card global-error-card panel" role="alert"><Icon name="alert-circle" size={24} /><div><strong>{state === 'FAILED' ? 'Не удалось рассчитать влияние признаков' : state === 'STALE' ? 'Результат изменился' : 'Не удалось показать влияние признаков'}</strong><p>{error}</p><div className="global-error-actions">{(state === 'FAILED' || state === 'ERROR') && expectedArtifact.current !== null && <button className="primary-action" onClick={retry}>{state === 'FAILED' ? 'Повторить расчёт' : 'Повторить'}</button>}<button className="back-action" onClick={() => navigate(routes.result)}>← Назад к результату</button></div></div></section>}

    {state === 'READY' && explanation && <>
      <section className="global-summary-row" aria-label="Сводка OOF-объяснения">
        <SummaryCard icon="algorithm" label="Модель" value={explanation.model_id} secondary={explanation.model_version} />
        <DatasetSummaryCard dataset={explanation.dataset_name} rowCount={explanation.row_count} />
        <SummaryCard icon="chart" label="Признаков" value={integerFormat.format(explanation.feature_count)} badge="OOF" />
      </section>

      <section className="global-top-shap-panel panel" aria-labelledby="global-top-shap-title">
        <div className="global-top-shap-heading">
          <div><h2 id="global-top-shap-title">Топ-10 признаков по среднему |SHAP|</h2><strong>Среднее |SHAP| по OOF</strong></div>
          <p>Чем длиннее полоса, тем больше среднее абсолютное влияние признака на оценки модели. Это не причинный эффект.</p>
        </div>
        {topFeatures.length ? <ol className="global-top-shap-list">
          {topFeatures.map(feature => <li key={feature.feature_id}>
            <span className="global-top-shap-rank">{feature.rank}</span>
            <span className="global-top-shap-name" title={feature.column_name}>{feature.column_name}</span>
            <span className="global-top-shap-value">{valueFormat.format(feature.mean_abs_shap)}</span>
            <span className="global-top-shap-track"><i style={{ width: `${topFeaturesMax > 0 ? Math.max(0, feature.mean_abs_shap / topFeaturesMax) * 100 : 0}%` }} /></span>
          </li>)}
        </ol> : <p className="global-top-shap-empty">Данные для графика недоступны.</p>}
      </section>

      <section className="global-feature-panel panel">
        <div className="global-panel-heading">
          <h2>Все признаки <span title="Среднее абсолютное значение SHAP по всей OOF-выборке"><Icon name="info" size={17} /></span></h2>
          <div className="global-controls">
            <label className="global-search"><Icon name="search" size={17} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Найти признак…" aria-label="Найти признак" /></label>
            <div className="global-sort" aria-label="Порядок сортировки">Среднее |SHAP| ↓</div>
            <div className="global-segmented" role="group" aria-label="Число признаков">
              <button className={presentation === 'ALL' ? 'active' : ''} aria-pressed={presentation === 'ALL'} onClick={() => setPresentation('ALL')}>Все признаки</button>
              <button className={presentation === 'TOP_10' ? 'active' : ''} aria-pressed={presentation === 'TOP_10'} onClick={() => setPresentation('TOP_10')}>Топ-10</button>
            </div>
          </div>
        </div>
        <p className="global-method-copy">Для каждого объекта используется модель того fold, в котором этот объект был проверочным. Затем для каждого признака считается среднее абсолютное значение SHAP по всей OOF-выборке.</p>
        <aside className="global-info-banner"><Icon name="info" size={19} /><p>Чем выше значение, тем сильнее признак в среднем влиял на оценки модели в OOF-проверке. Это не означает причинное влияние на результат.</p></aside>
        <div className="global-table-wrap"><table className="global-feature-table"><colgroup><col className="rank-column" /><col className="feature-column" /><col className="value-column" /><col /></colgroup><thead><tr><th>№</th><th>Признак</th><th>Среднее |SHAP| ↓</th><th>Визуальная шкала</th></tr></thead><tbody>
          {visibleFeatures.map(feature => <tr key={feature.feature_id}><td>{feature.rank}</td><td title={feature.column_name}>{feature.column_name}</td><td className="global-number">{valueFormat.format(feature.mean_abs_shap)}</td><td><div className="global-bar-track"><span style={{ width: `${maxValue > 0 ? Math.max(0, feature.mean_abs_shap / maxValue) * 100 : 0}%` }} /></div></td></tr>)}
          {!visibleFeatures.length && <tr><td className="global-empty" colSpan={4}>Признаки не найдены.</td></tr>}
        </tbody></table></div>
      </section>

      <details className="global-technical panel"><summary><Icon name="file" size={19} /><strong>Технические сведения</strong><span>Метод: OOF mean(abs(SHAP))</span><span>Выходное пространство: {explanation.output_space}</span><span>Объясняющий метод: SHAP</span><span>OOF строк: {integerFormat.format(explanation.row_count)}</span><span>Фолды: {integerFormat.format(explanation.folds)}</span><b>⌄</b></summary><dl><dt>Метод</dt><dd>OOF mean(abs(SHAP))</dd><dt>Выходное пространство</dt><dd>{explanation.output_space}</dd><dt>Объясняющий метод</dt><dd>SHAP</dd><dt>OOF строк</dt><dd>{integerFormat.format(explanation.row_count)}</dd><dt>Фолды</dt><dd>{integerFormat.format(explanation.folds)}</dd></dl></details>
    </>}
  </main>
}

function SummaryCard({ icon, label, value, secondary, badge }: { icon: 'algorithm' | 'table' | 'chart'; label: string; value: string; secondary?: string; badge?: string }) {
  return <article className="global-summary-card panel"><span className="global-summary-icon"><Icon name={icon} size={23} /></span><div><small>{label}</small><strong title={value}>{value}</strong>{secondary && <span>{secondary}</span>}</div>{badge && <b className="global-oof-badge">{badge}</b>}</article>
}

function DatasetSummaryCard({ dataset, rowCount }: { dataset: string; rowCount: number }) {
  return <article className="global-summary-card global-dataset-card panel"><span className="global-summary-icon"><Icon name="table" size={23} /></span><div className="global-summary-dual-fact"><section><small>Датасет</small><strong title={dataset}>{dataset}</strong></section><section><small>Объектов OOF</small><strong>{integerFormat.format(rowCount)}</strong></section></div></article>
}
