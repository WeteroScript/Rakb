"""UDP-over-TCP relay — run this on a VPS/host with OPEN outbound UDP.

The BotHost container (tgbot/tunnel.py) connects here over TCP and streams the
SA-MP client's UDP datagrams; this relay forwards them to the real game server
and streams the replies back. Token-authenticated so it is not an open relay.

Env:
  RELAY_TOKEN  (required) long random shared secret; must match TUNNEL_TOKEN
  RELAY_PORT   (default 9000) TCP port to listen on
  RELAY_BIND   (default 0.0.0.0)

Run:
  RELAY_TOKEN='a-long-random-string' python3 relay.py
Only the Python standard library is required (no dependencies).
"""
from __future__ import annotations

import asyncio
import os
import struct
import sys

_MAX_FRAME = 65535


def _frame(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


class _RelayUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer

    def datagram_received(self, data, addr):
        try:
            if not self.writer.is_closing():
                self.writer.write(_frame(data))
        except Exception:
            pass


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, token: str):
    transport = None
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=10.0)
        parts = line.decode(errors="replace").strip().split("\t")
        if len(parts) != 3:
            writer.write(b"ERR bad handshake\n")
            await writer.drain()
            return
        tok, ip, port = parts
        if token and tok != token:
            writer.write(b"ERR bad token\n")
            await writer.drain()
            return
        try:
            port = int(port)
            if not (0 < port < 65536):
                raise ValueError
        except ValueError:
            writer.write(b"ERR bad port\n")
            await writer.drain()
            return
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _RelayUdpProtocol(writer), remote_addr=(ip, port))
        writer.write(b"OK\n")
        await writer.drain()
        while True:
            hdr = await reader.readexactly(4)
            n = struct.unpack(">I", hdr)[0]
            if n > _MAX_FRAME:
                break
            payload = await reader.readexactly(n)
            transport.sendto(payload)
    except (asyncio.IncompleteReadError, ConnectionResetError, OSError, asyncio.TimeoutError):
        pass
    finally:
        if transport:
            try:
                transport.close()
            except Exception:
                pass
        try:
            writer.close()
        except Exception:
            pass


async def main() -> None:
    token = os.environ.get("RELAY_TOKEN", "").strip()
    port = int(os.environ.get("RELAY_PORT", "9000"))
    bind = os.environ.get("RELAY_BIND", "0.0.0.0")
    if not token:
        print("RELAY_TOKEN is required (prevents open-relay abuse). Set a long random string.",
              file=sys.stderr)
        sys.exit(1)
    server = await asyncio.start_server(lambda r, w: handle_client(r, w, token), bind, port)
    print(f"rakb relay on {bind}:{port} (token auth)", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
