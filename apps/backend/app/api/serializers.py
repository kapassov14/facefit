from __future__ import annotations

import re
from typing import Any

from app.core.config import AFTER_PHOTO_DISABLED_REASON, after_photo_feature_enabled
from app.db.models import (
    AdminUser,
    AnalysisRequest,
    BotSettings,
    Broadcast,
    CampaignSource,
    GeneratedReport,
    KnowledgeDocument,
    Lead,
    PromptTemplate,
    TelegramUser,
)
from app.storage.local import local_storage


STATUS_LABELS = {
    "good": "Всё хорошо",
    "attention": "Зона внимания",
    "priority": "Приоритет",
}


def _clean_text(value: Any, fallback: str = "") -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\b[Пп]роблем(а|ы|у|ой|е|ами|ах)?\b", "зона внимания", text)
    text = re.sub(r"\b[Бб]рыли\b", "снижение чёткости овала", text)
    text = re.sub(r"\b[Мм]ешки под глазами\b", "отёчность в зоне глаз", text)
    text = re.sub(r"\b[Нн]ормальная кожа\b", "кожа с ровной плотной базой", text)
    text = re.sub(r"\b[Нн]ормаль\w+\b", "комбинированная с ровной плотной базой", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or fallback


def _skin_type_title(value: Any) -> str:
    text = _clean_text(value)
    lowered = text.lower()
    if not lowered or lowered in {"normal", "unknown", "none", "не определено", "визуально не определено"}:
        return "Комбинированная, с ровной плотной базой"
    if "норм" in lowered:
        return "Комбинированная, с ровной плотной базой"
    if "сух" in lowered or "dry" in lowered or "обезвож" in lowered:
        return "Комбинированная, склонная к обезвоженности" if "комби" in lowered else "Сухая, склонная к обезвоженности"
    if "жир" in lowered or "oily" in lowered or "t-зон" in lowered or "т-зон" in lowered:
        return "Комбинированная, активная в T-зоне"
    if "чувств" in lowered or "sensitive" in lowered or "реактив" in lowered:
        return "Чувствительная, реактивная"
    if "комби" in lowered or "смешан" in lowered or "combination" in lowered or "mixed" in lowered:
        if "ровн" in lowered or "плот" in lowered:
            return "Комбинированная, с ровной плотной базой"
        return "Комбинированная, склонная к обезвоженности"
    return text or "Комбинированная, с ровной плотной базой"


def _skin_type_items(title: Any, source: Any, fallback: list[str] | None = None, limit: int = 4) -> list[str]:
    fallback_items = fallback or [
        "Плюс: кожа выглядит ровной и хорошо держит каркас лица.",
        "Зона глаз и центр лица быстрее показывают недосып.",
        "Увлажнение и мягкий отток поддерживают ровное сияние.",
    ]
    raw_items = source if isinstance(source, list) else []
    result: list[str] = []
    weak_markers = {
        "хорошая текстура",
        "присутствует легкая отечность",
        "присутствует лёгкая отёчность",
        "лицо выглядит уставшим",
        "есть потенциал",
        "хороший ресурс",
        "хорошим ресурсом",
        "эластич",
        "требует внимания",
        "лимфодренаж",
        "работа с тонусом",
        "более свежий",
        "отдохнувший вид",
        "четче овал",
        "чётче овал",
        "мягче носогубная",
        "поддержание тонуса",
        "улучшение лимфотока",
        "борьбы с отечностью",
        "борьбы с отёчностью",
        "хочется",
        "отёки по утрам",
        "отеки по утрам",
        "овал лица",
        "линия подбородка",
    }
    skin_markers = {
        "кож",
        "увлаж",
        "glass",
        "каркас",
        "плот",
        "ровн",
        "сиян",
        "текстур",
        "t-зон",
        "т-зон",
        "себум",
        "реактив",
        "сух",
        "центр лица",
        "зона глаз",
    }
    for item in raw_items:
        cleaned = _clean_text(item)
        cleaned = re.sub(r"^\s*плюс\s*[:\-—–]\s*", "", cleaned, flags=re.IGNORECASE)
        lowered = cleaned.lower()
        if (
            not cleaned
            or len(cleaned) < 22
            or any(marker in lowered for marker in weak_markers)
            or not any(marker in lowered for marker in skin_markers)
        ):
            continue
        if cleaned not in result:
            result.append(cleaned)
    if not result:
        for item in fallback_items:
            if len(result) >= limit:
                break
            cleaned_fb = re.sub(r"^\s*плюс\s*[:\-—–]\s*", "", item, flags=re.IGNORECASE)
            if cleaned_fb not in result:
                result.append(cleaned_fb)
    return _dedupe_lines(result)[:limit]


def _dedupe_lines(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = re.sub(r"\s+", " ", re.sub(r"[^0-9a-zа-яё ]", "", item.lower())).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _list(value: Any, fallback: list[str] | None = None, limit: int | None = None) -> list[str]:
    source = value if isinstance(value, list) else []
    result = [_clean_text(item) for item in source if _clean_text(item)]
    if not result and fallback:
        result = fallback[:]
    result = _dedupe_lines(result)
    return result[:limit] if limit else result


def _status(value: Any, color: Any = None) -> str:
    cleaned = _clean_text(value).lower()
    color_cleaned = _clean_text(color).lower()
    if cleaned in STATUS_LABELS:
        return cleaned
    if color_cleaned in {"green", "зелёный", "зеленый"}:
        return "good"
    if color_cleaned in {"red", "красный"}:
        return "priority"
    return "attention"


def _asset(path: str | None) -> dict[str, str | None]:
    if not path:
        return {"path": None, "url": None}
    if path.startswith(("http://", "https://", "data:")):
        return {"path": None, "url": path}
    return {"path": None, "url": local_storage.public_url(path)}


def _media_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith(("http://", "https://", "data:")):
        return path
    return local_storage.public_url(path)


def _score_percent(score: Any) -> int:
    match = re.search(r"\d{1,3}", _clean_text(score))
    if not match:
        return 78
    return max(0, min(100, int(match.group(0))))


def _skin_age_value(skin_age: dict[str, Any], protocol_copy: dict[str, Any]) -> str:
    if isinstance(protocol_copy.get("skin_age"), dict):
        value = _clean_text(protocol_copy["skin_age"].get("value"))
        if value:
            return value
    match = re.search(r"\d{1,3}", _clean_text(skin_age.get("estimated_range")))
    return match.group(0) if match else "32"


def _public_report_cta_url(settings: BotSettings) -> str:
    return settings.whatsapp_url or settings.telegram_url or settings.instagram_url or ""


def _personal_causes(personal_insight: dict[str, Any], limit: int = 4) -> list[str]:
    items = personal_insight.get("why_this_happens") if isinstance(personal_insight.get("why_this_happens"), list) else []
    result: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        bullet = _clean_text(item.get("short_protocol_bullet"))
        if not bullet:
            zone = _clean_text(item.get("zone"))
            visible = _clean_text(item.get("visible_sign"))
            mechanism = _clean_text(item.get("mechanism"))
            bullet = _clean_text(f"{zone}: {visible}. Причина: {mechanism}")
        if bullet:
            result.append(bullet)
    return result[:limit]


def _personal_strengths(personal_insight: dict[str, Any], limit: int = 4) -> list[str]:
    items = personal_insight.get("strengths_explained") if isinstance(personal_insight.get("strengths_explained"), list) else []
    result: list[str] = []
    for item in items:
        if isinstance(item, dict):
            bullet = _clean_text(item.get("short_protocol_bullet") or item.get("trait"))
        else:
            bullet = _clean_text(item)
        bullet = re.split(r"\s*:?\s*это\s+ресурс", bullet, maxsplit=1, flags=re.IGNORECASE)[0].strip(" .:;—–-")
        if bullet:
            result.append(bullet if bullet.endswith((".", "!", "?")) else bullet + ".")
    return result[:limit]


def report_view_model(report: GeneratedReport, settings: BotSettings) -> dict[str, Any]:
    analysis = report.analysis
    analysis_json = analysis.analysis_json if analysis and isinstance(analysis.analysis_json, dict) else {}
    protocol_copy = analysis.protocol_copy_json if analysis and isinstance(analysis.protocol_copy_json, dict) else {}
    personal_insight = analysis.personal_insight_json if analysis and isinstance(analysis.personal_insight_json, dict) else {}
    generated_report = report.report_json or {}

    skin_visual_age = analysis_json.get("skin_visual_age") if isinstance(analysis_json.get("skin_visual_age"), dict) else {}
    skin_copy = protocol_copy.get("skin_age") if isinstance(protocol_copy.get("skin_age"), dict) else {}
    skin_type = analysis_json.get("skin_type") if isinstance(analysis_json.get("skin_type"), dict) else {}
    skin_type_copy = protocol_copy.get("skin_type") if isinstance(protocol_copy.get("skin_type"), dict) else {}
    face_aging = analysis_json.get("face_type_and_aging_type") if isinstance(analysis_json.get("face_type_and_aging_type"), dict) else {}
    face_aging_copy = protocol_copy.get("face_aging") if isinstance(protocol_copy.get("face_aging"), dict) else {}
    morphotype_story = (
        personal_insight.get("morphotype_story")
        if isinstance(personal_insight.get("morphotype_story"), dict)
        else {}
    )
    forecast = analysis_json.get("time_forecast") if isinstance(analysis_json.get("time_forecast"), dict) else {}

    protocol_zones = protocol_copy.get("zones") if isinstance(protocol_copy.get("zones"), list) else []
    analysis_zones = analysis_json.get("zones") if isinstance(analysis_json.get("zones"), list) else []
    # Набор зон берём из ПРОТОКОЛА (те же зоны/порядок/статусы, что в PNG),
    # а тексты подтягиваем из analysis_json по номеру зоны (или по label).
    canonical_zones = protocol_zones or analysis_zones
    detail_by_num: dict[str, dict[str, Any]] = {}
    detail_by_label: dict[str, dict[str, Any]] = {}
    for raw_detail in analysis_zones:
        if not isinstance(raw_detail, dict):
            continue
        if raw_detail.get("number") is not None:
            detail_by_num[str(raw_detail.get("number"))] = raw_detail
        detail_label = _clean_text(raw_detail.get("name") or raw_detail.get("label")).lower()
        if detail_label:
            detail_by_label[detail_label] = raw_detail
    zones = []
    for index, raw_zone in enumerate(canonical_zones, start=1):
        if not isinstance(raw_zone, dict):
            continue
        number = raw_zone.get("number") or index
        label = _clean_text(raw_zone.get("name") or raw_zone.get("label"), f"Зона {index}")
        detail = detail_by_num.get(str(number)) or detail_by_label.get(label.lower()) or raw_zone
        status = _status(raw_zone.get("status") or raw_zone.get("color") or detail.get("status"), detail.get("color"))
        zones.append(
            {
                "number": number,
                "label": label,
                "status": status,
                "status_label": STATUS_LABELS[status],
                "short_comment": _clean_text(detail.get("short_comment"), STATUS_LABELS[status]),
                "reason": _clean_text(detail.get("reason"), "На состояние зоны могут влиять тонус мышц, лимфоток, осанка и мимические привычки."),
                "recommended_focus": _clean_text(detail.get("recommended_focus"), "Мягкая регулярная работа без перенапряжения."),
            }
        )

    seen_focus: set[str] = set()
    for zone in zones:
        focus_key = re.sub(r"\s+", " ", zone["recommended_focus"].lower()).strip()
        if focus_key and focus_key in seen_focus:
            zone["recommended_focus"] = ""
        else:
            seen_focus.add(focus_key)

    priority_zones = [zone["label"] for zone in zones if zone["status"] == "priority"] or [zone["label"] for zone in zones[:3]]
    strengths = _list(
        _personal_strengths(personal_insight),
        _list(protocol_copy.get("strengths"), _list(analysis_json.get("strengths"), ["Естественная выразительность лица."], 3), 3),
        3,
    )
    benefits = _list(
        protocol_copy.get("benefits"),
        _list(personal_insight.get("facefitness_strategy"), _list(analysis_json.get("facefitness_benefits"), ["Более свежий вид и мягкая поддержка овала лица."], 4), 4),
        4,
    )
    causes = _list(
        _personal_causes(personal_insight),
        _list(protocol_copy.get("causes"), _list(analysis_json.get("causes"), ["Тонус мышц, лимфоток, осанка и ежедневные привычки."], 4), 4),
        4,
    )
    forecast_items = _list(protocol_copy.get("forecast"), [], 3)
    if not forecast_items:
        forecast_items = [
            _clean_text(forecast.get("first_changes"), "7-14 дней: больше свежести."),
            _clean_text(forecast.get("visible_changes"), "4-6 недель: заметнее тонус и взгляд."),
            _clean_text(forecast.get("stable_result"), "8-12 недель: устойчивее овал."),
        ]

    user_name = generated_report.get("user_name") or (analysis.lead.name if analysis and analysis.lead else "Ваш протокол")
    protocol_path = analysis.face_protocol_image_path if analysis and analysis.face_protocol_version == "final_v1" else None
    if not protocol_path and analysis:
        protocol_path = analysis.protocol_image_path or analysis.legacy_protocol_image_path
    after_enabled = after_photo_feature_enabled()
    after_status = ((analysis.after_photo_status if analysis else None) or "PENDING") if after_enabled else "DISABLED"
    after_path = (analysis.after_photo_final_path or analysis.after_photo_path) if analysis and after_enabled else None
    after_state = "disabled" if not after_enabled else ("ready" if after_path and after_status in {"APPROVED", "COMPLETED"} else "pending")
    if after_enabled and after_status in {"FAILED", "SKIPPED_NO_API_KEY", "NEEDS_MANUAL_REVIEW"}:
        after_state = "failed" if after_status == "FAILED" else "skipped"
    after_messages = {
        "disabled": AFTER_PHOTO_DISABLED_REASON,
        "ready": "AI-визуализация готова.",
        "pending": "After-photo формируется отдельно и появится после генерации.",
        "failed": "After-photo не удалось сформировать. Основной протокол и отчет доступны.",
        "skipped": (
            "After-photo требует ручной проверки перед отправкой."
            if after_status == "NEEDS_MANUAL_REVIEW"
            else "After-photo временно недоступен без ключа генерации."
        ),
    }

    return {
        "token": report.public_token,
        "user": {
            "name": user_name,
            "source": "Telegram Bot" if analysis and analysis.telegram_user else "Bella Vladi",
        },
        "meta": {
            "analysis_date": generated_report.get("date") or (analysis.created_at.date().isoformat() if analysis and analysis.created_at else ""),
            "face_protocol_version": analysis.face_protocol_version if analysis else None,
            "status": analysis.status if analysis else None,
        },
        "summary": {
            "main_conclusion": _clean_text(
                protocol_copy.get("final_summary") or personal_insight.get("final_personal_summary") or personal_insight.get("main_hook") or analysis_json.get("summary"),
                "В лице уже есть сильная природная база.",
            ),
            "main_focus": _clean_text(
                personal_insight.get("main_visual_conflict") or generated_report.get("main_problem") or ", ".join(priority_zones),
                "Тонус и свежесть лица",
            ),
            "potential": _clean_text(
                personal_insight.get("main_leverage_point") or generated_report.get("main_potential") or ", ".join(strengths[:2]),
                "Снять напряжение и раскрыть природную красоту через систему",
            ),
            "priority_zones": priority_zones,
            "forecast_short": forecast_items[-1] if forecast_items else "8-12 недель: устойчивее овал.",
        },
        "skin_age": {
            "value": _skin_age_value(skin_visual_age, protocol_copy),
            "unit": _clean_text(skin_copy.get("unit"), "лет"),
            "estimated_range": _clean_text(skin_visual_age.get("estimated_range") or skin_copy.get("value"), "визуально свежий диапазон"),
            "score": _clean_text(skin_copy.get("score"), "78/100"),
            "score_percent": _score_percent(skin_copy.get("score")),
            "explanation": _clean_text(skin_copy.get("comment") or skin_visual_age.get("explanation"), "Кожа выглядит плотной и ухоженной; свежесть раскрывают взгляд и овал."),
            "improvement_potential": _clean_text(
                personal_insight.get("main_leverage_point") or analysis_json.get("cta_recommendation"),
                "Регулярная мягкая практика помогает поддержать свежесть, тонус и линию овала.",
            ),
        },
        "skin_type": {
            "title": _skin_type_title(skin_type_copy.get("title") or skin_type.get("type")),
            "features": _skin_type_items(skin_type_copy.get("title") or skin_type.get("type"), skin_type_copy.get("bullets") or skin_type.get("features")),
            "strengths": _skin_type_items(
                skin_type_copy.get("title") or skin_type.get("type"),
                skin_type.get("strengths"),
                ["Плотная ровная кожа — хороший актив лица.", "Кожа хорошо держит контур лица."],
                4,
            ),
            "attention_points": _list(skin_type.get("attention_points"), ["Зона глаз быстрее показывает недосып.", "Тонус нижней трети."], 4),
            "recommendations": _clean_text(generated_report.get("skin_recommendations"), "Мягкий лимфодренаж, регулярный уход и упражнения без перенапряжения."),
        },
        "face_aging": {
            "face_strengths": _clean_text(
                face_aging_copy.get("face_strengths") or face_aging_copy.get("face_type") or face_aging.get("face_type"),
                "Форма лица с хорошей скуловой опорой",
            ),
            "aging_type": _clean_text(face_aging_copy.get("aging_type") or morphotype_story.get("type") or face_aging.get("aging_type"), "Усталый / смешанный"),
            "explanation": _clean_text(
                morphotype_story.get("what_is_happening") or morphotype_story.get("why_this_type") or face_aging.get("explanation"),
                "Главный акцент — мягко снять напряжение, поддержать овал и открыть взгляд.",
            ),
            "forecast": _list(face_aging_copy.get("forecast"), [], 3),
            "strong_base": _clean_text(face_aging_copy.get("strong_base"), "Форма, скулы и пропорции — сильная природная база."),
            "bullets": _list(
                [
                    morphotype_story.get("why_this_type"),
                    morphotype_story.get("how_it_may_change"),
                    morphotype_story.get("strategy"),
                ],
                _list(face_aging_copy.get("bullets"), [], 3),
                3,
            ),
        },
        "zones": zones,
        "causes": {
            "intro": _clean_text(
                protocol_copy.get("why_intro") or morphotype_story.get("what_is_happening"),
                "Это не минус внешности, а логика видимых изменений: на свежесть влияют лимфа, мышцы, шея и тонус.",
            ),
            "items": causes,
            "outro": _clean_text(
                protocol_copy.get("why_outro") or morphotype_story.get("how_it_may_change"),
                "Если поддерживать отток, шею и тонус, лицо выглядит легче, свежее и собраннее.",
            ),
        },
        "strengths": strengths,
        "benefits": {
            "items": benefits,
            "outro": _clean_text(
                protocol_copy.get("benefits_outro"),
                "Свежий взгляд, ровный тон и собранный овал создают эффект естественного лифтинга.",
            ),
        },
        "forecast": [
            {"period": "Первые изменения", "text": forecast_items[0] if len(forecast_items) > 0 else "7-14 дней: больше свежести."},
            {"period": "Визуальный эффект", "text": forecast_items[1] if len(forecast_items) > 1 else "4-6 недель: заметнее тонус и взгляд."},
            {"period": "Устойчивость", "text": forecast_items[2] if len(forecast_items) > 2 else "8-12 недель: устойчивее овал."},
        ],
        "images": {
            "original_photo": _asset(analysis.original_photo_path if analysis else None),
            "face_protocol": _asset(protocol_path),
            "after_photo": _asset(after_path),
        },
        "after_photo": {
            "status": after_status,
            "state": after_state,
            "message": after_messages[after_state],
        },
        "cta": {
            "text": settings.cta_text or "Получить персональную программу",
            "url": _public_report_cta_url(settings),
        },
        "disclaimer": settings.disclaimer,
    }


def telegram_user_dict(user: TelegramUser | None) -> dict:
    if not user:
        return {}
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "current_status": user.current_status,
        "start_payload": user.start_payload,
        "created_at": user.created_at,
    }


def lead_dict(lead: Lead, include_analyses: bool = False) -> dict:
    latest = sorted(lead.analyses, key=lambda item: item.created_at, reverse=True)[0] if lead.analyses else None
    data = {
        "id": lead.id,
        "name": lead.name,
        "age": lead.age,
        "status": lead.status,
        "selected_problems": lead.selected_problems or [],
        "report_opened": lead.report_opened,
        "cta_clicked": lead.cta_clicked,
        "source": lead.source,
        "utm": lead.utm or {},
        "tags": lead.tags or [],
        "manager_comment": lead.manager_comment,
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
        "telegram_user": telegram_user_dict(lead.telegram_user),
        "latest_report_token": latest.report.public_token if latest and latest.report else None,
        "latest_analysis_id": latest.id if latest else None,
    }
    if include_analyses:
        data["analyses"] = [analysis_dict(item, compact=True) for item in sorted(lead.analyses, key=lambda x: x.created_at, reverse=True)]
        data["notes"] = [{"id": note.id, "text": note.text, "created_at": note.created_at} for note in lead.notes]
    return data


def analysis_dict(analysis: AnalysisRequest, compact: bool = False) -> dict:
    after_enabled = after_photo_feature_enabled()
    data = {
        "id": analysis.id,
        "status": analysis.status,
        "selected_problems": analysis.selected_problems or [],
        "original_photo_path": _media_url(analysis.original_photo_path),
        "protocol_image_path": _media_url(analysis.protocol_image_path),
        "protocol_image_url": analysis.protocol_image_url,
        "protocol_version": analysis.protocol_version,
        "protocol_slide_paths": [_media_url(path) for path in (analysis.protocol_slide_paths or []) if _media_url(path)],
        "protocol_slide_copy": analysis.protocol_slide_copy or {},
        "face_protocol_version": analysis.face_protocol_version,
        "face_protocol_image_path": _media_url(analysis.face_protocol_image_path),
        "protocol_copy_json": analysis.protocol_copy_json or {},
        "personal_insight_json": analysis.personal_insight_json or {},
        "legacy_protocol_image_path": _media_url(analysis.legacy_protocol_image_path),
        "legacy_protocol_image_url": analysis.legacy_protocol_image_url,
        "after_photo_path": _media_url(analysis.after_photo_path) if after_enabled else None,
        "after_photo_status": analysis.after_photo_status if after_enabled else "DISABLED",
        "after_photo_plan": analysis.after_photo_plan if after_enabled else {"disabled": True, "reason": AFTER_PHOTO_DISABLED_REASON},
        "after_photo_variants": (analysis.after_photo_variants or []) if after_enabled else [],
        "after_photo_variant_paths": [_media_url(path) for path in (analysis.after_photo_variant_paths or []) if _media_url(path)] if after_enabled else [],
        "after_photo_final_path": _media_url(analysis.after_photo_final_path) if after_enabled else None,
        "after_photo_quality_results": (analysis.after_photo_quality_results or []) if after_enabled else [],
        "after_photo_used_intensity": analysis.after_photo_used_intensity if after_enabled else None,
        "after_photo_retry_count": (analysis.after_photo_retry_count or 0) if after_enabled else 0,
        "final_after_photo_path": _media_url(analysis.after_photo_final_path or analysis.after_photo_path) if after_enabled else None,
        "moderation_status": analysis.moderation_status,
        "error_message": analysis.error_message,
        "created_at": analysis.created_at,
        "updated_at": analysis.updated_at,
        "completed_at": analysis.completed_at,
        "lead": {"id": analysis.lead.id, "name": analysis.lead.name} if analysis.lead else None,
        "telegram_user": telegram_user_dict(analysis.telegram_user),
        "report_token": analysis.report.public_token if analysis.report else None,
    }
    if not compact:
        data.update(
            {
                "analysis_json": analysis.analysis_json or {},
                "report_json": analysis.report_json or {},
                "zones": [
                    {
                        "number": zone.number,
                        "name": zone.name,
                        "status": zone.status,
                        "color": zone.color,
                        "short_comment": zone.short_comment,
                        "reason": zone.reason,
                        "recommended_focus": zone.recommended_focus,
                    }
                    for zone in analysis.zones
                ],
                "ai_logs": [
                    {
                        "id": log.id,
                        "stage": log.stage,
                        "status": log.status,
                        "message": log.message,
                        "created_at": log.created_at,
                        "payload": log.payload or {},
                    }
                    for log in sorted(analysis.ai_logs, key=lambda item: item.created_at, reverse=True)
                ],
                "images": [
                    {
                        "id": image.id,
                        "kind": image.kind,
                        "path": image.path,
                        "status": image.status,
                        "prompt": image.prompt,
                        "negative_prompt": image.negative_prompt,
                        "metadata_json": image.metadata_json or {},
                    }
                    for image in analysis.images
                ],
            }
        )
    return data


def report_public_dict(report: GeneratedReport, settings: BotSettings) -> dict:
    view_model = report_view_model(report, settings)
    analysis = report.analysis
    protocol_slides = []
    if analysis:
        zone_protocol = next(
            (
                image.path
                for image in sorted(analysis.images, key=lambda item: item.created_at or item.id, reverse=True)
                if image.kind == "face_zone_protocol" and image.status == "completed" and image.path
            ),
            None,
        )
        if analysis.face_protocol_version == "final_v1" and analysis.face_protocol_image_path:
            seen_protocols = set()
            protocol_slides = []
            for path in [zone_protocol or analysis.face_protocol_image_path, *(analysis.protocol_slide_paths or [])]:
                if path and path not in seen_protocols:
                    seen_protocols.add(path)
                    protocol_slides.append(_media_url(path) or path)
        elif analysis.protocol_version == "v4":
            protocol_slides = [_media_url(path) or path for path in (analysis.protocol_slide_paths or [])]
        else:
            protocol_slides = [_media_url(path) or path for path in (analysis.protocol_slide_paths or [])]
            image_slides = [
                _media_url(image.path) or image.path
                for image in sorted(analysis.images, key=lambda item: (item.metadata_json or {}).get("slide", item.id))
                if image.kind == "protocol_slide" and image.path
            ]
            protocol_slides = protocol_slides or image_slides
    protocol = protocol_slides[0] if protocol_slides else (
        _media_url(analysis.legacy_protocol_image_path) if analysis and analysis.protocol_version not in {"v2", "v3", "v4"} else None
    )
    return {
        "token": report.public_token,
        "view_model": view_model,
        "lead": {"name": view_model["user"]["name"]},
        "images": {
            "original": _media_url(analysis.original_photo_path) if analysis else None,
            "protocol": _media_url(analysis.face_protocol_image_path) if analysis and analysis.face_protocol_version == "final_v1" else protocol,
            "protocol_slides": protocol_slides,
            "protocol_version": analysis.face_protocol_version or analysis.protocol_version if analysis else None,
            "face_protocol": _media_url(analysis.face_protocol_image_path) if analysis else None,
            "face_protocol_version": analysis.face_protocol_version if analysis else None,
            "legacy_protocol": _media_url(analysis.legacy_protocol_image_path) if analysis else None,
            "after": _media_url(analysis.after_photo_final_path or analysis.after_photo_path) if analysis and after_photo_feature_enabled() else None,
        },
        "cta": {
            **view_model["cta"],
            "instagram_url": settings.instagram_url,
            "whatsapp_url": settings.whatsapp_url,
            "telegram_url": settings.telegram_url,
        },
        "disclaimer": view_model["disclaimer"],
    }


def document_dict(doc: KnowledgeDocument, include_chunks: bool = False) -> dict:
    data = {
        "id": doc.id,
        "title": doc.title,
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "is_active": doc.is_active,
        "chunk_count": len(doc.chunks),
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }
    if include_chunks:
        data["chunks"] = [
            {"id": chunk.id, "chunk_index": chunk.chunk_index, "content": chunk.content, "is_active": chunk.is_active}
            for chunk in doc.chunks
        ]
    return data


def prompt_dict(prompt: PromptTemplate) -> dict:
    return {
        "id": prompt.id,
        "key": prompt.key,
        "name": prompt.name,
        "content": prompt.content,
        "variables": prompt.variables or [],
        "is_active": prompt.is_active,
        "updated_at": prompt.updated_at,
    }


def settings_dict(settings: BotSettings, ai_key_status: dict | None = None) -> dict:
    return {
        "id": settings.id,
        "welcome_text": settings.welcome_text,
        "consent_text": settings.consent_text,
        "photo_instruction_text": settings.photo_instruction_text,
        "waiting_text": settings.waiting_text,
        "after_analysis_text": settings.after_analysis_text,
        "disclaimer": settings.disclaimer,
        "cta_text": settings.cta_text,
        "instagram_url": settings.instagram_url,
        "whatsapp_url": settings.whatsapp_url,
        "telegram_url": settings.telegram_url,
        "after_photo_enabled": False,
        "manual_moderation_enabled": settings.manual_moderation_enabled,
        "regeneration_enabled": settings.regeneration_enabled,
        "analysis_limit_per_user": settings.analysis_limit_per_user,
        "problem_catalog": settings.problem_catalog or [],
        "ai_settings": {**(settings.ai_settings or {}), "enable_after_photo": False},
        "ai_key_status": ai_key_status or {},
    }


def broadcast_dict(broadcast: Broadcast) -> dict:
    recipients = broadcast.recipients or []
    status_counts: dict[str, int] = {}
    for recipient in recipients:
        status_counts[recipient.status] = status_counts.get(recipient.status, 0) + 1
    return {
        "id": broadcast.id,
        "title": broadcast.title,
        "base_id": broadcast.base_id,
        "base": {"id": broadcast.base.id, "name": broadcast.base.name} if broadcast.base else None,
        "message_type": broadcast.message_type,
        "media_type": broadcast.media_type,
        "text": broadcast.message_text or broadcast.text,
        "message_text": broadcast.message_text or broadcast.text,
        "media_path": broadcast.media_path,
        "media_url": broadcast.media_url,
        "buttons": broadcast.buttons_json or broadcast.buttons or [],
        "buttons_json": broadcast.buttons_json or broadcast.buttons or [],
        "audience_filter": broadcast.audience_filter or {},
        "status": broadcast.status,
        "scheduled_at": broadcast.scheduled_at,
        "started_at": broadcast.started_at,
        "completed_at": broadcast.completed_at,
        "sent_at": broadcast.sent_at,
        "created_by": admin_dict(broadcast.created_by) if broadcast.created_by else None,
        "created_at": broadcast.created_at,
        "rate_limit_per_second": broadcast.rate_limit_per_second,
        "recipient_counts": status_counts,
        "recipients": [
            {
                "id": item.id,
                "telegram_user_id": item.telegram_user_id,
                "status": item.status,
                "error_message": item.error_message,
                "sent_at": item.sent_at or item.delivered_at,
                "telegram_message_id": item.telegram_message_id,
            }
            for item in recipients[:100]
        ],
    }


def campaign_dict(campaign: CampaignSource) -> dict:
    conversion = round((campaign.report_count / campaign.clicks) * 100, 2) if campaign.clicks else 0
    return {
        "id": campaign.id,
        "slug": campaign.slug,
        "title": campaign.title,
        "start_payload": campaign.start_payload,
        "url": campaign.url,
        "clicks": campaign.clicks,
        "photo_count": campaign.photo_count,
        "report_count": campaign.report_count,
        "cta_clicks": campaign.cta_clicks,
        "conversion": conversion,
        "is_active": campaign.is_active,
        "created_at": campaign.created_at,
    }


def admin_dict(admin: AdminUser) -> dict:
    return {
        "id": admin.id,
        "name": admin.name,
        "email": admin.email,
        "role": admin.role,
        "is_active": admin.is_active,
        "can_broadcast": admin.can_broadcast,
        "last_login_at": admin.last_login_at,
        "created_at": admin.created_at,
        "updated_at": admin.updated_at,
    }
