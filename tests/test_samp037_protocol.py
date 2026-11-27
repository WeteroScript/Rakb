#!/usr/bin/env python3
"""SA-MP 0.3.7 protocol regression test: real raksamp binary <-> mock server.

Locks in the wire-format fixes so they cannot silently regress:

  * kyretardizeDatagram encode/decode (0x6969 cookie, XOR-only answer)
  * ID_OPEN_CONNECTION_REQUEST / REPLY / COOKIE wire ids (24 / 25 / 26)
  * reliable ID_CONNECTION_REQUEST (11) and the 13-byte ACCEPTED (34) layout
  * RPC_ClientJoin (25) field order, NETGAME_VERSION 4057, challenge ^ version
  * gen_auth_key: SHA1 -> 100-byte transform -> CAnimManager XOR -> hex
  * DataStructures::List null guards (GCC drops the delete[] null check after
    a nonnull memcpy, which killed the client on the first reliable packet)
  * gen_gpci / BIG_NUM_MUL 32-bit limbs (unsigned long is 8 bytes on Linux)

Usage:
    RAKSAMP_BIN=/path/to/raksamp python3 tests/test_samp037_protocol.py
    python3 tests/test_samp037_protocol.py --bin /path/to/raksamp

Exit status is 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tgbot.config import InstanceConfig          # noqa: E402
from tgbot.sampnetencr import samp_decode        # noqa: E402
from tgbot.sampquery import _handshake_sync      # noqa: E402

COOKIE = 0x1234
CHALLENGE = 0xDEADBEEF
NETGAME_VERSION = 4057
CLIENT_VERSION = "0.3.7"
NICKNAME = "ProtocolTest"
AUTH_CHALLENGE = "testauth12345"

ID_CONNECTION_REQUEST = 11
ID_AUTH_KEY = 12
ID_RPC = 20
ID_OPEN_CONNECTION_REQUEST = 24
ID_OPEN_CONNECTION_REPLY = 25
ID_COOKIE = 26
ID_ACCEPTED = 34
RPC_CLIENT_JOIN = 25

_FAILURES: list[str] = []


# --------------------------------------------------------------------------
# RakNet BitStream bit order helpers (MSB-first inside each byte)
# --------------------------------------------------------------------------
class BitWriter:
    def __init__(self) -> None:
        self._bits: list[int] = []

    def bit(self, b: int) -> None:
        self._bits.append(b & 1)

    def write_bits(self, value: int, n: int) -> None:
        for i in range(n - 1, -1, -1):
            self.bit((value >> i) & 1)

    def u16le(self, v: int) -> None:
        self.write_bits(v & 0xFF, 8)
        self.write_bits((v >> 8) & 0xFF, 8)

    def compressed_u16(self, v: int) -> None:
        hi, lo = (v >> 8) & 0xFF, v & 0xFF
        if hi != 0:
            self.bit(0)
            self.write_bits(lo, 8)
            self.write_bits(hi, 8)
            return
        self.bit(1)
        if (lo & 0xF0) == 0:
            self.bit(1)
            self.write_bits(lo, 4)
        else:
            self.bit(0)
            self.write_bits(lo, 8)

    def data(self, payload: bytes) -> None:
        for b in payload:
            self.write_bits(b, 8)

    def out(self) -> bytes:
        out = bytearray()
        for i in range(0, len(self._bits), 8):
            b = 0
            for j in range(8):
                b = (b << 1) | (self._bits[i + j] if i + j < len(self._bits) else 0)
            out.append(b)
        return bytes(out)


class BitReader:
    def __init__(self, data: bytes) -> None:
        self.bits: list[int] = []
        for b in data:
            for i in range(7, -1, -1):
                self.bits.append((b >> i) & 1)
        self.pos = 0

    def read(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | (self.bits[self.pos] if self.pos < len(self.bits) else 0)
            self.pos += 1
        return v

    def u16le(self) -> int:
        lo = self.read(8)
        hi = self.read(8)
        return lo | (hi << 8)

    def compressed_u16(self) -> int:
        if self.read(1) == 0:
            lo = self.read(8)
            hi = self.read(8)
            return lo | (hi << 8)
        if self.read(1) == 1:
            return self.read(4)
        return self.read(8)

    def align(self) -> None:
        while self.pos % 8:
            self.pos += 1


def read_compressed_uint(r: BitReader) -> int:
    """BitStream::ReadCompressed(unsigned int) - used for the RPC bit length."""
    cur = 3
    while cur > 0:
        if r.read(1) == 1:
            cur -= 1
            continue
        raw = 0
        for i in range(cur + 1):
            raw |= r.read(8) << (8 * i)
        return raw
    if r.read(1) == 1:
        return r.read(4)
    return r.read(8)


def rpc_payload(payload: bytes) -> tuple[int, bytes]:
    """ID_RPC packet -> (rpc_id, inner bytes), skipping WriteCompressed(bitLength)."""
    r = BitReader(payload)
    if r.read(8) != ID_RPC:
        raise ValueError("not an ID_RPC packet")
    rpc_id = r.read(8)
    bitlen = read_compressed_uint(r)
    return rpc_id, bytes(r.read(8) for _ in range((bitlen + 7) // 8))


def parse_datagram(data: bytes) -> list[tuple[int, int, bytes]] | None:
    """Reliability-layer datagram -> [(messageNumber, reliability, payload)].

    Returns None for ACK-only / split datagrams, which this mock does not need.
    """
    r = BitReader(data)
    if r.read(1):
        return None  # hasAcks
    msgs = []
    while r.pos + 16 <= len(r.bits):
        msg_num = r.u16le()
        reliability = r.read(3)
        if reliability in (1, 3, 4):  # sequenced / ordered carry these fields
            r.read(32)  # orderingIndex
            r.read(4)   # orderingChannel
        if r.read(1):
            return None  # split packet
        length_bits = r.compressed_u16()
        r.align()        # payload uses WriteAlignedBytes / ReadAlignedBytes
        # round UP: the final byte is padded, truncating it corrupts the last char
        payload = bytes(r.read(8) for _ in range((length_bits + 7) // 8))
        msgs.append((msg_num, reliability, payload))
    return msgs


def make_datagram(payload: bytes, msg_num: int = 0, reliability: int = 2) -> bytes:
    w = BitWriter()
    w.bit(0)             # no acks
    w.u16le(msg_num)
    w.write_bits(reliability, 3)
    w.bit(0)             # not split
    w.compressed_u16(len(payload) * 8)
    while len(w._bits) % 8:
        w.bit(0)
    w.data(payload)
    return w.out()


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        _FAILURES.append(name)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------
# Mock 0.3.7 server: decodes client datagrams, answers in plaintext
# --------------------------------------------------------------------------
class MockServer:
    def __init__(self, port: int, full: bool = False, timeout: float = 20.0) -> None:
        self.port = port
        self.full = full
        self.log: list[tuple[str, str]] = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(timeout)
        self.client_addr = None
        self.stage = "request"
        self.clientjoin: bytes | None = None
        self.authkey_response: bytes | None = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def send_plain(self, data: bytes) -> None:
        self.sock.sendto(data, self.client_addr)

    def send_reliable(self, payload: bytes, msg_num: int) -> None:
        self.send_plain(make_datagram(payload, msg_num))

    def run(self) -> None:
        try:
            while True:
                try:
                    data, _ = self.sock.recvfrom(4096)
                except socket.timeout:
                    break
                self.client_addr = _
                if data[:4] == b"SAMP":
                    self._answer_query(data)
                    continue
                try:
                    plain = samp_decode(data, self.port)
                except ValueError:
                    self.log.append(("badenc", data.hex(" ")))
                    continue
                self.log.append(("recv", plain.hex(" ")))
                self._step(plain)
                if self.stage == "done":
                    break
        finally:
            self.sock.close()

    def _answer_query(self, data: bytes) -> None:
        """Answer the plaintext SAMP query ('i' info opcode) used by /query and /selftest."""
        if len(data) < 11:
            return
        opcode = data[10:11]
        if opcode != b"i":
            return
        body = bytearray(data[:11])
        body += bytes([0])                       # no password
        body += struct.pack("<HH", 7, 100)       # players / maxplayers
        for text in (b"Mock 0.3.7 Server", b"regression", b"English"):
            body += struct.pack("<I", len(text)) + text
        self.send_plain(bytes(body))

    def _step(self, plain: bytes) -> None:
        if not plain:
            return
        if self.stage == "request" and plain[0] == ID_OPEN_CONNECTION_REQUEST:
            self.send_plain(bytes([ID_COOKIE]) + struct.pack("<H", COOKIE))
            self.stage = "cookie"
        elif self.stage == "cookie" and plain[0] == ID_OPEN_CONNECTION_REQUEST:
            expected = bytes([ID_OPEN_CONNECTION_REQUEST]) + struct.pack("<H", COOKIE ^ 0x6969)
            if plain == expected:
                self.send_plain(bytes([ID_OPEN_CONNECTION_REPLY, 0]))
                self.stage = "connreq" if self.full else "done"
            else:
                self.log.append(("badcookie", plain.hex(" ")))
        elif self.stage == "connreq":
            for _, _, payload in parse_datagram(plain) or []:
                if payload and payload[0] == ID_CONNECTION_REQUEST:
                    self.log.append(("connreq", payload.hex(" ")))
                    # ACCEPTED: id, binaryAddress(4), port(2), playerIndex(2), challenge(4)
                    accept = (bytes([ID_ACCEPTED]) + socket.inet_aton("127.0.0.1")
                              + struct.pack("<H", self.port)
                              + struct.pack("<H", 2)
                              + struct.pack("<I", CHALLENGE))
                    self.send_reliable(accept, 0)
                    self.stage = "clientjoin"
        elif self.stage == "clientjoin":
            for _, _, payload in parse_datagram(plain) or []:
                if payload and payload[0] == ID_RPC:
                    rpc_id, inner = rpc_payload(payload)
                    if rpc_id == RPC_CLIENT_JOIN:
                        self.clientjoin = inner
                        self.log.append(("clientjoin", inner.hex(" ")))
                        self.send_reliable(
                            bytes([ID_AUTH_KEY, len(AUTH_CHALLENGE)]) + AUTH_CHALLENGE.encode(), 1)
                        self.stage = "authkey"
                    else:
                        self.log.append(("rpc", str(rpc_id)))
        elif self.stage == "authkey":
            for _, _, payload in parse_datagram(plain) or []:
                if payload and payload[0] == ID_AUTH_KEY:
                    self.authkey_response = payload
                    self.log.append(("authkey", payload.hex(" ")))
                    self.stage = "done"


def expected_auth_key(auth_in: str) -> str:
    """Reference gen_auth_key: SHA1 words are stored little-endian, then transformed."""
    digest = hashlib.sha1(auth_in.encode()).digest()
    h = bytearray(b"".join(digest[i:i + 4][::-1] for i in range(0, 20, 4)))
    table = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
        0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x80,
        0x08, 0x06, 0x00, 0x00, 0x00, 0xE4, 0xB5, 0xB7, 0x0A, 0x00, 0x00, 0x00,
        0x09, 0x70, 0x48, 0x59, 0x73, 0x00, 0x00, 0x0B, 0x13, 0x00, 0x00, 0x0B,
        0x13, 0x01, 0x00, 0x9A, 0x9C, 0x18, 0x00, 0x00, 0x00, 0x04, 0x67, 0x41,
        0x4D, 0x41, 0x00, 0x00, 0xB1, 0x8E, 0x7C, 0xFB, 0x51, 0x93, 0x00, 0x00,
        0x00, 0x20, 0x63, 0x48, 0x52, 0x4D, 0x00, 0x00, 0x7A, 0x25, 0x00, 0x00,
        0x80, 0x83, 0x00, 0x00, 0xF9, 0xFF, 0x00, 0x00, 0x80, 0xE9, 0x00, 0x00,
        0x75, 0x30, 0x00, 0x00,
    ])
    anim = bytes([0xFF, 0x25, 0x34, 0x39, 0x4D, 0x00, 0x90, 0x90, 0x90, 0x90,
                  0x56, 0x57, 0x50, 0x8B, 0x44, 0x24, 0x14, 0x8D, 0x0C, 0x80])
    xors = [0x2F] * 5 + [0x45] * 5 + [0x6F] * 5 + [0xDB] * 5
    for i in range(20):
        v = h[i]
        for t in table:
            v ^= t ^ xors[i]
        h[i] = v ^ anim[i]
    return "".join(f"{b:02X}" for b in h)


# --------------------------------------------------------------------------
# Part A - the /diag probe handshake
# --------------------------------------------------------------------------
def part_a() -> None:
    port = free_port()
    srv = MockServer(port, full=False, timeout=10)
    time.sleep(0.2)
    steps = _handshake_sync("127.0.0.1", port, 2.0)
    srv.thread.join(timeout=10)
    accepted = any(g and g[0] == ID_OPEN_CONNECTION_REPLY for _, _, g in steps)
    check("probe: handshake accepted", accepted,
          "; ".join(f"{label}: {s.hex(' ')} -> {g.hex(' ') if g else 'none'}"
                    for label, s, g in steps))
    check("probe: request plaintext is 18 00 00",
          bool(steps) and steps[0][1] == bytes([ID_OPEN_CONNECTION_REQUEST, 0, 0]))
    check("probe: cookie answer xor",
          len(steps) > 1 and steps[1][1] == bytes([ID_OPEN_CONNECTION_REQUEST])
          + struct.pack("<H", COOKIE ^ 0x6969))


# --------------------------------------------------------------------------
# Part B - the real client binary through the whole join sequence
# --------------------------------------------------------------------------
def part_b(binary: Path) -> None:
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="rakb-proto-") as tmp:
        tmp_path = Path(tmp)
        data_dir = tmp_path / "data"
        run_dir = tmp_path / "run"
        data_dir.mkdir()
        run_dir.mkdir()

        cfg = InstanceConfig(data_dir)
        cfg.set_server("127.0.0.1", port, NICKNAME)
        (run_dir / "RakSAMPClient.xml").write_text(cfg.render_xml(), encoding="utf-8")

        srv = MockServer(port, full=True, timeout=20)
        time.sleep(0.2)
        proc = subprocess.Popen([str(binary)], cwd=run_dir,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, env=dict(os.environ))
        try:
            srv.thread.join(timeout=25)
            time.sleep(0.5)
        finally:
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()

    wire = " | ".join(f"{k}:{v}" for k, v in srv.log)
    cookie_ok = any(
        k == "recv" and v == (bytes([ID_OPEN_CONNECTION_REQUEST])
                              + struct.pack("<H", COOKIE ^ 0x6969)).hex(" ")
        for k, v in srv.log)
    check("client: cookie answered correctly", cookie_ok, wire)
    check("client: sent CONNECTION_REQUEST", any(k == "connreq" for k, v in srv.log))
    check("client: sent RPC_ClientJoin", srv.clientjoin is not None)

    if srv.clientjoin:
        p = srv.clientjoin
        off = 0
        version = struct.unpack("<i", p[off:off + 4])[0]; off += 4
        mod = p[off]; off += 1
        namelen = p[off]; off += 1
        name = p[off:off + namelen].decode(); off += namelen
        resp = struct.unpack("<I", p[off:off + 4])[0]; off += 4
        authlen = p[off]; off += 1
        auth = p[off:off + authlen].decode(); off += authlen
        verlen = p[off]; off += 1
        ver = p[off:off + verlen].decode()
        check("ClientJoin: version 4057", version == NETGAME_VERSION, str(version))
        check("ClientJoin: mod 1", mod == 1, str(mod))
        check("ClientJoin: nickname", name == NICKNAME, name)
        check("ClientJoin: challenge response", resp == (CHALLENGE ^ NETGAME_VERSION), hex(resp))
        # gpci is variable-length hex (leading zero nibbles are suppressed)
        check("ClientJoin: auth key present",
              authlen > 0 and len(auth) == authlen
              and all(c in "0123456789ABCDEF" for c in auth), auth)
        check("ClientJoin: client version string", ver == CLIENT_VERSION, ver)

    check("client: AUTH_KEY response sent", srv.authkey_response is not None)
    if srv.authkey_response:
        p = srv.authkey_response
        klen = p[1]
        key = p[2:2 + klen].decode()
        check("AUTH_KEY: 40-char hex",
              klen == 40 and all(c in "0123456789ABCDEF" for c in key), key)
        expected = expected_auth_key(AUTH_CHALLENGE)
        check("AUTH_KEY: matches reference algorithm", key == expected, f"{key} vs {expected}")

    if _FAILURES:
        print("--- client stdout ---")
        print("\n".join(out.splitlines()[:25]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bin", default=os.environ.get("RAKSAMP_BIN", ""),
                        help="path to the raksamp binary (or set RAKSAMP_BIN)")
    args = parser.parse_args()

    binary = Path(args.bin) if args.bin else REPO_ROOT / "build" / "bin" / "raksamp"
    if not binary.is_file():
        print(f"raksamp binary not found: {binary}\n"
              "Build it first, then pass --bin /path/to/raksamp (or set RAKSAMP_BIN).")
        return 2

    part_a()
    part_b(binary)

    if _FAILURES:
        print(f"\n{len(_FAILURES)} CHECK(S) FAILED: " + ", ".join(_FAILURES))
        return 1
    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
