import { Icon } from './Icon'
// @ts-expect-error Vite resolves CSS Modules at runtime; this project has no generated CSS declarations.
import styles from './Sidebar.module.css'

export function Sidebar({ active, onHome, onNewAnalysis, onDocumentation, onHotkeys, onAbout }: { active: 'home' | 'analysis' | 'documentation' | 'hotkeys' | 'about'; onHome: () => void; onNewAnalysis?: () => void; onDocumentation: () => void; onHotkeys: () => void; onAbout: () => void }) {
  return <aside className={styles.sidebar}>
    <div className={styles.brand} role="img" aria-label="AXION" />
    <nav aria-label="Основная навигация" className={styles.navigation}>
      <button className={`${styles.item} ${active === 'home' ? styles.active : ''}`} onClick={onHome} aria-current={active === 'home' ? 'page' : undefined}><Icon name="home" size={24} /><span>Главная</span></button>
      {onNewAnalysis ? <button className={`${styles.item} ${styles.newAnalysis} ${active === 'analysis' ? styles.active : ''}`} onClick={onNewAnalysis}><Icon name="plus" size={24} /><span>Новый анализ</span></button> : <div className={`${styles.item} ${styles.newAnalysis} ${active === 'analysis' ? styles.active : ''}`}><Icon name="plus" size={24} /><span>Новый анализ</span></div>}
      <button className={styles.item} disabled title="Будет доступно позже"><Icon name="model" size={24} /><span>Модели</span></button>
      <button className={styles.item} disabled title="Будет доступно позже"><Icon name="menu" size={24} /><span>История</span></button>
      <button className={`${styles.item} ${styles.withDivider}`} disabled title="Будет доступно позже"><Icon name="settings" size={24} /><span>Настройки</span></button>
    </nav>
    <nav aria-label="Справка" className={styles.utility}>
      <button className={`${styles.utilityItem} ${active === 'documentation' ? styles.utilityActive : ''}`} onClick={onDocumentation}><Icon name="file" size={20} /><span>Документация</span></button>
      <button className={`${styles.utilityItem} ${active === 'hotkeys' ? styles.utilityActive : ''}`} onClick={onHotkeys}><Icon name="keyboard" size={20} /><span>Горячие клавиши</span></button>
      <button className={`${styles.utilityItem} ${active === 'about' ? styles.utilityActive : ''}`} onClick={onAbout}><Icon name="info" size={20} /><span>О платформе</span></button>
    </nav>
  </aside>
}
