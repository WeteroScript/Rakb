"""SA-MP server query over UDP (the 'SAMP' query protocol).

Doubles as a reachability probe for the container's outbound UDP:
  - query answers, but RakNet /connect fails -> UDP egress works, problem is at
    the game-protocol layer (version / cookie / server-side filtering of the play
    connection).
  - query times out -> outbound UDP is blocked on the host, or the server
    firewalls this container's source IP. SA-MP needs UDP, so the client cannot
    connect until that is resolved.
"""
from __future__ import annotations

import asyncio
import socket
import struct


def _query_sync(ip: str, port: int, opcode: str, timeout: float) -> bytes:
    resolved = socket.gethostbyname(ip)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        header = b"SAMP" + socket.inet_aton(resolved) + struct.pack("<H", port)
        pkt = header + opcode.encode("ascii")
        if opcode == "p":
            pkt += b"\x00\x00\x00\x00"
        sock.sendto(pkt, (resolved, port))
        data, _ = sock.recvfrom(4096)
        return data
    finally:
        sock.close()


def _parse_info(data: bytes) -> dict:
    # header: "SAMP"(4) + ip(4) + port(2) + opcode(1) = 11 bytes
    if len(data) < 11 or data[:4] != b"SAMP":
        raise ValueError("malformed query response")
    off = 11
    password = data[off]
    off += 1
    players, maxplayers = struct.unpack("<HH", data[off:off + 4])
    off += 4

    def read_str(o: int):
        n = struct.unpack("<I", data[o:o + 4])[0]
        o += 4
        s = data[o:o + n].decode("latin-1", "replace")
        return s, o + n

    hostname, off = read_str(off)
    gamemode, off = read_str(off)
    language, off = read_str(off)
    return {
        "password": bool(password), "players": players, "maxplayers": maxplayers,
        "hostname": hostname, "gamemode": gamemode, "language": language,
    }


async def query_server(ip: str, port: int, timeout: float = 3.0) -> dict:
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _query_sync, ip, port, "i", timeout)
    return _parse_info(data)
