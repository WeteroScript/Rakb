#!/usr/bin/env python3
"""/selftest logic regression test.

/selftest exists to rule out "our client encoding is wrong" on live traffic when
the real target is silent. Public servers are unreachable from CI, so this drives
the real selftest() coroutine against local mock servers:

  * a reachable server that completes the cookie exchange -> verified
  * a silent server is skipped, not reported as a protocol failure
  * a server that answers queries but not the handshake -> reachable, not verified
  * the running instance/config is never touched

Run: python3 tests/test_selftest.py
"""
from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tgbot import sampquery                                    # noqa: E402
from test_samp037_protocol import MockServer, free_port         # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        _FAILURES.append(name)


def closed_port() -> int:
    """A port with nothing listening: bind, note it, close."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class QueryOnlyServer(MockServer):
    """Answers the SAMP query but drops the game handshake."""

    def _step(self, plain: bytes) -> None:  # noqa: D102 - intentionally inert
        return


def run_with(refs) -> dict:
    original = sampquery.REFERENCE_SERVERS
    sampquery.REFERENCE_SERVERS = refs
    try:
        return asyncio.run(sampquery.selftest(timeout=1.5))
    finally:
        sampquery.REFERENCE_SERVERS = original


def main() -> int:
    # 1. healthy server: query + full cookie exchange
    port = free_port()
    srv = MockServer(port, full=False, timeout=8)
    res = run_with((("127.0.0.1", port),))
    srv.thread.join(timeout=8)
    check("healthy server -> verified", res["verified"] is True)
    check("healthy server -> reachable listed", len(res["reachable"]) == 1)
    check("query info parsed", bool(res["reachable"])
          and res["reachable"][0]["info"]["hostname"] == "Mock 0.3.7 Server",
          str(res["reachable"][0]["info"]) if res["reachable"] else "none")
    check("handshake steps recorded", bool(res["tried"][0]["steps"]),
          str(len(res["tried"][0]["steps"])))

    # 2. silent server first, healthy second: the silent one must be skipped
    dead = closed_port()
    port2 = free_port()
    srv2 = MockServer(port2, full=False, timeout=8)
    res2 = run_with((("127.0.0.1", dead), ("127.0.0.1", port2)))
    srv2.thread.join(timeout=8)
    check("silent server skipped, next one verified", res2["verified"] is True)
    check("silent server reported without info", res2["tried"][0]["info"] is None)
    check("both servers tried", len(res2["tried"]) == 2, str(len(res2["tried"])))

    # 3. query answers but handshake does not -> reachable, NOT verified
    port3 = free_port()
    srv3 = QueryOnlyServer(port3, full=False, timeout=8)
    res3 = run_with((("127.0.0.1", port3),))
    srv3.thread.join(timeout=8)
    check("query-only server -> not verified", res3["verified"] is False)
    check("query-only server -> still reachable", len(res3["reachable"]) == 1)

    # 4. all silent -> neither verified nor reachable
    res4 = run_with((("127.0.0.1", closed_port()),))
    check("all silent -> not verified", res4["verified"] is False)
    check("all silent -> nothing reachable", res4["reachable"] == [])

    if _FAILURES:
        print(f"\n{len(_FAILURES)} CHECK(S) FAILED: " + ", ".join(_FAILURES))
        return 1
    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
