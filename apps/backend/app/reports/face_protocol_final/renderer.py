from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.ai.prompts import DISCLAIMER
from app.core.config import settings
from app.reports.face_protocol_final.normalize import normalize_protocol_copy

logger = logging.getLogger(__name__)

CANVAS_WIDTH = 1080
ABC_CANVAS_WIDTH = 1600
ABC_CANVAS_HEIGHT = 1350
ABC_DESKTOP_HEIGHT = 1200
RENDER_ZOOM = 0.84
RENDER_LAYOUT_WIDTH = CANVAS_WIDTH / RENDER_ZOOM
LEGACY_RENDERER_ERROR = "LEGACY_FACE_PROTOCOL_RENDERER_DISABLED_USE_FINAL_V1"

STATUS_VISUALS = {
    "good": {"fill": "var(--good-soft)", "stroke": "var(--good)", "pill_class": ""},
    "attention": {"fill": "var(--attention-soft)", "stroke": "var(--attention)", "pill_class": "attn"},
    "priority": {"fill": "var(--priority-soft)", "stroke": "var(--priority)", "pill_class": "prio"},
}

DEFAULT_ZONE_SHAPES = {
    1: "forehead",
    2: "glabella",
    3: "eyes",
    4: "nasolabial",
    5: "mouth",
    6: "jawline",
}

ZONE_NUMBER_POSITIONS = {
    "forehead": (150, 84),
    "glabella": (150, 132),
    "eyes": (116, 148),
    "puffiness": (116, 168),
    "nasolabial": (178, 218),
    "cheeks": (192, 195),
    "mouth": (150, 224),
    "jawline": (214, 252),
    "chin": (150, 260),
    "neck": (196, 330),
}

MONTHS_RU = {
    1: "ЯНВАРЯ",
    2: "ФЕВРАЛЯ",
    3: "МАРТА",
    4: "АПРЕЛЯ",
    5: "МАЯ",
    6: "ИЮНЯ",
    7: "ИЮЛЯ",
    8: "АВГУСТА",
    9: "СЕНТЯБРЯ",
    10: "ОКТЯБРЯ",
    11: "НОЯБРЯ",
    12: "ДЕКАБРЯ",
}

DEFAULT_POINT_B = {
    "title": "ТОЧКА B",
    "sub": "ВЫ ПРИОБРЕТАЕТЕ КУРС",
    "eyebrow": "ВЫ ПОЛУЧАЕТЕ СИСТЕМУ",
    "headline": "Не одну технику, а <em>комплексный маршрут</em> к молодому лицу",
    "items": [
        {"icon": "face", "title": "Фейс-массаж и фейсфитнес", "desc": "Точечная работа с ключевыми зонами"},
        {"icon": "drop", "title": "Работа с отёками", "desc": "Лимфодренаж и утренние ритуалы"},
        {"icon": "posture", "title": "Осанка и шея", "desc": "Снимаем зажимы, открываем лицо"},
        {"icon": "leaf", "title": "Питание и уход", "desc": "Поддержка кожи изнутри и снаружи"},
    ],
    "proof": [
        "Пошаговые видеоуроки в удобном формате",
        "Готовые программы под ваши задачи",
        "Фокус на естественном результате",
    ],
    "bridge": "Хаотичные упражнения из соцсетей не работают — лицу нужна система. Курс даёт маршрут, по которому идут ученицы.",
}

ANCHOR_FALLBACKS = {
    "forehead_tension": {"x": 50, "y": 22},
    "eye_area": {"x": 58, "y": 34},
    "under_eye_area": {"x": 45, "y": 39},
    "morning_puffiness": {"x": 50, "y": 38},
    "nasolabial_area": {"x": 58, "y": 52},
    "cheek_volume": {"x": 62, "y": 50},
    "face_oval": {"x": 55, "y": 72},
    "jaw_tension": {"x": 65, "y": 70},
    "double_chin": {"x": 50, "y": 82},
    "neck": {"x": 50, "y": 90},
    "posture": {"x": 50, "y": 95},
    "skin_tone": {"x": 50, "y": 45},
    "skin_texture": {"x": 50, "y": 45},
    "facial_asymmetry": {"x": 50, "y": 50},
}


def _module_dir() -> Path:
    return Path(__file__).resolve().parent


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_module_dir()),
        autoescape=select_autoescape(("html", "xml")),
    )


def _format_date(value: Any) -> str:
    if isinstance(value, datetime):
        return f"{value.day} {MONTHS_RU[value.month]} {value.year}"
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%d.%m.%Y")
        except Exception:
            pass
    if value:
        return str(value)
    now = datetime.now()
    return f"{now.day} {MONTHS_RU[now.month]} {now.year}"


def _format_protocol_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d · %m · %Y")
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%d · %m · %Y")
        except Exception:
            pass
    if value:
        return str(value)
    return datetime.now().strftime("%d · %m · %Y")


def _clean_text(value: Any, fallback: str = "") -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[*_`#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip() or fallback


def _limit_text(value: Any, max_chars: int, fallback: str) -> str:
    text = _clean_text(value, fallback)
    if len(text) <= max_chars:
        return text
    words: list[str] = []
    for word in text.split():
        candidate = " ".join([*words, word])
        if len(candidate) > max_chars:
            break
        words.append(word)
    return (" ".join(words).strip(" .,:;—–-") or fallback[:max_chars]).strip()


def _list_text(value: Any, *, limit: int, max_chars: int, fallback: list[str]) -> list[str]:
    source = value if isinstance(value, list) else []
    result = [_limit_text(item, max_chars, fallback[0]) for item in source if _clean_text(item)]
    for item in fallback:
        if len(result) >= limit:
            break
        cleaned = _limit_text(item, max_chars, item)
        if cleaned not in result:
            result.append(cleaned)
    return result[:limit]


def _fallback_photo_data_uri() -> str:
    svg = """<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1200" viewBox="0 0 900 1200">
<defs>
<radialGradient id="skin" cx="50%" cy="38%" r="62%">
<stop offset="0%" stop-color="#f6e0cb"/>
<stop offset="58%" stop-color="#e8c8aa"/>
<stop offset="100%" stop-color="#c9a487"/>
</radialGradient>
</defs>
<rect width="900" height="1200" fill="url(#skin)"/>
<ellipse cx="450" cy="500" rx="235" ry="310" fill="#edd0b6" opacity=".55"/>
<path d="M260 860 Q450 1040 640 860" fill="none" stroke="#b99076" stroke-width="20" stroke-linecap="round" opacity=".22"/>
</svg>"""
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _photo_url(photo: str | None) -> str:
    if photo and photo.startswith(("http://", "https://", "data:")):
        return photo
    if photo:
        path = Path(photo).expanduser()
        candidates = [path]
        if not path.is_absolute():
            candidates.extend([
                settings.storage_root() / photo,
                _project_root() / "storage" / photo,
            ])
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve().as_uri()
    logger.warning("Using fallback face photo placeholder")
    return _fallback_photo_data_uri()


def _optional_photo_url(photo: str | None) -> str:
    return _photo_url(photo) if photo else ""


def _score_percent(score: str) -> int:
    match = re.search(r"\d{1,3}", score or "")
    if not match:
        return 78
    return max(0, min(100, int(match.group(0))))


def _apply_render_scale(html: str) -> str:
    render_css = f"""
  /* Render-only scale: keeps the provided journal layout intact while producing a 1080px-wide PNG around 1500px tall. */
  .sheet {{
    width: {RENDER_LAYOUT_WIDTH:.3f}px;
    zoom: {RENDER_ZOOM};
  }}
"""
    return html.replace("</style>", f"{render_css}</style>", 1)


def _zone_visual(status: str) -> dict[str, str]:
    return STATUS_VISUALS.get(status, STATUS_VISUALS["attention"])


def _zone_shape(label: str, fallback_index: int) -> str:
    normalized = (label or "").lower()
    if "лоб" in normalized:
        return "forehead"
    if "меж" in normalized:
        return "glabella"
    if "отеч" in normalized or "отёч" in normalized or "мешк" in normalized:
        return "puffiness"
    if "глаз" in normalized or "век" in normalized:
        return "eyes"
    if "носог" in normalized:
        return "nasolabial"
    if "скул" in normalized:
        return "cheeks"
    if "овал" in normalized or "бры" in normalized or "контур" in normalized:
        return "jawline"
    if "подбор" in normalized:
        return "chin"
    if "ше" in normalized:
        return "neck"
    if "рот" in normalized or "губ" in normalized or "периорал" in normalized:
        return "mouth"
    return DEFAULT_ZONE_SHAPES.get(fallback_index, "jawline")


def _map_zones(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for index, zone in enumerate(zones, start=1):
        shape = _zone_shape(str(zone.get("label", "")), index)
        num_x, num_y = ZONE_NUMBER_POSITIONS.get(shape, ZONE_NUMBER_POSITIONS["jawline"])
        result.append(
            {
                **zone,
                "shape": shape,
                "visual": _zone_visual(zone.get("status", "attention")),
                "num_x": num_x,
                "num_y": num_y,
            }
        )
    return result


def _context(
    *,
    user_name: str,
    photo_url: str,
    protocol_copy: dict[str, Any],
    created_at: Any,
    disclaimer: str | None = None,
) -> dict[str, Any]:
    zones = protocol_copy["zones"][:6]
    zone_visuals = [_zone_visual(zone.get("status", "attention")) for zone in zones]
    growth_zones = [
        {
            **zone,
            "pill_class": _zone_visual(zone.get("status", "attention"))["pill_class"],
        }
        for zone in protocol_copy["growth_zones"][:5]
    ]
    skin_age = protocol_copy["skin_age"]
    skin_type = protocol_copy["skin_type"]
    face_aging = protocol_copy["face_aging"]
    return {
        "user_name": user_name or "Гость",
        "analysis_date": _format_date(created_at),
        "photo_url": photo_url,
        "skin_age_value": skin_age["value"],
        "skin_age_unit": skin_age["unit"],
        "skin_age_comment": skin_age["comment"],
        "skin_score": skin_age["score"],
        "skin_score_percent": _score_percent(skin_age["score"]),
        "skin_type_title": skin_type["title"],
        "skin_type_bullets": skin_type["bullets"],
        "face_strengths": face_aging.get("face_strengths") or face_aging.get("face_type", ""),
        "aging_type": face_aging["aging_type"],
        "aging_bullets": face_aging["bullets"],
        "aging_forecast": face_aging.get("forecast", []),
        "aging_strong_base": face_aging.get("strong_base", ""),
        "zones": zones,
        "zone_visuals": zone_visuals,
        "map_zones": _map_zones(zones),
        "causes": protocol_copy["causes"],
        "why_intro": protocol_copy.get("why_intro", ""),
        "why_outro": protocol_copy.get("why_outro", ""),
        "strengths": protocol_copy["strengths"],
        "benefits": protocol_copy["benefits"],
        "benefits_outro": protocol_copy.get("benefits_outro", ""),
        "forecast": protocol_copy["forecast"],
        "growth_zones": growth_zones,
        "final_summary": protocol_copy["final_summary"],
        "disclaimer": disclaimer or DISCLAIMER,
    }


def _side_from_position(position: Any, index: int) -> str:
    text = _clean_text(position).lower()
    if text.startswith("right"):
        return "right"
    if text.startswith("left"):
        return "left"
    return "left" if index % 2 == 0 else "right"


def _anchor_from_callout(callout: dict[str, Any], index: int) -> dict[str, int]:
    raw = callout.get("anchor") if isinstance(callout.get("anchor"), dict) else {}
    fallback = ANCHOR_FALLBACKS.get(_clean_text(callout.get("id")), {"x": 50, "y": 35 + index * 8})
    try:
        x = int(float(raw.get("x", fallback["x"])))
        y = int(float(raw.get("y", fallback["y"])))
    except Exception:
        x, y = fallback["x"], fallback["y"]
    return {"x": max(0, min(100, x)), "y": max(0, min(100, y))}


def _annotations_from_callouts(callouts: Any, *, result: bool = False) -> list[dict[str, Any]]:
    source = callouts if isinstance(callouts, list) else []
    annotations = []
    for index, item in enumerate(source[:4]):
        if not isinstance(item, dict):
            continue
        text = item.get("description") or item.get("title") or item.get("text")
        annotations.append(
            {
                "side": _side_from_position(item.get("label_position"), index),
                "text": _limit_text(text, 78, "Зона внимания" if not result else "Возможное улучшение"),
                "anchor": _anchor_from_callout(item, index),
            }
        )
    return annotations


def _joined_block_items(block: Any, fallback: str) -> str:
    data = block if isinstance(block, dict) else {}
    items = _list_text(data.get("items"), limit=2, max_chars=70, fallback=[fallback])
    return _limit_text(" ".join(items), 150, fallback)


def _bella_protocol_from_analysis(analysis_json: dict[str, Any] | None) -> dict[str, Any]:
    analysis = analysis_json if isinstance(analysis_json, dict) else {}
    raw = analysis.get("bella_protocol")
    return raw if isinstance(raw, dict) else {}


def _fallback_protocol_data_from_copy(protocol_copy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    zones = protocol_copy.get("zones") if isinstance(protocol_copy.get("zones"), list) else []
    benefits = protocol_copy.get("benefits") if isinstance(protocol_copy.get("benefits"), list) else []
    causes = protocol_copy.get("causes") if isinstance(protocol_copy.get("causes"), list) else []
    growth = protocol_copy.get("growth_zones") if isinstance(protocol_copy.get("growth_zones"), list) else []
    a_annotations = []
    for index, zone in enumerate(zones[:4]):
        if not isinstance(zone, dict):
            continue
        a_annotations.append(
            {
                "side": "left" if index % 2 == 0 else "right",
                "text": _limit_text(zone.get("label"), 42, "Зона внимания"),
                "anchor": list(ANCHOR_FALLBACKS.values())[min(index, len(ANCHOR_FALLBACKS) - 1)],
            }
        )
    c_annotations = []
    for index, zone in enumerate((growth or zones)[:4]):
        if isinstance(zone, dict):
            text = zone.get("label")
        else:
            text = zone
        c_annotations.append(
            {
                "side": "right" if index % 2 == 0 else "left",
                "text": _limit_text(text, 78, "Возможное улучшение"),
                "anchor": list(ANCHOR_FALLBACKS.values())[min(index, len(ANCHOR_FALLBACKS) - 1)],
            }
        )
    return (
        {
            "title": "ТОЧКА А",
            "sub": "ВЫ СЕЙЧАС",
            "annotations": a_annotations,
            "pains_title": "Ваши боли",
            "pains": _list_text(causes, limit=4, max_chars=82, fallback=["Лицо выглядит уставшим", "Хочется более чёткий овал"]),
            "influence_label": "Как это влияет на жизнь",
            "influence": _limit_text(protocol_copy.get("why_intro"), 150, "Появляется ощущение, что лицу нужна понятная система поддержки."),
        },
        {
            "title": "ТОЧКА C",
            "sub": "ВАШ ВОЗМОЖНЫЙ РЕЗУЛЬТАТ",
            "annotations": c_annotations,
            "results_title": "Ваш результат",
            "results": _list_text(benefits, limit=4, max_chars=82, fallback=["Более свежий вид", "Чётче овал лица"]),
            "influence_label": "Как это влияет на жизнь",
            "influence": _limit_text(protocol_copy.get("benefits_outro"), 150, "Больше лёгкости, свежести и уверенности в своём отражении."),
        },
    )


def _protocol_data(
    *,
    analysis_request_id: str,
    user_name: str,
    before_image_url: str,
    after_image_url: str,
    protocol_copy: dict[str, Any],
    analysis_json: dict[str, Any] | None,
    created_at: Any,
) -> dict[str, Any]:
    bella = _bella_protocol_from_analysis(analysis_json)
    point_a_raw = bella.get("point_a") if isinstance(bella.get("point_a"), dict) else {}
    point_c_raw = bella.get("point_c") if isinstance(bella.get("point_c"), dict) else {}
    fallback_a, fallback_c = _fallback_protocol_data_from_copy(protocol_copy)

    pain_block = point_a_raw.get("pain_block") if isinstance(point_a_raw.get("pain_block"), dict) else {}
    life_impact = point_a_raw.get("life_impact") if isinstance(point_a_raw.get("life_impact"), dict) else {}
    result_block = point_c_raw.get("result_block") if isinstance(point_c_raw.get("result_block"), dict) else {}
    life_result = point_c_raw.get("life_result") if isinstance(point_c_raw.get("life_result"), dict) else {}

    point_a_annotations = _annotations_from_callouts(point_a_raw.get("face_callouts"))
    point_c_annotations = _annotations_from_callouts(point_c_raw.get("face_callouts"), result=True)

    point_a = fallback_a if not point_a_raw else {
        "title": "ТОЧКА А",
        "sub": "ВЫ СЕЙЧАС",
        "annotations": point_a_annotations or fallback_a["annotations"],
        "pains_title": _clean_text(pain_block.get("title"), "Ваши боли"),
        "pains": _list_text(pain_block.get("items"), limit=4, max_chars=82, fallback=fallback_a["pains"]),
        "influence_label": _clean_text(life_impact.get("title"), "Как это влияет на жизнь"),
        "influence": _joined_block_items(life_impact, fallback_a["influence"]),
    }
    point_c = fallback_c if not point_c_raw else {
        "title": "ТОЧКА C",
        "sub": "ВАШ ВОЗМОЖНЫЙ РЕЗУЛЬТАТ",
        "annotations": point_c_annotations or fallback_c["annotations"],
        "results_title": _clean_text(result_block.get("title"), "Ваш результат"),
        "results": _list_text(result_block.get("items"), limit=4, max_chars=82, fallback=fallback_c["results"]),
        "influence_label": _clean_text(life_result.get("title"), "Как это влияет на жизнь"),
        "influence": _joined_block_items(life_result, fallback_c["influence"]),
    }
    point_b = {
        **DEFAULT_POINT_B,
        "items": DEFAULT_POINT_B["items"][:4],
        "proof": DEFAULT_POINT_B["proof"][:3],
    }

    return {
        "brand": {"initial": "BV", "name": "BELLA VLADI", "tagline": "Эксперт по фейсфитнесу"},
        "header": {
            "title_main": "Как выглядит ваша",
            "title_accent": "трансформация",
            "title_tail": "с курсом",
            "subtitle": "Персональная карта лица — текущие зоны внимания, система работы и возможный результат",
            "meta_top": "ПЕРСОНАЛЬНЫЙ ПРОТОКОЛ",
            "meta_id": f"ID · BV-{analysis_request_id}",
            "meta_date": _format_protocol_date(created_at),
            "disclaimer": DISCLAIMER,
        },
        "images": {
            "before_image_url": before_image_url,
            "before_object_position": "50% 35%",
            "after_image_url": after_image_url,
            "after_object_position": "50% 35%",
        },
        "point_a": point_a,
        "point_b": point_b,
        "point_c": point_c,
        "transformation_path": {
            "a": {"title": "Жизнь как раньше", "desc": "Усталость, отёки и недовольство собой"},
            "b": {"title": "Решение инвестировать в себя", "desc": "Вы получаете систему и понятный маршрут"},
            "c": {"title": "Новая версия себя", "desc": "Каждый день лицо выглядит свежее и легче"},
        },
        "cta": {
            "quote": "Ваш протокол показывает: <em>результат возможен</em>, если работать системно",
            "primary": "Получить полную программу",
            "secondary": "Разобрать протокол с куратором",
        },
    }


def _chromium_executable_path() -> str | None:
    executable_path = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    if executable_path:
        return executable_path
    for candidate in (
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def _screenshot_sheet(html_path: Path, output_path: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for face_protocol_final. Install playwright and Chromium.") from exc

    executable_path = _chromium_executable_path()
    with sync_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if executable_path:
            launch_kwargs["executable_path"] = executable_path
        browser = playwright.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": CANVAS_WIDTH, "height": 2200}, device_scale_factor=1)
        page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        sheet = page.locator(".sheet")
        sheet.wait_for(state="visible", timeout=15_000)
        sheet.screenshot(path=str(output_path), type="png")
        browser.close()


def _screenshot_abc_protocol(html_path: Path, output_path: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for face_protocol_final. Install playwright and Chromium.") from exc

    executable_path = _chromium_executable_path()
    with sync_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if executable_path:
            launch_kwargs["executable_path"] = executable_path
        browser = playwright.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": ABC_CANVAS_WIDTH, "height": ABC_DESKTOP_HEIGHT}, device_scale_factor=1)
        page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        page.evaluate("document.body.style.padding = '0'")
        page.evaluate("document.body.style.gap = '0'")
        page.evaluate("document.body.style.background = '#ebe3d2'")
        page.evaluate("""
            document.body.classList.remove('fmt-mob');
            const protocol = document.querySelector('#protocol-desk');
            if (protocol) {
                protocol.style.transform = 'none';
                protocol.style.transformOrigin = 'top left';
                protocol.style.width = '1600px';
                protocol.style.height = '1200px';
                protocol.style.overflow = 'hidden';
            }
            const switcher = document.querySelector('.switcher');
            if (switcher) switcher.style.display = 'none';
        """)
        try:
            page.evaluate("window.preloadProtocolImages && window.preloadProtocolImages()")
        except Exception:
            logger.warning("Protocol image preload hook failed", exc_info=True)
        protocol = page.locator("#protocol-desk")
        protocol.wait_for(state="visible", timeout=15_000)
        protocol.screenshot(path=str(output_path), type="png")
        browser.close()


def render_face_protocol_final_v1(
    analysis_request_id: str,
    user_name: str,
    user_photo_path_or_url: str,
    protocol_copy: dict,
    output_dir: str,
    created_at,
    after_photo_path_or_url: str | None = None,
    analysis_json: dict[str, Any] | None = None,
) -> str:
    logger.info("FACE_PROTOCOL_RENDERER=final_v1")
    logger.info("Rendering face protocol from protocol_abc.html")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    try:
        normalized = normalize_protocol_copy(protocol_copy)
        logger.info("Protocol copy normalized")
        data = _protocol_data(
            analysis_request_id=analysis_request_id,
            user_name=user_name,
            before_image_url=_photo_url(user_photo_path_or_url),
            after_image_url=_optional_photo_url(after_photo_path_or_url),
            protocol_copy=normalized,
            analysis_json=analysis_json,
            created_at=created_at,
        )
        html = _env().get_template("protocol_abc.html").render(
            protocol_data_json=json.dumps(data, ensure_ascii=False),
        )
        safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(analysis_request_id)).strip("_") or "preview"
        html_path = output / f"face_protocol_final_v1_{safe_id}.html"
        png_path = output / f"face_protocol_final_v1_{safe_id}.png"
        html_path.write_text(html, encoding="utf-8")
        _screenshot_abc_protocol(html_path, png_path)
        logger.info("Saved face protocol PNG: %s", png_path)
        return str(png_path)
    except Exception:
        logger.error("Face protocol render failed", exc_info=True)
        raise
