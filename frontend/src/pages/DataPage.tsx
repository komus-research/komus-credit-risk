import { useEffect, useId, useRef, useState, type ReactElement } from 'react'
import { confirmDatasetPreparation, getDatasetPreparation, getDatasetProgress, getNativeSession, isDatasetNotUploaded, patchDatasetDraft, returnToDatasetRoles, reviewDatasetPreparation, type DatasetInspectionProgress, type DatasetPreparation, type PreparationWarning, uploadDataset } from '../api/session'
import { Icon } from '../components/Icon'
import { navigate, routes, type CanonicalRoute } from '../routing'

const permissionLabels: Record<string, string> = {
  MODEL_ALLOWED: 'Доступны модели', DIAGNOSTIC_ONLY: 'Только для диагностики', BLOCKED: 'Заблокированы', TARGET: 'Целевая колонка', IDENTIFIER: 'Идентификатор объекта',
}
const roleCards = [
  { key: 'target', label: 'Целевая колонка', icon: 'check' as const, hint: 'Колонка, по которой определяется целевое событие модели.' },
  { key: 'positive', label: 'Целевое событие', icon: 'settings' as const, hint: 'Значение, которое считается целевым событием.' },
  { key: 'identifier', label: 'Идентификатор объекта', icon: 'model' as const, hint: 'Поле для отображения объекта в результатах. Не используется как признак модели.' },
] as const
const inspectionStages = ['RECEIVING_FILE', 'STAGING_FILE', 'READING_SOURCE', 'INSPECTING_DATASET', 'ANALYZING_PREPARATION']

export function DataPage({ route, sessionReady, onDatasetUploaded, onStaleSession, recoveryMessage }: { route: CanonicalRoute; sessionReady: boolean; onDatasetUploaded: () => void; onStaleSession: () => void; recoveryMessage: string | null }) {
  const [preparation, setPreparation] = useState<DatasetPreparation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [inspecting, setInspecting] = useState(false)
  const [progress, setProgress] = useState<DatasetInspectionProgress | null>(null)
  const [now, setNow] = useState(Date.now())
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (route !== routes.roles && route !== routes.confirmation) {
      setPreparation(null)
      setInspecting(false)
      return
    }
    let active = true
    void getDatasetPreparation().then(next => {
      if (!active) return
      setPreparation(next)
      if (route === routes.roles) onDatasetUploaded()
    }).catch(reason => {
      if (!active) return
      setPreparation(null)
      if (isDatasetNotUploaded(reason)) onStaleSession()
    })
    return () => { active = false }
  }, [route, onDatasetUploaded, onStaleSession])
  useEffect(() => {
    if (!inspecting) return
    let active = true
    const refresh = () => void getDatasetProgress().then(next => {
      if (active && (next.status === 'RUNNING' || next.status === 'ERROR')) setProgress(next)
    }).catch(() => undefined)
    refresh()
    const interval = window.setInterval(refresh, 700)
    return () => { active = false; window.clearInterval(interval) }
  }, [inspecting])
  useEffect(() => {
    if (!inspecting || !progress?.started_at) return
    setNow(Date.now())
    const interval = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(interval)
  }, [inspecting, progress?.started_at])
  const update = (changes: Record<string, unknown>) => {
    setBusy(true); setError(null)
    void patchDatasetDraft(changes).then(setPreparation).catch(reason => {
      if (isDatasetNotUploaded(reason)) onStaleSession()
      else setError(reason instanceof Error ? reason.message : 'Не удалось сохранить изменения.')
    }).finally(() => setBusy(false))
  }
  const review = () => {
    setBusy(true); setError(null)
    void reviewDatasetPreparation().then(() => navigate(routes.confirmation)).catch(reason => {
      if (isDatasetNotUploaded(reason)) onStaleSession()
      else setError(reason instanceof Error ? reason.message : 'Не удалось открыть подтверждение.')
    }).finally(() => setBusy(false))
  }
  const backToRoles = () => {
    setBusy(true); setError(null)
    void returnToDatasetRoles().then(() => navigate(routes.roles)).catch(reason => {
      setError(reason instanceof Error ? reason.message : 'Не удалось вернуться к ролям.')
    }).finally(() => setBusy(false))
  }
  const selectFile = (file?: File) => {
    if (!file || !sessionReady || busy) return
    setBusy(true); setError(null)
    void (async () => {
      try {
        await getNativeSession()
        setInspecting(true)
        setProgress(null)
        setPreparation(await uploadDataset(file))
        onDatasetUploaded()
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : 'Не удалось обработать данные.')
      } finally {
        setInspecting(false)
        setBusy(false)
      }
    })()
  }

  if (route === routes.features) return <FeaturesBoundary />
  if (route === routes.confirmation) return <ConfirmationShell preparation={preparation} busy={busy} setBusy={setBusy} setError={setError} onBack={backToRoles} />

  return <main className="workspace data-workspace">
      <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index === 0 ? 'active' : ''}><span>{index + 1}</span>{name}</li>)}</ol></div>
      <header className="data-header"><h1>Подготовка данных</h1><p>Загрузите набор данных и проверьте, как система определила роли его колонок.</p></header>
      <ol className="data-stepper" aria-label="Этапы подготовки данных">{['Файл', 'Роли колонок', 'Подтверждение'].map((name, index) => {
        const state = inspecting ? (index === 0 ? 'active' : '') : preparation ? (index === 0 ? 'completed' : index === 1 ? 'active' : '') : (index === 0 ? 'active' : '')
        return <li key={name} className={state}><span>{state === 'completed' ? '✓' : index + 1}</span>{name}</li>
      })}</ol>

      {inspecting ? <section className="upload-panel panel"><InspectionProgress progress={progress} now={now} /></section> : route === '#/analysis/data/file' || !preparation ? <section className="upload-panel panel"><><Icon name="folder" size={42} /><h2>Загрузите файл датасета</h2><p>Поддерживаются CSV, XLSX, XLSB и Parquet. Файл обрабатывается на сервере и не раскрывает путь к нему в браузер.</p><input ref={input} type="file" accept=".csv,.xlsx,.xlsb,.parquet" disabled={!sessionReady || busy} onChange={event => selectFile(event.target.files?.[0])} /><button className="primary-action" disabled={!sessionReady || busy} onClick={() => input.current?.click()}><Icon name="plus" size={20} />Выбрать файл</button></></section> : <>
        <section className="file-summary panel">
          <div className="file-identity"><span className="file-icon"><Icon name="box" size={38} /></span><div><h2>{preparation.source.display_name}</h2><p className="file-ready"><Icon name="check" size={17} />Файл успешно проверен</p><p className="muted">Размер: {formatSize(preparation.source.size)}</p></div></div>
          <button className="secondary-action choose-file" disabled={!sessionReady || busy} onClick={() => input.current?.click()}>Выбрать другой файл</button>
          <dl className="file-facts"><Fact label="Строк" value={preparation.source.rows.toLocaleString('ru-RU')} /><Fact label="Колонок" value={String(preparation.source.columns)} /><Fact label="Размер" value={formatSize(preparation.source.size)} /><Fact label="Формат" value={preparation.source.format.toUpperCase()} /></dl>
          <input ref={input} className="hidden-input" type="file" accept=".csv,.xlsx,.xlsb,.parquet" disabled={!sessionReady || busy} onChange={event => selectFile(event.target.files?.[0])} />
        </section>

        <section className="key-roles panel"><div className="section-heading"><h2>Ключевые роли</h2><p>Укажите, какие колонки являются целевой, идентификатором и какое значение считается целевым событием.</p></div><div className="role-grid">{roleCards.map(role => <RoleControl key={role.key} role={role} preparation={preparation} busy={busy} update={update} />)}</div></section>
        <WarningPanel key={preparation.source.handle} preparation={preparation} />
        <section className="permission-summary panel"><div className="section-heading"><h2>Сводка по ролям</h2><p>Сводка рассчитана по текущему черновику ролей.</p></div><div className="permission-counts">{Object.entries(preparation.summary.permission_counts).map(([key, value]) => <div key={key}><span>{permissionLabels[key]}</span><strong>{value}</strong></div>)}</div></section>
        <footer className="data-footer"><button className="back-action" disabled={busy} onClick={() => navigate(routes.file)}>← Назад</button><div><p>Проверьте роли колонок перед подтверждением.</p><button className="primary-action" disabled={busy || !preparation.draft.target || !preparation.draft.identifier || preparation.draft.positive_class === null} onClick={review}>Продолжить к подтверждению <Icon name="arrow" size={19} /></button></div></footer>
      </>}
      {(recoveryMessage || error) && <div className="data-error" role={error ? 'alert' : 'status'}>
        {recoveryMessage && <span>{recoveryMessage}</span>}
        {recoveryMessage && error && <br />}
        {error && <span>{error}</span>}
      </div>}
    </main>
}

function Fact({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div> }
function WarningPanel({ preparation }: { preparation: DatasetPreparation }) {
  const [expanded, setExpanded] = useState(false)
  const [resolvedOpen, setResolvedOpen] = useState(false)
  const [infoOpen, setInfoOpen] = useState(false)
  const { warnings, warning_counts: counts } = preparation.summary
  const hasRequired = counts.action_required > 0
  const groups = [
    { state: 'ACTION_REQUIRED' as const, count: counts.action_required },
    { state: 'RESOLVED' as const, count: counts.resolved },
    { state: 'INFO' as const, count: counts.info },
  ]
  return <section className={`attention-section panel${hasRequired ? ' has-warnings' : ' all-resolved'}`}>
    <div className="warning-panel-header">
      <span className={`attention-icon${hasRequired ? '' : ' is-resolved'}`} aria-hidden="true">{hasRequired ? '!' : '✓'}</span>
      <div className="warning-panel-copy"><h2>Проверка колонок</h2><p>{hasRequired ? 'Есть замечания, которые стоит проверить перед продолжением.' : 'Все замечания учтены'}</p>
        <div className="warning-counts" aria-label="Сводка замечаний">
          {counts.action_required > 0 && <span className="warning-count action"><b>! {counts.action_required}</b> требуют решения</span>}
          {counts.resolved > 0 && <span className="warning-count resolved"><b>✓ {counts.resolved}</b> уже учтены</span>}
          {counts.info > 0 && <span className="warning-count info"><b>ⓘ {counts.info}</b> информация</span>}
        </div>
      </div>
      <button type="button" className="warning-panel-toggle" aria-expanded={expanded} aria-controls="preparation-warning-groups" onClick={() => setExpanded(value => !value)}>{expanded ? 'Скрыть' : 'Показать'}<span className={`warning-chevron${expanded ? ' open' : ''}`} aria-hidden="true" /></button>
    </div>
    {expanded && <div className="warning-list" id="preparation-warning-groups">
      {groups.map(({ state, count }) => {
        if (count === 0) return null
        const items = warnings.filter(warning => warning.resolution_state === state)
        if (state === 'ACTION_REQUIRED') return <section key={state} className="warning-group warning-group-action"><h3><span aria-hidden="true">!</span>Требуют решения — {count}</h3>{items.map((warning, index) => <WarningRow key={`${warning.code}-${warning.column_name ?? 'dataset'}-${index}`} warning={warning} state={state} />)}</section>
        const isResolved = state === 'RESOLVED'
        const open = isResolved ? resolvedOpen : infoOpen
        const toggle = isResolved ? setResolvedOpen : setInfoOpen
        return <section key={state} className={`warning-group warning-group-${state.toLowerCase()}`}>
          <button type="button" className="warning-group-toggle" aria-expanded={open} onClick={() => toggle(value => !value)}><span className="warning-group-symbol" aria-hidden="true">{isResolved ? '✓' : 'ⓘ'}</span><span>{isResolved ? 'Уже учтено' : 'Информация'} — {count}</span><span className={`warning-chevron${open ? ' open' : ''}`} aria-hidden="true" /></button>
          {open && <div className="warning-group-items">{items.map((warning, index) => <WarningRow key={`${warning.code}-${warning.column_name ?? 'dataset'}-${index}`} warning={warning} state={state} />)}</div>}
        </section>
      })}
    </div>}
  </section>
}

function WarningRow({ warning, state }: { warning: PreparationWarning; state: PreparationWarning['resolution_state'] }) {
  if (state === 'ACTION_REQUIRED') return <article className="warning-row warning-row-action">
    <span className="warning-marker" aria-hidden="true">!</span><div className="warning-row-content">
      <div className="warning-row-main"><strong className="warning-subject">{warning.subject_ru}</strong><span className="warning-title">{warning.title_ru}</span><WarningTooltip warning={warning} /></div>
      {warning.check_ru && <p className="warning-row-hint">{warning.check_ru}</p>}
    </div>
  </article>
  if (state === 'RESOLVED') return <article className="warning-row warning-row-resolved"><span className="warning-marker" aria-hidden="true">✓</span><div className="warning-row-content"><strong className="warning-subject">{warning.subject_ru}</strong><p className="warning-title">{warning.title_ru}</p>{warning.resolution_note_ru && <p className="warning-resolution-note">{warning.resolution_note_ru}</p>}</div></article>
  return <article className="warning-row warning-row-info"><span className="warning-marker" aria-hidden="true">ⓘ</span><div className="warning-row-content"><strong className="warning-subject">{warning.subject_ru}</strong><p className="warning-title">{warning.title_ru}</p><p className="warning-row-hint">{warning.detail_ru}</p></div></article>
}

function WarningTooltip({ warning }: { warning: PreparationWarning }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [open])
  return <span className="warning-tooltip-wrap" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false) }}>
    <button type="button" className="warning-tooltip-button" aria-label={`Подробнее: ${warning.title_ru}`} aria-describedby={open ? id : undefined} onFocus={() => setOpen(true)}>ⓘ</button>
    {open && <span className="warning-tooltip" id={id} role="tooltip"><strong>{warning.title_ru}</strong><span>Почему AXION обратил внимание</span><p>{warning.detail_ru}</p>{warning.check_ru && <><span>Что проверить</span><p>{warning.check_ru}</p></>}</span>}
  </span>
}
function InspectionProgress({ progress, now }: { progress: DatasetInspectionProgress | null; now: number }) {
  const activeStage = progress?.stage ?? null
  const activeIndex = activeStage ? inspectionStages.indexOf(activeStage) : -1
  const elapsed = progress?.started_at ? formatElapsed(now - Date.parse(progress.started_at)) : null
  return <div className="inspection-progress" aria-live="polite">
    <span className="inspection-stage-icon" aria-hidden="true"><Icon name="table" size={24} /></span>
    <div><h2>{progress?.stage_label ?? 'Проверка запускается'}</h2>{elapsed && <p className="inspection-elapsed">Прошло {elapsed}</p>}<p className="inspection-heartbeat"><span aria-hidden="true" />Проверка активна</p></div>
    <ol>{inspectionStages.map((stage, index) => <li key={stage} className={index < activeIndex ? 'done' : index === activeIndex ? 'current' : ''}><span>{index < activeIndex ? '✓' : index === activeIndex ? '●' : '○'}</span>{stageLabel(stage)}</li>)}</ol>
    <p className="inspection-note">Проверка продолжается, приложение работает. Для больших XLSB это может занять несколько минут.</p>
  </div>
}
function RoleControl({ role, preparation, busy, update }: { role: typeof roleCards[number]; preparation: DatasetPreparation; busy: boolean; update: (changes: Record<string, unknown>) => void }) {
  const target = preparation.draft.target ?? ''
  const identifier = preparation.draft.identifier ?? ''
  let select: ReactElement
  if (role.key === 'target') select = <select value={target} disabled={busy} onChange={event => update({ target: event.target.value || null })}><option value="">Не выбрана</option>{preparation.options.columns.map(value => <option key={value} value={value}>{value}</option>)}</select>
  else if (role.key === 'positive') select = <select value={String(preparation.draft.positive_class ?? '')} disabled={busy || !target} onChange={event => update({ positive_class: decodeValue(event.target.value, preparation.options.positive_classes) })}><option value="">Не выбрано</option>{preparation.options.positive_classes.map(value => <option key={String(value)} value={String(value)}>{String(value)}</option>)}</select>
  else select = <select value={identifier} disabled={busy} onChange={event => update({ identifier: event.target.value || null })}><option value="">Не выбран</option>{preparation.options.columns.filter(value => value !== target).map(value => <option key={value} value={value}>{value}</option>)}</select>
  return <article className="role-card"><span className={`role-icon ${role.key}`}><Icon name={role.icon} size={25} /></span><div><label>{role.label}</label>{select}<p>{role.hint}</p></div></article>
}

function formatSize(size: number) { return size < 1024 * 1024 ? `${Math.max(1, Math.round(size / 1024))} КБ` : `${(size / 1024 / 1024).toFixed(1)} МБ` }
function formatElapsed(milliseconds: number) { const seconds = Math.max(0, Math.floor(milliseconds / 1000)); return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}` }
function stageLabel(stage: string) { return ({ RECEIVING_FILE: 'Получаем файл', STAGING_FILE: 'Сохраняем временную копию', READING_SOURCE: 'Читаем таблицу', INSPECTING_DATASET: 'Проверяем структуру данных', ANALYZING_PREPARATION: 'Определяем роли колонок' } as Record<string, string>)[stage] ?? stage }
function decodeValue(value: string, choices: Array<string | number | boolean>) { return choices.find(item => String(item) === value) ?? null }

function ConfirmationShell({ preparation, busy, setBusy, setError, onBack }: { preparation: DatasetPreparation | null; busy: boolean; setBusy: (busy: boolean) => void; setError: (message: string | null) => void; onBack: () => void }) {
  const [acknowledged, setAcknowledged] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const confirm = () => {
    setBusy(true); setError(null); setMessage(null)
    void confirmDatasetPreparation(acknowledged).then(() => navigate(routes.features)).catch(reason => {
      const text = reason instanceof Error ? reason.message : 'Не удалось подтвердить подготовку данных.'
      setError(text); setMessage(text)
    }).finally(() => setBusy(false))
  }
  if (!preparation) return <main className="workspace data-workspace confirmation-workspace"><section className="upload-panel panel"><h2>Загружаем сведения о подготовке</h2></section></main>
  const counts = preparation.summary.permission_counts
  return <main className="workspace data-workspace confirmation-workspace">
    <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index === 0 ? 'active' : ''}><span>{index + 1}</span>{name}</li>)}</ol></div>
    <header className="data-header"><h1>Подготовка данных</h1><p>Проверьте сведения о файле, ключевые роли и итог подготовки перед созданием контекста данных.</p></header>
    <ol className="data-stepper confirmation-stepper" aria-label="Этапы подготовки данных"><li className="completed"><span>✓</span>Файл</li><li className="completed"><span>✓</span>Роли колонок</li><li className="active"><span>3</span>Подтверждение</li></ol>
    <section className="confirmation-file panel"><h2>Файл</h2><div className="confirmation-file-body"><span className="file-icon"><Icon name="box" size={38} /></span><div className="confirmation-file-identity"><strong>{preparation.source.display_name}</strong><p>{preparation.source.rows.toLocaleString('ru-RU')} строк <span>·</span> {preparation.source.columns} колонок <span>·</span> {formatSize(preparation.source.size)} <span>·</span> {preparation.source.format.toUpperCase()}</p></div></div></section>
    <section className="confirmation-card confirmation-roles panel"><h2>Ключевые роли</h2><div className="confirmation-role-grid"><article><span className="role-icon target"><Icon name="check" size={25} /></span><div><label>Цель</label><output>{preparation.draft.target ?? 'Не выбрана'}</output></div></article><article><span className="role-icon positive"><Icon name="settings" size={25} /></span><div><label>Целевое событие</label><output>{String(preparation.draft.positive_class ?? 'Не выбрано')}</output></div></article><article><span className="role-icon identifier"><Icon name="model" size={25} /></span><div><label>Идентификатор</label><output>{preparation.draft.identifier ?? 'Не выбран'}</output></div></article></div></section>
    <section className="confirmation-card confirmation-result panel"><h2>Итог подготовки</h2><p className="confirmation-total">{preparation.source.columns} колонок всего</p>
      <div className="confirmation-summary-grid">
        <section className="confirmation-summary-card" aria-label="Будет использовано в модели">
          <h3>Будет использовано в модели</h3>
          <div className="confirmation-summary-row model_allowed"><span className="confirmation-summary-icon"><Icon name="chart" size={21} /></span><span>Признаки модели</span><strong>{counts.MODEL_ALLOWED ?? 0}</strong></div>
          <div className="confirmation-summary-row target"><span className="confirmation-summary-icon"><Icon name="settings" size={20} /></span><span>Целевая колонка</span><strong>{counts.TARGET ?? 0}</strong></div>
          <div className="confirmation-summary-row identifier"><span className="confirmation-summary-icon"><Icon name="model" size={20} /></span><span>Идентификатор</span><strong>{counts.IDENTIFIER ?? 0}</strong></div>
        </section>
        <section className="confirmation-summary-card confirmation-summary-unused" aria-label="Не используется напрямую">
          <h3>Не используется напрямую</h3>
          <div className="confirmation-unused-value"><span className="confirmation-summary-icon"><Icon name="alert-circle" size={21} /></span><strong>{(counts.DIAGNOSTIC_ONLY ?? 0) + (counts.BLOCKED ?? 0)}</strong><span>колонок</span></div>
        </section>
      </div>
      <div className="confirmation-policy"><p>Вся подтверждённая популяция используется для OOF-оценки. Защищённая финальная тестовая выборка на этом этапе не создаётся.</p><label><input type="checkbox" checked={acknowledged} disabled={busy} onChange={event => setAcknowledged(event.target.checked)} /> Я понимаю и подтверждаю эту политику.</label></div>
    </section>
    {message && <div className="data-error confirmation-error" role="alert">{message}</div>}
    <footer className="data-footer confirmation-footer" aria-busy={busy}><button className="back-action" disabled={busy} onClick={onBack}>← Назад к ролям</button><div><button className="primary-action" aria-busy={busy} disabled={busy || !acknowledged} onClick={confirm}>{busy ? <><span className="confirmation-progress-spinner" aria-hidden="true" />Подготавливаем признаки…</> : <>Подтвердить и перейти к признакам <Icon name="arrow" size={19} /></>}</button></div></footer>
    </main>
}

function FeaturesBoundary() {
  return <main className="workspace data-workspace features-boundary"><p className="eyebrow">Новый анализ · Шаг 2</p><section className="panel"><Icon name="check" size={36} /><h1>Данные подготовлены</h1><p>Подтверждённый контекст создан на сервере. Выбор признаков будет доступен на следующем этапе.</p><button className="secondary-action" onClick={() => navigate(routes.home)}>На главную</button></section></main>
}
