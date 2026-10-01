import { useEffect, useRef, useState } from 'react'
import { getCurrentResult, updateCurrentThreshold, type ResultOverview, type ThresholdMetrics } from '../api/result'
import { Sidebar } from '../components/Sidebar'
import { navigate, routes } from '../routing'

const metricFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const percentFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const integerFormat = new Intl.NumberFormat('ru-RU')
const thresholdFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function metric(value: number) { return metricFormat.format(value) }
function percentage(value: number) { return `${percentFormat.format(value * 100)}%` }

export function ThresholdPage({ onHome }: { onHome: () => void }) {
  const [result, setResult] = useState<ResultOverview | null>(null)
  const [metrics, setMetrics] = useState<ThresholdMetrics | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [retry, setRetry] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const generation = useRef(0)
  const inFlight = useRef(false)
  const forceCommit = useRef(false)
  const latestCommittedMetrics = useRef<ThresholdMetrics | null>(null)

  useEffect(() => {
    let cancelled = false
    void getCurrentResult()
      .then(value => {
        if (cancelled) return
        setResult(value)
        setMetrics(value.threshold)
        latestCommittedMetrics.current = value.threshold
        setSelected(value.threshold.threshold)
      })
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить результат обучения.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (selected === null || !result || (selected === metrics?.threshold && !forceCommit.current)) return
    const requested = selected
    const requestGeneration = generation.current
    const timer = window.setTimeout(() => {
      if (inFlight.current) return
      inFlight.current = true
      forceCommit.current = false
      setSaving(true)
      setError(null)
      void updateCurrentThreshold(requested)
        .then(value => {
          latestCommittedMetrics.current = value
          if (generation.current === requestGeneration) setMetrics(value)
        })
        .catch(reason => {
          if (generation.current === requestGeneration) {
            setError(reason instanceof Error ? reason.message : 'Не удалось изменить диагностический порог.')
            const committed = latestCommittedMetrics.current
            if (committed) {
              setMetrics(committed)
              setSelected(committed.threshold)
            } else {
              setSelected(metrics?.threshold ?? requested)
            }
          }
        })
        .finally(() => {
          inFlight.current = false
          setSaving(false)
          if (generation.current !== requestGeneration) {
            forceCommit.current = true
            setRetry(value => value + 1)
          }
        })
    }, 260)
    return () => window.clearTimeout(timer)
  }, [selected, result, metrics?.threshold, retry])

  const summary = result?.summary
  const handleThresholdChange = (value: number) => {
    generation.current += 1
    setSelected(value)
  }

  return <div className="app-shell features-shell">
    <Sidebar active="analysis" onHome={onHome} />
    <main className="workspace result-workspace threshold-workspace">
      <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index < 4 ? 'completed' : 'active'}><span>{index < 4 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>
      <header className="result-header"><button className="threshold-back-link" onClick={() => navigate(routes.result)}>← Назад к результату</button><p className="eyebrow">Шаг 5 из 5 · Результат</p><h1>Исследование порога</h1><p>Посмотрите, как диагностический порог влияет на метрики классификации.</p></header>
      {error && <section className="result-error" role="alert"><strong>Не удалось обновить результат</strong><p>{error}</p><button className="secondary-action" onClick={() => navigate(routes.result)}>Вернуться к результату</button></section>}
      {loading && <p className="feature-loading">Загружаем сохранённый результат…</p>}
      {!loading && result && metrics && selected !== null && summary && <>
        <section className="threshold-notice panel"><b>i</b><p>Изменение порога не переобучает модель и не меняет оценки объектов. Порог является диагностическим и не выбирается AXION автоматически как оптимальный или бизнес-порог.</p></section>

        <section className="result-section"><h2>Качество ранжирования</h2><div className="result-ranking-grid">
          <article className="result-ranking panel"><small>Gini</small><strong>{metric(summary.gini)}</strong></article>
          <article className="result-ranking panel"><small>ROC-AUC</small><strong>{metric(summary.roc_auc)}</strong></article>
          <article className="result-ranking panel"><small>PR-AUC</small><strong>{metric(summary.pr_auc)}</strong></article>
        </div><p className="result-note">Gini, ROC-AUC и PR-AUC не зависят от выбранного порога.</p></section>

        <section className="threshold-control panel" aria-labelledby="threshold-label">
          <div className="threshold-control-heading"><div><h2 id="threshold-label">Диагностический порог</h2><p>Выберите значение от 0,00 до 1,00 с шагом 0,01.</p></div><strong aria-live="polite">{thresholdFormat.format(selected)}</strong></div>
          <input aria-label="Диагностический порог" type="range" min="0" max="1" step="0.01" value={selected} onChange={event => handleThresholdChange(Number(event.currentTarget.value))} />
          <div className="threshold-range-labels"><span>0,00</span><span>1,00</span></div>
          <p className="threshold-save-status" aria-live="polite">{saving ? 'Обновляем метрики…' : metrics.threshold === selected ? 'Метрики рассчитаны для выбранного порога.' : 'Изменения будут применены после выбора значения.'}</p>
        </section>

        <section className="result-section"><div className="result-section-heading"><div><h2>Основные метрики при пороге {thresholdFormat.format(metrics.threshold)}</h2></div></div><div className="result-threshold-grid">
          <article className="result-threshold-card panel"><small>Recall</small><strong>{metric(metrics.recall)}</strong></article>
          <article className="result-threshold-card panel"><small>Precision</small><strong>{metric(metrics.precision)}</strong></article>
          <article className="result-threshold-card panel"><small>F1</small><strong>{metric(metrics.f1)}</strong></article>
          <article className="result-threshold-card panel"><small>Объекты выше порога</small><strong>{integerFormat.format(metrics.above_threshold_count)}</strong><span>{percentage(metrics.above_threshold_share)} объектов</span></article>
          <article className="result-threshold-card panel"><small>TP · найденные события</small><strong>{integerFormat.format(metrics.tp)}</strong></article>
          <article className="result-threshold-card panel"><small>TN · верно исключённые</small><strong>{integerFormat.format(metrics.tn)}</strong></article>
          <article className="result-threshold-card panel threshold-fp"><small>FP · ложные срабатывания</small><strong>{integerFormat.format(metrics.fp)}</strong></article>
          <article className="result-threshold-card panel threshold-fn"><small>FN · пропущенные события</small><strong>{integerFormat.format(metrics.fn)}</strong></article>
        </div></section>

        <section className="threshold-curves panel"><h2>Зависимость метрик от порога</h2><p>График зависимости метрик от порога появится только при наличии отдельного backend-контракта для sweep.</p></section>
        <button className="secondary-action threshold-back-button" onClick={() => navigate(routes.result)}>← Назад к результату</button>
      </>}
    </main>
  </div>
}
