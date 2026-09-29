import { Sidebar } from '../components/Sidebar'
import { navigate, routes } from '../routing'

export function AlgorithmPage({ onHome }: { onHome: () => void }) {
  return <div className="app-shell features-shell"><Sidebar active="analysis" onHome={onHome} /><main className="workspace algorithm-boundary"><p className="eyebrow">Новый анализ · шаг 3</p><section className="panel"><h1>Выбор алгоритма</h1><p>Выбор признаков сохранён. Настройка алгоритма будет добавлена на следующем этапе.</p><button className="secondary-action" onClick={() => navigate(routes.features)}>Изменить признаки</button></section></main></div>
}
