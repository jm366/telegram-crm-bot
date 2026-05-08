"""GTM-OS Adapter — writes leads into the local/remote SQLite gtm.db.

Environment:
  GTMO_DB_PATH  — absolute path to gtm.db
  GTMO_APP_URL  — base URL for lead deeplinks
"""

import os
import sqlite3
import logging
from typing import Dict, Any
from services.crm.base import CRMAdapter

logger = logging.getLogger(__name__)

class GtmosAdapter(CRMAdapter):
    def __init__(self, db_path: str = "", app_url: str = ""):
        self.db_path = db_path or os.getenv("GTMO_DB_PATH", "/root/projects/gtm-os/gtm.db")
        self.app_url = app_url or os.getenv("GTMO_APP_URL", "https://samwise.yourdomain.com")

    async def health_check(self) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leads'")
            ok = c.fetchone() is not None
            conn.close()
            return ok
        except Exception:
            return False

    async def write_lead(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Build INSERT columns
        cols = []
        vals = []
        for k, v in fields.items():
            if v is not None:
                cols.append(k)
                vals.append(v)

        # Auto-compute total_score
        if "fit_score" in fields and "intent_score" in fields:
            fs = fields.get("fit_score")
            is_ = fields.get("intent_score")
            if fs is not None and is_ is not None:
                cols.append("total_score")
                vals.append(fs + is_)

        # Ensure table exists (idempotent)
        cursor.execute("""
          CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            first_name TEXT NOT NULL,
            last_name TEXT,
            email TEXT UNIQUE,
            title TEXT,
            company TEXT,
            company_website TEXT,
            phone TEXT,
            mobile TEXT,
            address TEXT,
            country TEXT DEFAULT 'UAE',
            city TEXT,
            industry TEXT,
            role_type TEXT,
            source_channel TEXT,
            source_campaign TEXT,
            landing_page TEXT,
            segment TEXT DEFAULT 'new',
            funnel_stage TEXT DEFAULT 'lead',
            fit_score INTEGER DEFAULT 0,
            intent_score INTEGER DEFAULT 0,
            total_score INTEGER DEFAULT 0,
            status TEXT DEFAULT 'new',
            priority INTEGER DEFAULT 3,
            notes TEXT,
            next_step TEXT,
            last_contacted_at TEXT,
            tags TEXT,
            linkedin TEXT,
            job_flexibility INTEGER DEFAULT 0,
            budget_authority INTEGER DEFAULT 0,
            urgency INTEGER DEFAULT 0
          )
        """)

        placeholders = ",".join(["?"] * len(vals))
        col_list = ",".join(cols)

        cursor.execute(f"INSERT INTO leads ({col_list}) VALUES ({placeholders})", vals)
        lead_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return {
            "ok": True,
            "id": lead_id,
            "url": f"{self.app_url}/leads/{lead_id}",
            "error": None,
        }
