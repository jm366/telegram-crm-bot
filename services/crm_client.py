import sqlite3
import os
from typing import Optional, Dict, Any

_DB_PATH = None

def get_db() -> sqlite3.Connection:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = os.getenv("GTMO_DB_PATH", "/root/projects/gtm-os/gtm.db")
    return sqlite3.connect(_DB_PATH)

def insert_lead(fields: Dict[str, any]) -> int:
    """Insert a lead into the gtm.db leads table. Returns the new lead_id."""
    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Build dynamic INSERT
    cols = []
    vals = []
    for k, v in fields.items():
        if v is not None:
            cols.append(k)
            vals.append(v)

    # Also compute total_score if fit_score + intent_score exist
    if "fit_score" in fields and "intent_score" in fields:
        if fields.get("fit_score") is not None and fields.get("intent_score") is not None:
            total = fields["fit_score"] + fields["intent_score"]
            fields["total_score"] = total
            if "total_score" not in cols:
                cols.append("total_score")
                vals.append(total)

    placeholders = ",".join(["?"] * len(vals))
    col_list = ",".join(cols)

    # Ensure the leads table exists
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

    cursor.execute(f"""
        INSERT INTO leads ({col_list})
        VALUES ({placeholders})
    """, vals)
    lead_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return lead_id
