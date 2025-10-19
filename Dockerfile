ARG PY_IMAGE=python:3.10-slim

# -------- build stage --------
FROM ${PY_IMAGE} AS build
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip wheel --no-deps -r requirements.txt -w /app/wheels

# -------- production stage --------
FROM ${PY_IMAGE} AS prod
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN adduser --disabled-password --gecos "" --home /app botuser

COPY --from=build /app/wheels /tmp/wheels
RUN python -m pip install --no-cache-dir /tmp/wheels/* \
 && rm -rf /tmp/wheels

COPY --chown=botuser:botuser . .

RUN chmod +x ./docker-entrypoint.sh

USER botuser
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "main.py"]