"""Pipedrive CRM (v1) adapter via REST API.

Auth: API token sent as query param ?api_token=TOKEN
Base URL: https://{PIPEDRIVE_DOMAIN}.pipedrive.com

Requires env vars:
  PIPEDRIVE_API_TOKEN
  PIPEDRIVE_DOMAIN
"""

import os
import logging
import aiohttp
from typing import Dict, Any, Optional
from services.crm.base import CRMAdapter

logger = logging.getLogger(__name__)


class PipedriveCrmAdapter(CRMAdapter):
    def __init__(
        self,
        api_token: Optional[str] = None,
        domain: Optional[str] = None,
    ):
        self.api_token = api_token or os.getenv("PIPEDRIVE_API_TOKEN", "")
        self.domain = domain or os.getenv("PIPEDRIVE_DOMAIN", "")

    @property
    def _base_url(self) -> str:
        return f"https://{self.domain}.pipedrive.com"

    def _get_query_params(self) -> Dict[str, str]:
        return {"api_token": self.api_token}

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> tuple[int, Dict[str, Any]]:
        """Send an authenticated HTTP request to Pipedrive v1."""
        if not self.api_token or not self.domain:
            raise RuntimeError(
                "Pipedrive credentials missing. Set PIPEDRIVE_API_TOKEN and PIPEDRIVE_DOMAIN."
            )

        url = f"{self._base_url}/v1{endpoint}"
        params = self._get_query_params()
        timeout = aiohttp.ClientTimeout(total=15)

        async with aiohttp.ClientSession() as sess:
            async with sess.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                timeout=timeout,
            ) as resp:
                body = await resp.json()
                return resp.status, body

    async def health_check(self) -> bool:
        """Ping /v1/users/me to verify connectivity."""
        try:
            status, body = await self._request("GET", "/users/me")
            return status < 400 and body.get("success", False)
        except Exception:
            return False

    async def write_lead(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Pipedrive Person (lead/contact).

        If a company name is present, first creates an Organization
        and links it via org_id on the Person.
        """
        org_id = None
        company = fields.get("company")
        # Create organization first if company name exists
        if company and str(company).strip():
            org_id = await self._create_or_find_organization(str(company).strip())

        # Build person payload
        payload: Dict[str, Any] = {
            "name": self._build_full_name(fields),
        }

        email = fields.get("email")
        if email and str(email).strip():
            payload["email"] = [{"value": str(email).strip(), "primary": True}]

        phone = fields.get("phone")
        if phone and str(phone).strip():
            payload["phone"] = [{"value": str(phone).strip(), "primary": True}]

        if org_id is not None:
            payload["org_id"] = org_id

        notes = fields.get("notes")
        if notes and str(notes).strip():
            payload["notes"] = str(notes).strip()

        status, body = await self._request("POST", "/persons", json_data=payload)
        logger.info("Pipedrive write_lead status=%s", status)

        # Parse response
        if status < 400 and body.get("success", False):
            data = body.get("data", {})
            person_id = data.get("id")
            lead_url = (
                f"https://{self.domain}.pipedrive.com/person/{person_id}"
                if person_id
                else None
            )
            return {
                "ok": True,
                "id": person_id,
                "url": lead_url,
                "error": None,
                "raw": body,
            }

        error_msg = body.get("error", "Pipedrive returned error")
        return {
            "ok": False,
            "id": None,
            "url": None,
            "error": error_msg,
            "raw": body,
        }

    def _build_full_name(self, fields: Dict[str, Any]) -> str:
        parts = []
        first = fields.get("first_name")
        last = fields.get("last_name")
        if first and str(first).strip():
            parts.append(str(first).strip())
        if last and str(last).strip():
            parts.append(str(last).strip())
        if parts:
            return " ".join(parts)
        return fields.get("name") or fields.get("email") or "Unknown"

    async def _create_or_find_organization(self, org_name: str) -> Optional[int]:
        """Search for an existing org by name; create one if not found."""
        # Search existing organization by name
        try:
            status, body = await self._request(
                "GET",
                "/organizations/find",
                json_data=None,
            )
        except Exception:
            # If search fails, fall through to create
            status, body = 0, {}

        # Pipedrive /organizations/find requires a 'term' query param
        # Re-issue with query string param
        search_url = f"{self._base_url}/v1/organizations/find"
        params = {**self._get_query_params(), "term": org_name}
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession() as sess:
            async with sess.get(search_url, params=params, timeout=timeout) as resp:
                body = await resp.json()
                if resp.status < 400 and body.get("success", False):
                    items = body.get("data", []) or []
                    if items:
                        return items[0].get("id")

        # Not found — create organization
        try:
            status, body = await self._request(
                "POST",
                "/organizations",
                json_data={"name": org_name},
            )
            if status < 400 and body.get("success", False):
                return body.get("data", {}).get("id")
        except Exception:
            logger.warning("Failed to create Pipedrive organization for '%s'", org_name)

        return None
