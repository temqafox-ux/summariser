# Telegram digest bot

Python-бот для **супергрупп / групп**: пишет **текст и подписи к медиа** в SQLite, по команде строит **дайджест за календарный день** (часовой пояс `DIGEST_TZ`) через **Z.AI** (OpenAI-совместимый API, модель по умолчанию `glm-5.1`). Повторный запрос за тот же снимок дня отдаёт результат **из кэша** без вызова LLM.

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

## Команды (в группе)

- `/digest` — вчера по календарю в `DIGEST_TZ`.
- `/digest 2026-05-12` — конкретная дата.
- `/digest 2026-05-12 force` или `/digest force` — пересчитать, игнорируя кэш.
- `/digest_today` — сегодня; опционально `/digest_today force`.

**Кто может вызывать:** только пользователи из **`DIGEST_ALLOWED_USER_IDS`** в `.env` — это **числа** (Telegram user id), через запятую. Это **не** «ник» в профиле и **не обязательно** строка `@username` (username может не быть или смениться). Свой id можно посмотреть через ботов вроде [@userinfobot](https://t.me/userinfobot) или [@getidsbot](https://t.me/getidsbot). Старое имя переменной **`ADMIN_USER_IDS`** всё ещё читается, если `DIGEST_ALLOWED_USER_IDS` пустой.

## Переменные окружения

См. [.env.example](.env.example): путь к SQLite, `DIGEST_MAX_MESSAGES` (0 = без лимита; иначе в дайджест попадают **последние** N сообщений дня), `PROMPT_VERSION`, `DIGEST_CHUNK_CHARS`.

## Примечание по Z.AI

Базовый URL по умолчанию: `https://api.z.ai/api/paas/v4` (как в [документации Z.AI](https://docs.z.ai/api-reference/introduction)). Ключ тот же класс, что для OpenAI-совместимых клиентов (например, в Roo Code), если вы используете этот endpoint.
