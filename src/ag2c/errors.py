class AG2CError(RuntimeError):
    """Base error for user-facing AG2C failures."""


class ConfigurationError(AG2CError):
    """Raised when the manifest or policy is invalid."""


class IndexError(AG2CError):
    """Raised when the repository index cannot be built or verified."""


class SliceError(AG2CError):
    """Raised when an entry slice cannot be compiled safely."""


class LedgerError(AG2CError):
    """Raised when the evidence ledger is invalid."""
