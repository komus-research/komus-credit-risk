import { Sidebar } from '../components/Sidebar'
import { navigate, routes } from '../routing'

export function QualityPage({ onHome }: { onHome: () => void }) {
  return <div className="app-shell features-shell"><Sidebar active="analysis" onHome={onHome} /><main className="workspace algorithm-boundary"><p className="eyebrow">Шаг 4 из 5</p><section className="panel"><h1>Проверка качества</h1><p>Алгоритм и его конфигурация сохранены. Проверка качества будет добавлена на следующем этапе.</p><button className="secondary-action" onClick={() => navigate(routes.algorithm)}>Назад к алгоритму</button></section></main></div>
}
