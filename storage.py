"""Append-only JSON records. SQLite locally; Supabase REST for durable hosting."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import requests

from research import utc


def encode(payload):
    return json.dumps(payload, allow_nan=False, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, path="data/basis-watch.sqlite3", url=None, key=None):
        if bool(url) != bool(key):
            raise ValueError("Both SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")
        self.url, self.key, self.path = url, key, Path(path)
        if url:
            if not url.startswith("https://"):
                raise ValueError("Database URL must use HTTPS.")
            self.endpoint = url.rstrip("/") + "/rest/v1/basis_records"
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,id))")

    @property
    def backend(self):
        return "Supabase · durable shared storage" if self.url else "SQLite · local disk only"

    def connect(self):
        return sqlite3.connect(self.path, timeout=20)

    def headers(self):
        # New sb_secret keys go in apikey only. Legacy service-role JWTs also
        # require Authorization. Never expose either key to the browser.
        h = {"apikey": self.key, "Content-Type": "application/json"}
        if not self.key.startswith("sb_secret_"):
            h["Authorization"] = "Bearer " + self.key
        return h

    def put(self, kind, identifier, payload):
        self.put_many(kind, [(identifier, payload)])

    def put_many(self, kind, items):
        now = utc().isoformat()
        records = [{"kind": kind, "id": str(k), "created_at": now, "payload": json.loads(encode(v))} for k, v in items]
        if not records:
            return
        if self.url:
            for offset in range(0, len(records), 200):
                headers = self.headers()
                headers["Prefer"] = "resolution=ignore-duplicates,return=minimal"
                r = requests.post(self.endpoint, params={"on_conflict": "kind,id"}, headers=headers,
                                  json=records[offset:offset+200], timeout=30)
                if not r.ok:
                    raise ValueError(f"Database write failed (HTTP {r.status_code}). Check the schema and server-side secrets.")
        else:
            with self.connect() as db:
                db.executemany("INSERT OR IGNORE INTO records VALUES (?,?,?,?)",
                               [(r["kind"], r["id"], now, encode(r["payload"])) for r in records])

    def records(self, kind=None, prefix=None):
        if self.url:
            rows, offset = [], 0
            while True:
                params = {"select": "*", "order": "created_at.asc,id.asc", "limit": 500, "offset": offset}
                if kind is not None:
                    params["kind"] = "eq." + kind
                if prefix is not None:
                    params["id"] = "like." + prefix + "*"
                r = requests.get(self.endpoint, params=params, headers=self.headers(), timeout=30)
                if not r.ok:
                    raise ValueError(f"Database read failed (HTTP {r.status_code}). Check the schema and server-side secrets.")
                batch = r.json()
                rows.extend(batch)
                if len(batch) < 500:
                    return rows
                offset += len(batch)
        else:
            query, args = "SELECT kind,id,created_at,payload FROM records WHERE 1=1", []
            if kind is not None:
                query += " AND kind=?"; args.append(kind)
            if prefix is not None:
                query += " AND substr(id,1,?)=?"; args.extend([len(prefix), prefix])
            with self.connect() as db:
                return [dict(kind=r[0], id=r[1], created_at=r[2], payload=json.loads(r[3])) for r in
                        db.execute(query + " ORDER BY created_at,id", args).fetchall()]


def configured_store(config):
    return Store(config.get("LEDGER_DB_PATH", str(Path(__file__).parent / "data/basis-watch.sqlite3")),
                 config.get("SUPABASE_URL"), config.get("SUPABASE_SERVICE_ROLE_KEY"))
