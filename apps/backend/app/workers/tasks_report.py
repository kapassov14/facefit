from __future__ import annotations

import logging

from app.db.models import AnalysisRequest, GeneratedReport
from app.db.session import SessionLocal
from app.reports.html_report import build_face_protocol_html, build_report_json
from app.workers.celery_app import celery_app
from app.workers.tasks_analysis import log_job

logger = logging.getLogger(__name__)


def _regenerate_report(analysis_id: int) -> None:
    db = SessionLocal()
    try:
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if not analysis or not analysis.analysis_json:
            raise ValueError("Анализ не найден или JSON анализа пустой")
        extra = {"source": "backend_template"}
        report_json = build_report_json(analysis.lead.name if analysis.lead else "Гость", analysis.analysis_json, analysis.selected_problems or [], extra)
        report = analysis.report or GeneratedReport(analysis_id=analysis.id, lead_id=analysis.lead_id)
        report.report_json = report_json
        report.html_content = build_face_protocol_html(analysis.analysis_json, analysis.lead.name if analysis.lead else "Гость", analysis.selected_problems or [], extra)
        report.is_published = True
        analysis.report_json = report_json
        db.add(report)
        db.commit()
        log_job(db, analysis.id, "regenerate_report", "success", "Report regenerated")
    except Exception as exc:
        logger.exception("Report regeneration failed")
        log_job(db, analysis_id, "regenerate_report", "failed", str(exc))
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks_report.regenerate_report_task", bind=True)
def regenerate_report_task(self, analysis_id: int) -> None:
    _regenerate_report(analysis_id)


def enqueue_report(analysis_id: int) -> None:
    try:
        regenerate_report_task.apply_async(args=[analysis_id], queue="report")
    except Exception as exc:
        logger.exception("Celery broker unavailable; report regeneration was not started")
        db = SessionLocal()
        try:
            log_job(db, analysis_id, "regenerate_report_enqueue", "failed", str(exc))
        finally:
            db.close()
