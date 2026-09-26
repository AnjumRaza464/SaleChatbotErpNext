class AppError(Exception):
    """Base application error with an HTTP-friendly message."""

    status_code = 500

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class ERPNextError(AppError):
    status_code = 502


class NotFoundError(AppError):
    status_code = 404


class ValidationError(AppError):
    status_code = 400
