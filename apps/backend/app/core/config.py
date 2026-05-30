from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/bella_vladi_bot"
    redis_url: str = "redis://localhost:6379/0"

    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"
    public_app_url: str = "http://localhost:5173"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24 * 7
    admin_email: str = "admin@bellavladi.local"
    admin_password: str = "admin12345"

    telegram_bot_token: str | None = None
    telegram_webhook_url: str | None = None
    telegram_update_mode: str = "webhook"
    telegram_webhook_secret: str | None = None
    telegram_webhook_drop_pending_updates: bool = False
    telegram_bot_username: str | None = None

    funnel_course_url: str | None = None
    funnel_installment_url: str | None = None
    funnel_manager_url: str | None = None
    funnel_training_video_path: str | None = None
    funnel_case_media_paths: str | None = None

    openai_api_key: str | None = None
    openai_analysis_model: str | None = None
    openai_report_model: str | None = None
    openai_protocol_copy_model: str | None = None
    openai_protocol_image_model: str | None = None
    openai_after_photo_image_model: str | None = None
    openai_after_photo_image_quality: str = "medium"
    openai_after_photo_image_size: str = "1024x1536"
    openai_vision_qa_model: str | None = None

    gemini_api_key: str | None = None
    gemini_model: str | None = None
    gemini_protocol_image_model: str | None = None

    ai_text_provider: str = "gemini"
    ai_image_provider: str = "openai"
    ai_analysis_model: str | None = "gemini-2.5-flash-lite"
    ai_image_model_openai: str | None = None
    ai_image_model_gemini: str | None = None
    ai_experiment_mode: bool = False

    replicate_api_token: str | None = None
    replicate_flux_model: str | None = None

    storage_driver: str = "local"
    local_storage_path: str = "./storage"

    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str | None = None

    ai_retry_count: int = 3
    ai_timeout_seconds: int = 180
    queue_concurrency: int = 2
    celery_result_expires_seconds: int = 3600
    ai_force_mock: bool = False
    ai_accept_best_effort: bool = True
    enable_gemini_fallback: bool = True
    enable_after_photo: bool = False
    face_protocol_version: str = "final_v1"
    protocol_single_image: bool = False
    protocol_image_provider: str = "openai"
    after_photo_variants: int = 3
    after_photo_variant_count: int = 3
    after_photo_provider: str = "replicate"
    after_photo_default_intensity: str = "balanced"
    after_photo_strength: float = 0.20
    after_photo_subtle_strength: float = 0.16
    after_photo_balanced_strength: float = 0.20
    after_photo_visible_strength: float = 0.30
    after_photo_guidance: float = 3.5
    after_photo_original_weight: float = 0.80
    after_photo_retry_count: int = 1
    after_photo_timeout_seconds: int = 300
    after_photo_min_visible_diff: float = 2.0
    after_photo_accept_best_effort: bool = False
    mediapipe_face_landmarker_model_path: str | None = None

    def storage_root(self) -> Path:
        return Path(self.local_storage_path).expanduser().resolve()

    @property
    def ai_mock_mode(self) -> bool:
        if self.ai_force_mock:
            return True
        provider = (self.ai_text_provider or "openai").strip().lower()
        if provider == "gemini":
            return not bool(self.gemini_api_key and (self.ai_analysis_model or self.gemini_model))
        return not bool(self.openai_api_key and (self.openai_analysis_model or self.ai_analysis_model))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


AFTER_PHOTO_FEATURE_ENABLED = False
AFTER_PHOTO_DISABLED_REASON = "After-photo disabled for MVP launch"


def after_photo_feature_enabled() -> bool:
    return AFTER_PHOTO_FEATURE_ENABLED and settings.enable_after_photo


def _is_local_url(value: str | None) -> bool:
    if not value:
        return True
    host = urlparse(value).hostname or ""
    return host in {"", "localhost", "127.0.0.1", "0.0.0.0", "frontend", "backend"}


def validate_production_settings() -> None:
    public_deployment = not all(
        _is_local_url(value)
        for value in [settings.backend_url, settings.frontend_url, settings.public_app_url, settings.telegram_webhook_url]
    )
    if not public_deployment:
        return
    problems = []
    if not settings.jwt_secret or settings.jwt_secret == "change-me" or len(settings.jwt_secret) < 32:
        problems.append("JWT_SECRET must be a long random secret")
    if settings.admin_password == "admin12345" or len(settings.admin_password) < 12:
        problems.append("ADMIN_PASSWORD must be changed from the default")
    if settings.admin_email == "admin@bellavladi.local":
        problems.append("ADMIN_EMAIL must be changed from the local default")
    if problems:
        raise RuntimeError("Unsafe production settings: " + "; ".join(problems))
