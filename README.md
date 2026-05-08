# Voice-to-CRM Telegram Bot (CRM-Agnostic)

A Telegram bot that accepts voice messages about people you meet, transcribes them with OpenAI Whisper, extracts structured lead data via LLM, asks follow-up questions for missing fields, and writes confirmed leads directly into your CRM.

**Inspired by Zoom API's structured data pattern**: voice goes in, structured JSON comes out, missing fields trigger smart follow-ups.

## Supported CRMs

| CRM | Provider Key | Auth |
|-----|-------------|------|
| ✅ **Zoho CRM** | `zoho` | OAuth2 (refresh token) |
| ✅ **HubSpot** | `hubspot` | Private App Access Token |
| ✅ **Pipedrive** | `pipedrive` | API Token |
| ✅ **Salesforce** | `salesforce` | OAuth2 (refresh token) |
| ✅ **Bitrix24** | `bitrix24` | Webhook URL or OAuth2 |
| ✅ **Odoo** | `odoo` | JSON-RPC (API key) |
| ✅ **GTM-OS** | `gtm-os` | Local SQLite (default) |

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
| `CRM_PROVIDER` | No | `zoho`, `hubspot`, `pipedrive`, `salesforce`, `bitrix24`, `odoo`, or `gtm-os` (default) |

### Zoho CRM

| Variable | How to get |
|----------|------------|
| `ZOHO_CLIENT_ID` | [console.zoho.com](https://console.zoho.com) → Self Client |
| `ZOHO_CLIENT_SECRET` | Same as above |
| `ZOHO_REFRESH_TOKEN` | Generate with scope `ZohoCRM.modules.ALL` |
| `ZOHO_DC` | Data center: `us`, `eu`, `in`, `cn`, `au`, `jp` |

### HubSpot

| Variable | How to get |
|----------|------------|
| `HUBSPOT_ACCESS_TOKEN` | Settings → Integrations → Private Apps → Create token |

### Pipedrive

| Variable | How to get |
|----------|------------|
| `PIPEDRIVE_API_TOKEN` | Settings → Personal Preferences → API |
| `PIPEDRIVE_DOMAIN` | Your company subdomain (e.g. `smartics` for smartics.pipedrive.com) |

### Salesforce

| Variable | How to get |
|----------|------------|
| `SFDC_CLIENT_ID` | Setup → App Manager → Connected App → Consumer Key |
| `SFDC_CLIENT_SECRET` | Consumer Secret from same page |
| `SFDC_REFRESH_TOKEN` | OAuth flow with scope `api refresh_token` |
| `SFDC_INSTANCE_URL` | e.g. `https://yourinstance.my.salesforce.com` |

### Bitrix24

**Webhook mode** (easiest for cloud):

| Variable | How to get |
|----------|------------|
| `BITRIX_WEBHOOK_URL` | Applications → Webhooks → Inbound webhook → copy full URL |

**OAuth mode** (on-premise):

| Variable | How to get |
|----------|------------|
| `BITRIX_CLIENT_ID` | Applications → OAuth → Client ID |
| `BITRIX_CLIENT_SECRET` | Applications → OAuth → Client Secret |
| `BITRIX_REFRESH_TOKEN` | OAuth flow |
| `BITRIX_DOMAIN` | Your portal URL |

### Odoo

| Variable | How to get |
|----------|------------|
| `ODOO_URL` | Your Odoo instance URL |
| `ODOO_DB` | Database name |
| `ODOO_USERNAME` | Login email |
| `ODOO_PASSWORD` | Settings → Users → API Keys (not your login password!) |

### GTM-OS (local SQLite)

| Variable | Description |
|----------|-------------|
| `GTMO_DB_PATH` | Absolute path to `gtm.db` |
| `GTMO_APP_URL` | Base URL for lead deeplinks |

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
┌──────▼───────┐
│ CRM Adapter  │──────┐
│ (pluggable)  │      ├─▶ Zoho CRM
└──────┬───────┘      ├─▶ HubSpot
       │               ├─▶ Pipedrive
┌──────▼───────┐      ├─▶ Salesforce
│ Telegram     │      ├─▶ Bitrix24
│ reply        │      ├─▶ Odoo
└──────────────┘      └─▶ GTM-OS
```

## Adding a New CRM Adapter

1. Create `services/crm/my_crm.py`
2. Implement `CRMAdapter`:

```python
from services.crm.base import CRMAdapter

class MyCrmAdapter(CRMAdapter):
    async def health_check(self) -> bool:
        return True  # ping your API

    async def write_lead(self, fields: dict) -> dict:
        # Create lead in your CRM
        return {"ok": True, "id": "123", "url": "https://...", "error": None}
```

3. Import + register in `services/crm/factory.py`

## Commands

| Command | What it does |
|---------|--------------|
| `/start` | Begin intake, shows connected CRM |
| `/cancel` | Cancel current intake |
| `/status` | What is the bot waiting for? |
| `/crm` | Check which CRM is active + connectivity |
| `/help` | List all commands |

## Production

```bash
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

## License

MIT
