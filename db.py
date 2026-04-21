import sqlite3
import time
import config


def _conn():
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at      REAL    NOT NULL,
                baseline_mm     REAL,
                notes           TEXT,
                oven_triggered  INTEGER DEFAULT 0,
                oven_at         REAL
            );
            CREATE TABLE IF NOT EXISTS measurements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL REFERENCES sessions(id),
                ts          REAL    NOT NULL,
                distance_mm INTEGER NOT NULL,
                rise_mm     REAL,
                rise_pct    REAL,
                speed_mm_h  REAL
            );
        """)
    print(f"[db] Database klaar: {config.DB_PATH}")


def start_session(baseline_mm: float, notes: str = "") -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO sessions (started_at, baseline_mm, notes) VALUES (?,?,?)",
            (time.time(), baseline_mm, notes),
        )
        return cur.lastrowid


def get_active_session():
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def mark_oven_triggered(session_id: int):
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET oven_triggered=1, oven_at=? WHERE id=?",
            (time.time(), session_id),
        )


def log_measurement(session_id, distance_mm, rise_mm, rise_pct, speed_mm_h):
    with _conn() as c:
        c.execute(
            """INSERT INTO measurements
               (session_id, ts, distance_mm, rise_mm, rise_pct, speed_mm_h)
               VALUES (?,?,?,?,?,?)""",
            (session_id, time.time(), distance_mm, rise_mm, rise_pct, speed_mm_h),
        )


def get_measurements(session_id: int, limit: int = 500) -> list:
    with _conn() as c:
        rows = c.execute(
            """SELECT ts, distance_mm, rise_mm, rise_pct, speed_mm_h
               FROM measurements WHERE session_id=?
               ORDER BY ts ASC LIMIT ?""",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_last_n(session_id: int, n: int = 20) -> list:
    with _conn() as c:
        rows = c.execute(
            """SELECT ts, distance_mm, rise_mm, rise_pct, speed_mm_h
               FROM measurements WHERE session_id=?
               ORDER BY ts DESC LIMIT ?""",
            (session_id, n),
        ).fetchall()
        return list(reversed([dict(r) for r in rows]))
