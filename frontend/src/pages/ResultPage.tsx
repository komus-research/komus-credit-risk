import { useEffect, useState } from 'react'
import { getCurrentResult, type ResultOverview } from '../api/result'
import { Icon } from '../components/Icon'
import { Sidebar } from '../components/Sidebar'
import { navigate, routes } from '../routing'

const numberFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const percentFormat = new Intl.NumberFormat('ru-RU', { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 })
const integerFormat = new Intl.NumberFormat('ru-RU')
const thresholdFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const unavailable = 'Действие пока недоступно: соответствующая возможность не подключена.'

function metric(value: number) { return numberFormat.format(value) }
function percent(value: number) { return percentFormat.format(value) }
function errorRate(numerator: number, denominator: number) { return denominator === 0 ? '—' : percentFormat.format(numerator / denominator) }

export function ResultPage({ onHome, onOpenThreshold, onOpenObjects }: { onHome: () => void; onOpenThreshold: () => void; onOpenObjects: () => void }) {
  const [result, setResult] = useState<ResultOverview | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void getCurrentResult()
      .then(value => { if (!cancelled) setResult(value) })
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить результат обучения.') })
    return () => { cancelled = true }
  }, [])

  const summary = result?.summary
  const threshold = result?.threshold
  const rocFolds = summary?.fold_metrics
    .map((fold, index) => ({ index, value: fold.roc_auc }))
    .filter((fold): fold is { index: number; value: number } => typeof fold.value === 'number' && Number.isFinite(fold.value)) ?? []

  return <div className="app-shell features-shell"><Sidebar active="analysis" onHome={onHome} /><main className="workspace result-workspace">
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
          {rocFolds.length ? <>
            <div className="result-fold-chart" role="img" aria-label={`ROC-AUC по ${rocFolds.length} частям проверки`}>
              <div className="result-chart-ylabels"><span>1,0</span><span>0,5</span><span>0,0</span></div>
              <div className="result-chart-plot">
                <div className="result-fold-gridline top" /><div className="result-fold-gridline middle" /><div className="result-fold-gridline bottom" />
                <div className="result-fold-bars">{rocFolds.map(({ index, value }) => <div className="result-fold-bar" key={index}><strong>{metric(value)}</strong><span className="result-fold-track"><i style={{ height: `${Math.max(0, Math.min(value, 1)) * 100}%` }} /></span><small>Часть {index + 1}</small></div>)}</div>
              </div>
            </div>
            <p className="result-chart-legend"><i />ROC-AUC по частям проверки</p>
          </> : <p className="result-muted">В сохранённом результате нет ROC-AUC по частям проверки.</p>}
          <p className="result-note">Разброс по фолдам не доказывает стабильность во времени.</p>
        </section>

        <section className="result-panel result-capture-panel panel">
          <PanelHeading title="Сколько событий находим" action="Подробнее" />
          <div className="result-unavailable-chart" role="img" aria-label="График охвата: данные пока не подключены"><div className="result-capture-ylabels"><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div><div className="result-capture-plot"><div /><div /><div /><div /><div /><p>Данные охвата пока не подключены</p></div><div className="result-capture-ticks"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div><span className="result-capture-xlabel">Доля объектов, %</span></div>
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
          <div className="result-influence-content"><div className="result-influence-unavailable">Откройте полный список и ранжирование признаков.</div><aside><Icon name="info" size={20} /><p>Этот блок объясняет поведение модели, но не доказывает причинность.</p></aside></div>
        </section>
      </div>

      <section className="result-objects-strip panel">
        <span className="result-objects-icon"><Icon name="users" size={26} /></span>
        <div className="result-objects-copy"><h2>Объекты оценки</h2><p>Посмотрите отдельные объекты и причины конкретных прогнозов.</p></div>
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
  </main></div>
}

function SummaryFact({ icon, label, value, detail }: { icon: 'algorithm' | 'table' | 'chart' | 'layers' | 'clock'; label: string; value: string; detail?: string }) {
  return <div className="result-summary-fact"><span className="result-summary-icon"><Icon name={icon} size={24} /></span><div><small>{label}</small><strong>{value}</strong>{detail && <span>{detail}</span>}</div></div>
}

function PanelHeading({ title, icon, action, badge, onAction }: { title: string; icon?: 'info'; action?: string; badge?: string; onAction?: () => void }) {
  return <div className="result-panel-heading"><h2>{title}{icon && <span className="result-heading-info" title={title}><Icon name={icon} size={17} /></span>}</h2>{badge && <span className="result-heading-badge">{badge}</span>}{action && <button className="result-heading-action" disabled={!onAction} onClick={onAction} title={onAction ? undefined : unavailable} aria-label={onAction ? `${action}: ${title}` : `${action} о разделе «${title}». ${unavailable}`}>{action} <Icon name="arrow" size={15} /></button>}</div>
}

function Metric({ label, value, bar, tone }: { label: string; value: string; bar?: number; tone?: 'negative' | 'warning' }) {
  const boundedBar = typeof bar === 'number' && Number.isFinite(bar) ? Math.max(0, Math.min(bar, 1)) : null
  return <div className={`result-metric${tone ? ` ${tone}` : ''}`}><small>{label}</small><strong>{value}</strong>{boundedBar !== null && <span className="result-metric-track"><i style={{ width: `${boundedBar * 100}%` }} /></span>}</div>
}

function ErrorCountRow({ label, count, rate, tone }: { label: string; count: string; rate: string; tone: 'negative' | 'warning' }) {
  return <div className={`result-error-count-row tone-${tone}`}><div><small>{label}</small><strong>{count}</strong></div><span className="result-error-rate">{rate}</span></div>
}

function ObjectFact({ icon, tone, label, value, unavailable: isUnavailable }: { icon: 'alert-circle' | 'warning' | 'info'; tone: 'negative' | 'warning' | 'info'; label: string; value: string; unavailable?: boolean }) {
  return <div className={`result-object-fact tone-${tone}`} title={isUnavailable ? 'Данные пока не подключены' : undefined}><span className="result-object-fact-label"><Icon name={icon} size={15} /><small>{label}</small></span><strong>{value}</strong></div>
}
