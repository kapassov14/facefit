from __future__ import annotations

import re
from typing import Any

from app.ai.aging_knowledge import aging_mechanics, aging_public_label, aging_strategy, normalize_aging_classification, sanitize_face_features_text
from app.ai.protocol_v4 import (
    build_age_changes_text,
    build_aging_type_text,
    build_future_changes_text,
    mixed_combo_type_ids_from_payload,
)
from app.reports.face_protocol_final.schema import DEFAULT_GROWTH_ZONES, DEFAULT_ZONES, EXAMPLE_PROTOCOL_COPY, ProtocolCopy

STATUS_VALUES = {"good", "attention", "priority"}

ALIASES = {
    "Область глаз / веки": "Зона глаз",
    "Нависшее веко / мешки под глазами": "Зона глаз",
    "Потеря овала / брыли": "Овал лица",
    "Второй подбородок": "Подбородок",
    "Отёчность и усталый вид": "Отёчность",
    "Отечность и усталый вид": "Отёчность",
    "Носогубные складки": "Носогубная зона",
    "Межбровная морщина": "Межбровье",
    "Межбровная зона": "Межбровье",
}


def _clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[*_`#>]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _apply_aliases(text: Any) -> str:
    cleaned = _clean_text(text)
    lowered = cleaned.lower()
    for source, replacement in ALIASES.items():
        if lowered == source.lower():
            return replacement
    for source, replacement in ALIASES.items():
        cleaned = re.sub(re.escape(source), replacement, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[Пп]роблем(а|ы|у|ой|е|ами|ах)?\b", "зона внимания", cleaned)
    cleaned = re.sub(r"\b[Бб]рыли\b", "снижение чёткости овала", cleaned)
    cleaned = re.sub(r"\b[Мм]ешки под глазами\b", "отёчность в зоне глаз", cleaned)
    cleaned = re.sub(r"\b[Нн]ормальная кожа\b", "кожа с ровной плотной базой", cleaned)
    cleaned = re.sub(r"\b[Нн]ормальная\b", "комбинированная с ровной плотной базой", cleaned)
    return cleaned


def _skin_type_title(value: Any) -> str:
    cleaned = _apply_aliases(value)
    lowered = cleaned.lower()
    if not lowered or lowered in {"normal", "unknown", "none", "не определено", "визуально не определено"}:
        return "Комби, с ровной плотной базой"
    if "норм" in lowered:
        return "Комби, с ровной плотной базой"
    if "сух" in lowered or "dry" in lowered or "обезвож" in lowered:
        return "Комби, склонная к обезвоженности" if "комби" in lowered else "Сухая, склонная к обезвоженности"
    if "жир" in lowered or "oily" in lowered or "t-зон" in lowered or "т-зон" in lowered:
        return "Комби, активная в T-зоне"
    if "чувств" in lowered or "sensitive" in lowered or "реактив" in lowered:
        return "Чувствительная, реактивная"
    if "комби" in lowered or "combination" in lowered or "смешан" in lowered:
        if "ровн" in lowered or "плот" in lowered:
            return "Комби, с ровной плотной базой"
        return "Комби, склонная к обезвоженности"
    return _shorten_text(cleaned, 42, "Комби, с ровной плотной базой")


def _skin_type_fallback_bullets(title: Any) -> list[str]:
    lowered = _clean_text(title).lower()
    if "сух" in lowered or "обезвож" in lowered:
        return [
            "Плюс: кожа хорошо держит нежный ухоженный вид.",
            "Центральной зоне нужно больше влаги и мягкости.",
            "При уходе и оттоке кожа выглядит ровнее.",
        ]
    if "t-зон" in lowered or "т-зон" in lowered or "жир" in lowered:
        return [
            "Плюс: кожа плотная и хорошо держит каркас лица.",
            "T-зоне важны баланс себума и мягкое увлажнение.",
            "Ровный уход помогает прийти к чистому свечению.",
        ]
    if "чувств" in lowered or "реактив" in lowered:
        return [
            "Плюс: кожа хорошо отвечает на бережный ритм.",
            "Ей важны мягкость, восстановление и без перегруза.",
            "Спокойный уход помогает вернуть ровное сияние.",
        ]
    return [
        "Плюс: кожа выглядит ровной и держит каркас лица.",
        "Зона глаз и центр лица быстрее показывают недосып.",
        "Увлажнение и отток поддерживают ровное сияние.",
    ]


def _face_aging_bullets_fallback(aging_type: Any) -> list[str]:
    key = _aging_type_key(aging_type)
    if key == "muscular":
        return [
            "Сильная мимика держит каркас, но может фиксировать межбровье.",
            "Жевательная зона влияет на строгость нижней трети.",
            "Старт — расслабление зажимов, затем мягкий тонус.",
        ]
    if key == "deformation":
        return [
            "Плотная база есть, но лимфа быстрее утяжеляет нижнюю треть.",
            "Шея влияет на отток и чёткость овала.",
            "Старт — осанка и лимфодренаж, потом овал.",
        ]
    if key == "wrinkled":
        return [
            "Контур может держаться хорошо, а кожа быстрее просит питания.",
            "Сетка и сухость заметнее без кровотока и увлажнения.",
            "Старт — мягкая стимуляция без агрессивной нагрузки.",
        ]
    # tired_mixed
    return [
        "Красивая база есть, но свежесть быстрее уходит через взгляд.",
        "Носослезная и носогубная зоны первыми показывают усталость.",
        "Старт — микроциркуляция, шея и мягкий тонус.",
    ]


def _is_weak_protocol_bullet(value: Any) -> bool:
    text = _clean_text(value).lower()
    if len(text) < 24:
        return True
    weak_markers = [
        "требует внимания",
        "есть потенциал",
        "общий тонус",
        "снижение тонуса мышц",
        "стратегию подбирать",
        "зона внимания",
        "склонен к отечности",
        "склонен к отёчности",
        "склонна к отечности",
        "склонна к отёчности",
        "деформационно-отечный и усталый типы",
    ]
    return any(marker in text for marker in weak_markers)


def _is_skin_specific_bullet(value: Any) -> bool:
    text = _clean_text(value).lower()
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


def _contentful_bullets(items: Any, *, fallback: list[str], limit: int, max_chars: int) -> list[str]:
    source = items if isinstance(items, list) else []
    result: list[str] = []
    for item in source:
        cleaned = _shorten_text(item, max_chars, "")
        if not cleaned or _is_weak_protocol_bullet(cleaned):
            continue
        if cleaned not in result:
            result.append(cleaned)
    for item in fallback:
        if len(result) >= limit:
            break
        shortened = _shorten_text(item, max_chars, item)
        if shortened not in result:
            result.append(shortened)
    return result[:limit]


def _is_weak_skin_bullet(value: Any) -> bool:
    text = _clean_text(value).lower()
    if len(text) < 22:
        return True
    weak_markers = [
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
        "хочется",
        "отёки по утрам",
        "отеки по утрам",
        "овал лица",
        "линия подбородка",
    ]
    return any(marker in text for marker in weak_markers)


def _skin_type_bullets(title: Any, items: Any) -> list[str]:
    fallback = _skin_type_fallback_bullets(title)
    source = items if isinstance(items, list) else []
    result: list[str] = []
    for item in source:
        cleaned = _shorten_text(item, 75, "")
        if not cleaned or _is_weak_skin_bullet(cleaned) or not _is_skin_specific_bullet(cleaned):
            continue
        if cleaned not in result:
            result.append(cleaned)
    for item in fallback:
        if len(result) >= 3:
            break
        if item not in result:
            result.append(item)
    return result[:3]


def _shorten_text(value: Any, max_chars: int, fallback: str) -> str:
    cleaned = _apply_aliases(value) or fallback
    if len(cleaned) <= max_chars:
        return cleaned

    for separator in (". ", "; ", ": ", ", ", " — ", " - ", " – "):
        head = cleaned.split(separator, 1)[0].strip(" .,:;—–-")
        if 8 <= len(head) <= max_chars:
            return _with_sentence_end(head, cleaned)

    words: list[str] = []
    for word in cleaned.split():
        candidate = " ".join([*words, word])
        if len(candidate) > max_chars:
            break
        words.append(word)
    shortened = " ".join(words).strip(" .,:;—–-")
    return _with_sentence_end(shortened or fallback[:max_chars].strip(" .,:;—–-"), cleaned)


def _with_sentence_end(text: str, source: str) -> str:
    if not text:
        return text
    if source.strip().endswith((".", "!", "?")) and not text.endswith((".", "!", "?")):
        return f"{text}."
    return text


def _status(value: Any) -> str:
    cleaned = _clean_text(value).lower()
    if cleaned in STATUS_VALUES:
        return cleaned
    if cleaned in {"green", "зелёный", "зеленый"}:
        return "good"
    if cleaned in {"red", "красный"}:
        return "priority"
    return "attention"


def _limited_text_list(items: Any, *, limit: int, max_chars: int, fallback: list[str]) -> list[str]:
    source = items if isinstance(items, list) else []
    result = [_shorten_text(item, max_chars, fallback[0]) for item in source if _clean_text(item)]
    result = result[:limit]
    for item in fallback:
        if len(result) >= limit:
            break
        shortened = _shorten_text(item, max_chars, item)
        if shortened not in result:
            result.append(shortened)
    return result[:limit]


def _normalize_zones(items: Any) -> list[dict[str, Any]]:
    source = items if isinstance(items, list) else []
    zones: list[dict[str, Any]] = []
    for index, raw_zone in enumerate(source[:6], start=1):
        if not isinstance(raw_zone, dict):
            continue
        default = DEFAULT_ZONES[min(index - 1, len(DEFAULT_ZONES) - 1)]
        zones.append(
            {
                "number": int(raw_zone.get("number") or index),
                "label": _shorten_text(raw_zone.get("label") or raw_zone.get("name"), 22, default["label"]),
                "status": _status(raw_zone.get("status") or raw_zone.get("color")),
            }
        )

    for default_zone in DEFAULT_ZONES:
        if len(zones) >= 6:
            break
        if not any(zone["label"].lower() == default_zone["label"].lower() for zone in zones):
            zones.append(default_zone.copy())
    return zones[:6]


def _normalize_growth_zones(items: Any, zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source = items if isinstance(items, list) else []
    if not source:
        source = [
            {"label": zone["label"], "status": zone["status"]}
            for zone in zones
            if zone["status"] in {"priority", "attention"}
        ]
        source.extend(DEFAULT_GROWTH_ZONES)

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_zone in source:
        if len(result) >= 5:
            break
        if isinstance(raw_zone, dict):
            label = _shorten_text(raw_zone.get("label") or raw_zone.get("name"), 22, "Зона")
            status = _status(raw_zone.get("status") or raw_zone.get("color"))
        else:
            label = _shorten_text(raw_zone, 22, "Зона")
            status = "attention"
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append({"label": label, "status": status})

    for fallback in DEFAULT_GROWTH_ZONES:
        if len(result) >= 5:
            break
        key = fallback["label"].lower()
        if key not in seen:
            result.append(fallback.copy())
            seen.add(key)
    return result[:5]


def _score_value(value: Any) -> str:
    cleaned = _clean_text(value)
    if re.fullmatch(r"\d{1,3}/100", cleaned):
        return cleaned
    match = re.search(r"\d{1,3}", cleaned)
    if match:
        number = max(0, min(100, int(match.group(0))))
        return f"{number}/100"
    return "78/100"


def _insight_causes(personal_insight: dict[str, Any] | None) -> list[str]:
    insight = personal_insight if isinstance(personal_insight, dict) else {}
    items = insight.get("why_this_happens") if isinstance(insight.get("why_this_happens"), list) else []
    result: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        bullet = item.get("short_protocol_bullet")
        if not _clean_text(bullet):
            zone = _clean_text(item.get("zone"))
            visible = _clean_text(item.get("visible_sign"))
            mechanism = _clean_text(item.get("mechanism"))
            bullet = f"{zone}: {visible}. Причина — {mechanism}."
        if _clean_text(bullet):
            result.append(str(bullet))
    return result


def _insight_strengths(personal_insight: dict[str, Any] | None) -> list[str]:
    insight = personal_insight if isinstance(personal_insight, dict) else {}
    items = insight.get("strengths_explained") if isinstance(insight.get("strengths_explained"), list) else []
    result: list[str] = []
    for item in items:
        if isinstance(item, dict):
            bullet = item.get("short_protocol_bullet") or item.get("trait")
        else:
            bullet = item
        if _clean_text(bullet):
            result.append(str(bullet))
    return result


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _compact_parts(*parts: Any) -> str:
    values = [_apply_aliases(part).strip(" .,:;—–-") for part in parts if _clean_text(part)]
    return ". ".join(dict.fromkeys(values))


def _journal_strengths(journal: dict[str, Any]) -> list[str]:
    strengths = _as_dict(journal.get("strengths"))
    items = _as_list(strengths.get("items"))
    result: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        why = item.get("why_it_is_strength")
        enhance = item.get("how_to_enhance")
        text = _compact_parts(title, why or enhance)
        if text:
            result.append(text)
    return result


def _journal_benefits(journal: dict[str, Any]) -> list[str]:
    benefits = _as_dict(journal.get("face_fitness_benefits"))
    sequence = _as_list(benefits.get("personal_sequence"))
    result: list[str] = []
    for item in sequence:
        if not isinstance(item, dict):
            continue
        text = _compact_parts(item.get("focus"), item.get("expected_effect") or item.get("why_first"))
        if text:
            result.append(text)
    return result


def _journal_causes(journal: dict[str, Any]) -> list[str]:
    why = _as_dict(journal.get("why_happens"))
    mechanics = _as_list(why.get("mechanics"))
    result: list[str] = []
    for item in mechanics:
        if not isinstance(item, dict):
            continue
        factor = item.get("factor")
        effect = item.get("how_it_affects_face")
        helps = item.get("what_helps")
        text = _compact_parts(factor, effect, helps)
        if text:
            result.append(text)
    return result


def _journal_forecast(journal: dict[str, Any]) -> list[str]:
    forecast = _as_dict(journal.get("time_forecast"))
    items = _as_list(forecast.get("items"))
    result: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        period = _clean_text(item.get("period"))
        description = _clean_text(item.get("description"))
        text = f"{period} — {description}" if period and description else period or description
        if text:
            result.append(text)
    return result


def _journal_growth(journal: dict[str, Any]) -> list[dict[str, Any]]:
    growth = _as_dict(journal.get("growth_zones"))
    priorities = _as_list(growth.get("priorities"))
    result: list[dict[str, Any]] = []
    for item in priorities:
        if isinstance(item, dict) and _clean_text(item.get("zone")):
            result.append({"label": item.get("zone"), "status": "priority" if item.get("priority") == 1 else "attention"})
    for item in _as_list(growth.get("items")):
        if _clean_text(item):
            result.append({"label": item, "status": "attention"})
    return result


def _journal_final_summary(journal: dict[str, Any]) -> str:
    final = _as_dict(journal.get("final_summary"))
    return _compact_parts(
        final.get("main_conclusion"),
        final.get("main_result_lever"),
        final.get("start_with"),
        final.get("expected_direction"),
    )


def _aging_type_key(value: Any) -> str:
    """Возвращает внутренний ключ для switch-логики. Только 4 варианта."""
    type_id = normalize_aging_classification(value)["type_id"]
    if type_id == "deformation_edema":
        return "deformation"
    if type_id == "fine_wrinkle":
        return "wrinkled"
    if type_id == "tired_mixed":
        return "tired_mixed"
    return type_id  # muscular


def _aging_forecast_fallback(aging_type: Any) -> list[str]:
    key = _aging_type_key(aging_type)
    if key == "muscular":
        return [
            "Сначала: межбровье и лоб могут сильнее фиксировать выражение.",
            "После 40: без расслабления лицо может сохранять маску напряжения.",
            "Дальше: жевательные мышцы могут делать нижнюю треть строже.",
        ]
    if key == "deformation":
        return [
            "Сначала: утренняя припухлость может проходить не полностью.",
            "После 40: ткани тяжелее удерживают чёткость овала.",
            "Дальше: без лимфодренажа нижняя треть может выглядеть тяжелее.",
        ]
    if key == "wrinkled":
        return [
            "Сначала: кожа быстрее показывает сухость и мелкую сетку.",
            "Дальше: объёмы в висках и щёках могут уходить заметнее.",
            "После 45: важны кровоток и мягкая нагрузка без перегруза.",
        ]
    # tired_mixed — универсальный fallback
    return [
        "Сначала: лицо свежее утром и сильнее устаёт к вечеру.",
        "Дальше: уголки и носослезная зона могут читаться заметнее.",
        "Регулярность помогает поддерживать свежесть и микроциркуляцию.",
    ]


def _strong_base_fallback(analysis: dict[str, Any], insight: dict[str, Any]) -> str:
    strengths = _insight_strengths(insight) or analysis.get("strengths") or []
    text = " ".join(str(item) for item in strengths[:3]).lower()
    if any(word in text for word in ("скул", "челюст", "кост", "овал", "пропорц")):
        return "Скулы и пропорции дают лицу естественную опору — это сильная природная база."
    if "глаз" in text or "взгляд" in text:
        return "Выразительный взгляд — ваша сильная черта; его раскрывают отток и расслабление лба."
    if "кож" in text or "плот" in text:
        return "Плотная кожа хорошо держит форму — это ресурс для свежего, ухоженного вида."
    return "Форма лица и пропорции уже дают хорошую базу; задача — раскрыть их мягче."


def _why_intro_fallback(analysis: dict[str, Any], insight: dict[str, Any]) -> str:
    skin_type = analysis.get("skin_type") if isinstance(analysis.get("skin_type"), dict) else {}
    morphotype = insight.get("morphotype_story") if isinstance(insight.get("morphotype_story"), dict) else {}
    aging = analysis.get("face_type_and_aging_type") if isinstance(analysis.get("face_type_and_aging_type"), dict) else {}
    aging_type = morphotype.get("type") or aging.get("aging_type", "")
    key = _aging_type_key(aging_type)
    skin = _skin_type_title(skin_type.get("type")) if skin_type.get("type") else ""
    skin_part = f"Ваш тип кожи — {skin}; " if skin else ""
    if key == "muscular":
        return skin_part + "мускульный сценарий даёт сильный каркас, но гипертонус может делать выражение строже."
    if key == "deformation":
        return skin_part + "деформационно-отечный сценарий проявляется через лимфу, шею и тяжесть нижней трети."
    if key == "wrinkled":
        return skin_part + "мелкоморщинистый сценарий связан с сухостью, истончением и потерей мягкой опоры кожи."
    # tired_mixed
    return skin_part + "усталый / смешанный сценарий проявляется через тонус, микроциркуляцию, уголки и носогубную зону."


def _why_outro_fallback(aging_type: Any) -> str:
    key = _aging_type_key(aging_type)
    if key == "muscular":
        return "Поэтому старт — не силовые упражнения, а расслабление; потом тонус ложится мягче."
    if key == "deformation":
        return "Случайные упражнения слабее: без шеи и оттока нижняя треть обычно отвечает медленнее."
    if key == "wrinkled":
        return "Этому типу важна дозировка: мягкая стимуляция работает лучше агрессивной нагрузки."
    # tired_mixed
    return "Здесь важна связка: микроциркуляция, шея и средняя треть, а не отдельное упражнение."


def _morphotype_causes_fallback(aging_type: Any) -> list[str]:
    key = _aging_type_key(aging_type)
    if key == "muscular":
        return [
            "Лоб и межбровье в гипертонусе — выражение выглядит строже.",
            "Жевательные мышцы могут уплотнять нижнюю треть и усиливать асимметрию.",
            "Носогубная зона может читаться из-за мышечного зажима.",
            "Старт — расслабление зажимов, затем мягкая нагрузка.",
        ]
    if key == "deformation":
        return [
            "Шея и статика влияют на отток жидкости от лица.",
            "Лишняя жидкость растягивает ткани и утяжеляет контуры.",
            "Нижняя треть первой показывает смещение мягких тканей вниз.",
            "Старт — осанка и лимфодренаж, затем работа с овалом.",
        ]
    if key == "wrinkled":
        return [
            "Кожа теряет липиды и влагу — сетка проявляется быстрее.",
            "Объём в висках и щёках может уходить раньше овала.",
            "Контур долго сохраняется, но текстура требует поддержки.",
            "Старт — кровоток и мягкая работа без агрессивной нагрузки.",
        ]
    # tired_mixed
    return [
        "Снижение тонуса делает уголки и среднюю треть менее собранными.",
        "Микроциркуляция влияет на сияние и свежесть кожи.",
        "Носослезная и носогубная зоны первыми показывают усталость.",
        "Старт — микроциркуляция и мягкое возвращение тонуса.",
    ]


def _benefits_outro_fallback(analysis: dict[str, Any], insight: dict[str, Any], aging_type: Any) -> str:
    strengths = " ".join(_insight_strengths(insight) or analysis.get("strengths") or []).lower()
    key = _aging_type_key(aging_type)
    if any(word in strengths for word in ("скул", "овал", "челюст", "ше")):
        return "Когда шея и отток включены, скулы и овал читаются заметнее."
    if "глаз" in strengths or "взгляд" in strengths:
        return "Главный эффект даст связка: мягкий взгляд, шея и более лёгкая нижняя треть."
    if key == "deformation":
        return "Система нужна, чтобы сначала раскрыть свежесть, а потом мягко собирать овал."
    if key == "muscular":
        return "Сначала расслабление зажимов, затем тонус — так черты выглядят мягче."
    if key == "wrinkled":
        return "Мягкий кровоток и уход дают коже более живой, не перегруженный вид."
    # tired_mixed
    return "Система важна: порядок шагов раскрывает природную базу лица мягче."


def _benefits_fallback(aging_type: Any) -> list[str]:
    key = _aging_type_key(aging_type)
    if key == "muscular":
        return [
            "Сначала снимет гипертонус лба, межбровья и жевательных.",
            "Потом вернёт баланс между сильными и ослабленными зонами.",
            "Выражение может стать мягче без потери чёткого каркаса.",
        ]
    if key == "deformation":
        return [
            "Сначала поддержит лимфодренаж и статику шеи.",
            "Потом поможет нижней трети выглядеть легче.",
            "Овал и скулы могут читаться собраннее.",
        ]
    if key == "wrinkled":
        return [
            "Поддержит кровоток и питание тканей.",
            "Даст мягкую нагрузку без перегруза тонкой кожи.",
            "Поможет сохранить живой вид и объём.",
        ]
    # tired_mixed
    return [
        "Начнёт с микроциркуляции и общего тонуса.",
        "Поддержит уголки, носослезную и носогубную зоны.",
        "Поможет лицу выглядеть более отдохнувшим даже к вечеру.",
    ]


def _aging_public_name(value: Any) -> str:
    label = aging_public_label(value)
    forms = {
        "Мускульный": "мускульному сценарию",
        "Деформационно-отечный": "деформационно-отечному сценарию",
        "Мелкоморщинистый": "мелкоморщинистому сценарию",
        "Усталый / смешанный": "усталому / смешанному сценарию",
    }
    return forms.get(label, "усталому / смешанному сценарию")


def _aging_mechanics(value: Any) -> tuple[str, str, str]:
    key = _aging_type_key(value)
    if key == "muscular":
        return (
            "мимическое напряжение, межбровье, лоб и жевательные мышцы",
            "смещение тканей вниз",
            "расслабить зажимы, а затем мягко подключить тонус",
        )
    if key == "deformation":
        return (
            "лимфоток, шею и нижнюю треть",
            "глубокие морщины",
            "начать с шеи и лимфодренажа, а затем подключить овал",
        )
    if key == "wrinkled":
        return (
            "сухость, тонкость кожи и потерю мягкой опоры",
            "тяжесть нижней трети",
            "дать коже увлажнение, мягкий кровоток и бережную нагрузку",
        )
    # tired_mixed
    classification = normalize_aging_classification(value)
    return (
        aging_mechanics(classification),
        "глубокие морщины",
        aging_strategy(classification),
    )


_FUTURE_CHANGES: dict[str, str] = {
    "muscular": (
        "Без грамотного ухода межбровье и лоб могут фиксироваться глубже, а жевательные — делать лицо более напряженным. "
        "Мимические линии со временем становятся статичными, поэтому важно мягко снимать гипертонус."
    ),
    "deformation": (
        "Без грамотного ухода задержка жидкости может держаться дольше: ткани растягиваются, тяжелеют, под глазами заметнее отечность, "
        "а овал теряет четкость. Лимфодренаж, шея и осанка помогают вернуть легкость."
    ),
    "wrinkled": (
        "Без грамотного ухода сухость, тонкость кожи и мелкая сетка могут проявляться ярче. "
        "Лицо быстрее теряет объемы, кожа выглядит суше, поэтому важны питание тканей, кровоток и мягкая работа с мышцами."
    ),
    "tired_mixed": (
        "Без грамотного ухода лицо может быстрее уставать к вечеру: заметнее становятся зона глаз, носослезная борозда, "
        "носогубные складки и уголки рта. Микроциркуляция, мягкий тонус и лимфодренаж возвращают свежесть."
    ),
}

_AGE_CHANGES_STAGES: dict[str, list[tuple[str, str]]] = {
    # (age_bracket_text, what_happens)
    "muscular": [
        ("25–30 лет", "начинают проявляться мимические линии лба и межбровья"),
        ("30–35 лет", "вертикальные заломы в межбровье могут становиться глубже"),
        ("35–40 лет", "гипертонус жевательных делает нижнюю часть визуально тяжелее"),
        ("после 40", "мимические морщины легче переходят в статичные борозды"),
    ],
    "deformation": [
        ("25–30 лет", "утренняя отечность и одутловатость могут проходить медленнее"),
        ("30–35 лет", "задержка жидкости делает ткани тяжелее"),
        ("35–40 лет", "нижняя треть и овал быстрее теряют четкость"),
        ("после 40", "перерастянутая жидкостью кожа сложнее держит упругость"),
    ],
    "wrinkled": [
        ("25–30 лет", "заметнее сухость и тонкая сетка вокруг глаз"),
        ("30–35 лет", "кожа быстрее теряет эластичность и мягкую опору"),
        ("35–40 лет", "виски, щеки и губы могут терять объем"),
        ("после 40", "без кровотока и питания лицо выглядит суше"),
    ],
    "tired_mixed": [
        ("25–30 лет", "лицо может выглядеть свежим утром, но уставать к вечеру"),
        ("30–35 лет", "заметнее становятся носослезная зона, носогубка и уголки рта"),
        ("35–40 лет", "пастозность и дефицит объемов сильнее дают невыспавшийся вид"),
        ("после 40", "сочетание признаков требует комплексной поддержки"),
    ],
}


def _age_changes_text(type_key: str, user_age: int | None) -> str:
    """
    Генерирует текст блока «Изменения по возрасту» с учётом реального возраста пользователя.
    Показываем 2-3 ближайших к его возрасту стадии.
    """
    stages = _AGE_CHANGES_STAGES.get(type_key, _AGE_CHANGES_STAGES["tired_mixed"])
    # age brackets: 25-30, 30-35, 35-40, 40+
    brackets = [25, 30, 35, 40]

    def _stage_index(age: int) -> int:
        for i, b in enumerate(brackets):
            if age < b + 5:
                return i
        return len(brackets) - 1

    if user_age and 16 <= user_age <= 90:
        idx = _stage_index(user_age)
        # show current + next stage (or 2 future if still young)
        show = stages[idx: idx + 3] or stages[-2:]
        current_bracket, current_what = show[0]
        lines = [f"Для вашего типа старения в возрасте {current_bracket} обычно {current_what}."]
        for bracket, what in show[1:]:
            prefix = "В" if not bracket.startswith("после") else "После"
            bracket_clean = bracket.removeprefix("после ") if bracket.startswith("после") else bracket
            lines.append(f"{prefix} {bracket_clean} — {what}.")
    else:
        # no age — generic
        bracket1, what1 = stages[1]
        bracket2, what2 = stages[2]
        _, what3 = stages[3]
        lines = [
            f"Для вашего типа старения в возрасте {bracket1} обычно {what1}.",
            f"В {bracket2} — {what2}.",
            f"После 40 — {what3}.",
        ]
    lines.append("Сейчас — лучшее время начать.")
    return " ".join(lines)

_BENEFITS: dict[str, str] = {
    "muscular": (
        "Фейс-фитнес именно для вас — это не «качать лицо», а вернуть мягкость сильной мышечной базе. "
        "Когда расслабятся межбровье, лоб и жевательные, взгляд станет спокойнее, черты мягче, "
        "а четкий овал будет выглядеть еще благороднее."
    ),
    "deformation": (
        "Фейс-фитнес для вас начнет работать через шею, осанку и лимфодренаж. Когда улучшится отток, "
        "зона глаз выглядит легче, нижняя треть меньше утяжеляет лицо, а природные скулы и овал становятся заметнее."
    ),
    "wrinkled": (
        "Фейс-фитнес для вашего типа — это мягкое питание тканей изнутри: микроциркуляция, бережный тонус и увлажнение. "
        "Лицо может выглядеть более живым, кожа — спокойнее и свежее, а изящный контур сохранит свою природную красоту."
    ),
    "tired_mixed": (
        "Фейс-фитнес для вас — способ вернуть лицу отдохнувшее выражение без изменения черт. "
        "Работа с шеей, лимфотоком и мягким тонусом освежает взгляд, смягчает носогубную зону "
        "и помогает уголкам рта выглядеть легче."
    ),
}

_TIME_FORECAST: dict[str, list[str]] = {
    "muscular": [
        "Через 2 недели — лоб и межбровье могут стать заметно мягче, выражение лица — спокойнее.",
        "Через 3–4 недели — взгляд открывается, жевательная зона расслабляется, лицо выглядит менее напряжённым.",
        "Через 6–8 недель — более устойчивое расслабление мимических мышц, мягкость и открытость черт.",
    ],
    "deformation": [
        "Через 2 недели — визуально меньше утренней отёчности, лицо более собранное с утра.",
        "Через 3–4 недели — мягче носогубная зона, лицо более открытое и свежее.",
        "Через 6–8 недель — устойчивее лимфоток, овал выглядит чётче и собраннее.",
    ],
    "wrinkled": [
        "Через 2 недели — кожа может выглядеть более свежей и увлажнённой, мелкие линии — менее заметны.",
        "Через 3–4 недели — улучшается текстура, зона глаз и лба выглядит мягче.",
        "Через 6–8 недель — более стабильная мягкость кожи, ровнее тон и сияние.",
    ],
    "tired_mixed": [
        "Через 2 недели — взгляд может стать свежее, меньше ощущения усталости на лице.",
        "Через 3–4 недели — лицо более открытое, носогубная зона спокойнее.",
        "Через 6–8 недель — более стабильная свежесть, мягче мимика и чётче контур.",
    ],
}

_FINAL_SUMMARY: dict[str, str] = {
    "muscular": (
        "У вас красивое лицо с сильной природной базой. Главное сейчас — снять напряжение, которое делает черты строже и скрывает вашу настоящую мягкость. "
        "Именно для этого создан этот курс."
    ),
    "deformation": (
        "У вас красивое лицо с мягкой женственной базой. Главное сейчас — вернуть тканям легкость, поддержать шею и овал, чтобы природные черты раскрылись яснее. "
        "Именно для этого создан этот курс."
    ),
    "wrinkled": (
        "У вас красивое, изящное лицо с тонкой природной выразительностью. Главное сейчас — напитать ткани, оживить кровоток и вернуть коже свежесть. "
        "Именно для этого создан этот курс."
    ),
    "tired_mixed": (
        "У вас красивое лицо с сильной природной базой. Главное сейчас — вернуть свежесть взгляду, мягкий тонус и убрать усталость, которая прячет вашу настоящую красоту. "
        "Именно для этого создан этот курс."
    ),
}

_AGING_TYPE_TAIL: dict[str, str] = {
    "muscular": "Лицо с {shape} хорошо держит форму, но свежесть быстрее всего меняется через взгляд и лобно-межбровную зону.",
    "deformation": "Лицо с {shape} хорошо держит черты, но свежесть быстрее всего меняется через лимфоток, шею и нижнюю треть.",
    "wrinkled": "Лицо с {shape} долго сохраняет контур, но свежесть быстрее всего меняется через текстуру кожи и зону глаз.",
    "tired_mixed": "Лицо с {shape} хорошо сохраняет мягкость черт, но свежесть быстрее меняется через взгляд, носогубную зону и нижнюю треть.",
}


def _face_shape_phrase(value: Any) -> str:
    text = _clean_text(value).lower()
    if "прямоуголь" in text:
        return "выразительная природная форма лица с хорошими пропорциями"
    if "круг" in text:
        return "мягкая округлая форма лица"
    if "серд" in text or "треуг" in text:
        return "лицо с выразительной верхней третью"
    if "овал" in text or "оваль" in text:
        return "мягкий овал с природной базой и выразительной зоной глаз"
    return sanitize_face_features_text(value, "лицо с мягкой гармоничной формой")


def _zone_titles(zones: list[dict[str, Any]], *, limit: int = 4) -> list[str]:
    titles: list[str] = []
    for zone in zones:
        status = _clean_text(zone.get("status")).lower()
        if status in {"priority", "attention", "red", "yellow", "orange"}:
            title = _apply_aliases(zone.get("label") or zone.get("name"))
            if title and title not in titles:
                titles.append(title)
        if len(titles) >= limit:
            break
    for fallback in ["зона глаз", "шея", "нижняя треть", "межбровье"]:
        if len(titles) >= limit:
            break
        if fallback not in [item.lower() for item in titles]:
            titles.append(fallback)
    return titles[:limit]


def _format_list_ru(items: list[str], fallback: str) -> str:
    cleaned = []
    for item in items:
        text = _clean_text(item).strip(" .")
        if not text:
            continue
        text = text[:1].lower() + text[1:]
        cleaned.append(text)
    if not cleaned:
        return fallback
    if len(cleaned) == 1:
        return cleaned[0]
    return ", ".join(cleaned[:-1]) + " и " + cleaned[-1]


def _skin_plus(type_title: str) -> tuple[str, str, str]:
    text = type_title.lower()
    if "сух" in text or "обезвож" in text:
        return (
            "кожа хорошо держит нежный ухоженный вид",
            "центральная зона",
            "увлажнения и восстановления",
        )
    if "t-зон" in text or "т-зон" in text or "жир" in text:
        return (
            "кожа плотная и хорошо держит каркас лица",
            "T-зона",
            "баланса и мягкого увлажнения",
        )
    if "чувств" in text or "реактив" in text:
        return (
            "кожа хорошо отвечает на бережный ритм",
            "центральная зона",
            "мягкости и восстановления",
        )
    return (
        "кожа хорошо держит каркас лица и медленнее дает глубокие заломы",
        "зона глаз и центр лица",
        "увлажнения и мягкого ухода",
    )


def _strict_zone_text(zone: dict[str, Any]) -> str:
    title = _apply_aliases(zone.get("label") or zone.get("name")) or "Зона"
    status = _status(zone.get("status"))
    status_label = "сильная зона" if status == "good" else "приоритет" if status == "priority" else "зона внимания"
    if title.lower() in {"межбровье", "лоб"}:
        visible = "Зона может делать взгляд строже даже в спокойном лице"
        action = "Начинать лучше с расслабления, не с активных упражнений"
    elif "глаз" in title.lower():
        visible = "Она быстрее всего влияет на ощущение свежести"
        action = "Начинать лучше с мягкого оттока и расслабления верхней трети"
    elif "овал" in title.lower() or "ниж" in title.lower():
        visible = "Она влияет на собранность лица и линию подбородка"
        action = "Лучше подключать шею, лимфоток и мягкий тонус"
    elif "носогуб" in title.lower():
        visible = "Зона зависит от средней трети, оттока и мягкости мимики"
        action = "Лучше работать через лицо целиком, а не давить в складку"
    else:
        visible = "Она влияет на общее ощущение свежести и мягкости лица"
        action = "Лучше идти через бережный регулярный маршрут"
    return f"{title} — {status_label}. {visible}. {action}."


def _year_word(n: int) -> str:
    """Русское склонение слова «год» для числа n: 1 год, 2 года, 5 лет."""
    m10, m100 = n % 10, n % 100
    if 11 <= m100 <= 14:
        return "лет"
    if m10 == 1:
        return "год"
    if 2 <= m10 <= 4:
        return "года"
    return "лет"


def _bio_age_text(user_age: int | None, type_key: str, focus_phrase: str) -> str:
    """
    Биологический возраст кожи.
    Если паспортный возраст известен — показываем passport_age + 2.
    Мягкая формулировка: не пугаем, объясняем и мотивируем.
    """
    _ZONES_BY_TYPE = {
        "muscular":    "заломы в зоне межбровья и напряжение лба",
        "deformation": "лёгкая отёчность нижней трети и носогубки",
        "wrinkled":    "мелкая сетка в зоне глаз и сухость кожи",
        "tired_mixed": "заломы в зоне межбровья и носогубки, а также лёгкая усталость взгляда",
    }
    zones_desc = _ZONES_BY_TYPE.get(type_key, _ZONES_BY_TYPE["tired_mixed"])
    if user_age and 16 <= user_age <= 90:
        display = user_age + 2
        return (
            f"Визуально ваша кожа выглядит примерно на {display} {_year_word(display)} — чуть старше паспортного возраста. "
            f"Это не про саму кожу — она у вас плотная и ухоженная. "
            f"Добавляют годы {zones_desc}. "
            "Хорошая новость — это именно то, что легко поддаётся коррекции при правильном подходе."
        )
    return (
        f"Визуально ваша кожа выглядит примерно на свой возраст. "
        f"Это не про саму кожу: она плотная и ухоженная. Возраст могут добавлять {focus_phrase}. "
        "Хорошая новость — это именно те зоны, которые хорошо раскрываются через регулярную работу."
    )


def _strict_blocks_from_analysis(
    *,
    analysis: dict[str, Any],
    zones: list[dict[str, Any]],
    skin_type_title: str,
    face_shape: Any,
    aging_type: Any,
    skin_age_value: Any,
    forecast_items: list[str],
    strengths: list[str],
    user_age: int | None = None,
) -> dict[str, Any]:
    aging_name = _aging_public_name(aging_type)
    mechanics, not_dominant, first_focus = _aging_mechanics(aging_type)
    focus_zones = _zone_titles(zones, limit=4)
    focus_phrase = _format_list_ru(focus_zones[:3], "зона глаз, шея и нижняя треть")
    all_focus_phrase = _format_list_ru(focus_zones, "зона глаз, шея и нижняя треть")
    shape = _face_shape_phrase(face_shape)
    age = _first_number(skin_age_value, "30")
    skin_plus, skin_zone, skin_need = _skin_plus(skin_type_title)
    public_skin_title = _clean_text(skin_type_title)
    if public_skin_title.lower().startswith("комби"):
        tail = public_skin_title[5:].strip(" ,")
        if tail.startswith("с "):
            public_skin_title = f"комбинированная кожа {tail}"
        elif tail:
            public_skin_title = f"комбинированная кожа, {tail}"
        else:
            public_skin_title = "комбинированная кожа"
    strong_text = " ".join(str(item) for item in strengths[:3]).lower()
    cheekbones = "Скулы создают природную опору и мягкий лифтинг-эффект"
    eyes = "Глаза — ваша выразительная черта"
    if "глаз" in strong_text or "взгляд" in strong_text:
        eyes = "Глаза и мягкий разрез взгляда — ваша выразительная черта"
    if "скул" in strong_text:
        cheekbones = "Скулы уже создают природную опору и мягкий лифтинг-эффект"

    forecast = forecast_items[:3] if forecast_items else []
    while len(forecast) < 3:
        fallback = [
            "Через 2 недели — взгляд может стать мягче, меньше утреннего напряжения.",
            "Через 3–4 недели — лицо может выглядеть более открытым, а главные зоны спокойнее.",
            "Через 6–8 недель — может появиться более стабильная мягкость мимики и чёткость контура.",
        ][len(forecast)]
        forecast.append(fallback)

    type_key = _aging_type_key(aging_type)
    aging_tail = _AGING_TYPE_TAIL.get(type_key, _AGING_TYPE_TAIL["tired_mixed"]).format(shape=shape)

    # ── AI-сгенерированный journal_protocol ──────────────────────────────────
    journal = analysis.get("journal_protocol") or {}
    j_skin_age   = journal.get("skin_age") or {}
    j_skin_type  = journal.get("skin_type") or {}
    j_strengths  = journal.get("strengths") or {}
    j_face_type  = journal.get("face_type") or {}
    j_benefits   = journal.get("face_fitness_benefits") or {}
    j_why        = journal.get("why_happens") or {}
    j_age_changes = journal.get("age_changes") or {}
    j_forecast   = journal.get("time_forecast") or {}
    j_final      = journal.get("final_summary") or {}

    # ── БЛОК 01: Биологический возраст (AI-приоритет) ─────────────────────────
    # ТЗ-формат — это ПРИМЕР для ИИ. Берём персональный текст ИИ, шаблон — только fallback.
    ai_skin_age_text = _clean_text(j_skin_age.get("description") or j_skin_age.get("main_observation"))
    if len(ai_skin_age_text) < 40:
        ai_skin_age_text = _bio_age_text(user_age, type_key, focus_phrase)

    # ── БЛОК: Тип кожи ────────────────────────────────────────────────────────
    ai_skin_type_text = _clean_text(j_skin_type.get("description"))
    if not ai_skin_type_text or len(ai_skin_type_text) < 30:
        ai_skin_type_text = (
            f"У вас {public_skin_title.lower()}. Плюс этого типа — {skin_plus}. "
            f"{skin_zone.capitalize()} просит чуть больше {skin_need}. "
            "При правильной системе кожа может выглядеть заметно свежее, ровнее — "
            "кожа может выглядеть ровнее и свежее при регулярном уходе."
        )

    # ── БЛОК: Ваши сильные стороны ────────────────────────────────────────────
    strength_items = j_strengths.get("items") or []
    if strength_items and isinstance(strength_items, list):
        parts: list[str] = []
        for idx, item in enumerate(strength_items[:4]):
            if not isinstance(item, dict):
                continue
            title = _clean_text(item.get("title"))
            why   = _clean_text(item.get("why_it_is_strength"))
            if not title:
                continue
            if idx == 0:
                # Первый айтем: "У вас {title} — {why}."
                phrase = f"У вас {title.lower()} — {why.rstrip('.')}." if why else f"У вас {title.lower()}."
            else:
                phrase = f"{title} — {why.rstrip('.')}." if why else f"{title}."
            parts.append(phrase)
        if parts:
            parts.append(
                "Фейсфитнес здесь нужен не чтобы менять лицо, "
                "а чтобы раскрыть то, что уже красиво от природы."
            )
        ai_face_strengths = " ".join(parts)
    else:
        ai_face_strengths = (
            f"У вас {shape} — это красивая выразительная форма, которую многие хотят получить через процедуры, а у вас есть от природы. "
            f"{cheekbones} — они создают тот самый эффект подтянутости, который так ценится. "
            f"{eyes} — это ваша визитная карточка. "
            "Кожа и пропорции уже создают сильную природную базу, которая будет работать на вас с возрастом. "
            "Фейсфитнес здесь нужен не чтобы менять лицо, а чтобы раскрыть то, что уже красиво от природы."
        )

    # ── БЛОК: Тип старения ──────────────────────────────────────────────────
    # Блок 04 — только из базы знаний выбранного типа. AI выбирает тип, но
    # описание не берем из journal/main_scenario, чтобы не смешивать сценарии.
    _PROTOCOL_TYPE_ID_BY_KEY = {
        "muscular": "muscular",
        "deformation": "deformation_edema",
        "wrinkled": "fine_wrinkle",
        "tired_mixed": "tired_mixed",
    }
    protocol_type_id = _PROTOCOL_TYPE_ID_BY_KEY.get(type_key, "tired_mixed")
    mixed_components = mixed_combo_type_ids_from_payload(
        {
            "aging_type": {"type_id": protocol_type_id, "evidence": _as_list(j_face_type.get("what_appears_first"))},
            "journal_protocol": journal,
            "analysis": analysis,
            "zones": zones,
            "strengths": strengths,
        }
    ) if protocol_type_id == "tired_mixed" else []
    ai_aging_text = _clean_text(
        j_face_type.get("main_scenario")
        or j_face_type.get("characteristic")
        or j_face_type.get("description")
    )
    kb_aging_text = ai_aging_text if len(ai_aging_text) >= 80 else build_aging_type_text(protocol_type_id, mixed_components)

    # ── БЛОК: Какие изменения будут со временем ──────────────────────────────
    # Блок 05 — только из базы знаний выбранного типа. Не берем AI/journal copy,
    # даже если он длинный: так исключаем смешение сценариев старения.
    ai_future_candidate = _clean_text(
        j_face_type.get("how_changes_over_time")
        or j_face_type.get("future_changes")
        or j_why.get("main_explanation")
        or j_why.get("description")
    )
    ai_future = ai_future_candidate if len(ai_future_candidate) >= 80 else build_future_changes_text(protocol_type_id, mixed_components)

    # ── БЛОК: Что даст фейс-фитнес ───────────────────────────────────────────
    # Формат ТЗ: цельный абзац. Если AI прислал длинный conclusion-абзац — берём его.
    # Иначе собираем плавный текст: вступление + последовательность как живые фразы.
    seq = j_benefits.get("personal_sequence") or []
    conclusion = _clean_text(j_benefits.get("conclusion"))
    if len(conclusion) >= 90:
        ai_benefits_text = conclusion
    elif seq and isinstance(seq, list) and any(isinstance(s, dict) for s in seq):
        intro = "Фейс-фитнес здесь — это мягкая работа с тем, что уже дано природой."
        sentences: list[str] = [intro]
        step_lead = ["Сначала", "Затем", "Дальше"]
        for idx, step in enumerate(seq[:3]):
            if not isinstance(step, dict):
                continue
            focus = _clean_text(step.get("focus") or step.get("why_first"))
            effect = _clean_text(step.get("expected_effect"))
            if focus and effect:
                effect_l = effect[0].lower() + effect[1:]
                sentences.append(f"{step_lead[min(idx, 2)]} — {focus.rstrip('.')}: {effect_l.rstrip('.')}.")
            elif effect:
                sentences.append(f"{effect[0].upper() + effect[1:].rstrip('.')}.")
        if conclusion and "раскры" not in conclusion.lower():
            sentences.append(conclusion.rstrip(".") + ".")
        else:
            sentences.append("Лицо будет выглядеть живее и отдохнувшим даже без макияжа.")
        ai_benefits_text = " ".join(sentences)
    else:
        ai_benefits_text = _BENEFITS.get(type_key, _BENEFITS["tired_mixed"])

    # ── БЛОК: Прогноз по времени ─────────────────────────────────────────────
    def _forecast_to_text(item: Any) -> str:
        """AI may return dicts {period, description} or plain strings."""
        if isinstance(item, dict):
            period = _clean_text(item.get("period"))
            description = _clean_text(item.get("description") or item.get("text"))
            if period and description:
                return f"{period} — {description}"
            return period or description
        return _clean_text(item)

    ai_forecast_items = [
        text for text in (_forecast_to_text(item) for item in (j_forecast.get("items") or []))
        if len(text) > 10
    ]
    if len(ai_forecast_items) < 3:
        fallback_forecast = _TIME_FORECAST.get(type_key, _TIME_FORECAST["tired_mixed"])
        while len(ai_forecast_items) < 3:
            ai_forecast_items.append(fallback_forecast[len(ai_forecast_items)])

    # ── БЛОК: Итог ───────────────────────────────────────────────────────────
    ai_final_text = (
        _clean_text(j_final.get("main_conclusion"))
        or _clean_text(analysis.get("summary"))
        or ""
    )
    if not ai_final_text or len(ai_final_text) < 30:
        ai_final_text = _FINAL_SUMMARY.get(type_key, _FINAL_SUMMARY["tired_mixed"])
    else:
        # Добавляем финальную мотивационную фразу если её нет
        lower = ai_final_text.lower()
        if "bella vladi" not in lower and "курс" not in lower:
            ai_final_text += " Именно для этого создан этот курс."

    return {
        "skin_visual_age": {
            "text": ai_skin_age_text
        },
        "skin_type": {
            "text": ai_skin_type_text
        },
        "face_strengths": {
            "text": ai_face_strengths
        },
        "aging_type": {
            "text": kb_aging_text
        },
        "future_changes": {
            "text": ai_future
        },
        "age_changes": {
            "text": _clean_text(j_age_changes.get("text") or j_age_changes.get("description"))
            or build_age_changes_text(protocol_type_id, user_age, mixed_components)
        },
        "face_fitness_benefits": {
            "text": ai_benefits_text
        },
        "time_forecast": {
            "intro": "Если вы начнёте заниматься по нашей системе:",
            "items": ai_forecast_items,
        },
        "growth_zones": {
            "text": (
                f"Главный фокус — {all_focus_phrase}. Именно они сильнее всего влияют на выражение лица, свежесть и овал. "
                f"Начинать лучше с {focus_zones[0]}, а затем подключать {_format_list_ru(focus_zones[1:], 'следующие зоны')}."
            )
        },
        "final_summary": {
            "text": ai_final_text
        },
        "zone_texts": [_strict_zone_text(zone) for zone in zones[:6]],
    }


def normalize_protocol_copy(protocol_copy: dict[str, Any] | None) -> dict[str, Any]:
    raw = protocol_copy if isinstance(protocol_copy, dict) else {}
    base = EXAMPLE_PROTOCOL_COPY | raw

    skin_age = base.get("skin_age") if isinstance(base.get("skin_age"), dict) else {}
    skin_type = base.get("skin_type") if isinstance(base.get("skin_type"), dict) else {}
    face_aging = base.get("face_aging") if isinstance(base.get("face_aging"), dict) else {}

    zones = _normalize_zones(base.get("zones"))
    normalized = {
        "skin_age": {
            "value": _shorten_text(skin_age.get("value"), 4, "32"),
            "unit": _shorten_text(skin_age.get("unit"), 8, "лет"),
            "comment": _shorten_text(skin_age.get("comment"), 110, EXAMPLE_PROTOCOL_COPY["skin_age"]["comment"]),
            "score": _score_value(skin_age.get("score")),
        },
        "skin_type": {
            "title": _skin_type_title(skin_type.get("title")),
            "bullets": _skin_type_bullets(skin_type.get("title"), skin_type.get("bullets")),
        },
        "face_aging": {
            "face_strengths": _shorten_text(
                sanitize_face_features_text(
                    face_aging.get("face_strengths") or face_aging.get("face_type"),
                    EXAMPLE_PROTOCOL_COPY["face_aging"]["face_strengths"],
                ),
                62,
                EXAMPLE_PROTOCOL_COPY["face_aging"]["face_strengths"],
            ),
            "aging_type": _shorten_text(aging_public_label(face_aging.get("aging_type")), 78, EXAMPLE_PROTOCOL_COPY["face_aging"]["aging_type"]),
            "bullets": _contentful_bullets(
                face_aging.get("bullets"),
                limit=3,
                max_chars=95,
                fallback=_face_aging_bullets_fallback(face_aging.get("aging_type")),
            ),
            "forecast": _limited_text_list(
                face_aging.get("forecast"),
                limit=3,
                max_chars=82,
                fallback=_aging_forecast_fallback(face_aging.get("aging_type")),
            ),
            "strong_base": _shorten_text(
                None if _is_weak_protocol_bullet(face_aging.get("strong_base")) else face_aging.get("strong_base"),
                110,
                EXAMPLE_PROTOCOL_COPY["face_aging"]["strong_base"],
            ),
        },
        "zones": zones,
        "causes": _limited_text_list(base.get("causes"), limit=4, max_chars=95, fallback=EXAMPLE_PROTOCOL_COPY["causes"]),
        "why_intro": _shorten_text(base.get("why_intro"), 180, EXAMPLE_PROTOCOL_COPY["why_intro"]),
        "why_outro": _shorten_text(base.get("why_outro"), 170, EXAMPLE_PROTOCOL_COPY["why_outro"]),
        "strengths": _limited_text_list(base.get("strengths"), limit=3, max_chars=75, fallback=EXAMPLE_PROTOCOL_COPY["strengths"]),
        "benefits": _limited_text_list(base.get("benefits"), limit=3, max_chars=75, fallback=EXAMPLE_PROTOCOL_COPY["benefits"]),
        "benefits_outro": _shorten_text(base.get("benefits_outro"), 130, EXAMPLE_PROTOCOL_COPY["benefits_outro"]),
        "forecast": _limited_text_list(base.get("forecast"), limit=3, max_chars=75, fallback=EXAMPLE_PROTOCOL_COPY["forecast"]),
        "growth_zones": _normalize_growth_zones(base.get("growth_zones"), zones),
        "final_summary": _shorten_text(base.get("final_summary"), 230, EXAMPLE_PROTOCOL_COPY["final_summary"]),
        "strict_blocks": base.get("strict_blocks") if isinstance(base.get("strict_blocks"), dict) else {},
    }
    return ProtocolCopy.model_validate(normalized).model_dump()


def _first_number(text: Any, fallback: str = "32") -> str:
    match = re.search(r"\d{1,3}", _clean_text(text))
    return match.group(0) if match else fallback


def build_protocol_copy_from_analysis(
    analysis_json: dict[str, Any],
    selected_problems: list[str] | None = None,
    personal_insight_json: dict[str, Any] | None = None,
    user_age: int | None = None,
) -> dict[str, Any]:
    analysis = analysis_json if isinstance(analysis_json, dict) else {}
    selected = selected_problems or []
    insight = personal_insight_json if isinstance(personal_insight_json, dict) else {}

    skin_age = analysis.get("skin_visual_age") if isinstance(analysis.get("skin_visual_age"), dict) else {}
    skin_type = analysis.get("skin_type") if isinstance(analysis.get("skin_type"), dict) else {}
    aging = analysis.get("face_type_and_aging_type") if isinstance(analysis.get("face_type_and_aging_type"), dict) else {}
    forecast = analysis.get("time_forecast") if isinstance(analysis.get("time_forecast"), dict) else {}
    journal = analysis.get("journal_protocol") if isinstance(analysis.get("journal_protocol"), dict) else {}
    j_skin_age = _as_dict(journal.get("skin_age"))
    j_skin_type = _as_dict(journal.get("skin_type"))
    j_face_type = _as_dict(journal.get("face_type"))
    j_benefits = _as_dict(journal.get("face_fitness_benefits"))
    j_why = _as_dict(journal.get("why_happens"))
    source_zones = analysis.get("zones") if isinstance(analysis.get("zones"), list) else []

    zones = [
        {
            "number": zone.get("number") or index,
            "label": zone.get("name") or zone.get("label"),
            "status": zone.get("status") or zone.get("color"),
        }
        for index, zone in enumerate(source_zones, start=1)
        if isinstance(zone, dict)
    ]

    features = []
    for key in ("strengths", "features", "attention_points"):
        value = skin_type.get(key)
        if isinstance(value, list):
            features.extend(value)
    if j_skin_type:
        features = [
            j_skin_type.get("strength"),
            *(_as_list(j_skin_type.get("features"))),
            j_skin_type.get("care_focus"),
            *features,
        ]

    growth = [
        {"label": problem, "status": "priority"}
        for problem in selected
    ]
    growth.extend({"label": zone.get("label"), "status": zone.get("status")} for zone in zones)

    insight_causes = _journal_causes(journal) or _insight_causes(insight)
    insight_strengths = _journal_strengths(journal) or _insight_strengths(insight)
    morphotype = insight.get("morphotype_story") if isinstance(insight.get("morphotype_story"), dict) else {}
    strategy = _journal_benefits(journal) or (insight.get("facefitness_strategy") if isinstance(insight.get("facefitness_strategy"), list) else [])
    aging_type = j_face_type.get("aging_type") or morphotype.get("type") or aging.get("aging_type")
    journal_forecast = _journal_forecast(journal)
    journal_growth = _journal_growth(journal)
    journal_final = _journal_final_summary(journal)
    skin_type_title = _skin_type_title(j_skin_type.get("type_name") or skin_type.get("type"))
    strict_blocks = _strict_blocks_from_analysis(
        analysis=analysis,
        zones=zones,
        skin_type_title=skin_type_title,
        face_shape=j_face_type.get("face_shape") or aging.get("face_type"),
        aging_type=aging_type,
        skin_age_value=j_skin_age.get("age_value") or skin_age.get("estimated_range"),
        forecast_items=journal_forecast
        or [
            forecast.get("first_changes"),
            forecast.get("visible_changes"),
            forecast.get("stable_result"),
        ],
        strengths=insight_strengths or analysis.get("strengths") or [],
        user_age=user_age,
    )
    if isinstance(analysis.get("strict_blocks"), dict) and analysis.get("strict_blocks"):
        strict_blocks = analysis["strict_blocks"]

    return normalize_protocol_copy(
        {
            "skin_age": {
                "value": _first_number(j_skin_age.get("age_value") or skin_age.get("estimated_range"), "32"),
                "unit": "лет",
                "comment": j_skin_age.get("description")
                or j_skin_age.get("main_observation")
                or skin_age.get("explanation")
                or EXAMPLE_PROTOCOL_COPY["skin_age"]["comment"],
                "score": _score_value(j_skin_age.get("score_value") or "78"),
            },
            "skin_type": {
                "title": skin_type_title,
                "bullets": features,
            },
            "face_aging": {
                "face_type": sanitize_face_features_text(j_face_type.get("face_shape") or aging.get("face_type")),
                "aging_type": aging_public_label(aging_type),
                "bullets": [
                    j_face_type.get("main_scenario"),
                    j_face_type.get("recommended_start"),
                    j_face_type.get("base_note"),
                    morphotype.get("why_this_type") or aging.get("explanation"),
                    morphotype.get("what_is_happening"),
                    morphotype.get("strategy"),
                    *[
                        f"{zone.get('label') or 'Зона'} — зона внимания."
                        for zone in zones
                        if zone.get("status") in {"priority", "attention", "red", "yellow"}
                    ],
                ],
                "forecast": journal_forecast or _aging_forecast_fallback(aging_type),
                "strong_base": j_face_type.get("base_note") or _strong_base_fallback(analysis, insight),
            },
            "zones": zones,
            "causes": insight_causes or _morphotype_causes_fallback(aging_type) or analysis.get("causes"),
            "why_intro": j_why.get("main_explanation") or _why_intro_fallback(analysis, insight),
            "why_outro": j_why.get("conclusion") or _why_outro_fallback(aging_type),
            "strengths": insight_strengths or analysis.get("strengths"),
            "benefits": strategy or analysis.get("facefitness_benefits") or _benefits_fallback(aging_type),
            "benefits_outro": j_benefits.get("conclusion") or _benefits_outro_fallback(analysis, insight, aging_type),
            "forecast": journal_forecast or [
                forecast.get("first_changes"),
                forecast.get("visible_changes"),
                forecast.get("stable_result"),
            ],
            "growth_zones": journal_growth or growth,
            "final_summary": journal_final
            or insight.get("final_personal_summary")
            or insight.get("main_leverage_point")
            or analysis.get("summary")
            or "В лице уже есть сильная природная база. Главный шаг сейчас — мягко снять лишнее напряжение и поддержать свежесть.",
            "strict_blocks": strict_blocks,
        }
    )
