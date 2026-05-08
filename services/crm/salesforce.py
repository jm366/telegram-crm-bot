"""Salesforce CRM REST API adapter (v58.0+) via OAuth2.

Requires env vars:
  SFDC_CLIENT_ID
  SFDC_CLIENT_SECRET
  SFDC_REFRESH_TOKEN
  SFDC_INSTANCE_URL          # e.g. https://yourinstance.my.salesforce.com

Or simpler (if you already have a session):
  SFDC_ACCESS_TOKEN
  SFDC_INSTANCE_URL

Docs: https://developer.salesforce.com/docs/atlas.en-us.238.0.api_rest.meta/api_rest/
"""

import os
import json
import time
import logging
from typing import Dict, Any, Optional
import aiohttp
from services.crm.base import CRMAdapter

logger = logging.getLogger(__name__)

SALESFORCE_LOGIN_URL = "https://login.salesforce.com/services/oauth2/token"

class SalesforceCrmAdapter(CRMAdapter):
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        access_token: Optional[str] = None,
        instance_url: Optional[str] = None,
    ):
        self.client_id = (client_id or os.getenv("SFDC_CLIENT_ID", "")).strip()
        self.client_secret = (client_secret or os.getenv("SFDC_CLIENT_SECRET", "")).strip()
        self.refresh_token = (refresh_token or os.getenv("SFDC_REFRESH_TOKEN", "")).strip()
        self._access_token = (access_token or os.getenv("SFDC_ACCESS_TOKEN", "")).strip()
        self.instance_url = (instance_url or os.getenv("SFDC_INSTANCE_URL", "")).strip().rstrip("/")

    async def _ensure_token(self) -> str:
        if self._access_token:
            return self._access_token
        if not all([self.client_id, self.client_secret, self.refresh_token]):
            raise RuntimeError("Salesforce credentials missing. Set SFDC_CLIENT_ID, SFDC_CLIENT_SECRET, SFDC_REFRESH_TOKEN (or SFDC_ACCESS_TOKEN).")
        async with aiohttp.ClientSession() as sess:
            data = {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            }
            async with sess.post(SALESFORCE_LOGIN_URL, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                body = await resp.json()
        if "access_token" not in body:
            raise RuntimeError(f"Salesforce token refresh failed: {body}")
        self._access_token = body["access_token"]
        if not self.instance_url and "instance_url" in body:
            self.instance_url = body["instance_url"].rstrip("/")
        return self._access_token

    async def health_check(self) -> bool:
        try:
            token = await self._ensure_token()
            url = f"{self.instance_url}/services/data/v58.0/limits"
            headers = {"Authorization": f"Bearer {token}"}
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return resp.status < 400
        except Exception:
            return False

    async def write_lead(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        token = await self._ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # 1. Find or create Account (company)
        account_id = None
        company = fields.get("company")
        if company:
            escaped = company.replace("'", "\\'")
            soql = f"SELECT Id FROM Account WHERE Name = '{escaped}'"
            search_url = f"{self.instance_url}/services/data/v58.0/query?q={soql}"
            async with aiohttp.ClientSession() as sess:
                async with sess.get(search_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    result = await resp.json()
            records = result.get("records", [])
            if records:
                account_id = records[0]["Id"]
            else:
                # Create account
                create_url = f"{self.instance_url}/services/data/v58.0/sobjects/Account/"
                payload = {"Name": company}
                async with aiohttp.ClientSession() as sess:
                    async with sess.post(create_url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        body = await resp.json()
                if body.get("success"):
                    account_id = body.get("id")

        # 2. Create Contact
        contact_payload: Dict[str, Any] = {}
        if fields.get("first_name"):
            contact_payload["FirstName"] = fields["first_name"]
        if fields.get("last_name"):
            contact_payload["LastName"] = fields["last_name"]
        else:
            contact_payload["LastName"] = "Unknown"
        if fields.get("email"):
            contact_payload["Email"] = fields["email"]
        if fields.get("phone"):
            contact_payload["Phone"] = fields["phone"]
        if fields.get("title"):
            contact_payload["Title"] = fields["title"]
        if fields.get("industry"):
            contact_payload["Industry"] = fields["industry"]
        if fields.get("notes"):
            contact_payload["Description"] = fields["notes"]
        if account_id:
            contact_payload["AccountId"] = account_id

        create_contact_url = f"{self.instance_url}/services/data/v58.0/sobjects/Contact/"
        async with aiohttp.ClientSession() as sess:
            async with sess.post(create_contact_url, headers=headers, json=contact_payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                body = await resp.json()

        if body.get("success"):
            contact_id = body.get("id")
            return {
                "ok": True,
                "id": contact_id,
                "url": f"{self.instance_url.rstrip('/')}/{contact_id}",
                "error": None,
                "raw": body,
            }
        else:
            return {
                "ok": False,
                "id": None,
                "url": None,
                "error": body.get("errors", [{"message": "Unknown"}])[0].get("message", "Salesforce error"),
                "raw": body,
            }
