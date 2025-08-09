class BookingServiceExceptions(Exception):
    pass

class FreePlaceIsNotFound(BookingServiceExceptions):
    pass

class BookingIsAlreadyExist(BookingServiceExceptions):
    pass

class CancelIsAlreadyExist(BookingServiceExceptions):
    pass

class FreePlaceIsAvailable(BookingServiceExceptions):
    pass

class UserIsAlreadyInWaitingList(BookingServiceExceptions):
    pass

class UserIsAlreadyPromoted(BookingServiceExceptions):
    pass