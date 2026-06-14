"""Typed exceptions for Atelier.

A small hierarchy so callers can catch Atelier-originated failures distinctly
from arbitrary stdlib errors.
"""


class AtelierError(Exception):
    """Base class for all Atelier-specific errors."""


class DatabaseError(AtelierError):
    """A database operation failed, with added context about what was attempted."""
