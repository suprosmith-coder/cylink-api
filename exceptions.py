class CylinkError(Exception):
    """Base exception for Cylink SDK."""
    pass


class AuthenticationError(CylinkError):
    pass


class APIError(CylinkError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code