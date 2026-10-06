import { useEffect, useState } from 'react'
import { downloadAnalystReport, getAnalystReport, type AnalystReport } from '../api/inference'
import { buildSavedInferenceReportDraftRoute, navigate } from '../routing'
import { Icon } from '../components/Icon'
import { TechnicalDetails } from '../components/TechnicalDetails'

const score = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 3, maximumFractionDigits: 3 })
const metric = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 4, maximumFractionDigits: 4 })

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : 'Не удалось загрузить аналитический отчёт.'
}

function direction(value: string) {
  return value === 'increases_output' ? 'Повышает оценку модели' : value === 'decreases_output' ? 'Снижает оценку модели' : 'Не изменяет оценку модели'
}

export function AnalystReportPage({ reportId }: { reportId: string }) {
  const [report, setReport] = useState<AnalystReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState<'pdf' | 'docx' | null>(null)

  useEffect(() => {
    let active = true
    setReport(null); setError(null)
    void getAnalystReport(reportId).then(value => { if (active) setReport(value) }).catch(reason => { if (active) setError(errorMessage(reason)) })
    return () => { active = false }
  }, [reportId])

  const download = async (format: 'pdf' | 'docx') => {
    if (downloading) return
    setDownloading(format); setError(null)
    try { await downloadAnalystReport(reportId, format) }
    catch (reason) { setError(errorMessage(reason)) }
    finally { setDownloading(null) }
  }

  const back = () => {
    if (report) navigate(buildSavedInferenceReportDraftRoute(report.source.inference_result_id))
    else window.history.back()
  }

  return <main className="workspace analyst-report-workspace">
    <header className="inference-result-header analyst-report-header"><div><button className="back-action inference-back" onClick={back}>← К черновику</button><p className="eyebrow">Модели / Анализ / Аналитический отчёт</p><h1>АНАЛИТИЧЕСКИЙ ОТЧЁТ</h1><p>Неизменяемая версия отчёта, сформированная из сохранённого evidence.</p></div><div className="inference-result-actions"><button className="secondary-action" disabled={!report || downloading !== null} onClick={() => void download('pdf')}><Icon name="download" />{downloading === 'pdf' ? 'Скачиваем…' : 'Скачать PDF'}</button><button className="primary-action" disabled={!report || downloading !== null} onClick={() => void download('docx')}><Icon name="download" />{downloading === 'docx' ? 'Скачиваем…' : 'Скачать DOCX'}</button></div></header>
    {error && <p className="inference-inline-error" role="alert"><Icon name="warning" />{error}</p>}
    {!error && !report && <section className="panel inference-state" aria-busy="true"><Icon name="clock" size={30} /><p>Загружаем аналитический отчёт…</p></section>}
    {report && <>
      <section className="panel analyst-report-meta"><div><span>Дата формирования</span><strong>{new Date(report.created_at).toLocaleString('ru-RU')}</strong></div><div><span>Модель</span><strong>{report.model_summary?.display_name ?? report.source.model_version}</strong></div><div><span>Порог решения</span><strong>{score.format(report.decision_context.threshold)}</strong></div><div><span>Компаний</span><strong>{report.companies.length}</strong></div></section>
      {report.model_summary && <section className="panel analyst-report-summary"><header><h2>Модель и качество</h2><p>Снимок сохранённой ModelVersion на момент формирования отчёта.</p></header><dl><div><dt>Модель</dt><dd>{report.model_summary.display_name}</dd></div><div><dt>Алгоритм</dt><dd>{report.model_summary.model_display_name}</dd></div><div><dt>Обучающая выборка</dt><dd>{report.model_summary.dataset_name}</dd></div><div><dt>Признаков</dt><dd>{report.model_summary.feature_count}</dd></div><div><dt>Кросс-валидация</dt><dd>{report.model_summary.folds} folds</dd></div><div><dt>OOF Gini</dt><dd>{metric.format(report.model_summary.oof_gini)}</dd></div><div><dt>OOF ROC-AUC</dt><dd>{metric.format(report.model_summary.oof_roc_auc)}</dd></div><div><dt>OOF PR-AUC</dt><dd>{metric.format(report.model_summary.oof_pr_auc)}</dd></div></dl></section>}
      <section className="analyst-report-list">{report.companies.map((company, index) => <article className="panel analyst-report-company" key={company.row_id}><header><span>{index + 1}</span><div><h2>{company.identifier}{company.subject_name ? ` · ${company.subject_name}` : ''}</h2><p>Оценка модели: <b>{score.format(company.score)}</b> · Порог: {score.format(company.threshold)} · <strong className={company.position === 'ABOVE' ? 'above' : 'below'}>{company.position === 'ABOVE' ? 'Выше порога' : 'Ниже порога'}</strong></p></div></header><h3>Основные факторы Local SHAP</h3><div className="analyst-report-table-wrap"><table><thead><tr><th>Признак</th><th>Значение</th><th>SHAP</th><th>Направление</th></tr></thead><tbody>{company.report_visible_contributions.map(item => <tr key={item.feature_id}><td>{item.display_name_ru || item.column_name}</td><td>{item.raw_value}</td><td>{item.shap_value >= 0 ? '+' : ''}{item.shap_value.toFixed(4)}</td><td>{direction(item.direction)}</td></tr>)}</tbody></table></div><h3>Result Interpreter</h3>{company.role_interpretations.length ? <div className="analyst-report-interpretations">{company.role_interpretations.map(item => <p key={`${item.role}-${item.text}`}><b>{item.role}.</b> {item.text}</p>)}</div> : <p className="analyst-report-muted">Интерпретация Result Interpreter не была сформирована на момент создания отчёта.</p>}</article>)}</section>
      <TechnicalDetails className="panel analyst-report-provenance"><summary>Техническая информация</summary><p>report_id: {report.report_id}</p><p>inference_result_id: {report.source.inference_result_id}</p><p>content_hash: {report.content_hash}</p></TechnicalDetails>
    </>}
  </main>
}
