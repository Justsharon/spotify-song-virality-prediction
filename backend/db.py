import json
import os
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DATA_DIR = Path(__file__).resolve().parent / "data"
MAIN_DB_PATH = DATA_DIR / "virality.db"
CACHE_DB_PATH = DATA_DIR / "cache.db"

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", 60 * 60 * 24))

MAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    cache_key TEXT NOT NULL,
    genre TEXT NOT NULL,
    is_viral INTEGER NOT NULL,
    viral_probability REAL NOT NULL,
    served_from_cache INTEGER NOT NULL DEFAULT 0,
    features TEXT NOT NULL,
    model_latency_ms REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_predictions_created_at ON predictions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_cache_key ON predictions (cache_key);
"""

CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    cache_key TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    genre TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0,
    last_hit_at REAL
);
CREATE INDEX IF NOT EXISTS idx_cache_expires_at ON cache (expires_at);

CREATE TABLE IF NOT EXISTS cache_meta (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO cache_meta (key, value) VALUES ('hits', 0), ('misses', 0), ('evictions', 0);
"""


def _connect(path: Path, durable: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(f"PRAGMA synchronous={'NORMAL' if durable else 'OFF'}")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


@contextmanager
def connect(path: Path, durable: bool = False) -> Iterator[sqlite3.Connection]:
    connection = _connect(path, durable)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with connect(MAIN_DB_PATH, durable=True) as connection:
        connection.executescript(MAIN_SCHEMA)
    with connect(CACHE_DB_PATH) as connection:
        connection.executescript(CACHE_SCHEMA)
    _ensure_writer()


def _bump_meta(connection: sqlite3.Connection, key: str, amount: int = 1) -> None:
    connection.execute(
        "UPDATE cache_meta SET value = value + ? WHERE key = ?", (amount, key)
    )


def get_cached(cache_key: str, ttl: int = CACHE_TTL_SECONDS) -> dict[str, Any] | None:
    now = time.time()
    with connect(CACHE_DB_PATH) as connection:
        row = connection.execute(
            "SELECT response, expires_at FROM cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()

        if row is None:
            _bump_meta(connection, "misses")
            return None

        if row["expires_at"] < now:
            connection.execute("DELETE FROM cache WHERE cache_key = ?", (cache_key,))
            _bump_meta(connection, "misses")
            _bump_meta(connection, "evictions")
            return None

        connection.execute(
            "UPDATE cache SET hits = hits + 1, last_hit_at = ? WHERE cache_key = ?",
            (now, cache_key),
        )
        _bump_meta(connection, "hits")
        return json.loads(row["response"])


def set_cached(
    cache_key: str, response: dict[str, Any], genre: str, ttl: int = CACHE_TTL_SECONDS
) -> None:
    now = time.time()
    with connect(CACHE_DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO cache (cache_key, response, genre, created_at, expires_at, hits, last_hit_at)
            VALUES (?, ?, ?, ?, ?, 0, NULL)
            ON CONFLICT(cache_key) DO UPDATE SET
                response = excluded.response,
                genre = excluded.genre,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
            """,
            (cache_key, json.dumps(response), genre, now, now + ttl),
        )


def purge_expired(ttl: int = CACHE_TTL_SECONDS) -> int:
    with connect(CACHE_DB_PATH) as connection:
        cursor = connection.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
        _bump_meta(connection, "evictions", cursor.rowcount)
        return cursor.rowcount


def clear_cache() -> int:
    with connect(CACHE_DB_PATH) as connection:
        cursor = connection.execute("DELETE FROM cache")
        connection.execute("UPDATE cache_meta SET value = 0 WHERE key IN ('hits','misses','evictions')")
        return cursor.rowcount


def cache_stats(ttl: int = CACHE_TTL_SECONDS) -> dict[str, Any]:
    with connect(CACHE_DB_PATH) as connection:
        entries = connection.execute("SELECT COUNT(*) AS n FROM cache").fetchone()["n"]
        meta = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key, value FROM cache_meta")
        }
        top = [
            {"genre": row["genre"], "hits": row["hits"], "cache_key": row["cache_key"]}
            for row in connection.execute(
                "SELECT genre, hits, cache_key FROM cache ORDER BY hits DESC, created_at DESC LIMIT 5"
            )
        ]

    hits = meta.get("hits", 0)
    misses = meta.get("misses", 0)
    total = hits + misses
    return {
        "entries": entries,
        "hits": hits,
        "misses": misses,
        "evictions": meta.get("evictions", 0),
        "hit_rate": round(hits / total, 4) if total else 0.0,
        "ttl_seconds": ttl,
        "top_entries": top,
    }


_WRITE_QUEUE: "queue.Queue[tuple | None]" = queue.Queue()
_WRITER_THREAD: threading.Thread | None = None
_WRITER_LOCK = threading.Lock()

_INSERT_PREDICTION = """
INSERT INTO predictions
    (created_at, cache_key, genre, is_viral, viral_probability,
     served_from_cache, features, model_latency_ms)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


def _writer_loop() -> None:
    while True:
        item = _WRITE_QUEUE.get()
        if item is None:
            _WRITE_QUEUE.task_done()
            return

        batch = [item]
        while True:
            try:
                extra = _WRITE_QUEUE.get_nowait()
            except queue.Empty:
                break
            if extra is None:
                _WRITE_QUEUE.task_done()
                extra = None
                break
            batch.append(extra)

        try:
            with connect(MAIN_DB_PATH, durable=True) as connection:
                connection.executemany(_INSERT_PREDICTION, batch)
        finally:
            for _ in batch:
                _WRITE_QUEUE.task_done()


def _ensure_writer() -> None:
    global _WRITER_THREAD
    if _WRITER_THREAD is not None and _WRITER_THREAD.is_alive():
        return
    with _WRITER_LOCK:
        if _WRITER_THREAD is None or not _WRITER_THREAD.is_alive():
            _WRITER_THREAD = threading.Thread(
                target=_writer_loop, name="prediction-writer", daemon=True
            )
            _WRITER_THREAD.start()


def flush_log() -> None:
    _WRITE_QUEUE.join()


def record_prediction(
    cache_key: str,
    genre: str,
    response: dict[str, Any],
    features: dict[str, Any],
    served_from_cache: bool,
    model_latency_ms: float = 0.0,
) -> None:
    _ensure_writer()
    _WRITE_QUEUE.put(
        (
            time.time(),
            cache_key,
            genre,
            int(response["is_viral"]),
            float(response["viral_probability"]),
            int(served_from_cache),
            json.dumps(features),
            float(model_latency_ms),
        )
    )


def recent_predictions(limit: int = 20) -> list[dict[str, Any]]:
    flush_log()
    with connect(MAIN_DB_PATH, durable=True) as connection:
        rows = connection.execute(
            """
            SELECT id, created_at, genre, is_viral, viral_probability,
                   served_from_cache, model_latency_ms
            FROM predictions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def prediction_stats() -> dict[str, Any]:
    flush_log()
    with connect(MAIN_DB_PATH, durable=True) as connection:
        total = connection.execute("SELECT COUNT(*) AS n FROM predictions").fetchone()["n"]
        viral = connection.execute(
            "SELECT COUNT(*) AS n FROM predictions WHERE is_viral = 1"
        ).fetchone()["n"]
        cached = connection.execute(
            "SELECT COUNT(*) AS n FROM predictions WHERE served_from_cache = 1"
        ).fetchone()["n"]
        avg_latency = connection.execute(
            "SELECT AVG(model_latency_ms) AS ms FROM predictions WHERE served_from_cache = 0"
        ).fetchone()["ms"]
    return {
        "total_predictions": total,
        "viral_predictions": viral,
        "non_viral_predictions": total - viral,
        "served_from_cache": cached,
        "avg_model_latency_ms": round(avg_latency, 3) if avg_latency else 0.0,
    }
