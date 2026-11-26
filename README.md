# Rakb — RakSAMP on Linux, driven by Telegram

Headless Linux port of the **RakSAMP Lite 0.3.7** SA-MP client (`jlfm / bartekdvd / P3ti`),
plus a Telegram bot that supervises it. Built to run on **BotHost** (bothost.ru) via a
custom Dockerfile, but runs anywhere with Docker or a plain Linux box.

```
Telegram  ──aiogram──►  tgbot (Python)  ──stdin/stdout──►  raksamp (C++)  ──UDP/RakNet──►  SA-MP server
```

## Layout

| Path | What |
|---|---|
| `rakfk/` | RakSAMP C++ source (client + RakNet + SAMP netcode) and `CMakeLists.txt` |
| `rakfk/common/wincompat.h` | Win32→POSIX shim (types, `_s` CRT, timing, Winsock, GUI stubs) |
| `rakfk/client/src/console.cpp` | stdin→`RunCommand` control channel (Linux) |
| `rakfk/client/src/window_linux.cpp` | headless GUI stubs |
| `tgbot/` | Python supervisor + aiogram 3 Telegram handlers + health endpoint |
| `Dockerfile` | multi-stage: compile C++ → `/opt/rakb/bin`, run Python from `/opt/rakb` |
| `DEPLOY.md` | BotHost deployment + Telegram command reference |

## The port

RakNet 3.x was already cross-platform; the work was the Win32 surface:

- `common/wincompat.h` supplies Win32 types (DWORD stays 32-bit for the wire structs),
  the secure CRT, `GetTickCount`/`Sleep`/`GetLocalTime`, a Winsock shim, and no-op GUI stubs.
- The Win32 GUI (`window.cpp`, the dialog thread, the teleport menu) is `#ifdef _WIN32`'d
  out and replaced with **stdout logging** — server dialogs/teleport lists surface in
  Telegram instead of a window.
- Fixed a real latent bug: `common.h` leaked `#pragma pack(1)` into tinyxml/RakNet headers
  (now reset), plus MSVC-isms (`__intN`, rvalue→ref casts, `unsigned long long(x)` functional
  casts) and case-sensitive header includes (case-alias symlinks).
- The original Windows build still works via `rakfk/RakSAMP_2008.sln`.

## Build & run (local)

```bash
cmake -S rakfk -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
pip install -r requirements.txt
BOT_TOKEN=... ADMIN_IDS=<your_id> \
  RAKSAMP_BIN=$PWD/build/bin/raksamp DATA_DIR=$PWD/data \
  python -m tgbot
```

Then in Telegram: `/run`, `/connect <ip> <port> [nick] [pass]`, `/auth <pass>`, `/spawn`,
`/log on`, `/cmd !players`, … See `DEPLOY.md` for the full command list and BotHost setup.

## Notes

- The binary is static-linked against libstdc++/libgcc; the runtime image needs only glibc.
- Config/state/logs persist in `/app/data` (BotHost volume); code lives in `/opt/rakb` to
  dodge BotHost's `/app` Git bind-mount.
- SA-MP uses UDP — the host must allow outbound UDP.
