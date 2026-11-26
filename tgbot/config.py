"""Environment config, persistent instance config, and RakSAMPClient.xml generation.

The RakSAMP client reads a fully-populated RakSAMPClient.xml from its working
directory. We keep the authoritative instance config as JSON in the persistent
data dir and render the XML from it on every (re)start, so the bot survives
BotHost redeploys (only /app/data persists).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


@dataclass
class Settings:
    bot_token: str = field(default_factory=lambda: os.environ.get("BOT_TOKEN", "").strip())
    admin_ids: tuple[int, ...] = field(default_factory=tuple)
    port: int = field(default_factory=lambda: _env_int("PORT", 8080))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", "/app/data")))
    raksamp_bin: str = field(default_factory=lambda: os.environ.get("RAKSAMP_BIN", "/opt/rakb/bin/raksamp"))
    autostart: bool = field(default_factory=lambda: os.environ.get("AUTOSTART", "").lower() in ("1", "true", "yes"))

    @classmethod
    def from_env(cls) -> "Settings":
        raw = os.environ.get("ADMIN_IDS", "").replace(";", ",")
        admins = tuple(int(x) for x in (p.strip() for p in raw.split(",")) if x.lstrip("-").isdigit())
        s = cls(admin_ids=admins)
        s.data_dir.mkdir(parents=True, exist_ok=True)
        return s

    def validate(self) -> None:
        if not self.bot_token:
            raise SystemExit("BOT_TOKEN is not set (configure it in the BotHost env panel).")
        if not self.admin_ids:
            raise SystemExit("ADMIN_IDS is not set (comma-separated Telegram user IDs).")


# Authoritative, JSON-serialisable instance config. Defaults mirror the upstream
# RakSAMPClient.xml so the client always gets a complete, valid document.
DEFAULT_CONFIG: dict = {
    "server": {"addr": "127.0.0.1", "port": 7777, "nickname": "RakBot", "password": ""},
    "runmode": 2,                 # 0 rcon, 1 bare, 2 still, 3 normal, 4 follow, 5 follow+veh
    "autorun": 0,
    "find": 0,
    "class_id": 0,
    "manual_spawn": 0,
    "print_timestamps": 1,
    "updatestats": 1,
    "minfps": 20,
    "maxfps": 90,
    "clientversion": "0.3.7",
    "chatcolor_rgb": [0, 0, 130],
    "clientmsg_rgb": [0, 130, 0],
    "cpalert_rgb": [170, 0, 0],
    "followplayer": "",
    "followplayerwithvehicleid": 0,
    "followXOffset": 3.0,
    "followYOffset": 0.0,
    "followZOffset": 0.0,
    "intervals": {"spam": 150, "fakekill": 35, "lag": 20, "joinflood": 50,
                  "chatflood": 20, "classflood": 30, "bulletflood": 25},
    "log": {"objects": 0, "pickups": 0, "textlabels": 0, "textdraws": 0},
    "sendrates": {"force": 0, "onfoot": 40, "incar": 40, "firing": 40, "multiplier": 1},
    "normal_pos": {"position": [325.35, 2512.09, 16.56], "rotation": 0.0, "force": 0},
    "teleports": [
        {"name": "Grove Street", "position": [2536.08, -1632.98, 13.79]},
        {"name": "LS Hospital", "position": [2033.00, -1416.02, 16.99]},
    ],
    "autorun_cmds": [],
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class InstanceConfig:
    """Loads/saves the instance config JSON and renders RakSAMPClient.xml."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "instance.json"
        self.data = deep_merge(DEFAULT_CONFIG, self._load())

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    def set_server(self, addr: str, port: int, nickname: str | None = None,
                   password: str | None = None) -> None:
        self.data["server"]["addr"] = addr
        self.data["server"]["port"] = int(port)
        if nickname is not None:
            self.data["server"]["nickname"] = nickname
        if password is not None:
            self.data["server"]["password"] = password
        self.save()

    def render_xml(self) -> str:
        d = self.data
        srv = d["server"]
        iv = d["intervals"]
        lg = d["log"]
        sr = d["sendrates"]
        np = d["normal_pos"]
        rgb = lambda c: f"{int(c[0])} {int(c[1])} {int(c[2])}"
        pos = lambda p: f"{p[0]} {p[1]} {p[2]}"

        lines = [
            '<RakSAMPClient console="1" runmode="%d" autorun="%d" find="%d" select_classid="%d" manual_spawn="%d"'
            % (d["runmode"], d["autorun"], d["find"], d["class_id"], d["manual_spawn"]),
            '               print_timestamps="%d" chatcolor_rgb="%s" clientmsg_rgb="%s" cpalert_rgb="%s"'
            % (d["print_timestamps"], rgb(d["chatcolor_rgb"]), rgb(d["clientmsg_rgb"]), rgb(d["cpalert_rgb"])),
            '               followplayer=%s followplayerwithvehicleid="%d" followXOffset="%s" followYOffset="%s" followZOffset="%s"'
            % (quoteattr(str(d["followplayer"])), d["followplayerwithvehicleid"],
               d["followXOffset"], d["followYOffset"], d["followZOffset"]),
            '               updatestats="%d" minfps="%d" maxfps="%d" clientversion=%s>'
            % (d["updatestats"], d["minfps"], d["maxfps"], quoteattr(str(d["clientversion"]))),
            "",
            "\t<server nickname=%s password=%s>%s:%d</server>"
            % (quoteattr(str(srv["nickname"])), quoteattr(str(srv["password"])),
               escape(str(srv["addr"])), int(srv["port"])),
            "",
            '\t<intervals spam="%d" fakekill="%d" lag="%d" joinflood="%d" chatflood="%d" classflood="%d" bulletflood="%d" />'
            % (iv["spam"], iv["fakekill"], iv["lag"], iv["joinflood"], iv["chatflood"], iv["classflood"], iv["bulletflood"]),
            '\t<log objects="%d" pickups="%d" textlabels="%d" textdraws="%d" />'
            % (lg["objects"], lg["pickups"], lg["textlabels"], lg["textdraws"]),
            '\t<sendrates force="%d" onfoot="%d" incar="%d" firing="%d" multiplier="%d" />'
            % (sr["force"], sr["onfoot"], sr["incar"], sr["firing"], sr["multiplier"]),
            '\t<normal_pos position="%s" rotation="%s" force="%d" />'
            % (pos(np["position"]), np["rotation"], np["force"]),
            "",
        ]
        for cmd in d.get("autorun_cmds", []):
            lines.append("\t<autorun>%s</autorun>" % escape(str(cmd)))
        for tp in d.get("teleports", []):
            lines.append("\t<teleport name=%s position=\"%s\" />"
                         % (quoteattr(str(tp["name"])), pos(tp["position"])))
        lines.append("")
        lines.append("</RakSAMPClient>")
        return "\n".join(lines) + "\n"

    def write_xml(self, run_dir: Path) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "RakSAMPClient.xml").write_text(self.render_xml(), encoding="utf-8")
