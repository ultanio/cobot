# Quick Start Guide

Get Cobot running in 5 minutes.

## Prerequisites

- Python 3.11 or higher
- An LLM API key (PPQ, OpenRouter, or local Ollama)
- A Telegram bot token (optional, from [@BotFather](https://t.me/BotFather))

## Step 1: Install

```bash
# Clone the repository
git clone https://github.com/ultanio/cobot
cd cobot

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install with Telegram support
pip install -e ".[telegram]"
```

## Step 2: Configure with Wizard

Run the setup wizard:

```bash
cobot wizard init
```

The wizard will guide you through configuration. Paste your secrets directly:

```
🤖 Identity

Agent name [Cobot]: MyBot

🔌 LLM Provider

Use PPQ (recommended)? [Y/n]: y
PPQ API key [${PPQ_API_KEY}]: sk-your-actual-api-key-here
Model [openai/gpt-4o]: 

🔧 Tool Execution

Enable shell command execution? [Y/n]: y

🔌 Plugins

Configure Telegram (Connect to Telegram for messaging)? [y/N]: y

Setting up Telegram for MyBot
Bot token (or env var) [${TELEGRAM_BOT_TOKEN}]: 123456789:ABCdefGHI-your-token
Long poll timeout (seconds) [30]: 
  ✓ Telegram configured

Configure User Authorization (Control who can interact with the bot)? [y/N]: y
Enable pairing? [Y/n]: y
Add Telegram owner ID? [Y/n]: y
Your Telegram user ID: 123456789
  ✓ User Authorization configured

✅ Configuration saved to cobot.yml
```

## Step 3: Run

Start cobot:

```bash
cobot run
```

You should see:

```
[Config] Provider: ppq
[telegram] Configured with 0 groups
[pairing] Ready (1 authorized, 0 pending)
Loaded 19 plugin(s)
Channels: telegram
```

Now message your bot on Telegram — it will respond!

For interactive terminal mode (no Telegram, just stdin/stdout):

```bash
cobot run --stdin
```

## Step 4: Manage Users

When someone new messages your bot, they get a pairing code:

```
Access not configured.
Your Telegram user id: 123456789
Pairing code: ABCD1234

Ask the bot owner to approve with:
  cobot pairing approve ABCD1234
```

Approve them (in another terminal):

```bash
cobot pairing approve ABCD1234
cobot pairing list              # See all users
cobot pairing revoke telegram 123456789  # Remove access
```

## Useful Commands

```bash
cobot status              # Check if running
cobot config show         # View config (secrets masked)
cobot config set key val  # Update config
cobot wizard plugins      # List available plugins
```

## Docker

Run Cobot in a container instead of installing Python locally.

**1. Set up your environment:**

```bash
cp .env.example .env
# Edit .env with your API key (e.g. OpenRouter, PPQ)
```

**2. Run the wizard (interactive setup):**

```bash
docker compose run cobot wizard init --home
```

The wizard writes config to `~/.cobot/cobot.yml` inside the container,
which maps to `./data/cobot.yml` on your host. Choose your LLM provider
(PPQ, OpenRouter, or Ollama) and the wizard handles the rest.

**3. Run:**

```bash
docker compose up -d                  # start in background
docker compose logs -f                # watch logs
docker compose run cobot run --stdin  # interactive terminal mode
```

## Next Steps

- [Architecture](architecture.md) — Understand how plugins work
- [Plugin Development](../CONTRIBUTING.md#plugin-development) — Create custom plugins
