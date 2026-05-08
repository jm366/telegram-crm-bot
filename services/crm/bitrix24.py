"""Bitrix24 CRM adapter via REST API.

Supports two modes:
  1. Webhook (cloud): BITRIX_WEBHOOK_URL
     e.g. https://yourcompany.bitrix24.com/rest/1/WEBHOOK_TOKEN/
  2. OAuth (on-premise): BITRIX_CLIENT_ID + BITRIX_CLIENT_SECRET + BITRIX_REFRESH_TOKEN

Docs: https://training.bitrix24.com/rest_help/

Methods used:
  - user.current         — health check
  - crm.company.list    — search company
  - crm.company.add     — create company
  - crm.contact.add     — create contact
  - crm.contact.company.items.set — link contact to company
"""

import os
import logging
from typing import Dict, Any, Optional
import aiohttp
from services.crm.base import CRMAdapter

logger = logging.getLogger(__name__)

class Bitrix24CrmAdapter(CRMAdapter):
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        self.webhook_url = (webhook_url or os.getenv("BITRIX_WEBHOOK_URL", "")).strip().rstrip("/")
        self.client_id = (client_id or os.getenv("BITRIX_CLIENT_ID", "")).strip()
        self.client_secret = (client_secret or os.getenv("BITRIX_CLIENT_SECRET", "")).strip()
        self.refresh_token = (refresh_token or os.getenv("BITRIX_REFRESH_TOKEN", "")).strip()
        self._oauth_domain = os.getenv("BITRIX_DOMAIN", "").strip().rstrip("/")
        self._access_token = ""

    def _api_url(self, method: str) -> str:
        if self.webhook_url:
            return f"{self.webhook_url}{method}"
        if self._oauth_domain:
            return f"{self._oauth_domain}/rest/{method}"
        raise RuntimeError("Bitrix24 URL missing. Set BITRIX_WEBHOOK_URL or BITRIX_DOMAIN.")

    async def _call(self, method: str, payload: Optional[Dict] = None) -> Dict:
        """ Generic Bitrix API call."""
        url = self._api_url(method)
        async with aiohttp.ClientSession() as sess:
            if payload:
                async with sess.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    return await resp.json()
            else:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    return await resp.json()

    async def health_check(self) -> bool:
        try:
            body = await self._call("user.current")
            return body.get("result") is not None
        except Exception:
            return False

    async def write_lead(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Create or find company
        company_id = None
        company_name = fields.get("company")
        if company_name:
            search = await self._call("crm.company.list", {
                "filter": {"TITLE": company_name},
                "select": ["ID"],
            })
            items = search.get("result", [])
            if items:
                company_id = items[0]["ID"]
            else:
                create = await self._call("crm.company.add", {
                    "fields": {
                        "TITLE": company_name,
                        "INDUSTRY": fields.get("industry", ""),
                        "ADDRESS": fields.get("address", ""),
                    }
                })
                company_id = create.get("result")

        # 2. Create contact
        contact_fields = {
            "NAME": fields.get("first_name", ""),
            "LAST_NAME": fields.get("last_name") or "Unknown",
            "EMAIL": [{"VALUE": fields["email"], "VALUE_TYPE": "WORK"}] if fields.get("email") else [],
            "PHONE": [{"VALUE": fields["phone"], "VALUE_TYPE": "WORK"}] if fields.get("phone") else [],
            "POST": fields.get("title", ""),
            "COMMENTS": fields.get("notes", ""),
        }
        if company_id:
            contact_fields["COMPANY_ID"] = company_id

        body = await self._call("crm.contact.add", {"fields": contact_fields, "params": {"REGISTER_SONET_EVENT": "Y"}})

        contact_id = body.get("result")
        if contact_id:
            # If company was created separately, explicitly link contact to it
            if company_id:
                await self._call("crm.contact.company.items.set", {
                    "id": contact_id,
                    "items": [{"COMPANY_ID": company_id}],
                })
            return {
                "ok": True,
                "id": contact_id,
                "url": f"{self._oauth_domain}/crm/contact/details/{contact_id}/" if self._oauth_domain else None,
                "error": None,
                "raw": body,
            }
        return {
            "ok": False,
            "id": None,
            "url": None,
            "error": body.get("error_description", "Bitrix24 error"),
            "raw": body,
        }
