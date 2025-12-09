"""
Lightweight compatibility helpers for older Python versions.
"""

from enum import Enum


try:  # Python 3.11+
    from enum import StrEnum  # type: ignore
except ImportError:
    class StrEnum(str, Enum):  # type: ignore
        """
        Minimal backport of Python 3.11's StrEnum for Python 3.9/3.10.
        """

        def __str__(self) -> str:  # pragma: no cover - trivial
            return str(self.value)
