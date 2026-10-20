class FactoryError(Exception):
    """Base class for factory errors."""


class PluginNotFound(FactoryError):
    pass


class WorkflowError(FactoryError):
    """The workflow definition is invalid (raised before anything runs)."""


class RoutingError(FactoryError):
    """A request cannot be routed safely (nothing fits, not confident, router unavailable)."""


class VagueRequest(RoutingError):
    """The workflow is clear but the request lacks what it needs to start."""
