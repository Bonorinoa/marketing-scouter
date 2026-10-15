"""SQLite store. Three tables:
  candidates  one row per source item (scored by Jev), status new/drafted/approved/dismissed
  drafts      append-only; the user's own take is stored verbatim and never overwritten
  events      audit trail: scout runs, Jev usage, drafts, status changes
Nothing in this package publishes anywhere: 'approved' only records that the human accepted it.
"""
import json
import os
import sqlite3
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY, panel TEXT NOT NULL, source TEXT NOT NULL, title TEXT NOT NULL,
  url TEXT NOT NULL, summary TEXT, published TEXT, fetched_at REAL NOT NULL, meta TEXT,
  relevance REAL, lens TEXT, scores TEXT, personal REAL, scored_with TEXT, scored_at REAL,
  status TEXT NOT NULL DEFAULT 'new'
);
CREATE INDEX IF NOT EXISTS idx_cand_panel ON candidates(panel, relevance);
CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT NOT NULL, user_take TEXT,
  lens TEXT, text TEXT NOT NULL, rationale TEXT, flags TEXT, model TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL, detail TEXT
);
"""
STATUSES = ("new", "drafted", "approved", "dismissed")


def connect(path=None):
    path = path or config.DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def log(db, kind, **detail):
    db.execute("INSERT INTO events(ts, kind, detail) VALUES (?,?,?)",
               (time.time(), kind, json.dumps(detail, ensure_ascii=False)))
    db.commit()


def upsert_candidates(db, items):
    """Insert unseen items; return the ids that were new. Existing rows (and their scores) are untouched."""
    new_ids = []
    from .sources import candidate_id
    for it in items:
        cid = candidate_id(it["url"])
        cur = db.execute(
            "INSERT OR IGNORE INTO candidates(id,panel,source,title,url,summary,published,fetched_at,meta)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, it["panel"], it["source"], it["title"], it["url"], it.get("summary", ""),
             it.get("published", ""), time.time(), json.dumps(it.get("meta", {}), ensure_ascii=False)))
        if cur.rowcount:
            new_ids.append(cid)
    db.commit()
    return new_ids


def unscored(db, version, only_panel=None, only_source=None, rescore=False):
    q = "SELECT * FROM candidates WHERE status != 'dismissed'"
    args = []
    if not rescore:
        q += " AND (scored_with IS NULL OR scored_with != ?)"
        args.append(version)
    if only_panel:
        q += " AND panel = ?"
        args.append(only_panel)
    if only_source:
        q += " AND source = ?"
        args.append(only_source)
    return [dict(r) for r in db.execute(q, args)]


def save_score(db, cid, version, s):
    db.execute("UPDATE candidates SET relevance=?, lens=?, scores=?, personal=?, scored_with=?, scored_at=?"
               " WHERE id=?", (s["relevance"], s["lens"], json.dumps(s["scores"], ensure_ascii=False),
                               s["personal"], version, time.time(), cid))
    db.commit()


def _row(r):
    d = dict(r)
    d["meta"] = json.loads(d.get("meta") or "{}")
    d["scores"] = json.loads(d.get("scores") or "{}")
    return d


def list_candidates(db, panel=None, min_relevance=0.0, status=None, limit=100):
    q = "SELECT * FROM candidates WHERE relevance IS NOT NULL AND relevance >= ?"
    args = [min_relevance]
    if panel:
        q += " AND panel = ?"
        args.append(panel)
    if status:
        q += " AND status = ?"
        args.append(status)
    else:
        q += " AND status != 'dismissed'"
    q += " ORDER BY relevance DESC LIMIT ?"
    args.append(limit)
    return [_row(r) for r in db.execute(q, args)]


def get_candidate(db, cid):
    r = db.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
    return _row(r) if r else None


def set_status(db, cid, status):
    if status not in STATUSES:
        raise ValueError("status must be one of %s" % (STATUSES,))
    db.execute("UPDATE candidates SET status=? WHERE id=?", (status, cid))
    db.commit()
    log(db, "status", id=cid, status=status)


def add_draft(db, cid, user_take, lens, text, rationale, flags, model):
    cur = db.execute("INSERT INTO drafts(candidate_id,user_take,lens,text,rationale,flags,model,created_at)"
                     " VALUES (?,?,?,?,?,?,?,?)",
                     (cid, user_take, lens, text, rationale, json.dumps(flags), model, time.time()))
    db.commit()
    if get_candidate(db, cid)["status"] == "new":
        set_status(db, cid, "drafted")
    return cur.lastrowid


def list_drafts(db, cid):
    return [dict(r) for r in db.execute("SELECT * FROM drafts WHERE candidate_id=? ORDER BY id DESC", (cid,))]
