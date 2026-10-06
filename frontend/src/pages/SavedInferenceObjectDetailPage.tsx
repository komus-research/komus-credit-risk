import { useEffect, useRef, useState } from 'react'
import { createSavedInferenceInterpretation, getSavedInferenceExplanation, getSavedInferenceObjectDetail, type SavedInferenceExplanation, type SavedInferenceInterpretation, type SavedInferenceObjectDetail } from '../api/inference'

const roles = [
  ['sales_manager', 'Менеджер продаж'], ['credit_controller', 'Кредитный контролёр'],
  ['lawyer', 'Юрист'], ['information_security', 'Информационная безопасность'],
] as const
const score = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
const exact = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 8 })

function errorText(value: unknown) { return value instanceof Error ? value.message : 'Не удалось получить данные объекта.' }
function directionLabel(direction: SavedInferenceExplanation['features'][number]['direction']) {
  return direction === 'increases_output' ? 'Повышает скор' : direction === 'decreases_output' ? 'Снижает скор' : 'Нейтральный вклад'
}

export function SavedInferenceObjectDetailPage({ inferenceResultId, rowId, threshold, onBack }: { inferenceResultId: string; rowId: string; threshold: number; onBack: () => void }) {
  const [detail, setDetail] = useState<SavedInferenceObjectDetail | null>(null)
  const [explanation, setExplanation] = useState<SavedInferenceExplanation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [shapError, setShapError] = useState<string | null>(null)
  const [mode, setMode] = useState<'BRIEF' | 'DETAILED'>('BRIEF')
  const [selectedRole, setSelectedRole] = useState<string>(roles[0][0])
  const [interpretations, setInterpretations] = useState<Record<string, SavedInferenceInterpretation>>({})
  const [interpretationError, setInterpretationError] = useState<Record<string, string>>({})
  const [busyRoles, setBusyRoles] = useState<Set<string>>(() => new Set())
  const lifecycleRef = useRef({ generation: 0, inferenceResultId, rowId })
  const bindingRef = useRef<{ detail: SavedInferenceObjectDetail | null; explanation: SavedInferenceExplanation | null }>({ detail, explanation })
  const busyRolesRef = useRef<Set<string>>(new Set())

  // Advance synchronously on navigation so a response resolving before the
  // effect cleanup still cannot publish state for the previous object.
  if (lifecycleRef.current.inferenceResultId !== inferenceResultId || lifecycleRef.current.rowId !== rowId) {
    lifecycleRef.current = { generation: lifecycleRef.current.generation + 1, inferenceResultId, rowId }
    busyRolesRef.current = new Set()
  }
  bindingRef.current = { detail, explanation }

  useEffect(() => {
    let active = true
    busyRolesRef.current = new Set()
    setDetail(null); setExplanation(null); setError(null); setShapError(null); setInterpretations({}); setInterpretationError({}); setBusyRoles(new Set())
    void getSavedInferenceObjectDetail(inferenceResultId, rowId, threshold).then(value => { if (active) setDetail(value) }).catch(value => { if (active) setError(errorText(value)) })
    // Local SHAP loads independently. This deliberately never invokes the interpreter.
    void getSavedInferenceExplanation(inferenceResultId, rowId).then(value => { if (active) setExplanation(value) }).catch(value => { if (active) setShapError(errorText(value)) })
    return () => { active = false }
  }, [inferenceResultId, rowId, threshold])

  const generate = async (role: string) => {
    const lifecycle = lifecycleRef.current
    const binding = bindingRef.current
    if (
      busyRolesRef.current.has(role)
      || lifecycle.inferenceResultId !== inferenceResultId
      || lifecycle.rowId !== rowId
      || binding.detail?.inference_result_id !== inferenceResultId
      || binding.explanation?.inference_result_id !== inferenceResultId
      || binding.explanation.row_id !== rowId
    ) return
    const expected = {
      generation: lifecycle.generation,
      inferenceResultId,
      rowId,
      modelVersionId: binding.explanation.model_version_id,
      explanationId: binding.explanation.explanation_id,
      evidenceHash: binding.explanation.evidence_hash,
    }
    const isCurrent = () => {
      const current = lifecycleRef.current
      const currentBinding = bindingRef.current
      return current.generation === expected.generation
        && current.inferenceResultId === expected.inferenceResultId
        && current.rowId === expected.rowId
        && currentBinding.detail?.model_version_id === expected.modelVersionId
        && currentBinding.explanation?.explanation_id === expected.explanationId
        && currentBinding.explanation?.evidence_hash === expected.evidenceHash
    }
    busyRolesRef.current.add(role)
    setBusyRoles(new Set(busyRolesRef.current))
    setInterpretationError(current => isCurrent() ? { ...current, [role]: '' } : current)
    try {
      const response = await createSavedInferenceInterpretation(inferenceResultId, rowId, role)
      if (!isCurrent()) return
      const responseMatches = response.inference_result_id === expected.inferenceResultId
        && response.row_id === expected.rowId
        && response.model_version_id === expected.modelVersionId
        && response.explanation_id === expected.explanationId
        && response.evidence_hash === expected.evidenceHash
      if (!responseMatches) {
        setInterpretationError(current => isCurrent() ? { ...current, [role]: 'Не удалось подтвердить привязку интерпретации к текущему объекту.' } : current)
        return
      }
      setInterpretations(current => isCurrent() ? { ...current, [role]: response } : current)
    } catch (value) {
      if (!isCurrent()) return
      setInterpretationError(current => isCurrent() ? { ...current, [role]: errorText(value) } : current)
    } finally {
      if (!isCurrent()) return
      busyRolesRef.current.delete(role)
      setBusyRoles(new Set(busyRolesRef.current))
    }
  }
  const selected = interpretations[selectedRole]
  const visible = explanation?.features.slice(0, mode === 'BRIEF' ? 5 : undefined) ?? []

  return <main className="workspace result-workspace object-detail-workspace">
    <button className="back-action objects-back-link" onClick={onBack}>← Назад к результату анализа</button>
    <header className="result-header"><p className="eyebrow">Модели / Анализ / Объект</p><h1>{detail ? `Объект ${detail.identifier_display}` : 'Объект анализа'}</h1><p>Прогноз для новых данных без известного фактического исхода.</p></header>
    {error && <section className="object-detail-error panel" role="alert"><strong>Не удалось загрузить объект</strong><p>{error}</p><button className="back-action" onClick={onBack}>← Назад к результату</button></section>}
    {!error && !detail && <section className="object-detail-loading panel" aria-busy="true"><p>Загружаем данные объекта…</p></section>}
    {detail && <>
      <section className="object-detail-facts panel" aria-label="Сведения об объекте">
        <article className="object-detail-fact"><small>Идентификатор</small><strong>{detail.identifier_display}</strong><span>{detail.identifier_column}</span></article>
        <article className="object-detail-fact"><small>Скор модели</small><strong>{score.format(detail.score)}</strong></article>
        <article className="object-detail-fact"><small>Текущий порог</small><strong>{exact.format(detail.threshold)}</strong><span>Рабочий порог модели не изменяется этим просмотром.</span></article>
        <article className="object-detail-fact"><small>Относительно порога</small><strong className="object-detail-position">{detail.position === 'ABOVE' ? '↑ Выше порога' : '↓ Ниже порога'}</strong></article>
        <article className="object-detail-fact"><small>Модель</small><strong>{detail.model_version_id}</strong><span>Inference Result: {detail.inference_result_id}</span></article>
      </section>
      <section className="panel"><h2>Точные значения признаков</h2><div className="local-explanation-feature-list detailed">{detail.features.map(feature => <article className="local-explanation-feature" key={feature.feature_id}><div className="local-explanation-feature-main"><strong>{feature.display_name_ru || feature.column_name}</strong><span>{feature.description_ru || feature.column_name}</span></div><div className="local-explanation-feature-value"><strong>{exact.format(feature.raw_value)}</strong></div></article>)}</div></section>
      <section className="local-explanation-section" aria-labelledby="saved-local-shap-title"><header className="local-explanation-heading"><div><h2 id="saved-local-shap-title">Локальное SHAP-объяснение</h2><p>Вклад признаков в скор модели для этого объекта.</p></div>{explanation && <div className="local-explanation-mode"><button className={mode === 'BRIEF' ? 'active' : ''} onClick={() => setMode('BRIEF')}>Кратко</button><button className={mode === 'DETAILED' ? 'active' : ''} onClick={() => setMode('DETAILED')}>Подробно</button></div>}</header>
        {!explanation && !shapError && <div className="local-explanation-loading panel" aria-busy="true"><p>Формируем локальное объяснение модели…</p></div>}
        {shapError && <div className="local-explanation-error panel" role="alert"><strong>Объяснение недоступно</strong><p>{shapError}</p><p>Скор модели и значения признаков остаются доступными.</p></div>}
        {explanation && <div className="local-explanation-content panel">{mode === 'DETAILED' && <div className="local-explanation-detailed-facts"><article><small>Базовое значение</small><strong>{exact.format(explanation.base_value)}</strong></article><article><small>Объяснённый выход</small><strong>{exact.format(explanation.explained_output_value)}</strong></article><article><small>Пространство выхода</small><strong>{explanation.output_space}</strong></article></div>}<div className="local-explanation-feature-list detailed">{visible.map(feature => <article className={`local-explanation-feature direction-${feature.direction}`} key={feature.feature_id}><div className="local-explanation-feature-main"><strong>{mode === 'DETAILED' ? `#${feature.rank} ` : ''}{feature.display_name_ru || feature.column_name}</strong><span>Значение: {exact.format(feature.raw_value)}</span></div><div className="local-explanation-feature-value"><strong>{exact.format(feature.shap_value)}</strong><span>{directionLabel(feature.direction)}</span></div></article>)}{mode === 'BRIEF' && explanation.remainder && <article className="local-explanation-feature"><strong>Остальные признаки ({explanation.remainder.feature_count})</strong><strong>{exact.format(explanation.remainder.shap_value)}</strong></article>}</div>{mode === 'DETAILED' && <details className="local-explanation-technical"><summary>Технические сведения</summary><p>{explanation.explanation_method_id} {explanation.explanation_method_version}; {explanation.explanation_provider_id} {explanation.explanation_provider_version}</p></details>}</div>}
        <p className="local-explanation-limitation">SHAP описывает вклад модели для этого объекта. Он не доказывает причинное влияние признака.</p>
      </section>
      {explanation && <section className="result-interpreter-section"><header className="result-interpreter-heading"><div><p className="eyebrow">Result Interpreter</p><h2>Интерпретация результата</h2><p>Формируется только по явному действию на основе проверенного результата модели и Local SHAP.</p></div><button className="primary-action interpreter-bulk-action" disabled={busyRoles.size !== 0 || explanation.result_interpretation_capability.state !== 'AVAILABLE'} onClick={() => void Promise.all(roles.map(([role]) => generate(role)))}>Сформировать все объяснения</button></header><div className="interpreter-safe-notice"><p>Внешняя модель вызывается только после явного запуска. Сервер применяет политику REDACTED_V1.</p></div><div className="interpreter-layout"><div className="interpreter-master" role="tablist">{roles.map(([role, label]) => <button key={role} className={`interpreter-role ${selectedRole === role ? 'active' : ''}`} onClick={() => setSelectedRole(role)}><span><strong>{label}</strong><small>{interpretations[role] ? 'Сформировано' : 'Не сформировано'}</small></span></button>)}</div><div className="interpreter-detail panel"><h3>{roles.find(([role]) => role === selectedRole)?.[1]}</h3>{explanation.result_interpretation_capability.state !== 'AVAILABLE' ? <p>Интерпретация недоступна: {explanation.result_interpretation_capability.reason_code}</p> : selected ? <><p className="interpreter-text">{selected.text}</p><p className="interpreter-created">Сформировано: {new Date(selected.created_at).toLocaleString('ru-RU')}</p><p className="interpreter-disclaimer">Текст интерпретирует проверенные evidence и SHAP; это не отдельный прогноз или автоматическое решение.</p><button className="secondary-action" onClick={() => void navigator.clipboard?.writeText(selected.text)}>Копировать</button><button className="primary-action" disabled={busyRoles.size !== 0} onClick={() => void generate(selectedRole)}>Сформировать заново</button></> : <><p>{interpretationError[selectedRole] || 'Объяснение ещё не сформировано.'}</p><button className="primary-action" disabled={busyRoles.size !== 0} onClick={() => void generate(selectedRole)}>{busyRoles.has(selectedRole) ? 'Формируем…' : interpretationError[selectedRole] ? 'Повторить' : 'Сформировать объяснение'}</button></>}</div></div></section>}
    </>}
  </main>
}
