import { useEffect, useState } from 'react'
import { getCurrentResult, type ResultOverview } from '../api/result'
import { Sidebar } from '../components/Sidebar'
import { navigate, routes } from '../routing'

const numberFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const integerFormat = new Intl.NumberFormat('ru-RU')
const thresholdFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function metric(value: number) { return numberFormat.format(value) }
function percentage(value: number) { return `${numberFormat.format(value * 100)}%` }
function foldValue(value: unknown): string {
  if (typeof value === 'number') return numberFormat.format(value)
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

export function ResultPage({ onHome, onOpenThreshold }: { onHome: () => void; onOpenThreshold: () => void }) {
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
  const foldColumns = summary?.fold_metrics.length ? Object.keys(summary.fold_metrics[0]) : []

  return <div className="app-shell features-shell"><Sidebar active="analysis" onHome={onHome} /><main className="workspace result-workspace">
    <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index < 4 ? 'completed' : 'active'}><span>{index < 4 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>
    <header className="result-header"><p className="eyebrow">Шаг 5 из 5</p><h1>Результат модели</h1><p>Сводка сохранённого эксперимента и его перекрёстной проверки.</p></header>
    {error && <section className="result-error" role="alert"><strong>Результат недоступен</strong><p>{error}</p><button className="secondary-action" onClick={() => navigate(routes.quality)}>← Вернуться к проверке качества</button></section>}
    {!result && !error && <p className="feature-loading">Загружаем сохранённый результат…</p>}
    {result && summary && threshold && <>
      <section className="result-complete panel"><b>✓</b><div><h2>Обучение и перекрёстная проверка завершены.</h2><p>Каждый объект оценивала модель, которая не использовала этот объект для обучения в соответствующем фолде.</p></div></section>

      <section className="result-section"><h2>Сводка эксперимента</h2><div className="result-summary-grid">
        <article className="result-card panel"><small>Алгоритм</small><strong>{summary.model_id}</strong><span>Версия модели {summary.model_version}</span></article>
        <article className="result-card panel"><small>Объекты</small><strong>{integerFormat.format(summary.object_count)}</strong><span>оценено в OOF</span></article>
        <article className="result-card panel"><small>Признаки</small><strong>{integerFormat.format(summary.feature_count)}</strong><span>в эксперименте</span></article>
        <article className="result-card panel"><small>Перекрёстная проверка</small><strong>{integerFormat.format(summary.folds)} фолдов</strong><span>{summary.evaluation_level}</span></article>
          {summary.runtime_seconds !== null && <article className="result-card panel"><small>Время обучения</small><strong>{numberFormat.format(summary.runtime_seconds)} с</strong></article>}
      </div></section>

      <section className="result-section"><h2>Качество ранжирования</h2><div className="result-ranking-grid">
        <article className="result-ranking panel"><small>Gini</small><strong>{metric(summary.gini)}</strong></article>
        <article className="result-ranking panel"><small>ROC-AUC</small><strong>{metric(summary.roc_auc)}</strong></article>
        <article className="result-ranking panel"><small>PR-AUC</small><strong>{metric(summary.pr_auc)}</strong></article>
      </div></section>

      <section className="result-section"><div className="result-section-heading"><div><h2>Диагностический порог: {thresholdFormat.format(threshold.threshold)}</h2><p>Порог {thresholdFormat.format(threshold.threshold)} используется здесь только для диагностического просмотра и не является автоматически выбранным бизнес-порогом.</p></div></div>
        <div className="result-threshold-grid">
          <article className="result-threshold-card panel"><small>Precision</small><strong>{metric(threshold.precision)}</strong></article>
          <article className="result-threshold-card panel"><small>Recall</small><strong>{metric(threshold.recall)}</strong></article>
          <article className="result-threshold-card panel"><small>F1</small><strong>{metric(threshold.f1)}</strong></article>
          <article className="result-threshold-card panel"><small>TP</small><strong>{integerFormat.format(threshold.tp)}</strong></article>
          <article className="result-threshold-card panel"><small>TN</small><strong>{integerFormat.format(threshold.tn)}</strong></article>
          <article className="result-threshold-card panel"><small>FP</small><strong>{integerFormat.format(threshold.fp)}</strong></article>
          <article className="result-threshold-card panel"><small>FN</small><strong>{integerFormat.format(threshold.fn)}</strong></article>
          <article className="result-threshold-card panel"><small>Выше порога</small><strong>{integerFormat.format(threshold.above_threshold_count)}</strong><span>{percentage(threshold.above_threshold_share)} объектов</span></article>
        </div>
      </section>

      <section className="result-section"><h2>Стабильность по фолдам</h2>{summary.fold_metrics.length ? <div className="result-table-wrap panel"><table className="result-fold-table"><thead><tr>{foldColumns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{summary.fold_metrics.map((fold, index) => <tr key={index}>{foldColumns.map(column => <td key={column}>{foldValue(fold[column])}</td>)}</tr>)}</tbody></table></div> : <p className="result-muted">В сохранённом результате нет метрик по фолдам.</p>}<p className="result-note">Метрики показывают разброс между фолдами и не подтверждают стабильность во времени.</p></section>

      <section className="result-section"><h2>Ограничения результата</h2>{summary.limitations.length ? <ul className="result-limitations">{summary.limitations.map((limitation, index) => <li key={`${index}-${limitation}`}>{limitation}</li>)}</ul> : <p className="result-muted">Backend не передал ограничений для этого результата.</p>}</section>

      <details className="result-technical panel"><summary>Технические сведения</summary><dl><div><dt>Artifact ID</dt><dd>{summary.artifact_id}</dd></div><div><dt>Result ID</dt><dd>{summary.result_id}</dd></div><div><dt>Уровень оценки</dt><dd>{summary.evaluation_level}</dd></div><div><dt>Время выполнения</dt><dd>{summary.runtime_seconds === null ? 'Не сохранено' : `${numberFormat.format(summary.runtime_seconds)} с`}</dd></div></dl></details>

      <nav className="result-actions" aria-label="Другие разделы результата"><button className="secondary-action" onClick={onOpenThreshold}>Исследовать порог</button><button className="secondary-action" disabled>Посмотреть объекты</button><button className="secondary-action" disabled>Подробнее о влиянии признаков</button></nav>
    </>}
  </main></div>
}
