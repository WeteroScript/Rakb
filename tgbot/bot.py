"""aiogram 3 handlers: the Telegram control surface for the raksamp supervisor.

Admin-only. Query commands capture the client's output and reply with it; action
commands fire into the client's stdin. /cmd is the universal escape hatch (any
RunCommand line, server /command, or plain chat).
"""
from __future__ import annotations

import html
import json
import socket

from aiogram import Bot, Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import Message

from .sampquery import nettest, query_server
from .supervisor import RakSampSupervisor

HELP = (
    "<b>RakSAMP control</b>\n"
    "<b>Lifecycle</b>\n"
    "/run — start the client\n"
    "/stop — stop it\n"
    "/restart — restart\n"
    "/status — process / connection state\n\n"
    "<b>Server</b>\n"
    "/connect &lt;ip&gt; &lt;port&gt; [nick] [pass] — set server &amp; (re)connect\n"
    "/nick &lt;name&gt; — change nickname (reconnect)\n"
    "/mode &lt;id&gt; — 1 bare, 2 still, 3 normal, 4 follow, 5 follow+veh\n"
    "/spawn — spawn\n"
    "/auth &lt;pass&gt; · /reg &lt;pass&gt; · /recon &lt;pass&gt;\n\n"
    "<b>Interaction</b>\n"
    "/say &lt;text&gt; — chat\n"
    "/scmd &lt;cmd&gt; — server command (e.g. login 123)\n"
    "/dialog &lt;id&gt; &lt;button 0/1&gt; &lt;item&gt; &lt;text&gt; — answer a dialog\n"
    "/players · /npcs · /vlist · /teleport [id]\n\n"
    "<b>Raw / logs</b>\n"
    "/cmd &lt;line&gt; — send any command (!pos x 100, !weapon 24, …)\n"
    "/log on|off — live log stream to this chat\n"
    "/logs [n] — last n log lines\n"
    "/config — current instance config\n"
    "/query [ip] [port] — UDP reachability probe (diagnose connect failures)\n"
    "/nettest [ip] [port] — probe reference servers + target: host-block vs target-block"
)


class AdminFilter(BaseFilter):
    def __init__(self, admins: set[int]):
        self.admins = admins

    async def __call__(self, message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in self.admins)


def _code(text: str) -> str:
    text = text or "(empty)"
    if len(text) > 3800:
        text = text[:3800] + "\n…(truncated)"
    return "<pre>" + html.escape(text) + "</pre>"


def build_router(sup: RakSampSupervisor, admins: set[int]) -> Router:
    r = Router()
    r.message.filter(AdminFilter(admins))

    async def relay(message: Message, line: str, wait: float = 1.2):
        if not sup.running:
            await message.answer("Client is not running. /run first.")
            return
        out = await sup.run_and_capture(line, wait=wait)
        await message.answer(_code("\n".join(out)))

    async def fire(message: Message, line: str, note: str | None = None):
        if not sup.running:
            await message.answer("Client is not running. /run first.")
            return
        ok = await sup.send(line)
        await message.answer(("sent: " + html.escape(note or line)) if ok else "send failed (process died?)")

    @r.message(Command("start", "help"))
    async def h_help(message: Message):
        await message.answer(HELP)

    @r.message(Command("status"))
    async def h_status(message: Message):
        s = sup.status()
        icon = "🟢" if s["connected"] else ("🟡" if s["running"] else "⚪")
        txt = (
            f"{icon} <b>status</b>\n"
            f"running: <b>{s['running']}</b>  connected: <b>{s['connected']}</b>\n"
            f"pid: {s['pid']}  uptime: {s['uptime_s']}s\n"
            f"server: <code>{html.escape(s['server'])}</code>\n"
            f"nick: <code>{html.escape(str(s['nickname']))}</code>  mode: {s['runmode']}\n"
            f"last: {html.escape(s['last_event'] or '-')}"
        )
        await message.answer(txt)

    @r.message(Command("run"))
    async def h_run(message: Message):
        res = await sup.start()
        await message.answer(f"client: <b>{res}</b>\nserver: <code>{html.escape(sup.status()['server'])}</code>")

    @r.message(Command("stop"))
    async def h_stop(message: Message):
        await message.answer(f"client: <b>{await sup.stop()}</b>")

    @r.message(Command("restart"))
    async def h_restart(message: Message):
        await message.answer(f"client: <b>{await sup.restart()}</b>")

    @r.message(Command("connect"))
    async def h_connect(message: Message, command: CommandObject):
        args = (command.args or "").split()
        if len(args) < 2:
            await message.answer("usage: /connect &lt;ip&gt; &lt;port&gt; [nick] [pass]")
            return
        addr, port = args[0], args[1]
        if not port.isdigit():
            await message.answer("port must be a number")
            return
        nick = args[2] if len(args) > 2 else None
        pw = args[3] if len(args) > 3 else None
        sup.cfg.set_server(addr, int(port), nick, pw)
        if sup.running:
            line = f"!change_server {addr} {port}"
            if nick:
                line += f" {nick}"
                if pw:
                    line += f" {pw}"
            out = await sup.run_and_wait(line, timeout=9.0)
            head = f"reconnecting to <code>{html.escape(addr)}:{port}</code>"
        else:
            await sup.start()
            out = await sup.run_and_wait(None, timeout=9.0)
            head = f"started against <code>{html.escape(addr)}:{port}</code>"
        body = "\n".join(out) if out else "(нет вывода за 9с — проверь /status и /log on)"
        state = "🟢 connected" if sup.connected else "🟡 not connected yet — /status, /log on"
        await message.answer(head + "\n" + _code(body) + "\n" + state)

    @r.message(Command("nick"))
    async def h_nick(message: Message, command: CommandObject):
        name = (command.args or "").strip()
        if not name:
            await message.answer("usage: /nick &lt;name&gt;")
            return
        sup.cfg.data["server"]["nickname"] = name
        sup.cfg.save()
        await fire(message, f"!change_name reconnect {name}", f"nick -> {name}")

    @r.message(Command("mode"))
    async def h_mode(message: Message, command: CommandObject):
        arg = (command.args or "").strip()
        if not arg.isdigit() or not (1 <= int(arg) <= 5):
            await message.answer("usage: /mode &lt;1..5&gt; (1 bare, 2 still, 3 normal, 4 follow, 5 follow+veh)")
            return
        sup.cfg.data["runmode"] = int(arg)
        sup.cfg.save()
        await fire(message, f"!runmode {arg}", f"runmode -> {arg}")

    @r.message(Command("spawn"))
    async def h_spawn(message: Message):
        await relay(message, "!spawn", wait=0.8)

    @r.message(Command("auth"))
    async def h_auth(message: Message, command: CommandObject):
        if not command.args:
            await message.answer("usage: /auth &lt;password&gt;")
            return
        await relay(message, f"!auth {command.args.strip()}", wait=1.0)

    @r.message(Command("reg"))
    async def h_reg(message: Message, command: CommandObject):
        if not command.args:
            await message.answer("usage: /reg &lt;password&gt;")
            return
        await relay(message, f"!reg {command.args.strip()}", wait=1.6)

    @r.message(Command("recon"))
    async def h_recon(message: Message, command: CommandObject):
        if not command.args:
            await message.answer("usage: /recon &lt;password&gt;")
            return
        await relay(message, f"!recon {command.args.strip()}", wait=1.0)

    @r.message(Command("players"))
    async def h_players(message: Message):
        await relay(message, "!players")

    @r.message(Command("npcs"))
    async def h_npcs(message: Message):
        await relay(message, "!npcs")

    @r.message(Command("vlist"))
    async def h_vlist(message: Message):
        await relay(message, "!vlist")

    @r.message(Command("teleport"))
    async def h_teleport(message: Message, command: CommandObject):
        arg = (command.args or "").strip()
        await relay(message, "!teleport" + (f" {arg}" if arg else ""))

    @r.message(Command("dialog"))
    async def h_dialog(message: Message, command: CommandObject):
        args = (command.args or "").split()
        if len(args) < 4:
            await message.answer("usage: /dialog &lt;id&gt; &lt;button 0/1&gt; &lt;item&gt; &lt;text&gt;")
            return
        await fire(message, f"!dialogresponse {args[0]} {args[1]} {args[2]} {' '.join(args[3:])}",
                   "dialog response sent")

    @r.message(Command("say"))
    async def h_say(message: Message, command: CommandObject):
        if not command.args:
            await message.answer("usage: /say &lt;text&gt;")
            return
        await fire(message, command.args, "chat sent")

    @r.message(Command("scmd"))
    async def h_scmd(message: Message, command: CommandObject):
        if not command.args:
            await message.answer("usage: /scmd &lt;command&gt;")
            return
        cmd = command.args.strip()
        if not cmd.startswith("/"):
            cmd = "/" + cmd
        await fire(message, cmd, "server command sent")

    @r.message(Command("cmd"))
    async def h_cmd(message: Message, command: CommandObject):
        if not command.args:
            await message.answer("usage: /cmd &lt;line&gt;  e.g. /cmd !pos x 100  or  /cmd !weapon 24")
            return
        await relay(message, command.args, wait=1.2)

    @r.message(Command("log"))
    async def h_log(message: Message, command: CommandObject):
        arg = (command.args or "").strip().lower()
        if arg in ("on", "1", "yes"):
            sup.subscribe(message.chat.id)
            await message.answer("live log: <b>on</b> (batched ~1.5s). /log off to stop.")
        elif arg in ("off", "0", "no"):
            sup.unsubscribe(message.chat.id)
            await message.answer("live log: <b>off</b>")
        else:
            await message.answer("usage: /log on|off")

    @r.message(Command("logs"))
    async def h_logs(message: Message, command: CommandObject):
        arg = (command.args or "").strip()
        n = int(arg) if arg.isdigit() else 40
        await message.answer(_code(sup.tail(min(n, 200))))

    @r.message(Command("config"))
    async def h_config(message: Message):
        await message.answer(_code(json.dumps(sup.cfg.data, indent=2, ensure_ascii=False)))

    @r.message(Command("query"))
    async def h_query(message: Message, command: CommandObject):
        args = (command.args or "").split()
        if len(args) >= 2:
            addr, port = args[0], args[1]
        else:
            addr = sup.cfg.data["server"]["addr"]
            port = str(sup.cfg.data["server"]["port"])
        if not port.isdigit():
            await message.answer("usage: /query [ip] [port]")
            return
        await message.answer(f"querying <code>{html.escape(addr)}:{port}</code> over UDP…")
        try:
            info = await query_server(addr, int(port), timeout=3.0)
        except (socket.timeout, TimeoutError):
            await message.answer(
                "🔴 <b>no UDP response in 3s</b>\n"
                "Either outbound UDP is blocked on the host, or the server firewalls this "
                "container's IP. SA-MP needs UDP — if the host blocks it, the client can't "
                "connect. Try BotHost's «Зарубежный IP» toggle + redeploy, or ask support about UDP egress."
            )
            return
        except Exception as e:
            await message.answer(f"query error: {html.escape(str(e))}")
            return
        await message.answer(
            "🟢 <b>UDP OK — server reachable</b>\n"
            f"hostname: <b>{html.escape(info['hostname'])}</b>\n"
            f"players: {info['players']}/{info['maxplayers']}  password: {info['password']}\n"
            f"gamemode: {html.escape(info['gamemode'])}\n"
            "UDP egress works. If /connect still fails, it's the game-protocol layer "
            "(version/cookie or server-side play filtering), not the network."
        )

    @r.message(Command("nettest"))
    async def h_nettest(message: Message, command: CommandObject):
        args = (command.args or "").split()
        if len(args) >= 2:
            addr, port = args[0], args[1]
        else:
            addr = sup.cfg.data["server"]["addr"]
            port = str(sup.cfg.data["server"]["port"])
        if not port.isdigit():
            await message.answer("usage: /nettest [ip] [port]")
            return
        await message.answer(
            f"nettest: probing 3 reference servers + <code>{html.escape(addr)}:{port}</code> over UDP…"
        )
        res = await nettest(addr, int(port), timeout=3.0)
        lines = ["<b>reference servers (UDP egress control):</b>"]
        for (h, p), ok in res["refs"]:
            lines.append(f"{'🟢' if ok else '🔴'} {h}:{p}")
        lines.append("")
        if res["target_ok"]:
            info = res["info"] or {}
            lines.append(
                f"🟢 <b>target reachable</b> — {html.escape(info.get('hostname', '?'))} "
                f"({info.get('players', '?')}/{info.get('maxplayers', '?')})"
            )
            lines.append("UDP egress AND the target both answer. If /connect still fails, it's the "
                         "game-protocol layer (version/cookie/play filtering), not the network.")
        elif res["udp_ok"]:
            lines.append(f"🔴 <b>target silent, but UDP egress works</b> (references answered).")
            lines.append("The host is NOT blocking UDP. The target itself is unreachable from here: "
                         "wrong ip/port, server offline, or it firewalls this container's IP. "
                         "Try BotHost «Зарубежный IP» + redeploy to change egress IP, or verify the address.")
        else:
            lines.append("🔴 <b>no UDP anywhere</b> — references AND target all silent.")
            lines.append("Outbound UDP is blocked on the host (or all egress is). SA-MP needs UDP. "
                         "Ask BotHost support about UDP egress, or run on a VPS with open UDP. "
                         "A subdomain/webhook does NOT help — that's inbound HTTPS, not outbound UDP.")
        await message.answer("\n".join(lines))

    return r


def make_broadcast(bot: Bot):
    async def broadcast(chat_id: int, text: str):
        await bot.send_message(chat_id, _code(text))
    return broadcast
