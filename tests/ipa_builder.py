"""Build synthetic but structurally real IPA archives for tests.

The Mach-O executable produced here is a genuine 64-bit Mach-O binary with a
real LC_CODE_SIGNATURE superblob containing a real entitlements plist, so the
entitlement extraction path is exercised against actual binary structures.
"""
from __future__ import annotations
import plistlib, struct, zipfile
from pathlib import Path

CS_MAGIC_EMBEDDED_SIGNATURE = 0xFADE0CC0
CS_MAGIC_ENTITLEMENTS = 0xFADE7171
LC_CODE_SIGNATURE = 0x1D
MH_MAGIC_64 = 0xFEEDFACF


def build_entitlements_superblob(entitlements: dict) -> bytes:
    ent = plistlib.dumps(entitlements, fmt=plistlib.FMT_XML)
    # CS_ENTITLEMENTS blob: uint32 magic, uint32 length, then the XML plist.
    ent_blob = struct.pack('>II', CS_MAGIC_ENTITLEMENTS, len(ent) + 8) + ent
    # SuperBlob: header (12B) + index entries (8B each) + blobs.
    index = struct.pack('>II', 5, 12 + 8)  # slot 5 = entitlements, blob at offset 20
    body = index + ent_blob
    return struct.pack('>III', CS_MAGIC_EMBEDDED_SIGNATURE, len(body) + 12, 1) + body


def build_macho(entitlements: dict, pad: int = 4096) -> bytes:
    """Return a 64-bit little-endian Mach-O with one LC_CODE_SIGNATURE load command."""
    signature = build_entitlements_superblob(entitlements)
    cmdsize = 16
    # header (32 bytes) + load command (16) + padding to hold the signature blob
    header_size = 32 + cmdsize
    total = header_size + len(signature) + pad
    # mach_header_64: magic, cputype, cpusubtype, filetype=MH_EXECUTE(2),
    # ncmds=1, sizeofcmds=cmdsize, flags, reserved
    header = struct.pack('<IiiIIIII', MH_MAGIC_64, 0x0100000C, 0, 2, 1, cmdsize, 0, 0)[:32]
    load_cmd = struct.pack('<IIII', LC_CODE_SIGNATURE, cmdsize, header_size, len(signature))
    data = bytearray(header + load_cmd)
    data += b'\x00' * (header_size - len(data))
    data += signature
    data += b'\x00' * (total - len(data))
    return bytes(data)


def build_ipa(
    path: str | Path,
    bundle_id: str = "com.example.demo",
    name: str = "Demo",
    version: str = "1.2.3",
    build: str = "42",
    min_os: str = "14.0",
    entitlements: dict | None = None,
    privacy: dict | None = None,
    extensions: list[tuple[str, dict, dict]] | None = None,
    signed: bool = True,
    info_overrides: dict | None = None,
) -> Path:
    entitlements = entitlements if entitlements is not None else {
        "application-identifier": f"ABCDE12345.{bundle_id}",
        "com.apple.developer.team-identifier": "ABCDE12345",
        "get-task-allow": False,
    }
    privacy = privacy if privacy is not None else {
        "NSCameraUsageDescription": "Demo needs the camera.",
    }
    extensions = extensions or []
    info_overrides = info_overrides or {}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    app_dir = f"Payload/{name}.app"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        info = {
            "CFBundleIdentifier": bundle_id,
            "CFBundleName": name,
            "CFBundleDisplayName": name,
            "CFBundleShortVersionString": version,
            "CFBundleVersion": build,
            "CFBundleExecutable": name,
            "MinimumOSVersion": min_os,
            "CFBundleIcons": {"CFBundlePrimaryIcon": {"CFBundleIconFiles": ["AppIcon"]}},
            **privacy,
        }
        if info_overrides:
            for k, v in info_overrides.items():
                if v is not None:
                    info[k] = v
                else:
                    info.pop(k, None)
        z.writestr(f"{app_dir}/Info.plist", plistlib.dumps(info))
        z.writestr(f"{app_dir}/{name}", build_macho(entitlements) if signed else b"\xcf\xfa\xed\xfe" + b"\x00" * 64)
        z.writestr(f"{app_dir}/AppIcon60x60@2x.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        for ext_bundle, ext_ent, ext_privacy in extensions:
            ext_dir = f"{app_dir}/PlugIns/{ext_bundle}.appex"
            ext_info = {
                "CFBundleIdentifier": f"{bundle_id}.{ext_bundle}",
                "CFBundleName": ext_bundle,
                "CFBundleShortVersionString": version,
                "CFBundleVersion": build,
                "CFBundleExecutable": ext_bundle,
                **ext_privacy,
            }
            z.writestr(f"{ext_dir}/Info.plist", plistlib.dumps(ext_info))
            z.writestr(f"{ext_dir}/{ext_bundle}", build_macho(ext_ent))
    return path
