import { useEffect, useMemo, useRef, useState } from 'react'
import { getCurrentObjects, getCurrentResult, type ResultObjectItem, type ResultObjectList, type ResultObjectsQuery, type ResultOverview } from '../api/result'
import { Sidebar } from '../components/Sidebar'
import { navigate, routes } from '../routing'

const chunkSize = 50
const integerFormat = new Intl.NumberFormat('ru-RU')
const scoreFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const scoreValueFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

type Outcome = ResultObjectItem['outcome']
type Sort = ResultObjectsQuery['sort']
type QuickView = 'errors' | 'high' | 'boundary' | 'missed' | 'false-positive' | 'all' | null

const quickViews: Array<{ id: Exclude<QuickView, null>; label: string }> = [
  { id: 'errors', label: 'Ошибки модели' },
  { id: 'high', label: 'Высокая оценка модели' },
  { id: 'boundary', label: 'Пограничные' },
  { id: 'missed', label: 'Пропущенные события' },
  { id: 'false-positive', label: 'Ложные срабатывания' },
  { id: 'all', label: 'Все объекты' },
]

function outcomeClass(outcome: Outcome) { return `objects-outcome objects-outcome-${outcome.toLowerCase()}` }

function targetMarker(item: ResultObjectItem) {
  return <span className={`objects-target objects-target-${item.outcome.toLowerCase()}`}><b aria-hidden="true">{item.y_true === 1 ? '●' : '○'}</b>{item.y_true === 1 ? 'Да' : 'Нет'}</span>
}

export function ObjectsPage({ onHome }: { onHome: () => void }) {
  const [result, setResult] = useState<ResultOverview | null>(null)
  const [contextError, setContextError] = useState<string | null>(null)
  const [objects, setObjects] = useState<ResultObjectList | null>(null)
  const [objectsError, setObjectsError] = useState<string | null>(null)
  const [loadingObjects, setLoadingObjects] = useState(true)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [target, setTarget] = useState<ResultObjectsQuery['target']>('ANY')
  const [outcomes, setOutcomes] = useState<Outcome[]>([])
  const [sort, setSort] = useState<Sort>('SCORE_DESC')
  const [scoreDraft, setScoreDraft] = useState({ min: 0, max: 1 })
  const [scoreRange, setScoreRange] = useState({ min: 0, max: 1 })
  const [offset, setOffset] = useState(0)
  const [quickView, setQuickView] = useState<QuickView>(null)
  const [retryToken, setRetryToken] = useState(0)
  const requestGeneration = useRef(0)

  useEffect(() => {
    let cancelled = false
    void getCurrentResult()
      .then(value => { if (!cancelled) setResult(value) })
      .catch(reason => { if (!cancelled) setContextError(reason instanceof Error ? reason.message : 'Не удалось загрузить результат обучения.') })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput)
      setOffset(0)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setScoreRange(scoreDraft)
      setOffset(0)
    }, 200)
    return () => window.clearTimeout(timer)
  }, [scoreDraft])

  const query = useMemo<ResultObjectsQuery>(() => ({
    offset,
    limit: chunkSize,
    search,
    target,
    outcomes: outcomes.length ? outcomes : undefined,
    min_score: scoreRange.min,
    max_score: scoreRange.max,
    sort,
  }), [offset, search, target, outcomes, scoreRange, sort])

  useEffect(() => {
    const controller = new AbortController()
    const generation = ++requestGeneration.current
    setLoadingObjects(true)
    setObjectsError(null)
    setObjects(null)
    void getCurrentObjects(query, controller.signal)
      .then(value => {
        if (generation === requestGeneration.current) setObjects(value)
      })
      .catch(reason => {
        if (controller.signal.aborted || generation !== requestGeneration.current) return
        setObjectsError(reason instanceof Error ? reason.message : 'Не удалось загрузить объекты из сохранённого OOF-результата.')
      })
      .finally(() => {
        if (generation === requestGeneration.current) setLoadingObjects(false)
      })
    return () => controller.abort()
  }, [query, retryToken])

  const applyQuickView = (view: Exclude<QuickView, null>) => {
    setQuickView(view)
    if (view === 'errors') { setOutcomes(['FP', 'FN']); setSort('SCORE_DESC') }
    if (view === 'high') { setOutcomes([]); setSort('SCORE_DESC') }
    if (view === 'boundary') { setOutcomes([]); setSort('DISTANCE_TO_THRESHOLD_ASC') }
    if (view === 'missed') { setOutcomes(['FN']); setSort('SCORE_DESC') }
    if (view === 'false-positive') { setOutcomes(['FP']); setSort('SCORE_DESC') }
    if (view === 'all') { setOutcomes([]); setSort('SCORE_DESC') }
    setOffset(0)
  }

  const toggleOutcome = (value: Outcome) => {
    setQuickView(null)
    setOutcomes(current => current.includes(value) ? current.filter(item => item !== value) : [...current, value])
    setOffset(0)
  }

  const firstShown = objects && objects.returned_count ? objects.offset + 1 : 0
  const lastShown = objects ? objects.offset + objects.returned_count : 0

  return <div className="app-shell features-shell"><Sidebar active="analysis" onHome={onHome} /><main className="workspace result-workspace objects-workspace">
    <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index < 4 ? 'completed' : 'active'}><span>{index < 4 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>
    <button className="objects-back-link" onClick={() => navigate(routes.result)}>← Назад к результату модели</button>
    <header className="result-header"><p className="eyebrow">Шаг 5 из 5 · Результат</p><h1>Объекты оценки</h1><p>Просмотрите OOF-оценки отдельных объектов, найдите ошибки и отфильтруйте сохранённый результат.</p></header>

    {contextError && <section className="result-error" role="alert"><strong>Результат недоступен</strong><p>{contextError}</p><button className="secondary-action" onClick={() => navigate(routes.result)}>← Вернуться к результату</button></section>}
    {!result && !contextError && <p className="feature-loading">Загружаем контекст сохранённого результата…</p>}
    {result && <>
      <section className="objects-context-grid">
        <article className="objects-context-card panel"><small>Модель</small><strong>{result.summary.model_id}</strong><span>версия {result.summary.model_version}</span></article>
        <article className="objects-context-card panel"><small>Источник оценок</small><strong>OOF</strong><span>{result.summary.evaluation_level}</span></article>
        <article className="objects-context-card panel"><small>Всего объектов</small><strong>{integerFormat.format(result.summary.object_count)}</strong><span>в сохранённом результате</span></article>
        <article className="objects-context-card panel"><small>Текущий порог</small><strong>{scoreFormat.format(result.threshold.threshold)}</strong><span>диагностический</span></article>
        <article className="objects-context-card objects-context-errors panel"><small>Ошибки модели</small><strong>FP {integerFormat.format(result.threshold.fp)} · FN {integerFormat.format(result.threshold.fn)}</strong><span>при текущем пороге</span></article>
      </section>

      <section className="objects-controls panel" aria-label="Поиск, фильтры и сортировка объектов">
        <label className="objects-search"><span aria-hidden="true">⌕</span><input value={searchInput} onChange={event => setSearchInput(event.target.value)} placeholder="Найти объект…" aria-label="Найти объект" /></label>
        <div className="objects-quick-views">{quickViews.map(view => <button key={view.id} className={quickView === view.id ? 'active' : ''} onClick={() => applyQuickView(view.id)}>{view.label}</button>)}</div>
        <div className="objects-filter-grid">
          <label>Целевое событие<select value={target} onChange={event => { setTarget(event.target.value as ResultObjectsQuery['target']); setQuickView(null); setOffset(0) }}><option value="ANY">Все</option><option value="POSITIVE">Да</option><option value="NEGATIVE">Нет</option></select></label>
          <fieldset className="objects-outcome-filter"><legend>Исход</legend><div>{(['TP', 'TN', 'FP', 'FN'] as Outcome[]).map(outcome => <label key={outcome}><input type="checkbox" checked={outcomes.includes(outcome)} onChange={() => toggleOutcome(outcome)} />{outcome}</label>)}</div></fieldset>
          <fieldset className="objects-range"><legend>Диапазон оценки модели</legend><div className="objects-range-values"><output>{scoreFormat.format(scoreDraft.min)}</output><span>—</span><output>{scoreFormat.format(scoreDraft.max)}</output></div><div className="objects-range-inputs"><input type="range" min="0" max="1" step="0.01" value={scoreDraft.min} onChange={event => setScoreDraft(current => ({ min: Math.min(Number(event.target.value), current.max), max: current.max }))} aria-label="Минимальная оценка модели" /><input type="range" min="0" max="1" step="0.01" value={scoreDraft.max} onChange={event => setScoreDraft(current => ({ min: current.min, max: Math.max(Number(event.target.value), current.min) }))} aria-label="Максимальная оценка модели" /></div></fieldset>
          <label>Сортировка<select value={sort} onChange={event => { setSort(event.target.value as Sort); setQuickView(null); setOffset(0) }}><option value="SCORE_DESC">Оценка: по убыванию</option><option value="SCORE_ASC">Оценка: по возрастанию</option><option value="DISTANCE_TO_THRESHOLD_ASC">Ближе к порогу</option></select></label>
        </div>
      </section>

      <section className="objects-table-panel panel">
        <div className="objects-table-meta"><div><strong>Всего объектов: {integerFormat.format(objects?.total_count ?? result.summary.object_count)}</strong>{objects && <span>Текущий порог: {scoreFormat.format(objects.threshold)}</span>}</div>{objects && <span>Показано {integerFormat.format(firstShown)}–{integerFormat.format(lastShown)} из {integerFormat.format(objects.filtered_count)}</span>}</div>
        {loadingObjects && <p className="objects-loading">Загружаем объекты…</p>}
        {objectsError && <div className="objects-error" role="alert"><p>Не удалось загрузить объекты из сохранённого OOF-результата.</p><button className="secondary-action" onClick={() => setRetryToken(value => value + 1)}>Повторить</button></div>}
        {objects && objects.filtered_count === 0 && <p className="objects-empty">По выбранным условиям объекты не найдены.</p>}
        {objects && objects.filtered_count > 0 && <div className="objects-table-viewport"><table className="objects-table"><thead><tr><th>Объект</th><th>Оценка модели</th><th title="Форма показывает целевое событие: ● — Да, ○ — Нет. Цвет показывает исход TP/TN/FP/FN.">Целевое событие <span aria-hidden="true">ⓘ</span></th><th>Положение относительно порога</th><th>Исход</th></tr></thead><tbody>{objects.items.map(item => <tr key={item.object_id}><td>{item.identifier_display}</td><td>{scoreValueFormat.format(item.score)}</td><td>{targetMarker(item)}</td><td className="objects-threshold-position">{item.predicted_positive ? '↑ Выше порога' : '↓ Ниже порога'}</td><td><span className={outcomeClass(item.outcome)}>{item.outcome}</span></td></tr>)}</tbody></table></div>}
        {objects && objects.filtered_count > 0 && <div className="objects-chunk-controls"><button className="secondary-action" disabled={objects.offset === 0 || loadingObjects} onClick={() => setOffset(value => Math.max(0, value - chunkSize))}>← Предыдущие</button><button className="secondary-action" disabled={objects.offset + objects.returned_count >= objects.filtered_count || loadingObjects} onClick={() => setOffset(value => value + chunkSize)}>Следующие →</button></div>}
      </section>
    </>}
  </main></div>
}
