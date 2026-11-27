#!/usr/bin/env python3
"""STUN probe regression test (used by /nettest and /myip).

The sandbox and most CI runners cannot reach public STUN servers, so this spins
up local RFC 5389 responders and checks the real client code against them:

  * XOR-MAPPED-ADDRESS decoding (the address must come back un-XORed)
  * plain MAPPED-ADDRESS fallback
  * transaction-id / magic-cookie validation (a mismatched reply is rejected)
  * attribute padding, and a non-success response type
  * timeout handling on a silent port

Run: python3 tests/test_stun_probe.py
"""
from __future__ import annotations

import socket
import struct
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tgbot.sampquery import STUN_MAGIC, _stun_query_sync  # noqa: E402

MAPPED_IP = "203.0.113.45"
MAPPED_PORT = 54321

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        _FAILURES.append(name)


def build_response(tid: bytes, mode: str) -> bytes:
    addr = struct.unpack(">I", socket.inet_aton(MAPPED_IP))[0]
    if mode == "xor":
        val = struct.pack(">BBHI", 0, 0x01, MAPPED_PORT ^ (STUN_MAGIC >> 16), addr ^ STUN_MAGIC)
        atype = 0x0020
    elif mode == "plain":
        val = struct.pack(">BBHI", 0, 0x01, MAPPED_PORT, addr)
        atype = 0x0001
    elif mode == "padded":
        # a 1-byte SOFTWARE-ish attribute first, so the parser must skip padding
        pad_attr = struct.pack(">HH", 0x8022, 1) + b"X" + b"\x00" * 3
        val = struct.pack(">BBHI", 0, 0x01, MAPPED_PORT ^ (STUN_MAGIC >> 16), addr ^ STUN_MAGIC)
        attrs = pad_attr + struct.pack(">HH", 0x0020, len(val)) + val
        return struct.pack(">HHI", 0x0101, len(attrs), STUN_MAGIC) + tid + attrs
    elif mode == "badtid":
        tid = bytes(12)
        val = struct.pack(">BBHI", 0, 0x01, MAPPED_PORT ^ (STUN_MAGIC >> 16), addr ^ STUN_MAGIC)
        atype = 0x0020
    elif mode == "errortype":
        val = struct.pack(">BBHI", 0, 0x01, MAPPED_PORT ^ (STUN_MAGIC >> 16), addr ^ STUN_MAGIC)
        attrs = struct.pack(">HH", 0x0020, len(val)) + val
        return struct.pack(">HHI", 0x0111, len(attrs), STUN_MAGIC) + tid + attrs
    else:
        raise ValueError(mode)
    attrs = struct.pack(">HH", atype, len(val)) + val
    return struct.pack(">HHI", 0x0101, len(attrs), STUN_MAGIC) + tid + attrs


class StunMock:
    """One-shot UDP responder; mode='silent' never answers."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.settimeout(5)
        self.request: bytes | None = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self) -> None:
        try:
            data, addr = self.sock.recvfrom(2048)
            self.request = data
            if self.mode == "silent":
                return
            # a real Binding Request is exactly 20 bytes with the magic cookie
            if len(data) == 20 and struct.unpack(">I", data[4:8])[0] == STUN_MAGIC:
                self.sock.sendto(build_response(data[8:20], self.mode), addr)
        except (socket.timeout, OSError):
            pass
        finally:
            self.sock.close()


def probe(mode: str, timeout: float = 2.0) -> tuple[str | None, bytes | None]:
    srv = StunMock(mode)
    try:
        result = _stun_query_sync("127.0.0.1", srv.port, timeout)
    finally:
        srv.thread.join(timeout=timeout + 2)
    return result, srv.request


def main() -> int:
    ip, req = probe("xor")
    ok_req = (req is not None and len(req) == 20
              and struct.unpack(">HHI", req[:8]) == (0x0001, 0, STUN_MAGIC)
              and len(req[8:20]) == 12)
    check("request is a valid 20-byte Binding Request", ok_req,
          req.hex(" ") if req else "none")
    check("XOR-MAPPED-ADDRESS decoded", ip == MAPPED_IP, str(ip))
    check("plain MAPPED-ADDRESS fallback", probe("plain")[0] == MAPPED_IP)
    check("padded attributes skipped", probe("padded")[0] == MAPPED_IP)
    check("mismatched transaction id rejected", probe("badtid")[0] is None)
    check("non-success response rejected", probe("errortype")[0] is None)
    check("silent port times out cleanly", probe("silent", timeout=1.0)[0] is None)

    if _FAILURES:
        print(f"\n{len(_FAILURES)} CHECK(S) FAILED: " + ", ".join(_FAILURES))
        return 1
    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
