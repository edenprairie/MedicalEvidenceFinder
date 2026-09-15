"""SQLite-backed immutable skill registry used to demonstrate production activation."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import uuid


class ProductionSkillRegistry:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS skill_versions (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
              content TEXT NOT NULL, content_hash TEXT NOT NULL, status TEXT NOT NULL,
              author TEXT NOT NULL, reviewer TEXT, reason TEXT NOT NULL,
              created_at TEXT NOT NULL, approved_at TEXT, UNIQUE(name, version)
            );
            CREATE TABLE IF NOT EXISTS skill_assignments (
              environment TEXT NOT NULL, name TEXT NOT NULL, version_id TEXT NOT NULL,
              activated_by TEXT NOT NULL, activated_at TEXT NOT NULL,
              PRIMARY KEY(environment, name)
            );
            """)

    def versions(self, name):
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT id,name,version,content_hash,status,author,reviewer,reason,created_at,approved_at FROM skill_versions WHERE name=? ORDER BY created_at DESC", (name,)).fetchall()
        keys = "id name version content_hash status author reviewer reason created_at approved_at".split()
        return [dict(zip(keys, row)) for row in rows]

    def submit(self, name, version, content, author, reason):
        if not all(str(value).strip() for value in (name, version, content, author, reason)):
            raise ValueError("Skill submissions require name, version, content, author, and reason")
        record = (str(uuid.uuid4()), name, version, content, hashlib.sha256(content.encode()).hexdigest(), "draft", author, None, reason, datetime.now(timezone.utc).isoformat(), None)
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO skill_versions VALUES (?,?,?,?,?,?,?,?,?,?,?)", record)
        return self.versions(name)[0]

    def approve(self, version_id, reviewer):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE skill_versions SET status='approved', reviewer=?, approved_at=? WHERE id=? AND status='draft'", (reviewer, datetime.now(timezone.utc).isoformat(), version_id))
        return self._get(version_id)

    def activate(self, environment, version_id, actor):
        record = self._get(version_id)
        if record["status"] != "approved":
            raise ValueError("Only approved skill versions can be activated")
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO skill_assignments VALUES (?,?,?,?,?)", (environment, record["name"], version_id, actor, datetime.now(timezone.utc).isoformat()))
            db.execute("UPDATE skill_versions SET status='active' WHERE id=?", (version_id,))
        return self.current(environment, record["name"])

    def current(self, environment, name):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT v.id,v.name,v.version,v.content_hash,v.status,v.author,v.reviewer,v.reason,v.created_at,v.approved_at FROM skill_assignments a JOIN skill_versions v ON v.id=a.version_id WHERE a.environment=? AND a.name=?", (environment, name)).fetchone()
        if not row:
            return None
        keys = "id name version content_hash status author reviewer reason created_at approved_at".split()
        return dict(zip(keys, row))

    def _get(self, version_id):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT id,name,version,content_hash,status,author,reviewer,reason,created_at,approved_at FROM skill_versions WHERE id=?", (version_id,)).fetchone()
        if not row:
            raise ValueError("Unknown skill version")
        keys = "id name version content_hash status author reviewer reason created_at approved_at".split()
        return dict(zip(keys, row))
