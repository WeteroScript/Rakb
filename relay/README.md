# UDP-over-TCP реле (для хостингов, которые режут исходящий UDP)

BotHost блокирует исходящий UDP, но разрешает исходящий TCP (так работает Telegram
long polling). SA-MP/RakNet — UDP-only. Это реле позволяет оставить бота на BotHost:
контейнер открывает TCP-соединение к реле, а реле (на хосте с открытым UDP)
пересылает датаграммы реальному игровому серверу и обратно.

```
raksamp ─UDP─► 127.0.0.1:7777 (tunnel.py в контейнере) ─TCP─► реле (VPS) ─UDP─► SA-MP сервер
```

Реле — чистый стандартный Python, без зависимостей. Нужен VPS/хост с **открытым
исходящим UDP** и открытым входящим TCP-портом (по умолчанию 9000).

## Запуск на VPS

Сгенерируйте длинный случайный токен (общий секрет для реле и бота):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Вариант A: напрямую

```bash
# скопируйте relay.py на VPS
RELAY_TOKEN='ВАШ_ТОКЕН' RELAY_PORT=9000 python3 relay.py
```

Чтобы переживало перезапуск — systemd-юнит `/etc/systemd/system/rakb-relay.service`:

```ini
[Unit]
Description=RakB UDP-over-TCP relay
After=network.target

[Service]
Environment=RELAY_TOKEN=ВАШ_ТОКЕН
Environment=RELAY_PORT=9000
ExecStart=/usr/bin/python3 /opt/rakb-relay/relay.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rakb-relay
```

### Вариант B: Docker

```bash
docker build -t rakb-relay ./relay
docker run -d --name rakb-relay --restart unless-stopped \
  -p 9000:9000 \
  -e RELAY_TOKEN='ВАШ_ТОКЕН' \
  rakb-relay
```

## Фаервол

Откройте **входящий TCP 9000** на VPS (security group / `ufw allow 9000/tcp`).
Исходящий UDP должен быть разрешён (на большинстве VPS он открыт по умолчанию).

## Настройка бота на BotHost

В панели BotHost → «Переменные окружения» добавьте:

| Переменная | Значение |
|---|---|
| `TUNNEL_RELAY` | `VPS_IP:9000` |
| `TUNNEL_TOKEN` | тот же токен, что `RELAY_TOKEN` |
| `TUNNEL_LOCAL_PORT` | `7777` (необязательно, по умолчанию 7777) |

Сделайте **новый деплой**. После этого `/connect <ip> <port>` автоматически идёт
через туннель: клиент подключается к локальному прокси `127.0.0.1:7777`, а реальный
адрес несёт туннель до реле. Статус — `/tunnel`.

## Безопасность

Реле требует токен (`RELAY_TOKEN`), иначе не запускается — это не open relay.
Токен должен совпадать с `TUNNEL_TOKEN`. Держите его секретным.
