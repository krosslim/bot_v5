ARG PY_IMAGE=python:3.14-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.7

FROM ${UV_IMAGE} AS uv

# -------- build stage --------
FROM ${PY_IMAGE} AS build
COPY --from=uv /uv /bin/uv

# Окружение собирается из uv.lock системным Python образа, без скачивания своего интерпретатора
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON_PREFERENCE=only-system \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# -------- production stage --------
FROM ${PY_IMAGE} AS prod
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:${PATH}"

RUN adduser --disabled-password --gecos "" --home /app botuser
WORKDIR /app

COPY --from=build /app/.venv /app/.venv
COPY --chown=botuser:botuser . .

RUN chmod +x ./docker-entrypoint.sh

USER botuser
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "main.py"]
