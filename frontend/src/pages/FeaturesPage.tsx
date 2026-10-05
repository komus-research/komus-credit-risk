import { useEffect, useMemo, useRef, useState } from 'react'
import { continueFeatures, getFeatures, patchFeatureSelection, type FeatureSelection, type NativeSession } from '../api/session'
import { Icon } from '../components/Icon'
import { navigate, routes } from '../routing'

const stepNames = ['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат']

export function FeaturesPage({ onSessionChange }: { onSessionChange: (session: NativeSession) => void }) {
  const [data, setData] = useState<FeatureSelection | null>(null)
  const [query, setQuery] = useState('')
  const [group, setGroup] = useState('all')
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestInFlight = useRef(false)
  const allSelected = Boolean(data && data.available_count > 0 && data.selected_count === data.available_count)
  const selectionProgress = data?.available_count ? Math.round((data.selected_count / data.available_count) * 100) : 0
  const searchActive = query.trim().length > 0

  useEffect(() => {
    void getFeatures()
      .then(next => { setData(next); setOpen(new Set()) })
      .catch(reason => setError(reason instanceof Error ? reason.message : 'Не удалось загрузить признаки.'))
  }, [])

  const visible = useMemo(() => {
    if (!data) return []
    const text = query.trim().toLocaleLowerCase('ru-RU')
    return data.features.filter(item =>
      (group === 'all' || item.group_id === group) &&
      (!text || item.display_name_ru.toLocaleLowerCase('ru-RU').includes(text) || item.column_name.toLocaleLowerCase('ru-RU').includes(text)),
    )
  }, [data, group, query])

  const save = (ids: string[]) => {
    if (requestInFlight.current) return
    requestInFlight.current = true
    setBusy(true)
    setError(null)
    void patchFeatureSelection(ids)
      .then(setData)
      .catch(reason => setError(reason instanceof Error ? reason.message : 'Не удалось сохранить выбор.'))
      .finally(() => { requestInFlight.current = false; setBusy(false) })
  }

  const toggle = (id: string) => {
    if (!data) return
    save(data.selected_feature_ids.includes(id)
      ? data.selected_feature_ids.filter(item => item !== id)
      : [...data.selected_feature_ids, id])
  }

  const setGroupIds = (ids: string[], include: boolean) => {
    if (!data) return
    const next = include
      ? [...new Set([...data.selected_feature_ids, ...ids])]
      : data.selected_feature_ids.filter(id => !ids.includes(id))
    save(next)
  }

  const continueToAlgorithm = () => {
    if (requestInFlight.current) return
    requestInFlight.current = true
    setBusy(true)
    setError(null)
    void continueFeatures()
      .then(next => { onSessionChange(next); navigate(routes.algorithm) })
      .catch(reason => setError(reason instanceof Error ? reason.message : 'Не удалось перейти к алгоритму.'))
      .finally(() => { requestInFlight.current = false; setBusy(false) })
  }

  return <main className="workspace features-workspace">
    <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{stepNames.map((name, index) => <li key={name} className={index === 0 ? 'completed' : index === 1 ? 'active' : ''}><span>{index === 0 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>
    <header className="features-header"><div><p className="eyebrow">Шаг 2 из 5</p><h1>Выбор признаков</h1><p>Выберите разрешённые признаки для текущего эксперимента.</p></div></header>
    {data && <>
      <section className="feature-dataset panel"><Icon name="box" size={30} /><div><strong>{data.dataset.display_name}</strong><span>{data.dataset.row_count.toLocaleString('ru-RU')} строк · {data.dataset.column_count} колонок · {data.dataset.source_format.toUpperCase()}</span></div><span>{data.dataset.source_type}</span></section>
      <section className="feature-summary-grid" aria-label="Сводка признаков">
        <article className="feature-summary-card panel"><span>Доступно признаков</span><strong>{data.available_count}</strong></article>
        <article className="feature-summary-card panel"><span>Выбрано для эксперимента</span><strong>{data.selected_count} <small>из {data.available_count}</small></strong><div className="feature-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={selectionProgress}><span style={{ width: `${selectionProgress}%` }} /></div><small className="feature-progress-label">{selectionProgress}%</small></article>
        <article className="feature-summary-card panel"><span>Групп</span><strong>{data.groups.length}</strong></article>
      </section>
      <section className="feature-toolbar panel"><button className="secondary-action" disabled={busy} onClick={() => save(allSelected ? [] : data.features.map(item => item.feature_id))}>{allSelected ? 'Убрать все признаки' : 'Включить все признаки'}</button><label className="feature-search"><Icon name="search" size={19} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Поиск по названию или колонке" /></label><label className="feature-filter">Группы<select value={group} onChange={event => setGroup(event.target.value)}><option value="all">Все группы</option>{data.groups.map(item => <option key={item.group_id} value={item.group_id}>{item.name_ru}</option>)}</select></label></section>
      {data.selected_count === 0 && <p className="feature-warning" role="alert">Выберите хотя бы один разрешённый признак.</p>}
      <section className="feature-groups">{data.groups.map(item => {
        const rows = visible.filter(row => row.group_id === item.group_id)
        if (!rows.length) return null
        const ids = data.features.filter(row => row.group_id === item.group_id).map(row => row.feature_id)
        const selectedInGroup = ids.filter(id => data.selected_feature_ids.includes(id)).length
        const expanded = searchActive || open.has(item.group_id)
        return <article className="feature-group panel" key={item.group_id}>
          <header>
            <button className="accordion-toggle" aria-expanded={expanded} onClick={() => { if (searchActive) return; setOpen(previous => { const next = new Set(previous); next.has(item.group_id) ? next.delete(item.group_id) : next.add(item.group_id); return next }) }}>
              <span>{expanded ? '⌄' : '›'}</span>
              <div className="feature-group-info"><h2>{item.name_ru} <small>{ids.length}</small></h2><p>{item.description_ru}</p><span className="feature-group-count">{selectedInGroup} из {ids.length} выбрано</span></div>
            </button>
            <div className="feature-group-actions"><button className="text-action" disabled={busy} onClick={() => setGroupIds(ids, true)}>Включить все</button><button className="text-action" disabled={busy} onClick={() => setGroupIds(ids, false)}>Убрать все</button></div>
          </header>
          {expanded && <div className="feature-rows">{rows.map(row => <label key={row.feature_id}>
            <input type="checkbox" checked={data.selected_feature_ids.includes(row.feature_id)} disabled={busy} onChange={() => toggle(row.feature_id)} />
            <strong className="feature-row-name">{row.display_name_ru}</strong>
            <span className="feature-row-description">{row.description_ru || '—'}</span>
            <code className="feature-row-technical">{row.column_name}</code>
          </label>)}</div>}
        </article>
      })}</section>
      <footer className="feature-footer"><button className="back-action" disabled={busy} onClick={() => navigate(routes.confirmation)}>← Назад к подтверждению</button><span>{error && <span className="feature-warning">{error}</span>}</span><button className="primary-action" disabled={busy || data.selected_count === 0} onClick={continueToAlgorithm}>Далее: алгоритм <Icon name="arrow" size={19} /></button></footer>
    </>}
    {!data && !error && <p className="feature-loading">Загружаем доступные признаки…</p>}{error && !data && <p className="feature-warning">{error}</p>}
  </main>
}
