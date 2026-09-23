"""Exception hierarchy. Every error Chaukas raises on purpose derives from ChaukasError."""


class ChaukasError(Exception):
    """Base class for all Chaukas errors."""


class ConfigError(ChaukasError):
    """Configuration is missing, malformed or fails validation."""


class ClockError(ChaukasError):
    """A clock was asked to move backwards or was otherwise misused."""


class BusClosedError(ChaukasError):
    """An event was published to a bus that has been closed."""


class LLMError(ChaukasError):
    """Base class for LLM failures; the engine falls back to keywords for that window."""


class LLMReplyError(LLMError):
    """The LLM answered, but not with a usable JSON object."""


class LLMUnavailableError(LLMError):
    """The LLM server could not be reached, timed out or answered with an HTTP error.

    ``elapsed_s`` is how long the attempt took, so a timeout still costs replay time.
    """

    def __init__(self, message: str, *, elapsed_s: float = 0.0) -> None:
        super().__init__(message)
        self.elapsed_s = elapsed_s
