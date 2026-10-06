import { useEffect, useState } from 'react'
import { getProjects, openProject, type ProjectWorkspace, type ProjectWorkspaceList } from '../api/inference'
import { buildInferenceResultRoute, navigate } from '../routing'
import { Icon } from '../components/Icon'

const dateFormat = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })

export function HistoryPage() {
  const [projects, setProjects] = useState<ProjectWorkspaceList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [opening, setOpening] = useState<string | null>(null)
  useEffect(() => { void getProjects().then(setProjects).catch(reason => setError(reason instanceof Error ? reason.message : 'Не удалось загрузить историю проектов.')) }, [])
  const continueProject = async (project: ProjectWorkspace) => {
    if (!project.resumable || opening) return
    setOpening(project.project_id); setError(null)
    try { navigate(buildInferenceResultRoute((await openProject(project.project_id)).inference_result_id)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось открыть проект.') }
    finally { setOpening(null) }
  }
  return <main className="workspace"><header className="topbar"><div className="page-heading"><h1>История проектов</h1><p>Сохранённые рабочие пространства открывают точный immutable Result через проверенную границу Project Open.</p></div></header>{error && <p className="inference-inline-error" role="alert"><Icon name="warning" />{error}</p>}{!projects && !error && <p className="feature-loading">Загружаем проекты…</p>}{projects && <section className="panel projects-panel"><div className="panel-title"><h2>Все проекты</h2><span>{projects.total_count}</span></div><div className="table-wrap"><table className="data-table projects-table"><thead><tr><th>Название проекта</th><th>Модель</th><th>Источник</th><th>Объектов</th><th>Последнее открытие</th><th /></tr></thead><tbody>{projects.items.length === 0 ? <tr><td colSpan={6} className="table-empty">Сохранённых проектов пока нет.</td></tr> : projects.items.map(item => <tr key={item.project_id}><td className="home-project-name" title={item.name}><strong>{item.name}</strong></td><td>{item.model_display_name ?? 'Недоступно'}</td><td>{item.source_display_name ?? 'Недоступно'}</td><td>{item.row_count?.toLocaleString('ru-RU') ?? '—'}</td><td>{item.last_opened_at ? dateFormat.format(new Date(item.last_opened_at)) : '—'}</td><td><button className="secondary-action" disabled={!item.resumable || opening !== null} onClick={() => void continueProject(item)}>{opening === item.project_id ? 'Открываем…' : 'Продолжить'}</button></td></tr>)}</tbody></table></div></section>}</main>
}
