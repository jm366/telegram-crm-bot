"""CRM Adapter Factory.

Select adapter via env var CRM_PROVIDER:
  - "zoho"   → Zoho CRM via OAuth2 REST API
  - "gtm-os" → GTM-OS local SQLite (default if unspecified)
"""

import os
import logging
from typing import Optional
from services.crm.base import CRMAdapter
from services.crm.zoho import ZohoCrmAdapter
from services.crm.gtmos import GtmosAdapter

logger = logging.getLogger(__name__)

_PROVIDER: Optional[str] = None

def get_provider_name() -> str:
    return os.getenv("CRM_PROVIDER", "gtm-os").strip().lower()

async def get_adapter() -> CRMAdapter:
    """Return the configured CRM adapter."""
    name = get_provider_name()
    if name == "zoho":
        return ZohoCrmAdapter()
    elif name == "gtm-os":
        return GtmosAdapter()
    else:
        # If user specified an unknown provider, warn and fall back to GTM-OS
        logger.warning("Unknown CRM_PROVIDER='%s', falling back to gtm-os", name)
        return GtmosAdapter()

async def adapter_info() -> str:
    """Return current adapter name for status display."""
    name = get_provider_name()
    adapter = await get_adapter()
    healthy = await adapter.health_check()
    status = "🟢 Connected" if healthy else "🔴 Unreachable"
    return f"Currently using: {name} CRM — {status}"
