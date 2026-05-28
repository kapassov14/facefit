from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.after_photo.generator import choose_best_after_photo_variant, generate_after_photo_final
from app.after_photo.prompt_builder import UNIVERSAL_AFTER_PHOTO_PROMPT, UNIVERSAL_NEGATIVE_PROMPT, build_after_photo_prompt
from app.after_photo.quality_check import run_after_photo_quality_check
from app.after_photo.schemas import AfterPhotoQualityResult
from app.core.config import settings
from app.storage.local import local_storage


def _make_image(path: Path, color: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (256, 320), color).save(path, format="PNG")


def main() -> None:
    assert "after face fitness transformation" in UNIVERSAL_AFTER_PHOTO_PROMPT
    assert "reduce heaviness in the lower third of the face by 45-60%" in UNIVERSAL_AFTER_PHOTO_PROMPT
    assert "different person" in UNIVERSAL_NEGATIVE_PROMPT
    for intensity in ("subtle", "balanced", "visible"):
        payload = build_after_photo_prompt(intensity)
        assert payload["intensity"] == intensity
        assert payload["attempt_index"] == 1
        assert payload["negative_prompt"]
    assert "stronger visible lift" in build_after_photo_prompt("balanced", attempt_index=2)["prompt"]
    assert "maximum visible face-fitness lift" in build_after_photo_prompt("balanced", attempt_index=3)["prompt"]

    good = AfterPhotoQualityResult(
        variant_path="/tmp/approved.png",
        same_identity=True,
        identity_score=0.9,
        realism_score=0.85,
        visible_improvement=True,
        skin_texture_preserved=True,
        recommendation="approve",
        reason="ok",
    ).model_dump()
    weak = AfterPhotoQualityResult(
        variant_path="/tmp/weak.png",
        same_identity=True,
        identity_score=0.84,
        realism_score=0.8,
        visible_improvement=False,
        skin_texture_preserved=True,
        recommendation="retry",
        reason="weak",
    ).model_dump()
    assert choose_best_after_photo_variant([weak, good])["variant_path"] == "/tmp/approved.png"

    test_dir = Path(local_storage.abs_path("previews/after_photo/smoke"))
    original = test_dir / "original.png"
    variant = test_dir / "variant.png"
    _make_image(original, "#d8b19f")
    _make_image(variant, "#d9b6a4")
    old_openai_key = settings.openai_api_key
    old_vision_model = settings.openai_vision_qa_model
    old_provider = settings.after_photo_provider
    old_after_model = settings.openai_after_photo_image_model
    old_token = settings.replicate_api_token
    old_model = settings.replicate_flux_model
    try:
        settings.openai_api_key = None
        settings.openai_vision_qa_model = None
        settings.after_photo_provider = "openai"
        settings.openai_after_photo_image_model = None
        qc = run_after_photo_quality_check(str(original), [str(variant)])
        assert qc["results"]
        settings.replicate_api_token = None
        settings.replicate_flux_model = None
        skipped = generate_after_photo_final("smoke", str(original))
        assert skipped["status"] == "SKIPPED_NO_API_KEY"
    finally:
        settings.openai_api_key = old_openai_key
        settings.openai_vision_qa_model = old_vision_model
        settings.after_photo_provider = old_provider
        settings.openai_after_photo_image_model = old_after_model
        settings.replicate_api_token = old_token
        settings.replicate_flux_model = old_model

    print("After-photo smoke test passed")


if __name__ == "__main__":
    main()
