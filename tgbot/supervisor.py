"""Supervises one headless raksamp process.

- renders config -> RakSAMPClient.xml in a persistent run dir
- spawns the binary with stdin/stdout pipes (the control channel)
- reads its stdout log: keeps a ring buffer, tracks connection state, feeds
  per-command capture windows and a rate-limited live-log broadcast
- writes commands to its stdin (RunCommand)
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from pathlib import Path

from .config import InstanceConfig

# Log substrings that mark connection state transitions.
_CONNECTED = ("Connected to ", "Connected. Joining")
_DISCONNECTED = ("Disconnected.", "Connection attempt failed", "connection was lost",
                 "Connection was closed", "server is full", "You are banned",
                 "Invalid password", "ConnectionRejected")


class RakSampSupervisor:
    def __init__(self, binary: str, data_dir: Path, broadcast=None, tunnel=None):
        self.binary = binary
        self.run_dir = data_dir / "run"
        self.cfg = InstanceConfig(data_dir)
        self.tunnel = tunnel  # optional tgbot.tunnel.Tunnel (UDP-over-TCP)
        self.proc: asyncio.subprocess.Process | None = None
        self.lines: deque[str] = deque(maxlen=3000)
        self.connected = False
        self.last_event = ""
        self.started_at = 0.0
        self._captures: list[list[str]] = []
        self._subscribers: set[int] = set()
        self._pending: list[str] = []
        self._reader: asyncio.Task | None = None
        self._broadcaster: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        # broadcast(chat_id, text) -> awaitable; injected by the bot layer
        self._broadcast = broadcast

    # ---- lifecycle ----
    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def effective_server(self) -> tuple[str, int]:
        """Address the client should actually dial. With a tunnel, that's the
        local proxy; the real target is carried by the tunnel to the relay."""
        if self.tunnel:
            return ("127.0.0.1", self.tunnel.local_port)
        srv = self.cfg.data["server"]
        return (srv["addr"], int(srv["port"]))

    async def start(self) -> str:
        async with self._lock:
            if self.running:
                return "already running"
            override = None
            if self.tunnel:
                await self.tunnel.start()
                srv = self.cfg.data["server"]
                await self.tunnel.set_target(srv["addr"], int(srv["port"]))
                override = ("127.0.0.1", self.tunnel.local_port)
            self.cfg.write_xml(self.run_dir, server_override=override)
            self.proc = await asyncio.create_subprocess_exec(
                self.binary,
                cwd=str(self.run_dir),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            self.started_at = time.time()
            self.connected = False
            self._reader = asyncio.create_task(self._read_loop())
            if self._broadcaster is None:
                self._broadcaster = asyncio.create_task(self._broadcast_loop())
            return "started"

    async def stop(self) -> str:
        async with self._lock:
            if not self.running:
                return "not running"
            await self._send_raw("!exit")
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self.proc.kill()
                    await self.proc.wait()
            return "stopped"

    async def restart(self) -> str:
        await self.stop()
        return await self.start()

    async def shutdown(self) -> None:
        await self.stop()
        for t in (self._reader, self._broadcaster):
            if t:
                t.cancel()
        if self.tunnel:
            await self.tunnel.close()

    # ---- commands ----
    async def _send_raw(self, line: str) -> bool:
        if not self.running or self.proc.stdin is None:
            return False
        try:
            self.proc.stdin.write((line.rstrip("\r\n") + "\n").encode("utf-8", "replace"))
            await self.proc.stdin.drain()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    async def send(self, line: str) -> bool:
        """Fire-and-forget command."""
        return await self._send_raw(line)

    async def run_and_capture(self, line: str, wait: float = 1.2) -> list[str]:
        """Send a command and collect the log it produces within `wait` seconds."""
        bucket: list[str] = []
        self._captures.append(bucket)
        try:
            ok = await self._send_raw(line)
            if not ok:
                return ["(process is not running)"]
            await asyncio.sleep(wait)
        finally:
            if bucket in self._captures:
                self._captures.remove(bucket)
        return bucket

    async def run_and_wait(self, line: str | None, timeout: float = 9.0) -> list[str]:
        """Send a command (or just watch, line=None) and collect log until a
        connection state transition (connected / failed) or `timeout` elapses.
        Used by /connect so the user sees the actual connection outcome."""
        bucket: list[str] = []
        self._captures.append(bucket)
        try:
            if line is not None and not await self._send_raw(line):
                return ["(process is not running)"]
            # Ignore the bare "Disconnected." that !change_server emits while tearing
            # down the old connection; wait for the real outcome of the new attempt.
            markers = _CONNECTED + tuple(m for m in _DISCONNECTED if m != "Disconnected.")
            deadline = time.time() + timeout
            while time.time() < deadline:
                await asyncio.sleep(0.3)
                if any(any(m in ln for m in markers) for ln in bucket):
                    await asyncio.sleep(0.4)  # grab trailing lines (hostname, etc.)
                    break
        finally:
            if bucket in self._captures:
                self._captures.remove(bucket)
        return bucket

    # ---- log handling ----
    async def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        while True:
            raw = await self.proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                continue
            self.lines.append(line)
            self._pending.append(line)
            for bucket in self._captures:
                bucket.append(line)
            self._update_state(line)
        # stdout closed -> process ended
        self.connected = False
        self.last_event = "process exited"
        self._pending.append("[supervisor] raksamp process exited.")

    def _update_state(self, line: str) -> None:
        if any(s in line for s in _CONNECTED):
            self.connected = True
            self.last_event = line
        elif any(s in line for s in _DISCONNECTED):
            self.connected = False
            self.last_event = line
        elif line.startswith("[DIALOG]"):
            self.last_event = line

    async def _broadcast_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(1.5)
                if not self._pending or not self._subscribers or not self._broadcast:
                    self._pending.clear()
                    continue
                chunk = "\n".join(self._pending)[-3900:]
                self._pending.clear()
                for chat_id in list(self._subscribers):
                    try:
                        await self._broadcast(chat_id, chunk)
                    except Exception:
                        self._subscribers.discard(chat_id)
        except asyncio.CancelledError:
            pass

    # ---- views ----
    def subscribe(self, chat_id: int) -> None:
        self._subscribers.add(chat_id)

    def unsubscribe(self, chat_id: int) -> None:
        self._subscribers.discard(chat_id)

    def tail(self, n: int = 40) -> str:
        return "\n".join(list(self.lines)[-n:]) or "(no output yet)"

    def status(self) -> dict:
        srv = self.cfg.data["server"]
        return {
            "running": self.running,
            "connected": self.connected,
            "pid": self.proc.pid if self.running else None,
            "uptime_s": int(time.time() - self.started_at) if self.running else 0,
            "server": f'{srv["addr"]}:{srv["port"]}',
            "nickname": srv["nickname"],
            "runmode": self.cfg.data["runmode"],
            "last_event": self.last_event,
        }
