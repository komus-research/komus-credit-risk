import { useEffect, useState } from 'react'
import { getQuality, NativeApiError, patchQualitySettings, runQualityPreflight, runQualityTraining, type QualityState } from '../api/session'
import { Sidebar } from '../components/Sidebar'
import { navigate, routes } from '../routing'

export function QualityPage({ onHome }: { onHome: () => void }) {
  const [data, setData] = useState<QualityState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const trainingRunning = data?.training.status === 'RUNNING'
  const operationBusy = busy || trainingRunning
  const [foldsDraft, setFoldsDraft] = useState('')
  const [seedDraft, setSeedDraft] = useState('')
  const parseInteger = (value: string): number | null => /^-?\d+$/.test(value.trim()) && Number.isSafeInteger(Number(value)) ? Number(value) : null
  const parsedFolds = parseInteger(foldsDraft)
  const parsedSeed = parseInteger(seedDraft)
  const draftChanged = Boolean(data && (parsedFolds === null || parsedSeed === null || parsedFolds !== data.settings.folds || parsedSeed !== data.settings.seed))
  const draftValid = parsedFolds !== null && parsedSeed !== null && Boolean(data && parsedFolds >= data.supported_protocol.minimum_folds)

  const preflight = (cancelled: () => boolean = () => false) => {
    setBusy(true)
    setError(null)
    setData(current => current ? { ...current, preflight: { ...current.preflight, status: 'RUNNING', identity: null, failure_code: null, message: 'Выполняем предварительную проверку…' }, can_start_training: false } : current)
    void runQualityPreflight().then(value => !cancelled() && setData(value)).catch(reason => !cancelled() && setError(reason instanceof Error ? reason.message : 'Не удалось выполнить предварительную проверку.')).finally(() => !cancelled() && setBusy(false))
  }

  useEffect(() => {
    let cancelled = false
    void getQuality().then(next => {
      if (cancelled) return
      setData(next)
      setFoldsDraft(String(next.settings.folds))
      setSeedDraft(String(next.settings.seed))
      if (next.preflight.status !== 'PASS' && next.preflight.status !== 'RUNNING') preflight(() => cancelled)
    }).catch(reason => !cancelled && setError(reason instanceof Error ? reason.message : 'Не удалось загрузить проверку.'))
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!trainingRunning) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    const poll = () => {
      timer = setTimeout(() => {
        void getQuality().then(next => {
          if (cancelled) return
          setData(next)
          if (next.training.status === 'RUNNING') poll()
        }).catch(reason => {
          if (!cancelled) setError(reason instanceof Error ? reason.message : 'Не удалось обновить ход обучения.')
          if (!cancelled) poll()
        })
      }, 1000)
    }
    poll()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [trainingRunning])

  const applySettings = () => {
    if (!data || !draftValid || parsedFolds === null || parsedSeed === null || !draftChanged || operationBusy) return
    setBusy(true); setError(null)
    void patchQualitySettings({ folds: parsedFolds, seed: parsedSeed }).then(next => {
      setData(next)
      setFoldsDraft(String(next.settings.folds))
      setSeedDraft(String(next.settings.seed))
      setData(current => current ? { ...current, preflight: { ...current.preflight, status: 'RUNNING', identity: null, failure_code: null, message: 'Выполняем предварительную проверку…' }, can_start_training: false } : current)
      return runQualityPreflight()
    }).then(setData).catch(reason => setError(reason instanceof NativeApiError ? reason.message : reason instanceof Error ? reason.message : 'Не удалось сохранить настройки.')).finally(() => setBusy(false))
  }
  const startTraining = () => {
    if (!data?.can_start_training || operationBusy) return
    setError(null)
    setData(current => current ? { ...current, training: { ...current.training, status: 'RUNNING', stage: null, stage_label: null, fold_number: null, folds_total: null, artifact_id: null, failure_code: null, message: 'Отправляем запрос на запуск обучения.' }, can_start_training: false } : current)
    void runQualityTraining().then(setData).catch(reason => {
      setError(reason instanceof NativeApiError ? reason.message : reason instanceof Error ? reason.message : 'Не удалось запустить обучение.')
      void getQuality().then(setData).catch(() => undefined)
    })
  }
  const steps = ['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат']
  const checks: Array<[string, string]> = [
    ['Данные готовы', 'Подтверждённый набор данных доступен для запуска.'], ['Выбранные признаки корректны', 'Выбранный набор признаков доступен алгоритму.'], ['Алгоритм доступен', 'Алгоритм и необходимые компоненты доступны.'], ['Настройки совместимы', 'Конфигурация успешно проверена.'], ['Пробное обучение выполнено', 'Модель успешно обучилась на небольшой контрольной выборке.'], ['Пробный прогноз получен', 'Прогнозы получены в корректном формате.'],
  ]
  const passed = data?.preflight.status === 'PASS'
  return <div className="app-shell features-shell"><Sidebar active="analysis" onHome={onHome} /><main className="workspace quality-workspace">
    <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{steps.map((name, index) => <li key={name} className={index < 3 ? 'completed' : index === 3 ? 'active' : ''}><span>{index < 3 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>
    <header className="quality-header"><p className="eyebrow">Шаг 4 из 5</p><h1>Проверка перед запуском</h1><p>Проверьте выбранную конфигурацию. AXION автоматически убедится, что всё готово к обучению.</p></header>
    {error && <p className="feature-warning">{error}</p>}
    {!data && !error && <p className="feature-loading">Загружаем конфигурацию…</p>}
    {data && <>
      <section className="quality-summary panel"><h2>Что будет использовано</h2><div className="quality-summary-grid">
        <article><span>▧</span><div><small>Данные</small><strong>{data.summary.dataset_name}</strong><em>{data.summary.population_size.toLocaleString('ru-RU')} строк</em></div></article>
        <article><span>▥</span><div><small>Признаки</small><strong>{data.summary.selected_feature_count} выбрано</strong></div><button className="text-action" disabled={operationBusy} onClick={() => navigate(routes.features)}>Изменить</button></article>
        <article><span>◇</span><div><small>Алгоритм</small><strong>{data.summary.selected_model_display_name_ru}</strong></div><button className="text-action" disabled={operationBusy} onClick={() => navigate(routes.algorithm)}>Изменить</button></article>
        <article><span>⚙</span><div><small>Настройки алгоритма</small><strong>{data.summary.configuration_mode === 'ADVANCED' ? 'Расширенные' : 'Рекомендуемые'}</strong></div><button className="text-action" disabled={operationBusy} onClick={() => navigate(routes.algorithm)}>Изменить</button></article>
      </div></section>
      <section className={`quality-preflight panel ${passed ? 'passed' : ''}`}><div className="quality-title"><div><h2>Проверка перед запуском</h2><p>AXION автоматически проверяет совместимость данных, признаков и алгоритма и выполняет небольшой пробный запуск.</p></div><span className={passed ? 'quality-pass-label' : 'quality-pending-label'}>{passed ? '✓ Предварительная проверка завершена' : data.preflight.status === 'RUNNING' || busy ? '◌ Выполняем предварительную проверку…' : data.preflight.message ?? data.plan.safe_validation_state}</span></div>
        {passed && <div className="quality-checks">{checks.map(([name, description]) => <div key={name}><b>✓</b><strong>{name}</strong><span>{description}</span></div>)}</div>}
        {!passed && <div className="quality-waiting">{data.preflight.status === 'FAIL' ? <>{data.preflight.message}<button className="secondary-action" disabled={operationBusy} onClick={() => preflight()}>Повторить проверку</button></> : 'Выполняем предварительную проверку…'}</div>}
        {passed && <div className="quality-success"><b>✓</b><div><h2>Готово к запуску</h2><p>Предварительная проверка подтверждает техническую готовность конфигурации.</p><p>Качество модели будет рассчитано во время полноценной проверки.</p><p>После обучения AXION автоматически рассчитает метрики качества.</p></div></div>}
      </section>
      {trainingRunning && <section className="quality-success panel" aria-live="polite"><b>◌</b><div><h2>{data.training.stage_label ?? 'Выполняется обучение'}</h2><p>{data.training.message}</p>{data.training.fold_number !== null && data.training.folds_total !== null && <p>Часть {data.training.fold_number} из {data.training.folds_total}</p>}</div></section>}
      {data.training.status === 'FAIL' && <p className="feature-warning" role="alert">{data.training.message}</p>}
      {data.training.status === 'COMPLETED' && <section className="quality-success panel"><b>✓</b><div><h2>Обучение завершено</h2><p>Обучение и проверка качества завершены. Результат сохранён.</p></div></section>}
      <details className="quality-details panel"><summary><span>⚙</span><div><strong>Дополнительные настройки</strong><small>Рекомендуемые параметры уже выбраны автоматически.</small></div></summary><div className="quality-settings"><label>Количество частей проверки<input type="text" inputMode="numeric" value={foldsDraft} disabled={operationBusy} onChange={e => setFoldsDraft(e.target.value)} /></label><label>Seed<input type="text" inputMode="numeric" value={seedDraft} disabled={operationBusy} onChange={e => setSeedDraft(e.target.value)} /></label><button className="secondary-action" disabled={operationBusy || !draftChanged || !draftValid} onClick={applySettings}>Применить настройки</button><p>Протокол: {data.supported_protocol.protocol_id} v{data.supported_protocol.protocol_version}</p></div>{draftChanged && !draftValid && <p className="quality-validation">Введите целые числа; число частей проверки должно быть не меньше {data.supported_protocol.minimum_folds}.</p>}</details>
      <details className="quality-details panel"><summary><span>▧</span><div><strong>Технические сведения</strong><small>Информация о протоколе проверки, используемых данных и других технических деталях.</small></div></summary><dl><div><dt>Protocol</dt><dd>{data.supported_protocol.protocol_id} v{data.supported_protocol.protocol_version}</dd></div><div><dt>Folds / seed</dt><dd>{data.settings.folds} / {data.settings.seed}</dd></div><div><dt>Model</dt><dd>{data.summary.selected_model_id}</dd></div><div><dt>Plan / smoke</dt><dd>{data.plan.status} / {data.preflight.status}</dd></div>{data.preflight.identity && <div><dt>Smoke identity</dt><dd>{data.preflight.identity}</dd></div>}{data.training.artifact_id && <div><dt>Artifact ID</dt><dd>{data.training.artifact_id}</dd></div>}</dl></details>
      <footer className="quality-footer"><button className="secondary-action" disabled={operationBusy} onClick={() => navigate(routes.algorithm)}>← Назад к алгоритму</button><div>{data.training.status === 'COMPLETED' && <button className="primary-action" onClick={() => navigate(routes.result)}>Открыть результат →</button>}<button className="primary-action" disabled={!data.can_start_training || operationBusy} onClick={startTraining}>{trainingRunning ? 'Обучение выполняется…' : data.training.status === 'COMPLETED' ? 'Обучение завершено' : 'Начать обучение →'}</button></div></footer>
    </>}
  </main></div>
}
