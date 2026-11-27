#!/usr/bin/env python3
"""/findport logic regression test.

A wrong port is indistinguishable from an IP block: every packet goes unanswered.
/findport probes the common SA-MP ports so that case is resolved with evidence.
Public hosts are unreachable from CI, so this drives the real findport() coroutine
against local mock servers on non-default ports.

Run: python3 tests/test_findport.py
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
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class QueryOnlyServer(MockServer):
    """Answers the SAMP query but never completes the game handshake."""

    def _step(self, plain: bytes) -> None:
        return


def main() -> int:
    # a live server on a NON-default port, plus two dead ports
    live = free_port()
    dead1, dead2 = closed_port(), closed_port()
    srv = MockServer(live, full=False, timeout=10)
    res = asyncio.run(sampquery.findport("127.0.0.1", (dead1, live, dead2), timeout=1.5))
    srv.thread.join(timeout=10)

    check("resolves the host", res["resolved"] == "127.0.0.1", str(res["resolved"]))
    check("all requested ports probed", len(res["results"]) == 3, str(len(res["results"])))
    check("only the live port answers",
          [r["port"] for r in res["answering"]] == [live],
          str([r["port"] for r in res["answering"]]))
    check("live port reported joinable",
          [r["port"] for r in res["joinable"]] == [live],
          str([r["port"] for r in res["joinable"]]))
    check("hostname parsed on the found port",
          res["answering"][0]["info"]["hostname"] == "Mock 0.3.7 Server")
    check("dead ports carry no info",
          all(r["info"] is None for r in res["results"] if r["port"] != live))

    # query-only server: answering, but NOT joinable
    qonly = free_port()
    srv2 = QueryOnlyServer(qonly, full=False, timeout=10)
    res2 = asyncio.run(sampquery.findport("127.0.0.1", (qonly,), timeout=1.5))
    srv2.thread.join(timeout=10)
    check("query-only port answers", len(res2["answering"]) == 1)
    check("query-only port not joinable", res2["joinable"] == [])

    # nothing listening at all
    res3 = asyncio.run(sampquery.findport("127.0.0.1", (closed_port(),), timeout=1.0))
    check("all dead -> nothing answering", res3["answering"] == [])
    check("all dead -> nothing joinable", res3["joinable"] == [])

    # the default list must contain both the stock port and the one that bit us
    check("default list covers 7777 and 5125",
          7777 in sampquery.COMMON_SAMP_PORTS and 5125 in sampquery.COMMON_SAMP_PORTS)

    # bad hostname is reported, not raised
    res4 = asyncio.run(sampquery.findport("no-such-host.invalid", (7777,), timeout=1.0))
    check("DNS failure reported", bool(res4["resolve_error"]), str(res4["resolve_error"]))

    if _FAILURES:
        print(f"\n{len(_FAILURES)} CHECK(S) FAILED: " + ", ".join(_FAILURES))
        return 1
    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
