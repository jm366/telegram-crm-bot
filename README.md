# Telegram CRM Voice Bot

## What It Does

You record a voice memo in Telegram about someone you met. The bot:
1. Transcribes it (OpenAI Whisper)
2. Extracts structured lead data via LLM
3. Points out what it already captured
4. Asks one question at a time for anything missing
5. Once complete, sends you a confirmation draft
6. On your **confirm**, it writes straight into the GTM-OS SQLite CRM
7. Replies with a link to the new lead in the web dashboard

## Install

```bash
git clone https://github.com/jm366/telegram-crm-bot.git
cd telegram-crm-bot
cp .env.example .env
# Edit .env with your tokens
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `OPENAI_API_KEY` | From OpenAI dashboard |
| `GTMO_DB_PATH` | Absolute path to `gtm.db` |
| `GTMO_APP_URL` | Base URL like `https://samwise.yourdomain.com` |
| `OPENAI_MODEL` | Optional, default `gpt-4o` |

## Run

```bash
source venv/bin/activate
python bot.py
```

Or with PM2 (production):

```bash
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

## How to Use

1. In Telegram, send a voice memo describing who you just met:
   > "Ajay Laul from Yokogawa — he's the technical director. He was very interested in our SCADA solution, especially the Mitsubishi case study."
2. Bot transcribes and extracts:
   - Name: Ajay Laul
   - Title: Technical Director
   - Company: Yokogawa
   - Segment: warm
3. Bot tells you what it got and asks for missing field:
   > "Got it — name, company, interest noted. **What's his email?**"
4. You reply with text (or another voice memo)
5. Bot fills the field, asks next one
6. When nothing missing, it shows a **draft**
7. You tap **Confirm** → saved to CRM → you get a link

## Commands

- `/start` — Start over
- `/cancel` — Cancel current intake
- `/status` — What is the bot waiting for?

