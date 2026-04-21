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
        # Migratie: voeg nieuwe kolommen toe als ze nog niet bestaan
        existing = {row[1] for row in c.execute("PRAGMA table_info(sessions)")}
        migrations = [
            ("flour_type",      "ALTER TABLE sessions ADD COLUMN flour_type TEXT"),
            ("hydration_pct",   "ALTER TABLE sessions ADD COLUMN hydration_pct INTEGER"),
            ("verdict",         "ALTER TABLE sessions ADD COLUMN verdict TEXT"),
            ("verdict_notes",   "ALTER TABLE sessions ADD COLUMN verdict_notes TEXT"),
            ("peak_speed_mm_h", "ALTER TABLE sessions ADD COLUMN peak_speed_mm_h REAL"),
            ("total_rise_mm",   "ALTER TABLE sessions ADD COLUMN total_rise_mm REAL"),
            ("ended_at",        "ALTER TABLE sessions ADD COLUMN ended_at REAL"),
        ]
        for col, sql in migrations:
            if col not in existing:
                c.execute(sql)
    print(f"[db] Database klaar: {config.DB_PATH}")


def start_session(baseline_mm: float, notes: str = "",
                  flour_type: str = None, hydration_pct: int = None) -> int:
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO sessions (started_at, baseline_mm, notes, flour_type, hydration_pct)
               VALUES (?,?,?,?,?)""",
            (time.time(), baseline_mm, notes, flour_type, hydration_pct),
        )
        return cur.lastrowid


def get_active_session():
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def end_session(session_id: int):
    with _conn() as c:
        rows = c.execute(
            "SELECT rise_mm, speed_mm_h FROM measurements WHERE session_id=?",
            (session_id,),
        ).fetchall()
        peak_speed = max((r["speed_mm_h"] or 0 for r in rows), default=0)
        total_rise = max((r["rise_mm"] or 0 for r in rows), default=0)
        c.execute(
            """UPDATE sessions
               SET ended_at=?, peak_speed_mm_h=?, total_rise_mm=?
               WHERE id=?""",
            (time.time(), peak_speed, total_rise, session_id),
        )


def list_unclosed_sessions() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def cleanup_orphan_sessions() -> int:
    cutoff = time.time() - 7 * 86400
    with _conn() as c:
        orphans = c.execute(
            """SELECT s.id FROM sessions s
               LEFT JOIN measurements m ON m.session_id = s.id
               WHERE s.ended_at IS NULL
               AND (m.id IS NULL OR s.started_at < ?)
               GROUP BY s.id""",
            (cutoff,),
        ).fetchall()
    count = 0
    for row in orphans:
        end_session(row["id"])
        count += 1
    return count


def list_sessions() -> list:
    with _conn() as c:
        rows = c.execute(
            """SELECT id, started_at, ended_at, baseline_mm, notes,
                      flour_type, hydration_pct, verdict, verdict_notes,
                      peak_speed_mm_h, total_rise_mm, oven_triggered
               FROM sessions ORDER BY id DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def set_session_verdict(session_id: int, verdict: str, notes: str = ""):
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET verdict=?, verdict_notes=? WHERE id=?",
            (verdict, notes, session_id),
        )


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


def get_measurements(session_id: int, limit: int = 2000) -> list:
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
