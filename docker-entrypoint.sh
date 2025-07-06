#!/usr/bin/env bash
set -e

echo "==> Applying DB migrations"
alembic upgrade head

echo "==> Starting bot"
exec "$@"