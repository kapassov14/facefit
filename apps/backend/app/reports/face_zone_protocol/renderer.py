from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.ai.aging_knowledge import (
    aging_mechanics,
    aging_public_label,
    aging_strategy,
    normalize_aging_classification,
    sanitize_face_features_text,
)
from app.ai.protocol_v4 import (
    build_aging_type_display_name,
    mixed_combo_type_ids_from_payload,
)
from app.core.config import settings
from app.reports.face_zone_protocol.mediapipe_map import canonical_zone_id, detect_face_zone_geometry

logger = logging.getLogger(__name__)

RENDER_WIDTH = 1184
RENDER_HEIGHT = 1980
OBJECT_POSITION = "50% 58%"

STATUS_LABELS = {
    "green": "Всё хорошо",
    "yellow": "Зона внимания",
    "orange": "Активный фокус",
    "red": "Приоритет",
}

DEFAULT_ZONES = [
    {
        "id": "forehead",
        "title": "Лоб",
        "status": "green",
        "description": "Лоб выглядит спокойным и открытым.",
        "what_is_visible": "Лоб выглядит относительно спокойным и поддерживает открытость лица.",
        "why_it_matters": "Эта зона влияет на мягкость взгляда и выражения.",
        "what_to_do": "Сохранять мягкое расслабление и не перегружать мимику.",
    },
    {
        "id": "brow",
        "title": "Межбровье",
        "status": "yellow",
        "description": "Может собирать мимическое напряжение.",
        "what_is_visible": "Глаза выразительные, но межбровье может делать взгляд строже.",
        "why_it_matters": "Даже лёгкий зажим в этой зоне меняет мягкость выражения.",
        "what_to_do": "Начинать с расслабления лба, межбровья и верхней трети.",
    },
    {
        "id": "eye_area",
        "title": "Зона глаз",
        "status": "yellow",
        "description": "Влияет на ощущение свежести взгляда.",
        "what_is_visible": "Зона глаз красивая и выразительная, но быстрее показывает недосып.",
        "why_it_matters": "Именно взгляд первым создаёт впечатление свежего и открытого лица.",
        "what_to_do": "Работать мягко: лимфодренаж, шея, расслабление верхней трети.",
    },
    {
        "id": "nasolabial",
        "title": "Носогубная зона",
        "status": "yellow",
        "description": "Связана с мягкостью средней трети.",
        "what_is_visible": "Носогубная зона может читаться ярче, когда средняя треть тяжелее.",
        "why_it_matters": "Она влияет на мягкость выражения вокруг рта и щёк.",
        "what_to_do": "Смягчать через лимфоток, расслабление жевательной зоны и работу со средней третью.",
    },
    {
        "id": "mouth_area",
        "title": "Околоротовая зона",
        "status": "yellow",
        "description": "Нижняя треть просит мягкого расслабления.",
        "what_is_visible": "Околоротовая зона может удерживать напряжение и визуально утяжелять нижнюю треть.",
        "why_it_matters": "От неё зависит, насколько лицо выглядит мягким и спокойным.",
        "what_to_do": "Добавлять расслабление, дыхание и мягкую работу с тонусом.",
    },
    {
        "id": "face_oval",
        "title": "Овал лица",
        "status": "yellow",
        "description": "Овал — сильная база лица.",
        "what_is_visible": "Овал выглядит ресурсным, а нижней трети нужна регулярная поддержка собранности.",
        "why_it_matters": "Контур лица сильнее всего отвечает за ощущение лифтинга и ухоженности.",
        "what_to_do": "Начать с шеи и лимфы, затем подключать мягкий тонус овала.",
    },
]

BEAUTY_ZONE_SPECS = [
    {
        "id": "forehead",
        "title": "Лоб / зона напряжения",
        "match_ids": {"forehead", "brow"},
        "fallback_status": "yellow",
        "description": "Лоб и межбровье показывают, где лицо может собирать напряжение.",
    },
    {
        "id": "eye_area",
        "title": "Зона под глазами",
        "match_ids": {"eye_area"},
        "fallback_status": "yellow",
        "description": "Зона глаз первой влияет на ощущение свежести и отдыха.",
    },
    {
        "id": "cheeks",
        "title": "Щёки / средняя треть",
        "match_ids": {"cheeks"},
        "fallback_status": "yellow",
        "description": "Средняя треть влияет на мягкость лица и глубину носогубной зоны.",
    },
    {
        "id": "nasolabial",
        "title": "Носогубная зона",
        "match_ids": {"nasolabial"},
        "fallback_status": "yellow",
        "description": "Носогубная зона может считываться ярче при тяжести средней трети.",
    },
    {
        "id": "mouth_area",
        "title": "Подбородок / около-ротовая зона",
        "match_ids": {"mouth_area"},
        "fallback_status": "yellow",
        "description": "Около-ротовая зона влияет на мягкость выражения и нижнюю треть.",
    },
    {
        "id": "face_oval",
        "title": "Овал лица / нижняя треть",
        "match_ids": {"face_oval", "neck"},
        "fallback_status": "yellow",
        "description": "Овал и нижняя треть отвечают за ощущение собранности лица.",
    },
]

EMPTY_MARKERS = {
    "визуально не определялся",
    "визуально не определялся отдельно",
    "не определено",
    "не удалось определить",
    "данные отсутствуют",
    "unknown",
    "none",
}


def _clean(value: Any, fallback: str = "") -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\b[Пп]роблем(а|ы|у|ой|е|ами|ах)?\b", "зона внимания", text)
    text = re.sub(r"\b[Бб]рыли\b", "снижение чёткости овала", text)
    text = re.sub(r"\b[Мм]ешки под глазами\b", "отёчность в зоне глаз", text)
    text = re.sub(r"\b[Нн]ормальная кожа\b", "кожа с ровной плотной базой", text)
    text = re.sub(r"\b[Нн]ормаль\w+\b", "комбинированная с ровной плотной базой", text)
    return re.sub(r"\s+", " ", text).strip() or fallback


def _clean_keep_breaks(value: Any, fallback: str = "") -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\b[Пп]роблем(а|ы|у|ой|е|ами|ах)?\b", "зона внимания", text)
    text = re.sub(r"\b[Бб]рыли\b", "снижение чёткости овала", text)
    text = re.sub(r"\b[Мм]ешки под глазами\b", "отёчность в зоне глаз", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\s+(30\s*[–-]\s*35\s*:)", r"\n\n\1", text)
    text = re.sub(r"\s+(35\s*[–-]\s*40\s*:)", r"\n\n\1", text)
    text = re.sub(r"\s+((?:После|после)\s+40(?:\s*[–-]\s*45)?\s*:)", r"\n\n\1", text)
    text = re.sub(r"\n{2,}(Сейчас\s+[—-])", r" \1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or fallback


def _meaningful(value: Any, fallback: str = "") -> str:
    text = _clean(value)
    if not text or text.lower() in EMPTY_MARKERS:
        return fallback
    if any(marker in text.lower() for marker in EMPTY_MARKERS):
        return fallback
    return text


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _selected_aging_value(
    analysis_json: dict[str, Any],
    protocol_copy: dict[str, Any] | None = None,
    personal_insight_json: dict[str, Any] | None = None,
) -> Any:
    protocol = protocol_copy if isinstance(protocol_copy, dict) else {}
    insight = personal_insight_json if isinstance(personal_insight_json, dict) else {}
    strict_blocks = _dict(protocol.get("strict_blocks")) or _dict(analysis_json.get("strict_blocks")) or _dict(analysis_json.get("bella_protocol_v4"))
    strict_aging = _dict(strict_blocks.get("aging_type"))
    if strict_aging.get("type_id"):
        return strict_aging
    context = _dict(analysis_json.get("analysis_context"))
    if context.get("aging_type_id"):
        return {
            "type_id": context.get("aging_type_id"),
            "type_name": context.get("aging_type_name"),
            "display_name": context.get("aging_display_name"),
            "combo_type_ids": context.get("combo_type_ids") or [],
            "combo_type_names": context.get("combo_type_names") or [],
        }
    classification = _dict(analysis_json.get("aging_classification"))
    if classification.get("type_id"):
        return classification
    morphotype = _dict(insight.get("morphotype_story"))
    if morphotype.get("type"):
        return morphotype.get("type")
    face = _dict(analysis_json.get("face_type_and_aging_type"))
    compact_aging = _dict(analysis_json.get("aging_type"))
    journal = _dict(analysis_json.get("journal_protocol"))
    journal_face = _dict(journal.get("face_type"))
    return journal_face.get("aging_type") or face.get("aging_type") or compact_aging.get("type") or "tired_mixed"


def _list(value: Any, fallback: list[str] | None = None, limit: int | None = None) -> list[str]:
    source = value if isinstance(value, list) else []
    result = [_clean(item) for item in source if _clean(item)]
    if not result and fallback:
        result = fallback[:]
    return result[:limit] if limit else result


def _limit(value: Any, max_chars: int, fallback: str) -> str:
    text = _meaningful(value, fallback)
    if len(text) <= max_chars:
        return text
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n{2,}", text) if part.strip()]
    selected: list[str] = []
    for sentence in sentences:
        candidate = " ".join([*selected, sentence]).strip()
        if len(candidate) > max_chars:
            break
        selected.append(sentence)
    if selected:
        return " ".join(selected).strip(" .,:;—–-") + "."
    for separator in (". ", "; ", ": ", ", ", " — ", " - ", " – "):
        head = text.split(separator, 1)[0].strip(" .,:;—–-")
        if max(40, max_chars // 3) <= len(head) <= max_chars:
            return f"{head}."
    words: list[str] = []
    for word in text.split():
        candidate = " ".join([*words, word])
        if len(candidate) > max_chars:
            break
        words.append(word)
    while words and _clean(words[-1]).lower() in {"и", "а", "но", "в", "с", "к", "по", "для", "на", "о"}:
        words.pop()
    return (" ".join(words).strip(" .,:;—–-") or fallback[:max_chars]).rstrip(".") + "."


def _limit_keep_breaks(value: Any, max_chars: int, fallback: str) -> str:
    text = _clean_keep_breaks(value, fallback)
    if len(text) <= max_chars:
        return text
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    selected: list[str] = []
    for paragraph in paragraphs:
        candidate = "\n\n".join([*selected, paragraph])
        if len(candidate) > max_chars:
            break
        selected.append(paragraph)
    if selected:
        return "\n\n".join(selected)
    return _limit(text, max_chars, fallback)


def _join_nonempty(parts: list[str], fallback: str, max_chars: int = 280) -> str:
    text = " ".join([part.strip() for part in parts if part and part.strip()])
    return _limit(text, max_chars, fallback)


def _strict_text(strict_blocks: dict[str, Any], key: str) -> str:
    value = strict_blocks.get(key) if isinstance(strict_blocks, dict) else None
    if isinstance(value, dict):
        return _meaningful(value.get("text") or value.get("summary"), "")
    return ""


def _strict_text_keep_breaks(strict_blocks: dict[str, Any], key: str) -> str:
    value = strict_blocks.get(key) if isinstance(strict_blocks, dict) else None
    if isinstance(value, dict):
        return _clean_keep_breaks(value.get("text") or value.get("summary"), "")
    return ""


def _rich_enough(value: Any, *, min_chars: int = 120) -> bool:
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


def _strict_bullets(strict_blocks: dict[str, Any], key: str) -> list[str]:
    value = strict_blocks.get(key) if isinstance(strict_blocks, dict) else None
    if not isinstance(value, dict):
        return []
    bullets = value.get("bullets")
    return [_clean(item) for item in bullets if _clean(item)] if isinstance(bullets, list) else []


def _strict_time_items(strict_blocks: dict[str, Any]) -> tuple[str, list[str]]:
    forecast = strict_blocks.get("time_forecast") if isinstance(strict_blocks.get("time_forecast"), dict) else {}
    intro = _meaningful(forecast.get("intro"), "")
    items = forecast.get("items") if isinstance(forecast.get("items"), list) else []
    cleaned: list[str] = []
    for item in items:
        if isinstance(item, dict):
            period = _clean(item.get("period"))
            text = _clean(item.get("text") or item.get("description"))
            value = f"{period} — {text}" if period and text else period or text
        else:
            value = _clean(item)
        if value:
            cleaned.append(_limit(value, 110, ""))
    return intro, cleaned[:3]


def _one_paragraph_item(text: str, fallback: str, max_chars: int = 260) -> list[str]:
    value = _meaningful(text, "")
    return [_clip_words(value, max_chars, fallback)] if value else []


def _format_factor_list(items: list[str], fallback: str = "зона глаз, лимфоток и нижняя треть") -> str:
    cleaned = [item.strip(" .,:;") for item in items if item and item.strip(" .,:;")]
    if not cleaned:
        return fallback
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} и {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])} и {cleaned[-1]}"


def _compact_item(value: Any, max_chars: int, fallback: str) -> str:
    if isinstance(value, dict):
        head = _meaningful(value.get("title") or value.get("focus") or value.get("factor") or value.get("zone") or value.get("mistake"), "")
        tail = _meaningful(
            value.get("expected_effect")
            or value.get("why_it_is_strength")
            or value.get("how_it_affects_face")
            or value.get("better_approach")
            or value.get("why_first"),
            "",
        )
        text = _join_nonempty([head, tail.replace("—", "").replace(":", "")], fallback, max_chars)
        return text
    return _limit(value, max_chars, fallback)


def _compact_skin_type_name(value: Any) -> str:
    text = _clean(value).lower()
    if not text or text in EMPTY_MARKERS:
        return "Комби, с ровной плотной базой"
    if any(marker in text for marker in ["normal", "норм"]):
        return "Комби, с ровной плотной базой"
    if any(marker in text for marker in ["комби", "combination", "mixed"]):
        if any(marker in text for marker in ["ровн", "плот"]):
            return "Комби, с ровной плотной базой"
        return "Комби, склонная к обезвоженности"
    if any(marker in text for marker in ["dry", "сух"]):
        return "Сухая, склонная к обезвоженности"
    if any(marker in text for marker in ["oily", "жир"]):
        return "Комби, активная в T-зоне"
    if any(marker in text for marker in ["sensitive", "чувств"]):
        return "Чувствительная, реактивная"
    return "Комби, склонная к обезвоженности"


def _skin_type_fallback_items(title: Any) -> list[str]:
    text = _clean(title).lower()
    if "сух" in text or "обезвож" in text:
        return [
            "Плюс: кожа хорошо держит нежный ухоженный вид.",
            "Центральной зоне нужно больше влаги.",
            "Уход и отток помогают коже выглядеть ровнее.",
        ]
    if "t-зон" in text or "т-зон" in text or "жир" in text:
        return [
            "Плюс: кожа плотная и держит каркас.",
            "T-зоне важны баланс и увлажнение.",
            "Ровный уход помогает чистому свечению.",
        ]
    if "чувств" in text or "реактив" in text:
        return [
            "Плюс: кожа хорошо отвечает на бережность.",
            "Ей важны восстановление и мягкий ритм.",
            "Спокойный уход возвращает ровное сияние.",
        ]
    return [
        "Плюс: кожа ровная и держит каркас лица.",
        "Зона глаз быстрее показывает недосып.",
        "Увлажнение и отток поддерживают ровное сияние.",
    ]


def _is_weak_skin_item(value: Any) -> bool:
    text = _clean(value).lower()
    if len(text) < 22:
        return True
    return any(
        marker in text
        for marker in [
            "хорошая текстура",
            "присутствует",
            "легкая отечность",
            "лёгкая отёчность",
            "лицо выглядит уставшим",
            "есть потенциал",
            "хороший ресурс",
            "хорошим ресурсом",
            "способность удерживать влагу",
            "эластичностью",
            "эластичност",
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
            "комбинированная с ровной плотной базой или смешанному",
            "хочется",
            "отёки по утрам",
            "отеки по утрам",
            "овал лица",
            "линия подбородка",
        ]
    )


def _is_skin_specific_item(value: Any) -> bool:
    text = _clean(value).lower()
    return any(
        marker in text
        for marker in [
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
        ]
    )


def _skin_type_items(title: Any, source_items: Any, fallback_items: list[str] | None = None) -> list[str]:
    result: list[str] = []
    source = source_items if isinstance(source_items, list) else []
    for item in source:
        cleaned = _limit(item, 74, "")
        if not cleaned or _is_weak_skin_item(cleaned) or not _is_skin_specific_item(cleaned):
            continue
        if cleaned not in result:
            result.append(cleaned)
    fallback_source = fallback_items if isinstance(fallback_items, list) else []
    clean_fallback = [
        _limit(item, 74, "")
        for item in fallback_source
        if _clean(item) and not _is_weak_skin_item(item)
    ]
    fallback = clean_fallback or _skin_type_fallback_items(title)
    for item in fallback:
        if len(result) >= 3:
            break
        if item not in result:
            result.append(item)
    return result[:3]


def _skin_type_description(value: Any, title: Any) -> str:
    text = _clean(value)
    if not text or "нормаль" in text.lower() or _is_weak_skin_item(text):
        return _limit(
            "Плюс кожи — она держит каркас; зоне глаз и центру лица важны увлажнение и мягкий отток.",
            95,
            "Плюс кожи — она держит каркас; важны увлажнение и мягкий отток.",
        )
    return _limit(text, 95, "Плюс кожи — она держит каркас; важны увлажнение и мягкий отток.")


def _skin_type_strength(value: Any) -> str:
    text = _clean(value)
    if not text or _is_weak_skin_item(text):
        return "Плюс кожи — ровная плотная база, которая хорошо держит каркас лица."
    return _limit(text, 92, "Плюс кожи — ровная плотная база, которая держит каркас лица.")


def _skin_type_care_focus(value: Any) -> str:
    text = _clean(value)
    if not text or _is_weak_skin_item(text):
        return "Главный уходовый фокус — увлажнение, мягкий отток и спокойный ритм."
    return _limit(text, 92, "Главный уходовый фокус — увлажнение, мягкий отток и спокойный ритм.")


def _rich_face_shape(value: Any) -> str:
    text = _clean(value).lower()
    if "прямоуголь" in text:
        return "Выразительная природная форма лица с хорошими пропорциями"
    if "овал" in text or "оваль" in text:
        return "Мягкий овал с природной базой и выразительной зоной глаз"
    if "круг" in text:
        return "Мягкая округлая форма лица с женственной природной базой"
    return _limit(sanitize_face_features_text(value), 92, "Гармоничная форма лица с мягкой природной базой")


def _rich_aging_label(value: Any, strict_text: Any = "") -> str:
    if isinstance(value, dict) and _clean(value.get("type_name")):
        return _clean(value.get("type_name")).upper()
    return aging_public_label(f"{_clean(value)} {_clean(strict_text)}").upper()


def _clip_words(value: Any, max_chars: int, fallback: str) -> str:
    text = _meaningful(value, fallback)
    if len(text) <= max_chars:
        return text
    words: list[str] = []
    for word in text.split():
        candidate = " ".join([*words, word])
        if len(candidate) > max_chars:
            break
        words.append(word)
    return (" ".join(words).strip(" .,:;—–-") or fallback).rstrip(".") + "."


def _status(value: Any, color: Any = None) -> str:
    cleaned = _clean(value).lower()
    color_cleaned = _clean(color).lower()
    if cleaned in {"good", "green", "всё хорошо", "все хорошо"} or color_cleaned in {"green", "зелёный", "зеленый"}:
        return "green"
    if cleaned in {"orange", "active", "активный фокус"} or color_cleaned in {"orange", "оранжевый"}:
        return "orange"
    if cleaned in {"priority", "red", "приоритет"} or color_cleaned in {"red", "красный"}:
        return "red"
    return "yellow"


def _first_number(value: Any, fallback: int = 30) -> int:
    match = re.search(r"\d{1,3}", _clean(value))
    if not match:
        return fallback
    return max(18, min(80, int(match.group(0))))


def _score(value: Any, fallback: int = 82) -> int:
    match = re.search(r"\d{1,3}", _clean(value))
    if not match:
        return fallback
    return max(0, min(100, int(match.group(0))))


def _int_value(value: Any, fallback: int, *, low: int, high: int) -> int:
    match = re.search(r"\d{1,3}", _clean(value))
    if not match:
        return fallback
    return max(low, min(high, int(match.group(0))))


def _date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    return _clean(value, datetime.now().strftime("%d.%m.%Y"))


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _photo_url(photo: str | None) -> str:
    if photo and photo.startswith(("http://", "https://", "data:", "file:")):
        return photo
    if photo:
        path = Path(photo).expanduser()
        candidates = [path]
        if not path.is_absolute():
            candidates.extend([settings.storage_root() / photo, _project_root() / "storage" / photo])
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve().as_uri()
    return ""


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


def _face_aging(analysis_json: dict[str, Any], personal_insight_json: dict[str, Any]) -> dict[str, Any]:
    face = analysis_json.get("face_type_and_aging_type") if isinstance(analysis_json.get("face_type_and_aging_type"), dict) else {}
    compact_face = analysis_json.get("face_type") if isinstance(analysis_json.get("face_type"), dict) else {}
    compact_aging = analysis_json.get("aging_type") if isinstance(analysis_json.get("aging_type"), dict) else {}
    morphotype = personal_insight_json.get("morphotype_story") if isinstance(personal_insight_json.get("morphotype_story"), dict) else {}
    selected_aging = _selected_aging_value(analysis_json, personal_insight_json=personal_insight_json)
    return {
        "shape": sanitize_face_features_text(_meaningful(face.get("face_type") or compact_face.get("shape"), "мягкий овал")),
        "aging": aging_public_label(_meaningful(selected_aging or morphotype.get("type") or face.get("aging_type") or compact_aging.get("type"), "tired_mixed")),
        "explanation": _meaningful(morphotype.get("diagnostic_summary") or face.get("explanation") or analysis_json.get("summary"), "Лицу полезны лимфодренаж, расслабление напряжённых зон и мягкая поддержка тонуса."),
    }


def _time_forecast(analysis_json: dict[str, Any], protocol_copy: dict[str, Any]) -> list[dict[str, str]]:
    forecast = analysis_json.get("time_forecast") if isinstance(analysis_json.get("time_forecast"), dict) else {}
    items = _list(protocol_copy.get("forecast"), [], 3)
    if items:
        periods = ["Через 2 недели", "Через 3–4 недели", "Через 6–8 недель"]
        return [{"period": periods[index], "description": _limit(item, 110, "может появиться больше свежести при регулярной практике.")} for index, item in enumerate(items[:3])]
    return [
        {"period": "Через 2 недели", "description": _meaningful(forecast.get("first_changes"), "визуально меньше отечности, взгляд свежее.")},
        {"period": "Через 3–4 недели", "description": _meaningful(forecast.get("visible_changes"), "мягче носогубная зона, лицо более открытое.")},
        {"period": "Через 6–8 недель", "description": _meaningful(forecast.get("stable_result"), "устойчивее тонус, овал выглядит собраннее.")},
    ]


def _zone_source(analysis_json: dict[str, Any], protocol_copy: dict[str, Any]) -> list[dict[str, Any]]:
    journal = _dict(analysis_json.get("journal_protocol"))
    journal_zone_map = _dict(journal.get("zone_map"))
    raw_zones = journal_zone_map.get("zones") if isinstance(journal_zone_map.get("zones"), list) else []
    if not raw_zones:
        raw_zones = analysis_json.get("zones") if isinstance(analysis_json.get("zones"), list) else []
    if not raw_zones:
        strict_blocks = _dict(analysis_json.get("strict_blocks")) or _dict(analysis_json.get("bella_protocol_v4"))
        strict_zone_map = _dict(strict_blocks.get("zone_map"))
        raw_zones = strict_zone_map.get("zones") if isinstance(strict_zone_map.get("zones"), list) else []
    if not raw_zones:
        raw_zones = protocol_copy.get("zones") if isinstance(protocol_copy.get("zones"), list) else []
    zones: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in raw_zones:
        if not isinstance(raw, dict):
            continue
        title = _clean(raw.get("name") or raw.get("label") or raw.get("zone"), "Зона внимания")
        title = _clean(raw.get("title") or title, "Зона внимания")
        zone_id = canonical_zone_id(title)
        if _clean(raw.get("id")):
            zone_id = canonical_zone_id(raw.get("id"))
        if zone_id == "overall" and len(zones) < len(DEFAULT_ZONES):
            zone_id = DEFAULT_ZONES[len(zones)]["id"]
        if zone_id in seen_ids:
            continue
        seen_ids.add(zone_id)
        visible = _limit(
            raw.get("what_is_visible") or raw.get("short_comment") or raw.get("issue") or raw.get("description"),
            80,
            "В этой зоне есть мягкий визуальный фокус.",
        )
        matters = _limit(
            raw.get("why_it_matters") or raw.get("reason"),
            80,
            "Зона влияет на ощущение свежести, открытости и собранности лица.",
        )
        action = _limit(
            raw.get("what_to_do") or raw.get("recommended_focus") or raw.get("recommendation"),
            80,
            "Лучше работать мягко и последовательно: лимфа, шея, затем тонус.",
        )
        zones.append(
            {
                "id": zone_id,
                "title": _limit(title, 24, "Зона внимания"),
                "status": _status(raw.get("status") or raw.get("level"), raw.get("color")),
                "description": visible,
                "what_is_visible": visible,
                "why_it_matters": matters,
                "what_to_do": action,
            }
        )
        if len(zones) >= 6:
            break
    for fallback in DEFAULT_ZONES:
        if len(zones) >= 6:
            break
        if fallback["id"] not in seen_ids:
            zones.append(fallback.copy())
            seen_ids.add(fallback["id"])
    return zones[:6]


def _zones_with_geometry(raw_zones: list[dict[str, Any]], geometry: dict[str, Any]) -> list[dict[str, Any]]:
    geometry_by_id = geometry.get("zones") if isinstance(geometry.get("zones"), dict) else {}
    result: list[dict[str, Any]] = []
    for index, zone in enumerate(raw_zones, start=1):
        zone_id = zone["id"]
        zone_geometry = geometry_by_id.get(zone_id) or geometry_by_id.get("overall") or {}
        result.append(
            {
                **zone,
                "number": index,
                "anchor": zone_geometry.get("anchor") or {"x": 50, "y": 50},
                "shape": zone_geometry.get("shape") or {"type": "ellipse", "x": 50, "y": 50, "width": 32, "height": 16},
            }
        )
    return result


def _stronger_status(current: str, candidate: str) -> str:
    rank = {"green": 0, "yellow": 1, "red": 2}
    return candidate if rank.get(candidate, 1) > rank.get(current, 1) else current


def _beauty_zone_map(raw_zones: list[dict[str, Any]], geometry: dict[str, Any]) -> list[dict[str, Any]]:
    geometry_by_id = geometry.get("zones") if isinstance(geometry.get("zones"), dict) else {}
    result: list[dict[str, Any]] = []
    for number, spec in enumerate(BEAUTY_ZONE_SPECS, start=1):
        matched = [zone for zone in raw_zones if zone.get("id") in spec["match_ids"]]
        status = None
        for zone in matched:
            zone_status = zone.get("status")
            if not zone_status:
                continue
            status = zone_status if status is None else _stronger_status(status, zone_status)
        status = status or spec["fallback_status"]
        description = _limit(
            next((zone.get("description") for zone in matched if zone.get("description")), None),
            78,
            spec["description"],
        )
        zone_id = spec["id"]
        zone_geometry = geometry_by_id.get(zone_id) or geometry_by_id.get("overall") or {}
        result.append(
            {
                "id": zone_id,
                "number": number,
                "title": spec["title"],
                "status": status,
                "description": description,
                "what_is_visible": description,
                "why_it_matters": description,
                "what_to_do": _limit(
                    next((zone.get("what_to_do") for zone in matched if zone.get("what_to_do")), None),
                    78,
                    "Работать мягко и последовательно, без перегруза зоны.",
                ),
                "anchor": zone_geometry.get("anchor") or {"x": 50, "y": 50},
                "shape": zone_geometry.get("shape") or {"type": "ellipse", "x": 50, "y": 50, "width": 32, "height": 16},
            }
        )
    return result


def build_face_zone_protocol_data(
    *,
    analysis_request_id: str,
    user_name: str,
    face_image_url: str,
    analysis_json: dict[str, Any] | None,
    protocol_copy: dict[str, Any] | None,
    personal_insight_json: dict[str, Any] | None,
    created_at: Any,
    zone_geometry: dict[str, Any],
) -> dict[str, Any]:
    analysis = analysis_json if isinstance(analysis_json, dict) else {}
    protocol = protocol_copy if isinstance(protocol_copy, dict) else {}
    insight = personal_insight_json if isinstance(personal_insight_json, dict) else {}
    journal = _dict(analysis.get("journal_protocol"))
    j_skin_age = _dict(journal.get("skin_age"))
    j_skin_type = _dict(journal.get("skin_type"))
    j_face_type = _dict(journal.get("face_type"))
    j_why = _dict(journal.get("why_happens"))
    j_age_changes = _dict(journal.get("age_changes"))
    j_strengths = _dict(journal.get("strengths"))
    j_benefits = _dict(journal.get("face_fitness_benefits"))
    j_forecast = _dict(journal.get("time_forecast"))
    j_growth = _dict(journal.get("growth_zones"))
    j_first_step = _dict(journal.get("first_step"))
    j_avoid = _dict(journal.get("what_to_avoid"))
    j_final = _dict(journal.get("final_summary"))
    strict_blocks = _dict(protocol.get("strict_blocks")) or _dict(analysis.get("strict_blocks")) or _dict(analysis.get("bella_protocol_v4"))
    selected_aging = _selected_aging_value(analysis, protocol, insight)
    selected_type_id = normalize_aging_classification(selected_aging)["type_id"]
    client_age = _int_value(
        _dict(strict_blocks.get("client")).get("age")
        or _dict(strict_blocks.get("skin_visual_age")).get("passport_age")
        or analysis.get("client_age"),
        30,
        low=16,
        high=90,
    )
    skin_age = _dict(analysis.get("skin_visual_age"))
    compact_skin_age = _dict(analysis.get("visual_skin_age"))
    skin_type = _dict(analysis.get("skin_type"))
    face = _face_aging(analysis, insight)
    source_zones = _zone_source(analysis, protocol)
    zones = _beauty_zone_map(source_zones, zone_geometry)
    source_priority_zones = [zone for zone in source_zones if zone["status"] in {"red", "yellow"}]
    priority_zones = [zone for zone in zones if zone["status"] in {"red", "yellow"}]
    priority_titles = [zone["title"] for zone in priority_zones][:5]
    focus_phrase = _format_factor_list(priority_titles[:3], "зона глаз, шея и нижняя треть")
    causes = _list(
        analysis.get("causes"),
        [
            "Замедленный лимфоток может делать зону глаз и среднюю треть визуально тяжелее.",
            "Напряжение шеи и жевательной зоны часто влияет на собранность овала.",
            "Недосып и мимическое напряжение быстрее проявляются во взгляде.",
        ],
        4,
    )
    raw_strengths = _list(
        analysis.get("strengths"),
        ["Мягкая природная форма выглядит выразительно.", "Скулы дают естественную опору.", "Плотная кожа держит контур."],
        4,
    )
    raw_benefits = _list(
        analysis.get("facefitness_benefits"),
        ["мягче взгляд после расслабления", "ярче скулы после оттока", "собраннее овал после шеи"],
        4,
    )
    summary = _meaningful(
        analysis.get("summary") or protocol.get("summary") or analysis.get("cta_recommendation"),
        "У лица сильная природная база; главный фокус — раскрыть взгляд и поддержать овал.",
    )

    skin_features = _list(skin_type.get("features"), [], 3)
    skin_strengths = _list(skin_type.get("strengths"), [], 2)
    skin_type_name = _compact_skin_type_name(j_skin_type.get("type_name") or skin_type.get("type"))
    skin_age_observation = _meaningful(
        j_skin_age.get("main_observation"),
        f"Кожа выглядит плотной и ухоженной; визуальный возраст больше задают {focus_phrase}.",
    )
    skin_age_factors = _list(
        j_skin_age.get("what_affects_age_perception"),
        [
            f"{focus_phrase} влияют на первое впечатление",
            "межбровье может делать взгляд строже",
            "нижней трети нужна мягкая поддержка собранности",
        ],
        3,
    )
    skin_age_focus = _meaningful(
        j_skin_age.get("main_focus"),
        "раскрыть свежесть, мягкость взгляда и собранный овал без изменения черт",
    )
    skin_age_description = _limit(_strict_text(strict_blocks, "skin_visual_age"), 280, "")

    strict_skin_type_text = _strict_text(strict_blocks, "skin_type")
    skin_type_description = _limit(strict_skin_type_text, 300, "")
    skin_type_items = _strict_bullets(strict_blocks, "skin_type")

    strict_aging_text = _strict_text(strict_blocks, "aging_type")
    face_shape = _rich_face_shape(j_face_type.get("face_shape") or face["shape"])
    aging_type = _rich_aging_label(selected_aging or j_face_type.get("aging_type") or face["aging"], strict_aging_text)
    mixed_components = mixed_combo_type_ids_from_payload(
        {
            "aging_type": _dict(selected_aging) or {"type_id": selected_type_id, "evidence": _list(j_face_type.get("what_appears_first"))},
            "strict_blocks": strict_blocks,
            "journal_protocol": journal,
            "zone_map": protocol.get("zone_map") or analysis.get("zone_map") or {},
            "analysis": analysis,
            "personal_insight": insight,
        }
    ) if selected_type_id == "tired_mixed" else []
    aging_type_display_name = build_aging_type_display_name(selected_type_id, mixed_components)
    age_changes_text = _limit_keep_breaks(
        _strict_text_keep_breaks(strict_blocks, "age_changes"),
        520,
        "",
    )
    future_changes_text = _limit(_strict_text(strict_blocks, "future_changes"), 520, "")
    face_scenario = _limit(strict_aging_text, 560, "")
    face_first = _list(
        j_face_type.get("what_appears_first"),
        [
            f"{focus_phrase} первыми меняют ощущение свежести",
            "носогубная зона зависит от мягкости средней трети",
            "овал лучше отвечает после шеи и лимфотока",
        ],
        3,
    )
    face_recommended_start = _meaningful(j_face_type.get("recommended_start"), "")
    if face_recommended_start:
        face_recommended_start = face_recommended_start[:1].upper() + face_recommended_start[1:]
    face_base_note = _meaningful(j_face_type.get("base_note"), "")

    mechanics = j_why.get("mechanics") if isinstance(j_why.get("mechanics"), list) else []
    if not mechanics:
        mechanics = []

    strict_strengths_text = _strict_text(strict_blocks, "face_strengths")
    strict_strengths_bullets = _strict_bullets(strict_blocks, "face_strengths")
    strengths_text_for_render = _limit(strict_strengths_text, 430, "")
    strengths_items = _one_paragraph_item(strengths_text_for_render, "", 420) or strict_strengths_bullets
    strengths_compact_bullets: list[str] = _compact_list(strict_strengths_bullets, [], limit=3, max_chars=92)

    strict_benefits_text = _strict_text(strict_blocks, "face_fitness_benefits")
    strict_benefits_bullets = _strict_bullets(strict_blocks, "face_fitness_benefits")
    benefits_text_for_render = _limit(strict_benefits_text, 430, "")
    sequence_items = _one_paragraph_item(benefits_text_for_render, "", 420) or strict_benefits_bullets
    benefits_compact_bullets: list[str] = strict_benefits_bullets

    strict_forecast_intro, strict_forecast_items = _strict_time_items(strict_blocks)
    forecast_items = strict_forecast_items
    priorities = j_growth.get("priorities") if isinstance(j_growth.get("priorities"), list) else []
    if not priorities:
        priorities = []

    first_step = {
        "title": _meaningful(j_first_step.get("title"), "Ваш первый шаг"),
        "action": _meaningful(j_first_step.get("action"), "Начните с мягкого лимфодренажа и расслабления шеи утром."),
        "duration": _meaningful(j_first_step.get("duration"), "3–5 минут"),
        "why_this": _meaningful(j_first_step.get("why_this"), "Это помогает подготовить взгляд, скулы и овал к упражнениям на тонус."),
        "expected_feeling": _meaningful(j_first_step.get("expected_feeling"), "Лицо может ощущаться легче, а взгляд — мягче."),
    }

    avoid_items = j_avoid.get("items") if isinstance(j_avoid.get("items"), list) else []
    if not avoid_items:
        avoid_items = [
            {
                "mistake": "Не давить агрессивно на зону под глазами.",
                "why_not": "эта область тонкая и может реагировать раздражением или большей отечностью",
                "better_approach": "работать через мягкий отток, шею и расслабление верхней трети",
            },
            {
                "mistake": "Не начинать с активной проработки овала при выраженной отечности.",
                "why_not": "сначала важно подготовить шею и отток, иначе тонус будет считываться слабее",
                "better_approach": "схема Bella Vladi: лимфа, шея, расслабление, затем упражнения",
            },
            {
                "mistake": "Не собирать хаотичные упражнения из интернета.",
                "why_not": "без последовательности легко перегрузить одну зону и не получить цельного эффекта",
                "better_approach": "идти по маршруту, который учитывает именно ваши зоны внимания",
            },
        ]

    strict_final_text = _strict_text(strict_blocks, "final_summary")
    strict_final_quote = _clean(_dict(strict_blocks.get("final_summary")).get("quote"), "")
    final_summary_text = _limit(strict_final_text, 320, "")

    data = {
        "protocol_version": _dict(strict_blocks).get("protocol_version") or "bella_face_protocol_v4",
        "brand": {
            "expert_name": "Bella Vladi",
            "protocol_name": "Face Protocol",
            "logo_text": "BV",
            "brand_line": "BELLA VLADI · FACE PROTOCOL",
        },
        "client": {
            "name": _clean(user_name, "Гость"),
            "date": _date(created_at),
            "age": client_age,
        },
        "images": {"face_image_url": face_image_url, "face_object_position": OBJECT_POSITION},
        "header": {
            "title": "Персональный протокол лица",
            "title_accent": "протокол",
            "subtitle": "Эстетический AI-разбор в формате журнала",
        },
        "skin_age": {
            "section_number": "01",
            "title": "Биологический возраст кожи",
            "age_value": _int_value(
                _dict(strict_blocks.get("skin_visual_age")).get("visual_age") or j_skin_age.get("age_value"),
                _first_number(skin_age.get("estimated_range") or compact_skin_age.get("range"), 30),
                low=18,
                high=80,
            ),
            "age_label": "лет",
            "score_label": "Состояние кожи",
            "score_value": _int_value(
                j_skin_age.get("score_value"),
                _score(skin_age.get("score") or compact_skin_age.get("confidence"), 82),
                low=0,
                high=100,
            ),
            "score_max": 100,
            "description": skin_age_description,
            "passport_age": _dict(strict_blocks.get("skin_visual_age")).get("passport_age") or skin_age.get("passport_age"),
            "age_delta": _dict(strict_blocks.get("skin_visual_age")).get("age_delta") or skin_age.get("age_delta"),
            "age_delta_label": _dict(strict_blocks.get("skin_visual_age")).get("age_delta_label") or skin_age.get("age_delta_label"),
            "main_observation": skin_age_observation,
            "what_affects_age_perception": skin_age_factors,
            "main_focus": skin_age_focus,
        },
            "skin_type": {
            "section_number": "02",
            "title": "Тип кожи",
            "type_name": skin_type_name,
            "description": skin_type_description,
            "features": skin_type_items,
            "strength": _skin_type_strength(j_skin_type.get("strength")),
            "care_focus": _skin_type_care_focus(j_skin_type.get("care_focus")),
            "items": skin_type_items,
        },
        "aging_profile": {
            "section_number": "04",
            "title": "Тип старения",
            "face_shape": face_shape,
            "aging_type": aging_type_display_name or aging_type,
            "combo_type_ids": mixed_components,
            "main_scenario": _clip_words(face_scenario, 560, ""),
            "recommended_start": _limit(face_recommended_start, 78, ""),
            "forecast_title": "Что проявляется первым:",
            "forecast_items": [_limit(item, 100, "") for item in face_first[:2]],
            "base_note": _limit(face_base_note, 88, ""),
        },
        "zone_map": {
            "section_number": "",
            "title": "Карта зон лица",
            "legend": [{"status": key, "label": label} for key, label in STATUS_LABELS.items()],
            "zones": zones,
            "contours": zone_geometry.get("contours") if isinstance(zone_geometry.get("contours"), dict) else {},
            "mediapipe": {
                "detected": bool(zone_geometry.get("detected")),
                "reason": zone_geometry.get("reason"),
            },
            "quality": zone_geometry.get("quality") if isinstance(zone_geometry.get("quality"), dict) else {},
        },
        "why_happens": {
            "section_number": "05",
            "title": "Какие изменения будут со временем",
            "description": _limit(
                future_changes_text,
                520,
                "",
            ),
            "subtitle": "Механика:",
            "mechanics": mechanics[:2],
            "items": (
                _one_paragraph_item(future_changes_text, "", 520)
                + _one_paragraph_item(age_changes_text, "", 430)
            )
            if future_changes_text
            else [],
            "conclusion": "",
        },
        "strengths": {"section_number": "03", "title": _meaningful(j_strengths.get("title"), "Ваши сильные стороны лица"), "items": strengths_items[:3], "compact_bullets": strengths_compact_bullets},
        "face_fitness_benefits": {
            "section_number": "07",
            "title": _meaningful(j_benefits.get("title"), "Что даст фейс-фитнес"),
            "text": benefits_text_for_render,
            "personal_sequence": sequence_items[:3],
            "items": sequence_items[:3],
            "compact_bullets": benefits_compact_bullets,
            "conclusion": "",
        },
        "time_forecast": {
            "section_number": "08",
            "title": _meaningful(j_forecast.get("title"), "Прогноз по времени"),
            "intro": strict_forecast_intro or "Если ты начнёшь заниматься по нашей системе:",
            "items": [_forecast_payload_item(item, index) for index, item in enumerate(forecast_items[:3])],
        },
        "growth_zones": {
            "section_number": "",
            "title": _meaningful(j_growth.get("title"), "Зоны роста"),
            "items": _list(j_growth.get("items"), [], 5),
            "priorities": priorities[:3],
            "text": _strict_text(strict_blocks, "growth_zones"),
        },
        "age_changes": {
            "section_number": "06",
            "title": _meaningful(j_age_changes.get("title"), "Первые изменения по возрасту"),
            "text": age_changes_text,
        },
        "first_step": {"section_number": "11", **first_step},
        "what_to_avoid": {
            "section_number": "12",
            "title": _meaningful(j_avoid.get("title"), "Чего не делать"),
            "items": [_compact_item(item, 105, "") for item in avoid_items[:2]],
        },
        "final_summary": {
            "label": "Итог",
            "text": _clip_words(final_summary_text, 260, ""),
            "main_conclusion": _meaningful(j_final.get("main_conclusion"), ""),
            "main_result_lever": _meaningful(j_final.get("main_result_lever"), ""),
            "start_with": _meaningful(j_final.get("start_with"), ""),
            "then_add": _meaningful(j_final.get("then_add"), ""),
            "expected_direction": _meaningful(j_final.get("expected_direction"), ""),
            "quote": strict_final_quote,
        },
        "footer": {
            "disclaimer": f"Это предварительный визуальный AI-разбор по фото. Не медицинское заключение и не замена консультации специалиста. ID · BV-{analysis_request_id}",
        },
        "meta": {"lead_id": analysis_request_id, "mediapipe_detected": bool(zone_geometry.get("detected"))},
        "strict_blocks": strict_blocks,
        "strengths_compliment": _meaningful(strengths_text_for_render or j_strengths.get("face_shape_compliment"), ""),
    }
    return _with_v3_template_aliases(data)


def _timeline_to_strings(items: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for item in items[:3]:
        if not isinstance(item, dict):
            result.append(_limit(item, 135, "При регулярной практике возможны мягкие визуальные изменения."))
            continue
        period = _meaningful(item.get("period"), "")
        description = _meaningful(item.get("description"), "могут появиться мягкие визуальные изменения.")
        result.append(f"{period} — {description}" if period else description)
    return result


def _forecast_payload_item(item: Any, index: int) -> dict[str, str]:
    default_periods = ["Через 2 недели", "Через 3–4 недели", "Через 6–8 недель"]
    if isinstance(item, dict):
        return {
            "period": _meaningful(item.get("period"), default_periods[min(index, 2)]),
            "description": _limit(item.get("description") or item.get("text"), 120, ""),
        }
    text = _clean(item)
    match = re.match(r"^(.+?)\s+[—–-]\s+(.+)$", text)
    if match:
        return {
            "period": match.group(1).strip(),
            "description": _limit(match.group(2).strip(), 120, ""),
        }
    return {
        "period": default_periods[min(index, 2)],
        "description": _limit(text, 120, ""),
    }


def _plain(value: Any) -> str:
    return _clean(value).strip(" .,:;—–-")


def _lower_first(value: Any) -> str:
    text = _plain(value)
    return text[:1].lower() + text[1:] if text else ""


def _compact_sentence(value: Any, max_chars: int, fallback: str) -> str:
    text = _meaningful(value, fallback)
    pieces = [piece.strip() for piece in re.split(r"(?<=[.!?])\s+", text) if piece.strip()]
    for piece in pieces:
        if len(piece) <= max_chars:
            return piece.rstrip(".") + "."
    return _clip_words(text, max_chars, fallback)


def _compact_list(items: Any, fallback: list[str], *, limit: int = 3, max_chars: int = 78) -> list[str]:
    source = items if isinstance(items, list) else []
    result: list[str] = []
    for item in source:
        text = _compact_sentence(item, max_chars, "")
        if not text or len(text) < 18:
            continue
        if text.count(".") > 1:
            text = _compact_sentence(text, max_chars, "")
        if text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    for item in fallback:
        if len(result) >= limit:
            break
        text = _compact_sentence(item, max_chars, item)
        if text not in result:
            result.append(text)
    return result[:limit]


def _compact_aging_name(value: Any) -> str:
    if isinstance(value, dict) and _clean(value.get("type_name")):
        return _clean(value.get("type_name"))
    return aging_public_label(value)


def _compact_aging_mechanics(value: Any) -> tuple[str, str]:
    return (aging_mechanics(value), aging_strategy(value))


def _compact_face_label(value: Any) -> str:
    text = sanitize_face_features_text(_plain(value))
    text = re.sub(r"\s*тип\s+лица\s*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .")
    text = text[:1].lower() + text[1:] if text else "мягкий овал с природной базой"
    return text


def _compact_future_bullets(aging_type: Any) -> list[str]:
    text = _clean(aging_type).lower()
    if "муск" in text:
        return [
            "Лоб и межбровье могут фиксировать более строгий взгляд.",
            "Жевательная зона может утяжелять нижнюю треть.",
            "Расслабление возвращает лицу мягкость выражения.",
        ]
    if "мелк" in text or "морщ" in text:
        return [
            "Кожа быстрее показывает сухость и мелкую сетку.",
            "Объемы щек могут выглядеть мягче без поддержки.",
            "Увлажнение и кровоток помогают сохранить живой вид.",
        ]
    if "деформа" in text:
        return [
            "Средняя треть может делать лицо визуально тяжелее.",
            "Овалу со временем нужно больше поддержки.",
            "Шея и лимфоток помогают сохранить собранность.",
        ]
    return [
        "Сначала заметнее считываются взгляд и носогубная зона.",
        "Средняя треть может делать лицо визуально тяжелее.",
        "Шея и лимфоток помогают сохранить собранный овал.",
    ]


def _compact_skin_bullets(skin_type_name: Any) -> list[str]:
    text = _clean(skin_type_name).lower()
    if "сух" in text or "обезвож" in text:
        return [
            "Плюс: кожа выглядит мягкой и ухоженной.",
            "Фокус: больше влаги и бережного восстановления.",
        ]
    if "t-зон" in text or "т-зон" in text or "жир" in text:
        return [
            "Плюс: кожа плотная и хорошо держит каркас.",
            "Фокус: баланс T-зоны и мягкое увлажнение.",
        ]
    if "чувств" in text or "реактив" in text:
        return [
            "Плюс: кожа хорошо отвечает на бережный ритм.",
            "Фокус: восстановление без перегруза.",
        ]
    return [
        "Плюс: ровная плотная база держит каркас.",
        "Фокус: увлажнение зоны глаз и центра лица.",
    ]


def _compact_forecast_items(
    items: Any,
    fallback: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Convert forecast items (dict or string) to compact {"period", "text"} format."""
    default_periods = ["Через 2 недели", "Через 3–4 недели", "Через 6–8 недель"]
    source = items if isinstance(items, list) else []
    result: list[dict[str, str]] = []
    for index, item in enumerate(source[:3]):
        if isinstance(item, dict):
            period = _meaningful(item.get("period"), default_periods[min(index, 2)])
            text = _limit(item.get("description") or item.get("text"), 110, "")
        else:
            text_raw = _clean(item)
            match = re.match(r"^(.+?)\s+[—–-]\s+(.+)$", text_raw)
            if match:
                period = match.group(1).strip()
                text = _limit(match.group(2).strip(), 110, "")
            else:
                period = default_periods[min(index, 2)]
                text = _limit(text_raw, 110, "")
        if period and text:
            result.append({"period": period, "text": text})
    if not result:
        return fallback[:3]
    while len(result) < 3 and len(fallback) > len(result):
        result.append(fallback[len(result)])
    return result[:3]


def _compact_protocol_payload(data: dict[str, Any]) -> dict[str, Any]:
    skin_age = _dict(data.get("skin_age"))
    skin_type = _dict(data.get("skin_type"))
    face_type = _dict(data.get("aging_profile") or data.get("face_type"))
    strengths = _dict(data.get("strengths"))
    benefits_block = _dict(data.get("face_fitness_benefits"))
    forecast = _dict(data.get("time_forecast"))
    growth = _dict(data.get("growth_zones"))
    final = _dict(data.get("final_summary"))

    face_shape = sanitize_face_features_text(_meaningful(face_type.get("face_shape"), ""))
    aging_name = _compact_aging_name(face_type.get("aging_type"))
    _, main_focus = _compact_aging_mechanics(face_type.get("aging_type"))
    growth_items = _list(growth.get("items"), [], 5)
    skin_age_short = _compact_sentence(
        skin_age.get("description"),
        176,
        "",
    )
    if "/" in skin_age_short or skin_age_short.count(",") > 1:
        skin_age_short = _compact_sentence(skin_age.get("description"), 176, "")

    compact = {
        "skin_visual_age": {
            "short_text": skin_age_short
        },
        "skin_type": {
            "short_text": _meaningful(skin_type.get("type_name"), ""),
            "bullets": _compact_list(skin_type.get("features") or skin_type.get("items"), [], limit=2, max_chars=92),
        },
        "face_and_aging_type": {
            "face_strengths": face_shape,
            "aging_type": aging_name,
            "main_focus": main_focus,
            "bullets": _compact_list(face_type.get("forecast_items"), [], limit=3, max_chars=100),
        },
        "future_changes": {
            "bullets": _compact_list(_dict(data.get("why_happens")).get("items"), [], limit=3, max_chars=100),
        },
        "face_strengths": {
            "bullets": _compact_list(
                strengths.get("compact_bullets") or strengths.get("items"),
                [],
                limit=3,
                max_chars=92,
            ),
        },
        "face_fitness_benefits": {
            "short_text": _compact_sentence(benefits_block.get("text"), 120, ""),
            "bullets": _compact_list(
                benefits_block.get("compact_bullets") or benefits_block.get("items") or benefits_block.get("personal_sequence"),
                [],
                limit=3,
                max_chars=92,
            ),
        },
        "time_forecast": {
            "basis": _meaningful(
                forecast.get("intro"),
                "Если ты начнёшь заниматься по нашей системе",
            ).rstrip(":"),
            "items": _compact_forecast_items(forecast.get("items"), []),
        },
        "growth_zones": {
            "summary": _meaningful(growth.get("text") or growth.get("summary"), ""),
            "items": growth_items,
        },
        "final_summary": {
            "text": _meaningful(final.get("text"), ""),
            "quote": _meaningful(
                "" if _looks_like_old_copy(final.get("quote")) else final.get("quote"),
                "",
            ),
        },
    }
    return compact


def _zone_anchor_value(value: Any, scale: float) -> float:
    number = float(value) if isinstance(value, (int, float)) or _clean(value).replace(".", "", 1).isdigit() else 50.0
    # The new mock template used a 300x385 SVG; MediaPipe data is stored in percent.
    return round(number / scale * 100, 2) if number > 100 else round(number, 2)


def _v3_template_zones(zone_map: dict[str, Any]) -> list[dict[str, Any]]:
    zones = zone_map.get("zones") if isinstance(zone_map.get("zones"), list) else []
    result: list[dict[str, Any]] = []
    for index, zone in enumerate(zones[:6], start=1):
        if not isinstance(zone, dict):
            continue
        anchor = _dict(zone.get("anchor"))
        result.append(
            {
                "id": index,
                "zone_id": zone.get("id") or f"zone_{index}",
                "name": _clean(zone.get("title"), f"Зона {index}"),
                "status": _status(zone.get("status")),
                "cx": _zone_anchor_value(anchor.get("x", 50), 300),
                "cy": _zone_anchor_value(anchor.get("y", 50), 385),
                "shape": zone.get("shape") or {},
                "anchor": anchor or {"x": 50, "y": 50},
            }
        )
    return result


def _v3_growth_areas(data: dict[str, Any]) -> list[dict[str, str]]:
    zone_map = _dict(data.get("zone_map"))
    zones = zone_map.get("zones") if isinstance(zone_map.get("zones"), list) else []
    areas: list[dict[str, str]] = []
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        status = _status(zone.get("status"))
        if status == "green" and len(areas) >= 3:
            continue
        areas.append({"name": _clean(zone.get("title"), "Зона внимания"), "status": status})
        if len(areas) >= 5:
            break
    if areas:
        return areas
    growth = _dict(data.get("growth_zones"))
    return [{"name": name, "status": "yellow"} for name in _list(growth.get("items"), [], 5)]


def _with_v3_template_aliases(data: dict[str, Any]) -> dict[str, Any]:
    """Add the compact schema expected by the uploaded face_protocol_v3 template."""

    skin_age = _dict(data.get("skin_age"))
    skin_type = _dict(data.get("skin_type"))
    face_type = _dict(data.get("aging_profile") or data.get("face_type"))
    zone_map = _dict(data.get("zone_map"))
    why = _dict(data.get("why_happens"))
    strengths = _dict(data.get("strengths"))
    benefits = _dict(data.get("face_fitness_benefits"))
    forecast = _dict(data.get("time_forecast"))
    final = _dict(data.get("final_summary"))
    images = _dict(data.get("images"))
    client = _dict(data.get("client"))
    strict_blocks = _dict(data.get("strict_blocks"))
    compact = _compact_protocol_payload(data)
    alias_type_id = normalize_aging_classification(_dict(strict_blocks.get("aging_type")) or face_type)["type_id"]
    alias_mixed_components = mixed_combo_type_ids_from_payload(data) if alias_type_id == "tired_mixed" else []
    alias_client_age = _int_value(
        client.get("age")
        or _dict(strict_blocks.get("client")).get("age")
        or _dict(strict_blocks.get("skin_visual_age")).get("passport_age"),
        30,
        low=16,
        high=90,
    )
    def _full_text(key: str, fallback: str = "") -> str:
        """Полный TZ-абзац из strict_blocks (нормализованный normalize.py)."""
        if key == "age_changes":
            return _strict_text_keep_breaks(strict_blocks, key) or fallback
        return _strict_text(strict_blocks, key) or fallback

    merged = dict(data)
    merged["compact_protocol"] = compact
    merged["user"] = {
        "name": _clean(client.get("name"), "Гость"),
        "date": _clean(client.get("date"), _date(datetime.now())),
    }
    merged["images"] = {
        **images,
        "face_url": images.get("face_image_url") or images.get("face_url") or "",
        "face_object_position": images.get("face_object_position") or OBJECT_POSITION,
    }
    merged["block_01_bio_age"] = {
        "estimated_age": skin_age.get("age_value") or 30,
        "passport_age": skin_age.get("passport_age") or _dict(strict_blocks.get("client")).get("age"),
        "score": skin_age.get("score_value") or 82,
        "description": _limit(
            _full_text("skin_visual_age", compact["skin_visual_age"]["short_text"]),
            300,
            compact["skin_visual_age"]["short_text"],
        ),
    }
    alias_skin_type_name = _meaningful(skin_type.get("type_name"), compact["skin_type"]["short_text"])
    merged["block_02_skin_type"] = {
        "type": alias_skin_type_name,
        "description": _limit(
            skin_type.get("description"),
            300,
            "",
        ),
        "features": _compact_list(skin_type.get("features") or skin_type.get("items"), [], limit=2, max_chars=92),
    }
    alias_strengths_text = _limit(
        data.get("strengths_compliment")
        or _dict(compact.get("face_strengths")).get("short_text")
        or " ".join(_dict(compact.get("face_strengths")).get("bullets") or []),
        430,
        "",
    )
    merged["block_03_strengths"] = {
        "compliment": alias_strengths_text,
        "items": compact["face_strengths"]["bullets"],
    }
    merged["block_04_face_aging"] = {
        "aging_type": build_aging_type_display_name(alias_type_id, alias_mixed_components),
        "description": _limit(_full_text("aging_type"), 560, ""),
        "bullets": compact["face_and_aging_type"]["bullets"],
    }
    merged["zone_map"] = {"zones": _v3_template_zones(zone_map), "contours": zone_map.get("contours") or {}, "quality": zone_map.get("quality") or {}}
    merged["block_05_why"] = {
        "text": _limit(_full_text("future_changes"), 520, ""),
        "reasons": compact["future_changes"]["bullets"],
    }
    age_changes = _dict(data.get("age_changes"))
    merged["block_06_age_changes"] = {
        "title": _meaningful(age_changes.get("title"), "Первые изменения по возрасту"),
        "text": _limit_keep_breaks(_full_text("age_changes"), 520, ""),
    }

    # Backward-compatible aliases for older previews/templates.
    merged["block_03_face_aging"] = merged["block_04_face_aging"]
    merged["block_04_zone_map"] = merged["zone_map"]
    merged["block_06_strengths"] = {
        "compliment": merged["block_03_strengths"]["compliment"],
        "items": merged["block_03_strengths"]["items"],
    }
    merged["block_07_facefitness_benefits"] = {
        "text": _limit(
            _meaningful(benefits.get("text"), ""),
            430,
            "",
        ),
        "items": compact["face_fitness_benefits"]["bullets"],
    }
    merged["block_08_timeline"] = {
        "intro": compact["time_forecast"]["basis"] + ":",
        "items": [
            f"{item['period']} — {item['text']}"
            for item in compact["time_forecast"]["items"]
        ],
    }
    merged["growth_areas"] = _v3_growth_areas(data)
    merged["growth_text"] = compact["growth_zones"]["summary"]
    merged["final_summary"] = _limit(_full_text("final_summary", compact["final_summary"]["text"]), 320, "")
    merged["tagline"] = compact["final_summary"]["quote"]
    return merged


def render_face_zone_protocol_v1(
    *,
    analysis_request_id: str,
    user_name: str,
    user_photo_path_or_url: str,
    analysis_json: dict[str, Any] | None,
    protocol_copy: dict[str, Any] | None,
    personal_insight_json: dict[str, Any] | None,
    output_dir: str,
    created_at: Any,
) -> str:
    logger.info("FACE_ZONE_PROTOCOL_RENDERER=journal_v1")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    html_path = output / f"face_zone_protocol_v1_{analysis_request_id}.html"
    output_path = output / f"face_zone_protocol_v1_{analysis_request_id}.png"
    template_path = Path(__file__).resolve().parent / "template.html"
    html_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")

    photo_url = _photo_url(user_photo_path_or_url)
    zone_geometry = detect_face_zone_geometry(user_photo_path_or_url, object_position=OBJECT_POSITION)
    data = build_face_zone_protocol_data(
        analysis_request_id=analysis_request_id,
        user_name=user_name,
        face_image_url=photo_url,
        analysis_json=analysis_json,
        protocol_copy=protocol_copy,
        personal_insight_json=personal_insight_json,
        created_at=created_at,
        zone_geometry=zone_geometry,
    )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Playwright is required for face_zone_protocol. Install playwright and Chromium.") from exc

    executable_path = _chromium_executable_path()
    with sync_playwright() as playwright:
        launch_kwargs: dict[str, Any] = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if executable_path:
            launch_kwargs["executable_path"] = executable_path
        browser = playwright.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": RENDER_WIDTH, "height": RENDER_HEIGHT}, device_scale_factor=1)
        page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        page.evaluate("document.body.classList.remove('full-readable-export')")
        page.evaluate("document.body.style.padding = '0'")
        page.evaluate("(payload) => window.renderProtocol && window.renderProtocol(payload)", data)
        try:
            page.evaluate("window.preloadProtocolImages && window.preloadProtocolImages()")
        except Exception:
            logger.warning("Zone protocol image preload hook failed", exc_info=True)
        if page.evaluate("document.fonts && document.fonts.ready ? true : false"):
            page.evaluate("document.fonts.ready")
        root = page.locator("#protocol-root")
        root.wait_for(state="visible", timeout=15_000)
        root.screenshot(path=str(output_path), type="png")
        browser.close()

    if not output_path.exists():
        raise RuntimeError("Expected face zone protocol PNG was not generated")
    return str(output_path)
