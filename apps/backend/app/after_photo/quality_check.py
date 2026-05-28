from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageStat

from app.ai.json_repair import parse_json_safely
from app.after_photo.schemas import AfterPhotoQualityResult
from app.core.config import settings

logger = logging.getLogger(__name__)


QUALITY_SYSTEM_PROMPT = """You evaluate AI-generated after-photo variants for a beauty face-fitness product.
Return strict JSON only. Do not praise the image. Be conservative.
The best result must preserve the same person's identity, age category, ethnicity, facial proportions, camera angle, expression and source-photo context.
Do not prefer subtle edits. A strong visible lifting effect is acceptable if identity is preserved.
Reject if the candidate only changes light, contrast, skin smoothness, sharpness, or general photo quality.
The candidate must show zone-specific structural improvement: fresher under-eye area/open gaze, lighter midface puffiness, clearer lower facial oval/jawline, and less lower-face heaviness.
Reject only if the result is a different person, has severe deformation, broken anatomy, heavy makeup, background changes, unusable artifacts, or no visible structural face-fitness transformation."""

QUALITY_USER_PROMPT = """Compare the original image with the candidate after-photo.
Score only this candidate using this schema:
{
  "same_identity": true,
  "identity_score": 0.0,
  "realism_score": 0.0,
  "visible_improvement": true,
  "structural_change_score": 0.0,
  "region_scores": {
    "under_eye": 0.0,
    "midface": 0.0,
    "lower_face": 0.0,
    "jawline": 0.0
  },
  "skin_texture_preserved": true,
  "too_much_retouch": false,
  "plastic_surgery_effect": false,
  "recommendation": "approve|retry|manual_review|reject",
  "reason": "short reason"
}
Use realism_score only as technical image coherence, not as a reason to prefer weak edits.
Approve only if identity_score >= 0.82, visible_improvement is true, structural_change_score >= 0.55, too_much_retouch is false, and there are no severe artifacts or identity changes.
Retry if the photo is merely smoother, brighter, cleaner, or sharper but the under-eye/lower-face/jawline/puffiness changes are not clearly visible."""

REGION_BOXES: dict[str, tuple[float, float, float, float]] = {
    "under_eye": (0.16, 0.30, 0.84, 0.48),
    "midface": (0.12, 0.42, 0.88, 0.64),
    "lower_face": (0.18, 0.58, 0.82, 0.84),
    "jawline": (0.08, 0.62, 0.92, 0.92),
}


def _image_to_data_url(path: str) -> str:
    file_path = Path(path)
    mime = "image/png" if file_path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(file_path.read_bytes()).decode('ascii')}"


def _mean_image_difference(original_path: str, variant_path: str) -> float:
    original = Image.open(original_path).convert("RGB").resize((160, 160), Image.Resampling.LANCZOS)
    variant = Image.open(variant_path).convert("RGB").resize((160, 160), Image.Resampling.LANCZOS)
    diff = ImageChops.difference(original, variant).convert("L")
    return float(ImageStat.Stat(diff).mean[0])


def _edge_difference(original: Image.Image, variant: Image.Image) -> float:
    original_edge = original.convert("L").filter(ImageFilter.FIND_EDGES)
    variant_edge = variant.convert("L").filter(ImageFilter.FIND_EDGES)
    diff = ImageChops.difference(original_edge, variant_edge)
    return float(ImageStat.Stat(diff).mean[0])


def _region_diff_scores(original_path: str, variant_path: str) -> dict[str, float]:
    size = (240, 360)
    with Image.open(original_path) as source_image, Image.open(variant_path) as output_image:
        source = source_image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
        output = output_image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
        width, height = size
        scores: dict[str, float] = {}
        for name, box in REGION_BOXES.items():
            left, top, right, bottom = box
            px_box = (
                round(left * width),
                round(top * height),
                round(right * width),
                round(bottom * height),
            )
            source_crop = source.crop(px_box)
            output_crop = output.crop(px_box)
            pixel_diff = float(ImageStat.Stat(ImageChops.difference(source_crop, output_crop).convert("L")).mean[0])
            edge_diff = _edge_difference(source_crop, output_crop)
            scores[name] = round(pixel_diff * 0.25 + edge_diff * 0.75, 3)
    return scores


def _structural_score_from_regions(region_scores: dict[str, float], global_diff: float) -> float:
    if not region_scores:
        return 0.0
    important = [
        region_scores.get("under_eye", 0.0),
        region_scores.get("midface", 0.0),
        region_scores.get("lower_face", 0.0),
        region_scores.get("jawline", 0.0),
    ]
    top_three = sorted(important, reverse=True)[:3]
    regional_average = sum(top_three) / max(1, len(top_three))
    lower_focus = max(region_scores.get("lower_face", 0.0), region_scores.get("jawline", 0.0))
    eye_focus = region_scores.get("under_eye", 0.0)
    global_factor = min(global_diff / 14.0, 1.0)
    region_factor = min(regional_average / 8.0, 1.0)
    lower_factor = min(lower_focus / 7.0, 1.0)
    eye_factor = min(eye_focus / 6.0, 1.0)
    score = global_factor * 0.25 + region_factor * 0.35 + lower_factor * 0.25 + eye_factor * 0.15
    return round(max(0.0, min(1.0, score)), 3)


def _fallback_quality_result(original_photo_path: str, variant_path: str, reason: str) -> AfterPhotoQualityResult:
    try:
        diff = _mean_image_difference(original_photo_path, variant_path)
        region_scores = _region_diff_scores(original_photo_path, variant_path)
        structural_score = _structural_score_from_regions(region_scores, diff)
        lower_focus = max(region_scores.get("lower_face", 0.0), region_scores.get("jawline", 0.0))
        visible = 2.0 <= diff <= 42.0 and structural_score >= 0.42 and lower_focus >= 1.8
        realism = 0.72 if visible else 0.6
        identity = 0.84 if diff <= 32.0 else 0.76 if diff <= 42.0 else 0.55
        recommendation = "approve" if visible and identity >= 0.82 else "retry"
        text = (
            f"{reason}; fallback diff={diff:.2f}; structural={structural_score:.2f}; "
            f"regions={region_scores}. {'Accepted by fallback structural QA.' if recommendation == 'approve' else 'Needs regeneration.'}"
        )
    except Exception as exc:
        visible = False
        realism = 0.0
        identity = 0.0
        structural_score = 0.0
        region_scores = {}
        recommendation = "manual_review"
        text = f"{reason}; fallback scoring failed: {exc}"
    return AfterPhotoQualityResult(
        variant_path=variant_path,
        same_identity=identity >= 0.7,
        identity_score=identity,
        realism_score=realism,
        visible_improvement=visible,
        structural_change_score=structural_score,
        region_scores=region_scores,
        skin_texture_preserved=False,
        too_much_retouch=False,
        plastic_surgery_effect=False,
        recommendation=recommendation,  # type: ignore[arg-type]
        reason=text,
        fallback_scoring=True,
    )


def _with_local_structural_checks(
    result: AfterPhotoQualityResult,
    original_photo_path: str,
    variant_path: str,
) -> AfterPhotoQualityResult:
    try:
        diff = _mean_image_difference(original_photo_path, variant_path)
        region_scores = _region_diff_scores(original_photo_path, variant_path)
        structural_score = _structural_score_from_regions(region_scores, diff)
    except Exception:
        return result

    result.region_scores = {**region_scores, **(result.region_scores or {})}
    result.structural_change_score = max(result.structural_change_score or 0.0, structural_score)
    lower_focus = max(region_scores.get("lower_face", 0.0), region_scores.get("jawline", 0.0))
    if result.recommendation == "approve" and (result.structural_change_score < 0.42 or lower_focus < 1.8):
        result.recommendation = "retry"
        result.visible_improvement = False
        suffix = f" Local structural QA rejected skin/light-only edit: diff={diff:.2f}, structural={structural_score:.2f}, regions={region_scores}."
        result.reason = (result.reason or "").strip() + suffix
    return result


def _vision_quality_result(original_photo_path: str, variant_path: str) -> AfterPhotoQualityResult:
    if not (settings.openai_api_key and settings.openai_api_key.isascii() and settings.openai_vision_qa_model):
        return _fallback_quality_result(original_photo_path, variant_path, "OpenAI vision QA unavailable")

    try:
        from openai import BadRequestError, OpenAI
    except Exception as exc:
        return _fallback_quality_result(original_photo_path, variant_path, f"OpenAI client unavailable: {exc}")

    client = OpenAI(api_key=settings.openai_api_key)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": QUALITY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": QUALITY_USER_PROMPT},
                {"type": "text", "text": "Original photo:"},
                {"type": "image_url", "image_url": {"url": _image_to_data_url(original_photo_path)}},
                {"type": "text", "text": "Candidate after-photo:"},
                {"type": "image_url", "image_url": {"url": _image_to_data_url(variant_path)}},
            ],
        },
    ]
    kwargs: dict[str, Any] = {
        "model": settings.openai_vision_qa_model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 500,
    }
    response = None
    for _ in range(3):
        try:
            response = client.chat.completions.create(**kwargs)
            break
        except BadRequestError as exc:
            message = str(exc).lower()
            if "max_tokens" in message and "max_completion_tokens" in message and "max_tokens" in kwargs:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                continue
            if "temperature" in message and "temperature" in kwargs:
                kwargs.pop("temperature", None)
                continue
            raise
    if response is None:
        raise RuntimeError("Vision QA returned no response")
    content = response.choices[0].message.content or "{}"
    data = parse_json_safely(content)
    data["variant_path"] = variant_path
    try:
        result = AfterPhotoQualityResult.model_validate(data)
        return _with_local_structural_checks(result, original_photo_path, variant_path)
    except Exception as exc:
        logger.warning("Vision QA returned invalid after-photo schema", exc_info=True)
        return _fallback_quality_result(original_photo_path, variant_path, f"Vision QA schema invalid: {exc}")


def run_after_photo_quality_check(original_photo_path: str, variant_paths: list[str]) -> dict:
    logger.info("Running after-photo quality check")
    results: list[AfterPhotoQualityResult] = []
    for path in variant_paths:
        try:
            results.append(_vision_quality_result(original_photo_path, path))
        except Exception as exc:
            logger.warning("After-photo quality check failed for %s", path, exc_info=True)
            results.append(_fallback_quality_result(original_photo_path, path, f"Vision QA failed: {exc}"))
    return {
        "results": [item.model_dump() for item in results],
        "used_vision_qa": bool(settings.openai_api_key and settings.openai_api_key.isascii() and settings.openai_vision_qa_model),
    }
