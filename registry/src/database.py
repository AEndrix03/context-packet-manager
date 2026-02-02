from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS packages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  package_id INTEGER NOT NULL,
  version TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  object_key TEXT NOT NULL,
  checksum TEXT,
  published_at TEXT NOT NULL,
  yanked INTEGER NOT NULL DEFAULT 0,
  manifest_json TEXT,
  FOREIGN KEY(package_id) REFERENCES packages(id) ON DELETE CASCADE,
  UNIQUE(package_id, version)
);

CREATE INDEX IF NOT EXISTS idx_versions_sha256 ON versions(sha256);
CREATE INDEX IF NOT EXISTS idx_versions_pkg_ver ON versions(package_id, version);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  action TEXT NOT NULL,
  package TEXT,
  version TEXT,
  sha256 TEXT,
  remote TEXT
);
"""


@dataclass(frozen=True)
class PackageVersionRow:
    name: str
    version: str
    sha256: str
    size_bytes: int
    object_key: str
    checksum: str | None
    published_at: str
    yanked: int
    manifest_json: str | None


class RegistryDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def _ensure_package(self, conn: sqlite3.Connection, name: str) -> int:
        row = conn.execute("SELECT id FROM packages WHERE name = ?", (name,)).fetchone()
        if row:
            return int(row["id"])
        conn.execute(
            "INSERT INTO packages(name, created_at) VALUES (?, ?)",
            (name, utcnow_iso()),
        )
        return int(conn.execute("SELECT id FROM packages WHERE name = ?", (name,)).fetchone()["id"])

    def log(self, action: str, package: str | None = None, version: str | None = None, sha256: str | None = None, remote: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO audit_log(ts, action, package, version, sha256, remote) VALUES (?, ?, ?, ?, ?, ?)",
                (utcnow_iso(), action, package, version, sha256, remote),
            )
            conn.commit()

    def exists(self, name: str, version: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM versions v
                JOIN packages p ON p.id = v.package_id
                WHERE p.name = ? AND v.version = ? AND v.yanked = 0
                """,
                (name, version),
            ).fetchone()
            return row is not None

    def get_version(self, name: str, version: str) -> PackageVersionRow | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT p.name, v.version, v.sha256, v.size_bytes, v.object_key, v.checksum, v.published_at, v.yanked, v.manifest_json
                FROM versions v
                JOIN packages p ON p.id = v.package_id
                WHERE p.name = ? AND v.version = ?
                """,
                (name, version),
            ).fetchone()
            if not row:
                return None
            return PackageVersionRow(
                name=row["name"],
                version=row["version"],
                sha256=row["sha256"],
                size_bytes=int(row["size_bytes"]),
                object_key=row["object_key"],
                checksum=row["checksum"],
                published_at=row["published_at"],
                yanked=int(row["yanked"]),
                manifest_json=row["manifest_json"],
            )

    def list_versions(self, name: str, include_yanked: bool = False) -> list[dict[str, Any]]:
        with self.connect() as conn:
            where = "p.name = ?"
            if not include_yanked:
                where += " AND v.yanked = 0"
            rows = conn.execute(
                f"""
                SELECT v.version, v.sha256, v.size_bytes, v.published_at, v.yanked
                FROM versions v
                JOIN packages p ON p.id = v.package_id
                WHERE {where}
                ORDER BY v.published_at DESC
                """,
                (name,),
            ).fetchall()
            return [dict(r) for r in rows]

    def insert_version(
        self,
        name: str,
        version: str,
        sha256: str,
        size_bytes: int,
        object_key: str,
        checksum: str | None = None,
        manifest_json: str | None = None,
    ) -> None:
        with self.connect() as conn:
            pkg_id = self._ensure_package(conn, name)
            conn.execute(
                """
                INSERT INTO versions(package_id, version, sha256, size_bytes, object_key, checksum, published_at, yanked, manifest_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (pkg_id, version, sha256, size_bytes, object_key, checksum, utcnow_iso(), manifest_json),
            )
            conn.commit()

    def yank(self, name: str, version: str, yanked: bool = True) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE versions
                SET yanked = ?
                WHERE id IN (
                    SELECT v.id
                    FROM versions v JOIN packages p ON p.id = v.package_id
                    WHERE p.name = ? AND v.version = ?
                )
                """,
                (1 if yanked else 0, name, version),
            )
            conn.commit()
            return cur.rowcount > 0

    def delete_version(self, name: str, version: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM versions
                WHERE id IN (
                    SELECT v.id
                    FROM versions v
                    JOIN packages p ON p.id = v.package_id
                    WHERE p.name = ? AND v.version = ?
                )
                """,
                (name, version),
            )
            conn.commit()
