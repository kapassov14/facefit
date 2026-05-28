from __future__ import annotations

import base64
import json
import mimetypes
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import google.generativeai as genai
import httpx
from PIL import Image, ImageOps

from app.core.config import settings
from app.ai.json_repair import parse_json_safely
from app.ai.prompts import build_analysis_system_prompt, build_analysis_user_prompt
from app.ai.protocol_v4 import ProtocolValidationError
from app.ai.schemas import normalize_analysis_payload, validate_and_sanitize_protocol


SCHEMA_INSTRUCTION = (
    build_analysis_system_prompt("")
    + "\n\nПреобразуй входной текст в полный JSON bella_face_protocol_v4. "
    "Если данных не хватает, сделай осторожную визуальную оценку без старых классификаций и без копирования примеров."
)

FACE_ANALYSIS_JSON_PROMPT = build_analysis_system_prompt("")


def repair_or_structure_with_gemini(raw_text: str) -> dict[str, Any] | None:
    if not (settings.enable_gemini_fallback and settings.gemini_api_key and settings.gemini_model):
        return None
    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(settings.gemini_model)
    response = model.generate_content(
        SCHEMA_INSTRUCTION + "\n\nВходной текст для преобразования:\n" + raw_text
    )
    try:
        return json.loads(response.text)
    except Exception:
        return None


def _validation_errors(exc: Exception) -> list[str]:
    if isinstance(exc, ProtocolValidationError):
        return exc.errors
    if hasattr(exc, "errors"):
        try:
            return [f"{err['loc']}: {err['msg']}" for err in exc.errors()]
        except Exception:
            pass
    return [str(exc)]


def _gemini_generate_json(model: str, prompt: str, photo_path: str) -> str:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    _read_image_part(photo_path),
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=settings.ai_timeout_seconds,
    )
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(f"Gemini face analysis failed: {detail[:800]}")
    return _extract_text(response.json()) or "{}"


def _normalize_gemini_response(raw: str, user_age: int | None) -> tuple[dict[str, Any], dict[str, Any]]:
    parsed = parse_json_safely(raw)
    normalized = normalize_analysis_payload(parsed, client_age=user_age)
    return validate_and_sanitize_protocol(normalized), parsed if isinstance(parsed, dict) else {}


def analyze_face_with_gemini(
    photo_path: str,
    user_name: str | None = None,
    selected_problems: list[str] | None = None,
    knowledge_context: str = "",
    system_prompt: str | None = None,
    user_age: int | None = None,
) -> dict[str, Any]:
    model = (settings.ai_analysis_model or settings.gemini_model or "gemini-2.5-flash-lite").removeprefix("models/")
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is missing")
    prompt = "\n\n".join(
        [
            build_analysis_system_prompt(system_prompt or ""),
            build_analysis_user_prompt(
                user_name,
                selected_problems or [],
                knowledge_context,
                system_prompt or "",
                user_age=user_age,
            ),
        ]
    )

    raw = _gemini_generate_json(model, prompt, photo_path)
    parsed_for_fallback: dict[str, Any] = {}
    try:
        result, parsed_for_fallback = _normalize_gemini_response(raw, user_age)
        result["_validation_meta"] = {
            "validationPassed": True,
            "retryCount": 0,
            "fallbackUsed": False,
            "validationErrors": [],
        }
        return result
    except Exception as exc:
        first_errors = _validation_errors(exc)

    retry_prompt = (
        f"{prompt}\n\n"
        "Предыдущий JSON не прошел validation. Исправь только JSON и верни полный объект bella_face_protocol_v4.\n"
        "Конкретные ошибки:\n- "
        + "\n- ".join(first_errors[:12])
        + "\n\nПредыдущий JSON:\n"
        + raw[:12000]
    )
    retry_raw = _gemini_generate_json(model, retry_prompt, photo_path)
    try:
        result, parsed_for_fallback = _normalize_gemini_response(retry_raw, user_age)
        result["_validation_meta"] = {
            "validationPassed": True,
            "retryCount": 1,
            "fallbackUsed": False,
            "validationErrors": first_errors,
        }
        return result
    except Exception as retry_exc:
        retry_errors = first_errors + _validation_errors(retry_exc)
        raise ProtocolValidationError(retry_errors) from retry_exc


def _protocol_image_model() -> str | None:
    model = settings.gemini_protocol_image_model or settings.gemini_model
    if not model:
        return None
    return model.removeprefix("models/")


def _read_image_part(path: str) -> dict[str, Any]:
    file_path = Path(path)
    mime_type = mimetypes.guess_type(file_path.name)[0] or "image/jpeg"
    return {
        "inlineData": {
            "mimeType": mime_type,
            "data": base64.b64encode(file_path.read_bytes()).decode("ascii"),
        }
    }


def _extract_inline_image(response_json: dict[str, Any]) -> bytes | None:
    for candidate in response_json.get("candidates", []):
        for part in (candidate.get("content") or {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    return None


def _extract_text(response_json: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in response_json.get("candidates", []):
        for part in (candidate.get("content") or {}).get("parts", []):
            if part.get("text"):
                texts.append(part["text"])
    return "\n".join(texts)


def _normalize_protocol_image(image_bytes: bytes, output_path: str) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    image = ImageOps.exif_transpose(image)
    target_size = (1080, 1350)
    source_ratio = image.width / image.height
    target_ratio = target_size[0] / target_size[1]
    if abs(source_ratio - target_ratio) < 0.08:
        result = ImageOps.fit(image, target_size, method=Image.Resampling.LANCZOS)
    else:
        result = Image.new("RGB", target_size, (250, 246, 240))
        contained = ImageOps.contain(image, target_size, method=Image.Resampling.LANCZOS)
        result.paste(contained, ((target_size[0] - contained.width) // 2, (target_size[1] - contained.height) // 2))
    result.save(output_path, quality=96)
    return output_path


def _zone_prompt_lines(analysis_json: dict[str, Any]) -> str:
    lines = []
    for zone in analysis_json.get("zones", [])[:9]:
        status = zone.get("status") or "attention"
        label = "Все хорошо" if status == "good" else "Приоритет" if status == "priority" else "Зона внимания"
        lines.append(f'{zone.get("number")}. {zone.get("name")} — {label}')
    return "\n".join(lines)


def _priority_prompt_lines(analysis_json: dict[str, Any]) -> str:
    zones = analysis_json.get("zones", [])
    priority = [zone for zone in zones if zone.get("status") == "priority" or zone.get("color") == "red"]
    attention = [zone for zone in zones if zone.get("status") == "attention" or zone.get("color") == "yellow"]
    selected = (priority + attention + zones)[:3]
    return "\n".join(
        f'{index}. {zone.get("name")} — {"зона приоритета" if zone.get("status") == "priority" else "зона внимания" if zone.get("status") == "attention" else "все хорошо"}'
        for index, zone in enumerate(selected, start=1)
    )


def build_gemini_protocol_prompt(user_name: str, analysis_json: dict[str, Any]) -> str:
    report_date = datetime.now().strftime("%d.%m.%Y")
    return f"""
Create one finished premium beauty infographic image for Telegram, 1080x1350 vertical 4:5.
Use the attached face photo as the central face map. Preserve the person's identity, face proportions, expression, skin texture and natural look.

Design direction:
- Bella Vladi premium beauty aesthetic
- light milky background, nude beige, dusty rose, muted sage green, soft gold accents
- mobile-first, very readable, lots of whitespace
- luxury editorial skincare protocol, not a medical chart
- no scary or diagnostic language

Layout:
Header:
Bella Vladi
Face Protocol
{user_name or "Гость"} · {report_date}
badge: "визуальный AI-разбор"

Main face map:
- the face photo should occupy 70-80% of image width
- overlay soft translucent highlighted zones, not dots
- use gentle glow/fill and outline for each zone
- each zone has only a small readable circular numbered badge near it, not covering eyes, lips, nose or key facial features
- do not place long text labels or callout label pills around the face photo
- do not write zone names directly on the face map
- place exactly 9 numbered badges, each number used once and only once:
  1 forehead / лоб
  2 glabella / межбровная зона
  3 eyes / область глаз и веки
  4 nasolabial / носогубная зона
  5 cheeks / скулы
  6 jawline / овал лица
  7 chin / подбородок
  8 neck / шея
  9 puffiness / зона отечности
- do not duplicate badge numbers, do not skip badge 4, and do not add any extra numbers
- status colors:
  good = muted sage green
  attention = warm beige / soft gold
  priority = dusty rose / soft red

Zones and statuses:
{_zone_prompt_lines(analysis_json)}

Bottom:
Reserve the lower part of the slide as a clean milky information panel. It must not overlap the face.

Legend:
Все хорошо
Зона внимания
Приоритет

Zone index:
Show a separate readable numbered zone index with number + Russian zone name:
1 Лоб
2 Межбровная зона
3 Область глаз / веки
4 Носогубная зона
5 Скулы
6 Овал лица
7 Подбородок
8 Шея
9 Зона отечности

Priority summary:
Главный фокус
{_priority_prompt_lines(analysis_json)}

Footer:
Протокол не является медицинским диагнозом и не обещает гарантированный результат.
Подробный отчет — по ссылке в боте

Important:
- Russian text must be crisp, large and readable.
- Do not add extra text beyond the requested labels.
- Do not write the phrase "today's date"; use exactly "{report_date}".
- Do not crop the face badly.
- Do not beautify, retouch heavily, or change identity.
- The result should look expensive, premium, clean and client-ready.
"""


def build_gemini_protocol_base_prompt(slide_kind: str) -> str:
    kind_titles = {
        "face_map": "Face Map slide background",
        "summary": "Summary slide background",
        "plan": "Plan and Forecast slide background",
    }
    return f"""
Create ONLY a premium editorial beauty background image, 1080x1350 vertical 4:5.
This background will be used under exact UI/text layers for a Bella Vladi Face Protocol Telegram slide.

Visual direction:
- warm milky ivory base
- extremely subtle dusty rose watercolor wash
- very soft sage green and champagne accents near the outer edges
- fine paper grain, soft editorial beauty texture
- airy, expensive, calm, clean
- premium skincare / beauty report mood
- no dark blocks, no heavy gradients, no medical look
- no frames, no cards, no UI components, no mockup objects

Slide type: {kind_titles.get(slide_kind, slide_kind)}

Important:
- Do not write any text, numbers, logos, labels, pseudo text or watermark.
- Do not include a face or person.
- Leave the center and lower center very calm and bright for overlay content.
- The result must look expensive, clean, mobile-first and client-ready.
"""


def _generate_image_from_parts(parts: list[dict[str, Any]], output_path: str) -> str:
    model = _protocol_image_model()
    if not (settings.gemini_api_key and model):
        raise RuntimeError("Gemini protocol image generation is not configured")

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=settings.ai_timeout_seconds,
    )
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(f"Gemini protocol image generation failed: {detail[:500]}")

    data = response.json()
    image_bytes = _extract_inline_image(data)
    if not image_bytes:
        text = _extract_text(data)
        raise RuntimeError(f"Gemini did not return an image. Text response: {text[:500]}")
    return _normalize_protocol_image(image_bytes, output_path)


def generate_protocol_background_with_gemini(output_path: str, slide_kind: str) -> str:
    return _generate_image_from_parts(
        [{"text": build_gemini_protocol_base_prompt(slide_kind)}],
        output_path,
    )


def generate_protocol_image_with_gemini(
    original_photo_path: str,
    output_path: str,
    user_name: str,
    analysis_json: dict[str, Any],
) -> str:
    model = _protocol_image_model()
    if not (settings.gemini_api_key and model):
        raise RuntimeError("Gemini protocol image generation is not configured")

    return _generate_image_from_parts(
        [
            {"text": build_gemini_protocol_prompt(user_name, analysis_json)},
            _read_image_part(original_photo_path),
        ],
        output_path,
    )
