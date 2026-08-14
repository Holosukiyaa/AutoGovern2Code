class DEGError(RuntimeError):
    """Base error for user-facing DEG failures."""


class ConfigurationError(DEGError):
    """Raised when the manifest or policy is invalid."""


class IndexError(DEGError):
    """Raised when the repository index cannot be built or verified."""


class SliceError(DEGError):
    """Raised when an entry slice cannot be compiled safely."""


class LedgerError(DEGError):
    """Raised when the evidence ledger is invalid."""
