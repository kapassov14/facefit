from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from openai import BadRequestError, OpenAI
from pydantic import ValidationError

from app.ai.gemini_client import repair_or_structure_with_gemini
from app.ai.json_repair import parse_json_safely
from app.ai.prompts import (
    PERSONAL_INSIGHT_SYSTEM_PROMPT,
    PERSONAL_INSIGHT_USER_PROMPT,
    PROTOCOL_COPY_SYSTEM_PROMPT,
    PROTOCOL_COPY_USER_PROMPT,
    PROTOCOL_SLIDE_COPY_SYSTEM_PROMPT,
    PROTOCOL_SLIDE_COPY_USER_PROMPT,
    REPORT_PROMPT,
    build_analysis_system_prompt,
    build_analysis_user_prompt,
)
from app.ai.protocol_v4 import ProtocolValidationError
from app.ai.schemas import normalize_analysis_payload, validate_and_sanitize_protocol
from app.core.config import settings
from app.reports.face_protocol_final.normalize import build_protocol_copy_from_analysis, normalize_protocol_copy
from app.reports.face_protocol_final.schema import EXAMPLE_PROTOCOL_COPY
from app.reports.protocol_v4.schema import build_protocol_slide_copy_from_analysis, normalize_protocol_slide_copy


def _chat_completion_with_temperature_fallback(client: OpenAI, **kwargs: Any):
    try:
        return client.chat.completions.create(**kwargs)
    except BadRequestError as exc:
        message = str(exc)
        if "temperature" in kwargs and "temperature" in message and "unsupported" in message.lower():
            retry_kwargs = dict(kwargs)
            retry_kwargs.pop("temperature", None)
            return client.chat.completions.create(**retry_kwargs)
        raise


def _image_to_data_url(path: str) -> str:
    file_path = Path(path)
    mime = "image/png" if file_path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(file_path.read_bytes()).decode('ascii')}"


def _compose_stage_system_prompt(base_system_prompt: str | None, stage_prompt: str) -> str:
    base = (base_system_prompt or "").strip()
    stage = stage_prompt.strip()
    if not base:
        return stage
    return (
        f"{base}\n\n"
        "## ИНСТРУКЦИЯ ТЕКУЩЕГО ЭТАПА\n"
        f"{stage}\n\n"
        "Если базовый системный промпт описывает подробную схему анализа, используй ее как методический контекст. "
        "Формат ответа и обязательные поля для текущего запроса определяются инструкцией текущего этапа."
    )


def _validation_errors(exc: Exception) -> list[str]:
    if isinstance(exc, ProtocolValidationError):
        return exc.errors
    if isinstance(exc, ValidationError):
        return [f"{err['loc']}: {err['msg']}" for err in exc.errors()]
    return [str(exc)]


def _normalize_analysis_response(raw: str, *, user_age: int | None) -> tuple[dict[str, Any], dict[str, Any]]:
    parsed = parse_json_safely(raw)
    normalized = normalize_analysis_payload(parsed, client_age=user_age)
    return validate_and_sanitize_protocol(normalized), parsed if isinstance(parsed, dict) else {}


def mock_analysis(selected_problems: list[str] | None = None) -> dict[str, Any]:
    selected = selected_problems or []
    priority_keywords = " ".join(selected).lower()

    def status_for(name: str) -> tuple[str, str]:
        key = name.lower()
        if any(word in priority_keywords for word in ["носогуб", "овал", "подбород", "брыли"]) and any(
            word in key for word in ["носогуб", "овал", "подбород"]
        ):
            return "priority", "red"
        if any(word in priority_keywords for word in ["веко", "глаз", "отеч", "устал"]) and any(
            word in key for word in ["глаз", "отеч"]
        ):
            return "attention", "yellow"
        if any(word in priority_keywords for word in ["межбров"]) and "межбров" in key:
            return "attention", "yellow"
        if name in {"Скулы", "Лоб"}:
            return "good", "green"
        return "attention", "yellow"

    zone_names = [
        "Лоб",
        "Межбровная зона",
        "Область глаз / веки",
        "Носогубная зона",
        "Скулы",
        "Овал лица",
        "Подбородок",
        "Шея",
        "Зона отечности",
    ]
    zones = []
    for index, name in enumerate(zone_names, start=1):
        status, color = status_for(name)
        zones.append(
            {
                "number": index,
                "name": name,
                "status": status,
                "color": color,
                "short_comment": "зона дает лицу опору" if status == "good" else "зона влияет на первое впечатление",
                "reason": "Связана с шеей, лимфотоком, мимикой и тонусом нижней трети.",
                "recommended_focus": "Сначала шея и отток, затем расслабление и мягкий тонус.",
            }
        )

    return {
        "skin_visual_age": {
            "estimated_range": "примерно в диапазоне 32-34",
            "explanation": "Кожа выглядит плотной и ухоженной; визуальный возраст больше задают взгляд и межбровье.",
            "confidence": "medium",
        },
        "skin_type": {
            "type": "комбинированная, склонная к обезвоженности",
            "features": ["Плюс: кожа хорошо держит каркас", "Центральной зоне нужно больше увлажнения", "Зона глаз быстрее показывает недосып"],
            "strengths": ["Скулы создают природную опору лица", "Кожа и овал хорошо держат контур"],
            "attention_points": ["Шея и лимфоток", "Нижняя треть", "Микроциркуляция зоны глаз"],
        },
        "face_type_and_aging_type": {
            "face_type": "мягкая природная форма лица с хорошей скуловой опорой",
            "aging_type": "Усталый / смешанный",
            "explanation": "Форма и скулы дают сильную базу; свежесть быстрее всего меняют взгляд, шея и нижняя треть.",
        },
        "aging_classification": {
            "type_id": "tired_mixed",
            "type_name": "Усталый / смешанный",
            "primary_type": "",
            "secondary_type": "",
            "combined_label": "",
            "confidence": "medium",
            "evidence_from_photo": ["зона глаз", "шея и нижняя треть", "носогубная зона"],
            "kb_source_used": True,
        },
        "face_features": {
            "title": "Форма и сильные стороны лица",
            "description": "Мягкая природная форма лица, скуловая опора и выразительная зона глаз.",
            "items": [
                {
                    "feature": "Скуловая опора",
                    "observation": "Скулы дают лицу естественную опору.",
                    "why_it_is_beautiful": "Это сильная природная база без изменения черт.",
                    "how_face_fitness_reveals_it": "Отток, шея и мягкий тонус помогают скулам читаться выразительнее.",
                }
            ],
        },
        "aging_type_block": {
            "title": "Тип старения",
            "text": "Ведущий сценарий: усталый / смешанный.",
            "characteristic": "Комбинация признаков усталости: зона глаз, носогубная зона, снижение свежести, лёгкая пастозность.",
            "how_changes_over_time": "Изменения идут через снижение тонуса, микроциркуляцию, зону глаз и нижнюю треть.",
            "what_if_nothing_changes": "Без системы свежесть лица может снижаться быстрее, особенно к вечеру.",
            "main_focus": "Микроциркуляция, шея, мягкий тонус, носогубная зона и свежесть взгляда.",
        },
        "zones": zones,
        "causes": ["Шея влияет на отток и свежесть взгляда", "Межбровье может делать лицо строже", "Средняя треть меняет мягкость носогубной зоны"],
        "strengths": ["Мягкая природная форма выглядит выразительно", "Скулы дают лицу естественную опору", "Плотная кожа держит контур"],
        "facefitness_benefits": [
            "раскрыть взгляд через расслабление лба",
            "подчеркнуть скулы и мягкий овал",
            "снять лишнюю тяжесть через шею и лимфу",
        ],
        "time_forecast": {
            "first_changes": "2 недели: взгляд может стать мягче и свежее.",
            "visible_changes": "3-4 недели: межбровье спокойнее, лицо более открытое.",
            "stable_result": "6-8 недель: мягкость мимики и контур могут стать устойчивее.",
        },
        "summary": "У лица сильная природная база; главный маршрут — снять напряжение и раскрыть свежесть через шею, лимфу и тонус.",
        "cta_recommendation": "Система Bella Vladi логична здесь, потому что ведет лицо по последовательности, а не по случайным упражнениям.",
        "journal_protocol": {
            "skin_age": {
                "age_value": 32,
                "score_value": 82,
                "main_observation": "Кожа выглядит плотной и ухоженной; визуальный возраст больше задают взгляд и межбровье.",
                "what_affects_age_perception": ["межбровье делает выражение строже", "зона глаз быстрее показывает недосып", "шея влияет на свежесть взгляда"],
                "main_focus": "снять напряжение верхней трети и вернуть лицу мягкую собранность",
                "description": "Кожа выглядит ресурсной; добавляют годы не качество кожи, а напряжение взгляда и межбровья.",
            },
            "skin_type": {
                "type_name": "комбинированная, с ровной плотной базой",
                "description": "У вас комбинированная кожа с ровной плотной базой. Плюс этого типа — кожа хорошо держит каркас; зона глаз и центр лица просят чуть больше увлажнения и мягкого ухода. При правильной системе кожа может выглядеть свежее, ровнее и ближе к эффекту ухоженного сияния.",
                "features": ["плотность кожи поддерживает овал", "зона глаз быстрее показывает недосып"],
                "strength": "ровная плотная база помогает лицу выглядеть собранно",
                "care_focus": "увлажнение, мягкий отток и регулярность без перегруза",
            },
            "face_type": {
                "face_shape": "мягкая природная форма лица с хорошей скуловой опорой",
                "aging_type": "Усталый / смешанный",
                "main_scenario": "У вас мягкая природная форма лица и выразительная зона глаз. Такая база хорошо сохраняет женственность черт, но свежесть быстрее меняют взгляд, носогубная зона и нижняя треть.",
                "what_appears_first": ["межбровье может делать взгляд строже", "зона глаз первой показывает недосып", "овал лучше отвечает после шеи"],
                "recommended_start": "начинать лучше с шеи, лимфы и расслабления верхней трети",
                "base_note": "Скулы и форма лица уже дают естественный лифтинг — его важно раскрыть.",
            },
            "zone_map": {
                "zones": [
                    {"id": "eye_area", "number": 1, "title": "Зона глаз", "status": "yellow", "what_is_visible": "Глаза выразительные, но быстрее показывают недосып и напряжение.", "why_it_matters": "Взгляд первым задает ощущение свежести.", "what_to_do": "Мягкий лимфодренаж, шея и расслабление верхней трети."},
                    {"id": "cheeks", "number": 2, "title": "Скулы", "status": "green", "what_is_visible": "Скулы дают лицу природную опору.", "why_it_matters": "Это база естественного лифтинга без изменения черт.", "what_to_do": "Подчеркивать через отток и мягкую активацию средней трети."},
                    {"id": "face_oval", "number": 3, "title": "Овал лица", "status": "yellow", "what_is_visible": "Контур сохранен, но нижняя треть зависит от шеи.", "why_it_matters": "Овал отвечает за ощущение собранности.", "what_to_do": "Сначала отток и шея, затем упражнения на тонус."},
                ]
            },
            "why_happens": {
                "title": "Какие изменения будут со временем",
                "main_explanation": "Без регулярной поддержки усталого / смешанного сценария к вечеру сильнее считываются зона глаз, носогубка и уголки рта. Хорошая новость: лимфоток, шея и мягкий тонус помогают вернуть лицу свежесть без давления.",
                "mechanics": [
                    {"factor": "Лимфоток", "how_it_affects_face": "когда отток слабее, зона глаз и щеки выглядят тяжелее", "what_helps": "мягкий утренний лимфодренаж"},
                    {"factor": "Шея", "how_it_affects_face": "зажимы могут мешать овалу выглядеть собраннее", "what_helps": "работа с шеей и ключицами"},
                    {"factor": "Нижняя треть", "how_it_affects_face": "напряжение делает лицо визуально строже", "what_helps": "расслабление, затем мягкий тонус"},
                ],
                "conclusion": "Именно поэтому система Bella Vladi логичнее случайных упражнений: важен порядок шагов.",
            },
            "strengths": {
                "title": "Ваши сильные стороны",
                "items": [
                    {"title": "Природная форма", "why_it_is_strength": "мягкая выразительность лица", "how_to_enhance": "раскрывать через шею и тонус"},
                    {"title": "Скулы", "why_it_is_strength": "естественная лифтинг-опора", "how_to_enhance": "подчеркивать через среднюю треть"},
                    {"title": "Плотная кожа", "why_it_is_strength": "хорошо держит контур", "how_to_enhance": "увлажнение и лимфодренаж"},
                ],
            },
            "face_fitness_benefits": {
                "title": "Что даст фейс-фитнес",
                "personal_sequence": [
                    {"step": 1, "focus": "Шея и лимфоток", "why_first": "они готовят лицо к свежести", "expected_effect": "взгляд может стать мягче"},
                    {"step": 2, "focus": "Лоб и межбровье", "why_first": "зажимы могут делать выражение строже", "expected_effect": "лицо может выглядеть спокойнее"},
                    {"step": 3, "focus": "Скулы и овал", "why_first": "после оттока природная база читается ярче", "expected_effect": "контур может стать собраннее"},
                ],
                "conclusion": "Фейс-фитнес здесь не меняет ваши черты, а раскрывает природную базу: взгляд становится мягче, скулы читаются выразительнее, носогубная зона спокойнее, а овал собраннее.",
            },
            "time_forecast": {
                "title": "Прогноз по времени",
                "intro": "На основе опыта Bella Vladi и 20 000+ женщин, прошедших программы:",
                "items": [
                    {"period": "Через 2 недели", "description": "визуально меньше отечности, взгляд свежее"},
                    {"period": "Через 3–4 недели", "description": "мягче носогубная зона, лицо более открытое"},
                    {"period": "Через 6–8 недель", "description": "устойчивее тонус, овал выглядит собраннее"},
                ],
            },
            "growth_zones": {
                "title": "Зоны роста",
                "items": ["Межбровье", "Зона глаз", "Шея", "Скулы", "Овал лица"],
                "priorities": [
                    {"priority": 1, "zone": "Шея и зона глаз", "why": "они первыми меняют ощущение свежести"},
                    {"priority": 2, "zone": "Межбровье", "why": "снятие зажима делает взгляд мягче"},
                    {"priority": 3, "zone": "Скулы и овал", "why": "это ваша природная лифтинг-база"},
                ],
            },
            "first_step": {
                "title": "Ваш первый шаг",
                "action": "Начните с мягкого лимфодренажа утром и расслабления шеи.",
                "duration": "3–5 минут",
                "why_this": "Это самый быстрый способ снять ощущение тяжести и подготовить лицо к тонусу.",
                "expected_feeling": "Лицо может ощущаться легче, а взгляд — свежее.",
            },
            "what_to_avoid": {
                "title": "Чего не делать",
                "items": [
                    {"mistake": "Не давить агрессивно под глазами", "why_not": "зона тонкая и может реагировать отечностью", "better_approach": "мягкий отток через шею и верхнюю треть"},
                    {"mistake": "Не начинать с активной прокачки овала", "why_not": "при отечности тонус считывается слабее", "better_approach": "сначала лимфа и шея, затем упражнения"},
                    {"mistake": "Не делать хаотичные упражнения", "why_not": "без последовательности легко перегрузить зоны", "better_approach": "идти по персональному маршруту"},
                ],
            },
            "final_summary": {
                "label": "Итог",
                "main_conclusion": "В лице уже есть выразительная природная база и хороший ресурс для мягкой работы.",
                "main_result_lever": "Главное сейчас — снять напряжение, которое скрывает вашу настоящую красоту.",
                "start_with": "Начинать лучше с шеи, оттока и расслабления.",
                "then_add": "Затем подключать зону глаз, носогубную область и овал.",
                "expected_direction": "При регулярной практике лицо может выглядеть мягче, свежее и собраннее.",
                "quote": "«Именно для этого создан этот курс.»",
            },
        },
    }


def analyze_face(
    photo_path: str,
    user_name: str | None,
    selected_problems: list[str],
    knowledge_context: str,
    system_prompt: str,
    user_age: int | None = None,
) -> dict[str, Any]:
    if settings.ai_force_mock or not settings.openai_api_key:
        raise RuntimeError("AI text generation requires OpenAI API key and AI_FORCE_MOCK=false")

    client = OpenAI(api_key=settings.openai_api_key, timeout=settings.ai_timeout_seconds)
    model = settings.openai_analysis_model or settings.openai_report_model or "gpt-5.5"
    system_content = build_analysis_system_prompt(system_prompt)
    user_text = build_analysis_user_prompt(user_name, selected_problems, knowledge_context, system_prompt, user_age=user_age)
    response = _chat_completion_with_temperature_fallback(
        client,
        model=model,
        temperature=0.35,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": _image_to_data_url(photo_path)}},
                ],
            },
        ],
    )
    raw = response.choices[0].message.content or "{}"
    parsed_for_fallback: dict[str, Any] = {}
    try:
        result, parsed_for_fallback = _normalize_analysis_response(raw, user_age=user_age)
        result["_validation_meta"] = {
            "validationPassed": True,
            "retryCount": 0,
            "fallbackUsed": False,
            "validationErrors": [],
        }
        return result
    except (ProtocolValidationError, ValidationError) as exc:
        first_errors = _validation_errors(exc)
    except Exception as exc:
        first_errors = _validation_errors(exc)

    retry_prompt = (
        f"{user_text}\n\n"
        "Предыдущий JSON не прошел validation. Исправь только JSON и верни полный объект bella_face_protocol_v4.\n"
        "Конкретные ошибки:\n- "
        + "\n- ".join(first_errors[:12])
        + "\n\nПредыдущий JSON:\n"
        + raw[:12000]
    )
    retry_response = _chat_completion_with_temperature_fallback(
        client,
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": retry_prompt},
                    {"type": "image_url", "image_url": {"url": _image_to_data_url(photo_path)}},
                ],
            },
        ],
    )
    retry_raw = retry_response.choices[0].message.content or "{}"
    try:
        result, parsed_for_fallback = _normalize_analysis_response(retry_raw, user_age=user_age)
        result["_validation_meta"] = {
            "validationPassed": True,
            "retryCount": 1,
            "fallbackUsed": False,
            "validationErrors": first_errors,
        }
        return result
    except Exception as retry_exc:
        retry_errors = first_errors + _validation_errors(retry_exc)

    try:
        repaired = repair_or_structure_with_gemini(raw)
        if repaired:
            result = normalize_analysis_payload(repaired, client_age=user_age)
            result = validate_and_sanitize_protocol(result)
            result["_validation_meta"] = {
                "validationPassed": True,
                "retryCount": 1,
                "fallbackUsed": False,
                "validationErrors": first_errors,
            }
            return result
    except Exception as exc:
        raise ProtocolValidationError(first_errors + _validation_errors(exc)) from exc
    raise ProtocolValidationError(first_errors)


def _aging_key(value: Any) -> str:
    """Возвращает внутренний ключ для логики normalize.py. Только 4 варианта."""
    text = str(value or "").lower()
    if "муск" in text:
        return "muscular"
    if "деформа" in text or "отеч" in text or "отёч" in text or "лимф" in text:
        return "deformation"
    if "мелк" in text or "морщ" in text or "сух" in text or "сетк" in text:
        return "wrinkled"
    # tired_mixed — универсальный fallback (покрывает tired, combined, ptosis, mixed)
    return "tired_mixed"


def _zone_key(value: Any) -> str:
    text = str(value or "").lower()
    if "межб" in text or "лоб" in text:
        return "brow_forehead"
    if "глаз" in text or "век" in text:
        return "eye_area"
    if "носогуб" in text:
        return "nasolabial"
    if "скул" in text or "щек" in text or "щёк" in text:
        return "midface"
    if "овал" in text or "челюст" in text:
        return "oval"
    if "подбор" in text or "около" in text or "рот" in text:
        return "mouth_chin"
    if "ше" in text or "осанк" in text:
        return "neck"
    if "отеч" in text or "отёч" in text:
        return "puffiness"
    return "general"


ZONE_INSIGHT_MAP = {
    "brow_forehead": {
        "visible": "лоб и межбровье могут собирать мимическое напряжение",
        "mechanism": "когда верхняя треть берет лишнюю работу, выразительный взгляд выглядит строже",
        "meaning": "эта зона меняет выражение лица даже при хорошей коже",
        "action": "начинать с расслабления лба и межбровья",
    },
    "eye_area": {
        "visible": "глаза выразительные, но быстрее показывают недосып",
        "mechanism": "на свежесть взгляда влияют шея, отток и напряжение верхней трети",
        "meaning": "взгляд — ваша сильная точка и первый маркер свежести",
        "action": "работать через шею, мягкий отток и расслабление",
    },
    "nasolabial": {
        "visible": "носогубная зона может читаться глубже",
        "mechanism": "часто это связано со средней третью, а не только со складкой",
        "meaning": "она добавляет лицу более усталое выражение вокруг рта",
        "action": "смягчать через щеки, жевательную зону и лимфоток",
    },
    "midface": {
        "visible": "скулы и средняя треть дают лицу природную опору",
        "mechanism": "когда средняя треть тяжелеет, скулы читаются слабее",
        "meaning": "эта зона отвечает за мягкий естественный лифтинг",
        "action": "сначала отток, затем мягкая активация скул",
    },
    "oval": {
        "visible": "овалу нужна более собранная нижняя треть",
        "mechanism": "контур зависит от шеи, платизмы и оттока",
        "meaning": "нижняя треть сильнее всего дает ощущение лифтинга",
        "action": "начинать с шеи, затем подключать тонус овала",
    },
    "mouth_chin": {
        "visible": "околоротовая зона может удерживать напряжение",
        "mechanism": "зажимы вокруг рта утяжеляют нижнюю треть",
        "meaning": "выражение лица может казаться строже, даже если черты мягкие",
        "action": "добавить расслабление и мягкую работу с подбородком",
    },
    "neck": {
        "visible": "шея влияет на посадку головы и овал",
        "mechanism": "напряжение шеи может ухудшать отток от лица",
        "meaning": "без этой базы лицо хуже отвечает на упражнения",
        "action": "начинать с шеи, ключиц и осанки",
    },
    "puffiness": {
        "visible": "тяжесть сильнее считывается в глазах и средней трети",
        "mechanism": "задержка жидкости часто связана с шеей и лимфотоком",
        "meaning": "лицо может выглядеть менее свежим даже при хорошей коже",
        "action": "первый шаг — мягкий лимфодренаж и шея",
    },
    "general": {
        "visible": "у лица есть сильная база, которой нужен понятный маршрут",
        "mechanism": "разные зоны реагируют на лимфу, мимику и тонус по-разному",
        "meaning": "хаотичные упражнения могут не попадать в главный маршрут",
        "action": "идти по порядку: шея, лимфа, расслабление, тонус",
    },
}


def build_personal_insights_from_analysis(analysis_json: dict[str, Any], selected_problems: list[str] | None = None) -> dict[str, Any]:
    analysis = analysis_json if isinstance(analysis_json, dict) else {}
    selected = selected_problems or []
    aging = analysis.get("face_type_and_aging_type") if isinstance(analysis.get("face_type_and_aging_type"), dict) else {}
    zones = [zone for zone in analysis.get("zones", []) if isinstance(zone, dict)] if isinstance(analysis.get("zones"), list) else []
    priority = [zone for zone in zones if zone.get("status") in {"priority", "attention"} or zone.get("color") in {"red", "yellow"}]
    strengths = analysis.get("strengths") if isinstance(analysis.get("strengths"), list) else []

    def zone_name(zone: dict[str, Any], fallback: str) -> str:
        return str(zone.get("name") or zone.get("label") or fallback)

    why_items = []
    for zone in (priority or zones)[:4]:
        name = zone_name(zone, "Зона")
        insight = ZONE_INSIGHT_MAP[_zone_key(name)]
        short_comment = str(zone.get("short_comment") or insight["visible"])
        if any(text in short_comment.lower() for text in ("зона внимания", "потенциал", "требует внимания")):
            short_comment = insight["visible"]
        reason = str(zone.get("reason") or insight["mechanism"])
        if any(text in reason.lower() for text in ("могут влиять", "регуляр", "общ")):
            reason = insight["mechanism"]
        why_items.append(
            {
                "zone": name,
                "visible_sign": short_comment,
                "mechanism": reason,
                "personal_meaning": insight["meaning"],
                "short_protocol_bullet": f"{name}: {insight['mechanism']}. Старт — {insight['action']}.",
            }
        )

    while len(why_items) < 3:
        why_items.append(
            {
                "zone": "Общее впечатление",
                "visible_sign": "нет одной главной складки, важна связка зон",
                "mechanism": "лицо отвечает лучше, когда шея, лимфа и тонус идут по порядку",
                "personal_meaning": "это объясняет, почему случайные упражнения дают слабый эффект.",
                "short_protocol_bullet": "Система важна: шея и лимфа готовят лицо к тонусу.",
            }
        )

    strength_items = []
    for item in strengths[:3]:
        text = str(item)
        key = _zone_key(text)
        guidance = ZONE_INSIGHT_MAP.get(key, ZONE_INSIGHT_MAP["general"])
        strength_items.append(
            {
                "trait": text,
                "why_it_matters": guidance["meaning"],
                "short_protocol_bullet": f"{text}: это ресурс, который лучше раскрывать через {guidance['action']}.",
            }
        )
    while len(strength_items) < 3:
        fallback = ["Мягкая природная форма выглядит выразительно", "Скулы дают естественную опору", "Плотная кожа держит контур"][len(strength_items)]
        strength_items.append(
            {
                "trait": fallback,
                "why_it_matters": "это природная база, которую не нужно менять — ее нужно раскрыть через маршрут.",
                "short_protocol_bullet": fallback,
            }
        )

    aging_type = str(aging.get("aging_type") or "Усталый / смешанный")
    if "комбини" in aging_type.lower() or "mixed" in aging_type.lower() or "птоз" in aging_type.lower():
        aging_type = "Усталый / смешанный"
    main_zone = zone_name(priority[0], "зоны глаз и овала") if priority else "зоны глаз и овала"
    aging_kind = _aging_key(aging_type)
    if aging_kind == "deformation":
        strategy = [
            "Начать с осанки, шеи и лимфодренажа, чтобы поддержать отток.",
            "Затем работать с нижней третью, где ткани быстрее тяжелеют.",
            "После этого подключать овал и зоны, где смещается объём.",
        ]
        what_is_happening = "Лицо меняется через лимфостаз, шею и смещение тканей вниз."
        how_change = "На дистанции утренняя припухлость может становиться устойчивее, а овал — мягче."
    elif aging_kind == "muscular":
        strategy = [
            "Сначала расслабить лоб, межбровье и жевательную зону.",
            "Потом балансировать зоны, которые без нагрузки слабеют.",
            "Работать мягко, чтобы не закреплять гипертонус.",
        ]
        what_is_happening = "Сильные мышцы держат каркас, но хронический гипертонус стягивает кожу в заломы."
        how_change = "На дистанции мимические линии могут закрепляться в покое и давать маску напряжения."
    elif aging_kind == "wrinkled":
        strategy = [
            "Начать с мягкой стимуляции кровотока без перегруза кожи.",
            "Поддерживать питание тканей и естественную мягкую опору.",
            "Тонус добавлять дозированно, чтобы не усиливать сетку.",
        ]
        what_is_happening = "Кожа быстрее теряет влагу, липиды и объём, поэтому силовая нагрузка не первый шаг."
        how_change = "На дистанции лицо может сохранять контур, но выглядеть суше из-за потери объёма."
    else:
        # tired_mixed — universalный fallback
        strategy = [
            "Начать с микроциркуляции и зоны глаз.",
            "Затем вернуть тонус средней трети и уголкам.",
            "После этого поддерживать носослезную и носогубную зоны.",
        ]
        what_is_happening = "Ведущий механизм — снижение тонуса мышц, ухудшение микроциркуляции и лёгкая пастозность."
        how_change = "На дистанции лицо может сильнее уставать к вечеру и терять свежесть взгляда."
    return {
        "main_hook": f"У лица есть сильная природная база; курс поможет раскрыть {main_zone}.",
        "main_visual_conflict": f"{main_zone} сейчас сильнее всего забирает свежесть, хотя база лица выглядит ресурсной.",
        "main_leverage_point": f"Рычаг результата — система: шея, лимфа, расслабление и тонус, а не случайные упражнения.",
        "morphotype_story": {
            "type": aging_type,
            "why_this_type": str(aging.get("explanation") or "сценарий выбран по ведущим зонам и механике лица."),
            "what_is_happening": what_is_happening,
            "how_it_may_change": how_change,
            "strategy": "Стратегию подбирать по ведущему типу: сначала база, затем зоны, которые раскрывают красоту сильнее всего.",
        },
        "why_this_happens": why_items[:4],
        "strengths_explained": strength_items[:3],
        "facefitness_strategy": strategy,
        "avoid": ["Не перегружать зоны гипертонуса", "Не ждать эффекта только от ухода без работы с лимфой и шеей"],
        "final_personal_summary": str(
            analysis.get("summary")
            or f"В лице уже есть сильная природная база. Главный шаг — раскрыть {main_zone} через систему Bella Vladi."
        ),
    }


def generate_personal_insights(
    analysis_json: dict[str, Any],
    selected_problems: list[str],
    knowledge_context: str = "",
    system_prompt: str | None = None,
) -> dict[str, Any]:
    model = settings.openai_protocol_copy_model or settings.openai_report_model or settings.openai_analysis_model
    fallback = build_personal_insights_from_analysis(analysis_json, selected_problems)
    if settings.ai_mock_mode or not (settings.openai_api_key and model):
        return fallback

    client = OpenAI(api_key=settings.openai_api_key, timeout=settings.ai_timeout_seconds)
    response = _chat_completion_with_temperature_fallback(
        client,
        model=model,
        temperature=0.42,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _compose_stage_system_prompt(system_prompt, PERSONAL_INSIGHT_SYSTEM_PROMPT)},
            {
                "role": "user",
                "content": (
                    f"{PERSONAL_INSIGHT_USER_PROMPT}\n\n"
                    + json.dumps(
                        {
                            "analysis_json": analysis_json,
                            "selected_problems": selected_problems,
                            "knowledge_context": knowledge_context[:12000],
                        },
                        ensure_ascii=False,
                    )
                ),
            },
        ],
    )
    try:
        parsed = parse_json_safely(response.choices[0].message.content or "{}")
        return parsed if isinstance(parsed, dict) else fallback
    except Exception:
        return fallback


def generate_report_copy(
    analysis_json: dict[str, Any],
    selected_problems: list[str],
    knowledge_context: str,
    system_prompt: str | None = None,
    report_prompt: str | None = None,
    personal_insight_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if settings.ai_mock_mode or not (settings.openai_api_key and settings.openai_report_model):
        return {
            "editor_note": "Mock mode: отчет собран локально на основе структурированного анализа.",
            "selected_problems": selected_problems,
        }
    client = OpenAI(api_key=settings.openai_api_key, timeout=settings.ai_timeout_seconds)
    stage_report_prompt = (report_prompt or REPORT_PROMPT).strip()
    response = _chat_completion_with_temperature_fallback(
        client,
        model=settings.openai_report_model,
        temperature=0.45,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": _compose_stage_system_prompt(
                    system_prompt,
                    f"{stage_report_prompt}\nОтвет строго JSON. Не добавляй markdown и пояснения вокруг JSON.",
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "analysis_json": analysis_json,
                        "personal_insight_json": personal_insight_json or {},
                        "selected_problems": selected_problems,
                        "knowledge_context": knowledge_context[:12000],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    return parse_json_safely(response.choices[0].message.content or "{}")


def generate_protocol_slide_copy(analysis_json: dict[str, Any], selected_problems: list[str]) -> dict[str, Any]:
    model = settings.openai_protocol_copy_model or settings.openai_report_model or settings.openai_analysis_model
    fallback = build_protocol_slide_copy_from_analysis(analysis_json, selected_problems)
    if settings.ai_mock_mode or not (settings.openai_api_key and model):
        return fallback

    client = OpenAI(api_key=settings.openai_api_key, timeout=settings.ai_timeout_seconds)
    response = _chat_completion_with_temperature_fallback(
        client,
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": PROTOCOL_SLIDE_COPY_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"{PROTOCOL_SLIDE_COPY_USER_PROMPT}\n\n"
                    + json.dumps(
                        {
                            "schema": {
                                "face_map": {
                                    "title": "AI Face Scan",
                                    "subtitle": "визуальный AI-разбор",
                                    "main_focus": ["Глаза", "Носогубка", "Овал"],
                                    "zones": [
                                        {"number": 1, "label": "Лоб", "status": "good", "shape": "forehead"},
                                        {"number": 2, "label": "Межбровка", "status": "attention", "shape": "glabella"},
                                        {"number": 3, "label": "Глаза", "status": "priority", "shape": "eyes"},
                                        {"number": 4, "label": "Носогубка", "status": "attention", "shape": "nasolabial"},
                                        {"number": 5, "label": "Скулы", "status": "good", "shape": "cheeks"},
                                        {"number": 6, "label": "Овал", "status": "priority", "shape": "jawline"},
                                        {"number": 7, "label": "Подбородок", "status": "attention", "shape": "chin"},
                                        {"number": 8, "label": "Шея", "status": "attention", "shape": "neck"},
                                    ],
                                },
                                "summary": {
                                    "skin_age": "до 95 символов",
                                    "skin_type": "до 95 символов",
                                    "aging_type": "до 95 символов",
                                    "strengths": "до 95 символов",
                                },
                                "plan": {
                                    "causes": ["до 55 символов"],
                                    "benefits": ["до 24 символов"],
                                    "forecast": ["до 38 символов"],
                                },
                            },
                            "limits": {
                                "zone_label": 14,
                                "main_focus_item": 18,
                                "summary_card_text": 78,
                                "main_conclusion": 92,
                                "causes_bullet": 55,
                                "benefits_chip": 24,
                                "forecast_item": 38,
                            },
                            "analysis_json": analysis_json,
                            "selected_problems": selected_problems,
                        },
                        ensure_ascii=False,
                    )
                ),
            },
        ],
    )
    parsed = parse_json_safely(response.choices[0].message.content or "{}")
    return normalize_protocol_slide_copy(parsed)


def generate_protocol_copy(
    analysis_json: dict[str, Any],
    selected_problems: list[str],
    knowledge_context: str = "",
    system_prompt: str | None = None,
    personal_insight_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    model = settings.openai_protocol_copy_model or settings.openai_report_model or settings.openai_analysis_model
    fallback = build_protocol_copy_from_analysis(analysis_json, selected_problems, personal_insight_json)
    if settings.ai_mock_mode or not (settings.openai_api_key and model):
        return fallback

    client = OpenAI(api_key=settings.openai_api_key, timeout=settings.ai_timeout_seconds)
    response = _chat_completion_with_temperature_fallback(
        client,
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _compose_stage_system_prompt(system_prompt, PROTOCOL_COPY_SYSTEM_PROMPT)},
            {
                "role": "user",
                "content": (
                    f"{PROTOCOL_COPY_USER_PROMPT}\n\n"
                    + json.dumps(
                        {
                            "schema": EXAMPLE_PROTOCOL_COPY,
                            "limits": {
                                "skin_age.comment": 110,
                                "skin_type.title": 42,
                                "skin_type.bullet": 75,
                                "face_aging.face_strengths": 62,
                                "face_aging.aging_type": 78,
                                "face_aging.forecast": 3,
                                "face_aging.forecast_item": 82,
                                "face_aging.strong_base": 110,
                                "aging.bullet": 95,
                                "why_intro": 180,
                                "causes": 4,
                                "cause.bullet": 95,
                                "why_outro": 170,
                                "strengths": 3,
                                "strength.bullet": 75,
                                "benefits": 3,
                                "benefit.bullet": 75,
                                "benefits_outro": 130,
                                "forecast": 3,
                                "forecast.bullet": 75,
                                "growth_zones": 5,
                                "growth_zone.label": 22,
                                "final_summary": 170,
                                "zone.label": 22,
                            },
                            "analysis_json": analysis_json,
                            "personal_insight_json": personal_insight_json or {},
                            "selected_problems": selected_problems,
                            "knowledge_context": knowledge_context[:12000],
                        },
                        ensure_ascii=False,
                    )
                ),
            },
        ],
    )
    parsed = parse_json_safely(response.choices[0].message.content or "{}")
    return normalize_protocol_copy(parsed)
