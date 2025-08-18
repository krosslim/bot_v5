class UserWarning(Exception):
    """Бизнес предупреждения без необходимости отката транзакции"""
    pass

class UserError(Exception):
    """Бизнес ошибки, требующие отката транзакции"""
    pass

class UserNotFound(UserWarning):
    """Пользователь не найден"""
    pass


class BookingError(Exception):
    pass

class NoCapacityInfo(BookingError):
    """Нет информации о лимитах на день"""
    pass

class FreePlaceIsNotFound(BookingError):
    """Свободных мест за указанный день нет"""
    pass

class BookingIsAlreadyExist(BookingError):
    """Бронь не требуется, так как уже существует"""
    pass

class CancelIsAlreadyExist(BookingError):
    """Повторная бронь"""
    pass

class FreePlaceIsAvailable(BookingError):
    """В процессе постановки в очередь появилось место"""
    pass

class UserIsAlreadyInWaitingList(BookingError):
    """Пользователь уже в очередь, повторно ставить в очередь не нужно"""
    pass

class UserIsAlreadyLeaveQueue(BookingError):
    """Пользователь уже покинул очередь"""
    pass





