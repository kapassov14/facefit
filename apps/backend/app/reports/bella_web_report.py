from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.ai.aging_knowledge import (
    AGING_KNOWLEDGE as CLOSED_AGING_KNOWLEDGE,
    aging_mechanics,
    aging_public_label,
    aging_strategy,
    build_aging_type_block,
    normalize_aging_classification,
    sanitize_face_features_text,
)
from app.ai.protocol_v4 import build_aging_type_display_name, mixed_combo_type_ids_from_payload, normalize_protocol_v4_lengths, normalize_protocol_v4_shape
from app.api.serializers import report_view_model
from app.db.models import BotSettings, GeneratedReport
from app.reports.face_zone_protocol.mediapipe_map import detect_face_zone_geometry
from app.reports.face_zone_protocol.renderer import build_face_zone_protocol_data
from app.storage.local import local_storage


TEMPLATE_PATH = Path(__file__).resolve().parent / "bella_web_report.html"
logger = logging.getLogger(__name__)

FALLBACK_BEFORE = "Фото загружается"
FALLBACK_AFTER = "Результат генерируется"

ICON_SEQUENCE = ["spark", "eye", "leaf", "drop", "posture", "face"]
FACTOR_ICONS = ["drop", "flow", "muscle", "jaw", "neck", "posture", "moon", "bottle", "smile"]

WEB_REPORT_OBJECT_POSITION = "50% 42%"
WEB_MAP_OBJECT_POSITION = "50% 58%"
WEB_REPORT_VERSION = "bella_web_report_v5"
WEB_REPORT_REQUIRED_SECTIONS = (
    "intro",
    "visual_age",
    "skin_type",
    "strengths",
    "aging",
    "future",
    "age_changes",
    "zones",
    "strategy",
    "forecast",
    "final",
)
WEB_REPORT_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bAI[-\s]?(оценка|разбор|протокол|анализ)\b", "AI-формулировка"),
    (r"\bнейрон\w*\b", "нейронная формулировка"),
    (r"\bweb[-\s]?(протокол|report|отчет|отч[её]т)\b", "техническая web-формулировка"),
    (r"\bбаза знаний\b", "ссылка на базу знаний"),
    (r"\bстратеги[яию]\b", "слово «стратегия»"),
    (r"\bмаршрут\b", "слово «маршрут»"),
    (r"\bкомпонент\w*\b", "слово «компонент»"),
    (r"\bмеханизм\w*\b", "слово «механизм»"),
    (r"\bведущие механизмы\b", "нейтральная техническая фраза"),
    (r"\bдинамика лица\b", "техническая фраза"),
    (r"\bпастоз\w*\b", "слово «пастозность»"),
    (r"\bлимфодренаж\w*\b", "слово «лимфодренаж»"),
    (r"\bлимфоток\w*\b", "слово «лимфоток»"),
    (r"\bмикроциркуляц\w*\b", "слово «микроциркуляция»"),
    (r"\bдвижени[ея] жидкости\b", "тяжёлая формулировка про жидкость"),
    (r"\bтип лица\b", "запрещённая классификация лица"),
    (r"\bпроблем\w*\b", "слово «проблема»"),
)


def _clean(value: Any, fallback: str = "") -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\b[Пп]роблем(а|ы|у|ой|е|ами|ах)?\b", "зона внимания", text)
    text = re.sub(r"\b[Бб]рыли\b", "снижение чёткости овала", text)
    text = re.sub(r"\b[Мм]ешки под глазами\b", "отёчность в зоне глаз", text)
    text = re.sub(r"\b[Нн]ормальная кожа\b", "кожа с ровной плотной базой", text)
    text = re.sub(r"\b[Нн]ормаль\w+\b", "комбинированная с ровной плотной базой", text)
    text = re.sub(r"\b(\d+)\s+лета\b", r"\1 лет", text)
    text = text.replace("normal", "комбинированная с ровной плотной базой")
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        text = sanitize_face_features_text(text, text)
    return text or (sanitize_face_features_text(fallback, fallback) if fallback else "")


def _web_copy(value: Any, fallback: str = "") -> str:
    text = _clean(value, fallback)
    replacements = [
        (r"\bAI-оценка\b", "Визуальная оценка"),
        (r"\bAI-разбор\b", "визуальный разбор"),
        (r"\bКороткий вывод AI:\s*", "Короткий вывод: "),
        (r"\bweb-протоколе\b", "разборе"),
        (r"\bweb-report\b", "подробный разбор"),
        (r"\bиз базы знаний\b", ""),
        (r"\bведущие механизмы\b", "в основе"),
        (r"\bВедущие механизмы\b", "В основе"),
        (r"\bглавный механизм\b", "главное направление"),
        (r"\bосновному механизму\b", "главному направлению"),
        (r"\bмеханизм\b", "процесс"),
        (r"\bмикроциркуляци[яию]\b", "питание тканей"),
        (r"\bлимфодренаж\w*\b", "мягкая работа с отёчностью"),
        (r"\bлимфоток\w*\b", "движение жидкости в тканях"),
        (r"\bотток жидкости\b", "движение жидкости в тканях"),
        (r"\bоттока жидкости\b", "движения жидкости в тканях"),
        (r"\bоттоку жидкости\b", "движению жидкости в тканях"),
        (r"\bотток\w*\b", "движение жидкости"),
        (r"\bпастозность\b", "лёгкая припухлость"),
        (r"\bпастозности\b", "лёгкой припухлости"),
        (r"\bгипертонус\b", "стойкое мышечное напряжение"),
        (r"\bгипертонуса\b", "стойкого мышечного напряжения"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    cleanup = {
        "лёгкая лёгкая припухлость": "лёгкая припухлость",
        "легкая лёгкая припухлость": "лёгкая припухлость",
        "замедленном движение жидкости": "замедленном движении жидкости",
        "при увлажнении и мягкая работа с отёчностью": "при увлажнении и мягкой работе с отёчностью",
        "и мягкая работа с отёчностью лицо": "и мягкой работе с отёчностью лицо",
        "через свежесть взгляда, мягкая работа с отёчностью": "через свежесть взгляда, мягкую работу с отёчностью",
        "поддерживать шею, движение жидкости в тканях и тонус": "поддерживать шею, лёгкость тканей и тонус",
    }
    for source, target in cleanup.items():
        text = text.replace(source, target)
    text = re.sub(r"\s+([.,:;])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" .")
    return text


def _sentence_case(value: Any) -> str:
    text = _web_copy(value)
    return text[:1].upper() + text[1:] if text else ""


def _skin_age_sentence(value: Any, fallback: str) -> str:
    text = _web_copy(_first_sentence(value, fallback, 220))
    text = re.sub(r",?\s*[Вв]изуально\s*[—–-]\s*на\s*\d+\s*лет", "", text).strip(" ,.")
    return text or fallback


def _years_word(value: int) -> str:
    number = abs(int(value))
    if 11 <= number % 100 <= 14:
        return "лет"
    if number % 10 == 1:
        return "год"
    if 2 <= number % 10 <= 4:
        return "года"
    return "лет"


def _years_phrase(value: int) -> str:
    return f"{value} {_years_word(value)}"


def _web_visual_age(passport_age: int, suggested_visual_age: int | None, report_id: int | None = None) -> int:
    """For the web-report the client asked to show +2/+3 years from passport age."""
    target_delta = 2 + ((report_id or 0) % 2)
    if suggested_visual_age is not None:
        try:
            suggested = int(suggested_visual_age)
        except (TypeError, ValueError):
            suggested = passport_age + target_delta
        if 2 <= suggested - passport_age <= 3:
            return suggested
    return passport_age + target_delta


def _walk_strings(value: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, dict):
        result: list[tuple[str, str]] = []
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            result.extend(_walk_strings(item, next_path))
        return result
    if isinstance(value, list):
        result = []
        for index, item in enumerate(value):
            next_path = f"{path}[{index}]"
            result.extend(_walk_strings(item, next_path))
        return result
    return []


def _quality_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _quality_sentences(strings: list[tuple[str, str]]) -> dict[str, list[str]]:
    sentences: dict[str, list[str]] = {}
    for path, text in strings:
        for sentence in re.split(r"(?<=[.!?])\s+", _quality_text(text)):
            normalized = re.sub(r"[«»\"'(),:;—–-]+", " ", sentence.lower())
            normalized = re.sub(r"\s+", " ", normalized).strip(" .")
            if len(normalized) < 54:
                continue
            sentences.setdefault(normalized, []).append(path)
    return sentences


def _validate_web_report_v5(
    detailed: dict[str, Any],
    *,
    aging_id: str,
    mixed_components: list[str],
    visual_age: int,
    passport_age: int,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    missing = [key for key in WEB_REPORT_REQUIRED_SECTIONS if not isinstance(detailed.get(key), dict)]
    if missing:
        errors.append(f"missing_sections: {', '.join(missing)}")

    delta = visual_age - passport_age
    if delta not in {2, 3}:
        errors.append(f"visual_age_delta_must_be_2_or_3: passport={passport_age}, visual={visual_age}")

    strings = _walk_strings(detailed)
    combined = "\n".join(text for _, text in strings)
    for pattern, label in WEB_REPORT_FORBIDDEN_PATTERNS:
        for path, text in strings:
            if re.search(pattern, text, flags=re.IGNORECASE):
                errors.append(f"forbidden_phrase: {label} at {path}")
                break

    duplicate_sentences = [
        f"{sentence[:90]}... ({len(paths)}x)"
        for sentence, paths in _quality_sentences(strings).items()
        if len(paths) > 1
    ]
    if duplicate_sentences:
        errors.extend(f"duplicate_sentence: {item}" for item in duplicate_sentences[:5])

    if not re.search(r"\b(фейс-фитнес|курс|трениров\w*)\b", combined, flags=re.IGNORECASE):
        errors.append("missing_course_bridge")
    if not re.search(r"\b(моложе|свежее|красивее|сияющ\w*|выразительн\w*)\b", combined, flags=re.IGNORECASE):
        errors.append("missing_beauty_result_language")
    if aging_id == "tired_mixed" and len(mixed_components) >= 2:
        combo_names = [_component_name(component).lower() for component in mixed_components[:2]]
        combo_text = combined.lower()
        missed = [name for name in combo_names if name not in combo_text]
        if missed:
            errors.append(f"mixed_type_components_not_explained: {', '.join(missed)}")

    skin_text = " ".join(text for path, text in strings if path.startswith("skin_type")).lower()
    if skin_text and not re.search(r"(увлажн|уход|сия|ровн|напитан|glass|гладк)", skin_text):
        warnings.append("skin_block_weak_potential_language")

    zone_items = _dict(detailed.get("zones")).get("items")
    if isinstance(zone_items, list) and len(zone_items) > 6:
        warnings.append("zone_cards_more_than_6")

    return {
        "version": WEB_REPORT_VERSION,
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _web_report_source_trace(
    *,
    aging_id: str,
    aging_name: str,
    mixed_components: list[str],
    used_photo_zone_map: bool,
    visual_age: int,
    passport_age: int,
) -> dict[str, Any]:
    return {
        "version": WEB_REPORT_VERSION,
        "content_sources": [
            "short_protocol_ai_output",
            "photo_protocol_zone_map",
            "aging_knowledge_base",
        ],
        "aging_type": aging_id,
        "aging_type_name": aging_name,
        "mixed_components": mixed_components,
        "uses_photo_protocol_zone_map": used_photo_zone_map,
        "passport_age": passport_age,
        "visual_age": visual_age,
        "visual_age_rule": "passport_age_plus_2_or_3",
    }


def _zone_sentence_label(value: Any) -> str:
    text = _clean(value, "ключевая зона").strip(" .")
    if text.lower().startswith("зона "):
        return text[:1].lower() + text[1:]
    return text


def _list(value: Any, fallback: list[str] | None = None, limit: int | None = None) -> list[str]:
    source = value if isinstance(value, list) else []
    result = [_clean(item) for item in source if _clean(item)]
    if not result and fallback:
        result = fallback[:]
    return result[:limit] if limit else result


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d · %m · %Y")
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%d · %m · %Y")
        except Exception:
            pass
    text = _clean(value)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%d · %m · %Y")
        except ValueError:
            pass
    return text or datetime.now().strftime("%d · %m · %Y")


def _asset_url(path: str | None) -> str:
    if not path:
        return ""
    if path.startswith(("http://", "https://", "data:")):
        return path
    return f"/storage/{path.lstrip('/')}"


def _clamp_number(value: Any, fallback: int, minimum: int = 0, maximum: int = 100) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = fallback
    return max(minimum, min(maximum, number))


def _anchor(value: Any, fallback: dict[str, int]) -> dict[str, int]:
    data = value if isinstance(value, dict) else {}
    return {
        "x": _clamp_number(data.get("x"), fallback["x"]),
        "y": _clamp_number(data.get("y"), fallback["y"]),
    }


def _severity(value: Any, *, result: bool = False) -> str:
    if result:
        return "green"
    raw = _clean(value).lower()
    return raw if raw in {"green", "yellow", "orange", "red"} else "yellow"


def _priority(status: Any, color: Any = None) -> str:
    status_text = _clean(status).lower()
    color_text = _clean(color).lower()
    if status_text == "priority" or color_text == "red":
        return "high"
    if status_text == "good" or color_text == "green":
        return "low"
    return "medium"


def _short(value: Any, fallback: str, limit: int = 120) -> str:
    text = _clean(value, fallback)
    if len(text) <= limit:
        return text
    words: list[str] = []
    for word in text.split():
        candidate = " ".join([*words, word])
        if len(candidate) > limit:
            break
        words.append(word)
    return (" ".join(words) or text[:limit]).rstrip(" .,:;") + "."


def _phrase(value: Any, fallback: str) -> str:
    return _clean(value, fallback).rstrip(" .,:;—–-")


def _bella_protocol(report: GeneratedReport) -> dict[str, Any]:
    analysis = report.analysis
    analysis_json = analysis.analysis_json if analysis and isinstance(analysis.analysis_json, dict) else {}
    bella = analysis_json.get("bella_protocol")
    if isinstance(bella, dict):
        return bella
    if "point_a" in analysis_json and "point_c" in analysis_json:
        return analysis_json
    return {}


def _protocol_candidate_from_report(report: GeneratedReport) -> dict[str, Any]:
    analysis = report.analysis
    if not analysis:
        return {}
    analysis_json = analysis.analysis_json if isinstance(analysis.analysis_json, dict) else {}
    protocol_copy = analysis.protocol_copy_json if isinstance(analysis.protocol_copy_json, dict) else {}
    candidates = [
        _dict(protocol_copy.get("strict_blocks")),
        _dict(protocol_copy.get("bella_protocol_v4")),
        _dict(analysis_json.get("bella_protocol_v4")),
        _dict(analysis_json.get("strict_blocks")),
        _dict(analysis_json.get("bella_protocol")),
        analysis_json if analysis_json.get("protocol_version") == "bella_face_protocol_v4" else {},
    ]
    for candidate in candidates:
        if candidate and all(key in candidate for key in ("skin_visual_age", "skin_type", "face_strengths", "aging_type")):
            return candidate
    return candidates[0] if candidates else {}


def _current_protocol(report: GeneratedReport) -> dict[str, Any]:
    protocol = _protocol_candidate_from_report(report)
    if not protocol:
        return {}
    try:
        return normalize_protocol_v4_lengths(normalize_protocol_v4_shape(protocol))
    except Exception:
        return protocol


def _block(protocol: dict[str, Any], key: str) -> dict[str, Any]:
    return _dict(protocol.get(key))


def _block_text(protocol: dict[str, Any], key: str, fallback: str = "") -> str:
    block = _block(protocol, key)
    return _clean(block.get("text") or block.get("summary") or block.get("description"), fallback)


def _block_bullets(protocol: dict[str, Any], key: str, limit: int = 3) -> list[str]:
    block = _block(protocol, key)
    return _list(block.get("bullets"), [], limit)


def _protocol_zone_map(protocol: dict[str, Any]) -> dict[str, Any]:
    zone_map = _dict(protocol.get("zone_map"))
    raw_zones = zone_map.get("zones") if isinstance(zone_map.get("zones"), list) else []
    zones: list[dict[str, Any]] = []
    for index, raw in enumerate([item for item in raw_zones if isinstance(item, dict)][:6], start=1):
        title = _clean(raw.get("title") or raw.get("name") or raw.get("label"), f"Зона {index}")
        status = _severity(raw.get("status") or raw.get("color"))
        number = raw.get("number") or (raw.get("id") if isinstance(raw.get("id"), int) else index)
        try:
            number = int(number)
        except (TypeError, ValueError):
            number = index
        zone_id = raw.get("zone_id") or (raw.get("id") if not isinstance(raw.get("id"), int) else f"zone_{index}")
        anchor = raw.get("anchor") if isinstance(raw.get("anchor"), dict) else {}
        cx = raw.get("cx") if raw.get("cx") is not None else anchor.get("x")
        cy = raw.get("cy") if raw.get("cy") is not None else anchor.get("y")
        zones.append(
            {
                "id": number,
                "zone_id": _clean(zone_id, f"zone_{index}"),
                "number": number,
                "name": title,
                "title": title,
                "status": status,
                "meaning": _clean(raw.get("meaning") or raw.get("why_it_matters") or raw.get("description") or raw.get("what_is_visible")),
                "care_priority": _clean(raw.get("care_priority") or raw.get("what_to_do") or raw.get("recommended_focus") or raw.get("action")),
                "cx": cx if cx is not None else 50,
                "cy": cy if cy is not None else 30 + index * 7,
                "anchor": anchor or {"x": cx if cx is not None else 50, "y": cy if cy is not None else 30 + index * 7},
                "shape": raw.get("shape") or {},
            }
        )
    return {
        "title": _clean(zone_map.get("title"), "Карта зон лица"),
        "zones": zones,
        "contours": zone_map.get("contours") if isinstance(zone_map.get("contours"), dict) else {},
        "quality": zone_map.get("quality") if isinstance(zone_map.get("quality"), dict) else {},
        "mediapipe": zone_map.get("mediapipe") if isinstance(zone_map.get("mediapipe"), dict) else {},
    }


def _callout(raw: dict[str, Any], index: int, *, result: bool = False) -> dict[str, Any]:
    fallback_points = [
        {"x": 45, "y": 34},
        {"x": 58, "y": 39},
        {"x": 58, "y": 52},
        {"x": 55, "y": 72},
        {"x": 65, "y": 70},
        {"x": 50, "y": 45},
    ]
    fallback = fallback_points[index % len(fallback_points)]
    return {
        "title": _short(raw.get("title"), "Зона внимания", 42),
        "desc": _short(raw.get("description") or raw.get("desc"), "Мягкая зона для регулярной работы.", 74),
        "severity": _severity(raw.get("severity"), result=result),
        "anchor": _anchor(raw.get("anchor"), fallback),
    }


def _callouts_from_bella(point: dict[str, Any], *, result: bool = False) -> list[dict[str, Any]]:
    raw_items = point.get("face_callouts") if isinstance(point.get("face_callouts"), list) else []
    items = [_callout(item, index, result=result) for index, item in enumerate(raw_items[:6]) if isinstance(item, dict)]
    return items


def _callouts_from_zones(zones: list[dict[str, Any]], *, result: bool = False) -> list[dict[str, Any]]:
    result_items: list[dict[str, Any]] = []
    for index, zone in enumerate(zones[:6]):
        result_items.append(
            _callout(
                {
                    "title": zone.get("label"),
                    "description": zone.get("recommended_focus") if result else zone.get("short_comment"),
                    "severity": "green" if result else ("red" if zone.get("status") == "priority" else "yellow"),
                },
                index,
                result=result,
            )
        )
    return result_items


def _strict_text(protocol_copy: dict[str, Any], key: str, fallback: str = "") -> str:
    strict_blocks = _dict(protocol_copy.get("strict_blocks"))
    value = strict_blocks.get(key)
    if isinstance(value, dict):
        return _clean(value.get("text") or value.get("short_text"), fallback)
    return _clean(value, fallback)


def _rich_enough(value: Any, *, min_chars: int = 150) -> bool:
    return len(_clean(value)) >= min_chars


def _looks_like_old_copy(value: Any) -> bool:
    text = _clean(value).lower()
    markers = (
        "фейсфитнес для вашего типа — это прежде всего",
        "фейс-фитнес для вашего типа — это прежде всего раскрытие",
        "система bella vladi помогает идти к этому",
        "вы посмотрите в зеркало",
        "ваша красота — в балансе",
    )
    return any(marker in text for marker in markers)


def _strict_time_forecast(protocol_copy: dict[str, Any]) -> dict[str, Any]:
    strict_blocks = _dict(protocol_copy.get("strict_blocks"))
    forecast = strict_blocks.get("time_forecast") if isinstance(strict_blocks.get("time_forecast"), dict) else {}
    raw_items = forecast.get("items") if isinstance(forecast.get("items"), list) else []
    periods = ["Через 2 недели", "Через 3–4 недели", "Через 6–8 недель"]
    items: list[dict[str, str]] = []
    for index in range(3):
        raw_item = raw_items[index] if index < len(raw_items) else {}
        if isinstance(raw_item, dict):
            period = _clean(raw_item.get("period"), periods[index])
            value = _clean(raw_item.get("text") or raw_item.get("description"))
        else:
            text = _clean(raw_item)
            match = re.match(r"^(.+?)\s+[—–-]\s+(.+)$", text)
            if match:
                period = _clean(match.group(1), periods[index])
                value = _clean(match.group(2))
            else:
                period = periods[index]
                value = re.sub(r"^Через\s+[^—–-]+[—–-]\s*", "", text).strip()
        if value:
            items.append({"period": period, "text": value.rstrip(" .") + "."})
    return {
        "title": "Прогноз по времени",
        "basis": _clean(forecast.get("intro"), "Если ты начнёшь заниматься по нашей системе").rstrip(":"),
        "items": items,
    }


def _aging_type_id(value: Any) -> str:
    return normalize_aging_classification(value)["type_id"]


def _aging_report_info(value: Any) -> dict[str, Any]:
    classification = normalize_aging_classification(value)
    block = build_aging_type_block(classification)
    type_id = classification["type_id"]
    type_name = (
        _clean(value.get("display_name"))
        if isinstance(value, dict) and value.get("display_name")
        else _clean(value.get("type_name"))
        if isinstance(value, dict) and value.get("type_name")
        else classification["combined_label"] or classification["type_name"]
    )
    info = CLOSED_AGING_KNOWLEDGE[type_id]
    future = [
        f"Сейчас — сильнее считываются зоны, связанные с направлением: {aging_mechanics(classification)}.",
        "6–12 месяцев — без поддержки это направление может проявляться заметнее.",
        f"1–2 года — ключевые зоны могут сильнее влиять на выражение лица.",
        f"3–5 лет — регулярная система помогает визуально смягчать этот сценарий.",
    ]
    return {
        "type_name": type_name,
        "definition": block["characteristic"],
        "mechanics": aging_mechanics(classification),
        "not_dominant": ["произвольная классификация лица", "типы вне базы Bella Vladi"],
        "strategy": aging_strategy(classification),
        "future": future,
        "classification": classification,
        "block": block,
        "raw_info": info,
    }


def _skin_type_name(value: Any) -> str:
    text = _clean(value)
    lowered = text.lower()
    if not text or lowered in {"normal", "unknown", "none", "не определено", "визуально не определено"} or "норм" in lowered:
        return "Комбинированная кожа с ровной плотной базой"
    if "сух" in lowered or "обезвож" in lowered:
        return "Комбинированная, склонная к обезвоженности" if "комби" in lowered else "Сухая, склонная к обезвоженности"
    if "жир" in lowered or "t-зон" in lowered or "т-зон" in lowered:
        return "Комбинированная, активная в T-зоне"
    if "чувств" in lowered:
        return "Чувствительная, реактивная"
    if "комби" in lowered or "смеш" in lowered or "combination" in lowered:
        return "Комбинированная кожа с ровной плотной базой"
    return _short(text, "Комбинированная кожа с ровной плотной базой", 64)


def _face_type_name(value: Any) -> str:
    text = sanitize_face_features_text(_clean(value, "мягкий овал с природной базой"))
    lowered = text.lower()
    if "овал" in lowered:
        return "Мягкий овал и природная база"
    if "прям" in lowered:
        return "Выразительная природная форма"
    if "круг" in lowered:
        return "Мягкая округлая форма"
    if "серд" in lowered or "треуг" in lowered:
        return "Выразительная верхняя треть"
    return _short(text, "Мягкая природная форма", 54)


def _as_sentences(text: Any, fallback: str, limit: int = 3) -> list[str]:
    cleaned = _clean(text, fallback)
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    if not parts:
        parts = [fallback]
    result = []
    for part in parts:
        item = part.rstrip(" .") + "."
        if item not in result:
            result.append(item)
        if len(result) >= limit:
            break
    return result


def _first_sentence(text: Any, fallback: str, limit: int = 190) -> str:
    sentence = _as_sentences(text, fallback, 1)[0]
    return _short(sentence, fallback, limit).rstrip(" .") + "."


def _status_label(status: str) -> str:
    return {
        "strong": "Сильная зона",
        "attention": "Зона внимания",
        "active_focus": "Активный фокус",
        "priority": "Приоритет",
    }.get(status, "Зона внимания")


def _zone_status(status: Any) -> str:
    text = _clean(status).lower()
    if text in {"green", "good", "strong"}:
        return "strong"
    if text in {"red", "priority"}:
        return "priority"
    if text in {"orange", "active_focus"}:
        return "active_focus"
    return "attention"


def _zone_color(status: str) -> str:
    return {"strong": "green", "attention": "yellow", "active_focus": "orange", "priority": "red"}.get(status, "yellow")


def _zone_meaning(title: str, status: str) -> str:
    lower = title.lower()
    if "лоб" in lower or "межбров" in lower:
        return "Эта зона влияет на мягкость взгляда и выражения лица."
    if "глаз" in lower:
        return "Глаза первыми считывают свежесть, сон и напряжение шеи."
    if "щ" in lower or "сред" in lower:
        return "Средняя треть влияет на мягкость щек и глубину носогубной зоны."
    if "носогуб" in lower:
        return "Эта зона часто проявляется ярче, когда средняя треть выглядит тяжелее."
    if "подбор" in lower or "рот" in lower:
        return "Околоротовая зона отвечает за мягкость выражения и нижнюю треть."
    if "овал" in lower or "ниж" in lower:
        return "Овал дает ощущение лифтинга, собранности и ухоженности лица."
    if status == "strong":
        return "Это ресурс лица, на который можно опираться в работе."
    return "Зона помогает понять, с какой области лучше начинать работу."


def _zone_action(title: str) -> str:
    lower = title.lower()
    if "глаз" in lower:
        return "Начинать с шеи, зоны глаз и мягкого расслабления верхней трети."
    if "носогуб" in lower:
        return "Смягчать через среднюю треть, жевательную зону и питание тканей."
    if "овал" in lower or "ниж" in lower or "подбор" in lower:
        return "Сначала шея, затем мягкий тонус овала."
    if "лоб" in lower or "межбров" in lower:
        return "Работать через расслабление, дыхание и мягкое раскрытие взгляда."
    return "Работать мягко и последовательно, без перегруза зоны."


def _client_age(report: GeneratedReport) -> int:
    analysis = report.analysis
    if analysis and analysis.lead and analysis.lead.age:
        return int(analysis.lead.age)
    return 30


def _image_url_from_analysis(report: GeneratedReport, path: str | None) -> str:
    if not path:
        return ""
    return _asset_url(path)


def _focus_start_phrase(focus: str) -> str:
    text = _clean(focus).strip(" .")
    replacements = [
        (r"\bзона глаз\b", "зоны глаз"),
        (r"\bносогубная зона\b", "носогубной зоны"),
        (r"\bсредняя треть\b", "средней трети"),
        (r"\bнижняя треть\b", "нижней трети"),
        (r"\bшея\b", "шеи"),
        (r"\bовал\b", "овала"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text or "зоны глаз, шеи и овала"


def _zone_geometry(report: GeneratedReport) -> dict[str, Any]:
    analysis = report.analysis
    if not analysis or not analysis.original_photo_path:
        return {}
    try:
        return detect_face_zone_geometry(local_storage.abs_path(analysis.original_photo_path), object_position=WEB_MAP_OBJECT_POSITION)
    except Exception:
        return {}


def _journal_data(report: GeneratedReport, before_url: str, geometry: dict[str, Any]) -> dict[str, Any]:
    analysis = report.analysis
    if not analysis:
        return {}
    return build_face_zone_protocol_data(
        analysis_request_id=str(analysis.id),
        user_name=analysis.lead.name if analysis.lead and analysis.lead.name else "Гость",
        face_image_url=before_url,
        analysis_json=analysis.analysis_json or {},
        protocol_copy=analysis.protocol_copy_json or {},
        personal_insight_json=analysis.personal_insight_json or {},
        created_at=analysis.created_at,
        zone_geometry=geometry or {},
    )


def _type_specific_web_route(aging_id: str) -> dict[str, Any]:
    routes: dict[str, dict[str, Any]] = {
        "muscular": {
            "results": [
                "взгляд может стать мягче после расслабления лба и межбровья",
                "жевательная зона может меньше утяжелять выражение",
                "мимика выглядит спокойнее без потери четкого каркаса",
                "лицо легче сохраняет мягкость в покое",
            ],
            "steps": [
                {"stage": "Этап 1", "title": "Отпустить гипертонус", "goal": "смягчить лоб, межбровье и жевательные", "zones": ["лоб", "межбровье", "жевательные"], "possible_effect": "выражение может стать спокойнее"},
                {"stage": "Этап 2", "title": "Раскрыть взгляд", "goal": "снизить лишнюю работу верхней трети", "zones": ["круговая мышца глаза", "лоб"], "possible_effect": "взгляд может выглядеть мягче"},
                {"stage": "Этап 3", "title": "Вернуть баланс", "goal": "подключить тонус после расслабления", "zones": ["скулы", "овал"], "possible_effect": "черты сохраняют четкость без жесткости"},
                {"stage": "Этап 4", "title": "Закрепить мягкость", "goal": "сделать расслабление ежедневной привычкой", "zones": ["мимика", "дыхание"], "possible_effect": "лицо легче остается расслабленным"},
            ],
        },
        "deformation_edema": {
            "results": [
                "утром лицо может выглядеть легче и спокойнее",
                "нижняя треть может стать визуально легче",
                "овал и скулы читаются собраннее при регулярной работе",
                "шея и осанка помогают поддерживать легкость лица",
            ],
            "steps": [
                {"stage": "Этап 1", "title": "Сделать лицо легче утром", "goal": "поддержать шею, ключицы и зону глаз", "zones": ["шея", "ключицы", "зона глаз"], "possible_effect": "лицо может выглядеть легче утром"},
                {"stage": "Этап 2", "title": "Поддержать осанку", "goal": "снять зажимы, которые усиливают тяжесть нижней трети", "zones": ["шея", "осанка"], "possible_effect": "овал выглядит собраннее"},
                {"stage": "Этап 3", "title": "Собрать нижнюю треть", "goal": "подключить мягкий тонус после работы с отёчностью", "zones": ["нижняя треть", "овал"], "possible_effect": "контур может стать четче"},
                {"stage": "Этап 4", "title": "Закрепить легкость", "goal": "сохранить регулярность и чистую линию овала", "zones": ["шея", "овал"], "possible_effect": "свежесть держится стабильнее"},
            ],
        },
        "fine_wrinkle": {
            "results": [
                "кожа может выглядеть более напитанной и живой",
                "мелкая сетка визуально смягчается при регулярном уходе",
                "зона глаз получает больше мягкой поддержки",
                "текстура выглядит ровнее без агрессивной нагрузки",
            ],
            "steps": [
                {"stage": "Этап 1", "title": "Поддержать увлажнение", "goal": "дать коже мягкость и восстановление", "zones": ["кожа", "зона глаз"], "possible_effect": "текстура может выглядеть ровнее"},
                {"stage": "Этап 2", "title": "Поддержать питание кожи", "goal": "мягко включить питание тканей", "zones": ["щеки", "лоб", "зона глаз"], "possible_effect": "тон кожи может стать живее"},
                {"stage": "Этап 3", "title": "Дать бережный тонус", "goal": "поддержать мышечную опору без перегруза", "zones": ["скулы", "овал"], "possible_effect": "лицо выглядит более собранным"},
                {"stage": "Этап 4", "title": "Закрепить питание", "goal": "сделать уход регулярным и мягким", "zones": ["увлажнение", "питание тканей"], "possible_effect": "кожа дольше сохраняет свежесть"},
            ],
        },
        "tired_mixed": {
            "results": [
                "взгляд может выглядеть свежее и мягче",
                "носогубная зона может стать визуально спокойнее",
                "уголки рта и средняя треть выглядят живее",
                "лицо легче сохраняет свежесть к вечеру",
            ],
            "steps": [
                {"stage": "Этап 1", "title": "Вернуть свежесть", "goal": "поддержать питание тканей и убрать ощущение усталости", "zones": ["зона глаз", "шея"], "possible_effect": "взгляд может стать свежее"},
                {"stage": "Этап 2", "title": "Смягчить среднюю треть", "goal": "снизить усталое впечатление в носогубной зоне", "zones": ["носогубная зона", "щеки"], "possible_effect": "лицо выглядит мягче"},
                {"stage": "Этап 3", "title": "Поддержать уголки", "goal": "вернуть мягкий тонус нижней части лица", "zones": ["уголки рта", "околоротовая зона"], "possible_effect": "выражение выглядит живее"},
                {"stage": "Этап 4", "title": "Закрепить тонус", "goal": "сохранить свежесть и регулярность", "zones": ["питание тканей", "тонус"], "possible_effect": "лицо меньше выглядит уставшим"},
            ],
        },
    }
    return routes.get(aging_id, routes["tired_mixed"])


def _sentences(value: Any, limit: int = 3) -> list[str]:
    text = _clean(value)
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n{2,}", text) if part.strip()]
    result: list[str] = []
    for part in parts:
        sentence = part.rstrip(" .") + "."
        if sentence not in result:
            result.append(sentence)
        if len(result) >= limit:
            break
    return result


def _paragraphs(*values: Any, limit: int | None = None) -> list[str]:
    result: list[str] = []
    for value in values:
        for paragraph in str(value or "").split("\n\n"):
            cleaned = _clean(paragraph)
            if cleaned and cleaned not in result:
                result.append(cleaned.rstrip(" .") + ".")
            if limit and len(result) >= limit:
                return result
    return result


def _human_join(items: list[str], fallback: str = "ключевые зоны лица") -> str:
    cleaned = [_clean(item) for item in items if _clean(item)]
    if not cleaned:
        return fallback
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} и {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f" и {cleaned[-1]}"


def _strength_titles_from_protocol(protocol: dict[str, Any], limit: int = 3) -> list[str]:
    titles: list[str] = []
    for item in _block_bullets(protocol, "face_strengths", limit):
        title = _clean(item.split("—", 1)[0].split(":", 1)[0], "")
        if title and title not in titles:
            titles.append(title)
    return titles[:limit]


def _hero_conclusion_from_strengths(protocol: dict[str, Any], strengths_short: str) -> str:
    strengths = _block(protocol, "face_strengths")
    detail = _first_sentence(
        strengths.get("text"),
        "гармоничные черты, аккуратный овал и спокойные пропорции уже создают красивое впечатление",
        170,
    )
    detail = re.sub(r"^[Уу]\s+(?:вас|тебя)\s+", "", detail.rstrip(" .")).strip()
    detail = detail[:1].lower() + detail[1:] if detail else "гармоничные черты уже создают красивое впечатление"
    intro = (
        f"У вас {detail}"
        if re.search(r"нежн\w*.*молод|молод\w*.*нежн", detail.lower())
        else f"У вас очень нежное, молодое лицо: {detail}"
    )
    return (
        f"{intro}. Этот разбор показывает ваш путь: как выглядеть ещё красивее, свежее и моложе, "
        f"сохраняя и подчёркивая ваши природные сильные стороны — {strengths_short.lower()}."
    )


def _zone_titles(zone_map: dict[str, Any], *, statuses: set[str] | None = None, limit: int = 4) -> list[str]:
    zones = zone_map.get("zones") if isinstance(zone_map.get("zones"), list) else []
    result: list[str] = []
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        status = _clean(zone.get("status")).lower()
        if statuses and status not in statuses:
            continue
        title = _clean(zone.get("title"))
        if title and title not in result:
            result.append(title)
        if len(result) >= limit:
            break
    return result


def _kb_for_component(component_id: str) -> dict[str, str]:
    if component_id == "tired":
        return CLOSED_AGING_KNOWLEDGE["tired_mixed"]
    return CLOSED_AGING_KNOWLEDGE.get(component_id, CLOSED_AGING_KNOWLEDGE["tired_mixed"])


def _component_name(component_id: str) -> str:
    return {
        "tired": "Усталый",
        "muscular": "Мускульный",
        "deformation_edema": "Деформационно-отечный",
        "fine_wrinkle": "Мелкоморщинистый",
    }.get(component_id, component_id)


def _combo_type_phrase(mixed_components: list[str]) -> str:
    adjectives = {
        "tired": "усталого",
        "tired_mixed": "усталого",
        "muscular": "мускульного",
        "deformation_edema": "деформационно-отечного",
        "fine_wrinkle": "мелкоморщинистого",
    }
    parts = [adjectives.get(component, _component_name(component).lower()) for component in mixed_components[:2]]
    if len(parts) >= 2:
        return f"{parts[0]} и {parts[1]} типов"
    return "смешанного типа"


def _combo_scenario_phrase(mixed_components: list[str]) -> str:
    adjectives = {
        "tired": "усталого",
        "tired_mixed": "усталого",
        "muscular": "мускульного",
        "deformation_edema": "деформационно-отечного",
        "fine_wrinkle": "мелкоморщинистого",
    }
    parts = [adjectives.get(component, _component_name(component).lower()) for component in mixed_components[:2]]
    if len(parts) >= 2:
        return f"{parts[0]} и {parts[1]} сценариев"
    return "смешанного сценария"


def _web_combo_chapters(aging_id: str, mixed_components: list[str]) -> list[dict[str, str]]:
    if aging_id != "tired_mixed" or len(mixed_components) < 2:
        return []
    chapters: list[dict[str, str]] = []
    for component_id in mixed_components[:2]:
        chapters.append(
            {
                "title": _component_name(component_id),
                "text": _component_web_summary(component_id),
            }
        )
    return chapters


def _component_web_summary(component_id: str) -> str:
    return {
        "tired": (
            "Усталый тип чаще проявляется через зону глаз, носослёзную линию, носогубную зону "
            "и уголки рта: лицо быстрее показывает усталость к вечеру, даже если черты сами по себе гармоничные."
        ),
        "tired_mixed": (
            "Усталый тип чаще проявляется через зону глаз, носослёзную линию, носогубную зону "
            "и уголки рта: лицо быстрее показывает усталость к вечеру, даже если черты сами по себе гармоничные."
        ),
        "deformation_edema": (
            "Деформационно-отечный тип связан с утренней припухлостью, зоной глаз, шеей и нижней третью. "
            "Главная задача — помогать лицу выглядеть легче и сохранять чистую линию овала."
        ),
        "muscular": (
            "Мускульный тип связан с напряжением лба, межбровья и жевательной зоны. "
            "Когда эти зоны становятся мягче, лицо выглядит спокойнее и моложе без потери выразительности."
        ),
        "fine_wrinkle": (
            "Мелкоморщинистый тип связан с сухостью, тонкостью кожи и ранней мелкой сеткой. "
            "Здесь особенно важны увлажнение, питание тканей и бережная работа без перегруза."
        ),
    }.get(component_id, _web_copy(_kb_for_component(component_id).get("characteristic")))


def _public_type_focus(aging_id: str, mixed_components: list[str]) -> str:
    if aging_id == "tired_mixed" and len(mixed_components) >= 2:
        return f"сочетание {_combo_scenario_phrase(mixed_components)}, зона глаз, свежесть лица и поддержка овала"
    return {
        "muscular": "смягчение напряжения в лбу, межбровье и жевательной зоне",
        "deformation_edema": "лёгкость лица утром, зона глаз, шея и поддержка чёткого овала",
        "fine_wrinkle": "качество кожи, увлажнение, питание тканей и бережная работа с зоной глаз",
        "tired_mixed": "свежесть взгляда, носогубная зона, уголки рта и спокойное выражение лица",
    }.get(aging_id, "свежесть лица и поддержка природных сильных сторон")


def _web_aging_text(
    aging_id: str,
    aging_name: str,
    mixed_components: list[str],
    kb: dict[str, str],
    aging: dict[str, Any],
) -> list[str]:
    if aging_id == "tired_mixed" and len(mixed_components) >= 2:
        return [
            (
                f"Ваш сценарий — сочетание {_combo_scenario_phrase(mixed_components)}. Это не новый отдельный тип, "
                "а комбинация двух процессов, поэтому лицо важно читать по зонам: где быстрее появляется усталость, "
                "а где нужна поддержка чёткости и свежести."
            ),
            " ".join(_component_web_summary(component) for component in mixed_components[:2]),
        ]
    return [
        f"Ваш тип старения — {aging_name}. {_web_copy(kb.get('characteristic') or aging.get('text'))}.",
        _web_copy(kb.get("what_inside")),
    ]


def _web_aging_chapters(
    aging_id: str,
    mixed_components: list[str],
    kb: dict[str, str],
    public_type_focus: str,
) -> list[dict[str, str]]:
    chapters = [
        {"title": "Что это значит для вас", "text": _web_copy(kb.get("what_inside") or kb.get("characteristic"))},
        {"title": "Как это может проявляться", "text": _web_copy(kb.get("how_changes_over_time"))},
        {"title": "На что обратить внимание", "text": public_type_focus},
    ]
    if aging_id == "tired_mixed" and len(mixed_components) >= 2:
        chapters = [
            *(_web_combo_chapters(aging_id, mixed_components)),
            {"title": "Главный ориентир", "text": _sentence_case(public_type_focus)},
        ]
    return chapters


def _web_route_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for step in steps:
        result.append(
            {
                **step,
                "goal": _web_copy(step.get("goal")),
                "possible_effect": _web_copy(step.get("possible_effect")),
                "zones": [_web_copy(zone) for zone in step.get("zones", [])],
            }
        )
    return result


def _web_zone_detail(zone: dict[str, Any], aging_name: str, type_focus: str) -> dict[str, Any]:
    title = _clean(zone.get("title"), "Зона лица")
    status = _clean(zone.get("status"), "yellow")
    meaning = _clean(zone.get("meaning"))
    care = _clean(zone.get("care_priority"))
    if not meaning:
        meaning = _zone_meaning(title, _zone_status(status))
    if not care:
        care = _zone_action(title)
    return {
        "number": zone.get("number"),
        "title": title,
        "status": status,
        "status_label": statusLabelFromColor(status),
        "meaning": _web_copy(meaning),
        "analysis": (
            f"В подробном разборе эта зона оценивается в связке с типом старения «{aging_name}». "
            f"Она показывает, где лицу важнее всего поддержка: {type_focus}."
        ),
        "action": _web_copy(care),
        "anchor": zone.get("anchor") or {"x": 50, "y": 50},
        "shape": zone.get("shape") or {},
    }


def _plain_component_text(component_id: str) -> str:
    return {
        "tired": (
            "от усталого типа чаще заметны зона под глазами, носослёзная линия, носогубная зона "
            "и уголки рта. Лицо может выглядеть свежим утром, но быстрее уставать к вечеру."
        ),
        "tired_mixed": (
            "от усталого типа чаще заметны зона под глазами, носослёзная линия, носогубная зона "
            "и уголки рта. Лицо может выглядеть свежим утром, но быстрее уставать к вечеру."
        ),
        "deformation_edema": (
            "от деформационно-отечного типа есть склонность к утренней припухлости, мягкости тканей "
            "и постепенному утяжелению нижней трети."
        ),
        "muscular": (
            "от мускульного типа лоб, межбровье и жевательная зона могут держать напряжение. "
            "Из-за этого лицо выглядит строже, даже когда вы расслаблены."
        ),
        "fine_wrinkle": (
            "от мелкоморщинистого типа кожа быстрее просит увлажнения и питания. "
            "Мелкая сетка может появляться раньше, зато контур лица часто долго остается аккуратным."
        ),
    }.get(component_id, "лицу важна мягкая регулярная работа без перегруза.")


def _skin_plain_blocks(skin_type_name: str, skin_type: dict[str, Any]) -> dict[str, Any]:
    source = _web_copy(skin_type.get("text"))
    lowered = f"{skin_type_name} {source}".lower()
    if "обезвож" in lowered or "сух" in lowered:
        tendency = "ей важно регулярное увлажнение, мягкое очищение и уход без пересушивания"
        avoid = "не пересушивать кожу активными средствами и не перегружать её частыми экспериментами"
        potential = "при правильном уходе кожа может стать более ровной, напитанной и сияющей"
    elif "t-зон" in lowered or "т-зон" in lowered or "жир" in lowered:
        tendency = "центральная зона может быстрее давать блеск, а щеки при этом оставаться спокойнее"
        avoid = "не пытаться полностью обезжирить кожу: так она может выглядеть суше и менее живой"
        potential = "при балансе увлажнения и мягкого ухода тон выглядит ровнее, а лицо свежее"
    elif "чувств" in lowered:
        tendency = "ей нужен спокойный уход без агрессивных средств и резких смен косметики"
        avoid = "не перегружать кожу активами и не делать уход слишком сложным"
        potential = "при бережном подходе кожа выглядит ровнее, мягче и спокойнее"
    else:
        tendency = "она хорошо держит форму лица и обычно благодарно отвечает на регулярный уход"
        avoid = "не запускать увлажнение и не перегружать кожу агрессивными средствами"
        potential = "при грамотном уходе можно получить более ровный тон, сияние и эффект ухоженной кожи"
    return {
        "text": [
            f"У вас {skin_type_name.lower()}. {source or 'По фото кожа выглядит аккуратной, ровной и ухоженной.'}",
            f"Главное для такой кожи: {tendency}. Тогда она выглядит мягкой, послушной и более сияющей.",
            f"Потенциал хороший: {potential}. Это как раз тот самый эффект свежей, гладкой кожи, к которому обычно стремятся уходом.",
        ],
        "bullets": [
            f"Склонность: {tendency}.",
            f"Чего избегать: {avoid}.",
            f"Потенциал: {potential}.",
        ],
    }


def _age_plain_blocks(visual_age: int, passport_age: int, zone_focus: str, skin_age: dict[str, Any]) -> dict[str, Any]:
    delta = visual_age - passport_age
    if delta >= 3:
        relation = "чуть старше паспортного возраста"
        reason = f"это чаще связано не с самой кожей, а с зонами, которые дают усталый вид: {zone_focus}"
    elif delta <= -3:
        relation = "моложе паспортного возраста"
        reason = "это хороший ресурс: лицо выглядит свежим, а кожа и черты дают мягкое молодое впечатление"
    else:
        relation = "примерно на свой возраст"
        reason = f"сейчас важнее всего поддерживать зоны, которые могут добавлять усталость: {zone_focus}"
    short = _skin_age_sentence(skin_age.get("text"), "кожа выглядит ухоженной и свежей")
    return {
        "text": [
            f"По фото кожа выглядит примерно на {visual_age} лет — {relation}.",
            f"{reason.capitalize()}. {short}.",
            "Хорошая новость: сейчас это выглядит как этап, когда можно не исправлять выраженные изменения, а заранее поддержать лицо и выглядеть заметно свежее.",
        ],
        "notes": [
            "что добавляет возраст: усталость взгляда, напряжение или мягкость отдельных зон",
            "что помогает: регулярность, уход и мягкая работа с лицом",
            "цель: выглядеть свежее, моложе и спокойнее, не меняя свои черты",
        ],
    }


def _aging_plain_blocks(
    aging_id: str,
    aging_name: str,
    mixed_components: list[str],
    kb: dict[str, str],
    priority_zones: list[str],
) -> dict[str, Any]:
    zones = _human_join(priority_zones[:3], "зона глаз и нижняя треть")
    if aging_id == "tired_mixed" and len(mixed_components) >= 2:
        return {
            "intro": f"У вас сочетание {_combo_type_phrase(mixed_components)}.",
            "text": [
                (
                    f"Это комбинированный вариант: в лице сочетаются признаки {_combo_type_phrase(mixed_components)}. "
                    f"По фото особенно стоит смотреть на {zones}."
                ),
                (
                    "Такой тип важно поддерживать сразу по нескольким зонам: тогда лицо выглядит свежее, "
                    "взгляд раскрывается, а природные сильные стороны читаются мягче и красивее."
                ),
            ],
            "chapters": [
                {"title": _component_name(component), "text": _plain_component_text(component)[:1].upper() + _plain_component_text(component)[1:]}
                for component in mixed_components[:2]
            ],
        }
    plain_by_type = {
        "muscular": [
            "У вас мускульный тип старения: отдельные мышцы лица могут долго находиться в напряжении, особенно лоб, межбровье и жевательная зона.",
            "Из-за этого лицо может выглядеть более строгим или уставшим, даже если вы расслаблены. Зато овал часто долго остается четким.",
            "Фейс-фитнес здесь нужен прежде всего для расслабления зажимов: так взгляд становится мягче, а черты выглядят моложе и спокойнее.",
        ],
        "deformation_edema": [
            "У вас деформационно-отечный тип: лицо может быть склонно к утренней припухлости, мягкости тканей и постепенной потере четкости овала.",
            "Главные зоны внимания — шея, зона под глазами и нижняя треть. Если их поддерживать, лицо выглядит легче и свежее.",
            "Фейс-фитнес здесь помогает не менять черты, а удерживать красивую линию лица, свежий взгляд и более собранный контур.",
        ],
        "fine_wrinkle": [
            "У вас мелкоморщинистый тип: кожа быстрее просит увлажнения, питания и бережного отношения.",
            "Такой тип часто долго сохраняет аккуратный контур, но может раньше показывать сухость, мелкую сетку и усталость кожи.",
            "Фейс-фитнес здесь нужен мягкий: чтобы кожа выглядела более живой, напитанной и свежей без перегруза.",
        ],
        "tired_mixed": [
            "У вас усталый / смешанный тип: лицо может выглядеть свежим утром, но быстрее уставать к вечеру.",
            "Чаще всего это проявляется через зону под глазами, носогубную зону, уголки рта и общее снижение свежести.",
            "Фейс-фитнес помогает вернуть лицу отдохнувший вид, раскрыть взгляд и поддержать мягкий тонус.",
        ],
    }
    text = plain_by_type.get(aging_id, plain_by_type["tired_mixed"])
    return {
        "intro": f"Ваш тип: {aging_name}.",
        "text": [
            (
                f"Ваш тип старения — {aging_name}. Ниже простым языком: что происходит с лицом, "
                "как это может проявляться и почему регулярная работа помогает выглядеть свежее."
            ),
            f"По фото особенно важно поддерживать {zones}: это поможет раскрыть сильные стороны лица без изменения ваших черт.",
        ],
        "chapters": [
            {"title": "Характеристика типа", "text": text[0]},
            {"title": "Как это видно на лице", "text": text[1]},
            {"title": "Почему важно заниматься", "text": text[2]},
        ],
    }


def _future_plain_blocks(
    aging_id: str,
    mixed_components: list[str],
    zone_focus: str,
    age_changes: dict[str, Any],
    future: dict[str, Any],
) -> list[str]:
    ai_text = _web_copy(future.get("text"))
    age_text = _web_copy(age_changes.get("text"))
    if aging_id == "tired_mixed" and len(mixed_components) >= 2:
        base = (
            f"Если не поддерживать лицо, зоны «{zone_focus}» могут постепенно сильнее давать усталый вид: "
            "взгляд выглядит менее свежим, носогубная зона становится заметнее, а нижняя треть — мягче."
        )
        age_line = (
            "В 25–30 лет обычно первыми заметны усталость под глазами и снижение сияния к вечеру. "
            "В 30–35 лет активнее проявляются носослёзная зона, носогубка и мягкость нижней трети."
        )
    else:
        base = {
            "muscular": (
                "Если не работать с напряжением, межбровье, лоб и жевательная зона могут фиксироваться сильнее. "
                "Лицо выглядит строже и старше, даже когда вы спокойны."
            ),
            "deformation_edema": (
                "Если не поддерживать шею и нижнюю треть, лицо может чаще выглядеть припухшим утром, "
                "а овал со временем становится менее четким."
            ),
            "fine_wrinkle": (
                "Если не поддерживать кожу и мышцы, лицо может быстрее терять свежесть: кожа выглядит суше, "
                "а мелкая сетка становится заметнее."
            ),
            "tired_mixed": (
                "Если не поддерживать лицо, зона глаз, носогубка и уголки рта могут сильнее давать усталый вид. "
                "Лицо выглядит менее отдохнувшим, особенно к вечеру."
            ),
        }.get(aging_id, "")
        age_line = {
            "muscular": (
                "В 25–30 лет обычно заметнее становятся мимические линии лба и межбровья. "
                "После 30 лет напряжение может сильнее влиять на взгляд и выражение лица."
            ),
            "deformation_edema": (
                "В 25–30 лет чаще заметна утренняя припухлость и усталость под глазами. "
                "После 30 лет нижняя треть может становиться мягче, если не поддерживать шею и овал."
            ),
            "fine_wrinkle": (
                "В 25–30 лет кожа может быстрее показывать сухость и мелкую сетку. "
                "После 30 лет без увлажнения и мягкой работы лицо может выглядеть более уставшим."
            ),
            "tired_mixed": (
                "В 25–30 лет чаще проявляется усталость под глазами и снижение свежести к вечеру. "
                "После 30 лет заметнее становятся носогубная зона и уголки рта."
            ),
        }.get(aging_id, "")
    return [
        base,
        f"Сейчас у вас хорошая точка для старта: выраженных изменений ещё немного, поэтому тренировки могут не исправлять, а красиво раскрывать лицо.",
        age_line or "Чем раньше начать мягкую регулярную работу, тем проще сохранить свежесть взгляда, четкость овала и природную гармонию лица.",
    ]


def _zone_plain_details(zone_map: dict[str, Any], aging_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for zone in zone_map.get("zones", [])[:6]:
        if not isinstance(zone, dict):
            continue
        title = _clean(zone.get("title"), "Зона лица")
        status = _clean(zone.get("status"), "yellow")
        meaning = _web_copy(zone.get("meaning") or _zone_meaning(title, _zone_status(status)))
        action = _web_copy(zone.get("care_priority") or _zone_action(title))
        if "лоб" in title.lower():
            action = f"в зоне «{title.lower()}» выражение становится мягче, а взгляд спокойнее."
        elif "глаз" in title.lower():
            action = f"после работы с зоной «{title.lower()}» взгляд выглядит свежее и моложе."
        elif "щ" in title.lower() or "сред" in title.lower() or "носогуб" in title.lower():
            action = f"если поддерживать «{title.lower()}», лицо выглядит более собранным и отдохнувшим."
        elif "овал" in title.lower() or "ниж" in title.lower() or "подбор" in title.lower() or "рот" in title.lower():
            action = f"при работе с зоной «{title.lower()}» овал выглядит чище, а нижняя часть лица — визуально легче."
        is_strong = status == "green"
        items.append(
            {
                "number": zone.get("number"),
                "title": title,
                "status": status,
                "status_label": statusLabelFromColor(status),
                "meaning": meaning,
                "analysis": (
                    f"Это сильная зона: «{title.lower()}» можно раскрывать, чтобы лицо выглядело ещё выразительнее."
                    if is_strong
                    else f"Это зона внимания: «{title.lower()}» может сильнее влиять на усталый вид лица."
                ),
                "action": action,
                "anchor": zone.get("anchor") or {"x": 50, "y": 50},
                "shape": zone.get("shape") or {},
            }
        )
    return items


def _fitness_plain_blocks(
    aging_name: str,
    aging_id: str,
    mixed_components: list[str],
    strong_focus: str,
    priority_zones: list[str],
    benefits: dict[str, Any],
) -> dict[str, Any]:
    zones = _human_join(priority_zones[:3], "зона глаз и овал")
    text = [
        f"Фейс-фитнес в вашем случае нужен не для того, чтобы менять лицо. Он нужен, чтобы раскрыть то, что уже красиво: {strong_focus.lower()}.",
        f"Если регулярно работать с зонами «{zones}», лицо может выглядеть свежее, моложе и более собранно.",
        "Главная идея: подчеркнуть скулы, раскрыть взгляд, сделать овал чище и вернуть лицу ощущение отдыха.",
    ]
    results_by_type = {
        "muscular": [
            "взгляд станет мягче за счет расслабления лба и межбровья",
            "жевательная зона будет меньше утяжелять выражение",
            "лицо сохранит четкость, но будет выглядеть спокойнее",
        ],
        "deformation_edema": [
            "лицо утром может выглядеть легче и свежее",
            "нижняя треть станет визуально собраннее",
            "скулы и овал будут читаться выразительнее",
        ],
        "fine_wrinkle": [
            "кожа будет выглядеть более напитанной и живой",
            "мелкая сетка визуально смягчится",
            "лицо будет выглядеть свежее без агрессивной нагрузки",
        ],
        "tired_mixed": [
            "взгляд станет свежее и мягче",
            "носогубная зона и уголки рта будут выглядеть спокойнее",
            "лицо будет дольше сохранять отдохнувший вид",
        ],
    }
    if aging_id == "tired_mixed" and len(mixed_components) >= 2:
        results = [
            "взгляд будет выглядеть свежее и открытее",
            "нижняя треть станет визуально легче",
            "скулы, овал и природные сильные стороны будут заметнее",
        ]
    else:
        results = results_by_type.get(aging_id, results_by_type["tired_mixed"])
    steps = [
        {"title": "Раскрыть взгляд", "goal": "сделать лицо более свежим и отдохнувшим", "zones": ["зона глаз", "лоб"], "possible_effect": "взгляд выглядит мягче и моложе"},
        {"title": "Поддержать овал", "goal": "сделать нижнюю часть лица визуально легче", "zones": ["шея", "нижняя треть"], "possible_effect": "контур выглядит собраннее"},
        {"title": "Подчеркнуть сильные стороны", "goal": f"раскрыть {strong_focus.lower()}", "zones": priority_zones[:2] or ["скулы", "овал"], "possible_effect": "лицо выглядит красивее, свежее и ухоженнее"},
    ]
    return {"text": text, "results": results, "steps": steps}


def _forecast_plain_blocks(aging_id: str, priority_zones: list[str], main_focus: str) -> dict[str, Any]:
    first = _zone_sentence_label(_zone_focus_at(priority_zones, main_focus, 0))
    second = _zone_sentence_label(_zone_focus_at(priority_zones, main_focus, 1))
    third = _zone_sentence_label(_zone_focus_at(priority_zones, main_focus, 2))
    items = [
        {
            "period": "Через 2 недели",
            "text": f"Лицо может выглядеть свежее утром, а «{first}» — спокойнее.",
            "how_to_notice": ["сделайте фото в одинаковом свете", "сравните взгляд и общее выражение лица"],
        },
        {
            "period": "Через 3–4 недели",
            "text": f"«{second}» может меньше давать усталость, лицо выглядит более открытым.",
            "how_to_notice": ["сравните фото без макияжа", "посмотрите, легче ли читаются скулы и овал"],
        },
        {
            "period": "Через 6–8 недель",
            "text": f"Результат становится устойчивее: «{third}» выглядит спокойнее, лицо — моложе и собраннее.",
            "how_to_notice": ["сравните первое и текущее фото", "оцените, насколько лицо выглядит отдохнувшим"],
        },
    ]
    return {
        "title": "Прогноз по времени",
        "intro": "Это мягкий прогноз без обещаний: результат зависит от регулярности, но первые визуальные изменения обычно можно отслеживать по фото.",
        "items": items,
        "control": [
            {"title": "Как проверять", "text": "Раз в неделю делайте фото анфас в одинаковом свете и без активной мимики."},
            {"title": "Что сравнивать", "text": "Смотрите на свежесть взгляда, чёткость овала и то, насколько лицо выглядит отдохнувшим."},
            {"title": "Главный признак", "text": "Хороший знак — вы выглядите свежее и красивее, но при этом остаётесь собой."},
        ],
    }


def _zone_focus_at(priority_zones: list[str], main_focus: str, index: int) -> str:
    if priority_zones:
        return priority_zones[min(index, len(priority_zones) - 1)]
    return _clean(main_focus, "ключевые зоны лица")


def _forecast_text_by_type(
    *,
    aging_id: str,
    mixed_components: list[str],
    priority_zones: list[str],
    main_focus: str,
    index: int,
) -> str:
    zone = _zone_focus_at(priority_zones, main_focus, index)
    combo_names = [_component_name(component) for component in mixed_components[:2]]
    if aging_id == "tired_mixed" and len(combo_names) >= 2:
        combo = _combo_scenario_phrase(mixed_components)
        return [
            (
                f"Первый ориентир — свежесть лица в покое. При сочетании {combo} важно смотреть, "
                f"становится ли мягче зона «{zone}» и меньше ли она забирает внимание."
            ),
            (
                f"К этому сроку обычно понятнее разница между утренним и вечерним лицом: «{zone}» "
                "должна выглядеть спокойнее, а природные сильные стороны — читаться чище."
            ),
            (
                f"Главный ориентир — устойчивость: лицо дольше сохраняет свежий, собранный вид, "
                f"а зона «{zone}» не утяжеляет общее впечатление."
            ),
        ][index]

    by_type = {
        "muscular": [
            f"Сначала оцениваем мягкость выражения: «{zone}» должна выглядеть спокойнее, без ощущения зажатости в покое.",
            f"Дальше смотрим на глубину мимических линий: «{zone}» может стать менее резкой при одинаковом выражении лица.",
            f"К 6–8 неделе важна устойчивость: лицо сохраняет четкость, но выглядит мягче и менее напряженно.",
        ],
        "deformation_edema": [
            f"Первый ориентир — более легкое утреннее лицо: «{zone}» выглядит спокойнее, без лишней тяжести.",
            f"Дальше сравниваем нижнюю треть и зону глаз: «{zone}» должна меньше утяжелять лицо к вечеру.",
            f"К 6–8 неделе важна стабильность: овал читается чище, а лицо дольше сохраняет свежий вид в течение дня.",
        ],
        "fine_wrinkle": [
            f"Сначала смотрим на качество кожи: «{zone}» должна выглядеть мягче, ровнее и более напитанной.",
            f"К 3–4 неделе оцениваем мелкую сетку и сухость: «{zone}» меньше подчеркивает возраст при том же свете.",
            f"К 6–8 неделе важен общий вид кожи: лицо выглядит более живым, а текстура — спокойнее и плотнее.",
        ],
        "tired_mixed": [
            f"Первый ориентир — свежесть взгляда и выражения: «{zone}» выглядит спокойнее, лицо меньше считывается уставшим.",
            f"К 3–4 неделе смотрим на среднюю и нижнюю треть: «{zone}» должна меньше тянуть выражение вниз.",
            f"К 6–8 неделе важна устойчивость: лицо дольше выглядит отдохнувшим, а природные линии читаются четче.",
        ],
    }
    return by_type.get(aging_id, by_type["tired_mixed"])[index]


def _forecast_control_items(aging_id: str, priority_zones: list[str], main_focus: str) -> list[dict[str, str]]:
    focus = _human_join(priority_zones[:3], main_focus)
    good_sign = {
        "muscular": "выражение лица стало мягче, межбровье и лоб меньше создают ощущение напряжения",
        "deformation_edema": "утром лицо выглядит легче, а нижняя треть и зона глаз меньше утяжеляют контур",
        "fine_wrinkle": "кожа выглядит более ровной и живой, мелкая сетка меньше заметна при том же свете",
        "tired_mixed": "лицо дольше выглядит свежим, а взгляд, носогубная зона и уголки рта выглядят спокойнее",
    }.get(aging_id, "лицо дольше выглядит свежим и собранным")
    return [
        {
            "title": "Фото-контроль",
            "text": (
                "Раз в неделю делайте одно фото анфас в одинаковом свете и с нейтральным выражением. "
                "Так будет видно не настроение дня, а реальное изменение лица."
            ),
        },
        {
            "title": "На что смотреть",
            "text": f"Сравнивайте прежде всего зоны: {focus}. Они лучше всего показывают, меняется ли лицо в нужную сторону.",
        },
        {
            "title": "Хороший знак",
            "text": f"Хорошая динамика — это когда {good_sign}. Без резких обещаний, но с понятным визуальным результатом.",
        },
    ]


def statusLabelFromColor(color: str) -> str:
    return {
        "green": "Сильная зона",
        "yellow": "Зона внимания",
        "orange": "Активный фокус",
        "red": "Приоритет",
    }.get(_clean(color).lower(), "Зона внимания")


def _build_detailed_web_sections(
    *,
    protocol: dict[str, Any],
    zone_map: dict[str, Any],
    aging_id: str,
    aging_name: str,
    mixed_components: list[str],
    visual_age: int,
    passport_age: int,
    skin_type_name: str,
    main_focus: str,
) -> dict[str, Any]:
    skin_age = _block(protocol, "skin_visual_age")
    skin_type = _block(protocol, "skin_type")
    strengths = _block(protocol, "face_strengths")
    aging = _block(protocol, "aging_type")
    future = _block(protocol, "future_changes")
    age_changes = _block(protocol, "age_changes")
    benefits = _block(protocol, "face_fitness_benefits")
    forecast = _block(protocol, "time_forecast")
    final = _block(protocol, "final_summary")

    kb = CLOSED_AGING_KNOWLEDGE.get(aging_id, CLOSED_AGING_KNOWLEDGE["tired_mixed"])
    priority_zones = _zone_titles(zone_map, statuses={"yellow", "orange", "red"}, limit=4)
    strong_zones = _zone_titles(zone_map, statuses={"green"}, limit=3)
    strength_focus_titles = _strength_titles_from_protocol(protocol, 3)
    zone_focus = _human_join(priority_zones, main_focus)
    strong_focus = _human_join(strength_focus_titles or strong_zones, "форма лица, взгляд и природная база")

    age_data = _age_plain_blocks(visual_age, passport_age, zone_focus, skin_age)
    skin_data = _skin_plain_blocks(skin_type_name, skin_type)
    aging_data = _aging_plain_blocks(aging_id, aging_name, mixed_components, kb, priority_zones)
    fitness_data = _fitness_plain_blocks(aging_name, aging_id, mixed_components, strong_focus, priority_zones, benefits)
    forecast_data = _forecast_plain_blocks(aging_id, priority_zones, main_focus)
    zone_details = _zone_plain_details(zone_map, aging_id)

    strength_items = [
        {
            "title": item.split("—", 1)[0].split(":", 1)[0].strip(" ."),
            "text": _web_copy((item.split("—", 1)[1] if "—" in item else item.split(":", 1)[1] if ":" in item else item).strip(" .")),
        }
        for item in _block_bullets(protocol, "face_strengths", 3)
    ]
    if not strength_items:
        strength_items = [
            {"title": "Форма лица", "text": "у вас гармоничная форма, которую важно не менять, а красиво подчеркнуть"},
            {"title": "Взгляд", "text": "глаза дают лицу мягкость и молодое впечатление"},
            {"title": "Пропорции", "text": "черты выглядят спокойными и естественными"},
        ]

    if aging_id == "tired_mixed" and len(mixed_components) >= 2:
        type_line = f"Ваш тип старения — сочетание {_combo_type_phrase(mixed_components)}."
        aging_section_note = "Ниже разложено, из каких типов состоит сочетание и как это может проявляться по зонам."
    else:
        type_line = f"Ваш тип старения — {aging_name}."
        aging_section_note = "Ниже простым языком: характеристика, проявления и зачем лицу регулярная поддержка."

    avoid_by_type = {
        "muscular": [
            "не усиливать мимику там, где лицо уже держит напряжение",
            "не начинать с активной нагрузки без расслабления лба и жевательной зоны",
            "не оценивать результат только по овалу: мягкость взгляда здесь не менее важна",
        ],
        "deformation_edema": [
            "не перегружать лицо силовыми упражнениями, если утром есть припухлость",
            "не забывать про шею: она сильно влияет на лёгкость лица",
            "не ждать выраженных изменений, когда овал уже потеряет чёткость",
        ],
        "fine_wrinkle": [
            "не пересушивать кожу активными средствами",
            "не делать слишком жёсткие техники на тонкой коже",
            "не ждать лифтинг-эффекта без увлажнения и питания кожи",
        ],
        "tired_mixed": [
            "не работать только с одной зоной, если усталость видна сразу в нескольких местах",
            "не игнорировать шею и зону глаз",
            "не оценивать лицо только вечером, когда усталость дня сильнее заметна",
        ],
    }

    return {
        "intro": {
            "title": "Главный вывод",
            "text": [
                (
                    f"По фото видно: у вас красивое лицо с хорошей природной базой — {strong_focus.lower()}. "
                    f"Главные зоны, которые могут добавлять усталость или возраст: {zone_focus}."
                ),
                (
                    "Сейчас у вас хороший момент для старта: выраженные изменения ещё не доминируют, "
                    "и регулярная работа может сделать лицо заметно свежее, моложе и выразительнее."
                ),
            ],
            "highlights": [
                f"Визуальный возраст: {_years_phrase(visual_age)}",
                f"Паспортный возраст: {_years_phrase(passport_age)}",
                type_line,
            ],
        },
        "visual_age": {
            "title": "Почему лицо выглядит именно так",
            "text": age_data["text"],
            "notes": age_data["notes"],
        },
        "skin_type": {
            "title": "Кожа: тип, склонности и потенциал",
            "label": skin_type_name,
            "text": skin_data["text"],
            "bullets": skin_data["bullets"],
        },
        "strengths": {
            "title": "Ваши сильные стороны лица",
            "text": [
                (
                    f"У вас есть черты, которые многие специально пытаются подчеркнуть процедурами: {strong_focus.lower()}. "
                    "Это ваша природная база, и её важно не перекрывать, а раскрывать."
                ),
                (
                    f"{_web_copy(_first_sentence(strengths.get('text'), 'у лица есть красивая природная форма, мягкий взгляд и гармоничные пропорции', 260))}. "
                    "Тренировки помогут сделать эти сильные стороны заметнее: взгляд свежее, скулы выразительнее, лицо собраннее."
                ),
            ],
            "items": strength_items,
        },
        "aging": {
            "title": "Ваш тип старения",
            "type_name": aging_name,
            "combo_note": aging_section_note,
            "text": aging_data["text"],
            "chapters": aging_data["chapters"],
            "evidence": _list(aging.get("evidence"), priority_zones, 5),
        },
        "future": {
            "title": "Что будет со временем",
            "text": _future_plain_blocks(aging_id, mixed_components, zone_focus, age_changes, future),
        },
        "age_changes": {
            "title": "Почему важно начать сейчас",
            "text": [
                "Сейчас лицо ещё хорошо отвечает на мягкую регулярную работу. Это лучший момент, чтобы не бороться с выраженными изменениями позже, а заранее поддержать свежесть и форму.",
                "Цель не в том, чтобы изменить лицо. Цель — сделать его более отдохнувшим, подтянутым и красивым за счёт ваших природных сильных сторон.",
            ],
        },
        "zones": {
            "title": "Карта зон: коротко и понятно",
            "intro": (
                "Карта показывает не «недостатки», а зоны, с которыми стоит работать в первую очередь. "
                "В курсе эти зоны прорабатываются так, чтобы лицо выглядело свежее и гармоничнее."
            ),
            "items": zone_details,
        },
        "strategy": {
            "title": "Что даст фейс-фитнес именно вам",
            "text": fitness_data["text"],
            "results": fitness_data["results"],
            "steps": fitness_data["steps"],
        },
        "forecast": forecast_data,
        "avoid": {
            "title": "Что важно делать аккуратно",
            "items": [_web_copy(item) for item in avoid_by_type.get(aging_id, avoid_by_type["tired_mixed"])],
        },
        "final": {
            "title": "Итог",
            "text": [
                (
                    f"У вас красивое лицо с сильной природной базой: {strong_focus.lower()}. "
                    "Сейчас задача не исправлять себя, а раскрыть то, что уже есть."
                ),
                (
                    f"Если регулярно работать с зонами «{zone_focus}», лицо может выглядеть свежее, моложе и легче. "
                    "Взгляд раскроется, овал станет чище, а сильные стороны будут заметнее."
                ),
                "Именно для этого создан курс: чтобы вы смотрели на себя и видели не усталость, а свою настоящую красоту.",
            ],
            "quote": "Раскрыть природную красоту — мягко, регулярно и без перегруза.",
        },
    }


def build_bella_web_report_data(report: GeneratedReport, settings: BotSettings) -> dict[str, Any]:
    analysis = report.analysis
    analysis_json = analysis.analysis_json if analysis and isinstance(analysis.analysis_json, dict) else {}
    protocol_copy = analysis.protocol_copy_json if analysis and isinstance(analysis.protocol_copy_json, dict) else {}
    try:
        view = report_view_model(report, settings)
    except Exception:
        view = {}
    images = _dict(view.get("images"))
    before_asset = _dict(images.get("original_photo"))
    before_url = _asset_url(before_asset.get("path") or before_asset.get("url") or (analysis.original_photo_path if analysis else None))
    report_date = _date(_dict(view.get("meta")).get("analysis_date") or (analysis.created_at if analysis else None))
    lead_name = _clean(analysis.lead.name if analysis and analysis.lead and analysis.lead.name else _dict(view.get("user")).get("name"), "Гость")
    client_age = _client_age(report)
    cta_text = settings.cta_text or "Получить программу Bella Vladi"

    protocol = _current_protocol(report)
    if not protocol:
        protocol = normalize_protocol_v4_shape({"client": {"name": lead_name, "age": client_age, "date": report_date}})

    client = _dict(protocol.get("client"))
    skin_age = _block(protocol, "skin_visual_age")
    skin_type = _block(protocol, "skin_type")
    strengths = _block(protocol, "face_strengths")
    aging = _block(protocol, "aging_type")
    future = _block(protocol, "future_changes")
    age_changes = _block(protocol, "age_changes")
    benefits = _block(protocol, "face_fitness_benefits")
    forecast = _block(protocol, "time_forecast")
    final = _block(protocol, "final_summary")
    protocol_images = _dict(protocol.get("images"))

    passport_age = _clamp_number(skin_age.get("passport_age") or client.get("age") or client_age, client_age, 1, 110)
    raw_visual_age = _clamp_number(skin_age.get("visual_age"), passport_age, 1, 110)
    visual_age = _clamp_number(_web_visual_age(passport_age, raw_visual_age, report.id), passport_age + 2, 1, 120)
    aging_id = str(aging.get("type_id") or "tired_mixed")
    mixed_components = mixed_combo_type_ids_from_payload(protocol) if aging_id == "tired_mixed" else []
    aging_name = _clean(aging.get("display_name") or build_aging_type_display_name(aging_id, mixed_components), "Усталый / смешанный")
    skin_type_name = _clean(skin_type.get("type_name"), "Комбинированная, с ровной плотной базой")
    before_url = protocol_images.get("face_image_url") or before_url
    geometry = _zone_geometry(report)
    photo_protocol_data = _journal_data(report, before_url, geometry)
    photo_protocol_images = _dict(photo_protocol_data.get("images"))
    photo_zone_map = _dict(photo_protocol_data.get("zone_map"))
    used_photo_zone_map = bool(photo_zone_map)
    zone_map = _protocol_zone_map({"zone_map": photo_zone_map}) if used_photo_zone_map else _protocol_zone_map(protocol)
    priority_titles = [
        _clean(zone.get("title"))
        for zone in zone_map["zones"]
        if zone.get("status") in {"yellow", "orange", "red"} and _clean(zone.get("title"))
    ][:4]
    main_focus = ", ".join(priority_titles[:3]) or _clean(_block(protocol, "growth_zones").get("summary"), "ключевые зоны лица")
    hero_strengths = _human_join(_strength_titles_from_protocol(protocol, 3), "овал, скулы и пропорции")
    hero_conclusion = _hero_conclusion_from_strengths(protocol, hero_strengths)
    final_text = _block_text(protocol, "final_summary")
    quote = _clean(final.get("quote"))
    forecast_items = forecast.get("items") if isinstance(forecast.get("items"), list) else []

    detailed = _build_detailed_web_sections(
        protocol=protocol,
        zone_map=zone_map,
        aging_id=aging_id,
        aging_name=aging_name,
        mixed_components=mixed_components,
        visual_age=visual_age,
        passport_age=passport_age,
        skin_type_name=skin_type_name,
        main_focus=main_focus,
    )
    source_trace = _web_report_source_trace(
        aging_id=aging_id,
        aging_name=aging_name,
        mixed_components=mixed_components,
        used_photo_zone_map=used_photo_zone_map,
        visual_age=visual_age,
        passport_age=passport_age,
    )
    quality = _validate_web_report_v5(
        detailed,
        aging_id=aging_id,
        mixed_components=mixed_components,
        visual_age=visual_age,
        passport_age=passport_age,
    )
    detailed = {**detailed, "version": WEB_REPORT_VERSION, "source_trace": source_trace, "quality": quality}
    if not quality["passed"]:
        logger.warning(
            "bella_web_report_v5_quality_failed report_id=%s aging_type=%s errors=%s warnings=%s",
            report.id,
            aging_id,
            quality["errors"],
            quality["warnings"],
        )
    else:
        logger.info(
            "bella_web_report_v5_quality_passed report_id=%s aging_type=%s warnings=%s",
            report.id,
            aging_id,
            quality["warnings"],
        )

    return {
        "report_version": WEB_REPORT_VERSION,
        "web_report_version": WEB_REPORT_VERSION,
        "report_id": f"BV-{report.id:04d}" if report.id else "BV-REPORT",
        "client": {"name": _clean(client.get("name"), lead_name), "age": passport_age, "date": _date(client.get("date") or report_date)},
        "images": {
            "before_image_url": before_url,
            "before_object_position": WEB_REPORT_OBJECT_POSITION,
            "map_object_position": photo_protocol_images.get("face_object_position") or WEB_MAP_OBJECT_POSITION,
            "face_protocol_image_url": _asset_url(analysis.face_protocol_image_path if analysis else None),
        },
        "hero": {
            "title": "Персональный протокол лица",
            "main_conclusion": hero_conclusion,
            "visual_age": f"{visual_age} лет",
            "aging_type_short": aging_name,
            "main_focus": main_focus,
            "strengths_short": hero_strengths,
        },
        "deep_report": detailed,
        "web_report_quality": quality,
        "web_report_source_trace": source_trace,
        "zone_map": zone_map,
        "final_summary": {"text": final_text, "quote": quote},
        "final_cta": {"title": "Ваш персональный разбор готов", "text": final_text, "primary_button": cta_text},
        "footer": "Это предварительный визуальный AI-разбор по фото. Не медицинское заключение и не замена консультации специалиста.",
    }


def render_bella_web_report_html(report: GeneratedReport, settings: BotSettings) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_json = json.dumps(build_bella_web_report_data(report, settings), ensure_ascii=False).replace("</", "<\\/")
    token_json = json.dumps(report.public_token or "", ensure_ascii=False)
    return template.replace("__REPORT_DATA_JSON__", data_json).replace("__REPORT_TOKEN_JSON__", token_json)
