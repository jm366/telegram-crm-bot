# Voice-to-CRM Telegram Bot (CRM-Agnostic)

A Telegram bot that accepts voice messages about people you meet, transcribes them with OpenAI Whisper, extracts structured lead data via LLM, asks follow-up questions for missing fields, and writes confirmed leads directly into your CRM.

**Inspired by Zoom API's structured data pattern**: voice goes in, structured JSON comes out, missing fields trigger smart follow-ups.

## Supported CRMs

- ✅ **Zoho CRM** (v6 REST API via OAuth2)
- ✅ **GTM-OS** (local SQLite)
- 🧩 **Easy to add**: HubSpot, Pipedrive, Salesforce, etc. — just implement `services/crm/base.py`

## How It Works

| Step | What happens |
|------|--------------|
| 1. 🎙 | You record a voice memo about Ajay Laul from Yokogawa |
| 2. 🧠 | Bot transcribes → LLM extracts name, company, title, segment, fit score |
| 3. ❓ | Bot says "Got name & company. **What's his email?**" |
| 4. ✅ | You reply → bot fills field → asks next missing one |
| 5. 📝 | Bot shows draft with Confirm / Edit / Discard buttons |
| 6. 🚀 | On Confirm → writes to **your** CRM → replies with CRM link + ID |

## Quick Start

```bash
git clone https://github.com/jm366/telegram-crm-bot.git
cd telegram-crm-bot
cp .env.example .env
# Edit .env with your tokens
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | From @BotFather |
| `OPENAI_API_KEY` | Yes | From OpenAI dashboard |
| `CRM_PROVIDER` | No | `zoho` or `gtm-os` (default: `gtm-os`) |

### Zoho CRM-specific

| Variable | For | How to get |
|----------|-----|------------|
| `ZOHO_CLIENT_ID` | OAuth app ID | [console.zoho.com](https://console.zoho.com) → Client for Server-based Applications |
| `ZOHO_CLIENT_SECRET` | OAuth app secret | Same as above |
| `ZOHO_REFRESH_TOKEN` | Long-lived token | Generate via [Self Client](https://www.zoho.com/accounts/protocol/oauth/self-client.html) with scope `ZohoCRM.modules.ALL` |
| `ZOHO_DC` | No | Data center: `us` (default), `eu`, `in`, `cn`, `au`, `jp` |

### GTM-OS-specific

| Variable | Required | Description |
|----------|----------|-------------|
| `GTMO_DB_PATH` | No | Absolute path to `gtm.db` |
| `GTMO_APP_URL` | No | Base URL for lead deeplinks |

## Architecture

```
┌──────────────┐
│ Telegram bot │
└──────┬───────┘
       │ voice memo
┌──────▼───────┐     ┌──────────────┐
│ OpenAI       │──▶│ Whisper        │
│              │     │ transcription  │
└──────┬───────┘     └──────────────┘
       │ text
┌──────▼───────┐     ┌──────────────┐
│ LLM          │──▶│ structured JSON│
│ extraction   │     │ (LeadExtraction│
│              │     │  Pydantic model)│
└──────┬───────┘     └──────────────┘
       │ missing fields?
┌──────▼───────┐
│ Follow-up Q  │
│ generator    │
└──────┬───────┘
       │ user confirms
┌──────▼───────┐     ┌──────────────┐
│ CRM Adapter  │──▶│ Zoho / GTM-OS│
│ (pluggable)  │     │ write lead   │
└──────┬───────┘     └──────────────┘
       │ CRM URL + ID
┌──────▼───────┐
│ Telegram     │
│ reply        │
└──────────────┘
```

## Adding a New CRM Adapter

Create a file in `services/crm/` that implements `CRMAdapter`:

```python
from services.crm.base import CRMAdapter

class MyCrmAdapter(CRMAdapter):
    async def health_check(self) -> bool:
        # Ping API, return True if reachable
        return True

    async def write_lead(self, fields: dict) -> dict:
        # Create lead in your CRM
        # Return {"ok": True, "id": "123", "url": "https://...", "error": None}
        return {"ok": True, "id": "123", "url": None, "error": None}
```

Then register it in `services/crm/factory.py`:

```python
if name == "my-crm":
    return MyCrmAdapter()
```

## Commands

| Command | What it does |
|---------|--------------|
| `/start` | Begin intake, shows connected CRM |
| `/cancel` | Cancel current intake |
| `/status` | What is the bot waiting for? |
| `/crm` | Check which CRM is active + connectivity |
| `/help` | List all commands |

## Run with PM2 (Production)

```bash
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

## License

MIT
