from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
from statistics import mean
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_ZONE_GEOMETRY: dict[str, dict[str, dict[str, float] | str]] = {
    "forehead": {"anchor": {"x": 50, "y": 20}, "shape": {"type": "ellipse", "x": 50, "y": 20, "width": 44, "height": 12}},
    "brow": {"anchor": {"x": 50, "y": 34}, "shape": {"type": "ellipse", "x": 50, "y": 34, "width": 20, "height": 12}},
    "eye_area": {"anchor": {"x": 39, "y": 39}, "shape": {"type": "ellipse", "x": 50, "y": 39, "width": 45, "height": 14}},
    "nasolabial": {"anchor": {"x": 58, "y": 57}, "shape": {"type": "ellipse", "x": 55, "y": 57, "width": 24, "height": 18}},
    "mouth_area": {"anchor": {"x": 50, "y": 64}, "shape": {"type": "ellipse", "x": 50, "y": 64, "width": 26, "height": 14}},
    "face_oval": {"anchor": {"x": 63, "y": 72}, "shape": {"type": "ellipse", "x": 50, "y": 72, "width": 52, "height": 20}},
    "cheeks": {"anchor": {"x": 50, "y": 51}, "shape": {"type": "ellipse", "x": 50, "y": 51, "width": 50, "height": 18}},
    "neck": {"anchor": {"x": 50, "y": 88}, "shape": {"type": "ellipse", "x": 50, "y": 88, "width": 38, "height": 14}},
    "overall": {"anchor": {"x": 50, "y": 50}, "shape": {"type": "ellipse", "x": 50, "y": 50, "width": 58, "height": 58}},
}

ZONE_ALIASES: list[tuple[str, str]] = [
    (r"лоб|forehead", "forehead"),
    (r"межбров|бров|brow", "brow"),
    (r"под\s*глаз|глаз|век|eye|under", "eye_area"),
    (r"носогуб|nasolab", "nasolabial"),
    (r"рот|губ|около.?рот|mouth|lip", "mouth_area"),
    (r"овал|челюст|подбород|брыл|нижн|jaw|chin|oval", "face_oval"),
    (r"щек|щёк|скул|cheek", "cheeks"),
    (r"шея|neck", "neck"),
    (r"кож|тон|свеж|сиян|skin|fresh", "cheeks"),
    (r"отеч|отёч|puff", "face_oval"),
]

LANDMARK_GROUPS: dict[str, list[int]] = {
    "forehead": [10, 67, 109, 151, 338, 297],
    "brow": [9, 8, 55, 65, 285, 295],
    "eye_area": [33, 133, 159, 145, 362, 263, 386, 374],
    "nasolabial": [2, 98, 327, 205, 425, 164],
    "mouth_area": [0, 13, 14, 17, 61, 291],
    "face_oval": [172, 397, 152, 175, 150, 379, 234, 454],
    "cheeks": [50, 187, 205, 280, 411, 425],
    "neck": [152, 175, 148, 377],
    "overall": [10, 152, 234, 454],
}

FACE_OVAL_CONTOUR = [
    10,
    338,
    297,
    332,
    284,
    251,
    389,
    356,
    454,
    323,
    361,
    288,
    397,
    365,
    379,
    378,
    400,
    377,
    152,
    148,
    176,
    149,
    150,
    136,
    172,
    58,
    132,
    93,
    234,
    127,
    162,
    21,
    54,
    103,
    67,
    109,
]

LOWER_FACE_CONTOUR = [
    234,
    93,
    132,
    58,
    172,
    136,
    150,
    149,
    176,
    148,
    152,
    377,
    400,
    378,
    379,
    365,
    397,
    288,
    361,
    323,
    454,
]

ZONE_POLYGON_INDICES: dict[str, list[int] | list[list[int]]] = {
    # Canonical masks are expressed as MediaPipe landmark indices, then mapped to
    # the user's actual face. Keep these shapes intentionally soft and broad: the
    # visual protocol needs beauty-map regions, not medical annotation precision.
    "forehead": [103, 67, 109, 10, 338, 297, 332, 296, 336, 9, 107, 66],
    "brow": [55, 65, 52, 8, 282, 295, 285, 417, 168, 193],
    "eye_area": [
        [33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7],
        [362, 398, 384, 385, 386, 387, 388, 466, 263, 249, 390, 373, 374, 380, 381, 382],
    ],
    "cheeks": [
        [50, 101, 118, 205, 187, 207, 216, 213, 192, 147, 123, 116, 111],
        [280, 330, 347, 425, 411, 427, 436, 433, 416, 376, 352, 345, 340],
    ],
    "nasolabial": [
        [98, 97, 2, 0, 37, 39, 40, 185, 61, 146, 206, 205],
        [327, 326, 2, 0, 267, 269, 270, 409, 291, 375, 426, 425],
    ],
    "mouth_area": [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185],
    "face_oval": LOWER_FACE_CONTOUR,
}


def canonical_zone_id(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    for pattern, zone_id in ZONE_ALIASES:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return zone_id
    return "overall"


def _clamp(value: float, low: float = 2.0, high: float = 98.0) -> float:
    return max(low, min(high, value))


def _parse_object_position(value: str | None) -> tuple[float, float]:
    text = value or "50% 42%"
    matches = re.findall(r"(-?\d+(?:\.\d+)?)%", text)
    if len(matches) >= 2:
        return float(matches[0]) / 100, float(matches[1]) / 100
    if len(matches) == 1:
        return float(matches[0]) / 100, 0.5
    return 0.5, 0.42


def _cover_transform(
    *,
    image_width: int,
    image_height: int,
    object_position: str | None,
    container_width: float = 1.0,
    container_height: float = 1.05,
):
    pos_x, pos_y = _parse_object_position(object_position)
    image_ratio = image_width / max(1, image_height)
    image_w = image_ratio
    image_h = 1.0
    scale = max(container_width / image_w, container_height / image_h)
    rendered_w = image_w * scale
    rendered_h = image_h * scale
    offset_x = max(0.0, rendered_w - container_width) * pos_x
    offset_y = max(0.0, rendered_h - container_height) * pos_y

    def transform(x: float, y: float) -> tuple[float, float]:
        return (
            _clamp(((x * rendered_w - offset_x) / container_width) * 100),
            _clamp(((y * rendered_h - offset_y) / container_height) * 100),
        )

    return transform


def _bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _ellipse_from_points(points: list[tuple[float, float]], *, pad_x: float = 4.0, pad_y: float = 3.0) -> dict[str, float | str]:
    left, top, right, bottom = _bbox(points)
    width = max(10.0, right - left + pad_x * 2)
    height = max(8.0, bottom - top + pad_y * 2)
    return {
        "type": "ellipse",
        "x": round(_clamp((left + right) / 2), 2),
        "y": round(_clamp((top + bottom) / 2), 2),
        "width": round(min(82.0, width), 2),
        "height": round(min(58.0, height), 2),
    }


def _ellipse_shape(
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    rotation: float = 0.0,
) -> dict[str, float | str]:
    return {
        "type": "ellipse",
        "x": round(_clamp(x), 2),
        "y": round(_clamp(y), 2),
        "width": round(max(4.0, min(82.0, width)), 2),
        "height": round(max(4.0, min(58.0, height)), 2),
        "rotation": round(rotation, 2),
    }


def _anchor(points: list[tuple[float, float]]) -> dict[str, float]:
    return {"x": round(_clamp(mean(point[0] for point in points)), 2), "y": round(_clamp(mean(point[1] for point in points)), 2)}


def _default_result(reason: str) -> dict[str, Any]:
    return {
        "detected": False,
        "reason": reason,
        "quality": _quality(False, reason),
        "zones": DEFAULT_ZONE_GEOMETRY,
        "contours": {},
    }


def _quality(ok: bool, reason: str = "ok", **extra: Any) -> dict[str, Any]:
    messages = {
        "ok": "Фото подходит для построения карты зон.",
        "missing_photo_path": "Фото не найдено. Пришлите фото лица заново.",
        "photo_not_found": "Фото не найдено. Пришлите фото лица заново.",
        "image_read_failed": "Фото не удалось прочитать. Пришлите другое фото лица.",
        "mediapipe_unavailable": "Не удалось проверить лицо на фото. Попробуйте другое фото.",
        "face_not_detected": "Я не вижу лицо достаточно четко. Пришлите фото анфас при хорошем свете.",
        "multiple_faces": "На фото должно быть одно лицо. Пришлите фото только одного человека.",
        "face_too_small": "Лицо на фото слишком далеко. Пришлите более крупное фото лица анфас.",
        "face_too_close_or_cropped": "Лицо слишком близко к краям или обрезано. Пришлите фото, где лицо видно полностью.",
        "face_cropped": "Часть лица обрезана. Пришлите фото, где полностью видны лоб, подбородок и овал лица.",
        "poor_light": "На фото недостаточно света или контраста. Пришлите фото при ровном дневном освещении.",
        "overexposed": "Фото слишком пересвечено. Пришлите снимок с более ровным светом.",
        "head_pose_too_angled": "Голова слишком наклонена или повернута. Пришлите фото анфас, без сильного наклона.",
    }
    return {"ok": ok, "reason": reason, "message": messages.get(reason, messages["face_not_detected"]), **extra}


def _landmark_points(
    landmarks: Any,
    indices: list[int],
    transform,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for index in indices:
        lm = landmarks[index]
        points.append(transform(lm.x, lm.y))
    return points


def _serialized_points(points: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [{"x": round(_clamp(x), 2), "y": round(_clamp(y), 2)} for x, y in points]


def _polygon_shape_from_indices(landmarks: Any, indices_or_groups: list[int] | list[list[int]], transform) -> dict[str, Any]:
    groups = indices_or_groups if indices_or_groups and isinstance(indices_or_groups[0], list) else [indices_or_groups]  # type: ignore[index]
    polygons: list[list[dict[str, float]]] = []
    all_points: list[tuple[float, float]] = []
    for group in groups:  # type: ignore[assignment]
        points = _landmark_points(landmarks, group, transform)
        if len(points) >= 3:
            polygons.append(_serialized_points(points))
            all_points.extend(points)
    if not all_points:
        return {"type": "ellipse", "x": 50, "y": 50, "width": 32, "height": 16}
    return {"type": "polygons", "polygons": polygons, **_ellipse_from_points(all_points, pad_x=1.5, pad_y=1.5)}


def _normalize_pose_angle(value: float) -> float:
    """Fold OpenCV Euler angle variants into a human-readable near-frontal range."""
    while value > 180:
        value -= 360
    while value < -180:
        value += 360
    if value > 90:
        value = 180 - value
    elif value < -90:
        value = -180 - value
    return value


def _estimate_pose_degrees(landmarks: Any, image_width: int, image_height: int, cv2, np) -> dict[str, float] | None:
    try:
        image_points = np.array(
            [
                (landmarks[1].x * image_width, landmarks[1].y * image_height),
                (landmarks[152].x * image_width, landmarks[152].y * image_height),
                (landmarks[33].x * image_width, landmarks[33].y * image_height),
                (landmarks[263].x * image_width, landmarks[263].y * image_height),
                (landmarks[61].x * image_width, landmarks[61].y * image_height),
                (landmarks[291].x * image_width, landmarks[291].y * image_height),
            ],
            dtype="double",
        )
        model_points = np.array(
            [
                (0.0, 0.0, 0.0),
                (0.0, -63.0, -12.0),
                (-43.0, 32.0, -26.0),
                (43.0, 32.0, -26.0),
                (-28.0, -28.0, -24.0),
                (28.0, -28.0, -24.0),
            ],
            dtype="double",
        )
        focal_length = float(image_width)
        center = (image_width / 2, image_height / 2)
        camera_matrix = np.array(
            [[focal_length, 0, center[0]], [0, focal_length, center[1]], [0, 0, 1]],
            dtype="double",
        )
        success, rotation_vector, _translation_vector = cv2.solvePnP(
            model_points,
            image_points,
            camera_matrix,
            np.zeros((4, 1)),
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not success:
            return None
        rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
        angles, *_ = cv2.RQDecomp3x3(rotation_matrix)
        pitch, yaw, roll = [_normalize_pose_angle(float(v)) for v in angles]
        return {"pitch": round(pitch, 2), "yaw": round(yaw, 2), "roll": round(roll, 2)}
    except Exception:
        return None


def _brightness_quality(image, cv2, np) -> dict[str, float | str] | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mean_value = float(np.mean(gray))
    contrast = float(np.std(gray))
    if mean_value < 45 or contrast < 18:
        return {"reason": "poor_light", "brightness": round(mean_value, 2), "contrast": round(contrast, 2)}
    if mean_value > 225:
        return {"reason": "overexposed", "brightness": round(mean_value, 2), "contrast": round(contrast, 2)}
    return {"reason": "ok", "brightness": round(mean_value, 2), "contrast": round(contrast, 2)}


def _face_box_quality(landmarks: Any) -> dict[str, Any]:
    xs = [float(landmarks[index].x) for index in FACE_OVAL_CONTOUR]
    ys = [float(landmarks[index].y) for index in FACE_OVAL_CONTOUR]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    face_width = right - left
    face_height = bottom - top
    face_box = {
        "left": round(left, 4),
        "top": round(top, 4),
        "right": round(right, 4),
        "bottom": round(bottom, 4),
        "width": round(face_width, 4),
        "height": round(face_height, 4),
    }
    if face_width < 0.28 or face_height < 0.34:
        return {"ok": False, "reason": "face_too_small", "face_box": face_box}
    if face_width > 0.86 or face_height > 0.92:
        return {"ok": False, "reason": "face_too_close_or_cropped", "face_box": face_box}
    if left < 0.025 or right > 0.975 or top < 0.015 or bottom > 0.985:
        return {"ok": False, "reason": "face_cropped", "face_box": face_box}
    return {"ok": True, "reason": "ok", "face_box": face_box}


def _detect_with_face_landmarker(mp, rgb, model_path: str | None) -> tuple[list[Any], str, list[Any]]:
    if not model_path or not Path(model_path).exists():
        return [], "face_mesh", []
    try:
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            output_facial_transformation_matrixes=True,
            num_faces=2,
        )
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        with vision.FaceLandmarker.create_from_options(options) as landmarker:
            result = landmarker.detect(mp_image)
        return list(result.face_landmarks or []), "face_landmarker", list(result.facial_transformation_matrixes or [])
    except Exception:
        logger.warning("MediaPipe FaceLandmarker failed; falling back to FaceMesh", exc_info=True)
        return [], "face_mesh", []


def _detect_landmarks(mp, rgb, model_path: str | None) -> tuple[list[Any], str, list[Any]]:
    landmark_sets, backend, matrices = _detect_with_face_landmarker(mp, rgb, model_path)
    if landmark_sets:
        return landmark_sets, backend, matrices
    face_mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=2,
        refine_landmarks=True,
        min_detection_confidence=0.5,
    )
    try:
        result = face_mesh.process(rgb)
    finally:
        face_mesh.close()
    return list(result.multi_face_landmarks or []), "face_mesh", []


def validate_face_photo(photo_path: str | Path | None) -> dict[str, Any]:
    """Validate whether a photo is suitable for detailed landmark-based zone map."""
    geometry = detect_face_zone_geometry(photo_path)
    return geometry.get("quality") or _quality(False, geometry.get("reason") or "face_not_detected")


def detect_face_zone_geometry(photo_path: str | Path | None, *, object_position: str = "50% 42%") -> dict[str, Any]:
    """Return zone anchors/shapes in template-percent coordinates using MediaPipe landmarks.

    The returned coordinates match the template's `object-fit: cover` photo frame, so
    markers stay aligned with the visible crop instead of the raw original image.
    """

    if not photo_path:
        return _default_result("missing_photo_path")
    path = Path(photo_path)
    if not path.exists():
        return _default_result("photo_not_found")

    try:
        import cv2
        import mediapipe as mp
        import numpy as np
    except Exception as exc:  # pragma: no cover - exercised in deployments without mediapipe.
        logger.warning("MediaPipe is unavailable for face zone map: %s", exc)
        return _default_result("mediapipe_unavailable")

    image = cv2.imread(str(path))
    if image is None:
        return _default_result("image_read_failed")

    height, width = image.shape[:2]
    brightness = _brightness_quality(image, cv2, np)
    transform = _cover_transform(image_width=width, image_height=height, object_position=object_position)
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    model_path = os.getenv("MEDIAPIPE_FACE_LANDMARKER_MODEL_PATH")
    landmark_sets, backend, matrices = _detect_landmarks(mp, rgb, model_path)

    if not landmark_sets:
        return _default_result("face_not_detected")
    if len(landmark_sets) > 1:
        result = _default_result("multiple_faces")
        result["quality"] = _quality(False, "multiple_faces", backend=backend, face_count=len(landmark_sets))
        return result

    first_landmark_set = landmark_sets[0]
    landmarks = first_landmark_set.landmark if hasattr(first_landmark_set, "landmark") else first_landmark_set
    face_box = _face_box_quality(landmarks)
    pose = _estimate_pose_degrees(landmarks, width, height, cv2, np)
    quality_extra: dict[str, Any] = {
        "backend": backend,
        "face_count": len(landmark_sets),
        "has_transformation_matrix": bool(matrices),
        "brightness": (brightness or {}).get("brightness"),
        "contrast": (brightness or {}).get("contrast"),
        "pose": pose,
        "face_box": face_box.get("face_box"),
    }
    quality_reason = "ok"
    if brightness and brightness.get("reason") != "ok":
        quality_reason = str(brightness["reason"])
    elif not face_box.get("ok"):
        quality_reason = str(face_box.get("reason") or "face_cropped")
    elif pose and (
        abs(float(pose.get("yaw", 0))) > 18
        or abs(float(pose.get("pitch", 0))) > 18
        or abs(float(pose.get("roll", 0))) > 14
    ):
        quality_reason = "head_pose_too_angled"
    quality_ok = quality_reason == "ok"

    def point(index: int) -> tuple[float, float]:
        lm = landmarks[index]
        return transform(lm.x, lm.y)

    def contour(indices: list[int]) -> list[dict[str, float]]:
        points = []
        for index in indices:
            x, y = point(index)
            points.append({"x": round(x, 2), "y": round(y, 2)})
        return points

    zones: dict[str, dict[str, Any]] = {}
    for zone_id, indices in LANDMARK_GROUPS.items():
        try:
            points = [point(index) for index in indices]
        except IndexError:
            zones[zone_id] = DEFAULT_ZONE_GEOMETRY[zone_id]
            continue
        try:
            shape = _polygon_shape_from_indices(landmarks, ZONE_POLYGON_INDICES.get(zone_id) or indices, transform)
        except Exception:
            shape = _ellipse_from_points(points)
        anchor = _anchor(points)
        zones[zone_id] = {"anchor": anchor, "shape": shape}

    left_eye_points = [point(index) for index in [33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7]]
    right_eye_points = [point(index) for index in [362, 398, 384, 385, 386, 387, 388, 466, 263, 249, 390, 373, 374, 380, 381, 382]]
    eye_points = [*left_eye_points, *right_eye_points]
    left, top, right, bottom = _bbox(eye_points)
    face_points = [point(index) for index in [234, 454, 10, 152]]
    face_left, face_top, face_right, face_bottom = _bbox(face_points)
    face_width = max(28.0, face_right - face_left)
    face_height = max(34.0, face_bottom - face_top)
    chin = point(152)
    mouth = _anchor([point(index) for index in [13, 14, 17, 0]])
    brow_mid = point(9)

    def under_eye_shape(points: list[tuple[float, float]], rotation: float) -> dict[str, float | str]:
        eye_left, _eye_top, eye_right, eye_bottom = _bbox(points)
        eye_width = max(8.0, eye_right - eye_left)
        eye_height = max(5.0, bottom - top)
        return _ellipse_shape(
            x=(eye_left + eye_right) / 2,
            y=eye_bottom + eye_height * 0.52,
            width=eye_width * 1.22,
            height=eye_height * 0.86,
            rotation=rotation,
        )

    zones["forehead"] = {
        "anchor": {"x": round(_clamp((face_left + face_right) / 2), 2), "y": round(_clamp(face_top + face_height * 0.16), 2)},
        "shape": _ellipse_shape(
            x=(face_left + face_right) / 2,
            y=face_top + max(5.0, (brow_mid[1] - face_top) * 0.42),
            width=max(30.0, face_width * 0.68),
            height=max(8.0, face_height * 0.10),
        ),
    }
    zones["eye_area"] = {
        "anchor": {"x": round(_clamp(left + (right - left) * 0.22), 2), "y": round(_clamp(bottom + max(4.0, (bottom - top) * 0.42)), 2)},
        "shape": {
            "type": "ellipse",
            "x": round(_clamp((left + right) / 2), 2),
            "y": round(_clamp(bottom + max(4.0, (bottom - top) * 0.45)), 2),
            "width": round(min(62.0, max(34.0, right - left + 6)), 2),
            "height": round(max(8.0, (bottom - top) * 0.82), 2),
            "shapes": [under_eye_shape(left_eye_points, -4), under_eye_shape(right_eye_points, 4)],
        },
    }
    cheek_y = bottom + (mouth["y"] - bottom) * 0.42
    cheek_width = max(18.0, face_width * 0.29)
    cheek_height = max(15.0, face_height * 0.25)
    zones["cheeks"] = {
        "anchor": {"x": round(_clamp(face_right - face_width * 0.28), 2), "y": round(_clamp(cheek_y), 2)},
        "shape": {
            "type": "ellipse",
            "x": round(_clamp((face_left + face_right) / 2), 2),
            "y": round(_clamp(cheek_y), 2),
            "width": round(min(70.0, max(34.0, face_width * 0.72)), 2),
            "height": round(cheek_height, 2),
            "shapes": [
                _ellipse_shape(
                    x=face_left + face_width * 0.27,
                    y=cheek_y,
                    width=cheek_width,
                    height=cheek_height,
                    rotation=-10,
                ),
                _ellipse_shape(
                    x=face_right - face_width * 0.27,
                    y=cheek_y,
                    width=cheek_width,
                    height=cheek_height,
                    rotation=10,
                ),
            ],
        },
    }
    zones["nasolabial"] = {
        **zones.get("nasolabial", DEFAULT_ZONE_GEOMETRY["nasolabial"]),
        "anchor": {
            "x": round(_clamp(face_right - face_width * 0.38), 2),
            "y": round(_clamp(mouth["y"] - (mouth["y"] - bottom) * 0.22), 2),
        },
    }
    zones["mouth_area"] = {
        "anchor": {"x": round(_clamp(chin[0]), 2), "y": round(_clamp(mouth["y"] + (chin[1] - mouth["y"]) * 0.68), 2)},
        "shape": _ellipse_shape(
            x=chin[0],
            y=mouth["y"] + (chin[1] - mouth["y"]) * 0.74,
            width=max(18.0, face_width * 0.36),
            height=max(7.0, (chin[1] - mouth["y"]) * 0.42),
        ),
    }
    zones["face_oval"] = {
        "anchor": {"x": round(_clamp(face_right - face_width * 0.18), 2), "y": round(_clamp((mouth["y"] + chin[1]) / 2), 2)},
        "shape": _polygon_shape_from_indices(landmarks, LOWER_FACE_CONTOUR, transform),
    }
    zones["neck"] = {
        "anchor": {"x": round(_clamp(chin[0]), 2), "y": round(_clamp(chin[1] + 12), 2)},
        "shape": {"type": "ellipse", "x": round(_clamp(chin[0]), 2), "y": round(_clamp(chin[1] + 12), 2), "width": 38, "height": 14},
    }

    return {
        "detected": quality_ok,
        "reason": quality_reason,
        "quality": _quality(quality_ok, quality_reason, **quality_extra),
        "image_width": width,
        "image_height": height,
        "contours": {
            "face_oval": contour(FACE_OVAL_CONTOUR),
            "lower_face": contour(LOWER_FACE_CONTOUR),
        },
        "zones": {**DEFAULT_ZONE_GEOMETRY, **zones},
    }
