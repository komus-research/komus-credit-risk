import { useEffect, useMemo, useState } from 'react'
import {
  getCurrentResult,
  getCurrentThresholdPreview,
  getCurrentThresholdSweep,
  updateCurrentThreshold,
  type ResultOverview,
  type ThresholdMetrics,
} from '../api/result'
import { Icon } from '../components/Icon'
import { navigate, routes } from '../routing'

const DEFAULT_THRESHOLD = 0.5
const thresholdFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const percentFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const integerFormat = new Intl.NumberFormat('ru-RU')
const metricFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

function percent(value: number) { return `${percentFormat.format(value * 100)}%` }
function clampThreshold(value: number) { return Math.min(1, Math.max(0, Math.round(value * 100) / 100)) }
function sameThreshold(left: number, right: number) { return Math.abs(left - right) < 0.000001 }

function displayModel(modelId: string) {
  const names: Record<string, string> = {
    catboost: 'CatBoost',
    lightgbm: 'LightGBM',
    xgboost: 'XGBoost',
    gbdt_mean: 'GBDT mean',
  }
  return names[modelId] ?? modelId
}

function MetricCard({ label, value, bar, tone = 'teal', detail }: {
  label: string
  value: string
  bar: number
  tone?: 'teal' | 'cyan'
  detail?: string
}) {
  return <article className="threshold-metric-card">
    <small>{label}</small>
    <strong>{value}</strong>
    {detail && <span>{detail}</span>}
    <div className="threshold-metric-track"><i className={tone} style={{ width: `${Math.max(0, Math.min(1, bar)) * 100}%` }} /></div>
  </article>
}

function ThresholdCurve({ points, metrics }: { points: ThresholdMetrics[]; metrics: ThresholdMetrics }) {
  const width = 640
  const height = 236
  const left = 42
  const right = 18
  const top = 18
  const bottom = 34
  const plotWidth = width - left - right
  const plotHeight = height - top - bottom
  const x = (threshold: number) => left + threshold * plotWidth
  const y = (value: number) => top + (1 - Math.max(0, Math.min(1, value))) * plotHeight
  const pathFor = (selector: (point: ThresholdMetrics) => number) => points
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${x(point.threshold).toFixed(2)} ${y(selector(point)).toFixed(2)}`)
    .join(' ')
  const grid = [0, .25, .5, .75, 1]

  return <div className="threshold-chart-shell">
    <svg className="threshold-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Зависимость Recall и Precision от диагностического порога">
      {grid.map(value => <g key={value}>
        <line className="threshold-chart-grid" x1={left} x2={width - right} y1={y(value)} y2={y(value)} />
        <text className="threshold-chart-label" x={left - 8} y={y(value) + 4} textAnchor="end">{Math.round(value * 100)}</text>
      </g>)}
      {[0, .2, .4, .6, .8, 1].map(value => <g key={value}>
        <line className="threshold-chart-grid vertical" x1={x(value)} x2={x(value)} y1={top} y2={height - bottom} />
        <text className="threshold-chart-label" x={x(value)} y={height - 9} textAnchor="middle">{value.toFixed(1).replace('.', ',')}</text>
      </g>)}
      <path className="threshold-chart-line recall" d={pathFor(point => point.recall)} />
      <path className="threshold-chart-line precision" d={pathFor(point => point.precision)} />
      <line className="threshold-chart-marker" x1={x(metrics.threshold)} x2={x(metrics.threshold)} y1={top} y2={height - bottom} />
      <circle className="threshold-chart-dot recall" cx={x(metrics.threshold)} cy={y(metrics.recall)} r="5" />
      <circle className="threshold-chart-dot precision" cx={x(metrics.threshold)} cy={y(metrics.precision)} r="5" />
    </svg>
    <div className="threshold-chart-legend">
      <span><i className="recall" />Recall</span>
      <span><i className="precision" />Precision</span>
      <strong>Порог {thresholdFormat.format(metrics.threshold)}</strong>
    </div>
  </div>
}

function ErrorCard({ label, count, rate, note, tone }: {
  label: string
  count: number
  rate: number
  note: string
  tone: 'fn' | 'fp'
}) {
  return <article className={`threshold-error-card ${tone}`}>
    <div><small>{label}</small><strong>{integerFormat.format(count)}</strong></div>
    <div className="threshold-error-rate"><b>{percent(rate)}</b><span>{note}</span></div>
    <div className="threshold-error-track"><i style={{ width: `${Math.max(0, Math.min(1, rate)) * 100}%` }} /></div>
  </article>
}

export function ThresholdPage() {
  const [result, setResult] = useState<ResultOverview | null>(null)
  const [savedMetrics, setSavedMetrics] = useState<ThresholdMetrics | null>(null)
  const [metrics, setMetrics] = useState<ThresholdMetrics | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [sweep, setSweep] = useState<ThresholdMetrics[]>([])
  const [loading, setLoading] = useState(true)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void getCurrentResult()
      .then(value => {
        if (controller.signal.aborted) return
        setResult(value)
        setSavedMetrics(value.threshold)
        setMetrics(value.threshold)
        setSelected(value.threshold.threshold)
      })
      .catch(reason => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить результат.')
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })

    void getCurrentThresholdSweep(controller.signal)
      .then(value => { if (!controller.signal.aborted) setSweep(value) })
      .catch(() => { if (!controller.signal.aborted) setSweep([]) })

    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (selected === null || !savedMetrics) return
    if (sameThreshold(selected, savedMetrics.threshold)) {
      setMetrics(savedMetrics)
      setPreviewLoading(false)
      setPreviewError(null)
      return
    }

    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setPreviewLoading(true)
      setPreviewError(null)
      void getCurrentThresholdPreview(selected, controller.signal)
        .then(value => { if (!controller.signal.aborted) setMetrics(value) })
        .catch(reason => {
          if (!controller.signal.aborted) setPreviewError(reason instanceof Error ? reason.message : 'Не удалось пересчитать метрики.')
        })
        .finally(() => { if (!controller.signal.aborted) setPreviewLoading(false) })
    }, 180)

    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [selected, savedMetrics])

  const unsaved = selected !== null && savedMetrics !== null && !sameThreshold(selected, savedMetrics.threshold)
  const summary = result?.summary
  const targetEvents = metrics ? metrics.tp + metrics.fn : 0
  const fnRate = metrics && metrics.tp + metrics.fn ? metrics.fn / (metrics.tp + metrics.fn) : 0
  const fpRate = metrics && metrics.tp + metrics.fp ? metrics.fp / (metrics.tp + metrics.fp) : 0
  const interpretation = useMemo(() => {
    if (!metrics) return null
    return {
      first: `При пороге ${thresholdFormat.format(metrics.threshold)} модель выделяет ${percent(metrics.above_threshold_share)} объектов и находит ${percent(metrics.recall)} фактических целевых событий.`,
      second: `При этом пропущено ${integerFormat.format(metrics.fn)} событий, а ${integerFormat.format(metrics.fp)} объектов являются ложными срабатываниями.`,
    }
  }, [metrics])

  const saveScenario = async () => {
    if (selected === null || !unsaved) return
    setSaving(true)
    setPreviewError(null)
    try {
      const value = await updateCurrentThreshold(selected)
      setSavedMetrics(value)
      setMetrics(value)
      setSelected(value.threshold)
    } catch (reason) {
      setPreviewError(reason instanceof Error ? reason.message : 'Не удалось сохранить выбранный порог.')
    } finally {
      setSaving(false)
    }
  }

  const cancelChanges = () => {
    if (!savedMetrics) return
    setSelected(savedMetrics.threshold)
    setMetrics(savedMetrics)
    setPreviewError(null)
  }

  const setThreshold = (value: number) => setSelected(clampThreshold(value))

  return <main className="workspace result-workspace threshold-workspace threshold-explorer">
    <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index < 4 ? 'completed' : 'active'}><span>{index < 4 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>

    <header className="threshold-explorer-header">
      <div className="threshold-breadcrumbs"><button className="text-action" onClick={() => navigate(routes.result)}>← Назад к результату модели</button><span>Результат модели</span><b>/</b><span>Исследование порога</span></div>
      <div className="threshold-title-row"><div><h1>Исследование порога</h1><p>Посмотрите, как изменение порога влияет на количество найденных и пропущенных событий.</p></div>{unsaved && <span className="threshold-unsaved"><i />Изменения не сохранены</span>}</div>
    </header>

    {error && <section className="result-error" role="alert"><strong>Исследование порога недоступно</strong><p>{error}</p><button className="back-action" onClick={() => navigate(routes.result)}>← Вернуться к результату</button></section>}
    {loading && <p className="feature-loading">Загружаем данные исследования порога…</p>}

    {!loading && result && summary && metrics && savedMetrics && selected !== null && <>
      <aside className="threshold-explorer-notice"><Icon name="info" size={20} /><p>Порог не изменяет прогнозы модели. Он определяет, начиная с какой оценки объект относится к положительному классу.</p></aside>

      <section className="threshold-context-strip panel" aria-label="Контекст исследования порога">
        <div><span className="threshold-context-icon"><Icon name="algorithm" size={23} /></span><small>Модель</small><strong>{displayModel(summary.model_id)}</strong></div>
        <div><span className="threshold-context-icon"><Icon name="file" size={23} /></span><small>Источник оценок</small><strong>OOF</strong></div>
        <div><span className="threshold-context-icon"><Icon name="chart" size={23} /></span><small>Объектов</small><strong>{integerFormat.format(summary.object_count)}</strong></div>
        <div><span className="threshold-context-icon"><Icon name="layers" size={23} /></span><small>Целевых событий</small><strong>{integerFormat.format(targetEvents)}</strong></div>
        <div><span className="threshold-context-icon"><Icon name="settings" size={23} /></span><small>Исходный порог</small><strong>{thresholdFormat.format(DEFAULT_THRESHOLD)}</strong></div>
      </section>

      <section className="threshold-selector panel">
        <div className="threshold-selector-title"><h2>Порог <Icon name="info" size={16} /></h2><span className="threshold-selected-badge">{thresholdFormat.format(selected)}</span></div>
        <div className="threshold-slider-row">
          <div className="threshold-slider-wrap">
            <input aria-label="Диагностический порог" type="range" min="0" max="1" step="0.01" value={selected} onChange={event => setThreshold(Number(event.currentTarget.value))} />
            <span className="threshold-default-marker" style={{ left: `${DEFAULT_THRESHOLD * 100}%` }}><i /><small>Исходный {thresholdFormat.format(DEFAULT_THRESHOLD)}</small></span>
            <div className="threshold-range-labels"><span>0,00</span><span>1,00</span></div>
          </div>
          <input className="threshold-number-input" aria-label="Точное значение порога" type="number" min="0" max="1" step="0.01" value={selected.toFixed(2)} onChange={event => setThreshold(Number(event.currentTarget.value))} />
          <span className="threshold-scenario-badge">Диагностический сценарий</span>
          <button className="secondary-action" disabled={sameThreshold(selected, DEFAULT_THRESHOLD)} onClick={() => setThreshold(DEFAULT_THRESHOLD)}>Вернуть исходный порог</button>
        </div>
        <p className="threshold-preview-status">{previewLoading ? 'Пересчитываем метрики…' : previewError ? 'Предпросмотр временно недоступен. Выбранный порог всё равно можно сохранить.' : 'Изменяйте порог — метрики и графики пересчитываются автоматически.'}</p>
      </section>

      <section className="threshold-metrics panel">
        <h2>Основные метрики при текущем пороге <Icon name="info" size={16} /></h2>
        <div className="threshold-metrics-grid">
          <MetricCard label="Recall" value={percent(metrics.recall)} bar={metrics.recall} />
          <MetricCard label="Precision" value={percent(metrics.precision)} bar={metrics.precision} tone="cyan" />
          <MetricCard label="F1" value={metricFormat.format(metrics.f1)} bar={metrics.f1} />
          <MetricCard label="Объектов выше порога" value={integerFormat.format(metrics.above_threshold_count)} detail={percent(metrics.above_threshold_share)} bar={metrics.above_threshold_share} tone="cyan" />
        </div>
        {interpretation && <div className="threshold-interpretation"><Icon name="file" size={24} /><div><strong>{interpretation.first}</strong><p>{interpretation.second}</p></div></div>}
      </section>

      <div className="threshold-analysis-grid">
        <section className="threshold-chart-panel panel">
          <h2>Как меняются Recall и Precision <Icon name="info" size={16} /></h2>
          {sweep.length ? <ThresholdCurve points={sweep} metrics={metrics} /> : <p className="result-muted">График временно недоступен. Текущие метрики продолжают работать.</p>}
        </section>

        <section className="threshold-errors-panel panel">
          <h2>Ошибки при текущем пороге <Icon name="info" size={16} /></h2>
          <ErrorCard label="Пропущенные события (FN)" count={metrics.fn} rate={fnRate} note={`от всех фактических целевых событий (${integerFormat.format(targetEvents)})`} tone="fn" />
          <ErrorCard label="Ложные срабатывания (FP)" count={metrics.fp} rate={fpRate} note={`среди объектов выше порога (${integerFormat.format(metrics.above_threshold_count)})`} tone="fp" />
          <aside className="threshold-ranking-note"><Icon name="info" size={18} /><span>Gini, ROC-AUC и PR-AUC не зависят от выбранного порога.</span></aside>
        </section>
      </div>

      <details className="threshold-details panel">
        <summary><Icon name="table" size={20} /><strong>Подробная таблица ошибок</strong><small>TP, FP, TN, FN и метрики по всем значениям порога.</small><span>⌄</span></summary>
        <div className="threshold-table-wrap"><table><thead><tr><th>Порог</th><th>Recall</th><th>Precision</th><th>F1</th><th>TP</th><th>FP</th><th>TN</th><th>FN</th></tr></thead><tbody>{sweep.map(point => <tr key={point.threshold}><td>{thresholdFormat.format(point.threshold)}</td><td>{percent(point.recall)}</td><td>{percent(point.precision)}</td><td>{metricFormat.format(point.f1)}</td><td>{integerFormat.format(point.tp)}</td><td>{integerFormat.format(point.fp)}</td><td>{integerFormat.format(point.tn)}</td><td>{integerFormat.format(point.fn)}</td></tr>)}</tbody></table></div>
      </details>

      <details className="threshold-details panel">
        <summary><Icon name="file" size={20} /><strong>Технические сведения</strong><small>Источник оценок, текущий сценарий и параметры расчёта.</small><span>⌄</span></summary>
        <dl className="threshold-technical-list">
          <div><dt>Artifact ID</dt><dd>{summary.artifact_id}</dd></div>
          <div><dt>Источник оценок</dt><dd>OOF</dd></div>
          <div><dt>Исходный порог</dt><dd>{thresholdFormat.format(DEFAULT_THRESHOLD)}</dd></div>
          <div><dt>Сохранённый порог</dt><dd>{thresholdFormat.format(savedMetrics.threshold)}</dd></div>
          <div><dt>Точек графика</dt><dd>{sweep.length || '—'}</dd></div>
        </dl>
      </details>

      <footer className="threshold-explorer-footer">
        <button className="back-action" onClick={() => navigate(routes.result)}>← Назад к результату модели</button>
        <div><button className="secondary-action" disabled={!unsaved || saving} onClick={cancelChanges}>Отменить изменения</button><button className="primary-action" disabled={!unsaved || saving || previewLoading} onClick={saveScenario}>{saving ? 'Сохраняем…' : 'Сохранить сценарий'}</button></div>
      </footer>
    </>}
  </main>
}
