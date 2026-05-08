"""HubSpot CRM REST API v3 adapter via Private App Access Token.

Docs: https://developers.hubspot.com/docs/api/crm/

Requires env var:
  HUBSPOT_ACCESS_TOKEN   # Private app token (starts with pat-na1, pat-eu1, etc.)

Endpoints used:
  GET  /integrations/v1/me                          – health check
  POST /crm/v3/objects/contacts                     – create contact
  POST /crm/v3/objects/companies/search             – search company by domain/name
  POST /crm/v3/objects/companies                    – create company if missing
  POST /crm/v3/associations/{from}/{fromId}/{to}/{toId} – associate contact ↔ company
"""

import os
import logging
from typing import Dict, Any, Optional

import aiohttp
from services.crm.base import CRMAdapter

logger = logging.getLogger(__name__)

HUBSPOT_API_BASE = "https://api.hubapi.com"


class HubSpotCrmAdapter(CRMAdapter):
    def __init__(self, access_token: Optional[str] = None):
        self.access_token = (access_token or os.getenv("HUBSPOT_ACCESS_TOKEN", "")).strip()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    # ── Private helpers ──

    async def _request(
        self,
        method: str,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: int = 15,
    ) -> Dict[str, Any]:
        url = f"{HUBSPOT_API_BASE}{path}"
        async with aiohttp.ClientSession() as sess:
            async with sess.request(
                method,
                url,
                headers=self._headers(),
                json=json_body,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                body = await resp.json()
                logger.debug("HubSpot %s %s → status=%s body=%s", method, path, resp.status, body)
                return {"status": resp.status, "body": body}

    async def _search_company(self, name: str) -> Optional[int]:
        """Search for a company by exact name. Return the internal company ID or None."""
        if not name or not name.strip():
            return None
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {"propertyName": "name", "operator": "EQ", "value": name.strip()},
                    ]
                }
            ],
            "properties": ["name"],
            "limit": 1,
        }
        result = await self._request("POST", "/crm/v3/objects/companies/search", json_body=payload)
        if result["status"] >= 400:
            logger.warning("HubSpot company search failed: %s", result["body"])
            return None
        results = result["body"].get("results", [])
        if results:
            company_id = results[0].get("id")
            logger.info("HubSpot company found: id=%s name='%s'", company_id, name.strip())
            return int(company_id)
        return None

    async def _create_company(self, name: str) -> Optional[int]:
        """Create a minimal company and return its internal ID."""
        payload = {
            "properties": {
                "name": name.strip(),
            }
        }
        result = await self._request("POST", "/crm/v3/objects/companies", json_body=payload)
        if result["status"] >= 400:
            logger.error("HubSpot company create failed: %s", result["body"])
            return None
        company_id = result["body"].get("id")
        logger.info("HubSpot company created: id=%s name='%s'", company_id, name.strip())
        return int(company_id) if company_id else None

    async def _associate_contact_to_company(
        self, contact_id: int, company_id: int
    ) -> bool:
        """Create a standard contact-to-company association."""
        # Association type IDs:
        #   contact-to-company (primary) = 1 in HubSpot V4 associations API,
        #   but the V3 legacy association endpoint used here (without associationTypeId)
        #   defaults to the primary association. We use the V3 PUT/POST endpoint shape:
        #   POST /crm/v3/associations/{fromObjectType}/{fromObjectId}/{toObjectType}/{toObjectType}/{toObjectId}
        #   with payload specifying associationCategory + associationTypeId for V4 compatibility.
        #   Using HubSpot's newest recommended V4 endpoint for explicit safety:
        path = f"/crm/v4/objects/contacts/{contact_id}/associations/companies/{company_id}"
        payload = [
            {
                "associationCategory": "HUBSPOT_DEFINED",
                "associationTypeId": 1,  # contact to company (primary)
            }
        ]
        result = await self._request("PUT", path, json_body=payload)
        if result["status"] >= 400:
            logger.error(
                "HubSpot association failed contact=%s company=%s: %s",
                contact_id,
                company_id,
                result["body"],
            )
            return False
        logger.info(
            "HubSpot associated contact %s → company %s", contact_id, company_id
        )
        return True

    # ── CRMAdapter interface ──

    async def health_check(self) -> bool:
        """Ping HubSpot integrations/v1/me endpoint."""
        if not self.access_token:
            logger.warning("HubSpot access token missing; health check skipped.")
            return False
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(
                    f"{HUBSPOT_API_BASE}/integrations/v1/me",
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    return resp.status < 400
        except Exception as exc:
            logger.warning("HubSpot health check error: %s", exc)
            return False

    async def write_lead(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Create a HubSpot Contact with normalized fields and optionally link to a Company."""
        if not self.access_token:
            raise RuntimeError(
                "HubSpot access token missing. Set HUBSPOT_ACCESS_TOKEN environment variable."
            )

        # Build contact properties
        props = {}

        def set_if_present(hubspot_prop: str, value: Any):
            if value is not None and str(value).strip():
                props[hubspot_prop] = str(value).strip()

        set_if_present("firstname", fields.get("first_name"))
        set_if_present("lastname", fields.get("last_name") or "Unknown")
        set_if_present("email", fields.get("email"))
        set_if_present("phone", fields.get("phone"))
        set_if_present("jobtitle", fields.get("title"))

        # Optional extras HubSpot knows about
        set_if_present("mobilephone", fields.get("mobile"))
        set_if_present("company", fields.get("company"))
        set_if_present("address", fields.get("address"))
        set_if_present("city", fields.get("city"))
        set_if_present("country", fields.get("country"))
        set_if_present("industry", fields.get("industry"))
        set_if_present("website", fields.get("company_website"))

        payload = {"properties": props}

        result = await self._request("POST", "/crm/v3/objects/contacts", json_body=payload)
        status = result["status"]
        body = result["body"]

        if status >= 400:
            logger.error("HubSpot create contact failed: status=%s body=%s", status, body)
            msg = body.get("message", f"HTTP {status}")
            if "errors" in body and body["errors"]:
                msg = body["errors"][0].get("message", msg)
            return {
                "ok": False,
                "id": None,
                "url": None,
                "error": msg,
                "raw": body,
            }

        contact_id = body.get("id")
        contact_url = (
            f"https://app.hubspot.com/contacts/{contact_id}"
            if contact_id else None
        )

        logger.info("HubSpot contact created: id=%s", contact_id)

        # ── Company search / create / associate ──
        company_name = fields.get("company")
        if company_name and company_name.strip():
            company_id = await self._search_company(company_name)
            if not company_id:
                company_id = await self._create_company(company_name)
            if company_id and contact_id:
                await self._associate_contact_to_company(int(contact_id), company_id)

        return {
            "ok": True,
            "id": contact_id,
            "url": contact_url,
            "error": None,
            "raw": body,
        }
