# Запуск на своём ПК (бесплатно, без карты)

Самый надёжный бесплатный путь без карты и без студенческой почты — запустить стек
на своём компьютере. Домашний интернет не режет исходящий UDP, поэтому `/connect`
работает сразу. Минус: ПК должен быть включён и в сети (бот работает, пока он работает).

Стек — Linux-контейнер, поэтому на Windows запускаем через **Docker Desktop** (бесплатен
для личного использования), на Linux — через обычный Docker.

## Windows

1. Установи **Docker Desktop**: [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/).
   При установке включи **WSL2 backend** (предлагается по умолчанию). Перезагрузись, если попросит.
2. Запусти Docker Desktop и дождись, пока он станет «running».
3. Открой **PowerShell** и склонируй репозиторий (нужен [git](https://git-scm.com/download/win)):
   ```powershell
   git clone --branch arena/3b12d5df-rakb https://github.com/WeteroScript/Rakb.git
   cd Rakb
   ```
4. Собери и запусти (подставь свои токен и id):
   ```powershell
   docker build -t rakb .
   docker run -d --name rakb --restart unless-stopped `
     -e BOT_TOKEN="123456:ABC..." `
     -e ADMIN_IDS="123456789" `
     -e AUTOSTART=1 `
     -v rakb-data:/app/data `
     rakb
   ```
5. Проверка:
   ```powershell
   docker logs -f rakb
   # ждём: health on 0.0.0.0:8080 | admins=... | bin=/opt/rakb/bin/raksamp
   ```

Сборка занимает несколько минут. Чтобы бот работал постоянно — не выключай ПК и
отключи сон: **Параметры → Система → Питание и спящий режим → Сон = Никогда**.

## Linux

```bash
git clone --branch arena/3b12d5df-rakb https://github.com/WeteroScript/Rakb.git
cd Rakb
sudo bash scripts/deploy-vps.sh "BOT_TOKEN" "ADMIN_IDS"
```

(скрипт поставит Docker, соберёт и запустит; на домашнем Linux swap не обязателен,
но скрипт добавит его при отсутствии.)

## Управление из Telegram

```
/nettest                          # референсы и цель 🟢 (домашний UDP открыт)
/connect 80.66.82.249 5125 Nick
/status
```

Входящие порты открывать не нужно — бот ходит в Telegram исходящим polling, клиент
подключается к серверу исходящим UDP.

## Если репозиторий приватный

`git clone` попросит авторизацию. Сделай репозиторий публичным на время деплоя
(Settings → Danger Zone → Change visibility) или клонируй с personal access token.

## Обновление

```powershell
cd Rakb
git pull
docker build -t rakb .
docker rm -f rakb
docker run -d --name rakb --restart unless-stopped -e BOT_TOKEN="..." -e ADMIN_IDS="..." -e AUTOSTART=1 -v rakb-data:/app/data rakb
```

Данные живут в томе `rakb-data` и переживают пересборку.
