from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.reports import protocol_image
from app.reports.face_protocol_final.normalize import normalize_protocol_copy
from app.reports.face_protocol_final.renderer import render_face_protocol_final_v1
from app.reports.face_protocol_final.schema import EXAMPLE_PROTOCOL_COPY
from app.reports.protocol_v2 import renderer as protocol_v2_renderer
from app.reports.protocol_v3 import renderer as protocol_v3_renderer
from app.reports.protocol_v4 import renderer as protocol_v4_renderer

EXPECTED_LEGACY_ERROR = "LEGACY_FACE_PROTOCOL_RENDERER_DISABLED_USE_FINAL_V1"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_legacy_disabled(name: str, call) -> None:
    try:
        call()
    except RuntimeError as exc:
        _assert(str(exc) == EXPECTED_LEGACY_ERROR, f"{name} has wrong legacy error: {exc}")
        return
    raise AssertionError(f"{name} did not raise legacy renderer error")


def main() -> None:
    module_dir = Path(__file__).resolve().parent
    template_path = module_dir / "template.html"
    _assert(template_path.exists(), "template.html does not exist")

    normalized = normalize_protocol_copy(EXAMPLE_PROTOCOL_COPY)
    _assert(normalized["skin_age"]["comment"], "normalize_protocol_copy did not return skin_age.comment")
    _assert(len(normalized["zones"]) == 6, "normalize_protocol_copy did not return six MVP map zones")

    output_dir = settings.storage_root() / "previews" / "face_protocol_final" / "smoke"
    png_path = Path(
        render_face_protocol_final_v1(
            analysis_request_id="smoke",
            user_name="Smoke",
            user_photo_path_or_url="",
            protocol_copy=normalized,
            output_dir=str(output_dir),
            created_at=datetime.now(),
        )
    )
    html_path = output_dir / "face_protocol_final_v1_smoke.html"
    _assert(png_path.exists(), "renderer did not create PNG")
    _assert(png_path.stat().st_size > 10_000, "renderer PNG is empty or too small")
    _assert(html_path.exists(), "renderer did not create HTML preview")

    _assert_legacy_disabled(
        "protocol_image.generate_protocol_image",
        lambda: protocol_image.generate_protocol_image("missing.jpg", "out.png", "Smoke", {}),
    )
    _assert_legacy_disabled(
        "protocol_v2.generate_face_protocol_slides_v2",
        lambda: protocol_v2_renderer.generate_face_protocol_slides_v2("1", "missing.jpg", {}, "Smoke", datetime.now(), "/tmp/v2"),
    )
    _assert_legacy_disabled(
        "protocol_v3.render_face_protocol_v3",
        lambda: protocol_v3_renderer.render_face_protocol_v3("1", "Smoke", "missing.jpg", {}, "/tmp/v3", datetime.now()),
    )
    _assert_legacy_disabled(
        "protocol_v4.render_face_protocol_v4",
        lambda: protocol_v4_renderer.render_face_protocol_v4("1", "Smoke", "missing.jpg", {}, "/tmp/v4", datetime.now()),
    )

    workers_dir = Path(__file__).resolve().parents[2] / "workers"
    analysis_source = (workers_dir / "tasks_analysis.py").read_text(encoding="utf-8")
    telegram_source = (workers_dir / "tasks_telegram.py").read_text(encoding="utf-8")
    _assert("render_face_protocol_final_v1" not in analysis_source, "pipeline still imports first protocol renderer")
    _assert("render_face_zone_protocol_v1" in analysis_source, "pipeline does not render journal zone protocol")
    _assert("render_face_protocol_v4" not in analysis_source, "pipeline still imports protocol_v4 renderer")
    _assert('face_protocol_version = "final_v1"' in analysis_source, "new analyses do not save face_protocol_version = final_v1")
    _assert("analysis.face_protocol_image_path" in telegram_source, "Telegram flow does not use face_protocol_image_path")
    _assert("FSInputFile(protocol_image_path)" in telegram_source, "Telegram send does not send final_v1 PNG path")
    _assert("legacy_protocol_image_url" not in telegram_source, "Telegram send uses legacy_protocol_image_url")

    print(f"Smoke test OK: {png_path.resolve()}")


if __name__ == "__main__":
    main()
