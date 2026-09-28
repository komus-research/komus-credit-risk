import { useEffect, useState } from 'react'
import { getNativeSession, type NativeSession } from '../api/session'
import { Icon } from '../components/Icon'

const asset = (path: string) => `/native-assets/${path}`

const summary = [
  ['folder', 'Проектов'],
  ['box', 'Сохранённых моделей'],
  ['clock', 'Проектов в работе'],
  ['check', 'Завершённых проектов'],
] as const

const navigation = [
  ['home', 'Главная', false],
  ['plus', 'Новый анализ', true],
  ['model', 'Модели', true],
  ['menu', 'Проекты / История', true],
  ['settings', 'Настройки', true],
] as const

export function HomePage() {
  const [session, setSession] = useState<NativeSession | null>(null)

  useEffect(() => {
    void getNativeSession().then(setSession).catch(() => setSession(null))
  }, [])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <img className="brand" src={asset('brand/logo-primary-dark.png')} alt="AXION — аналитическая платформа" />
        <nav aria-label="Основная навигация" className="navigation">
          {navigation.map(([icon, label, disabled]) => (
            <button key={label} className={`nav-item ${label === 'Главная' ? 'is-active' : ''} ${label === 'Настройки' ? 'with-divider' : ''}`} disabled={disabled} title={disabled ? 'Будет доступно позже' : undefined}>
              <Icon name={icon} size={26} /><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="profile"><div className="avatar">АП</div><div><strong>Андреев П. С.</strong><small>Аналитик</small></div><Icon name="arrow" size={18} /></div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div><h1>Главная</h1><p>Проекты, модели и последние действия</p></div>
          <div className="header-actions">
            <label className="search" title="Поиск станет доступен после подключения истории и каталога моделей"><Icon name="search" size={23} /><input disabled placeholder="Поиск проектов и моделей..." aria-label="Поиск проектов и моделей — пока недоступен" /></label>
            <button className="primary-action" disabled title="Будет доступно позже"><Icon name="plus" size={27} />Новый анализ</button>
          </div>
        </header>

        <section className="hero" aria-label="AXION"><img src={asset('images/home-hero-banner.webp')} alt="AXION — аналитическая платформа" /></section>

        <section className="summary-grid" aria-label="Сводные показатели">
          {summary.map(([icon, label]) => <article className="summary-card" key={label} title="Сводная история пока не подключена" aria-label={`${label}: данные пока недоступны`}><div className="summary-icon"><Icon name={icon} size={29} /></div><div><p>{label}</p><strong>—</strong></div></article>)}
        </section>

        <section className="panel quick-start"><h2>Быстрый старт</h2><div className="quick-grid">
          <FutureAction icon="plus" title="Новый анализ" description="Загрузить данные и начать новый анализ" accent />
          <FutureAction icon="box" title="Открыть модель" description="Использовать сохранённую модель без повторного обучения" />
          <FutureAction icon="menu" title="Продолжить последний проект" description="История проектов пока не подключена" />
        </div></section>

        {session?.has_meaningful_temporary_work && <section className="session-note" aria-live="polite"><Icon name="clock" /><span>В текущей сессии есть незавершённый анализ.</span></section>}

        <div className="two-column">
          <section className="panel status-panel"><PanelTitle title="Выполняется сейчас" actionLabel="Все процессы" /><div className="empty-state"><div className="empty-icon"><Icon name="clock" /></div><div><strong>Сейчас нет фоновых операций</strong><p>Операции анализа выполняются на соответствующих шагах.</p></div></div></section>
          <section className="panel status-panel"><PanelTitle title="Требует внимания" actionLabel="Все уведомления" /><div className="empty-state"><div className="empty-icon attention"><Icon name="check" /></div><div><strong>Нет уведомлений, требующих внимания</strong><p>Центр уведомлений пока не подключён.</p></div></div></section>
        </div>

        <section className="panel projects-panel"><PanelTitle title="Последние проекты" actionLabel="Все проекты" /><DataTable columns={['Название проекта', 'Последнее изменение', 'Этап', 'Модель', 'Датасет', 'Статус', 'Последнее действие']} empty="История проектов пока не подключена" className="projects-table" /></section>

        <section className="panel projects-panel models-panel"><PanelTitle title="Сохранённые модели" actionLabel="Все модели" /><DataTable columns={['Название модели', 'Алгоритм', 'Версия', 'Дата обучения', 'Датасет', 'Признаков', 'Gini', 'ROC-AUC', 'PR-AUC', 'Статус']} empty="Каталог сохранённых моделей пока не подключён" className="models-table" /></section>
      </main>
    </div>
  )
}

function FutureAction({ icon, title, description, accent = false }: { icon: 'plus' | 'box' | 'menu'; title: string; description: string; accent?: boolean }) {
  return <button className={`quick-action ${accent ? 'accent' : ''}`} disabled title="Будет доступно позже"><span className="quick-icon"><Icon name={icon} size={30} /></span><span><strong>{title}</strong><small>{description}</small></span><Icon name="arrow" size={19} /></button>
}

function PanelTitle({ title, actionLabel }: { title: string; actionLabel: string }) {
  return <div className="panel-title"><h2>{title}</h2><span title="Будет доступно позже" aria-label={`${actionLabel} — будет доступно позже`}>{actionLabel} <Icon name="arrow" size={17} /></span></div>
}

function DataTable({ columns, empty, className }: { columns: string[]; empty: string; className: string }) {
  return <div className="table-wrap"><table className={`data-table ${className}`}><thead><tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead><tbody><tr><td colSpan={columns.length} className="table-empty">{empty}</td></tr></tbody></table></div>
}
