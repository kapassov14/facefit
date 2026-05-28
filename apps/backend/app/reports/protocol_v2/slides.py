from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import ImageDraw

from app.reports.protocol_v2.layout import (
    HEIGHT,
    PALETTE,
    WIDTH,
    draw_card_text,
    draw_centered_text,
    draw_header,
    draw_section_block,
    draw_slide_title,
    draw_soft_panel,
    draw_status_legend,
    draw_runtime_marker,
    font,
    font_path,
    make_canvas,
    paste_photo_cover,
    save_rgb,
)
from app.reports.protocol_v2.text_utils import draw_fitted_text, measure_text, shorten_text_semantic
from app.reports.protocol_v2.zone_overlay import ZoneView, normalize_zones, draw_face_zones


def _limit(text: Any, max_chars: int) -> str:
    value = shorten_text_semantic("" if text is None else str(text), max_chars)
    return value.strip()


def _limit_bullet(text: Any, max_chars: int = 55) -> str:
    return _limit(text, max_chars).rstrip(".")


def _ordered_focus(zones: list[ZoneView]) -> list[ZoneView]:
    priority = [zone for zone in zones if zone.status == "priority"]
    attention = [zone for zone in zones if zone.status == "attention"]
    good = [zone for zone in zones if zone.status == "good"]
    return (priority + attention + good)[:3]


def _canonical_short_phrase(text: Any, *, kind: str, max_chars: int) -> str:
    value = str(text or "").strip()
    lower = value.lower()

    if kind == "skin_type":
        if "комб" in lower:
            return "Комбинированная, склонная к отёчности."
        if "сух" in lower:
            return "Сухая, требует мягкого увлажнения."
        if "жир" in lower:
            return "Жирная, с хорошим запасом плотности."
        if "чувств" in lower:
            return "Чувствительная, нужен бережный уход."
        if "норм" in lower:
            return "Нормальная, с ровным визуальным тоном."

    if kind == "strength":
        if "глаз" in lower or "взгляд" in lower:
            return "выразительные глаза"
        if "кож" in lower or "плотн" in lower:
            return "плотная кожа"
        if "овал" in lower:
            return "потенциал овала"
        if "скул" in lower:
            return "хорошие скулы"
        if "симмет" in lower:
            return "мягкая симметрия"
        if "естествен" in lower:
            return "естественная красота"

    if kind == "cause":
        if "ше" in lower or "ключ" in lower or "осанк" in lower:
            return "Шея может замедлять отток"
        if "лимф" in lower and ("глаз" in lower or "сред" in lower):
            return "Лимфоотток в зоне глаз"
        if "отеч" in lower or "отёч" in lower or "пастоз" in lower:
            return "Отёчность в средней трети"
        if "межбров" in lower or "гипертонус" in lower:
            return "Напряжение межбровки"
        if "овал" in lower or "нижн" in lower:
            return "Слабый тонус овала"

    if kind == "benefit":
        if "отеч" in lower or "отёч" in lower or "пастоз" in lower:
            return "Меньше утренней отёчности"
        if "век" in lower or "глаз" in lower or "взгляд" in lower:
            return "Более открытый взгляд"
        if "носогуб" in lower:
            return "Мягче носогубная зона"
        if "овал" in lower or "контур" in lower:
            return "Чётче нижний контур"
        if "нижн" in lower or "подбород" in lower or "губ" in lower:
            return "Мягче нижняя треть лица"
        if "тонус" in lower:
            return "Больше тонуса кожи"

    return _limit_bullet(value, max_chars)


def _first_list(values: Any, max_items: int, max_chars: int, fallback: list[str], *, kind: str) -> list[str]:
    if not isinstance(values, list):
        return fallback[:max_items]
    result = [_canonical_short_phrase(item, kind=kind, max_chars=max_chars) for item in values if str(item).strip()]
    return (result or fallback)[:max_items]


def _strengths_copy(values: Any) -> str:
    if not isinstance(values, list):
        return "Выразительные глаза, плотная кожа."
    result: list[str] = []
    for item in values:
        phrase = _canonical_short_phrase(item, kind="strength", max_chars=34)
        if phrase and phrase not in result:
            result.append(phrase)
    if not result:
        result = ["выразительные глаза", "плотная кожа"]
    return _limit(", ".join(result[:3]).capitalize(), 90)


def _forecast_copy(time_forecast: dict[str, Any]) -> list[str]:
    first = str(time_forecast.get("first_changes") or "").lower()
    visible = str(time_forecast.get("visible_changes") or "").lower()
    return [
        "2 недели: меньше отёчности" if "2" in first or "14" in first else "7–14 дней: меньше отёчности",
        "1 месяц: свежее лицо" if "месяц" in visible or "3" in visible or "4" in visible else "4–6 недель: свежее лицо",
        "3 месяца: устойчивее овал",
    ]


def prepare_slide_safe_copy(analysis_json: dict[str, Any]) -> dict[str, Any]:
    zones = normalize_zones(analysis_json)
    skin_age = analysis_json.get("skin_visual_age") or {}
    skin_type = analysis_json.get("skin_type") or {}
    face_type = analysis_json.get("face_type_and_aging_type") or {}
    time_forecast = analysis_json.get("time_forecast") or {}

    age_range = _limit(skin_age.get("estimated_range") or "свежий визуальный диапазон", 34).rstrip(".")
    age_expl = _limit(skin_age.get("explanation") or "есть лёгкие признаки усталости", 52).rstrip(".")
    skin_type_text = _canonical_short_phrase(skin_type.get("type") or "", kind="skin_type", max_chars=70)
    aging_type = ", ".join(
        part
        for part in [
            _limit(face_type.get("face_type") or "мягкий овал", 30).rstrip("."),
            _limit(face_type.get("aging_type") or "усталый тип", 38).rstrip("."),
        ]
        if part
    )
    strengths = _strengths_copy(analysis_json.get("strengths"))

    causes = _first_list(
        analysis_json.get("causes"),
        3,
        55,
        ["Отёчность в зоне глаз", "Напряжение межбровки", "Слабый тонус овала"],
        kind="cause",
    )
    benefits = _first_list(
        analysis_json.get("facefitness_benefits"),
        3,
        55,
        ["Более открытый взгляд", "Мягче носогубная зона", "Чётче нижний контур"],
        kind="benefit",
    )
    forecast = _forecast_copy(time_forecast)

    return {
        "face_map": {
            "main_focus": [
                {"label": _limit(zone.short_label, 22).rstrip("."), "status": zone.status}
                for zone in _ordered_focus(zones)
            ],
            "zones": [
                {"number": zone.number, "short_label": zone.short_label, "status": zone.status}
                for zone in zones
            ],
        },
        "summary": {
            "skin_age": _limit(f"{age_range}: {age_expl}", 90),
            "skin_type": _limit(skin_type_text or "Комбинированная, склонная к отёчности.", 90),
            "aging_type": _limit(aging_type or "Усталый тип с акцентом на глаза и овал.", 90),
            "strengths": strengths,
        },
        "plan": {
            "causes": causes,
            "benefits": benefits,
            "forecast": forecast,
        },
    }


def _date_text() -> str:
    return datetime.now().strftime("%d.%m.%Y")


def _draw_footer(image, text: str) -> None:
    draw = ImageDraw.Draw(image)
    draw_centered_text(draw, (72, HEIGHT - 68, WIDTH - 72, HEIGHT - 28), text, font(22), PALETTE.text_secondary)


def render_slide_1(
    *,
    photo_path: str,
    output_path: str | Path,
    user_name: str,
    analysis_json: dict[str, Any],
    background_path: str | None = None,
    date_text: str | None = None,
) -> str:
    safe = prepare_slide_safe_copy(analysis_json)
    zones = normalize_zones(analysis_json)
    image = make_canvas(background_path)
    draw_header(image, user_name=user_name, date_text=date_text or _date_text())

    photo_box = (78, 250, 1002, 1038)
    face_box = paste_photo_cover(image, photo_path, photo_box, radius=42)
    draw_face_zones(image, face_box, zones, label_bounds=photo_box)

    panel = (78, 1064, 1002, 1268)
    draw_soft_panel(image, panel, radius=40)
    draw_status_legend(image, panel[0] + 54, panel[1] + 30)

    draw = ImageDraw.Draw(image)
    draw.text((panel[0] + 54, panel[1] + 88), "Главный фокус", font=font(30, bold=True), fill=PALETTE.text)
    x = panel[0] + 54
    y = panel[1] + 138
    for item in safe["face_map"]["main_focus"][:3]:
        label = f"{item['label']}"
        chip = label
        chip_font = font(25, bold=True)
        text_w, _ = measure_text(draw, chip, chip_font)
        chip_w = max(190, min(270, text_w + 44))
        draw.rounded_rectangle((x, y, x + chip_w, y + 54), radius=27, outline="#D6C9BD", fill="#FFF9F2", width=2)
        draw_fitted_text(
            draw,
            chip,
            (x + 22, y + 11, x + chip_w - 20, y + 44),
            font_path(bold=True),
            25,
            22,
            1,
            fill=PALETTE.text,
        )
        x += chip_w + 18

    _draw_footer(image, "Подробный отчет — по ссылке в боте")
    draw_runtime_marker(image)
    return save_rgb(image, output_path)


def render_slide_2(
    *,
    output_path: str | Path,
    user_name: str,
    analysis_json: dict[str, Any],
    background_path: str | None = None,
) -> str:
    safe = prepare_slide_safe_copy(analysis_json)
    image = make_canvas(background_path)
    draw_slide_title(image, "Краткое резюме", f"{user_name or 'Гость'} · Bella Vladi")

    cards = [
        ((72, 224, 1008, 416), "Биологический возраст кожи", safe["summary"]["skin_age"], PALETTE.dusty_rose),
        ((72, 448, 1008, 640), "Тип кожи", safe["summary"]["skin_type"], PALETTE.sage),
        ((72, 672, 1008, 864), "Форма лица и старения", safe["summary"]["aging_type"], PALETTE.sand),
        ((72, 896, 1008, 1088), "Сильные стороны", safe["summary"]["strengths"], PALETTE.muted_rose),
    ]
    for box, title, text, accent in cards:
        draw_card_text(image, box, title=title, text=text, accent=accent, body_max_size=36, body_min_size=30, body_lines=2)

    bottom = (118, 1148, 962, 1242)
    draw_soft_panel(image, bottom, radius=34, fill="#FFF8F1", border="#E1D0C2", shadow=False)
    draw = ImageDraw.Draw(image)
    draw_centered_text(draw, bottom, "Полный разбор — на странице отчета", font(31, bold=True), PALETTE.text)
    _draw_footer(image, "Протокол не является медицинским диагнозом")
    draw_runtime_marker(image)
    return save_rgb(image, output_path)


def render_slide_3(
    *,
    output_path: str | Path,
    user_name: str,
    analysis_json: dict[str, Any],
    background_path: str | None = None,
) -> str:
    safe = prepare_slide_safe_copy(analysis_json)
    image = make_canvas(background_path)
    draw_slide_title(image, "План и прогноз", "реалистичный фокус на 3 месяца")

    draw_section_block(
        image,
        (72, 208, 1008, 436),
        title="Почему это происходит",
        bullets=safe["plan"]["causes"],
        accent=PALETTE.dusty_rose,
    )
    draw_section_block(
        image,
        (72, 462, 1008, 690),
        title="Что даст фейсфитнес",
        bullets=safe["plan"]["benefits"],
        accent=PALETTE.sage,
    )
    draw_section_block(
        image,
        (72, 716, 1008, 944),
        title="Прогноз по времени",
        bullets=safe["plan"]["forecast"],
        accent=PALETTE.sand,
    )

    cta_box = (92, 1000, 988, 1198)
    draw_soft_panel(image, cta_box, radius=42, fill="#FFF8F1", border="#D9C8B8", shadow=True, shadow_alpha=30)
    draw = ImageDraw.Draw(image)
    draw_centered_text(draw, (cta_box[0] + 38, cta_box[1] + 34, cta_box[2] - 38, cta_box[1] + 82), "Следующий шаг", font(34, bold=True), PALETTE.text_secondary)
    draw_centered_text(
        draw,
        (cta_box[0] + 46, cta_box[1] + 86, cta_box[2] - 46, cta_box[1] + 150),
        "Получить персональную программу",
        font(38, bold=True),
        PALETTE.text,
    )
    draw_centered_text(
        draw,
        (cta_box[0] + 46, cta_box[1] + 146, cta_box[2] - 46, cta_box[1] + 192),
        "Bella Vladi",
        font(34, serif=True),
        PALETTE.dusty_rose,
    )

    _draw_footer(image, "Подробный отчет и CTA — по ссылке в боте")
    draw_runtime_marker(image)
    return save_rgb(image, output_path)
