import inspect
import logging
import random
from functools import wraps
from typing import Any, Callable, Coroutine, TypeVar

from sqlalchemy.exc import SQLAlchemyError, DBAPIError, ProgrammingError
from asyncpg.exceptions import PostgresError

logger = logging.getLogger(__name__)


T = TypeVar("T")

class DBError(Exception):
    pass

def handle_db_errors(
    func: Callable[..., Coroutine[Any, Any, T]]
) -> Callable[..., Coroutine[Any, Any, T]]:

    if not inspect.iscoroutinefunction(func):
        raise TypeError(
            f"@handle_db_errors применим только к async-функциям, "
            f"но передан {func.__qualname__!r}"
        )

    @wraps(func)
    async def wrapper(*args, **kwargs) -> T:

        try:
            return await func(*args, **kwargs)

        except (
                SQLAlchemyError, DBAPIError, PostgresError, ProgrammingError,
                ConnectionError, TimeoutError
        ) as exc:

            session = getattr(args[0], "session", None)
            if session and session.in_transaction():
                await session.rollback()

            logger.exception(
                "DB error in %s",
                func.__qualname__
            )
            raise DBError from exc

    return wrapper


def with_db_errors(cls):
    for name, method in inspect.getmembers(cls, inspect.iscoroutinefunction):
        if not name.startswith("__"):
            setattr(cls, name, handle_db_errors(method))
    return cls