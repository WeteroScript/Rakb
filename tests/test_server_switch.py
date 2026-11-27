#!/usr/bin/env python3
"""Server-switch password handling regression test.

The password travels inside ID_CONNECTION_REQUEST. Carrying one server's password
over to the next makes a server that expects none drop the request, which looks
exactly like a network failure - the client gets ID_OPEN_CONNECTION_REPLY, sends
the connection request, and hears nothing back.

These checks cover the config layer the /connect handler drives:
  * switching target without a password clears it
  * an explicit password on the new target is kept
  * reconnecting to the same target keeps the password
  * "-" clears it explicitly
  * the cleared value reaches RakSAMPClient.xml

Run: python3 tests/test_server_switch.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tgbot.config import InstanceConfig  # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        _FAILURES.append(name)


def apply_connect(cfg: InstanceConfig, addr: str, port: int,
                  nick: str | None, pw: str | None) -> None:
    """Mirror of the /connect handler's password rules."""
    if pw == "-":
        pw = ""
    prev = cfg.data["server"]
    target_changed = addr != prev["addr"] or int(port) != int(prev["port"])
    if pw is None and target_changed:
        pw = ""
    cfg.set_server(addr, int(port), nick, pw)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rakb-switch-") as tmp:
        cfg = InstanceConfig(Path(tmp))

        # first target with a password (the Black Russia case)
        apply_connect(cfg, "80.66.82.249", 5125, "Fuugf_Tyyg", "66666666")
        check("password stored for first target",
              cfg.data["server"]["password"] == "66666666")

        # switch to a different server, no password given -> must be cleared
        apply_connect(cfg, "46.39.225.193", 7778, "Nick", None)
        check("switching target clears the old password",
              cfg.data["server"]["password"] == "",
              repr(cfg.data["server"]["password"]))
        check("cleared password reaches the XML",
              'password=""' in cfg.render_xml(), "")

        # same target, no password given -> keep it
        apply_connect(cfg, "46.39.225.193", 7778, "Nick", "secret")
        apply_connect(cfg, "46.39.225.193", 7778, "Nick", None)
        check("same target keeps the password",
              cfg.data["server"]["password"] == "secret")

        # port-only change is still a different server
        apply_connect(cfg, "46.39.225.193", 7779, "Nick", None)
        check("port change also clears the password",
              cfg.data["server"]["password"] == "")

        # explicit password on a new target is kept
        apply_connect(cfg, "1.2.3.4", 7777, "Nick", "pw2")
        check("explicit password on new target kept",
              cfg.data["server"]["password"] == "pw2")

        # "-" clears explicitly on the same target
        apply_connect(cfg, "1.2.3.4", 7777, "Nick", "-")
        check('"-" clears the password explicitly',
              cfg.data["server"]["password"] == "")

        # nickname is untouched when not supplied
        apply_connect(cfg, "1.2.3.4", 7777, None, None)
        check("nickname preserved when omitted",
              cfg.data["server"]["nickname"] == "Nick")

        # a password with the trailing NUL the client sends is still just the string
        apply_connect(cfg, "5.6.7.8", 7777, "Nick", "66666666")
        check("password length is the visible length",
              len(cfg.data["server"]["password"]) == 8)

    if _FAILURES:
        print(f"\n{len(_FAILURES)} CHECK(S) FAILED: " + ", ".join(_FAILURES))
        return 1
    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
