import { useEffect, useMemo, useRef, useState } from 'react'
import { getCurrentObjects, getCurrentResult, type ResultObjectItem, type ResultObjectList, type ResultObjectsQuery, type ResultOverview } from '../api/result'
import { Sidebar } from '../components/Sidebar'
import { buildObjectsRoute, currentRoute, navigate, navigateObjectDetail, navigateObjects, parseObjectsQuery, replaceObjects, routes, type ObjectsQueryState } from '../routing'

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
  const [objectsQuery, setObjectsQuery] = useState<ObjectsQueryState>(() => parseObjectsQuery())
  const [searchInput, setSearchInput] = useState(() => parseObjectsQuery().search)
  const [scoreDraft, setScoreDraft] = useState(() => {
    const query = parseObjectsQuery()
    return { min: query.minScore, max: query.maxScore }
  })
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
    const syncQuery = () => {
      if (currentRoute() === routes.resultObjects) setObjectsQuery(parseObjectsQuery())
    }
    window.addEventListener('hashchange', syncQuery)
    return () => window.removeEventListener('hashchange', syncQuery)
  }, [])

  useEffect(() => { setSearchInput(objectsQuery.search) }, [objectsQuery.search])

  useEffect(() => {
    setScoreDraft({ min: objectsQuery.minScore, max: objectsQuery.maxScore })
  }, [objectsQuery.minScore, objectsQuery.maxScore])

  const updateObjectsQuery = (next: ObjectsQueryState, replace = false) => {
    const normalized = parseObjectsQuery(buildObjectsRoute(next))
    setObjectsQuery(normalized)
    if (replace) replaceObjects(normalized)
    else navigateObjects(normalized)
  }

  useEffect(() => {
    if (searchInput.trim() === objectsQuery.search) return
    const timer = window.setTimeout(() => {
      updateObjectsQuery({ ...objectsQuery, search: searchInput.trim(), offset: 0 }, true)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [searchInput, objectsQuery])

  useEffect(() => {
    if (scoreDraft.min === objectsQuery.minScore && scoreDraft.max === objectsQuery.maxScore) return
    const timer = window.setTimeout(() => {
      updateObjectsQuery({ ...objectsQuery, minScore: scoreDraft.min, maxScore: scoreDraft.max, offset: 0 }, true)
    }, 200)
    return () => window.clearTimeout(timer)
  }, [scoreDraft, objectsQuery])

  const query = useMemo<ResultObjectsQuery>(() => ({
    offset: objectsQuery.offset,
    limit: chunkSize,
    search: objectsQuery.search,
    target: objectsQuery.target,
    outcomes: objectsQuery.outcomes.length ? objectsQuery.outcomes : undefined,
    min_score: objectsQuery.minScore,
    max_score: objectsQuery.maxScore,
    sort: objectsQuery.sort,
  }), [objectsQuery])

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
    const preset = view === 'errors' ? { outcomes: ['FP', 'FN'] as Outcome[], sort: 'SCORE_DESC' as Sort }
      : view === 'boundary' ? { outcomes: [] as Outcome[], sort: 'DISTANCE_TO_THRESHOLD_ASC' as Sort }
      : view === 'missed' ? { outcomes: ['FN'] as Outcome[], sort: 'SCORE_DESC' as Sort }
      : view === 'false-positive' ? { outcomes: ['FP'] as Outcome[], sort: 'SCORE_DESC' as Sort }
      : { outcomes: [] as Outcome[], sort: 'SCORE_DESC' as Sort }
    updateObjectsQuery({ ...objectsQuery, ...preset, quickView: view, offset: 0 })
  }

  const toggleOutcome = (value: Outcome) => {
    const outcomes = objectsQuery.outcomes.includes(value)
      ? objectsQuery.outcomes.filter(item => item !== value)
      : [...objectsQuery.outcomes, value]
    updateObjectsQuery({ ...objectsQuery, outcomes, quickView: null, offset: 0 })
  }

  const firstShown = objects && objects.returned_count ? objects.offset + 1 : 0
  const lastShown = objects ? objects.offset + objects.returned_count : 0
  const openObject = (objectId: string) => navigateObjectDetail(objectId, parseObjectsQuery())

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
        <div className="objects-quick-views">{quickViews.map(view => <button key={view.id} className={objectsQuery.quickView === view.id ? 'active' : ''} onClick={() => applyQuickView(view.id)}>{view.label}</button>)}</div>
        <div className="objects-filter-grid">
          <label>Целевое событие<select value={objectsQuery.target} onChange={event => updateObjectsQuery({ ...objectsQuery, target: event.target.value as ResultObjectsQuery['target'], quickView: null, offset: 0 })}><option value="ANY">Все</option><option value="POSITIVE">Да</option><option value="NEGATIVE">Нет</option></select></label>
          <fieldset className="objects-outcome-filter"><legend>Исход</legend><div>{(['TP', 'TN', 'FP', 'FN'] as Outcome[]).map(outcome => <label key={outcome}><input type="checkbox" checked={objectsQuery.outcomes.includes(outcome)} onChange={() => toggleOutcome(outcome)} />{outcome}</label>)}</div></fieldset>
          <fieldset className="objects-range"><legend>Диапазон оценки модели</legend><div className="objects-range-values"><output>{scoreFormat.format(scoreDraft.min)}</output><span>—</span><output>{scoreFormat.format(scoreDraft.max)}</output></div><div className="objects-range-inputs"><input type="range" min="0" max="1" step="0.01" value={scoreDraft.min} onChange={event => setScoreDraft(current => ({ min: Math.min(Number(event.target.value), current.max), max: current.max }))} aria-label="Минимальная оценка модели" /><input type="range" min="0" max="1" step="0.01" value={scoreDraft.max} onChange={event => setScoreDraft(current => ({ min: current.min, max: Math.max(Number(event.target.value), current.min) }))} aria-label="Максимальная оценка модели" /></div></fieldset>
          <label>Сортировка<select value={objectsQuery.sort} onChange={event => updateObjectsQuery({ ...objectsQuery, sort: event.target.value as Sort, quickView: null, offset: 0 })}><option value="SCORE_DESC">Оценка: по убыванию</option><option value="SCORE_ASC">Оценка: по возрастанию</option><option value="DISTANCE_TO_THRESHOLD_ASC">Ближе к порогу</option></select></label>
        </div>
      </section>

      <section className="objects-table-panel panel">
        <div className="objects-table-meta"><div><strong>Всего объектов: {integerFormat.format(objects?.total_count ?? result.summary.object_count)}</strong>{objects && <span>Текущий порог: {scoreFormat.format(objects.threshold)}</span>}</div>{objects && <span>Показано {integerFormat.format(firstShown)}–{integerFormat.format(lastShown)} из {integerFormat.format(objects.filtered_count)}</span>}</div>
        {loadingObjects && <p className="objects-loading">Загружаем объекты…</p>}
        {objectsError && <div className="objects-error" role="alert"><p>Не удалось загрузить объекты из сохранённого OOF-результата.</p><button className="secondary-action" onClick={() => setRetryToken(value => value + 1)}>Повторить</button></div>}
        {objects && objects.filtered_count === 0 && <p className="objects-empty">По выбранным условиям объекты не найдены.</p>}
        {objects && objects.filtered_count > 0 && <div className="objects-table-viewport"><table className="objects-table"><thead><tr><th>Объект</th><th>Оценка модели</th><th title="Форма показывает целевое событие: ● — Да, ○ — Нет. Цвет показывает исход TP/TN/FP/FN.">Целевое событие <span aria-hidden="true">ⓘ</span></th><th>Положение относительно порога</th><th>Исход</th></tr></thead><tbody>{objects.items.map(item => <tr key={item.object_id} tabIndex={0} aria-label={`Открыть карточку объекта ${item.identifier_display}`} onClick={() => openObject(item.object_id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openObject(item.object_id) } }}><td>{item.identifier_display}</td><td>{scoreValueFormat.format(item.score)}</td><td>{targetMarker(item)}</td><td className="objects-threshold-position">{item.predicted_positive ? '↑ Выше порога' : '↓ Ниже порога'}</td><td><span className={outcomeClass(item.outcome)}>{item.outcome}</span></td></tr>)}</tbody></table></div>}
        {objects && objects.filtered_count > 0 && <div className="objects-chunk-controls"><button className="secondary-action" disabled={objects.offset === 0 || loadingObjects} onClick={() => updateObjectsQuery({ ...objectsQuery, offset: Math.max(0, objectsQuery.offset - chunkSize) })}>← Предыдущие</button><button className="secondary-action" disabled={objects.offset + objects.returned_count >= objects.filtered_count || loadingObjects} onClick={() => updateObjectsQuery({ ...objectsQuery, offset: objectsQuery.offset + chunkSize })}>Следующие →</button></div>}
      </section>
    </>}
  </main></div>
}
