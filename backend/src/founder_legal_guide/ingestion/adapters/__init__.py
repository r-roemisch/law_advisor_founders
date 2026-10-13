from . import eurlex, gii, us, web  # noqa: F401  (registers the adapters)
from .base import ADAPTERS, SourceAdapter

__all__ = ["ADAPTERS", "SourceAdapter"]
