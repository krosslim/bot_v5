import asyncio
import logging
import sys

from aiogram import Bot

from config import settings as s


async def check_health():
    try:
        bot = Bot(token=s.TOKEN)
        await bot.get_me()
        await bot.session.close()
        return 0
    except Exception as e:
        logging.error("Health check failed: %s", e)
        return 1


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.ERROR,
        format="[healthcheck] %(levelname)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)]
    )
    sys.exit(asyncio.run(check_health()))