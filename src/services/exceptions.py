class UserWarn(Exception):
    """Бизнес предупреждения без необходимости отката транзакции"""
    pass

class UserError(Exception):
    """Бизнес ошибки, требующие отката транзакции"""
    pass

class UserNotFound(UserWarn):
    """Пользователь не найден"""
    pass

class FullNameIsIncorrect(UserWarn):
    "Не корректный формат имени"
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

class NoActiveBooking(BookingError):
    """У пользователя нет активных бронирований"""
    pass

class CacheCalDate(BookingError):
    """Не удалось записать в Redis список дат"""
    pass

class CalDateIsNotFound(BookingError):
    """Не удалось получить данные по дате"""
    pass

class NoDataForMissedBooking(BookingError):
    """Нет дат для указанного месяца, чтобы отметиться за предыдущие дни"""
    pass
