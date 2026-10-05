import { useEffect, useRef, useState } from 'react'
import { getModelVersions, type ModelVersionList } from '../api/models'
import { buildModelDetailRoute, navigate } from '../routing'
import { Icon } from '../components/Icon'

const pageSize = 50
const metricFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
const dateFormat = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })

function savedDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : dateFormat.format(date)
}

export function ModelsPage() {
  const [models, setModels] = useState<ModelVersionList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [retryToken, setRetryToken] = useState(0)
  const requestGeneration = useRef(0)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim())
      setOffset(0)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    const controller = new AbortController()
    const generation = ++requestGeneration.current
    setLoading(true)
    setError(null)
    void getModelVersions({ offset, limit: pageSize, search: search || undefined, sort: 'SAVED_DESC' }, controller.signal)
      .then(value => { if (generation === requestGeneration.current) setModels(value) })
      .catch(reason => {
        if (!controller.signal.aborted && generation === requestGeneration.current) {
          setError(reason instanceof Error ? reason.message : 'Не удалось загрузить сохранённые модели.')
        }
      })
      .finally(() => { if (generation === requestGeneration.current) setLoading(false) })
    return () => controller.abort()
  }, [offset, retryToken, search])

  const openDetail = (modelVersionId: string) => navigate(buildModelDetailRoute(modelVersionId))
  const firstShown = models && models.returned_count ? models.offset + 1 : 0
  const lastShown = models ? models.offset + models.returned_count : 0

  return <main className="workspace models-workspace">
    <header className="models-header">
      <div><h1>Модели</h1><p>Управляйте сохранёнными обученными моделями и доступными алгоритмами.</p></div>
      <button className="primary-action models-connect-action" disabled title="Возможность пока не подключена"><Icon name="plus" />Подключить алгоритм</button>
    </header>

    <div className="models-tabs" role="tablist" aria-label="Разделы моделей">
      <button className="active" role="tab" aria-selected="true"><Icon name="layers" />Обученные модели</button>
      <button role="tab" aria-selected="false" disabled title="Возможность пока не подключена"><Icon name="box" />Алгоритмы</button>
    </div>

    <section className="models-controls panel" aria-label="Поиск сохранённых моделей">
      <label className="models-search"><Icon name="search" /><input value={searchInput} onChange={event => setSearchInput(event.target.value)} placeholder="Найти модель…" aria-label="Найти модель" /></label>
      <span className="models-control-note">Поиск выполняется по сохранённой библиотеке</span>
    </section>

    <section className="models-list-panel panel">
      <div className="models-list-heading"><div><h2>Обученные модели</h2><p>Каждая строка — отдельная сохранённая версия модели. Метрики приведены по OOF.</p></div>{models && <span>{models.filtered_count} из {models.total_count}</span>}</div>
      {loading && <div className="models-state"><Icon name="clock" size={28} /><p>Загружаем сохранённые модели…</p></div>}
      {error && <div className="models-state models-state-error" role="alert"><Icon name="warning" size={28} /><div><strong>Не удалось загрузить модели</strong><p>{error}</p></div><button className="secondary-action" onClick={() => setRetryToken(value => value + 1)}>Повторить</button></div>}
      {!loading && !error && models?.filtered_count === 0 && <div className="models-state"><Icon name="model" size={28} /><div><strong>Сохранённых моделей пока нет</strong><p>{search ? 'Попробуйте изменить поисковый запрос.' : 'Сохраните модель на странице результата, чтобы она появилась в библиотеке.'}</p></div></div>}
      {!loading && !error && models && models.filtered_count > 0 && <>
        <div className="models-table-wrap"><table className="models-library-table"><thead><tr><th>Название модели</th><th>Алгоритм</th><th>Датасет</th><th>Признаки</th><th>Сохранена</th><th>Качество OOF</th><th aria-label="Открыть" /></tr></thead><tbody>{models.items.map(item => <tr key={item.model_version_id} tabIndex={0} onClick={() => openDetail(item.model_version_id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openDetail(item.model_version_id) } }}><td><strong>{item.display_name}</strong><small>{item.display_version}</small></td><td><span className="models-algorithm-chip">{item.model_display_name}</span><small>{item.algorithm_version}</small></td><td>{item.dataset_name}</td><td>{item.feature_count}</td><td><small>Сохранена</small>{savedDate(item.saved_at)}</td><td><div className="models-metrics"><span>Gini <b>{metricFormat.format(item.oof_gini)}</b></span><span>ROC-AUC <b>{metricFormat.format(item.oof_roc_auc)}</b></span><span>PR-AUC <b>{metricFormat.format(item.oof_pr_auc)}</b></span></div></td><td><button className="models-open-action" onClick={event => { event.stopPropagation(); openDetail(item.model_version_id) }} aria-label={`Открыть ${item.display_name}`}><Icon name="arrow" /></button></td></tr>)}</tbody></table></div>
        <footer className="models-pagination"><span>Показано {firstShown}–{lastShown} из {models.filtered_count}</span><div><button className="secondary-action" disabled={models.offset === 0} onClick={() => setOffset(value => Math.max(0, value - pageSize))}>← Предыдущие</button><button className="secondary-action" disabled={models.offset + models.returned_count >= models.filtered_count} onClick={() => setOffset(value => value + pageSize)}>Следующие →</button></div></footer>
      </>}
    </section>
  </main>
}
