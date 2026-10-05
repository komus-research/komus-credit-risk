import { useEffect, useState, type FormEvent } from 'react'
import { getModelVersion, renameModelVersion, type ModelVersionDetail } from '../api/models'
import { navigate, routes } from '../routing'
import { Icon } from '../components/Icon'

const metricFormat = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
const numberFormat = new Intl.NumberFormat('ru-RU')
const dateFormat = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : dateFormat.format(date)
}

function value(value: unknown) {
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

function DetailContent({ model, onRenamed }: { model: ModelVersionDetail; onRenamed: (displayName: string) => void }) {
  const [editingName, setEditingName] = useState(false)
  const [draftName, setDraftName] = useState(model.display_name)
  const [renameBusy, setRenameBusy] = useState(false)
  const [renameError, setRenameError] = useState<string | null>(null)
  const technical = {
    model_version_id: model.model_version_id,
    experiment_artifact_id: model.experiment_artifact_id,
    dataset_fingerprint: model.dataset.dataset_fingerprint,
    population_id: model.population.population_id,
    population_fingerprint: model.population.population_fingerprint,
    ...model.technical_provenance,
  }
  const metrics = [
    ['Gini', model.oof_quality.gini], ['ROC-AUC', model.oof_quality.roc_auc], ['PR-AUC', model.oof_quality.pr_auc],
    ['Precision @ 0.50', model.oof_quality.precision_at_0_5], ['Recall @ 0.50', model.oof_quality.recall_at_0_5], ['F1 @ 0.50', model.oof_quality.f1_at_0_5],
  ]
  const startRename = () => {
    setDraftName(model.display_name)
    setRenameError(null)
    setEditingName(true)
  }
  const cancelRename = () => {
    if (renameBusy) return
    setDraftName(model.display_name)
    setRenameError(null)
    setEditingName(false)
  }
  const submitRename = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const nextName = draftName.trim()
    if (!nextName || nextName.length > 160 || /[\r\n\0]/.test(nextName)) {
      setRenameError('Название модели должно содержать от 1 до 160 символов в одной строке.')
      return
    }
    if (nextName === model.display_name) {
      setEditingName(false)
      setRenameError(null)
      return
    }
    setRenameBusy(true)
    setRenameError(null)
    try {
      const renamed = await renameModelVersion(model.model_version_id, nextName)
      onRenamed(renamed.display_name)
      setDraftName(renamed.display_name)
      setEditingName(false)
    } catch (reason) {
      setRenameError(reason instanceof Error ? reason.message : 'Не удалось изменить название модели.')
    } finally {
      setRenameBusy(false)
    }
  }
  return <>
    <button className="back-action model-back-link" onClick={() => navigate(routes.models)}>← Модели</button>
    <header className="model-detail-header"><div className="model-detail-title"><p className="eyebrow">Сохранённая обученная модель</p>{editingName
      ? <form className="model-name-edit-form" onSubmit={submitRename}><input value={draftName} maxLength={160} autoFocus onChange={event => setDraftName(event.target.value)} onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); cancelRename() } }} aria-label="Название модели" /><button className="text-action" type="submit" disabled={renameBusy}>Сохранить</button><button className="text-action model-name-edit-cancel" type="button" disabled={renameBusy} onClick={cancelRename}>Отмена</button></form>
      : <div className="model-name-row"><h1>{model.display_name}</h1><button className="model-name-edit-action" type="button" onClick={startRename} aria-label="Изменить название модели" title="Изменить название модели"><Icon name="edit" size={21} /></button></div>}{renameError && <p className="model-name-edit-error" role="alert">{renameError}</p>}</div><div className="model-detail-identity"><div><small>Алгоритм</small><strong>{model.algorithm.model_display_name}</strong></div><div><small>Версия сохранённой модели</small><strong>{model.display_version}</strong></div><div><small>Статус</small><strong className="model-saved-status">● Сохранена</strong></div></div></header>
    <section className="model-quick-summary panel"><div><Icon name="layers" /><small>Датасет</small><strong>{model.dataset.dataset_name}</strong></div><div><Icon name="chart" /><small>Признаки</small><strong>{model.features.length}</strong></div><div><Icon name="clock" /><small>Эксперимент создан</small><strong>{formatDate(model.source_result.experiment_created_at)}</strong></div><div><Icon name="chart" /><small>OOF Gini</small><strong>{metricFormat.format(model.oof_quality.gini)}</strong></div></section>
    <section className="model-future-actions"><button className="primary-action" disabled title="Возможность пока не подключена"><Icon name="arrow" />Использовать для прогноза</button><button className="secondary-action" disabled title="Возможность пока не подключена"><Icon name="plus" />Новый запуск на основе модели</button><button className="secondary-action" disabled title="Возможность пока не подключена"><Icon name="chart" />Открыть результаты</button></section>
    <section className="model-detail-section panel"><div className="model-section-heading"><Icon name="chart" /><div><h2>Качество модели (OOF)</h2><p>Метрики рассчитаны по OOF-прогнозам. Precision, Recall и F1 приведены для диагностического порога 0.50.</p></div></div><div className="model-quality-grid">{metrics.map(([label, metric]) => <article key={String(label)}><small>{label}</small><strong>{metricFormat.format(metric as number)}</strong><i style={{ width: `${Math.max(0, Math.min(100, Number(metric) * 100))}%` }} /></article>)}</div></section>
    <section className="model-detail-section panel"><div className="model-section-heading"><Icon name="layers" /><div><h2>Данные и признаки</h2><p>Сохранённая привязка датасета, популяции и признаков.</p></div></div><div className="model-data-features"><dl className="model-facts"><div><dt>Датасет</dt><dd>{model.dataset.dataset_name} · {model.dataset.dataset_version}</dd></div><div><dt>Популяция</dt><dd>{model.population.population_role} · {numberFormat.format(model.population.population_row_count)} строк</dd></div><div><dt>Target</dt><dd>{model.target}</dd></div><div><dt>Положительный класс</dt><dd>{String(model.positive_class)}</dd></div><div><dt>Identifier</dt><dd>{model.identifier}</dd></div><div><dt>Признаки</dt><dd>{model.features.length}</dd></div></dl><div className="model-features-table-wrap"><table><thead><tr><th>Признак</th><th>Техническое имя</th><th>Тип</th><th>Статус</th></tr></thead><tbody>{model.features.map(feature => <tr key={feature.feature_id}><td><strong>{feature.display_name}</strong><small>{feature.description}</small></td><td>{feature.column_name}</td><td>{feature.logical_type}</td><td>{feature.usage_status}</td></tr>)}</tbody></table></div></div></section>
    <details className="model-details panel"><summary><Icon name="settings" /><strong>Параметры обучения</strong><span>Сохранённая конфигурация, seed и протокол</span></summary><dl className="model-technical-list"><div><dt>Режим конфигурации</dt><dd>{model.configuration.configuration_mode ?? 'Не указан'}</dd></div><div><dt>User overrides</dt><dd><pre>{model.configuration.user_overrides == null ? '—' : value(model.configuration.user_overrides)}</pre></dd></div><div><dt>Resolved parameters</dt><dd><pre>{value(model.configuration.resolved_parameters)}</pre></dd></div><div><dt>Seed / folds</dt><dd>{model.configuration.seed} / {model.configuration.folds}</dd></div><div><dt>Протокол</dt><dd>{model.configuration.protocol_id} · {model.configuration.protocol_version}</dd></div><div><dt>Уровень оценки</dt><dd>{model.configuration.evaluation_level}</dd></div></dl></details>
    <details className="model-details panel"><summary><Icon name="settings" /><strong>Технические сведения</strong><span>Идентификаторы, хеши и сохранённое происхождение</span></summary><dl className="model-technical-list">{Object.entries(technical).filter(([, item]) => item !== null && item !== undefined).map(([key, item]) => <div key={key}><dt>{key}</dt><dd><pre>{value(item)}</pre></dd></div>)}</dl></details>
  </>
}

export function ModelVersionDetailPage({ modelVersionId }: { modelVersionId: string }) {
  const [model, setModel] = useState<ModelVersionDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setModel(null)
    setError(null)
    void getModelVersion(modelVersionId, controller.signal)
      .then(value => { if (!controller.signal.aborted) setModel(value) })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить сохранённую модель.') })
    return () => controller.abort()
  }, [modelVersionId, retryToken])

  return <main className="workspace models-workspace model-detail-workspace">
    {!model && !error && <section className="model-detail-state"><Icon name="clock" size={30} /><p>Загружаем сохранённую модель…</p></section>}
    {error && <section className="model-detail-state model-detail-error" role="alert"><Icon name="warning" size={30} /><div><strong>Не удалось загрузить модель</strong><p>{error}</p><button className="secondary-action" onClick={() => setRetryToken(value => value + 1)}>Повторить</button><button className="back-action" onClick={() => navigate(routes.models)}>← Модели</button></div></section>}
    {model && <DetailContent model={model} onRenamed={displayName => setModel(current => current ? { ...current, display_name: displayName } : current)} />}
  </main>
}
