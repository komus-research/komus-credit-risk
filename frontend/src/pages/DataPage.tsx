import { useEffect, useRef, useState, type ReactElement } from 'react'
import { getDatasetPreparation, getDatasetProgress, getNativeSession, patchDatasetDraft, type DatasetInspectionProgress, type DatasetPreparation, uploadDataset } from '../api/session'
import { Icon } from '../components/Icon'

const asset = (path: string) => `/native-assets/${path}`
const permissionLabels: Record<string, string> = {
  MODEL_ALLOWED: 'Доступны модели', DIAGNOSTIC_ONLY: 'Только для диагностики', BLOCKED: 'Заблокированы', TARGET: 'Целевая колонка', IDENTIFIER: 'Идентификатор объекта',
}
const roleCards = [
  { key: 'target', label: 'Целевая колонка', icon: 'check' as const, hint: 'Колонка, по которой определяется целевое событие модели.' },
  { key: 'positive', label: 'Целевое событие', icon: 'settings' as const, hint: 'Значение, которое считается целевым событием.' },
  { key: 'identifier', label: 'Идентификатор объекта', icon: 'model' as const, hint: 'Поле для отображения объекта в результатах. Не используется как признак модели.' },
] as const
const inspectionStages = ['RECEIVING_FILE', 'STAGING_FILE', 'READING_SOURCE', 'INSPECTING_DATASET', 'ANALYZING_PREPARATION']

export function DataPage() {
  const [preparation, setPreparation] = useState<DatasetPreparation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [inspecting, setInspecting] = useState(false)
  const [progress, setProgress] = useState<DatasetInspectionProgress | null>(null)
  const [now, setNow] = useState(Date.now())
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    void getNativeSession().catch(() => undefined)
    void getDatasetPreparation().then(setPreparation).catch(() => undefined)
  }, [])
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
    void patchDatasetDraft(changes).then(setPreparation).catch((reason: Error) => setError(reason.message)).finally(() => setBusy(false))
  }
  const selectFile = (file?: File) => {
    if (!file) return
    setBusy(true); setInspecting(true); setProgress(null); setError(null)
    void (async () => {
      try {
        await getNativeSession()
        setPreparation(await uploadDataset(file))
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : 'Не удалось обработать данные.')
      } finally {
        setInspecting(false)
        setBusy(false)
      }
    })()
  }

  return <div className="app-shell data-shell">
    <aside className="sidebar">
      <img className="brand" src={asset('brand/logo-primary-dark.png')} alt="AXION — аналитическая платформа" />
      <nav aria-label="Основная навигация" className="navigation">
        <a className="nav-item nav-link" href="/" aria-label="Главная"><Icon name="home" size={26} /><span>Главная</span></a>
        <div className="nav-item is-active"><Icon name="plus" size={26} /><span>Новый анализ</span></div>
        <button className="nav-item" disabled><Icon name="model" size={26} /><span>Модели</span></button>
        <button className="nav-item" disabled><Icon name="menu" size={26} /><span>Проекты / История</span></button>
        <button className="nav-item with-divider" disabled><Icon name="settings" size={26} /><span>Настройки</span></button>
      </nav>
      <div className="profile"><div className="avatar">АП</div><div><strong>Андреев П. С.</strong><small>Аналитик</small></div></div>
    </aside>

    <main className="workspace data-workspace">
      <div className="analysis-nav"><span className="analysis-context">Новый анализ</span><ol className="analysis-stepper" aria-label="Этапы анализа">{['Данные', 'Признаки', 'Алгоритм', 'Проверка качества', 'Результат'].map((name, index) => <li key={name} className={index === 0 ? 'active' : ''}><span>{index + 1}</span>{name}</li>)}</ol></div>
      <header className="data-header"><h1>Подготовка данных</h1><p>Загрузите набор данных и проверьте, как система определила роли его колонок.</p></header>
      <ol className="data-stepper" aria-label="Этапы подготовки данных">{['Файл', 'Роли колонок', 'Подтверждение'].map((name, index) => {
        const state = preparation ? (index === 0 ? 'completed' : index === 1 ? 'active' : '') : (index === 0 ? 'active' : '')
        return <li key={name} className={state}><span>{state === 'completed' ? '✓' : index + 1}</span>{name}</li>
      })}</ol>

      {!preparation ? <section className="upload-panel panel">{inspecting ? <InspectionProgress progress={progress} now={now} /> : <><Icon name="folder" size={42} /><h2>Загрузите файл датасета</h2><p>Поддерживаются CSV, XLSX, XLSB и Parquet. Файл обрабатывается на сервере и не раскрывает путь к нему в браузер.</p><input ref={input} type="file" accept=".csv,.xlsx,.xlsb,.parquet" onChange={event => selectFile(event.target.files?.[0])} /><button className="primary-action" disabled={busy} onClick={() => input.current?.click()}><Icon name="plus" size={20} />Выбрать файл</button></>}</section> : <>
        <section className="file-summary panel">
          <div className="file-identity"><span className="file-icon"><Icon name="box" size={38} /></span><div><h2>{preparation.source.display_name}</h2><p className="file-ready"><Icon name="check" size={17} />Файл успешно проверен</p><p className="muted">Размер: {formatSize(preparation.source.size)}</p></div></div>
          <button className="secondary-action choose-file" disabled={busy} onClick={() => input.current?.click()}>Выбрать другой файл</button>
          <dl className="file-facts"><Fact label="Строк" value={preparation.source.rows.toLocaleString('ru-RU')} /><Fact label="Колонок" value={String(preparation.source.columns)} /><Fact label="Размер" value={formatSize(preparation.source.size)} /><Fact label="Формат" value={preparation.source.format.toUpperCase()} /></dl>
          <input ref={input} className="hidden-input" type="file" accept=".csv,.xlsx,.xlsb,.parquet" onChange={event => selectFile(event.target.files?.[0])} />
        </section>

        <section className="key-roles panel"><div className="section-heading"><h2>Ключевые роли</h2><p>Укажите, какие колонки являются целевой, идентификатором и какое значение считается целевым событием.</p></div><div className="role-grid">{roleCards.map(role => <RoleControl key={role.key} role={role} preparation={preparation} busy={busy} update={update} />)}</div></section>
        <section className="attention-section panel"><div className="section-heading attention-heading"><span className="attention-icon">!</span><div><h2>Требуют внимания{preparation.summary.warnings.length ? ` — ${preparation.summary.warnings.length}` : ''}</h2><p>{preparation.summary.warnings.length ? 'Проверьте замечания перед подтверждением ролей колонок.' : 'Нет замечаний, требующих решения'}</p></div></div>{preparation.summary.warnings.length > 0 && <div className="warning-list">{preparation.summary.warnings.map((warning, index) => <p key={`${warning}-${index}`}>{warning}</p>)}</div>}</section>
        <section className="permission-summary panel"><div className="section-heading"><h2>Колонки без замечаний</h2><p>Сводка рассчитана по текущему черновику ролей.</p></div><div className="permission-counts">{Object.entries(preparation.summary.permission_counts).map(([key, value]) => <div key={key}><span>{permissionLabels[key]}</span><strong>{value}</strong></div>)}</div></section>
        <section className="inert-section panel"><div><Icon name="menu" size={25} /><div><h2>Предпросмотр данных</h2><p>Содержимое набора данных пока не доступно в этом экране.</p></div></div><Icon name="arrow" size={20} /></section>
        <section className="inert-section panel"><div><Icon name="settings" size={25} /><div><h2>Технические сведения</h2><p>Дополнительные параметры файла будут показаны здесь, когда станут доступны.</p></div></div><Icon name="arrow" size={20} /></section>
        <footer className="data-footer"><button className="secondary-action" disabled>Назад</button><div><p>Проверьте роли колонок перед подтверждением.</p><button className="primary-action" disabled>Продолжить к подтверждению <Icon name="arrow" size={19} /></button></div></footer>
      </>}
      {error && <div className="data-error" role="alert">{error}</div>}
    </main>
  </div>
}

function Fact({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div> }
function InspectionProgress({ progress, now }: { progress: DatasetInspectionProgress | null; now: number }) {
  const activeStage = progress?.stage ?? null
  const activeIndex = activeStage ? inspectionStages.indexOf(activeStage) : -1
  const elapsed = progress?.started_at ? formatElapsed(now - Date.parse(progress.started_at)) : null
  return <div className="inspection-progress" aria-live="polite">
    <Icon name="settings" size={35} />
    <div><h2>{progress?.stage_label ?? 'Проверка запускается'}</h2>{elapsed && <p className="inspection-elapsed">Прошло {elapsed}</p>}</div>
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
