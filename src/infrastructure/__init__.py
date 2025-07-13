from dishka import make_async_container
from src.infrastructure.di import PostgresProvider, RedisProvider, RepositoryProvider, ServiceProvider

di_container = make_async_container(PostgresProvider(),
                                    RedisProvider(), RepositoryProvider(), ServiceProvider())