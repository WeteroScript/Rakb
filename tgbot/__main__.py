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

    tunnel = None
    if settings.tunnel_relay:
        from .tunnel import Tunnel
        host, _, port_s = settings.tunnel_relay.rpartition(":")
        if not host or not port_s.isdigit():
            raise SystemExit("TUNNEL_RELAY must be host:port (the relay/relay.py endpoint).")
        if not settings.tunnel_token:
            raise SystemExit("TUNNEL_TOKEN is required when TUNNEL_RELAY is set (must match RELAY_TOKEN).")
        tunnel = Tunnel(host, int(port_s), settings.tunnel_token, settings.tunnel_local_port)
        await tunnel.start()
        logging.info("tunnel: local 127.0.0.1:%d -> relay %s (UDP-over-TCP)",
                     settings.tunnel_local_port, settings.tunnel_relay)

    sup = RakSampSupervisor(settings.raksamp_bin, settings.data_dir, tunnel=tunnel)
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
