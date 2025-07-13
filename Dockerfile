# ---------- build stage ------------------------------------------------------
FROM python:3.10 AS base

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# ---------- production stage -------------------------------------------------
FROM python:3.10 AS prod
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY --from=base /usr/local/lib/python3.10 /usr/local/lib/python3.10
COPY --from=base /usr/local/bin /usr/local/bin

COPY . .

RUN adduser --disabled-password --gecos "" botuser \
 && chown -R botuser:botuser /app
USER botuser

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "main.py"]