class FactoryError(Exception):
    """Base error for user-facing pipeline failures."""


class ConfigurationError(FactoryError):
    pass


class LLMError(FactoryError):
    def __init__(self, message: str, *, status_code: int | None = None, transient: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.transient = transient


class PackageValidationError(FactoryError):
    def __init__(self, diagnostics: list[str]):
        super().__init__("; ".join(diagnostics))
        self.diagnostics = diagnostics
