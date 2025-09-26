import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.postgres.models import Product, Profession, SystemConfig
from src.utils.app_configuration.register import SystemTask

logger = logging.getLogger(__name__)


@SystemTask.register("init_professions_products_dict", "Настройка справочников продуктов и профессий")
async def init_professions_products_dict(session: AsyncSession) -> None:

    async with session.begin():
        products = [
            {"name": "Веб КЦ (общее)"},
            {"name": "Поддержка (продавцы)"},
            {"name": "Поддержка (покупатели)"},
            {"name": "Телефония"},
            {"name": "Роботизация"},
            {"name": "АРМ Банка"},
            {"name": "Чаты"},
            {"name": "WFM / База знаний"}
        ]
        await session.execute(insert(Product).values(products))

        professions = [
            {"name": "Веб КЦ (общее)"},
            {"name": "Системный аналитик"},
            {"name": "Разработчик"},
            {"name": "Тестировщик"},
            {"name": "Продуктовый менеджер"},
            {"name": "Проектный менеджер"}
        ]
        await session.execute(insert(Profession).values(professions))

        await session.execute(insert(SystemConfig)
                .values(key="init_professions_products_dict", value=f"done"))

        logger.info(f"Task 'init_professions_products_dict' is done")