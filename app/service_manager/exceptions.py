class ServiceManagerException(Exception):
    """Raised when a registered report fails to execute."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
