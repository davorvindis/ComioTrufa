"""SQLite database module for ComioTrufa."""

import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connect()
        self.initialize()

    def _connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def initialize(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                previous_state TEXT NOT NULL,
                new_state TEXT NOT NULL,
                event_type TEXT NOT NULL,
                confidence REAL,
                image_path TEXT,
                notified INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                state TEXT NOT NULL,
                confidence REAL,
                image_path TEXT,
                raw_response TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                meals_detected INTEGER DEFAULT 0,
                first_meal_time TEXT,
                last_meal_time TEXT,
                refills INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON readings(timestamp);
        """)
        self.conn.commit()

    def save_reading(self, state: str, confidence: float, image_path: str, raw_response: str = ""):
        """Save a raw reading from the vision analysis."""
        self.conn.execute(
            "INSERT INTO readings (state, confidence, image_path, raw_response) VALUES (?, ?, ?, ?)",
            (state, confidence, image_path, raw_response),
        )
        self.conn.commit()

    def save_event(self, previous_state: str, new_state: str, event_type: str,
                   confidence: float, image_path: str) -> int:
        """Save a state transition event. Returns the event ID."""
        cursor = self.conn.execute(
            "INSERT INTO events (previous_state, new_state, event_type, confidence, image_path) "
            "VALUES (?, ?, ?, ?, ?)",
            (previous_state, new_state, event_type, confidence, image_path),
        )
        self.conn.commit()

        # Update daily stats
        if event_type == "dog_ate":
            self._update_daily_stats_meal()
        elif event_type == "bowl_refilled":
            self._update_daily_stats_refill()

        return cursor.lastrowid

    def mark_notified(self, event_id: int):
        """Mark an event as notified via Telegram."""
        self.conn.execute("UPDATE events SET notified = 1 WHERE id = ?", (event_id,))
        self.conn.commit()

    def get_last_state(self) -> Optional[str]:
        """Get the most recent known state."""
        row = self.conn.execute(
            "SELECT new_state FROM events ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row:
            return row["new_state"]
        return None

    def get_last_reading(self) -> Optional[dict]:
        """Get the most recent reading."""
        row = self.conn.execute(
            "SELECT * FROM readings ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_recent_events(self, limit: int = 10) -> list[dict]:
        """Get recent state change events."""
        rows = self.conn.execute(
            "SELECT * FROM events WHERE event_type IN ('dog_ate', 'bowl_refilled') "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_today_stats(self) -> dict:
        """Get today's statistics."""
        today = date.today().isoformat()
        row = self.conn.execute(
            "SELECT * FROM daily_stats WHERE date = ?", (today,)
        ).fetchone()
        if row:
            return dict(row)
        return {"date": today, "meals_detected": 0, "first_meal_time": None,
                "last_meal_time": None, "refills": 0}

    def get_week_stats(self) -> list[dict]:
        """Get the last 7 days of statistics."""
        rows = self.conn.execute(
            "SELECT * FROM daily_stats ORDER BY date DESC LIMIT 7"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_last_eat_time(self) -> Optional[str]:
        """Get the timestamp of the last 'dog_ate' event."""
        row = self.conn.execute(
            "SELECT timestamp FROM events WHERE event_type = 'dog_ate' "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["timestamp"] if row else None

    def _update_daily_stats_meal(self):
        today = date.today().isoformat()
        now = datetime.now().strftime("%H:%M:%S")
        self.conn.execute("""
            INSERT INTO daily_stats (date, meals_detected, first_meal_time, last_meal_time)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                meals_detected = meals_detected + 1,
                first_meal_time = COALESCE(first_meal_time, ?),
                last_meal_time = ?
        """, (today, now, now, now, now))
        self.conn.commit()

    def _update_daily_stats_refill(self):
        today = date.today().isoformat()
        self.conn.execute("""
            INSERT INTO daily_stats (date, refills)
            VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET refills = refills + 1
        """, (today,))
        self.conn.commit()

    def cleanup_old_images(self, keep_days: int, images_dir: str):
        """Delete image files older than keep_days."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()

        rows = self.conn.execute(
            "SELECT image_path FROM readings WHERE timestamp < ? AND image_path IS NOT NULL",
            (cutoff,),
        ).fetchall()

        for row in rows:
            path = Path(row["image_path"])
            if path.exists():
                path.unlink()

        # Clean up old readings (keep events forever)
        self.conn.execute("DELETE FROM readings WHERE timestamp < ?", (cutoff,))
        self.conn.commit()

    def close(self):
        self.conn.close()
