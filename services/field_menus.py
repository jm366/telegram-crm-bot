"""Interactive picklist menus for Zoho CRM fields.

Each menu mirrors the picklist options from the Zoho CRM presentation.
Users can tap an option or type text as fallback.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List, Dict, Any, Optional

# ── Zoho CRM picklist definitions (from presentation) ──

FIELD_MENUS: Dict[str, Dict[str, Any]] = {
    "industry": {
        "label": "🛠 Industry",
        "type": "single",
        "options": [
            "Manufacturing",
            "Oil & Gas",
            "Energy & Utilities",
            "Real Estate & Construction",
            "Smart City / Infrastructure",
            "Food Processing",
            "Logistics & Supply Chain",
            "IT & Digital Solutions",
            "Marine & Offshore",
            "Facility Management",
            "Government",
            "Retail & Commerce",
            "Education & Training",
            "Healthcare & Lifesciences",
            "Automotive",
            "Aviation",
            "Mining & Steel",
            "Chemicals & Materials",
            "Water & Wastewater",
            "Security & Defence",
        ]
    },
    "contact_type": {
        "label": "🧑‍💼 Contact Type",
        "type": "single",
        "options": [
            "Decision Maker",
            "Technical",
            "Influencer",
            "Procurement",
            "Unknown",
        ]
    },
    "deal_stage": {
        "label": "📊 Deal Stage",
        "type": "single",
        "options": [
            "New Inquiry",
            "Discovery",
            "Proposal",
            "Negotiation",
            "Closed Won",
            "Closed Lost",
        ]
    },
    "segment": {
        "label": "🌡 Segment",
        "type": "single",
        "options": [
            "Hot",
            "Warm",
            "Partner",
            "Learn",
            "Low Priority",
        ]
    },
}


def build_inline_keyboard(field_name: str, current_value: Optional[str] = None) -> Optional[InlineKeyboardMarkup]:
    """Build 2-column Telegram inline keyboard for a given field."""
    config = FIELD_MENUS.get(field_name)
    if not config:
        return None
    
    keyboard: List[List[InlineKeyboardButton]] = []
    options = config["options"]
    
    # Show in groups of 2
    for i in range(0, len(options), 2):
        row = [
            InlineKeyboardButton(
                f"✓ {options[i]}" if current_value == options[i] else options[i],
                callback_data=f"fill:{field_name}:{options[i]}"
            )
        ]
        if i + 1 < len(options):
            row.append(
                InlineKeyboardButton(
                    f"✓ {options[i+1]}" if current_value == options[i+1] else options[i+1],
                    callback_data=f"fill:{field_name}:{options[i+1]}"
                )
            )
        keyboard.append(row)
    
    # Bottom row: skip / type custom / go back
    keyboard.append([
        InlineKeyboardButton("⏭ Skip", callback_data=f"fill:{field_name}:skip"),
        InlineKeyboardButton("⌨️ Type custom", callback_data=f"fill:{field_name}:type"),
    ])
    
    return InlineKeyboardMarkup(keyboard)


def get_menu_text(field_name: str, question_text: str) -> str:
    """Compose the prompt text for a menu-based field."""
    config = FIELD_MENUS.get(field_name)
    if not config:
        return question_text
    
    return (
        f"⏳ Need the *{config['label']}*\n\n"
        f"_{question_text}_\n\n"
        f"🔽 Tap an option, reply with text, or:")


def is_menu_field(field_name: str) -> bool:
    return field_name in FIELD_MENUS
