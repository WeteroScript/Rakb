#!/usr/bin/env python3
"""Handshake trace (/netdebug) regression test.

The stock client only printed "Got packet on port N", which cannot show where a
join stalls. With netdebug=1 it prints the packet id of every datagram received,
the cookie challenge and our answer, and the moment it sends the connection
request. With netdebug=0 it must print nothing.

Run: RAKSAMP_BIN=/path/to/raksamp python3 tests/test_netdebug.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tgbot.config import InstanceConfig                       # noqa: E402
from test_samp037_protocol import MockServer, free_port        # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        _FAILURES.append(name)


def run(binary: Path, flag: int) -> list[str]:
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="rakb-netdbg-") as tmp:
        run_dir = Path(tmp) / "run"
        run_dir.mkdir()
        cfg = InstanceConfig(Path(tmp) / "data")
        cfg.set_server("127.0.0.1", port, "TraceTest")
        cfg.data["netdebug"] = flag
        cfg.save()
        xml = cfg.render_xml()
        check(f"netdebug={flag} rendered into the XML", f'netdebug="{flag}"' in xml)
        (run_dir / "RakSAMPClient.xml").write_text(xml, encoding="utf-8")

        srv = MockServer(port, full=True, timeout=12)
        time.sleep(0.2)
        proc = subprocess.Popen([str(binary)], cwd=run_dir, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, env=dict(os.environ))
        try:
            srv.thread.join(timeout=20)
            time.sleep(0.3)
        finally:
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
    return [l for l in out.splitlines() if l.startswith("[net]")]


def main() -> int:
    arg = os.environ.get("RAKSAMP_BIN", "")
    binary = Path(arg) if arg else REPO_ROOT / "build" / "bin" / "raksamp"
    if not binary.is_file():
        print(f"raksamp binary not found: {binary}\nPass RAKSAMP_BIN=/path/to/raksamp.")
        return 2

    on = run(binary, 1)
    joined = "\n".join(on)
    check("trace produced when on", len(on) >= 5, f"{len(on)} lines")
    check("outgoing request traced with its bytes",
          "send open-connection-request" in joined and "18 00 00" in joined)
    check("received datagrams traced with packet id", "id=0x1A" in joined, joined[:200])
    check("cookie challenge and answer traced",
          "cookie challenge=0x1234" in joined and "answer=0x7B5D" in joined)
    check("open-connection-reply step traced",
          "open-connection-reply -> sending connection-request" in joined)

    off = run(binary, 0)
    check("no trace when off", off == [], f"{len(off)} lines")

    if _FAILURES:
        print(f"\n{len(_FAILURES)} CHECK(S) FAILED: " + ", ".join(_FAILURES))
        return 1
    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
