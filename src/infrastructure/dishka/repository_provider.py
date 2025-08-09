from dishka import Provider, provide, Scope
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.postgres.repository import Repository


class RepositoryProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_repository(self, session: AsyncSession) -> Repository:
        return Repository(session)