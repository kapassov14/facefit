from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.after_photo.generator import generate_after_photo_final, image_provider_has_credentials
from app.ai.gemini_client import analyze_face_with_gemini
from app.ai.openai_client import analyze_face
from app.core.config import settings


class TextVisionProvider(Protocol):
    name: str

    def analyze_face_photo(
        self,
        photo_path: str,
        user_name: str | None,
        selected_problems: list[str],
        knowledge_context: str,
        system_prompt: str,
        user_age: int | None = None,
    ) -> dict[str, Any]:
        ...


class ImageEditProvider(Protocol):
    name: str

    def generate_after_photo(
        self,
        analysis_request_id: str,
        photo_path: str,
        intensity: str | None = None,
        analysis_json: dict[str, Any] | None = None,
        selected_problems: list[str] | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass
class ProviderResult:
    provider: str
    payload: dict[str, Any]
    latency_ms: int
    fallback_used: bool = False
    error: str | None = None


class OpenAITextVisionProvider:
    name = "openai"

    def analyze_face_photo(
        self,
        photo_path: str,
        user_name: str | None,
        selected_problems: list[str],
        knowledge_context: str,
        system_prompt: str,
        user_age: int | None = None,
    ) -> dict[str, Any]:
        return analyze_face(photo_path, user_name, selected_problems, knowledge_context, system_prompt, user_age=user_age)


class GeminiTextVisionProvider:
    name = "gemini"

    def analyze_face_photo(
        self,
        photo_path: str,
        user_name: str | None,
        selected_problems: list[str],
        knowledge_context: str,
        system_prompt: str,
        user_age: int | None = None,
    ) -> dict[str, Any]:
        return analyze_face_with_gemini(photo_path, user_name, selected_problems, knowledge_context, system_prompt, user_age=user_age)


class OpenAIImageEditProvider:
    name = "openai"

    def generate_after_photo(
        self,
        analysis_request_id: str,
        photo_path: str,
        intensity: str | None = None,
        analysis_json: dict[str, Any] | None = None,
        selected_problems: list[str] | None = None,
    ) -> dict[str, Any]:
        return generate_after_photo_final(
            analysis_request_id,
            photo_path,
            preferred_intensity=intensity,
            provider_override="openai",
            analysis_json=analysis_json,
            selected_problems=selected_problems,
        )


class GeminiImageEditProvider:
    name = "gemini"

    def generate_after_photo(
        self,
        analysis_request_id: str,
        photo_path: str,
        intensity: str | None = None,
        analysis_json: dict[str, Any] | None = None,
        selected_problems: list[str] | None = None,
    ) -> dict[str, Any]:
        return generate_after_photo_final(
            analysis_request_id,
            photo_path,
            preferred_intensity=intensity,
            provider_override="gemini",
            analysis_json=analysis_json,
            selected_problems=selected_problems,
        )


TEXT_PROVIDERS: dict[str, TextVisionProvider] = {
    "openai": OpenAITextVisionProvider(),
    "gemini": GeminiTextVisionProvider(),
}

IMAGE_PROVIDERS: dict[str, ImageEditProvider] = {
    "openai": OpenAIImageEditProvider(),
    "gemini": GeminiImageEditProvider(),
}


def normalize_provider(value: str | None, fallback: str = "openai") -> str:
    provider = (value or fallback).strip().lower()
    return provider if provider in {"openai", "gemini"} else fallback


def _text_provider_has_credentials(provider: str) -> bool:
    if provider == "gemini":
        return bool(settings.gemini_api_key and (settings.ai_analysis_model or settings.gemini_model))
    return bool(settings.openai_api_key and settings.openai_api_key.isascii())


def _logged_v4_fallback_payload(
    *,
    user_name: str | None,
    selected_problems: list[str],
    user_age: int | None,
    reason: str,
) -> dict[str, Any]:
    raise RuntimeError(f"AI protocol generation requires a real vision model: {reason}")


def analyze_face_with_fallback(
    photo_path: str,
    user_name: str | None,
    selected_problems: list[str],
    knowledge_context: str,
    system_prompt: str,
    user_age: int | None = None,
) -> ProviderResult:
    if settings.ai_force_mock:
        payload = _logged_v4_fallback_payload(
            user_name=user_name,
            selected_problems=selected_problems,
            user_age=user_age,
            reason="AI_FORCE_MOCK is enabled",
        )
        return ProviderResult(provider="mock", payload=payload, latency_ms=0, fallback_used=True, error="AI_FORCE_MOCK is enabled")

    preferred = normalize_provider(settings.ai_text_provider, "gemini")
    provider_order = [preferred, "openai" if preferred == "gemini" else "gemini"]
    last_error: str | None = None
    for index, provider_name in enumerate(provider_order):
        if not _text_provider_has_credentials(provider_name):
            last_error = f"{provider_name} credentials are missing"
            continue
        provider = TEXT_PROVIDERS[provider_name]
        started = time.perf_counter()
        try:
            payload = provider.analyze_face_photo(photo_path, user_name, selected_problems, knowledge_context, system_prompt, user_age=user_age)
            return ProviderResult(
                provider=provider_name,
                payload=payload,
                latency_ms=int((time.perf_counter() - started) * 1000),
                fallback_used=index > 0,
            )
        except Exception as exc:
            last_error = str(exc)
            continue
    if not (settings.openai_api_key or settings.gemini_api_key):
        raise RuntimeError("No AI text provider credentials; protocol generation requires a real AI response")
    raise RuntimeError(last_error or "No AI text provider is available")


def choose_image_provider_for_user(user_key: str | int | None = None) -> str:
    configured = normalize_provider(settings.ai_image_provider, "openai")
    if not settings.ai_experiment_mode:
        return configured
    key = str(user_key or "")
    bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % 2
    return "openai" if bucket == 0 else "gemini"


def generate_after_photo_with_fallback(
    analysis_request_id: str,
    photo_path: str,
    user_key: str | int | None = None,
    intensity: str | None = None,
    analysis_json: dict[str, Any] | None = None,
    selected_problems: list[str] | None = None,
) -> ProviderResult:
    preferred = choose_image_provider_for_user(user_key)
    provider_order = [preferred, "openai" if preferred == "gemini" else "gemini"]
    last_result: dict[str, Any] | None = None
    last_error: str | None = None
    for index, provider_name in enumerate(provider_order):
        if not image_provider_has_credentials(provider_name):
            last_error = f"{provider_name} image credentials are missing"
            continue
        provider = IMAGE_PROVIDERS[provider_name]
        started = time.perf_counter()
        try:
            result = provider.generate_after_photo(analysis_request_id, photo_path, intensity, analysis_json, selected_problems)
            result["provider"] = provider_name
            latency = int((time.perf_counter() - started) * 1000)
            if result.get("status") not in {"FAILED", "SKIPPED_NO_API_KEY"}:
                return ProviderResult(provider=provider_name, payload=result, latency_ms=latency, fallback_used=index > 0)
            last_result = result
            last_error = result.get("reason") or result.get("status")
        except Exception as exc:
            last_error = str(exc)
            continue
    if last_result is not None:
        return ProviderResult(provider=last_result.get("provider") or preferred, payload=last_result, latency_ms=0, fallback_used=True, error=last_error)
    return ProviderResult(
        provider=preferred,
        payload={"status": "SKIPPED_NO_API_KEY", "reason": last_error or "No image provider is available"},
        latency_ms=0,
        fallback_used=True,
        error=last_error,
    )
