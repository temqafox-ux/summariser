# Telegram digest bot

Python-бот для **супергрупп / групп**: пишет **текст и подписи к медиа** в SQLite, по команде строит **дайджест за календарный день** (часовой пояс `DIGEST_TZ`) через **Z.AI**. В модель уходит **отфильтрованное** представление дня: сообщения **сгруппированы по пользователю**, длинные реплики **обрезаются** (см. `DIGEST_FILTER_*`). Повторный запрос за тот же снимок дня отдаёт результат **из кэша** без вызова LLM (ключ кэша учитывает `PROMPT_VERSION` и параметры фильтра).

## Требования Telegram

1. Создайте бота в [@BotFather](https://t.me/BotFather), получите `BOT_TOKEN`.
2. В BotFather для бота отключите **Group Privacy** (чтобы бот видел все сообщения в группе), иначе в БД попадёт только часть переписки.
3. Добавьте бота в группу / супергруппу. В `.env` задайте **`DIGEST_ALLOWED_USER_IDS`**: числовые Telegram **user id** тех, кому разрешена команда `/digest` (см. ниже).

## Установка

```bash
cd tgBot
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

Скопируйте [.env.example](.env.example) в `.env` и заполните `BOT_TOKEN` и `Z_AI_API_KEY`.

## Запуск

```bash
python -m tg_digest_bot
```

## Деплой на VPS (Git + systemd)

Предполагается **Debian/Ubuntu**, исходники уже в репозитории на GitHub/GitLab — на сервере делаешь `git clone` / `git pull`.

1. **Python 3.11+**  
   Например Ubuntu 24.04: `sudo apt update && sudo apt install -y git python3 python3-venv`

2. **Пользователь под бота** (не под root), домашний каталог не обязан совпадать с кодом:
   ```bash
   sudo useradd --system --shell /usr/sbin/nologin tgbot
   sudo git clone <URL_твоего_репо> /opt/tg-digest-bot
   sudo chown -R tgbot:tgbot /opt/tg-digest-bot
   ```
   Либо работай под своим пользователем и в unit-файле укажи своего `User`/`Group`.

3. **Код и venv**:
   ```bash
   cd /opt/tg-digest-bot
   sudo -u tgbot bash deploy/bootstrap-vps.sh
   ```
   Скрипт создаёт `.venv`, ставит зависимости `pip install -e .`.

4. **`.env`** в `/opt/tg-digest-bot/.env`, права `chmod 600`. Обязательно задай абсолютный путь к БД, например:
   `DATABASE_PATH=/opt/tg-digest-bot/data/bot.sqlite3`  
   Плюс `BOT_TOKEN`, `Z_AI_API_KEY`, `DIGEST_ALLOWED_USER_IDS`, `DIGEST_TZ`, осмысленный `HTTP_USER_AGENT` (часто просят контакт в UA для внешних API).

5. **systemd**: скопируй [deploy/tg-digest-bot.service.example](deploy/tg-digest-bot.service.example) в `/etc/systemd/system/tg-digest-bot.service`, поправь `User`, `Group`, `WorkingDirectory`, `ExecStart` (путь к `python` внутри `.venv`), затем:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now tg-digest-bot
   journalctl -u tg-digest-bot -f
   ```

6. **Обновление после `git pull`**:
   ```bash
   sudo systemctl stop tg-digest-bot
   cd /opt/tg-digest-bot && sudo -u tgbot git pull
   sudo -u tgbot bash -c 'cd /opt/tg-digest-bot && . .venv/bin/activate && pip install -e .'
   sudo systemctl start tg-digest-bot
   ```

Исходящие HTTPS (Telegram polling, Z.AI, опционально фид лиг) **не требуют** открывать входящий порт на файрволе.

## Деплой в Docker (VPS или локально)

Образ поднимает бота в фоне с **`restart: unless-stopped`**, SQLite лежит на хосте в каталоге **`./data`** (том в `docker-compose.yml`).

1. На сервере: `git clone` / `git pull`, в корне репозитория скопируй [.env.example](.env.example) → `.env`, заполни секреты и настройки. Строку `DATABASE_PATH` в `.env` для Compose **можно не трогать**: в [docker-compose.yml](docker-compose.yml) задано переопределение `DATABASE_PATH=/data/bot.sqlite3` внутри контейнера.

2. Каталог под БД с правами пользователя в образе (**uid 1000**):
   ```bash
   mkdir -p data
   sudo chown 1000:1000 data
   ```

3. Запуск в фоне и логи:
   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```

4. Обновление после коммита:
   ```bash
   git pull
   docker compose up -d --build
   ```

**Если в логах `attempt to write a readonly database`:** процесс в контейнере идёт от **uid 1000**, а каталог `data` или файл `bot.sqlite3` на хосте созданы от **root** (часто после первого запуска без `chown`). Исправление на сервере из каталога с репозиторием:
```bash
sudo chown -R 1000:1000 data
docker compose restart
```
Если файл БД уже есть и не помогает — проверь `ls -la data/` (у каталога и у `*.sqlite3*` должны быть права на запись для владельца 1000). SQLite также пишет в каталог рядом с файлом (WAL), поэтому важны права **на всю папку `data`**, не только на файл.

Нужен **Docker Engine** с поддержкой **`docker compose`** (Compose v2). Входящие порты не нужны.

**Если `apt install docker-compose-plugin` пишет `Unable to locate package`, а `docker compose` — `unknown command`:** чаще всего стоит пакет **`docker.io`** из репозитория дистрибутива без плагина. Варианты:

1. **Правильно (рекомендуется)** — поставить официальный Docker Engine по инструкции для твоей ОС, там же появится плагин:  
   [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/) (для Debian — соседняя страница в меню). После этого:
   ```bash
   sudo apt install -y docker-compose-plugin
   docker compose version
   ```

2. **Быстро, только плагин Compose v2** (если `docker` уже рабочий, но нет `compose`) — бинарник в каталог плагинов CLI:
   ```bash
   sudo mkdir -p /usr/local/lib/docker/cli-plugins
   sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
     -o /usr/local/lib/docker/cli-plugins/docker-compose
   sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
   docker compose version
   ```
   Если `uname -m` не совпадёт с именем файла в релизе (редко), скачай вручную с [страницы релизов compose](https://github.com/docker/compose/releases).

**Не используй устаревший `docker-compose` 1.x** (Python, `docker-compose==1.29.2`): на новом Docker Engine часто падает с `KeyError: 'ContainerConfig'`. Вызывай только **`docker compose`** (с пробелом).

## Команды (в группе)

- `/digest` — вчера по календарю в `DIGEST_TZ`.
- `/digest 2026-05-12` — конкретная дата.
- `/digest 2026-05-12 force` или `/digest force` — пересчитать, игнорируя кэш.
- `/digest_mini` — короткая **цифровая** статистика за вчера (локальный день `DIGEST_TZ`): число сообщений, авторы, топ по репликам, самая длинная фраза, тихий/гучный час, первое/последнее сообщение. Без LLM, без лимита `DIGEST_MAX_MESSAGES` (считается по всем сообщениям дня в БД).
- `/digest_mini 2026-05-12` — за указанную дату; `/digest_mini сегодня` или `today` — за сегодня.
- `/digest_today` — сегодня; опционально `/digest_today force`.
- `/digest_today_raw` — полный сырой JSON за **сегодня** (как в БД по срезу дня).
- `/digest_today_raw_filtered` — JSON **того же представления**, что уходит в LLM: пользователи и списки обрезанных строк, плюс поле `filter` с параметрами.
- `/poe2market` — мемная «новостная» сводка по рынку лиги: сначала запрос **публичного** REST без ключа (агрегатор листингов, настраивается `POE2_SCOUT_*`), затем LLM; в тексте ответа **не** должны светиться названия сторонних сервисов. Статус «Собираю рынок…» перед выдачей. Опционально: `/poe2market Standard` — имя лиги как в фиде (регистр не важен). Без аргумента — `POE2_MARKET_LEAGUE` из `.env` или авто «текущая» софткор.
- `/poe2leagues` — список имён лиг из того же фида (удобно подставить в `/poe2market`).
- `/poe2build` — мемный «вердикт GGG»: по **твоим** сообщениям в этой группе за **сегодня** (`DIGEST_TZ`) LLM подбирает стиль билда Path of Exile 2; скиллы/гемы можно на английском. **`/poe2build @username`** или **`/poe2build username`** — за **сегодня** по сообщениям этого человека (ищем в БД по полю `@username` в сохранённых сообщениях). **`/poe2build @nick 2026-05-12`** или **`/poe2build 2026-05-12 @nick`** — за указанную дату. Без аргумента = сегодня, ты сам; до 450 реплик; длина строк — `DIGEST_FILTER_MAX_MESSAGE_CHARS`.

**Кто может вызывать:** только пользователи из **`DIGEST_ALLOWED_USER_IDS`** в `.env` — это **числа** (Telegram user id), через запятую. Это **не** «ник» в профиле и **не обязательно** строка `@username` (username может не быть или смениться). Свой id можно посмотреть через ботов вроде [@userinfobot](https://t.me/userinfobot) или [@getidsbot](https://t.me/getidsbot). Старое имя переменной **`ADMIN_USER_IDS`** всё ещё читается, если `DIGEST_ALLOWED_USER_IDS` пустой.

## Переменные окружения

См. [.env.example](.env.example): SQLite, `DIGEST_MAX_MESSAGES`, `PROMPT_VERSION`, `DIGEST_CHUNK_CHARS`, **`DIGEST_FILTER_*`**, **`HTTP_USER_AGENT`**, **`POE2_SCOUT_*`** / **`POE2_MARKET_LEAGUE`** для `/poe2market`.

## Примечание по Z.AI

Базовый URL по умолчанию: `https://api.z.ai/api/paas/v4` (как в [документации Z.AI](https://docs.z.ai/api-reference/introduction)). Ключ тот же класс, что для OpenAI-совместимых клиентов (например, в Roo Code), если вы используете этот endpoint.

## Если /digest «молчит»

- В группе часто уходит вариант `/digest@username_бота` — в коде для команд включено `ignore_mention=True`, обновите проект и перезапустите бота.
- В `.env` должен быть непустой **`DIGEST_ALLOWED_USER_IDS`** и в нём **ваш** числовой id — иначе бот ответит текстом про список (если ответа нет вообще — проверьте, что боту разрешено **писать** в группе).
- В консоли при успешном вызове появится строка вида `/digest user_id=…`.

### Ошибка при вызове Z.AI (в чате и в логе)

- **401 / «ошибка авторизации»** — неверный или чужой `Z_AI_API_KEY`; для общего API нужен ключ из [управления ключами Z.AI](https://z.ai/manage-apikey/apikey-list), не токен BotFather.
- **404** — неверный `Z_AI_BASE_URL` или имя модели; для Z.AI обычно `https://api.z.ai/api/paas/v4` и модель `glm-5.1` (не путать с endpoint «Coding Plan»).
- **400** — в тексте ошибки API часто указано, что не так (модель, лимиты и т.д.).
