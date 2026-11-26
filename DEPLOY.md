# Деплой на BotHost (bothost.ru)

RakSAMP-клиент портирован на headless Linux и управляется через Telegram-бота.
BotHost работает на Linux и поддерживает свой `Dockerfile` — этим и пользуемся.

## Что внутри

- `rakfk/` — C++ исходники RakSAMP 0.3.7 + `CMakeLists.txt` (сборка `raksamp` под Linux).
- `tgbot/` — Python-супервизор (aiogram 3): запускает `raksamp`, шлёт команды в его
  stdin, читает stdout-лог и пересылает в Telegram.
- `Dockerfile` — двухстадийная сборка: компилирует C++ → `/opt/rakb/bin/raksamp`,
  ставит Python-бота в `/opt/rakb`. Код лежит в `/opt/rakb`, а не в `/app`.

## Важные особенности BotHost (учтены в проекте)

1. **`/app` монтируется из Git при запуске** и скрывает всё, что образ положил в
   `/app`. Поэтому бинарник и код бота живут в `/opt/rakb`.
2. **`/app/data` — персистентный том** (тарифы Basic/Pro). Туда пишутся конфиг
   (`instance.json`), `RakSAMPClient.xml` и логи. На бесплатном тарифе данные
   стираются при рестарте.
3. **Порт**: контейнер слушает `0.0.0.0:$PORT` (health-эндпоинт). Telegram работает
   через long polling — публичный URL/вебхук не нужен.
4. **Свой Dockerfile**: команду запуска задаёт `CMD` из Dockerfile, поле «Главный
   файл» игнорируется.

## Шаги

1. **Токен и ID.** Создайте бота у [@BotFather](https://t.me/BotFather), получите
   `BOT_TOKEN`. Узнайте свой числовой Telegram ID (например, у [@userinfobot](https://t.me/userinfobot)).

2. **Репозиторий.** Запушьте этот репозиторий в GitHub/GitLab (или загрузите ZIP в
   панель BotHost). В корне должны быть `Dockerfile`, `requirements.txt`, `rakfk/`, `tgbot/`.

3. **Создайте бота на BotHost.** В дополнительных настройках включите
   **«Использовать собственный Dockerfile»** и укажите `Dockerfile` из корня.

4. **Переменные окружения** (панель → «Переменные окружения»):

   | Переменная | Значение | Обязательно |
   |---|---|---|
   | `BOT_TOKEN` | токен от BotFather | да |
   | `ADMIN_IDS` | ваши числовые ID через запятую, напр. `123456789` | да |
   | `PORT` | `8080` | нет (по умолчанию 8080) |
   | `DATA_DIR` | `/app/data` | нет (по умолчанию /app/data) |
   | `AUTOSTART` | `1` — запускать клиент сразу при старте контейнера | нет |

5. **Персистентное хранилище.** Включите том `/app/data` (Basic/Pro), чтобы конфиг
   и логи переживали перезапуски.

6. **Деплой.** Соберите и запустите. В логах контейнера будет
   `health on 0.0.0.0:8080 | admins=... | bin=/opt/rakb/bin/raksamp`.

## Управление из Telegram

Откройте бота (команды доступны только `ADMIN_IDS`):

```
/run                          # запустить клиент
/connect 1.2.3.4 7777 MyNick  # сервер + ник (опционально пароль 4-м аргументом)
/auth password                # авторизация на сервере (!auth)
/spawn                        # заспавниться
/mode 3                       # runmode: 1 bare, 2 still, 3 normal, 4 follow, 5 follow+veh
/say привет                   # сообщение в чат
/scmd login 123               # серверная команда (/login 123)
/players                      # список игроков (с выводом)
/teleport                     # список телепортов; /teleport <id> — перейти
/dialog 5 1 0 text            # ответ на диалог сервера
/cmd !pos x 100               # любая команда RunCommand
/log on                       # живой лог в этот чат (батчами ~1.5с)
/logs 50                      # последние 50 строк лога
/status                       # состояние процесса/подключения
/config                       # текущий конфиг
/stop · /restart
```

Серверные диалоги в headless-режиме приходят в лог как `[DIALOG] id=... title=...`
— отвечайте `/dialog <id> <button 0/1> <item> <text>`.

## Сеть

SA-MP/RakNet ходит по **UDP**. Исходящий UDP из контейнера должен быть разрешён
(стандартный Docker bridge это позволяет). Если тариф/фаервол режет UDP — клиент
не подключится; уточните у поддержки BotHost.

## Локальная проверка

```bash
# сборка клиента
cmake -S rakfk -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j

# бот локально (бинарник рядом)
pip install -r requirements.txt
BOT_TOKEN=... ADMIN_IDS=123456789 \
  RAKSAMP_BIN=$PWD/build/bin/raksamp DATA_DIR=$PWD/data PORT=8080 \
  python -m tgbot
```

Через Docker:

```bash
docker build -t rakb-tg .
docker run --rm -p 8080:8080 \
  -e BOT_TOKEN=... -e ADMIN_IDS=123456789 \
  -v rakb-data:/app/data rakb-tg
```
