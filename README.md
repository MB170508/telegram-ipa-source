# Telegram-to-AltStore Automated Repository

A Python application that automatically imports IPA files from Telegram channels and publishes them as a functional AltStore source, using GitHub Releases for permanent distribution.

## Quick Start

```bash
# Clone and set up
git clone https://github.com/your-username/telegram-ipa-source.git
cd telegram-ipa-source
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp config.example.toml config.toml
# Edit config.toml with your settings
# Add secrets to .env (see below)

# Run
python -m telegram_altstore.cli import-history --channel @some_channel
python -m telegram_altstore.cli generate-source
python -m telegram_altstore.cli monitor  # continuous
```

## How It Works

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Telegram       │───▶│  telegram-altstore│───▶│  GitHub         │
│  Channels       │    │  (this tool)     │    │  Releases       │
│  (IPAs)         │    │                  │    │  (hosting)      │
└─────────────────┘    └────────┬─────────┘    └─────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │  source.json     │
                        │  (AltStore       │
                        │   catalogue)     │
                        └──────────────────┘
```

1. **Monitor/Import**: The tool connects to Telegram via Telethon and downloads IPA files from configured channels
2. **Extract**: It parses each IPA (ZIP archive), extracts Info.plist metadata, and parses the code signature to get entitlements and privacy usage descriptions
3. **Publish**: Each IPA is uploaded to GitHub Releases (tagged by SHA-256 hash)
4. **Generate**: Builds `source.json` in AltStore format and commits it to the repository

## Configuration

### Environment Variables (`.env`)

Create a `.env` file:

```bash
# Required
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx

# Optional (defaults shown)
TELEGRAM_SESSION_NAME=telegram_altstore
```

Get Telegram API credentials at https://my.telegram.org/apps.

Create a GitHub Personal Access Token (classic) with `repo` scope.

### `config.toml`

```toml
[source]
name = "Telegram IPA Source"
identifier = "com.example.telegram.ipa.source"  # NEVER change after first publish
subtitle = "Apps imported from Telegram channels"
description = "IPA files imported automatically from Telegram channels."
tintColor = "2F6FED"

[github]
owner = "your-github-username"
repo = "telegram-ipa-source"
source_path = "source.json"
icons_dir = "assets/icons"
backups_dir = "backups"
verify_public_download = true

[telegram]
channels = ["@channel_one", "@channel_two"]
session_name = "telegram_altstore"

[options]
all_versions = true
tmp_dir = "tmp"
db_path = "state/altstore.db"
```

### GitHub Actions Workflow

This project includes an automated GitHub Actions workflow that:

- **Triggers**: On every `release.published` and `release.edited` event
- **Function**: Automatically updates `source.json` from all GitHub releases
- **Sorting**: Apps are grouped by Telegram channel and sorted by bundle identifier
- **Location**: `.github/workflows/update-source-on-release.yml`

To use:
1. Push the workflow files to your repository
2. The workflow runs automatically on releases
3. Generated `source.json` is committed back to the repository

## Commands

| Command | Description |
|---------|-------------|
| `import-history` | Backfill IPAs from channel history |
| `monitor` | Run as a daemon, watching for new messages |
| `generate-source` | Build `source.json` from database |
| `validate` | Validate an existing source.json |
| `publish-one` | Publish a single IPA file directly |

### Examples

```bash
# Import last 50 messages from a channel
python -m telegram_altstore.cli import-history --channel @my_channel --limit 50

# Dry run (download but don't publish)
python -m telegram_altstore.cli import-history --channel @my_channel --dry-run

# Generate source.json
python -m telegram_altstore.cli generate-source -o source.json

# Validate source.json
python -m telegram_altstore.cli validate source.json

# Publish single IPA
python -m telegram_altstore.cli publish-one myapp.ipa

# Run monitor daemon
python -m telegram_altstore.cli monitor
```

## Architecture

### Core Modules

- **`ipa.py`** — IPA file parsing. Opens the ZIP, reads `Info.plist`, parses Mach-O code signatures to extract entitlements and privacy usage descriptions (`NS*UsageDescription`).

- **`github.py`** — GitHub API client. Creates releases, uploads IPA assets, manages `source.json` in the repository with timestamped backups.

- **`source.py`** — AltStore source.json builder. Aggregates published apps, validates schema, writes the catalogue file.

- **`db.py`** — SQLite database tracking imports: channel, message ID, SHA-256 hash, bundle ID, version, build, publication status.

- **`cli.py`** — Command-line interface using argparse + Telethon for async Telegram access.

### Metadata Extraction

The tool extracts the following from each IPA:

| Field | Source |
|-------|--------|
| `name` | `CFBundleDisplayName` or `CFBundleName` |
| `bundle_id` | `CFBundleIdentifier` |
| `version` | `CFBundleShortVersionString` |
| `build` | `CFBundleVersion` |
| `min_os` | `MinimumOSVersion` |
| `entitlements` | Code signature (`CS_ENTITLEMENTS` blob) |
| `privacy` | `Info.plist` keys matching `NS*UsageDescription` |
| `icon` | `CFBundleIcons` / `CFBundlePrimaryIcon` |

Entitlements and privacy descriptions become `appPermissions` in the AltStore source, telling AltStore what permissions the app requests.

## AltStore Source Schema

The generated `source.json` follows AltStore's format:

```json
{
  "name": "Telegram IPA Source",
  "identifier": "com.example.telegram.ipa.source",
  "subtitle": "Apps imported from Telegram channels",
  "description": "...",
  "tintColor": "2F6FED",
  "apps": [
    {
      "name": "Example App",
      "bundleIdentifier": "com.example.app",
      "developerName": "Unknown",
      "localizedDescription": "Imported from Telegram.",
      "appPermissions": {
        "entitlements": [{"name": "com.apple.developer.networking.wifi"}],
        "privacy": [{"name": "Camera", "usageDescription": "Take photos"}]
      },
      "versions": [
        {
          "version": "1.0.0",
          "buildVersion": "1",
          "date": "2024-01-15",
          "downloadURL": "https://github.com/.../app.ipa",
          "size": 12345678
        }
      ]
    }
  ],
  "news": []
}
```

## Requirements

- Python 3.11+
- See `pyproject.toml` for dependencies:
  - `telethon` — Telegram client
  - `requests` — HTTP client
  - `python-dotenv` — env file loading

## Testing

```bash
pytest tests/ -v
```

The test suite includes synthetic IPA generation for verifying metadata extraction and source.json generation.

## Troubleshooting

**IPA parsing fails with "could not extract the main app code-signing entitlements"**

The IPA must have a valid code signature on its main executable. Some sideloading tools strip signatures. Use properly-signed IPAs.

**GitHub asset returns 404 after upload**

Ensure the repository and release are public, or set `verify_public_download = false` in config.

**Rate limiting**

The tool automatically retries with exponential backoff. For heavy usage, use a GitHub App token instead of a PAT.

## License

ISC