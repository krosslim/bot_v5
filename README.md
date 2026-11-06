# bot_v5

---

Бот для бронирования мест в офисе

<details>

<summary>
Структура проекта
</summary>

```angular2html
├── Dockerfile
├── README.md
├── alembic
│   ├── README
│   ├── env.py
│   ├── script.py.mako
│   └── versions
├── alembic.ini
├── config.py
├── docker-compose.yml
├── docker-entrypoint.sh
├── main.py
├── pyproject.toml
├── uv.lock
└── src
    ├── clients
    ├── dto
    ├── fsm
    ├── handlers
    │   ├── chat
    │   ├── common
    │   └── user
    ├── infrastructure
    │   └── dishka
    ├── jobs
    ├── middlewares
    ├── services
    ├── storage
    │   ├── postgres
    │   └── redis
    ├── ui
    │   ├── keyboard
    │   └── messages
    ├── use_cases
    └── utils
```

</details>

### Как развернуть локально

---
```bash
# Клонировать репозиторий
https://github.com/krosslim/bot_v5.git
```
#### 1. Настроить проект
```bash
cd bot_v5
cp .env.example .env
```
#### 2. Заполнить .env
```bash
# Токен, выданный BotFather
TOKEN=
# Username бота
BOT_USERNAME=

# Настройки ассинхронного движка Postgres для Sqlalchemy 2. 
# Подробнее: https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.asyncpg
POSTGRES_DB=
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_URL=
POSTGRES_POOL_SIZE=
POSTGRES_MAX_OVERFLOW=
POSTGRES_POOL_TIMEOUT=
POSTGRES_ECHO=
POSTGRES_POOL_PRE_PING=
POSTGRES_POOL_RECYCLE=

# Чат для сотрудников (Бот должен иметь админ права!)
TG_CHAT_ID=

# Для состояний бота (FSM)
REDIS_URL=

# Ссылка на HTTP-метод GoogleSheet API для редактирования таблицы посещений
GOOGLE_SHEET_URL= 
# API-ключ для выполнения HTTP-метода (генерируется на стороне GoogleSheet API)
GOOGLE_SHEET_TOKEN=
# Ссылка на таблицу GoogleSheet
GOOGLE_SHEET_USER_URL=
```
#### 2.1. Управление конектом к GoogleSheet API
> Если нет возможности подключить, 
> то необходимо выключить: 
> <br>#src/jobs/\_\_init_\_\.py<br>
> id джоба = "sheet_update_job"

#### 3. Запустить проект
```bash
docker compose up --build -d
```
#### Запуск без Docker (разработка)
Нужен Python 3.14 и [uv](https://docs.astral.sh/uv/). Зависимости описаны в `pyproject.toml`, точные версии зафиксированы в `uv.lock`.
```bash
uv sync                          # создать .venv на Python 3.14 и поставить зависимости из uv.lock
uv run alembic upgrade head      # применить миграции
uv run python main.py            # запустить бота
```
Добавить или обновить зависимость: `uv add <пакет>` / `uv lock --upgrade-package <пакет>`, затем закоммитить `pyproject.toml` и `uv.lock`.
Docker-образ ставит зависимости через `uv sync --locked`: сборка упадёт, если `uv.lock` не соответствует `pyproject.toml`.

### Виджеты выбора места (Bot API 10.4)

---
Календарь со схемой зала в личном чате и дайджест со схемой в группе работают на HTML-виджетах Telegram.
По умолчанию выключены: бот работает как раньше, но каждой новой брони уже выдаётся номер места.

```bash
# .env
WIDGETS_ENABLED=true          # «Забронировать место» и бронь за сотрудника открывают виджет, «Мои брони» скрыта из меню
DIGEST_WIDGET_ENABLED=true    # дайджест в группе уходит виджетом
WIDGET_HISTORY_MONTHS=3       # сколько прошлых месяцев можно листать в календаре (только просмотр)
# Методы виджетов пока есть только на бете Bot API (обычный токен подходит):
TELEGRAM_API_BASE=https://api.telegram.org/beta
```

- Миграция `e1a7c3f9b2d4` добавляет `bookings.seat_no` и раздаёт места будущим броням по порядку записи: `alembic upgrade head`.
- Схема зала, подпись кабинета и место руководителя: `src/ui/widgets/layout.py`. Шаблоны виджетов: `src/ui/widgets/*.html` (≤ 4096 байт после zlib).
- При старте бот проверяет, есть ли методы виджетов на этом адресе. Если нет, в логе будет подсказка, а бот покажет старые экраны и отправит дайджест текстом.
- Тестовые брони в локальной базе: `uv run python scripts/dev_seed_bookings.py` — сценарии на ноябрь и прошлые дни за `WIDGET_HISTORY_MONTHS`; `--only-past` — только прошлые дни.
- Запросы из виджетов приходят апдейтом `widget_query`, его перехватывает `WidgetQueryMiddleware` (aiogram пока не знает этот тип).
- Отправить дайджест сразу, не дожидаясь 16:00 (только для администраторов, в личке с ботом): `/digest_now` — на ближайший рабочий день, `/digest_now 10.11` — на дату.
- Тесты виджетов без БД: `uv run python -m unittest discover -s tests -t .`
