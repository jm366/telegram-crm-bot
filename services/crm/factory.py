"""CRM Adapter Factory.

Select adapter via env var CRM_PROVIDER:
  - "zoho"       → Zoho CRM via OAuth2 REST API
  - "hubspot"    → HubSpot CRM via Private App token
  - "pipedrive"  → Pipedrive CRM via API token
  - "salesforce" → Salesforce CRM via OAuth2
  - "bitrix24"   → Bitrix24 via webhook or OAuth
  - "odoo"       → Odoo CRM via XML-RPC
  - "gtm-os"     → GTM-OS local SQLite (default)
"""

import os
import logging
from typing import Optional
from services.crm.base import CRMAdapter
from services.crm.zoho import ZohoCrmAdapter
from services.crm.hubspot import HubSpotCrmAdapter
from services.crm.pipedrive import PipedriveCrmAdapter
from services.crm.salesforce import SalesforceCrmAdapter
from services.crm.bitrix24 import Bitrix24CrmAdapter
from services.crm.odoo import OdooCrmAdapter
from services.crm.gtmos import GtmosAdapter

logger = logging.getLogger(__name__)

def get_provider_name() -> str:
    return os.getenv("CRM_PROVIDER", "gtm-os").strip().lower()

async def get_adapter() -> CRMAdapter:
    """Return the configured CRM adapter."""
    name = get_provider_name()
    adapters = {
        "zoho": ZohoCrmAdapter,
        "hubspot": HubSpotCrmAdapter,
        "pipedrive": PipedriveCrmAdapter,
        "salesforce": SalesforceCrmAdapter,
        "bitrix24": Bitrix24CrmAdapter,
        "bitrix": Bitrix24CrmAdapter,
        "odoo": OdooCrmAdapter,
        "gtm-os": GtmosAdapter,
    }
    if name in adapters:
        return adapters[name]()
    # If user specified an unknown provider, warn and fall back to GTM-OS
    logger.warning("Unknown CRM_PROVIDER='%s', falling back to gtm-os", name)
    return GtmosAdapter()

async def adapter_info() -> str:
    """Return current adapter name for status display."""
    name = get_provider_name()
    # Use nice display names
    display_names = {
        "zoho": "Zoho CRM",
        "hubspot": "HubSpot CRM",
        "pipedrive": "Pipedrive CRM",
        "salesforce": "Salesforce",
        "bitrix24": "Bitrix24",
        "bitrix": "Bitrix24",
        "odoo": "Odoo CRM",
        "gtm-os": "GTM-OS",
    }
    display = display_names.get(name, name)
    adapter = await get_adapter()
    try:
        healthy = await adapter.health_check()
    except Exception:
        healthy = False
    status = "🟢 Connected" if healthy else "🔴 Unreachable"
    return f"Currently using: {display} — {status}"
