from __future__ import annotations

import re
from typing import Any

# ─── Разрешённые типы (закрытая база Bella Vladi) ────────────────────────────
# Строго 4 типа — больше не добавлять.
AGING_TYPE_IDS = {
    "muscular",
    "deformation_edema",
    "fine_wrinkle",
    "tired_mixed",
}

AGING_TYPE_NAMES = {
    "muscular": "Мускульный",
    "deformation_edema": "Деформационно-отечный",
    "fine_wrinkle": "Мелкоморщинистый",
    "tired_mixed": "Усталый / смешанный",
}

# Карта «старое id → новое» для обратной совместимости
_LEGACY_ID_MAP: dict[str, str] = {
    "tired": "tired_mixed",
    "combined": "tired_mixed",
    "ptosis_gravity": "tired_mixed",
    "ptosis": "tired_mixed",
    "mixed": "tired_mixed",
    # прямые алиасы
    "muscular": "muscular",
    "deformation_edema": "deformation_edema",
    "deformation": "deformation_edema",
    "fine_wrinkle": "fine_wrinkle",
    "fine": "fine_wrinkle",
    "tired_mixed": "tired_mixed",
}

AGING_KNOWLEDGE: dict[str, dict[str, str]] = {
    "muscular": {
        "characteristic": (
            "Характерен для лиц с развитой мимической мускулатурой и генетически малым количеством "
            "подкожно-жировой клетчатки. Сильные мышцы плотно спаяны с кожей, поэтому овал лица "
            "может долго оставаться четким, но хронический гипертонус стягивает кожу в глубокие заломы."
        ),
        "what_inside": (
            "Отдельные группы мышц находятся в состоянии хронического гипертонуса, особенно жевательные, "
            "височные, лобная и круговая мышца глаза. Они буквально каменеют, укорачиваются и стягивают "
            "кожу в глубокие заломы. Мышцы-антагонисты, например щечные и подбородочные, без должной "
            "нагрузки слабеют и атрофируются, возникает дисбаланс натяжения тканей."
        ),
        "how_changes_over_time": (
            "Сначала формируются резкие вертикальные морщины в межбровье. "
            "Затем проявляются «рубленые» носогубные складки: они возникают не из-за провисания тканей, "
            "а из-за жесткого мышечного зажима. Гипертонус жевательных мышц делает лицо визуально более "
            "квадратным и тяжелым. После 40 лет может появляться нависание верхнего века как следствие "
            "спазма лобной мышцы."
        ),
        "what_if_nothing_changes": (
            "Мимические морщины переходят в статические глубокие борозды, которые видны даже в покое. "
            "Ткани в местах зажимов постепенно фиброзируются, а асимметрия может нарастать из-за "
            "доминирующей стороны жевания. Лицо выглядит старше именно из-за эффекта маски напряжения "
            "и потери мягкости черт."
        ),
        "main_focus": "Расслабление гипертонуса: межбровье, лоб, жевательные мышцы, мягкость мимики, баланс мышц.",
        "mechanics": "мимическое напряжение, межбровье, лоб и жевательные мышцы",
        "strategy": "сначала расслабление зажимов, затем мягкое восстановление баланса мышц",
    },
    "deformation_edema": {
        "characteristic": (
            "Сценарий со склонностью к задержке жидкости, избытку мягких тканей и утяжелению нижней трети. "
            "Под весом подкожного жира и лимфостаза ткани смещаются вниз, поэтому главный фокус — "
            "лимфоток, шея, осанка и поддержка четкости овала."
        ),
        "what_inside": (
            "Главная причина — застой лимфы и нарушение микроциркуляции. Мимические мышцы работают как насос, "
            "который проталкивает жидкость. Если они в спазме или слишком слабы, лимфодренаж замедляется. "
            "Зажатые мышцы шеи и сутулость буквально перекрывают пути оттока жидкости от лица."
        ),
        "how_changes_over_time": (
            "Лицо склонно к утренней одутловатости, которая лишь частично проходит к вечеру. "
            "Из-за постоянной лишней жидкости ткани растягиваются и тяжелеют. Под глазами формируется "
            "стойкая отечность, появляется пастозность и лунообразность контуров, цвет лица может становиться тусклее."
        ),
        "what_if_nothing_changes": (
            "Хронический застой лимфы приводит к растяжению связочного аппарата и кожи. "
            "Утренняя припухлость постепенно переходит в более выраженные деформации и тяжесть нижней трети. "
            "Такой сценарий лучше всего откликается на работу с осанкой и лимфодренажные техники на ранних этапах."
        ),
        "main_focus": "Лимфодренаж, шея, осанка, снятие отёчности, нижняя треть, микроциркуляция.",
        "mechanics": "лимфоток, шею, мягкие ткани, нижнюю треть и микроциркуляцию",
        "strategy": "сначала шея, осанка и лимфодренаж, затем мягкая поддержка нижней трети",
    },
    "fine_wrinkle": {
        "characteristic": (
            "Тип «печеного яблока», характерный для астенического телосложения и сухой тонкой кожи. "
            "Контур лица может долго сохраняться, но кожа быстрее теряет эластичность и требует мягкой поддержки."
        ),
        "what_inside": (
            "Основной процесс — истощение тканей. Подкожно-жировой слой не смещается вниз, а буквально тает, "
            "из-за чего кожа лишается естественной мягкой основы. Мышцы от природы тонкие и без нагрузки "
            "быстро слабеют, кровоток замедляется, кожа получает меньше питания изнутри."
        ),
        "how_changes_over_time": (
            "Лицо начинает терять объемы: первыми проваливаются виски и щеки, скулы выглядят более острыми. "
            "Губы истончаются, рано проявляются мелкие морщинки над верхней губой. Кожа вокруг глаз и на щеках "
            "покрывается сеточкой, при этом овал лица долго остается четким."
        ),
        "what_if_nothing_changes": (
            "Если не оживлять мышцы и не разгонять кровоток, лицо продолжит сохнуть. "
            "После 45 лет кожа может сильнее обтягивать костную основу из-за дефицита жировой и мышечной прослойки. "
            "Работа с мышцами здесь нужна, чтобы восстановить питание тканей и вернуть лицу живой вид."
        ),
        "main_focus": "Микроциркуляция, питание тканей, мягкая работа с мышцами, увлажнение, тонус без перегруза.",
        "mechanics": "сухость кожи, дефицит объёма, микроциркуляцию и мягкую мышечную опору",
        "strategy": "мягкая стимуляция кровотока, питание тканей и работа без перегруза",
    },
    "tired_mixed": {
        "characteristic": (
            "Усталый / смешанный сценарий объединяет физиологичное снижение тонуса и частое сочетание признаков "
            "нескольких морфотипов. Лицо может выглядеть свежим утром, но уставать к вечеру; изменения распределяются "
            "неравномерно по зонам."
        ),
        "what_inside": (
            "Ведущие механизмы — снижение тонуса мышц, ухудшение микроциркуляции, легкая пастозность и "
            "неравномерное распределение изменений. Например, нижняя часть может давать отечность, а верхняя — "
            "активную мимику; поэтому нужен комплексный подход."
        ),
        "how_changes_over_time": (
            "Появляется опущение уголков рта, углубляется носослезная борозда и носогубные складки, кожа теряет сияние. "
            "Лицо быстрее считывается как невыспавшееся, особенно к вечеру. При смешанном сценарии может сочетаться "
            "мелкая сетка вокруг глаз и деформация овала."
        ),
        "what_if_nothing_changes": (
            "Лицо может всё чаще выглядеть усталым даже после отдыха. Зона глаз, носогубная зона и уголки рта "
            "будут сильнее влиять на выражение. Смешанный сценарий требует комплексной работы: лимфодренаж, "
            "расслабление мышц и глубокое увлажнение."
        ),
        "main_focus": "Восстановление свежести, микроциркуляция, тонус, уголки рта, носослезная зона, мягкий лимфодренаж.",
        "mechanics": "тонус мышц, микроциркуляцию, носогубную зону и общую свежесть лица",
        "strategy": "сначала микроциркуляция, шея и мягкий тонус, затем носослезная зона и уголки рта",
    },
}

# ─── Публичные утилиты ────────────────────────────────────────────────────────

def clean_public_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\b[Пп]роблем(а|ы|у|ой|е|ами|ах)?\b", "зона внимания", text)
    text = re.sub(r"\b[Бб]рыли\b", "снижение чёткости овала", text)
    text = re.sub(r"\b[Мм]ешки под глазами\b", "отёчность в зоне глаз", text)
    text = text.replace("устало-отёчный тип", "усталый / смешанный тип")
    text = text.replace("устало-отечный тип", "усталый / смешанный тип")
    return re.sub(r"\s+", " ", text).strip()


def sanitize_face_features_text(
    value: Any,
    fallback: str = "мягкая природная форма лица, скуловая опора и выразительная зона глаз",
) -> str:
    text = clean_public_text(value)
    text = re.sub(r"\b[Оо]вальн\w*\s+тип\s+лица\b", "мягкая природная форма лица", text)
    text = re.sub(r"\b[Пп]рямоугольн\w*\s+тип\s+лица\b", "выразительная природная форма лица", text)
    text = re.sub(r"\b[Кк]ругл\w*\s+тип\s+лица\b", "мягкая округлая форма лица", text)
    text = re.sub(r"\b[Рр]омбовидн\w*\s+тип\s+лица\b", "выразительная скуловая опора", text)
    text = re.sub(r"\b[А-Яа-яA-Za-z-]+\s+тип\s+лица\b", "природная форма лица", text)
    text = re.sub(r"\b[Тт]ип лица\s*[—:-]?\s*", "Форма лица: ", text)
    text = re.sub(r"\s+", " ", text).strip(" .,:;")
    return text or fallback


def _markers(text: str) -> str | None:
    """Возвращает type_id по маркерам в тексте или None."""
    if any(word in text for word in ("муск", "гипертонус", "жеватель", "мимич", "muscular")):
        return "muscular"
    if any(word in text for word in ("деформа", "отеч", "отёч", "edema", "лимф", "пастоз")):
        return "deformation_edema"
    if any(word in text for word in ("мелк", "морщ", "fine", "wrinkle", "сух", "сетк")):
        return "fine_wrinkle"
    if any(word in text for word in ("устал", "tired", "носослез", "микроциркуля", "уголк",
                                     "птоз", "гравита", "gravity", "комбини", "смешан",
                                     "combined", "mixed")):
        return "tired_mixed"
    return None


def normalize_aging_classification(
    value: Any,
    *,
    fallback_text: Any = "",
    default_confidence: str = "medium",
) -> dict[str, Any]:
    """
    Нормализует любое представление типа старения в один из 4 разрешённых:
    muscular | deformation_edema | fine_wrinkle | tired_mixed
    """
    raw = value if isinstance(value, dict) else {}

    # Собираем весь текстовый контекст в нижнем регистре
    text = " ".join(
        clean_public_text(part).lower()
        for part in [
            raw.get("type_id"),
            raw.get("type_name"),
            raw.get("primary_type"),
            raw.get("secondary_type"),
            raw.get("combined_label"),
            fallback_text,
            value if not isinstance(value, dict) else "",
        ]
        if part is not None
    )

    # 1. Проверяем explicit type_id
    explicit = clean_public_text(raw.get("type_id") or "").lower().strip()
    if explicit in AGING_TYPE_IDS:
        type_id = explicit
    elif explicit in _LEGACY_ID_MAP:
        type_id = _LEGACY_ID_MAP[explicit]
    # 2. Маркерный поиск по всему тексту
    elif (detected := _markers(text)) is not None:
        type_id = detected
    # 3. Последний fallback
    else:
        type_id = "tired_mixed"

    confidence = clean_public_text(raw.get("confidence") or default_confidence).lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = default_confidence

    combined_label = clean_public_text(raw.get("combined_label") or "")
    if type_id != "tired_mixed" or not combined_label:
        combined_label = ""
    elif not any(marker in combined_label.lower() for marker in ("комбинирован", "+", "смешан")):
        combined_label = ""

    return {
        "type_id": type_id,
        "type_name": AGING_TYPE_NAMES[type_id],
        # Оставляем для обратной совместимости, но не используем как отдельный тип
        "primary_type": "",
        "secondary_type": "",
        "combined_label": combined_label,
        "confidence": confidence,
        "evidence_from_photo": raw.get("evidence_from_photo") if isinstance(raw.get("evidence_from_photo"), list) else [],
        "kb_source_used": True,
    }


def aging_public_label(classification: dict[str, Any] | str) -> str:
    data = normalize_aging_classification(classification)
    return AGING_TYPE_NAMES[data["type_id"]]


def build_aging_type_block(classification: dict[str, Any] | str) -> dict[str, str]:
    data = normalize_aging_classification(classification)
    info = AGING_KNOWLEDGE[data["type_id"]]
    user_type = AGING_TYPE_NAMES[data["type_id"]]
    text = (
        f"Ваш тип: {user_type}.\n\n"
        f"Характеристика этого типа:\n{info['characteristic']}\n\n"
        f"Как меняется лицо со временем:\n{info['how_changes_over_time']}\n\n"
        f"Что будет, если ничего не делать:\n{info['what_if_nothing_changes']}\n\n"
        f"Главный фокус фейсфитнеса:\n{info['main_focus']}"
    )
    return {
        "title": "Тип старения",
        "text": text,
        "characteristic": info["characteristic"],
        "how_changes_over_time": info["how_changes_over_time"],
        "what_if_nothing_changes": info["what_if_nothing_changes"],
        "main_focus": info["main_focus"],
    }


def aging_mechanics(type_or_classification: Any) -> str:
    data = normalize_aging_classification(type_or_classification)
    return AGING_KNOWLEDGE[data["type_id"]]["mechanics"]


def aging_strategy(type_or_classification: Any) -> str:
    data = normalize_aging_classification(type_or_classification)
    return AGING_KNOWLEDGE[data["type_id"]]["strategy"]


# ─── Валидация протокола ──────────────────────────────────────────────────────

ALLOWED_AGING_TYPES: frozenset[str] = frozenset(AGING_TYPE_IDS)

FORBIDDEN_PHRASES: list[str] = [
    "тип лица",
    "овальный тип лица",
    "круглый тип лица",
    "прямоугольный тип лица",
    "ромбовидный тип лица",
    "визуально не определено",
    "100%",
    "гарантированно",
    "минус 10 лет",
    "птозный тип",
    "гравитационный тип",
    "комбинированный тип",
    "ptosis_gravity",
]

_FORBIDDEN_RE = re.compile(
    "|".join(re.escape(p) for p in FORBIDDEN_PHRASES),
    re.IGNORECASE,
)

# Автоматические замены запрещённых фраз
_AUTO_REPLACE: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bпроблем(а|ы|у|ой|е|ами|ах)?\b", re.IGNORECASE), "зона внимания"),
    (re.compile(r"\bProblem\b", re.IGNORECASE), "attention zone"),
    (re.compile(r"\bптозный\s+(тип|сценарий)\b", re.IGNORECASE), "усталый / смешанный сценарий"),
    (re.compile(r"\bгравитационный\s+(тип|сценарий)\b", re.IGNORECASE), "усталый / смешанный сценарий"),
    (re.compile(r"\bкомбинированный\s+тип\b", re.IGNORECASE), "усталый / смешанный сценарий"),
    (re.compile(r"\bустало-отёчный\s+тип\b", re.IGNORECASE), "усталый / смешанный сценарий"),
    (re.compile(r"\bустало-отечный\s+тип\b", re.IGNORECASE), "усталый / смешанный сценарий"),
    (re.compile(r"\b[А-Яа-яA-Za-z-]+\s+тип\s+лица\b", re.IGNORECASE), "природная форма лица"),
    (re.compile(r"\bтип\s+лица\b", re.IGNORECASE), "форма лица"),
]


def sanitize_protocol_text(text: str) -> str:
    """Автоматически заменяет все запрещённые фразы в тексте."""
    for pattern, replacement in _AUTO_REPLACE:
        text = pattern.sub(replacement, text)
    return text


def validate_aging_type_id(type_id: Any) -> bool:
    """True если тип разрешён."""
    return str(type_id or "").lower().strip() in ALLOWED_AGING_TYPES


def validate_no_forbidden_phrases(text: str) -> list[str]:
    """Возвращает список найденных запрещённых фраз."""
    return _FORBIDDEN_RE.findall(text)
