"""Web-search provider implementations."""

from .base import (
    SearchConfigurationError,
    SearchError,
    SearchProvider,
    SearchQuery,
    SearchResult,
    SearchTransportError,
)
from .mock import MockSearchProvider
from .searxng import SearXNGSearchProvider

__all__ = [
    "MockSearchProvider",
    "SearchConfigurationError",
    "SearchError",
    "SearchProvider",
    "SearchQuery",
    "SearchResult",
    "SearchTransportError",
    "SearXNGSearchProvider",
]
