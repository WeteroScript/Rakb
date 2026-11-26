"""UDP-over-TCP tunnel client (runs inside the BotHost container).

BotHost blocks outbound UDP but allows outbound TCP (that's how Telegram long
polling works). SA-MP/RakNet is UDP-only. This component lets the client keep
running on BotHost by carrying its UDP datagrams over a TCP connection to a
relay (see relay/relay.py) on a host with open UDP.

    raksamp --UDP--> 127.0.0.1:local_port (this proxy) --TCP--> relay --UDP--> SA-MP server

The proxy is transparent to RakNet: it sends to 127.0.0.1:local_port and gets
replies from the same address, so no client-side changes are needed.

Wire protocol (TCP): a handshake line "TOKEN\\tIP\\tPORT\\n", the relay answers
"OK\\n", then both directions carry frames [4-byte big-endian length][payload].
"""
from __future__ import annotations

import asyncio
import struct

_MAX_FRAME = 65535


def _frame(data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + data


class _ProxyProtocol(asyncio.DatagramProtocol):
    def __init__(self, tunnel: "Tunnel"):
        self.tunnel = tunnel

    def datagram_received(self, data, addr):
        self.tunnel._on_datagram(data, addr)

    def error_received(self, exc):
        self.tunnel.last_error = f"udp: {exc}"


class Tunnel:
    def __init__(self, relay_host: str, relay_port: int, token: str, local_port: int = 7777):
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.token = token
        self.local_port = local_port
        self.target: tuple[str, int] | None = None
        self.relay_connected = False
        self.last_error = ""
        self.bytes_up = 0
        self.bytes_down = 0
        self._transport: asyncio.DatagramTransport | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task | None = None
        self._client_addr = None
        self._conn_lock = asyncio.Lock()
        self._reconnecting = False
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _ProxyProtocol(self), local_addr=("127.0.0.1", self.local_port))
        self._started = True

    async def set_target(self, ip: str, port: int) -> None:
        self.target = (ip, int(port))
        await self._connect_relay()

    async def _connect_relay(self) -> None:
        async with self._conn_lock:
            await self._close_relay()
            if not self.target:
                return
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.relay_host, self.relay_port), timeout=8.0)
                ip, port = self.target
                self._writer.write(f"{self.token}\t{ip}\t{port}\n".encode())
                await self._writer.drain()
                resp = await asyncio.wait_for(self._reader.readline(), timeout=8.0)
                if resp.strip() != b"OK":
                    self.last_error = f"relay: {resp.decode(errors='replace').strip()}"
                    await self._close_relay()
                    return
                self.relay_connected = True
                self.last_error = ""
                self._read_task = asyncio.create_task(self._read_relay())
            except Exception as e:
                self.last_error = f"relay connect: {e}"
                self.relay_connected = False
                await self._close_relay()

    async def _close_relay(self) -> None:
        self.relay_connected = False
        if self._read_task:
            self._read_task.cancel()
            self._read_task = None
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None
        self._reader = None

    async def _read_relay(self) -> None:
        try:
            while True:
                hdr = await self._reader.readexactly(4)
                n = struct.unpack(">I", hdr)[0]
                if n > _MAX_FRAME:
                    break
                payload = await self._reader.readexactly(n)
                self.bytes_down += len(payload)
                if self._transport and self._client_addr:
                    self._transport.sendto(payload, self._client_addr)
        except asyncio.CancelledError:
            return
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            pass
        self.relay_connected = False
        self.last_error = self.last_error or "relay connection closed"

    def _on_datagram(self, data, addr) -> None:
        self._client_addr = addr
        self.bytes_up += len(data)
        if self.relay_connected and self._writer and not self._writer.is_closing():
            try:
                self._writer.write(_frame(data))
            except Exception as e:
                self.last_error = f"send: {e}"
                self.relay_connected = False
        elif not self._reconnecting:
            self._reconnecting = True
            asyncio.create_task(self._reconnect_once())

    async def _reconnect_once(self) -> None:
        try:
            await self._connect_relay()
        finally:
            self._reconnecting = False

    async def close(self) -> None:
        await self._close_relay()
        if self._transport:
            self._transport.close()
            self._transport = None
        self._started = False

    def status(self) -> dict:
        return {
            "enabled": True,
            "relay": f"{self.relay_host}:{self.relay_port}",
            "relay_connected": self.relay_connected,
            "target": f"{self.target[0]}:{self.target[1]}" if self.target else None,
            "local": f"127.0.0.1:{self.local_port}",
            "bytes_up": self.bytes_up,
            "bytes_down": self.bytes_down,
            "last_error": self.last_error,
        }
