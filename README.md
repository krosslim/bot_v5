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
├── requirements.txt
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

# Чат для сотрудников
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