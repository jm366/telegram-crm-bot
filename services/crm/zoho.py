"""Zoho CRM (v6) adapter via OAuth2 REST API.

Docs: https://desk.zoho.com/portal/apideveloper/home
OAuth: https://console.zoho.com/

Requires env vars:
  ZOHO_CLIENT_ID
  ZOHO_CLIENT_SECRET
  ZOHO_REFRESH_TOKEN
  ZOHO_OAUTH_TOKEN_FILE   # optional, defaults to ./.zoho_tokens.json

The token file caches access_token + expiry to avoid excessive refresh calls.
"""

import os
import json
import time
import logging
import asyncio
import aiohttp
from typing import Dict, Any, Optional
from services.crm.base import CRMAdapter

logger = logging.getLogger(__name__)

ZOHO_ACCOUNTS_BASE_URLS = {
    "us": "https://accounts.zoho.com",
    "eu": "https://accounts.zoho.eu",
    "in": "https://accounts.zoho.in",
    "cn": "https://accounts.zoho.com.cn",
    "au": "https://accounts.zoho.com.au",
    "jp": "https://accounts.zoho.jp",
}

ZOHO_API_BASE_URLS = {
    "us": "https://www.zohoapis.com",
    "eu": "https://www.zohoapis.eu",
    "in": "https://www.zohoapis.in",
    "cn": "https://www.zohoapis.com.cn",
    "au": "https://www.zohoapis.com.au",
    "jp": "https://www.zohoapis.jp",
}

class ZohoCrmAdapter(CRMAdapter):
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        dc: str = "us",
    ):
        self.client_id = client_id or os.getenv("ZOHO_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("ZOHO_CLIENT_SECRET", "")
        self.refresh_token = refresh_token or os.getenv("ZOHO_REFRESH_TOKEN", "")
        self.dc = dc or os.getenv("ZOHO_DC", "us")
        self.token_file = os.getenv("ZOHO_OAUTH_FILE", os.path.join(os.path.dirname(__file__), "..", "..", ".zoho_tokens.json"))
        self._token: Optional[str] = None
        self._token_expiry: float = 0  # unix epoch

    # ── Token management ──

    def _load_cached_token(self) -> Optional[str]:
        try:
            with open(self.token_file, "r") as f:
                data = json.load(f)
            expiry = data.get("expires_at", 0)
            if time.time() < expiry - 60:  # 60s buffer
                self._token = data.get("access_token")
                self._token_expiry = expiry
                return self._token
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return None

    def _save_token(self, token: str, expires_in: int):
        self._token = token
        self._token_expiry = time.time() + expires_in
        try:
            with open(self.token_file, "w") as f:
                json.dump({"access_token": token, "expires_at": self._token_expiry}, f)
        except Exception as e:
            logger.warning("Could not cache Zoho token: %s", e)

    async def _get_access_token(self) -> str:
        cached = self._token or self._load_cached_token()
        if cached and time.time() < self._token_expiry - 120:
            return cached
        return await self._refresh_access_token()

    async def _refresh_access_token(self) -> str:
        """POST to Zoho accounts OAuth endpoint."""
        if not self.client_id or not self.client_secret or not self.refresh_token:
            raise RuntimeError("Zoho credentials missing. Set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN.")
        acc_url = ZOHO_ACCOUNTS_BASE_URLS.get(self.dc, ZOHO_ACCOUNTS_BASE_URLS["us"])
        url = f"{acc_url}/oauth/v2/token"
        data = {
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, data=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                body = await resp.json()
        if "access_token" not in body:
            raise RuntimeError(f"Zoho token refresh failed: {body}")
        self._save_token(body["access_token"], body.get("expires_in", 3600))
        return body["access_token"]

    # ── CRMAdapter interface ──

    async def health_check(self) -> bool:
        """Quick fetch of current user."""
        try:
            token = await self._get_access_token()
            api_base = ZOHO_API_BASE_URLS.get(self.dc, ZOHO_API_BASE_URLS["us"])
            url = f"{api_base}/crm/v6/users"
            headers = {"Authorization": f"Zoho-oauthtoken {token}"}
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return resp.status < 400
        except Exception:
            return False

    async def write_lead(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Zoho CRM Lead with normalized fields."""
        token = await self._get_access_token()
        api_base = ZOHO_API_BASE_URLS.get(self.dc, ZOHO_API_BASE_URLS["us"])
        url = f"{api_base}/crm/v6/Leads"
        headers = {
            "Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json",
        }

        # Map normalized fields → Zoho CRM field API names
        # See https://www.zoho.com/crm/help/customer-center/api/leads.html
        zoho_data = {}

        def set_if_present(key: str, value: Any):
            if value is not None and str(value).strip():
                zoho_data[key] = str(value).strip()

        set_if_present("First_Name", fields.get("first_name"))
        set_if_present("Last_Name", fields.get("last_name") or "Unknown")  # required
        set_if_present("Email", fields.get("email"))
        set_if_present("Phone", fields.get("phone"))
        set_if_present("Mobile", fields.get("mobile"))
        set_if_present("Industry", fields.get("industry"))
        set_if_present("Company", fields.get("company"))
        set_if_present("Title", fields.get("title"))
        set_if_present("Street", fields.get("address"))
        set_if_present("City", fields.get("city"))
        set_if_present("Country", fields.get("country"))
        set_if_present("Description", fields.get("notes"))
        set_if_present("Lead_Source", fields.get("source_channel"))
        set_if_present("Website", fields.get("company_website"))
        set_if_present("LinkedIn", fields.get("linkedin"))

        # Custom fields for smartics scoring
        if fields.get("fit_score") is not None:
            zoho_data.setdefault("Lead_Score", int(fields["fit_score"]))
        if fields.get("intent_score") is not None:
            zoho_data.setdefault("Priority", "High" if fields["intent_score"] > 70 else "Normal")

        # Segment as Tag (if available in Zoho)
        segment = fields.get("segment")
        if segment:
            # Zoho Tags are separate API; let's just store in Lead_Source_Description custom field if available
            zoho_data.setdefault("Lead_Source_Description", f"Segment: {segment}")

        payload = {"data": [zoho_data], "trigger": ["approval", "workflow", "blueprint"]}

        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                body = await resp.json()
                logger.info("Zoho response status=%s body=%s", resp.status, body)

        # Parse response
        if body.get("data") and len(body["data"]) > 0:
            record = body["data"][0]
            if record.get("status") == "success":
                crm_id = record.get("details", {}).get("id")
                # Zoho lead detail URL
                lead_url = f"https://crm.zoho.com/crm/tab/Leads/{crm_id}" if crm_id else None
                return {
                    "ok": True,
                    "id": crm_id,
                    "url": lead_url,
                    "error": None,
                    "raw": body,
                }
            else:
                return {
                    "ok": False,
                    "id": None,
                    "url": None,
                    "error": record.get("message", "Zoho returned error"),
                    "raw": body,
                }

        return {
            "ok": False,
            "id": None,
            "url": None,
            "error": body.get("message", "Unexpected Zoho response"),
            "raw": body,
        }
