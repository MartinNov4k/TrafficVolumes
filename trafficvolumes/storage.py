"""The project file: a single SQLite database holding the network and the counts.

One ``*.tvol`` file contains the imported link directions, the definition of the
values to collect, everything the surveyor has typed in so far and an audit
trail of the changes.  Handing that one file to somebody is all it takes to hand
over the work, and it is also what comes back when the survey is finished.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .model import DEFAULT_FIELDS, LinkDirection, ValueField, direction_key

SCHEMA_VERSION = "1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS fields (
    name       TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    value_type TEXT NOT NULL,
    unit       TEXT NOT NULL DEFAULT '',
    required   INTEGER NOT NULL DEFAULT 0,
    position   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS links (
    dir_key   TEXT PRIMARY KEY,
    link_no   TEXT NOT NULL,
    from_node TEXT NOT NULL,
    to_node   TEXT NOT NULL,
    name      TEXT NOT NULL DEFAULT '',
    type_no   TEXT NOT NULL DEFAULT '',
    length    REAL,
    capacity  REAL,
    attrs     TEXT NOT NULL DEFAULT '{}',
    geom      TEXT NOT NULL,
    minx REAL NOT NULL, miny REAL NOT NULL, maxx REAL NOT NULL, maxy REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_links_no ON links(link_no);
CREATE INDEX IF NOT EXISTS idx_links_bbox ON links(minx, maxx, miny, maxy);
CREATE TABLE IF NOT EXISTS link_values (
    dir_key TEXT NOT NULL,
    field   TEXT NOT NULL,
    value   TEXT,
    PRIMARY KEY (dir_key, field)
);
CREATE TABLE IF NOT EXISTS entries (
    dir_key    TEXT PRIMARY KEY,
    status     TEXT NOT NULL DEFAULT 'filled',
    note       TEXT NOT NULL DEFAULT '',
    surveyor   TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    dir_key   TEXT NOT NULL,
    field     TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    surveyor  TEXT NOT NULL DEFAULT '',
    ts        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_dir ON history(dir_key);
"""

#: Guard rail so that one careless request cannot try to draw a whole country.
MAX_FEATURES = 40000


class StorageError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Stats:
    total: int
    filled: int
    flagged: int

    @property
    def remaining(self) -> int:
        return self.total - self.filled

    def to_dict(self) -> Dict[str, int]:
        return {
            "total": self.total,
            "filled": self.filled,
            "flagged": self.flagged,
            "remaining": self.remaining,
        }


class Project:
    """Read/write access to one project file."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = os.fspath(path)
        self._local = threading.local()
        self._write_lock = threading.Lock()

    # -- connection handling --------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- creation -------------------------------------------------------------

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        links: Sequence[LinkDirection],
        *,
        fields: Sequence[ValueField] = DEFAULT_FIELDS,
        name: str = "",
        crs: str = "LOCAL",
        coord_mode: str = "local",
        source: str = "",
        overwrite: bool = False,
    ) -> "Project":
        target = os.fspath(path)
        if os.path.exists(target):
            if not overwrite:
                raise StorageError(f"{target} already exists (use --force to replace it).")
            os.remove(target)
        project = cls(target)
        conn = project.conn
        conn.executescript(_SCHEMA)
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                [
                    ("schema_version", SCHEMA_VERSION),
                    ("name", name or os.path.splitext(os.path.basename(target))[0]),
                    ("crs", crs),
                    ("coord_mode", coord_mode),
                    ("source", source),
                    ("created_at", _now()),
                ],
            )
            project._write_fields(conn, fields)
            project._write_links(conn, links)
        return project

    @staticmethod
    def _write_fields(conn: sqlite3.Connection, fields: Sequence[ValueField]) -> None:
        if not fields:
            raise StorageError("A project needs at least one value field.")
        conn.execute("DELETE FROM fields")
        conn.executemany(
            "INSERT INTO fields(name, label, value_type, unit, required, position) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (f.name, f.label, f.value_type, f.unit, int(f.required), index)
                for index, f in enumerate(fields)
            ],
        )

    @staticmethod
    def _write_links(conn: sqlite3.Connection, links: Sequence[LinkDirection]) -> None:
        seen: set[str] = set()
        rows = []
        duplicates = 0
        for link in links:
            if link.key in seen:
                duplicates += 1
                continue
            seen.add(link.key)
            minx, miny, maxx, maxy = link.bbox()
            rows.append(
                (
                    link.key,
                    link.link_no,
                    link.from_node,
                    link.to_node,
                    link.name,
                    link.type_no,
                    link.length,
                    link.capacity,
                    json.dumps(link.attrs, ensure_ascii=False),
                    json.dumps([[round(x, 7), round(y, 7)] for x, y in link.geometry]),
                    minx,
                    miny,
                    maxx,
                    maxy,
                )
            )
        conn.executemany(
            "INSERT INTO links(dir_key, link_no, from_node, to_node, name, type_no, length, "
            "capacity, attrs, geom, minx, miny, maxx, maxy) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        if duplicates:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('duplicate_rows', ?)",
                (str(duplicates),),
            )

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> "Project":
        target = os.fspath(path)
        if not os.path.exists(target):
            raise StorageError(f"Project file {target} does not exist.")
        project = cls(target)
        try:
            version = project.meta().get("schema_version")
        except sqlite3.DatabaseError as exc:
            raise StorageError(f"{target} is not a TrafficVolumes project file.") from exc
        if version != SCHEMA_VERSION:
            raise StorageError(
                f"{target} was written by another version of TrafficVolumes "
                f"(schema {version!r}, expected {SCHEMA_VERSION!r})."
            )
        return project

    # -- metadata -------------------------------------------------------------

    def meta(self) -> Dict[str, str]:
        return {row["key"]: row["value"] for row in self.conn.execute("SELECT key, value FROM meta")}

    def set_meta(self, key: str, value: str) -> None:
        with self._write_lock, self.conn as conn:
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    def fields(self) -> List[ValueField]:
        rows = self.conn.execute(
            "SELECT name, label, value_type, unit, required, position FROM fields ORDER BY position"
        )
        return [
            ValueField(
                name=row["name"],
                label=row["label"],
                value_type=row["value_type"],
                unit=row["unit"],
                required=bool(row["required"]),
                position=row["position"],
            )
            for row in rows
        ]

    def stats(self) -> Stats:
        total = self.conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        filled = self.conn.execute(
            "SELECT COUNT(DISTINCT dir_key) FROM link_values WHERE value IS NOT NULL AND value != ''"
        ).fetchone()[0]
        flagged = self.conn.execute(
            "SELECT COUNT(*) FROM entries WHERE status = 'flagged'"
        ).fetchone()[0]
        return Stats(total=total, filled=filled, flagged=flagged)

    def bounds(self) -> Optional[Tuple[float, float, float, float]]:
        row = self.conn.execute(
            "SELECT MIN(minx), MIN(miny), MAX(maxx), MAX(maxy) FROM links"
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return (row[0], row[1], row[2], row[3])

    # -- querying -------------------------------------------------------------

    def query_links(
        self,
        *,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        search: str = "",
        only_empty: bool = False,
        only_flagged: bool = False,
        limit: int = MAX_FEATURES,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """Return link directions with their current values, plus a truncation flag."""
        where: List[str] = []
        params: List[Any] = []
        if bbox:
            where.append("l.maxx >= ? AND l.minx <= ? AND l.maxy >= ? AND l.miny <= ?")
            params.extend([bbox[0], bbox[2], bbox[1], bbox[3]])
        if search:
            needle = f"%{search.strip().lower()}%"
            where.append(
                "(LOWER(l.name) LIKE ? OR LOWER(l.link_no) LIKE ? "
                "OR LOWER(l.from_node) LIKE ? OR LOWER(l.to_node) LIKE ?)"
            )
            params.extend([needle] * 4)
        if only_empty:
            where.append(
                "NOT EXISTS (SELECT 1 FROM link_values v WHERE v.dir_key = l.dir_key "
                "AND v.value IS NOT NULL AND v.value != '')"
            )
        if only_flagged:
            where.append(
                "EXISTS (SELECT 1 FROM entries e WHERE e.dir_key = l.dir_key AND e.status = 'flagged')"
            )
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        limit = max(1, min(int(limit), MAX_FEATURES))
        rows = self.conn.execute(
            f"SELECT l.* FROM links l{clause} ORDER BY l.link_no, l.from_node LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        truncated = len(rows) > limit
        rows = rows[:limit]

        keys = [row["dir_key"] for row in rows]
        values = self._values_for(keys)
        entries = self._entries_for(keys)
        result = [self._row_to_dict(row, values, entries) for row in rows]
        return result, truncated

    def _values_for(self, keys: Sequence[str]) -> Dict[str, Dict[str, str]]:
        out: Dict[str, Dict[str, str]] = {}
        for chunk in _chunks(keys, 400):
            placeholders = ",".join("?" * len(chunk))
            for row in self.conn.execute(
                f"SELECT dir_key, field, value FROM link_values WHERE dir_key IN ({placeholders})",
                tuple(chunk),
            ):
                out.setdefault(row["dir_key"], {})[row["field"]] = row["value"]
        return out

    def _entries_for(self, keys: Sequence[str]) -> Dict[str, sqlite3.Row]:
        out: Dict[str, sqlite3.Row] = {}
        for chunk in _chunks(keys, 400):
            placeholders = ",".join("?" * len(chunk))
            for row in self.conn.execute(
                f"SELECT * FROM entries WHERE dir_key IN ({placeholders})", tuple(chunk)
            ):
                out[row["dir_key"]] = row
        return out

    def _row_to_dict(
        self,
        row: sqlite3.Row,
        values: Dict[str, Dict[str, str]],
        entries: Dict[str, sqlite3.Row],
    ) -> Dict[str, Any]:
        entry = entries.get(row["dir_key"])
        return {
            "key": row["dir_key"],
            "link_no": row["link_no"],
            "from_node": row["from_node"],
            "to_node": row["to_node"],
            "name": row["name"],
            "type_no": row["type_no"],
            "length": row["length"],
            "capacity": row["capacity"],
            "geom": json.loads(row["geom"]),
            "values": values.get(row["dir_key"], {}),
            "note": entry["note"] if entry else "",
            "status": entry["status"] if entry else "empty",
            "surveyor": entry["surveyor"] if entry else "",
            "updated_at": entry["updated_at"] if entry else None,
        }

    def get_link(self, dir_key: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM links WHERE dir_key = ?", (dir_key,)).fetchone()
        if row is None:
            return None
        data = self._row_to_dict(row, self._values_for([dir_key]), self._entries_for([dir_key]))
        data["attrs"] = json.loads(row["attrs"])
        reverse = self.conn.execute(
            "SELECT dir_key FROM links WHERE link_no = ? AND from_node = ? AND to_node = ?",
            (row["link_no"], row["to_node"], row["from_node"]),
        ).fetchone()
        data["reverse_key"] = reverse["dir_key"] if reverse else None
        return data

    def history(self, dir_key: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT field, old_value, new_value, surveyor, ts FROM history "
            "WHERE dir_key = ? ORDER BY id DESC LIMIT ?",
            (dir_key, limit),
        )
        return [dict(row) for row in rows]

    # -- writing --------------------------------------------------------------

    def set_values(
        self,
        dir_key: str,
        raw_values: Dict[str, Any],
        *,
        surveyor: str = "",
        note: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store the values typed in for one direction and record the change."""
        fields = {f.name: f for f in self.fields()}
        unknown = [name for name in raw_values if name.upper() not in fields]
        if unknown:
            raise StorageError(f"Unknown value field(s): {', '.join(sorted(unknown))}")

        cleaned: Dict[str, Optional[Any]] = {}
        for name, field in fields.items():
            if name in raw_values or name.lower() in raw_values:
                raw = raw_values.get(name, raw_values.get(name.lower()))
                cleaned[name] = field.coerce(raw)

        with self._write_lock, self.conn as conn:
            exists = conn.execute(
                "SELECT 1 FROM links WHERE dir_key = ?", (dir_key,)
            ).fetchone()
            if exists is None:
                raise StorageError(f"Link direction {dir_key!r} is not part of this project.")

            previous = {
                row["field"]: row["value"]
                for row in conn.execute(
                    "SELECT field, value FROM link_values WHERE dir_key = ?", (dir_key,)
                )
            }
            timestamp = _now()
            for name, value in cleaned.items():
                text = None if value is None else str(value)
                if previous.get(name) == text:
                    continue
                if text is None:
                    conn.execute(
                        "DELETE FROM link_values WHERE dir_key = ? AND field = ?", (dir_key, name)
                    )
                else:
                    conn.execute(
                        "INSERT INTO link_values(dir_key, field, value) VALUES (?, ?, ?) "
                        "ON CONFLICT(dir_key, field) DO UPDATE SET value = excluded.value",
                        (dir_key, name, text),
                    )
                conn.execute(
                    "INSERT INTO history(dir_key, field, old_value, new_value, surveyor, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (dir_key, name, previous.get(name), text, surveyor, timestamp),
                )

            remaining = conn.execute(
                "SELECT COUNT(*) FROM link_values WHERE dir_key = ? AND value IS NOT NULL "
                "AND value != ''",
                (dir_key,),
            ).fetchone()[0]
            new_status = status or ("filled" if remaining else "empty")
            if new_status == "empty" and not note:
                conn.execute("DELETE FROM entries WHERE dir_key = ?", (dir_key,))
            else:
                current = conn.execute(
                    "SELECT note FROM entries WHERE dir_key = ?", (dir_key,)
                ).fetchone()
                conn.execute(
                    "INSERT INTO entries(dir_key, status, note, surveyor, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(dir_key) DO UPDATE SET "
                    "status = excluded.status, note = excluded.note, "
                    "surveyor = excluded.surveyor, updated_at = excluded.updated_at",
                    (
                        dir_key,
                        new_status,
                        (current["note"] if current and note is None else (note or "")),
                        surveyor,
                        timestamp,
                    ),
                )
        result = self.get_link(dir_key)
        assert result is not None
        return result

    def clear_values(self, dir_key: str, *, surveyor: str = "") -> Dict[str, Any]:
        empty = {f.name: None for f in self.fields()}
        return self.set_values(dir_key, empty, surveyor=surveyor, note="", status="empty")

    def set_fields(self, fields: Sequence[ValueField]) -> None:
        """Replace the value definitions, keeping values of fields that survive."""
        keep = {f.name for f in fields}
        with self._write_lock, self.conn as conn:
            self._write_fields(conn, fields)
            placeholders = ",".join("?" * len(keep)) or "''"
            conn.execute(
                f"DELETE FROM link_values WHERE field NOT IN ({placeholders})", tuple(keep)
            )

    # -- bulk access ----------------------------------------------------------

    def iter_entered(self) -> Iterator[Dict[str, Any]]:
        """Yield every direction that carries at least one value, in Visum key order."""
        rows = self.conn.execute(
            "SELECT l.dir_key, l.link_no, l.from_node, l.to_node, l.name, "
            "       e.note, e.surveyor, e.updated_at "
            "FROM links l LEFT JOIN entries e ON e.dir_key = l.dir_key "
            "WHERE EXISTS (SELECT 1 FROM link_values v WHERE v.dir_key = l.dir_key "
            "              AND v.value IS NOT NULL AND v.value != '') "
            "ORDER BY CAST(l.link_no AS INTEGER), l.link_no, l.from_node"
        ).fetchall()
        keys = [row["dir_key"] for row in rows]
        values = self._values_for(keys)
        for row in rows:
            item = dict(row)
            item["values"] = values.get(row["dir_key"], {})
            yield item

    def iter_all_directions(self) -> Iterator[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT l.dir_key, l.link_no, l.from_node, l.to_node, l.name, "
            "       e.note, e.surveyor, e.updated_at "
            "FROM links l LEFT JOIN entries e ON e.dir_key = l.dir_key "
            "ORDER BY CAST(l.link_no AS INTEGER), l.link_no, l.from_node"
        ).fetchall()
        keys = [row["dir_key"] for row in rows]
        values = self._values_for(keys)
        for row in rows:
            item = dict(row)
            item["values"] = values.get(row["dir_key"], {})
            yield item

    def import_values(
        self,
        records: Iterable[Tuple[str, str, str, Dict[str, Any]]],
        *,
        surveyor: str = "import",
        overwrite: bool = True,
    ) -> Tuple[int, int]:
        """Merge values coming from another project file or a CSV.

        Returns the number of updated directions and the number of records whose
        link direction is unknown in this project.
        """
        updated = 0
        missing = 0
        for link_no, from_node, to_node, values in records:
            key = direction_key(link_no, from_node, to_node)
            if self.conn.execute("SELECT 1 FROM links WHERE dir_key = ?", (key,)).fetchone() is None:
                missing += 1
                continue
            if not overwrite:
                existing = self.conn.execute(
                    "SELECT 1 FROM link_values WHERE dir_key = ? AND value IS NOT NULL "
                    "AND value != ''",
                    (key,),
                ).fetchone()
                if existing:
                    continue
            self.set_values(key, values, surveyor=surveyor)
            updated += 1
        return updated, missing


def _chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
