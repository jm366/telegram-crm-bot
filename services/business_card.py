import os
import base64
import json
from io import BytesIO
from typing import Dict, Tuple, Optional
from services.openai_transcribe import get_openai

VISION_SYSTEM_PROMPT = """You are a business card OCR + CRM data extraction assistant for smartics.io.

smartics.io is a UAE-based company selling SCADA, BMS, IoT, building energy management, and AI optimization solutions. They have case studies with Mitsubishi and Bahamas.

Your job: look at a business card photo and extract structured lead data.

RULES:
1. Extract ALL information visible on the card. Use null or "" for missing fields.
2. Be smart about inference — job titles may be abbreviated (e.g. "MD" = Managing Director).
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

EXTRACTION_SCHEMA_DESCRIPTION = """Extract structured lead data. Fields:
- first_name (string): person's first name
- last_name (string): surname
- title (string): job title (expand abbreviations)
- company (string): company name
- email (string): email address
- phone (string): phone number(s). Prefer mobile if multiple.
- industry (string): industry sector if inferable
- notes (string): extra context, verbatim text from card
- segment (string): one of "hot", "warm", "partner", "learn", "low_priority"
- fit_score (integer): 0-100
- intent_score (integer): 0-100
- next_step (string): recommended follow-up action
- confidence (number): 0.0-1.0
- tags (array of strings): relevant keywords like "cnc", "machining", "bms", "automation"
- linkedin (string): LinkedIn URL if present on card"""


def _image_to_base64(image_path: str) -> str:
    """Open any image and encode as base64 JPEG."""
    from PIL import Image
    img = Image.open(image_path)
    # Convert to RGB if needed
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")



async def extract_lead_from_photo(image_path: str) -> Tuple[Dict, str]:
    """
    Analyze a business card image and return (lead_dict, raw_content).
    """
    from models import ExtractionResult

    b64_image = _image_to_base64(image_path)
    mime_prefix = "data:image/jpeg;base64,"

    client = await get_openai()
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Analyze this business card and extract structured lead data.\n\n"
                            "Respond with ONLY valid JSON. No markdown, no explanations.\n\n"
                            f"Schema:\n{EXTRACTION_SCHEMA_DESCRIPTION}"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"{mime_prefix}{b64_image}",
                        },
                    },
                ]
            }
        ],
        tools=[{
            "type": "function",
            "function": {
                "name": "extract_lead",
                "description": "Extract structured lead data from business card",
                "parameters": ExtractionResult.model_json_schema(),
            }
        }],
        tool_choice={"type": "function", "function": {"name": "extract_lead"}},
    )

    tool_call = response.choices[0].message.tool_calls[0]
    data = json.loads(tool_call.function.arguments)
    result = ExtractionResult(**data)
    raw = result.lead.model_dump()
    return raw, response.choices[0].message.content or ""
