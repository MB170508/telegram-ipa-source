from __future__ import annotations
import hashlib, json, logging, plistlib, re, struct, zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
USAGE_RE = re.compile(r"^NS(.+?)UsageDescription$")
CS_SUPERBLOB = 0xFADE0CC0
CS_ENTITLEMENTS = 0xFADE7171
LC_CODE_SIGNATURE = 0x1D

@dataclass(frozen=True)
class IpaMetadata:
    name: str
    bundle_id: str
    version: str
    build: str
    min_os: str | None
    entitlements: tuple[str, ...]
    privacy: tuple[tuple[str, str], ...]
    icon_path: str | None
    sha256: str
    size: int

def _read_plist(z: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        value = plistlib.loads(z.read(name))
    except (KeyError, plistlib.InvalidFileException, ValueError) as e:
        raise IpaError(f"invalid or missing Info.plist: {name}") from e
    if not isinstance(value, dict): raise IpaError(f"Info.plist is not a dictionary: {name}")
    return value

class IpaError(ValueError): pass

def _parse_signature(data: bytes) -> dict[str, Any] | None:
    """Read signed Mach-O entitlements from LC_CODE_SIGNATURE (thin/fat)."""
    if len(data) < 28: return None
    magic = data[:4]
    if magic in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
        # Fat binary: fat headers are always big-endian; each slice carries its own magic.
        is64 = magic == b'\xca\xfe\xba\xbf'
        nfat = struct.unpack_from('>I', data, 4)[0]; off = 8; step = 32 if is64 else 20
        for _ in range(min(nfat, 32)):
            if off + step > len(data): break
            _, slice_off, slice_size, _, _ = struct.unpack_from('>IIIII' if is64 else '>IIII', data, off)
            if slice_off + slice_size <= len(data) and slice_size > 0:
                result = _parse_signature(data[slice_off:slice_off + slice_size])
                if result: return result
            off += step
        return None
    if magic == b'\xcf\xfa\xed\xfe': endian, is64 = '<', True      # MH_MAGIC_64 little-endian
    elif magic == b'\xfe\xed\xfa\xcf': endian, is64 = '>', True      # MH_MAGIC_64 big-endian
    elif magic == b'\xce\xfa\xed\xfe': endian, is64 = '<', False     # MH_MAGIC little-endian
    elif magic == b'\xfe\xed\xfa\xce': endian, is64 = '>', False     # MH_MAGIC big-endian
    else: return None
    try:
        ncmds=struct.unpack_from(endian+'I',data,16)[0]; off=32 if is64 else 28; sig=None
        for _ in range(min(ncmds,10000)):
            cmd,cmdsize=struct.unpack_from(endian+'II',data,off)
            if cmdsize<8 or off+cmdsize>len(data): return None
            if cmd==LC_CODE_SIGNATURE and cmdsize>=16: sig=struct.unpack_from(endian+'II',data,off+8); break
            off+=cmdsize
        if not sig: return None
        soff,ssize=sig; blob=data[soff:soff+ssize]
        if len(blob)<12: return None
        magic, length, count=struct.unpack_from('>III',blob,0)
        if magic!=CS_SUPERBLOB or length>len(blob): return None
        for i in range(min(count,128)):
            slot,boff=struct.unpack_from('>II',blob,12+i*8)
            if boff+8>length: continue
            bmagic,blen=struct.unpack_from('>II',blob,boff)
            if bmagic==CS_ENTITLEMENTS and boff+blen<=length:
                ent=plistlib.loads(blob[boff+8:boff+blen])
                return ent if isinstance(ent,dict) else None
    except (struct.error, ValueError, plistlib.InvalidFileException): return None
    return None

def inspect_ipa(path: str | Path) -> IpaMetadata:
    path=Path(path)
    if not path.is_file() or path.suffix.lower()!='.ipa': raise IpaError('not an IPA file')
    digest=hashlib.sha256(); size=0
    with path.open('rb') as f:
        while chunk:=f.read(1024*1024): digest.update(chunk); size+=len(chunk)
    try: z=zipfile.ZipFile(path)
    except zipfile.BadZipFile as e: raise IpaError('IPA is not a valid ZIP archive') from e
    with z:
        infos=[n for n in z.namelist() if n.startswith('Payload/') and n.endswith('.app/Info.plist') and '.appex/' not in n]
        if len(infos)!=1: raise IpaError(f'expected one main app Info.plist, found {len(infos)}')
        main=infos[0]; info=_read_plist(z,main); app_prefix=main.rsplit('Info.plist',1)[0]
        required=('CFBundleIdentifier','CFBundleShortVersionString','CFBundleVersion')
        missing=[k for k in required if not info.get(k)]
        if missing: raise IpaError('missing required Info.plist fields: '+', '.join(missing))
        plist_names=[n for n in z.namelist() if n.startswith('Payload/') and (n.endswith('.app/Info.plist') or n.endswith('.appex/Info.plist'))]
        entitlements:set[str]=set(); privacy:dict[str,str]={}; found_signed_main=False
        for plist_name in plist_names:
            pi=_read_plist(z,plist_name)
            for key,value in pi.items():
                match=USAGE_RE.match(str(key))
                if match and isinstance(value,str): privacy[match.group(1)]=value
            base=plist_name.rsplit('Info.plist',1)[0]
            executable=pi.get('CFBundleExecutable')
            if not executable: continue
            exe_path=base+str(executable)
            try: signature=_parse_signature(z.read(exe_path))
            except KeyError: raise IpaError(f'missing app executable: {exe_path}')
            if signature is not None:
                if plist_name==main: found_signed_main=True
                entitlements.update(str(k) for k in signature)
        if not found_signed_main:
            # Some IPA signing pipelines strip executable code signatures. Do
            # not publish guessed/empty permissions as if extraction succeeded.
            raise IpaError('could not extract the main app code-signing entitlements; refusing incomplete AltStore permissions')
        icon=None
        for key in ('CFBundleIcons','CFBundleIcons~ipad'):
            primary=info.get(key,{}).get('CFBundlePrimaryIcon',{}).get('CFBundleIconFiles',[]) if isinstance(info.get(key),dict) else []
            for stem in reversed(primary):
                for suffix in ('','@2x','@3x'):
                    candidate=app_prefix+str(stem)+suffix+'.png'
                    if candidate in z.namelist(): icon=candidate; break
                if icon: break
            if icon: break
        return IpaMetadata(str(info.get('CFBundleDisplayName') or info.get('CFBundleName') or info['CFBundleIdentifier']),str(info['CFBundleIdentifier']),str(info['CFBundleShortVersionString']),str(info['CFBundleVersion']),str(info['MinimumOSVersion']) if info.get('MinimumOSVersion') else None,tuple(sorted(entitlements)),tuple(sorted(privacy.items())),icon,digest.hexdigest(),size)

def metadata_dict(meta: IpaMetadata) -> dict[str,Any]: return asdict(meta)
