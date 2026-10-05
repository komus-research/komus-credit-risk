import { useEffect, useState } from 'react'
import {
  getCurrentGlobalOOFExplanation,
  getCurrentGlobalOOFStatus,
  getCurrentResult,
  GlobalOOFAPIError,
  type GlobalOOFOperation,
  runCurrentGlobalOOF,
  type GlobalOOFExplanation,
  type ResultCapture,
  type ResultOverview,
} from '../api/result'
import { Icon } from '../components/Icon'
import { navigate, routes } from '../routing'

const numberFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const percentFormat = new Intl.NumberFormat('ru-RU', { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 })
const integerFormat = new Intl.NumberFormat('ru-RU')
const thresholdFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const unavailable = 'Действие пока недоступно: соответствующая возможность не подключена.'

function metric(value: number) { return numberFormat.format(value) }
function percent(value: number) { return percentFormat.format(value) }
function errorRate(numerator: number, denominator: number) { return denominator === 0 ? '—' : percent(numerator / denominator) }

type GlobalPreviewStatus = 'idle' | 'loading' | 'running' | 'ready' | 'changed' | 'error'

function waitForGlobalOOFPoll(signal: AbortSignal) {
  return new Promise<void>(resolve => {
    const finish = () => {
      window.clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }
    const timer = window.setTimeout(finish, 1000)
    signal.addEventListener('abort', finish, { once: true })
  })
}

export function ResultPage({ onOpenThreshold, onOpenObjects }: { onOpenThreshold: () => void; onOpenObjects: () => void }) {
  const [result, setResult] = useState<ResultOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [globalPreview, setGlobalPreview] = useState<GlobalOOFExplanation | null>(null)
  const [globalPreviewStatus, setGlobalPreviewStatus] = useState<GlobalPreviewStatus>('idle')

  useEffect(() => {
    let cancelled = false
    void getCurrentResult()
      .then(value => { if (!cancelled) setResult(value) })
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить результат обучения.') })
    return () => { cancelled = true }
  }, [])

  const summary = result?.summary
  const threshold = result?.threshold
  const capture = result?.capture

  useEffect(() => {
    const artifactId = result?.summary.artifact_id
    if (!artifactId) return
    const controller = new AbortController()
    const { signal } = controller
    let lifecycleComplete = false
    setGlobalPreview(null)
    setGlobalPreviewStatus('loading')

    const loadExplanation = async () => {
      const explanation = await getCurrentGlobalOOFExplanation(signal)
      if (signal.aborted) return
      if (explanation.artifact_id !== artifactId) {
        lifecycleComplete = true
        setGlobalPreviewStatus('changed')
        return
      }
      lifecycleComplete = true
      setGlobalPreview(explanation)
      setGlobalPreviewStatus('ready')
    }

    const runLifecycle = async () => {
      try {
        await loadExplanation()
        if (signal.aborted || lifecycleComplete) return
      } catch (reason) {
        if (signal.aborted) return
        if (reason instanceof GlobalOOFAPIError && reason.code === 'RESULT_CHANGED') {
          setGlobalPreviewStatus('changed')
          return
        }
        if (!(reason instanceof GlobalOOFAPIError) || reason.code !== 'GLOBAL_OOF_RESULT_NOT_READY') {
          setGlobalPreviewStatus('error')
          return
        }
      }

      let operation: GlobalOOFOperation
      try {
        operation = await runCurrentGlobalOOF(false, signal)
        if (signal.aborted) return
        if (operation.artifact_id !== artifactId) {
          setGlobalPreviewStatus('changed')
          return
        }
        setGlobalPreviewStatus(operation.status === 'FAILED' ? 'error' : operation.status === 'READY' ? 'loading' : 'running')
        while (operation.status === 'NOT_STARTED' || operation.status === 'RUNNING') {
          await waitForGlobalOOFPoll(signal)
          if (signal.aborted) return
          operation = await getCurrentGlobalOOFStatus(signal)
          if (signal.aborted) return
          if (operation.artifact_id !== artifactId) {
            setGlobalPreviewStatus('changed')
            return
          }
          if (operation.status === 'RUNNING' || operation.status === 'NOT_STARTED') setGlobalPreviewStatus('running')
        }
        if (operation.status === 'FAILED') {
          setGlobalPreviewStatus('error')
          return
        }
        await loadExplanation()
      } catch (reason) {
        if (signal.aborted) return
        if (reason instanceof GlobalOOFAPIError && reason.code === 'RESULT_CHANGED') setGlobalPreviewStatus('changed')
        else setGlobalPreviewStatus('error')
      }
    }

    void runLifecycle()
    return () => controller.abort()
  }, [result?.summary.artifact_id])

  const foldMetrics = summary?.fold_metrics.filter(fold =>
    Number.isFinite(fold.fold) && Number.isFinite(fold.roc_auc),
  ) ?? []

  return <main className="workspace result-workspace">
    <div className="analysis-nav"><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index < 4 ? 'completed' : 'active'}><span>{index < 4 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>
    <header className="result-header">
      <div><h1>Результат модели</h1><p>Итоги обучения, проверка качества и анализ поведения модели на всей оценочной выборке.</p></div>
      <div className="result-header-actions" aria-label="Действия с результатом">
        <button className="secondary-action" disabled title={unavailable} aria-label={`Сохранить модель. ${unavailable}`}><Icon name="file" size={17} />Сохранить модель</button>
        <button className="secondary-action" disabled title={unavailable} aria-label={`Экспорт отчёта. ${unavailable}`}><Icon name="download" size={17} />Экспорт отчёта</button>
        <button className="primary-action" disabled title={unavailable} aria-label={`Обзор проекта. ${unavailable}`}><Icon name="folder" size={17} />Обзор проекта</button>
      </div>
    </header>
    {error && <section className="result-error" role="alert"><strong>Результат недоступен</strong><p>{error}</p></section>}
    {!result && !error && <p className="feature-loading">Загружаем сохранённый результат…</p>}
    {result && summary && threshold && <div className="result-dashboard">
      <section className="result-summary-strip panel" aria-label="Сводка эксперимента">
        <SummaryFact icon="algorithm" label="Алгоритм" value={summary.model_id} detail={`Версия ${summary.model_version}`} />
        <SummaryFact icon="table" label="Данные" value={`${integerFormat.format(summary.object_count)} объектов`} />
        <SummaryFact icon="chart" label="Признаки" value={integerFormat.format(summary.feature_count)} />
        <SummaryFact icon="layers" label="Проверка" value={`OOF · ${integerFormat.format(summary.folds)} части`} />
        <SummaryFact icon="clock" label="Время обучения" value={summary.runtime_seconds === null ? '—' : `${numberFormat.format(summary.runtime_seconds)} с`} />
      </section>

      <aside className="result-info-banner"><Icon name="info" size={22} /><p>Метрики рассчитаны по OOF-прогнозам: каждая строка оценивалась моделью, которая не обучалась на этой строке.</p></aside>

      <div className="result-top-grid">
        <section className="result-panel panel">
          <PanelHeading title="Качество модели" icon="info" action="Подробнее о качестве" />
          <div className="result-quality-metrics">
            <Metric label="Gini" value={metric(summary.gini)} bar={summary.gini} />
            <Metric label="ROC-AUC" value={metric(summary.roc_auc)} bar={summary.roc_auc} />
            <Metric label="PR-AUC" value={metric(summary.pr_auc)} bar={summary.pr_auc} />
          </div>
        </section>

        <section className="result-panel panel">
          <PanelHeading title="Стабильность проверки" action="Подробнее" />
          {foldMetrics.length ? <>
            <div className="result-fold-chart result-overview-fold-chart" role="img" aria-label={`ROC-AUC по ${foldMetrics.length} частям проверки`}>
              <div className="result-chart-ylabels"><span>1,0</span><span>0,5</span><span>0,0</span></div>
              <div className="result-chart-plot">
                <div className="result-fold-gridline top" /><div className="result-fold-gridline middle" /><div className="result-fold-gridline bottom" />
                <div className="result-fold-bars">{foldMetrics.map(fold => <div className="result-fold-bar" key={fold.fold} title={`Часть ${fold.fold}: ROC-AUC ${metric(fold.roc_auc)}`}>
                  <strong>{metric(fold.roc_auc)}</strong>
                  <span className="result-fold-track"><i style={{ height: `${Math.max(0, Math.min(fold.roc_auc, 1)) * 100}%` }} /></span>
                  <small>Часть {fold.fold}</small>
                </div>)}</div>
              </div>
            </div>
            <p className="result-chart-legend"><i />ROC-AUC по частям проверки</p>
          </> : <p className="result-muted">Данные для графика недоступны.</p>}
          <p className="result-note">Разброс по фолдам не доказывает стабильность во времени.</p>
        </section>

        <section className="result-panel result-capture-panel panel">
          <CapturePanelHeading />
          <CaptureChart capture={capture} />
        </section>
      </div>

      <div className="result-middle-grid">
        <section className="result-panel result-errors-panel panel">
          <PanelHeading title="Ошибки и порог" icon="info" badge="Диагностический порог" />
          <div className="result-error-top-metrics">
            <Metric label="Порог" value={thresholdFormat.format(threshold.threshold)} />
            <Metric label="Recall" value={percent(threshold.recall)} />
            <Metric label="Precision" value={percent(threshold.precision)} />
          </div>
          <div className="result-error-counts">
            <ErrorCountRow label="Пропущено событий" count={integerFormat.format(threshold.fn)} rate={errorRate(threshold.fn, threshold.tp + threshold.fn)} tone="negative" />
            <ErrorCountRow label="Ложных срабатываний" count={integerFormat.format(threshold.fp)} rate={errorRate(threshold.fp, threshold.tn + threshold.fp)} tone="warning" />
          </div>
          <button className="primary-action result-panel-action" onClick={onOpenThreshold}>Исследовать порог <Icon name="arrow" size={18} /></button>
        </section>

        <section className="result-panel result-influence-panel panel">
          <PanelHeading title="На какие признаки модель опиралась сильнее всего" icon="info" action="Подробнее" onAction={() => navigate(routes.resultGlobalExplanation)} />
          <FeatureInfluencePreview explanation={globalPreview} status={globalPreviewStatus} />
        </section>
      </div>

      <section className="result-objects-strip panel">
        <span className="result-objects-icon"><Icon name="users" size={26} /></span>
        <div className="result-objects-copy"><h2>Объекты оценки</h2><p>Посмотрите отдельные объекты, сложные случаи и причины конкретных прогнозов.</p></div>
        <ObjectFact icon="alert-circle" tone="negative" label="Сложные случаи" value="—" unavailable />
        <ObjectFact icon="warning" tone="warning" label="Пограничные" value="—" unavailable />
        <ObjectFact icon="info" tone="info" label="Пропущенные события" value={integerFormat.format(threshold.fn)} />
        <button className="primary-action" onClick={onOpenObjects}>Посмотреть объекты <Icon name="arrow" size={18} /></button>
      </section>

      <details className="result-collapsible panel"><summary><Icon name="warning" size={22} /><span>Ограничения и предупреждения</span><small>Важная информация об интерпретации результата модели</small></summary>
        {summary.limitations.length ? <ul className="result-limitations">{summary.limitations.map((limitation, index) => <li key={`${index}-${limitation}`}>{limitation}</li>)}</ul> : <p className="result-muted">Backend не передал ограничений для этого результата.</p>}
      </details>
      <details className="result-collapsible result-technical panel"><summary><Icon name="file" size={22} /><span>Технические сведения</span><small>Детальная информация о модели, данных и процессе обучения</small></summary>
        <dl><div><dt>Artifact ID</dt><dd>{summary.artifact_id}</dd></div><div><dt>Result ID</dt><dd>{summary.result_id}</dd></div><div><dt>Уровень оценки</dt><dd>{summary.evaluation_level}</dd></div><div><dt>Время выполнения</dt><dd>{summary.runtime_seconds === null ? '—' : `${numberFormat.format(summary.runtime_seconds)} с`}</dd></div></dl>
      </details>
    </div>}
  </main>
}

function SummaryFact({ icon, label, value, detail }: { icon: 'algorithm' | 'table' | 'chart' | 'layers' | 'clock'; label: string; value: string; detail?: string }) {
  return <div className="result-summary-fact"><span className="result-summary-icon"><Icon name={icon} size={24} /></span><div><small>{label}</small><strong>{value}</strong>{detail && <span>{detail}</span>}</div></div>
}

function PanelHeading({ title, icon, action, badge, onAction }: { title: string; icon?: 'info'; action?: string; badge?: string; onAction?: () => void }) {
  return <div className="result-panel-heading"><h2>{title}{icon && <span className="result-heading-info" title={title}><Icon name={icon} size={17} /></span>}</h2>{badge && <span className="result-heading-badge">{badge}</span>}{action && <button className="tertiary-action result-heading-action" disabled={!onAction} onClick={onAction} title={onAction ? undefined : unavailable} aria-label={onAction ? `${action}: ${title}` : `${action} о разделе «${title}». ${unavailable}`}>{action} <Icon name="arrow" size={15} /></button>}</div>
}

function CapturePanelHeading() {
  const [tooltipVisible, setTooltipVisible] = useState(false)
  const tooltipId = 'capture-chart-tooltip'
  return <div className="result-panel-heading capture-panel-heading"><h2>Сколько событий находим<button type="button" className="capture-info-trigger" aria-label="Как читать график охвата событий" aria-describedby={tooltipId} onMouseEnter={() => setTooltipVisible(true)} onMouseLeave={() => setTooltipVisible(false)} onFocus={() => setTooltipVisible(true)} onBlur={() => setTooltipVisible(false)} onKeyDown={event => { if (event.key === 'Escape') { setTooltipVisible(false); event.currentTarget.blur() } }}><Icon name="info" size={15} /></button></h2><div id={tooltipId} className="capture-info-tooltip" role="tooltip" hidden={!tooltipVisible}><strong>Как читать график</strong><p>По оси X — доля объектов с наибольшими оценками модели в OOF-проверке, включённых в выборку. По оси Y — накопленная доля фактических целевых событий, найденных среди этих объектов.</p><p>График помогает понять, насколько целевые события концентрируются в верхней части ранжирования модели. На небольших выборках линия может быть ступенчатой: доля найденных событий меняется только при добавлении очередного объекта с целевым событием.</p><p>Отмеченная точка показывает конкретное сочетание доли объектов и доли найденных событий. Она не является автоматически лучшим порогом или бизнес-решением.</p></div></div>
}

function Metric({ label, value, bar, tone }: { label: string; value: string; bar?: number; tone?: 'negative' | 'warning' }) {
  const boundedBar = typeof bar === 'number' && Number.isFinite(bar) ? Math.max(0, Math.min(bar, 1)) : null
  return <div className={`result-metric${tone ? ` ${tone}` : ''}`}><small>{label}</small><strong>{value}</strong>{boundedBar !== null && <span className="result-metric-track"><i style={{ width: `${boundedBar * 100}%` }} /></span>}</div>
}

function CaptureChart({ capture }: { capture: ResultCapture | undefined }) {
  if (!capture || capture.total_positive_events === 0 || !capture.points.length) {
    return <div className="result-capture-empty"><Icon name="info" size={18} /><p>В выборке нет целевых событий для построения кривой охвата.</p></div>
  }
  const line = capture.points
    .map((point, index) => {
      const x = point.object_share * 100
      const y = 100 - point.event_share * 100
      return index === 0 ? `M ${x} ${y}` : `H ${x} V ${y}`
    })
    .join(' ')
  const marker = capture.marker

  return <div className="result-capture-chart">
    <div className="result-capture-graphic" role="img" aria-label="Накопительная ступенчатая кривая найденных целевых событий по OOF-прогнозам">
      <span className="result-capture-ytitle">Найдено событий, %</span>
      <div className="result-capture-ylabels"><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div>
      <div className="result-capture-plot">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {[0, 25, 50, 75, 100].map(value => <line className="result-capture-grid" key={`h-${value}`} x1="0" x2="100" y1={value} y2={value} />)}
          {[0, 25, 50, 75, 100].map(value => <line className="result-capture-grid" key={`v-${value}`} y1="0" y2="100" x1={value} x2={value} />)}
          <path className="result-capture-line" d={line} />
          {marker && <><line className="result-capture-marker-line" x1={marker.object_share * 100} x2={marker.object_share * 100} y1={100 - marker.event_share * 100} y2="100" /><circle className="result-capture-marker-dot" cx={marker.object_share * 100} cy={100 - marker.event_share * 100} r="2.7" /></>}
        </svg>
      </div>
      <div className="result-capture-ticks"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div>
      <span className="result-capture-xtitle">Доля объектов, %</span>
    </div>
    {marker && <p className="result-capture-readout"><strong>{percent(marker.object_share)} объектов</strong><span>→</span><strong>{percent(marker.event_share)} событий</strong></p>}
  </div>
}

function FeatureInfluencePreview({ explanation, status }: { explanation: GlobalOOFExplanation | null; status: GlobalPreviewStatus }) {
  const features = explanation?.features.slice(0, 7) ?? []
  const maxValue = Math.max(0, ...features.map(feature => Number.isFinite(feature.mean_abs_shap) ? feature.mean_abs_shap : 0))
  return <div className="result-influence-content">
    <div className="result-feature-preview">
      {status === 'loading' || status === 'idle' || status === 'running' ? <div className="result-influence-loading" role="status" aria-live="polite"><span className="global-spinner result-influence-spinner" aria-hidden="true" /><span><strong>Отчет готовится...</strong><small>Расчёт влияния признаков может занять несколько минут.</small></span></div>
        : status === 'changed' ? <p className="result-influence-state">Результат изменился. Обновите экран.</p>
          : status === 'error' ? <p className="result-influence-state">Влияние признаков пока недоступно.</p>
            : features.length ? features.map(feature => {
              const value = Number.isFinite(feature.mean_abs_shap) ? feature.mean_abs_shap : 0
              const width = maxValue > 0 ? Math.max(0, value) / maxValue * 100 : 0
              return <div className="result-feature-row" key={feature.feature_id} title={`Ранг ${feature.rank}: ${feature.column_name}`}>
                <span>{feature.column_name}</span><i><b style={{ width: `${width}%` }} /></i><strong>{metric(value)}</strong>
              </div>
            }) : <p className="result-influence-state">Нет признаков для отображения.</p>}
    </div>
    <aside><Icon name="info" size={18} /><p>Показывает, какие признаки в среднем сильнее влияли на оценки модели. Это описание поведения модели, а не доказательство причинного влияния.</p></aside>
  </div>
}

function ErrorCountRow({ label, count, rate, tone }: { label: string; count: string; rate: string; tone: 'negative' | 'warning' }) {
  return <div className={`result-error-count-row tone-${tone}`}><div><small>{label}</small><strong>{count}</strong></div><span className="result-error-rate">{rate}</span></div>
}

function ObjectFact({ icon, tone, label, value, unavailable: isUnavailable }: { icon: 'alert-circle' | 'warning' | 'info'; tone: 'negative' | 'warning' | 'info'; label: string; value: string; unavailable?: boolean }) {
  return <div className={`result-object-fact tone-${tone}`} title={isUnavailable ? 'Данные пока не подключены.' : undefined}><span className="result-object-fact-label"><Icon name={icon} size={15} /><small>{label}</small></span><strong>{value}</strong></div>
}
