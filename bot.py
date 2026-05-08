import os
import logging
import tempfile
import asyncio
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    Application,
)

from services.openai_transcribe import transcribe_audio
from services.crm_extractor import (
    extract_lead_from_text,
    get_missing_fields,
    generate_followup_question,
    summarize_draft,
)
from services.crm.factory import get_adapter, adapter_info, get_provider_name
from services.business_card import extract_lead_from_photo
from services.field_menus import (
    build_inline_keyboard,
    get_menu_text,
    is_menu_field,
)

load_dotenv()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Conversation States ───
STATE_IDLE = 0
STATE_COLLECTING = 1
STATE_CONFIRM = 2

class ConversationStore:
    """In-memory conversation state (per chat_id)."""
    def __init__(self):
        self._data: Dict[int, Dict[str, Any]] = {}
    def get(self, chat_id: int) -> Dict[str, Any]:
        return self._data.setdefault(chat_id, {"state": STATE_IDLE, "lead": {}, "missing": [], "transcript": ""})
    def reset(self, chat_id: int):
        self._data[chat_id] = {"state": STATE_IDLE, "lead": {}, "missing": [], "transcript": ""}
    def set_state(self, chat_id: int, state: int):
        self.get(chat_id)["state"] = state
    def set_lead(self, chat_id: int, lead_data: Dict):
        self.get(chat_id)["lead"] = lead_data
    def set_missing(self, chat_id: int, missing: list):
        self.get(chat_id)["missing"] = missing
    def set_transcript(self, chat_id: int, transcript: str):
        self.get(chat_id)["transcript"] = transcript
    def pop_missing(self, chat_id: int) -> str:
        missing = self.get(chat_id)["missing"]
        if missing:
            return missing.pop(0)
        return ""
    def append_missing(self, chat_id: int, field: str):
        self.get(chat_id)["missing"].append(field)

store = ConversationStore()

# ─── Constants ───
BASE_URL = os.getenv("GTMO_APP_URL", "https://samwise.yourdomain.com").rstrip("/")

# ─── Handlers ───

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    store.reset(chat_id)
    provider = get_provider_name()
    display_names = {
        "zoho": "Zoho CRM",
        "hubspot": "HubSpot CRM",
        "pipedrive": "Pipedrive CRM",
        "salesforce": "Salesforce",
        "bitrix24": "Bitrix24",
        "bitrix": "Bitrix24",
        "odoo": "Odoo CRM",
        "gtm-os": "GTM-OS",
    }
    crm_name = display_names.get(provider, provider)
    await update.message.reply_text(
        f"👋 Hi! I'm your voice-to-CRM intake bot.\n\n"
        f"Connected to: *{crm_name}*\n\n"
        "Send me a voice memo or a photo of a business card, and I'll:\n"
        "1. 🎙 Transcribe it / 📷 Read the card\n"
        "2. � Extract lead info\n"
        "3. ❓ Ask for missing details\n"
        "4. 📝 Create a confirmed lead in your CRM\n\n"
        "Try it now — record a voice message or snap a business card!\n\n"
        "Commands: /help /status /crm"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Commands:\n"
        "/start — Start over\n"
        "/cancel — Cancel current intake\n"
        "/status — What am I waiting for?\n"
        "/crm — Check CRM connection\n\n"
        "Send a voice memo 📷 or a business card photo anytime!"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    store.reset(chat_id)
    await update.message.reply_text("❌ Cancelled. Ready when you are — send a voice memo anytime!")
    return ConversationHandler.END


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = store.get(chat_id)
    state = data["state"]
    if state == STATE_IDLE:
        await update.message.reply_text("I'm idle — send a voice memo to start!")
    elif state == STATE_COLLECTING:
        missing = data["missing"]
        lead = data["lead"]
        fields = ", ".join([k for k, v in lead.items() if v])
        await update.message.reply_text(f"Currently collecting. Got: {fields or 'nothing yet'}.\nStill need: {', '.join(missing) or 'nothing'}. Tell me more!")
    elif state == STATE_CONFIRM:
        await update.message.reply_text("I'm waiting for your confirmation — check the draft above and tap Confirm or Edit.")
    return


async def crm_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check which CRM is active and whether it's reachable."""
    try:
        info = await adapter_info()
        await update.message.reply_text(f"🔗 {info}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ CRM check failed: {e}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main entry point: user sends voice / audio."""
    chat_id = update.effective_chat.id
    voice = update.message.voice or update.message.audio

    if not voice:
        await update.message.reply_text("I only understand voice messages for now — send me a voice memo!")
        return STATE_IDLE

    # Progress update
    progress = await update.message.reply_text("🎙 Downloading voice...")

    # Download to temp file
    file = await context.bot.get_file(voice.file_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
        await file.download_to_drive(tmp.name)
        ogg_path = tmp.name

    await progress.edit_text("🧠 Transcribing with Whisper...")
    try:
        transcript = await transcribe_audio(ogg_path)
    except Exception as e:
        logger.error("Transcription failed: %s", e)
        await progress.edit_text("❌ Sorry, transcription failed. Try again?")
        return STATE_IDLE
    finally:
        try:
            os.unlink(ogg_path)
        except Exception:
            pass

    if not transcript.strip():
        await progress.edit_text("⚠️ I couldn't understand the audio. Try speaking louder or closer to the mic.")
        return STATE_IDLE

    await progress.edit_text(f"✅ Transcribed!\n\n\"{transcript[:400]}{'…' if len(transcript)>400 else ''}\"\n\n🔍 Extracting lead data...")

    # Extract via LLM
    try:
        result, raw = await extract_lead_from_text(transcript)
    except Exception as e:
        logger.error("Extraction failed: %s", e)
        await progress.edit_text("❌ Couldn't extract lead info. Try sending a clearer memo with name and company.")
        return STATE_IDLE

    lead_data = raw
    missing = get_missing_fields(raw)

    logger.info("Extracted lead for chat %s: %s | missing: %s", chat_id, raw, missing)

    # Save state
    store.set_transcript(chat_id, transcript)
    store.set_lead(chat_id, lead_data)
    store.set_missing(chat_id, missing)

    if not missing:
        # Go straight to confirm
        return await _send_confirm(update, context, chat_id)

    # Need more info — ask first missing question
    store.set_state(chat_id, STATE_COLLECTING)
    field = missing[0]
    question = await generate_followup_question(lead_data, field, transcript)

    summary = await summarize_draft(lead_data)
    
    # Check if this field has a picklist menu
    if is_menu_field(field):
        menu_text = get_menu_text(field, question)
        markup = build_inline_keyboard(field, lead_data.get(field))
        await progress.edit_text(menu_text, reply_markup=markup, parse_mode="Markdown")
    else:
        text = (
            f"I found this so far:\n\n{summary}\n\n"
            f"⏳ I still need a few more details. {question}\n\n"
            "(You can reply with text or send another voice memo.)"
        )
        await progress.edit_text(text)
    return STATE_COLLECTING


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User sends a photo of a business card."""
    chat_id = update.effective_chat.id
    photo = update.message.photo

    if not photo:
        await update.message.reply_text("📷 I need a photo to read a business card. Please upload one!")
        return STATE_IDLE

    # Get the largest version
    file = await context.bot.get_file(photo[-1].file_id)
    tmp_path = os.path.join(tempfile.gettempdir(), f"card_{chat_id}_{photo[-1].file_id}.jpg")
    await file.download_to_drive(tmp_path)

    progress = await update.message.reply_text("📷 Analysing business card...")

    try:
        lead_data, raw = await extract_lead_from_photo(tmp_path)
    except Exception as e:
        logger.error("Photo extraction failed: %s", e)
        await progress.edit_text("❌ Couldn't read that business card. Try a clearer photo or send a voice memo instead.")
        return STATE_IDLE
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    await progress.edit_text("🔍 Extracted data from card! Drafting...")

    missing = get_missing_fields(lead_data)
    store.set_transcript(chat_id, "(Photo of business card)")
    store.set_lead(chat_id, lead_data)
    store.set_missing(chat_id, missing)

    logger.info("Extracted card lead for chat %s: %s | missing: %s", chat_id, lead_data, missing)

    if not missing:
        return await _send_confirm(update, context, chat_id)

    store.set_state(chat_id, STATE_COLLECTING)
    field = missing[0]
    # Reuse the transcript-aware follow-up generator, but with the card context instead
    question = await generate_followup_question(lead_data, field, "Business card photo")

    summary = await summarize_draft(lead_data)
    
    # Check if this field has a picklist menu
    if is_menu_field(field):
        menu_text = get_menu_text(field, question)
        markup = build_inline_keyboard(field, lead_data.get(field))
        await progress.edit_text(menu_text, reply_markup=markup, parse_mode="Markdown")
    else:
        text = (
            f"I read the card and found this:\n\n{summary}\n\n"
            f"⏳ I still need a few more details. {question}\n\n"
            "(Just reply with text.)"
        )
        await progress.edit_text(text)
    return STATE_COLLECTING


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Text replies during collection phase."""
    chat_id = update.effective_chat.id
    data = store.get(chat_id)
    state = data["state"]
    text = update.message.text.strip()

    if state == STATE_IDLE:
        await update.message.reply_text("Send me a voice memo or a photo of a business card to start lead intake, or use /start")
        return STATE_IDLE

    if state == STATE_COLLECTING:
        # Try to fill the most recent missing field from the user's text
        lead = data["lead"]
        missing = data["missing"]

        # Simple heuristic: we know what field we asked for last — update it
        # We'll also let the LLM re-extract the text in context
        if missing:
            current_field = missing[0]
        else:
            current_field = None

        # Simple direct assignment for common short answers
        # But also try LLM re-extraction with context
        updated = await _attempt_contextual_fill(lead, text, current_field, data["transcript"])

        # Merge updated fields
        for k, v in updated.items():
            if v is not None and (k in REQUIRED_FIELDS or k in DESIRED_FIELDS):
                lead[k] = v

        store.set_lead(chat_id, lead)
        store.set_missing(chat_id, get_missing_fields(lead))
        missing = store.get(chat_id)["missing"]

        if not missing:
            return await _send_confirm(update, context, chat_id)

        # Ask next missing question — with menu if applicable
        next_field = missing[0]
        question = await generate_followup_question(lead, next_field, data["transcript"])
        summary = await summarize_draft(lead)
        
        if is_menu_field(next_field):
            menu_text = get_menu_text(next_field, question)
            markup = build_inline_keyboard(next_field, lead.get(next_field))
            await update.message.reply_text(menu_text, reply_markup=markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"👍\n\n{summary}\n\n❓ {question}"
            )
        return STATE_COLLECTING

    if state == STATE_CONFIRM:
        # If they typed something while waiting for confirm, just nudge them
        await update.message.reply_text("I'm waiting for you to confirm or edit the draft — tap a button above!")
        return STATE_CONFIRM

    return state


async def _attempt_contextual_fill(lead: Dict, text: str, field_hint: Optional[str], transcript: str) -> Dict:
    """Use LLM to parse a short text reply and fill the right field."""
    from services.crm_extractor import get_openai
    client = await get_openai()
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    prompt = f"""
The user is in a CRM intake conversation. We previously asked about field: '{field_hint or "unknown"}'.
Original transcript: {transcript}
User's reply: "{text}"
Current lead data: {lead}

Return strict JSON with ONLY the fields that should be updated. Unknown=omit. Match these keys exactly:
first_name, last_name, email, phone, title, company, industry, address, city, country, notes, segment, fit_score, intent_score, priority, tags, linkedin, next_step.
"""
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": "You are a CRM field parser. Be precise. Output only JSON with field updates."},
                       {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=300,
        )
        content = response.choices[0].message.content
        import json
        updates = json.loads(content) if content else {}
        # Filter to expected keys
        valid = {k: v for k, v in updates.items() if v is not None and v != ""}
        return valid
    except Exception as e:
        logger.warning("Contextual fill LLM failed: %s", e)
        # Fallback — if field_hint looks like a simple text answer, stuff it in
        fallback = {}
        if field_hint and text and not any(c in text for c in ["{", "}", "question", "don't know"]):
            fallback[field_hint] = text
        return fallback


async def _send_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Send confirmation draft with buttons."""
    store.set_state(chat_id, STATE_CONFIRM)
    lead = store.get(chat_id)["lead"]
    summary = await summarize_draft(lead)

    keyboard = [
        [InlineKeyboardButton("✅ Confirm — Save to CRM", callback_data="action:confirm")],
        [InlineKeyboardButton("✏️ Edit — Add details", callback_data="action:edit")],
        [InlineKeyboardButton("❌ Discard", callback_data="action:discard")],
    ]
    markup = InlineKeyboardMarkup(keyboard)

    text = (
        "📝 Draft Lead Summary:\n"
        "─────────────────────\n"
        f"{summary}\n"
        "─────────────────────\n\n"
        "Does this look right?"
    )
    await update.message.reply_text(text, reply_markup=markup)
    return STATE_CONFIRM


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    data = query.data

    # ── Handle field fill callbacks ──
    if data.startswith("fill:"):
        parts = data.split(":")
        if len(parts) >= 3:
            field_name = parts[1]
            value = ":".join(parts[2:])  # handle values with colons
            
            lead = store.get(chat_id)["lead"]
            
            if value == "skip":
                # Remove this field from missing list
                missing = store.get(chat_id)["missing"]
                if field_name in missing:
                    missing.remove(field_name)
                store.set_missing(chat_id, missing)
                
                # Ask next question
                missing = store.get(chat_id)["missing"]
                if not missing:
                    return await _send_confirm(update, context, chat_id)
                
                next_field = missing[0]
                question = await generate_followup_question(lead, next_field, store.get(chat_id)["transcript"])
                summary = await summarize_draft(lead)
                
                if is_menu_field(next_field):
                    menu_text = get_menu_text(next_field, question)
                    markup = build_inline_keyboard(next_field, lead.get(next_field))
                    await query.edit_message_text(menu_text, reply_markup=markup, parse_mode="Markdown")
                else:
                    await query.edit_message_text(
                        f"👍\n\n{summary}\n\n❓ {question}",
                        parse_mode="Markdown"
                    )
                return STATE_COLLECTING
            
            elif value == "type":
                # User wants to type custom value — show summary and prompt for text
                summary = await summarize_draft(lead)
                prompt = (
                    f"{summary}\n\n"
                    f"✍️ Please type the {field_name.replace('_', ' ').title()}:\n"
                    "(Send your reply as a text message)"
                )
                await query.edit_message_text(prompt, parse_mode="Markdown")
                return STATE_COLLECTING
            
            else:
                # User selected a picklist option
                lead[field_name] = value
                store.set_lead(chat_id, lead)
                
                # Ask next missing question
                missing = get_missing_fields(lead)
                store.set_missing(chat_id, missing)
                
                if not missing:
                    summary = await summarize_draft(lead)
                    await query.edit_message_text(
                        f"✓ {field_name.replace('_', ' ').title()} set to *{value}*\n\n{summary}",
                        parse_mode="Markdown"
                    )
                    return await _send_confirm(update, context, chat_id)
                
                next_field = missing[0]
                question = await generate_followup_question(lead, next_field, store.get(chat_id)["transcript"])
                summary = await summarize_draft(lead)
                
                if is_menu_field(next_field):
                    menu_text = get_menu_text(next_field, question)
                    markup = build_inline_keyboard(next_field, lead.get(next_field))
                    await query.edit_message_text(menu_text, reply_markup=markup, parse_mode="Markdown")
                else:
                    await query.edit_message_text(
                        f"✓ {field_name.replace('_', ' ').title()} set to *{value}*\n\n"
                        f"{summary}\n\n❓ {question}",
                        parse_mode="Markdown"
                    )
                return STATE_COLLECTING

    if data == "action:confirm":
        await query.edit_message_text("💾 Saving to CRM...")
        lead = store.get(chat_id)["lead"]
        try:
            adapter = await get_adapter()
            result = await adapter.write_lead(lead)
            if result["ok"]:
                crm_url = result.get("url")
                crm_id = result.get("id")
                msg = (
                    f"✅ Lead saved!\n\n"
                    f"CRM ID: `{crm_id}`\n"
                )
                if crm_url:
                    msg += f"🔗 [Open in CRM]({crm_url})\n\n"
                msg += "Send another voice memo anytime!"
                await query.edit_message_text(msg, parse_mode="Markdown")
                # Also add a keyboard to let them add another easily
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Add Another Lead", callback_data="action:new")]
                ])
                await context.bot.send_message(chat_id, "Ready for next intake — record a new voice memo!", reply_markup=reply_markup)
            else:
                await query.edit_message_text(
                    f"❌ CRM returned an error:\n_{result.get('error', 'Unknown error')}_\n\n"
                    "You can try again or /cancel.",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error("Insert failed: %s", e)
            await query.edit_message_text(f"❌ Failed to save: {e}\nTry /cancel and start again.")
        store.reset(chat_id)

    elif data == "action:edit":
        store.set_state(chat_id, STATE_COLLECTING)
        store.get(chat_id)["missing"].append("notes")
        await query.edit_message_text("Got it — what would you like to add or change? (Just reply text)")

    elif data == "action:discard":
        store.reset(chat_id)
        await query.edit_message_text("❌ Discarded. Ready for next — send a voice memo anytime!")

    elif data == "action:new":
        store.reset(chat_id)
        await query.edit_message_text("🎙 Send a new voice memo!")


# ─── Main ───

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

    app: Application = ApplicationBuilder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.VOICE | filters.AUDIO, handle_voice),
            MessageHandler(filters.PHOTO, handle_photo),
        ],
        states={
            STATE_IDLE: [
                MessageHandler(filters.VOICE | filters.AUDIO, handle_voice),
                MessageHandler(filters.PHOTO, handle_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
            ],
            STATE_COLLECTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                MessageHandler(filters.VOICE | filters.AUDIO, handle_voice),
                MessageHandler(filters.PHOTO, handle_photo),
            ],
            STATE_CONFIRM: [
                CallbackQueryHandler(callback_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("help", help_command),
            CommandHandler("status", status),
        ],
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("crm", crm_status))

    logger.info("🚀 Telegram CRM Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
