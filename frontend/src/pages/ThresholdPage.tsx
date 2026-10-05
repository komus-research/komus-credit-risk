import { useEffect, useId, useMemo, useState } from 'react'
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
const ratioFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const compactCostFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const rubleFormat = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 })

function percent(value: number) { return `${percentFormat.format(value * 100)}%` }
function sanitizeCostInput(value: string) {
  const digits = value.replace(/\D/g, '').replace(/^0+(?=\d)/, '')
  return digits.slice(0, 15)
}
function formatCostInput(value: string) {
  if (!value) return ''
  const parsed = Number(value)
  return Number.isFinite(parsed) ? integerFormat.format(parsed) : value
}
function parseScenarioCost(value: string) {
  if (!value.trim()) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}
function compactCostLabel(value: number | null) {
  if (value === null) return 'Введите сумму за одну ошибку'
  if (value >= 1_000_000_000) return `${compactCostFormat.format(value / 1_000_000_000)} млрд ₽`
  if (value >= 1_000_000) return `${compactCostFormat.format(value / 1_000_000)} млн ₽`
  if (value >= 1_000) return `${compactCostFormat.format(value / 1_000)} тыс. ₽`
  return `${integerFormat.format(value)} ₽`
}
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
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
  const width = 640
  const height = 236
  const left = 58
  const right = 18
  const top = 18
  const bottom = 40
  const plotWidth = width - left - right
  const plotHeight = height - top - bottom
  const x = (threshold: number) => left + threshold * plotWidth
  const y = (value: number) => top + (1 - Math.max(0, Math.min(1, value))) * plotHeight
  const hasPositivePredictions = (point: ThresholdMetrics) => point.above_threshold_count > 0
  const recallAt = (point: ThresholdMetrics) => hasPositivePredictions(point) ? point.recall : null
  const precisionAt = (point: ThresholdMetrics) => hasPositivePredictions(point) ? point.precision : null
  const pathFor = (selector: (point: ThresholdMetrics) => number | null) => {
    let drawing = false
    return points
      .map(point => {
        const value = selector(point)
        if (value === null || !Number.isFinite(value)) {
          drawing = false
          return ''
        }
        const command = drawing ? 'L' : 'M'
        drawing = true
        return `${command} ${x(point.threshold).toFixed(2)} ${y(value).toFixed(2)}`
      })
      .filter(Boolean)
      .join(' ')
  }
  const grid = [0, .25, .5, .75, 1]
  const hovered = hoveredIndex === null ? null : points[hoveredIndex]

  const handlePointerMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    if (!rect.width) return
    const viewX = ((event.clientX - rect.left) / rect.width) * width
    const threshold = Math.max(0, Math.min(1, (viewX - left) / plotWidth))
    let nearestIndex = 0
    let nearestDistance = Number.POSITIVE_INFINITY
    points.forEach((point, index) => {
      const distance = Math.abs(point.threshold - threshold)
      if (distance < nearestDistance) {
        nearestDistance = distance
        nearestIndex = index
      }
    })
    setHoveredIndex(nearestIndex)
  }

  const hoveredPrecision = hovered ? precisionAt(hovered) : null

  return <div className="threshold-chart-shell">
    <svg
      className="threshold-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Зависимость Recall и Precision от диагностического порога"
      onMouseMove={handlePointerMove}
      onMouseLeave={() => setHoveredIndex(null)}
    >
      {grid.map(value => <g key={value}>
        <line className="threshold-chart-grid" x1={left} x2={width - right} y1={y(value)} y2={y(value)} />
        <text className="threshold-chart-label" x={left - 8} y={y(value) + 4} textAnchor="end">{Math.round(value * 100)}</text>
      </g>)}
      {[0, .2, .4, .6, .8, 1].map(value => <g key={value}>
        <line className="threshold-chart-grid vertical" x1={x(value)} x2={x(value)} y1={top} y2={height - bottom} />
        <text className="threshold-chart-label" x={x(value)} y={height - 18} textAnchor="middle">{value.toFixed(1).replace('.', ',')}</text>
      </g>)}
      <text className="threshold-chart-axis-label" x={15} y={top + plotHeight / 2} textAnchor="middle" transform={`rotate(-90 15 ${top + plotHeight / 2})`}>Доля, %</text>
      <text className="threshold-chart-axis-label" x={width - right} y={height - 3} textAnchor="end">Порог</text>
      <path className="threshold-chart-line recall" d={pathFor(recallAt)} />
      <path className="threshold-chart-line precision" d={pathFor(precisionAt)} />
      <line className="threshold-chart-marker" x1={x(metrics.threshold)} x2={x(metrics.threshold)} y1={top} y2={height - bottom} />
      {hasPositivePredictions(metrics) && <circle className="threshold-chart-dot recall" cx={x(metrics.threshold)} cy={y(metrics.recall)} r="5" />}
      {hasPositivePredictions(metrics) && <circle className="threshold-chart-dot precision" cx={x(metrics.threshold)} cy={y(metrics.precision)} r="5" />}
      {hovered && <>
        <line className="threshold-chart-hover-marker" x1={x(hovered.threshold)} x2={x(hovered.threshold)} y1={top} y2={height - bottom} />
        {hasPositivePredictions(hovered) && <circle className="threshold-chart-hover-dot recall" cx={x(hovered.threshold)} cy={y(hovered.recall)} r="4.5" />}
        {hoveredPrecision !== null && <circle className="threshold-chart-hover-dot precision" cx={x(hovered.threshold)} cy={y(hoveredPrecision)} r="4.5" />}
      </>}
    </svg>
    <div className="threshold-chart-hover-readout" aria-live="polite">
      {hovered && <>
        <strong>Порог {thresholdFormat.format(hovered.threshold)}</strong>
        <span><i className="recall" />Recall <b>{percent(hovered.recall)}</b></span>
        <span><i className="precision" />Precision <b>{hoveredPrecision === null ? '—' : percent(hoveredPrecision)}</b></span>
        {hoveredPrecision === null && <small>нет объектов выше порога</small>}
      </>}
    </div>
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

function ThresholdInfoTooltip({ title, body, note }: { title: string; body: string; note?: string }) {
  const [open, setOpen] = useState(false)
  const id = useId()

  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [open])

  return <span
    className="threshold-info-wrap"
    onMouseEnter={() => setOpen(true)}
    onMouseLeave={() => setOpen(false)}
    onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false) }}
  >
    <button
      type="button"
      className="threshold-info-button"
      aria-label={`Подробнее: ${title}`}
      aria-describedby={open ? id : undefined}
      onFocus={() => setOpen(true)}
      onClick={event => { event.stopPropagation(); setOpen(value => !value) }}
    ><Icon name="info" size={14} /></button>
    {open && <span className="threshold-info-tooltip" id={id} role="tooltip">
      <strong>{title}</strong>
      <p>{body}</p>
      {note && <p className="threshold-info-note">{note}</p>}
    </span>}
  </span>
}

function CostScenario({ metrics, fnCostInput, fpCostInput, onFnCostChange, onFpCostChange }: {
  metrics: ThresholdMetrics
  fnCostInput: string
  fpCostInput: string
  onFnCostChange: (value: string) => void
  onFpCostChange: (value: string) => void
}) {
  const fnCost = parseScenarioCost(fnCostInput)
  const fpCost = parseScenarioCost(fpCostInput)
  const fnLoss = fnCost === null ? null : metrics.fn * fnCost
  const fpLoss = fpCost === null ? null : metrics.fp * fpCost
  const totalLoss = fnLoss === null || fpLoss === null ? null : fnLoss + fpLoss
  const totalErrors = metrics.fn + metrics.fp
  const fnShare = totalErrors ? metrics.fn / totalErrors : 0
  const fpShare = totalErrors ? metrics.fp / totalErrors : 0
  const errorRatio = metrics.fp > 0 ? `${ratioFormat.format(metrics.fn / metrics.fp)} : 1` : metrics.fn > 0 ? '∞ : 1' : '0 : 0'

  const costText = (value: number | null) => value === null ? '—' : rubleFormat.format(value)

  return <div className="threshold-cost-scenario">
    <div className="threshold-cost-counts">
      <div className="fn"><small>Пропущенные события (FN)</small><strong>{integerFormat.format(metrics.fn)}</strong><div><i style={{ width: `${fnShare * 100}%` }} /></div></div>
      <div className="fp"><small>Ложные срабатывания (FP)</small><strong>{integerFormat.format(metrics.fp)}</strong><div><i style={{ width: `${fpShare * 100}%` }} /></div></div>
    </div>

    <div className="threshold-cost-inputs">
      <div className="threshold-cost-field">
        <div className="threshold-cost-field-label">
          <span>Стоимость FN</span>
          <ThresholdInfoTooltip
            title="Стоимость FN — пропущенного события"
            body="FN (False Negative) — фактическое целевое событие произошло, но оценка объекта оказалась ниже выбранного порога, поэтому модель не отнесла его к положительному классу."
            note="Укажите среднюю денежную стоимость одного такого случая именно для вашего бизнес-сценария. Это не стоимость, рассчитанная моделью, и не утверждённая сумма Комуса."
          />
        </div>
        <div className="threshold-cost-input-box">
          <input
            aria-label="Сценарная стоимость FN"
            inputMode="numeric"
            value={formatCostInput(fnCostInput)}
            placeholder="500 000"
            onChange={event => onFnCostChange(sanitizeCostInput(event.currentTarget.value))}
          />
          <b>₽</b>
        </div>
        <small className="threshold-cost-magnitude">{compactCostLabel(fnCost)}</small>
      </div>

      <div className="threshold-cost-field">
        <div className="threshold-cost-field-label">
          <span>Стоимость FP</span>
          <ThresholdInfoTooltip
            title="Стоимость FP — ложного срабатывания"
            body="FP (False Positive) — фактического целевого события не было, но оценка объекта оказалась выше выбранного порога, поэтому модель отнесла его к положительному классу."
            note="Укажите среднюю стоимость одного такого случая по вашей политике: например, стоимость лишней проверки или необоснованного ограничения клиента — только если бизнес именно так трактует FP."
          />
        </div>
        <div className="threshold-cost-input-box">
          <input
            aria-label="Сценарная стоимость FP"
            inputMode="numeric"
            value={formatCostInput(fpCostInput)}
            placeholder="5 000"
            onChange={event => onFpCostChange(sanitizeCostInput(event.currentTarget.value))}
          />
          <b>₽</b>
        </div>
        <small className="threshold-cost-magnitude">{compactCostLabel(fpCost)}</small>
      </div>
    </div>

    <div className="threshold-error-ratio">
      <div>
        <strong>Соотношение ошибок
          <ThresholdInfoTooltip
            title="Соотношение FN : FP"
            body="Это соотношение количества ошибок при текущем пороге, а не их денежной стоимости. Например, 9,9 : 1 означает примерно 9,9 пропущенного события на одно ложное срабатывание."
            note="При движении порога FN и FP меняются автоматически, поэтому это соотношение тоже пересчитывается."
          />
        </strong>
        <b>FN : FP = {errorRatio}</b>
      </div>
      <div><span className="fn"><i />Пропущенные события — {percent(fnShare)}</span><span className="fp"><i />Ложные срабатывания — {percent(fpShare)}</span></div>
    </div>

    <div className="threshold-loss-estimate">
      <h3>Оценка бизнес-потерь при текущем пороге</h3>
      <div><span className="fn"><i />Пропущенный дефолт (FN)</span><small>{integerFormat.format(metrics.fn)} × {fnCost === null ? '—' : rubleFormat.format(fnCost)}</small><strong>{costText(fnLoss)}</strong></div>
      <div><span className="fp"><i />Ложное срабатывание (FP)</span><small>{integerFormat.format(metrics.fp)} × {fpCost === null ? '—' : rubleFormat.format(fpCost)}</small><strong>{costText(fpLoss)}</strong></div>
      <footer><b>Общие потери</b><strong>{costText(totalLoss)}</strong></footer>
    </div>

    <small className="threshold-cost-scenario-note">Исследовательский сценарий: стоимость FN/FP задаётся пользователем и не является утверждённой политикой Комуса.</small>
  </div>
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
  const [appliedNotice, setAppliedNotice] = useState<string | null>(null)
  const [errorPanelTab, setErrorPanelTab] = useState<'errors' | 'cost'>('errors')
  const [fnCostInput, setFnCostInput] = useState('')
  const [fpCostInput, setFpCostInput] = useState('')
  const sweepByStep = useMemo(
    () => new Map(sweep.map(point => [Math.round(point.threshold * 100), point])),
    [sweep],
  )

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

    const sweepPoint = sweepByStep.get(Math.round(selected * 100))
    if (sweepPoint && sameThreshold(sweepPoint.threshold, selected)) {
      setMetrics(sweepPoint)
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
  }, [selected, savedMetrics, sweepByStep])

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

  const applyThreshold = async () => {
    if (selected === null || !unsaved) return
    setSaving(true)
    setPreviewError(null)
    try {
      const value = await updateCurrentThreshold(selected)
      setSavedMetrics(value)
      setMetrics(value)
      setSelected(value.threshold)
      setAppliedNotice(`Порог ${thresholdFormat.format(value.threshold)} применён к текущему результату`)
    } catch (reason) {
      setPreviewError(reason instanceof Error ? reason.message : 'Не удалось применить выбранный порог.')
    } finally {
      setSaving(false)
    }
  }

  const cancelChanges = () => {
    if (!savedMetrics) return
    setSelected(savedMetrics.threshold)
    setMetrics(savedMetrics)
    setPreviewError(null)
    setAppliedNotice(null)
  }

  const setThreshold = (value: number) => {
    const next = clampThreshold(value)
    setAppliedNotice(null)
    setSelected(next)
    const sweepPoint = sweepByStep.get(Math.round(next * 100))
    if (sweepPoint && sameThreshold(sweepPoint.threshold, next)) {
      setMetrics(sweepPoint)
      setPreviewLoading(false)
      setPreviewError(null)
    }
  }

  return <main className="workspace result-workspace threshold-workspace threshold-explorer">
    <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index < 4 ? 'completed' : 'active'}><span>{index < 4 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>

    <header className="threshold-explorer-header">
      <div className="threshold-breadcrumbs"><button className="text-action" onClick={() => navigate(routes.result)}>← Назад к результату модели</button><span>Результат модели</span><b>/</b><span>Исследование порога</span></div>
      <div className="threshold-title-row"><div><h1>Исследование порога</h1><p>Посмотрите, как изменение порога влияет на количество найденных и пропущенных событий.</p></div>{unsaved ? <span className="threshold-unsaved"><i />Изменения не применены</span> : appliedNotice ? <span className="threshold-applied"><i />{appliedNotice}</span> : null}</div>
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
        <p className="threshold-preview-status">{previewLoading ? 'Пересчитываем метрики…' : previewError ? 'Предпросмотр временно недоступен. Выбранный порог всё равно можно применить.' : appliedNotice ? 'Порог применён к текущему результату. Модель не переобучалась.' : 'Изменяйте порог — метрики и графики пересчитываются автоматически.'}</p>
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
          <div className="threshold-error-tabs" role="tablist" aria-label="Ошибки и цена ошибки">
            <button className={errorPanelTab === 'errors' ? 'active' : ''} role="tab" aria-selected={errorPanelTab === 'errors'} onClick={() => setErrorPanelTab('errors')}>Ошибки при текущем пороге</button>
            <div className="threshold-cost-tab-control">
              <button className={errorPanelTab === 'cost' ? 'active' : ''} role="tab" aria-selected={errorPanelTab === 'cost'} onClick={() => setErrorPanelTab('cost')}>Цена ошибки</button>
              <ThresholdInfoTooltip
                title="Цена ошибки"
                body="Этот режим переводит текущие FN и FP в денежный исследовательский сценарий. Формула простая: FN × стоимость одного FN + FP × стоимость одного FP."
                note="Порог меняет количество FN/FP, а введённые вами суммы меняют денежную оценку. Модель при этом не переобучается, а значения стоимости не считаются утверждённой политикой Комуса."
              />
            </div>
          </div>
          {errorPanelTab === 'errors' ? <>
            <ErrorCard label="Пропущенные события (FN)" count={metrics.fn} rate={fnRate} note={`от всех фактических целевых событий (${integerFormat.format(targetEvents)})`} tone="fn" />
            <ErrorCard label="Ложные срабатывания (FP)" count={metrics.fp} rate={fpRate} note={`среди объектов выше порога (${integerFormat.format(metrics.above_threshold_count)})`} tone="fp" />
            <aside className="threshold-ranking-note"><Icon name="info" size={18} /><span>Gini, ROC-AUC и PR-AUC не зависят от выбранного порога.</span></aside>
          </> : <CostScenario metrics={metrics} fnCostInput={fnCostInput} fpCostInput={fpCostInput} onFnCostChange={setFnCostInput} onFpCostChange={setFpCostInput} />}
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
          <div><dt>Применённый порог</dt><dd>{thresholdFormat.format(savedMetrics.threshold)}</dd></div>
          <div><dt>Точек графика</dt><dd>{sweep.length || '—'}</dd></div>
        </dl>
      </details>

      <footer className="threshold-explorer-footer">
        <button className="back-action" onClick={() => navigate(routes.result)}>← Назад к результату модели</button>
        <div><button className="secondary-action" disabled={!unsaved || saving} onClick={cancelChanges}>Отменить изменения</button><button className="primary-action" title="Применить выбранный порог к текущему результату. Модель не переобучается." disabled={!unsaved || saving || previewLoading} onClick={applyThreshold}>{saving ? 'Применяем…' : 'Применить порог'}</button></div>
      </footer>
    </>}
  </main>
}
