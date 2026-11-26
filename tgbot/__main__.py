"""Entry point: python -m tgbot

Starts the health endpoint, wires the supervisor to the Telegram bot, and runs
long polling. On SIGTERM (BotHost redeploy) aiogram stops polling and we shut the
raksamp child down cleanly.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .bot import build_router, make_broadcast
from .config import Settings
from .health import start_health
from .supervisor import RakSampSupervisor


async def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    settings.validate()

    sup = RakSampSupervisor(settings.raksamp_bin, settings.data_dir)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    sup._broadcast = make_broadcast(bot)

    dp = Dispatcher()
    dp.include_router(build_router(sup, set(settings.admin_ids)))

    health = await start_health(sup, settings.port)
    logging.info("health on 0.0.0.0:%d | admins=%s | bin=%s | data=%s",
                 settings.port, settings.admin_ids, settings.raksamp_bin, settings.data_dir)

    if settings.autostart:
        logging.info("autostart: %s", await sup.start())

    try:
        await dp.start_polling(bot)
    finally:
        await sup.shutdown()
        await health.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
