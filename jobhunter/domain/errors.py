"""Domain/application errors. Interfaces map these to HTTP status codes or CLI exit messages."""


class JobHunterError(Exception):
    """Base class for expected, user-facing errors."""


class NotFound(JobHunterError):
    pass


class InvalidInput(JobHunterError):
    pass


class Conflict(JobHunterError):
    pass


class RunBusy(Conflict):
    pass


class BudgetExceeded(JobHunterError):
    pass


class NotConfigured(JobHunterError):
    """An optional integration (Gmail, Hunter...) isn't set up."""


class Unauthorized(JobHunterError):
    pass


class Forbidden(JobHunterError):
    pass
