#!/usr/bin/env python3
"""
Generate source.json for AltStore from GitHub releases.
This script:
1. Creates database if it doesn't exist
2. Fetches all GitHub releases
3. Populates database with release info
4. Generates source.json from published apps
5. Validates the output
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

try:
    import tomllib as toml
except ImportError:
    import tomli as toml

try:
    import requests
except ImportError:
    print("Error: requests module required. Install with: pip install requests")
    sys.exit(1)

def create_database_if_needed(db_path):
    """Create database schema if it doesn't exist."""
    if not db_path.exists():
        conn = sqlite3.connect(db_path)
        conn.executescript('''
            CREATE TABLE imports (
                id INTEGER PRIMARY KEY, 
                channel TEXT NOT NULL, 
                message_id INTEGER NOT NULL, 
                sha256 TEXT NOT NULL UNIQUE, 
                bundle_id TEXT, 
                version TEXT, 
                build TEXT, 
                status TEXT NOT NULL, 
                release_tag TEXT, 
                asset_url TEXT, 
                metadata_json TEXT, 
                error TEXT, 
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, 
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, 
                UNIQUE(channel, message_id)
            );
            CREATE INDEX IF NOT EXISTS imports_bundle ON imports(bundle_id);
        ''')
        conn.commit()
        conn.close()
        print(f"Created new database: {db_path}")

def load_config():
    """Load config.toml or use defaults."""
    config_path = Path('config.toml')
    if config_path.exists():
        try:
            with open(config_path, 'rb') as f:
                return toml.load(f)
        except Exception as e:
            print(f"Error loading config.toml: {e}")
    
    # Default config
    return {
        'source': {
            'name': 'Telegram IPA Source',
            'identifier': 'com.benzo.altstore',
            'subtitle': 'Apps imported from Telegram channels',
            'description': 'IPA files imported automatically from Telegram channels.',
            'tintColor': '38761D'
        }
    }

def fetch_github_releases(repo, token):
    """Fetch all releases from GitHub API."""
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json',
        'X-GitHub-Api-Version': '2022-11-28'
    }
    
    releases_url = f'https://api.github.com/repos/{repo}/releases'
    try:
        response = requests.get(releases_url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching releases: {e}")
        return []

def process_releases(conn, releases):
    """Process GitHub releases and populate database."""
    cursor = conn.cursor()
    
    # Get existing releases
    cursor.execute("SELECT release_tag FROM imports WHERE status='published'")
    existing_releases = {row[0] for row in cursor.fetchall()}
    
    new_count = 0
    for release in releases:
        release_tag = release['tag_name']
        
        # Skip if we already have this release
        if release_tag in existing_releases:
            continue
        
        # Look for IPA assets
        for asset in release['assets']:
            if asset['name'].endswith('.ipa'):
                asset_url = asset['browser_download_url']
                
                # Extract app info from release name/tag
                if release_tag.startswith('ipa-'):
                    sha256_part = release_tag[4:]
                else:
                    sha256_part = release_tag
                
                # Try to get metadata from release body
                metadata = {}
                if release.get('body'):
                    try:
                        metadata = json.loads(release['body'])
                    except json.JSONDecodeError:
                        # Try to extract basic info from release name/body
                        if 'bundle_id' not in metadata:
                            metadata['bundle_id'] = 'unknown'
                        if 'version' not in metadata:
                            metadata['version'] = '1.0'
                        if 'build' not in metadata:
                            metadata['build'] = '1'
                    except Exception:
                        pass
                
                # Insert into database
                cursor.execute('''
                    INSERT OR REPLACE INTO imports 
                    (channel, message_id, sha256, bundle_id, version, build, status, release_tag, asset_url, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    'github', 0, sha256_part[:64],
                    metadata.get('bundle_id', 'unknown'),
                    metadata.get('version', '1.0'),
                    metadata.get('build', '1'),
                    'published',
                    release_tag,
                    asset_url,
                    json.dumps(metadata)
                ))
                new_count += 1
    
    conn.commit()
    return new_count

def build_source_json(config, conn):
    """Build source.json from published apps in database."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM imports WHERE status='published'")
    rows = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]
    
    # Group apps by channel first
    channels = {}
    for r in rows:
        if not r.get('asset_url'):
            continue
            
        channel = r['channel']
        if channel not in channels:
            channels[channel] = {}
            
        m = json.loads(r['metadata_json']) if r.get('metadata_json') else {}
        bid = r['bundle_id']
        
        app = channels[channel].setdefault(bid, {
            'name': m.get('name', bid),
            'bundleIdentifier': bid,
            'developerName': 'Unknown',
            'localizedDescription': f'Imported from Telegram channel {channel}.',
            'versions': [],
            'appPermissions': {
                'entitlements': [{'name': x} for x in m.get('entitlements', [])],
                'privacy': [{'name': k, 'usageDescription': v} for k,v in m.get('privacy', [])]
            }
        })
        
        version = {
            'version': r['version'],
            'buildVersion': r['build'],
            'date': r['updated_at'][:10],
            'downloadURL': r['asset_url'],
            'size': m.get('size', 0)
        }
        
        if m.get('min_os'):
            version['minOSVersion'] = m['min_os']
            
        app['versions'].append(version)
    
    # Sort versions by version + build (newest first) within each app
    # and sort apps within each channel by bundle ID
    all_apps = []
    for channel, apps in sorted(channels.items()):
        for app in sorted(apps.values(), key=lambda x: x['bundleIdentifier']):
            app['versions'].sort(key=lambda x: x['version'] + x['buildVersion'], reverse=True)
            all_apps.append(app)
    
    return {
        'name': config['source']['name'],
        'identifier': config['source']['identifier'],
        'subtitle': config['source'].get('subtitle', ''),
        'description': config['source'].get('description', ''),
        'tintColor': config['source'].get('tintColor', '#2F6FED'),
        'apps': all_apps,
        'news': []
    }

def main():
    """Main function."""
    # Setup
    Path('state').mkdir(exist_ok=True)
    db_path = Path('state/altstore.db')
    
    # Create database if needed
    create_database_if_needed(db_path)
    
    # Load config
    config = load_config()
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Get GitHub token and repo
    token = os.environ.get('GITHUB_TOKEN')
    repo = os.environ.get('GITHUB_REPOSITORY', 'MB170508/telegram-ipa-source')
    
    if not token:
        print("Warning: GITHUB_TOKEN not set. Will use only existing database entries.")
        releases = []
    else:
        # Fetch and process releases
        releases = fetch_github_releases(repo, token)
        new_count = process_releases(conn, releases)
        print(f"Processed {new_count} new releases from {len(releases)} total releases")
    
    # Build source.json
    source_data = build_source_json(config, conn)
    
    # Write source.json
    with open('source.json', 'w', encoding='utf-8') as f:
        json.dump(source_data, f, indent=2, ensure_ascii=False)
    
    print(f"Wrote source.json with {len(source_data['apps'])} apps")
    
    # Validate the file
    try:
        with open('source.json', 'r', encoding='utf-8') as f:
            json.load(f)
        print("✓ source.json is valid JSON")
    except Exception as e:
        print(f"✗ Error validating source.json: {e}")
        sys.exit(1)
    
    conn.close()

if __name__ == '__main__':
    main()