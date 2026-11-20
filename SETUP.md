# Telegram AltStore Source — Setup & Usage Guide

## Prerequisites

1. **GitHub account** with a public repo
2. **Telegram API credentials** (free, takes 2 min)
3. **Python 3.10+** installed

---

## Step 1: Get Telegram API Credentials

1. Go to https://my.telegram.org/apps
2. Log in with your Telegram account
3. Click "Create application"
4. Fill in:
   - App title: `telegram-altstore` (or any name)
   - Short name: `telegram-altstore`
   - URL: `https://github.com/yourusername`
   - Platform: `Other`
5. Copy the **api_id** (numeric) and **api_hash** (alphanumeric string)

---

## Step 2: Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `telegram-ipa-source` (or any name)
3. **Must be public** (AltStore sources require public repos)
4. Add a `README.md` (required for repo creation)
5. Generate a token:
   - Go to https://github.com/settings/tokens/new
   - Scopes: `repo` (full control)
   - Copy the token (shown once)

---

## Step 3: Fill In `.env`

```bash
TELEGRAM_API_ID=12345678      # your numeric api_id
TELEGRAM_API_HASH=abc123...   # your api_hash string
GITHUB_TOKEN=ghp_xxx...       # your GitHub token
```

---

## Step 4: Fill In `config.toml`

```toml
[github]
owner = "your-github-username"      # NOT the full repo URL
repo = "telegram-ipa-source"        # your repo name
```

```toml
[telegram]
channels = ["@channel_handle_1", "@channel_handle_2"]
```

**Find channel handles:**
- Open the channel in Telegram
- Look at the link: `t.me/CHANNEL_HANDLE`
- Add the `@` prefix: `@CHANNEL_handle`

---

## Step 5: Install & Run

```bash
# Install
pip install telegram-altstore

# Authenticate (saves session to ~/.local/share/telegram-altstore/)
telegram-altstore auth

# Test it works
telegram-altstore list
```

---

## Step 6: Run the Sync (First Time)

```bash
# Full sync: reads all channel messages, uploads IPAs to GitHub
telegram-altstore sync
```

This will:
1. Connect to your Telegram channels
2. Find IPA files in the last ~1000 messages
3. Upload each IPA to GitHub as a release
4. Generate `source.json` for AltStore

---

## Step 7: Add Source to AltStore

After first sync, your source URL is:
```
https://raw.githubusercontent.com/OWNER/REPO/main/source.json
```

1. Open AltStore on your iPhone
2. Tap the **+** button
3. Paste the URL above
4. The app should appear

---

## Usage

```bash
# Quick sync (last 100 messages only)
telegram-altstore sync --quick

# Check for new IPAs without uploading
telegram-altstore list --new

# Run as daemon (auto-sync every hour)
telegram-altstore daemon --interval 60
```

---

## Troubleshooting

**"Channel not found"**
- Make sure the bot/user is a member of the channel
- Check the handle is correct (case-sensitive)

**GitHub upload fails**
- Verify your token has `repo` scope
- Make sure the repo is public

**AltStore says "Invalid source"**
- Double-check the source.json URL is correct
- Ensure the repo has at least one release (IPA file)