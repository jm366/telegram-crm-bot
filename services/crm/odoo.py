"""Odoo CRM adapter via JSON-RPC (external API).

Uses Odoo's external API (xmlrpc/jsonrpc) to create CRM Leads (crm.lead).

Connection:
  - ODOO_URL          — e.g. https://mycompany.odoo.com
  - ODOO_DB           — database name
  - ODOO_USERNAME     — login (email)
  - ODOO_PASSWORD     — password or API key

Endpoints used:
  - /jsonrpc          — authenticate
  - /jsonrpc          — create crm.lead
  - /jsonrpc          — search/create res.partner (company)
"""

import os
import logging
import json
from typing import Dict, Any, Optional
import aiohttp
from services.crm.base import CRMAdapter

logger = logging.getLogger(__name__)

class OdooCrmAdapter(CRMAdapter):
    def __init__(
        self,
        url: Optional[str] = None,
        db: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.url = (url or os.getenv("ODOO_URL", "")).strip().rstrip("/")
        self.db = (db or os.getenv("ODOO_DB", "")).strip()
        self.username = (username or os.getenv("ODOO_USERNAME", "")).strip()
        self.password = (password or os.getenv("ODOO_PASSWORD", "")).strip()
        self._uid: Optional[int] = None

    async def _jsonrpc(self, endpoint: str, payload: Dict) -> Dict:
        url = f"{self.url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        data = {"jsonrpc": "2.0", "method": "call", "params": payload, "id": 1}
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                body = await resp.json()
        return body.get("result")

    async def _authenticate(self) -> int:
        if self._uid is not None:
            return self._uid
        result = await self._jsonrpc("/jsonrpc", {
            "service": "common",
            "method": "authenticate",
            "args": [self.db, self.username, self.password, {}],
        })
        if not result:
            raise RuntimeError("Odoo authentication failed")
        self._uid = result
        return self._uid

    async def health_check(self) -> bool:
        try:
            uid = await self._authenticate()
            return uid is not None and uid > 0
        except Exception:
            return False

    async def write_lead(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        uid = await self._authenticate()

        # 1. Find or create company (res.partner)
        partner_id = None
        company_name = fields.get("company")
        if company_name:
            search = await self._jsonrpc("/jsonrpc", {
                "service": "object",
                "method": "execute_kw",
                "args": [self.db, uid, self.password, "res.partner", "search", [[["is_company", "=", True], ["name", "ilike", company_name]]]],
            })
            if search:
                partner_id = search[0]
            else:
                create_partner = await self._jsonrpc("/jsonrpc", {
                    "service": "object",
                    "method": "execute_kw",
                    "args": [self.db, uid, self.password, "res.partner", "create", [{
                        "name": company_name,
                        "is_company": True,
                        "industry_id": False,
                    }]],
                })
                partner_id = create_partner

        # 2. Create CRM Lead (crm.lead)
        lead_data = {
            "name": f"{fields.get('first_name', '')} {fields.get('last_name', 'Unknown')}".strip(),
            "contact_name": f"{fields.get('first_name', '')} {fields.get('last_name', '')}".strip(),
            "email_from": fields.get("email", ""),
            "phone": fields.get("phone", ""),
            "mobile": fields.get("mobile", ""),
            "function": fields.get("title", ""),
            "street": fields.get("address", ""),
            "city": fields.get("city", ""),
            "country_id": False,
            "description": fields.get("notes", ""),
            "type": "lead",
        }
        if partner_id:
            lead_data["partner_id"] = partner_id

        # Optional: map our segment to Odoo priority
        segment = fields.get("segment")
        if segment == "hot":
            lead_data["priority"] = "3"
        elif segment == "warm":
            lead_data["priority"] = "2"
        else:
            lead_data["priority"] = "1"

        result = await self._jsonrpc("/jsonrpc", {
            "service": "object",
            "method": "execute_kw",
            "args": [self.db, uid, self.password, "crm.lead", "create", [lead_data]],
        })

        if isinstance(result, int):
            lead_id = result
            return {
                "ok": True,
                "id": lead_id,
                "url": f"{self.url}/web#id={lead_id}&model=crm.lead" if self.url else None,
                "error": None,
                "raw": {"lead_id": lead_id},
            }
        else:
            return {
                "ok": False,
                "id": None,
                "url": None,
                "error": str(result) if result else "Odoo create failed",
                "raw": result,
            }
