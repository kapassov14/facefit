from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

DEFAULT_PROBLEMS = [
    {"slug": "nasolabial", "title": "Носогубные складки"},
    {"slug": "glabella", "title": "Межбровная морщина"},
    {"slug": "eyes", "title": "Нависшее веко / мешки под глазами"},
    {"slug": "oval", "title": "Потеря овала / брыли"},
    {"slug": "double_chin", "title": "Второй подбородок"},
    {"slug": "puffiness", "title": "Отечность и усталый вид"},
    {"slug": "skin_tone", "title": "Тонус и цвет кожи"},
]


def consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Согласна, продолжить", callback_data="consent:yes")],
            [InlineKeyboardButton(text="Отмена", callback_data="consent:no")],
        ]
    )


def problems_keyboard(problem_catalog: list[dict[str, str]] | None = None, selected: set[str] | None = None) -> InlineKeyboardMarkup:
    selected = selected or set()
    rows = []
    for item in problem_catalog or DEFAULT_PROBLEMS:
        mark = "✓ " if item["slug"] in selected else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{item['title']}", callback_data=f"problem:{item['slug']}")])
    rows.append([InlineKeyboardButton(text="✅ Готово — сделай анализ", callback_data="problem:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def title_by_slug(slug: str, problem_catalog: list[dict[str, str]] | None = None) -> str:
    for item in problem_catalog or DEFAULT_PROBLEMS:
        if item["slug"] == slug:
            return item["title"]
    return slug
