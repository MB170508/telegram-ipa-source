from __future__ import annotations
import json, sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from ipa_builder import build_ipa
from telegram_altstore.ipa import IpaError, inspect_ipa


def test_inspect_real_macho_entitlements_and_privacy(tmp_path):
    ipa = build_ipa(tmp_path / "Demo.ipa")
    meta = inspect_ipa(ipa)
    assert meta.bundle_id == "com.example.demo"
    assert meta.version == "1.2.3"
    assert meta.build == "42"
    assert meta.min_os == "14.0"
    assert meta.name == "Demo"
    assert "application-identifier" in meta.entitlements
    assert meta.privacy == (("Camera", "Demo needs the camera."),)
    assert meta.size == ipa.stat().st_size
    assert len(meta.sha256) == 64


def test_extension_entitlements_are_included(tmp_path):
    ipa = build_ipa(
        tmp_path / "Demo.ipa",
        extensions=[("Widget", {"com.apple.security.application-groups": ["group.demo"]}, {"NSPhotoLibraryUsageDescription": "Widget photos"})],
    )
    meta = inspect_ipa(ipa)
    assert "com.apple.security.application-groups" in meta.entitlements
    assert ("PhotoLibrary", "Widget photos") in meta.privacy


def test_unsigned_ipa_is_rejected(tmp_path):
    ipa = build_ipa(tmp_path / "Unsigned.ipa", signed=False)
    with pytest.raises(IpaError, match="entitlements"):
        inspect_ipa(ipa)


def test_non_zip_is_rejected(tmp_path):
    bad = tmp_path / "bad.ipa"
    bad.write_bytes(b"not a zip")
    with pytest.raises(IpaError):
        inspect_ipa(bad)


def test_missing_version_is_rejected(tmp_path):
    ipa = build_ipa(tmp_path / "NoVersion.ipa", info_overrides={"CFBundleShortVersionString": None})
    with pytest.raises(IpaError, match="missing required Info.plist fields"):
        inspect_ipa(ipa)
