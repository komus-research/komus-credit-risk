import { useEffect, useState } from 'react'
import { getCurrentObjectDetail, type ResultObjectDetail } from '../api/result'
import { Sidebar } from '../components/Sidebar'

const scoreFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })

function exactThreshold(value: number) {
  return String(value).replace('.', ',')
}

const outcomeExplanation: Record<ResultObjectDetail['outcome'], string> = {
  TP: 'Целевое событие есть, оценка выше порога.',
  TN: 'Целевого события нет, оценка ниже порога.',
  FP: 'Целевого события нет, но оценка выше порога.',
  FN: 'Целевое событие есть, но оценка ниже порога.',
}

function outcomeClass(outcome: ResultObjectDetail['outcome']) {
  return `objects-outcome objects-outcome-${outcome.toLowerCase()}`
}

function targetClass(outcome: ResultObjectDetail['outcome']) {
  return `objects-target objects-target-${outcome.toLowerCase()}`
}

export function ObjectDetailPage({ objectId, onBack, onHome }: { objectId: string; onBack: () => void; onHome: () => void }) {
  const [detail, setDetail] = useState<ResultObjectDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [retryToken, setRetryToken] = useState(0)

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
  const showLoading = loading || (!currentDetail && !error)

  return <div className="app-shell features-shell"><Sidebar active="analysis" onHome={onHome} /><main className="workspace result-workspace object-detail-workspace">
    <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index < 4 ? 'completed' : 'active'}><span>{index < 4 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>
    <button className="objects-back-link" onClick={onBack}>← Назад к объектам</button>
    <header className="result-header"><p className="eyebrow">Шаг 5 из 5 · Результат</p><h1>{currentDetail ? `Объект ${currentDetail.identifier_display}` : 'Объект оценки'}</h1><p>Факты по OOF-оценке выбранного объекта.</p></header>

    {showLoading && <section className="object-detail-loading panel" aria-busy="true" aria-live="polite"><span className="object-detail-loading-mark" aria-hidden="true" /><p>Загружаем данные объекта…</p></section>}
    {!showLoading && error && <section className="object-detail-error panel" role="alert"><strong>Не удалось загрузить объект</strong><p>{error}</p><div><button className="secondary-action" onClick={() => setRetryToken(value => value + 1)}>Повторить</button><button className="secondary-action" onClick={onBack}>← Назад к объектам</button></div></section>}
    {!showLoading && !error && currentDetail && <>
      <section className="object-detail-facts panel" aria-label="Факты по объекту">
        <article className="object-detail-fact"><small>Оценка модели</small><strong>{scoreFormat.format(currentDetail.score)}</strong></article>
        <article className="object-detail-fact"><small>Диагностический порог</small><strong>{exactThreshold(currentDetail.threshold)}</strong><span>Порог аналитический: он не является автоматически оптимальным или рекомендованным.</span></article>
        <article className="object-detail-fact"><small>Целевое событие</small><strong className={targetClass(currentDetail.outcome)}><b aria-hidden="true">{currentDetail.y_true === 1 ? '●' : '○'}</b>{currentDetail.y_true === 1 ? 'Да' : 'Нет'}</strong></article>
        <article className="object-detail-fact"><small>Относительно порога</small><strong className="object-detail-position">{currentDetail.predicted_positive ? '↑ Выше порога' : '↓ Ниже порога'}</strong></article>
        <article className="object-detail-fact"><small>Результат</small><strong className="object-detail-outcome"><span className={outcomeClass(currentDetail.outcome)}>{currentDetail.outcome}</span><span>{outcomeExplanation[currentDetail.outcome]}</span></strong></article>
        <article className="object-detail-fact"><small>Источник оценки</small><strong>OOF</strong><span>Fold {currentDetail.fold_number}</span></article>
      </section>

      <section className="object-detail-explanation panel" aria-label="Пояснение результата"><span className="object-detail-info" aria-hidden="true">i</span><p>{outcomeExplanation[currentDetail.outcome]}</p></section>

      <section className="object-detail-fold panel"><div><small>Fold {currentDetail.fold_number}</small><strong>Происхождение OOF-оценки</strong></div><p>Fold — часть перекрёстной проверки, на которой получена OOF-оценка объекта. Модель, сформировавшая эту оценку, обучалась на других folds и не использовала этот объект при обучении. Fold доступен только для чтения.</p></section>
    </>}
  </main></div>
}
