import { useEffect, useRef, useState } from 'react'
import {
  createCurrentGlobalResultInterpretation,
  getCurrentGlobalOOFExplanation,
  getCurrentGlobalOOFStatus,
  getCurrentResult,
  GlobalOOFAPIError,
  saveCurrentResultModel,
  type GlobalOOFOperation,
  runCurrentGlobalOOF,
  type GlobalOOFExplanation,
  type GlobalResultInterpretation,
  type ResultCapture,
  type ResultInterpreterRole,
  type ResultOverview,
} from '../api/result'
import { Icon } from '../components/Icon'
import { navigate, routes } from '../routing'

const numberFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 })
const percentFormat = new Intl.NumberFormat('ru-RU', { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 })
const integerFormat = new Intl.NumberFormat('ru-RU')
const thresholdFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const unavailable = 'Действие пока недоступно: соответствующая возможность не подключена.'

function metric(value: number) { return numberFormat.format(value) }
function percent(value: number) { return percentFormat.format(value) }
function errorRate(numerator: number, denominator: number) { return denominator === 0 ? '—' : percent(numerator / denominator) }

type GlobalPreviewStatus = 'idle' | 'loading' | 'running' | 'ready' | 'changed' | 'error'
type ModelSaveStatus = 'NOT_SAVED' | 'SAVING' | 'SAVED' | 'ERROR'

const globalInterpreterRoles: Array<{ id: ResultInterpreterRole; name: string; purpose: string }> = [
  { id: 'sales_manager', name: 'Менеджер по продажам', purpose: 'Бизнес-интерпретация качества модели и ошибок' },
  { id: 'credit_controller', name: 'Кредитный контролёр', purpose: 'Разбор качества, порога, ошибок и стабильности' },
  { id: 'lawyer', name: 'Юрист', purpose: 'Нейтральное объяснение ограничений и применения модели' },
  { id: 'information_security', name: 'Информационная безопасность', purpose: 'Фокус на данных, признаках и рисках использования' },
]

type GlobalInterpretationStatus = 'IDLE' | 'LOADING' | 'READY' | 'ERROR'
type GlobalInterpretationState = {
  status: GlobalInterpretationStatus
  response?: GlobalResultInterpretation
  message?: string
  refreshing?: boolean
}
type GlobalInterpretationStates = Record<ResultInterpreterRole, GlobalInterpretationState>

function createGlobalInterpretationStates(): GlobalInterpretationStates {
  return Object.fromEntries(globalInterpreterRoles.map(({ id }) => [id, { status: 'IDLE' }])) as GlobalInterpretationStates
}

function globalInterpretationStatusCopy(state: GlobalInterpretationState) {
  if (state.refreshing) return 'Обновление'
  return ({ IDLE: 'Не сформировано', LOADING: 'Формирование', READY: 'Готово', ERROR: 'Ошибка' } as const)[state.status]
}

function globalInterpretationCreatedAt(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function GlobalResultInterpreterPanel({ globalStatus, artifactId }: { globalStatus: GlobalPreviewStatus; artifactId: string }) {
  const [selectedRole, setSelectedRole] = useState<ResultInterpreterRole>('sales_manager')
  const [interpretations, setInterpretations] = useState<GlobalInterpretationStates>(createGlobalInterpretationStates)
  const [copiedRole, setCopiedRole] = useState<ResultInterpreterRole | null>(null)
  const controllers = useRef<Partial<Record<ResultInterpreterRole, AbortController>>>({})
  const copyTimer = useRef<number | null>(null)
  const activeArtifactId = useRef(artifactId)
  activeArtifactId.current = artifactId
  const evidenceReady = globalStatus === 'ready'
  const selected = globalInterpreterRoles.find(role => role.id === selectedRole)!
  const selectedInterpretation = interpretations[selectedRole]

  useEffect(() => {
    setSelectedRole('sales_manager')
    setInterpretations(createGlobalInterpretationStates())
    setCopiedRole(null)
    Object.values(controllers.current).forEach(controller => controller?.abort())
    controllers.current = {}
  }, [artifactId])

  useEffect(() => () => {
    Object.values(controllers.current).forEach(controller => controller?.abort())
    if (copyTimer.current !== null) window.clearTimeout(copyTimer.current)
  }, [])

  function updateInterpretation(role: ResultInterpreterRole, next: GlobalInterpretationState) {
    setInterpretations(current => ({ ...current, [role]: next }))
  }

  function generateInterpretation(role: ResultInterpreterRole) {
    const prior = interpretations[role]
    if (!evidenceReady || prior.status === 'LOADING' || prior.refreshing || controllers.current[role]) return
    const controller = new AbortController()
    controllers.current[role] = controller
    const regenerating = prior.status === 'READY' && Boolean(prior.response)
    updateInterpretation(role, regenerating
      ? { ...prior, refreshing: true, message: undefined }
      : { status: 'LOADING' })

    void createCurrentGlobalResultInterpretation(role, controller.signal)
      .then(response => {
        if (controller.signal.aborted || activeArtifactId.current !== artifactId) return
        if (response.artifact_id !== artifactId || response.role !== role) {
          const message = 'Текущий результат изменился. Сформируйте объяснение заново.'
          updateInterpretation(role, regenerating ? { ...prior, refreshing: false, message } : { status: 'ERROR', message })
          return
        }
        updateInterpretation(role, { status: 'READY', response })
      })
      .catch(reason => {
        if (controller.signal.aborted || activeArtifactId.current !== artifactId || (reason instanceof Error && reason.name === 'AbortError')) return
        const message = reason instanceof Error ? reason.message : 'Не удалось сформировать интерпретацию общего результата.'
        updateInterpretation(role, regenerating ? { ...prior, refreshing: false, message } : { status: 'ERROR', message })
      })
      .finally(() => {
        if (controllers.current[role] === controller) delete controllers.current[role]
      })
  }

  function generateAllInterpretations() {
    globalInterpreterRoles.forEach(({ id }) => {
      const state = interpretations[id]
      if (state.status === 'IDLE' || state.status === 'ERROR') generateInterpretation(id)
    })
  }

  function copyInterpretation(role: ResultInterpreterRole, text: string) {
    void navigator.clipboard.writeText(text).then(() => {
      setCopiedRole(role)
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current)
      copyTimer.current = window.setTimeout(() => setCopiedRole(current => current === role ? null : current), 1800)
    }).catch(() => undefined)
  }

  const hasBulkTargets = globalInterpreterRoles.some(({ id }) => {
    const state = interpretations[id]
    return state.status === 'IDLE' || state.status === 'ERROR'
  })

  return <section className="result-interpreter-section result-global-interpreter" aria-labelledby="global-result-interpreter-title">
    <header className="result-interpreter-heading">
      <div>
        <p className="eyebrow">Result Interpreter</p>
        <h2 id="global-result-interpreter-title">Интерпретация общего результата</h2>
        <p>Объяснение всего обучения модели: качество OOF, ошибки, порог, стабильность и агрегированное влияние признаков.</p>
      </div>
      <button type="button" className="primary-action interpreter-bulk-action" onClick={generateAllInterpretations} disabled={!evidenceReady || !hasBulkTargets}>Сформировать все объяснения</button>
    </header>
    <div className="interpreter-safe-notice">
      <span aria-hidden="true">i</span>
      <p>В LLM передаётся только подготовленный сервером набор подтверждённых агрегированных фактов. Данные отдельных компаний, идентификаторы и локальные SHAP-объяснения в этот общий анализ не входят.</p>
    </div>
    <div className="interpreter-layout">
      <div className="interpreter-master" role="tablist" aria-label="Роли интерпретации общего результата">
        {globalInterpreterRoles.map(role => {
          const state = interpretations[role.id]
          const active = role.id === selectedRole
          return <button type="button" key={role.id} role="tab" aria-selected={active} className={`interpreter-role ${active ? 'active' : ''}`} onClick={() => setSelectedRole(role.id)}>
            <span className={`interpreter-role-status status-${state.status.toLowerCase()}`} aria-hidden="true" />
            <span><strong>{role.name}</strong><small>{role.purpose}</small></span>
            <em>{globalInterpretationStatusCopy(state)}</em>
          </button>
        })}
      </div>
      <div className="interpreter-detail panel" role="tabpanel">
        <div className="interpreter-detail-heading">
          <div><small>Роль</small><h3>{selected.name}</h3></div>
          <span className={`interpreter-status-badge status-${selectedInterpretation.status.toLowerCase()}`}>{globalInterpretationStatusCopy(selectedInterpretation)}</span>
        </div>
        {!evidenceReady && <div className="interpreter-empty"><p>Сначала должен быть готов агрегированный OOF / SHAP-контекст модели.</p></div>}
        {evidenceReady && selectedInterpretation.status === 'IDLE' && <div className="interpreter-empty"><p>Объяснение ещё не сформировано.</p><button type="button" className="primary-action" onClick={() => generateInterpretation(selectedRole)}>Сформировать объяснение</button></div>}
        {evidenceReady && selectedInterpretation.status === 'LOADING' && <div className="interpreter-progress" aria-busy="true" aria-live="polite"><span className="object-detail-loading-mark" aria-hidden="true" /><p>Формируем объяснение общего результата для выбранной роли…</p></div>}
        {evidenceReady && selectedInterpretation.status === 'ERROR' && <div className="interpreter-error" role="alert"><p>{selectedInterpretation.message}</p><button type="button" className="secondary-action" onClick={() => generateInterpretation(selectedRole)}>Повторить</button></div>}
        {evidenceReady && selectedInterpretation.status === 'READY' && selectedInterpretation.response && <div className="interpreter-ready">
          {selectedInterpretation.refreshing && <div className="interpreter-refreshing" aria-live="polite"><span className="object-detail-loading-mark" aria-hidden="true" />Обновляем объяснение…</div>}
          {selectedInterpretation.message && <p className="interpreter-action-error" role="alert">{selectedInterpretation.message}</p>}
          <p className="interpreter-text">{selectedInterpretation.response.text}</p>
          <p className="interpreter-created">Сформировано: {globalInterpretationCreatedAt(selectedInterpretation.response.created_at)}</p>
          <p className="interpreter-disclaimer">LLM объясняет подтверждённые OOF-метрики и агрегированный SHAP. Она не является кредитным предиктором, не выбирает бизнес-порог и не доказывает причинность или временную стабильность.</p>
          <div className="interpreter-actions">
            <button type="button" className="primary-action" onClick={() => generateInterpretation(selectedRole)} disabled={selectedInterpretation.refreshing}>Сформировать заново</button>
            <button type="button" className="secondary-action" onClick={() => copyInterpretation(selectedRole, selectedInterpretation.response!.text)}>{copiedRole === selectedRole ? 'Скопировано' : 'Копировать'}</button>
          </div>
        </div>}
      </div>
    </div>
  </section>
}

function waitForGlobalOOFPoll(signal: AbortSignal) {
  return new Promise<void>(resolve => {
    const finish = () => {
      window.clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }
    const timer = window.setTimeout(finish, 1000)
    signal.addEventListener('abort', finish, { once: true })
  })
}

export function ResultPage({ onOpenThreshold, onOpenObjects }: { onOpenThreshold: () => void; onOpenObjects: () => void }) {
  const [result, setResult] = useState<ResultOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [modelSaveStatus, setModelSaveStatus] = useState<ModelSaveStatus>('NOT_SAVED')
  const [modelSaveError, setModelSaveError] = useState<string | null>(null)
  const [modelNameDialogOpen, setModelNameDialogOpen] = useState(false)
  const [modelName, setModelName] = useState('')
  const [globalPreview, setGlobalPreview] = useState<GlobalOOFExplanation | null>(null)
  const [globalPreviewStatus, setGlobalPreviewStatus] = useState<GlobalPreviewStatus>('idle')

  useEffect(() => {
    let cancelled = false
    void getCurrentResult()
      .then(value => {
        if (cancelled) return
        setResult(value)
        setModelSaveStatus(value.saved_model ? 'SAVED' : 'NOT_SAVED')
      })
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить результат обучения.') })
    return () => { cancelled = true }
  }, [])

  const saveModel = async () => {
    if (!result || result.saved_model || modelSaveStatus === 'SAVING') return
    setModelSaveStatus('SAVING')
    setModelSaveError(null)
    try {
      const savedModel = await saveCurrentResultModel(modelName.trim() || undefined)
      setResult(current => current ? {
        ...current,
        saved_model: {
          model_version_id: savedModel.model_version_id,
          display_name: savedModel.display_name,
          display_version: savedModel.display_version,
          saved_at: savedModel.saved_at,
          decision_threshold: savedModel.decision_threshold,
          decision_threshold_state: savedModel.decision_threshold_state,
        },
      } : current)
      setModelSaveStatus('SAVED')
      setModelNameDialogOpen(false)
    } catch (reason) {
      setModelSaveStatus('ERROR')
      setModelSaveError(reason instanceof Error ? reason.message : 'Не удалось сохранить модель.')
    }
  }

  const openModelSaveDialog = () => {
    if (!result || modelIsSaved) return
    setModelName(result.saved_model?.display_name ?? result.summary.model_id)
    setModelSaveError(null); setModelNameDialogOpen(true)
  }

  const summary = result?.summary
  const threshold = result?.threshold
  const capture = result?.capture
  const savedModel = result?.saved_model
  const modelIsSaved = Boolean(savedModel)
  const saveButtonLabelBase = modelSaveStatus === 'SAVING'
    ? 'Сохраняем модель…'
    : modelIsSaved ? 'Модель сохранена' : 'Сохранить модель'
  const saveButtonLabel = saveButtonLabelBase
  const saveButtonTitle = modelIsSaved && savedModel
    ? `Сохранено: ${savedModel.display_name} — ${savedModel.display_version}`
    : undefined

  useEffect(() => {
    const artifactId = result?.summary.artifact_id
    if (!artifactId) return
    const controller = new AbortController()
    const { signal } = controller
    let lifecycleComplete = false
    setGlobalPreview(null)
    setGlobalPreviewStatus('loading')

    const loadExplanation = async () => {
      const explanation = await getCurrentGlobalOOFExplanation(signal)
      if (signal.aborted) return
      if (explanation.artifact_id !== artifactId) {
        lifecycleComplete = true
        setGlobalPreviewStatus('changed')
        return
      }
      lifecycleComplete = true
      setGlobalPreview(explanation)
      setGlobalPreviewStatus('ready')
    }

    const runLifecycle = async () => {
      try {
        await loadExplanation()
        if (signal.aborted || lifecycleComplete) return
      } catch (reason) {
        if (signal.aborted) return
        if (reason instanceof GlobalOOFAPIError && reason.code === 'RESULT_CHANGED') {
          setGlobalPreviewStatus('changed')
          return
        }
        if (!(reason instanceof GlobalOOFAPIError) || reason.code !== 'GLOBAL_OOF_RESULT_NOT_READY') {
          setGlobalPreviewStatus('error')
          return
        }
      }

      let operation: GlobalOOFOperation
      try {
        operation = await runCurrentGlobalOOF(false, signal)
        if (signal.aborted) return
        if (operation.artifact_id !== artifactId) {
          setGlobalPreviewStatus('changed')
          return
        }
        setGlobalPreviewStatus(operation.status === 'FAILED' ? 'error' : operation.status === 'READY' ? 'loading' : 'running')
        while (operation.status === 'NOT_STARTED' || operation.status === 'RUNNING') {
          await waitForGlobalOOFPoll(signal)
          if (signal.aborted) return
          operation = await getCurrentGlobalOOFStatus(signal)
          if (signal.aborted) return
          if (operation.artifact_id !== artifactId) {
            setGlobalPreviewStatus('changed')
            return
          }
          if (operation.status === 'RUNNING' || operation.status === 'NOT_STARTED') setGlobalPreviewStatus('running')
        }
        if (operation.status === 'FAILED') {
          setGlobalPreviewStatus('error')
          return
        }
        await loadExplanation()
      } catch (reason) {
        if (signal.aborted) return
        if (reason instanceof GlobalOOFAPIError && reason.code === 'RESULT_CHANGED') setGlobalPreviewStatus('changed')
        else setGlobalPreviewStatus('error')
      }
    }

    void runLifecycle()
    return () => controller.abort()
  }, [result?.summary.artifact_id])

  const foldMetrics = summary?.fold_metrics.filter(fold =>
    Number.isFinite(fold.fold) && Number.isFinite(fold.roc_auc),
  ) ?? []

  return <main className="workspace result-workspace">
    <div className="analysis-nav"><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index < 4 ? 'completed' : 'active'}><span>{index < 4 ? '✓' : index + 1}</span>{name}</li>)}</ol></div>
    <header className="result-header">
      <div><h1>Результат модели</h1><p>Итоги обучения, проверка качества и анализ поведения модели на всей оценочной выборке.</p></div>
      <div className="result-header-actions" aria-label="Действия с результатом">
        <div className="result-save-action">
          <button className="secondary-action" disabled={!result || modelIsSaved || modelSaveStatus === 'SAVING'} onClick={openModelSaveDialog} title={saveButtonTitle} aria-label={saveButtonTitle ?? saveButtonLabel}><Icon name="file" size={17} />{saveButtonLabel}</button>
          {modelSaveError && <span className="result-save-error" role="alert">{modelSaveError}</span>}
        </div>
        <button className="secondary-action" disabled title={unavailable} aria-label={`Экспорт отчёта. ${unavailable}`}><Icon name="download" size={17} />Экспорт отчёта</button>
        <button className="primary-action" disabled title={unavailable} aria-label={`Обзор проекта. ${unavailable}`}><Icon name="folder" size={17} />Обзор проекта</button>
      </div>
    </header>
    {error && <section className="result-error" role="alert"><strong>Результат недоступен</strong><p>{error}</p></section>}
    {!result && !error && <p className="feature-loading">Загружаем сохранённый результат…</p>}
    {result && summary && threshold && <div className="result-dashboard">
      <section className="result-summary-strip panel" aria-label="Сводка эксперимента">
        <SummaryFact icon="algorithm" label="Алгоритм" value={summary.model_id} detail={`Версия ${summary.model_version}`} />
        <SummaryFact icon="table" label="Данные" value={`${integerFormat.format(summary.object_count)} объектов`} />
        <SummaryFact icon="chart" label="Признаки" value={integerFormat.format(summary.feature_count)} />
        <SummaryFact icon="layers" label="Проверка" value={`OOF · ${integerFormat.format(summary.folds)} части`} />
        <SummaryFact icon="clock" label="Время обучения" value={summary.runtime_seconds === null ? '—' : `${numberFormat.format(summary.runtime_seconds)} с`} />
      </section>

      <aside className="result-info-banner"><Icon name="info" size={22} /><p>Метрики рассчитаны по OOF-прогнозам: каждая строка оценивалась моделью, которая не обучалась на этой строке.</p></aside>

      <div className="result-top-grid">
        <section className="result-panel panel">
          <PanelHeading title="Качество модели" icon="info" action="Подробнее о качестве" />
          <div className="result-quality-metrics">
            <Metric label="Gini" value={metric(summary.gini)} bar={summary.gini} />
            <Metric label="ROC-AUC" value={metric(summary.roc_auc)} bar={summary.roc_auc} />
            <Metric label="PR-AUC" value={metric(summary.pr_auc)} bar={summary.pr_auc} />
          </div>
        </section>

        <section className="result-panel panel">
          <PanelHeading title="Стабильность проверки" action="Подробнее" />
          {foldMetrics.length ? <>
            <div className="result-fold-chart result-overview-fold-chart" role="img" aria-label={`ROC-AUC по ${foldMetrics.length} частям проверки`}>
              <div className="result-chart-ylabels"><span>1,0</span><span>0,5</span><span>0,0</span></div>
              <div className="result-chart-plot">
                <div className="result-fold-gridline top" /><div className="result-fold-gridline middle" /><div className="result-fold-gridline bottom" />
                <div className="result-fold-bars">{foldMetrics.map(fold => <div className="result-fold-bar" key={fold.fold} title={`Часть ${fold.fold}: ROC-AUC ${metric(fold.roc_auc)}`}>
                  <strong>{metric(fold.roc_auc)}</strong>
                  <span className="result-fold-track"><i style={{ height: `${Math.max(0, Math.min(fold.roc_auc, 1)) * 100}%` }} /></span>
                  <small>Часть {fold.fold}</small>
                </div>)}</div>
              </div>
            </div>
            <p className="result-chart-legend"><i />ROC-AUC по частям проверки</p>
          </> : <p className="result-muted">Данные для графика недоступны.</p>}
          <p className="result-note">Разброс по фолдам не доказывает стабильность во времени.</p>
        </section>

        <section className="result-panel result-capture-panel panel">
          <CapturePanelHeading />
          <CaptureChart capture={capture} />
        </section>
      </div>

      <div className="result-middle-grid">
        <section className="result-panel result-errors-panel panel">
          <PanelHeading title="Ошибки и порог" icon="info" badge="Диагностический порог" />
          <div className="result-error-top-metrics">
            <Metric label="Порог" value={thresholdFormat.format(threshold.threshold)} />
            <Metric label="Recall" value={percent(threshold.recall)} />
            <Metric label="Precision" value={percent(threshold.precision)} />
          </div>
          <div className="result-error-counts">
            <ErrorCountRow label="Пропущено событий" count={integerFormat.format(threshold.fn)} rate={errorRate(threshold.fn, threshold.tp + threshold.fn)} tone="negative" />
            <ErrorCountRow label="Ложных срабатываний" count={integerFormat.format(threshold.fp)} rate={errorRate(threshold.fp, threshold.tn + threshold.fp)} tone="warning" />
          </div>
          <button className="primary-action result-panel-action" onClick={onOpenThreshold}>Исследовать порог <Icon name="arrow" size={18} /></button>
        </section>

        <section className="result-panel result-influence-panel panel">
          <PanelHeading title="На какие признаки модель опиралась сильнее всего" icon="info" action="Подробнее" onAction={() => navigate(routes.resultGlobalExplanation)} />
          <FeatureInfluencePreview explanation={globalPreview} status={globalPreviewStatus} />
        </section>
      </div>

      <section className="result-objects-strip panel">
        <span className="result-objects-icon"><Icon name="users" size={26} /></span>
        <div className="result-objects-copy"><h2>Объекты оценки</h2><p>Посмотрите отдельные объекты, сложные случаи и причины конкретных прогнозов.</p></div>
        <ObjectFact icon="alert-circle" tone="negative" label="Сложные случаи" value="—" unavailable />
        <ObjectFact icon="warning" tone="warning" label="Пограничные" value="—" unavailable />
        <ObjectFact icon="info" tone="info" label="Пропущенные события" value={integerFormat.format(threshold.fn)} />
        <button className="primary-action" onClick={onOpenObjects}>Посмотреть объекты <Icon name="arrow" size={18} /></button>
      </section>

      <GlobalResultInterpreterPanel globalStatus={globalPreviewStatus} artifactId={summary.artifact_id} />

      <details className="result-collapsible panel"><summary><Icon name="warning" size={22} /><span>Ограничения и предупреждения</span><small>Важная информация об интерпретации результата модели</small></summary>
        {summary.limitations.length ? <ul className="result-limitations">{summary.limitations.map((limitation, index) => <li key={`${index}-${limitation}`}>{limitation}</li>)}</ul> : <p className="result-muted">Backend не передал ограничений для этого результата.</p>}
      </details>
      <details className="result-collapsible result-technical panel"><summary><Icon name="file" size={22} /><span>Технические сведения</span><small>Детальная информация о модели, данных и процессе обучения</small></summary>
        <dl><div><dt>Artifact ID</dt><dd>{summary.artifact_id}</dd></div><div><dt>Result ID</dt><dd>{summary.result_id}</dd></div><div><dt>Уровень оценки</dt><dd>{summary.evaluation_level}</dd></div><div><dt>Время выполнения</dt><dd>{summary.runtime_seconds === null ? '—' : `${numberFormat.format(summary.runtime_seconds)} с`}</dd></div></dl>
      </details>
    </div>}
    {modelNameDialogOpen && <div className="native-modal-backdrop" role="presentation"><section className="native-modal" role="dialog" aria-modal="true" aria-labelledby="save-model-name-title"><h2 id="save-model-name-title">Название модели</h2><p>Перед первым сохранением задайте отображаемое название модели.</p><label>Название<input autoFocus value={modelName} maxLength={160} onChange={event => setModelName(event.target.value)} /></label>{modelSaveError && <p className="result-save-error" role="alert">{modelSaveError}</p>}<div><button className="secondary-action" disabled={modelSaveStatus === 'SAVING'} onClick={() => setModelNameDialogOpen(false)}>Отмена</button><button className="primary-action" disabled={modelSaveStatus === 'SAVING' || !modelName.trim()} onClick={() => void saveModel()}>{modelSaveStatus === 'SAVING' ? 'Сохраняем…' : 'Сохранить модель'}</button></div></section></div>}
  </main>
}

function SummaryFact({ icon, label, value, detail }: { icon: 'algorithm' | 'table' | 'chart' | 'layers' | 'clock'; label: string; value: string; detail?: string }) {
  return <div className="result-summary-fact"><span className="result-summary-icon"><Icon name={icon} size={24} /></span><div><small>{label}</small><strong>{value}</strong>{detail && <span>{detail}</span>}</div></div>
}

function PanelHeading({ title, icon, action, badge, onAction }: { title: string; icon?: 'info'; action?: string; badge?: string; onAction?: () => void }) {
  return <div className="result-panel-heading"><h2>{title}{icon && <span className="result-heading-info" title={title}><Icon name={icon} size={17} /></span>}</h2>{badge && <span className="result-heading-badge">{badge}</span>}{action && <button className="tertiary-action result-heading-action" disabled={!onAction} onClick={onAction} title={onAction ? undefined : unavailable} aria-label={onAction ? `${action}: ${title}` : `${action} о разделе «${title}». ${unavailable}`}>{action} <Icon name="arrow" size={15} /></button>}</div>
}

function CapturePanelHeading() {
  const [tooltipVisible, setTooltipVisible] = useState(false)
  const tooltipId = 'capture-chart-tooltip'
  return <div className="result-panel-heading capture-panel-heading"><h2>Сколько событий находим<button type="button" className="capture-info-trigger" aria-label="Как читать график охвата событий" aria-describedby={tooltipId} onMouseEnter={() => setTooltipVisible(true)} onMouseLeave={() => setTooltipVisible(false)} onFocus={() => setTooltipVisible(true)} onBlur={() => setTooltipVisible(false)} onKeyDown={event => { if (event.key === 'Escape') { setTooltipVisible(false); event.currentTarget.blur() } }}><Icon name="info" size={15} /></button></h2><div id={tooltipId} className="capture-info-tooltip" role="tooltip" hidden={!tooltipVisible}><strong>Как читать график</strong><p>По оси X — доля объектов с наибольшими оценками модели в OOF-проверке, включённых в выборку. По оси Y — накопленная доля фактических целевых событий, найденных среди этих объектов.</p><p>График помогает понять, насколько целевые события концентрируются в верхней части ранжирования модели. На небольших выборках линия может быть ступенчатой: доля найденных событий меняется только при добавлении очередного объекта с целевым событием.</p><p>Отмеченная точка показывает конкретное сочетание доли объектов и доли найденных событий. Она не является автоматически лучшим порогом или бизнес-решением.</p></div></div>
}

function Metric({ label, value, bar, tone }: { label: string; value: string; bar?: number; tone?: 'negative' | 'warning' }) {
  const boundedBar = typeof bar === 'number' && Number.isFinite(bar) ? Math.max(0, Math.min(bar, 1)) : null
  return <div className={`result-metric${tone ? ` ${tone}` : ''}`}><small>{label}</small><strong>{value}</strong>{boundedBar !== null && <span className="result-metric-track"><i style={{ width: `${boundedBar * 100}%` }} /></span>}</div>
}

function CaptureChart({ capture }: { capture: ResultCapture | undefined }) {
  if (!capture || capture.total_positive_events === 0 || !capture.points.length) {
    return <div className="result-capture-empty"><Icon name="info" size={18} /><p>В выборке нет целевых событий для построения кривой охвата.</p></div>
  }
  const line = capture.points
    .map((point, index) => {
      const x = point.object_share * 100
      const y = 100 - point.event_share * 100
      return index === 0 ? `M ${x} ${y}` : `H ${x} V ${y}`
    })
    .join(' ')
  const marker = capture.marker

  return <div className="result-capture-chart">
    <div className="result-capture-graphic" role="img" aria-label="Накопительная ступенчатая кривая найденных целевых событий по OOF-прогнозам">
      <span className="result-capture-ytitle">Найдено событий, %</span>
      <div className="result-capture-ylabels"><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div>
      <div className="result-capture-plot">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {[0, 25, 50, 75, 100].map(value => <line className="result-capture-grid" key={`h-${value}`} x1="0" x2="100" y1={value} y2={value} />)}
          {[0, 25, 50, 75, 100].map(value => <line className="result-capture-grid" key={`v-${value}`} y1="0" y2="100" x1={value} x2={value} />)}
          <path className="result-capture-line" d={line} />
          {marker && <><line className="result-capture-marker-line" x1={marker.object_share * 100} x2={marker.object_share * 100} y1={100 - marker.event_share * 100} y2="100" /><circle className="result-capture-marker-dot" cx={marker.object_share * 100} cy={100 - marker.event_share * 100} r="2.7" /></>}
        </svg>
      </div>
      <div className="result-capture-ticks"><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div>
      <span className="result-capture-xtitle">Доля объектов, %</span>
    </div>
    {marker && <p className="result-capture-readout"><strong>{percent(marker.object_share)} объектов</strong><span>→</span><strong>{percent(marker.event_share)} событий</strong></p>}
  </div>
}

function FeatureInfluencePreview({ explanation, status }: { explanation: GlobalOOFExplanation | null; status: GlobalPreviewStatus }) {
  const features = explanation?.features.slice(0, 7) ?? []
  const maxValue = Math.max(0, ...features.map(feature => Number.isFinite(feature.mean_abs_shap) ? feature.mean_abs_shap : 0))
  return <div className="result-influence-content">
    <div className="result-feature-preview">
      {status === 'loading' || status === 'idle' || status === 'running' ? <div className="result-influence-loading" role="status" aria-live="polite"><span className="global-spinner result-influence-spinner" aria-hidden="true" /><span><strong>Отчет готовится...</strong><small>Расчёт влияния признаков может занять несколько минут.</small></span></div>
        : status === 'changed' ? <p className="result-influence-state">Результат изменился. Обновите экран.</p>
          : status === 'error' ? <p className="result-influence-state">Влияние признаков пока недоступно.</p>
            : features.length ? features.map(feature => {
              const value = Number.isFinite(feature.mean_abs_shap) ? feature.mean_abs_shap : 0
              const width = maxValue > 0 ? Math.max(0, value) / maxValue * 100 : 0
              return <div className="result-feature-row" key={feature.feature_id} title={`Ранг ${feature.rank}: ${feature.column_name}`}>
                <span>{feature.column_name}</span><i><b style={{ width: `${width}%` }} /></i><strong>{metric(value)}</strong>
              </div>
            }) : <p className="result-influence-state">Нет признаков для отображения.</p>}
    </div>
    <aside><Icon name="info" size={18} /><p>Показывает, какие признаки в среднем сильнее влияли на оценки модели. Это описание поведения модели, а не доказательство причинного влияния.</p></aside>
  </div>
}

function ErrorCountRow({ label, count, rate, tone }: { label: string; count: string; rate: string; tone: 'negative' | 'warning' }) {
  return <div className={`result-error-count-row tone-${tone}`}><div><small>{label}</small><strong>{count}</strong></div><span className="result-error-rate">{rate}</span></div>
}

function ObjectFact({ icon, tone, label, value, unavailable: isUnavailable }: { icon: 'alert-circle' | 'warning' | 'info'; tone: 'negative' | 'warning' | 'info'; label: string; value: string; unavailable?: boolean }) {
  return <div className={`result-object-fact tone-${tone}`} title={isUnavailable ? 'Данные пока не подключены.' : undefined}><span className="result-object-fact-label"><Icon name={icon} size={15} /><small>{label}</small></span><strong>{value}</strong></div>
}
