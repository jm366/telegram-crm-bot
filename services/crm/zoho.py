"""Zoho CRM (v6) adapter via OAuth2 REST API.

Creates BOTH a Lead (Contact) and a linked Deal on extraction.

Required env:
  ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN,
  ZOHO_DC (us/eu/in/cn/au/jp)
"""

import os
import json
import logging
import asyncio
import aiohttp
import time
from typing import Dict, Any, Optional
from services.crm.base import CRMAdapter

logger = logging.getLogger(__name__)

ZOHO_ACCOUNTS_URLS = {
    "us": "https://accounts.zoho.com",
    "eu": "https://accounts.zoho.eu",
    "in": "https://accounts.zoho.in",
    "cn": "https://accounts.zoho.com.cn",
    "au": "https://accounts.zoho.com.au",
    "jp": "https://accounts.zoho.jp",
}

ZOHO_API_URLS = {
    "us": "https://www.zohoapis.com",
    "eu": "https://www.zohoapis.eu",
    "in": "https://www.zohoapis.in",
    "cn": "https://www.zohoapis.com.cn",
    "au": "https://www.zohoapis.com.au",
    "jp": "https://www.zohoapis.jp",
}


def _zoho_picklist(value: str, picklist: list) -> str:
    """Map a free-form value to the closest Zoho picklist option."""
    if not value:
        return picklist[0]  # default
    v = value.strip().lower()
    for opt in picklist:
        if v == opt.lower():
            return opt
    # Fuzzy fallback
    if v in ("decision maker", "decision_maker", "owner", "ceo", "md", "vp"):
        return "Decision Maker"
    if v in ("technical", "engineer", "architect"):
        return "Technical"
    if v in ("influencer", "manager"):
        return "Influencer"
    if v in ("procurement", "purchaser", "buyer"):
        return "Procurement"
    if "negotiation" in v:
        return "Negotiation"
    if "proposal" in v:
        return "Proposal"
    if "discovery" in v:
        return "Discovery"
    if "close" in v or "won" in v:
        return "Closed Won"
    return picklist[0]


class ZohoCrmAdapter(CRMAdapter):
    """Zoho adapter: writes a Lead (Contacts) and optionally a Deal."""

    def __init__(self, dc: Optional[str] = None):
        self.client_id = os.getenv("ZOHO_CLIENT_ID", "")
        self.client_secret = os.getenv("ZOHO_CLIENT_SECRET", "")
        self.refresh_token = os.getenv("ZOHO_REFRESH_TOKEN", "")
        self.dc = (dc or os.getenv("ZOHO_DC", "us")).lower()
        self._token: Optional[str] = None
        self._token_expiry: float = 0

    # ── Token ──

    async def _refresh_access_token(self) -> str:
        acc = ZOHO_ACCOUNTS_URLS.get(self.dc, ZOHO_ACCOUNTS_URLS["us"])
        url = f"{acc}/oauth/v2/token"
        data = {
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(url, data=data, timeout=aiohttp.ClientTimeout(total=15)) as r:
                body = await r.json()
        if "access_token" not in body:
            raise RuntimeError(f"Zoho token refresh failed: {body}")
        self._token = body["access_token"]
        self._token_expiry = time.time() + body.get("expires_in", 3600)
        return self._token

    async def _access_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 120:
            return self._token
        return await self._refresh_access_token()

    # ── CRMAdapter ──

    async def health_check(self) -> bool:
        try:
            token = await self._access_token()
            api = ZOHO_API_URLS.get(self.dc, ZOHO_API_URLS["us"])
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"{api}/crm/v6/settings/modules/Contacts",
                    headers={"Authorization": f"Zoho-oauthtoken {token}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    return r.status < 400
        except Exception:
            return False

    async def write_lead(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Create Contact + Deal. Return unified result."""
        token = await self._access_token()
        api = ZOHO_API_URLS.get(self.dc, ZOHO_API_URLS["us"])
        hdrs = {"Authorization": f"Zoho-oauthtoken {token}", "Content-Type": "application/json"}

        # ── 1. Create Contact (mapped from lead fields) ──
        contact = self._build_contact(fields)
        contact_resp = await self._post(api, "/crm/v6/Contacts", hdrs, contact)
        contact_id = self._extract_id(contact_resp)

        # ── 2. Create Deal linked to Contact if deal_name present ──
        deal_id = None
        deal_resp = None
        if fields.get("deal_name"):
            deal_data = self._build_deal(fields, contact_id)
            deal_resp = await self._post(api, "/crm/v6/Deals", hdrs, deal_data)
            deal_id = self._extract_id(deal_resp)

        # ── 3. Build response ──
        base_url = "https://crm.zoho.com"
        if self.dc != "us":
            base_url = f"https://crm.zoho.{self.dc}"

        res = {
            "ok": True,
            "contact_id": contact_id,
            "deal_id": deal_id,
            "url": f"{base_url}/crm/{self.dc}/tab/Contacts/{contact_id}" if contact_id else None,
            "deal_url": f"{base_url}/crm/{self.dc}/tab/Deals/{deal_id}" if deal_id else None,
            "error": None,
            "raw_contact": contact_resp,
            "raw_deal": deal_resp,
        }

        # If Contact creation failed, report failure
        if not contact_id:
            err = contact_resp.get("data", [{}])[0].get("message", "Contact creation failed")
            res["ok"] = False
            res["error"] = err

        return res

    # ── Helpers ──

    def _build_contact(self, f: Dict[str, Any]) -> Dict[str, Any]:
        def s(k: str, vkey: Optional[str] = None):
            val = f.get(vkey or k)
            if val is not None and str(val).strip():
                # Special handling for Contact_Type picklist
                if k == "Contact_Type":
                    d[k] = _zoho_picklist(str(val), ["Decision Maker", "Technical", "Influencer", "Procurement", "Unknown"])
                else:
                    d[k] = str(val).strip()
        d: Dict[str, Any] = {}
        s("First_Name", "first_name")
        last = f.get("last_name", "Unknown")
        if not last:
            last = "Unknown"
        d["Last_Name"] = str(last).strip()
        s("Email", "email")
        s("Phone", "phone")
        s("Mobile", "mobile")
        s("Title", "title")
        s("Company", "company")
        s("Industry", "industry")
        s("Street", "address")
        s("City", "city")
        s("Country", "country")
        s("Description", "notes")
        s("Lead_Source", "source_channel")
        s("Lead_Source_Description", "campaign_source")
        s("Website", "company_website")
        s("LinkedIn", "linkedin")
        s("Contact_Type", "contact_type")
        # Custom size field mapped to Company context
        if f.get("company_size"):
            d.setdefault("No_of_Employees", str(f["company_size"]).strip())
        if f.get("fit_score") is not None:
            d.setdefault("Lead_Score", int(f["fit_score"]))
        if f.get("segment"):
            d.setdefault("Tag", str(f["segment"]))
        return d

    def _build_deal(self, f: Dict[str, Any], contact_id: Optional[str]) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        # Deal Name
        deal_name = f.get("deal_name")
        if not deal_name:
            # Auto-generate: "Company - Industry - Location"
            parts = []
            if f.get("company"):
                parts.append(str(f["company"]))
            if f.get("industry"):
                parts.append(str(f["industry"]))
            loc = f.get("city") or f.get("country")
            if loc:
                parts.append(str(loc))
            deal_name = " - ".join(parts) if parts else "New Lead"
        d["Deal_Name"] = deal_name

        # Stage picklist
        stage = f.get("deal_stage", "New Inquiry")
        d["Stage"] = _zoho_picklist(
            stage,
            ["New Inquiry", "Discovery", "Proposal", "Negotiation", "Closed Won", "Closed Lost"]
        )
        if f.get("closing_date"):
            d["Closing_Date"] = str(f["closing_date"])
        if f.get("expected_revenue"):
            # Strip currency symbols for numeric field
            rev = str(f["expected_revenue"])
            for ch in ", AED USD $":
                rev = rev.replace(ch, "")
            try:
                d["Expected_Revenue"] = float(rev.strip())
            except ValueError:
                d["Expected_Revenue"] = f["expected_revenue"]
        if f.get("campaign_source"):
            d["Campaign_Source"] = str(f["campaign_source"])
        if f.get("product_interest"):
            d["Product_Interest"] = str(f["product_interest"])
        if contact_id:
            d["Contact_Name"] = {"id": contact_id}
        return d

    async def _post(self, api_base: str, path: str, hdrs: Dict, data: Dict) -> Dict:
        url = f"{api_base}{path}"
        payload = {"data": [data], "trigger": ["approval", "workflow", "blueprint"]}
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=hdrs, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as r:
                body = await r.json()
        logger.info("Zoho POST %s -> status=%s", path, r.status)
        return body

    @staticmethod
    def _extract_id(response: Dict) -> Optional[str]:
        try:
            rec = response["data"][0]
            if rec.get("status") == "success":
                return rec.get("details", {}).get("id")
        except Exception:
            pass
        return None
