/**
 * Portfolio-only fixture. Every metric, object and status here is fictional.
 * Never pass these objects to the live API or the model store.
 */
export type DemoProject = {
  name: string
  updated: string
  stage: string
  model: string
  dataset: string
  status: string
  statusTone: 'working' | 'completed' | 'ready' | 'attention'
  action: string
}
export type DemoModel = {
  name: string
  algorithm: string
  version: string
  trained: string
  dataset: string
  features: number
  gini: number
  rocAuc: number
  prAuc: number
  status: string
}
export const demoHome = {
  summary: [12, 8, 3, 7] as const,
  current: { project: 'Retail 2026', algorithm: 'CatBoost', stage: 'Обучение модели', fold: 'Fold 3 из 5', progress: 60 },
  attention: { project: 'Автокредиты', date: '28 авг. 2026', title: 'Проверьте новые категории признака «Тип клиента»', explanation: 'В демонстрационном наборе данных найдены значения, не встречавшиеся при подготовке модели.' },
  projects: [
    { name: 'Retail 2026', updated: '12 сент. 2026, 14:32', stage: 'Алгоритм', model: 'CatBoost v3.1', dataset: 'retail_2026_train', status: 'В работе', statusTone: 'working', action: 'Настроены гиперпараметры' },
    { name: 'Малый бизнес (МСБ)', updated: '10 сент. 2026, 11:15', stage: 'Результат', model: 'LightGBM v4.0', dataset: 'smb_2026', status: 'Обучение завершено', statusTone: 'completed', action: 'Получены метрики' },
    { name: 'Кредитные карты', updated: '5 сент. 2026, 09:48', stage: 'Проверка', model: 'XGBoost v2.0', dataset: 'cards_2026', status: 'Готов к использованию', statusTone: 'ready', action: 'Проверка качества завершена' },
    { name: 'Автокредиты', updated: '28 авг. 2026, 16:20', stage: 'Данные', model: '—', dataset: 'auto_2026', status: 'Требует внимания', statusTone: 'attention', action: 'Требуется проверка данных' },
  ] satisfies DemoProject[],
  models: [
    { name: 'Retail PD Model', algorithm: 'CatBoost', version: 'v3.1', trained: '12.09.2026', dataset: 'retail_2026_train', features: 47, gini: 0.804, rocAuc: 0.902, prAuc: 0.601, status: 'Готова к использованию' },
    { name: 'SMB Scoring Model', algorithm: 'LightGBM', version: 'v4.0', trained: '10.09.2026', dataset: 'smb_2026', features: 62, gini: 0.730, rocAuc: 0.865, prAuc: 0.547, status: 'Готова к использованию' },
    { name: 'Credit Cards PD', algorithm: 'XGBoost', version: 'v2.0', trained: '05.09.2026', dataset: 'cards_2026', features: 38, gini: 0.742, rocAuc: 0.871, prAuc: 0.493, status: 'Архивная версия' },
  ] satisfies DemoModel[],
}
