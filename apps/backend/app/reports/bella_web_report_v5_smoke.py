from __future__ import annotations

import hashlib
import json
from typing import Any

from app.reports.bella_web_report import (
    WEB_REPORT_VERSION,
    _build_detailed_web_sections,
    _validate_web_report_v5,
    _web_visual_age,
)


def _zone_map(zones: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "title": "Карта зон лица",
        "zones": [
            {
                "id": f"zone_{index}",
                "number": index,
                "title": title,
                "status": status,
                "meaning": "зона влияет на свежесть и общее впечатление лица",
                "anchor": {"x": 34 + index * 6, "y": 28 + index * 8},
                "shape": {},
            }
            for index, (title, status) in enumerate(zones, start=1)
        ],
    }


def _protocol(
    *,
    age: int,
    aging_id: str,
    aging_name: str,
    skin_name: str,
    strengths_text: str,
) -> dict[str, Any]:
    return {
        "client": {"name": "Smoke", "age": age, "date": "2026-05-27"},
        "skin_visual_age": {
            "passport_age": age,
            "visual_age": age + 2,
            "text": "кожа выглядит ухоженной, но отдельные зоны могут добавлять усталость",
        },
        "skin_type": {
            "type_name": skin_name,
            "text": "по фото кожа выглядит ровной, ей важно увлажнение и спокойный регулярный уход",
            "bullets": ["хорошо держит форму", "может выглядеть сияющей при уходе"],
        },
        "face_strengths": {
            "text": strengths_text,
            "bullets": [
                "Овал — аккуратная нижняя линия лица",
                "Скулы — дают лицу мягкую опору",
                "Глаза — выразительные и открытые",
            ],
        },
        "aging_type": {
            "type_id": aging_id,
            "type_name": aging_name,
            "display_name": aging_name,
            "evidence": ["зона глаз", "овал лица", "носогубная зона"],
            "text": f"Ваш тип старения — {aging_name}.",
        },
        "future_changes": {"text": "без регулярной поддержки лицо может быстрее выглядеть уставшим"},
        "age_changes": {"text": "сейчас хороший момент начать мягкую работу с лицом"},
        "face_fitness_benefits": {"text": "фейс-фитнес поможет подчеркнуть природные сильные стороны"},
        "time_forecast": {"items": []},
        "final_summary": {"text": "у вас красивое лицо с сильной природной базой", "quote": ""},
    }


def _case_payloads() -> list[dict[str, Any]]:
    return [
        {
            "name": "muscular",
            "age": 31,
            "aging_id": "muscular",
            "aging_name": "Мускульный",
            "mixed_components": [],
            "skin": "Комбинированная, склонная к обезвоженности",
            "strengths": "У лица четкий овал, выразительный взгляд и хорошая костная база.",
            "zones": _zone_map([("Лоб / межбровье", "orange"), ("Жевательная зона", "yellow"), ("Скулы", "green")]),
        },
        {
            "name": "deformation_edema",
            "age": 29,
            "aging_id": "deformation_edema",
            "aging_name": "Деформационно-отечный",
            "mixed_components": [],
            "skin": "Комбинированная кожа",
            "strengths": "У лица мягкая женственная форма, спокойные пропорции и выразительные скулы.",
            "zones": _zone_map([("Зона под глазами", "yellow"), ("Овал лица / нижняя треть", "orange"), ("Скулы", "green")]),
        },
        {
            "name": "fine_wrinkle",
            "age": 36,
            "aging_id": "fine_wrinkle",
            "aging_name": "Мелкоморщинистый",
            "mixed_components": [],
            "skin": "Сухая, тонкая кожа",
            "strengths": "У лица аккуратный контур, тонкие черты и очень мягкое молодое впечатление.",
            "zones": _zone_map([("Кожа щек", "yellow"), ("Зона вокруг глаз", "orange"), ("Овал лица", "green")]),
        },
        {
            "name": "mixed_tired_deformation",
            "age": 24,
            "aging_id": "tired_mixed",
            "aging_name": "Комбинированный: Усталый + Деформационно-отечный",
            "mixed_components": ["tired", "deformation_edema"],
            "skin": "Комбинированная, склонная к обезвоженности",
            "strengths": "У лица нежное молодое впечатление, светлый открытый взгляд и аккуратный овал.",
            "zones": _zone_map([("Зона под глазами", "yellow"), ("Носогубная зона", "yellow"), ("Овал лица / нижняя треть", "orange")]),
        },
    ]


def main() -> None:
    signatures: dict[str, str] = {}
    failures: list[str] = []
    for index, case in enumerate(_case_payloads(), start=1):
        passport_age = case["age"]
        visual_age = _web_visual_age(passport_age, passport_age, index)
        detailed = _build_detailed_web_sections(
            protocol=_protocol(
                age=passport_age,
                aging_id=case["aging_id"],
                aging_name=case["aging_name"],
                skin_name=case["skin"],
                strengths_text=case["strengths"],
            ),
            zone_map=case["zones"],
            aging_id=case["aging_id"],
            aging_name=case["aging_name"],
            mixed_components=case["mixed_components"],
            visual_age=visual_age,
            passport_age=passport_age,
            skin_type_name=case["skin"],
            main_focus=", ".join(zone["title"] for zone in case["zones"]["zones"][:3]),
        )
        quality = _validate_web_report_v5(
            detailed,
            aging_id=case["aging_id"],
            mixed_components=case["mixed_components"],
            visual_age=visual_age,
            passport_age=passport_age,
        )
        signature = hashlib.sha256(json.dumps(detailed, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        signatures[case["name"]] = signature
        if not quality["passed"]:
            failures.append(f"{case['name']}: {quality['errors']}")

    if len(set(signatures.values())) != len(signatures):
        failures.append("reports_are_not_unique_across_cases")

    if failures:
        raise SystemExit("\n".join(failures))

    print(f"{WEB_REPORT_VERSION} smoke ok")
    for name, signature in signatures.items():
        print(f"{name}: {signature}")


if __name__ == "__main__":
    main()
