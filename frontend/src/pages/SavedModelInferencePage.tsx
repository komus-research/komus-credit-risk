import { useEffect, useRef, useState } from 'react'
import { cancelSavedModelInference, preflightSavedModelInference, runSavedModelInference, type SavedModelInferencePreflight } from '../api/inference'
import { getModelVersion, type ModelVersionDetail } from '../api/models'
import { buildInferenceResultRoute, buildModelDetailRoute, navigate } from '../routing'
import { Icon } from '../components/Icon'

const dateFormat = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
const numberFormat = new Intl.NumberFormat('ru-RU')

function errorMessage(reason: unknown) { return reason instanceof Error ? reason.message : 'Не удалось выполнить проверку новых данных.' }
function date(value: string) { const parsed = new Date(value); return Number.isNaN(parsed.getTime()) ? value : dateFormat.format(parsed) }

export function SavedModelInferencePage({ modelVersionId }: { modelVersionId: string }) {
  const [model, setModel] = useState<ModelVersionDetail | null>(null)
  const [modelError, setModelError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const [preflight, setPreflight] = useState<SavedModelInferencePreflight | null>(null)
  const [replacementError, setReplacementError] = useState<string | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const preparedId = useRef<string | null>(null)
  const lifecycle = useRef({ generation: 0, modelVersionId: '' })

  useEffect(() => {
    const generation = lifecycle.current.generation + 1
    lifecycle.current = { generation, modelVersionId }
    const controller = new AbortController()
    setModel(null); setModelError(null); setPreflight(null); setReplacementError(null); setRunError(null); setChecking(false); setRunning(false); preparedId.current = null
    const isCurrent = () => lifecycle.current.generation === generation && lifecycle.current.modelVersionId === modelVersionId
    void getModelVersion(modelVersionId, controller.signal).then(value => { if (!controller.signal.aborted && isCurrent()) setModel(value) }).catch(reason => { if (!controller.signal.aborted && isCurrent()) setModelError(errorMessage(reason)) })
    return () => {
      controller.abort()
      const preparationId = preparedId.current
      preparedId.current = null
      if (isCurrent()) lifecycle.current = { generation: generation + 1, modelVersionId }
      if (preparationId) void cancelSavedModelInference(modelVersionId, preparationId).catch(() => undefined)
    }
  }, [modelVersionId])

  const selectFile = async (file: File | null) => {
    if (!file || checking || running) return
    const requestGeneration = lifecycle.current.generation
    const requestModelVersionId = modelVersionId
    const isCurrent = () => lifecycle.current.generation === requestGeneration && lifecycle.current.modelVersionId === requestModelVersionId
    setChecking(true); setReplacementError(null); setRunError(null)
    try {
      const next = await preflightSavedModelInference(requestModelVersionId, file)
      if (!isCurrent()) {
        void cancelSavedModelInference(requestModelVersionId, next.preparation_id).catch(() => undefined)
        return
      }
      preparedId.current = next.preparation_id
      setPreflight(next)
    } catch (reason) {
      if (isCurrent()) setReplacementError(errorMessage(reason))
    } finally { if (isCurrent()) setChecking(false) }
  }
  const run = async () => {
    const preparationId = preparedId.current
    if (!preparationId || running) return
    const requestGeneration = lifecycle.current.generation
    const requestModelVersionId = modelVersionId
    const isCurrent = () => lifecycle.current.generation === requestGeneration && lifecycle.current.modelVersionId === requestModelVersionId
    setRunning(true); setRunError(null)
    try {
      const result = await runSavedModelInference(requestModelVersionId, preparationId)
      if (!isCurrent()) return
      if (preparedId.current === preparationId) preparedId.current = null
      navigate(buildInferenceResultRoute(result.inference_result_id))
    } catch (reason) { if (isCurrent()) { setRunError(errorMessage(reason)); setRunning(false) } }
  }

  if (!model && !modelError) return <main className="workspace inference-workspace"><section className="inference-state"><Icon name="clock" size={30} /><p>Загружаем сохранённую модель…</p></section></main>
  if (modelError) return <main className="workspace inference-workspace"><section className="inference-state inference-error" role="alert"><Icon name="warning" size={28} /><div><strong>Не удалось загрузить модель</strong><p>{modelError}</p><button className="back-action" onClick={() => navigate(buildModelDetailRoute(modelVersionId))}>← Назад к модели</button></div></section></main>
  if (!model) return null

  return <main className="workspace inference-workspace">
    <button className="back-action inference-back" onClick={() => navigate(buildModelDetailRoute(model.model_version_id))}>← Назад к модели</button>
    <header className="inference-header"><p className="eyebrow">Модели / {model.display_name} / Прогноз</p><h1>Прогноз на новых данных</h1><p>Используйте сохранённую модель для расчёта оценки новых объектов.</p></header>
    <section className="panel inference-model-card"><h2>Используемая модель</h2><div className="inference-model-facts"><div className="inference-card-icon"><Icon name="box" size={34} /></div><div><strong>{model.display_name}</strong><small>Сохранённая модель</small></div><dl><div><dt>Алгоритм</dt><dd>{model.algorithm.model_display_name}</dd></div><div><dt>Версия сохранённой модели</dt><dd>{model.display_version}</dd></div><div><dt>Датасет обучения</dt><dd>{model.dataset.dataset_name}</dd></div><div><dt>Обучена</dt><dd>{date(model.source_result.experiment_created_at)}</dd></div><div><dt>Признаков модели</dt><dd>{model.features.length}</dd></div></dl><button className="secondary-action" onClick={() => navigate(buildModelDetailRoute(model.model_version_id))}><Icon name="folder" />Открыть модель</button></div></section>
    <section className="panel inference-file-card"><h2>Новые данные</h2>{preflight ? <div className="inference-file-ready"><div className="inference-card-icon"><Icon name="file" size={34} /></div><div><strong>{preflight.source_display_name}</strong><small>Формат: {preflight.source_format.toUpperCase()}</small></div><dl><div><dt>Объектов (строк)</dt><dd>{numberFormat.format(preflight.row_count)}</dd></div><div><dt>Столбцов</dt><dd>{preflight.column_count}</dd></div><div><dt>Идентификатор</dt><dd>{preflight.identifier_column}</dd></div><div><dt>Target</dt><dd>Не требуется</dd></div></dl><button className="secondary-action" disabled={checking || running} onClick={() => inputRef.current?.click()}><Icon name="folder" />Выбрать другой файл</button></div> : <div className="inference-file-empty"><Icon name="file" size={32} /><div><strong>Выберите новые данные</strong><p>Target для расчёта оценки не требуется.</p></div><button className="secondary-action" disabled={checking || running} onClick={() => inputRef.current?.click()}><Icon name="folder" />Выбрать файл</button></div>}
      <input ref={inputRef} className="hidden-input" type="file" onChange={event => { void selectFile(event.target.files?.[0] ?? null); event.currentTarget.value = '' }} />
      {checking && <p className="inference-inline-status"><Icon name="clock" />Проверяем совместимость выбранного файла…</p>}
      {replacementError && <p className="inference-inline-error" role="alert"><Icon name="warning" />{replacementError}{preflight ? ' Предыдущая совместимая подготовка остаётся доступна для анализа.' : ''}</p>}
    </section>
    {preflight && <div className="inference-ready-layout"><section className="panel inference-checks"><h2>Проверка совместимости</h2>{([['required_features', 'Входные признаки', `${preflight.required_feature_count} обязательных признаков найдены.`], ['input_types', 'Типы данных', 'Типы входных данных совместимы с моделью.'], ['feature_binding', 'Порядок и привязка', 'Признаки сопоставлены с сохранённой схемой модели.'], ['rows', 'Объекты', `${numberFormat.format(preflight.row_count)} строк готовы к расчёту оценки.`], ['identifier', 'Идентификатор', `Столбец ${preflight.identifier_column} будет использован для отображения объектов.`]] as const).map(([key, title, detail]) => <div className="inference-check" key={key}><Icon name="check" /><strong>{title}</strong><span>{detail}</span><b>{preflight.checks[key] === 'PASS' ? 'Готово' : '—'}</b></div>)}{preflight.ignored_column_count > 0 && <div className="inference-ignored"><Icon name="info" /><div><strong>Дополнительные столбцы: {preflight.ignored_column_count}</strong><span>Они разрешены, отображены как игнорируемые и не будут переданы модели.</span></div></div>}</section><aside className="inference-aside-stack"><section className="panel inference-aside"><h2>Объяснение результатов</h2><div className="inference-availability"><span><Icon name="check" />Local Explanation / SHAP</span><span><Icon name="check" />Result Interpreter</span></div><p>После расчёта оценки объектов будут доступны в сохранённом результате.</p></section><section className="panel inference-aside"><h2>После расчёта</h2><p>Вы сможете:</p><ul><li>просматривать оценки всех объектов;</li><li>искать объекты по идентификатору;</li><li>сортировать и фильтровать результаты;</li><li>сохранять конфигурацию просмотра.</li></ul></section></aside></div>}
    {runError && <p className="inference-inline-error" role="alert"><Icon name="warning" />{runError}</p>}
    <footer className={`inference-run-panel panel ${preflight ? 'is-ready' : ''}`}><div><Icon name={preflight ? 'check' : 'info'} size={32} /><div><h2>{preflight ? 'Данные готовы к расчёту' : 'Сначала выберите файл'}</h2><p>{preflight ? `Сохранённая модель рассчитает оценки для ${numberFormat.format(preflight.row_count)} объектов. Модель не будет переобучена.` : 'Проверка совместимости начнётся только после выбора файла.'}</p></div></div><div><button className="secondary-action" disabled={running} onClick={() => navigate(buildModelDetailRoute(model.model_version_id))}>Отмена</button><button className="primary-action" disabled={!preflight || checking || running} onClick={() => void run()}><Icon name="arrow" />{running ? 'Анализ…' : 'Анализ'}</button></div></footer>
    {preflight && <details className="panel inference-technical-row"><summary><Icon name="settings" /><strong>Технические сведения</strong><span>Проверенная подготовка новых данных</span><Icon name="arrow" /></summary><dl><div><dt>Идентификатор</dt><dd>{preflight.identifier_column}</dd></div><div><dt>Формат источника</dt><dd>{preflight.source_format}</dd></div><div><dt>Обязательные признаки</dt><dd>{preflight.required_feature_count}</dd></div></dl></details>}
  </main>
}
