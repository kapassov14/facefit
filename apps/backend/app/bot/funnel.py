from __future__ import annotations

from html import escape
from pathlib import Path

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.core.config import settings

AFTER_VISUAL_DELAY_SECONDS = 60
OFFER_DELAY_SECONDS = 30 * 60
BONUS_DELAY_SECONDS = 24 * 60 * 60

DEFAULT_COURSE_URL = "https://bellavladi.ru"


def first_name(name: str | None) -> str:
    cleaned = " ".join((name or "").split()).strip()
    return escape(cleaned or "красотка")


def welcome_text() -> str:
    return (
        "Привет! Это Белла 🤍\n\n"
        "Этот бот проанализирует твоё лицо по моей авторской методике и даст точные персональные рекомендации: "
        "твой тип старения, оценку внешности и конкретный план как сохранить свою красоту.\n\n"
        "Всё это абсолютно бесплатно. Просто загрузи фото и через минуту у тебя будет персональный протокол лица 💆"
    )


def name_request_text() -> str:
    return "Как тебя зовут?"


def age_request_text(name: str | None = None) -> str:
    return (
        f"{first_name(name)}, напиши, пожалуйста, свой возраст цифрой.\n\n"
        "Это нужно, чтобы я сравнила паспортный возраст с визуальным впечатлением кожи и сделала протокол точнее.\n"
        "Если не хочешь указывать возраст — напиши «пропустить»."
    )


def photo_instruction_text(name: str | None) -> str:
    return (
        f"{first_name(name)}, отлично! 🤍\n\n"
        "Для персонального протокола мне нужно твоё фото анфас при дневном освещении, без фильтров.\n\n"
        "Вот пример как должно выглядеть фото 👇\n\n"
        "Постарайся загрузить в хорошем качестве, так протокол будет точнее и я начну анализ)"
    )


def problems_prompt_text(name: str | None) -> str:
    return (
        f"{first_name(name)}, ты красотка! ✨\n\n"
        "Теперь выбери, что тебя сейчас беспокоит больше всего? "
        "Можешь выбрать одну или несколько зон."
    )


def protocol_ready_caption() -> str:
    return "Готово! Вот твой персональный протокол лица"


def zone_protocol_caption() -> str:
    return "Карта зон лица с персональными акцентами."


def after_visual_text(name: str | None) -> str:
    return (
        f"{first_name(name)}, посмотри, вот такую подтяжку зон ты можешь сделать с помощью фейс-фитнеса за 30 дней.\n\n"
        "Первые изменения ты увидишь уже через две недели. За два месяца регулярных занятий по 20 минут в день "
        "ты можешь заметно подтянуть лицо.\n\n"
        "Хочешь попробовать тренировку от Беллы? Тоже абсолютно бесплатно."
    )


def training_text() -> str:
    return (
        "Держи — тренировка против носогубных складок, морщин и потери овала.\n\n"
        "Я знаю, что времени на себя почти нет)) Работа, стресс, контроль над всеми и вся, семья, "
        "и ты снова в конце списка…\n\n"
        "Именно поэтому этот комплекс занимает всего 6 минут, чтобы ты могла найти это драгоценное время "
        "на себя и свою женственность. Я тебя понимаю, как никто другой: у меня маленький ребёнок, бизнес, "
        "семья, я переехала в другую страну и всё равно нахожу время на себя.\n\n"
        "Поэтому главное для меня — чтобы каждая тренировка давала эффект даже при минимуме времени. "
        "В этом месяце мне уже сорок, и я точно живой пример, что это работает 🫣"
    )


def selected_zone_text(selected_problems: list[str] | None) -> str:
    problems = [item for item in (selected_problems or []) if item]
    if not problems:
        return "зоны, которые ты выбрала"
    if len(problems) == 1:
        return problems[0]
    if len(problems) == 2:
        return f"{problems[0]} и {problems[1]}"
    return f"{', '.join(problems[:2])} и другие зоны"


def offer_text(name: str | None, selected_problems: list[str] | None) -> str:
    zone = escape(selected_zone_text(selected_problems))
    return (
        f"{first_name(name)}, дарю тебе еще один подарок на 48 часов 🎁\n\n"
        f"Я знаю, что тебя беспокоит: {zone}. Вот каких результатов смогли добиться женщины благодаря моей программе "
        "всего за первые 30 дней 👇\n\n"
        "Ты можешь присоединиться к моему полноценному курсу, где я собрала 69 упражнений из Кореи, Японии, "
        "Гонконга, России и Таиланда. Я объединила самые эффективные техники и выстроила программу так, "
        "чтобы ты не собирала упражнения по интернету, а просто следовала моей системе и подтянула всё, "
        "что тебя сейчас беспокоит.\n\n"
        "Большинство моих учениц тоже находили совсем немного времени на себя, но этого хватило, чтобы уже через "
        "две недели увидеть первые изменения.\n\n"
        "Ты можешь присоединиться к курсу всего за 1 200 руб. в месяц через Яндекс Сплит, без переплат.\n\n"
        "И вместе с курсом в течение 48 часов ты забираешь бонусы:\n"
        "— Протокол ухода за кожей твоего типа\n"
        "— Корейский Glass Skin чек-лист\n"
        "— Противоотёчный экспресс-массаж для лица\n"
        "— Урок по лифтинг-макияжу от профессионального визажиста\n"
        "— Видеоурок массажа головы для роста волос\n"
        "— План питания Anti-age\n\n"
        "Бонусы будут открыты сразу после оплаты 😍🫠"
    )


def course_more_text() -> str:
    return (
        "Курс FaceLifting — это система из 69 упражнений для лица, собранная в понятный маршрут.\n\n"
        "Ты не выбираешь случайные упражнения из интернета, а идёшь по последовательности: лимфоток, шея, "
        "зона глаз, носогубная зона, овал и тонус кожи.\n\n"
        "Формат создан так, чтобы заниматься дома по 20 минут в день и видеть первые изменения уже через две недели "
        "при регулярной практике."
    )


def questions_text() -> str:
    return (
        "Конечно 🤍\n\n"
        "Напиши свой вопрос, и менеджер поможет разобраться: какой формат подойдет, как проходит оплата "
        "и с чего лучше начать именно тебе."
    )


def bonus_reminder_text(name: str | None) -> str:
    return (
        f"{first_name(name)}, доброе утро! 🌸\n\n"
        "Хочу напомнить: сегодня последний день, когда ты можешь забрать курс вместе с бонусами.\n\n"
        "Завтра бонусное предложение сгорит, и ты сможешь купить только базовый курс, без дополнительных материалов.\n\n"
        "А бонусы — это настоящие секреты, которые я собирала годами. 🤍\n"
        "Я заплатила топовым специалистам — дерматологам, трихологам, нутрициологам — чтобы они составили "
        "для тебя эти материалы. Общая стоимость этих консультаций — более $3 000.\n\n"
        "Люди, которые посвятили карьеру женской красоте, сохранению молодости, идеальной коже и подтянутому лицу, "
        "поделились всем, что знают.\n\n"
        "И ты можешь забрать всё это прямо сейчас — сразу после покупки, без подписок и доплат."
    )


def bonus_details_text() -> str:
    return (
        "Что входит в бонусы:\n\n"
        "1. Протокол ухода за кожей твоего типа\n"
        "2. Корейский Glass Skin чек-лист\n"
        "3. Противоотёчный экспресс-массаж для лица\n"
        "4. Урок по лифтинг-макияжу от профессионального визажиста\n"
        "5. Видеоурок массажа головы для роста волос\n"
        "6. План питания Anti-age\n\n"
        "Все материалы открываются сразу после оплаты."
    )


def fallback_course_url() -> str:
    return settings.funnel_course_url or DEFAULT_COURSE_URL


def fallback_installment_url() -> str:
    return settings.funnel_installment_url or fallback_course_url()


def fallback_manager_url() -> str:
    return settings.funnel_manager_url or fallback_course_url()


def training_video_path() -> str | None:
    configured = settings.funnel_training_video_path
    if not configured:
        return None
    path = Path(configured)
    if not path.is_absolute():
        path = settings.storage_root() / configured
    return str(path) if path.exists() else None


def case_media_paths() -> list[str]:
    raw = settings.funnel_case_media_paths or ""
    paths: list[str] = []
    for item in raw.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        path = Path(cleaned)
        if not path.is_absolute():
            path = settings.storage_root() / cleaned
        if path.exists():
            paths.append(str(path))
    return paths[:3]


def after_visual_keyboard(analysis_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, хочу тренировку", callback_data=f"funnel:training:{analysis_id}")],
            [InlineKeyboardButton(text="Расскажи подробнее о курсе", callback_data=f"funnel:course_more:{analysis_id}")],
        ]
    )


def offer_keyboard(analysis_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Хочу начать — взять курс", callback_data=f"funnel:buy:{analysis_id}")],
            [InlineKeyboardButton(text="Узнать подробнее о курсе", callback_data=f"funnel:course_more:{analysis_id}")],
            [InlineKeyboardButton(text="Есть вопросы", callback_data=f"funnel:questions:{analysis_id}")],
            [InlineKeyboardButton(text="Хочу в рассрочку", callback_data=f"funnel:installment:{analysis_id}")],
        ]
    )


def bonus_keyboard(analysis_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Забрать курс с бонусами", callback_data=f"funnel:buy:{analysis_id}")],
            [InlineKeyboardButton(text="Что входит в бонусы?", callback_data=f"funnel:bonuses:{analysis_id}")],
        ]
    )


def link_keyboard(text: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])
