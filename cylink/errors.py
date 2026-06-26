from .exceptions import CylinkError, APIError, AuthenticationError

class CylinkAPIError(CylinkError):
    """Base exception for Cylink SDK errors."""
    pass

__all__ = ["CylinkAPIError", "APIError", "AuthenticationError"]
