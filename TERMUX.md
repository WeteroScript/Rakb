# Запуск на телефоне (Android, Termux) — бесплатно, без карты и ПК

У телефона «домашний»/мобильный ip — тот же, с которого ты заходишь в SA-MP, поэтому
игровые серверы его пускают (в отличие от ip хостинга). Запускаем весь стек прямо на
телефоне через Termux. Минус: телефон должен быть включён, в сети и не «усыплять» Termux.

Стек собирается под ARM64 (x86-asm в клиент не попадает, `char` принудительно signed).

## 1. Установи Termux

**Не из Google Play** (там старая сломанная версия). Поставь из **F-Droid**:
[ f-droid.org/packages/com.termux ](https://f-droid.org/packages/com.termux/) — или APK с
[github.com/termux/termux-app/releases](https://github.com/termux/termux-app/releases).

## 2. Подними Ubuntu внутри Termux

Открой Termux и по очереди:

```bash
pkg update -y
pkg install proot-distro -y
proot-distro install ubuntu
proot-distro login ubuntu
```

Последняя команда заводит тебя в Ubuntu (приглашение сменится на `root@...`).

## 3. Деплой одной командой (внутри Ubuntu)

```bash
apt update && apt install -y curl
curl -fsSL https://raw.githubusercontent.com/WeteroScript/Rakb/arena/3b12d5df-rakb/scripts/termux-setup.sh -o termux-setup.sh
bash termux-setup.sh "BOT_TOKEN" "ADMIN_IDS"
```

Скрипт поставит g++/cmake/python, склонирует ветку, соберёт ARM-клиент и запустит бота
с `AUTOSTART=1`. Сборка на телефоне — несколько минут. Не закрывай Termux.

## 4. Чтобы Android не убил бота

- В шторке уведомлений Termux нажми **Acquire wakelock**.
- Настройки Android → Приложения → Termux → Батарея → **Без ограничений** (не оптимизировать).
- Держи телефон на зарядке и в сети (Wi-Fi или мобильный интернет).

## 5. Управление из Telegram

```
/nettest                          # теперь samp-серверы должны быть 🟢 (домашний ip)
/connect 80.66.82.249 7777 Nick
/status
```

## Перезапуск после закрытия Termux

```bash
proot-distro login ubuntu
bash termux-setup.sh "BOT_TOKEN" "ADMIN_IDS"
```

Данные живут в `/root/rakb-data` и переживают перезапуск.

## Если сборка под ARM упадёт

Пришли текст ошибки из Termux — поправлю код под ARM. Клиент не использует x86-asm,
так что основные риски — знаковость `char` (уже учтена) и выравнивание структур.
