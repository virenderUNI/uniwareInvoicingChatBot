from contextvars import ContextVar
from typing import Optional

# ContextVar to store the RequestContext for each request
_request_context: ContextVar[Optional['RequestContext']] = ContextVar('request_context', default=None)

class RequestContext:
    """Stores request-specific data like tenantCode, userId, and sessionId."""
    def __init__(self):
        self._storage = {}

    def set(self, key: str, value: str):
        self._storage[key] = value

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._storage.get(key, default)

    def clear(self):
        self._storage.clear()

    @staticmethod
    def current() -> 'RequestContext':
        """Returns the current request-specific context."""
        context = _request_context.get()
        if context is None:
            raise RuntimeError("No RequestContext available. Ensure middleware is configured and called within a request scope.")
        return context

    @staticmethod
    def set_current(context: Optional['RequestContext']):
        """Sets the current request-specific context."""
        _request_context.set(context)