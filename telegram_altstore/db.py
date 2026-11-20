from __future__ import annotations
import json, logging, os, sqlite3
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)
class Database:
    def __init__(self, path: str):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS imports (id INTEGER PRIMARY KEY, channel TEXT NOT NULL, message_id INTEGER NOT NULL, sha256 TEXT NOT NULL UNIQUE, bundle_id TEXT, version TEXT, build TEXT, status TEXT NOT NULL, release_tag TEXT, asset_url TEXT, metadata_json TEXT, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(channel,message_id)); CREATE INDEX IF NOT EXISTS imports_bundle ON imports(bundle_id);''')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path); db.row_factory=sqlite3.Row
        try: yield db; db.commit()
        finally: db.close()
    def seen_message(self, channel, message_id):
        with self.connect() as d: return d.execute('SELECT 1 FROM imports WHERE channel=? AND message_id=?',(channel,message_id)).fetchone() is not None
    def seen_hash(self, sha256):
        with self.connect() as d: return d.execute('SELECT 1 FROM imports WHERE sha256=?',(sha256,)).fetchone() is not None
    def add(self, channel, message_id, meta, status='downloaded'):
        with self.connect() as d: d.execute('INSERT OR IGNORE INTO imports(channel,message_id,sha256,bundle_id,version,build,status,metadata_json) VALUES(?,?,?,?,?,?,?,?)',(channel,message_id,meta.sha256,meta.bundle_id,meta.version,meta.build,status,json.dumps(meta.__dict__ if hasattr(meta,'__dict__') else {})))
    def mark(self, sha256, status, **fields):
        allowed={'release_tag','asset_url','error'}; vals=[status]; sets=['status=?']
        for k,v in fields.items():
            if k in allowed: sets.append(k+'=?'); vals.append(v)
        sets.append('updated_at=CURRENT_TIMESTAMP'); vals.append(sha256)
        with self.connect() as d: d.execute('UPDATE imports SET '+','.join(sets)+' WHERE sha256=?',vals)
    def rows(self):
        with self.connect() as d: return [dict(r) for r in d.execute("SELECT * FROM imports WHERE status='published' ORDER BY bundle_id, version DESC, build DESC")]
