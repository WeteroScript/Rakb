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

from .projects import VANILLA_JOIN_VERSION, identify
from .sampquery import (COMMON_SAMP_PORTS, compare, diag, findport, nettest,
                        query_server, selftest)
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
    "/diag [ip] [port] — full 0.3.7 handshake probe: shows the server's raw answers\n"
    "/nettest [ip] [port] — probe reference servers + target: host-block vs target-block\n"
    "/myip — the egress IP a game server sees (via STUN, also tests high-port UDP)\n"
    "/selftest — verify the 0.3.7 handshake against a live public server (read-only)\n"
    "/findport &lt;ip&gt; [port ...] — find which UDP port actually answers SA-MP\n"
    "/project [ip] [port] — identify a mobile-CRMP project and compare with vanilla SA-MP\n"
    "/netdebug on|off — client handshake trace (packet ids, cookie, connection request)\n"
    "/tunnel — UDP-over-TCP tunnel status (when TUNNEL_RELAY is set)"
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
        if pw == "-":
            pw = ""  # explicit "no password"
        prev = sup.cfg.data["server"]
        target_changed = addr != prev["addr"] or int(port) != int(prev["port"])
        # A different server must not inherit the previous server's password: it is
        # sent inside ID_CONNECTION_REQUEST and a server that expects none can drop
        # the request outright, which looks like a network failure.
        if pw is None and target_changed:
            pw = ""
        sup.cfg.set_server(addr, int(port), nick, pw)
        if sup.tunnel:
            await sup.tunnel.set_target(addr, int(port))
        via = " via tunnel" if sup.tunnel else ""
        # Nick, password and netdebug are read from RakSAMPClient.xml at startup, and
        # !change_server cannot clear a password at all, so restart to make the XML
        # authoritative instead of leaving the running client on stale settings.
        if sup.running:
            await sup.restart()
            head = f"reconnecting to <code>{html.escape(addr)}:{port}</code>{via}"
        else:
            await sup.start()
            head = f"started against <code>{html.escape(addr)}:{port}</code>{via}"
        out = await sup.run_and_wait(None, timeout=9.0)
        eff = sup.cfg.data["server"]
        pw_state = f"set ({len(eff['password'])} chars)" if eff["password"] else "none"
        head += f"\nnick: <code>{html.escape(str(eff['nickname']))}</code>, password: {pw_state}"
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
            f"nettest: probing DNS + NTP + STUN (high ports) + SA-MP refs + "
            f"<code>{html.escape(addr)}:{port}</code> over UDP…"
        )
        res = await nettest(addr, int(port), timeout=3.0)
        lines = ["<b>DNS over UDP (port 53):</b>"]
        for s, ok in res["dns"]:
            lines.append(f"{'🟢' if ok else '🔴'} {s}:53")
        lines.append("<b>NTP over UDP (port 123):</b>")
        for s, ok in res["ntp"]:
            lines.append(f"{'🟢' if ok else '🔴'} {s}:123")
        lines.append("<b>STUN over UDP (high ports — same range as SA-MP):</b>")
        for (h, p), mapped in res["stun"]:
            lines.append(f"{'🟢' if mapped else '🔴'} {h}:{p}"
                         + (f" → sees us as {html.escape(mapped)}" if mapped else ""))
        lines.append("<b>SA-MP reference servers:</b>")
        for (h, p), ok in res["refs"]:
            lines.append(f"{'🟢' if ok else '🔴'} {h}:{p}")
        if res["egress_ip"]:
            lines.append(f"\n<b>this container's egress IP:</b> <code>{html.escape(res['egress_ip'])}</code>")
        lines.append("")
        if res["target_ok"]:
            info = res["info"] or {}
            lines.append(
                f"🟢 <b>target reachable</b> — {html.escape(info.get('hostname', '?'))} "
                f"({info.get('players', '?')}/{info.get('maxplayers', '?')})"
            )
            lines.append("UDP works and the target answers. /connect should work; if it still fails "
                         "it's the game-protocol layer (version/cookie/play filtering), not the network.")
        elif res["high_port_ok"] or res["udp_ok"]:
            lines.append("🟡 <b>high-port UDP works, but the target is silent.</b>")
            lines.append("STUN answered on 19302/3478, so this host does NOT block UDP on SA-MP's port "
                         "range and the return path is fine. The target is dropping us specifically: "
                         "it firewalls hosting/datacenter IPs, or the ip/port is wrong, or it's offline. "
                         "Your home IP works because it isn't in a hosting range.")
            if res["egress_ip"]:
                lines.append(f"Give the server owner this IP to whitelist: <code>{html.escape(res['egress_ip'])}</code>.")
        elif res["dns_ok"] and res["ntp_ok"]:
            lines.append("🔴 <b>only low ports (53/123) get through — high-port UDP is filtered.</b>")
            lines.append("DNS and NTP answer but every STUN server on 19302/3478 is silent. That is a host "
                         "egress rule, not the game server: SA-MP needs UDP on 7777 and it never leaves. "
                         "Send support this exact result and ask them to open outbound UDP to arbitrary "
                         "high ports (test case: STUN binding request to stun.l.google.com:19302).")
        elif res["dns_ok"]:
            lines.append("🔴 <b>only DNS (53) works</b> — NTP, STUN and SA-MP are all silent.")
            lines.append("The host permits DNS UDP only. Ask support to open outbound UDP generally; "
                         "test case: STUN to stun.l.google.com:19302.")
        else:
            lines.append("🔴 <b>no UDP return anywhere</b> — DNS, NTP, STUN and SA-MP all silent.")
            lines.append("Packets leave but replies never come back (or egress is blocked). This contradicts "
                         "support's 'UDP is open' — send them this exact result: a DNS query to 8.8.8.8:53 gets "
                         "no reply, so the UDP return path is being dropped.")
        await message.answer("\n".join(lines))

    @r.message(Command("selftest"))
    async def h_selftest(message: Message):
        """Prove the 0.3.7 handshake on a live public server (read-only)."""
        await message.answer(
            "selftest: walking the real 0.3.7 cookie exchange against live public "
            "SA-MP servers (does not touch your instance)…"
        )
        res = await selftest(timeout=3.0)
        lines = []
        for t in res["tried"]:
            head = f"<b>{html.escape(t['host'])}:{t['port']}</b>"
            if t["info"] is None:
                lines.append(f"🔴 {head} — silent ({html.escape(t['query_error'] or 'no reply')})")
                continue
            info = t["info"]
            lines.append(f"🟢 {head} — {html.escape(str(info.get('hostname', '?')))} "
                         f"({info.get('players', '?')}/{info.get('maxplayers', '?')})")
            for label, sent, got in t["steps"]:
                mark = "🟢" if got else "🔴"
                lines.append(f"   {mark} {html.escape(label)}: "
                             f"<code>{sent.hex(' ')}</code> → "
                             f"<code>{got.hex(' ') if got else 'no reply'}</code>")
        lines.append("")
        if res["verified"]:
            lines.append("🟢 <b>client protocol verified on live traffic.</b>")
            lines.append("A real public server accepted our encoded open-connection request and "
                         "returned ID_OPEN_CONNECTION_REPLY (25). The 0.3.7 encoding, cookie "
                         "0x6969 answer and wire ids are correct against a real server, not just "
                         "a mock. If your target stays silent, it is dropping this container's IP.")
            lines.append("To see the full join with the real binary: "
                         "<code>/connect &lt;that ip&gt; &lt;port&gt; Nick</code>.")
        elif res["reachable"]:
            lines.append("🟡 <b>a live server answers queries but not the game handshake.</b>")
            lines.append("UDP and the query protocol work. The play connection is filtered for this "
                         "IP (common on public servers), so this cannot confirm the handshake. "
                         "Try /selftest again later or /connect to a server you control.")
        else:
            lines.append("🔴 <b>no reference server answered at all.</b>")
            lines.append("They may be down or all filter hosting IPs. Run /nettest — if STUN is green "
                         "there, egress is fine and this is target-side filtering.")
        await message.answer("\n".join(lines))

    @r.message(Command("myip"))
    async def h_myip(message: Message):
        """The egress IP the outside world sees — what a game server would firewall."""
        await message.answer("myip: asking STUN servers over UDP…")
        res = await nettest("127.0.0.1", 7777, timeout=3.0)
        lines = []
        for (h, p), mapped in res["stun"]:
            lines.append(f"{'🟢' if mapped else '🔴'} {h}:{p}"
                         + (f" → {html.escape(mapped)}" if mapped else ""))
        if res["egress_ip"]:
            lines.append(f"\n<b>egress IP:</b> <code>{html.escape(res['egress_ip'])}</code>")
            lines.append("This is the address a game server sees. If it belongs to a hosting range, "
                         "an anti-hosting firewall will drop it while your home IP works.")
        else:
            lines.append("\n🔴 no STUN answer — high-port UDP is not getting through (see /nettest).")
        await message.answer("\n".join(lines))

    @r.message(Command("diag"))
    async def h_diag(message: Message, command: CommandObject):
        args = (command.args or "").split()
        if len(args) >= 2:
            addr, port = args[0], args[1]
        else:
            addr = sup.cfg.data["server"]["addr"]
            port = str(sup.cfg.data["server"]["port"])
        if not port.isdigit():
            await message.answer("usage: /diag [ip] [port]")
            return
        await message.answer(
            f"diag: walking the 0.3.7 handshake with <code>{html.escape(addr)}:{port}</code> "
            "(query + raw connect packets, up to ~15 s)…"
        )
        res = await diag(addr, int(port))
        lines = [f"<b>diag {html.escape(addr)}:{port}</b>"]
        if res["resolve_error"]:
            lines.append(f"🔴 DNS: {html.escape(res['resolve_error'])}")
            await message.answer("\n".join(lines))
            return
        lines.append(f"resolved: <code>{res['resolved']}</code>")
        if res["info"]:
            i = res["info"]
            lines.append(
                f"🟢 query: {html.escape(i.get('hostname', '?'))} "
                f"({i.get('players', '?')}/{i.get('maxplayers', '?')})"
            )
        else:
            lines.append(f"🔴 query silent ({html.escape(res['query_error'] or 'timeout')})")
        lines.append("<b>handshake:</b>")
        if res["handshake_error"]:
            lines.append(f"🔴 {html.escape(res['handshake_error'])}")
        for label, sent, got in res["steps"]:
            if got is None:
                lines.append(f"🔴 {html.escape(label)}: <code>{sent.hex(' ')}</code> → no reply")
            else:
                lines.append(
                    f"🟢 {html.escape(label)}: <code>{sent.hex(' ')}</code> → <code>{got.hex(' ')}</code>"
                )
        accepted = any(g and g[0] == 25 for _, _, g in res["steps"])   # ID_OPEN_CONNECTION_REPLY
        refused = any(g and g[0] == 29 for _, _, g in res["steps"])    # ID_CONNECTION_ATTEMPT_FAILED
        full = any(g and g[0] == 31 for _, _, g in res["steps"])       # ID_NO_FREE_INCOMING_CONNECTIONS
        cookie = any(g and g[0] == 26 for _, _, g in res["steps"])     # ID_OPEN_CONNECTION_COOKIE
        any_reply = any(g for _, _, g in res["steps"])
        lines.append("")
        if accepted:
            lines.append("🟢 <b>handshake accepted</b> — the server lets this IP connect. "
                         "If /connect still fails, the problem is inside the client — send me this output.")
        elif full:
            lines.append("🟡 <b>server is full</b> (no free slots) — this IP is not filtered.")
        elif refused:
            lines.append("🔴 <b>server actively refuses</b> this IP (ban / anti-DDoS filter).")
        elif cookie:
            lines.append("🟡 <b>cookie challenge seen, answer not accepted</b> — the server sees us "
                         "but drops the handshake. Send me this output.")
        elif any_reply:
            lines.append("🟡 <b>server replies, but not with a handshake</b> — send me this output.")
        elif res["info"]:
            lines.append("🟡 <b>query answers, game handshake silent</b> — the server allows queries "
                         "but filters play connections from this IP (anti-DDoS).")
        else:
            lines.append("🔴 <b>fully silent</b> — wrong port, server offline, or it drops this IP.")
            project = identify(res["resolved"] or addr, int(port))
            if project:
                lines.append(f"⚠️ <b>{html.escape(project.name)}</b> — a mobile-CRMP project played "
                             "through its own launcher, not a stock SA-MP client. Its servers do not "
                             "answer a vanilla 0.3.7 open-connection request.")
                lines.append(f"Run <code>/project {html.escape(addr)} {port}</code> for the details "
                             "and a side-by-side probe against a vanilla server.")
            else:
                lines.append(f"Check the port first: <code>/findport {html.escape(addr)}</code> "
                             "probes the common SA-MP ports and shows which one actually answers. "
                             "A wrong port looks exactly like an IP block.")
        await message.answer("\n".join(lines))

    @r.message(Command("netdebug"))
    async def h_netdebug(message: Message, command: CommandObject):
        """Toggle the client's handshake trace (packet ids, cookie, connection request)."""
        arg = (command.args or "").strip().lower()
        if arg not in ("on", "off"):
            state = "on" if sup.cfg.data.get("netdebug", 0) else "off"
            await message.answer(f"netdebug is <b>{state}</b>\nusage: /netdebug on|off")
            return
        sup.cfg.data["netdebug"] = 1 if arg == "on" else 0
        sup.cfg.save()
        # the flag is read from RakSAMPClient.xml at startup, so a restart applies it
        res = await sup.restart()
        await message.answer(
            f"netdebug <b>{arg}</b> — {html.escape(str(res))}\n"
            + ("Now /connect and then /logs 60: you'll see <code>[net] recv … id=0x..</code>, "
               "<code>[net] cookie challenge=… -> answer=…</code> and "
               "<code>[net] open-connection-reply -> sending connection-request</code>. "
               "That shows exactly which step the server stops answering."
               if arg == "on" else "Handshake trace off.")
        )

    @r.message(Command("project"))
    async def h_project(message: Message, command: CommandObject):
        """Identify a known mobile-CRMP project and compare it with vanilla SA-MP."""
        args = (command.args or "").split()
        if args:
            addr = args[0]
            port = args[1] if len(args) > 1 else str(sup.cfg.data["server"]["port"])
        else:
            addr = sup.cfg.data["server"]["addr"]
            port = str(sup.cfg.data["server"]["port"])
        if not port.isdigit():
            await message.answer("usage: /project [ip] [port]")
            return
        try:
            resolved = socket.gethostbyname(addr)
        except OSError as e:
            await message.answer(f"🔴 DNS: {html.escape(str(e))}")
            return
        project = identify(resolved, int(port))
        if not project:
            await message.answer(
                f"<code>{html.escape(resolved)}:{port}</code> is not a known mobile-CRMP project.\n"
                "Use /diag for the handshake and /findport to locate the port."
            )
            return

        await message.answer(
            f"project: <b>{html.escape(project.name)}</b> — probing the target, "
            f"{len(project.siblings)} sibling servers and vanilla SA-MP controls…"
        )
        res = await compare(resolved, int(port), project.siblings, timeout=2.5)
        lines = [f"<b>{html.escape(project.name)}</b> — <code>{html.escape(resolved)}:{port}</code>",
                 f"join version: <code>{project.join_version}</code> "
                 f"(vanilla 0.3.7 uses <code>{VANILLA_JOIN_VERSION}</code>)", ""]
        for r in res["results"]:
            mark = "🟢" if r["any_reply"] else "🔴"
            label = {"target": "target", "sibling": "sibling", "control": "vanilla control"}[r["role"]]
            extra = ""
            if r["info"]:
                extra = f" — {html.escape(str(r['info'].get('hostname', '?')))}"
            elif r["accepted"]:
                extra = " — handshake accepted"
            elif r["cookie"]:
                extra = " — cookie challenge seen"
            elif r["unreachable"]:
                extra = " — ICMP port-unreachable: host alive, nothing on this port"
            elif r["handshake_error"] or r["query_error"]:
                extra = f" — {html.escape(r['handshake_error'] or r['query_error'])} (no answer)"
            lines.append(f"{mark} {label} <code>{html.escape(r['host'])}:{r['port']}</code>{extra}")
            # raw bytes for anything that answered: shows exactly where the
            # exchange stalls instead of leaving it to guesswork
            for step_label, sent, got in r.get("steps", []):
                lines.append(f"     {html.escape(step_label)}: "
                             f"<code>{sent.hex(' ')}</code> → "
                             f"<code>{got.hex(' ') if got else 'no reply'}</code>")
        lines.append("")
        if res["project_replies"]:
            lines.append("🟢 This project does answer us — the join layer is the next thing to look at.")
        elif res["control_ok"]:
            lines.append("🔴 <b>every server of this project is silent, while vanilla SA-MP answers "
                         "from the same container.</b>")
            lines.append("So egress, UDP and our 0.3.7 encoding are fine. This project's servers do not "
                         "accept a stock client at all — the drop happens before any version field is "
                         "sent, at the first open-connection request.")
        else:
            lines.append("🟡 Nothing answered, including the vanilla controls — run /nettest; "
                         "the controls may be down right now.")
        lines.append("")
        lines.append("<b>What this project requires:</b>")
        for note in project.notes:
            lines.append(f"• {html.escape(note)}")
        lines.append("")
        lines.append("Sources: " + " ".join(
            f'<a href="{html.escape(s)}">{html.escape(s.split("//")[1].split("/")[0])}</a>'
            for s in project.sources))
        await message.answer("\n".join(lines), disable_web_page_preview=True)

    @r.message(Command("findport"))
    async def h_findport(message: Message, command: CommandObject):
        """Find the UDP port a host actually answers SA-MP on."""
        args = (command.args or "").split()
        if not args:
            await message.answer("usage: /findport <ip> [port ...]")
            return
        addr = args[0]
        ports = None
        if len(args) > 1:
            if not all(a.isdigit() and 0 < int(a) < 65536 for a in args[1:]):
                await message.answer("ports must be numbers in 1..65535")
                return
            ports = tuple(int(a) for a in args[1:])
        shown = ports or COMMON_SAMP_PORTS
        await message.answer(
            f"findport: probing {len(shown)} UDP ports on <code>{html.escape(addr)}</code>…"
        )
        res = await findport(addr, ports, timeout=2.0)
        if res["resolve_error"]:
            await message.answer(f"🔴 DNS: {html.escape(res['resolve_error'])}")
            return
        lines = [f"<b>findport {html.escape(addr)}</b> → <code>{res['resolved']}</code>"]
        if not res["answering"]:
            lines.append(f"🔴 nothing answered on: {', '.join(str(p) for p in shown)}")
            lines.append("Either the server is offline, or it uses a port outside this list — "
                         "pass it explicitly: <code>/findport &lt;ip&gt; &lt;port&gt;</code>. "
                         "If you know the port and it is still silent here, then it is filtering us.")
        else:
            for r in res["answering"]:
                i = r["info"]
                mark = "🟢" if r["accepted"] else "🟡"
                lines.append(
                    f"{mark} <b>:{r['port']}</b> — {html.escape(str(i.get('hostname', '?')))} "
                    f"({i.get('players', '?')}/{i.get('maxplayers', '?')})"
                    + (" — handshake accepted, joinable" if r["accepted"]
                       else " — query answers, handshake did not complete")
                )
            lines.append("")
            if res["joinable"]:
                best = res["joinable"][0]["port"]
                lines.append(f"Use <code>/connect {html.escape(addr)} {best} Nick</code>.")
            else:
                lines.append("Query answers but no handshake completed — send me this output.")
        await message.answer("\n".join(lines))

    @r.message(Command("tunnel"))
    async def h_tunnel(message: Message):
        if not sup.tunnel:
            await message.answer(
                "tunnel: <b>off</b>\nSet <code>TUNNEL_RELAY=host:port</code> and "
                "<code>TUNNEL_TOKEN=...</code> (matching a relay/relay.py on a VPS with open UDP) "
                "to carry SA-MP traffic over TCP when the host blocks UDP."
            )
            return
        st = sup.tunnel.status()
        icon = "🟢" if st["relay_connected"] else "🔴"
        await message.answer(
            f"{icon} <b>tunnel</b> (UDP-over-TCP)\n"
            f"relay: <code>{html.escape(st['relay'])}</code>  connected: <b>{st['relay_connected']}</b>\n"
            f"target: <code>{html.escape(st['target'] or '-')}</code>\n"
            f"local proxy: <code>{st['local']}</code>\n"
            f"bytes up/down: {st['bytes_up']}/{st['bytes_down']}\n"
            f"last error: {html.escape(st['last_error'] or '-')}"
        )

    return r


def make_broadcast(bot: Bot):
    async def broadcast(chat_id: int, text: str):
        await bot.send_message(chat_id, _code(text))
    return broadcast
