from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.core.config import settings
from app.reports.overlay_zones import STATUS_COLORS, zone_position

LEGACY_RENDERER_ERROR = "LEGACY_FACE_PROTOCOL_RENDERER_DISABLED_USE_FINAL_V1"


def _fail_legacy_renderer() -> None:
    raise RuntimeError(LEGACY_RENDERER_ERROR)


SIZE = (1080, 1350)
BG = (250, 246, 240)
PAPER = (255, 253, 249)
PEARL = (236, 223, 213)
INK = (48, 42, 39)
CLAY = (116, 98, 90)
MUTED = (147, 126, 116)
ROSE = (183, 111, 124)
SAGE = (113, 154, 126)
GOLD = (214, 171, 77)
RED = (196, 94, 91)
DARK = (54, 46, 42)
BLUSH = (246, 235, 231)
CREAM = (255, 250, 245)
LINE = (222, 205, 196)


ZONE_DEFAULTS = [
    (1, "Лоб"),
    (2, "Межбровная зона"),
    (3, "Область глаз / веки"),
    (4, "Носогубная зона"),
    (5, "Скулы"),
    (6, "Овал лица"),
    (7, "Подбородок"),
    (8, "Шея"),
    (9, "Зона отечности"),
]

SHORT_ZONE_NAMES = {
    1: "лоб",
    2: "межбровка",
    3: "глаза / веки",
    4: "носогубная зона",
    5: "скулы",
    6: "овал",
    7: "подбородок",
    8: "шея",
    9: "отечность",
}

FACE_LABELS = {
    1: "Лоб",
    2: "Межбровка",
    3: "Глаза",
    4: "Носогубка",
    5: "Скулы",
    6: "Овал",
    7: "Подбородок",
    8: "Шея",
    9: "Отёчность",
}

FACE_LABEL_OFFSETS = {
    2: (0, -18),
    3: (0, 20),
    4: (0, 6),
    7: (0, 8),
}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _serif_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return _font(size, bold=bold)


def _status_color(zone: dict[str, Any]) -> tuple[int, int, int]:
    color = zone.get("color")
    status = zone.get("status")
    if color == "green" or status == "good":
        return SAGE
    if color == "red" or status == "priority":
        return RED
    return GOLD


def _status_label(zone: dict[str, Any]) -> str:
    if zone.get("status") == "good" or zone.get("color") == "green":
        return "Все хорошо"
    if zone.get("status") == "priority" or zone.get("color") == "red":
        return "Приоритет"
    return "Зона внимания"


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int, max_lines: int | None = None) -> list[str]:
    words = str(text or "").replace("\n", " ").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
        if max_lines and len(lines) >= max_lines:
            break
    if current and (not max_lines or len(lines) < max_lines):
        lines.append(current)
    if max_lines and len(lines) == max_lines and " ".join(lines) != " ".join(words):
        line = lines[-1]
        while draw.textlength(line + "...", font=font) > width and len(line) > 3:
            line = line[:-1].rstrip()
        lines[-1] = line + "..."
    return lines or [""]


def _text(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    width: int,
    font: ImageFont.ImageFont,
    fill=INK,
    gap: int = 8,
    max_lines: int | None = None,
) -> int:
    x, y = xy
    line_height = getattr(font, "size", 18) + gap
    for line in _wrap(draw, text, font, width, max_lines):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _brief_text(text: str, limit: int = 120) -> str:
    cleaned = " ".join(str(text or "").replace("\n", " ").split())
    if not cleaned:
        return ""
    for separator in (".", "!", "?"):
        index = cleaned.find(separator)
        if 25 <= index <= limit:
            return cleaned[: index + 1]
    if len(cleaned) <= limit:
        return cleaned
    shortened = cleaned[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return shortened + "."


def _soft_bullet(text: str) -> str:
    lowered = str(text or "").lower()
    if "лимф" in lowered or "отеч" in lowered or "отёч" in lowered:
        return "Лимфоток требует мягкой активации."
    if "шея" in lowered or "ключ" in lowered or "осан" in lowered:
        return "Шея и осанка влияют на отток."
    if "гипертонус" in lowered or "мим" in lowered:
        return "Лёгкий гипертонус усиливает усталость."
    if "пастоз" in lowered or "сним" in lowered or "сниз" in lowered:
        return "Снизит утреннюю пастозность."
    if "тонус" in lowered or "век" in lowered or "взгляд" in lowered:
        return "Улучшит тонус и свежесть взгляда."
    if "расслаб" in lowered or "нижн" in lowered:
        return "Расслабит нижнюю треть лица."
    return _brief_text(text, 42)


def _center_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font: ImageFont.ImageFont, fill=INK) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x0, y0, x1, y1 = box
    draw.text((x0 + (x1 - x0 - tw) / 2, y0 + (y1 - y0 - th) / 2 - 1), text, font=font, fill=fill)


def _canvas_from_background(background_path: str | None = None) -> Image.Image:
    if background_path and Path(background_path).exists():
        image = Image.open(background_path).convert("RGBA")
        if image.size != SIZE:
            image = ImageOps.fit(image, SIZE, method=Image.Resampling.LANCZOS)
        veil = Image.new("RGBA", SIZE, (255, 252, 247, 78))
        image.alpha_composite(veil)
        return image
    return Image.new("RGBA", SIZE, BG + (255,))


def _reference_header(draw: ImageDraw.ImageDraw, user_name: str, y: int = 30) -> None:
    brand_font = _serif_font(50)
    title_font = _serif_font(46)
    meta_font = _font(25)
    badge_font = _font(20, True)
    _center_text(draw, (80, y, 1000, y + 55), "Bella Vladi", brand_font, fill=DARK)
    _center_text(draw, (80, y + 58, 1000, y + 112), "Face Protocol", title_font, fill=DARK)
    _center_text(draw, (80, y + 118, 1000, y + 150), f"{user_name or 'Гость'} · {datetime.now().strftime('%d.%m.%Y')}", meta_font, fill=INK)
    badge = (365, y + 160, 715, y + 207)
    draw.rounded_rectangle(badge, radius=23, fill=(255, 250, 244, 238), outline=(184, 157, 124, 220), width=2)
    _center_text(draw, badge, "визуальный AI-разбор", badge_font, fill=DARK)


def _reference_card(canvas: Image.Image, box: tuple[int, int, int, int]) -> None:
    shadow = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((box[0], box[1] + 12, box[2], box[3] + 12), radius=28, fill=(74, 46, 34, 36))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    canvas.alpha_composite(shadow)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius=28, fill=(255, 253, 248, 242), outline=(184, 157, 124, 210), width=2)


def _rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill=PAPER, outline=PEARL, radius: int = 30, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _shadowed_rounded(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    fill=PAPER,
    outline=PEARL,
    radius: int = 34,
    shadow_alpha: int = 28,
) -> None:
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shifted = (box[0] + 0, box[1] + 10, box[2], box[3] + 10)
    shadow_draw.rounded_rectangle(shifted, radius=radius, fill=(80, 54, 42, shadow_alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.alpha_composite(shadow)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)


def _paste_rounded(canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int], radius: int = 34) -> None:
    x0, y0, x1, y1 = box
    size = (x1 - x0, y1 - y0)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    canvas.paste(image, (x0, y0), mask)


def _load_photo(path: str, size: tuple[int, int]) -> Image.Image:
    photo = Image.open(path).convert("RGB")
    photo = ImageOps.exif_transpose(photo)
    return ImageOps.fit(photo, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.42))


def _header(draw: ImageDraw.ImageDraw, user_name: str, badge: str = "визуальный AI-разбор") -> None:
    brand = _font(24, True)
    title = _font(62, True)
    meta = _font(25)
    badge_font = _font(18, True)
    draw.text((58, 40), "Bella Vladi", font=brand, fill=ROSE)
    draw.text((58, 76), "Face Protocol", font=title, fill=INK)
    draw.text((60, 150), f"{user_name or 'Гость'} · {datetime.now().strftime('%d.%m.%Y')}", font=meta, fill=CLAY)
    box = (740, 58, 1020, 112)
    _rounded(draw, box, fill=(244, 232, 226), outline=(229, 211, 204), radius=27)
    _center_text(draw, box, badge, badge_font, fill=CLAY)


def _normalised_zones(analysis_json: dict[str, Any]) -> list[dict[str, Any]]:
    raw_zones = list(analysis_json.get("zones") or [])
    by_number = {
        int(zone.get("number")): zone
        for zone in raw_zones
        if str(zone.get("number", "")).isdigit()
    }
    zones: list[dict[str, Any]] = []
    for index, default_name in ZONE_DEFAULTS:
        source = by_number.get(index) or (raw_zones[index - 1] if len(raw_zones) >= index else {})
        zone = dict(source)
        zone["number"] = index
        zone["name"] = zone.get("name") or default_name
        zone["status"] = zone.get("status") or "attention"
        zone["color"] = zone.get("color") or ("green" if zone["status"] == "good" else "red" if zone["status"] == "priority" else "yellow")
        zones.append(zone)
    return zones


def _zone_shape(zone_name: str, photo_box: tuple[int, int, int, int]) -> tuple[str, tuple[int, int, int, int]]:
    x0, y0, x1, y1 = photo_box
    w, h = x1 - x0, y1 - y0
    name = zone_name.lower()
    cx, cy = zone_position(zone_name, photo_box)

    if "лоб" in name:
        return "ellipse", (int(x0 + w * 0.31), int(y0 + h * 0.08), int(x0 + w * 0.69), int(y0 + h * 0.25))
    if "межбров" in name:
        return "ellipse", (int(cx - w * 0.075), int(cy - h * 0.045), int(cx + w * 0.075), int(cy + h * 0.055))
    if "глаз" in name or "веки" in name:
        return "ellipse", (int(x0 + w * 0.18), int(y0 + h * 0.24), int(x0 + w * 0.82), int(y0 + h * 0.40))
    if "носогуб" in name:
        return "ellipse", (int(x0 + w * 0.31), int(y0 + h * 0.43), int(x0 + w * 0.69), int(y0 + h * 0.66))
    if "скул" in name:
        return "ellipse", (int(x0 + w * 0.21), int(y0 + h * 0.36), int(x0 + w * 0.79), int(y0 + h * 0.55))
    if "овал" in name:
        return "ellipse", (int(x0 + w * 0.20), int(y0 + h * 0.56), int(x0 + w * 0.80), int(y0 + h * 0.84))
    if "подбород" in name:
        return "ellipse", (int(x0 + w * 0.37), int(y0 + h * 0.72), int(x0 + w * 0.63), int(y0 + h * 0.86))
    if "шея" in name:
        return "ellipse", (int(x0 + w * 0.32), int(y0 + h * 0.84), int(x0 + w * 0.68), int(y0 + h * 1.02))
    if "отеч" in name:
        return "ellipse", (int(x0 + w * 0.17), int(y0 + h * 0.30), int(x0 + w * 0.83), int(y0 + h * 0.48))
    return "ellipse", (cx - 70, cy - 42, cx + 70, cy + 42)


def _badge_position(zone_name: str, photo_box: tuple[int, int, int, int]) -> tuple[int, int]:
    x0, y0, x1, y1 = photo_box
    w, h = x1 - x0, y1 - y0
    name = zone_name.lower()
    positions = [
        (("лоб",), (0.72, 0.16)),
        (("межбров",), (0.61, 0.29)),
        (("глаз", "веки"), (0.84, 0.34)),
        (("носогуб",), (0.72, 0.56)),
        (("скул",), (0.19, 0.45)),
        (("овал",), (0.83, 0.72)),
        (("подбород",), (0.63, 0.82)),
        (("шея",), (0.70, 0.92)),
        (("отеч",), (0.16, 0.34)),
    ]
    for keys, (rx, ry) in positions:
        if any(key in name for key in keys):
            return int(x0 + w * rx), int(y0 + h * ry)
    return zone_position(zone_name, photo_box)


def _label_box(draw: ImageDraw.ImageDraw, center: tuple[int, int], text: str, color: tuple[int, int, int], side: str) -> None:
    font = _font(21, True)
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0] + 34
    height = 38
    cx, cy = center
    if side == "left":
        box = (cx - width - 38, cy - height // 2, cx - 38, cy + height // 2)
    else:
        box = (cx + 38, cy - height // 2, cx + width + 38, cy + height // 2)
    dx = 0
    if box[0] < 72:
        dx = 72 - box[0]
    elif box[2] > 1008:
        dx = 1008 - box[2]
    if dx:
        box = (box[0] + dx, box[1], box[2] + dx, box[3])
    draw.rounded_rectangle(box, radius=19, fill=(255, 252, 247, 238), outline=color + (225,), width=2)
    draw.text((box[0] + 17, box[1] + 6), text, font=font, fill=DARK)


def _draw_zone_overlay(
    base: Image.Image,
    photo_box: tuple[int, int, int, int],
    zones: list[dict[str, Any]],
    show_labels: bool = False,
) -> None:
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    glow_draw = ImageDraw.Draw(glow)
    badge_font = _font(26, True)

    for zone in zones:
        color = _status_color(zone)
        alpha = 42 if zone.get("status") == "priority" or zone.get("color") == "red" else 34
        _, box = _zone_shape(zone.get("name", ""), photo_box)
        glow_draw.ellipse(box, fill=color + (55,), outline=color + (120,), width=7)

    glow = glow.filter(ImageFilter.GaussianBlur(24))
    base.alpha_composite(glow)

    for zone in zones:
        color = _status_color(zone)
        _, box = _zone_shape(zone.get("name", ""), photo_box)
        overlay_draw.ellipse(box, fill=color + (38,), outline=color + (230,), width=4)

    base.alpha_composite(overlay)
    draw = ImageDraw.Draw(base)
    for zone in zones:
        color = _status_color(zone)
        bx, by = _badge_position(zone.get("name", ""), photo_box)
        _, shape_box = _zone_shape(zone.get("name", ""), photo_box)
        target = ((shape_box[0] + shape_box[2]) // 2, (shape_box[1] + shape_box[3]) // 2)
        draw.line((target[0], target[1], bx, by), fill=color + (155,), width=2)
        r = 28
        draw.ellipse((bx - r - 5, by - r - 5, bx + r + 5, by + r + 5), fill=(255, 255, 255, 238))
        draw.ellipse((bx - r, by - r, bx + r, by + r), fill=color + (255,))
        _center_text(draw, (bx - r, by - r, bx + r, by + r), str(zone.get("number", "")), badge_font, fill=(255, 255, 255))
        if show_labels:
            number = int(zone.get("number") or 0)
            side = "left" if bx > (photo_box[0] + photo_box[2]) / 2 else "right"
            if number in {1, 2, 4, 7, 8}:
                side = "right"
            if number in {5, 6}:
                side = "left"
            if number == 3:
                side = "right"
            label = FACE_LABELS.get(number, str(zone.get("name", "")))
            dx, dy = FACE_LABEL_OFFSETS.get(number, (0, 0))
            _label_box(draw, (bx + dx, by + dy), label, color, side)


def _legend(draw: ImageDraw.ImageDraw, y: int) -> None:
    font = _font(22, True)
    items = [("Все хорошо", SAGE), ("Зона внимания", GOLD), ("Приоритет", RED)]
    x = 120
    for label, color in items:
        draw.ellipse((x, y + 7, x + 24, y + 31), fill=color)
        draw.text((x + 36, y), label, font=font, fill=CLAY)
        x += 295


def _compact_legend(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    font = _font(18, True)
    items = [("Все хорошо", SAGE), ("Зона внимания", GOLD), ("Приоритет", RED)]
    for label, color in items:
        draw.ellipse((x, y + 5, x + 18, y + 23), fill=color)
        draw.text((x + 28, y), label, font=font, fill=CLAY)
        x += 205


def _draw_zone_index_panel(canvas: Image.Image, zones: list[dict[str, Any]], top: int = 956) -> None:
    draw = ImageDraw.Draw(canvas)
    panel = (54, top, 1026, 1276)
    _shadowed_rounded(canvas, panel, fill=(255, 253, 249, 246), outline=LINE + (255,), radius=36, shadow_alpha=22)
    draw = ImageDraw.Draw(canvas)

    title_font = _font(29, True)
    item_font = _font(21, True)
    focus_font = _font(20, True)
    draw.text((90, top + 28), "Карта зон", font=title_font, fill=INK)
    _compact_legend(draw, 330, top + 34)

    columns = [(90, top + 86, zones[:5]), (560, top + 86, zones[5:])]
    row_gap = 35
    for x, y, column_zones in columns:
        for zone in column_zones:
            color = _status_color(zone)
            r = 16
            draw.ellipse((x, y - 1, x + r * 2, y + r * 2 - 1), fill=color)
            _center_text(draw, (x, y - 1, x + r * 2, y + r * 2 - 1), str(zone.get("number")), _font(14, True), fill=(255, 255, 255))
            _text(draw, str(zone.get("name", "")), (x + 44, y - 2), 360, item_font, fill=CLAY, gap=0, max_lines=1)
            y += row_gap

    focus = " · ".join(
        f"{zone.get('number')} {SHORT_ZONE_NAMES.get(int(zone.get('number', 0)), str(zone.get('name', '')).lower())}"
        for zone in _priority_zones(zones, limit=3)
    )
    focus_box = (88, top + 260, 992, top + 302)
    draw.rounded_rectangle(focus_box, radius=21, fill=(246, 235, 231, 255), outline=(230, 210, 203, 255), width=1)
    _text(draw, f"Главный фокус: {focus}", (110, top + 268), 850, focus_font, fill=DARK, gap=0, max_lines=1)


def _reference_legend(draw: ImageDraw.ImageDraw, y: int) -> None:
    font = _font(27)
    items = [("Все хорошо", SAGE), ("Зона внимания", GOLD), ("Приоритет", RED)]
    x = 145
    for label, color in items:
        draw.ellipse((x, y, x + 40, y + 40), fill=color + (170,), outline=color, width=4)
        draw.text((x + 58, y + 3), label, font=font, fill=INK)
        x += 310


def _reference_focus(draw: ImageDraw.ImageDraw, zones: list[dict[str, Any]], y: int) -> None:
    title_font = _font(25, True)
    item_font = _font(24)
    draw.text((142, y), "Главный фокус", font=title_font, fill=INK)
    for index, zone in enumerate(_priority_zones(zones, limit=3), start=1):
        label = "зона приоритета" if zone.get("status") == "priority" else "зона внимания" if zone.get("status") == "attention" else "все хорошо"
        line = f"{index}. {zone.get('name')} — {label}"
        _text(draw, line, (142, y + 36 + (index - 1) * 32), 820, item_font, fill=INK, gap=0, max_lines=1)


def _compose_exact_slide_1(
    base_image_path: str | None,
    original_photo_path: str,
    output_path: str,
    user_name: str,
    analysis_json: dict[str, Any],
) -> str:
    _fail_legacy_renderer()
    image = _canvas_from_background(base_image_path)

    card = (56, 206, 1024, 1247)
    _reference_card(image, card)
    draw = ImageDraw.Draw(image)
    _reference_header(draw, user_name, y=24)

    zones = _normalised_zones(analysis_json)
    photo_box = (88, 230, 992, 997)
    photo = _load_photo(original_photo_path, (photo_box[2] - photo_box[0], photo_box[3] - photo_box[1])).convert("RGBA")
    photo_layer = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    _paste_rounded(photo_layer, photo.convert("RGB"), photo_box, radius=16)
    _draw_zone_overlay(photo_layer, photo_box, zones, show_labels=True)
    clip_mask = Image.new("L", SIZE, 0)
    ImageDraw.Draw(clip_mask).rounded_rectangle(photo_box, radius=16, fill=255)
    photo_layer.putalpha(ImageChops.multiply(photo_layer.getchannel("A"), clip_mask))
    image.alpha_composite(photo_layer)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(photo_box, radius=16, outline=(190, 160, 122, 210), width=2)

    _reference_legend(draw, 1034)
    _reference_focus(draw, zones, 1096)
    footer_font = _font(22)
    _center_text(
        draw,
        (60, 1274, 1020, 1302),
        "Протокол не является медицинским диагнозом и не обещает гарантированный результат.",
        footer_font,
        fill=INK,
    )
    _center_text(draw, (60, 1306, 1020, 1334), "Подробный отчет — по ссылке в боте", _font(22), fill=INK)
    image.convert("RGB").save(output_path, quality=96)
    return output_path


def _priority_zones(zones: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    priority = [zone for zone in zones if zone.get("status") == "priority" or zone.get("color") == "red"]
    attention = [zone for zone in zones if zone.get("status") == "attention" or zone.get("color") == "yellow"]
    good = [zone for zone in zones if zone.get("status") == "good" or zone.get("color") == "green"]
    return (priority + attention + good)[:limit]


def _list_lines(
    draw: ImageDraw.ImageDraw,
    items: Iterable[str],
    xy: tuple[int, int],
    width: int,
    font: ImageFont.ImageFont,
    max_items: int = 3,
    max_lines: int = 2,
) -> int:
    x, y = xy
    for item in list(items)[:max_items]:
        draw.ellipse((x, y + 12, x + 10, y + 22), fill=ROSE)
        y = _text(draw, str(item), (x + 24, y), width - 24, font, fill=CLAY, gap=5, max_lines=max_lines) + 8
    return y


def _slide_1(original_photo_path: str, output_path: str, user_name: str, analysis_json: dict[str, Any]) -> str:
    _fail_legacy_renderer()
    return _compose_exact_slide_1(None, original_photo_path, output_path, user_name, analysis_json)


def _metric_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], number: str, title: str, body: str, accent: tuple[int, int, int]) -> None:
    _rounded(draw, box, fill=PAPER, outline=PEARL, radius=34)
    x0, y0, x1, _ = box
    n_font = _font(22, True)
    h_font = _font(28, True)
    b_font = _font(25)
    draw.ellipse((x0 + 30, y0 + 30, x0 + 78, y0 + 78), fill=accent)
    _center_text(draw, (x0 + 30, y0 + 30, x0 + 78, y0 + 78), number, n_font, fill=(255, 255, 255))
    draw.text((x0 + 96, y0 + 30), title, font=h_font, fill=INK)
    _text(draw, body, (x0 + 34, y0 + 98), x1 - x0 - 68, b_font, fill=CLAY, gap=8, max_lines=2)


def _section_kicker(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], accent: tuple[int, int, int]) -> None:
    x, y = xy
    font = _font(17, True)
    draw.rounded_rectangle((x, y, x + 82, y + 34), radius=17, fill=accent)
    _center_text(draw, (x, y, x + 82, y + 34), text, font, fill=(255, 255, 255))


def _editorial_panel(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    number: str,
    title: str,
    body: str,
    accent: tuple[int, int, int],
    fill=CREAM,
    max_lines: int = 2,
) -> None:
    _shadowed_rounded(canvas, box, fill=fill + (255,), outline=LINE + (255,), radius=32, shadow_alpha=18)
    draw = ImageDraw.Draw(canvas)
    x0, y0, x1, _ = box
    draw.text((x0 + 28, y0 + 24), number, font=_font(42, True), fill=accent)
    draw.text((x0 + 112, y0 + 34), title, font=_font(29, True), fill=INK)
    draw.rounded_rectangle((x0 + 28, y0 + 92, x0 + 86, y0 + 99), radius=4, fill=accent)
    _text(draw, body, (x0 + 28, y0 + 116), x1 - x0 - 56, _font(24), fill=CLAY, gap=8, max_lines=max_lines)


def _chip(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, accent: tuple[int, int, int]) -> None:
    draw.rounded_rectangle(box, radius=22, fill=(255, 255, 255), outline=LINE, width=1)
    draw.ellipse((box[0] + 16, box[1] + 15, box[0] + 28, box[1] + 27), fill=accent)
    _text(draw, text, (box[0] + 42, box[1] + 9), box[2] - box[0] - 58, _font(20, True), fill=CLAY, gap=0, max_lines=1)


def _slide_2(output_path: str, user_name: str, analysis_json: dict[str, Any], background_path: str | None = None) -> str:
    _fail_legacy_renderer()
    canvas = _canvas_from_background(background_path)
    card = (56, 206, 1024, 1247)
    _reference_card(canvas, card)
    draw = ImageDraw.Draw(canvas)
    _reference_header(draw, user_name, y=24)
    _center_text(draw, (90, 252, 990, 314), "Краткое резюме", _serif_font(56), fill=DARK)
    _center_text(draw, (110, 320, 970, 350), "Главные выводы протокола без перегруза", _font(24), fill=CLAY)

    skin_age = analysis_json.get("skin_visual_age") or {}
    skin_type = analysis_json.get("skin_type") or {}
    face_type = analysis_json.get("face_type_and_aging_type") or {}
    strengths = analysis_json.get("strengths") or []
    skin_age_body = _brief_text(f"{skin_age.get('estimated_range', '')}. {skin_age.get('explanation', '')}", 112)
    skin_type_body = _brief_text(str(skin_type.get("type", "")).split(",")[0], 54)
    face_type_body = _brief_text(f"{face_type.get('face_type', '')} · {face_type.get('aging_type', '')}", 54)

    _editorial_panel(canvas, (88, 374, 992, 560), "01", "Биологический возраст кожи", skin_age_body, ROSE, fill=PAPER)
    _editorial_panel(canvas, (88, 592, 520, 790), "02", "Тип кожи", skin_type_body, SAGE, fill=(252, 248, 243))
    _editorial_panel(canvas, (560, 592, 992, 790), "03", "Сильные стороны / старение", face_type_body, GOLD, fill=(255, 250, 245))

    _shadowed_rounded(canvas, (88, 828, 992, 1158), fill=(255, 253, 250, 242), outline=(184, 157, 124, 170), radius=26, shadow_alpha=12)
    draw = ImageDraw.Draw(canvas)
    draw.text((124, 866), "06", font=_font(40, True), fill=ROSE)
    draw.text((202, 876), "Ваши сильные стороны", font=_font(31, True), fill=INK)
    strength_texts = list(str(item) for item in strengths[:3]) or [
        "Естественная гармония лица",
        "Хороший потенциал овала",
        "Выразительный взгляд",
    ]
    y = 946
    for index, text in enumerate(strength_texts):
        accent = [ROSE, SAGE, GOLD][index % 3]
        draw.ellipse((132, y + 13, 148, y + 29), fill=accent)
        y = _text(draw, text, (168, y), 760, _font(24), fill=INK, gap=7, max_lines=2) + 12

    _center_text(draw, (60, 1274, 1020, 1302), "Протокол не является медицинским диагнозом.", _font(22), fill=INK)
    _center_text(draw, (60, 1306, 1020, 1334), "Подробный отчет — по ссылке в боте", _font(22), fill=INK)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, quality=96)
    return output_path


def _timeline_item(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], label: str, text: str, accent: tuple[int, int, int]) -> None:
    _rounded(draw, box, fill=PAPER, outline=PEARL, radius=28)
    x0, y0, x1, _ = box
    draw.rounded_rectangle((x0 + 26, y0 + 24, x0 + 176, y0 + 62), radius=19, fill=accent)
    _center_text(draw, (x0 + 26, y0 + 24, x0 + 176, y0 + 62), label, _font(17, True), fill=(255, 255, 255))
    _text(draw, text, (x0 + 28, y0 + 84), x1 - x0 - 56, _font(23), fill=CLAY, gap=7, max_lines=2)


def _slide_3(output_path: str, user_name: str, analysis_json: dict[str, Any], background_path: str | None = None) -> str:
    _fail_legacy_renderer()
    canvas = _canvas_from_background(background_path)
    card = (56, 206, 1024, 1247)
    _reference_card(canvas, card)
    draw = ImageDraw.Draw(canvas)
    _reference_header(draw, user_name, y=24)
    _center_text(draw, (90, 252, 990, 314), "План и прогноз", _serif_font(56), fill=DARK)
    _center_text(draw, (110, 320, 970, 350), "Мягкий ориентир при регулярной работе 3 месяца", _font(24), fill=CLAY)

    causes = analysis_json.get("causes") or []
    benefits = analysis_json.get("facefitness_benefits") or []
    forecast = analysis_json.get("time_forecast") or {}

    _shadowed_rounded(canvas, (88, 370, 520, 724), fill=(255, 253, 250, 238), outline=(184, 157, 124, 160), radius=24, shadow_alpha=10)
    _shadowed_rounded(canvas, (560, 370, 992, 724), fill=(255, 253, 250, 238), outline=(184, 157, 124, 160), radius=24, shadow_alpha=10)
    draw = ImageDraw.Draw(canvas)
    draw.text((124, 404), "05", font=_font(40, True), fill=ROSE)
    draw.text((124, 466), "Почему это происходит", font=_font(27, True), fill=INK)
    _list_lines(draw, [_soft_bullet(item) for item in causes], (126, 532), 340, _font(21), max_items=3)
    draw.text((596, 404), "07", font=_font(40, True), fill=SAGE)
    draw.text((596, 466), "Что даст фейсфитнес", font=_font(27, True), fill=INK)
    _list_lines(draw, [_soft_bullet(item) for item in benefits], (598, 532), 340, _font(21), max_items=3)

    _center_text(draw, (88, 780, 992, 826), "08. Прогноз по времени", _font(34, True), fill=INK)
    timeline_y = 850
    timeline = [
        ("2 недели", forecast.get("first_changes", "Больше свежести и меньше утренней отечности."), ROSE),
        ("1 месяц", forecast.get("visible_changes", "Заметнее тонус, взгляд и линия овала."), SAGE),
        ("3 месяца", forecast.get("stable_result", "Более устойчивый визуальный эффект."), GOLD),
    ]
    boxes = [(88, timeline_y, 992, timeline_y + 92), (88, timeline_y + 112, 992, timeline_y + 204), (88, timeline_y + 224, 992, timeline_y + 316)]
    for (label, text, accent), box in zip(timeline, boxes):
        _shadowed_rounded(canvas, box, fill=PAPER + (242,), outline=(184, 157, 124, 155), radius=24, shadow_alpha=8)
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle((box[0] + 24, box[1] + 25, box[0] + 174, box[1] + 65), radius=20, fill=accent)
        _center_text(draw, (box[0] + 24, box[1] + 25, box[0] + 174, box[1] + 65), label, _font(18, True), fill=(255, 255, 255))
        _text(draw, text, (box[0] + 208, box[1] + 20), 650, _font(22), fill=INK, gap=6, max_lines=2)

    _center_text(draw, (60, 1274, 1020, 1302), "Протокол не является медицинским диагнозом.", _font(20), fill=INK)
    _center_text(draw, (60, 1306, 1020, 1334), "Получить персональную программу Bella Vladi", _font(24, True), fill=ROSE)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, quality=96)
    return output_path


def generate_protocol_slides(
    original_photo_path: str,
    output_dir: str,
    user_name: str,
    analysis_json: dict[str, Any],
    single_image: bool = False,
) -> list[str]:
    _fail_legacy_renderer()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if settings.protocol_image_provider.lower() != "gemini":
        raise RuntimeError("Bella Vladi Face Protocol requires PROTOCOL_IMAGE_PROVIDER=gemini")

    slide_1 = output / "slide_1_face_map.jpg"
    slide_1_base = output / "slide_1_gemini_base.jpg"
    paths = [
        _compose_exact_slide_1(
            generate_protocol_background_with_gemini(str(slide_1_base), "face_map"),
            original_photo_path,
            str(slide_1),
            user_name,
            analysis_json,
        )
    ]
    if not single_image:
        slide_2_bg = generate_protocol_background_with_gemini(str(output / "slide_2_gemini_base.jpg"), "summary")
        slide_3_bg = generate_protocol_background_with_gemini(str(output / "slide_3_gemini_base.jpg"), "plan")
        paths.append(_slide_2(str(output / "slide_2_summary.jpg"), user_name, analysis_json, slide_2_bg))
        paths.append(_slide_3(str(output / "slide_3_plan_forecast.jpg"), user_name, analysis_json, slide_3_bg))
    return paths


def generate_protocol_image(
    original_photo_path: str,
    output_path: str,
    user_name: str,
    analysis_json: dict[str, Any],
) -> str:
    _fail_legacy_renderer()
    if settings.protocol_image_provider.lower() != "gemini":
        raise RuntimeError("Bella Vladi Face Protocol requires PROTOCOL_IMAGE_PROVIDER=gemini")
    base_path = str(Path(output_path).with_name("slide_1_gemini_base.jpg"))
    return _compose_exact_slide_1(
        generate_protocol_background_with_gemini(base_path, "face_map"),
        original_photo_path,
        output_path,
        user_name,
        analysis_json,
    )
