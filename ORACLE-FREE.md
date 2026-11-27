# Бесплатный хостинг: Oracle Cloud Always Free (без туннеля)

Oracle Cloud Always Free даёт настоящую VM **навсегда бесплатно**, с открытым
исходящим UDP. На ней запускаем **весь** стек (бот + SA-MP клиент) напрямую —
туннель и реле не нужны, `/connect` работает сразу.

> Нужна настоящая карта Visa/Mastercard для верификации личности (временная
> авторизация ~$1, возвращается). Always Free ресурсы не тарифицируются.
> Prepaid/виртуальные карты обычно не проходят.

## 1. Регистрация

1. Открой [oracle.com/cloud/free](https://www.oracle.com/cloud/free/) → **Sign Up**.
2. Email, пароль, подтверждение телефона.
3. Карта Visa/Mastercard (верификация, списаний за Always Free нет).
4. **Home Region** выбери сразу и навсегда — ближайший к тебе, напр.
   **Germany (Frankfurt)** или **Netherlands (Amsterdam)**. Сменить потом нельзя.

## 2. Создание VM

Console → **Compute → Instances → Create Instance**:

| Поле | Значение |
|---|---|
| Name | `rakb` |
| Image | **Canonical Ubuntu 22.04** (или 24.04) |
| Shape | **Change Shape → AMD → `VM.Standard.E2.1.Micro`** (помечен «Always Free») |
| Networking | новая VCN, **Assign a public IPv4 address** = Yes |
| SSH key | сгенерируй и скачай приватный ключ (или вставь свой публичный) |
| Boot volume | по умолчанию (~47 GB), бесплатно до 200 GB |

**Важно про shape:** бинарник собран под x86-64, поэтому бери именно **AMD**
`VM.Standard.E2.1.Micro`, а не ARM Ampere. AMD micro всегда доступен и подходит
(1 GB RAM + swap из скрипта). ARM может дать больше RAM, но там бывают очереди
ёмкости и другая архитектура.

Нажми **Create**. Через ~1 минуту у инстанса появится **Public IP**.

## 3. Подключение по SSH

```bash
chmod 400 ssh-key-*.key
ssh -i ssh-key-*.key ubuntu@PUBLIC_IP
```

(если образ Oracle Linux, а не Ubuntu — пользователь `opc`, но мы берём Ubuntu.)

## 4. Деплой одной командой

На VM:

```bash
curl -fsSL https://raw.githubusercontent.com/WeteroScript/Rakb/arena/3b12d5df-rakb/scripts/deploy-vps.sh -o deploy-vps.sh
sudo bash deploy-vps.sh "BOT_TOKEN" "ADMIN_IDS"
```

Скрипт сам: добавит 2 GB swap, поставит Docker, склонирует ветку, соберёт образ и
запустит контейнер с `AUTOSTART=1`. Сборка на micro занимает несколько минут.

> Если репозиторий приватный — `git clone` внутри скрипта не пройдёт. Сделай его
> публичным на время деплоя (Settings → Danger Zone → Change visibility) или
> склонируй вручную с токеном в `/opt/rakb` и запусти скрипт ещё раз.

Проверка:

```bash
docker logs -f rakb
# ждём: health on 0.0.0.0:8080 | admins=... | bin=/opt/rakb/bin/raksamp
```

## 5. Управление из Telegram

Входящие порты открывать не нужно (бот ходит в Telegram исходящим polling, клиент
подключается к серверу исходящим UDP). Только SSH 22 уже открыт.

В боте:
```
/nettest                       # теперь референсы и цель должны быть 🟢
/connect 80.66.82.249 5125 Nick
/status
```

## Обновление кода

```bash
ssh -i ssh-key-*.key ubuntu@PUBLIC_IP
sudo bash deploy-vps.sh "BOT_TOKEN" "ADMIN_IDS"   # пересоберёт и перезапустит
```

Данные (`instance.json`, логи) живут в Docker-томе `rakb-data` и переживают
пересборку.
