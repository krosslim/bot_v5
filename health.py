"""Healthcheck контейнера: бот жив, если недавно обновил метку (src/infrastructure/liveness.py).

Без сети и тяжёлых импортов: проверка идёт миллисекунды и не зависит от доступности Telegram и загрузки CPU."""
import sys

from src.infrastructure.liveness import LIVENESS_FILE, MAX_AGE, is_alive

if __name__ == "__main__":
    if is_alive():
        sys.exit(0)
    print(f"[healthcheck] метка {LIVENESS_FILE} отсутствует или старше {MAX_AGE} с", file=sys.stderr)
    sys.exit(1)
