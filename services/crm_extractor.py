import os
import json
from typing import Dict, Optional, List, Tuple
from models import LeadExtraction, ExtractionResult
from services.openai_transcribe import get_openai

# Fields that MUST be collected before writing to CRM
REQUIRED_FIELDS = ["first_name", "company"]

# Fields that are desirable for a complete lead record
DESIRED_FIELDS = [
    "last_name", "email", "phone", "title", "industry",
    "notes", "segment", "fit_score", "intent_score", "next_step",
    "contact_type", "closing_date", "expected_revenue", "campaign_source", "company_size"
]

EXTRACTION_SYSTEM_PROMPT = """You are a CRM lead extraction assistant for smartics.io — a UAE-based company selling SCADA, BMS, IoT, building energy management, and AI optimization solutions. They have case studies with Mitsubishi and Bahamas.

Your job: parse unstructured voice transcripts and business card images and output structured JSON matching the Zoho CRM schema.

RULES:
1. Extract ALL information you can find. Use null or "" for missing fields.
2. Be smart about inference from context:
   - If someone says "I'm the technical director at GESATCO" infer title=technical director and company=GESATCO.
   - Infer Contact_Type from titles: "CEO/MD/Owner/VP" = Decision Maker, "Engineer/Manager (non-VP)" or "Technical" = Influencer, "Consultant/Procurement" = Procurement.
   - If revenue is mentioned ("80K project", "200K dirham budget"), record it in expected_revenue with currency (AED if UAE location). Convert shorthand: 80K = 80,000 AED.
   - If timing is mentioned ("start end of year", "closing Q1", "project in 2 months"), estimate closing_date as YYYY-MM-DD.
   - If source is mentioned ("we met at ADIPEC", "referral from Ahmad"), record in campaign_source.
   - Deal_name should be derived automatically if not stated: format as "Name - Industry - Location" (e.g. "Acme Corp - Oil & Gas - Dubai").
3. Assess segment automatically:
   - hot: direct fit for SCADA/BMS/IoT — decision maker at industrial/manufacturing/building company
   - warm: interest but not clearly active buyer
   - partner: reseller/integrator
   - learn: competitor / intel
   - low_priority: explicitly not interested or wrong fit
4. fit_score: rate 0-100 based on smartics product fit
5. intent_score: rate 0-100 based on urgency / buying signals
6. next_step: recommend one concrete follow-up action
7. Return strictly valid JSON matching the schema. Do not add fields."""

FOLLOWUP_SYSTEM_PROMPT = """You are a friendly Telegram CRM assistant helping John Mark (smartics.io MD). You just extracted partial lead data from a voice memo or business card photo.

Your job: ask ONE concise follow-up question to get a specific missing field. Keep it friendly and professional.

GUIDELINES:
- Ask only for the single most important missing field.
- If the person's name is missing, ask "What's this person's first name?"
- If company is missing, ask "Which company do they work for?"
- If email is missing, ask "Do you have their email?"
- If phone is missing, ask "Their phone or WhatsApp number?"
- If industry is missing, ask "What industry are they in — manufacturing, oil & gas, etc.?"
- If contact_type is missing, ask "What's their role — Decision Maker, Technical, Procurement, Influencer?"
- If closing_date is missing, ask "When does this project need to close by? (or rough timeline)"
- If expected_revenue is missing, ask "What's the approximate project budget or value?"
- If campaign_source is missing, ask "Where did you meet this lead? (e.g., ADIPEC, LinkedIn, referral)"
- Reference what you already know so the user knows you're building context.
- If nothing is missing, say "Looking good — I think I have all I need! ✅"

Respond in a single short sentence."""

async def extract_lead_from_text(text: str) -> Tuple[ExtractionResult, Dict[str, str]]:
    """Run LLM extraction. Returns (result, raw_fields_dict)."""
    client = await get_openai()
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract lead from this transcript:\n\n{text}"},
        ],
        tools=[{
            "type": "function",
            "function": {
                "name": "extract_lead",
                "description": "Extract structured lead data",
                "parameters": ExtractionResult.model_json_schema(),
            }
        }],
        tool_choice={"type": "function", "function": {"name": "extract_lead"}},
    )

    tool_call = response.choices[0].message.tool_calls[0]
    data = json.loads(tool_call.function.arguments)
    result = ExtractionResult(**data)

    # Flatten for easy field checking
    raw = result.lead.model_dump()
    return result, raw


def get_missing_fields(fields: Dict[str, any]) -> List[str]:
    """Return list of field names that are empty/null."""
    missing = []
    for k in REQUIRED_FIELDS:
        if not fields.get(k):
            missing.append(k)
    for k in DESIRED_FIELDS:
        if not fields.get(k):
            missing.append(k)
    # dedup preserving order
    seen = set()
    unique = []
    for k in missing:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


async def generate_followup_question(known_fields: Dict[str, any], missing_field: str, transcript: str) -> str:
    """Ask a follow-up question for a specific missing field."""
    client = await get_openai()
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    # Build context of what we already know
    known_summary = ", ".join([f"{k}={v}" for k, v in known_fields.items() if v])

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": FOLLOWUP_SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript: {transcript}\n\nKnown fields: {known_summary}\n\nMissing field to ask about: {missing_field}"},
        ],
        max_tokens=120,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


async def summarize_draft(fields: Dict[str, any]) -> str:
    """Generate a draft summary for user confirmation."""
    lines = []
    # Contact info
    contact_keys = ["first_name", "last_name", "title", "company", "email", "phone", "industry", "address", "country", "city", "contact_type"]
    for k in contact_keys:
        v = fields.get(k)
        if v:
            label = k.replace("_", " ").title()
            lines.append(f"• {label}: {v}")
    # Deal info
    deal_keys = ["deal_name", "deal_stage", "closing_date", "expected_revenue", "campaign_source", "project_start_date"]
    for k in deal_keys:
        v = fields.get(k)
        if v:
            label = k.replace("_", " ").title()
            lines.append(f"• {label}: {v}")
    # Scoring
    if "fit_score" in fields:
        lines.append(f"• Fit Score: {fields['fit_score']} / 100")
    if "intent_score" in fields:
        lines.append(f"• Intent Score: {fields['intent_score']} / 100")
    # Notes and next step
    for k in ["notes", "next_step"]:
        v = fields.get(k)
        if v:
            label = k.replace("_", " ").title()
            lines.append(f"• {label}: {v}")
    return "\n".join(lines)
