import { Icon } from './Icon'

const asset = (path: string) => `/native-assets/${path}`

export function Sidebar({ active, onHome, onNewAnalysis }: { active: 'home' | 'analysis'; onHome: () => void; onNewAnalysis?: () => void }) {
  return <aside className="sidebar shared-sidebar">
    <div className="brand-block" role="img" aria-label="AXION"><img className="brand-mark" src={asset('brand/logo-mark-primary.png')} alt="" /><img className="brand-wordmark" src={asset('brand/wordmark-dark.png')} alt="" /></div>
    <nav aria-label="Основная навигация" className="navigation">
      <button className={`nav-item ${active === 'home' ? 'is-active' : ''}`} onClick={onHome} aria-current={active === 'home' ? 'page' : undefined}><Icon name="home" size={26} /><span>Главная</span></button>
      {onNewAnalysis ? <button className={`nav-item ${active === 'analysis' ? 'is-active' : ''}`} onClick={onNewAnalysis}><Icon name="plus" size={26} /><span>Новый анализ</span></button> : <div className={`nav-item ${active === 'analysis' ? 'is-active' : ''}`}><Icon name="plus" size={26} /><span>Новый анализ</span></div>}
      <button className="nav-item" disabled title="Будет доступно позже"><Icon name="model" size={26} /><span>Модели</span></button>
      <button className="nav-item" disabled title="Будет доступно позже"><Icon name="menu" size={26} /><span>Проекты / История</span></button>
      <button className="nav-item with-divider" disabled title="Будет доступно позже"><Icon name="settings" size={26} /><span>Настройки</span></button>
    </nav>
    <div className="profile"><div className="avatar">АП</div><div><strong>Андреев П. С.</strong><small>Аналитик</small></div><Icon name="arrow" size={18} /></div>
  </aside>
}
