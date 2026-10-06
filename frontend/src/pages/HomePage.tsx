import { useEffect, useRef, useState } from 'react'
import { getModelVersions, type ModelVersionList, type ModelVersionListItem } from '../api/models'
import { getProjects, openProject, type ProjectWorkspace, type ProjectWorkspaceList } from '../api/inference'
import type { NativeSession } from '../api/session'
import { buildInferenceResultRoute, buildModelDetailRoute, navigate } from '../routing'
import { Icon } from '../components/Icon'

const asset = (path: string) => `/native-assets/${path}`
const summary = [['folder', 'Проектов'], ['box', 'Сохранённых моделей'], ['clock', 'Проектов в работе'], ['check', 'Завершённых проектов']] as const
const metricFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
const savedDateFormat = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
function savedDate(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : savedDateFormat.format(date) }

export function HomePage({ session, onContinue, onStartNewAnalysis, onOpenModels, startingNewAnalysis }: { session: NativeSession | null; onContinue: () => void; onStartNewAnalysis: () => void; onOpenModels: () => void; startingNewAnalysis: boolean }) {
  const [models, setModels] = useState<ModelVersionList | null>(null)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [modelsLoading, setModelsLoading] = useState(true)
  const [modelsRetryToken, setModelsRetryToken] = useState(0)
  const [projects, setProjects] = useState<ProjectWorkspaceList | null>(null)
  const [projectsError, setProjectsError] = useState<string | null>(null)
  const [openingProjectId, setOpeningProjectId] = useState<string | null>(null)
  const requestGeneration = useRef(0)

  useEffect(() => { document.body.classList.add('home-v2-route'); return () => document.body.classList.remove('home-v2-route') }, [])
  useEffect(() => {
    const controller = new AbortController(); const generation = ++requestGeneration.current
    setModelsLoading(true); setModelsError(null)
    void getModelVersions({ offset: 0, limit: 5, sort: 'SAVED_DESC' }, controller.signal).then(value => { if (generation === requestGeneration.current) setModels(value) }).catch(reason => { if (!controller.signal.aborted && generation === requestGeneration.current) setModelsError(reason instanceof Error ? reason.message : 'Не удалось загрузить сохранённые модели.') }).finally(() => { if (generation === requestGeneration.current) setModelsLoading(false) })
    return () => controller.abort()
  }, [modelsRetryToken])
  useEffect(() => { void getProjects(0, 50).then(value => { setProjects(value); setProjectsError(null) }).catch(reason => setProjectsError(reason instanceof Error ? reason.message : 'Не удалось загрузить проекты.')) }, [])

  const savedModelCount = !modelsLoading && !modelsError && models ? models.total_count : '—'
  const lastProject = projects?.items[0] ?? null
  const values = [projects?.total_count ?? '—', savedModelCount, projects?.resumable_count ?? '—', '—']
  const continueProject = async (project: ProjectWorkspace) => {
    if (!project.resumable || openingProjectId) return
    setOpeningProjectId(project.project_id); setProjectsError(null)
    try { navigate(buildInferenceResultRoute((await openProject(project.project_id)).inference_result_id)) }
    catch (reason) { setProjectsError(reason instanceof Error ? reason.message : 'Не удалось открыть проект.') }
    finally { setOpeningProjectId(null) }
  }

  return <main className="workspace">
    <header className="topbar"><div className="page-heading"><h1>Главная</h1><p>Проекты, модели и последние действия</p></div><div className="header-actions"><label className="search" title="Поиск станет доступен после подключения истории и каталога моделей"><Icon name="search" size={23} /><input disabled placeholder="Поиск проектов и моделей..." aria-label="Поиск проектов и моделей — пока недоступен" /></label><button className="primary-action" disabled={startingNewAnalysis} onClick={onStartNewAnalysis}><Icon name="plus" size={27} />Новый анализ</button></div></header>
    <section className="hero" aria-label="AXION"><img src={asset('images/home-hero-banner.webp')} alt="AXION — аналитическая платформа" /></section>
    <section className="summary-grid" aria-label="Сводные показатели">{summary.map(([icon, label], index) => <article className="summary-card" key={label} title={index === 1 ? modelsError ?? undefined : projectsError ?? undefined}><div className="summary-icon"><Icon name={icon} size={29} /></div><div><p>{label}</p><strong>{values[index]}</strong></div></article>)}</section>
    <section className="panel quick-start"><h2>Быстрый старт</h2><div className="quick-grid"><FutureAction icon="plus" title="Новый анализ" description="Загрузить данные и начать новый анализ" accent onClick={onStartNewAnalysis} disabled={startingNewAnalysis} /><FutureAction icon="box" title="Открыть модель" description="Использовать сохранённую модель без повторного обучения" onClick={onOpenModels} disabled={false} />{session?.analysis_active && session.has_meaningful_temporary_work ? <FutureAction icon="menu" title="Продолжить текущий анализ" description="Вернуться к активному анализу" accent onClick={onContinue} disabled={false} /> : <FutureAction icon="menu" title="Продолжить последний проект" description={lastProject?.name ?? 'Сохранённых проектов пока нет'} onClick={lastProject ? () => void continueProject(lastProject) : undefined} disabled={!lastProject?.resumable || openingProjectId !== null} />}</div></section>
    <div className="two-column"><section className="panel status-panel"><PanelTitle title="Выполняется сейчас" actionLabel="Все процессы" /><div className="empty-state"><div className="empty-icon"><Icon name="clock" /></div><div><strong>Сейчас нет фоновых операций</strong><p>Операции анализа выполняются на соответствующих шагах.</p></div></div></section><section className="panel status-panel"><PanelTitle title="Требует внимания" actionLabel="Все уведомления" /><div className="empty-state"><div className="empty-icon attention"><Icon name="check" /></div><div><strong>Нет уведомлений, требующих внимания</strong><p>Центр уведомлений пока не подключён.</p></div></div></section></div>
    {projectsError && <p className="inference-inline-error" role="alert"><Icon name="warning" />{projectsError}</p>}
    <section className="panel projects-panel"><PanelTitle title="Последние проекты" actionLabel="Все проекты" onAction={() => navigate('#/history')} /><ProjectsTable projects={projects} openingProjectId={openingProjectId} onContinue={continueProject} /></section>
    <section className="panel projects-panel models-panel"><PanelTitle title="Сохранённые модели" actionLabel="Все модели" onAction={onOpenModels} /><SavedModelsTable loading={modelsLoading} error={modelsError} models={models} onRetry={() => setModelsRetryToken(value => value + 1)} onOpenModel={modelVersionId => navigate(buildModelDetailRoute(modelVersionId))} /></section>
  </main>
}

function FutureAction({ icon, title, description, accent = false, onClick, disabled = true }: { icon: 'plus' | 'box' | 'menu'; title: string; description: string; accent?: boolean; onClick?: () => void; disabled?: boolean }) { return <button className={`quick-action ${accent ? 'accent' : ''}`} disabled={disabled} onClick={onClick}><span className="quick-icon"><Icon name={icon} size={30} /></span><span><strong>{title}</strong><small>{description}</small></span><Icon name="arrow" size={19} /></button> }
function PanelTitle({ title, actionLabel, onAction }: { title: string; actionLabel: string; onAction?: () => void }) { return <div className="panel-title"><h2>{title}</h2><button className="panel-link" type="button" disabled={!onAction} onClick={onAction}>{actionLabel} <Icon name="arrow" size={17} /></button></div> }
function ProjectsTable({ projects, openingProjectId, onContinue }: { projects: ProjectWorkspaceList | null; openingProjectId: string | null; onContinue: (project: ProjectWorkspace) => void }) { const columns = ['Название проекта', 'Модель', 'Источник', 'Объектов', 'Действие']; return <div className="table-wrap"><table className="data-table projects-table"><thead><tr>{columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{!projects ? <tr><td colSpan={columns.length} className="table-empty">Загружаем проекты…</td></tr> : projects.items.length === 0 ? <tr><td colSpan={columns.length} className="table-empty">Сохранённых проектов пока нет.</td></tr> : projects.items.slice(0, 5).map(item => <tr key={item.project_id}><td className="home-project-name" title={item.name}><strong>{item.name}</strong></td><td>{item.model_display_name ?? 'Недоступно'}</td><td>{item.source_display_name ?? 'Недоступно'}</td><td>{item.row_count?.toLocaleString('ru-RU') ?? '—'}</td><td><button className="text-action" disabled={!item.resumable || openingProjectId !== null} onClick={() => onContinue(item)}>{openingProjectId === item.project_id ? 'Открываем…' : 'Продолжить'}</button></td></tr>)}</tbody></table></div> }
function SavedModelsTable({ loading, error, models, onRetry, onOpenModel }: { loading: boolean; error: string | null; models: ModelVersionList | null; onRetry: () => void; onOpenModel: (modelVersionId: string) => void }) { const columns = ['Название модели', 'Алгоритм', 'Версия', 'Сохранена', 'Датасет', 'Признаков', 'OOF Gini', 'OOF ROC-AUC', 'OOF PR-AUC', 'Статус']; const open = (item: ModelVersionListItem) => onOpenModel(item.model_version_id); return <div className="table-wrap"><table className="data-table models-table"><thead><tr>{columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{loading && <tr><td colSpan={columns.length} className="table-empty home-models-state"><Icon name="clock" size={18} /> Загружаем сохранённые модели…</td></tr>}{!loading && error && <tr><td colSpan={columns.length} className="table-empty home-models-error" role="alert"><span><Icon name="warning" size={18} /> {error}</span><button className="secondary-action" onClick={onRetry}>Повторить</button></td></tr>}{!loading && !error && models?.total_count === 0 && <tr><td colSpan={columns.length} className="table-empty">Сохранённых моделей пока нет.</td></tr>}{!loading && !error && models?.items.map(item => <tr className="home-model-row" key={item.model_version_id} tabIndex={0} onClick={() => open(item)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(item) } }}><td className="home-model-cell-ellipsis" title={item.display_name}><strong>{item.display_name}</strong></td><td className="home-model-cell-ellipsis" title={`${item.model_display_name} · ${item.algorithm_version}`}>{item.model_display_name}</td><td>{item.display_version}</td><td>{savedDate(item.saved_at)}</td><td className="home-model-cell-ellipsis" title={item.dataset_name}>{item.dataset_name}</td><td>{item.feature_count}</td><td>{metricFormat.format(item.oof_gini)}</td><td>{metricFormat.format(item.oof_roc_auc)}</td><td>{metricFormat.format(item.oof_pr_auc)}</td><td><span className="home-model-saved">Сохранена</span></td></tr>)}</tbody></table></div> }
