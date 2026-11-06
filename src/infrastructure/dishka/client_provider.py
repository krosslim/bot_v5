from dishka import Provider, Scope, provide

from src.clients.isdayoff_client import IsDayOffClient


class ClientProvider(Provider):

    @provide(scope=Scope.APP)
    def provide_isdayoff_client(self) -> IsDayOffClient:
        return IsDayOffClient()
