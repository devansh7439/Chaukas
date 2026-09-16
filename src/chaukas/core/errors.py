"""Exception hierarchy. Every error Chaukas raises on purpose derives from ChaukasError."""


class ChaukasError(Exception):
    """Base class for all Chaukas errors."""


class ConfigError(ChaukasError):
    """Configuration is missing, malformed or fails validation."""


class ClockError(ChaukasError):
    """A clock was asked to move backwards or was otherwise misused."""


class BusClosedError(ChaukasError):
    """An event was published to a bus that has been closed."""
