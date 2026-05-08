"""CRM-agnostic adapter pattern.

Inspired by Zoom's webhook + structured output pattern — this bot extracts
standardized lead data, then writes to ANY CRM via a small adapter.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class CRMAdapter(ABC):
    """Abstract base. Implementations handle specifics of each CRM."""

    @abstractmethod
    async def write_lead(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Create a lead/contact in the CRM.

        Args:
            fields: normalized lead dict from the extraction pipeline
        Returns:
            dict with at minimum {"ok": bool, "id": any, "url": str | None, "error": str | None}
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Quick ping to verify connectivity."""
        ...
