from dishka import Provider, Scope, provide
from config import Config

class ConfigProvider(Provider):
    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self._cfg = cfg

    @provide(scope=Scope.APP)
    def config(self) -> Config:
        return self._cfg