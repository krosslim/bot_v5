from aiogram.dispatcher.middlewares.data import MiddlewareData
from dishka import AsyncContainer


class ContainerMiddlewareData(MiddlewareData, total=False):
    dishka_container: AsyncContainer

