"""Tiny HTTP health/status endpoint. BotHost expects the container to listen on
0.0.0.0:$PORT; Telegram itself uses long polling, so this is only for health checks
and a quick status glance."""
from __future__ import annotations

from aiohttp import web


def make_health_app(supervisor):
    async def index(_request):
        return web.json_response({"ok": True, **supervisor.status()})

    async def healthz(_request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/health", healthz)
    app.router.add_get("/healthz", healthz)
    return app


async def start_health(supervisor, port: int) -> web.AppRunner:
    runner = web.AppRunner(make_health_app(supervisor))
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    return runner
