from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from app.bot import handlers_consent, handlers_funnel, handlers_name, handlers_photo, handlers_problems, handlers_start, handlers_stop
from app.bot.webhook import delete_telegram_webhook_for_polling, setup_telegram_webhook
from app.core.config import settings
from app.core.logging import configure_logging

_dispatcher: Dispatcher | None = None


def build_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is not None:
        return _dispatcher
    storage = RedisStorage.from_url(settings.redis_url) if settings.redis_url else MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(handlers_start.router)
    dp.include_router(handlers_stop.router)
    dp.include_router(handlers_consent.router)
    dp.include_router(handlers_name.router)
    dp.include_router(handlers_photo.router)
    dp.include_router(handlers_problems.router)
    dp.include_router(handlers_funnel.router)
    _dispatcher = dp
    return _dispatcher


async def main() -> None:
    configure_logging()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан. Добавьте токен в .env.")
    if settings.telegram_update_mode == "webhook":
        logging.getLogger(__name__).info("Telegram bot is configured for webhook mode")
        await setup_telegram_webhook()
        return
    bot = Bot(settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()
    logging.getLogger(__name__).info("Bella Vladi Telegram bot started")
    await delete_telegram_webhook_for_polling()
    logging.getLogger(__name__).info("Starting Telegram polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
