"""Domain exceptions shared by API, CLI and providers."""


class NovelHarnessError(Exception):
    """Base class for expected application errors."""


class ConfigurationError(NovelHarnessError):
    """The runtime configuration is invalid."""


class AuthenticationError(NovelHarnessError):
    """A request does not carry valid user authentication."""


class BillingUnavailableError(NovelHarnessError):
    """The billing service cannot authorize a paid operation."""


class InsufficientBalanceError(NovelHarnessError):
    """The authenticated user has no remaining balance."""


class ResourceNotFoundError(NovelHarnessError):
    """A requested domain resource does not exist."""


class ConflictError(NovelHarnessError):
    """A write conflicts with the current resource version."""


class WorkflowStateError(ConflictError):
    """A workflow transition is invalid for its current state."""


class DocumentError(NovelHarnessError):
    """A document cannot be validated or parsed."""


class ProviderError(NovelHarnessError):
    """A provider call failed."""


class ProviderUnavailableError(ProviderError):
    """A provider cannot currently serve requests."""


class ProviderResponseError(ProviderError):
    """A provider returned an invalid response."""


class OriginalityError(NovelHarnessError):
    """A draft is too similar to an ingested source."""
