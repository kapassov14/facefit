from __future__ import annotations

from typing import Any

from app.after_photo.schemas import AfterPhotoIntensity, AfterPhotoPrompt, IntensityPreset
from app.core.config import settings

UNIVERSAL_AFTER_PHOTO_PROMPT = """Edit the provided portrait photo. Create an obvious “after face fitness transformation” version of the same exact person.

This is an IMAGE EDIT of the original photo, not a new generation.

MAIN GOAL:
Create a strong, clearly visible facial lifting transformation, as if the person completed an intensive face fitness, lymphatic drainage, posture and facial massage program.

The result must show real visible structural improvements, not just brighter skin or cleaner retouch.
Do not play safe. Do not keep the face almost unchanged. The transformation must be obvious at thumbnail size.
This is allowed to be a strong advertising-style transformation as long as it is still the same person.

ABSOLUTELY PRESERVE:
- same exact identity
- same age category
- same ethnicity
- same facial proportions
- same camera angle
- same framing
- same hairstyle
- same hair color
- same background
- same lighting direction
- same skin tone
- same natural expression
- same natural skin texture
- pores, small imperfections and asymmetry

VISIBLE TRANSFORMATION REQUIREMENTS:
Make the improvement strongly noticeable. Prioritize structural lifting over subtle retouch.

1. Facial lifting and oval:
- strongly lift and tighten the lower face
- make the facial oval much clearer and more defined
- reduce heaviness in the lower third of the face by 45-60%
- make the lower face visibly slimmer and less heavy
- reduce visual width/heaviness around the jaw and mouth area by about 15-25%
- reduce the appearance of jowls / sagging around the jawline
- make the jawline visibly more collected and toned
- noticeably improve the chin-neck transition
- lift the soft tissues visually upward, not just brighten the skin

2. Cheekbones and midface:
- lift the midface
- make cheekbones slightly more pronounced and clearly more visually defined
- add a visible lifted cheek effect
- create a stronger V-lift impression from cheekbones to jawline
- make cheeks look more toned, not hollow
- reduce midface puffiness by 35-45%
- preserve the person's natural cheek shape

3. Eyes and gaze:
- make the gaze more open, fresh, expressive and visually brighter
- visibly lift the upper eyelid area
- reduce heaviness around the eyes
- reduce under-eye puffiness by 40-55%
- remove visible dark circles / blue under-eye shadows as much as possible while preserving natural skin tone
- make the eyes look more rested, but do not change eye shape
- do not enlarge the eyes
- do not add makeup, mascara, eyeliner or lashes

4. Nasolabial area:
- visibly soften the nasolabial folds
- make the area around the mouth look less tired
- reduce visual heaviness around the nose-mouth area
- do not erase the nasolabial folds completely
- do not change the smile, lips, mouth shape or expression

5. Forehead and brow tension:
- visibly soften the appearance of forehead tension
- relax the area between the eyebrows
- make the brow area look calmer and less tense
- reduce visible forehead lines, brow lines and fine wrinkles by about 70%
- do not change eyebrow shape or position dramatically

6. Skin and freshness:
- make the face look fresher, healthier and more rested
- keep natural skin texture visible
- keep pores and small imperfections
- reduce approximately 70% of visible wrinkles and fine lines while keeping the face natural and recognizably textured
- do not over-smooth the skin, but visible lifting is more important than tiny texture perfection
- do not create glossy, plastic or airbrushed skin
- do not simply brighten the photo
- skin improvement should be secondary; structural lifting is the priority

IMPORTANT PRIORITY:
The main visible difference must come from:
- lifted facial oval
- slightly more pronounced and more defined cheekbones
- more open, expressive gaze
- visibly reduced dark circles under the eyes
- approximately 70% fewer visible wrinkles / fine lines
- reduced puffiness
- softer nasolabial area
- fresher appearance

STRENGTH TARGET:
- this should look like a strong before/after advertisement result
- the face must not look almost identical to the source image
- if choosing between a subtle edit and a stronger edit, choose the stronger edit
- preserve identity, but do not preserve puffiness, heaviness, tired gaze or sagging
- visibly change the facial contour: lower face slimmer, cheeks lifted, jawline clearer
- the result should be obvious when placed next to the original photo in a small Telegram image

STRICT IDENTITY RULES:
Do not change:
- identity
- face shape beyond the requested lifting
- lip shape
- eye shape
- nose shape
- eyebrow shape
- hairstyle
- hairline
- skin tone
- background
- lighting
- clothing
- camera angle
- facial expression

Do not add:
- makeup
- lipstick
- mascara
- eyeliner
- contouring
- blush
- glossy skin
- fake eyelashes
- perfect skin

The final image must look like the SAME PERSON after 8-12 weeks of intensive face fitness, lymphatic drainage, posture work, facial massage and healthy lifestyle.

Make the before/after difference clearly visible, especially in the facial oval, cheekbones, gaze and lower face."""

UNIVERSAL_NEGATIVE_PROMPT = (
    "different person, changed identity, changed bone structure, changed ethnicity, changed age category, "
    "changed face angle, changed background, changed lighting, changed hairstyle, changed hairline, "
    "changed eye shape, changed nose, changed mouth, changed lip shape, heavy makeup, "
    "deformed face, distorted eyes, distorted teeth, asymmetry artifacts, blurry, low quality"
)

INTENSITY_PROMPT_ADDITIONS: dict[AfterPhotoIntensity, str] = {
    "subtle": "Apply a visible transformation while preserving identity. Do not make a barely noticeable edit.",
    "balanced": "Apply a strong structural face-fitness transformation while preserving identity.",
    "visible": "Apply the strongest visible structural face-fitness transformation while preserving identity. Make the before/after difference obvious: slimmer lower face, lifted cheeks, clearer jawline, fresher gaze.",
}

EDIT_ATTEMPT_PROMPT_ADDITIONS: dict[int, str] = {
    1: (
        "Attempt 1: strong structural lift. Make the face much fresher and less puffy, "
        "with an obvious lower-face lift in a before/after comparison."
    ),
    2: (
        "Attempt 2: stronger visible lift because the previous result was too subtle. "
        "Increase de-puffing, lower-face lift, cheek definition and jawline clarity while preserving identity."
    ),
    3: (
        "Attempt 3: maximum visible face-fitness lift while preserving identity. Make the improvement unmistakably visible: "
        "much less swelling, tighter and slimmer facial oval, more defined cheeks, more open gaze and a clearer jawline. "
        "This must not be subtle."
    ),
}


def _normalize_intensity(intensity: str | None) -> AfterPhotoIntensity:
    value = (intensity or settings.after_photo_default_intensity or "balanced").strip().lower()
    if value in {"subtle", "balanced", "visible"}:
        return value  # type: ignore[return-value]
    return "balanced"


def get_intensity_preset(intensity: str | None) -> IntensityPreset:
    normalized = _normalize_intensity(intensity)
    strength = {
        "subtle": settings.after_photo_subtle_strength,
        "balanced": settings.after_photo_balanced_strength,
        "visible": settings.after_photo_visible_strength,
    }[normalized]
    return IntensityPreset(
        name=normalized,
        prompt_addition=INTENSITY_PROMPT_ADDITIONS[normalized],
        strength=strength,
        guidance=settings.after_photo_guidance,
    )


def stronger_intensity(intensity: str) -> AfterPhotoIntensity:
    current = _normalize_intensity(intensity)
    if current == "subtle":
        return "balanced"
    return "visible"


def conservative_intensity(intensity: str) -> AfterPhotoIntensity:
    current = _normalize_intensity(intensity)
    if current == "visible":
        return "balanced"
    return "subtle"


ZONE_PROMPT_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("глаз", "eye", "under", "век"), "remove dark circles and blue under-eye shadows, reduce under-eye puffiness, and make the gaze more open, expressive and rested"),
    (("овал", "jaw", "нижн", "подбород", "брыл"), "create a clearer, more lifted lower facial oval and reduce lower-face heaviness"),
    (("носогуб", "nasolab"), "subtly soften the nasolabial area without changing the mouth or expression"),
    (("щек", "скул", "cheek", "midface"), "make cheekbones slightly more pronounced and more defined while reducing midface puffiness"),
    (("лоб", "межбров", "brow", "forehead"), "reduce about 70% of visible forehead and brow wrinkles while preserving eyebrow shape"),
    (("шея", "neck"), "slightly improve the chin-neck transition without changing posture or framing"),
    (("отеч", "отёч", "puff"), "reduce visible facial puffiness while preserving natural skin texture"),
)


def _collect_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_collect_text_values(item))
        return result
    if isinstance(value, dict):
        result = []
        for key in (
            "id",
            "zone",
            "name",
            "title",
            "issue",
            "recommendation",
            "what_is_visible",
            "why_it_matters",
            "what_to_do",
            "description",
            "main_observation",
            "main_focus",
            "main_scenario",
            "recommended_start",
            "main_explanation",
            "main_result_lever",
            "start_with",
            "then_add",
            "status",
            "level",
        ):
            result.extend(_collect_text_values(value.get(key)))
        for key in (
            "zones",
            "items",
            "features",
            "strengths",
            "recommended_focus",
            "what_appears_first",
            "mechanics",
            "priorities",
            "personal_sequence",
        ):
            result.extend(_collect_text_values(value.get(key)))
        return result
    return []


def build_structured_after_photo_focus(analysis_json: dict[str, Any] | None, selected_problems: list[str] | None = None) -> list[str]:
    analysis = analysis_json if isinstance(analysis_json, dict) else {}
    candidates: list[Any] = [analysis]
    for key in ("zones", "zone_map", "attention_points", "recommended_focus", "causes"):
        value = analysis.get(key)
        if isinstance(value, dict):
            candidates.extend(value.get("zones") or value.get("items") or [])
        elif isinstance(value, list):
            candidates.extend(value)
    skin_type = analysis.get("skin_type")
    if isinstance(skin_type, dict):
        candidates.extend(skin_type.get("attention_points") or [])
    candidates.extend(selected_problems or [])

    raw_text = " ".join(_collect_text_values(candidates)).lower()
    instructions: list[str] = []
    for keywords, instruction in ZONE_PROMPT_RULES:
        if any(keyword in raw_text for keyword in keywords) and instruction not in instructions:
            instructions.append(instruction)
    if not instructions:
        instructions = [
            "make the gaze more open and rested",
            "create a clearer and more lifted lower facial oval",
            "reduce visible puffiness in the face",
            "make cheekbones slightly more pronounced and more defined",
            "remove visible dark circles under the eyes",
            "reduce visible wrinkles and fine lines by about 70%",
        ]
    return instructions[:6]


def build_after_photo_prompt(
    intensity: str,
    attempt_index: int = 1,
    analysis_json: dict[str, Any] | None = None,
    selected_problems: list[str] | None = None,
) -> dict:
    preset = get_intensity_preset(intensity)
    attempt = max(1, min(3, int(attempt_index or 1)))
    structured_focus = build_structured_after_photo_focus(analysis_json, selected_problems)
    structured_block = "\n".join(f"- {item}" for item in structured_focus)
    prompt = (
        f"{UNIVERSAL_AFTER_PHOTO_PROMPT}\n\n"
        "PERSONALIZED EDIT TARGETS FROM THE FACE ANALYSIS:\n"
        f"{structured_block}\n\n"
        "The visible before/after difference must be structural and zone-specific, not just smoother skin, cleaner lighting, or a beauty retouch.\n\n"
        f"{preset.prompt_addition}\n\n"
        f"{EDIT_ATTEMPT_PROMPT_ADDITIONS[attempt]}\n\n"
        "Final instruction: produce a visibly transformed after-photo, not a conservative retouch."
    )
    payload = AfterPhotoPrompt(
        prompt=prompt,
        negative_prompt=UNIVERSAL_NEGATIVE_PROMPT,
        intensity=preset.name,
        preset=preset,
        attempt_index=attempt,
    ).model_dump()
    payload["structured_focus"] = structured_focus
    return payload
