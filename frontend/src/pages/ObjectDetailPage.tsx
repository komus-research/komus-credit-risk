import { useEffect, useState } from 'react'
import {
  getCurrentObjectDetail,
  getCurrentObjectExplanation,
  type LocalExplanation,
  type LocalExplanationDirection,
  type LocalExplanationFeature,
  type ResultObjectDetail,
} from '../api/result'
import { Sidebar } from '../components/Sidebar'

const scoreFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

function exactValue(value: number) {
  return String(value).replace('.', ',')
}

const outcomeExplanation: Record<ResultObjectDetail['outcome'], string> = {
  TP: 'Целевое событие есть, оценка выше порога.',
  TN: 'Целевого события нет, оценка ниже порога.',
  FP: 'Целевого события нет, но оценка выше порога.',
  FN: 'Целевое событие есть, но оценка ниже порога.',
}

const directionCopy: Record<LocalExplanationDirection, string> = {
  increases_output: '↑ увеличивает оценку модели',
  decreases_output: '↓ уменьшает оценку модели',
  neutral: 'не меняет оценку модели',
}

function outcomeClass(outcome: ResultObjectDetail['outcome']) {
  return `objects-outcome objects-outcome-${outcome.toLowerCase()}`
}

function targetClass(outcome: ResultObjectDetail['outcome']) {
  return `objects-target objects-target-${outcome.toLowerCase()}`
}

function featureLabel(feature: LocalExplanationFeature) {
  return feature.display_name_ru?.trim() || feature.column_name
}

function ExplanationFeatureRow({ feature, width, rank }: { feature: LocalExplanationFeature; width: number; rank?: number }) {
  return <article className={`local-explanation-feature direction-${feature.direction}`}>
    <div className="local-explanation-feature-main">
      <div className="local-explanation-feature-title">
        {rank !== undefined && <span className="local-explanation-rank">{rank}</span>}
        <strong>{featureLabel(feature)}</strong>
      </div>
      {feature.description_ru && <p className="local-explanation-description">{feature.description_ru}</p>}
      <span className="local-explanation-direction">{directionCopy[feature.direction]}</span>
    </div>
    <div className="local-explanation-feature-value">
      <span className="local-explanation-bar-track" aria-hidden="true"><span style={{ width: `${width}%` }} /></span>
      <strong>{exactValue(feature.shap_value)}</strong>
    </div>
    {rank !== undefined && <dl className="local-explanation-feature-facts">
      <div><dt>Ранг</dt><dd>{feature.abs_rank}</dd></div>
      <div><dt>Значение объекта</dt><dd>{exactValue(feature.raw_value)}</dd></div>
      <div><dt>Вклад SHAP</dt><dd>{exactValue(feature.shap_value)}</dd></div>
    </dl>}
  </article>
}

function remainderLabel(direction: LocalExplanationDirection) {
  return <span className={`local-explanation-direction direction-text-${direction}`}>{directionCopy[direction]}</span>
}

export function ObjectDetailPage({ objectId, onBack, onHome }: { objectId: string; onBack: () => void; onHome: () => void }) {
  const [detail, setDetail] = useState<ResultObjectDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [retryToken, setRetryToken] = useState(0)
  const [explanationRetryToken, setExplanationRetryToken] = useState(0)
  const [explanation, setExplanation] = useState<{ artifactId: string; objectId: string; status: 'LOADING' | 'READY' | 'ERROR'; value?: LocalExplanation; message?: string } | null>(null)
  const [modeState, setModeState] = useState<{ objectId: string; mode: 'BRIEF' | 'DETAILED' }>({ objectId, mode: 'BRIEF' })

  useEffect(() => {
    setExplanation(null)
    setModeState({ objectId, mode: 'BRIEF' })
  }, [objectId])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setLoading(true)
    setDetail(null)
    setError(null)

    void getCurrentObjectDetail(objectId, controller.signal)
      .then(value => {
        if (!active) return
        if (value.object_id !== objectId) {
          setError('Не удалось подтвердить данные выбранного объекта.')
          return
        }
        setDetail(value)
      })
      .catch(reason => {
        if (!active || controller.signal.aborted) return
        setError(reason instanceof Error ? reason.message : 'Не удалось загрузить карточку объекта.')
      })
      .finally(() => { if (active) setLoading(false) })

    return () => {
      active = false
      controller.abort()
    }
  }, [objectId, retryToken])

  const currentDetail = detail?.object_id === objectId ? detail : null
  const currentMode = modeState.objectId === objectId ? modeState.mode : 'BRIEF'

  useEffect(() => {
    if (!currentDetail || currentDetail.object_id !== objectId) return
    const expectedArtifactId = currentDetail.artifact_id
    const controller = new AbortController()
    let active = true
    setExplanation({ artifactId: expectedArtifactId, objectId, status: 'LOADING' })

    void getCurrentObjectExplanation(objectId, controller.signal)
      .then(value => {
        if (!active) return
        if (value.artifact_id !== expectedArtifactId || value.object_id !== objectId) {
          setExplanation({ artifactId: expectedArtifactId, objectId, status: 'ERROR', message: 'Не удалось подтвердить объяснение выбранного объекта.' })
          return
        }
        setExplanation({ artifactId: expectedArtifactId, objectId, status: 'READY', value })
      })
      .catch(reason => {
        if (!active || controller.signal.aborted) return
        setExplanation({ artifactId: expectedArtifactId, objectId, status: 'ERROR', message: reason instanceof Error ? reason.message : 'Не удалось построить объяснение. Сам результат объекта остаётся доступен.' })
      })

    return () => {
      active = false
      controller.abort()
    }
  }, [currentDetail?.artifact_id, currentDetail?.object_id, objectId, explanationRetryToken])

  const showLoading = loading || (!currentDetail && !error)
  const explanationIdentityMatches = Boolean(currentDetail && explanation?.artifactId === currentDetail.artifact_id && explanation?.objectId === objectId)
  const currentExplanation = explanationIdentityMatches ? explanation : null

  return <div className="app-shell features-shell"><Sidebar active="analysis" onHome={onHome} /><main className="workspace result-workspace object-detail-workspace">
    <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index < 4 ? 'completed' : 'active'}><span>{index < 4 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>
    <button className="objects-back-link" onClick={onBack}>← Назад к объектам</button>
    <header className="result-header"><p className="eyebrow">Шаг 5 из 5 · Результат</p><h1>{currentDetail ? `Объект ${currentDetail.identifier_display}` : 'Объект оценки'}</h1><p>Факты по OOF-оценке выбранного объекта.</p></header>

    {showLoading && <section className="object-detail-loading panel" aria-busy="true" aria-live="polite"><span className="object-detail-loading-mark" aria-hidden="true" /><p>Загружаем данные объекта…</p></section>}
    {!showLoading && error && <section className="object-detail-error panel" role="alert"><strong>Не удалось загрузить объект</strong><p>{error}</p><div><button className="secondary-action" onClick={() => setRetryToken(value => value + 1)}>Повторить</button><button className="secondary-action" onClick={onBack}>← Назад к объектам</button></div></section>}
    {!showLoading && !error && currentDetail && <>
      <section className="object-detail-facts panel" aria-label="Факты по объекту">
        <article className="object-detail-fact"><small>Оценка модели</small><strong>{scoreFormat.format(currentDetail.score)}</strong></article>
        <article className="object-detail-fact"><small>Диагностический порог</small><strong>{exactValue(currentDetail.threshold)}</strong><span>Порог аналитический: он не является автоматически оптимальным или рекомендованным.</span></article>
        <article className="object-detail-fact"><small>Целевое событие</small><strong className={targetClass(currentDetail.outcome)}><b aria-hidden="true">{currentDetail.y_true === 1 ? '●' : '○'}</b>{currentDetail.y_true === 1 ? 'Да' : 'Нет'}</strong></article>
        <article className="object-detail-fact"><small>Относительно порога</small><strong className="object-detail-position">{currentDetail.predicted_positive ? '↑ Выше порога' : '↓ Ниже порога'}</strong></article>
        <article className="object-detail-fact"><small>Результат</small><strong className="object-detail-outcome"><span className={outcomeClass(currentDetail.outcome)}>{currentDetail.outcome}</span><span>{outcomeExplanation[currentDetail.outcome]}</span></strong></article>
        <article className="object-detail-fact"><small>Источник оценки</small><strong>OOF</strong><span>Fold {currentDetail.fold_number}</span></article>
      </section>

      <section className="object-detail-explanation panel" aria-label="Пояснение результата"><span className="object-detail-info" aria-hidden="true">i</span><p>{outcomeExplanation[currentDetail.outcome]}</p></section>

      <section className="object-detail-fold panel"><div><small>Fold {currentDetail.fold_number}</small><strong>Происхождение OOF-оценки</strong></div><p>Fold — часть перекрёстной проверки, на которой получена OOF-оценка объекта. Модель, сформировавшая эту оценку, обучалась на других folds и не использовала этот объект при обучении. Fold доступен только для чтения.</p></section>

      <section className="local-explanation-section" aria-labelledby="local-explanation-title">
        <header className="local-explanation-heading">
          <div><h2 id="local-explanation-title">Как признаки сдвигали оценку модели</h2><p>Локальное SHAP-объяснение сохранённой OOF-оценки этого объекта.</p></div>
          {currentExplanation?.status === 'READY' && <div className="local-explanation-mode" role="group" aria-label="Режим объяснения">
            <button type="button" className={currentMode === 'BRIEF' ? 'active' : ''} aria-pressed={currentMode === 'BRIEF'} onClick={() => setModeState({ objectId, mode: 'BRIEF' })}>Кратко</button>
            <button type="button" className={currentMode === 'DETAILED' ? 'active' : ''} aria-pressed={currentMode === 'DETAILED'} onClick={() => setModeState({ objectId, mode: 'DETAILED' })}>Подробно</button>
          </div>}
        </header>
        {(!currentExplanation || currentExplanation.status === 'LOADING') && <div className="local-explanation-loading panel" aria-busy="true" aria-live="polite"><span className="object-detail-loading-mark" aria-hidden="true" /><p>Формируем локальное объяснение модели…</p></div>}
        {currentExplanation?.status === 'ERROR' && <div className="local-explanation-error panel" role="alert"><span className="local-explanation-error-mark" aria-hidden="true">!</span><div><strong>Объяснение недоступно</strong><p>{currentExplanation.message}</p><p>Оценка модели и данные объекта остаются доступными.</p><button className="secondary-action" onClick={() => setExplanationRetryToken(value => value + 1)}>Повторить</button></div></div>}
        {currentExplanation?.status === 'READY' && currentExplanation.value && <ExplanationReady explanation={currentExplanation.value} mode={currentMode} />}
        <p className="local-explanation-limitation">Вклад SHAP описывает поведение модели для этого объекта и не доказывает причинное влияние признака.</p>
      </section>
    </>}
  </main></div>
}

function ExplanationReady({ explanation, mode }: { explanation: LocalExplanation; mode: 'BRIEF' | 'DETAILED' }) {
  const visibleFeatures = mode === 'BRIEF' ? explanation.features.slice(0, 5) : explanation.features
  const barValues = [...visibleFeatures.map(feature => Math.abs(feature.shap_value)), ...(mode === 'BRIEF' && explanation.remainder ? [Math.abs(explanation.remainder.shap_value)] : [])]
  const maxMagnitude = Math.max(0, ...barValues)
  const barWidth = (value: number) => maxMagnitude === 0 ? 0 : Math.max(3, Math.abs(value) / maxMagnitude * 100)
  const rawMargin = explanation.output_space === 'raw_margin'

  return <div className="local-explanation-content panel">
    {mode === 'BRIEF' ? <>
      <div className="local-explanation-summary-facts">
        <div><small>OOF-оценка модели</small><strong>{exactValue(explanation.prediction_probability)}</strong></div>
        <div><small>Пространство объяснения</small><strong>{explanation.output_space}</strong></div>
      </div>
      <div className="local-explanation-feature-list">
        {visibleFeatures.map(feature => <ExplanationFeatureRow key={feature.feature_id} feature={feature} width={barWidth(feature.shap_value)} />)}
        {explanation.remainder && <article className={`local-explanation-feature direction-${explanation.remainder.direction}`}>
          <div className="local-explanation-feature-main"><strong>Остальные признаки</strong><span className="local-explanation-remainder-count">{explanation.remainder.feature_count} признаков</span>{remainderLabel(explanation.remainder.direction)}</div>
          <div className="local-explanation-feature-value"><span className="local-explanation-bar-track" aria-hidden="true"><span style={{ width: `${barWidth(explanation.remainder.shap_value)}%` }} /></span><strong>{exactValue(explanation.remainder.shap_value)}</strong></div>
        </article>}
      </div>
    </> : <>
      <div className="local-explanation-detailed-facts">
        <article><small>Начальная оценка модели</small><strong>{exactValue(explanation.base_value)}</strong><p>Начальная оценка — референсная точка SHAP. Вклады признаков конкретного объекта увеличивают или уменьшают её и формируют объяснённый выход модели.</p></article>
        <article><small>Объяснённый выход модели</small><strong>{exactValue(explanation.explained_output_value)}</strong>{rawMargin && <span>Значение в пространстве raw margin.</span>}</article>
        <article><small>Пространство объяснения</small><strong>{explanation.output_space}</strong></article>
        <article><small>OOF-оценка модели</small><strong>{exactValue(explanation.prediction_probability)}</strong></article>
      </div>
      {rawMargin && <p className="local-explanation-space-note">Начальная оценка, объяснённый выход и вклады SHAP указаны в пространстве raw margin.</p>}
      <h3 className="local-explanation-list-title">Все признаки ({explanation.features.length})</h3>
      <div className="local-explanation-feature-list detailed">
        {explanation.features.map(feature => <ExplanationFeatureRow key={feature.feature_id} feature={feature} width={barWidth(feature.shap_value)} rank={feature.abs_rank} />)}
      </div>
      <details className="local-explanation-technical"><summary>Технические сведения</summary><dl>
        <dt>Метод объяснения</dt><dd>{explanation.explanation_method_id}</dd><dt>Версия метода</dt><dd>{explanation.explanation_method_version}</dd>
        <dt>Провайдер объяснения</dt><dd>{explanation.explanation_provider_id}</dd><dt>Версия провайдера</dt><dd>{explanation.explanation_provider_version}</dd>
        <dt>Версия evidence</dt><dd>{explanation.evidence_version}</dd><dt>Хеш evidence</dt><dd>{explanation.evidence_hash}</dd>
      </dl></details>
    </>}
  </div>
}
