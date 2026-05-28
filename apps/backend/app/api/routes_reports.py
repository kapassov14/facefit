from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, selectinload

from app.api.serializers import report_public_dict
from app.core.exceptions import not_found
from app.db.crm import add_lead_event
from app.db.models import AnalysisRequest, BotSettings, CampaignSource, ClientStatus, CtaClickEvent, GeneratedReport, ReportViewEvent
from app.db.repositories import get_bot_settings
from app.db.session import get_db
from app.reports.bella_web_report import build_bella_web_report_data, render_bella_web_report_html

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/{token}")
def get_public_report(token: str, db: Session = Depends(get_db)) -> dict:
    report = (
        db.query(GeneratedReport)
        .options(
            selectinload(GeneratedReport.analysis).selectinload(AnalysisRequest.lead),
            selectinload(GeneratedReport.analysis).selectinload(AnalysisRequest.telegram_user),
            selectinload(GeneratedReport.analysis).selectinload(AnalysisRequest.images),
        )
        .filter(GeneratedReport.public_token == token, GeneratedReport.is_published.is_(True))
        .first()
    )
    if not report:
        raise not_found("Отчет не найден")
    settings = get_bot_settings(db)
    payload = report_public_dict(report, settings)
    payload["report_abc"] = build_bella_web_report_data(report, settings)
    return payload


@router.get("/{token}/html", response_class=HTMLResponse)
def get_public_report_html(token: str, request: Request, db: Session = Depends(get_db)) -> str:
    report = (
        db.query(GeneratedReport)
        .options(
            selectinload(GeneratedReport.analysis).selectinload(AnalysisRequest.lead),
            selectinload(GeneratedReport.analysis).selectinload(AnalysisRequest.telegram_user),
            selectinload(GeneratedReport.analysis).selectinload(AnalysisRequest.images),
        )
        .filter(GeneratedReport.public_token == token, GeneratedReport.is_published.is_(True))
        .first()
    )
    if not report:
        raise not_found("Отчет не найден")
    settings = get_bot_settings(db)
    report.opened_count += 1
    if report.analysis and report.analysis.lead:
        report.analysis.lead.report_opened = True
        if report.analysis.lead.crm_status not in {ClientStatus.CTA_CLICKED, ClientStatus.PAID, ClientStatus.BOUGHT}:
            report.analysis.lead.crm_status = ClientStatus.REPORT_OPENED
        add_lead_event(db, report.analysis.lead, "report_opened", "Пользователь открыл отчет", {"report_id": report.id})
    db.add(
        ReportViewEvent(
            report_id=report.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    db.commit()
    return render_bella_web_report_html(report, settings)


@router.post("/{token}/view")
def track_view(token: str, request: Request, db: Session = Depends(get_db)) -> dict:
    report = db.query(GeneratedReport).filter(GeneratedReport.public_token == token, GeneratedReport.is_published.is_(True)).first()
    if not report:
        raise not_found("Отчет не найден")
    report.opened_count += 1
    if report.analysis and report.analysis.lead:
        report.analysis.lead.report_opened = True
        if report.analysis.lead.crm_status not in {ClientStatus.CTA_CLICKED, ClientStatus.PAID, ClientStatus.BOUGHT}:
            report.analysis.lead.crm_status = ClientStatus.REPORT_OPENED
        add_lead_event(db, report.analysis.lead, "report_opened", "Пользователь открыл отчет", {"report_id": report.id})
    db.add(
        ReportViewEvent(
            report_id=report.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    db.commit()
    return {"ok": True, "event": "report_opened"}


@router.post("/{token}/cta-click")
def track_cta(token: str, request: Request, db: Session = Depends(get_db)) -> dict:
    report = db.query(GeneratedReport).filter(GeneratedReport.public_token == token, GeneratedReport.is_published.is_(True)).first()
    if not report:
        raise not_found("Отчет не найден")
    settings: BotSettings = get_bot_settings(db)
    target = settings.whatsapp_url or settings.telegram_url or settings.instagram_url or ""
    report.cta_click_count += 1
    if report.analysis and report.analysis.lead:
        report.analysis.lead.cta_clicked = True
        report.analysis.lead.crm_status = ClientStatus.CTA_CLICKED
        add_lead_event(db, report.analysis.lead, "cta_clicked", "Пользователь нажал CTA", {"report_id": report.id, "target_url": target})
        if report.analysis.telegram_user and report.analysis.telegram_user.campaign:
            campaign: CampaignSource = report.analysis.telegram_user.campaign
            campaign.cta_clicks += 1
    db.add(
        CtaClickEvent(
            report_id=report.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            target_url=target,
        )
    )
    db.commit()
    return {"ok": True, "event": "cta_clicked", "target_url": target}
