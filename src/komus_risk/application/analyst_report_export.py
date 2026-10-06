"""Read-only projections of immutable analyst-report artifacts.

The report JSON remains the authority.  This module only turns an already
validated V1 artifact into display/export content; it never reaches inference,
SHAP, drafts, or an interpreter.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from textwrap import wrap
from typing import Any


@dataclass(frozen=True, slots=True)
class ReportContribution:
    name: str
    raw_value: float
    shap_value: float
    direction: str


@dataclass(frozen=True, slots=True)
class ReportCompany:
    number: int
    identifier: str
    subject_name: str | None
    score: float
    threshold: float
    position_label: str
    contributions: tuple[ReportContribution, ...]
    interpretations: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ReportProjection:
    report_id: str
    content_hash: str
    created_at: str
    model_version: str
    inference_result_id: str
    threshold: float
    companies: tuple[ReportCompany, ...]


def project_report(report: dict[str, Any]) -> ReportProjection:
    """Project a report whose integrity was checked by ``AnalystReportStore``."""
    source = report["source"]
    threshold = float(report["decision_context"]["threshold"])
    companies = tuple(
        ReportCompany(
            number=index,
            identifier=company["identifier"],
            subject_name=company["subject_name"],
            score=float(company["score"]),
            threshold=float(company["threshold"]),
            position_label="Выше порога" if company["position"] == "ABOVE" else "Ниже порога",
            contributions=tuple(
                ReportContribution(
                    name=item["display_name_ru"] or item["column_name"],
                    raw_value=float(item["raw_value"]),
                    shap_value=float(item["shap_value"]),
                    direction=_direction_label(item["direction"]),
                )
                for item in company["report_visible_contributions"]
            ),
            interpretations=tuple((item["role"], item["text"]) for item in company["role_interpretations"]),
        )
        for index, company in enumerate(report["companies"], start=1)
    )
    return ReportProjection(
        report_id=report["report_id"], content_hash=report["content_hash"],
        created_at=report["created_at"], model_version=source["model_version"],
        inference_result_id=source["inference_result_id"], threshold=threshold, companies=companies,
    )


def _direction_label(value: str) -> str:
    return {
        "increases_output": "Повышает оценку модели",
        "decreases_output": "Снижает оценку модели",
        "neutral": "Не изменяет оценку модели",
    }[value]


def report_pdf(projection: ReportProjection) -> bytes:
    """Render a dependable, paginated A4 text PDF using installed matplotlib."""
    import matplotlib
    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib import rcParams

    rcParams["font.family"] = "DejaVu Sans"  # bundled by matplotlib; supports Cyrillic.
    destination = BytesIO()
    lines = _pdf_lines(projection)
    per_page = 43
    with PdfPages(destination) as pdf:
        for start in range(0, len(lines), per_page):
            figure = plt.figure(figsize=(8.27, 11.69))
            figure.patch.set_facecolor("white")
            page = lines[start:start + per_page]
            figure.text(0.08, 0.965, "AXION", fontsize=16, fontweight="bold", color="#0b4b50")
            figure.text(0.08, 0.938, "Аналитический отчёт", fontsize=12, fontweight="bold")
            figure.text(0.08, 0.905, "\n".join(page), fontsize=8.6, va="top", linespacing=1.38)
            figure.text(0.08, 0.035, f"report_id: {projection.report_id}", fontsize=6.5, color="#555555")
            pdf.savefig(figure, bbox_inches="tight")
            plt.close(figure)
    return destination.getvalue()


def _pdf_lines(projection: ReportProjection) -> list[str]:
    lines = [
        f"Дата формирования: {projection.created_at}",
        f"Модель: {projection.model_version}",
        f"Inference Result: {projection.inference_result_id}",
        f"Порог решения: {projection.threshold:.3f}",
        f"Количество компаний: {len(projection.companies)}", "",
    ]
    for company in projection.companies:
        title = f"Компания {company.number}: {company.identifier}"
        if company.subject_name:
            title += f" ({company.subject_name})"
        lines += [title, f"Score: {company.score:.3f}; порог: {company.threshold:.3f}; {company.position_label}", "Основные факторы Local SHAP:"]
        lines += [f"• {item.name}: {item.raw_value:g}; SHAP {item.shap_value:+.4f}; {item.direction}" for item in company.contributions]
        if company.interpretations:
            lines.append("Result Interpreter:")
            for role, text in company.interpretations:
                lines.append(f"{role}: {text}")
        else:
            lines.append("Интерпретация Result Interpreter не была сформирована на момент создания отчёта.")
        lines.append("")
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(wrap(line, width=104, break_long_words=False, break_on_hyphens=False) or [""])
    return wrapped


def report_docx(projection: ReportProjection) -> bytes:
    """Render the same projection to DOCX, retaining Russian Unicode text."""
    from docx import Document
    from docx.shared import Pt

    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10)
    document.add_heading("AXION", level=1)
    document.add_heading("Аналитический отчёт", level=2)
    for text in (
        f"Дата формирования: {projection.created_at}", f"Модель: {projection.model_version}",
        f"Inference Result: {projection.inference_result_id}", f"Порог решения: {projection.threshold:.3f}",
        f"Количество компаний: {len(projection.companies)}",
    ):
        document.add_paragraph(text)
    for company in projection.companies:
        heading = f"Компания {company.number}: {company.identifier}"
        if company.subject_name:
            heading += f" ({company.subject_name})"
        document.add_heading(heading, level=2)
        document.add_paragraph(f"Score: {company.score:.3f}; порог: {company.threshold:.3f}; {company.position_label}")
        document.add_heading("Основные факторы Local SHAP", level=3)
        table = document.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        for cell, value in zip(table.rows[0].cells, ("Признак", "Значение", "SHAP", "Направление"), strict=True):
            cell.text = value
        for item in company.contributions:
            cells = table.add_row().cells
            for cell, value in zip(cells, (item.name, f"{item.raw_value:g}", f"{item.shap_value:+.4f}", item.direction), strict=True):
                cell.text = value
        document.add_heading("Result Interpreter", level=3)
        if company.interpretations:
            for role, text in company.interpretations:
                document.add_paragraph(f"{role}: {text}")
        else:
            document.add_paragraph("Интерпретация Result Interpreter не была сформирована на момент создания отчёта.")
    document.add_heading("Техническая информация", level=2)
    document.add_paragraph(f"report_id: {projection.report_id}")
    document.add_paragraph(f"content_hash: {projection.content_hash}")
    destination = BytesIO()
    document.save(destination)
    return destination.getvalue()
