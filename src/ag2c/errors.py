STALE_EXTERNAL_STORE = "AG2C_STALE_EXTERNAL_STORE"
RELOCATED_PROJECT = "AG2C_RELOCATED_PROJECT"
GIT_MISSING = "AG2C_GIT_MISSING"


class AG2CError(RuntimeError):
    """Base error for user-facing AG2C failures."""

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ConfigurationError(AG2CError):
    """Raised when the manifest or policy is invalid."""


class IndexError(AG2CError):
    """Raised when the repository index cannot be built or verified."""


class SliceError(AG2CError):
    """Raised when an entry slice cannot be compiled safely."""


class LedgerError(AG2CError):
    """Raised when the evidence ledger is invalid."""
