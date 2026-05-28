from __future__ import annotations

import logging
import random
import shutil
import base64
import mimetypes
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageChops, ImageOps, ImageStat

from app.after_photo.prompt_builder import build_after_photo_prompt
from app.after_photo.quality_check import run_after_photo_quality_check
from app.after_photo.schemas import AfterPhotoFinalResult, AfterPhotoQualityResult
from app.core.config import settings
from app.reports.face_zone_protocol.mediapipe_map import detect_face_zone_geometry
from app.storage.local import local_storage

logger = logging.getLogger(__name__)

OPENAI_IMAGE_EDIT_ENDPOINT = "https://api.openai.com/v1/images/edits"
MIN_VISIBLE_IMAGE_DIFF = 6.0
MAX_EDIT_ATTEMPTS = 3


class AfterPhotoTooSubtleError(RuntimeError):
    pass


def _copy_as_png(source_path: str, target_path: str) -> str:
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as image:
        image.convert("RGB").save(target_path, format="PNG", optimize=True)
    return target_path


def _debug_dir() -> Path:
    primary = Path("/debug")
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception:
        fallback = Path(local_storage.abs_path("debug"))
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning("Could not write to /debug, using fallback debug dir: %s", fallback)
        return fallback


def _save_debug_png(source_path: str, filename: str) -> None:
    try:
        target = _debug_dir() / filename
        with Image.open(source_path) as image:
            image.convert("RGB").save(target, format="PNG", optimize=True)
        logger.info("Saved after-photo debug file: %s", target)
    except Exception:
        logger.warning("Failed to save after-photo debug file: %s", filename, exc_info=True)


def _output_rel(analysis_request_id: str, index: int, retry_pass: int = 0) -> str:
    suffix = f"retry_{retry_pass}_variant_{index}" if retry_pass else f"variant_{index}"
    return f"after_photos/{analysis_request_id}/after_photo_{analysis_request_id}_{suffix}.png"


def _final_rel(analysis_request_id: str) -> str:
    return f"after_photos/{analysis_request_id}/after_photo_{analysis_request_id}_final.png"


def _download_model_output(result: Any, output_abs: str) -> str:
    url = result[0] if isinstance(result, list) and result else str(result)
    Path(output_abs).parent.mkdir(parents=True, exist_ok=True)
    raw_path = str(Path(output_abs).with_suffix(".raw"))
    if not url.startswith("http"):
        raise RuntimeError("Replicate returned a non-URL result")
    with httpx.stream("GET", url, timeout=settings.after_photo_timeout_seconds) as response:
        response.raise_for_status()
        with open(raw_path, "wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)
    _copy_as_png(raw_path, output_abs)
    Path(raw_path).unlink(missing_ok=True)
    return output_abs


def _image_difference_score(source_path: str, output_path: str) -> float:
    source = Image.open(source_path).convert("RGB").resize((192, 192), Image.Resampling.LANCZOS)
    output = Image.open(output_path).convert("RGB").resize((192, 192), Image.Resampling.LANCZOS)
    diff = ImageChops.difference(source, output).convert("L")
    return float(ImageStat.Stat(diff).mean[0])


def _image_dimensions(path: str) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def _target_aspect_ratio() -> float:
    raw = (settings.openai_after_photo_image_size or "1024x1536").lower().strip()
    if "x" in raw:
        try:
            width, height = [int(part) for part in raw.split("x", 1)]
            if width > 0 and height > 0:
                return width / height
        except Exception:
            pass
    return 2 / 3


def _crop_box_from_face_box(face_box: dict[str, Any], image_width: int, image_height: int) -> tuple[int, int, int, int]:
    left = float(face_box.get("left") or 0.18) * image_width
    right = float(face_box.get("right") or 0.82) * image_width
    top = float(face_box.get("top") or 0.08) * image_height
    bottom = float(face_box.get("bottom") or 0.92) * image_height
    face_width = max(1.0, right - left)
    face_height = max(1.0, bottom - top)
    target_ratio = _target_aspect_ratio()
    crop_h = max(face_height / 0.70, face_width / max(target_ratio * 0.82, 0.1))
    crop_w = crop_h * target_ratio
    if crop_w > image_width:
        crop_w = float(image_width)
        crop_h = crop_w / target_ratio
    if crop_h > image_height:
        crop_h = float(image_height)
        crop_w = crop_h * target_ratio
    center_x = (left + right) / 2
    center_y = top + face_height * 0.52
    x0 = max(0.0, min(image_width - crop_w, center_x - crop_w / 2))
    y0 = max(0.0, min(image_height - crop_h, center_y - crop_h / 2))
    return (round(x0), round(y0), round(x0 + crop_w), round(y0 + crop_h))


def _prepare_after_photo_input_crop(analysis_request_id: str, original_photo_path: str) -> tuple[str, dict[str, Any]]:
    geometry = detect_face_zone_geometry(original_photo_path)
    quality = geometry.get("quality") if isinstance(geometry.get("quality"), dict) else {}
    face_box = quality.get("face_box") if isinstance(quality.get("face_box"), dict) else None
    if not face_box:
        return original_photo_path, {"used": False, "reason": geometry.get("reason") or "face_box_unavailable", "quality": quality}
    with Image.open(original_photo_path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        source_width, source_height = image.width, image.height
        crop_box = _crop_box_from_face_box(face_box, source_width, source_height)
        cropped = image.crop(crop_box)
        target_rel = f"after_photos/{analysis_request_id}/after_photo_{analysis_request_id}_input_crop.png"
        target_abs = local_storage.abs_path(target_rel)
        Path(target_abs).parent.mkdir(parents=True, exist_ok=True)
        cropped.save(target_abs, format="PNG", optimize=True)
    face_height_ratio = (float(face_box.get("height") or 0) * source_height) / max(1, crop_box[3] - crop_box[1])
    metadata = {
        "used": True,
        "path": target_rel,
        "abs_path": target_abs,
        "crop_box": crop_box,
        "face_height_ratio": round(face_height_ratio, 3),
        "quality": quality,
    }
    logger.info("Prepared after-photo face crop: %s", metadata)
    return target_abs, metadata


def _log_generation_result(
    *,
    model: str,
    endpoint: str,
    request_id: str | None,
    source_path: str,
    output_path: str,
    b64_json_exists: bool,
) -> float:
    output = Path(output_path)
    original_width, original_height = _image_dimensions(source_path)
    width, height = _image_dimensions(output_path)
    diff = _image_difference_score(source_path, output_path)
    is_different = diff >= _min_visible_image_diff()
    buffers_identical = Path(source_path).read_bytes() == output.read_bytes()
    logger.info(
        (
            "AFTER_PHOTO_IMAGE_GENERATION endpoint=%s model=%s request_id=%s "
            "original_dimensions=%sx%s generated_dimensions=%sx%s output_bytes=%s "
            "b64_json_exists=%s buffers_identical=%s diff_score=%.2f is_different=%s"
        ),
        endpoint,
        model,
        request_id or "n/a",
        original_width,
        original_height,
        width,
        height,
        output.stat().st_size if output.exists() else 0,
        b64_json_exists,
        buffers_identical,
        diff,
        is_different,
    )
    return diff


def _assert_after_photo_is_different(source_path: str, output_path: str) -> None:
    min_required = _min_visible_image_diff()
    diff = _image_difference_score(source_path, output_path)
    if diff < min_required:
        logger.warning(
            "After-photo diff is below previous threshold, but quality filter is disabled; "
            "accepting generated image. diff_score=%.2f min_required=%.2f",
            diff,
            min_required,
        )


def _min_visible_image_diff() -> float:
    configured = float(settings.after_photo_min_visible_diff or MIN_VISIBLE_IMAGE_DIFF)
    return max(0.5, min(20.0, configured))


def _save_openai_image_response(payload: dict[str, Any], output_abs: str) -> str:
    data = payload.get("data") or []
    if not data:
        raise RuntimeError("OpenAI image edit returned no image data")
    first = data[0]
    Path(output_abs).parent.mkdir(parents=True, exist_ok=True)
    if first.get("b64_json"):
        Path(output_abs).write_bytes(base64.b64decode(first["b64_json"]))
        return output_abs
    if first.get("url"):
        return _download_model_output(first["url"], output_abs)
    raise RuntimeError("OpenAI image edit returned neither b64_json nor url")


def _save_image_bytes(image_bytes: bytes, output_abs: str) -> str:
    Path(output_abs).parent.mkdir(parents=True, exist_ok=True)
    raw_path = str(Path(output_abs).with_suffix(".raw"))
    Path(raw_path).write_bytes(image_bytes)
    try:
        _copy_as_png(raw_path, output_abs)
    finally:
        Path(raw_path).unlink(missing_ok=True)
    return output_abs


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


def image_provider_has_credentials(provider: str | None) -> bool:
    normalized = (provider or settings.ai_image_provider or settings.after_photo_provider or "openai").strip().lower()
    if normalized == "openai":
        return bool(settings.openai_api_key and settings.openai_api_key.isascii())
    if normalized == "gemini":
        return bool(settings.gemini_api_key and (settings.ai_image_model_gemini or settings.gemini_protocol_image_model or settings.gemini_model))
    if normalized == "replicate":
        return bool(settings.replicate_api_token and settings.replicate_flux_model)
    return False


def _generate_openai_variant(photo_path: str, output_abs: str, prompt_payload: dict[str, Any], seed: int) -> str:
    model = settings.ai_image_model_openai or settings.openai_after_photo_image_model or settings.openai_protocol_image_model or "gpt-image-2"
    prompt = (
        f"{prompt_payload['prompt']}\n\n"
        f"Negative constraints: {prompt_payload.get('negative_prompt') or ''}\n\n"
        "Use the uploaded portrait as the identity and composition source. "
        "Make a strong visible structural face-fitness edit. Do not return the original photo unchanged."
    )
    mime = mimetypes.guess_type(photo_path)[0] or "image/jpeg"
    data: dict[str, str] = {
        "model": model,
        "prompt": prompt,
        "n": "1",
        "size": settings.openai_after_photo_image_size,
        "quality": settings.openai_after_photo_image_quality,
        "input_fidelity": "high",
        "output_format": "png",
    }
    response: httpx.Response | None = None
    for unsupported_key in (None, "input_fidelity", "quality", "output_format", "size"):
        if unsupported_key:
            data.pop(unsupported_key, None)
        with open(photo_path, "rb") as image_file:
            response = httpx.post(
                OPENAI_IMAGE_EDIT_ENDPOINT,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                data=data,
                files={"image": (Path(photo_path).name, image_file, mime)},
                timeout=settings.after_photo_timeout_seconds,
            )
        if response.status_code < 400:
            break
        message = response.text.lower()
        if unsupported_key == "size" or not any(key in message for key in ("input_fidelity", "quality", "output_format", "size")):
            break
    if response is None or response.status_code >= 400:
        detail = response.text[:1200] if response is not None else "empty response"
        request_id = None
        if response is not None:
            request_id = (
                response.headers.get("x-request-id")
                or response.headers.get("openai-request-id")
                or response.headers.get("request-id")
            )
        logger.error(
            "OpenAI image edit failed model=%s endpoint=%s request_id=%s detail=%s",
            model,
            "/v1/images/edits",
            request_id or "n/a",
            detail,
        )
        raise RuntimeError(f"OpenAI image edit failed with model={model}: {detail}")
    payload = response.json()
    first_item = (payload.get("data") or [{}])[0]
    b64_json_exists = bool(first_item.get("b64_json"))
    saved = _save_openai_image_response(payload, output_abs)
    request_id = (
        response.headers.get("x-request-id")
        or response.headers.get("openai-request-id")
        or response.headers.get("request-id")
    )
    _log_generation_result(
        model=model,
        endpoint="/v1/images/edits",
        request_id=request_id,
        source_path=photo_path,
        output_path=saved,
        b64_json_exists=b64_json_exists,
    )
    _assert_after_photo_is_different(photo_path, saved)
    return saved


def _generate_gemini_variant(photo_path: str, output_abs: str, prompt_payload: dict[str, Any], seed: int) -> str:
    model = (settings.ai_image_model_gemini or settings.gemini_protocol_image_model or settings.gemini_model or "").removeprefix("models/")
    if not (settings.gemini_api_key and model):
        raise RuntimeError("Gemini image edit is not configured")
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            prompt_payload["prompt"]
                            + "\n\nThis is an image edit. Use the provided image as the source portrait."
                            + "\nReturn one edited image."
                        )
                    },
                    _read_image_part(photo_path),
                ],
            }
        ],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=settings.after_photo_timeout_seconds,
    )
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(f"Gemini image edit failed: {detail[:800]}")
    data = response.json()
    image_bytes = _extract_inline_image(data)
    if not image_bytes:
        text = _extract_text(data)
        raise RuntimeError(f"Gemini image edit returned no image. Text response: {text[:500]}")
    saved = _save_image_bytes(image_bytes, output_abs)
    _log_generation_result(
        model=model,
        endpoint="gemini.generateContent",
        request_id=None,
        source_path=photo_path,
        output_path=saved,
        b64_json_exists=False,
    )
    _assert_after_photo_is_different(photo_path, saved)
    return saved


def _generate_provider_variant(photo_path: str, output_abs: str, prompt_payload: dict[str, Any], seed: int, provider_override: str | None = None) -> str:
    if settings.ai_force_mock:
        return _copy_as_png(photo_path, output_abs)

    provider = (provider_override or settings.ai_image_provider or settings.after_photo_provider or "openai").strip().lower()
    if provider == "openai":
        return _generate_openai_variant(photo_path, output_abs, prompt_payload, seed)
    if provider == "gemini":
        return _generate_gemini_variant(photo_path, output_abs, prompt_payload, seed)

    import replicate

    client = replicate.Client(api_token=settings.replicate_api_token)
    preset = prompt_payload.get("preset") or {}
    with open(photo_path, "rb") as image_file:
        request_input: dict[str, Any] = {
            "prompt": prompt_payload["prompt"],
            "input_image": image_file,
            "aspect_ratio": "match_input_image",
            "strength": float(preset.get("strength") or settings.after_photo_strength),
            "guidance": float(preset.get("guidance") or settings.after_photo_guidance),
            "seed": seed,
        }
        if prompt_payload.get("negative_prompt"):
            request_input["negative_prompt"] = prompt_payload["negative_prompt"]
        try:
            result = client.run(settings.replicate_flux_model, input=request_input)
        except Exception as exc:
            message = str(exc)
            retried = False
            for key in ("negative_prompt", "strength", "guidance", "seed"):
                if key in request_input and key in message:
                    request_input.pop(key, None)
                    retried = True
            if not retried:
                raise
            image_file.seek(0)
            result = client.run(settings.replicate_flux_model, input=request_input)
    saved = _download_model_output(result, output_abs)
    _log_generation_result(
        model=settings.replicate_flux_model or "replicate",
        endpoint="replicate.run",
        request_id=None,
        source_path=photo_path,
        output_path=saved,
        b64_json_exists=False,
    )
    _assert_after_photo_is_different(photo_path, saved)
    return saved


def generate_after_photo_variants(
    analysis_request_id: str,
    photo_path: str,
    intensity: str | None = None,
    retry_pass: int = 0,
    attempt_index: int = 1,
    variant_count: int | None = None,
    provider_override: str | None = None,
    analysis_json: dict[str, Any] | None = None,
    selected_problems: list[str] | None = None,
) -> list[str]:
    logger.info("AFTER_PHOTO_PIPELINE=structured_face_crop_qa_v1")
    prompt_payload = build_after_photo_prompt(
        intensity or settings.after_photo_default_intensity,
        attempt_index=attempt_index,
        analysis_json=analysis_json,
        selected_problems=selected_problems,
    )
    logger.info("Selected intensity: %s", prompt_payload["intensity"])
    logger.info("Generating after-photo variants from source image: %s; edit_attempt=%s", photo_path, attempt_index)

    count = variant_count if variant_count is not None else (settings.after_photo_variant_count or settings.after_photo_variants or 3)
    variant_total = max(1, min(6, count))
    variant_paths: list[str] = []
    for index in range(1, variant_total + 1):
        output_rel = _output_rel(analysis_request_id, index, retry_pass)
        output_abs = local_storage.abs_path(output_rel)
        seed = random.randint(10_000, 999_999)
        _generate_provider_variant(photo_path, output_abs, prompt_payload, seed, provider_override=provider_override)
        if Path(output_abs).exists() and Path(output_abs).stat().st_size > 0:
            _assert_after_photo_is_different(photo_path, output_abs)
            if index == 1:
                _save_debug_png(output_abs, f"after-attempt-{attempt_index}.png")
            logger.info("Generated variant: %s", output_rel)
            variant_paths.append(output_rel)
        else:
            raise RuntimeError(f"After-photo variant was not created: {output_rel}")
    return variant_paths


def choose_best_after_photo_variant(qc_results: list[dict[str, Any]]) -> dict:
    results = [AfterPhotoQualityResult.model_validate(item) for item in qc_results]
    approved = [item for item in results if item.approved]
    if approved:
        best = max(approved, key=lambda item: item.ranking_score)
        return {"status": "approved", "variant_path": best.variant_path, "quality": best.model_dump(), "score": best.ranking_score}
    if not results:
        return {"status": "manual_review", "reason": "No quality results"}
    best = max(results, key=lambda item: item.ranking_score)
    return {"status": "manual_review", "variant_path": best.variant_path, "quality": best.model_dump(), "score": best.ranking_score}


def _choose_best_effort_variant(original_photo_path: str, variant_paths: list[str], qc_results: list[dict[str, Any]]) -> dict | None:
    if not settings.after_photo_accept_best_effort or not variant_paths:
        return None

    by_path = {item.get("variant_path"): item for item in qc_results if isinstance(item, dict) and item.get("variant_path")}
    candidates: list[dict[str, Any]] = []
    for path in variant_paths:
        abs_path = local_storage.abs_path(path)
        if not Path(abs_path).exists():
            continue
        try:
            diff = _image_difference_score(original_photo_path, abs_path)
        except Exception:
            continue
        if diff < _min_visible_image_diff():
            continue
        quality = by_path.get(abs_path) or by_path.get(path) or {}
        recommendation = str(quality.get("recommendation") or "manual_review").lower()
        if recommendation == "reject" or quality.get("too_much_retouch"):
            continue
        rank = float(quality.get("ranking_score") or 0.0) if isinstance(quality, dict) else 0.0
        if not rank and isinstance(quality, dict):
            identity = float(quality.get("identity_score") or 0.0)
            realism = float(quality.get("realism_score") or 0.0)
            rank = identity * 0.6 + realism * 0.15 + min(diff / 40.0, 0.2)
        candidates.append({"path": path, "abs_path": abs_path, "diff": diff, "quality": quality, "score": rank + min(diff / 100.0, 0.1)})

    if not candidates:
        return None
    return max(candidates, key=lambda item: item["score"])


def _copy_final_variant(analysis_request_id: str, variant_abs_or_rel: str) -> str:
    final_rel = _final_rel(analysis_request_id)
    final_abs = local_storage.abs_path(final_rel)
    Path(final_abs).parent.mkdir(parents=True, exist_ok=True)
    source = variant_abs_or_rel
    if not Path(source).is_absolute():
        source = local_storage.abs_path(source)
    shutil.copyfile(source, final_abs)
    return final_rel


def _choose_most_changed_variant(original_photo_path: str, variant_paths: list[str]) -> dict:
    best: dict[str, Any] | None = None
    for path in variant_paths:
        abs_path = local_storage.abs_path(path)
        if not Path(abs_path).exists():
            continue
        try:
            diff = _image_difference_score(original_photo_path, abs_path)
        except Exception:
            diff = 0.0
        candidate = {"path": path, "abs_path": abs_path, "diff": diff}
        if best is None or candidate["diff"] > best["diff"]:
            best = candidate
    if not best:
        raise RuntimeError("No generated after-photo variant exists")
    return best


def _quality_is_too_subtle(quality_results: list[dict[str, Any]]) -> bool:
    if not quality_results:
        return True
    parsed = [AfterPhotoQualityResult.model_validate(item) for item in quality_results]
    return all(not item.visible_improvement or item.recommendation == "retry" for item in parsed)


def generate_after_photo_final(
    analysis_request_id: str,
    original_photo_path: str,
    preferred_intensity: str | None = None,
    provider_override: str | None = None,
    analysis_json: dict[str, Any] | None = None,
    selected_problems: list[str] | None = None,
) -> dict:
    intensity = (preferred_intensity or settings.after_photo_default_intensity or "balanced").strip().lower()
    if intensity not in {"subtle", "balanced", "visible"}:
        intensity = "balanced"

    provider = (provider_override or settings.ai_image_provider or settings.after_photo_provider or "openai").strip().lower()
    missing_reason = f"{provider} image provider credentials are missing"
    has_generation_credentials = image_provider_has_credentials(provider)

    if not has_generation_credentials:
        logger.warning("No after-photo generation credentials, skipping after-photo generation")
        result = AfterPhotoFinalResult(
            status="SKIPPED_NO_API_KEY",
            used_intensity=intensity,  # type: ignore[arg-type]
            reason=missing_reason,
        ).model_dump()
        result["provider"] = provider
        return result

    all_variant_paths: list[str] = []
    used_retry = False
    retry_count = 0

    try:
        _save_debug_png(original_photo_path, "original.png")
        edit_input_path, crop_metadata = _prepare_after_photo_input_crop(analysis_request_id, original_photo_path)
        _save_debug_png(edit_input_path, "after-input-crop.png")
        current_intensity = "visible"
        attempt_index = MAX_EDIT_ATTEMPTS
        count = max(2, min(4, int(settings.after_photo_variant_count or settings.after_photo_variants or 3)))
        logger.info(
            "After-photo structured generation using intensity=%s attempt=%s variant_count=%s crop_used=%s",
            current_intensity,
            attempt_index,
            count,
            crop_metadata.get("used"),
        )
        variant_rel_paths = generate_after_photo_variants(
            analysis_request_id=analysis_request_id,
            photo_path=edit_input_path,
            intensity=current_intensity,
            retry_pass=0,
            attempt_index=attempt_index,
            variant_count=count,
            provider_override=provider,
            analysis_json=analysis_json,
            selected_problems=selected_problems,
        )
        all_variant_paths.extend(variant_rel_paths)
        variant_abs_paths = [local_storage.abs_path(path) for path in all_variant_paths]
        quality_payload = run_after_photo_quality_check(edit_input_path, variant_abs_paths)
        quality_results = quality_payload.get("results") or []
        best_choice = choose_best_after_photo_variant(quality_results)
        if best_choice.get("status") != "approved":
            best_effort = _choose_best_effort_variant(edit_input_path, all_variant_paths, quality_results)
            if not best_effort:
                used_retry = True
                retry_count = 1
                retry_rel_paths = generate_after_photo_variants(
                    analysis_request_id=analysis_request_id,
                    photo_path=edit_input_path,
                    intensity=current_intensity,
                    retry_pass=retry_count,
                    attempt_index=MAX_EDIT_ATTEMPTS,
                    variant_count=count,
                    provider_override=provider,
                    analysis_json=analysis_json,
                    selected_problems=selected_problems,
                )
                all_variant_paths.extend(retry_rel_paths)
                retry_abs_paths = [local_storage.abs_path(path) for path in retry_rel_paths]
                retry_quality = run_after_photo_quality_check(edit_input_path, retry_abs_paths)
                quality_results.extend(retry_quality.get("results") or [])
                best_choice = choose_best_after_photo_variant(quality_results)
                best_effort = _choose_best_effort_variant(edit_input_path, all_variant_paths, quality_results)
            if best_choice.get("status") != "approved" and best_effort:
                best_choice = {
                    "status": "manual_review",
                    "variant_path": best_effort["path"],
                    "quality": best_effort.get("quality") or {},
                    "score": best_effort.get("score") or 0,
                }
        variant_path = best_choice.get("variant_path")
        if not variant_path:
            raise AfterPhotoTooSubtleError("After-photo QA rejected all variants: no visible structural edit")
        final_rel = _copy_final_variant(analysis_request_id, str(variant_path))
        status = "APPROVED" if best_choice.get("status") == "approved" or settings.after_photo_accept_best_effort else "NEEDS_MANUAL_REVIEW"
        reason = f"Structured after-photo selected by QA; choice={best_choice.get('status')} score={best_choice.get('score')}"
        logger.info(reason)
        result = AfterPhotoFinalResult(
            status=status,  # type: ignore[arg-type]
            final_path=final_rel,
            variant_paths=all_variant_paths,
            quality_results=quality_results,
            used_intensity=current_intensity,  # type: ignore[arg-type]
            used_retry=used_retry,
            retry_count=retry_count,
            reason=reason,
        ).model_dump()
        result["provider"] = provider
        result["crop"] = crop_metadata
        result["quality_used_vision_qa"] = quality_payload.get("used_vision_qa")
        result["structured_focus"] = build_after_photo_prompt(
            current_intensity,
            attempt_index=attempt_index,
            analysis_json=analysis_json,
            selected_problems=selected_problems,
        ).get("structured_focus")
        return result
    except Exception as exc:
        logger.error("After-photo generation failed", exc_info=True)
        result = AfterPhotoFinalResult(
            status="FAILED",
            final_path=None,
            variant_paths=all_variant_paths,
            quality_results=[],
            used_intensity=intensity,  # type: ignore[arg-type]
            used_retry=used_retry,
            retry_count=retry_count,
            reason=str(exc),
        ).model_dump()
        result["provider"] = provider
        return result
