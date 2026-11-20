from __future__ import annotations
import json
from pathlib import Path

import pytest

from telegram_altstore.source import SourceError, build_source, validate_source, write_source

CONFIG = {
    "source": {"name": "Test Source", "identifier": "com.example.source", "subtitle": "sub", "description": "desc", "tintColor": "2F6FED"},
    "options": {"all_versions": True},
}


def row(bundle, version, build, sha, updated="2026-01-01 00:00:00", size=1234, ents=("com.apple.x",), privacy=(("Camera", "why"),)):
    return {
        "bundle_id": bundle, "version": version, "build": build, "asset_url": f"https://github.com/o/r/releases/download/ipa-{sha}/{bundle}.ipa",
        "updated_at": updated,
        "metadata_json": json.dumps({"name": "App", "size": size, "entitlements": list(ents), "privacy": [list(p) for p in privacy], "min_os": "14.0"}),
    }


def test_build_source_groups_versions_newest_first():
    rows = [row("com.a", "1.0", "1", "a1", updated="2026-01-01 00:00:00"), row("com.a", "2.0", "2", "a2", updated="2026-02-01 00:00:00"), row("com.b", "1.0", "9", "b1")]
    source = build_source(CONFIG, rows)
    assert len(source["apps"]) == 2
    app = source["apps"][0]
    assert app["bundleIdentifier"] == "com.a"
    assert [v["version"] for v in app["versions"]] == ["2.0", "1.0"]
    assert app["versions"][0]["buildVersion"] == "2"
    assert app["versions"][0]["size"] == 1234
    assert app["versions"][0]["minOSVersion"] == "14.0"


def test_permissions_are_not_fabricated():
    source = build_source(CONFIG, [row("com.a", "1.0", "1", "a1", ents=(), privacy=())])
    app = source["apps"][0]
    assert app["appPermissions"]["entitlements"] == []
    assert app["appPermissions"]["privacy"] == []


def test_validator_rejects_http_and_duplicates():
    source = build_source(CONFIG, [row("com.a", "1.0", "1", "a1")])
    source["apps"][0]["versions"][0]["downloadURL"] = "http://example.com/a.ipa"
    with pytest.raises(SourceError):
        validate_source(source)
    source = build_source(CONFIG, [row("com.a", "1.0", "1", "a1"), row("com.a", "1.1", "2", "a2")])
    assert validate_source(source)


def test_write_source_roundtrip(tmp_path):
    source = build_source(CONFIG, [row("com.a", "1.0", "1", "a1")])
    out = tmp_path / "source.json"
    write_source(out, source)
    assert json.loads(out.read_text())["identifier"] == "com.example.source"
