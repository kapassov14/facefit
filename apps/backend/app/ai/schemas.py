from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.ai.aging_knowledge import (
    AGING_TYPE_NAMES,
    ALLOWED_AGING_TYPES,
    FORBIDDEN_PHRASES,
    aging_public_label,
    build_aging_type_block,
    normalize_aging_classification,
    sanitize_face_features_text,
    sanitize_protocol_text,
    validate_aging_type_id,
    validate_no_forbidden_phrases,
)
from app.core.config import settings
from app.ai.protocol_v4 import (
    PROTOCOL_VERSION as BELLA_PROTOCOL_V4,
    ProtocolValidationError,
    build_age_changes_text,
    build_future_changes_text,
    build_skin_type_text,
    is_skin_type_text_valid,
    protocol_v4_to_legacy_payload,
    validate_bella_protocol_v4,
)


def _clean_text(value: Any) -> str:
    return " ".join(("" if value is None else str(value)).split())


def _public_skin_type(value: Any) -> str:
    text = _clean_text(value)
    lowered = text.lower()
    if not lowered or lowered in {"normal", "unknown", "none", "не определено", "визуально не определено"}:
        return "комбинированная, с ровной плотной базой"
    if "норм" in lowered:
        return "комбинированная, с ровной плотной базой"
    if "смеш" in lowered or "комби" in lowered or "combination" in lowered or "mixed" in lowered:
        if "обезвож" in lowered or "сух" in lowered:
            return "комбинированная, склонная к обезвоженности"
        return "комбинированная, с ровной плотной базой"
    if "dry" in lowered or "сух" in lowered or "обезвож" in lowered:
        return "сухая, склонная к обезвоженности"
    if "oily" in lowered or "жир" in lowered or "t-зон" in lowered or "т-зон" in lowered:
        return "комбинированная, активная в T-зоне"
    if "sensitive" in lowered or "чувств" in lowered or "реактив" in lowered:
        return "чувствительная, реактивная"
    return text


def _public_text(value: Any) -> str:
    text = _clean_text(value)
    text = text.replace("проблема", "зона внимания").replace("Проблема", "Зона внимания")
    text = text.replace("нормальная кожа", "кожа с ровной плотной базой")
    text = text.replace("Нормальная кожа", "Кожа с ровной плотной базой")
    text = text.replace("нормальная", "комбинированная с ровной плотной базой")
    text = text.replace("Нормальная", "Комбинированная с ровной плотной базой")
    return text


class SkinVisualAge(BaseModel):
    estimated_range: str
    explanation: str
    confidence: Literal["low", "medium", "high"] = "medium"


class SkinType(BaseModel):
    type: str
    features: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    attention_points: list[str] = Field(default_factory=list)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: Any) -> str:
        return _public_skin_type(value)

    @field_validator("features", "strengths", "attention_points", mode="before")
    @classmethod
    def normalize_text_list(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [_public_text(item) for item in value if _public_text(item)]


class FaceTypeAndAgingType(BaseModel):
    face_type: str
    aging_type: str
    explanation: str

    @field_validator("face_type", mode="before")
    @classmethod
    def normalize_face_features(cls, value: Any) -> str:
        return sanitize_face_features_text(value)

    @field_validator("aging_type", mode="before")
    @classmethod
    def normalize_aging(cls, value: Any) -> str:
        return aging_public_label(value)

    @field_validator("explanation", mode="before")
    @classmethod
    def normalize_explanation(cls, value: Any) -> str:
        return _public_text(sanitize_face_features_text(value, _public_text(value)))


class Zone(BaseModel):
    number: int
    name: str
    status: Literal["good", "attention", "priority"]
    color: Literal["green", "yellow", "red"]
    short_comment: str
    reason: str
    recommended_focus: str


class TimeForecast(BaseModel):
    first_changes: str
    visible_changes: str
    stable_result: str


class JournalSkinAge(BaseModel):
    age_value: int | None = None
    score_value: int | None = None
    main_observation: str = ""
    what_affects_age_perception: list[str] = Field(default_factory=list)
    main_focus: str = ""
    description: str = ""


class JournalSkinType(BaseModel):
    type_name: str = ""
    description: str = ""
    features: list[str] = Field(default_factory=list)
    strength: str = ""
    care_focus: str = ""

    @field_validator("type_name", mode="before")
    @classmethod
    def normalize_type_name(cls, value: Any) -> str:
        return _public_skin_type(value)

    @field_validator("description", "strength", "care_focus", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return _public_text(value)

    @field_validator("features", mode="before")
    @classmethod
    def normalize_features(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [_public_text(item) for item in value if _public_text(item)]


class JournalFaceType(BaseModel):
    face_shape: str = ""
    aging_type: str = ""
    main_scenario: str = ""
    what_appears_first: list[str] = Field(default_factory=list)
    recommended_start: str = ""
    base_note: str = ""

    @field_validator("face_shape", mode="before")
    @classmethod
    def normalize_face_shape(cls, value: Any) -> str:
        return sanitize_face_features_text(value)

    @field_validator("aging_type", mode="before")
    @classmethod
    def normalize_journal_aging(cls, value: Any) -> str:
        return aging_public_label(value)

    @field_validator("main_scenario", "recommended_start", "base_note", mode="before")
    @classmethod
    def normalize_journal_text(cls, value: Any) -> str:
        return sanitize_face_features_text(_public_text(value), _public_text(value))


class JournalZone(BaseModel):
    id: str = ""
    number: int = 0
    title: str = ""
    status: Literal["green", "yellow", "red"] = "yellow"
    what_is_visible: str = ""
    why_it_matters: str = ""
    what_to_do: str = ""
    anchor: dict[str, float] = Field(default_factory=dict)
    shape: dict[str, Any] = Field(default_factory=dict)


class JournalMechanic(BaseModel):
    factor: str = ""
    how_it_affects_face: str = ""
    what_helps: str = ""


class JournalStrength(BaseModel):
    title: str = ""
    why_it_is_strength: str = ""
    how_to_enhance: str = ""


class JournalSequenceStep(BaseModel):
    step: int = 0
    focus: str = ""
    why_first: str = ""
    expected_effect: str = ""


class JournalPriority(BaseModel):
    priority: int = 0
    zone: str = ""
    why: str = ""


class JournalFirstStep(BaseModel):
    title: str = "Ваш первый шаг"
    action: str = ""
    duration: str = ""
    why_this: str = ""
    expected_feeling: str = ""


class JournalAvoidItem(BaseModel):
    mistake: str = ""
    why_not: str = ""
    better_approach: str = ""


class JournalFinalSummary(BaseModel):
    label: str = "Итог"
    main_conclusion: str = ""
    main_result_lever: str = ""
    start_with: str = ""
    then_add: str = ""
    expected_direction: str = ""
    quote: str = "«Именно для этого создан этот курс.»"


class JournalProtocol(BaseModel):
    skin_age: JournalSkinAge = Field(default_factory=JournalSkinAge)
    skin_type: JournalSkinType = Field(default_factory=JournalSkinType)
    face_type: JournalFaceType = Field(default_factory=JournalFaceType)
    zone_map: dict[str, Any] = Field(default_factory=dict)
    why_happens: dict[str, Any] = Field(default_factory=dict)
    strengths: dict[str, Any] = Field(default_factory=dict)
    face_fitness_benefits: dict[str, Any] = Field(default_factory=dict)
    time_forecast: dict[str, Any] = Field(default_factory=dict)
    growth_zones: dict[str, Any] = Field(default_factory=dict)
    first_step: JournalFirstStep = Field(default_factory=JournalFirstStep)
    what_to_avoid: dict[str, Any] = Field(default_factory=dict)
    final_summary: JournalFinalSummary = Field(default_factory=JournalFinalSummary)


class AgingClassification(BaseModel):
    # Строго 4 разрешённых типа — никакие другие не принимаются
    type_id: Literal["muscular", "deformation_edema", "fine_wrinkle", "tired_mixed"]
    type_name: str = ""
    primary_type: str = ""
    secondary_type: str = ""
    combined_label: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"
    evidence_from_photo: list[str] = Field(default_factory=list)
    kb_source_used: bool = True

    @model_validator(mode="before")
    @classmethod
    def normalize_model(cls, data: Any) -> dict[str, Any]:
        return normalize_aging_classification(data)


class FaceFeatureItem(BaseModel):
    feature: str = ""
    observation: str = ""
    why_it_is_beautiful: str = ""
    how_face_fitness_reveals_it: str = ""

    @field_validator("feature", "observation", "why_it_is_beautiful", "how_face_fitness_reveals_it", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return sanitize_face_features_text(value, _public_text(value))


class FaceFeatures(BaseModel):
    title: str = "Форма и сильные стороны лица"
    description: str = ""
    items: list[FaceFeatureItem] = Field(default_factory=list)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: Any) -> str:
        return "Форма и сильные стороны лица"

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: Any) -> str:
        return sanitize_face_features_text(value)


class AgingTypeBlock(BaseModel):
    title: str = "Тип старения"
    text: str = ""
    characteristic: str = ""
    how_changes_over_time: str = ""
    what_if_nothing_changes: str = ""
    main_focus: str = ""


class FaceAnalysis(BaseModel):
    skin_visual_age: SkinVisualAge
    skin_type: SkinType
    face_type_and_aging_type: FaceTypeAndAgingType
    zones: list[Zone]
    causes: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    facefitness_benefits: list[str] = Field(default_factory=list)
    time_forecast: TimeForecast
    summary: str
    cta_recommendation: str
    journal_protocol: JournalProtocol | None = None
    strict_blocks: dict[str, Any] | None = None
    aging_classification: AgingClassification | None = None
    face_features: FaceFeatures | None = None
    aging_type_block: AgingTypeBlock | None = None

    @model_validator(mode="before")
    @classmethod
    def enforce_closed_knowledge(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        result = dict(data)
        face_aging = result.get("face_type_and_aging_type") if isinstance(result.get("face_type_and_aging_type"), dict) else {}
        journal = result.get("journal_protocol") if isinstance(result.get("journal_protocol"), dict) else {}
        journal_face = journal.get("face_type") if isinstance(journal.get("face_type"), dict) else {}
        classification = normalize_aging_classification(
            result.get("aging_classification"),
            fallback_text=" ".join(
                str(item)
                for item in [
                    face_aging.get("aging_type"),
                    journal_face.get("aging_type"),
                    result.get("aging_type"),
                    result.get("summary"),
                ]
                if item
            ),
        )
        result["aging_classification"] = classification
        result["aging_type_block"] = result.get("aging_type_block") or build_aging_type_block(classification)

        public_aging = classification["combined_label"] or classification["type_name"]
        if face_aging:
            face_aging = dict(face_aging)
            face_aging["face_type"] = sanitize_face_features_text(face_aging.get("face_type"))
            face_aging["aging_type"] = public_aging
            face_aging["explanation"] = sanitize_face_features_text(face_aging.get("explanation"), _public_text(face_aging.get("explanation")))
            result["face_type_and_aging_type"] = face_aging
        if journal_face:
            journal = dict(journal)
            journal_face = dict(journal_face)
            journal_face["face_shape"] = sanitize_face_features_text(journal_face.get("face_shape"))
            journal_face["aging_type"] = public_aging
            journal_face["main_scenario"] = sanitize_face_features_text(journal_face.get("main_scenario"), _public_text(journal_face.get("main_scenario")))
            journal["face_type"] = journal_face
            result["journal_protocol"] = journal

        if not isinstance(result.get("face_features"), dict):
            description = sanitize_face_features_text(
                face_aging.get("face_type") or journal_face.get("face_shape") or result.get("summary")
            )
            result["face_features"] = {
                "title": "Форма и сильные стороны лица",
                "description": description,
                "items": [
                    {
                        "feature": "Природная база",
                        "observation": description,
                        "why_it_is_beautiful": "Черты не нужно менять: в них уже есть мягкость, баланс и опора.",
                        "how_face_fitness_reveals_it": "Фейсфитнес помогает раскрыть эту базу через шею, отток, расслабление и тонус.",
                    }
                ],
            }
        return result


class CompactSkinAge(BaseModel):
    range: str
    confidence: Literal["low", "medium", "high"] = "medium"
    explanation: str


class CompactSkinType(BaseModel):
    type: Literal["dry", "oily", "combination", "normal", "sensitive", "unknown"] = "unknown"
    features: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)


class CompactFaceType(BaseModel):
    shape: str
    description: str


class CompactAgingType(BaseModel):
    type: Literal["tired_mixed", "deformation_edema", "fine_wrinkle", "muscular",
                  # легаси алиасы для обратной совместимости старых ответов AI
                  "tired", "deformation", "mixed", "combined", "unknown"] = "unknown"
    description: str


class CompactZone(BaseModel):
    zone: Literal["under_eyes", "nasolabial", "jawline", "cheeks", "forehead", "eyelids", "neck", "overall"]
    level: Literal["green", "yellow", "red"]
    issue: str
    recommendation: str


class FaceAnalysisJson(BaseModel):
    visual_skin_age: CompactSkinAge
    skin_type: CompactSkinType
    face_type: CompactFaceType
    aging_type: CompactAgingType
    zones: list[CompactZone]
    summary: str
    recommended_focus: list[str] = Field(default_factory=list)
    offer_angle: str = ""


ANALYSIS_JSON_SCHEMA: dict = {
    "type": "object",
    "required": [
        "skin_visual_age",
        "skin_type",
        "face_type_and_aging_type",
        "zones",
        "causes",
        "strengths",
        "facefitness_benefits",
        "time_forecast",
        "summary",
        "cta_recommendation",
        "journal_protocol",
    ],
}


ZONE_LABELS = {
    "under_eyes": "Область под глазами",
    "nasolabial": "Носогубная зона",
    "jawline": "Овал лица",
    "cheeks": "Скулы и щеки",
    "forehead": "Лоб",
    "eyelids": "Веки",
    "neck": "Шея",
    "overall": "Общее впечатление",
}

AGING_LABELS = {
    "muscular": AGING_TYPE_NAMES["muscular"],
    "deformation_edema": AGING_TYPE_NAMES["deformation_edema"],
    "fine_wrinkle": AGING_TYPE_NAMES["fine_wrinkle"],
    "tired_mixed": AGING_TYPE_NAMES["tired_mixed"],
    # легаси алиасы
    "tired": AGING_TYPE_NAMES["tired_mixed"],
    "deformation": AGING_TYPE_NAMES["deformation_edema"],
    "mixed": AGING_TYPE_NAMES["tired_mixed"],
    "combined": AGING_TYPE_NAMES["tired_mixed"],
    "unknown": AGING_TYPE_NAMES["tired_mixed"],
}

SKIN_TYPE_LABELS = {
    "dry": "сухая",
    "oily": "жирная",
    "combination": "комбинированная",
    "normal": "комбинированная, с ровной плотной базой",
    "sensitive": "чувствительная",
    "unknown": "по фото ближе к комбинированной с ровной базой",
}


BELLA_CALLOUT_LABELS = {
    "morning_puffiness": "Зона отечности",
    "under_eye_area": "Область под глазами",
    "eye_area": "Область глаз / веки",
    "forehead_tension": "Лоб",
    "nasolabial_area": "Носогубная зона",
    "cheek_volume": "Скулы",
    "face_oval": "Овал лица",
    "jaw_tension": "Жевательная зона",
    "double_chin": "Подбородок",
    "neck": "Шея",
    "posture": "Осанка и шея",
    "skin_tone": "Тон кожи",
    "skin_texture": "Качество кожи",
    "facial_asymmetry": "Асимметрия лица",
}

BELLA_SEGMENT_AGING_TYPES = {
    "puffiness": "деформационно-отечный тип",
    "under_eye_area": "усталый тип",
    "eye_area": "усталый тип",
    "forehead_tension": "мускульный тип",
    "nasolabial_area": "усталый / смешанный тип",
    "face_oval": "деформационно-отечный тип",
    "jaw_tension": "мускульный тип",
    "double_chin": "деформационно-отечный тип",
    "neck": "деформационно-отечный тип",
    "posture": "деформационно-отечный тип",
    "skin_texture": "мелкоморщинистый тип",
    "skin_tone": "усталый тип",
    "facial_asymmetry": "усталый / смешанный тип",
    "general_freshness": "усталый тип",
}


def _string(value: Any, fallback: str = "", *fallbacks: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("проблема", "зона внимания").replace("Проблема", "Зона внимания")
    text = text.replace("проблемы", "зоны внимания").replace("Проблемы", "Зоны внимания")
    text = text.replace("брыли", "снижение чёткости овала").replace("Брыли", "Снижение чёткости овала")
    cleaned = " ".join(text.split())
    if cleaned:
        return cleaned
    for item in (fallback, *fallbacks):
        fallback_text = "" if item is None else str(item)
        fallback_text = fallback_text.replace("проблема", "зона внимания").replace("Проблема", "Зона внимания")
        fallback_text = fallback_text.replace("проблемы", "зоны внимания").replace("Проблемы", "Зоны внимания")
        fallback_text = fallback_text.replace("брыли", "снижение чёткости овала").replace("Брыли", "Снижение чёткости овала")
        cleaned_fallback = " ".join(fallback_text.split())
        if cleaned_fallback:
            return cleaned_fallback
    return ""


def _list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_string(item) for item in value if _string(item)]


def _status_from_bella_severity(value: Any) -> tuple[str, str]:
    severity = _string(value).lower()
    if severity == "green":
        return "good", "green"
    if severity in {"red", "orange"}:
        return "priority", "red" if severity == "red" else "yellow"
    return "attention", "yellow"


def bella_protocol_to_face_analysis(payload: dict[str, Any]) -> dict:
    point_a = payload.get("point_a") if isinstance(payload.get("point_a"), dict) else {}
    point_c = payload.get("point_c") if isinstance(payload.get("point_c"), dict) else {}
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    journal = payload.get("journal_protocol") if isinstance(payload.get("journal_protocol"), dict) else {}
    journal_skin_type = journal.get("skin_type") if isinstance(journal.get("skin_type"), dict) else {}
    journal_face_type = journal.get("face_type") if isinstance(journal.get("face_type"), dict) else {}
    a_callouts = point_a.get("face_callouts") if isinstance(point_a.get("face_callouts"), list) else []
    c_callouts = point_c.get("face_callouts") if isinstance(point_c.get("face_callouts"), list) else []
    c_by_id = {item.get("id"): item for item in c_callouts if isinstance(item, dict) and item.get("id")}

    zones: list[dict[str, Any]] = []
    for index, raw in enumerate(a_callouts[:9], start=1):
        if not isinstance(raw, dict):
            continue
        callout_id = _string(raw.get("id"))
        status, color = _status_from_bella_severity(raw.get("severity"))
        matching_result = c_by_id.get(callout_id) if callout_id else None
        zones.append(
            {
                "number": index,
                "name": _string(raw.get("title")) or BELLA_CALLOUT_LABELS.get(callout_id, "Зона внимания"),
                "status": status,
                "color": color,
                "short_comment": _string(raw.get("description"), "Визуально зона требует мягкого внимания."),
                "reason": _string(
                    raw.get("description"),
                    "На зону могут влиять лимфоток, мышечный тонус, осанка и мимические привычки.",
                ),
                "recommended_focus": _string(
                    matching_result.get("description") if isinstance(matching_result, dict) else None,
                    "Мягкий лимфодренаж, работа с тонусом мышц и поддержка шеи.",
                ),
            }
        )
    if not zones:
        zones.append(
            {
                "number": 1,
                "name": "Общее впечатление",
                "status": "attention",
                "color": "yellow",
                "short_comment": _string(point_a.get("short_description"), "Первый фокус — понять ведущую зону и ее механизм."),
                "reason": _string(point_a.get("short_description"), "Лицо лучше отвечает, когда шея, отток и тонус идут по порядку."),
                "recommended_focus": _string(point_c.get("short_description"), "Регулярная работа с лимфой, тонусом и осанкой."),
            }
        )

    pain = point_a.get("pain_block") if isinstance(point_a.get("pain_block"), dict) else {}
    life_impact = point_a.get("life_impact") if isinstance(point_a.get("life_impact"), dict) else {}
    result_block = point_c.get("result_block") if isinstance(point_c.get("result_block"), dict) else {}
    life_result = point_c.get("life_result") if isinstance(point_c.get("life_result"), dict) else {}
    benefits = _list_strings(result_block.get("items")) or _list_strings(life_result.get("items"))
    causes = _list_strings(pain.get("items")) + _list_strings(life_impact.get("items"))
    positive_zones = [zone["name"] for zone in zones if zone["status"] == "good"]
    strengths = positive_zones + benefits[:3]
    main_segment = _string(meta.get("main_segment"), "general_freshness")
    main_aging = BELLA_SEGMENT_AGING_TYPES.get(main_segment, "усталый / смешанный тип")
    forecast_focus = benefits or [_string(point_c.get("short_description"), "более свежий и собранный вид")]

    normalized = FaceAnalysis.model_validate(
        {
            "skin_visual_age": {
                "estimated_range": "визуально в пределах возрастной нормы",
                "explanation": _string(
                    point_a.get("short_description"),
                    "Кожа выглядит ресурсной; свежесть сильнее всего раскрывают взгляд, шея и мягкий овал.",
                ),
                "confidence": "medium",
            },
            "skin_type": {
                "type": _string(journal_skin_type.get("type_name"), "кожа с ровной базой, которая хорошо отвечает на отток"),
                "features": causes[:3] or [zone["short_comment"] for zone in zones[:3]],
                "strengths": strengths[:3] or ["Форма, скулы и кожа — природная база, которую раскрывают шея, отток и тонус."],
                "attention_points": [zone["name"] for zone in zones if zone["status"] in {"attention", "priority"}][:5],
            },
            "face_type_and_aging_type": {
                "face_type": _string(journal_face_type.get("face_shape"), "лицо с сохраненной формой и хорошей природной базой"),
                "aging_type": _string(journal_face_type.get("aging_type"), main_aging),
                "explanation": _string(
                    journal_face_type.get("main_scenario") or journal_face_type.get("recommended_start"),
                    point_a.get("short_description"),
                    "Главный фокус выбран по зонам, которые сильнее всего раскрывают свежесть и мягкость лица.",
                ),
            },
            "zones": zones,
            "causes": causes[:5] or [zone["reason"] for zone in zones[:5]],
            "strengths": strengths[:4] or ["У лица есть сильная природная база, которую можно раскрыть регулярной практикой."],
            "facefitness_benefits": benefits[:4] or [zone["recommended_focus"] for zone in zones[:4]],
            "time_forecast": {
                "first_changes": f"7-14 дней: {forecast_focus[0]}.",
                "visible_changes": f"4-6 недель: {forecast_focus[min(1, len(forecast_focus) - 1)]}.",
                "stable_result": "8-12 недель: более устойчивый визуальный эффект при регулярной практике.",
            },
            "summary": _string(point_a.get("short_description"), "У лица сильная природная база; главный фокус — мягко раскрыть свежесть и собранность."),
            "cta_recommendation": _string(
                point_c.get("short_description"),
                "Система Bella Vladi поможет раскрывать природную базу по понятной последовательности.",
            ),
            "journal_protocol": payload.get("journal_protocol") if isinstance(payload.get("journal_protocol"), dict) else None,
        }
    ).model_dump()
    normalized["bella_protocol"] = payload
    return normalized


def compact_analysis_to_face_analysis(payload: dict) -> dict:
    compact = FaceAnalysisJson.model_validate(payload)
    zones = []
    for index, zone in enumerate(compact.zones[:9], start=1):
        status = "good" if zone.level == "green" else "priority" if zone.level == "red" else "attention"
        zones.append(
            {
                "number": index,
                "name": ZONE_LABELS.get(zone.zone, zone.zone),
                "status": status,
                "color": zone.level,
                "short_comment": zone.issue,
                "reason": zone.issue,
                "recommended_focus": zone.recommendation,
            }
        )
    if not zones:
        zones.append(
            {
                "number": 1,
                "name": "Общее впечатление",
                "status": "attention",
                "color": "yellow",
                "short_comment": compact.summary,
                "reason": compact.summary,
                "recommended_focus": compact.offer_angle or "Мягкий регулярный face fitness без перенапряжения.",
            }
        )
    forecast_focus = compact.recommended_focus[:3] or [compact.offer_angle or "мягкая регулярная практика"]
    return FaceAnalysis.model_validate(
        {
            "skin_visual_age": {
                "estimated_range": compact.visual_skin_age.range,
                "explanation": compact.visual_skin_age.explanation,
                "confidence": compact.visual_skin_age.confidence,
            },
            "skin_type": {
                "type": SKIN_TYPE_LABELS.get(compact.skin_type.type, compact.skin_type.type),
                "features": compact.skin_type.features,
                "strengths": compact.skin_type.strengths,
                "attention_points": [zone.issue for zone in compact.zones if zone.level in {"yellow", "red"}][:5],
            },
            "face_type_and_aging_type": {
                "face_type": compact.face_type.shape,
                "aging_type": AGING_LABELS.get(compact.aging_type.type, compact.aging_type.type),
                "explanation": compact.aging_type.description or compact.face_type.description,
            },
            "zones": zones,
            "causes": [zone.issue for zone in compact.zones[:5]],
            "strengths": compact.skin_type.strengths,
            "facefitness_benefits": [zone.recommendation for zone in compact.zones[:4]] or forecast_focus,
            "time_forecast": {
                "first_changes": f"7-14 дней: {forecast_focus[0]}.",
                "visible_changes": f"4-6 недель: {forecast_focus[min(1, len(forecast_focus) - 1)]}.",
                "stable_result": "6-8 недель: более устойчивая мягкость мимики и четкость контура.",
            },
            "summary": compact.summary,
            "cta_recommendation": compact.offer_angle or "Система Bella Vladi помогает раскрывать природную базу по шагам.",
            "journal_protocol": payload.get("journal_protocol") if isinstance(payload.get("journal_protocol"), dict) else None,
        }
    ).model_dump()


def strict_report_to_face_analysis(payload: dict[str, Any]) -> dict:
    def block_text(key: str, fallback: str = "") -> str:
        value = payload.get(key) if isinstance(payload.get(key), dict) else {}
        return _public_text(value.get("text") if isinstance(value, dict) else "") or fallback

    skin_age_text = block_text("skin_visual_age", "Кожа выглядит плотной и ухоженной; свежесть раскрывают взгляд и мягкий овал.")
    raw_skin_type_text = block_text("skin_type")
    skin_type_value = payload.get("skin_type") if isinstance(payload.get("skin_type"), dict) else {}
    skin_type_name = _public_skin_type(skin_type_value.get("type_name") or raw_skin_type_text)
    skin_type_text = raw_skin_type_text if is_skin_type_text_valid(f"{skin_type_name} {raw_skin_type_text}") else build_skin_type_text(skin_type_name)
    strengths_text = block_text("face_strengths", "Форма, скулы и пропорции создают сильную природную базу.")
    aging_text = block_text("aging_type", "Ваш тип старения визуально ближе к усталому / смешанному.")
    aging_type = payload.get("aging_type") if isinstance(payload.get("aging_type"), dict) else {}
    aging_id = normalize_aging_classification(aging_type)["type_id"]
    client = payload.get("client") if isinstance(payload.get("client"), dict) else {}
    skin_visual_age = payload.get("skin_visual_age") if isinstance(payload.get("skin_visual_age"), dict) else {}
    client_age = client.get("age") if isinstance(client.get("age"), int) else skin_visual_age.get("passport_age")
    future_text = build_future_changes_text(aging_id)
    age_changes_text = build_age_changes_text(aging_id, client_age if isinstance(client_age, int) else None)
    benefits_text = block_text("face_fitness_benefits", "Фейсфитнес помогает раскрыть природную базу через мягкую последовательность.")
    growth_text = block_text("growth_zones", "Главный фокус — зона глаз, шея и нижняя треть.")
    final_text = block_text("final_summary", "В лице уже есть сильная природная база и хороший ресурс для мягкой работы.")

    time_forecast = payload.get("time_forecast") if isinstance(payload.get("time_forecast"), dict) else {}
    forecast_items = time_forecast.get("items") if isinstance(time_forecast.get("items"), list) else []
    forecast_items = [_public_text(item) for item in forecast_items if _public_text(item)]
    while len(forecast_items) < 3:
        forecast_items.append(
            [
                "Через 2 недели — взгляд может стать мягче, меньше утреннего напряжения.",
                "Через 3–4 недели — лицо может выглядеть более открытым.",
                "Через 6–8 недель — может появиться устойчивее мягкость мимики и чёткость контура.",
            ][len(forecast_items)]
        )

    classification = normalize_aging_classification(payload.get("aging_classification"), fallback_text=aging_text)
    aging_type = classification["combined_label"] or classification["type_name"]
    aging_block = payload.get("aging_type_block") if isinstance(payload.get("aging_type_block"), dict) else build_aging_type_block(classification)
    face_features = payload.get("face_features") if isinstance(payload.get("face_features"), dict) else {
        "title": "Форма и сильные стороны лица",
        "description": sanitize_face_features_text(strengths_text),
        "items": [
            {
                "feature": "Природная база",
                "observation": sanitize_face_features_text(strengths_text),
                "why_it_is_beautiful": "В лице уже есть мягкость, баланс и опора.",
                "how_face_fitness_reveals_it": "Система помогает раскрыть это через шею, отток, расслабление и тонус.",
            }
        ],
    }

    zone_names = []
    for name in ["Межбровье", "Зона глаз", "Шея", "Овал лица", "Носогубная зона", "Лоб"]:
        if name.lower() in growth_text.lower() or len(zone_names) < 4:
            zone_names.append(name)
        if len(zone_names) >= 6:
            break
    zones = [
        {
            "number": index,
            "name": name,
            "status": "priority" if index <= 2 else "attention",
            "color": "red" if index <= 2 else "yellow",
            "short_comment": f"{name} — зона внимания.",
            "reason": growth_text,
            "recommended_focus": benefits_text,
        }
        for index, name in enumerate(zone_names, start=1)
    ]

    normalized = FaceAnalysis.model_validate(
        {
            "skin_visual_age": {"estimated_range": skin_age_text, "explanation": skin_age_text, "confidence": "medium"},
            "skin_type": {
                "type": _public_skin_type(skin_type_text),
                "features": [skin_type_text],
                "strengths": [strengths_text],
                "attention_points": zone_names[:4],
            },
            "face_type_and_aging_type": {
                "face_type": sanitize_face_features_text(strengths_text),
                "aging_type": aging_type,
                "explanation": aging_text,
            },
            "zones": zones,
            "causes": [future_text],
            "strengths": [strengths_text],
            "facefitness_benefits": [benefits_text],
            "time_forecast": {
                "first_changes": forecast_items[0],
                "visible_changes": forecast_items[1],
                "stable_result": forecast_items[2],
            },
            "summary": final_text,
            "cta_recommendation": final_text,
            "journal_protocol": {
                "skin_age": {"description": skin_age_text, "main_observation": skin_age_text},
                "skin_type": {"type_name": _public_skin_type(skin_type_text), "description": skin_type_text, "features": [skin_type_text]},
                "face_type": {
                    "face_shape": sanitize_face_features_text(strengths_text),
                    "aging_type": aging_type,
                    "main_scenario": aging_text,
                    "base_note": sanitize_face_features_text(strengths_text),
                },
                "why_happens": {"main_explanation": future_text, "conclusion": growth_text},
                "age_changes": {"text": age_changes_text},
                "strengths": {"items": [{"title": "Ваши сильные стороны", "why_it_is_strength": strengths_text, "how_to_enhance": benefits_text}]},
                "face_fitness_benefits": {"personal_sequence": [{"step": 1, "focus": "Система Bella Vladi", "expected_effect": benefits_text}], "conclusion": benefits_text},
                "time_forecast": {"intro": time_forecast.get("intro") or "", "items": forecast_items},
                "growth_zones": {"items": zone_names, "priorities": [{"priority": 1, "zone": zone_names[0], "why": growth_text}]},
                "final_summary": {"main_conclusion": final_text, "quote": "«Именно для этого создан этот курс.»"},
            },
            "aging_classification": classification,
            "face_features": face_features,
            "aging_type_block": aging_block,
        }
    ).model_dump()
    normalized["strict_blocks"] = payload
    return normalized


def normalize_analysis_payload(payload: dict[str, Any], *, client_age: int | None = None) -> dict:
    if isinstance(payload, dict) and payload.get("protocol_version") == BELLA_PROTOCOL_V4:
        validated_v4 = validate_bella_protocol_v4(payload, best_effort=settings.ai_accept_best_effort)
        legacy_payload = protocol_v4_to_legacy_payload(validated_v4)
        normalized = FaceAnalysis.model_validate(legacy_payload).model_dump()
        normalized["strict_blocks"] = validated_v4
        normalized["bella_protocol_v4"] = validated_v4
        normalized["analysis_context"] = {
            "aging_type_id": validated_v4["aging_type"]["type_id"],
            "aging_type_name": validated_v4["aging_type"]["type_name"],
            "aging_display_name": validated_v4["aging_type"].get("display_name") or validated_v4["aging_type"]["type_name"],
            "combo_type_ids": validated_v4["aging_type"].get("combo_type_ids", []),
            "combo_type_names": validated_v4["aging_type"].get("combo_type_names", []),
            "passport_age": validated_v4["skin_visual_age"]["passport_age"],
            "visual_age": validated_v4["skin_visual_age"]["visual_age"],
        }
        return normalized
    if {"skin_visual_age", "skin_type", "face_strengths", "aging_type", "time_forecast", "final_summary"}.issubset(payload.keys()):
        return strict_report_to_face_analysis(payload)
    if "point_a" in payload and "point_c" in payload:
        return bella_protocol_to_face_analysis(payload)
    if "visual_skin_age" in payload and "face_type" in payload and "aging_type" in payload:
        return compact_analysis_to_face_analysis(payload)
    return FaceAnalysis.model_validate(payload).model_dump()


# ─── Валидация и санация финального ответа ────────────────────────────────────

def validate_and_sanitize_protocol(result: dict[str, Any]) -> dict[str, Any]:
    """
    1. Проверяет, что тип старения — один из 4 разрешённых.
       Если нет — корректирует через normalize_aging_classification.
    2. Прогоняет все строковые значения через sanitize_protocol_text.
    Возвращает очищенный словарь.
    """
    import json as _json

    if isinstance(result.get("bella_protocol_v4"), dict):
        validated_v4 = validate_bella_protocol_v4(result["bella_protocol_v4"], best_effort=settings.ai_accept_best_effort)
        result["bella_protocol_v4"] = validated_v4
        result["strict_blocks"] = validated_v4
        result["analysis_context"] = {
            "aging_type_id": validated_v4["aging_type"]["type_id"],
            "aging_type_name": validated_v4["aging_type"]["type_name"],
            "aging_display_name": validated_v4["aging_type"].get("display_name") or validated_v4["aging_type"]["type_name"],
            "combo_type_ids": validated_v4["aging_type"].get("combo_type_ids", []),
            "combo_type_names": validated_v4["aging_type"].get("combo_type_names", []),
            "passport_age": validated_v4["skin_visual_age"]["passport_age"],
            "visual_age": validated_v4["skin_visual_age"]["visual_age"],
        }

    # Санируем весь JSON-текст разом (быстро и без рекурсии)
    raw_str = _json.dumps(result, ensure_ascii=False)
    clean_str = sanitize_protocol_text(raw_str)
    try:
        result = _json.loads(clean_str)
    except Exception:
        pass  # если JSON сломался — возвращаем оригинал

    # Проверяем тип старения
    aging = result.get("aging_classification") if isinstance(result.get("aging_classification"), dict) else {}
    type_id = aging.get("type_id", "")
    if not validate_aging_type_id(type_id):
        fixed = normalize_aging_classification(aging)
        result["aging_classification"] = fixed

    return result
