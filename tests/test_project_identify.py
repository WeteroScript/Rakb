#!/usr/bin/env python3
"""Project identification + comparative probe regression test.

A mobile-CRMP project that only accepts its own launcher answers nothing to a
stock 0.3.7 open-connection request, which is indistinguishable from a wrong port
or an IP block. identify() names the project, and compare() probes it next to
vanilla controls so the silence can be attributed correctly.

Run: python3 tests/test_project_identify.py
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
from tgbot.projects import (BLACK_RUSSIA, VANILLA_JOIN_VERSION,  # noqa: E402
                            identify)
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


def main() -> int:
    # --- identification -------------------------------------------------
    check("MAGADAN identified", identify("80.66.82.249", 5125) is BLACK_RUSSIA)
    check("RED identified", identify("80.66.82.46", 5125) is BLACK_RUSSIA)
    check("Barvikha range identified", identify("80.66.71.10", 5125) is BLACK_RUSSIA)
    check("wrong port not matched", identify("80.66.82.249", 7777) is None)
    check("port omitted still matches", identify("80.66.82.249") is BLACK_RUSSIA)
    check("unrelated ip not matched", identify("46.39.225.193", 7778) is None)
    check("adjacent network not matched", identify("80.66.83.249", 5125) is None)
    check("hostname is not an ip -> no match", identify("example.com", 5125) is None)
    check("join version differs from vanilla",
          BLACK_RUSSIA.join_version == 24342 and VANILLA_JOIN_VERSION == 4057)
    check("every source is an https url",
          all(s.startswith("https://") for s in BLACK_RUSSIA.sources))

    # --- comparative probe ---------------------------------------------
    # target silent, one vanilla control alive -> project-specific silence
    live = free_port()
    srv = MockServer(live, full=False, timeout=10)
    original = sampquery.REFERENCE_SERVERS
    sampquery.REFERENCE_SERVERS = (("127.0.0.1", live),)
    try:
        dead_target = closed_port()
        res = asyncio.run(sampquery.compare("127.0.0.1", dead_target, ("127.0.0.1",),
                                            timeout=1.5))
    finally:
        sampquery.REFERENCE_SERVERS = original
    srv.thread.join(timeout=10)

    check("target role first", res["target"]["role"] == "target")
    check("silent target has no reply", res["target"]["any_reply"] is False)
    check("sibling probed", len(res["siblings"]) == 1)
    check("control answered", res["control_ok"] is True)
    check("project silent while control answers", res["project_replies"] is False)

    # target alive -> project_replies True
    live2 = free_port()
    srv2 = MockServer(live2, full=False, timeout=10)
    sampquery.REFERENCE_SERVERS = (("127.0.0.1", closed_port()),)
    try:
        res2 = asyncio.run(sampquery.compare("127.0.0.1", live2, (), timeout=1.5))
    finally:
        sampquery.REFERENCE_SERVERS = original
    srv2.thread.join(timeout=10)
    check("answering target -> project_replies", res2["project_replies"] is True)
    check("answering target accepted handshake", res2["target"]["accepted"] is True)
    check("raw handshake steps carried for the bot output",
          len(res2["target"]["steps"]) >= 2
          and all(len(item) == 3 for item in res2["target"]["steps"]),
          str(len(res2["target"]["steps"])))
    # a closed local port answers with ICMP unreachable, which must be reported
    # as such rather than lumped in with a filtered/timeout silence
    check("silent target reports why it is silent",
          bool(res["target"]["handshake_error"] or res["target"]["query_error"]
               or res["target"]["steps"]),
          f"query={res['target']['query_error']} hs={res['target']['handshake_error']}")
    check("closed port flagged as ICMP unreachable", res["target"]["unreachable"] is True,
          f"query={res['target']['query_error']} hs={res['target']['handshake_error']}")
    check("answering server not flagged unreachable", res2["target"]["unreachable"] is False)
    check("all controls dead -> control_ok False", res2["control_ok"] is False)

    if _FAILURES:
        print(f"\n{len(_FAILURES)} CHECK(S) FAILED: " + ", ".join(_FAILURES))
        return 1
    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
