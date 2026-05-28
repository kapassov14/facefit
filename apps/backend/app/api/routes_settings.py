from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import SettingsPatch
from app.api.serializers import settings_dict
from app.core.config import settings as env_settings
from app.core.security import AdminAuth
from app.db.repositories import get_bot_settings
from app.db.session import get_db

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _key_status() -> dict:
    return {
        "openai_api_key": bool(env_settings.openai_api_key),
        "gemini_api_key": bool(env_settings.gemini_api_key),
        "replicate_api_token": bool(env_settings.replicate_api_token),
        "models": {
            "ai_text_provider": env_settings.ai_text_provider,
            "ai_image_provider": env_settings.ai_image_provider,
            "ai_analysis_model": env_settings.ai_analysis_model,
            "ai_image_model_openai": env_settings.ai_image_model_openai,
            "ai_image_model_gemini": env_settings.ai_image_model_gemini,
            "ai_experiment_mode": env_settings.ai_experiment_mode,
            "openai_analysis_model": env_settings.openai_analysis_model,
            "openai_report_model": env_settings.openai_report_model,
            "gemini_model": env_settings.gemini_model,
            "replicate_flux_model": env_settings.replicate_flux_model,
        },
        "mock_mode": env_settings.ai_mock_mode,
    }


@router.get("")
def get_settings(_: AdminAuth, db: Session = Depends(get_db)) -> dict:
    return settings_dict(get_bot_settings(db), _key_status())


@router.patch("")
def patch_settings(payload: SettingsPatch, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    settings = get_bot_settings(db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "after_photo_enabled":
            value = False
        if field == "ai_settings" and isinstance(value, dict):
            value = {**value, "enable_after_photo": False}
        setattr(settings, field, value)
    settings.after_photo_enabled = False
    if isinstance(settings.ai_settings, dict):
        settings.ai_settings = {**settings.ai_settings, "enable_after_photo": False}
    db.commit()
    db.refresh(settings)
    return settings_dict(settings, _key_status())
