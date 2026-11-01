import { useEffect } from 'react'
import { Icon } from '../components/Icon'
import { demoHome } from './demoHomeFixture'
import './demoHome.css'

const asset = (path: string) => '/native-assets/' + path
const summary = [
  ['folder', 'Проектов'],
  ['box', 'Сохранённых моделей'],
  ['clock', 'Проектов в работе'],
  ['check', 'Завершённых проектов'],
] as const
const number = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

export function isDemoHomeMode() {
  return new URLSearchParams(window.location.search).get('demo') === '1'
}

export function openLiveHome() {
  window.location.assign(window.location.pathname + '#/home')
}

/**
 * Read-only showcase. No API reads or writes, model-training actions,
 * project openings or clicks that could touch persisted data.
 */
export function DemoHomePage() {
  useEffect(() => {
    document.body.classList.add('home-v2-route')
    return () => document.body.classList.remove('home-v2-route')
  }, [])

  return <main className="workspace demo-home">
    <header className="topbar demo-topbar">
      <div className="page-heading">
        <h1>Главная <span className="demo-label" title="Условные данные, не результаты реальной модели">ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ</span></h1>
        <p>Проекты, модели и последние действия</p>
      </div>
      <div className="header-actions">
        <label className="search" title="Поиск доступен в рабочем режиме"><Icon name="search" size={23} /><input disabled placeholder="Поиск проектов и моделей..." aria-label="Поиск доступен в рабочем режиме" /></label>
        <button className="primary-action demo-real-switch" onClick={openLiveHome}><Icon name="arrow" size={20} />Рабочая версия</button>
      </div>
    </header>

    <section className="hero" aria-label="AXION"><img src={asset('images/home-hero-banner.webp')} alt="AXION — аналитическая платформа" /></section>

    <section className="summary-grid" aria-label="Условные сводные показатели">
      {summary.map(([icon, label], index) => <article className="summary-card" key={label}>
        <div className="summary-icon"><Icon name={icon} size={29} /></div>
        <div><p>{label}</p><strong>{demoHome.summary[index]}</strong></div>
      </article>)}
    </section>

    <section className="panel quick-start">
      <h2>Быстрый старт</h2>
      <div className="quick-grid">
        <DemoAction icon="plus" title="Новый анализ" description="Загрузить данные и начать новый анализ" accent />
        <DemoAction icon="box" title="Открыть модель" description="Использовать сохранённую модель без повторного обучения" />
        <DemoAction icon="menu" title="Продолжить последний проект" description="Retail 2026 · Этап: Алгоритм" />
      </div>
    </section>

    <div className="two-column">
      <section className="panel status-panel demo-status-panel">
        <div className="panel-title"><h2>Выполняется сейчас</h2><span>Пример процесса <Icon name="arrow" size={16}/></span></div>
        <div className="demo-process">
          <div className="demo-status-icon"><Icon name="box" size={22}/></div>
          <div className="demo-process-main">
            <strong>{demoHome.current.algorithm} · Проект «{demoHome.current.project}»</strong>
            <div className="demo-process-note"><span>{demoHome.current.stage}</span><span>{demoHome.current.fold}</span></div>
            <div className="demo-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={demoHome.current.progress} aria-label="Демонстрационный прогресс"><span style={{width:demoHome.current.progress + '%'}}/></div>
          </div><b className="demo-progress-value">{demoHome.current.progress}%</b>
        </div>
      </section>
      <section className="panel status-panel demo-status-panel">
        <div className="panel-title"><h2>Требует внимания</h2><span>Пример уведомления <Icon name="arrow" size={16}/></span></div>
        <div className="demo-attention">
          <div className="demo-attention-icon"><Icon name="warning" size={24}/></div>
          <div className="demo-attention-main"><strong>{demoHome.attention.project}</strong><p>{demoHome.attention.title}</p></div>
          <small>{demoHome.attention.date}</small>
        </div>
      </section>
    </div>

    <section className="panel projects-panel">
      <div className="panel-title"><h2>Последние проекты</h2><span>Примеры проектов <Icon name="arrow" size={16}/></span></div>
      <div className="table-wrap">
        <table className="data-table demo-projects-table">
          <thead><tr><th>Название проекта</th><th>Последнее изменение</th><th>Этап</th><th>Модель</th><th>Датасет</th><th>Статус</th><th>Последнее действие</th></tr></thead>
          <tbody>{demoHome.projects.map(project => <tr key={project.name}>
            <td className="home-project-name"><span className="demo-folder"><Icon name="folder" size={14}/></span><strong>{project.name}</strong></td>
            <td>{project.updated}</td>
            <td>{project.stage}</td>
            <td>{project.model}</td>
            <td>{project.dataset}</td>
            <td><span className={'demo-status-pill ' + project.statusTone}><i />{project.status}</span></td>
            <td>{project.action}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </section>

    <section className="panel projects-panel models-panel">
      <div className="panel-title"><h2>Сохранённые модели</h2><span>Примеры моделей <Icon name="arrow" size={16}/></span></div>
      <div className="table-wrap">
        <table className="data-table demo-models-table">
          <thead><tr><th>Название модели</th><th>Алгоритм</th><th>Версия</th><th>Дата обучения</th><th>Датасет</th><th>Признаков</th><th>Gini</th><th>ROC-AUC</th><th>PR-AUC</th><th>Статус</th></tr></thead>
          <tbody>{demoHome.models.map(model => <tr key={model.name}>
            <td><strong>{model.name}</strong></td><td>{model.algorithm}</td><td>{model.version}</td>
            <td>{model.trained}</td><td>{model.dataset}</td><td>{model.features}</td>
            <td>{number.format(model.gini)}</td><td>{number.format(model.rocAuc)}</td><td>{number.format(model.prAuc)}</td>
            <td><span className={'demo-status-pill ' + (model.status.startsWith('Архивная') ? 'archived' : 'ready')}><i/>{model.status}</span></td>
          </tr>)}</tbody>
        </table>
      </div>
    </section>
    <p className="demo-footnote">Демонстрационный режим · Все проекты, даты, значения и показатели на этой странице вымышлены. Реальные данные и модели не изменяются.</p>
  </main>
}

function DemoAction({ icon, title, description, accent = false }: { icon: 'plus' | 'box' | 'menu'; title: string; description: string; accent?: boolean }) {
  return <div className={'quick-action demo-action ' + (accent ? 'accent' : '')} title="Демонстрация интерфейса — для действий откройте рабочую версию">
    <span className="quick-icon"><Icon name={icon} size={30}/></span>
    <span><strong>{title}</strong><small>{description}</small></span>
    <Icon name="arrow" size={19}/>
  </div>
}
