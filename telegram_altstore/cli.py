from __future__ import annotations
import argparse, asyncio, json, logging, os, sys, tempfile, time, tomllib
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename

from .db import Database
from .github import GitHub, GitHubError
from .ipa import IpaError, inspect_ipa
from .source import SourceError, build_source, validate_source, write_source

load_dotenv()
log = logging.getLogger(__name__)

def load_config(path='config.toml'):
    p=Path(path)
    if not p.exists(): p=Path('config.example.toml')
    with p.open('rb') as f: return tomllib.load(f)

def configure_logging(level=logging.INFO):
    logging.basicConfig(level=level, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

def _channel_id(channel):
    s=channel.strip()
    if s.lstrip('-').isdigit(): return int(s)
    if s.startswith('https://t.me/'): return s.split('/')[-1].split('?')[0]
    return s

async def _download_media(client, message, dest):
    progress=None
    await client.download_media(message, dest, progress_callback=progress)
    return dest

def _is_ipa_document(doc):
    if not doc: return False
    if getattr(doc,'mime_type','') in ('application/octet-stream','application/x-ios-app','application/zip'):
        return any(getattr(a,'file_name','').lower().endswith('.ipa') for a in doc.attributes)
    return False

async def _process_message(client, db, gh, cfg, channel, message, dry_run=False):
    if db.seen_message(channel, message.id): return False
    doc=message.document
    if not _is_ipa_document(doc): return False
    meta=inspect_ipa if not dry_run else None
    tmp_dir=Path(cfg['options'].get('tmp_dir','tmp')); tmp_dir.mkdir(parents=True,exist_ok=True)
    path=tmp_dir/f'{channel}_{message.id}.ipa'
    if dry_run:
        log.info('[dry-run] would download %s message %s', channel, message.id); return True
    await _download_media(client, message, str(path))
    try:
        meta=inspect_ipa(path)
        if db.seen_hash(meta.sha256):
            log.info('duplicate SHA-256 %s; skipping',meta.sha256); return True
        db.add(channel, message.id, meta, status='validated')
        tag,url=gh.publish_ipa(path, meta.sha256, meta.bundle_id, meta.version, meta.build)
        db.mark(meta.sha256, 'published', release_tag=tag, asset_url=url)
        log.info('published %s %s (%s) -> %s', meta.bundle_id, meta.version, meta.build, url)
        return True
    except Exception as e:
        log.exception('failed to process %s/%s',channel,message.id)
        try: db.add(channel, message.id, {'sha256':'unknown'}, status='failed', error=str(e))
        except Exception: pass
        return False
    finally:
        try: path.unlink(missing_ok=True)
        except Exception: pass

async def cmd_import_history(args):
    cfg=load_config(args.config); db=Database(cfg['options'].get('db_path','state/altstore.db'))
    gh=GitHub(cfg['github']['owner'],cfg['github']['repo'],os.environ['GITHUB_TOKEN'], verify=cfg['github'].get('verify_public_download',True))
    async with TelegramClient(cfg['telegram'].get('session_name','telegram_altstore'), int(os.environ['TELEGRAM_API_ID']), os.environ['TELEGRAM_API_HASH']) as client:
        for c in cfg['telegram']['channels']:
            entity=await client.get_entity(_channel_id(c)); log.info('importing %s',c)
            async for message in client.iter_messages(entity):
                if not _is_ipa_document(message.document): continue
                await _process_message(client, db, gh, cfg, str(entity.id), message, dry_run=args.dry_run)
                if args.limit and db.rows().__len__()>=args.limit: break

async def cmd_monitor(args):
    cfg=load_config(args.config); db=Database(cfg['options'].get('db_path','state/altstore.db'))
    gh=GitHub(cfg['github']['owner'],cfg['github']['repo'],os.environ['GITHUB_TOKEN'], verify=cfg['github'].get('verify_public_download',True))
    client=TelegramClient(cfg['telegram'].get('session_name','telegram_altstore'), int(os.environ['TELEGRAM_API_ID']), os.environ['TELEGRAM_API_HASH'])
    @client.on(events.NewMessage(chats=[_channel_id(c) for c in cfg['telegram']['channels']]))
    async def handler(event):
        if not _is_ipa_document(event.message.document): return
        channel=event.chat_id
        await _process_message(client, db, gh, cfg, str(channel), event.message)
        if cfg['options'].get('auto_push_source',True): await _push_source(cfg, db, gh)
    await client.start()
    log.info('monitor started'); await client.run_until_disconnected()

async def _push_source(cfg, db, gh):
    rows=db.rows(); source=build_source(cfg, rows)
    gh.publish_source(source, cfg['github']['source_path'], cfg['github']['backups_dir'])

async def cmd_generate_source(args):
    cfg=load_config(args.config); db=Database(cfg['options'].get('db_path','state/altstore.db'))
    source=build_source(cfg, db.rows())
    out=Path(args.output) if args.output else Path(cfg['github']['source_path'])
    write_source(out, source); log.info('wrote %s',out)

def cmd_validate(args):
    source=json.loads(Path(args.source).read_text())
    try: validate_source(source); print('source.json is valid'); return 0
    except SourceError as e: print('validation failed:',e); return 1

async def cmd_publish_one(args):
    cfg=load_config(args.config); db=Database(cfg['options'].get('db_path','state/altstore.db'))
    gh=GitHub(cfg['github']['owner'],cfg['github']['repo'],os.environ['GITHUB_TOKEN'])
    meta=inspect_ipa(args.ipa); tag,url=gh.publish_ipa(Path(args.ipa), meta.sha256, meta.bundle_id, meta.version, meta.build)
    print(tag, url)

def main(argv=None):
    configure_logging(); p=argparse.ArgumentParser('telegram-altstore')
    p.add_argument('-c','--config',default='config.toml')
    p.add_argument('--dry-run',action='store_true')
    sub=p.add_subparsers(dest='cmd')
    h=sub.add_parser('import-history'); h.add_argument('--limit',type=int)
    sub.add_parser('monitor')
    sub.add_parser('generate-source').add_argument('-o','--output')
    v=sub.add_parser('validate'); v.add_argument('source')
    o=sub.add_parser('publish-one'); o.add_argument('ipa')
    args=p.parse_args(argv)
    if args.dry_run and not args.config: print('dry-run requires config')
    if args.cmd=='import-history': asyncio.run(cmd_import_history(args))
    elif args.cmd=='monitor': asyncio.run(cmd_monitor(args))
    elif args.cmd=='generate-source': asyncio.run(cmd_generate_source(args))
    elif args.cmd=='validate': sys.exit(cmd_validate(args))
    elif args.cmd=='publish-one': asyncio.run(cmd_publish_one(args))
    else: p.print_help()

if __name__=='__main__': main()
